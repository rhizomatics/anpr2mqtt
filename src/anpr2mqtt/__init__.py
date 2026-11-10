from usingversion import getattr_with_version

from anpr2mqtt.app import run as run
from anpr2mqtt.tools import tools as tools

__getattr__ = getattr_with_version("anpr2mqtt", __file__, __name__)
