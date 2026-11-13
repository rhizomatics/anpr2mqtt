import datetime as dt
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal, cast

import niquests
import structlog
from niquests_cache import CachedSession as _CachedSession
from niquests_cache.backends import FileCache

from anpr2mqtt.settings import CacheType

log = structlog.get_logger()


class APIClient:
    def lookup(self, reg: str) -> dict[str, Any]:
        raise NotImplementedError()


class DVLAClient(APIClient):
    ID = "GB"
    REG_RE = r"(^[A-Z]{2}[0-9]{2}\s?[A-Z]{3}$)|(^[A-Z][0-9]{1,3}[A-Z]{3}$)|(^[A-Z]{3}[0-9]{1,3}[A-Z]$)|(^[0-9]{1,4}[A-Z]{1,2}$)|(^[0-9]{1,3}[A-Z]{1,3}$)|(^[A-Z]{1,2}[0-9]{1,4}$)|(^[A-Z]{1,3}[0-9]{1,3}$)|(^[A-Z]{1,3}[0-9]{1,4}$)|(^[0-9]{3}[DX]{1}[0-9]{3}$)"  # noqa: E501
    """https://developer-portal.driver-vehicle-licensing.api.gov.uk"""

    def __init__(
        self,
        api_key: str,
        cache_ttl: int = 60 * 60 * 6,
        cache_type: CacheType = CacheType.MEMORY,
        cache_dir: Path | None = None,
        verify_plate: str | None = None,
        test: bool = False,
    ) -> None:
        self.cache_session: _CachedSession | None = None
        if cache_type == CacheType.FILE and cache_dir:
            try:
                file_cache: FileCache = FileCache(cache_name=str(cache_dir), use_cache_dir=True)
                log.debug("Caching DVLA at %s for %s", file_cache.cache_dir, cache_ttl)
                self.cache_session = _CachedSession(
                    cache_name="dvla_cache", allowable_methods=["GET", "POST"], expire_after=cache_ttl, backend=file_cache
                )
            except Exception as e:
                log.error("Unable to configure file system caching, reverting to in memory: %s", e)
                cache_type = CacheType.MEMORY

        if self.cache_session is None:
            if cache_type != CacheType.MEMORY:
                log.warn("Unable to cache DVLA as %s, falling back to in memory for %s", cache_type, cache_ttl)
            else:
                log.debug("Caching DVLA in memory for %s", cache_ttl)
            self.cache_session = _CachedSession(
                cache_name="dvla_cache", allowable_methods=["GET", "POST"], backend="memory", expire_after=cache_ttl
            )

        self.api_key: str = api_key
        self.env_prefix: Literal["uat."] | Literal[""] = "uat." if test else ""
        if verify_plate:
            result: dict[str, Any] = self.lookup(reg=verify_plate)
            if result and result["success"]:
                log.info("Verified DVLA API lookup using %s, details: %s", verify_plate, result["plate"])
            else:
                log.error("DVLA startup verification failed: %s", result)

    def lookup(self, reg: str) -> dict[str, Any]:
        if not re.match(self.REG_RE, reg):
            log.warning(f"DVLA SKIP invalid reg {reg}")
            return {"reg_match_fail": self.ID, "plate": {}, "success": False}
        if self.cache_session is None:
            log.error("Unable to lookup, failed to configure cache session or fallback")
            return {"lookup_fail": "missing cache", "plate": {}, "success": False}
        try:
            with self.cache_session as client:
                log.debug(f"Fetching DVLA info from API, cache_ttl={self.cache_session.settings.expire_after}")
                # niquests-cache keys on method, url and headers only, not the body, so the reg goes in the
                # url fragment to give each plate its own cache entry; fragments are never sent to the server
                response: niquests.Response = client.post(
                    url=f"https://{self.env_prefix}driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles#{reg.upper()}",
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    json={"registrationNumber": reg.upper()},
                )
                # cache hits are rebuilt from the stored entry, so have no underlying raw connection response
                from_cache: bool = response.raw is None
                created_at: dt.datetime | None = _response_date(response)
                if from_cache:
                    log.debug("DVLA API cached response, created %s", created_at)
                if response.status_code == 200:
                    plate: dict[str, Any] = cast("dict[str,Any]", response.json())
                    return {
                        "cache": {
                            "calls": len(response.history) if response.history else 0,
                            "cached": from_cache,
                            "created": created_at.isoformat() if created_at else None,
                        },
                        "plate": plate,
                        "description": f"{plate.get('colour', '').title()} {plate.get('make', '').title()}" if plate else None,
                        "success": True,
                    }

                body: dict[str, Any] = cast("dict[str,Any]", response.json()) if response.content else {}
                log.error("DVLA API FAIL: %s", body)
                return {
                    # DVLA errors come as a list under "errors", AWS API gateway rejections as a "Message"
                    "api_errors": body.get("errors") or ([{"title": body["Message"]}] if "Message" in body else []),
                    "api_status": response.status_code,
                    "plate": {},
                    "success": False,
                }
        except Exception as e:
            log.exception("Failed to fetch DVLA reg data")
            return {"api_exception": str(e), "plate": {}, "success": False}


def _response_date(response: niquests.Response) -> dt.datetime | None:
    """Original response time from the Date header, which is preserved in cached entries."""
    date_header: str | None = response.headers.get("Date") if response.headers else None
    if not date_header:
        return None
    try:
        return parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
