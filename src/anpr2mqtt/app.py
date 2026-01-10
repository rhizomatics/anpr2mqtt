import logging
import sys
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from paho.mqtt.enums import CallbackAPIVersion, MQTTErrorCode
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from watchdog.observers import Observer

from anpr2mqtt.event_handler import EventHandler
from anpr2mqtt.hass import post_discovery_message
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


def run() -> None:
    """Watch a directory, post any matching files to MQTT after optionally analyzing the image"""
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
    settings: Settings = Settings()  # type: ignore[call-arg]
    if settings.log_level != "INFO":
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, str(settings.log_level))))
    log.info("ANPR2MQTT Starting up")
    log.info(
        "ANPR2MQRR %s known vehicles, %s alert vehicles, %s corrections, %s ignore patterns",
        len(settings.plates.known),
        len(settings.plates.dangerous),
        len(settings.plates.correction),
        len(settings.plates.ignore),
    )

    state_topic = f"{settings.mqtt.topic_root}/{settings.camera}/state"
    image_topic = f"{settings.mqtt.topic_root}/{settings.camera}/image"
    client: mqtt.Client
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
        log.info(f"Publishing at {settings.mqtt.topic_root}/{settings.camera}")
        post_discovery_message(client, settings.homeassistant.discovery_topic_root, state_topic, image_topic, settings.camera)
    except Exception as e:
        log.error("Failed to connect to MQTT: %s", e, exc_info=1)
        sys.exit(-500)

    try:
        event_handler = EventHandler(
            client=client,
            camera=settings.camera,
            state_topic=state_topic,
            image_topic=image_topic,
            file_system_config=settings.file_system,
            plate_config=settings.plates,
            ocr_config=settings.ocr,
            image_config=settings.image,
            dvla_config=settings.dvla,
            tracker_config=settings.tracker,
        )  # ty:ignore[invalid-argument-type]
        observer = Observer()
        log.debug("Scheduling watchdog for %s", settings.file_system.watch_path)
        observer.schedule(event_handler, str(settings.file_system.watch_path), recursive=False)  # ty:ignore[invalid-argument-type]
    except Exception as e:
        log.error("Failed to setup file system watchdog: %s", e)
        sys.exit(-400)

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
        run()
