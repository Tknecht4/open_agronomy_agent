from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


PHASE6_EXTERNAL_LINKS_VERSION = "phase6.external_links.v1"
VALID_STATUSES = {"pending_provider_staffing", "pending_public_url", "ready"}
READY_STATUS = "ready"
EXPECTED_LINK_IDS = {
    "github_repository",
    "contribution_guide",
    "support_issue_tracker",
}
EXPECTED_LABEL_BY_LINK_ID = {
    "github_repository": "GitHub repository",
    "contribution_guide": "Contribution guide",
    "support_issue_tracker": "Support and issue tracker",
}
EXPECTED_OWNER_ROLE_BY_LINK_ID = {link_id: "product_owner" for link_id in EXPECTED_LINK_IDS}
EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID = {
    "github_repository": "pending_public_url",
    "contribution_guide": "pending_public_url",
    "support_issue_tracker": "pending_provider_staffing",
}
EXPECTED_REQUIRED_BEFORE_BY_LINK_ID = {link_id: "external_launch" for link_id in EXPECTED_LINK_IDS}
EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID = {link_id: False for link_id in EXPECTED_LINK_IDS}
REQUIRED_EVIDENCE_BY_LINK_ID = {
    "github_repository": {
        "frontend/src/PublicDemoPages.tsx",
        "docs/phase6_public_claims_review.md",
    },
    "contribution_guide": {
        "frontend/src/PublicDemoPages.tsx",
        "plans/agronomy_agent_phase6_pre_demo_launch_packet/agronomy_agent_phase6_pre_demo_launch_design_packet.md",
    },
    "support_issue_tracker": {
        "frontend/src/PublicDemoPages.tsx",
        "docs/phase6_launch_readiness_board.yaml",
    },
}
PLACEHOLDER_URL_RE = re.compile(r"(example\.|localhost|127\.0\.0\.1|todo|placeholder|replace-me)", re.I)


