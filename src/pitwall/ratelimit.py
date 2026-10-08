"""Client-side sliding-window rate limiting."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Allow at most `count` calls per `seconds`, for every (count, seconds) window given."""

    def __init__(
        self,
        *windows: tuple[int, float],
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._windows = windows
        self._horizon = max((seconds for _, seconds in windows), default=0.0)
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._clock = clock
        self._sleep = sleep

    async def acquire(self) -> None:
        """Wait until one more call fits in every window, then record it."""
        async with self._lock:
            while (wait := self._wait_s(self._clock())) > 0:
                await self._sleep(wait)
            self._calls.append(self._clock())

    def _wait_s(self, now: float) -> float:
        while self._calls and now - self._calls[0] >= self._horizon:
            self._calls.popleft()

        wait = 0.0
        for count, seconds in self._windows:
            recent = [t for t in self._calls if now - t < seconds]
            if len(recent) >= count:
                # Wait until enough of the oldest calls leave this window.
                wait = max(wait, recent[-count] + seconds - now)
        return wait
