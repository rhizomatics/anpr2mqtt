import logging
import sys
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from paho.mqtt.enums import CallbackAPIVersion, MQTTErrorCode
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from pydantic_settings import CliApp
from watchdog.observers import Observer

import anpr2mqtt
from anpr2mqtt.event_handler import EventHandler
from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import Settings

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
    if rc.getName() == "Not authorized":
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
    try:
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            clean_session=True,
            client_id="anpr2mqtt",
        )
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.username_pw_set(username=settings.mqtt.user, password=settings.mqtt.password)
        rc: MQTTErrorCode = client.connect(host=settings.mqtt.host, port=int(settings.mqtt.port), keepalive=60)
        log.info("Client connection requested", result_code=rc)
        client.loop_start()
        log.info(f"Connected to MQTT at {settings.mqtt.host}:{settings.mqtt.port} as {settings.mqtt.user}")
        log.info(f"Publishing at {settings.mqtt.topic_root}")
        publisher = HomeAssistantPublisher(client, "homeassistant.status")

    except Exception as e:
        log.error("Failed to connect to MQTT: %s", e, exc_info=1)
        sys.exit(-500)

    try:
        observer = Observer()
    except Exception as e:
        log.error("Failed to setup file system watchdog: %s", e)
        sys.exit(-400)

    for event_config in settings.events:
        try:
            state_topic = f"{settings.mqtt.topic_root}/{event_config.event}/{event_config.camera}/state"
            image_topic = f"{settings.mqtt.topic_root}/{event_config.event}/{event_config.camera}/image"
            event_handler = EventHandler(
                publisher=publisher,
                event_config=event_config,
                state_topic=state_topic,
                image_topic=image_topic,
                target_config=settings.targets.get(event_config.target_type),
                ocr_config=settings.ocr,
                image_config=settings.image,
                dvla_config=settings.dvla,
                tracker_config=settings.tracker,
            )  # ty:ignore[invalid-argument-type]
            log.debug("Scheduling watchdog for %s", event_config.watch_path)
            observer.schedule(event_handler, str(event_config.watch_path), recursive=False)  # ty:ignore[invalid-argument-type]
            publisher.post_discovery_message(
                settings.homeassistant.discovery_topic_root,
                state_topic=state_topic,
                image_topic=image_topic,
                event_config=event_config,
                device_creation=settings.homeassistant.device_creation,
            )
            log.info("Publishing %s %s state to %s", event_config.event, event_config.camera, state_topic)
        except Exception as e:
            log.error("Failed to schedule event %s %s watchdog: %s", event_config.event, event_config.camera, e)

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
    CliApp.run(model_cls=Anpr2MQTT)
