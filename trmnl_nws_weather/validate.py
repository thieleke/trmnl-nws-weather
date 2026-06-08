"""Shared input validation for environment variables and CLI arguments.

All validators return the validated value on success.  For environment
variables they return the *default* on failure (after logging a warning).
For CLI arguments they raise ``SystemExit`` so argparse-style hard failures
are preserved.
"""

from __future__ import annotations

import logging
import sys
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlparse

log = logging.getLogger("trmnl_nws_weather")


# -----------------------------------------------------------------------
# URL validation
# -----------------------------------------------------------------------


def validate_url(value: str, source: str, *, default: str = "",
                 fail_hard: bool = False) -> str:
    """Validate that *value* is a well-formed HTTP(S) URL.

    Only ``http`` and ``https`` schemes are permitted.  Empty strings are
    allowed through (they signal "no URL configured").

    Parameters
    ----------
    value:
        The URL string to validate.
    source:
        Human-readable label used in warnings (e.g. ``"--webhook"`` or
        ``"TRMNL_AQI_URL"``).
    default:
        Value returned when validation fails in soft mode (default ``""``).
    fail_hard:
        When ``True`` exit the process on invalid input (CLI mode).  When
        ``False`` return *default* after logging a warning (env-var mode).
    """
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        msg = (f"{source} has an invalid scheme {parsed.scheme!r} "
               f"(only http/https allowed)")
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default", msg)
        return default
    if not parsed.hostname:
        msg = f"{source} has no hostname"
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default", msg)
        return default
    return value


# -----------------------------------------------------------------------
# Coordinate validation
# -----------------------------------------------------------------------


def validate_coordinate(value: float, source: str, low: float, high: float,
                        default: float, *, fail_hard: bool = False) -> float:
    """Validate a latitude or longitude value.

    The value must be within ``[low, high]``.  On success the value is
    truncated to 4 decimal places (toward zero) to match the NWS API format.
    """
    if not low <= value <= high:
        msg = (f"{source} value {value:.4f} is out of range "
               f"[{low:.4f}, {high:.4f}]")
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default (%s)", msg, default)
        return default
    quantized = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return float(quantized)


# -----------------------------------------------------------------------
# Integer range validation
# -----------------------------------------------------------------------


def validate_int(value: int, source: str, low: int, high: int,
                 default: int, *, fail_hard: bool = False) -> int:
    """Validate an integer within ``[low, high]``."""
    if not low <= value <= high:
        msg = (f"{source} value {value} is out of range [{low}, {high}]")
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default (%s)", msg, default)
        return default
    return value


# -----------------------------------------------------------------------
# Choice validation
# -----------------------------------------------------------------------


def validate_choice(value: int, source: str, choices: tuple[int, ...],
                    default: int, *, fail_hard: bool = False) -> int:
    """Validate that *value* is one of the allowed ``choices``."""
    if value not in choices:
        allowed = ", ".join(str(c) for c in choices)
        msg = f"{source} value {value} is not allowed (choose from {allowed})"
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default (%s)", msg, default)
        return default
    return value


# -----------------------------------------------------------------------
# Float range validation
# -----------------------------------------------------------------------


def validate_float(value: float, source: str, low: float, high: float,
                   default: float, *, fail_hard: bool = False) -> float:
    """Validate a float within ``[low, high]``."""
    if not low <= value <= high:
        msg = (f"{source} value {value} is out of range [{low:.4f}, {high:.4f}]")
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default (%s)", msg, default)
        return default
    return value


# -----------------------------------------------------------------------
# Port validation
# -----------------------------------------------------------------------


def validate_port(value: int, source: str = "--port",
                  *, fail_hard: bool = False) -> int:
    """Validate a TCP port number (1-65535)."""
    if not 1 <= value <= 65535:
        msg = f"{source} value {value} is not a valid port (1-65535)"
        if fail_hard:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        log.warning("%s; falling back to default (8400)", msg)
        return 8400
    return value
