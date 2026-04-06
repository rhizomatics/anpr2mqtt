# Debug Tools

ANPR2MQTT ships a `tools` CLI with subcommands to help debug file system integration or OCR.
All options can also be discovered via `--help`:

```bash
uv run tools --help
uv run tools ocr_file --help
uv run tools list_dir --help
```

## OCR (`ocr_file`)

Loads an image, runs OCR on it (with optional crop and invert), and prints the result.
It ignores any YAML config file but respects environment variables.
Useful for iterating quickly on bounding-box settings against a local image.

```bash
uv run tools ocr_file 20241230152519495_N74DYX_VEHICLE_DETECTION.jpg
```

All `event` and `ocr` settings can be overridden from the command line:

```bash
uv run tools ocr_file fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg \
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
uv run tools list_dir
```

Override any `event` setting from the command line, for example to test a different path or regex:

```bash
uv run tools list_dir \
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
uv run tools dvla_lookup AB12CDE --dvla.api_key YOUR_API_KEY
```

The API key can also be supplied via the `DVLA__API_KEY` environment variable:

```bash
DVLA__API_KEY=your-key uv run tools dvla_lookup AB12CDE
```

Use `--test` to hit the DVLA UAT environment instead of production:

```bash
uv run tools dvla_lookup AB12CDE --dvla.api_key YOUR_KEY --test true
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
