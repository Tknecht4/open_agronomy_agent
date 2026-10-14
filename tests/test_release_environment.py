from __future__ import annotations

import json
import pytest

import scripts.capture_release_environment as capture

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
        "requirements/requirements-phase4-ci.txt",
        "requirements/requirements-benchmark-analysis.txt",
        "requirements/requirements-container.txt",
        "requirements/requirements-docs.txt",
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


def test_environment_receipt_binds_benchmark_analysis_dependencies(tmp_path) -> None:
    for relative in (
        "pyproject.toml",
        "requirements.txt",
        "requirements/requirements-phase4-ci.txt",
        "requirements/requirements-benchmark-analysis.txt",
        "requirements/requirements-container.txt",
        "requirements/requirements-docs.txt",
        "frontend/package.json",
        "frontend/package-lock.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{relative}\n", encoding="utf-8")

    receipt = build_environment_receipt(
        tmp_path,
        captured_at="2026-08-15T00:00:00+00:00",
    )

    dependency_paths = {str(item["path"]) for item in receipt["dependency_inputs"]}
    assert "requirements/requirements-benchmark-analysis.txt" in dependency_paths
    assert receipt["missing_dependency_inputs"] == []


@pytest.mark.parametrize("exact_checkout", [True, False])
def test_environment_git_identity_requires_the_requested_checkout_root(tmp_path, monkeypatch, exact_checkout):
    calls = []
    def command(root, *args):
        calls.append(args)
        if args == ("git", "rev-parse", "--show-toplevel"):
            return 0, str(root if exact_checkout else root.parent)
        if args == ("git", "rev-parse", "HEAD"):
            return 0, "a" * 40
        if args[0] == "git":
            return 0, ""
        return 0, "test-version"
    monkeypatch.setattr(capture, "_command", command)
    receipt = capture.build_environment_receipt(tmp_path)
    assert receipt["source"]["git_available"] is exact_checkout
    assert receipt["source"]["worktree_clean"] is exact_checkout
    assert receipt["source"]["commit"] == ("a" * 40 if exact_checkout else None)
    if not exact_checkout:
        assert ("git", "rev-parse", "HEAD") not in calls