def validate_phase6_external_links(links_path: str | Path, *, root_dir: str | Path | None = None) -> dict[str, Any]:
    links_file = Path(links_path)
    root = Path(root_dir) if root_dir is not None else _infer_root(links_file)
    payload = _load_yaml(links_file)
    failures: list[dict[str, str]] = []

    if payload.get("schema_version") != PHASE6_EXTERNAL_LINKS_VERSION:
        failures.append({"field": "schema_version", "reason": f"expected {PHASE6_EXTERNAL_LINKS_VERSION}"})
    if str(payload.get("phase")) != "6":
        failures.append({"field": "phase", "reason": "expected Phase 6 external links"})
    if set(payload.get("status_values") or []) != VALID_STATUSES:
        failures.append({"field": "status_values", "reason": "status values must match validator contract"})

    rows = payload.get("links") if isinstance(payload.get("links"), list) else []
    seen: set[str] = set()
    ready_ids: list[str] = []
    pending_ids: list[str] = []
    label_by_link_id: dict[str, str] = {}
    owner_role_by_link_id: dict[str, str] = {}
    status_by_link_id: dict[str, str] = {}
    required_before_by_link_id: dict[str, str] = {}
    has_url_by_link_id: dict[str, bool] = {}
    evidence_by_link_id: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        field = f"links[{index}]"
        if not isinstance(row, dict):
            failures.append({"field": field, "reason": "link row must be an object"})
            continue
        link_id = str(row.get("id") or "").strip()
        if not link_id:
            failures.append({"field": field, "reason": "id is required"})
        elif link_id in seen:
            failures.append({"field": field, "reason": f"duplicate link id {link_id}"})
        seen.add(link_id)
        label = str(row.get("label") or "").strip()
        if link_id:
            label_by_link_id[link_id] = label
        if not label:
            failures.append({"field": field, "reason": "label is required"})
        owner_role = str(row.get("owner_role") or "").strip()
        if link_id:
            owner_role_by_link_id[link_id] = owner_role
        if not owner_role:
            failures.append({"field": field, "reason": "owner_role is required"})
        required_before = str(row.get("required_before") or "").strip()
        if link_id:
            required_before_by_link_id[link_id] = required_before
        if not required_before:
            failures.append({"field": field, "reason": "required_before is required"})
        status = str(row.get("status") or "").strip()
        if link_id:
            status_by_link_id[link_id] = status
            has_url_by_link_id[link_id] = bool(str(row.get("url") or "").strip())
        if status not in VALID_STATUSES:
            failures.append({"field": field, "reason": f"invalid status {status}"})
        elif status == READY_STATUS:
            ready_ids.append(link_id)
            _validate_ready_url(row, field, failures)
        else:
            pending_ids.append(link_id)
            _validate_optional_url(row, field, failures)
            if not str(row.get("next_action") or "").strip():
                failures.append({"field": field, "reason": "pending link rows require next_action"})
        evidence_paths = _validate_evidence_paths(field, row.get("evidence"), failures, root=root)
        if link_id:
            evidence_by_link_id[link_id] = evidence_paths
            for required_evidence in sorted(REQUIRED_EVIDENCE_BY_LINK_ID.get(link_id, set()) - set(evidence_paths)):
                failures.append({"field": field, "reason": f"missing required evidence: {required_evidence}"})

    missing_ids = sorted(EXPECTED_LINK_IDS - seen)
    extra_ids = sorted(seen - EXPECTED_LINK_IDS)
    for link_id in missing_ids:
        failures.append({"field": "links", "reason": f"missing external link {link_id}"})
    for link_id in extra_ids:
        failures.append({"field": "links", "reason": f"unknown external link {link_id}"})

    label_mismatches = _mismatches(EXPECTED_LABEL_BY_LINK_ID, label_by_link_id)
    owner_role_mismatches = _mismatches(EXPECTED_OWNER_ROLE_BY_LINK_ID, owner_role_by_link_id)
    status_mismatches = _mismatches(EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID, status_by_link_id)
    required_before_mismatches = _mismatches(EXPECTED_REQUIRED_BEFORE_BY_LINK_ID, required_before_by_link_id)
    has_url_mismatches = _bool_mismatches(EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID, has_url_by_link_id)
    missing_required_evidence_by_link_id = {
        link_id: sorted(required - set(evidence_by_link_id.get(link_id, [])))
        for link_id, required in sorted(REQUIRED_EVIDENCE_BY_LINK_ID.items())
        if required - set(evidence_by_link_id.get(link_id, []))
    }
    pre_provider_link_inventory_exact = (
        not missing_ids
        and not extra_ids
        and not label_mismatches
        and not owner_role_mismatches
        and not status_mismatches
        and not required_before_mismatches
        and not has_url_mismatches
        and not missing_required_evidence_by_link_id
    )

    external_links_ready = not failures and not missing_ids and not extra_ids and set(ready_ids) == EXPECTED_LINK_IDS
    return {
        "schema_version": PHASE6_EXTERNAL_LINKS_VERSION,
        "links_path": str(links_file),
        "tracking_gate_passed": not failures,
        "external_links_ready": external_links_ready,
        "failure_count": len(failures),
        "failures": failures,
        "link_count": len(rows),
        "ready_count": len(ready_ids),
        "pending_count": len(pending_ids),
        "expected_link_ids": sorted(EXPECTED_LINK_IDS),
        "observed_link_ids": sorted(link_id for link_id in seen if link_id),
        "ready_ids": ready_ids,
        "pending_ids": pending_ids,
        "link_records": _link_records(rows),
        "missing_link_ids": missing_ids,
        "extra_link_ids": extra_ids,
        "expected_label_by_link_id": EXPECTED_LABEL_BY_LINK_ID,
        "label_by_link_id": label_by_link_id,
        "label_mismatches": label_mismatches,
        "expected_owner_role_by_link_id": EXPECTED_OWNER_ROLE_BY_LINK_ID,
        "owner_role_by_link_id": owner_role_by_link_id,
        "owner_role_mismatches": owner_role_mismatches,
        "expected_pre_provider_status_by_link_id": EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID,
        "status_by_link_id": status_by_link_id,
        "status_mismatches": status_mismatches,
        "expected_required_before_by_link_id": EXPECTED_REQUIRED_BEFORE_BY_LINK_ID,
        "required_before_by_link_id": required_before_by_link_id,
        "required_before_mismatches": required_before_mismatches,
        "expected_pre_provider_has_url_by_link_id": EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID,
        "has_url_by_link_id": has_url_by_link_id,
        "has_url_mismatches": has_url_mismatches,
        "required_evidence_by_link_id": {link_id: sorted(values) for link_id, values in sorted(REQUIRED_EVIDENCE_BY_LINK_ID.items())},
        "evidence_by_link_id": evidence_by_link_id,
        "missing_required_evidence_by_link_id": missing_required_evidence_by_link_id,
        "pre_provider_link_inventory_exact": pre_provider_link_inventory_exact,
    }


