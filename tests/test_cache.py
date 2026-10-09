import asyncio
import math

import pytest

from pitwall.cache import Cache, cache_key
from pitwall.errors import UpstreamUnavailable

pytestmark = pytest.mark.anyio


class Upstream:
    """Fake fetch that counts calls and can be switched to failing."""

    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    async def __call__(self) -> dict:
        self.calls += 1
        await asyncio.sleep(0)  # let concurrent callers overlap
        if self.error:
            raise self.error
        return {"call": self.calls}


@pytest.fixture
def cache(clock):
    db = Cache(clock=clock)
    yield db
    db.close()


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


async def test_miss_then_hit(cache, upstream):
    first = await cache.get_or_fetch("k", 60, upstream)
    second = await cache.get_or_fetch("k", 60, upstream)

    assert (first.status, first.value) == ("miss", {"call": 1})
    assert (second.status, second.value) == ("hit", {"call": 1})
    assert upstream.calls == 1


async def test_expired_entry_is_refetched(cache, upstream, clock):
    await cache.get_or_fetch("k", 60, upstream)
    clock.now += 61
    refreshed = await cache.get_or_fetch("k", 60, upstream)

    assert (refreshed.status, refreshed.value) == ("miss", {"call": 2})
    assert refreshed.fetched_at == clock.now


async def test_infinite_ttl_never_expires(cache, upstream, clock):
    await cache.get_or_fetch("k", math.inf, upstream)
    clock.now += 10 * 365 * 86_400
    assert (await cache.get_or_fetch("k", math.inf, upstream)).status == "hit"


async def test_failed_refresh_serves_stale_copy(cache, upstream, clock):
    first = await cache.get_or_fetch("k", 60, upstream)
    clock.now += 61
    upstream.error = UpstreamUnavailable("test", "down")
    stale = await cache.get_or_fetch("k", 60, upstream)

    assert (stale.status, stale.value) == ("stale", {"call": 1})
    assert stale.fetched_at == first.fetched_at


async def test_failure_without_cached_copy_raises(cache, upstream):
    upstream.error = UpstreamUnavailable("test", "down")
    with pytest.raises(UpstreamUnavailable):
        await cache.get_or_fetch("k", 60, upstream)


async def test_bugs_are_not_hidden_behind_stale_data(cache, upstream, clock):
    await cache.get_or_fetch("k", 60, upstream)
    clock.now += 61
    upstream.error = KeyError("parser bug")
    with pytest.raises(KeyError):
        await cache.get_or_fetch("k", 60, upstream)


async def test_concurrent_misses_share_one_fetch(cache, upstream):
    results = await asyncio.gather(*(cache.get_or_fetch("k", 60, upstream) for _ in range(5)))

    assert upstream.calls == 1
    assert {r.value["call"] for r in results} == {1}


async def test_entries_survive_restart(tmp_path, upstream, clock):
    path = tmp_path / "nested" / "cache.sqlite3"
    first = Cache(path, clock=clock)
    await first.get_or_fetch("k", 60, upstream)
    first.close()

    second = Cache(path, clock=clock)
    assert (await second.get_or_fetch("k", 60, upstream)).status == "hit"
    second.close()


def test_cache_key_ignores_param_order():
    assert cache_key("openf1", "/laps", {"session_key": 1, "driver_number": 44}) == cache_key(
        "openf1", "/laps", {"driver_number": 44, "session_key": 1}
    )
    assert cache_key("openf1", "/laps") != cache_key("jolpica", "/laps")
