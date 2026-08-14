from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from agronomy_agent.paths import repo_path
from agronomy_agent.agent import load_model_config
from agronomy_agent.agno_runtime.runtime import AgentRuntimeMode, resolve_agent_runtime
from agronomy_agent.knowledge_updates import resolve_active_rag_config
from agronomy_agent.knowledge_update_trust import (
    VerifiedKnowledgeUpdateTrustPolicy,
    load_knowledge_update_trust_policy,
)
from agronomy_agent.runtime_profiles import DEFAULT_MODEL_CONFIG, DEFAULT_RAG_CONFIG


@dataclass(frozen=True)
class ServerSettings:
    db_path: Path
    artifact_root: Path
    model_config_path: str = DEFAULT_MODEL_CONFIG
    default_rag_config: str = DEFAULT_RAG_CONFIG
    prompt_version: str = "phase3_default_v0"
    corpus_audit_id: str | None = None
    redaction_mode_default: str = "snippets_hashed"
    static_dir: Path | None = None
    database_backend: str = "sqlite"
    database_url: str | None = None
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_jwks_json: str | None = None
    jwt_jwks_url: str | None = None
    allow_local_dev_auth: bool = True
    local_pairing_token_sha256: str | None = None
    oidc_authorization_endpoint: str | None = None
    oidc_token_endpoint: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_session_secret: str | None = None
    oidc_logout_endpoint: str | None = None
    oidc_post_logout_redirect_uri: str | None = None
    oidc_scopes: str = "openid email profile"
    rate_limit_requests: int = 600
    rate_limit_window_seconds: int = 60
    rate_limit_backend: str = "memory"
    redis_url: str | None = None
    rate_limit_fail_open: bool = False
    job_queue_backend: str = "local"
    job_queue_name: str = "agronomy:jobs:ingest"
    eval_queue_name: str = "agronomy:jobs:eval"
    export_queue_name: str = "agronomy:jobs:exports"
    embedding_queue_name: str = "agronomy:jobs:embedding"
    image_queue_name: str = "agronomy:jobs:image"
    job_queue_fail_open: bool = False
    structured_access_logs: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "agronomy-agent-api"
    network_mode: str = "online"
    object_store_backend: str = "local"
    object_store_endpoint: str | None = None
    object_store_bucket: str | None = None
    object_store_region: str = "us-east-1"
    object_store_access_key: str | None = None
    object_store_secret_key: str | None = None
    vlm_observation_backend: str = "local"
    vlm_observation_endpoint: str | None = None
    vlm_observation_api_key: str | None = None
    vlm_observation_timeout_seconds: float = 10.0
    attachment_scan_backend: str = "local"
    attachment_scan_endpoint: str | None = None
    attachment_scan_api_key: str | None = None
    attachment_scan_timeout_seconds: float = 10.0
    model_queue_max_wait_ms: float = 1000.0
    model_queue_wait_ms_estimate: float = 0.0
    agent_runtime: AgentRuntimeMode = "agno"
    knowledge_update_root: Path | None = None
    knowledge_update_public_key: Path | None = None
    knowledge_update_trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None
    knowledge_update_allow_unsigned: bool = False
    allow_rag_config_override: bool = False
    allow_model_id_override: bool = False

    @property
    def db_name(self) -> str:
        return self.db_path.name

    @property
    def default_model_id(self) -> str:
        config = load_model_config(self.model_config_path)
        model_id = str(
            config.get("serving_model_id") or config.get("model_id") or ""
        ).strip()
        if not model_id:
            raise ValueError(
                f"model configuration does not define a serving model ID: {self.model_config_path}"
            )
        return model_id

    @property
    def artifact_dir(self) -> Path:
        return self.artifact_root / self.prompt_version


def _coerce_path(value: str) -> Path:
    return repo_path(value)


