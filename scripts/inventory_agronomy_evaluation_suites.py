#!/usr/bin/env python3
"""Inventory agronomy question suites and expose their construct and provenance limits."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize_suite(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    question_rows = [row for row in rows if row.get("question") or row.get("turns")]
    questions = [str(row.get("question") or row.get("turns") or "") for row in question_rows]
    lexical_contract_rows = sum(
        bool(row.get("required_patterns") or row.get("forbidden_patterns") or row.get("ask_for_patterns"))
        for row in question_rows
    )
    semantic_reference_rows = sum(
        bool(row.get("expert_reference_points") or row.get("reference_answer") or row.get("expected_answer"))
        for row in question_rows
    )
    origins = Counter(str(row.get("question_origin") or "missing") for row in question_rows)
    return {
        "path": str(path),
        "rows": len(question_rows),
        "unique_questions": len(set(questions)),
        "duplicate_question_variants": len(question_rows) - len(set(questions)),
        "lexical_contract_rows": lexical_contract_rows,
        "semantic_reference_rows": semantic_reference_rows,
        "multi_turn_rows": sum(bool(row.get("turns")) for row in question_rows),
        "question_origin": dict(sorted(origins.items())),
        "traceable_real_user_rows": sum(
            count
            for origin, count in origins.items()
            if origin in {
                "deidentified_grower_query",
                "deidentified_advisor_query",
                "farmer_survey",
                "support_log_with_consent",
                "participatory_field_study",
            }
        ),
        "metric_role": (
            "lexical_contract_regression_only"
            if lexical_contract_rows
            else "semantic_or_workflow_review_requires_human_labels"
        ),
        "external_usefulness_claim_eligible": False,
    }


def build_inventory(paths: list[Path]) -> dict[str, Any]:
    suites = []
    all_questions: set[str] = set()
    for path in sorted(paths):
        rows = _jsonl(path)
        if not rows or not any(isinstance(row, dict) and (row.get("question") or row.get("turns")) for row in rows):
            continue
        summary = summarize_suite(path, rows)
        suites.append(summary)
        for row in rows:
            if row.get("question") or row.get("turns"):
                all_questions.add(hashlib.sha256(str(row.get("question") or row.get("turns")).encode("utf-8")).hexdigest())
    return {
        "schema_version": "open_agronomy_agent.evaluation_suite_inventory.v1",
        "suite_files": len(suites),
        "question_rows_including_cross_suite_duplicates": sum(row["rows"] for row in suites),
        "unique_question_fingerprints": len(all_questions),
        "lexical_contract_rows_including_duplicates": sum(row["lexical_contract_rows"] for row in suites),
        "traceable_real_user_rows": sum(row["traceable_real_user_rows"] for row in suites),
        "external_usefulness_claim_eligible": False,
        "boundary": (
            "The inventory contains synthetic, expert-authored, imported proxy, regression, transfer, and workflow suites. "
            "No row carries traceable real-user provenance metadata, so aggregate rows cannot estimate grower usefulness or field failure probability."
        ),
        "suites": suites,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = [path for root in args.root for path in root.rglob("*.jsonl")]
    report = build_inventory(paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown = [
        "# Evaluation suite inventory",
        "",
        f"Suite files: **{report['suite_files']}**",
        f"Question rows including cross-suite duplicates: **{report['question_rows_including_cross_suite_duplicates']}**",
        f"Unique question fingerprints: **{report['unique_question_fingerprints']}**",
        f"Lexical-contract rows including duplicates: **{report['lexical_contract_rows_including_duplicates']}**",
        f"Traceable real-user rows: **{report['traceable_real_user_rows']}**",
        "",
        report["boundary"],
        "",
        "| Suite | Rows | Unique | Contract | Semantic reference | Multi-turn | Role |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for suite in report["suites"]:
        markdown.append(
            f"| `{suite['path']}` | {suite['rows']} | {suite['unique_questions']} | "
            f"{suite['lexical_contract_rows']} | {suite['semantic_reference_rows']} | "
            f"{suite['multi_turn_rows']} | {suite['metric_role']} |"
        )
    args.output.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("suite_files", "question_rows_including_cross_suite_duplicates", "unique_question_fingerprints", "traceable_real_user_rows")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
