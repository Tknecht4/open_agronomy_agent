#!/usr/bin/env python3
"""Model-free preflight for a frozen benchmark development round.

The preflight validates source, suite, model, environment, public-package,
egress, output-identity, and interface boundaries.  It never generates or
judges answers. A passing receipt authorizes only the selected, explicitly
declared development rerun; it is not a sealed v3 holdout or an agronomic-
performance claim.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agronomy_agent.agent import build_context  # noqa: E402
from agronomy_agent.benchmark_contract import validate_benchmark  # noqa: E402
from agronomy_agent.corpus_governance import audit_runtime_corpora  # noqa: E402
from scripts.audit_benchmark_separation import build_audit as build_separation_audit  # noqa: E402
from scripts.capture_release_environment import dependency_input_receipts  # noqa: E402


DEFAULT_PLAN = ROOT / "configs/final_benchmark_round_rc3.json"
DEFAULT_OUTPUT = ROOT / "outputs/release/final_benchmark_readiness_rc3.json"
PLAN_SCHEMAS = {
    "open_agronomy_agent.final_benchmark_round.v1",
    "open_agronomy_agent.final_benchmark_round.v2",
    "open_agronomy_agent.final_benchmark_round.v3",
}
EGRESS_SCHEMA = "open_agronomy_agent.benchmark_egress_authorization.v2"
ENVIRONMENT_SCHEMA = "open_agronomy_agent.release_environment_receipt.v1"
PUBLIC_PACKAGE_SCHEMA = "open_agronomy_agent.public_repository_receipt.v1"
JUDGE_CALIBRATION_SCHEMA = "open_agronomy_agent.benchmark_judge_calibration.v1"
PLACEHOLDER_MARKERS = ("replace-with", "replace_me", "placeholder", "template", "example")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    detail: str,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "passed": bool(passed),
            "detail": detail,
            "evidence": dict(evidence or {}),
        }
    )


def _load_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return loaded


def _parse_utc(value: object, *, field: str) -> dt.datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field}_missing")
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{field}_must_be_utc")
    return parsed.astimezone(dt.UTC)


def _is_placeholder(value: object) -> bool:
    text = str(value or "").strip().lower()
    return not text or any(marker in text for marker in PLACEHOLDER_MARKERS)


def _is_placeholder_digest(value: object) -> bool:
    text = str(value or "").strip().lower()
    return not re.fullmatch(r"[0-9a-f]{64}", text) or len(set(text)) == 1


def _relative_file(root: Path, relative: object) -> Path:
    candidate = Path(str(relative or ""))
    if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe repository-relative path: {relative!r}")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes repository: {relative!r}")
    return resolved


def _file_record(
    root: Path,
    record: Mapping[str, Any],
    *,
    path_key: str,
    hash_key: str,
) -> tuple[bool, dict[str, Any]]:
    try:
        path = _relative_file(root, record.get(path_key))
    except ValueError as exc:
        return False, {"failure": str(exc)}
    expected = str(record.get(hash_key) or "")
    actual = sha256(path) if path.is_file() else None
    return bool(path.is_file() and re.fullmatch(r"[0-9a-f]{64}", expected) and actual == expected), {
        "path": str(path),
        "expected_sha256": expected or None,
        "actual_sha256": actual,
    }


def validate_plan_semantics(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate orchestration semantics without touching benchmark data."""

    failures: list[str] = []
    schema = plan.get("schema_version")
    if schema not in PLAN_SCHEMAS:
        failures.append("unsupported_plan_schema")
    if schema in {
        "open_agronomy_agent.final_benchmark_round.v2",
        "open_agronomy_agent.final_benchmark_round.v3",
    }:
        if plan.get("round_class") != "development_rerun_nonclaim":
            failures.append("round_class_must_be_development_rerun_nonclaim")
        if plan.get("benchmark_layer") != "development_regression":
            failures.append("benchmark_layer_must_be_development_regression")
        if plan.get("claim_eligible") is not False:
            failures.append("development_round_must_not_be_claim_eligible")
        internal = plan.get("internal_benchmark") or {}
        if internal.get("service_orchestration_exercised") is not False:
            failures.append("service_orchestration_boundary_missing")
        if internal.get("v3_harness_component_matrix_exercised") is not False:
            failures.append("v3_component_matrix_boundary_missing")
        external = plan.get("external_diagnostic") or {}
        if external.get("lifecycle") != "retired_after_rc1_exposure":
            failures.append("external_agroqa_v1_must_be_retired")
        if external.get("execution_allowed") is not False:
            failures.append("retired_external_execution_must_be_false")
        if external.get("rerun_command_emitted") is not False:
            failures.append("retired_external_command_flag_must_be_false")
        if "external_transfer_diagnostic" in (plan.get("evaluation_order") or []):
            failures.append("retired_external_diagnostic_in_evaluation_order")
        v3 = plan.get("v3_boundary") or {}
        if any(
            v3.get(key) is not False
            for key in (
                "sealed_holdout_exercised",
                "v3_performance_claim_eligible",
                "harness_component_effect_claim_eligible",
            )
        ):
            failures.append("v3_nonclaim_boundary_invalid")
        judge = plan.get("judge") or {}
        if judge.get("default_enabled") is not False:
            failures.append("semantic_judge_must_default_disabled")
        if judge.get("status") != "blocked_until_real_calibrated_receipt":
            failures.append("judge_calibration_gate_missing")
        if judge.get("self_judgment_policy") != "never_score_candidate_with_same_exact_model":
            failures.append("candidate_self_judgment_policy_missing")

        replication = plan.get("replication") or {}
        trials = replication.get("trials") or []
        if not isinstance(trials, list) or not trials:
            failures.append("replication_trials_missing")
        required_trial_fields = {
            "trial_id",
            "generation_seed",
            "verification_seed",
            "case_order_seed",
            "judge_seed",
        }
        trial_ids: list[str] = []
        identity_rows: list[tuple[Any, ...]] = []
        for index, trial in enumerate(trials):
            if not isinstance(trial, dict) or not required_trial_fields <= set(trial):
                failures.append(f"trial_{index}_identity_incomplete")
                continue
            trial_id = str(trial.get("trial_id") or "")
            trial_ids.append(trial_id)
            if not SAFE_ID.fullmatch(trial_id):
                failures.append(f"trial_{index}_id_unsafe")
            seeds = tuple(trial.get(field) for field in sorted(required_trial_fields - {"trial_id"}))
            if any(not isinstance(seed, int) or isinstance(seed, bool) or seed < 0 for seed in seeds):
                failures.append(f"trial_{index}_seed_invalid")
            identity_rows.append((trial_id, *seeds))
        if len(trial_ids) != len(set(trial_ids)):
            failures.append("duplicate_trial_id")
        if len(identity_rows) != len(set(identity_rows)):
            failures.append("duplicate_trial_identity")
        if replication.get("process_isolation_policy") != "fresh_process_per_run":
            failures.append("fresh_process_per_run_required")
        if replication.get("cache_policy") != "no_prompt_cache":
            failures.append("no_prompt_cache_required")
        sampling = replication.get("sampling") or {}
        if not {"temperature", "top_p", "top_k"} <= set(sampling):
            failures.append("sampling_overrides_incomplete")

        model_keys: list[str] = []
        for index, model in enumerate(plan.get("models") or []):
            model_key = str((model or {}).get("model_key") or "")
            model_keys.append(model_key)
            if not SAFE_ID.fullmatch(model_key):
                failures.append(f"model_{index}_key_unsafe")
            if (model or {}).get("backend") not in {"mlx_local", "codex_app_server"}:
                failures.append(f"model_{index}_backend_unsupported")
            if not re.fullmatch(r"[0-9a-f]{64}", str((model or {}).get("config_sha256") or "")):
                failures.append(f"model_{index}_config_digest_invalid")
            if (model or {}).get("backend") == "mlx_local" and not re.fullmatch(
                r"[0-9a-f]{40}", str((model or {}).get("revision") or "")
            ):
                failures.append(f"model_{index}_revision_not_exact")
        if not model_keys:
            failures.append("models_missing")
        if len(model_keys) != len(set(model_keys)):
            failures.append("duplicate_model_key")

        egress = plan.get("egress") or {}
        authorized = list(egress.get("authorized_payload_classes_exact") or [])
        excluded = list(egress.get("excluded_payload_classes_exact") or [])
        if egress.get("authorization_schema") != EGRESS_SCHEMA:
            failures.append("egress_v2_schema_required")
        if not authorized or len(authorized) != len(set(authorized)):
            failures.append("exact_authorized_payload_classes_invalid")
        if not excluded or len(excluded) != len(set(excluded)):
            failures.append("exact_excluded_payload_classes_invalid")
        if set(authorized) & set(excluded):
            failures.append("egress_payload_classes_overlap")

        if schema == "open_agronomy_agent.final_benchmark_round.v3":
            if internal.get("suite_exposure_status") != "exposed_and_used_for_system_tuning":
                failures.append("internal_suite_exposure_status_missing")
            runtime_profile = internal.get("runtime_profile") or {}
            if runtime_profile.get("status") != "active_release_candidate":
                failures.append("runtime_profile_status_invalid")
            if runtime_profile.get("master_profile_id") != "canada-offline-master":
                failures.append("master_profile_id_invalid")
            for path_key, hash_key in (
                ("rag_config_path", "rag_config_sha256"),
                ("registry_path", "registry_sha256"),
                ("policy_path", "policy_sha256"),
                ("knowledge_release_manifest_path", "knowledge_release_manifest_sha256"),
            ):
                if not str(runtime_profile.get(path_key) or "").strip():
                    failures.append(f"runtime_profile_{path_key}_missing")
                if not re.fullmatch(r"[0-9a-f]{64}", str(runtime_profile.get(hash_key) or "")):
                    failures.append(f"runtime_profile_{hash_key}_invalid")

    return {
        "status": "pass" if not failures else "blocked",
        "schema_version": schema,
        "round_id": plan.get("round_id"),
        "failures": failures,
    }


