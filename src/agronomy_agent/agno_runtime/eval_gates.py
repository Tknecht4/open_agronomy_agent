from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path
from agronomy_agent.agno_runtime.rollback import load_agentos_decision


DEFAULT_AGNO_GATE_MATRIX = "plans/agronomy_agent_agno_rag_foundation_packet/agno_rag_eval_gate_matrix.csv"


def load_agno_eval_gate_matrix(path: str | Path = DEFAULT_AGNO_GATE_MATRIX) -> list[dict[str, str]]:
    with repo_path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Agno RAG eval gate matrix is empty")
    required = {"gate_id", "gate_name", "scope", "pass_condition", "block_condition", "owner"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Agno RAG eval gate matrix missing columns: {', '.join(sorted(missing))}")
    return rows


def evaluate_agno_promotion_gates(metrics: dict[str, Any], *, matrix_path: str | Path = DEFAULT_AGNO_GATE_MATRIX) -> dict[str, Any]:
    rows = load_agno_eval_gate_matrix(matrix_path)
    metrics = normalize_agno_promotion_metrics(metrics)
    reasons: list[str] = []
    if metrics.get("profile_only_requires_comparison_report", False):
        reasons.append("comparison_report_required")
    if not metrics.get("legacy_parity_passed", False):
        reasons.append("legacy_parity_failed")
    if metrics.get("safety_regressions", 0):
        reasons.append("safety_regression")
    if metrics.get("prompt_leak_count", 0):
        reasons.append("prompt_leak_regression")
    if metrics.get("metadata_access_violations", 0):
        reasons.append("metadata_access_violation")
    if metrics.get("agno_dependency_available") is not True:
        reasons.append("agno_dependency_missing")
    support_delta = float(metrics.get("retrieval_support_delta", 0.0))
    if support_delta < 0 and not str(metrics.get("retrieval_parity_reason") or "").strip():
        reasons.append("retrieval_support_regression")
    latency_ratio = float(metrics.get("warm_p95_latency_ratio", 1.0))
    latency_delta_ms = float(metrics.get("warm_p95_latency_delta_ms", 0.0))
    if latency_ratio > 1.25 and latency_delta_ms > 5.0 and not metrics.get("explicit_latency_approval", False):
        reasons.append("latency_regression")
    if _nonempty_sequence(metrics.get("case_latency_regression_case_ids")) and not metrics.get("explicit_latency_approval", False):
        reasons.append("case_latency_regression")
    if metrics.get("resource_load_within_budget") is False:
        reasons.append("resource_load_budget_exceeded")
    if metrics.get("resource_singleton_reused") is False:
        reasons.append("resource_singleton_reuse_missed")
    if metrics.get("resource_singleton_reuse_within_budget") is False:
        reasons.append("resource_singleton_reuse_budget_exceeded")
    if metrics.get("compiled_index_cache_within_budget") is False:
        reasons.append("compiled_index_cache_budget_exceeded")
    if metrics.get("agno_index_max_eligible_docs_within_budget") is False or _metric_exceeds_budget(
        metrics,
        value_key="agno_index_max_eligible_docs",
        budget_key="agno_index_max_eligible_docs_budget",
    ):
        reasons.append("agno_index_eligible_fanout_budget_exceeded")
    if metrics.get("agno_index_max_scored_candidates_within_budget") is False or _metric_exceeds_budget(
        metrics,
        value_key="agno_index_max_scored_candidates",
        budget_key="agno_index_max_scored_candidates_budget",
    ):
        reasons.append("agno_index_scored_candidate_budget_exceeded")
    if metrics.get("agno_index_runtime_caches_within_budget") is False:
        reasons.append("agno_index_runtime_cache_budget_exceeded")
    profile_recommendation = str(metrics.get("profile_recommendation") or "").strip()
    if profile_recommendation and profile_recommendation != "promote_agno_replace_legacy":
        reasons.append("agno_replacement_not_recommended")
    legacy_profile_scope = str(metrics.get("legacy_profile_scope") or "").strip()
    if legacy_profile_scope and legacy_profile_scope != "benchmark_only_retired_serving_path_removed":
        reasons.append("legacy_serving_scope_not_retired")
    if not metrics.get("rollback_verified", False):
        reasons.append("rollback_not_verified")
    if not metrics.get("trace_completeness_passed", False):
        reasons.append("trace_incomplete")
    if not str(metrics.get("agentos_decision") or "").strip():
        reasons.append("agentos_decision_missing")
    return {
        "report_version": "agno_rag_promotion_gate_v1",
        "gate_count": len(rows),
        "promotion_allowed": not reasons,
        "reasons": reasons,
        "gate_ids": [row["gate_id"] for row in rows],
        "metrics": metrics,
    }


def normalize_agno_promotion_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    if metrics.get("report_version") == "agno_rag_comparison_report_v1" and isinstance(metrics.get("metrics"), dict):
        normalized = dict(metrics["metrics"])
    elif metrics.get("report_version") == "agno_vs_legacy_profile_v1" and isinstance(metrics.get("summary"), dict):
        summary = dict(metrics["summary"])
        normalized = {
            **summary,
            "profile_only_requires_comparison_report": True,
            "legacy_parity_passed": not bool(summary.get("support_regression_case_ids")),
            "agno_dependency_available": (summary.get("agno_dependency") or {}).get("sdk_available") is True,
        }
    else:
        normalized = dict(metrics)
    rollback_evidence = normalized.get("rollback_evidence")
    if isinstance(rollback_evidence, dict) and rollback_evidence.get("report_version") == "agno_rag_rollback_probe_v1":
        normalized["rollback_verified"] = bool(rollback_evidence.get("rollback_verified"))
    if not str(normalized.get("agentos_decision") or "").strip():
        decision_path = normalized.get("agentos_decision_path")
        if decision_path:
            normalized["agentos_decision"] = load_agentos_decision(decision_path)
    return normalized


def _metric_exceeds_budget(metrics: dict[str, Any], *, value_key: str, budget_key: str) -> bool:
    value = metrics.get(value_key)
    budget = metrics.get(budget_key)
    if value is None or budget is None:
        return False
    return float(value) > float(budget)


def _nonempty_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple, set)) and bool(value)
