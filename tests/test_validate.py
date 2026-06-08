"""Tests for shared input validation in trmnl_nws_weather.validate."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from trmnl_nws_weather import validate


# -----------------------------------------------------------------------
# URL validation
# -----------------------------------------------------------------------


class TestValidateURL:
    """Tests for validate.validate_url()."""

    def test_empty_string_passes_through(self):
        assert validate.validate_url("", "test") == ""

    def test_valid_http_url(self):
        assert (
            validate.validate_url("http://example.com/path", "test")
            == "http://example.com/path"
        )

    def test_valid_https_url(self):
        assert (
            validate.validate_url("https://example.com", "test")
            == "https://example.com"
        )

    def test_valid_url_with_port(self):
        assert (
            validate.validate_url("http://10.0.0.3:8300/aqi", "test")
            == "http://10.0.0.3:8300/aqi"
        )

    def test_file_scheme_rejected_soft(self):
        result = validate.validate_url("file:///etc/passwd", "test", fail_hard=False)
        assert result == ""

    def test_gopher_scheme_rejected_soft(self):
        result = validate.validate_url("gopher://example.com", "test", fail_hard=False)
        assert result == ""

    def test_no_scheme_rejected_soft(self):
        result = validate.validate_url("example.com/path", "test", fail_hard=False)
        assert result == ""

    def test_invalid_scheme_exits_hard(self):
        with pytest.raises(SystemExit):
            validate.validate_url("file:///etc/passwd", "test", fail_hard=True)

    def test_no_hostname_rejected_soft(self):
        result = validate.validate_url("http://", "test", fail_hard=False)
        assert result == ""

    def test_no_hostname_exits_hard(self):
        with pytest.raises(SystemExit):
            validate.validate_url("http://", "test", fail_hard=True)

    def test_private_ip_allowed(self):
        """Private IPs are explicitly allowed by design."""
        url = "http://169.254.169.254/latest/meta-data/"
        assert validate.validate_url(url, "test") == url

    def test_localhost_allowed(self):
        """localhost is allowed by design."""
        url = "http://localhost:6379/"
        assert validate.validate_url(url, "test") == url

    def test_logs_warning_on_rejection(self, caplog):
        validate.validate_url("file:///etc/passwd", "MY_VAR", fail_hard=False)
        assert "MY_VAR" in caplog.text
        assert "falling back to default" in caplog.text


# -----------------------------------------------------------------------
# Coordinate validation
# -----------------------------------------------------------------------


class TestValidateCoordinate:
    """Tests for validate.validate_coordinate()."""

    def test_valid_latitude(self):
        assert validate.validate_coordinate(40.0404, "lat", -90.0, 90.0, 0.0) == pytest.approx(40.0404)

    def test_valid_longitude(self):
        assert validate.validate_coordinate(-122.3756, "lon", -180.0, 180.0, 0.0) == pytest.approx(-122.3756)

    def test_truncates_to_four_decimals(self):
        result = validate.validate_coordinate(40.04049999, "lat", -90.0, 90.0, 0.0)
        assert result == 40.0404

    def test_inclusive_upper_bound(self):
        assert validate.validate_coordinate(90.0, "lat", -90.0, 90.0, 0.0) == 90.0

    def test_inclusive_lower_bound(self):
        assert validate.validate_coordinate(-90.0, "lat", -90.0, 90.0, 0.0) == -90.0

    def test_out_of_range_returns_default_soft(self):
        result = validate.validate_coordinate(95.0, "lat", -90.0, 90.0, 40.0404)
        assert result == 40.0404

    def test_out_of_range_exits_hard(self):
        with pytest.raises(SystemExit):
            validate.validate_coordinate(95.0, "lat", -90.0, 90.0, 40.0404, fail_hard=True)

    def test_logs_warning_on_out_of_range(self, caplog):
        validate.validate_coordinate(95.0, "MY_LAT", -90.0, 90.0, 40.0, fail_hard=False)
        assert "MY_LAT" in caplog.text
        assert "out of range" in caplog.text


# -----------------------------------------------------------------------
# Integer validation
# -----------------------------------------------------------------------


class TestValidateInt:
    """Tests for validate.validate_int()."""

    def test_valid_value(self):
        assert validate.validate_int(1800, "refresh", 60, 86400, 1800) == 1800

    def test_boundary_low(self):
        assert validate.validate_int(60, "refresh", 60, 86400, 1800) == 60

    def test_boundary_high(self):
        assert validate.validate_int(86400, "refresh", 60, 86400, 1800) == 86400

    def test_below_range_returns_default_soft(self):
        result = validate.validate_int(0, "refresh", 60, 86400, 1800)
        assert result == 1800

    def test_above_range_returns_default_soft(self):
        result = validate.validate_int(999999, "refresh", 60, 86400, 1800)
        assert result == 1800

    def test_out_of_range_exits_hard(self):
        with pytest.raises(SystemExit):
            validate.validate_int(0, "refresh", 60, 86400, 1800, fail_hard=True)

    def test_logs_warning_on_rejection(self, caplog):
        validate.validate_int(-1, "MY_INT", 0, 100, 50, fail_hard=False)
        assert "MY_INT" in caplog.text
        assert "out of range" in caplog.text


# -----------------------------------------------------------------------
# Float validation
# -----------------------------------------------------------------------


class TestValidateFloat:
    """Tests for validate.validate_float()."""

    def test_valid_value(self):
        assert validate.validate_float(0.5, "pos", 0.0, 1.0, 0.0) == 0.5

    def test_boundary_low(self):
        assert validate.validate_float(0.0, "pos", 0.0, 1.0, 0.0) == 0.0

    def test_boundary_high(self):
        assert validate.validate_float(1.0, "pos", 0.0, 1.0, 0.0) == 1.0

    def test_below_range_returns_default_soft(self):
        result = validate.validate_float(-0.5, "pos", 0.0, 1.0, 0.0)
        assert result == 0.0

    def test_above_range_returns_default_soft(self):
        result = validate.validate_float(2.0, "pos", 0.0, 1.0, 0.0)
        assert result == 0.0

    def test_out_of_range_exits_hard(self):
        with pytest.raises(SystemExit):
            validate.validate_float(-1.0, "pos", 0.0, 1.0, 0.0, fail_hard=True)


# -----------------------------------------------------------------------
# Port validation
# -----------------------------------------------------------------------


class TestValidatePort:
    """Tests for validate.validate_port()."""

    def test_valid_port(self):
        assert validate.validate_port(8400) == 8400

    def test_port_one(self):
        assert validate.validate_port(1) == 1

    def test_port_65535(self):
        assert validate.validate_port(65535) == 65535

    def test_zero_returns_default_soft(self):
        result = validate.validate_port(0, fail_hard=False)
        assert result == 8400

    def test_too_high_returns_default_soft(self):
        result = validate.validate_port(70000, fail_hard=False)
        assert result == 8400

    def test_negative_returns_default_soft(self):
        result = validate.validate_port(-1, fail_hard=False)
        assert result == 8400

    def test_invalid_port_exits_hard(self):
        with pytest.raises(SystemExit):
            validate.validate_port(0, fail_hard=True)

    def test_logs_warning_on_rejection(self, caplog):
        validate.validate_port(0, "--my-port", fail_hard=False)
        assert "--my-port" in caplog.text
