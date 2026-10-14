# Home Assistant Automation

Example Home Assistant automation to send notifications when an MQTT update is received.

This uses [Supernotify](https://supernotify.rhizomatics.org.uk) to respect priorities and make multiple notifications for the same event - in the live example this includes Mobile Push alerts, email (with the snapshot ANPR image as an attachment), chimes ( hunting horn for known vehicles, doorbell chimes for unknown ) and Alexa spoken announcements.

It can be adapted to a plain notification by removing the `data` section and changing the `action`. Modern Home Assistant UI allows pasting in yaml to create automations.

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
