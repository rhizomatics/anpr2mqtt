from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from anpr2mqtt.api_client import DVLA, APIClient


def _mock_session(mocker: MockerFixture, status_code: int, json_data: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.from_cache = False
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    session.post.return_value = resp
    mocker.patch("anpr2mqtt.api_client._CachedSession", return_value=session)
    return session


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
    result: dict[str, Any] = DVLA("7878748347834").lookup("SP13TST").get("plate", {})
    assert result["yearOfManufacture"] == 2004


def test_dvla_invalid_reg() -> None:
    result = DVLA("fake_key").lookup("NOTAVALID!!!REG")
    assert isinstance(result, dict)
    assert result == {"reg_match_fail": "GB", "plate": {}}


def test_dvla_api_error_response(mocker: MockerFixture) -> None:
    _mock_session(mocker, 403, {"errors": [{"title": "Forbidden", "code": "403", "status": "403"}]})
    result = DVLA("bad_key").lookup("SP13TST")
    assert isinstance(result, dict)
    assert "api_errors" in result
    assert result["api_status"] == 403


def test_dvla_api_exception(mocker: MockerFixture) -> None:
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    session.post.side_effect = ConnectionError("network down")
    mocker.patch("anpr2mqtt.api_client._CachedSession", return_value=session)
    result = DVLA("fake_key").lookup("SP13TST")
    assert isinstance(result, dict)
    assert "api_exception" in result


def test_api_client_base_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        APIClient().lookup("TEST")


@pytest.mark.skip
def test_real_api_call() -> None:
    """Requires a UAT env key to use the test reg"""
    import os

    api_key: str | None = os.environ.get("DVLA_API_KEY")
    assert api_key
    reg: str = "AA19AAA"  # see https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/mock-responses.html#test-vrns
    result = DVLA(api_key=api_key, test=True).lookup(reg)
    assert result
    assert "api_errors" not in result
    assert "api_exception" not in result
    assert "reg_match_fail" not in result
