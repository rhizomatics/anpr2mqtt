import json
import threading
from io import BytesIO
from typing import Any
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from anpr2mqtt.frigate_handler import FrigateHandler
from anpr2mqtt.settings import (
    TARGET_TYPE_PLATE,
    AutoClearSettings,
    CameraSettings,
    DVLASettings,
    EventSettings,
    FrigateSettings,
    ImageSettings,
    Target,
)
from anpr2mqtt.tracker import Sighting, Tracker


def _make_jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buf, "JPEG")
    return buf.getvalue()


def _make_payload(**overrides: Any) -> bytes:
    data: dict[str, Any] = {
        "type": "end",
        "event_id": "evt-123",
        "camera": "driveway",
        "start_time": 1_700_000_000.0,
        "after": {
            "recognized_license_plate": "AB12CDE",
            # Use an integer score so int() cast doesn't truncate to 0
            "recognized_license_plate_score": 95,
        },
    }
    data.update(overrides)
    return json.dumps(data).encode()


@pytest.fixture
def mock_mqtt() -> Mock:
    return Mock()


@pytest.fixture
def mock_publisher() -> Mock:
    return Mock()


@pytest.fixture
def mock_tracker() -> Mock:
    tracker = Mock(spec=Tracker)
    tracker.find.return_value = Sighting(
        target=Target(id="AB12CDE", target_type=TARGET_TYPE_PLATE),
    )
    tracker.record.return_value = {"previous_sightings": 0}
    return tracker


@pytest.fixture
def camera_config(mock_tracker: Mock) -> dict[str, Any]:
    event_cfg = EventSettings(camera="driveway", event="anpr")
    cam_cfg = CameraSettings(name="driveway")
    return {
        "driveway": (
            event_cfg,
            cam_cfg,
            mock_tracker,
            "anpr2mqtt/anpr/driveway/state",
            "anpr2mqtt/anpr/driveway/image",
        )
    }


@pytest.fixture
def handler(mock_mqtt: Mock, mock_publisher: Mock, camera_config: dict[str, Any]) -> FrigateHandler:
    return FrigateHandler(
        mqtt_client=mock_mqtt,
        frigate_settings=FrigateSettings(enabled=True, min_score=0.70),
        publisher=mock_publisher,
        image_settings=ImageSettings(),
        dvla_settings=DVLASettings(),
        camera_configs=camera_config,
    )


# --- start ---


def test_start_subscribes_and_registers_callbacks(handler: FrigateHandler, mock_mqtt: Mock) -> None:
    handler.start()
    mock_mqtt.subscribe.assert_any_call("frigate/events")
    mock_mqtt.subscribe.assert_any_call("frigate/+/snapshot")
    mock_mqtt.message_callback_add.assert_any_call("frigate/events", handler._on_event_message)
    mock_mqtt.message_callback_add.assert_any_call("frigate/+/snapshot", handler._on_snapshot_message)


# --- _on_snapshot_message ---


def test_on_snapshot_message_caches_bytes(handler: FrigateHandler) -> None:
    msg = Mock()
    msg.topic = "frigate/driveway/snapshot"
    msg.payload = b"\xff\xd8\xff"
    handler._on_snapshot_message(Mock(), None, msg)
    assert handler._snapshot_cache["driveway"] == b"\xff\xd8\xff"


def test_on_snapshot_message_ignores_empty_payload(handler: FrigateHandler) -> None:
    msg = Mock()
    msg.topic = "frigate/driveway/snapshot"
    msg.payload = b""
    handler._on_snapshot_message(Mock(), None, msg)
    assert "driveway" not in handler._snapshot_cache


def test_on_snapshot_message_short_topic_ignored(handler: FrigateHandler) -> None:
    msg = Mock()
    msg.topic = "frigate/snapshot"
    msg.payload = b"data"
    handler._on_snapshot_message(Mock(), None, msg)
    assert handler._snapshot_cache == {}


def test_on_snapshot_message_overwrites_stale_cache(handler: FrigateHandler) -> None:
    handler._snapshot_cache["driveway"] = b"old"
    msg = Mock()
    msg.topic = "frigate/driveway/snapshot"
    msg.payload = b"new"
    handler._on_snapshot_message(Mock(), None, msg)
    assert handler._snapshot_cache["driveway"] == b"new"


# --- _on_event_message ---


def test_on_event_message_delegates_to_process_event(handler: FrigateHandler) -> None:
    msg = Mock()
    msg.payload = _make_payload()
    with patch.object(handler, "_process_event") as mock_process:
        handler._on_event_message(Mock(), None, msg)
    mock_process.assert_called_once_with(msg.topic, msg.payload)


