import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import ANY, Mock, patch

from PIL import Image
from pytest_mock import MockerFixture

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.event_handler import EventHandler, examine_file, process_image, scan_ocr_fields
from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import (
    AutoClearSettings,
    CameraSettings,
    DimensionSettings,
    DVLASettings,
    EventSettings,
    HomeAssistantSettings,
    ImageSettings,
    OCRFieldSettings,
    OCRSettings,
    Target,
    TargetGroup,
    TargetSettings,
)
from anpr2mqtt.tracker import Tracker


def test_eventhandler_handles_reg_plate_event(event_handler: EventHandler, tracker: Tracker) -> None:
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    state_call = next(
        c
        for c in event_handler.publisher.client.publish.call_args_list  # type: ignore[attr-defined]
        if c.args[0] == "test/topic"
    )
    payload = json.loads(state_call.kwargs["payload"])
    assert payload["target"] == "B4DM3N"
    assert payload["orig_target"] == "B4DM3N"
    assert payload["known"] is False
    assert payload["dangerous"] is False
    assert payload["ignore"] is False
    assert payload["description"] == "Unknown vehicle"
    assert payload["entity_id"] is None
    assert payload["event"] == "unit_testing"
    assert payload["camera"] == "test_cam"
    assert payload["reg_info"] is None
    assert payload["history"]["previous_sightings"] == 0
    assert payload["image_event"] == "VEHICLE_DETECTION"
    assert payload["ext"] == "jpg"
    assert payload["image_size"] == 123445
    assert payload["plate"] == "B4DM3N"

    event_handler.publisher.client.publish.assert_any_call(  # type: ignore[attr-defined]
        "test/images", payload=ANY, qos=0, retain=True
    )
    sightings_db_path: Path = tracker.tracker_config.data_dir / "plate" / "B4DM3N.json"
    assert sightings_db_path.exists()
    with sightings_db_path.open("r") as f:
        sightings = json.load(f)
        assert sightings == ["2025-06-02T10:30:45.407000+00:00"]


def test_eventhandler_copes_with_malformed_reg_plate_event(event_handler: EventHandler) -> None:
    event = Mock()
    event.src_path = "fixtures/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    event_handler.publisher.client.publish.assert_called_once_with(  # type: ignore[attr-defined]
        "test/topic",
        payload=json.dumps(
            {
                "target": None,
                "target_type": "plate",
                "description": "Unknown vehicle",
                "plate": None,
                "event": "unit_testing",
                "camera": "test_cam",
                "area": None,
                "live_url": None,
                "linked_cameras": {},
                "reg_info": None,
                "history": None,
                "vehicle_direction": "Unknown",
                "event_image_url": "http://127.0.0.1/images/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg",
                "file_path": "fixtures/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg",
                "source": "filesystem",
            }
        ),
        qos=0,
        retain=True,
    )


def test_process_image(tmp_path: Path) -> None:
    fixture_image_path = Path("fixtures") / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    image: Image.Image | None = process_image(
        fixture_image_path,
        ImageInfo("", "anpr", dt.datetime.now(tz=dt.UTC), size=fixture_image_path.stat().st_size, ext="jpeg"),
        jpeg_opts={"quality": 30, "progressive": True, "optimize": True},
        png_opts={},
    )
    assert image is not None
    image.save(tmp_path / "test.jpeg", "jpeg")
    reimage = Image.open(tmp_path / "test.jpeg")
    assert reimage is not None


def test_process_image_png(tmp_path: Path) -> None:
    img = Image.new("RGB", (100, 100), color="blue")
    png_path = tmp_path / "test.png"
    img.save(png_path, "png")
    image_info = ImageInfo("", "anpr", dt.datetime.now(tz=dt.UTC), size=png_path.stat().st_size, ext="png")
    result = process_image(png_path, image_info, jpeg_opts={}, png_opts={"optimize": True})
    assert result is not None


