from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path
from agronomy_agent.server.services.advisory_readiness_service import (
    system_advisory_readiness,
)
from agronomy_agent.source_permission_receipts import (
    DEFAULT_RECEIPT_ROOT,
    DEFAULT_REGISTRY_PATH,
    load_permission_response_registry,
)


GAP_MATRIX_PATH = "outputs/knowledge_freeze_readiness_20260725/conference_freeze_gap_matrix.json"
ADMISSION_QUEUE_PATH = "data/manifests/provincial_applied_guidance_admission_queue_20260724.json"
PERMISSION_PACKET_PATH = "data/manifests/provincial_permission_requests_20260725.json"
APPLIED_DISCOVERY_SLATE_PATH = (
    "data/manifests/canadian_applied_guidance_slate_20260726.json"
)
APPLIED_EVAL_CONTRACT_PATH = (
    "data/evals/canadian_applied_guidance_admission_eval_contract_20260726.json"
)
REVIEW_PACKET_REGISTRY_PATH = (
    "data/manifests/applied_guidance_review_packet_registry_20260726.json"
)
FRENCH_SOURCE_DISPOSITION_PATH = (
    "data/manifests/french_applied_guidance_source_disposition_20260726.json"
)
SOURCE_PREFLIGHT_REGISTRY_PATH = (
    "data/manifests/applied_guidance_source_preflight_registry_20260726.json"
)
PERMISSION_RESPONSE_REGISTRY_PATH = DEFAULT_REGISTRY_PATH
PERMISSION_RESPONSE_ROOT_PATH = DEFAULT_RECEIPT_ROOT
PROVINCES = (
    "British Columbia",
    "Alberta",
    "Saskatchewan",
    "Manitoba",
    "Ontario",
    "Quebec",
    "New Brunswick",
    "Nova Scotia",
    "Prince Edward Island",
    "Newfoundland and Labrador",
)
DISCOVERY_JURISDICTIONS = ("Canada", *PROVINCES)
DISCOVERY_LEADS_PER_JURISDICTION = 3


