"""Liveness heartbeat: the main loop touches a file, and the healthcheck checks how recently.

Checking a local file means the container healthcheck needs no MQTT credentials or extra system
packages, and fails if the main loop stalls or the broker connection is lost, not only on a crash.
"""

import os
import tempfile
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

HEARTBEAT_ENV = "ANPR2MQTT_HEARTBEAT_FILE"
HEARTBEAT_INTERVAL = 10  # seconds between touches of the heartbeat file
DEFAULT_MAX_AGE = 60  # seconds, several missed beats before the healthcheck fails


def heartbeat_path() -> Path:
    return Path(os.environ.get(HEARTBEAT_ENV) or Path(tempfile.gettempdir()) / "anpr2mqtt.heartbeat")


class Heartbeat:
    """Touches the heartbeat file at most once per interval, so it can be called on every loop pass"""

    def __init__(self, path: Path | None = None, interval: float = HEARTBEAT_INTERVAL) -> None:
        self.path: Path = path or heartbeat_path()
        self.interval: float = interval
        self.last_beat: float | None = None

    def beat(self) -> None:
        now: float = time.monotonic()
        if self.last_beat is not None and now - self.last_beat < self.interval:
            return
        try:
            self.path.touch()
            self.last_beat = now
        except OSError as e:
            log.warning("Unable to write heartbeat file %s: %s", self.path, e)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.last_beat = None


def heartbeat_age(path: Path | None = None) -> float | None:
    """Seconds since the last heartbeat, or None if there has never been one"""
    try:
        return time.time() - (path or heartbeat_path()).stat().st_mtime
    except FileNotFoundError:
        return None
