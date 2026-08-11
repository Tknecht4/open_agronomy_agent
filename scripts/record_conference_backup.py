#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = ROOT / "scripts/conference_backup_recording.js"
DEFAULT_PLAYWRIGHT_CLI = Path.home() / ".codex/skills/playwright/scripts/playwright_cli.sh"
DEFAULT_VIDEO = ROOT / "outputs/open_agronomy_agent_canadian_conference_backup_latest.webm"
DEFAULT_RECEIPT = ROOT / "outputs/open_agronomy_agent_canadian_conference_backup_latest.json"
DEFAULT_PLAYER = ROOT / "outputs/open_agronomy_agent_canadian_conference_backup_player.html"
DEFAULT_URL = "http://127.0.0.1:8080/"
TARGET_URL_PATTERN = re.compile(
    r"const targetUrl = globalThis\.process\?\.env\?\.CONFERENCE_RECORDING_URL \|\| 'http://127\.0\.0\.1:8080/'"
)


def extract_playwright_result(stdout: str) -> dict[str, Any]:
    marker = "### Result"
    marker_index = stdout.find(marker)
    if marker_index < 0:
        raise ValueError("Playwright output did not contain a Result section")
    payload_start = stdout.find("\n", marker_index)
    if payload_start < 0:
        raise ValueError("Playwright Result section was empty")
    payload, _ = json.JSONDecoder().raw_decode(stdout[payload_start:].lstrip())
    if not isinstance(payload, dict):
        raise ValueError("Playwright Result payload must be a JSON object")
    return payload


def prepare_recording_script(path: Path, *, url: str) -> str:
    prepared = TARGET_URL_PATTERN.sub(f"const targetUrl = {json.dumps(url)}", path.read_text(encoding="utf-8"), count=1)
    if url not in prepared:
        raise ValueError("could not inject conference recording target URL")
    return prepared


