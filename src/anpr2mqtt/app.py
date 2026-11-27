import logging
import sys
import threading
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from paho.mqtt.enums import CallbackAPIVersion, MQTTErrorCode, MQTTProtocolVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from pydantic import ValidationError
from pydantic_settings import CliApp
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

import anpr2mqtt
from anpr2mqtt.event_handler import EventHandler, verify_ocr
from anpr2mqtt.frigate_handler import CameraConfig, FrigateHandler
from anpr2mqtt.handler_common import SUBSCRIPTIONS
from anpr2mqtt.hass import (
    AVAILABILITY_OFFLINE,
    OFFLINE_PUBLISH_TIMEOUT,
    HomeAssistantPublisher,
    availability_topic,
    publish_availability,
    secondary_image_topic,
)
from anpr2mqtt.heartbeat import Heartbeat
from anpr2mqtt.image_stats import ImageStats, local_now
from anpr2mqtt.settings import (
    DEFAULT_CAMERA,
    LINK_FRIGATE,
    TARGET_TYPE_PLATE,
    CameraSettings,
    EventSettings,
    Settings,
    linked_cameras,
    setting_source,
)
from anpr2mqtt.tracker import Tracker, compute_time_analysis
from anpr2mqtt.upload_handler import UploadHandler

log = structlog.get_logger()
# v3.1.1 CONNACK 4/5 and v5 reason codes 134/135; paho also reports v5 refusals as a "Protocol error" disconnect
CREDENTIAL_FAILURES: tuple[str, ...] = ("Not authorized", "Bad user name or password")
# run like docker run --restart always -d -v /ftp:/ftp d4d8dea7d1e3


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    _flags: mqtt.ConnectFlags,
    rc: ReasonCode,
    _props: Properties | None = None,
) -> None:
    log.debug("on_connect, MQTT result code " + str(rc))
    if rc.getName() in CREDENTIAL_FAILURES:
        log.error("Invalid MQTT credentials", result_code=rc)
        return
    if rc != 0:
        log.warning("Connection failed to broker", result_code=rc)
    else:
        log.debug("Connected to broker", result_code=rc)
        if isinstance(userdata, dict) and userdata.get("availability_topic"):
            # on every (re)connect, since the will may have marked us offline while disconnected
            publish_availability(client, userdata["availability_topic"], online=True)
        if isinstance(userdata, dict):
            # clean session, so the broker has dropped any subscriptions from a previous connection
            for topic in list(userdata.get(SUBSCRIPTIONS, [])):
                log.debug("(Re)subscribing", topic=topic)
                client.subscribe(topic)


def on_disconnect(
    _client: mqtt.Client,
    _userdata: Any,
    _disconnect_flags: mqtt.DisconnectFlags,
    rc: ReasonCode,
    _props: Properties | None,
) -> None:
    if rc == 0:
        log.debug("Disconnected from broker", result_code=rc)
    else:
        log.warning("Disconnect failure from broker", result_code=rc)


