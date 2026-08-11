from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from agronomy_agent.paths import repo_path


PACKET_DIR = repo_path("plans/agronomy_agent_phase4_hosted_platform_packet_final")
DEFAULT_SCHEMA_PATH = PACKET_DIR / "phase4_postgres_schema_starter.sql"
DEFAULT_CHECKSUMS_PATH = PACKET_DIR / "checksums.sha256"
PHASE5_PACKET_DIR = repo_path("plans/agronomy_agent_phase5_optimization_hardening_packet")
DEFAULT_PHASE5_OBSERVABILITY_SCHEMA_PATH = repo_path("src/agronomy_agent/server/storage/phase5_observability_tables.sql")
PACKET_PHASE5_OBSERVABILITY_SCHEMA_PATH = PHASE5_PACKET_DIR / "phase5_observability_tables.sql"
REQUIRED_OBJECT_CHECKS = {
    "users": "SELECT to_regclass('public.users')",
    "auth_sessions": "SELECT to_regclass('public.auth_sessions')",
    "password_credentials": "SELECT to_regclass('public.password_credentials')",
    "auth_tokens": "SELECT to_regclass('public.auth_tokens')",
    "organizations": "SELECT to_regclass('public.organizations')",
    "workspaces": "SELECT to_regclass('public.workspaces')",
    "field_events": "SELECT to_regclass('public.field_events')",
    "threads": "SELECT to_regclass('public.threads')",
    "messages": "SELECT to_regclass('public.messages')",
    "trace_events": "SELECT to_regclass('public.trace_events')",
    "retrieval_events": "SELECT to_regclass('public.retrieval_events')",
    "tool_events": "SELECT to_regclass('public.tool_events')",
    "feedback_events": "SELECT to_regclass('public.feedback_events')",
    "reflection_candidates": "SELECT to_regclass('public.reflection_candidates')",
    "attachments": "SELECT to_regclass('public.attachments')",
    "artifacts": "SELECT to_regclass('public.artifacts')",
    "data_sources": "SELECT to_regclass('public.data_sources')",
    "knowledge_sources": "SELECT to_regclass('public.knowledge_sources')",
    "knowledge_source_versions": "SELECT to_regclass('public.knowledge_source_versions')",
    "knowledge_chunk_reviews": "SELECT to_regclass('public.knowledge_chunk_reviews')",
    "knowledge_ingest_jobs": "SELECT to_regclass('public.knowledge_ingest_jobs')",
    "source_documents": "SELECT to_regclass('public.source_documents')",
    "document_chunks": "SELECT to_regclass('public.document_chunks')",
    "embeddings": "SELECT to_regclass('public.embeddings')",
    "ingest_jobs": "SELECT to_regclass('public.ingest_jobs')",
    "exports": "SELECT to_regclass('public.exports')",
    "export_jobs": "SELECT to_regclass('public.export_jobs')",
    "embedding_jobs": "SELECT to_regclass('public.embedding_jobs')",
    "image_jobs": "SELECT to_regclass('public.image_jobs')",
    "eval_candidates": "SELECT to_regclass('public.eval_candidates')",
    "eval_runs": "SELECT to_regclass('public.eval_runs')",
    "change_proposals": "SELECT to_regclass('public.change_proposals')",
    "audit_events": "SELECT to_regclass('public.audit_events')",
    "corpus_audits": "SELECT to_regclass('public.corpus_audits')",
    "agent_trace_spans": "SELECT to_regclass('public.agent_trace_spans')",
    "agent_turn_metrics": "SELECT to_regclass('public.agent_turn_metrics')",
    "prompt_leak_events": "SELECT to_regclass('public.prompt_leak_events')",
    "optimization_candidates": "SELECT to_regclass('public.optimization_candidates')",
    "phase5_training_candidates": "SELECT to_regclass('public.phase5_training_candidates')",
    "phase5_adapter_registry": "SELECT to_regclass('public.phase5_adapter_registry')",
    "phase5_model_registry": "SELECT to_regclass('public.phase5_model_registry')",
    "vector_extension": "SELECT 1 FROM pg_extension WHERE extname = 'vector'",
    "rls_helper": "SELECT to_regproc('public.app_current_user_id')",
}
REQUIRED_RLS_TABLES = [
    "organizations",
    "memberships",
    "workspaces",
    "field_contexts",
    "field_events",
    "threads",
    "messages",
    "trace_events",
    "retrieval_events",
    "tool_events",
    "feedback_events",
    "reflection_candidates",
    "attachments",
    "artifacts",
    "data_sources",
    "knowledge_sources",
    "knowledge_source_versions",
    "knowledge_chunk_reviews",
    "knowledge_ingest_jobs",
    "source_documents",
    "document_chunks",
    "embeddings",
    "ingest_jobs",
    "exports",
    "export_jobs",
    "embedding_jobs",
    "image_jobs",
    "eval_candidates",
    "eval_runs",
    "change_proposals",
    "audit_events",
    "corpus_audits",
]


def schema_digest(schema_path: Path = DEFAULT_SCHEMA_PATH) -> str:
    return hashlib.sha256(schema_path.read_bytes()).hexdigest()


