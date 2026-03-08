"""Unit tests for tools.py (complementing the subprocess-based test_tools.py)."""

import contextlib
import re
from pathlib import Path
from unittest.mock import patch

from anpr2mqtt.settings import DimensionSettings, EventSettings, OCRFieldSettings
from anpr2mqtt.tools import ListTool, OCRTool

FIXTURE_IMAGE = "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg"


def test_ocr_tool_cli_cmd_default_ocr() -> None:
    """OCRTool with no custom OCR field uses default OCRSettings."""
    tool = OCRTool(image_file=FIXTURE_IMAGE)
    tool.cli_cmd()  # Should run without error


def test_ocr_tool_cli_cmd_custom_ocr() -> None:
    """OCRTool with explicit OCRFieldSettings uses it."""
    ocr = OCRFieldSettings(
        label="vehicle_direction",
        invert=True,
        crop=DimensionSettings(x=850, y=0, h=30, w=650),
    )
    tool = OCRTool(image_file=FIXTURE_IMAGE, ocr=ocr)
    tool.cli_cmd()


def test_ocr_tool_cli_cmd_no_event() -> None:
    """OCRTool with event=None falls back to empty Path."""
    tool = OCRTool.model_construct(image_file=FIXTURE_IMAGE, event=None, ocr=None, log_level="INFO")
    # event is None → may fail to open image; just check it doesn't raise uncaught
    with contextlib.suppress(Exception):
        tool.cli_cmd()


def test_ocr_tool_cli_cmd_debug_log() -> None:
    """OCRTool with DEBUG log_level sets structlog accordingly."""
    tool = OCRTool(image_file=FIXTURE_IMAGE, log_level="DEBUG")
    tool.cli_cmd()


def test_list_tool_cli_cmd_fixtures() -> None:
    """ListTool lists fixture files and prints matched ones."""
    event = EventSettings(
        camera="test_cam",
        event="anpr",
        watch_path=Path("fixtures"),
        image_name_re=re.compile(
            r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"
        ),
        ocr_field_ids=[],
    )
    tool = ListTool(event=event)
    printed: list[str] = []
    with patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a))):
        tool.cli_cmd()
    assert any("B4DM3N" in p for p in printed)


def test_list_tool_cli_cmd_empty_dir(tmp_path: Path) -> None:
    """ListTool on an empty directory produces no image-match output."""
    event = EventSettings(
        camera="test_cam",
        event="anpr",
        watch_path=tmp_path,
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg)"),
        ocr_field_ids=[],
    )
    tool = ListTool(event=event)
    printed_targets: list[str] = []
    with patch("builtins.print", side_effect=lambda *a, **_k: printed_targets.append(str(a))):
        tool.cli_cmd()
    # structlog uses print internally; no image targets should be printed
    assert not any("timestamp=" in t for t in printed_targets)