def build_settings(
    *,
    db_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
    static_dir: str | Path | None = None,
    model_config_path: str | None = None,
    default_rag_config: str | Path | None = None,
    database_backend: str | None = None,
    database_url: str | None = None,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    jwt_jwks_json: str | None = None,
    jwt_jwks_url: str | None = None,
    allow_local_dev_auth: bool | None = None,
    local_pairing_token_sha256: str | None = None,
    oidc_authorization_endpoint: str | None = None,
    oidc_token_endpoint: str | None = None,
    oidc_client_id: str | None = None,
    oidc_client_secret: str | None = None,
    oidc_redirect_uri: str | None = None,
    oidc_session_secret: str | None = None,
    oidc_logout_endpoint: str | None = None,
    oidc_post_logout_redirect_uri: str | None = None,
    oidc_scopes: str | None = None,
    rate_limit_requests: int | None = None,
    rate_limit_window_seconds: int | None = None,
    rate_limit_backend: str | None = None,
    redis_url: str | None = None,
    rate_limit_fail_open: bool | None = None,
    job_queue_backend: str | None = None,
    job_queue_name: str | None = None,
    eval_queue_name: str | None = None,
    export_queue_name: str | None = None,
    embedding_queue_name: str | None = None,
    image_queue_name: str | None = None,
    job_queue_fail_open: bool | None = None,
    structured_access_logs: bool | None = None,
    otel_enabled: bool | None = None,
    otel_service_name: str | None = None,
    network_mode: str | None = None,
    object_store_backend: str | None = None,
    object_store_endpoint: str | None = None,
    object_store_bucket: str | None = None,
    object_store_region: str | None = None,
    object_store_access_key: str | None = None,
    object_store_secret_key: str | None = None,
    vlm_observation_backend: str | None = None,
    vlm_observation_endpoint: str | None = None,
    vlm_observation_api_key: str | None = None,
    vlm_observation_timeout_seconds: float | None = None,
    attachment_scan_backend: str | None = None,
    attachment_scan_endpoint: str | None = None,
    attachment_scan_api_key: str | None = None,
    attachment_scan_timeout_seconds: float | None = None,
    model_queue_max_wait_ms: float | None = None,
    model_queue_wait_ms_estimate: float | None = None,
    agent_runtime: str | None = None,
    knowledge_update_root: str | Path | None = None,
    knowledge_update_public_key: str | Path | None = None,
    knowledge_update_trust_policy: str | Path | None = None,
    knowledge_update_trust_policy_signature: str | Path | None = None,
    knowledge_update_trust_root_public_key: str | Path | None = None,
    knowledge_update_expected_trust_policy_sha256: str | None = None,
    knowledge_update_allow_unsigned: bool | None = None,
    allow_rag_config_override: bool | None = None,
    allow_model_id_override: bool | None = None,
) -> ServerSettings:
    db = _coerce_path(str(db_path or os.getenv("AGRONOMY_AGENT_DB_PATH") or "outputs/cockpit/phase3.sqlite3"))
    artifact = _coerce_path(str(artifact_root or os.getenv("AGRONOMY_AGENT_ARTIFACT_ROOT") or "outputs/cockpit/artifacts"))
    static_value = static_dir if static_dir is not None else os.getenv("AGRONOMY_AGENT_STATIC_DIR")
    static_path = None if static_value is None else _coerce_path(str(static_value))
    db.parent.mkdir(parents=True, exist_ok=True)
    artifact.mkdir(parents=True, exist_ok=True)
    if static_path is not None:
        static_path.mkdir(parents=True, exist_ok=True)
    db_backend = (database_backend or os.getenv("AGRONOMY_AGENT_DB_BACKEND") or "sqlite").strip().lower()
    if db_backend not in {"sqlite", "postgres"}:
        raise ValueError("AGRONOMY_AGENT_DB_BACKEND must be 'sqlite' or 'postgres'")
    db_url = database_url or os.getenv("AGRONOMY_AGENT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if db_backend == "postgres" and not db_url:
        raise ValueError("AGRONOMY_AGENT_DATABASE_URL or DATABASE_URL is required when AGRONOMY_AGENT_DB_BACKEND=postgres")
    limit_value = rate_limit_requests if rate_limit_requests is not None else os.getenv("AGRONOMY_AGENT_RATE_LIMIT_REQUESTS", "600")
    window_value = (
        rate_limit_window_seconds
        if rate_limit_window_seconds is not None
        else os.getenv("AGRONOMY_AGENT_RATE_LIMIT_WINDOW_SECONDS", "60")
    )
    limit = int(limit_value)
    window_seconds = int(window_value)
    if limit <= 0:
        raise ValueError("AGRONOMY_AGENT_RATE_LIMIT_REQUESTS must be > 0")
    if window_seconds <= 0:
        raise ValueError("AGRONOMY_AGENT_RATE_LIMIT_WINDOW_SECONDS must be > 0")
    limiter_backend = (rate_limit_backend or os.getenv("AGRONOMY_AGENT_RATE_LIMIT_BACKEND") or "memory").strip().lower()
    if limiter_backend not in {"memory", "redis"}:
        raise ValueError("AGRONOMY_AGENT_RATE_LIMIT_BACKEND must be 'memory' or 'redis'")
    limiter_redis_url = redis_url or os.getenv("AGRONOMY_AGENT_REDIS_URL") or os.getenv("REDIS_URL")
    if limiter_backend == "redis" and not limiter_redis_url:
        raise ValueError("AGRONOMY_AGENT_REDIS_URL or REDIS_URL is required when AGRONOMY_AGENT_RATE_LIMIT_BACKEND=redis")
    queue_backend = (job_queue_backend or os.getenv("AGRONOMY_AGENT_JOB_QUEUE_BACKEND") or "local").strip().lower()
    if queue_backend not in {"local", "redis"}:
        raise ValueError("AGRONOMY_AGENT_JOB_QUEUE_BACKEND must be 'local' or 'redis'")
    if queue_backend == "redis" and not limiter_redis_url:
        raise ValueError("AGRONOMY_AGENT_REDIS_URL or REDIS_URL is required when AGRONOMY_AGENT_JOB_QUEUE_BACKEND=redis")
    queue_name = (job_queue_name or os.getenv("AGRONOMY_AGENT_JOB_QUEUE_NAME") or "agronomy:jobs:ingest").strip()
    if not queue_name:
        raise ValueError("AGRONOMY_AGENT_JOB_QUEUE_NAME must be non-empty")
    eval_job_queue_name = (eval_queue_name or os.getenv("AGRONOMY_AGENT_EVAL_QUEUE_NAME") or "agronomy:jobs:eval").strip()
    if not eval_job_queue_name:
        raise ValueError("AGRONOMY_AGENT_EVAL_QUEUE_NAME must be non-empty")
    export_job_queue_name = (export_queue_name or os.getenv("AGRONOMY_AGENT_EXPORT_QUEUE_NAME") or "agronomy:jobs:exports").strip()
    if not export_job_queue_name:
        raise ValueError("AGRONOMY_AGENT_EXPORT_QUEUE_NAME must be non-empty")
    embedding_job_queue_name = (embedding_queue_name or os.getenv("AGRONOMY_AGENT_EMBEDDING_QUEUE_NAME") or "agronomy:jobs:embedding").strip()
    if not embedding_job_queue_name:
        raise ValueError("AGRONOMY_AGENT_EMBEDDING_QUEUE_NAME must be non-empty")
    image_job_queue_name = (image_queue_name or os.getenv("AGRONOMY_AGENT_IMAGE_QUEUE_NAME") or "agronomy:jobs:image").strip()
    if not image_job_queue_name:
        raise ValueError("AGRONOMY_AGENT_IMAGE_QUEUE_NAME must be non-empty")
    limiter_fail_open = (
        rate_limit_fail_open
        if rate_limit_fail_open is not None
        else os.getenv("AGRONOMY_AGENT_RATE_LIMIT_FAIL_OPEN", "false").lower() in {"1", "true", "yes"}
    )
    queue_fail_open = (
        job_queue_fail_open
        if job_queue_fail_open is not None
        else os.getenv("AGRONOMY_AGENT_JOB_QUEUE_FAIL_OPEN", "false").lower() in {"1", "true", "yes"}
    )
    access_logs_enabled = (
        structured_access_logs
        if structured_access_logs is not None
        else os.getenv("AGRONOMY_AGENT_STRUCTURED_ACCESS_LOGS", "true").lower() not in {"0", "false", "no"}
    )
    local_dev_auth_enabled = (
        allow_local_dev_auth
        if allow_local_dev_auth is not None
        else os.getenv("AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH", "true").lower() not in {"0", "false", "no"}
    )
    pairing_token_sha256 = str(
        local_pairing_token_sha256
        or os.getenv("AGRONOMY_AGENT_LOCAL_PAIRING_TOKEN_SHA256")
        or ""
    ).strip().lower()
    resolved_session_secret = (
        oidc_session_secret or os.getenv("AGRONOMY_AGENT_OIDC_SESSION_SECRET")
    )
    if pairing_token_sha256:
        try:
            valid_pairing_hash = (
                len(pairing_token_sha256) == 64
                and len(bytes.fromhex(pairing_token_sha256)) == 32
            )
        except ValueError:
            valid_pairing_hash = False
        if not valid_pairing_hash:
            raise ValueError(
                "AGRONOMY_AGENT_LOCAL_PAIRING_TOKEN_SHA256 must be a 64-character SHA-256 hex digest"
            )
        if local_dev_auth_enabled:
            raise ValueError(
                "local pairing requires AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH=false"
            )
        if not resolved_session_secret or len(resolved_session_secret) < 32:
            raise ValueError(
                "local pairing requires AGRONOMY_AGENT_OIDC_SESSION_SECRET with at least 32 characters"
            )
    telemetry_enabled = (
        otel_enabled
        if otel_enabled is not None
        else os.getenv("AGRONOMY_AGENT_OTEL_ENABLED", "false").lower() in {"1", "true", "yes"}
    )
    telemetry_service_name = (otel_service_name or os.getenv("AGRONOMY_AGENT_OTEL_SERVICE_NAME") or "agronomy-agent-api").strip()
    if not telemetry_service_name:
        raise ValueError("AGRONOMY_AGENT_OTEL_SERVICE_NAME must be non-empty")
    resolved_network_mode = (
        network_mode or os.getenv("AGRONOMY_AGENT_NETWORK_MODE") or "online"
    ).strip().lower()
    if resolved_network_mode not in {"online", "offline"}:
        raise ValueError("AGRONOMY_AGENT_NETWORK_MODE must be 'online' or 'offline'")
    storage_backend = (object_store_backend or os.getenv("AGRONOMY_AGENT_OBJECT_STORE_BACKEND") or "local").strip().lower()
    if storage_backend not in {"local", "s3"}:
        raise ValueError("AGRONOMY_AGENT_OBJECT_STORE_BACKEND must be 'local' or 's3'")
    storage_region = (object_store_region or os.getenv("AGRONOMY_AGENT_OBJECT_STORE_REGION") or "us-east-1").strip()
    if not storage_region:
        raise ValueError("AGRONOMY_AGENT_OBJECT_STORE_REGION must be non-empty")
    vlm_backend = (vlm_observation_backend or os.getenv("AGRONOMY_AGENT_VLM_OBSERVATION_BACKEND") or "local").strip().lower()
    if vlm_backend not in {"local", "http"}:
        raise ValueError("AGRONOMY_AGENT_VLM_OBSERVATION_BACKEND must be 'local' or 'http'")
    vlm_timeout_value = (
        vlm_observation_timeout_seconds
        if vlm_observation_timeout_seconds is not None
        else os.getenv("AGRONOMY_AGENT_VLM_OBSERVATION_TIMEOUT_SECONDS", "10")
    )
    vlm_timeout = float(vlm_timeout_value)
    if vlm_timeout <= 0:
        raise ValueError("AGRONOMY_AGENT_VLM_OBSERVATION_TIMEOUT_SECONDS must be > 0")
    scan_backend = (attachment_scan_backend or os.getenv("AGRONOMY_AGENT_ATTACHMENT_SCAN_BACKEND") or "local").strip().lower()
    if scan_backend not in {"local", "http"}:
        raise ValueError("AGRONOMY_AGENT_ATTACHMENT_SCAN_BACKEND must be 'local' or 'http'")
    scan_timeout_value = (
        attachment_scan_timeout_seconds
        if attachment_scan_timeout_seconds is not None
        else os.getenv("AGRONOMY_AGENT_ATTACHMENT_SCAN_TIMEOUT_SECONDS", "10")
    )
    scan_timeout = float(scan_timeout_value)
    if scan_timeout <= 0:
        raise ValueError("AGRONOMY_AGENT_ATTACHMENT_SCAN_TIMEOUT_SECONDS must be > 0")
    model_queue_max_wait_value = (
        model_queue_max_wait_ms
        if model_queue_max_wait_ms is not None
        else os.getenv("AGRONOMY_AGENT_MODEL_QUEUE_MAX_WAIT_MS", "1000")
    )
    model_queue_max_wait = float(model_queue_max_wait_value)
    if model_queue_max_wait < 0:
        raise ValueError("AGRONOMY_AGENT_MODEL_QUEUE_MAX_WAIT_MS must be >= 0")
    model_queue_wait_value = (
        model_queue_wait_ms_estimate
        if model_queue_wait_ms_estimate is not None
        else os.getenv("AGRONOMY_AGENT_MODEL_QUEUE_WAIT_MS_ESTIMATE", "0")
    )
    model_queue_wait = float(model_queue_wait_value)
    if model_queue_wait < 0:
        raise ValueError("AGRONOMY_AGENT_MODEL_QUEUE_WAIT_MS_ESTIMATE must be >= 0")
    runtime_mode = resolve_agent_runtime(explicit=agent_runtime)
    resolved_model_config_path = (
        model_config_path or os.getenv("AGRONOMY_AGENT_MODEL_CONFIG") or DEFAULT_MODEL_CONFIG
    ).strip()
    if not resolved_model_config_path:
        raise ValueError("AGRONOMY_AGENT_MODEL_CONFIG must be non-empty")
    fallback_rag_config = str(
        default_rag_config
        or os.getenv("AGRONOMY_AGENT_RAG_CONFIG")
        or DEFAULT_RAG_CONFIG
    ).strip()
    if not fallback_rag_config:
        raise ValueError("AGRONOMY_AGENT_RAG_CONFIG must be non-empty")
    update_root_value = (
        knowledge_update_root
        if knowledge_update_root is not None
        else os.getenv("AGRONOMY_AGENT_KNOWLEDGE_UPDATE_ROOT")
    )
    update_key_value = (
        knowledge_update_public_key
        if knowledge_update_public_key is not None
        else os.getenv("AGRONOMY_AGENT_KNOWLEDGE_UPDATE_PUBLIC_KEY")
    )
    trust_policy_value = (
        knowledge_update_trust_policy
        if knowledge_update_trust_policy is not None
        else os.getenv("AGRONOMY_AGENT_KNOWLEDGE_UPDATE_TRUST_POLICY")
    )
    trust_policy_signature_value = (
        knowledge_update_trust_policy_signature
        if knowledge_update_trust_policy_signature is not None
        else os.getenv("AGRONOMY_AGENT_KNOWLEDGE_UPDATE_TRUST_POLICY_SIGNATURE")
    )
    trust_root_key_value = (
        knowledge_update_trust_root_public_key
        if knowledge_update_trust_root_public_key is not None
        else os.getenv("AGRONOMY_AGENT_KNOWLEDGE_UPDATE_TRUST_ROOT_PUBLIC_KEY")
    )
    expected_trust_policy_sha256 = (
        knowledge_update_expected_trust_policy_sha256
        if knowledge_update_expected_trust_policy_sha256 is not None
        else os.getenv(
            "AGRONOMY_AGENT_KNOWLEDGE_UPDATE_EXPECTED_TRUST_POLICY_SHA256"
        )
    )
    allow_unsigned_update = (
        knowledge_update_allow_unsigned
        if knowledge_update_allow_unsigned is not None
        else os.getenv("AGRONOMY_AGENT_KNOWLEDGE_UPDATE_ALLOW_UNSIGNED", "false").lower()
        in {"1", "true", "yes"}
    )
    rag_config_override_allowed = (
        allow_rag_config_override
        if allow_rag_config_override is not None
        else os.getenv("AGRONOMY_AGENT_ALLOW_RAG_CONFIG_OVERRIDE", "false").lower()
        in {"1", "true", "yes"}
    )
    model_id_override_allowed = (
        allow_model_id_override
        if allow_model_id_override is not None
        else os.getenv("AGRONOMY_AGENT_ALLOW_MODEL_ID_OVERRIDE", "false").lower()
        in {"1", "true", "yes"}
    )
    update_root_path = _coerce_path(str(update_root_value)) if update_root_value else None
    update_key_path = _coerce_path(str(update_key_value)) if update_key_value else None
    trust_values = (
        trust_policy_value,
        trust_policy_signature_value,
        trust_root_key_value,
        expected_trust_policy_sha256,
    )
    if any(trust_values) and not all(trust_values):
        raise ValueError(
            "knowledge update trust policy, signature, root public key, and expected "
            "policy SHA-256 must be configured together"
        )
    if update_key_path is not None and all(trust_values):
        raise ValueError(
            "legacy knowledge update public key cannot be combined with threshold trust-policy mode"
        )
    if allow_unsigned_update and all(trust_values):
        raise ValueError(
            "unsigned knowledge updates cannot be combined with threshold trust-policy mode"
        )
    verified_trust_policy = (
        load_knowledge_update_trust_policy(
            policy_path=_coerce_path(str(trust_policy_value)),
            signature_path=_coerce_path(str(trust_policy_signature_value)),
            root_public_key_path=_coerce_path(str(trust_root_key_value)),
            expected_policy_sha256=str(expected_trust_policy_sha256),
        )
        if all(trust_values)
        else None
    )
    if (
        update_root_path is not None
        and update_key_path is None
        and verified_trust_policy is None
        and not allow_unsigned_update
    ):
        raise ValueError(
            "a legacy public key or verified threshold trust policy is required when "
            "a knowledge update root is configured"
        )
    resolved_rag_config = fallback_rag_config
    if update_root_path is not None:
        resolved_rag_config = str(
            resolve_active_rag_config(
                update_root=update_root_path,
                fallback=fallback_rag_config,
                public_key=update_key_path,
                trust_policy=verified_trust_policy,
                allow_unsigned=allow_unsigned_update,
            )
        )
    return ServerSettings(
        db_path=db,
        artifact_root=artifact,
        model_config_path=resolved_model_config_path,
        default_rag_config=resolved_rag_config,
        static_dir=static_path,
        database_backend=db_backend,
        database_url=db_url,
        jwt_secret=jwt_secret or os.getenv("AGRONOMY_AGENT_JWT_SECRET"),
        jwt_issuer=jwt_issuer or os.getenv("AGRONOMY_AGENT_JWT_ISSUER"),
        jwt_audience=jwt_audience or os.getenv("AGRONOMY_AGENT_JWT_AUDIENCE"),
        jwt_jwks_json=jwt_jwks_json or os.getenv("AGRONOMY_AGENT_JWT_JWKS_JSON"),
        jwt_jwks_url=jwt_jwks_url or os.getenv("AGRONOMY_AGENT_JWT_JWKS_URL"),
        allow_local_dev_auth=local_dev_auth_enabled,
        local_pairing_token_sha256=pairing_token_sha256 or None,
        oidc_authorization_endpoint=oidc_authorization_endpoint or os.getenv("AGRONOMY_AGENT_OIDC_AUTHORIZATION_ENDPOINT"),
        oidc_token_endpoint=oidc_token_endpoint or os.getenv("AGRONOMY_AGENT_OIDC_TOKEN_ENDPOINT"),
        oidc_client_id=oidc_client_id or os.getenv("AGRONOMY_AGENT_OIDC_CLIENT_ID"),
        oidc_client_secret=oidc_client_secret or os.getenv("AGRONOMY_AGENT_OIDC_CLIENT_SECRET"),
        oidc_redirect_uri=oidc_redirect_uri or os.getenv("AGRONOMY_AGENT_OIDC_REDIRECT_URI"),
        oidc_session_secret=resolved_session_secret,
        oidc_logout_endpoint=oidc_logout_endpoint or os.getenv("AGRONOMY_AGENT_OIDC_LOGOUT_ENDPOINT"),
        oidc_post_logout_redirect_uri=oidc_post_logout_redirect_uri or os.getenv("AGRONOMY_AGENT_OIDC_POST_LOGOUT_REDIRECT_URI"),
        oidc_scopes=(oidc_scopes or os.getenv("AGRONOMY_AGENT_OIDC_SCOPES") or "openid email profile").strip(),
        rate_limit_requests=limit,
        rate_limit_window_seconds=window_seconds,
        rate_limit_backend=limiter_backend,
        redis_url=limiter_redis_url,
        rate_limit_fail_open=limiter_fail_open,
        job_queue_backend=queue_backend,
        job_queue_name=queue_name,
        eval_queue_name=eval_job_queue_name,
        export_queue_name=export_job_queue_name,
        embedding_queue_name=embedding_job_queue_name,
        image_queue_name=image_job_queue_name,
        job_queue_fail_open=queue_fail_open,
        structured_access_logs=access_logs_enabled,
        otel_enabled=telemetry_enabled,
        otel_service_name=telemetry_service_name,
        network_mode=resolved_network_mode,
        object_store_backend=storage_backend,
        object_store_endpoint=object_store_endpoint or os.getenv("AGRONOMY_AGENT_OBJECT_STORE_ENDPOINT"),
        object_store_bucket=object_store_bucket or os.getenv("AGRONOMY_AGENT_OBJECT_STORE_BUCKET"),
        object_store_region=storage_region,
        object_store_access_key=object_store_access_key or os.getenv("AGRONOMY_AGENT_OBJECT_STORE_ACCESS_KEY"),
        object_store_secret_key=object_store_secret_key or os.getenv("AGRONOMY_AGENT_OBJECT_STORE_SECRET_KEY"),
        vlm_observation_backend=vlm_backend,
        vlm_observation_endpoint=vlm_observation_endpoint or os.getenv("AGRONOMY_AGENT_VLM_OBSERVATION_ENDPOINT"),
        vlm_observation_api_key=vlm_observation_api_key or os.getenv("AGRONOMY_AGENT_VLM_OBSERVATION_API_KEY"),
        vlm_observation_timeout_seconds=vlm_timeout,
        attachment_scan_backend=scan_backend,
        attachment_scan_endpoint=attachment_scan_endpoint or os.getenv("AGRONOMY_AGENT_ATTACHMENT_SCAN_ENDPOINT"),
        attachment_scan_api_key=attachment_scan_api_key or os.getenv("AGRONOMY_AGENT_ATTACHMENT_SCAN_API_KEY"),
        attachment_scan_timeout_seconds=scan_timeout,
        model_queue_max_wait_ms=model_queue_max_wait,
        model_queue_wait_ms_estimate=model_queue_wait,
        agent_runtime=runtime_mode,
        knowledge_update_root=update_root_path,
        knowledge_update_public_key=update_key_path,
        knowledge_update_trust_policy=verified_trust_policy,
        knowledge_update_allow_unsigned=allow_unsigned_update,
        allow_rag_config_override=rag_config_override_allowed,
        allow_model_id_override=model_id_override_allowed,
    )


def make_corpus_audit_id(paths: list[str]) -> str:
    payload = "|".join(sorted(paths))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"ca_{digest}"
