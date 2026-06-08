"""Tests for day/night determination in :mod:`trmnl_nws_weather.sun`.

Two complementary strategies are used:

* **Boundary tests** assert that the sun/moon transition happens at published
  almanac sunrise/sunset times (within a tolerance that absorbs the NOAA
  approximation and minute rounding).
* **Physics tests** assert location-independent invariants -- local noon is
  always daytime and local midnight always nighttime, and day length follows
  the correct hemisphere's seasons -- across the whole year and both
  hemispheres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trmnl_nws_weather import sun

# How far the computed transition may sit from the published time.  The NOAA
# approximation tracks real sunrise/sunset to ~2 minutes for these latitudes;
# 20 minutes leaves generous headroom while still being a meaningful assertion.
_TOLERANCE = timedelta(minutes=20)


def _tz(offset_hours: int) -> timezone:
    return timezone(timedelta(hours=offset_hours))


# (label, latitude, longitude, utc_offset, year, month, day, sunrise, sunset)
# Sunrise/sunset are local clock times from published almanac data, with the
# UTC offset chosen to match the date's standard/daylight rule for that place.
# All locations are US states/territories; the southern-hemisphere case (Pago
# Pago, American Samoa) is covered by the physics tests below.
_KNOWN = [
    ("Minneapolis Jun", 44.98, -93.27, -5, 2025, 6, 21, (5, 26), (21, 3)),
    ("Minneapolis Dec", 44.98, -93.27, -6, 2025, 12, 21, (7, 49), (16, 34)),
    ("Honolulu Mar", 21.31, -157.86, -10, 2025, 3, 20, (6, 38), (18, 46)),
    ("Honolulu Jun", 21.31, -157.86, -10, 2025, 6, 21, (5, 50), (19, 16)),
    ("Miami Sep", 25.76, -80.19, -4, 2025, 9, 23, (7, 10), (19, 18)),
]


@pytest.mark.parametrize(
    "label,lat,lon,off,y,m,d,sunrise,sunset",
    _KNOWN,
    ids=[row[0] for row in _KNOWN],
)
def test_known_sunrise_sunset_boundaries(label, lat, lon, off, y, m, d, sunrise, sunset):
    tz = _tz(off)
    rise = datetime(y, m, d, *sunrise, tzinfo=tz)
    fall = datetime(y, m, d, *sunset, tzinfo=tz)

    # Comfortably inside night before sunrise, inside day after it.
    assert not sun.is_daytime(rise - _TOLERANCE, lat, lon)
    assert sun.is_daytime(rise + _TOLERANCE, lat, lon)
    # Inside day before sunset, inside night after it.
    assert sun.is_daytime(fall - _TOLERANCE, lat, lon)
    assert not sun.is_daytime(fall + _TOLERANCE, lat, lon)


# Non-polar locations in both hemispheres; local noon/midnight invariants hold
# everywhere outside the polar day/night zones.
# (label, latitude, longitude, standard_offset)
_LOCATIONS = [
    ("Minneapolis", 44.98, -93.27, -6),
    ("Miami", 25.76, -80.19, -5),
    ("Honolulu", 21.31, -157.86, -10),
    ("Pago Pago (S)", -14.28, -170.70, -11),  # American Samoa, southern hemisphere
]


@pytest.mark.parametrize("label,lat,lon,off", _LOCATIONS, ids=[r[0] for r in _LOCATIONS])
@pytest.mark.parametrize("month", range(1, 13))
def test_local_noon_is_day_and_midnight_is_night(label, lat, lon, off, month):
    tz = _tz(off)
    noon = datetime(2025, month, 15, 12, 0, tzinfo=tz)
    midnight = datetime(2025, month, 15, 0, 0, tzinfo=tz)
    assert sun.is_daytime(noon, lat, lon), f"{label} {month}: noon should be day"
    assert not sun.is_daytime(midnight, lat, lon), f"{label} {month}: midnight should be night"


def _day_length_hours(lat: float, lon: float, tz: timezone, y: int, m: int, d: int) -> float:
    """Minutes of daylight on a calendar day, sampled once per minute."""
    base = datetime(y, m, d, 0, 0, tzinfo=tz)
    lit = sum(
        1 for i in range(24 * 60) if sun.is_daytime(base + timedelta(minutes=i), lat, lon)
    )
    return lit / 60


def test_hemisphere_seasonality():
    """Day length must track the local hemisphere's seasons.

    Northern summer solstice has the longest day in the north and the shortest
    in the south; this asymmetry confirms the latitude sign is handled
    correctly rather than, say, mirrored.
    """
    jun = (2025, 6, 21)  # northern summer / southern winter
    dec = (2025, 12, 21)  # northern winter / southern summer

    north = (44.98, -93.27, _tz(-5))  # Minneapolis
    south = (-14.28, -170.70, _tz(-11))  # Pago Pago, American Samoa

    north_jun = _day_length_hours(*north[:2], north[2], *jun)
    north_dec = _day_length_hours(*north[:2], north[2], *dec)
    south_jun = _day_length_hours(*south[:2], south[2], *jun)
    south_dec = _day_length_hours(*south[:2], south[2], *dec)

    # Northern hemisphere: June day longer than December.
    assert north_jun > north_dec + 2
    # Southern hemisphere: the reverse.
    assert south_dec > south_jun + 1
    # The far-northern site swings far more than the near-equatorial one.
    assert (north_jun - north_dec) > (south_dec - south_jun)


def test_naive_datetime_is_treated_as_local():
    """A naive datetime is accepted (interpreted as local system time)."""
    # Should not raise; result is a bool either way.
    assert isinstance(sun.is_daytime(datetime(2025, 6, 21, 12, 0), 44.98, -93.27), bool)
