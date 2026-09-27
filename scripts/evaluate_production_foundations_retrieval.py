#!/usr/bin/env python3
"""Measure source-card reachability in the exposed foundations development set."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.agent import load_agent_resources  # noqa: E402
from agronomy_agent.corpus_release import source_locator_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "data/eval/production_foundations_development_v1.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = args.config.resolve()
    cases = args.cases.resolve()
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite output: {output}")
    resources = load_agent_resources(config)
    results = []
    for line in cases.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        docs = resources.retriever.search(case["question"], top_k=7)
        ids = [doc.doc_id for doc in docs]
        expected = case.get("expected_doc_id")
        rank = ids.index(expected) + 1 if expected in ids else None
        results.append({
            "case_id": case["case_id"],
            "kind": case["kind"],
            "expected_doc_id": expected,
            "expected_rank": rank,
            "top_doc_ids": ids,
            "all_locators_valid": all(source_locator_status(doc.source_locator)[0] for doc in docs),
            "expected_policy": next((doc.retrieval_policy for doc in docs if doc.doc_id == expected), None),
        })
    positive = [row for row in results if row["kind"] not in {"transfer_boundary", "current_data_negative"}]
    report = {
        "schema_version": "open_agronomy_agent.production_foundations_retrieval_development.v1",
        "claim_eligible": False,
        "case_file_sha256": hashlib.sha256(cases.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "positive_count": len(positive),
        "recall_at_1": sum(row["expected_rank"] == 1 for row in positive) / len(positive),
        "recall_at_3": sum(row["expected_rank"] is not None and row["expected_rank"] <= 3 for row in positive) / len(positive),
        "recall_at_7": sum(row["expected_rank"] is not None for row in positive) / len(positive),
        "all_returned_locators_valid": all(row["all_locators_valid"] for row in results),
        "results": results,
        "interpretation": "Expected cards were authored after cases but from the same known sources. This tests reachability only, not independent answer quality.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "positive_count": len(positive), "recall_at_1": report["recall_at_1"], "recall_at_3": report["recall_at_3"], "recall_at_7": report["recall_at_7"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
