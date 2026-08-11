from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from agronomy_agent.artifact_signature import verify_manifest_signature
from agronomy_agent.field_events import verify_field_event_chain
from agronomy_agent.knowledge_updates import knowledge_update_status
from agronomy_agent.knowledge_update_trust import VerifiedKnowledgeUpdateTrustPolicy
from agronomy_agent.server.storage.backup import (
    ARTIFACTS_DIR_NAME,
    DB_SNAPSHOT_NAME,
    KNOWLEDGE_UPDATES_DIR_NAME,
    MANIFEST_DIGEST_NAME,
    MANIFEST_NAME,
    restore_backup,
    restore_journal_path,
    validate_backup,
)


BACKUP_EXPORT_RECEIPT_SCHEMA = "open_agronomy_agent.backup_export_receipt.v1"
SECOND_MACHINE_RESTORE_SCHEMA = "open_agronomy_agent.backup_restore_drill.v2"
DEVICE_ID_PREFIX = "sha256:"
DEFAULT_EXPORT_VALIDITY = timedelta(days=30)
MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SYSTEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EXPORT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MAC_UUID_RE = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    method: str


CommandRunner = Callable[[list[str]], str]
TextReader = Callable[[Path], str]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pseudonymous_device_id(raw_identity: str) -> str:
    normalized = raw_identity.strip().lower()
    if not normalized:
        raise ValueError("device identity source is empty")
    digest = hashlib.sha256(
        b"open-agronomy-agent-device-v1\x00" + normalized.encode("utf-8")
    ).hexdigest()
    return f"{DEVICE_ID_PREFIX}{digest}"


def capture_device_identity(
    *,
    platform_name: str | None = None,
    command_runner: CommandRunner | None = None,
    text_reader: TextReader | None = None,
) -> DeviceIdentity:
    """Capture a pseudonymous hardware identity without returning the raw identifier."""

    system = platform_name or platform.system()
    run = command_runner or _run_command
    read = text_reader or (lambda path: path.read_text(encoding="utf-8"))
    if system == "Darwin":
        output = run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
        match = _MAC_UUID_RE.search(output)
        if match is None:
            raise RuntimeError("IOPlatformUUID was not available from IORegistry")
        return DeviceIdentity(
            device_id=pseudonymous_device_id(match.group(1)),
            method="macos_ioplatformuuid_sha256_v1",
        )
    if system == "Linux":
        raw = read(Path("/etc/machine-id"))
        return DeviceIdentity(
            device_id=pseudonymous_device_id(raw),
            method="linux_machine_id_sha256_v1",
        )
    raise RuntimeError(f"unsupported platform for hardware identity capture: {system}")


def build_backup_export_receipt(
    *,
    backup_dir: Path,
    system_id: str,
    source_identity: DeviceIdentity | None = None,
    captured_at: datetime | None = None,
    validity: timedelta = DEFAULT_EXPORT_VALIDITY,
    export_id: str | None = None,
) -> dict[str, Any]:
    """Build the canonical receipt that a release custodian signs offline."""

    _validate_system_id(system_id)
    if validity <= timedelta(0) or validity > DEFAULT_EXPORT_VALIDITY:
        raise ValueError(
            "export receipt validity must be positive and no longer than 30 days"
        )
    identity = source_identity or capture_device_identity()
    _validate_device_identity(identity)
    backup_dir = backup_dir.resolve()
    manifest = validate_backup(backup_dir)
    _validate_exact_backup_file_set(backup_dir, manifest)
    captured = _coerce_time(captured_at)
    backup_created = datetime.fromtimestamp(int(manifest["created_at_unix"]), tz=timezone.utc)
    if captured + MAX_FUTURE_CLOCK_SKEW < backup_created:
        raise ValueError("export receipt cannot predate the backup")
    receipt_id = export_id or uuid.uuid4().hex
    if not _EXPORT_ID_RE.fullmatch(receipt_id):
        raise ValueError("export_id must be 32 lowercase hexadecimal characters")
    return {
        "schema_version": BACKUP_EXPORT_RECEIPT_SCHEMA,
        "status": "ready_for_recovery",
        "export_id": receipt_id,
        "captured_at": _format_time(captured),
        "expires_at": _format_time(captured + validity),
        "subject": {
            "system_id": system_id,
            "source_device_id": identity.device_id,
            "source_device_identity_method": identity.method,
        },
        "backup": _backup_binding(backup_dir, manifest),
        "boundary": (
            "This receipt binds a source device and one validated backup manifest. Its detached "
            "Ed25519 signature authenticates the export claim; a recovery machine must independently "
            "capture a different hardware identity and complete semantic restore verification."
        ),
    }


