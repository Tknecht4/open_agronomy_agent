from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


PHASE6_HUMAN_SIGNOFF_DECISIONS_VERSION = "phase6.human_signoff_decisions.v1"
VALID_STATUSES = {
    "pending_review",
    "pending_provider_target",
    "pending_provider_staffing",
    "pending_manual_review",
    "approved",
    "blocked",
}
VALID_ITEM_TYPES = {"human_signoff", "launch_rehearsal"}
EXPECTED_HUMAN_SIGNOFF_IDS = {
    "hidden_scaffolding_leakage",
    "public_claims_review",
    "named_owner_replacement",
}
EXPECTED_REHEARSAL_IDS = {
    "field_context_readiness_rehearsal",
    "final_host_lighthouse_lab",
    "real_device_mobile_review",
    "local_inference_research_signoff",
    "external_links_and_owner_replacement",
}
EXPECTED_DECISION_IDS = EXPECTED_HUMAN_SIGNOFF_IDS | EXPECTED_REHEARSAL_IDS
EXPECTED_OWNER_ROLE_BY_DECISION = {
    "hidden_scaffolding_leakage": "tech_lead",
    "public_claims_review": "product_science_lead",
    "named_owner_replacement": "tech_lead",
    "field_context_readiness_rehearsal": "frontend_lead",
    "final_host_lighthouse_lab": "frontend_lead",
    "real_device_mobile_review": "frontend_lead",
    "local_inference_research_signoff": "research_engineer",
    "external_links_and_owner_replacement": "product_owner",
}
EXPECTED_PRE_PROVIDER_STATUS_BY_DECISION = {
    "hidden_scaffolding_leakage": "pending_review",
    "public_claims_review": "pending_review",
    "named_owner_replacement": "pending_provider_staffing",
    "field_context_readiness_rehearsal": "pending_manual_review",
    "final_host_lighthouse_lab": "pending_provider_target",
    "real_device_mobile_review": "pending_manual_review",
    "local_inference_research_signoff": "pending_manual_review",
    "external_links_and_owner_replacement": "pending_provider_staffing",
}
EXPECTED_ITEM_TYPE_BY_DECISION = {
    **{item_id: "human_signoff" for item_id in EXPECTED_HUMAN_SIGNOFF_IDS},
    **{item_id: "launch_rehearsal" for item_id in EXPECTED_REHEARSAL_IDS},
}
REQUIRED_EVIDENCE_BY_DECISION = {
    "hidden_scaffolding_leakage": {
        "outputs/phase6_launch_leak_qa_latest.json",
        "scripts/run_phase6_launch_leak_qa.py",
        "tests/test_phase6_launch_qa.py",
        "docs/phase6_human_signoff_packet.md",
    },
    "public_claims_review": {
        "outputs/phase6_public_claims_review_latest.json",
        "docs/phase6_public_claims_review.md",
        "frontend/src/PublicDemoPages.tsx",
        "tests/test_phase6_public_claims.py",
        "docs/phase6_sample_reports",
        "docs/phase6_data_source_coverage",
        "docs/phase6_external_links.yaml",
    },
    "named_owner_replacement": {
        "docs/phase6_launch_owner_staffing.yaml",
        "docs/phase6_launch_runbook.md",
        "scripts/validate_phase6_owner_staffing.py",
        "tests/test_phase6_owner_staffing.py",
    },
    "field_context_readiness_rehearsal": {
        "outputs/phase6_field_context_rehearsal_latest.json",
        "scripts/validate_phase6_field_context_rehearsal.py",
        "scripts/phase6_browser_field_context_rehearsal.js",
        "frontend/src/fieldContextReadiness.ts",
        "frontend/src/fieldContextReadiness.test.ts",
        "docs/phase6_field_context_readiness_ux.md",
    },
    "final_host_lighthouse_lab": {
        "docs/phase6_frontend_performance_budget.md",
        "docs/phase6_container_launch_preflight.md",
        "outputs/phase6_frontend_performance_budget_latest.json",
        "outputs/phase6_final_host_performance_review_latest.json",
        "scripts/validate_phase6_frontend_performance_budget.py",
        "scripts/validate_phase6_final_host_performance_review.py",
        "scripts/run_phase6_browser_performance_lab.py",
        "scripts/phase6_browser_performance_lab.js",
    },
    "real_device_mobile_review": {
        "docs/phase6_responsive_mobile_qa.md",
        "frontend/src/responsiveAudit.ts",
        "frontend/src/responsiveAudit.test.ts",
        "outputs/phase6_responsive_mobile_qa_latest.json",
        "scripts/validate_phase6_responsive_mobile_qa.py",
        "scripts/phase6_browser_responsive_qa_flow.js",
    },
    "local_inference_research_signoff": {
        "docs/phase6_local_inference_preview.md",
        "frontend/src/localPreview.ts",
        "frontend/src/localPreview.test.ts",
    },
    "external_links_and_owner_replacement": {
        "docs/phase6_launch_readiness_board.yaml",
        "docs/phase6_launch_runbook.md",
        "docs/phase6_external_links.yaml",
        "scripts/validate_phase6_external_links.py",
        "frontend/src/PublicDemoPages.tsx",
    },
}
REVIEWED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?$")


