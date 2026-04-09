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
    result: dict[str, Any] = DVLAClient("7878748347834").lookup("SP13TST").get("plate", {})
    assert result["yearOfManufacture"] == 2004


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