def write_phase6_external_links_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _validate_ready_url(row: dict[str, Any], field: str, failures: list[dict[str, str]]) -> None:
    url = str(row.get("url") or "").strip()
    if not url:
        failures.append({"field": field, "reason": "ready external links require url"})
    else:
        _validate_external_url(url, field, failures)


def _validate_optional_url(row: dict[str, Any], field: str, failures: list[dict[str, str]]) -> None:
    url = str(row.get("url") or "").strip()
    if url:
        _validate_external_url(url, field, failures)


def _validate_external_url(url: str, field: str, failures: list[dict[str, str]]) -> None:
    if not url.startswith("https://"):
        failures.append({"field": field, "reason": "external link url must use https"})
    elif PLACEHOLDER_URL_RE.search(url):
        failures.append({"field": field, "reason": "external link url must not be a placeholder"})


def _link_records(rows: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        records.append(
            {
                "id": str(row.get("id") or ""),
                "label": str(row.get("label") or ""),
                "owner_role": str(row.get("owner_role") or ""),
                "status": str(row.get("status") or ""),
                "required_before": str(row.get("required_before") or ""),
                "has_url": bool(str(row.get("url") or "").strip()),
                "next_action": str(row.get("next_action") or ""),
                "evidence_count": len(row.get("evidence") or []) if isinstance(row.get("evidence"), list) else 0,
            }
        )
    return records


def _validate_evidence_paths(field: str, evidence_value: Any, failures: list[dict[str, str]], *, root: Path) -> list[str]:
    evidence = evidence_value if isinstance(evidence_value, list) else []
    if not evidence:
        failures.append({"field": field, "reason": "evidence is required"})
        return []
    evidence_paths: list[str] = []
    for evidence_index, evidence_path in enumerate(evidence):
        evidence_text = str(evidence_path or "").strip()
        evidence_field = f"{field}.evidence[{evidence_index}]"
        if not evidence_text:
            failures.append({"field": evidence_field, "reason": "evidence path is required"})
        elif not (root / evidence_text).exists():
            failures.append({"field": evidence_field, "reason": f"evidence path does not exist: {evidence_text}"})
        else:
            evidence_paths.append(evidence_text)
    return evidence_paths


def _infer_root(links_file: Path) -> Path:
    candidate = links_file.resolve().parent.parent
    if (candidate / "docs").exists() and (candidate / "frontend").exists():
        return candidate
    return links_file.resolve().parent


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


def _bool_mismatches(expected: dict[str, bool], observed: dict[str, bool]) -> dict[str, dict[str, bool]]:
    return {
        item_id: {"expected": expected_value, "observed": observed_value}
        for item_id, expected_value in sorted(expected.items())
        if (observed_value := observed.get(item_id)) is not None and observed_value is not expected_value
    }
