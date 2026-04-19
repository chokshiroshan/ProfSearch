"""Simple async rate limiter based on minimum request spacing."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._lock = asyncio.Lock()
        self._next_allowed_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed_at - now
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            self._next_allowed_at = time.monotonic() + self.min_interval_seconds