def test_process_image_no_opts() -> None:
    fixture_image_path = Path("fixtures") / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    image_info = ImageInfo("", "anpr", dt.datetime.now(tz=dt.UTC), size=fixture_image_path.stat().st_size, ext="jpg")
    result = process_image(fixture_image_path, image_info, jpeg_opts={}, png_opts={})
    assert result is not None


def test_process_image_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.jpg"
    image_info = ImageInfo("", "anpr", dt.datetime.now(tz=dt.UTC), size=0, ext="jpg")
    result = process_image(missing, image_info, jpeg_opts={}, png_opts={})
    assert result is None


def test_process_image_broken_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    with broken.open("w") as f:
        f.write("JPG")
    image_info = ImageInfo("", "anpr", dt.datetime.now(tz=dt.UTC), size=0, ext="jpg")
    result = process_image(broken, image_info, jpeg_opts={}, png_opts={})
    assert result is None


# --- examine_file ---


def test_examine_file_valid() -> None:
    fixture = Path("fixtures") / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    pattern = re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)")
    result = examine_file(fixture, pattern)
    assert result is not None
    assert result.target == "B4DM3N"
    assert result.event == "VEHICLE_DETECTION"
    assert result.ext == "jpg"


def test_examine_file_no_match(tmp_path: Path) -> None:
    f = tmp_path / "not_matching_name.jpg"
    f.write_bytes(b"fake")
    pattern = re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg)")
    result = examine_file(f, pattern)
    assert result is None


def test_examine_file_no_target(tmp_path: Path) -> None:
    # pattern matches but has no 'target' group
    f = tmp_path / "20250602103045407_VEHICLE_DETECTION.jpg"
    f.write_bytes(b"fake")
    pattern = re.compile(r"(?P<dt>[0-9]{17})_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg)")
    result = examine_file(f, pattern)
    assert result is None


def test_examine_file_no_ext_group(tmp_path: Path) -> None:
    # ext group not present in pattern; falls back to splitting file name
    f = tmp_path / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    f.write_bytes(b"fake")
    pattern = re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.jpg")
    result = examine_file(f, pattern)
    assert result is not None
    assert result.target == "B4DM3N"


# --- scan_ocr_fields ---


def test_scan_ocr_fields_no_image() -> None:
    event_config = EventSettings(camera="cam1", event="anpr", ocr_field_ids=["hik_direction"])
    ocr_config = OCRSettings()
    result = scan_ocr_fields(None, event_config, ocr_config)
    assert result == {"vehicle_direction": "Unknown"}


def test_scan_ocr_fields_no_fields() -> None:
    event_config = EventSettings(camera="cam1", event="anpr", ocr_field_ids=[])
    ocr_config = OCRSettings()
    img = Image.new("RGB", (100, 100))
    result = scan_ocr_fields(img, event_config, ocr_config)
    assert result == {}


def test_scan_ocr_fields_unknown_field_id() -> None:
    event_config = EventSettings(camera="cam1", event="anpr", ocr_field_ids=["nonexistent"])
    ocr_config = OCRSettings()
    img = Image.new("RGB", (100, 100))
    result = scan_ocr_fields(img, event_config, ocr_config)
    assert result == {}


def test_scan_ocr_fields_with_real_image() -> None:
    fixture = Path("fixtures") / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    img = Image.open(fixture)
    event_config = EventSettings(camera="cam1", event="anpr", ocr_field_ids=["hik_direction"])
    ocr_config = OCRSettings()
    result = scan_ocr_fields(img, event_config, ocr_config)
    assert "vehicle_direction" in result


# --- on_created ---


def test_on_created_skips_directory(event_handler: EventHandler) -> None:
    event = Mock()
    event.event_type = "created"
    event.is_directory = True
    event_handler.on_created(event)
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_created_skips_non_created_event(event_handler: EventHandler) -> None:
    event = Mock()
    event.event_type = "modified"
    event.is_directory = False
    event_handler.on_created(event)
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_created_valid(event_handler: EventHandler) -> None:
    event = Mock()
    event.event_type = "created"
    event.is_directory = False
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event_handler.on_created(event)
    # on_created just logs, doesn't publish
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


