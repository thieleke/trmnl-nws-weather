"""Data models for parsed forecast data.

These are unit-agnostic: temperatures are stored in Fahrenheit and wind speeds
in mph (the feed's native units).  Conversion happens at render time via the
``units`` module so a single parse can be displayed in either system.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Sky(str, Enum):
    """Coarse weather state used to pick a display icon and label.

    The digital DWML feed does not include a pre-rendered icon, so the state is
    inferred from the ``weather`` conditions and cloud cover.
    """

    SUNNY = "sunny"
    PARTLY_CLOUDY = "partly_cloudy"
    CLOUDY = "cloudy"
    WINDY = "windy"
    RAIN = "rain"
    SNOW = "snow"
    SLEET = "sleet"
    ICE = "ice"
    FOG = "fog"
    THUNDERSTORM = "thunderstorm"

    @property
    def label(self) -> str:
        return {
            Sky.SUNNY: "Sunny",
            Sky.PARTLY_CLOUDY: "Partly Cloudy",
            Sky.CLOUDY: "Cloudy",
            Sky.WINDY: "Windy",
            Sky.RAIN: "Rain",
            Sky.SNOW: "Snow",
            Sky.SLEET: "Sleet",
            Sky.ICE: "Ice",
            Sky.FOG: "Fog",
            Sky.THUNDERSTORM: "Thunderstorms",
        }[self]


# Below this precipitation chance, an unlikely rain/thunderstorm is shown as
# cloudy rather than as precipitation.
PRECIP_DOWNGRADE_POP = 40.0


def effective_sky(sky: Sky, pop_percent: float | None,
                  threshold: float = PRECIP_DOWNGRADE_POP) -> Sky:
    """Present an unlikely rain/thunderstorm as cloudy.

    When the precipitation chance is below ``threshold`` percent, a ``RAIN`` or
    ``THUNDERSTORM`` classification is downgraded to ``CLOUDY`` (it probably
    won't precipitate).  Snow, sleet, and ice are left unchanged.
    """
    if (sky in (Sky.RAIN, Sky.THUNDERSTORM)
            and pop_percent is not None and pop_percent < threshold):
        return Sky.CLOUDY
    return sky


@dataclass(slots=True)
class HourPoint:
    """A single hour of forecast data (native feed units)."""

    time: datetime
    temperature_f: float | None = None
    dew_point_f: float | None = None
    heat_index_f: float | None = None
    pop_percent: float | None = None  # probability of precipitation
    wind_mph: float | None = None
    gust_mph: float | None = None
    wind_dir_deg: float | None = None
    cloud_percent: float | None = None
    humidity_percent: float | None = None
    qpf_inches: float | None = None  # quantitative precipitation forecast
    weather_types: list[str] = field(default_factory=list)
    weather_coverage: str | None = None
    sky: Sky = Sky.SUNNY

    @property
    def precip_type(self) -> str | None:
        """The specific precipitation type for this hour, or None if unspecified.

        Derived from the explicit forecast ``weather-type``; returns None when
        the feed lists no precipitation type for the hour (callers can then show
        a generic indicator instead of a word).
        """
        from .utils import any_match

        types = [t.lower() for t in self.weather_types]

        # Thunderstorms outrank rain: they are a distinct, more hazardous type
        # and are reported even when rain is listed alongside them.
        if any_match(types, "thunderstorm", "tstorm", "t-storm"):
            return "T'Storm"
        if any_match(types, "snow", "flurries", "wintry"):
            return "Snow"
        if any_match(types, "sleet"):
            return "Sleet"
        if any_match(types, "freezing", "ice", "glaze"):
            return "Ice"
        if any_match(types, "rain", "showers", "drizzle"):
            return "Rain"
        # Any other explicitly-forecast type: show it normalised to Title case.
        if self.weather_types:
            return self.weather_types[0].strip().title()
        return None

    @property
    def precip_label(self) -> str:
        """Precipitation-type word, falling back to the generic "Precip"."""
        return self.precip_type or "Precip"


@dataclass(slots=True)
class CurrentObservation:
    """Latest observed conditions from the nearest reporting station.

    Sourced from the MapClick ``FcstType=json`` ``currentobservation`` block,
    which reflects actual measured weather rather than the forecast.  Stored in
    the feed's native units (Fahrenheit, mph).
    """

    station_name: str
    observed_text: str  # raw observation timestamp string, e.g. "4 Jun 01:53 am CDT"
    temperature_f: float | None
    dew_point_f: float | None
    humidity_percent: float | None
    wind_mph: float | None
    gust_mph: float | None
    wind_dir_deg: float | None
    weather_text: str
    sky: Sky
    aqi: int | None = None


@dataclass(slots=True)
class Forecast:
    """A parsed forecast for a single location."""

    location_name: str
    latitude: float
    longitude: float
    generated_at: datetime
    hours: list[HourPoint]

    def current(self, now: datetime) -> HourPoint:
        """Return the hour nearest to ``now`` (the "current conditions")."""
        # Find the insertion point for 'now' in the sorted list of hours
        times = [h.time for h in self.hours]
        idx = bisect.bisect_left(times, now)
        
        if idx == 0:
            return self.hours[0]
        if idx == len(self.hours):
            return self.hours[-1]
        
        # Check which of the two neighbors is closer
        before = self.hours[idx - 1]
        after = self.hours[idx]
        if abs((before.time - now).total_seconds()) <= abs((after.time - now).total_seconds()):
            return before
        return after

    def window(self, start: datetime, end: datetime) -> list[HourPoint]:
        """Return hours whose timestamp falls within [start, end]."""
        return [h for h in self.hours if start <= h.time <= end]
