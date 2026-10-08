from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from pitwall.errors import (
    UpstreamBadResponse,
    UpstreamError,
    UpstreamNotFound,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from pitwall.http import JsonClient, retry_after_s
from pitwall.ratelimit import RateLimiter

pytestmark = pytest.mark.anyio


class Replay(httpx.MockTransport):
    """Answer each request with the next scripted Response, or raise the next exception."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []
        super().__init__(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def make_client(transport: Replay, clock, max_retries: int = 3) -> JsonClient:
    return JsonClient(
        "test",
        "https://api.test/v1",
        RateLimiter(),
        max_retries=max_retries,
        transport=transport,
        sleep=clock.sleep,
    )


async def test_returns_json_and_sends_params(clock):
    transport = Replay(httpx.Response(200, json=[{"lap": 1}]))
    async with make_client(transport, clock) as client:
        assert await client.get("/laps", {"session_key": 9574}) == [{"lap": 1}]

    request = transport.requests[0]
    assert request.url == "https://api.test/v1/laps?session_key=9574"
    assert request.headers["User-Agent"].startswith("pitwall/")
    assert clock.slept == []


async def test_retries_server_errors_with_exponential_backoff(clock):
    transport = Replay(httpx.Response(503), httpx.Response(502), httpx.Response(200, json={}))
    async with make_client(transport, clock) as client:
        assert await client.get("/x") == {}
    assert clock.slept == [0.5, 1.0]


async def test_rate_limit_waits_for_retry_after(clock):
    transport = Replay(
        httpx.Response(429, headers={"Retry-After": "4"}),
        httpx.Response(200, json={}),
    )
    async with make_client(transport, clock) as client:
        await client.get("/x")
    assert clock.slept == [4.0]


async def test_gives_up_after_max_retries(clock):
    transport = Replay(*[httpx.Response(429)] * 3)
    async with make_client(transport, clock, max_retries=2) as client:
        with pytest.raises(UpstreamRateLimited) as caught:
            await client.get("/x")
    assert caught.value.status == 429
    assert len(transport.requests) == 3


async def test_timeouts_are_retried_then_reported(clock):
    transport = Replay(*[httpx.ReadTimeout("slow")] * 2)
    async with make_client(transport, clock, max_retries=1) as client:
        with pytest.raises(UpstreamUnavailable, match="timed out"):
            await client.get("/x")
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404), UpstreamNotFound),
        (httpx.Response(422), UpstreamError),
        (httpx.Response(200, text="<html>"), UpstreamBadResponse),
    ],
)
async def test_permanent_failures_are_not_retried(clock, response, error):
    transport = Replay(response)
    async with make_client(transport, clock) as client:
        with pytest.raises(error) as caught:
            await client.get("/x")
    assert caught.value.source == "test"
    assert not caught.value.retryable
    assert len(transport.requests) == 1


def test_retry_after_accepts_seconds_and_http_dates():
    def parse(value: str) -> float | None:
        return retry_after_s(httpx.Response(429, headers={"Retry-After": value}))

    in_ten = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    assert parse("7") == 7.0
    assert 8 < parse(in_ten) <= 10
    assert parse("soon") is None
    assert retry_after_s(httpx.Response(429)) is None
