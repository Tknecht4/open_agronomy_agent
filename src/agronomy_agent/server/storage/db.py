from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from agronomy_agent.answer_receipts import (
    ANSWER_RECEIPT_METADATA_KEY,
    build_answer_integrity_receipt,
    verify_answer_integrity_receipt,
)
from agronomy_agent.field_events import (
    FIELD_EVENT_TYPES,
    field_event_integrity_sha256,
    field_event_sync_export,
    validate_field_event_fast_forward,
    verify_field_event_chain,
)
from agronomy_agent.field_measurements import validate_field_event_payload
from agronomy_agent.server.services.field_context_quality import evaluate_field_context_quality
from agronomy_agent.server.services.privacy_boundary import minimized_export_trace_payload
from agronomy_agent.server.storage.backup import assert_no_pending_restore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


TEXT_EMBEDDING_DIMENSIONS = 64


def _text_terms(value: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9]+", value.lower())


def _local_text_embedding(value: str, *, dimensions: int = TEXT_EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for term in _text_terms(value):
        bucket = int(hashlib.sha256(term.encode("utf-8")).hexdigest()[:8], 16) % dimensions
        vector[bucket] += 1.0
    norm = sum(component * component for component in vector) ** 0.5
    if not norm:
        return vector
    return [round(component / norm, 8) for component in vector]


class TraceStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        assert_no_pending_restore(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._field_event_lock = threading.RLock()
        self._init_schema()
        self.db_path.chmod(0o600)

    @contextlib.contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        cursor = self._conn.cursor()
        try:
            yield cursor
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    user_pseudonym TEXT,
                    tags TEXT NOT NULL,
                    context TEXT NOT NULL,
                    consent TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_turn_id TEXT,
                    user_message TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    answer_status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    system_state TEXT NOT NULL,
                    trace TEXT NOT NULL,
                    objectives TEXT NOT NULL,
                    prompt_messages TEXT,
                    metadata TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS turns_core_content_no_update
                BEFORE UPDATE OF
                    user_message, answer, created_at, system_state, trace,
                    objectives, prompt_messages, metadata
                ON turns
                BEGIN
                    SELECT RAISE(ABORT, 'answer turn content is immutable');
                END
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS turn_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    event_name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieved_docs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_invocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reflections (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS data_sources (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    path TEXT,
                    url TEXT,
                    owner TEXT,
                    license_status TEXT DEFAULT 'unknown',
                    training_eligible INTEGER DEFAULT 0,
                    refresh_policy TEXT DEFAULT 'manual',
                    checksum TEXT,
                    inspection TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    artifact_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS exports (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    redaction_mode TEXT NOT NULL,
                    manifest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_audits (
                    id TEXT PRIMARY KEY,
                    config_path TEXT NOT NULL,
                    corpus_hash TEXT NOT NULL,
                    corpus_count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    auth_provider_subject TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    role_label TEXT,
                    region_hint TEXT,
                    units_preference TEXT NOT NULL DEFAULT 'mixed',
                    privacy_mode TEXT NOT NULL DEFAULT 'standard',
                    training_consent_default TEXT NOT NULL DEFAULT 'no',
                    trace_storage_enabled INTEGER NOT NULL DEFAULT 1,
                    feedback_use_allowed INTEGER NOT NULL DEFAULT 0,
                    training_candidate_allowed INTEGER NOT NULL DEFAULT 0,
                    public_anonymized_examples_allowed INTEGER NOT NULL DEFAULT 0,
                    product_updates_allowed INTEGER NOT NULL DEFAULT 0,
                    retention_preference TEXT NOT NULL DEFAULT 'default',
                    consent_updated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase6_auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    auth_subject TEXT NOT NULL,
                    email TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT,
                    user_agent_hash TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase6_password_credentials (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase6_auth_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_organizations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'demo',
                    created_by_user_id TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_memberships (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'adviser',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    UNIQUE(organization_id, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_workspaces (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    settings TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_field_contexts (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    region_text TEXT NOT NULL,
                    country TEXT,
                    province_state TEXT,
                    county_rm TEXT,
                    crop_current TEXT,
                    crop_year INTEGER,
                    soil_series_or_texture TEXT,
                    drainage_class TEXT,
                    irrigation_status TEXT,
                    soil_test_summary TEXT,
                    crop_rotation_notes TEXT,
                    management_notes TEXT,
                    known_constraints TEXT NOT NULL DEFAULT '[]',
                    sensitivity TEXT NOT NULL DEFAULT 'medium',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_field_events (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    field_context_id TEXT NOT NULL,
                    recorded_by_user_id TEXT,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    provenance TEXT NOT NULL DEFAULT '{}',
                    corrects_event_id TEXT,
                    previous_event_sha256 TEXT,
                    integrity_sha256 TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(field_context_id) REFERENCES phase4_field_contexts(id),
                    FOREIGN KEY(corrects_event_id) REFERENCES phase4_field_events(id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_phase4_field_events_field_time
                ON phase4_field_events(field_context_id, recorded_at, id)
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS phase4_field_events_no_update
                BEFORE UPDATE ON phase4_field_events
                BEGIN
                    SELECT RAISE(ABORT, 'field events are append-only');
                END
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS phase4_field_events_no_delete
                BEFORE DELETE ON phase4_field_events
                BEGIN
                    SELECT RAISE(ABORT, 'field events are append-only');
                END
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_threads (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    field_context_id TEXT,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'agronomic_rag',
                    task_family TEXT,
                    risk_level TEXT,
                    model_profile_id TEXT,
                    rag_config_id TEXT,
                    trace_capture_level TEXT NOT NULL DEFAULT 'operational',
                    training_eligible INTEGER NOT NULL DEFAULT 0,
                    redaction_status TEXT NOT NULL DEFAULT 'not_required',
                    visibility TEXT NOT NULL DEFAULT 'workspace',
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_messages (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT,
                    sequence_no INTEGER NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(thread_id, sequence_no)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_trace_events (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    message_id TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    prompt_hash TEXT,
                    output_hash TEXT,
                    source_hash TEXT,
                    elapsed_ms INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_feedback_events (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    message_id TEXT,
                    created_by_user_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    failure_tags TEXT NOT NULL DEFAULT '[]',
                    human_correction TEXT,
                    ideal_answer TEXT,
                    training_consent INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_reflection_candidates (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT,
                    thread_id TEXT,
                    target_component TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    candidate_rule TEXT,
                    evidence TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    created_by_user_id TEXT NOT NULL,
                    reviewed_by_user_id TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_data_sources (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    publisher TEXT,
                    canonical_url TEXT,
                    license_state TEXT NOT NULL DEFAULT 'unknown',
                    rag_eligible INTEGER NOT NULL DEFAULT 0,
                    sft_eligible INTEGER NOT NULL DEFAULT 0,
                    source_kind TEXT NOT NULL,
                    crops TEXT NOT NULL DEFAULT '[]',
                    regions TEXT NOT NULL DEFAULT '[]',
                    buckets TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    UNIQUE(organization_id, workspace_id, source_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_attachments (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT,
                    message_id TEXT,
                    created_by_user_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    modality TEXT NOT NULL DEFAULT 'text',
                    sensitivity TEXT NOT NULL DEFAULT 'medium',
                    parse_status TEXT NOT NULL DEFAULT 'pending',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_document_chunks (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    data_source_id TEXT,
                    attachment_id TEXT,
                    source_doc_id TEXT,
                    chunk_index INTEGER NOT NULL,
                    title TEXT,
                    text_content TEXT NOT NULL,
                    source_url TEXT,
                    license_state TEXT NOT NULL DEFAULT 'user_workspace_private',
                    training_eligible INTEGER NOT NULL DEFAULT 0,
                    visibility TEXT NOT NULL DEFAULT 'private',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_embeddings (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    chunk_id TEXT,
                    attachment_id TEXT,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    encoder_name TEXT NOT NULL,
                    encoder_version TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector TEXT NOT NULL DEFAULT '[]',
                    license_state TEXT NOT NULL DEFAULT 'user_workspace_private',
                    training_eligible INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_ingest_jobs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    data_source_id TEXT,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    queue_name TEXT NOT NULL DEFAULT 'ingest',
                    error_message TEXT,
                    result TEXT NOT NULL DEFAULT '{}',
                    created_by_user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_exports (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT,
                    created_by_user_id TEXT NOT NULL,
                    export_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    redaction_status TEXT NOT NULL DEFAULT 'not_required',
                    sha256 TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_export_jobs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    export_type TEXT NOT NULL,
                    redaction_status TEXT NOT NULL DEFAULT 'not_required',
                    status TEXT NOT NULL DEFAULT 'queued',
                    queue_name TEXT NOT NULL DEFAULT 'exports',
                    export_id TEXT,
                    error_message TEXT,
                    result TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_embedding_jobs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    job_type TEXT NOT NULL DEFAULT 'attachment_embedding_reindex',
                    status TEXT NOT NULL DEFAULT 'queued',
                    queue_name TEXT NOT NULL DEFAULT 'embedding',
                    error_message TEXT,
                    result TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_image_jobs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT,
                    created_by_user_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    crop TEXT,
                    region TEXT,
                    attachment_ids TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'queued',
                    queue_name TEXT NOT NULL DEFAULT 'image',
                    error_message TEXT,
                    result TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_eval_candidates (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    message_id TEXT,
                    candidate_type TEXT NOT NULL DEFAULT 'eval_row',
                    target_component TEXT NOT NULL DEFAULT 'eval',
                    payload TEXT NOT NULL DEFAULT '{}',
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    created_by_user_id TEXT NOT NULL,
                    reviewed_by_user_id TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_eval_runs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    candidate_ids TEXT NOT NULL DEFAULT '[]',
                    metrics TEXT NOT NULL DEFAULT '{}',
                    gates TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_change_proposals (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    target_component TEXT NOT NULL,
                    proposal_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    rationale TEXT,
                    linked_reflection_id TEXT,
                    linked_eval_run_id TEXT,
                    review_status TEXT NOT NULL DEFAULT 'candidate',
                    gates TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    reviewed_by_user_id TEXT,
                    reviewed_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase4_audit_events (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT,
                    workspace_id TEXT,
                    actor_user_id TEXT,
                    event_type TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_trace_spans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    thread_id TEXT,
                    turn_id TEXT,
                    span_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    stage TEXT NOT NULL,
                    start_ns INTEGER NOT NULL,
                    end_ns INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    status TEXT NOT NULL,
                    error_type TEXT,
                    error_message_redacted TEXT,
                    input_size INTEGER,
                    output_size INTEGER,
                    token_estimate_in INTEGER,
                    token_estimate_out INTEGER,
                    cache_status TEXT,
                    component_version TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_turn_metrics (
                    trace_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    user_id TEXT,
                    workspace_id TEXT,
                    route_question_type TEXT,
                    risk_level TEXT,
                    namespaces TEXT NOT NULL DEFAULT '[]',
                    required_tools TEXT NOT NULL DEFAULT '[]',
                    rag_config_version TEXT,
                    corpus_bundle_version TEXT,
                    prompt_template_version TEXT,
                    context_packer_version TEXT,
                    model_id TEXT NOT NULL,
                    quantization TEXT,
                    max_tokens INTEGER NOT NULL DEFAULT 0,
                    temperature REAL NOT NULL DEFAULT 0,
                    top_p REAL NOT NULL DEFAULT 0.9,
                    top_k INTEGER NOT NULL DEFAULT 0,
                    total_latency_ms REAL NOT NULL,
                    time_to_first_token_ms REAL,
                    decode_tokens_per_sec REAL,
                    prompt_tokens_est INTEGER,
                    completion_tokens_est INTEGER,
                    context_tokens_est INTEGER,
                    retrieval_doc_count INTEGER NOT NULL DEFAULT 0,
                    top_doc_score REAL,
                    source_diversity INTEGER NOT NULL DEFAULT 0,
                    required_support_rate REAL,
                    tool_notes_count INTEGER NOT NULL DEFAULT 0,
                    tool_precision_proxy REAL,
                    tool_recall_proxy REAL,
                    answer_word_count INTEGER NOT NULL DEFAULT 0,
                    leak_check_passed INTEGER NOT NULL DEFAULT 0,
                    risk_banner_present INTEGER NOT NULL DEFAULT 0,
                    missing_data_present INTEGER NOT NULL DEFAULT 0,
                    quality_flags TEXT NOT NULL DEFAULT '[]',
                    user_feedback_score REAL,
                    human_review_status TEXT NOT NULL DEFAULT 'unreviewed',
                    reflection_status TEXT NOT NULL DEFAULT 'not_created',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_leak_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    thread_id TEXT,
                    turn_id TEXT,
                    leak_class TEXT NOT NULL,
                    matched_text_hash TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    reviewer_status TEXT NOT NULL DEFAULT 'unreviewed',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL UNIQUE,
                    workspace_id TEXT,
                    created_by_user_id TEXT,
                    candidate_type TEXT NOT NULL,
                    parent_version TEXT,
                    candidate_version TEXT NOT NULL,
                    generated_from_trace_ids TEXT NOT NULL DEFAULT '[]',
                    reflection_summary TEXT,
                    patch TEXT NOT NULL DEFAULT '{}',
                    eval_summary TEXT NOT NULL DEFAULT '{}',
                    rollback_plan TEXT,
                    pareto_status TEXT NOT NULL DEFAULT 'pending',
                    promoted_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase5_training_candidates (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL UNIQUE,
                    reviewer_user_id TEXT,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    consent_scope TEXT NOT NULL,
                    redaction_status TEXT NOT NULL DEFAULT 'redacted',
                    repair_layer TEXT,
                    failure_class TEXT,
                    messages TEXT NOT NULL DEFAULT '[]',
                    labels TEXT NOT NULL DEFAULT '{}',
                    dataset_card TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    exported_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase5_adapter_registry (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    adapter_id TEXT NOT NULL UNIQUE,
                    base_model_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    artifact_uri TEXT,
                    eval_summary TEXT NOT NULL DEFAULT '{}',
                    rollback_plan TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS phase5_model_registry (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    quantization TEXT NOT NULL,
                    context_window INTEGER NOT NULL,
                    hardware_profile TEXT NOT NULL,
                    license TEXT NOT NULL,
                    latency_profile TEXT NOT NULL DEFAULT '{}',
                    eval_profile TEXT NOT NULL DEFAULT '{}',
                    release_status TEXT NOT NULL DEFAULT 'candidate',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workspace_id, model_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    license_status TEXT NOT NULL,
                    canonical_url TEXT,
                    artifact_path TEXT,
                    checksum_sha256 TEXT,
                    source_kind TEXT,
                    rag_eligible INTEGER NOT NULL DEFAULT 1,
                    sft_eligible INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workspace_id, source_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_ingest_jobs (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    runtime TEXT NOT NULL,
                    reader TEXT NOT NULL,
                    chunking_strategy TEXT NOT NULL,
                    embedder_profile TEXT NOT NULL,
                    knowledge_base TEXT NOT NULL,
                    contents_table TEXT NOT NULL,
                    vector_table TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_of_source_id TEXT,
                    error_message TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_source_versions (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    canonical_url TEXT,
                    artifact_path TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunk_reviews (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    reviewer_status TEXT NOT NULL DEFAULT 'pending',
                    rejection_reasons TEXT NOT NULL DEFAULT '[]',
                    evidence_coordinates TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON turn_events(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_turn ON turn_events(turn_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_data_source_type ON data_sources(source_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_memberships_user ON phase4_memberships(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase6_auth_sessions_user ON phase6_auth_sessions(user_id, revoked_at, expires_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase6_auth_tokens_lookup ON phase6_auth_tokens(purpose, token_hash, consumed_at, expires_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_workspaces_org ON phase4_workspaces(organization_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_threads_workspace ON phase4_threads(workspace_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_messages_thread ON phase4_messages(thread_id, sequence_no)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_trace_thread ON phase4_trace_events(thread_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_eval_candidates_workspace ON phase4_eval_candidates(workspace_id, review_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_eval_runs_workspace ON phase4_eval_runs(workspace_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_change_proposals_workspace ON phase4_change_proposals(workspace_id, review_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_exports_workspace ON phase4_exports(workspace_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_export_jobs_workspace ON phase4_export_jobs(workspace_id, status, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_embedding_jobs_workspace ON phase4_embedding_jobs(workspace_id, status, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_image_jobs_workspace ON phase4_image_jobs(workspace_id, status, created_at)")
            self._ensure_column(cursor, "phase4_data_sources", "deleted_at", "TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_data_sources_workspace ON phase4_data_sources(workspace_id, deleted_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_attachments_workspace ON phase4_attachments(workspace_id, deleted_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_chunks_attachment ON phase4_document_chunks(attachment_id, deleted_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_embeddings_attachment ON phase4_embeddings(attachment_id, deleted_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase4_audit_workspace ON phase4_audit_events(workspace_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_trace_spans_trace ON agent_trace_spans(trace_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_trace_spans_stage_time ON agent_trace_spans(stage, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_turn_metrics_created ON agent_turn_metrics(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_turn_metrics_route ON agent_turn_metrics(route_question_type, risk_level)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prompt_leak_trace ON prompt_leak_events(trace_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimization_candidates_id ON optimization_candidates(candidate_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimization_candidates_workspace ON optimization_candidates(workspace_id, pareto_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase5_training_candidates_workspace ON phase5_training_candidates(workspace_id, review_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase5_adapter_registry_adapter ON phase5_adapter_registry(adapter_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase5_model_registry_status ON phase5_model_registry(workspace_id, release_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_sources_workspace ON knowledge_sources(workspace_id, visibility, license_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_ingest_jobs_source ON knowledge_ingest_jobs(source_id, status)")
            for column, column_type in {
                "trace_storage_enabled": "INTEGER NOT NULL DEFAULT 1",
                "feedback_use_allowed": "INTEGER NOT NULL DEFAULT 0",
                "training_candidate_allowed": "INTEGER NOT NULL DEFAULT 0",
                "public_anonymized_examples_allowed": "INTEGER NOT NULL DEFAULT 0",
                "product_updates_allowed": "INTEGER NOT NULL DEFAULT 0",
                "retention_preference": "TEXT NOT NULL DEFAULT 'default'",
                "consent_updated_at": "TEXT",
            }.items():
                self._ensure_column(cursor, "phase4_users", column, column_type)
            self._ensure_column(cursor, "phase4_eval_candidates", "reviewed_by_user_id", "TEXT")
            for column, column_type in {
                "max_tokens": "INTEGER NOT NULL DEFAULT 0",
                "temperature": "REAL NOT NULL DEFAULT 0",
                "top_p": "REAL NOT NULL DEFAULT 0.9",
                "top_k": "INTEGER NOT NULL DEFAULT 0",
                "tool_precision_proxy": "REAL",
                "tool_recall_proxy": "REAL",
                "user_feedback_score": "REAL",
                "human_review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
                "reflection_status": "TEXT NOT NULL DEFAULT 'not_created'",
            }.items():
                self._ensure_column(cursor, "agent_turn_metrics", column, column_type)
            for column, column_type in {
                "workspace_id": "TEXT",
                "created_by_user_id": "TEXT",
                "rollback_plan": "TEXT",
            }.items():
                self._ensure_column(cursor, "optimization_candidates", column, column_type)

    def _ensure_column(self, cursor: sqlite3.Cursor, table_name: str, column_name: str, column_type: str) -> None:
        columns = {row["name"] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any]:
        return {} if row is None else dict(row)

    def append_event(self, session_id: str, event_name: str, payload: dict[str, Any], *, turn_id: str | None = None) -> int:
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO turn_events(session_id, turn_id, event_name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, turn_id, event_name, _as_json(payload), now),
            )
            return int(cursor.lastrowid)

    def create_session(
        self,
        title: str,
        consent: dict[str, Any],
        context: dict[str, Any],
        *,
        user_pseudonym: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        session_id = self._new_id("sess")
        now = _now()
        row_tags = list(tags or [])
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sessions(
                    id, title, user_pseudonym, tags, context, consent, status, archived, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title,
                    user_pseudonym,
                    _as_json(row_tags),
                    _as_json(context),
                    _as_json(consent),
                    "active",
                    0,
                    now,
                    now,
                ),
            )
            cursor.execute(
                "INSERT INTO turn_events(session_id, event_name, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    "session.created",
                    _as_json({"session_id": session_id, "title": title}),
                    now,
                ),
            )
        return self.get_session(session_id)

    def list_sessions(self, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            if include_archived:
                rows = cursor.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC",
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT * FROM sessions WHERE archived = 0 ORDER BY updated_at DESC",
                ).fetchall()
            sessions = [self._normalize_session_row(dict(row)) for row in rows]
            for session in sessions:
                session["turns"] = self._get_turns_for_session(session["session_id"])
            return sessions

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            session = self._normalize_session_row(dict(row))
            turns = self._get_turns_for_session(session_id)
            session["turns"] = turns
            return session

    def _normalize_session_row(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": raw["id"],
            "title": raw["title"],
            "user_pseudonym": raw["user_pseudonym"],
            "tags": _from_json(raw["tags"], []),
            "context": _from_json(raw["context"], {}),
            "consent": _from_json(raw["consent"], {}),
            "status": raw["status"],
            "archived": bool(raw["archived"]),
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
        }

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        user_pseudonym: str | None = None,
        tags: Iterable[str] | None = None,
        context: dict[str, Any] | None = None,
        consent: dict[str, Any] | None = None,
        archived: bool | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        now = _now()
        session = self.get_session(session_id)
        if not session:
            return None
        updates: list[str] = []
        values: list[Any] = []
        if title is not None:
            updates.append("title = ?")
            values.append(title)
        if user_pseudonym is not None:
            updates.append("user_pseudonym = ?")
            values.append(user_pseudonym)
        if tags is not None:
            updates.append("tags = ?")
            values.append(_as_json(list(tags)))
        if context is not None:
            updates.append("context = ?")
            values.append(_as_json(context))
        if consent is not None:
            updates.append("consent = ?")
            values.append(_as_json(consent))
        if archived is not None:
            updates.append("archived = ?")
            values.append(int(archived))
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if not updates:
            updates.append("updated_at = ?")
            values.append(now)
        else:
            updates.append("updated_at = ?")
            values.append(now)
        values.append(session_id)
        q = "UPDATE sessions SET " + ", ".join(updates) + " WHERE id = ?"
        with self._cursor() as cursor:
            cursor.execute(q, values)
        return self.get_session(session_id)

    def create_turn(
        self,
        session_id: str,
        user_message: str,
        answer: str,
        *,
        parent_turn_id: str | None,
        answer_status: str = "draft",
        system_state: dict[str, Any],
        trace: dict[str, Any],
        objectives: dict[str, Any],
        feedback: dict[str, Any] | None = None,
        reflection: dict[str, Any] | None = None,
        prompt_messages: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        event_stream: bool = True,
    ) -> str:
        now = _now()
        turn_id = self._new_id("turn")
        prompt_messages_payload = _as_json(prompt_messages or [])
        metadata_record = dict(metadata or {})
        metadata_record[ANSWER_RECEIPT_METADATA_KEY] = build_answer_integrity_receipt(
            session_id=session_id,
            turn_id=turn_id,
            created_at=now,
            user_message=user_message,
            answer=answer,
            system_state=system_state,
            trace=trace,
        )
        metadata_payload = _as_json(metadata_record)
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO turns(
                    id, session_id, parent_turn_id, user_message, answer, answer_status,
                    created_at, system_state, trace, objectives, prompt_messages, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    session_id,
                    parent_turn_id,
                    user_message,
                    answer,
                    answer_status,
                    now,
                    _as_json(system_state),
                    _as_json(trace),
                    _as_json(objectives),
                    prompt_messages_payload,
                    metadata_payload,
                ),
            )
            for route in [trace.get("route")] if isinstance(trace, dict) and trace.get("route") else []:
                cursor.execute(
                    "INSERT INTO routes(turn_id, payload) VALUES (?, ?)",
                    (turn_id, _as_json(route)),
                )
            for doc in trace.get("retrieved_docs", []):
                cursor.execute(
                    "INSERT INTO retrieved_docs(turn_id, payload) VALUES (?, ?)",
                    (turn_id, _as_json(doc)),
                )
            for hit in trace.get("graph_hits", []):
                cursor.execute(
                    "INSERT INTO graph_hits(turn_id, payload) VALUES (?, ?)",
                    (turn_id, _as_json(hit)),
                )
            for tool in trace.get("tool_invocations", []):
                cursor.execute(
                    "INSERT INTO tool_invocations(turn_id, payload) VALUES (?, ?)",
                    (turn_id, _as_json(tool)),
                )
            if feedback is not None:
                cursor.execute(
                    """
                    INSERT INTO feedback(id, session_id, turn_id, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self._new_id("fb"), session_id, turn_id, _as_json(feedback), now, now),
                )
            if reflection is not None:
                cursor.execute(
                    """
                    INSERT INTO reflections(id, session_id, turn_id, scope, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (self._new_id("rf"), session_id, turn_id, reflection.get("review_status", "candidate"), _as_json(reflection), now, now),
                )
            if event_stream:
                cursor.execute(
                    "INSERT INTO turn_events(session_id, turn_id, event_name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, turn_id, "turn.started", _as_json({"turn_id": turn_id}), now),
                )
            cursor.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            if event_stream:
                cursor.execute(
                    "INSERT INTO turn_events(session_id, turn_id, event_name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, turn_id, "answer.completed", _as_json({"turn_id": turn_id, "mode": system_state.get("mode")}), now),
                )
        return turn_id

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            if not row:
                return None
            turn = dict(row)
            turn["turn_id"] = row["id"]
            turn["trace"] = _from_json(turn["trace"], {})
            turn["system_state"] = _from_json(turn["system_state"], {})
            turn["objectives"] = _from_json(turn["objectives"], {})
            turn["prompt_messages"] = _from_json(turn["prompt_messages"], [])
            turn["metadata"] = _from_json(turn["metadata"], {})
            turn["feedback"] = self._get_feedback_payload(turn_id)
            turn["reflection"] = self._get_reflection_payload(turn_id)
            turn["trace"]["retrieved_docs"] = [
                _from_json(row["payload"], {})
                for row in cursor.execute("SELECT payload FROM retrieved_docs WHERE turn_id = ? ORDER BY id", (turn_id,)).fetchall()
            ]
            turn["trace"]["graph_hits"] = [
                _from_json(row["payload"], {})
                for row in cursor.execute("SELECT payload FROM graph_hits WHERE turn_id = ? ORDER BY id", (turn_id,)).fetchall()
            ]
            turn["trace"]["tool_invocations"] = [
                _from_json(row["payload"], {})
                for row in cursor.execute(
                    "SELECT payload FROM tool_invocations WHERE turn_id = ? ORDER BY id",
                    (turn_id,),
                ).fetchall()
            ]
            route_rows = cursor.execute("SELECT payload FROM routes WHERE turn_id = ?", (turn_id,)).fetchone()
            turn["trace"]["route"] = _from_json(route_rows["payload"], None) if route_rows else None
            turn["answer_integrity_receipt"] = verify_answer_integrity_receipt(turn)
            return turn

    def _get_turns_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            return [self._normalize_turn_row(dict(row)) for row in rows]

    def _normalize_turn_row(self, raw: dict[str, Any]) -> dict[str, Any]:
        turn = {
            "turn_id": raw["id"],
            "session_id": raw["session_id"],
            "parent_turn_id": raw["parent_turn_id"],
            "user_message": raw["user_message"],
            "answer": raw["answer"],
            "answer_status": raw["answer_status"],
            "created_at": raw["created_at"],
            "system_state": _from_json(raw["system_state"], {}),
            "trace": _from_json(raw["trace"], {}),
            "objectives": _from_json(raw["objectives"], {}),
            "prompt_messages": _from_json(raw["prompt_messages"], []),
            "metadata": _from_json(raw["metadata"], {}),
        }
        turn["answer_integrity_receipt"] = verify_answer_integrity_receipt(turn)
        return turn

    def _get_feedback_payload(self, turn_id: str) -> dict[str, Any]:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT payload FROM feedback WHERE turn_id = ?", (turn_id,)).fetchone()
            if row:
                return _from_json(row["payload"], {})
        return {}

    def _get_reflection_payload(self, turn_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT payload FROM reflections WHERE turn_id = ? ORDER BY created_at DESC", (turn_id,)).fetchone()
            if row:
                return _from_json(row["payload"], {})
        return None

    def set_feedback(self, session_id: str, turn_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self._cursor() as cursor:
            existing = cursor.execute("SELECT id FROM feedback WHERE turn_id = ?", (turn_id,)).fetchone()
            if existing:
                cursor.execute(
                    "UPDATE feedback SET payload = ?, updated_at = ? WHERE turn_id = ?",
                    (_as_json(payload), now, turn_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO feedback(id, session_id, turn_id, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (self._new_id("fb"), session_id, turn_id, _as_json(payload), now, now),
                )
            cursor.execute(
                "UPDATE turns SET answer_status = ? WHERE id = ?",
                (payload.get("answer_status", "reviewed"), turn_id),
            )
            cursor.execute(
                "INSERT INTO turn_events(session_id, turn_id, event_name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, turn_id, "feedback.submitted", _as_json(payload), now),
            )
        return self._get_feedback_payload(turn_id)

    def set_reflection(self, session_id: str, turn_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self._cursor() as cursor:
            existing = cursor.execute("SELECT id FROM reflections WHERE turn_id = ?", (turn_id,)).fetchone()
            if existing:
                cursor.execute(
                    "UPDATE reflections SET payload = ?, scope = ?, updated_at = ? WHERE turn_id = ?",
                    (_as_json(payload), payload.get("review_status", "candidate"), now, turn_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO reflections(id, session_id, turn_id, scope, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_id("rf"),
                        session_id,
                        turn_id,
                        payload.get("review_status", "candidate"),
                        _as_json(payload),
                        now,
                        now,
                    ),
                )
            cursor.execute(
                "INSERT INTO turn_events(session_id, turn_id, event_name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, turn_id, "reflection.created", _as_json(payload), now),
            )
        return self._get_reflection_payload(turn_id) or {}

    def list_events(self, session_id: str, since_id: int | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            if since_id is None:
                rows = cursor.execute(
                    "SELECT * FROM turn_events WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT * FROM turn_events WHERE session_id = ? AND id > ? ORDER BY id ASC",
                    (session_id, since_id),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "turn_id": row["turn_id"],
                    "event_name": row["event_name"],
                    "payload": _from_json(row["payload"], {}),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    def list_data_sources(self) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute("SELECT * FROM data_sources ORDER BY created_at DESC").fetchall()
            return [
                {
                    "source_id": row["id"],
                    "source_type": row["source_type"],
                    "path": row["path"],
                    "url": row["url"],
                    "owner": row["owner"],
                    "license_status": row["license_status"],
                    "training_eligible": bool(row["training_eligible"]),
                    "refresh_policy": row["refresh_policy"],
                    "checksum": row["checksum"],
                    "inspection": _from_json(row["inspection"], {}),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

    def create_data_source(
        self,
        source_type: str,
        *,
        path: str | None = None,
        url: str | None = None,
        owner: str | None = None,
        license_status: str = "unknown",
        training_eligible: bool = False,
        refresh_policy: str = "manual",
        checksum: str | None = None,
        inspection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        source_id = self._new_id("source")
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO data_sources(
                    id, source_type, path, url, owner, license_status, training_eligible, refresh_policy,
                    checksum, inspection, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    source_type,
                    path,
                    url,
                    owner,
                    license_status,
                    int(bool(training_eligible)),
                    refresh_policy,
                    checksum,
                    _as_json(inspection or {}),
                    now,
                    now,
                ),
            )
        return {
            "source_id": source_id,
            "source_type": source_type,
            "path": path,
            "url": url,
            "owner": owner,
            "license_status": license_status,
            "training_eligible": training_eligible,
            "refresh_policy": refresh_policy,
            "checksum": checksum,
            "inspection": inspection or {},
            "created_at": now,
            "updated_at": now,
        }

    def create_export(
        self,
        session_id: str,
        redaction_mode: str,
        manifest: dict[str, Any],
        export_id: str | None = None,
    ) -> str:
        export_id = export_id or self._new_id("exp")
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO exports(id, session_id, redaction_mode, manifest, created_at) VALUES (?, ?, ?, ?, ?)",
                (export_id, session_id, redaction_mode, _as_json(manifest), now),
            )
            cursor.execute(
                "INSERT INTO turn_events(session_id, event_name, payload, created_at) VALUES (?, ?, ?, ?)",
                (session_id, "export.completed", _as_json({"export_id": export_id}), now),
            )
        return export_id

    def get_export_manifest(self, export_id: str) -> dict[str, Any] | None:
        record = self.get_export(export_id)
        return record["manifest"] if record else None

    def get_export(self, export_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT id, session_id, redaction_mode, manifest, created_at FROM exports WHERE id = ?",
                (export_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "export_id": row["id"],
                "session_id": row["session_id"],
                "redaction_mode": row["redaction_mode"],
                "manifest": _from_json(row["manifest"], {}),
                "created_at": row["created_at"],
            }

    def create_corpus_audit(self, audit_id: str, config_path: str, corpus_hash: str, corpus_count: int) -> str:
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO corpus_audits(id, config_path, corpus_hash, corpus_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (audit_id, config_path, corpus_hash, corpus_count, now),
            )
        return audit_id

    @staticmethod
    def _new_uuid() -> str:
        return str(uuid.uuid4())

    def upsert_phase4_user(self, *, email: str, display_name: str | None = None) -> dict[str, Any]:
        now = _now()
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("email is required")
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_users WHERE email = ?", (normalized_email,)).fetchone()
            if row:
                cursor.execute(
                    "UPDATE phase4_users SET display_name = ?, updated_at = ?, last_login_at = ? WHERE id = ?",
                    (display_name or row["display_name"], now, now, row["id"]),
                )
                user_id = row["id"]
            else:
                user_id = self._new_uuid()
                cursor.execute(
                    """
                    INSERT INTO phase4_users(
                        id, email, display_name, auth_provider_subject, status,
                        created_at, updated_at, last_login_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        normalized_email,
                        display_name or normalized_email.split("@")[0],
                        f"local_dev:{normalized_email}",
                        "active",
                        now,
                        now,
                        now,
                    ),
                )
        return self.get_phase4_user(user_id) or {}

    def get_phase4_user(self, user_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_users WHERE id = ?", (user_id,)).fetchone()
            return self._normalize_phase4_user(dict(row)) if row else None

    def get_phase4_user_by_email(self, email: str) -> dict[str, Any] | None:
        normalized_email = email.strip().lower()
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_users WHERE email = ?", (normalized_email,)).fetchone()
            return self._normalize_phase4_user(dict(row)) if row else None

    def _normalize_phase4_user(self, raw: dict[str, Any]) -> dict[str, Any]:
        training_candidate_allowed = bool(raw.get("training_candidate_allowed")) or str(raw.get("training_consent_default") or "").lower() == "yes"
        account_consent = {
            "schema_version": "phase6.account_consent.v1",
            "trace_storage_enabled": bool(raw.get("trace_storage_enabled", 1)),
            "feedback_use_allowed": bool(raw.get("feedback_use_allowed", 0)),
            "training_candidate_allowed": training_candidate_allowed,
            "public_anonymized_examples_allowed": bool(raw.get("public_anonymized_examples_allowed", 0)),
            "product_updates_allowed": bool(raw.get("product_updates_allowed", 0)),
            "retention_preference": raw.get("retention_preference") or "default",
            "updated_at": raw.get("consent_updated_at"),
        }
        return {
            "id": raw["id"],
            "email": raw["email"],
            "display_name": raw["display_name"],
            "auth_provider_subject": raw["auth_provider_subject"],
            "status": raw["status"],
            "role_label": raw["role_label"],
            "region_hint": raw["region_hint"],
            "units_preference": raw["units_preference"],
            "privacy_mode": raw["privacy_mode"],
            "training_consent_default": raw["training_consent_default"],
            "account_consent": account_consent,
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
            "last_login_at": raw["last_login_at"],
        }

    def get_phase6_account_consent(self, user_id: str) -> dict[str, Any] | None:
        user = self.get_phase4_user(user_id)
        return dict(user["account_consent"]) if user else None

    def update_phase6_account_consent(
        self,
        *,
        user_id: str,
        actor_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        user = self.get_phase4_user(user_id)
        if not user or user.get("status") != "active":
            return None
        allowed = {
            "trace_storage_enabled",
            "feedback_use_allowed",
            "training_candidate_allowed",
            "public_anonymized_examples_allowed",
            "product_updates_allowed",
            "retention_preference",
        }
        updates = {key: value for key, value in payload.items() if key in allowed}
        if not updates:
            return dict(user["account_consent"])
        now = _now()
        assignments: list[str] = []
        values: list[Any] = []
        changes: dict[str, dict[str, Any]] = {}
        current = dict(user["account_consent"])
        for key, value in updates.items():
            stored_value = value
            if key.endswith("_allowed") or key == "trace_storage_enabled":
                stored_value = int(bool(value))
                next_value = bool(value)
            else:
                next_value = value
            if current.get(key) == next_value:
                continue
            assignments.append(f"{key} = ?")
            values.append(stored_value)
            changes[key] = {"from": current.get(key), "to": next_value}
        if "training_candidate_allowed" in changes:
            assignments.append("training_consent_default = ?")
            values.append("yes" if bool(updates["training_candidate_allowed"]) else "no")
        if not assignments:
            return dict(user["account_consent"])
        assignments.extend(["consent_updated_at = ?", "updated_at = ?"])
        values.extend([now, now, user_id])
        with self._cursor() as cursor:
            cursor.execute(
                f"UPDATE phase4_users SET {', '.join(assignments)} WHERE id = ?",
                tuple(values),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="account.consent_updated",
                actor_user_id=actor_user_id,
                target_type="user",
                target_id=user_id,
                payload={"changes": changes, "reauthenticated": True},
                created_at=now,
            )
        updated = self.get_phase4_user(user_id)
        return dict(updated["account_consent"]) if updated else None

    def create_phase6_password_signup(
        self,
        *,
        email: str,
        display_name: str | None,
        password_hash: str,
        token_hash: str,
        expires_at: str,
    ) -> dict[str, Any]:
        now = _now()
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("email is required")
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_users WHERE email = ?", (normalized_email,)).fetchone()
            if row:
                user = self._normalize_phase4_user(dict(row))
                created = False
                if user["status"] == "pending_verification":
                    cursor.execute(
                        """
                        UPDATE phase4_users
                        SET display_name = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (display_name or user["display_name"], now, user["id"]),
                    )
                    cursor.execute(
                        """
                        INSERT INTO phase6_password_credentials(user_id, email, password_hash, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                          password_hash = excluded.password_hash,
                          updated_at = excluded.updated_at
                        """,
                        (user["id"], normalized_email, password_hash, now, now),
                    )
                    self._create_phase6_auth_token_row(
                        cursor,
                        user_id=user["id"],
                        email=normalized_email,
                        purpose="email_verification",
                        token_hash=token_hash,
                        expires_at=expires_at,
                        created_at=now,
                    )
                    user = self.get_phase4_user(user["id"]) or user
                    token_created = True
                else:
                    token_created = False
            else:
                user_id = self._new_uuid()
                cursor.execute(
                    """
                    INSERT INTO phase4_users(
                        id, email, display_name, auth_provider_subject, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        normalized_email,
                        display_name or normalized_email.split("@")[0],
                        f"password:{normalized_email}",
                        "pending_verification",
                        now,
                        now,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO phase6_password_credentials(user_id, email, password_hash, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, normalized_email, password_hash, now, now),
                )
                self._create_phase6_auth_token_row(
                    cursor,
                    user_id=user_id,
                    email=normalized_email,
                    purpose="email_verification",
                    token_hash=token_hash,
                    expires_at=expires_at,
                    created_at=now,
                )
                user = self.get_phase4_user(user_id) or {}
                created = True
                token_created = True
        return {"user": user, "created": created, "verification_token_created": token_created}

    def get_phase6_password_credential(self, email: str) -> dict[str, Any] | None:
        normalized_email = email.strip().lower()
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                SELECT c.*, u.status, u.display_name
                FROM phase6_password_credentials c
                JOIN phase4_users u ON u.id = c.user_id
                WHERE c.email = ?
                """,
                (normalized_email,),
            ).fetchone()
            return dict(row) if row else None

    def verify_phase6_email_token(self, *, token_hash: str) -> dict[str, Any] | None:
        now = _now()
        with self._cursor() as cursor:
            token = self._consume_phase6_auth_token_row(cursor, purpose="email_verification", token_hash=token_hash, consumed_at=now)
            if not token:
                return None
            cursor.execute(
                "UPDATE phase6_password_credentials SET email_verified_at = ?, updated_at = ? WHERE user_id = ?",
                (now, now, token["user_id"]),
            )
            cursor.execute(
                "UPDATE phase4_users SET status = 'active', updated_at = ? WHERE id = ?",
                (now, token["user_id"]),
            )
            return self.get_phase4_user(token["user_id"])

    def create_phase6_password_reset_token(self, *, email: str, token_hash: str, expires_at: str) -> bool:
        credential = self.get_phase6_password_credential(email)
        if not credential or credential.get("status") != "active" or not credential.get("email_verified_at"):
            return False
        now = _now()
        with self._cursor() as cursor:
            self._create_phase6_auth_token_row(
                cursor,
                user_id=credential["user_id"],
                email=credential["email"],
                purpose="password_reset",
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=now,
            )
        return True

    def reset_phase6_password(self, *, token_hash: str, password_hash: str) -> dict[str, Any] | None:
        now = _now()
        with self._cursor() as cursor:
            token = self._consume_phase6_auth_token_row(cursor, purpose="password_reset", token_hash=token_hash, consumed_at=now)
            if not token:
                return None
            cursor.execute(
                "UPDATE phase6_password_credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (password_hash, now, token["user_id"]),
            )
            cursor.execute("UPDATE phase4_users SET updated_at = ? WHERE id = ?", (now, token["user_id"]))
            return self.get_phase4_user(token["user_id"])

    def _create_phase6_auth_token_row(
        self,
        cursor: sqlite3.Cursor,
        *,
        user_id: str,
        email: str,
        purpose: str,
        token_hash: str,
        expires_at: str,
        created_at: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO phase6_auth_tokens(id, user_id, email, purpose, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (self._new_uuid(), user_id, email, purpose, token_hash, expires_at, created_at),
        )

    def _consume_phase6_auth_token_row(
        self,
        cursor: sqlite3.Cursor,
        *,
        purpose: str,
        token_hash: str,
        consumed_at: str,
    ) -> dict[str, Any] | None:
        row = cursor.execute(
            """
            SELECT *
            FROM phase6_auth_tokens
            WHERE purpose = ? AND token_hash = ? AND consumed_at IS NULL AND expires_at > ?
            """,
            (purpose, token_hash, consumed_at),
        ).fetchone()
        if not row:
            return None
        cursor.execute("UPDATE phase6_auth_tokens SET consumed_at = ? WHERE id = ?", (consumed_at, row["id"]))
        return dict(row)

    def upsert_phase6_auth_session(
        self,
        *,
        session_id: str,
        user_id: str,
        auth_subject: str,
        email: str,
        display_name: str,
        issued_at: str,
        expires_at: str,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        user_agent_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest() if user_agent else None
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase6_auth_sessions(
                    id, user_id, auth_subject, email, display_name, issued_at,
                    expires_at, last_seen_at, user_agent_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (session_id, user_id, auth_subject, email, display_name, issued_at, expires_at, now, user_agent_hash),
            )
        return self.get_phase6_auth_session(session_id) or {}

    def get_phase6_auth_session(self, session_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase6_auth_sessions WHERE id = ?", (session_id,)).fetchone()
            return self._normalize_phase6_auth_session(dict(row)) if row else None

    def touch_phase6_auth_session(self, session_id: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("UPDATE phase6_auth_sessions SET last_seen_at = ? WHERE id = ?", (_now(), session_id))

    def list_phase6_auth_sessions(self, user_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT *
                FROM phase6_auth_sessions
                WHERE user_id = ?
                ORDER BY last_seen_at DESC, issued_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [self._normalize_phase6_auth_session(dict(row)) for row in rows]

    def revoke_phase6_auth_sessions(self, *, user_id: str, revoked_by_user_id: str) -> dict[str, Any]:
        now = _now()
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase6_auth_sessions WHERE user_id = ? AND revoked_at IS NULL",
                (user_id,),
            ).fetchall()
            cursor.execute(
                "UPDATE phase6_auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            session_rows = [self._normalize_phase6_auth_session(dict(row)) for row in rows]
            for session in session_rows:
                cursor.execute(
                    """
                    INSERT INTO phase4_audit_events(
                        id, actor_user_id, event_type, target_type, target_id, payload, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_uuid(),
                        revoked_by_user_id,
                        "auth.sessions_revoked",
                        "auth_session",
                        session["id"],
                        _as_json({"user_id": user_id, "revoked_all": True}),
                        now,
                    ),
                )
        return {"revoked_at": now, "revoked_count": len(session_rows), "sessions": session_rows}

    def revoke_phase6_auth_session(self, *, session_id: str, revoked_by_user_id: str) -> dict[str, Any]:
        now = _now()
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM phase6_auth_sessions WHERE id = ? AND revoked_at IS NULL",
                (session_id,),
            ).fetchone()
            if not row:
                return {"revoked_at": None, "revoked_count": 0, "session": None}
            cursor.execute("UPDATE phase6_auth_sessions SET revoked_at = ? WHERE id = ?", (now, session_id))
            session = self._normalize_phase6_auth_session(dict(row))
            cursor.execute(
                """
                INSERT INTO phase4_audit_events(
                    id, actor_user_id, event_type, target_type, target_id, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._new_uuid(),
                    revoked_by_user_id,
                    "auth.session_revoked",
                    "auth_session",
                    session["id"],
                    _as_json({"user_id": session["user_id"], "revoked_all": False}),
                    now,
                ),
            )
        return {"revoked_at": now, "revoked_count": 1, "session": session}

    def _normalize_phase6_auth_session(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "user_id": raw["user_id"],
            "auth_subject": raw["auth_subject"],
            "email": raw["email"],
            "display_name": raw["display_name"],
            "issued_at": raw["issued_at"],
            "expires_at": raw["expires_at"],
            "last_seen_at": raw["last_seen_at"],
            "revoked_at": raw["revoked_at"],
            "user_agent_hash": raw["user_agent_hash"],
        }

    def create_phase4_organization(
        self,
        *,
        name: str,
        slug: str,
        plan: str,
        created_by_user_id: str,
    ) -> dict[str, Any]:
        now = _now()
        organization_id = self._new_uuid()
        membership_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_organizations(
                    id, name, slug, plan, created_by_user_id, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (organization_id, name, slug, plan, created_by_user_id, _as_json({}), now, now),
            )
            cursor.execute(
                """
                INSERT INTO phase4_memberships(id, organization_id, user_id, role, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (membership_id, organization_id, created_by_user_id, "owner", "active", now),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="organization.created",
                actor_user_id=created_by_user_id,
                organization_id=organization_id,
                target_type="organization",
                target_id=organization_id,
                payload={"name": name, "slug": slug},
                created_at=now,
            )
        created = self.get_phase4_organization(organization_id) or {}
        created["role"] = "owner"
        created["membership_status"] = "active"
        return created

    def list_phase4_organizations_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT o.*, m.role, m.status AS membership_status
                FROM phase4_organizations o
                JOIN phase4_memberships m ON m.organization_id = o.id
                WHERE m.user_id = ? AND m.status = 'active' AND o.deleted_at IS NULL
                ORDER BY o.created_at ASC
                """,
                (user_id,),
            ).fetchall()
            return [self._normalize_phase4_organization(dict(row)) for row in rows]

    def get_phase4_organization(self, organization_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_organizations WHERE id = ? AND deleted_at IS NULL", (organization_id,)).fetchone()
            return self._normalize_phase4_organization(dict(row)) if row else None

    def _normalize_phase4_organization(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {
            "id": raw["id"],
            "name": raw["name"],
            "slug": raw["slug"],
            "plan": raw["plan"],
            "created_by_user_id": raw["created_by_user_id"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
            "deleted_at": raw["deleted_at"],
        }
        if "role" in raw:
            out["role"] = raw["role"]
        if "membership_status" in raw:
            out["membership_status"] = raw["membership_status"]
        return out

    def phase4_user_can_access_org(self, user_id: str, organization_id: str) -> bool:
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                SELECT 1 FROM phase4_memberships
                WHERE user_id = ? AND organization_id = ? AND status = 'active'
                """,
                (user_id, organization_id),
            ).fetchone()
            return bool(row)

    def get_phase4_membership(self, *, user_id: str, organization_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                SELECT *
                FROM phase4_memberships
                WHERE user_id = ? AND organization_id = ? AND status = 'active'
                """,
                (user_id, organization_id),
            ).fetchone()
            return self._normalize_phase4_membership(dict(row)) if row else None

    def list_phase4_memberships(self, organization_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT m.*, u.email, u.display_name
                FROM phase4_memberships m
                JOIN phase4_users u ON u.id = m.user_id
                WHERE m.organization_id = ? AND m.status = 'active'
                ORDER BY m.created_at ASC
                """,
                (organization_id,),
            ).fetchall()
            return [self._normalize_phase4_membership(dict(row)) for row in rows]

    def upsert_phase4_membership(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        now = _now()
        with self._cursor() as cursor:
            existing = cursor.execute(
                "SELECT * FROM phase4_memberships WHERE organization_id = ? AND user_id = ?",
                (organization_id, user_id),
            ).fetchone()
            if existing:
                cursor.execute(
                    """
                    UPDATE phase4_memberships
                    SET role = ?, status = 'active'
                    WHERE organization_id = ? AND user_id = ?
                    """,
                    (role, organization_id, user_id),
                )
                membership_id = existing["id"]
            else:
                membership_id = self._new_uuid()
                cursor.execute(
                    """
                    INSERT INTO phase4_memberships(id, organization_id, user_id, role, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (membership_id, organization_id, user_id, role, "active", now),
                )
            self._insert_phase4_audit(
                cursor,
                event_type="membership.upserted",
                actor_user_id=actor_user_id,
                organization_id=organization_id,
                target_type="membership",
                target_id=membership_id,
                payload={"user_id": user_id, "role": role},
                created_at=now,
            )
        return self.get_phase4_membership(user_id=user_id, organization_id=organization_id) or {}

    def _normalize_phase4_membership(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "user_id": raw["user_id"],
            "role": raw["role"],
            "status": raw["status"],
            "created_at": raw["created_at"],
        }
        if "email" in raw:
            out["email"] = raw["email"]
        if "display_name" in raw:
            out["display_name"] = raw["display_name"]
        return out

    def create_phase4_workspace(
        self,
        *,
        organization_id: str,
        name: str,
        created_by_user_id: str,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        workspace_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_workspaces(
                    id, organization_id, name, created_by_user_id, settings, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (workspace_id, organization_id, name, created_by_user_id, _as_json(settings or {}), now, now),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="workspace.created",
                actor_user_id=created_by_user_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                target_type="workspace",
                target_id=workspace_id,
                payload={"name": name},
                created_at=now,
            )
        return self.get_phase4_workspace(workspace_id) or {}

    def list_phase4_workspaces_for_user(self, user_id: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            params: list[Any] = [user_id]
            org_filter = ""
            if organization_id:
                org_filter = "AND w.organization_id = ?"
                params.append(organization_id)
            rows = cursor.execute(
                f"""
                SELECT w.*
                FROM phase4_workspaces w
                JOIN phase4_memberships m ON m.organization_id = w.organization_id
                WHERE m.user_id = ? AND m.status = 'active' AND w.deleted_at IS NULL {org_filter}
                ORDER BY w.created_at ASC
                """,
                params,
            ).fetchall()
            return [self._normalize_phase4_workspace(dict(row)) for row in rows]

    def get_phase4_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_workspaces WHERE id = ? AND deleted_at IS NULL", (workspace_id,)).fetchone()
            return self._normalize_phase4_workspace(dict(row)) if row else None

    def delete_phase4_workspace(self, *, workspace_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        now = _now()
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_workspaces WHERE id = ? AND deleted_at IS NULL", (workspace_id,)).fetchone()
            if not row:
                return None
            workspace = self._normalize_phase4_workspace(dict(row))
            usage = self.phase4_workspace_usage(workspace_id)
            cursor.execute("UPDATE phase4_workspaces SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, workspace_id))
            cursor.execute("UPDATE phase4_field_contexts SET deleted_at = ?, updated_at = ? WHERE workspace_id = ? AND deleted_at IS NULL", (now, now, workspace_id))
            cursor.execute(
                """
                UPDATE phase4_threads
                SET deleted_at = ?, status = 'deleted', training_eligible = 0, updated_at = ?
                WHERE workspace_id = ? AND deleted_at IS NULL
                """,
                (now, now, workspace_id),
            )
            cursor.execute("UPDATE phase4_attachments SET deleted_at = ?, parse_status = ? WHERE workspace_id = ? AND deleted_at IS NULL", (now, "deleted", workspace_id))
            cursor.execute("UPDATE phase4_data_sources SET deleted_at = ?, updated_at = ? WHERE workspace_id = ? AND deleted_at IS NULL", (now, now, workspace_id))
            cursor.execute("UPDATE phase4_document_chunks SET deleted_at = ? WHERE workspace_id = ? AND deleted_at IS NULL", (now, workspace_id))
            cursor.execute("UPDATE phase4_embeddings SET deleted_at = ? WHERE workspace_id = ? AND deleted_at IS NULL", (now, workspace_id))
            self._insert_phase4_audit(
                cursor,
                event_type="workspace.deleted",
                actor_user_id=deleted_by_user_id,
                organization_id=workspace["organization_id"],
                workspace_id=workspace_id,
                target_type="workspace",
                target_id=workspace_id,
                payload={
                    "name": workspace["name"],
                    "soft_deleted": True,
                    "thread_count": usage["thread_count"],
                    "attachment_count": usage["attachment_count"],
                    "data_source_count": usage["data_source_count"],
                    "retention_policy": "soft_delete_then_purge_policy",
                },
                created_at=now,
            )
        workspace["deleted_at"] = now
        workspace["updated_at"] = now
        workspace["deletion_summary"] = {
            "soft_deleted": True,
            "thread_count": usage["thread_count"],
            "attachment_count": usage["attachment_count"],
            "data_source_count": usage["data_source_count"],
            "retention_policy": "soft_delete_then_purge_policy",
        }
        return workspace

    def _normalize_phase4_workspace(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "name": raw["name"],
            "created_by_user_id": raw["created_by_user_id"],
            "settings": _from_json(raw["settings"], {}),
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
            "deleted_at": raw["deleted_at"],
        }

    def phase4_user_can_access_workspace(self, user_id: str, workspace_id: str) -> bool:
        workspace = self.get_phase4_workspace(workspace_id)
        return bool(workspace and self.phase4_user_can_access_org(user_id, workspace["organization_id"]))

    def delete_phase6_account(self, *, user_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        user = self.get_phase4_user(user_id)
        if not user or user.get("status") != "active":
            return None
        now = _now()
        organizations = self.list_phase4_organizations_for_user(user_id)
        workspaces = self.list_phase4_workspaces_for_user(user_id)
        with self._cursor() as cursor:
            cursor.execute("UPDATE phase4_users SET status = 'deleted', updated_at = ? WHERE id = ?", (now, user_id))
            cursor.execute("UPDATE phase4_memberships SET status = 'inactive' WHERE user_id = ? AND status = 'active'", (user_id,))
            for workspace in workspaces:
                self._insert_phase4_audit(
                    cursor,
                    event_type="account.deleted",
                    actor_user_id=deleted_by_user_id,
                    organization_id=workspace["organization_id"],
                    workspace_id=workspace["id"],
                    target_type="user",
                    target_id=user_id,
                    payload={
                        "email_hash": hashlib.sha256(str(user["email"]).encode("utf-8")).hexdigest(),
                        "memberships_inactivated": True,
                        "export_acknowledgement_required": True,
                    },
                    created_at=now,
                )
        deleted = dict(user)
        deleted["status"] = "deleted"
        deleted["updated_at"] = now
        return {
            "schema_version": "phase6.account_delete.v1",
            "deleted_at": now,
            "user": deleted,
            "organization_count": len(organizations),
            "workspace_count": len(workspaces),
            "memberships_inactivated": True,
            "reauth_method": "current_identity_email_confirmation",
            "export_acknowledged": True,
        }

    def phase4_workspace_usage(self, workspace_id: str) -> dict[str, int]:
        with self._cursor() as cursor:
            return {
                "thread_count": int(
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM phase4_threads WHERE workspace_id = ? AND deleted_at IS NULL",
                        (workspace_id,),
                    ).fetchone()["count"],
                ),
                "message_count": int(
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM phase4_messages WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()["count"],
                ),
                "attachment_count": int(
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM phase4_attachments WHERE workspace_id = ? AND deleted_at IS NULL",
                        (workspace_id,),
                    ).fetchone()["count"],
                ),
                "attachment_bytes": int(
                    cursor.execute(
                        "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM phase4_attachments WHERE workspace_id = ? AND deleted_at IS NULL",
                        (workspace_id,),
                    ).fetchone()["total"],
                ),
                "data_source_count": int(
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM phase4_data_sources WHERE workspace_id = ? AND deleted_at IS NULL",
                        (workspace_id,),
                    ).fetchone()["count"],
                ),
                "eval_run_count": int(
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM phase4_eval_runs WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()["count"],
                ),
                "export_count": int(
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM phase4_exports WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()["count"],
                ),
            }

    def create_phase4_field_context(self, *, workspace: dict[str, Any], created_by_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        field_context_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_field_contexts(
                    id, organization_id, workspace_id, created_by_user_id, display_name, region_text,
                    country, province_state, county_rm, crop_current, crop_year, soil_series_or_texture,
                    drainage_class, irrigation_status, soil_test_summary, crop_rotation_notes, management_notes,
                    known_constraints, sensitivity, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    field_context_id,
                    workspace["organization_id"],
                    workspace["id"],
                    created_by_user_id,
                    payload["display_name"],
                    payload["region_text"],
                    payload.get("country"),
                    payload.get("province_state"),
                    payload.get("county_rm"),
                    payload.get("crop_current"),
                    payload.get("crop_year"),
                    payload.get("soil_series_or_texture"),
                    payload.get("drainage_class"),
                    payload.get("irrigation_status"),
                    payload.get("soil_test_summary"),
                    payload.get("crop_rotation_notes"),
                    payload.get("management_notes"),
                    _as_json(payload.get("known_constraints", [])),
                    payload.get("sensitivity", "medium"),
                    _as_json(payload.get("metadata", {})),
                    now,
                    now,
                ),
            )
        return self.get_phase4_field_context(field_context_id) or {}

    def list_phase4_field_contexts(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_field_contexts WHERE workspace_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_field_context(dict(row)) for row in rows]

    def get_phase4_field_context(self, field_context_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_field_contexts WHERE id = ? AND deleted_at IS NULL", (field_context_id,)).fetchone()
            return self._normalize_phase4_field_context(dict(row)) if row else None

    def update_phase4_field_context(
        self,
        *,
        field_context_id: str,
        actor_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = self.get_phase4_field_context(field_context_id)
        if not current:
            return None
        allowed_fields = {
            "display_name",
            "region_text",
            "country",
            "province_state",
            "county_rm",
            "crop_current",
            "crop_year",
            "soil_series_or_texture",
            "drainage_class",
            "irrigation_status",
            "soil_test_summary",
            "crop_rotation_notes",
            "management_notes",
            "known_constraints",
            "sensitivity",
            "metadata",
        }
        updates = {key: value for key, value in payload.items() if key in allowed_fields}
        if not updates:
            return current
        now = _now()
        assignments = [f"{key} = ?" for key in updates]
        params = [_as_json(value) if key in {"known_constraints", "metadata"} else value for key, value in updates.items()]
        params.extend([now, field_context_id])
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE phase4_field_contexts
                SET {", ".join(assignments)}, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                params,
            )
            self._insert_phase4_audit(
                cursor,
                event_type="field_context.updated",
                actor_user_id=actor_user_id,
                organization_id=current["organization_id"],
                workspace_id=current["workspace_id"],
                target_type="field_context",
                target_id=field_context_id,
                payload={"updated_fields": sorted(updates)},
                created_at=now,
            )
        return self.get_phase4_field_context(field_context_id)

    def delete_phase4_field_context(self, *, field_context_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        current = self.get_phase4_field_context(field_context_id)
        if not current:
            return None
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE phase4_field_contexts SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, now, field_context_id),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="field_context.deleted",
                actor_user_id=deleted_by_user_id,
                organization_id=current["organization_id"],
                workspace_id=current["workspace_id"],
                target_type="field_context",
                target_id=field_context_id,
                payload={"display_name": current["display_name"], "region_text": current["region_text"]},
                created_at=now,
            )
        deleted = dict(current)
        deleted["deleted_at"] = now
        deleted["updated_at"] = now
        return deleted

    def _normalize_phase4_field_context(self, raw: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "display_name": raw["display_name"],
            "region_text": raw["region_text"],
            "country": raw["country"],
            "province_state": raw["province_state"],
            "county_rm": raw["county_rm"],
            "crop_current": raw["crop_current"],
            "crop_year": raw["crop_year"],
            "soil_series_or_texture": raw["soil_series_or_texture"],
            "drainage_class": raw["drainage_class"],
            "irrigation_status": raw["irrigation_status"],
            "soil_test_summary": raw["soil_test_summary"],
            "crop_rotation_notes": raw["crop_rotation_notes"],
            "management_notes": raw["management_notes"],
            "known_constraints": _from_json(raw["known_constraints"], []),
            "sensitivity": raw["sensitivity"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
            "deleted_at": raw["deleted_at"],
        }
        normalized["quality_meter"] = evaluate_field_context_quality(normalized)
        return normalized

    def append_phase4_field_event(
        self,
        *,
        field_context: dict[str, Any],
        recorded_by_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_type = str(payload.get("event_type") or "")
        corrects_event_id = str(payload["corrects_event_id"]) if payload.get("corrects_event_id") else None
        if event_type not in FIELD_EVENT_TYPES:
            raise ValueError(f"unsupported field event type: {event_type}")
        if (event_type == "correction") != bool(corrects_event_id):
            raise ValueError("correction events must identify exactly one corrected field event")
        validate_field_event_payload(payload.get("payload"))

        event_id = self._new_uuid()
        with self._field_event_lock:
            with self._cursor() as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                recorded_at = _now()
                occurred_at = str(payload.get("occurred_at") or recorded_at)
                previous = cursor.execute(
                    """
                    SELECT integrity_sha256
                    FROM phase4_field_events
                    WHERE field_context_id = ?
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT 1
                    """,
                    (field_context["id"],),
                ).fetchone()
                if corrects_event_id:
                    corrected = cursor.execute(
                        """
                        SELECT id
                        FROM phase4_field_events
                        WHERE id = ? AND field_context_id = ?
                        """,
                        (corrects_event_id, field_context["id"]),
                    ).fetchone()
                    if not corrected:
                        raise ValueError("corrected field event does not exist in this field")
                event = {
                    "id": event_id,
                    "organization_id": field_context["organization_id"],
                    "workspace_id": field_context["workspace_id"],
                    "field_context_id": field_context["id"],
                    "recorded_by_user_id": recorded_by_user_id,
                    "event_type": event_type,
                    "occurred_at": occurred_at,
                    "payload": dict(payload.get("payload") or {}),
                    "provenance": dict(payload.get("provenance") or {}),
                    "corrects_event_id": corrects_event_id,
                    "previous_event_sha256": previous["integrity_sha256"] if previous else None,
                    "recorded_at": recorded_at,
                }
                event["integrity_sha256"] = field_event_integrity_sha256(event)
                cursor.execute(
                    """
                    INSERT INTO phase4_field_events(
                        id, organization_id, workspace_id, field_context_id, recorded_by_user_id,
                        event_type, occurred_at, payload, provenance, corrects_event_id,
                        previous_event_sha256, integrity_sha256, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["id"],
                        event["organization_id"],
                        event["workspace_id"],
                        event["field_context_id"],
                        event["recorded_by_user_id"],
                        event["event_type"],
                        event["occurred_at"],
                        _as_json(event["payload"]),
                        _as_json(event["provenance"]),
                        event["corrects_event_id"],
                        event["previous_event_sha256"],
                        event["integrity_sha256"],
                        event["recorded_at"],
                    ),
                )
                self._insert_phase4_audit(
                    cursor,
                    event_type="field_event.appended",
                    actor_user_id=recorded_by_user_id,
                    organization_id=field_context["organization_id"],
                    workspace_id=field_context["workspace_id"],
                    target_type="field_event",
                    target_id=event_id,
                    payload={
                        "field_context_id": field_context["id"],
                        "field_event_type": event_type,
                        "integrity_sha256": event["integrity_sha256"],
                        "corrects_event_id": corrects_event_id,
                    },
                    created_at=recorded_at,
                )
        return self.get_phase4_field_event(event_id) or {}

    def get_phase4_field_event(self, event_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_field_events WHERE id = ?", (event_id,)).fetchone()
            return self._normalize_phase4_field_event(dict(row)) if row else None

    def list_phase4_field_events(self, field_context_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT *
                FROM phase4_field_events
                WHERE field_context_id = ?
                ORDER BY recorded_at, id
                """,
                (field_context_id,),
            ).fetchall()
            return [self._normalize_phase4_field_event(dict(row)) for row in rows]

    def verify_phase4_field_event_chain(self, field_context_id: str) -> dict[str, Any]:
        return verify_field_event_chain(self.list_phase4_field_events(field_context_id))

    def export_phase4_field_event_sync(
        self,
        field_context_id: str,
        *,
        after_sha256: str | None = None,
    ) -> dict[str, Any]:
        return field_event_sync_export(
            self.list_phase4_field_events(field_context_id),
            field_context_id=field_context_id,
            after_sha256=after_sha256,
        )

    def import_phase4_field_event_sync(
        self,
        *,
        field_context: dict[str, Any],
        syncing_user_id: str,
        source_device_id: str,
        base_head_sha256: str | None,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for event in events:
            validate_field_event_payload(event.get("payload"))
        with self._field_event_lock:
            with self._cursor() as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                rows = cursor.execute(
                    """
                    SELECT *
                    FROM phase4_field_events
                    WHERE field_context_id = ?
                    ORDER BY recorded_at, id
                    """,
                    (field_context["id"],),
                ).fetchall()
                local = [self._normalize_phase4_field_event(dict(row)) for row in rows]
                validation = validate_field_event_fast_forward(
                    local_events=local,
                    incoming_events=events,
                    field_context=field_context,
                    syncing_user_id=syncing_user_id,
                    base_head_sha256=base_head_sha256,
                )
                if validation["status"] == "already_applied":
                    return {
                        "schema_version": "open_agronomy_agent.field_event_sync_result.v1",
                        "status": "already_applied",
                        "field_context_id": field_context["id"],
                        "source_device_id": source_device_id,
                        "imported_event_count": 0,
                        "chain": verify_field_event_chain(local),
                        "boundary": (
                            "Idempotent fast-forward retry; no event was duplicated. source_device_id is "
                            "an operator-supplied label, not device attestation."
                        ),
                    }
                for event in validation["events"]:
                    cursor.execute(
                        """
                        INSERT INTO phase4_field_events(
                            id, organization_id, workspace_id, field_context_id, recorded_by_user_id,
                            event_type, occurred_at, payload, provenance, corrects_event_id,
                            previous_event_sha256, integrity_sha256, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event["id"],
                            event["organization_id"],
                            event["workspace_id"],
                            event["field_context_id"],
                            event["recorded_by_user_id"],
                            event["event_type"],
                            event["occurred_at"],
                            _as_json(event["payload"]),
                            _as_json(event["provenance"]),
                            event.get("corrects_event_id"),
                            event.get("previous_event_sha256"),
                            event["integrity_sha256"],
                            event["recorded_at"],
                        ),
                    )
                self._insert_phase4_audit(
                    cursor,
                    event_type="field_event.sync_imported",
                    actor_user_id=syncing_user_id,
                    organization_id=field_context["organization_id"],
                    workspace_id=field_context["workspace_id"],
                    target_type="field_context",
                    target_id=field_context["id"],
                    payload={
                        "source_device_id": source_device_id,
                        "base_head_sha256": base_head_sha256,
                        "result_head_sha256": validation["result_head_sha256"],
                        "imported_event_count": validation["event_count"],
                        "accepted_full_prefix": validation["accepted_full_prefix"],
                    },
                    created_at=_now(),
                )
                combined = [*local, *validation["events"]]
        return {
            "schema_version": "open_agronomy_agent.field_event_sync_result.v1",
            "status": "imported",
            "field_context_id": field_context["id"],
            "source_device_id": source_device_id,
            "imported_event_count": validation["event_count"],
            "accepted_full_prefix": validation["accepted_full_prefix"],
            "chain": verify_field_event_chain(combined),
            "boundary": (
                "Imported as one atomic fast-forward batch. source_device_id is an operator-supplied label, "
                "not device attestation; divergent branches require human reconciliation."
            ),
        }

    @staticmethod
    def _normalize_phase4_field_event(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "open_agronomy_agent.field_event.v1",
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "field_context_id": raw["field_context_id"],
            "recorded_by_user_id": raw.get("recorded_by_user_id"),
            "event_type": raw["event_type"],
            "occurred_at": raw.get("occurred_at"),
            "payload": _from_json(raw.get("payload"), {}),
            "provenance": _from_json(raw.get("provenance"), {}),
            "corrects_event_id": raw.get("corrects_event_id"),
            "previous_event_sha256": raw.get("previous_event_sha256"),
            "integrity_sha256": raw["integrity_sha256"],
            "recorded_at": raw["recorded_at"],
        }

    def create_phase4_thread(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        title: str,
        mode: str,
        trace_capture_level: str,
        field_context_id: str | None = None,
        model_profile_id: str | None = None,
        rag_config_id: str | None = None,
        training_eligible: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        thread_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_threads(
                    id, organization_id, workspace_id, created_by_user_id, field_context_id, title, mode,
                    model_profile_id, rag_config_id, trace_capture_level, training_eligible, metadata,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    workspace["organization_id"],
                    workspace["id"],
                    created_by_user_id,
                    field_context_id,
                    title,
                    mode,
                    model_profile_id,
                    rag_config_id,
                    trace_capture_level,
                    int(bool(training_eligible)),
                    _as_json(metadata or {}),
                    now,
                    now,
                ),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="thread.created",
                actor_user_id=created_by_user_id,
                organization_id=workspace["organization_id"],
                workspace_id=workspace["id"],
                target_type="thread",
                target_id=thread_id,
                payload={"title": title, "mode": mode},
                created_at=now,
            )
        return self.get_phase4_thread(thread_id) or {}

    def list_phase4_threads(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_threads WHERE workspace_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC",
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_thread(dict(row), include_messages=False) for row in rows]

    def get_phase4_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_threads WHERE id = ? AND deleted_at IS NULL", (thread_id,)).fetchone()
            if not row:
                return None
            thread = self._normalize_phase4_thread(dict(row), include_messages=True)
            thread["messages"] = self.list_phase4_messages(thread_id)
            return thread

    def update_phase4_thread_metadata(
        self,
        thread_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        task_family: str | None = None,
        risk_level: str | None = None,
    ) -> dict[str, Any] | None:
        thread = self.get_phase4_thread(thread_id)
        if not thread:
            return None
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if metadata is not None:
            updates.append("metadata = ?")
            values.append(_as_json(metadata))
        if task_family is not None:
            updates.append("task_family = ?")
            values.append(task_family)
        if risk_level is not None:
            updates.append("risk_level = ?")
            values.append(risk_level)
        values.append(thread_id)
        with self._cursor() as cursor:
            cursor.execute("UPDATE phase4_threads SET " + ", ".join(updates) + " WHERE id = ?", values)
        return self.get_phase4_thread(thread_id)

    def update_phase4_thread_consent(
        self,
        *,
        thread_id: str,
        actor_user_id: str,
        trace_capture_level: str | None = None,
        training_eligible: bool | None = None,
        redaction_status: str | None = None,
    ) -> dict[str, Any] | None:
        thread = self.get_phase4_thread(thread_id)
        if not thread:
            return None
        now = _now()
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [now]
        changes: dict[str, dict[str, Any]] = {}

        if trace_capture_level is not None and trace_capture_level != thread["trace_capture_level"]:
            updates.append("trace_capture_level = ?")
            values.append(trace_capture_level)
            changes["trace_capture_level"] = {"from": thread["trace_capture_level"], "to": trace_capture_level}
        if training_eligible is not None and bool(training_eligible) != bool(thread["training_eligible"]):
            updates.append("training_eligible = ?")
            values.append(int(bool(training_eligible)))
            changes["training_eligible"] = {"from": bool(thread["training_eligible"]), "to": bool(training_eligible)}
        if redaction_status is not None and redaction_status != thread["redaction_status"]:
            updates.append("redaction_status = ?")
            values.append(redaction_status)
            changes["redaction_status"] = {"from": thread["redaction_status"], "to": redaction_status}

        if len(updates) == 1:
            return thread
        values.append(thread_id)
        with self._cursor() as cursor:
            cursor.execute("UPDATE phase4_threads SET " + ", ".join(updates) + " WHERE id = ?", values)
            self._insert_phase4_audit(
                cursor,
                event_type="training_consent.updated",
                actor_user_id=actor_user_id,
                organization_id=thread["organization_id"],
                workspace_id=thread["workspace_id"],
                target_type="thread",
                target_id=thread_id,
                payload={"changes": changes},
                created_at=now,
            )
        return self.get_phase4_thread(thread_id)

    def delete_phase4_thread(self, *, thread_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        thread = self.get_phase4_thread(thread_id)
        if not thread:
            return None
        now = _now()
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                UPDATE phase4_threads
                SET deleted_at = ?, status = 'deleted', training_eligible = 0, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                RETURNING *
                """,
                (now, now, thread_id),
            ).fetchone()
            if not row:
                return None
            deleted = self._normalize_phase4_thread(dict(row), include_messages=True)
            deleted["messages"] = self.list_phase4_messages(thread_id)
            self._insert_phase4_audit(
                cursor,
                event_type="thread.deleted",
                actor_user_id=deleted_by_user_id,
                organization_id=thread["organization_id"],
                workspace_id=thread["workspace_id"],
                target_type="thread",
                target_id=thread_id,
                payload={"message_count": len(thread.get("messages", [])), "training_eligible": False},
                created_at=now,
            )
            return deleted

    def _normalize_phase4_thread(self, raw: dict[str, Any], *, include_messages: bool) -> dict[str, Any]:
        out = {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "field_context_id": raw["field_context_id"],
            "title": raw["title"],
            "mode": raw["mode"],
            "task_family": raw["task_family"],
            "risk_level": raw["risk_level"],
            "model_profile_id": raw["model_profile_id"],
            "rag_config_id": raw["rag_config_id"],
            "trace_capture_level": raw["trace_capture_level"],
            "training_eligible": bool(raw["training_eligible"]),
            "redaction_status": raw["redaction_status"],
            "visibility": raw["visibility"],
            "status": raw["status"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
            "deleted_at": raw["deleted_at"],
        }
        if include_messages:
            out["messages"] = []
        return out

    def phase4_user_can_access_thread(self, user_id: str, thread_id: str) -> bool:
        thread = self.get_phase4_thread(thread_id)
        return bool(thread and self.phase4_user_can_access_workspace(user_id, thread["workspace_id"]))

    def create_phase4_message(
        self,
        *,
        thread: dict[str, Any],
        actor: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        message_id = self._new_uuid()
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) AS max_sequence FROM phase4_messages WHERE thread_id = ?",
                (thread["id"],),
            ).fetchone()
            sequence_no = int(row["max_sequence"]) + 1
            cursor.execute(
                """
                INSERT INTO phase4_messages(
                    id, organization_id, workspace_id, thread_id, actor, content, content_hash,
                    sequence_no, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    actor,
                    content,
                    str(uuid.uuid5(uuid.NAMESPACE_URL, content)),
                    sequence_no,
                    _as_json(metadata or {}),
                    now,
                ),
            )
            cursor.execute("UPDATE phase4_threads SET updated_at = ? WHERE id = ?", (now, thread["id"]))
        return self.get_phase4_message(message_id) or {}

    def get_phase4_message(self, message_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_messages WHERE id = ?", (message_id,)).fetchone()
            return self._normalize_phase4_message(dict(row)) if row else None

    def list_phase4_messages(self, thread_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_messages WHERE thread_id = ? ORDER BY sequence_no ASC",
                (thread_id,),
            ).fetchall()
            return [self._normalize_phase4_message(dict(row)) for row in rows]

    def _normalize_phase4_message(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "actor": raw["actor"],
            "content": raw["content"],
            "content_hash": raw["content_hash"],
            "sequence_no": raw["sequence_no"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
        }

    def append_phase4_trace_event(
        self,
        *,
        thread: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        actor: str | None = "system",
        message_id: str | None = None,
        prompt_hash: str | None = None,
        output_hash: str | None = None,
        source_hash: str | None = None,
        elapsed_ms: int | None = None,
    ) -> dict[str, Any]:
        now = _now()
        event_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_trace_events(
                    id, organization_id, workspace_id, thread_id, message_id, event_type, actor,
                    payload, prompt_hash, output_hash, source_hash, elapsed_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    message_id,
                    event_type,
                    actor,
                    _as_json(payload),
                    prompt_hash,
                    output_hash,
                    source_hash,
                    elapsed_ms,
                    now,
                ),
            )
        return self.get_phase4_trace_event(event_id) or {}

    def get_phase4_trace_event(self, event_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_trace_events WHERE id = ?", (event_id,)).fetchone()
            return self._normalize_phase4_trace_event(dict(row)) if row else None

    def list_phase4_trace_events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_trace_events WHERE thread_id = ? ORDER BY created_at ASC",
                (thread_id,),
            ).fetchall()
            return [self._normalize_phase4_trace_event(dict(row)) for row in rows]

    def _normalize_phase4_trace_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "message_id": raw["message_id"],
            "event_type": raw["event_type"],
            "actor": raw["actor"],
            "payload": _from_json(raw["payload"], {}),
            "hashes": {
                "prompt_hash": raw["prompt_hash"],
                "output_hash": raw["output_hash"],
                "source_hash": raw["source_hash"],
            },
            "elapsed_ms": raw["elapsed_ms"],
            "created_at": raw["created_at"],
        }

    def create_phase5_trace_spans(self, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not spans:
            return []
        now = _now()
        with self._cursor() as cursor:
            for span in spans:
                cursor.execute(
                    """
                    INSERT INTO agent_trace_spans(
                        trace_id, thread_id, turn_id, span_id, parent_span_id, stage,
                        start_ns, end_ns, duration_ms, status, error_type,
                        error_message_redacted, input_size, output_size,
                        token_estimate_in, token_estimate_out, cache_status,
                        component_version, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        span["trace_id"],
                        span.get("thread_id"),
                        span.get("turn_id"),
                        span["span_id"],
                        span.get("parent_span_id"),
                        span["stage"],
                        int(span["start_ns"]),
                        int(span["end_ns"]),
                        float(span["duration_ms"]),
                        span["status"],
                        span.get("error_type"),
                        span.get("error_message_redacted"),
                        span.get("input_size"),
                        span.get("output_size"),
                        span.get("token_estimate_in"),
                        span.get("token_estimate_out"),
                        span.get("cache_status"),
                        span.get("component_version"),
                        _as_json(span.get("metadata") or {}),
                        now,
                    ),
                )
        return self.list_phase5_trace_spans(str(spans[0]["trace_id"]))

    def create_phase5_turn_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO agent_turn_metrics(
                    trace_id, thread_id, turn_id, user_id, workspace_id,
                    route_question_type, risk_level, namespaces, required_tools,
                    rag_config_version, corpus_bundle_version, prompt_template_version,
                    context_packer_version, model_id, quantization, max_tokens,
                    temperature, top_p, top_k, total_latency_ms,
                    time_to_first_token_ms, decode_tokens_per_sec, prompt_tokens_est,
                    completion_tokens_est, context_tokens_est, retrieval_doc_count,
                    top_doc_score, source_diversity, required_support_rate,
                    tool_notes_count, tool_precision_proxy, tool_recall_proxy,
                    answer_word_count, leak_check_passed, risk_banner_present,
                    missing_data_present, quality_flags, user_feedback_score,
                    human_review_status, reflection_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics["trace_id"],
                    metrics["thread_id"],
                    metrics["turn_id"],
                    metrics.get("user_id"),
                    metrics.get("workspace_id"),
                    metrics.get("route_question_type"),
                    metrics.get("risk_level"),
                    _as_json(metrics.get("namespaces") or []),
                    _as_json(metrics.get("required_tools") or []),
                    metrics.get("rag_config_version"),
                    metrics.get("corpus_bundle_version"),
                    metrics.get("prompt_template_version"),
                    metrics.get("context_packer_version"),
                    metrics["model_id"],
                    metrics.get("quantization"),
                    int(metrics.get("max_tokens") or 0),
                    float(metrics.get("temperature") if metrics.get("temperature") is not None else 0.0),
                    float(metrics.get("top_p") if metrics.get("top_p") is not None else 0.9),
                    int(metrics.get("top_k") or 0),
                    float(metrics["total_latency_ms"]),
                    metrics.get("time_to_first_token_ms"),
                    metrics.get("decode_tokens_per_sec"),
                    metrics.get("prompt_tokens_est"),
                    metrics.get("completion_tokens_est"),
                    metrics.get("context_tokens_est"),
                    int(metrics.get("retrieval_doc_count") or 0),
                    metrics.get("top_doc_score"),
                    int(metrics.get("source_diversity") or 0),
                    metrics.get("required_support_rate"),
                    int(metrics.get("tool_notes_count") or 0),
                    metrics.get("tool_precision_proxy"),
                    metrics.get("tool_recall_proxy"),
                    int(metrics.get("answer_word_count") or 0),
                    int(bool(metrics.get("leak_check_passed"))),
                    int(bool(metrics.get("risk_banner_present"))),
                    int(bool(metrics.get("missing_data_present"))),
                    _as_json(metrics.get("quality_flags") or []),
                    metrics.get("user_feedback_score"),
                    metrics.get("human_review_status") or "unreviewed",
                    metrics.get("reflection_status") or "not_created",
                    now,
                ),
            )
        stored = self.get_phase5_turn_metrics(str(metrics["trace_id"]))
        if stored is None:
            raise RuntimeError("failed to persist Phase 5 turn metrics")
        return stored

    def create_phase5_prompt_leak_events(
        self,
        *,
        trace_id: str,
        thread_id: str | None,
        turn_id: str | None,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not findings:
            return []
        now = _now()
        with self._cursor() as cursor:
            for finding in findings:
                cursor.execute(
                    """
                    INSERT INTO prompt_leak_events(
                        trace_id, thread_id, turn_id, leak_class, matched_text_hash,
                        severity, reviewer_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace_id,
                        thread_id,
                        turn_id,
                        finding["leak_class"],
                        finding["matched_text_hash"],
                        finding["severity"],
                        finding.get("reviewer_status", "unreviewed"),
                        now,
                    ),
                )
        return self.list_phase5_prompt_leak_events(trace_id)

    def list_phase5_trace_spans(self, trace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM agent_trace_spans WHERE trace_id = ? ORDER BY start_ns ASC, id ASC",
                (trace_id,),
            ).fetchall()
            return [self._normalize_phase5_trace_span(dict(row)) for row in rows]

    def get_phase5_turn_metrics(self, trace_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM agent_turn_metrics WHERE trace_id = ?", (trace_id,)).fetchone()
            return self._normalize_phase5_turn_metrics(dict(row)) if row else None

    def list_phase5_turn_metrics(self, workspace_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM agent_turn_metrics WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, max(1, min(int(limit), 5000))),
            ).fetchall()
            return [self._normalize_phase5_turn_metrics(dict(row)) for row in rows]

    def update_phase5_turn_feedback(
        self,
        *,
        turn_id: str,
        user_feedback_score: float | None,
        human_review_status: str = "feedback_received",
    ) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE agent_turn_metrics
                SET user_feedback_score = ?, human_review_status = ?
                WHERE turn_id = ?
                """,
                (user_feedback_score, human_review_status, turn_id),
            )
            row = cursor.execute("SELECT * FROM agent_turn_metrics WHERE turn_id = ?", (turn_id,)).fetchone()
            return self._normalize_phase5_turn_metrics(dict(row)) if row else None

    def list_phase5_prompt_leak_events(self, trace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM prompt_leak_events WHERE trace_id = ? ORDER BY created_at ASC, id ASC",
                (trace_id,),
            ).fetchall()
            return [self._normalize_phase5_prompt_leak_event(dict(row)) for row in rows]

    def get_phase5_admin_trace(self, trace_id: str) -> dict[str, Any] | None:
        metrics = self.get_phase5_turn_metrics(trace_id)
        if not metrics:
            return None
        return {
            "trace_id": trace_id,
            "metrics": metrics,
            "spans": self.list_phase5_trace_spans(trace_id),
            "prompt_leak_events": self.list_phase5_prompt_leak_events(trace_id),
        }

    def _normalize_phase5_trace_span(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": raw["trace_id"],
            "thread_id": raw["thread_id"],
            "turn_id": raw["turn_id"],
            "span_id": raw["span_id"],
            "parent_span_id": raw["parent_span_id"],
            "stage": raw["stage"],
            "start_ns": raw["start_ns"],
            "end_ns": raw["end_ns"],
            "duration_ms": raw["duration_ms"],
            "status": raw["status"],
            "error_type": raw["error_type"],
            "error_message_redacted": raw["error_message_redacted"],
            "input_size": raw["input_size"],
            "output_size": raw["output_size"],
            "token_estimate_in": raw["token_estimate_in"],
            "token_estimate_out": raw["token_estimate_out"],
            "cache_status": raw["cache_status"],
            "component_version": raw["component_version"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
        }

    def _normalize_phase5_turn_metrics(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": raw["trace_id"],
            "thread_id": raw["thread_id"],
            "turn_id": raw["turn_id"],
            "user_id": raw["user_id"],
            "workspace_id": raw["workspace_id"],
            "route_question_type": raw["route_question_type"],
            "risk_level": raw["risk_level"],
            "namespaces": _from_json(raw["namespaces"], []),
            "required_tools": _from_json(raw["required_tools"], []),
            "rag_config_version": raw["rag_config_version"],
            "corpus_bundle_version": raw["corpus_bundle_version"],
            "prompt_template_version": raw["prompt_template_version"],
            "context_packer_version": raw["context_packer_version"],
            "model_id": raw["model_id"],
            "quantization": raw["quantization"],
            "max_tokens": int(raw.get("max_tokens") or 0),
            "temperature": float(raw.get("temperature") if raw.get("temperature") is not None else 0.0),
            "top_p": float(raw.get("top_p") if raw.get("top_p") is not None else 0.9),
            "top_k": int(raw.get("top_k") or 0),
            "total_latency_ms": raw["total_latency_ms"],
            "time_to_first_token_ms": raw["time_to_first_token_ms"],
            "decode_tokens_per_sec": raw["decode_tokens_per_sec"],
            "prompt_tokens_est": raw["prompt_tokens_est"],
            "completion_tokens_est": raw["completion_tokens_est"],
            "context_tokens_est": raw["context_tokens_est"],
            "retrieval_doc_count": raw["retrieval_doc_count"],
            "top_doc_score": raw["top_doc_score"],
            "source_diversity": raw["source_diversity"],
            "required_support_rate": raw["required_support_rate"],
            "tool_notes_count": raw["tool_notes_count"],
            "tool_precision_proxy": raw.get("tool_precision_proxy"),
            "tool_recall_proxy": raw.get("tool_recall_proxy"),
            "answer_word_count": raw["answer_word_count"],
            "leak_check_passed": bool(raw["leak_check_passed"]),
            "risk_banner_present": bool(raw["risk_banner_present"]),
            "missing_data_present": bool(raw["missing_data_present"]),
            "quality_flags": _from_json(raw["quality_flags"], []),
            "user_feedback_score": raw.get("user_feedback_score"),
            "human_review_status": raw.get("human_review_status") or "unreviewed",
            "reflection_status": raw.get("reflection_status") or "not_created",
            "created_at": raw["created_at"],
        }

    def _normalize_phase5_prompt_leak_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "trace_id": raw["trace_id"],
            "thread_id": raw["thread_id"],
            "turn_id": raw["turn_id"],
            "leak_class": raw["leak_class"],
            "matched_text_hash": raw["matched_text_hash"],
            "severity": raw["severity"],
            "reviewer_status": raw["reviewer_status"],
            "created_at": raw["created_at"],
        }

    def create_phase5_optimization_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        candidate_id = str(payload.get("candidate_id") or uuid.uuid4())
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO optimization_candidates(
                    candidate_id, workspace_id, created_by_user_id, candidate_type,
                    parent_version, candidate_version, generated_from_trace_ids,
                    reflection_summary, patch, eval_summary, rollback_plan,
                    pareto_status, promoted_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    payload.get("workspace_id"),
                    payload.get("created_by_user_id"),
                    payload["candidate_type"],
                    payload.get("parent_version"),
                    payload["candidate_version"],
                    _as_json(payload.get("generated_from_trace_ids") or []),
                    payload.get("reflection_summary"),
                    _as_json(payload.get("patch") or {}),
                    _as_json(payload.get("eval_summary") or {}),
                    payload.get("rollback_plan"),
                    payload.get("pareto_status", "pending"),
                    payload.get("promoted_at"),
                    now,
                ),
            )
        loaded = self.get_phase5_optimization_candidate(candidate_id)
        if loaded is None:
            raise RuntimeError("failed to persist Phase 5 optimization candidate")
        return loaded

    def get_phase5_optimization_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM optimization_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
            return self._normalize_phase5_optimization_candidate(dict(row)) if row else None

    def list_phase5_optimization_candidates(self, workspace_id: str, *, pareto_status: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            if pareto_status:
                rows = cursor.execute(
                    "SELECT * FROM optimization_candidates WHERE workspace_id = ? AND pareto_status = ? ORDER BY created_at DESC",
                    (workspace_id, pareto_status),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT * FROM optimization_candidates WHERE workspace_id = ? ORDER BY created_at DESC",
                    (workspace_id,),
                ).fetchall()
            return [self._normalize_phase5_optimization_candidate(dict(row)) for row in rows]

    def update_phase5_optimization_candidate_status(
        self,
        candidate_id: str,
        *,
        pareto_status: str,
        promoted_at: str | None = None,
        eval_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE optimization_candidates
                SET pareto_status = ?,
                    promoted_at = ?,
                    eval_summary = COALESCE(?, eval_summary)
                WHERE candidate_id = ?
                """,
                (
                    pareto_status,
                    promoted_at,
                    _as_json(eval_summary) if eval_summary is not None else None,
                    candidate_id,
                ),
            )
        return self.get_phase5_optimization_candidate(candidate_id)

    def create_phase5_training_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        candidate_id = str(payload.get("id") or uuid.uuid4())
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO phase5_training_candidates(
                    id, workspace_id, thread_id, trace_id, reviewer_user_id,
                    review_status, consent_scope, redaction_status, repair_layer,
                    failure_class, messages, labels, dataset_card, created_at,
                    reviewed_at, exported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    payload["workspace_id"],
                    payload["thread_id"],
                    payload["trace_id"],
                    payload.get("reviewer_user_id"),
                    payload.get("review_status", "pending"),
                    payload["consent_scope"],
                    payload.get("redaction_status", "redacted"),
                    payload.get("repair_layer"),
                    payload.get("failure_class"),
                    _as_json(payload.get("messages") or []),
                    _as_json(payload.get("labels") or {}),
                    _as_json(payload.get("dataset_card") or {}),
                    payload.get("created_at") or now,
                    payload.get("reviewed_at"),
                    payload.get("exported_at"),
                ),
            )
        loaded = self.get_phase5_training_candidate(candidate_id)
        if loaded is None:
            raise RuntimeError("failed to persist Phase 5 training candidate")
        return loaded

    def get_phase5_training_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase5_training_candidates WHERE id = ?", (candidate_id,)).fetchone()
            return self._normalize_phase5_training_candidate(dict(row)) if row else None

    def list_phase5_training_candidates(self, workspace_id: str, *, review_status: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            if review_status:
                rows = cursor.execute(
                    "SELECT * FROM phase5_training_candidates WHERE workspace_id = ? AND review_status = ? ORDER BY created_at DESC",
                    (workspace_id, review_status),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT * FROM phase5_training_candidates WHERE workspace_id = ? ORDER BY created_at DESC",
                    (workspace_id,),
                ).fetchall()
            return [self._normalize_phase5_training_candidate(dict(row)) for row in rows]

    def update_phase5_training_candidate_review(
        self,
        candidate_id: str,
        *,
        review_status: str,
        reviewer_user_id: str,
        labels: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_phase5_training_candidate(candidate_id)
        if not current:
            return None
        merged_labels = {**current.get("labels", {}), **(labels or {})}
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase5_training_candidates
                SET review_status = ?, reviewer_user_id = ?, labels = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (review_status, reviewer_user_id, _as_json(merged_labels), _now(), candidate_id),
            )
        return self.get_phase5_training_candidate(candidate_id)

    def mark_phase5_training_candidates_exported(self, candidate_ids: list[str]) -> None:
        if not candidate_ids:
            return
        with self._cursor() as cursor:
            cursor.executemany(
                "UPDATE phase5_training_candidates SET exported_at = ? WHERE id = ?",
                [(_now(), candidate_id) for candidate_id in candidate_ids],
            )

    def upsert_phase5_adapter_registry(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row_id = str(payload.get("id") or uuid.uuid4())
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase5_adapter_registry(
                    id, workspace_id, adapter_id, base_model_id, method, status,
                    artifact_uri, eval_summary, rollback_plan, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(adapter_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    base_model_id = excluded.base_model_id,
                    method = excluded.method,
                    status = excluded.status,
                    artifact_uri = excluded.artifact_uri,
                    eval_summary = excluded.eval_summary,
                    rollback_plan = excluded.rollback_plan,
                    updated_at = excluded.updated_at
                """,
                (
                    row_id,
                    payload.get("workspace_id"),
                    payload["adapter_id"],
                    payload["base_model_id"],
                    payload["method"],
                    payload.get("status", "planned"),
                    payload.get("artifact_uri"),
                    _as_json(payload.get("eval_summary") or {}),
                    payload["rollback_plan"],
                    now,
                    now,
                ),
            )
        return self.get_phase5_adapter_registry(payload["adapter_id"]) or {}

    def get_phase5_adapter_registry(self, adapter_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase5_adapter_registry WHERE adapter_id = ?", (adapter_id,)).fetchone()
            return self._normalize_phase5_adapter_registry(dict(row)) if row else None

    def list_phase5_adapter_registry(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            if workspace_id:
                rows = cursor.execute(
                    "SELECT * FROM phase5_adapter_registry WHERE workspace_id = ? OR workspace_id IS NULL ORDER BY updated_at DESC",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = cursor.execute("SELECT * FROM phase5_adapter_registry ORDER BY updated_at DESC").fetchall()
            return [self._normalize_phase5_adapter_registry(dict(row)) for row in rows]

    def upsert_phase5_model_registry(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row_id = str(payload.get("id") or uuid.uuid4())
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase5_model_registry(
                    id, workspace_id, model_id, quantization, context_window,
                    hardware_profile, license, latency_profile, eval_profile,
                    release_status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, model_id) DO UPDATE SET
                    quantization = excluded.quantization,
                    context_window = excluded.context_window,
                    hardware_profile = excluded.hardware_profile,
                    license = excluded.license,
                    latency_profile = excluded.latency_profile,
                    eval_profile = excluded.eval_profile,
                    release_status = excluded.release_status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    row_id,
                    payload["workspace_id"],
                    payload["model_id"],
                    payload["quantization"],
                    int(payload["context_window"]),
                    payload["hardware_profile"],
                    payload["license"],
                    _as_json(payload.get("latency_profile") or {}),
                    _as_json(payload.get("eval_profile") or {}),
                    payload.get("release_status", "candidate"),
                    payload.get("notes"),
                    now,
                    now,
                ),
            )
        return self.get_phase5_model_registry(payload["workspace_id"], payload["model_id"]) or {}

    def get_phase5_model_registry(self, workspace_id: str, model_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM phase5_model_registry WHERE workspace_id = ? AND model_id = ?",
                (workspace_id, model_id),
            ).fetchone()
            return self._normalize_phase5_model_registry(dict(row)) if row else None

    def list_phase5_model_registry(self, workspace_id: str, *, release_status: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            if release_status:
                rows = cursor.execute(
                    "SELECT * FROM phase5_model_registry WHERE workspace_id = ? AND release_status = ? ORDER BY updated_at DESC",
                    (workspace_id, release_status),
                ).fetchall()
            else:
                rows = cursor.execute(
                    "SELECT * FROM phase5_model_registry WHERE workspace_id = ? ORDER BY updated_at DESC",
                    (workspace_id,),
                ).fetchall()
            return [self._normalize_phase5_model_registry(dict(row)) for row in rows]

    def create_knowledge_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row_id = str(payload.get("id") or self._new_id("ksrc"))
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_sources(
                    id, workspace_id, source_id, title, owner, visibility,
                    license_status, canonical_url, artifact_path, checksum_sha256,
                    source_kind, rag_eligible, sft_eligible, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, source_id) DO UPDATE SET
                    title = excluded.title,
                    owner = excluded.owner,
                    visibility = excluded.visibility,
                    license_status = excluded.license_status,
                    canonical_url = excluded.canonical_url,
                    artifact_path = excluded.artifact_path,
                    checksum_sha256 = excluded.checksum_sha256,
                    source_kind = excluded.source_kind,
                    rag_eligible = excluded.rag_eligible,
                    sft_eligible = excluded.sft_eligible,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    row_id,
                    payload.get("workspace_id"),
                    payload["source_id"],
                    payload["title"],
                    payload.get("owner", "unknown"),
                    payload.get("visibility", "public"),
                    payload.get("license_status", "review_required"),
                    payload.get("canonical_url"),
                    payload.get("artifact_path"),
                    payload.get("checksum_sha256"),
                    payload.get("source_kind"),
                    int(bool(payload.get("rag_eligible", True))),
                    int(bool(payload.get("sft_eligible", False))),
                    _as_json(payload.get("metadata") or {}),
                    now,
                    now,
                ),
            )
        return self.get_knowledge_source(payload.get("workspace_id"), payload["source_id"]) or {}

    def get_knowledge_source(self, workspace_id: str | None, source_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM knowledge_sources WHERE workspace_id IS ? AND source_id = ?",
                (workspace_id, source_id),
            ).fetchone()
            return self._normalize_knowledge_source(dict(row)) if row else None

    def create_knowledge_ingest_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row_id = str(payload.get("id") or self._new_id("kjob"))
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_ingest_jobs(
                    id, source_id, status, runtime, reader, chunking_strategy,
                    embedder_profile, knowledge_base, contents_table, vector_table,
                    chunk_count, duplicate_of_source_id, error_message,
                    started_at, finished_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    payload["source_id"],
                    payload.get("status", "queued"),
                    payload.get("runtime", "agno_knowledge"),
                    payload["reader"],
                    payload["chunking_strategy"],
                    payload["embedder_profile"],
                    payload["knowledge_base"],
                    payload["contents_table"],
                    payload["vector_table"],
                    int(payload.get("chunk_count", 0)),
                    payload.get("duplicate_of_source_id"),
                    payload.get("error_message"),
                    payload.get("started_at"),
                    payload.get("finished_at"),
                    now,
                    now,
                ),
            )
            row = cursor.execute("SELECT * FROM knowledge_ingest_jobs WHERE id = ?", (row_id,)).fetchone()
            return self._normalize_knowledge_ingest_job(dict(row))

    def list_knowledge_ingest_jobs(self, *, source_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        where = "WHERE source_id = ?" if source_id else ""
        params: list[Any] = [source_id] if source_id else []
        params.append(max(1, min(int(limit), 500)))
        with self._cursor() as cursor:
            rows = cursor.execute(
                f"""
                SELECT * FROM knowledge_ingest_jobs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [self._normalize_knowledge_ingest_job(dict(row)) for row in rows]

    def create_knowledge_source_version(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row_id = str(payload.get("id") or self._new_id("kver"))
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_source_versions(
                    id, source_id, checksum_sha256, canonical_url, artifact_path,
                    status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    payload["source_id"],
                    payload["checksum_sha256"],
                    payload.get("canonical_url"),
                    payload.get("artifact_path"),
                    payload["status"],
                    _as_json(payload.get("metadata") or {}),
                    now,
                ),
            )
            row = cursor.execute("SELECT * FROM knowledge_source_versions WHERE id = ?", (row_id,)).fetchone()
            return self._normalize_knowledge_source_version(dict(row))

    def list_knowledge_source_versions(self, source_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM knowledge_source_versions
                WHERE source_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (source_id, max(1, min(int(limit), 500))),
            ).fetchall()
            return [self._normalize_knowledge_source_version(dict(row)) for row in rows]

    def create_knowledge_chunk_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row_id = str(payload.get("id") or self._new_id("kreview"))
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_chunk_reviews(
                    id, source_id, chunk_id, reviewer_status, rejection_reasons,
                    evidence_coordinates, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    payload["source_id"],
                    payload["chunk_id"],
                    payload.get("reviewer_status", "pending"),
                    _as_json(payload.get("rejection_reasons") or []),
                    _as_json(payload.get("evidence_coordinates") or {}),
                    now,
                    now,
                ),
            )
            row = cursor.execute("SELECT * FROM knowledge_chunk_reviews WHERE id = ?", (row_id,)).fetchone()
            return self._normalize_knowledge_chunk_review(dict(row))

    def list_knowledge_chunk_reviews(self, source_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM knowledge_chunk_reviews
                WHERE source_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (source_id, max(1, min(int(limit), 500))),
            ).fetchall()
            return [self._normalize_knowledge_chunk_review(dict(row)) for row in rows]

    def _normalize_phase5_optimization_candidate(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": raw["candidate_id"],
            "workspace_id": raw.get("workspace_id"),
            "created_by_user_id": raw.get("created_by_user_id"),
            "candidate_type": raw["candidate_type"],
            "parent_version": raw.get("parent_version"),
            "candidate_version": raw["candidate_version"],
            "generated_from_trace_ids": _from_json(raw.get("generated_from_trace_ids"), []),
            "reflection_summary": raw.get("reflection_summary"),
            "patch": _from_json(raw.get("patch"), {}),
            "eval_summary": _from_json(raw.get("eval_summary"), {}),
            "rollback_plan": raw.get("rollback_plan"),
            "pareto_status": raw.get("pareto_status"),
            "promoted_at": raw.get("promoted_at"),
            "created_at": raw.get("created_at"),
        }

    def _normalize_knowledge_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "workspace_id": raw.get("workspace_id"),
            "source_id": raw["source_id"],
            "title": raw["title"],
            "owner": raw["owner"],
            "visibility": raw["visibility"],
            "license_status": raw["license_status"],
            "canonical_url": raw.get("canonical_url"),
            "artifact_path": raw.get("artifact_path"),
            "checksum_sha256": raw.get("checksum_sha256"),
            "source_kind": raw.get("source_kind"),
            "rag_eligible": bool(raw.get("rag_eligible")),
            "sft_eligible": bool(raw.get("sft_eligible")),
            "metadata": _from_json(raw.get("metadata_json"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_knowledge_ingest_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "source_id": raw["source_id"],
            "status": raw["status"],
            "runtime": raw["runtime"],
            "reader": raw["reader"],
            "chunking_strategy": raw["chunking_strategy"],
            "embedder_profile": raw["embedder_profile"],
            "knowledge_base": raw["knowledge_base"],
            "contents_table": raw["contents_table"],
            "vector_table": raw["vector_table"],
            "chunk_count": raw.get("chunk_count"),
            "duplicate_of_source_id": raw.get("duplicate_of_source_id"),
            "error_message": raw.get("error_message"),
            "started_at": raw.get("started_at"),
            "finished_at": raw.get("finished_at"),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_knowledge_source_version(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "source_id": raw["source_id"],
            "checksum_sha256": raw["checksum_sha256"],
            "canonical_url": raw.get("canonical_url"),
            "artifact_path": raw.get("artifact_path"),
            "status": raw["status"],
            "metadata": _from_json(raw.get("metadata_json"), {}),
            "created_at": raw.get("created_at"),
        }

    def _normalize_knowledge_chunk_review(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "source_id": raw["source_id"],
            "chunk_id": raw["chunk_id"],
            "reviewer_status": raw["reviewer_status"],
            "rejection_reasons": _from_json(raw.get("rejection_reasons"), []),
            "evidence_coordinates": _from_json(raw.get("evidence_coordinates"), {}),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_phase5_training_candidate(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "trace_id": raw["trace_id"],
            "reviewer_user_id": raw.get("reviewer_user_id"),
            "review_status": raw["review_status"],
            "consent_scope": raw["consent_scope"],
            "redaction_status": raw["redaction_status"],
            "repair_layer": raw.get("repair_layer"),
            "failure_class": raw.get("failure_class"),
            "messages": _from_json(raw.get("messages"), []),
            "labels": _from_json(raw.get("labels"), {}),
            "dataset_card": _from_json(raw.get("dataset_card"), {}),
            "created_at": raw.get("created_at"),
            "reviewed_at": raw.get("reviewed_at"),
            "exported_at": raw.get("exported_at"),
        }

    def _normalize_phase5_adapter_registry(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "workspace_id": raw.get("workspace_id"),
            "adapter_id": raw["adapter_id"],
            "base_model_id": raw["base_model_id"],
            "method": raw["method"],
            "status": raw["status"],
            "artifact_uri": raw.get("artifact_uri"),
            "eval_summary": _from_json(raw.get("eval_summary"), {}),
            "rollback_plan": raw["rollback_plan"],
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def _normalize_phase5_model_registry(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "workspace_id": raw["workspace_id"],
            "model_id": raw["model_id"],
            "quantization": raw["quantization"],
            "context_window": int(raw["context_window"]),
            "hardware_profile": raw["hardware_profile"],
            "license": raw["license"],
            "latency_profile": _from_json(raw.get("latency_profile"), {}),
            "eval_profile": _from_json(raw.get("eval_profile"), {}),
            "release_status": raw["release_status"],
            "notes": raw.get("notes"),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def create_phase4_feedback(
        self,
        *,
        thread: dict[str, Any],
        message_id: str,
        created_by_user_id: str,
        rating: str,
        failure_tags: list[str],
        human_correction: str | None = None,
        ideal_answer: str | None = None,
        training_consent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        feedback_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_feedback_events(
                    id, organization_id, workspace_id, thread_id, message_id, created_by_user_id,
                    rating, failure_tags, human_correction, ideal_answer, training_consent, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    message_id,
                    created_by_user_id,
                    rating,
                    _as_json(failure_tags),
                    human_correction,
                    ideal_answer,
                    int(bool(training_consent)),
                    _as_json(metadata or {}),
                    now,
                ),
            )
        feedback = self.get_phase4_feedback(feedback_id) or {}
        self.append_phase4_trace_event(
            thread=thread,
            event_type="user_feedback",
            actor="user",
            message_id=message_id,
            payload=feedback,
        )
        return feedback

    def get_phase4_feedback(self, feedback_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_feedback_events WHERE id = ?", (feedback_id,)).fetchone()
            return self._normalize_phase4_feedback(dict(row)) if row else None

    def list_phase4_feedback_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_feedback_events WHERE thread_id = ? ORDER BY created_at ASC",
                (thread_id,),
            ).fetchall()
            return [self._normalize_phase4_feedback(dict(row)) for row in rows]

    def _normalize_phase4_feedback(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "message_id": raw["message_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "rating": raw["rating"],
            "failure_tags": _from_json(raw["failure_tags"], []),
            "human_correction": raw["human_correction"],
            "ideal_answer": raw["ideal_answer"],
            "training_consent": bool(raw["training_consent"]),
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
        }

    def create_phase4_reflection_candidate(
        self,
        *,
        thread: dict[str, Any],
        created_by_user_id: str,
        target_component: str,
        lesson: str,
        candidate_rule: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        reflection_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_reflection_candidates(
                    id, organization_id, workspace_id, thread_id, target_component, lesson,
                    candidate_rule, evidence, status, created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reflection_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    target_component,
                    lesson,
                    candidate_rule,
                    _as_json(evidence or {}),
                    "candidate",
                    created_by_user_id,
                    now,
                ),
            )
        reflection = self.get_phase4_reflection(reflection_id) or {}
        self.append_phase4_trace_event(
            thread=thread,
            event_type="reflection_candidate",
            actor="system",
            payload=reflection,
        )
        return reflection

    def get_phase4_reflection(self, reflection_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_reflection_candidates WHERE id = ?", (reflection_id,)).fetchone()
            return self._normalize_phase4_reflection(dict(row)) if row else None

    def update_phase4_reflection_status(self, *, reflection_id: str, reviewed_by_user_id: str, status: str) -> dict[str, Any] | None:
        reflection = self.get_phase4_reflection(reflection_id)
        if not reflection:
            return None
        reviewed_at = _now()
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE phase4_reflection_candidates SET status = ?, reviewed_by_user_id = ?, reviewed_at = ? WHERE id = ?",
                (status, reviewed_by_user_id, reviewed_at, reflection_id),
            )
        updated = self.get_phase4_reflection(reflection_id)
        thread = self.get_phase4_thread(reflection["thread_id"]) if reflection.get("thread_id") else None
        if thread and updated:
            self.append_phase4_trace_event(
                thread=thread,
                event_type="reflection_review",
                actor="reviewer",
                payload=updated,
            )
        return updated

    def _normalize_phase4_reflection(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "memory_id": raw["id"],
            "id": raw["id"],
            "schema_version": "phase4.reflection_memory.v1",
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "target_component": raw["target_component"],
            "lesson": raw["lesson"],
            "candidate_rule": raw["candidate_rule"],
            "source_thread_ids": [raw["thread_id"]] if raw["thread_id"] else [],
            "evidence": _from_json(raw["evidence"], {}),
            "status": raw["status"],
            "scope": "workspace",
            "created_by_user_id": raw["created_by_user_id"],
            "reviewed_by_user_id": raw["reviewed_by_user_id"],
            "created_at": raw["created_at"],
            "reviewed_at": raw["reviewed_at"],
        }

    def create_phase4_attachment(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        payload: dict[str, Any],
        storage_uri: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        now = _now()
        attachment_id = self._new_uuid()
        text_content = str(payload.get("text_content") or "")
        chunks = [text_content[index : index + 1200] for index in range(0, len(text_content), 1200)] if text_content.strip() else []
        metadata = {
            "retention_policy": payload.get("retention_policy", "delete_on_request"),
            "scan_status": "passed_local_stub",
            "parse_method": (
                "image_metadata_stub"
                if str(payload.get("content_type", "")).startswith("image/")
                else "local_pdf_text_stub"
                if payload.get("content_type") == "application/pdf"
                else "plain_text"
            ),
            "chunk_count": len(chunks),
            "embedding_status": "metadata_only_local_stub",
            "private_rag_scope": "workspace",
        }
        metadata.update(payload.get("metadata") or {})
        if str(payload.get("content_type", "")).startswith("image/"):
            parse_status = "image_staged"
        elif payload.get("content_type") == "application/pdf":
            parse_status = "private_indexed" if chunks else "parse_blocked"
        else:
            parse_status = "private_indexed"
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_attachments(
                    id, organization_id, workspace_id, thread_id, message_id, created_by_user_id,
                    filename, content_type, storage_uri, size_bytes, sha256, modality, sensitivity,
                    parse_status, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    workspace["organization_id"],
                    workspace["id"],
                    payload.get("thread_id"),
                    payload.get("message_id"),
                    created_by_user_id,
                    payload["filename"],
                    payload["content_type"],
                    storage_uri,
                    size_bytes,
                    sha256,
                    payload.get("modality", "text"),
                    payload.get("sensitivity", "medium"),
                    parse_status,
                    _as_json(metadata),
                    now,
                ),
            )
            for index, chunk_text in enumerate(chunks):
                chunk_id = self._new_uuid()
                cursor.execute(
                    """
                    INSERT INTO phase4_document_chunks(
                        id, organization_id, workspace_id, attachment_id, source_doc_id,
                        chunk_index, title, text_content, license_state, training_eligible,
                        visibility, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        workspace["organization_id"],
                        workspace["id"],
                        attachment_id,
                        attachment_id,
                        index,
                        payload["filename"],
                        chunk_text,
                        "user_workspace_private",
                        0,
                        "private",
                        _as_json({"text_len": len(chunk_text), "local_index_stub": True}),
                        now,
                    ),
                )
                embedding_vector = _local_text_embedding(chunk_text)
                cursor.execute(
                    """
                    INSERT INTO phase4_embeddings(
                        id, organization_id, workspace_id, chunk_id, attachment_id,
                        source_kind, source_id, modality, encoder_name, encoder_version,
                        dimensions, vector, license_state, training_eligible, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_uuid(),
                        workspace["organization_id"],
                        workspace["id"],
                        chunk_id,
                        attachment_id,
                        "user_upload",
                        attachment_id,
                        payload.get("modality", "text"),
                        "local-hash-bow",
                        "v1",
                        len(embedding_vector),
                        _as_json(embedding_vector),
                        "user_workspace_private",
                        0,
                        _as_json({"chunk_index": index, "embedding_status": "computed_local_hash_bow"}),
                        now,
                    ),
                )
            image_fingerprint = (metadata.get("image") or {}).get("fingerprint") or {}
            if image_fingerprint:
                embedding_vector = _local_text_embedding(text_content)
                cursor.execute(
                    """
                    INSERT INTO phase4_embeddings(
                        id, organization_id, workspace_id, chunk_id, attachment_id,
                        source_kind, source_id, modality, encoder_name, encoder_version,
                        dimensions, vector, license_state, training_eligible, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_uuid(),
                        workspace["organization_id"],
                        workspace["id"],
                        None,
                        attachment_id,
                        "user_upload",
                        attachment_id,
                        payload.get("modality", "image"),
                        "local-image-fingerprint-stub",
                        "v0",
                        int(image_fingerprint.get("dimensions") or 0),
                        _as_json(image_fingerprint.get("vector") or []),
                        "user_workspace_private",
                        0,
                        _as_json(
                            {
                                "embedding_status": "metadata_only_local_stub",
                                "fingerprint_hash": image_fingerprint.get("hash"),
                                "algorithm": image_fingerprint.get("algorithm"),
                                "filters": metadata.get("filters", {}),
                            },
                        ),
                        now,
                    ),
                )
            self._insert_phase4_audit(
                cursor,
                event_type="attachment.created",
                actor_user_id=created_by_user_id,
                organization_id=workspace["organization_id"],
                workspace_id=workspace["id"],
                target_type="attachment",
                target_id=attachment_id,
                payload={"filename": payload["filename"], "size_bytes": size_bytes, "chunk_count": len(chunks)},
                created_at=now,
            )
        return self.get_phase4_attachment(attachment_id) or {}

    def list_phase4_attachments(self, workspace_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
            rows = cursor.execute(
                f"""
                SELECT * FROM phase4_attachments
                WHERE workspace_id = ? {deleted_filter}
                ORDER BY created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_attachment(dict(row)) for row in rows]

    def get_phase4_attachment(self, attachment_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
            row = cursor.execute(
                f"SELECT * FROM phase4_attachments WHERE id = ? {deleted_filter}",
                (attachment_id,),
            ).fetchone()
            return self._normalize_phase4_attachment(dict(row)) if row else None

    def delete_phase4_attachment(self, *, attachment_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        attachment = self.get_phase4_attachment(attachment_id)
        if not attachment:
            return None
        now = _now()
        with self._cursor() as cursor:
            cursor.execute("UPDATE phase4_attachments SET deleted_at = ?, parse_status = ? WHERE id = ?", (now, "deleted", attachment_id))
            cursor.execute("UPDATE phase4_document_chunks SET deleted_at = ? WHERE attachment_id = ?", (now, attachment_id))
            cursor.execute("UPDATE phase4_embeddings SET deleted_at = ? WHERE attachment_id = ?", (now, attachment_id))
            self._insert_phase4_audit(
                cursor,
                event_type="attachment.deleted",
                actor_user_id=deleted_by_user_id,
                organization_id=attachment["organization_id"],
                workspace_id=attachment["workspace_id"],
                target_type="attachment",
                target_id=attachment_id,
                payload={"filename": attachment["filename"], "derived_chunks_tombstoned": True, "derived_embeddings_tombstoned": True},
                created_at=now,
            )
        return self.get_phase4_attachment(attachment_id, include_deleted=True)

    def list_phase4_attachment_chunks(self, attachment_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_document_chunks
                WHERE attachment_id = ? AND deleted_at IS NULL
                ORDER BY chunk_index ASC
                """,
                (attachment_id,),
            ).fetchall()
            return [self._normalize_phase4_document_chunk(dict(row)) for row in rows]

    def list_phase4_attachment_chunks_with_embeddings(self, attachment_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT c.*, e.vector AS embedding_vector, e.encoder_name, e.encoder_version, e.dimensions AS embedding_dimensions,
                       e.metadata AS embedding_metadata
                FROM phase4_document_chunks c
                LEFT JOIN phase4_embeddings e ON e.chunk_id = c.id AND e.deleted_at IS NULL
                WHERE c.attachment_id = ? AND c.deleted_at IS NULL
                ORDER BY c.chunk_index ASC
                """,
                (attachment_id,),
            ).fetchall()
            chunks: list[dict[str, Any]] = []
            for row in rows:
                raw = dict(row)
                chunk = self._normalize_phase4_document_chunk(raw)
                chunk["embedding"] = {
                    "vector": _from_json(raw.get("embedding_vector"), []),
                    "encoder_name": raw.get("encoder_name"),
                    "encoder_version": raw.get("encoder_version"),
                    "dimensions": raw.get("embedding_dimensions"),
                    "metadata": _from_json(raw.get("embedding_metadata"), {}),
                }
                chunks.append(chunk)
            return chunks

    def list_phase4_data_source_chunks_with_embeddings(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT c.*, e.vector AS embedding_vector, e.encoder_name, e.encoder_version,
                       e.dimensions AS embedding_dimensions, e.metadata AS embedding_metadata,
                       s.source_id AS registered_source_id, s.publisher, s.source_kind,
                       s.crops, s.regions, s.buckets, s.rag_eligible,
                       s.metadata AS data_source_metadata
                FROM phase4_document_chunks c
                JOIN phase4_data_sources s
                  ON s.id = c.data_source_id AND s.deleted_at IS NULL
                LEFT JOIN phase4_embeddings e
                  ON e.chunk_id = c.id AND e.deleted_at IS NULL
                WHERE c.workspace_id = ?
                  AND c.data_source_id IS NOT NULL
                  AND c.deleted_at IS NULL
                  AND s.rag_eligible = 1
                ORDER BY s.updated_at DESC, c.chunk_index ASC
                """,
                (workspace_id,),
            ).fetchall()
            chunks: list[dict[str, Any]] = []
            for row in rows:
                raw = dict(row)
                chunk = self._normalize_phase4_document_chunk(raw)
                chunk["embedding"] = {
                    "vector": _from_json(raw.get("embedding_vector"), []),
                    "encoder_name": raw.get("encoder_name"),
                    "encoder_version": raw.get("encoder_version"),
                    "dimensions": raw.get("embedding_dimensions"),
                    "metadata": _from_json(raw.get("embedding_metadata"), {}),
                }
                chunk["data_source"] = {
                    "source_id": raw.get("registered_source_id"),
                    "publisher": raw.get("publisher"),
                    "source_kind": raw.get("source_kind"),
                    "crops": _from_json(raw.get("crops"), []),
                    "regions": _from_json(raw.get("regions"), []),
                    "buckets": _from_json(raw.get("buckets"), []),
                    "rag_eligible": bool(raw.get("rag_eligible")),
                    "metadata": _from_json(raw.get("data_source_metadata"), {}),
                }
                chunks.append(chunk)
            return chunks

    def create_phase4_embedding_job(
        self,
        *,
        attachment: dict[str, Any],
        created_by_user_id: str,
        queue_name: str = "embedding",
    ) -> dict[str, Any]:
        now = _now()
        job_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_embedding_jobs(
                    id, organization_id, workspace_id, attachment_id, created_by_user_id,
                    job_type, status, queue_name, result, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    attachment["organization_id"],
                    attachment["workspace_id"],
                    attachment["id"],
                    created_by_user_id,
                    "attachment_embedding_reindex",
                    "queued",
                    queue_name,
                    _as_json({}),
                    now,
                ),
            )
        return self.get_phase4_embedding_job(job_id) or {}

    def get_phase4_embedding_job(self, job_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_embedding_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._normalize_phase4_embedding_job(dict(row)) if row else None

    def list_phase4_queued_embedding_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_embedding_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._normalize_phase4_embedding_job(dict(row)) for row in rows]

    def update_phase4_embedding_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.get_phase4_embedding_job(job_id)
        if not job:
            return None
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_embedding_jobs
                SET status = ?, result = ?, error_message = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    _as_json(job.get("result", {}) if result is None else result),
                    error_message,
                    started_at,
                    finished_at,
                    job_id,
                ),
            )
        return self.get_phase4_embedding_job(job_id)

    def _normalize_phase4_embedding_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "attachment_id": raw["attachment_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "job_type": raw["job_type"],
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "error_message": raw["error_message"],
            "result": _from_json(raw["result"], {}),
            "created_at": raw["created_at"],
            "started_at": raw["started_at"],
            "finished_at": raw["finished_at"],
        }

    def create_phase4_image_job(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        question: str,
        attachment_ids: list[str],
        thread_id: str | None = None,
        crop: str | None = None,
        region: str | None = None,
        queue_name: str = "image",
    ) -> dict[str, Any]:
        now = _now()
        job_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_image_jobs(
                    id, organization_id, workspace_id, thread_id, created_by_user_id,
                    question, crop, region, attachment_ids, status, queue_name, result, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    workspace["organization_id"],
                    workspace["id"],
                    thread_id,
                    created_by_user_id,
                    question,
                    crop,
                    region,
                    _as_json(attachment_ids),
                    "queued",
                    queue_name,
                    _as_json({}),
                    now,
                ),
            )
        return self.get_phase4_image_job(job_id) or {}

    def get_phase4_image_job(self, job_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_image_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._normalize_phase4_image_job(dict(row)) if row else None

    def list_phase4_queued_image_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_image_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._normalize_phase4_image_job(dict(row)) for row in rows]

    def update_phase4_image_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.get_phase4_image_job(job_id)
        if not job:
            return None
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_image_jobs
                SET status = ?, result = ?, error_message = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    _as_json(job.get("result", {}) if result is None else result),
                    error_message,
                    started_at,
                    finished_at,
                    job_id,
                ),
            )
        return self.get_phase4_image_job(job_id)

    def _normalize_phase4_image_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "question": raw["question"],
            "crop": raw["crop"],
            "region": raw["region"],
            "attachment_ids": _from_json(raw["attachment_ids"], []),
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "error_message": raw["error_message"],
            "result": _from_json(raw["result"], {}),
            "created_at": raw["created_at"],
            "started_at": raw["started_at"],
            "finished_at": raw["finished_at"],
        }

    def list_phase4_image_embeddings(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT e.*, a.filename, a.content_type, a.metadata AS attachment_metadata
                FROM phase4_embeddings e
                JOIN phase4_attachments a ON a.id = e.attachment_id
                WHERE e.workspace_id = ?
                  AND e.deleted_at IS NULL
                  AND a.deleted_at IS NULL
                  AND e.modality IN ('image', 'multimodal')
                ORDER BY e.created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_embedding(dict(row)) for row in rows]

    def replace_phase4_attachment_embeddings(self, attachment_id: str, *, worker_name: str = "local_worker") -> dict[str, Any]:
        attachment = self.get_phase4_attachment(attachment_id)
        if not attachment:
            raise ValueError(f"attachment not found: {attachment_id}")
        now = _now()
        metadata = dict(attachment.get("metadata") or {})
        text_count = 0
        image_count = 0
        with self._cursor() as cursor:
            cursor.execute("UPDATE phase4_embeddings SET deleted_at = ? WHERE attachment_id = ? AND deleted_at IS NULL", (now, attachment_id))
            chunk_rows = cursor.execute(
                """
                SELECT * FROM phase4_document_chunks
                WHERE attachment_id = ? AND deleted_at IS NULL
                ORDER BY chunk_index ASC
                """,
                (attachment_id,),
            ).fetchall()
            for row in chunk_rows:
                chunk = dict(row)
                embedding_vector = _local_text_embedding(chunk["text_content"])
                cursor.execute(
                    """
                    INSERT INTO phase4_embeddings(
                        id, organization_id, workspace_id, chunk_id, attachment_id,
                        source_kind, source_id, modality, encoder_name, encoder_version,
                        dimensions, vector, license_state, training_eligible, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_uuid(),
                        attachment["organization_id"],
                        attachment["workspace_id"],
                        chunk["id"],
                        attachment_id,
                        "user_upload",
                        attachment_id,
                        "text",
                        "local-hash-bow",
                        "v1",
                        len(embedding_vector),
                        _as_json(embedding_vector),
                        "user_workspace_private",
                        0,
                        _as_json(
                            {
                                "chunk_index": chunk["chunk_index"],
                                "embedding_status": "computed_local_hash_bow",
                                "worker": worker_name,
                            },
                        ),
                        now,
                    ),
                )
                text_count += 1
            image_fingerprint = (metadata.get("image") or {}).get("fingerprint") or {}
            if image_fingerprint.get("vector"):
                vector = image_fingerprint.get("vector") or []
                cursor.execute(
                    """
                    INSERT INTO phase4_embeddings(
                        id, organization_id, workspace_id, chunk_id, attachment_id,
                        source_kind, source_id, modality, encoder_name, encoder_version,
                        dimensions, vector, license_state, training_eligible, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_uuid(),
                        attachment["organization_id"],
                        attachment["workspace_id"],
                        None,
                        attachment_id,
                        "user_upload",
                        attachment_id,
                        attachment.get("modality", "image"),
                        "local-image-fingerprint-stub",
                        "v0",
                        int(image_fingerprint.get("dimensions") or len(vector)),
                        _as_json(vector),
                        "user_workspace_private",
                        0,
                        _as_json(
                            {
                                "embedding_status": "metadata_only_local_stub",
                                "fingerprint_hash": image_fingerprint.get("hash"),
                                "algorithm": image_fingerprint.get("algorithm"),
                                "filters": metadata.get("filters", {}),
                                "worker": worker_name,
                            },
                        ),
                        now,
                    ),
                )
                image_count += 1
            metadata.update(
                {
                    "embedding_status": "computed_worker_reindex",
                    "embedding_worker": worker_name,
                    "embedding_reindexed_at": now,
                    "embedding_text_count": text_count,
                    "embedding_image_count": image_count,
                },
            )
            cursor.execute(
                "UPDATE phase4_attachments SET metadata = ? WHERE id = ?",
                (_as_json(metadata), attachment_id),
            )
        return {
            "attachment_id": attachment_id,
            "text_embedding_count": text_count,
            "image_embedding_count": image_count,
            "worker": worker_name,
        }

    def _normalize_phase4_embedding(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "chunk_id": raw["chunk_id"],
            "attachment_id": raw["attachment_id"],
            "source_kind": raw["source_kind"],
            "source_id": raw["source_id"],
            "modality": raw["modality"],
            "encoder_name": raw["encoder_name"],
            "encoder_version": raw["encoder_version"],
            "dimensions": raw["dimensions"],
            "vector": _from_json(raw["vector"], []),
            "license_state": raw["license_state"],
            "training_eligible": bool(raw["training_eligible"]),
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "deleted_at": raw["deleted_at"],
            "filename": raw.get("filename"),
            "content_type": raw.get("content_type"),
            "attachment_metadata": _from_json(raw.get("attachment_metadata"), {}),
        }

    def _normalize_phase4_document_chunk(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "data_source_id": raw["data_source_id"],
            "attachment_id": raw["attachment_id"],
            "source_doc_id": raw["source_doc_id"],
            "chunk_index": raw["chunk_index"],
            "title": raw["title"],
            "text_content": raw["text_content"],
            "source_url": raw["source_url"],
            "license_state": raw["license_state"],
            "training_eligible": bool(raw["training_eligible"]),
            "visibility": raw["visibility"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "deleted_at": raw["deleted_at"],
        }

    def _normalize_phase4_attachment(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "message_id": raw["message_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "filename": raw["filename"],
            "content_type": raw["content_type"],
            "storage_uri": raw["storage_uri"],
            "size_bytes": raw["size_bytes"],
            "sha256": raw["sha256"],
            "modality": raw["modality"],
            "sensitivity": raw["sensitivity"],
            "parse_status": raw["parse_status"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "deleted_at": raw["deleted_at"],
        }

    def create_phase4_data_source(self, *, workspace: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        data_source_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_data_sources(
                    id, organization_id, workspace_id, source_id, title, publisher, canonical_url,
                    license_state, rag_eligible, sft_eligible, source_kind, crops, regions, buckets,
                    metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data_source_id,
                    workspace["organization_id"],
                    workspace["id"],
                    payload["source_id"],
                    payload["title"],
                    payload.get("publisher"),
                    payload.get("canonical_url"),
                    payload.get("license_state", "unknown"),
                    int(bool(payload.get("rag_eligible", False))),
                    int(bool(payload.get("sft_eligible", False))),
                    payload["source_kind"],
                    _as_json(payload.get("crops", [])),
                    _as_json(payload.get("regions", [])),
                    _as_json(payload.get("buckets", [])),
                    _as_json(
                        {
                            **(payload.get("metadata") or {}),
                            **{
                                key: payload[key]
                                for key in ["source_path", "text_content"]
                                if payload.get(key) is not None
                            },
                        },
                    ),
                    now,
                    now,
                ),
            )
        return self.get_phase4_data_source(data_source_id) or {}

    def list_phase4_data_sources(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_data_sources WHERE workspace_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_data_source(dict(row)) for row in rows]

    def get_phase4_data_source(self, data_source_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_data_sources WHERE id = ? AND deleted_at IS NULL", (data_source_id,)).fetchone()
            return self._normalize_phase4_data_source(dict(row)) if row else None

    def update_phase4_data_source(
        self,
        *,
        data_source_id: str,
        actor_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = self.get_phase4_data_source(data_source_id)
        if not current:
            return None
        allowed_fields = {
            "title",
            "publisher",
            "canonical_url",
            "license_state",
            "rag_eligible",
            "sft_eligible",
            "source_kind",
            "crops",
            "regions",
            "buckets",
            "metadata",
            "source_path",
            "text_content",
        }
        updates = {key: value for key, value in payload.items() if key in allowed_fields}
        if not updates:
            return current
        metadata_updates = dict(current.get("metadata") or {})
        if "metadata" in updates:
            metadata_updates.update(updates.pop("metadata") or {})
        for key in ["source_path", "text_content"]:
            if key in updates:
                metadata_updates[key] = updates.pop(key)
        if metadata_updates != (current.get("metadata") or {}):
            updates["metadata"] = metadata_updates
        if not updates:
            return current
        now = _now()
        json_fields = {"crops", "regions", "buckets", "metadata"}
        bool_fields = {"rag_eligible", "sft_eligible"}
        assignments = [f"{key} = ?" for key in updates]
        params = [
            _as_json(value) if key in json_fields else int(bool(value)) if key in bool_fields else value
            for key, value in updates.items()
        ]
        params.extend([now, data_source_id])
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE phase4_data_sources
                SET {", ".join(assignments)}, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                params,
            )
            self._insert_phase4_audit(
                cursor,
                event_type="data_source.updated",
                actor_user_id=actor_user_id,
                organization_id=current["organization_id"],
                workspace_id=current["workspace_id"],
                target_type="data_source",
                target_id=data_source_id,
                payload={"updated_fields": sorted(updates)},
                created_at=now,
            )
        return self.get_phase4_data_source(data_source_id)

    def delete_phase4_data_source(self, *, data_source_id: str, deleted_by_user_id: str) -> dict[str, Any] | None:
        current = self.get_phase4_data_source(data_source_id)
        if not current:
            return None
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE phase4_data_sources SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, now, data_source_id),
            )
            cursor.execute(
                "UPDATE phase4_document_chunks SET deleted_at = ? WHERE data_source_id = ? AND deleted_at IS NULL",
                (now, data_source_id),
            )
            cursor.execute(
                """
                UPDATE phase4_embeddings
                SET deleted_at = ?
                WHERE source_kind = ? AND source_id = ? AND deleted_at IS NULL
                """,
                (now, "data_source", data_source_id),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="data_source.deleted",
                actor_user_id=deleted_by_user_id,
                organization_id=current["organization_id"],
                workspace_id=current["workspace_id"],
                target_type="data_source",
                target_id=data_source_id,
                payload={"source_id": current["source_id"], "title": current["title"]},
                created_at=now,
            )
        deleted = dict(current)
        deleted["deleted_at"] = now
        deleted["updated_at"] = now
        return deleted

    def _normalize_phase4_data_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "source_id": raw["source_id"],
            "title": raw["title"],
            "publisher": raw["publisher"],
            "canonical_url": raw["canonical_url"],
            "license_state": raw["license_state"],
            "rag_eligible": bool(raw["rag_eligible"]),
            "sft_eligible": bool(raw["sft_eligible"]),
            "source_kind": raw["source_kind"],
            "crops": _from_json(raw["crops"], []),
            "regions": _from_json(raw["regions"], []),
            "buckets": _from_json(raw["buckets"], []),
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
            "deleted_at": raw["deleted_at"],
        }

    def create_phase4_ingest_job(self, *, data_source: dict[str, Any], created_by_user_id: str) -> dict[str, Any]:
        now = _now()
        job_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_ingest_jobs(
                    id, organization_id, workspace_id, data_source_id, job_type, status, queue_name,
                    result, created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    data_source["organization_id"],
                    data_source["workspace_id"],
                    data_source["id"],
                    "data_source_ingest",
                    "queued",
                    "ingest",
                    _as_json({"queued": True, "phase": "phase4_stub"}),
                    created_by_user_id,
                    now,
                ),
            )
        return self.get_phase4_ingest_job(job_id) or {}

    def update_phase4_ingest_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_phase4_ingest_job(job_id)
        if not current:
            return {}
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_ingest_jobs
                SET status = ?, result = ?, error_message = ?, started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    _as_json(result if result is not None else current.get("result", {})),
                    error_message,
                    started_at,
                    finished_at,
                    job_id,
                ),
            )
        return self.get_phase4_ingest_job(job_id) or {}

    def replace_phase4_data_source_chunks(
        self,
        *,
        data_source: dict[str, Any],
        chunks: list[dict[str, Any]],
    ) -> int:
        now = _now()
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE phase4_document_chunks SET deleted_at = ? WHERE data_source_id = ? AND deleted_at IS NULL",
                (now, data_source["id"]),
            )
            cursor.execute(
                """
                UPDATE phase4_embeddings
                SET deleted_at = ?
                WHERE source_kind = ? AND source_id = ? AND deleted_at IS NULL
                """,
                (now, "data_source", data_source["id"]),
            )
            for index, chunk in enumerate(chunks):
                text_content = str(chunk["text_content"])
                chunk_id = self._new_uuid()
                cursor.execute(
                    """
                    INSERT INTO phase4_document_chunks(
                        id, organization_id, workspace_id, data_source_id, source_doc_id,
                        chunk_index, title, text_content, source_url, license_state,
                        training_eligible, visibility, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        data_source["organization_id"],
                        data_source["workspace_id"],
                        data_source["id"],
                        data_source["source_id"],
                        index,
                        data_source["title"],
                        text_content,
                        data_source.get("canonical_url"),
                        data_source["license_state"],
                        int(bool(data_source.get("sft_eligible"))),
                        "workspace",
                        _as_json(
                            {
                                "text_len": len(text_content),
                                "local_ingest_worker": True,
                                **(chunk.get("metadata") or {}),
                            },
                        ),
                        now,
                    ),
                )
                embedding_vector = _local_text_embedding(text_content)
                cursor.execute(
                    """
                    INSERT INTO phase4_embeddings(
                        id, organization_id, workspace_id, chunk_id, attachment_id,
                        source_kind, source_id, modality, encoder_name, encoder_version,
                        dimensions, vector, license_state, training_eligible, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_uuid(),
                        data_source["organization_id"],
                        data_source["workspace_id"],
                        chunk_id,
                        None,
                        "data_source",
                        data_source["id"],
                        "text",
                        "local-hash-bow",
                        "v1",
                        len(embedding_vector),
                        _as_json(embedding_vector),
                        data_source["license_state"],
                        int(bool(data_source.get("sft_eligible"))),
                        _as_json({"chunk_index": index, "embedding_status": "computed_local_hash_bow"}),
                        now,
                    ),
                )
        return len(chunks)

    def get_phase4_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_ingest_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return self._normalize_phase4_ingest_job(dict(row))

    def list_phase4_ingest_jobs(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_ingest_jobs
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_ingest_job(dict(row)) for row in rows]

    def list_phase4_queued_ingest_jobs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_ingest_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._normalize_phase4_ingest_job(dict(row)) for row in rows]

    def count_phase4_document_chunks_by_source(self, workspace_id: str) -> dict[str, int]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT data_source_id, COUNT(*) AS chunk_count
                FROM phase4_document_chunks
                WHERE workspace_id = ? AND data_source_id IS NOT NULL AND deleted_at IS NULL
                GROUP BY data_source_id
                """,
                (workspace_id,),
            ).fetchall()
            return {str(row["data_source_id"]): int(row["chunk_count"]) for row in rows}

    def _normalize_phase4_ingest_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "data_source_id": raw["data_source_id"],
            "job_type": raw["job_type"],
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "error_message": raw["error_message"],
            "result": _from_json(raw["result"], {}),
            "created_by_user_id": raw["created_by_user_id"],
            "created_at": raw["created_at"],
            "started_at": raw["started_at"],
            "finished_at": raw["finished_at"],
        }

    def create_phase4_eval_candidate(self, *, thread: dict[str, Any], created_by_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        candidate_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_eval_candidates(
                    id, organization_id, workspace_id, thread_id, message_id, candidate_type,
                    target_component, payload, review_status, created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    payload.get("message_id"),
                    payload.get("candidate_type", "eval_row"),
                    payload.get("target_component", "eval"),
                    _as_json(payload),
                    "pending",
                    created_by_user_id,
                    now,
                ),
            )
        candidate = self.get_phase4_eval_candidate(candidate_id) or {}
        self.append_phase4_trace_event(thread=thread, event_type="eval_candidate", actor="system", payload=candidate)
        return candidate

    def get_phase4_eval_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_eval_candidates WHERE id = ?", (candidate_id,)).fetchone()
            if not row:
                return None
            return self._normalize_phase4_eval_candidate(dict(row))

    def list_phase4_eval_candidates(self, workspace_id: str, *, review_status: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            params: list[Any] = [workspace_id]
            status_filter = ""
            if review_status:
                status_filter = "AND review_status = ?"
                params.append(review_status)
            rows = cursor.execute(
                f"""
                SELECT * FROM phase4_eval_candidates
                WHERE workspace_id = ? {status_filter}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
            return [self._normalize_phase4_eval_candidate(dict(row)) for row in rows]

    def update_phase4_eval_candidate_status(
        self,
        *,
        candidate_id: str,
        reviewed_by_user_id: str,
        review_status: str,
    ) -> dict[str, Any] | None:
        candidate = self.get_phase4_eval_candidate(candidate_id)
        if not candidate:
            return None
        reviewed_at = _now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_eval_candidates
                SET review_status = ?, reviewed_by_user_id = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (review_status, reviewed_by_user_id, reviewed_at, candidate_id),
            )
        updated = self.get_phase4_eval_candidate(candidate_id)
        thread = self.get_phase4_thread(candidate["thread_id"])
        if thread and updated:
            self.append_phase4_trace_event(
                thread=thread,
                event_type="eval_candidate",
                actor="reviewer",
                payload=updated,
            )
        return updated

    def _normalize_phase4_eval_candidate(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "message_id": raw["message_id"],
            "candidate_type": raw["candidate_type"],
            "target_component": raw["target_component"],
            "payload": _from_json(raw["payload"], {}),
            "review_status": raw["review_status"],
            "created_by_user_id": raw["created_by_user_id"],
            "reviewed_by_user_id": raw.get("reviewed_by_user_id"),
            "created_at": raw["created_at"],
            "reviewed_at": raw["reviewed_at"],
        }

    def create_phase4_eval_run(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        name: str,
        candidate_ids: list[str],
        metrics: dict[str, Any] | None = None,
        gates: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "completed",
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        run_id = self._new_uuid()
        if status == "completed":
            started_at = started_at or now
            finished_at = finished_at or now
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_eval_runs(
                    id, organization_id, workspace_id, created_by_user_id, name, status,
                    candidate_ids, metrics, gates, metadata, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workspace["organization_id"],
                    workspace["id"],
                    created_by_user_id,
                    name,
                    status,
                    _as_json(candidate_ids),
                    _as_json(metrics or {}),
                    _as_json(gates or {}),
                    _as_json(metadata or {}),
                    now,
                    started_at,
                    finished_at,
                ),
            )
        return self.get_phase4_eval_run(run_id) or {}

    def get_phase4_eval_run(self, run_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_eval_runs WHERE id = ?", (run_id,)).fetchone()
            return self._normalize_phase4_eval_run(dict(row)) if row else None

    def list_phase4_eval_runs(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM phase4_eval_runs WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            return [self._normalize_phase4_eval_run(dict(row)) for row in rows]

    def list_phase4_queued_eval_runs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_eval_runs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._normalize_phase4_eval_run(dict(row)) for row in rows]

    def update_phase4_eval_run(
        self,
        *,
        run_id: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        gates: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        run = self.get_phase4_eval_run(run_id)
        if not run:
            return None
        next_metadata = dict(run.get("metadata") or {})
        if metadata:
            next_metadata.update(metadata)
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_eval_runs
                SET status = ?, metrics = ?, gates = ?, metadata = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    _as_json(run.get("metrics", {}) if metrics is None else metrics),
                    _as_json(run.get("gates", {}) if gates is None else gates),
                    _as_json(next_metadata),
                    started_at,
                    finished_at,
                    run_id,
                ),
            )
        return self.get_phase4_eval_run(run_id)

    def _normalize_phase4_eval_run(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "name": raw["name"],
            "status": raw["status"],
            "candidate_ids": _from_json(raw["candidate_ids"], []),
            "metrics": _from_json(raw["metrics"], {}),
            "gates": _from_json(raw["gates"], {}),
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "started_at": raw["started_at"],
            "finished_at": raw["finished_at"],
        }

    def create_phase4_change_proposal(
        self,
        *,
        workspace: dict[str, Any],
        created_by_user_id: str,
        payload: dict[str, Any],
        gates: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        proposal_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_change_proposals(
                    id, organization_id, workspace_id, created_by_user_id, title, target_component,
                    proposal_type, summary, rationale, linked_reflection_id, linked_eval_run_id,
                    review_status, gates, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    workspace["organization_id"],
                    workspace["id"],
                    created_by_user_id,
                    payload["title"],
                    payload["target_component"],
                    payload["proposal_type"],
                    payload["summary"],
                    payload.get("rationale"),
                    payload.get("linked_reflection_id"),
                    payload.get("linked_eval_run_id"),
                    "candidate",
                    _as_json(gates),
                    _as_json(payload.get("metadata") or {}),
                    now,
                ),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="change_proposal.created",
                actor_user_id=created_by_user_id,
                organization_id=workspace["organization_id"],
                workspace_id=workspace["id"],
                target_type="change_proposal",
                target_id=proposal_id,
                payload={
                    "title": payload["title"],
                    "target_component": payload["target_component"],
                    "proposal_type": payload["proposal_type"],
                    "linked_eval_run_id": payload.get("linked_eval_run_id"),
                    "promotion_allowed": bool(gates.get("promotion_allowed")),
                },
                created_at=now,
            )
        return self.get_phase4_change_proposal(proposal_id) or {}

    def get_phase4_change_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_change_proposals WHERE id = ?", (proposal_id,)).fetchone()
            return self._normalize_phase4_change_proposal(dict(row)) if row else None

    def list_phase4_change_proposals(self, workspace_id: str, *, review_status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [workspace_id]
        status_filter = ""
        if review_status:
            status_filter = "AND review_status = ?"
            params.append(review_status)
        with self._cursor() as cursor:
            rows = cursor.execute(
                f"""
                SELECT *
                FROM phase4_change_proposals
                WHERE workspace_id = ? {status_filter}
                ORDER BY created_at DESC, id DESC
                """,
                params,
            ).fetchall()
            return [self._normalize_phase4_change_proposal(dict(row)) for row in rows]

    def update_phase4_change_proposal_status(
        self,
        *,
        proposal_id: str,
        reviewed_by_user_id: str,
        review_status: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        proposal = self.get_phase4_change_proposal(proposal_id)
        if not proposal:
            return None
        reviewed_at = _now()
        metadata = dict(proposal.get("metadata") or {})
        if notes:
            metadata["review_notes"] = notes
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_change_proposals
                SET review_status = ?, reviewed_by_user_id = ?, reviewed_at = ?, metadata = ?
                WHERE id = ?
                """,
                (review_status, reviewed_by_user_id, reviewed_at, _as_json(metadata), proposal_id),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="change_proposal.reviewed",
                actor_user_id=reviewed_by_user_id,
                organization_id=proposal["organization_id"],
                workspace_id=proposal["workspace_id"],
                target_type="change_proposal",
                target_id=proposal_id,
                payload={
                    "review_status": review_status,
                    "previous_review_status": proposal["review_status"],
                    "promotion_allowed": bool(proposal.get("gates", {}).get("promotion_allowed")),
                    "notes": notes,
                },
                created_at=reviewed_at,
            )
        return self.get_phase4_change_proposal(proposal_id)

    def _normalize_phase4_change_proposal(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "title": raw["title"],
            "target_component": raw["target_component"],
            "proposal_type": raw["proposal_type"],
            "summary": raw["summary"],
            "rationale": raw["rationale"],
            "linked_reflection_id": raw["linked_reflection_id"],
            "linked_eval_run_id": raw["linked_eval_run_id"],
            "review_status": raw["review_status"],
            "gates": _from_json(raw["gates"], {}),
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
            "reviewed_by_user_id": raw["reviewed_by_user_id"],
            "reviewed_at": raw["reviewed_at"],
        }

    def create_phase4_export(
        self,
        *,
        thread: dict[str, Any],
        created_by_user_id: str,
        export_type: str,
        storage_uri: str,
        redaction_status: str,
        sha256: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        export_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_exports(
                    id, organization_id, workspace_id, thread_id, created_by_user_id, export_type,
                    storage_uri, redaction_status, sha256, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    export_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    created_by_user_id,
                    export_type,
                    storage_uri,
                    redaction_status,
                    sha256,
                    _as_json(metadata),
                    now,
                ),
            )
            self._insert_phase4_audit(
                cursor,
                event_type="export.created",
                actor_user_id=created_by_user_id,
                organization_id=thread["organization_id"],
                workspace_id=thread["workspace_id"],
                target_type="export",
                target_id=export_id,
                payload={
                    "thread_id": thread["id"],
                    "export_type": export_type,
                    "redaction_status": redaction_status,
                    "sha256": sha256,
                },
                created_at=now,
            )
        export = {
            "id": export_id,
            "organization_id": thread["organization_id"],
            "workspace_id": thread["workspace_id"],
            "thread_id": thread["id"],
            "created_by_user_id": created_by_user_id,
            "export_type": export_type,
            "storage_uri": storage_uri,
            "redaction_status": redaction_status,
            "sha256": sha256,
            "metadata": metadata,
            "created_at": now,
        }
        self.append_phase4_trace_event(
            thread=thread,
            event_type="export_event",
            actor="system",
            payload=minimized_export_trace_payload(export),
        )
        return export

    def create_phase4_export_job(
        self,
        *,
        thread: dict[str, Any],
        created_by_user_id: str,
        export_type: str,
        redaction_status: str,
        queue_name: str = "exports",
    ) -> dict[str, Any]:
        now = _now()
        job_id = self._new_uuid()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO phase4_export_jobs(
                    id, organization_id, workspace_id, thread_id, created_by_user_id,
                    export_type, redaction_status, status, queue_name, result, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    thread["organization_id"],
                    thread["workspace_id"],
                    thread["id"],
                    created_by_user_id,
                    export_type,
                    redaction_status,
                    "queued",
                    queue_name,
                    _as_json({}),
                    now,
                ),
            )
        return self.get_phase4_export_job(job_id) or {}

    def get_phase4_export_job(self, job_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_export_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._normalize_phase4_export_job(dict(row)) if row else None

    def list_phase4_queued_export_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        with self._cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT * FROM phase4_export_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._normalize_phase4_export_job(dict(row)) for row in rows]

    def list_phase4_export_jobs(
        self,
        *,
        workspace_id: str,
        thread_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 500))
        filters = "WHERE workspace_id = ?"
        params: list[Any] = [workspace_id]
        if thread_id:
            filters += " AND thread_id = ?"
            params.append(thread_id)
        if status:
            filters += " AND status = ?"
            params.append(status)
        with self._cursor() as cursor:
            rows = cursor.execute(
                f"""
                SELECT * FROM phase4_export_jobs
                {filters}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, bounded_limit),
            ).fetchall()
            return [self._normalize_phase4_export_job(dict(row)) for row in rows]

    def update_phase4_export_job(
        self,
        *,
        job_id: str,
        status: str,
        export_id: str | None = None,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.get_phase4_export_job(job_id)
        if not job:
            return None
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE phase4_export_jobs
                SET status = ?,
                    export_id = COALESCE(?, export_id),
                    result = ?,
                    error_message = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    export_id,
                    _as_json(job.get("result", {}) if result is None else result),
                    error_message,
                    started_at,
                    finished_at,
                    job_id,
                ),
            )
        return self.get_phase4_export_job(job_id)

    def _normalize_phase4_export_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "export_type": raw["export_type"],
            "redaction_status": raw["redaction_status"],
            "status": raw["status"],
            "queue_name": raw["queue_name"],
            "export_id": raw["export_id"],
            "error_message": raw["error_message"],
            "result": _from_json(raw["result"], {}),
            "created_at": raw["created_at"],
            "started_at": raw["started_at"],
            "finished_at": raw["finished_at"],
        }

    def list_phase4_exports(
        self,
        *,
        workspace_id: str,
        thread_id: str | None = None,
        export_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        params: list[Any] = [workspace_id]
        filters = ""
        if thread_id:
            filters += " AND thread_id = ?"
            params.append(thread_id)
        if export_type:
            filters += " AND export_type = ?"
            params.append(export_type)
        params.append(limit)
        with self._cursor() as cursor:
            rows = cursor.execute(
                f"""
                SELECT *
                FROM phase4_exports
                WHERE workspace_id = ? {filters}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [self._normalize_phase4_export(dict(row)) for row in rows]

    def get_phase4_export(self, export_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT * FROM phase4_exports WHERE id = ?", (export_id,)).fetchone()
            return self._normalize_phase4_export(dict(row)) if row else None

    def _normalize_phase4_export(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "thread_id": raw["thread_id"],
            "created_by_user_id": raw["created_by_user_id"],
            "export_type": raw["export_type"],
            "storage_uri": raw["storage_uri"],
            "redaction_status": raw["redaction_status"],
            "sha256": raw["sha256"],
            "metadata": _from_json(raw["metadata"], {}),
            "created_at": raw["created_at"],
        }

    def _insert_phase4_audit(
        self,
        cursor: sqlite3.Cursor,
        *,
        event_type: str,
        created_at: str,
        actor_user_id: str | None = None,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO phase4_audit_events(
                id, organization_id, workspace_id, actor_user_id, event_type,
                target_type, target_id, payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._new_uuid(),
                organization_id,
                workspace_id,
                actor_user_id,
                event_type,
                target_type,
                target_id,
                _as_json(payload or {}),
                created_at,
            ),
        )

    def list_phase4_audit_events(
        self,
        *,
        workspace_id: str,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        params: list[Any] = [workspace_id]
        event_filter = ""
        if event_type:
            event_filter = "AND event_type = ?"
            params.append(event_type)
        params.append(limit)
        with self._cursor() as cursor:
            rows = cursor.execute(
                f"""
                SELECT *
                FROM phase4_audit_events
                WHERE workspace_id = ? {event_filter}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [self._normalize_phase4_audit_event(dict(row)) for row in rows]

    def _normalize_phase4_audit_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": raw["id"],
            "organization_id": raw["organization_id"],
            "workspace_id": raw["workspace_id"],
            "actor_user_id": raw["actor_user_id"],
            "event_type": raw["event_type"],
            "target_type": raw["target_type"],
            "target_id": raw["target_id"],
            "payload": _from_json(raw["payload"], {}),
            "created_at": raw["created_at"],
        }
