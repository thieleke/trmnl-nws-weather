import re
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

from trmnl_nws_weather import service
from trmnl_nws_weather.config import Device, Settings

DOCS = Path(__file__).resolve().parents[1] / "docs"
SAMPLE_XML = DOCS / "MapClick.php.xml"
SAMPLE_JSON = DOCS / "MapClick.json"

# img_<lat>_<lon>_<width>_<height>_<bit_depth>_<unix-ts>.png
FILENAME_RE = re.compile(
    r"^img_-?\d+\.\d{4}_-?\d+\.\d{4}_\d+_\d+_\d+_\d+\.png$")

# Default panel (OG) geometry fragment of the cache tag.
OG_GEOM = "800_480_2"


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
    tag = f"40.0404_-76.3042_{OG_GEOM}"
    (tmp_path / f"img_{tag}_{now}.png").write_bytes(b"x")

    assert service.find_cached(tmp_path, tag, now, 900) is not None
    # Just outside the 15-minute window:
    assert service.find_cached(tmp_path, tag, now + 901, 900) is None
    # Different coordinates:
    assert service.find_cached(tmp_path, f"10.0000_20.0000_{OG_GEOM}", now, 900) is None


def test_find_cached_isolated_by_panel_geometry(tmp_path):
    # An image rendered for the OG panel must not be served for an X-panel
    # request made at the same moment (different width/height/bit depth).
    now = int(time.time())
    (tmp_path / f"img_40.0404_-76.3042_{OG_GEOM}_{now}.png").write_bytes(b"x")

    assert service.find_cached(tmp_path, f"40.0404_-76.3042_{OG_GEOM}", now, 900) is not None
    assert service.find_cached(tmp_path, "40.0404_-76.3042_1872_1404_4", now, 900) is None


def test_find_cached_picks_most_recent(tmp_path):
    now = int(time.time())
    tag = f"40.0404_-76.3042_{OG_GEOM}"
    for ts in (now - 600, now - 60, now - 300):
        (tmp_path / f"img_{tag}_{ts}.png").write_bytes(b"x")
    newest = service.find_cached(tmp_path, tag, now, 900)
    assert newest.name == f"img_{tag}_{now - 60}.png"


def test_timestamp_parsing():
    assert service._timestamp_of(
        Path("img_40.0404_-76.3042_800_480_2_1780590454.png")) == 1780590454
    assert service._timestamp_of(Path("not-an-image.png")) is None
