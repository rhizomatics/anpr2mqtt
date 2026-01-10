import pathlib

import pytest
from pydantic_settings import YamlConfigSettingsSource

from anpr2mqtt.settings import Settings

EXAMPLES_ROOT = "examples"

examples = [str(p.name) for p in pathlib.Path(EXAMPLES_ROOT).iterdir() if p.name.endswith(".yaml")]


@pytest.mark.parametrize("config_name", examples)
def test_load_yaml(config_name: str) -> None:
    config_path = pathlib.Path(EXAMPLES_ROOT) / config_name

    settings = YamlConfigSettingsSource(Settings, config_path)

    assert settings()["mqtt"]["password"] is not None
    assert settings()["file_system"]["watch_path"] is not None
