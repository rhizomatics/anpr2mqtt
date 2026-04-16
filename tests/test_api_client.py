from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from anpr2mqtt.api_client import APIClient, DVLAClient
from anpr2mqtt.settings import CacheType


def _make_response(status_code: int, json_data: object, from_cache: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.from_cache = from_cache
    resp.history = None
    resp.created_at = None
    return resp


def _mock_session(mocker: MockerFixture, status_code: int, json_data: object) -> tuple[MagicMock, MagicMock]:
    """Return (session_cls_mock, session_instance_mock)."""
    resp = _make_response(status_code, json_data)
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    session.post.return_value = resp
    cls_mock = mocker.patch("anpr2mqtt.api_client._CachedSession", return_value=session)
    return cls_mock, session


def test_discover_metadata(mocker: MockerFixture) -> None:
    _mock_session(
        mocker,
        200,
        {
            "artEndDate": "2025-02-28",
            "co2Emissions": 135,
            "colour": "BLUE",
            "engineCapacity": 2494,
            "fuelType": "PETROL",
            "make": "ROVER",
            "markedForExport": False,
            "monthOfFirstRegistration": "2004-12",
            "motStatus": "No details held by DVLA",
            "registrationNumber": "ABC1234",
            "revenueWeight": 1640,
            "taxDueDate": "2007-01-01",
            "taxStatus": "Untaxed",
            "typeApproval": "N1",
            "wheelplan": "NON STANDARD",
            "yearOfManufacture": 2004,
            "euroStatus": "EURO 6 AD",
            "realDrivingEmissions": "1",
            "dateOfLastV5CIssued": "2016-12-25",
        },
    )
    result: dict[str, Any] = DVLAClient("7878748347834").lookup("SP13TST")
    plate: dict[str, Any] = result.get("plate", {})
    assert plate["yearOfManufacture"] == 2004
    assert result["description"] == "Blue Rover"
    assert result["success"]


def test_dvla_invalid_reg() -> None:
    result = DVLAClient("fake_key").lookup("NOTAVALID!!!REG")
    assert isinstance(result, dict)
    assert result == {"reg_match_fail": "GB", "plate": {}, "success": False}


def test_dvla_api_error_response(mocker: MockerFixture) -> None:
    _mock_session(mocker, 403, {"errors": [{"title": "Forbidden", "code": "403", "status": "403"}]})
    result = DVLAClient("bad_key").lookup("SP13TST")
    assert isinstance(result, dict)
    assert "api_errors" in result
    assert result["api_status"] == 403


def test_dvla_api_exception(mocker: MockerFixture) -> None:
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    session.post.side_effect = ConnectionError("network down")
    mocker.patch("anpr2mqtt.api_client._CachedSession", return_value=session)
    result = DVLAClient("fake_key").lookup("SP13TST")
    assert isinstance(result, dict)
    assert "api_exception" in result


def test_api_client_base_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        APIClient().lookup("TEST")


def test_init_without_cache_dir_uses_memory_backend(mocker: MockerFixture) -> None:
    cls_mock, _ = _mock_session(mocker, 200, {})
    DVLAClient("key")
    _, kwargs = cls_mock.call_args
    assert kwargs["backend"] == "memory"


def test_init_with_cache_dir_uses_file_cache(mocker: MockerFixture, tmp_path: Path) -> None:
    file_cache_cls = mocker.patch("anpr2mqtt.api_client.FileCache")
    cls_mock, _ = _mock_session(mocker, 200, {})
    DVLAClient("key", cache_dir=tmp_path, cache_type=CacheType.FILE)
    file_cache_cls.assert_called_once_with(cache_name=str(tmp_path), use_cache_dir=True)
    _, kwargs = cls_mock.call_args
    assert kwargs["backend"] is file_cache_cls.return_value


def test_init_file_cache_exception_falls_back_to_memory(mocker: MockerFixture, tmp_path: Path) -> None:
    """FileCache constructor raises → falls back to in-memory cache (lines 50-52)."""
    mocker.patch("anpr2mqtt.api_client.FileCache", side_effect=OSError("disk full"))
    cls_mock, _ = _mock_session(mocker, 200, {})
    DVLAClient("key", cache_dir=tmp_path, cache_type=CacheType.FILE)
    _, kwargs = cls_mock.call_args
    assert kwargs["backend"] == "memory"


def test_init_file_type_no_dir_warns_falls_back(mocker: MockerFixture) -> None:
    """cache_type=FILE but cache_dir=None → file block skipped, warn about non-MEMORY type (line 56)."""
    cls_mock, _ = _mock_session(mocker, 200, {})
    DVLAClient("key", cache_type=CacheType.FILE, cache_dir=None)
    _, kwargs = cls_mock.call_args
    assert kwargs["backend"] == "memory"


def test_dvla_verify_plate_success(mocker: MockerFixture) -> None:
    """verify_plate with successful lookup logs info (lines 66-69)."""
    _mock_session(mocker, 200, {"registrationNumber": "SP13TST", "make": "FORD"})
    client = DVLAClient("key", verify_plate="SP13TST")
    assert client.api_key == "key"


def test_dvla_verify_plate_failure(mocker: MockerFixture) -> None:
    """verify_plate with failed lookup logs error (line 70)."""
    _mock_session(mocker, 403, {"errors": [{"title": "Forbidden"}]})
    client = DVLAClient("key", verify_plate="SP13TST")
    assert client.api_key == "key"


def test_lookup_cached_response_logs_cache_hit(mocker: MockerFixture) -> None:
    """from_cache=True triggers the cache-hit log (line 91)."""
    resp = _make_response(200, {"registrationNumber": "SP13TST"}, from_cache=True)
    resp.created_at = __import__("datetime").datetime(2025, 1, 1)
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    session.post.return_value = resp
    mocker.patch("anpr2mqtt.api_client._CachedSession", return_value=session)
    result = DVLAClient("key").lookup("SP13TST")
    assert result["cache"]["cached"] is True


@pytest.mark.skip
def test_real_api_call() -> None:
    """Require a UAT env key; exercises the default (in-memory) cache."""
    import os

    api_key: str | None = os.environ.get("DVLA_API_KEY")
    assert api_key
    reg: str = "AA19AAA"  # see https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/mock-responses.html#test-vrns
    result = DVLAClient(api_key=api_key, test=True).lookup(reg)
    assert result
    assert "api_errors" not in result
    assert "api_exception" not in result
    assert "reg_match_fail" not in result


@pytest.mark.skip
def test_real_api_call_with_file_cache(tmp_path: Path) -> None:
    """Require a UAT env key; exercises the FileCache backend and verifies second call is served from cache."""
    import os

    api_key: str | None = os.environ.get("DVLA_API_KEY")
    assert api_key
    reg: str = "AA19AAA"  # see https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/mock-responses.html#test-vrns
    result: dict[str, Any] = DVLAClient(api_key=api_key, cache_dir=tmp_path, test=True).lookup(reg)
    assert result
    assert "api_errors" not in result
    assert "api_exception" not in result
    assert "reg_match_fail" not in result
    cached_result = DVLAClient(api_key=api_key, cache_dir=tmp_path, test=True).lookup(reg)
    assert cached_result["cache"]["cached"] is True
