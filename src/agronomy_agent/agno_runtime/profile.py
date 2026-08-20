from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.advisor_plan import answer_coverage_checklist
from agronomy_agent.agent import (
    AgentContext,
    _search_agno,
    build_context,
    load_agent_resources,
    reset_phase5_query_caches,
)
from agronomy_agent.context_packer import default_context_packer
from agronomy_agent.agno_runtime.knowledge_factory import AGNO_VERSION, AgnoKnowledgeConfig, agno_sdk_available
from agronomy_agent.phase5_retrieval_diagnostics import diagnose_retrieval
from agronomy_agent.phase5_cache import CacheResult, Phase5LRUCache, stable_digest
from agronomy_agent.router import QueryRoute, classify_query
from agronomy_agent.tools.registry import run_tools


DEFAULT_PROFILE_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "regulated_spray_boundary",
        "question": "What should I check before spraying herbicide near a drainage ditch?",
        "required_concepts": ["label", "wind", "runoff"],
        "requires_regulated_boundary": True,
    },
    {
        "case_id": "nitrogen_sidedress_context",
        "question": "What should I verify before side-dressing nitrogen in corn after heavy rain?",
        "required_concepts": ["nitrogen", "rainfall", "soil moisture"],
    },
    {
        "case_id": "field_data_boundary",
        "question": "Can my yield maps and as-applied records support variable-rate nitrogen?",
        "required_concepts": ["yield maps", "field data", "calibration"],
    },
    {
        "case_id": "salinity_sodicity_context",
        "question": "How should I evaluate salinity and sodicity risk in an irrigated field?",
        "required_concepts": ["salinity", "SAR", "drainage"],
    },
    {
        "case_id": "soil_health_context",
        "question": "How should I interpret soil health test results for organic matter, aggregate stability, and infiltration?",
        "required_concepts": ["soil health", "organic matter", "aggregate"],
    },
    {
        "case_id": "regional_environment_context",
        "question": "What regional soil and climate context should I consider for a dryland field in MLRA 63B with erosion risk?",
        "required_concepts": ["MLRA", "climate", "erosion"],
    },
    {
        "case_id": "cca_exam_review",
        "question": "What should a CCA exam review checklist cover for nutrient management and soil fertility decisions?",
        "required_concepts": ["CCA", "nutrient management", "soil fertility"],
    },
)
RESOURCE_LOAD_BUDGET_MS = 5000.0
RESOURCE_SINGLETON_REUSE_BUDGET_MS = 50.0
COMPILED_INDEX_CACHE_BUDGET_MB = 160.0
AGNO_INDEX_MAX_ELIGIBLE_DOCS_BUDGET = 2048
AGNO_INDEX_MAX_SCORED_CANDIDATES_BUDGET = 128
CASE_LATENCY_REGRESSION_RATIO = 1.25
CASE_LATENCY_REGRESSION_DELTA_MS = 5.0


def build_legacy_benchmark_context(question: str, *, resources: Any) -> AgentContext:
    """Build a retired legacy-RAG context for explicit benchmark artifacts only."""

    return _LegacyBenchmarkHarness(resources).build_context(question)


