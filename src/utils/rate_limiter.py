"""Small sliding-window rate limiter for public APIs."""

from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Synchronous sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self.timestamps and self.timestamps[0] < now - self.window_seconds:
            self.timestamps.popleft()

        if len(self.timestamps) >= self.max_requests:
            sleep_time = self.timestamps[0] + self.window_seconds - now
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.timestamps.append(time.monotonic())
