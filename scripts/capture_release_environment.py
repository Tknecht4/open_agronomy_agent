#!/usr/bin/env python3
"""Capture the exact local release-test environment without claiming a lock.

The repository's Python requirement files intentionally contain compatible
ranges. This receipt records the versions that were actually installed for one
test or benchmark run; it is not a portable resolver lock and must not be
presented as one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


DEPENDENCY_INPUTS = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-phase4-ci.txt",
    "requirements-container.txt",
    "requirements-docs.txt",
    "frontend/package.json",
    "frontend/package-lock.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command(root: Path, *command: str) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout.strip()


def dependency_input_receipts(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in DEPENDENCY_INPUTS:
        path = root / relative
        records.append(
            {
                "path": relative,
                "present": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else None,
                "sha256": _sha256(path) if path.is_file() else None,
            }
        )
    return records


def _installed_python_packages() -> list[dict[str, str]]:
    versions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        if name:
            versions[name.casefold()] = str(distribution.version)
    return [
        {"name": name, "version": versions[name]}
        for name in sorted(versions)
    ]


def build_environment_receipt(
    root: Path,
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    commit_status, commit = _command(root, "git", "rev-parse", "HEAD")
    status_code, status_text = _command(
        root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    node_status, node_version = _command(root, "node", "--version")
    npm_status, npm_version = _command(root, "npm", "--version")
    dependency_inputs = dependency_input_receipts(root)
    return {
        "schema_version": "open_agronomy_agent.release_environment_receipt.v1",
        "captured_at": captured_at
        or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "source": {
            "commit": commit if commit_status == 0 else None,
            "git_available": commit_status == 0 and status_code == 0,
            "worktree_clean": status_code == 0 and not status_text,
            "changed_path_count": len(status_text.splitlines()) if status_text else 0,
        },
        "dependency_policy": {
            "python": "observed_installed_versions_from_range_declarations_not_portable_lock",
            "frontend": "package_lock_v3_exact_resolution",
            "claim_boundary": (
                "This receipt identifies one observed local environment. Python requirement files contain "
                "compatible ranges, so recreating the environment may resolve different transitive versions."
            ),
        },
        "runtime": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
            "platform_release": platform.release(),
            "node": node_version if node_status == 0 else None,
            "npm": npm_version if npm_status == 0 else None,
        },
        "dependency_inputs": dependency_inputs,
        "python_packages": _installed_python_packages(),
        "missing_dependency_inputs": [
            str(item["path"])
            for item in dependency_inputs
            if not item["present"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/release/release_environment.json"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    receipt = build_environment_receipt(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "pass" if not receipt["missing_dependency_inputs"] else "blocked",
                "output": str(output),
                "sha256": _sha256(output),
                "worktree_clean": receipt["source"]["worktree_clean"],
                "python_package_count": len(receipt["python_packages"]),
                "python_lock_boundary": "observed_versions_from_ranges_not_portable_lock",
            },
            indent=2,
        )
    )
    return 0 if not receipt["missing_dependency_inputs"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
