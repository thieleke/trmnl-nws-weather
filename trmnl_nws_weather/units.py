"""Unit conversion and formatting.

The NWS digital DWML feed always reports temperatures in degrees Fahrenheit,
wind speed in miles per hour, and precipitation amounts in inches.  This module
converts those native values for display in either Imperial or Metric units.
"""

from __future__ import annotations

from .config import Units


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def mph_to_kmh(mph: float) -> float:
    return mph * 1.609344


def temperature(value_f: float | None, units: Units) -> float | None:
    """Convert a native Fahrenheit temperature to the target unit system."""
    if value_f is None:
        return None
    return f_to_c(value_f) if units is Units.METRIC else value_f


def wind_speed(value_mph: float | None, units: Units) -> float | None:
    """Convert a native mph wind speed to the target unit system."""
    if value_mph is None:
        return None
    return mph_to_kmh(value_mph) if units is Units.METRIC else value_mph


def temp_unit_label(units: Units) -> str:
    return "°C" if units is Units.METRIC else "°F"


def temp_degree_label(units: Units) -> str:
    """Short degree label without the temperature scale letter."""
    return "°"


def wind_unit_label(units: Units) -> str:
    return "km/h" if units is Units.METRIC else "mph"


def format_temp(value_f: float | None, units: Units, *, with_unit: bool = False) -> str:
    """Render a temperature as a rounded integer string."""
    converted = temperature(value_f, units)
    if converted is None:
        return "--"
    text = f"{round(converted)}{temp_degree_label(units)}"
    return f"{text}{('C' if units is Units.METRIC else 'F')}" if with_unit else text


def format_wind(value_mph: float | None, units: Units) -> str:
    converted = wind_speed(value_mph, units)
    if converted is None:
        return "--"
    return f"{round(converted)} {wind_unit_label(units)}"


_COMPASS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def degrees_to_compass(degrees: float | None) -> str:
    """Convert a wind bearing in degrees-true to a 16-point compass label."""
    if degrees is None:
        return ""
    index = int((degrees % 360) / 22.5 + 0.5) % 16
    return _COMPASS[index]
