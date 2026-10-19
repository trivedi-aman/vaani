"""
In-memory rate limits for a single-server deployment.

Sliding windows keyed by (bucket, client), plus a daily budget for the
expensive thing (calls, which spend Bedrock and Sarvam credit). For more
than one server, swap this for Redis behind the same two methods.
"""
import threading
import time
from collections import deque
from datetime import UTC, datetime


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int | None:
        """Record a hit. Returns None if allowed, else seconds until the next one is."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            if len(self._hits) > 20_000:            # forget idle clients
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[k]
            return None

    def blocked(self, key: str) -> int | None:
        """Like hit(), but only looks: None if a hit would be allowed, else seconds to wait."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            while q and now - q[0] > self.window:
                q.popleft()
            if q and len(q) >= self.limit:
                return max(1, int(self.window - (now - q[0])) + 1)
            return None


class DailyBudget:
    def __init__(self, limit: int):
        self.limit = limit
        self._day = ""
        self._used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        with self._lock:
            if today != self._day:
                self._day, self._used = today, 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        return self._used
