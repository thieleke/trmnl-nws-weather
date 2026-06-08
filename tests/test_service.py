import re
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

from trmnl_nws_weather import service
from trmnl_nws_weather.config import Device, Settings, Theme, TimeFormat, Units

DOCS = Path(__file__).resolve().parents[1] / "docs"
SAMPLE_XML = DOCS / "MapClick.php.xml"
SAMPLE_JSON = DOCS / "MapClick.json"

# img_<lat>_<lon>_<width>_<height>_<bit_depth>_<l|d>_<i|m>_<12|24>_<unix-ts>.png
FILENAME_RE = re.compile(
    r"^img_-?\d+\.\d{4}_-?\d+\.\d{4}_\d+_\d+_\d+_[ld]_[im]_(?:12|24)_\d+\.png$")

# Default (OG, light, imperial, 12-hour) options fragment of the cache tag.
OG_OPTS = "800_480_2_l_i_12"


def _settings(tmp_path) -> Settings:
    return replace(Settings(), output_dir=tmp_path)


def test_offline_render_returns_json_and_writes_file(tmp_path):
    settings = _settings(tmp_path)
    result = service.render_once(settings, xml_path=SAMPLE_XML, obs_path=SAMPLE_JSON)

    assert result["cached"] is False
    assert FILENAME_RE.match(result["filename"])
    assert "Intercourse" in result["description"]

    out = tmp_path / result["filename"]
    assert out.exists()
    # Description is embedded in the PNG so cache hits can report it.
    assert Image.open(out).info.get("Description") == result["description"]


def test_filename_embeds_panel_geometry(tmp_path):
    settings = replace(_settings(tmp_path), device=Device.X)
    result = service.render_once(settings, xml_path=SAMPLE_XML, obs_path=SAMPLE_JSON)
    assert FILENAME_RE.match(result["filename"])
    # The X panel's width/height/bit_depth appear in the name (before the ts).
    assert "_1872_1404_4_" in result["filename"]


def test_cache_hit_serves_existing_image(tmp_path):
    settings = _settings(tmp_path)
    first = service.render_once(settings, xml_path=SAMPLE_XML, obs_path=SAMPLE_JSON)

    # Live request (xml_path None) with caching: must return the cached file
    # without any network access, because a fresh image already exists.
    cached = service.render_once(settings, use_cache=True)
    assert cached["cached"] is True
    assert cached["filename"] == first["filename"]
    assert cached["description"] == first["description"]


def test_no_cache_bypasses_existing_image(tmp_path):
    settings = _settings(tmp_path)
    service.render_once(settings, xml_path=SAMPLE_XML, obs_path=SAMPLE_JSON)

    # use_cache=False always renders (offline here to avoid the network).
    result = service.render_once(settings, xml_path=SAMPLE_XML, use_cache=False)
    assert result["cached"] is False


def test_find_cached_window_and_coords(tmp_path):
    now = int(time.time())
    tag = f"40.0404_-76.3042_{OG_OPTS}"
    (tmp_path / f"img_{tag}_{now}.png").write_bytes(b"x")

    assert service.find_cached(tmp_path, tag, now, 900) is not None
    # Just outside the 15-minute window:
    assert service.find_cached(tmp_path, tag, now + 901, 900) is None
    # Different coordinates:
    assert service.find_cached(tmp_path, f"10.0000_20.0000_{OG_OPTS}", now, 900) is None


def test_find_cached_isolated_by_panel_geometry(tmp_path):
    # An image rendered for the OG panel must not be served for an X-panel
    # request made at the same moment (different width/height/bit depth).
    now = int(time.time())
    (tmp_path / f"img_40.0404_-76.3042_{OG_OPTS}_{now}.png").write_bytes(b"x")

    assert service.find_cached(tmp_path, f"40.0404_-76.3042_{OG_OPTS}", now, 900) is not None
    assert service.find_cached(tmp_path, "40.0404_-76.3042_1872_1404_4_l_i_12", now, 900) is None


