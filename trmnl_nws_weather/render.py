"""Render a :class:`~trmnl_nws_weather.models.Forecast` to a 2-bit 800x480 PNG.

Quality strategy: everything is drawn on an 8-bit grayscale canvas at 4x the
target resolution, then downscaled with LANCZOS resampling.  This antialiases
text, the temperature curve, and the icons.  The result is finally quantised to
four grey levels (2-bit) to match the TRMNL e-ink panel.

Layout follows the reference photo with the plan revisions applied:
  * the header location line is removed and the date enlarged;
  * the "updated" timestamp is made small and secondary;
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PIL import Image
from PIL.Image import Resampling
from PIL import ImageDraw

from . import icons, units
from .config import Settings
from .models import CurrentObservation, Forecast, HourPoint, effective_sky
from .theme import Palette, font
from .utils import SUPERSAMPLING_FACTOR, format_clock, format_day_hour_label, format_hour_label

WIDTH, HEIGHT = 800, 480
MARGIN = 16  # content inset (no outer frame is drawn)

# Four grey levels of a 2-bit image.
_LEVELS = (0, 64, 128, 255)

# Precomputed quantization LUT: maps each 8-bit value to the nearest palette index (0..3).
# Computed once at module load to avoid recomputing on every render.
_INDEX_LUT = bytes(
    min(range(4), key=lambda i: abs(v - _LEVELS[i])) for v in range(256)
)


class _Canvas:
    """Thin wrapper that scales all coordinates/sizes by the supersample factor."""

    def __init__(self, palette: Palette) -> None:
        self.p = palette
        self.img = Image.new("L", (WIDTH * SUPERSAMPLING_FACTOR, HEIGHT * SUPERSAMPLING_FACTOR), palette.bg)
        self.d = ImageDraw.Draw(self.img)

    # -- primitives (inputs in final 800x480 coordinates) ------------------
    def line(self, xy: tuple[float, float] | tuple[float, float, float, float], width: float = 1, fill: float | None = None) -> None:
        fill = self.p.fg if fill is None else fill
        self.d.line([c * SUPERSAMPLING_FACTOR for c in xy], fill=fill, width=max(1, round(width * SUPERSAMPLING_FACTOR)))

    def rect(self, box: tuple[float, float, float, float], width: float = 1, outline: float | None = None) -> None:
        outline = self.p.fg if outline is None else outline
        self.d.rectangle([c * SUPERSAMPLING_FACTOR for c in box], outline=outline,
                         width=max(1, round(width * SUPERSAMPLING_FACTOR)))

    def fill_rect(self, box: tuple[float, float, float, float], fill: float) -> None:
        self.d.rectangle([c * SUPERSAMPLING_FACTOR for c in box], fill=fill)

    def dot(self, x: float, y: float, r: float, fill: float | None = None) -> None:
        fill = self.p.fg if fill is None else fill
        self.d.ellipse([(x - r) * SUPERSAMPLING_FACTOR, (y - r) * SUPERSAMPLING_FACTOR, (x + r) * SUPERSAMPLING_FACTOR, (y + r) * SUPERSAMPLING_FACTOR],
                       fill=fill)

    def text(self, xy: tuple[float, float], s: str, size: float, *, bold: bool = False, anchor: str = "la", fill: float | None = None) -> None:
        fill = self.p.fg if fill is None else fill
        self.d.text((xy[0] * SUPERSAMPLING_FACTOR, xy[1] * SUPERSAMPLING_FACTOR), s, font=font(round(size * SUPERSAMPLING_FACTOR), bold=bold),
                    fill=fill, anchor=anchor)

    def text_width(self, s: str, size: float, *, bold: bool = False) -> float:
        f = font(round(size * SUPERSAMPLING_FACTOR), bold=bold)
        return self.d.textlength(s, font=f) / SUPERSAMPLING_FACTOR

    def paste_icon(self, glyph: Image.Image, x: float, y: float, fill: float | None = None) -> None:
        """Composite a monochrome icon mask onto the page in ``fill`` colour."""
        fill = self.p.fg if fill is None else fill
        solid = Image.new("L", glyph.size, fill)
        self.img.paste(solid, (round(x * SUPERSAMPLING_FACTOR), round(y * SUPERSAMPLING_FACTOR)), glyph)


def _quantize_2bit(img: Image.Image) -> Image.Image:
    """Downscale to target size and map to a 4-colour (2-bit) palette image."""
    small = img.resize((WIDTH, HEIGHT), Resampling.LANCZOS)

    indexed = small.point(_INDEX_LUT)
    out = indexed.convert("P")
    palette = []
    for level in _LEVELS:
        palette += [level, level, level]
    palette += [0, 0, 0] * (256 - len(_LEVELS))
    out.putpalette(palette)
    return out


# --------------------------------------------------------------------------
# Section renderers
# --------------------------------------------------------------------------

def _header(c: _Canvas, now: datetime, settings: Settings,
            headline: str | None) -> None:
    # Enlarged date (location line removed per the plan).  Day-of-month is built
    # explicitly to avoid the non-portable %-d / %#d strftime directives.
    date_text = f"{now.strftime('%A').upper()} · {now.strftime('%B').upper()} {now.day}"
    c.text((MARGIN, 40), date_text, 34, bold=True, anchor="lm")
    date_w = c.text_width(date_text, 34, bold=True)

    # Secondary, de-emphasised "updated" timestamp, top-right.
    c.text((WIDTH - MARGIN, 24), "UPDATED", 11, anchor="rm", fill=c.p.muted)
    c.text((WIDTH - MARGIN, 44), format_clock(now, settings.time_format), 17, anchor="rm", fill=c.p.muted)

    # Upcoming-period forecast phrase, in the otherwise-empty space beside the
    # date.  Reduced to a human-friendly summary and ellipsised to fit.
    #if headline:
    #    hx = MARGIN + date_w + 24
    #    max_right = WIDTH - MARGIN - 96  # leave room for the UPDATED/time block
    #    avail = max_right - hx
    #    if avail > 70:
    #        text = _fit_text(c, _humanize_headline(headline), 15, avail)
    #        c.text((hx, 43), text, 15, anchor="lm", fill=c.p.muted)


def _humanize_headline(text: str) -> str:
    """Reduce an NWS forecast phrase to a short, human-friendly summary.

    NWS phrases chain clauses with " then " (e.g. "Chance Showers then Showers
    Likely"); the first clause is the nearest-term condition, so we keep it and
    drop the rest.
    """
    return text.split(" then ")[0].strip()


def _fit_text(c: _Canvas, text: str, size: int, max_w: float, *,
              bold: bool = False) -> str:
    """Trim ``text`` to ``max_w`` px, ellipsising at a word boundary."""
    if c.text_width(text, size, bold=bold) <= max_w:
        return text
    words = text.split()
    while len(words) > 1:
        words.pop()
        candidate = " ".join(words) + "…"
        if c.text_width(candidate, size, bold=bold) <= max_w:
            return candidate
    trimmed = text
    while trimmed and c.text_width(trimmed + "…", size, bold=bold) > max_w:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else ""




def _graph(c: _Canvas, forecast: Forecast, now: datetime, settings: Settings) -> None:
    # Graph spans 90% of the full width, horizontally centred.
    left, right = 40, WIDTH - 40
    top, bottom = 108, 152  # temperature curve vertical extent

    # Anchor the window on the next whole hour so the (partly elapsed) current
    # hour is never plotted as the first dot.  ``graph_now_position`` then offsets
    # that anchor within the window as before.
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    pos = settings.graph_now_position
    span = timedelta(hours=settings.graph_window_hours)
    start = next_hour - span * pos
    end = start + span
    pts = forecast.window(start, end)
    pts = [h for h in pts if h.temperature_f is not None]
    if len(pts) < 2:
        return

    temps: list[float] = [h.temperature_f for h in pts]  # type: ignore[misc]
    tmin, tmax = min(temps), max(temps)
    if tmax == tmin:
        tmax += 1

    # Map the x-axis over the actual span of plotted points (not the nominal
    # window) so the curve always fills the full width edge-to-edge.  The NWS
    # feed begins at the upcoming whole hour, so the first point would otherwise
    # sit inset from the left, shifting the whole curve sideways.
    t0, t1 = pts[0].time, pts[-1].time
    total = (t1 - t0).total_seconds() or 1.0

    def x_of(t: datetime) -> float:
        return left + (right - left) * ((t - t0).total_seconds() / total)

    def y_of(temp_f: float) -> float:
        return bottom - (bottom - top) * ((temp_f - tmin) / (tmax - tmin))

    # Curve.
    coords = [(x_of(h.time), y_of(h.temperature_f)) for h in pts]  # type: ignore[misc]
    c.d.line([(x * SUPERSAMPLING_FACTOR, y * SUPERSAMPLING_FACTOR) for x, y in coords], fill=c.p.fg,
             width=max(1, round(2 * SUPERSAMPLING_FACTOR)), joint="curve")
    for x, y in coords:
        c.dot(x, y, 2.2)

    # High / low markers with value + time.
    hi = max(pts, key=lambda h: h.temperature_f)  # type: ignore[type-var]
    lo = min(pts, key=lambda h: h.temperature_f)  # type: ignore[type-var]

    # A small condition icon just below each hour's dot.  Tucking it below the
    # dot keeps it clear of the curve (the local slope can't rise into it).  The
    # LOW dot is skipped because its label sits below the line in that space; the
    # HIGH dot's label is above the line, so its icon still fits.
    icon_px = 36
    for h, (x, y) in zip(pts, coords):
        if h is lo:
            continue
        sky = effective_sky(h.sky, h.pop_percent)
        glyph = icons.render(sky, round(icon_px * SUPERSAMPLING_FACTOR))
        c.paste_icon(glyph, round(x - icon_px / 2), round(y + 8), fill=c.p.muted)

    _peak_label(c, "HIGH", hi, x_of(hi.time), y_of(hi.temperature_f), settings, above=True)
    _peak_label(c, "LOW", lo, x_of(lo.time), y_of(lo.temperature_f), settings, above=False)

    # Label the end dots with their temperature and time, always above the line
    # so they stay clear of each dot's condition icon below.  Skipped when an
    # end point is already the high or low (those carry their own labels).
    for end in (pts[0], pts[-1]):
        if end is not hi and end is not lo:
            _peak_label(c, "", end, x_of(end.time), y_of(end.temperature_f),
                        settings, above=True)

    # "NOW" vertical marker.  When anchored near the left edge, left-align the
    # label so it stays clear of the border.
    #nx = x_of(now)
    #c.line((nx, top - 6, nx, bottom + 6), width=1, fill=c.p.muted)
    #label_anchor = "lm" if nx < 120 else "mm"
    #c.text((nx + (3 if nx < 120 else 0), top - 18), "", 12,
    #       anchor=label_anchor, fill=c.p.muted)


def _peak_label(c: _Canvas, tag: str, h: HourPoint, x: float, y: float,
                settings: Settings, *, above: bool) -> None:
    value = units.format_temp(h.temperature_f, settings.units)
    when = format_hour_label(h.time, settings.time_format)
    # Keep the label over its own dot, nudging it in only as far as its own width
    # requires so it never detaches from the dot (which would make an edge dot
    # look mislabelled).
    half = max(c.text_width(tag, 11), c.text_width(value, 19, bold=True),
               c.text_width(when, 11)) / 2
    anchor_x = min(max(x, MARGIN + half), WIDTH - MARGIN - half)
    if above:
        c.text((anchor_x, y - 38), tag, 11, anchor="mm", fill=c.p.muted)
        c.text((anchor_x, y - 22), value, 19, bold=True, anchor="mm")
        c.text((anchor_x, y - 8), when, 11, anchor="mm", fill=c.p.muted)
    else:
        c.text((anchor_x, y + 12), tag, 11, anchor="mm", fill=c.p.muted)
        c.text((anchor_x, y + 28), value, 19, bold=True, anchor="mm")
        c.text((anchor_x, y + 42), when, 11, anchor="mm", fill=c.p.muted)


def _current(c: _Canvas, forecast: Forecast, now: datetime, settings: Settings,
             observation: CurrentObservation | None) -> None:
    cur = forecast.current(now)

    # Prefer actual observed conditions; fall back to the current forecast hour
    # field-by-field when an observation (or a field within it) is unavailable.
    raw_sky = observation.sky if observation else cur.sky
    # An unlikely rain/thunderstorm (current-hour chance < 40%) reads as cloudy.
    sky = effective_sky(raw_sky, cur.pop_percent)
    temp_f = (observation.temperature_f if observation and
              observation.temperature_f is not None else cur.temperature_f)
    humidity = (observation.humidity_percent if observation and
                observation.humidity_percent is not None else cur.humidity_percent)
    wind = (observation.wind_mph if observation and
            observation.wind_mph is not None else cur.wind_mph)
    if sky != raw_sky:  # downgraded to cloudy
        label = sky.label.upper()
    elif observation and observation.weather_text:
        label = observation.weather_text.upper()
    else:
        label = sky.label.upper()

    top = 210

    # Right-half metric-grid geometry, computed up front so the condition label
    # below can be bounded to the empty strip to the left of the grid (gx0).
    gx0, gx1 = 404, WIDTH - MARGIN
    gy0, gy1 = top + 4, top + 134
    midx = (gx0 + gx1) / 2
    midy = (gy0 + gy1) / 2

    # --- Left half: icon, big temperature, condition label ---
    icon_size = 104
    icon = icons.render(sky, round(icon_size * SUPERSAMPLING_FACTOR))
    c.paste_icon(icon, 28, top + 6)

    temp_num = units.format_temp(temp_f, settings.units).replace("°", "")
    unit = "°C" if settings.units.value == "metric" else "°F"
    tx = 158
    ty = top + 58
    c.text((tx, ty), temp_num, 90, bold=True, anchor="lm")
    num_w = c.text_width(temp_num, 90, bold=True)
    c.text((tx + num_w + 6, ty - 26), unit, 30, bold=True, anchor="lm")

    # Condition label.  It may be a long NWS phrase ("THUNDERSTORM IN VICINITY
    # RAIN FOG/MIST"), so use the full width up to the metric grid, shrink the
    # font to fit, and only ellipsise at a word boundary as a last resort.
    label_max_w = gx0 - MARGIN - 12
    label_size = 22
    while label_size > 12 and c.text_width(label, label_size, bold=True) > label_max_w:
        label_size -= 1
    label = _fit_text(c, label, label_size, label_max_w, bold=True)
    # Centre the condition label within the strip left of the metric grid.
    c.text(((MARGIN + gx0) / 2, ty + 58), label, label_size, bold=True, anchor="mm")

    # --- Right half: 2x2 metric boxes ---
    aqi_val = str(observation.aqi) if observation and observation.aqi is not None else "--"
    boxes = {
        (0, 0): ("AQI", aqi_val, "aqi"),
        (1, 0): ("PRECIP CHANCE", _pop_text(cur), "droplet"),  # POP is forecast-only
        (0, 1): ("HUMIDITY", _pct(humidity), "humidity"),
        (1, 1): ("WIND", units.format_wind(wind, settings.units), "wind"),
    }
    cells = {
        (0, 0): (gx0, gy0, midx, midy),
        (1, 0): (midx, gy0, gx1, midy),
        (0, 1): (gx0, midy, midx, gy1),
        (1, 1): (midx, midy, gx1, gy1),
    }
    for key, cell in cells.items():
        c.rect(cell, width=1, outline=c.p.muted)
        content = boxes[key]
        if content is None:
            continue
        label, value, glyph_name = content
        bx0, by0, bx1, by1 = cell
        gly = icons.glyph(glyph_name, round(18 * SUPERSAMPLING_FACTOR))
        c.paste_icon(gly, round(bx0 + 16), round(by0 + 14), fill=c.p.fg)
        c.text((bx0 + 40, by0 + 23), label, 13, anchor="lm", fill=c.p.muted)
        c.text(((bx0 + bx1) / 2, by0 + 48), value, 27, bold=True, anchor="mm")


def _pop_text(h: HourPoint) -> str:
    return f"{round(h.pop_percent)}%" if h.pop_percent is not None else "--"


def _pct(value: float | None) -> str:
    return f"{round(value)}%" if value is not None else "--"


def _forecast_strip(c: _Canvas, forecast: Forecast, now: datetime,
                    settings: Settings) -> None:
    top = 354
    c.line((MARGIN, top, WIDTH - MARGIN, top), width=1)

    # Preview the next six 6-hourly boundaries (00:00, 06:00, 12:00, 18:00),
    # beginning at the first boundary strictly after now, for an even multi-day
    # outlook.  Each target is snapped to the nearest available forecast hour.
    first = now.replace(minute=0, second=0, microsecond=0)
    while first <= now or first.hour % 6 != 0:
        first += timedelta(hours=1)
    cols = [forecast.current(first + timedelta(hours=6 * i)) for i in range(6)]
    n = len(cols)

    x0, x1 = MARGIN, WIDTH - MARGIN
    col_w = (x1 - x0) / n
    for i, h in enumerate(cols):
        cx = x0 + col_w * (i + 0.5)
        if i > 0:
            sx = x0 + col_w * i
            c.line((sx, top + 8, sx, HEIGHT - 18), width=1, fill=c.p.muted)

        c.text((cx, top + 18), format_day_hour_label(h.time, settings.time_format), 14, anchor="mm",
               fill=c.p.muted)

        sky = effective_sky(h.sky, h.pop_percent)
        icon = icons.render(sky, round(30 * SUPERSAMPLING_FACTOR))
        c.paste_icon(icon, round(cx - 38), top + 30)
        c.text((cx + 6, top + 46), units.format_temp(h.temperature_f, settings.units,
               with_unit=True), 20, bold=True, anchor="lm")

        # Precipitation chance.  Prefix with the specific type (Title case) when
        # the feed gives one; otherwise show a generic droplet icon in place of
        # the word "Precip".  A rain/thunderstorm downgraded to cloudy (chance
        # < 40%) is treated as unspecified here too.  Shrunk if needed so it
        # never spills into the next cell.
        pop = _pop_text(h)
        py = top + 82
        ptype = None if sky != h.sky else h.precip_type
        if ptype is None:
            isz = 17.5
            gap = 4
            total = isz + gap + c.text_width(pop, 16.25)
            sx = cx - total / 2
            drop = icons.glyph("droplet", round(isz * SUPERSAMPLING_FACTOR))
            c.paste_icon(drop, round(sx), round(py - isz / 2), fill=c.p.muted)
            c.text((sx + isz + gap, py), pop, 16.25, anchor="lm", fill=c.p.muted)
        else:
            precip = f"{ptype} {pop}"
            psize = 16.25
            while psize > 11 and c.text_width(precip, psize) > col_w - 12:
                psize -= 1
            c.text((cx, py), precip, psize, anchor="mm", fill=c.p.muted)


# --------------------------------------------------------------------------

def render(forecast: Forecast, settings: Settings,
           now: datetime | None = None,
           observation: CurrentObservation | None = None,
           headline: str | None = None) -> Image.Image:
    """Render the forecast to a 2-bit (4 grey level) 800x480 ``P`` image.

    When ``observation`` is supplied, the current-conditions section reflects
    actual measured weather; otherwise it falls back to the current forecast
    hour.  ``headline`` is an optional upcoming-period forecast phrase shown in
    the header beside the date.
    """
    if now is None:
        # Anchor "now" to the forecast's own timezone so the marker lines up.
        ref = forecast.hours[0].time if forecast.hours else datetime.now().astimezone()
        now = datetime.now(ref.tzinfo)

    palette = Palette(settings.theme)
    c = _Canvas(palette)

    _header(c, now, settings, headline)
    # Dividers bracketing the temperature graph (below the header, above the
    # current conditions).
    c.line((MARGIN, 64, WIDTH - MARGIN, 64), width=1)
    _graph(c, forecast, now, settings)
    c.line((MARGIN, 204, WIDTH - MARGIN, 204), width=1)
    _current(c, forecast, now, settings, observation)
    _forecast_strip(c, forecast, now, settings)

    return _quantize_2bit(c.img)
