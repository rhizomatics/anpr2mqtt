import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

import structlog
import tzlocal
from rapidfuzz.distance import Levenshtein

from anpr2mqtt.settings import (
    Target,
    TargetSettings,
    TrackerSettings,
)

log = structlog.get_logger()


@dataclass
class Sighting:
    target: Target
    uncorrected: str | None = None
    ignore: bool = False
    previous_sightings: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = self.target.as_dict()
        result.update({"orig_target": self.uncorrected, "ignore": self.ignore})
        return result


class Tracker:
    def __init__(self, target_type: str, tracker_config: TrackerSettings, target_config: TargetSettings | None = None) -> None:
        self.target_type: str = target_type
        self.tracker_config: TrackerSettings = tracker_config
        self.target_config: TargetSettings | None = target_config

    def all(self, entity_id_only: bool = False) -> list[Target]:
        results: list[Target] = []
        if not self.target_config:
            return results
        results.extend(target for target in self.target_config.known.values() if target.entity_id or not entity_id_only)
        results.extend(target for target in self.target_config.dangerous.values() if target.entity_id or not entity_id_only)
        return results

    def history(self, target_id: str, target_type: str) -> list[str]:
        target_id = target_id or "UNKNOWN"
        target_type_path = self.tracker_config.data_dir / target_type
        target_type_path.mkdir(exist_ok=True)
        target_file = target_type_path / f"{target_id}.json"

        try:
            if target_file.exists():
                with target_file.open("r") as f:
                    return json.load(f)

        except Exception as e:
            log.exception("Failed to find sightings for %s:%s", target_id, e)
        return []

    def record(self, target: str, target_type: str, event_dt: dt.datetime | None) -> dict[str, Any]:
        target = target or "UNKNOWN"
        target_type_path = self.tracker_config.data_dir / target_type
        target_type_path.mkdir(exist_ok=True)
        target_file = target_type_path / f"{target}.json"
        sightings = self.history(target, target_type)
        time_analysis: dict[str, Any] = {}
        try:
            time_analysis = compute_time_analysis(sightings, event_dt)
            sightings.append(event_dt.isoformat() if event_dt else dt.datetime.now(tz=tzlocal.get_localzone()).isoformat())
            with target_file.open("w") as f:
                json.dump(sightings, f)
        except Exception as e:
            log.exception("Failed to record sightings for %s:%s", target, e)
        return time_analysis

    def find(self, target_id: str) -> Sighting:
        result: Sighting = Sighting(
            target=Target(id=target_id, target_type=self.target_type, priority="high"), uncorrected=target_id
        )
        if not target_id or self.target_config is None:
            # empty dict to make home assistant template logic easier
            return result

        lookup_id = target_id
        for corrected_target, patterns in self.target_config.correction.items():
            if any(re.match(pat, target_id) for pat in patterns):
                result.target.id = corrected_target
                lookup_id = corrected_target
                log.info("Corrected target %s -> %s", target_id, lookup_id)
                break
        for pat in self.target_config.ignore:
            if re.match(pat, target_id):
                log.info("Ignoring %s matching ignore pattern %s", target_id, pat)
                result.ignore = True
                result.target.priority = "low"
                if result.target.group is None:  # not yet found in registered lists
                    result.target.description = "Ignored"
                break
        max_dist = self.target_config.auto_match_tolerance
        target: Target | None = None
        registered_match: str | None = (
            lookup_id
            if lookup_id in self.target_config.dangerous
            else (_fuzzy_match(lookup_id, max_dist, list(self.target_config.dangerous.keys())) if max_dist > 0 else None)
        )
        if registered_match:
            target = self.target_config.dangerous[registered_match]
        if registered_match is None:
            registered_match = (
                lookup_id
                if lookup_id in self.target_config.known
                else (_fuzzy_match(lookup_id, max_dist, list(self.target_config.known.keys())) if max_dist > 0 else None)
            )
            if registered_match:
                target = self.target_config.known[registered_match]
        if target:
            if registered_match != lookup_id:
                log.info(
                    "Fuzzy-matched %s to registered plate %s (distance %s)",
                    lookup_id,
                    registered_match,
                    Levenshtein.distance(lookup_id, target.id),
                )
            result.target = target
        return result


def compute_time_analysis(sightings: list[str], current_dt: dt.datetime | None = None) -> dict[str, Any]:
    """Derive visit history and time-of-day statistics from previous sightings.

    Called before the current visit is appended, so all counts/times reflect prior history only.

    Returns a dict with:
      - previous_sightings: int — number of times seen before the current visit
      - last_seen: ISO datetime string of the most recent prior sighting, or None
      - hourly_counts: dict[int,int] of 24 ints, index = hour (0-23)
      - earliest_time: "HH:MM:SS" of the earliest time-of-day previously seen, or None
      - latest_time:   "HH:MM:SS" of the latest time-of-day previously seen, or None
      - within_time_range: bool — current time falls within [earliest, latest], or None if no history
    """
    hourly_counts: dict[int, int] = {}
    times: list[dt.time] = []
    last_seen: str | None = sightings[-1] if sightings else None
    for s in sightings:
        try:
            ts: dt.datetime = dt.datetime.fromisoformat(s)
            hourly_counts.setdefault(ts.hour, 0)
            hourly_counts[ts.hour] += 1
            times.append(ts.replace(tzinfo=None).time())
        except Exception as e:
            log.warning("Skipping unparsable sighting timestamp %r: %s", s, e)

    earliest = min(times) if times else None
    latest = max(times) if times else None

    result = {
        "previous_sightings": len(sightings),
        "last_seen": last_seen,
        "hourly_counts": hourly_counts,
        "earliest_time": earliest.isoformat() if earliest else None,
        "latest_time": latest.isoformat() if latest else None,
    }
    if current_dt is not None:
        if earliest is not None and latest is not None:
            current_t = current_dt.replace(tzinfo=None).time()
            result["within_time_range"] = earliest <= current_t <= latest
        else:
            result["within_time_range"] = None

    return result


def _fuzzy_match(target_id: str, max_dist: int, candidates: list[str]) -> str | None:
    """Return the closest key in candidates within max_dist edits, or None."""
    best: str | None = None
    best_dist = max_dist + 1
    for candidate in candidates:
        d = Levenshtein.distance(target_id, candidate)
        if d < best_dist:
            best_dist = d
            best = candidate
    return best if best_dist <= max_dist else None
