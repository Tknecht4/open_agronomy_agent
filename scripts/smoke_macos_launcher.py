#!/usr/bin/env python3
"""Exercise the actual Mac app launcher, browser pairing, Quit, and reopen."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _status(path: Path) -> dict[str, Any] | None:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return row if isinstance(row, dict) else None


def _health(port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            f"http://127.0.0.1:{port}/api/health", timeout=2
        ) as response:
            row = json.load(response)
    except (OSError, ValueError):
        return None
    return row if isinstance(row, dict) else None


def _session_exists(state: Path, session_id: str) -> bool:
    database = state / "db/open-agronomy.sqlite3"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is not None


def _quit_app() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application id "io.openagronomy.desktop" to quit'],
        check=True, capture_output=True, text=True, timeout=15,
    )


def _wait_ready(
    status_path: Path, *, previous_launch_id: str | None = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        row = _status(status_path)
        if row and row.get("phase") == "error":
            raise RuntimeError("native launcher reported an error; inspect its private backend log")
        if row and row.get("phase") == "ready" and row.get("browser_opened") is True:
            port = row.get("port")
            launch_id = row.get("launch_id")
            if (
                isinstance(port, int) and 1024 <= port <= 65535
                and isinstance(launch_id, str) and len(launch_id) == 64
                and launch_id != previous_launch_id
                and _alive(int(row.get("launcher_pid") or 0))
                and _alive(int(row.get("backend_pid") or 0))
            ):
                health = _health(port)
                if health and health.get("status") == "ok" and (
                    health.get("local_pairing") or {}
                ).get("launch_id") == launch_id:
                    return row
        time.sleep(0.5)
    raise TimeoutError("native launcher/browser/backend did not reach matching ready state")


def _wait_browser_pairing(port: int) -> bool:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        health = _health(port)
        if health and (health.get("local_pairing") or {}).get("consumed") is True:
            return True
        time.sleep(0.5)
    return False


def _wait_stopped(status_path: Path, *, launcher_pid: int, backend_pid: int, port: int) -> None:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        row = _status(status_path)
        if (
            row and row.get("phase") == "stopped"
            and not _alive(launcher_pid) and not _alive(backend_pid)
            and _health(port) is None
        ):
            return
        time.sleep(0.5)
    raise TimeoutError("native Quit left its backend process or listener active")


def smoke(app: Path, state: Path, backend_report: Path, report: Path) -> dict[str, Any]:
    expected_state = Path.home() / "Library/Application Support/OpenAgronomyAgent/desktop"
    if state.resolve() != expected_state.resolve():
        raise ValueError("launcher smoke state must match the app's private Application Support path")
    app = app.resolve(strict=True)
    source = json.loads(backend_report.read_text(encoding="utf-8"))
    if source.get("status") != "pass" or not source.get("session_id"):
        raise ValueError("launcher smoke requires a passing packaged-backend receipt")
    session_id = str(source["session_id"])
    if not _session_exists(state, session_id):
        raise ValueError("packaged-backend session is absent before launcher restart")
    status_path = state / "launcher-status.json"
    prior = _status(status_path)
    if status_path.exists() and (prior is None or prior.get("phase") != "stopped"):
        raise ValueError("launcher must be stopped before the reopen smoke")
    initial_port = prior.get("port") if prior else None
    observations: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    try:
        for attempt in range(2):
            subprocess.run(["open", "-n", "-a", str(app)], check=True, timeout=20)
            active = _wait_ready(
                status_path,
                previous_launch_id=observations[-1]["launch_id"] if observations else None,
            )
            port = int(active["port"])
            if initial_port is not None and port != initial_port:
                raise ValueError("reopen changed the first-run browser origin")
            if not _wait_browser_pairing(port):
                raise RuntimeError("default browser did not consume the native one-time pairing token")
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f"http://127.0.0.1:{port}/", timeout=5
            ) as response:
                if response.status != 200 or b'<div id="root"' not in response.read():
                    raise ValueError("native app did not expose the production workspace")
            if not _session_exists(state, session_id):
                raise ValueError("persisted session disappeared after native launch")
            observations.append(
                {
                    "attempt": attempt + 1,
                    "launch_id": active["launch_id"],
                    "port": port,
                    "browser_pairing_consumed": True,
                    "workspace_status": 200,
                    "session_preserved": True,
                }
            )
            _quit_app()
            _wait_stopped(
                status_path, launcher_pid=int(active["launcher_pid"]),
                backend_pid=int(active["backend_pid"]), port=port,
            )
            active = None
        if observations[0]["port"] != observations[1]["port"]:
            raise ValueError("native reopen changed the browser origin and stranded local drafts")
        result = {
            "schema_version": "open_agronomy_agent.macos_launcher_smoke.v1",
            "status": "pass",
            "launches": observations,
            "model_revision": source["model_revision"],
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        try:
            _quit_app()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        remaining = active or _status(status_path) or {}
        for key in ("backend_pid", "launcher_pid"):
            pid = int(remaining.get(key) or 0)
            if _alive(pid):
                os.kill(pid, signal.SIGTERM)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--backend-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = smoke(args.app, args.state_root, args.backend_report, args.report)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as exc:
        failure = {
            "schema_version": "open_agronomy_agent.macos_launcher_smoke.v1",
            "status": "fail",
            "detail": str(exc),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