def verify_source_checkout(root: Path, *, branch: str, require_clean: bool) -> dict[str, Any]:
    values: dict[str, str] = {}
    failures: list[str] = []
    commands = {
        "branch": ["git", "branch", "--show-current"],
        "commit": ["git", "rev-parse", "HEAD"],
        "status": ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    }
    for key, command in commands.items():
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        if completed.returncode:
            failures.append(f"git_{key}_unavailable")
            values[key] = ""
        else:
            values[key] = completed.stdout.strip()
    if values.get("branch") != branch:
        failures.append("release_branch_mismatch")
    if require_clean and values.get("status"):
        failures.append("worktree_not_clean")
    return {
        "status": "pass" if not failures else "blocked",
        "branch": values.get("branch") or None,
        "commit": values.get("commit") or None,
        "worktree_clean": not bool(values.get("status")),
        "changed_path_count": len(values.get("status", "").splitlines()),
        "failures": failures,
    }


def _installed_python_packages() -> list[dict[str, str]]:
    versions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        if name:
            versions[name.casefold()] = str(distribution.version)
    return [{"name": name, "version": versions[name]} for name in sorted(versions)]


def verify_environment_receipt(
    root: Path,
    receipt_path: Path | None,
    *,
    git_commit: str | None,
    checked_at: dt.datetime | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if receipt_path is None or not receipt_path.is_file():
        return {"status": "blocked", "failures": ["environment_receipt_missing"]}
    try:
        receipt = _load_object(receipt_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "failures": [f"environment_receipt_unreadable:{type(exc).__name__}"]}
    if receipt.get("schema_version") != ENVIRONMENT_SCHEMA:
        failures.append("environment_receipt_schema_mismatch")
    source = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    if source.get("commit") != git_commit:
        failures.append("environment_receipt_commit_mismatch")
    if source.get("worktree_clean") is not True:
        failures.append("environment_receipt_not_captured_from_clean_worktree")
    policy = receipt.get("dependency_policy") if isinstance(receipt.get("dependency_policy"), dict) else {}
    if policy.get("python") != "observed_installed_versions_from_range_declarations_not_portable_lock":
        failures.append("environment_receipt_python_boundary_missing")
    try:
        captured_at = _parse_utc(receipt.get("captured_at"), field="captured_at")
        if captured_at > (checked_at or dt.datetime.now(dt.UTC)):
            failures.append("environment_receipt_from_future")
    except ValueError as exc:
        captured_at = None
        failures.append(str(exc))

    expected_inputs = {str(row["path"]): row for row in dependency_input_receipts(root)}
    observed_inputs = {
        str(row.get("path")): row
        for row in (receipt.get("dependency_inputs") or [])
        if isinstance(row, dict) and row.get("path")
    }
    if set(observed_inputs) != set(expected_inputs):
        failures.append("environment_dependency_inventory_mismatch")
    for path, expected in expected_inputs.items():
        observed = observed_inputs.get(path) or {}
        if any(observed.get(key) != expected.get(key) for key in ("present", "bytes", "sha256")):
            failures.append(f"environment_dependency_identity_mismatch:{path}")
    if receipt.get("missing_dependency_inputs") != [
        path for path, row in expected_inputs.items() if not row["present"]
    ]:
        failures.append("environment_missing_dependency_inventory_mismatch")

    runtime = receipt.get("runtime") if isinstance(receipt.get("runtime"), dict) else {}
    expected_runtime = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "platform_release": platform.release(),
    }
    if any(runtime.get(key) != value for key, value in expected_runtime.items()):
        failures.append("environment_runtime_mismatch")
    installed = _installed_python_packages()
    if receipt.get("python_packages") != installed:
        failures.append("environment_python_packages_mismatch")
    return {
        "status": "pass" if not failures else "blocked",
        "path": str(receipt_path.resolve()),
        "sha256": sha256(receipt_path),
        "captured_at": captured_at.isoformat().replace("+00:00", "Z") if captured_at else None,
        "commit": source.get("commit"),
        "python_package_count": len(receipt.get("python_packages") or []),
        "dependency_boundary": policy.get("python"),
        "failures": failures,
    }


