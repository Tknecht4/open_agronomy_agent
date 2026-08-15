#!/usr/bin/env python3
"""Build and verify a content-addressed private benchmark retention bundle.

The private bundle retains the canonical SQLite database and, when supplied,
the exact experiment files that produced it.  A separate public-safe export
contains hashes and structured measurements but never prompts, answers,
retrieved text, rationales, or private field context.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import errno
import hashlib
import hmac
import io
import json
import math
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.benchmark_retention_bundle.v1"
PUBLIC_SCHEMA_VERSION = "open_agronomy_agent.benchmark_public_safe_response.v2"
PUBLIC_TRANSFORM_POLICY_VERSION = "open_agronomy_agent.benchmark_public_safe_projection.v3"
OUTER_COMPLETION_RECEIPT = "benchmark_retention_completion.json"
TRANSIENT_EXPERIMENT_FILENAMES = frozenset({".eval_run.lock"})
PRIVACY_BOUNDARY = (
    "Only public_safe artifacts may be published. The private directory contains exact prompts, "
    "answers, context, judgments, keyed-link material, and potentially private evidence."
)
PUBLIC_MATERIAL_ERROR_CODES = frozenset(
    {
        "agronomic_factual_error",
        "calibration_error",
        "incomplete_answer",
        "invented_premise",
        "irrelevant_response",
        "missing_authority",
        "numeric_error",
        "source_fit_error",
        "unit_error",
        "unsafe_certainty",
        "unsupported_claim",
        "wrong_crop",
        "wrong_region",
        "wrong_source",
        "unclassified_material_error",
    }
)

PUBLIC_CATEGORY_VALUES: dict[str, frozenset[str]] = {
    "benchmark_lane": frozenset(
        {
            "canadian_advisory_transfer",
            "canadian_decision_quality",
            "external_real_farmer_agronomy_qa",
            "field_history_lineage",
            "objective_agronomic_calculation",
            "official_source_answer_boundary",
            "retrieval_lineage",
        }
    ),
    "metric_role": frozenset(
        {
            "blinded_multidimensional_answer_review",
            "decision_card_source_and_authority_trace",
            "decision_contract_and_human_review",
            "deterministic_format_invariance_regression",
            "deterministic_lexical_and_trace_regression",
            "deterministic_reference_overlap_diagnostic",
            "expected_source_retrieval_regression",
            "external_extractive_faithfulness_diagnostic",
            "objective_agronomic_calculation_accuracy",
            "objective_multiple_choice_accuracy",
            "source_boundary_and_field_context_regression",
            "source_specific_answer_and_scope_regression",
        }
    ),
    "system_variant": frozenset({"raw_model", "kernel_only", "kernel_field_context", "full_system"}),
    "mode": frozenset({"raw_model", "baseline", "kernel_field_context", "agronomic_rag"}),
    "generation_path": frozenset(
        {
            "candidate_generation",
            "model_generation",
            "deterministic_evidence_sufficiency_hold",
            "deterministic_tool_result",
            "deterministic_tool_clarification",
        }
    ),
    "intervention_action": frozenset(
        {
            "no_action",
            "preserve_draft",
            "accept_rewrite",
            "fallback_or_degraded",
            "preserve_deterministic_result",
            "request_missing_tool_input",
        }
    ),
    "question_validity": frozenset({"valid", "questionable", "invalid", "not_assessed"}),
    "answer_disposition": frozenset({"pass", "revise", "fail", "not_assessed"}),
    "judge_confidence": frozenset({"low", "medium", "high", "not_assessed"}),
    "judge_generator_relationship": frozenset(
        {"same_model", "cross_model", "human", "not_declared", "not_assessed"}
    ),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_link_key(database: Path) -> bytes:
    """Return a private key for public-to-private commitments.

    The key is derived from the exact canonical database bytes and is never
    written into the public derivative.  A holder of the private bundle can
    recompute every link; a public-only reader cannot cheaply dictionary-match
    short answers, question text, or private identifiers.
    """

    return bytes.fromhex(sha256_file(database))


def _keyed_link(key: bytes, *, domain: str, value: Any) -> str:
    message = f"{domain}\x00{canonical_json(value)}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _public_identity(key: bytes, *, domain: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    return f"private_link_{_keyed_link(key, domain=domain, value=str(value))[:24]}"


def _public_category(field: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().casefold()
    return normalized if normalized in PUBLIC_CATEGORY_VALUES[field] else "unclassified"


def _validate_stored_text_hash(*, field: str, value: Any, stored: Any) -> str | None:
    if value is None:
        if stored not in (None, ""):
            raise ValueError(f"{field} hash is present while its private value is null")
        return None
    actual = _sha256_text(str(value))
    if str(stored or "") != actual:
        raise ValueError(f"{field} stored sha256 does not match its private value")
    return actual


def _public_number(
    value: Any,
    *,
    field: str,
    minimum: float = 0.0,
    maximum: float | None = None,
    integer: bool = False,
) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"public measurement {field} must be a numeric scalar or null")
    number = float(value)
    if not math.isfinite(number) or number < minimum or (
        maximum is not None and number > maximum
    ):
        raise ValueError(f"public measurement {field} is outside its declared range")
    if integer:
        if not number.is_integer():
            raise ValueError(f"public measurement {field} must be an integer")
        return int(number)
    return number


def _public_bool(value: Any, *, field: str, sqlite_integer: bool = False) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if sqlite_integer and isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"public measurement {field} must be boolean or null")


def _validate_database_contract(connection: sqlite3.Connection) -> None:
    """Reject lookalike databases that weaken critical linkage constraints."""

    required_columns: dict[str, dict[str, tuple[str, int, int]]] = {
        "benchmark_case": {
            "eval_id": ("TEXT", 0, 1),
            "question": ("TEXT", 1, 0),
            "question_sha256": ("TEXT", 1, 0),
        },
        "response": {
            "response_id": ("TEXT", 0, 1),
            "run_id": ("TEXT", 1, 0),
            "eval_id": ("TEXT", 1, 0),
            "output": ("TEXT", 1, 0),
            "output_sha256": ("TEXT", 1, 0),
            "exact_messages_json": ("TEXT", 1, 0),
        },
        "semantic_judgment": {
            "response_id": ("TEXT", 0, 1),
            "judge_model_id": ("TEXT", 1, 0),
            "dimensions_json": ("TEXT", 1, 0),
            "material_errors_json": ("TEXT", 1, 0),
            "needs_source_validation": ("INTEGER", 1, 0),
            "provenance_json": ("TEXT", 1, 0),
            "judgment_json": ("TEXT", 1, 0),
        },
    }
    errors: list[str] = []
    for table, declarations in required_columns.items():
        columns = {
            str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for name, expected in declarations.items():
            if columns.get(name) != expected:
                errors.append(f"{table}.{name}:{columns.get(name)!r}!={expected!r}")
    if errors:
        raise ValueError("benchmark database violates canonical linkage schema: " + ", ".join(errors))


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _database_snapshot(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {"benchmark_run", "response", "semantic_judgment", "benchmark_case", "model"}
    missing = sorted(required - tables)
    if missing:
        connection.close()
        raise ValueError("benchmark database missing required tables: " + ", ".join(missing))
    _validate_database_contract(connection)
    counts = {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in sorted(required)
    }
    canonical_responses = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM response r
            JOIN benchmark_run br ON br.run_id = r.run_id
            WHERE br.is_canonical = 1
            """
        ).fetchone()[0]
    )
    connection.close()
    if integrity != "ok" or foreign_keys:
        raise ValueError(
            f"benchmark database failed integrity checks: integrity={integrity!r}, "
            f"foreign_key_errors={len(foreign_keys)}"
        )
    return {
        "integrity_check": integrity,
        "foreign_key_error_count": len(foreign_keys),
        "counts": counts,
        "canonical_response_count": canonical_responses,
    }


