import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from watchdog.events import FileClosedEvent, FileCreatedEvent, FileDeletedEvent, FileMovedEvent, RegexMatchingEventHandler

from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import EventSettings

if TYPE_CHECKING:
    from collections.abc import Iterable

log = structlog.get_logger()


class UploadHandler(RegexMatchingEventHandler):
    """Counts every file landing in, or removed from, a watch path, such as an ftp landing zone, without looking inside

    Alongside a directory's other events, it shows uploads are still arriving even when none of them are plates, such
    as only scene changes or snapshots, or on its own, as a general purpose landing zone monitor. Not tied to a
    camera, since several cameras may share a landing zone, or one camera upload to several.

    The matching files currently in the watch path are found by a scan at startup, kept up to date as files come and
    go, and scanned again each midnight, to correct for anything missed, such as a whole directory moved away.
    """

    def __init__(
        self,
        publisher: HomeAssistantPublisher,
        state_topic: str,
        event_config: EventSettings,
    ) -> None:
        self.watch_root: Path = event_config.watch_path.resolve()
        fqre: str = f"{re.escape(str(self.watch_root))}/{event_config.image_name_re.pattern}"
        super().__init__(regexes=[fqre], ignore_directories=True, case_sensitive=True)
        log.debug("Counting uploads matching %s", fqre)
        self.publisher: HomeAssistantPublisher = publisher
        self.state_topic: str = state_topic
        self.event_config: EventSettings = event_config
        # matching files now in the watch path, with their sizes, and the sum of those sizes
        self._files: dict[str, int] = {}
        self._bytes: int = 0
        self._lock = threading.Lock()

    def matches(self, path: str) -> bool:
        return any(regex.match(path) for regex in self.regexes)

    def scan(self) -> None:
        """Find every matching file now in the watch path, replacing what's known from file events"""
        started: float = time.monotonic()
        found: dict[str, int] = {}
        try:
            candidates: Iterable[Path] = (
                self.watch_root.rglob("*") if self.event_config.watch_tree else self.watch_root.iterdir()
            )
            for path in candidates:
                try:
                    if path.is_file() and self.matches(str(path)):
                        found[str(path)] = path.stat().st_size
                except OSError:
                    continue  # removed while scanning
        except OSError as e:
            log.warning("Unable to scan %s for current uploads: %s", self.watch_root, e)
            return
        with self._lock:
            self._files = found
            self._bytes = sum(found.values())
        log.info(
            "Found %s files, %s bytes, in %s in %.1fs",
            len(found),
            self._bytes,
            self.watch_root,
            time.monotonic() - started,
        )

    def current(self) -> tuple[int, int]:
        """Count and total size of the matching files now in the watch path"""
        with self._lock:
            return len(self._files), self._bytes

    def publish_state(self) -> None:
        files, size = self.current()
        self.publisher.post_upload_state(self.state_topic, self.event_config, current_files=files, current_bytes=size)

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        """Note a file being written, or moved in from elsewhere, counted as an upload only once closed"""
        if event.is_directory:
            return
        size: int = self._add(str(event.src_path))
        if size:
            # moved in whole, so there won't be a close to publish it
            self._publish(str(event.src_path))

    def on_closed(self, event: FileClosedEvent) -> None:
        if event.is_directory:
            return
        path: str = str(event.src_path)
        log.debug("Upload detected: %s", path)
        size: int = self._add(path)
        self._record_upload(path, size)
        self._publish(path)

    def on_deleted(self, event: FileDeletedEvent) -> None:  # type: ignore[override]
        """Count a file deleted, or moved out of the watch path, as removed"""
        if event.is_directory:
            return
        path: str = str(event.src_path)
        log.debug("Upload removed: %s", path)
        self._record_removal(path, self._remove(path))
        self._publish(path)

    def on_moved(self, event: FileMovedEvent) -> None:  # type: ignore[override]
        """Follow a rename, an upload if it now matches and didn't before, or a removal if the reverse"""
        if event.is_directory:
            return
        src, dest = str(event.src_path), str(event.dest_path)
        was, now = self.matches(src), self.matches(dest)
        if was:
            size: int = self._remove(src)
            if not now:
                self._record_removal(src, size)
        if now:
            size = self._add(dest)
            if not was:
                self._record_upload(dest, size)
        if was != now:
            self._publish(dest)

    def _add(self, path: str) -> int:
        try:
            size: int = Path(path).stat().st_size
        except OSError:
            size = 0
        with self._lock:
            self._bytes += size - self._files.get(path, 0)
            self._files[path] = size
        return size

    def _remove(self, path: str) -> int:
        with self._lock:
            size: int = self._files.pop(path, 0)
            self._bytes -= size
        return size

    def _record_upload(self, path: str, size: int) -> None:
        try:
            self.publisher.record_upload(self.event_config, self._relative_name(path), size)
        except Exception as e:
            log.error("Failed to count upload %s: %s", path, e, exc_info=1)

    def _record_removal(self, path: str, size: int) -> None:
        try:
            self.publisher.record_removal(self.event_config, self._relative_name(path), size)
        except Exception as e:
            log.error("Failed to count removal of %s: %s", path, e, exc_info=1)

    def _publish(self, path: str) -> None:
        try:
            self.publish_state()
        except Exception as e:
            log.error("Failed to publish upload state after %s: %s", path, e, exc_info=1)

    def _relative_name(self, path: str) -> str:
        """Relative to the watch path, so a file in a watched tree's subdirectory says which one"""
        file_path = Path(path)
        try:
            return str(file_path.relative_to(self.watch_root))
        except ValueError:
            return file_path.name
