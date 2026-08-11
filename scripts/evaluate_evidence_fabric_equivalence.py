#!/usr/bin/env python3
"""Check EF-001 prompt/retrieval equivalence against a frozen full-system run.

The new evidence contracts are allowed to add trace metadata only.  This gate
rebuilds a deterministic 40-case sample from the same questions and field
snapshots, then requires exact messages, packed context, and selected-document
order before a model rerun is interpreted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.agent import build_messages, load_agent_resources, load_yaml  # noqa: E402
from agronomy_agent.evals import answer_profile_environment  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sample(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if isinstance((row.get("metadata") or {}).get("benchmark_generation_input"), dict)
    ]
    ordered = sorted(
        eligible,
        key=lambda row: hashlib.sha256(str(row.get("eval_id") or "").encode("utf-8")).hexdigest(),
    )
    if len(ordered) < count:
        raise ValueError(f"reference contains only {len(ordered)} context-captured rows; need {count}")
    return ordered[:count]


def evaluate(
    *,
    reference_outputs: Path,
    rag_config: Path,
    model_config: Path,
    sample_count: int,
) -> dict[str, Any]:
    rows = _sample(_load_jsonl(reference_outputs), sample_count)
    resources = load_agent_resources(str(rag_config))
    prompt_profile = str(load_yaml(model_config).get("prompt_profile") or "default")
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        reference_metadata = row.get("metadata") or {}
        reference_packet = reference_metadata["benchmark_generation_input"]
        with answer_profile_environment(str(row.get("answer_profile") or "benchmark")):
            messages, context = build_messages(
                str(row.get("question") or ""),
                "agronomic_rag",
                resources=resources,
                field_context=row.get("eval_field_context") or None,
                prompt_profile=prompt_profile,
            )
        selected = [] if context is None else [doc.doc_id for doc in context.retrieved_docs]
        rebuilt_context = None if context is None else context.packed_context.text
        checks = {
            "messages_exact": messages == reference_packet.get("messages"),
            "context_block_exact": rebuilt_context == reference_packet.get("context_block"),
            "selected_document_order_exact": selected == list(reference_metadata.get("retrieved_doc_ids") or []),
            "fabric_captured": bool(
                context is None
                or (context.runtime_metadata or {}).get("evidence_fabric", {}).get("status") == "captured"
            ),
        }
        comparisons.append(
            {
                "eval_id": row.get("eval_id"),
                "checks": checks,
                "passed": all(checks.values()),
                "reference_document_order": list(reference_metadata.get("retrieved_doc_ids") or []),
                "candidate_document_order": selected,
                "evidence_packet_id": (
                    None
                    if context is None
                    else (context.runtime_metadata or {})
                    .get("evidence_fabric", {})
                    .get("evidence_packet", {})
                    .get("packet_id")
                ),
            }
        )
    failed = [row for row in comparisons if not row["passed"]]
    return {
        "schema_version": "open_agronomy_agent.evidence_fabric_equivalence.v1",
        "candidate": "EF-001 canonical evidence contracts and behavior-preserving adapters",
        "reference_outputs": str(reference_outputs),
        "reference_outputs_sha256": _sha256(reference_outputs),
        "rag_config": str(rag_config),
        "rag_config_sha256": _sha256(rag_config),
        "model_config": str(model_config),
        "model_config_sha256": _sha256(model_config),
        "sample_selection": "ascending sha256(eval_id) among context-captured rows",
        "sample_count": len(comparisons),
        "passed_count": len(comparisons) - len(failed),
        "failed_count": len(failed),
        "status": "pass" if not failed else "fail",
        "public_answer_path_changed": False,
        "comparisons": comparisons,
        "boundary": (
            "This gate proves exact retrieval order and generation inputs on the locked sample. "
            "It does not replace the two-model answer rerun or independent agronomist review."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-outputs", type=Path, required=True)
    parser.add_argument("--rag-config", type=Path, default=ROOT / "configs/rag_final_mvp.yaml")
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        reference_outputs=args.reference_outputs.resolve(),
        rag_config=args.rag_config.resolve(),
        model_config=args.model_config.resolve(),
        sample_count=args.sample_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "sample_count", "passed_count", "failed_count")}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
