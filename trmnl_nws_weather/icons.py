"""Procedurally drawn weather icons.

The digital DWML feed has no icon field, so glyphs are drawn from primitives.
Each icon is rendered into a transparent supersampled buffer and downscaled with
LANCZOS resampling, giving smooth edges that survive the final 2-bit quantise.

All icons are monochrome: shapes are drawn in an opaque "ink" channel and the
caller composites them onto the page in the theme's foreground colour.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .models import Sky
from .utils import SUPERSAMPLING_FACTOR


def _new(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("L", (size * SUPERSAMPLING_FACTOR, size * SUPERSAMPLING_FACTOR), 0)
    return img, ImageDraw.Draw(img)


def _sun(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, lw: int,
         rays: bool = True) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    if not rays:
        return
    ray_in = r * 1.35
    ray_out = r * 1.95
    for k in range(8):
        a = math.radians(k * 45)
        x0, y0 = cx + ray_in * math.cos(a), cy + ray_in * math.sin(a)
        x1, y1 = cx + ray_out * math.cos(a), cy + ray_out * math.sin(a)
        draw.line((x0, y0, x1, y1), fill=255, width=lw)


def _moon(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    """Draw a stylised crescent moon centred at ``(cx, cy)``.

    The crescent is carved by subtracting an offset disc (drawn transparent) from
    a full disc.  The moon is drawn before any cloud, so the carve only affects
    the moon and a later cloud composites cleanly on top.
    """
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    # Subtract a disc shifted up and to the right, leaving a lower-left crescent.
    ox, oy = r * 0.50, -r * 0.22
    draw.ellipse((cx - r + ox, cy - r + oy, cx + r + ox, cy + r + oy), fill=0)


def _cloud(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float]) -> None:
    """Draw a filled cloud within ``box``."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    base_top = y0 + h * 0.55
    # Flat base of the cloud.
    draw.rounded_rectangle((x0, base_top, x1, y1), radius=h * 0.22, fill=255)
    # Three puffs along the top.
    draw.ellipse((x0, base_top - h * 0.22, x0 + w * 0.5, y1), fill=255)
    draw.ellipse((x0 + w * 0.22, y0, x0 + w * 0.78, y1), fill=255)
    draw.ellipse((x0 + w * 0.5, base_top - h * 0.12, x1, y1), fill=255)


def _streaks(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], *, kind: str, lw: int) -> None:
    """Draw precipitation beneath a cloud (rain lines, snow flakes, sleet mix)."""
    x0, y0, x1, y1 = box
    w = x1 - x0

    cols = [x0 + w * f for f in (0.25, 0.5, 0.75)]
    top = y1 + (y1 - y0) * 0.08
    bottom = top + (y1 - y0) * 0.55
    if kind == "rain":
        for x in cols:
            draw.line((x + w * 0.05, top, x - w * 0.05, bottom), fill=255, width=lw)
    elif kind == "snow":
        r = (y1 - y0) * 0.16
        for x in cols:
            cy = (top + bottom) / 2
            for k in range(3):
                a = math.radians(k * 60)
                draw.line((x - r * math.cos(a), cy - r * math.sin(a),
                           x + r * math.cos(a), cy + r * math.sin(a)),
                          fill=255, width=max(1, lw - 1))
    elif kind == "sleet":
        for i, x in enumerate(cols):
            if i % 2 == 0:
                draw.line((x + w * 0.05, top, x - w * 0.05, bottom),
                          fill=255, width=lw)
            else:
                rr = (y1 - y0) * 0.09
                cy = (top + bottom) / 2
                draw.ellipse((x - rr, cy - rr, x + rr, cy + rr), fill=255)


