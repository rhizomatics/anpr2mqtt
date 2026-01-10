from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from PIL import Image
from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    CliApp,
    CliPositionalArg,
    CliSubCommand,
    SettingsConfigDict,
)

from anpr2mqtt.event_handler import examine_file, scan_ocr_fields
from anpr2mqtt.settings import FileSystemSettings, OCRFieldSettings, OCRSettings

if TYPE_CHECKING:
    from anpr2mqtt.const import ImageInfo

log = structlog.get_logger()


class OCRTool(BaseModel):
    file_system: FileSystemSettings | None = None
    ocr: OCRFieldSettings | None = None
    image_file: CliPositionalArg[str]

    def cli_cmd(self) -> None:
        image_path: Path = self.file_system.watch_path if self.file_system is not None else Path()
        image: Image.Image | None = Image.open(image_path / self.image_file)
        if self.ocr is not None:
            ocr_settings: OCRSettings = OCRSettings(fields={"test": self.ocr})
        else:
            ocr_settings = OCRSettings()
        if image:
            print(scan_ocr_fields(image, ocr_settings))  # noqa: T201
        else:
            print("Image can't be loaded")  # noqa: T201


class ListTool(BaseModel):
    file_system: FileSystemSettings

    def cli_cmd(self) -> None:
        for p in self.file_system.watch_path.iterdir():  # ty:ignore[invalid-argument-type]
            results: ImageInfo | None = examine_file(p, self.file_system.image_name_re)
            if results is not None:
                print(f"{results.plate}: timestamp={results.timestamp},ext={results.ext}")  # noqa: T201


class Tools(BaseSettings, cli_parse_args=True, cli_exit_on_error=True):
    model_config = SettingsConfigDict(
        yaml_file="/config/anpr2mqtt.yaml",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        cli_avoid_json=True,
    )
    ocr_file: CliSubCommand[OCRTool]
    list_dir: CliSubCommand[ListTool]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
