"""Shared utility functions and constants.

Centralises helpers used across multiple modules so they have a single
source of truth: clock formatting, substring matching, and the common
supersampling factor for icon and page rendering.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum


# -----------------------------------------------------------------------
# Supersampling
# -----------------------------------------------------------------------

# Factor applied to icon and page canvases before LANCZOS downscaling,
# giving smooth edges that survive the final 2-bit quantisation.
SUPERSAMPLING_FACTOR = 4


# -----------------------------------------------------------------------
# Time format
# -----------------------------------------------------------------------


class TimeFormat(str, Enum):
    """Clock display mode for time labels."""

    TWELVE_HOUR = "12"  # 12-hour with AM/PM (default)
    TWENTY_FOUR_HOUR = "24"  # 24-hour military time


# -----------------------------------------------------------------------
# Clock / label formatting
# -----------------------------------------------------------------------


def format_clock(dt: datetime, time_format: TimeFormat = TimeFormat.TWELVE_HOUR) -> str:
    """Full clock string with minutes.

    Examples: ``3:04 PM`` (12-hour) or ``15:04`` (24-hour).
    """
    if time_format is TimeFormat.TWENTY_FOUR_HOUR:
        return dt.strftime("%H:%M")
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ampm}"


def format_hour_label(dt: datetime, time_format: TimeFormat = TimeFormat.TWELVE_HOUR) -> str:
    """Hour-only label without minutes.

    Examples: ``3 PM`` (12-hour) or ``15`` (24-hour).
    """
    if time_format is TimeFormat.TWENTY_FOUR_HOUR:
        return str(dt.hour)
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour} {ampm}"


def format_day_hour_label(dt: datetime, time_format: TimeFormat = TimeFormat.TWELVE_HOUR) -> str:
    """Day abbreviation and hour.

    Examples: ``Mon 3 PM`` (12-hour) or ``Mon 15`` (24-hour).
    """
    if time_format is TimeFormat.TWENTY_FOUR_HOUR:
        return f"{dt.strftime('%a')} {dt.hour}"
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%a')} {hour} {ampm}"


# -----------------------------------------------------------------------
# Substring matching
# -----------------------------------------------------------------------


def any_match(haystacks: list[str], *needles: str) -> bool:
    """Return ``True`` when any *needle* is a substring of any *haystack*.

    Used for classifying weather types from the NWS feed where a single
    weather-token may contain multiple words (e.g. ``"thunderstorms"``).
    """
    return any(needle in h for h in haystacks for needle in needles)
