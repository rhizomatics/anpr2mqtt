# Home Assistant Automation

Example Home Assistant automation to send notifications when an MQTT update is received.

This uses [Supernotify](https://supernotify.rhizomatics.org.uk) to respect priorities and make multiple notifications for the same event - in the live example this includes Mobile Push alerts, email (with the snapshot ANPR image as an attachment), chimes ( hunting horn for known vehicles, doorbell chimes for unknown ) and Alexa spoken announcements.

It can be adapted to a plain notification by removing the `data` section and changing the `action`. Modern Home Assistant UI allows pasting in yaml to create automations.

```yaml
--8<-- "examples/ha_automation.yaml"
```