def test_on_event_message_catches_exceptions(handler: FrigateHandler) -> None:
    msg = Mock()
    msg.payload = _make_payload()
    with patch.object(handler, "_process_event", side_effect=RuntimeError("boom")):
        handler._on_event_message(Mock(), None, msg)  # must not raise


# --- _process_event: early returns ---


def test_process_event_invalid_json_skipped(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler._process_event("frigate/events", b"not valid json{")
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_non_end_type_ignored(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler._process_event("frigate/events", _make_payload(type="new"))
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_update_type_ignored(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler._process_event("frigate/events", _make_payload(type="update"))
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_camera_not_in_allowlist_skipped(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler.frigate_settings = FrigateSettings(cameras=["driveway"], min_score=0.70)
    handler._process_event("frigate/events", _make_payload(camera="garage"))
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_camera_in_allowlist_processed(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler.frigate_settings = FrigateSettings(cameras=["driveway"], min_score=0.70)
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload(camera="driveway"))
    mock_publisher.post_state_message.assert_called_once()


def test_process_event_no_camera_filter_allows_all(handler: FrigateHandler, mock_publisher: Mock) -> None:
    # cameras=None means process everything; use a known camera to avoid real filesystem writes
    assert handler.frigate_settings.cameras is None
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload(camera="driveway", event_id="no-filter-test"))
    mock_publisher.post_state_message.assert_called_once()


def test_process_event_duplicate_event_id_skipped(handler: FrigateHandler, mock_publisher: Mock) -> None:
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.reset_mock()
    handler._process_event("frigate/events", _make_payload())
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_missing_plate_skipped(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler._process_event(
        "frigate/events", _make_payload(after={"recognized_license_plate": None, "recognized_license_plate_score": 95})
    )
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_low_score_skipped(handler: FrigateHandler, mock_publisher: Mock) -> None:
    # int(0) = 0 < min_score 0.70 → filtered
    handler._process_event(
        "frigate/events", _make_payload(after={"recognized_license_plate": "AB12CDE", "recognized_license_plate_score": 0})
    )
    mock_publisher.post_state_message.assert_not_called()


# --- _process_event: happy path ---


def test_process_event_publishes_state(handler: FrigateHandler, mock_publisher: Mock) -> None:
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.post_state_message.assert_called_once()
    args, kwargs = mock_publisher.post_state_message.call_args
    assert args[0] == "anpr2mqtt/anpr/driveway/state"
    assert kwargs["source"] == "frigate"
    assert kwargs["frigate_event_id"] == "evt-123"


def test_process_event_publishes_image_when_available(handler: FrigateHandler, mock_publisher: Mock) -> None:
    img = Image.new("RGB", (10, 10))
    with patch.object(handler, "_get_event_image", return_value=img), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.post_image_message.assert_called_once()
    args = mock_publisher.post_image_message.call_args[0]
    assert args[0] == "anpr2mqtt/anpr/driveway/image"


def test_process_event_no_image_skips_image_publish(handler: FrigateHandler, mock_publisher: Mock) -> None:
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.post_image_message.assert_not_called()


def test_process_event_sets_frigate_ui_url(handler: FrigateHandler, mock_publisher: Mock) -> None:
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    kwargs = mock_publisher.post_state_message.call_args[1]
    assert kwargs["frigate_ui_url"] == "http://frigate:5000/events?id=evt-123"


def test_process_event_no_url_leaves_ui_url_none(handler: FrigateHandler, mock_publisher: Mock) -> None:
    assert handler.frigate_settings.url is None
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    kwargs = mock_publisher.post_state_message.call_args[1]
    assert kwargs["frigate_ui_url"] is None


def test_process_event_ignored_plate_skips_state_publish(
    handler: FrigateHandler, mock_publisher: Mock, mock_tracker: Mock
) -> None:
    mock_tracker.find.return_value = Sighting(
        target=Target(id="AB12CDE", target_type=TARGET_TYPE_PLATE),
        ignore=True,
    )
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.post_state_message.assert_not_called()


def test_process_event_target_with_entity_id_publishes_target_state(
    handler: FrigateHandler, mock_publisher: Mock, mock_tracker: Mock
) -> None:
    mock_tracker.find.return_value = Sighting(
        target=Target(id="AB12CDE", target_type=TARGET_TYPE_PLATE, entity_id="my_car"),
    )
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.publish_target_state.assert_called_once()
    call_kwargs = mock_publisher.publish_target_state.call_args[1]
    assert "my_car" in call_kwargs["state_topic"]


def test_process_event_no_entity_id_skips_target_state(
    handler: FrigateHandler, mock_publisher: Mock, mock_tracker: Mock
) -> None:
    mock_tracker.find.return_value = Sighting(
        target=Target(id="AB12CDE", target_type=TARGET_TYPE_PLATE, entity_id=None),
    )
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload())
    mock_publisher.publish_target_state.assert_not_called()


def test_process_event_schedules_autoclear(handler: FrigateHandler) -> None:
    with (
        patch.object(handler, "_get_event_image", return_value=None),
        patch.object(handler, "_schedule_autoclear") as mock_sched,
    ):
        handler._process_event("frigate/events", _make_payload())
    mock_sched.assert_called_once()


def test_process_event_extra_info_includes_frigate_key(handler: FrigateHandler, mock_publisher: Mock) -> None:
    after = {
        "recognized_license_plate": "AB12CDE",
        "recognized_license_plate_score": 95,
        "current_estimated_speed": 42,
    }
    with patch.object(handler, "_get_event_image", return_value=None), patch.object(handler, "_schedule_autoclear"):
        handler._process_event("frigate/events", _make_payload(after=after))
    kwargs = mock_publisher.post_state_message.call_args[1]
    assert "frigate" in kwargs["extra_info"]
    assert kwargs["extra_info"]["frigate"]["current_estimated_speed"] == 42


# --- processed event ID set bounded ---


def test_process_event_id_set_pruned_when_oversized(mock_tracker: Mock) -> None:
    cam_cfg: dict[str, Any] = {
        "x": (
            EventSettings(camera="x", event="anpr"),
            CameraSettings(name="x"),
            mock_tracker,
            "anpr2mqtt/anpr/x/state",
            "anpr2mqtt/anpr/x/image",
        )
    }
    h = FrigateHandler(
        mqtt_client=Mock(),
        frigate_settings=FrigateSettings(min_score=0.0),
        publisher=Mock(),
        image_settings=ImageSettings(),
        dvla_settings=DVLASettings(),
        camera_configs=cam_cfg,
    )
    h._processed_events = {str(i) for i in range(5001)}
    with patch.object(h, "_get_event_image", return_value=None), patch.object(h, "_schedule_autoclear"):
        h._process_event("frigate/events", _make_payload(event_id="trim-trigger", camera="x"))
    # After pruning [2500:] from 5001 entries and adding the new ID: 2502 total
    assert len(h._processed_events) <= 2502


# --- _get_event_image ---


def test_get_event_image_uses_cached_mqtt_snapshot(handler: FrigateHandler) -> None:
    handler._snapshot_cache["driveway"] = _make_jpeg_bytes()
    img = handler._get_event_image("evt-123", "driveway")
    assert img is not None


def test_get_event_image_falls_back_to_api_when_no_cache(handler: FrigateHandler) -> None:
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    expected = Image.new("RGB", (10, 10))
    with patch.object(handler, "_fetch_api_snapshot", return_value=expected) as mock_fetch:
        img = handler._get_event_image("evt-123", "driveway")
    mock_fetch.assert_called_once_with("evt-123")
    assert img is expected


def test_get_event_image_returns_none_when_no_snapshot_no_url(handler: FrigateHandler) -> None:
    assert handler.frigate_settings.url is None
    img = handler._get_event_image("evt-123", "driveway")
    assert img is None


def test_get_event_image_falls_back_to_api_on_bad_snapshot_bytes(handler: FrigateHandler) -> None:
    handler._snapshot_cache["driveway"] = b"not-an-image"
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    with patch.object(handler, "_fetch_api_snapshot", return_value=None) as mock_fetch:
        handler._get_event_image("evt-123", "driveway")
    mock_fetch.assert_called_once_with("evt-123")


# --- _fetch_api_snapshot ---


def test_fetch_api_snapshot_success(handler: FrigateHandler) -> None:
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.content = _make_jpeg_bytes()
    with patch("anpr2mqtt.frigate_handler.niquests.get", return_value=mock_resp):
        img = handler._fetch_api_snapshot("evt-123")
    assert img is not None


def test_fetch_api_snapshot_non_200_returns_none(handler: FrigateHandler) -> None:
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    mock_resp = Mock()
    mock_resp.status_code = 404
    mock_resp.content = b""
    with patch("anpr2mqtt.frigate_handler.niquests.get", return_value=mock_resp):
        img = handler._fetch_api_snapshot("evt-123")
    assert img is None


def test_fetch_api_snapshot_network_error_returns_none(handler: FrigateHandler) -> None:
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    with patch("anpr2mqtt.frigate_handler.niquests.get", side_effect=ConnectionError("timeout")):
        img = handler._fetch_api_snapshot("evt-123")
    assert img is None


def test_fetch_api_snapshot_uses_correct_url(handler: FrigateHandler) -> None:
    handler.frigate_settings = FrigateSettings(url="http://frigate:5000", min_score=0.70)
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.content = _make_jpeg_bytes()
    with patch("anpr2mqtt.frigate_handler.niquests.get", return_value=mock_resp) as mock_get:
        handler._fetch_api_snapshot("evt-abc")
    mock_get.assert_called_once_with("http://frigate:5000/api/events/evt-abc/snapshot.jpg", timeout=10)


# --- _resolve_camera_config ---


def test_resolve_camera_config_returns_known_camera(handler: FrigateHandler) -> None:
    event_cfg, cam_cfg, _, state_topic, image_topic = handler._resolve_camera_config("driveway")
    assert event_cfg.camera == "driveway"
    assert cam_cfg.name == "driveway"
    assert state_topic == "anpr2mqtt/anpr/driveway/state"
    assert image_topic == "anpr2mqtt/anpr/driveway/image"


def test_resolve_camera_config_unknown_camera_synthesises_defaults(handler: FrigateHandler) -> None:
    event_cfg, cam_cfg, _, state_topic, image_topic = handler._resolve_camera_config("garage")
    assert event_cfg.camera == "garage"
    assert cam_cfg.name == "garage"
    assert "garage" in state_topic
    assert "garage" in image_topic


def test_resolve_camera_config_unknown_camera_uses_default_tracker(handler: FrigateHandler) -> None:
    default_tracker = Mock(spec=Tracker)
    handler.default_tracker = default_tracker
    _, _, tracker, _, _ = handler._resolve_camera_config("unknown")
    assert tracker is default_tracker


def test_resolve_camera_config_unknown_camera_creates_tracker_when_no_default(handler: FrigateHandler) -> None:
    handler.default_tracker = None
    _, _, tracker, _, _ = handler._resolve_camera_config("unknown")
    assert isinstance(tracker, Tracker)


# --- _schedule_autoclear ---


def test_schedule_autoclear_does_nothing_when_disabled(handler: FrigateHandler) -> None:
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(enabled=False))
    handler._schedule_autoclear("driveway", event_cfg, "s", "i")
    assert "driveway" not in handler._autoclear_timers


def test_schedule_autoclear_creates_timer(handler: FrigateHandler) -> None:
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(enabled=True, post_event=60))
    handler._schedule_autoclear("driveway", event_cfg, "s", "i")
    assert "driveway" in handler._autoclear_timers
    handler._autoclear_timers["driveway"].cancel()


def test_schedule_autoclear_cancels_existing_timer(handler: FrigateHandler) -> None:
    old_timer = Mock(spec=threading.Timer)
    handler._autoclear_timers["driveway"] = old_timer
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(enabled=True, post_event=60))
    handler._schedule_autoclear("driveway", event_cfg, "s", "i")
    old_timer.cancel.assert_called_once()
    handler._autoclear_timers["driveway"].cancel()


