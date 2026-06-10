"""The weather display service.

Retrieves the NWS forecast and current observation, renders a monochrome PNG at
the configured panel size and bit depth (2-bit 800x480 by default), and writes
it to the configured images directory.  Generated files are named
``img_<lat>_<lon>_<width>_<height>_<bit_depth>_<l|d>_<i|m>_<12|24>_<unix-ts>.png``
so they can be reused as a cache keyed on the coordinates, the panel geometry,
and the display options (theme, units, time format) — every input that changes
the rendered pixels (see :func:`render_once` and :attr:`Settings.cache_tag`).
Renders for different devices or settings therefore never collide or serve each
other from the cache.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TypedDict

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from . import aqi, nws, render
from . import config
from .config import Settings

log = logging.getLogger("trmnl_nws_weather")

_DESCRIPTION_KEY = "Description"

# Hard ceiling on the number of generated images kept in the output directory,
# across all coordinates/devices/settings.  Enforced before the age-based prune
# so a runaway directory can never grow large enough to slow the per-tag globs.
MAX_CACHED_IMAGES = 50_000

# Floor on the cache window used by the web server, regardless of the configured
# cache_seconds.  An unauthenticated GET /weather renders on a cache miss, which
# fetches from weather.gov; this minimum bounds how often a flood of requests can
# trigger those upstream fetches even when caching is otherwise disabled.
MIN_WEBSERVER_CACHE_SECONDS = 60

# GUID pattern (case-insensitive) used to scrub webhook URLs before logging.
_GUID_RE = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    re.IGNORECASE,
)


class RenderResult(TypedDict):
    """Result of a single render (or cache hit)."""

    filename: str
    cached: bool
    description: str


def _timestamp_of(path: Path) -> int | None:
    """Extract the trailing unix timestamp from a generated image filename.

    The timestamp is always the last ``_``-separated field, so this works
    regardless of how many fields (coordinates, panel geometry) precede it.
    """
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None


def find_cached(output_dir: Path, cache_tag: str, now_ts: int,
                window_seconds: int) -> Path | None:
    """Return the most recent cached image for ``cache_tag`` within the window.

    A match is an ``img_<cache_tag>_<ts>.png`` file whose timestamp is within
    ``window_seconds`` of ``now_ts``.  ``cache_tag`` encodes both the
    coordinates and the panel geometry, so a render only matches one made for
    the same device.  Returns None if there is no fresh image.
    """
    if not output_dir.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for path in output_dir.glob(f"img_{cache_tag}_*.png"):
        ts = _timestamp_of(path)
        # A future-dated file (e.g. after a backward clock correction) is not
        # "fresh"; require the age to be within [0, window_seconds].
        if ts is None or not 0 <= now_ts - ts <= window_seconds:
            continue
        if best is None or ts > best[0]:
            best = (ts, path)
    return best[1] if best else None


def cap_image_count(output_dir: Path, max_files: int = MAX_CACHED_IMAGES) -> int:
    """Delete the oldest images so at most ``max_files`` remain in ``output_dir``.

    This is a hard ceiling across *all* images in the directory (every
    coordinate / device / setting), independent of their age.  It runs before
    the age-based prune (:func:`cleanup_old_images`) so a directory that has
    somehow grown huge is trimmed by a single count + sort rather than letting
    the per-tag globs scan an unbounded number of files on every request.

    Oldest is determined by the embedded generation timestamp (no per-file
    ``stat`` for the common case), falling back to the modification time only
    for any file whose name has no parseable timestamp.  Returns the number of
    files removed.  Best-effort: a file that cannot be deleted is logged and
    skipped.
    """
    if not output_dir.is_dir():
        return 0
    paths = list(output_dir.glob("img_*.png"))
    excess = len(paths) - max_files
    if excess <= 0:
        return 0

    def _age_key(path: Path) -> float:
        ts = _timestamp_of(path)
        if ts is not None:
            return ts
        try:  # unparseable name: fall back to mtime so it still sorts sensibly
            return path.stat().st_mtime
        except OSError:
            return 0.0

    paths.sort(key=_age_key)  # oldest first
    removed = 0
    for path in paths[:excess]:
        try:
            path.unlink()
            removed += 1
        except OSError as e:
            log.warning("Could not delete cached image %s: %s", path.name, e)
    if removed:
        log.info("Image cache over %d; removed %d oldest image(s)",
                 max_files, removed)
    return removed


def cleanup_old_images(output_dir: Path, cache_tag: str, now_ts: int,
                       max_age_seconds: int) -> int:
    """Delete ``img_<cache_tag>_<ts>.png`` files older than ``max_age_seconds``.

    Returns the number of files removed.  Best-effort: a file that cannot be
    deleted (e.g. removed concurrently) is logged and skipped.
    """
    if not output_dir.is_dir():
        return 0
    removed = 0
    for path in output_dir.glob(f"img_{cache_tag}_*.png"):
        ts = _timestamp_of(path)
        if ts is None or now_ts - ts <= max_age_seconds:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as e:
            log.warning("Could not delete old image %s: %s", path.name, e)
    if removed:
        log.info("Cleaned up %d image(s) older than %ss", removed, max_age_seconds)
    return removed


def _read_description(path: Path) -> str:
    try:
        with Image.open(path) as im:
            return im.info.get(_DESCRIPTION_KEY, "")
    except Exception:  # noqa: BLE001 - a missing/unreadable tag is non-fatal
        return ""


def render_once(settings: Settings, *, xml_path: Path | None = None,
                obs_path: Path | None = None, use_cache: bool = True) -> RenderResult:
    """Render (or serve from cache) a single image.

    Returns a result dict: ``{"filename", "cached", "description"}``.

    ``xml_path`` / ``obs_path`` load the forecast XML and observation JSON from
    disk instead of the network (offline testing); offline renders bypass the
    cache.  When ``use_cache`` is true and a fresh image already exists for the
    configured coordinates, that file is returned without fetching or rendering.
    """
    now_ts = int(time.time())

    if use_cache and xml_path is None:
        cached = find_cached(settings.output_dir, settings.cache_tag, now_ts,
                             settings.cache_seconds)
        if cached is not None:
            log.info("Cache hit (<%ss): %s", settings.cache_seconds, cached.name)
            return {"filename": cached.name, "cached": True,
                    "description": _read_description(cached)}

    observation = None
    headline = None
    if xml_path is not None:
        log.info("Loading forecast from %s", xml_path)
        forecast = nws.parse(xml_path.read_bytes())
        if obs_path is not None:
            obs_bytes = obs_path.read_bytes()
            observation = nws.parse_observation(obs_bytes)
            headline = nws.parse_headline(obs_bytes)
    else:
        log.info("Fetching forecast: %s", settings.forecast_url)
        forecast = nws.load(settings.forecast_url)
        # The observation JSON (one fetch) provides both the current conditions
        # and the upcoming-period headline.  Best-effort: a failure still yields
        # a render using the current forecast hour as a fallback.
        try:
            log.info("Fetching observation: %s", settings.observation_url)
            obs_bytes = nws.fetch(settings.observation_url)
            observation = nws.parse_observation(obs_bytes)
            headline = nws.parse_headline(obs_bytes)
        except Exception:  # noqa: BLE001
            log.warning("Observation fetch failed; using forecast hour", exc_info=True)

        # AQI is an optional, best-effort overlay on the observation (aqi.py
        # logs and swallows its own failures).
        if observation is not None:
            observation.aqi = aqi.fetch_aqi(settings)

    if observation is not None:
        log.info("Observed: %s, %s°F at %s",
                 observation.weather_text, observation.temperature_f,
                 observation.station_name)

    image = render.render(forecast, settings, observation=observation,
                          headline=headline)

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.output_dir / f"img_{settings.cache_tag}_{now_ts}.png"
    # Embed the location so cache hits can report it without re-fetching.
    meta = PngInfo()
    meta.add_text(_DESCRIPTION_KEY, forecast.location_name)
    # optimize keeps the palette PNG compact for transfer to the device; bits
    # packs the indices at the configured depth (2-bit by default).
    image.save(out_path, format="PNG", optimize=True, bits=settings.bit_depth,
               pnginfo=meta)
    log.info("Wrote %s (%s)", out_path.name, forecast.location_name)
    # Enforce the hard count ceiling first (cheap, whole-directory) so a huge
    # backlog can never slow the per-tag age prune that follows.
    cap_image_count(settings.output_dir, MAX_CACHED_IMAGES)
    # Then prune stale renders so the output directory does not grow without bound.
    cleanup_old_images(settings.output_dir, settings.cache_tag, now_ts,
                       settings.cleanup_age_seconds)
    return {"filename": out_path.name, "cached": False,
            "description": forecast.location_name}


def _get_client_ip(handler: "BaseHTTPRequestHandler", *,
                   trust_proxy_headers: bool) -> str:
    """Return the client IP address to log for a request.

    ``X-Real-IP`` / ``X-Forwarded-For`` are client-controlled unless a trusted
    reverse proxy sets them, so they are only consulted when
    ``trust_proxy_headers`` is enabled (``TRMNL_TRUST_PROXY_HEADERS``).
    Otherwise — and as the fallback in either mode — the direct TCP peer address
    is used.
    """
    if trust_proxy_headers:
        x_real_ip = handler.headers.get("X-Real-IP")
        if x_real_ip:
            return x_real_ip.strip()

        x_forwarded_for = handler.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            # The first IP in the chain is the original client.
            return x_forwarded_for.split(",")[0].strip()

    return handler.client_address[0]


def run_webserver(settings: Settings, port: int) -> None:
    """Run a web server that serves the weather image at /weather."""
    from http.server import ThreadingHTTPServer

    # The cache window is floored so an unauthenticated flood of cache-miss
    # requests cannot fetch from weather.gov more often than this.
    cache_window = max(settings.cache_seconds, MIN_WEBSERVER_CACHE_SECONDS)
    # Serialise the render-on-miss path: concurrent misses should produce a
    # single fetch+render, with later waiters served the freshly-written file.
    render_lock = threading.Lock()

    class WeatherHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            client_ip = _get_client_ip(
                self, trust_proxy_headers=settings.trust_proxy_headers)
            log.info("Request %s from %s", self.path, client_ip)
            if self.path != "/weather":
                self.send_error(404, "Not Found")
                return

            path = self._resolve_image()
            if path is not None:
                self._serve_file(path)
            else:
                self.send_error(500, "Could not generate image")

        def _resolve_image(self) -> Path | None:
            """Return a fresh image path, rendering on a cache miss."""
            now_ts = int(time.time())
            cached_path = find_cached(settings.output_dir, settings.cache_tag,
                                      now_ts, cache_window)
            if cached_path is not None and cached_path.exists():
                log.info("Serving cached image: %s", cached_path.name)
                return cached_path

            with render_lock:
                # Re-check under the lock: another thread may have rendered while
                # we waited, so we serve its result instead of rendering again.
                now_ts = int(time.time())
                cached_path = find_cached(settings.output_dir, settings.cache_tag,
                                          now_ts, cache_window)
                if cached_path is not None and cached_path.exists():
                    log.info("Serving cached image: %s", cached_path.name)
                    return cached_path

                log.info("Cache miss, generating new image")
                try:
                    result = render_once(settings, use_cache=False)
                except Exception:  # noqa: BLE001 - keep the server alive
                    log.exception("Render failed for %s", self.path)
                    return None
                out_path = settings.output_dir / result["filename"]
                return out_path if out_path.exists() else None

        def _serve_file(self, path: Path) -> None:
            try:
                content = path.read_bytes()
                mtime = path.stat().st_mtime
            except OSError as e:
                # Detail goes to the server log only; the client gets a generic
                # message so internal paths/state are never disclosed.
                log.error("Error serving file %s: %s", path, e)
                self.send_error(500, "Internal Server Error")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", f"max-age={cache_window}")
            self.send_header("Last-Modified", formatdate(mtime, usegmt=True))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer((settings.bind_address, port), WeatherHandler)
    log.info("Starting web server on %s:%d...", settings.bind_address, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopping web server...")
        server.server_close()

def run_forever(settings: Settings) -> None:
    """Render on the configured interval until interrupted.

    The periodic producer always generates a fresh image (the cache is for
    on-demand requests), printing each result as a JSON line.
    """
    log.info("Starting service: refresh every %ss", settings.refresh_seconds)
    while True:
        started = time.monotonic()
        try:
            result = render_once(settings, use_cache=False)
            print(json.dumps(result), flush=True)
        except Exception:  # noqa: BLE001 - keep the loop alive on transient errors
            log.exception("Render failed; will retry next interval")
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, settings.refresh_seconds - elapsed))


def upload_to_webhook(image_path: Path, webhook_url: str) -> None:
    """POST a PNG image to a webhook URL.

    Sends the file with ``Content-Type: image/png``.  Raises on HTTP errors
    so the caller can log or retry.
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    file_size = image_path.stat().st_size
    if file_size > 5 * 1024 * 1024:
        raise ValueError(f"Image too large ({file_size} bytes), maximum is 5 MB")

    log.info("Uploading %s (%d bytes) to %s", image_path.name, file_size,
             _GUID_RE.sub("<guid>", webhook_url))

    with open(image_path, "rb") as f:
        data = f.read()

    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "image/png", "User-Agent": config.WEBHOOK_USER_AGENT},
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        log.info("Webhook response: %s %s", resp.status, resp.reason)