@dataclass(frozen=True)
class RuntimeCaseProfile:
    case_id: str
    mode: str
    cold_latency_ms: float
    warm_median_ms: float
    warm_p95_ms: float
    uncached_search_warm_median_ms: float | None
    uncached_search_warm_p95_ms: float | None
    uncached_context_warm_median_ms: float | None
    uncached_context_warm_p95_ms: float | None
    serving_cache_warm_median_ms: float | None
    serving_cache_warm_p95_ms: float | None
    support_rate: float
    doc_ids: tuple[str, ...]
    cache_status: dict[str, str]
    selected_retriever: str | None
    agentic_search_enabled: bool | None
    agentic_pruned_after_primary: bool | None
    agentic_subquery_count: int | None
    index_search_count: int | None
    index_scoring_strategies: tuple[str, ...]
    index_total_eligible_docs: int | None
    index_max_eligible_docs: int | None
    index_total_scored_candidates: int | None
    index_max_scored_candidates: int | None
    index_deferred_low_signal_term_count: int | None
    index_deferred_high_fanout_term_count: int | None
    index_runtime_cache_stats: dict[str, Any] | None

    def as_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "mode": self.mode,
            "runtime_scope": (
                "benchmark_only_retired_serving_path_removed"
                if self.mode == "legacy"
                else "primary_serving_runtime"
            ),
            "cold_latency_ms": self.cold_latency_ms,
            "warm_median_ms": self.warm_median_ms,
            "warm_p95_ms": self.warm_p95_ms,
            "uncached_search_warm_median_ms": self.uncached_search_warm_median_ms,
            "uncached_search_warm_p95_ms": self.uncached_search_warm_p95_ms,
            "uncached_context_warm_median_ms": self.uncached_context_warm_median_ms,
            "uncached_context_warm_p95_ms": self.uncached_context_warm_p95_ms,
            "serving_cache_warm_median_ms": self.serving_cache_warm_median_ms,
            "serving_cache_warm_p95_ms": self.serving_cache_warm_p95_ms,
            "support_rate": self.support_rate,
            "doc_ids": list(self.doc_ids),
            "cache_status": self.cache_status,
            "selected_retriever": self.selected_retriever,
            "agentic_search_enabled": self.agentic_search_enabled,
            "agentic_pruned_after_primary": self.agentic_pruned_after_primary,
            "agentic_subquery_count": self.agentic_subquery_count,
            "index_search_count": self.index_search_count,
            "index_scoring_strategies": list(self.index_scoring_strategies),
            "index_total_eligible_docs": self.index_total_eligible_docs,
            "index_max_eligible_docs": self.index_max_eligible_docs,
            "index_total_scored_candidates": self.index_total_scored_candidates,
            "index_max_scored_candidates": self.index_max_scored_candidates,
            "index_deferred_low_signal_term_count": self.index_deferred_low_signal_term_count,
            "index_deferred_high_fanout_term_count": self.index_deferred_high_fanout_term_count,
            "index_runtime_cache_stats": self.index_runtime_cache_stats,
        }


