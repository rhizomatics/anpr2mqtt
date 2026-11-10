import os
import time
from pathlib import Path

import pytest

from anpr2mqtt.heartbeat import HEARTBEAT_ENV, Heartbeat, heartbeat_age, heartbeat_path
from anpr2mqtt.tools import HealthcheckTool


@pytest.fixture
def beat_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "beat"
    monkeypatch.setenv(HEARTBEAT_ENV, str(path))
    return path


def test_path_from_env(beat_file: Path) -> None:
    assert heartbeat_path() == beat_file


@pytest.mark.usefixtures("beat_file")
def test_age_none_before_first_beat() -> None:
    assert heartbeat_age() is None


@pytest.mark.usefixtures("beat_file")
def test_beat_creates_file() -> None:
    Heartbeat().beat()
    age = heartbeat_age()
    assert age is not None
    assert age < 5


def test_beat_throttled_within_interval(beat_file: Path) -> None:
    heartbeat = Heartbeat(interval=3600)
    heartbeat.beat()
    os.utime(beat_file, (0, 0))
    heartbeat.beat()
    assert beat_file.stat().st_mtime == 0


def test_beat_again_after_interval(beat_file: Path) -> None:
    heartbeat = Heartbeat(interval=0)
    heartbeat.beat()
    os.utime(beat_file, (0, 0))
    heartbeat.beat()
    assert beat_file.stat().st_mtime > 0


def test_beat_unwritable_does_not_raise(tmp_path: Path) -> None:
    heartbeat = Heartbeat(path=tmp_path / "missing_dir" / "beat")
    heartbeat.beat()
    assert heartbeat.last_beat is None


def test_clear_removes_file(beat_file: Path) -> None:
    heartbeat = Heartbeat()
    heartbeat.beat()
    heartbeat.clear()
    assert not beat_file.exists()
    heartbeat.clear()  # already gone is fine


@pytest.mark.usefixtures("beat_file")
def test_healthcheck_healthy(capsys: pytest.CaptureFixture[str]) -> None:
    Heartbeat().beat()
    HealthcheckTool().cli_cmd()
    assert "HEALTHY" in capsys.readouterr().out


@pytest.mark.usefixtures("beat_file")
def test_healthcheck_no_heartbeat() -> None:
    with pytest.raises(SystemExit) as e:
        HealthcheckTool().cli_cmd()
    assert e.value.code == 1


def test_healthcheck_stale(beat_file: Path) -> None:
    beat_file.touch()
    stale = time.time() - 120
    os.utime(beat_file, (stale, stale))
    with pytest.raises(SystemExit) as e:
        HealthcheckTool(max_age=60).cli_cmd()
    assert e.value.code == 1
    HealthcheckTool(max_age=600).cli_cmd()
