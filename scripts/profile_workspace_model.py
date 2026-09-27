#!/usr/bin/env python3
"""Profile two local pinned-model production-core turns with no provider egress.

Requires --execute-local-pinned. The output is a non-claim timing receipt with
synthetic questions and no answer text. HF_HUB_OFFLINE=1 is forced in process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time
import traceback
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"

from huggingface_hub import snapshot_download  # noqa: E402
import yaml  # noqa: E402

from agronomy_agent.execution_core import AgentExecutionRequest  # noqa: E402
from agronomy_agent.server.app import create_app  # noqa: E402
from agronomy_agent.server.settings import build_settings  # noqa: E402
from agronomy_agent.server.services.chat_service import execute_agent_request  # noqa: E402
from agronomy_agent.server.trace_timer import TraceProfiler  # noqa: E402


QUESTIONS = (
    "Explain how crop rotation can affect soil organic matter, and what a field test would still need to establish.",
    "How might cover crop residue change erosion risk in a Prairie wheat field, and what remains uncertain?",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_receipt(receipt: dict[str, Any], path: Path) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def memory_sample() -> dict[str, float | None]:
    result: dict[str, float | None] = {"process_peak_rss_mib": None, "metal_active_mib": None, "metal_peak_mib": None}
    try:
        # macOS ru_maxrss is bytes; Linux uses KiB. This script targets the local Mac.
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["process_peak_rss_mib"] = round(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024, 2)
    except Exception:
        pass
    try:
        import mlx.core as mx

        result["metal_active_mib"] = round(mx.metal.get_active_memory() / (1024 * 1024), 2)
        result["metal_peak_mib"] = round(mx.metal.get_peak_memory() / (1024 * 1024), 2)
    except Exception:
        pass
    return result


def generation_counts(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {"draft": None, "verification": None}
    verification = metadata.get("answer_verification")
    verification_stats = verification.get("generation_stats") if isinstance(verification, dict) else None

    def selected(stats: Any) -> dict[str, Any] | None:
        if not isinstance(stats, dict):
            return None
        return {key: stats.get(key) for key in ("prompt_tokens", "generation_tokens", "prompt_tps", "generation_tps")}

    return {
        "draft": selected(metadata.get("generation_stats")),
        "verification": selected(verification_stats),
    }


def supervise_profile(command: list[str], path: Path, deadline_seconds: float) -> int:
    """Bound the worker even if native work blocks Python signal handling."""
    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=deadline_seconds)
    except subprocess.TimeoutExpired:
        # The worker owns this process group; preserve other local model servers.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt = {
                "schema_version": "open_agronomy_agent.workspace_model_profile.v1",
                "claim_eligible": False, "network_mode": "offline",
                "private_knowledge_mode": "disabled", "cells": [],
            }
        failure = {"type": "TimeoutError", "message": f"profile worker exceeded {deadline_seconds} seconds"}
        receipt["status"] = "failed"
        receipt["failure"] = failure
        for cell in receipt.get("cells", []):
            if cell.get("status") == "running":
                cell["status"] = "interrupted"
                cell["failure"] = failure
        path.parent.mkdir(parents=True, exist_ok=True)
        write_receipt(receipt, path)
        print(json.dumps({"status": "failed", "receipt": str(path)}))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-local-pinned", action="store_true", help="Required explicit opt-in for Metal model generation")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=120)
    parser.add_argument("--deadline-seconds", type=int, default=900)
    parser.add_argument("--profile-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    # Profiling must not inherit a machine-local private retrieval overlay.
    os.environ["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] = "disabled"
    os.environ.pop("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", None)
    if not args.execute_local_pinned:
        parser.error("--execute-local-pinned is required")
    if args.max_tokens < 1 or args.max_tokens > 160:
        parser.error("max tokens must be between 1 and 160")
    if args.deadline_seconds < 1 or args.deadline_seconds > 900:
        parser.error("deadline must be between 1 and 900 seconds")
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error("output directory must be new or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "receipt.json"
    if not args.profile_worker:
        command = [sys.executable, str(Path(__file__).resolve()), "--execute-local-pinned",
                   "--output-dir", str(output_dir), "--max-tokens", str(args.max_tokens),
                   "--deadline-seconds", str(args.deadline_seconds), "--profile-worker"]
        return supervise_profile(command, path, args.deadline_seconds)
    model_config = yaml.safe_load((ROOT / "configs/model.yaml").read_text(encoding="utf-8"))
    model_id = str(model_config["serving_model_id"])
    revision = str(model_config["model_revision"])
    receipt: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.workspace_model_profile.v1",
        "status": "running",
        "claim_eligible": False,
        "network_mode": "offline",
        "private_knowledge_mode": "disabled",
        "model_id": model_id,
        "model_revision": revision,
        "max_tokens": args.max_tokens,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "source_sha256": {
            str(source.relative_to(ROOT)): digest(source)
            for source in (
                ROOT / "scripts/profile_workspace_model.py",
                ROOT / "src/agronomy_agent/server/app.py",
                ROOT / "src/agronomy_agent/server/services/chat_service.py",
                ROOT / "src/agronomy_agent/agent.py",
                ROOT / "configs/model.yaml",
                ROOT / "configs/rag.yaml",
            )
        },
        "cells": [],
    }
    write_receipt(receipt, path)

    deadline_expired = False

    def check_deadline() -> None:
        if deadline_expired:
            raise TimeoutError(f"local profiling exceeded {args.deadline_seconds} seconds")

    def expired(_signal: int, _frame: Any) -> None:
        nonlocal deadline_expired
        deadline_expired = True
        raise TimeoutError(f"local profiling exceeded {args.deadline_seconds} seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.deadline_seconds)
    try:
        started = time.perf_counter()
        snapshot_download(repo_id=model_id, revision=revision, local_files_only=True)
        receipt["snapshot_preflight"] = {"status": "available", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
        write_receipt(receipt, path)

        settings = build_settings(
            db_path=output_dir / "synthetic.sqlite3",
            artifact_root=output_dir / "artifacts",
            model_config_path="configs/model.yaml",
            default_rag_config="configs/rag.yaml",
            network_mode="offline",
            structured_access_logs=False,
        )
        started = time.perf_counter()
        app = create_app(settings)
        receipt["app_create_cold_ms"] = round((time.perf_counter() - started) * 1000, 3)
        store = app.state.trace_store
        write_receipt(receipt, path)

        import mlx.core as mx

        receipt["metal_device"] = str(mx.default_device())
        for index, question in enumerate(QUESTIONS):
            check_deadline()
            cell: dict[str, Any] = {
                "index": index,
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                "status": "running",
                "stages": [],
            }
            receipt["cells"].append(cell)
            write_receipt(receipt, path)
            session = store.create_session(f"Synthetic model profile {index}", {}, {})
            profiler = TraceProfiler()
            request = AgentExecutionRequest(
                store=store,
                settings=settings,
                session_id=session["session_id"],
                message=question,
                mode="agronomic_rag",
                model_id=model_id,
                rag_config="configs/rag.yaml",
                max_tokens=args.max_tokens,
                trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
                execution_class="observed_system_execution_nonclaim",
                profiler=profiler,
            )
            try:
                mx.metal.reset_peak_memory()
                started = time.perf_counter()
                result = execute_agent_request(request)
                check_deadline()
                cell["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
                cell["status"] = "completed"
                cell["answer_sha256"] = hashlib.sha256(result.answer.encode()).hexdigest()
                cell["answer_chars"] = len(result.answer)
                cell["stage_receipt_count"] = len(result.stage_receipts)
                trace = result.turn.get("trace") if isinstance(result.turn.get("trace"), dict) else {}
                cell["generation_counts"] = generation_counts(trace.get("metadata"))
                cell["memory"] = memory_sample()
            except Exception as exc:
                cell["status"] = "failed"
                cell["failure"] = {"type": type(exc).__name__, "message": str(exc)[:500], "traceback": traceback.format_exc(limit=6)}
                cell["memory"] = memory_sample()
                if deadline_expired:
                    raise
            finally:
                cell["stages"] = [
                    {"stage": span.stage, "duration_ms": span.duration_ms, "status": span.status,
                     "input_size": span.input_size, "output_size": span.output_size,
                     "token_estimate_in": span.token_estimate_in, "token_estimate_out": span.token_estimate_out}
                    for span in profiler.spans
                ]
                write_receipt(receipt, path)
        receipt["status"] = "completed" if all(cell["status"] == "completed" for cell in receipt["cells"]) else "completed_with_failures"
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["failure"] = {"type": type(exc).__name__, "message": str(exc)[:500], "traceback": traceback.format_exc(limit=6)}
    finally:
        signal.alarm(0)
        write_receipt(receipt, path)
    print(json.dumps({"status": receipt["status"], "receipt": str(path)}))
    return 0 if receipt["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
