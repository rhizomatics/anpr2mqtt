import json
import random
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from PIL import Image

import anpr2mqtt
from anpr2mqtt.settings import CameraSettings, EventSettings, HomeAssistantSettings
from anpr2mqtt.tracker import Sighting, Target

from .const import ImageInfo

log = structlog.get_logger()


class HomeAssistantPublisher:
    def __init__(self, client: mqtt.Client, cfg: HomeAssistantSettings) -> None:
        self.client: mqtt.Client = client
        self.hass_status_topic: str = cfg.status_topic
        self.discovery_topic_prefix: str = cfg.discovery_topic_root
        self.device_creation: bool = cfg.device_creation
        self.republish: dict[str, Any] = {}
        self.hass_online: bool | None = None

    def start(self) -> None:
        log.info("Subscribing to Home Assistant birth and last will at %s", self.hass_status_topic)
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_unsubscribe = self.on_unsubscribe
        self.client.subscribe(self.hass_status_topic)

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
            decoded: str | None = msg.payload.decode("utf-8") if msg.payload else None
            if decoded == "offline":
                log.warn("Home Assistant gone offline")
                self.hass_online = False
            elif decoded == "online":
                if self.hass_online is False:
                    log.info("Home Assistant back online")
                    self.hass_online = True
                    self.republish_discovery()
                else:
                    log.info("Home Assistant online")
                    self.hass_online = True
            else:
                log.warn("Unknown Home Assistant status payload: %s", msg.payload)
        else:
            log.debug("Unknown message on %s", msg.topic)

    def republish_discovery(self) -> None:
        for topic, payload in self.republish.items():
            log.debug("Republishing to %s", topic)
            # add jitter to republish to reduce herd load on HA after restart
            time.sleep(random.randint(1, 10))  # noqa: S311
            self.client.publish(topic, payload)

    def publish_sensor_discovery(self, state_topic: str, event_config: EventSettings, camera: CameraSettings) -> None:
        name: str = event_config.description or f"{event_config.event} {camera.name}"
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
        if self.device_creation:
            self.add_device_info(payload, camera)
        topic: str = f"{self.discovery_topic_prefix}/sensor/{event_config.camera}/{event_config.event}/config"
        msg: str = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = msg
        log.info("Published HA MQTT sensor Discovery message to %s", topic)

    def publish_image_discovery(
        self, state_topic: str, image_topic: str, event_config: EventSettings, camera: CameraSettings
    ) -> None:
        name: str = event_config.description or f"{event_config.event} {event_config.camera}"
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
        if self.device_creation:
            self.add_device_info(payload, camera)
        topic = f"{self.discovery_topic_prefix}/image/{event_config.camera}/{event_config.event}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = msg
        log.info("Published HA MQTT Discovery message to %s", topic)

    def publish_camera_discovery(
        self, state_topic: str, image_topic: str, event_config: EventSettings, camera: CameraSettings
    ) -> None:
        name: str = event_config.description or f"{event_config.event} {event_config.camera}"
        payload = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "unique_id": f"{event_config.event}_{camera.name}",
            "default_entity_id": f"camera.{event_config.event}_{camera.name}_anpr",
            "topic": image_topic,
            "json_attributes_topic": state_topic,
            "icon": "mdi:car-back",
            "name": name,
        }
        if self.device_creation:
            self.add_device_info(payload, camera)
        topic = f"{self.discovery_topic_prefix}/camera/{camera.name}/{event_config.event}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = msg
        log.info("Published HA MQTT Discovery message to %s", topic)

    def publish_target_sensor_discovery(
        self,
        entity_id: str,
        target_type: str,
        targets: list[Target],
        state_topic: str,
    ) -> None:
        payload: dict[str, Any] = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "unique_id": f"{target_type}_{hash(':'.join(t.id for t in targets))}",
            "default_entity_id": f"sensor.{entity_id}",
            "name": targets[0].description if len(targets) == 1 else entity_id,
            "state_topic": state_topic,
            "json_attributes_topic": state_topic,
            "value_template": "{{ value_json.last_seen }}",
            "device_class": "timestamp",
            "icon": targets[0].icon if len(targets) == 1 else None,
        }
        topic = f"{self.discovery_topic_prefix}/sensor/{entity_id}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = msg
        log.info("Published HA MQTT target sensor Discovery message to %s", topic)

    def publish_target_state(self, state_topic: str, time_analysis: dict[str, Any], description: str | None = None) -> None:
        payload: dict[str, Any] = {**time_analysis}
        if description:
            payload["description"] = description
        try:
            msg = json.dumps(payload)
            self.client.publish(state_topic, payload=msg, qos=0, retain=True)
            log.debug("Published target state to %s: %s", state_topic, payload)
        except Exception as e:
            log.error("Failed to publish target state to %s: %s", state_topic, e, exc_info=1)

    def add_device_info(self, payload: dict[str, Any], camera: CameraSettings) -> None:
        payload["dev"] = {
            "name": f"anpr2mqtt on {camera.name}",
            "sw_version": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "manufacturer": "rhizomatics",
            "identifiers": [f"{camera.name}.anpr2mqtt"],
        }
        if camera.area:
            payload["dev"]["suggested_area"] = camera.area

    def post_state_message(
        self,
        topic: str,
        sighting: Sighting | None,
        event_config: EventSettings,
        camera: CameraSettings,
        ocr_fields: dict[str, str | None] | None = None,
        image_info: ImageInfo | None = None,
        time_analysis: dict[str, Any] | None = None,
        url: str | None = None,
        error: str | None = None,
        file_path: Path | None = None,
        reg_info: Any = None,
    ) -> None:

        payload: dict[str, Any] = sighting.as_dict() if sighting else {"target": None, "target_type": event_config.target_type}
        payload.update(
            {
                event_config.target_type: sighting.target.id if sighting else None,
                "event": event_config.event,
                "camera": camera.name or "UNKNOWN",
                "area": camera.area,
                "live_url": camera.live_url,
                "reg_info": reg_info,
                "history": time_analysis,
            }
        )
        if ocr_fields:
            payload.update(ocr_fields)
        if error:
            payload["error"] = error
        if url is not None:
            payload["event_image_url"] = url
        if file_path is not None:
            payload["file_path"] = str(file_path)

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
            log.debug("Published HA MQTT State message to %s: %s", topic, payload)
        except Exception as e:
            log.error("Failed to publish event %s: %s", payload, e, exc_info=1)

    def post_image_message(self, topic: str, image: Image.Image | None, img_format: str = "JPEG") -> None:
        try:
            if image is None:
                self.client.publish(topic, payload=None, qos=0, retain=True)
                log.debug("Cleared HA MQTT Image message at %s", topic)
                return
            img_byte_arr = BytesIO()
            image.save(img_byte_arr, format=img_format)
            img_bytes = img_byte_arr.getvalue()

            self.client.publish(topic, payload=img_bytes, qos=0, retain=True)
            log.debug("Published HA MQTT Image message to %s: %s bytes", topic, len(img_bytes))
        except Exception as e:
            log.error("Failed to publish image entity: %s", e, exc_info=1)
