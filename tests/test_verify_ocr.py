"""Startup OCR verification against the bundled sample image."""

from unittest.mock import patch

from pytesseract import TesseractNotFoundError
from structlog.testing import capture_logs

from anpr2mqtt.event_handler import verify_ocr


def test_verify_ocr_tesseract_missing() -> None:
    with (
        patch("anpr2mqtt.event_handler.pytesseract.get_tesseract_version", side_effect=TesseractNotFoundError()),
        capture_logs() as logs,
    ):
        assert verify_ocr() is False
    assert "ocr_field_ids: []" in str(logs)


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
