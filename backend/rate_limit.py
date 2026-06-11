"""In-memory sliding-window rate limiter.

Each caller key gets a `deque[float]` of request timestamps. A request
is allowed only if fewer than `limit` timestamps fall in the trailing
`window` seconds.

Suitable for a single process; for multi-replica deployments swap the
dict for Redis. Idle keys are evicted lazily by `consume()` to keep the
dict bounded under realistic traffic — a caller that sends 1 request
and goes silent would otherwise own its deque for the lifetime of the
process.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowCounter:
    """Counts requests in the last N seconds per key.

    Use this when bursts should not be allowed to "save up" — each call
    records a timestamp and a request is allowed only if fewer than
    `limit` timestamps fall in the trailing window.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self.limit = limit
        self.window = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        # When the dict grows past this size, do a single sweep on the
        # next consume() call: drop every entry whose newest stamp is
        # older than the window. Cheap O(n) amortised over a constant
        # number of calls between sweeps.
        self._evict_threshold = 1024

    def consume(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            if len(self._buckets) > self._evict_threshold:
                self._evict_stale(cutoff)
            stamps = self._buckets.get(key)
            if stamps is None:
                stamps = deque()
                self._buckets[key] = stamps
            while stamps and stamps[0] < cutoff:
                stamps.popleft()
            if len(stamps) >= self.limit:
                return False
            stamps.append(now)
            return True

    def _evict_stale(self, cutoff: float) -> None:
        """Drop entries whose newest stamp is already past the window.

        A deque with no in-window timestamps has nothing useful to add
        to a future consume(); removing it keeps the dict bounded.
        """
        stale = [k for k, q in self._buckets.items() if not q or q[-1] < cutoff]
        for k in stale:
            del self._buckets[k]
