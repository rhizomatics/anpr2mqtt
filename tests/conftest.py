import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from anpr2mqtt.event_handler import EventHandler
from anpr2mqtt.settings import DVLASettings, FileSystemSettings, ImageSettings, OCRSettings, PlateSettings, TrackerSettings


@pytest.fixture(scope="session", autouse=True)
def set_tz_env_variable() -> None:
    os.environ["TZ"] = "UTC"


@pytest.fixture
def event_handler() -> EventHandler:
    return EventHandler(
        Mock(),
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
