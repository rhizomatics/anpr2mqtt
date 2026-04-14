import datetime as dt
import json
import re
from pathlib import Path
from unittest.mock import ANY, Mock, call, patch

from PIL import Image
from pytest_mock import MockerFixture

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.event_handler import EventHandler, _compute_time_analysis, examine_file, process_image, scan_ocr_fields
from anpr2mqtt.settings import (
    AutoClearSettings,
    DimensionSettings,
    DVLASettings,
    EventSettings,
    HomeAssistantSettings,
    OCRFieldSettings,
    OCRSettings,
    TargetSettings,
)


def test_eventhandler_handles_reg_plate_event(event_handler: EventHandler) -> None:
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    event_handler.publisher.client.publish.assert_has_calls(  # type: ignore[attr-defined]
        [
            call(
                "test/topic",
                payload=json.dumps(
                    {
                        "target": "B4DM3N",
                        "target_type": "plate",
                        "plate": "B4DM3N",
                        "event": "unit_testing",
                        "camera": "test_cam",
                        "area": None,
                        "live_url": None,
                        "reg_info": None,
                        "history": {
                            "previous_sightings": 0,
                            "last_seen": None,
                            "hourly_counts": {},
                            "earliest_time": None,
                            "latest_time": None,
                            "within_time_range": None,
                        },
                        "vehicle_direction": "Forward",
                        "event_image_url": "http://127.0.0.1/images/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                        "file_path": "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                        "orig_target": "B4DM3N",
                        "ignore": False,
                        "known": False,
                        "dangerous": False,
                        "priority": "high",
                        "description": "Unknown vehicle",
                        "event_time": "2025-06-02T10:30:45.000407+00:00",
                        "image_event": "VEHICLE_DETECTION",
                        "ext": "jpg",
                        "image_size": 123445,
                    }
                ),
                qos=0,
                retain=True,
            ),
            call("test/images", payload=ANY, qos=0, retain=True),
        ],
        any_order=True,
    )
    sightings_db_path: Path = event_handler.tracker_config.data_dir / "plate" / "B4DM3N.json"
    assert sightings_db_path.exists()
    with sightings_db_path.open("r") as f:
        sightings = json.load(f)
        assert sightings == ["2025-06-02T10:30:45.000407+00:00"]


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
                "plate": None,
                "event": "unit_testing",
                "camera": "test_cam",
                "area": None,
                "live_url": None,
                "reg_info": None,
                "history": None,
                "vehicle_direction": "Unknown",
                "event_image_url": "http://127.0.0.1/images/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg",
                "file_path": "fixtures/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg",
            }
        ),
        qos=0,
        retain=True,
    )


def test_corrections_unknown(event_handler: EventHandler) -> None:
    results = event_handler.classify_target("PK12TST")
    assert results == {
        "dangerous": False,
        "description": "Unknown vehicle",
        "ignore": False,
        "known": False,
        "priority": "high",
        "orig_target": "PK12TST",
        "target": "PK12TST",
    }


def test_corrections_gangsta(event_handler: EventHandler) -> None:
    event_handler.target_config = TargetSettings(dangerous={"PK12TST": "Local dodgy man"})
    results = event_handler.classify_target("PK12TST")
    assert results == {
        "dangerous": True,
        "description": "Local dodgy man",
        "ignore": False,
        "known": False,
        "priority": "critical",
        "orig_target": "PK12TST",
        "target": "PK12TST",
    }


def test_corrections_known(event_handler: EventHandler) -> None:
    event_handler.target_config = TargetSettings(known={"PK12TST": "Postie"})
    results = event_handler.classify_target("PK12TST")
    assert results == {
        "dangerous": False,
        "description": "Postie",
        "ignore": False,
        "known": True,
        "priority": "medium",
        "orig_target": "PK12TST",
        "target": "PK12TST",
    }


def test_corrections_known_with_correction(event_handler: EventHandler) -> None:
    event_handler.target_config = TargetSettings(known={"PK12TST": "Postie"}, correction={"PK12TST": ["P12TST"]})

    results = event_handler.classify_target("P12TST")
    assert results == {
        "dangerous": False,
        "description": "Postie",
        "ignore": False,
        "known": True,
        "priority": "medium",
        "orig_target": "P12TST",
        "target": "PK12TST",
    }


