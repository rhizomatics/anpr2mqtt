import re
import warnings
from enum import StrEnum, auto
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core.core_schema import FieldValidationInfo
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

TARGET_TYPE_PLATE: Final[str] = "plate"


class MQTTSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    topic_root: str = "anpr2mqtt"
    host: str = Field(default="localhost", description="MQTT broker IP address or hostname")
    port: int = Field(default=1883, description="MQTT broker port number")
    user: str = Field(description="MQTT account user name")
    protocol: str = Field(default="3.11", description="MQTT protocol version, v3 and v5 supported")
    password: str = Field(alias="pass", description="MQTT account password")


class CameraSettings(BaseModel):
    name: str = Field(default="driveway", description="Camera Identifier, used to build MQTT topic names")
    area: str | None = Field(default=None, description="Home Assistant area ID")
    live_url: str | None = Field(default=None, description="URL to watch camera feed live")


class AutoClearSettings(BaseModel):
    enabled: bool = Field(default=True, description="Enable auto-clear of state after last event")
    post_event: int = Field(default=300, description="Seconds after last event to reset state")
    state: bool = Field(default=True, description="Auto-clear state")
    image: bool = Field(default=False, description="Auto-clear image")


class EventSettings(BaseModel):
    camera: str = Field(default="driveway", description="Camera name")
    event: str = Field(default="anpr", description="Identifier of the event, used in MQTT topic description")
    description: str | None = Field(default=None, description="Free text description of event")
    target_type: str = Field(default="plate", description="Type of target for this event, 'plate' if ANPR")
    watch_path: Path = Field(default=Path(), description="File system directory to watch")
    watch_tree: bool = Field(
        default=False, description="Watch directory tree at path, or false for only the root watch_path directory"
    )
    image_name_re: re.Pattern[str] = Field(
        default=re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"),
        description="Regular expression to find datetime, file extension and target from image name",
    )
    image_url_base: str | None = Field(default=None, description="Base URL to turn a file name into a web link")
    ocr_field_ids: list[str] = Field(
        default_factory=lambda: ["hik_direction"], description="OCR field definitions to find in image"
    )
    autoclear: AutoClearSettings = AutoClearSettings()

    @field_validator("image_url_base")
    @classmethod
    def validate_image_url_base(cls, v: str | None) -> str | None:
        if v is not None and v.endswith("/"):
            warnings.warn(
                f"image_url_base has a trailing slash ({v!r}); this will produce double-slash URLs. "
                "Remove the trailing slash from image_url_base.",
                UserWarning,
                stacklevel=2,
            )
        return v

    @field_validator("image_name_re")
    @classmethod
    def validate_image_name_re(cls, v: re.Pattern[str]) -> re.Pattern[str]:
        required = {"dt", "target"}
        missing = required - set(v.groupindex)
        if missing:
            raise ValueError(f"image_name_re is missing required named groups: {sorted(missing)}")
        return v


class HomeAssistantSettings(BaseModel):
    discovery_topic_root: str = "homeassistant"
    status_topic: str = Field(
        default="homeassistant/status", description="HomeAssistant status topic, where birth and will messages are posted"
    )
    device_creation: bool = Field(
        default=True, description="Create a Home Assistant Device and associate the event sensors and images to it"
    )
    image_entity: bool = Field(default=True, description="Create an Image entity via MQTT discovery")
    camera_entity: bool = Field(default=True, description="Create a Camera entity via MQTT discovery")


class CacheType(StrEnum):
    MEMORY = auto()
    FILE = auto()


class DVLASettings(BaseModel):
    api_key: str | None = Field(default=None, description="DVLA issued API key")
    cache_ttl: int = Field(default=86400, description="Time to live for cached DVLA API results, in seconds, default 1 day")
    cache_type: CacheType = Field(default=CacheType.FILE, description="Cache implementation, MEMORY or FILE")
    cache_dir: Path | None = Field(default=Path("/data/cache"), description="Cache directory")
    verify_plate: str | None = Field(default=None, description="Plate to check at startup to verify API")


class TrackerSettings(BaseModel):
    data_dir: Path = Path("/data")


class ImageSettings(BaseModel):
    jpeg_opts: dict[str, int | bool | float | str | tuple[int | float, int | float]] = Field(
        default={"quality": 30, "progressive": True, "optimize": True}
    )
    png_opts: dict[str, int | bool | float | str | tuple[int, int]] = Field(
        default={"quality": 30, "dpi": (60, 90), "optimize": True}
    )


