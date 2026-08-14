#!/usr/bin/env python3
"""Retain one non-claim execution through the production cockpit core."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_rehearsal import (  # noqa: E402
    ObservedSystemBenchmarkAdapter,
    RETRIEVAL_BOTH_CONFIGURATION_ID,
    RETRIEVAL_COMPONENT_CONFIGURATIONS,
)
from agronomy_agent.execution_core import AgentExecutionRequest  # noqa: E402
from agronomy_agent.server.settings import build_settings  # noqa: E402
from agronomy_agent.server.storage.db import TraceStore  # noqa: E402


DEFAULT_QUESTION = "Convert a fertilizer rate of 100 lb/ac to kg/ha."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one retained, claim-ineligible rehearsal through the same "
            "production core used by the cockpit."
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--mode",
        choices=("baseline", "agronomic_rag", "mock"),
        default="agronomic_rag",
    )
    parser.add_argument("--model-id", default="mock")
    parser.add_argument("--model-config", default="configs/model_gemma4_e2b_interface_v2.yaml")
    parser.add_argument("--rag-config", default="configs/rag_governed_runtime_v2.yaml")
    parser.add_argument("--max-tokens", type=int, default=180)
    parser.add_argument(
        "--retrieval-configuration",
        choices=tuple(RETRIEVAL_COMPONENT_CONFIGURATIONS),
        default=RETRIEVAL_BOTH_CONFIGURATION_ID,
        help=(
            "Controlled document/graph retrieval arm. Non-retrieval production "
            "stages cannot be disabled by this rehearsal."
        ),
    )
    parser.add_argument(
        "--field-context-json",
        help="Optional JSON object supplied as the session field context.",
    )
    parser.add_argument(
        "--network-mode",
        choices=("offline", "online"),
        default="offline",
    )
    parser.add_argument("--store-prompt-messages", action="store_true")
    parser.add_argument("--store-retrieved-text", action="store_true")
    return parser


def _field_context(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("--field-context-json must decode to a JSON object")
    return payload


def main() -> int:
    args = build_parser().parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty rehearsal directory: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / "observed_system_rehearsal.sqlite3"
    result_path = output_dir / "observed_system_rehearsal.json"

    store = TraceStore(database_path)
    session = store.create_session(
        "Observed-system benchmark rehearsal",
        {"trace_storage_enabled": True},
        {},
        tags=["benchmark_rehearsal", "claim_ineligible"],
    )
    settings = build_settings(
        db_path=database_path,
        artifact_root=output_dir / "artifacts",
        model_config_path=args.model_config,
        default_rag_config=args.rag_config,
        network_mode=args.network_mode,
    )
    field_context = _field_context(args.field_context_json)
    component_configuration = RETRIEVAL_COMPONENT_CONFIGURATIONS[
        args.retrieval_configuration
    ]
    request = AgentExecutionRequest(
        store=store,
        settings=settings,
        session_id=session["session_id"],
        message=args.question,
        mode=args.mode,
        model_id=args.model_id,
        rag_config=args.rag_config,
        max_tokens=args.max_tokens,
        trace_options={
            "store_prompt_messages": args.store_prompt_messages,
            "store_retrieved_text": args.store_retrieved_text,
        },
        session_context={"field_context": field_context} if field_context else None,
        execution_class="observed_system_execution_nonclaim",
        document_retrieval_enabled=component_configuration["document_retrieval"],
        graph_retrieval_enabled=component_configuration["graph_retrieval"],
    )
    result = ObservedSystemBenchmarkAdapter().execute(
        request,
        component_configuration_id=args.retrieval_configuration,
    )
    result_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result_class": result.result_class,
                "claim_eligible": result.claim_eligible,
                "turn_id": result.execution.turn_id,
                "answer": result.execution.answer,
                "result_path": str(result_path),
                "database_path": str(database_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