# --- _do_autoclear ---


def test_do_autoclear_publishes_state_and_image(handler: FrigateHandler, mock_publisher: Mock) -> None:
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(state=True, image=True))
    handler._do_autoclear("driveway", event_cfg, "s/state", "s/image")
    mock_publisher.post_state_message.assert_called_once()
    mock_publisher.post_image_message.assert_called_once()


def test_do_autoclear_state_only(handler: FrigateHandler, mock_publisher: Mock) -> None:
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(state=True, image=False))
    handler._do_autoclear("driveway", event_cfg, "s", "i")
    mock_publisher.post_state_message.assert_called_once()
    mock_publisher.post_image_message.assert_not_called()


def test_do_autoclear_image_only(handler: FrigateHandler, mock_publisher: Mock) -> None:
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(state=False, image=True))
    handler._do_autoclear("driveway", event_cfg, "s", "i")
    mock_publisher.post_state_message.assert_not_called()
    mock_publisher.post_image_message.assert_called_once()


def test_do_autoclear_passes_none_sighting_to_state(handler: FrigateHandler, mock_publisher: Mock) -> None:
    event_cfg = EventSettings(camera="driveway", event="anpr", autoclear=AutoClearSettings(state=True, image=False))
    handler._do_autoclear("driveway", event_cfg, "s", "i")
    kwargs = mock_publisher.post_state_message.call_args[1]
    assert kwargs["sighting"] is None


# --- DVLAClient initialisation ---


def test_dvla_api_client_created_when_key_provided(mock_mqtt: Mock, mock_publisher: Mock) -> None:
    with patch("anpr2mqtt.frigate_handler.DVLAClient") as mock_dvla_cls:
        h = FrigateHandler(
            mqtt_client=mock_mqtt,
            frigate_settings=FrigateSettings(),
            publisher=mock_publisher,
            image_settings=ImageSettings(),
            dvla_settings=DVLASettings(api_key="test-key"),
            camera_configs={},
        )
    mock_dvla_cls.assert_called_once()
    assert h.api_client is not None


def test_dvla_api_client_not_created_without_key(handler: FrigateHandler) -> None:
    assert handler.api_client is None
