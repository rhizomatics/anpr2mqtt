# Minimal Configuration

Smallest working configuration ( although the actual smallest is no file at all and using only environment variables for MQTT )

```yaml
---
events:
  - target_type: plate
    watch_path: /ftp/hikcam2
mqtt:
  user: anpr2mqtt
  password: my_secret_password
  # assumes mqtt broker on localhost
```
