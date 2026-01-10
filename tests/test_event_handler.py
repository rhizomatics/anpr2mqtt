import datetime as dt
import json
import re
from pathlib import Path
from unittest.mock import ANY, Mock, call

from PIL import Image

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.event_handler import EventHandler, process_image
from anpr2mqtt.settings import DVLASettings, FileSystemSettings, ImageSettings, OCRSettings, PlateSettings, TrackerSettings


def test_eventhandler_handles_reg_plate_event(tmp_path: Path) -> None:
    client = Mock()
    uut = EventHandler(
        client,
        camera="testcam",
        state_topic="test/topic",
        image_topic="test/images",
        dvla_config=DVLASettings(),
        plate_config=PlateSettings(),
        image_config=ImageSettings(),
        tracker_config=TrackerSettings(data_dir=tmp_path),
        ocr_config=OCRSettings(direction_box="850,0,650,30"),
        file_system_config=FileSystemSettings(
            image_url_base="http://127.0.0.1/images",
            image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<plate>[A-Z0-9]+)_VEHICLE_DETECTION\.(?P<ext>jpg|png|gif|jpeg)"),
            watch_path=Path("/fixtures"),
        ),
    )
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    uut.on_closed(event)
    client.publish.assert_has_calls(
        [
            call(
                "test/topic",
                payload=json.dumps(
                    {
                        "plate": "B4DM3N",
                        "vehicle_direction": "Forward",
                        "reg_info": None,
                        "camera": "testcam",
                        "event_image_url": "http://127.0.0.1/images/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                        "file_path": "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                        "orig_plate": "B4DM3N",
                        "ignore": False,
                        "known": False,
                        "dangerous": False,
                        "priority": "high",
                        "description": "Unknown vehicle",
                        "previous_sightings": 0,
                        "event_time": "2025-06-02T10:30:45.000407+00:00",
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
    sightings_db_path: Path = tmp_path / "B4DM3N.json"
    assert sightings_db_path.exists()
    with sightings_db_path.open("r") as f:
        sightings = json.load(f)
        assert sightings == ["2025-06-02T10:30:45.000407+00:00"]


def test_eventhandler_copes_with_malformed_reg_plate_event() -> None:
    client = Mock()
    uut = EventHandler(
        client,
        camera="test_cam",
        state_topic="test/topic",
        image_topic="test/images",
        dvla_config=DVLASettings(),
        plate_config=PlateSettings(),
        image_config=ImageSettings(),
        tracker_config=TrackerSettings(),
        ocr_config=OCRSettings(direction_box="850,0,650,30"),
        file_system_config=FileSystemSettings(
            image_url_base="http://127.0.0.1/images",
            image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<plate>[A-Z0-9]+)_VEHICLE_DETECTION\.(?P<ext>jpg|png|gif|jpeg)"),
            watch_path=Path("/fixtures"),
        ),
    )

    event = Mock()
    event.src_path = "fixtures/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg"
    event.event_type = "closed"
    event.is_directory = False
    uut.on_closed(event)
    client.publish.assert_called_once_with(
        "test/topic",
        payload=json.dumps(
            {
                "plate": "",
                "vehicle_direction": "Unknown",
                "reg_info": None,
                "camera": "test_cam",
                "event_image_url": "http://127.0.0.1/images/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg",
                "file_path": "fixtures/2024110312013232013_P99JHG_VEHICLE_DETECTION.jpeg",
            }
        ),
        qos=0,
        retain=True,
    )


def test_corrections_unknown(event_handler: EventHandler) -> None:
    results = event_handler.classify_plate("PK12TST")
    assert results == {
        "dangerous": False,
        "description": "Unknown vehicle",
        "ignore": False,
        "known": False,
        "priority": "high",
        "orig_plate": "PK12TST",
        "plate": "PK12TST",
    }


def test_corrections_gangsta(event_handler: EventHandler) -> None:
    event_handler.plate_config.dangerous["PK12TST"] = "Local dodgy man"
    results = event_handler.classify_plate("PK12TST")
    assert results == {
        "dangerous": True,
        "description": "Local dodgy man",
        "ignore": False,
        "known": False,
        "priority": "critical",
        "orig_plate": "PK12TST",
        "plate": "PK12TST",
    }


def test_corrections_known(event_handler: EventHandler) -> None:
    event_handler.plate_config.known["PK12TST"] = "Postie"
    results = event_handler.classify_plate("PK12TST")
    assert results == {
        "dangerous": False,
        "description": "Postie",
        "ignore": False,
        "known": True,
        "priority": "medium",
        "orig_plate": "PK12TST",
        "plate": "PK12TST",
    }


def test_corrections_known_with_correction(event_handler: EventHandler) -> None:
    event_handler.plate_config.known["PK12TST"] = "Postie"
    event_handler.plate_config.correction["PK12TST"] = ["P12TST"]
    results = event_handler.classify_plate("P12TST")
    assert results == {
        "dangerous": False,
        "description": "Postie",
        "ignore": False,
        "known": True,
        "priority": "medium",
        "orig_plate": "P12TST",
        "plate": "PK12TST",
    }


def test_corrections_ignore(event_handler: EventHandler) -> None:
    event_handler.plate_config.ignore.append(".*TST")
    results = event_handler.classify_plate("PK12TST")
    assert results == {
        "dangerous": False,
        "description": "Ignored Plate",
        "ignore": True,
        "known": False,
        "priority": "low",
        "orig_plate": "PK12TST",
        "plate": "PK12TST",
    }


def test_process_image(tmp_path: Path) -> None:
    fixture_image_path = Path("fixtures") / "20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    image: Image.Image | None = process_image(
        fixture_image_path,
        ImageInfo("", dt.datetime.now(tz=dt.UTC), size=fixture_image_path.stat().st_size, ext="jpeg"),
        jpeg_opts={"quality": 30, "progressive": True, "optimize": True},
        png_opts={},
    )
    assert image is not None
    image.save(tmp_path / "test.jpeg", "jpeg")
    reimage = Image.open(tmp_path / "test.jpeg")
    assert reimage is not None
