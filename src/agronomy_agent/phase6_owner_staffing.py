from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


PHASE6_OWNER_STAFFING_VERSION = "phase6.launch_owner_staffing.v1"
VALID_STATUSES = {"role_placeholder", "named_pending", "named_ready"}
EXPECTED_ROLES = {
    "tech_lead",
    "security_owner",
    "backend_lead",
    "ops_lead",
    "frontend_lead",
    "full_stack_lead",
    "product_science_lead",
    "privacy_owner",
    "research_engineer",
    "product_owner",
}
EXPECTED_ROLLBACK_ACTIONS = {
    "disable_signup",
    "disable_model_generation",
    "disable_local_preview",
    "disable_exports",
    "source_takedown",
}
EXPECTED_SIGNOFF_DEPENDENCIES = {
    "named_owner_replacement",
    "final_host_lighthouse_lab",
    "real_device_mobile_review",
}
EXPECTED_ROLE_STATUS_BY_ID = {role_id: "role_placeholder" for role_id in EXPECTED_ROLES}
EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION = {
    "disable_signup": "security_owner",
    "disable_model_generation": "ops_lead",
    "disable_local_preview": "research_engineer",
    "disable_exports": "full_stack_lead",
    "source_takedown": "product_science_lead",
}
EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION = {
    "disable_signup": "tech_lead",
    "disable_model_generation": "product_science_lead",
    "disable_local_preview": "product_science_lead",
    "disable_exports": "ops_lead",
    "source_takedown": "privacy_owner",
}
EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY = {
    "named_owner_replacement": "tech_lead",
    "final_host_lighthouse_lab": "frontend_lead",
    "real_device_mobile_review": "frontend_lead",
}
EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY = {
    "named_owner_replacement": "pending_provider_staffing",
    "final_host_lighthouse_lab": "pending_provider_target",
    "real_device_mobile_review": "pending_manual_review",
}


