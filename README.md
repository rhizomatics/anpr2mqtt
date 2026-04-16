![anpr2mqtt](assets/images/anpr2mqttdark-256x256.png){ align=left }

# anpr2mqtt

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics)

[![PyPI - Version](https://img.shields.io/pypi/v/anpr2mqtt)](https://pypi.org/project/anpr2mqtt/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/rhizomatics/anpr2mqtt)
[![Coverage](https://raw.githubusercontent.com/rhizomatics/anpr2mqtt/refs/heads/badges/badges/coverage.svg)](https://anpr2mqtt.rhizomatics.org.uk/developer/coverage/)
![Tests](https://raw.githubusercontent.com/rhizomatics/anpr2mqtt/refs/heads/badges/badges/tests.svg)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/rhizomatics/anpr2mqtt/main.svg)](https://results.pre-commit.ci/latest/github/rhizomatics/anpr2mqtt/main)
[![Github Deploy](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/deploy.yml)
[![CodeQL](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/dependabot/dependabot-updates)


# ANPR MQTT Bridge

A simple way to integrate CCTV cameras with built-in **ANPR** (**Automatic Number Plate Recognition**, aka **ALPR** or **Automatic License Plate Recognition**) to MQTT for Home Assistant integration, or any other MQTT consumer. Running under Docker is preferred but not necessary.

All that is needed is for the camera to be configured to upload images on plate recognition, by ftp, NAS or whatever else. ANPR2MQTT monitors the directory where the images lands and publishes plate information to MQTT. Its simple, requires no proprietary vendor APIs ( or differing ONVIF implementations ), and Home Assistant gets a copy of the actual annotated detection image to use on dashboards or to attach to notifications.

While intended for vehicle plate detection, it can be used to watch for and analyze any file, so for example uploaded face detection, missing object, unattended baggage or line crossing images. A single `anpr2mqtt` instance can watch multiple paths and patterns for different cameras and events.

## Features

* Minimal configuration
    - Ready configured to work with popular Hikvision ANPR camera settings
       - See [Example Camera Configuration](camera.md)
* File System Integration
    - Watches directory for ANPR camera images using [Watchdog](https://python-watchdog.readthedocs.io/en/stable/index.html)
        - Uses [inotify](https://www.man7.org/linux/man-pages/man7/inotify.7.html) on Linux, or equiv on other operating systems for efficient listening to file system events without continual polling
    - Extracts target ( for example licence plate ), timestamp and event type information from filenames
* [Home Assistant Integration](homeassistant.md). 
    - Publishes events to MQTT for Home Assistant as a [MQTT Sensor Entity](https://www.home-assistant.io/integrations/sensor.mqtt/)
    - Auto-discovery configuration for Home Assistant
    - Creates [MQTT Image Entity](https://www.home-assistant.io/integrations/image.mqtt/) on Home Assistant for image snapshot, so no web access to ftp needed
    - Optionally also creates an [MQTT Camera Entity](https://www.home-assistant.io/integrations/camera.mqtt/)
* Plate Enrichment
    - OCR-based extraction of fields using [tesseract-ocr](https://github.com/tesseract-ocr/tesseract)
        - By default direction detection (Forward/Reverse) 
        - Corrections by regular expression to fix OCR mis-readings
    - Tracks and counts previous sightings
    - Configurable to classify plates as known, to be ignored or as a potential threat
    - Regular expression based corrections, for known plates that the ANPR sometimes mis-reads
    - Fuzzy match corrections for known plates, based on Levenshtein algorithm
    - UK Only
        - [DVLA Lookup](api.md) if API_KEY provided, for detailed MOT and tax information
        - Lookups cached for configurable time
* Auto clear vehicle state optionally, after configurable time
* [Debug Tools](debug_tools.md) built-in


## Docker Deployment

Build and run with Docker, example [docker-compose.yaml](examples/docker_compose.md) provided.

## Configuration

ANPR2MQTT uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), which means configuration can happen in a variety of ways, and these can be combined - yaml configuration file, environment variables, Docker Secrets, built-in defaults, and `.env` file or command line arguments.

### CLI Arguments

Every configuration setting can be passed as a command line argument, using dot notation for nested settings.
This is the highest-priority source and overrides all other configuration.

```bash
uv run --with anpr2mqtt anpr2mqtt --mqtt.host 192.168.1.10 --mqtt.port 1884 --log_level DEBUG
```

Run `uv run --with anpr2mqtt anpr2mqtt --help` to see all available flags, and find more information at [Debug Tools](debug_tools.md)

## Home Assistant Integration

See [Home Assistant Integration](homeassistant.md) for configuration and example notification automation.

### Environment Variables

[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) needs double underscores for
environment variables in config sections. For example, `MQTT__HOST` means set the value `host` in the `mqtt` config section.

| Env Variable                  | Description | Default |
|-------------------------------|-------------|---------|
| `MQTT__HOST`                  | MQTT broker hostname | `localhost` |
| `MQTT__PORT`                  | MQTT broker port | `1883` |
| `MQTT__TOPIC_ROOT`            | MQTT topic for events | `anpr2mqtt` |
| `MQTT__USER`                  | MQTT username | - |
| `MQTT__PASS`                  | MQTT password | - |
| `LOG_LEVEL`                   | Python logging level | INFO |
| `DVLA__API_KEY`               | API Key for Gov API Lookup | - |


## Image Filename Format

Expected format: `YYYYMMDDHHMMSSmmm_PLATE_VEHICLE_DETECTION.jpg`

Example: `20180502174029596_A2GEO_VEHICLE_DETECTION.jpg`

A regular expression can be defined to match different file name formats.

## Image Box Coordinates

Where cameras provide an estimated direction for the vehicle, this can be captured via OCR and
included in the response. See [OCR](ocr.md) for an explanation and examples.

## Auto Clear

By default, the state will be reset back to unavailable 5 minutes after a detection, while the image will
be left present as record of last known vehicle. This behavior can be changed ( to switch off auto clear,
or change the time lag, or also clear image ) using the `autoclear` configuration for each event.

```yaml title="configuration snippet"
- camera: shed
  watch_path: /ftp/shedcam
  autoclear:
    post_event: 360
    state: True
    image: False
```

## Corrections

The licence plate detection may mis-read or miss some of the characters of the plate. When the result is
published to MQTT, both the raw original and corrected versions are provided.

Two mechanisms help with this:

### Fuzzy Matching

The Levenshtein method is used to compare the plate against a list of known plates in the configuration, subject to a maximum distance tolerance ( number of mismatched characters ) defined by `auto_match_tolerance` for the event. If its a match for more than one, the plate with least distance is chosen.

### Regex / String Matching

Each known plate can be associated with a list of regular expressions and/or plain strings, and these will be checked for every discovered licence plate.

## Primary Dependencies

- **watchdog** - File system monitoring (cross-platform)
- **paho-mqtt** - MQTT client
- **Pillow** - Image processing
- **pytesseract** - OCR for direction detection
- **structlog** - Structured logging
- **niquests** - API Client
- **requests-cache** - API result caching

## Distribution

ANPR2MQTT is free and open sourced under the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).

##  Rhizomatics Open Source for Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Automatically arm and disarm Home Assistant alarm control panels using physical buttons, presence, calendars, sun and more
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - OpenTelemetry (OTLP) and Syslog event capture for Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Unified notification for easy multi-channel messaging, including powerful chime and security camera integration.


### Python / Docker

- [Updates2MQTT](https://updates2mqtt.rhizomatics.org.uk) - Automatically notify via MQTT on Docker image updates, with advanced handling to extract versions and release notes from images, and option to remotely pull and restart containers from Home Assistant. Also available on [PyPI](https://pypi.org/project/updates2mqtt/)