def write_private_json(path: Path, payload: dict[str, Any]) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def verify_backup_export_receipt(
    *,
    backup_dir: Path,
    receipt_path: Path,
    signature_path: Path,
    public_key_path: Path,
    expected_system_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_system_id(expected_system_id)
    receipt_path = receipt_path.resolve()
    signature_path = signature_path.resolve()
    public_key_path = public_key_path.resolve()
    signature = verify_manifest_signature(
        manifest=receipt_path,
        signature=signature_path,
        public_key=public_key_path,
    )
    if not signature["verified"]:
        raise ValueError("backup export receipt detached signature is invalid")
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"backup export receipt is not valid JSON: {exc}") from exc
    validate_backup_export_receipt_payload(
        payload,
        expected_system_id=expected_system_id,
        now=now,
    )
    backup_dir = backup_dir.resolve()
    manifest = validate_backup(backup_dir)
    _validate_exact_backup_file_set(backup_dir, manifest)
    actual_binding = _backup_binding(backup_dir, manifest)
    if payload["backup"] != actual_binding:
        raise ValueError("backup does not match the signed export receipt")
    return {
        "payload": payload,
        "receipt_sha256": sha256_path(receipt_path),
        "signature_sha256": sha256_path(signature_path),
        "trusted_public_key_sha256": sha256_path(public_key_path),
        "backup_manifest_sha256": actual_binding["backup_manifest_sha256"],
        "signature_verified": True,
        "backup_validated": True,
        "backup_manifest_bound": True,
    }


