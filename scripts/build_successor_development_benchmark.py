#!/usr/bin/env python3
"""Build the exposed successor benchmark against the active offline corpus.

This compiler preserves the completed RC3 contract unchanged.  It appends only
source-grounded U.S. NRCS, table, and jurisdiction-boundary regression cases
to the existing project-authored Canadian development suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_contract import read_json, sha256, write_benchmark  # noqa: E402


BASE_CONTRACT = ROOT / "configs/open_agronomy_canadian_performance_v1_runtime_v2.json"
OUTPUT_CONTRACT = ROOT / "configs/open_agronomy_successor_development.json"
EXTENSION_SOURCE = "data/eval/offline_corpus_successor_benchmark_extension.jsonl"


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def build_contract() -> dict[str, Any]:
    base = read_json(BASE_CONTRACT)
    source_path = ROOT / EXTENSION_SOURCE
    sources = [dict(source) for source in base["sources"]]
    sources.append(
        {
            "path": EXTENSION_SOURCE,
            "sha256": sha256(source_path),
            "rows": _line_count(source_path),
            "lane": "successor_retrieval_lineage",
            "metric_role": "source_exact_jurisdiction_and_authority_regression",
            "origin_class": "project_owned",
            "primary": False,
            "claim_eligible": False,
            "review_policy": {
                "automated_judge_role": "not_used",
                "deterministic_proxy_role": "source_trace_and_boundary_regression_only",
                "independent_agronomist_review_required": False,
            },
        }
    )
    return {
        "schema_version": "open_agronomy_agent.benchmark_contract.v1",
        "benchmark_id": "open_agronomy_successor_development",
        "benchmark_namespace": "oasdev",
        "evaluation_partition": "internal",
        "status": "frozen_exposed_successor_corpus_development_regression",
        "created_at": "2026-08-20T00:00:00Z",
        "suite_path": "data/eval/open_agronomy_successor_development.jsonl",
        "manifest_path": "data/eval/open_agronomy_successor_development_manifest.json",
        "system_interface_contract": "configs/open_agronomy_successor_development_interface.json",
        "answer_profile": "production",
        "rubric": "mixed_capability",
        "rag_config": "configs/rag.yaml",
        "max_tokens": 480,
        "default_modes": ["raw_model", "baseline", "kernel_field_context", "agronomic_rag"],
        "primary_comparison": "four_arm_exposed_successor_corpus_development_regression",
        "claim_eligible": False,
        "deduplication_policy": "keep_first_source_order",
        "sources": sources,
        "evaluation_policy": {
            **base["evaluation_policy"],
            "claim_boundary": (
                "Development regression only. RC3 remains frozen historical evidence; "
                "this successor suite is exposed and project-authored, so it cannot estimate unbiased generalization."
            ),
            "successor_source_trace_role": (
                "Measure source-exact retrieval, U.S.-analogue boundary handling, and Canadian authority suppression; "
                "do not convert these diagnostics into answer-quality or agronomist-equivalence claims."
            ),
        },
        "contamination_policy": {
            **base["contamination_policy"],
            "suite_exposure_status": "exposed_project_authored_successor_development_regression",
            "future_unbiased_evaluation_requires_new_holdout": True,
        },
        "result_contract": {
            **base["result_contract"],
            "capture_exact_messages": True,
            "capture_context_packets": True,
            "store_source_trace": True,
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
