"""Command-line entry point.

Examples::

    # Render once from the bundled sample XML (offline) and exit:
    uv run trmnl-nws-weather --once --xml docs/MapClick.php.xml

    # Render once from the live NWS feed:
    uv run trmnl-nws-weather --once

    # Render and POST the image to a webhook URL:
    uv run trmnl-nws-weather --webhook https://example.com/webhook

    # ...or omit the URL when TRMNL_WEBHOOK_URL is set in the environment/.env:
    uv run trmnl-nws-weather --webhook

    # Run the periodic service:
    uv run trmnl-nws-weather
"""

from __future__ import annotations

import argparse
import json
import logging
import urllib.error
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path

from . import config
from .config import Settings, Theme, TimeFormat, Units
from .service import render_once, run_forever, run_webserver, upload_to_webhook
from . import validate as _validate

_QUANTUM = Decimal("0.0001")  # 4 fractional digits


def _coordinate(low: Decimal, high: Decimal, label: str):
    """Build an argparse type that validates and truncates a coordinate.

    The value must be a decimal number within [low, high]; its fractional part
    is truncated (toward zero) to 4 digits.  ``Decimal`` is used so truncation
    is exact and free of binary-float rounding artefacts.
    """

    def parse(raw: str) -> float:
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise argparse.ArgumentTypeError(
                f"{label} must be a decimal number (got {raw!r})")
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(
                f"{label} must be between {low} and {high} (got {value})")
        return float(value.quantize(_QUANTUM, rounding=ROUND_DOWN))

    return parse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trmnl-nws-weather", description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="render a single image and exit")
    parser.add_argument("--xml", type=Path, default=None,
                        help="load forecast XML from a file instead of the network")
    parser.add_argument("--obs", type=Path, default=None,
                        help="load observation JSON from a file (pairs with --xml)")
    parser.add_argument("--lat", type=_coordinate(Decimal(-90), Decimal(90), "latitude"),
                        default=None,
                        help="override latitude, decimal -90..90 (requires --lon)")
    parser.add_argument("--lon",
                        type=_coordinate(Decimal(-180), Decimal(180), "longitude"),
                        default=None,
                        help="override longitude, decimal -180..180 (requires --lat)")
    parser.add_argument("--units", choices=[u.value for u in Units], default=None,
                        help="override unit system (imperial|metric)")
    parser.add_argument("--theme", choices=[t.value for t in Theme], default=None,
                        help="override theme (light|dark)")
    parser.add_argument("--time-format", choices=[f.value for f in TimeFormat], default=None,
                        help="override time format (12|24)")
    parser.add_argument("--device", type=str.lower,
                        choices=[d.value for d in config.Device], default=None,
                        help="hardware preset: og (TRMNL OG, 800x480 2-bit) | "
                             "x (TRMNL X, 1872x1404 4-bit); overrides "
                             "--width/--height/--bit-depth")
    parser.add_argument("--width", type=int, default=None,
                        help=f"output panel width in px "
                             f"({config.MIN_DIMENSION}-{config.MAX_DIMENSION}, default 800)")
    parser.add_argument("--height", type=int, default=None,
                        help=f"output panel height in px "
                             f"({config.MIN_DIMENSION}-{config.MAX_DIMENSION}, default 480)")
    parser.add_argument("--bit-depth", type=int, default=None,
                        choices=config.ALLOWED_BIT_DEPTHS,
                        help="monochrome grey-ramp depth (default 2 = 4 levels)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="override the images output directory")
    parser.add_argument("--no-cache", action="store_true",
                        help="always render, ignoring any recent cached image")
    parser.add_argument("--webhook", type=str, nargs="?", default=None, const="",
                        help="POST the generated image to a webhook URL and exit; "
                             "the URL may be omitted if TRMNL_WEBHOOK_URL is set")
    parser.add_argument("--webserver", action="store_true",
                        help="run a web server to serve the weather image")
    parser.add_argument("--port", type=int, default=None,
                        help="port for the web server (default: 8400)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = Settings()  # load from env vars and defaults
    overrides = {}
    if args.units:
        overrides["units"] = Units(args.units)
    if args.theme:
        overrides["theme"] = Theme(args.theme)
    if args.time_format:
        overrides["time_format"] = TimeFormat(args.time_format)
    if args.output_dir:
        overrides["output_dir"] = args.output_dir
    # A device preset expands to a fixed width/height/bit_depth and overrides
    # the individual flags (applied in Settings.__post_init__).
    if args.device:
        overrides["device"] = config.Device(args.device)
    # Panel geometry / bit depth: range-checked here so a bad CLI value fails
    # hard (argparse already restricts --bit-depth to the allowed set).
    if args.width is not None:
        overrides["width"] = _validate.validate_int(
            args.width, "--width", config.MIN_DIMENSION, config.MAX_DIMENSION,
            config.DEFAULT_WIDTH, fail_hard=True)
    if args.height is not None:
        overrides["height"] = _validate.validate_int(
            args.height, "--height", config.MIN_DIMENSION, config.MAX_DIMENSION,
            config.DEFAULT_HEIGHT, fail_hard=True)
    if args.bit_depth is not None:
        overrides["bit_depth"] = args.bit_depth

    # Latitude and longitude only override the location when both are supplied.
    # The argparse --lat/--lon type already range-checks and truncates them.
    if args.lat is not None and args.lon is not None:
        overrides["latitude"] = args.lat
        overrides["longitude"] = args.lon
    elif (args.lat is None) != (args.lon is None):
        logging.warning(
            "Both --lat and --lon are required to override the location; "
            "using the default point %s, %s", settings.latitude, settings.longitude)

    if overrides:
        settings = replace_settings(settings, **overrides)

    # Validate --port with range check.
    port = args.port if args.port is not None else 8400
    port = _validate.validate_port(port, fail_hard=True)

    if args.webserver:
        run_webserver(settings, port=port)
        return 0

    if args.webhook is not None:
        # A URL on the command line wins; otherwise fall back to TRMNL_WEBHOOK_URL.
        raw_webhook = args.webhook or settings.webhook_url
        webhook_url = _validate.validate_url(raw_webhook, "--webhook", fail_hard=True)
        if not webhook_url:
            logging.error("No webhook URL provided; pass one to --webhook or set "
                          "TRMNL_WEBHOOK_URL.")
            return 1
        try:
            result = render_once(settings, xml_path=args.xml, obs_path=args.obs,
                                 use_cache=not args.no_cache)
        except urllib.error.HTTPError as exc:
            logging.error("NWS request failed (HTTP %s) for %s, %s - the point may "
                          "be outside NWS coverage (US and territories).",
                          exc.code, settings.latitude, settings.longitude)
            return 1
        except urllib.error.URLError as exc:
            logging.error("Could not reach the NWS API: %s", exc.reason)
            return 1
        image_path = settings.output_dir / result["filename"]
        try:
            upload_to_webhook(image_path, webhook_url)
        except urllib.error.HTTPError as exc:
            logging.error("Webhook POST failed (HTTP %s): %s", exc.code, exc.reason)
            return 1
        except urllib.error.URLError as exc:
            logging.error("Webhook URL unreachable: %s", exc.reason)
            return 1
        except (FileNotFoundError, ValueError) as exc:
            logging.error("Upload failed: %s", exc)
            return 1
        print(json.dumps(result))
        return 0

    if args.once or args.xml is not None:
        try:
            result = render_once(settings, xml_path=args.xml, obs_path=args.obs,
                                 use_cache=not args.no_cache)
        except urllib.error.HTTPError as exc:
            logging.error("NWS request failed (HTTP %s) for %s, %s - the point may "
                          "be outside NWS coverage (US and territories).",
                          exc.code, settings.latitude, settings.longitude)
            return 1
        except urllib.error.URLError as exc:
            logging.error("Could not reach the NWS API: %s", exc.reason)
            return 1
        # Result (filename, cached, description) to stdout as JSON; logs go to stderr.
        print(json.dumps(result))
        return 0

    run_forever(settings)
    return 0


def replace_settings(settings: Settings, **changes) -> Settings:
    return replace(settings, **changes)


if __name__ == "__main__":
    raise SystemExit(main())
