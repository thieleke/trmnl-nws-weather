"""Fonts and colour palette for rendering.

The image is rendered on an 8-bit grayscale canvas and quantised to 2 bits (four
grey levels) on save, matching the TRMNL 7.5" panel's bit depth.  Foreground and
background levels swap based on the configured :class:`~trmnl_nws_weather.config.Theme`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .config import Theme

# Four evenly spaced grey levels available in a 2-bit image.
BLACK = 0
DARK = 85
LIGHT = 170
WHITE = 255


class Palette:
    """Resolved foreground/background/muted levels for a theme."""

    __slots__ = ("bg", "fg", "muted")

    def __init__(self, theme: Theme) -> None:
        if theme is Theme.DARK:
            self.bg = BLACK
            self.fg = WHITE
            self.muted = LIGHT
        else:
            self.bg = WHITE
            self.fg = BLACK
            self.muted = DARK


# Fonts are vendored with the package (the freely-licensed Inter and DejaVu
# families) so the service is portable across operating systems and does not
# depend on whatever happens to be installed in the host's system font dir.
_FONT_DIR = Path(__file__).parent / "assets" / "fonts"


@dataclass(frozen=True, slots=True)
class FontFamily:
    """A regular/bold pair.

    For a variable font the same file is used for both weights and a named
    instance (e.g. ``"Regular"`` / ``"Bold"``) selects the weight.
    """

    regular: Path
    bold: Path
    regular_instance: str | None = None
    bold_instance: str | None = None


DEJAVU = FontFamily(
    regular=_FONT_DIR / "DejaVuSans.ttf",
    bold=_FONT_DIR / "DejaVuSans-Bold.ttf",
)
INTER = FontFamily(
    regular=_FONT_DIR / "Inter.ttf",
    bold=_FONT_DIR / "Inter.ttf",
    regular_instance="Regular",
    bold_instance="Bold",
)

# Inter is the default: it matches the TRMNL reference design more closely than
# DejaVu (tighter, more upright numerals and even uppercase tracking).
_family = INTER


def set_family(family: FontFamily) -> None:
    """Switch the active font family (clears the size cache)."""
    global _family
    _family = family
    font.cache_clear()


@lru_cache(maxsize=128)
def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Return a cached TrueType font at ``size`` px, falling back to default."""
    path = _family.bold if bold else _family.regular
    if not path.exists():
        return ImageFont.load_default()
    f = ImageFont.truetype(str(path), size)
    instance = _family.bold_instance if bold else _family.regular_instance
    if instance:
        try:
            f.set_variation_by_name(instance)
        except OSError:
            pass
    return f
