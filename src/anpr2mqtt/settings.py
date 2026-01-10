import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class MQTTSettings(BaseModel):
    topic_root: str = "anpr"
    host: str = Field(default="localhost", description="MQTT broker IP address or hostname")
    port: int = Field(default=1883, description="MQTT broker port number")
    user: str
    password: str = Field(alias="pass", description="MQTT account password")


class FileSystemSettings(BaseModel):
    watch_path: Path = Field(default=Path("/ftp"), description="File system directory to watch")
    image_name_re: re.Pattern[str] = Field(
        default=re.compile(r"(?P<dt>[0-9]{17})_(?P<plate>[A-Z0-9]+)_VEHICLE_DETECTION\.(?P<ext>jpg|png|gif|jpeg)"),
        description="Regular expression to find date and plate from image name",
    )
    image_url_base: str | None = Field(default=None, description="Base URL to turn a file name into a web link")


class HomeAssistantSettings(BaseModel):
    discovery_topic_root: str = "homeassistant"


class DVLASettings(BaseModel):
    api_key: str | None = None
    cache_ttl: int = 86400


class TrackerSettings(BaseModel):
    data_dir: Path = Path("/data")


class ImageSettings(BaseModel):
    jpeg_opts: dict = Field(default={"quality": 30, "progressive": True, "optimize": True})
    png_opts: dict = Field(default={"quality": 30, "dpi": (60, 90), "optimize": True})


class OCRSettings(BaseModel):
    direction_box: str = Field(
        default="850,0,650,30", description="Box to crop for vehicle direction, horz, vert, width, height"
    )
    invert: bool = True


class PlateSettings(BaseModel):
    known: dict[str, str | None] = Field(default_factory=lambda: {})
    dangerous: dict[str, str | None] = Field(default_factory=lambda: {})
    ignore: list[str] = Field(default_factory=list)
    correction: dict[str, list[re.Pattern | str]] = Field(default_factory=lambda: {})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        secrets_dir="/run/secrets",
        yaml_file="/config/anpr2mqtt.yaml",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        cli_avoid_json=True,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    camera: str = "anpr"
    image: ImageSettings = ImageSettings()
    plates: PlateSettings = PlateSettings()
    tracker: TrackerSettings = TrackerSettings()
    mqtt: MQTTSettings
    dvla: DVLASettings = DVLASettings()
    homeassistant: HomeAssistantSettings = HomeAssistantSettings()
    ocr: OCRSettings = OCRSettings()
    file_system: FileSystemSettings = FileSystemSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            CliSettingsSource(settings_cls, cli_parse_args=True),
            env_settings,
            dotenv_settings,
            NestedSecretsSettingsSource(file_secret_settings, secrets_dir_missing="ok"),
            YamlConfigSettingsSource(settings_cls),
            init_settings,
        )
