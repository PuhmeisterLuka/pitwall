from typing import Any

import httpx
import pytest

from pitwall.cache import Cache
from pitwall.errors import UpstreamBadResponse, UpstreamUnavailable
from pitwall.http import JsonClient
from pitwall.ratelimit import RateLimiter
from pitwall.sources import Jolpica, OpenF1
from pitwall.sources.base import LIVE_TTL_S

pytestmark = pytest.mark.anyio

SPA = {"season": "2024", "round": "14", "raceName": "Belgian Grand Prix", "Results": []}


class Router(httpx.MockTransport):
    """Serve JSON by URL path (404 for unknown paths, or a status code instead of a body)."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []
        super().__init__(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "No results found."})
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, json=body)


def mrdata(total: int = 1, **tables: Any) -> dict:
    """Wrap tables in Jolpica's MRData envelope."""
    return {"MRData": {"total": str(total), **tables}}


@pytest.fixture
async def connect(clock):
    """Build sources on fake HTTP and one shared cache; close them after the test."""
    cache = Cache(clock=clock)
    opened = []

    def build(source_cls, routes: dict[str, Any]):
        router = Router(routes)
        http = JsonClient(
            source_cls.name,
            "https://upstream.test",
            RateLimiter(),
            max_retries=0,
            transport=router,
            sleep=clock.sleep,
        )
        opened.append(source_cls(http, cache))
        return opened[-1], router

    yield build
    for source in opened:
        await source.aclose()
    cache.close()


async def test_jolpica_unwraps_calendar_and_asks_for_a_full_page(connect):
    jolpica, router = connect(Jolpica, {"/2024/races.json": mrdata(RaceTable={"Races": [SPA]})})

    calendar = await jolpica.calendar(2024)

    assert calendar.value == [SPA]
    assert router.requests[0].url.params["limit"] == "100"


async def test_jolpica_race_result_is_none_before_the_race(connect):
    jolpica, _ = connect(
        Jolpica,
        {
            "/2024/14/results.json": mrdata(RaceTable={"Races": [SPA]}),
            "/2024/15/results.json": mrdata(0, RaceTable={"Races": []}),
        },
    )

    assert (await jolpica.race_result(2024, 14)).value == SPA
    assert (await jolpica.race_result(2024, 15)).value is None


async def test_jolpica_standings_rows(connect):
    rows = [{"position": "1", "Driver": {"code": "VER"}}]
    jolpica, _ = connect(
        Jolpica,
        {
            "/2024/14/driverStandings.json": mrdata(
                StandingsTable={"StandingsLists": [{"DriverStandings": rows}]}
            ),
            "/2024/1/driverStandings.json": mrdata(0, StandingsTable={"StandingsLists": []}),
        },
    )

    assert (await jolpica.driver_standings(2024, 14)).value == rows
    assert (await jolpica.driver_standings(2024, 1)).value == []


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": True},
        mrdata(RaceTable={}),
        mrdata(250, RaceTable={"Races": [SPA]}),
    ],
    ids=["no-envelope", "no-table", "truncated"],
)
async def test_jolpica_rejects_unusable_payloads(connect, payload):
    jolpica, _ = connect(Jolpica, {"/2024/races.json": payload})
    with pytest.raises(UpstreamBadResponse, match="jolpica"):
        await jolpica.calendar(2024)


async def test_openf1_empty_query_is_an_empty_list(connect):
    openf1, router = connect(OpenF1, {})

    assert (await openf1.pit_stops(9574)).value == []
    assert (await openf1.pit_stops(9574)).status == "hit"
    assert len(router.requests) == 1


async def test_openf1_filters_by_session(connect):
    stints = [{"driver_number": 44, "compound": "HARD"}]
    openf1, router = connect(OpenF1, {"/stints": stints})

    assert (await openf1.stints(9574)).value == stints
    assert router.requests[0].url.params["session_key"] == "9574"


async def test_openf1_live_session_lockout_is_explained(connect):
    openf1, _ = connect(OpenF1, {"/laps": 401})
    with pytest.raises(UpstreamUnavailable, match="while an F1 session is live") as caught:
        await openf1.laps(9574)
    assert caught.value.status == 401


async def test_openf1_rejects_non_list_payloads(connect):
    openf1, _ = connect(OpenF1, {"/laps": {"detail": "oops"}})
    with pytest.raises(UpstreamBadResponse, match="expected a list"):
        await openf1.laps(9574)


async def test_settled_data_outlives_live_data(connect, clock):
    openf1, router = connect(OpenF1, {"/drivers": [{"driver_number": 1}]})
    await openf1.drivers(1, settled=True)
    await openf1.drivers(2)

    clock.now += LIVE_TTL_S + 1

    assert (await openf1.drivers(1, settled=True)).status == "hit"
    assert (await openf1.drivers(2)).status == "miss"
    assert len(router.requests) == 3


async def test_outage_serves_last_good_copy(connect, clock):
    openf1, router = connect(OpenF1, {"/drivers": [{"driver_number": 1}]})
    await openf1.drivers(9574)

    clock.now += LIVE_TTL_S + 1
    router.routes["/drivers"] = 503

    stale = await openf1.drivers(9574)
    assert (stale.status, stale.value) == ("stale", [{"driver_number": 1}])


async def test_outage_without_cached_copy_raises(connect):
    openf1, _ = connect(OpenF1, {"/drivers": 503})
    with pytest.raises(UpstreamUnavailable):
        await openf1.drivers(9574)
