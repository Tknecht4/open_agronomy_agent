#!/usr/bin/env python3
"""Build the machine-local paired-model benchmark results database.

The database intentionally contains exact prompts and retrieved private context.
It is a local research artifact and must never be added to a distributable bundle.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPERIMENT_DIR = ROOT / "outputs" / "full_system_model_matrix_20260801"
SCHEMA_VERSION = "open_agronomy_agent.full_system_benchmark_db.v6"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(payload)
    return rows


DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS database_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_case (
    eval_id TEXT PRIMARY KEY,
    ordinal INTEGER NOT NULL,
    task_family TEXT NOT NULL,
    question TEXT NOT NULL,
    question_sha256 TEXT NOT NULL,
    field_context_json TEXT NOT NULL,
    semantic_reference_json TEXT NOT NULL,
    eval_metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model (
    model_key TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_revision TEXT,
    model_config_path TEXT,
    model_config_sha256 TEXT,
    UNIQUE(model_id, model_revision, model_config_sha256)
);

CREATE TABLE IF NOT EXISTS benchmark_run (
    run_id TEXT PRIMARY KEY,
    model_key TEXT NOT NULL REFERENCES model(model_key),
    mode TEXT NOT NULL CHECK(mode IN ('raw_model', 'baseline', 'kernel_field_context', 'agronomic_rag')),
    system_variant TEXT NOT NULL CHECK(system_variant IN ('raw_model', 'kernel_only', 'kernel_field_context', 'full_system')),
    trial_id TEXT NOT NULL DEFAULT 'legacy-trial-000',
    generation_seed INTEGER,
    case_order_seed INTEGER,
    judge_seed INTEGER,
    run_execution_id TEXT,
    outputs_path TEXT NOT NULL UNIQUE,
    outputs_sha256 TEXT NOT NULL,
    summary_path TEXT NOT NULL,
    summary_sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    proxy_mean REAL,
    elapsed_seconds REAL,
    answer_profile TEXT,
    context_packet_capture INTEGER NOT NULL CHECK(context_packet_capture IN (0, 1)),
    is_canonical INTEGER NOT NULL DEFAULT 0 CHECK(is_canonical IN (0, 1)),
    run_identity_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS response (
    response_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    eval_id TEXT NOT NULL REFERENCES benchmark_case(eval_id),
    observation_id TEXT,
    matched_trial_key TEXT,
    ordinal INTEGER NOT NULL,
    output TEXT NOT NULL,
    output_sha256 TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL,
    exact_messages_json TEXT NOT NULL,
    context_block TEXT,
    context_block_sha256 TEXT,
    field_context_json TEXT NOT NULL,
    score_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    route_json TEXT,
    verification_json TEXT,
    generation_stats_json TEXT,
    generation_path TEXT,
    UNIQUE(run_id, eval_id)
);

CREATE TABLE IF NOT EXISTS retrieved_document (
    response_id TEXT NOT NULL REFERENCES response(response_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    doc_id TEXT NOT NULL,
    source_id TEXT,
    title TEXT,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    source TEXT,
    source_type TEXT,
    score REAL,
    retrieval_policy TEXT,
    answer_role TEXT,
    distribution_scope TEXT,
    jurisdictions_json TEXT NOT NULL,
    crops_json TEXT NOT NULL,
    content_risk_tags_json TEXT NOT NULL,
    PRIMARY KEY(response_id, rank)
);

CREATE TABLE IF NOT EXISTS graph_hit (
    response_id TEXT NOT NULL REFERENCES response(response_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    name TEXT,
    kind TEXT,
    evidence TEXT,
    neighbors_json TEXT NOT NULL,
    PRIMARY KEY(response_id, rank)
);

CREATE TABLE IF NOT EXISTS tool_note (
    response_id TEXT NOT NULL REFERENCES response(response_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY(response_id, rank)
);

CREATE TABLE IF NOT EXISTS evidence_packet (
    response_id TEXT PRIMARY KEY REFERENCES response(response_id) ON DELETE CASCADE,
    fabric_schema_version TEXT NOT NULL,
    fabric_record_sha256 TEXT NOT NULL,
    packet_id TEXT NOT NULL,
    question_frame_id TEXT NOT NULL,
    capture_status TEXT NOT NULL,
    validated_answer_id TEXT,
    answer_status TEXT,
    question_frame_json TEXT NOT NULL,
    version_ledger_json TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    validated_answer_json TEXT
);

CREATE TABLE IF NOT EXISTS evidence_capsule (
    response_id TEXT NOT NULL REFERENCES response(response_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    capsule_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    applicability_id TEXT NOT NULL,
    authority_role TEXT NOT NULL,
    evidence_role TEXT NOT NULL,
    factual_interpretation_authority TEXT NOT NULL,
    field_action_authority TEXT NOT NULL,
    authority_reason TEXT NOT NULL,
    span_ids_json TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    review_state TEXT NOT NULL,
    capture_status TEXT NOT NULL,
    PRIMARY KEY(response_id, rank)
);

CREATE TABLE IF NOT EXISTS query_coverage_state (
    response_id TEXT NOT NULL REFERENCES response(response_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    slot_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ADEQUATE', 'PARTIAL', 'ABSENT', 'STALE', 'CONFLICTING', 'OUT_OF_SCOPE')),
    required_authority TEXT,
    evidence_capsule_ids_json TEXT NOT NULL,
    missing_inputs_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    PRIMARY KEY(response_id, rank)
);

CREATE TABLE IF NOT EXISTS semantic_judgment (
    response_id TEXT PRIMARY KEY REFERENCES response(response_id) ON DELETE CASCADE,
    judge_model_id TEXT NOT NULL,
    judge_model_revision TEXT,
    judge_generator_relationship TEXT,
    judge_backend TEXT,
    question_validity TEXT,
    answer_disposition TEXT,
    confidence TEXT,
    semantic_score REAL,
    dimensions_json TEXT NOT NULL,
    material_errors_json TEXT NOT NULL,
    rationale TEXT,
    needs_source_validation INTEGER NOT NULL CHECK(needs_source_validation IN (0, 1)),
    provenance_json TEXT NOT NULL,
    judgment_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_run (
    judge_run_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    judgments_path TEXT NOT NULL UNIQUE,
    judgments_sha256 TEXT NOT NULL,
    summary_path TEXT NOT NULL,
    summary_sha256 TEXT NOT NULL,
    judge_role TEXT NOT NULL,
    judge_model_id TEXT NOT NULL,
    judge_model_revision TEXT,
    reasoning_effort TEXT,
    judge_backend TEXT,
    judge_generator_relationship TEXT,
    promotion_eligible INTEGER NOT NULL CHECK(promotion_eligible IN (0, 1)),
    calibration_status TEXT,
    prompt_sha256 TEXT,
    output_schema_sha256 TEXT,
    protocol_identity_json TEXT NOT NULL,
    summary_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_assessment (
    judge_run_id TEXT NOT NULL REFERENCES judge_run(judge_run_id) ON DELETE CASCADE,
    response_id TEXT NOT NULL REFERENCES response(response_id) ON DELETE CASCADE,
    review_id TEXT NOT NULL,
    answer_disposition TEXT,
    confidence TEXT,
    semantic_score REAL,
    assessment_json TEXT NOT NULL,
    PRIMARY KEY(judge_run_id, response_id)
);

DROP INDEX IF EXISTS idx_run_model_mode;
CREATE INDEX IF NOT EXISTS idx_run_model_mode ON benchmark_run(model_key, mode, trial_id);
CREATE INDEX IF NOT EXISTS idx_response_eval ON response(eval_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_response_observation
    ON response(observation_id) WHERE observation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_response_matched_trial ON response(matched_trial_key);
CREATE INDEX IF NOT EXISTS idx_doc_source ON retrieved_document(source_id, doc_id);
CREATE INDEX IF NOT EXISTS idx_judgment_disposition ON semantic_judgment(answer_disposition);
CREATE INDEX IF NOT EXISTS idx_judge_run_source ON judge_run(source_run_id, judge_role);
CREATE INDEX IF NOT EXISTS idx_judge_assessment_response ON judge_assessment(response_id);
CREATE INDEX IF NOT EXISTS idx_evidence_packet_id ON evidence_packet(packet_id);
CREATE INDEX IF NOT EXISTS idx_evidence_capsule_id ON evidence_capsule(capsule_id);
CREATE INDEX IF NOT EXISTS idx_query_coverage_status ON query_coverage_state(status, slot_key);

DROP VIEW IF EXISTS paired_response;
CREATE VIEW paired_response AS
SELECT
    m.model_id,
    m.model_revision,
    rb.trial_id,
    rb.generation_seed,
    c.eval_id,
    c.task_family,
    c.question,
    baseline.response_id AS baseline_response_id,
    baseline.output AS baseline_output,
    fullresp.response_id AS full_system_response_id,
    fullresp.output AS full_system_output,
    json_extract(baseline.score_json, '$.score') AS baseline_proxy_score,
    json_extract(fullresp.score_json, '$.score') AS full_system_proxy_score,
    jb.semantic_score AS baseline_semantic_score,
    jf.semantic_score AS full_system_semantic_score,
    jb.answer_disposition AS baseline_disposition,
    jf.answer_disposition AS full_system_disposition,
    baseline.elapsed_seconds AS baseline_elapsed_seconds,
    fullresp.elapsed_seconds AS full_system_elapsed_seconds
FROM model m
JOIN benchmark_run rb ON rb.model_key = m.model_key AND rb.mode = 'raw_model' AND rb.is_canonical = 1
JOIN response baseline ON baseline.run_id = rb.run_id
JOIN benchmark_case c ON c.eval_id = baseline.eval_id
JOIN benchmark_run rf ON rf.model_key = m.model_key AND rf.mode = 'agronomic_rag'
    AND rf.trial_id = rb.trial_id AND rf.generation_seed IS rb.generation_seed
    AND rf.is_canonical = 1
JOIN response fullresp ON fullresp.run_id = rf.run_id AND fullresp.eval_id = c.eval_id
    AND (baseline.matched_trial_key IS NULL OR fullresp.matched_trial_key = baseline.matched_trial_key)
LEFT JOIN semantic_judgment jb ON jb.response_id = baseline.response_id
LEFT JOIN semantic_judgment jf ON jf.response_id = fullresp.response_id;

DROP VIEW IF EXISTS arm_response_matrix;
CREATE VIEW arm_response_matrix AS
SELECT
    m.model_id,
    m.model_revision,
    br.trial_id,
    br.generation_seed,
    c.eval_id,
    c.task_family,
    c.question,
    MAX(CASE WHEN br.mode = 'raw_model' THEN r.response_id END) AS raw_model_response_id,
    MAX(CASE WHEN br.mode = 'baseline' THEN r.response_id END) AS kernel_only_response_id,
    MAX(CASE WHEN br.mode = 'kernel_field_context' THEN r.response_id END) AS kernel_field_context_response_id,
    MAX(CASE WHEN br.mode = 'agronomic_rag' THEN r.response_id END) AS full_system_response_id,
    MAX(CASE WHEN br.mode = 'raw_model' THEN json_extract(r.score_json, '$.score') END) AS raw_model_score,
    MAX(CASE WHEN br.mode = 'baseline' THEN json_extract(r.score_json, '$.score') END) AS kernel_only_score,
    MAX(CASE WHEN br.mode = 'kernel_field_context' THEN json_extract(r.score_json, '$.score') END) AS kernel_field_context_score,
    MAX(CASE WHEN br.mode = 'agronomic_rag' THEN json_extract(r.score_json, '$.score') END) AS full_system_score
FROM model m
JOIN benchmark_run br ON br.model_key = m.model_key AND br.is_canonical = 1
JOIN response r ON r.run_id = br.run_id
JOIN benchmark_case c ON c.eval_id = r.eval_id
GROUP BY m.model_key, br.trial_id, br.generation_seed, c.eval_id;

DROP VIEW IF EXISTS model_arm_summary;
CREATE VIEW model_arm_summary AS
SELECT
    m.model_id,
    m.model_revision,
    m.model_config_path,
    m.model_config_sha256,
    r.trial_id,
    r.generation_seed,
    r.system_variant,
    COUNT(resp.response_id) AS response_count,
    AVG(json_extract(resp.score_json, '$.score')) AS proxy_mean,
    AVG(j.semantic_score) AS semantic_mean,
    SUM(CASE WHEN j.answer_disposition = 'pass' THEN 1 ELSE 0 END) AS semantic_pass,
    SUM(CASE WHEN j.answer_disposition = 'revise' THEN 1 ELSE 0 END) AS semantic_revise,
    SUM(CASE WHEN j.answer_disposition = 'fail' THEN 1 ELSE 0 END) AS semantic_fail,
    AVG(resp.elapsed_seconds) AS latency_mean_seconds
FROM model m
JOIN benchmark_run r ON r.model_key = m.model_key
JOIN response resp ON resp.run_id = r.run_id
LEFT JOIN semantic_judgment j ON j.response_id = resp.response_id
WHERE r.is_canonical = 1
GROUP BY m.model_key, r.trial_id, r.generation_seed, r.system_variant;

DROP VIEW IF EXISTS benchmark_lane_summary;
CREATE VIEW benchmark_lane_summary AS
SELECT
    m.model_id,
    m.model_revision,
    m.model_config_path,
    m.model_config_sha256,
    r.trial_id,
    r.generation_seed,
    r.system_variant,
    COALESCE(json_extract(c.eval_metadata_json, '$.benchmark_lane'), 'legacy_unspecified') AS benchmark_lane,
    COALESCE(json_extract(c.eval_metadata_json, '$.metric_role'), 'legacy_unspecified') AS metric_role,
    COUNT(resp.response_id) AS response_count,
    AVG(CASE WHEN json_extract(resp.score_json, '$.proxy_valid') = 1
        THEN json_extract(resp.score_json, '$.score') END) AS valid_proxy_mean,
    AVG(j.semantic_score) AS automated_triage_mean,
    SUM(CASE WHEN j.answer_disposition = 'pass' THEN 1 ELSE 0 END) AS automated_triage_pass,
    SUM(CASE WHEN j.answer_disposition = 'revise' THEN 1 ELSE 0 END) AS automated_triage_revise,
    SUM(CASE WHEN j.answer_disposition = 'fail' THEN 1 ELSE 0 END) AS automated_triage_fail,
    AVG(resp.elapsed_seconds) AS latency_mean_seconds
FROM model m
JOIN benchmark_run r ON r.model_key = m.model_key
JOIN response resp ON resp.run_id = r.run_id
JOIN benchmark_case c ON c.eval_id = resp.eval_id
LEFT JOIN semantic_judgment j ON j.response_id = resp.response_id
WHERE r.is_canonical = 1
GROUP BY m.model_key, r.trial_id, r.generation_seed, r.system_variant, benchmark_lane, metric_role;
"""


def connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    existing_run_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(benchmark_run)")
    }
    if existing_run_columns and "is_canonical" not in existing_run_columns:
        connection.execute(
            "ALTER TABLE benchmark_run ADD COLUMN is_canonical INTEGER NOT NULL DEFAULT 0"
        )
        existing_run_columns.add("is_canonical")
    for column, declaration in {
        "trial_id": "TEXT NOT NULL DEFAULT 'legacy-trial-000'",
        "generation_seed": "INTEGER",
        "case_order_seed": "INTEGER",
        "judge_seed": "INTEGER",
        "run_execution_id": "TEXT",
    }.items():
        if existing_run_columns and column not in existing_run_columns:
            connection.execute(f"ALTER TABLE benchmark_run ADD COLUMN {column} {declaration}")
    existing_response_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(response)")
    }
    for column in ("observation_id", "matched_trial_key"):
        if existing_response_columns and column not in existing_response_columns:
            connection.execute(f"ALTER TABLE response ADD COLUMN {column} TEXT")
    connection.executescript(DDL)
    judgment_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(semantic_judgment)")
    }
    if "judge_model_revision" not in judgment_columns:
        connection.execute("ALTER TABLE semantic_judgment ADD COLUMN judge_model_revision TEXT")
    if "judge_generator_relationship" not in judgment_columns:
        connection.execute(
            "ALTER TABLE semantic_judgment ADD COLUMN judge_generator_relationship TEXT"
        )
    return connection


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def ingest_run(connection: sqlite3.Connection, outputs_path: Path) -> tuple[str, int]:
    run_dir = outputs_path.parent
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise ValueError(f"run is missing summary or manifest: {run_dir}")
    rows = read_jsonl(outputs_path)
    summary = read_json(summary_path)
    manifest = read_json(manifest_path)
    if not rows:
        raise ValueError(f"run contains no responses: {outputs_path}")
    if summary.get("context_packet_capture") is not True:
        raise ValueError(f"run did not opt into context packet capture: {outputs_path}")
    if len(rows) != int(summary.get("samples") or -1):
        raise ValueError(f"summary row count mismatch: {outputs_path}")
    model_id = str(summary.get("model_id") or rows[0].get("model_id") or "")
    run_identity = summary.get("run_identity") or manifest
    revision = run_identity.get("model_revision")
    model_config_path = str(summary.get("model_config") or "")
    model_config_sha256 = str(run_identity.get("model_config_sha256") or "")
    existing_model = connection.execute(
        """
        SELECT model_key FROM model
        WHERE model_id = ? AND model_revision IS ? AND COALESCE(model_config_sha256, '') = ?
        """,
        (model_id, revision, model_config_sha256),
    ).fetchone()
    model_key = (
        str(existing_model["model_key"])
        if existing_model is not None
        else stable_id(model_id, str(revision or ""), model_config_sha256)
    )
    connection.execute(
        """
        INSERT INTO model(model_key, model_id, model_revision, model_config_path, model_config_sha256)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(model_key) DO UPDATE SET
            model_config_path=excluded.model_config_path,
            model_config_sha256=excluded.model_config_sha256
        """,
        (
            model_key,
            model_id,
            revision,
            model_config_path,
            model_config_sha256,
        ),
    )
    mode = str(rows[0].get("mode") or summary.get("mode") or "")
    run_id = str(summary.get("run_identity_sha256") or stable_id(display_path(outputs_path), sha256(outputs_path)))
    replication = summary.get("replication_contract") or run_identity.get("replication_contract") or {}
    case_order = replication.get("case_order") or {}
    trial_id = str(replication.get("trial_id") or rows[0].get("trial_id") or "legacy-trial-000")
    connection.execute(
        """
        INSERT INTO benchmark_run(
            run_id, model_key, mode, system_variant, trial_id, generation_seed,
            case_order_seed, judge_seed, run_execution_id, outputs_path, outputs_sha256,
            summary_path, summary_sha256, row_count, proxy_mean, elapsed_seconds,
            answer_profile, context_packet_capture, run_identity_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            outputs_sha256=excluded.outputs_sha256,
            summary_sha256=excluded.summary_sha256,
            row_count=excluded.row_count,
            proxy_mean=excluded.proxy_mean,
            elapsed_seconds=excluded.elapsed_seconds,
            run_identity_json=excluded.run_identity_json
        """,
        (
            run_id,
            model_key,
            mode,
            {
                "raw_model": "raw_model",
                "baseline": "kernel_only",
                "kernel_field_context": "kernel_field_context",
                "agronomic_rag": "full_system",
            }[mode],
            trial_id,
            replication.get("generation_seed"),
            case_order.get("case_order_seed"),
            replication.get("judge_seed"),
            run_identity.get("run_execution_id") or summary.get("run_execution_id"),
            display_path(outputs_path),
            sha256(outputs_path),
            display_path(summary_path),
            sha256(summary_path),
            len(rows),
            summary.get("mean_score"),
            sum(float(row.get("elapsed_seconds") or 0.0) for row in rows),
            summary.get("answer_profile"),
            1,
            json_text(run_identity),
        ),
    )
    for ordinal, row in enumerate(rows, start=1):
        eval_id = str(row["eval_id"])
        question = str(row["question"])
        connection.execute(
            """
            INSERT INTO benchmark_case(
                eval_id, ordinal, task_family, question, question_sha256,
                field_context_json, semantic_reference_json, eval_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(eval_id) DO UPDATE SET
                question=excluded.question,
                question_sha256=excluded.question_sha256,
                field_context_json=excluded.field_context_json,
                semantic_reference_json=excluded.semantic_reference_json,
                eval_metadata_json=excluded.eval_metadata_json
            """,
            (
                eval_id,
                ordinal,
                str(row.get("task_family") or "unknown"),
                question,
                hashlib.sha256(question.encode("utf-8")).hexdigest(),
                json_text(row.get("eval_field_context") or {}),
                json_text(row.get("semantic_reference") or {}),
                json_text(row.get("eval_metadata") or {}),
            ),
        )
        metadata = dict(row.get("metadata") or {})
        packet = metadata.pop("benchmark_generation_input", None)
        if not isinstance(packet, dict):
            raise ValueError(f"{outputs_path}:{eval_id}: missing benchmark_generation_input")
        messages = packet.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"{outputs_path}:{eval_id}: missing exact model messages")
        context_block = packet.get("context_block")
        observation_id = str(row.get("observation_id") or "") or None
        response_id = observation_id or stable_id(run_id, eval_id)
        output = str(row.get("output") or "")
        connection.execute(
            """
            INSERT INTO response(
                response_id, run_id, eval_id, observation_id, matched_trial_key,
                ordinal, output, output_sha256,
                elapsed_seconds, exact_messages_json, context_block,
                context_block_sha256, field_context_json, score_json,
                metadata_json, route_json, verification_json,
                generation_stats_json, generation_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(response_id) DO UPDATE SET
                output=excluded.output,
                output_sha256=excluded.output_sha256,
                elapsed_seconds=excluded.elapsed_seconds,
                exact_messages_json=excluded.exact_messages_json,
                context_block=excluded.context_block,
                context_block_sha256=excluded.context_block_sha256,
                score_json=excluded.score_json,
                metadata_json=excluded.metadata_json,
                route_json=excluded.route_json,
                verification_json=excluded.verification_json,
                generation_stats_json=excluded.generation_stats_json,
                generation_path=excluded.generation_path
            """,
            (
                response_id,
                run_id,
                eval_id,
                observation_id,
                row.get("matched_trial_key"),
                ordinal,
                output,
                hashlib.sha256(output.encode("utf-8")).hexdigest(),
                float(row.get("elapsed_seconds") or 0.0),
                json_text(messages),
                context_block,
                hashlib.sha256(str(context_block).encode("utf-8")).hexdigest()
                if context_block is not None
                else None,
                json_text(row.get("eval_field_context") or {}),
                json_text(row.get("score") or {}),
                json_text(metadata),
                json_text(metadata.get("route")) if metadata.get("route") is not None else None,
                json_text(metadata.get("answer_verification"))
                if metadata.get("answer_verification") is not None
                else None,
                json_text(metadata.get("generation_stats"))
                if metadata.get("generation_stats") is not None
                else None,
                metadata.get("generation_path"),
            ),
        )
        connection.execute("DELETE FROM retrieved_document WHERE response_id = ?", (response_id,))
        for document in packet.get("retrieved_documents") or []:
            text = str(document.get("text") or "")
            connection.execute(
                """
                INSERT INTO retrieved_document(
                    response_id, rank, doc_id, source_id, title, text, text_sha256,
                    source, source_type, score, retrieval_policy, answer_role,
                    distribution_scope, jurisdictions_json, crops_json,
                    content_risk_tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response_id,
                    int(document.get("rank") or 0),
                    str(document.get("doc_id") or ""),
                    document.get("source_id"),
                    document.get("title"),
                    text,
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    document.get("source"),
                    document.get("source_type"),
                    document.get("score"),
                    document.get("retrieval_policy"),
                    document.get("answer_role"),
                    document.get("distribution_scope"),
                    json_text(document.get("jurisdictions") or []),
                    json_text(document.get("crops") or []),
                    json_text(document.get("content_risk_tags") or []),
                ),
            )
        connection.execute("DELETE FROM graph_hit WHERE response_id = ?", (response_id,))
        for hit in packet.get("graph_hits") or []:
            connection.execute(
                "INSERT INTO graph_hit VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    response_id,
                    int(hit.get("rank") or 0),
                    str(hit.get("node_id") or ""),
                    hit.get("name"),
                    hit.get("kind"),
                    hit.get("evidence"),
                    json_text(hit.get("neighbors") or []),
                ),
            )
        connection.execute("DELETE FROM tool_note WHERE response_id = ?", (response_id,))
        for rank, note in enumerate(packet.get("tool_notes") or [], start=1):
            connection.execute(
                "INSERT INTO tool_note VALUES (?, ?, ?, ?)",
                (response_id, rank, str(note.get("name") or ""), str(note.get("text") or "")),
            )
        connection.execute("DELETE FROM evidence_packet WHERE response_id = ?", (response_id,))
        connection.execute("DELETE FROM evidence_capsule WHERE response_id = ?", (response_id,))
        connection.execute("DELETE FROM query_coverage_state WHERE response_id = ?", (response_id,))
        fabric = metadata.get("evidence_fabric")
        if isinstance(fabric, dict) and fabric.get("status") == "captured":
            evidence_packet = fabric.get("evidence_packet")
            question_frame = fabric.get("question_frame")
            validated_answer = fabric.get("validated_answer")
            if not isinstance(evidence_packet, dict) or not isinstance(question_frame, dict):
                raise ValueError(f"{outputs_path}:{eval_id}: incomplete captured evidence fabric")
            record_sha256 = str(fabric.get("record_sha256") or "")
            if len(record_sha256) != 64:
                raise ValueError(f"{outputs_path}:{eval_id}: invalid evidence fabric record hash")
            fabric_payload = dict(fabric)
            fabric_payload.pop("record_sha256", None)
            expected_record_sha256 = hashlib.sha256(
                json_text(fabric_payload).encode("utf-8")
            ).hexdigest()
            if record_sha256 != expected_record_sha256:
                raise ValueError(f"{outputs_path}:{eval_id}: evidence fabric record hash mismatch")
            connection.execute(
                """
                INSERT INTO evidence_packet(
                    response_id, fabric_schema_version, fabric_record_sha256,
                    packet_id, question_frame_id, capture_status,
                    validated_answer_id, answer_status, question_frame_json,
                    version_ledger_json, packet_json, validated_answer_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response_id,
                    str(fabric.get("schema_version") or ""),
                    record_sha256,
                    str(evidence_packet.get("packet_id") or ""),
                    str(evidence_packet.get("question_frame_id") or ""),
                    str(evidence_packet.get("capture_status") or ""),
                    validated_answer.get("validated_answer_id")
                    if isinstance(validated_answer, dict)
                    else None,
                    validated_answer.get("answer_status")
                    if isinstance(validated_answer, dict)
                    else None,
                    json_text(question_frame),
                    json_text(evidence_packet.get("version_ledger") or {}),
                    json_text(evidence_packet),
                    json_text(validated_answer) if isinstance(validated_answer, dict) else None,
                ),
            )
            for rank, capsule in enumerate(evidence_packet.get("capsules") or [], start=1):
                connection.execute(
                    """
                    INSERT INTO evidence_capsule(
                        response_id, rank, capsule_id, source_version_id,
                        applicability_id, authority_role, evidence_role,
                        factual_interpretation_authority, field_action_authority, authority_reason,
                        span_ids_json, limitations_json, review_state, capture_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response_id,
                        rank,
                        str(capsule.get("capsule_id") or ""),
                        str(capsule.get("source_version_id") or ""),
                        str(capsule.get("applicability_id") or ""),
                        str(capsule.get("authority_role") or ""),
                        str(capsule.get("evidence_role") or ""),
                        str(capsule.get("factual_interpretation_authority") or ""),
                        str(capsule.get("field_action_authority") or ""),
                        str(capsule.get("authority_reason") or ""),
                        json_text(capsule.get("span_ids") or []),
                        json_text(capsule.get("limitations") or []),
                        str(capsule.get("review_state") or ""),
                        str(capsule.get("capture_status") or ""),
                    ),
                )
            for rank, coverage in enumerate(evidence_packet.get("coverage") or [], start=1):
                connection.execute(
                    """
                    INSERT INTO query_coverage_state(
                        response_id, rank, slot_key, status, required_authority,
                        evidence_capsule_ids_json, missing_inputs_json, reasons_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response_id,
                        rank,
                        str(coverage.get("slot_key") or ""),
                        str(coverage.get("status") or ""),
                        coverage.get("required_authority"),
                        json_text(coverage.get("evidence_capsule_ids") or []),
                        json_text(coverage.get("missing_inputs") or []),
                        json_text(coverage.get("reasons") or []),
                    ),
                )
    return run_id, len(rows)


