#!/usr/bin/env python3
"""Build a two-phase blinded agronomist review packet from saved answer runs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


REVIEW_COLUMNS = [
    "review_id",
    "reviewer_id",
    "would_a_grower_plausibly_ask_this",
    "question_realism_1_to_4",
    "answer_disposition_pass_revise_fail",
    "agronomic_accuracy_1_to_4",
    "decision_usefulness_1_to_4",
    "calibration_safety_1_to_4",
    "crop_jurisdiction_fit_1_to_4",
    "unsafe_or_material_omission_yes_no",
    "requires_current_source_validation_yes_no",
    "primary_error_code",
    "review_notes",
]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_packet(
    sources: list[tuple[str, list[dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    flattened: list[tuple[str, dict[str, Any]]] = []
    for source_label, rows in sources:
        flattened.extend((source_label, row) for row in rows)
    if not flattened:
        raise ValueError("at least one saved answer is required")
    identities = [
        f"{label}|{row.get('eval_id')}|{row.get('question')}|{row.get('output')}"
        for label, row in flattened
    ]
    seed = _stable("|".join(sorted(identities)) + "|agronomist-review-v1")
    ordered = sorted(flattened, key=lambda item: _stable(f"{seed}|{item[0]}|{item[1].get('eval_id')}"))
    phase_a: list[dict[str, Any]] = []
    phase_b: list[dict[str, Any]] = []
    identity_map: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source_label, row in ordered:
        eval_id = str(row.get("eval_id") or "")
        question = str(row.get("question") or "").strip()
        answer = str(row.get("output") or row.get("answer") or "").strip()
        if not eval_id or not question or not answer:
            raise ValueError(f"incomplete review row: {source_label}:{eval_id or '<missing>'}")
        review_id = "agr_" + _stable(f"{seed}|{source_label}|{eval_id}")[:20]
        if review_id in seen_ids:
            raise ValueError("review ID collision")
        seen_ids.add(review_id)
        metadata = row.get("eval_metadata") if isinstance(row.get("eval_metadata"), dict) else {}
        common = {
            "review_id": review_id,
            "question": question,
            "answer": answer,
            "crop": metadata.get("crop") or row.get("crop"),
            "jurisdiction": metadata.get("jurisdiction") or row.get("jurisdiction"),
            "task_family": row.get("task_family"),
            "review_stage": "phase_a_answer_and_question_only",
        }
        phase_a.append(common)
        semantic = row.get("semantic_reference") if isinstance(row.get("semantic_reference"), dict) else {}
        phase_b.append(
            {
                **common,
                "review_stage": "phase_b_source_assisted_after_phase_a_lock",
                "non_exhaustive_reference_points": list(semantic.get("expert_reference_points") or []),
                "known_material_error_hypotheses": list(semantic.get("material_errors") or []),
                "critical_evidence": list(semantic.get("critical_evidence") or []),
                "safe_boundary": semantic.get("safe_boundary"),
                "reference_boundary": (
                    "These criteria are author-provided hypotheses, not gold wording or agronomist certification. "
                    "Review the answer independently and verify current or regulated claims from authoritative sources."
                ),
            }
        )
        identity_map.append(
            {
                "review_id": review_id,
                "source_label": source_label,
                "eval_id": eval_id,
                "question_sha256": _stable(question),
                "answer_sha256": _stable(answer),
            }
        )
    manifest = {
        "schema_version": "open_agronomy_agent.agronomist_answer_review_packet.v1",
        "status": "ready_for_two_phase_independent_review",
        "rows": len(phase_a),
        "model_identity_exposed": False,
        "automated_judge_result_exposed": False,
        "generation_path_exposed": False,
        "question_origin_claim": "not_proven_real_user",
        "phase_policy": (
            "Complete and lock phase A before opening phase B. Use at least two independent Canadian agronomist reviewers; "
            "adjudicate disagreements after both first-pass forms are immutable."
        ),
        "review_columns": REVIEW_COLUMNS,
    }
    return phase_a, phase_b, identity_map, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, help="LABEL=path/to/outputs.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--benchmark-lane",
        help="Keep only rows whose eval_metadata.benchmark_lane matches this value.",
    )
    args = parser.parse_args()
    sources: list[tuple[str, list[dict[str, Any]]]] = []
    source_receipts: list[dict[str, Any]] = []
    for value in args.source:
        if "=" not in value:
            raise ValueError("--source must be LABEL=PATH")
        label, raw_path = value.split("=", 1)
        path = Path(raw_path)
        rows = _jsonl(path)
        if args.benchmark_lane:
            rows = [
                row for row in rows
                if isinstance(row.get("eval_metadata"), dict)
                and row["eval_metadata"].get("benchmark_lane") == args.benchmark_lane
            ]
        sources.append((label, rows))
        source_receipts.append({"label": label, "path": str(path), "sha256": _sha(path)})
    phase_a, phase_b, identity_map, manifest = build_packet(sources)
    manifest["benchmark_lane_filter"] = args.benchmark_lane
    args.output_dir.mkdir(parents=True, exist_ok=True)
    phase_a_path = args.output_dir / "phase_a_blind_question_answer.jsonl"
    phase_b_path = args.output_dir / "phase_b_reference_assisted.jsonl"
    identity_path = args.output_dir / "private_identity_map.jsonl"
    form_path = args.output_dir / "review_form.csv"
    _write_jsonl(phase_a_path, phase_a)
    _write_jsonl(phase_b_path, phase_b)
    _write_jsonl(identity_path, identity_map)
    with form_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for row in phase_a:
            writer.writerow({"review_id": row["review_id"]})
    manifest.update(
        {
            "sources": source_receipts,
            "phase_a": {"path": phase_a_path.name, "sha256": _sha(phase_a_path)},
            "phase_b": {"path": phase_b_path.name, "sha256": _sha(phase_b_path)},
            "identity_map": {"path": identity_path.name, "sha256": _sha(identity_path)},
            "review_form": {"path": form_path.name, "sha256": _sha(form_path)},
        }
    )
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "rows": manifest["rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
