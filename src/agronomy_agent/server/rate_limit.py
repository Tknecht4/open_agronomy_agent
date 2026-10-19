from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from math import ceil


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


@dataclass
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    backend = "memory"

    def __init__(self, *, limit: int, window_seconds: int, max_keys: int = 4096) -> None:
        if limit <= 0:
            raise ValueError("rate limit must be > 0")
        if window_seconds <= 0:
            raise ValueError("rate limit window_seconds must be > 0")
        if max_keys <= 0:
            raise ValueError("max_keys must be > 0")
        self.max_keys = max_keys
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: OrderedDict[str, _Window] = OrderedDict()

    def check(self, key: str, *, now: float) -> RateLimitResult:
        if not key:
            raise ValueError("rate limit key must be non-empty")
        # Insertion order is window-start order. Expire before admitting a new peer.
        while self._windows:
            first = next(iter(self._windows.values()))
            if now < first.started_at + self.window_seconds:
                break
            self._windows.popitem(last=False)
        window = self._windows.get(key)
        if window is None:
            if len(self._windows) >= self.max_keys:
                # Never evict an active bucket: churn must not reset a peer budget.
                first = next(iter(self._windows.values()))
                return RateLimitResult(False, self.limit, 0, max(1, ceil(first.started_at + self.window_seconds - now)))
            window = _Window(started_at=now, count=0)
            self._windows[key] = window
        if window.count >= self.limit:
            return RateLimitResult(
                allowed=False,
                limit=self.limit,
                remaining=0,
                reset_after_seconds=max(1, ceil(window.started_at + self.window_seconds - now)),
            )
        window.count += 1
        return RateLimitResult(
            allowed=True,
            limit=self.limit,
            remaining=max(0, self.limit - window.count),
            reset_after_seconds=max(1, ceil(window.started_at + self.window_seconds - now)),
        )
