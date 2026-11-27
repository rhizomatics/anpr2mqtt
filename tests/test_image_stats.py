import datetime as dt
import json
from pathlib import Path

from anpr2mqtt.image_stats import ImageStats

MON = dt.datetime(2026, 11, 23, 9, 0, tzinfo=dt.UTC)


def test_counts_per_event_only() -> None:
    stats = ImageStats()
    stats.record(ImageStats.event_key("face", "front"), MON)
    stats.record(ImageStats.event_key("anpr", "front"), MON)
    stats.record(ImageStats.event_key("face", "barn"), MON)
    assert stats.attributes(ImageStats.event_key("face", "front"), MON) == {
        "today": 1,
        "this_week": 1,
        "total": 1,
        "last_received": MON.isoformat(),
    }
    assert stats.attributes(ImageStats.event_key("anpr", "front"), MON)["total"] == 1


def test_today_and_this_week_roll_over() -> None:
    stats = ImageStats()
    stats.record(ImageStats.event_key("face", "front"), MON)
    stats.record(ImageStats.event_key("face", "front"), MON + dt.timedelta(hours=1))
    tue = MON + dt.timedelta(days=1)
    assert stats.attributes(ImageStats.event_key("face", "front"), tue) == {
        "today": 0,
        "this_week": 2,
        "total": 2,
        "last_received": (MON + dt.timedelta(hours=1)).isoformat(),
    }
    stats.record(ImageStats.event_key("face", "front"), tue)
    assert stats.attributes(ImageStats.event_key("face", "front"), tue)["today"] == 1
    assert stats.attributes(ImageStats.event_key("face", "front"), tue)["this_week"] == 3
    next_mon = MON + dt.timedelta(days=7)
    assert stats.attributes(ImageStats.event_key("face", "front"), next_mon)["this_week"] == 0
    stats.record(ImageStats.event_key("face", "front"), next_mon)
    assert stats.attributes(ImageStats.event_key("face", "front"), next_mon)["this_week"] == 1
    assert stats.attributes(ImageStats.event_key("face", "front"), next_mon)["total"] == 4


def test_unseen_event_has_zero_counts() -> None:
    assert ImageStats().attributes(ImageStats.event_key("face", "front"), MON) == {
        "today": 0,
        "this_week": 0,
        "total": 0,
        "last_received": None,
    }


def test_last_file_kept_for_uploads() -> None:
    stats = ImageStats()
    stats.record(ImageStats.upload_key("ftp"), MON, file_name="a.jpg")
    stats.record(ImageStats.upload_key("ftp"), MON, file_name="b.mp4")
    assert stats.counts(ImageStats.upload_key("ftp")).last_file == "b.mp4"
    assert "last_file" not in stats.attributes(ImageStats.upload_key("ftp"), MON), "not in an event's images attribute"


def test_counts_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "data" / "image_stats.json"
    ImageStats(path).record(ImageStats.upload_key("ftp"), MON, file_name="a.jpg")
    reloaded = ImageStats(path)
    assert reloaded.attributes(ImageStats.upload_key("ftp"), MON)["total"] == 1
    assert reloaded.counts(ImageStats.upload_key("ftp")).last_file == "a.jpg"


def test_camera_and_overall_counts_from_1_4_0_dropped(tmp_path: Path) -> None:
    path = tmp_path / "image_stats.json"
    old = {"total": 5, "last_received": None, "day": None, "today": 0, "week": None, "this_week": 0}
    path.write_text(json.dumps({"event:face/front": old, "upload:ftp": old, "camera:front": old, "all": old}))
    stats = ImageStats(path)
    assert stats.attributes(ImageStats.event_key("face", "front"), MON)["total"] == 5
    assert stats.attributes(ImageStats.upload_key("ftp"), MON)["total"] == 5
    stats.record(ImageStats.event_key("face", "front"), MON)
    assert set(json.loads(path.read_text())) == {"event:face/front", "upload:ftp"}


def test_unreadable_file_starts_afresh(tmp_path: Path) -> None:
    path = tmp_path / "image_stats.json"
    path.write_text("not json")
    stats = ImageStats(path)
    assert stats.attributes(ImageStats.event_key("face", "front"), MON)["total"] == 0
    stats.record(ImageStats.event_key("face", "front"), MON)
    assert ImageStats(path).attributes(ImageStats.event_key("face", "front"), MON)["total"] == 1
