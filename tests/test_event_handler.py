import datetime as dt
import json
from pathlib import Path
from unittest.mock import ANY, Mock, call

from PIL import Image

from anpr2mqtt.const import ImageInfo
from anpr2mqtt.event_handler import EventHandler, process_image
from anpr2mqtt.settings import TargetSettings


def test_eventhandler_handles_reg_plate_event(event_handler: EventHandler) -> None:
    event = Mock()
    event.src_path = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"
    event.event_type = "closed"
    event.is_directory = False
    event_handler.on_closed(event)
    event_handler.client.publish.assert_has_calls(  # type: ignore[attr-defined]
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
    event_handler.client.publish.assert_called_once_with(  # type: ignore[attr-defined]
        "test/topic",
        payload=json.dumps(
            {
                "target": None,
                "target_type": "plate",
                "plate": None,
                "event": "unit_testing",
                "camera": "test_cam",
                "area": None,
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