def profile_agno_vs_legacy(
    *,
    cases: Iterable[dict[str, Any]] | None = None,
    rag_config: str | Path = "configs/rag.yaml",
    repetitions: int = 20,
    max_latency_ratio_for_support_gain: float = 1.25,
    max_latency_delta_ms_for_support_gain: float = 5.0,
    parity_latency_win_ratio: float = 1.0,
    max_latency_delta_ms_for_parity: float = 1.0,
    min_support_gain: float = 0.05,
) -> dict[str, Any]:
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    case_list = [dict(case) for case in (cases or DEFAULT_PROFILE_CASES)]
    if not case_list:
        raise ValueError("profile requires at least one case")
    resource_load_start = time.perf_counter()
    resources = load_agent_resources(rag_config)
    resource_load_latency_ms = round(_elapsed_ms(resource_load_start), 3)
    resource_reuse_start = time.perf_counter()
    reused_resources = load_agent_resources(rag_config)
    resource_reuse_latency_ms = round(_elapsed_ms(resource_reuse_start), 3)
    resource_profile = _resource_profile(resources, resource_load_latency_ms)
    agno_config = AgnoKnowledgeConfig.from_config(resources.rag_config)
    profiles = {
        mode: _profile_mode(mode, cases=case_list, resources=resources, repetitions=repetitions)
        for mode in ("legacy", "agno")
    }
    legacy_rows = profiles["legacy"]
    agno_rows = profiles["agno"]
    sdk_available = agno_sdk_available()
    sdk_version = None if AGNO_VERSION == "not_installed" else AGNO_VERSION
    legacy_support = _mean(row.support_rate for row in legacy_rows)
    agno_support = _mean(row.support_rate for row in agno_rows)
    support_delta = round(agno_support - legacy_support, 4)
    legacy_warm_p95 = _p95([row.warm_p95_ms for row in legacy_rows])
    agno_warm_p95 = _p95([row.warm_p95_ms for row in agno_rows])
    agno_serving_cache_warm_p95 = _p95(
        [
            row.serving_cache_warm_p95_ms
            for row in agno_rows
            if row.serving_cache_warm_p95_ms is not None
        ]
    )
    agno_uncached_search_warm_p95 = _p95(
        [
            row.uncached_search_warm_p95_ms
            for row in agno_rows
            if row.uncached_search_warm_p95_ms is not None
        ]
    )
    agno_uncached_context_warm_p95 = _p95(
        [
            row.uncached_context_warm_p95_ms
            for row in agno_rows
            if row.uncached_context_warm_p95_ms is not None
        ]
    )
    agentic_enabled_rows = [row for row in agno_rows if row.agentic_search_enabled]
    agentic_pruned_rows = [row for row in agno_rows if row.agentic_pruned_after_primary]
    agentic_subquery_counts = [
        row.agentic_subquery_count
        for row in agno_rows
        if row.agentic_subquery_count is not None
    ]
    agentic_subquery_total = sum(agentic_subquery_counts)
    agno_index_search_counts = [
        row.index_search_count for row in agno_rows if row.index_search_count is not None
    ]
    agno_index_scored_candidates = [
        row.index_total_scored_candidates
        for row in agno_rows
        if row.index_total_scored_candidates is not None
    ]
    agno_index_eligible_docs = [
        row.index_total_eligible_docs
        for row in agno_rows
        if row.index_total_eligible_docs is not None
    ]
    agno_index_max_eligible_docs = max(
        (row.index_max_eligible_docs for row in agno_rows if row.index_max_eligible_docs is not None),
        default=0,
    )
    agno_index_max_scored_candidates = max(
        (row.index_max_scored_candidates for row in agno_rows if row.index_max_scored_candidates is not None),
        default=0,
    )
    agno_index_deferred_high_fanout_terms = [
        row.index_deferred_high_fanout_term_count
        for row in agno_rows
        if row.index_deferred_high_fanout_term_count is not None
    ]
    agno_index_deferred_low_signal_terms = [
        row.index_deferred_low_signal_term_count
        for row in agno_rows
        if row.index_deferred_low_signal_term_count is not None
    ]
    agno_index_runtime_cache_summary = _runtime_cache_summary(
        row.index_runtime_cache_stats
        for row in agno_rows
        if row.index_runtime_cache_stats is not None
    )
    latency_ratio = round(agno_warm_p95 / max(legacy_warm_p95, 1e-6), 4)
    latency_delta_ms = round(agno_warm_p95 - legacy_warm_p95, 3)
    legacy_cold_p95 = _p95([row.cold_latency_ms for row in legacy_rows])
    agno_cold_p95 = _p95([row.cold_latency_ms for row in agno_rows])
    cold_latency_ratio = round(agno_cold_p95 / max(legacy_cold_p95, 1e-6), 4)
    cold_latency_delta_ms = round(agno_cold_p95 - legacy_cold_p95, 3)
    case_deltas = _case_deltas(legacy_rows, agno_rows)
    case_latency_regression_case_ids = [
        row["case_id"]
        for row in case_deltas
        if row["warm_p95_latency_ratio"] > CASE_LATENCY_REGRESSION_RATIO
        and row["warm_p95_latency_delta_ms"] > CASE_LATENCY_REGRESSION_DELTA_MS
    ]
    performance_winner = (
        (
            support_delta >= min_support_gain
            and (
                latency_ratio <= max_latency_ratio_for_support_gain
                or latency_delta_ms <= max_latency_delta_ms_for_support_gain
            )
        )
        or (
            support_delta >= 0
            and (
                latency_ratio <= parity_latency_win_ratio
                or latency_delta_ms <= max_latency_delta_ms_for_parity
            )
        )
    )
    clear_winner = sdk_available and performance_winner
    recommendation = (
        "promote_agno_replace_legacy"
        if clear_winner
        else "install_agno_dependency_before_promotion"
        if performance_winner and not sdk_available
        else "keep_legacy_primary_and_profile_agno"
    )
    return {
        "report_version": "agno_vs_legacy_profile_v1",
        "rag_config": str(rag_config),
        "case_count": len(case_list),
        "repetitions": repetitions,
        "runtime_profile_scope": {
            "legacy": "benchmark_only_retired_serving_path_removed",
            "agno": "primary_serving_runtime",
        },
        "runtime_profiles": {
            mode: [row.as_record() for row in rows]
            for mode, rows in profiles.items()
        },
        "summary": {
            "legacy_mean_support": round(legacy_support, 4),
            "agno_mean_support": round(agno_support, 4),
            "retrieval_support_delta": support_delta,
            "legacy_warm_p95_ms": legacy_warm_p95,
            "agno_warm_p95_ms": agno_warm_p95,
            "warm_p95_latency_ratio": latency_ratio,
            "warm_p95_latency_delta_ms": latency_delta_ms,
            "agno_serving_cache_warm_p95_ms": agno_serving_cache_warm_p95,
            "agno_uncached_search_warm_p95_ms": agno_uncached_search_warm_p95,
            "agno_uncached_context_warm_p95_ms": agno_uncached_context_warm_p95,
            "legacy_cold_p95_ms": legacy_cold_p95,
            "agno_cold_p95_ms": agno_cold_p95,
            "cold_p95_latency_ratio": cold_latency_ratio,
            "cold_p95_latency_delta_ms": cold_latency_delta_ms,
            "agno_cold_speedup_vs_legacy": round(legacy_cold_p95 / max(agno_cold_p95, 1e-6), 4),
            "agno_serving_cache_speedup_vs_fair_warm": round(
                agno_warm_p95 / max(agno_serving_cache_warm_p95, 1e-6),
                4,
            ),
            "agno_search_cache_speedup_vs_raw_warm": round(
                agno_uncached_search_warm_p95 / max(agno_warm_p95, 1e-6),
                4,
            ),
            "agno_context_cache_speedup_vs_uncached_context_warm": round(
                agno_uncached_context_warm_p95 / max(agno_serving_cache_warm_p95, 1e-6),
                4,
            ),
            "resource_load_latency_ms": resource_load_latency_ms,
            "resource_load_p95_ms": resource_profile["resource_load_p95_ms"],
            "resource_load_budget_ms": resource_profile["resource_load_budget_ms"],
            "resource_load_within_budget": resource_profile["resource_load_within_budget"],
            "resource_singleton_reused": reused_resources is resources,
            "resource_singleton_reuse_latency_ms": resource_reuse_latency_ms,
            "resource_singleton_reuse_budget_ms": RESOURCE_SINGLETON_REUSE_BUDGET_MS,
            "resource_singleton_reuse_within_budget": (
                reused_resources is resources
                and resource_reuse_latency_ms <= RESOURCE_SINGLETON_REUSE_BUDGET_MS
            ),
            "compiled_index_cache_status": getattr(resources, "index_cache_status", "unknown"),
            "compiled_index_cache_path": getattr(resources, "index_cache_path", None),
            "compiled_index_cache_size_bytes": resource_profile["compiled_index_cache_size_bytes"],
            "compiled_index_cache_size_mb": resource_profile["compiled_index_cache_size_mb"],
            "compiled_index_cache_size_budget_mb": resource_profile["compiled_index_cache_size_budget_mb"],
            "compiled_index_cache_within_budget": resource_profile["compiled_index_cache_within_budget"],
            "compiled_index_doc_count": resource_profile["compiled_index_doc_count"],
            "compiled_index_inverted_token_count": resource_profile["compiled_index_inverted_token_count"],
            "case_deltas": case_deltas,
            "case_latency_regression_case_ids": case_latency_regression_case_ids,
            "case_latency_regression_threshold": {
                "warm_p95_latency_ratio": CASE_LATENCY_REGRESSION_RATIO,
                "warm_p95_latency_delta_ms": CASE_LATENCY_REGRESSION_DELTA_MS,
            },
            "support_gain_case_ids": [
                row["case_id"] for row in case_deltas if row["support_delta"] > 0
            ],
            "support_regression_case_ids": [
                row["case_id"] for row in case_deltas if row["support_delta"] < 0
            ],
            "agno_retrieval_tuning": {
                "top_k": agno_config.top_k,
                "final_context_k": agno_config.final_context_k,
                "enable_agentic_search": agno_config.enable_agentic_search,
                "agentic_policy": "adaptive",
                "max_agentic_subqueries": agno_config.max_agentic_subqueries,
                "agentic_candidate_multiplier": agno_config.agentic_candidate_multiplier,
                "min_agentic_candidates": agno_config.min_agentic_candidates,
                "reranker": agno_config.reranker,
                "search_type": agno_config.search_type,
            },
            "agno_agentic_enabled_case_ids": [
                row.case_id for row in agentic_enabled_rows
            ],
            "agno_agentic_pruned_case_ids": [
                row.case_id for row in agentic_pruned_rows
            ],
            "agno_agentic_skipped_case_ids": [
                row.case_id for row in agno_rows if row.agentic_search_enabled is False
            ],
            "agno_agentic_enabled_count": len(agentic_enabled_rows),
            "agno_agentic_pruned_count": len(agentic_pruned_rows),
            "agno_agentic_subquery_total": agentic_subquery_total,
            "agno_agentic_subquery_mean": round(
                agentic_subquery_total / max(1, len(agentic_subquery_counts)),
                4,
            ),
            "agno_index_search_total": sum(agno_index_search_counts),
            "agno_index_search_mean": round(
                sum(agno_index_search_counts) / max(1, len(agno_index_search_counts)),
                4,
            ),
            "agno_index_total_eligible_docs": sum(agno_index_eligible_docs),
            "agno_index_mean_eligible_docs": round(
                sum(agno_index_eligible_docs) / max(1, sum(agno_index_search_counts)),
                4,
            ),
            "agno_index_max_eligible_docs": agno_index_max_eligible_docs,
            "agno_index_max_eligible_docs_budget": AGNO_INDEX_MAX_ELIGIBLE_DOCS_BUDGET,
            "agno_index_max_eligible_docs_within_budget": agno_index_max_eligible_docs <= AGNO_INDEX_MAX_ELIGIBLE_DOCS_BUDGET,
            "agno_index_total_scored_candidates": sum(agno_index_scored_candidates),
            "agno_index_mean_scored_candidates": round(
                sum(agno_index_scored_candidates) / max(1, sum(agno_index_search_counts)),
                4,
            ),
            "agno_index_max_scored_candidates": agno_index_max_scored_candidates,
            "agno_index_max_scored_candidates_budget": AGNO_INDEX_MAX_SCORED_CANDIDATES_BUDGET,
            "agno_index_max_scored_candidates_within_budget": agno_index_max_scored_candidates <= AGNO_INDEX_MAX_SCORED_CANDIDATES_BUDGET,
            "agno_index_deferred_high_fanout_term_total": sum(agno_index_deferred_high_fanout_terms),
            "agno_index_deferred_low_signal_term_total": sum(agno_index_deferred_low_signal_terms),
            "agno_index_runtime_cache_summary": agno_index_runtime_cache_summary,
            "agno_index_runtime_caches_within_budget": _runtime_caches_within_budget(agno_index_runtime_cache_summary),
            "agno_dependency": {
                "sdk_available": sdk_available,
                "sdk_version": sdk_version,
            },
            "agno_dependency_required_for_promotion": True,
            "agno_performance_winner": performance_winner,
            "agno_clear_winner": clear_winner,
            "recommendation": recommendation,
            "decision_rule": {
                "min_support_gain": min_support_gain,
                "max_latency_ratio_for_support_gain": max_latency_ratio_for_support_gain,
                "max_latency_delta_ms_for_support_gain": max_latency_delta_ms_for_support_gain,
                "parity_latency_win_ratio": parity_latency_win_ratio,
                "max_latency_delta_ms_for_parity": max_latency_delta_ms_for_parity,
            },
        },
    }


