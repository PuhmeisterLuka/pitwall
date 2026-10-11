"""The HTTP layer both sources share."""

import asyncio
import logging
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from typing import Any, Self

import httpx

from pitwall.errors import (
    UpstreamBadResponse,
    UpstreamError,
    UpstreamNotFound,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from pitwall.ratelimit import RateLimiter, Sleep

log = logging.getLogger(__name__)

USER_AGENT = "pitwall/0.1 (+https://github.com/PuhmeisterLuka/pitwall)"
MAX_DELAY_S = 30.0

Params = Mapping[str, str | int | float]


class JsonClient:
    """GET JSON from one upstream with rate limiting, timeouts and retries."""

    def __init__(
        self,
        name: str,
        base_url: str,
        limiter: RateLimiter,
        *,
        timeout_s: float = 10.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.name = name
        self._limiter = limiter
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    async def get(self, path: str, params: Params | None = None) -> Any:
        """Return decoded JSON, retrying transient failures with backoff."""
        attempt = 0
        while True:
            try:
                return await self._get_once(path, params)
            except UpstreamError as error:
                if not error.retryable or attempt >= self._max_retries:
                    raise
                delay = self._delay(attempt, error.retry_after)
                log.warning("%s; retry %d in %.1fs", error, attempt + 1, delay)
                await self._sleep(delay)
                attempt += 1

    async def _get_once(self, path: str, params: Params | None) -> Any:
        await self._limiter.acquire()
        try:
            response = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise UpstreamUnavailable(self.name, f"timed out on {path}") from exc
        except httpx.TransportError as exc:
            raise UpstreamUnavailable(self.name, f"connection failed on {path}") from exc

        if not response.is_success:
            raise self._error_for(response)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamBadResponse(
                self.name, f"invalid JSON from {path}", status=response.status_code
            ) from exc

    def _error_for(self, response: httpx.Response) -> UpstreamError:
        status = response.status_code
        message = f"HTTP {status} from {response.url.path}"
        if status == 404:
            return UpstreamNotFound(self.name, message, status=status)
        if status == 429:
            return UpstreamRateLimited(
                self.name, message, status=status, retry_after=retry_after_s(response)
            )
        if status >= 500:
            return UpstreamUnavailable(
                self.name, message, status=status, retry_after=retry_after_s(response)
            )
        return UpstreamError(self.name, message, status=status)

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        backoff = self._backoff_s * 2**attempt
        return min(MAX_DELAY_S, max(backoff, retry_after or 0.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def retry_after_s(response: httpx.Response) -> float | None:
    """Parse a Retry-After header given as seconds or as an HTTP date."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None
