import datetime as dt
from pathlib import Path

from anpr2mqtt.image_stats import ImageStats

MON = dt.datetime(2026, 11, 23, 9, 0, tzinfo=dt.UTC)


def test_counts_per_event_camera_and_overall() -> None:
    stats = ImageStats()
    stats.record("face", "front", MON)
    stats.record("anpr", "front", MON)
    stats.record("face", "barn", MON)
    face_front = stats.attributes("face", "front", MON)
    assert face_front["event"]["total"] == 1
    assert face_front["camera"]["total"] == 2
    assert face_front["all"]["total"] == 3
    assert face_front["event"]["last_received"] == MON.isoformat()


def test_today_and_this_week_roll_over() -> None:
    stats = ImageStats()
    stats.record("face", "front", MON)
    stats.record("face", "front", MON + dt.timedelta(hours=1))
    tue = MON + dt.timedelta(days=1)
    assert stats.attributes("face", "front", tue)["event"] == {
        "today": 0,
        "this_week": 2,
        "total": 2,
        "last_received": (MON + dt.timedelta(hours=1)).isoformat(),
    }
    stats.record("face", "front", tue)
    assert stats.attributes("face", "front", tue)["event"]["today"] == 1
    assert stats.attributes("face", "front", tue)["event"]["this_week"] == 3
    next_mon = MON + dt.timedelta(days=7)
    assert stats.attributes("face", "front", next_mon)["event"]["this_week"] == 0
    stats.record("face", "front", next_mon)
    assert stats.attributes("face", "front", next_mon)["event"]["this_week"] == 1
    assert stats.attributes("face", "front", next_mon)["event"]["total"] == 4


def test_unseen_event_has_zero_counts() -> None:
    assert ImageStats().attributes("face", "front", MON)["event"] == {
        "today": 0,
        "this_week": 0,
        "total": 0,
        "last_received": None,
    }


def test_counts_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "data" / "image_stats.json"
    ImageStats(path).record("face", "front", MON)
    assert ImageStats(path).attributes("face", "front", MON)["event"]["total"] == 1


def test_unreadable_file_starts_afresh(tmp_path: Path) -> None:
    path = tmp_path / "image_stats.json"
    path.write_text("not json")
    stats = ImageStats(path)
    assert stats.attributes("face", "front", MON)["all"]["total"] == 0
    stats.record("face", "front", MON)
    assert ImageStats(path).attributes("face", "front", MON)["all"]["total"] == 1