# --- on_closed edge cases ---


def test_on_closed_skips_directory(event_handler: EventHandler) -> None:
    event = Mock()
    event.event_type = "closed"
    event.is_directory = True
    event_handler.on_closed(event)
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_closed_skips_non_closed_event(event_handler: EventHandler) -> None:
    event = Mock()
    event.event_type = "modified"
    event.is_directory = False
    event_handler.on_closed(event)
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_closed_empty_file(event_handler: EventHandler, tmp_path: Path) -> None:
    empty_file = tmp_path / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    empty_file.write_bytes(b"")
    event = Mock()
    event.event_type = "closed"
    event.is_directory = False
    event.src_path = str(empty_file)
    event_handler.on_closed(event)
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_closed_no_image_url_base(event_handler: EventHandler) -> None:
    event_handler.event_config = EventSettings(
        camera="test_cam",
        event="unit_testing",
        image_url_base=None,
        image_name_re=re.compile(
            r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"
        ),
        watch_path=Path("/fixtures"),
        ocr_field_ids=[],
    )
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    _args, kwargs = event_handler.publisher.client.publish.call_args_list[0]  # type: ignore[attr-defined]
    payload = json.loads(kwargs["payload"])
    assert "event_image_url" not in payload


def test_on_closed_ignored_target(event_handler: EventHandler) -> None:
    event_handler.tracker.target_config = TargetSettings(ignore=[r"B4DM3N"])
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    # publish should be called 0 times since we skip ignored targets
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_closed_with_api_client(event_handler: EventHandler) -> None:
    mock_api = Mock()
    mock_api.lookup.return_value = {"plate": {"make": "FORD", "colour": "BLUE"}, "success": True, "description": "Blue Ford"}
    event_handler.api_client = mock_api
    event_handler.event_config = EventSettings(
        camera="test_cam",
        event="unit_testing",
        image_url_base="http://127.0.0.1/images",
        image_name_re=re.compile(
            r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"
        ),
        watch_path=Path("/fixtures"),
        ocr_field_ids=[],
        target_type="plate",
    )
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    mock_api.lookup.assert_called_once_with("B4DM3N")
    _args, kwargs = event_handler.publisher.client.publish.call_args_list[0]  # type: ignore[attr-defined]
    payload = json.loads(kwargs["payload"])
    assert payload["reg_info"] == {"make": "FORD", "colour": "BLUE"}
    assert payload["description"] == "Blue Ford"


def test_on_closed_known_target_skips_api(event_handler: EventHandler) -> None:
    mock_api = Mock()
    event_handler.api_client = mock_api
    event_handler.tracker.target_config = TargetSettings(
        groups=[TargetGroup(name="known", members=[Target(id="B4DM3N", description="My car")])]
    )

    event_handler.event_config = EventSettings(
        camera="test_cam",
        event="unit_testing",
        image_url_base="http://127.0.0.1/images",
        image_name_re=re.compile(
            r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"
        ),
        watch_path=Path("/fixtures"),
        ocr_field_ids=[],
        target_type="plate",
    )
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    mock_api.lookup.assert_not_called()


def test_on_closed_image_format_png(event_handler: EventHandler, tmp_path: Path) -> None:
    img = Image.new("RGB", (100, 100), color="green")
    fname = "20250602103045407_B4DM3N_VEHICLE_DETECTION.png"
    img_path = tmp_path / fname
    img.save(img_path, "png")
    event_handler.event_config = EventSettings(
        camera="test_cam",
        event="unit_testing",
        image_url_base=None,
        image_name_re=re.compile(
            r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"
        ),
        watch_path=tmp_path,
        ocr_field_ids=[],
    )
    event = Mock()
    event.src_path = str(img_path)
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    # Should publish state + image
    assert event_handler.publisher.client.publish.call_count >= 1  # type: ignore[attr-defined]


