import json
from pathlib import Path
from typing import Any

import pytest

from pitwall.cache import Cached
from pitwall.sources import Sources

STANDING = {
    "position": "1",
    "points": "277",
    "wins": "7",
    "Driver": {"code": "VER", "givenName": "Max", "familyName": "Verstappen"},
    "Constructors": [{"name": "Red Bull"}],
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClock:
    """Manual clock: sleep() moves time forward without waiting."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(scope="session")
def spa() -> dict:
    """Trimmed real responses for the 2024 Belgian GP from both APIs."""
    path = Path(__file__).parent / "fixtures" / "spa_2024.json"
    return json.loads(path.read_text(encoding="utf-8"))


class StubSource:
    """Stands in for a source: each method answers from `answers`, or raises it if it's an error."""

    def __init__(self, name: str, **answers: Any) -> None:
        self.name = name
        self.answers = answers
        self.status = "hit"
        self.fetched_at = 1_760_000_000.0  # when the stubbed answers claim to come from
        self.calls: list[tuple[str, tuple, bool]] = []

    def __getattr__(self, method: str) -> Any:
        if method not in self.answers:
            raise AttributeError(method)

        async def answer(*args: Any, settled: bool = False) -> Cached:
            self.calls.append((method, args, settled))
            value = self.answers[method]
            if isinstance(value, Exception):
                raise value
            return Cached(value, self.status, self.fetched_at)

        return answer


@pytest.fixture
def spa_sources(spa) -> Sources:
    """Both sources answering with the recorded 2024 Belgian GP."""
    race = spa["jolpica_race"]
    jolpica = StubSource(
        "jolpica",
        calendar=[{key: value for key, value in race.items() if key != "Results"}],
        race_result=race,
        driver_standings=[STANDING],
    )
    openf1 = StubSource(
        "openf1",
        sessions=[spa["openf1_session"]],
        drivers=spa["openf1_drivers"],
        laps=spa["openf1_laps"],
        stints=spa["openf1_stints"],
        pit_stops=spa["openf1_pit_stops"],
        weather=spa["openf1_weather"],
    )
    return Sources(jolpica, openf1)