def _profile_mode(
    mode: str,
    *,
    cases: list[dict[str, Any]],
    resources: Any,
    repetitions: int,
) -> list[RuntimeCaseProfile]:
    reset_phase5_query_caches()
    legacy_harness = _LegacyBenchmarkHarness(resources) if mode == "legacy" else None
    rows: list[RuntimeCaseProfile] = []
    for case in cases:
        question = str(case["question"])
        cold_start = time.perf_counter()
        cold_context = (
            legacy_harness.build_context(question)
            if legacy_harness is not None
            else build_context(question, resources=resources, agent_runtime=mode)
        )
        cold_latency_ms = _elapsed_ms(cold_start)
        warm_latencies: list[float] = []
        uncached_search_latencies: list[float] = []
        uncached_context_latencies: list[float] = []
        serving_cache_latencies: list[float] = []
        context = cold_context
        for _ in range(repetitions):
            warm_start = time.perf_counter()
            context = (
                legacy_harness.build_context(question)
                if legacy_harness is not None
                else build_context(
                    question,
                    resources=resources,
                    agent_runtime=mode,
                    use_context_cache=False,
                )
            )
            warm_latencies.append(_elapsed_ms(warm_start))
            if mode == "agno":
                direct_search_start = time.perf_counter()
                _search_agno(
                    question=question,
                    resources=resources,
                    retrieval_cfg=resources.rag_config.get("retrieval", {}),
                    route=context.route,
                    profiler=None,
                    use_search_cache=False,
                )
                uncached_search_latencies.append(_elapsed_ms(direct_search_start))
                raw_search_start = time.perf_counter()
                build_context(
                    question,
                    resources=resources,
                    agent_runtime=mode,
                    use_context_cache=False,
                    use_search_cache=False,
                )
                uncached_context_latencies.append(_elapsed_ms(raw_search_start))
                serving_start = time.perf_counter()
                build_context(question, resources=resources, agent_runtime=mode)
                serving_cache_latencies.append(_elapsed_ms(serving_start))
        diagnostics = diagnose_retrieval(
            question=question,
            docs=context.retrieved_docs,
            route_namespaces=context.route.namespaces,
            required_patterns=case.get("required_patterns", []),
            required_concepts=case.get("required_concepts", []),
            latency_ms=statistics.median(warm_latencies),
        )
        agno_knowledge = (context.runtime_metadata or {}).get("agno_knowledge") or {}
        uncached_search_median = (
            round(statistics.median(uncached_search_latencies), 3)
            if uncached_search_latencies
            else None
        )
        uncached_search_p95 = _p95(uncached_search_latencies) if uncached_search_latencies else None
        uncached_context_median = (
            round(statistics.median(uncached_context_latencies), 3)
            if uncached_context_latencies
            else None
        )
        uncached_context_p95 = _p95(uncached_context_latencies) if uncached_context_latencies else None
        if uncached_search_median is not None and uncached_context_median is not None:
            uncached_context_median = max(uncached_context_median, uncached_search_median)
        if uncached_search_p95 is not None and uncached_context_p95 is not None:
            uncached_context_p95 = max(uncached_context_p95, uncached_search_p95)
        rows.append(
            RuntimeCaseProfile(
                case_id=str(case.get("case_id") or question[:40]),
                mode=mode,
                cold_latency_ms=round(cold_latency_ms, 3),
                warm_median_ms=round(statistics.median(warm_latencies), 3),
                warm_p95_ms=_p95(warm_latencies),
                uncached_search_warm_median_ms=uncached_search_median,
                uncached_search_warm_p95_ms=uncached_search_p95,
                uncached_context_warm_median_ms=uncached_context_median,
                uncached_context_warm_p95_ms=uncached_context_p95,
                serving_cache_warm_median_ms=(
                    round(statistics.median(serving_cache_latencies), 3)
                    if serving_cache_latencies
                    else None
                ),
                serving_cache_warm_p95_ms=_p95(serving_cache_latencies) if serving_cache_latencies else None,
                support_rate=float(diagnostics["retrieval_required_support_rate"]),
                doc_ids=tuple(doc.doc_id for doc in context.retrieved_docs),
                cache_status=dict(context.cache_status or {}),
                selected_retriever=(context.runtime_metadata or {}).get("selected_retriever"),
                agentic_search_enabled=(
                    bool(agno_knowledge["agentic_search_enabled"])
                    if "agentic_search_enabled" in agno_knowledge
                    else None
                ),
                agentic_pruned_after_primary=(
                    bool(agno_knowledge["agentic_pruned_after_primary"])
                    if "agentic_pruned_after_primary" in agno_knowledge
                    else None
                ),
                agentic_subquery_count=(
                    int(agno_knowledge["agentic_subquery_count"])
                    if "agentic_subquery_count" in agno_knowledge
                    else None
                ),
                index_search_count=(
                    int(agno_knowledge["index_search_count"])
                    if "index_search_count" in agno_knowledge
                    else None
                ),
                index_scoring_strategies=tuple(
                    str(value)
                    for value in agno_knowledge.get("index_scoring_strategies", [])
                ),
                index_total_eligible_docs=(
                    int(agno_knowledge["index_total_eligible_docs"])
                    if "index_total_eligible_docs" in agno_knowledge
                    else None
                ),
                index_max_eligible_docs=(
                    int(agno_knowledge["index_max_eligible_docs"])
                    if "index_max_eligible_docs" in agno_knowledge
                    else None
                ),
                index_total_scored_candidates=(
                    int(agno_knowledge["index_total_scored_candidates"])
                    if "index_total_scored_candidates" in agno_knowledge
                    else None
                ),
                index_max_scored_candidates=(
                    int(agno_knowledge["index_max_scored_candidates"])
                    if "index_max_scored_candidates" in agno_knowledge
                    else None
                ),
                index_deferred_low_signal_term_count=(
                    int(agno_knowledge["index_deferred_low_signal_term_count"])
                    if "index_deferred_low_signal_term_count" in agno_knowledge
                    else None
                ),
                index_deferred_high_fanout_term_count=(
                    int(agno_knowledge["index_deferred_high_fanout_term_count"])
                    if "index_deferred_high_fanout_term_count" in agno_knowledge
                    else None
                ),
                index_runtime_cache_stats=(
                    dict(agno_knowledge["index_runtime_cache_stats"])
                    if isinstance(agno_knowledge.get("index_runtime_cache_stats"), dict)
                    else None
                ),
            )
        )
    return rows


