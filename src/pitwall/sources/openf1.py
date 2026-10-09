"""OpenF1: per-session timing data keyed by car number."""

from typing import Any

from pitwall.cache import Cached
from pitwall.errors import UpstreamBadResponse, UpstreamNotFound
from pitwall.http import Params
from pitwall.sources.base import Source


class OpenF1(Source):
    name = "openf1"
    limits = ((3, 1.0), (30, 60.0))

    async def sessions(self, year: int, *, name: str = "Race", settled: bool = False) -> Cached:
        """A year's sessions with this name ("Race", "Sprint", "Qualifying", ...)."""
        return await self._get("/sessions", {"year": year, "session_name": name}, settled=settled)

    async def drivers(self, session_key: int, *, settled: bool = False) -> Cached:
        return await self._session_rows("/drivers", session_key, settled)

    async def laps(self, session_key: int, *, settled: bool = False) -> Cached:
        return await self._session_rows("/laps", session_key, settled)

    async def stints(self, session_key: int, *, settled: bool = False) -> Cached:
        return await self._session_rows("/stints", session_key, settled)

    async def pit_stops(self, session_key: int, *, settled: bool = False) -> Cached:
        return await self._session_rows("/pit", session_key, settled)

    async def results(self, session_key: int, *, settled: bool = False) -> Cached:
        return await self._session_rows("/session_result", session_key, settled)

    async def weather(self, session_key: int, *, settled: bool = False) -> Cached:
        return await self._session_rows("/weather", session_key, settled)

    async def _session_rows(self, path: str, session_key: int, settled: bool) -> Cached:
        return await self._get(path, {"session_key": session_key}, settled=settled)

    async def _request(self, path: str, params: Params | None) -> Any:
        try:
            rows = await self._http.get(path, params)
        except UpstreamNotFound:
            return []  # OpenF1 answers an empty query with 404
        if not isinstance(rows, list):
            raise UpstreamBadResponse(self.name, f"expected a list from {path}")
        return rows
