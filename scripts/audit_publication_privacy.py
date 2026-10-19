#!/usr/bin/env python3
"""Reject personal paths in exact Git index bytes; never print matched values."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agronomy_agent.publication_privacy import personal_path_lines


def audit_index(root: Path, *, staged: bool) -> dict:
    command = (["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z"] if staged
               else ["git", "ls-files", "-z"])
    names = subprocess.check_output(command, cwd=root).split(b"\0")
    failures = []
    scanned = 0
    for raw_name in sorted(set(names)):
        if not raw_name:
            continue
        name = raw_name.decode("utf-8")
        # The index is authoritative even when a safer working copy exists.
        content = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        scanned += 1
        for line in personal_path_lines(content):
            failures.append({"path": name, "line": line, "category": "personal_filesystem_path"})
    return {"schema_version": "open_agronomy.publication_privacy.v1", "scope": "staged_index" if staged else "tracked_index", "status": "fail" if failures else "pass", "scanned_files": scanned, "findings": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--staged", action="store_true")
    modes.add_argument("--tracked", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_index(args.root.resolve(), staged=args.staged)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({**report, "findings": report["findings"][:20]}, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
