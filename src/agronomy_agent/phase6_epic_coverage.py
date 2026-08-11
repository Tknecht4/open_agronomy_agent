from __future__ import annotations

import csv
import json
import struct
import subprocess
from pathlib import Path
from typing import Any

from agronomy_agent.phase6_accessibility_primary_flows import (
    REQUIRED_AUDIT_RULES as REQUIRED_ACCESSIBILITY_AUDIT_RULES,
    REQUIRED_LAUNCH_GATE_EVIDENCE as REQUIRED_ACCESSIBILITY_LAUNCH_GATE_EVIDENCE,
    REQUIRED_LOW_BANDWIDTH_REASONS as REQUIRED_ACCESSIBILITY_LOW_BANDWIDTH_REASONS,
    REQUIRED_PRIMARY_FLOW_TEST_IDS as REQUIRED_ACCESSIBILITY_PRIMARY_FLOW_IDS,
    REQUIRED_SEMANTIC_COLOR_TOKENS as REQUIRED_ACCESSIBILITY_SEMANTIC_TOKEN_IDS,
)
from agronomy_agent.phase6_account_backlog import (
    EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE,
    EXPECTED_DEFERRED_FEATURES,
    EXPECTED_FEATURE_IDS,
    EXPECTED_IMPLEMENTED_FEATURES,
    EXPECTED_PHASE_BY_FEATURE,
    EXPECTED_PRIORITY_BY_FEATURE,
    EXPECTED_STATUS_BY_FEATURE,
)
from agronomy_agent.phase6_account_privacy_rights import (
    EXPECTED_CONTROL_EVIDENCE_BY_ID as EXPECTED_ACCOUNT_PRIVACY_CONTROL_EVIDENCE_BY_ID,
    EXPECTED_CONTROL_IDS as EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS,
    EXPECTED_CONTROL_STATUS_BY_ID as EXPECTED_ACCOUNT_PRIVACY_CONTROL_STATUS_BY_ID,
    REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION,
)
from agronomy_agent.phase6_admin_trace_access import (
    REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_ADMIN_TRACE_SNIPPETS_BY_SECTION,
)
from agronomy_agent.phase6_demo_assets import (
    EXPECTED_ASSET_ID_LIST as EXPECTED_DEMO_ASSET_ID_LIST,
    EXPECTED_ASSET_OWNER_ROLE_BY_ID as EXPECTED_DEMO_ASSET_OWNER_ROLE_BY_ID,
    EXPECTED_ASSET_PACKET_TEXT_BY_ID as EXPECTED_DEMO_ASSET_PACKET_TEXT_BY_ID,
    EXPECTED_ASSET_STATUS_BY_ID as EXPECTED_DEMO_ASSET_STATUS_BY_ID,
    EXPECTED_PUBLIC_PAGE_IDS as EXPECTED_DEMO_PUBLIC_PAGE_IDS,
    EXPECTED_SAMPLE_REPORT_TYPES as EXPECTED_DEMO_SAMPLE_REPORT_TYPES,
    REPORT_VERSION as PHASE6_DEMO_ASSETS_VERSION,
)
from agronomy_agent.phase6_external_links import (
    EXPECTED_LABEL_BY_LINK_ID,
    EXPECTED_LINK_IDS,
    EXPECTED_OWNER_ROLE_BY_LINK_ID as EXPECTED_EXTERNAL_LINK_OWNER_ROLE_BY_LINK_ID,
    EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID,
    EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID,
    EXPECTED_REQUIRED_BEFORE_BY_LINK_ID,
    PHASE6_EXTERNAL_LINKS_VERSION,
    REQUIRED_EVIDENCE_BY_LINK_ID as REQUIRED_EXTERNAL_LINK_EVIDENCE_BY_LINK_ID,
)
from agronomy_agent.phase6_frontend_bundle_budget import EXPECTED_BUNDLE_BUDGET_IDS
from agronomy_agent.phase6_frontend_performance_budget import (
    EXPECTED_FRONTEND_PERFORMANCE_BLOCKER_PACKET_METRIC_IDS,
    EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS,
    EXPECTED_FRONTEND_PERFORMANCE_EXCEPTION_IDS,
    EXPECTED_FRONTEND_PERFORMANCE_PACKET_METRIC_IDS,
)
from agronomy_agent.phase6_frontend_qa_matrix import (
    EXPECTED_BLOCKER_TEST_AREA_IDS,
    EXPECTED_MONITOR_TEST_AREA_IDS,
    EXPECTED_TEST_AREA_IDS,
)
from agronomy_agent.phase6_feedback_review import REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_FEEDBACK_SNIPPETS_BY_SECTION
from agronomy_agent.phase6_human_signoff_decisions import (
    EXPECTED_DECISION_IDS as EXPECTED_SIGNOFF_DECISION_IDS,
    EXPECTED_ITEM_TYPE_BY_DECISION as EXPECTED_SIGNOFF_ITEM_TYPE_BY_DECISION,
    EXPECTED_OWNER_ROLE_BY_DECISION as EXPECTED_SIGNOFF_OWNER_ROLE_BY_DECISION,
    EXPECTED_PRE_PROVIDER_STATUS_BY_DECISION as EXPECTED_SIGNOFF_PRE_PROVIDER_STATUS_BY_DECISION,
)
from agronomy_agent.phase6_launch_qa import (
    PHASE6_LAUNCH_QA_MIN_TURNS,
    PHASE6_LAUNCH_QA_PROBE_LABELS,
    PHASE6_LAUNCH_QA_VERSION,
)
from agronomy_agent.phase6_launch_gate_matrix import (
    EXPECTED_EVIDENCE_BY_GATE_ID as EXPECTED_LAUNCH_GATE_EVIDENCE_BY_GATE_ID,
    EXPECTED_LAUNCH_GATE_IDS,
    EXPECTED_STATUS_BY_GATE_ID,
    PHASE6_LAUNCH_GATE_MATRIX_VERSION,
)
from agronomy_agent.phase6_local_inference_preview import EXPECTED_MATRIX as EXPECTED_LOCAL_INFERENCE_MATRIX
from agronomy_agent.phase6_owner_staffing import (
    EXPECTED_ROLLBACK_ACTIONS,
    EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION,
    EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION,
    EXPECTED_ROLES,
    EXPECTED_ROLE_STATUS_BY_ID,
    EXPECTED_SIGNOFF_DEPENDENCIES,
    EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY,
    EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY,
    PHASE6_OWNER_STAFFING_VERSION,
)
from agronomy_agent.phase6_pwa_offline_lite import (
    PHASE6_SCOPE_ITEMS as PHASE6_PWA_SCOPE_ITEMS,
    PRIVATE_API_PREFIXES as PHASE6_PWA_PRIVATE_API_PREFIXES,
    REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_PWA_SNIPPETS_BY_SECTION,
)
from agronomy_agent.phase6_pre_provider_readiness import (
    EXPECTED_HUMAN_SIGNOFF_PACKET_ITEMS,
    EXPECTED_HUMAN_SIGNOFF_REHEARSAL_ITEMS,
    EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCIES,
    EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCY_DETAILS,
)
from agronomy_agent.phase6_rate_limits_quotas import (
    EXPECTED_RATE_LIMIT_BACKENDS,
    REQUIRED_BOARD_EVIDENCE as REQUIRED_RATE_LIMIT_BOARD_EVIDENCE,
    REQUIRED_QUOTA_KEYS as REQUIRED_RATE_LIMIT_QUOTA_KEYS,
    REQUIRED_QUOTA_TEST_SNIPPETS as REQUIRED_RATE_LIMIT_QUOTA_TEST_SNIPPETS,
    REQUIRED_RATE_LIMIT_TESTS,
    REQUIRED_READINESS_FLAGS as REQUIRED_RATE_LIMIT_READINESS_FLAGS,
)
from agronomy_agent.phase6_readiness_board import (
    EXPECTED_BLOCKER_EVIDENCE_BY_ID as EXPECTED_READINESS_BLOCKER_EVIDENCE_BY_ID,
    EXPECTED_BLOCKER_IDS as EXPECTED_READINESS_BLOCKER_IDS,
    EXPECTED_BLOCKER_STATUS_BY_ID as EXPECTED_READINESS_BLOCKER_STATUS_BY_ID,
    EXPECTED_DEMO_ASSET_IDS,
    EXPECTED_DEMO_ASSET_STATUS_BY_ID,
    EXPECTED_ROLLBACK_ACTION_IDS as EXPECTED_READINESS_ROLLBACK_ACTION_IDS,
    PHASE6_READINESS_BOARD_VERSION,
)
from agronomy_agent.phase6_reports_source_provenance import (
    EXPECTED_REPORTS as EXPECTED_PHASE6_REPORTS,
    REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION,
)
from agronomy_agent.phase6_ui_information_architecture import (
    EXPECTED_AREA_IDS as EXPECTED_UI_AREA_IDS,
    EXPECTED_AUDIENCE_BY_AREA as EXPECTED_UI_AUDIENCE_BY_AREA,
    EXPECTED_COMPONENT_IDS as EXPECTED_UI_COMPONENT_IDS,
    EXPECTED_PENDING_COMPONENT_IDS as EXPECTED_UI_PENDING_COMPONENT_IDS,
    EXPECTED_ROUTE_BY_AREA as EXPECTED_UI_ROUTE_BY_AREA,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.epic_coverage.v1"

EXPECTED_ROADMAP_ROWS: tuple[dict[str, str], ...] = (
    {
        "phase": "6.0",
        "workstream": "launch freeze",
        "deliverable": "API response contract and launch issue board",
        "owner_suggestion": "tech lead",
        "exit_gate": "contract tests pass",
    },
    {
        "phase": "6.1",
        "workstream": "accounts",
        "deliverable": "settings/consent/export/delete flows",
        "owner_suggestion": "backend+frontend",
        "exit_gate": "auth QA pass",
    },
    {
        "phase": "6.2",
        "workstream": "chat UX",
        "deliverable": "answer/evidence/field/feedback polish",
        "owner_suggestion": "frontend",
        "exit_gate": "200-turn leak QA pass",
    },
    {
        "phase": "6.3",
        "workstream": "reports",
        "deliverable": "thread report and field brief exports",
        "owner_suggestion": "full-stack",
        "exit_gate": "render QA pass",
    },
    {
        "phase": "6.4",
        "workstream": "perf+a11y",
        "deliverable": "CWV telemetry, Lighthouse CI, WCAG audit",
        "owner_suggestion": "frontend",
        "exit_gate": "budgets pass",
    },
    {
        "phase": "6.5",
        "workstream": "local preview",
        "deliverable": "WebGPU probe and local inference sandbox",
        "owner_suggestion": "research engineer",
        "exit_gate": "feature flag and fallback pass",
    },
    {
        "phase": "6.6",
        "workstream": "launch content",
        "deliverable": "landing/docs/demo script/sample reports",
        "owner_suggestion": "product+science",
        "exit_gate": "rehearsal pass",
    },
)
EXPECTED_PUBLIC_SAMPLE_REPORT_TYPES = {"thread_report", "field_context_brief", "demo_eval_snapshot"}
EXPECTED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION = {
    section: list(snippets)
    for section, snippets in sorted(REQUIRED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION.items())
}
EXPECTED_ADMIN_TRACE_SNIPPETS_BY_SECTION = {
    section: list(snippets)
    for section, snippets in sorted(REQUIRED_ADMIN_TRACE_SNIPPETS_BY_SECTION.items())
}
EXPECTED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION = {
    section: list(snippets)
    for section, snippets in sorted(REQUIRED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION.items())
}
EXPECTED_FEEDBACK_SNIPPETS_BY_SECTION = {
    section: list(snippets)
    for section, snippets in sorted(REQUIRED_FEEDBACK_SNIPPETS_BY_SECTION.items())
}
EXPECTED_PWA_SNIPPETS_BY_SECTION = {
    section: list(snippets)
    for section, snippets in sorted(REQUIRED_PWA_SNIPPETS_BY_SECTION.items())
}
EXPECTED_PWA_RUNTIME_CACHE_MAX_ENTRIES = 32
EXPECTED_FRONTEND_QA_MATRIX_COLUMNS = ("test_area", "scenario", "tooling", "pass_condition", "launch_gate")
EXPECTED_LAUNCH_LEAK_PROBE_LABELS = tuple(PHASE6_LAUNCH_QA_PROBE_LABELS)
EXPECTED_LAUNCH_LEAK_RISK_LEVELS = ("low", "medium", "regulated")
EXPECTED_LAUNCH_LEAK_ANSWER_TYPES = ("conceptual", "diagnostic", "field_context", "product_boundary")
REQUIRED_TRACKED_PACKET_SOURCES = (
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/agronomy_agent_phase6_pre_demo_launch_design_packet.md",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_account_feature_backlog.csv",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_frontend_performance_budget.csv",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_frontend_qa_matrix.csv",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_implementation_roadmap.csv",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_launch_readiness_checklist.yaml",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_public_demo_script.md",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_report_manifest_schema.json",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_report_templates.yaml",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_ui_information_architecture.json",
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_webgpu_client_inference_decision_matrix.csv",
)
EXPECTED_OWNER_ROLE_IDS = tuple(sorted(EXPECTED_ROLES))
EXPECTED_OWNER_ROLLBACK_ACTION_IDS = tuple(sorted(EXPECTED_ROLLBACK_ACTIONS))
EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS = tuple(sorted(EXPECTED_SIGNOFF_DEPENDENCIES))
EXPECTED_SIGNOFF_DECISION_ID_LIST = tuple(sorted(EXPECTED_SIGNOFF_DECISION_IDS))
EXPECTED_EXTERNAL_LINK_ID_LIST = tuple(sorted(EXPECTED_LINK_IDS))
EXPECTED_EXTERNAL_LINK_EVIDENCE_BY_ID = {link_id: sorted(values) for link_id, values in sorted(REQUIRED_EXTERNAL_LINK_EVIDENCE_BY_LINK_ID.items())}
EXPECTED_PHASE6_REPORT_TYPE_IDS = tuple(sorted(EXPECTED_PHASE6_REPORTS))
EXPECTED_OPEN_LAUNCH_GATE_IDS = tuple(
    gate_id for gate_id in EXPECTED_LAUNCH_GATE_IDS if EXPECTED_STATUS_BY_GATE_ID[gate_id] != "complete"
)
EXPECTED_OPEN_READINESS_BLOCKER_IDS = tuple(
    blocker_id for blocker_id in EXPECTED_READINESS_BLOCKER_IDS if EXPECTED_READINESS_BLOCKER_STATUS_BY_ID[blocker_id] != "complete"
)
EXPECTED_OPEN_DEMO_ASSET_IDS = tuple(
    asset_id for asset_id in EXPECTED_DEMO_ASSET_IDS if EXPECTED_DEMO_ASSET_STATUS_BY_ID[asset_id] != "complete"
)
EXPECTED_PWA_PHASE6_SCOPE_ITEM_COUNT = len(PHASE6_PWA_SCOPE_ITEMS)
EXPECTED_PWA_PRIVATE_API_PREFIXES = tuple(PHASE6_PWA_PRIVATE_API_PREFIXES)
EXPECTED_RESPONSIVE_VIEWPORT_WIDTHS = (375, 768, 1120)
EXPECTED_RESPONSIVE_RULE_IDS = (
    "desktop-tablet-mobile-matrix",
    "mobile-breakpoint-present",
    "mobile-full-width-controls",
    "mobile-public-nav-targets",
    "mobile-touch-targets",
    "overflow-wrap-boundaries",
    "primary-flow-surfaces-present",
)
EXPECTED_RESPONSIVE_SURFACE_IDS = (
    "hosted-evidence-panel",
    "hosted-export",
    "hosted-export-account",
    "hosted-field-context",
    "hosted-platform",
    "public-demo-pages",
)
REQUIRED_RESPONSIVE_EVIDENCE = (
    "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_frontend_qa_matrix.csv",
    "docs/phase6_responsive_mobile_qa.md",
    "frontend/src/responsiveAudit.ts",
    "frontend/src/responsiveAudit.test.ts",
    "frontend/src/App.test.tsx",
    "scripts/phase6_browser_responsive_qa_flow.js",
)
REQUIRED_RESPONSIVE_MANUAL_REVIEW_ITEMS = (
    "run scripts/phase6_browser_responsive_qa_flow.js against the current local or hosted cockpit",
    "confirm browser flow reports zero same-origin fetch/XHR failures and zero console/page errors",
    "real 375px-class phone or BrowserStack touch and scroll check",
    "tablet portrait and landscape check",
    "final hosted target check after external links are inserted",
)
EXPECTED_LOCAL_INFERENCE_TASK_COUNT = len(EXPECTED_LOCAL_INFERENCE_MATRIX)
EXPECTED_LOCAL_INFERENCE_DEFAULT_TASK_IDS = tuple(
    sorted(expected["task_id"] for expected in EXPECTED_LOCAL_INFERENCE_MATRIX.values() if expected["default"] == "yes")
)
EXPECTED_LOCAL_INFERENCE_SERVER_TASK_IDS = tuple(
    sorted(
        expected["task_id"]
        for expected in EXPECTED_LOCAL_INFERENCE_MATRIX.values()
        if expected["candidate_runtime"] in {"server 4-bit harness", "server harness only"}
    )
)
EXPECTED_LOCAL_INFERENCE_DOWNLOAD_TASK_IDS = tuple(
    sorted(expected["task_id"] for expected in EXPECTED_LOCAL_INFERENCE_MATRIX.values() if expected["output_label"] == "local_draft_allowed")
)
EXPECTED_FIELD_CONTEXT_REHEARSAL_SURFACES = (
    "hosted-answer-panel",
    "hosted-field-context",
    "hosted-field-context-quality",
    "hosted-field-context-readiness",
    "hosted-geo-priors",
)
EXPECTED_FIELD_CONTEXT_REHEARSAL_EVIDENCE = (
    "scripts/phase6_browser_field_context_rehearsal.js",
    "docs/phase6_field_context_readiness_ux.md",
    "frontend/src/fieldContextReadiness.ts",
    "frontend/src/fieldContextReadiness.test.ts",
    "frontend/src/App.test.tsx",
)
EXPECTED_FIELD_CONTEXT_REHEARSAL_MANUAL_ITEMS = (
    "run scripts/phase6_browser_field_context_rehearsal.js against the current local or hosted cockpit",
    "create each safe sample field context and confirm ready/blocked uses",
    "ask one field-context-bound chat question and review answer caveats",
    "keep product/rate decisions blocked until current label and local authority are present",
)


def validate_phase6_epic_coverage(
    *,
    roadmap_path: Path = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_implementation_roadmap.csv",
    answer_contract_test_path: Path = ROOT / "tests/test_phase6_answer_contract.py",
    launch_gate_matrix_report: Path = ROOT / "outputs/phase6_launch_gate_matrix_latest.json",
    readiness_board_report: Path = ROOT / "outputs/phase6_readiness_board_latest.json",
    account_backlog_report: Path = ROOT / "outputs/phase6_account_backlog_latest.json",
    account_privacy_rights_report: Path = ROOT / "outputs/phase6_account_privacy_rights_latest.json",
    admin_trace_access_report: Path = ROOT / "outputs/phase6_admin_trace_access_latest.json",
    launch_leak_report: Path = ROOT / "outputs/phase6_launch_leak_qa_latest.json",
    feedback_review_report: Path = ROOT / "outputs/phase6_feedback_review_latest.json",
    reports_source_provenance_report: Path = ROOT / "outputs/phase6_reports_source_provenance_latest.json",
    demo_assets_report: Path = ROOT / "outputs/phase6_demo_assets_latest.json",
    frontend_qa_matrix_report: Path = ROOT / "outputs/phase6_frontend_qa_matrix_latest.json",
    frontend_events_report: Path = ROOT / "outputs/phase6_frontend_events_latest.json",
    frontend_performance_report: Path = ROOT / "outputs/phase6_frontend_performance_budget_latest.json",
    frontend_bundle_report: Path = ROOT / "outputs/phase6_frontend_bundle_budget_latest.json",
    final_host_report: Path = ROOT / "outputs/phase6_final_host_performance_review_latest.json",
    accessibility_report: Path = ROOT / "outputs/phase6_accessibility_primary_flows_latest.json",
    responsive_report: Path = ROOT / "outputs/phase6_responsive_mobile_qa_latest.json",
    pwa_offline_lite_report: Path = ROOT / "outputs/phase6_pwa_offline_lite_latest.json",
    local_inference_report: Path = ROOT / "outputs/phase6_local_inference_preview_latest.json",
    ui_information_architecture_report: Path = ROOT / "outputs/phase6_ui_information_architecture_latest.json",
    human_signoff_report: Path = ROOT / "outputs/phase6_human_signoff_decisions_latest.json",
    owner_staffing_report: Path = ROOT / "outputs/phase6_owner_staffing_latest.json",
    external_links_report: Path = ROOT / "outputs/phase6_external_links_latest.json",
    public_claims_report: Path = ROOT / "outputs/phase6_public_claims_review_latest.json",
    rate_limits_quotas_report: Path = ROOT / "outputs/phase6_rate_limits_quotas_latest.json",
    field_context_rehearsal_report: Path = ROOT / "outputs/phase6_field_context_rehearsal_latest.json",
    human_signoff_packet_report: Path = ROOT / "outputs/phase6_human_signoff_packet_latest.json",
    agno_promotion_gate_report: Path = ROOT / "outputs/agno_rag_promotion_gate_latest.json",
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    packet_source_tracking = _validate_required_packet_sources_tracked(failures)
    rows = _load_roadmap(roadmap_path, failures)
    _validate_roadmap_rows(rows, failures)

    reports = {
        "launch_gate_matrix": _load_json(launch_gate_matrix_report, "launch_gate_matrix", failures),
        "readiness_board": _load_json(readiness_board_report, "readiness_board", failures),
        "account_backlog": _load_json(account_backlog_report, "account_backlog", failures),
        "account_privacy_rights": _load_json(account_privacy_rights_report, "account_privacy_rights", failures),
        "admin_trace_access": _load_json(admin_trace_access_report, "admin_trace_access", failures),
        "launch_leak_qa": _load_json(launch_leak_report, "launch_leak_qa", failures),
        "feedback_review": _load_json(feedback_review_report, "feedback_review", failures),
        "reports_source_provenance": _load_json(reports_source_provenance_report, "reports_source_provenance", failures),
        "demo_assets": _load_json(demo_assets_report, "demo_assets", failures),
        "frontend_qa_matrix": _load_json(frontend_qa_matrix_report, "frontend_qa_matrix", failures),
        "frontend_events": _load_json(frontend_events_report, "frontend_events", failures),
        "frontend_performance_budget": _load_json(frontend_performance_report, "frontend_performance_budget", failures),
        "frontend_bundle_budget": _load_json(frontend_bundle_report, "frontend_bundle_budget", failures),
        "final_host_performance_review": _load_json(final_host_report, "final_host_performance_review", failures),
        "accessibility_primary_flows": _load_json(accessibility_report, "accessibility_primary_flows", failures),
        "responsive_mobile_qa": _load_json(responsive_report, "responsive_mobile_qa", failures),
        "pwa_offline_lite": _load_json(pwa_offline_lite_report, "pwa_offline_lite", failures),
        "local_inference_preview": _load_json(local_inference_report, "local_inference_preview", failures),
        "ui_information_architecture": _load_json(ui_information_architecture_report, "ui_information_architecture", failures),
        "human_signoff_decisions": _load_json(human_signoff_report, "human_signoff_decisions", failures),
        "owner_staffing": _load_json(owner_staffing_report, "owner_staffing", failures),
        "external_links": _load_json(external_links_report, "external_links", failures),
        "public_claims_review": _load_json(public_claims_report, "public_claims_review", failures),
        "rate_limits_quotas": _load_json(rate_limits_quotas_report, "rate_limits_quotas", failures),
        "field_context_rehearsal": _load_json(field_context_rehearsal_report, "field_context_rehearsal", failures),
        "human_signoff_packet": _load_json(human_signoff_packet_report, "human_signoff_packet", failures),
        "agno_promotion_gate": _load_json(agno_promotion_gate_report, "agno_promotion_gate", failures),
    }

    phase_results = [
        _phase_60(answer_contract_test_path, reports, failures),
        _phase_61(reports, failures),
        _phase_62(reports, failures),
        _phase_63(reports, failures),
        _phase_64(reports, failures),
        _phase_65(reports, failures),
        _phase_66(reports, failures),
    ]

    evidence = {
        "roadmap": _display_path(roadmap_path),
        "answer_contract_tests": _display_path(answer_contract_test_path),
        "launch_gate_matrix": _display_path(launch_gate_matrix_report),
        "readiness_board": _display_path(readiness_board_report),
        "account_backlog": _display_path(account_backlog_report),
        "account_privacy_rights": _display_path(account_privacy_rights_report),
        "admin_trace_access": _display_path(admin_trace_access_report),
        "launch_leak_qa": _display_path(launch_leak_report),
        "feedback_review": _display_path(feedback_review_report),
        "reports_source_provenance": _display_path(reports_source_provenance_report),
        "demo_assets": _display_path(demo_assets_report),
        "frontend_qa_matrix": _display_path(frontend_qa_matrix_report),
        "frontend_events": _display_path(frontend_events_report),
        "frontend_performance_budget": _display_path(frontend_performance_report),
        "frontend_bundle_budget": _display_path(frontend_bundle_report),
        "final_host_performance_review": _display_path(final_host_report),
        "accessibility_primary_flows": _display_path(accessibility_report),
        "responsive_mobile_qa": _display_path(responsive_report),
        "pwa_offline_lite": _display_path(pwa_offline_lite_report),
        "local_inference_preview": _display_path(local_inference_report),
        "ui_information_architecture": _display_path(ui_information_architecture_report),
        "human_signoff_decisions": _display_path(human_signoff_report),
        "owner_staffing": _display_path(owner_staffing_report),
        "external_links": _display_path(external_links_report),
        "public_claims_review": _display_path(public_claims_report),
        "rate_limits_quotas": _display_path(rate_limits_quotas_report),
        "field_context_rehearsal": _display_path(field_context_rehearsal_report),
        "human_signoff_packet": _display_path(human_signoff_packet_report),
        "agno_promotion_gate": _display_path(agno_promotion_gate_report),
    }
    complete_phase_ids = [row["phase"] for row in phase_results if row["automated_gate_passed"]]
    incomplete_phase_ids = [row["phase"] for row in phase_results if not row["automated_gate_passed"]]
    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "phase_count": len(rows),
        "expected_phase_count": len(EXPECTED_ROADMAP_ROWS),
        "complete_phase_ids": complete_phase_ids,
        "incomplete_phase_ids": incomplete_phase_ids,
        "phase_results": phase_results,
        "external_launch_ready": False,
        "manual_or_provider_dependencies_required": True,
        "packet_source_tracking": packet_source_tracking,
        "packet_sources_tracked": not packet_source_tracking["missing_or_untracked"],
        "manual_or_provider_dependency_ids": [
            "public_claims_review",
            "hidden_scaffolding_leakage_review",
            "final_host_lighthouse_lab",
            "real_device_mobile_review",
            "named_owner_replacement",
            "provider_rate_limit_quota_review",
            "final_public_links",
        ],
        "evidence": evidence,
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_epic_coverage_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_required_packet_sources_tracked(failures: list[dict[str, str]]) -> dict[str, Any]:
    index_paths = _tracked_paths_from_git_index(ROOT)
    missing_or_untracked: list[str] = []
    for relative_path in REQUIRED_TRACKED_PACKET_SOURCES:
        path = ROOT / relative_path
        if not path.exists():
            missing_or_untracked.append(relative_path)
            failures.append({"section": "packet_sources", "reason": f"required packet source missing: {relative_path}"})
            continue
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative_path],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 and relative_path not in index_paths:
            missing_or_untracked.append(relative_path)
            failures.append({"section": "packet_sources", "reason": f"required packet source is not tracked: {relative_path}"})
    return {
        "required_count": len(REQUIRED_TRACKED_PACKET_SOURCES),
        "tracked_count": len(REQUIRED_TRACKED_PACKET_SOURCES) - len(missing_or_untracked),
        "missing_or_untracked": missing_or_untracked,
    }


def _tracked_paths_from_git_index(repo_root: Path) -> set[str]:
    """Read v2/v3 Git index entries when the platform Git CLI is unavailable."""

    git_path = repo_root / ".git"
    if git_path.is_file():
        marker = git_path.read_text(encoding="utf-8", errors="replace").strip()
        if not marker.startswith("gitdir:"):
            return set()
        git_dir = Path(marker.partition(":")[2].strip())
        if not git_dir.is_absolute():
            git_dir = (repo_root / git_dir).resolve()
    else:
        git_dir = git_path
    index_path = git_dir / "index"
    try:
        data = index_path.read_bytes()
    except OSError:
        return set()
    if len(data) < 12 or data[:4] != b"DIRC":
        return set()
    version, entry_count = struct.unpack(">II", data[4:12])
    if version not in {2, 3}:
        return set()
    paths: set[str] = set()
    offset = 12
    for _ in range(entry_count):
        entry_start = offset
        if offset + 62 > len(data):
            return set()
        flags = struct.unpack(">H", data[offset + 60 : offset + 62])[0]
        path_start = offset + 62
        declared_length = flags & 0x0FFF
        if declared_length < 0x0FFF:
            path_end = path_start + declared_length
            if path_end >= len(data) or data[path_end] != 0:
                return set()
        else:
            path_end = data.find(b"\0", path_start)
            if path_end < 0:
                return set()
        paths.add(data[path_start:path_end].decode("utf-8", errors="surrogateescape"))
        entry_length = path_end - entry_start + 1
        offset = entry_start + ((entry_length + 7) // 8) * 8
    return paths


def _phase_60(answer_contract_test_path: Path, reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    text = _read_text(answer_contract_test_path, "phase_6_0", failures)
    ui_ia = reports["ui_information_architecture"]
    launch_gate_matrix = reports["launch_gate_matrix"]
    readiness_board = reports["readiness_board"]
    agno_gate = reports["agno_promotion_gate"]
    agno_metrics = agno_gate.get("metrics") if isinstance(agno_gate.get("metrics"), dict) else {}
    rollback = agno_metrics.get("rollback_evidence") if isinstance(agno_metrics.get("rollback_evidence"), dict) else {}
    rollback_checks = rollback.get("checks") if isinstance(rollback.get("checks"), dict) else {}
    checks = [
        _check("answer contract tests exist", answer_contract_test_path.exists()),
        _check("public answer contract covered", "test_phase6_structured_answer_contract_sanitizes_internal_and_raw_html" in text),
        _check("hosted stream contract covered", "test_phase6_hosted_chat_stream_emits_public_answer_contract" in text),
        _check("UI information architecture tracked", ui_ia.get("gate_passed") is True),
        _check("UI IA area ids exact", tuple(_strings(ui_ia.get("observed_area_ids"))) == EXPECTED_UI_AREA_IDS),
        _check("UI IA routes exact", ui_ia.get("observed_route_by_area") == EXPECTED_UI_ROUTE_BY_AREA),
        _check("UI IA audiences exact", ui_ia.get("observed_audience_by_area") == EXPECTED_UI_AUDIENCE_BY_AREA),
        _check("UI IA component ids exact", tuple(_strings(ui_ia.get("observed_component_ids"))) == EXPECTED_UI_COMPONENT_IDS),
        _check("UI IA component evidence ids exact", tuple(_strings(ui_ia.get("component_evidence_ids"))) == EXPECTED_UI_COMPONENT_IDS),
        _check("UI IA pending components exact", tuple(_strings(ui_ia.get("pending_external_component_ids"))) == EXPECTED_UI_PENDING_COMPONENT_IDS),
        _check("UI IA inventory exact", ui_ia.get("ui_inventory_exact") is True),
        _check("UI IA has no inventory deltas", not any(_strings(ui_ia.get(key)) for key in ("missing_area_ids", "extra_area_ids", "missing_component_ids", "extra_component_ids", "missing_component_evidence_ids", "extra_component_evidence_ids")) and not any(ui_ia.get(key) for key in ("route_mismatches", "audience_mismatches"))),
        _check("UI route projection review explicit", ui_ia.get("route_projection_review_required") is True),
        _check("React frontend cutover verified", ui_ia.get("react_frontend_cutover_verified") is True),
        _check("Gradio dependency removed", ui_ia.get("gradio_dependency_removed") is True),
        _check("launch gate matrix schema exact", launch_gate_matrix.get("schema_version") == PHASE6_LAUNCH_GATE_MATRIX_VERSION),
        _check("launch gate matrix tracked", launch_gate_matrix.get("tracking_gate_passed") is True),
        _check("launch gate matrix failure count zero", int(launch_gate_matrix.get("failure_count") or 0) == 0 and not launch_gate_matrix.get("failures")),
        _check("launch gate matrix keeps launch blocked", launch_gate_matrix.get("launch_ready") is False),
        _check("launch gate matrix expected ids reported", tuple(_strings(launch_gate_matrix.get("expected_gate_ids"))) == EXPECTED_LAUNCH_GATE_IDS),
        _check("launch gate matrix ids exact", tuple(_strings(launch_gate_matrix.get("observed_gate_ids"))) == EXPECTED_LAUNCH_GATE_IDS),
        _check("launch gate matrix expected statuses reported", launch_gate_matrix.get("expected_status_by_gate_id") == EXPECTED_STATUS_BY_GATE_ID),
        _check("launch gate matrix statuses exact", launch_gate_matrix.get("status_by_gate_id") == EXPECTED_STATUS_BY_GATE_ID),
        _check("launch gate matrix expected evidence reported", launch_gate_matrix.get("expected_evidence_by_gate_id") == EXPECTED_LAUNCH_GATE_EVIDENCE_BY_GATE_ID),
        _check("launch gate matrix evidence exact", launch_gate_matrix.get("evidence_by_gate_id") == EXPECTED_LAUNCH_GATE_EVIDENCE_BY_GATE_ID),
        _check("launch gate matrix gate count exact", int(launch_gate_matrix.get("launch_gate_count") or 0) == len(EXPECTED_LAUNCH_GATE_IDS)),
        _check("launch gate matrix complete count exact", int(launch_gate_matrix.get("complete_gate_count") or -1) == len(EXPECTED_LAUNCH_GATE_IDS) - len(EXPECTED_OPEN_LAUNCH_GATE_IDS)),
        _check("launch gate matrix open count exact", int(launch_gate_matrix.get("open_gate_count") or -1) == len(EXPECTED_OPEN_LAUNCH_GATE_IDS)),
        _check("launch gate matrix open ids exact", tuple(_strings(launch_gate_matrix.get("open_gate_ids"))) == EXPECTED_OPEN_LAUNCH_GATE_IDS),
        _check("launch gate matrix inventory exact", launch_gate_matrix.get("gate_inventory_exact") is True),
        _check("launch gate matrix has no inventory deltas", not any(_strings(launch_gate_matrix.get(key)) for key in ("missing_gate_ids", "extra_gate_ids", "missing_launch_gates", "extra_launch_gates")) and not any(launch_gate_matrix.get(key) for key in ("status_mismatches", "packet_text_mismatches", "evidence_mismatches"))),
        _check("readiness board schema exact", readiness_board.get("schema_version") == PHASE6_READINESS_BOARD_VERSION),
        _check("readiness board tracked", readiness_board.get("tracking_gate_passed") is True),
        _check("readiness board failure count zero", int(readiness_board.get("failure_count") or 0) == 0 and not readiness_board.get("failures")),
        _check("readiness board keeps launch blocked", readiness_board.get("launch_ready") is False),
        _check("readiness board expected blocker ids reported", tuple(_strings(readiness_board.get("expected_blocker_ids"))) == EXPECTED_READINESS_BLOCKER_IDS),
        _check("readiness board blocker ids exact", tuple(_strings(readiness_board.get("observed_blocker_ids"))) == EXPECTED_READINESS_BLOCKER_IDS),
        _check("readiness board expected blocker statuses reported", readiness_board.get("expected_blocker_status_by_id") == EXPECTED_READINESS_BLOCKER_STATUS_BY_ID),
        _check("readiness board blocker statuses exact", readiness_board.get("blocker_status_by_id") == EXPECTED_READINESS_BLOCKER_STATUS_BY_ID),
        _check("readiness board expected blocker evidence reported", readiness_board.get("expected_blocker_evidence_by_id") == EXPECTED_READINESS_BLOCKER_EVIDENCE_BY_ID),
        _check("readiness board blocker evidence exact", readiness_board.get("blocker_evidence_by_id") == EXPECTED_READINESS_BLOCKER_EVIDENCE_BY_ID),
        _check("readiness board blocker count exact", int(readiness_board.get("blocker_count") or 0) == len(EXPECTED_READINESS_BLOCKER_IDS)),
        _check("readiness board complete blocker count exact", int(readiness_board.get("complete_blocker_count") or -1) == len(EXPECTED_READINESS_BLOCKER_IDS) - len(EXPECTED_OPEN_READINESS_BLOCKER_IDS)),
        _check("readiness board open blocker count exact", int(readiness_board.get("open_blocker_count") or -1) == len(EXPECTED_OPEN_READINESS_BLOCKER_IDS)),
        _check("readiness board open blocker ids exact", tuple(_strings(readiness_board.get("open_blocker_ids"))) == EXPECTED_OPEN_READINESS_BLOCKER_IDS),
        _check("readiness board expected demo asset ids reported", tuple(_strings(readiness_board.get("expected_demo_asset_ids"))) == EXPECTED_DEMO_ASSET_IDS),
        _check("readiness board demo asset ids exact", tuple(_strings(readiness_board.get("observed_demo_asset_ids"))) == EXPECTED_DEMO_ASSET_IDS),
        _check("readiness board expected demo asset statuses reported", readiness_board.get("expected_demo_asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID),
        _check("readiness board demo asset statuses exact", readiness_board.get("demo_asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID),
        _check("readiness board demo asset count exact", int(readiness_board.get("demo_asset_count") or 0) == len(EXPECTED_DEMO_ASSET_IDS)),
        _check("readiness board open demo asset count exact", _int_value(readiness_board.get("open_demo_asset_count")) == len(EXPECTED_OPEN_DEMO_ASSET_IDS)),
        _check("readiness board open demo asset ids exact", tuple(_strings(readiness_board.get("open_demo_asset_ids"))) == EXPECTED_OPEN_DEMO_ASSET_IDS),
        _check("readiness board expected rollback action ids reported", tuple(_strings(readiness_board.get("expected_rollback_action_ids"))) == EXPECTED_READINESS_ROLLBACK_ACTION_IDS),
        _check("readiness board rollback action ids exact", tuple(_strings(readiness_board.get("observed_rollback_action_ids"))) == EXPECTED_READINESS_ROLLBACK_ACTION_IDS),
        _check("readiness board rollback action count exact", int(readiness_board.get("rollback_action_count") or 0) == len(EXPECTED_READINESS_ROLLBACK_ACTION_IDS)),
        _check("readiness board inventory exact", readiness_board.get("board_inventory_exact") is True),
        _check("readiness board has no inventory deltas", not any(_strings(readiness_board.get(key)) for key in ("missing_blocker_ids", "extra_blocker_ids", "missing_demo_asset_ids", "extra_demo_asset_ids", "missing_rollback_action_ids", "extra_rollback_action_ids", "missing_packet_blockers", "missing_packet_demo_assets", "missing_packet_rollback_actions", "missing_launch_modes", "extra_launch_modes")) and not any(readiness_board.get(key) for key in ("blocker_status_mismatches", "blocker_evidence_mismatches", "demo_asset_status_mismatches"))),
        _check("Agno promotion gate passed", agno_gate.get("promotion_allowed") is True),
        _check("Agno dependency available", agno_metrics.get("agno_dependency_available") is True),
        _check("Agno replacement recommended", agno_metrics.get("profile_recommendation") == "promote_agno_replace_legacy"),
        _check("Agno resource singleton reuse verified", agno_metrics.get("resource_singleton_reused") is True),
        _check("Agno resource singleton reuse within budget", agno_metrics.get("resource_singleton_reuse_within_budget") is True),
        _check("Agno eligible fanout within budget", agno_metrics.get("agno_index_max_eligible_docs_within_budget") is True),
        _check("Agno scored candidate fanout within budget", agno_metrics.get("agno_index_max_scored_candidates_within_budget") is True),
        _check("Agno runtime index caches within budget", agno_metrics.get("agno_index_runtime_caches_within_budget") is True),
        _check("Agno case latency regressions absent", not _strings(agno_metrics.get("case_latency_regression_case_ids"))),
        _check("legacy runtime removal verified", rollback_checks.get("legacy_runtime_removed") is True),
    ]
    return _phase_result("6.0", checks, failures)


def _phase_61(reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    backlog = reports["account_backlog"]
    account = reports["account_privacy_rights"]
    checks = [
        _check("account backlog tracking passed", backlog.get("tracking_gate_passed") is True),
        _check("launch-required account features ready", backlog.get("launch_required_features_ready") is True),
        _check("account backlog expected feature ids reported", _string_tuple(backlog.get("expected_feature_ids")) == EXPECTED_FEATURE_IDS),
        _check("account backlog observed feature ids exact", _string_tuple(backlog.get("observed_feature_ids")) == EXPECTED_FEATURE_IDS),
        _check("account backlog feature inventory exact", _string_tuple(backlog.get("feature_ids")) == EXPECTED_FEATURE_IDS),
        _check("account backlog priorities exact", backlog.get("priority_by_feature") == EXPECTED_PRIORITY_BY_FEATURE),
        _check("account backlog phases exact", backlog.get("phase_by_feature") == EXPECTED_PHASE_BY_FEATURE),
        _check("account backlog statuses exact", backlog.get("status_by_feature") == EXPECTED_STATUS_BY_FEATURE),
        _check("account backlog acceptance criteria exact", backlog.get("acceptance_criteria_by_feature") == EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE),
        _check("account backlog inventory exact flag", backlog.get("account_backlog_inventory_exact") is True),
        _check("account backlog has no inventory deltas", not any(_strings(backlog.get(key)) for key in ("missing_features", "extra_features")) and not any(backlog.get(key) for key in ("priority_mismatches", "phase_mismatches", "acceptance_criteria_mismatches"))),
        _check("account backlog implemented inventory exact", _string_tuple(backlog.get("implemented_features")) == EXPECTED_IMPLEMENTED_FEATURES),
        _check("account backlog deferred scope stable", _string_tuple(backlog.get("deferred_features")) == EXPECTED_DEFERRED_FEATURES),
        _check("account privacy gate passed", account.get("gate_passed") is True),
        _check("account privacy schema exact", account.get("schema_version") == "phase6.account_privacy_rights.v1"),
        _check("account privacy failure count zero", int(account.get("failure_count") or 0) == 0 and not account.get("failures")),
        _check("account privacy control ids exact", _string_tuple(account.get("observed_control_ids")) == EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS),
        _check("account privacy expected control ids reported", _string_tuple(account.get("expected_control_ids")) == EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS),
        _check("account privacy control count exact", int(account.get("control_count") or 0) == len(EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS)),
        _check("account privacy expected statuses reported", account.get("expected_control_status_by_id") == EXPECTED_ACCOUNT_PRIVACY_CONTROL_STATUS_BY_ID),
        _check("account privacy statuses exact", account.get("control_status_by_id") == EXPECTED_ACCOUNT_PRIVACY_CONTROL_STATUS_BY_ID),
        _check("account privacy evidence exact", account.get("control_evidence_by_id") == EXPECTED_ACCOUNT_PRIVACY_CONTROL_EVIDENCE_BY_ID),
        _check("account privacy control inventory exact", account.get("account_privacy_control_inventory_exact") is True),
        _check("account privacy has no control deltas", not any(_strings(account.get(key)) for key in ("missing_control_ids", "extra_control_ids")) and not account.get("control_status_mismatches")),
        _check("account privacy expected snippet inventory reported", account.get("expected_snippets_by_section") == EXPECTED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION),
        _check("account privacy snippet inventory exact", account.get("observed_snippets_by_section") == EXPECTED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION),
        _check("account privacy has no missing snippets", not any(account.get("missing_snippets_by_section", {}).values())),
        _check("account privacy snippet inventory flag exact", account.get("snippet_inventory_exact") is True),
        _check("account auth launch gate complete", account.get("auth_gate_complete") is True),
        _check("account data launch gate complete", account.get("data_gate_complete") is True),
        _check("account backlog linked gate passed", account.get("account_backlog_gate_passed") is True),
        _check("password auth token gated", account.get("password_auth_token_gated") is True),
        _check("account export covered", account.get("account_export_covered") is True),
        _check(
            "account export excludes object bytes and vectors",
            account.get("data_export_excludes_object_bytes_and_vectors") is True,
        ),
        _check(
            "account export excludes internal storage handles",
            account.get("data_export_excludes_internal_storage_handles") is True,
        ),
        _check("delete account covered", account.get("delete_account_covered") is True),
        _check("delete workspace covered", account.get("delete_workspace_covered") is True),
        _check("delete thread covered", account.get("delete_thread_covered") is True),
        _check("data deletion covered", account.get("data_deletion_covered") is True),
        _check("consent and retention covered", account.get("consent_and_retention_covered") is True),
        _check("session management covered", account.get("session_management_covered") is True),
        _check("sensitive action reauth covered", account.get("sensitive_action_reauth_covered") is True),
        _check("frontend account privacy controls visible", account.get("frontend_privacy_controls_visible") is True),
    ]
    return _phase_result("6.1", checks, failures)


def _phase_62(reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    launch_leak = reports["launch_leak_qa"]
    feedback = reports["feedback_review"]
    admin_trace = reports["admin_trace_access"]
    launch_leak_provenance = launch_leak.get("artifact_provenance") if isinstance(launch_leak.get("artifact_provenance"), dict) else {}
    checks = [
        _check("launch leak QA gate passed", launch_leak.get("gate_passed") is True),
        _check("launch leak QA schema exact", launch_leak.get("schema_version") == PHASE6_LAUNCH_QA_VERSION),
        _check("launch leak QA covers at least 200 turns", int(launch_leak.get("case_count") or 0) >= PHASE6_LAUNCH_QA_MIN_TURNS),
        _check("launch leak QA min-turn floor stable", int(launch_leak.get("min_turns") or 0) == PHASE6_LAUNCH_QA_MIN_TURNS),
        _check("launch leak QA failure count zero", int(launch_leak.get("failure_count") or 0) == 0 and not launch_leak.get("failures")),
        _check("launch leak QA gate reasons empty", not _strings(launch_leak.get("gate_reasons"))),
        _check("launch leak QA human review required", launch_leak.get("human_review_required") is True),
        _check("launch leak QA provenance builder exact", launch_leak_provenance.get("case_builder") == "build_phase6_launch_leak_qa_cases"),
        _check("launch leak QA provenance case count matches", int(launch_leak_provenance.get("case_count") or 0) == int(launch_leak.get("case_count") or -1)),
        _check("launch leak QA provenance min turns matches", int(launch_leak_provenance.get("min_turns") or 0) == int(launch_leak.get("min_turns") or -1)),
        _check("launch leak QA forbidden pattern coverage tracked", int(launch_leak_provenance.get("forbidden_pattern_count") or 0) >= 10),
        _check("launch leak QA probe labels exact", tuple(_strings(launch_leak.get("required_probe_labels"))) == EXPECTED_LAUNCH_LEAK_PROBE_LABELS),
        _check("launch leak QA no missing probe labels", not _strings(launch_leak.get("missing_required_probe_labels"))),
        _check("launch leak QA probe coverage exact", _mapping_keys(launch_leak.get("probe_coverage")) == tuple(sorted(EXPECTED_LAUNCH_LEAK_PROBE_LABELS))),
        _check("launch leak QA review samples cover probes", len(launch_leak.get("review_samples") or []) == len(EXPECTED_LAUNCH_LEAK_PROBE_LABELS)),
        _check("launch leak QA removed leak classes tracked", int(launch_leak.get("removed_leak_class_count") or 0) > 0),
        _check("launch leak QA risk coverage exact", _mapping_keys(launch_leak.get("risk_level_coverage")) == EXPECTED_LAUNCH_LEAK_RISK_LEVELS),
        _check("launch leak QA answer type coverage exact", _mapping_keys(launch_leak.get("answer_type_coverage")) == EXPECTED_LAUNCH_LEAK_ANSWER_TYPES),
        _check("feedback review gate passed", feedback.get("gate_passed") is True),
        _check("feedback review schema exact", feedback.get("schema_version") == "phase6.feedback_review.v1"),
        _check("feedback review launch gate complete", feedback.get("launch_gate_complete") is True),
        _check("feedback review failure count zero", int(feedback.get("failure_count") or 0) == 0 and not feedback.get("failures")),
        _check("feedback endpoint access controlled", feedback.get("feedback_endpoint_access_controlled") is True),
        _check("feedback trace event recorded", feedback.get("feedback_trace_event_recorded") is True),
        _check("feedback phase5 trace span recorded", feedback.get("feedback_phase5_trace_span_recorded") is True),
        _check("feedback creates eval candidates", feedback.get("eval_candidate_created_from_feedback") is True),
        _check("feedback review and replay covered", feedback.get("review_and_replay_covered") is True),
        _check("feedback quick taxonomy visible", feedback.get("quick_feedback_taxonomy_visible") is True),
        _check("feedback admin triage taxonomy visible", feedback.get("admin_triage_taxonomy_visible") is True),
        _check("feedback detailed controls visible", feedback.get("detailed_feedback_controls_visible") is True),
        _check("feedback triage visible", feedback.get("frontend_triage_visible") is True),
        _check("feedback report exports include feedback", feedback.get("report_exports_include_feedback") is True),
        _check("feedback expected snippet inventory reported", feedback.get("expected_snippets_by_section") == EXPECTED_FEEDBACK_SNIPPETS_BY_SECTION),
        _check("feedback snippet inventory exact", feedback.get("observed_snippets_by_section") == EXPECTED_FEEDBACK_SNIPPETS_BY_SECTION),
        _check("feedback has no missing snippets", not any(feedback.get("missing_snippets_by_section", {}).values())),
        _check("feedback snippet inventory flag exact", feedback.get("snippet_inventory_exact") is True),
        _check("admin trace access gate passed", admin_trace.get("gate_passed") is True),
        _check("admin trace launch gate complete", admin_trace.get("launch_gate_complete") is True),
        _check("admin trace backend roles restricted", admin_trace.get("admin_roles_restricted") is True),
        _check("admin trace phase5 route access controlled", admin_trace.get("phase5_admin_trace_access_controlled") is True),
        _check("admin trace cross-workspace denial covered", admin_trace.get("cross_workspace_denial_covered") is True),
        _check("admin trace frontend panel gated", admin_trace.get("admin_ops_frontend_gated") is True),
        _check("admin trace frontend observability failures visible", admin_trace.get("admin_ops_failures_visible") is True),
        _check("normal user admin panel hidden", admin_trace.get("normal_user_admin_panel_hidden") is True),
        _check("admin trace expected snippet inventory reported", admin_trace.get("expected_snippets_by_section") == EXPECTED_ADMIN_TRACE_SNIPPETS_BY_SECTION),
        _check("admin trace snippet inventory exact", admin_trace.get("observed_snippets_by_section") == EXPECTED_ADMIN_TRACE_SNIPPETS_BY_SECTION),
        _check("admin trace has no missing snippets", not any(admin_trace.get("missing_snippets_by_section", {}).values())),
        _check("admin trace snippet inventory flag exact", admin_trace.get("snippet_inventory_exact") is True),
    ]
    return _phase_result("6.2", checks, failures)


def _phase_63(reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    provenance = reports["reports_source_provenance"]
    demo_assets = reports["demo_assets"]
    provenance_sample_types = set(_strings(provenance.get("sample_report_types")))
    demo_sample_types = set(_strings(demo_assets.get("sample_report_types")))
    checks = [
        _check("report provenance gate passed", provenance.get("gate_passed") is True),
        _check("report provenance launch gate complete", provenance.get("launch_gate_complete") is True),
        _check("report provenance failure count zero", int(provenance.get("failure_count") or 0) == 0 and not _strings(provenance.get("failures"))),
        _check("report type inventory exact", tuple(_strings(provenance.get("report_types"))) == EXPECTED_PHASE6_REPORT_TYPE_IDS),
        _check("schema covers all report types", provenance.get("schema_covers_all_report_types") is True),
        _check("template catalog covers all report types", provenance.get("template_catalog_covers_all_report_types") is True),
        _check("export service covers all report types", provenance.get("export_service_covers_all_report_types") is True),
        _check("tests cover all report types", provenance.get("tests_cover_all_report_types") is True),
        _check("sample reports validate", provenance.get("sample_reports_validate") is True),
        _check("sample report data origins covered", provenance.get("sample_data_origins_covered") is True),
        _check("sample report packet metadata and disclaimers covered", provenance.get("packet_metadata_and_disclaimers_covered") is True),
        _check("report hidden scaffolding excluded", provenance.get("hidden_scaffolding_excluded") is True),
        _check("report source provenance covered", provenance.get("source_provenance_covered") is True),
        _check("async export jobs covered", provenance.get("async_export_jobs_covered") is True),
        _check("report provenance expected snippet inventory reported", provenance.get("expected_snippets_by_section") == EXPECTED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION),
        _check("report provenance snippet inventory exact", provenance.get("observed_snippets_by_section") == EXPECTED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION),
        _check("report provenance has no missing snippets", not any(provenance.get("missing_snippets_by_section", {}).values())),
        _check("report provenance snippet inventory flag exact", provenance.get("snippet_inventory_exact") is True),
        _check("source/provenance sample report types stable", provenance_sample_types == EXPECTED_PUBLIC_SAMPLE_REPORT_TYPES),
        _check("demo sample report asset types stable", demo_sample_types == EXPECTED_PUBLIC_SAMPLE_REPORT_TYPES),
        _check("demo and provenance sample report types match", demo_sample_types == provenance_sample_types),
    ]
    return _phase_result("6.3", checks, failures)


def _phase_64(reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    qa_matrix = reports["frontend_qa_matrix"]
    frontend_events = reports["frontend_events"]
    frontend_perf = reports["frontend_performance_budget"]
    bundle = reports["frontend_bundle_budget"]
    final_host = reports["final_host_performance_review"]
    container = final_host.get("container_summary") if isinstance(final_host.get("container_summary"), dict) else {}
    browser_lab = final_host.get("browser_lab_summary") if isinstance(final_host.get("browser_lab_summary"), dict) else {}
    accessibility = reports["accessibility_primary_flows"]
    responsive = reports["responsive_mobile_qa"]
    pwa = reports["pwa_offline_lite"]
    checks = [
        _check("frontend QA matrix gate passed", qa_matrix.get("gate_passed") is True),
        _check("frontend QA matrix row count stable", int(qa_matrix.get("row_count") or 0) == 10),
        _check("frontend QA matrix columns stable", tuple(_strings(qa_matrix.get("columns"))) == EXPECTED_FRONTEND_QA_MATRIX_COLUMNS),
        _check("frontend QA matrix blocker count stable", int(qa_matrix.get("blocker_count") or 0) == 9),
        _check("frontend QA matrix monitor count stable", int(qa_matrix.get("monitor_count") or 0) == 1),
        _check("frontend QA matrix test areas exact", tuple(_strings(qa_matrix.get("observed_test_areas"))) == EXPECTED_TEST_AREA_IDS),
        _check("frontend QA matrix blocker areas exact", tuple(_strings(qa_matrix.get("observed_blocker_test_areas"))) == EXPECTED_BLOCKER_TEST_AREA_IDS),
        _check("frontend QA matrix monitor areas exact", tuple(_strings(qa_matrix.get("observed_monitor_test_areas"))) == EXPECTED_MONITOR_TEST_AREA_IDS),
        _check("frontend QA matrix row inventory exact", qa_matrix.get("row_inventory_exact") is True),
        _check("frontend QA matrix has no row deltas", not any(_strings(qa_matrix.get(key)) for key in ("missing_test_areas", "extra_test_areas"))),
        _check("frontend QA matrix evidence inventory exact", qa_matrix.get("evidence_inventory_exact") is True),
        _check("frontend QA matrix has no evidence deltas", not any(_strings(qa_matrix.get(key)) for key in ("missing_evidence_areas", "extra_evidence_areas")) and not any(qa_matrix.get(key) for key in ("missing_evidence_by_area", "extra_evidence_by_area"))),
        _check("frontend QA matrix has no extra evidence areas", not _strings(qa_matrix.get("extra_evidence_areas"))),
        _check("frontend QA matrix evidence paths exist", qa_matrix.get("all_evidence_paths_exist") is True),
        _check("frontend event taxonomy gate passed", frontend_events.get("gate_passed") is True),
        _check("frontend event taxonomy covers all packet events", int(frontend_events.get("required_event_count") or 0) == 25),
        _check("frontend event taxonomy has frontend parity", int(frontend_events.get("frontend_event_count") or 0) == 25),
        _check("frontend event taxonomy has backend parity", int(frontend_events.get("server_schema_event_count") or 0) == 25),
        _check("frontend event names match packet exactly", _strings(frontend_events.get("frontend_event_names")) == _strings(frontend_events.get("required_event_names"))),
        _check("backend event names match packet exactly", _strings(frontend_events.get("server_schema_event_names")) == _strings(frontend_events.get("required_event_names"))),
        _check("frontend event taxonomy exact", frontend_events.get("event_taxonomy_exact") is True),
        _check("frontend event taxonomy has no deltas", not any(_strings(frontend_events.get(key)) for key in ("missing_frontend_event_names", "extra_frontend_event_names", "missing_server_schema_event_names", "extra_server_schema_event_names"))),
        _check("frontend privacy keys match packet exactly", _strings(frontend_events.get("frontend_privacy_keys")) == _strings(frontend_events.get("required_privacy_keys"))),
        _check("backend privacy keys match packet exactly", _strings(frontend_events.get("server_privacy_keys")) == _strings(frontend_events.get("required_privacy_keys"))),
        _check("frontend event privacy key taxonomy exact", frontend_events.get("privacy_key_taxonomy_exact") is True),
        _check("frontend event privacy key taxonomy has no deltas", not any(_strings(frontend_events.get(key)) for key in ("missing_frontend_privacy_keys", "extra_frontend_privacy_keys", "missing_server_privacy_keys", "extra_server_privacy_keys"))),
        _check("frontend event privacy tests covered", frontend_events.get("frontend_private_metadata_rejection_covered") is True),
        _check("frontend RUM metadata redaction covered", frontend_events.get("frontend_rum_metadata_redaction_covered") is True),
        _check("frontend telemetry failures observable", frontend_events.get("frontend_telemetry_failure_event_covered") is True),
        _check("backend RUM metadata redaction covered", frontend_events.get("backend_rum_metadata_redaction_covered") is True),
        _check("backend unknown event rejection covered", frontend_events.get("backend_unknown_event_rejection_covered") is True),
        _check("frontend performance budget gate passed", frontend_perf.get("gate_passed") is True),
        _check("frontend performance blocker budgets mapped", int(frontend_perf.get("mapped_budget_count") or 0) == 11),
        _check("frontend performance packet metrics exact", tuple(_strings(frontend_perf.get("packet_metric_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_PACKET_METRIC_IDS),
        _check("frontend performance blocker packet metrics exact", tuple(_strings(frontend_perf.get("packet_blocker_metric_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_BLOCKER_PACKET_METRIC_IDS),
        _check("frontend performance required budget ids exact", tuple(_strings(frontend_perf.get("required_budget_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS),
        _check("frontend performance frontend budget ids exact", tuple(_strings(frontend_perf.get("frontend_budget_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS),
        _check("frontend performance backend budget ids exact", tuple(_strings(frontend_perf.get("server_budget_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS),
        _check("frontend performance schema metric ids exact", tuple(_strings(frontend_perf.get("schema_metric_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS),
        _check("frontend performance exception remains documented", int(frontend_perf.get("documented_exception_count") or 0) == 1),
        _check("frontend performance exception ids exact", tuple(_strings(frontend_perf.get("documented_exception_ids"))) == EXPECTED_FRONTEND_PERFORMANCE_EXCEPTION_IDS),
        _check("frontend performance budget manifest exact", frontend_perf.get("budget_manifest_exact") is True),
        _check("frontend performance budget has no deltas", not any(_strings(frontend_perf.get(key)) for key in ("missing_packet_metric_ids", "extra_packet_metric_ids", "missing_blocker_packet_metric_ids", "extra_blocker_packet_metric_ids", "missing_frontend_budget_ids", "extra_frontend_budget_ids", "missing_server_budget_ids", "extra_server_budget_ids", "missing_schema_metric_ids", "extra_schema_metric_ids", "missing_documented_exception_ids", "extra_documented_exception_ids"))),
        _check("frontend bundle budget passed", bundle.get("gate_passed") is True),
        _check("frontend bundle budget ids stable", tuple(_strings(bundle.get("budget_ids"))) == EXPECTED_BUNDLE_BUDGET_IDS),
        _check("frontend bundle manifest exact", bundle.get("budget_manifest_exact") is True),
        _check("frontend bundle has no unbudgeted assets", not _strings(bundle.get("unbudgeted_assets"))),
        _check("frontend bundle entry references intact", not _strings(bundle.get("html_reference_missing"))),
        _check("frontend bundle all assets budgeted", int(bundle.get("asset_count") or 0) == int(bundle.get("budgeted_asset_count") or -1)),
        _check("final-host gate passed", final_host.get("gate_passed") is True),
        _check("final-host automated prerequisites passed", final_host.get("automated_prerequisites_passed") is True),
        _check("final host keeps provider target required", final_host.get("provider_target_required") is True),
        _check("final host keeps Lighthouse required", final_host.get("lighthouse_still_required") is True),
        _check("final host container summary tracked", bool(container)),
        _check("final host container service inventory tracked", int(container.get("required_service_count") or 0) == int(container.get("service_count") or -1) == 5),
        _check("final host container secret placeholders verified", container.get("sensitive_env_inline_secret_check") is True),
        _check("final host worker healthcheck required", container.get("worker_healthcheck_required") is True),
        _check("final host worker healthcheck non-mutating", container.get("worker_healthcheck_non_mutating") is True),
        _check("final host API env placeholders tracked", int(container.get("required_api_env_placeholder_count") or 0) >= 18),
        _check("final host worker env placeholders tracked", int(container.get("required_worker_env_placeholder_count") or 0) >= 7),
        _check("browser lab artifact boundary tracked", bool(browser_lab)),
        _check("browser lab required for final-host review", browser_lab.get("required_for_final_host_review") is True),
        _check("browser lab not required for pre-provider readiness", browser_lab.get("required_for_pre_provider") is False),
        _check("browser lab artifact status is explicit", browser_lab.get("artifact_status") in {"missing", "validated"}),
        _check("accessibility primary flows passed", accessibility.get("gate_passed") is True),
        _check("accessibility launch gate complete", accessibility.get("launch_gate_complete") is True),
        _check("accessibility failure count zero", int(accessibility.get("failure_count") or 0) == 0 and not _strings(accessibility.get("failures"))),
        _check("accessibility docs current", accessibility.get("docs_current") is True),
        _check("accessibility primary flow audit complete", accessibility.get("primary_flow_audited") is True),
        _check("accessibility keyboard and alert affordances covered", accessibility.get("keyboard_and_alert_affordances") is True),
        _check("accessibility low-bandwidth coverage complete", accessibility.get("low_bandwidth_accessibility_covered") is True),
        _check("accessibility audit rules exact", tuple(_strings(accessibility.get("covered_audit_rule_ids"))) == REQUIRED_ACCESSIBILITY_AUDIT_RULES),
        _check("accessibility primary flow ids exact", tuple(_strings(accessibility.get("covered_primary_flow_ids"))) == REQUIRED_ACCESSIBILITY_PRIMARY_FLOW_IDS),
        _check("accessibility semantic token ids exact", tuple(_strings(accessibility.get("covered_semantic_token_ids"))) == REQUIRED_ACCESSIBILITY_SEMANTIC_TOKEN_IDS),
        _check("accessibility low-bandwidth reasons exact", tuple(_strings(accessibility.get("covered_low_bandwidth_reasons"))) == REQUIRED_ACCESSIBILITY_LOW_BANDWIDTH_REASONS),
        _check("accessibility launch-gate evidence ids exact", tuple(_strings(accessibility.get("launch_gate_evidence_ids"))) == REQUIRED_ACCESSIBILITY_LAUNCH_GATE_EVIDENCE),
        _check("accessibility inventory exact", accessibility.get("accessibility_inventory_exact") is True),
        _check("accessibility has no inventory deltas", not any(_strings(accessibility.get(key)) for key in ("missing_audit_rule_ids", "missing_primary_flow_ids", "missing_semantic_token_ids", "missing_low_bandwidth_reasons", "missing_launch_gate_evidence_ids", "extra_launch_gate_evidence_ids"))),
        _check("responsive automated QA passed", responsive.get("automated_gate_passed") is True),
        _check("responsive schema exact", responsive.get("schema_version") == "phase6.responsive_mobile_qa.v1"),
        _check("responsive failure count zero", int(responsive.get("failure_count") or 0) == 0 and not responsive.get("failures")),
        _check("responsive manual review remains explicit", responsive.get("manual_review_required") is True),
        _check("responsive viewport widths exact", _responsive_viewport_widths(responsive.get("viewport_profiles")) == EXPECTED_RESPONSIVE_VIEWPORT_WIDTHS),
        _check("responsive rule count stable", int(responsive.get("required_rule_count") or 0) == len(EXPECTED_RESPONSIVE_RULE_IDS)),
        _check("responsive rule ids exact", tuple(_strings(responsive.get("required_rules"))) == EXPECTED_RESPONSIVE_RULE_IDS),
        _check("responsive surface count stable", int(responsive.get("required_surface_count") or 0) == len(EXPECTED_RESPONSIVE_SURFACE_IDS)),
        _check("responsive surface ids exact", tuple(_strings(responsive.get("required_surfaces"))) == EXPECTED_RESPONSIVE_SURFACE_IDS),
        _check("responsive evidence exact", tuple(_strings(responsive.get("evidence"))) == REQUIRED_RESPONSIVE_EVIDENCE),
        _check("responsive manual review items exact", tuple(_strings(responsive.get("manual_review_items"))) == REQUIRED_RESPONSIVE_MANUAL_REVIEW_ITEMS),
        _check("PWA offline-lite gate passed", pwa.get("gate_passed") is True),
        _check("PWA failure count zero", int(pwa.get("failure_count") or 0) == 0 and not pwa.get("failures")),
        _check("PWA external launch remains provider-blocked", pwa.get("external_launch_ready") is False),
        _check("PWA packet scope covered", pwa.get("packet_scope_covered") is True),
        _check("PWA packet scope item count stable", int(pwa.get("phase6_scope_item_count") or 0) == EXPECTED_PWA_PHASE6_SCOPE_ITEM_COUNT),
        _check("PWA installable shell ready", pwa.get("installable_shell_ready") is True),
        _check("PWA offline page ready", pwa.get("offline_page_ready") is True),
        _check("PWA draft preservation ready", pwa.get("draft_preservation_ready") is True),
        _check("PWA deferred queue ready", pwa.get("deferred_queue_ready") is True),
        _check("PWA scratchpad remains local only", pwa.get("scratchpad_local_only") is True),
        _check("PWA no offline model generation boundary retained", pwa.get("no_offline_model_generation") is True),
        _check("PWA service worker cache boundary retained", pwa.get("service_worker_cache_bounded") is True),
        _check("PWA runtime asset cache budget retained", pwa.get("service_worker_runtime_cache_budgeted") is True),
        _check("PWA runtime asset cache max entries exact", int(pwa.get("service_worker_runtime_cache_max_entries") or 0) == EXPECTED_PWA_RUNTIME_CACHE_MAX_ENTRIES),
        _check("PWA deferred queue privacy retained", pwa.get("deferred_queue_privacy_guarded") is True),
        _check("PWA production registration bounded", pwa.get("production_registration_bounded") is True),
        _check("PWA docs current", pwa.get("docs_current") is True),
        _check("PWA CI tests tracked", pwa.get("ci_tests_tracked") is True),
        _check("PWA frontend tests tracked", pwa.get("frontend_tests_tracked") is True),
        _check("PWA private API prefix inventory exact", tuple(_strings(pwa.get("private_api_prefixes"))) == EXPECTED_PWA_PRIVATE_API_PREFIXES),
        _check("PWA private API prefix count stable", int(pwa.get("private_api_prefix_count") or 0) == len(EXPECTED_PWA_PRIVATE_API_PREFIXES)),
        _check("PWA expected snippet inventory reported", pwa.get("expected_snippets_by_section") == EXPECTED_PWA_SNIPPETS_BY_SECTION),
        _check("PWA snippet inventory exact", pwa.get("observed_snippets_by_section") == EXPECTED_PWA_SNIPPETS_BY_SECTION),
        _check("PWA has no missing snippets", not any(pwa.get("missing_snippets_by_section", {}).values())),
        _check("PWA snippet inventory flag exact", pwa.get("snippet_inventory_exact") is True),
    ]
    return _phase_result("6.4", checks, failures)


def _phase_65(reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    local = reports["local_inference_preview"]
    checks = [
        _check("local inference gate passed", local.get("gate_passed") is True),
        _check("local inference schema exact", local.get("schema_version") == "phase6.local_inference_preview.v1"),
        _check("local inference launch gate complete", local.get("launch_gate_complete") is True),
        _check("local inference failure count zero", int(local.get("failure_count") or 0) == 0 and not local.get("failures")),
        _check("local inference matrix task count stable", int(local.get("matrix_task_count") or 0) == EXPECTED_LOCAL_INFERENCE_TASK_COUNT),
        _check("local inference expected task count stable", int(local.get("expected_task_count") or 0) == EXPECTED_LOCAL_INFERENCE_TASK_COUNT),
        _check("local inference default task ids exact", tuple(_strings(local.get("default_enabled_task_ids"))) == EXPECTED_LOCAL_INFERENCE_DEFAULT_TASK_IDS),
        _check("local inference server-required task ids exact", tuple(_strings(local.get("server_harness_required_task_ids"))) == EXPECTED_LOCAL_INFERENCE_SERVER_TASK_IDS),
        _check("local inference download-eligible task ids exact", tuple(_strings(local.get("download_eligible_task_ids"))) == EXPECTED_LOCAL_INFERENCE_DOWNLOAD_TASK_IDS),
        _check("local inference feature flag required", local.get("feature_flag_required") is True),
        _check("server harness remains canonical", local.get("canonical_answer_path") == "server_harness"),
        _check("no-download boundary retained", local.get("no_download_boundary") is True),
        _check("local inference forbidden dependencies absent", not _strings(local.get("forbidden_dependencies"))),
        _check("local inference forbidden imports absent", not _strings(local.get("forbidden_imports"))),
        _check("explicit download consent required", local.get("explicit_download_consent_required") is True),
        _check("human research signoff still required", local.get("human_research_signoff_required") is True),
    ]
    return _phase_result("6.5", checks, failures)


def _phase_66(reports: dict[str, dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    demo = reports["demo_assets"]
    field_context_rehearsal = reports["field_context_rehearsal"]
    signoff = reports["human_signoff_decisions"]
    signoff_packet = reports["human_signoff_packet"]
    signoff_packet_summaries = signoff_packet.get("summaries") if isinstance(signoff_packet.get("summaries"), dict) else {}
    signoff_packet_rate_limits = signoff_packet_summaries.get("rate_limits_quotas") if isinstance(signoff_packet_summaries.get("rate_limits_quotas"), dict) else {}
    signoff_packet_dependencies = signoff_packet_summaries.get("pre_provider_dependencies") if isinstance(signoff_packet_summaries.get("pre_provider_dependencies"), dict) else {}
    signoff_packet_dependency_details = signoff_packet_dependencies.get("dependency_details") if isinstance(signoff_packet_dependencies.get("dependency_details"), list) else []
    staffing = reports["owner_staffing"]
    links = reports["external_links"]
    public_claims = reports["public_claims_review"]
    rate_limits = reports["rate_limits_quotas"]
    public_claim_source_ids = {str(row.get("source_id")) for row in public_claims.get("sources") or [] if isinstance(row, dict)}
    required_public_claim_sources = set(_strings(public_claims.get("required_generated_review_sources")))
    public_claim_boundary_ids = set(_strings(public_claims.get("required_boundaries")))
    public_claim_boundary_evidence = public_claims.get("boundary_evidence") if isinstance(public_claims.get("boundary_evidence"), dict) else {}
    homepage = public_claims.get("homepage_explanation") if isinstance(public_claims.get("homepage_explanation"), dict) else {}
    checks = [
        _check("demo assets passed", demo.get("gate_passed") is True),
        _check("demo assets schema exact", demo.get("schema_version") == PHASE6_DEMO_ASSETS_VERSION),
        _check("demo assets failure count zero", int(demo.get("failure_count") or 0) == 0 and not demo.get("failures")),
        _check("all demo assets complete", demo.get("all_assets_complete") is True),
        _check("demo asset count exact", int(demo.get("asset_count") or 0) == len(EXPECTED_DEMO_ASSET_ID_LIST)),
        _check("demo asset expected ids reported", _string_tuple(demo.get("expected_asset_ids")) == EXPECTED_DEMO_ASSET_ID_LIST),
        _check("demo asset ids exact", _string_tuple(demo.get("observed_asset_ids")) == EXPECTED_DEMO_ASSET_ID_LIST),
        _check("demo asset sorted ids exact", set(_strings(demo.get("asset_ids"))) == set(EXPECTED_DEMO_ASSET_ID_LIST)),
        _check("demo asset expected statuses reported", demo.get("expected_asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID),
        _check("demo asset statuses exact", demo.get("asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID),
        _check("demo asset expected owner roles reported", demo.get("expected_asset_owner_role_by_id") == EXPECTED_DEMO_ASSET_OWNER_ROLE_BY_ID),
        _check("demo asset owner roles exact", demo.get("asset_owner_role_by_id") == EXPECTED_DEMO_ASSET_OWNER_ROLE_BY_ID),
        _check("demo asset expected packet text reported", demo.get("expected_asset_packet_text_by_id") == EXPECTED_DEMO_ASSET_PACKET_TEXT_BY_ID),
        _check("demo asset packet text exact", demo.get("asset_packet_text_by_id") == EXPECTED_DEMO_ASSET_PACKET_TEXT_BY_ID),
        _check("demo asset evidence present", _evidence_map_covers(demo.get("asset_evidence_by_id"), EXPECTED_DEMO_ASSET_ID_LIST)),
        _check("demo asset inventory exact", demo.get("demo_asset_inventory_exact") is True),
        _check("demo assets have no inventory deltas", not any(_strings(demo.get(key)) for key in ("missing_asset_ids", "extra_asset_ids")) and not any(demo.get(key) for key in ("status_mismatches", "owner_role_mismatches", "packet_text_mismatches"))),
        _check("human demo review remains required", demo.get("human_review_required") is True),
        _check("human demo review reason retained", "public-claims review" in str(demo.get("human_review_reason") or "")),
        _check("demo public page count exact", int(demo.get("public_page_count") or 0) == len(EXPECTED_DEMO_PUBLIC_PAGE_IDS)),
        _check("demo public page ids exact", set(_strings(demo.get("public_page_ids"))) == EXPECTED_DEMO_PUBLIC_PAGE_IDS),
        _check("demo homepage word count bounded", 0 < int(demo.get("homepage_word_count") or 0) <= 120),
        _check("demo sample report types exact", set(_strings(demo.get("sample_report_types"))) == EXPECTED_DEMO_SAMPLE_REPORT_TYPES),
        _check("demo data-source coverage ready", demo.get("data_source_coverage_ready") is True),
        _check("demo sample field contexts visible", demo.get("sample_field_contexts_visible") is True),
        _check("demo script ready", demo.get("demo_script_ready") is True),
        _check("field-context rehearsal gate passed", field_context_rehearsal.get("automated_gate_passed") is True),
        _check("field-context rehearsal schema exact", field_context_rehearsal.get("schema_version") == "phase6.field_context_rehearsal_gate.v1"),
        _check("field-context rehearsal failure count zero", int(field_context_rehearsal.get("failure_count") or 0) == 0 and not field_context_rehearsal.get("failures")),
        _check("field-context browser rehearsal schema exact", field_context_rehearsal.get("browser_rehearsal_schema") == "phase6.browser_field_context_rehearsal.v1"),
        _check("field-context rehearsal surfaces exact", tuple(_strings(field_context_rehearsal.get("required_surfaces"))) == EXPECTED_FIELD_CONTEXT_REHEARSAL_SURFACES),
        _check("field-context rehearsal evidence exact", tuple(_strings(field_context_rehearsal.get("evidence"))) == EXPECTED_FIELD_CONTEXT_REHEARSAL_EVIDENCE),
        _check("field-context manual review remains required", field_context_rehearsal.get("manual_review_required") is True),
        _check("field-context manual review reason retained", bool(str(field_context_rehearsal.get("manual_review_reason") or "").strip())),
        _check("field-context manual review items exact", tuple(_strings(field_context_rehearsal.get("manual_review_items"))) == EXPECTED_FIELD_CONTEXT_REHEARSAL_MANUAL_ITEMS),
        _check("human signoff tracking passed", signoff.get("tracking_gate_passed") is True),
        _check("human signoff decision ids exact", _string_tuple(signoff.get("observed_decision_ids")) == EXPECTED_SIGNOFF_DECISION_ID_LIST),
        _check("human signoff expected decision ids reported", _string_tuple(signoff.get("expected_decision_ids")) == EXPECTED_SIGNOFF_DECISION_ID_LIST),
        _check("human signoff pre-provider statuses exact", signoff.get("status_by_decision_id") == EXPECTED_SIGNOFF_PRE_PROVIDER_STATUS_BY_DECISION),
        _check("human signoff expected pre-provider statuses reported", signoff.get("expected_pre_provider_status_by_decision_id") == EXPECTED_SIGNOFF_PRE_PROVIDER_STATUS_BY_DECISION),
        _check("human signoff item types exact", signoff.get("item_type_by_decision_id") == EXPECTED_SIGNOFF_ITEM_TYPE_BY_DECISION),
        _check("human signoff owner roles exact", signoff.get("owner_role_by_decision_id") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DECISION),
        _check("human signoff pre-provider inventory exact", signoff.get("pre_provider_decision_inventory_exact") is True),
        _check("human signoff has no inventory deltas", not any(_strings(signoff.get(key)) for key in ("missing_decision_ids", "extra_decision_ids")) and not any(signoff.get(key) for key in ("status_mismatches", "item_type_mismatches", "owner_role_mismatches"))),
        _check("human signoff remains incomplete before humans", signoff.get("launch_signoff_complete") is False),
        _check("human signoff packet schema exact", signoff_packet.get("schema_version") == "phase6.human_signoff_packet.v1"),
        _check("human signoff packet gate passed", signoff_packet.get("gate_passed") is True),
        _check("human signoff packet review-ready", signoff_packet.get("review_ready") is True),
        _check("human signoff packet does not self-approve launch", signoff_packet.get("launch_signoff_complete") is False),
        _check("human signoff packet failure count zero", int(signoff_packet.get("failure_count") or 0) == 0),
        _check("human signoff packet signoff items exact", _item_ids(signoff_packet.get("signoff_items")) == EXPECTED_HUMAN_SIGNOFF_PACKET_ITEMS),
        _check("human signoff packet rehearsal items exact", _item_ids(signoff_packet.get("rehearsal_items")) == EXPECTED_HUMAN_SIGNOFF_REHEARSAL_ITEMS),
        _check("human signoff packet summarizes passing rate limits", signoff_packet_rate_limits.get("gate_passed") is True),
        _check("human signoff packet carries Redis limiter dependency", signoff_packet_rate_limits.get("public_demo_requires_redis_rate_limit") is True),
        _check("human signoff packet carries provider quota dependency", signoff_packet_rate_limits.get("provider_quota_review_required") is True),
        _check("human signoff packet remaining dependency count exact", int(signoff_packet_dependencies.get("remaining_dependency_count") or 0) == len(EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCIES)),
        _check("human signoff packet dependency details exact", _normalize_dependency_details(signoff_packet_dependency_details) == _expected_dependency_details()),
        _check("human signoff packet does not claim external launch ready", signoff_packet_dependencies.get("external_launch_ready") is False),
        _check("human signoff packet dependency sources complete", not _strings(signoff_packet_dependencies.get("missing_source_ids"))),
        _check("owner staffing schema exact", staffing.get("schema_version") == PHASE6_OWNER_STAFFING_VERSION),
        _check("owner staffing tracking passed", staffing.get("tracking_gate_passed") is True),
        _check("owner staffing failure count zero", int(staffing.get("failure_count") or 0) == 0 and not staffing.get("failures")),
        _check("owner staffing external launch remains blocked", staffing.get("external_launch_ready") is False),
        _check("owner staffing role count exact", int(staffing.get("role_count") or 0) == len(EXPECTED_OWNER_ROLE_IDS)),
        _check("owner staffing expected role ids reported", _string_tuple(staffing.get("expected_role_ids")) == EXPECTED_OWNER_ROLE_IDS),
        _check("owner staffing observed role ids exact", _string_tuple(staffing.get("observed_role_ids")) == EXPECTED_OWNER_ROLE_IDS),
        _check("owner staffing role inventory exact", _string_tuple(staffing.get("role_ids")) == EXPECTED_OWNER_ROLE_IDS),
        _check("owner staffing expected role statuses reported", staffing.get("expected_role_status_by_id") == EXPECTED_ROLE_STATUS_BY_ID),
        _check("owner staffing role statuses exact", staffing.get("role_status_by_id") == EXPECTED_ROLE_STATUS_BY_ID),
        _check("owner staffing role inventory flag exact", staffing.get("role_inventory_exact") is True),
        _check("owner staffing open role count exact", int(staffing.get("open_role_count") or 0) == len(EXPECTED_OWNER_ROLE_IDS)),
        _check("owner staffing open roles exact", set(_strings(staffing.get("open_role_ids"))) == set(EXPECTED_OWNER_ROLE_IDS)),
        _check("owner staffing placeholder roles exact", set(_strings(staffing.get("placeholder_role_ids"))) == set(EXPECTED_OWNER_ROLE_IDS)),
        _check("owner staffing launch surface roles exact", set(_strings(staffing.get("launch_surface_role_ids"))) == set(EXPECTED_OWNER_ROLE_IDS)),
        _check("owner staffing role deltas absent", not any(_strings(staffing.get(key)) for key in ("missing_roles", "extra_roles", "missing_launch_surface_roles"))),
        _check("owner staffing rollback action count exact", int(staffing.get("rollback_action_count") or 0) == len(EXPECTED_OWNER_ROLLBACK_ACTION_IDS)),
        _check("owner staffing expected rollback ids reported", _string_tuple(staffing.get("expected_rollback_action_ids")) == EXPECTED_OWNER_ROLLBACK_ACTION_IDS),
        _check("owner staffing observed rollback ids exact", _string_tuple(staffing.get("observed_rollback_action_ids")) == EXPECTED_OWNER_ROLLBACK_ACTION_IDS),
        _check("owner staffing rollback actions covered", _string_tuple(staffing.get("rollback_action_ids")) == EXPECTED_OWNER_ROLLBACK_ACTION_IDS),
        _check("owner staffing expected rollback owner roles reported", staffing.get("expected_rollback_owner_role_by_action") == EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION),
        _check("owner staffing rollback owner roles exact", staffing.get("rollback_owner_role_by_action") == EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION),
        _check("owner staffing expected rollback backup roles reported", staffing.get("expected_rollback_backup_role_by_action") == EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION),
        _check("owner staffing rollback backup roles exact", staffing.get("rollback_backup_role_by_action") == EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION),
        _check("owner staffing rollback inventory flag exact", staffing.get("rollback_inventory_exact") is True),
        _check("owner staffing rollback deltas absent", not any(_strings(staffing.get(key)) for key in ("missing_rollback_actions", "extra_rollback_actions"))),
        _check("owner staffing signoff dependency count exact", int(staffing.get("signoff_dependency_count") or 0) == len(EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS)),
        _check("owner staffing expected signoff ids reported", _string_tuple(staffing.get("expected_signoff_dependency_ids")) == EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS),
        _check("owner staffing observed signoff ids exact", _string_tuple(staffing.get("observed_signoff_dependency_ids")) == EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS),
        _check("owner staffing signoff dependencies covered", _string_tuple(staffing.get("signoff_dependency_ids")) == EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS),
        _check("owner staffing expected signoff owner roles reported", staffing.get("expected_signoff_owner_role_by_dependency") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY),
        _check("owner staffing signoff owner roles exact", staffing.get("signoff_owner_role_by_dependency") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY),
        _check("owner staffing expected signoff statuses reported", staffing.get("expected_signoff_status_by_dependency") == EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY),
        _check("owner staffing signoff statuses exact", staffing.get("signoff_status_by_dependency") == EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY),
        _check("owner staffing signoff inventory flag exact", staffing.get("signoff_dependency_inventory_exact") is True),
        _check("owner staffing open signoff ids exact", set(_strings(staffing.get("open_signoff_ids"))) == set(EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS)),
        _check("owner staffing signoff deltas absent", not any(_strings(staffing.get(key)) for key in ("missing_signoff_dependencies", "extra_signoff_dependencies"))),
        _check("owner staffing pre-provider inventory flag exact", staffing.get("pre_provider_staffing_inventory_exact") is True),
        _check("owner staffing has no inventory mismatches", not any(staffing.get(key) for key in ("role_status_mismatches", "rollback_owner_role_mismatches", "rollback_backup_role_mismatches", "signoff_owner_role_mismatches", "signoff_status_mismatches"))),
        _check("named owner replacement remains open", staffing.get("staffing_ready") is False),
        _check("external links schema exact", links.get("schema_version") == PHASE6_EXTERNAL_LINKS_VERSION),
        _check("external links tracking passed", links.get("tracking_gate_passed") is True),
        _check("external links failure count zero", int(links.get("failure_count") or 0) == 0 and not links.get("failures")),
        _check("external links count exact", int(links.get("link_count") or 0) == len(EXPECTED_EXTERNAL_LINK_ID_LIST)),
        _check("external links ready count zero", _int_value(links.get("ready_count")) == 0),
        _check("external links pending count exact", int(links.get("pending_count") or 0) == len(EXPECTED_EXTERNAL_LINK_ID_LIST)),
        _check("external links expected ids reported", _string_tuple(links.get("expected_link_ids")) == EXPECTED_EXTERNAL_LINK_ID_LIST),
        _check("external links observed ids exact", _string_tuple(links.get("observed_link_ids")) == EXPECTED_EXTERNAL_LINK_ID_LIST),
        _check("external links ready ids empty", not _strings(links.get("ready_ids"))),
        _check("external links pending ids exact", set(_strings(links.get("pending_ids"))) == set(EXPECTED_EXTERNAL_LINK_ID_LIST)),
        _check("external link records exact", _link_record_ids(links.get("link_records")) == set(EXPECTED_EXTERNAL_LINK_ID_LIST)),
        _check("external link records have evidence", _link_records_have_evidence(links.get("link_records"))),
        _check("external link records have no URLs", _link_records_have_no_urls(links.get("link_records"))),
        _check("external link expected labels reported", links.get("expected_label_by_link_id") == EXPECTED_LABEL_BY_LINK_ID),
        _check("external link labels exact", links.get("label_by_link_id") == EXPECTED_LABEL_BY_LINK_ID),
        _check("external link expected owner roles reported", links.get("expected_owner_role_by_link_id") == EXPECTED_EXTERNAL_LINK_OWNER_ROLE_BY_LINK_ID),
        _check("external link owner roles exact", links.get("owner_role_by_link_id") == EXPECTED_EXTERNAL_LINK_OWNER_ROLE_BY_LINK_ID),
        _check("external link expected statuses reported", links.get("expected_pre_provider_status_by_link_id") == EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID),
        _check("external link statuses exact", links.get("status_by_link_id") == EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID),
        _check("external link expected required-before reported", links.get("expected_required_before_by_link_id") == EXPECTED_REQUIRED_BEFORE_BY_LINK_ID),
        _check("external link required-before exact", links.get("required_before_by_link_id") == EXPECTED_REQUIRED_BEFORE_BY_LINK_ID),
        _check("external link expected URL state reported", links.get("expected_pre_provider_has_url_by_link_id") == EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID),
        _check("external link URL state exact", links.get("has_url_by_link_id") == EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID),
        _check("external link required evidence exact", links.get("required_evidence_by_link_id") == EXPECTED_EXTERNAL_LINK_EVIDENCE_BY_ID),
        _check("external link pre-provider inventory exact", links.get("pre_provider_link_inventory_exact") is True),
        _check("external links have no inventory deltas", not any(_strings(links.get(key)) for key in ("missing_link_ids", "extra_link_ids")) and not any(links.get(key) for key in ("label_mismatches", "owner_role_mismatches", "status_mismatches", "required_before_mismatches", "has_url_mismatches", "missing_required_evidence_by_link_id"))),
        _check("external links remain pending until final URLs", links.get("external_links_ready") is False),
        _check("public claims review schema exact", public_claims.get("schema_version") == "phase6.public_claims_review.v1"),
        _check("public claims automated gate passed", public_claims.get("gate_passed") is True),
        _check("public claims failure count zero", int(public_claims.get("failure_count") or 0) == 0 and int(public_claims.get("violation_count") or 0) == 0),
        _check("public claims violations absent", not _strings(public_claims.get("failures")) and not _strings(public_claims.get("violations"))),
        _check("public claims human signoff remains explicit", public_claims.get("human_signoff_required") is True),
        _check("public claims generated review sources complete", not _strings(public_claims.get("missing_generated_review_sources")) and required_public_claim_sources <= public_claim_source_ids),
        _check("public claims boundaries complete", not _strings(public_claims.get("missing_boundaries")) and public_claim_boundary_ids == set(public_claim_boundary_evidence)),
        _check("public claims homepage concepts complete", not _strings(homepage.get("missing_concepts")) and int(homepage.get("word_count") or 10_000) <= int(homepage.get("max_words") or 0)),
        _check("rate-limit quota gate passed", rate_limits.get("gate_passed") is True),
        _check("rate-limit checklist blocker tracked", rate_limits.get("checklist_blocker_tracked") is True),
        _check("rate-limit readiness board complete", rate_limits.get("readiness_board_complete") is True),
        _check("rate-limit fail closed by default", rate_limits.get("rate_limit_fail_closed_default") is True),
        _check("public demo requires Redis rate limiting", rate_limits.get("public_demo_requires_redis_rate_limit") is True),
        _check("provider quota review remains explicit", rate_limits.get("provider_quota_review_required") is True),
        _check("frontend quota status visible", rate_limits.get("frontend_quota_visible") is True),
        _check("rate-limit backends exact", _string_tuple(rate_limits.get("rate_limit_backends")) == EXPECTED_RATE_LIMIT_BACKENDS),
        _check("rate-limit readiness flags exact", rate_limits.get("readiness_flags") == REQUIRED_RATE_LIMIT_READINESS_FLAGS),
        _check("workspace quota keys exact", _string_tuple(rate_limits.get("quota_keys")) == tuple(sorted(REQUIRED_RATE_LIMIT_QUOTA_KEYS))),
        _check("enforced workspace quota keys exact", _string_tuple(rate_limits.get("enforced_quota_keys")) == tuple(sorted(REQUIRED_RATE_LIMIT_QUOTA_KEYS))),
        _check("workspace quota inventory exact", rate_limits.get("quota_inventory_exact") is True),
        _check("rate-limit board evidence exact", _string_tuple(rate_limits.get("board_evidence_ids")) == REQUIRED_RATE_LIMIT_BOARD_EVIDENCE),
        _check("rate-limit regression tests exact", _string_tuple(rate_limits.get("covered_rate_limit_test_ids")) == REQUIRED_RATE_LIMIT_TESTS),
        _check("quota regression snippets exact", _string_tuple(rate_limits.get("covered_quota_test_snippets")) == REQUIRED_RATE_LIMIT_QUOTA_TEST_SNIPPETS),
        _check("rate-limit evidence inventory exact", rate_limits.get("evidence_inventory_exact") is True),
        _check("rate-limit pre-provider inventory exact", rate_limits.get("pre_provider_rate_limit_inventory_exact") is True),
        _check("rate-limit report has no inventory deltas", not any(_strings(rate_limits.get(key)) for key in ("missing_quota_keys", "extra_quota_keys", "missing_enforced_quota_keys", "extra_enforced_quota_keys", "missing_board_evidence_ids", "extra_board_evidence_ids", "missing_rate_limit_test_ids", "missing_quota_test_snippets")) and not rate_limits.get("readiness_flag_mismatches")),
    ]
    return _phase_result("6.6", checks, failures)


def _phase_result(phase: str, checks: list[dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    missing = [check["name"] for check in checks if not check["passed"]]
    for check_name in missing:
        failures.append({"section": f"phase_{phase}", "reason": check_name})
    check_status_by_name = {str(check["name"]): bool(check["passed"]) for check in checks}
    return {
        "phase": phase,
        "automated_gate_passed": not missing,
        "check_count": len(checks),
        "passed_check_count": len(checks) - len(missing),
        "failed_check_count": len(missing),
        "check_status_by_name": check_status_by_name,
        "failed_checks": missing,
    }


def _check(name: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed)}


def _validate_roadmap_rows(rows: list[dict[str, str]], failures: list[dict[str, str]]) -> None:
    _expect(len(rows) == len(EXPECTED_ROADMAP_ROWS), "roadmap", f"roadmap must contain {len(EXPECTED_ROADMAP_ROWS)} rows", failures)
    for index, expected in enumerate(EXPECTED_ROADMAP_ROWS):
        row = rows[index] if index < len(rows) else {}
        for key, value in expected.items():
            _expect(row.get(key) == value, "roadmap", f"row {index} {key} must be {value}", failures)


def _load_roadmap(path: Path, failures: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [
                {str(key): str(value) for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]
    except Exception as exc:
        failures.append({"section": "roadmap", "reason": f"could not read {_display_path(path)}: {exc}"})
        return []


def _load_json(path: Path, section: str, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return {}
    if not isinstance(payload, dict):
        failures.append({"section": section, "reason": f"{_display_path(path)} must contain a JSON object"})
        return {}
    return payload


def _read_text(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> None:
    if not condition:
        failures.append({"section": section, "reason": reason})


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(_strings(value))


def _int_value(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _item_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item.get("item_id") or "") for item in value if isinstance(item, dict)}


def _link_record_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item.get("id") or "") for item in value if isinstance(item, dict)}


def _link_records_have_evidence(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(item, dict) and int(item.get("evidence_count") or 0) >= 2 for item in value)


def _link_records_have_no_urls(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(item, dict) and item.get("has_url") is False for item in value)


def _evidence_map_covers(value: Any, expected_ids: tuple[str, ...]) -> bool:
    if not isinstance(value, dict):
        return False
    return all(isinstance(value.get(item_id), list) and bool(value.get(item_id)) for item_id in expected_ids)


def _expected_dependency_details() -> list[dict[str, Any]]:
    return [
        {
            "dependency_id": str(item["dependency_id"]),
            "category": str(item["category"]),
            "summary": str(item["summary"]),
            "source_ids": list(item["source_ids"]),
        }
        for item in EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCY_DETAILS
    ]


def _normalize_dependency_details(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    details: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        details.append(
            {
                "dependency_id": str(item.get("dependency_id") or ""),
                "category": str(item.get("category") or ""),
                "summary": str(item.get("summary") or ""),
                "source_ids": list(item.get("source_ids") or []),
            }
        )
    return details


def _mapping_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted(str(key) for key in value))


def _responsive_viewport_widths(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    widths: list[int] = []
    for item in value:
        if isinstance(item, dict):
            try:
                widths.append(int(item.get("target_width_px") or 0))
            except (TypeError, ValueError):
                widths.append(0)
    return tuple(widths)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
