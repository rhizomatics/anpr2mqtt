# Development Setup

## First Time

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies
uv sync

# Run the app
uv run anpr2mqtt
```

## Common Commands

```bash
# Install/sync dependencies
uv sync                    # Install all dependencies
uv sync --no-dev          # Production only (no dev dependencies)
uv sync --frozen          # Use lockfile without updating

# Run commands
uv run anpr2mqtt          # Run the application
uv run pytest             # Run tests
uv run python script.py   # Run any Python script

# Manage dependencies
uv add httpx.             # Add production dependency
uv add --dev pytest       # Add dev dependency
uv remove package-name    # Remove a dependency
uv lock                   # Update lockfile after manual pyproject.toml edits

# Python version management
uv python install 3.13    # Install Python 3.12
uv python list            # List installed Python versions
uv venv                   # Create virtual environment
```

### Pre-commit Hooks

This project uses pre-commit hooks:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```


## Docker Build

```bash
# Build image
docker build -t anpr2mqtt .

# Run container
docker run -d \
  --restart always \
  -v /path/to/ftp:/ftp \
  -e MQTT_HOST=192.100.10.20 \
  -e MQTT_PORT=1883 \
  -e MQTT_USER=user \
  -e MQTT_PASS=pass \
  -e MQTT_TOPIC=anpr/driveway \
  anpr2mqtt
```

## Dependencies Troubleshooting

### Need to regenerate lockfile?
```bash
rm uv.lock
uv lock
```

### Lockfile out of sync?
```bash
uv lock --upgrade  # Update all packages
uv sync --frozen   # Use exact lockfile versions
```
