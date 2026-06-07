from datetime import datetime

from trmnl_nws_weather.models import Sky


def test_parse_location_and_hours(sample_forecast):
    fc = sample_forecast
    assert fc.location_name == "3 Miles WNW Intercourse PA"
    assert round(fc.latitude, 2) == 40.04
    assert round(fc.longitude, 2) == -76.30
    # The sample is a 7-day hourly forecast.
    assert len(fc.hours) == 168


def test_first_hour_values(sample_forecast):
    h = sample_forecast.hours[0]
    assert h.temperature_f == 67.0
    assert h.humidity_percent == 61.0
    assert h.wind_mph == 7.0
    assert h.pop_percent == 2.0
    assert h.sky is Sky.PARTLY_CLOUDY  # 62% cloud, no precip


def test_nil_values_become_none(sample_forecast):
    # Heat index is nil for the first hours of the sample feed.
    assert sample_forecast.hours[0].heat_index_f is None


def test_current_and_window(sample_forecast):
    fc = sample_forecast
    now = fc.hours[0].time
    assert fc.current(now) is fc.hours[0]
    window = fc.window(now, fc.hours[5].time)
    assert window == fc.hours[:6]


def test_thunderstorm_classification(sample_forecast):
    # Hour index 8 in the sample carries a thunderstorms weather-type.
    assert any(h.sky is Sky.THUNDERSTORM for h in sample_forecast.hours)


def test_precip_label_uses_weather_type(sample_forecast):
    # Hours without a forecast weather-type fall back to the generic label.
    no_type = next(h for h in sample_forecast.hours if not h.weather_types)
    assert no_type.precip_label == "Precip"

    # Hours with rain (and no thunderstorm) report "Rain".
    rainy = next(h for h in sample_forecast.hours
                 if h.weather_types == ["rain"])
    assert rainy.precip_label == "Rain"

    # Thunderstorm hours are a distinct category, even with rain listed too.
    storm = next(h for h in sample_forecast.hours
                 if "thunderstorms" in [t.lower() for t in h.weather_types])
    assert storm.precip_label == "T'Storm"


def test_precip_label_types():
    from trmnl_nws_weather.models import HourPoint
    from datetime import datetime

    def label(*types: str) -> str:
        return HourPoint(time=datetime(2026, 1, 1), weather_types=list(types)).precip_label

    assert label("thunderstorms", "rain") == "T'Storm"  # storms outrank rain
    assert label("snow") == "Snow"
    assert label("sleet") == "Sleet"
    assert label("freezing rain") == "Ice"  # "freezing" wins over "rain"
    assert label("rain") == "Rain"
    assert label() == "Precip"


def test_precip_type_none_when_unspecified():
    from trmnl_nws_weather.models import HourPoint
    from datetime import datetime

    # No weather-type -> None, so the renderer shows a droplet icon, not a word.
    assert HourPoint(time=datetime(2026, 1, 1)).precip_type is None
    assert HourPoint(time=datetime(2026, 1, 1), weather_types=["rain"]).precip_type == "Rain"


def test_effective_sky_downgrades_unlikely_precip():
    from trmnl_nws_weather.models import effective_sky

    # Rain/thunderstorm below 40% chance -> cloudy.
    assert effective_sky(Sky.RAIN, 15) is Sky.CLOUDY
    assert effective_sky(Sky.THUNDERSTORM, 39.9) is Sky.CLOUDY
    # At or above 40% -> unchanged.
    assert effective_sky(Sky.RAIN, 40) is Sky.RAIN
    assert effective_sky(Sky.THUNDERSTORM, 60) is Sky.THUNDERSTORM
    # Snow/sleet/ice are never downgraded; only rain and thunderstorms.
    assert effective_sky(Sky.SNOW, 10) is Sky.SNOW
    assert effective_sky(Sky.SLEET, 5) is Sky.SLEET
    # Unknown chance -> left unchanged (cannot be "less than 40%").
    assert effective_sky(Sky.RAIN, None) is Sky.RAIN
    # Non-precip skies pass through.
    assert effective_sky(Sky.SUNNY, 0) is Sky.SUNNY
