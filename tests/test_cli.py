from decimal import Decimal

import argparse

import pytest

from trmnl_nws_weather.__main__ import _build_parser, _coordinate

_lat = _coordinate(Decimal(-90), Decimal(90), "latitude")
_lon = _coordinate(Decimal(-180), Decimal(180), "longitude")


def test_truncates_to_four_digits():
    assert _lat("39.739212") == 39.7392
    assert _lon("-104.990299") == -104.9902  # truncated toward zero
    assert _lat("40.04049999") == 40.0404  # no binary-float rounding drift


def test_inclusive_bounds():
    assert _lat("90") == 90.0
    assert _lat("-90") == -90.0
    assert _lon("180") == 180.0
    assert _lon("-180") == -180.0


@pytest.mark.parametrize("value", ["95", "-90.1", "90.0001"])
def test_latitude_out_of_range_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        _lat(value)


@pytest.mark.parametrize("value", ["200", "-180.1", "180.5"])
def test_longitude_out_of_range_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        _lon(value)


def test_non_decimal_rejected():
    with pytest.raises(argparse.ArgumentTypeError):
        _lat("abc")
    with pytest.raises(argparse.ArgumentTypeError):
        _lon("N40")


def test_parser_accepts_lat_lon():
    args = _build_parser().parse_args(["--lat", "12.3456789", "--lon", "-65.4321"])
    assert args.lat == 12.3456
    assert args.lon == -65.4321


def test_url_coordinates_padded_to_four_places():
    from dataclasses import replace
    from trmnl_nws_weather.config import Settings, _format_coordinate

    # Trailing zeros must be preserved for the NWS API (40.3 -> 40.3000).
    assert _format_coordinate(40.3) == "40.3000"
    assert _format_coordinate(42.0) == "42.0000"
    assert _format_coordinate(-76.3042) == "-76.3042"

    s = replace(Settings(), latitude=40.3, longitude=71.51)
    assert "lat=40.3000&lon=71.5100" in s.forecast_url
    assert "lat=40.3000&lon=71.5100" in s.observation_url
