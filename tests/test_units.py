from trmnl_nws_weather import units
from trmnl_nws_weather.config import Units


def test_fahrenheit_to_celsius():
    assert round(units.f_to_c(32), 2) == 0.0
    assert round(units.f_to_c(212), 2) == 100.0


def test_mph_to_kmh():
    assert round(units.mph_to_kmh(10), 1) == 16.1


def test_format_temp_imperial_and_metric():
    assert units.format_temp(67, Units.IMPERIAL) == "67°"
    assert units.format_temp(67, Units.IMPERIAL, with_unit=True) == "67°F"
    # 67F -> ~19.4C -> rounds to 19
    assert units.format_temp(67, Units.METRIC, with_unit=True) == "19°C"


def test_format_temp_missing():
    assert units.format_temp(None, Units.IMPERIAL) == "--"


def test_format_wind():
    assert units.format_wind(8, Units.IMPERIAL) == "8 mph"
    assert units.format_wind(8, Units.METRIC) == "13 km/h"
