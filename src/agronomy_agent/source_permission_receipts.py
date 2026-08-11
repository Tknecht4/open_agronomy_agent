from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path


SCHEMA_VERSION = "open_agronomy_agent.provincial_permission_response_receipt.v1"
PACKET_SCHEMA_VERSION = "open_agronomy_agent.provincial_permission_request_packet.v1"
REGISTRY_SCHEMA_VERSION = "open_agronomy_agent.provincial_permission_response_registry.v1"
DEFAULT_PACKET_PATH = "data/manifests/provincial_permission_requests_20260725.json"
DEFAULT_REGISTRY_PATH = (
    "data/manifests/provincial_permission_response_registry_20260725.json"
)
DEFAULT_RECEIPT_ROOT = "data/manifests/provincial_permission_responses"
GRANT_STATES = {"granted_exact_scope", "granted_derived_material_only"}
RESPONSE_STATES = GRANT_STATES | {"partial_or_ambiguous", "denied"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.json$")
ALLOWED_FIELDS = {
    "schema_version",
    "request_id",
    "jurisdiction",
    "source_url",
    "response_state",
    "received_at",
    "issuer_organization",
    "issuer_authority",
    "private_response_sha256",
    "granted_rights",
    "conditions",
    "whole_source_distribution",
    "term_end",
    "territory",
}
REGISTRY_ALLOWED_FIELDS = {
    "schema_version",
    "generated_at",
    "request_packet_sha256",
    "receipts",
    "boundary",
}
REGISTRY_ENTRY_ALLOWED_FIELDS = {
    "request_id",
    "receipt_file",
    "receipt_sha256",
}


def validate_permission_response_receipt(
    receipt: dict[str, Any],
    *,
    packet_path: str | Path = DEFAULT_PACKET_PATH,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    packet = json.loads(repo_path(packet_path).read_text(encoding="utf-8"))
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported permission request packet")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported permission response receipt")
    extra = set(receipt) - ALLOWED_FIELDS
    if extra:
        raise ValueError(f"permission response receipt has unsupported fields: {sorted(extra)}")

    requests = {
        str(request["request_id"]): request for request in packet.get("requests", [])
    }
    request_id = _required_text(receipt, "request_id")
    if request_id not in requests:
        raise ValueError("permission response receipt request_id is not in the frozen packet")
    request = requests[request_id]
    if _required_text(receipt, "jurisdiction") != request["jurisdiction"]:
        raise ValueError("permission response receipt jurisdiction does not match request")
    if _required_text(receipt, "source_url") != request["source_url"]:
        raise ValueError("permission response receipt source_url does not match request")

    response_state = _required_text(receipt, "response_state")
    if response_state not in RESPONSE_STATES:
        raise ValueError("permission response receipt response_state is invalid")
    received_at = _parse_utc_timestamp(_required_text(receipt, "received_at"))
    _required_text(receipt, "issuer_organization")
    _required_text(receipt, "issuer_authority")
    private_hash = _required_text(receipt, "private_response_sha256")
    if not SHA256_RE.fullmatch(private_hash):
        raise ValueError("private_response_sha256 must be a lowercase SHA-256 digest")

    granted_rights = receipt.get("granted_rights")
    if not isinstance(granted_rights, list) or any(
        not isinstance(right, str) or not right.strip() for right in granted_rights
    ):
        raise ValueError("granted_rights must be a list of non-empty strings")
    if len(granted_rights) != len(set(granted_rights)):
        raise ValueError("granted_rights must not contain duplicates")
    requested_rights = set(request["requested_rights"])
    unknown_rights = set(granted_rights) - requested_rights
    if unknown_rights:
        raise ValueError("granted_rights contains text not present in the frozen request")

    conditions = receipt.get("conditions")
    if not isinstance(conditions, list) or any(
        not isinstance(condition, str) or not condition.strip() for condition in conditions
    ):
        raise ValueError("conditions must be a list of non-empty strings")
    whole_source = receipt.get("whole_source_distribution")
    if whole_source is not None and not isinstance(whole_source, bool):
        raise ValueError("whole_source_distribution must be true, false, or null")
    term_end = receipt.get("term_end")
    parsed_term_end = None
    if term_end is not None:
        parsed_term_end = _parse_date(term_end)
    territory = _required_text(receipt, "territory")

    missing_rights = sorted(requested_rights - set(granted_rights))
    evaluation_date = as_of or dt.datetime.now(dt.UTC).date()
    expired = parsed_term_end is not None and parsed_term_end < evaluation_date
    future_response = received_at.date() > evaluation_date
    complete_grant = (
        response_state in GRANT_STATES
        and not missing_rights
        and not conditions
        and territory.casefold() == "worldwide"
        and not expired
        and not future_response
    )
    reasons = []
    if response_state not in GRANT_STATES:
        reasons.append(f"response state is {response_state}")
    if missing_rights:
        reasons.append(f"{len(missing_rights)} requested rights are not explicitly granted")
    if conditions:
        reasons.append("grant conditions require independent rights review")
    if territory.casefold() != "worldwide":
        reasons.append("territory does not cover the requested worldwide use")
    if expired:
        reasons.append(f"permission expired before {evaluation_date.isoformat()}")
    elif term_end is not None:
        reasons.append("permission has a finite term and requires expiry enforcement")
    if future_response:
        reasons.append("response receipt date is after the evaluation date")

    return {
        "schema_version": "open_agronomy_agent.permission_response_decision.v1",
        "request_id": request_id,
        "jurisdiction": request["jurisdiction"],
        "source_url": request["source_url"],
        "response_state": response_state,
        "received_at": received_at.isoformat(),
        "private_response_sha256": private_hash,
        "rights_gate_cleared": complete_grant,
        "admission_state": (
            "rights_gate_candidate_only" if complete_grant else "blocked_clarification_required"
        ),
        "activation_allowed": False,
        "whole_source_distribution_allowed": bool(whole_source) if complete_grant else False,
        "missing_requested_rights": missing_rights,
        "conditions": list(conditions),
        "term_end": term_end,
        "reasons": reasons,
        "coverage_next_action": (
            "Complete independent rights review; then agronomic review, "
            "jurisdiction and currency scoping, disjoint evaluation, and a new "
            "signed release. Do not activate this source from the receipt alone."
            if complete_grant
            else "Resolve the denial, ambiguity, conditions, territory, term, or "
            "missing requested rights. Do not admit this source."
        ),
        "mandatory_next_gates": [
            "independent rights review",
            "independent agronomic review",
            "jurisdiction and currency scoping",
            "disjoint retrieval and answer evaluation",
            "new signed release",
        ],
    }


def load_permission_response_registry(
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    receipt_root: str | Path = DEFAULT_RECEIPT_ROOT,
    packet_path: str | Path = DEFAULT_PACKET_PATH,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    registry_file = repo_path(registry_path).resolve()
    receipt_directory = repo_path(receipt_root).resolve()
    packet_file = repo_path(packet_path).resolve()
    registry = _read_object(registry_file, "permission response registry")
    packet = _read_object(packet_file, "permission request packet")

    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported permission response registry")
    extra = set(registry) - REGISTRY_ALLOWED_FIELDS
    if extra:
        raise ValueError(
            f"permission response registry has unsupported fields: {sorted(extra)}"
        )
    registry_generated_at = _parse_utc_timestamp(
        _required_text(registry, "generated_at"),
        field="generated_at",
    )
    _required_text(registry, "boundary")
    packet_hash = _sha256(packet_file)
    expected_packet_hash = _required_text(registry, "request_packet_sha256")
    if not SHA256_RE.fullmatch(expected_packet_hash):
        raise ValueError("request_packet_sha256 must be a lowercase SHA-256 digest")
    if expected_packet_hash != packet_hash:
        raise ValueError("permission response registry request packet hash does not match")
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported permission request packet")

    requests = {
        str(request["request_id"]): request for request in packet.get("requests", [])
    }
    entries = registry.get("receipts")
    if not isinstance(entries, list):
        raise ValueError("permission response registry receipts must be a list")
    decisions: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("permission response registry entry must be an object")
        extra = set(entry) - REGISTRY_ENTRY_ALLOWED_FIELDS
        if extra:
            raise ValueError(
                f"permission response registry entry has unsupported fields: {sorted(extra)}"
            )
        request_id = _required_text(entry, "request_id")
        if request_id not in requests:
            raise ValueError("permission response registry request_id is not in the packet")
        if request_id in decisions:
            raise ValueError("permission response registry request_id is duplicated")
        receipt_file = _required_text(entry, "receipt_file")
        if not RECEIPT_FILE_RE.fullmatch(receipt_file):
            raise ValueError("receipt_file must be a lowercase JSON filename")
        expected_receipt_hash = _required_text(entry, "receipt_sha256")
        if not SHA256_RE.fullmatch(expected_receipt_hash):
            raise ValueError("receipt_sha256 must be a lowercase SHA-256 digest")
        receipt_path = (receipt_directory / receipt_file).resolve()
        if not receipt_path.is_relative_to(receipt_directory):
            raise ValueError("permission response receipt escapes the receipt root")
        if receipt_path.is_symlink():
            raise ValueError("permission response receipt must not be a symlink")
        actual_receipt_hash = _sha256(receipt_path)
        if actual_receipt_hash != expected_receipt_hash:
            raise ValueError("permission response receipt hash does not match registry")
        receipt = _read_object(receipt_path, "permission response receipt")
        receipt_received_at = _parse_utc_timestamp(
            _required_text(receipt, "received_at")
        )
        if receipt_received_at > registry_generated_at:
            raise ValueError(
                "permission response receipt received_at is after registry generated_at"
            )
        decision = validate_permission_response_receipt(
            receipt,
            packet_path=packet_file,
            as_of=as_of,
        )
        if decision["request_id"] != request_id:
            raise ValueError("permission response registry request_id does not match receipt")
        decisions[request_id] = {
            "receipt_sha256": actual_receipt_hash,
            "decision": decision,
        }

    return {
        "schema_version": "open_agronomy_agent.permission_response_registry_decision.v1",
        "registry_sha256": _sha256(registry_file),
        "request_packet_sha256": packet_hash,
        "response_count": len(decisions),
        "responses": decisions,
        "boundary": _required_text(registry, "boundary"),
    }


def register_permission_response_receipt(
    receipt_path: str | Path,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    receipt_root: str | Path = DEFAULT_RECEIPT_ROOT,
    packet_path: str | Path = DEFAULT_PACKET_PATH,
    replace: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    registry_file = repo_path(registry_path).resolve()
    receipt_directory = repo_path(receipt_root).resolve()
    packet_file = repo_path(packet_path).resolve()
    receipt_reference = repo_path(receipt_path)
    if receipt_reference.is_symlink():
        raise ValueError("permission response receipt must not be a symlink")
    receipt_file = receipt_reference.resolve()
    if receipt_file.parent != receipt_directory:
        raise ValueError("public receipt must be a direct child of the receipt root")
    if not RECEIPT_FILE_RE.fullmatch(receipt_file.name):
        raise ValueError("receipt filename must be a lowercase JSON filename")

    current = load_permission_response_registry(
        registry_path=registry_file,
        receipt_root=receipt_directory,
        packet_path=packet_file,
    )
    receipt = _read_object(receipt_file, "permission response receipt")
    decision = validate_permission_response_receipt(receipt, packet_path=packet_file)
    receipt_hash = _sha256(receipt_file)
    registry = _read_object(registry_file, "permission response registry")
    entries = list(registry["receipts"])
    existing_index = next(
        (
            index
            for index, entry in enumerate(entries)
            if entry["request_id"] == decision["request_id"]
        ),
        None,
    )
    entry = {
        "request_id": decision["request_id"],
        "receipt_file": receipt_file.name,
        "receipt_sha256": receipt_hash,
    }
    if existing_index is not None and not replace:
        raise ValueError(
            "permission response registry already contains this request_id; "
            "use --replace only after reviewing the changed public receipt"
        )
    if existing_index is None:
        entries.append(entry)
    else:
        entries[existing_index] = entry
    registry["receipts"] = sorted(entries, key=lambda item: item["request_id"])
    timestamp = now or dt.datetime.now(dt.UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() != dt.timedelta(0):
        raise ValueError("registration time must include the UTC offset")
    registry["generated_at"] = timestamp.isoformat(timespec="seconds")

    registry_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=registry_file.parent,
            prefix=f".{registry_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(registry, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        load_permission_response_registry(
            registry_path=temporary_path,
            receipt_root=receipt_directory,
            packet_path=packet_file,
        )
        os.replace(temporary_path, registry_file)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    registered = load_permission_response_registry(
        registry_path=registry_file,
        receipt_root=receipt_directory,
        packet_path=packet_file,
    )
    return {
        "schema_version": "open_agronomy_agent.permission_response_registration.v1",
        "request_id": decision["request_id"],
        "receipt_sha256": receipt_hash,
        "replaced": existing_index is not None,
        "rights_gate_cleared": decision["rights_gate_cleared"],
        "activation_allowed": False,
        "registry_sha256": registered["registry_sha256"],
        "response_count": registered["response_count"],
        "coverage_next_action": decision["coverage_next_action"],
        "prior_response_count": current["response_count"],
    }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _parse_utc_timestamp(
    value: str,
    *,
    field: str = "received_at",
) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{field} must include the UTC offset")
    return parsed


def _parse_date(value: Any) -> dt.date:
    if not isinstance(value, str):
        raise ValueError("term_end must be an ISO date or null")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("term_end must be an ISO date or null") from exc


def _read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
