from pathlib import Path

from trmnl_nws_weather import nws
from trmnl_nws_weather.models import Sky

OBS_JSON = Path(__file__).resolve().parents[1] / "docs" / "MapClick.json"


def test_parse_observation():
    obs = nws.parse_observation(OBS_JSON.read_bytes())
    assert obs is not None
    assert obs.temperature_f == 67.0
    assert obs.humidity_percent == 57.0
    assert obs.wind_mph == 7.0
    assert obs.gust_mph is None  # "NA" -> None
    assert obs.weather_text == "Fair"
    assert "Intercourse" in obs.station_name


def test_parse_observation_empty():
    assert nws.parse_observation(b'{"currentobservation": {}}') is None


def test_parse_headline_second_item():
    headline = nws.parse_headline(OBS_JSON.read_bytes())
    assert headline == "Chance Showers then Showers Likely"


def test_parse_headline_out_of_range():
    assert nws.parse_headline(b'{"data": {"weather": ["Sunny"]}}', index=1) is None


def test_classify_observation_text():
    assert nws._classify_observation("Thunderstorm", "") is Sky.THUNDERSTORM
    assert nws._classify_observation("Light Snow", "") is Sky.SNOW
    assert nws._classify_observation("Freezing Rain", "") is Sky.ICE
    assert nws._classify_observation("Light Rain", "") is Sky.RAIN
    assert nws._classify_observation("Partly Cloudy", "") is Sky.PARTLY_CLOUDY
    assert nws._classify_observation("Mostly Cloudy", "") is Sky.CLOUDY
    assert nws._classify_observation("Fair", "") is Sky.SUNNY