def _regular_experiment_files(root: Path) -> list[Path]:
    """Return regular descendants after rejecting links and special files."""

    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"experiment directory contains a symlink: {path}")
            if stat.S_ISDIR(mode):
                pending.append(path)
            elif stat.S_ISREG(mode):
                files.append(path)
            else:
                raise ValueError(
                    f"experiment directory contains a non-regular entry: {path}"
                )
    return sorted(files)


def _experiment_entries(experiment_dir: Path | None) -> list[dict[str, Any]]:
    if experiment_dir is None:
        return []
    provided_root = experiment_dir.expanduser()
    try:
        root_mode = provided_root.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValueError(f"experiment directory does not exist: {provided_root}") from exc
    if stat.S_ISLNK(root_mode):
        raise ValueError(f"experiment directory must not be a symlink: {provided_root}")
    if not stat.S_ISDIR(root_mode):
        raise ValueError(f"experiment directory does not exist: {provided_root}")
    root = provided_root.resolve(strict=True)
    regular_files = _regular_experiment_files(root)
    entries: list[dict[str, Any]] = []
    for path in regular_files:
        relative = path.relative_to(root).as_posix()
        # The canonical database is copied separately and must have one identity.
        # The outer completion receipt is written only after this immutable
        # bundle exists, so it is deliberately not an input to its own identity.
        # Run locks coordinate live processes; they are neither benchmark evidence
        # nor stable experiment artifacts and may change during retention copying.
        if path.name in {
            "full_system_benchmark.sqlite3",
            OUTER_COMPLETION_RECEIPT,
            *TRANSIENT_EXPERIMENT_FILENAMES,
        }:
            continue
        entries.append(
            {
                "source": path,
                "path": f"private/experiment/{relative}",
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "artifact_class": _artifact_class(relative),
            }
        )
    return entries