def expected_schema_digest(checksums_path: Path = DEFAULT_CHECKSUMS_PATH) -> str:
    expected = {
        line.split(maxsplit=1)[1]: line.split(maxsplit=1)[0]
        for line in checksums_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    try:
        return expected[DEFAULT_SCHEMA_PATH.name]
    except KeyError as exc:
        raise ValueError(f"checksum entry missing for {DEFAULT_SCHEMA_PATH.name}") from exc


def assert_schema_checksum(
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    checksums_path: Path = DEFAULT_CHECKSUMS_PATH,
) -> str:
    digest = schema_digest(schema_path)
    expected = expected_schema_digest(checksums_path)
    if digest != expected:
        raise ValueError(f"Postgres schema checksum mismatch: expected {expected}, got {digest}")
    return digest


def psycopg_connect() -> Callable[..., Any]:
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("psycopg is required to apply the Postgres schema; install psycopg[binary]") from exc
    return psycopg.connect


def apply_postgres_schema(
    database_url: str,
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    checksums_path: Path = DEFAULT_CHECKSUMS_PATH,
    connect: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if not database_url.strip():
        raise ValueError("database_url is required")
    digest = assert_schema_checksum(schema_path=schema_path, checksums_path=checksums_path)
    schema_sql = schema_path.read_text(encoding="utf-8")
    observability_schema_path = (
        DEFAULT_PHASE5_OBSERVABILITY_SCHEMA_PATH
        if DEFAULT_PHASE5_OBSERVABILITY_SCHEMA_PATH.exists()
        else PACKET_PHASE5_OBSERVABILITY_SCHEMA_PATH
    )
    observability_sql = observability_schema_path.read_text(encoding="utf-8") if observability_schema_path.exists() else ""
    connector = connect or psycopg_connect()
    with connector(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema_sql)
            if observability_sql:
                cursor.execute(observability_sql)
            verified = verify_postgres_schema(cursor)
    return {
        "status": "applied",
        "schema_path": str(schema_path),
        "schema_sha256": digest,
        "observability_schema_path": str(observability_schema_path) if observability_sql else None,
        "observability_schema_sha256": hashlib.sha256(observability_sql.encode("utf-8")).hexdigest() if observability_sql else None,
        "verified_objects": verified,
    }


def verify_postgres_schema(cursor: Any) -> list[str]:
    missing: list[str] = []
    verified: list[str] = []
    for object_name, query in REQUIRED_OBJECT_CHECKS.items():
        cursor.execute(query)
        row = cursor.fetchone()
        if not row or row[0] is None:
            missing.append(object_name)
        else:
            verified.append(object_name)
    if missing:
        raise RuntimeError(f"Postgres schema verification failed; missing: {', '.join(missing)}")
    return verified


class PostgresPreflightError(RuntimeError):
    pass


def preflight_postgres_database(
    database_url: str,
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    checksums_path: Path = DEFAULT_CHECKSUMS_PATH,
    connect: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if not database_url.strip():
        raise PostgresPreflightError("Postgres preflight failed: database_url is required")
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise PostgresPreflightError("Postgres preflight failed: database_url must use postgresql:// or postgres://")

    try:
        digest = assert_schema_checksum(schema_path=schema_path, checksums_path=checksums_path)
        connector = connect or psycopg_connect()
        with connector(database_url) as connection:
            with connection.cursor() as cursor:
                verified_objects = verify_postgres_schema(cursor)
                rls_tables = verify_postgres_rls(cursor)
                vector_probe = _probe_pgvector(cursor)
    except PostgresPreflightError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PostgresPreflightError(f"Postgres preflight failed: {_sanitize_database_error(exc, database_url)}") from exc

    return {
        "status": "ok",
        "schema_sha256": digest,
        "verified_object_count": len(verified_objects),
        "verified_objects": verified_objects,
        "rls_table_count": len(rls_tables),
        "rls_tables": rls_tables,
        "vector_probe": vector_probe,
    }


def verify_postgres_rls(cursor: Any) -> list[str]:
    missing: list[str] = []
    verified: list[str] = []
    for table in REQUIRED_RLS_TABLES:
        cursor.execute(
            """
            SELECT c.relrowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s
            """,
            (table,),
        )
        row = cursor.fetchone()
        if not row or row[0] is not True:
            missing.append(table)
        else:
            verified.append(table)
    if missing:
        raise PostgresPreflightError(f"Postgres preflight failed: RLS is not enabled for {', '.join(missing)}")
    return verified


def _probe_pgvector(cursor: Any) -> dict[str, Any]:
    probe_table = "agronomy_preflight_vector_probe"
    try:
        cursor.execute(
            f"""
            CREATE TEMP TABLE {probe_table} (
              id text PRIMARY KEY,
              embedding vector(3) NOT NULL
            ) ON COMMIT DROP
            """,
        )
        cursor.execute(
            f"""
            INSERT INTO {probe_table}(id, embedding)
            VALUES ('probe', '[0.1,0.2,0.3]'::vector)
            """,
        )
        cursor.execute(
            f"""
            SELECT id, embedding <=> '[0.1,0.2,0.3]'::vector AS distance
            FROM {probe_table}
            WHERE id = 'probe'
            """,
        )
        row = cursor.fetchone()
        if not row or row[0] != "probe" or float(row[1]) > 1e-9:
            raise PostgresPreflightError("Postgres preflight failed: pgvector probe readback mismatch")
        return {"temp_table": probe_table, "write_read_checked": True, "distance": float(row[1])}
    finally:
        cursor.execute(f"DROP TABLE IF EXISTS {probe_table}")


def _sanitize_database_error(exc: Exception, database_url: str) -> str:
    message = str(exc)
    if database_url:
        message = message.replace(database_url, _redacted_database_url(database_url))
    parsed = urlparse(database_url)
    if parsed.password:
        message = message.replace(parsed.password, "<redacted>")
    return message


def _redacted_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.netloc:
        return "postgresql://<redacted>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    if parsed.username:
        host = f"{parsed.username}:<redacted>@{host}"
    return urlunparse((parsed.scheme or "postgresql", host, parsed.path, "", "", ""))
