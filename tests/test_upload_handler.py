import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from watchdog.events import (
    DirDeletedEvent,
    DirModifiedEvent,
    FileClosedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
)

from anpr2mqtt.app import rescan_uploads
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


def _states(handler: UploadHandler) -> list[dict[str, Any]]:
    publish: Mock = handler.publisher.client.publish  # type: ignore[assignment]
    return [json.loads(c.kwargs["payload"]) for c in publish.call_args_list if c.args[0] == STATE_TOPIC]


def _write(path: Path, size: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return str(path)


def test_every_file_counted_with_its_size(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path, watch_tree=True)
    for name, size in (("10.0.0.1_01_20261127071024588_SCENE_CHANGE_DETECTION.jpg", 10), ("notes.txt", 5)):
        handler.dispatch(FileClosedEvent(_write(root / name, size)))
    handler.dispatch(FileClosedEvent(_write(root / "sub" / "clip.mp4", 100)))

    states = _states(handler)
    assert [s["total"] for s in states] == [1, 2, 3]
    assert states[-1]["today"] == 3
    assert (states[-1]["total_bytes"], states[-1]["today_bytes"]) == (115, 115)
    assert (states[-1]["current"], states[-1]["current_bytes"]) == (3, 115)
    assert states[-1]["last_file"] == "sub/clip.mp4", "relative to the watch path, so the subdirectory shows"
    assert states[-1]["last_received"] is not None
    assert states[-1]["event"] == "upload"
    assert states[-1]["id"] == "ftp"


def test_scan_finds_files_already_there(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write(root / "a.jpg", 10)
    _write(root / "b.jpg", 20)
    _write(root / "skip.tmp", 99)
    _write(root / "sub" / "c.jpg", 40)
    handler = _handler(tmp_path, image_name_re=r".*\.jpg")
    handler.scan()
    assert handler.current() == (2, 30), "only matching files, and not in subdirectories unless watching the tree"

    tree = _handler(tmp_path, watch_tree=True, image_name_re=r".*\.jpg")
    tree.scan()
    assert tree.current() == (3, 70)
    tree.publish_state()
    state = _states(tree)[-1]
    assert (state["current"], state["current_bytes"], state["total"]) == (3, 70, 0), "found, not received"


def test_scan_of_missing_path_keeps_what_was_known(tmp_path: Path) -> None:
    handler = _handler(tmp_path / "missing")
    handler.scan()
    assert handler.current() == (0, 0)


def test_removal_counted_with_size_known_before(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path)
    path = _write(root / "a.jpg", 25)
    handler.scan()
    Path(path).unlink()
    handler.dispatch(FileDeletedEvent(path))

    state = _states(handler)[-1]
    assert (state["current"], state["current_bytes"]) == (0, 0)
    assert (state["removed_today"], state["removed_total"], state["removed_total_bytes"]) == (1, 1, 25)
    assert state["last_removed_file"] == "a.jpg"
    assert state["last_removed"] is not None
    assert state["total"] == 0, "a removal isn't an upload"


def test_created_tracked_as_current_but_counted_only_when_closed(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path)
    path = _write(root / "a.jpg", 0)
    handler.dispatch(FileCreatedEvent(path))
    assert handler.current() == (1, 0)
    assert _states(handler) == [], "empty while being written, so nothing published yet"
    _write(root / "a.jpg", 30)
    handler.dispatch(FileClosedEvent(path))
    assert handler.current() == (1, 30), "size updated, not counted twice"
    assert _states(handler)[-1]["total"] == 1


def test_moved_in_whole_published_as_current(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    handler.dispatch(FileCreatedEvent(_write(tmp_path.resolve() / "a.jpg", 30)))
    state = _states(handler)[-1]
    assert (state["current"], state["current_bytes"], state["total"]) == (1, 30, 0)


def test_rename_within_matches_keeps_counts(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path)
    old = _write(root / "a.jpg", 30)
    handler.scan()
    new = str(root / "b.jpg")
    Path(old).rename(new)
    handler.dispatch(FileMovedEvent(old, new))
    assert handler.current() == (1, 30)
    assert _states(handler) == [], "nothing changed worth publishing"


def test_rename_from_temporary_name_is_an_upload(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path, image_name_re=r".*\.jpg$")
    temp = _write(root / ".upload.a.jpg.part", 30)
    handler.dispatch(FileClosedEvent(temp))
    assert _states(handler) == [], "temporary name doesn't match"
    final = str(root / "a.jpg")
    Path(temp).rename(final)
    handler.dispatch(FileMovedEvent(temp, final))
    state = _states(handler)[-1]
    assert (state["total"], state["total_bytes"], state["current"]) == (1, 30, 1)
    assert state["last_file"] == "a.jpg"


def test_rename_to_unmatched_name_is_a_removal(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path, image_name_re=r".*\.jpg$")
    old = _write(root / "a.jpg", 30)
    handler.scan()
    new = str(root / "a.jpg.done")
    Path(old).rename(new)
    handler.dispatch(FileMovedEvent(old, new))
    state = _states(handler)[-1]
    assert (state["current"], state["removed_total"], state["removed_total_bytes"]) == (0, 1, 30)


def test_only_matching_files_counted(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path, image_name_re=r".*\.jpg")
    handler.dispatch(FileClosedEvent(_write(root / "a.jpg", 1)))
    handler.dispatch(FileClosedEvent(_write(root / "a.tmp", 1)))
    handler.dispatch(FileClosedEvent(str(tmp_path.parent.resolve() / "elsewhere.jpg")))
    assert [s["total"] for s in _states(handler)] == [1]


def test_directories_ignored(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    sub = str(tmp_path.resolve() / "sub")
    handler.on_closed(DirModifiedEvent(sub))  # type: ignore[arg-type]
    handler.on_created(DirModifiedEvent(sub))  # type: ignore[arg-type]
    handler.on_deleted(DirDeletedEvent(sub))  # type: ignore[arg-type]
    handler.on_moved(DirModifiedEvent(sub))  # type: ignore[arg-type]
    assert _states(handler) == []


def test_count_failure_logged_not_raised(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    handler.publisher.image_stats = Mock(record=Mock(side_effect=OSError("disk full")))
    handler.publisher.post_upload_state = Mock(side_effect=OSError("broker gone"))  # type: ignore[method-assign]
    path = _write(tmp_path.resolve() / "a.jpg", 1)
    handler.on_closed(FileClosedEvent(path))
    handler.on_deleted(FileDeletedEvent(path))
    assert handler.current() == (0, 0)


def test_midnight_rescan_corrects_drift(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    handler = _handler(tmp_path, watch_tree=True)
    _write(root / "sub" / "a.jpg", 10)
    handler.scan()
    # a whole directory moved away only tells watchdog about the directory
    (root / "sub").rename(tmp_path.parent / f"{tmp_path.name}-gone")
    assert handler.current() == (1, 10)
    rescan_uploads([handler])
    assert handler.current() == (0, 0)
    assert _states(handler)[-1]["current"] == 0


def test_rescan_failure_logged_not_raised(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    handler.scan = Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    rescan_uploads([handler])
