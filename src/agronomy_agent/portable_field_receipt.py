from __future__ import annotations

import base64
import binascii
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from agronomy_agent.answer_receipts import build_answer_integrity_receipt


PORTABLE_RECEIPT_SCHEMA_VERSION = (
    "open_agronomy_agent.field_offline_portable_runtime_receipt.v2"
)
REQUIRED_EVIDENCE_KINDS = {
    "client_runtime_network_probe",
    "public_egress_probe",
    "answer_trace",
    "model_identity_receipt",
    "field_session_capture",
    "power_runtime_log",
    "release_manifest",
}


def canonical_signing_payload(receipt: Mapping[str, Any]) -> bytes:
    payload = {
        key: value
        for key, value in receipt.items()
        if key != "signatures"
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def signing_payload_sha256(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_signing_payload(receipt)).hexdigest()


def sign_receipt(
    receipt: Mapping[str, Any],
    *,
    role: str,
    private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    if role not in {"operator", "witness"}:
        raise ValueError("role must be operator or witness")
    signer = receipt.get(role)
    if not isinstance(signer, Mapping) or not signer.get("id"):
        raise ValueError(f"receipt {role} identity is missing")
    signed = deepcopy(dict(receipt))
    payload = canonical_signing_payload(signed)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    signatures = signed.get("signatures")
    signature_set = dict(signatures) if isinstance(signatures, Mapping) else {}
    signature_set["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    signature_set[role] = {
        "algorithm": "ed25519",
        "signer_id": str(signer["id"]),
        "key_id": f"sha256:{hashlib.sha256(public_key).hexdigest()}",
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
        "signature_base64": base64.b64encode(
            private_key.sign(payload)
        ).decode("ascii"),
    }
    signed["signatures"] = signature_set
    return signed


def verify_receipt_signatures(receipt: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    signatures = receipt.get("signatures")
    if not isinstance(signatures, Mapping):
        return ["receipt signatures are missing"]
    payload = canonical_signing_payload(receipt)
    payload_sha = hashlib.sha256(payload).hexdigest()
    if signatures.get("payload_sha256") != payload_sha:
        errors.append("signed payload SHA-256 does not match the receipt")
    key_ids: list[str] = []
    for role in ("operator", "witness"):
        signer = receipt.get(role)
        record = signatures.get(role)
        if not isinstance(signer, Mapping) or not isinstance(record, Mapping):
            errors.append(f"{role} signature is missing")
            continue
        if record.get("algorithm") != "ed25519":
            errors.append(f"{role} signature algorithm must be ed25519")
        if record.get("signer_id") != signer.get("id"):
            errors.append(f"{role} signature signer does not match receipt identity")
        try:
            public_bytes = base64.b64decode(
                str(record.get("public_key_base64") or ""),
                validate=True,
            )
            signature_bytes = base64.b64decode(
                str(record.get("signature_base64") or ""),
                validate=True,
            )
        except (binascii.Error, ValueError):
            errors.append(f"{role} signature encoding is invalid")
            continue
        if len(public_bytes) != 32 or len(signature_bytes) != 64:
            errors.append(f"{role} Ed25519 key or signature length is invalid")
            continue
        key_id = f"sha256:{hashlib.sha256(public_bytes).hexdigest()}"
        key_ids.append(key_id)
        if record.get("key_id") != key_id:
            errors.append(f"{role} signature key ID does not match its public key")
        try:
            Ed25519PublicKey.from_public_bytes(public_bytes).verify(
                signature_bytes,
                payload,
            )
        except (InvalidSignature, ValueError):
            errors.append(f"{role} signature verification failed")
    if len(key_ids) == 2 and key_ids[0] == key_ids[1]:
        errors.append("operator and witness signing keys must be distinct")
    return errors


def _parse_time(value: Any, *, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{label} timestamp is missing")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} timestamp is invalid")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} timestamp must include a timezone")
        return None
    return parsed


def _require(
    condition: bool,
    message: str,
    errors: list[str],
) -> None:
    if not condition:
        errors.append(message)


def _load_nested_file(
    *,
    root: Path,
    relative: Any,
    expected_sha256: Any,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(relative, str):
        errors.append(f"{label} path is missing")
        return
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label} path escapes the repository root")
        return
    if not resolved.is_file():
        errors.append(f"{label} file is missing: {relative}")
        return
    actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if actual != expected_sha256:
        errors.append(f"{label} SHA-256 mismatch")


def _validate_release_manifest(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    evidence_sha256: str,
    errors: list[str],
) -> None:
    runtime = receipt.get("runtime") or {}
    archive = payload.get("archive") or {}
    _require(
        payload.get("schema_version") == "open_agronomy_agent.edge_container_release.v4"
        and payload.get("status") == "pass",
        "release manifest evidence is not a passing v4 release",
        errors,
    )
    _require(
        evidence_sha256 == runtime.get("release_manifest_sha256"),
        "release manifest evidence hash does not match receipt runtime binding",
        errors,
    )
    _require(
        payload.get("version") == runtime.get("release_version"),
        "release version does not match receipt",
        errors,
    )
    _require(
        archive.get("sha256") == runtime.get("archive_sha256"),
        "release archive SHA-256 does not match receipt",
        errors,
    )
    _require(
        payload.get("runtime_contract_sha256")
        == runtime.get("runtime_contract_sha256"),
        "release runtime contract does not match receipt",
        errors,
    )
    _require(
        payload.get("runtime_manifest_file_sha256")
        == runtime.get("runtime_manifest_sha256"),
        "release runtime manifest file hash does not match receipt",
        errors,
    )


def _validate_network_probe(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    errors: list[str],
) -> datetime | None:
    deployment = receipt.get("deployment") or {}
    witness = receipt.get("witness") or {}
    _require(
        payload.get("schema_version")
        == "open_agronomy_agent.portable_field_client_runtime_network_probe.v1"
        and payload.get("status") == "pass",
        "client-runtime network evidence is not a passing portable probe",
        errors,
    )
    _require(
        payload.get("client_device_id") == deployment.get("client_device_id")
        and payload.get("runtime_device_id") == deployment.get("runtime_device_id"),
        "client-runtime network probe device identities do not match receipt",
        errors,
    )
    _require(
        payload.get("witness_id") == witness.get("id"),
        "client-runtime network probe witness does not match receipt",
        errors,
    )
    _require(
        payload.get("client_runtime_link") == deployment.get("client_runtime_link"),
        "client-runtime link type does not match receipt",
        errors,
    )
    _require(
        isinstance(payload.get("target_origin"), str)
        and str(payload.get("target_origin")).startswith("https://"),
        "client-runtime probe did not use an authenticated HTTPS origin",
        errors,
    )
    for key, message in (
        ("tls_certificate_verified", "client did not verify the runtime TLS certificate"),
        ("runtime_reachable", "client did not reach the runtime"),
        (
            "client_public_internet_unavailable_or_disabled",
            "client public internet was not shown unavailable or disabled",
        ),
    ):
        _require(payload.get(key) is True, message, errors)
    _require(
        payload.get("runtime_health_status") == 200
        and payload.get("runtime_network_mode") == "offline",
        "client-runtime probe did not observe a healthy offline runtime",
        errors,
    )
    return _parse_time(
        payload.get("captured_at"),
        label="client-runtime network probe",
        errors=errors,
    )


def _validate_public_egress_probe(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    errors: list[str],
) -> datetime | None:
    runtime = receipt.get("runtime") or {}
    runtime_manifest = payload.get("runtime_manifest") or {}
    _require(
        payload.get("schema_version") == "open_agronomy_agent.offline_network_probe.v1"
        and payload.get("passed") is True,
        "public-egress evidence is not a passing offline network probe",
        errors,
    )
    _require(
        (payload.get("host_model") or {}).get("reachable") is True,
        "offline network probe did not reach the local model",
        errors,
    )
    _require(
        (payload.get("public_network") or {}).get("reachable") is False,
        "offline network probe did not block public egress",
        errors,
    )
    _require(
        runtime_manifest.get("available") is True
        and runtime_manifest.get("status") == "pass"
        and runtime_manifest.get("contract_sha256")
        == runtime.get("runtime_contract_sha256")
        and runtime_manifest.get("sha256")
        == runtime.get("runtime_manifest_sha256"),
        "offline network probe runtime binding does not match receipt",
        errors,
    )
    return _parse_time(
        payload.get("captured_at"),
        label="public-egress probe",
        errors=errors,
    )


def _validate_answer_trace(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    evidence_by_kind: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> datetime | None:
    _require(
        payload.get("schema_version")
        == "open_agronomy_agent.portable_field_answer_trace.v1",
        "answer trace evidence schema is unsupported",
        errors,
    )
    turn = payload.get("turn")
    if not isinstance(turn, Mapping):
        errors.append("answer trace evidence does not contain a turn")
        return None
    trace = turn.get("trace") if isinstance(turn.get("trace"), Mapping) else {}
    system_state = (
        turn.get("system_state")
        if isinstance(turn.get("system_state"), Mapping)
        else {}
    )
    expected = build_answer_integrity_receipt(
        session_id=str(turn.get("session_id") or ""),
        turn_id=str(turn.get("turn_id") or turn.get("id") or ""),
        created_at=str(turn.get("created_at") or ""),
        user_message=str(turn.get("user_message") or ""),
        answer=str(turn.get("answer") or ""),
        system_state=system_state,
        trace=trace,
    )
    observed_receipt = turn.get("answer_integrity_receipt")
    if not isinstance(observed_receipt, Mapping):
        errors.append("answer trace is missing its answer-integrity receipt")
    else:
        _require(
            observed_receipt.get("status") == "verified"
            and all(
                observed_receipt.get(key) == expected.get(key)
                for key in (
                    "session_id",
                    "turn_id",
                    "question_sha256",
                    "answer_sha256",
                    "trace_sha256",
                    "system_state_sha256",
                    "field_snapshot_sha256",
                    "receipt_sha256",
                )
            ),
            "answer trace integrity receipt does not verify its turn content",
            errors,
        )
    answer = receipt.get("answer") or {}
    _require(
        expected["session_id"] == answer.get("session_id")
        and expected["turn_id"] == answer.get("turn_id")
        and expected["question_sha256"] == answer.get("question_sha256")
        and expected["answer_sha256"] == answer.get("answer_sha256")
        and expected["trace_sha256"] == answer.get("trace_sha256"),
        "answer trace hashes or identifiers do not match portable receipt",
        errors,
    )
    lineage = ((trace.get("metadata") or {}).get("field_lineage") or {})
    _require(
        lineage.get("field_access_authorized") is True
        and lineage.get("field_context_id") == answer.get("field_context_id")
        and lineage.get("field_snapshot_sha256")
        == answer.get("field_snapshot_sha256"),
        "answer trace is not bound to the authorized field snapshot in receipt",
        errors,
    )
    model_identity = system_state.get("model_identity") or {}
    runtime = receipt.get("runtime") or {}
    model_evidence = evidence_by_kind.get("model_identity_receipt") or {}
    _require(
        model_identity.get("status") == "verified_runtime_receipt"
        and bool(model_identity.get("request_model_id"))
        and model_identity.get("response_model_id")
        == model_identity.get("request_model_id")
        and model_identity.get("configured_model_id")
        == runtime.get("configured_model_id")
        and model_identity.get("configured_model_revision")
        == runtime.get("configured_model_revision")
        and model_identity.get("receipt_sha256")
        == model_evidence.get("sha256"),
        "answer response is not bound to the supplied model identity receipt",
        errors,
    )
    network = payload.get("network") or {}
    _require(
        network.get("mode") == "offline"
        and network.get("external_calls_attempted") == 0,
        "answer trace evidence does not bind offline mode and zero external calls",
        errors,
    )
    return _parse_time(
        payload.get("captured_at"),
        label="answer trace capture",
        errors=errors,
    )


def _validate_model_identity(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    errors: list[str],
) -> None:
    runtime = receipt.get("runtime") or {}
    adaptation = payload.get("parametric_adaptation") or {}
    _require(
        payload.get("schema_version") == "open_agronomy_agent.model_host_identity.v2"
        and payload.get("status") == "ready",
        "model identity evidence is not a ready v2 host receipt",
        errors,
    )
    _require(
        payload.get("model_id") == runtime.get("configured_model_id")
        and payload.get("model_revision") == runtime.get("configured_model_revision"),
        "model identity evidence does not match receipt model",
        errors,
    )
    _require(
        adaptation.get("mode") == "base_only"
        and adaptation.get("adapter_path") is None,
        "model identity evidence does not preserve the base-only adaptation decision",
        errors,
    )
    for key in (
        "model_config_sha256",
        "server_command_sha256",
        "model_artifact_manifest_sha256",
        "process_id",
    ):
        _require(bool(payload.get(key)), f"model identity evidence is missing {key}", errors)


def _validate_field_session(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    root: Path,
    errors: list[str],
) -> datetime | None:
    deployment = receipt.get("deployment") or {}
    answer = receipt.get("answer") or {}
    witness = receipt.get("witness") or {}
    _require(
        payload.get("schema_version")
        == "open_agronomy_agent.portable_field_session_capture.v1"
        and payload.get("status") == "pass",
        "field-session evidence is not a passing portable capture",
        errors,
    )
    _require(
        payload.get("witness_id") == witness.get("id")
        and payload.get("client_device_id") == deployment.get("client_device_id")
        and payload.get("runtime_device_id") == deployment.get("runtime_device_id"),
        "field-session identities do not match receipt",
        errors,
    )
    _require(
        payload.get("session_id") == answer.get("session_id")
        and payload.get("turn_id") == answer.get("turn_id")
        and payload.get("field_context_id") == answer.get("field_context_id")
        and payload.get("field_snapshot_sha256")
        == answer.get("field_snapshot_sha256"),
        "field-session answer or field binding does not match receipt",
        errors,
    )
    _require(
        isinstance(payload.get("paired_origin"), str)
        and str(payload.get("paired_origin")).startswith("https://")
        and payload.get("certificate_trusted_by_client") is True
        and payload.get("pairing_secret_recorded") is False,
        "field-session capture does not prove trusted pairing without secret retention",
        errors,
    )
    visual = payload.get("visual_evidence") or {}
    _load_nested_file(
        root=root,
        relative=visual.get("path"),
        expected_sha256=visual.get("sha256"),
        label="field-session visual evidence",
        errors=errors,
    )
    return _parse_time(
        payload.get("captured_at"),
        label="field-session capture",
        errors=errors,
    )


def _validate_power_log(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    errors: list[str],
) -> tuple[datetime | None, datetime | None]:
    deployment = receipt.get("deployment") or {}
    witness = receipt.get("witness") or {}
    _require(
        payload.get("schema_version")
        == "open_agronomy_agent.portable_field_power_runtime_log.v1"
        and payload.get("status") == "pass",
        "power-runtime evidence is not a passing portable log",
        errors,
    )
    _require(
        payload.get("witness_id") == witness.get("id")
        and payload.get("runtime_device_id") == deployment.get("runtime_device_id")
        and payload.get("portable_power_source")
        == deployment.get("portable_power_source"),
        "power-runtime identities or source do not match receipt",
        errors,
    )
    started = _parse_time(payload.get("started_at"), label="power log start", errors=errors)
    ended = _parse_time(payload.get("ended_at"), label="power log end", errors=errors)
    samples = payload.get("samples")
    if not isinstance(samples, list) or len(samples) < 4:
        errors.append("power-runtime log requires at least four heartbeat samples")
        samples = []
    sample_times: list[datetime] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            errors.append(f"power-runtime sample {index} is invalid")
            continue
        observed = _parse_time(
            sample.get("captured_at"),
            label=f"power-runtime sample {index}",
            errors=errors,
        )
        if observed:
            sample_times.append(observed)
        _require(
            sample.get("runtime_reachable") is True
            and sample.get("public_egress_blocked") is True
            and sample.get("portable_power_confirmed") is True,
            f"power-runtime sample {index} does not preserve all required states",
            errors,
        )
    if started and ended:
        minutes = (ended - started).total_seconds() / 60
        _require(
            minutes >= max(30, int(deployment.get("observed_runtime_minutes") or 0)),
            "power-runtime observation duration is shorter than receipt claim",
            errors,
        )
        if sample_times:
            _require(
                min(sample_times) >= started and max(sample_times) <= ended,
                "power-runtime samples fall outside the observation interval",
                errors,
            )
            _require(
                (max(sample_times) - min(sample_times)).total_seconds() / 60 >= 30,
                "power-runtime heartbeat samples do not span 30 minutes",
                errors,
            )
    return started, ended


def validate_evidence_payloads(
    *,
    receipt: Mapping[str, Any],
    root: Path,
    evidence_by_kind: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    errors: list[str] = []
    observed = set(evidence_by_kind)
    missing = sorted(REQUIRED_EVIDENCE_KINDS - observed)
    extra = sorted(observed - REQUIRED_EVIDENCE_KINDS)
    if missing:
        errors.append(f"required evidence kinds are missing: {missing}")
    if extra:
        errors.append(f"unsupported evidence kinds are present: {extra}")
    if errors:
        return errors

    release = evidence_by_kind["release_manifest"]
    _validate_release_manifest(
        release["payload"],
        receipt,
        str(release["sha256"]),
        errors,
    )
    network_time = _validate_network_probe(
        evidence_by_kind["client_runtime_network_probe"]["payload"],
        receipt,
        errors,
    )
    egress_time = _validate_public_egress_probe(
        evidence_by_kind["public_egress_probe"]["payload"],
        receipt,
        errors,
    )
    answer_time = _validate_answer_trace(
        evidence_by_kind["answer_trace"]["payload"],
        receipt,
        evidence_by_kind,
        errors,
    )
    _validate_model_identity(
        evidence_by_kind["model_identity_receipt"]["payload"],
        receipt,
        errors,
    )
    session_time = _validate_field_session(
        evidence_by_kind["field_session_capture"]["payload"],
        receipt,
        root=root,
        errors=errors,
    )
    started, ended = _validate_power_log(
        evidence_by_kind["power_runtime_log"]["payload"],
        receipt,
        errors,
    )
    if started and ended:
        for label, observed in (
            ("client-runtime network probe", network_time),
            ("public-egress probe", egress_time),
            ("answer trace", answer_time),
            ("field-session capture", session_time),
        ):
            if observed and not (started <= observed <= ended):
                errors.append(f"{label} was not captured during the power observation")
        receipt_time = _parse_time(
            receipt.get("captured_at"),
            label="portable receipt",
            errors=errors,
        )
        if receipt_time and receipt_time < ended:
            errors.append("portable receipt was finalized before power observation ended")
    return errors