def validate_phase6_human_signoff_decisions(decisions_path: str | Path, *, root_dir: str | Path | None = None) -> dict[str, Any]:
    decisions_file = Path(decisions_path)
    root = Path(root_dir) if root_dir is not None else decisions_file.resolve().parents[1]
    payload = _load_yaml(decisions_file)
    failures: list[dict[str, str]] = []

    if payload.get("schema_version") != PHASE6_HUMAN_SIGNOFF_DECISIONS_VERSION:
        failures.append({"field": "schema_version", "reason": f"expected {PHASE6_HUMAN_SIGNOFF_DECISIONS_VERSION}"})
    if str(payload.get("phase")) != "6":
        failures.append({"field": "phase", "reason": "expected Phase 6 signoff decisions"})
    if set(payload.get("status_values") or []) != VALID_STATUSES:
        failures.append({"field": "status_values", "reason": "status values must match validator contract"})

    rows = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
    seen: set[str] = set()
    pending_ids: list[str] = []
    blocked_ids: list[str] = []
    approved_ids: list[str] = []
    status_by_decision_id: dict[str, str] = {}
    item_type_by_decision_id: dict[str, str] = {}
    owner_role_by_decision_id: dict[str, str] = {}
    for index, row in enumerate(rows):
        field = f"decisions[{index}]"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "decision row must be an object"})
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            failures.append({"field": field, "reason": "item_id is required"})
        elif item_id in seen:
            failures.append({"field": field, "reason": f"duplicate item_id {item_id}"})
        seen.add(item_id)
        item_type = str(row.get("item_type") or "").strip()
        if item_id:
            item_type_by_decision_id[item_id] = item_type
        if item_type not in VALID_ITEM_TYPES:
            failures.append({"field": field, "reason": f"invalid item_type {item_type}"})
        if item_id in EXPECTED_HUMAN_SIGNOFF_IDS and item_type != "human_signoff":
            failures.append({"field": field, "reason": f"{item_id} must be a human_signoff item"})
        if item_id in EXPECTED_REHEARSAL_IDS and item_type != "launch_rehearsal":
            failures.append({"field": field, "reason": f"{item_id} must be a launch_rehearsal item"})
        owner_role = str(row.get("owner_role") or "").strip()
        if item_id:
            owner_role_by_decision_id[item_id] = owner_role
        if not owner_role:
            failures.append({"field": field, "reason": "owner_role is required"})
        elif item_id in EXPECTED_OWNER_ROLE_BY_DECISION and owner_role != EXPECTED_OWNER_ROLE_BY_DECISION[item_id]:
            failures.append({"field": field, "reason": f"{item_id} owner_role must be {EXPECTED_OWNER_ROLE_BY_DECISION[item_id]}"})
        required_before = str(row.get("required_before") or "").strip()
        if not required_before:
            failures.append({"field": field, "reason": "required_before is required"})
        elif required_before != "external_launch":
            failures.append({"field": field, "reason": "required_before must be external_launch"})
        status = str(row.get("status") or "").strip()
        if item_id:
            status_by_decision_id[item_id] = status
        if status not in VALID_STATUSES:
            failures.append({"field": field, "reason": f"invalid status {status}"})
        elif status == "approved":
            approved_ids.append(item_id)
            _validate_approval_fields(row, field, failures)
        elif status == "blocked":
            blocked_ids.append(item_id)
            _validate_terminal_decision_fields(row, field, failures, status="blocked")
        else:
            pending_ids.append(item_id)
        evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        if not evidence:
            failures.append({"field": field, "reason": "evidence is required"})
        evidence_paths = {str(value or "").strip() for value in evidence}
        for required_evidence in sorted(REQUIRED_EVIDENCE_BY_DECISION.get(item_id, set()) - evidence_paths):
            failures.append({"field": field, "reason": f"missing required evidence: {required_evidence}"})
        for evidence_index, value in enumerate(evidence):
            evidence_path = str(value or "").strip()
            if not evidence_path:
                failures.append({"field": f"{field}.evidence[{evidence_index}]", "reason": "evidence path is required"})
            elif not (root / evidence_path).exists():
                failures.append({"field": f"{field}.evidence[{evidence_index}]", "reason": f"evidence path does not exist: {evidence_path}"})

    missing = sorted(EXPECTED_DECISION_IDS - seen)
    extra = sorted(seen - EXPECTED_DECISION_IDS)
    for item_id in missing:
        failures.append({"field": "decisions", "reason": f"missing signoff decision {item_id}"})
    for item_id in extra:
        failures.append({"field": "decisions", "reason": f"unknown signoff decision {item_id}"})

    status_mismatches = _mismatches(EXPECTED_PRE_PROVIDER_STATUS_BY_DECISION, status_by_decision_id)
    item_type_mismatches = _mismatches(EXPECTED_ITEM_TYPE_BY_DECISION, item_type_by_decision_id)
    owner_role_mismatches = _mismatches(EXPECTED_OWNER_ROLE_BY_DECISION, owner_role_by_decision_id)
    exact_pre_provider_inventory = (
        not missing
        and not extra
        and not status_mismatches
        and not item_type_mismatches
        and not owner_role_mismatches
    )

    external_flag = bool(payload.get("external_launch_signoff_complete"))
    all_approved = not missing and not extra and len(approved_ids) == len(EXPECTED_DECISION_IDS)
    launch_signoff_complete = not failures and external_flag and all_approved
    if external_flag and not all_approved:
        failures.append({"field": "external_launch_signoff_complete", "reason": "cannot be true until every decision is approved"})

    return {
        "schema_version": PHASE6_HUMAN_SIGNOFF_DECISIONS_VERSION,
        "decisions_path": str(decisions_file),
        "tracking_gate_passed": not failures,
        "launch_signoff_complete": launch_signoff_complete,
        "external_launch_signoff_complete": external_flag,
        "failure_count": len(failures),
        "failures": failures,
        "decision_count": len(rows),
        "approved_count": len(approved_ids),
        "pending_count": len(pending_ids),
        "blocked_count": len(blocked_ids),
        "approved_ids": approved_ids,
        "pending_ids": pending_ids,
        "blocked_ids": blocked_ids,
        "expected_decision_ids": sorted(EXPECTED_DECISION_IDS),
        "observed_decision_ids": sorted(item_id for item_id in seen if item_id),
        "missing_decision_ids": missing,
        "extra_decision_ids": extra,
        "expected_pre_provider_status_by_decision_id": EXPECTED_PRE_PROVIDER_STATUS_BY_DECISION,
        "status_by_decision_id": status_by_decision_id,
        "status_mismatches": status_mismatches,
        "expected_item_type_by_decision_id": EXPECTED_ITEM_TYPE_BY_DECISION,
        "item_type_by_decision_id": item_type_by_decision_id,
        "item_type_mismatches": item_type_mismatches,
        "expected_owner_role_by_decision_id": EXPECTED_OWNER_ROLE_BY_DECISION,
        "owner_role_by_decision_id": owner_role_by_decision_id,
        "owner_role_mismatches": owner_role_mismatches,
        "pre_provider_decision_inventory_exact": exact_pre_provider_inventory,
    }


def write_phase6_human_signoff_decisions_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _validate_approval_fields(row: dict[str, Any], field: str, failures: list[dict[str, str]]) -> None:
    _validate_terminal_decision_fields(row, field, failures, status="approved")


def _validate_terminal_decision_fields(
    row: dict[str, Any],
    field: str,
    failures: list[dict[str, str]],
    *,
    status: str,
) -> None:
    for key in ("reviewer_name", "decision_summary"):
        if not str(row.get(key) or "").strip():
            failures.append({"field": field, "reason": f"{status} decisions require {key}"})
    reviewed_at = str(row.get("reviewed_at") or "").strip()
    if not reviewed_at:
        failures.append({"field": field, "reason": f"{status} decisions require reviewed_at"})
    elif REVIEWED_AT_RE.match(reviewed_at) is None:
        failures.append({"field": field, "reason": "reviewed_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ"})


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _mismatches(expected: dict[str, str], observed: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        item_id: {"expected": expected_value, "observed": observed_value}
        for item_id, expected_value in sorted(expected.items())
        if (observed_value := observed.get(item_id)) is not None and observed_value != expected_value
    }
