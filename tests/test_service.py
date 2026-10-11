import datetime as dt

import pytest

from pitwall.errors import UpstreamRateLimited, UpstreamUnavailable
from pitwall.service import NotFound, RaceService, SourceStatus, worst

pytestmark = pytest.mark.anyio

TODAY = dt.date(2026, 10, 10)


def service(sources, today: dt.date = TODAY) -> RaceService:
    return RaceService(sources, today=lambda: today)


def fetched(source) -> dt.datetime:
    return dt.datetime.fromtimestamp(source.fetched_at, dt.UTC)


def settled_flags(sources) -> set[bool]:
    return {settled for _, _, settled in sources.jolpica.calls + sources.openf1.calls}


async def test_race_merges_both_sources(spa_sources):
    view = await service(spa_sources).race(2024, 14)
    winner = view.report.entries[0]

    assert (winner.driver.code, winner.driver.team_colour) == ("HAM", "#27F4D2")
    assert view.report.event.session_key == 9574
    assert view.sources == {
        "jolpica": SourceStatus("hit", fetched(spa_sources.jolpica)),
        "openf1": SourceStatus("hit", fetched(spa_sources.openf1)),
    }


async def test_finished_races_are_fetched_as_settled(spa_sources):
    await service(spa_sources).race(2024, 14)
    assert settled_flags(spa_sources) == {True}


async def test_recent_races_stay_live(spa_sources):
    await service(spa_sources, today=dt.date(2024, 7, 29)).race(2024, 14)
    assert settled_flags(spa_sources) == {False}


async def test_openf1_outage_still_serves_the_official_result(spa_sources):
    spa_sources.openf1.answers["laps"] = UpstreamUnavailable("openf1", "HTTP 503 from /v1/laps")
    view = await service(spa_sources).race(2024, 14)
    winner = view.report.entries[0]

    assert (winner.driver.code, winner.lap_times_s) == ("HAM", ())
    assert view.sources["openf1"].status == "error"
    assert "HTTP 503" in view.sources["openf1"].error
    assert view.sources["jolpica"].status == "hit"


async def test_stale_answers_are_reported(spa_sources):
    spa_sources.openf1.status = "stale"
    view = await service(spa_sources).race(2024, 14)
    assert view.sources["openf1"] == SourceStatus("stale", fetched(spa_sources.openf1))


async def test_jolpica_outage_is_an_error(spa_sources):
    spa_sources.jolpica.answers["calendar"] = UpstreamUnavailable("jolpica", "timed out")
    with pytest.raises(UpstreamUnavailable):
        await service(spa_sources).race(2024, 14)


async def test_unknown_or_unraced_rounds_are_not_found(spa_sources):
    with pytest.raises(NotFound, match="2024 has no round 15"):
        await service(spa_sources).race(2024, 15)

    spa_sources.jolpica.answers["race_result"] = None
    with pytest.raises(NotFound, match="Belgian Grand Prix 2024 has no result yet"):
        await service(spa_sources).race(2024, 14)


async def test_season_pairs_rounds_with_openf1_sessions(spa_sources):
    view = await service(spa_sources).season(2024)
    [event] = view.events

    assert (event.round, event.session_key) == (14, 9574)
    assert view.sources["openf1"].status == "hit"


async def test_season_without_openf1_still_lists_its_rounds(spa_sources):
    spa_sources.openf1.answers["sessions"] = UpstreamRateLimited("openf1", "HTTP 429")
    view = await service(spa_sources).season(2024)

    assert [e.session_key for e in view.events] == [None]
    assert view.sources["openf1"].status == "error"


async def test_empty_season_is_not_found(spa_sources):
    spa_sources.jolpica.answers["calendar"] = []
    with pytest.raises(NotFound, match="No calendar for 2031"):
        await service(spa_sources).season(2031)


async def test_standings_after_a_round(spa_sources):
    view = await service(spa_sources).standings(2024, 14)
    assert [(s.position, s.code, s.points) for s in view.standings] == [(1, "VER", 277.0)]


def test_worst_status_wins_and_keeps_the_oldest_time():
    old, new = dt.datetime(2026, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    statuses = [SourceStatus("hit", new), SourceStatus("stale", old), SourceStatus("miss", new)]

    assert worst(statuses) == SourceStatus("stale", old)
    assert worst([*statuses, SourceStatus("error", error="down")]) == SourceStatus(
        "error", old, "down"
    )
