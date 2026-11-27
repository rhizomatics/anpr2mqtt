from pathlib import Path
from typing import Any

import pytest

from anpr2mqtt.settings import (
    CameraSettings,
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
