#!/usr/bin/env python3
"""Build the canonical Canadian agronomic-performance development benchmark.

The historical internal suite remains immutable.  This compiler selects only
Canadian agronomic capability lanes, adds an objective calculation anchor, and
freezes a new contract with a production-prompt, four-arm causal design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_contract import read_json, sha256, write_benchmark  # noqa: E402


LEGACY_CONTRACT = ROOT / "configs/open_agronomy_internal_v2.json"
OUTPUT_CONTRACT = ROOT / "configs/open_agronomy_canadian_performance_v1.json"
CALC_SOURCE = "data/eval/canadian_agronomic_calculations_v1.jsonl"
KEPT_LANES = {
    "canadian_decision_quality",
    "canadian_advisory_transfer",
    "field_history_lineage",
    "official_source_answer_boundary",
    "retrieval_lineage",
}


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def build_contract() -> dict[str, Any]:
    legacy = read_json(LEGACY_CONTRACT)
    sources = [dict(source) for source in legacy["sources"] if source["lane"] in KEPT_LANES]
    sources.append(
        {
            "path": CALC_SOURCE,
            "sha256": sha256(ROOT / CALC_SOURCE),
            "rows": _line_count(ROOT / CALC_SOURCE),
            "lane": "objective_agronomic_calculation",
            "metric_role": "objective_agronomic_calculation_accuracy",
            "origin_class": "project_owned",
            "primary": False,
            "claim_eligible": False,
            "review_policy": {
                "automated_judge_role": "not_used",
                "deterministic_proxy_role": "objective_numeric_tolerance",
                "independent_agronomist_review_required": False,
            },
        }
    )
    return {
        "schema_version": "open_agronomy_agent.benchmark_contract.v1",
        "benchmark_id": "open_agronomy_canadian_performance_v1",
        "benchmark_namespace": "oacp1",
        "evaluation_partition": "internal",
        "status": "frozen_project_owned_canadian_development_benchmark",
        "created_at": "2026-08-09T00:00:00Z",
        "suite_path": "data/eval/open_agronomy_canadian_performance_v1.jsonl",
        "manifest_path": "data/eval/open_agronomy_canadian_performance_v1_manifest.json",
        "system_interface_contract": "configs/open_agronomy_canadian_performance_interface_v1.json",
        "answer_profile": "production",
        "rubric": "mixed_capability",
        "rag_config": "configs/rag_final_mvp.yaml",
        "max_tokens": 480,
        "default_modes": ["raw_model", "baseline", "kernel_field_context", "agronomic_rag"],
        "primary_comparison": "four_arm_canadian_agent_contribution_analysis",
        "claim_eligible": False,
        "deduplication_policy": "keep_first_source_order",
        "sources": sources,
        "evaluation_policy": {
            "automated_judge_role": "triage_only_until_calibrated_against_independent_agronomists",
            "deterministic_proxy_role": "regression_only_never_answer_quality",
            "objective_calculation_role": "separate_exact_capability_anchor",
            "report_lanes_separately": True,
            "single_composite_score_allowed": False,
            "human_review_required_for_external_claim": True,
            "primary_answer_quality_lane": "canadian_decision_quality",
            "real_user_confirmation_set_required_for_external_claim": True,
            "service_orchestration_lane_required_before_product_claim": True,
        },
        "contamination_policy": legacy["contamination_policy"],
        "result_contract": {
            **legacy["result_contract"],
            "store_answers_before_scoring": True,
            "store_raw_model_kernel_only_field_context_and_full_system_arms": True,
            "store_raw_model_kernel_only_and_full_system_arms": False,
        },
    }


def main() -> int:
    contract = build_contract()
    OUTPUT_CONTRACT.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = write_benchmark(ROOT, OUTPUT_CONTRACT)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
