#!/usr/bin/env python3
"""Validate the external conference release authority and its frozen artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY = ROOT / "docs/conference_release_authority_20260810.json"
DEFAULT_OUTPUT = ROOT / "outputs/conference_release_authority_validation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_file(value: Any) -> Path:
    relative = Path(str(value or ""))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe or empty repository path: {value!r}")
    resolved = (ROOT / relative).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError(f"repository path escapes root: {value!r}")
    return resolved


def validate_file_record(
    record: dict[str, Any],
    *,
    label: str,
    failures: list[str],
) -> Path | None:
    try:
        path = _repo_file(record.get("path"))
    except ValueError as exc:
        failures.append(f"{label}: {exc}")
        return None
    if not path.is_file():
        failures.append(f"{label}: missing file {path.relative_to(ROOT)}")
        return None
    expected = str(record.get("sha256") or "")
    actual = sha256(path)
    if expected != actual:
        failures.append(f"{label}: SHA-256 mismatch ({expected!r} != {actual})")
    return path


def validate_benchmark_database(
    record: dict[str, Any],
    *,
    label: str,
    failures: list[str],
    expected_suite_sha256: str | None = None,
) -> dict[str, Any]:
    path = validate_file_record(record, label=label, failures=failures)
    if path is None:
        return {}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = len(list(connection.execute("PRAGMA foreign_key_check")))
        response_count = int(connection.execute("SELECT COUNT(*) FROM response").fetchone()[0])
        canonical_run_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM benchmark_run WHERE is_canonical = 1"
            ).fetchone()[0]
        )
        unique_model_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT model_key) FROM benchmark_run WHERE is_canonical = 1"
            ).fetchone()[0]
        )
        unique_arm_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT mode) FROM benchmark_run WHERE is_canonical = 1"
            ).fetchone()[0]
        )
        canonical_response_count = int(
            connection.execute(
                """SELECT COUNT(*)
                   FROM response AS response
                   JOIN benchmark_run AS run ON run.run_id = response.run_id
                   WHERE run.is_canonical = 1"""
            ).fetchone()[0]
        )
        empty_output_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM response WHERE trim(output) = ''"
            ).fetchone()[0]
        )
        empty_messages_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM response WHERE trim(exact_messages_json) IN ('', '[]', '{}')"
            ).fetchone()[0]
        )
        judge_assessment_count = int(
            connection.execute("SELECT COUNT(*) FROM judge_assessment").fetchone()[0]
        )
        semantic_judgment_count = int(
            connection.execute("SELECT COUNT(*) FROM semantic_judgment").fetchone()[0]
        )
        expected_cases = int(record.get("expected_case_count") or 0)
        run_row_count_mismatches = int(
            connection.execute(
                "SELECT COUNT(*) FROM benchmark_run WHERE is_canonical = 1 AND row_count != ?",
                (expected_cases,),
            ).fetchone()[0]
        ) if expected_cases else 0
        suite_hashes = sorted(
            str(row[0])
            for row in connection.execute(
                """SELECT DISTINCT json_extract(run_identity_json, '$.suite_sha256')
                   FROM benchmark_run WHERE is_canonical = 1"""
            )
            if row[0] is not None
        )
        implementation_hashes = sorted(
            str(row[0])
            for row in connection.execute(
                """SELECT DISTINCT json_extract(run_identity_json, '$.implementation.sha256')
                   FROM benchmark_run WHERE is_canonical = 1"""
            )
            if row[0] is not None
        )
    expected_responses = int(record.get("expected_response_count") or 0)
    expected_runs = int(record.get("expected_canonical_run_count") or 0)
    expected_models = int(record.get("expected_model_count") or 0)
    expected_arms = int(record.get("expected_arm_count") or 0)
    expected_judge_assessments = int(record.get("expected_judge_assessment_count") or 0)
    expected_semantic_judgments = int(record.get("expected_semantic_judgment_count") or 0)
    checks = {
        "path": str(path.relative_to(ROOT)),
        "integrity_check": integrity,
        "foreign_key_error_count": foreign_key_errors,
        "response_count": response_count,
        "canonical_response_count": canonical_response_count,
        "canonical_run_count": canonical_run_count,
        "unique_model_count": unique_model_count,
        "unique_arm_count": unique_arm_count,
        "empty_output_count": empty_output_count,
        "empty_messages_count": empty_messages_count,
        "judge_assessment_count": judge_assessment_count,
        "semantic_judgment_count": semantic_judgment_count,
        "run_row_count_mismatches": run_row_count_mismatches,
        "suite_sha256_values": suite_hashes,
        "implementation_sha256_values": implementation_hashes,
    }
    if integrity != "ok":
        failures.append(f"{label}: SQLite integrity is {integrity!r}")
    if foreign_key_errors:
        failures.append(f"{label}: {foreign_key_errors} foreign-key errors")
    if canonical_response_count != response_count:
        failures.append(
            f"{label}: {response_count - canonical_response_count} responses belong to non-canonical runs"
        )
    if empty_output_count:
        failures.append(f"{label}: {empty_output_count} empty responses")
    if empty_messages_count:
        failures.append(f"{label}: {empty_messages_count} responses lack exact messages")
    if judge_assessment_count != expected_judge_assessments:
        failures.append(
            f"{label}: judge assessment count {judge_assessment_count} != {expected_judge_assessments}"
        )
    if semantic_judgment_count != expected_semantic_judgments:
        failures.append(
            f"{label}: semantic judgment count {semantic_judgment_count} != {expected_semantic_judgments}"
        )
    if run_row_count_mismatches:
        failures.append(
            f"{label}: {run_row_count_mismatches} canonical runs have the wrong case count"
        )
    if expected_suite_sha256 and suite_hashes != [expected_suite_sha256]:
        failures.append(
            f"{label}: suite SHA-256 values {suite_hashes!r} != {[expected_suite_sha256]!r}"
        )
    if len(implementation_hashes) != 1:
        failures.append(
            f"{label}: canonical runs span {len(implementation_hashes)} implementation identities; "
            "a release comparison must use one frozen implementation"
        )
    for name, actual, expected in (
        ("response count", response_count, expected_responses),
        ("canonical run count", canonical_run_count, expected_runs),
        ("model count", unique_model_count, expected_models),
        ("arm count", unique_arm_count, expected_arms),
    ):
        if actual != expected:
            failures.append(f"{label}: {name} {actual} != {expected}")
    return checks


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def _validate_receipt_gate(
    record: dict[str, Any],
    *,
    label: str,
    gate_path: tuple[str, ...],
    failures: list[str],
    expected: Any = True,
) -> dict[str, Any]:
    path = validate_file_record(record, label=label, failures=failures)
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    value: Any = payload
    for key in gate_path:
        value = value.get(key) if isinstance(value, dict) else None
    if value != expected:
        failures.append(
            f"{label}: {'.'.join(gate_path)} is {value!r}, expected {expected!r}"
        )
    return payload


def validate(authority_path: Path) -> dict[str, Any]:
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    observations: dict[str, Any] = {}
    if authority.get("schema_version") != "open_agronomy_agent.conference_release_authority.v2":
        failures.append("authority schema is not v2")
    if authority.get("status") != "pass":
        failures.append("authority status is not pass")

    git_record = authority.get("git") or {}
    try:
        branch = _git("branch", "--show-current")
        head = _git("rev-parse", "HEAD")
        reference = str(git_record.get("reference") or "")
        resolved_reference = _git("rev-parse", f"{reference}^{{commit}}") if reference else ""
        porcelain = _git("status", "--porcelain")
        observations["git"] = {
            "branch": branch,
            "head": head,
            "reference": reference,
            "resolved_reference": resolved_reference,
            "clean": not porcelain,
        }
        if branch != git_record.get("branch"):
            failures.append(f"Git branch {branch!r} does not match authority")
        if not reference or resolved_reference != head:
            failures.append("Git release reference does not resolve to HEAD")
        if porcelain:
            failures.append("Git worktree is not clean")
    except (subprocess.CalledProcessError, ValueError) as exc:
        failures.append(f"Git validation failed: {exc}")

    model = authority.get("model") or {}
    model_path = validate_file_record(
        {"path": model.get("config_path"), "sha256": model.get("config_sha256")},
        label="model config",
        failures=failures,
    )
    if model_path is not None:
        model_config = yaml.safe_load(model_path.read_text(encoding="utf-8")) or {}
        configured_id = str(
            model_config.get("serving_model_id") or model_config.get("model_id") or ""
        )
        if configured_id != model.get("model_id"):
            failures.append("model ID does not match pinned config")
        if str(model_config.get("model_revision") or "") != model.get("revision"):
            failures.append("model revision does not match pinned config")

    knowledge = authority.get("knowledge") or {}
    validate_file_record(
        {
            "path": knowledge.get("runtime_manifest"),
            "sha256": knowledge.get("runtime_manifest_sha256"),
        },
        label="runtime manifest",
        failures=failures,
    )

    evaluation = authority.get("evaluation") or {}
    observations["internal_benchmark"] = validate_benchmark_database(
        evaluation.get("internal") or {},
        label="internal benchmark",
        failures=failures,
        expected_suite_sha256=str(evaluation.get("internal_suite_sha256") or ""),
    )
    observations["external_benchmark"] = validate_benchmark_database(
        evaluation.get("external") or {},
        label="external benchmark",
        failures=failures,
        expected_suite_sha256=str(evaluation.get("external_suite_sha256") or ""),
    )

    portable = authority.get("portable_archive") or {}
    archive_path = validate_file_record(portable, label="portable archive", failures=failures)
    verification = _validate_receipt_gate(
        portable.get("verification") or {},
        label="portable verification",
        gate_path=("status",),
        expected="pass",
        failures=failures,
    )
    if archive_path is not None and verification:
        if verification.get("archive_sha256") != sha256(archive_path):
            failures.append("portable verification does not identify the authorized archive")
        if verification.get("benchmark_evidence_required") is not True:
            failures.append("portable verification did not require benchmark evidence")

    demo = authority.get("demo") or {}
    journey = _validate_receipt_gate(
        demo.get("journey_matrix") or {},
        label="journey matrix",
        gate_path=("gate_passed",),
        failures=failures,
    )
    if journey and journey.get("complete") is not True:
        failures.append("journey matrix is not complete")
    _validate_receipt_gate(
        demo.get("browser_rehearsal") or {},
        label="browser rehearsal",
        gate_path=("gate_passed",),
        failures=failures,
    )
    fallback = _validate_receipt_gate(
        demo.get("fallback_recording") or {},
        label="fallback recording",
        gate_path=("workflow", "gate_passed"),
        failures=failures,
    )
    if fallback:
        video_record = {
            "path": fallback.get("video_path"),
            "sha256": fallback.get("video_sha256"),
        }
        validate_file_record(video_record, label="fallback video", failures=failures)

    documents = authority.get("documents") or {}
    for key in ("architecture_paper", "performance_brief", "operator_runbook"):
        validate_file_record(documents.get(key) or {}, label=key, failures=failures)

    return {
        "schema_version": "open_agronomy_agent.conference_release_validation.v1",
        "status": "pass" if not failures else "fail",
        "release_id": authority.get("release_id"),
        "authority_path": str(authority_path.resolve()),
        "authority_sha256": sha256(authority_path),
        "failures": failures,
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", type=Path, default=DEFAULT_AUTHORITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = validate(args.authority.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
