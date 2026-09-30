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
    positive = bool(expected)
    negative_contract = bool(forbidden or case.get("expect_no_us_analogue_context") or case.get("expect_no_admitted_community_context"))
    # A source repeated across chunks earns relevance once, not once per chunk.
    unique_source_ranks: dict[str, int] = {}
    for entry in retrieved:
        if entry["source_id"] in expected:
            unique_source_ranks.setdefault(entry["source_id"], entry["rank"])
    dcg = sum(1.0 / math.log2(rank + 1) for rank in unique_source_ranks.values() if rank <= 7)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(7, len(expected)) + 1))
    expected_precision = case.get("expected_locator_precision")
    precision_ok = expected_precision is None or any(entry["locator_precision"] == expected_precision for entry in retrieved if entry["source_id"] in expected)
    forbidden_hit = any(entry["evidence_tier"] in forbidden for entry in retrieved)
    boundary_ok = True
    if case.get("expect_no_us_analogue_context"):
        boundary_ok = not any(entry["evidence_tier"] == "US_government_analogue_reference" for entry in retrieved)
    if case.get("expect_no_admitted_community_context"):
        boundary_ok = boundary_ok and not any(entry["evidence_tier"] == "community_experience" for entry in retrieved)
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
        "case_status": case.get("case_status", "active"),
        "execution_status": "completed",
        "metric_population": "positive_source" if positive else "negative_control" if negative_contract else "unscored_no_contract",
        "expected_source_ids": sorted(expected),
        "retrieved": retrieved,
        "first_expected_source_rank": first_rank,
        "recall_at": {str(k): sum(rank <= k for rank in unique_source_ranks.values()) / len(expected) if positive else None for k in K_VALUES},
        "ndcg_at_7": dcg / ideal if positive else None,
        "negative_control_compliant": (not forbidden_hit and boundary_ok) if not positive and negative_contract else None,
        "source_locator_valid": all(entry["source_locator_complete"] for entry in retrieved) and precision_ok,
        "authority_compliant": not forbidden_hit and boundary_ok,
        "latency_ms": round(elapsed_ms, 3),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _interval(values: list[float], *, seed_offset: int) -> dict[str, float | int | None]:
    if not values:
        return {"mean": None, "low": None, "high": None, "denominator": 0}
    rng = random.Random(SEED + seed_offset)
    means = sorted(_mean([values[rng.randrange(len(values))] for _ in values]) for _ in range(RESAMPLES))
    return {"mean": _mean(values), "low": means[int(0.025 * (RESAMPLES - 1))], "high": means[int(0.975 * (RESAMPLES - 1))], "denominator": len(values)}


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for metric, field, key in (
        ("recall_at_1", "recall_at", "1"),
        ("recall_at_3", "recall_at", "3"),
        ("recall_at_7", "recall_at", "7"),
        ("ndcg_at_7", "ndcg_at_7", None),
        ("negative_control_compliance_rate", "negative_control_compliant", None),
        ("source_locator_validity_rate", "source_locator_valid", None),
        ("jurisdiction_authority_compliance_rate", "authority_compliant", None),
    ):
        values = []
        for row in results:
            value = (row.get(field) or {}).get(key) if key else row.get(field)
            if value is not None:
                values.append(float(value))
        summary[metric] = _interval(values, seed_offset=len(summary))
    latencies = sorted(row["latency_ms"] for row in results if row.get("latency_ms") is not None)
    summary["latency_ms"] = {
        "median": statistics.median(latencies) if latencies else None,
        "p95": latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)] if latencies else None,
        "denominator": len(latencies),
    }
    return summary


