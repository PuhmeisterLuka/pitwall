import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClock:
    """Manual clock whose sleep advances time instantly."""

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
