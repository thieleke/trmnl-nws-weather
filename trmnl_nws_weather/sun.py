"""Determine whether a given instant is daytime or nighttime at a location.

The NWS DWML feed carries no sunrise/sunset field, so day vs night is computed
from the sun's position using the standard NOAA solar-position approximation.
This keeps the icon selection (sun vs moon) accurate across seasons and
latitudes without pulling in an astronomy dependency.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# Solar zenith angle (degrees) at sunrise/sunset.  90.833 = 90 (geometric
# horizon) plus the standard ~0.833 correction for atmospheric refraction and
# the sun's apparent radius.
_HORIZON_ZENITH = 90.833


def solar_zenith_deg(when: datetime, latitude: float, longitude: float) -> float:
    """Return the sun's zenith angle (degrees) at ``when`` for the location.

    A zenith of 0 places the sun directly overhead; 90 is the horizon.  ``when``
    may be naive (interpreted as local system time) or timezone-aware.
    """
    utc = when.astimezone(timezone.utc)
    # Fractional hour of the UTC day, including the day-of-year fraction so the
    # equation of time and declination track the moment, not just the date.
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = 2 * math.pi / 365 * (utc.timetuple().tm_yday - 1 + (hour - 12) / 24)

    # Equation of time (minutes) and solar declination (radians), NOAA series.
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    # True solar time (minutes) -> hour angle (degrees).
    true_solar_time = hour * 60 + eqtime + 4 * longitude
    hour_angle = math.radians(true_solar_time / 4 - 180)

    lat = math.radians(latitude)
    cos_zenith = (
        math.sin(lat) * math.sin(decl)
        + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    )
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return math.degrees(math.acos(cos_zenith))


def is_daytime(when: datetime, latitude: float, longitude: float) -> bool:
    """Return ``True`` when the sun is above the horizon at ``when``."""
    return solar_zenith_deg(when, latitude, longitude) < _HORIZON_ZENITH