def test_on_closed_exception_path(event_handler: EventHandler) -> None:
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    with patch("anpr2mqtt.event_handler.examine_file", side_effect=RuntimeError("boom")):
        event_handler.on_closed(event)
    # Should have published an error state
    _args, kwargs = event_handler.publisher.client.publish.call_args  # type: ignore[attr-defined]
    payload = json.loads(kwargs["payload"])
    assert "error" in payload


# --- autoclear ---


def _set_autoclear(handler: EventHandler, **kwargs: object) -> None:
    handler.event_config = handler.event_config.model_copy(update={"autoclear": AutoClearSettings(**kwargs)})


def test_do_autoclear_sensor_only(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, state=True, image=False)
    event_handler._do_autoclear()
    event_handler.publisher.post_state_message = Mock()  # type: ignore[method-assign]
    publisher_mock: Mock = event_handler.publisher.client  # type: ignore[assignment]
    # state topic published, image topic not touched
    calls = [c for c in publisher_mock.publish.call_args_list if c.args[0] == "test/images"]
    assert calls == []


def test_do_autoclear_sensor_clears_state(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, state=True, image=False)
    with (
        patch.object(event_handler.publisher, "post_state_message") as mock_state,
        patch.object(event_handler.publisher, "post_image_message") as mock_image,
    ):
        event_handler._do_autoclear()
    mock_state.assert_called_once_with(
        event_handler.state_topic, sighting=None, event_config=event_handler.event_config, camera=event_handler.camera
    )
    mock_image.assert_not_called()


def test_do_autoclear_sensor_false_does_not_clear_state(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, state=False, image=False)
    with (
        patch.object(event_handler.publisher, "post_state_message") as mock_state,
        patch.object(event_handler.publisher, "post_image_message") as mock_image,
    ):
        event_handler._do_autoclear()
    mock_state.assert_not_called()
    mock_image.assert_not_called()


def test_do_autoclear_image_clears_image_topic(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, state=False, image=True)
    with (
        patch.object(event_handler.publisher, "post_state_message") as mock_state,
        patch.object(event_handler.publisher, "post_image_message") as mock_image,
    ):
        event_handler._do_autoclear()
    mock_state.assert_not_called()
    mock_image.assert_called_once_with(event_handler.image_topic, image=None)


def test_schedule_autoclear_disabled_starts_no_timer(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=False)
    with patch("anpr2mqtt.handler_common.threading.Timer") as mock_timer_cls:
        event_handler._schedule_autoclear()
    mock_timer_cls.assert_not_called()


def test_schedule_autoclear_starts_timer_with_correct_delay(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=120)
    with patch("anpr2mqtt.handler_common.threading.Timer") as mock_timer_cls:
        mock_timer = Mock()
        mock_timer_cls.return_value = mock_timer
        event_handler._schedule_autoclear()
    delay = mock_timer_cls.call_args.args[0]
    assert delay == 120
    mock_timer.start.assert_called_once()


def test_schedule_autoclear_cancels_previous_timer(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=60)
    first_timer = Mock()
    event_handler._autoclear_timer._timer = first_timer
    with patch("anpr2mqtt.handler_common.threading.Timer") as mock_timer_cls:
        mock_timer_cls.return_value = Mock()
        event_handler._schedule_autoclear()
    first_timer.cancel.assert_called_once()


def test_schedule_autoclear_timer_is_daemon(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=10)
    with patch("anpr2mqtt.handler_common.threading.Timer") as mock_timer_cls:
        mock_timer = Mock()
        mock_timer_cls.return_value = mock_timer
        event_handler._schedule_autoclear()
    assert mock_timer.daemon is True


def test_on_closed_schedules_autoclear(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=300)
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    with patch.object(event_handler, "_schedule_autoclear") as mock_schedule:
        event_handler.on_closed(event)
    mock_schedule.assert_called_once()


def test_on_closed_no_image_schedules_autoclear(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=300)
    event = Mock()
    event.src_path = "fixtures/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg"
    event.event_type = "closed"
    event.is_directory = False
    with patch.object(event_handler, "_schedule_autoclear") as mock_schedule:
        event_handler.on_closed(event)
    mock_schedule.assert_called_once()


