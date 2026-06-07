"""Command-line entry point.

Examples::

    # Render once from the bundled sample XML (offline) and exit:
    uv run trmnl-nws-weather --once --xml docs/MapClick.php.xml

    # Render once from the live NWS feed:
    uv run trmnl-nws-weather --once

    # Render and POST the image to a webhook URL:
    uv run trmnl-nws-weather --webhook https://example.com/webhook

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

from .config import Settings, Theme, TimeFormat, Units
from .service import render_once, run_forever, run_webserver, upload_to_webhook

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
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="override the images output directory")
    parser.add_argument("--no-cache", action="store_true",
                        help="always render, ignoring any recent cached image")
    parser.add_argument("--webhook", type=str, default=None,
                        help="POST the generated image to the given webhook URL and exit")
    parser.add_argument("--webserver", action="store_true",
                        help="run a web server to serve the weather image")
    parser.add_argument("--port", type=int, default=8400,
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

    # Latitude and longitude only override the location when both are supplied.
    if args.lat is not None and args.lon is not None:
        overrides["latitude"] = args.lat
        overrides["longitude"] = args.lon
    elif (args.lat is None) != (args.lon is None):
        logging.warning(
            "Both --lat and --lon are required to override the location; "
            "using the default point %s, %s", settings.latitude, settings.longitude)

    if overrides:
        settings = replace_settings(settings, **overrides)

    if args.webserver:
        run_webserver(settings, port=args.port)
        return 0

    if args.webhook:
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
            upload_to_webhook(image_path, args.webhook)
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
