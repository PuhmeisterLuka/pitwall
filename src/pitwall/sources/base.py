"""Shared plumbing for upstream sources: caching, TTLs and response-shape checks."""

from collections.abc import Callable
from typing import Any, ClassVar

from pitwall.cache import Cache, Cached, cache_key
from pitwall.errors import UpstreamBadResponse
from pitwall.http import JsonClient, Params

LIVE_TTL_S = 15 * 60
SETTLED_TTL_S = 30 * 86_400  # a finished race changes when the stewards correct it, which is rare

Extract = Callable[[Any], Any]


def as_is(payload: Any) -> Any:
    return payload


class Source:
    """Cached, rate-limited access to one upstream API."""

    name: ClassVar[str]
    limits: ClassVar[tuple[tuple[int, float], ...]]

    def __init__(self, http: JsonClient, cache: Cache) -> None:
        self._http = http
        self._cache = cache

    async def _get(
        self,
        path: str,
        params: Params | None = None,
        *,
        settled: bool,
        extract: Extract = as_is,
    ) -> Cached:
        """Fetch through the cache: 15 minutes for live data, 30 days once an event has settled."""

        async def fetch() -> Any:
            payload = await self._request(path, params)
            try:
                return extract(payload)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise UpstreamBadResponse(
                    self.name, f"unexpected response shape from {path}"
                ) from exc

        ttl_s = SETTLED_TTL_S if settled else LIVE_TTL_S
        return await self._cache.get_or_fetch(cache_key(self.name, path, params), ttl_s, fetch)

    async def _request(self, path: str, params: Params | None) -> Any:
        """Plain GET; override for API-specific quirks."""
        return await self._http.get(path, params)

    async def aclose(self) -> None:
        await self._http.aclose()
