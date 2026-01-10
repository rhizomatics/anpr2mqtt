import datetime as dt
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from PIL import Image

import anpr2mqtt

from .const import ImageInfo

log = structlog.get_logger()


def post_discovery_message(
    client: mqtt.Client, discovery_topic_prefix: str, state_topic: str, image_topic: str, camera: str
) -> None:
    topic = f"{discovery_topic_prefix}/sensor/{camera}/anpr/config"
    payload: dict[str, Any] = {
        "o": {
            "name": "anpr2mqtt",
            "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "url": "https://anpt2mqtt.rhizomatics.org.uk",
        },
        "device_class": None,
        "value_template": "{{ value_json.plate }}",
        "unique_id": f"anpr_{camera}",
        "state_topic": state_topic,
        "json_attributes_topic": state_topic,
        "icon": "mdi:car-back",
        "name": f"ANPR {camera} Plate",
        "dev": {
            "name": f"anpr2mqtt on {camera}",
            "sw_version": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "manufacturer": "rhizomatics",
            "identifiers": [f"{camera}.anpr2mqtt"],
        },
    }
    client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
    log.info("Published HA MQTT sensor Discovery message to %s", topic)

    topic = f"{discovery_topic_prefix}/image/{camera}/anpr/config"
    payload = {
        "o": {
            "name": "anpr2mqtt",
            "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "url": "https://anpt2mqtt.rhizomatics.org.uk",
        },
        "device_class": None,
        "unique_id": f"anpr_{camera}",
        "image_topic": image_topic,
        "json_attributes_topic": state_topic,
        "icon": "mdi:car-back",
        "name": f"ANPR {camera} Snapshot",
        "dev": {
            "name": f"anpr2mqtt on {camera}",
            "sw_version": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "manufacturer": "rhizomatics",
            "identifiers": [f"{camera}.anpr2mqtt"],
        },
    }
    client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
    log.info("Published HA MQTT Discovery message to %s", topic)


def post_state_message(
    client: mqtt.Client,
    topic: str,
    plate: str | None,
    image_info: ImageInfo | None = None,
    direction: str | None = None,
    camera: str | None = None,
    classification: dict[str, Any] | None = None,
    previous_sightings: int | None = None,
    last_sighting: dt.datetime | None = None,
    url: str | None = None,
    error: str | None = None,
    file_path: Path | None = None,
    reg_info: Any = None,
) -> None:
    payload: dict[str, Any] = {"plate": "", "vehicle_direction": direction or "Unknown", "reg_info": reg_info}

    if error:
        payload["error"] = error
    payload["camera"] = camera or "UNKNOWN"
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
                    "plate": plate,
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
