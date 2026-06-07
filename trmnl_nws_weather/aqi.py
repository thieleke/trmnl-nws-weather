"""Optional Air Quality Index (AQI) lookup.

The NWS feed does not carry air quality, so AQI is sourced separately.  Two
free options are supported:

* **Open-Meteo** (the default) -- the free, no-API-key
  `Air Quality API <https://open-meteo.com/en/docs/air-quality-api>`_.  It
  returns the US EPA AQI (``us_aqi``) directly for the configured
  latitude/longitude, so it works out of the box for any point in NWS coverage.
* **A custom URL** (``TRMNL_AQI_URL``) -- any endpoint returning JSON shaped
  like ``{"aqi": <number>}``.  Use this to surface a local air-quality sensor;
  it takes precedence over the built-in provider when set.

Set ``TRMNL_AQI_PROVIDER=none`` (and leave ``TRMNL_AQI_URL`` empty) to disable
AQI entirely.  AQI is strictly best-effort: every failure is logged and turns
into ``None`` so it never blocks a render.
"""

from __future__ import annotations

import json
import logging

from . import nws
from .config import Settings, _format_coordinate

log = logging.getLogger("trmnl_nws_weather")

# Open-Meteo Air Quality endpoint.  ``current=us_aqi`` yields the US EPA AQI as
# a single integer under ``current.us_aqi``.
OPEN_METEO_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality"
    "?latitude={lat}&longitude={lon}&current=us_aqi"
)

_OPEN_METEO_ALIASES = {"open-meteo", "openmeteo", "open_meteo"}
_DISABLED_ALIASES = {"", "none", "off", "disabled"}


def _to_int(value: object) -> int | None:
    """Coerce a JSON number/string to a rounded int, or None."""
    if value is None:
        return None
    try:
        return round(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_open_meteo(raw: bytes) -> int | None:
    """Pull ``current.us_aqi`` out of an Open-Meteo Air Quality response."""
    current = (json.loads(raw) or {}).get("current") or {}
    return _to_int(current.get("us_aqi"))


def _parse_custom(raw: bytes) -> int | None:
    """Pull ``aqi`` out of a custom ``{"aqi": N}`` response."""
    return _to_int((json.loads(raw) or {}).get("aqi"))


def fetch_aqi(settings: Settings) -> int | None:
    """Return the current AQI for the configured point, or None.

    A custom ``aqi_url`` (e.g. a local sensor) takes precedence; otherwise the
    configured provider is used.  All failures are swallowed and logged so a
    missing AQI never blocks a render.
    """
    try:
        if settings.aqi_url:
            return _parse_custom(nws.fetch(settings.aqi_url))

        provider = (settings.aqi_provider or "").strip().lower()
        if provider in _DISABLED_ALIASES:
            return None
        if provider in _OPEN_METEO_ALIASES:
            url = OPEN_METEO_URL.format(
                lat=_format_coordinate(settings.latitude),
                lon=_format_coordinate(settings.longitude),
            )
            return _parse_open_meteo(nws.fetch(url))

        log.warning("Unknown AQI provider %r; skipping AQI", settings.aqi_provider)
        return None
    except Exception as e:  # noqa: BLE001 - AQI is best-effort
        log.warning("AQI fetch failed: %s", e)
        return None
