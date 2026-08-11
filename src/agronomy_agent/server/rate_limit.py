from __future__ import annotations

import hashlib
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


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


class RateLimiterUnavailable(RuntimeError):
    pass


class RedisProtocolClient:
    def __init__(self, redis_url: str, *, timeout_seconds: float = 1.0) -> None:
        parsed = urlparse(redis_url)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("Redis rate limit URL must be redis://host[:port][/db]")
        self.host = parsed.hostname
        self.port = parsed.port or 6379
        self.password = parsed.password
        self.db = int(parsed.path.strip("/") or "0")
        self.timeout_seconds = timeout_seconds

    def execute(self, *parts: object) -> Any:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as conn:
                conn.settimeout(self.timeout_seconds)
                if self.password:
                    self._send(conn, "AUTH", self.password)
                    self._read(conn)
                if self.db:
                    self._send(conn, "SELECT", self.db)
                    self._read(conn)
                self._send(conn, *parts)
                return self._read(conn)
        except OSError as exc:
            raise RateLimiterUnavailable(f"Redis rate limiter unavailable: {exc}") from exc

    def _send(self, conn: socket.socket, *parts: object) -> None:
        payload = [f"*{len(parts)}\r\n".encode("ascii")]
        for part in parts:
            encoded = str(part).encode("utf-8")
            payload.append(f"${len(encoded)}\r\n".encode("ascii"))
            payload.append(encoded + b"\r\n")
        conn.sendall(b"".join(payload))

    def _read_line(self, conn: socket.socket) -> bytes:
        data = bytearray()
        while not data.endswith(b"\r\n"):
            chunk = conn.recv(1)
            if not chunk:
                raise RateLimiterUnavailable("Redis connection closed")
            data.extend(chunk)
        return bytes(data[:-2])

    def _read(self, conn: socket.socket) -> Any:
        prefix = conn.recv(1)
        if not prefix:
            raise RateLimiterUnavailable("Redis connection closed")
        if prefix == b"+":
            return self._read_line(conn).decode("utf-8")
        if prefix == b":":
            return int(self._read_line(conn))
        if prefix == b"$":
            length = int(self._read_line(conn))
            if length < 0:
                return None
            payload = b""
            while len(payload) < length + 2:
                chunk = conn.recv(length + 2 - len(payload))
                if not chunk:
                    raise RateLimiterUnavailable("Redis bulk response ended early")
                payload += chunk
            return payload[:-2].decode("utf-8")
        if prefix == b"-":
            raise RateLimiterUnavailable(self._read_line(conn).decode("utf-8"))
        raise RateLimiterUnavailable(f"unsupported Redis response prefix: {prefix!r}")


class RedisFixedWindowRateLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        redis_url: str,
        key_prefix: str = "agronomy:rate_limit",
        client: Any | None = None,
    ) -> None:
        if limit <= 0:
            raise ValueError("rate limit must be > 0")
        if window_seconds <= 0:
            raise ValueError("rate limit window_seconds must be > 0")
        if not redis_url.strip() and client is None:
            raise ValueError("redis_url is required")
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix.strip(":") or "agronomy:rate_limit"
        self.client = client or RedisProtocolClient(redis_url)

    def check(self, key: str, *, now: float | None = None) -> RateLimitResult:
        if not key:
            raise ValueError("rate limit key must be non-empty")
        redis_key = f"{self.key_prefix}:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
        try:
            count = int(self.client.execute("INCR", redis_key))
            if count == 1:
                self.client.execute("EXPIRE", redis_key, self.window_seconds)
            ttl = int(self.client.execute("TTL", redis_key))
        except (OSError, TypeError, ValueError, RateLimiterUnavailable) as exc:
            raise RateLimiterUnavailable(str(exc)) from exc
        reset_after = ttl if ttl > 0 else self.window_seconds
        return RateLimitResult(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=max(0, self.limit - count),
            reset_after_seconds=max(1, reset_after),
        )
