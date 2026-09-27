#!/usr/bin/env python3
"""Profile the local workspace API and mock production core with synthetic state.

This is a non-claim diagnostic. It never calls a model or public provider, uses
only a fresh SQLite database in the output directory, and retains failed cells.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import math
import platform
import pstats
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agronomy_agent.execution_core import AgentExecutionRequest  # noqa: E402
from agronomy_agent.server.app import create_app  # noqa: E402
from agronomy_agent.server.services.chat_service import execute_agent_request  # noqa: E402
from agronomy_agent.server.settings import build_settings  # noqa: E402
from agronomy_agent.server.storage.db import TraceStore  # noqa: E402
from agronomy_agent.server.trace_timer import TraceProfiler  # noqa: E402


OWNER = {"X-Agronomy-User-Email": "synthetic-profile@example.test"}
QUESTION = "Convert a fertilizer rate of 100 lb/ac to kg/ha."


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)


def summarize(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "min_ms": round(min(values), 3) if values else None,
        "median_ms": round(statistics.median(values), 3) if values else None,
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else None,
    }


def measured_call(call: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter_ns()
    result = call()
    return (time.perf_counter_ns() - started) / 1_000_000, result


def run_cell(
    receipt: dict[str, Any],
    name: str,
    call: Callable[[], Any],
    *,
    repeats: int = 1,
    profile: bool = False,
) -> Any:
    values: list[float] = []
    result: Any = None
    profiler = cProfile.Profile() if profile else None
    failure: dict[str, Any] | None = None
    for index in range(repeats):
        try:
            if profiler is not None:
                profiler.enable()
            elapsed, result = measured_call(call)
            values.append(elapsed)
        except Exception as exc:  # retain the failed cell and move on
            failure = {
                "type": type(exc).__name__,
                "message": str(exc)[:500],
                "sample_index": index,
                "traceback": traceback.format_exc(limit=5),
            }
            break
        finally:
            if profiler is not None:
                profiler.disable()
    cell: dict[str, Any] = {
        "status": "failed" if failure else "completed",
        "timing": summarize(values),
        "requested_samples": repeats,
        "failure": failure,
    }
    if profiler is not None:
        buffer = io.StringIO()
        pstats.Stats(profiler, stream=buffer).strip_dirs().sort_stats("cumulative").print_stats(18)
        cell["cprofile_top_cumulative"] = buffer.getvalue()
    receipt["cells"][name] = cell
    write_receipt(receipt)
    return result


def write_receipt(receipt: dict[str, Any]) -> None:
    output = Path(receipt["_output_file"])
    public = {key: value for key, value in receipt.items() if not key.startswith("_")}
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)


def expect_json(client: TestClient, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url}: HTTP {response.status_code}: {response.text[:250]}")
    return response.json()


def seed_history(store: TraceStore, *, owner_id: str, field_id: str, sessions: int, turns: int) -> None:
    for session_index in range(sessions):
        current_field = field_id if session_index == 0 else f"synthetic-other-{session_index}"
        session = store.create_session(
            f"Synthetic session {session_index}",
            {},
            {"field_context_id": current_field, "extra": {"_session_owner_user_id": owner_id}},
        )
        for turn_index in range(turns):
            trace = {
                "metadata": {"field_lineage": {"field_context_id": current_field}},
                "route": {"question_type": "synthetic"},
                "retrieved_docs": [],
                "graph_hits": [],
                "tool_invocations": [],
            }
            turn_id = store.create_turn(
                session["session_id"],
                f"Synthetic question {session_index}-{turn_index}",
                "Synthetic answer for local timing only.",
                parent_turn_id=None,
                system_state={"mode": "mock"},
                trace=trace,
                objectives={},
                event_stream=False,
            )
            if session_index == 0 and turn_index == 0:
                store.set_feedback(
                    session["session_id"],
                    turn_id,
                    {"rating": 1, "answer_status": "reviewed"},
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--warm-repeats", type=int, default=5)
    parser.add_argument("--sessions", type=int, default=20)
    parser.add_argument("--turns-per-session", type=int, default=8)
    args = parser.parse_args()
    if min(args.warm_repeats, args.sessions, args.turns_per_session) < 1:
        parser.error("warm repeats, sessions, and turns per session must be positive")
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error("output directory must be new or empty; existing evidence is never overwritten")
    output_dir.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.workspace_backend_profile.v1",
        "status": "running",
        "claim_eligible": False,
        "network_mode": "offline",
        "model": "mock_only",
        "input": {
            "question_sha256": hashlib.sha256(QUESTION.encode()).hexdigest(),
            "sessions": args.sessions,
            "turns_per_session": args.turns_per_session,
            "warm_repeats": args.warm_repeats,
        },
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "source_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                ROOT / "scripts/profile_workspace_backend.py",
                ROOT / "src/agronomy_agent/server/app.py",
                ROOT / "src/agronomy_agent/server/services/chat_service.py",
                ROOT / "src/agronomy_agent/server/storage/db.py",
                ROOT / "src/agronomy_agent/execution_core.py",
                ROOT / "configs/model.yaml",
                ROOT / "configs/rag.yaml",
                ROOT / "configs/runtime_profiles.json",
            )
        },
        "cells": {},
        "_output_file": str(output_dir / "receipt.json"),
    }
    write_receipt(receipt)
    settings = build_settings(
        db_path=output_dir / "synthetic.sqlite3",
        artifact_root=output_dir / "artifacts",
        network_mode="offline",
        allow_model_id_override=True,
        structured_access_logs=False,
    )
    app = run_cell(receipt, "app_create_cold", lambda: create_app(settings), profile=True)
    if app is None:
        receipt["status"] = "failed"
        write_receipt(receipt)
        return 1
    store: TraceStore = app.state.trace_store
    with TestClient(app) as client:
        for name, method, url in (
            ("health", "GET", "/api/health"),
            ("configs", "GET", "/api/configs"),
            ("geo_layers", "GET", "/api/geo/layers"),
            ("fields_list", "GET", "/api/demo/fields"),
            ("sessions_list", "GET", "/api/sessions"),
        ):
            call = lambda method=method, url=url: expect_json(client, method, url, headers=OWNER)
            run_cell(receipt, f"{name}_cold", call)
            run_cell(receipt, f"{name}_warm", call, repeats=args.warm_repeats, profile=True)

        created = run_cell(
            receipt,
            "field_create",
            lambda: expect_json(
                client,
                "POST",
                "/api/demo/fields",
                headers=OWNER,
                json={
                    "name": "Synthetic North Quarter",
                    "field": {"crop": "canola", "region": "Leduc", "jurisdiction": "Alberta"},
                    "geometry": {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}},
                },
            ),
        )
        if created:
            field_id = created["field"]["field_context_id"]
            owner_id = created["storage"]["user_id"]
            run_cell(
                receipt,
                "history_seed",
                lambda: seed_history(
                    store,
                    owner_id=owner_id,
                    field_id=field_id,
                    sessions=args.sessions,
                    turns=args.turns_per_session,
                ),
            )
            history_url = f"/api/demo/fields/{field_id}/history"
            history_call = lambda: expect_json(client, "GET", history_url, headers=OWNER)
            full_turn_loads = 0
            original_get_turn = store.get_turn

            def counted_get_turn(turn_id: str) -> Any:
                nonlocal full_turn_loads
                full_turn_loads += 1
                return original_get_turn(turn_id)

            store.get_turn = counted_get_turn
            run_cell(receipt, "field_history_cold", history_call, profile=True)
            receipt["cells"]["field_history_cold"]["full_turn_loads"] = full_turn_loads
            full_turn_loads = 0
            run_cell(receipt, "field_history_warm", history_call, repeats=args.warm_repeats, profile=True)
            receipt["cells"]["field_history_warm"]["full_turn_loads"] = full_turn_loads
            store.get_turn = original_get_turn
            write_receipt(receipt)
            run_cell(
                receipt,
                "sessions_list_seeded_warm",
                lambda: expect_json(client, "GET", "/api/sessions", headers=OWNER),
                repeats=args.warm_repeats,
                profile=True,
            )

        session = store.create_session("Synthetic core profile", {}, {})
        stage_profiler = TraceProfiler()
        request = AgentExecutionRequest(
            store=store,
            settings=settings,
            session_id=session["session_id"],
            message=QUESTION,
            mode="mock",
            model_id="mock",
            rag_config="configs/rag.yaml",
            max_tokens=100,
            trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
            profiler=stage_profiler,
            execution_class="observed_system_execution_nonclaim",
        )
        run_cell(receipt, "core_mock_cold", lambda: execute_agent_request(request), profile=True)
        receipt["core_stage_spans"] = [
            {"stage": span.stage, "duration_ms": span.duration_ms, "status": span.status}
            for span in stage_profiler.spans
        ]
        write_receipt(receipt)
        def warm_core() -> Any:
            warm_request = AgentExecutionRequest(
                store=store,
                settings=settings,
                session_id=session["session_id"],
                message=QUESTION,
                mode="mock",
                model_id="mock",
                rag_config="configs/rag.yaml",
                max_tokens=100,
                trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
                profiler=TraceProfiler(),
                execution_class="observed_system_execution_nonclaim",
            )
            return execute_agent_request(warm_request)

        run_cell(receipt, "core_mock_warm", warm_core, repeats=args.warm_repeats, profile=True)
    receipt["status"] = (
        "completed" if all(cell["status"] == "completed" for cell in receipt["cells"].values()) else "completed_with_failures"
    )
    write_receipt(receipt)
    print(json.dumps({"status": receipt["status"], "receipt": str(output_dir / "receipt.json")}))
    return 0 if receipt["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
