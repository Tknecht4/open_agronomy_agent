from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from agronomy_agent.server.settings import ServerSettings


WEAK_SECRET_VALUES = {
    "",
    "changeme",
    "change-me",
    "password",
    "secret",
    "test",
    "local",
    "minio",
    "minio123",
}


@dataclass(frozen=True)
class ReadinessFinding:
    key: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "severity": self.severity, "message": self.message}


def assess_public_demo_readiness(settings: ServerSettings) -> dict[str, Any]:
    findings: list[ReadinessFinding] = []

    def blocker(key: str, message: str) -> None:
        findings.append(ReadinessFinding(key=key, severity="blocker", message=message))

    def warning(key: str, message: str) -> None:
        findings.append(ReadinessFinding(key=key, severity="warning", message=message))

    if settings.database_backend != "postgres":
        blocker("database_backend", "Public demos must use the schema-verified Postgres runtime, not local SQLite.")
    if not _url_has_scheme(settings.database_url, {"postgresql", "postgres"}):
        blocker("database_url", "AGRONOMY_AGENT_DATABASE_URL must be a Postgres URL.")

    if settings.allow_local_dev_auth:
        blocker("local_dev_auth", "Disable local-dev auth headers with AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH=false.")
    if settings.jwt_secret:
        blocker("jwt_secret", "Use OIDC/JWKS verification for public demos instead of a shared HS256 JWT secret.")
    if not _https_url(settings.jwt_jwks_url):
        blocker("jwt_jwks_url", "AGRONOMY_AGENT_JWT_JWKS_URL must be configured as HTTPS.")
    if not settings.jwt_issuer:
        blocker("jwt_issuer", "AGRONOMY_AGENT_JWT_ISSUER is required for token validation.")
    if not settings.jwt_audience:
        blocker("jwt_audience", "AGRONOMY_AGENT_JWT_AUDIENCE is required for token validation.")
    if not _https_url(settings.oidc_authorization_endpoint):
        blocker("oidc_authorization_endpoint", "OIDC authorization endpoint must be HTTPS.")
    if not _https_url(settings.oidc_token_endpoint):
        blocker("oidc_token_endpoint", "OIDC token endpoint must be HTTPS.")
    if not settings.oidc_client_id:
        blocker("oidc_client_id", "OIDC client id is required.")
    if not _https_url(settings.oidc_redirect_uri):
        blocker("oidc_redirect_uri", "OIDC redirect URI must be HTTPS.")
    if not _strong_secret(settings.oidc_session_secret, min_length=32):
        blocker("oidc_session_secret", "OIDC session secret must be non-placeholder and at least 32 characters.")
    if settings.oidc_client_secret and not _strong_secret(settings.oidc_client_secret, min_length=16):
        blocker("oidc_client_secret", "OIDC client secret is configured but too weak or placeholder-like.")
    if settings.oidc_logout_endpoint and not _https_url(settings.oidc_logout_endpoint):
        blocker("oidc_logout_endpoint", "Configured provider logout endpoint must be HTTPS.")
    if settings.oidc_post_logout_redirect_uri and not _https_url(settings.oidc_post_logout_redirect_uri):
        blocker("oidc_post_logout_redirect_uri", "Configured post-logout redirect URI must be HTTPS.")

    if settings.rate_limit_backend != "redis":
        blocker("rate_limit_backend", "Public demos need Redis-backed rate limiting for shared API replicas.")
    if settings.rate_limit_fail_open:
        blocker("rate_limit_fail_open", "Rate limiting must fail closed for public demos.")
    if settings.rate_limit_requests > 600:
        warning("rate_limit_budget", "Rate-limit request budget is above the recommended demo ceiling of 600 per window.")

    if settings.job_queue_backend != "redis":
        blocker("job_queue_backend", "Public demos need Redis-backed job queues.")
    if settings.job_queue_fail_open:
        blocker("job_queue_fail_open", "Job queue enqueue failures must fail closed for public demos.")
    if not _redis_url(settings.redis_url):
        blocker("redis_url", "AGRONOMY_AGENT_REDIS_URL or REDIS_URL must be a Redis URL.")

    if settings.object_store_backend != "s3":
        blocker("object_store_backend", "Public demos must use S3-compatible object storage, not local filesystem storage.")
    if not _https_url(settings.object_store_endpoint):
        blocker("object_store_endpoint", "S3-compatible object-store endpoint must be HTTPS.")
    if not settings.object_store_bucket:
        blocker("object_store_bucket", "Object-store bucket is required.")
    if not settings.object_store_region:
        blocker("object_store_region", "Object-store region is required.")
    if not _strong_secret(settings.object_store_access_key, min_length=8):
        blocker("object_store_access_key", "Object-store access key must be configured and non-placeholder.")
    if not _strong_secret(settings.object_store_secret_key, min_length=16):
        blocker("object_store_secret_key", "Object-store secret key must be configured and non-placeholder.")

    if settings.attachment_scan_backend != "http":
        blocker("attachment_scan_backend", "Public demos must use a production attachment malware scanner, not the local signature stub.")
    if not _https_url(settings.attachment_scan_endpoint):
        blocker("attachment_scan_endpoint", "Attachment scan endpoint must be configured as HTTPS.")

    if not settings.structured_access_logs:
        blocker("structured_access_logs", "Structured access logs must be enabled for incident traceability.")
    if not settings.otel_enabled:
        blocker("otel_enabled", "OpenTelemetry must be enabled before public demo promotion.")
    if not settings.otel_service_name:
        blocker("otel_service_name", "OpenTelemetry service name is required.")

    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    warning_count = sum(1 for finding in findings if finding.severity == "warning")
    checks = {
        "database": settings.database_backend == "postgres" and bool(settings.database_url),
        "auth": not settings.allow_local_dev_auth and bool(settings.jwt_jwks_url) and bool(settings.oidc_session_secret),
        "rate_limit": settings.rate_limit_backend == "redis" and not settings.rate_limit_fail_open,
        "queue": settings.job_queue_backend == "redis" and not settings.job_queue_fail_open,
        "object_store": settings.object_store_backend == "s3" and bool(settings.object_store_bucket),
        "attachment_scanning": settings.attachment_scan_backend == "http" and bool(settings.attachment_scan_endpoint),
        "observability": settings.structured_access_logs and settings.otel_enabled,
    }
    return {
        "status": "ready" if blocker_count == 0 else "blocked",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "checks": checks,
        "findings": [finding.as_dict() for finding in findings],
    }


def readiness_report_json(settings: ServerSettings) -> str:
    return json.dumps(assess_public_demo_readiness(settings), indent=2, sort_keys=True)


def _url_has_scheme(value: str | None, schemes: set[str]) -> bool:
    if not value:
        return False
    return urlparse(value).scheme.lower() in schemes


def _https_url(value: str | None) -> bool:
    return _url_has_scheme(value, {"https"})


def _redis_url(value: str | None) -> bool:
    return _url_has_scheme(value, {"redis", "rediss"})


def _strong_secret(value: str | None, *, min_length: int) -> bool:
    if value is None:
        return False
    stripped = value.strip()
    if len(stripped) < min_length:
        return False
    return stripped.lower() not in WEAK_SECRET_VALUES
