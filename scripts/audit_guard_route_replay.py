#!/usr/bin/env python3
"""Replay every guard-eligible public case through the production execution core."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_rehearsal import ObservedSystemBenchmarkAdapter  # noqa: E402
from agronomy_agent.evals import tool_trace_audit  # noqa: E402
from agronomy_agent.execution_core import AgentExecutionRequest  # noqa: E402
from agronomy_agent.server.settings import build_settings  # noqa: E402
from agronomy_agent.server.storage.db import TraceStore  # noqa: E402


DEFAULT_SUITE = ROOT / "data/eval/open_agronomy_canadian_performance_v1.jsonl"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-config", default="configs/model_gemma4_e2b_interface_v2.yaml")
    parser.add_argument("--rag-config", default="configs/rag.yaml")
    args = parser.parse_args()

    suite = args.suite if args.suite.is_absolute() else ROOT / args.suite
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    cases = [row for row in _rows(suite) if row.get("expected_tools")]
    if len(cases) != 154 or len({row.get("eval_id") for row in cases}) != 154:
        raise ValueError("guard replay requires the exact 154 unique guard-eligible cases")

    database_path = output / "guard_route_replay.sqlite3"
    store = TraceStore(database_path)
    settings = build_settings(
        db_path=database_path,
        artifact_root=output / "artifacts",
        model_config_path=args.model_config,
        default_rag_config=args.rag_config,
        network_mode="offline",
    )
    adapter = ObservedSystemBenchmarkAdapter()
    observations: list[dict[str, Any]] = []
    for row in cases:
        session = store.create_session(
            f"Guard replay {row['eval_id']}",
            {"trace_storage_enabled": True},
            {},
            tags=["benchmark_rehearsal", "guard_route_replay", "claim_ineligible"],
        )
        field_context = row.get("field_context") if isinstance(row.get("field_context"), dict) else None
        result = adapter.execute(
            AgentExecutionRequest(
                store=store,
                settings=settings,
                session_id=session["session_id"],
                message=str(row["question"]),
                mode="agronomic_rag",
                model_id="mock",
                rag_config=args.rag_config,
                max_tokens=180,
                trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
                session_context={"field_context": field_context} if field_context else None,
                execution_class="observed_system_execution_nonclaim",
            )
        )
        trace_metadata = result.execution.turn.get("trace", {}).get("metadata", {})
        audit = tool_trace_audit(row, trace_metadata)
        observations.append(
            {
                "eval_id": row["eval_id"],
                "expected_local_guards": audit["expected_local_guards"],
                "routed_local_guards": audit["routed_local_guards"],
                "missing_local_guards": audit["missing_local_guards"],
                "complete": not audit["missing_local_guards"],
                "stage_receipt_count": len(result.execution.stage_receipts),
                "turn_id": result.execution.turn_id,
            }
        )

    missing = [row for row in observations if not row["complete"]]
    incomplete_stages = [row for row in observations if row["stage_receipt_count"] != 17]
    report = {
        "schema_version": "open_agronomy_agent.guard_route_replay.v1",
        "status": "pass" if not missing and not incomplete_stages else "blocked",
        "claim_eligible": False,
        "claim_boundary": "Current-code route and trace completeness only; not model answer quality or agronomic correctness.",
        "suite_path": str(suite.relative_to(ROOT)),
        "suite_sha256": _sha256(suite),
        "eligible_cases": len(observations),
        "complete_cases": len(observations) - len(missing),
        "missing_cases": len(missing),
        "seventeen_stage_cases": len(observations) - len(incomplete_stages),
        "observations": observations,
    }
    report_path = output / "guard_route_replay.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
