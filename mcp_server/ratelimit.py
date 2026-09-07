"""A small in-process sliding-window rate limiter.

Synthetic public demo — this exists to stop a runaway client, not to be a
security boundary. One process, one dict; nothing shared across instances.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Raise RateLimitExceeded if `key` is over its budget."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.max:
                retry_after = int(q[0] + self.window - now) + 1
                raise RateLimitExceeded(
                    f"rate limit: {self.max} requests / {self.window}s. "
                    f"retry in ~{retry_after}s"
                )
            q.append(now)
            if len(self._hits) > 10_000:  # crude cap so the dict can't grow forever
                self._evict(cutoff)

    def _evict(self, cutoff: float) -> None:
        for k in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            self._hits.pop(k, None)


class RateLimitExceeded(RuntimeError):
    pass
