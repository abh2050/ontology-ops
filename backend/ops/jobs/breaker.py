"""Process-local circuit breaker for paid provider calls (spec 12.3).

After 5 consecutive known provider failures it opens for 60 seconds and blocks new
paid admissions; then it allows exactly one half-open probe. This is not fleet
wide: it is correct only while one worker process runs (documented in decisions.md).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class CircuitBreaker:
    def __init__(self, threshold: int = 5, open_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self.probe_in_flight = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state()

    def _state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.open_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        with self._lock:
            state = self._state()
            if state == "closed":
                return True
            if state == "half_open" and not self.probe_in_flight:
                self.probe_in_flight = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self.opened_at = None
            self.probe_in_flight = False

    def record_known_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.probe_in_flight or self.failures >= self.threshold:
                self.opened_at = self.clock()
            self.probe_in_flight = False

    def release_probe(self) -> None:
        """An admitted probe ended without a provider verdict (e.g. unknown outcome)."""
        with self._lock:
            self.probe_in_flight = False
