# Debug Tools

ANPR2MQTT ships an `anprtools` CLI with subcommands to help debug file system integration or OCR.
All options can also be discovered via `--help`:

NOTE: if running from a checked out `anpr2mqtt` project with active `venv`, use `uv run anprtools ...`
instead of `uvx --from anpr2mqtt anprtools ...` to run against your local checkout rather than the published package.

```bash
uvx --from anpr2mqtt anprtools --help
uvx --from anpr2mqtt anprtools ocr_file --help
uvx --from anpr2mqtt anprtools list_dir --help
```

## OCR (`ocr_file`)

Loads an image, runs OCR on it (with optional crop and invert), and prints the result.
It ignores any YAML config file but respects environment variables.
Useful for iterating quickly on bounding-box settings against a local image.

NOTE: OCR needs the [tesseract-ocr](https://github.com/tesseract-ocr/tesseract) binary on your `PATH`, which isn't
installed by `uv`/`uvx`. The Docker image includes it, but to run outside Docker install it first, e.g.
`brew install tesseract` on macOS or `apt install tesseract-ocr-eng` on Debian/Ubuntu. Without it, `ocr_file` reports
`tesseract is not installed or it's not in your PATH` instead of an OCR result.

```bash
uvx --from anpr2mqtt anprtools ocr_file 20241230152519495_N74DYX_VEHICLE_DETECTION.jpg
```

All `event` and `ocr` settings can be overridden from the command line:

```bash
uvx --from anpr2mqtt anprtools ocr_file fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg \
  --ocr.crop.x 850 --ocr.crop.y 0 --ocr.crop.h 200 --ocr.crop.w 400 \
  --ocr.invert False
```

Key flags for `ocr_file`:

| Flag | Description | Default |
|------|-------------|---------|
| `IMAGE_FILE` | Image filename (positional) | required |
| `--event.watch_path` | Directory containing the image | `.` (current dir) |
| `--event.image_name_re` | Regex to parse filename for plate/timestamp | Hikvision default |
| `--ocr.crop.x/y/h/w` | Crop box coordinates and size (pixels) | — |
| `--ocr.invert` | Invert colours before OCR | `True` |
| `--log_level` | Logging verbosity | `INFO` |

If no `event` config is defined, the image is looked for in the current working directory.

## Directory Listing (`list_dir`)

Lists images in a directory that match the ANPR image regular expression.

```bash
uvx --from anpr2mqtt anprtools list_dir
```

Override any `event` setting from the command line, for example to test a different path or regex:

```bash
uv run anprtools list_dir \
  --event.watch_path /ftp/Driveway \
  --event.image_name_re '(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)'
```

Key flags for `list_dir`:

| Flag | Description | Default |
|------|-------------|---------|
| `--event.watch_path` | Directory to list | `.` (current dir) |
| `--event.image_name_re` | Regex to match filenames | Hikvision default |
| `--log_level` | Logging verbosity | `INFO` |

## DVLA Lookup (`dvla_lookup`)

Performs a live DVLA vehicle enquiry for a registration plate and prints the JSON response.
Useful for verifying your API key and checking what data the API returns for a given plate.

```bash
uvx --from anpr2mqtt anprtools dvla_lookup AB12CDE --dvla.api_key YOUR_API_KEY
```

The API key can also be supplied via the `DVLA__API_KEY` environment variable:

```bash
DVLA__API_KEY=your-key uv run anprtools dvla_lookup AB12CDE
```

Use `--test` to hit the DVLA UAT environment instead of production:

```bash
uvx --from anpr2mqtt anprtools dvla_lookup AB12CDE --dvla.api_key YOUR_KEY --test true
```

Key flags for `dvla_lookup`:

| Flag | Description | Default |
|------|-------------|---------|
| `REGISTRATION` | Vehicle registration number (positional) | required |
| `--dvla.api_key` | DVLA API key | — |
| `--dvla.cache_ttl` | Cache TTL in seconds | `86400` |
| `--dvla.cache_type` | Cache type | `FILE` |
| `--dvla.cache_dir` | Caching directory | `/data/cache` |
| `--test` | Use UAT environment | `False` |
| `--log_level` | Logging verbosity | `INFO` |

## Healthcheck (`healthcheck`)

Reports whether ANPR2MQTT is running and connected to MQTT. While it is, the main loop touches a heartbeat
file every 10 seconds, and `healthcheck` exits non-zero if that file is missing or older than `--max_age`
seconds (default 60). The Docker image runs it as its `HEALTHCHECK`, so `docker ps` shows the container as
`healthy` or `unhealthy` with no extra configuration.

```bash
docker exec anpr2mqtt anprtools healthcheck
```

The heartbeat file is `anpr2mqtt.heartbeat` in the system temporary directory (`/tmp` in the container),
or the path in the `ANPR2MQTT_HEARTBEAT_FILE` environment variable, which must be set the same for both
the app and the healthcheck.
