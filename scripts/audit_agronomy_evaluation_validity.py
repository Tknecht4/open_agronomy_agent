#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agronomy_agent.evaluation_validity import build_evaluation_validity_report


def load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render(report: dict[str, Any]) -> str:
    questions = report["question_suite"]
    proxy = report["deterministic_proxy"]
    judge = report["automated_judge"]
    lines = [
        "# Agronomy evaluation validity audit",
        "",
        f"External capability claim eligible: **{report['external_capability_claim_eligible']}**",
        "",
        "## Question realism",
        "",
        f"- Rows: {questions['rows']}",
        f"- Proven real-user questions: {questions['proven_real_user_rows']}",
        f"- Multi-turn questions: {questions['multi_turn_rows']}",
        f"- Blockers: {', '.join(questions['blockers']) or 'none'}",
        f"- Claim scope: {questions['supported_claim_scope']}",
        "",
        "## Deterministic proxy",
        "",
        f"- Valid lexical contracts: {proxy['valid_lexical_contract_rows']}/{proxy['rows']}",
        f"- Undefined rows: {proxy['undefined_proxy_rows']}",
        f"- Finding: {proxy['finding']}",
        "",
        "## Automated judge",
        "",
        f"- Pass rate: {judge['pass_rate']}",
        f"- Self-reported high-confidence rate: {judge['high_confidence_rate']}",
        f"- Answer-length/score Pearson: {judge['answer_length_score_pearson']}",
        f"- Independent agronomist calibration rows: {judge['independent_agronomist_review_rows']}",
        f"- Known false accepts: {len(judge['known_false_accepts'])}",
        f"- Blockers: {', '.join(judge['blockers']) or 'none'}",
    ]
    controls = judge.get("logic_control_audit")
    if controls:
        lines.extend(
            [
                f"- Logic-control accuracy: {controls['exact_disposition_accuracy']}",
                f"- Logic-control false-accept rate: {controls['false_accept_rate']}",
                f"- Logic-control boundary: {controls['control_boundary']}",
            ]
        )
    lines.extend([
        "",
        "## Honest conclusion",
        "",
        report["honest_conclusion"],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--manual-reviews", type=Path)
    parser.add_argument("--judge-control-judgments", type=Path)
    parser.add_argument("--judge-control-expected", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_evaluation_validity_report(
        suite_rows=load_jsonl(args.suite),
        output_rows=load_jsonl(args.outputs),
        judgment_rows=load_jsonl(args.judgments),
        manual_reviews=load_jsonl(args.manual_reviews),
        judge_control_judgments=load_jsonl(args.judge_control_judgments),
        judge_control_expected=(
            load_jsonl(args.judge_control_expected)
            if args.judge_control_expected is not None
            else None
        ),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "audit.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"external_capability_claim_eligible": report["external_capability_claim_eligible"], "release_blockers": report["release_blockers"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