class DimensionSettings(BaseModel):
    x: int = Field(description="Horizontal position of crop box, measured from image left side")
    y: int = Field(description="Vertical position of crop box, measured from image bottom side")
    h: int = Field(description="Height of crop box in pixels")
    w: int = Field(description="Width of crop box in pixels")


class OCRFieldSettings(BaseModel):
    label: str = "ocr_field"
    crop: DimensionSettings | None = None
    invert: bool = True
    correction: dict[str, list[re.Pattern[str]]] = Field(default_factory=lambda: {})
    values: list[str] | None = None


class OCRSettings(BaseModel):
    """Defaults for reading `direction` for the Hikvision DS-2CD4A25FWD-IZS"""

    fields: dict[str, OCRFieldSettings] = Field(
        default_factory=lambda: {
            "hik_direction": OCRFieldSettings(
                label="vehicle_direction",
                invert=True,
                crop=DimensionSettings(x=850, y=0, h=30, w=650),
                values=["Forward", "Reverse", "Unknown"],
                correction={"Forward": [re.compile(r"Fo.*rd")], "Reverse": [re.compile(r"Re.*rse"), re.compile(r"Bac.*rd")]},
            )
        }
    )


class Target(BaseModel):
    id: str = ""
    target_type: str = ""
    group: str | None = None
    description: str | None = Field(default=None, description="Target description")
    entity_id: str | None = Field(
        default=None, description="Entity ID to publish using Home Assistant MQTT Discovery compatible message"
    )
    icon: str = Field(
        default="mdi:car",
        description="Name of icon to publish, for Home Assistant should be a Material Design reference like 'mdi:car'",
    )
    priority: str | None = Field(default=None, description="Priority to report for use in Home Assistant notifications")

    def as_dict(self) -> dict[str, bool | str | None]:
        return {
            "dangerous": self.group == "dangerous",
            "description": self.description,
            "known": self.group == "known",
            "priority": self.priority,
            "target": self.id,
            "target_type": self.target_type,
            "entity_id": self.entity_id,
            "icon": self.icon,
        }


_PRIORITY_BY_GROUP: dict[str, str] = {"known": "medium", "dangerous": "critical"}


class TargetSettings(BaseModel):
    known: dict[str, Target] = Field(default_factory=lambda: {})
    dangerous: dict[str, Target] = Field(default_factory=lambda: {})
    ignore: list[str] = Field(default_factory=list)
    correction: dict[str, list[str | re.Pattern[str]]] = Field(default_factory=lambda: {})
    auto_match_tolerance: int = Field(
        default=1,
        description="Maximum tolerance for auto matching against known plates, using Levenshtein, 0 to disable fuzzy matching",
    )

    @field_validator("known", "dangerous", mode="before")
    @classmethod
    def coerce_targets(cls, v: object, info: FieldValidationInfo) -> dict[str, Target]:
        if not isinstance(v, dict):
            return v  # type: ignore[return-value]
        group: str = info.field_name or ""
        result: dict[str, Target] = {}
        for key, val in v.items():
            if isinstance(val, Target):
                result[key] = val
            elif isinstance(val, str):
                result[key] = Target(id=key, group=group, description=val)
            elif isinstance(val, dict):
                result[key] = Target(id=key, group=group, **val)
            else:
                result[key] = Target(id=key, group=group)
            if result[key].priority is None:
                result[key].priority = _PRIORITY_BY_GROUP.get(group, "high")
        return result


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        secrets_dir="/run/secrets",
        yaml_file="/config/anpr2mqtt.yaml",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        cli_avoid_json=False,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cameras: list[CameraSettings] = Field(default_factory=list)
    events: list[EventSettings] = Field(default_factory=lambda: [])
    image: ImageSettings = ImageSettings()
    targets: dict[str, TargetSettings] = Field(default_factory=lambda: {})
    tracker: TrackerSettings = TrackerSettings()
    mqtt: MQTTSettings
    dvla: DVLASettings = DVLASettings()
    homeassistant: HomeAssistantSettings = HomeAssistantSettings()
    ocr: OCRSettings = OCRSettings()

    @model_validator(mode="before")
    @classmethod
    def inject_target_type(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        for target_type, target_settings in (data.get("targets") or {}).items():
            if not isinstance(target_settings, dict):
                continue
            for group in ("known", "dangerous"):
                for target_id, val in (target_settings.get(group) or {}).items():
                    if isinstance(val, dict):
                        val["target_type"] = target_type
                    elif isinstance(val, str):
                        target_settings[group][target_id] = {"description": val, "target_type": target_type}
        return data

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