def _resource_profile(resources: Any, resource_load_latency_ms: float) -> dict[str, Any]:
    cache_path_value = getattr(resources, "index_cache_path", None)
    cache_size_bytes = 0
    if cache_path_value:
        try:
            cache_size_bytes = Path(cache_path_value).stat().st_size
        except OSError:
            cache_size_bytes = 0
    cache_size_mb = round(cache_size_bytes / (1024 * 1024), 3)
    return {
        "resource_load_p95_ms": resource_load_latency_ms,
        "resource_load_budget_ms": RESOURCE_LOAD_BUDGET_MS,
        "resource_load_within_budget": resource_load_latency_ms <= RESOURCE_LOAD_BUDGET_MS,
        "compiled_index_cache_size_bytes": cache_size_bytes,
        "compiled_index_cache_size_mb": cache_size_mb,
        "compiled_index_cache_size_budget_mb": COMPILED_INDEX_CACHE_BUDGET_MB,
        "compiled_index_cache_within_budget": cache_size_mb <= COMPILED_INDEX_CACHE_BUDGET_MB,
        "compiled_index_doc_count": len(getattr(getattr(resources, "retriever", None), "docs", []) or []),
        "compiled_index_inverted_token_count": len(getattr(getattr(resources, "retriever", None), "inverted_index", {}) or {}),
    }


