import re
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

from trmnl_nws_weather import service
from trmnl_nws_weather.config import Settings

DOCS = Path(__file__).resolve().parents[1] / "docs"
SAMPLE_XML = DOCS / "MapClick.php.xml"
SAMPLE_JSON = DOCS / "MapClick.json"

FILENAME_RE = re.compile(r"^img_-?\d+\.\d{4}_-?\d+\.\d{4}_\d+\.png$")


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
    (tmp_path / f"img_40.0404_-76.3042_{now}.png").write_bytes(b"x")

    assert service.find_cached(tmp_path, "40.0404_-76.3042", now, 900) is not None
    # Just outside the 15-minute window:
    assert service.find_cached(tmp_path, "40.0404_-76.3042", now + 901, 900) is None
    # Different coordinates:
    assert service.find_cached(tmp_path, "10.0000_20.0000", now, 900) is None


def test_find_cached_picks_most_recent(tmp_path):
    now = int(time.time())
    for ts in (now - 600, now - 60, now - 300):
        (tmp_path / f"img_40.0404_-76.3042_{ts}.png").write_bytes(b"x")
    newest = service.find_cached(tmp_path, "40.0404_-76.3042", now, 900)
    assert newest.name == f"img_40.0404_-76.3042_{now - 60}.png"


def test_timestamp_parsing():
    assert service._timestamp_of(Path("img_40.0404_-76.3042_1780590454.png")) == 1780590454
    assert service._timestamp_of(Path("not-an-image.png")) is None
