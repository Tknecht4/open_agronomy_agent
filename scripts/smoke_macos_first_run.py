#!/usr/bin/env python3
"""Test a fresh Mac app launch and its user-initiated model setup button."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scripts.smoke_macos_launcher import (
    _alive,
    _quit_app,
    _status,
    _wait_browser_pairing,
    _wait_ready,
    _wait_stopped,
)


class SmokeFailure(RuntimeError):
    """A bounded CI-safe first-run failure code."""


def _wait_phase(path: Path, phase: str, *, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        row = _status(path)
        if row and row.get("phase") == "error":
            raise SmokeFailure("native_launcher_reported_error")
        if row and row.get("phase") == phase:
            return row
        time.sleep(0.5)
    raise SmokeFailure("native_setup_phase_timeout")


def _click_setup_button(state: Path) -> None:
    script = '\n'.join([
        'tell application id "io.openagronomy.desktop" to activate',
        'tell application "System Events"',
        '  set targetProcess to first application process whose bundle identifier is "io.openagronomy.desktop"',
        '  click button "Install local model" of window "Open Agronomy" of targetProcess',
        'end tell',
    ])
    completed = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if completed.returncode != 0:
        logs = state / "logs"
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        private = logs / "first-run-ui-automation.log"
        private.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
        private.chmod(0o600)
        raise SmokeFailure("ui_automation_unavailable_or_button_missing")


def smoke(app: Path, state: Path, report: Path) -> dict[str, Any]:
    expected_state = Path.home() / "Library/Application Support/OpenAgronomyAgent/desktop"
    if state.resolve() != expected_state.resolve():
        raise SmokeFailure("unexpected_application_state_root")
    if state.exists() and any(state.iterdir()):
        raise SmokeFailure("first_run_state_not_empty")
    app = app.resolve(strict=True)
    receipt = state / "receipts/model-install.json"
    status_path = state / "launcher-status.json"
    started = time.monotonic()
    active: dict[str, Any] | None = None
    try:
        subprocess.run(["open", "-n", "-a", str(app)], check=True, timeout=20)
        _wait_phase(status_path, "setup_required", timeout_seconds=120)
        if receipt.exists():
            raise SmokeFailure("model_download_started_without_user_action")
        _click_setup_button(state)
        _wait_phase(status_path, "installing_model", timeout_seconds=30)
        active = _wait_ready(status_path, timeout_seconds=1800)
        if not _wait_browser_pairing(int(active["port"])):
            raise SmokeFailure("first_run_browser_pairing_not_consumed")
        model = json.loads(receipt.read_text(encoding="utf-8"))
        if model.get("revision") != "238767527555cb75a05732a84dff5d6ba0dd6809" or len(model.get("files") or []) != 10:
            raise SmokeFailure("first_run_model_receipt_not_pinned")
        result = {
            "schema_version": "open_agronomy_agent.macos_first_run_smoke.v1",
            "status": "pass",
            "setup_required_before_consent": True,
            "setup_button_clicked": True,
            "model_revision": model["revision"],
            "model_file_count": len(model["files"]),
            "browser_pairing_consumed": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        _quit_app()
        _wait_stopped(
            status_path,
            launcher_pid=int(active["launcher_pid"]),
            backend_pid=int(active["backend_pid"]),
            port=int(active["port"]),
        )
        result["listener_stopped"] = True
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        try:
            _quit_app()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        remaining = active or _status(status_path) or {}
        for key in ("operation_pid", "backend_pid", "launcher_pid"):
            pid = int(remaining.get(key) or 0)
            if _alive(pid):
                os.kill(pid, signal.SIGTERM)


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
        code = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
        failure = {"schema_version": "open_agronomy_agent.macos_first_run_smoke.v1",
                   "status": "fail", "error_code": code}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
