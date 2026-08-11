#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agronomy_agent.artifact_signature import verify_manifest_signature
from agronomy_agent.corpus_governance import CORPUS_AUDIT_IMPLEMENTATION_PATHS
from agronomy_agent.operator_attestation import (
    OPERATOR_ATTESTATION_SCHEMA,
    validate_volume_encryption_evidence,
)
from agronomy_agent.recovery_evidence import validate_second_machine_restore_receipt
from agronomy_agent.security_evidence import validate_implementation_binding


OPERATOR_CONTROL_IDS = (
    "volume_encryption",
    "off_device_backup_restore",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEVICE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OBSERVATION_CLOCK_TOLERANCE = timedelta(minutes=5)
_MAX_EVIDENCE_TO_ISSUANCE_DELAY = timedelta(hours=24)
_MAX_ATTESTATION_VALIDITY = timedelta(days=7)
_REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_BACKUP_IMPLEMENTATION_PATHS = (
    "scripts/run_backup_restore_drill.py",
    "src/agronomy_agent/field_events.py",
    "src/agronomy_agent/knowledge_update_trust.py",
    "src/agronomy_agent/knowledge_updates.py",
    "src/agronomy_agent/security_evidence.py",
    "src/agronomy_agent/server/storage/backup.py",
)
ENCRYPTED_BACKUP_IMPLEMENTATION_PATHS = (
    "scripts/run_encrypted_backup_recovery_drill.py",
    "src/agronomy_agent/security_evidence.py",
    "src/agronomy_agent/server/storage/backup.py",
    "src/agronomy_agent/server/storage/encrypted_backup.py",
)
KNOWLEDGE_TRUST_IMPLEMENTATION_PATHS = (
    "scripts/run_knowledge_update_trust_rotation_drill.py",
    "src/agronomy_agent/artifact_signature.py",
    "src/agronomy_agent/knowledge_update_trust.py",
    "src/agronomy_agent/knowledge_updates.py",
    "src/agronomy_agent/security_evidence.py",
)
KNOWLEDGE_ACTIVATION_RECOVERY_IMPLEMENTATION_PATHS = (
    "scripts/run_knowledge_update_activation_recovery_drill.py",
    "src/agronomy_agent/artifact_signature.py",
    "src/agronomy_agent/knowledge_update_trust.py",
    "src/agronomy_agent/knowledge_updates.py",
    "src/agronomy_agent/security_evidence.py",
    "tests/test_knowledge_updates.py",
)
RESTORE_JOURNAL_IMPLEMENTATION_PATHS = (
    "scripts/run_restore_journal_recovery_drill.py",
    "src/agronomy_agent/security_evidence.py",
    "src/agronomy_agent/server/storage/backup.py",
)
RESTORE_PREPARED_CHECKPOINTS = (
    "prepared_journal_pending_fsynced",
    "journal_prepared",
    "prepared_database_previous_renamed",
    "prepared_database_target_installed",
    "prepared_artifacts_previous_renamed",
    "prepared_artifacts_target_installed",
    "prepared_knowledge_updates_previous_renamed",
    "prepared_knowledge_updates_target_installed",
    "committed_journal_pending_fsynced",
)
RESTORE_COMMITTED_CHECKPOINTS = (
    "committed_journal_persisted",
    "committed_database_previous_removed",
    "committed_artifacts_previous_removed",
    "committed_knowledge_updates_previous_removed",
    "committed_cleanup_complete",
    "journal_unlinked",
    "journal_removed",
)
RESTORE_CHECKPOINTS = (
    *RESTORE_PREPARED_CHECKPOINTS,
    *RESTORE_COMMITTED_CHECKPOINTS,
)


def _json_status(path: Path, expected_schema: str) -> tuple[bool, dict[str, Any] | None, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, None, str(exc)
    passed = payload.get("schema_version") == expected_schema and payload.get("status") == "pass"
    return passed, payload, "pass" if passed else "schema or status mismatch"


def _local_control_status(
    path: Path,
    control_id: str,
) -> tuple[bool, dict[str, Any] | None, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("receipt root must be an object")
        validators = {
            "local_backup_restore_drill": _validate_local_backup_drill,
            "encrypted_portable_backup_recovery_drill": (
                _validate_encrypted_backup_drill
            ),
            "threshold_knowledge_update_rotation_drill": (
                _validate_knowledge_trust_drill
            ),
            "knowledge_update_activation_sigkill_recovery": (
                _validate_knowledge_activation_recovery_drill
            ),
            "restore_journal_sigkill_checkpoint_matrix": (
                _validate_restore_journal_drill
            ),
            "runtime_corpus_governance": _validate_runtime_corpus_audit,
        }
        validator = validators.get(control_id)
        if validator is None:
            raise ValueError(f"unsupported local control: {control_id}")
        validator(payload)
        detail = (
            "pass; semantic checks and current implementation binding verified"
            if control_id != "runtime_corpus_governance"
            else "pass; corpus semantics and current audit implementation binding verified"
        )
        return True, payload, detail
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return False, None, str(exc)


def _require_schema_and_status(
    payload: dict[str, Any],
    schema: str,
) -> None:
    if payload.get("schema_version") != schema:
        raise ValueError(f"schema_version must be {schema}")
    if payload.get("status") != "pass":
        raise ValueError("receipt status must be pass")


def _require_true_checks(
    payload: dict[str, Any],
    expected: set[str],
    *,
    quick_check: str | None = None,
) -> dict[str, Any]:
    checks = payload.get("checks")
    if not isinstance(checks, dict) or set(checks) != expected:
        raise ValueError("receipt checks do not match the supported semantic contract")
    for field in expected:
        expected_value: Any = "ok" if field == quick_check else True
        if checks.get(field) != expected_value:
            raise ValueError(f"receipt check did not pass: {field}")
    return checks


def _validate_local_backup_drill(payload: dict[str, Any]) -> None:
    _require_schema_and_status(
        payload,
        "open_agronomy_agent.backup_restore_drill.v2",
    )
    checks = payload.get("checks")
    required = {
        "manifest_validated",
        "database_quick_check",
        "database_snapshot_sha256_match",
        "artifact_count_match",
        "knowledge_update_count_match",
        "field_event_chains_valid",
        "restored_knowledge_runtime_valid",
        "restored_release_files_read_only",
        "restore_journal_cleared",
    }
    if not isinstance(checks, dict) or set(checks) != required:
        raise ValueError("local backup checks do not match the supported contract")
    for field in required - {
        "database_quick_check",
        "restored_knowledge_runtime_valid",
        "restored_release_files_read_only",
    }:
        if checks.get(field) is not True:
            raise ValueError(f"local backup check did not pass: {field}")
    if checks.get("database_quick_check") != "ok":
        raise ValueError("local backup database quick_check did not pass")
    knowledge_count = payload.get("knowledge_update_file_count")
    if not isinstance(knowledge_count, int) or isinstance(knowledge_count, bool):
        raise ValueError("local backup knowledge_update_file_count is invalid")
    expected_knowledge = True if knowledge_count else "not_applicable"
    for field in (
        "restored_knowledge_runtime_valid",
        "restored_release_files_read_only",
    ):
        if checks.get(field) != expected_knowledge:
            raise ValueError(f"local backup {field} does not match backup content")
    chains = payload.get("field_event_chains")
    if not isinstance(chains, dict) or chains.get("valid") is not True:
        raise ValueError("local backup field-event chains are not valid")
    topology = payload.get("storage_topology")
    if (
        not isinstance(topology, dict)
        or topology.get("same_host") is not True
        or topology.get("second_machine") is not False
    ):
        raise ValueError("local backup topology must remain explicitly same-host")
    if payload.get("temporary_restore_removed") is not True:
        raise ValueError("local backup temporary restore cleanup did not pass")
    validate_implementation_binding(
        payload.get("implementation_binding"),
        expected_paths=LOCAL_BACKUP_IMPLEMENTATION_PATHS,
    )


def _validate_encrypted_backup_drill(payload: dict[str, Any]) -> None:
    _require_schema_and_status(
        payload,
        "open_agronomy_agent.encrypted_backup_recovery_drill.v1",
    )
    _require_true_checks(
        payload,
        {
            "source_backup_validated",
            "fresh_recipient_keypair",
            "private_key_mode_0600",
            "encrypted_bundle_mode_0600",
            "encrypted_bundle_hash_bound",
            "reviewed_bundle_sha256_bound",
            "plaintext_sqlite_header_absent",
            "header_marked_unauthenticated_before_decrypt",
            "authenticated_restore_passed",
            "exporter_authentication_not_inferred",
            "database_quick_check",
            "database_snapshot_sha256_match",
            "artifact_count_match",
            "knowledge_update_count_match",
            "wrong_key_and_tamper_matrix_rejected",
        },
        quick_check="database_quick_check",
    )
    expected_rejections = {
        "wrong_recipient_key",
        "reviewed_bundle_sha256_mismatch",
        "header_tamper",
        "ciphertext_tamper",
        "tag_tamper",
        "truncated_tamper",
    }
    _validate_rejection_matrix(payload, expected_rejections)
    if payload.get("temporary_plaintext_and_keys_removed") is not True:
        raise ValueError("encrypted backup temporary plaintext or keys were not removed")
    validate_implementation_binding(
        payload.get("implementation_binding"),
        expected_paths=ENCRYPTED_BACKUP_IMPLEMENTATION_PATHS,
    )


def _validate_knowledge_trust_drill(payload: dict[str, Any]) -> None:
    _require_schema_and_status(
        payload,
        "open_agronomy_agent.knowledge_update_trust_rotation_drill.v1",
    )
    _require_true_checks(
        payload,
        {
            "initial_two_of_three_quorum_installed",
            "offline_root_distinct_from_package_signers",
            "policy_sequence_advanced",
            "revoked_key_recorded",
            "rotated_quorum_installed",
            "all_compromise_and_rollback_cases_rejected",
        },
    )
    _validate_rejection_matrix(
        payload,
        {
            "one_of_two_signatures",
            "tampered_package_signature",
            "expired_policy",
            "revoked_signer_active_package",
            "policy_hash_rollback",
        },
    )
    transition = payload.get("policy_transition")
    if (
        not isinstance(transition, dict)
        or transition.get("threshold") != 2
        or transition.get("initial_active_keys") != 3
        or transition.get("rotated_active_keys", 0) < 2
        or transition.get("revoked_keys", 0) < 1
        or not isinstance(transition.get("from_sequence"), int)
        or not isinstance(transition.get("to_sequence"), int)
        or transition["to_sequence"] <= transition["from_sequence"]
    ):
        raise ValueError("knowledge trust policy transition is not the required 2-of-3 rotation")
    if payload.get("temporary_keys_policies_packages_and_state_removed") is not True:
        raise ValueError("knowledge trust drill temporary secret state was not removed")
    validate_implementation_binding(
        payload.get("implementation_binding"),
        expected_paths=KNOWLEDGE_TRUST_IMPLEMENTATION_PATHS,
    )


def _validate_knowledge_activation_recovery_drill(
    payload: dict[str, Any],
) -> None:
    _require_schema_and_status(
        payload,
        "open_agronomy_agent.knowledge_update_activation_recovery_drill.v1",
    )
    _require_true_checks(
        payload,
        {
            "before_receipt_worker_exited_abruptly",
            "unreceipted_activation_rolled_back",
            "after_receipt_worker_exited_abruptly",
            "receipted_activation_retained",
            "receipt_digest_required_for_commit",
            "pending_transaction_removed",
            "two_recovery_events_durable",
            "clock_rollback_rejected",
            "final_release_signature_and_corpus_revalidated",
        },
    )
    cases = payload.get("abrupt_exit_cases")
    actions = payload.get("recovery_actions")
    if (
        not isinstance(cases, list)
        or len(cases) != 2
        or [case.get("phase") for case in cases if isinstance(case, dict)]
        != ["before_receipt", "after_receipt"]
        or [case.get("exit_code") for case in cases if isinstance(case, dict)]
        != [91, 93]
        or not isinstance(actions, list)
        or len(actions) != 2
        or [action.get("action") for action in actions if isinstance(action, dict)]
        != ["rollback_unreceipted_activation", "retain_committed"]
        or [action.get("receipt_complete") for action in actions if isinstance(action, dict)]
        != [False, True]
        or payload.get("recovery_event_count") != 2
    ):
        raise ValueError(
            "knowledge activation recovery drill commit-window matrix is incomplete"
        )
    if payload.get("temporary_keys_packages_and_state_removed") is not True:
        raise ValueError(
            "knowledge activation recovery drill temporary state was not removed"
        )
    if "physical power loss" not in str(payload.get("boundary") or ""):
        raise ValueError(
            "knowledge activation recovery drill must preserve its physical-power boundary"
        )
    validate_implementation_binding(
        payload.get("implementation_binding"),
        expected_paths=KNOWLEDGE_ACTIVATION_RECOVERY_IMPLEMENTATION_PATHS,
    )


def _validate_restore_journal_drill(payload: dict[str, Any]) -> None:
    _require_schema_and_status(
        payload,
        "open_agronomy_agent.restore_journal_recovery_drill.v2",
    )
    _require_true_checks(
        payload,
        {
            "every_named_checkpoint_exercised",
            "every_worker_received_sigkill",
            "every_prepared_checkpoint_rolled_back",
            "every_committed_checkpoint_retained_restore",
            "all_recovery_calls_idempotent",
            "no_case_left_transaction_debris",
            "knowledge_update_target_included",
            "prepared_pending_journal_promoted",
            "committed_pending_journal_discarded_under_prepared_authority",
        },
    )
    checkpoint_count = payload.get("checkpoint_count")
    prepared_count = payload.get("prepared_checkpoint_count")
    committed_count = payload.get("committed_checkpoint_count")
    cases = payload.get("cases")
    if (
        checkpoint_count != len(RESTORE_CHECKPOINTS)
        or prepared_count != len(RESTORE_PREPARED_CHECKPOINTS)
        or committed_count != len(RESTORE_COMMITTED_CHECKPOINTS)
        or not isinstance(cases, list)
        or len(cases) != checkpoint_count
        or [case.get("checkpoint") for case in cases if isinstance(case, dict)]
        != list(RESTORE_CHECKPOINTS)
    ):
        raise ValueError("restore journal checkpoint matrix is incomplete")
    for case in cases:
        _validate_restore_journal_case(case)
    topology = payload.get("storage_topology")
    if (
        not isinstance(topology, dict)
        or topology.get("same_host") is not True
        or topology.get("second_machine") is not False
    ):
        raise ValueError("restore journal topology must remain explicitly same-host")
    if payload.get("temporary_private_state_removed") is not True:
        raise ValueError("restore journal temporary state was not removed")
    validate_implementation_binding(
        payload.get("implementation_binding"),
        expected_paths=RESTORE_JOURNAL_IMPLEMENTATION_PATHS,
    )


def _validate_restore_journal_case(case: dict[str, Any]) -> None:
    checkpoint = case["checkpoint"]
    prepared = checkpoint in RESTORE_PREPARED_CHECKPOINTS
    no_journal = checkpoint in {"journal_unlinked", "journal_removed"}
    expected_policy = "rollback_prepared" if prepared else "retain_committed"
    recovery = case.get("recovery")
    before = case.get("before_recovery")
    worker = case.get("worker")
    if (
        case.get("status") != "pass"
        or case.get("expected_policy") != expected_policy
        or case.get("expected_recovery_action") is not True
        or case.get("expected_state_valid") is not True
        or case.get("second_recovery_status") != "no_pending_restore"
        or case.get("transaction_debris") != []
        or not isinstance(worker, dict)
        or worker.get("returncode") != -9
        or worker.get("expected_returncode") != -9
        or not isinstance(recovery, dict)
        or not isinstance(before, dict)
    ):
        raise ValueError(f"restore journal case is incomplete: {checkpoint}")
    expected_status = "no_pending_restore" if no_journal else "recovered"
    expected_action = (
        None
        if no_journal
        else "rolled_back_prepared_restore"
        if prepared
        else "finalized_committed_restore"
    )
    if (
        recovery.get("status") != expected_status
        or recovery.get("action") != expected_action
    ):
        raise ValueError(f"restore journal recovery outcome is invalid: {checkpoint}")
    authoritative = before.get("journal")
    pending = before.get("pending")
    if checkpoint == "prepared_journal_pending_fsynced":
        before_valid = (
            authoritative is None
            and isinstance(pending, dict)
            and pending.get("status") == "prepared"
            and pending.get("mode_private") is True
        )
    elif checkpoint == "committed_journal_pending_fsynced":
        before_valid = (
            isinstance(authoritative, dict)
            and authoritative.get("status") == "prepared"
            and authoritative.get("mode_private") is True
            and isinstance(pending, dict)
            and pending.get("status") == "committed"
            and pending.get("mode_private") is True
        )
    elif no_journal:
        before_valid = authoritative is None and pending is None
    else:
        before_valid = (
            isinstance(authoritative, dict)
            and authoritative.get("status")
            == ("prepared" if prepared else "committed")
            and authoritative.get("mode_private") is True
            and pending is None
        )
    if not before_valid:
        raise ValueError(
            f"restore journal pre-recovery state is invalid: {checkpoint}"
        )


def _validate_runtime_corpus_audit(payload: dict[str, Any]) -> None:
    _require_schema_and_status(
        payload,
        "open_agronomy_agent.runtime_corpus_audit.v1",
    )
    configured = payload.get("configured_corpus_count")
    audited = payload.get("audited_corpus_count")
    corpora = payload.get("corpora")
    if (
        not isinstance(configured, int)
        or not isinstance(audited, int)
        or configured != audited
        or not isinstance(corpora, list)
        or len(corpora) != configured
        or payload.get("errors") != []
    ):
        raise ValueError("runtime corpus audit is incomplete or contains errors")
    if any(
        not isinstance(row, dict)
        or row.get("sha256_verified") is not True
        or row.get("malformed_rows") != 0
        or row.get("missing_doc_id_rows") != 0
        or row.get("missing_source_rows") != 0
        for row in corpora
    ):
        raise ValueError("runtime corpus audit contains an invalid corpus row")
    validate_implementation_binding(
        payload.get("implementation_binding"),
        expected_paths=CORPUS_AUDIT_IMPLEMENTATION_PATHS,
    )


def _validate_rejection_matrix(
    payload: dict[str, Any],
    expected: set[str],
) -> None:
    matrix = payload.get("rejection_matrix")
    if (
        not isinstance(matrix, dict)
        or set(matrix) != expected
        or any(
            not isinstance(row, dict)
            or row.get("passed") is not True
            or not isinstance(row.get("detail"), str)
            or not row["detail"].strip()
            for row in matrix.values()
        )
    ):
        raise ValueError("rejection matrix is incomplete or contains a failed case")


def _private_mode(path: Path, expected: int) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    actual = stat.S_IMODE(path.stat().st_mode)
    return actual & 0o077 == 0 and actual <= expected, oct(actual)


def _sbom_status(path: Path, root: Path = _REPO_ROOT) -> tuple[bool, str]:
    try:
        sbom = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(sbom, dict) or sbom.get("spdxVersion") != "SPDX-2.3":
            raise ValueError("SPDX version is not 2.3")
        packages = sbom.get("packages")
        if not isinstance(packages, list) or len(packages) <= 1:
            raise ValueError("package inventory is empty")
        package_names = {
            str(package.get("name") or "").lower().replace("_", "-")
            for package in packages
            if isinstance(package, dict)
        }
        requirements_path = root / "requirements-container.txt"
        lock_path = root / "frontend" / "package-lock.json"
        required_names = {
            match.group(1).lower().replace("_", "-")
            for raw in requirements_path.read_text(encoding="utf-8").splitlines()
            if (value := raw.strip()) and not value.startswith("#")
            if (match := re.match(r"^([A-Za-z0-9_.-]+)", value))
        }
        missing = sorted(required_names - package_names)
        if missing:
            raise ValueError(f"direct container dependencies are missing: {missing}")
        if "cryptography" not in package_names:
            raise ValueError("cryptography dependency is missing")
        annotations = sbom.get("annotations")
        if not isinstance(annotations, list) or not annotations:
            raise ValueError("source-input hash annotation is missing")
        input_binding: dict[str, Any] | None = None
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            try:
                candidate = json.loads(str(annotation.get("comment") or ""))
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and {
                "requirements_container_sha256",
                "frontend_package_lock_sha256",
            } <= set(candidate):
                input_binding = candidate
                break
        if input_binding is None:
            raise ValueError("source-input hash annotation is missing")
        expected_requirements = _sha256(requirements_path)
        expected_lock = _sha256(lock_path)
        if input_binding["requirements_container_sha256"] != expected_requirements:
            raise ValueError("SBOM is stale for requirements-container.txt")
        if input_binding["frontend_package_lock_sha256"] != expected_lock:
            raise ValueError("SBOM is stale for frontend/package-lock.json")
        return (
            True,
            f"{len(packages)} packages; direct={len(required_names)}; source inputs hash-bound",
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return False, str(exc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _require_exact_keys(payload: dict[str, Any], expected: set[str], field: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(f"{field} keys mismatch; missing={missing}; unexpected={unexpected}")


def _operator_attestation_checks(
    *,
    manifest: Path | None,
    signature: Path | None,
    public_key: Path | None,
    expected_system_id: str | None,
    expected_device_id: str | None,
    evidence_paths: dict[str, Path] | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, tuple[bool, str]], dict[str, Any]]:
    supplied = (manifest, signature, public_key, expected_system_id, expected_device_id)
    if not any(value is not None for value in supplied):
        detail = "signed operator attestation not supplied"
        return (
            {control_id: (False, detail) for control_id in OPERATOR_CONTROL_IDS},
            {"status": "not_supplied"},
        )
    if not all(value is not None for value in supplied):
        detail = (
            "attestation manifest, detached signature, trusted public key, expected system id, "
            "and expected device id must be supplied together"
        )
        return (
            {control_id: (False, detail) for control_id in OPERATOR_CONTROL_IDS},
            {"status": "incomplete"},
        )

    assert manifest is not None
    assert signature is not None
    assert public_key is not None
    assert expected_system_id is not None
    assert expected_device_id is not None
    resolved_manifest = manifest.resolve()
    resolved_signature = signature.resolve()
    resolved_public_key = public_key.resolve()
    try:
        signature_report = verify_manifest_signature(
            manifest=resolved_manifest,
            signature=resolved_signature,
            public_key=resolved_public_key,
        )
    except (OSError, RuntimeError) as exc:
        detail = f"operator attestation signature could not be verified: {exc}"
        return (
            {control_id: (False, detail) for control_id in OPERATOR_CONTROL_IDS},
            {"status": "signature_error", "detail": str(exc)},
        )
    if not signature_report["verified"]:
        detail = "operator attestation detached signature is invalid"
        return (
            {control_id: (False, detail) for control_id in OPERATOR_CONTROL_IDS},
            {"status": "invalid_signature"},
        )

    try:
        payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("attestation root must be an object")
        _require_exact_keys(
            payload,
            {
                "schema_version",
                "status",
                "issued_at",
                "expires_at",
                "subject",
                "attestor",
                "controls",
            },
            "attestation",
        )
        if payload.get("schema_version") != OPERATOR_ATTESTATION_SCHEMA:
            raise ValueError(f"schema_version must be {OPERATOR_ATTESTATION_SCHEMA}")
        if payload.get("status") != "attested":
            raise ValueError("status must be attested")
        issued_at = _utc_timestamp(payload.get("issued_at"), "issued_at")
        expires_at = _utc_timestamp(payload.get("expires_at"), "expires_at")
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if expires_at <= issued_at:
            raise ValueError("expires_at must be after issued_at")
        if expires_at - issued_at > _MAX_ATTESTATION_VALIDITY:
            raise ValueError("attestation validity must not exceed seven days")
        if issued_at > current_time:
            raise ValueError("attestation is not yet valid")
        if expires_at < current_time:
            raise ValueError("attestation has expired")

        subject = payload.get("subject")
        if not isinstance(subject, dict):
            raise ValueError("subject must be an object")
        _require_exact_keys(subject, {"system_id", "device_id"}, "subject")
        if subject.get("system_id") != expected_system_id:
            raise ValueError("subject.system_id does not match the expected system")
        if subject.get("device_id") != expected_device_id:
            raise ValueError("subject.device_id does not match the expected device")
        if not _DEVICE_ID_RE.fullmatch(str(subject.get("device_id") or "")):
            raise ValueError("subject.device_id must be the enrolled pseudonymous hardware digest")

        attestor = payload.get("attestor")
        if not isinstance(attestor, dict):
            raise ValueError("attestor must be an object")
        _require_exact_keys(attestor, {"id", "role"}, "attestor")
        for field in ("id", "role"):
            if not isinstance(attestor.get(field), str) or not attestor[field].strip():
                raise ValueError(f"attestor.{field} must be a non-empty string")

        controls = payload.get("controls")
        if not isinstance(controls, list):
            raise ValueError("controls must be an array")
        controls_by_id: dict[str, dict[str, Any]] = {}
        for control in controls:
            if not isinstance(control, dict) or not isinstance(control.get("id"), str):
                raise ValueError("each control must be an object with a string id")
            _require_exact_keys(
                control,
                {"id", "status", "checked_at", "method", "evidence"},
                "control",
            )
            control_id = control["id"]
            if control_id not in OPERATOR_CONTROL_IDS:
                raise ValueError(f"unsupported control id: {control_id}")
            if control_id in controls_by_id:
                raise ValueError(f"duplicate control id: {control_id}")
            controls_by_id[control_id] = control
        if set(controls_by_id) != set(OPERATOR_CONTROL_IDS):
            raise ValueError("controls must contain exactly the required operator control ids")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        detail = f"signed operator attestation is invalid: {exc}"
        return (
            {control_id: (False, detail) for control_id in OPERATOR_CONTROL_IDS},
            {"status": "invalid_payload", "detail": str(exc)},
        )

    key_sha256 = hashlib.sha256(resolved_public_key.read_bytes()).hexdigest()
    checks: dict[str, tuple[bool, str]] = {}
    verified_evidence: dict[str, dict[str, Any]] = {}
    for control_id in OPERATOR_CONTROL_IDS:
        control = controls_by_id.get(control_id)
        try:
            if control is None:
                raise ValueError("control is missing")
            if control.get("status") != "pass":
                raise ValueError("status must be pass")
            method = control.get("method")
            if not isinstance(method, str) or not method.strip():
                raise ValueError("method must be a non-empty string")
            checked_at = _utc_timestamp(control.get("checked_at"), f"{control_id}.checked_at")
            if checked_at > issued_at:
                raise ValueError("checked_at must not follow attestation issuance")
            if issued_at - checked_at > _MAX_EVIDENCE_TO_ISSUANCE_DELAY:
                raise ValueError("checked_at is too old relative to attestation issuance")
            evidence = control.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("at least one hashed evidence reference is required")
            for index, item in enumerate(evidence):
                if not isinstance(item, dict):
                    raise ValueError(f"evidence[{index}] must be an object")
                _require_exact_keys(item, {"kind", "uri", "sha256"}, f"evidence[{index}]")
                if not isinstance(item.get("kind"), str) or not item["kind"].strip():
                    raise ValueError(f"evidence[{index}].kind must be a non-empty string")
                if not isinstance(item.get("uri"), str) or not item["uri"].strip():
                    raise ValueError(f"evidence[{index}].uri must be a non-empty string")
                digest = item.get("sha256")
                if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                    raise ValueError(f"evidence[{index}].sha256 must be a lowercase SHA-256 digest")
            observation_path = (evidence_paths or {}).get(control_id)
            if observation_path is None:
                raise ValueError("the referenced evidence file was not supplied to the verifier")
            resolved_observation = observation_path.resolve()
            if not resolved_observation.is_file():
                raise ValueError(f"the supplied evidence file does not exist: {resolved_observation}")
            observation_sha256 = _sha256(resolved_observation)
            if observation_sha256 not in {item["sha256"] for item in evidence}:
                raise ValueError("the supplied evidence file SHA-256 is not bound by the signed control")
            observation = _validate_control_observation(
                control_id=control_id,
                path=resolved_observation,
                checked_at=checked_at,
                current_time=current_time,
            )
            if (
                control_id == "off_device_backup_restore"
                and (
                    observation["export_receipt"]["system_id"]
                    != expected_system_id
                    or observation["storage_topology"]["source_device_id"]
                    != expected_device_id
                )
            ):
                raise ValueError(
                    "restore evidence system or source device does not match the signed "
                    "attestation subject"
                )
            verified_evidence[control_id] = {
                "path": str(resolved_observation),
                "sha256": observation_sha256,
                "schema_version": observation["schema_version"],
                "captured_at": observation["captured_at"],
            }
            checks[control_id] = (
                True,
                f"verified signed attestation and supplied evidence; evidence={len(evidence)}; "
                f"evidence_sha256={observation_sha256}; operator_key_sha256={key_sha256}",
            )
        except ValueError as exc:
            checks[control_id] = (False, f"signed control claim is invalid: {exc}")

    return checks, {
        "status": "verified",
        "schema_version": OPERATOR_ATTESTATION_SCHEMA,
        "manifest": str(resolved_manifest),
        "signature": str(resolved_signature),
        "trusted_public_key": str(resolved_public_key),
        "operator_key_sha256": key_sha256,
        "subject": {
            "system_id": expected_system_id,
            "device_id": expected_device_id,
        },
        "issued_at": payload["issued_at"],
        "expires_at": payload["expires_at"],
        "verified_evidence": verified_evidence,
    }


def _validate_control_observation(
    *,
    control_id: str,
    path: Path,
    checked_at: datetime,
    current_time: datetime,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"the supplied evidence file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("the supplied evidence root must be an object")
    if payload.get("status") != "pass":
        raise ValueError("the supplied evidence status must be pass")
    captured_at = _utc_timestamp(payload.get("captured_at"), f"{control_id}.evidence.captured_at")
    if captured_at > current_time:
        raise ValueError("the supplied evidence was captured in the future")
    if abs(captured_at - checked_at) > _OBSERVATION_CLOCK_TOLERANCE:
        raise ValueError("the supplied evidence capture time does not match the signed checked_at")

    if control_id == "volume_encryption":
        validate_volume_encryption_evidence(payload, current_time=current_time)
    elif control_id == "off_device_backup_restore":
        validate_second_machine_restore_receipt(payload)
    else:
        raise ValueError(f"unsupported control id: {control_id}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate local security and recovery evidence without overclaiming external controls.")
    parser.add_argument("--db-path", type=Path, default=Path("outputs/cockpit/phase3.sqlite3"))
    parser.add_argument("--artifact-root", type=Path, default=Path("outputs/cockpit/artifacts"))
    parser.add_argument("--backup-drill", type=Path, required=True)
    parser.add_argument("--encrypted-backup-drill", type=Path, required=True)
    parser.add_argument("--knowledge-trust-drill", type=Path, required=True)
    parser.add_argument(
        "--knowledge-activation-recovery-drill",
        type=Path,
        required=True,
    )
    parser.add_argument("--restore-journal-drill", type=Path, required=True)
    parser.add_argument("--corpus-audit", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--release-checksums", type=Path)
    parser.add_argument("--release-signature", type=Path)
    parser.add_argument("--release-public-key", type=Path)
    parser.add_argument("--operator-attestation", type=Path)
    parser.add_argument("--operator-attestation-signature", type=Path)
    parser.add_argument("--operator-attestation-public-key", type=Path)
    parser.add_argument("--expected-system-id")
    parser.add_argument("--expected-device-id")
    parser.add_argument("--volume-encryption-observation", type=Path)
    parser.add_argument("--separate-storage-restore-observation", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    backup_pass, _, backup_detail = _local_control_status(
        args.backup_drill.resolve(),
        "local_backup_restore_drill",
    )
    encrypted_backup_pass, _, encrypted_backup_detail = _local_control_status(
        args.encrypted_backup_drill.resolve(),
        "encrypted_portable_backup_recovery_drill",
    )
    knowledge_trust_pass, _, knowledge_trust_detail = _local_control_status(
        args.knowledge_trust_drill.resolve(),
        "threshold_knowledge_update_rotation_drill",
    )
    activation_recovery_pass, _, activation_recovery_detail = _local_control_status(
        args.knowledge_activation_recovery_drill.resolve(),
        "knowledge_update_activation_sigkill_recovery",
    )
    journal_recovery_pass, _, journal_recovery_detail = _local_control_status(
        args.restore_journal_drill.resolve(),
        "restore_journal_sigkill_checkpoint_matrix",
    )
    corpus_pass, _, corpus_detail = _local_control_status(
        args.corpus_audit.resolve(),
        "runtime_corpus_governance",
    )
    sbom_pass, sbom_detail = _sbom_status(args.sbom.resolve())
    db_mode_pass, db_mode = _private_mode(args.db_path.resolve(), 0o600)
    artifact_mode_pass, artifact_mode = _private_mode(args.artifact_root.resolve(), 0o700)

    signature_pass = False
    signature_detail = "trusted signed release not supplied"
    signature_paths = (args.release_checksums, args.release_signature, args.release_public_key)
    if all(signature_paths):
        signature_report = verify_manifest_signature(
            manifest=args.release_checksums.resolve(),
            signature=args.release_signature.resolve(),
            public_key=args.release_public_key.resolve(),
        )
        signature_pass = signature_report["verified"]
        signature_detail = signature_report["status"]
    elif any(signature_paths):
        signature_detail = "checksums, signature, and trusted public key must be supplied together"

    operator_checks, operator_attestation = _operator_attestation_checks(
        manifest=args.operator_attestation,
        signature=args.operator_attestation_signature,
        public_key=args.operator_attestation_public_key,
        expected_system_id=args.expected_system_id,
        expected_device_id=args.expected_device_id,
        evidence_paths={
            control_id: path
            for control_id, path in {
                "volume_encryption": args.volume_encryption_observation,
                "off_device_backup_restore": args.separate_storage_restore_observation,
            }.items()
            if path is not None
        },
    )
    volume_encryption_pass, volume_encryption_detail = operator_checks["volume_encryption"]
    off_device_backup_pass, off_device_backup_detail = operator_checks["off_device_backup_restore"]
    observations: dict[str, Any] = {}
    if args.volume_encryption_observation:
        observation_path = args.volume_encryption_observation.resolve()
        observation_pass, observation_payload, observation_detail = _json_status(
            observation_path,
            "open_agronomy_agent.device_encryption_evidence.v1",
        )
        observations["volume_encryption"] = {
            "status": "observed" if observation_pass else "invalid",
            "path": str(observation_path),
            "sha256": _sha256(observation_path) if observation_path.is_file() else None,
            "detail": observation_detail,
            "checks": (observation_payload or {}).get("checks"),
            "release_gate_effect": "none_without_valid_signed_operator_attestation",
        }
        if observation_pass and not volume_encryption_pass:
            volume_encryption_detail += (
                f"; unsigned observation available with sha256={observations['volume_encryption']['sha256']}, "
                "but it does not clear the signed attestation gate"
            )
    if args.separate_storage_restore_observation:
        observation_path = args.separate_storage_restore_observation.resolve()
        observation_pass, observation_payload, observation_detail = _json_status(
            observation_path,
            "open_agronomy_agent.backup_restore_drill.v2",
        )
        topology = (observation_payload or {}).get("storage_topology") or {}
        same_host_rehearsal = bool(
            observation_pass
            and topology.get("same_host") is True
            and topology.get("second_machine") is False
        )
        second_machine_semantic_pass = False
        if observation_pass and observation_payload is not None:
            try:
                validate_second_machine_restore_receipt(observation_payload)
                second_machine_semantic_pass = True
            except ValueError:
                second_machine_semantic_pass = False
        evidence_kind = (
            "verified_second_machine"
            if second_machine_semantic_pass
            else "same_host_rehearsal"
            if same_host_rehearsal
            else "invalid"
        )
        observations["separate_storage_restore"] = {
            "status": "observed" if evidence_kind != "invalid" else "invalid",
            "evidence_kind": evidence_kind,
            "path": str(observation_path),
            "sha256": _sha256(observation_path) if observation_path.is_file() else None,
            "detail": observation_detail,
            "storage_topology": topology,
            "release_gate_effect": (
                "eligible_only_with_valid_signed_operator_attestation"
                if second_machine_semantic_pass
                else "none_without_second_machine_and_valid_signed_operator_attestation"
            ),
        }
        if same_host_rehearsal and not off_device_backup_pass:
            off_device_backup_detail += (
                f"; same-host separate-storage restore passed with "
                f"sha256={observations['separate_storage_restore']['sha256']}, but it does not prove "
                "second-machine recovery or clear the signed attestation gate"
            )
        elif second_machine_semantic_pass and not off_device_backup_pass:
            off_device_backup_detail += (
                f"; a semantically valid second-machine receipt is available with "
                f"sha256={observations['separate_storage_restore']['sha256']}, but it does not clear "
                "the gate without a valid signed operator attestation bound to that exact receipt"
            )

    checks = [
        {"id": "local_backup_restore_drill", "passed": backup_pass, "detail": backup_detail},
        {
            "id": "encrypted_portable_backup_recovery_drill",
            "passed": encrypted_backup_pass,
            "detail": encrypted_backup_detail,
        },
        {
            "id": "threshold_knowledge_update_rotation_drill",
            "passed": knowledge_trust_pass,
            "detail": knowledge_trust_detail,
        },
        {
            "id": "knowledge_update_activation_sigkill_recovery",
            "passed": activation_recovery_pass,
            "detail": activation_recovery_detail,
        },
        {
            "id": "restore_journal_sigkill_checkpoint_matrix",
            "passed": journal_recovery_pass,
            "detail": journal_recovery_detail,
        },
        {"id": "runtime_corpus_governance", "passed": corpus_pass, "detail": corpus_detail},
        {"id": "dependency_inventory_sbom", "passed": sbom_pass, "detail": sbom_detail},
        {"id": "private_sqlite_permissions", "passed": db_mode_pass, "detail": db_mode},
        {"id": "private_artifact_permissions", "passed": artifact_mode_pass, "detail": artifact_mode},
        {"id": "trusted_release_signature", "passed": signature_pass, "detail": signature_detail},
        {
            "id": "volume_encryption_operator_attestation",
            "passed": volume_encryption_pass,
            "detail": volume_encryption_detail,
        },
        {
            "id": "off_device_backup_operator_attestation",
            "passed": off_device_backup_pass,
            "detail": off_device_backup_detail,
        },
    ]
    local_control_ids = {
        "local_backup_restore_drill",
        "encrypted_portable_backup_recovery_drill",
        "threshold_knowledge_update_rotation_drill",
        "knowledge_update_activation_sigkill_recovery",
        "restore_journal_sigkill_checkpoint_matrix",
        "runtime_corpus_governance",
        "dependency_inventory_sbom",
        "private_sqlite_permissions",
        "private_artifact_permissions",
    }
    local_controls_pass = all(check["passed"] for check in checks if check["id"] in local_control_ids)
    production_ready = all(check["passed"] for check in checks)
    report = {
        "schema_version": "open_agronomy_agent.security_recovery_readiness.v2",
        "status": "ready" if production_ready else "blocked",
        "local_controls_pass": local_controls_pass,
        "production_ready": production_ready,
        "checks": checks,
        "operator_attestation": operator_attestation,
        "observations": observations,
        "boundary": (
            "Local checks include a journaled restore interrupted by real SIGKILL and an application-layer "
            "encrypted portable-backup restore with wrong-key and tamper rejection, plus a root-pinned "
            "threshold knowledge-update rotation and revocation drill, and signed-knowledge activation "
            "reconciliation across both real-SIGKILL commit windows. Volume encryption and "
            "off-device recovery still require a detached-signed, "
            "time-bounded operator attestation bound to the expected system and device with hashed evidence "
            "references. The trusted release key remains an operator-owned trust anchor. None of these controls "
            "is inferred from a passing application test or an unaudited command-line boolean. The SIGKILL drill "
            "does not stand in for physical-power-loss or second-machine recovery."
        ),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if local_controls_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
