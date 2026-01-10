# Environment File

Example `.env` file for Docker Compose configuration to separately store the environment variables.

``` bash
# Example env file for docker-compose.yaml
# Used by both the app itself and the healthcheck script

# To use these, add to config.yaml like ${oc.env:MQTT_HOST}

MQTT__HOST=192.168.0.1
MQTT__PORT=1883
MQTT__USER=my_mqtt_user
MQTT__PASS=my_mqtt_secret
```