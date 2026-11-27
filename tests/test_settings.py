import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from anpr2mqtt.settings import (
    CameraSettings,
    EventSettings,
    FrigateSettings,
    Target,
    TargetGroup,
    TargetSettings,
    linked_cameras,
)


def _group(**kwargs: Any) -> TargetGroup:
    return TargetGroup(
        name="known",
        priority="medium",
        icon="mdi:car",
        entity_id="sensor.known",
        members=[Target(id="ABC123")],
        **kwargs,
    )


def _member(group: TargetGroup) -> Target:
    return group.members[0]


# ── inheritance (None fields pick up group values) ───────────────────────────


def test_inherits_priority() -> None:
    assert _member(_group()).priority == "medium"


def test_inherits_icon() -> None:
    ts = TargetSettings(groups=[_group()])
    assert ts.groups[0].members[0].icon == "mdi:car"


def test_inherits_entity_id() -> None:
    assert _member(_group()).entity_id == "sensor.known"


def test_inherits_description_from_group_name() -> None:
    assert _member(_group()).description == "known"


# ── no override (set fields are preserved) ───────────────────────────────────


def test_does_not_override_priority() -> None:
    g = TargetGroup(name="known", priority="medium", members=[Target(id="ABC123", priority="critical")])
    assert g.members[0].priority == "critical"


def test_does_not_override_icon() -> None:
    g = TargetGroup(name="known", icon="mdi:car", members=[Target(id="ABC123", icon="mdi:truck")])
    assert g.members[0].icon == "mdi:truck"


def test_does_not_override_entity_id() -> None:
    g = TargetGroup(name="known", entity_id="sensor.group", members=[Target(id="ABC123", entity_id="sensor.mine")])
    assert g.members[0].entity_id == "sensor.mine"


def test_does_not_override_description() -> None:
    g = TargetGroup(name="known", members=[Target(id="ABC123", description="My car")])
    assert g.members[0].description == "My car"


def test_linked_frigate_camera_by_name() -> None:
    frigate = FrigateSettings(enabled=True)
    assert linked_cameras(CameraSettings(name="driveway"), frigate) == {"frigate": "driveway"}


def test_linked_frigate_camera_set() -> None:
    frigate = FrigateSettings(enabled=True)
    camera = CameraSettings(name="drive", linked_cameras={"frigate": "driveway_lpr"})
    assert linked_cameras(camera, frigate) == {"frigate": "driveway_lpr"}


def test_linked_cameras_kept_with_frigate_off() -> None:
    camera = CameraSettings(name="driveway", linked_cameras={"unifiprotect": "Driveway G4", "frigate": "driveway"})
    assert linked_cameras(camera, FrigateSettings()) == {"unifiprotect": "Driveway G4", "frigate": "driveway"}
    # nothing matched by name without the Frigate listener
    assert linked_cameras(CameraSettings(name="driveway"), FrigateSettings()) == {}


def test_linked_frigate_camera_only_cameras_processed() -> None:
    frigate = FrigateSettings(enabled=True, cameras=["garage"])
    assert linked_cameras(CameraSettings(name="driveway"), frigate) == {}
    camera = CameraSettings(name="drive", linked_cameras={"frigate": "garage", "blueiris": "drive"})
    assert linked_cameras(camera, frigate) == {"frigate": "garage", "blueiris": "drive"}