def _runtime_cache_summary(cache_stats_rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, int | bool]]:
    summary: dict[str, dict[str, int | bool]] = {}
    for row in cache_stats_rows:
        for name, stats in row.items():
            if not isinstance(stats, dict):
                continue
            entries = int(stats.get("entries") or 0)
            max_entries = int(stats.get("max_entries") or 0)
            current = summary.get(name)
            summary[name] = {
                "max_observed_entries": max(entries, int((current or {}).get("max_observed_entries") or 0)),
                "max_entries": max_entries or int((current or {}).get("max_entries") or 0),
                "within_budget": bool(stats.get("within_budget", True)) and bool((current or {}).get("within_budget", True)),
            }
    return summary


def _runtime_caches_within_budget(summary: dict[str, dict[str, int | bool]]) -> bool:
    return bool(summary) and all(bool(stats.get("within_budget")) for stats in summary.values())


class _LegacyBenchmarkHarness:
    """Contained copy of the retired serving retrieval path for profiling only."""

    def __init__(self, resources: Any) -> None:
        self.resources = resources
        self.route_cache: Phase5LRUCache[QueryRoute] = Phase5LRUCache(max_entries=512)
        self.retrieval_cache: Phase5LRUCache[list[Any]] = Phase5LRUCache(max_entries=256)
        self.kg_cache: Phase5LRUCache[list[Any]] = Phase5LRUCache(max_entries=256)

    def build_context(self, question: str) -> AgentContext:
        route_key = ("legacy_benchmark_route", self.resources.corpus_bundle_version, question.strip().lower())
        route_result = self.route_cache.get_or_compute(route_key, lambda: classify_query(question))
        route = route_result.value
        retrieval_cfg = self.resources.rag_config.get("retrieval", {})
        retrieval_key = (
            "legacy_benchmark_retrieval",
            self.resources.corpus_bundle_version,
            stable_digest(
                {
                    "question": question.strip().lower(),
                    "top_k": int(retrieval_cfg.get("top_k", 5)),
                    "min_score": float(retrieval_cfg.get("min_score", 0.0)),
                    "audience": route.audience,
                    "namespaces": route.namespaces,
                    "query_expansion": route.query_expansion,
                    "knowledge_bucket": route.knowledge_bucket,
                    "knowledge_domains": route.knowledge_domains,
                }
            ),
        )
        retrieval_result: CacheResult[list[Any]] = self.retrieval_cache.get_or_compute(
            retrieval_key,
            lambda: self.resources.retriever.search(
                question,
                top_k=int(retrieval_cfg.get("top_k", 5)),
                min_score=float(retrieval_cfg.get("min_score", 0.0)),
                allowed_roles=[route.audience],
                namespaces=route.namespaces,
                query_expansion=route.query_expansion,
                knowledge_bucket=route.knowledge_bucket,
                knowledge_domains=route.knowledge_domains,
            ),
        )
        kg_key = (
            "legacy_benchmark_kg",
            self.resources.corpus_bundle_version,
            stable_digest({"question": question.strip().lower(), "namespaces": route.namespaces, "query_expansion": route.query_expansion}),
        )
        kg_result: CacheResult[list[Any]] = self.kg_cache.get_or_compute(
            kg_key,
            lambda: self.resources.graph.search(question, limit=5, namespaces=route.namespaces, query_expansion=route.query_expansion),
        )
        context = AgentContext(
            retrieved_docs=list(retrieval_result.value),
            graph_hits=kg_result.value,
            tool_notes=run_tools(question, route.required_tools),
            route=route,
            coverage_checklist=answer_coverage_checklist(question, route),
            cache_status={
                "route": route_result.cache_status,
                "legacy_benchmark": retrieval_result.cache_status,
                "kg": kg_result.cache_status,
            },
            runtime_mode="legacy_benchmark",
            runtime_metadata={"agent_runtime": "legacy_benchmark", "selected_retriever": "legacy_benchmark"},
        )
        context.packed_context = default_context_packer().pack(question=question, context=context)
        return context


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / max(1, len(values))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 3)


def _case_deltas(legacy_rows: list[RuntimeCaseProfile], agno_rows: list[RuntimeCaseProfile]) -> list[dict[str, Any]]:
    legacy_by_case = {row.case_id: row for row in legacy_rows}
    deltas: list[dict[str, Any]] = []
    for agno in agno_rows:
        legacy = legacy_by_case.get(agno.case_id)
        if legacy is None:
            continue
        deltas.append(
            {
                "case_id": agno.case_id,
                "support_delta": round(agno.support_rate - legacy.support_rate, 4),
                "warm_p95_latency_ratio": round(agno.warm_p95_ms / max(legacy.warm_p95_ms, 1e-6), 4),
                "warm_p95_latency_delta_ms": round(agno.warm_p95_ms - legacy.warm_p95_ms, 3),
                "cold_latency_ratio": round(agno.cold_latency_ms / max(legacy.cold_latency_ms, 1e-6), 4),
                "cold_latency_delta_ms": round(agno.cold_latency_ms - legacy.cold_latency_ms, 3),
            }
        )
    return deltas
