from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


PHASE6_LAUNCH_GATE_MATRIX_VERSION = "phase6.launch_gate_matrix.v1"
VALID_STATUSES = {
    "complete",
    "needs_human_signoff",
    "pending_provider_target",
    "pending_manual_review",
    "pending_provider_staffing",
}
OPEN_STATUSES = VALID_STATUSES - {"complete"}
EXPECTED_LAUNCH_GATES = [
    "No hidden prompt/checklist/tool/routing leakage in 200-turn launch QA suite.",
    "No critical auth/session/privacy bugs.",
    "Users can export and delete data.",
    "Reports render correctly and include source/provenance metadata.",
    "Public demo routes meet frontend performance budgets or have documented exceptions.",
    "Chat usable on desktop, tablet, and mobile.",
    "Accessibility pass for primary flows.",
    "All public pages have reviewed claims and caveats.",
    "Admin trace view works but is access controlled.",
    "Feedback creates reviewable improvement records.",
    "Browser local inference is disabled by default or clearly marked as experimental.",
    "Launch runbook has owners and rollback plan.",
]
EXPECTED_LAUNCH_GATE_IDS = (
    "hidden_prompt_checklist_tool_routing_leakage",
    "auth_session_privacy_bugs",
    "data_export_delete",
    "reports_source_provenance",
    "frontend_performance_budget",
    "desktop_tablet_mobile_chat",
    "accessibility_primary_flows",
    "public_claims_caveats",
    "admin_trace_access_control",
    "feedback_reviewable_records",
    "local_inference_boundary",
    "runbook_owners_rollback",
)
EXPECTED_STATUS_BY_GATE_ID = {
    "hidden_prompt_checklist_tool_routing_leakage": "needs_human_signoff",
    "auth_session_privacy_bugs": "complete",
    "data_export_delete": "complete",
    "reports_source_provenance": "complete",
    "frontend_performance_budget": "pending_provider_target",
    "desktop_tablet_mobile_chat": "pending_manual_review",
    "accessibility_primary_flows": "complete",
    "public_claims_caveats": "needs_human_signoff",
    "admin_trace_access_control": "complete",
    "feedback_reviewable_records": "complete",
    "local_inference_boundary": "complete",
    "runbook_owners_rollback": "pending_provider_staffing",
}
EXPECTED_PACKET_TEXT_BY_GATE_ID = dict(zip(EXPECTED_LAUNCH_GATE_IDS, EXPECTED_LAUNCH_GATES, strict=True))
EXPECTED_EVIDENCE_BY_GATE_ID = {
    "hidden_prompt_checklist_tool_routing_leakage": [
        "outputs/phase6_launch_leak_qa_latest.json",
        "scripts/run_phase6_launch_leak_qa.py",
        "tests/test_phase6_launch_qa.py",
        "docs/phase6_human_signoff_decisions.yaml",
        "scripts/validate_phase6_human_signoff_decisions.py",
        "tests/test_phase6_human_signoff_decisions.py",
        "docs/phase6_human_signoff_packet.md",
    ],
    "auth_session_privacy_bugs": [
        "scripts/phase6_browser_auth_qa_flow.js",
        "docs/phase6_account_privacy_rights.md",
        "scripts/validate_phase6_account_privacy_rights.py",
        "tests/test_phase6_account_privacy_rights.py",
        "outputs/phase6_account_privacy_rights_latest.json",
        "scripts/validate_phase6_account_backlog.py",
        "docs/phase6_account_backlog_readiness.md",
        "outputs/phase6_account_backlog_latest.json",
        "tests/test_phase6_account_export.py",
        "tests/test_phase6_account_backlog.py",
        "tests/test_phase4_hosted_api.py",
        "frontend/src/App.test.tsx",
    ],
    "data_export_delete": [
        "docs/phase6_account_privacy_rights.md",
        "scripts/validate_phase6_account_privacy_rights.py",
        "tests/test_phase6_account_privacy_rights.py",
        "outputs/phase6_account_privacy_rights_latest.json",
        "tests/test_phase6_account_export.py",
        "tests/test_phase6_account_backlog.py",
        "scripts/validate_phase6_account_backlog.py",
        "outputs/phase6_account_backlog_latest.json",
        "tests/test_phase4_hosted_api.py",
        "docs/phase6_pre_demo_launch_status.md",
    ],
    "reports_source_provenance": [
        "docs/phase6_reports_source_provenance.md",
        "scripts/validate_phase6_reports_source_provenance.py",
        "tests/test_phase6_reports_source_provenance.py",
        "outputs/phase6_reports_source_provenance_latest.json",
        "tests/test_phase6_reports.py",
        "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_report_manifest_schema.json",
        "docs/phase6_sample_reports",
    ],
    "frontend_performance_budget": [
        "docs/phase6_frontend_performance_budget.md",
        "docs/phase6_container_launch_preflight.md",
        "docs/phase6_pre_provider_readiness.md",
        "docs/phase6_human_signoff_decisions.yaml",
        "scripts/validate_phase6_frontend_performance_budget.py",
        "scripts/validate_phase6_container_launch.py",
        "scripts/validate_phase6_final_host_performance_review.py",
        "scripts/validate_phase6_frontend_bundle_budget.py",
        "scripts/validate_phase6_pre_provider_readiness.py",
        "scripts/run_phase6_browser_performance_lab.py",
        "scripts/phase6_browser_performance_lab.js",
        "tests/test_phase6_frontend_performance_budget.py",
        "tests/test_phase6_container_launch.py",
        "tests/test_phase6_final_host_performance_review.py",
        "tests/test_phase6_frontend_bundle_budget.py",
        "tests/test_phase6_pre_provider_readiness.py",
        "outputs/phase6_frontend_performance_budget_latest.json",
        "outputs/phase6_container_launch_preflight_latest.json",
        "outputs/phase6_final_host_performance_review_latest.json",
        "outputs/phase6_frontend_bundle_budget_latest.json",
        "outputs/phase6_pre_provider_readiness_latest.json",
    ],
    "desktop_tablet_mobile_chat": [
        "docs/phase6_responsive_mobile_qa.md",
        "outputs/phase6_responsive_mobile_qa_latest.json",
        "scripts/validate_phase6_responsive_mobile_qa.py",
        "docs/phase6_human_signoff_decisions.yaml",
        "frontend/src/responsiveAudit.ts",
        "frontend/src/App.test.tsx",
        "scripts/phase6_browser_responsive_qa_flow.js",
        "tests/test_phase6_responsive_mobile_qa.py",
    ],
    "accessibility_primary_flows": [
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
    ],
    "public_claims_caveats": [
        "docs/phase6_public_claims_review.md",
        "docs/phase6_human_signoff_decisions.yaml",
        "scripts/validate_phase6_human_signoff_decisions.py",
        "tests/test_phase6_human_signoff_decisions.py",
        "scripts/validate_phase6_public_claims.py",
        "tests/test_phase6_public_claims.py",
        "frontend/src/PublicDemoPages.tsx",
    ],
    "admin_trace_access_control": [
        "docs/phase6_admin_trace_access.md",
        "scripts/validate_phase6_admin_trace_access.py",
        "tests/test_phase6_admin_trace_access.py",
        "outputs/phase6_admin_trace_access_latest.json",
        "tests/test_phase5_observability.py",
        "frontend/src/HostedPlatform.tsx",
        "frontend/src/App.test.tsx",
    ],
    "feedback_reviewable_records": [
        "docs/phase6_feedback_review.md",
        "scripts/validate_phase6_feedback_review.py",
        "tests/test_phase6_feedback_review.py",
        "tests/test_phase4_hosted_api.py",
        "tests/test_phase6_reports.py",
        "frontend/src/HostedPlatform.tsx",
        "frontend/src/App.test.tsx",
    ],
    "local_inference_boundary": [
        "docs/phase6_local_inference_preview.md",
        "scripts/validate_phase6_local_inference_preview.py",
        "tests/test_phase6_local_inference_preview.py",
        "outputs/phase6_local_inference_preview_latest.json",
        "frontend/src/localPreview.ts",
        "frontend/src/localPreview.test.ts",
        "frontend/src/App.test.tsx",
    ],
    "runbook_owners_rollback": [
        "docs/phase6_launch_runbook.md",
        "docs/phase6_launch_readiness_board.yaml",
        "docs/phase6_launch_owner_staffing.yaml",
        "docs/phase6_human_signoff_decisions.yaml",
        "docs/phase6_external_links.yaml",
        "docs/phase6_pre_provider_readiness.md",
        "scripts/validate_phase6_owner_staffing.py",
        "scripts/validate_phase6_external_links.py",
        "scripts/validate_phase6_pre_provider_readiness.py",
        "tests/test_phase6_owner_staffing.py",
        "tests/test_phase6_external_links.py",
        "tests/test_phase6_pre_provider_readiness.py",
        "docs/phase6_human_signoff_packet.md",
    ],
}


