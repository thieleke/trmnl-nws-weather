"""Runtime configuration for the weather display service.

Settings are read from environment variables (prefixed ``TRMNL_``) with sane
defaults, so the service runs out of the box for hard-coded Intercourse, PA
location.

All environment variable values are validated before use.  Invalid values fall
back to their built-in defaults after a warning is logged, so malicious or
misconfigured input cannot crash the service or cause unexpected behaviour.

Validation logic is centralised in :mod:`trmnl_nws_weather.validate`; this
module provides thin wrappers that handle string parsing (since environment
variables are always strings) and delegate to the shared validators.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

from . import validate
from .utils import TimeFormat  # noqa: PLC0414

load_dotenv()  # Reads variables from the .env file into the environment, so they can be picked up by Settings

log = logging.getLogger("trmnl_nws_weather")


def _format_coordinate(value: float) -> str:
    """Format a coordinate as a zero-padded, 4-decimal-place string.

    The NWS MapClick API expects the lat/lon to carry their fractional digits;
    a trailing-zero-trimmed value like ``40.3`` can be rejected, so we always
    emit four places (``40.3000``).  The value is truncated toward zero (not
    rounded) to keep it consistent with the CLI's coordinate handling.
    """
    quantized = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return f"{quantized:f}"


class Units(str, Enum):
    """Measurement system for displayed values."""

    IMPERIAL = "imperial"  # degrees F, wind in mph
    METRIC = "metric"  # degrees C, wind in km/h


class Theme(str, Enum):
    """Light mode/Dark mode for the rendered image."""

    LIGHT = "light"  # black text on a white background
    DARK = "dark"  # white text on a black background


# -----------------------------------------------------------------------
# Environment variable helpers
# -----------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_url(key: str, default: str) -> str:
    """Read and validate a URL environment variable.

    Parses the raw string from the environment and delegates to
    :func:`validate.validate_url`.  Returns *default* on invalid input.
    """
    return validate.validate_url(_env(key, default), key, default=default)


def _env_coordinate(key: str, low: float, high: float, default: float) -> float:
    """Read and validate a coordinate environment variable.

    Parses the raw string to float and delegates to
    :func:`validate.validate_coordinate`.  Returns *default* on invalid input.
    """
    raw = _env(key, str(default))
    try:
        value = float(raw)
    except (ValueError, TypeError):
        log.warning("%s is not a valid number %r; falling back to default (%s)",
                    key, raw, default)
        return default
    return validate.validate_coordinate(value, key, low, high, default)


def _env_int(key: str, low: int, high: int, default: int) -> int:
    """Read and validate an integer environment variable.

    Parses the raw string to int and delegates to
    :func:`validate.validate_int`.  Returns *default* on invalid input.
    """
    raw = _env(key, str(default))
    try:
        value = int(raw)
    except (ValueError, TypeError):
        log.warning("%s is not a valid integer %r; falling back to default (%s)",
                    key, raw, default)
        return default
    return validate.validate_int(value, key, low, high, default)


def _env_float(key: str, low: float, high: float, default: float) -> float:
    """Read and validate a float environment variable.

    Parses the raw string to float and delegates to
    :func:`validate.validate_float`.  Returns *default* on invalid input.
    """
    raw = _env(key, str(default))
    try:
        value = float(raw)
    except (ValueError, TypeError):
        log.warning("%s is not a valid number %r; falling back to default (%s)",
                    key, raw, default)
        return default
    return validate.validate_float(value, key, low, high, default)


def _env_enum(key: str, enum_class: type[Enum], default: Enum) -> Enum:
    """Read and validate an enum environment variable.

    Comparison is case-insensitive.  Returns *default* on invalid input.
    """
    raw = _env(key, default.value)
    try:
        return enum_class(raw.lower())  # type: ignore[call-arg]
    except ValueError:
        valid = ", ".join(member.value for member in enum_class)
        log.warning("%s value %r is not valid (allowed: %s); "
                    "falling back to default (%s)",
                    key, raw, valid, default.value)
        return default


# -----------------------------------------------------------------------
# Defaults
# -----------------------------------------------------------------------

DEFAULT_LATITUDE = 40.0404
DEFAULT_LONGITUDE = -76.3042
DEFAULT_UNITS = Units.IMPERIAL
DEFAULT_THEME = Theme.LIGHT
DEFAULT_TIME_FORMAT = TimeFormat.TWELVE_HOUR
DEFAULT_REFRESH_SECONDS = 30 * 60
DEFAULT_GRAPH_WINDOW_HOURS = 18
DEFAULT_GRAPH_NOW_POSITION = 0.0
DEFAULT_FORECAST_HOURS = 6
DEFAULT_CACHE_SECONDS = 15 * 60
DEFAULT_CLEANUP_AGE_SECONDS = 6 * 60 * 60
DEFAULT_OUTPUT_DIR = Path("images")
# AQI is sourced separately from the NWS feed.  By default we use the free,
# key-less Open-Meteo Air Quality API (see aqi.py); a custom URL overrides it.
DEFAULT_AQI_PROVIDER = "open-meteo"
DEFAULT_AQI_URL = ""
# Default webhook URL for --webhook; empty means one must be given on the CLI.
DEFAULT_WEBHOOK_URL = ""

# User-Agent strings for outgoing HTTP requests.
NWS_USER_AGENT = "trmnl-nws-weather/0.1"
WEBHOOK_USER_AGENT = "curl/8.x"


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable service configuration."""

    latitude: float = field(
        default_factory=lambda: _env_coordinate(
            "TRMNL_LATITUDE", -90.0, 90.0, DEFAULT_LATITUDE)
    )
    longitude: float = field(
        default_factory=lambda: _env_coordinate(
            "TRMNL_LONGITUDE", -180.0, 180.0, DEFAULT_LONGITUDE)
    )
    units: Units = field(  # type: ignore[assignment]
        default_factory=lambda: _env_enum("TRMNL_UNITS", Units, DEFAULT_UNITS)
    )
    theme: Theme = field(  # type: ignore[assignment]
        default_factory=lambda: _env_enum("TRMNL_THEME", Theme, DEFAULT_THEME)
    )
    time_format: TimeFormat = field(  # type: ignore[assignment]
        default_factory=lambda: _env_enum("TRMNL_TIME_FORMAT", TimeFormat, DEFAULT_TIME_FORMAT)
    )
    # How often the service re-fetches the forecast and re-renders, in seconds.
    refresh_seconds: int = field(
        default_factory=lambda: _env_int(
            "TRMNL_REFRESH_SECONDS", 60, 86400, DEFAULT_REFRESH_SECONDS)
    )
    # Width of the temperature graph time window and where "now" sits in it,
    # as a fraction from the left edge.  The layout spec calls for "now" centred,
    # but the NWS digital DWML feed only provides *forward* hourly data (it
    # begins at the upcoming hour), so a centred marker would leave the left
    # half of the graph permanently empty.  We therefore anchor "now" near the
    # left and fill the window with the 18-hour forecast.  Override to 0.5 if a
    # data source with historical hours is ever wired in.
    graph_window_hours: int = field(
        default_factory=lambda: _env_int(
            "TRMNL_GRAPH_WINDOW_HOURS", 1, 720, DEFAULT_GRAPH_WINDOW_HOURS)
    )
    graph_now_position: float = field(
        default_factory=lambda: _env_float(
            "TRMNL_GRAPH_NOW_POSITION", 0.0, 1.0, DEFAULT_GRAPH_NOW_POSITION)
    )
    # Number of forecast columns shown along the bottom.
    # Window is centred on the current hour so the layout stays stable
    # (does not scroll left→right as time advances).
    forecast_hours: int = field(
        default_factory=lambda: _env_int(
            "TRMNL_FORECAST_HOURS", 1, 240, DEFAULT_FORECAST_HOURS)
    )
    # A freshly-requested image is served from cache if one exists for the same
    # coordinates generated within this many seconds (unless --no-cache).
    cache_seconds: int = field(
        default_factory=lambda: _env_int(
            "TRMNL_CACHE_SECONDS", 0, 86400, DEFAULT_CACHE_SECONDS)
    )
    # Generated PNGs older than this are deleted after each fresh render, so the
    cleanup_age_seconds: int = field(
        default_factory=lambda: _env_int(
            "TRMNL_CLEANUP_AGE_SECONDS", 0, 604800, DEFAULT_CLEANUP_AGE_SECONDS)
    )
    # Directory generated PNGs are written to.
    output_dir: Path = field(
        default_factory=lambda: Path(_env("TRMNL_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    )
    # AQI (Air Quality Index) source.  ``aqi_provider`` selects the built-in
    # provider (``open-meteo`` or ``none``); ``aqi_url`` points at a custom
    # ``{"aqi": N}`` endpoint (e.g. a local sensor) and, when set, overrides the
    # provider.  See aqi.py.
    aqi_provider: str = field(
        default_factory=lambda: _env("TRMNL_AQI_PROVIDER", DEFAULT_AQI_PROVIDER)
    )
    aqi_url: str = field(
        default_factory=lambda: _env_url("TRMNL_AQI_URL", DEFAULT_AQI_URL)
    )
    # Default destination for ``--webhook`` when no URL is given on the CLI.
    webhook_url: str = field(
        default_factory=lambda: _env_url("TRMNL_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
    )

    @property
    def coord_tag(self) -> str:
        """The ``<lat>_<lon>`` fragment used in generated image filenames."""
        return (f"{_format_coordinate(self.latitude)}"
                f"_{_format_coordinate(self.longitude)}")

    @property
    def _coords(self) -> str:
        """The ``lat=&lon=`` query fragment, formatted to 4 decimal places."""
        return (f"lat={_format_coordinate(self.latitude)}"
                f"&lon={_format_coordinate(self.longitude)}")

    @property
    def forecast_url(self) -> str:
        """NWS digital DWML endpoint for the configured point."""
        return (f"https://forecast.weather.gov/MapClick.php"
                f"?{self._coords}&FcstType=digitalDWML")

    @property
    def observation_url(self) -> str:
        """MapClick JSON endpoint; its ``currentobservation`` block holds the
        latest measured conditions from the nearest station."""
        return (f"https://forecast.weather.gov/MapClick.php"
                f"?{self._coords}&FcstType=json")
