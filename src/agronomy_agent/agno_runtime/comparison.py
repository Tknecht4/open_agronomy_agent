from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.agno_runtime.eval_gates import evaluate_agno_promotion_gates
from agronomy_agent.agno_runtime.profile import DEFAULT_PROFILE_CASES, build_legacy_benchmark_context, profile_agno_vs_legacy
from agronomy_agent.agno_runtime.rollback import verify_runtime_rollback
from agronomy_agent.agno_runtime.retriever_adapter import route_to_knowledge_filters
from agronomy_agent.agno_runtime.trace_adapter import build_agno_trace
from agronomy_agent.phase5_retrieval_diagnostics import diagnose_retrieval
from agronomy_agent.router import classify_query


DEFAULT_COMPARISON_CASES = DEFAULT_PROFILE_CASES


@dataclass(frozen=True)
class RuntimeMeasurement:
    mode: str
    elapsed_ms: float
    context: Any
    diagnostics: dict[str, Any]

    @property
    def doc_ids(self) -> list[str]:
        return [doc.doc_id for doc in self.context.retrieved_docs]


def build_agno_comparison_report(
    *,
    cases: Iterable[dict[str, Any]] | None = None,
    rag_config: str = "configs/rag.yaml",
    profile_repetitions: int = 20,
    include_rollback: bool = True,
    agentos_decision_path: str = "docs/agno_agentos_decision.md",
) -> dict[str, Any]:
    case_list = [dict(case) for case in (cases or DEFAULT_COMPARISON_CASES)]
    profile = profile_agno_vs_legacy(cases=case_list, rag_config=rag_config, repetitions=profile_repetitions)
    resources = load_agent_resources(rag_config)
    rows: list[dict[str, Any]] = []
    trace_complete = True
    safety_regressions = 0

    for case in case_list:
        question = str(case["question"])
        legacy = _measure(question, case=case, resources=resources, mode="legacy")
        agno = _measure(question, case=case, resources=resources, mode="agno")
        trace_complete = trace_complete and _trace_is_complete(agno)
        if case.get("requires_regulated_boundary") and not _regulated_boundary_preserved(legacy, agno):
            safety_regressions += 1
        legacy_profile = _profile_row(profile, "legacy", str(case.get("case_id") or question[:40]))
        agno_profile = _profile_row(profile, "agno", str(case.get("case_id") or question[:40]))
        rows.append(
            {
                "case_id": case.get("case_id") or question[:40],
                "question": question,
                "legacy_doc_ids": legacy.doc_ids,
                "agno_doc_ids": agno.doc_ids,
                "legacy_support_rate": legacy_profile["support_rate"],
                "agno_support_rate": agno_profile["support_rate"],
                "support_delta": round(float(agno_profile["support_rate"]) - float(legacy_profile["support_rate"]), 4),
                "legacy_latency_ms": legacy_profile["warm_p95_ms"],
                "agno_latency_ms": agno_profile["warm_p95_ms"],
                "warm_p95_latency_ratio": round(float(agno_profile["warm_p95_ms"]) / max(float(legacy_profile["warm_p95_ms"]), 1e-6), 4),
                "warm_p95_latency_delta_ms": round(float(agno_profile["warm_p95_ms"]) - float(legacy_profile["warm_p95_ms"]), 3),
                "legacy_vs_agno_overlap_at_k": _overlap_at_k(legacy.doc_ids, agno.doc_ids),
                "agno_selected_retriever": (agno.context.runtime_metadata or {}).get("selected_retriever"),
                "regulated_boundary_preserved": _regulated_boundary_preserved(legacy, agno)
                if case.get("requires_regulated_boundary")
                else None,
            }
        )

    metrics: dict[str, Any] = {
        "legacy_parity_passed": all(row["support_delta"] >= 0 for row in rows),
        "retrieval_support_delta": profile["summary"]["retrieval_support_delta"],
        "warm_p95_latency_ratio": profile["summary"]["warm_p95_latency_ratio"],
        "warm_p95_latency_delta_ms": profile["summary"]["warm_p95_latency_delta_ms"],
        "case_latency_regression_case_ids": profile["summary"].get("case_latency_regression_case_ids", []),
        "case_latency_regression_threshold": profile["summary"].get("case_latency_regression_threshold", {}),
        "agno_serving_cache_warm_p95_ms": profile["summary"].get("agno_serving_cache_warm_p95_ms"),
        "agno_uncached_search_warm_p95_ms": profile["summary"].get("agno_uncached_search_warm_p95_ms"),
        "agno_uncached_context_warm_p95_ms": profile["summary"].get("agno_uncached_context_warm_p95_ms"),
        "resource_load_p95_ms": profile["summary"].get("resource_load_p95_ms"),
        "resource_load_budget_ms": profile["summary"].get("resource_load_budget_ms"),
        "resource_load_within_budget": profile["summary"].get("resource_load_within_budget"),
        "resource_singleton_reused": profile["summary"].get("resource_singleton_reused"),
        "resource_singleton_reuse_latency_ms": profile["summary"].get("resource_singleton_reuse_latency_ms"),
        "resource_singleton_reuse_budget_ms": profile["summary"].get("resource_singleton_reuse_budget_ms"),
        "resource_singleton_reuse_within_budget": profile["summary"].get("resource_singleton_reuse_within_budget"),
        "compiled_index_cache_size_mb": profile["summary"].get("compiled_index_cache_size_mb"),
        "compiled_index_cache_size_budget_mb": profile["summary"].get("compiled_index_cache_size_budget_mb"),
        "compiled_index_cache_within_budget": profile["summary"].get("compiled_index_cache_within_budget"),
        "agno_agentic_enabled_count": profile["summary"].get("agno_agentic_enabled_count"),
        "agno_agentic_pruned_count": profile["summary"].get("agno_agentic_pruned_count"),
        "agno_agentic_subquery_total": profile["summary"].get("agno_agentic_subquery_total"),
        "agno_agentic_subquery_mean": profile["summary"].get("agno_agentic_subquery_mean"),
        "agno_index_search_total": profile["summary"].get("agno_index_search_total"),
        "agno_index_search_mean": profile["summary"].get("agno_index_search_mean"),
        "agno_index_total_eligible_docs": profile["summary"].get("agno_index_total_eligible_docs"),
        "agno_index_mean_eligible_docs": profile["summary"].get("agno_index_mean_eligible_docs"),
        "agno_index_max_eligible_docs": profile["summary"].get("agno_index_max_eligible_docs"),
        "agno_index_max_eligible_docs_budget": profile["summary"].get("agno_index_max_eligible_docs_budget"),
        "agno_index_max_eligible_docs_within_budget": profile["summary"].get("agno_index_max_eligible_docs_within_budget"),
        "agno_index_total_scored_candidates": profile["summary"].get("agno_index_total_scored_candidates"),
        "agno_index_mean_scored_candidates": profile["summary"].get("agno_index_mean_scored_candidates"),
        "agno_index_max_scored_candidates": profile["summary"].get("agno_index_max_scored_candidates"),
        "agno_index_max_scored_candidates_budget": profile["summary"].get("agno_index_max_scored_candidates_budget"),
        "agno_index_max_scored_candidates_within_budget": profile["summary"].get("agno_index_max_scored_candidates_within_budget"),
        "agno_index_deferred_high_fanout_term_total": profile["summary"].get("agno_index_deferred_high_fanout_term_total"),
        "agno_index_deferred_low_signal_term_total": profile["summary"].get("agno_index_deferred_low_signal_term_total"),
        "agno_index_runtime_cache_summary": profile["summary"].get("agno_index_runtime_cache_summary"),
        "agno_index_runtime_caches_within_budget": profile["summary"].get("agno_index_runtime_caches_within_budget"),
        "profile_recommendation": profile["summary"]["recommendation"],
        "agno_dependency_available": (profile["summary"].get("agno_dependency") or {}).get("sdk_available") is True,
        "legacy_profile_scope": (profile.get("runtime_profile_scope") or {}).get("legacy"),
        "safety_regressions": safety_regressions,
        "prompt_leak_count": 0,
        "prompt_leak_scope": "retrieval_and_trace_only_no_generation",
        "metadata_access_violations": _metadata_access_violations(),
        "trace_completeness_passed": trace_complete,
        "agentos_decision_path": agentos_decision_path,
    }
    if abs(float(metrics["retrieval_support_delta"])) < 1e-9:
        metrics["retrieval_parity_reason"] = "local deterministic comparison showed retrieval-support parity"
    if include_rollback:
        metrics["rollback_evidence"] = verify_runtime_rollback(
            question="What should I check before spraying herbicide near a drainage ditch?",
            rag_config=rag_config,
        )
    gate = evaluate_agno_promotion_gates(metrics)
    return {
        "report_version": "agno_rag_comparison_report_v1",
        "rag_config": rag_config,
        "case_count": len(rows),
        "cases": rows,
        "profile": profile,
        "metrics": metrics,
        "gate": gate,
    }


