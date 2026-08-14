from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.agent import build_context, load_agent_resources, phase5_cache_stats, reset_phase5_query_caches
from agronomy_agent.phase5_reports import percentile
from agronomy_agent.paths import repo_path
from agronomy_agent.server.trace_timer import TraceProfiler


DEFAULT_GATE_QUESTIONS = (
    "What should we check for phosphorus runoff risk near a ditch?",
    "How should I reason about sulfur deficiency in corn?",
    "What field data are required before a variable-rate nitrogen prescription?",
)
DEFAULT_RUNTIME_BUDGET_PATH = "plans/agronomy_agent_phase5_optimization_hardening_packet/phase5_runtime_budget_targets.csv"
STAGE_BUDGET_ALIASES = {
    "router_classify": ("agent.route.classify",),
    "lexical_retrieval": ("agent.rag.lexical_search",),
    "kg_lookup": ("agent.kg.search",),
    "deterministic_tools": ("agent.tools.run_guard_notes",),
    "context_packing": ("agent.context.pack",),
}


@dataclass(frozen=True)
class Phase5LatencyGateResult:
    passed: bool
    failures: tuple[str, ...]
    report: dict[str, Any]


def evaluate_ci_latency_gate(
    *,
    questions: Iterable[str] = DEFAULT_GATE_QUESTIONS,
    rag_config: str = "configs/rag_governed_runtime_v2.yaml",
    max_warm_p95_ms: float = 2000.0,
    runtime_budget_path: str | Path = DEFAULT_RUNTIME_BUDGET_PATH,
) -> Phase5LatencyGateResult:
    question_list = [question for question in questions if question.strip()]
    if not question_list:
        raise ValueError("phase5 latency gate requires at least one question")

    reset_phase5_query_caches()
    resources = load_agent_resources(rag_config)
    cold_rows = [_timed_context(question, resources=resources) for question in question_list]
    warm_rows = [_timed_context(question, resources=resources) for question in question_list]
    warm_latencies = [row["duration_ms"] for row in warm_rows]
    warm_cache_failures = [
        {"question": row["question"], "cache_status": row["cache_status"]}
        for row in warm_rows
        if not _required_context_caches_hit(row["cache_status"])
    ]
    warm_p95 = percentile(warm_latencies, 0.95) or 0.0
    stage_budget_report = evaluate_stage_budgets(
        [span for row in warm_rows for span in row["spans"]],
        runtime_budgets=load_runtime_budgets(runtime_budget_path),
    )

    failures: list[str] = []
    if warm_p95 > max_warm_p95_ms:
        failures.append("warm_context_p95_latency_regression")
    if warm_cache_failures:
        failures.append("warm_context_cache_miss")
    if stage_budget_report["failures"]:
        failures.append("stage_budget_regression")

    report = {
        "gate_version": "phase5_ci_latency_gate_v1",
        "rag_config": rag_config,
        "corpus_bundle_version": resources.corpus_bundle_version,
        "sample_count": len(question_list),
        "max_warm_p95_ms": max_warm_p95_ms,
        "cold_context_latency_ms": _latency_summary([row["duration_ms"] for row in cold_rows]),
        "warm_context_latency_ms": _latency_summary(warm_latencies),
        "warm_cache_failures": warm_cache_failures,
        "stage_budget_report": stage_budget_report,
        "cache_stats": phase5_cache_stats(),
        "failures": failures,
        "passed": not failures,
    }
    return Phase5LatencyGateResult(passed=not failures, failures=tuple(failures), report=report)


def load_runtime_budgets(path: str | Path = DEFAULT_RUNTIME_BUDGET_PATH) -> dict[str, dict[str, Any]]:
    resolved = repo_path(path)
    with resolved.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            str(row["stage"]): {
                "p50_target_ms": float(row["p50_target_ms"]),
                "p95_target_ms": float(row["p95_target_ms"]),
                "primary_optimization": row.get("primary_optimization", ""),
            }
            for row in rows
            if row.get("stage")
        }


def evaluate_stage_budgets(
    rows: list[dict[str, Any]],
    *,
    runtime_budgets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    by_stage: dict[str, list[float]] = {}
    for row in rows:
        stage = str(row.get("stage") or "")
        duration = row.get("duration_ms")
        if not stage or duration is None:
            continue
        by_stage.setdefault(stage, []).append(float(duration))
    stages: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for budget_stage, budget in sorted(runtime_budgets.items()):
        observed = []
        for observed_stage in (budget_stage, *STAGE_BUDGET_ALIASES.get(budget_stage, ())):
            observed.extend(by_stage.get(observed_stage, []))
        p50 = percentile(observed, 0.50)
        p95 = percentile(observed, 0.95)
        stage_report = {
            "observed_count": len(observed),
            "p50_ms": p50,
            "p95_ms": p95,
            "p50_target_ms": budget["p50_target_ms"],
            "p95_target_ms": budget["p95_target_ms"],
            "primary_optimization": budget.get("primary_optimization", ""),
        }
        exceeded = []
        if p50 is not None and p50 > budget["p50_target_ms"]:
            exceeded.append("p50")
        if p95 is not None and p95 > budget["p95_target_ms"]:
            exceeded.append("p95")
        stage_report["exceeded"] = exceeded
        stages[budget_stage] = stage_report
        if exceeded:
            failures.append({"stage": budget_stage, "exceeded": exceeded, "p50_ms": p50, "p95_ms": p95})
    return {
        "report_version": "phase5_stage_budget_report_v1",
        "budget_stage_count": len(runtime_budgets),
        "observed_stage_count": sum(1 for stage in stages.values() if stage["observed_count"]),
        "stages": stages,
        "failures": failures,
        "passed": not failures,
    }


def _timed_context(question: str, *, resources: Any) -> dict[str, Any]:
    start_ns = time.perf_counter_ns()
    profiler = TraceProfiler()
    context = build_context(question, resources=resources, profiler=profiler)
    duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
    return {
        "question": question,
        "duration_ms": round(duration_ms, 3),
        "cache_status": context.cache_status or {},
        "doc_count": len(context.retrieved_docs),
        "graph_hit_count": len(context.graph_hits),
        "tool_notes_count": len(context.tool_notes),
        "spans": profiler.span_records(),
    }


def _required_context_caches_hit(cache_status: dict[str, str]) -> bool:
    if "agno" in cache_status and "retrieval" not in cache_status:
        return all(cache_status.get(key) == "hit" for key in ("route", "agno", "kg"))
    return all(cache_status.get(key) == "hit" for key in ("route", "retrieval", "kg"))


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": round(max(values), 3) if values else None,
    }