def _excluded(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def _collect_public_paths(root: Path, manifest: Mapping[str, Any]) -> set[str]:
    exclusions = [str(value) for value in manifest.get("exclude_globs") or []]
    files: set[str] = set()
    for value in manifest.get("paths") or []:
        path = _relative_file(root, value)
        if not path.is_file():
            raise FileNotFoundError(str(value))
        files.add(path.relative_to(root).as_posix())
    for value in manifest.get("trees") or []:
        tree = _relative_file(root, value)
        if not tree.is_dir():
            raise FileNotFoundError(str(value))
        for path in tree.rglob("*"):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(root).as_posix()
                if not _excluded(relative, exclusions):
                    files.add(relative)
    for value in manifest.get("globs") or []:
        matched = [path for path in root.glob(str(value)) if path.is_file()]
        if not matched:
            raise FileNotFoundError(str(value))
        files.update(path.relative_to(root).as_posix() for path in matched)
    return files


def verify_public_release_receipt(
    source_root: Path,
    release_root: Path | None,
    *,
    manifest_path: Path,
    checked_at: dt.datetime | None = None,
) -> dict[str, Any]:
    if release_root is None:
        return {"status": "blocked", "failures": ["public_release_root_missing"]}
    release_root = release_root.resolve()
    receipt_path = release_root / "PUBLIC_RELEASE_RECEIPT.json"
    if not receipt_path.is_file():
        return {"status": "blocked", "failures": ["public_release_receipt_missing"]}
    failures: list[str] = []
    try:
        receipt = _load_object(receipt_path)
        manifest = _load_object(manifest_path)
        expected_paths = _collect_public_paths(source_root, manifest)
    except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError) as exc:
        return {
            "status": "blocked",
            "path": str(receipt_path),
            "failures": [f"public_release_validation_input_invalid:{type(exc).__name__}:{exc}"],
        }
    if receipt.get("schema_version") != PUBLIC_PACKAGE_SCHEMA:
        failures.append("public_release_receipt_schema_mismatch")
    expected_manifest_relative = manifest_path.resolve().relative_to(source_root.resolve()).as_posix()
    if receipt.get("manifest_path") != expected_manifest_relative:
        failures.append("public_release_manifest_path_mismatch")
    if receipt.get("manifest_sha256") != sha256(manifest_path):
        failures.append("public_release_manifest_sha256_mismatch")
    try:
        built_at = _parse_utc(receipt.get("built_at"), field="built_at")
        if built_at > (checked_at or dt.datetime.now(dt.UTC)):
            failures.append("public_release_receipt_from_future")
    except ValueError as exc:
        built_at = None
        failures.append(str(exc))

    rows = receipt.get("files") or []
    if not isinstance(rows, list):
        rows = []
        failures.append("public_release_files_not_list")
    receipted_paths = [str(row.get("path") or "") for row in rows if isinstance(row, dict)]
    if len(receipted_paths) != len(set(receipted_paths)):
        failures.append("public_release_duplicate_receipt_path")
    if set(receipted_paths) != expected_paths:
        failures.append("public_release_inventory_mismatch")
    actual_inventory = {
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    }
    if actual_inventory != expected_paths | {"PUBLIC_RELEASE_RECEIPT.json"}:
        failures.append("public_release_destination_inventory_mismatch")

    total_bytes = 0
    source_mismatches: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            failures.append("public_release_invalid_file_record")
            continue
        relative = str(row.get("path") or "")
        try:
            packaged = _relative_file(release_root, relative)
            source = _relative_file(source_root, relative)
        except ValueError:
            failures.append(f"public_release_unsafe_path:{relative}")
            continue
        if packaged.is_symlink() or not packaged.is_file():
            failures.append(f"public_release_missing_or_symlink:{relative}")
            continue
        size = packaged.stat().st_size
        total_bytes += size
        if size != row.get("bytes"):
            failures.append(f"public_release_size_mismatch:{relative}")
            continue
        packaged_hash = sha256(packaged)
        if packaged_hash != row.get("sha256"):
            failures.append(f"public_release_hash_mismatch:{relative}")
        # This file is deliberately regenerated against the curated tree.
        if relative != "container/runtime_manifest.json":
            if not source.is_file() or sha256(source) != packaged_hash:
                source_mismatches.append(relative)
    if source_mismatches:
        failures.append("public_release_not_bound_to_current_source")
    if len(rows) != receipt.get("file_count") or len(rows) != len(expected_paths):
        failures.append("public_release_file_count_mismatch")
    if total_bytes != receipt.get("total_bytes"):
        failures.append("public_release_total_bytes_mismatch")
    return {
        "status": "pass" if not failures else "blocked",
        "root": str(release_root),
        "path": str(receipt_path),
        "receipt_sha256": sha256(receipt_path),
        "manifest_sha256": sha256(manifest_path),
        "built_at": built_at.isoformat().replace("+00:00", "Z") if built_at else None,
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "source_mismatches": source_mismatches[:20],
        "failures": failures,
    }


def verify_output_start_state(root: Path, relative: str) -> dict[str, Any]:
    try:
        path = _relative_file(root, relative)
    except ValueError as exc:
        return {"status": "blocked", "path": str(relative), "files": [], "failures": [str(exc)]}
    files = sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file()) if path.is_dir() else []
    failures = ["benchmark_output_not_fresh"] if files or (path.exists() and not path.is_dir()) else []
    return {
        "status": "pass" if not failures else "blocked",
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "files": files[:20],
        "failures": failures,
    }


