import pathlib
import re

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, YamlConfigSettingsSource

from anpr2mqtt.settings import EventSettings, Settings

EXAMPLES_ROOT = "examples"

examples = [str(p.name) for p in pathlib.Path(EXAMPLES_ROOT).iterdir() if p.name.startswith("anpr2mqtt.yaml")]


def test_image_name_re_missing_required_group() -> None:
    """Regex without 'dt' or 'target' named group raises ValueError (settings.py line 66)."""
    with pytest.raises(ValidationError, match="missing required named groups"):
        EventSettings(
            camera="cam",
            event="anpr",
            image_name_re=re.compile(r"(?P<notdt>[0-9]{17})_(?P<notarget>[A-Z0-9]+)\.jpg"),
        )


@pytest.mark.parametrize("config_name", examples)
def test_load_yaml(config_name: str) -> None:
    config_path = pathlib.Path(EXAMPLES_ROOT) / config_name

    class YamlOnlySettings(Settings):
        @classmethod
        def settings_customise_sources(  # type: ignore[override]
            cls,
            settings_cls: type[BaseSettings],
            **_kwargs: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls, yaml_file=config_path),)

    settings = YamlOnlySettings()  # type: ignore[call-arg]

    assert settings.mqtt.password is not None
    assert settings.events[0].watch_path is not None
    if settings.targets:
        assert settings.targets["plate"].groups is not None
