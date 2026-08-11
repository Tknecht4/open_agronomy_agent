from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import nullcontext
from typing import Any

from fastapi import Request


ACCESS_LOGGER_NAME = "agronomy_agent.server.access"
ACCESS_LOGGER = logging.getLogger(ACCESS_LOGGER_NAME)
TRACEPARENT_RE = re.compile(r"^[\da-f]{2}-([\da-f]{32})-[\da-f]{16}-[\da-f]{2}$")


class ServerTelemetry:
    def __init__(self, *, enabled: bool, service_name: str) -> None:
        self.enabled = enabled
        self.service_name = service_name
        self.available = False
        self.reason = "disabled"
        self._trace: Any = None
        self._propagate: Any = None
        self._tracer: Any = None
        if not enabled:
            return
        try:
            from opentelemetry import propagate, trace
        except ImportError:
            self.reason = "opentelemetry package not installed"
            return
        self._trace = trace
        self._propagate = propagate
        self._tracer = trace.get_tracer(service_name)
        self.available = True
        self.reason = "enabled"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "service_name": self.service_name,
            "reason": self.reason,
        }

    def start_http_span(self, request: Request, request_id_value: str) -> Any:
        if not self.available:
            return nullcontext(None)
        context = self._propagate.extract(dict(request.headers))
        span_name = f"{request.method} {request.url.path}"
        return self._tracer.start_as_current_span(
            span_name,
            context=context,
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "server.request_id": request_id_value,
            },
        )


def build_telemetry(*, enabled: bool, service_name: str) -> ServerTelemetry:
    return ServerTelemetry(enabled=enabled, service_name=service_name)


def request_actor(request: Request) -> dict[str, str]:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        return {"actor_type": "bearer", "actor_hash": _stable_hash(authorization)}
    email = request.headers.get("x-agronomy-user-email", "").strip().lower()
    if email:
        return {"actor_type": "local_dev_email", "actor_hash": _stable_hash(email)}
    client_host = request.client.host if request.client else "unknown"
    return {"actor_type": "client_host", "actor_hash": _stable_hash(client_host)}


def request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "").strip()
    return supplied[:128] if supplied else uuid.uuid4().hex


def request_trace_id(request: Request) -> str | None:
    traceparent = request.headers.get("traceparent", "").strip().lower()
    match = TRACEPARENT_RE.match(traceparent)
    return match.group(1) if match else None


def log_request(
    *,
    request: Request,
    request_id_value: str,
    status_code: int,
    started_at: float,
    rate_limited: bool = False,
    error_type: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "http_request",
        "request_id": request_id_value,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        "rate_limited": rate_limited,
        **request_actor(request),
    }
    if request.query_params:
        payload["query_keys"] = sorted(request.query_params.keys())
    trace_id = request_trace_id(request)
    if trace_id:
        payload["trace_id"] = trace_id
    if error_type:
        payload["error_type"] = error_type
    level = logging.WARNING if status_code >= 400 else logging.INFO
    ACCESS_LOGGER.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