def evaluation_gate(report: dict[str, Any], threshold_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply caller-owned thresholds; no inferred universal performance floor."""
    failures = []
    if report["failed_case_count"]:
        failures.append("retrieval_execution_failed")
    if not report["executed_case_count"]:
        failures.append("no_cases_executed")
    if report.get("unscored_case_count", 0):
        failures.append("cases_without_scoring_contract")
    policy = threshold_policy or {}
    if set(policy) - {"minimum_rates", "require_no_blocked_cases"}:
        raise ValueError("unknown retrieval threshold policy field")
    if policy.get("require_no_blocked_cases") and report["blocked_case_count"]:
        failures.append("blocked_cases_present")
    rates = policy.get("minimum_rates", {})
    if not isinstance(rates, dict):
        raise ValueError("minimum_rates must be an object")
    for metric, threshold in rates.items():
        if metric not in report["summary"] or metric == "latency_ms":
            raise ValueError(f"unknown threshold metric: {metric}")
        if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not 0 <= threshold <= 1:
            raise ValueError(f"threshold must be a rate in [0, 1]: {metric}")
        observed = report["summary"][metric]["mean"]
        if observed is None or observed < threshold:
            failures.append(f"threshold_not_met:{metric}")
    return {"passed": not failures, "failures": failures, "threshold_policy": policy,
            "performance_thresholds_supplied": bool(rates), "claim_eligible": False}


def evaluate(*, config_path: Path, case_path: Path, suite_path: Path,
             threshold_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    from agronomy_agent.evals import build_rag_artifact_identity

    config_path = config_path.resolve()
    case_path = case_path.resolve()
    suite_path = suite_path.resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = _read_cases(case_path)
    if suite.get("case_file_sha256") != _sha256(case_path):
        raise ValueError("retrieval suite case-file hash mismatch")
    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate retrieval case IDs")
    resources = load_agent_resources(config_path)
    tiers = _policy_tiers(ROOT, config_path)
    results = []
    for case in cases:
        if case.get("case_status") != "active":
            results.append({"case_id": case["case_id"], "partition": case["partition"],
                            "case_status": case.get("case_status", "unknown"),
                            "execution_status": "blocked", "blocking_reason": case.get("blocking_reason"),
                            "metric_population": "not_executed"})
            continue
        started = time.perf_counter()
        try:
            question = str(case["question"])
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
        except Exception as exc:
            results.append({"case_id": case["case_id"], "partition": case["partition"],
                            "case_status": case["case_status"], "execution_status": "failed",
                            "metric_population": "not_executed", "error_type": type(exc).__name__,
                            "error": str(exc)})
    completed = [row for row in results if row["execution_status"] == "completed"]
    by_partition: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_partition.setdefault(str(row["partition"]), []).append(row)
    implementation = sorted((ROOT / "src/agronomy_agent").rglob("*.py")) + [Path(__file__).resolve()]
    digest = hashlib.sha256()
    for path in implementation:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    report = {
        "schema_version": "open_agronomy_agent.offline_corpus_retrieval_evaluation.v2",
        "suite_id": suite["suite_id"], "suite_sha256": suite["suite_sha256"],
        "suite_manifest_sha256": _sha256(suite_path),
        "case_file": _relative(ROOT, str(case_path)), "case_file_sha256": _sha256(case_path),
        "config_path": _relative(ROOT, str(config_path)), "config_sha256": _sha256(config_path),
        "implementation": {"sha256": digest.hexdigest(), "file_count": len(implementation),
                           "scope": ["src/agronomy_agent/**/*.py", "scripts/evaluate_offline_corpus_retrieval.py"]},
        "source_artifacts": build_rag_artifact_identity(resources),
        "retriever": "exact_token_bm25_lazy_shards", "status": "baseline_complete",
        "case_count": len(results), "executed_case_count": len(completed),
        "blocked_case_count": sum(row["execution_status"] == "blocked" for row in results),
        "failed_case_count": sum(row["execution_status"] == "failed" for row in results),
        "positive_case_count": sum(row.get("metric_population") == "positive_source" for row in results),
        "unscored_case_count": sum(row.get("metric_population") == "unscored_no_contract" for row in results),
        "negative_case_count": sum(row.get("metric_population") == "negative_control" for row in results),
        "positive_source_case_count": sum(row.get("metric_population") == "positive_source" for row in results),
        "negative_control_case_count": sum(row.get("metric_population") == "negative_control" for row in results),
        "summary": summarize_results(completed),
        "partitions": {partition: {"cases": len(rows), "summary": summarize_results(rows),
                                    "statuses": dict(Counter(row["execution_status"] for row in rows))}
                       for partition, rows in sorted(by_partition.items())},
        "results": results,
        "interpretation": "Fixed-suite retrieval diagnostic; positive-source metrics exclude negative controls and blocked/failed cases. Intervals are case-resampling sensitivity intervals, not population confidence intervals.",
        "promotion_gate": "No runtime profile or agronomic competence is qualified by this baseline alone.",
    }
    report["evaluation_gate"] = evaluation_gate(report, threshold_policy)
    if not report["evaluation_gate"]["passed"]:
        report["status"] = "blocked"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold-policy", type=Path, help="JSON policy with explicit minimum_rates and optional require_no_blocked_cases")
    parser.add_argument("--enforce", action="store_true", help="Return nonzero when the explicit evaluation gate blocks")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; historical retrieval receipts are immutable")
    policy = json.loads(args.threshold_policy.read_text()) if args.threshold_policy else None
    result = evaluate(config_path=args.config, case_path=args.cases, suite_path=args.suite, threshold_policy=policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "status": result["status"], "summary": result["summary"]}, indent=2))
    return 1 if args.enforce and not result["evaluation_gate"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
