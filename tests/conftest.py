import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from anpr2mqtt.event_handler import EventHandler
from anpr2mqtt.settings import (
    DimensionSettings,
    DVLASettings,
    FileSystemSettings,
    ImageSettings,
    OCRFieldSettings,
    OCRSettings,
    PlateSettings,
    TrackerSettings,
)


@pytest.fixture(scope="session", autouse=True)
def set_tz_env_variable() -> None:
    os.environ["TZ"] = "UTC"


@pytest.fixture
def event_handler(tmp_path: Path) -> EventHandler:
    return EventHandler(
        Mock(),
        camera="test_cam",
        state_topic="test/topic",
        image_topic="test/images",
        dvla_config=DVLASettings(),
        plate_config=PlateSettings(),
        image_config=ImageSettings(),
        tracker_config=TrackerSettings(data_dir=tmp_path),
        ocr_config=OCRSettings(
            fields={"vehicle_direction": OCRFieldSettings(invert=True, crop=DimensionSettings(x=850, y=0, h=30, w=650))}
        ),
        file_system_config=FileSystemSettings(
            image_url_base="http://127.0.0.1/images",
            image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<plate>[A-Z0-9]+)_VEHICLE_DETECTION\.(?P<ext>jpg|png|gif|jpeg)"),
            watch_path=Path("/fixtures"),
        ),
    )
