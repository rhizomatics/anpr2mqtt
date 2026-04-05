import re
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from anpr2mqtt.app import main_loop, on_connect, on_disconnect
from anpr2mqtt.settings import EventSettings


def _make_rc(name: str, eq_zero: bool = True) -> Mock:
    rc = MagicMock()
    rc.getName.return_value = name
    rc.__eq__ = lambda self, other: eq_zero and other == 0  # type: ignore[method-assign,misc,assignment]  # noqa: ARG005
    rc.__ne__ = lambda self, other: not (eq_zero and other == 0)  # type: ignore[method-assign,misc,assignment]  # noqa: ARG005
    rc.__str__.return_value = name  # type: ignore[attr-defined]
    return rc


def test_on_connect_success() -> None:
    rc = _make_rc("Success", eq_zero=True)
    on_connect(Mock(), None, Mock(), rc)


def test_on_connect_not_authorized() -> None:
    rc = _make_rc("Not authorized", eq_zero=False)
    on_connect(Mock(), None, Mock(), rc)


def test_on_connect_failure() -> None:
    rc = _make_rc("Connection Refused", eq_zero=False)
    on_connect(Mock(), None, Mock(), rc)


def test_on_disconnect_success() -> None:
    rc = _make_rc("Normal disconnection", eq_zero=True)
    on_disconnect(Mock(), None, Mock(), rc, None)


def test_on_disconnect_failure() -> None:
    rc = _make_rc("Unexpected disconnection", eq_zero=False)
    on_disconnect(Mock(), None, Mock(), rc, None)


def _make_mock_settings(protocol: str = "3.11", events: list[EventSettings] | None = None) -> Mock:
    from anpr2mqtt.settings import HomeAssistantSettings

    settings = Mock()
    settings.log_level = "INFO"
    settings.targets = {}
    settings.mqtt.protocol = protocol
    settings.mqtt.host = "localhost"
    settings.mqtt.port = 1883
    settings.mqtt.user = "test"
    settings.mqtt.password = "pass"  # noqa: S105
    settings.mqtt.topic_root = "anpr2mqtt"
    settings.homeassistant = HomeAssistantSettings(status_topic="homeassistant/status")
    settings.events = events if events is not None else []
    settings.cameras = []
    settings.ocr = Mock()
    settings.image = Mock()
    settings.dvla = Mock()
    settings.dvla.api_key = None
    settings.tracker = Mock()
    settings.tracker.data_dir = Path("/tmp/tracker_test")  # noqa: S108
    return settings


def test_main_loop_minimal() -> None:
    """main_loop with no events, observer exits immediately."""
    mock_settings = _make_mock_settings()
    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()

    mock_observer.start.assert_called_once()
    mock_observer.stop.assert_called_once()


def test_main_loop_mqtt_protocol_31() -> None:
    mock_settings = _make_mock_settings(protocol="3.1")
    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()


def test_main_loop_mqtt_protocol_5() -> None:
    mock_settings = _make_mock_settings(protocol="5")
    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()


def test_main_loop_mqtt_protocol_unknown() -> None:
    mock_settings = _make_mock_settings(protocol="2.0")
    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()


def test_main_loop_mqtt_connect_fails() -> None:
    """main_loop exits with sys.exit if MQTT connection raises."""
    mock_settings = _make_mock_settings()
    mock_client = Mock()
    mock_client.connect.side_effect = ConnectionRefusedError("refused")

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        pytest.raises(SystemExit) as exc_info,
    ):
        main_loop()
    assert exc_info.value.code == -500


def test_main_loop_with_events(tmp_path: Path) -> None:
    """main_loop with one event schedules a watchdog handler."""
    from anpr2mqtt.settings import CameraSettings, DVLASettings, EventSettings, ImageSettings, OCRSettings, TrackerSettings

    event_config = EventSettings(
        camera="cam1",
        event="anpr",
        watch_path=tmp_path,
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg)"),
        ocr_field_ids=[],
    )
    mock_settings = _make_mock_settings(events=[event_config])
    mock_settings.cameras = [CameraSettings(name="cam1")]
    mock_settings.ocr = OCRSettings()
    mock_settings.image = ImageSettings()
    mock_settings.dvla = DVLASettings()
    mock_settings.tracker = TrackerSettings(data_dir=tmp_path)
    mock_settings.homeassistant.image_entity = True
    mock_settings.homeassistant.camera_entity = True

    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()

    mock_observer.schedule.assert_called_once()


def test_main_loop_with_event_no_matching_camera(tmp_path: Path) -> None:
    """Event with camera not in cameras list creates a default CameraSettings."""
    from anpr2mqtt.settings import DVLASettings, EventSettings, ImageSettings, OCRSettings, TrackerSettings

    event_config = EventSettings(
        camera="unknown_cam",
        event="anpr",
        watch_path=tmp_path,
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VD)\.(?P<ext>jpg)"),
        ocr_field_ids=[],
    )
    mock_settings = _make_mock_settings(events=[event_config])
    mock_settings.cameras = []
    mock_settings.ocr = OCRSettings()
    mock_settings.image = ImageSettings()
    mock_settings.dvla = DVLASettings()
    mock_settings.tracker = TrackerSettings(data_dir=tmp_path)
    mock_settings.homeassistant.image_entity = False
    mock_settings.homeassistant.camera_entity = False

    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()

    mock_observer.schedule.assert_called_once()


def test_main_loop_observer_exception() -> None:
    """main_loop handles exception in observer loop gracefully."""
    mock_settings = _make_mock_settings()
    mock_client = Mock()
    mock_observer = Mock()
    mock_observer.is_alive.side_effect = RuntimeError("observer error")

    with (
        patch("anpr2mqtt.app.Settings", return_value=mock_settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=mock_client),
        patch("anpr2mqtt.app.Observer", return_value=mock_observer),
    ):
        main_loop()

    mock_observer.stop.assert_called_once()
    mock_observer.join.assert_called()
