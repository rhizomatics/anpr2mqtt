import datetime as dt
import json
import re
from pathlib import Path
from unittest.mock import ANY, Mock, call, patch

from PIL import Image

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.event_handler import EventHandler, examine_file, process_image, scan_ocr_fields
from anpr2mqtt.settings import (
    EventSettings,
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
                        "vehicle_direction": "Forward",
                        "event_image_url": "http://127.0.0.1/images/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                        "file_path": "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                        "orig_target": "B4DM3N",
                        "ignore": False,
                        "known": False,
                        "dangerous": False,
                        "priority": "high",
                        "description": "Unknown vehicle",
                        "previous_sightings": 0,
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
    mock_api.lookup.return_value = {"make": "FORD", "colour": "BLUE"}
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


def test_track_target_new(event_handler: EventHandler) -> None:
    count, last = event_handler.track_target("TEST123", "plate", dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    assert count == 0
    assert last is None


def test_track_target_existing(event_handler: EventHandler) -> None:
    ts1 = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    ts2 = dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    event_handler.track_target("TEST456", "plate", ts1)
    count, last = event_handler.track_target("TEST456", "plate", ts2)
    assert count == 1
    assert last == ts1


def test_track_target_no_timestamp(event_handler: EventHandler) -> None:
    count, _last = event_handler.track_target("UNKNOWN", "plate", None)
    assert count == 0


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
