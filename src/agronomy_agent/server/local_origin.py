"""Strict browser boundaries for the unauthenticated loopback development profile."""
from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
FORWARDED_HEADERS = frozenset({"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port"})
DEFAULT_DEV_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173", "http://[::1]:5173")


def loopback_origin(value: str) -> str:
    """Accept a serialized HTTP(S) origin, never credentials, paths or loose hosts."""
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid loopback origin") from exc
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS
            or parsed.username is not None or parsed.password is not None
            or value != f"{parsed.scheme}://{parsed.netloc}" or any(c.isspace() for c in value)
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("invalid loopback origin")
    # Require the ordinary serialized spelling, including brackets for IPv6.
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if parsed.netloc != host + (f":{port}" if port is not None else ""):
        raise ValueError("invalid loopback origin")
    return value


def development_origin_error(request: Request, extra_origins: tuple[str, ...]) -> str | None:
    hosts = request.headers.getlist("host")
    origins = request.headers.getlist("origin")
    if len(hosts) != 1 or len(origins) > 1 or any(name in request.headers for name in FORWARDED_HEADERS):
        return "Local development request authority is invalid"
    try:
        current = loopback_origin(f"{request.url.scheme}://{hosts[0]}")
        if origins:
            observed = loopback_origin(origins[0])
            if observed != current and observed not in extra_origins:
                return "Local development Origin is not allowed"
    except ValueError:
        return "Local development Host or Origin is invalid"
    return None
