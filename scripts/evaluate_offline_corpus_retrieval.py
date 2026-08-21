#!/usr/bin/env python3
"""Evaluate the frozen successor retrieval suite without invoking a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.agent import load_agent_resources  # noqa: E402
from agronomy_agent.corpus_release import canonical_json, source_locator_status  # noqa: E402


DEFAULT_CONFIG = ROOT / "configs/rag.yaml"
DEFAULT_CASES = ROOT / "data/eval/offline_corpus_retrieval.jsonl"
DEFAULT_SUITE = ROOT / "data/manifests/offline_corpus_retrieval_suite.json"
DEFAULT_OUTPUT = ROOT / "data/manifests/offline_corpus_retrieval_evaluation.json"
K_VALUES = (1, 3, 7)
RESAMPLES = 50_000
SEED = 20260819


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _policy_tiers(root: Path, config_path: Path) -> dict[str, str]:
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    policy_path = root / str(config["retrieval"]["corpus_policy_manifest"])
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    return {str(item["path"]): str(item["evidence_tier"]) for item in policy.get("corpora") or []}


def _relative(root: Path, value: str) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def _case_result(case: dict[str, Any], docs: list[Any], tiers: dict[str, str], elapsed_ms: float) -> dict[str, Any]:
    expected = {str(value) for value in case.get("expected_source_ids") or []}
    forbidden = {str(value) for value in case.get("forbidden_evidence_tiers") or []}
    retrieved = []
    for rank, doc in enumerate(docs, start=1):
        locator_ok, locator_status = source_locator_status(doc.source_locator)
        path = _relative(ROOT, doc.corpus_path)
        retrieved.append(
            {
                "rank": rank,
                "doc_id": doc.doc_id,
                "source_id": doc.source_id,
                "evidence_tier": tiers.get(path, "unknown"),
                "retrieval_policy": doc.retrieval_policy,
                "source_locator_complete": locator_ok,
                "source_locator_status": locator_status,
                "locator_precision": (doc.source_locator or {}).get("precision"),
                "transfer_scope": doc.transfer_scope,
                "applicability_boundary": doc.applicability_boundary,
                "tags": list(doc.tags),
            }
        )
    source_ranks = [entry["rank"] for entry in retrieved if entry["source_id"] in expected]
    first_rank = min(source_ranks) if source_ranks else None
    expected_precision = case.get("expected_locator_precision")
    precision_ok = expected_precision is None or any(entry["locator_precision"] == expected_precision for entry in retrieved if entry["source_id"] in expected)
    forbidden_hit = any(entry["evidence_tier"] in forbidden for entry in retrieved)
    boundary_ok = True
    if case.get("expect_no_us_analogue_context"):
        boundary_ok = not any(entry["evidence_tier"] == "US_government_analogue_reference" for entry in retrieved)
    if case.get("expect_no_admitted_community_context"):
        boundary_ok = not any(entry["evidence_tier"] == "community_experience" for entry in retrieved)
    if case.get("expected_mlra"):
        expected_mlra = str(case["expected_mlra"]).casefold()
        boundary_ok = boundary_ok and any(
            expected_mlra in str(entry["doc_id"]).casefold()
            or expected_mlra in {str(tag).casefold() for tag in entry.get("tags") or []}
            for entry in retrieved
        )
    if case.get("required_transfer_scope"):
        boundary_ok = boundary_ok and any(entry["transfer_scope"] == case["required_transfer_scope"] for entry in retrieved if entry["source_id"] in expected)
    if case.get("required_applicability_boundary_fragment"):
        fragment = str(case["required_applicability_boundary_fragment"]).casefold()
        boundary_ok = boundary_ok and any(fragment in str(entry["applicability_boundary"]).casefold() for entry in retrieved if entry["source_id"] in expected)
    return {
        "case_id": case["case_id"],
        "partition": case["partition"],
        "expected_source_ids": sorted(expected),
        "retrieved": retrieved,
        "first_expected_source_rank": first_rank,
        "recall_at": {str(k): bool(first_rank is not None and first_rank <= k) for k in K_VALUES},
        "ndcg_at_7": 0.0 if first_rank is None or first_rank > 7 else 1.0 / math.log2(first_rank + 1),
        "source_locator_valid": all(entry["source_locator_complete"] for entry in retrieved) and precision_ok,
        "authority_compliant": not forbidden_hit and boundary_ok,
        "latency_ms": round(elapsed_ms, 3),
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _interval(values: list[float], *, seed_offset: int) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0}
    rng = random.Random(SEED + seed_offset)
    means = sorted(_mean([values[rng.randrange(len(values))] for _ in values]) for _ in range(RESAMPLES))
    return {"mean": _mean(values), "low": means[int(0.025 * (RESAMPLES - 1))], "high": means[int(0.975 * (RESAMPLES - 1))]}


def evaluate(*, config_path: Path, case_path: Path, suite_path: Path) -> dict[str, Any]:
    config_path = config_path.resolve()
    case_path = case_path.resolve()
    suite_path = suite_path.resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = [case for case in _read_cases(case_path) if case.get("case_status") == "active"]
    resources = load_agent_resources(config_path)
    tiers = _policy_tiers(ROOT, config_path)
    results = []
    for case in cases:
        started = time.perf_counter()
        question = str(case["question"])
        # This evaluates retrieval, not the downstream evidence packer.  The
        # packer's policy decisions have separate answerability tests and must
        # not erase a source-recall failure or inflate a lexical baseline.
        docs = list(resources.retriever.search(question, top_k=7))
        for release in resources.on_demand_releases:
            docs.extend(release.search(question, top_k=7, retrieval_policies=("context_only",)))
        docs.sort(key=lambda doc: (-float(doc.score), str(doc.doc_id)))
        unique = []
        seen = set()
        for doc in docs:
            if doc.doc_id not in seen:
                unique.append(doc)
                seen.add(doc.doc_id)
        results.append(_case_result(case, unique[:7], tiers, (time.perf_counter() - started) * 1000))
    summary: dict[str, Any] = {}
    for metric, getter in {
        "recall_at_1": lambda row: float(row["recall_at"]["1"]),
        "recall_at_3": lambda row: float(row["recall_at"]["3"]),
        "recall_at_7": lambda row: float(row["recall_at"]["7"]),
        "ndcg_at_7": lambda row: float(row["ndcg_at_7"]),
        "source_locator_validity_rate": lambda row: float(row["source_locator_valid"]),
        "jurisdiction_authority_compliance_rate": lambda row: float(row["authority_compliant"]),
    }.items():
        summary[metric] = _interval([getter(row) for row in results], seed_offset=len(summary))
    summary["latency_ms"] = {
        "median": statistics.median(row["latency_ms"] for row in results),
        "p95": sorted(row["latency_ms"] for row in results)[max(0, math.ceil(len(results) * 0.95) - 1)],
    }
    by_partition: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_partition.setdefault(str(row["partition"]), []).append(row)
    return {
        "schema_version": "open_agronomy_agent.offline_corpus_retrieval_evaluation.v1",
        "suite_id": suite["suite_id"],
        "suite_sha256": suite["suite_sha256"],
        "case_file": case_path.relative_to(ROOT).as_posix(),
        "case_file_sha256": _sha256(case_path),
        "config_path": config_path.relative_to(ROOT).as_posix(),
        "config_sha256": _sha256(config_path),
        "retriever": "exact_token_bm25_lazy_shards",
        "status": "baseline_complete",
        "case_count": len(results),
        "summary": summary,
        "partitions": {
            partition: {
                "cases": len(rows),
                "recall_at_7": _mean([float(row["recall_at"]["7"]) for row in rows]),
                "authority_compliance": _mean([float(row["authority_compliant"]) for row in rows]),
            }
            for partition, rows in sorted(by_partition.items())
        },
        "results": results,
        "interpretation": "Fixed-suite retrieval baseline only; intervals are case-resampling sensitivity intervals, not population confidence intervals.",
        "promotion_gate": "No hybrid, dense, or reranking profile is active from this baseline alone.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = evaluate(config_path=args.config, case_path=args.cases, suite_path=args.suite)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": result["status"], "summary": result["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
