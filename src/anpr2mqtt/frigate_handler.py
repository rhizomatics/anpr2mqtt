import datetime as dt
import json
import threading
from io import BytesIO
from typing import Any, cast

import niquests
import paho.mqtt.client as mqtt
import structlog
from PIL import Image

from anpr2mqtt.api_client import APIClient, DVLAClient
from anpr2mqtt.const import ImageInfo
from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import (
    TARGET_TYPE_PLATE,
    CameraSettings,
    DVLASettings,
    EventSettings,
    FrigateSettings,
    ImageSettings,
)
from anpr2mqtt.tracker import Sighting, Tracker

log = structlog.get_logger()

# dict value: (event_config, camera_settings, tracker, state_topic, image_topic)
CameraConfig = tuple[EventSettings, CameraSettings, Tracker, str, str]


class FrigateHandler:
    def __init__(
        self,
        mqtt_client: mqtt.Client,
        frigate_settings: FrigateSettings,
        publisher: HomeAssistantPublisher,
        image_settings: ImageSettings,
        dvla_settings: DVLASettings,
        camera_configs: dict[str, CameraConfig],
        mqtt_topic_root: str = "anpr2mqtt",
        default_tracker: Tracker | None = None,
    ) -> None:
        self.mqtt_client = mqtt_client
        self.frigate_settings = frigate_settings
        self.publisher = publisher
        self.image_settings = image_settings
        self.camera_configs = camera_configs
        self.mqtt_topic_root = mqtt_topic_root
        self.default_tracker = default_tracker

        # Latest JPEG snapshot bytes per camera, from MQTT retained messages
        self._snapshot_cache: dict[str, bytes] = {}
        self._snapshot_lock = threading.Lock()

        # Track processed event IDs to avoid duplicate publications
        self._processed_events: set[str] = set()
        self._processed_lock = threading.Lock()

        # Per-camera autoclear timers
        self._autoclear_timers: dict[str, threading.Timer] = {}
        self._autoclear_lock = threading.Lock()

        self.api_client: APIClient | None = None
        if dvla_settings.api_key:
            self.api_client = DVLAClient(
                dvla_settings.api_key,
                cache_type=dvla_settings.cache_type,
                cache_ttl=dvla_settings.cache_ttl,
                cache_dir=dvla_settings.cache_dir,
                verify_plate=dvla_settings.verify_plate,
            )

    def start(self) -> None:
        self.mqtt_client.message_callback_add(self.frigate_settings.topic, self._on_event_message)
        self.mqtt_client.message_callback_add("frigate/+/snapshot", self._on_snapshot_message)
        self.mqtt_client.subscribe(self.frigate_settings.topic)
        self.mqtt_client.subscribe("frigate/+/snapshot")
        log.info(
            "Frigate listener started, min_score=%.2f topic=%s",
            self.frigate_settings.min_score,
            self.frigate_settings.topic,
        )

    def _on_snapshot_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) >= 3 and msg.payload:
            camera = parts[1]
            with self._snapshot_lock:
                self._snapshot_cache[camera] = bytes(msg.payload)
            log.debug("Cached Frigate snapshot for camera %s (%d bytes)", camera, len(msg.payload))

    def _on_event_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            self._process_event(msg.payload)
        except Exception as e:
            log.error("Frigate event processing error: %s", e, exc_info=True)

    def _process_event(self, raw: bytes) -> None:
        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("Frigate event JSON parse error: %s", e)
            return

        event_type: str = payload.get("type", "")
        event_id: str = payload.get("event_id", "")
        camera: str = payload.get("camera", "")

        # Only process end events — they carry the most complete plate data
        if event_type != "end":
            return

        if self.frigate_settings.cameras and camera not in self.frigate_settings.cameras:
            return

        with self._processed_lock:
            if event_id in self._processed_events:
                return
            self._processed_events.add(event_id)
            # Bound memory usage
            if len(self._processed_events) > 5000:
                self._processed_events = set(list(self._processed_events)[2500:])

        after_data: dict[str, str | int | float | bool] = payload.get("after", {}) or {}
        plate: str | None = cast("str|None", after_data.get("recognized_license_plate"))
        score: float | None = float(after_data.get("recognized_license_plate_score", 0.0))
        if not plate:
            if after_data.get("label") == "car":
                log.info("Frigate event %s for %s has no recognized plate", event_id, after_data.get("label"))
            else:
                log.debug("Frigate event %s has no recognized plate", event_id)
            return

        if score is None:
            log.info("Frigate event %s has plate %s with no score, skipping", event_id, plate)
        elif score < self.frigate_settings.min_score:
            log.info(
                "Frigate event %s has plate %s score %.3f below threshold %.3f, skipping",
                event_id,
                plate,
                score,
                self.frigate_settings.min_score,
            )
            return

        log.info("Frigate event %s: plate=%s score=%.3f camera=%s", event_id, plate, score, camera)

        image: Image.Image | None = self._get_event_image(event_id, camera)
        event_config, camera_settings, tracker, state_topic, image_topic = self._resolve_camera_config(camera)

        start_time: float = float(payload.get("start_time") or 0)
        timestamp = dt.datetime.fromtimestamp(start_time, tz=dt.UTC) if start_time else dt.datetime.now(dt.UTC)

        image_size = 0
        if image:
            buf = BytesIO()
            image.save(buf, "JPEG")
            image_size = buf.tell()

        image_info = ImageInfo(target=plate, event="frigate_event", timestamp=timestamp, ext="jpg", size=image_size)

        sighting: Sighting = tracker.find(plate)

        reg_info: dict[str, Any] | None = None
        if sighting.target.lookup and self.api_client and event_config.target_type == TARGET_TYPE_PLATE:
            api_info: dict[str, Any] = self.api_client.lookup(sighting.target.id)
            if api_info.get("success"):
                reg_info = api_info.get("plate")
                if sighting.target.description is None and api_info.get("description"):
                    sighting.target.description = api_info["description"]

        time_analysis: dict[str, Any] = tracker.record(sighting.target.id, event_config.target_type, timestamp)
        extra_info: dict[str, dict[str, Any]] = {"frigate": {}}
        for attr in (
            "recognized_license_plate_score",
            "velocity_angle",
            "current_estimated_speed",
            "average_estimated_speed",
            "label",
            "sub_label",
            "",
        ):
            if after_data.get(attr):
                extra_info["frigate"][attr] = after_data.get(attr)

        if sighting.target.entity_id:
            target_state_topic = f"{self.mqtt_topic_root}/{event_config.event}/targets/{sighting.target.entity_id}/state"
            self.publisher.publish_target_state(
                state_topic=target_state_topic,
                description=sighting.target.description,
                time_analysis=time_analysis,
            )

        if sighting.ignore:
            log.info("Skipping MQTT for ignored plate %s", sighting.target.id)
            return

        frigate_ui_url: str | None = None
        if self.frigate_settings.url:
            frigate_ui_url = f"{self.frigate_settings.url}/events?id={event_id}"

        self.publisher.post_state_message(
            state_topic,
            sighting=sighting,
            event_config=event_config,
            camera=camera_settings,
            image_info=image_info,
            time_analysis=time_analysis,
            reg_info=reg_info,
            extra_info=extra_info,
            source="frigate",
            frigate_event_id=event_id,
            frigate_ui_url=frigate_ui_url,
        )

        if image:
            self.publisher.post_image_message(image_topic, image, "JPEG")

        self._schedule_autoclear(camera, event_config, state_topic, image_topic)

    def _get_event_image(self, event_id: str, camera: str) -> Image.Image | None:
        # Prefer the retained MQTT snapshot for this camera (has bounding boxes)
        with self._snapshot_lock:
            snapshot_bytes = self._snapshot_cache.get(camera)

        if snapshot_bytes:
            try:
                img = Image.open(BytesIO(snapshot_bytes))
                img.load()
                log.debug("Using MQTT snapshot for event %s camera %s", event_id, camera)
                return img
            except Exception as e:
                log.warning("Failed to decode MQTT snapshot for camera %s: %s", camera, e)

        # Fall back to Frigate HTTP API snapshot (also includes bounding boxes)
        if self.frigate_settings.url:
            return self._fetch_api_snapshot(event_id)

        log.warning("No image for Frigate event %s (no MQTT snapshot cached, no url configured)", event_id)
        return None

    def _fetch_api_snapshot(self, event_id: str) -> Image.Image | None:
        url = f"{self.frigate_settings.url}/api/events/{event_id}/snapshot.jpg"
        try:
            resp = niquests.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                img = Image.open(BytesIO(resp.content))
                img.load()
                log.info("Fetched API snapshot for event %s (%d bytes)", event_id, len(resp.content))
                return img
            log.warning("API snapshot for event %s returned HTTP %s", event_id, resp.status_code)
        except Exception as e:
            log.warning("Failed to fetch API snapshot for event %s: %s", event_id, e)
        return None

    def _resolve_camera_config(self, camera: str) -> CameraConfig:
        if camera in self.camera_configs:
            return self.camera_configs[camera]

        # No matching event config — synthesise defaults using shared tracker if available
        log.warning("No event config found for Frigate camera %s, using defaults", camera)
        event_config = EventSettings(camera=camera, event="anpr", target_type=TARGET_TYPE_PLATE)
        camera_settings = CameraSettings(name=camera)
        from anpr2mqtt.settings import TrackerSettings

        tracker = self.default_tracker or Tracker(
            target_type=TARGET_TYPE_PLATE,
            tracker_config=TrackerSettings(),
            target_config=None,
            auto_match_tolerance=1,
        )
        state_topic = f"{self.mqtt_topic_root}/{event_config.event}/cameras/{camera}/state"
        image_topic = f"{self.mqtt_topic_root}/{event_config.event}/cameras/{camera}/image"
        return event_config, camera_settings, tracker, state_topic, image_topic

    def _schedule_autoclear(self, camera: str, event_config: EventSettings, state_topic: str, image_topic: str) -> None:
        autoclear = event_config.autoclear
        if not autoclear.enabled:
            return
        with self._autoclear_lock:
            existing = self._autoclear_timers.get(camera)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(
                autoclear.post_event, self._do_autoclear, args=(camera, event_config, state_topic, image_topic)
            )
            timer.daemon = True
            timer.start()
            self._autoclear_timers[camera] = timer
        log.debug("Frigate autoclear scheduled in %ss for camera %s", autoclear.post_event, camera)

    def _do_autoclear(self, camera: str, event_config: EventSettings, state_topic: str, image_topic: str) -> None:
        log.info("Frigate autoclear firing for camera %s", camera)
        autoclear = event_config.autoclear
        # We don't have a full camera_settings here — reconstruct it
        _, camera_settings, _, _, _ = self._resolve_camera_config(camera)
        if autoclear.state:
            self.publisher.post_state_message(state_topic, sighting=None, event_config=event_config, camera=camera_settings)
        if autoclear.image:
            self.publisher.post_image_message(image_topic, image=None)
