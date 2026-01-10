import re
from typing import TYPE_CHECKING, Any, cast

import structlog
from hishel.httpx import SyncCacheClient

if TYPE_CHECKING:
    from httpx import Response

log = structlog.get_logger()


class APIClient:
    def lookup(self, reg: str) -> list[Any] | dict[str, Any] | None:
        raise NotImplementedError()


class DVLA(APIClient):
    ID = "GB"
    REG_RE = r"(^[A-Z]{2}[0-9]{2}\s?[A-Z]{3}$)|(^[A-Z][0-9]{1,3}[A-Z]{3}$)|(^[A-Z]{3}[0-9]{1,3}[A-Z]$)|(^[0-9]{1,4}[A-Z]{1,2}$)|(^[0-9]{1,3}[A-Z]{1,3}$)|(^[A-Z]{1,2}[0-9]{1,4}$)|(^[A-Z]{1,3}[0-9]{1,3}$)|(^[A-Z]{1,3}[0-9]{1,4}$)|(^[0-9]{3}[DX]{1}[0-9]{3}$)"  # noqa: E501
    """https://developer-portal.driver-vehicle-licensing.api.gov.uk"""

    def __init__(self, api_key: str, cache_ttl: int = 60 * 60 * 6) -> None:
        self.cache_ttl: int = cache_ttl
        self.api_key: str = api_key

    def lookup(self, reg: str) -> list[Any] | dict[str, Any] | None:
        if not re.match(self.REG_RE, reg):
            log.warning(f"DVLA SKIP invalid reg {reg}")
            return {"reg_match_fail": self.ID}
        try:
            with SyncCacheClient(headers=[("cache-control", f"max-age={self.cache_ttl}")]) as client:
                log.debug(f"Fetching DVLA info from API, cache_ttl={self.cache_ttl}")
                response: Response = client.post(
                    url="https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    json={"registrationNumber": reg.upper()},
                )
                if response.extensions.get("hishel_from_cache"):
                    log.debug("DVLA API cached response")
                if response.status_code == 200:
                    return cast("dict[str,Any]", response.json())

                log.error("DVLA API FAIL: %s", response.json())
                return {"api_errors": response.json()["errors"], "api_status": response.status_code}
        except Exception as e:
            log.exception("Failed to fetch DVLA reg data")
            return {"api_exception": str(e)}