def main_loop() -> None:
    """Watch a directory, post any matching files to MQTT after optionally analyzing the image"""
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
    settings: Settings = Settings()
    if settings.log_level != "INFO":
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, str(settings.log_level))))
    log.info("ANPR2MQTT %s starting up", anpr2mqtt.version)  # pyright: ignore[reportAttributeAccessIssue]
    for target_type in settings.targets:
        log.info(
            "ANPR2MQTT %s target groups, %s corrections, %s ignore patterns",
            len(settings.targets[target_type].groups),
            len(settings.targets[target_type].correction),
            len(settings.targets[target_type].ignore),
        )
    if settings.ocr.verify_on_startup and any(event.ocr_field_ids for event in settings.events):
        verify_ocr()

    client: mqtt.Client
    publisher: HomeAssistantPublisher
    protocol: MQTTProtocolVersion
    if settings.mqtt.protocol in ("3", "3.11"):
        protocol = MQTTProtocolVersion.MQTTv311
    elif settings.mqtt.protocol == "3.1":
        protocol = MQTTProtocolVersion.MQTTv31
    elif settings.mqtt.protocol in ("5", "5.0"):
        protocol = MQTTProtocolVersion.MQTTv5
    else:
        log.info("No valid MQTT protocol version found (%s), setting to default v3.11", settings.mqtt.protocol)
        protocol = MQTTProtocolVersion.MQTTv311
    log.debug("MQTT protocol set to %r", protocol)

    avail_topic: str = availability_topic(settings.mqtt.topic_root)
    try:
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            clean_session=True if protocol != MQTTProtocolVersion.MQTTv5 else None,
            client_id=settings.mqtt.client_id,
            protocol=protocol,
            userdata={"availability_topic": avail_topic, SUBSCRIPTIONS: []},
        )
        # broker publishes this if the connection drops without a clean disconnect, e.g. a crash or kill
        client.will_set(avail_topic, payload=AVAILABILITY_OFFLINE, qos=1, retain=True)
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.username_pw_set(username=settings.mqtt.user, password=settings.mqtt.password)
        log.info("MQTT password taken from %s", setting_source(Settings, "mqtt", "pass") or "unknown source")
        rc: MQTTErrorCode = client.connect(host=settings.mqtt.host, port=int(settings.mqtt.port), keepalive=60)
        log.info("Client connection requested", result_code=rc)
        client.loop_start()
        log.info(f"Connected to MQTT at {settings.mqtt.host}:{settings.mqtt.port} as {settings.mqtt.user}")
        log.info(f"Publishing at {settings.mqtt.topic_root}")
        publisher = HomeAssistantPublisher(
            client,
            settings.homeassistant,
            availability_topic=avail_topic,
            image_stats=ImageStats(settings.tracker.data_dir / "image_stats.json"),
        )

    except Exception as e:
        log.error("Failed to connect to MQTT: %s", e, exc_info=1)
        sys.exit(-500)

    try:
        observer = Observer()
    except Exception as e:
        log.error("Failed to setup file system watchdog: %s", e)
        sys.exit(-400)

    # Maps camera name → (event_config, camera_settings, tracker, state_topic, image_topic)
    # Used by FrigateHandler to share the same pipeline as filesystem events.
    frigate_camera_configs: dict[str, CameraConfig] = {}

    events_failed: int = 0
    upload_handlers: list[UploadHandler] = []
    for event_config in settings.events:
        camera: CameraSettings | None = None
        try:
            if event_config.is_upload:
                upload_handlers.append(start_upload(publisher, observer, settings.mqtt.topic_root, event_config))
                continue
            camera_name: str = event_config.camera or DEFAULT_CAMERA
            for camera_config in settings.cameras:
                if camera_config.name == camera_name:
                    camera = camera_config
            if camera is None:
                camera = CameraSettings(name=camera_name)
            # resolved once, so Home Assistant is told the same Frigate camera that events are routed by
            camera = camera.model_copy(update={"linked_cameras": linked_cameras(camera, settings.frigate)})
            state_topic = f"{settings.mqtt.topic_root}/{event_config.event}/cameras/{camera.name}/state"
            image_topic = f"{settings.mqtt.topic_root}/{event_config.event}/cameras/{camera.name}/image"
            # plates are sensors, anything else is an event entity, fired by its own topic
            event_topic: str | None = (
                None
                if event_config.is_plate
                else f"{settings.mqtt.topic_root}/{event_config.event}/cameras/{camera.name}/event"
            )
            second_image_topic: str | None = (
                secondary_image_topic(image_topic, event_config.secondary_image_event)
                if event_config.secondary_image_event and settings.homeassistant.image_entity
                else None
            )
            tracker = Tracker(
                event_config.target_type,
                tracker_config=settings.tracker,
                target_config=settings.targets.get(event_config.target_type),
                region=event_config.region,
                auto_match_tolerance=event_config.auto_match_tolerance,
            )
            # keyed by the Frigate camera, so a differently named one is published as this camera
            frigate_key = camera.linked_cameras.get(LINK_FRIGATE, camera.name)
            # only plate events, so a face event on the same camera doesn't take Frigate's licence plates
            if event_config.target_type == TARGET_TYPE_PLATE and frigate_key not in frigate_camera_configs:
                frigate_camera_configs[frigate_key] = (event_config, camera, tracker, state_topic, image_topic)
            event_handler = EventHandler(
                publisher=publisher,
                event_config=event_config,
                state_topic=state_topic,
                camera=camera,
                image_topic=image_topic,
                ocr_config=settings.ocr,
                image_config=settings.image,
                dvla_config=settings.dvla,
                tracker=tracker,
                mqtt_topic_root=settings.mqtt.topic_root,
                secondary_image_topic=second_image_topic,
                event_topic=event_topic,
            )
            log.debug("Scheduling watchdog for %s", event_config.watch_path)
            observer.schedule(event_handler, str(event_config.watch_path), recursive=event_config.watch_tree)
            if event_topic:
                publisher.publish_event_discovery(
                    event_topic=event_topic, state_topic=state_topic, event_config=event_config, camera=camera
                )
                publisher.remove_sensor_discovery(event_config)
            else:
                publisher.publish_sensor_discovery(state_topic=state_topic, event_config=event_config, camera=camera)
            if settings.homeassistant.image_entity:
                publisher.publish_image_discovery(
                    state_topic=state_topic, image_topic=image_topic, event_config=event_config, camera=camera
                )
            if second_image_topic:
                publisher.publish_image_discovery(
                    state_topic=state_topic,
                    image_topic=second_image_topic,
                    event_config=event_config,
                    camera=camera,
                    image_event=event_config.secondary_image_event,
                )
            if settings.homeassistant.camera_entity:
                publisher.publish_camera_discovery(
                    state_topic=state_topic, image_topic=image_topic, event_config=event_config, camera=camera
                )
            # selectively publish known targets as HA sensors, using last seen timestamp as state value
            for entity_id, targets in tracker.entities.items():
                target_topic: str = f"{settings.mqtt.topic_root}/{event_config.event}/targets/{entity_id}/state"
                log.info("Publishing sensor.%s for %s targets", entity_id, len(targets))
                icon: str | None = targets[0].icon if len(targets) > 1 and targets[0].icon else event_config.icon
                publisher.publish_target_sensor_discovery(
                    entity_id=entity_id,
                    target_type=event_config.target_type,
                    icon=icon,
                    targets=targets,
                    state_topic=target_topic,
                )

                previous_sightings: list[str] = []
                for target in targets:
                    previous_sightings.extend(tracker.history(target.id, target.target_type))
                if previous_sightings:
                    time_analysis: dict[str, Any] = compute_time_analysis(sorted(previous_sightings))
                else:
                    time_analysis = {"last_seen": None}
                publisher.publish_target_state(
                    state_topic=target_topic,
                    time_analysis=time_analysis,
                )

            # post initial empty state message
            publisher.post_state_message(state_topic, sighting=None, event_config=event_config, camera=camera)
            log.info("Publishing %s %s state to %s", event_config.event, camera.name, state_topic)
        except Exception as e:
            events_failed += 1
            log.error(
                "Failed to schedule event %s %s watchdog: %s",
                event_config.event,
                camera.name if camera else "unknown camera",
                e,
            )

    publisher.start()
    observer.start()
    if events_failed:
        log.warning("Not removing stale Home Assistant entities, since %s events failed to start", events_failed)
    else:
        # off the main thread, since it waits for the broker to send back retained discovery
        threading.Thread(target=publisher.sweep_stale_discovery, name="hass-sweep", daemon=True).start()

    if settings.frigate.enabled:
        event_settings: EventSettings | None = None
        for cfg in settings.events:
            if cfg.target_type == "plate":
                event_settings = cfg
                break
        event_settings = event_settings or EventSettings(target_type="plate")

        default_tracker = Tracker(
            target_type="plate",
            tracker_config=settings.tracker,
            target_config=settings.targets.get("plate"),
            region=event_settings.region,
            auto_match_tolerance=event_settings.auto_match_tolerance,
        )
        frigate_handler = FrigateHandler(
            mqtt_client=client,
            frigate_settings=settings.frigate,
            publisher=publisher,
            image_settings=settings.image,
            dvla_settings=settings.dvla,
            camera_configs=frigate_camera_configs,
            mqtt_topic_root=settings.mqtt.topic_root,
            default_tracker=default_tracker,
        )
        frigate_handler.start()
    else:
        log.info("Frigate listener disabled")

    heartbeat = Heartbeat()
    try:
        log.info("Starting observer loop")
        today = local_now().date()
        while observer.is_alive():
            # only while connected, so the healthcheck also fails if the broker connection is lost
            if client.is_connected():
                heartbeat.beat()
            if local_now().date() != today:
                # so today's and this week's image counts go back to 0, even for a camera with no images since
                today = local_now().date()
                publisher.refresh_image_stats()
                # off the main loop, so a large landing zone's scan doesn't hold up the heartbeat
                threading.Thread(target=rescan_uploads, args=(upload_handlers,), name="upload-rescan", daemon=True).start()
            observer.join(1)
    except Exception as e:
        log.error("Failed in run observer loop: %s", e, exc_info=1)
    finally:
        heartbeat.clear()
        observer.stop()
        observer.join()
        log.info("loop observer ended")
        shutdown_mqtt(client, avail_topic)


