import pytest
from pytest_httpx import HTTPXMock

from anpr2mqtt.api_client import DVLA, APIClient


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_discover_metadata(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        json={
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
        }
    )
    api_client = DVLA("7878748347834")
    result = api_client.lookup("SP13TST")
    assert result["yearOfManufacture"] == 2004  # type:ignore[call-overload,index]


def test_dvla_invalid_reg() -> None:
    api_client = DVLA("fake_key")
    result = api_client.lookup("NOTAVALID!!!REG")
    assert isinstance(result, dict)
    assert result == {"reg_match_fail": "GB"}


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_dvla_api_error_response(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        status_code=403,
        json={"errors": [{"title": "Forbidden", "code": "403", "status": "403"}]},
    )
    api_client = DVLA("bad_key")
    result = api_client.lookup("SP13TST")
    assert isinstance(result, dict)
    assert "api_errors" in result
    assert result["api_status"] == 403


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_dvla_api_exception(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(ConnectionError("network down"))
    api_client = DVLA("fake_key")
    result = api_client.lookup("SP13TST")
    assert isinstance(result, dict)
    assert "api_exception" in result


def test_api_client_base_not_implemented() -> None:
    client = APIClient()
    with pytest.raises(NotImplementedError):
        client.lookup("TEST")
