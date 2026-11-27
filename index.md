# anpr2mqtt

# ANPR MQTT Bridge

A simple way to integrate into Home Assistant (or other MQTT consumers) any CCTV camera that can upload files via FTP, NAS etc into a monitored directory. Specializes in **ANPR** (**Automatic Number Plate Recognition**, aka **ALPR** or **Automatic License Plate Recognition**) with support for face events, and configurable for other event types. Running under Docker is preferred but not necessary.

All that is needed is for the camera to be configured to upload images on plate recognition, or any other event, by ftp, NAS or whatever else. ANPR2MQTT monitors the directory where the images lands and publishes plate, or other event, information to MQTT. Its simple, requires no proprietary vendor APIs ( or differing ONVIF implementations ), and Home Assistant gets a copy of the actual annotated detection image to use on dashboards or to attach to notifications.

While it specialises in vehicle plate detection, it can watch for any camera event that uploads images, such as face capture, scene change, missing object, unattended baggage or line crossing, defined by configuration alone, without `anpr2mqtt` needing to know about each one. See [Other Events](https://anpr2mqtt.rhizomatics.org.uk/camera/#other-events). A single `anpr2mqtt` instance can watch multiple paths and patterns for different cameras and events.

Info

The enrichment features, such as DVLA lookup and previous sightings, are now integrated directly into the Home Assistant Marketplace integration [Camera AutoNotify](https://camera-autonotify.rhizomatics.org.uk) and this is now the recommended method, and with this integration there is no longer any reason to divert Frigate messages via `anpr2mqtt`.

The functionality can still be used in `anpr2mqtt`, which may be needed if transitioning to AutoNotify or using something or than Home Assistant. There is also an import function in AutoNotify to pull in previous sightings and plate classifications from `anpr2mqtt` configuration.

## Features

- **Minimal configuration**
  - Ready configured to work with popular Hikvision ANPR camera settings
  - See [Example Camera Configuration](https://anpr2mqtt.rhizomatics.org.uk/camera/index.md)
- **File System Integration**
  - Watches directory for camera images using [Watchdog](https://python-watchdog.readthedocs.io/en/stable/index.html)
    - Uses [inotify](https://www.man7.org/linux/man-pages/man7/inotify.7.html) on Linux, or equiv on other operating systems for efficient listening to file system events without continual polling
  - Extracts target ( for example licence plate ), timestamp and event type information from filenames
- **[Other Camera Events](https://anpr2mqtt.rhizomatics.org.uk/camera/#other-events)**
  - Face capture, scene change, line crossing, region entry or any other event a camera uploads images for, by configuration
  - Kept apart from plates, with no plate lookups or corrections
  - Paired images, such as a face crop and its whole scene, as one event
  - Minimum gap between events, for noisy or repeating events
- **[Home Assistant Integration](https://anpr2mqtt.rhizomatics.org.uk/homeassistant/index.md)**
  - Publishes plates to MQTT for Home Assistant as a [MQTT Sensor Entity](https://www.home-assistant.io/integrations/sensor.mqtt/), and other events as a [MQTT Event Entity](https://www.home-assistant.io/integrations/event.mqtt/)
  - [Image counts](https://anpr2mqtt.rhizomatics.org.uk/homeassistant/#image-counts) per event, for today, this week and in total, for health checks such as a camera that's stopped sending images
  - [Upload monitoring](https://anpr2mqtt.rhizomatics.org.uk/camera/#uploads) of an ftp landing zone, counting every file that arrives, as a sensor that doesn't notify
  - Auto-discovery configuration for Home Assistant
  - Creates [MQTT Image Entity](https://www.home-assistant.io/integrations/image.mqtt/) on Home Assistant for image snapshot, so no web access to ftp needed
  - Optionally also creates an [MQTT Camera Entity](https://www.home-assistant.io/integrations/camera.mqtt/)
- **Integrated OCR** (Text Recognition)
  - OCR-based extraction of fields using [tesseract-ocr](https://github.com/tesseract-ocr/tesseract)
    - By default direction detection (*Forward*/*Reverse*) for example as stamped on an image by a Hikvision ANPR camera
    - Corrections by regular expression to fix OCR mis-readings
- Plate Enrichment
  - Tracks and counts previous sightings
  - Configurable to classify plates as known, to be ignored or as a potential threat
  - Regular expression based corrections, for known plates that the ANPR sometimes mis-reads
  - Fuzzy match corrections for known plates, based on Levenshtein algorithm
  - UK Only
    - [DVLA Lookup](https://anpr2mqtt.rhizomatics.org.uk/api/index.md) if API_KEY provided, for detailed MOT and tax information
    - Lookups cached for configurable time
  - For Home Assistant, [Camera AutoNotify](https://camera-autonotify.rhizomatics.org.uk) is recommended to do this rather than in anpr2mqtt.
- Frigate Integration
  - All the same enrichments, including DVLA lookup, can also be extended to licence plates recognized by Frigate ( see [Frigate License Plate Recognition](https://docs.frigate.video/configuration/license_plate_recognition)), assuming that `frigate/events` and `frigate/tracked_object_update` topics are on the same MQTT broker.
  - Shares same sighting tracking as local images
  - For Home Assistant, [Camera AutoNotify](https://camera-autonotify.rhizomatics.org.uk) is recommended to do this rather than in anpr2mqtt.
- Auto clear vehicle state optionally, after configurable time
- [Debug Tools](https://anpr2mqtt.rhizomatics.org.uk/debug_tools/index.md) built-in

## Container Deployment

Build and run with Docker or Podman, example [docker-compose.yaml](https://anpr2mqtt.rhizomatics.org.uk/examples/docker_compose/index.md) provided.

## Configuration

ANPR2MQTT uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), which means configuration can happen in a variety of ways, and these can be combined - yaml configuration file, environment variables, Docker Secrets, built-in defaults, and `.env` file or command line arguments.

Camera names, and each event's `event`, `camera` and `target_type`, are used in MQTT topics, Home Assistant entity ids and file names, so they must be 1 to 64 letters, digits, `_` or `-`, such as `front_door`. Anything else, such as a space, `/`, `.`, `+` or `#`, stops `anpr2mqtt` starting, with a message saying which one. Use `description` for text to show in Home Assistant.

### CLI Arguments

Every configuration setting can be passed as a command line argument, using dot notation for nested settings. This is the highest-priority source and overrides all other configuration.

```bash
uvx anpr2mqtt --mqtt.host 192.168.1.10 --mqtt.port 1884 --log_level DEBUG
```

Run `uvx anpr2mqtt --help` to see all available flags, and find more information at [Debug Tools](https://anpr2mqtt.rhizomatics.org.uk/debug_tools/index.md)

When running outside Docker, OCR also needs the `tesseract` binary installed, e.g. `brew install tesseract` on macOS.

## Home Assistant Integration

See [Home Assistant Integration](https://anpr2mqtt.rhizomatics.org.uk/homeassistant/index.md) for configuration and example notification automation.

### Environment Variables

[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) needs double underscores for environment variables in config sections. For example, `MQTT__HOST` means set the value `host` in the `mqtt` config section.

| Env Variable       | Description                | Default     |
| ------------------ | -------------------------- | ----------- |
| `MQTT__HOST`       | MQTT broker hostname       | `localhost` |
| `MQTT__PORT`       | MQTT broker port           | `1883`      |
| `MQTT__TOPIC_ROOT` | MQTT topic for events      | `anpr2mqtt` |
| `MQTT__USER`       | MQTT username              | -           |
| `MQTT__PASS`       | MQTT password              | -           |
| `LOG_LEVEL`        | Python logging level       | INFO        |
| `DVLA__API_KEY`    | API Key for Gov API Lookup | -           |

## Image Filename Format

Expected format: `YYYYMMDDHHMMSSmmm_PLATE_VEHICLE_DETECTION.jpg`

Example: `20180502174029596_A2GEO_VEHICLE_DETECTION.jpg`

Each event should say what it's for with `target_type`, `plate` for ANPR, or anything else for other events. Leaving it out means `plate`, so older configurations still work, but any event without it becomes a plate event, with a plate sensor, even on a camera with no ANPR.

A regular expression can be defined to match different file name formats, such as for other events, `10.180.10.30_01_20261127071024588_SCENE_CHANGE_DETECTION.jpg`, see [Other Events](https://anpr2mqtt.rhizomatics.org.uk/camera/#other-events).

## Image Box Coordinates

Where cameras provide an estimated direction for the vehicle, this can be captured via OCR and included in the response. See [OCR](https://anpr2mqtt.rhizomatics.org.uk/ocr/index.md) for an explanation and examples.

## Auto Clear

By default, the state will be reset back to unavailable 5 minutes after a detection, while the image will be left present as record of last known vehicle. This behavior can be changed ( to switch off auto clear, or change the time lag, or also clear image ) using the `autoclear` configuration for each event.

configuration snippet

```yaml
- camera: shed
  target_type: plate
  watch_path: /ftp/shedcam
  autoclear:
    post_event: 360
    state: True
    image: False
```

## Corrections

The licence plate detection may mis-read or miss some of the characters of the plate. When the result is published to MQTT, both the raw original and corrected versions are provided.

Two mechanisms help with this:

### Fuzzy Matching

The Levenshtein method is used to compare the plate against a list of known plates in the configuration, subject to a maximum distance tolerance ( number of mismatched characters ) defined by `auto_match_tolerance` for the event. If its a match for more than one, the plate with least distance is chosen.

### Regex / String Matching

Each known plate can be associated with a list of regular expressions and/or plain strings, and these will be checked for every discovered licence plate.

### Working with Frigate

A Frigate camera's plates are published as the camera of the same name in the `cameras` config. Where the namesdiffer, link the camera to the Frigate camera by name in `linked_cameras`:

```yaml
cameras:
- name: drive
  linked_cameras:
    frigate: driveway_lpr
    unifiprotect: Driveway G4
```

`linked_cameras` can also name the same camera in any other integration that sees it, such as UniFi Protect, Viseron or Blue Iris, each keyed by its Home Assistant domain, `unifiprotect`, `viseron` or `blueiris`. They're given to Home Assistant as the `linked_cameras` attribute, along with the Frigate camera matched by name, for integrations that join anpr2mqtt sightings to the events of the cameras they supplement.

## Primary Dependencies

- **watchdog** - File system monitoring (cross-platform)
- **paho-mqtt** - MQTT client
- **Pillow** - Image processing
- **pytesseract** - OCR for direction detection
- **structlog** - Structured logging
- **niquests** - API Client
- **niquests-cache** - API result caching

## Distribution

ANPR2MQTT is free and open sourced under the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).

## Rhizomatics Open Source for Home Assistant

### HACS

- [AutoArm](https://autoarm.rhizomatics.org.uk) - Automatically arm and disarm Home Assistant alarm control panels using physical buttons, presence, calendars, sun and more
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - OpenTelemetry (OTLP) and Syslog event capture for Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Unified notification for easy multi-channel messaging, including powerful chime and security camera integration.

### Python / Docker

- [Updates2MQTT](https://updates2mqtt.rhizomatics.org.uk) - Automatically notify via MQTT on Docker image updates, with advanced handling to extract versions and release notes from images, and option to remotely pull and restart containers from Home Assistant. Also available on [PyPI](https://pypi.org/project/updates2mqtt/)