def validate_phase6_launch_gate_matrix(matrix_path: str | Path, *, root_dir: str | Path | None = None) -> dict[str, Any]:
    matrix_file = Path(matrix_path)
    root = Path(root_dir) if root_dir is not None else matrix_file.resolve().parents[1]
    matrix = _load_yaml(matrix_file)
    failures: list[dict[str, str]] = []

    if matrix.get("schema_version") != PHASE6_LAUNCH_GATE_MATRIX_VERSION:
        failures.append({"field": "schema_version", "reason": f"expected {PHASE6_LAUNCH_GATE_MATRIX_VERSION}"})
    if str(matrix.get("phase")) != "6":
        failures.append({"field": "phase", "reason": "expected Phase 6 matrix"})
    if not str(matrix.get("matrix_owner") or "").strip():
        failures.append({"field": "matrix_owner", "reason": "matrix owner is required"})
    status_values = set(_sequence(matrix.get("status_values")))
    if status_values != VALID_STATUSES:
        failures.append(
            {
                "field": "status_values",
                "reason": f"status values must be {sorted(VALID_STATUSES)}",
            }
        )

    rows = _sequence(matrix.get("launch_gates"))
    _validate_rows(rows, failures, root=root)
    gate_texts = [str(row.get("packet_text") or "") for row in rows if isinstance(row, dict)]
    observed_gate_ids = [str(row.get("id") or "") for row in rows if isinstance(row, dict)]
    status_by_gate_id = {str(row.get("id") or ""): str(row.get("status") or "") for row in rows if isinstance(row, dict)}
    packet_text_by_gate_id = {str(row.get("id") or ""): str(row.get("packet_text") or "") for row in rows if isinstance(row, dict)}
    evidence_by_gate_id = {
        str(row.get("id") or ""): [str(item) for item in _sequence(row.get("evidence"))]
        for row in rows
        if isinstance(row, dict)
    }
    missing_gate_ids = sorted(set(EXPECTED_LAUNCH_GATE_IDS) - set(observed_gate_ids))
    extra_gate_ids = sorted(set(observed_gate_ids) - set(EXPECTED_LAUNCH_GATE_IDS))
    missing_gates = [gate for gate in EXPECTED_LAUNCH_GATES if gate not in gate_texts]
    extra_gates = sorted(set(gate_texts) - set(EXPECTED_LAUNCH_GATES))
    status_mismatches = {
        gate_id: {"expected": expected_status, "observed": status_by_gate_id.get(gate_id, "")}
        for gate_id, expected_status in EXPECTED_STATUS_BY_GATE_ID.items()
        if status_by_gate_id.get(gate_id) != expected_status
    }
    packet_text_mismatches = {
        gate_id: {"expected": expected_text, "observed": packet_text_by_gate_id.get(gate_id, "")}
        for gate_id, expected_text in EXPECTED_PACKET_TEXT_BY_GATE_ID.items()
        if packet_text_by_gate_id.get(gate_id) != expected_text
    }
    evidence_mismatches = {
        gate_id: {
            "expected": expected_evidence,
            "observed": evidence_by_gate_id.get(gate_id, []),
        }
        for gate_id, expected_evidence in EXPECTED_EVIDENCE_BY_GATE_ID.items()
        if evidence_by_gate_id.get(gate_id) != expected_evidence
    }
    for gate_id in missing_gate_ids:
        failures.append({"field": "launch_gates", "reason": f"missing launch gate id {gate_id}"})
    for gate_id in extra_gate_ids:
        failures.append({"field": "launch_gates", "reason": f"unknown launch gate id {gate_id}"})
    for gate_id, mismatch in status_mismatches.items():
        failures.append({"field": "launch_gates", "reason": f"{gate_id} status {mismatch['observed']} does not match expected {mismatch['expected']}"})
    for gate_id, mismatch in packet_text_mismatches.items():
        failures.append({"field": "launch_gates", "reason": f"{gate_id} packet_text does not match expected {mismatch['expected']}"})
    for gate_id in evidence_mismatches:
        failures.append({"field": "launch_gates", "reason": f"{gate_id} evidence does not match expected launch-gate evidence"})
    for gate in missing_gates:
        failures.append({"field": "launch_gates", "reason": f"missing launch gate {gate}"})
    for gate in extra_gates:
        failures.append({"field": "launch_gates", "reason": f"unknown launch gate {gate}"})

    open_rows = [row for row in rows if isinstance(row, dict) and row.get("status") in OPEN_STATUSES]
    complete_rows = [row for row in rows if isinstance(row, dict) and row.get("status") == "complete"]
    return {
        "schema_version": PHASE6_LAUNCH_GATE_MATRIX_VERSION,
        "matrix_path": str(matrix_file),
        "tracking_gate_passed": not failures,
        "launch_ready": not failures and not open_rows,
        "failure_count": len(failures),
        "failures": failures,
        "launch_gate_count": len(rows),
        "complete_gate_count": len(complete_rows),
        "open_gate_count": len(open_rows),
        "open_gate_ids": [str(row.get("id")) for row in open_rows],
        "expected_gate_ids": list(EXPECTED_LAUNCH_GATE_IDS),
        "observed_gate_ids": observed_gate_ids,
        "missing_gate_ids": missing_gate_ids,
        "extra_gate_ids": extra_gate_ids,
        "expected_status_by_gate_id": EXPECTED_STATUS_BY_GATE_ID,
        "status_by_gate_id": status_by_gate_id,
        "status_mismatches": status_mismatches,
        "expected_packet_text_by_gate_id": EXPECTED_PACKET_TEXT_BY_GATE_ID,
        "packet_text_by_gate_id": packet_text_by_gate_id,
        "packet_text_mismatches": packet_text_mismatches,
        "expected_evidence_by_gate_id": EXPECTED_EVIDENCE_BY_GATE_ID,
        "evidence_by_gate_id": evidence_by_gate_id,
        "evidence_mismatches": evidence_mismatches,
        "gate_inventory_exact": (
            tuple(observed_gate_ids) == EXPECTED_LAUNCH_GATE_IDS
            and not missing_gate_ids
            and not extra_gate_ids
            and not status_mismatches
            and not packet_text_mismatches
            and not evidence_mismatches
        ),
        "missing_launch_gates": missing_gates,
        "extra_launch_gates": extra_gates,
    }


