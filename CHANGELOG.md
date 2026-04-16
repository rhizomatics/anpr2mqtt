# 1.0.0
## Known Targets Configuration
- Restructured from 2 fixed groups ("known" and "dangerous") to a flexible groups structure, so any number of groups can be created, for example "family","postman","delivery","utility"
  - Groups can have an `icon`,`entity_id` and `priority`, targets will inherit these if they don't have their own, or leave empty at group level and populate only on group members
  - Existing config using `known` or `dangerous` will be translated at runtime to new structure
- `correction` lists of patterns or strings can now be added directly to target
- `auto_match_tolerance` now moved to Event config
- API lookup can be configured at target or group level, defaults to off, since vehicles already known
## Target specific sensors in Home Assistant
- Groups and individual targets can be given an `entity_id` and a sensor will be created in Home Assistant using MQTT discovery
  - State for the sensor will be timestamp of last sighting, and combined past history will be attributes
  - Any number of vehicles can be combined in a single sensor, so for example see last post vehicle detected, even if several come to the property
- Targets can now be more than a simple string - currently `description` and `entity_id` supported
## Time Analysis
- Previous sightings now have a richer set of analysis, with histogram data by visit hour of day, earliest/latest times
## Home Assistant
- Improved example automation
- Icon now configurable in the Event config, previously fixed at `mdi:car-back`
## Internals and Fixes
- Corrected example configurations
- Refactored internally to a `Sighting` class and a more complete `Target` definition, replacing ad hoc dicts

# 0.10.2
- Improve error handling when started without config file
- Fix healthcheck script use of MQTT env vars
# 0.10.1
- Update Home Assistant example to display a history summary, use the new `spoken_message` feature of Supernotify, and check `event_image_url` existing
- Now warns at start up if `image_base_url` has a trailing slash
- Always send a `history` value, defaulting to empty dict, to simplify HA templates
- Added pypi publishing
# 0.10.0
- Auto match plates with potential errors to known plates, using Levenshtein algorithm, and controlled via new `auto_match_tolerance` setting
- Historical analysis now provides a count of times vehicle previously seen
by hour of the day, the earliest and latest time of day ever seen, and if the current visit is within that range
# 0.9.2
- Test fixes
# 0.9.1
- Fixes for API Client caching and logging
- Report % saved on image compression
- Option to specify a `verify_plate` to check the DVLA API at startup
# 0.9.0
- Replaced the now doubtfully maintained httpx with niquests, and hishel with requests-cache
- Settings now has configuration for `cache_dir` and to choose `cache_type` between `FILE` or `MEMORY`
- Add DVLA lookup to the CLI tools
  - `uv run --with anpr2mqtt tools dvla_lookup MAG1C --dvla.api_key <my_api_key>`
    - (can skip the `--with anpr2mqtt` if running from checked out dir)
# 0.8.0
- Autoclear to optionally reset state after period of time
- Validate all regular expressions at startup
# 0.7.2
- Python moved to 3.14 for docker image
## Home Assistant Integration
- Remove state republication on HA restart
# 0.7.1
## Home Assistant Integration
- Now subscribes to the HA 'birth' and 'last will' messages to re-publish on HA restart
- State always published at startup
- Camera settings can be added, to add `area` and `live_url` to the message
- Camera Entity can now be added, and option to switch this and/or the Image entity creation
## Directory Scanning
- `watch_tree` can be set to recursively watch all subdirectories below `watch_path`
## MQTT
- MQTT protocol can now be set up to v5 or down to v3, defaults to v3.11
# 0.6.2
## Examples
- Added an example Home Assistant automation to generate notifications using details and priority from MQTT event
# 0.6.1
- Log state topic at startup
# 0.6.0
- Multiple events now supported, e.g. face detection or line crossing
- OCR field definitions can be reused across events, or different crop definitions for the same value
  - For example, `vehicle_direction` could have different bounding boxes, or even values, on different cameras
- Suggested area provided for Home Assistant Device if configured
# 0.5.0
- Home Assistant Device creation optional
- Simplified OCR coordinates
- Flexible OCR field capture
# 0.4.1
- Improve CLI handling for tools
- File name parsing now more forgiving of regexp format
# 0.4.0
- CLI handling and env vars switched from click to pydantic-settings
- Added new anpr2mqtt.yaml config
- Migrated sightings tracker from appdaemon app
- Migrated plate classification from appdaemon app
- Added DVLA api lookup from appdaemon app