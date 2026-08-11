"""Frozen Open Agronomy Benchmark compilation and validation.

The contract deliberately separates answer-quality, known-failure regression,
and external-transfer evidence.  It never converts those lanes into one score.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "open_agronomy_agent.benchmark_case.v1"
MANIFEST_VERSION = "open_agronomy_agent.benchmark_manifest.v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(row)
    return rows


def _task_family(row: dict[str, Any], lane: str) -> str:
    return str(row.get("task_family") or row.get("category") or lane).lower().replace(" ", "_")


def normalize_case(
    row: dict[str, Any],
    *,
    source: dict[str, Any],
    benchmark_namespace: str = "oab1",
    evaluation_partition: str | None = None,
) -> dict[str, Any]:
    source_id = str(row.get("eval_id") or row.get("id") or row.get("prompt_id") or "").strip()
    question = str(row.get("question") or "").strip()
    if not source_id or not question:
        raise ValueError(f"incomplete benchmark source row: {source['path']}:{source_id or '<missing>'}")
    lane = str(source["lane"])
    required_patterns = list(row.get("required_patterns") or [])
    forbidden_patterns = list(row.get("forbidden_patterns") or [])
    ask_for_patterns = list(row.get("ask_for_patterns") or [])
    reference_points = list(row.get("expert_reference_points") or row.get("gold_answers") or [])
    if isinstance(row.get("gold_answer"), str) and not reference_points:
        reference_points = [str(row["gold_answer"])]
    field_context = dict(row.get("field_context") or {})
    for target, source_key in (("province_state", "jurisdiction"), ("crop_current", "crop"), ("region_text", "region")):
        if row.get(source_key) is not None:
            field_context.setdefault(target, row[source_key])
    lexical_contract = bool(required_patterns or forbidden_patterns or ask_for_patterns)
    default_origin = (
        "project_authored_or_legacy_synthetic_not_real_user"
        if evaluation_partition == "internal"
        else "synthetic_or_external_dataset_not_real_user_provenance"
    )
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "eval_id": f"{benchmark_namespace}::{lane}::{source_id}",
        "source_eval_id": source_id,
        "source_suite": str(source["path"]),
        "benchmark_lane": lane,
        "metric_role": str(source["metric_role"]),
        "primary_benchmark_lane": bool(source.get("primary", False)),
        "question": question,
        "task_family": _task_family(row, lane),
        "jurisdiction": row.get("jurisdiction"),
        "crop": row.get("crop"),
        "category": row.get("category") or (row.get("topic_categories") or [None])[0],
        "question_style": row.get("question_style"),
        "language": row.get("language") or "English",
        "support_mode": row.get("support_mode"),
        "difficulty": row.get("difficulty") or row.get("hardness_bucket"),
        "field_context": field_context,
        "expert_reference_points": reference_points,
        "required_patterns": required_patterns,
        "forbidden_patterns": forbidden_patterns,
        "ask_for_patterns": ask_for_patterns,
        "required_tools": list(row.get("required_tools") or row.get("expected_tools") or []),
        "expected_tools": list(row.get("required_tools") or row.get("expected_tools") or []),
        "preferred_source_ids": list(row.get("preferred_source_ids") or row.get("expected_source_ids") or []),
        "forbidden_source_ids": list(row.get("forbidden_source_ids") or []),
        "source_use_boundary": row.get("source_use_boundary"),
        "wrong_jurisdiction_policy": row.get("wrong_jurisdiction_policy"),
        "question_origin": row.get("question_origin") or default_origin,
        "official_ai_agribench": False,
        "claim_eligible": bool(source.get("claim_eligible", False)),
        "lexical_contract_available": lexical_contract,
        "review_policy": dict(source.get("review_policy") or {
            "automated_judge_role": "triage_only",
            "deterministic_proxy_role": "regression_only" if lexical_contract else "undefined",
            "independent_agronomist_review_required": lane == "canadian_decision_quality",
        }),
    }
    if evaluation_partition is not None:
        normalized["evaluation_partition"] = evaluation_partition
    for key in (
        "reference_answer",
        "expected_answer",
        "acceptable_answer_variants",
        "material_errors",
        "critical_evidence",
        "safe_boundary",
        "public_dataset_id",
        "public_dataset_revision",
        "public_source_row_index",
        "public_source_question",
        "option_permutation",
        "correct_option_text",
        "correct_option_roman",
        "correct_option_word_length_rank",
        "original_difficulty_level",
        "expected_card_ids",
        "expected_source_ids",
        "expected_advisory_authority",
        "expected_public_adapters",
        "scoring_method",
        "reference_numeric",
        "reference_unit",
        "unit_aliases",
        "absolute_tolerance",
        "calculation_contract",
        "source_url",
        "source_license",
        "source_revision",
        "cca_domain_alignment",
        "reference_answer_status",
        "source_question_sha256",
    ):
        if key in row:
            normalized[key] = row[key]
    return normalized


def compile_benchmark(root: Path, contract_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = read_json(contract_path)
    if contract.get("schema_version") != "open_agronomy_agent.benchmark_contract.v1":
        raise ValueError("unsupported benchmark contract schema")
    evaluation_partition = contract.get("evaluation_partition")
    if evaluation_partition not in (None, "internal", "public"):
        raise ValueError("evaluation_partition must be internal or public")
    sources = list(contract.get("sources") or [])
    if evaluation_partition == "internal" and any(source.get("origin_class") == "public_benchmark" for source in sources):
        raise ValueError("internal benchmark cannot include a public benchmark source")
    if evaluation_partition == "public" and any(source.get("origin_class") != "public_benchmark" for source in sources):
        raise ValueError("public benchmark may include only public benchmark sources")
    rows: list[dict[str, Any]] = []
    source_receipts: list[dict[str, Any]] = []
    benchmark_namespace = str(contract.get("benchmark_namespace") or "oab1")
    deduplicate = contract.get("deduplication_policy") == "keep_first_source_order"
    seen_questions: set[str] = set()
    for source in sources:
        path = root / str(source["path"])
        actual_sha = sha256(path)
        if actual_sha != source.get("sha256"):
            raise ValueError(f"frozen source SHA-256 mismatch: {source['path']}")
        source_rows = read_jsonl(path)
        if len(source_rows) != int(source.get("rows") or -1):
            raise ValueError(f"frozen source row mismatch: {source['path']}")
        normalized_source_rows = [
            normalize_case(
                row,
                source=source,
                benchmark_namespace=benchmark_namespace,
                evaluation_partition=evaluation_partition,
            )
            for row in source_rows
        ]
        excluded_exact_duplicates = 0
        if deduplicate:
            retained: list[dict[str, Any]] = []
            for row in normalized_source_rows:
                question_hash = hashlib.sha256(str(row["question"]).strip().lower().encode("utf-8")).hexdigest()
                if question_hash in seen_questions:
                    excluded_exact_duplicates += 1
                    continue
                seen_questions.add(question_hash)
                retained.append(row)
            normalized_source_rows = retained
        rows.extend(normalized_source_rows)
        receipt = {**source, "actual_sha256": actual_sha}
        if deduplicate:
            receipt.update({
                "included_rows": len(normalized_source_rows),
                "excluded_exact_duplicates": excluded_exact_duplicates,
            })
        source_receipts.append(receipt)
    ids = [str(row["eval_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate normalized eval IDs")
    question_hashes = [hashlib.sha256(str(row["question"]).encode("utf-8")).hexdigest() for row in rows]
    duplicates = len(question_hashes) - len(set(question_hashes))
    if duplicates:
        raise ValueError(f"canonical benchmark contains {duplicates} exact duplicate questions")
    lane_counts = Counter(str(row["benchmark_lane"]) for row in rows)
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "benchmark_id": contract["benchmark_id"],
        "status": contract["status"],
        "contract_path": str(contract_path.relative_to(root)),
        "contract_sha256": sha256(contract_path),
        "suite_path": contract["suite_path"],
        "rows": len(rows),
        "lane_counts": dict(sorted(lane_counts.items())),
        "unique_questions": len(set(question_hashes)),
        "exact_duplicate_questions": duplicates,
        "traceable_real_user_questions": sum(
            str(row["question_origin"]).lower().startswith("real_user") for row in rows
        ),
        "claim_eligible": bool(contract.get("claim_eligible", False)),
        "default_modes": list(contract.get("default_modes") or []),
        "primary_comparison": contract.get("primary_comparison"),
        "sources": source_receipts,
        "evaluation_policy": contract["evaluation_policy"],
        "contamination_policy": contract["contamination_policy"],
        "result_contract": contract["result_contract"],
    }
    if evaluation_partition is not None:
        manifest["evaluation_partition"] = evaluation_partition
        manifest["question_origin_counts"] = dict(sorted(Counter(str(row["question_origin"]) for row in rows).items()))
    if contract.get("system_interface_contract"):
        manifest["system_interface_contract"] = contract["system_interface_contract"]
    if deduplicate:
        manifest["deduplication_policy"] = contract["deduplication_policy"]
    return rows, manifest


def write_benchmark(root: Path, contract_path: Path) -> dict[str, Any]:
    rows, manifest = compile_benchmark(root, contract_path)
    suite_path = root / str(read_json(contract_path)["suite_path"])
    manifest_path = root / str(read_json(contract_path)["manifest_path"])
    suite_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    manifest["suite_sha256"] = sha256(suite_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def validate_benchmark(root: Path, contract_path: Path) -> dict[str, Any]:
    contract = read_json(contract_path)
    expected_rows, expected = compile_benchmark(root, contract_path)
    suite_path = root / str(contract["suite_path"])
    manifest_path = root / str(contract["manifest_path"])
    actual_rows = read_jsonl(suite_path)
    actual_manifest = read_json(manifest_path)
    if actual_rows != expected_rows:
        raise ValueError("compiled benchmark suite drift; rebuild from frozen sources")
    expected["suite_sha256"] = sha256(suite_path)
    if actual_manifest != expected:
        raise ValueError("benchmark manifest drift; rebuild from frozen sources")
    return actual_manifest