def _bolt(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    cx = x0 + w * 0.5
    top = y1 + h * 0.05
    pts = [
        (cx + w * 0.08, top),
        (cx - w * 0.18, top + h * 0.42),
        (cx + w * 0.02, top + h * 0.42),
        (cx - w * 0.12, top + h * 0.78),
        (cx + w * 0.22, top + h * 0.32),
        (cx + w * 0.02, top + h * 0.32),
    ]
    draw.polygon(pts, fill=255)


def _wind(draw: ImageDraw.ImageDraw, size: int, lw: int) -> None:
    """Three trailing wind lines with curl hooks."""
    s = size * SUPERSAMPLING_FACTOR
    for y, length in ((0.36, 0.62), (0.52, 0.78), (0.68, 0.5)):
        yy = s * y
        x_end = s * (0.12 + length)
        draw.line((s * 0.12, yy, x_end, yy), fill=255, width=lw)
        # Curl at the end of the two longer streaks.
        if length > 0.55:
            r = s * 0.07
            draw.arc((x_end - r, yy - r * 2, x_end + r, yy), start=90, end=330,
                     fill=255, width=lw)


def _fog(draw: ImageDraw.ImageDraw, size: int, lw: int) -> None:
    s = size * SUPERSAMPLING_FACTOR
    for y in (0.36, 0.5, 0.64, 0.78):
        yy = s * y
        inset = s * (0.14 if y in (0.5, 0.78) else 0.08)
        draw.line((s * 0.1 + inset, yy, s * 0.9 - inset, yy), fill=255, width=lw)


def render(sky: Sky, size: int, *, night: bool = False) -> Image.Image:
    """Render ``sky`` as an ``L`` image (size×size); 255 = ink, 0 = transparent.

    When ``night`` is true, the clear- and partly-clear-sky icons use a crescent
    moon in place of the sun; the cloud and precipitation icons are unchanged.
    """
    img, draw = _new(size)
    s = size * SUPERSAMPLING_FACTOR
    lw = max(2, round(s * 0.035))

    if sky is Sky.SUNNY:
        if night:
            _moon(draw, s * 0.5, s * 0.5, s * 0.26)
        else:
            _sun(draw, s * 0.5, s * 0.5, s * 0.24, lw)
    elif sky is Sky.PARTLY_CLOUDY:
        if night:
            _moon(draw, s * 0.66, s * 0.35, s * 0.19)
        else:
            _sun(draw, s * 0.66, s * 0.36, s * 0.17, lw)
        _cloud(draw, (s * 0.12, s * 0.40, s * 0.82, s * 0.80))
    elif sky is Sky.CLOUDY:
        _cloud(draw, (s * 0.1, s * 0.28, s * 0.9, s * 0.72))
    elif sky is Sky.WINDY:
        _wind(draw, size, lw)
    elif sky is Sky.FOG:
        _cloud(draw, (s * 0.12, s * 0.16, s * 0.88, s * 0.52))
        _fog(draw, size, lw)
    elif sky is Sky.RAIN:
        _cloud(draw, (s * 0.12, s * 0.18, s * 0.88, s * 0.56))
        _streaks(draw, (s * 0.12, s * 0.18, s * 0.88, s * 0.56), kind="rain", lw=lw)
    elif sky is Sky.SNOW:
        _cloud(draw, (s * 0.12, s * 0.18, s * 0.88, s * 0.56))
        _streaks(draw, (s * 0.12, s * 0.18, s * 0.88, s * 0.56), kind="snow", lw=lw)
    elif sky in (Sky.SLEET, Sky.ICE):
        _cloud(draw, (s * 0.12, s * 0.18, s * 0.88, s * 0.56))
        _streaks(draw, (s * 0.12, s * 0.18, s * 0.88, s * 0.56), kind="sleet", lw=lw)
    elif sky is Sky.THUNDERSTORM:
        _cloud(draw, (s * 0.12, s * 0.16, s * 0.88, s * 0.54))
        _bolt(draw, (s * 0.30, s * 0.16, s * 0.70, s * 0.54))

    return img.resize((size, size), Image.LANCZOS)


# --- Small glyphs for the metric boxes ------------------------------------

def glyph(name: str, size: int) -> Image.Image:
    """Render a small labelled-box glyph (droplet, humidity, wind, aqi)."""
    img, draw = _new(size)
    s = size * SUPERSAMPLING_FACTOR
    lw = max(2, round(s * 0.06))
    if name == "droplet":
        cx = s * 0.5
        top = s * 0.16
        bot = s * 0.82
        r = s * 0.26
        draw.ellipse((cx - r, bot - 2 * r, cx + r, bot), fill=255)
        draw.polygon([(cx, top), (cx - r * 0.92, bot - r * 0.9),
                      (cx + r * 0.92, bot - r * 0.9)], fill=255)
    elif name == "humidity":
        # Droplet outline with a small inner highlight implied by percent usage.
        cx = s * 0.5
        top = s * 0.16
        bot = s * 0.82
        r = s * 0.26
        draw.ellipse((cx - r, bot - 2 * r, cx + r, bot), outline=255, width=lw)
        draw.polygon([(cx, top), (cx - r, bot - r), (cx + r, bot - r)],
                     outline=255, width=lw)
    elif name == "wind":
        _wind(draw, size, lw)
    elif name == "aqi":
        # Simple circle with a dot in the middle for AQI
        cx = s * 0.5
        cy = s * 0.5
        r = s * 0.35
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=255, width=lw)
        draw.ellipse((cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2), fill=255)
    return img.resize((size, size), Image.LANCZOS)
