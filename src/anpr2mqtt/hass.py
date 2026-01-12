import datetime as dt
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from PIL import Image

import anpr2mqtt
from anpr2mqtt.settings import EventSettings

from .const import ImageInfo

log = structlog.get_logger()


def post_discovery_message(
    client: mqtt.Client,
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
        "default_entity_id":f"sensor.{event_config.event}_{event_config.camera}",
        "unique_id": f"{event_config.event}_{event_config.camera}",
        "state_topic": state_topic,
        "json_attributes_topic": state_topic,
        "icon": "mdi:car-back",
        "name": name,
    }
    if device_creation:
        add_device_info(payload, event_config)
    topic = f"{discovery_topic_prefix}/sensor/{event_config.camera}/{event_config.event}/config"
    client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
    log.info("Published HA MQTT sensor Discovery message to %s", topic)

    payload = {
        "o": {
            "name": "anpr2mqtt",
            "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "url": "https://anpr2mqtt.rhizomatics.org.uk",
        },
        "device_class": None,
        "unique_id": f"{event_config.event}_{event_config.camera}",
        "default_entity_id":f"image.{event_config.event}_{event_config.camera}",
        "image_topic": image_topic,
        "json_attributes_topic": state_topic,
        "icon": "mdi:car-back",
        "name": name,
    }
    if device_creation:
        add_device_info(payload, event_config)
    topic = f"{discovery_topic_prefix}/image/{event_config.camera}/{event_config.event}/config"
    client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
    log.info("Published HA MQTT Discovery message to %s", topic)


def add_device_info(payload: dict[str, Any], event_config: EventSettings) -> None:
    payload["dev"] = {
        "name": f"anpr2mqtt on {event_config.camera}",
        "sw_version": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
        "manufacturer": "rhizomatics",
        "identifiers": [f"{event_config.event}_{event_config.camera}.anpr2mqtt"],
    }
    if event_config.area:
        payload["dev"]["suggested_area"] = event_config.area


def post_state_message(
    client: mqtt.Client,
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

        client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
        log.debug("Published HA MQTT State message to %s: %s", topic, payload)
    except Exception as e:
        log.error("Failed to publish event %s: %s", payload, e, exc_info=1)


def post_image_message(client: mqtt.Client, topic: str, image: Image.Image, img_format: str = "JPEG") -> None:
    try:
        img_byte_arr = BytesIO()
        image.save(img_byte_arr, format=img_format)
        img_bytes = img_byte_arr.getvalue()

        client.publish(topic, payload=img_bytes, qos=0, retain=True)
        log.debug("Published HA MQTT Image message to %s: %s bytes", topic, len(img_bytes))
    except Exception as e:
        log.error("Failed to publish image entity: %s", e, exc_info=1)
