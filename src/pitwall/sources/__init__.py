"""Upstream sources and how to open them together."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from pitwall.cache import Cache
from pitwall.config import Settings
from pitwall.http import JsonClient
from pitwall.ratelimit import RateLimiter
from pitwall.sources.base import Source
from pitwall.sources.jolpica import Jolpica
from pitwall.sources.openf1 import OpenF1

__all__ = ["Jolpica", "OpenF1", "Source", "Sources", "open_sources"]


@dataclass(frozen=True)
class Sources:
    jolpica: Jolpica
    openf1: OpenF1


@asynccontextmanager
async def open_sources(settings: Settings) -> AsyncIterator[Sources]:
    """Open both sources on one shared cache and close them all on exit."""
    cache = Cache(settings.cache_path)
    jolpica = Jolpica(_client(Jolpica, settings.jolpica_url, settings), cache)
    openf1 = OpenF1(_client(OpenF1, settings.openf1_url, settings), cache)
    try:
        yield Sources(jolpica, openf1)
    finally:
        await jolpica.aclose()
        await openf1.aclose()
        cache.close()


def _client(source: type[Source], base_url: str, settings: Settings) -> JsonClient:
    return JsonClient(
        source.name,
        base_url,
        RateLimiter(*source.limits),
        timeout_s=settings.timeout_s,
        max_retries=settings.max_retries,
    )