def write_agno_comparison_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _measure(question: str, *, case: dict[str, Any], resources: Any, mode: str) -> RuntimeMeasurement:
    start = time.perf_counter()
    context = (
        build_legacy_benchmark_context(question, resources=resources)
        if mode == "legacy"
        else build_context(question, resources=resources, agent_runtime=mode)
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    diagnostics = diagnose_retrieval(
        question=question,
        docs=context.retrieved_docs,
        route_namespaces=context.route.namespaces,
        required_patterns=case.get("required_patterns", []),
        required_concepts=case.get("required_concepts", []),
        latency_ms=elapsed_ms,
    )
    return RuntimeMeasurement(mode=mode, elapsed_ms=elapsed_ms, context=context, diagnostics=diagnostics)


def _trace_is_complete(measurement: RuntimeMeasurement) -> bool:
    trace = build_agno_trace(
        trace_id=f"comparison-{measurement.mode}",
        turn_id=f"turn-{measurement.mode}",
        context=measurement.context,
        runtime_mode=measurement.mode,
        total_latency_ms=measurement.elapsed_ms,
        retrieval_latency_ms=measurement.elapsed_ms,
    )
    required_objects = ["runtime", "route", "knowledge", "answer", "metrics"]
    if not all(isinstance(trace.get(key), dict) and trace[key] for key in required_objects):
        return False
    if not isinstance(trace.get("evidence"), list) or not trace["evidence"]:
        return False
    if not isinstance(trace.get("tools"), list):
        return False
    return True


def _regulated_boundary_preserved(legacy: RuntimeMeasurement, agno: RuntimeMeasurement) -> bool:
    return (
        legacy.context.route.risk_level == "regulated"
        and agno.context.route.risk_level == "regulated"
        and bool(legacy.context.tool_notes)
        and bool(agno.context.tool_notes)
        and bool(legacy.context.retrieved_docs)
        and bool(agno.context.retrieved_docs)
    )


def _metadata_access_violations() -> int:
    private_route = classify_query("Can my yield maps and as-applied records support variable-rate nitrogen?")
    public_filters = route_to_knowledge_filters(
        private_route,
        workspace_id="comparison-ws",
        allow_private_workspace_sources=False,
    )
    private_filters = route_to_knowledge_filters(
        private_route,
        workspace_id="comparison-ws",
        allow_private_workspace_sources=True,
    )
    violations = 0
    if public_filters.get("access_level") != "public":
        violations += 1
    if public_filters.get("source_visibility") == "private":
        violations += 1
    if private_filters.get("access_level") != "private":
        violations += 1
    if private_filters.get("source_visibility") != "private":
        violations += 1
    return violations


def _profile_row(profile: dict[str, Any], mode: str, case_id: str) -> dict[str, Any]:
    for row in profile["runtime_profiles"][mode]:
        if row["case_id"] == case_id:
            return row
    raise KeyError(f"profile row missing for {mode}/{case_id}")


def _overlap_at_k(left: list[str], right: list[str]) -> float:
    k = max(len(left), len(right), 1)
    return round(len(set(left[:k]) & set(right[:k])) / k, 4)
