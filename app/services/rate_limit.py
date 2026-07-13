"""Small bounded in-process sliding-window limiter for public portal endpoints."""

from __future__ import annotations

from collections import OrderedDict, deque
from math import ceil
from threading import Lock
from time import monotonic
from typing import Deque, Optional


class SlidingWindowLimiter:
    """Track recent events without allowing unbounded attacker-controlled keys."""

    def __init__(self, *, max_keys: int = 10_000) -> None:
        self.max_keys = max_keys
        self._events: OrderedDict[str, Deque[float]] = OrderedDict()
        self._lock = Lock()

    def hit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        now: Optional[float] = None,
    ) -> int:
        """Record an event and return zero, or seconds until another is allowed."""

        current = monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            events = self._events.get(key)
            if events is None:
                while len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                events = deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)

            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, ceil(events[0] + window_seconds - current))
            events.append(current)
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
