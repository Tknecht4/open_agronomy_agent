from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.container_launch_preflight.v1"
DEFAULT_COMPOSE = ROOT / "docker-compose.phase6.launch.yml"
DEFAULT_FRONTEND_DOCKERFILE = ROOT / "frontend/Dockerfile.launch"
DEFAULT_FRONTEND_NGINX = ROOT / "frontend/nginx.launch.conf"
DEFAULT_API_DOCKERFILE = ROOT / "infra/Dockerfile.api"
DEFAULT_DOCKERIGNORE = ROOT / ".dockerignore"

REQUIRED_SERVICES = {"postgres", "redis", "api", "worker", "frontend"}
REQUIRED_API_ENV = {
    "AGRONOMY_AGENT_DB_BACKEND": "postgres",
    "AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH": "false",
    "AGRONOMY_AGENT_RATE_LIMIT_BACKEND": "redis",
    "AGRONOMY_AGENT_RATE_LIMIT_FAIL_OPEN": "false",
    "AGRONOMY_AGENT_JOB_QUEUE_BACKEND": "redis",
    "AGRONOMY_AGENT_JOB_QUEUE_FAIL_OPEN": "false",
    "AGRONOMY_AGENT_OBJECT_STORE_BACKEND": "s3",
    "AGRONOMY_AGENT_ATTACHMENT_SCAN_BACKEND": "http",
    "AGRONOMY_AGENT_STRUCTURED_ACCESS_LOGS": "true",
    "AGRONOMY_AGENT_OTEL_ENABLED": "true",
}
REQUIRED_ENV_PLACEHOLDERS = {
    "AGRONOMY_AGENT_DATABASE_URL",
    "AGRONOMY_AGENT_JWT_ISSUER",
    "AGRONOMY_AGENT_JWT_AUDIENCE",
    "AGRONOMY_AGENT_JWT_JWKS_URL",
    "AGRONOMY_AGENT_OIDC_AUTHORIZATION_ENDPOINT",
    "AGRONOMY_AGENT_OIDC_TOKEN_ENDPOINT",
    "AGRONOMY_AGENT_OIDC_CLIENT_ID",
    "AGRONOMY_AGENT_OIDC_CLIENT_SECRET",
    "AGRONOMY_AGENT_OIDC_REDIRECT_URI",
    "AGRONOMY_AGENT_OIDC_SESSION_SECRET",
    "AGRONOMY_AGENT_REDIS_URL",
    "AGRONOMY_AGENT_OBJECT_STORE_ENDPOINT",
    "AGRONOMY_AGENT_OBJECT_STORE_BUCKET",
    "AGRONOMY_AGENT_OBJECT_STORE_REGION",
    "AGRONOMY_AGENT_OBJECT_STORE_ACCESS_KEY",
    "AGRONOMY_AGENT_OBJECT_STORE_SECRET_KEY",
    "AGRONOMY_AGENT_ATTACHMENT_SCAN_ENDPOINT",
    "AGRONOMY_AGENT_ATTACHMENT_SCAN_API_KEY",
}
REQUIRED_WORKER_ENV_PLACEHOLDERS = {
    "AGRONOMY_AGENT_DATABASE_URL",
    "AGRONOMY_AGENT_REDIS_URL",
    "AGRONOMY_AGENT_OBJECT_STORE_ENDPOINT",
    "AGRONOMY_AGENT_OBJECT_STORE_BUCKET",
    "AGRONOMY_AGENT_OBJECT_STORE_REGION",
    "AGRONOMY_AGENT_OBJECT_STORE_ACCESS_KEY",
    "AGRONOMY_AGENT_OBJECT_STORE_SECRET_KEY",
}
SENSITIVE_ENV_KEY_RE = re.compile(r"(PASSWORD|SECRET|API_KEY|ACCESS_KEY|DATABASE_URL|REDIS_URL|TOKEN)", re.IGNORECASE)
REQUIRED_WORKER_FLAGS = {
    "--run-queued-ingest",
    "--run-queued-evals",
    "--run-queued-exports",
    "--run-queued-embeddings",
    "--run-queued-images",
}
REQUIRED_PROXY_PREFIXES = (
    "api",
    "admin",
    "auth",
    "orgs",
    "workspaces",
    "field-contexts",
    "geo",
    "threads",
    "chat",
    "route",
    "retrieve",
    "tools",
    "attachments",
    "messages",
    "eval-candidates",
    "eval-runs",
    "change-proposals",
    "data-sources",
    "ingest-jobs",
    "corpus-health",
    "quotas",
    "audit-events",
    "exports",
    "export-jobs",
    "image-rag",
)


