# 0.9.0
- Replaced the now doubtfully maintained httpx with niquests, and hishel with requests-cache
- Settings now has configuration for `cache_dir` and to choose `cache_type` between `FILE` or `MEMORY`
- Add DVLA lookup to the CLI tools
  - `uv run tools dvla_lookup MAG1C --dvla.api_key <my_api_key>`
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