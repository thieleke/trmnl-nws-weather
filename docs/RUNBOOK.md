# Runbook — Generating the Weather PNG

Operational guide for producing the 2-bit 800×480 weather PNG for the TRMNL
7.5" e-ink display. For design/layout details see [`../README.md`](../README.md).

---

## 1. What it does

On each run the service:

1. Checks the cache: if an image for the same coordinates was generated in the
   last 15 minutes, returns it (unless `--no-cache`) and stops here.
2. Fetches the NWS **digital DWML** hourly forecast for the configured point.
3. Fetches the MapClick **JSON** current observation + worded forecast.
4. Renders an 800×480, 2-bit (4 grey level) PNG.
5. Writes it to `images/img_<lat>_<lon>_<unix-ts>.png` and prints a JSON result.

If the observation fetch fails, the render still succeeds using the current
forecast hour as a fallback.

---

## 2. Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** *or* plain **`pip`** (both shown below)
- Outbound HTTPS to `forecast.weather.gov` (live runs) and, for AQI,
  `air-quality-api.open-meteo.com`

Fonts (Inter + DejaVu) are vendored in the package — no system fonts required.

---

## 3. One-time setup

From the project root, choose **one** of:

```bash
# uv — creates .venv/ and installs dependencies:
uv sync

# pip / plain Python:
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt   # or: pip install .  (also installs the CLI)
```

Verify the install:

```bash
uv run trmnl-nws-weather --help     # uv
python -m trmnl_nws_weather --help  # pip / plain Python
```

> **Every command below uses `uv run trmnl-nws-weather …`.** If you installed
> with pip, substitute `python -m trmnl_nws_weather …` (identical arguments).

### Set your location

Defaults render for Intercourse, PA. Point it at your location either with
`--lat`/`--lon` flags, or persistently via a `.env` file: copy the documented
[`.env.example`](../.env.example) to `.env` in the project root and edit the
coordinates (and anything else you want to change).

---

## 4. Generate a PNG

### 4a. Send to TRMNL (webhook image) — most common

