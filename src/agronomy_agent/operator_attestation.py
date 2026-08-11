from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agronomy_agent.artifact_signature import verify_manifest_signature
from agronomy_agent.recovery_evidence import (
    BACKUP_EXPORT_RECEIPT_SCHEMA,
    SECOND_MACHINE_RESTORE_SCHEMA,
    sha256_path,
    validate_backup_export_receipt_payload,
    validate_second_machine_restore_receipt,
)


OPERATOR_ATTESTATION_SCHEMA = "open_agronomy_agent.operator_security_attestation.v1"
DEVICE_ENCRYPTION_EVIDENCE_SCHEMA = "open_agronomy_agent.device_encryption_evidence.v1"
DEFAULT_ATTESTATION_VALIDITY = timedelta(days=7)
MAX_ATTESTATION_VALIDITY = timedelta(days=7)
MAX_EVIDENCE_AGE_AT_ISSUANCE = timedelta(hours=24)
MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEVICE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SYSTEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def build_operator_security_attestation(
    *,
    volume_evidence_path: Path,
    restore_evidence_path: Path,
    export_receipt_path: Path,
    export_signature_path: Path,
    export_public_key_path: Path,
    expected_export_public_key_sha256: str,
    expected_system_id: str,
    expected_source_device_id: str,
    attestor_id: str,
    attestor_role: str,
    volume_evidence_uri: str,
    restore_evidence_uri: str,
    issued_at: datetime | None = None,
    validity: timedelta = DEFAULT_ATTESTATION_VALIDITY,
) -> dict[str, Any]:
    """Build an unsigned attestation from verified evidence; never sign it here."""

    _validate_system_id(expected_system_id)
    _validate_device_id(expected_source_device_id)
    _validate_sha256(
        expected_export_public_key_sha256,
        "expected_export_public_key_sha256",
    )
    for field, value in (
        ("attestor_id", attestor_id),
        ("attestor_role", attestor_role),
        ("volume_evidence_uri", volume_evidence_uri),
        ("restore_evidence_uri", restore_evidence_uri),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
    if validity <= timedelta(0) or validity > MAX_ATTESTATION_VALIDITY:
        raise ValueError("attestation validity must be positive and no longer than 7 days")
    issued = _coerce_time(issued_at)

    export_public_key_path = export_public_key_path.resolve()
    actual_export_key_sha256 = sha256_path(export_public_key_path)
    if actual_export_key_sha256 != expected_export_public_key_sha256:
        raise ValueError("export public key does not match the pinned fingerprint")
    export_receipt_path = export_receipt_path.resolve()
    export_signature_path = export_signature_path.resolve()
    signature = verify_manifest_signature(
        manifest=export_receipt_path,
        signature=export_signature_path,
        public_key=export_public_key_path,
    )
    if not signature["verified"]:
        raise ValueError("backup export receipt detached signature is invalid")
    export_receipt = _load_json_object(export_receipt_path, "backup export receipt")
    validate_backup_export_receipt_payload(
        export_receipt,
        expected_system_id=expected_system_id,
        now=issued,
    )
    export_captured_at = _parse_time(
        export_receipt.get("captured_at"),
        "export_receipt.captured_at",
    )
    if export_captured_at > issued:
        raise ValueError("backup export receipt was captured after attestation issuance")
    if export_receipt["subject"]["source_device_id"] != expected_source_device_id:
        raise ValueError("backup export source device does not match enrolled device")

    restore_evidence_path = restore_evidence_path.resolve()
    restore_evidence = _load_json_object(
        restore_evidence_path,
        "second-machine restore evidence",
    )
    validate_second_machine_restore_receipt(restore_evidence)
    _cross_bind_restore_to_export(
        restore_evidence=restore_evidence,
        export_receipt=export_receipt,
        export_receipt_path=export_receipt_path,
        export_signature_path=export_signature_path,
        export_public_key_path=export_public_key_path,
    )
    if restore_evidence["storage_topology"]["source_device_id"] != expected_source_device_id:
        raise ValueError("restore evidence source device does not match enrolled device")

    volume_evidence_path = volume_evidence_path.resolve()
    volume_evidence = _load_json_object(
        volume_evidence_path,
        "volume-encryption evidence",
    )
    volume_captured_at = validate_volume_encryption_evidence(
        volume_evidence,
        current_time=issued,
    )
    restore_captured_at = _parse_time(
        restore_evidence.get("captured_at"),
        "restore_evidence.captured_at",
    )
    for field, captured in (
        ("volume-encryption evidence", volume_captured_at),
        ("second-machine restore evidence", restore_captured_at),
    ):
        if captured > issued:
            raise ValueError(f"{field} was captured after attestation issuance")
        if issued - captured > MAX_EVIDENCE_AGE_AT_ISSUANCE:
            raise ValueError(f"{field} is older than the 24-hour issuance window")

    return {
        "schema_version": OPERATOR_ATTESTATION_SCHEMA,
        "status": "attested",
        "issued_at": _format_time(issued),
        "expires_at": _format_time(issued + validity),
        "subject": {
            "system_id": expected_system_id,
            "device_id": expected_source_device_id,
        },
        "attestor": {
            "id": attestor_id.strip(),
            "role": attestor_role.strip(),
        },
        "controls": [
            {
                "id": "volume_encryption",
                "status": "pass",
                "checked_at": _format_time(volume_captured_at),
                "method": (
                    "reviewed device encryption observation and bound its exact SHA-256"
                ),
                "evidence": [
                    {
                        "kind": "command_receipt",
                        "uri": volume_evidence_uri.strip(),
                        "sha256": sha256_path(volume_evidence_path),
                    }
                ],
            },
            {
                "id": "off_device_backup_restore",
                "status": "pass",
                "checked_at": _format_time(restore_captured_at),
                "method": (
                    "verified pinned export signature and distinct-device semantic restore"
                ),
                "evidence": [
                    {
                        "kind": "restore_receipt",
                        "uri": restore_evidence_uri.strip(),
                        "sha256": sha256_path(restore_evidence_path),
                    }
                ],
            },
        ],
    }


def validate_volume_encryption_evidence(
    payload: Any,
    *,
    current_time: datetime | None = None,
) -> datetime:
    if not isinstance(payload, dict):
        raise ValueError("volume-encryption evidence root must be an object")
    if payload.get("schema_version") != DEVICE_ENCRYPTION_EVIDENCE_SCHEMA:
        raise ValueError("volume-encryption evidence schema is unsupported")
    if payload.get("status") != "pass":
        raise ValueError("volume-encryption evidence status must be pass")
    checks = payload.get("checks")
    required = {
        "project_volume_inspected",
        "project_volume_encrypted",
        "system_filevault_on",
    }
    if not isinstance(checks, dict) or any(checks.get(item) is not True for item in required):
        raise ValueError("volume-encryption evidence does not pass every required check")
    captured_at = _parse_time(payload.get("captured_at"), "volume_evidence.captured_at")
    current = _coerce_time(current_time)
    if captured_at > current + MAX_FUTURE_CLOCK_SKEW:
        raise ValueError("volume-encryption evidence was captured in the future")
    return captured_at


def _cross_bind_restore_to_export(
    *,
    restore_evidence: dict[str, Any],
    export_receipt: dict[str, Any],
    export_receipt_path: Path,
    export_signature_path: Path,
    export_public_key_path: Path,
) -> None:
    restored_export = restore_evidence["export_receipt"]
    expected = {
        "schema_version": BACKUP_EXPORT_RECEIPT_SCHEMA,
        "export_id": export_receipt["export_id"],
        "system_id": export_receipt["subject"]["system_id"],
        "receipt_sha256": sha256_path(export_receipt_path),
        "signature_sha256": sha256_path(export_signature_path),
        "trusted_public_key_sha256": sha256_path(export_public_key_path),
    }
    for field, value in expected.items():
        if restored_export.get(field) != value:
            raise ValueError(
                f"second-machine restore evidence {field} does not match the signed export"
            )
    if restore_evidence.get("schema_version") != SECOND_MACHINE_RESTORE_SCHEMA:
        raise ValueError("second-machine restore evidence schema is unsupported")
    if restore_evidence["backup"] != export_receipt["backup"]:
        raise ValueError(
            "second-machine restore backup binding does not match the signed export"
        )
    if (
        restore_evidence["storage_topology"]["source_device_id"]
        != export_receipt["subject"]["source_device_id"]
    ):
        raise ValueError(
            "second-machine restore source device does not match the signed export"
        )


def _load_json_object(path: Path, field: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{field} root must be an object")
    return payload


def _validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_device_id(value: Any) -> str:
    if not isinstance(value, str) or not _DEVICE_ID_RE.fullmatch(value):
        raise ValueError("expected_source_device_id must be a sha256-prefixed digest")
    return value


def _validate_system_id(value: Any) -> str:
    if not isinstance(value, str) or not _SYSTEM_ID_RE.fullmatch(value):
        raise ValueError("expected_system_id is invalid")
    return value


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
