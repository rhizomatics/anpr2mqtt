from typing import TYPE_CHECKING

import structlog
from PIL import Image
from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    CliApp,
    CliPositionalArg,
    CliSubCommand,
)

from anpr2mqtt.event_handler import determine_anpr_direction, examine_file
from anpr2mqtt.settings import FileSystemSettings, OCRSettings

if TYPE_CHECKING:
    from anpr2mqtt.const import ImageInfo

log = structlog.get_logger()


class OCRTool(BaseModel):
    file_system: FileSystemSettings
    ocr: OCRSettings = OCRSettings()
    image_file: CliPositionalArg[str]

    def cli_cmd(self) -> None:
        coordinates: list[int] | None = [int(v) for v in self.ocr.direction_box.split(",")] if self.ocr.direction_box else None
        image: Image.Image | None = Image.open(self.file_system.watch_path / self.image_file)
        if image:
            print(determine_anpr_direction(image, coordinates))  # noqa: T201
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
    ocr_file: CliSubCommand[OCRTool]
    list_dir: CliSubCommand[ListTool]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
