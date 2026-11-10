"""Startup OCR verification against the bundled sample image."""

import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pytesseract import TesseractNotFoundError

from anpr2mqtt.app import main_loop
from anpr2mqtt.event_handler import verify_ocr
from anpr2mqtt.settings import (
    CameraSettings,
    DVLASettings,
    EventSettings,
    ImageSettings,
    OCRSettings,
    TrackerSettings,
)
from tests.test_app import _make_mock_settings


def test_verify_ocr_tesseract_missing() -> None:
    with patch("anpr2mqtt.event_handler.pytesseract.get_tesseract_version", side_effect=TesseractNotFoundError()):
        assert verify_ocr() is False


TESSERACT_PRESENT = patch("anpr2mqtt.event_handler.pytesseract.get_tesseract_version", return_value="5.5.0")
OCR_READ = "anpr2mqtt.event_handler.pytesseract.image_to_string"


def test_verify_ocr_reads_sample() -> None:
    """Loads the bundled sample, crops it with the Hikvision field and accepts a correct read"""
    with TESSERACT_PRESENT, patch(OCR_READ, return_value="Direction:Forward") as ocr:
        assert verify_ocr() is True
    region = ocr.call_args.args[0]
    assert region.size == (650, 30)


def test_verify_ocr_wrong_read() -> None:
    with TESSERACT_PRESENT, patch(OCR_READ, return_value="garbage"):
        assert verify_ocr() is False


@pytest.mark.parametrize(("verify_on_startup", "ocr_field_ids", "called"), [
    (True, ["hik_direction"], True),
    (False, ["hik_direction"], False),
    (True, [], False),
])  # fmt: skip
def test_main_loop_verifies_ocr_only_when_used(
    tmp_path: Path, verify_on_startup: bool, ocr_field_ids: list[str], called: bool
) -> None:
    event_config = EventSettings(
        camera="cam1",
        event="anpr",
        watch_path=tmp_path,
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg)"),
        ocr_field_ids=ocr_field_ids,
    )
    settings = _make_mock_settings(events=[event_config])
    settings.cameras = [CameraSettings(name="cam1")]
    settings.ocr = OCRSettings(verify_on_startup=verify_on_startup)
    settings.image = ImageSettings()
    settings.dvla = DVLASettings()
    settings.tracker = TrackerSettings(data_dir=tmp_path)
    observer = Mock()
    observer.is_alive.return_value = False

    with (
        patch("anpr2mqtt.app.Settings", return_value=settings),
        patch("anpr2mqtt.app.mqtt.Client", return_value=Mock()),
        patch("anpr2mqtt.app.Observer", return_value=observer),
        patch("anpr2mqtt.app.verify_ocr") as verify,
    ):
        main_loop()

    assert verify.called is called
