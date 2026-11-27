import re
import warnings
from enum import StrEnum, auto
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

TARGET_TYPE_PLATE: Final[str] = "plate"
# not a camera event, but any file landing in the watch path, counted to check that uploads are still arriving
TARGET_TYPE_UPLOAD: Final[str] = "upload"
UPLOAD_NAME_RE: Final[str] = r".+"
DEFAULT_CAMERA: Final[str] = "driveway"

# Names used in MQTT topics, Home Assistant discovery and entity ids, and file paths: no topic separators or wildcards,
# path separators, dots, spaces or anything else Home Assistant discovery would reject
NAME_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Targets, such as plates, also name sighting history files, and may come from untrusted MQTT messages, such as Frigate's
TARGET_ID_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,31}")
# Frigate event ids, such as 1790171055.400738-28axk4, used in Frigate API URLs
FRIGATE_EVENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def is_valid_name(value: str | None) -> bool:
    return value is not None and NAME_RE.fullmatch(value) is not None


def check_name(value: str, what: str) -> str:
    if not is_valid_name(value):
        raise ValueError(
            f"{what} {value!r} must be 1 to 64 letters, digits, '_' or '-', such as 'front_door', since it's used in "
            "MQTT topics and Home Assistant entity ids. Use description for display text"
        )
    return value


def is_valid_target_id(value: str | None) -> bool:
    return value is not None and TARGET_ID_RE.fullmatch(value) is not None


class MQTTSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    topic_root: str = "anpr2mqtt"
    client_id: str = Field(
        default="anpr2mqtt",
        description="MQTT client ID, which must be different for each anpr2mqtt instance on the same broker",
    )
    host: str = Field(default="localhost", description="MQTT broker IP address or hostname")
    port: int = Field(default=1883, description="MQTT broker port number")
    user: str = Field(description="MQTT account user name")
    protocol: str = Field(default="3.11", description="MQTT protocol version, v3 and v5 supported")
    password: str = Field(alias="pass", description="MQTT account password")


