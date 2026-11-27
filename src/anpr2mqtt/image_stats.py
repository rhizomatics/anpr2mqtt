"""Counts, and sizes, of images received per event, and of files uploaded and removed, for health checks

Counted as images arrive, whether or not they're published as an event, since a duplicate, an ignored plate or a
face's background image still shows the camera is sending them. Counts across a camera, or everything landing in a
directory, come from an upload event watching that directory. Kept in a file, so a restart doesn't reset them.
"""

import datetime as dt
import json
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import structlog
import tzlocal

log = structlog.get_logger()

EVENT_KEY_PREFIX: str = "event:"
UPLOAD_KEY_PREFIX: str = "upload:"
REMOVED_KEY_PREFIX: str = "removed:"


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
    last_file: str | None = None
    total_bytes: int = 0
    today_bytes: int = 0
    this_week_bytes: int = 0

    def add(self, now: dt.datetime, file_name: str | None = None, size: int = 0) -> None:
        day, week = _day(now), _week(now)
        same_day, same_week = self.day == day, self.week == week
        self.today = self.today + 1 if same_day else 1
        self.today_bytes = self.today_bytes + size if same_day else size
        self.this_week = self.this_week + 1 if same_week else 1
        self.this_week_bytes = self.this_week_bytes + size if same_week else size
        self.day, self.week = day, week
        self.total += 1
        self.total_bytes += size
        self.last_received = now.isoformat()
        self.last_file = file_name

    def as_attributes(self, now: dt.datetime, prefix: str = "") -> dict[str, Any]:
        """Today's and this week's counts are 0 once the day or week has moved on without any images"""
        same_day, same_week = self.day == _day(now), self.week == _week(now)
        return {
            f"{prefix}today": self.today if same_day else 0,
            f"{prefix}today_bytes": self.today_bytes if same_day else 0,
            f"{prefix}this_week": self.this_week if same_week else 0,
            f"{prefix}this_week_bytes": self.this_week_bytes if same_week else 0,
            f"{prefix}total": self.total,
            f"{prefix}total_bytes": self.total_bytes,
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
        return f"{EVENT_KEY_PREFIX}{event}/{camera}"

    @staticmethod
    def upload_key(upload_name: str) -> str:
        """By upload name, event and id, since a landing zone may be shared by several cameras, or belong to none"""
        return f"{UPLOAD_KEY_PREFIX}{upload_name}"

    @staticmethod
    def removed_key(upload_name: str) -> str:
        return f"{REMOVED_KEY_PREFIX}{upload_name}"

    def record(self, key: str, now: dt.datetime | None = None, file_name: str | None = None, size: int = 0) -> None:
        now = now or local_now()
        with self._lock:
            self._counts.setdefault(key, Counts()).add(now, file_name, size)
            self._save()

    def counts(self, key: str) -> Counts:
        """Copy the counts for a key, so they can be read outside the lock"""
        with self._lock:
            return Counts(**asdict(self._counts.get(key, Counts())))

    def attributes(self, key: str, now: dt.datetime | None = None) -> dict[str, Any]:
        """Build the images attribute for an event's entities, counting its own images only"""
        counts: Counts = self.counts(key)
        return {**counts.as_attributes(now or local_now()), "last_received": counts.last_received}

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            known: set[str] = {f.name for f in fields(Counts)}
            with self.path.open("r") as f:
                # camera and overall counts from 1.4.0 are dropped, since upload events count those now
                self._counts = {
                    key: Counts(**{k: v for k, v in counts.items() if k in known})
                    for key, counts in json.load(f).items()
                    if key.startswith((EVENT_KEY_PREFIX, UPLOAD_KEY_PREFIX, REMOVED_KEY_PREFIX))
                }
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
