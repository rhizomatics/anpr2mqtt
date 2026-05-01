import datetime as dt
import threading
from typing import Any

import structlog

from anpr2mqtt.api_client import APIClient, DVLAClient
from anpr2mqtt.normalizers import Normalizer, fuzzy_match
from anpr2mqtt.settings import TARGET_TYPE_PLATE, DVLASettings, EventSettings

log = structlog.get_logger()


def build_dvla_client(dvla_settings: DVLASettings, target_type: str | None = None) -> APIClient | None:
    if not dvla_settings.api_key:
        return None
    if target_type is not None and target_type != TARGET_TYPE_PLATE:
        return None
    return DVLAClient(
        dvla_settings.api_key,
        cache_type=dvla_settings.cache_type,
        cache_ttl=dvla_settings.cache_ttl,
        cache_dir=dvla_settings.cache_dir,
        verify_plate=dvla_settings.verify_plate,
    )


def correct_against_good_read(
    plate: str,
    cached: tuple[str, dt.datetime] | None,
    ttl: int,
    tolerance: int,
    normalizer: Normalizer | None = None,
) -> str:
    if ttl <= 0 or tolerance <= 0 or cached is None:
        return plate
    good_plate, good_ts = cached
    age = (dt.datetime.now(dt.UTC) - good_ts).total_seconds()
    if age > ttl:
        return plate
    candidates: list[str] = [good_plate]
    alt_candidate: str | None = normalizer.normalize(plate) if normalizer else None
    if alt_candidate:
        candidates.append(alt_candidate)

    if fuzzy_match(plate, tolerance, candidates) is not None and plate != good_plate:
        log.info("Correcting %s -> %s via last known good (age=%.1fs)", plate, good_plate, age)
        return good_plate
    return plate


class CameraGatekeeper:
    """Camera-level duplicate gate.

    Suppresses events within the visit gap window even when the plate string differs
    (e.g. two bad reads of the same vehicle). Exception: if the last published event
    had no DVLA enrichment, one replacement is allowed through so a subsequently-enriched
    read can supersede the raw notification.
    """

    def __init__(self) -> None:
        self._last_time: dt.datetime | None = None
        self._last_had_dvla: bool = False
        self._lock = threading.Lock()

    def allow(self, event_time: dt.datetime, has_dvla: bool, gap_seconds: int) -> bool:
        """Return True (and update state) if this event should be published."""
        with self._lock:
            if self._last_time is None or gap_seconds <= 0:
                self._last_time = event_time
                self._last_had_dvla = has_dvla
                return True

            elapsed = (event_time - self._last_time).total_seconds()

            if elapsed < 0 or elapsed >= gap_seconds:
                self._last_time = event_time
                self._last_had_dvla = has_dvla
                return True

            # Within gap — prior had DVLA enrichment: suppress
            if self._last_had_dvla:
                log.info(
                    "Camera gate: suppressing within-gap event (prior enriched, elapsed=%.1fs gap=%ds)",
                    elapsed,
                    gap_seconds,
                )
                return False

            # Prior lacked enrichment: allow one replacement
            log.info(
                "Camera gate: allowing replacement (prior unenriched, elapsed=%.1fs gap=%ds)",
                elapsed,
                gap_seconds,
            )
            self._last_time = event_time
            self._last_had_dvla = has_dvla
            return True


class AutoclearTimer:
    """Manages a cancel-and-restart debounce timer for a single autoclear slot."""

    def __init__(self) -> None:
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def schedule(self, event_config: EventSettings, callback: Any, label: str) -> None:
        autoclear = event_config.autoclear
        if not autoclear.enabled:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(autoclear.post_event, callback)
            self._timer.daemon = True
            self._timer.start()
        log.debug("Autoclear scheduled in %ss for %s", autoclear.post_event, label)
