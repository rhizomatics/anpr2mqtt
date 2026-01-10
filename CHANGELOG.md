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