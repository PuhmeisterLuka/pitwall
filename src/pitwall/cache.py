"""SQLite-backed JSON cache with request coalescing and stale-on-error fallback."""

import asyncio
import json
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pitwall.errors import UpstreamError
from pitwall.ratelimit import Clock

Fetch = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class Cached:
    """A value, how the cache served it, and when it came from upstream (epoch seconds)."""

    value: Any
    status: Literal["hit", "miss", "stale"]
    fetched_at: float


def cache_key(source: str, path: str, params: Mapping[str, Any] | None = None) -> str:
    """Build a key that ignores parameter order."""
    query = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    return f"{source}:{path}?{query}"


class Cache:
    """Serve fresh entries, fetch missing or expired ones, fall back to stale on failure."""

    def __init__(self, path: str | Path = ":memory:", clock: Clock = time.time) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS entries"
            " (key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at REAL NOT NULL)"
        )
        self._clock = clock
        self._inflight: dict[str, asyncio.Task[Cached]] = {}

    async def get_or_fetch(self, key: str, ttl_s: float, fetch: Fetch) -> Cached:
        """Return the entry for `key`, calling `fetch` if it is missing or older than `ttl_s`."""
        entry = self._read(key)
        if entry and self._clock() - entry.fetched_at < ttl_s:
            return entry
        try:
            return await self._refresh(key, fetch)
        except UpstreamError:
            if entry is None:
                raise
            return replace(entry, status="stale")

    async def _refresh(self, key: str, fetch: Fetch) -> Cached:
        # Concurrent misses on one key share a single upstream call.
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch_and_store(key, fetch))
            self._inflight[key] = task
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        # Shield so one cancelled caller doesn't cancel the fetch for the others.
        return await asyncio.shield(task)

    async def _fetch_and_store(self, key: str, fetch: Fetch) -> Cached:
        value = await fetch()
        fetched_at = self._clock()
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO entries VALUES (?, ?, ?)",
                (key, json.dumps(value), fetched_at),
            )
        return Cached(value, "miss", fetched_at)

    def _read(self, key: str) -> Cached | None:
        row = self._db.execute(
            "SELECT value, fetched_at FROM entries WHERE key = ?", (key,)
        ).fetchone()
        return Cached(json.loads(row[0]), "hit", row[1]) if row else None

    def close(self) -> None:
        self._db.close()
