from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.accessibility_primary_flows.v1"

ACCESSIBILITY_AUDIT_PATH = ROOT / "frontend/src/accessibilityAudit.ts"
ACCESSIBILITY_TEST_PATH = ROOT / "frontend/src/accessibilityAudit.test.ts"
APP_TEST_PATH = ROOT / "frontend/src/App.test.tsx"
APP_PATH = ROOT / "frontend/src/App.tsx"
HOSTED_PATH = ROOT / "frontend/src/HostedPlatform.tsx"
DESIGN_TOKENS_PATH = ROOT / "frontend/src/designTokens.ts"
DESIGN_TOKENS_TEST_PATH = ROOT / "frontend/src/designTokens.test.ts"
LOW_BANDWIDTH_PATH = ROOT / "frontend/src/lowBandwidth.ts"
LOW_BANDWIDTH_TEST_PATH = ROOT / "frontend/src/lowBandwidth.test.ts"
DOC_PATH = ROOT / "docs/phase6_accessibility_audit.md"
MATRIX_PATH = ROOT / "docs/phase6_launch_gate_matrix.yaml"

REQUIRED_AUDIT_RULES = (
    "button-name",
    "form-control-name",
    "link-name",
    "image-alt",
    "no-positive-tabindex",
    "duplicate-id",
    "heading-order",
)
REQUIRED_PRIMARY_FLOW_TEST_IDS = (
    "hosted-create-thread",
    "hosted-account-export",
    "hosted-load-admin-ops",
)
REQUIRED_SEMANTIC_COLOR_TOKENS = (
    "success",
    "caution",
    "regulated",
    "missingData",
    "evidence",
    "source",
    "internalDebug",
)
REQUIRED_LOW_BANDWIDTH_REASONS = (
    "save_data",
    "slow_effective_type",
    "low_downlink",
    "high_rtt",
)
REQUIRED_LAUNCH_GATE_EVIDENCE = (
    "docs/phase6_accessibility_primary_flows.md",
    "scripts/validate_phase6_accessibility_primary_flows.py",
    "tests/test_phase6_accessibility_primary_flows.py",
    "outputs/phase6_accessibility_primary_flows_latest.json",
    "docs/phase6_accessibility_audit.md",
    "docs/phase6_design_tokens.md",
    "docs/phase6_low_bandwidth_mode.md",
    "frontend/src/accessibilityAudit.ts",
    "frontend/src/accessibilityAudit.test.ts",
    "frontend/src/designTokens.ts",
    "frontend/src/designTokens.test.ts",
    "frontend/src/lowBandwidth.ts",
    "frontend/src/lowBandwidth.test.ts",
    "frontend/src/App.test.tsx",
)