def write_phase6_launch_gate_matrix_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _validate_rows(rows: list[Any], failures: list[dict[str, str]], *, root: Path) -> None:
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        field = f"launch_gates[{index}]"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "row must be an object"})
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            failures.append({"field": field, "reason": "id is required"})
        elif row_id in seen_ids:
            failures.append({"field": field, "reason": f"duplicate id {row_id}"})
        seen_ids.add(row_id)
        if not str(row.get("packet_text") or "").strip():
            failures.append({"field": field, "reason": "packet_text is required"})
        status = str(row.get("status") or "")
        if status not in VALID_STATUSES:
            failures.append({"field": field, "reason": f"invalid status {status}"})
        if not str(row.get("owner_role") or "").strip():
            failures.append({"field": field, "reason": "owner_role is required"})
        if status in OPEN_STATUSES and not str(row.get("next_action") or "").strip():
            failures.append({"field": field, "reason": "open rows require next_action"})
        evidence = _sequence(row.get("evidence"))
        if status == "complete" and not evidence:
            failures.append({"field": field, "reason": "complete rows require evidence"})
        for evidence_index, evidence_path in enumerate(evidence):
            evidence_text = str(evidence_path)
            if not evidence_text.strip():
                failures.append({"field": f"{field}.evidence[{evidence_index}]", "reason": "evidence path is required"})
                continue
            if not (root / evidence_text).exists():
                failures.append(
                    {
                        "field": f"{field}.evidence[{evidence_index}]",
                        "reason": f"evidence path does not exist: {evidence_text}",
                    }
                )


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