def validate_phase6_container_launch(
    *,
    compose_path: Path = DEFAULT_COMPOSE,
    frontend_dockerfile: Path = DEFAULT_FRONTEND_DOCKERFILE,
    frontend_nginx: Path = DEFAULT_FRONTEND_NGINX,
    api_dockerfile: Path = DEFAULT_API_DOCKERFILE,
    dockerignore: Path = DEFAULT_DOCKERIGNORE,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    compose = _load_yaml(compose_path, failures)
    services = compose.get("services") if isinstance(compose, dict) else {}
    if not isinstance(services, dict):
        failures.append(_failure("compose", "services", "compose file must define a services mapping"))
        services = {}

    _validate_services(services, failures)
    _validate_api_service(services.get("api") or {}, failures)
    _validate_worker_service(services.get("worker") or {}, failures)
    _validate_frontend_service(services.get("frontend") or {}, failures)
    _validate_dependency_services(services, failures)
    _validate_frontend_dockerfile(frontend_dockerfile, failures)
    _validate_frontend_nginx(frontend_nginx, failures)
    _validate_api_dockerfile(api_dockerfile, failures)
    _validate_dockerignore(dockerignore, failures)

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "compose_path": _display_path(compose_path),
        "frontend_dockerfile": _display_path(frontend_dockerfile),
        "frontend_nginx": _display_path(frontend_nginx),
        "api_dockerfile": _display_path(api_dockerfile),
        "required_service_count": len(REQUIRED_SERVICES),
        "service_count": len(services),
        "required_api_env_placeholder_count": len(REQUIRED_ENV_PLACEHOLDERS),
        "required_worker_env_placeholder_count": len(REQUIRED_WORKER_ENV_PLACEHOLDERS),
        "sensitive_env_inline_secret_check": True,
        "worker_healthcheck_required": True,
        "worker_healthcheck_non_mutating": _worker_healthcheck_non_mutating(services.get("worker") or {}),
        "provider_target_required": True,
        "lighthouse_still_required": True,
        "required_proxy_prefix_count": len(REQUIRED_PROXY_PREFIXES),
        "required_proxy_prefixes": list(REQUIRED_PROXY_PREFIXES),
        "failure_count": len(failures),
        "failures": failures,
    }


def _validate_services(services: dict[str, Any], failures: list[dict[str, str]]) -> None:
    missing = sorted(REQUIRED_SERVICES - set(services))
    for service in missing:
        failures.append(_failure("compose", service, "required launch service is missing"))


def _validate_api_service(service: dict[str, Any], failures: list[dict[str, str]]) -> None:
    build = service.get("build") if isinstance(service, dict) else {}
    env = _env(service)
    healthcheck = service.get("healthcheck") if isinstance(service, dict) else {}

    if not isinstance(build, dict) or build.get("dockerfile") != "infra/Dockerfile.api":
        failures.append(_failure("api", "build", "api must build from infra/Dockerfile.api"))
    for key, expected in REQUIRED_API_ENV.items():
        if _normalize_bool_string(env.get(key)) != expected:
            failures.append(_failure("api", key, f"expected {expected}"))
    for key in sorted(REQUIRED_ENV_PLACEHOLDERS):
        value = str(env.get(key) or "")
        if not _required_placeholder(value):
            failures.append(_failure("api", key, "must be a required provider/env placeholder"))
    _validate_no_inline_sensitive_env("api", env, failures)
    if "/health" not in json.dumps(healthcheck):
        failures.append(_failure("api", "healthcheck", "api healthcheck must probe /health"))


