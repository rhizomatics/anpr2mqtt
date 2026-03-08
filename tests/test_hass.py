import datetime as dt
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import CameraSettings, EventSettings, HomeAssistantSettings


@pytest.fixture
def mock_client() -> Mock:
    return Mock()


@pytest.fixture
def publisher(mock_client: Mock) -> HomeAssistantPublisher:
    cfg = HomeAssistantSettings(status_topic="homeassistant/status")
    return HomeAssistantPublisher(mock_client, cfg)


@pytest.fixture
def publisher_no_device(mock_client: Mock) -> HomeAssistantPublisher:
    cfg = HomeAssistantSettings(status_topic="homeassistant/status", device_creation=False)
    return HomeAssistantPublisher(mock_client, cfg)


@pytest.fixture
def event_config() -> EventSettings:
    return EventSettings(camera="cam1", event="anpr")


@pytest.fixture
def camera() -> CameraSettings:
    return CameraSettings(name="cam1")


@pytest.fixture
def camera_with_area() -> CameraSettings:
    return CameraSettings(name="cam1", area="Driveway", live_url="http://cam1/live")


# --- start ---


def test_start(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.start()
    mock_client.subscribe.assert_called_once_with("homeassistant/status")
    assert mock_client.on_message == publisher.on_message
    assert mock_client.on_subscribe == publisher.on_subscribe
    assert mock_client.on_unsubscribe == publisher.on_unsubscribe


# --- on_subscribe / on_unsubscribe ---


def test_on_subscribe(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.on_subscribe(mock_client, None, 1, [])


def test_on_unsubscribe(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.on_unsubscribe(mock_client, None, 1, [])


# --- on_message ---


def test_on_message_offline(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = b"offline"
    publisher.on_message(mock_client, None, msg)
    assert publisher.hass_online is False


def test_on_message_online_after_offline(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.republish["test/topic"] = "payload"
    publisher.hass_online = False
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = b"online"
    with patch("time.sleep"), patch("random.randint", return_value=1):
        publisher.on_message(mock_client, None, msg)
    assert publisher.hass_online is True
    mock_client.publish.assert_called_once_with("test/topic", "payload")


def test_on_message_online_first_time(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = b"online"
    publisher.on_message(mock_client, None, msg)
    assert publisher.hass_online is True
    mock_client.publish.assert_not_called()


def test_on_message_unknown_payload(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = b"something_unexpected"
    publisher.on_message(mock_client, None, msg)


def test_on_message_empty_payload(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = None
    publisher.on_message(mock_client, None, msg)


def test_on_message_unknown_topic(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    msg = Mock()
    msg.topic = "some/other/topic"
    msg.payload = b"online"
    publisher.on_message(mock_client, None, msg)


# --- republish_discovery ---


def test_republish_discovery_empty(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.republish_discovery()
    mock_client.publish.assert_not_called()


def test_republish_discovery_with_entries(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.republish["topic/a"] = "payloadA"
    publisher.republish["topic/b"] = "payloadB"
    with patch("time.sleep"), patch("random.randint", return_value=1):
        publisher.republish_discovery()
    assert mock_client.publish.call_count == 2
    mock_client.publish.assert_any_call("topic/a", "payloadA")
    mock_client.publish.assert_any_call("topic/b", "payloadB")


# --- publish_sensor_discovery ---


def test_publish_sensor_discovery_with_device(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    state_topic = "anpr2mqtt/anpr/cam1/state"
    publisher.publish_sensor_discovery(state_topic, event_config, camera)
    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    topic = args[0]
    payload = json.loads(kwargs["payload"])
    assert topic == "homeassistant/sensor/cam1/anpr/config"
    assert payload["state_topic"] == state_topic
    assert "dev" in payload
    assert kwargs["retain"] is True


def test_publish_sensor_discovery_no_device(
    publisher_no_device: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher_no_device.publish_sensor_discovery("anpr2mqtt/anpr/cam1/state", event_config, camera)
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert "dev" not in payload


def test_publish_sensor_discovery_with_description(
    publisher: HomeAssistantPublisher, mock_client: Mock, camera: CameraSettings
) -> None:
    event_config = EventSettings(camera="cam1", event="anpr", description="Front Gate ANPR")
    publisher.publish_sensor_discovery("anpr2mqtt/anpr/cam1/state", event_config, camera)
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["name"] == "Front Gate ANPR"


def test_publish_sensor_discovery_stored_for_republish(
    publisher: HomeAssistantPublisher, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.publish_sensor_discovery("anpr2mqtt/anpr/cam1/state", event_config, camera)
    assert "homeassistant/sensor/cam1/anpr/config" in publisher.republish


# --- publish_image_discovery ---


def test_publish_image_discovery(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.publish_image_discovery("anpr2mqtt/anpr/cam1/state", "anpr2mqtt/anpr/cam1/image", event_config, camera)
    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    topic = args[0]
    payload = json.loads(kwargs["payload"])
    assert topic == "homeassistant/image/cam1/anpr/config"
    assert payload["image_topic"] == "anpr2mqtt/anpr/cam1/image"
    assert "dev" in payload
    assert kwargs["retain"] is True


def test_publish_image_discovery_no_device(
    publisher_no_device: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher_no_device.publish_image_discovery("s", "i", event_config, camera)
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert "dev" not in payload


# --- publish_camera_discovery ---


def test_publish_camera_discovery(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.publish_camera_discovery("anpr2mqtt/anpr/cam1/state", "anpr2mqtt/anpr/cam1/image", event_config, camera)
    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    topic = args[0]
    payload = json.loads(kwargs["payload"])
    assert topic == "homeassistant/camera/cam1/anpr/config"
    assert "dev" in payload


def test_publish_camera_discovery_no_device(
    publisher_no_device: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher_no_device.publish_camera_discovery("s", "i", event_config, camera)
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert "dev" not in payload


# --- add_device_info ---


def test_add_device_info_with_area(publisher: HomeAssistantPublisher, camera_with_area: CameraSettings) -> None:
    payload: dict[str, Any] = {}
    publisher.add_device_info(payload, camera_with_area)
    assert "dev" in payload
    assert payload["dev"]["suggested_area"] == "Driveway"


def test_add_device_info_without_area(publisher: HomeAssistantPublisher, camera: CameraSettings) -> None:
    payload: dict[str, Any] = {}
    publisher.add_device_info(payload, camera)
    assert "dev" in payload
    assert "suggested_area" not in payload["dev"]


# --- post_state_message ---


def test_post_state_message_minimal(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.post_state_message("anpr2mqtt/anpr/cam1/state", target=None, event_config=event_config, camera=camera)
    mock_client.publish.assert_called_once()
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["target"] is None
    assert payload["event"] == "anpr"
    assert payload["camera"] == "cam1"


def test_post_state_message_with_all_fields(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera_with_area: CameraSettings
) -> None:
    image_info = ImageInfo(
        target="AB12CDE",
        event="VEHICLE_DETECTION",
        timestamp=dt.datetime(2025, 6, 2, 10, 30, 45, tzinfo=dt.UTC),
        ext="jpg",
        size=12345,
    )
    publisher.post_state_message(
        "anpr2mqtt/anpr/cam1/state",
        target="AB12CDE",
        event_config=event_config,
        camera=camera_with_area,
        ocr_fields={"vehicle_direction": "Forward"},
        image_info=image_info,
        classification={"known": True, "dangerous": False},
        previous_sightings=3,
        last_sighting=dt.datetime(2025, 6, 1, tzinfo=dt.UTC),
        url="http://cam1/image.jpg",
        reg_info={"make": "FORD"},
        file_path=Path("/data/image.jpg"),
    )
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["target"] == "AB12CDE"
    assert payload["vehicle_direction"] == "Forward"
    assert payload["known"] is True
    assert payload["previous_sightings"] == 3
    assert payload["event_image_url"] == "http://cam1/image.jpg"
    assert payload["file_path"] == "/data/image.jpg"
    assert payload["ext"] == "jpg"
    assert payload["image_size"] == 12345
    assert payload["area"] == "Driveway"
    assert payload["live_url"] == "http://cam1/live"
    assert payload["reg_info"] == {"make": "FORD"}
    assert "last_sighting" in payload


def test_post_state_message_with_error(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.post_state_message("topic", target=None, event_config=event_config, camera=camera, error="Something broke")
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["error"] == "Something broke"


def test_post_state_message_publish_exception(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    mock_client.publish.side_effect = RuntimeError("mqtt down")
    # Should not raise
    publisher.post_state_message("topic", target=None, event_config=event_config, camera=camera)


# --- post_image_message ---


def test_post_image_message(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    img = Image.new("RGB", (10, 10), color="red")
    publisher.post_image_message("anpr2mqtt/anpr/cam1/image", img, "JPEG")
    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    assert args[0] == "anpr2mqtt/anpr/cam1/image"
    assert isinstance(kwargs["payload"], bytes)
    assert len(kwargs["payload"]) > 0


def test_post_image_message_exception(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    mock_client.publish.side_effect = RuntimeError("mqtt down")
    img = Image.new("RGB", (10, 10))
    # Should not raise
    publisher.post_image_message("topic", img, "JPEG")