def test_corrections_ignore(event_handler: EventHandler) -> None:
    event_handler.target_config = TargetSettings(ignore=[".*TST"])
    results = event_handler.classify_target("PK12TST")
    assert results == {
        "dangerous": False,
        "description": "Ignored",
        "ignore": True,
        "known": False,
        "priority": "low",
        "orig_target": "PK12TST",
        "target": "PK12TST",
    }


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
    event_handler.target_config = TargetSettings(ignore=[r"B4DM3N"])
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    # publish should be called 0 times since we skip ignored targets
    event_handler.publisher.client.publish.assert_not_called()  # type: ignore[attr-defined]


def test_on_closed_with_api_client(event_handler: EventHandler) -> None:
    mock_api = Mock()
    mock_api.lookup.return_value = {"plate": {"make": "FORD", "colour": "BLUE"}}
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


def test_on_closed_known_target_skips_api(event_handler: EventHandler) -> None:
    mock_api = Mock()
    event_handler.api_client = mock_api
    event_handler.target_config = TargetSettings(known={"B4DM3N": "My car"})
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


# --- track_target ---


# --- _compute_time_analysis ---


def test_time_analysis_no_history() -> None:
    result = _compute_time_analysis([], dt.datetime(2025, 6, 2, 10, 30, tzinfo=dt.UTC))
    assert result["previous_sightings"] == 0
    assert result["last_seen"] is None
    assert result["hourly_counts"] == {}
    assert result["earliest_time"] is None
    assert result["latest_time"] is None
    assert result["within_time_range"] is None


def test_time_analysis_no_current_dt() -> None:
    sightings = ["2025-06-02T07:30:00+00:00", "2025-06-02T09:15:00+00:00"]
    result = _compute_time_analysis(sightings, None)
    assert result["previous_sightings"] == 2
    assert result["last_seen"] == "2025-06-02T09:15:00+00:00"
    assert result["within_time_range"] is None
    assert result["earliest_time"] == "07:30:00"
    assert result["latest_time"] == "09:15:00"


def test_time_analysis_hourly_counts() -> None:
    sightings = [
        "2025-06-01T08:00:00+00:00",
        "2025-06-02T08:30:00+00:00",
        "2025-06-03T14:00:00+00:00",
    ]
    result = _compute_time_analysis(sightings, dt.datetime(2025, 6, 4, 8, 0, tzinfo=dt.UTC))
    assert result["hourly_counts"][8] == 2
    assert result["hourly_counts"][14] == 1
    assert sum(result["hourly_counts"].values()) == 3


def test_time_analysis_within_range() -> None:
    sightings = ["2025-06-02T07:00:00+00:00", "2025-06-02T09:00:00+00:00"]
    result = _compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 8, 0, tzinfo=dt.UTC))
    assert result["earliest_time"] == "07:00:00"
    assert result["latest_time"] == "09:00:00"
    assert result["within_time_range"] is True


def test_time_analysis_outside_range() -> None:
    sightings = ["2025-06-02T07:00:00+00:00", "2025-06-02T09:00:00+00:00"]
    result = _compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 22, 0, tzinfo=dt.UTC))
    assert result["within_time_range"] is False


def test_time_analysis_at_boundary() -> None:
    # Exactly at earliest or latest is within range
    sightings = ["2025-06-02T07:00:00+00:00", "2025-06-02T09:00:00+00:00"]
    at_earliest = _compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 7, 0, tzinfo=dt.UTC))
    at_latest = _compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 9, 0, tzinfo=dt.UTC))
    assert at_earliest["within_time_range"] is True
    assert at_latest["within_time_range"] is True


def test_time_analysis_ignores_bad_entries() -> None:
    sightings = ["2025-06-02T08:00:00+00:00", "not-a-timestamp", "also-bad"]
    result = _compute_time_analysis(sightings, dt.datetime(2025, 6, 3, 8, 0, tzinfo=dt.UTC))
    assert result["hourly_counts"][8] == 1
    assert sum(result["hourly_counts"].values()) == 1


def test_track_target_time_analysis_populated(event_handler: EventHandler) -> None:
    ts1 = dt.datetime(2025, 6, 1, 8, 0, tzinfo=dt.UTC)
    ts2 = dt.datetime(2025, 6, 2, 14, 0, tzinfo=dt.UTC)
    ts3 = dt.datetime(2025, 6, 3, 10, 0, tzinfo=dt.UTC)
    event_handler.track_target("TIMETEST", "plate", ts1)
    event_handler.track_target("TIMETEST", "plate", ts2)
    analysis = event_handler.track_target("TIMETEST", "plate", ts3)
    assert analysis["previous_sightings"] == 2
    assert analysis["last_seen"] == ts2.isoformat()
    assert analysis["hourly_counts"][8] == 1
    assert analysis["hourly_counts"][14] == 1
    assert analysis["earliest_time"] == "08:00:00"
    assert analysis["latest_time"] == "14:00:00"
    assert analysis["within_time_range"] is True  # 10:00 is between 08:00 and 14:00