def start_upload(
    publisher: HomeAssistantPublisher,
    observer: BaseObserver,
    topic_root: str,
    event_config: EventSettings,
) -> UploadHandler:
    """Only counted, as a sensor of the last upload, with no camera, image or event entities, tracking or OCR"""
    state_topic: str = f"{topic_root}/uploads/{event_config.upload_name}/state"
    upload_handler = UploadHandler(publisher=publisher, state_topic=state_topic, event_config=event_config)
    log.debug("Scheduling upload watchdog for %s", upload_handler.watch_root)
    observer.schedule(upload_handler, str(upload_handler.watch_root), recursive=event_config.watch_tree)
    publisher.publish_upload_discovery(state_topic=state_topic, event_config=event_config)
    # before the observer starts, so no file events are lost to the scan replacing what they found
    upload_handler.scan()
    upload_handler.publish_state()
    log.info("Counting uploads to %s as %s, at %s", event_config.watch_path, event_config.upload_name, state_topic)
    return upload_handler


def rescan_uploads(upload_handlers: list[UploadHandler]) -> None:
    """Correct the current files for anything file events missed, and today's counts going back to 0"""
    for upload_handler in upload_handlers:
        try:
            upload_handler.scan()
            upload_handler.publish_state()
        except Exception as e:
            log.error("Failed to rescan uploads at %s: %s", upload_handler.watch_root, e, exc_info=1)


def shutdown_mqtt(client: mqtt.Client, avail_topic: str) -> None:
    """Mark entities unavailable then disconnect, since a clean disconnect doesn't trigger the will"""
    try:
        if client.is_connected():
            publish_availability(client, avail_topic, online=False).wait_for_publish(timeout=OFFLINE_PUBLISH_TIMEOUT)
    except Exception as e:
        log.warning("Unable to confirm offline availability published: %s", e)
    client.disconnect()
    client.loop_stop()


class Anpr2MQTT(Settings):
    def cli_cmd(self) -> None:
        main_loop()


def run() -> None:
    try:
        CliApp.run(model_cls=Anpr2MQTT)
    except ValidationError as e:
        log.error(e)
        log.error("Unable to startup, validation error on settings, check configuration file, arguments or env vars")
        log.error("MQTT host, account and password are mandatory (if using env vars, be sure to use MQTT__HOST not MQTT_HOST)")
        log.error("Use --help for a full set of config")
        log.error("Use the anprtools CLI for testing out directory watch, image analysis and APIs")
