#!/usr/bin/env python3
"""Build and preflight an unsigned v2 portable-field receipt from real evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from agronomy_agent.answer_receipts import build_answer_integrity_receipt
from agronomy_agent.portable_field_receipt import (
    PORTABLE_RECEIPT_SCHEMA_VERSION,
    REQUIRED_EVIDENCE_KINDS,
    validate_evidence_payloads,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILENAMES = {
    "client_runtime_network_probe": "client_runtime_network_probe.json",
    "public_egress_probe": "public_egress_probe.json",
    "answer_trace": "answer_trace.json",
    "model_identity_receipt": "model_identity_receipt.json",
    "field_session_capture": "field_session_capture.json",
    "power_runtime_log": "power_runtime_log.json",
    "release_manifest": "release_manifest.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _timestamp(value: Any, *, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} timestamp is missing")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timestamp must include a timezone")
    return parsed


def _evidence_inventory(
    *,
    root: Path,
    evidence_paths: Mapping[str, Path],
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    if set(evidence_paths) != REQUIRED_EVIDENCE_KINDS:
        missing = sorted(REQUIRED_EVIDENCE_KINDS - set(evidence_paths))
        extra = sorted(set(evidence_paths) - REQUIRED_EVIDENCE_KINDS)
        raise ValueError(f"evidence mapping mismatch; missing={missing}; extra={extra}")
    inventory: list[dict[str, str]] = []
    evidence_by_kind: dict[str, dict[str, Any]] = {}
    root_resolved = root.resolve()
    for kind in sorted(REQUIRED_EVIDENCE_KINDS):
        path = evidence_paths[kind].resolve()
        try:
            relative = path.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"{kind} evidence must be inside {root_resolved}") from exc
        if not path.is_file():
            raise ValueError(f"{kind} evidence is missing: {relative}")
        sha256 = _sha256(path)
        payload = _load_object(path)
        inventory.append(
            {"kind": kind, "path": str(relative), "sha256": sha256}
        )
        evidence_by_kind[kind] = {
            "path": str(relative),
            "sha256": sha256,
            "payload": payload,
        }
    return inventory, evidence_by_kind


def build_receipt(
    *,
    root: Path,
    evidence_paths: Mapping[str, Path],
    receipt_id: str,
    captured_at: str,
    field_task: Mapping[str, str],
    operator: Mapping[str, str],
    witness: Mapping[str, Any],
    boundary: str,
) -> dict[str, Any]:
    root = root.resolve()
    evidence, evidence_by_kind = _evidence_inventory(
        root=root,
        evidence_paths=evidence_paths,
    )
    payloads = {
        kind: row["payload"] for kind, row in evidence_by_kind.items()
    }
    client = payloads["client_runtime_network_probe"]
    egress = payloads["public_egress_probe"]
    answer_trace = payloads["answer_trace"]
    model = payloads["model_identity_receipt"]
    power = payloads["power_runtime_log"]
    release = payloads["release_manifest"]
    turn = answer_trace.get("turn")
    if not isinstance(turn, Mapping):
        raise ValueError("answer trace does not contain a turn object")
    trace = turn.get("trace") if isinstance(turn.get("trace"), Mapping) else {}
    system_state = (
        turn.get("system_state")
        if isinstance(turn.get("system_state"), Mapping)
        else {}
    )
    lineage = ((trace.get("metadata") or {}).get("field_lineage") or {})
    answer_integrity = build_answer_integrity_receipt(
        session_id=str(turn.get("session_id") or ""),
        turn_id=str(turn.get("turn_id") or turn.get("id") or ""),
        created_at=str(turn.get("created_at") or ""),
        user_message=str(turn.get("user_message") or ""),
        answer=str(turn.get("answer") or ""),
        system_state=system_state,
        trace=trace,
    )
    started = _timestamp(power.get("started_at"), label="power log start")
    ended = _timestamp(power.get("ended_at"), label="power log end")
    observed_minutes = int((ended - started).total_seconds() // 60)
    release_archive = (
        release.get("archive")
        if isinstance(release.get("archive"), Mapping)
        else {}
    )
    runtime_manifest = (
        egress.get("runtime_manifest")
        if isinstance(egress.get("runtime_manifest"), Mapping)
        else {}
    )
    receipt = {
        "schema_version": PORTABLE_RECEIPT_SCHEMA_VERSION,
        "status": "pass",
        "receipt_id": receipt_id,
        "captured_at": captured_at,
        "field_task": dict(field_task),
        "operator": dict(operator),
        "witness": dict(witness),
        "deployment": {
            "topology": "portable_field_runtime",
            "client_device_id": client.get("client_device_id"),
            "runtime_device_id": client.get("runtime_device_id"),
            "devices_distinct": (
                client.get("client_device_id") != client.get("runtime_device_id")
            ),
            "client_runtime_link": client.get("client_runtime_link"),
            "client_runtime_reachable": client.get("runtime_reachable") is True,
            "client_public_internet_unavailable_or_disabled": (
                client.get("client_public_internet_unavailable_or_disabled")
                is True
            ),
            "public_egress_blocked": (
                egress.get("passed") is True
                and (egress.get("public_network") or {}).get("reachable") is False
            ),
            "portable_power_source": power.get("portable_power_source"),
            "observed_runtime_minutes": observed_minutes,
        },
        "runtime": {
            "release_version": release.get("version"),
            "release_manifest_sha256": evidence_by_kind["release_manifest"][
                "sha256"
            ],
            "archive_sha256": release_archive.get("sha256"),
            "runtime_contract_sha256": release.get("runtime_contract_sha256"),
            "runtime_manifest_sha256": release.get(
                "runtime_manifest_file_sha256"
            ),
            "configured_model_id": model.get("model_id"),
            "configured_model_revision": model.get("model_revision"),
            "model_identity_verified": model.get("status") == "ready",
        },
        "answer": {
            "question_sha256": answer_integrity["question_sha256"],
            "answer_sha256": answer_integrity["answer_sha256"],
            "trace_sha256": answer_integrity["trace_sha256"],
            "session_id": answer_integrity["session_id"],
            "turn_id": answer_integrity["turn_id"],
            "field_context_id": lineage.get("field_context_id"),
            "field_snapshot_sha256": lineage.get("field_snapshot_sha256"),
            "model_response_identity_bound": True,
            "field_context_snapshot_bound": True,
            "network_mode": (answer_trace.get("network") or {}).get("mode"),
            "external_calls_attempted": (
                answer_trace.get("network") or {}
            ).get("external_calls_attempted"),
        },
        "evidence": evidence,
        "boundary": boundary,
    }
    errors = validate_evidence_payloads(
        receipt=receipt,
        root=root,
        evidence_by_kind=evidence_by_kind,
    )
    if errors:
        raise ValueError("portable evidence preflight failed: " + "; ".join(errors))
    if runtime_manifest.get("sha256") != receipt["runtime"][
        "runtime_manifest_sha256"
    ]:
        raise ValueError(
            "public-egress evidence and release manifest name different runtime manifests"
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--packet-dir", type=Path, required=True)
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--captured-at")
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--crop-or-land-use", required=True)
    parser.add_argument("--question-class", required=True)
    parser.add_argument(
        "--location-privacy",
        choices=("generalized", "withheld"),
        default="generalized",
    )
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--operator-role", default="farmer")
    parser.add_argument("--witness-id", required=True)
    parser.add_argument("--witness-role", default="independent agronomist")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    packet_dir = (
        args.packet_dir.resolve()
        if args.packet_dir.is_absolute()
        else (root / args.packet_dir).resolve()
    )
    try:
        packet_dir.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"packet directory must be inside {root}") from exc
    output = args.output or packet_dir / "receipt-unsigned.json"
    output = output if output.is_absolute() else root / output
    if output.exists():
        raise SystemExit(f"refusing to overwrite receipt draft: {output}")
    captured_at = args.captured_at or dt.datetime.now(dt.UTC).replace(
        microsecond=0
    ).isoformat()
    evidence_paths = {
        kind: packet_dir / filename
        for kind, filename in DEFAULT_FILENAMES.items()
    }
    try:
        receipt = build_receipt(
            root=root,
            evidence_paths=evidence_paths,
            receipt_id=args.receipt_id,
            captured_at=captured_at,
            field_task={
                "jurisdiction": args.jurisdiction,
                "crop_or_land_use": args.crop_or_land_use,
                "question_class": args.question_class,
                "location_privacy": args.location_privacy,
            },
            operator={"id": args.operator_id, "role": args.operator_role},
            witness={
                "id": args.witness_id,
                "role": args.witness_role,
                "observed_live": True,
                "independent_from_development": True,
            },
            boundary=(
                "This receipt proves one independently observed portable topology. "
                "It does not establish general agronomic safety, signer identity, "
                "farmer comprehension, or universal device support."
            ),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "preflight_pass",
                "output": str(output),
                "evidence_count": len(receipt["evidence"]),
                "observed_runtime_minutes": receipt["deployment"][
                    "observed_runtime_minutes"
                ],
                "next_step": (
                    "Sign operator then witness with "
                    "scripts/sign_portable_field_runtime_receipt.py."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
