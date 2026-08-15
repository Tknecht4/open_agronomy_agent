#!/usr/bin/env python3
"""Reproduce the public RC3 development-checkpoint tables and figures.

This script deliberately reads only the nine completion-receipted RC3 trials.
It never discovers bundles by globbing the retention root, never exports answer
text or prompts, and never converts missing semantic review into a zero score.

The published outputs describe an exposed development regression and harness
checkpoint.  They are not a model leaderboard, a v3 benchmark result, or an
estimate of agronomic correctness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union


SCHEMA_VERSION = "open_agronomy_agent.rc3_checkpoint_analysis.v1"
VALIDATION_SCHEMA = "open_agronomy_agent.rc3_checkpoint_validation.v1"
ARTIFACT_SCHEMA = "open_agronomy_agent.rc3_checkpoint_artifacts.v1"
ARTIFACT_MANIFEST_RELATIVE = "source_data/artifact_manifest.json"
ANALYSIS_DATE = "2026-08-15"
ANALYSIS_SEED = 20260815
BOOTSTRAP_DRAWS = 50_000
EXPECTED_SUITE_SHA256 = "5c3ce59195ac603d2dd8ec5f36f3672b3ee0c20227cdb4fd301dfe3848a83c63"
EXPECTED_SOURCE_SNAPSHOT_SHA256 = "25fb45e1d1ea7476a8d0b58ef563dc6afb7bc391e85f97a72324491cb6c273c3"
EXPECTED_IMPLEMENTATION_COMMIT = "3e30fb5de38105fa5bba3845411eb2174c21d3c4"
EXPECTED_BENCHMARK_ID = "open_agronomy_canadian_performance_v1_runtime_v2"

MODEL_SPECS: dict[str, dict[str, str]] = {
    "gemma3_270m_rc3": {
        "label": "Gemma 3 270M",
        "short_label": "Gemma 3",
        "model_id": "mlx-community/gemma-3-270m-it-4bit",
        "backend": "MLX local",
        "verification_profile": "constrained",
    },
    "gemma4_e2b_rc3": {
        "label": "Gemma 4 E2B",
        "short_label": "Gemma 4",
        "model_id": "mlx-community/gemma-4-e2b-it-4bit",
        "backend": "MLX local",
        "verification_profile": "balanced",
    },
    "luna_high_rc3": {
        "label": "Luna High",
        "short_label": "Luna",
        "model_id": "gpt-5.6-luna",
        "backend": "Codex App Server",
        "verification_profile": "frontier",
    },
}
TRIAL_IDS = ("trial-001", "trial-002", "trial-003")
ARM_ORDER = ("raw_model", "kernel_only", "kernel_field_context", "full_system")
ARM_LABELS = {
    "raw_model": "Raw",
    "kernel_only": "Kernel",
    "kernel_field_context": "Kernel + field",
    "full_system": "Full system",
}
LANE_ORDER = (
    "canadian_decision_quality",
    "canadian_advisory_transfer",
    "field_history_lineage",
    "official_source_answer_boundary",
    "retrieval_lineage",
    "objective_agronomic_calculation",
)
LANE_LABELS = {
    "canadian_decision_quality": "Canadian decision quality",
    "canadian_advisory_transfer": "Advisory transfer",
    "field_history_lineage": "Field-history lineage",
    "official_source_answer_boundary": "Official-source boundary",
    "retrieval_lineage": "Retrieval lineage",
    "objective_agronomic_calculation": "Objective calculations",
}
OBJECTIVE_LANE = "objective_agronomic_calculation"
LEXICAL_LANE = "official_source_answer_boundary"
LOCAL_GUARD_IDS = {
    "field_data_guard",
    "fertility_guard",
    "label_guard",
    "nutrient_4r_guard",
    "pesticide_safety_guard",
    "resistance_management_guard",
    "salinity_sodicity_guard",
    "soil_structure_guard",
    "weather_guard",
}
FRENCH_MARKERS = {
    "avant", "avec", "culture", "dans", "des", "donnees", "etiquette",
    "faire", "la", "les", "mesures", "ne", "pas", "pour", "sol", "source",
    "verifier",
}
PUBLISHED_FILES = (
    "README.md",
    "main.tex",
    "references.bib",
    "generated_results.tex",
    "generated_tables.tex",
    "paper_evidence_manifest.yaml",
    "paper.pdf",
    "scripts/analyze_rc3_checkpoint.py",
    "source_data/public_safe_response_measurements.csv",
    "source_data/trial_inventory.csv",
    "source_data/lane_coverage.csv",
    "source_data/deterministic_metric_summary.csv",
    "source_data/paired_arm_effects.csv",
    "source_data/retrieval_lineage_summary.csv",
    "source_data/harness_activation_summary.csv",
    "source_data/interface_trace_summary.csv",
    "source_data/repeatability_summary.csv",
    "source_data/resource_summary.csv",
    "source_data/checkpoint_validation_receipt.json",
    "source_data/analysis_manifest.json",
    "figures/rc3_evidence_coverage.svg",
    "figures/rc3_evidence_coverage.pdf",
    "figures/rc3_deterministic_metrics.svg",
    "figures/rc3_deterministic_metrics.pdf",
    "figures/rc3_harness_behavior.svg",
    "figures/rc3_harness_behavior.pdf",
    "figures/rc3_repeatability_latency.svg",
    "figures/rc3_repeatability_latency.pdf",
    "figures/manifest.json",
)


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "configs").is_dir():
            return candidate
    raise RuntimeError("could not locate repository root")


ROOT = _repo_root()
DEFAULT_PAPER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPLETION_ROOT = ROOT / "outputs/open_agronomy_canadian_performance_v1_runtime_v2_rc3"
DEFAULT_RETENTION_ROOT = ROOT / "outputs/benchmark_retention"
DEFAULT_SUITE = ROOT / "data/eval/open_agronomy_canadian_performance_v1.jsonl"
DEFAULT_STORE_MANIFEST = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14/store_manifest.json"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            rows.append(value)
    return rows


def _json_object(value: Optional[str]) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _round(value: Optional[float], digits: int = 4) -> Union[float, str]:
    return "" if value is None or math.isnan(value) else round(value, digits)


def _bootstrap_case_mean(values: Sequence[float], *, seed_offset: int) -> tuple[float, float]:
    """Return a case-resampling sensitivity interval over trial-averaged cases."""

    import numpy as np

    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(ANALYSIS_SEED + seed_offset)
    draws = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    chunk = 2_000
    for start in range(0, BOOTSTRAP_DRAWS, chunk):
        size = min(chunk, BOOTSTRAP_DRAWS - start)
        indexes = rng.integers(0, data.size, size=(size, data.size))
        draws[start : start + size] = data[indexes].mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def _output_contract_pass(output: str) -> bool:
    words = re.findall(r"\b\w+\b", output)
    paragraphs = [part for part in re.split(r"\n\s*\n", output.strip()) if part.strip()]
    forbidden = bool(re.search(r"(?m)^\s*(?:[-*#]|\d+[.)]\s)", output))
    return bool(output.strip()) and len(words) <= 170 and len(paragraphs) == 2 and not forbidden


def _french_pass(output: str) -> bool:
    normalized = unicodedata.normalize("NFKD", output.lower().replace("œ", "oe"))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    tokens = set(re.findall(r"[a-z]+", normalized))
    return len(tokens & FRENCH_MARKERS) >= 4


def _source_records(cases: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    records: dict[str, dict[str, Any]] = {}
    for case in cases:
        source_path = str(case["source_suite"])
        if source_path not in cache:
            cache[source_path] = _read_jsonl(ROOT / source_path)
        source_eval_id = str(case["source_eval_id"])
        matches = [
            row for row in cache[source_path]
            if str(row.get("eval_id") or row.get("id") or "") == source_eval_id
        ]
        if len(matches) != 1:
            raise ValueError(f"source lineage mismatch for {case['eval_id']}: {len(matches)} matches")
        records[str(case["eval_id"])] = matches[0]
    return records


def _completion_specs() -> list[tuple[str, str]]:
    return [(model_key, trial_id) for model_key in MODEL_SPECS for trial_id in TRIAL_IDS]


def _load_trial(
    *,
    completion_root: Path,
    retention_root: Path,
    model_key: str,
    trial_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    trial_dir = completion_root / model_key / trial_id
    completion_path = trial_dir / "benchmark_retention_completion.json"
    database_path = trial_dir / "full_system_benchmark.sqlite3"
    invocation_path = trial_dir / "benchmark_invocation.json"
    for path in (completion_path, database_path, invocation_path):
        if not path.is_file():
            raise ValueError(f"missing canonical trial artifact: {path}")

    completion = _load_object(completion_path)
    if completion.get("status") != "complete" or completion.get("benchmark_id") != EXPECTED_BENCHMARK_ID:
        raise ValueError(f"invalid completion receipt: {completion_path}")
    bundle_id = str((completion.get("retention") or {}).get("bundle_id") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", bundle_id):
        raise ValueError(f"invalid retention bundle id: {bundle_id!r}")
    manifest_path = retention_root / bundle_id / "manifest.json"
    manifest = _load_object(manifest_path)
    if manifest.get("bundle_id") != bundle_id or manifest.get("completion_status") != "complete":
        raise ValueError(f"invalid retained manifest: {manifest_path}")
    if manifest.get("implementation_commit") != EXPECTED_IMPLEMENTATION_COMMIT:
        raise ValueError(f"unexpected implementation commit in {manifest_path}")

    database_sha = _sha256_path(database_path)
    if database_sha != (manifest.get("identity") or {}).get("database_sha256"):
        raise ValueError(f"live database is not the retained database: {database_path}")
    if _sha256_path(invocation_path) != completion.get("terminal_invocation_sha256"):
        raise ValueError(f"terminal invocation mismatch: {invocation_path}")
    invocation = _load_object(invocation_path)
    completed_arms = invocation.get("completed")
    if (
        invocation.get("status") != "execution_complete"
        or not isinstance(completed_arms, list)
        or len(completed_arms) != 4
        or {str(item.get("mode") or "") for item in completed_arms if isinstance(item, dict)}
        != {"raw_model", "baseline", "kernel_field_context", "agronomic_rag"}
    ):
        raise ValueError(f"trial invocation is not complete: {invocation_path}")
    if invocation.get("benchmark_suite_sha256") != EXPECTED_SUITE_SHA256:
        raise ValueError(f"suite identity mismatch: {invocation_path}")
    if invocation.get("benchmark_source_snapshot_sha256") != EXPECTED_SOURCE_SNAPSHOT_SHA256:
        raise ValueError(f"source snapshot mismatch: {invocation_path}")
    if invocation.get("automated_judge_requested") is not False:
        raise ValueError(f"unexpected automated semantic judge: {invocation_path}")

    trial_root = trial_dir.resolve(strict=True)
    run_dirs: dict[str, Path] = {}
    final_partial_identical_arms = 0
    for item in completed_arms:
        mode = str(item["mode"])
        run_dir = Path(str(item.get("run_dir") or ""))
        if not run_dir.is_absolute():
            run_dir = trial_dir / run_dir
        run_dir = run_dir.resolve(strict=True)
        if not run_dir.is_relative_to(trial_root):
            raise ValueError(f"completed run is outside its trial directory: {run_dir}")
        final_path = run_dir / "outputs.jsonl"
        partial_path = run_dir / "outputs.partial.jsonl"
        if not final_path.is_file() or not partial_path.is_file():
            raise ValueError(f"completed arm is missing final or partial output: {run_dir}")
        if final_path.read_bytes() != partial_path.read_bytes():
            raise ValueError(f"completed arm final and partial outputs differ: {run_dir}")
        if len(_read_jsonl(final_path)) != 241:
            raise ValueError(f"completed arm does not contain 241 rows: {run_dir}")
        run_dirs[mode] = run_dir
        final_partial_identical_arms += 1

    review_dir = trial_dir / "review_packets" / model_key
    review_manifest_path = review_dir / "manifest.json"
    review_manifest = _load_object(review_manifest_path)
    if (
        review_manifest.get("status") != "ready_for_two_phase_independent_review"
        or review_manifest.get("rows") != 180
        or review_manifest.get("model_identity_exposed") is not False
        or review_manifest.get("automated_judge_result_exposed") is not False
        or review_manifest.get("generation_path_exposed") is not False
    ):
        raise ValueError(f"invalid agronomist review packet manifest: {review_manifest_path}")
    expected_review_files = {
        "phase_a": "phase_a_blind_question_answer.jsonl",
        "phase_b": "phase_b_reference_assisted.jsonl",
        "identity_map": "private_identity_map.jsonl",
        "review_form": "review_form.csv",
    }
    for key, expected_name in expected_review_files.items():
        record = review_manifest.get(key) or {}
        if record.get("path") != expected_name:
            raise ValueError(f"review packet {key} path mismatch: {review_manifest_path}")
        artifact_path = review_dir / expected_name
        if not artifact_path.is_file() or _sha256_path(artifact_path) != record.get("sha256"):
            raise ValueError(f"review packet {key} hash mismatch: {artifact_path}")
    packet_rows: dict[str, list[dict[str, Any]]] = {}
    for key in ("phase_a", "phase_b", "identity_map"):
        packet_rows[key] = _read_jsonl(review_dir / expected_review_files[key])
        if len(packet_rows[key]) != 180:
            raise ValueError(f"review packet {key} does not contain 180 rows: {review_dir}")

    sources = review_manifest.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError(f"review packet source inventory mismatch: {review_manifest_path}")
    expected_sources = {
        "model_only": run_dirs["raw_model"] / "outputs.jsonl",
        "full_system": run_dirs["agronomic_rag"] / "outputs.jsonl",
    }
    for source in sources:
        label = str(source.get("label") or "")
        if label not in expected_sources:
            raise ValueError(f"unknown review packet source label: {label!r}")
        source_path = Path(str(source.get("path") or "")).resolve(strict=True)
        if source_path != expected_sources[label] or _sha256_path(source_path) != source.get("sha256"):
            raise ValueError(f"review packet source mismatch for {label}: {review_manifest_path}")

    review_form_path = review_dir / "review_form.csv"
    with review_form_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        review_rows = list(reader)
    review_columns = review_manifest.get("review_columns")
    if list(reader.fieldnames or []) != review_columns or len(review_rows) != 180:
        raise ValueError(f"review form schema or row-count mismatch: {review_form_path}")
    review_ids = [str(row.get("review_id") or "") for row in review_rows]
    if any(not value for value in review_ids) or len(set(review_ids)) != 180:
        raise ValueError(f"review form identities are not unique and complete: {review_form_path}")
    expected_review_ids = set(review_ids)
    for key in ("phase_a", "phase_b", "identity_map"):
        packet_review_ids = [str(row.get("review_id") or "") for row in packet_rows[key]]
        if len(set(packet_review_ids)) != 180 or set(packet_review_ids) != expected_review_ids:
            raise ValueError(f"review packet {key} identities do not match the review form: {review_dir}")
    if {str(row.get("review_stage") or "") for row in packet_rows["phase_a"]} != {
        "phase_a_answer_and_question_only"
    }:
        raise ValueError(f"review packet phase A stage mismatch: {review_dir}")
    if {str(row.get("review_stage") or "") for row in packet_rows["phase_b"]} != {
        "phase_b_source_assisted_after_phase_a_lock"
    }:
        raise ValueError(f"review packet phase B stage mismatch: {review_dir}")
    identity_labels: dict[str, set[str]] = defaultdict(set)
    for row in packet_rows["identity_map"]:
        identity_labels[str(row.get("eval_id") or "")].add(
            str(row.get("source_label") or "")
        )
    if (
        len(identity_labels) != 90
        or "" in identity_labels
        or any(labels != {"model_only", "full_system"} for labels in identity_labels.values())
    ):
        raise ValueError(f"review packet is not 90 paired raw/full cases: {review_dir}")
    review_value_columns = [column for column in review_columns if column != "review_id"]
    review_rows_completed = sum(
        any(str(row.get(column) or "").strip() for column in review_value_columns)
        for row in review_rows
    )
    if review_rows_completed != 0:
        raise ValueError(f"review form is no longer blank: {review_form_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError(f"database integrity failure: {database_path}")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError(f"database foreign-key failure: {database_path}")
    counts = {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("benchmark_run", "benchmark_case", "response", "semantic_judgment", "judge_run", "judge_assessment")
    }
    if counts != {
        "benchmark_run": 4,
        "benchmark_case": 241,
        "response": 964,
        "semantic_judgment": 0,
        "judge_run": 0,
        "judge_assessment": 0,
    }:
        raise ValueError(f"unexpected trial database counts for {model_key}/{trial_id}: {counts}")

    documents: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        "SELECT response_id, rank, doc_id, source_id, text FROM retrieved_document ORDER BY response_id, rank"
    ):
        documents[str(row["response_id"])].append(dict(row))
    graph_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        "SELECT response_id, rank, node_id, name, evidence FROM graph_hit ORDER BY response_id, rank"
    ):
        graph_hits[str(row["response_id"])].append(dict(row))

    query = """
        SELECT m.model_id, m.model_revision, m.model_config_sha256,
               br.mode, br.system_variant, br.trial_id, br.generation_seed,
               br.case_order_seed, br.judge_seed, br.run_execution_id,
               r.response_id, r.eval_id, r.observation_id, r.matched_trial_key,
               r.ordinal, r.output, r.output_sha256, r.elapsed_seconds,
               r.score_json, r.metadata_json, r.verification_json,
               r.exact_messages_json, r.context_block, r.field_context_json,
               r.generation_stats_json, r.generation_path,
               c.task_family, c.question_sha256, c.eval_metadata_json
        FROM response r
        JOIN benchmark_run br ON br.run_id = r.run_id
        JOIN model m ON m.model_key = br.model_key
        JOIN benchmark_case c ON c.eval_id = r.eval_id
        WHERE br.is_canonical = 1
        ORDER BY br.system_variant, r.ordinal
    """
    database_rows = [dict(row) for row in connection.execute(query)]
    connection.close()
    if len(database_rows) != 964:
        raise ValueError(f"expected 964 rows in {database_path}, found {len(database_rows)}")

    by_arm = Counter(str(row["system_variant"]) for row in database_rows)
    if by_arm != Counter({arm: 241 for arm in ARM_ORDER}):
        raise ValueError(f"arm count mismatch for {model_key}/{trial_id}: {by_arm}")
    if {str(row["trial_id"]) for row in database_rows} != {trial_id}:
        raise ValueError(f"trial identity mismatch in {database_path}")
    if {str(row["model_id"]) for row in database_rows} != {MODEL_SPECS[model_key]["model_id"]}:
        raise ValueError(f"model identity mismatch in {database_path}")
    if len({str(row["observation_id"]) for row in database_rows}) != 964:
        raise ValueError(f"observation identities are not unique in {database_path}")

    rows: list[dict[str, Any]] = []
    for raw in database_rows:
        score = _json_object(raw.pop("score_json"))
        metadata = _json_object(raw.pop("metadata_json"))
        messages_value = json.loads(str(raw.pop("exact_messages_json") or "[]"))
        exact_messages = messages_value if isinstance(messages_value, list) else []
        context_block = str(raw.pop("context_block") or "")
        field_context = _json_object(raw.pop("field_context_json"))
        verification = metadata.get("answer_verification") or _json_object(raw.pop("verification_json"))
        generation = metadata.get("generation_stats") or _json_object(raw.pop("generation_stats_json"))
        eval_metadata = _json_object(raw.pop("eval_metadata_json"))
        response_id = str(raw["response_id"])
        lane = str(eval_metadata.get("benchmark_lane") or "")
        tool_trace = score.get("tool_trace_audit") or {}
        expected_guards = sorted(set(tool_trace.get("expected_local_guards") or []))
        routed_guards = sorted(set(tool_trace.get("routed_local_guards") or []))
        missing_guards = sorted(set(tool_trace.get("missing_local_guards") or []))
        admission = metadata.get("context_admission") or {}
        intervention = metadata.get("evidence_intervention") or {}
        route = metadata.get("route") or {}
        evidence_fabric = metadata.get("evidence_fabric") or {}
        tool_invocations = metadata.get("tool_invocations") or []
        tool_results = metadata.get("tool_results") or []
        output = str(raw.pop("output"))
        objective_accuracy = score.get("accuracy") if lane == OBJECTIVE_LANE else None
        diagnostic_score = score.get("score") if score.get("proxy_valid") is True else None
        rows.append(
            {
                **raw,
                "model_key": model_key,
                "model_label": MODEL_SPECS[model_key]["label"],
                "benchmark_lane": lane,
                "metric_role": str(eval_metadata.get("metric_role") or ""),
                "language": str(eval_metadata.get("language") or "English"),
                "objective_accuracy": objective_accuracy,
                "diagnostic_score": diagnostic_score,
                "diagnostic_construct": str(score.get("construct") or ""),
                "score_rubric": str(score.get("rubric") or ""),
                "proxy_valid": score.get("proxy_valid") is True,
                "parse_valid": score.get("parse_valid"),
                "generation_path_class": str(raw.get("generation_path") or "model_generation"),
                "verification_action": str(verification.get("intervention_action") or "not_run"),
                "verification_triggered": verification.get("triggered") is True,
                "answerability_state": str(intervention.get("answerability_state") or "not_applicable"),
                "evidence_intervention_status": str(intervention.get("status") or "not_applicable"),
                "context_admission_policy": str(admission.get("policy") or "not_applicable"),
                "document_count": len(documents.get(response_id, [])),
                "graph_hit_count": len(graph_hits.get(response_id, [])),
                "tool_invocation_count": len(tool_invocations),
                "tool_result_count": len(tool_results),
                "expected_guard_count": len(expected_guards),
                "routed_guard_count": len(routed_guards),
                "missing_guard_count": len(missing_guards),
                "output_contract_pass": _output_contract_pass(output),
                "french_language_pass": _french_pass(output) if eval_metadata.get("language") == "French" else None,
                "prompt_tokens": generation.get("prompt_tokens"),
                "generation_tokens": generation.get("generation_tokens"),
                "_input_lineage_present": bool(
                    exact_messages
                    and all(
                        isinstance(message, dict)
                        and message.get("role")
                        and message.get("content")
                        for message in exact_messages
                    )
                ),
                "_field_context_eligible": bool(field_context),
                "_field_context_bound": bool(field_context and context_block.strip()),
                "_route_trace_present": all(
                    route.get(key) for key in ("question_type", "risk_level", "namespaces")
                ),
                "_context_admission_trace_present": bool(admission),
                "_evidence_lineage_present": bool(
                    evidence_fabric.get("record_sha256")
                    and evidence_fabric.get("evidence_packet")
                ),
                "_output": output,
                "_score": score,
                "_metadata": metadata,
                "_documents": documents.get(response_id, []),
                "_graph_hits": graph_hits.get(response_id, []),
            }
        )

    run_execution_ids = {str(row["run_execution_id"]) for row in rows}
    if len(run_execution_ids) != 4:
        raise ValueError(f"expected four execution identities for {model_key}/{trial_id}")

    model_row = rows[0]
    inventory = {
        "model_key": model_key,
        "model_label": MODEL_SPECS[model_key]["label"],
        "model_id": model_row["model_id"],
        "model_revision": model_row["model_revision"],
        "model_config_sha256": model_row["model_config_sha256"],
        "trial_id": trial_id,
        "generation_seed": model_row["generation_seed"],
        "case_order_seed": model_row["case_order_seed"],
        "database_sha256": database_sha,
        "retention_bundle_id": bundle_id,
        "terminal_invocation_sha256": completion["terminal_invocation_sha256"],
        "implementation_commit": EXPECTED_IMPLEMENTATION_COMMIT,
        "benchmark_source_snapshot_sha256": EXPECTED_SOURCE_SNAPSHOT_SHA256,
        "responses": 964,
        "arms": 4,
        "semantic_judgments": 0,
        "automated_judge_requested": False,
        "final_partial_identical_arms": final_partial_identical_arms,
        "review_packet_rows": len(review_rows),
        "review_rows_completed": review_rows_completed,
    }
    return inventory, rows, {"documents": documents, "graph_hits": graph_hits}


def _public_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "model_key", "model_label", "model_id", "model_revision", "model_config_sha256",
        "trial_id", "generation_seed", "case_order_seed", "system_variant", "eval_id",
        "observation_id", "matched_trial_key", "task_family", "benchmark_lane", "metric_role",
        "language", "output_sha256", "elapsed_seconds", "generation_path_class",
        "objective_accuracy", "deterministic_diagnostic_score", "score_construct", "score_rubric",
        "proxy_valid", "parse_valid", "answerability_state", "evidence_intervention_status",
        "context_admission_policy", "verification_action", "verification_triggered",
        "document_count", "graph_hit_count", "tool_invocation_count", "tool_result_count",
        "expected_guard_count", "routed_guard_count", "missing_guard_count",
        "output_contract_pass", "french_language_pass", "prompt_tokens", "generation_tokens",
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        projected = {field: row.get(field, "") for field in fields}
        projected["deterministic_diagnostic_score"] = (
            row.get("diagnostic_score", "")
            if row.get("benchmark_lane") == LEXICAL_LANE
            else ""
        )
        projected["score_construct"] = row.get("diagnostic_construct", "")
        output.append(projected)
    return output


PUBLIC_FIELDS = list(_public_rows([{}])[0])


def _lane_coverage(suite: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane in LANE_ORDER:
        cases = [case for case in suite if case.get("benchmark_lane") == lane]
        objective = len(cases) if lane == OBJECTIVE_LANE else 0
        lexical = sum(bool(case.get("lexical_contract_available")) for case in cases) if lane == LEXICAL_LANE else 0
        unscored = len(cases) - objective - lexical
        rows.append(
            {
                "benchmark_lane": lane,
                "lane_label": LANE_LABELS[lane],
                "cases": len(cases),
                "objective_numeric_cases": objective,
                "lexical_regression_cases": lexical,
                "unscored_cases": unscored,
                "interpretation": (
                    "objective numeric tolerance" if lane == OBJECTIVE_LANE else
                    "lexical contract regression only; not answer quality" if lane == LEXICAL_LANE else
                    "trace or independent human review pending"
                ),
            }
        )
    if sum(row["cases"] for row in rows) != 241:
        raise ValueError("lane coverage no longer totals 241")
    if sum(row["objective_numeric_cases"] + row["lexical_regression_cases"] for row in rows) != 49:
        raise ValueError("deterministically scored case coverage no longer totals 49")
    return rows


def _metric_value(row: Mapping[str, Any], metric: str) -> Optional[float]:
    value = row["objective_accuracy"] if metric == "objective_numeric_tolerance" else row["diagnostic_score"]
    return None if value in (None, "") else float(value)


def _metric_summaries(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    metrics = (
        ("objective_numeric_tolerance", OBJECTIVE_LANE),
        ("official_source_lexical_regression", LEXICAL_LANE),
    )
    index = {(row["model_key"], row["trial_id"], row["system_variant"], row["eval_id"]): row for row in rows}
    for model_key in MODEL_SPECS:
        for metric_index, (metric, lane) in enumerate(metrics):
            eval_ids = sorted({str(row["eval_id"]) for row in rows if row["benchmark_lane"] == lane and _metric_value(row, metric) is not None})
            for arm in ARM_ORDER:
                trial_means: list[float] = []
                case_means: list[float] = []
                for trial_id in TRIAL_IDS:
                    values = [_metric_value(index[(model_key, trial_id, arm, eval_id)], metric) for eval_id in eval_ids]
                    if any(value is None for value in values):
                        raise ValueError(f"missing {metric} value for {model_key}/{trial_id}/{arm}")
                    trial_means.append(statistics.mean(float(value) for value in values if value is not None))
                for eval_id in eval_ids:
                    values = [_metric_value(index[(model_key, trial_id, arm, eval_id)], metric) for trial_id in TRIAL_IDS]
                    case_means.append(statistics.mean(float(value) for value in values if value is not None))
                low, high = _bootstrap_case_mean(
                    case_means,
                    # The same case indexes are used for every candidate and
                    # arm in a metric family, preserving the frozen pairing.
                    seed_offset=metric_index,
                )
                summaries.append(
                    {
                        "model_key": model_key,
                        "model_label": MODEL_SPECS[model_key]["label"],
                        "system_variant": arm,
                        "arm_label": ARM_LABELS[arm],
                        "metric": metric,
                        "cases": len(eval_ids),
                        "trial_001": round(trial_means[0], 4),
                        "trial_002": round(trial_means[1], 4),
                        "trial_003": round(trial_means[2], 4),
                        "finite_suite_mean": round(statistics.mean(case_means), 4),
                        "sensitivity_interval_low": round(low, 4),
                        "sensitivity_interval_high": round(high, 4),
                        "interval_definition": f"{BOOTSTRAP_DRAWS} case resamples with shared indexes across candidate/arm cells in this metric family; effective seed {ANALYSIS_SEED + metric_index}; not a population CI",
                    }
                )
            comparisons = (
                ("kernel_only", "raw_model"),
                ("kernel_field_context", "kernel_only"),
                ("full_system", "kernel_field_context"),
                ("full_system", "raw_model"),
            )
            for right, left in comparisons:
                case_deltas: list[float] = []
                trial_deltas: list[float] = []
                for trial_id in TRIAL_IDS:
                    deltas = [
                        float(_metric_value(index[(model_key, trial_id, right, eval_id)], metric))
                        - float(_metric_value(index[(model_key, trial_id, left, eval_id)], metric))
                        for eval_id in eval_ids
                    ]
                    trial_deltas.append(statistics.mean(deltas))
                for eval_id in eval_ids:
                    deltas = [
                        float(_metric_value(index[(model_key, trial_id, right, eval_id)], metric))
                        - float(_metric_value(index[(model_key, trial_id, left, eval_id)], metric))
                        for trial_id in TRIAL_IDS
                    ]
                    case_deltas.append(statistics.mean(deltas))
                low, high = _bootstrap_case_mean(
                    case_deltas,
                    seed_offset=1000 + metric_index,
                )
                effects.append(
                    {
                        "model_key": model_key,
                        "model_label": MODEL_SPECS[model_key]["label"],
                        "metric": metric,
                        "comparison": f"{right}_minus_{left}",
                        "cases": len(eval_ids),
                        "trial_001": round(trial_deltas[0], 4),
                        "trial_002": round(trial_deltas[1], 4),
                        "trial_003": round(trial_deltas[2], 4),
                        "finite_suite_mean_delta": round(statistics.mean(case_deltas), 4),
                        "sensitivity_interval_low": round(low, 4),
                        "sensitivity_interval_high": round(high, 4),
                        "interval_definition": f"{BOOTSTRAP_DRAWS} paired case resamples of within-case arm differences; effective seed {ANALYSIS_SEED + 1000 + metric_index}; not a population CI",
                    }
                )
    return summaries, effects


def _objective_parser_audit(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    full = [row for row in rows if row["system_variant"] == "full_system" and row["benchmark_lane"] == OBJECTIVE_LANE]
    audited = 0
    false_negative_ids: set[str] = set()
    false_negative_cases: dict[str, dict[str, Any]] = {}
    for row in full:
        score = row["_score"]
        tool_results = row["_metadata"].get("tool_results") or []
        if len(tool_results) != 1:
            raise ValueError(f"expected one typed calculation result for {row['eval_id']}")
        payload = tool_results[0].get("payload") or {}
        value = float(payload["value"])
        reference = float(score["reference_numeric"])
        tolerance = float(score["absolute_tolerance"])
        if abs(value - reference) <= tolerance:
            audited += 1
        if float(row["objective_accuracy"]) == 0.0 and abs(value - reference) <= tolerance:
            case_id = str(row["eval_id"]).rsplit("::", 1)[-1]
            false_negative_ids.add(case_id)
            detail = {
                "eval_id": case_id,
                "typed_tool_value": round(value, 3),
                "typed_tool_unit": str(payload.get("unit") or ""),
                "reference_numeric": reference,
                "absolute_tolerance": tolerance,
                "frozen_parser_accuracy": float(row["objective_accuracy"]),
            }
            if case_id in false_negative_cases and false_negative_cases[case_id] != detail:
                raise ValueError(f"parser-audit detail drift across trials: {case_id}")
            false_negative_cases[case_id] = detail
    if audited != len(full) or false_negative_ids != {"ca_calc_map_04", "ca_calc_urea_03"}:
        raise ValueError(f"unexpected parser audit result: {audited}/{len(full)}, {sorted(false_negative_ids)}")
    return {
        "canonical_full_system_cases": 16,
        "canonical_parser_passes": 14,
        "canonical_parser_accuracy_percent": 87.5,
        "post_run_tool_payload_cases": 16,
        "post_run_tool_payload_within_tolerance": 16,
        "post_run_tool_payload_accuracy_percent": 100.0,
        "false_negative_case_ids": sorted(false_negative_ids),
        "false_negative_cases": [
            false_negative_cases[case_id] for case_id in sorted(false_negative_cases)
        ],
        "interpretation": "The 87.5% frozen score is preserved. The 100% value is a post-run parser-sensitivity audit of typed tool payloads, not a replacement score.",
    }


def _retrieval_summary(
    rows: Sequence[Mapping[str, Any]],
    suite: Sequence[Mapping[str, Any]],
    source_records: Mapping[str, Mapping[str, Any]],
    store_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reference = {
        str(row["eval_id"]): row
        for row in rows
        if row["model_key"] == "gemma3_270m_rc3"
        and row["trial_id"] == "trial-001"
        and row["system_variant"] == "full_system"
    }
    admitted_sources = set(store_manifest.get("included_source_ids") or [])
    output: list[dict[str, Any]] = []
    for lane in ("retrieval_lineage", "field_history_lineage"):
        cases = [case for case in suite if case.get("benchmark_lane") == lane]
        expected_source_cases = source_hits = 0
        admitted_expected_cases = admitted_hits = unadmitted_cases = unadmitted_leaks = 0
        negative_controls = 0
        pattern_cases = complete_pattern_cases = pattern_hits = pattern_total = 0
        expected_card_cases = expected_card_ids = card_hits = 0
        for case in cases:
            eval_id = str(case["eval_id"])
            source = source_records[eval_id]
            row = reference[eval_id]
            docs = row["_documents"]
            retrieved_sources = {str(doc.get("source_id") or "") for doc in docs}
            expected = (
                [str(source["support_source_id"])]
                if source.get("support_source_id")
                else [str(value) for value in source.get("expected_source_ids") or []]
            )
            if expected:
                expected_source_cases += 1
                hit = any(value in retrieved_sources for value in expected)
                source_hits += hit
                if any(value in admitted_sources for value in expected):
                    admitted_expected_cases += 1
                    admitted_hits += hit
                else:
                    unadmitted_cases += 1
                    unadmitted_leaks += hit
            else:
                negative_controls += 1
            patterns = [str(value) for value in source.get("required_retrieval_patterns") or []]
            if patterns:
                pattern_cases += 1
                text = "\n".join(str(doc.get("text") or "") for doc in docs)
                hits = [bool(re.search(pattern, text, re.IGNORECASE)) for pattern in patterns]
                complete_pattern_cases += all(hits)
                pattern_hits += sum(hits)
                pattern_total += len(hits)
            cards = [str(value) for value in source.get("expected_card_ids") or []]
            if cards:
                expected_card_cases += 1
                expected_card_ids += len(cards)
                graph_nodes = {str(hit.get("node_id") or "") for hit in row["_graph_hits"]}
                card_hits += sum(card in graph_nodes for card in cards)
        output.append(
            {
                "benchmark_lane": lane,
                "cases": len(cases),
                "expected_source_cases": expected_source_cases,
                "expected_source_case_hits": source_hits,
                "expected_source_case_recall": _round(source_hits / expected_source_cases if expected_source_cases else None),
                "negative_control_cases": negative_controls,
                "admitted_expected_source_cases": admitted_expected_cases,
                "admitted_expected_source_hits": admitted_hits,
                "admission_aware_recall": _round(admitted_hits / admitted_expected_cases if admitted_expected_cases else None),
                "unadmitted_expected_source_cases": unadmitted_cases,
                "unadmitted_source_leakage_hits": unadmitted_leaks,
                "required_pattern_cases": pattern_cases,
                "complete_pattern_cases": complete_pattern_cases,
                "required_patterns": pattern_total,
                "required_pattern_hits": pattern_hits,
                "expected_card_cases": expected_card_cases,
                "expected_card_ids": expected_card_ids,
                "runtime_card_hits": card_hits,
                "interpretation": (
                    "Frozen expected-source and regex-pattern trace; invariant across models and trials; not answer quality."
                    if lane == "retrieval_lineage" else
                    "Prospective source/card lineage; unadmitted sources are excluded from the recall denominator and card IDs are absent from runtime."
                ),
            }
        )
    expected = output[0]
    if (
        expected["expected_source_case_hits"], expected["expected_source_cases"],
        expected["complete_pattern_cases"], expected["required_pattern_cases"],
        expected["required_pattern_hits"], expected["required_patterns"],
    ) != (22, 26, 13, 16, 46, 50):
        raise ValueError(f"retrieval lineage drift: {expected}")
    field = output[1]
    if (
        field["admitted_expected_source_hits"], field["admitted_expected_source_cases"],
        field["unadmitted_expected_source_cases"], field["unadmitted_source_leakage_hits"],
        field["expected_card_cases"], field["expected_card_ids"], field["runtime_card_hits"],
    ) != (11, 16, 13, 0, 28, 29, 0):
        raise ValueError(f"field-history lineage drift: {field}")
    return output


def _harness_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for model_key in MODEL_SPECS:
        subset = [row for row in rows if row["model_key"] == model_key and row["system_variant"] == "full_system"]
        generation = Counter(str(row["generation_path_class"]) for row in subset)
        verifier = Counter(str(row["verification_action"]) for row in subset)
        answerability = Counter(str(row["answerability_state"]) for row in subset)
        admissions = Counter(str(row["context_admission_policy"]) for row in subset)
        tool_plans = Counter(str((row["_metadata"].get("tool_plan") or {}).get("status") or "not_applicable") for row in subset)
        french = [row for row in subset if row["language"] == "French"]
        guard_cases = [row for row in subset if row["expected_guard_count"]]
        output.append(
            {
                "model_key": model_key,
                "model_label": MODEL_SPECS[model_key]["label"],
                "responses": len(subset),
                "model_generations": generation["model_generation"],
                "deterministic_tool_results": generation["deterministic_tool_result"],
                "deterministic_evidence_holds": generation["deterministic_evidence_sufficiency_hold"],
                "deterministic_tool_clarifications": generation["deterministic_tool_clarification"],
                "documents_present": sum(int(row["document_count"]) > 0 for row in subset),
                "document_rows": sum(int(row["document_count"]) for row in subset),
                "graph_present": sum(int(row["graph_hit_count"]) > 0 for row in subset),
                "graph_rows": sum(int(row["graph_hit_count"]) for row in subset),
                "tool_plan_ready": tool_plans["ready"],
                "tool_plan_clarification": tool_plans["clarification_required"],
                "tool_plan_not_applicable": tool_plans["not_applicable"],
                "verifier_triggered": sum(bool(row["verification_triggered"]) for row in subset),
                "verifier_accept_rewrite": verifier["accept_rewrite"],
                "verifier_fallback_or_degraded": verifier["fallback_or_degraded"],
                "verifier_preserve_draft": verifier["preserve_draft"],
                "verifier_preserve_deterministic": verifier["preserve_deterministic_result"],
                "verifier_not_run": verifier["not_run"],
                "verifier_request_input": verifier["request_missing_tool_input"],
                "answer_directly": answerability["answer_directly"],
                "answer_bounded": answerability["answer_with_bounded_uncertainty"],
                "require_authority": answerability["require_authority"],
                "ask_question": answerability["ask_one_discriminating_question"],
                "kernel_field_only": admissions["kernel_and_field_context_only"],
                "regional_context": admissions["explicit_regional_context_interpretation"],
                "strong_source": admissions["source_interpretation_primary"],
                "typed_capability": admissions["typed_capability_result"],
                "output_contract_passes": sum(bool(row["output_contract_pass"]) for row in subset),
                "output_contract_cases": len(subset),
                "french_preserved": sum(bool(row["french_language_pass"]) for row in french),
                "french_cases": len(french),
                "complete_guard_cases": sum(int(row["missing_guard_count"]) == 0 for row in guard_cases),
                "guard_cases": len(guard_cases),
            }
        )
    for row in output:
        if (row["model_generations"], row["deterministic_tool_results"], row["deterministic_evidence_holds"], row["deterministic_tool_clarifications"]) != (489, 48, 174, 12):
            raise ValueError(f"generation-path drift: {row}")
        if (row["documents_present"], row["document_rows"], row["graph_present"], row["graph_rows"]) != (621, 2850, 528, 1143):
            raise ValueError(f"retrieval activation drift: {row}")
        if (
            row["kernel_field_only"],
            row["regional_context"],
            row["strong_source"],
            row["typed_capability"],
        ) != (582, 66, 27, 48):
            raise ValueError(f"context-admission classification drift: {row}")
        if (row["french_preserved"], row["french_cases"], row["complete_guard_cases"], row["guard_cases"]) != (27, 36, 402, 462):
            raise ValueError(f"interface diagnostic drift: {row}")
    return output


def _interface_trace_summary(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for model_key in MODEL_SPECS:
        subset = [
            row
            for row in rows
            if row["model_key"] == model_key
            and row["system_variant"] == "full_system"
        ]
        responses = len(subset)
        field_eligible = sum(bool(row["_field_context_eligible"]) for row in subset)
        row = {
            "model_key": model_key,
            "model_label": MODEL_SPECS[model_key]["label"],
            "full_system_observations": responses,
            "input_lineage_complete": sum(
                bool(item["_input_lineage_present"]) for item in subset
            ),
            "field_context_eligible": field_eligible,
            "field_context_bound": sum(
                bool(item["_field_context_bound"]) for item in subset
            ),
            "route_trace_complete": sum(
                bool(item["_route_trace_present"]) for item in subset
            ),
            "context_admission_trace_complete": sum(
                bool(item["_context_admission_trace_present"]) for item in subset
            ),
            "evidence_lineage_complete": sum(
                bool(item["_evidence_lineage_present"]) for item in subset
            ),
            "interpretation": (
                "Presence and linkage contract only; not evidence correctness or answer quality."
            ),
        }
        if responses != 723 or field_eligible != responses:
            raise ValueError(f"unexpected full-system interface denominator: {row}")
        complete_fields = (
            "input_lineage_complete",
            "field_context_bound",
            "route_trace_complete",
            "context_admission_trace_complete",
            "evidence_lineage_complete",
        )
        if any(int(row[field]) != responses for field in complete_fields):
            raise ValueError(f"full-system interface trace drift: {row}")
        output.append(row)
    return output


def _repeatability(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for model_key in MODEL_SPECS:
        for arm in ARM_ORDER:
            hashes: dict[str, set[str]] = defaultdict(set)
            for row in rows:
                if row["model_key"] == model_key and row["system_variant"] == arm:
                    hashes[str(row["eval_id"])].add(str(row["output_sha256"]))
            counts = Counter(len(values) for values in hashes.values())
            output.append(
                {
                    "model_key": model_key,
                    "model_label": MODEL_SPECS[model_key]["label"],
                    "system_variant": arm,
                    "arm_label": ARM_LABELS[arm],
                    "cases": len(hashes),
                    "one_unique_output": counts[1],
                    "two_unique_outputs": counts[2],
                    "three_unique_outputs": counts[3],
                    "exact_three_trial_repeatability": round(counts[1] / len(hashes), 6),
                    "interpretation": (
                        "Fresh-process/order repeatability under local temperature-zero argmax; not independent seeds or correctness."
                        if model_key != "luna_high_rc3" else
                        "Exact-text repeatability across unseeded remote repeated calls; not correctness."
                    ),
                }
            )
    expected_local = [row for row in output if row["model_key"] != "luna_high_rc3"]
    if any(row["one_unique_output"] != 241 for row in expected_local):
        raise ValueError("local repeatability drift")
    luna = {(row["system_variant"]): (row["one_unique_output"], row["two_unique_outputs"], row["three_unique_outputs"]) for row in output if row["model_key"] == "luna_high_rc3"}
    if luna != {
        "raw_model": (7, 5, 229),
        "kernel_only": (7, 8, 226),
        "kernel_field_context": (6, 6, 229),
        "full_system": (123, 14, 104),
    }:
        raise ValueError(f"Luna repeatability drift: {luna}")
    return output


def _resource_summary(rows: Sequence[Mapping[str, Any]], completion_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for model_key in MODEL_SPECS:
        for arm in ARM_ORDER:
            subset = [row for row in rows if row["model_key"] == model_key and row["system_variant"] == arm]
            values = [float(row["elapsed_seconds"]) for row in subset]
            trial_medians = []
            for trial_id in TRIAL_IDS:
                trial_values = [float(row["elapsed_seconds"]) for row in subset if row["trial_id"] == trial_id]
                trial_medians.append(statistics.median(trial_values))
            maximum = max(subset, key=lambda row: float(row["elapsed_seconds"]))
            output.append(
                {
                    "model_key": model_key,
                    "model_label": MODEL_SPECS[model_key]["label"],
                    "backend": MODEL_SPECS[model_key]["backend"],
                    "system_variant": arm,
                    "arm_label": ARM_LABELS[arm],
                    "observations": len(values),
                    "median_seconds": round(statistics.median(values), 4),
                    "p25_seconds": round(_percentile(values, 0.25), 4),
                    "p75_seconds": round(_percentile(values, 0.75), 4),
                    "p95_seconds": round(_percentile(values, 0.95), 4),
                    "mean_seconds": round(statistics.mean(values), 4),
                    "max_seconds": round(max(values), 4),
                    "max_eval_id": maximum["eval_id"],
                    "trial_001_median_seconds": round(trial_medians[0], 4),
                    "trial_002_median_seconds": round(trial_medians[1], 4),
                    "trial_003_median_seconds": round(trial_medians[2], 4),
                    "interpretation": "Observed end-to-end wall time; descriptive only; cross-backend speed claims are unsupported.",
                }
            )
    outlier = next(row for row in output if row["model_key"] == "gemma4_e2b_rc3" and row["system_variant"] == "kernel_only")
    if outlier["max_eval_id"] != "oacp1::canadian_decision_quality::ca_v2_manitoba_soils_06" or not math.isclose(float(outlier["max_seconds"]), 5062.879, abs_tol=0.001):
        raise ValueError(f"known latency outlier drift: {outlier}")

    totals = Counter()
    pricing_identity: Optional[dict[str, Any]] = None
    for trial_id in TRIAL_IDS:
        ledger = _load_object(completion_root / "luna_high_rc3" / trial_id / "cost_ledger_manifest.json")
        if ledger.get("integrity_check") != "ok":
            raise ValueError(f"cost ledger integrity failure: {trial_id}")
        pricing = ledger["pricing_index"]
        current = {
            "pricing_index_id": pricing["pricing_index_id"],
            "pricing_index_sha256": ledger["pricing_index_sha256"],
            "billing_scope": pricing["billing_scope"],
        }
        if pricing_identity is not None and current != pricing_identity:
            raise ValueError("pricing identity drift across Luna trials")
        pricing_identity = current
        for key, value in ledger["totals"].items():
            totals[key] += value
    usage = {
        **dict(pricing_identity or {}),
        "calls": int(totals["calls"]),
        "input_tokens": int(totals["input_tokens"]),
        "output_tokens": int(totals["output_tokens"]),
        "reasoning_output_tokens": int(totals["reasoning_output_tokens"]),
        "total_tokens": int(totals["total_tokens"]),
        "api_equivalent_cost_usd": round(float(totals["api_equivalent_cost_usd"]), 8),
        "actual_billed_cost_usd": None,
        "answer_verifier_calls": 183,
        "interpretation": "API-equivalent estimate only. Actual ChatGPT-authenticated billing and local energy use were not observed.",
    }
    if (usage["calls"], usage["total_tokens"], usage["answer_verifier_calls"]) != (2841, 10919444, 183):
        raise ValueError(f"Luna usage drift: {usage}")
    return output, usage


def _plot_setup() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 11,
            "axes.labelsize": 9.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "legend.fontsize": 8,
            "figure.titlesize": 12,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "svg.hashsalt": "open-agronomy-rc3-20260815",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return plt


COLORS = {
    "gemma3_270m_rc3": "#0072B2",
    "gemma4_e2b_rc3": "#E69F00",
    "luna_high_rc3": "#009E73",
    "objective": "#0072B2",
    "lexical": "#CC79A7",
    "pending": "#B8BDC6",
    "tool": "#56B4E9",
    "hold": "#D55E00",
    "clarify": "#CC79A7",
    "model": "#009E73",
    "fallback": "#D55E00",
    "rewrite": "#0072B2",
    "preserve": "#009E73",
    "neutral": "#7A7A7A",
}
MARKERS = {"gemma3_270m_rc3": "o", "gemma4_e2b_rc3": "s", "luna_high_rc3": "^"}


def _save_figure(fig: Any, path_stem: Path, title: str) -> list[dict[str, Any]]:
    path_stem.parent.mkdir(parents=True, exist_ok=True)
    svg = path_stem.with_suffix(".svg")
    pdf = path_stem.with_suffix(".pdf")
    fig.savefig(
        svg,
        bbox_inches="tight",
        metadata={"Date": None, "Title": title, "Creator": "Open Agronomy Agent RC3 analysis"},
    )
    # Matplotlib formats multiline SVG path data with a space before each
    # newline. Normalize that generator-specific whitespace so the published
    # vector artifacts remain both deterministic and clean under Git's
    # whitespace checks.
    svg_text = svg.read_text(encoding="utf-8")
    svg.write_text(
        "\n".join(line.rstrip() for line in svg_text.splitlines()) + "\n",
        encoding="utf-8",
    )
    fig.savefig(
        pdf,
        bbox_inches="tight",
        metadata={"CreationDate": None, "ModDate": None, "Title": title, "Creator": "Open Agronomy Agent RC3 analysis"},
    )
    return [
        {"path": f"figures/{svg.name}", "sha256": _sha256_path(svg), "bytes": svg.stat().st_size},
        {"path": f"figures/{pdf.name}", "sha256": _sha256_path(pdf), "bytes": pdf.stat().st_size},
    ]


def _plot_evidence_coverage(paper_root: Path, lane_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    plt = _plot_setup()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), gridspec_kw={"width_ratios": [1.55, 1.0]})
    ax = axes[0]
    labels = [str(row["lane_label"]) for row in lane_rows]
    y = list(range(len(labels)))
    objective = [int(row["objective_numeric_cases"]) for row in lane_rows]
    lexical = [int(row["lexical_regression_cases"]) for row in lane_rows]
    unscored = [int(row["unscored_cases"]) for row in lane_rows]
    ax.barh(y, objective, color=COLORS["objective"], label="Objective numeric score")
    ax.barh(y, lexical, left=objective, color=COLORS["lexical"], label="Lexical regression proxy")
    left = [a + b for a, b in zip(objective, lexical)]
    ax.barh(y, unscored, left=left, color=COLORS["pending"], label="Trace-only or human review pending")
    for pos, row in enumerate(lane_rows):
        ax.text(int(row["cases"]) + 1.2, pos, str(row["cases"]), va="center", fontsize=8)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Frozen cases")
    ax.set_title("A. Score availability is lane-specific")
    ax.set_xlim(0, 100)
    ax.legend(loc="lower right", frameon=False)

    ax = axes[1]
    checks = [
        ("Completion-receipted trials", 9, 9),
        ("Canonical arm executions", 36, 36),
        ("Canonical observations", 8676, 8676),
        ("Deterministically scored cases/arm", 49, 241),
        ("Reviewer-form rows completed", 0, 1620),
    ]
    yy = list(range(len(checks)))
    rates = [100.0 * num / den for _, num, den in checks]
    colors = [COLORS["model"]] * 3 + [COLORS["lexical"], COLORS["pending"]]
    ax.barh(yy, rates, color=colors, height=0.62)
    for pos, ((_, num, den), rate) in enumerate(zip(checks, rates)):
        ax.text(min(rate + 2, 95), pos, f"{num:,}/{den:,}", va="center", fontsize=8.5)
    ax.set_yticks(yy, [label for label, _, _ in checks])
    ax.invert_yaxis()
    ax.set_xlim(0, 105)
    ax.set_xlabel("Percent of declared denominator")
    ax.set_title("B. Execution complete; quality review is not")
    fig.suptitle("RC3 evidence boundary: complete matrix, limited outcome authority", y=1.01)
    fig.tight_layout()
    artifacts = _save_figure(fig, paper_root / "figures/rc3_evidence_coverage", "RC3 evidence coverage")
    plt.close(fig)
    return artifacts


def _plot_deterministic_metrics(
    paper_root: Path,
    summaries: Sequence[Mapping[str, Any]],
    parser_audit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    plt = _plot_setup()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), sharey=True)
    metrics = (
        ("objective_numeric_tolerance", "A. Objective numeric tolerance (16 cases)"),
        ("official_source_lexical_regression", "B. Official-source lexical proxy (33 cases)"),
    )
    model_offsets = {-1: -0.22, 0: 0.0, 1: 0.22}
    for ax, (metric, title) in zip(axes, metrics):
        for model_index, model_key in enumerate(MODEL_SPECS):
            offset = model_offsets[model_index - 1]
            subset = [row for row in summaries if row["model_key"] == model_key and row["metric"] == metric]
            subset.sort(key=lambda row: ARM_ORDER.index(str(row["system_variant"])))
            xs = [index + offset for index in range(len(ARM_ORDER))]
            means = [float(row["finite_suite_mean"]) for row in subset]
            lows = [float(row["sensitivity_interval_low"]) for row in subset]
            highs = [float(row["sensitivity_interval_high"]) for row in subset]
            ax.plot(xs, means, color=COLORS[model_key], alpha=0.55, linewidth=1.2)
            ax.errorbar(
                xs,
                means,
                yerr=[[mean - low for mean, low in zip(means, lows)], [high - mean for mean, high in zip(means, highs)]],
                color=COLORS[model_key],
                marker=MARKERS[model_key],
                markersize=5.5,
                capsize=2,
                linewidth=1.2,
                label=MODEL_SPECS[model_key]["label"],
            )
            for x, row in zip(xs, subset):
                trial_values = [float(row[f"trial_00{trial}"]) for trial in (1, 2, 3)]
                for trial_offset, value in zip((-0.035, 0.0, 0.035), trial_values):
                    ax.scatter(x + trial_offset, value, s=13, facecolors="white", edgecolors=COLORS[model_key], linewidths=0.8, zorder=4)
        ax.axhline(0, color="#8A8A8A", linewidth=0.7)
        ax.set_xticks(range(len(ARM_ORDER)), [ARM_LABELS[arm] for arm in ARM_ORDER], rotation=18, ha="right")
        ax.set_ylim(-3, 105)
        ax.set_ylabel("Percent")
        ax.set_title(title)
        ax.grid(axis="y", color="#D5D8DC", linewidth=0.6)
    axes[0].scatter(
        [3],
        [float(parser_audit["post_run_tool_payload_accuracy_percent"])],
        marker="D",
        s=54,
        facecolors="none",
        edgecolors="#222222",
        linewidths=1.2,
        zorder=5,
        label="Post-run typed-payload audit",
    )
    axes[0].annotate(
        "Frozen parser: 14/16\nTyped payload audit: 16/16",
        xy=(3, 100),
        xytext=(1.85, 76),
        arrowprops={"arrowstyle": "->", "color": "#333333", "linewidth": 0.8},
        fontsize=8,
    )
    handles, labels = axes[1].get_legend_handles_labels()
    axes[1].legend(handles, labels, loc="lower left", frameon=False)
    axes[0].legend(loc="lower left", frameon=False, fontsize=7.5)
    fig.suptitle("Deterministic endpoints: trial observations and case-resampling sensitivity intervals", y=1.01)
    fig.text(
        0.5,
        -0.01,
        "Open symbols are the three observed trial means; intervals resample cases after trial averaging. The lexical proxy is not answer quality.",
        ha="center",
        fontsize=8,
    )
    fig.tight_layout()
    artifacts = _save_figure(fig, paper_root / "figures/rc3_deterministic_metrics", "RC3 deterministic metrics")
    plt.close(fig)
    return artifacts


def _plot_harness_behavior(
    paper_root: Path,
    harness: Sequence[Mapping[str, Any]],
    retrieval: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    plt = _plot_setup()
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 4.5), gridspec_kw={"width_ratios": [1.05, 1.25, 1.1]})
    labels = [MODEL_SPECS[row["model_key"]]["short_label"] for row in harness]
    y = list(range(len(labels)))
    ax = axes[0]
    categories = (
        ("model_generations", "Model generation", COLORS["model"]),
        ("deterministic_tool_results", "Typed tool result", COLORS["tool"]),
        ("deterministic_evidence_holds", "Evidence hold", COLORS["hold"]),
        ("deterministic_tool_clarifications", "Tool clarification", COLORS["clarify"]),
    )
    left = [0] * len(harness)
    for key, label, color in categories:
        values = [int(row[key]) for row in harness]
        ax.barh(y, values, left=left, color=color, label=label)
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Responses across 3 trials")
    ax.set_title("A. Full-system output origin")
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        frameon=False,
        fontsize=7.2,
        ncol=2,
    )

    ax = axes[1]
    verifier_categories = (
        ("verifier_accept_rewrite", "Rewrite accepted", COLORS["rewrite"]),
        ("verifier_fallback_or_degraded", "Fallback/degraded", COLORS["fallback"]),
        ("verifier_preserve_draft", "Draft preserved", COLORS["preserve"]),
        ("verifier_preserve_deterministic", "Deterministic preserved", COLORS["tool"]),
        ("verifier_request_input", "Input requested", COLORS["clarify"]),
        ("verifier_not_run", "Not run", COLORS["pending"]),
    )
    left = [0] * len(harness)
    for key, label, color in verifier_categories:
        values = [int(row[key]) for row in harness]
        ax.barh(y, values, left=left, color=color, label=label)
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Responses across 3 trials")
    ax.set_title("B. Verification disposition")
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        frameon=False,
        fontsize=6.9,
        ncol=2,
    )

    ax = axes[2]
    retrieval_row = next(row for row in retrieval if row["benchmark_lane"] == "retrieval_lineage")
    field_row = next(row for row in retrieval if row["benchmark_lane"] == "field_history_lineage")
    checks = [
        ("Documents present", 207, 241),
        ("Graph hits present", 176, 241),
        ("Expected source surfaced", int(retrieval_row["expected_source_case_hits"]), int(retrieval_row["expected_source_cases"])),
        ("Required patterns hit", int(retrieval_row["required_pattern_hits"]), int(retrieval_row["required_patterns"])),
        ("Admitted field sources hit", int(field_row["admitted_expected_source_hits"]), int(field_row["admitted_expected_source_cases"])),
        ("French outputs preserved", 9, 12),
        ("Local-guard routes complete", 134, 154),
    ]
    yy = list(range(len(checks)))
    rates = [100 * num / den for _, num, den in checks]
    ax.hlines(yy, 0, rates, color="#B8BDC6", linewidth=2)
    ax.scatter(rates, yy, color=COLORS["objective"], s=34, zorder=3)
    for pos, ((_, num, den), rate) in enumerate(zip(checks, rates)):
        ax.text(min(rate + 2, 92), pos, f"{num}/{den}", va="center", fontsize=7.6)
    ax.set_yticks(yy, [label for label, _, _ in checks])
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    ax.set_xlabel("Trace coverage (%)")
    ax.set_title("C. Retrieval and interface traces")
    fig.suptitle("The harness - not only the generator - determines full-system behavior", y=1.01)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.27)
    artifacts = _save_figure(fig, paper_root / "figures/rc3_harness_behavior", "RC3 harness behavior")
    plt.close(fig)
    return artifacts


def _plot_repeatability_latency(
    paper_root: Path,
    repeatability: Sequence[Mapping[str, Any]],
    resources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    plt = _plot_setup()
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(10.7, 4.5), gridspec_kw={"width_ratios": [0.85, 1.55]})
    ax = axes[0]
    matrix = np.array(
        [
            [100 * next(row for row in repeatability if row["model_key"] == model_key and row["system_variant"] == arm)["exact_three_trial_repeatability"] for arm in ARM_ORDER]
            for model_key in MODEL_SPECS
        ]
    )
    ax.imshow(matrix, vmin=0, vmax=100, cmap="Blues", aspect="auto")
    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix[row_index, column_index]
            ax.text(column_index, row_index, f"{value:.1f}%", ha="center", va="center", color="white" if value > 62 else "#222222", fontsize=8.5)
    ax.set_xticks(range(len(ARM_ORDER)), [ARM_LABELS[arm] for arm in ARM_ORDER], rotation=28, ha="right")
    ax.set_yticks(range(len(MODEL_SPECS)), [MODEL_SPECS[key]["short_label"] for key in MODEL_SPECS])
    ax.set_title("A. Exact output repeatability")
    ax.set_xlabel("Arm")

    ax = axes[1]
    model_offsets = {-1: -0.22, 0: 0.0, 1: 0.22}
    for model_index, model_key in enumerate(MODEL_SPECS):
        offset = model_offsets[model_index - 1]
        subset = [row for row in resources if row["model_key"] == model_key]
        subset.sort(key=lambda row: ARM_ORDER.index(str(row["system_variant"])))
        xs = [index + offset for index in range(len(ARM_ORDER))]
        medians = [float(row["median_seconds"]) for row in subset]
        p95 = [float(row["p95_seconds"]) for row in subset]
        ax.vlines(xs, medians, p95, color=COLORS[model_key], linewidth=1.5)
        ax.scatter(xs, medians, marker=MARKERS[model_key], color=COLORS[model_key], s=35, label=MODEL_SPECS[model_key]["label"], zorder=4)
        ax.scatter(xs, p95, marker="_", color=COLORS[model_key], s=65, zorder=4)
        for x, row in zip(xs, subset):
            trial_values = [float(row[f"trial_00{trial}_median_seconds"]) for trial in (1, 2, 3)]
            ax.scatter([x - 0.04, x, x + 0.04], trial_values, s=10, facecolors="white", edgecolors=COLORS[model_key], linewidths=0.7, zorder=5)
    outlier = next(row for row in resources if row["model_key"] == "gemma4_e2b_rc3" and row["system_variant"] == "kernel_only")
    x_outlier = 1 + model_offsets[0]
    ax.scatter([x_outlier], [float(outlier["max_seconds"])], marker="^", facecolors="none", edgecolors="#222222", s=46, zorder=5)
    ax.annotate("5,062.879 s host/runtime stall", xy=(x_outlier, float(outlier["max_seconds"])), xytext=(1.55, 900), arrowprops={"arrowstyle": "->", "linewidth": 0.8}, fontsize=7.8)
    ax.set_yscale("log")
    ax.set_ylim(0.03, 9000)
    ax.set_xticks(range(len(ARM_ORDER)), [ARM_LABELS[arm] for arm in ARM_ORDER], rotation=18, ha="right")
    ax.set_ylabel("Observed wall time (seconds, log scale)")
    ax.set_title("B. Median, p95, and retained maximum latency")
    ax.grid(axis="y", which="both", color="#D5D8DC", linewidth=0.55)
    ax.legend(loc="lower right", frameon=False)
    fig.suptitle("Replication and execution cost are descriptive, not answer quality", y=1.01)
    fig.tight_layout()
    artifacts = _save_figure(fig, paper_root / "figures/rc3_repeatability_latency", "RC3 repeatability and latency")
    plt.close(fig)
    return artifacts


def _escape_tex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _write_generated_tex(
    paper_root: Path,
    metrics: Sequence[Mapping[str, Any]],
    parser_audit: Mapping[str, Any],
    retrieval: Sequence[Mapping[str, Any]],
    harness: Sequence[Mapping[str, Any]],
    repeatability: Sequence[Mapping[str, Any]],
    usage: Mapping[str, Any],
) -> None:
    objective = {(row["model_key"], row["system_variant"]): row for row in metrics if row["metric"] == "objective_numeric_tolerance"}
    lexical = {(row["model_key"], row["system_variant"]): row for row in metrics if row["metric"] == "official_source_lexical_regression"}
    retrieval_row = next(row for row in retrieval if row["benchmark_lane"] == "retrieval_lineage")
    field_row = next(row for row in retrieval if row["benchmark_lane"] == "field_history_lineage")
    macros = "\n".join(
        [
            r"\newcommand{\RCObservations}{8,676}",
            r"\newcommand{\RCTrials}{nine}",
            r"\newcommand{\RCScoredCases}{49/241}",
            r"\newcommand{\RCSemanticJudgments}{zero}",
            rf"\newcommand{{\RCRetrievalSource}}{{{retrieval_row['expected_source_case_hits']}/{retrieval_row['expected_source_cases']}}}",
            rf"\newcommand{{\RCRetrievalPattern}}{{{retrieval_row['required_pattern_hits']}/{retrieval_row['required_patterns']}}}",
            rf"\newcommand{{\RCFieldAdmitted}}{{{field_row['admitted_expected_source_hits']}/{field_row['admitted_expected_source_cases']}}}",
            rf"\newcommand{{\RCCanonicalCalc}}{{{parser_audit['canonical_parser_passes']}/{parser_audit['canonical_full_system_cases']}}}",
            rf"\newcommand{{\RCToolAudit}}{{{parser_audit['post_run_tool_payload_within_tolerance']}/{parser_audit['post_run_tool_payload_cases']}}}",
            rf"\newcommand{{\RCLunaCalls}}{{{int(usage['calls']):,}}}",
            rf"\newcommand{{\RCLunaTokens}}{{{int(usage['total_tokens']):,}}}",
            rf"\newcommand{{\RCLunaCost}}{{\${float(usage['api_equivalent_cost_usd']):.4f}}}",
        ]
    )
    (paper_root / "generated_results.tex").write_text(macros + "\n", encoding="utf-8")

    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Deterministic development metrics. Values are finite-suite means across case-level trial averages. The official-source metric is a lexical contract regression, not answer quality.}",
        r"\label{tab:metrics}",
        r"\small",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Candidate configuration & Metric & Raw & Kernel & Kernel + field & Full system \\",
        r"\midrule",
    ]
    for model_key in MODEL_SPECS:
        label = _escape_tex(MODEL_SPECS[model_key]["label"])
        obj_values = [float(objective[(model_key, arm)]["finite_suite_mean"]) for arm in ARM_ORDER]
        lex_values = [float(lexical[(model_key, arm)]["finite_suite_mean"]) for arm in ARM_ORDER]
        lines.append(f"{label} & " + r"Numeric tolerance (\%) & " + " & ".join(f"{value:.2f}" for value in obj_values) + r" \\")
        lines.append(f"{label} & " + r"Lexical proxy (\%) & " + " & ".join(f"{value:.2f}" for value in lex_values) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table*}"])

    lines.extend(
        [
            "",
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Full-system harness activation across three trials per configuration. Counts are execution traces, not correctness scores.}",
            r"\label{tab:harness}",
            r"\small",
            r"\begin{tabular}{lrrr}",
            r"\toprule",
            r"Configuration & Generated & Holds & Verifier triggered \\",
            r"\midrule",
        ]
    )
    for row in harness:
        lines.append(
            f"{_escape_tex(MODEL_SPECS[row['model_key']]['short_label'])} & {row['model_generations']} & {row['deterministic_evidence_holds']} & {row['verifier_triggered']} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])
    (paper_root / "generated_tables.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _manifest_records(base: Path, relative_paths: Iterable[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in sorted(set(relative_paths)):
        path = base / relative
        if not path.is_file():
            raise ValueError(f"missing package artifact: {relative}")
        records.append({"path": relative, "sha256": _sha256_path(path), "bytes": path.stat().st_size})
    return records


def _finalize_package(paper_root: Path) -> dict[str, Any]:
    artifacts = _manifest_records(paper_root, PUBLISHED_FILES)
    payload = {
        "schema_version": ARTIFACT_SCHEMA,
        "analysis_date": ANALYSIS_DATE,
        "package": "development-benchmark-rc3-20260815",
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "aggregate_sha256": _sha256_bytes(_canonical(artifacts).encode("utf-8")),
        "boundary": "The manifest excludes itself to avoid self-reference. Raw answers, prompts, databases, logs, and model weights are not public package artifacts.",
    }
    _write_json(paper_root / "source_data/artifact_manifest.json", payload)
    return payload


def _validate_public_measurements(
    rows: Sequence[Mapping[str, str]],
    fieldnames: Optional[Sequence[str]],
) -> None:
    if list(fieldnames or []) != PUBLIC_FIELDS:
        raise ValueError("public response measurement schema drift")
    if len(rows) != 8676:
        raise ValueError(f"expected 8,676 public response rows, found {len(rows)}")
    observation_ids = [str(row.get("observation_id") or "") for row in rows]
    if len(set(observation_ids)) != 8676 or any(not value for value in observation_ids):
        raise ValueError("public response observation identities are not unique and complete")
    sample_identities = {
        (
            str(row.get("model_key") or ""),
            str(row.get("trial_id") or ""),
            str(row.get("system_variant") or ""),
            str(row.get("eval_id") or ""),
        )
        for row in rows
    }
    if len(sample_identities) != 8676:
        raise ValueError("public response model/trial/arm/case identities are not unique")
    group_counts = Counter(
        (
            str(row.get("model_key") or ""),
            str(row.get("trial_id") or ""),
            str(row.get("system_variant") or ""),
        )
        for row in rows
    )
    if len(group_counts) != 36 or set(group_counts.values()) != {241}:
        raise ValueError("public response model/trial/arm topology mismatch")
    matched = Counter(str(row.get("matched_trial_key") or "") for row in rows)
    if len(matched) != 2169 or set(matched.values()) != {4} or "" in matched:
        raise ValueError("public response matched-arm identity mismatch")
    if any(
        not re.fullmatch(r"[0-9a-f]{64}", str(row.get("output_sha256") or ""))
        for row in rows
    ):
        raise ValueError("public response output hash is invalid")
    boolean_fields = (
        "proxy_valid",
        "parse_valid",
        "verification_triggered",
        "output_contract_pass",
        "french_language_pass",
    )
    for field in boolean_fields:
        values = {str(row.get(field) or "") for row in rows}
        if not values <= {"", "True", "False"}:
            raise ValueError(f"public response {field} is not boolean-or-missing")
    objective_values = [
        row["objective_accuracy"] for row in rows if row.get("objective_accuracy")
    ]
    diagnostic_values = [
        row["deterministic_diagnostic_score"]
        for row in rows
        if row.get("deterministic_diagnostic_score")
    ]
    if len(objective_values) != 576 or len(diagnostic_values) != 1188:
        raise ValueError("public deterministic score cardinality mismatch")
    for field, values in (
        ("objective_accuracy", objective_values),
        ("deterministic_diagnostic_score", diagnostic_values),
    ):
        try:
            numeric = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"public response {field} is not numeric") from exc
        if any(not math.isfinite(value) or not 0.0 <= value <= 100.0 for value in numeric):
            raise ValueError(f"public response {field} is outside [0, 100]")
    if any(
        row.get("objective_accuracy")
        and row.get("benchmark_lane") != OBJECTIVE_LANE
        for row in rows
    ):
        raise ValueError("objective_accuracy leaked into a non-objective lane")
    if any(
        row.get("deterministic_diagnostic_score")
        and row.get("benchmark_lane") != LEXICAL_LANE
        for row in rows
    ):
        raise ValueError("deterministic_diagnostic_score leaked outside the lexical lane")


def _verify_published(paper_root: Path) -> dict[str, Any]:
    artifact_manifest = _load_object(paper_root / ARTIFACT_MANIFEST_RELATIVE)
    if artifact_manifest.get("schema_version") != ARTIFACT_SCHEMA:
        raise ValueError("unexpected artifact manifest schema")
    expected_records = _manifest_records(paper_root, PUBLISHED_FILES)
    if artifact_manifest.get("artifacts") != expected_records:
        raise ValueError("published artifact bytes do not match artifact_manifest.json")
    if artifact_manifest.get("aggregate_sha256") != _sha256_bytes(_canonical(expected_records).encode("utf-8")):
        raise ValueError("published aggregate identity mismatch")
    expected_files = set(PUBLISHED_FILES) | {ARTIFACT_MANIFEST_RELATIVE}
    actual_files = {
        path.relative_to(paper_root).as_posix()
        for path in paper_root.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        raise ValueError(
            f"published package inventory mismatch: missing={missing}, unexpected={unexpected}"
        )
    with (paper_root / "source_data/public_safe_response_measurements.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    _validate_public_measurements(rows, reader.fieldnames)
    validation = _load_object(paper_root / "source_data/checkpoint_validation_receipt.json")
    if validation.get("canonical_observations") != 8676 or validation.get("semantic_judgments") != 0:
        raise ValueError("checkpoint validation counts drift")
    # Construct machine-local path sentinels without embedding those same
    # public-release-forbidden literals in this distributable verifier.
    forbidden = (
        "/" + "Users/",
        "/" + "Volumes/",
        "/" + "private/" + "tmp/",
        "Bear" + "er ",
        "-----BEGIN " + "PRIVATE KEY-----",
    )
    for relative in PUBLISHED_FILES:
        path = paper_root / relative
        if path.suffix.lower() not in {".md", ".tex", ".bib", ".yaml", ".json", ".csv", ".py", ".svg"}:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                raise ValueError(f"forbidden machine-local or secret marker {token!r} in {relative}")
    result = {
        "status": "verified",
        "artifact_count": len(expected_records),
        "aggregate_sha256": artifact_manifest["aggregate_sha256"],
        "canonical_observations": len(rows),
        "semantic_judgments": 0,
    }
    print(json.dumps(result, sort_keys=True))
    return result


def build_checkpoint(
    *,
    completion_root: Path,
    retention_root: Path,
    suite_path: Path,
    store_manifest_path: Path,
    paper_root: Path,
) -> dict[str, Any]:
    if _sha256_path(suite_path) != EXPECTED_SUITE_SHA256:
        raise ValueError("suite bytes differ from the completed RC3 identity")
    suite = _read_jsonl(suite_path)
    if len(suite) != 241 or len({str(row["eval_id"]) for row in suite}) != 241:
        raise ValueError("suite must contain 241 unique cases")
    source_records = _source_records(suite)
    store_manifest = _load_object(store_manifest_path)

    inventory: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for model_key, trial_id in _completion_specs():
        trial_inventory, trial_rows, _ = _load_trial(
            completion_root=completion_root,
            retention_root=retention_root,
            model_key=model_key,
            trial_id=trial_id,
        )
        inventory.append(trial_inventory)
        rows.extend(trial_rows)
    if len(rows) != 8676 or len({str(row["observation_id"]) for row in rows}) != 8676:
        raise ValueError("expected 8,676 unique canonical observations")
    if len({str(row["run_execution_id"]) for row in rows}) != 36:
        raise ValueError("expected 36 unique arm execution identities")
    matched = Counter(str(row["matched_trial_key"]) for row in rows)
    if len(matched) != 2169 or set(matched.values()) != {4}:
        raise ValueError("paired arm identity mismatch")

    lane_rows = _lane_coverage(suite)
    metric_rows, effect_rows = _metric_summaries(rows)
    parser_audit = _objective_parser_audit(rows)
    retrieval_rows = _retrieval_summary(rows, suite, source_records, store_manifest)
    harness_rows = _harness_summary(rows)
    interface_trace_rows = _interface_trace_summary(rows)
    repeatability_rows = _repeatability(rows)
    resource_rows, luna_usage = _resource_summary(rows, completion_root)
    successor_repairs = [
        {
            "repair": "objective_product_mass_unit_alias",
            "status": "future_only_not_part_of_rc3",
            "artifacts": _manifest_records(
                ROOT,
                ("src/agronomy_agent/evals.py", "tests/test_evals.py"),
            ),
        },
        {
            "repair": "versioned_public_metric_projection",
            "status": "future_only_not_part_of_rc3",
            "artifacts": _manifest_records(
                ROOT,
                (
                    "scripts/build_benchmark_retention_bundle.py",
                    "configs/schemas/benchmark_retention_bundle_v1.schema.json",
                    "tests/test_benchmark_retention_bundle.py",
                ),
            ),
        },
        {
            "repair": "deterministic_hold_language_preservation",
            "status": "future_only_not_part_of_rc3",
            "artifacts": _manifest_records(
                ROOT,
                ("src/agronomy_agent/answerability.py", "tests/test_answerability.py"),
            ),
        },
        {
            "repair": "context_admission_reporting_categories",
            "status": "future_only_not_part_of_rc3",
            "artifacts": _manifest_records(
                ROOT,
                (
                    "src/agronomy_agent/benchmark_report.py",
                    "tests/test_benchmark_report.py",
                ),
            ),
        },
    ]

    source_dir = paper_root / "source_data"
    _write_csv(source_dir / "public_safe_response_measurements.csv", _public_rows(rows), PUBLIC_FIELDS)
    _write_csv(source_dir / "trial_inventory.csv", inventory, list(inventory[0]))
    _write_csv(source_dir / "lane_coverage.csv", lane_rows, list(lane_rows[0]))
    _write_csv(source_dir / "deterministic_metric_summary.csv", metric_rows, list(metric_rows[0]))
    _write_csv(source_dir / "paired_arm_effects.csv", effect_rows, list(effect_rows[0]))
    _write_csv(source_dir / "retrieval_lineage_summary.csv", retrieval_rows, list(retrieval_rows[0]))
    _write_csv(source_dir / "harness_activation_summary.csv", harness_rows, list(harness_rows[0]))
    _write_csv(
        source_dir / "interface_trace_summary.csv",
        interface_trace_rows,
        list(interface_trace_rows[0]),
    )
    _write_csv(source_dir / "repeatability_summary.csv", repeatability_rows, list(repeatability_rows[0]))
    _write_csv(source_dir / "resource_summary.csv", resource_rows, list(resource_rows[0]))

    figure_records: list[dict[str, Any]] = []
    figure_records.extend(_plot_evidence_coverage(paper_root, lane_rows))
    figure_records.extend(_plot_deterministic_metrics(paper_root, metric_rows, parser_audit))
    figure_records.extend(_plot_harness_behavior(paper_root, harness_rows, retrieval_rows))
    figure_records.extend(_plot_repeatability_latency(paper_root, repeatability_rows, resource_rows))
    figure_manifest = {
        "schema_version": "open_agronomy_agent.rc3_checkpoint_figures.v1",
        "analysis_seed": ANALYSIS_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "artifacts": sorted(figure_records, key=lambda row: row["path"]),
        "boundary": "Vector figures show deterministic diagnostics, trace activation, repeatability, and observed resources. They do not report semantic answer quality or a composite rank.",
    }
    _write_json(paper_root / "figures/manifest.json", figure_manifest)

    _write_generated_tex(paper_root, metric_rows, parser_audit, retrieval_rows, harness_rows, repeatability_rows, luna_usage)
    validation = {
        "schema_version": VALIDATION_SCHEMA,
        "status": "complete_nonclaim_development_checkpoint",
        "analysis_date": ANALYSIS_DATE,
        "benchmark_id": EXPECTED_BENCHMARK_ID,
        "claim_eligible": False,
        "suite_exposure_status": "exposed_and_used_for_system_tuning",
        "benchmark_suite_sha256": EXPECTED_SUITE_SHA256,
        "benchmark_source_snapshot_sha256": EXPECTED_SOURCE_SNAPSHOT_SHA256,
        "implementation_commit": EXPECTED_IMPLEMENTATION_COMMIT,
        "canonical_trials": 9,
        "canonical_arm_executions": 36,
        "canonical_observations": 8676,
        "unique_observation_ids": 8676,
        "matched_trial_keys": 2169,
        "cases_per_arm": 241,
        "semantic_judgments": 0,
        "automated_semantic_judge_requested": False,
        "independent_human_reviews_completed": 0,
        "final_partial_identical_arms": sum(
            int(row["final_partial_identical_arms"]) for row in inventory
        ),
        "review_packets": len(inventory),
        "review_packet_rows": sum(int(row["review_packet_rows"]) for row in inventory),
        "review_rows_completed": sum(int(row["review_rows_completed"]) for row in inventory),
        "deterministically_scored_cases_per_arm": 49,
        "retention_bundle_ids": [row["retention_bundle_id"] for row in inventory],
        "objective_parser_audit": parser_audit,
        "successor_repairs": successor_repairs,
        "luna_usage": luna_usage,
        "known_interface_findings": {
            "full_system_trace_completeness": {
                "candidate_configurations": 3,
                "observations_per_candidate": 723,
                "input_lineage": "complete",
                "field_context_binding": "complete",
                "route_trace": "complete",
                "context_admission_trace": "complete",
                "evidence_lineage": "complete",
                "interpretation": "Presence and linkage contract only; not evidence correctness or answer quality.",
            },
            "french_language_preservation": {"preserved": 9, "eligible": 12},
            "local_guard_route_completeness": {"complete": 134, "eligible": 154},
            "latency_outlier": {
                "eval_id": "oacp1::canadian_decision_quality::ca_v2_manitoba_soils_06",
                "elapsed_seconds": 5062.879,
                "classification": "unexplained_host_or_runtime_stall_retained_in_results",
            },
        },
        "boundary": "RC3 measures exposed-suite deterministic diagnostics and harness behavior. It does not establish answer quality, agronomic correctness, model superiority, grower utility, field outcomes, or Benchmark v3 performance.",
    }
    _write_json(source_dir / "checkpoint_validation_receipt.json", validation)

    generated_relatives = [
        "generated_results.tex",
        "generated_tables.tex",
        "source_data/public_safe_response_measurements.csv",
        "source_data/trial_inventory.csv",
        "source_data/lane_coverage.csv",
        "source_data/deterministic_metric_summary.csv",
        "source_data/paired_arm_effects.csv",
        "source_data/retrieval_lineage_summary.csv",
        "source_data/harness_activation_summary.csv",
        "source_data/interface_trace_summary.csv",
        "source_data/repeatability_summary.csv",
        "source_data/resource_summary.csv",
        "source_data/checkpoint_validation_receipt.json",
        "figures/rc3_evidence_coverage.svg",
        "figures/rc3_evidence_coverage.pdf",
        "figures/rc3_deterministic_metrics.svg",
        "figures/rc3_deterministic_metrics.pdf",
        "figures/rc3_harness_behavior.svg",
        "figures/rc3_harness_behavior.pdf",
        "figures/rc3_repeatability_latency.svg",
        "figures/rc3_repeatability_latency.pdf",
        "figures/manifest.json",
    ]
    analysis_manifest = {
        "schema_version": SCHEMA_VERSION,
        "analysis_date": ANALYSIS_DATE,
        "analysis_seed": ANALYSIS_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "unit_of_analysis": "benchmark case after averaging the three observed trials",
        "interval_definition": "95% case-resampling sensitivity intervals with shared resample indices across candidate and arm cells within each metric family; arm contrasts are paired within case; base seed 20260815 with metric-family offsets 0/1 and contrast offsets 1000/1001; not population or human-agreement confidence intervals",
        "inputs": {
            "benchmark_suite": {"path": "data/eval/open_agronomy_canadian_performance_v1.jsonl", "sha256": EXPECTED_SUITE_SHA256, "rows": 241},
            "benchmark_source_snapshot_sha256": EXPECTED_SOURCE_SNAPSHOT_SHA256,
            "implementation_commit": EXPECTED_IMPLEMENTATION_COMMIT,
            "canonical_trial_databases": [
                {
                    "model_key": row["model_key"],
                    "trial_id": row["trial_id"],
                    "database_sha256": row["database_sha256"],
                    "retention_bundle_id": row["retention_bundle_id"],
                    "terminal_invocation_sha256": row["terminal_invocation_sha256"],
                }
                for row in inventory
            ],
        },
        "outputs": _manifest_records(paper_root, generated_relatives),
        "boundaries": [
            "No semantic answer-quality judgment is present.",
            "No missing score is converted to zero.",
            "The frozen 14/16 calculation parser result is preserved; 16/16 is separately labelled as a post-run tool-payload audit.",
            "Retrieval, verifier, tool, stability, latency, and trace presence are not interpreted as agronomic correctness.",
            "Only the nine completion-receipted bundles are inputs; the superseded unreferenced bundle is excluded.",
        ],
    }
    _write_json(source_dir / "analysis_manifest.json", analysis_manifest)
    result = {
        "status": "generated",
        "observations": len(rows),
        "trials": len(inventory),
        "figures": len(figure_records),
        "semantic_judgments": 0,
        "analysis_manifest_sha256": _sha256_path(source_dir / "analysis_manifest.json"),
    }
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completion-root", type=Path, default=DEFAULT_COMPLETION_ROOT)
    parser.add_argument("--retention-root", type=Path, default=DEFAULT_RETENTION_ROOT)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--store-manifest", type=Path, default=DEFAULT_STORE_MANIFEST)
    parser.add_argument("--paper-root", type=Path, default=DEFAULT_PAPER_ROOT)
    parser.add_argument("--verify-published", action="store_true")
    parser.add_argument("--finalize-package", action="store_true")
    args = parser.parse_args()
    if args.verify_published and args.finalize_package:
        parser.error("--verify-published and --finalize-package are mutually exclusive")
    paper_root = args.paper_root.resolve()
    if args.verify_published:
        _verify_published(paper_root)
    elif args.finalize_package:
        payload = _finalize_package(paper_root)
        print(json.dumps({"status": "finalized", "artifact_count": payload["artifact_count"], "aggregate_sha256": payload["aggregate_sha256"]}, sort_keys=True))
    else:
        build_checkpoint(
            completion_root=args.completion_root.resolve(),
            retention_root=args.retention_root.resolve(),
            suite_path=args.suite.resolve(),
            store_manifest_path=args.store_manifest.resolve(),
            paper_root=paper_root,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
