"""Build the API's views from both sources and record where each part came from."""

import asyncio
import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from pitwall.cache import Cached
from pitwall.errors import UpstreamError
from pitwall.models import Event, RaceReport, Standing
from pitwall.normalize import (
    SessionData,
    build_calendar,
    build_report,
    match_session,
    parse_event,
    parse_standings,
)
from pitwall.sources import Sources

SETTLE_AFTER = dt.timedelta(days=3)  # by then the stewards have ruled on penalties
SEVERITY = ("hit", "miss", "stale", "error")

Status = Literal["hit", "miss", "stale", "error"]


class NotFound(Exception):
    """Nothing to show for this season or round (yet)."""


@dataclass(frozen=True, slots=True)
class SourceStatus:
    status: Status  # hit: cached, miss: fetched now, stale: upstream failed, old copy served
    fetched_at: dt.datetime | None = None  # age of the oldest data used
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SeasonView:
    season: int
    events: list[Event]
    sources: dict[str, SourceStatus]


@dataclass(frozen=True, slots=True)
class RaceView:
    report: RaceReport
    sources: dict[str, SourceStatus]


@dataclass(frozen=True, slots=True)
class StandingsView:
    season: int
    round: int
    standings: list[Standing]
    sources: dict[str, SourceStatus]


class Provenance:
    """Records how each upstream answered while the service builds one response."""

    def __init__(self) -> None:
        self._seen: defaultdict[str, list[SourceStatus]] = defaultdict(list)

    def use(self, source: str, cached: Cached) -> Any:
        fetched_at = dt.datetime.fromtimestamp(cached.fetched_at, dt.UTC)
        self._seen[source].append(SourceStatus(cached.status, fetched_at))
        return cached.value

    def fail(self, source: str, error: UpstreamError) -> None:
        self._seen[source].append(SourceStatus("error", error=error.message))

    def summary(self) -> dict[str, SourceStatus]:
        return {source: worst(statuses) for source, statuses in self._seen.items()}


def worst(statuses: list[SourceStatus]) -> SourceStatus:
    """The most severe status, dated by the oldest data behind it."""
    severest = max(statuses, key=lambda s: SEVERITY.index(s.status))
    oldest = min((s.fetched_at for s in statuses if s.fetched_at), default=None)
    return replace(severest, fetched_at=oldest)


def utc_today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


class RaceService:
    def __init__(self, sources: Sources, today: Callable[[], dt.date] = utc_today) -> None:
        self._jolpica = sources.jolpica
        self._openf1 = sources.openf1
        self._today = today

    async def season(self, season: int) -> SeasonView:
        log = Provenance()
        races = await self._calendar(season, log)
        sessions = await self._sessions(season, log)
        return SeasonView(season, build_calendar(races, sessions), log.summary())

    async def race(self, season: int, round_no: int) -> RaceView:
        log = Provenance()
        event = await self._event(season, round_no, log)
        settled = self._settled(event)
        cached = await self._jolpica.race_result(season, round_no, settled=settled)
        race = log.use("jolpica", cached)
        if race is None:
            raise NotFound(f"{event.name} {season} has no result yet")
        timing = await self._timing(event, settled, log)
        return RaceView(build_report(race, timing), log.summary())

    async def standings(self, season: int, round_no: int) -> StandingsView:
        log = Provenance()
        event = await self._event(season, round_no, log)
        settled = self._settled(event)
        cached = await self._jolpica.driver_standings(season, round_no, settled=settled)
        rows = log.use("jolpica", cached)
        if not rows:
            raise NotFound(f"No standings after {event.name} {season} yet")
        return StandingsView(season, round_no, parse_standings(rows), log.summary())

    async def _calendar(self, season: int, log: Provenance) -> list[dict]:
        races = log.use("jolpica", await self._jolpica.calendar(season, settled=self._past(season)))
        if not races:
            raise NotFound(f"No calendar for {season}")
        return races

    async def _event(self, season: int, round_no: int, log: Provenance) -> Event:
        races = await self._calendar(season, log)
        event = next((e for e in map(parse_event, races) if e.round == round_no), None)
        if event is None:
            raise NotFound(f"{season} has no round {round_no}")
        return event

    async def _sessions(self, season: int, log: Provenance) -> list[dict]:
        """OpenF1's race sessions, or [] if OpenF1 fails; the official data goes out either way."""
        try:
            cached = await self._openf1.sessions(season, settled=self._past(season))
        except UpstreamError as error:
            log.fail("openf1", error)
            return []
        return log.use("openf1", cached)

    async def _timing(self, event: Event, settled: bool, log: Provenance) -> SessionData | None:
        session = match_session(event, await self._sessions(event.season, log))
        if session is None:
            return None
        key, openf1 = session["session_key"], self._openf1
        try:
            answers = await asyncio.gather(
                openf1.drivers(key, settled=settled),
                openf1.laps(key, settled=settled),
                openf1.stints(key, settled=settled),
                openf1.pit_stops(key, settled=settled),
                openf1.weather(key, settled=settled),
            )
        except UpstreamError as error:
            log.fail("openf1", error)
            return None
        return SessionData(session, *(log.use("openf1", answer) for answer in answers))

    def _past(self, season: int) -> bool:
        return season < self._today().year

    def _settled(self, event: Event) -> bool:
        return event.date + SETTLE_AFTER <= self._today()
