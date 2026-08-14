from __future__ import annotations

import json

from scripts.audit_release_candidate_checkout import _environment_errors
from scripts.capture_release_environment import build_environment_receipt


def test_environment_receipt_is_path_safe_and_explicitly_not_a_python_lock(tmp_path) -> None:
    receipt = build_environment_receipt(
        tmp_path,
        captured_at="2026-08-13T00:00:00+00:00",
    )

    assert receipt["dependency_policy"]["python"] == (
        "observed_installed_versions_from_range_declarations_not_portable_lock"
    )
    assert receipt["dependency_policy"]["frontend"] == "package_lock_v3_exact_resolution"
    assert receipt["source"]["git_available"] is False
    assert receipt["missing_dependency_inputs"]
    serialized = json.dumps(receipt)
    assert str(tmp_path) not in serialized
    assert all(set(item) == {"name", "version"} for item in receipt["python_packages"])


def test_environment_audit_rejects_dirty_or_stale_dependency_receipt(tmp_path) -> None:
    for relative in (
        "pyproject.toml",
        "requirements.txt",
        "requirements-phase4-ci.txt",
        "requirements-container.txt",
        "requirements-docs.txt",
        "frontend/package.json",
        "frontend/package-lock.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{relative}\n", encoding="utf-8")
    receipt = build_environment_receipt(
        tmp_path,
        captured_at="2026-08-13T00:00:00+00:00",
    )
    receipt["source"] = {
        "commit": "old-commit",
        "git_available": True,
        "worktree_clean": False,
        "changed_path_count": 1,
    }
    receipt["dependency_inputs"][0]["sha256"] = "0" * 64
    receipt_path = tmp_path / "environment.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    errors = _environment_errors(tmp_path, receipt_path, "new-commit")

    assert "environment_receipt_commit_mismatch" in errors
    assert "environment_receipt_was_not_captured_from_clean_worktree" in errors
    assert any(error.startswith("environment_receipt_dependency_hash_mismatch:") for error in errors)