def run_second_machine_restore_verification(
    *,
    backup_dir: Path,
    receipt_path: Path,
    signature_path: Path,
    public_key_path: Path,
    expected_system_id: str,
    knowledge_update_public_key: Path | None = None,
    knowledge_update_trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    destination_identity: DeviceIdentity | None = None,
    work_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify and restore a signed export, emitting pass only for distinct devices."""

    captured_at = _coerce_time(now)
    destination = destination_identity or capture_device_identity()
    _validate_device_identity(destination)
    source_identity: DeviceIdentity | None = None
    export_verification: dict[str, Any] | None = None
    backup_binding: dict[str, Any] | None = None
    field_event_chains: dict[str, Any] = {
        "status": "not_run",
        "valid": False,
        "field_count": 0,
        "event_count": 0,
        "fields": [],
    }
    knowledge_validation: dict[str, Any] = {"status": "not_run"}
    checks: dict[str, Any] = {
        "manifest_validated": False,
        "export_receipt_signature_verified": False,
        "backup_manifest_bound_to_signed_export": False,
        "source_and_restore_devices_distinct": False,
        "database_quick_check": "not_run",
        "database_snapshot_sha256_match": False,
        "artifact_count_match": False,
        "knowledge_update_count_match": False,
        "field_event_chains_valid": False,
        "restored_knowledge_runtime_valid": "not_run",
        "restored_release_files_read_only": "not_run",
        "restore_journal_cleared": False,
    }
    error: str | None = None
    passed = False
    temporary_restore_removed = True
    temporary_path: Path | None = None
    try:
        export_verification = verify_backup_export_receipt(
            backup_dir=backup_dir,
            receipt_path=receipt_path,
            signature_path=signature_path,
            public_key_path=public_key_path,
            expected_system_id=expected_system_id,
            now=captured_at,
        )
        payload = export_verification["payload"]
        backup_binding = payload["backup"]
        source_identity = DeviceIdentity(
            device_id=payload["subject"]["source_device_id"],
            method=payload["subject"]["source_device_identity_method"],
        )
        checks["manifest_validated"] = True
        checks["export_receipt_signature_verified"] = True
        checks["backup_manifest_bound_to_signed_export"] = True
        distinct = source_identity.device_id != destination.device_id
        checks["source_and_restore_devices_distinct"] = distinct
        if not distinct:
            raise ValueError(
                "source and restore hardware identities are identical; same-host recovery "
                "cannot produce second-machine evidence"
            )
        knowledge_count = int(backup_binding["knowledge_update_file_count"])
        if (
            knowledge_count
            and knowledge_update_public_key is None
            and knowledge_update_trust_policy is None
        ):
            raise ValueError(
                "a pinned knowledge-update public key or verified threshold trust policy "
                "is required when the backup contains knowledge-update state"
            )

        work_parent = work_root.resolve() if work_root else None
        if work_parent is not None:
            work_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="agronomy-second-machine-restore-",
            dir=work_parent,
        ) as temporary:
            work = Path(temporary)
            temporary_path = work
            restored_db = work / "restore" / DB_SNAPSHOT_NAME
            restored_artifacts = work / "restore" / ARTIFACTS_DIR_NAME
            restored_knowledge = work / "restore" / KNOWLEDGE_UPDATES_DIR_NAME
            restore_backup(
                backup_dir=backup_dir,
                target_db_path=restored_db,
                target_artifact_root=restored_artifacts,
                target_knowledge_update_root=restored_knowledge if knowledge_count else None,
            )
            quick_check = _sqlite_quick_check(restored_db)
            field_event_chains = _field_event_chain_report(restored_db)
            artifact_count = sum(
                1 for path in restored_artifacts.rglob("*") if path.is_file()
            )
            restored_knowledge_count = (
                sum(1 for path in restored_knowledge.rglob("*") if path.is_file())
                if knowledge_count
                else 0
            )
            knowledge_valid = True
            permissions_valid = True
            if knowledge_count:
                permissions_valid = _release_files_are_read_only(restored_knowledge)
                knowledge_validation = knowledge_update_status(
                    update_root=restored_knowledge,
                    public_key=(
                        knowledge_update_public_key.resolve()
                        if knowledge_update_public_key is not None
                        else None
                    ),
                    trust_policy=knowledge_update_trust_policy,
                    allow_unsigned=False,
                )
                knowledge_valid = knowledge_validation.get("status") == "active"
            else:
                knowledge_validation = {"status": "not_applicable"}
            checks.update(
                {
                    "database_quick_check": quick_check,
                    "database_snapshot_sha256_match": (
                        sha256_path(backup_dir.resolve() / DB_SNAPSHOT_NAME)
                        == sha256_path(restored_db)
                    ),
                    "artifact_count_match": (
                        artifact_count == int(backup_binding["artifact_count"])
                    ),
                    "knowledge_update_count_match": (
                        restored_knowledge_count == knowledge_count
                    ),
                    "field_event_chains_valid": field_event_chains["valid"],
                    "restored_knowledge_runtime_valid": (
                        knowledge_valid if knowledge_count else "not_applicable"
                    ),
                    "restored_release_files_read_only": (
                        permissions_valid if knowledge_count else "not_applicable"
                    ),
                    "restore_journal_cleared": not restore_journal_path(restored_db).exists(),
                }
            )
            passed = (
                quick_check == "ok"
                and all(
                    checks[name] is True
                    for name in (
                        "manifest_validated",
                        "export_receipt_signature_verified",
                        "backup_manifest_bound_to_signed_export",
                        "source_and_restore_devices_distinct",
                        "database_snapshot_sha256_match",
                        "artifact_count_match",
                        "knowledge_update_count_match",
                        "field_event_chains_valid",
                        "restore_journal_cleared",
                    )
                )
                and knowledge_valid
                and permissions_valid
            )
            if not passed:
                raise ValueError("one or more semantic restore checks failed")
        temporary_restore_removed = not temporary_path.exists()
        if not temporary_restore_removed:
            raise OSError("temporary restore cleanup failed")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        error = str(exc)
        passed = False
        if temporary_path is not None:
            temporary_restore_removed = not temporary_path.exists()
            if not temporary_restore_removed:
                try:
                    shutil.rmtree(temporary_path)
                except OSError:
                    pass
                temporary_restore_removed = not temporary_path.exists()
        if not temporary_restore_removed:
            error = f"{error}; temporary restore cleanup failed"

    distinct = bool(
        source_identity is not None
        and source_identity.device_id != destination.device_id
    )
    topology = {
        "source_device_id": source_identity.device_id if source_identity else None,
        "restore_device_id": destination.device_id,
        "source_device_identity_method": source_identity.method if source_identity else None,
        "restore_device_identity_method": destination.method,
        "source_and_restore_devices_distinct": distinct,
        "same_host": False if distinct else (True if source_identity else None),
        "second_machine": bool(passed and distinct),
    }
    export_report = (
        {
            "schema_version": BACKUP_EXPORT_RECEIPT_SCHEMA,
            "export_id": export_verification["payload"]["export_id"],
            "system_id": export_verification["payload"]["subject"]["system_id"],
            "receipt_sha256": export_verification["receipt_sha256"],
            "signature_sha256": export_verification["signature_sha256"],
            "trusted_public_key_sha256": export_verification[
                "trusted_public_key_sha256"
            ],
            "signature_verified": export_verification["signature_verified"],
            "backup_validated": export_verification["backup_validated"],
            "backup_manifest_bound": export_verification["backup_manifest_bound"],
        }
        if export_verification is not None
        else {
            "schema_version": BACKUP_EXPORT_RECEIPT_SCHEMA,
            "signature_verified": False,
            "backup_validated": False,
            "backup_manifest_bound": False,
        }
    )
    return {
        "schema_version": SECOND_MACHINE_RESTORE_SCHEMA,
        "status": "pass" if passed else "fail",
        "captured_at": _format_time(captured_at),
        "export_receipt": export_report,
        "backup": backup_binding,
        "storage_topology": topology,
        "field_event_chains": field_event_chains,
        "restored_knowledge_validation": knowledge_validation,
        "checks": checks,
        "temporary_restore_removed": temporary_restore_removed,
        "error": error,
        "boundary": (
            "A pass proves that a receipt signed by the pinned export key bound the exact backup "
            "manifest, the source and restore hardware identities differed, and the restored local "
            "state passed the recorded semantic checks. It does not prove physical power-loss, "
            "controller, filesystem-corruption, or managed-service recovery."
        ),
    }


def validate_second_machine_restore_receipt(payload: Any) -> None:
    """Strict semantic validation used by the production-readiness gate."""

    if not isinstance(payload, dict):
        raise ValueError("restore evidence root must be an object")
    if payload.get("schema_version") != SECOND_MACHINE_RESTORE_SCHEMA:
        raise ValueError("restore evidence has an unsupported schema")
    if payload.get("status") != "pass":
        raise ValueError("restore evidence status must be pass")
    topology = payload.get("storage_topology")
    if not isinstance(topology, dict):
        raise ValueError("restore evidence has no storage topology")
    if topology.get("same_host") is not False or topology.get("second_machine") is not True:
        raise ValueError("restore evidence does not prove a distinct second-machine recovery")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "captured_at",
            "export_receipt",
            "backup",
            "storage_topology",
            "field_event_chains",
            "restored_knowledge_validation",
            "checks",
            "temporary_restore_removed",
            "error",
            "boundary",
        },
        "restore evidence",
    )
    required_topology = {
        "source_device_id",
        "restore_device_id",
        "source_device_identity_method",
        "restore_device_identity_method",
        "source_and_restore_devices_distinct",
        "same_host",
        "second_machine",
    }
    if set(topology) != required_topology:
        raise ValueError("restore evidence topology keys do not match the supported schema")
    source_device = _validated_device_id(topology.get("source_device_id"))
    restore_device = _validated_device_id(topology.get("restore_device_id"))
    if source_device == restore_device:
        raise ValueError("restore evidence source and restore device identities are identical")
    if topology.get("source_and_restore_devices_distinct") is not True:
        raise ValueError("restore evidence does not prove a distinct second-machine recovery")
    for field in ("source_device_identity_method", "restore_device_identity_method"):
        if not isinstance(topology.get(field), str) or not topology[field].strip():
            raise ValueError(f"restore evidence {field} must be non-empty")

    export = payload.get("export_receipt")
    if not isinstance(export, dict):
        raise ValueError("restore evidence has no signed export verification")
    _require_exact_keys(
        export,
        {
            "schema_version",
            "export_id",
            "system_id",
            "receipt_sha256",
            "signature_sha256",
            "trusted_public_key_sha256",
            "signature_verified",
            "backup_validated",
            "backup_manifest_bound",
        },
        "restore evidence export receipt",
    )
    for field in (
        "receipt_sha256",
        "signature_sha256",
        "trusted_public_key_sha256",
    ):
        _validated_sha256(export.get(field), f"export_receipt.{field}")
    if export.get("schema_version") != BACKUP_EXPORT_RECEIPT_SCHEMA:
        raise ValueError("restore evidence export receipt schema is unsupported")
    if not _EXPORT_ID_RE.fullmatch(str(export.get("export_id") or "")):
        raise ValueError("restore evidence export_id is invalid")
    _validate_system_id(export.get("system_id"))
    for field in ("signature_verified", "backup_validated", "backup_manifest_bound"):
        if export.get(field) is not True:
            raise ValueError(f"restore evidence {field} must be true")

    backup = payload.get("backup")
    _validate_backup_binding(backup)
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("restore evidence checks must be an object")
    expected_check_keys = {
        "manifest_validated",
        "export_receipt_signature_verified",
        "backup_manifest_bound_to_signed_export",
        "source_and_restore_devices_distinct",
        "database_quick_check",
        "database_snapshot_sha256_match",
        "artifact_count_match",
        "knowledge_update_count_match",
        "field_event_chains_valid",
        "restored_knowledge_runtime_valid",
        "restored_release_files_read_only",
        "restore_journal_cleared",
    }
    _require_exact_keys(checks, expected_check_keys, "restore evidence checks")
    required_true = {
        "manifest_validated",
        "export_receipt_signature_verified",
        "backup_manifest_bound_to_signed_export",
        "source_and_restore_devices_distinct",
        "database_snapshot_sha256_match",
        "artifact_count_match",
        "knowledge_update_count_match",
        "field_event_chains_valid",
        "restore_journal_cleared",
    }
    if any(checks.get(field) is not True for field in required_true):
        raise ValueError("restore evidence does not pass every required semantic check")
    if checks.get("database_quick_check") != "ok":
        raise ValueError("restore evidence database quick_check did not pass")
    knowledge_count = int(backup["knowledge_update_file_count"])
    for field in (
        "restored_knowledge_runtime_valid",
        "restored_release_files_read_only",
    ):
        expected = True if knowledge_count else "not_applicable"
        if checks.get(field) != expected:
            raise ValueError(f"restore evidence {field} does not match backup content")
    chains = payload.get("field_event_chains")
    if not isinstance(chains, dict) or chains.get("valid") is not True:
        raise ValueError("restore evidence field-event chains are not valid")
    if not isinstance(payload.get("restored_knowledge_validation"), dict):
        raise ValueError("restore evidence knowledge validation must be an object")
    if payload.get("temporary_restore_removed") is not True:
        raise ValueError("restore evidence temporary restore was not removed")
    if payload.get("error") is not None:
        raise ValueError("passing restore evidence must not contain an error")
    if not isinstance(payload.get("boundary"), str) or not payload["boundary"].strip():
        raise ValueError("restore evidence boundary must be non-empty")


def _run_command(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"device identity command failed ({result.returncode}): "
            f"{result.stderr.strip() or 'no diagnostic'}"
        )
    return result.stdout


def validate_backup_export_receipt_payload(
    payload: Any,
    *,
    expected_system_id: str,
    now: datetime | None,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("backup export receipt root must be an object")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "export_id",
            "captured_at",
            "expires_at",
            "subject",
            "backup",
            "boundary",
        },
        "backup export receipt",
    )
    if payload.get("schema_version") != BACKUP_EXPORT_RECEIPT_SCHEMA:
        raise ValueError("unsupported backup export receipt schema")
    if payload.get("status") != "ready_for_recovery":
        raise ValueError("backup export receipt status must be ready_for_recovery")
    if not _EXPORT_ID_RE.fullmatch(str(payload.get("export_id") or "")):
        raise ValueError("backup export receipt export_id is invalid")
    captured_at = _parse_time(payload.get("captured_at"), "captured_at")
    expires_at = _parse_time(payload.get("expires_at"), "expires_at")
    current = _coerce_time(now)
    if captured_at > current + MAX_FUTURE_CLOCK_SKEW:
        raise ValueError("backup export receipt was captured in the future")
    if expires_at <= captured_at:
        raise ValueError("backup export receipt expires_at must follow captured_at")
    if expires_at - captured_at > DEFAULT_EXPORT_VALIDITY:
        raise ValueError("backup export receipt validity exceeds 30 days")
    if current >= expires_at:
        raise ValueError("backup export receipt has expired")
    subject = payload.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("backup export receipt subject must be an object")
    _require_exact_keys(
        subject,
        {
            "system_id",
            "source_device_id",
            "source_device_identity_method",
        },
        "backup export receipt subject",
    )
    if subject.get("system_id") != expected_system_id:
        raise ValueError("backup export receipt system_id does not match the expected system")
    _validated_device_id(subject.get("source_device_id"))
    method = subject.get("source_device_identity_method")
    if not isinstance(method, str) or not method.strip():
        raise ValueError("source_device_identity_method must be non-empty")
    _validate_backup_binding(payload.get("backup"))
    backup_created_at = datetime.fromtimestamp(
        int(payload["backup"]["backup_created_at_unix"]),
        tz=timezone.utc,
    )
    if captured_at + MAX_FUTURE_CLOCK_SKEW < backup_created_at:
        raise ValueError("backup export receipt predates the bound backup")
    if not isinstance(payload.get("boundary"), str) or not payload["boundary"].strip():
        raise ValueError("backup export receipt boundary must be non-empty")


def _backup_binding(backup_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "backup_id": str(manifest["backup_id"]),
        "backup_format": str(manifest["format"]),
        "backup_created_at_unix": int(manifest["created_at_unix"]),
        "backup_manifest_sha256": sha256_path(backup_dir / MANIFEST_NAME),
        "database_sha256": str(manifest["database"]["sha256"]),
        "artifact_count": len(manifest.get("artifacts", [])),
        "knowledge_update_file_count": len(manifest.get("knowledge_updates", [])),
    }


def _validate_backup_binding(binding: Any) -> None:
    if not isinstance(binding, dict):
        raise ValueError("backup binding must be an object")
    _require_exact_keys(
        binding,
        {
            "backup_id",
            "backup_format",
            "backup_created_at_unix",
            "backup_manifest_sha256",
            "database_sha256",
            "artifact_count",
            "knowledge_update_file_count",
        },
        "backup binding",
    )
    if not isinstance(binding.get("backup_id"), str) or not binding["backup_id"]:
        raise ValueError("backup_id must be non-empty")
    if binding.get("backup_format") not in {
        "agronomy-agent-phase4-backup-v2",
        "agronomy-agent-phase4-backup-v3",
    }:
        raise ValueError("backup_format is unsupported")
    if (
        not isinstance(binding.get("backup_created_at_unix"), int)
        or isinstance(binding["backup_created_at_unix"], bool)
        or binding["backup_created_at_unix"] < 0
    ):
        raise ValueError("backup_created_at_unix must be a non-negative integer")
    _validated_sha256(
        binding.get("backup_manifest_sha256"),
        "backup_manifest_sha256",
    )
    _validated_sha256(binding.get("database_sha256"), "database_sha256")
    for field in ("artifact_count", "knowledge_update_file_count"):
        value = binding.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")


def _validate_exact_backup_file_set(
    backup_dir: Path,
    manifest: dict[str, Any],
) -> None:
    for path in [backup_dir, *backup_dir.rglob("*")]:
        if path.is_symlink():
            raise ValueError(f"backup contains a symlink: {path.relative_to(backup_dir)}")
    expected = {
        MANIFEST_NAME,
        MANIFEST_DIGEST_NAME,
        DB_SNAPSHOT_NAME,
        *(
            f"{ARTIFACTS_DIR_NAME}/{entry['path']}"
            for entry in manifest.get("artifacts", [])
        ),
        *(
            f"{KNOWLEDGE_UPDATES_DIR_NAME}/{entry['path']}"
            for entry in manifest.get("knowledge_updates", [])
        ),
    }
    actual = {
        path.relative_to(backup_dir).as_posix()
        for path in backup_dir.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise ValueError(
            "backup file set is not exactly manifest-bound; "
            f"unexpected={sorted(actual - expected)}; missing={sorted(expected - actual)}"
        )


def _sqlite_quick_check(path: Path) -> str:
    connection = sqlite3.connect(str(path))
    try:
        return str(connection.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        connection.close()


def _field_event_chain_report(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'phase4_field_events'"
        ).fetchone()
        if not exists:
            return {
                "status": "not_present",
                "valid": True,
                "field_count": 0,
                "event_count": 0,
                "fields": [],
            }
        field_ids = [
            str(row["field_context_id"])
            for row in connection.execute(
                "SELECT DISTINCT field_context_id FROM phase4_field_events ORDER BY field_context_id"
            ).fetchall()
        ]
        fields: list[dict[str, Any]] = []
        for field_id in field_ids:
            rows = connection.execute(
                """
                SELECT *
                FROM phase4_field_events
                WHERE field_context_id = ?
                ORDER BY recorded_at, id
                """,
                (field_id,),
            ).fetchall()
            events: list[dict[str, Any]] = []
            for row in rows:
                event = dict(row)
                event["payload"] = json.loads(str(event.get("payload") or "{}"))
                event["provenance"] = json.loads(str(event.get("provenance") or "{}"))
                events.append(event)
            chain = verify_field_event_chain(events)
            fields.append(
                {
                    "field_context_id": field_id,
                    "valid": chain["valid"],
                    "event_count": chain["event_count"],
                    "head_sha256": chain["head_sha256"],
                    "failures": chain["failures"],
                }
            )
        return {
            "status": "verified",
            "valid": all(bool(field["valid"]) for field in fields),
            "field_count": len(fields),
            "event_count": sum(int(field["event_count"]) for field in fields),
            "fields": fields,
        }
    finally:
        connection.close()


def _release_files_are_read_only(root: Path) -> bool:
    releases = root / "releases"
    return releases.is_dir() and all(
        not (path.stat().st_mode & 0o222)
        for release in releases.iterdir()
        if release.is_dir()
        for path in [release, *release.rglob("*")]
    )


def _validate_device_identity(identity: DeviceIdentity) -> None:
    _validated_device_id(identity.device_id)
    if not isinstance(identity.method, str) or not identity.method.strip():
        raise ValueError("device identity method must be non-empty")


def _validated_device_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(DEVICE_ID_PREFIX)
        or not _SHA256_RE.fullmatch(value[len(DEVICE_ID_PREFIX) :])
    ):
        raise ValueError("device_id must be a sha256-prefixed lowercase digest")
    return value


def _validated_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_system_id(system_id: str) -> None:
    if not isinstance(system_id, str) or not _SYSTEM_ID_RE.fullmatch(system_id):
        raise ValueError(
            "system_id must be 1-128 characters using letters, digits, dot, underscore, or hyphen"
        )


def _require_exact_keys(payload: dict[str, Any], expected: set[str], field: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{field} keys mismatch; missing={sorted(expected - actual)}; "
            f"unexpected={sorted(actual - expected)}"
        )


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _coerce_time(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("time must include a timezone")
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
