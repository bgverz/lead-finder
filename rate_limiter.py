"""Rate limiter for API calls."""

import asyncio
import time
from collections import deque


class RateLimiter:
    """Simple sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.monotonic()

            # Remove timestamps outside the window
            while self.timestamps and self.timestamps[0] < now - self.window_seconds:
                self.timestamps.popleft()

            # If at capacity, wait until the oldest request expires
            if len(self.timestamps) >= self.max_requests:
                sleep_time = self.timestamps[0] + self.window_seconds - now
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            self.timestamps.append(time.monotonic())

    def acquire_sync(self):
        """Synchronous version for non-async code."""
        now = time.monotonic()

        while self.timestamps and self.timestamps[0] < now - self.window_seconds:
            self.timestamps.popleft()

        if len(self.timestamps) >= self.max_requests:
            sleep_time = self.timestamps[0] + self.window_seconds - now
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.timestamps.append(time.monotonic())