def ingest_judgments(connection: sqlite3.Connection, judgments_path: Path) -> int:
    run_dir = judgments_path.parent.parent
    outputs_path = run_dir / "outputs.jsonl"
    run = connection.execute(
        "SELECT run_id FROM benchmark_run WHERE outputs_path = ?",
        (display_path(outputs_path),),
    ).fetchone()
    if run is None:
        return 0
    summary = read_json(judgments_path.parent / "summary.json")
    judge_model = str(summary.get("model") or "unknown")
    summary_path = judgments_path.parent / "summary.json"
    judge_run_id = stable_id(
        run["run_id"],
        display_path(judgments_path),
        sha256(judgments_path),
        sha256(summary_path),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO judge_run(
            judge_run_id, source_run_id, judgments_path, judgments_sha256,
            summary_path, summary_sha256, judge_role, judge_model_id,
            judge_model_revision, reasoning_effort, judge_backend,
            judge_generator_relationship, promotion_eligible, calibration_status,
            prompt_sha256, output_schema_sha256, protocol_identity_json, summary_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            judge_run_id,
            run["run_id"],
            display_path(judgments_path),
            sha256(judgments_path),
            display_path(summary_path),
            sha256(summary_path),
            str(summary.get("judge_role") or "semantic_answer_quality"),
            judge_model,
            summary.get("judge_model_revision"),
            summary.get("reasoning_effort"),
            summary.get("judge_backend"),
            summary.get("judge_generator_relationship"),
            int(bool(summary.get("promotion_eligible"))),
            summary.get("human_calibration_status"),
            summary.get("judge_prompt_sha256"),
            summary.get("judge_output_schema_sha256"),
            json_text(summary.get("app_server_protocol_identity") or {}),
            json_text(summary),
        ),
    )
    count = 0
    for judgment in read_jsonl(judgments_path):
        eval_id = str(judgment.get("review_id") or "")
        response = connection.execute(
            "SELECT response_id FROM response WHERE run_id = ? AND eval_id = ?",
            (run["run_id"], eval_id),
        ).fetchone()
        if response is None:
            raise ValueError(f"judgment has no source response: {judgments_path}:{eval_id}")
        connection.execute(
            """
            INSERT OR REPLACE INTO judge_assessment(
                judge_run_id, response_id, review_id, answer_disposition,
                confidence, semantic_score, assessment_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                judge_run_id,
                response["response_id"],
                eval_id,
                judgment.get("answer_disposition"),
                judgment.get("confidence"),
                judgment.get("semantic_score_0_to_100"),
                json_text(judgment),
            ),
        )
        judge_role = str(summary.get("judge_role") or "semantic_answer_quality")
        if (
            judgments_path.parent.name != "semantic_judge"
            and judge_role != "semantic_answer_quality"
        ):
            count += 1
            continue
        connection.execute(
            """
            INSERT INTO semantic_judgment(
                response_id, judge_model_id, judge_model_revision,
                judge_generator_relationship, judge_backend, question_validity,
                answer_disposition, confidence, semantic_score, dimensions_json,
                material_errors_json, rationale, needs_source_validation,
                provenance_json, judgment_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(response_id) DO UPDATE SET
                judge_model_id=excluded.judge_model_id,
                judge_model_revision=excluded.judge_model_revision,
                judge_generator_relationship=excluded.judge_generator_relationship,
                judge_backend=excluded.judge_backend,
                question_validity=excluded.question_validity,
                answer_disposition=excluded.answer_disposition,
                confidence=excluded.confidence,
                semantic_score=excluded.semantic_score,
                dimensions_json=excluded.dimensions_json,
                material_errors_json=excluded.material_errors_json,
                rationale=excluded.rationale,
                needs_source_validation=excluded.needs_source_validation,
                provenance_json=excluded.provenance_json,
                judgment_json=excluded.judgment_json
            """,
            (
                response["response_id"],
                judge_model,
                summary.get("judge_model_revision"),
                summary.get("judge_generator_relationship"),
                summary.get("judge_backend"),
                judgment.get("question_validity"),
                judgment.get("answer_disposition"),
                judgment.get("confidence"),
                judgment.get("semantic_score_0_to_100"),
                json_text(judgment.get("dimensions") or {}),
                json_text(judgment.get("material_errors") or []),
                judgment.get("rationale"),
                int(bool(judgment.get("needs_source_validation"))),
                json_text(judgment.get("review_provenance") or {}),
                json_text(judgment),
            ),
        )
        count += 1
    return count


def scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def build_database(experiment_dir: Path, database: Path) -> dict[str, Any]:
    experiment_dir = experiment_dir.resolve()
    connection = connect(database)
    run_records: list[dict[str, Any]] = []
    for outputs_path in sorted(experiment_dir.glob("runs/*/*/*/outputs.jsonl")):
        run_id, rows = ingest_run(connection, outputs_path)
        run_records.append({"run_id": run_id, "path": display_path(outputs_path), "rows": rows})
    connection.execute("UPDATE benchmark_run SET is_canonical = 0")
    canonical_groups = connection.execute(
        """
        SELECT model_key, mode, trial_id, generation_seed
        FROM benchmark_run
        GROUP BY model_key, mode, trial_id, generation_seed
        """
    ).fetchall()
    for group in canonical_groups:
        canonical = connection.execute(
            """
            SELECT run_id FROM benchmark_run
            WHERE model_key = ? AND mode = ? AND trial_id = ? AND generation_seed IS ?
            ORDER BY outputs_path DESC
            LIMIT 1
            """,
            (
                group["model_key"],
                group["mode"],
                group["trial_id"],
                group["generation_seed"],
            ),
        ).fetchone()
        if canonical is not None:
            connection.execute(
                "UPDATE benchmark_run SET is_canonical = 1 WHERE run_id = ?",
                (canonical["run_id"],),
            )
    judgment_rows = 0
    for judgments_path in sorted(experiment_dir.glob("runs/*/*/*/semantic_judge*/judgments.jsonl")):
        judgment_rows += ingest_judgments(connection, judgments_path)
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "distribution_scope": "machine_local_private_benchmark_only",
        "experiment_dir": display_path(experiment_dir),
        "run_count": scalar(connection, "SELECT COUNT(*) FROM benchmark_run"),
        "model_count": scalar(connection, "SELECT COUNT(*) FROM model"),
        "case_count": scalar(connection, "SELECT COUNT(*) FROM benchmark_case"),
        "response_count": scalar(connection, "SELECT COUNT(*) FROM response"),
        "retrieved_document_count": scalar(connection, "SELECT COUNT(*) FROM retrieved_document"),
        "evidence_packet_count": scalar(connection, "SELECT COUNT(*) FROM evidence_packet"),
        "evidence_capsule_count": scalar(connection, "SELECT COUNT(*) FROM evidence_capsule"),
        "query_coverage_state_count": scalar(connection, "SELECT COUNT(*) FROM query_coverage_state"),
        "semantic_judgment_count": scalar(connection, "SELECT COUNT(*) FROM semantic_judgment"),
        "judge_run_count": scalar(connection, "SELECT COUNT(*) FROM judge_run"),
        "judge_assessment_count": scalar(connection, "SELECT COUNT(*) FROM judge_assessment"),
        "ingested_runs": run_records,
        "ingested_judgment_rows": judgment_rows,
    }
    for key, value in metadata.items():
        connection.execute(
            "INSERT OR REPLACE INTO database_metadata(key, value_json) VALUES (?, ?)",
            (key, json_text(value)),
        )
    connection.commit()
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_errors = list(connection.execute("PRAGMA foreign_key_check"))
    connection.close()
    metadata["integrity_check"] = integrity
    metadata["foreign_key_error_count"] = len(foreign_key_errors)
    metadata["database_path"] = display_path(database)
    metadata["database_bytes"] = database.stat().st_size
    metadata["database_sha256"] = sha256(database)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    experiment_dir = args.experiment_dir.resolve()
    database = (args.database or experiment_dir / "full_system_benchmark.sqlite3").resolve()
    manifest = (args.manifest or experiment_dir / "database_manifest.json").resolve()
    report = build_database(experiment_dir, database)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["integrity_check"] == "ok" and report["foreign_key_error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
