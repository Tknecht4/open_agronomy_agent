from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


PHASE6_READINESS_BOARD_VERSION = "phase6.launch_readiness_board.v1"
VALID_STATUSES = {"complete", "in_progress", "needs_human_signoff", "not_started"}
OPEN_STATUSES = {"in_progress", "needs_human_signoff", "not_started"}
EXPECTED_BLOCKER_IDS = (
    "hidden_scaffolding_leakage",
    "auth_browser_qa",
    "data_export_deletion",
    "thread_reports",
    "core_web_vitals",
    "accessibility_audit",
    "public_claims_review",
    "rate_limits_quotas",
    "incident_runbook_owner",
    "local_inference_boundary",
)
EXPECTED_BLOCKER_STATUS_BY_ID = {
    "hidden_scaffolding_leakage": "needs_human_signoff",
    "auth_browser_qa": "complete",
    "data_export_deletion": "complete",
    "thread_reports": "complete",
    "core_web_vitals": "complete",
    "accessibility_audit": "complete",
    "public_claims_review": "needs_human_signoff",
    "rate_limits_quotas": "complete",
    "incident_runbook_owner": "complete",
    "local_inference_boundary": "complete",
}
EXPECTED_BLOCKER_EVIDENCE_BY_ID = {
    "hidden_scaffolding_leakage": [
        "outputs/phase6_launch_leak_qa_latest.json",
        "scripts/run_phase6_launch_leak_qa.py",
        "tests/test_phase6_launch_qa.py",
        "frontend/src/renderingSecurityAudit.ts",
        "frontend/src/renderingSecurityAudit.test.ts",
        "docs/phase6_rendering_security_qa.md",
        "scripts/build_phase6_human_signoff_packet.py",
        "tests/test_phase6_human_signoff_packet.py",
        "outputs/phase6_human_signoff_packet_latest.json",
        "docs/phase6_human_signoff_packet.md",
        "docs/phase6_human_signoff_decisions.yaml",
        "scripts/validate_phase6_human_signoff_decisions.py",
        "tests/test_phase6_human_signoff_decisions.py",
    ],
    "auth_browser_qa": [
        "scripts/phase6_browser_auth_qa_flow.js",
        "scripts/validate_phase6_account_backlog.py",
        "docs/phase6_account_backlog_readiness.md",
        "outputs/phase6_account_backlog_latest.json",
        "tests/test_phase6_account_export.py",
        "frontend/src/App.test.tsx",
    ],
    "data_export_deletion": [
        "tests/test_phase6_account_export.py",
        "tests/test_phase6_account_backlog.py",
        "scripts/validate_phase6_account_backlog.py",
        "outputs/phase6_account_backlog_latest.json",
        "docs/phase6_pre_demo_launch_status.md",
    ],
    "thread_reports": [
        "tests/test_phase6_reports.py",
        "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_report_manifest_schema.json",
    ],
    "core_web_vitals": [
        "frontend/src/rum.ts",
        "tests/test_phase6_frontend_rum.py",
        "frontend/src/rum.test.ts",
        "scripts/validate_phase6_frontend_performance_budget.py",
        "scripts/validate_phase6_container_launch.py",
        "tests/test_phase6_frontend_performance_budget.py",
        "tests/test_phase6_container_launch.py",
        "docs/phase6_frontend_performance_budget.md",
        "docs/phase6_container_launch_preflight.md",
        "outputs/phase6_frontend_performance_budget_latest.json",
        "outputs/phase6_container_launch_preflight_latest.json",
    ],
    "accessibility_audit": [
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
    "public_claims_review": [
        "frontend/src/PublicDemoPages.tsx",
        "docs/phase6_demo_assets.md",
        "scripts/validate_phase6_demo_assets.py",
        "tests/test_phase6_demo_assets.py",
        "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_public_demo_script.md",
        "docs/phase6_public_claims_review.md",
        "scripts/validate_phase6_public_claims.py",
        "tests/test_phase6_public_claims.py",
        "outputs/phase6_public_claims_review_latest.json",
        "docs/phase6_external_links.yaml",
        "scripts/build_phase6_human_signoff_packet.py",
        "scripts/validate_phase6_external_links.py",
        "tests/test_phase6_human_signoff_packet.py",
        "tests/test_phase6_external_links.py",
        "outputs/phase6_human_signoff_packet_latest.json",
        "docs/phase6_human_signoff_packet.md",
        "docs/phase6_human_signoff_decisions.yaml",
        "scripts/validate_phase6_human_signoff_decisions.py",
        "tests/test_phase6_human_signoff_decisions.py",
    ],
    "rate_limits_quotas": [
        "docs/phase6_rate_limits_quotas.md",
        "scripts/validate_phase6_rate_limits_quotas.py",
        "tests/test_phase6_rate_limits_quotas.py",
        "tests/test_rate_limit.py",
        "tests/test_phase4_hosted_api.py",
    ],
    "incident_runbook_owner": [
        "docs/phase6_launch_runbook.md",
        "docs/phase6_launch_owner_staffing.yaml",
        "scripts/validate_phase6_owner_staffing.py",
        "tests/test_phase6_owner_staffing.py",
    ],
    "local_inference_boundary": [
        "frontend/src/localPreview.ts",
        "frontend/src/localPreview.test.ts",
        "frontend/src/App.test.tsx",
        "docs/phase6_local_inference_preview.md",
    ],
}
EXPECTED_DEMO_ASSET_IDS = (
    "landing_page",
    "known_limitations_page",
    "data_source_coverage_page",
    "sample_field_contexts",
    "example_prompt_library",
    "sample_reports",
    "demo_script",
    "privacy_data_use_page",
    "support_feedback_page",
)
EXPECTED_DEMO_ASSET_STATUS_BY_ID = {asset_id: "complete" for asset_id in EXPECTED_DEMO_ASSET_IDS}
EXPECTED_ROLLBACK_ACTION_IDS = (
    "disable_signup",
    "disable_model_generation",
    "disable_local_preview",
    "disable_exports",
    "source_takedown",
)


def validate_phase6_readiness_board(
    board_path: str | Path,
    checklist_path: str | Path,
    *,
    root_dir: str | Path | None = None,
) -> dict[str, Any]:
    board_file = Path(board_path)
    checklist_file = Path(checklist_path)
    root = Path(root_dir) if root_dir is not None else _infer_root(board_file, checklist_file)
    board = _load_yaml(board_file)
    checklist = _load_yaml(checklist_file)
    failures: list[dict[str, str]] = []

    if board.get("schema_version") != PHASE6_READINESS_BOARD_VERSION:
        failures.append(
            {
                "field": "schema_version",
                "reason": f"expected {PHASE6_READINESS_BOARD_VERSION}",
            }
        )
    if str(board.get("phase")) != str(checklist.get("phase")):
        failures.append({"field": "phase", "reason": "board phase does not match packet checklist"})
    if not str(board.get("board_owner") or "").strip():
        failures.append({"field": "board_owner", "reason": "board owner is required"})

    checklist_launch_modes = set(_sequence(checklist.get("launch_modes")))
    board_launch_modes = set(_sequence(board.get("launch_modes")))
    launch_modes_missing = sorted(checklist_launch_modes - board_launch_modes)
    launch_modes_extra = sorted(board_launch_modes - checklist_launch_modes)
    for mode in launch_modes_missing:
        failures.append({"field": "launch_modes", "reason": f"missing launch mode {mode}"})
    for mode in launch_modes_extra:
        failures.append({"field": "launch_modes", "reason": f"unknown launch mode {mode}"})
    board_status_values = set(_sequence(board.get("status_values")))
    if board_status_values != VALID_STATUSES:
        failures.append(
            {
                "field": "status_values",
                "reason": f"status values must be {sorted(VALID_STATUSES)}",
            }
        )

    blocker_rows = _sequence(board.get("blockers"))
    asset_rows = _sequence(board.get("must_have_demo_assets"))
    rollback_rows = _mapping(board.get("rollback_plan"))

    _validate_rows("blockers", blocker_rows, failures, require_next_action=True, root=root)
    _validate_rows("must_have_demo_assets", asset_rows, failures, require_next_action=True, root=root)
    _validate_rollback_rows(rollback_rows, failures, root=root)

    blocker_packet_text = {str(row.get("packet_text")) for row in blocker_rows}
    asset_packet_text = {str(row.get("packet_text")) for row in asset_rows}
    rollback_keys = set(rollback_rows)
    observed_blocker_ids = [str(row.get("id") or "") for row in blocker_rows if isinstance(row, dict)]
    observed_demo_asset_ids = [str(row.get("id") or "") for row in asset_rows if isinstance(row, dict)]
    observed_rollback_action_ids = list(rollback_rows)
    blocker_status_by_id = {str(row.get("id") or ""): str(row.get("status") or "") for row in blocker_rows if isinstance(row, dict)}
    blocker_evidence_by_id = {
        str(row.get("id") or ""): [str(item) for item in _sequence(row.get("evidence"))]
        for row in blocker_rows
        if isinstance(row, dict)
    }
    demo_asset_status_by_id = {str(row.get("id") or ""): str(row.get("status") or "") for row in asset_rows if isinstance(row, dict)}

    missing_blockers = sorted(set(checklist.get("blockers") or []) - blocker_packet_text)
    missing_assets = sorted(set(checklist.get("must_have_demo_assets") or []) - asset_packet_text)
    missing_rollbacks = sorted(set(_mapping(checklist.get("rollback_plan"))) - rollback_keys)
    extra_blockers = sorted(blocker_packet_text - set(checklist.get("blockers") or []))
    extra_assets = sorted(asset_packet_text - set(checklist.get("must_have_demo_assets") or []))
    extra_rollbacks = sorted(rollback_keys - set(_mapping(checklist.get("rollback_plan"))))
    missing_blocker_ids = sorted(set(EXPECTED_BLOCKER_IDS) - set(observed_blocker_ids))
    extra_blocker_ids = sorted(set(observed_blocker_ids) - set(EXPECTED_BLOCKER_IDS))
    missing_demo_asset_ids = sorted(set(EXPECTED_DEMO_ASSET_IDS) - set(observed_demo_asset_ids))
    extra_demo_asset_ids = sorted(set(observed_demo_asset_ids) - set(EXPECTED_DEMO_ASSET_IDS))
    missing_rollback_action_ids = sorted(set(EXPECTED_ROLLBACK_ACTION_IDS) - set(observed_rollback_action_ids))
    extra_rollback_action_ids = sorted(set(observed_rollback_action_ids) - set(EXPECTED_ROLLBACK_ACTION_IDS))
    blocker_status_mismatches = {
        blocker_id: {"expected": expected_status, "observed": blocker_status_by_id.get(blocker_id, "")}
        for blocker_id, expected_status in EXPECTED_BLOCKER_STATUS_BY_ID.items()
        if blocker_status_by_id.get(blocker_id) != expected_status
    }
    demo_asset_status_mismatches = {
        asset_id: {"expected": expected_status, "observed": demo_asset_status_by_id.get(asset_id, "")}
        for asset_id, expected_status in EXPECTED_DEMO_ASSET_STATUS_BY_ID.items()
        if demo_asset_status_by_id.get(asset_id) != expected_status
    }
    blocker_evidence_mismatches = {
        blocker_id: {"expected": expected_evidence, "observed": blocker_evidence_by_id.get(blocker_id, [])}
        for blocker_id, expected_evidence in EXPECTED_BLOCKER_EVIDENCE_BY_ID.items()
        if blocker_evidence_by_id.get(blocker_id) != expected_evidence
    }

    for text in missing_blockers:
        failures.append({"field": "blockers", "reason": f"missing packet blocker {text}"})
    for text in missing_assets:
        failures.append({"field": "must_have_demo_assets", "reason": f"missing packet demo asset {text}"})
    for key in missing_rollbacks:
        failures.append({"field": "rollback_plan", "reason": f"missing rollback action {key}"})
    for text in extra_blockers:
        failures.append({"field": "blockers", "reason": f"unknown blocker {text}"})
    for text in extra_assets:
        failures.append({"field": "must_have_demo_assets", "reason": f"unknown demo asset {text}"})
    for key in extra_rollbacks:
        failures.append({"field": "rollback_plan", "reason": f"unknown rollback action {key}"})
    for blocker_id in missing_blocker_ids:
        failures.append({"field": "blockers", "reason": f"missing blocker id {blocker_id}"})
    for blocker_id in extra_blocker_ids:
        failures.append({"field": "blockers", "reason": f"unknown blocker id {blocker_id}"})
    for asset_id in missing_demo_asset_ids:
        failures.append({"field": "must_have_demo_assets", "reason": f"missing demo asset id {asset_id}"})
    for asset_id in extra_demo_asset_ids:
        failures.append({"field": "must_have_demo_assets", "reason": f"unknown demo asset id {asset_id}"})
    for action_id in missing_rollback_action_ids:
        failures.append({"field": "rollback_plan", "reason": f"missing rollback action id {action_id}"})
    for action_id in extra_rollback_action_ids:
        failures.append({"field": "rollback_plan", "reason": f"unknown rollback action id {action_id}"})
    for blocker_id, mismatch in blocker_status_mismatches.items():
        failures.append({"field": "blockers", "reason": f"{blocker_id} status {mismatch['observed']} does not match expected {mismatch['expected']}"})
    for asset_id, mismatch in demo_asset_status_mismatches.items():
        failures.append({"field": "must_have_demo_assets", "reason": f"{asset_id} status {mismatch['observed']} does not match expected {mismatch['expected']}"})
    for blocker_id in blocker_evidence_mismatches:
        failures.append({"field": "blockers", "reason": f"{blocker_id} evidence does not match expected readiness evidence"})

    open_blockers = [row for row in blocker_rows if row.get("status") in OPEN_STATUSES]
    open_assets = [row for row in asset_rows if row.get("status") in OPEN_STATUSES]
    complete_blockers = [row for row in blocker_rows if row.get("status") == "complete"]

    return {
        "schema_version": PHASE6_READINESS_BOARD_VERSION,
        "board_path": str(board_file),
        "checklist_path": str(checklist_file),
        "tracking_gate_passed": not failures,
        "launch_ready": not failures and not open_blockers and not open_assets,
        "failure_count": len(failures),
        "failures": failures,
        "blocker_count": len(blocker_rows),
        "complete_blocker_count": len(complete_blockers),
        "open_blocker_count": len(open_blockers),
        "open_blocker_ids": [str(row.get("id")) for row in open_blockers],
        "expected_blocker_ids": list(EXPECTED_BLOCKER_IDS),
        "observed_blocker_ids": observed_blocker_ids,
        "missing_blocker_ids": missing_blocker_ids,
        "extra_blocker_ids": extra_blocker_ids,
        "expected_blocker_status_by_id": EXPECTED_BLOCKER_STATUS_BY_ID,
        "blocker_status_by_id": blocker_status_by_id,
        "blocker_status_mismatches": blocker_status_mismatches,
        "expected_blocker_evidence_by_id": EXPECTED_BLOCKER_EVIDENCE_BY_ID,
        "blocker_evidence_by_id": blocker_evidence_by_id,
        "blocker_evidence_mismatches": blocker_evidence_mismatches,
        "demo_asset_count": len(asset_rows),
        "open_demo_asset_count": len(open_assets),
        "open_demo_asset_ids": [str(row.get("id")) for row in open_assets],
        "expected_demo_asset_ids": list(EXPECTED_DEMO_ASSET_IDS),
        "observed_demo_asset_ids": observed_demo_asset_ids,
        "missing_demo_asset_ids": missing_demo_asset_ids,
        "extra_demo_asset_ids": extra_demo_asset_ids,
        "expected_demo_asset_status_by_id": EXPECTED_DEMO_ASSET_STATUS_BY_ID,
        "demo_asset_status_by_id": demo_asset_status_by_id,
        "demo_asset_status_mismatches": demo_asset_status_mismatches,
        "rollback_action_count": len(rollback_rows),
        "expected_rollback_action_ids": list(EXPECTED_ROLLBACK_ACTION_IDS),
        "observed_rollback_action_ids": observed_rollback_action_ids,
        "missing_rollback_action_ids": missing_rollback_action_ids,
        "extra_rollback_action_ids": extra_rollback_action_ids,
        "board_inventory_exact": (
            tuple(observed_blocker_ids) == EXPECTED_BLOCKER_IDS
            and tuple(observed_demo_asset_ids) == EXPECTED_DEMO_ASSET_IDS
            and tuple(observed_rollback_action_ids) == EXPECTED_ROLLBACK_ACTION_IDS
            and not missing_blocker_ids
            and not extra_blocker_ids
            and not missing_demo_asset_ids
            and not extra_demo_asset_ids
            and not missing_rollback_action_ids
            and not extra_rollback_action_ids
            and not blocker_status_mismatches
            and not blocker_evidence_mismatches
            and not demo_asset_status_mismatches
        ),
        "missing_packet_blockers": missing_blockers,
        "missing_packet_demo_assets": missing_assets,
        "missing_packet_rollback_actions": missing_rollbacks,
        "missing_launch_modes": launch_modes_missing,
        "extra_launch_modes": launch_modes_extra,
    }


def write_phase6_readiness_board_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _validate_rows(prefix: str, rows: list[dict[str, Any]], failures: list[dict[str, str]], *, require_next_action: bool, root: Path) -> None:
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        field = f"{prefix}[{index}]"
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
        if prefix == "blockers" and not str(row.get("escalation_owner") or "").strip():
            failures.append({"field": field, "reason": "escalation_owner is required for blockers"})
        evidence = row.get("evidence")
        if status == "complete" and not _sequence(evidence):
            failures.append({"field": field, "reason": "complete rows require evidence"})
        _validate_evidence_paths(field, _sequence(evidence), failures, root=root)
        if require_next_action and not str(row.get("next_action") or "").strip():
            failures.append({"field": field, "reason": "next_action is required"})


def _validate_rollback_rows(rows: dict[str, Any], failures: list[dict[str, str]], *, root: Path) -> None:
    for key, row in rows.items():
        field = f"rollback_plan.{key}"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "rollback action must be an object"})
            continue
        if not str(row.get("owner_role") or "").strip():
            failures.append({"field": field, "reason": "owner_role is required"})
        if not str(row.get("runbook_section") or "").strip():
            failures.append({"field": field, "reason": "runbook_section is required"})
        if not _sequence(row.get("evidence")):
            failures.append({"field": field, "reason": "evidence is required"})
        _validate_evidence_paths(field, _sequence(row.get("evidence")), failures, root=root)


def _validate_evidence_paths(field: str, evidence: list[Any], failures: list[dict[str, str]], *, root: Path) -> None:
    for evidence_index, evidence_path in enumerate(evidence):
        evidence_text = str(evidence_path or "").strip()
        evidence_field = f"{field}.evidence[{evidence_index}]"
        if not evidence_text:
            failures.append({"field": evidence_field, "reason": "evidence path is required"})
        elif not (root / evidence_text).exists():
            failures.append({"field": evidence_field, "reason": f"evidence path does not exist: {evidence_text}"})


def _infer_root(board_file: Path, checklist_file: Path) -> Path:
    for candidate in (
        board_file.resolve().parent.parent,
        checklist_file.resolve().parent.parent.parent,
    ):
        if (candidate / "docs").exists() and (candidate / "plans").exists():
            return candidate
    return board_file.resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