class CameraSettings(BaseModel):
    name: str = Field(
        default="driveway",
        description="Camera Identifier, used to build MQTT topic names, letters, digits, '_' or '-' only",
    )
    area: str | None = Field(default=None, description="Home Assistant area ID")
    live_url: str | None = Field(default=None, description="URL to watch camera feed live")
    linked_cameras: dict[str, str] = Field(
        default_factory=dict,
        description="The same camera in other integrations, by the Home Assistant domain of each, such as frigate, "
        "unifiprotect, viseron or blueiris, for integrations that join sightings to their events. The frigate camera "
        "is also the one whose licence plate events are published as this camera, only needed where its name differs",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return check_name(v, "camera name")


class AutoClearSettings(BaseModel):
    enabled: bool = Field(default=True, description="Enable auto-clear of state after last event")
    post_event: int = Field(default=300, description="Seconds after last event to reset state")
    state: bool = Field(default=True, description="Auto-clear state")
    image: bool = Field(default=False, description="Auto-clear image")


class EventSettings(BaseModel):
    camera: str | None = Field(
        default=None,
        description="Camera name, 'driveway' if not given. Optional for uploads, which aren't tied to a camera, since "
        "several cameras may share a landing zone, and only shown as an attribute if given",
    )
    event: str = Field(
        default="anpr",
        description="Identifier of the event, used in MQTT topics and entity ids, 'anpr' for plates, otherwise the target_type",
    )
    id: str | None = Field(
        default=None,
        description="For uploads only, tells several landing zones apart, such as 'shed' for sensor.upload_shed. Not "
        "needed for a single upload",
    )
    description: str | None = Field(default=None, description="Free text description of event")
    target_type: str = Field(
        default="plate",
        description="Type of target for this event, 'plate' if ANPR, best always given. Any other type, such as 'face' or "
        "'scene_change', is published as a Home Assistant event entity rather than a sensor, and has no plate lookups or "
        "corrections. 'upload' counts every file arriving in the watch path, as a sensor of the last upload, without "
        "publishing any events, told apart by id rather than camera. Defaults to 'plate', so configurations "
        "from before other events were supported still work",
    )
    region: str | None = Field(default="UK", description="Region for applying correction, normalization rules")
    default_description: str | None = Field(
        default=None,
        description="Default description if no known match found, 'Unknown vehicle' for plates, otherwise from the event name",
    )
    icon: str | None = Field(
        default=None,
        description="Default icon to provide for Home Assistant entities, mdi:car-back for plates, mdi:folder-upload for "
        "uploads, otherwise mdi:cctv",
    )
    watch_path: Path = Field(default=Path(), description="File system directory to watch")
    watch_tree: bool = Field(
        default=False, description="Watch directory tree at path, or false for only the root watch_path directory"
    )
    image_name_re: re.Pattern[str] = Field(
        default=re.compile(r"(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)"),
        description="Regular expression to find datetime, file extension and target from image name. The target group "
        "is only required for plates, so events without one, such as faces, are published with their capture time as state. "
        "For uploads, any file name by default, with no datetime needed",
    )
    secondary_image_event: str | None = Field(
        default=None,
        description="Value of the image name's event group for a second image of the same capture, such as "
        "FACE_BACKGROUND, published as its own image entity rather than as another event",
    )
    min_event_gap_seconds: int = Field(
        default=0,
        description="For events without a target, such as faces, minimum seconds after one event before another is "
        "published, so several images of the same face are one event; 0 to publish every image. Plates use the "
        "tracker's min_visit_gap_seconds",
    )
    image_url_base: str | None = Field(default=None, description="Base URL to turn a file name into a web link")
    ocr_field_ids: list[str] = Field(
        default_factory=lambda: ["hik_direction"],
        description="OCR field definitions to find in image, the Hikvision vehicle direction for plates, otherwise none",
    )
    autoclear: AutoClearSettings = AutoClearSettings()
    auto_match_tolerance: int = Field(
        default=1,
        description="Maximum tolerance for auto matching against known plates, using Levenshtein, 0 to disable fuzzy matching",
    )
    good_read_ttl: int = Field(
        default=60,
        description="Seconds to retain the last DVLA-confirmed plate per camera for mis-read correction; 0 to disable",
    )
    good_read_tolerance: int = Field(
        default=2,
        description="Max Levenshtein distance from last known-good plate to trigger correction; 0 to disable",
    )

    @field_validator("event", "camera", "target_type", "id")
    @classmethod
    def validate_names(cls, v: str | None, info: ValidationInfo) -> str | None:
        return None if v is None else check_name(v, str(info.field_name))

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

    @model_validator(mode="before")
    @classmethod
    def non_plate_defaults(cls, data: Any) -> Any:
        """Other events don't get the plate defaults, an 'anpr' event name and the vehicle direction OCR"""
        if isinstance(data, dict):
            target_type: Any = data.get("target_type", TARGET_TYPE_PLATE)
            if target_type != TARGET_TYPE_UPLOAD and data.get("camera") is None:
                data = {**data, "camera": DEFAULT_CAMERA}
            if target_type != TARGET_TYPE_PLATE:
                data = {**data}
                data.setdefault("event", target_type)
                data.setdefault("ocr_field_ids", [])
                if target_type == TARGET_TYPE_UPLOAD:
                    data.setdefault("image_name_re", UPLOAD_NAME_RE)
        return data

    @model_validator(mode="after")
    def validate_target_groups(self) -> "EventSettings":
        groups = set(self.image_name_re.groupindex)
        # uploads aren't read for their capture time, so can be any file
        if "dt" not in groups and not self.is_upload:
            raise ValueError("image_name_re is missing required named groups: ['dt']")
        if self.target_type == TARGET_TYPE_PLATE and "target" not in groups:
            raise ValueError(
                "image_name_re is missing required named groups: ['target']. "
                "For events other than plates, set target_type, such as target_type: scene_change"
            )
        if self.id is not None and not self.is_upload:
            raise ValueError("id is only for uploads, other events are told apart by their event and camera")
        if self.secondary_image_event and "event" not in groups:
            raise ValueError("secondary_image_event needs an 'event' named group in image_name_re")
        if self.default_description is None:
            self.default_description = "Unknown vehicle" if self.is_plate else self.event.replace("_", " ").capitalize()
        if self.icon is None:
            self.icon = "mdi:car-back" if self.is_plate else "mdi:folder-upload" if self.is_upload else "mdi:cctv"
        return self

    @property
    def is_plate(self) -> bool:
        """Plate events are Home Assistant sensors, any other kind of event is an event entity"""
        return self.target_type == TARGET_TYPE_PLATE

    @property
    def is_upload(self) -> bool:
        """Uploads are counted, as a sensor of the last one, but never published as events"""
        return self.target_type == TARGET_TYPE_UPLOAD

    @property
    def upload_name(self) -> str:
        """Name of an upload's entity, topics and counts, by event and id, as uploads aren't tied to a camera"""
        return f"{self.event}_{self.id}" if self.id else self.event

    @property
    def has_target(self) -> bool:
        """Whether image names identify a target, such as a plate, or only that something was seen, such as a face"""
        return "target" in self.image_name_re.groupindex


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
    remove_stale_entities: bool = Field(
        default=True,
        description="At startup, remove Home Assistant entities this instance created before but no longer has, such as "
        "for events removed from the configuration",
    )


class CacheType(StrEnum):
    MEMORY = auto()
    FILE = auto()


class DVLASettings(BaseModel):
    api_key: str | None = Field(default=None, description="DVLA issued API key")
    cache_ttl: int = Field(default=86400, description="Time to live for cached DVLA API results, in seconds, default 1 day")
    cache_type: CacheType = Field(default=CacheType.FILE, description="Cache implementation, MEMORY or FILE")
    cache_dir: Path | None = Field(default=Path("/data/cache"), description="Cache directory")
    verify_plate: str | None = Field(default=None, description="Plate to check at startup to verify API")


class FrigateSettings(BaseModel):
    enabled: bool = Field(default=False, description="Enable Frigate MQTT event listener")
    topic: list[str] = Field(
        default=["frigate/events", "frigate/tracked_object_update"], description="MQTT topic for Frigate events"
    )
    min_score: float = Field(default=0.70, description="Minimum plate recognition score to process (0.0->1.0)")
    url: str | None = Field(
        default=None, description="Frigate base URL for API snapshot fallback and UI links, e.g. http://frigate:5000"
    )
    cameras: list[str] | None = Field(default=None, description="Camera names to process; None means all cameras")


# the key of a linked Frigate camera, the Frigate integration's Home Assistant domain
LINK_FRIGATE = "frigate"


def linked_cameras(camera: CameraSettings, frigate: FrigateSettings) -> dict[str, str]:
    """Find the cameras linked to this one, by the Home Assistant domain of each integration.

    Those set are always kept. While the Frigate listener is on, and processes a camera of the same name, that Frigate
    camera is linked too, unless another is set, since its licence plate events are published as this camera.
    """
    links = dict(camera.linked_cameras)
    if frigate.enabled and LINK_FRIGATE not in links and (frigate.cameras is None or camera.name in frigate.cameras):
        links[LINK_FRIGATE] = camera.name
    return links


class TrackerSettings(BaseModel):
    data_dir: Path = Path("/data")
    min_visit_gap_seconds: int = Field(
        default=0,
        description="Minimum seconds between recorded visits for the same target; 0 to disable (every read is a visit)",
    )


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


def hik_direction_field() -> OCRFieldSettings:
    """Field to read `direction` from the caption bar of the Hikvision DS-2CD4A25FWD-IZS"""
    return OCRFieldSettings(
        label="vehicle_direction",
        invert=True,
        crop=DimensionSettings(x=850, y=0, h=30, w=650),
        values=["Forward", "Reverse", "Unknown"],
        correction={"Forward": [re.compile(r"Fo.*rd")], "Reverse": [re.compile(r"Re.*rse"), re.compile(r"Bac.*rd")]},
    )


class OCRSettings(BaseModel):
    """Defaults for reading `direction` for the Hikvision DS-2CD4A25FWD-IZS"""

    fields: dict[str, OCRFieldSettings] = Field(default_factory=lambda: {"hik_direction": hik_direction_field()})
    verify_on_startup: bool = Field(
        default=True, description="OCR a bundled sample image at startup, to check Tesseract is installed and working"
    )


class Target(BaseModel):
    id: str = Field(description="Target identifier, for example reg plate")
    target_type: str = ""
    group: str | None = None
    lookup: bool | None = Field(
        default=None, description="Lookup registration plate using API, defaults to False for configured plates"
    )
    description: str | None = Field(default=None, description="Target description")
    entity_id: str | None = Field(
        default=None, description="Entity ID to publish using Home Assistant MQTT Discovery compatible message"
    )
    icon: str | None = Field(
        default=None,
        description="Name of icon to publish, for Home Assistant should be a Material Design reference like 'mdi:car'",
    )
    priority: str | None = Field(default=None, description="Priority to report for use in Home Assistant notifications")
    correction: list[str | re.Pattern[str]] = Field(default_factory=lambda: [])

    def as_dict(self) -> dict[str, bool | str | None]:
        result: dict[str, bool | str | None] = {
            "dangerous": self.group == "dangerous",  # backward compat
            "description": self.description,
            "known": self.group == "known",  # backward compat
            "priority": self.priority,
            "target": self.id,
            "target_type": self.target_type,
            "entity_id": self.entity_id,
        }
        if self.icon:
            result["icon"] = self.icon

        return result


_PRIORITY_BY_GROUP: dict[str, str] = {"known": "medium", "dangerous": "critical"}


class TargetGroup(BaseModel):
    name: str = Field(description="Name of the target group, for example 'known'")
    priority: str = Field(default="medium", description="Priority to report on MQTT message for sightings of this group")
    lookup: bool = Field(
        default=False, description="Lookup registration plate using API, defaults to False for configured plates"
    )
    members: list[Target] = Field(description="List of target IDs or full target definitions")
    icon: str | None = Field(
        default=None,
        description="Name of icon to publish, for Home Assistant should be a Material Design reference like 'mdi:car'",
    )
    entity_id: str | None = Field(
        default=None, description="Entity ID to publish using Home Assistant MQTT Discovery compatible message"
    )

    @field_validator("members", mode="before")
    @classmethod
    def coerce_member_strings(cls, v: object) -> object:
        if not isinstance(v, list):
            return v
        return [{"id": item} if isinstance(item, str) else item for item in v]

    @model_validator(mode="after")
    def apply_group_defaults(self) -> "TargetGroup":

        for target in self.members:
            target.group = self.name
            if target.lookup is None:
                target.lookup = self.lookup
            if target.priority is None:
                target.priority = self.priority
            if target.icon is None:
                target.icon = self.icon
            if target.entity_id is None:
                target.entity_id = self.entity_id
            if target.description is None:
                target.description = self.name
        return self


class TargetSettings(BaseModel):
    groups: list[TargetGroup] = Field(default_factory=list)
    known: dict[str, object] = Field(default_factory=dict, deprecated="Replaced by a 'groups' entry with name 'known'")
    dangerous: dict[str, object] = Field(
        default_factory=dict, deprecated="Replaced by a 'groups' entry with name 'dangerous' and priority 'critical'"
    )
    ignore: list[str | re.Pattern[str]] = Field(default_factory=list)
    correction: dict[str, list[str | re.Pattern[str]]] = Field(default_factory=lambda: {})


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
    frigate: FrigateSettings = FrigateSettings()
    homeassistant: HomeAssistantSettings = HomeAssistantSettings()
    ocr: OCRSettings = OCRSettings()

    @model_validator(mode="before")
    @classmethod
    def migrate_and_inject_target_type(cls, data: object) -> object:
        """Migrate legacy 'known'/'dangerous' to TargetGroup entries and inject target_type into all members."""
        if not isinstance(data, dict):
            return data
        for target_type, target_settings in (data.get("targets") or {}).items():
            if not isinstance(target_settings, dict):
                continue
            groups: list[dict[str, object] | TargetGroup] = list(target_settings.get("groups") or [])

            # migration of original known/dangerous fixed groups
            existing_names = {g["name"] if isinstance(g, dict) else g.name for g in groups}
            for group_name in ("known", "dangerous"):
                legacy: dict[str, object] = target_settings.get(group_name) or {}
                if not legacy or group_name in existing_names:
                    continue
                members = []
                for target_id, val in legacy.items():
                    if isinstance(val, str):
                        members.append({"id": target_id, "description": val, "target_type": target_type})
                    elif isinstance(val, dict):
                        members.append({"id": target_id, "target_type": target_type, **val})
                    else:
                        members.append({"id": target_id, "target_type": target_type})
                groups.append(
                    {
                        "name": group_name,
                        "priority": _PRIORITY_BY_GROUP.get(group_name, "medium"),
                        "members": members,
                        "lookup": group_name == "dangerous",
                    }
                )
            # normalize strings->dicts
            target_settings["groups"] = groups
            for group in groups:
                if not isinstance(group, dict):
                    continue
                raw_members = group.get("members")
                if not isinstance(raw_members, list):
                    continue
                for i, member in enumerate(raw_members):
                    if isinstance(member, str):
                        raw_members[i] = {"id": member, "target_type": target_type}
                    elif isinstance(member, dict) and "target_type" not in member:
                        member["target_type"] = target_type
        return data

    @model_validator(mode="after")
    def unique_upload_events(self) -> "Settings":
        """Reject uploads sharing a name, since without a camera, they'd share an entity and counts"""
        names: list[str] = [event.upload_name for event in self.events if event.is_upload]
        duplicates: list[str] = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"each upload needs its own id, such as 'id: shed', but more than one is named {duplicates}")
        return self

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


