import json
import random
import threading
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
from anpr2mqtt.image_stats import Counts, ImageStats, local_now
from anpr2mqtt.settings import CameraSettings, EventSettings, HomeAssistantSettings, Target
from anpr2mqtt.tracker import Sighting

from .const import ImageInfo
from .handler_common import subscribe

log = structlog.get_logger()

STALE_SWEEP_SECONDS: float = 5  # long enough for the broker to send back every retained discovery message
# discovery payload keys naming the topics an entity reads, cleared along with a stale entity
ENTITY_TOPIC_KEYS: tuple[str, ...] = ("state_topic", "json_attributes_topic", "image_topic", "topic")

AVAILABILITY_ONLINE = "online"  # Home Assistant default payload_available
AVAILABILITY_OFFLINE = "offline"  # Home Assistant default payload_not_available
OFFLINE_PUBLISH_TIMEOUT = 2.0
# on every device, so an integration building on anpr2mqtt can tell its devices for certain
DEVICE_MANUFACTURER = "Rhizomatics"
DEVICE_MODEL = "anpr2mqtt"


def availability_topic(topic_root: str) -> str:
    return f"{topic_root}/availability"


def secondary_image_topic(image_topic: str, secondary_image_event: str) -> str:
    """Image topic for a capture's second image, such as image/face_background alongside a face's image"""
    return f"{image_topic}/{secondary_image_event.lower()}"


def publish_availability(client: mqtt.Client, topic: str, online: bool) -> mqtt.MQTTMessageInfo:
    """Retained plain string payload, as expected by Home Assistant availability_topic"""
    payload: str = AVAILABILITY_ONLINE if online else AVAILABILITY_OFFLINE
    log.debug("Publishing availability %s to %s", payload, topic)
    return client.publish(topic, payload=payload, qos=1, retain=True)