def _trials(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    trials = (plan.get("replication") or {}).get("trials") or []
    if trials:
        return [dict(row) for row in trials]
    return [
        {
            "trial_id": "trial-000",
            "generation_seed": None,
            "verification_seed": None,
            "case_order_seed": None,
            "judge_seed": None,
        }
    ]


def _run_output_dir(plan: Mapping[str, Any], model: Mapping[str, Any], trial: Mapping[str, Any]) -> str:
    internal = plan["internal_benchmark"]
    if internal.get("output_layout"):
        rendered = str(internal["output_layout"]).format(
            output_root=internal["output_root"],
            model_key=model["model_key"],
            trial_id=trial["trial_id"],
        )
        candidate = Path(rendered)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"unsafe output layout result: {rendered}")
        return candidate.as_posix()
    return str(internal["output_dir"])


def verify_output_schedule(root: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    identities: list[dict[str, Any]] = []
    output_paths: list[str] = []
    for model in plan.get("models") or []:
        for trial in _trials(plan):
            try:
                output = _run_output_dir(plan, model, trial)
            except (KeyError, ValueError) as exc:
                failures.append(f"invalid_output_identity:{exc}")
                continue
            output_paths.append(output)
            identities.append(
                {
                    "model_key": model.get("model_key"),
                    "trial_id": trial.get("trial_id"),
                    "output_dir": output,
                    "invocation_receipt": f"{output}/invocations/{model.get('model_key')}__{trial.get('trial_id')}.json",
                }
            )
    if len(output_paths) != len(set(output_paths)):
        failures.append("per_model_trial_output_collision")
    internal = plan.get("internal_benchmark") or {}
    root_relative = str(internal.get("output_root") or internal.get("output_dir") or "")
    root_state = verify_output_start_state(root, root_relative)
    failures.extend(root_state.get("failures") or [])
    return {
        "status": "pass" if not failures else "blocked",
        "output_root": root_state,
        "planned_identity_count": len(identities),
        "planned_identities": identities,
        "failures": failures,
    }


def verify_egress_authorization(
    path: Path | None,
    *,
    benchmark_id: str,
    suite_sha256: str,
    required_payloads: list[str],
    forbidden_payloads: list[str],
    checked_at: dt.datetime | None = None,
) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"status": "blocked", "failures": ["egress_authorization_missing"]}
    try:
        payload = _load_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "path": str(path), "failures": [f"egress_authorization_unreadable:{type(exc).__name__}"]}
    failures: list[str] = []
    if payload.get("schema_version") != EGRESS_SCHEMA:
        failures.append("schema_mismatch")
    if payload.get("authorization_decision") != "authorized":
        failures.append("authorization_decision_not_authorized")
    if payload.get("benchmark_id") != benchmark_id:
        failures.append("benchmark_id_mismatch")
    if payload.get("benchmark_suite_sha256") != suite_sha256:
        failures.append("suite_sha256_mismatch")
    source = payload.get("authorization_source")
    key_id = payload.get("authorized_by_key_id")
    if _is_placeholder(source) or _is_placeholder(key_id):
        failures.append("human_authority_provenance_missing_or_placeholder")
    authorized = list(payload.get("authorized_payload_classes") or [])
    excluded = list(payload.get("excluded_payload_classes") or [])
    if len(authorized) != len(set(authorized)) or set(authorized) != set(required_payloads):
        failures.append("authorized_payload_classes_not_exact")
    if len(excluded) != len(set(excluded)) or set(excluded) != set(forbidden_payloads):
        failures.append("excluded_payload_classes_not_exact")
    if set(authorized) & set(excluded):
        failures.append("authorized_and_excluded_payload_classes_overlap")
    if set(forbidden_payloads) & set(authorized):
        failures.append("forbidden_payload_class_authorized")
    try:
        authorized_at = _parse_utc(payload.get("authorized_at"), field="authorized_at")
    except ValueError as exc:
        authorized_at = None
        failures.append(str(exc))
    try:
        expires_at = _parse_utc(payload.get("expires_at"), field="expires_at")
    except ValueError as exc:
        expires_at = None
        failures.append(str(exc))
    now = checked_at or dt.datetime.now(dt.UTC)
    if authorized_at and expires_at:
        if expires_at <= authorized_at:
            failures.append("authorization_validity_interval_invalid")
        if authorized_at > now:
            failures.append("authorization_not_yet_valid")
        if expires_at <= now:
            failures.append("authorization_expired")
    return {
        "status": "pass" if not failures else "blocked",
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "authorization_decision": payload.get("authorization_decision"),
        "authorization_source": source,
        "authorized_by_key_id": key_id,
        "authorized_at": payload.get("authorized_at"),
        "expires_at": payload.get("expires_at"),
        "authorized_payload_classes": authorized,
        "excluded_payload_classes": excluded,
        "failures": failures,
    }


def verify_judge_calibration(
    path: Path | None,
    *,
    root: Path,
    judge_contract: Mapping[str, Any],
) -> dict[str, Any]:
    if path is None:
        return {
            "status": "blocked_not_requested",
            "judge_execution_enabled": False,
            "failures": ["judge_calibration_not_supplied"],
        }
    if not path.is_file():
        return {"status": "blocked", "judge_execution_enabled": False, "failures": ["judge_calibration_missing"]}
    failures: list[str] = []
    try:
        payload = _load_object(path)
        schema_path = _relative_file(root, judge_contract.get("calibration_schema_path"))
        schema = _load_object(schema_path)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        schema_errors = [
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}:{error.message}"
            for error in sorted(validator.iter_errors(payload), key=lambda row: list(row.absolute_path))
        ]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "blocked",
            "judge_execution_enabled": False,
            "path": str(path),
            "failures": [f"judge_calibration_unreadable:{type(exc).__name__}"],
        }
    if schema_errors:
        failures.append("judge_calibration_schema_invalid")
    if payload.get("schema_version") != JUDGE_CALIBRATION_SCHEMA:
        failures.append("judge_calibration_schema_mismatch")
    if payload.get("status") != "calibrated_pass":
        failures.append("judge_calibration_not_passed")
    judge = payload.get("judge") if isinstance(payload.get("judge"), dict) else {}
    if judge.get("backend") != judge_contract.get("backend"):
        failures.append("judge_backend_mismatch")
    if judge.get("model_id") != judge_contract.get("model"):
        failures.append("judge_model_mismatch")
    if judge.get("role") not in set(judge_contract.get("roles") or []):
        failures.append("judge_role_mismatch")
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    placeholders = [field for field, value in artifacts.items() if _is_placeholder_digest(value)]
    if placeholders:
        failures.append("judge_calibration_artifact_digest_placeholder")
    thresholds = (
        payload.get("acceptance_thresholds")
        if isinstance(payload.get("acceptance_thresholds"), dict)
        else {}
    )
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    try:
        metrics_pass = bool(thresholds and observed) and (
            float(observed.get("macro_f1", -1)) >= float(thresholds.get("macro_f1", 2))
            and float(observed.get("false_positive_rate", 2))
            <= float(thresholds.get("false_positive_rate", -1))
            and float(observed.get("false_negative_rate", 2))
            <= float(thresholds.get("false_negative_rate", -1))
            and float(observed.get("order_flip_rate", 2))
            <= float(thresholds.get("order_flip_rate", -1))
        )
    except (TypeError, ValueError):
        metrics_pass = False
    if not metrics_pass:
        failures.append("judge_calibration_metrics_below_threshold")
    if payload.get("human_adjudication_authoritative") is not True:
        failures.append("human_adjudication_not_authoritative")
    if payload.get("candidate_self_judgment_is_sole_release_evidence") is not False:
        failures.append("candidate_self_judgment_boundary_invalid")
    return {
        "status": "pass" if not failures else "blocked",
        "judge_execution_enabled": not failures,
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "calibration_id": payload.get("calibration_id"),
        "judge_model": judge.get("model_id"),
        "schema_errors": schema_errors,
        "placeholder_digest_fields": placeholders,
        "metrics_pass": metrics_pass,
        "failures": failures,
    }