SOURCE_LABELS: Final[dict[type[PydanticBaseSettingsSource], str]] = {
    CliSettingsSource: "command line",
    EnvSettingsSource: "environment variable",
    DotEnvSettingsSource: "dotenv file",
    NestedSecretsSettingsSource: "secrets",
    YamlConfigSettingsSource: "config file",
    InitSettingsSource: "init",
}


def setting_source(settings_cls: type[BaseSettings], *path: str) -> str | None:
    """Name the highest priority settings source that supplies the value at path, e.g. ("mqtt", "pass")

    Diagnostic only, so an env var silently overriding the config file can be spotted; never exposes the value.
    """
    try:
        sources = settings_cls.settings_customise_sources(
            settings_cls,
            init_settings=InitSettingsSource(settings_cls, init_kwargs={}),
            env_settings=EnvSettingsSource(settings_cls),
            dotenv_settings=DotEnvSettingsSource(settings_cls),
            file_secret_settings=SecretsSettingsSource(settings_cls),
        )
    except Exception:
        return None
    for source in sources:
        if _source_value(source, path) is not None:
            return SOURCE_LABELS.get(type(source), type(source).__name__)
    return None


def _source_value(source: PydanticBaseSettingsSource, path: tuple[str, ...]) -> Any:
    """Value a single settings source supplies at path, or None if it doesn't, or can't be read"""
    try:
        value: Any = source()
        for key in path:
            value = value[key]
    except Exception:
        return None
    return value
