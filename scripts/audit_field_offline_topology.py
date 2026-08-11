#!/usr/bin/env python3
"""Separate prepared-runtime offline proof from portable field-client proof."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from agronomy_agent.portable_field_receipt import (
    REQUIRED_EVIDENCE_KINDS,
    validate_evidence_payloads,
    verify_receipt_signatures,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.field_offline_topology_readiness.v1"
DEFAULT_SCHEMA = ROOT / "data/manifests/field_offline_portable_runtime_receipt_schema_v2.json"
DEFAULT_RECEIPT = ROOT / "outputs/field_offline_portable_runtime_receipt_v2.json"
DEFAULT_PWA = ROOT / "outputs/phase6_pwa_offline_lite_latest.json"
DEFAULT_COLD_AUDIT = ROOT / "outputs/current_source_readiness_20260725/offline_cold_start_audit.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "container/runtime_manifest.json"
DEFAULT_OUTPUT = ROOT / "outputs/field_offline_topology_readiness_latest.json"
PRODUCTION_ENTRY = ROOT / "frontend/src/main.tsx"
PRODUCTION_APP = ROOT / "frontend/src/OpenAgronomyApp.tsx"
CAPABILITY = ROOT / "frontend/src/fieldRuntimeAvailability.ts"
WORKFLOW_TEST = ROOT / "frontend/src/openAgronomyMapWorkflow.test.tsx"
RUN_COCKPIT = ROOT / "scripts/run_cockpit.py"
APPLE_LAUNCHER = ROOT / "container/apple.sh"
FIELD_LAN_PREFLIGHT = ROOT / "scripts/validate_field_lan_launch.py"
LOCAL_PAIRING = ROOT / "frontend/src/localPairing.ts"
LOCAL_PAIRING_TEST = ROOT / "tests/test_local_field_pairing.py"

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _contains(path: Path, *snippets: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return all(snippet in text for snippet in snippets)


def _prepared_runtime_passes(path: Path, runtime_manifest_path: Path) -> bool:
    if not path.is_file() or not runtime_manifest_path.is_file():
        return False
    try:
        row = _load_json(path)
        runtime_manifest = _load_json(runtime_manifest_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    checks = row.get("checks") or {}
    binding = row.get("runtime_manifest") or {}
    return (
        row.get("status") == "pass"
        and checks.get("container_public_egress_blocked") is True
        and checks.get("model_response_identity_bound") is True
        and checks.get("runtime_manifest_contract_bound") is True
        and checks.get("trace_declares_offline") is True
        and checks.get("trace_records_zero_external_attempts") is True
        and binding.get("contract_sha256")
        == runtime_manifest.get("contract_sha256")
        and binding.get("sha256") == _sha256(runtime_manifest_path)
    )


def _pwa_production_gate_passes(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        row = _load_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    evidence = row.get("evidence") or {}
    return (
        row.get("gate_passed") is True
        and evidence.get("app_shell") == "frontend/src/OpenAgronomyApp.tsx"
        and row.get("draft_preservation_ready") is True
        and row.get("offline_storage_recovery_ready") is True
        and row.get("no_offline_model_generation") is True
    )


def validate_portable_receipt(
    *,
    root: Path,
    receipt_path: Path,
    schema_path: Path,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    if not receipt_path.is_file():
        return False, ["portable field-runtime receipt not supplied"], None
    try:
        receipt = _load_json(receipt_path)
        schema = _load_json(schema_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return False, [f"receipt or schema could not be loaded: {exc}"], None

    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in sorted(
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).iter_errors(receipt),
            key=lambda error: list(error.absolute_path),
        )
    ]
    deployment = receipt.get("deployment") or {}
    if deployment.get("client_device_id") == deployment.get("runtime_device_id"):
        errors.append("deployment client and runtime device identities must be distinct")
    if (receipt.get("operator") or {}).get("id") == (receipt.get("witness") or {}).get("id"):
        errors.append("operator and independent witness identities must be distinct")

    evidence = receipt.get("evidence") or []
    observed_kind_rows = [
        str(item.get("kind") or "")
        for item in evidence
        if isinstance(item, dict)
    ]
    observed_kinds = set(observed_kind_rows)
    missing_kinds = sorted(REQUIRED_EVIDENCE_KINDS - observed_kinds)
    if missing_kinds:
        errors.append(f"required evidence kinds are missing: {missing_kinds}")
    duplicate_kinds = sorted(
        kind
        for kind in observed_kinds
        if observed_kind_rows.count(kind) > 1
    )
    if duplicate_kinds:
        errors.append(f"evidence kinds must be unique: {duplicate_kinds}")

    root_resolved = root.resolve()
    verified_evidence: list[dict[str, Any]] = []
    evidence_by_kind: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        relative = item.get("path")
        if not isinstance(relative, str):
            continue
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            errors.append(f"evidence[{index}] escapes the repository root")
            continue
        if not resolved.is_file():
            errors.append(f"evidence[{index}] is missing: {relative}")
            continue
        actual = _sha256(resolved)
        expected = item.get("sha256")
        if actual != expected:
            errors.append(
                f"evidence[{index}] SHA-256 mismatch: expected {expected}; observed {actual}"
            )
            continue
        try:
            payload = _load_json(resolved)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"evidence[{index}] is not a JSON object: {exc}")
            continue
        kind = str(item.get("kind") or "")
        if kind not in evidence_by_kind:
            evidence_by_kind[kind] = {
                "path": relative,
                "sha256": actual,
                "payload": payload,
            }
        verified_evidence.append(
            {"kind": item.get("kind"), "path": relative, "sha256": actual}
        )

    errors.extend(verify_receipt_signatures(receipt))
    errors.extend(
        validate_evidence_payloads(
            receipt=receipt,
            root=root,
            evidence_by_kind=evidence_by_kind,
        )
    )
    if errors:
        return False, errors, receipt
    return True, [], {**receipt, "verified_evidence": verified_evidence}


def build_report(
    *,
    root: Path = ROOT,
    schema_path: Path = DEFAULT_SCHEMA,
    receipt_path: Path = DEFAULT_RECEIPT,
    pwa_path: Path = DEFAULT_PWA,
    cold_audit_path: Path = DEFAULT_COLD_AUDIT,
    runtime_manifest_path: Path = DEFAULT_RUNTIME_MANIFEST,
) -> dict[str, Any]:
    portable_pass, portable_errors, portable_receipt = validate_portable_receipt(
        root=root,
        receipt_path=receipt_path,
        schema_path=schema_path,
    )
    if portable_pass:
        current_runtime = _load_json(runtime_manifest_path)
        receipt_runtime = (portable_receipt or {}).get("runtime") or {}
        expected_contract = current_runtime.get("contract_sha256")
        expected_manifest = _sha256(runtime_manifest_path)
        if receipt_runtime.get("runtime_contract_sha256") != expected_contract:
            portable_errors.append(
                "portable receipt runtime contract does not match the current sealed runtime"
            )
        if receipt_runtime.get("runtime_manifest_sha256") != expected_manifest:
            portable_errors.append(
                "portable receipt runtime manifest does not match the current sealed runtime"
            )
        portable_pass = not portable_errors
    checks = {
        "production_entrypoint_uses_open_agronomy_app": _contains(
            root / PRODUCTION_ENTRY.relative_to(ROOT),
            "OpenAgronomyApp",
        ),
        "production_ui_uses_runtime_capability_gate": _contains(
            root / PRODUCTION_APP.relative_to(ROOT),
            "fieldAnswerCapability",
            "answerCapability.canGenerateAnswer",
        ),
        "production_ui_preserves_device_local_question_draft": _contains(
            root / PRODUCTION_APP.relative_to(ROOT),
            "loadPhase6ChatDraft",
            "savePhase6ChatDraft",
            "clearPhase6ChatDraft",
        ),
        "production_ui_preserves_device_local_field_notes": _contains(
            root / PRODUCTION_APP.relative_to(ROOT),
            "loadPhase6Scratchpad",
            "savePhase6Scratchpad",
            "clearPhase6Scratchpad",
        ),
        "production_ui_preserves_unreadable_local_data": _contains(
            root / PRODUCTION_APP.relative_to(ROOT),
            "PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT",
            "offline-storage-recovery-notice",
            "downloadPhase6OfflineStorageRecovery",
        ),
        "disconnected_client_is_notes_only": _contains(
            root / CAPABILITY.relative_to(ROOT),
            "Runtime unavailable · notes only",
            "This device cannot generate an answer.",
            "canGenerateAnswer: false",
        ),
        "disconnected_client_behavior_is_integration_tested": _contains(
            root / WORKFLOW_TEST.relative_to(ROOT),
            "Runtime unavailable · notes only",
            "This device cannot generate an answer",
        ),
        "non_loopback_bind_refuses_anonymous_local_auth": _contains(
            root / RUN_COCKPIT.relative_to(ROOT),
            "_validate_bind_security",
            "refusing a non-loopback bind while local development authentication is enabled",
        ),
        "field_lan_requires_tls_offline_and_single_use_pairing": _contains(
            root / RUN_COCKPIT.relative_to(ROOT),
            "--field-lan",
            "--tls-certfile",
            'network_mode="offline" if args.field_lan else None',
            "secrets.token_urlsafe(32)",
        ),
        "sealed_runtime_field_lan_launch_is_fail_closed": _contains(
            root / APPLE_LAUNCHER.relative_to(ROOT),
            "start-field-lan",
            "validate_field_lan_launch.py",
            '--publish "${FIELD_LAN_BIND_ADDRESS}:${APP_PORT}:${CONTAINER_PORT}"',
            "--env AGRONOMY_AGENT_NETWORK_MODE=offline",
            "--env AGRONOMY_AGENT_FIELD_LAN=true",
            "--env AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH=false",
            "--env AGRONOMY_AGENT_LOCAL_PAIRING_TOKEN_SHA256",
            "--ssl-certfile /run/open-agronomy-field-lan/tls.crt",
        )
        and _contains(
            root / FIELD_LAN_PREFLIGHT.relative_to(ROOT),
            "specific private or link-local IPv4 address",
            "TLS private key must not be group- or world-readable",
            "_validate_tls_identity",
        ),
        "browser_pairing_fragment_is_cleared_before_exchange": _contains(
            root / LOCAL_PAIRING.relative_to(ROOT),
            "history.replaceState",
            "/auth/local-pair",
        ),
        "paired_client_auth_is_integration_tested": _contains(
            root / LOCAL_PAIRING_TEST.relative_to(ROOT),
            "test_single_use_pairing_unlocks_only_the_paired_browser_session",
            "test_pairing_session_keeps_csrf_protection_for_unsafe_requests",
        ),
        "production_pwa_gate_passes": _pwa_production_gate_passes(pwa_path),
        "prepared_runtime_egress_isolation_passes": _prepared_runtime_passes(
            cold_audit_path,
            runtime_manifest_path,
        ),
        "portable_field_runtime_receipt_passes": portable_pass,
    }
    implementation_checks = {
        key: value
        for key, value in checks.items()
        if key != "portable_field_runtime_receipt_passes"
    }
    status = (
        "pass"
        if all(implementation_checks.values()) and portable_pass
        else "blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "status": status,
        "checks": checks,
        "topology_claims": {
            "prepared_runtime_offline": (
                "supported"
                if checks["prepared_runtime_egress_isolation_passes"]
                else "not_supported"
            ),
            "disconnected_client_answers_without_runtime_path": "not_supported_by_design",
            "disconnected_client_notes_and_drafts": (
                "supported"
                if all(implementation_checks.values())
                else "not_supported"
            ),
            "portable_field_runtime_answers_without_public_internet": (
                "supported" if portable_pass else "not_yet_evidenced"
            ),
        },
        "portable_receipt": {
            "path": str(receipt_path.relative_to(root))
            if receipt_path.is_relative_to(root)
            else str(receipt_path),
            "exists": receipt_path.is_file(),
            "sha256": _sha256(receipt_path) if receipt_path.is_file() else None,
            "errors": portable_errors,
            "validated": portable_receipt if portable_pass else None,
        },
        "evidence": {
            "schema": str(schema_path.relative_to(root)),
            "pwa_readiness": str(pwa_path.relative_to(root)),
            "prepared_runtime_cold_audit": str(cold_audit_path.relative_to(root)),
            "runtime_manifest": str(runtime_manifest_path.relative_to(root)),
            "production_entry": str(PRODUCTION_ENTRY.relative_to(ROOT)),
            "production_app": str(PRODUCTION_APP.relative_to(ROOT)),
            "capability_policy": str(CAPABILITY.relative_to(ROOT)),
            "workflow_test": str(WORKFLOW_TEST.relative_to(ROOT)),
            "field_lan_launcher": str(RUN_COCKPIT.relative_to(ROOT)),
            "sealed_field_lan_launcher": str(APPLE_LAUNCHER.relative_to(ROOT)),
            "field_lan_launch_preflight": str(
                FIELD_LAN_PREFLIGHT.relative_to(ROOT)
            ),
            "local_pairing_bootstrap": str(LOCAL_PAIRING.relative_to(ROOT)),
            "local_pairing_test": str(LOCAL_PAIRING_TEST.relative_to(ROOT)),
        },
        "boundary": (
            "Blocking public internet from a prepared runtime does not prove that a "
            "disconnected field client can reach that runtime. Without a validated "
            "portable runtime link, the field client is notes-and-drafts only."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pwa", type=Path, default=DEFAULT_PWA)
    parser.add_argument("--cold-audit", type=Path, default=DEFAULT_COLD_AUDIT)
    parser.add_argument(
        "--runtime-manifest",
        type=Path,
        default=DEFAULT_RUNTIME_MANIFEST,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    report = build_report(
        root=root,
        schema_path=resolve(args.schema),
        receipt_path=resolve(args.receipt),
        pwa_path=resolve(args.pwa),
        cold_audit_path=resolve(args.cold_audit),
        runtime_manifest_path=resolve(args.runtime_manifest),
    )
    output = resolve(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": report["checks"],
                "portable_receipt_errors": report["portable_receipt"]["errors"],
            },
            indent=2,
        )
    )
    return 1 if args.require_pass and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
