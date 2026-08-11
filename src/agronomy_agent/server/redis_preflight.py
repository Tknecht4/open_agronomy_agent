from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from agronomy_agent.server.rate_limit import RateLimiterUnavailable, RedisProtocolClient
from agronomy_agent.server.settings import ServerSettings, build_settings


class RedisPreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class RedisPreflightResult:
    backend: str
    queue_names: list[str]
    probe_prefix: str
    ping: str
    queue_write_pop_checked: bool
    rate_limit_counter_checked: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "queue_names": self.queue_names,
            "probe_prefix": self.probe_prefix,
            "ping": self.ping,
            "queue_write_pop_checked": self.queue_write_pop_checked,
            "rate_limit_counter_checked": self.rate_limit_counter_checked,
        }


def preflight_redis(
    settings: ServerSettings,
    *,
    client_factory: Callable[[str], Any] | None = None,
    probe_prefix: str | None = None,
) -> RedisPreflightResult:
    if not settings.redis_url:
        raise RedisPreflightError("Redis preflight failed: AGRONOMY_AGENT_REDIS_URL or REDIS_URL is required")
    redis_url = str(settings.redis_url)
    try:
        client = client_factory(redis_url) if client_factory else RedisProtocolClient(redis_url)
    except (OSError, TypeError, ValueError, RateLimiterUnavailable) as exc:
        raise RedisPreflightError(f"Redis preflight failed: {_sanitize_error(exc, redis_url)}") from exc
    prefix = (probe_prefix or f"agronomy:preflight:{uuid.uuid4().hex}").strip(":")
    queue_names = _configured_queue_names(settings)
    cleanup_keys: list[str] = []
    try:
        ping = str(client.execute("PING"))
        if ping.upper() != "PONG":
            raise RedisPreflightError(f"Redis preflight failed: unexpected PING response {ping!r}")
        for index, _queue_name in enumerate(queue_names):
            probe_queue = f"{prefix}:queue:{index}"
            cleanup_keys.append(probe_queue)
            token = f"probe-{index}-{uuid.uuid4().hex}"
            depth = int(client.execute("RPUSH", probe_queue, token))
            if depth < 1:
                raise RedisPreflightError("Redis preflight failed: probe queue write returned invalid depth")
            observed = client.execute("LPOP", probe_queue)
            if observed != token:
                raise RedisPreflightError("Redis preflight failed: probe queue readback mismatch")
            client.execute("DEL", probe_queue)
            cleanup_keys.remove(probe_queue)
        counter_key = f"{prefix}:rate-limit"
        cleanup_keys.append(counter_key)
        count = int(client.execute("INCR", counter_key))
        if count != 1:
            raise RedisPreflightError("Redis preflight failed: probe counter did not start at 1")
        client.execute("EXPIRE", counter_key, max(1, settings.rate_limit_window_seconds))
        ttl = int(client.execute("TTL", counter_key))
        if ttl <= 0:
            raise RedisPreflightError("Redis preflight failed: probe counter TTL was not set")
        client.execute("DEL", counter_key)
        cleanup_keys.remove(counter_key)
    except RedisPreflightError:
        raise
    except (OSError, TypeError, ValueError, RateLimiterUnavailable) as exc:
        raise RedisPreflightError(f"Redis preflight failed: {_sanitize_error(exc, settings.redis_url)}") from exc
    finally:
        for key in cleanup_keys:
            try:
                client.execute("DEL", key)
            except Exception:
                pass
    return RedisPreflightResult(
        backend="redis",
        queue_names=queue_names,
        probe_prefix=prefix,
        ping=ping,
        queue_write_pop_checked=True,
        rate_limit_counter_checked=True,
    )


def _configured_queue_names(settings: ServerSettings) -> list[str]:
    names = [
        settings.job_queue_name,
        settings.eval_queue_name,
        settings.export_queue_name,
        settings.embedding_queue_name,
        settings.image_queue_name,
    ]
    unique = []
    for name in names:
        normalized = name.strip()
        if not normalized:
            raise RedisPreflightError("Redis preflight failed: queue names must be non-empty")
        if normalized not in unique:
            unique.append(normalized)
    if len(unique) != len(names):
        raise RedisPreflightError("Redis preflight failed: queue names must be unique")
    return unique


def _sanitize_error(exc: Exception, redis_url: str | None) -> str:
    message = str(exc)
    if redis_url:
        message = message.replace(str(redis_url), "redis://<redacted>")
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight the Phase 4 Redis queue/rate-limit backend.")
    parser.add_argument("--redis-url", help="Override AGRONOMY_AGENT_REDIS_URL.")
    parser.add_argument("--probe-prefix", help="Temporary Redis key prefix for preflight probes.")
    args = parser.parse_args(argv)

    try:
        settings = build_settings(redis_url=args.redis_url)
        result = preflight_redis(settings, probe_prefix=args.probe_prefix)
    except (RedisPreflightError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", **result.as_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
