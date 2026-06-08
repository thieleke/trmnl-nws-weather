"""Tests for environment variable validation wrappers in config.py.

These tests exercise the string-parsing layer that sits between raw
environment variables and the shared validators in validate.py.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def _clear_env(prefix="TRMNL_"):
    """Remove all TRMNL_ env vars so tests start clean."""
    to_remove = [k for k in os.environ if k.startswith(prefix)]
    for k in to_remove:
        del os.environ[k]


# -----------------------------------------------------------------------
# _env_url
# -----------------------------------------------------------------------


class TestEnvURL:
    """Tests for config._env_url()."""

    def setup_method(self):
        _clear_env()

    def test_returns_default_when_not_set(self):
        from trmnl_nws_weather.config import _env_url
        result = _env_url("TRMNL_FAKE_URL", "")
        assert result == ""

    def test_returns_valid_url(self):
        from trmnl_nws_weather.config import _env_url
        with patch.dict(os.environ, {"TRMNL_FAKE_URL": "http://example.com/aqi"}):
            result = _env_url("TRMNL_FAKE_URL", "")
        assert result == "http://example.com/aqi"

    def test_rejects_file_scheme(self):
        from trmnl_nws_weather.config import _env_url
        with patch.dict(os.environ, {"TRMNL_FAKE_URL": "file:///etc/passwd"}):
            result = _env_url("TRMNL_FAKE_URL", "http://default.com")
        assert result == "http://default.com"

    def test_rejects_no_scheme(self):
        from trmnl_nws_weather.config import _env_url
        with patch.dict(os.environ, {"TRMNL_FAKE_URL": "example.com"}):
            result = _env_url("TRMNL_FAKE_URL", "http://default.com")
        assert result == "http://default.com"

    def test_allows_empty_string(self):
        from trmnl_nws_weather.config import _env_url
        with patch.dict(os.environ, {"TRMNL_FAKE_URL": ""}):
            result = _env_url("TRMNL_FAKE_URL", "http://default.com")
        assert result == ""

    def test_allows_private_ip(self):
        from trmnl_nws_weather.config import _env_url
        with patch.dict(os.environ, {"TRMNL_FAKE_URL": "http://10.0.0.3:8300/aqi"}):
            result = _env_url("TRMNL_FAKE_URL", "")
        assert result == "http://10.0.0.3:8300/aqi"


# -----------------------------------------------------------------------
# _env_coordinate
# -----------------------------------------------------------------------


class TestEnvCoordinate:
    """Tests for config._env_coordinate()."""

    def setup_method(self):
        _clear_env()

    def test_valid_latitude(self):
        from trmnl_nws_weather.config import _env_coordinate
        with patch.dict(os.environ, {"TRMNL_LAT": "42.0367"}):
            result = _env_coordinate("TRMNL_LAT", -90.0, 90.0, 40.0)
        assert result == pytest.approx(42.0367)

    def test_out_of_range_returns_default(self):
        from trmnl_nws_weather.config import _env_coordinate
        with patch.dict(os.environ, {"TRMNL_LAT": "999"}):
            result = _env_coordinate("TRMNL_LAT", -90.0, 90.0, 40.0)
        assert result == 40.0

    def test_non_numeric_returns_default(self):
        from trmnl_nws_weather.config import _env_coordinate
        with patch.dict(os.environ, {"TRMNL_LAT": "abc"}):
            result = _env_coordinate("TRMNL_LAT", -90.0, 90.0, 40.0)
        assert result == 40.0

    def test_truncates_to_four_decimals(self):
        from trmnl_nws_weather.config import _env_coordinate
        with patch.dict(os.environ, {"TRMNL_LAT": "40.04049999"}):
            result = _env_coordinate("TRMNL_LAT", -90.0, 90.0, 40.0)
        assert result == 40.0404

    def test_uses_default_when_not_set(self):
        from trmnl_nws_weather.config import _env_coordinate
        result = _env_coordinate("TRMNL_MISSING", -90.0, 90.0, 40.0404)
        assert result == pytest.approx(40.0404)


# -----------------------------------------------------------------------
# _env_int
# -----------------------------------------------------------------------


class TestEnvInt:
    """Tests for config._env_int()."""

    def setup_method(self):
        _clear_env()

    def test_valid_value(self):
        from trmnl_nws_weather.config import _env_int
        with patch.dict(os.environ, {"TRMNL_VAL": "1800"}):
            result = _env_int("TRMNL_VAL", 60, 86400, 1800)
        assert result == 1800

    def test_below_range_returns_default(self):
        from trmnl_nws_weather.config import _env_int
        with patch.dict(os.environ, {"TRMNL_VAL": "0"}):
            result = _env_int("TRMNL_VAL", 60, 86400, 1800)
        assert result == 1800

    def test_above_range_returns_default(self):
        from trmnl_nws_weather.config import _env_int
        with patch.dict(os.environ, {"TRMNL_VAL": "999999"}):
            result = _env_int("TRMNL_VAL", 60, 86400, 1800)
        assert result == 1800

    def test_non_integer_returns_default(self):
        from trmnl_nws_weather.config import _env_int
        with patch.dict(os.environ, {"TRMNL_VAL": "abc"}):
            result = _env_int("TRMNL_VAL", 60, 86400, 1800)
        assert result == 1800

    def test_uses_default_when_not_set(self):
        from trmnl_nws_weather.config import _env_int
        result = _env_int("TRMNL_MISSING", 60, 86400, 1800)
        assert result == 1800


# -----------------------------------------------------------------------
# _env_float
# -----------------------------------------------------------------------


class TestEnvFloat:
    """Tests for config._env_float()."""

    def setup_method(self):
        _clear_env()

    def test_valid_value(self):
        from trmnl_nws_weather.config import _env_float
        with patch.dict(os.environ, {"TRMNL_VAL": "0.5"}):
            result = _env_float("TRMNL_VAL", 0.0, 1.0, 0.0)
        assert result == 0.5

    def test_below_range_returns_default(self):
        from trmnl_nws_weather.config import _env_float
        with patch.dict(os.environ, {"TRMNL_VAL": "-1.0"}):
            result = _env_float("TRMNL_VAL", 0.0, 1.0, 0.0)
        assert result == 0.0

    def test_above_range_returns_default(self):
        from trmnl_nws_weather.config import _env_float
        with patch.dict(os.environ, {"TRMNL_VAL": "2.0"}):
            result = _env_float("TRMNL_VAL", 0.0, 1.0, 0.0)
        assert result == 0.0

    def test_non_numeric_returns_default(self):
        from trmnl_nws_weather.config import _env_float
        with patch.dict(os.environ, {"TRMNL_VAL": "abc"}):
            result = _env_float("TRMNL_VAL", 0.0, 1.0, 0.0)
        assert result == 0.0


# -----------------------------------------------------------------------
# _env_enum
# -----------------------------------------------------------------------


class TestEnvEnum:
    """Tests for config._env_enum()."""

    def setup_method(self):
        _clear_env()

    def test_valid_value(self):
        from trmnl_nws_weather.config import _env_enum, Units
        with patch.dict(os.environ, {"TRMNL_VAL": "metric"}):
            result = _env_enum("TRMNL_VAL", Units, Units.IMPERIAL)
        assert result == Units.METRIC

    def test_case_insensitive(self):
        from trmnl_nws_weather.config import _env_enum, Units
        with patch.dict(os.environ, {"TRMNL_VAL": "METRIC"}):
            result = _env_enum("TRMNL_VAL", Units, Units.IMPERIAL)
        assert result == Units.METRIC

    def test_invalid_returns_default(self):
        from trmnl_nws_weather.config import _env_enum, Units
        with patch.dict(os.environ, {"TRMNL_VAL": "malignant"}):
            result = _env_enum("TRMNL_VAL", Units, Units.IMPERIAL)
        assert result == Units.IMPERIAL

    def test_uses_default_when_not_set(self):
        from trmnl_nws_weather.config import _env_enum, Units
        result = _env_enum("TRMNL_MISSING", Units, Units.IMPERIAL)
        assert result == Units.IMPERIAL


# -----------------------------------------------------------------------
# Settings integration
# -----------------------------------------------------------------------


class TestSettingsValidation:
    """Integration tests for Settings loading with invalid env vars."""

    def setup_method(self):
        _clear_env()

    def test_invalid_latitude_falls_back(self, caplog):
        # Must reimport after env change to trigger default_factory
        import importlib
        import trmnl_nws_weather.config as config_mod
        with patch.dict(os.environ, {"TRMNL_LATITUDE": "999"}):
            importlib.reload(config_mod)
            settings = config_mod.Settings()
        assert settings.latitude == pytest.approx(config_mod.DEFAULT_LATITUDE)

    def test_invalid_units_falls_back(self, caplog):
        import importlib
        import trmnl_nws_weather.config as config_mod
        with patch.dict(os.environ, {"TRMNL_UNITS": "malignant"}):
            importlib.reload(config_mod)
            settings = config_mod.Settings()
        assert settings.units == config_mod.DEFAULT_UNITS

    def test_invalid_aqi_url_falls_back(self, caplog):
        import importlib
        import trmnl_nws_weather.config as config_mod
        with patch.dict(os.environ, {"TRMNL_AQI_URL": "file:///etc/passwd"}):
            importlib.reload(config_mod)
            settings = config_mod.Settings()
        assert settings.aqi_url == ""

    def test_valid_https_url_accepted(self):
        import importlib
        import trmnl_nws_weather.config as config_mod
        with patch.dict(os.environ, {"TRMNL_WEBHOOK_URL": "https://hooks.example.com/post"}):
            importlib.reload(config_mod)
            settings = config_mod.Settings()
        assert settings.webhook_url == "https://hooks.example.com/post"
