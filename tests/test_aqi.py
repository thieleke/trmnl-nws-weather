from dataclasses import replace

from trmnl_nws_weather import aqi
from trmnl_nws_weather.config import Settings


def test_parse_open_meteo():
    raw = b'{"current": {"time": "2026-06-07T07:00", "us_aqi": 36}}'
    assert aqi._parse_open_meteo(raw) == 36


def test_parse_open_meteo_rounds():
    assert aqi._parse_open_meteo(b'{"current": {"us_aqi": 41.6}}') == 42


def test_parse_open_meteo_missing():
    assert aqi._parse_open_meteo(b'{"current": {}}') is None
    assert aqi._parse_open_meteo(b'{}') is None


def test_parse_custom():
    assert aqi._parse_custom(b'{"aqi": 73}') == 73
    assert aqi._parse_custom(b'{"aqi": null}') is None
    assert aqi._parse_custom(b'{}') is None


def test_fetch_disabled_makes_no_request(monkeypatch):
    # provider=none with no custom URL must not touch the network.
    def boom(*a, **k):
        raise AssertionError("network should not be called when AQI is disabled")

    monkeypatch.setattr(aqi.nws, "fetch", boom)
    settings = replace(Settings(), aqi_provider="none", aqi_url="")
    assert aqi.fetch_aqi(settings) is None


def test_fetch_open_meteo_uses_coordinates(monkeypatch):
    captured = {}

    def fake_fetch(url, **k):
        captured["url"] = url
        return b'{"current": {"us_aqi": 12}}'

    monkeypatch.setattr(aqi.nws, "fetch", fake_fetch)
    settings = replace(Settings(), aqi_provider="open-meteo", aqi_url="",
                       latitude=40.0404, longitude=-76.3042)
    assert aqi.fetch_aqi(settings) == 12
    assert "latitude=40.0404" in captured["url"]
    assert "longitude=-76.3042" in captured["url"]


def test_custom_url_takes_precedence(monkeypatch):
    monkeypatch.setattr(aqi.nws, "fetch", lambda url, **k: b'{"aqi": 99}')
    settings = replace(Settings(), aqi_provider="open-meteo",
                       aqi_url="http://sensor.local/aqi")
    assert aqi.fetch_aqi(settings) == 99


def test_fetch_swallows_errors(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(aqi.nws, "fetch", boom)
    settings = replace(Settings(), aqi_provider="open-meteo", aqi_url="")
    assert aqi.fetch_aqi(settings) is None