def test_track_target_new(event_handler: EventHandler) -> None:
    result = event_handler.track_target("TEST123", "plate", dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    assert result["previous_sightings"] == 0
    assert result["last_seen"] is None


def test_track_target_existing(event_handler: EventHandler) -> None:
    ts1 = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    ts2 = dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    event_handler.track_target("TEST456", "plate", ts1)
    result = event_handler.track_target("TEST456", "plate", ts2)
    assert result["previous_sightings"] == 1
    assert result["last_seen"] == ts1.isoformat()


def test_track_target_no_timestamp(event_handler: EventHandler) -> None:
    result = event_handler.track_target("UNKNOWN", "plate", None)
    assert result["previous_sightings"] == 0


# --- classify_target: no target_config ---


def test_classify_target_no_config(event_handler: EventHandler) -> None:
    event_handler.target_config = None
    result = event_handler.classify_target("AB12CDE")
    assert result["target"] == "AB12CDE"
    assert result["known"] is False


def test_classify_target_none_target(event_handler: EventHandler) -> None:
    result = event_handler.classify_target(None)
    assert result["target"] is None
    assert result["known"] is False


def test_classify_target_dangerous_no_description(event_handler: EventHandler) -> None:
    event_handler.target_config = TargetSettings(dangerous={"AB12CDE": None})
    result = event_handler.classify_target("AB12CDE")
    assert result["dangerous"] is True
    assert result["description"] == "Potential threat"


def test_classify_target_known_no_description(event_handler: EventHandler) -> None:
    event_handler.target_config = TargetSettings(known={"AB12CDE": None})
    result = event_handler.classify_target("AB12CDE")
    assert result["known"] is True
    assert result["description"] == "Known"


# --- autoclear ---


def _set_autoclear(handler: EventHandler, **kwargs: object) -> None:
    handler.event_config = handler.event_config.model_copy(
        update={"autoclear": AutoClearSettings(**kwargs)}  # type:ignore[arg-type]
    )


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
        event_handler.state_topic, target=None, event_config=event_handler.event_config, camera=event_handler.camera
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
    with patch("anpr2mqtt.event_handler.threading.Timer") as mock_timer_cls:
        event_handler._schedule_autoclear()
    mock_timer_cls.assert_not_called()


def test_schedule_autoclear_starts_timer_with_correct_delay(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=120)
    with patch("anpr2mqtt.event_handler.threading.Timer") as mock_timer_cls:
        mock_timer = Mock()
        mock_timer_cls.return_value = mock_timer
        event_handler._schedule_autoclear()
    mock_timer_cls.assert_called_once_with(120, event_handler._do_autoclear)
    mock_timer.start.assert_called_once()


def test_schedule_autoclear_cancels_previous_timer(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=60)
    first_timer = Mock()
    event_handler._autoclear_timer = first_timer
    with patch("anpr2mqtt.event_handler.threading.Timer") as mock_timer_cls:
        mock_timer_cls.return_value = Mock()
        event_handler._schedule_autoclear()
    first_timer.cancel.assert_called_once()


def test_schedule_autoclear_timer_is_daemon(event_handler: EventHandler) -> None:
    _set_autoclear(event_handler, enabled=True, post_event=10)
    with patch("anpr2mqtt.event_handler.threading.Timer") as mock_timer_cls:
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


# --- classify_target: fuzzy matching via auto_match_tolerance ---


def test_fuzzy_match_known_within_tolerance(event_handler: EventHandler) -> None:
    # "AB12CDF" is distance 1 from "AB12CDE"
    event_handler.target_config = TargetSettings(known={"AB12CDE": "Alice"}, auto_match_tolerance=1)
    result = event_handler.classify_target("AB12CDF")
    assert result["known"] is True
    assert result["description"] == "Alice"
    assert result["priority"] == "medium"


def test_fuzzy_match_known_beyond_tolerance(event_handler: EventHandler) -> None:
    # "AB12CXX" is distance 2 from "AB12CDE", tolerance is 1
    event_handler.target_config = TargetSettings(known={"AB12CDE": "Alice"}, auto_match_tolerance=1)
    result = event_handler.classify_target("AB12CXX")
    assert result["known"] is False
    assert result["priority"] == "high"


def test_fuzzy_match_known_disabled(event_handler: EventHandler) -> None:
    # tolerance=0 means only exact matches; "AB12CDF" must not match "AB12CDE"
    event_handler.target_config = TargetSettings(known={"AB12CDE": "Alice"}, auto_match_tolerance=0)
    result = event_handler.classify_target("AB12CDF")
    assert result["known"] is False


def test_fuzzy_match_dangerous_within_tolerance(event_handler: EventHandler) -> None:
    # "PK12TSX" is distance 1 from "PK12TST"
    event_handler.target_config = TargetSettings(dangerous={"PK12TST": "Suspect"}, auto_match_tolerance=1)
    result = event_handler.classify_target("PK12TSX")
    assert result["dangerous"] is True
    assert result["description"] == "Suspect"
    assert result["priority"] == "critical"


def test_fuzzy_match_dangerous_beyond_tolerance(event_handler: EventHandler) -> None:
    # "PK12XXX" is distance 3 from "PK12TST", tolerance is 1
    event_handler.target_config = TargetSettings(dangerous={"PK12TST": "Suspect"}, auto_match_tolerance=1)
    result = event_handler.classify_target("PK12XXX")
    assert result["dangerous"] is False


def test_fuzzy_match_picks_closest_known(event_handler: EventHandler) -> None:
    # "AB12CDF" is distance 1 from "AB12CDE" and distance 2 from "AB12CDZ"
    event_handler.target_config = TargetSettings(
        known={"AB12CDE": "Alice", "AB12CDZ": "Bob"},
        auto_match_tolerance=2,
    )
    result = event_handler.classify_target("AB12CDF")
    assert result["known"] is True
    assert result["description"] == "Alice"


def test_fuzzy_match_exact_preferred(event_handler: EventHandler) -> None:
    # Exact match should win even when tolerance > 0
    event_handler.target_config = TargetSettings(known={"AB12CDE": "Exact match"}, auto_match_tolerance=2)
    result = event_handler.classify_target("AB12CDE")
    assert result["known"] is True
    assert result["description"] == "Exact match"


def test_fuzzy_match_both_known_and_dangerous(event_handler: EventHandler) -> None:
    # A plate close to entries in both lists should get both flags
    event_handler.target_config = TargetSettings(
        known={"AB12CDE": "Alice"},
        dangerous={"AB12CDX": "Threat"},
        auto_match_tolerance=1,
    )
    # "AB12CDF" is distance 1 from both "AB12CDE" and "AB12CDX"
    result = event_handler.classify_target("AB12CDF")
    assert result["known"] is True
    assert result["dangerous"] is True


# --- EventHandler.__init__ branches ---


def test_event_handler_init_with_dvla_api_key(tmp_path: Path) -> None:
    from anpr2mqtt.hass import HomeAssistantPublisher
    from anpr2mqtt.settings import CameraSettings, ImageSettings, OCRSettings, TrackerSettings

    with patch("anpr2mqtt.event_handler.DVLAClient") as mock_dvla_cls:
        handler = EventHandler(
            HomeAssistantPublisher(Mock(), HomeAssistantSettings(status_topic="t")),
            state_topic="t/state",
            image_topic="t/image",
            dvla_config=DVLASettings(api_key="testkey"),
            target_config=TargetSettings(),
            camera=CameraSettings(name="cam"),
            image_config=ImageSettings(),
            tracker_config=TrackerSettings(data_dir=tmp_path),
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
    event_handler.target_config = TargetSettings(
        correction={"CORRECTED": [r"B4DM3N"]},
        known={"CORRECTED": "My car"},
        auto_match_tolerance=0,
    )
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


# --- track_target: exception path ---


def test_track_target_exception(event_handler: EventHandler, tmp_path: Path) -> None:
    """json.load raises → exception is caught and logged (lines 225-226)."""
    target_dir = tmp_path / "plate"
    target_dir.mkdir()
    bad_file = target_dir / "BADPLATE.json"
    bad_file.write_text("not valid json")
    result = event_handler.track_target("BADPLATE", "plate", dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    assert result == {}


# --- scan_ocr_fields: uncovered branches ---


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
