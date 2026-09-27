from __future__ import annotations

from dataclasses import dataclass


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

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        if limit <= 0:
            raise ValueError("rate limit must be > 0")
        if window_seconds <= 0:
            raise ValueError("rate limit window_seconds must be > 0")
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, _Window] = {}

    def check(self, key: str, *, now: float) -> RateLimitResult:
        if not key:
            raise ValueError("rate limit key must be non-empty")
        window = self._windows.get(key)
        if window is None or now - window.started_at >= self.window_seconds:
            window = _Window(started_at=now, count=0)
            self._windows[key] = window
        if window.count >= self.limit:
            return RateLimitResult(
                allowed=False,
                limit=self.limit,
                remaining=0,
                reset_after_seconds=max(1, int(window.started_at + self.window_seconds - now)),
            )
        window.count += 1
        return RateLimitResult(
            allowed=True,
            limit=self.limit,
            remaining=max(0, self.limit - window.count),
            reset_after_seconds=max(1, int(window.started_at + self.window_seconds - now)),
        )