def _validate_worker_service(service: dict[str, Any], failures: list[dict[str, str]]) -> None:
    build = service.get("build") if isinstance(service, dict) else {}
    env = _env(service)
    command = [str(part) for part in service.get("command", [])] if isinstance(service, dict) else []
    healthcheck = service.get("healthcheck") if isinstance(service, dict) else {}

    if not isinstance(build, dict) or build.get("dockerfile") != "infra/Dockerfile.api":
        failures.append(_failure("worker", "build", "worker must reuse infra/Dockerfile.api"))
    missing_flags = sorted(REQUIRED_WORKER_FLAGS - set(command))
    for flag in missing_flags:
        failures.append(_failure("worker", flag, "required queued job worker flag is missing"))
    for key in ["AGRONOMY_AGENT_DB_BACKEND", "AGRONOMY_AGENT_JOB_QUEUE_BACKEND", "AGRONOMY_AGENT_JOB_QUEUE_FAIL_OPEN"]:
        expected = "postgres" if key.endswith("DB_BACKEND") else ("redis" if key.endswith("QUEUE_BACKEND") else "false")
        if _normalize_bool_string(env.get(key)) != expected:
            failures.append(_failure("worker", key, f"expected {expected}"))
    for key in sorted(REQUIRED_WORKER_ENV_PLACEHOLDERS):
        value = str(env.get(key) or "")
        if not _required_placeholder(value):
            failures.append(_failure("worker", key, "must be a required provider/env placeholder"))
    _validate_no_inline_sensitive_env("worker", env, failures)
    _validate_worker_healthcheck(healthcheck, failures)


def _validate_frontend_service(service: dict[str, Any], failures: list[dict[str, str]]) -> None:
    build = service.get("build") if isinstance(service, dict) else {}
    healthcheck = service.get("healthcheck") if isinstance(service, dict) else {}
    depends_on = service.get("depends_on") if isinstance(service, dict) else {}
    env = _env(service)

    if not isinstance(build, dict) or build.get("dockerfile") != "Dockerfile.launch":
        failures.append(_failure("frontend", "build", "frontend must use Dockerfile.launch for production static serving"))
    if env:
        failures.append(_failure("frontend", "environment", "launch frontend should use same-origin proxy instead of build-time API env"))
    if "/healthz" not in json.dumps(healthcheck):
        failures.append(_failure("frontend", "healthcheck", "frontend healthcheck must probe /healthz"))
    api_dep = depends_on.get("api") if isinstance(depends_on, dict) else None
    if not isinstance(api_dep, dict) or api_dep.get("condition") != "service_healthy":
        failures.append(_failure("frontend", "depends_on", "frontend must wait for healthy api service"))


def _validate_dependency_services(services: dict[str, Any], failures: list[dict[str, str]]) -> None:
    postgres = services.get("postgres") or {}
    redis = services.get("redis") or {}
    postgres_env = _env(postgres)
    if not str(postgres.get("image", "")).startswith("pgvector/pgvector:"):
        failures.append(_failure("postgres", "image", "postgres service must use pgvector image"))
    if not _required_placeholder(str(postgres_env.get("POSTGRES_PASSWORD") or "")):
        failures.append(_failure("postgres", "POSTGRES_PASSWORD", "must be a required provider/env placeholder"))
    _validate_no_inline_sensitive_env("postgres", postgres_env, failures)
    if "001_schema.sql" not in json.dumps(postgres.get("volumes", [])):
        failures.append(_failure("postgres", "schema", "postgres must mount the starter schema read-only"))
    if "healthcheck" not in postgres:
        failures.append(_failure("postgres", "healthcheck", "postgres healthcheck is required"))
    if not str(redis.get("image", "")).startswith("redis:"):
        failures.append(_failure("redis", "image", "redis service must use redis image"))
    if "healthcheck" not in redis:
        failures.append(_failure("redis", "healthcheck", "redis healthcheck is required"))


def _validate_worker_healthcheck(healthcheck: object, failures: list[dict[str, str]]) -> None:
    if not isinstance(healthcheck, dict):
        failures.append(_failure("worker", "healthcheck", "worker healthcheck is required"))
        return
    healthcheck_text = json.dumps(healthcheck)
    if "agronomy_agent.server.worker" not in healthcheck_text or "--healthcheck" not in healthcheck_text:
        failures.append(_failure("worker", "healthcheck", "worker healthcheck must use the non-mutating worker --healthcheck command"))
    if "--run-queued-" in healthcheck_text:
        failures.append(_failure("worker", "healthcheck", "worker healthcheck must not consume queued jobs"))


