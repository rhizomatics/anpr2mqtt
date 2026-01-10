import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from anpr2mqtt.event_handler import EventHandler
from anpr2mqtt.settings import (
    DimensionSettings,
    DVLASettings,
    EventSettings,
    ImageSettings,
    OCRFieldSettings,
    OCRSettings,
    TargetSettings,
    TrackerSettings,
)


@pytest.fixture(scope="session", autouse=True)
def set_tz_env_variable() -> None:
    os.environ["TZ"] = "UTC"


@pytest.fixture
def event_handler(tmp_path: Path) -> EventHandler:
    return EventHandler(
        Mock(),
        state_topic="test/topic",
        image_topic="test/images",
        dvla_config=DVLASettings(),
        target_config=TargetSettings(),
        image_config=ImageSettings(),
        tracker_config=TrackerSettings(data_dir=tmp_path),
        ocr_config=OCRSettings(
            fields={
                "test_direction": OCRFieldSettings(
                    label="vehicle_direction", invert=True, crop=DimensionSettings(x=850, y=0, h=30, w=650)
                )
            }
        ),
        event_config=EventSettings(
            camera="test_cam",
            event="unit_testing",
            image_url_base="http://127.0.0.1/images",
            image_name_re=re.compile(
                r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"
            ),
            watch_path=Path("/fixtures"),
            ocr_field_ids=["test_direction"],
        ),
    )