def verify_local_model(root: Path, hub_cache: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    try:
        config_path = _relative_file(root, record["config_path"])
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, KeyError, ValueError, yaml.YAMLError) as exc:
        return {"status": "blocked", "model_key": record.get("model_key"), "failures": [f"model_profile_unreadable:{type(exc).__name__}"]}
    model_id = str(config.get("serving_model_id") or config.get("model_id") or "")
    revision = str(config.get("model_revision") or "")
    if sha256(config_path) != record.get("config_sha256"):
        failures.append("config_sha256_mismatch")
    if model_id != record.get("model_id"):
        failures.append("model_id_mismatch")
    if revision != record.get("revision"):
        failures.append("revision_mismatch")
    snapshot = hub_cache / ("models--" + model_id.replace("/", "--")) / "snapshots" / revision
    files = sorted((path for path in snapshot.rglob("*") if path.is_file()), key=lambda path: path.relative_to(snapshot).as_posix()) if snapshot.is_dir() else []
    names = {path.name for path in files}
    weights = [path for path in files if path.name.endswith((".safetensors", ".gguf", ".npz"))]
    if not snapshot.is_dir():
        failures.append("exact_revision_snapshot_missing")
    elif not ({"config.json", "tokenizer_config.json"} <= names):
        failures.append("model_metadata_incomplete")
    elif not ({"tokenizer.json", "tokenizer.model"} & names):
        failures.append("tokenizer_missing")
    elif not weights or not all(path.resolve().stat().st_size > 0 for path in weights):
        failures.append("weights_missing_or_empty")
    aggregate = hashlib.sha256()
    snapshot_bytes = 0
    for path in files:
        resolved = path.resolve()
        try:
            resolved.relative_to(hub_cache.resolve())
        except ValueError:
            failures.append(f"snapshot_file_outside_hub_cache:{path.name}")
            continue
        size = resolved.stat().st_size
        snapshot_bytes += size
        aggregate.update(path.relative_to(snapshot).as_posix().encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(size).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(resolved.name.encode("utf-8"))
        aggregate.update(b"\n")
    return {
        "status": "pass" if not failures else "blocked",
        "model_key": record.get("model_key"),
        "model_id": model_id,
        "revision": revision,
        "snapshot": str(snapshot),
        "snapshot_file_count": len(files),
        "snapshot_bytes": snapshot_bytes,
        "snapshot_file_identity_sha256": aggregate.hexdigest() if files else None,
        "identity_boundary": "relative_path_plus_resolved_blob_name_and_size; model revision is pinned but weight bytes are not rehashed by this preflight",
        "failures": failures,
    }


def _append_option(command: list[str], flag: str, value: object) -> None:
    if value is not None:
        command.extend([flag, str(value)])


def build_benchmark_command(
    plan: Mapping[str, Any],
    model: Mapping[str, Any],
    egress_authorization: Path,
    trial: Mapping[str, Any] | None = None,
    *,
    calibrated_judge: bool = False,
) -> list[str]:
    """Build one isolated model-by-trial command from the frozen plan."""

    internal = plan["internal_benchmark"]
    trial = dict(trial or _trials(plan)[0])
    command = [
        ".venv/bin/python",
        "scripts/run_open_agronomy_benchmark.py",
        "--evaluation-set",
        "internal",
        "--contract",
        str(internal["contract_path"]),
        "--model-config",
        str(model["config_path"]),
        "--model-key",
        str(model["model_key"]),
        "--modes",
        ",".join(internal["arms"]),
        "--output-dir",
        _run_output_dir(plan, model, trial),
        "--trial-id",
        str(trial["trial_id"]),
    ]
    replication = plan.get("replication") or {}
    sampling = replication.get("sampling") or {}
    _append_option(command, "--generation-seed", trial.get("generation_seed"))
    _append_option(command, "--verification-seed", trial.get("verification_seed"))
    _append_option(command, "--case-order-seed", trial.get("case_order_seed"))
    _append_option(command, "--judge-seed", trial.get("judge_seed"))
    _append_option(command, "--temperature", sampling.get("temperature"))
    _append_option(command, "--top-p", sampling.get("top_p"))
    _append_option(command, "--top-k", sampling.get("top_k"))
    _append_option(command, "--process-isolation-policy", replication.get("process_isolation_policy"))
    _append_option(command, "--cache-policy", replication.get("cache_policy"))
    command.extend(
        [
            "--egress-authorization",
            str(egress_authorization.resolve()),
            "--build-review-packet",
            "--resume-partial-runs",
        ]
    )
    if model.get("backend") == "codex_app_server":
        command.extend(["--codex-app-server", "--reasoning-effort", str(model.get("reasoning_effort") or "high")])
    judge = plan.get("judge") or {}
    same_exact_model = model.get("model_id") == judge.get("model")
    if calibrated_judge and not same_exact_model:
        command.extend(
            [
                "--judge",
                "--judge-backend",
                str(judge["backend"]),
                "--judge-model",
                str(judge["model"]),
                "--judge-reasoning-effort",
                str(judge["reasoning_effort"]),
                "--judge-roles",
                ",".join(judge["roles"]),
            ]
        )
    return command


def run_interface_probes(root: Path, rag_config_path: Path) -> dict[str, Any]:
    config = str(rag_config_path)
    explicit = build_context(
        "For a Saskatchewan field, can an NRCS ecological site be used as a cross-border analogue for soil water and ecological dynamics?",
        config,
        use_context_cache=False,
        use_search_cache=False,
    )
    ordinary = build_context(
        "A Saskatchewan field has wet depressions and poor emergence. What should I inspect before changing drainage?",
        config,
        field_context={"crop_current": "spring wheat", "province_state": "Saskatchewan"},
        use_context_cache=False,
        use_search_cache=False,
    )
    saskatchewan_rate = build_context(
        "Set an exact nitrogen rate for my Saskatchewan spring wheat field after a wet spring.",
        config,
        field_context={"crop_current": "spring wheat", "province_state": "Saskatchewan"},
        use_context_cache=False,
        use_search_cache=False,
    )
    explicit_docs = [doc for doc in explicit.retrieved_docs if doc.transfer_scope == "cross_border_analogue"]
    ordinary_docs = [doc for doc in ordinary.retrieved_docs if doc.transfer_scope == "cross_border_analogue"]
    boundaries = list((saskatchewan_rate.runtime_metadata or {}).get("canadian_coverage_boundaries") or [])
    sk_boundary = next((row for row in boundaries if row.get("jurisdiction") == "Saskatchewan"), {})
    explicit_packed = explicit.packed_context.text if explicit.packed_context else ""
    sk_packed = saskatchewan_rate.packed_context.text if saskatchewan_rate.packed_context else ""
    return {
        "nrcs_explicit_analogue": {
            "passed": bool(explicit_docs)
            and all(doc.retrieval_policy == "context_only" for doc in explicit_docs)
            and "US CROSS-BORDER ANALOGUE" in explicit_packed
            and "never treat as Canadian field truth" in explicit_packed,
            "doc_ids": [doc.doc_id for doc in explicit_docs],
        },
        "nrcs_ordinary_canadian_exclusion": {
            "passed": not ordinary_docs,
            "unexpected_doc_ids": [doc.doc_id for doc in ordinary_docs],
        },
        "saskatchewan_fail_closed": {
            "passed": sk_boundary.get("status") == "live_reference_only"
            and sk_boundary.get("requires_prompt_boundary") is True
            and "no province-specific applied-guidance document" in sk_packed
            and not saskatchewan_rate.retrieved_docs,
            "status": sk_boundary.get("status"),
            "retrieved_doc_ids": [doc.doc_id for doc in saskatchewan_rate.retrieved_docs],
            "live_reference_source_ids": [row.get("source_id") for row in sk_boundary.get("live_references") or []],
        },
    }


def audit(
    *,
    root: Path,
    plan_path: Path,
    hub_cache: Path,
    egress_authorization: Path | None,
    public_release_root: Path | None,
    environment_receipt: Path | None,
    judge_calibration: Path | None = None,
    checked_at: dt.datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    plan = _load_object(plan_path)
    checks: list[dict[str, Any]] = []
    plan_validation = validate_plan_semantics(plan)
    _check(
        checks,
        "plan_contract",
        plan_validation["status"] == "pass",
        "the selected plan is supported and preserves its declared non-claim, retirement, replication, and egress boundaries",
        {**plan_validation, "path": str(plan_path), "sha256": sha256(plan_path)},
    )

    source = verify_source_checkout(
        root,
        branch=str(plan.get("release_branch") or ""),
        require_clean=bool((plan.get("readiness") or {}).get("require_clean_git", True)),
    )
    _check(
        checks,
        "clean_source_checkout_receipt",
        source["status"] == "pass",
        "source identity is the named clean committed branch",
        source,
    )

    internal_record = plan["internal_benchmark"]
    external_record = plan["external_diagnostic"]
    internal_contract_ok, internal_contract_evidence = _file_record(
        root, internal_record, path_key="contract_path", hash_key="contract_sha256"
    )
    internal_suite_ok, internal_suite_evidence = _file_record(
        root, internal_record, path_key="suite_path", hash_key="suite_sha256"
    )
    internal_manifest = validate_benchmark(root, root / internal_record["contract_path"])
    _check(
        checks,
        "frozen_internal_development_benchmark",
        internal_contract_ok
        and internal_suite_ok
        and internal_manifest.get("rows") == internal_record["rows"]
        and internal_manifest.get("evaluation_partition") == "internal"
        and internal_manifest.get("claim_eligible") is False,
        "internal contract and suite are exact, exposed, project-owned development evidence",
        {
            "contract": internal_contract_evidence,
            "suite": internal_suite_evidence,
            "manifest_suite_sha256": internal_manifest.get("suite_sha256"),
            "rows": internal_manifest.get("rows"),
        },
    )

    external_contract_ok, external_contract_evidence = _file_record(
        root, external_record, path_key="contract_path", hash_key="contract_sha256"
    )
    external_suite_ok, external_suite_evidence = _file_record(
        root, external_record, path_key="suite_path", hash_key="suite_sha256"
    )
    external_manifest = validate_benchmark(root, root / external_record["contract_path"])
    is_development_round = plan.get("schema_version") in {
        "open_agronomy_agent.final_benchmark_round.v2",
        "open_agronomy_agent.final_benchmark_round.v3",
    }
    retirement_ok = (
        external_record.get("lifecycle") == "retired_after_rc1_exposure"
        and external_record.get("execution_allowed") is False
        and external_record.get("rerun_command_emitted") is False
    ) if is_development_round else True
    _check(
        checks,
        "external_agroqa_v1_frozen_and_retired",
        external_contract_ok
        and external_suite_ok
        and external_manifest.get("suite_sha256") == external_record["suite_sha256"]
        and external_manifest.get("rows") == external_record["rows"]
        and external_manifest.get("evaluation_partition") == "public"
        and retirement_ok,
        "the exposed AgroQA v1 transfer artifact is retained byte-for-byte but cannot be rerun in the selected development round",
        {
            "contract": external_contract_evidence,
            "suite": external_suite_evidence,
            "lifecycle": external_record.get("lifecycle"),
            "execution_allowed": external_record.get("execution_allowed"),
            "rerun_command_emitted": external_record.get("rerun_command_emitted"),
        },
    )

    construct_path = root / "data/eval/open_agronomy_canadian_performance_v1_construct_audit.json"
    construct = _load_object(construct_path)
    _check(
        checks,
        "benchmark_construct_boundary",
        construct.get("status") == "development_construct_only"
        and construct.get("construct_verdict", {}).get("primary_capability_claim_eligible") is False
        and construct.get("current_suite", {}).get("rows") == internal_record["rows"],
        "construct audit preserves the development-only claim boundary",
        {"path": str(construct_path), "sha256": sha256(construct_path)},
    )

    separation = build_separation_audit(
        root / internal_record["contract_path"],
        root / external_record["contract_path"],
    )
    _check(
        checks,
        "internal_external_separation",
        separation.get("status") == "pass",
        "retained internal and external artifacts remain separated even though external v1 is retired",
        {
            "maximum_token_jaccard": separation.get("question_overlap", {}).get("maximum_token_jaccard"),
            "rag_exact_matches": separation.get("rag_contamination", {}).get("exact_public_question_match_count"),
        },
    )

    internal_contract = _load_object(root / internal_record["contract_path"])
    rag_config_path = _relative_file(root, internal_contract.get("rag_config"))
    runtime_profile = internal_record.get("runtime_profile") or {}
    runtime_binding_failures: list[str] = []
    runtime_binding_evidence: dict[str, Any] = {
        "contract_rag_config": internal_contract.get("rag_config"),
        "declared_master_profile_id": runtime_profile.get("master_profile_id"),
    }
    if plan.get("schema_version") == "open_agronomy_agent.final_benchmark_round.v3":
        if runtime_profile.get("rag_config_path") != internal_contract.get("rag_config"):
            runtime_binding_failures.append("contract_runtime_profile_path_mismatch")
        for path_key, hash_key in (
            ("rag_config_path", "rag_config_sha256"),
            ("registry_path", "registry_sha256"),
            ("policy_path", "policy_sha256"),
            ("knowledge_release_manifest_path", "knowledge_release_manifest_sha256"),
        ):
            exact, evidence = _file_record(
                root,
                runtime_profile,
                path_key=path_key,
                hash_key=hash_key,
            )
            runtime_binding_evidence[path_key] = evidence
            if not exact:
                runtime_binding_failures.append(f"{path_key}_receipt_mismatch")
        try:
            store_manifest = _load_object(
                _relative_file(root, runtime_profile.get("knowledge_release_manifest_path"))
            )
            profile_ids = {
                str(item.get("profile_id") or "")
                for item in store_manifest.get("profiles") or []
                if isinstance(item, dict)
            }
            if store_manifest.get("store_id") != runtime_profile.get("knowledge_release_id"):
                runtime_binding_failures.append("knowledge_release_id_mismatch")
            if runtime_profile.get("master_profile_id") not in profile_ids:
                runtime_binding_failures.append("master_profile_absent_from_release")
            if int((store_manifest.get("totals") or {}).get("rows") or -1) != int(
                runtime_profile.get("knowledge_release_rows") or -2
            ):
                runtime_binding_failures.append("knowledge_release_row_count_mismatch")
            runtime_binding_evidence["store_id"] = store_manifest.get("store_id")
            runtime_binding_evidence["profile_ids"] = sorted(profile_ids)
            runtime_binding_evidence["rows"] = (store_manifest.get("totals") or {}).get("rows")
        except (OSError, TypeError, ValueError) as exc:
            runtime_binding_failures.append("knowledge_release_manifest_invalid")
            runtime_binding_evidence["knowledge_release_error"] = str(exc)
    _check(
        checks,
        "benchmark_runtime_profile_binding",
        not runtime_binding_failures,
        "the benchmark contract, active runtime profile, corpus policy, and immutable master knowledge release are hash-bound",
        {**runtime_binding_evidence, "failures": runtime_binding_failures},
    )

    runtime = audit_runtime_corpora(root=root, rag_config_path=rag_config_path)
    _check(
        checks,
        "runtime_corpus_governance",
        runtime.get("status") == "pass" and not runtime.get("errors"),
        "configured runtime corpora pass policy and hash validation",
        {"audited_corpus_count": runtime.get("audited_corpus_count"), "row_counts": runtime.get("row_counts_by_eligibility")},
    )

    retention_path = _relative_file(
        root,
        (plan.get("release_receipts") or {}).get("source_retention_receipt", "data/manifests/source_retention_receipt.json"),
    )
    retention = _load_object(retention_path)
    _check(
        checks,
        "source_retention_receipt",
        retention.get("status") == "pass"
        and retention.get("deletion_authorized") is False
        and all((retention.get("checks") or {}).values()),
        "source bytes and derived lineage remain retained; the receipt authorizes no deletion",
        {"path": str(retention_path), "sha256": sha256(retention_path)},
    )

    environment = verify_environment_receipt(
        root,
        environment_receipt,
        git_commit=source.get("commit"),
        checked_at=checked_at,
    )
    _check(
        checks,
        "exact_environment_receipt",
        environment["status"] == "pass",
        "the observed installed environment is bound to this clean commit and current dependency inputs",
        environment,
    )

    manifest_path = _relative_file(
        root,
        (plan.get("release_receipts") or {}).get("public_repository_manifest", "configs/public_repository_manifest.json"),
    )
    public_receipt = verify_public_release_receipt(
        root,
        public_release_root,
        manifest_path=manifest_path,
        checked_at=checked_at,
    )
    _check(
        checks,
        "exact_public_package_receipt",
        public_receipt["status"] == "pass",
        "the fresh public package has the exact current manifest inventory and a byte-valid receipt",
        public_receipt,
    )

    output_start = verify_output_schedule(root, plan)
    _check(
        checks,
        "fresh_per_model_trial_outputs",
        output_start["status"] == "pass",
        "each model-by-trial execution has a unique fresh output and durable invocation identity",
        output_start,
    )

    disk = shutil.disk_usage(root)
    minimum_free = int((plan.get("readiness") or {}).get("minimum_free_disk_bytes") or 0)
    _check(
        checks,
        "free_disk",
        disk.free >= minimum_free,
        "free disk meets the bounded benchmark-output floor",
        {"free_bytes": disk.free, "minimum_free_bytes": minimum_free},
    )
    _check(
        checks,
        "mlx_runtime",
        importlib.util.find_spec("mlx") is not None and importlib.util.find_spec("mlx_lm") is not None,
        "MLX and mlx_lm are importable in the selected receipted environment",
    )

    model_receipts: list[dict[str, Any]] = []
    for model in plan["models"]:
        if model["backend"] == "mlx_local":
            receipt = verify_local_model(root, hub_cache, model)
        else:
            config_path = _relative_file(root, model["config_path"])
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            exact = (
                sha256(config_path) == model["config_sha256"]
                and (config.get("serving_model_id") or config.get("model_id")) == model["model_id"]
                and config.get("model_revision") == model.get("revision")
            )
            receipt = {
                "status": "pass" if exact else "blocked",
                "model_key": model["model_key"],
                "model_id": model["model_id"],
                "revision": model.get("revision"),
                "backend": model["backend"],
                "config_path": str(config_path),
                "config_sha256": sha256(config_path),
                "failures": [] if exact else ["remote_profile_mismatch"],
            }
        model_receipts.append(receipt)
    _check(
        checks,
        "model_profiles_and_exact_local_snapshots",
        all(row["status"] == "pass" for row in model_receipts),
        "local models resolve only to their pinned revisions and the remote model profile is exact",
        {"hub_cache": str(hub_cache.resolve()), "models": model_receipts},
    )

    egress_contract = plan["egress"]
    required_payloads = list(
        egress_contract.get("authorized_payload_classes_exact")
        or egress_contract.get("authorized_payload_classes_required")
        or []
    )
    forbidden_payloads = list(
        egress_contract.get("excluded_payload_classes_exact")
        or egress_contract.get("payload_classes_forbidden")
        or []
    )
    egress = verify_egress_authorization(
        egress_authorization,
        benchmark_id=str(internal_manifest["benchmark_id"]),
        suite_sha256=str(internal_manifest["suite_sha256"]),
        required_payloads=required_payloads,
        forbidden_payloads=forbidden_payloads,
        checked_at=checked_at,
    )
    _check(
        checks,
        "suite_bound_egress_authorization_v2",
        egress["status"] == "pass",
        "a current human authority exactly allows benchmark payloads and excludes private/corpus payloads",
        egress,
    )

    judge = verify_judge_calibration(
        judge_calibration,
        root=root,
        judge_contract=plan.get("judge") or {},
    )
    judge_requested = judge_calibration is not None
    judge_gate_passed = judge["status"] == "pass" if judge_requested else (
        (plan.get("judge") or {}).get("default_enabled") is False
        and judge["status"] == "blocked_not_requested"
    )
    _check(
        checks,
        "semantic_judge_calibration_gate",
        judge_gate_passed,
        (
            "a supplied real calibration receipt permits advisory judging"
            if judge_requested
            else "no calibration was supplied, so semantic judging remains safely omitted from every command"
        ),
        judge,
    )

    probes = run_interface_probes(root, rag_config_path)
    _check(
        checks,
        "release_interface_probes",
        all(row.get("passed") for row in probes.values()),
        "NRCS transfer and Saskatchewan evidence-gap behavior are fail-closed",
        probes,
    )

    calibrated_judge = bool(judge.get("judge_execution_enabled"))
    commands = [
        build_benchmark_command(
            plan,
            model,
            egress_authorization or Path("EGRESS_AUTHORIZATION_REQUIRED"),
            trial,
            calibrated_judge=calibrated_judge,
        )
        for model in plan["models"]
        for trial in _trials(plan)
    ]
    command_outputs = [command[command.index("--output-dir") + 1] for command in commands]
    command_trials = [command[command.index("--trial-id") + 1] for command in commands]
    external_tokens = {"external", "open_agronomy_external_agroqa_v1", "agroqa"}
    emits_external = any(any(token.lower() in external_tokens for token in command) for command in commands)
    explicit_replication_flags = {
        "--trial-id",
        "--generation-seed",
        "--verification-seed",
        "--case-order-seed",
        "--judge-seed",
        "--temperature",
        "--top-p",
        "--top-k",
        "--process-isolation-policy",
        "--cache-policy",
    }
    command_contract_ok = (
        len(commands) == len(plan["models"]) * len(_trials(plan))
        and len(command_outputs) == len(set(command_outputs))
        and all(explicit_replication_flags <= set(command) for command in commands)
        and not emits_external
        and all(trial_id in {row["trial_id"] for row in _trials(plan)} for trial_id in command_trials)
    )
    _check(
        checks,
        "command_identity_and_external_retirement",
        command_contract_ok,
        "commands are explicit, isolated model-by-trial internal runs and emit no AgroQA v1 rerun",
        {
            "command_count": len(commands),
            "unique_output_count": len(set(command_outputs)),
            "external_command_emitted": emits_external,
            "external_diagnostic_commands": [],
        },
    )

    failures = [row for row in checks if not row["passed"]]
    status = "ready" if not failures else "blocked"
    readiness_schema = (
        "open_agronomy_agent.final_benchmark_readiness.v3"
        if plan.get("schema_version") == "open_agronomy_agent.final_benchmark_round.v3"
        else "open_agronomy_agent.final_benchmark_readiness.v2"
    )
    return {
        "schema_version": readiness_schema,
        "status": status,
        "round_id": plan.get("round_id"),
        "round_class": plan.get("round_class"),
        "claim_eligible": False,
        "benchmark_layer": plan.get("benchmark_layer"),
        "root": str(root),
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": sha256(plan_path),
        "git_commit": source.get("commit"),
        "network_requests_performed": 0,
        "generation_performed": False,
        "judging_performed": False,
        "judge_execution_enabled": calibrated_judge,
        "judge_same_model_exclusion": "a Luna candidate command never asks the same exact Luna model to judge itself",
        "v3_boundary": plan.get("v3_boundary"),
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "command_status": "executable_after_pass" if status == "ready" else "planned_only_blocked_by_preflight",
        "benchmark_commands": commands,
        "external_diagnostic_commands": [],
        "external_diagnostic_policy": external_record["use_policy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--hub-cache", type=Path, default=None)
    parser.add_argument("--egress-authorization", type=Path, required=True)
    parser.add_argument("--public-release-root", type=Path, required=True)
    parser.add_argument("--environment-receipt", type=Path, required=True)
    parser.add_argument(
        "--judge-calibration",
        type=Path,
        help="Optional real calibrated-pass receipt. Without it, no emitted command enables semantic judging.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path | None, *, relative_to_root: bool = True) -> Path | None:
        if path is None:
            return None
        if path.is_absolute() or not relative_to_root:
            return path.resolve()
        return (root / path).resolve()

    plan_path = resolved(args.plan)
    assert plan_path is not None
    hub_cache = args.hub_cache or Path(os.getenv("HF_HUB_CACHE") or root / ".hf_cache/hub")
    output = resolved(args.output)
    assert output is not None
    report = audit(
        root=root,
        plan_path=plan_path,
        hub_cache=hub_cache.resolve(),
        egress_authorization=resolved(args.egress_authorization),
        public_release_root=resolved(args.public_release_root),
        environment_receipt=resolved(args.environment_receipt),
        judge_calibration=resolved(args.judge_calibration),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
