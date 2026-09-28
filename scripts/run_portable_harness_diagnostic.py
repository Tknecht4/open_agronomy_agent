#!/usr/bin/env python3
"""Run a public, exposed, non-claim diagnostic through the product execution core.

Each cell is a killable child process. Results are append-only and a run can be
resumed against its original input hashes. This is an instrument, not a judge.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_rehearsal import ObservedSystemBenchmarkAdapter  # noqa: E402
from agronomy_agent.execution_core import AgentExecutionRequest  # noqa: E402
from agronomy_agent.server.settings import build_settings  # noqa: E402
from agronomy_agent.server.storage.db import TraceStore  # noqa: E402
from agronomy_agent.server.services.chat_service import _build_mlx_generator  # noqa: E402
from agronomy_agent.server.services.conversation_context import cache_scope  # noqa: E402

SCHEMA = "open_agronomy_agent.portable_harness_diagnostic.v1"
DEFAULT_CASES = ROOT / "data/eval/production_foundations_method_holdout_v3.jsonl"
DEFAULT_ARMS = {
    "active": ROOT / "configs/rag.yaml",
    "method_candidate": ROOT / "configs/rag_production_foundations_method_candidate.yaml",
}
DIRECT_REFERENCE_SYSTEM = (
    "You are an agronomy research assistant. Answer the user's question directly and explain the "
    "reasoning or calculation method when useful. Distinguish general methods from local measurements "
    "and current legal authority. State material unknowns; do not invent field facts, pesticide labels, "
    "rates, thresholds, or guaranteed outcomes."
)

# Synthetic prompts contain no private field records or evaluation answers.
CONTINUITY = (
    {
        "id": "synthetic_rate_correction",
        "turns": [
            "Synthetic wheat field: 40 acres; seed rate 100 lb/ac. Explain how to estimate total seed mass, showing units. Do not choose a seeding rate.",
            "Correction: the field is 50 acres, not 40. Keep the same stated 100 lb/ac rate. Recalculate and name what changed.",
            "Correction: the 100 lb/ac figure was only an example, not an approved target. Explain the calculation method without claiming a real purchase amount.",
        ],
    },
    {
        "id": "synthetic_authority_correction",
        "turns": [
            "A synthetic Ontario orchard note says an insect was seen yesterday. What evidence is needed before a pesticide decision?",
            "Correction: the insect identification was uncertain and the photo may show a beneficial species. Revise the next steps.",
            "Correction: we have no current product label or local threshold. Summarize what remains unknown and what can safely be done now.",
        ],
    },
)


def long_context_turns() -> list[str]:
    note = ("Synthetic planning note: soil sample identity is unknown; a regional map is context, "
            "not a field measurement; no rate, diagnosis, or label authority has been supplied. ")
    return [
        "Review these deliberately repetitive synthetic notes and identify the missing evidence. " + note * 115,
        "Correction: the earlier notes were generic examples, not observations from this field. "
        "What can be concluded, and what must remain unknown?",
    ]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"cases file missing: {path}")
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id") or case.get("id") or "").strip()
        if not case_id or case_id in ids or not str(case.get("question") or "").strip():
            raise ValueError("cases require distinct id/case_id and nonempty question")
        ids.add(case_id)
    return cases


def public_rag_config(source: Path) -> dict[str, Any]:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid RAG config: {source}")
    retrieval = payload.get("retrieval")
    if not isinstance(retrieval, dict) or not retrieval.get("corpus_policy_manifest"):
        raise ValueError(f"RAG config has no corpus policy: {source}")
    # The source profiles enable a machine-local overlay. The benchmark must
    # disable it even if the Colab host has an inherited manifest environment.
    payload["private_knowledge"] = {"enabled": False, "required": False}
    return payload


def rag_artifact_receipt(payload: dict[str, Any]) -> dict[str, str]:
    """Hash the active bytes the two public RAG profiles can use in this run."""

    retrieval = payload["retrieval"]
    # Canadian public-source lookups use this registry indirectly through
    # canada_sources, including for questions with no explicit tool call.
    values = ["data/manifests/canada_agronomy_sources.json",
              retrieval["corpus_policy_manifest"], *(retrieval.get("corpus_paths") or []),
              *(retrieval.get("graph_paths") or [])]
    for graph in retrieval.get("graph_paths") or []:
        graph_path = Path(str(graph))
        values.append(str(graph_path.with_suffix(".manifest.json")))
    profile = payload.get("release_profile") or {}
    for key in ("active_store", "production_foundations_store", "method_transfer_store"):
        if profile.get(key):
            values.append(profile[key])
    for release in retrieval.get("on_demand_corpus_releases") or []:
        manifest_value = release["manifest_path"]
        values.append(manifest_value)
        manifest_path = ROOT / manifest_value
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        index = manifest.get("bm25_statistics_index") or {}
        values.append(str(Path(manifest_value).parent / str(index.get("path") or "")))
    receipts: dict[str, str] = {}
    for value in values:
        path = Path(str(value))
        resolved = (path if path.is_absolute() else ROOT / path).resolve()
        if not resolved.is_file() or not resolved.is_relative_to(ROOT):
            raise ValueError(f"public RAG artifact missing or outside repository: {value}")
        receipts[resolved.relative_to(ROOT).as_posix()] = sha256_file(resolved)
    return dict(sorted(receipts.items()))


def model_config_for_cell(source: Path, *, cache_enabled: bool) -> dict[str, Any]:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("model_revision"):
        raise ValueError("model config must declare a pinned model_revision")
    if payload.get("draft_model_id"):
        raise ValueError("diagnostic does not support a draft model")
    if payload.get("answer_verification", {}).get("enabled"):
        verifier = payload["answer_verification"]
        if verifier.get("model_id") != payload.get("serving_model_id", payload.get("model_id")):
            raise ValueError("verifier must use the same pinned serving model")
        if verifier.get("model_revision") != payload["model_revision"]:
            raise ValueError("verifier revision must match the pinned serving revision")
    payload["prompt_cache_enabled"] = cache_enabled
    payload["use_stream_generate"] = True
    return payload


def build_units(cases: list[dict[str, Any]], *, continuity: bool, long_context: bool = False,
                cache_case_id: str | None, direct_reference: bool = False) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for arm in DEFAULT_ARMS:
        for case in cases:
            case_id = str(case.get("case_id") or case["id"])
            units.append({"unit_id": f"main/{arm}/{case_id}", "kind": "exposed_pair", "arm": arm,
                          "case_id": case_id, "turns": [case["question"]], "cache_enabled": False})
        if continuity:
            for sequence in CONTINUITY:
                units.append({"unit_id": f"continuity/{arm}/{sequence['id']}", "kind": "synthetic_continuity",
                              "arm": arm, "case_id": sequence["id"], "turns": sequence["turns"], "cache_enabled": False})
        if long_context:
            units.append({"unit_id": f"long_context/{arm}/synthetic_history_boundary", "kind": "synthetic_long_context",
                          "arm": arm, "case_id": "synthetic_history_boundary", "turns": long_context_turns(),
                          "cache_enabled": False})
        if cache_case_id:
            question = next((case["question"] for case in cases if str(case.get("case_id") or case.get("id")) == cache_case_id), None)
            if question is None:
                raise ValueError(f"unknown cache case ID: {cache_case_id}")
            units.append({"unit_id": f"cache/{arm}/{cache_case_id}", "kind": "cache_cold_warm",
                          "arm": arm, "case_id": cache_case_id, "turns": [question],
                          "cache_enabled": True})
    if direct_reference:
        for case in cases:
            case_id = str(case.get("case_id") or case["id"])
            units.append({"unit_id": f"direct_reference/{case_id}", "kind": "direct_reference",
                          "arm": "direct_reference", "case_id": case_id,
                          "turns": [case["question"]], "cache_enabled": False})
    return units


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _stage(execution: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
    for item in execution.get("stage_receipts") or []:
        if item.get("stage_id") == stage_id:
            return item
    return None


def _source_receipt() -> dict[str, Any]:
    paths = sorted(path for path in (ROOT / "src").rglob("*.py") if path.is_file() and not path.is_symlink())
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    source_files = {path.relative_to(ROOT).as_posix(): sha256_file(path) for path in paths}
    return {"git_commit": commit, "source_tree_sha256": canonical_hash(source_files),
            "source_file_count": len(source_files), "source_sha256": source_files}


def _runtime_receipt() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for package in ("mlx", "mlx-lm", "pyyaml"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    try:
        import mlx.core as mx
        device = str(mx.default_device())
    except (ImportError, RuntimeError) as exc:
        device = f"unavailable:{type(exc).__name__}"
    return {"python": sys.version, "platform": platform.platform(), "packages": versions, "mlx_device": device}


def _preflight_child(spec_path: Path, output_path: Path) -> int:
    """Exercise the exact source generator in an isolated, killable process."""

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    messages = [{"role": "system", "content": DIRECT_REFERENCE_SYSTEM},
                {"role": "user", "content": "State that an unmeasured synthetic field value is unknown."}]
    started = time.perf_counter()
    try:
        config_path = Path(spec["model_config"])
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        generator = _build_mlx_generator(spec["model_id"], config, str(config_path))
        generator.max_tokens = 8
        generator.set_cache_scope("portable-diagnostic-source-preflight")
        answer = str(generator.generate(messages))
        stats = dict(getattr(generator, "last_generation_stats", {}) or {})
        identity = dict(getattr(generator, "model_identity", {}) or {})
        snapshot = str(getattr(generator, "_resolved_model_snapshot", "") or "") or None
        runtime = _runtime_receipt()
        if not answer.strip() or int(stats.get("generation_tokens") or 0) <= 0 or not snapshot:
            raise RuntimeError("source generator produced no verified model tokens or resolved snapshot")
        if "gpu" not in str(runtime.get("mlx_device") or "").lower():
            raise RuntimeError("source generator did not report an MLX GPU device")
        row = {"schema_version": SCHEMA, "status": "passed", "boundary": "generator_availability_only_not_quality_cell",
               "manifest_sha256": spec["manifest_sha256"],
               "model_id": spec["model_id"], "configured_revision": config.get("model_revision"),
               "model_config_sha256": sha256_file(config_path), "resolved_model_snapshot": snapshot,
               "prompt_messages": messages, "prompt_sha256": canonical_hash(messages),
               "answer": answer, "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
               "generation_stats": stats, "model_identity": identity, "runtime": runtime,
               "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
        exit_code = 0
    except Exception as exc:
        config_path = Path(spec["model_config"])
        row = {"schema_version": SCHEMA, "status": "failed", "boundary": "generator_availability_only_not_quality_cell",
               "manifest_sha256": spec["manifest_sha256"],
               "model_id": spec["model_id"],
               "model_config_sha256": sha256_file(config_path) if config_path.is_file() else None,
               "error_type": type(exc).__name__, "error": str(exc)[:1000],
               "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
        exit_code = 1
    output_path.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return exit_code


def _ensure_preflight(*, output_dir: Path, model_config: Path, model_id: str,
                      environment: dict[str, str], timeout_seconds: float,
                      manifest_sha256: str) -> bool:
    ledger = output_dir / "preflight.jsonl"
    prior = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()] if ledger.exists() else []
    if any(row.get("status") == "passed" and (row.get("child") or {}).get("manifest_sha256") == manifest_sha256
           for row in prior):
        return True
    root = output_dir / "preflight"
    root.mkdir(exist_ok=True)
    attempt = 1
    while (root / f"attempt-{attempt:06d}").exists():
        attempt += 1
    cell = root / f"attempt-{attempt:06d}"
    cell.mkdir(exist_ok=False)
    spec = cell / "spec.json"
    result = cell / "result.json"
    spec.write_text(json.dumps({"model_config": str(model_config), "model_id": model_id,
                                "manifest_sha256": manifest_sha256}, sort_keys=True) + "\n")
    try:
        process = subprocess.run([sys.executable, str(Path(__file__)), "--preflight-spec", str(spec),
                                  "--preflight-output", str(result)], cwd=ROOT, env=environment,
                                 capture_output=True, text=True, timeout=timeout_seconds, check=False)
        exit_code: int | None = process.returncode
        stderr_tail = process.stderr[-2000:]
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stderr_tail = str(exc.stderr or b"")[-2000:]
    child = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else None
    passed = (exit_code == 0 and isinstance(child, dict) and child.get("status") == "passed"
              and child.get("manifest_sha256") == manifest_sha256)
    _append_jsonl(ledger, {"schema_version": SCHEMA, "status": "passed" if passed else "failed",
                          "attempt": attempt, "attempt_dir": str(cell), "exit_code": exit_code,
                          "stderr_tail": None if passed else stderr_tail, "child": child,
                          "recorded_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"preflight": "passed" if passed else "failed", "attempt": attempt}), flush=True)
    return passed


def model_execution_disposition(metadata: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    fallback = metadata.get("generation_fallback")
    unavailable = metadata.get("generation_unavailable")
    bypass = metadata.get("generation_bypass")
    stats = metadata.get("generation_stats") or {}
    draft = _stage(execution, "draft_generation") or {}
    evidence = draft.get("evidence") or {}
    if fallback or unavailable or evidence.get("fallback_used"):
        disposition = "backend_fallback_or_unavailable"
        product_quality_eligible = False
        model_generation_eligible = False
    elif bypass:
        disposition = "deterministic_bypass"
        product_quality_eligible = True
        model_generation_eligible = False
    elif evidence.get("model_call_executed") and int(stats.get("generation_tokens") or 0) > 0:
        disposition = "model_generated"
        product_quality_eligible = True
        model_generation_eligible = True
    else:
        disposition = "unknown"
        product_quality_eligible = False
        model_generation_eligible = False
    return {"disposition": disposition, "product_quality_eligible": product_quality_eligible,
            "model_generation_eligible": model_generation_eligible,
            "generation_path": metadata.get("generation_path"),
            "generation_fallback": fallback, "generation_unavailable": unavailable,
            "generation_bypass": bypass, "draft_generation_evidence": evidence}


def direct_cache_probe(*, messages: list[dict[str, str]], model_id: str,
                       disabled_config_path: Path, enabled_config_path: Path,
                       max_tokens: int, session_id: str) -> dict[str, Any]:
    """Repeat one exact product prompt; only the generator cache setting varies."""

    if not messages or any(not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"}
                           for item in messages):
        raise ValueError("cache probe requires retained exact product prompt messages")
    prompt_hash = canonical_hash(messages)
    # The product turn may already have prepared a draft cache. An isolated
    # role keeps this direct probe cold while preserving one stable namespace.
    scope = cache_scope(session_id, "diagnostic_isolated_parity")
    outputs: list[dict[str, Any]] = []
    enabled_generator: Any | None = None
    for condition, config_path in (("disabled", disabled_config_path), ("cold", enabled_config_path),
                                   ("warm", enabled_config_path)):
        started = time.perf_counter()
        try:
            if condition == "warm":
                generator = enabled_generator
                assert generator is not None
            else:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                generator = _build_mlx_generator(model_id, config, str(config_path))
                generator.max_tokens = max_tokens
                generator.set_cache_scope(scope)
                if condition == "cold":
                    enabled_generator = generator
            answer = str(generator.generate(messages))
            outputs.append({"condition": condition, "status": "completed", "answer": answer,
                            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                            "generation_stats": dict(getattr(generator, "last_generation_stats", {}) or {}),
                            "model_identity": dict(getattr(generator, "model_identity", {}) or {}),
                            "resolved_model_snapshot": str(getattr(generator, "_resolved_model_snapshot", "") or "") or None,
                            "prompt_sha256": prompt_hash, "cache_scope": scope})
        except Exception as exc:
            outputs.append({"condition": condition, "status": "failed", "error_type": type(exc).__name__,
                            "error": str(exc)[:500], "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                            "prompt_sha256": prompt_hash, "cache_scope": scope})
            break
    statuses = {item["condition"]: (item.get("generation_stats") or {}).get("prompt_cache_status") for item in outputs}
    cold_invalid = statuses.get("cold") == "reused_saved_prefix"
    warm_reuse = statuses.get("warm") == "reused_saved_prefix"
    complete = len(outputs) == 3 and all(item["status"] == "completed" for item in outputs) and not cold_invalid
    return {"boundary": "direct_generator_same_exact_product_prompt_not_product_answer_quality",
            "status": "completed" if complete else "failed",
            "failure_reason": "isolated_cold_reused_prefix" if cold_invalid else "condition_failed_or_missing" if not complete else None,
            "prompt_messages": messages, "prompt_sha256": prompt_hash, "outputs": outputs,
            "answer_equal": len({item["answer_sha256"] for item in outputs}) == 1 if complete else None,
            "cache_statuses": statuses,
            "cache_reuse_status": "observed" if warm_reuse else "unavailable_or_not_reused"}


def direct_reference(*, question: str, model_id: str, model_config_path: Path,
                     max_tokens: int) -> dict[str, Any]:
    """A bundled minimal-prompt model reference, deliberately outside the product core."""

    messages = [{"role": "system", "content": DIRECT_REFERENCE_SYSTEM},
                {"role": "user", "content": question}]
    config = yaml.safe_load(model_config_path.read_text(encoding="utf-8"))
    generator = _build_mlx_generator(model_id, config, str(model_config_path))
    generator.max_tokens = max_tokens
    started = time.perf_counter()
    answer = str(generator.generate(messages))
    return {"status": "completed", "turn_index": 0, "question": question,
            "answer": answer, "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "prompt_messages": messages, "prompt_sha256": canonical_hash(messages),
            "generation_stats": dict(getattr(generator, "last_generation_stats", {}) or {}),
            "model_identity": dict(getattr(generator, "model_identity", {}) or {}),
            "resolved_model_snapshot": str(getattr(generator, "_resolved_model_snapshot", "") or "") or None,
            "boundary": "bundled_minimal_prompt_reference_no_retrieval_editor_or_history_not_product_mode_or_causal_attribution"}


def _worker(spec_path: Path, output_path: Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    unit = spec["unit"]
    if unit["kind"] == "direct_reference":
        try:
            row = direct_reference(question=unit["turns"][0], model_id=spec["model_id"],
                                   model_config_path=Path(spec["model_config"]), max_tokens=spec["max_tokens"])
            row["runtime"] = _runtime_receipt()
            _append_jsonl(output_path, row)
            return 0
        except Exception as exc:
            _append_jsonl(output_path, {"status": "failed", "turn_index": 0,
                                          "question": unit["turns"][0], "error_type": type(exc).__name__,
                                          "error": str(exc)[:500]})
            return 1
    store = TraceStore(Path(spec["db_path"]))
    settings = build_settings(
        db_path=Path(spec["db_path"]), artifact_root=Path(spec["artifact_root"]),
        model_config_path=spec["model_config"], default_rag_config=spec["rag_config"],
        network_mode="offline",
    )
    session = store.create_session("Public portable diagnostic", {"trace_storage_enabled": True}, {},
                                   tags=["exposed", "claim_ineligible", "synthetic_or_public"])
    adapter = ObservedSystemBenchmarkAdapter()
    runtime = _runtime_receipt()
    for index, question in enumerate(unit["turns"]):
        started = time.perf_counter()
        try:
            request = AgentExecutionRequest(
                store=store, settings=settings, session_id=session["session_id"], message=question,
                mode="agronomic_rag", model_id=spec["model_id"], rag_config=spec["rag_config"],
                max_tokens=spec["max_tokens"],
                trace_options={"store_prompt_messages": True, "store_retrieved_text": True},
                execution_class="observed_system_execution_nonclaim",
            )
            execution = adapter.execute(request).to_dict()["execution"]
            turn = store.get_turn(execution["turn_id"])
            if turn is None:
                raise RuntimeError("completed execution has no persisted turn")
            trace = turn["trace"]
            metadata = trace.get("metadata") or {}
            row = {
                "status": "completed", "turn_index": index, "question": question,
                "answer": execution["answer"], "turn_id": execution["turn_id"],
                "session_id": session["session_id"], "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "prompt_messages": trace.get("prompt_messages"),
                "answer_stages": metadata.get("answer_stages"),
                "verification": metadata.get("answer_verification"),
                "context_budget": metadata.get("context_budget"),
                "retrieved_docs": trace.get("retrieved_docs"),
                "retrieved_docs_sha256": canonical_hash(trace.get("retrieved_docs") or []),
                "graph_hits": trace.get("graph_hits"),
                "graph_hits_sha256": canonical_hash(trace.get("graph_hits") or []),
                "generation_stats": metadata.get("generation_stats"),
                "generation_fallback": metadata.get("generation_fallback"),
                "generation_unavailable": metadata.get("generation_unavailable"),
                "generation_bypass": metadata.get("generation_bypass"),
                "generation_path": metadata.get("generation_path"),
                "model_execution": model_execution_disposition(metadata, execution),
                "verification_generation_stats": (metadata.get("answer_verification") or {}).get("generation_stats"),
                "model_identity": metadata.get("model_identity"),
                "execution_fingerprints": metadata.get("execution_fingerprints"),
                "stage_receipts": execution.get("stage_receipts"),
                "document_retrieval": _stage(execution, "document_retrieval"),
                "evidence_selection": _stage(execution, "evidence_selection_packing"),
                "private_knowledge": metadata.get("private_knowledge"),
                "runtime": runtime,
            }
            if (metadata.get("private_knowledge") or {}).get("enabled"):
                raise RuntimeError("private knowledge overlay appeared in public diagnostic")
            if unit["kind"] == "cache_cold_warm":
                row["direct_cache_probe"] = direct_cache_probe(
                    messages=row["prompt_messages"], model_id=spec["model_id"],
                    disabled_config_path=Path(spec["model_config"]),
                    enabled_config_path=Path(spec["cache_model_config"]),
                    max_tokens=spec["max_tokens"], session_id=session["session_id"],
                )
                if row["direct_cache_probe"]["status"] != "completed":
                    row["status"] = "failed"
        except Exception as exc:
            row = {"status": "failed", "turn_index": index, "question": question,
                   "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                   "error_type": type(exc).__name__, "error": str(exc)[:500]}
            _append_jsonl(output_path, row)
            return 1
        _append_jsonl(output_path, row)
    return 0


def _run_parent(args: argparse.Namespace) -> int:
    cases_path = args.cases.resolve()
    model_path = args.model_config.resolve()
    output_dir = args.output_dir.resolve()
    cases = load_cases(cases_path)
    if args.max_tokens <= 0 or args.cell_timeout_seconds <= 0:
        raise ValueError("max tokens and cell timeout must be positive")
    arms = {arm: path.resolve() for arm, path in DEFAULT_ARMS.items()}
    for arm, path in arms.items():
        if not path.is_file():
            raise ValueError(f"{arm} RAG config missing: {path}")
    model_off = model_config_for_cell(model_path, cache_enabled=False)
    model_on = model_config_for_cell(model_path, cache_enabled=True)
    model_id = str(model_off.get("serving_model_id") or model_off.get("model_id") or "")
    if not model_id:
        raise ValueError("model config has no serving model ID")
    if args.model_id and args.model_id != model_id:
        raise ValueError("requested model ID differs from pinned serving model")
    if args.cache_case_id and not args.include_cache:
        raise ValueError("--cache-case-id requires --include-cache")
    cache_case_id = (args.cache_case_id or str(cases[0].get("case_id") or cases[0]["id"])) if args.include_cache else None
    units = build_units(cases, continuity=args.include_continuity,
                        long_context=args.include_long_context, cache_case_id=cache_case_id,
                        direct_reference=args.include_direct_reference)
    run_id = args.run_id
    if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise ValueError("--run-id must contain only letters, numbers, hyphen, underscore")
    manifest = {
        "schema_version": SCHEMA, "run_id": run_id, "claim_eligible": False,
        "case_exposure": "exposed_development_nonsealed", "quality_judgment": "unavailable",
        "cases_path": str(cases_path), "cases_sha256": sha256_file(cases_path),
        "model_config_path": str(model_path), "model_config_sha256": sha256_file(model_path),
        "model_id": model_id, "model_revision": model_off["model_revision"],
        "source": _source_receipt(),
        "max_tokens": args.max_tokens, "cell_timeout_seconds": args.cell_timeout_seconds,
        "rag_configs": {arm: {"path": str(path), "sha256": sha256_file(path),
                               "effective_sha256": canonical_hash(public_rag_config(path)),
                               "artifact_sha256": rag_artifact_receipt(public_rag_config(path))}
                        for arm, path in arms.items()},
        "runner_sha256": sha256_file(Path(__file__)),
        "units": units,
        "cache_boundary": "one product turn captures exact prompt; direct generator disabled/cold/warm repeats those identical message bytes with same session and draft role scope",
        "direct_reference_boundary": "bundled fixed minimal agronomy system prompt and pinned generator, no retrieval/editor/history; not product mode or causal attribution",
        "direct_reference_system_prompt": DIRECT_REFERENCE_SYSTEM,
        "private_overlay_policy": "disabled_in_effective_configs_and_environment",
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    manifest_path = output_dir / "manifest.json"
    if args.resume:
        if not manifest_path.is_file() or json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("resume manifest differs from current inputs or runner")
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"output directory is nonempty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.execute:
        print(json.dumps({"run_id": run_id, "units": len(units), "manifest": str(manifest_path), "executed": False}))
        return 0
    effective_dir = output_dir / "effective_configs"
    effective_dir.mkdir(exist_ok=True)
    for arm, source in arms.items():
        (effective_dir / f"rag_{arm}.yaml").write_text(yaml.safe_dump(public_rag_config(source), sort_keys=False), encoding="utf-8")
    for enabled, name in ((False, "disabled"), (True, "enabled")):
        (effective_dir / f"model_{name}.yaml").write_text(yaml.safe_dump(model_config_for_cell(model_path, cache_enabled=enabled), sort_keys=False), encoding="utf-8")
    ledger_path = output_dir / "cells.jsonl"
    completed = {json.loads(line)["unit_id"] for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()} if ledger_path.exists() else set()
    work_dir = output_dir / "work"
    work_dir.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] = "0"
    environment.pop("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", None)
    environment["AGRONOMY_AGENT_MODEL_BACKEND"] = "mlx"
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["PYTHONPATH"] = str(ROOT / "src")
    prior_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()] if ledger_path.exists() else []
    failures = sum(row.get("status") != "completed" for row in prior_rows)
    if len(completed) < len(units) and not _ensure_preflight(
        output_dir=output_dir, model_config=effective_dir / "model_disabled.yaml",
        model_id=model_id, environment=environment, timeout_seconds=args.cell_timeout_seconds,
        manifest_sha256=manifest["manifest_sha256"],
    ):
        return 1
    for position, unit in enumerate(units):
        if unit["unit_id"] in completed:
            continue
        # A child can finish after writing worker.jsonl while the parent is
        # interrupted before committing cells.jsonl. Resume must keep those
        # orphan bytes and execute in a fresh attempt directory.
        attempt = 1
        while (work_dir / f"{position:04d}-attempt-{attempt:06d}").exists():
            attempt += 1
        cell_dir = work_dir / f"{position:04d}-attempt-{attempt:06d}"
        cell_dir.mkdir(exist_ok=False)
        spec = {"unit": unit, "db_path": str(cell_dir / "traces.sqlite3"),
                "artifact_root": str(cell_dir / "artifacts"),
                "model_config": str(effective_dir / "model_disabled.yaml"),
                "cache_model_config": str(effective_dir / "model_enabled.yaml") if unit["cache_enabled"] else None,
                "rag_config": str(effective_dir / f"rag_{unit['arm']}.yaml") if unit["arm"] in arms else None,
                "model_id": model_id, "max_tokens": args.max_tokens}
        spec_path = cell_dir / "spec.json"
        spec_path.write_text(json.dumps(spec, sort_keys=True) + "\n", encoding="utf-8")
        worker_path = cell_dir / "worker.jsonl"
        started = time.perf_counter()
        try:
            process = subprocess.run([sys.executable, str(Path(__file__)), "--worker-spec", str(spec_path),
                                      "--worker-output", str(worker_path)], cwd=ROOT, env=environment,
                                     capture_output=True, text=True, timeout=args.cell_timeout_seconds, check=False)
            exit_code: int | None = process.returncode
            stderr_tail = process.stderr[-2000:]
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            stderr_tail = str(exc.stderr or b"")[-2000:]
            timed_out = True
        observed = [json.loads(line) for line in worker_path.read_text(encoding="utf-8").splitlines() if line.strip()] if worker_path.exists() else []
        status = "completed" if exit_code == 0 and len(observed) == len(unit["turns"]) and all(row.get("status") == "completed" for row in observed) else ("timed_out" if timed_out else "failed")
        row = {"schema_version": SCHEMA, "run_id": run_id, "unit_id": unit["unit_id"],
               "attempt": attempt, "attempt_dir": str(cell_dir),
               "kind": unit["kind"], "arm": unit["arm"], "case_id": unit["case_id"],
               "cache_enabled": unit["cache_enabled"], "status": status,
               "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
               "exit_code": exit_code, "stderr_tail": stderr_tail if status != "completed" else None,
               "expected_turns": len(unit["turns"]), "observed_turns": len(observed), "turns": observed,
               "recorded_at": datetime.now(timezone.utc).isoformat()}
        _append_jsonl(ledger_path, row)
        print(json.dumps({"unit_id": unit["unit_id"], "status": status, "observed_turns": len(observed)}), flush=True)
        failures += status != "completed"
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--model-config", type=Path, default=ROOT / "configs/model.yaml")
    parser.add_argument("--model-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--max-tokens", type=int, default=320)
    parser.add_argument("--cell-timeout-seconds", type=float, default=600)
    parser.add_argument("--include-continuity", action="store_true")
    parser.add_argument("--include-long-context", action="store_true")
    parser.add_argument("--include-cache", action="store_true")
    parser.add_argument("--include-direct-reference", action="store_true")
    parser.add_argument("--cache-case-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--preflight-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--preflight-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_spec:
        if not args.worker_output:
            parser.error("worker output is required")
        return _worker(args.worker_spec, args.worker_output)
    if args.preflight_spec:
        if not args.preflight_output:
            parser.error("preflight output is required")
        return _preflight_child(args.preflight_spec, args.preflight_output)
    if not args.output_dir or not args.run_id:
        parser.error("--output-dir and --run-id are required")
    try:
        return _run_parent(args)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