def test_setting_source_identifies_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, YamlConfigSettingsSource

    from anpr2mqtt.settings import Settings, setting_source

    config = tmp_path / "anpr2mqtt.yaml"
    config.write_text("mqtt:\n  user: anpr\n  pass: from-yaml\n")

    class YamlEnvSettings(Settings):
        @classmethod
        def settings_customise_sources(  # type: ignore[override]
            cls,
            settings_cls: type[BaseSettings],
            env_settings: PydanticBaseSettingsSource,
            **_kwargs: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (env_settings, YamlConfigSettingsSource(settings_cls, yaml_file=config))

    monkeypatch.delenv("MQTT__PASS", raising=False)
    assert setting_source(YamlEnvSettings, "mqtt", "pass") == "config file"
    monkeypatch.setenv("MQTT__PASS", "from-env")
    assert setting_source(YamlEnvSettings, "mqtt", "pass") == "environment variable"
    assert YamlEnvSettings().mqtt.password == "from-env"  # ruff: ignore[hardcoded-password-string]
    assert setting_source(YamlEnvSettings, "mqtt", "nonexistent") is None


def test_face_event_needs_no_target_group() -> None:
    event = EventSettings(
        target_type="face",
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_(?P<event>FACE_SNAP|FACE_BACKGROUND)\.jpg"),
        secondary_image_event="FACE_BACKGROUND",
    )
    assert event.has_target is False
    assert EventSettings().has_target is True


def test_plate_event_still_needs_target_group() -> None:
    with pytest.raises(ValidationError, match="target"):
        EventSettings(image_name_re=re.compile(r"(?P<dt>[0-9]{17})_FACE_SNAP\.jpg"))


def test_secondary_image_event_needs_event_group() -> None:
    with pytest.raises(ValidationError, match="secondary_image_event"):
        EventSettings(
            target_type="face", image_name_re=re.compile(r"(?P<dt>[0-9]{17})_FACE\.jpg"), secondary_image_event="FACE_X"
        )


def test_defaults_follow_target_type() -> None:
    plate = EventSettings()
    assert plate.is_plate is True
    assert plate.default_description == "Unknown vehicle"
    assert plate.icon == "mdi:car-back"
    scene = EventSettings(
        event="scene_change", target_type="scene_change", image_name_re=re.compile(r"(?P<dt>[0-9]{17})_SCENE\.jpg")
    )
    assert scene.is_plate is False
    assert scene.default_description == "Scene change"
    assert scene.icon == "mdi:cctv"
    custom = EventSettings(
        target_type="face",
        default_description="Face",
        icon="mdi:face-recognition",
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_FACE\.jpg"),
    )
    assert (custom.default_description, custom.icon) == ("Face", "mdi:face-recognition")


def test_upload_event_defaults() -> None:
    upload = EventSettings(target_type="upload")
    assert upload.is_upload
    assert not upload.is_plate
    assert not upload.has_target
    assert upload.event == "upload"
    assert upload.ocr_field_ids == []
    assert upload.icon == "mdi:folder-upload"
    assert upload.image_name_re.pattern == ".+", "any file, no datetime needed"
    assert upload.default_description == "Upload"


def test_upload_event_can_narrow_files_without_datetime() -> None:
    upload = EventSettings.model_validate({"target_type": "upload", "image_name_re": r".*\.jpg"})
    assert upload.image_name_re.pattern == r".*\.jpg"


def _settings(events: list[dict[str, Any]]) -> Any:
    from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

    from anpr2mqtt.settings import Settings

    class InitOnlySettings(Settings):
        model_config = SettingsConfigDict(yaml_file=None)

        @classmethod
        def settings_customise_sources(  # type: ignore[override]
            cls, _settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource, **_kwargs: Any
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (init_settings,)

    return InitOnlySettings(mqtt={"user": "u", "pass": "p"}, events=events)


def test_uploads_told_apart_by_id() -> None:
    uploads: list[dict[str, Any]] = [
        {"target_type": "upload", "watch_path": "/ftp/a"},
        {"target_type": "upload", "watch_path": "/ftp/b"},
    ]
    with pytest.raises(ValidationError, match=r"own id.*\['upload'\]"):
        _settings(uploads)
    uploads[1]["id"] = "b"
    assert [e.upload_name for e in _settings(uploads).events] == ["upload", "upload_b"]
    uploads[0]["id"] = "b"
    with pytest.raises(ValidationError, match=r"\['upload_b'\]"):
        _settings(uploads)


def test_id_only_for_uploads() -> None:
    with pytest.raises(ValidationError, match="id is only for uploads"):
        EventSettings(target_type="face", id="x")
    with pytest.raises(ValidationError, match="id"):
        EventSettings(target_type="upload", id="not ok")


def test_upload_name_may_repeat_another_kind_of_event() -> None:
    events = [{"camera": "a", "target_type": "face", "event": "upload"}, {"target_type": "upload", "watch_path": "/ftp"}]
    assert len(_settings(events).events) == 2


def test_camera_optional_only_for_uploads() -> None:
    assert EventSettings(target_type="upload").camera is None
    assert EventSettings(target_type="upload", camera="shed").camera == "shed"
    assert EventSettings(target_type="face").camera == "driveway"
    assert EventSettings().camera == "driveway"


def test_other_events_still_need_datetime() -> None:
    with pytest.raises(ValidationError, match="'dt'"):
        EventSettings.model_validate({"target_type": "face", "image_name_re": r".*\.jpg"})


def test_missing_target_suggests_target_type() -> None:
    with pytest.raises(ValidationError, match="set target_type"):
        EventSettings(image_name_re=re.compile(r"(?P<dt>[0-9]{17})_SCENE_CHANGE_DETECTION\.jpg"))


def test_non_plate_event_name_and_ocr_default_from_target_type() -> None:
    face = EventSettings(target_type="face", image_name_re=re.compile(r"(?P<dt>[0-9]{17})_FACE\.jpg"))
    assert face.event == "face"
    assert face.ocr_field_ids == []
    assert face.default_description == "Face"
    plate = EventSettings()
    assert plate.event == "anpr"
    assert plate.ocr_field_ids == ["hik_direction"]
    named = EventSettings(
        event="front_face",
        target_type="face",
        ocr_field_ids=["hik_direction"],
        image_name_re=re.compile(r"(?P<dt>[0-9]{17})_FACE\.jpg"),
    )
    assert (named.event, named.ocr_field_ids) == ("front_face", ["hik_direction"])


@pytest.mark.parametrize("name", ["front/door", "front#", "a+b", "front door", "../x", "x.y", "", "x" * 65])
def test_invalid_names_rejected(name: str) -> None:
    with pytest.raises(ValidationError, match="letters, digits"):
        CameraSettings(name=name)
    with pytest.raises(ValidationError, match="letters, digits"):
        EventSettings(event=name)
    with pytest.raises(ValidationError, match="letters, digits"):
        EventSettings(camera=name)
    with pytest.raises(ValidationError, match="letters, digits"):
        EventSettings(target_type=name, image_name_re=re.compile(r"(?P<dt>[0-9]{17})\.jpg"))


@pytest.mark.parametrize("name", ["driveway", "Front_Door", "back-gate", "cam2"])
def test_valid_names_accepted(name: str) -> None:
    assert CameraSettings(name=name).name == name
    assert EventSettings(event=name, camera=name).event == name
