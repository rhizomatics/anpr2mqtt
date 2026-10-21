"""Build the Docker image and check the app starts inside it.

Catches packaging problems that the in-venv tests can't see, such as a dependency
only installed in dev (e.g. YAML support for the config file) or a broken entrypoint.
Skipped when no Docker daemon is available, except in CI where that's a failure.
"""

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

PROJECT_ROOT = Path(__file__).parent.parent
STARTED_MARKER = "Starting observer loop"
STARTUP_TIMEOUT = 60


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0


if not docker_available():
    # optional locally, but mandatory in CI so a missing daemon can't silently pass
    if os.environ.get("CI"):
        pytest.fail("Docker daemon not available in CI", pytrace=False)
    pytest.skip("Docker daemon not available", allow_module_level=True)


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)  # noqa: S603


def container_logs(name: str) -> str:
    result = docker("logs", name, check=False)
    return result.stdout + result.stderr


def is_running(name: str) -> bool:
    return docker("inspect", "-f", "{{.State.Running}}", name, check=False).stdout.strip() == "true"


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    tag = f"anpr2mqtt-test:{uuid.uuid4().hex[:8]}"
    result = docker("build", "-t", tag, str(PROJECT_ROOT), check=False)
    assert result.returncode == 0, f"docker build failed:\n{result.stderr[-4000:]}"
    yield tag
    docker("rmi", "-f", tag, check=False)


@pytest.fixture
def broker() -> Iterator[tuple[str, str]]:
    """Mosquitto on a private network, returning (network, broker hostname)"""
    suffix = uuid.uuid4().hex[:8]
    network = f"anpr2mqtt-test-{suffix}"
    name = f"anpr2mqtt-test-broker-{suffix}"
    docker("network", "create", network)
    docker(
        "run", "-d", "--name", name, "--network", network,
        "eclipse-mosquitto:2", "mosquitto", "-c", "/mosquitto-no-auth.conf",
    )  # fmt: skip
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline and " running" not in container_logs(name):
        time.sleep(0.5)
    yield network, name
    docker("rm", "-f", name, check=False)
    docker("network", "rm", network, check=False)


def test_container_starts(image: str, broker: tuple[str, str], tmp_path: Path) -> None:
    network, broker_host = broker
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "anpr2mqtt.yaml").write_text(
        f"""---
events:
  - watch_path: /app/.cache
tracker:
  data_dir: /tmp
mqtt:
  host: {broker_host}
  user: anpr2mqtt
  password: test
"""
    )
    name = f"anpr2mqtt-test-app-{uuid.uuid4().hex[:8]}"
    docker("run", "-d", "--name", name, "--network", network, "-v", f"{config_dir}:/config:ro", image)
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline and STARTED_MARKER not in container_logs(name) and is_running(name):
            time.sleep(1)
        assert STARTED_MARKER in container_logs(name), f"app did not start:\n{container_logs(name)}"
        # still up shortly after, rather than crashing once the observer loop began
        time.sleep(2)
        assert is_running(name), f"app exited after startup:\n{container_logs(name)}"
    finally:
        docker("rm", "-f", name, check=False)