def canadian_knowledge_coverage(
    *,
    gap_matrix_path: Path | None = None,
    admission_queue_path: Path | None = None,
    permission_packet_path: Path | None = None,
    applied_discovery_slate_path: Path | None = None,
    source_census_path: Path | None = None,
    applied_eval_contract_path: Path | None = None,
    review_packet_registry_path: Path | None = None,
    french_source_disposition_path: Path | None = None,
    source_preflight_registry_path: Path | None = None,
    permission_response_registry_path: Path | None = None,
    permission_response_root_path: Path | None = None,
    advisory_readiness_path: Path | None = None,
    advisory_evidence_root: Path | None = None,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    gap_path = (gap_matrix_path or repo_path(GAP_MATRIX_PATH)).resolve()
    queue_path = (admission_queue_path or repo_path(ADMISSION_QUEUE_PATH)).resolve()
    permission_path = (
        permission_packet_path or repo_path(PERMISSION_PACKET_PATH)
    ).resolve()
    discovery_path = (
        applied_discovery_slate_path or repo_path(APPLIED_DISCOVERY_SLATE_PATH)
    ).resolve()
    eval_contract_path = (
        applied_eval_contract_path or repo_path(APPLIED_EVAL_CONTRACT_PATH)
    ).resolve()
    packet_registry_path = (
        review_packet_registry_path or repo_path(REVIEW_PACKET_REGISTRY_PATH)
    ).resolve()
    french_disposition_path = (
        french_source_disposition_path
        or repo_path(FRENCH_SOURCE_DISPOSITION_PATH)
    ).resolve()
    source_preflight_path = (
        source_preflight_registry_path
        or repo_path(SOURCE_PREFLIGHT_REGISTRY_PATH)
    ).resolve()
    response_registry_path = (
        permission_response_registry_path
        or repo_path(PERMISSION_RESPONSE_REGISTRY_PATH)
    ).resolve()
    response_root_path = (
        permission_response_root_path or repo_path(PERMISSION_RESPONSE_ROOT_PATH)
    ).resolve()
    try:
        gap = _read_json(gap_path)
        queue = _read_json(queue_path)
        permission_packet = _read_json(permission_path)
        _validate_gap_matrix(gap)
        _validate_admission_queue(queue)
        _validate_permission_packet(permission_packet, queue)
        response_registry = load_permission_response_registry(
            registry_path=response_registry_path,
            receipt_root=response_root_path,
            packet_path=permission_path,
            as_of=as_of,
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        advisory_readiness = system_advisory_readiness(
            knowledge_coverage_ready=False,
            readiness_path=advisory_readiness_path,
            evidence_root=advisory_evidence_root,
        )
        return {
            "schema_version": "open_agronomy_agent.canadian_knowledge_coverage.v1",
            "available": False,
            "status": "unavailable",
            "message": f"Governed Canadian coverage evidence is unavailable: {exc}",
            "advisory_ready": False,
            "knowledge_coverage_ready": False,
            "advisory_readiness": advisory_readiness,
            "discovery_pipeline": {
                "available": False,
                "admitted_candidates": 0,
                "boundary": (
                    "Coverage evidence is unavailable; discovery cannot be treated as "
                    "admission or permission to advise."
                ),
            },
            "boundary": (
                "Missing coverage evidence must not be interpreted as knowledge coverage or "
                "permission to provide province-specific applied advice."
            ),
            "summary": {},
            "provinces": [],
        }

    discovery_pipeline: dict[str, Any]
    discovery_sha256: str | None = None
    source_census_sha256: str | None = None
    eval_contract_sha256: str | None = None
    review_packet_registry_sha256: str | None = None
    french_source_disposition_sha256: str | None = None
    source_preflight_registry_sha256: str | None = None
    try:
        discovery = _read_json(discovery_path)
        _validate_applied_discovery_slate(discovery)
        discovery_sha256 = _sha256(discovery_path)
        census_declaration = discovery["source_census"]
        census_path = (
            source_census_path
            or repo_path(str(census_declaration["path"]))
        ).resolve()
        source_census = _read_json(census_path)
        _validate_official_source_census(source_census)
        source_census_sha256 = _sha256(census_path)
        if source_census_sha256 != census_declaration["sha256"]:
            raise ValueError(
                "official-source census hash does not match discovery slate"
            )
        eval_contract = _read_json(eval_contract_path)
        _validate_applied_eval_contract(eval_contract, discovery_sha256)
        review_packet_registry = _read_json(packet_registry_path)
        _validate_review_packet_registry(
            review_packet_registry,
            queue=queue,
            census_sha256=source_census_sha256,
            slate_sha256=discovery_sha256,
        )
        french_source_disposition = _read_json(french_disposition_path)
        _validate_french_source_disposition(
            french_source_disposition,
            discovery=discovery,
            slate_sha256=discovery_sha256,
        )
        source_preflight_registry = _read_json(source_preflight_path)
        _validate_source_preflight_registry(
            source_preflight_registry,
            discovery=discovery,
            slate_sha256=discovery_sha256,
        )
        discovery_diagnostics = discovery["diagnostics"]
        review_summary = review_packet_registry["summary"]
        packet_groups = [
            _review_packet_presentation(row)
            for row in review_packet_registry["packet_groups"]
        ]
        french_summary = french_source_disposition["summary"]
        discovery_pipeline = {
            "available": True,
            "selected_candidates": int(
                discovery_diagnostics["selected_candidates"]
            ),
            "jurisdictions_with_candidates": int(
                discovery_diagnostics["jurisdictions_with_candidates"]
            ),
            "french_candidates": int(discovery_diagnostics["french_candidates"]),
            "access_barrier_candidates": int(
                discovery_diagnostics["access_barrier_candidates"]
            ),
            "federal_publications_candidates": sum(
                row.get("authority_id") == "goc_publications_aafc"
                for row in discovery["candidates"]
            ),
            "admitted_candidates": 0,
            "evaluation_contract_status": eval_contract["status"],
            "evaluation_results_claimed": False,
            "runtime_admission_before_gate": False,
            "acquisition_funnel": {
                "official_records_discovered": int(
                    source_census["summary"]["record_count"]
                ),
                "ranked_leads": int(
                    discovery_diagnostics["selected_candidates"]
                ),
                "admitted_from_ranked_leads": 0,
                "display_text": (
                    f"{int(source_census['summary']['record_count']):,} official records "
                    f"→ {int(discovery_diagnostics['selected_candidates']):,} ranked leads "
                    "→ 0 admitted"
                ),
                "boundary": (
                    "This is the current census-to-ranked-lead discovery lane. It does "
                    "not imply review or agronomic correctness. The Manitoba check-stamp "
                    "and stored-grain packets are now bound to two ranked leads; the other "
                    "prepared packet sources retain their separate acquisition lineage."
                ),
            },
            "review_pipeline": {
                **review_summary,
                "lineage_relation_to_current_ranked_slate": (
                    "mixed_exact_ranked_and_separate_acquisition"
                ),
                "display_text": (
                    f"Separate review lane: {review_summary['prepared_packet_groups']} "
                    f"prepared groups · {review_summary['source_documents']} source "
                    f"documents · {review_summary['candidate_summaries']} candidate "
                    f"summaries · {review_summary['cryptographically_verified_reviews']}/"
                    f"{review_summary['required_independent_reviews']} independent "
                    f"reviews cryptographically verified · "
                    f"{review_summary['admitted_packet_groups']} admitted"
                ),
                "boundary": (
                    "Manitoba now has two 2026 OpenMB crop-protection documents outside "
                    "the ranked slate plus exact ranked check-stamp and stored-grain "
                    "sources; its eight candidate summaries remain quarantined. Alberta's three "
                    "2026 OGLA documents remain post-census and outside the slate, and "
                    "its legacy CSV review path does not verify signer identity. The "
                    "B.C. section 59.1 candidate is a current-authority replacement "
                    "with an explicit HTML/PDF currentness conflict; its one-row "
                    "candidate-only promotion transform is implemented but inert. "
                    "Across all three groups, all "
                    f"{review_summary['candidate_summaries']} candidates remain "
                    "unreviewed and "
                    f"{review_summary['required_independent_reviews']} independent "
                    "reviews are required."
                ),
                "packet_groups": packet_groups,
            },
            "french_source_lane": {
                **french_summary,
                "status": french_source_disposition["status"],
                "display_text": (
                    f"French source lane: "
                    f"{french_summary['ranked_french_records']} ranked records → "
                    f"{french_summary['unique_source_families']} source families → "
                    f"{french_summary['connected_link_only_families']} connected "
                    f"link-only · "
                    f"{french_summary['source_asset_access_blocked_families']} "
                    "source asset access-blocked · "
                    f"{french_summary['exact_byte_currentness_rejected_families']} "
                    "exact-byte currentness-rejected · "
                    f"{french_summary['exact_byte_rights_blocked_families']} "
                    "exact-byte rights-blocked → "
                    f"{french_summary['packaged_offline_families']} "
                    "packaged offline → 0 admitted"
                ),
                "source_families": french_source_disposition["source_families"],
                "existing_lawful_translation_lane": (
                    french_source_disposition["existing_lawful_translation_lane"]
                ),
                "boundary": french_source_disposition["boundary"],
            },
            "source_preflight_pipeline": {
                **source_preflight_registry["summary"],
                "display_text": (
                    f"Source preflights: "
                    f"{source_preflight_registry['summary']['preflighted_source_families']} "
                    f"families · "
                    f"{source_preflight_registry['summary']['ranked_records_resolved']} "
                    f"ranked records resolved · "
                    f"{source_preflight_registry['summary']['advanced_to_review_packet']} "
                    f"advanced · "
                    f"{source_preflight_registry['summary']['rejected_for_actionable_review_packet']} "
                    "actionable-rejected · "
                    f"{source_preflight_registry['summary']['blocked_pending_rights_clarification']} "
                    "rights-blocked"
                ),
                "preflights": source_preflight_registry["preflights"],
                "boundary": source_preflight_registry["boundary"],
            },
            "source_leads": _applied_discovery_source_leads(
                discovery,
                preflights=source_preflight_registry["preflights"],
                french_source_families=(
                    french_source_disposition["source_families"]
                ),
            ),
            "boundary": (
                "Discovery candidates are acquisition leads only and cannot influence "
                "answers before exact rights, byte freeze, extraction lineage, independent "
                "agronomic review, and disjoint evaluation gates pass."
            ),
        }
        eval_contract_sha256 = _sha256(eval_contract_path)
        review_packet_registry_sha256 = _sha256(packet_registry_path)
        french_source_disposition_sha256 = _sha256(french_disposition_path)
        source_preflight_registry_sha256 = _sha256(source_preflight_path)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        discovery_pipeline = {
            "available": False,
            "message": f"Applied-guidance discovery evidence is unavailable: {exc}",
            "admitted_candidates": 0,
            "boundary": (
                "Unavailable discovery evidence must not be interpreted as source "
                "coverage, admission, or permission to advise."
            ),
        }

    queue_by_province = {str(row["jurisdiction"]): row for row in queue["rows"]}
    permission_by_province = {
        str(row["jurisdiction"]): row for row in permission_packet["requests"]
    }
    withheld_permission_by_province = {
        str(row["jurisdiction"]): row
        for row in permission_packet["withheld_requests"]
    }
    response_by_request = response_registry["responses"]
    provinces = []
    for row in gap["province_matrix"]:
        province = str(row["province"])
        admission = queue_by_province[province]
        permission = permission_by_province.get(province)
        withheld_permission = withheld_permission_by_province.get(province)
        registered_response = (
            response_by_request.get(permission["request_id"])
            if permission is not None
            else None
        )
        permission_decision = (
            registered_response["decision"]
            if registered_response is not None
            else None
        )
        standard_rows = int(row["active_standard_applied_rows"])
        bounded_rows = int(row["active_bounded_applied_rows"])
        context_rows = int(row["active_rows"]) + int(row["active_context_supplement_rows"])
        provinces.append(
            {
                "province": province,
                "context_available": context_rows > 0,
                "standard_applied_guidance": standard_rows > 0,
                "bounded_applied_guidance": bounded_rows > 0,
                "active_context_rows": context_rows,
                "active_standard_applied_rows": standard_rows,
                "active_bounded_applied_rows": bounded_rows,
                "coverage_label": (
                    "Reviewed applied guidance"
                    if standard_rows
                    else "Bounded context only"
                    if bounded_rows
                    else "Regional context only"
                    if context_rows
                    else "No active local context"
                ),
                "admission_state": str(admission["admission_state"]),
                "candidate": str(admission["candidate"]),
                "review_packet": admission.get("review_packet"),
                "signed_review_kit": admission.get("signed_review_kit"),
                "source_url": str(admission["source_url"]),
                "rights_state": str(admission["rights_state"]),
                "rights_url": str(admission["rights_url"]),
                "rights_reaudit_at": admission.get("rights_reaudit_at"),
                "rights_reaudit_result": admission.get("rights_reaudit_result"),
                "permission_request_id": (
                    permission["request_id"] if permission is not None else None
                ),
                "permission_status": (
                    f"response_recorded / {permission_decision['response_state']}"
                    if permission_decision is not None
                    else f"{permission['request_status']} / {permission['response_state']}"
                    if permission is not None
                    else (
                        "withheld_after_preflight / "
                        + str(withheld_permission["preflight_state"])
                    )
                    if withheld_permission is not None
                    else "not_required"
                ),
                "permission_withheld_state": (
                    withheld_permission["withheld_state"]
                    if withheld_permission is not None
                    else None
                ),
                "permission_withheld_reason": (
                    withheld_permission["reason"]
                    if withheld_permission is not None
                    else None
                ),
                "permission_preflight_id": (
                    withheld_permission["preflight_id"]
                    if withheld_permission is not None
                    else None
                ),
                "permission_route": (
                    permission["submission_route"] if permission is not None else None
                ),
                "permission_route_state": (
                    permission["route_state"] if permission is not None else None
                ),
                "permission_response_state": (
                    permission_decision["response_state"]
                    if permission_decision is not None
                    else None
                ),
                "permission_decision_state": (
                    permission_decision["admission_state"]
                    if permission_decision is not None
                    else None
                ),
                "permission_rights_gate_cleared": (
                    permission_decision["rights_gate_cleared"]
                    if permission_decision is not None
                    else False
                ),
                "permission_received_at": (
                    permission_decision["received_at"]
                    if permission_decision is not None
                    else None
                ),
                "permission_receipt_sha256": (
                    registered_response["receipt_sha256"]
                    if registered_response is not None
                    else None
                ),
                "next_action": (
                    permission_decision["coverage_next_action"]
                    if permission_decision is not None
                    else str(withheld_permission["next_gate"])
                    if withheld_permission is not None
                    else str(admission["next_action"])
                ),
            }
        )

    summary = gap["summary"]
    standard_count = sum(row["standard_applied_guidance"] for row in provinces)
    context_count = sum(row["context_available"] for row in provinces)
    bounded_count = sum(row["bounded_applied_guidance"] for row in provinces)
    pending_review_count = sum(
        row["admission_state"]
        in {
            "candidate_pending_independent_agronomist",
            "candidate_pending_independent_professional_review",
        }
        for row in provinces
    )
    french_standard_rows = int(summary["actual_french_standard_applied_rows"])
    knowledge_coverage_ready = (
        standard_count == len(PROVINCES) and french_standard_rows > 0
    )
    advisory_readiness = system_advisory_readiness(
        knowledge_coverage_ready=knowledge_coverage_ready,
        readiness_path=advisory_readiness_path,
        evidence_root=advisory_evidence_root,
    )
    advisory_evidence = advisory_readiness.get("evidence") or {}
    advisory_lineage = {
        key: value
        for key in (
            "advisory_readiness_sha256",
            "advisory_blocker_baseline_sha256",
        )
        if isinstance((value := advisory_evidence.get(key)), str)
        and len(value) == 64
    }
    advisory_ready = bool(advisory_readiness["advisory_ready"])
    return {
        "schema_version": "open_agronomy_agent.canadian_knowledge_coverage.v1",
        "available": True,
        "status": "blocked" if not advisory_ready else "ready",
        "generated_at": gap["generated_at"],
        "advisory_ready": advisory_ready,
        "knowledge_coverage_ready": knowledge_coverage_ready,
        "advisory_readiness": advisory_readiness,
        "discovery_pipeline": discovery_pipeline,
        "admission_frontier": queue["admission_frontier"],
        "summary": {
            "province_count": len(PROVINCES),
            "governed_local_rows": int(summary["active_rows"]),
            "governed_local_sources": int(summary["active_sources"]),
            "regional_context_provinces": context_count,
            "standard_applied_guidance_provinces": standard_count,
            "bounded_applied_guidance_provinces": bounded_count,
            "recommendation_grade_active_provinces": int(
                queue["recommendation_grade_active_provinces"]
            ),
            "candidates_pending_independent_agronomist": pending_review_count,
            "rights_reaudited_blocked_provinces": sum(
                bool(row.get("rights_reaudit_result"))
                and row["admission_state"]
                not in {
                    "candidate_pending_independent_agronomist",
                    "candidate_pending_independent_professional_review",
                }
                for row in provinces
            ),
            "permission_requests_not_submitted": sum(
                row["permission_status"] == "not_submitted / none" for row in provinces
            ),
            "permission_requests_withheld_after_preflight": sum(
                row["permission_withheld_state"]
                == "withheld_after_exact_source_preflight"
                for row in provinces
            ),
            "permission_responses_recorded": sum(
                row["permission_response_state"] is not None for row in provinces
            ),
            "permission_rights_gate_candidates": sum(
                row["permission_rights_gate_cleared"] for row in provinces
            ),
            "permission_responses_blocked": sum(
                row["permission_response_state"] is not None
                and not row["permission_rights_gate_cleared"]
                for row in provinces
            ),
            "actual_french_text_rows": int(summary["actual_french_text_rows"]),
            "actual_french_standard_applied_rows": french_standard_rows,
        },
        "provinces": provinces,
        "evidence": {
            "gap_matrix_sha256": _sha256(gap_path),
            "admission_queue_sha256": _sha256(queue_path),
            "permission_request_packet_sha256": _sha256(permission_path),
            "permission_response_registry_sha256": response_registry[
                "registry_sha256"
            ],
            **(
                {"applied_discovery_slate_sha256": discovery_sha256}
                if discovery_sha256 is not None
                else {}
            ),
            **(
                {"official_source_census_sha256": source_census_sha256}
                if source_census_sha256 is not None
                else {}
            ),
            **(
                {"applied_eval_contract_sha256": eval_contract_sha256}
                if eval_contract_sha256 is not None
                else {}
            ),
            **(
                {
                    "applied_guidance_review_packet_registry_sha256": (
                        review_packet_registry_sha256
                    )
                }
                if review_packet_registry_sha256 is not None
                else {}
            ),
            **(
                {
                    "french_applied_guidance_source_disposition_sha256": (
                        french_source_disposition_sha256
                    )
                }
                if french_source_disposition_sha256 is not None
                else {}
            ),
            **(
                {
                    "applied_guidance_source_preflight_registry_sha256": (
                        source_preflight_registry_sha256
                    )
                }
                if source_preflight_registry_sha256 is not None
                else {}
            ),
            **advisory_lineage,
        },
        "boundary": (
            "Regional and bounded context can frame questions but cannot independently support a "
            "province-specific management action. The knowledge gate requires current standard "
            "applied guidance in every province plus active French standard guidance. A registered "
            "permission response can clear only a rights-gate candidate and never activates a "
            "source. Full advisory readiness additionally requires every hash-bound system, "
            "security, independent-expert and farmer/adviser validation gate to pass."
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"coverage evidence root must be an object: {path}")
    return payload


def _validate_gap_matrix(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "open_agronomy_agent.conference_freeze_gap_matrix.v1":
        raise ValueError("unsupported conference-freeze gap matrix")
    rows = payload.get("province_matrix")
    if not isinstance(rows, list) or [row.get("province") for row in rows] != list(PROVINCES):
        raise ValueError("coverage matrix must contain the canonical ten provinces in order")
    required_counts = {
        "active_rows",
        "active_standard_applied_rows",
        "active_bounded_applied_rows",
        "active_context_supplement_rows",
    }
    for row in rows:
        if not required_counts.issubset(row) or any(
            not isinstance(row[key], int) or row[key] < 0 for key in required_counts
        ):
            raise ValueError("coverage matrix province counts are invalid")
    summary = payload.get("summary")
    if not isinstance(summary, dict) or any(
        not isinstance(summary.get(key), int)
        for key in (
            "active_rows",
            "active_sources",
            "actual_french_text_rows",
            "actual_french_standard_applied_rows",
        )
    ):
        raise ValueError("coverage matrix language summary is invalid")


def _validate_admission_queue(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "open_agronomy_agent.provincial_applied_guidance_queue.v1":
        raise ValueError("unsupported provincial admission queue")
    rows = payload.get("rows")
    if not isinstance(rows, list) or {row.get("jurisdiction") for row in rows} != set(PROVINCES):
        raise ValueError("admission queue must contain one row for every province")
    for row in rows:
        if any(
            not isinstance(row.get(key), str) or not row[key].strip()
            for key in (
                "candidate",
                "source_url",
                "rights_state",
                "rights_url",
                "admission_state",
                "next_action",
            )
        ):
            raise ValueError("admission queue row is incomplete")
        if not row["source_url"].startswith("https://") or not row["rights_url"].startswith(
            "https://"
        ):
            raise ValueError("admission queue evidence links must use https")
        if "rights_reaudit_result" in row and any(
            not isinstance(row.get(key), str) or not row[key].strip()
            for key in ("rights_reaudit_at", "rights_reaudit_result")
        ):
            raise ValueError("admission queue rights re-audit is incomplete")
    count = payload.get("recommendation_grade_active_provinces")
    if not isinstance(count, int) or count < 0 or count > len(PROVINCES):
        raise ValueError("recommendation-grade province count is invalid")
    active_jurisdictions = payload.get("recommendation_grade_active_jurisdictions")
    if (
        not isinstance(active_jurisdictions, list)
        or any(
            not isinstance(value, str) or value not in PROVINCES
            for value in active_jurisdictions
        )
        or len(active_jurisdictions) != len(set(active_jurisdictions))
    ):
        raise ValueError("recommendation-grade active jurisdictions are invalid")
    row_active_jurisdictions = sorted(
        row["jurisdiction"]
        for row in rows
        if row["admission_state"] == "active_decisive"
    )
    if sorted(active_jurisdictions) != row_active_jurisdictions:
        raise ValueError(
            "recommendation-grade active jurisdictions do not match admission rows"
        )
    if count != len(active_jurisdictions):
        raise ValueError(
            "recommendation-grade province count does not match active jurisdictions"
        )
    frontier = payload.get("admission_frontier")
    if not isinstance(frontier, dict):
        raise ValueError("admission queue frontier is missing")
    review_ready = frontier.get("current_review_ready_jurisdictions")
    expected_review_ready = sorted(
        row["jurisdiction"]
        for row in rows
        if row["admission_state"]
        in {
            "candidate_pending_independent_agronomist",
            "candidate_pending_independent_professional_review",
        }
    )
    if review_ready != expected_review_ready:
        raise ValueError(
            "admission frontier review-ready jurisdictions do not match queue rows"
        )
    third = frontier.get("next_third_jurisdiction")
    if not isinstance(third, dict):
        raise ValueError("admission frontier third-jurisdiction lane is missing")
    third_jurisdiction = third.get("jurisdiction")
    queue_by_jurisdiction = {
        str(row["jurisdiction"]): row for row in rows
    }
    third_row = queue_by_jurisdiction.get(str(third_jurisdiction))
    third_is_prepared = (
        third.get("status") == "review_packet_prepared_not_runtime_authorized"
    )
    if (
        third_row is None
        or third_is_prepared != (third_jurisdiction in review_ready)
        or third.get("candidate") != third_row["candidate"]
        or third.get("source_url") != third_row["source_url"]
        or third.get("rights_url") != third_row["rights_url"]
        or third.get("runtime_activation_authorized") is not False
        or not isinstance(third.get("selection_basis"), str)
        or not third["selection_basis"].strip()
        or not isinstance(third.get("unresolved_gates"), list)
        or not third["unresolved_gates"]
        or any(
            not isinstance(value, str) or not value.strip()
            for value in third["unresolved_gates"]
        )
    ):
        raise ValueError("admission frontier third-jurisdiction lane is invalid")
    next_unprepared = frontier.get("next_unprepared_jurisdiction")
    if (
        not isinstance(next_unprepared, dict)
        or next_unprepared.get("jurisdiction") in review_ready
        or next_unprepared.get("runtime_activation_authorized") is not False
        or not isinstance(next_unprepared.get("unresolved_gates"), list)
        or not next_unprepared["unresolved_gates"]
    ):
        raise ValueError("admission frontier unprepared lane is invalid")
    if (
        not isinstance(frontier.get("boundary"), str)
        or not frontier["boundary"].strip()
    ):
        raise ValueError("admission frontier boundary is missing")


def _validate_permission_packet(packet: dict[str, Any], queue: dict[str, Any]) -> None:
    if (
        packet.get("schema_version")
        != "open_agronomy_agent.provincial_permission_request_packet.v1"
    ):
        raise ValueError("unsupported provincial permission request packet")
    requests = packet.get("requests")
    withheld_requests = packet.get("withheld_requests")
    if (
        not isinstance(requests, list)
        or not isinstance(withheld_requests, list)
        or packet.get("request_count") != len(requests)
        or packet.get("withheld_request_count") != len(withheld_requests)
    ):
        raise ValueError(
            "permission request packet request and withheld counts are stale"
        )
    by_jurisdiction = {request.get("jurisdiction"): request for request in requests}
    if len(by_jurisdiction) != len(requests):
        raise ValueError("permission request jurisdictions must be unique")
    withheld_by_jurisdiction = {
        request.get("jurisdiction"): request
        for request in withheld_requests
    }
    if (
        len(withheld_by_jurisdiction) != len(withheld_requests)
        or set(by_jurisdiction) & set(withheld_by_jurisdiction)
    ):
        raise ValueError(
            "permission request and withheld jurisdictions must be unique"
        )
    blocked = {
        row["jurisdiction"]: row
        for row in queue["rows"]
        if row["admission_state"]
        not in {
            "candidate_pending_independent_agronomist",
            "candidate_pending_independent_professional_review",
            "active_decisive",
        }
    }
    if set(by_jurisdiction) | set(withheld_by_jurisdiction) != set(blocked):
        raise ValueError("permission request packet does not match rights-blocked provinces")
    for jurisdiction, request in by_jurisdiction.items():
        if any(
            not isinstance(request.get(key), str) or not request[key].strip()
            for key in (
                "request_id",
                "source_url",
                "submission_route",
                "route_state",
                "request_status",
                "response_state",
            )
        ):
            raise ValueError("permission request packet row is incomplete")
        if request["source_url"] != blocked[jurisdiction]["source_url"]:
            raise ValueError("permission request source does not match admission queue")
        if not request["submission_route"].startswith("https://"):
            raise ValueError("permission submission route must use https")
    for jurisdiction, withheld in withheld_by_jurisdiction.items():
        if (
            withheld.get("source_url") != blocked[jurisdiction]["source_url"]
            or withheld.get("withheld_state")
            != "withheld_after_exact_source_preflight"
            or withheld.get("preflight_state")
            != "rejected_for_actionable_review_packet"
            or not isinstance(withheld.get("preflight_id"), str)
            or not withheld["preflight_id"]
            or not isinstance(withheld.get("reason"), str)
            or not withheld["reason"]
            or not isinstance(withheld.get("next_gate"), str)
            or not withheld["next_gate"]
            or withheld.get("runtime_admitted") is not False
        ):
            raise ValueError(
                "withheld permission request escaped exact-source preflight"
            )


def _validate_applied_discovery_slate(payload: dict[str, Any]) -> None:
    if (
        payload.get("schema_version")
        != "open_agronomy_agent.canadian_applied_guidance_slate.v2"
    ):
        raise ValueError("unsupported Canadian applied-guidance discovery slate")
    boundary = payload.get("boundary")
    if (
        not isinstance(boundary, dict)
        or boundary.get("discovery_only") is not True
        or boundary.get("automatic_ingestion") is not False
        or boundary.get("automatic_admission") is not False
        or boundary.get("automatic_advisory_use") is not False
    ):
        raise ValueError("applied-guidance discovery boundary is unsafe")
    diagnostics = payload.get("diagnostics")
    required_counts = {
        "selected_candidates",
        "jurisdictions_with_candidates",
        "french_candidates",
        "access_barrier_candidates",
    }
    if not isinstance(diagnostics, dict) or any(
        not isinstance(diagnostics.get(key), int) or diagnostics[key] < 0
        for key in required_counts
    ):
        raise ValueError("applied-guidance discovery diagnostics are invalid")
    candidates = payload.get("candidates")
    if (
        not isinstance(candidates, list)
        or len(candidates) != diagnostics["selected_candidates"]
    ):
        raise ValueError("applied-guidance discovery candidate count is invalid")
    if any(
        row.get("discovery_only") is not True
        or row.get("admission_state") != "discovered_not_admitted"
        or not isinstance(row.get("required_next_gate"), str)
        or not row["required_next_gate"]
        for row in candidates
    ):
        raise ValueError("applied-guidance discovery candidate escaped its gate")
    barriers = payload.get("access_barriers")
    if not isinstance(barriers, list):
        raise ValueError("applied-guidance access barriers are invalid")
    all_records = [*candidates, *barriers]
    record_ids = [row.get("record_id") for row in all_records]
    if (
        any(not isinstance(value, str) or not value for value in record_ids)
        or len(record_ids) != len(set(record_ids))
    ):
        raise ValueError("applied-guidance discovery record IDs are invalid")
    for row in all_records:
        if (
            row.get("jurisdiction") not in DISCOVERY_JURISDICTIONS
            or not isinstance(row.get("title"), str)
            or not row["title"].strip()
            or not isinstance(row.get("url"), str)
            or not row["url"].startswith("https://")
            or not isinstance(row.get("language"), str)
            or not row["language"]
            or not isinstance(row.get("rights_lane"), str)
            or not row["rights_lane"]
            or not isinstance(row.get("access_state"), str)
            or not row["access_state"]
            or not isinstance(row.get("applied_task_signals"), list)
            or not row["applied_task_signals"]
            or any(
                not isinstance(signal, str) or not signal
                for signal in row["applied_task_signals"]
            )
        ):
            raise ValueError("applied-guidance discovery lead is incomplete")
    if any(
        row.get("discovery_only") is not True
        or row.get("admission_state") != "access_blocked_not_admitted"
        or not isinstance(row.get("required_next_gate"), str)
        or not row["required_next_gate"]
        for row in barriers
    ):
        raise ValueError("applied-guidance access barrier escaped its gate")
    jurisdiction_rows = payload.get("jurisdictions")
    if (
        not isinstance(jurisdiction_rows, list)
        or {row.get("jurisdiction") for row in jurisdiction_rows}
        != set(DISCOVERY_JURISDICTIONS)
        or len(jurisdiction_rows) != len(DISCOVERY_JURISDICTIONS)
    ):
        raise ValueError("applied-guidance jurisdiction summaries are incomplete")
    for summary in jurisdiction_rows:
        jurisdiction = summary["jurisdiction"]
        candidate_count = sum(
            row["jurisdiction"] == jurisdiction for row in candidates
        )
        barrier_count = sum(
            row["jurisdiction"] == jurisdiction for row in barriers
        )
        if (
            summary.get("candidate_count") != candidate_count
            or summary.get("access_barrier_count") != barrier_count
            or not isinstance(summary.get("gaps"), list)
        ):
            raise ValueError("applied-guidance jurisdiction summary is stale")
    if (
        diagnostics["selected_candidates"] != len(candidates)
        or diagnostics["jurisdictions_with_candidates"]
        != len({row["jurisdiction"] for row in candidates})
        or diagnostics["french_candidates"]
        != sum(row["language"] == "fr-CA" for row in candidates)
        or diagnostics["access_barrier_candidates"] != len(barriers)
    ):
        raise ValueError("applied-guidance discovery diagnostics are stale")
    source_census = payload.get("source_census")
    if (
        not isinstance(source_census, dict)
        or not isinstance(source_census.get("path"), str)
        or not source_census["path"].startswith("data/manifests/")
        or not isinstance(source_census.get("sha256"), str)
        or len(source_census["sha256"]) != 64
    ):
        raise ValueError("applied-guidance source census declaration is invalid")


def _validate_official_source_census(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported Canadian official-source census")
    records = payload.get("records")
    summary = payload.get("summary")
    if (
        not isinstance(records, list)
        or not isinstance(summary, dict)
        or summary.get("record_count") != len(records)
        or not isinstance(summary.get("authority_count"), int)
        or summary["authority_count"] < 1
        or not isinstance(summary.get("jurisdiction_count"), int)
        or summary["jurisdiction_count"] < len(DISCOVERY_JURISDICTIONS)
    ):
        raise ValueError("Canadian official-source census counts are invalid")
    record_ids = [row.get("record_id") for row in records]
    if (
        any(not isinstance(value, str) or not value for value in record_ids)
        or len(record_ids) != len(set(record_ids))
    ):
        raise ValueError("Canadian official-source census record IDs are invalid")


def _validate_review_packet_registry(
    payload: dict[str, Any],
    *,
    queue: dict[str, Any],
    census_sha256: str,
    slate_sha256: str,
) -> None:
    if (
        payload.get("schema_version")
        != "open_agronomy_agent.applied_guidance_review_packet_registry.v1"
        or payload.get("status") != "ready_for_external_independent_review"
        or payload.get("runtime_admission_before_gate") is not False
    ):
        raise ValueError("unsupported or unsafe applied-guidance packet registry")
    if (payload.get("source_census") or {}).get("sha256") != census_sha256:
        raise ValueError("review-packet registry census hash is stale")
    if (payload.get("ranked_slate") or {}).get("sha256") != slate_sha256:
        raise ValueError("review-packet registry slate hash is stale")
    groups = payload.get("packet_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("review-packet registry has no packet groups")
    expected_jurisdictions = {
        str(row["jurisdiction"])
        for row in queue["rows"]
        if row["admission_state"]
        in {
            "candidate_pending_independent_agronomist",
            "candidate_pending_independent_professional_review",
        }
    }
    if {row.get("jurisdiction") for row in groups} != expected_jurisdictions:
        raise ValueError("review-packet groups do not match the admission queue")
    packet_ids = [row.get("packet_id") for row in groups]
    if (
        any(not isinstance(value, str) or not value for value in packet_ids)
        or len(packet_ids) != len(set(packet_ids))
    ):
        raise ValueError("review-packet IDs are invalid")
    for group in groups:
        documents = group.get("source_documents")
        candidates = group.get("candidates") or {}
        ranked_lineage = group.get("ranked_slate_lineage") or {}
        census_lineage = group.get("census_lineage") or {}
        required_reviews = group.get("required_independent_reviews")
        worksheet_reviews = group.get("worksheet_completed_review_rows")
        completed_reviews = group.get("completed_independent_reviews")
        verified_reviews = group.get("cryptographically_verified_reviews")
        evidence_mode = group.get("review_evidence_mode")
        if (
            group.get("status") != "ready_for_external_independent_review"
            or not isinstance(documents, list)
            or not documents
            or group.get("source_document_count") != len(documents)
            or not isinstance(candidates.get("count"), int)
            or candidates["count"] < 1
            or not isinstance(required_reviews, int)
            or required_reviews < candidates["count"]
            or not isinstance(worksheet_reviews, int)
            or worksheet_reviews < 0
            or worksheet_reviews > required_reviews
            or not isinstance(completed_reviews, int)
            or completed_reviews < 0
            or completed_reviews > required_reviews
            or not isinstance(verified_reviews, int)
            or verified_reviews < 0
            or verified_reviews > completed_reviews
            or evidence_mode
            not in {
                (
                    "coordinator_signed_registry_and_assignment_plus_"
                    "individually_signed_reviews"
                ),
                (
                    "legacy_unsigned_csv_without_signer_identity_"
                    "verification"
                ),
            }
            or not isinstance(
                group.get("legacy_csv_is_promotion_evidence"), bool
            )
            or group.get("runtime_admitted") is not False
            or ranked_lineage.get("relation")
            not in {
                "not_in_current_ranked_slate",
                "partial_source_documents_in_current_ranked_slate",
            }
            or not isinstance(ranked_lineage.get("record_ids"), list)
            or census_lineage.get("relation")
            not in {
                "all_source_documents_present_in_census",
                "partial_source_documents_present_in_census",
                "post_census_separate_acquisition",
            }
            or not isinstance(census_lineage.get("record_ids"), list)
        ):
            raise ValueError("review-packet group lineage or counts are invalid")
        expected_evidence_mode = {
            "Alberta": (
                "coordinator_signed_registry_and_assignment_plus_"
                "individually_signed_reviews"
            ),
            "Manitoba": (
                "coordinator_signed_registry_and_assignment_plus_"
                "individually_signed_reviews"
            ),
            "British Columbia": (
                "coordinator_signed_registry_and_assignment_plus_"
                "individually_signed_reviews"
            ),
        }.get(group.get("jurisdiction"))
        if (
            evidence_mode != expected_evidence_mode
            or group["legacy_csv_is_promotion_evidence"]
            != (
                evidence_mode
                == "legacy_unsigned_csv_without_signer_identity_verification"
            )
        ):
            raise ValueError("review-packet evidence mode is inconsistent")
        if (
            ranked_lineage["relation"] == "not_in_current_ranked_slate"
            and ranked_lineage["record_ids"]
        ) or (
            ranked_lineage["relation"]
            == "partial_source_documents_in_current_ranked_slate"
            and (
                not ranked_lineage["record_ids"]
                or not set(ranked_lineage["record_ids"]).issubset(
                    set(census_lineage["record_ids"])
                )
            )
        ):
            raise ValueError("review-packet ranked lineage relation is invalid")
        if group.get("independent_review_cleared") != (
            verified_reviews == required_reviews
        ):
            raise ValueError("review-packet independent-clearance state is stale")
        internal_fidelity = group.get("internal_source_fidelity_review")
        minimum_repaired_candidates = (
            0 if group.get("jurisdiction") == "British Columbia" else 1
        )
        if (
            group.get("jurisdiction")
            in {"Alberta", "British Columbia", "Manitoba"}
            and internal_fidelity is None
        ):
            raise ValueError(
                "review-packet internal source-fidelity state is missing"
            )
        if internal_fidelity is not None and (
            not isinstance(internal_fidelity, dict)
            or internal_fidelity.get("classification")
            not in {
                (
                    "development_side_pdf_fidelity_review_not_independent_"
                    "agronomic_review"
                ),
                (
                    "development_side_source_fidelity_review_not_independent_"
                    "agronomic_review"
                ),
                (
                    "development_side_legal_source_fidelity_review_not_"
                    "independent_professional_review"
                ),
            }
            or internal_fidelity.get("external_review_credit") is not False
            or not isinstance(
                internal_fidelity.get(
                    "source_pages_rendered_and_visually_checked"
                ),
                int,
            )
            or internal_fidelity[
                "source_pages_rendered_and_visually_checked"
            ]
            < 0
            or not isinstance(
                internal_fidelity.get("source_html_snapshots_checked", 0),
                int,
            )
            or internal_fidelity.get("source_html_snapshots_checked", 0) < 0
            or (
                internal_fidelity[
                    "source_pages_rendered_and_visually_checked"
                ]
                + internal_fidelity.get("source_html_snapshots_checked", 0)
                < 1
            )
            or not isinstance(
                internal_fidelity.get("repaired_candidate_count"), int
            )
            or internal_fidelity["repaired_candidate_count"]
            < minimum_repaired_candidates
            or not isinstance(internal_fidelity.get("decision"), str)
            or not internal_fidelity["decision"]
        ):
            raise ValueError(
                "review-packet internal source-fidelity state is unsafe"
            )
        validation_manifest = group.get("validation_manifest") or {}
        if (
            not isinstance(validation_manifest.get("path"), str)
            or not validation_manifest["path"].startswith("docs/")
            or not isinstance(validation_manifest.get("sha256"), str)
            or len(validation_manifest["sha256"]) != 64
        ):
            raise ValueError("review-packet validation manifest is incomplete")
        validation_manifest_path = repo_path(validation_manifest["path"]).resolve()
        if (
            not validation_manifest_path.is_file()
            or _sha256(validation_manifest_path)
            != validation_manifest["sha256"]
        ):
            raise ValueError("review-packet validation manifest hash mismatch")
        candidate_artifacts = candidates.get("artifacts")
        if candidate_artifacts is None:
            candidate_artifacts = [
                {
                    "path": candidates.get("path"),
                    "sha256": candidates.get("sha256"),
                    "count": candidates.get("count"),
                }
            ]
        if (
            not isinstance(candidate_artifacts, list)
            or not candidate_artifacts
            or sum(
                artifact.get("count", -1)
                for artifact in candidate_artifacts
                if isinstance(artifact, dict)
            )
            != candidates["count"]
        ):
            raise ValueError("review-packet candidate artifacts are invalid")
        for artifact in candidate_artifacts:
            if (
                not isinstance(artifact, dict)
                or not isinstance(artifact.get("path"), str)
                or not artifact["path"].startswith("docs/")
                or not isinstance(artifact.get("sha256"), str)
                or len(artifact["sha256"]) != 64
                or not isinstance(artifact.get("count"), int)
                or artifact["count"] < 1
            ):
                raise ValueError("review-packet candidate artifact is incomplete")
            artifact_path = repo_path(artifact["path"]).resolve()
            if (
                not artifact_path.is_file()
                or _sha256(artifact_path) != artifact["sha256"]
            ):
                raise ValueError("review-packet candidate artifact hash mismatch")
        validation_manifests = group.get("validation_manifests")
        if validation_manifests is not None:
            if (
                not isinstance(validation_manifests, list)
                or not validation_manifests
                or sum(
                    item.get("candidate_count", -1)
                    for item in validation_manifests
                    if isinstance(item, dict)
                )
                != candidates["count"]
            ):
                raise ValueError("review-packet validation manifests are invalid")
            for item in validation_manifests:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("path"), str)
                    or not item["path"].startswith("docs/")
                    or not isinstance(item.get("sha256"), str)
                    or len(item["sha256"]) != 64
                    or not isinstance(item.get("candidate_count"), int)
                    or item["candidate_count"] < 1
                ):
                    raise ValueError("review-packet validation manifest is incomplete")
                manifest_path = repo_path(item["path"]).resolve()
                if (
                    not manifest_path.is_file()
                    or _sha256(manifest_path) != item["sha256"]
                ):
                    raise ValueError("review-packet validation manifest hash mismatch")
        for document in documents:
            if (
                not isinstance(document.get("source_id"), str)
                or not document["source_id"]
                or not isinstance(document.get("title"), str)
                or not document["title"]
                or not isinstance(document.get("download_url"), str)
                or not document["download_url"].startswith("https://")
                or not isinstance(document.get("sha256"), str)
                or len(document["sha256"]) != 64
                or not isinstance(document.get("licence"), str)
                or not document["licence"]
                or not isinstance(document.get("licence_url"), str)
                or not document["licence_url"].startswith("https://")
                or not isinstance(document.get("local_path"), str)
                or not document["local_path"].startswith("data/")
                or document.get("packaged_in_runtime") is not False
            ):
                raise ValueError("review-packet source document is incomplete")
            local_path = repo_path(document["local_path"]).resolve()
            if local_path.exists() and (
                not local_path.is_file()
                or _sha256(local_path) != document["sha256"]
            ):
                raise ValueError("review-packet source document hash mismatch")
    expected_summary = {
        "prepared_packet_groups": len(groups),
        "source_documents": sum(row["source_document_count"] for row in groups),
        "candidate_summaries": sum(row["candidates"]["count"] for row in groups),
        "required_independent_reviews": sum(
            row["required_independent_reviews"] for row in groups
        ),
        "completed_independent_reviews": sum(
            row["completed_independent_reviews"] for row in groups
        ),
        "cryptographically_verified_reviews": sum(
            row["cryptographically_verified_reviews"] for row in groups
        ),
        "independent_review_cleared_packet_groups": sum(
            row["independent_review_cleared"] for row in groups
        ),
        "admitted_packet_groups": sum(row["runtime_admitted"] for row in groups),
    }
    if payload.get("summary") != expected_summary:
        raise ValueError("review-packet registry summary is stale")


def _review_packet_presentation(group: dict[str, Any]) -> dict[str, Any]:
    signed = (
        group["review_evidence_mode"]
        == (
            "coordinator_signed_registry_and_assignment_plus_"
            "individually_signed_reviews"
        )
    )
    lines = [
        (
            f"{group['source_document_count']} source docs · "
            f"{group['candidates']['count']} candidates quarantined · 0 admitted"
        ),
        (
            "Review evidence: signed reviewer registry, frozen assignments, and "
            "individual signatures required"
            if signed
            else (
                "Review evidence: legacy unsigned CSV; signer identity is not "
                "cryptographically verified"
            )
        ),
        "Internal fidelity checked; no external review credit",
        (
            "Census lineage: "
            f"{group['census_lineage']['relation'].replace('_', ' ')}"
        ),
        (
            "Ranked-slate lineage: "
            f"{group['ranked_slate_lineage']['relation'].replace('_', ' ')}"
        ),
    ]
    return {
        **group,
        "display_lines": lines,
        "promotion_warning": (
            None
            if signed
            else (
                "Promotion warning: this legacy path accepts unsigned review rows "
                "and does not provide equivalent identity assurance."
            )
        ),
    }


def _validate_french_source_disposition(
    payload: dict[str, Any],
    *,
    discovery: dict[str, Any],
    slate_sha256: str,
) -> None:
    if (
        payload.get("schema_version")
        != "open_agronomy_agent.french_applied_guidance_source_disposition.v2"
        or payload.get("status")
        != "blocked_pending_written_permission_and_downstream_review"
    ):
        raise ValueError("unsupported French source disposition")
    if (payload.get("slate") or {}).get("sha256") != slate_sha256:
        raise ValueError("French source disposition slate hash is stale")

    french_slate_records = {
        str(row["record_id"]): row
        for row in discovery["candidates"]
        if row["language"] == "fr-CA"
    }
    all_slate_record_ids = {
        str(row["record_id"]) for row in discovery["candidates"]
    }
    records = payload.get("records")
    families = payload.get("source_families")
    if not isinstance(records, list) or not isinstance(families, list):
        raise ValueError("French source disposition records are invalid")
    disposition_by_id = {str(row.get("record_id") or ""): row for row in records}
    if (
        len(disposition_by_id) != len(records)
        or set(disposition_by_id) != set(french_slate_records)
    ):
        raise ValueError(
            "French source disposition must exactly match ranked French records"
        )
    for record_id, row in disposition_by_id.items():
        slate_row = french_slate_records[record_id]
        if (
            row.get("source_family_id") in {None, ""}
            or row.get("jurisdiction") != slate_row["jurisdiction"]
            or row.get("language") != "fr-CA"
            or row.get("title") != slate_row["title"]
            or row.get("url") != slate_row["url"]
            or row.get("slate_state") != "discovered_not_admitted"
            or row.get("runtime_admitted") is not False
        ):
            raise ValueError("French source disposition record binding is invalid")

    family_ids = [row.get("source_family_id") for row in families]
    if (
        not families
        or any(not isinstance(value, str) or not value for value in family_ids)
        or len(family_ids) != len(set(family_ids))
    ):
        raise ValueError("French source-family identifiers are invalid")
    family_record_ids: list[str] = []
    for family in families:
        record_ids = family.get("record_ids")
        mode = family.get("operating_mode") or {}
        permission = family.get("permission_request") or {}
        admission = family.get("admission") or {}
        rights_evidence = family.get("rights_evidence")
        source_access = family.get("source_access")
        has_source_access = isinstance(source_access, dict)
        access_blocked = has_source_access and (
            source_access.get("source_asset_access_blocked") is True
        )
        recovered_source = has_source_access and (
            source_access.get("source_asset_access_blocked") is False
        )
        if (
            not isinstance(record_ids, list)
            or not record_ids
            or any(
                disposition_by_id.get(record_id, {}).get("source_family_id")
                != family["source_family_id"]
                for record_id in record_ids
            )
            or mode.get("connected_link_only_reference")
            is not (not has_source_access)
            or mode.get("network_required") is not True
            or mode.get("project_managed_offline_source_copy") is not False
            or mode.get("project_managed_extracted_or_vector_index") is not False
            or mode.get("packaged_offline_source_distribution") is not False
            or mode.get("packaged_offline_derived_distribution") is not False
            or mode.get("commercial_distribution") is not False
            or permission.get("status")
            != (
                "withheld_pending_source_access"
                if access_blocked
                else (
                    "withheld_after_exact_source_preflight"
                    if recovered_source
                    else "not_submitted"
                )
            )
            or permission.get("response_state") != "none"
            or not isinstance(permission.get("submission_route"), str)
            or not permission["submission_route"].startswith("https://")
            or not isinstance(permission.get("requested_rights"), list)
            or len(permission["requested_rights"]) < 1
            or admission.get("rights_gate_cleared") is not False
            or admission.get("content_frozen") is not recovered_source
            or admission.get("independent_agronomic_review_cleared") is not False
            or admission.get("disjoint_evaluation_cleared") is not False
            or admission.get("runtime_admitted") is not False
            or not isinstance(rights_evidence, list)
            or not rights_evidence
            or any(
                not isinstance(evidence.get("url"), str)
                or not evidence["url"].startswith("https://")
                or not isinstance(evidence.get("finding"), str)
                or not evidence["finding"]
                for evidence in rights_evidence
            )
        ):
            raise ValueError("French source family escaped its rights gate")
        if has_source_access:
            receipt_path = source_access.get("receipt_path")
            receipt_sha256 = source_access.get("receipt_sha256")
            if (
                not isinstance(receipt_path, str)
                or not receipt_path.startswith(
                    "data/manifests/source_asset_access_receipts/"
                )
                or not isinstance(receipt_sha256, str)
                or len(receipt_sha256) != 64
                or not isinstance(
                    source_access.get("ranked_record_ids"), list
                )
                or not set(source_access["ranked_record_ids"]).issubset(
                    all_slate_record_ids
                )
            ):
                raise ValueError("French source-access receipt is invalid")
            if access_blocked and (
                source_access.get("status")
                != "blocked_official_asset_redirects_to_archive_interstitial"
                or source_access.get("exact_pdf_frozen") is not False
                or source_access.get("initial_http_status") != 307
                or source_access.get("followed_content_type") != "text/html"
                or not set(record_ids).issubset(
                    source_access["ranked_record_ids"]
                )
            ):
                raise ValueError("French source-access blocker is invalid")
            if recovered_source and (
                source_access.get("status")
                != (
                    "recovered_exact_official_bilingual_pdf_via_"
                    "archive_continuation"
                )
                or source_access.get("exact_pdf_frozen") is not True
                or not isinstance(
                    source_access.get("french_exact_record_ids"), list
                )
                or not source_access["french_exact_record_ids"]
                or not isinstance(
                    source_access.get("related_unresolved_record_ids"), list
                )
                or not set(source_access["french_exact_record_ids"]).issubset(
                    record_ids
                )
                or not set(
                    source_access["related_unresolved_record_ids"]
                ).issubset(record_ids)
                or (family.get("source_preflight") or {}).get("state")
                not in {
                    "rejected_for_actionable_review_packet",
                    "blocked_pending_rights_clarification",
                }
                or (family.get("source_preflight") or {}).get(
                    "currentness_gate_passed"
                )
                is not False
                or (family.get("source_preflight") or {}).get(
                    "runtime_admitted"
                )
                is not False
            ):
                raise ValueError("French recovered-source preflight is invalid")
            resolved_receipt = repo_path(receipt_path).resolve()
            if (
                not resolved_receipt.is_file()
                or _sha256(resolved_receipt) != receipt_sha256
            ):
                raise ValueError("French source-access receipt hash mismatch")
            receipt = _read_json(resolved_receipt)
            if (
                receipt.get("ranked_record_ids")
                != source_access["ranked_record_ids"]
            ):
                raise ValueError(
                    "French source-access receipt record binding mismatch"
                )
        family_record_ids.extend(record_ids)
    if (
        len(family_record_ids) != len(set(family_record_ids))
        or set(family_record_ids) != set(disposition_by_id)
    ):
        raise ValueError("French source-family record membership is invalid")

    lawful_lane = payload.get("existing_lawful_translation_lane") or {}
    if (
        lawful_lane.get("candidate_count") != 6
        or lawful_lane.get("runtime_admitted") is not False
        or "not descendants" not in str(lawful_lane.get("relationship") or "")
        or not isinstance(lawful_lane.get("path"), str)
        or not lawful_lane["path"].startswith("docs/")
        or not isinstance(lawful_lane.get("sha256"), str)
        or len(lawful_lane["sha256"]) != 64
        or not isinstance(lawful_lane.get("candidate_path"), str)
        or not lawful_lane["candidate_path"].startswith("docs/")
        or not isinstance(lawful_lane.get("candidate_sha256"), str)
        or len(lawful_lane["candidate_sha256"]) != 64
    ):
        raise ValueError("French lawful translation lane relation is invalid")
    lawful_manifest_path = repo_path(lawful_lane["path"]).resolve()
    lawful_candidate_path = repo_path(lawful_lane["candidate_path"]).resolve()
    if (
        not lawful_manifest_path.is_file()
        or _sha256(lawful_manifest_path) != lawful_lane["sha256"]
        or not lawful_candidate_path.is_file()
        or _sha256(lawful_candidate_path)
        != lawful_lane["candidate_sha256"]
    ):
        raise ValueError("French lawful translation lane hash mismatch")
    expected_summary = {
        "ranked_french_records": len(records),
        "unique_source_families": len(families),
        "federal_records": sum(
            row["jurisdiction"] == "Canada" for row in records
        ),
        "quebec_records": sum(
            row["jurisdiction"] == "Quebec" for row in records
        ),
        "permission_requests_not_submitted": sum(
            row["permission_request"]["status"] == "not_submitted"
            for row in families
        ),
        "permission_requests_withheld_pending_source_access": sum(
            row["permission_request"]["status"]
            == "withheld_pending_source_access"
            for row in families
        ),
        "permission_requests_withheld_after_exact_source_preflight": sum(
            row["permission_request"]["status"]
            == "withheld_after_exact_source_preflight"
            for row in families
        ),
        "connected_link_only_families": sum(
            row["operating_mode"]["connected_link_only_reference"]
            for row in families
        ),
        "source_asset_access_blocked_families": sum(
            (row.get("source_access") or {}).get(
                "source_asset_access_blocked"
            )
            is True
            for row in families
        ),
        "exact_byte_currentness_rejected_families": sum(
            (row.get("source_preflight") or {}).get("state")
            == "rejected_for_actionable_review_packet"
            for row in families
        ),
        "exact_byte_rights_blocked_families": sum(
            (row.get("source_preflight") or {}).get("state")
            == "blocked_pending_rights_clarification"
            for row in families
        ),
        "packaged_offline_families": 0,
        "runtime_admitted_families": 0,
    }
    if payload.get("summary") != expected_summary:
        raise ValueError("French source disposition summary is stale")


def _validate_source_preflight_registry(
    payload: dict[str, Any],
    *,
    discovery: dict[str, Any],
    slate_sha256: str,
) -> None:
    if (
        payload.get("schema_version")
        != "open_agronomy_agent.applied_guidance_source_preflight_registry.v1"
        or payload.get("status") != "current_preflight_decisions_recorded"
    ):
        raise ValueError("unsupported source-preflight registry")
    if (payload.get("slate") or {}).get("sha256") != slate_sha256:
        raise ValueError("source-preflight registry slate hash is stale")
    preflights = payload.get("preflights")
    if not isinstance(preflights, list) or not preflights:
        raise ValueError("source-preflight registry has no preflights")
    ranked_by_id = {
        str(row["record_id"]): row for row in discovery["candidates"]
    }
    seen_preflights: set[str] = set()
    seen_records: set[str] = set()
    for row in preflights:
        preflight_id = row.get("preflight_id")
        record_ids = row.get("record_ids")
        source = row.get("source") or {}
        rights = row.get("rights") or {}
        disposition = row.get("disposition") or {}
        has_local_source = (
            isinstance(source.get("local_path"), str)
            and source["local_path"].startswith("data/raw/")
        )
        review_receipt = source.get("review_receipt") or {}
        has_receipt_only_source = (
            source.get("local_path") is None
            and isinstance(review_receipt, dict)
            and isinstance(review_receipt.get("path"), str)
            and review_receipt["path"].startswith(
                "data/manifests/source_rights_currentness_receipts/"
            )
            and isinstance(review_receipt.get("sha256"), str)
            and len(review_receipt["sha256"]) == 64
            and review_receipt.get("review_mode")
            == "temporary_exact_asset_review_no_project_managed_source_copy_retained"
        )
        if (
            not isinstance(preflight_id, str)
            or not preflight_id
            or preflight_id in seen_preflights
            or not isinstance(record_ids, list)
            or not record_ids
            or any(
                not isinstance(record_id, str)
                or record_id not in ranked_by_id
                or record_id in seen_records
                for record_id in record_ids
            )
            or not (has_local_source or has_receipt_only_source)
            or not isinstance(source.get("sha256"), str)
            or len(source["sha256"]) != 64
            or not isinstance(source.get("bytes"), int)
            or source["bytes"] < 1
            or not isinstance(source.get("pages"), int)
            or source["pages"] < 1
            or source.get("packaged_in_runtime") is not False
            or source.get("private_source_copy_required_at_runtime") is not False
            or disposition.get("state")
            not in {
                "advanced_to_review_packet",
                "rejected_for_actionable_review_packet",
                "blocked_pending_rights_clarification",
            }
            or disposition.get("runtime_admitted") is not False
            or not isinstance(
                disposition.get("candidate_summaries_prepared"), int
            )
            or disposition["candidate_summaries_prepared"] < 0
            or not isinstance(rights.get("evidence_url"), str)
            or not rights["evidence_url"].startswith("https://")
        ):
            raise ValueError("source preflight escaped its gate or lineage")
        if has_local_source:
            local_path = repo_path(source["local_path"]).resolve()
            if local_path.exists() and (
                not local_path.is_file()
                or local_path.stat().st_size != source["bytes"]
                or _sha256(local_path) != source["sha256"]
            ):
                raise ValueError("source-preflight frozen source hash or size mismatch")
        else:
            receipt_path = repo_path(review_receipt["path"]).resolve()
            exact_assets = source.get("exact_assets")
            if (
                not receipt_path.is_file()
                or _sha256(receipt_path) != review_receipt["sha256"]
                or not isinstance(exact_assets, list)
                or len(exact_assets) < 2
                or any(
                    not isinstance(asset, dict)
                    or asset.get("retained_in_repository") is not False
                    or not isinstance(asset.get("language"), str)
                    or not asset["language"]
                    or not isinstance(asset.get("landing_url"), str)
                    or not asset["landing_url"].startswith("https://")
                    or not isinstance(asset.get("download_url"), str)
                    or not asset["download_url"].startswith("https://")
                    or not isinstance(asset.get("sha256"), str)
                    or len(asset["sha256"]) != 64
                    or not isinstance(asset.get("bytes"), int)
                    or asset["bytes"] < 1
                    or not isinstance(asset.get("pages"), int)
                    or asset["pages"] < 1
                    for asset in exact_assets
                )
            ):
                raise ValueError(
                    "source-preflight receipt-only asset lineage is incomplete"
                )
        language_assets = source.get("language_assets")
        if language_assets is not None:
            if (
                not isinstance(language_assets, list)
                or len(language_assets) < 2
            ):
                raise ValueError(
                    "source-preflight language-asset lineage is incomplete"
                )
            seen_languages: set[str] = set()
            primary_assets = 0
            for asset in language_assets:
                if (
                    not isinstance(asset, dict)
                    or not isinstance(asset.get("language"), str)
                    or not asset["language"]
                    or asset["language"] in seen_languages
                    or not isinstance(asset.get("role"), str)
                    or not asset["role"]
                    or not isinstance(asset.get("url"), str)
                    or not asset["url"].startswith("https://")
                    or not isinstance(asset.get("local_path"), str)
                    or not asset["local_path"].startswith("data/raw/")
                    or not isinstance(asset.get("sha256"), str)
                    or len(asset["sha256"]) != 64
                    or not isinstance(asset.get("bytes"), int)
                    or asset["bytes"] < 1
                    or not isinstance(asset.get("pages"), int)
                    or asset["pages"] < 1
                    or asset.get("media_type") != "application/pdf"
                    or asset.get("encrypted") is not False
                ):
                    raise ValueError(
                        "source-preflight language-asset lineage is incomplete"
                    )
                seen_languages.add(asset["language"])
                if asset["role"] == "primary_ranked_edition":
                    primary_assets += 1
                    if (
                        asset["local_path"] != source["local_path"]
                        or asset["sha256"] != source["sha256"]
                        or asset["bytes"] != source["bytes"]
                        or asset["pages"] != source["pages"]
                    ):
                        raise ValueError(
                            "source-preflight primary language asset drifted"
                        )
                asset_path = repo_path(asset["local_path"]).resolve()
                if asset_path.exists() and (
                    not asset_path.is_file()
                    or asset_path.stat().st_size != asset["bytes"]
                    or _sha256(asset_path) != asset["sha256"]
                ):
                    raise ValueError(
                        "source-preflight language-asset hash or size mismatch"
                    )
            if primary_assets != 1:
                raise ValueError(
                    "source-preflight language assets need one primary edition"
                )
        catalog_snapshot_path = source.get("catalog_snapshot_path")
        catalog_snapshot_sha256 = source.get("catalog_snapshot_sha256")
        if catalog_snapshot_path is not None or catalog_snapshot_sha256 is not None:
            if (
                not isinstance(catalog_snapshot_path, str)
                or not catalog_snapshot_path.startswith("data/raw/")
                or not isinstance(catalog_snapshot_sha256, str)
                or len(catalog_snapshot_sha256) != 64
            ):
                raise ValueError(
                    "source-preflight catalog snapshot lineage is incomplete"
                )
            resolved_catalog_path = repo_path(catalog_snapshot_path).resolve()
            if resolved_catalog_path.exists() and (
                not resolved_catalog_path.is_file()
                or _sha256(resolved_catalog_path) != catalog_snapshot_sha256
            ):
                raise ValueError(
                    "source-preflight catalog snapshot hash mismatch"
                )
        regulatory_snapshot = source.get("regulatory_registry_snapshot")
        if regulatory_snapshot is not None:
            if (
                not isinstance(regulatory_snapshot, dict)
                or not isinstance(regulatory_snapshot.get("local_path"), str)
                or not regulatory_snapshot["local_path"].startswith("data/raw/")
                or not isinstance(regulatory_snapshot.get("sha256"), str)
                or len(regulatory_snapshot["sha256"]) != 64
                or not isinstance(regulatory_snapshot.get("bytes"), int)
                or regulatory_snapshot["bytes"] < 1
                or not isinstance(regulatory_snapshot.get("records"), int)
                or regulatory_snapshot["records"] < 1
                or not isinstance(regulatory_snapshot.get("url"), str)
                or not regulatory_snapshot["url"].startswith("https://")
            ):
                raise ValueError(
                    "source-preflight regulatory snapshot lineage is incomplete"
                )
            regulatory_snapshot_path = repo_path(
                regulatory_snapshot["local_path"]
            ).resolve()
            if regulatory_snapshot_path.exists() and (
                not regulatory_snapshot_path.is_file()
                or regulatory_snapshot_path.stat().st_size
                != regulatory_snapshot["bytes"]
                or _sha256(regulatory_snapshot_path)
                != regulatory_snapshot["sha256"]
            ):
                raise ValueError(
                    "source-preflight regulatory snapshot hash or size mismatch"
                )
        regulatory_reconciliation_snapshots = source.get(
            "regulatory_reconciliation_snapshots"
        )
        if regulatory_reconciliation_snapshots is not None:
            if (
                not isinstance(regulatory_reconciliation_snapshots, list)
                or not regulatory_reconciliation_snapshots
            ):
                raise ValueError(
                    "source-preflight regulatory reconciliation lineage "
                    "is incomplete"
                )
            seen_reconciliation_roles: set[str] = set()
            for snapshot in regulatory_reconciliation_snapshots:
                if (
                    not isinstance(snapshot, dict)
                    or not isinstance(snapshot.get("role"), str)
                    or not snapshot["role"]
                    or snapshot["role"] in seen_reconciliation_roles
                    or not isinstance(snapshot.get("local_path"), str)
                    or not snapshot["local_path"].startswith("data/raw/")
                    or not isinstance(snapshot.get("sha256"), str)
                    or len(snapshot["sha256"]) != 64
                    or not isinstance(snapshot.get("bytes"), int)
                    or snapshot["bytes"] < 1
                    or not isinstance(snapshot.get("rows"), int)
                    or snapshot["rows"] < 1
                    or not isinstance(snapshot.get("encoding"), str)
                    or not snapshot["encoding"]
                    or not isinstance(snapshot.get("licence"), str)
                    or not snapshot["licence"]
                    or not isinstance(snapshot.get("reviewed_on"), str)
                    or not snapshot["reviewed_on"]
                    or not isinstance(snapshot.get("url"), str)
                    or not snapshot["url"].startswith("https://")
                ):
                    raise ValueError(
                        "source-preflight regulatory reconciliation lineage "
                        "is incomplete"
                    )
                seen_reconciliation_roles.add(snapshot["role"])
                snapshot_path = repo_path(snapshot["local_path"]).resolve()
                if snapshot_path.exists() and (
                    not snapshot_path.is_file()
                    or snapshot_path.stat().st_size != snapshot["bytes"]
                    or _sha256(snapshot_path) != snapshot["sha256"]
                ):
                    raise ValueError(
                        "source-preflight regulatory reconciliation hash or "
                        "size mismatch"
                    )
        current_authority_snapshots = source.get(
            "current_authority_snapshots"
        )
        if current_authority_snapshots is not None:
            if (
                not isinstance(current_authority_snapshots, list)
                or not current_authority_snapshots
            ):
                raise ValueError(
                    "source-preflight current-authority snapshot lineage is incomplete"
                )
            for snapshot in current_authority_snapshots:
                snapshot_has_local_copy = (
                    isinstance(snapshot, dict)
                    and isinstance(snapshot.get("local_path"), str)
                    and snapshot["local_path"].startswith("data/raw/")
                )
                snapshot_is_receipt_only = (
                    has_receipt_only_source
                    and isinstance(snapshot, dict)
                    and snapshot.get("local_path") is None
                    and snapshot.get("retained_in_repository") is False
                )
                if (
                    not isinstance(snapshot, dict)
                    or not (
                        snapshot_has_local_copy or snapshot_is_receipt_only
                    )
                    or not isinstance(snapshot.get("sha256"), str)
                    or len(snapshot["sha256"]) != 64
                    or not isinstance(snapshot.get("bytes"), int)
                    or snapshot["bytes"] < 1
                    or not isinstance(snapshot.get("url"), str)
                    or not snapshot["url"].startswith("https://")
                    or not isinstance(snapshot.get("reviewed_on"), str)
                    or not snapshot["reviewed_on"]
                    or not isinstance(snapshot.get("last_updated"), str)
                    or not snapshot["last_updated"]
                ):
                    raise ValueError(
                        "source-preflight current-authority snapshot lineage "
                        "is incomplete"
                    )
                if snapshot_has_local_copy:
                    snapshot_path = repo_path(snapshot["local_path"]).resolve()
                    if snapshot_path.exists() and (
                        not snapshot_path.is_file()
                        or snapshot_path.stat().st_size != snapshot["bytes"]
                        or _sha256(snapshot_path) != snapshot["sha256"]
                    ):
                        raise ValueError(
                            "source-preflight current-authority snapshot hash or "
                            "size mismatch"
                        )
        if disposition["state"] == "rejected_for_actionable_review_packet":
            rejected_role = disposition.get("allowed_role")
            if (
                rejected_role
                not in {
                    "historical_or_background_reference_candidate_only",
                    "connected_live_calculator_route_only_no_offline_emulation",
                    (
                        "historical_identification_and_ipm_background_candidate_"
                        "only_no_threshold_or_pesticide_selection_use"
                    ),
                }
                or disposition["candidate_summaries_prepared"] != 0
                or (
                    rejected_role
                    in {
                        "historical_or_background_reference_candidate_only",
                        (
                            "historical_identification_and_ipm_background_candidate_"
                            "only_no_threshold_or_pesticide_selection_use"
                        ),
                    }
                    and disposition.get("currentness_gate_passed") is not False
                )
                or (
                    rejected_role
                    == "connected_live_calculator_route_only_no_offline_emulation"
                    and (
                        disposition.get("currentness_gate_passed") is not True
                        or disposition.get(
                            "rights_gate_passed_for_bounded_derivatives"
                        )
                        is not False
                    )
                )
            ):
                raise ValueError("rejected source preflight has an unsafe role")
        if disposition["state"] == "blocked_pending_rights_clarification" and (
            disposition.get("rights_gate_passed_for_bounded_derivatives") is not False
            or not isinstance(
                disposition.get("currentness_gate_passed"), bool
            )
            or disposition.get("allowed_role")
            not in {
                "connected_reference_only_pending_multi_owner_review",
                "connected_reference_and_private_preflight_evidence_only",
                "connected_secondary_reference_and_regulatory_lookup_lead_only",
                "connected_catalogue_reference_only_no_actionable_claim_use",
                (
                    "exact_preflight_evidence_and_connected_nonchemical_"
                    "identification_monitoring_candidate_only_no_threshold_"
                    "or_pesticide_use"
                ),
                (
                    "exact_preflight_evidence_and_connected_historical_"
                    "identification_background_only_no_threshold_treatment_"
                    "timing_or_pesticide_use"
                ),
                (
                    "bilingual_connected_background_and_current_ontario_tool_"
                    "router_only_no_offline_rates_or_handbook_derived_answers"
                ),
            }
            or disposition["candidate_summaries_prepared"] != 0
        ):
            raise ValueError("rights-blocked source preflight has an unsafe role")
        if disposition["state"] == "advanced_to_review_packet":
            review_packet = row.get("review_packet") or {}
            packet_path_value = review_packet.get("path")
            candidate_path_value = review_packet.get("candidate_path")
            if (
                disposition.get("currentness_gate_passed") is not True
                or disposition.get("allowed_role")
                not in {
                    "quarantined_bounded_field_observation_candidate",
                    "quarantined_bounded_monitoring_candidate",
                    "quarantined_bounded_regulatory_navigation_candidate",
                }
                or disposition["candidate_summaries_prepared"] < 1
                or not isinstance(packet_path_value, str)
                or not packet_path_value.startswith("docs/")
                or not isinstance(candidate_path_value, str)
                or not candidate_path_value.startswith("docs/")
                or not isinstance(review_packet.get("sha256"), str)
                or len(review_packet["sha256"]) != 64
                or not isinstance(review_packet.get("candidate_sha256"), str)
                or len(review_packet["candidate_sha256"]) != 64
                or review_packet.get("candidate_count")
                != disposition["candidate_summaries_prepared"]
                or not isinstance(
                    review_packet.get("required_independent_reviews"), int
                )
                or review_packet["required_independent_reviews"]
                < review_packet["candidate_count"]
                or review_packet.get("completed_independent_reviews") != 0
            ):
                raise ValueError("advanced source preflight review packet is unsafe")
            packet_path = repo_path(packet_path_value).resolve()
            candidate_path = repo_path(candidate_path_value).resolve()
            if (
                not packet_path.is_file()
                or _sha256(packet_path) != review_packet["sha256"]
                or not candidate_path.is_file()
                or _sha256(candidate_path)
                != review_packet["candidate_sha256"]
            ):
                raise ValueError("advanced source preflight packet hash mismatch")
        seen_preflights.add(preflight_id)
        seen_records.update(record_ids)
    expected_summary = {
        "preflighted_source_families": len(preflights),
        "ranked_records_resolved": len(seen_records),
        "advanced_to_review_packet": sum(
            row["disposition"]["state"] == "advanced_to_review_packet"
            for row in preflights
        ),
        "rejected_for_actionable_review_packet": sum(
            row["disposition"]["state"]
            == "rejected_for_actionable_review_packet"
            for row in preflights
        ),
        "blocked_pending_rights_clarification": sum(
            row["disposition"]["state"]
            == "blocked_pending_rights_clarification"
            for row in preflights
        ),
        "runtime_admitted": 0,
    }
    if payload.get("summary") != expected_summary:
        raise ValueError("source-preflight registry summary is stale")


def _applied_discovery_source_leads(
    payload: dict[str, Any],
    *,
    preflights: list[dict[str, Any]] | None = None,
    french_source_families: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates = payload["candidates"]
    barriers = payload["access_barriers"]
    preflight_by_record_id = {
        record_id: {
            "preflight_id": row["preflight_id"],
            "source_family_id": row["source_family_id"],
            "disposition": row["disposition"]["state"],
            "allowed_role": row["disposition"]["allowed_role"],
            "reason": row["disposition"]["reason"],
            "next_gate": row["next_gate"],
            "reviewed_source_title": row["source"]["title"],
            "title_correction": next(
                (
                    ranked_record.get("title_correction")
                    for ranked_record in row.get("slate_binding", [])
                    if ranked_record.get("record_id") == record_id
                ),
                None,
            ),
            "runtime_admitted": False,
        }
        for row in (preflights or [])
        for record_id in row["record_ids"]
    }
    source_access_family_by_record_id = {
        record_id: family
        for family in (french_source_families or [])
        if isinstance(family.get("source_access"), dict)
        for record_id in family["source_access"].get(
            "ranked_record_ids", family["record_ids"]
        )
    }
    summaries = {
        row["jurisdiction"]: row for row in payload["jurisdictions"]
    }
    result: list[dict[str, Any]] = []
    for jurisdiction in DISCOVERY_JURISDICTIONS:
        summary = summaries[jurisdiction]
        jurisdiction_candidates = [
            row for row in candidates if row["jurisdiction"] == jurisdiction
        ]
        jurisdiction_barriers = [
            row for row in barriers if row["jurisdiction"] == jurisdiction
        ]
        selected: list[dict[str, Any]] = []
        preflight_source_families: set[str] = set()
        for row in jurisdiction_candidates:
            if row["record_id"] not in preflight_by_record_id:
                continue
            access_family = source_access_family_by_record_id.get(
                row["record_id"]
            )
            access_family_id = (
                str(access_family["source_family_id"])
                if access_family is not None
                else ""
            )
            if access_family_id and access_family_id in preflight_source_families:
                continue
            selected.append(row)
            if access_family_id:
                preflight_source_families.add(access_family_id)
            if len(selected) >= DISCOVERY_LEADS_PER_JURISDICTION:
                break
        selected_ids = {row["record_id"] for row in selected}
        selected_access_families = {
            source_access_family_by_record_id[row["record_id"]][
                "source_family_id"
            ]
            for row in selected
            if row["record_id"] in source_access_family_by_record_id
        }
        for row in jurisdiction_candidates:
            access_family = source_access_family_by_record_id.get(
                row["record_id"]
            )
            if (
                len(selected) >= DISCOVERY_LEADS_PER_JURISDICTION
                or access_family is None
                or row["record_id"] in selected_ids
                or access_family["source_family_id"]
                in selected_access_families
            ):
                continue
            selected.append(row)
            selected_ids.add(row["record_id"])
            selected_access_families.add(access_family["source_family_id"])
        selected.extend(
            row
            for row in jurisdiction_candidates
            if row["record_id"] not in selected_ids
        )
        selected = selected[:DISCOVERY_LEADS_PER_JURISDICTION]
        if not selected:
            selected = jurisdiction_barriers[:1]
        result.append(
            {
                "jurisdiction": jurisdiction,
                "candidate_count": int(summary["candidate_count"]),
                "access_barrier_count": int(summary["access_barrier_count"]),
                "gaps": list(summary["gaps"]),
                "leads": [
                    {
                        "record_id": row["record_id"],
                        "title": (
                            preflight_by_record_id.get(
                                row["record_id"], {}
                            ).get("reviewed_source_title")
                            or row["title"]
                        ),
                        "url": row["url"],
                        "language": row["language"],
                        "format": row.get("format") or "unknown",
                        "rights_lane": row["rights_lane"],
                        "currency_state": (
                            "exact_source_bytes_unavailable"
                            if (
                                source_access_family_by_record_id.get(
                                    row["record_id"], {}
                                ).get("source_access")
                                or {}
                            ).get("source_asset_access_blocked")
                            is True
                            else (
                                (
                                    "exact_source_bytes_recovered_"
                                    + (
                                        "rights_blocked"
                                        if (
                                            source_access_family_by_record_id.get(
                                                row["record_id"], {}
                                            ).get("source_preflight")
                                            or {}
                                        ).get("state")
                                        == "blocked_pending_rights_clarification"
                                        else "currentness_rejected"
                                    )
                                )
                                if (
                                    source_access_family_by_record_id.get(
                                        row["record_id"], {}
                                    ).get("source_access")
                                    or {}
                                ).get("source_asset_access_blocked")
                                is False
                                else (
                                    row.get("currency_state")
                                    or "publisher_access_blocked"
                                )
                            )
                        ),
                        "access_state": (
                            (
                                source_access_family_by_record_id.get(
                                    row["record_id"], {}
                                ).get("source_access")
                                or {}
                            ).get("status")
                            or row["access_state"]
                        ),
                        "access_barrier": (
                            row in jurisdiction_barriers
                            or (
                                source_access_family_by_record_id.get(
                                    row["record_id"], {}
                                ).get("source_access")
                                or {}
                            ).get("source_asset_access_blocked")
                            is True
                        ),
                        "source_asset_access_blocked": (
                            (
                                source_access_family_by_record_id.get(
                                    row["record_id"], {}
                                ).get("source_access")
                                or {}
                            )
                            .get("source_asset_access_blocked")
                        ),
                        "source_access": (
                            source_access_family_by_record_id.get(
                                row["record_id"], {}
                            ).get("source_access")
                        ),
                        "task_signals": list(row["applied_task_signals"]),
                        "required_next_gate": (
                            (
                                source_access_family_by_record_id.get(
                                    row["record_id"], {}
                                ).get("source_access")
                                or {}
                            ).get("required_next_gate")
                            or (
                                preflight_by_record_id.get(
                                    row["record_id"], {}
                                ).get("next_gate")
                            )
                            or row["required_next_gate"]
                        ),
                        "preflight": preflight_by_record_id.get(row["record_id"]),
                    }
                    for row in selected
                ],
            }
        )
    return result


def _validate_applied_eval_contract(
    payload: dict[str, Any],
    discovery_sha256: str,
) -> None:
    if payload.get("schema_version") != (
        "open_agronomy_agent.canadian_applied_guidance_admission_eval_contract.v1"
    ):
        raise ValueError("unsupported Canadian applied-guidance evaluation contract")
    if (
        payload.get("results_claimed") is not False
        or payload.get("runtime_admission_before_gate") is not False
        or payload.get("candidate_pool", {}).get("admitted_record_ids") != []
        or payload.get("inputs", {}).get("slate", {}).get("sha256")
        != discovery_sha256
        or payload.get("split_contract", {}).get(
            "candidate_source_families_may_not_supply_held_out_gold"
        )
        is not True
    ):
        raise ValueError("applied-guidance evaluation contract is unsafe or stale")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
