import json
from pathlib import Path
from unittest.mock import Mock

from watchdog.events import DirModifiedEvent, FileClosedEvent

from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.image_stats import ImageStats
from anpr2mqtt.settings import EventSettings, HomeAssistantSettings
from anpr2mqtt.upload_handler import UploadHandler

STATE_TOPIC = "anpr2mqtt/uploads/upload_ftp/state"


def _handler(watch_path: Path, watch_tree: bool = False, image_name_re: str | None = None) -> UploadHandler:
    publisher = HomeAssistantPublisher(Mock(), HomeAssistantSettings(), image_stats=ImageStats())
    event_config = EventSettings.model_validate(
        {"id": "ftp", "target_type": "upload", "watch_path": watch_path, "watch_tree": watch_tree}
        | ({"image_name_re": image_name_re} if image_name_re else {})
    )
    return UploadHandler(publisher, STATE_TOPIC, event_config)


def _states(handler: UploadHandler) -> list[dict[str, object]]:
    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    return [json.loads(c.kwargs["payload"]) for c in publish.call_args_list if c.args[0] == STATE_TOPIC]


def test_every_file_counted(tmp_path: Path) -> None:
    handler = _handler(tmp_path, watch_tree=True)
    root = tmp_path.resolve()
    for name in ("10.0.0.1_01_20261127071024588_SCENE_CHANGE_DETECTION.jpg", "notes.txt", "sub/clip.mp4"):
        handler.dispatch(FileClosedEvent(str(root / name)))

    states = _states(handler)
    assert [s["total"] for s in states] == [1, 2, 3]
    assert states[-1]["today"] == 3
    assert states[-1]["last_file"] == "sub/clip.mp4", "relative to the watch path, so the subdirectory shows"
    assert states[-1]["last_received"] is not None
    assert states[-1]["event"] == "upload"
    assert states[-1]["id"] == "ftp"


def test_only_matching_files_counted(tmp_path: Path) -> None:
    handler = _handler(tmp_path, image_name_re=r".*\.jpg")
    root = tmp_path.resolve()
    handler.dispatch(FileClosedEvent(str(root / "a.jpg")))
    handler.dispatch(FileClosedEvent(str(root / "a.tmp")))
    handler.dispatch(FileClosedEvent(str(tmp_path.parent.resolve() / "elsewhere.jpg")))
    assert [s["total"] for s in _states(handler)] == [1]


def test_directories_ignored(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    handler.on_closed(DirModifiedEvent(str(tmp_path.resolve() / "sub")))  # type: ignore[arg-type]
    assert _states(handler) == []


def test_count_failure_logged_not_raised(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    handler.publisher.image_stats = Mock(record=Mock(side_effect=OSError("disk full")))
    handler.on_closed(FileClosedEvent(str(tmp_path.resolve() / "a.jpg")))
    assert _states(handler) == []