# --- EventHandler.__init__ branches ---


def test_event_handler_init_with_dvla_api_key(tmp_path: Path) -> None:
    from anpr2mqtt.hass import HomeAssistantPublisher
    from anpr2mqtt.settings import CameraSettings, ImageSettings, OCRSettings, TrackerSettings

    with patch("anpr2mqtt.handler_common.DVLAClient") as mock_dvla_cls:
        handler = EventHandler(
            HomeAssistantPublisher(Mock(), HomeAssistantSettings(status_topic="t")),
            state_topic="t/state",
            image_topic="t/image",
            dvla_config=DVLASettings(api_key="testkey"),
            camera=CameraSettings(name="cam"),
            image_config=ImageSettings(),
            tracker=Tracker("testing", TrackerSettings(data_dir=tmp_path)),
            ocr_config=OCRSettings(),
            event_config=EventSettings(camera="cam", event="anpr", watch_path=tmp_path, target_type="plate", ocr_field_ids=[]),
        )
    mock_dvla_cls.assert_called_once()
    assert handler.api_client is mock_dvla_cls.return_value


def test_ignore_directories_property(event_handler: EventHandler) -> None:
    assert event_handler.ignore_directories is True


# --- on_closed: image/format edge cases ---


def test_on_closed_image_process_returns_none(event_handler: EventHandler) -> None:
    """When process_image returns None the image publish is skipped (153->160 branch)."""
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    with patch("anpr2mqtt.event_handler.process_image", return_value=None):
        event_handler.on_closed(event)
    # Only state message published, no image publish
    calls = [c for c in event_handler.publisher.client.publish.call_args_list if c.args[0] == "test/images"]  # type: ignore[attr-defined]
    assert calls == []


def test_on_closed_image_format_none(event_handler: EventHandler) -> None:
    """When image_info.ext is None, img_format is None and image publish is skipped (line 159)."""
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    fake_info = ImageInfo(target="B4DM3N", event="VEHICLE_DETECTION", timestamp=dt.datetime.now(tz=dt.UTC), ext=None, size=100)
    with (
        patch("anpr2mqtt.event_handler.examine_file", return_value=fake_info),
        patch("anpr2mqtt.event_handler.process_image", return_value=Image.new("RGB", (10, 10))),
    ):
        event_handler.on_closed(event)
    calls = [c for c in event_handler.publisher.client.publish.call_args_list if c.args[0] == "test/images"]  # type: ignore[attr-defined]
    assert calls == []


def test_on_closed_correction_changes_target(event_handler: EventHandler) -> None:
    """When correction remaps target, line 120 (target = classification['target']) is hit."""
    event_handler.tracker.target_config = TargetSettings(
        correction={"CORRECTED": [r"B4DM3N"]},
        known={"CORRECTED": Target(id="CORRECTED", description="My car", group="known")},
    )
    event_handler.tracker.auto_match_tolerance = 0
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    _args, kwargs = event_handler.publisher.client.publish.call_args_list[0]  # type: ignore[attr-defined]
    payload = json.loads(kwargs["payload"])
    assert payload["target"] == "CORRECTED"
    assert payload["orig_target"] == "B4DM3N"


# --- process_image: size branch ---


def test_process_image_size_unchanged() -> None:
    """When image_info.size is 0, the size-change logging branch is skipped (329->337)."""
    fixture_image_path = Path("fixtures") / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    image_info = ImageInfo("", "anpr", dt.datetime.now(tz=dt.UTC), size=0, ext="jpg")
    result = process_image(fixture_image_path, image_info, jpeg_opts={"quality": 30}, png_opts={})
    assert result is not None


def _make_event_and_ocr(field: OCRFieldSettings) -> tuple[EventSettings, OCRSettings]:
    event_config = EventSettings(camera="cam", event="anpr", ocr_field_ids=["myfield"])
    ocr_config = OCRSettings(fields={"myfield": field})
    return event_config, ocr_config


