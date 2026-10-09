"""Jolpica-F1 (Ergast-compatible): calendar, official results, standings."""

from typing import Any

from pitwall.cache import Cached
from pitwall.errors import UpstreamBadResponse
from pitwall.sources.base import Extract, Source

PAGE_LIMIT = 100  # Jolpica's maximum page size


class Jolpica(Source):
    name = "jolpica"
    limits = ((4, 1.0), (500, 3600.0))

    async def calendar(self, season: int, *, settled: bool = False) -> Cached:
        """Every round of the season, in order."""
        return await self._table(f"/{season}/races.json", _races, settled)

    async def race_result(self, season: int, round_no: int, *, settled: bool = False) -> Cached:
        """The race with its classified `Results`, or None before it has run."""
        return await self._table(f"/{season}/{round_no}/results.json", _first_race, settled)

    async def driver_standings(
        self, season: int, round_no: int, *, settled: bool = False
    ) -> Cached:
        """Championship order after `round_no`."""
        return await self._table(f"/{season}/{round_no}/driverStandings.json", _standings, settled)

    async def _table(self, path: str, extract: Extract, settled: bool) -> Cached:
        """Fetch one page of an MRData response and pull the rows out of it."""

        def unwrap(payload: Any) -> Any:
            data = payload["MRData"]
            if int(data["total"]) > PAGE_LIMIT:
                raise UpstreamBadResponse(self.name, f"{path} has more than {PAGE_LIMIT} rows")
            return extract(data)

        return await self._get(path, {"limit": PAGE_LIMIT}, settled=settled, extract=unwrap)


def _races(data: Any) -> list[dict]:
    return data["RaceTable"]["Races"]


def _first_race(data: Any) -> dict | None:
    return next(iter(_races(data)), None)


def _standings(data: Any) -> list[dict]:
    lists = data["StandingsTable"]["StandingsLists"]
    return lists[0]["DriverStandings"] if lists else []
