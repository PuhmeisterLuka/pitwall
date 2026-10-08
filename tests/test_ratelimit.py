import pytest

from pitwall.ratelimit import RateLimiter

pytestmark = pytest.mark.anyio


async def acquire_times(limiter: RateLimiter, clock, calls: int) -> list[float]:
    """Acquire `calls` times and return each call's start, relative to the first."""
    start = clock.now
    times = []
    for _ in range(calls):
        await limiter.acquire()
        times.append(round(clock.now - start, 6))
    return times


async def test_burst_within_limit_does_not_wait(clock):
    limiter = RateLimiter((3, 1.0), clock=clock, sleep=clock.sleep)
    assert await acquire_times(limiter, clock, 3) == [0, 0, 0]


async def test_call_over_limit_waits_for_window(clock):
    limiter = RateLimiter((3, 1.0), clock=clock, sleep=clock.sleep)
    assert await acquire_times(limiter, clock, 5) == [0, 0, 0, 1.0, 1.0]


async def test_every_window_is_enforced(clock):
    limiter = RateLimiter((2, 1.0), (3, 10.0), clock=clock, sleep=clock.sleep)
    assert await acquire_times(limiter, clock, 4) == [0, 0, 1.0, 10.0]


async def test_no_windows_means_unlimited(clock):
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    assert await acquire_times(limiter, clock, 50) == [0] * 50