def test_scan_ocr_fields_no_crop_no_invert(mocker: MockerFixture) -> None:
    """Field with crop=None and invert=False exercises the no-crop/no-invert branches."""
    mocker.patch("anpr2mqtt.event_handler.pytesseract.image_to_string", return_value="")
    field = OCRFieldSettings(label="test_field", crop=None, invert=False, values=None)
    event_config, ocr_config = _make_event_and_ocr(field)
    result = scan_ocr_fields(Image.new("RGB", (100, 100)), event_config, ocr_config)
    assert "test_field" in result


def test_scan_ocr_fields_empty_tesseract_output(mocker: MockerFixture) -> None:
    """Empty string from tesseract → parsed=[] → 'Unparsable field' warning (lines 422-423)."""
    mocker.patch("anpr2mqtt.event_handler.pytesseract.image_to_string", return_value="")
    field = OCRFieldSettings(label="dir", crop=DimensionSettings(x=0, y=0, h=10, w=10), invert=True, values=["Forward"])
    event_config, ocr_config = _make_event_and_ocr(field)
    result = scan_ocr_fields(Image.new("RGB", (100, 100)), event_config, ocr_config)
    assert result["dir"] == "Unknown"


def test_scan_ocr_fields_correction_match(mocker: MockerFixture) -> None:
    """Candidate not in correction keys but matches a pattern → candidate is remapped (lines 428-431)."""
    mocker.patch("anpr2mqtt.event_handler.pytesseract.image_to_string", return_value="label: Fo rd")
    field = OCRFieldSettings(
        label="dir",
        crop=DimensionSettings(x=0, y=0, h=10, w=10),
        invert=False,
        correction={"Forward": [re.compile(r"Fo.*rd")]},
        values=["Forward"],
    )
    event_config, ocr_config = _make_event_and_ocr(field)
    result = scan_ocr_fields(Image.new("RGB", (100, 100)), event_config, ocr_config)
    assert result["dir"] == "Forward"


def test_scan_ocr_fields_case_correction(mocker: MockerFixture) -> None:
    """Candidate matches a value case-insensitively → candidate is case-corrected (lines 435-436)."""
    mocker.patch("anpr2mqtt.event_handler.pytesseract.image_to_string", return_value="label: forward")
    field = OCRFieldSettings(label="dir", crop=None, invert=False, values=["Forward"])
    event_config, ocr_config = _make_event_and_ocr(field)
    result = scan_ocr_fields(Image.new("RGB", (100, 100)), event_config, ocr_config)
    assert result["dir"] == "Forward"


def test_scan_ocr_fields_unknown_value(mocker: MockerFixture) -> None:
    """Candidate not in allowed values → result set to 'Unknown' (lines 440-441)."""
    mocker.patch("anpr2mqtt.event_handler.pytesseract.image_to_string", return_value="label: GARBAGE")
    field = OCRFieldSettings(label="dir", crop=None, invert=False, values=["Forward", "Reverse"])
    event_config, ocr_config = _make_event_and_ocr(field)
    result = scan_ocr_fields(Image.new("RGB", (100, 100)), event_config, ocr_config)
    assert result["dir"] == "Unknown"


def test_scan_ocr_fields_ocr_exception(mocker: MockerFixture) -> None:
    """Pytesseract raises → exception caught, OCR_ERROR set (lines 445-447)."""
    mocker.patch("anpr2mqtt.event_handler.pytesseract.image_to_string", side_effect=RuntimeError("tesseract gone"))
    field = OCRFieldSettings(label="dir", crop=None, invert=False, values=None)
    event_config, ocr_config = _make_event_and_ocr(field)
    result = scan_ocr_fields(Image.new("RGB", (100, 100)), event_config, ocr_config)
    assert "OCR_ERROR" in result


