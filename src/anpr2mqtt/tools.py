from pathlib import Path
from typing import TYPE_CHECKING, Literal

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
from anpr2mqtt.settings import EventSettings, OCRFieldSettings, OCRSettings

if TYPE_CHECKING:
    from anpr2mqtt.const import ImageInfo

log = structlog.get_logger()


class OCRTool(BaseModel):
    event: EventSettings | None = EventSettings()
    ocr: OCRFieldSettings | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    image_file: CliPositionalArg[str]

    def cli_cmd(self) -> None:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(self.log_level))

        image_path: Path = self.event.watch_path if self.event is not None else Path()
        image: Image.Image | None = Image.open(image_path / self.image_file)
        if self.ocr is not None:
            ocr_settings: OCRSettings = OCRSettings(fields={"hik_direction": self.ocr})
        else:
            ocr_settings = OCRSettings()
        log.debug("ocr_files: ocr_settings->%s", ocr_settings)
        if image and self.event:
            print(scan_ocr_fields(image, self.event, ocr_settings))  # noqa: T201
        else:
            print("Image can't be loaded")  # noqa: T201


class ListTool(BaseModel):
    event: EventSettings = EventSettings()
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    def cli_cmd(self) -> None:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(self.log_level))
        log.info(f"list_dir: {self.event.event} from {self.event.watch_path.resolve()}")
        for p in self.event.watch_path.iterdir():  # ty:ignore[invalid-argument-type]
            results: ImageInfo | None = examine_file(p, self.event.image_name_re)
            if results is not None:
                print(f"{results.target}: timestamp={results.timestamp},ext={results.ext}")  # noqa: T201


class Tools(BaseSettings, cli_parse_args=True, cli_exit_on_error=True):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_ignore_empty=True,
        cli_avoid_json=True,
    )
    ocr_file: CliSubCommand[OCRTool]
    list_dir: CliSubCommand[ListTool]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)


def tools() -> None:
    CliApp.run(model_cls=Tools)
