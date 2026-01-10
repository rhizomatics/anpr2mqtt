import pytest
from pytest_httpx import HTTPXMock

from anpr2mqtt.api_client import DVLA


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