def validate_phase6_owner_staffing(
    staffing_path: str | Path,
    *,
    checklist_path: str | Path | None = None,
    readiness_board_path: str | Path | None = None,
    launch_gate_matrix_path: str | Path | None = None,
    runbook_path: str | Path | None = None,
    root_dir: str | Path | None = None,
) -> dict[str, Any]:
    staffing_file = Path(staffing_path)
    root = Path(root_dir) if root_dir is not None else staffing_file.resolve().parents[1]
    staffing = _load_yaml(staffing_file)
    failures: list[dict[str, str]] = []

    if staffing.get("schema_version") != PHASE6_OWNER_STAFFING_VERSION:
        failures.append({"field": "schema_version", "reason": f"expected {PHASE6_OWNER_STAFFING_VERSION}"})
    if str(staffing.get("phase")) != "6":
        failures.append({"field": "phase", "reason": "expected Phase 6 owner staffing"})
    if not str(staffing.get("provider_target") or "").strip():
        failures.append({"field": "provider_target", "reason": "provider target status is required"})

    roles = _sequence(staffing.get("roles"))
    role_ids = _validate_roles(roles, failures)
    rollback_actions = _mapping(staffing.get("rollback_actions"))
    signoff_dependencies = _sequence(staffing.get("signoff_dependencies"))
    checklist = _load_optional_yaml(_resolve(root, checklist_path)) if checklist_path is not None else {}
    readiness_board = _load_optional_yaml(_resolve(root, readiness_board_path)) if readiness_board_path is not None else {}
    launch_gate_matrix = _load_optional_yaml(_resolve(root, launch_gate_matrix_path)) if launch_gate_matrix_path is not None else {}
    runbook_text = _load_optional_text(_resolve(root, runbook_path)) if runbook_path is not None else ""
    _validate_rollback_actions(rollback_actions, role_ids, failures, checklist=checklist, runbook_text=runbook_text)
    _validate_signoff_dependencies(signoff_dependencies, role_ids, failures, root=root, runbook_text=runbook_text)
    surface_role_ids = _referenced_launch_surface_roles(readiness_board, launch_gate_matrix, runbook_text)
    missing_surface_roles = sorted(surface_role_ids - role_ids)
    for role_id in missing_surface_roles:
        failures.append({"field": "roles", "reason": f"launch surface references unstaffed role {role_id}"})

    missing_roles = sorted(EXPECTED_ROLES - role_ids)
    extra_roles = sorted(role_ids - EXPECTED_ROLES)
    rollback_action_ids = {str(action) for action in rollback_actions}
    signoff_dependency_ids = {str(item.get("item_id") or "") for item in signoff_dependencies if isinstance(item, dict)}
    missing_rollbacks = sorted(EXPECTED_ROLLBACK_ACTIONS - rollback_action_ids)
    extra_rollbacks = sorted(rollback_action_ids - EXPECTED_ROLLBACK_ACTIONS)
    missing_signoffs = sorted(EXPECTED_SIGNOFF_DEPENDENCIES - signoff_dependency_ids)
    extra_signoffs = sorted(signoff_dependency_ids - EXPECTED_SIGNOFF_DEPENDENCIES)
    role_status_by_id = _role_status_by_id(roles)
    rollback_owner_role_by_action = _rollback_field_by_action(rollback_actions, "owner_role")
    rollback_backup_role_by_action = _rollback_field_by_action(rollback_actions, "backup_role")
    signoff_owner_role_by_dependency = _signoff_field_by_dependency(signoff_dependencies, "owner_role")
    signoff_status_by_dependency = _signoff_field_by_dependency(signoff_dependencies, "status")
    role_status_mismatches = _mismatches(EXPECTED_ROLE_STATUS_BY_ID, role_status_by_id)
    rollback_owner_role_mismatches = _mismatches(EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION, rollback_owner_role_by_action)
    rollback_backup_role_mismatches = _mismatches(EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION, rollback_backup_role_by_action)
    signoff_owner_role_mismatches = _mismatches(EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY, signoff_owner_role_by_dependency)
    signoff_status_mismatches = _mismatches(EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY, signoff_status_by_dependency)
    for role_id in missing_roles:
        failures.append({"field": "roles", "reason": f"missing launch role {role_id}"})
    for role_id in extra_roles:
        failures.append({"field": "roles", "reason": f"unknown launch role {role_id}"})
    for action in missing_rollbacks:
        failures.append({"field": "rollback_actions", "reason": f"missing rollback staffing action {action}"})
    for action in extra_rollbacks:
        failures.append({"field": "rollback_actions", "reason": f"unknown rollback staffing action {action}"})
    for item_id in missing_signoffs:
        failures.append({"field": "signoff_dependencies", "reason": f"missing signoff dependency {item_id}"})
    for item_id in extra_signoffs:
        failures.append({"field": "signoff_dependencies", "reason": f"unknown signoff dependency {item_id}"})

    open_roles = [
        role
        for role in roles
        if isinstance(role, dict)
        and (
            str(role.get("status") or "") != "named_ready"
            or not str(role.get("named_owner") or "").strip()
            or not str(role.get("backup_owner") or "").strip()
            or not str(role.get("contact_channel") or "").strip()
        )
    ]
    open_signoffs = [
        item
        for item in signoff_dependencies
        if isinstance(item, dict) and str(item.get("status") or "") != "complete"
    ]
    return {
        "schema_version": PHASE6_OWNER_STAFFING_VERSION,
        "staffing_path": str(staffing_file),
        "tracking_gate_passed": not failures,
        "staffing_ready": not failures and not open_roles and not open_signoffs and bool(staffing.get("external_launch_ready")),
        "external_launch_ready": bool(staffing.get("external_launch_ready")),
        "failure_count": len(failures),
        "failures": failures,
        "role_count": len(roles),
        "expected_role_ids": sorted(EXPECTED_ROLES),
        "observed_role_ids": sorted(role_ids),
        "role_ids": sorted(role_ids),
        "expected_role_status_by_id": EXPECTED_ROLE_STATUS_BY_ID,
        "role_status_by_id": role_status_by_id,
        "role_status_mismatches": role_status_mismatches,
        "role_inventory_exact": not missing_roles and not extra_roles and not role_status_mismatches,
        "open_role_count": len(open_roles),
        "open_role_ids": [str(role.get("role_id")) for role in open_roles],
        "placeholder_role_ids": [str(role.get("role_id")) for role in open_roles if str(role.get("status") or "") == "role_placeholder"],
        "launch_surface_role_ids": sorted(surface_role_ids),
        "missing_launch_surface_roles": missing_surface_roles,
        "rollback_action_count": len(rollback_actions),
        "expected_rollback_action_ids": sorted(EXPECTED_ROLLBACK_ACTIONS),
        "observed_rollback_action_ids": sorted(rollback_action_ids),
        "rollback_action_ids": sorted(rollback_action_ids),
        "expected_rollback_owner_role_by_action": EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION,
        "rollback_owner_role_by_action": rollback_owner_role_by_action,
        "rollback_owner_role_mismatches": rollback_owner_role_mismatches,
        "expected_rollback_backup_role_by_action": EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION,
        "rollback_backup_role_by_action": rollback_backup_role_by_action,
        "rollback_backup_role_mismatches": rollback_backup_role_mismatches,
        "rollback_inventory_exact": not missing_rollbacks
        and not extra_rollbacks
        and not rollback_owner_role_mismatches
        and not rollback_backup_role_mismatches,
        "signoff_dependency_count": len(signoff_dependencies),
        "expected_signoff_dependency_ids": sorted(EXPECTED_SIGNOFF_DEPENDENCIES),
        "observed_signoff_dependency_ids": sorted(signoff_dependency_ids),
        "signoff_dependency_ids": sorted(signoff_dependency_ids),
        "expected_signoff_owner_role_by_dependency": EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY,
        "signoff_owner_role_by_dependency": signoff_owner_role_by_dependency,
        "signoff_owner_role_mismatches": signoff_owner_role_mismatches,
        "expected_signoff_status_by_dependency": EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY,
        "signoff_status_by_dependency": signoff_status_by_dependency,
        "signoff_status_mismatches": signoff_status_mismatches,
        "signoff_dependency_inventory_exact": not missing_signoffs
        and not extra_signoffs
        and not signoff_owner_role_mismatches
        and not signoff_status_mismatches,
        "open_signoff_ids": [str(item.get("item_id")) for item in open_signoffs],
        "missing_roles": missing_roles,
        "extra_roles": extra_roles,
        "missing_rollback_actions": missing_rollbacks,
        "extra_rollback_actions": extra_rollbacks,
        "missing_signoff_dependencies": missing_signoffs,
        "extra_signoff_dependencies": extra_signoffs,
        "pre_provider_staffing_inventory_exact": not missing_surface_roles
        and not missing_roles
        and not extra_roles
        and not missing_rollbacks
        and not extra_rollbacks
        and not missing_signoffs
        and not extra_signoffs
        and not role_status_mismatches
        and not rollback_owner_role_mismatches
        and not rollback_backup_role_mismatches
        and not signoff_owner_role_mismatches
        and not signoff_status_mismatches,
    }


