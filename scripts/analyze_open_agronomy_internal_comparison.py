#!/usr/bin/env python3
"""Build a reproducible comparison receipt for internal-v2 paired model runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.answer_verifier import _looks_incomplete, _looks_repetitive  # noqa: E402


DEFAULT_EXPERIMENT = ROOT / "outputs/open_agronomy_internal_v2_model_comparison"
DEFAULT_SUITE = ROOT / "data/eval/open_agronomy_internal_v2.jsonl"
DEFAULT_DECISION_CARDS = ROOT / "outputs/decision_card_pilot_20260730/decision_cards.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))
    return ordered[index]


def _summary(values: list[float], digits: int = 3) -> dict[str, float]:
    return {
        "mean": round(statistics.mean(values), digits),
        "median": round(statistics.median(values), digits),
        "p95": round(_quantile(values, 0.95), digits),
    }


def _source_records(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    records: dict[str, dict[str, Any]] = {}
    for case in cases:
        source_path = str(case["source_suite"])
        if source_path not in cache:
            cache[source_path] = _read_jsonl(ROOT / source_path)
        source_eval_id = str(case["source_eval_id"])
        records[case["eval_id"]] = next(
            row
            for row in cache[source_path]
            if str(row.get("eval_id") or row.get("id")) == source_eval_id
        )
    return records


def _decision_card_admission_index(path: Path = DEFAULT_DECISION_CARDS) -> dict[str, dict[str, Any]]:
    """Return the explicit runtime-admission state for compiled research cards.

    Decision-card identifiers are not knowledge-graph node identifiers.  The
    pilot cards are also governed artifacts: a card can be expected by a
    research case while still being forbidden from runtime retrieval.  Keep
    that distinction visible in the comparison receipt.
    """

    if not path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    for card in _read_jsonl(path):
        card_id = str(card.get("card_id") or "")
        if not card_id:
            continue
        runtime = card.get("runtime") or {}
        review = card.get("review") or {}
        index[card_id] = {
            "packaged_in_runtime": runtime.get("packaged_in_runtime") is True,
            "advisory_authority": runtime.get("advisory_authority") is True,
            "review_status": str(review.get("status") or "unknown"),
        }
    return index


def build_analysis(experiment: Path, suite_path: Path) -> dict[str, Any]:
    database = experiment / "full_system_benchmark.sqlite3"
    report = json.loads((experiment / "benchmark_report.json").read_text(encoding="utf-8"))
    suite = _read_jsonl(suite_path)
    source_records = _source_records(suite)
    card_admission = _decision_card_admission_index()
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    response_rows = connection.execute(
        """
        SELECT m.model_id, m.model_revision, br.system_variant, r.response_id,
               r.eval_id, r.output, r.elapsed_seconds, r.context_block,
               r.generation_path, r.score_json, r.metadata_json,
               bc.eval_metadata_json
        FROM response r
        JOIN benchmark_run br ON br.run_id = r.run_id
        JOIN model m ON m.model_key = br.model_key
        JOIN benchmark_case bc ON bc.eval_id = r.eval_id
        WHERE br.is_canonical = 1
        """
    ).fetchall()
    available_variants = {str(row["system_variant"]) for row in response_rows}
    baseline_variant = next(
        (
            value
            for value in ("raw_model", "model_only_baseline", "kernel_only")
            if value in available_variants
        ),
        "raw_model",
    )
    analyzed_variants = [
        value
        for value in (
            "raw_model",
            "kernel_only",
            "kernel_field_context",
            "model_only_baseline",
            "full_system",
        )
        if value in available_variants
    ]
    documents: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        "SELECT response_id, rank, doc_id, source_id, text FROM retrieved_document ORDER BY response_id, rank"
    ):
        documents[str(row["response_id"])].append(dict(row))

    models = sorted({str(row["model_id"]) for row in response_rows})
    arm_stats: list[dict[str, Any]] = []
    for model_id in models:
        for variant in analyzed_variants:
            rows = [
                row for row in response_rows
                if row["model_id"] == model_id and row["system_variant"] == variant
            ]
            word_counts = [len(str(row["output"]).split()) for row in rows]
            latencies = [float(row["elapsed_seconds"]) for row in rows]
            generation_paths: Counter[str] = Counter()
            generation_tokens: list[int] = []
            verifier_actions: Counter[str] = Counter()
            for row in rows:
                metadata = json.loads(row["metadata_json"])
                generation_paths[str(row["generation_path"] or "generated_answer")] += 1
                stats = metadata.get("generation_stats") or {}
                if stats.get("generation_tokens") is not None:
                    generation_tokens.append(int(stats["generation_tokens"]))
                verification = metadata.get("answer_verification") or {}
                action = verification.get("intervention_action")
                if action:
                    verifier_actions[str(action)] += 1
            arm_stats.append(
                {
                    "model_id": model_id,
                    "model_revision": rows[0]["model_revision"],
                    "system_variant": variant,
                    "responses": len(rows),
                    "empty_outputs": sum(not str(row["output"]).strip() for row in rows),
                    "word_count": _summary([float(value) for value in word_counts], 1),
                    "latency_seconds": _summary(latencies, 3),
                    "context_packets_present": sum(bool(str(row["context_block"] or "").strip()) for row in rows),
                    "repetitive_output_count": sum(_looks_repetitive(str(row["output"])) for row in rows),
                    "incomplete_output_count": sum(_looks_incomplete(str(row["output"])) for row in rows),
                    "generation_path_counts": dict(sorted(generation_paths.items())),
                    "verifier_intervention_counts": dict(sorted(verifier_actions.items())),
                    "generation_token_records": len(generation_tokens),
                    "generation_at_480_token_ceiling": sum(value >= 480 for value in generation_tokens),
                }
            )

    lane_rows = connection.execute(
        "SELECT * FROM benchmark_lane_summary ORDER BY model_id, benchmark_lane, system_variant"
    ).fetchall()
    lane_values: dict[tuple[str, str], dict[str, float | None]] = defaultdict(dict)
    lane_roles: dict[tuple[str, str], str] = {}
    for row in lane_rows:
        key = (str(row["model_id"]), str(row["benchmark_lane"]))
        lane_values[key][str(row["system_variant"])] = row["valid_proxy_mean"]
        lane_roles[key] = str(row["metric_role"])
    lane_comparisons: list[dict[str, Any]] = []
    for (model_id, lane), values in sorted(lane_values.items()):
        baseline = values.get(baseline_variant)
        full = values.get("full_system")
        pair_counts = connection.execute(
            """
            SELECT
              SUM(CASE WHEN p.full_system_proxy_score > p.baseline_proxy_score THEN 1 ELSE 0 END),
              SUM(CASE WHEN p.full_system_proxy_score = p.baseline_proxy_score THEN 1 ELSE 0 END),
              SUM(CASE WHEN p.full_system_proxy_score < p.baseline_proxy_score THEN 1 ELSE 0 END),
              COUNT(p.baseline_proxy_score)
            FROM paired_response p
            JOIN benchmark_case bc ON bc.eval_id = p.eval_id
            WHERE p.model_id = ?
              AND json_extract(bc.eval_metadata_json, '$.benchmark_lane') = ?
              AND p.baseline_proxy_score IS NOT NULL
              AND p.full_system_proxy_score IS NOT NULL
            """,
            (model_id, lane),
        ).fetchone()
        lane_comparisons.append(
            {
                "model_id": model_id,
                "benchmark_lane": lane,
                "metric_role": lane_roles[(model_id, lane)],
                "baseline_valid_proxy_mean": baseline,
                "full_system_valid_proxy_mean": full,
                "delta": None if baseline is None or full is None else round(float(full) - float(baseline), 3),
                "paired_proxy_outcomes": {
                    "wins": int(pair_counts[0] or 0),
                    "ties": int(pair_counts[1] or 0),
                    "losses": int(pair_counts[2] or 0),
                    "scored_pairs": int(pair_counts[3] or 0),
                },
            }
        )

    outputs_by_model: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in response_rows:
        if row["system_variant"] == "full_system":
            outputs_by_model[str(row["model_id"])][str(row["eval_id"])] = dict(row)
    trace_results: list[dict[str, Any]] = []
    for model_id in models:
        model_outputs = outputs_by_model[model_id]
        for lane in ("retrieval_lineage", "field_history_lineage"):
            lane_cases = [case for case in suite if case["benchmark_lane"] == lane]
            expected_source_cases = source_hits = 0
            expected_card_cases = runtime_admitted_card_cases = quarantined_card_cases = 0
            unknown_card_admission_cases = runtime_card_hits = quarantined_card_leakage_hits = 0
            pattern_cases = complete_pattern_cases = pattern_total = pattern_hits = 0
            for case in lane_cases:
                source = source_records[case["eval_id"]]
                response = model_outputs[case["eval_id"]]
                metadata = json.loads(response["metadata_json"])
                docs = documents[response["response_id"]]
                source_ids = {str(doc.get("source_id") or "") for doc in docs}
                expected_sources = (
                    [str(source["support_source_id"])]
                    if source.get("support_source_id")
                    else [str(value) for value in source.get("expected_source_ids") or []]
                )
                if expected_sources:
                    expected_source_cases += 1
                    source_hits += any(value in source_ids for value in expected_sources)
                expected_cards = [str(value) for value in source.get("expected_card_ids") or []]
                if expected_cards:
                    expected_card_cases += 1
                    graph_nodes = {str(value) for value in metadata.get("graph_nodes") or []}
                    states = [card_admission.get(value) for value in expected_cards]
                    admitted = [
                        value
                        for value, state in zip(expected_cards, states)
                        if state is not None and state["packaged_in_runtime"]
                    ]
                    quarantined = [
                        value
                        for value, state in zip(expected_cards, states)
                        if state is not None and not state["packaged_in_runtime"]
                    ]
                    unknown = [value for value, state in zip(expected_cards, states) if state is None]
                    runtime_admitted_card_cases += bool(admitted)
                    quarantined_card_cases += bool(quarantined)
                    unknown_card_admission_cases += bool(unknown)
                    runtime_card_hits += any(value in graph_nodes for value in admitted)
                    quarantined_card_leakage_hits += any(value in graph_nodes for value in quarantined)
                patterns = [str(value) for value in source.get("required_retrieval_patterns") or []]
                if patterns:
                    pattern_cases += 1
                    text = "\n".join(str(doc.get("text") or "") for doc in docs)
                    hits = [bool(re.search(pattern, text, re.IGNORECASE)) for pattern in patterns]
                    complete_pattern_cases += all(hits)
                    pattern_hits += sum(hits)
                    pattern_total += len(hits)
            trace_results.append(
                {
                    "model_id": model_id,
                    "benchmark_lane": lane,
                    "cases": len(lane_cases),
                    "expected_source_case_hits": source_hits,
                    "expected_source_cases": expected_source_cases,
                    "expected_source_case_recall": (
                        round(source_hits / expected_source_cases, 4) if expected_source_cases else None
                    ),
                    "complete_retrieval_pattern_cases": complete_pattern_cases,
                    "retrieval_pattern_cases": pattern_cases,
                    "retrieval_pattern_case_recall": (
                        round(complete_pattern_cases / pattern_cases, 4) if pattern_cases else None
                    ),
                    "retrieval_pattern_hits": pattern_hits,
                    "retrieval_patterns": pattern_total,
                    "expected_card_cases": expected_card_cases,
                    "runtime_admitted_card_cases": runtime_admitted_card_cases,
                    "runtime_card_case_hits": runtime_card_hits,
                    "runtime_card_case_recall": (
                        round(runtime_card_hits / runtime_admitted_card_cases, 4)
                        if runtime_admitted_card_cases
                        else None
                    ),
                    "quarantined_card_cases": quarantined_card_cases,
                    "quarantined_card_leakage_hits": quarantined_card_leakage_hits,
                    "unknown_card_admission_cases": unknown_card_admission_cases,
                }
            )

    cross_model: dict[str, Any] = {}
    if len(models) >= 2:
        for variant in analyzed_variants:
            by_model: dict[str, dict[str, str]] = {}
            for model_id in models:
                by_model[model_id] = {
                    str(row["eval_id"]): str(row["output"])
                    for row in response_rows
                    if row["model_id"] == model_id and row["system_variant"] == variant
                }
            cross_model[variant] = {
                "byte_identical_outputs": sum(
                    len({by_model[model_id][eval_id] for model_id in models}) == 1
                    for eval_id in by_model[models[0]]
                ),
                "paired_cases": len(by_model[models[0]]),
                "models_compared": models,
            }

    review_packets: dict[str, str] = {}
    for model_id in models:
        pattern = "*270m*/manifest.json" if "270m" in model_id else "*e2b*/manifest.json"
        manifest = next((experiment / "review_packets").glob(pattern), None)
        if manifest is not None:
            review_packets[model_id] = str(manifest.relative_to(ROOT))

    judge_rows = connection.execute(
        """
        SELECT m.model_id, br.system_variant, r.eval_id, ja.semantic_score,
               ja.answer_disposition, jr.judge_generator_relationship
        FROM judge_assessment ja
        JOIN judge_run jr ON jr.judge_run_id = ja.judge_run_id
        JOIN benchmark_run br ON br.run_id = jr.source_run_id
        JOIN model m ON m.model_key = br.model_key
        JOIN response r ON r.response_id = ja.response_id
        WHERE br.is_canonical = 1 AND jr.judge_role = 'semantic_answer_quality'
        ORDER BY m.model_id, br.system_variant, r.eval_id
        """
    ).fetchall()
    judge_by_arm: list[dict[str, Any]] = []
    judge_by_model: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for model_id in sorted({str(row["model_id"]) for row in judge_rows}):
        for variant in analyzed_variants:
            rows = [
                row for row in judge_rows
                if row["model_id"] == model_id and row["system_variant"] == variant
            ]
            scores = [float(row["semantic_score"]) for row in rows if row["semantic_score"] is not None]
            dispositions = Counter(str(row["answer_disposition"] or "unknown") for row in rows)
            relationship = sorted({str(row["judge_generator_relationship"] or "unknown") for row in rows})
            record = {
                "model_id": model_id,
                "system_variant": variant,
                "assessments": len(rows),
                "semantic_score_mean": round(statistics.mean(scores), 3) if scores else None,
                "answer_disposition": dict(sorted(dispositions.items())),
                "judge_generator_relationship": relationship,
            }
            judge_by_arm.append(record)
            judge_by_model[model_id][variant] = {
                str(row["eval_id"]): float(row["semantic_score"])
                for row in rows if row["semantic_score"] is not None
            }
    judge_paired_comparisons: list[dict[str, Any]] = []
    for model_id, variants in sorted(judge_by_model.items()):
        baseline = variants.get(baseline_variant, {})
        full = variants.get("full_system", {})
        paired_ids = sorted(set(baseline) & set(full))
        deltas = [full[eval_id] - baseline[eval_id] for eval_id in paired_ids]
        judge_paired_comparisons.append(
            {
                "model_id": model_id,
                "paired_cases": len(paired_ids),
                "full_minus_baseline_mean": round(statistics.mean(deltas), 3) if deltas else None,
                "full_higher": sum(delta > 0 for delta in deltas),
                "tied": sum(delta == 0 for delta in deltas),
                "baseline_higher": sum(delta < 0 for delta in deltas),
            }
        )
    judge_lane_comparisons = [
        dict(row)
        for row in connection.execute(
            f"""
            WITH judgment AS (
              SELECT m.model_id, br.system_variant, r.eval_id, ja.semantic_score,
                     json_extract(bc.eval_metadata_json, '$.benchmark_lane') AS benchmark_lane
              FROM judge_assessment ja
              JOIN judge_run jr ON jr.judge_run_id = ja.judge_run_id
              JOIN benchmark_run br ON br.run_id = jr.source_run_id
              JOIN model m ON m.model_key = br.model_key
              JOIN response r ON r.response_id = ja.response_id
              JOIN benchmark_case bc ON bc.eval_id = r.eval_id
              WHERE br.is_canonical = 1 AND jr.judge_role = 'semantic_answer_quality'
            ), paired AS (
              SELECT baseline.model_id, baseline.benchmark_lane, baseline.eval_id,
                     baseline.semantic_score AS baseline_score,
                     full_system.semantic_score AS full_system_score
              FROM judgment baseline
              JOIN judgment full_system
                ON full_system.model_id = baseline.model_id
               AND full_system.eval_id = baseline.eval_id
               AND full_system.benchmark_lane = baseline.benchmark_lane
              WHERE baseline.system_variant = '{baseline_variant}'
                AND full_system.system_variant = 'full_system'
            )
            SELECT model_id, benchmark_lane, COUNT(*) AS paired_cases,
                   ROUND(AVG(full_system_score - baseline_score), 3) AS full_minus_baseline_mean,
                   SUM(full_system_score > baseline_score) AS full_higher,
                   SUM(full_system_score = baseline_score) AS tied,
                   SUM(full_system_score < baseline_score) AS baseline_higher
            FROM paired
            GROUP BY model_id, benchmark_lane
            ORDER BY model_id, benchmark_lane
            """
        )
    ]
    judge_intervention_comparisons = [
        dict(row)
        for row in connection.execute(
            f"""
            WITH judgment AS (
              SELECT m.model_id, br.system_variant, r.eval_id, ja.semantic_score
              FROM judge_assessment ja
              JOIN judge_run jr ON jr.judge_run_id = ja.judge_run_id
              JOIN benchmark_run br ON br.run_id = jr.source_run_id
              JOIN model m ON m.model_key = br.model_key
              JOIN response r ON r.response_id = ja.response_id
              WHERE br.is_canonical = 1 AND jr.judge_role = 'semantic_answer_quality'
            ), full_system_metadata AS (
              SELECT m.model_id, r.eval_id,
                     COALESCE(
                       json_extract(r.metadata_json, '$.answer_verification.intervention_action'),
                       'not_run'
                     ) AS intervention_action
              FROM response r
              JOIN benchmark_run br ON br.run_id = r.run_id
              JOIN model m ON m.model_key = br.model_key
              WHERE br.is_canonical = 1 AND br.system_variant = 'full_system'
            ), paired AS (
              SELECT baseline.model_id, baseline.eval_id,
                     baseline.semantic_score AS baseline_score,
                     full_system.semantic_score AS full_system_score,
                     metadata.intervention_action
              FROM judgment baseline
              JOIN judgment full_system
                ON full_system.model_id = baseline.model_id
               AND full_system.eval_id = baseline.eval_id
              JOIN full_system_metadata metadata
                ON metadata.model_id = baseline.model_id
               AND metadata.eval_id = baseline.eval_id
              WHERE baseline.system_variant = '{baseline_variant}'
                AND full_system.system_variant = 'full_system'
            )
            SELECT model_id, intervention_action, COUNT(*) AS paired_cases,
                   ROUND(AVG(full_system_score - baseline_score), 3) AS full_minus_baseline_mean,
                   SUM(full_system_score > baseline_score) AS full_higher,
                   SUM(full_system_score = baseline_score) AS tied,
                   SUM(full_system_score < baseline_score) AS baseline_higher
            FROM paired
            GROUP BY model_id, intervention_action
            ORDER BY model_id, intervention_action
            """
        )
    ]
    valid_judge_batches = len(list(experiment.glob("runs/*/*/*/semantic_judge*/batches/batch_[0-9][0-9][0-9][0-9].receipt.json")))
    invalid_judge_attempts = len(list(experiment.glob("runs/*/*/*/semantic_judge*/failed_attempts/*.receipt.json")))
    judge_reliability = {
        "valid_exact_id_batches": valid_judge_batches,
        "invalid_archived_attempts": invalid_judge_attempts,
        "exact_id_completion_rate_per_consumed_attempt": round(
            valid_judge_batches / (valid_judge_batches + invalid_judge_attempts), 4
        ) if valid_judge_batches + invalid_judge_attempts else None,
        "interpretation": "Structured ID-completeness reliability only; not judge correctness or calibration.",
    }
    cost_ledger_path = experiment / "cost_ledger_manifest.json"
    cost_ledger = json.loads(cost_ledger_path.read_text(encoding="utf-8")) if cost_ledger_path.is_file() else None

    connection.close()
    return {
        "schema_version": "open_agronomy_agent.internal_model_comparison.v1",
        "status": (
            "complete_internal_run_human_answer_review_pending"
            if len(models) >= 2
            else "partial_model_matrix_additional_model_pending"
        ),
        "benchmark_id": report["benchmark_id"],
        "suite_sha256": report["suite_sha256"],
        "suite_rows": report["suite_rows"],
        "database_path": str(database.relative_to(ROOT)),
        "database_sha256": _sha256(database),
        "database_integrity": integrity,
        "foreign_key_error_count": len(foreign_keys),
        "models": report["models"],
        "counts": report["counts"],
        "arm_stats": arm_stats,
        "baseline_variant": baseline_variant,
        "lane_comparisons": lane_comparisons,
        "source_contract_trace_recovery": trace_results,
        "cross_model_output_identity": cross_model,
        "review_packets": review_packets,
        "role_scoped_semantic_judge": {
            "arm_summaries": judge_by_arm,
            "paired_comparisons": judge_paired_comparisons,
            "paired_lane_comparisons": judge_lane_comparisons,
            "paired_intervention_comparisons": judge_intervention_comparisons,
            "reliability": judge_reliability,
        },
        "cost_ledger": cost_ledger,
        "interpretation_boundaries": [
            "No proxy values are combined across lanes.",
            "The 90-case Canadian decision-quality lane and 31-case advisory-transfer lane remain unscored until blinded independent agronomist review.",
            "Deterministic proxy deltas measure regression-contract coverage, not agronomic answer accuracy.",
            "Retrieval support-source and pattern expectations were recovered from the original source suites because the compiled benchmark currently drops support_source_id and required_retrieval_patterns. Field-history expectations are present in the compiled suite but are not yet scored by the canonical report.",
            "Expected decision-card identifiers are audited against explicit runtime admission. Quarantined research cards are not counted as recall misses; any appearance of one in runtime graph nodes is reported as leakage.",
            "Public verification v3 was not executed or answer-inspected.",
            "Luna-on-Luna results are self-judged and must not be compared naively with Luna cross-model judgments; all automated judgments remain uncalibrated triage.",
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    baseline_variant = str(payload.get("baseline_variant") or "model_only_baseline")
    lines = [
        "# Open Agronomy internal-v2 three-model comparison",
        "",
        f"Status: `{payload['status']}`",
        "",
        f"Suite: `{payload['benchmark_id']}` · {payload['suite_rows']} cases · `{payload['suite_sha256']}`",
        "",
        "## Arm behavior",
        "",
        "| Model | Arm | Responses | Mean words | Mean latency (s) | Repetitive | Incomplete | 480-token ceiling / attempts |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["arm_stats"]:
        lines.append(
            f"| {row['model_id']} | {row['system_variant']} | {row['responses']} | "
            f"{row['word_count']['mean']:.1f} | {row['latency_seconds']['mean']:.3f} | "
            f"{row['repetitive_output_count']} | {row['incomplete_output_count']} | "
            f"{row['generation_at_480_token_ceiling']}/{row['generation_token_records']} |"
        )
    full_rows = [row for row in payload["arm_stats"] if row["system_variant"] == "full_system"]
    hold_counts = {
        row["generation_path_counts"].get("deterministic_evidence_sufficiency_hold", 0)
        for row in full_rows
    }
    generation_counts = {row["generation_token_records"] for row in full_rows}
    hold_text = str(next(iter(hold_counts))) if len(hold_counts) == 1 else "/".join(map(str, sorted(hold_counts)))
    generation_text = (
        str(next(iter(generation_counts)))
        if len(generation_counts) == 1
        else "/".join(map(str, sorted(generation_counts)))
    )
    lines += [
        "",
        "## Harness intervention",
        "",
        f"A deterministic evidence-sufficiency hold bypassed generation for {hold_text} cases in each full-system arm. "
        f"The remaining {generation_text} cases were generated and then checked by the answer verifier.",
        "",
        "| Model | Preserve draft | Accept rewrite | Fallback or degraded |",
        "|---|---:|---:|---:|",
    ]
    for row in payload["arm_stats"]:
        if row["system_variant"] != "full_system":
            continue
        actions = row["verifier_intervention_counts"]
        lines.append(
            f"| {row['model_id']} | {actions.get('preserve_draft', 0)} | "
            f"{actions.get('accept_rewrite', 0)} | {actions.get('fallback_or_degraded', 0)} |"
        )
    identity = payload["cross_model_output_identity"]
    lines += ["", "## Cross-model output identity", ""]
    if {baseline_variant, "full_system"} <= set(identity):
        lines.append(
            f"Only {identity[baseline_variant]['byte_identical_outputs']}/"
            f"{identity[baseline_variant]['paired_cases']} baseline answers were byte-identical across models, "
            f"but {identity['full_system']['byte_identical_outputs']}/"
            f"{identity['full_system']['paired_cases']} full-system answers were. This is evidence that the current "
            "harness often dominates model choice; it is not evidence that those shared answers are correct."
        )
    else:
        lines.append("Cross-model identity is pending until a second matched model completes both arms.")
    lines += [
        "",
        "## Deterministic regression lanes",
        "",
        "These are regression-contract diagnostics, not answer-quality scores.",
        "",
        "| Model | Lane | Baseline | Full system | Delta | W/T/L |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in payload["lane_comparisons"]:
        if row["delta"] is None:
            continue
        outcomes = row["paired_proxy_outcomes"]
        lines.append(
            f"| {row['model_id']} | {row['benchmark_lane']} | "
            f"{row['baseline_valid_proxy_mean']:.3f} | {row['full_system_valid_proxy_mean']:.3f} | "
            f"{row['delta']:+.3f} | {outcomes['wins']}/{outcomes['ties']}/{outcomes['losses']} |"
        )
    lines += ["", "## Source and lineage trace recovery", ""]
    for row in payload["source_contract_trace_recovery"]:
        lines.append(
            f"- `{row['model_id']}` · `{row['benchmark_lane']}`: "
            f"source hits {row['expected_source_case_hits']}/{row['expected_source_cases']}; "
            f"complete pattern cases {row['complete_retrieval_pattern_cases']}/{row['retrieval_pattern_cases']}; "
            f"runtime-card hits {row['runtime_card_case_hits']}/{row['runtime_admitted_card_cases']}; "
            f"quarantined cases {row['quarantined_card_cases']} with "
            f"{row['quarantined_card_leakage_hits']} leakage hits; "
            f"unknown admission {row['unknown_card_admission_cases']}."
        )
    judge = payload.get("role_scoped_semantic_judge")
    if judge:
        lines += [
        "",
        "## Role-scoped Luna semantic triage",
        "",
        "These answer-quality assessments are separate from deterministic regression lanes. "
        "They are automated, uncalibrated triage rather than agronomist validation.",
        "",
        "| Model | Arm | Assessments | Mean score | Pass / revise / fail | Judge relationship |",
        "|---|---|---:|---:|---:|---|",
        ]
        for row in judge["arm_summaries"]:
            dispositions = row["answer_disposition"]
            mean = row["semantic_score_mean"]
            mean_text = "—" if mean is None else f"{mean:.3f}"
            lines.append(
                f"| {row['model_id']} | {row['system_variant']} | {row['assessments']} | {mean_text} | "
                f"{dispositions.get('pass', 0)} / {dispositions.get('revise', 0)} / "
                f"{dispositions.get('fail', 0)} | {', '.join(row['judge_generator_relationship'])} |"
            )
        lines += [
            "",
            "| Model | Paired cases | Mean full - baseline | Full higher / tie / baseline higher |",
            "|---|---:|---:|---:|",
        ]
        for row in judge["paired_comparisons"]:
            delta = row["full_minus_baseline_mean"]
            delta_text = "—" if delta is None else f"{delta:+.3f}"
            lines.append(
                f"| {row['model_id']} | {row['paired_cases']} | {delta_text} | "
                f"{row['full_higher']} / {row['tied']} / {row['baseline_higher']} |"
            )
        lines += [
            "",
            "### Paired semantic delta by harness intervention",
            "",
            "`not_run` is the deterministic evidence-sufficiency hold; the candidate model did not generate these answers.",
            "",
            "| Model | Full-system intervention | Cases | Mean full - baseline | Full higher / tie / baseline higher |",
            "|---|---|---:|---:|---:|",
        ]
        for row in judge["paired_intervention_comparisons"]:
            delta = row["full_minus_baseline_mean"]
            delta_text = "—" if delta is None else f"{delta:+.3f}"
            lines.append(
                f"| {row['model_id']} | {row['intervention_action']} | {row['paired_cases']} | "
                f"{delta_text} | {row['full_higher']} / {row['tied']} / {row['baseline_higher']} |"
            )
        reliability = judge["reliability"]
        completion_rate = reliability["exact_id_completion_rate_per_consumed_attempt"]
        completion_text = "—" if completion_rate is None else f"{completion_rate:.1%}"
        lines += [
            "",
            f"Structured-output reliability: {reliability['valid_exact_id_batches']} exact-ID-complete batches, "
            f"{reliability['invalid_archived_attempts']} archived invalid attempts, "
            f"{completion_text} completion per consumed attempt. {reliability['interpretation']}",
        ]
    ledger = payload.get("cost_ledger")
    if ledger:
        totals = ledger["totals"]
        lines += [
            "",
            "## Luna usage ledger",
            "",
            f"Indexed {totals['calls']} calls and {totals['total_tokens']:,} total tokens. "
            f"The standard-pricing API-equivalent estimate is "
            f"${totals['api_equivalent_cost_usd']:.6f} USD; actual ChatGPT-authenticated "
            "App Server billing is not observable from this run.",
        ]
    lines += ["", "## Interpretation boundaries", ""]
    lines.extend(f"- {value}" for value in payload["interpretation_boundaries"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    args = parser.parse_args()
    experiment = args.experiment_dir.resolve()
    payload = build_analysis(experiment, args.suite.resolve())
    json_path = experiment / "comparison_analysis.json"
    markdown_path = experiment / "comparison_analysis.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "json": str(json_path), "markdown": str(markdown_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