def test_find_cached_isolated_by_display_options(tmp_path):
    # Same coordinates and panel, but different theme/units/time format must not
    # share a cache entry — each varies the rendered pixels.
    now = int(time.time())
    (tmp_path / f"img_40.0404_-76.3042_{OG_OPTS}_{now}.png").write_bytes(b"x")  # light/imperial/12

    assert service.find_cached(tmp_path, f"40.0404_-76.3042_{OG_OPTS}", now, 900) is not None
    assert service.find_cached(tmp_path, "40.0404_-76.3042_800_480_2_d_i_12", now, 900) is None  # dark
    assert service.find_cached(tmp_path, "40.0404_-76.3042_800_480_2_l_m_12", now, 900) is None  # metric
    assert service.find_cached(tmp_path, "40.0404_-76.3042_800_480_2_l_i_24", now, 900) is None  # 24h


def test_find_cached_picks_most_recent(tmp_path):
    now = int(time.time())
    tag = f"40.0404_-76.3042_{OG_OPTS}"
    for ts in (now - 600, now - 60, now - 300):
        (tmp_path / f"img_{tag}_{ts}.png").write_bytes(b"x")
    newest = service.find_cached(tmp_path, tag, now, 900)
    assert newest.name == f"img_{tag}_{now - 60}.png"


def test_cap_image_count_removes_oldest_over_limit(tmp_path):
    # Five images across two cache tags; cap to 3 keeps the three newest by
    # timestamp regardless of which tag they belong to.
    now = int(time.time())
    made = {}
    for i, tag in enumerate(
            [OG_OPTS, OG_OPTS, "1872_1404_4_d_m_24", OG_OPTS, "1872_1404_4_d_m_24"]):
        ts = now - i * 100
        p = tmp_path / f"img_40.0404_-76.3042_{tag}_{ts}.png"
        p.write_bytes(b"x")
        made[ts] = p

    removed = service.cap_image_count(tmp_path, max_files=3)
    assert removed == 2
    remaining = {p.name for p in tmp_path.glob("img_*.png")}
    # The two oldest timestamps were deleted; the three newest survive.
    oldest_two = sorted(made)[:2]
    assert all(made[ts].name not in remaining for ts in oldest_two)
    assert len(remaining) == 3


def test_cap_image_count_noop_under_limit(tmp_path):
    now = int(time.time())
    for i in range(3):
        (tmp_path / f"img_40.0404_-76.3042_{OG_OPTS}_{now - i}.png").write_bytes(b"x")
    assert service.cap_image_count(tmp_path, max_files=50) == 0
    assert len(list(tmp_path.glob("img_*.png"))) == 3


def test_cap_image_count_missing_dir(tmp_path):
    assert service.cap_image_count(tmp_path / "nope", max_files=10) == 0


def test_render_once_enforces_cap(tmp_path, monkeypatch):
    # A render writes its file and then trims the directory to the cap.
    monkeypatch.setattr(service, "MAX_CACHED_IMAGES", 2)
    now = int(time.time())
    for i in range(5):  # pre-existing backlog older than the new render
        (tmp_path / f"img_0.0000_0.0000_{OG_OPTS}_{now - 10000 - i}.png").write_bytes(b"x")

    settings = _settings(tmp_path)
    result = service.render_once(settings, xml_path=SAMPLE_XML, obs_path=SAMPLE_JSON)

    remaining = {p.name for p in tmp_path.glob("img_*.png")}
    assert len(remaining) == 2
    # The freshly written image is the newest, so it survives the cap.
    assert result["filename"] in remaining


def test_cache_tag_encodes_options():
    # Set every rendered-pixel option explicitly so the tag is independent of
    # any ambient environment / .env defaults.
    s = replace(Settings(), latitude=40.0404, longitude=-76.3042,
                theme=Theme.LIGHT, units=Units.IMPERIAL,
                time_format=TimeFormat.TWELVE_HOUR)
    assert s.cache_tag.endswith("_800_480_2_l_i_12")
    dark_metric_24 = replace(s, theme=Theme.DARK, units=Units.METRIC,
                             time_format=TimeFormat.TWENTY_FOUR_HOUR)
    assert dark_metric_24.cache_tag.endswith("_800_480_2_d_m_24")
    assert replace(s, device=Device.X).cache_tag.endswith("_1872_1404_4_l_i_12")


def test_timestamp_parsing():
    assert service._timestamp_of(
        Path("img_40.0404_-76.3042_800_480_2_l_i_12_1780590454.png")) == 1780590454
    assert service._timestamp_of(Path("not-an-image.png")) is None