def write_phase6_owner_staffing_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _validate_roles(rows: list[Any], failures: list[dict[str, str]]) -> set[str]:
    seen: set[str] = set()
    for index, row in enumerate(rows):
        field = f"roles[{index}]"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "role row must be an object"})
            continue
        role_id = str(row.get("role_id") or "").strip()
        if not role_id:
            failures.append({"field": field, "reason": "role_id is required"})
        elif role_id in seen:
            failures.append({"field": field, "reason": f"duplicate role_id {role_id}"})
        seen.add(role_id)
        if not str(row.get("area") or "").strip():
            failures.append({"field": field, "reason": "area is required"})
        status = str(row.get("status") or "")
        if status not in VALID_STATUSES:
            failures.append({"field": field, "reason": f"invalid status {status}"})
        if not _sequence(row.get("required_for")):
            failures.append({"field": field, "reason": "required_for is required"})
        if not str(row.get("next_action") or "").strip():
            failures.append({"field": field, "reason": "next_action is required"})
        if status == "named_ready":
            for key in ("named_owner", "backup_owner", "contact_channel"):
                if not str(row.get(key) or "").strip():
                    failures.append({"field": field, "reason": f"named_ready roles require {key}"})
    return seen


def _validate_rollback_actions(
    rows: dict[str, Any],
    role_ids: set[str],
    failures: list[dict[str, str]],
    *,
    checklist: dict[str, Any],
    runbook_text: str,
) -> None:
    checklist_actions = set(_mapping(checklist.get("rollback_plan"))) if checklist else set()
    if checklist_actions and set(rows) != checklist_actions:
        missing = sorted(checklist_actions - set(rows))
        extra = sorted(set(rows) - checklist_actions)
        if missing:
            failures.append({"field": "rollback_actions", "reason": f"missing checklist rollback actions: {', '.join(missing)}"})
        if extra:
            failures.append({"field": "rollback_actions", "reason": f"unknown rollback actions not in checklist: {', '.join(extra)}"})
    runbook_headings = _markdown_headings(runbook_text)
    for action, row in rows.items():
        field = f"rollback_actions.{action}"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "rollback action must be an object"})
            continue
        owner_role = str(row.get("owner_role") or "").strip()
        backup_role = str(row.get("backup_role") or "").strip()
        if owner_role not in role_ids:
            failures.append({"field": field, "reason": f"owner_role is not staffed: {owner_role}"})
        if backup_role and backup_role not in role_ids:
            failures.append({"field": field, "reason": f"backup_role is not staffed: {backup_role}"})
        if row.get("named_owner_required") is not True:
            failures.append({"field": field, "reason": "named_owner_required must be true"})
        for key in ("runbook_section", "provider_dependency"):
            if not str(row.get(key) or "").strip():
                failures.append({"field": field, "reason": f"{key} is required"})
        section = str(row.get("runbook_section") or "").strip()
        if runbook_headings and _slug(section) not in runbook_headings:
            failures.append({"field": field, "reason": f"runbook section is missing: {section}"})


