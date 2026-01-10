![anpr2mqtt](images/anpr2mqttdark-256x256.png){ align=left }

# anpr2mqtt

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics)


[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/rhizomatics/anpr2mqtt)
[![Coverage](https://raw.githubusercontent.com/rhizomatics/anpr2mqtt/refs/heads/badges/badges/coverage.svg)](https://anpr2mqtt.rhizomatics.org.uk/developer/coverage/)
![Tests](https://raw.githubusercontent.com/rhizomatics/anpr2mqtt/refs/heads/badges/badges/tests.svg)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/rhizomatics/anpr2mqtt/main.svg)](https://results.pre-commit.ci/latest/github/rhizomatics/anpr2mqtt/main)
[![Github Deploy](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/deploy.yml)
[![CodeQL](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/anpr2mqtt/actions/workflows/dependabot/dependabot-updates)


# ANPR MQTT Bridge

A simple way to integrate CCTV cameras with built-in ANPR (Automatic Number Plate Recognition, aka Automatic Licence Plate Recognitio) to MQTT for Home Assistant integration, or any other MQTT consumer. All that is needed is for the camera to
be configured to upload images on plate recognition, by ftp, NAS or whatever else. ANPR2MQTT monitors the directory where the images lands and publishes plate information to MQTT.

## Features

- Watches directory for ANPR camera images using [Watchdog](https://python-watchdog.readthedocs.io/en/stable/index.html) (inotify on Linux, or equiv on other os)
- Extracts license plate information from filenames
- OCR-based direction detection (Forward/Reverse)
- Publishes events to MQTT for Home Assistant
- Auto-discovery configuration for Home Assistant
- Creates MQTT Image Entities on Home Assistant for image snapshot, so no web access to ftp needed
- Tracks and counts previous sightings
- Configurable to classify plates as known, to be ignored or as a potential threat
- Regular expression based corrections, for known plates that the ANPR sometimes mis-reads
- UK Only
  - DVLA Lookup if API_KEY provided, for detailed MOT and tax information





## Docker Deployment

Build and run with Docker:

```bash
docker build -t anpr2mqtt .
docker run -d \
  --restart always \
  -v /path/to/ftp:/ftp \
  -e MQTT_HOST=your-mqtt-host \
  -e MQTT_PORT=1883 \
  -e MQTT_USER=username \
  -e MQTT_PASS=password \
  -e MQTT_TOPIC=anpr/driveway \
  anpr2mqtt
```
## Configuration

ANPR2MQTT uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), which means
configuration can happen in a variety of ways, and these can be combined - yaml configuration file, environment
variables, Docker Secrets, built-in defaults, and `.env` file or command line arguments.

### Environment Variables

[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) needs double underscores for
environment variables in config sections. For example, `MQTT__HOST` means set the value `host` in the `mqtt` config section.

| Env Variable                  | Description | Default |
|-------------------------------|-------------|---------|
| `MQTT__HOST`                  | MQTT broker hostname | `localhost` |
| `MQTT__PORT`                  | MQTT broker port | `1883` |
| `MQTT__TOPIC_ROOT`            | MQTT topic for events | `anpr/driveway` |
| `MQTT__USER`                  | MQTT username | - |
| `MQTT__PASS`                  | MQTT password | - |
| `FILE_SYSTEM__WATCH_PATH`     | Directory to watch | - |
| `FILE_SYSTEM__IMAGE_URL_BASE` | Optional HTTP Base URL to prepend to file name | - |
| `LOG_LEVEL`                   | Python logging level | INFO |
| `DVLA__API_KEY`               | API Key for Gov API Lookup | - |


## Image Filename Format

Expected format: `YYYYMMDDHHMMSSmmm_PLATE_VEHICLE_DETECTION.jpg`

Example: `20180502174029596_A2GEO_VEHICLE_DETECTION.jpg`

## Image Box Coordinates

See [PIL Coordinate System](https://pillow.readthedocs.io/en/stable/handbook/concepts.html#coordinate-system)

## Primary Dependencies

- **paho-mqtt** - MQTT client
- **Pillow** - Image processing
- **pytesseract** - OCR for direction detection
- **structlog** - Structured logging
- **httpx** - API Client
- **hishel** - API result caching
- **watchdog** - File system monitoring (cross-platform)

## Home Assistant Integration

The service auto-configures a sensor in Home Assistant via MQTT discovery:

- **Entity ID**: `sensor.anpr_<camera>`
- **Attributes**: `plate`, `last_seen`, `url`, `direction`

And an image entity

- **Entity ID**: `image.anpr_<camera>`

The image entity reuses all the attributes from the sensor entity.


## Example Automation

```yaml
alias: Driveway ANPR Alert
description: ""
triggers:
  - trigger: state
    entity_id:
      - sensor.driveway_anpr
conditions: []
actions:
  - action: notify.supernotifier
    metadata: {}
    data:
      message: >-
        {{ trigger.to_state.attributes.description }} with {{
        trigger.to_state.attributes.plate }} spotted at {{
        trigger.to_state.attributes.camera }} camera in an
        {{ trigger.to_state.attributes.direction }} direction.

        {% if trigger.to_state.attributes.previous_sightings == 0 %} Not
        previously sighted  {% else %}  {{
        trigger.to_state.attributes.previous_sightings }} previous sightings,
        last seen on {{ trigger.to_state.attributes.last_sighting[:10] }} at {{
        trigger.to_state.attributes.last_sighting[11:16] }}   {% endif %}

        {% if trigger.to_state.attributes.reginfo is defined %}  
        DVLA info: 
        {{ trigger.to_state.attributes.reginfo }}  
        {% endif %}
      title: >-
        {{ trigger.to_state.attributes.description }} spotted on {{
        trigger.to_state.attributes.camera }} camera
      data:
        priority: "{{ trigger.to_state.attributes.priority }}"
        media:
          camera_entity_id: "image.anpr_{{trigger.to_state.attributes.camera}}"
```

## Distribution

ANPR2MQTT is free and open sourced under the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).
