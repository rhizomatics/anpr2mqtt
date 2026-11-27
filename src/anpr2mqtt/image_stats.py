"""Counts of images received, per event, per camera and overall, for health checks such as no images today

Counted as images arrive, whether or not they're published as an event, since a duplicate, an ignored plate or a
face's background image still shows the camera is sending them. Kept in a file, so a restart doesn't reset them.
"""

import datetime as dt
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import structlog
import tzlocal

log = structlog.get_logger()

ALL: str = "all"


def local_now() -> dt.datetime:
    """In the local timezone, as image name timestamps are, so days and weeks start at local midnight"""
    return dt.datetime.now(tz=tzlocal.get_localzone())


@dataclass
class Counts:
    total: int = 0
    last_received: str | None = None
    day: str | None = None
    today: int = 0
    week: str | None = None
    this_week: int = 0

    def add(self, now: dt.datetime) -> None:
        day, week = _day(now), _week(now)
        self.today = self.today + 1 if self.day == day else 1
        self.this_week = self.this_week + 1 if self.week == week else 1
        self.day, self.week = day, week
        self.total += 1
        self.last_received = now.isoformat()

    def as_attributes(self, now: dt.datetime) -> dict[str, Any]:
        """Today's and this week's counts are 0 once the day or week has moved on without any images"""
        return {
            "today": self.today if self.day == _day(now) else 0,
            "this_week": self.this_week if self.week == _week(now) else 0,
            "total": self.total,
            "last_received": self.last_received,
        }


def _day(now: dt.datetime) -> str:
    return now.date().isoformat()


def _week(now: dt.datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


class ImageStats:
    def __init__(self, path: Path | None = None) -> None:
        self.path: Path | None = path
        self._counts: dict[str, Counts] = {}
        self._lock = threading.Lock()
        self._load()

    @staticmethod
    def event_key(event: str, camera: str) -> str:
        return f"event:{event}/{camera}"

    @staticmethod
    def camera_key(camera: str) -> str:
        return f"camera:{camera}"

    def record(self, event: str, camera: str, now: dt.datetime | None = None) -> None:
        now = now or local_now()
        with self._lock:
            for key in (self.event_key(event, camera), self.camera_key(camera), ALL):
                self._counts.setdefault(key, Counts()).add(now)
            self._save()

    def attributes(self, event: str, camera: str, now: dt.datetime | None = None) -> dict[str, Any]:
        """Build the images attribute for an event's entities, with its camera's and overall counts alongside its own"""
        now = now or local_now()
        with self._lock:
            return {
                scope: self._counts.get(key, Counts()).as_attributes(now)
                for scope, key in (("event", self.event_key(event, camera)), ("camera", self.camera_key(camera)), (ALL, ALL))
            }

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            with self.path.open("r") as f:
                self._counts = {key: Counts(**counts) for key, counts in json.load(f).items()}
            log.info("Loaded image counts from %s", self.path)
        except Exception as e:
            log.warning("Unable to load image counts from %s, starting afresh: %s", self.path, e)

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp: Path = self.path.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump({key: asdict(counts) for key, counts in self._counts.items()}, f)
            tmp.replace(self.path)
        except Exception as e:
            log.warning("Unable to save image counts to %s: %s", self.path, e)
