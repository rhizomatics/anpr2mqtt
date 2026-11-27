import re
from pathlib import Path

import structlog
from watchdog.events import FileClosedEvent, RegexMatchingEventHandler

from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import EventSettings

log = structlog.get_logger()


class UploadHandler(RegexMatchingEventHandler):
    """Counts every file landing in a watch path, such as an ftp landing zone, without looking inside it

    Alongside a directory's other events, it shows uploads are still arriving even when none of them are plates, such
    as only scene changes or snapshots, or on its own, as a general purpose landing zone monitor. Not tied to a
    camera, since several cameras may share a landing zone, or one camera upload to several.
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

    def on_closed(self, event: FileClosedEvent) -> None:
        if event.is_directory:
            return
        file_path = Path(str(event.src_path))
        log.debug("Upload detected: %s", file_path)
        try:
            self.publisher.record_upload(self.event_config, self._relative_name(file_path))
            self.publisher.post_upload_state(self.state_topic, self.event_config)
        except Exception as e:
            log.error("Failed to count upload %s: %s", file_path, e, exc_info=1)

    def _relative_name(self, file_path: Path) -> str:
        """Relative to the watch path, so a file in a watched tree's subdirectory says which one"""
        try:
            return str(file_path.relative_to(self.watch_root))
        except ValueError:
            return file_path.name