def validate_phase6_accessibility_primary_flows(
    *,
    accessibility_audit_path: Path = ACCESSIBILITY_AUDIT_PATH,
    accessibility_test_path: Path = ACCESSIBILITY_TEST_PATH,
    app_test_path: Path = APP_TEST_PATH,
    app_path: Path = APP_PATH,
    hosted_path: Path = HOSTED_PATH,
    design_tokens_path: Path = DESIGN_TOKENS_PATH,
    design_tokens_test_path: Path = DESIGN_TOKENS_TEST_PATH,
    low_bandwidth_path: Path = LOW_BANDWIDTH_PATH,
    low_bandwidth_test_path: Path = LOW_BANDWIDTH_TEST_PATH,
    doc_path: Path = DOC_PATH,
    matrix_path: Path = MATRIX_PATH,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    audit = _read(accessibility_audit_path, "accessibility_audit", failures)
    audit_test = _read(accessibility_test_path, "accessibility_test", failures)
    app_test = _read(app_test_path, "app_test", failures)
    app = _read(app_path, "app", failures)
    hosted = _read(hosted_path, "hosted_platform", failures)
    design_tokens = _read(design_tokens_path, "design_tokens", failures)
    design_tokens_test = _read(design_tokens_test_path, "design_tokens_test", failures)
    low_bandwidth = _read(low_bandwidth_path, "low_bandwidth", failures)
    low_bandwidth_test = _read(low_bandwidth_test_path, "low_bandwidth_test", failures)
    doc = _read(doc_path, "accessibility_doc", failures)
    matrix = _read(matrix_path, "launch_gate_matrix", failures)
    matrix_payload = _load_yaml(matrix_path, "launch_gate_matrix", failures)

    audit_rules_covered = _audit_rules_covered(audit, audit_test, failures)
    covered_audit_rule_ids = [rule for rule in REQUIRED_AUDIT_RULES if f"'{rule}'" in audit]
    missing_audit_rule_ids = [rule for rule in REQUIRED_AUDIT_RULES if rule not in covered_audit_rule_ids]
    primary_flow_audited = _require_all(
        app_test,
        "app_test",
        failures,
        [
            "passes Phase 6 accessibility audit across primary launch flows",
            "auditPhase6Accessibility(document)",
            "schemaVersion: 'phase6.frontend_accessibility_audit.v1'",
            "passed: true",
            "violationCount: 0",
            "hosted-account-export",
            "hosted-load-admin-ops",
            "hosted-create-thread",
        ],
    )
    covered_primary_flow_ids = [flow_id for flow_id in REQUIRED_PRIMARY_FLOW_TEST_IDS if flow_id in app_test]
    missing_primary_flow_ids = [flow_id for flow_id in REQUIRED_PRIMARY_FLOW_TEST_IDS if flow_id not in covered_primary_flow_ids]
    semantic_tokens_covered = _require_all(
        design_tokens + "\n" + design_tokens_test,
        "design_tokens",
        failures,
        [
            "requiredPhase6SemanticColorTokens",
            "'success'",
            "'caution'",
            "'regulated'",
            "'missingData'",
            "'evidence'",
            "'source'",
            "'internalDebug'",
            "publishes the required semantic color system from the packet",
            "keeps one typography scale in TypeScript and CSS",
        ],
    )
    covered_semantic_token_ids = [
        token
        for token in REQUIRED_SEMANTIC_COLOR_TOKENS
        if f"'{token}'" in design_tokens
    ]
    missing_semantic_token_ids = [token for token in REQUIRED_SEMANTIC_COLOR_TOKENS if token not in covered_semantic_token_ids]
    keyboard_and_alert_affordances = _require_all(
        app + "\n" + hosted + "\n" + doc,
        "keyboard_and_alerts",
        failures,
        [
            'role="alert"',
            "native buttons",
            "keyboard activation",
            "aria-label",
            "Public demo navigation has an explicit `aria-label`",
        ],
    )
    low_bandwidth_accessibility_covered = _low_bandwidth_covered(low_bandwidth, low_bandwidth_test, failures)
    covered_low_bandwidth_reasons = [
        reason
        for reason in REQUIRED_LOW_BANDWIDTH_REASONS
        if f"'{reason}'" in low_bandwidth and reason in low_bandwidth_test
    ]
    missing_low_bandwidth_reasons = [
        reason for reason in REQUIRED_LOW_BANDWIDTH_REASONS if reason not in covered_low_bandwidth_reasons
    ]
    docs_current = _require_all(
        doc,
        "accessibility_doc",
        failures,
        [
            "Audit date: 2026-06-01",
            "primary pre-demo flows",
            "WCAG-oriented DOM",
            "Residual Launch Rehearsal Work",
            "No accessibility blocker remains",
        ],
    )
    launch_gate_complete = _require_all(
        matrix,
        "launch_gate_matrix",
        failures,
        [
            "id: accessibility_primary_flows",
            "status: complete",
            "Accessibility pass for primary flows.",
        ],
    )
    launch_gate = _launch_gate(matrix_payload)
    _expect(launch_gate is not None, "launch_gate_matrix", "launch matrix must track accessibility_primary_flows", failures)
    launch_gate_evidence_ids = [str(item) for item in (launch_gate or {}).get("evidence") or []]
    missing_launch_gate_evidence_ids = sorted(set(REQUIRED_LAUNCH_GATE_EVIDENCE) - set(launch_gate_evidence_ids))
    extra_launch_gate_evidence_ids = sorted(set(launch_gate_evidence_ids) - set(REQUIRED_LAUNCH_GATE_EVIDENCE))
    for evidence_id in REQUIRED_LAUNCH_GATE_EVIDENCE:
        _expect(evidence_id in launch_gate_evidence_ids, "launch_gate_matrix", f"accessibility evidence missing {evidence_id}", failures)
        _expect((ROOT / evidence_id).exists(), "launch_gate_matrix", f"accessibility evidence path missing: {evidence_id}", failures)
    _expect(not extra_launch_gate_evidence_ids, "launch_gate_matrix", f"accessibility evidence includes non-packet ids: {extra_launch_gate_evidence_ids}", failures)

    accessibility_inventory_exact = (
        audit_rules_covered
        and primary_flow_audited
        and semantic_tokens_covered
        and keyboard_and_alert_affordances
        and low_bandwidth_accessibility_covered
        and docs_current
        and launch_gate_complete
        and not missing_audit_rule_ids
        and not missing_primary_flow_ids
        and not missing_semantic_token_ids
        and not missing_low_bandwidth_reasons
        and not missing_launch_gate_evidence_ids
        and not extra_launch_gate_evidence_ids
    )

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "launch_gate_complete": launch_gate_complete,
        "audit_rules_covered": audit_rules_covered,
        "primary_flow_audited": primary_flow_audited,
        "semantic_tokens_covered": semantic_tokens_covered,
        "keyboard_and_alert_affordances": keyboard_and_alert_affordances,
        "low_bandwidth_accessibility_covered": low_bandwidth_accessibility_covered,
        "docs_current": docs_current,
        "checked_rules": list(REQUIRED_AUDIT_RULES),
        "required_audit_rule_ids": list(REQUIRED_AUDIT_RULES),
        "covered_audit_rule_ids": covered_audit_rule_ids,
        "missing_audit_rule_ids": missing_audit_rule_ids,
        "required_primary_flow_ids": list(REQUIRED_PRIMARY_FLOW_TEST_IDS),
        "covered_primary_flow_ids": covered_primary_flow_ids,
        "missing_primary_flow_ids": missing_primary_flow_ids,
        "required_semantic_token_ids": list(REQUIRED_SEMANTIC_COLOR_TOKENS),
        "covered_semantic_token_ids": covered_semantic_token_ids,
        "missing_semantic_token_ids": missing_semantic_token_ids,
        "required_low_bandwidth_reasons": list(REQUIRED_LOW_BANDWIDTH_REASONS),
        "covered_low_bandwidth_reasons": covered_low_bandwidth_reasons,
        "missing_low_bandwidth_reasons": missing_low_bandwidth_reasons,
        "required_launch_gate_evidence_ids": list(REQUIRED_LAUNCH_GATE_EVIDENCE),
        "launch_gate_evidence_ids": launch_gate_evidence_ids,
        "missing_launch_gate_evidence_ids": missing_launch_gate_evidence_ids,
        "extra_launch_gate_evidence_ids": extra_launch_gate_evidence_ids,
        "accessibility_inventory_exact": accessibility_inventory_exact,
        "evidence": {
            "accessibility_audit": _display_path(accessibility_audit_path),
            "accessibility_test": _display_path(accessibility_test_path),
            "app_test": _display_path(app_test_path),
            "app": _display_path(app_path),
            "hosted_platform": _display_path(hosted_path),
            "design_tokens": _display_path(design_tokens_path),
            "design_tokens_test": _display_path(design_tokens_test_path),
            "low_bandwidth": _display_path(low_bandwidth_path),
            "low_bandwidth_test": _display_path(low_bandwidth_test_path),
            "accessibility_doc": _display_path(doc_path),
            "launch_gate_matrix": _display_path(matrix_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_accessibility_primary_flows_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _audit_rules_covered(audit: str, audit_test: str, failures: list[dict[str, str]]) -> bool:
    source_ok = _require_all(
        audit,
        "accessibility_audit",
        failures,
        [
            "schemaVersion: 'phase6.frontend_accessibility_audit.v1'",
            *[f"'{rule}'" for rule in REQUIRED_AUDIT_RULES],
        ],
    )
    test_ok = _require_all(audit_test, "accessibility_test", failures, [
        "fails closed on unlabeled controls and unnamed buttons",
        "passes labeled controls and ordinary heading order",
        "button-name",
        "form-control-name",
        "link-name",
        "image-alt",
        "no-positive-tabindex",
    ])
    return source_ok and test_ok


def _low_bandwidth_covered(low_bandwidth: str, low_bandwidth_test: str, failures: list[dict[str, str]]) -> bool:
    source_ok = _require_all(
        low_bandwidth,
        "low_bandwidth",
        failures,
        [
            "detectPhase6LowBandwidth",
            "save_data",
            "slow_effective_type",
            "low_downlink",
            "high_rtt",
            "private upload attachments are skipped",
        ],
    )
    test_ok = _require_all(
        low_bandwidth_test,
        "low_bandwidth_test",
        failures,
        [
            "detects data-saver and slow browser connections",
            "persists explicit user preference",
            "combines user preference and detection into an active mode",
            "private upload attachments are skipped",
        ],
    )
    return source_ok and test_ok


def _read(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _load_yaml(path: Path, section: str, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return {}
    if not isinstance(payload, dict):
        failures.append({"section": section, "reason": f"{_display_path(path)} must contain a YAML mapping"})
        return {}
    return payload


def _launch_gate(matrix: dict[str, Any]) -> dict[str, Any] | None:
    for row in matrix.get("launch_gates") or []:
        if isinstance(row, dict) and row.get("id") == "accessibility_primary_flows":
            return row
    return None


def _require_all(text: str, section: str, failures: list[dict[str, str]], snippets: list[str]) -> bool:
    missing = [snippet for snippet in snippets if snippet not in text]
    for snippet in missing:
        failures.append({"section": section, "reason": f"missing required evidence snippet: {snippet}"})
    return not missing


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> None:
    if not condition:
        failures.append({"section": section, "reason": reason})


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