def _artifact_class(relative: str) -> str:
    lower = relative.lower()
    if lower.endswith("outputs.jsonl"):
        return "candidate_responses"
    if lower.endswith("judgments.jsonl"):
        return "semantic_judgments"
    if lower.endswith(".prompt.txt") or "/prompts/" in lower:
        return "judge_prompt"
    if lower.endswith(".receipt.json") or "receipt" in lower:
        return "receipt"
    if lower.endswith("summary.json"):
        return "summary"
    if lower.endswith("manifest.json"):
        return "manifest"
    return "experiment_supporting_artifact"


def _public_rows(database: Path) -> list[dict[str, Any]]:
    link_key = _database_link_key(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT
            resp.response_id,
            resp.ordinal AS response_ordinal,
            resp.output,
            resp.output_sha256,
            resp.exact_messages_json,
            resp.context_block,
            resp.context_block_sha256,
            resp.eval_id,
            resp.elapsed_seconds,
            resp.generation_path,
            resp.score_json,
            resp.metadata_json,
            resp.route_json,
            resp.verification_json,
            resp.generation_stats_json,
            resp.field_context_json,
            br.run_id,
            br.system_variant,
            br.mode,
            br.run_identity_json,
            m.model_id,
            m.model_revision,
            c.task_family,
            c.question,
            c.question_sha256,
            c.eval_metadata_json,
            j.response_id AS judgment_response_id,
            j.judge_model_id,
            j.judge_model_revision,
            j.judge_generator_relationship,
            j.judge_backend,
            j.question_validity,
            j.answer_disposition,
            j.confidence,
            j.semantic_score,
            j.dimensions_json,
            j.material_errors_json,
            j.rationale,
            j.needs_source_validation,
            j.provenance_json,
            j.judgment_json
        FROM response resp
        JOIN benchmark_run br ON br.run_id = resp.run_id
        JOIN model m ON m.model_key = br.model_key
        JOIN benchmark_case c ON c.eval_id = resp.eval_id
        LEFT JOIN semantic_judgment j ON j.response_id = resp.response_id
        WHERE br.is_canonical = 1
        ORDER BY m.model_id, br.system_variant, resp.eval_id
        """
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        _validate_stored_text_hash(
            field=f"response:{row['response_id']}:output",
            value=row["output"],
            stored=row["output_sha256"],
        )
        _validate_stored_text_hash(
            field=f"response:{row['response_id']}:context_block",
            value=row["context_block"],
            stored=row["context_block_sha256"],
        )
        _validate_stored_text_hash(
            field=f"case:{row['eval_id']}:question",
            value=row["question"],
            stored=row["question_sha256"],
        )
        score = _json(row["score_json"], {})
        verification = _json(row["verification_json"], {})
        generation = _json(row["generation_stats_json"], {})
        metadata = _json(row["eval_metadata_json"], {})
        dimensions = _json(row["dimensions_json"], {})
        errors = _json(row["material_errors_json"], [])
        private_response_record = {
            "response_id": row["response_id"],
            "run_id": row["run_id"],
            "eval_id": row["eval_id"],
            "ordinal": row["response_ordinal"],
            "output": row["output"],
            "output_sha256": row["output_sha256"],
            "elapsed_seconds": row["elapsed_seconds"],
            "exact_messages_json": row["exact_messages_json"],
            "context_block": row["context_block"],
            "context_block_sha256": row["context_block_sha256"],
            "field_context_json": row["field_context_json"],
            "score_json": row["score_json"],
            "metadata_json": row["metadata_json"],
            "route_json": row["route_json"],
            "verification_json": row["verification_json"],
            "generation_stats_json": row["generation_stats_json"],
            "generation_path": row["generation_path"],
        }
        private_judgment_record = {
            "response_id": row["response_id"],
            "judge_model_id": row["judge_model_id"],
            "judge_model_revision": row["judge_model_revision"],
            "judge_generator_relationship": row["judge_generator_relationship"],
            "judge_backend": row["judge_backend"],
            "question_validity": row["question_validity"],
            "answer_disposition": row["answer_disposition"],
            "confidence": row["confidence"],
            "semantic_score": row["semantic_score"],
            "dimensions_json": row["dimensions_json"],
            "material_errors_json": row["material_errors_json"],
            "rationale": row["rationale"],
            "needs_source_validation": row["needs_source_validation"],
            "provenance_json": row["provenance_json"],
            "judgment_json": row["judgment_json"],
        }
        final_assessment = verification.get("final_assessment") or verification.get("draft_assessment") or {}
        output.append(
            {
                "schema_version": PUBLIC_SCHEMA_VERSION,
                "response_id": _public_identity(
                    link_key,
                    domain="response_id",
                    value=row["response_id"],
                ),
                "private_response_record_link_sha256": _keyed_link(
                    link_key,
                    domain="private_response_record",
                    value=private_response_record,
                ),
                "private_judgment_record_link_sha256": (
                    _keyed_link(
                        link_key,
                        domain="private_judgment_record",
                        value=private_judgment_record,
                    )
                    if row["judgment_response_id"] is not None
                    else None
                ),
                "context_link_sha256": (
                    None
                    if row["context_block"] is None
                    else _keyed_link(
                        link_key,
                        domain="private_context_block",
                        value=row["context_block"],
                    )
                ),
                "question_link_sha256": _keyed_link(
                    link_key,
                    domain="private_question",
                    value=row["question"],
                ),
                "run_id": _public_identity(link_key, domain="run_id", value=row["run_id"]),
                "eval_id": _public_identity(link_key, domain="eval_id", value=row["eval_id"]),
                "benchmark_lane": _public_category("benchmark_lane", metadata.get("benchmark_lane")),
                "metric_role": _public_category("metric_role", metadata.get("metric_role")),
                "task_family": _public_identity(
                    link_key,
                    domain="task_family",
                    value=row["task_family"],
                ),
                "model_id": _public_identity(link_key, domain="model_id", value=row["model_id"]),
                "model_revision": _public_identity(
                    link_key,
                    domain="model_revision",
                    value=row["model_revision"],
                ),
                "system_variant": _public_category("system_variant", row["system_variant"]),
                "mode": _public_category("mode", row["mode"]),
                "generation_path": _public_category("generation_path", row["generation_path"]),
                "answer_origin": _answer_origin(row["generation_path"], verification),
                "intervention_triggered": _public_bool(
                    verification.get("triggered"),
                    field="verification.triggered",
                ),
                "intervention_action": _public_category(
                    "intervention_action",
                    verification.get("intervention_action") or "no_action",
                ),
                "fallback_applied": _public_bool(
                    verification.get("fallback_applied"),
                    field="verification.fallback_applied",
                ),
                "rewrite_accepted": _public_bool(
                    verification.get("rewrite_accepted"),
                    field="verification.rewrite_accepted",
                ),
                "verifier_requires_review": _public_bool(
                    final_assessment.get("requires_review"),
                    field="verification.final_assessment.requires_review",
                ),
                "semantic_score": _public_number(
                    row["semantic_score"],
                    field="semantic_score",
                    maximum=100.0,
                ),
                "question_validity": _public_category(
                    "question_validity",
                    row["question_validity"] or "not_assessed",
                ),
                "answer_disposition": _public_category(
                    "answer_disposition",
                    row["answer_disposition"] or "not_assessed",
                ),
                "judge_confidence": _public_category(
                    "judge_confidence",
                    row["confidence"] or "not_assessed",
                ),
                "judge_model_id": _public_identity(
                    link_key,
                    domain="judge_model_id",
                    value=row["judge_model_id"],
                ),
                "judge_model_revision": _public_identity(
                    link_key,
                    domain="judge_model_revision",
                    value=row["judge_model_revision"],
                ),
                "judge_generator_relationship": _public_category(
                    "judge_generator_relationship",
                    row["judge_generator_relationship"] or "not_assessed",
                ),
                "agronomic_accuracy": _public_number(
                    dimensions.get("agronomic_accuracy"),
                    field="dimensions.agronomic_accuracy",
                    maximum=4.0,
                ),
                "decision_relevance": _public_number(
                    dimensions.get("decision_relevance"),
                    field="dimensions.decision_relevance",
                    maximum=4.0,
                ),
                "completeness_actionability": _public_number(
                    dimensions.get("completeness_actionability"),
                    field="dimensions.completeness_actionability",
                    maximum=4.0,
                ),
                "calibration_safety": _public_number(
                    dimensions.get("calibration_safety"),
                    field="dimensions.calibration_safety",
                    maximum=4.0,
                ),
                "crop_region_source_fit": _public_number(
                    dimensions.get("crop_region_source_fit"),
                    field="dimensions.crop_region_source_fit",
                    maximum=4.0,
                ),
                "material_error_codes_json": canonical_json(_public_material_error_codes(errors)),
                "needs_source_validation": _public_bool(
                    row["needs_source_validation"],
                    field="needs_source_validation",
                    sqlite_integer=True,
                ),
                "objective_accuracy": _public_number(
                    score.get("accuracy"),
                    field="score.accuracy",
                    maximum=100.0,
                ),
                "parse_valid": _public_bool(
                    score.get("parse_valid"),
                    field="score.parse_valid",
                ),
                "elapsed_seconds": _public_number(
                    row["elapsed_seconds"],
                    field="elapsed_seconds",
                ),
                "prompt_tokens": _public_number(
                    generation.get("prompt_tokens"),
                    field="generation.prompt_tokens",
                    maximum=1_000_000_000,
                    integer=True,
                ),
                "generation_tokens": _public_number(
                    generation.get("generation_tokens"),
                    field="generation.generation_tokens",
                    maximum=1_000_000_000,
                    integer=True,
                ),
            }
        )
    connection.close()
    return output


def _answer_origin(generation_path: Any, verification: dict[str, Any]) -> str:
    path = str(generation_path or "")
    action = str(verification.get("intervention_action") or "")
    if path == "deterministic_evidence_sufficiency_hold":
        return "deterministic_hold"
    fallback_applied = _public_bool(
        verification.get("fallback_applied"),
        field="verification.fallback_applied",
    )
    rewrite_accepted = _public_bool(
        verification.get("rewrite_accepted"),
        field="verification.rewrite_accepted",
    )
    if fallback_applied is True or action == "fallback_or_degraded":
        return "fallback_or_degraded"
    if rewrite_accepted is True or action == "accept_rewrite":
        return "accepted_rewrite"
    if action == "preserve_draft":
        return "preserved_draft"
    return "candidate_output"


def _public_material_error_codes(values: Any) -> list[str]:
    """Map arbitrary judge strings into a fixed, public-safe taxonomy."""

    if not isinstance(values, list):
        return []
    mappings = (
        (("unit",), "unit_error"),
        (("numeric", "arithmetic", "calculation"), "numeric_error"),
        (("wrong_crop", "crop_mismatch"), "wrong_crop"),
        (("wrong_region", "jurisdiction", "regional"), "wrong_region"),
        (("wrong_source", "source_mismatch"), "wrong_source"),
        (("authority", "label", "regulation"), "missing_authority"),
        (("unsafe", "overconfident", "certainty", "guarantee"), "unsafe_certainty"),
        (("invent", "fabricat", "false_premise"), "invented_premise"),
        (("irrelevant", "off_topic"), "irrelevant_response"),
        (("incomplete", "omission", "missing_answer"), "incomplete_answer"),
        (("calibrat", "uncertainty"), "calibration_error"),
        (("source_fit", "crop_region_source"), "source_fit_error"),
        (("unsupported", "unsubstantiated"), "unsupported_claim"),
        (("agronomic", "factual"), "agronomic_factual_error"),
    )
    codes: set[str] = set()
    for raw in values:
        normalized = str(raw or "").strip().casefold().replace("-", "_").replace(" ", "_")
        code = next(
            (candidate for hints, candidate in mappings if any(hint in normalized for hint in hints)),
            "unclassified_material_error",
        )
        if code not in PUBLIC_MATERIAL_ERROR_CODES:  # defensive fail closed
            code = "unclassified_material_error"
        codes.add(code)
    return sorted(codes)


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        raise ValueError("canonical benchmark has no public-safe response rows")
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(
        {
            key: _spreadsheet_safe_cell(value)
            for key, value in row.items()
        }
        for row in rows
    )
    return handle.getvalue().encode("utf-8")


def _spreadsheet_safe_cell(value: Any) -> Any:
    """Make every exported string inert in spreadsheet formula parsers.

    CSV quoting is not a formula-injection boundary: spreadsheet applications
    can still execute quoted cells that begin with a formula marker. Prefixing
    the cell with an apostrophe preserves the visible value while forcing text
    interpretation. Leading whitespace is included because some consumers trim
    it before deciding whether to evaluate a formula.
    """

    if not isinstance(value, str) or not value:
        return value
    marker_index = 0
    while marker_index < len(value):
        character = value[marker_index]
        category = unicodedata.category(character)
        if not (character.isspace() or category in {"Cc", "Cf", "Zl", "Zp", "Zs"}):
            break
        marker_index += 1
    if marker_index < len(value) and value[marker_index] in "=+-@":
        return "'" + value
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_bytes(_csv_bytes(rows))


def _inventory(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(entry["path"]),
            "sha256": str(entry["sha256"]),
            "bytes": int(entry["bytes"]),
            "artifact_class": str(entry["artifact_class"]),
        }
        for entry in entries
    ]


def _public_transform_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "policy_version": PUBLIC_TRANSFORM_POLICY_VERSION,
        "public_schema_version": PUBLIC_SCHEMA_VERSION,
        "privacy_boundary_sha256": _sha256_text(PRIVACY_BOUNDARY),
        "builder_sha256": sha256_file(Path(__file__).resolve()),
        "rows_sha256": hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest(),
        "csv_sha256": hashlib.sha256(_csv_bytes(rows)).hexdigest(),
    }


def _identity_payload(
    *,
    database_sha256: str,
    implementation_commit: str,
    experiment_inventory: list[dict[str, Any]],
    public_transform: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "database_sha256": database_sha256,
        "implementation_commit": implementation_commit,
        "experiment_files": experiment_inventory,
        "public_transform": public_transform,
    }


def _content_address(identity: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()


def _retained_experiment_inventory(bundle_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    contract_root = bundle_dir / "private/retention_contract"
    contract_classes = {
        "build_benchmark_retention_bundle.py": "retention_builder_source",
        "benchmark_retention_bundle_v1.schema.json": "retention_manifest_schema",
    }
    if contract_root.exists():
        for path in sorted(item for item in contract_root.rglob("*") if item.is_file()):
            entries.append(
                {
                    "path": path.relative_to(bundle_dir).as_posix(),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "artifact_class": contract_classes.get(path.name, "retention_contract_artifact"),
                }
            )
    experiment_root = bundle_dir / "private/experiment"
    if experiment_root.exists():
        for path in sorted(item for item in experiment_root.rglob("*") if item.is_file()):
            relative = path.relative_to(experiment_root).as_posix()
            entries.append(
                {
                    "path": f"private/experiment/{relative}",
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "artifact_class": _artifact_class(relative),
                }
            )
    return entries


def _retention_schema_path() -> Path:
    retained_sibling = Path(__file__).resolve().with_name(
        "benchmark_retention_bundle_v1.schema.json"
    )
    if retained_sibling.is_file():
        return retained_sibling
    return ROOT / "configs/schemas/benchmark_retention_bundle_v1.schema.json"


def _validate_manifest_schema(manifest: dict[str, Any]) -> None:
    schema_path = _retention_schema_path()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(value) for value in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"benchmark retention manifest schema validation failed: {details}")


def build_retention_bundle(
    *,
    database: Path,
    bundle_root: Path,
    experiment_dir: Path | None = None,
    implementation_commit: str | None = None,
) -> dict[str, Any]:
    database = database.resolve()
    bundle_root = bundle_root.resolve()
    if not database.is_file():
        raise ValueError(f"canonical benchmark database is missing: {database}")
    snapshot = _database_snapshot(database)
    database_entry = {
        "source": database,
        "path": "private/full_system_benchmark.sqlite3",
        "sha256": sha256_file(database),
        "bytes": database.stat().st_size,
        "artifact_class": "canonical_database",
    }
    experiment_entries = _experiment_entries(experiment_dir)
    retention_sources = (
        (Path(__file__).resolve(), "private/retention_contract/build_benchmark_retention_bundle.py", "retention_builder_source"),
        (
            ROOT / "configs/schemas/benchmark_retention_bundle_v1.schema.json",
            "private/retention_contract/benchmark_retention_bundle_v1.schema.json",
            "retention_manifest_schema",
        ),
    )
    retention_entries = [
        {
            "source": source,
            "path": path,
            "sha256": sha256_file(source),
            "bytes": source.stat().st_size,
            "artifact_class": artifact_class,
        }
        for source, path, artifact_class in retention_sources
    ]
    retention_entries.sort(key=lambda entry: str(entry["path"]))
    private_entries = [*retention_entries, *experiment_entries]
    public_rows = _public_rows(database)
    declared_commit = str(implementation_commit or "not_declared")
    identity_payload = _identity_payload(
        database_sha256=database_entry["sha256"],
        implementation_commit=declared_commit,
        experiment_inventory=_inventory(private_entries),
        public_transform=_public_transform_identity(public_rows),
    )
    bundle_id = _content_address(identity_payload)
    destination = bundle_root / bundle_id
    if destination.exists():
        return verify_retention_bundle(destination)

    bundle_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-retention-", dir=bundle_root) as temporary:
        staging = Path(temporary) / bundle_id
        staging.mkdir()
        for entry in (database_entry, *private_entries):
            target = staging / str(entry["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(entry["source"]), target)
        public_dir = staging / "public_safe"
        public_dir.mkdir(parents=True, exist_ok=True)
        public_csv = public_dir / "response_measurements.csv"
        _write_csv(public_csv, public_rows)
        public_entry = {
            "path": "public_safe/response_measurements.csv",
            "sha256": sha256_file(public_csv),
            "bytes": public_csv.stat().st_size,
            "artifact_class": "public_safe_response_measurements",
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_id": bundle_id,
            "created_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
            "distribution_scope": "private_content_addressed_benchmark_with_public_safe_derivative",
            "implementation_commit": declared_commit,
            "identity": identity_payload,
            "database": snapshot,
            "private_artifacts": _inventory((database_entry, *private_entries)),
            "public_safe_artifacts": [public_entry],
            "privacy_boundary": PRIVACY_BOUNDARY,
            "completion_status": "complete",
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify_retention_bundle(staging)
        try:
            staging.rename(destination)
        except OSError as exc:
            if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY} or not destination.is_dir():
                raise
            return verify_retention_bundle(destination)
    return verify_retention_bundle(destination)


def verify_retention_bundle(bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"retention manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported benchmark retention schema")
    _validate_manifest_schema(manifest)
    if bundle_dir.name != manifest.get("bundle_id"):
        raise ValueError("bundle directory does not match content-addressed bundle_id")
    errors: list[str] = []
    for entry in [*manifest.get("private_artifacts", []), *manifest.get("public_safe_artifacts", [])]:
        path = bundle_dir / str(entry.get("path") or "")
        if not path.is_file():
            errors.append(f"missing:{entry.get('path')}")
            continue
        if path.stat().st_size != int(entry["bytes"]):
            errors.append(f"size:{entry.get('path')}")
        if sha256_file(path) != entry.get("sha256"):
            errors.append(f"sha256:{entry.get('path')}")
    database_path = bundle_dir / "private/full_system_benchmark.sqlite3"
    if not database_path.is_file():
        errors.append("missing:private/full_system_benchmark.sqlite3")
    else:
        actual_snapshot = _database_snapshot(database_path)
        if actual_snapshot != manifest.get("database"):
            errors.append("database_snapshot")
        public_rows = _public_rows(database_path)
        retained_builder = bundle_dir / "private/retention_contract/build_benchmark_retention_bundle.py"
        retained_schema = bundle_dir / "private/retention_contract/benchmark_retention_bundle_v1.schema.json"
        if not retained_builder.is_file() or not retained_schema.is_file():
            errors.append("retention_contract_artifacts")
        public_transform = _public_transform_identity(public_rows)
        if retained_builder.is_file():
            public_transform["builder_sha256"] = sha256_file(retained_builder)
        public_csv_path = bundle_dir / "public_safe/response_measurements.csv"
        if public_csv_path.is_file() and public_csv_path.read_bytes() != _csv_bytes(public_rows):
            errors.append("public_safe_regeneration")
        actual_identity = _identity_payload(
            database_sha256=sha256_file(database_path),
            implementation_commit=str(manifest.get("implementation_commit") or ""),
            experiment_inventory=_retained_experiment_inventory(bundle_dir),
            public_transform=public_transform,
        )
        if actual_identity != manifest.get("identity"):
            errors.append("identity_payload")
        if _content_address(actual_identity) != manifest.get("bundle_id"):
            errors.append("bundle_content_address")
        actual_private_inventory = [
            {
                "path": "private/full_system_benchmark.sqlite3",
                "sha256": sha256_file(database_path),
                "bytes": database_path.stat().st_size,
                "artifact_class": "canonical_database",
            },
            *_retained_experiment_inventory(bundle_dir),
        ]
        if actual_private_inventory != manifest.get("private_artifacts"):
            errors.append("private_artifact_inventory")
        actual_public_inventory = [
            {
                "path": "public_safe/response_measurements.csv",
                "sha256": hashlib.sha256(_csv_bytes(public_rows)).hexdigest(),
                "bytes": len(_csv_bytes(public_rows)),
                "artifact_class": "public_safe_response_measurements",
            }
        ]
        if actual_public_inventory != manifest.get("public_safe_artifacts"):
            errors.append("public_artifact_inventory")
    declared_files = {
        "manifest.json",
        *(
            str(entry.get("path") or "")
            for entry in [*manifest.get("private_artifacts", []), *manifest.get("public_safe_artifacts", [])]
        ),
    }
    actual_files = {
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file()
    }
    if actual_files != declared_files:
        errors.append("artifact_inventory_exactness")
    if errors:
        raise ValueError("benchmark retention verification failed: " + ", ".join(errors))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "verified",
        "bundle_id": manifest["bundle_id"],
        "bundle_dir": str(bundle_dir),
        "private_artifact_count": len(manifest.get("private_artifacts", [])),
        "public_safe_artifact_count": len(manifest.get("public_safe_artifacts", [])),
        "canonical_response_count": manifest.get("database", {}).get("canonical_response_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--experiment-dir", type=Path)
    parser.add_argument("--implementation-commit")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        report = verify_retention_bundle(args.verify)
    else:
        if args.database is None or args.bundle_root is None:
            parser.error("--database and --bundle-root are required unless --verify is used")
        report = build_retention_bundle(
            database=args.database,
            bundle_root=args.bundle_root,
            experiment_dir=args.experiment_dir,
            implementation_commit=args.implementation_commit,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
