# HomeAssistant Integration

`anpr2mqtt` represents each ANPR cameras as a [MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/) and [MQTT Image](https://www.home-assistant.io/integrations/image.mqtt/) entities, and uses [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) so that HomeAssistant automatically picks up components discovered by ANPR2MQTT with zero configuration on HomeAssistant itself.

The MQTT image entity can be used in the same way as a `camera` entity, so can be included in mobile push, email etc notifications, or added to a Home Assistant dashboard. See the example below, or use [Supernotify](https://supernotify.rhizomatics.org.uk) camera support.

## Attributes

Both the `sensor` and `image` attributes have the same extensive set of attributes.

The target value will also appear in a field named after `target_type`, for example, `plate` for easier to read Home Assistant automations.

| Attribute                  | Example                                                                                |
| -------------------------- | -------------------------------------------------------------------------------------- |
| target                     | J23TST                                                                                 |
| target_type                | plate                                                                                  |
| `target_type`              | J23TST                                                                                 |
| source                     | filesystem                                                                             |
| reg_info                   | null                                                                                   |
| area                       | driveway                                                                               |
| camera                     | drivewacam                                                                             |
| orig_target                | J23TST                                                                                 |
| ignore                     | false                                                                                  |
| known                      | true                                                                                   |
| dangerous                  | false                                                                                  |
| priority                   | medium                                                                                 |
| description                | Amazon Prime                                                                           |
| history.previous_sightings | 15                                                                                     |
| history.last_seen          | 2026-01-08T14:15:28.000319+00:00                                                       |
| event_time                 | 2026-01-08T14:15:28.000320+00:00                                                       |
| event_image_url            | http://192.168.10.10/cctv//ftp/Driveway/20260108141528320_J23TST_VEHICLE_DETECTION.jpg |
| image_event                | VEHICLE DETECTION                                                                      |
| ext                        | jpg                                                                                    |
| image_size                 | 124907                                                                                 |

The `reg_info` will be populated with the licence plate API lookup, for example UK DVLA, if provided.

Some attributes are only present for events from a particular source, since they don't apply to the other. `source` is always `filesystem` or `frigate`, and can be used to tell which set to expect:

| Attribute         | Source                                | Example                                                      |
| ----------------- | ------------------------------------- | ------------------------------------------------------------ |
| file_path         | filesystem                            | /ftp/Driveway/20260108141528320_J23TST_VEHICLE_DETECTION.jpg |
| vehicle_direction | filesystem (OCR field, if configured) | Forward                                                      |
| frigate_event_id  | frigate                               | 1790171055.400738-28axk4                                     |
| frigate_ui_url    | frigate                               | http://192.168.10.10:5000/events?id=1790171055.400738-28axk4 |
| frigate           | frigate                               | `{"recognized_license_plate_score": 0.92}`                   |

`event_image_url` is populated for both sources, pointing directly at the event image (the filesystem image on the local web server, or the Frigate event snapshot API), so notification automations can rely on it regardless of which source raised the event.

## Example Automation

This example uses [Supernotify](https://supernotify.rhizomatics.org.uk) to generate multiple alerts, such as email with ANPR image attachment, mobile push with the image and click through to Frigate page, voice assistant announcement and sounding chimes. It can also be used with any of the built-in notification integrations, though without the same multiple-transport and media handling capabilities.

```yaml
alias: Driveway ANPR Alert
description: Notify via email, chime, Alexa and mobile push when a vehicle identified
triggers:
  - trigger: state
    entity_id:
      - sensor.anpr_driveway
    attribute: event_time
conditions:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.anpr_driveway
        state:
          - unavailable
          - unknown
actions:
  - action: notify.supernotifier
    metadata: {}
    data:
      message: >-
        {{ trigger.to_state.attributes.description }} with {{
        trigger.to_state.attributes.plate }} spotted at {{
        trigger.to_state.attributes.camera }} camera{% if
        trigger.to_state.attributes.vehicle_direction is defined %}, moving {{
        trigger.to_state.attributes.vehicle_direction }}{% endif %}

        {% if trigger.to_state.attributes.history.previous_sightings == 0 %} Not
        previously sighted  {% else %}  with {{
        trigger.to_state.attributes.history.previous_sightings }} previous
        sightings. {% endif %} {% if
        trigger.to_state.attributes.history.last_seen is defined and
        trigger.to_state.attributes.history.last_seen is not none %} last
        seen on {{ trigger.to_state.attributes.history.last_seen[:10] }} at
        {{ trigger.to_state.attributes.history.last_seen[11:16] }}   {%
        endif %}

        {% if 'reg_info' in trigger.to_state.attributes and
        trigger.to_state.attributes.reg_info is not none %}  DVLA info: {{
        trigger.to_state.attributes.reg_info }}   {% endif %}

        {% if 'hourly_counts' in trigger.to_state.attributes.history and
        trigger.to_state.attributes.history.hourly_counts is not none %}  Visit
        History: {% for time,count in
        trigger.to_state.attributes.history.hourly_counts.items() %}
          {{ time }}{% if int(time) < 12 %}am{% else %}pm{% endif %} : {{ count }} times
        {% endfor %}{% endif %}
      title: >-
        {{ trigger.to_state.attributes.description }} spotted on {{
        trigger.to_state.attributes.camera }} camera
      data:
        priority: "{{ trigger.to_state.attributes.priority }}"
        spoken_message: >-
          {{ trigger.to_state.attributes.description }} with {{
          trigger.to_state.attributes.plate }} spotted at {{
          trigger.to_state.attributes.camera }} camera{% if
          trigger.to_state.attributes.vehicle_direction is defined %}, moving {{
          trigger.to_state.attributes.vehicle_direction }}{% endif %}
        apply_scenarios: >-
          {% if trigger.to_state.attributes.known %}known_vehicle{% else
          %}unknown_vehicle{% endif %}
        constrain_scenarios:
          - known_vehicle
          - unknown_vehicle
        media:
          camera_entity_id: image.anpr_{{trigger.to_state.attributes.camera}}
          snapshot_url: >-
            {% if 'event_image_url' in trigger.to_state.attributes %}{{
            trigger.to_state.attributes.event_image_url }}{% endif %}
mode: single
```

## Configuration

In general, no configuration is needed, if Home Assistant is already running with MQTT, and the defaults haven't been changed.

Make sure `anpr2mqtt` is publishing to the same broker, the [MQTT Integration](https://www.home-assistant.io/integrations/mqtt/) is installed and automatic discovery is not disabled.

The `homeassistant` default topic prefix matches the default ANPR2MQTT config, if its changed in HomeAssistant, then the ANPR2MQTT config must be changed to match.

## Device Creation

A Home Assistant device will be created for each ANPR2MQTT camera, and Home Assistant will then group the relevant entities together on this device page. Use `device_creation: false` in the `homeassistant` config block if you want to switch off this behaviour.

## MQTT Topics

There are 3 separate types of MQTT topic used for HomeAssisstant integration:

- *Config* to support auto discovery.
  - A topic is created per camera, with a name like `homeassistant/sensor/driveway/anpr/config`.
  - Optionally a `image` and `camera` topic can be created
  - The `homeassistant` topic prefix can also be configured.
- *State* to report the last plate seen and attributes
  - `anpr2mqtt/camera_name/state`
  - `anpr2mqtt/camera_name/image`

## Verifying it Works

Rather than wait for a container to need an update, you can check right away that Home Assistant has recognized the ANPR entities.

From the [Entities View](https://www.home-assistant.io/docs/configuration/entities_domains/), or the [Developer Tools](https://www.home-assistant.io/docs/tools/dev-tools/), filter the entities by `anpr.`

## Republishing on Home Assistant restart

Home Assistant's MQTT integration can publish the status of Home Assistant itself to *birth* and *last will and testament* topics. Current default for this is `homeassistant/status`, though older installations may have `hass/status` - if its non-default, override in the config under `homeassistant: status_topic`.

## Individual or Group Sensors

A single target, a group, or any mix of groups and targets, can be given an `entity_id` and published to Home Assistant as a sensor, with the state value being the last sighting timestamp, and the attributes being the combined history of the targets.

## More Home Assistant information

- [MQTT Integration](https://www.home-assistant.io/integrations/mqtt/)
  - Includes setting up a MQTT broker, MQTT Discovery, and trouble-shooting
- [MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/)
- [MQTT Image](https://www.home-assistant.io/integrations/image.mqtt/)
