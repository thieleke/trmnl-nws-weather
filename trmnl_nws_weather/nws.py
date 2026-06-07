"""Fetch and parse the National Weather Service digital DWML forecast.

Endpoint (per the project plan)::

    https://forecast.weather.gov/MapClick.php?lat=<lat>&lon=<lon>&FcstType=digitalDWML

The feed pairs a ``time-layout`` (a list of start/end valid times) with a set of
hourly ``parameters`` (temperature, wind, precipitation, ...).  Each parameter is
a flat list of ``<value>`` elements aligned positionally with the layout's start
times.  We zip them back together into a list of :class:`HourPoint`.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime
import xml.etree.ElementTree as ET
from defusedxml.ElementTree import fromstring as safe_fromstring

from . import config
from .models import CurrentObservation, Forecast, HourPoint, Sky
from .utils import any_match

_REQUEST_TIMEOUT = 30


def fetch(url: str, *, timeout: int = _REQUEST_TIMEOUT) -> bytes:
    """Retrieve the raw forecast XML.

    A descriptive ``User-Agent`` is sent because weather.gov rejects requests
    from the default urllib agent.
    """
    request = urllib.request.Request(url, headers={"User-Agent": config.NWS_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _floats(parent: ET.Element | None) -> list[float | None]:
    """Read the ``<value>`` children of an element as floats (None when nil)."""
    if parent is None:
        return []
    values: list[float | None] = []
    for value in parent.findall("value"):
        if value.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            values.append(None)
            continue
        text = (value.text or "").strip()
        values.append(float(text) if text else None)
    return values


def _classify(weather_types: list[str], cloud_percent: float | None,
              wind_mph: float | None, pop_percent: float | None) -> Sky:
    """Infer a coarse :class:`Sky` state from the hourly conditions."""
    types = [t.lower() for t in weather_types]

    # Precipitation / hazard types take precedence over cloud cover.
    if any_match(types, "thunderstorm"):
        return Sky.THUNDERSTORM
    if any_match(types, "freezing", "ice", "glaze"):
        return Sky.ICE
    if any_match(types, "sleet"):
        return Sky.SLEET
    if any_match(types, "snow", "flurries", "wintry"):
        return Sky.SNOW
    if any_match(types, "rain", "showers", "drizzle"):
        return Sky.RAIN
    if any_match(types, "fog", "haze", "mist"):
        return Sky.FOG

    # Sustained strong wind with no precipitation reads as "windy".
    if wind_mph is not None and wind_mph >= 20:
        return Sky.WINDY

    if cloud_percent is None:
        return Sky.SUNNY
    if cloud_percent >= 70:
        return Sky.CLOUDY
    if cloud_percent >= 30:
        return Sky.PARTLY_CLOUDY
    return Sky.SUNNY


def parse(xml_bytes: bytes) -> Forecast:
    """Parse digital DWML bytes into a :class:`Forecast`."""
    root = safe_fromstring(xml_bytes)
    data = root.find("data")
    if data is None:
        raise ValueError("DWML document has no <data> element")

    location = data.find("location")
    area = location.findtext("area-description") if location is not None else None
    point = location.find("point") if location is not None else None
    
    latitude = 0.0
    longitude = 0.0
    if point is not None:
        lat_val = point.get("latitude")
        lon_val = point.get("longitude")
        if lat_val is not None:
            latitude = float(lat_val)
        if lon_val is not None:
            longitude = float(lon_val)

    creation = root.findtext("head/product/creation-date")
    generated_at = (
        datetime.fromisoformat(creation) if creation else datetime.now().astimezone()
    )

    # Map each time-layout key to its ordered list of start times.
    layouts: dict[str, list[datetime]] = {}
    for layout in data.findall("time-layout"):
        key = layout.findtext("layout-key")
        if not key:
            continue
        starts = [
            datetime.fromisoformat(t.text)
            for t in layout.findall("start-valid-time")
            if t.text
        ]
        layouts[key] = starts

    params = data.find("parameters")
    if params is None:
        raise ValueError("DWML document has no <parameters> element")

    def find(tag: str, **attrs: str) -> ET.Element | None:
        for el in params.findall(tag):
            if all(el.get(k) == v for k, v in attrs.items()):
                return el
        return None

    temps = _floats(find("temperature", type="hourly"))
    dewpoints = _floats(find("temperature", type="dew point"))
    heat_index = _floats(find("temperature", type="heat index"))
    pop = _floats(find("probability-of-precipitation"))
    wind = _floats(find("wind-speed", type="sustained"))
    gust = _floats(find("wind-speed", type="gust"))
    direction = _floats(find("direction", type="wind"))
    cloud = _floats(find("cloud-amount"))
    humidity = _floats(find("humidity"))
    qpf = _floats(find("hourly-qpf"))

    # Weather conditions are nested rather than flat <value> lists.
    weather_el = params.find("weather")
    weather_rows: list[tuple[list[str], str | None]] = []
    if weather_el is not None:
        for cond in weather_el.findall("weather-conditions"):
            values = cond.findall("value")
            wtypes = [v.get("weather-type", "") for v in values if v.get("weather-type")]
            coverage = values[0].get("coverage") if values else None
            weather_rows.append((wtypes, coverage))

    # Every hourly parameter shares the single-hour layout key.
    times = layouts.get("k-p1h-n1-0") or next(iter(layouts.values()), [])

    def at(seq: list, i: int):
        return seq[i] if i < len(seq) else None

    hours: list[HourPoint] = []
    for i, time in enumerate(times):
        wtypes, coverage = weather_rows[i] if i < len(weather_rows) else ([], None)
        cloud_pct = at(cloud, i)
        wind_mph = at(wind, i)
        pop_pct = at(pop, i)
        sky = _classify(wtypes, cloud_pct, wind_mph, pop_pct)
        hours.append(
            HourPoint(
                time=time,
                temperature_f=at(temps, i),
                dew_point_f=at(dewpoints, i),
                heat_index_f=at(heat_index, i),
                pop_percent=pop_pct,
                wind_mph=wind_mph,
                gust_mph=at(gust, i),
                wind_dir_deg=at(direction, i),
                cloud_percent=cloud_pct,
                humidity_percent=at(humidity, i),
                qpf_inches=at(qpf, i),
                weather_types=wtypes,
                weather_coverage=coverage,
                sky=sky,
            )
        )

    return Forecast(
        location_name=area or "Unknown",
        latitude=latitude,
        longitude=longitude,
        generated_at=generated_at,
        hours=hours,
    )


def load(url: str, *, timeout: int = _REQUEST_TIMEOUT) -> Forecast:
    """Fetch and parse in one step."""
    return parse(fetch(url, timeout=timeout))


# --- Current observations (MapClick FcstType=json) ------------------------

def _maybe_float(value: str | None) -> float | None:
    """Parse a JSON observation string, treating ''/'NA' as missing."""
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() == "NA":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _classify_observation(text: str, image: str) -> Sky:
    """Infer a :class:`Sky` from an observed condition string / icon code.

    Precipitation and hazards take precedence over cloud cover; "partly" is
    checked before the generic "cloudy" so "Partly Cloudy" is not mistaken for
    overcast.
    """
    t = (text or "").lower()
    img = (image or "").lower()

    if any_match([t], "thunder") or any_match([img], "tsra"):
        return Sky.THUNDERSTORM
    if any_match([t], "freezing", "glaze") or any_match([t], "ice pellets") or any_match([img], "fzra", "ip"):
        return Sky.ICE
    if any_match([t], "sleet"):
        return Sky.SLEET
    if any_match([t], "snow", "flurries", "wintry") or any_match([img], "sn"):
        return Sky.SNOW
    if any_match([t], "rain", "showers", "drizzle") or any_match([img], "ra", "shra"):
        return Sky.RAIN
    if any_match([t], "fog", "haze", "mist", "smoke") or any_match([img], "fg", "br"):
        return Sky.FOG
    if any_match([t], "windy", "breezy"):
        return Sky.WINDY
    if any_match([t], "partly", "scattered", "mostly clear") or any_match([img], "sct", "few"):
        return Sky.PARTLY_CLOUDY
    if any_match([t], "cloudy", "overcast", "broken") or any_match([img], "ovc", "bkn"):
        return Sky.CLOUDY
    if any_match([t], "fair", "clear", "sunny") or any_match([img], "skc", "clr"):
        return Sky.SUNNY
    return Sky.SUNNY


def parse_observation(json_bytes: bytes) -> CurrentObservation | None:
    """Parse the ``currentobservation`` block from MapClick JSON.

    Returns None when the payload has no usable observation.
    """
    payload = json.loads(json_bytes)
    obs = payload.get("currentobservation") or {}
    if not obs:
        return None

    weather_text = (obs.get("Weather") or "").strip()
    image = (obs.get("Weatherimage") or "").strip()
    return CurrentObservation(
        station_name=(obs.get("name") or "").strip(),
        observed_text=(obs.get("Date") or "").strip(),
        temperature_f=_maybe_float(obs.get("Temp")),
        dew_point_f=_maybe_float(obs.get("Dewp")),
        humidity_percent=_maybe_float(obs.get("Relh")),
        wind_mph=_maybe_float(obs.get("Winds")),
        gust_mph=_maybe_float(obs.get("Gust")),
        wind_dir_deg=_maybe_float(obs.get("Windd")),
        weather_text=weather_text,
        sky=_classify_observation(weather_text, image),
    )


def load_observation(url: str, *, timeout: int = _REQUEST_TIMEOUT) -> CurrentObservation | None:
    """Fetch and parse the current observation in one step."""
    return parse_observation(fetch(url, timeout=timeout))


def parse_headline(json_bytes: bytes, *, index: int = 1) -> str | None:
    """Return the worded forecast phrase at ``index`` of MapClick JSON.

    ``data.weather`` is a list of short forecast phrases by period; ``index=1``
    is the period after the current one (e.g. "Chance Showers then Showers
    Likely").  Returns None when unavailable.
    """
    payload = json.loads(json_bytes)
    weather = (payload.get("data") or {}).get("weather") or []
    if index < len(weather):
        text = (weather[index] or "").strip()
        return text or None
    return None
