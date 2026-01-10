# HomeAssistant Integration

 `anpr2mqtt` represents each ANPR cameras as a [MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/) and [MQTT Image](https://www.home-assistant.io/integrations/image.mqtt/) entities, and uses [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) so that HomeAssistant automatically picks up components discovered by ANPR2MQTT with zero configuration on HomeAssistant itself. 

 The MQTT image entity can be used in the same way as a `camera` entity, so can be included in mobile push, email etc notifications, or added to a Home Assistant dashboard. See the example below, or use [Supernotify](https://supernotify.rhizomatics.org.uk) camera support.

## Attributes

Both the `sensor` and `image` attributes have the same extensive set of attributes

| Attribute          | Example                                                      |
|--------------------|--------------------------------------------------------------|
| plate              | J23TST                                                       |
| vehicle_direction  | Forward                                                      |
| reg_info           | null                                                         |
| camera             | driveway                                                     |
| file_path          | /ftp/Driveway/20260108141528320_J23TST_VEHICLE_DETECTION.jpg |
| event_image_url    | http://192.168.10.10/cctv//ftp/Driveway/20260108141528320_J23TST_VEHICLE_DETECTION.jpg |
| orig_plate         | J23TST                                                       |
| ignore             | false                                                        |
| known              | true                                                         |
| dangerous          | false                                                        |
| priority           | medium                                                       |
| description        | Amazon Prime                                                 |
| previous_sightings | 15                                                           |
| last_sighting      | 2026-01-08T14:15:28.000319+00:00                             |
| event_time         | 2026-01-08T14:15:28.000320+00:00                             |
| ext                | jpg                                                          |
| image_size         | 124907                                                       |

The `reg_info` will be populated with the licence plate API lookup, for example UK DVLA,
if provided.

## Example Automation

This example uses [Supernotify](https://supernotify.rhizomatics.org.uk) to generate multiple
alerts, such as email with ANPR image attachment, mobile push with the image and click through to
Frigate page, voice assistant announcement and sounding chimes. It can also be used with any of the built-in notification integrations, though without the same multiple-transport and media handling capabilities.

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

        {% if trigger.to_state.attributes.previous_sightings == 0 %} 
        Not previously sighted  
        {% else %}  
        {{ trigger.to_state.attributes.previous_sightings }} previous sightings,
        last seen on {{ trigger.to_state.attributes.last_sighting[:10] }} at {{
        trigger.to_state.attributes.last_sighting[11:16] }}   
        {% endif %}

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
          snapshot_url: "{{ trigger.to_state.attributes.event_image_url }}"
```

## Configuration

In general, no configuration is needed, if Home Assistant is already running with MQTT, and the defaults haven't been changed.

Make sure `anpr2mqtt` is publishing to the same broker, the [MQTT Integration](https://www.home-assistant.io/integrations/mqtt/) is installed and automatic discovery is not disabled.

![Home Assistant MQTT Integration configuration](images/ha_mqtt_discovery.png "Home Assistant MQTT Discovery")

The `homeassistant` default topic prefix matches the default ANPR2MQTT config, if its changed in HomeAssistant, then the ANPR2MQTT config must be changed to match.

![Home Assistant updates in Settings](images/ha_update_page.png "Home Assistant Updates")

## Device Creation

A Home Assistant device will be created for each ANPR2MQTT camera, and Home Assistant
will then group the relevant entities together on this device page. Use `device_creation: false` in the 
`homeassistant` config block if you want to switch off this behaviour.

## MQTT Topics

There are 3 separate types of MQTT topic used for HomeAssisstant integration:

- *Config* to support auto discovery. 
    - A topic is created per camera, with a name like `homeassistant/sensor/camera/anpr/config`. 
    - The `homeassistant` topic prefix can also be configured.
- *State* to report the last plate seen and attributes
    - `anpr/camera_name/state`
    - `anpr/camera_name/image`


## Verifying it Works

Rather than wait for a container to need an update, you can check right away that
Home Assistant has recognized the ANPR entities.

From the [Entities View](https://www.home-assistant.io/docs/configuration/entities_domains/), or the
[Developer Tools](https://www.home-assistant.io/docs/tools/dev-tools/), filter
the entities by `anpr.` 

![Home Assistant Entities](images/ha_entities.png){width=640}

## More Home Assistant information

- [MQTT Integration](https://www.home-assistant.io/integrations/mqtt/)
    - Includes setting up a MQTT broker, MQTT Discovery, and trouble-shooting
- [MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/)
- [MQTT Image](https://www.home-assistant.io/integrations/image.mqtt/)
