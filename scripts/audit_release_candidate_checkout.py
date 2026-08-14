#!/usr/bin/env python3
"""Fail-closed audit of a committed release-candidate checkout and environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_public_repository import DEFAULT_MANIFEST, _collect, _validate_scope
from scripts.capture_release_environment import dependency_input_receipts


ENVIRONMENT_SCHEMA = "open_agronomy_agent.release_environment_receipt.v1"


def _command(root: Path, *command: str) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment_errors(root: Path, receipt_path: Path, commit: str | None) -> list[str]:
    if not receipt_path.is_file():
        return [f"environment_receipt_missing:{receipt_path}"]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"environment_receipt_invalid:{type(exc).__name__}"]
    errors: list[str] = []
    if receipt.get("schema_version") != ENVIRONMENT_SCHEMA:
        errors.append("environment_receipt_schema_mismatch")
    source = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    if source.get("commit") != commit:
        errors.append("environment_receipt_commit_mismatch")
    if source.get("worktree_clean") is not True:
        errors.append("environment_receipt_was_not_captured_from_clean_worktree")
    policy = receipt.get("dependency_policy") if isinstance(receipt.get("dependency_policy"), dict) else {}
    if policy.get("python") != "observed_installed_versions_from_range_declarations_not_portable_lock":
        errors.append("environment_receipt_python_boundary_missing")
    expected_inputs = {
        str(item["path"]): item
        for item in dependency_input_receipts(root)
    }
    observed_inputs = {
        str(item.get("path")): item
        for item in (receipt.get("dependency_inputs") or [])
        if isinstance(item, dict) and item.get("path")
    }
    if set(observed_inputs) != set(expected_inputs):
        errors.append("environment_receipt_dependency_inventory_mismatch")
    for path, expected in expected_inputs.items():
        observed = observed_inputs.get(path) or {}
        if observed.get("sha256") != expected.get("sha256"):
            errors.append(f"environment_receipt_dependency_hash_mismatch:{path}")
    if not receipt.get("python_packages"):
        errors.append("environment_receipt_python_packages_missing")
    return errors


def audit(
    root: Path,
    *,
    manifest_path: Path,
    require_clean: bool,
    environment_receipt: Path | None,
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    errors: list[str] = []
    commit_status, commit = _command(root, "git", "rev-parse", "HEAD")
    status_code, status_text = _command(
        root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if commit_status != 0 or status_code != 0:
        errors.append("git_checkout_unavailable")
        commit = None
    if require_clean and status_text:
        errors.append(f"worktree_not_clean:{len(status_text.splitlines())}_paths")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        public_files = _collect(manifest)
        _validate_scope(public_files, manifest)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        public_files = []
        errors.append(f"public_manifest_invalid:{type(exc).__name__}:{exc}")

    untracked_release_files: list[str] = []
    for path in public_files:
        relative = path.resolve().relative_to(root).as_posix()
        tracked_status, _ = _command(root, "git", "ls-files", "--error-unmatch", "--", relative)
        if tracked_status != 0:
            untracked_release_files.append(relative)
    if untracked_release_files:
        errors.append(f"public_manifest_has_untracked_files:{len(untracked_release_files)}")

    if environment_receipt is None:
        errors.append("environment_receipt_required")
    else:
        errors.extend(_environment_errors(root, environment_receipt.resolve(), commit))

    return {
        "schema_version": "open_agronomy_agent.release_candidate_checkout_audit.v1",
        "status": "pass" if not errors else "blocked",
        "commit": commit,
        "worktree_clean": status_code == 0 and not status_text,
        "public_manifest": manifest_path.relative_to(root).as_posix()
        if manifest_path.is_relative_to(root)
        else str(manifest_path),
        "public_file_count": len(public_files),
        "public_manifest_sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
        "untracked_release_files": untracked_release_files,
        "python_dependency_boundary": "range_declarations_plus_observed_environment_receipt",
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--environment-receipt", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args(argv)
    root = ROOT
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    environment = args.environment_receipt
    if environment is not None and not environment.is_absolute():
        environment = root / environment
    report = audit(
        root,
        manifest_path=manifest,
        require_clean=args.require_clean,
        environment_receipt=environment,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