def test_scan_ocr_fields_image_size_exception() -> None:
    """image.size raises → IMAGE_ERROR set (lines 389-392)."""
    bad_image = Mock()
    bad_image.size = property(lambda _self: (_ for _ in ()).throw(RuntimeError("no size")))

    field = OCRFieldSettings(label="dir", crop=DimensionSettings(x=0, y=0, h=10, w=10), invert=False, values=None)
    event_config, ocr_config = _make_event_and_ocr(field)

    # Trigger via a mock whose .size raises
    broken = Mock(spec=Image.Image)
    type(broken).size = property(lambda _self: (_ for _ in ()).throw(RuntimeError("no size")))
    result = scan_ocr_fields(broken, event_config, ocr_config)
    assert "IMAGE_ERROR" in result


# --- targetless events, such as faces ---

FACE_RE = re.compile(
    r"(?P<ip>[0-9.]+)_(?P<channel>[0-9]+)_(?P<dt>[0-9]{17})_(?P<event>FACE_SNAP|FACE_BACKGROUND)\.(?P<ext>jpg|jpeg)"
)


def _face_handler(tracker: Tracker, secondary_image_topic: str | None = "test/images/face_background") -> EventHandler:
    return EventHandler(
        HomeAssistantPublisher(Mock(), HomeAssistantSettings(status_topic="status_test_topic")),
        state_topic="test/face",
        image_topic="test/images",
        dvla_config=DVLASettings(),
        camera=CameraSettings(name="front"),
        image_config=ImageSettings(),
        tracker=tracker,
        ocr_config=OCRSettings(),
        event_config=EventSettings(
            camera="front",
            event="face",
            target_type="face",
            default_description="Face",
            image_name_re=FACE_RE,
            secondary_image_event="FACE_BACKGROUND",
            watch_path=Path("/fixtures"),
            ocr_field_ids=[],
        ),
        secondary_image_topic=secondary_image_topic,
        event_topic="test/face/event",
    )


def _closed(path: Path) -> Mock:
    event = Mock()
    event.src_path = str(path)
    event.event_type = "closed"
    event.is_directory = False
    return event


def _face_file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    Image.new("RGB", (40, 40), color="grey").save(path, "jpeg")
    return path


def test_face_snap_publishes_event_and_image(tracker: Tracker, tmp_path: Path) -> None:
    handler = _face_handler(tracker)
    handler.on_closed(_closed(_face_file(tmp_path, "10.180.10.20_01_20261120175018129_FACE_SNAP.jpg")))

    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    state_call = next(c for c in publish.call_args_list if c.args[0] == "test/face")
    payload = json.loads(state_call.kwargs["payload"])
    assert payload["target"] is None
    assert payload["target_type"] == "face"
    assert payload["description"] == "Face"
    assert payload["image_event"] == "FACE_SNAP"
    assert payload["event_time"].startswith("2026-11-20T17:50:18.129")
    publish.assert_any_call("test/images", payload=ANY, qos=0, retain=True)
    assert not any(c.args[0] == "test/images/face_background" for c in publish.call_args_list)
    assert not list(tracker.tracker_config.data_dir.rglob("*.json")), "faces aren't tracked as sightings"


def test_face_background_only_updates_its_image(tracker: Tracker, tmp_path: Path) -> None:
    handler = _face_handler(tracker)
    handler.on_closed(_closed(_face_file(tmp_path, "10.180.10.20_01_20261120175018160_FACE_BACKGROUND.jpg")))

    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    publish.assert_called_once_with("test/images/face_background", payload=ANY, qos=0, retain=True)


def test_face_background_ignored_without_secondary_topic(tracker: Tracker, tmp_path: Path) -> None:
    handler = _face_handler(tracker, secondary_image_topic=None)
    handler.on_closed(_closed(_face_file(tmp_path, "10.180.10.20_01_20261120175018160_FACE_BACKGROUND.jpg")))

    handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_face_autoclear_clears_both_images(tracker: Tracker) -> None:
    handler = _face_handler(tracker)
    handler.event_config.autoclear.image = True
    handler._do_autoclear()

    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    publish.assert_any_call("test/images", payload=None, qos=0, retain=True)
    publish.assert_any_call("test/images/face_background", payload=None, qos=0, retain=True)


