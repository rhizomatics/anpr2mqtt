import datetime as dt
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from PIL import Image

import anpr2mqtt
from anpr2mqtt.settings import EventSettings

from .const import ImageInfo

log = structlog.get_logger()


class HomeAssistantPublisher:
    def __init__(self, client: mqtt.Client, hass_status_topic: str) -> None:
        self.client = client
        self.hass_status_topic = hass_status_topic
        self.client.subscribe(self.hass_status_topic)
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_unsubscribe = self.on_unsubscribe
        self.republish: dict[str, Any] = {}

    def on_subscribe(
        self,
        _client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_code_list: list[ReasonCode],
        properties: Properties | None = None,
    ) -> None:
        log.debug("on_subscribe, userdata=%s, mid=%s, reasons=%s, properties=%s", userdata, mid, reason_code_list, properties)

    def on_unsubscribe(
        self,
        _client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_code_list: list[ReasonCode],
        properties: Properties | None = None,
    ) -> None:
        log.debug("on_unsubscribe, userdata=%s, mid=%s, reasons=%s, properties=%s", userdata, mid, reason_code_list, properties)

    def on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback for incoming MQTT messages"""  # noqa: D401
        if msg.topic == self.hass_status_topic:
            if msg.payload == "offline":
                log.warn("Home Assistant gone offline")
            elif msg.payload == "online":
                log.info("Home Assistant now online")
                for topic, payload in self.republish.items():
                    log.debug("Republishing to %s", topic)
                    self.client.publish(topic, payload)
            else:
                log.warn("Unknown Home Assistant status payload: %s", msg.payload)

    def post_discovery_message(
        self,
        discovery_topic_prefix: str,
        state_topic: str,
        image_topic: str,
        event_config: EventSettings,
        device_creation: bool = True,
    ) -> None:
        name: str = event_config.description or f"{event_config.event} {event_config.camera}"
        payload: dict[str, Any] = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "device_class": None,
            "value_template": "{{ value_json.target }}",
            "default_entity_id": f"sensor.{event_config.event}_{event_config.camera}",
            "unique_id": f"{event_config.event}_{event_config.camera}",
            "state_topic": state_topic,
            "json_attributes_topic": state_topic,
            "icon": "mdi:car-back",
            "name": name,
        }
        if device_creation:
            self.add_device_info(payload, event_config)
        topic: str = f"{discovery_topic_prefix}/sensor/{event_config.camera}/{event_config.event}/config"
        msg: str = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = msg
        log.info("Published HA MQTT sensor Discovery message to %s", topic)

        payload = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "device_class": None,
            "unique_id": f"{event_config.event}_{event_config.camera}",
            "default_entity_id": f"image.{event_config.event}_{event_config.camera}",
            "image_topic": image_topic,
            "json_attributes_topic": state_topic,
            "icon": "mdi:car-back",
            "name": name,
        }
        if device_creation:
            self.add_device_info(payload, event_config)
        topic = f"{discovery_topic_prefix}/image/{event_config.camera}/{event_config.event}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = msg
        log.info("Published HA MQTT Discovery message to %s", topic)

    def add_device_info(self, payload: dict[str, Any], event_config: EventSettings) -> None:
        payload["dev"] = {
            "name": f"anpr2mqtt on {event_config.camera}",
            "sw_version": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "manufacturer": "rhizomatics",
            "identifiers": [f"{event_config.event}_{event_config.camera}.anpr2mqtt"],
        }
        if event_config.area:
            payload["dev"]["suggested_area"] = event_config.area

    def post_state_message(
        self,
        topic: str,
        target: str | None,
        event_config: EventSettings,
        ocr_fields: dict[str, str | None],
        image_info: ImageInfo | None = None,
        classification: dict[str, Any] | None = None,
        previous_sightings: int | None = None,
        last_sighting: dt.datetime | None = None,
        url: str | None = None,
        error: str | None = None,
        file_path: Path | None = None,
        reg_info: Any = None,
    ) -> None:
        payload: dict[str, Any] = {
            "target": target,
            "target_type": event_config.target_type,
            event_config.target_type: target,
            "event": event_config.event,
            "camera": event_config.camera or "UNKNOWN",
            "area": event_config.area,
            "reg_info": reg_info,
        }
        payload.update(ocr_fields)
        if error:
            payload["error"] = error
        if url is not None:
            payload["event_image_url"] = url
        if file_path is not None:
            payload["file_path"] = str(file_path)
        if classification is not None:
            payload.update(classification)
        if previous_sightings is not None:
            payload["previous_sightings"] = previous_sightings
        if last_sighting is not None:
            payload["last_sighting"] = last_sighting.isoformat()

        try:
            if image_info:
                payload.update(
                    {
                        "event_time": image_info.timestamp.isoformat(),
                        "image_event": image_info.event,
                        "ext": image_info.ext,
                        "image_size": image_info.size,
                    }
                )
            msg: str = json.dumps(payload)
            self.client.publish(topic, payload=msg, qos=0, retain=True)
            self.republish[topic] = msg
            log.debug("Published HA MQTT State message to %s: %s", topic, payload)
        except Exception as e:
            log.error("Failed to publish event %s: %s", payload, e, exc_info=1)

    def post_image_message(self, topic: str, image: Image.Image, img_format: str = "JPEG") -> None:
        try:
            img_byte_arr = BytesIO()
            image.save(img_byte_arr, format=img_format)
            img_bytes = img_byte_arr.getvalue()

            self.client.publish(topic, payload=img_bytes, qos=0, retain=True)
            self.republish[topic] = img_bytes
            log.debug("Published HA MQTT Image message to %s: %s bytes", topic, len(img_bytes))
        except Exception as e:
            log.error("Failed to publish image entity: %s", e, exc_info=1)