This is how most people use the tool: render the current weather and POST it
straight to a TRMNL panel via the
**[Webhook Image](https://help.trmnl.com/en/articles/13213669-webhook-image)**
plugin.

1. In TRMNL: **Plugins → Webhook Image → Add to my plugins**, name the instance,
   and copy the private **webhook URL** (treat it like a password).
2. Render and upload in one step:

```bash
uv run trmnl-nws-weather --once \
  --webhook "https://usetrmnl.com/api/plugin_settings/<your-uuid>/image"
```

To avoid repeating the URL, store it in `.env` as `TRMNL_WEBHOOK_URL` and call
`--webhook` with no argument (a URL on the command line still overrides it):

```bash
uv run trmnl-nws-weather --once --webhook
```

The tool renders the 800×480 PNG, then POSTs it as `Content-Type: image/png`.
On success you'll see the upload logged and the usual JSON on stdout:

```text
INFO Wrote img_40.0404_-76.3042_1780590454.png (Intercourse PA)
INFO Uploading img_40.0404_-76.3042_1780590454.png (... bytes) to https://usetrmnl.com/...
INFO Webhook response: 200 OK
```

TRMNL limits webhook images to **5 MB** and **12 uploads/hour** — the output is
~tens of KB, and refreshing every 30 minutes (2/hour) stays well inside both.

**Keep it current with a scheduler.** Run the command on a timer:

```bash
# Linux/macOS — crontab -e, every 30 minutes:
*/30 * * * * cd /path/to/trmnl-nws-weather && uv run trmnl-nws-weather --once --webhook "https://usetrmnl.com/api/plugin_settings/<your-uuid>/image" >> /tmp/trmnl.log 2>&1
```

```powershell
# Windows — Task Scheduler, repeat every 30 minutes:
schtasks /Create /SC MINUTE /MO 30 /TN trmnl-nws-weather /TR `
  "powershell -NoProfile -Command \"cd C:\path\to\trmnl-nws-weather; uv run trmnl-nws-weather --once --webhook 'https://usetrmnl.com/api/plugin_settings/<your-uuid>/image'\""
```

(Set your location once in `.env` so the scheduled command stays short, or add
`--lat`/`--lon` to the command.)

### 4b. One image to a file (no upload)

```bash
uv run trmnl-nws-weather --once
```

Progress logs go to **stderr**; the result is printed to **stdout** as JSON:

```text
INFO Fetching forecast: https://forecast.weather.gov/MapClick.php?...FcstType=digitalDWML
INFO Fetching observation: https://forecast.weather.gov/MapClick.php?...FcstType=json
INFO Observed: Fair, 67.0°F at Intercourse, Lancaster Airport
INFO Wrote img_40.0404_-76.3042_1780590454.png (Intercourse PA)
```

```json
{"filename": "img_40.0404_-76.3042_1780590454.png", "cached": false, "description": "Intercourse PA"}
```

The PNG is the file named by `"filename"` (under the output directory). On a
cache hit, `"cached"` is `true` and no fetch/render occurs. Capture just the
JSON with `2>/dev/null`.

### 4c. One image from committed sample data (offline / no network)

```bash
uv run trmnl-nws-weather --once --xml docs/MapClick.php.xml --obs docs/MapClick.json
```

Use this to test rendering changes deterministically. `--obs` is optional; omit
it to exercise the "no observation" fallback path.

### 4d. Continuous service or web server

```bash
# Re-render on an interval (TRMNL_REFRESH_SECONDS, default 1800 = 30 min):
uv run trmnl-nws-weather

# Or serve the latest image over HTTP at /weather (default port 8400):
uv run trmnl-nws-weather --webserver --port 8080
```

The service runs forever; stop with `Ctrl+C`. A transient fetch error is logged
and retried next interval — the loop does not exit. (The webhook method in 4a is
simpler for most users; use these when you want a long-running process or to
pull the image yourself.)

### 4e. Variations (units / theme / output location)

```bash
# Metric units (°C, km/h):
uv run trmnl-nws-weather --once --units metric

# Dark theme (white on black):
uv run trmnl-nws-weather --once --theme dark

# Write somewhere else:
uv run trmnl-nws-weather --once --output-dir /path/to/out
```

### 4f. All CLI options

| Flag | Description |
| --- | --- |
| `--once` | Render a single image and exit |
| `--xml PATH` | Load forecast XML from a file instead of the network |
| `--obs PATH` | Load observation JSON from a file (pairs with `--xml`) |
| `--lat DEG` | Override latitude, decimal -90..90 (requires `--lon`) |
| `--lon DEG` | Override longitude, decimal -180..180 (requires `--lat`) |
| `--units {imperial,metric}` | Override unit system |
| `--theme {light,dark}` | Override theme |
| `--time-format {12,24}` | Override time format |
| `--output-dir PATH` | Override the images output directory |
| `--no-cache` | Always render, ignoring any recent cached image |
| `--webhook [URL]` | POST the generated image to a webhook URL and exit; the URL may be omitted when `TRMNL_WEBHOOK_URL` is set |
| `--webserver` | Run a web server to serve the weather image |
| `--port INT` | Port for the web server (default: 8400) |
| `-v`, `--verbose` | Enable debug logging |

---

## 5. Configuration

CLI flags override environment variables, which override defaults.

Values outside the listed range (or otherwise invalid) are rejected with a
warning and the default is used instead.

| Env var | Default | Range / allowed | Purpose |
| --- | --- | --- | --- |
| `TRMNL_LATITUDE` | `40.0404` | -90 to 90 | Forecast point latitude |
| `TRMNL_LONGITUDE` | `-76.3042` | -180 to 180 | Forecast point longitude |
| `TRMNL_UNITS` | `imperial` | `imperial` or `metric` | `imperial` (°F/mph) or `metric` (°C/km/h) |
| `TRMNL_THEME` | `light` | `light` or `dark` | `light` (black on white) or `dark` |
| `TRMNL_REFRESH_SECONDS` | `1800` | 60 to 86400 | Service re-render interval |
| `TRMNL_GRAPH_WINDOW_HOURS` | `18` | 1 to 720 | Temperature graph time span |
| `TRMNL_GRAPH_NOW_POSITION` | `0.0` | 0.0 to 1.0 | "Now" position in graph (0 = left) |
| `TRMNL_FORECAST_HOURS` | `6` | 1 to 240 | Columns in the forecast strip |
| `TRMNL_CACHE_SECONDS` | `900` | 0 to 86400 | Cache window for same-coordinate requests |
| `TRMNL_TIME_FORMAT` | `12` | `12` or `24` | Time format, 12 or 24 hour |
| `TRMNL_CLEANUP_AGE_SECONDS` | `21600` | 0 to 604800 | Age of files to delete (seconds) |
| `TRMNL_OUTPUT_DIR` | `images` | any path | Output directory |
| `TRMNL_AQI_PROVIDER` | `open-meteo` | `open-meteo` or `none` | AQI source: `open-meteo` (free, no key) or `none` |
| `TRMNL_AQI_URL` | *(empty)* | `http`/`https` URL | Custom `{"aqi": N}` endpoint; overrides the provider |
| `TRMNL_WEBHOOK_URL` | *(empty)* | `http`/`https` URL | Default URL for `--webhook` when none is given on the CLI |

| CLI flag | Purpose |
| --- | --- |
| `--once` | Render a single image and exit |
| `--xml PATH` | Load forecast XML from a file instead of the network |
| `--obs PATH` | Load observation JSON from a file (pairs with `--xml`) |
| `--lat DEG` | Override latitude, decimal -90..90 (requires `--lon`) |
| `--lon DEG` | Override longitude, decimal -180..180 (requires `--lat`) |
| `--units {imperial,metric}` | Override unit system |
| `--theme {light,dark}` | Override theme |
| `--output-dir PATH` | Override output directory |
| `--no-cache` | Always render, ignoring any recent cached image |
| `-v`, `--verbose` | Debug logging |

**Change the location** (example — Denver, CO):

```bash
# Command-line flags (both required together; values truncated to 4 decimals):
uv run trmnl-nws-weather --once --lat 39.7392 --lon -104.9903
```

```powershell
# Or via environment variables (PowerShell):
$env:TRMNL_LATITUDE = "39.7392"; $env:TRMNL_LONGITUDE = "-104.9903"
uv run trmnl-nws-weather --once
```

`--lat` / `--lon` must be decimal degrees within range (-90..90 latitude,
-180..180 longitude); invalid or out-of-range values are rejected with an error.
The point must be within NWS coverage (United States and territories).

**Persist settings with a `.env` file.** Copy [`.env.example`](../.env.example)
to `.env` in the project root; it is loaded automatically on every run. A
minimal example for a second city (Boring, Oregon):

```dotenv
# .env
TRMNL_LATITUDE=45.4318
TRMNL_LONGITUDE=-122.3756
TRMNL_UNITS=imperial
TRMNL_THEME=light
# AQI: built-in free Open-Meteo by default; set a custom sensor URL if you have one.
TRMNL_AQI_PROVIDER=open-meteo
# TRMNL_AQI_URL=http://my-sensor.local/aqi
```

### Air Quality Index (AQI)

The NWS feed has no air-quality data, so the AQI box is filled separately:

- **`open-meteo`** (default) — the free, **no-API-key**
  [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api),
  which returns the US EPA AQI for your `TRMNL_LATITUDE`/`TRMNL_LONGITUDE`.
- **`none`** — disable the lookup; the box shows `--`.
- **Custom endpoint** — set `TRMNL_AQI_URL` to any URL returning JSON like
  `{"aqi": 42}` (e.g. a local sensor). When set it overrides
  `TRMNL_AQI_PROVIDER`. AQI is best-effort: a failure is logged and the render
  proceeds without it.

---

## 6. Output format

- **Path:** `images/img_<lat>_<lon>_<unix-ts>.png` — coordinates to 4 decimals,
  `unix-ts` = generation time (seconds). E.g.
  `img_40.0404_-76.3042_1780590454.png`.
- **Format:** PNG, 800×480, palette mode, **2-bit** (4 grey levels), suitable
  for direct display on the TRMNL panel. The location is stored in the PNG
  `Description` text chunk.
- **Result:** the one-shot command prints JSON to stdout —
  `{"filename": "...", "cached": true|false, "description": "..."}`.
- **Caching:** a same-coordinate request within `TRMNL_CACHE_SECONDS` (default
  900 s) returns the existing file with `"cached": true`. Use `--no-cache` to
  force a fresh render. After each fresh render, files older than
  `TRMNL_CLEANUP_AGE_SECONDS` (default 6 h) are pruned automatically.
- The `images/` directory is created automatically and is git-ignored.

Verify a generated file:

```bash
python -c "from PIL import Image; im=Image.open('images/<file>.png'); print(im.mode, im.size, im.info.get('Description'))"
# -> P (800, 480) Intercourse PA
```

---

## 7. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `HTTP Error 403` on fetch | weather.gov rejects default agents; the service already sends a descriptive `User-Agent`. Confirm outbound HTTPS is allowed. |
| `URLError` / timeout | Network/DNS issue. Retry; the service loop retries automatically each interval. |
| Current conditions look like the forecast, not observed | Observation fetch failed (logged as a warning). The render fell back to the current forecast hour; re-run when connectivity returns. |
| Graph is empty / flat | The forecast had fewer than two hourly points. Check the forecast URL returns `digitalDWML` data for the point. |
| Wrong location in output | `TRMNL_LATITUDE` / `TRMNL_LONGITUDE` not set as intended, or point is outside NWS coverage. |
| Text/icons look blocky | Expected: the panel is 2-bit. The render supersamples 3× then quantises; this is the target output. |
| Same image returned repeatedly (`"cached": true`) | A fresh image for those coordinates exists (within `TRMNL_CACHE_SECONDS`). Use `--no-cache` to force a render. |
| Webhook `HTTP 422` | Image too large, wrong format, or corrupt — should not happen with the built-in 800×480 PNG; check the webhook URL is the **Webhook Image** plugin's. |
| Webhook `HTTP 429` | TRMNL rate limit (12 uploads/hour) exceeded. Increase your schedule interval. |
| Panel not updating after a `200` | Use **Force Refresh** in the TRMNL plugin settings; the device polls on its own cycle. |
| AQI box shows `--` | AQI disabled (`TRMNL_AQI_PROVIDER=none`), the source was unreachable (logged), or the observation fetch failed. |
| `command not found: uv` | Install uv (<https://docs.astral.sh/uv/getting-started/installation/>) or use the pip path with `python -m trmnl_nws_weather`. |

Run with `-v` for full debug logging (URLs, observed values, stack traces):

```bash
uv run trmnl-nws-weather --once -v
```

---

## 8. Validate after code changes

```bash
uv run python -m pytest            # unit tests (uv)
python -m pytest                   # unit tests (pip / activated venv)
uv run trmnl-nws-weather --once --xml docs/MapClick.php.xml --obs docs/MapClick.json
```

Open the written PNG and confirm the layout renders as expected before relying
on live output.
