#!/usr/bin/env python3
"""Run exposed production-foundations questions through the product execution core.

This instrument retains responses and trace receipts. Its source-hit and numeric
proxies are diagnostics, not an agronomic or sealed benchmark judgment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_rehearsal import ObservedSystemBenchmarkAdapter  # noqa: E402
from agronomy_agent.execution_core import AgentExecutionRequest  # noqa: E402
from agronomy_agent.server.settings import build_settings  # noqa: E402
from agronomy_agent.server.storage.db import TraceStore  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage(result: dict, name: str) -> dict:
    for item in result["execution"].get("stage_receipts") or []:
        if item.get("stage_id") == name:
            return item.get("evidence") or {}
    return {}


def _numeric_proxy(answer: str, expected: float, tolerance: float) -> bool:
    """Check presence only; source/input numbers can give false positives."""
    for token in re.findall(r"(?<!\w)-?\d[\d,]*(?:\.\d+)?", answer):
        try:
            if abs(float(token.replace(",", "")) - expected) <= tolerance:
                return True
        except ValueError:
            pass
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "data/eval/production_foundations_development_v1.jsonl")
    parser.add_argument("--rag-config", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, default=ROOT / "configs/model.yaml")
    parser.add_argument("--model-id", default="mlx-community/gemma-4-e2b-it-4bit")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-ids", help="Comma-separated subset; otherwise run all cases")
    parser.add_argument("--max-tokens", type=int, default=160)
    args = parser.parse_args()
    cases_path = args.cases.resolve()
    config_path = args.rag_config.resolve()
    model_path = args.model_config.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"refusing nonempty output directory: {output_dir}")
    if args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")
    if not config_path.is_relative_to(ROOT):
        parser.error("--rag-config must be inside this repository")
    rag_payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    policy_path = ROOT / str((rag_payload.get("retrieval") or {}).get("corpus_policy_manifest") or "")
    if not policy_path.is_file():
        parser.error("RAG corpus policy is missing")
    supplement_value = str((rag_payload.get("release_profile") or {}).get("production_foundations_store") or "")
    supplement_store = ROOT / supplement_value if supplement_value else None
    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    selected = set(args.case_ids.split(",")) if args.case_ids else None
    if selected is not None:
        unknown = selected - {case["case_id"] for case in cases}
        if unknown:
            parser.error(f"unknown case IDs: {sorted(unknown)}")
        cases = [case for case in cases if case["case_id"] in selected]
    output_dir.mkdir(parents=True, exist_ok=True)
    store = TraceStore(output_dir / "traces.sqlite3")
    settings = build_settings(
        db_path=output_dir / "traces.sqlite3",
        artifact_root=output_dir / "artifacts",
        model_config_path=str(model_path),
        default_rag_config=str(config_path),
        network_mode="offline",
    )
    rows = []
    adapter = ObservedSystemBenchmarkAdapter()
    for case in cases:
        session = store.create_session("Production foundations exposed development", {"trace_storage_enabled": True}, {}, tags=["development", "claim_ineligible"])
        request = AgentExecutionRequest(
            store=store,
            settings=settings,
            session_id=session["session_id"],
            message=case["question"],
            mode="agronomic_rag",
            model_id=args.model_id,
            rag_config=str(config_path),
            max_tokens=args.max_tokens,
            trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
            execution_class="observed_system_execution_nonclaim",
        )
        started = time.perf_counter()
        result = adapter.execute(request).to_dict()
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        persisted = store.get_turn(result["execution"]["turn_id"])
        trace_metadata = ((persisted or {}).get("trace") or {}).get("metadata") or {}
        generation_stats = trace_metadata.get("generation_stats") or {}
        answer = result["execution"]["answer"]
        documents = _stage(result, "document_retrieval").get("document_ids") or []
        expected = case.get("expected_doc_id")
        row = {
            "case_id": case["case_id"],
            "kind": case.get("kind") or case.get("case_class") or "unspecified",
            "question": case["question"],
            "answer": answer,
            "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
            "expected_doc_id": expected,
            "expected_doc_retrieved": expected in documents if expected else None,
            "retrieved_doc_ids": documents,
            "numeric_presence_proxy": _numeric_proxy(
                answer,
                float(case.get("expected_number", case.get("expected_value"))),
                float(case.get("number_tolerance", case.get("absolute_tolerance", 0.01))),
            ) if "expected_number" in case or "expected_value" in case else None,
            "required_term_presence_proxy": {term: term.casefold() in answer.casefold() for term in case.get("required_terms") or []},
            "draft_generation": _stage(result, "draft_generation"),
            "fallback_origin": _stage(result, "fallback_origin"),
            "verification": _stage(result, "verification"),
            "elapsed_ms": elapsed,
            "turn_id": result["execution"]["turn_id"],
            "model_identity": trace_metadata.get("model_identity") or {},
            "seed_application": generation_stats.get("seed_application") or {},
            "generation_tokens": generation_stats.get("generation_tokens"),
            "prompt_tokens": generation_stats.get("prompt_tokens"),
            "execution_fingerprints": trace_metadata.get("execution_fingerprints") or {},
        }
        rows.append(row)
        with (output_dir / "cases.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(json.dumps({"case_id": row["case_id"], "expected_doc_retrieved": row["expected_doc_retrieved"], "numeric_presence_proxy": row["numeric_presence_proxy"], "elapsed_ms": elapsed}), flush=True)
    report = {
        "schema_version": "open_agronomy_agent.production_foundations_exposed_development.v1",
        "claim_eligible": False,
        "cases_sha256": _sha256(cases_path),
        "rag_config_sha256": _sha256(config_path),
        "rag_config_path": config_path.relative_to(ROOT).as_posix(),
        "corpus_policy_sha256": _sha256(policy_path),
        "supplement_store_sha256": json.loads(supplement_store.read_text(encoding="utf-8"))["store_sha256"] if supplement_store else None,
        "model_config_sha256": _sha256(model_path),
        "model_id": args.model_id,
        "max_tokens": args.max_tokens,
        "runner_sha256": _sha256(Path(__file__)),
        "case_count": len(rows),
        "expected_doc_retrieved_count": sum(row["expected_doc_retrieved"] is True for row in rows),
        "numeric_presence_proxy_count": sum(row["numeric_presence_proxy"] is True for row in rows),
        "model_generation_completed_count": sum(row["draft_generation"].get("reason") == "draft_generation_completed" for row in rows),
        "fallback_count": sum(bool(row["fallback_origin"].get("fallback_used")) for row in rows),
        "elapsed_ms_total": round(sum(row["elapsed_ms"] for row in rows), 1),
        "seed_application_statuses": sorted({str(row["seed_application"].get("status") or "missing") for row in rows}),
        "cases": rows,
        "interpretation": "Exposed development instrument; numeric text presence can match a question number and requires manual adjudication.",
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_dir / "report.json"), "cases": len(rows), "source_hits": report["expected_doc_retrieved_count"], "fallbacks": report["fallback_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
