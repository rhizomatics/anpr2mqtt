from pydantic_settings import CliApp
from usingversion import getattr_with_version  # type:ignore[import-not-found]

from anpr2mqtt.app import Anpr2MQTT
from anpr2mqtt.tools import Tools

__getattr__ = getattr_with_version("anpr2mqtt", __file__, __name__)


def run() -> None:
    CliApp.run(model_cls=Anpr2MQTT)


def tools() -> None:
    CliApp.run(model_cls=Tools)
