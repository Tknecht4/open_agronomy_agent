#!/usr/bin/env python3
"""Exercise a relocated Mac app backend without development runtimes on PATH."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _backend_json(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "phase" in row:
            return row
    raise ValueError(f"backend emitted no status JSON: {output[-400:]}")


def _clean_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
        and not key.startswith(("HF_", "AGRONOMY_AGENT_"))
    }
    environment["PATH"] = "/usr/bin:/bin"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    opener: urllib.request.OpenerDirector,
    origin: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    csrf: str | None = None,
    timeout: int = 15,
) -> tuple[int, bytes]:
    headers: dict[str, str] = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Origin": origin})
        if csrf:
            headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(origin + path, data=data, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _run_setup_command(
    backend: Path,
    command: str,
    *,
    runtime: Path,
    state: Path,
    model_cache: Path | None,
    environment: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    args = [
        str(backend), command,
        "--runtime-root", str(runtime),
        "--state-root", str(state),
        "--require-bundle-manifest",
    ]
    if model_cache is not None:
        args += ["--model-cache", str(model_cache)]
    completed = subprocess.run(
        args, env=environment, capture_output=True, text=True, timeout=timeout, check=False
    )
    row = _backend_json(completed.stdout + "\n" + completed.stderr)
    if completed.returncode != 0 or row.get("phase") == "error":
        raise RuntimeError(f"{command} failed: {row.get('detail') or row}")
    return row


def smoke(
    app: Path, state: Path, *, report: Path, model_cache: Path | None = None
) -> dict[str, Any]:
    app = app.resolve(strict=True)
    backend = app / "Contents/Helpers/OpenAgronomyBackend/OpenAgronomyBackend"
    runtime = app / "Contents/Resources/runtime"
    if not backend.is_file() or not (runtime / "frontend/dist/index.html").is_file():
        raise ValueError("app is missing its backend executable or production UI")
    if state.exists() and any(state.iterdir()):
        raise ValueError("smoke state must be absent or empty")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if model_cache is not None and not model_cache.is_absolute():
        raise ValueError("model cache override must be absolute")
    environment = _clean_environment()
    initial = _run_setup_command(
        backend, "status", runtime=runtime, state=state,
        model_cache=model_cache, environment=environment, timeout=180,
    )
    if initial.get("phase") != "setup_required":
        raise ValueError("fresh app state unexpectedly contained a model receipt")
    installed = _run_setup_command(
        backend, "install-model", runtime=runtime, state=state,
        model_cache=model_cache, environment=environment, timeout=1800,
    )
    if installed.get("phase") != "ready":
        raise ValueError("model installation did not reach ready")
    ready = _run_setup_command(
        backend, "status", runtime=runtime, state=state,
        model_cache=model_cache, environment=environment, timeout=180,
    )
    if ready.get("phase") != "ready" or ready.get("revision") != installed.get("revision"):
        raise ValueError("installed model receipt did not verify on restart")

    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    token = secrets.token_urlsafe(32)
    secret = secrets.token_urlsafe(48)
    environment["AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN"] = token
    environment["AGRONOMY_AGENT_DESKTOP_SESSION_SECRET"] = secret
    args = [
        str(backend), "serve", "--runtime-root", str(runtime),
        "--state-root", str(state), "--port", str(port),
        "--require-bundle-manifest",
    ]
    if model_cache is not None:
        args += ["--model-cache", str(model_cache)]
    log_path = state / "backend-smoke.log"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, env=environment, stdout=log, stderr=log)
        try:
            for _ in range(180):
                if process.poll() is not None:
                    raise RuntimeError(f"backend exited before readiness: {log_path}")
                try:
                    health_status, body = _request(opener, origin, "/api/health", timeout=2)
                    health = json.loads(body)
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.5)
                    continue
                launch_id = (health.get("local_pairing") or {}).get("launch_id")
                if health_status == 200 and health.get("status") == "ok" and launch_id == hashlib.sha256(token.encode()).hexdigest():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("backend readiness timed out")

            anonymous, _ = _request(opener, origin, "/auth/me")
            if anonymous != 401:
                raise ValueError(f"unauthenticated desktop request returned {anonymous}")
            ui_status, ui = _request(opener, origin, "/")
            if ui_status != 200 or b"<div id=\"root\"" not in ui:
                raise ValueError("installed app did not serve the production UI")
            paired, pair_body = _request(
                opener, origin, "/auth/local-pair", payload={"token": token}
            )
            if paired != 200:
                raise ValueError(f"desktop browser pairing returned {paired}")
            csrf = str(json.loads(pair_body)["csrf_token"])
            replay, _ = _request(opener, origin, "/auth/local-pair", payload={"token": token})
            if replay != 409:
                raise ValueError(f"pairing replay returned {replay}")
            session_status, session_body = _request(
                opener, origin, "/api/sessions",
                payload={"title": "Mac app installed smoke", "consent": {}}, csrf=csrf,
            )
            if session_status != 200:
                raise ValueError(f"authenticated session creation returned {session_status}")
            session_id = str(json.loads(session_body)["session_id"])
            turn_status, turn_body = _request(
                opener, origin, f"/api/sessions/{session_id}/turns",
                payload={
                    "message": "Explain the difference between soil texture and soil structure using the available offline evidence.",
                    "mode": "agronomic_rag",
                    "max_tokens": 220,
                },
                csrf=csrf,
                timeout=360,
            )
            if turn_status != 200:
                raise ValueError(f"model-backed turn returned {turn_status}: {turn_body[:400]!r}")
            turn = json.loads(turn_body)["turn"]
            identity = turn["system_state"]["model_identity"]
            generated = (turn["trace"]["metadata"].get("generation_stats") or {}).get("generation_tokens")
            retrieved = turn["trace"].get("retrieved_docs") or []
            if (
                identity.get("backend") != "mlx_local"
                or identity.get("configured_model_revision") != installed["revision"]
                or not isinstance(generated, int) or generated <= 0
                or not retrieved
            ):
                raise ValueError("installed app did not produce a pinned, source-bound MLX answer")
            result = {
                "schema_version": "open_agronomy_agent.macos_app_smoke.v1",
                "status": "pass",
                "model_revision": installed["revision"],
                "model_file_count": installed["file_count"],
                "runtime_manifest_sha256": hashlib.sha256(
                    (app / "Contents/Resources/runtime-manifest.json").read_bytes()
                ).hexdigest(),
                "ui_status": ui_status,
                "pre_pair_status": anonymous,
                "pair_status": paired,
                "replay_status": replay,
                "turn_status": turn_status,
                "answer_sha256": hashlib.sha256(turn["answer"].encode()).hexdigest(),
                "generation_tokens": generated,
                "retrieved_document_count": len(retrieved),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    try:
        _request(opener, origin, "/api/health", timeout=1)
    except OSError:
        result["listener_stopped"] = True
    else:
        raise ValueError("backend listener remained after owned process stopped")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path)
    args = parser.parse_args()
    try:
        result = smoke(args.app, args.state_root, report=args.report, model_cache=args.model_cache)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        failure = {
            "schema_version": "open_agronomy_agent.macos_app_smoke.v1",
            "status": "fail",
            "detail": str(exc),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
