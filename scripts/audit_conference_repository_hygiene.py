#!/usr/bin/env python3
"""Audit the candidate conference tree for release-hygiene failures."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/conference_repository_hygiene_latest.json"
HARD_FILE_LIMIT = 100 * 1024 * 1024
WARNING_FILE_LIMIT = 50 * 1024 * 1024
FORBIDDEN_PARTS = {".pytest_cache", "__pycache__", "dist", "node_modules"}
FORBIDDEN_NAMES = {".DS_Store", ".env", "id_rsa", "id_ed25519"}
MODEL_WEIGHT_SUFFIXES = {".bin", ".gguf", ".npz", ".pt", ".pth", ".safetensors"}
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "openai_token": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
}


def _git_paths(repo_root: Path, *, staged: bool) -> list[Path]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z"]
    if not staged:
        command = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [repo_root / value.decode("utf-8") for value in completed.stdout.split(b"\0") if value]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _secret_matches(path: Path) -> list[str]:
    matches: list[str] = []
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            if b"\0" in block:
                return matches
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(block):
                    matches.append(name)
    return sorted(set(matches))


def audit(repo_root: Path, paths: Iterable[Path]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    files: list[dict[str, Any]] = []
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root).as_posix()
        parts = set(path.relative_to(repo_root).parts)
        size = path.stat().st_size
        if parts & FORBIDDEN_PARTS or path.name in FORBIDDEN_NAMES:
            failures.append(f"generated or private path selected: {relative}")
        if path.suffix.lower() in MODEL_WEIGHT_SUFFIXES:
            failures.append(f"model weight selected: {relative}")
        if size >= HARD_FILE_LIMIT:
            failures.append(f"file exceeds GitHub 100 MiB limit: {relative} ({size} bytes)")
        elif size >= WARNING_FILE_LIMIT:
            warnings.append(f"file exceeds 50 MiB warning threshold: {relative} ({size} bytes)")
        secret_matches = _secret_matches(path)
        if secret_matches:
            failures.append(f"secret signature in {relative}: {', '.join(secret_matches)}")
        files.append(
            {
                "path": relative,
                "bytes": size,
                "sha256": _sha256(path),
                "secret_signatures": secret_matches,
            }
        )
    root_licenses = [
        candidate.name
        for candidate in repo_root.iterdir()
        if candidate.is_file() and candidate.name.lower() in {"license", "license.md", "license.txt"}
    ]
    owner_actions = [] if root_licenses else [
        "Select and add the project software licence before describing the public repository as open source."
    ]
    return {
        "schema_version": "open_agronomy_agent.conference_repository_hygiene.v1",
        "status": "pass" if not failures else "fail",
        "scanned_file_count": len(files),
        "scanned_bytes": sum(row["bytes"] for row in files),
        "root_licenses": root_licenses,
        "owner_actions": owner_actions,
        "failures": failures,
        "warnings": warnings,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Audit only files staged for the checkpoint.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = audit(ROOT, _git_paths(ROOT, staged=args.staged))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
