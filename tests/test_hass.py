import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.hass import DEVICE_MANUFACTURER, DEVICE_MODEL, HomeAssistantPublisher
from anpr2mqtt.settings import CameraSettings, EventSettings, HomeAssistantSettings, Target
from anpr2mqtt.tracker import Sighting


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
    publisher.republish["test/topic"] = {"payload": "123"}
    publisher.hass_online = False
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = b"online"
    with patch("time.sleep"), patch("random.randint", return_value=1):
        publisher.on_message(mock_client, None, msg)
        _join_republish()
    assert publisher.hass_online is True
    mock_client.publish.assert_called_once_with("test/topic", '{"payload": "123", "trigger": "homeassistant/status_online"}')


def _join_republish() -> None:
    for t in threading.enumerate():
        if t.name == "hass-republish":
            t.join(timeout=5)


def test_on_message_republish_does_not_sleep_on_mqtt_thread(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    """Regression: the jittered sleeps ran in the paho callback, stalling keepalives and Frigate events"""
    publisher.republish["test/topic"] = {"payload": "123"}
    publisher.hass_online = False
    msg = Mock()
    msg.topic = "homeassistant/status"
    msg.payload = b"online"
    sleeping_threads: list[int] = []
    with patch("time.sleep", side_effect=lambda _s: sleeping_threads.append(threading.get_ident())):
        publisher.on_message(mock_client, None, msg)
        _join_republish()
    assert sleeping_threads
    assert threading.get_ident() not in sleeping_threads
    mock_client.publish.assert_called_once()


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
    publisher.republish_discovery("empty")
    mock_client.publish.assert_not_called()


def test_republish_discovery_with_entries(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.republish["topic/a"] = {"payload": "A"}
    publisher.republish["topic/b"] = {"payload": "B"}
    with patch("time.sleep"), patch("random.randint", return_value=1):
        publisher.republish_discovery("entries")
    assert mock_client.publish.call_count == 2
    mock_client.publish.assert_any_call("topic/a", '{"payload": "A", "trigger": "entries"}')
    mock_client.publish.assert_any_call("topic/b", '{"payload": "B", "trigger": "entries"}')


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
    assert payload["dev"]["configuration_url"] == "http://cam1/live"


def test_add_device_info_says_anpr2mqtt(publisher: HomeAssistantPublisher, camera: CameraSettings) -> None:
    payload: dict[str, Any] = {}
    publisher.add_device_info(payload, camera)
    assert (
        (payload["dev"]["manufacturer"], payload["dev"]["model"])
        == (DEVICE_MANUFACTURER, DEVICE_MODEL)
        == (
            "Rhizomatics",
            "anpr2mqtt",
        )
    )
    # unchanged, so existing devices are kept
    assert payload["dev"]["identifiers"] == ["cam1.anpr2mqtt"]
    assert "configuration_url" not in payload["dev"]


def test_add_device_info_skips_unusable_live_url(publisher: HomeAssistantPublisher) -> None:
    payload: dict[str, Any] = {}
    publisher.add_device_info(payload, CameraSettings(name="cam1", live_url="frigate.local/cam1"))
    assert "configuration_url" not in payload["dev"]


def test_add_device_info_without_area(publisher: HomeAssistantPublisher, camera: CameraSettings) -> None:
    payload: dict[str, Any] = {}
    publisher.add_device_info(payload, camera)
    assert "dev" in payload
    assert "suggested_area" not in payload["dev"]


# --- post_state_message ---


def test_post_state_message_minimal(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.post_state_message("anpr2mqtt/anpr/cam1/state", sighting=None, event_config=event_config, camera=camera)
    mock_client.publish.assert_called_once()
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["target"] is None
    assert payload["event"] == "anpr"
    assert payload["camera"] == "cam1"


def test_post_state_message_linked_cameras(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings
) -> None:
    camera = CameraSettings(name="cam1", linked_cameras={"frigate": "driveway_lpr", "viseron": "drive"})
    publisher.post_state_message("anpr2mqtt/anpr/cam1/state", sighting=None, event_config=event_config, camera=camera)
    _args, kwargs = mock_client.publish.call_args
    assert json.loads(kwargs["payload"])["linked_cameras"] == {"frigate": "driveway_lpr", "viseron": "drive"}


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
        sighting=Sighting(target=Target(id="AB12CDE", target_type="plate", group="known")),
        event_config=event_config,
        camera=camera_with_area,
        extra_info={"vehicle_direction": "Forward"},
        image_info=image_info,
        time_analysis={
            "previous_sightings": 3,
            "last_seen": "2025-06-01T00:00:00+00:00",
            "hourly_counts": {},
            "earliest_time": "08:00:00",
            "latest_time": "14:00:00",
            "within_time_range": True,
        },
        url="http://cam1/image.jpg",
        reg_info={"make": "FORD"},
        file_path=Path("/data/image.jpg"),
    )
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["target"] == "AB12CDE"
    assert payload["vehicle_direction"] == "Forward"
    assert payload["known"] is True
    assert payload["history"]["previous_sightings"] == 3
    assert payload["history"]["last_seen"] == "2025-06-01T00:00:00+00:00"
    assert payload["history"]["within_time_range"] is True
    assert payload["event_image_url"] == "http://cam1/image.jpg"
    assert payload["file_path"] == "/data/image.jpg"
    assert payload["ext"] == "jpg"
    assert payload["image_size"] == 12345
    assert payload["area"] == "Driveway"
    assert payload["live_url"] == "http://cam1/live"
    assert payload["linked_cameras"] == {}
    assert payload["reg_info"] == {"make": "FORD"}


def test_post_state_message_with_error(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.post_state_message("topic", sighting=None, event_config=event_config, camera=camera, error="Something broke")
    _args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert payload["error"] == "Something broke"


def test_post_state_message_publish_exception(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    mock_client.publish.side_effect = RuntimeError("mqtt down")
    # Should not raise
    publisher.post_state_message("topic", sighting=None, event_config=event_config, camera=camera)


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


def test_post_image_message_none_clears_topic(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    """image=None publishes a null payload to clear the topic (lines 232-234)."""
    publisher.post_image_message("test/images", None)
    mock_client.publish.assert_called_once_with("test/images", payload=None, qos=0, retain=True)


def test_post_state_message_with_camera_publish_exception(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    """client.publish raises → exception caught and logged (lines 226-227 in hass.py)."""
    mock_client.publish.side_effect = RuntimeError("broker gone")
    event_config = EventSettings(camera="cam", event="anpr")
    camera = CameraSettings(name="cam")
    # Should not raise
    publisher.post_state_message("test/topic", sighting=None, event_config=event_config, camera=camera)


# --- availability ---


def test_availability_topic() -> None:
    from anpr2mqtt.hass import availability_topic

    assert availability_topic("anpr2mqtt") == "anpr2mqtt/availability"


@pytest.mark.parametrize(("online", "payload"), [(True, "online"), (False, "offline")])
def test_publish_availability(mock_client: Mock, online: bool, payload: str) -> None:
    from anpr2mqtt.hass import publish_availability

    publish_availability(mock_client, "anpr2mqtt/availability", online=online)
    mock_client.publish.assert_called_once_with("anpr2mqtt/availability", payload=payload, qos=1, retain=True)


def _discovery_payloads(mock_client: Mock) -> list[dict[str, Any]]:
    return [json.loads(c.kwargs["payload"]) for c in mock_client.publish.call_args_list]


def _publish_all_discovery(pub: HomeAssistantPublisher, event_config: EventSettings, camera: CameraSettings) -> None:
    pub.publish_sensor_discovery("s/state", event_config, camera)
    pub.publish_image_discovery("s/state", "s/image", event_config, camera)
    pub.publish_camera_discovery("s/state", "s/image", event_config, camera)
    pub.publish_target_sensor_discovery("tgt", "plate", [Target(id="AB12CDE")], "t/state", None)


def test_discovery_includes_availability_topic(mock_client: Mock, event_config: EventSettings, camera: CameraSettings) -> None:
    pub = HomeAssistantPublisher(
        mock_client, HomeAssistantSettings(status_topic="homeassistant/status"), availability_topic="anpr2mqtt/availability"
    )
    _publish_all_discovery(pub, event_config, camera)
    payloads = _discovery_payloads(mock_client)
    assert len(payloads) == 4
    assert all(p["availability_topic"] == "anpr2mqtt/availability" for p in payloads)


def test_discovery_without_availability_topic(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    _publish_all_discovery(publisher, event_config, camera)
    assert all("availability_topic" not in p for p in _discovery_payloads(mock_client))


def test_start_records_subscription_once(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    userdata: dict = {"subscriptions": []}
    mock_client.user_data_get.return_value = userdata
    publisher.start()
    publisher.start()
    assert userdata["subscriptions"] == ["homeassistant/status"]


def test_target_sensor_unique_id_is_stable(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    """Regression: unique_id used hash(), which Python randomises per process, so every restart made a new entity"""
    targets = [Target(id="AB12CDE"), Target(id="XY99ZZZ")]
    publisher.publish_target_sensor_discovery("known_cars", "plate", targets, "t/state", None)
    assert _discovery_payloads(mock_client)[0]["unique_id"] == "plate_known_cars"


def _scene_event() -> EventSettings:
    import re

    return EventSettings(
        camera="cam1",
        event="scene_change",
        target_type="scene_change",
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<event>SCENE_CHANGE_DETECTION)\.jpg"),
    )


def test_publish_event_discovery(publisher: HomeAssistantPublisher, mock_client: Mock, camera: CameraSettings) -> None:
    publisher.publish_event_discovery(
        "anpr2mqtt/scene_change/cameras/cam1/event", "anpr2mqtt/scene_change/cameras/cam1/state", _scene_event(), camera
    )
    args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert args[0] == "homeassistant/event/cam1/scene_change/config"
    assert payload["default_entity_id"] == "event.scene_change_cam1"
    assert payload["state_topic"] == "anpr2mqtt/scene_change/cameras/cam1/event"
    assert payload["event_types"] == ["scene_change"]
    assert payload["json_attributes_topic"] == "anpr2mqtt/scene_change/cameras/cam1/state"
    assert "images" in payload["json_attributes_template"]
    assert "event_time" not in payload["json_attributes_template"]
    assert payload["icon"] == "mdi:cctv"
    assert payload["dev"]["model"] == DEVICE_MODEL
    assert kwargs["retain"] is True


def test_remove_sensor_discovery(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.remove_sensor_discovery(_scene_event())
    mock_client.publish.assert_called_once_with("homeassistant/sensor/cam1/scene_change/config", payload="", qos=0, retain=True)


def test_state_with_event_topic_fires_event(
    publisher: HomeAssistantPublisher, mock_client: Mock, camera: CameraSettings
) -> None:
    info = ImageInfo(None, "SCENE_CHANGE_DETECTION", dt.datetime(2026, 11, 27, 7, 10, 24, 588000, tzinfo=dt.UTC), "jpg", 10)
    publisher.post_state_message(
        "anpr2mqtt/scene_change/cameras/cam1/state", None, _scene_event(), camera, image_info=info, event_topic="ev/topic"
    )
    calls = {c.args[0]: c.kwargs for c in mock_client.publish.call_args_list}
    assert calls["anpr2mqtt/scene_change/cameras/cam1/state"]["retain"] is True
    assert calls["ev/topic"]["retain"] is False
    event = json.loads(calls["ev/topic"]["payload"])
    assert event["event_type"] == "scene_change"
    assert event["image_event"] == "SCENE_CHANGE_DETECTION"
    assert event["description"] == "Scene change"


def test_cleared_state_fires_no_event(publisher: HomeAssistantPublisher, mock_client: Mock, camera: CameraSettings) -> None:
    publisher.post_state_message("state/topic", None, _scene_event(), camera, event_topic="ev/topic")
    assert [c.args[0] for c in mock_client.publish.call_args_list] == ["state/topic"]


def test_plate_sensor_discovery_uses_target(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.publish_sensor_discovery("anpr2mqtt/anpr/cam1/state", event_config, camera)
    payload = json.loads(mock_client.publish.call_args.kwargs["payload"])
    assert payload["device_class"] is None
    assert payload["value_template"] == "{{ value_json.target }}"


def test_publish_secondary_image_discovery(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.publish_image_discovery(
        "anpr2mqtt/anpr/cam1/state", "anpr2mqtt/anpr/cam1/image/face_background", event_config, camera, "FACE_BACKGROUND"
    )
    args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert args[0] == "homeassistant/image/cam1/anpr_face_background/config"
    assert payload["unique_id"] == "anpr_cam1_face_background"
    assert payload["default_entity_id"] == "image.anpr_cam1_face_background"
    assert payload["image_topic"] == "anpr2mqtt/anpr/cam1/image/face_background"
    assert payload["name"].endswith("face background")


def test_state_carries_image_counts_and_refreshes(mock_client: Mock, camera: CameraSettings, tmp_path: Path) -> None:
    from anpr2mqtt.image_stats import ImageStats

    stats = ImageStats(tmp_path / "image_stats.json")
    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings(), image_stats=stats)
    scene = _scene_event()
    publisher.record_image(scene, camera)
    publisher.post_state_message("state/topic", None, scene, camera, event_topic="ev/topic")
    first = json.loads(mock_client.publish.call_args.kwargs["payload"])
    assert first["images"]["today"] == 1
    assert first["images"]["total"] == 1

    mock_client.reset_mock()
    publisher.record_image(scene, camera)
    publisher.refresh_image_stats("state/topic")
    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    refreshed = json.loads(kwargs["payload"])
    assert args[0] == "state/topic", "refreshes the state, never fires the event"
    assert refreshed["images"]["total"] == 2
    assert {k: v for k, v in refreshed.items() if k != "images"} == {k: v for k, v in first.items() if k != "images"}


def test_event_counts_only_its_own_images(mock_client: Mock, camera: CameraSettings) -> None:
    from anpr2mqtt.image_stats import ImageStats

    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings(), image_stats=ImageStats())
    scene = _scene_event()
    publisher.record_image(EventSettings(camera="cam1", target_type="face"), camera)
    publisher.record_image(scene, camera)
    publisher.post_state_message("state/topic", None, scene, camera)
    assert json.loads(mock_client.publish.call_args.kwargs["payload"])["images"]["total"] == 1


def _upload_event() -> EventSettings:
    return EventSettings(id="shed", target_type="upload", watch_path=Path("/ftp/shed"))


def test_publish_upload_discovery(mock_client: Mock) -> None:
    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings(), availability_topic="anpr2mqtt/availability")
    publisher.publish_upload_discovery("anpr2mqtt/uploads/upload_shed/state", _upload_event())
    args, kwargs = mock_client.publish.call_args
    payload = json.loads(kwargs["payload"])
    assert args[0] == "homeassistant/sensor/uploads/upload_shed/config"
    assert payload["unique_id"] == "uploads_upload_shed"
    assert payload["default_entity_id"] == "sensor.upload_shed", "named by id, no camera"
    assert payload["name"] == "Upload shed"
    assert payload["device_class"] == "timestamp"
    assert payload["value_template"] == "{{ value_json.last_received }}"
    assert payload["icon"] == "mdi:folder-upload"
    assert "dev" not in payload, "not on the device, so not taken as a plate sensor"
    assert payload["availability_topic"] == "anpr2mqtt/availability"
    assert args[0] in publisher.republish


def test_upload_state_and_midnight_refresh(mock_client: Mock) -> None:
    from anpr2mqtt.image_stats import ImageStats

    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings(), image_stats=ImageStats())
    upload = _upload_event()
    publisher.post_upload_state("upload/state", upload)
    empty = json.loads(mock_client.publish.call_args.kwargs["payload"])
    assert empty["total"] == 0
    assert empty["last_received"] is None
    assert empty["last_file"] is None
    assert empty["watch_path"] == "/ftp/shed"
    assert "camera" not in empty
    assert empty["id"] == "shed"

    publisher.record_upload(upload, "sub/x.jpg")
    mock_client.reset_mock()
    publisher.refresh_image_stats()
    mock_client.publish.assert_called_once()
    args, kwargs = mock_client.publish.call_args
    refreshed = json.loads(kwargs["payload"])
    assert args[0] == "upload/state"
    assert kwargs["retain"] is True
    assert refreshed["total"] == 1
    assert refreshed["today"] == 1
    assert refreshed["last_file"] == "sub/x.jpg"
    assert refreshed["last_received"] is not None


def test_upload_camera_published_as_attribute_only(mock_client: Mock) -> None:
    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings())
    upload = EventSettings(id="shed", camera="shed_cam", target_type="upload", watch_path=Path("/ftp/shed"))
    publisher.post_upload_state("upload/state", upload)
    assert json.loads(mock_client.publish.call_args.kwargs["payload"])["camera"] == "shed_cam"

    publisher.publish_upload_discovery("upload/state", upload)
    args, kwargs = mock_client.publish.call_args
    discovery = json.loads(kwargs["payload"])
    assert args[0] == "homeassistant/sensor/uploads/upload_shed/config", "camera not in the topic"
    assert discovery["default_entity_id"] == "sensor.upload_shed", "camera not in the entity id"
    assert "dev" not in discovery, "camera doesn't put it on a device"


def test_refresh_without_stats_does_nothing(publisher: HomeAssistantPublisher, mock_client: Mock) -> None:
    publisher.refresh_image_stats()
    mock_client.publish.assert_not_called()


def test_camera_entity_id_suffix_only_for_plates(
    publisher: HomeAssistantPublisher, mock_client: Mock, event_config: EventSettings, camera: CameraSettings
) -> None:
    publisher.publish_camera_discovery("s", "i", event_config, camera)
    assert json.loads(mock_client.publish.call_args.kwargs["payload"])["default_entity_id"] == "camera.anpr_cam1_anpr"
    publisher.publish_camera_discovery("s", "i", _scene_event(), camera)
    assert json.loads(mock_client.publish.call_args.kwargs["payload"])["default_entity_id"] == "camera.scene_change_cam1"


def _retained(topic: str, payload: Any) -> Mock:
    msg = Mock()
    msg.topic = topic
    msg.retain = True
    msg.payload = json.dumps(payload).encode() if payload is not None else b""
    return msg


def _sweep(publisher: HomeAssistantPublisher, mock_client: Mock, retained: list[Mock]) -> list[str]:
    """Run a sweep, with the broker sending back these retained messages when subscribed"""
    callbacks: dict[str, Any] = {}
    mock_client.message_callback_add.side_effect = lambda pattern, cb: callbacks.__setitem__(pattern, cb)
    mock_client.subscribe.side_effect = lambda pattern: [callbacks[pattern](mock_client, None, m) for m in retained]
    return publisher.sweep_stale_discovery(wait=0)


def test_sweep_removes_only_own_stale_discovery(mock_client: Mock, camera: CameraSettings) -> None:
    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings(), availability_topic="anpr2mqtt/availability")
    publisher.publish_event_discovery("anpr2mqtt/face/cameras/front/event", "anpr2mqtt/face/cameras/front/state",
                                      _scene_event(), camera)  # fmt: skip
    current = next(iter(publisher.republish))
    mine = {"availability_topic": "anpr2mqtt/availability", "unique_id": "anpr_front",
            "state_topic": "anpr2mqtt/anpr/cameras/front/state"}  # fmt: skip
    mock_client.reset_mock()

    removed = _sweep(publisher, mock_client, [
        _retained(current, publisher.republish[current]),
        _retained("homeassistant/sensor/front/anpr/config", mine),
        _retained("homeassistant/sensor/other/anpr/config", {**mine, "availability_topic": "other/availability"}),
        _retained("homeassistant/sensor/zigbee/config", {"state_topic": "zigbee2mqtt/x"}),
        _retained("homeassistant/sensor/cleared/config", None),
    ])  # fmt: skip

    assert removed == ["homeassistant/sensor/front/anpr/config"]
    published = {c.args[0]: c.kwargs for c in mock_client.publish.call_args_list}
    assert set(published) == {"homeassistant/sensor/front/anpr/config", "anpr2mqtt/anpr/cameras/front/state"}
    assert all(kw["payload"] == "" and kw["retain"] for kw in published.values())
    mock_client.unsubscribe.assert_called_once_with("homeassistant/#")
    mock_client.message_callback_remove.assert_called_once_with("homeassistant/#")


def test_sweep_keeps_state_topics_still_in_use(mock_client: Mock, camera: CameraSettings) -> None:
    publisher = HomeAssistantPublisher(mock_client, HomeAssistantSettings(), availability_topic="anpr2mqtt/availability")
    publisher.publish_sensor_discovery("anpr2mqtt/anpr/cameras/cam1/state", EventSettings(camera="cam1"), camera)
    mock_client.reset_mock()
    old_image = {"availability_topic": "anpr2mqtt/availability", "image_topic": "anpr2mqtt/anpr/cameras/cam1/image",
                 "json_attributes_topic": "anpr2mqtt/anpr/cameras/cam1/state"}  # fmt: skip

    _sweep(publisher, mock_client, [_retained("homeassistant/image/cam1/anpr/config", old_image)])

    cleared = [c.args[0] for c in mock_client.publish.call_args_list]
    assert "anpr2mqtt/anpr/cameras/cam1/image" in cleared
    assert "anpr2mqtt/anpr/cameras/cam1/state" not in cleared, "the plate sensor still reads it"


def test_sweep_disabled_or_without_availability(mock_client: Mock) -> None:
    off = HomeAssistantPublisher(
        mock_client, HomeAssistantSettings(remove_stale_entities=False), availability_topic="anpr2mqtt/availability"
    )
    assert off.sweep_stale_discovery(wait=0) == []
    assert HomeAssistantPublisher(mock_client, HomeAssistantSettings()).sweep_stale_discovery(wait=0) == []
    mock_client.subscribe.assert_not_called()