def resolve_playwright_cli(path: Path) -> tuple[Path, str]:
    """Prefer an already-installed CLI so recording never needs the network."""

    if path != DEFAULT_PLAYWRIGHT_CLI:
        return path, "explicit"
    cached = sorted(
        (Path.home() / ".npm" / "_npx").glob("*/node_modules/.bin/playwright-cli"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if cached:
        return cached[0], "cached_direct"
    return path, "npx_wrapper_offline"


def render_player_html(video_name: str) -> str:
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link rel=\"icon\" href=\"data:,\">
  <title>Open Agronomy Agent - Conference Backup</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; background: #101713; color: #f4f7f2; font-family: Inter, system-ui, sans-serif; }}
    body {{ display: grid; grid-template-rows: 62px minmax(0, 1fr); }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 0 24px; border-bottom: 1px solid #314038; background: #18231d; }}
    header strong {{ font-size: 18px; }}
    header span {{ color: #b8c8bc; font-size: 13px; }}
    video {{ width: 100%; height: 100%; object-fit: contain; background: #000; }}
  </style>
</head>
<body>
  <header><strong>Open Agronomy Agent</strong><span>Canadian conference fallback - verified browser recording</span></header>
  <video controls autoplay playsinline preload=\"auto\">
    <source src=\"{video_name}\" type=\"video/webm\">
    This browser cannot play the WebM conference backup.
  </video>
</body>
</html>
"""


def finalize_recording(*, video: Path, receipt: Path, player: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    video = video.resolve()
    receipt = receipt.resolve()
    player = player.resolve()
    if not video.is_file() or video.stat().st_size <= 0:
        raise RuntimeError(f"conference recording was not written: {video}")
    player.parent.mkdir(parents=True, exist_ok=True)
    player.write_text(render_player_html(video.name), encoding="utf-8")
    receipt_payload = {
        "schema_version": "open_agronomy_agent.conference_backup_recording_receipt.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video_path": str(video.relative_to(ROOT) if video.is_relative_to(ROOT) else video),
        "video_bytes": video.stat().st_size,
        "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "player_path": str(player.relative_to(ROOT) if player.is_relative_to(ROOT) else player),
        "player_bytes": player.stat().st_size,
        "player_sha256": hashlib.sha256(player.read_bytes()).hexdigest(),
        "workflow": workflow,
    }
    receipt.write_text(json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt_payload


def _run_cli(
    playwright_cli: Path,
    session: str,
    *args: str,
    timeout_seconds: int = 240,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(playwright_cli), f"-s={session}", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stdout + completed.stderr).strip())
    return completed


def record_backup(
    *,
    url: str = DEFAULT_URL,
    video: Path = DEFAULT_VIDEO,
    receipt: Path = DEFAULT_RECEIPT,
    player: Path = DEFAULT_PLAYER,
    script: Path = DEFAULT_SCRIPT,
    playwright_cli: Path = DEFAULT_PLAYWRIGHT_CLI,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    video = video.resolve()
    receipt = receipt.resolve()
    video.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    prepared = prepare_recording_script(script, url=url)
    resolved_playwright_cli, playwright_cli_mode = resolve_playwright_cli(playwright_cli)
    session = f"conference-backup-{os.getpid()}"
    run_result: dict[str, Any] | None = None
    recording_started = False

    with tempfile.TemporaryDirectory(prefix="conference-backup-recording-") as tmp_dir:
        temp_root = Path(tmp_dir)
        prepared_script = temp_root / "conference_backup_recording.js"
        prepared_script.write_text(prepared, encoding="utf-8")
        cli_env = {
            **os.environ,
            "npm_config_offline": "true",
            "PWTEST_DAEMON_SESSION_DIR": str(temp_root / "daemon"),
            "PLAYWRIGHT_BROWSERS_PATH": str(temp_root / "browsers"),
            "PWTEST_SERVER_REGISTRY": str(temp_root / "server-registry"),
        }
        try:
            _run_cli(resolved_playwright_cli, session, "open", url, timeout_seconds=timeout_seconds, env=cli_env)
            _run_cli(resolved_playwright_cli, session, "resize", "1440", "900", timeout_seconds=timeout_seconds, env=cli_env)
            _run_cli(
                resolved_playwright_cli,
                session,
                "run-code",
                "async (page) => { await page.waitForSelector('.leaflet-map:not(.map-loading)', { timeout: 30000 }); await page.waitForTimeout(800); return true }",
                timeout_seconds=timeout_seconds,
                env=cli_env,
            )
            _run_cli(
                resolved_playwright_cli,
                session,
                "video-start",
                str(video),
                "--size",
                "1440x900",
                timeout_seconds=timeout_seconds,
                env=cli_env,
            )
            recording_started = True
            _run_cli(resolved_playwright_cli, session, "video-hide-actions", timeout_seconds=timeout_seconds, env=cli_env)
            completed = _run_cli(
                resolved_playwright_cli,
                session,
                "run-code",
                "--filename",
                str(prepared_script),
                timeout_seconds=timeout_seconds,
                env=cli_env,
            )
            run_result = extract_playwright_result(completed.stdout)
        finally:
            if recording_started:
                try:
                    _run_cli(resolved_playwright_cli, session, "video-stop", timeout_seconds=60, env=cli_env)
                except Exception:
                    pass
            try:
                _run_cli(resolved_playwright_cli, session, "close", timeout_seconds=60, env=cli_env)
            except Exception:
                pass

    if run_result is None:
        raise RuntimeError("conference recording did not produce a workflow report")
    run_result["browser_harness"] = {
        "playwright_cli_mode": playwright_cli_mode,
        "npm_offline_enforced": True,
        "network_install_attempted": False,
    }
    return finalize_recording(video=video, receipt=receipt, player=player, workflow=run_result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the deterministic Canadian conference fallback workflow.")
    parser.add_argument("--url", default=os.getenv("CONFERENCE_RECORDING_URL", DEFAULT_URL))
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--player", type=Path, default=DEFAULT_PLAYER)
    parser.add_argument("--finalize-existing", action="store_true", help="Regenerate player and hashes from the existing video/receipt without recording again.")
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--playwright-cli", type=Path, default=DEFAULT_PLAYWRIGHT_CLI)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    try:
        if args.finalize_existing:
            existing = json.loads(args.receipt.read_text(encoding="utf-8"))
            workflow = existing.get("workflow")
            if not isinstance(workflow, dict):
                raise ValueError("existing receipt does not contain a workflow object")
            receipt = finalize_recording(video=args.video, receipt=args.receipt, player=args.player, workflow=workflow)
        else:
            receipt = record_backup(
                url=args.url,
                video=args.video,
                receipt=args.receipt,
                player=args.player,
                script=args.script,
                playwright_cli=args.playwright_cli,
                timeout_seconds=args.timeout_seconds,
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("workflow", {}).get("gate_passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
