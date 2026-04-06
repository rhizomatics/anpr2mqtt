import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import niquests
import structlog
from requests_cache import FileCache
from requests_cache.session import CacheMixin

from anpr2mqtt.settings import CacheType

if TYPE_CHECKING:
    from requests_cache import CachedResponse


class _CachedSession(CacheMixin, niquests.Session):  # type: ignore[misc]
    """requests-cache backed by niquests as the transport."""


log = structlog.get_logger()


class APIClient:
    def lookup(self, reg: str) -> dict[str, Any]:
        raise NotImplementedError()


class DVLA(APIClient):
    ID = "GB"
    REG_RE = r"(^[A-Z]{2}[0-9]{2}\s?[A-Z]{3}$)|(^[A-Z][0-9]{1,3}[A-Z]{3}$)|(^[A-Z]{3}[0-9]{1,3}[A-Z]$)|(^[0-9]{1,4}[A-Z]{1,2}$)|(^[0-9]{1,3}[A-Z]{1,3}$)|(^[A-Z]{1,2}[0-9]{1,4}$)|(^[A-Z]{1,3}[0-9]{1,3}$)|(^[A-Z]{1,3}[0-9]{1,4}$)|(^[0-9]{3}[DX]{1}[0-9]{3}$)"  # noqa: E501
    """https://developer-portal.driver-vehicle-licensing.api.gov.uk"""

    def __init__(
        self,
        api_key: str,
        cache_ttl: int = 60 * 60 * 6,
        cache_type: CacheType = CacheType.MEMORY,
        cache_dir: Path | None = None,
        test: bool = False,
    ) -> None:
        if cache_type == CacheType.FILE and cache_dir:
            file_cache: FileCache = FileCache(cache_name=str(cache_dir), use_cache_dir=True)
            log.debug("Caching DVLA at %s for %s", file_cache.cache_dir, cache_ttl)
            self.cache_session = _CachedSession(
                cache_name="dvla_cache", allowable_methods=["GET", "POST"], expire_after=cache_ttl, backend=file_cache
            )
        else:
            log.debug("Caching DVLA in memory for %s", cache_ttl)
            self.cache_session = _CachedSession(
                cache_name="dvla_cache", allowable_methods=["GET", "POST"], backend="memory", expire_after=cache_ttl
            )
        self.api_key: str = api_key
        self.env_prefix: Literal["uat."] | Literal[""] = "uat." if test else ""

    def lookup(self, reg: str) -> dict[str, Any]:
        if not re.match(self.REG_RE, reg):
            log.warning(f"DVLA SKIP invalid reg {reg}")
            return {"reg_match_fail": self.ID, "plate": {}}
        try:
            with self.cache_session as client:
                log.debug(f"Fetching DVLA info from API, cache_ttl={self.cache_session.expire_after}")
                response: CachedResponse = cast(
                    "CachedResponse",
                    client.post(
                        url=f"https://{self.env_prefix}driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
                        headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                        json={"registrationNumber": reg.upper()},
                    ),
                )
                if response.from_cache:
                    log.debug("DVLA API cached response, created %s", response.created_at)
                if response.status_code == 200:
                    return {
                        "cache": {
                            "calls": len(response.history) if response.history else 0,
                            "cached": response.from_cache,
                            "created": response.created_at.isoformat() if response.created_at else None,
                        },
                        "plate": cast("dict[str,Any]", response.json()),
                    }

                log.error("DVLA API FAIL: %s", response.json())
                return {"api_errors": response.json()["errors"], "api_status": response.status_code, "plate": {}}
        except Exception as e:
            log.exception("Failed to fetch DVLA reg data")
            return {"api_exception": str(e), "plate": {}}