class HomeAssistantPublisher:
    def __init__(
        self,
        client: mqtt.Client,
        cfg: HomeAssistantSettings,
        availability_topic: str | None = None,
        image_stats: ImageStats | None = None,
    ) -> None:
        self.client: mqtt.Client = client
        self.image_stats: ImageStats | None = image_stats
        # last state published to each topic, so image counts can be refreshed without a new sighting
        self._last_state: dict[str, tuple[dict[str, Any], EventSettings, CameraSettings]] = {}
        self._state_posts: dict[str, int] = {}
        self.availability_topic: str | None = availability_topic
        self.hass_status_topic: str = cfg.status_topic
        self.discovery_topic_prefix: str = cfg.discovery_topic_root
        self.device_creation: bool = cfg.device_creation
        self.remove_stale_entities: bool = cfg.remove_stale_entities
        self.republish: dict[str, dict[str, Any]] = {}
        self.hass_online: bool | None = None

    def start(self) -> None:
        log.info("Subscribing to Home Assistant birth and last will at %s", self.hass_status_topic)
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_unsubscribe = self.on_unsubscribe
        subscribe(self.client, self.hass_status_topic)

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
        """Callback for incoming MQTT messages"""  # ruff: ignore[non-imperative-mood]
        if msg.topic == self.hass_status_topic:
            decoded: str | None = msg.payload.decode("utf-8") if msg.payload else None
            if decoded == "offline":
                log.warn("Home Assistant gone offline")
                self.hass_online = False
            elif decoded == "online":
                if self.hass_online is False:
                    log.info("Home Assistant back online, republishing discoveries")
                    self.hass_online = True
                    # off the paho network thread, since the jittered sleeps would stall keepalives and Frigate events
                    threading.Thread(
                        target=self.republish_discovery, args=(f"{msg.topic}_{decoded}",), name="hass-republish", daemon=True
                    ).start()
                else:
                    log.info("Home Assistant online")
                    self.hass_online = True
            else:
                log.warn("Unknown Home Assistant status payload: %s", msg.payload)
        else:
            log.debug("Unknown message on %s", msg.topic)

    def sweep_stale_discovery(self, wait: float = STALE_SWEEP_SECONDS) -> list[str]:
        """Remove entities this instance published discovery for before, but not this time, such as removed events

        Only discovery naming this instance's availability topic is touched, so other anpr2mqtt instances on the same
        broker, and anything else's discovery, are left alone. Retained state topics of removed entities are cleared
        too, unless a current entity still reads them. Returns the discovery topics removed.
        """
        if not self.remove_stale_entities or not self.availability_topic:
            return []
        pattern: str = f"{self.discovery_topic_prefix}/#"
        found: dict[str, dict[str, Any]] = {}
        lock = threading.Lock()

        def on_discovery(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
            if not msg.retain or not msg.payload:
                return
            try:
                payload: Any = json.loads(msg.payload)
            except ValueError:
                return
            if isinstance(payload, dict) and payload.get("availability_topic") == self.availability_topic:
                with lock:
                    found[msg.topic] = payload

        self.client.message_callback_add(pattern, on_discovery)
        try:
            self.client.subscribe(pattern)
            time.sleep(wait)
            self.client.unsubscribe(pattern)
        finally:
            self.client.message_callback_remove(pattern)

        with lock:
            stale: dict[str, dict[str, Any]] = {t: p for t, p in found.items() if t not in self.republish}
        in_use: set[str] = {str(p[k]) for p in self.republish.values() for k in ENTITY_TOPIC_KEYS if p.get(k)}
        topic_root: str = self.availability_topic.rsplit("/", 1)[0] + "/"
        for topic, payload in stale.items():
            log.info("Removing stale Home Assistant entity %s, no longer configured", payload.get("unique_id", topic))
            self.client.publish(topic, payload="", qos=0, retain=True)
            for key in ENTITY_TOPIC_KEYS:
                entity_topic: Any = payload.get(key)
                if isinstance(entity_topic, str) and entity_topic.startswith(topic_root) and entity_topic not in in_use:
                    self.client.publish(entity_topic, payload="", qos=0, retain=True)
                    in_use.add(entity_topic)  # cleared once, even if several stale entities read it
        if not stale:
            log.debug("No stale Home Assistant entities found")
        return list(stale)

    def republish_discovery(self, source_event: str) -> None:
        for topic, payload in self.republish.items():
            log.debug("Republishing to %s for %s", topic, source_event)
            # add jitter to republish to reduce herd load on HA after restart
            time.sleep(random.randint(1, 10))  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            payload["trigger"] = source_event
            self.client.publish(topic, json.dumps(payload))

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
            "name": name,
        }
        if event_config.icon:
            payload["icon"] = event_config.icon
        if self.device_creation:
            self.add_device_info(payload, camera)
        self.add_availability(payload)
        topic: str = f"{self.discovery_topic_prefix}/sensor/{event_config.camera}/{event_config.event}/config"
        msg: str = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = payload
        log.info("Published HA MQTT sensor Discovery message to %s", topic)

    def publish_event_discovery(
        self, event_topic: str, state_topic: str, event_config: EventSettings, camera: CameraSettings
    ) -> None:
        """Event entity for anything other than plates, such as faces or scene changes

        Kept out of the sensor domain, so integrations that take an anpr2mqtt device's sensors for plates, such as
        Camera AutoNotify, aren't given other events they can't handle.
        """
        name: str = event_config.description or f"{event_config.event} {camera.name}"
        payload: dict[str, Any] = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "default_entity_id": f"event.{event_config.event}_{event_config.camera}",
            "unique_id": f"{event_config.event}_{event_config.camera}",
            "state_topic": event_topic,
            # the event's own details come with each event; only the image counts, refreshed between events, from state
            "json_attributes_topic": state_topic,
            "json_attributes_template": "{{ {'images': value_json.images | default(None)} | tojson }}",
            "event_types": [event_config.event],
            "name": name,
        }
        if event_config.icon:
            payload["icon"] = event_config.icon
        if self.device_creation:
            self.add_device_info(payload, camera)
        self.add_availability(payload)
        topic: str = f"{self.discovery_topic_prefix}/event/{event_config.camera}/{event_config.event}/config"
        self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
        self.republish[topic] = payload
        log.info("Published HA MQTT event Discovery message to %s", topic)

    def publish_upload_discovery(self, state_topic: str, event_config: EventSettings) -> None:
        """Sensor of the last file uploaded to a watch path, with its counts, for checking that uploads still arrive

        Free floating, with no device, since a landing zone may be shared by several cameras, or belong to none. That
        also keeps it from integrations that take an anpr2mqtt device's sensors as plates, such as Camera AutoNotify,
        so nothing is notified for each upload. Named by event and id, checked unique among uploads.
        """
        payload: dict[str, Any] = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "device_class": "timestamp",
            "value_template": "{{ value_json.last_received }}",
            "default_entity_id": f"sensor.{event_config.upload_name}",
            "unique_id": f"uploads_{event_config.upload_name}",
            "state_topic": state_topic,
            "json_attributes_topic": state_topic,
            "name": event_config.description or event_config.upload_name.replace("_", " ").capitalize(),
        }
        if event_config.icon:
            payload["icon"] = event_config.icon
        self.add_availability(payload)
        topic: str = f"{self.discovery_topic_prefix}/sensor/uploads/{event_config.upload_name}/config"
        self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
        self.republish[topic] = payload
        log.info("Published HA MQTT upload sensor Discovery message to %s", topic)

    def post_upload_state(
        self, topic: str, event_config: EventSettings, current_files: int = 0, current_bytes: int = 0
    ) -> None:
        """Publish the files now in the watch path and the latest counts, retained, after each change, and at midnight

        Received and removed counts are since counting started, so with files coming and going, the current files
        say what's actually there now.
        """
        received: Counts = Counts()
        removed: Counts = Counts()
        if self.image_stats:
            received = self.image_stats.counts(ImageStats.upload_key(event_config.upload_name))
            removed = self.image_stats.counts(ImageStats.removed_key(event_config.upload_name))
        now = local_now()
        payload: dict[str, Any] = {
            "event": event_config.event,
            "id": event_config.id,
            "watch_path": str(event_config.watch_path),
            # only for reference, as the camera this is the landing zone for
            **({"camera": event_config.camera} if event_config.camera else {}),
            "current": current_files,
            "current_bytes": current_bytes,
            **received.as_attributes(now),
            "last_received": received.last_received,
            "last_file": received.last_file,
            **removed.as_attributes(now, prefix="removed_"),
            "last_removed": removed.last_received,
            "last_removed_file": removed.last_file,
        }
        try:
            self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
            log.debug("Published HA MQTT upload state to %s: %s", topic, payload)
        except Exception as e:
            log.error("Failed to publish upload state to %s: %s", topic, e, exc_info=1)

    def remove_sensor_discovery(self, event_config: EventSettings) -> None:
        """Remove a sensor an earlier version made for an event that's now an event entity"""
        topic: str = f"{self.discovery_topic_prefix}/sensor/{event_config.camera}/{event_config.event}/config"
        self.client.publish(topic, payload="", qos=0, retain=True)
        log.debug("Removed any HA MQTT sensor Discovery message at %s", topic)

    def publish_image_discovery(
        self,
        state_topic: str,
        image_topic: str,
        event_config: EventSettings,
        camera: CameraSettings,
        image_event: str | None = None,
    ) -> None:
        """Image entity for an event, or with image_event, for a second image of the same capture"""
        name: str = event_config.description or f"{event_config.event} {event_config.camera}"
        object_id: str = f"{event_config.event}_{event_config.camera}"
        if image_event:
            name = f"{name} {image_event.lower().replace('_', ' ')}"
            object_id = f"{object_id}_{image_event.lower()}"
        payload = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            "device_class": None,
            "unique_id": object_id,
            "default_entity_id": f"image.{object_id}",
            "image_topic": image_topic,
            "json_attributes_topic": state_topic,
            "icon": event_config.icon,
            "name": name,
        }
        if self.device_creation:
            self.add_device_info(payload, camera)
        self.add_availability(payload)
        node: str = f"{event_config.event}_{image_event.lower()}" if image_event else event_config.event
        topic = f"{self.discovery_topic_prefix}/image/{event_config.camera}/{node}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = payload
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
            # plates keep their _anpr suffix, so existing entity ids don't change
            "default_entity_id": f"camera.{event_config.event}_{camera.name}" + ("_anpr" if event_config.is_plate else ""),
            "topic": image_topic,
            "json_attributes_topic": state_topic,
            "icon": event_config.icon,
            "name": name,
        }
        if self.device_creation:
            self.add_device_info(payload, camera)
        self.add_availability(payload)
        topic = f"{self.discovery_topic_prefix}/camera/{camera.name}/{event_config.event}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = payload
        log.info("Published HA MQTT Discovery message to %s", topic)

    def publish_target_sensor_discovery(
        self, entity_id: str, target_type: str, targets: list[Target], state_topic: str, icon: str | None
    ) -> None:
        payload: dict[str, Any] = {
            "o": {
                "name": "anpr2mqtt",
                "sw": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "url": "https://anpr2mqtt.rhizomatics.org.uk",
            },
            # keyed like the discovery topic, so it survives restarts and group membership changes
            "unique_id": f"{target_type}_{entity_id}",
            "default_entity_id": f"sensor.{entity_id}",
            "name": targets[0].description if len(targets) == 1 else entity_id,
            "state_topic": state_topic,
            "json_attributes_topic": state_topic,
            "value_template": "{{ value_json.last_seen }}",
            "device_class": "timestamp",
        }
        if icon:
            payload["icon"] = icon
        self.add_availability(payload)
        topic = f"{self.discovery_topic_prefix}/sensor/{entity_id}/config"
        msg = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        self.republish[topic] = payload
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

    def add_availability(self, payload: dict[str, Any]) -> None:
        if self.availability_topic:
            # payloads are the Home Assistant defaults, `online` and `offline`, so not repeated here
            payload["availability_topic"] = self.availability_topic

    def add_device_info(self, payload: dict[str, Any], camera: CameraSettings) -> None:
        # manufacturer and model together say for certain that a device is anpr2mqtt's, for integrations that build on it
        payload["dev"] = {
            "name": f"anpr2mqtt on {camera.name}",
            "sw_version": anpr2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
            "identifiers": [f"{camera.name}.anpr2mqtt"],
        }
        if camera.area:
            payload["dev"]["suggested_area"] = camera.area
        # Home Assistant rejects the whole discovery message for a configuration URL it can't use
        if camera.live_url and camera.live_url.startswith(("http://", "https://")):
            payload["dev"]["configuration_url"] = camera.live_url

    def post_state_message(
        self,
        topic: str,
        sighting: Sighting | None,
        event_config: EventSettings,
        camera: CameraSettings,
        extra_info: dict[str, Any] | None = None,
        image_info: ImageInfo | None = None,
        time_analysis: dict[str, Any] | None = None,
        url: str | None = None,
        error: str | None = None,
        file_path: Path | None = None,
        reg_info: Any = None,
        source: str | None = None,
        frigate_event_id: str | None = None,
        frigate_ui_url: str | None = None,
        event_topic: str | None = None,
    ) -> None:
        """State, retained for attributes, and with event_topic, an event entity's event, for each sighting"""
        payload: dict[str, Any] = sighting.as_dict() if sighting else {"target": None, "target_type": event_config.target_type}
        if payload.get("description") is None:
            payload["description"] = event_config.default_description
        payload.update(
            {
                event_config.target_type: sighting.target.id if sighting else None,
                "event": event_config.event,
                "camera": camera.name or "UNKNOWN",
                "area": camera.area,
                "live_url": camera.live_url,
                "linked_cameras": camera.linked_cameras,
                "reg_info": reg_info,
                "history": time_analysis,
            }
        )
        if extra_info:
            payload.update(extra_info)
        if error:
            payload["error"] = error
        if url is not None:
            payload["event_image_url"] = url
        if file_path is not None:
            payload["file_path"] = str(file_path)
        if source is not None:
            payload["source"] = source
        if frigate_event_id is not None:
            payload["frigate_event_id"] = frigate_event_id
        if frigate_ui_url is not None:
            payload["frigate_ui_url"] = frigate_ui_url

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
            self._last_state[topic] = (payload, event_config, camera)
            self._state_posts[topic] = self._state_posts.get(topic, 0) + 1
            self._publish_state(topic, payload, event_config, camera)
            if event_topic and image_info and not error:
                # not retained, or Home Assistant would fire the event again on restart
                event_msg: str = json.dumps({"event_type": event_config.event, **payload})
                self.client.publish(event_topic, payload=event_msg, qos=0, retain=False)
                log.debug("Published HA MQTT Event message to %s", event_topic)
        except Exception as e:
            log.error("Failed to publish event %s: %s", payload, e, exc_info=1)

    def _publish_state(self, topic: str, payload: dict[str, Any], event_config: EventSettings, camera: CameraSettings) -> None:
        if self.image_stats:
            payload["images"] = self.image_stats.attributes(ImageStats.event_key(event_config.event, camera.name))
        msg: str = json.dumps(payload)
        self.client.publish(topic, payload=msg, qos=0, retain=True)
        log.debug("Published HA MQTT State message to %s: %s", topic, payload)

    def record_image(self, event_config: EventSettings, camera: CameraSettings, size: int = 0) -> None:
        if self.image_stats:
            self.image_stats.record(ImageStats.event_key(event_config.event, camera.name), size=size)

    def record_upload(self, event_config: EventSettings, file_name: str, size: int = 0) -> None:
        if self.image_stats:
            self.image_stats.record(ImageStats.upload_key(event_config.upload_name), file_name=file_name, size=size)

    def record_removal(self, event_config: EventSettings, file_name: str, size: int = 0) -> None:
        if self.image_stats:
            self.image_stats.record(ImageStats.removed_key(event_config.upload_name), file_name=file_name, size=size)

    def state_posts(self, topic: str) -> int:
        """How many states have been published to a topic, to tell if handling an image published one"""
        return self._state_posts.get(topic, 0)

    def refresh_image_stats(self, topic: str | None = None) -> None:
        """Republish the last state, of one topic or all, with the latest image counts and nothing else changed

        Neither the state nor event_time change, so it isn't taken as a new sighting, and no event entity fires.
        """
        if not self.image_stats:
            return
        for state_topic, (payload, event_config, camera) in list(self._last_state.items()):
            if topic is None or state_topic == topic:
                try:
                    self._publish_state(state_topic, payload, event_config, camera)
                except Exception as e:
                    log.error("Failed to refresh image counts at %s: %s", state_topic, e)

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