def test_examine_file_without_target_when_not_required(tmp_path: Path) -> None:
    f = tmp_path / "10.180.10.20_01_20261120175018129_FACE_SNAP.jpg"
    f.write_bytes(b"fake")
    result = examine_file(f, FACE_RE, require_target=False)
    assert result is not None
    assert result.target is None
    assert result.event == "FACE_SNAP"
    assert result.ext == "jpg"


def _face_states(handler: EventHandler) -> list[dict[str, Any]]:
    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    return [json.loads(c.kwargs["payload"]) for c in publish.call_args_list if c.args[0] == "test/face"]


def test_face_within_gap_is_one_event(tracker: Tracker, tmp_path: Path) -> None:
    handler = _face_handler(tracker, secondary_image_topic=None)
    handler.event_config.min_event_gap_seconds = 10
    for name in (
        "10.180.10.40_01_20261125175413139_FACE_SNAP.jpg",
        "10.180.10.40_01_20261125175414335_FACE_SNAP.jpg",
        "10.180.10.40_01_20261125175430000_FACE_SNAP.jpg",
    ):
        handler.on_closed(_closed(_face_file(tmp_path, name)))

    times = [dt.datetime.fromisoformat(state["event_time"]).time() for state in _face_states(handler)]
    assert times == [dt.time(17, 54, 13, 139000), dt.time(17, 54, 30)]


def test_face_without_gap_is_every_image(tracker: Tracker, tmp_path: Path) -> None:
    handler = _face_handler(tracker, secondary_image_topic=None)
    for name in ("10.180.10.40_01_20261125175413139_FACE_SNAP.jpg", "10.180.10.40_01_20261125175414335_FACE_SNAP.jpg"):
        handler.on_closed(_closed(_face_file(tmp_path, name)))

    assert len(_face_states(handler)) == 2


def test_examine_file_reads_milliseconds(tmp_path: Path) -> None:
    f = tmp_path / "10.180.10.40_01_20261125175413139_FACE_SNAP.jpg"
    f.write_bytes(b"fake")
    result = examine_file(f, FACE_RE, require_target=False)
    assert result is not None
    assert result.timestamp.microsecond == 139000


def test_face_fires_event_entity(tracker: Tracker, tmp_path: Path) -> None:
    handler = _face_handler(tracker)
    handler.on_closed(_closed(_face_file(tmp_path, "10.180.10.20_01_20261120175018129_FACE_SNAP.jpg")))
    handler.on_closed(_closed(_face_file(tmp_path, "10.180.10.20_01_20261120175018160_FACE_BACKGROUND.jpg")))

    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    events = [c for c in publish.call_args_list if c.args[0] == "test/face/event"]
    assert len(events) == 1, "only the snap fires the event, not the background"
    assert json.loads(events[0].kwargs["payload"])["event_type"] == "face"
    assert events[0].kwargs["retain"] is False


def test_every_image_counted_even_when_not_published(tracker: Tracker, tmp_path: Path) -> None:
    from anpr2mqtt.image_stats import ImageStats

    handler = _face_handler(tracker)
    handler.publisher.image_stats = ImageStats(tmp_path / "image_stats.json")
    handler.event_config.min_event_gap_seconds = 10
    for name in (
        "10.180.10.20_01_20261120175018129_FACE_SNAP.jpg",
        "10.180.10.20_01_20261120175018160_FACE_BACKGROUND.jpg",
        "10.180.10.20_01_20261120175019000_FACE_SNAP.jpg",
    ):
        handler.on_closed(_closed(_face_file(tmp_path, name)))

    states = _face_states(handler)
    assert [s["images"]["total"] for s in states] == [1, 2, 3]
    assert all(s["event_time"] == states[0]["event_time"] for s in states), "later images only refresh the counts"
    assert states[-1]["images"]["today"] == 3
    assert set(states[-1]["images"]) == {
        "today",
        "today_bytes",
        "this_week",
        "this_week_bytes",
        "total",
        "total_bytes",
        "last_received",
    }, "no camera or overall counts"
    assert states[-1]["images"]["total_bytes"] == sum(p.stat().st_size for p in tmp_path.glob("*.jpg"))