def _validate_signoff_dependencies(
    rows: list[Any],
    role_ids: set[str],
    failures: list[dict[str, str]],
    *,
    root: Path,
    runbook_text: str,
) -> None:
    runbook_headings = _markdown_headings(runbook_text)
    seen: set[str] = set()
    for index, row in enumerate(rows):
        field = f"signoff_dependencies[{index}]"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "signoff dependency must be an object"})
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            failures.append({"field": field, "reason": "item_id is required"})
        elif item_id in seen:
            failures.append({"field": field, "reason": f"duplicate item_id {item_id}"})
        seen.add(item_id)
        owner_role = str(row.get("owner_role") or "").strip()
        if owner_role not in role_ids:
            failures.append({"field": field, "reason": f"owner_role is not staffed: {owner_role}"})
        for key in ("required_before", "runbook_section"):
            if not str(row.get(key) or "").strip():
                failures.append({"field": field, "reason": f"{key} is required"})
        section = str(row.get("runbook_section") or "").strip()
        if runbook_headings and _slug(section) not in runbook_headings:
            failures.append({"field": field, "reason": f"runbook section is missing: {section}"})
        evidence = _sequence(row.get("evidence"))
        if not evidence:
            failures.append({"field": field, "reason": "evidence is required"})
        for evidence_index, evidence_path in enumerate(evidence):
            evidence_text = str(evidence_path)
            if not (root / evidence_text).exists():
                failures.append({"field": f"{field}.evidence[{evidence_index}]", "reason": f"evidence path does not exist: {evidence_text}"})


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _load_optional_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return _load_yaml(path)


def _load_optional_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _resolve(root: Path, path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _referenced_launch_surface_roles(readiness_board: dict[str, Any], launch_gate_matrix: dict[str, Any], runbook_text: str) -> set[str]:
    roles: set[str] = set()
    for section in ("blockers", "must_have_demo_assets"):
        for row in _sequence(readiness_board.get(section)):
            if isinstance(row, dict):
                for key in ("owner_role", "escalation_owner"):
                    roles.update(_role_values(row.get(key)))
    for row in _mapping(readiness_board.get("rollback_plan")).values():
        if isinstance(row, dict):
            roles.update(_role_values(row.get("owner_role")))
    for row in _sequence(launch_gate_matrix.get("launch_gates")):
        if isinstance(row, dict):
            roles.update(_role_values(row.get("owner_role")))
    roles.update(match.group(1) for match in re.finditer(r"`([a-z][a-z0-9_]*_(?:lead|owner))`", runbook_text))
    return {role for role in roles if role}


def _role_values(value: Any) -> set[str]:
    text = str(value or "").strip()
    return {text} if text else set()


def _markdown_headings(markdown: str) -> set[str]:
    headings: set[str] = set()
    for line in markdown.splitlines():
        match = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if match:
            headings.add(_slug(match.group(1)))
    return headings


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _role_status_by_id(rows: list[Any]) -> dict[str, str]:
    return {
        str(row.get("role_id") or "").strip(): str(row.get("status") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("role_id") or "").strip()
    }


def _rollback_field_by_action(rows: dict[str, Any], field: str) -> dict[str, str]:
    return {
        str(action): str(row.get(field) or "").strip()
        for action, row in rows.items()
        if isinstance(row, dict)
    }


def _signoff_field_by_dependency(rows: list[Any], field: str) -> dict[str, str]:
    return {
        str(row.get("item_id") or "").strip(): str(row.get(field) or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("item_id") or "").strip()
    }


def _mismatches(expected: dict[str, str], observed: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        item_id: {"expected": expected_value, "observed": observed_value}
        for item_id, expected_value in sorted(expected.items())
        if (observed_value := observed.get(item_id)) is not None and observed_value != expected_value
    }
