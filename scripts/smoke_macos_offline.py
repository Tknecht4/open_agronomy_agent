#!/usr/bin/env python3
"""Prove packaged local inference with public TCP/UDP egress denied by macOS."""

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

from scripts.smoke_macos_app import _clean_environment, _free_port, _request, _startup_summary


SANDBOX_PROFILE = (
    '(version 1)(allow default)'
    '(deny network-outbound (require-not (remote ip "localhost:*")))'
)


def _prove_public_egress_blocked(environment: dict[str, str]) -> None:
    probe = (
        "import socket,sys; "
        "\ntry: socket.create_connection(('203.0.113.1',80),timeout=2)"
        "\nexcept PermissionError as exc: sys.exit(0 if exc.errno == 1 else 2)"
        "\nexcept OSError: sys.exit(3)"
        "\nelse: sys.exit(4)"
    )
    completed = subprocess.run(
        ["sandbox-exec", "-p", SANDBOX_PROFILE, sys.executable, "-c", probe],
        env=environment, capture_output=True, text=True, check=False, timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"public egress denial was not observed: probe code {completed.returncode}")


def smoke(app: Path, state: Path, report: Path) -> dict[str, Any]:
    app = app.resolve(strict=True)
    backend = app / "Contents/Helpers/OpenAgronomyBackend.app/Contents/MacOS/OpenAgronomyBackend"
    runtime = app / "Contents/Resources/runtime"
    if not backend.is_file() or not state.is_dir():
        raise ValueError("packaged backend or provisioned state is missing")
    environment = _clean_environment()
    _prove_public_egress_blocked(environment)
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    token = secrets.token_urlsafe(32)
    environment["AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN"] = token
    environment["AGRONOMY_AGENT_DESKTOP_SESSION_SECRET"] = secrets.token_urlsafe(48)
    command = [
        "sandbox-exec", "-p", SANDBOX_PROFILE,
        str(backend), "serve", "--runtime-root", str(runtime),
        "--state-root", str(state), "--require-bundle-manifest",
        "--network-mode", "offline", "--port", str(port),
    ]
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    log_path = state / "offline-backend-smoke.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        "sandboxed backend exited before readiness: "
                        + json.dumps({"exit_code": process.returncode, "startup": _startup_summary(state)})
                    )
                try:
                    status, body = _request(opener, origin, "/api/health", timeout=2)
                    health = json.loads(body)
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.5)
                    continue
                if (
                    status == 200 and health.get("status") == "ok"
                    and health.get("network", {}).get("mode") == "offline"
                    and health.get("network", {}).get("external_calls_allowed") is False
                    and health.get("local_pairing", {}).get("launch_id")
                    == hashlib.sha256(token.encode()).hexdigest()
                ):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("sandboxed backend did not become offline-ready")
            paired, pair_body = _request(
                opener, origin, "/auth/local-pair", payload={"token": token}
            )
            if paired != 200:
                raise ValueError(f"offline pairing returned {paired}")
            csrf = str(json.loads(pair_body)["csrf_token"])
            session_status, session_body = _request(
                opener, origin, "/api/sessions",
                payload={"title": "Mac app offline smoke", "consent": {}}, csrf=csrf,
            )
            if session_status != 200:
                raise ValueError(f"offline session returned {session_status}")
            session_id = str(json.loads(session_body)["session_id"])
            turn_status, turn_body = _request(
                opener, origin, f"/api/sessions/{session_id}/turns",
                payload={
                    "message": "Explain the difference between soil texture and soil structure using installed offline evidence.",
                    "mode": "agronomic_rag", "max_tokens": 220,
                },
                csrf=csrf, timeout=360,
            )
            if turn_status != 200:
                raise ValueError(f"offline model-backed turn returned {turn_status}")
            turn = json.loads(turn_body)["turn"]
            identity = turn["system_state"]["model_identity"]
            generated = (turn["trace"]["metadata"].get("generation_stats") or {}).get("generation_tokens")
            retrieved = turn["trace"].get("retrieved_docs") or []
            if (
                identity.get("backend") != "mlx_local"
                or identity.get("configured_model_revision")
                != "238767527555cb75a05732a84dff5d6ba0dd6809"
                or not isinstance(generated, int) or generated <= 0 or not retrieved
            ):
                raise ValueError("offline answer lacks pinned local model or installed sources")
            result = {
                "schema_version": "open_agronomy_agent.macos_offline_smoke.v1",
                "status": "pass",
                "os_public_egress_denied": True,
                "loopback_api_ready": True,
                "network_mode": "offline",
                "turn_status": turn_status,
                "model_revision": identity["configured_model_revision"],
                "generation_tokens": generated,
                "retrieved_document_count": len(retrieved),
                "answer_sha256": hashlib.sha256(turn["answer"].encode()).hexdigest(),
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
        raise ValueError("sandboxed backend listener remained after stop")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = smoke(args.app, args.state_root, args.report)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        failure = {
            "schema_version": "open_agronomy_agent.macos_offline_smoke.v1",
            "status": "fail", "error_code": type(exc).__name__,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
