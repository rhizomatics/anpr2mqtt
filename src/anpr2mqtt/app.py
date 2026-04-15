import logging
import sys
from typing import Any, cast

import paho.mqtt.client as mqtt
import structlog
from paho.mqtt.enums import CallbackAPIVersion, MQTTErrorCode, MQTTProtocolVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from pydantic import ValidationError
from pydantic_settings import CliApp
from watchdog.observers import Observer

import anpr2mqtt
from anpr2mqtt.event_handler import EventHandler
from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import CameraSettings, Settings
from anpr2mqtt.tracker import Tracker, compute_time_analysis

log = structlog.get_logger()
# run like docker run --restart always -d -v /ftp:/ftp d4d8dea7d1e3


def on_connect(
    _client: mqtt.Client,
    _userdata: Any,
    _flags: mqtt.ConnectFlags,
    rc: ReasonCode,
    _props: Properties | None = None,
) -> None:
    log.debug("on_connect, MQTT result code " + str(rc))
    if cast("str", rc.getName()) == "Not authorized":
        log.error("Invalid MQTT credentials", result_code=rc)
        return
    if rc != 0:
        log.warning("Connection failed to broker", result_code=rc)
    else:
        log.debug("Connected to broker", result_code=rc)


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
    settings: Settings = Settings()  # type: ignore[call-arg]
    if settings.log_level != "INFO":
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, str(settings.log_level))))
    log.info("ANPR2MQTT %s starting up", anpr2mqtt.version)  # pyright: ignore[reportAttributeAccessIssue]
    for target_type in settings.targets:
        log.info(
            "ANPR2MQTT %s known vehicles, %s alert vehicles, %s corrections, %s ignore patterns",
            len(settings.targets[target_type].known),
            len(settings.targets[target_type].dangerous),
            len(settings.targets[target_type].correction),
            len(settings.targets[target_type].ignore),
        )

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

    try:
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            clean_session=True if protocol != MQTTProtocolVersion.MQTTv5 else None,
            client_id="anpr2mqtt",
            protocol=protocol,
        )
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.username_pw_set(username=settings.mqtt.user, password=settings.mqtt.password)
        rc: MQTTErrorCode = client.connect(host=settings.mqtt.host, port=int(settings.mqtt.port), keepalive=60)
        log.info("Client connection requested", result_code=rc)
        client.loop_start()
        log.info(f"Connected to MQTT at {settings.mqtt.host}:{settings.mqtt.port} as {settings.mqtt.user}")
        log.info(f"Publishing at {settings.mqtt.topic_root}")
        publisher = HomeAssistantPublisher(client, settings.homeassistant)

    except Exception as e:
        log.error("Failed to connect to MQTT: %s", e, exc_info=1)
        sys.exit(-500)

    try:
        observer = Observer()
    except Exception as e:
        log.error("Failed to setup file system watchdog: %s", e)
        sys.exit(-400)

    for event_config in settings.events:
        camera: CameraSettings | None = None
        try:
            for camera_config in settings.cameras:
                if camera_config.name == event_config.camera:
                    camera = camera_config
            if camera is None:
                camera = CameraSettings(name=event_config.camera)
            state_topic = f"{settings.mqtt.topic_root}/{event_config.event}/{camera.name}/state"
            image_topic = f"{settings.mqtt.topic_root}/{event_config.event}/{camera.name}/image"
            tracker = Tracker(
                event_config.target_type,
                tracker_config=settings.tracker,
                target_config=settings.targets.get(event_config.target_type),
            )
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
            )  # ty:ignore[invalid-argument-type]
            log.debug("Scheduling watchdog for %s", event_config.watch_path)
            observer.schedule(event_handler, str(event_config.watch_path), recursive=event_config.watch_tree)  # ty:ignore[invalid-argument-type]
            publisher.publish_sensor_discovery(state_topic=state_topic, event_config=event_config, camera=camera)
            if settings.homeassistant.image_entity:
                publisher.publish_image_discovery(
                    state_topic=state_topic, image_topic=image_topic, event_config=event_config, camera=camera
                )
            if settings.homeassistant.camera_entity:
                publisher.publish_camera_discovery(
                    state_topic=state_topic, image_topic=image_topic, event_config=event_config, camera=camera
                )
            # selectively publish known targets as HA sensors, using last seen timestamp as state value
            for entity_id, targets in tracker.entities.items():
                target_topic: str = f"{settings.mqtt.topic_root}/{event_config.event}/{entity_id}/state"
                publisher.publish_target_sensor_discovery(
                    entity_id=entity_id, target_type=event_config.target_type, targets=targets, state_topic=target_topic
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
            log.error(
                "Failed to schedule event %s %s watchdog: %s",
                event_config.event,
                camera.name if camera else "unknown camera",
                e,
            )

    publisher.start()
    observer.start()

    try:
        log.info("Starting observer loop")
        while observer.is_alive():
            observer.join(1)
    except Exception as e:
        log.error("Failed in run observer loop: %s", e, exc_info=1)
    finally:
        observer.stop()
        observer.join()
        log.info("loop observer ended")


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
        log.error("Use the tools CLI for testing out directory watch, image analysis and APIs")
