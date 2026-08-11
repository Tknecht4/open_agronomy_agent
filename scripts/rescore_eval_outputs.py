from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agronomy_agent.answer_safety import normalize_public_answer
from agronomy_agent.evals import (
    aggregate,
    enrich_eval_metadata_with_expected_source_trace,
    eval_question,
    load_jsonl,
    score_item,
    score_item_agribench_proxy,
)
from agronomy_agent.paths import repo_path


def _load_output_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Rescore saved eval outputs with the current rubric while preserving answer text by default.")
    parser.add_argument("--input-run-dir", required=True, help="Existing eval run directory containing outputs.jsonl.")
    parser.add_argument("--suite", required=True, help="Eval suite JSONL used for the original run.")
    parser.add_argument("--output-dir", required=True, help="Directory to write rescored outputs.jsonl and summary.json.")
    parser.add_argument("--mode", default="agronomic_rag_rescore")
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--rubric", choices=["pattern", "agribench_proxy"], default="agribench_proxy")
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply legacy public-answer normalization before scoring. Disabled by default because it changes model output.",
    )
    args = parser.parse_args()

    input_run_dir = repo_path(args.input_run_dir)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    suite_by_id = {item["eval_id"]: item for item in load_jsonl(repo_path(args.suite))}
    source_rows = _load_output_rows(input_run_dir / "outputs.jsonl")

    rescored_rows: list[dict[str, Any]] = []
    normalized_rows = 0
    improved_rows = 0
    regressed_rows = 0
    for row in source_rows:
        eval_id = row["eval_id"]
        item = suite_by_id[eval_id]
        original_output = str(row.get("output", ""))
        normalized_output = (
            normalize_public_answer(original_output, question=eval_question(item))
            if args.normalize
            else original_output
        )
        if normalized_output != original_output:
            normalized_rows += 1

        metadata = enrich_eval_metadata_with_expected_source_trace(dict(row.get("metadata") or {}), item)
        if args.rubric == "agribench_proxy":
            score = score_item_agribench_proxy(normalized_output, item, metadata)
        else:
            score = score_item(normalized_output, item)

        original_value = row.get("score", {}).get("score")
        original_score = float(original_value) if isinstance(original_value, (int, float)) else None
        if score["score"] is not None and original_score is not None:
            if score["score"] > original_score:
                improved_rows += 1
            elif score["score"] < original_score:
                regressed_rows += 1

        updated = dict(row)
        updated["output"] = normalized_output
        updated["score"] = score
        updated["metadata"] = {
            **metadata,
            "rescored_from_run_dir": str(input_run_dir),
            "rescore_normalized": normalized_output != original_output,
            "rescore_original_score": original_score,
        }
        rescored_rows.append(updated)

    with (output_dir / "outputs.jsonl").open("w", encoding="utf-8") as handle:
        for row in rescored_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = aggregate(rescored_rows, args.mode, args.model)
    summary["source_run_dir"] = str(input_run_dir)
    summary["rubric"] = args.rubric
    summary["normalization_enabled"] = args.normalize
    summary["normalized_rows"] = normalized_rows
    summary["improved_rows"] = improved_rows
    summary["regressed_rows"] = regressed_rows
    summary["under90_rows"] = sum(
        1
        for row in rescored_rows
        if isinstance(row["score"].get("score"), (int, float))
        and row["score"]["score"] < 90.0
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