def _worker_healthcheck_non_mutating(service: dict[str, Any]) -> bool:
    healthcheck = service.get("healthcheck") if isinstance(service, dict) else {}
    if not isinstance(healthcheck, dict):
        return False
    healthcheck_text = json.dumps(healthcheck)
    return (
        "agronomy_agent.server.worker" in healthcheck_text
        and "--healthcheck" in healthcheck_text
        and "--run-queued-" not in healthcheck_text
    )


def _validate_frontend_dockerfile(path: Path, failures: list[dict[str, str]]) -> None:
    text = _read(path, failures)
    if not text:
        return
    required = ["FROM node:20-alpine AS build", "RUN npm ci", "RUN npm run build", "FROM nginx:", "COPY nginx.launch.conf", "HEALTHCHECK"]
    for needle in required:
        if needle not in text:
            failures.append(_failure("frontend_dockerfile", needle, "required production build/serve directive is missing"))
    forbidden = ["npm run dev", "vite --host", "vite preview"]
    for needle in forbidden:
        if needle in text:
            failures.append(_failure("frontend_dockerfile", needle, "launch image must not run the dev server"))
    if re.search(r'"npm"\s*,\s*"run"\s*,\s*"dev"', text):
        failures.append(_failure("frontend_dockerfile", "npm run dev", "launch image must not run the dev server"))


def _validate_frontend_nginx(path: Path, failures: list[dict[str, str]]) -> None:
    text = _read(path, failures)
    if not text:
        return
    if "listen 8080" not in text:
        failures.append(_failure("nginx", "listen", "frontend nginx must listen on container port 8080"))
    if "try_files $uri $uri/ /index.html" not in text:
        failures.append(_failure("nginx", "spa_fallback", "SPA fallback must serve index.html"))
    if "proxy_pass http://api:8000" not in text:
        failures.append(_failure("nginx", "api_proxy", "frontend must proxy API calls to the api service"))
    missing_prefixes = [prefix for prefix in REQUIRED_PROXY_PREFIXES if not re.search(rf"\b{re.escape(prefix)}\b", text)]
    for prefix in missing_prefixes:
        failures.append(_failure("nginx", prefix, "required backend route prefix is missing from proxy rule"))


def _validate_api_dockerfile(path: Path, failures: list[dict[str, str]]) -> None:
    text = _read(path, failures)
    if not text:
        return
    if "pip install --no-cache-dir -r requirements.txt" not in text:
        failures.append(_failure("api_dockerfile", "requirements", "api image must install project requirements"))
    if "agronomy_agent.server.app:create_app" not in text:
        failures.append(_failure("api_dockerfile", "server", "api image must launch the FastAPI app factory"))


def _validate_dockerignore(path: Path, failures: list[dict[str, str]]) -> None:
    lines = {line.strip() for line in _read(path, failures).splitlines() if line.strip() and not line.startswith("#")}
    for required in [".env", "frontend/node_modules", "frontend/dist", "outputs", "models", "runs", "data/raw", "data/derived"]:
        if required not in lines:
            failures.append(_failure("dockerignore", required, "heavy or secret-prone path must be excluded from image context"))


def _load_yaml(path: Path, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(_failure("compose", _display_path(path), f"could not parse compose yaml: {exc}"))
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read(path: Path, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(_failure("file", _display_path(path), f"could not read file: {exc}"))
        return ""


def _env(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment", {}) if isinstance(service, dict) else {}
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return dict(item.split("=", 1) for item in raw if isinstance(item, str) and "=" in item)
    return {}


def _required_placeholder(value: str) -> bool:
    return value.startswith("${") and ":?" in value and value.endswith("}")


def _validate_no_inline_sensitive_env(service_name: str, env: dict[str, str], failures: list[dict[str, str]]) -> None:
    for key, value in sorted(env.items()):
        if not SENSITIVE_ENV_KEY_RE.search(key):
            continue
        if _required_placeholder(str(value)):
            continue
        failures.append(_failure(service_name, key, "sensitive env value must be supplied as a required provider/env placeholder"))


def _normalize_bool_string(value: object) -> str:
    return str(value or "").strip().lower()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _failure(surface: str, key: str, reason: str) -> dict[str, str]:
    return {"surface": surface, "key": key, "reason": reason}
