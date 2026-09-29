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


REAL_USER_ORIGINS = {
    "deidentified_grower_query", "deidentified_advisor_query", "farmer_survey",
    "support_log_with_consent", "participatory_field_study",
    "real_user_farmer_question_from_peer_reviewed_external_dataset",
}


def _origin(row: dict[str, Any]) -> str:
    def find(container: dict[str, Any], *, typed_origin: bool = False) -> str | None:
        value = container.get("question_origin")
        if isinstance(value, str) and value:
            return value
        value = container.get("origin")
        if isinstance(value, str) and value:
            return value
        if typed_origin:
            for key in ("type", "kind", "name"):
                if isinstance(container.get(key), str) and container[key]:
                    return container[key]
        for key in ("origin", "provenance", "metadata", "eval_metadata"):
            if isinstance(container.get(key), dict):
                found = find(container[key], typed_origin=key == "origin")
                if found:
                    return found
        return None
    return find(row) or "missing"


def _question_texts(row: dict[str, Any]) -> list[str]:
    texts = []
    turns = row.get("turns") or []
    if isinstance(turns, list):
        texts = [str(turn if isinstance(turn, str) else turn.get("question") or turn.get("content") or "")
                 for turn in turns if isinstance(turn, (str, dict))
                 and (not isinstance(turn, dict) or turn.get("role", "user") == "user")]
    if row.get("question") and str(row["question"]) not in texts:
        texts.append(str(row["question"]))
    return [text for text in texts if text]


def _traceable(row: dict[str, Any]) -> bool:
    if _origin(row) not in REAL_USER_ORIGINS:
        return False
    def has_reference(container: dict[str, Any]) -> bool:
        if any(container.get(key) for key in ("source_url", "source_record_id", "public_dataset_id")):
            return True
        return any(has_reference(container[key]) for key in ("origin", "provenance", "metadata", "eval_metadata")
                   if isinstance(container.get(key), dict))
    # An origin assertion alone is not traceability or independent validation.
    return has_reference(row)


def summarize_suite(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    question_rows = [row for row in rows if isinstance(row, dict) and _question_texts(row)]
    questions = [text for row in question_rows for text in _question_texts(row) if text]
    lexical_contract_rows = sum(bool(row.get("required_patterns") or row.get("forbidden_patterns") or row.get("ask_for_patterns")) for row in question_rows)
    semantic_reference_rows = sum(bool(row.get("expert_reference_points") or row.get("reference_answer") or row.get("expected_answer")) for row in question_rows)
    origins = Counter(_origin(row) for row in question_rows)
    scenarios = {str(row.get("scenario_id") or row.get("match_group")) for row in question_rows if row.get("scenario_id") or row.get("match_group")}
    bundles = {str(row["bundle_id"]) for row in question_rows if row.get("bundle_id")}
    return {
        "path": str(path), "rows": len(question_rows),
        "question_text_count": len(questions), "unique_questions": len(set(questions)),
        "duplicate_question_variants": len(questions) - len(set(questions)),
        "scenario_identity_count": len(scenarios), "scenario_identities": sorted(scenarios),
        "scenario_identity_missing_rows": sum(not (row.get("scenario_id") or row.get("match_group")) for row in question_rows),
        "field_bundle_count": len(bundles), "field_bundle_ids": sorted(bundles),
        "lexical_contract_rows": lexical_contract_rows, "semantic_reference_rows": semantic_reference_rows,
        "multi_turn_rows": sum(bool(row.get("turns")) for row in question_rows),
        "question_origin": dict(sorted(origins.items())),
        "real_user_origin_asserted_rows": sum(_origin(row) in REAL_USER_ORIGINS for row in question_rows),
        "traceable_real_user_rows": sum(_traceable(row) for row in question_rows),
        "external_farmer_question_rows": sum(_origin(row) == "real_user_farmer_question_from_peer_reviewed_external_dataset" for row in question_rows),
        "target_user_validation_established": False,
        "metric_role": "lexical_contract_regression_only" if lexical_contract_rows else "semantic_or_workflow_review_requires_human_labels",
        "external_usefulness_claim_eligible": False,
    }


def build_inventory(paths: list[Path]) -> dict[str, Any]:
    suites = []
    all_questions: set[str] = set()
    for path in sorted(set(paths)):
        rows = _jsonl(path)
        if not rows or not any(isinstance(row, dict) and (row.get("question") or row.get("turns")) for row in rows):
            continue
        summary = summarize_suite(path, rows)
        suites.append(summary)
        for row in rows:
            if isinstance(row, dict) and (row.get("question") or row.get("turns")):
                all_questions.update(hashlib.sha256(text.encode("utf-8")).hexdigest() for text in _question_texts(row) if text)
    return {
        "schema_version": "open_agronomy_agent.evaluation_suite_inventory.v2",
        "suite_files": len(suites),
        "question_rows_including_cross_suite_duplicates": sum(row["rows"] for row in suites),
        "unique_question_fingerprints": len(all_questions),
        "question_text_count_including_duplicates": sum(row["question_text_count"] for row in suites),
        "scenario_identity_count_within_suite": sum(row["scenario_identity_count"] for row in suites),
        "field_bundle_count_within_suite": sum(row["field_bundle_count"] for row in suites),
        "external_farmer_question_rows": sum(row["external_farmer_question_rows"] for row in suites),
        "target_user_validation_established": False,
        "lexical_contract_rows_including_duplicates": sum(row["lexical_contract_rows"] for row in suites),
        "traceable_real_user_rows": sum(row["traceable_real_user_rows"] for row in suites),
        "external_usefulness_claim_eligible": False,
        "boundary": (
            "The inventory contains synthetic, expert-authored, imported proxy, regression, transfer, and workflow suites. "
            "Traceable external farmer questions are distinguished from authored questions; imported origins and repeated text do not establish validation with target users. Scenario identities and field bundles are distinct from text counts. Aggregate rows cannot estimate grower usefulness or field failure probability."
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
