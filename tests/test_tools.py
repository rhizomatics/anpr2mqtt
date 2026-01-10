from pytestshellutils.shell import Subprocess


def test_ocr_file_default_dir(shell: Subprocess) -> None:

    ret = shell.run("uv", "run", "tools", "ocr_file", "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg")
    assert ret.returncode == 0
    assert "{'vehicle_direction': 'Forward'}" in ret.stdout


def test_ocr_file_alt_crop(shell: Subprocess) -> None:

    ret = shell.run("uv", "run", "tools", "ocr_file", "fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg",
                    "--ocr.crop.x", "850", "--ocr.crop.y", "0", "--ocr.crop.h", "30", "--ocr.crop.w", "650", "--ocr.invert", "True", "--log_level", "DEBUG")

    assert ret.returncode == 0
    assert "{'ocr_field': 'Forward'}" in ret.stdout


def test_ocr_list_dir_default(shell: Subprocess) -> None:
    ret = shell.run("uv", "run", "tools", "list_dir")
    assert ret.returncode == 0


def test_ocr_list_dir_override(shell: Subprocess) -> None:
    ret = shell.run("uv", "run", "tools", "list_dir", "--event.watch_path", "fixtures")
    assert ret.returncode == 0
    assert "B4DM3N: timestamp=2025-06-02 10:30:45.000407+00:00,ext=jpg" in ret.stdout
