from __future__ import annotations

import json
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
)
from agronomy_agent.phase6_external_links import (
    EXPECTED_LABEL_BY_LINK_ID,
    EXPECTED_LINK_IDS,
    EXPECTED_OWNER_ROLE_BY_LINK_ID as EXPECTED_EXTERNAL_LINK_OWNER_ROLE_BY_LINK_ID,
    EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID,
    EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID,
    EXPECTED_REQUIRED_BEFORE_BY_LINK_ID,
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
from agronomy_agent.phase6_launch_gate_matrix import (
    EXPECTED_EVIDENCE_BY_GATE_ID as EXPECTED_LAUNCH_GATE_EVIDENCE_BY_GATE_ID,
    EXPECTED_LAUNCH_GATE_IDS,
    EXPECTED_STATUS_BY_GATE_ID,
)
from agronomy_agent.phase6_owner_staffing import (
    EXPECTED_ROLLBACK_ACTIONS,
    EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION,
    EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION,
    EXPECTED_ROLES,
    EXPECTED_ROLE_STATUS_BY_ID,
    EXPECTED_SIGNOFF_DEPENDENCIES,
    EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY,
    EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY,
)
from agronomy_agent.phase6_rate_limits_quotas import (
    EXPECTED_RATE_LIMIT_BACKENDS,
    REQUIRED_BOARD_EVIDENCE as REQUIRED_RATE_LIMIT_BOARD_EVIDENCE,
    REQUIRED_QUOTA_TEST_SNIPPETS,
    REQUIRED_RATE_LIMIT_TESTS,
    REQUIRED_READINESS_FLAGS as REQUIRED_RATE_LIMIT_READINESS_FLAGS,
)
from agronomy_agent.phase6_pwa_offline_lite import REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_PWA_SNIPPETS_BY_SECTION
from agronomy_agent.phase6_readiness_board import (
    EXPECTED_BLOCKER_EVIDENCE_BY_ID as EXPECTED_READINESS_BLOCKER_EVIDENCE_BY_ID,
    EXPECTED_BLOCKER_IDS as EXPECTED_READINESS_BLOCKER_IDS,
    EXPECTED_BLOCKER_STATUS_BY_ID as EXPECTED_READINESS_BLOCKER_STATUS_BY_ID,
    EXPECTED_DEMO_ASSET_IDS,
    EXPECTED_DEMO_ASSET_STATUS_BY_ID,
    EXPECTED_ROLLBACK_ACTION_IDS as EXPECTED_READINESS_ROLLBACK_ACTION_IDS,
)
from agronomy_agent.phase6_reports_source_provenance import REQUIRED_SNIPPETS_BY_SECTION as REQUIRED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION
from agronomy_agent.phase6_ui_information_architecture import (
    EXPECTED_AREA_IDS as EXPECTED_UI_AREA_IDS,
    EXPECTED_AUDIENCE_BY_AREA as EXPECTED_UI_AUDIENCE_BY_AREA,
    EXPECTED_COMPONENT_IDS as EXPECTED_UI_COMPONENT_IDS,
    EXPECTED_PENDING_COMPONENT_IDS as EXPECTED_UI_PENDING_COMPONENT_IDS,
    EXPECTED_ROUTE_BY_AREA as EXPECTED_UI_ROUTE_BY_AREA,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.pre_provider_readiness.v1"

DEFAULT_LAUNCH_GATE_MATRIX_REPORT = ROOT / "outputs/phase6_launch_gate_matrix_latest.json"
DEFAULT_READINESS_BOARD_REPORT = ROOT / "outputs/phase6_readiness_board_latest.json"
DEFAULT_CONTAINER_REPORT = ROOT / "outputs/phase6_container_launch_preflight_latest.json"
DEFAULT_FINAL_HOST_REPORT = ROOT / "outputs/phase6_final_host_performance_review_latest.json"
DEFAULT_FRONTEND_EVENTS_REPORT = ROOT / "outputs/phase6_frontend_events_latest.json"
DEFAULT_FRONTEND_QA_MATRIX_REPORT = ROOT / "outputs/phase6_frontend_qa_matrix_latest.json"
DEFAULT_FRONTEND_PERFORMANCE_REPORT = ROOT / "outputs/phase6_frontend_performance_budget_latest.json"
DEFAULT_FRONTEND_BUNDLE_REPORT = ROOT / "outputs/phase6_frontend_bundle_budget_latest.json"
DEFAULT_HUMAN_SIGNOFF_REPORT = ROOT / "outputs/phase6_human_signoff_decisions_latest.json"
DEFAULT_OWNER_STAFFING_REPORT = ROOT / "outputs/phase6_owner_staffing_latest.json"
DEFAULT_EXTERNAL_LINKS_REPORT = ROOT / "outputs/phase6_external_links_latest.json"
DEFAULT_LAUNCH_LEAK_REPORT = ROOT / "outputs/phase6_launch_leak_qa_latest.json"
DEFAULT_PUBLIC_CLAIMS_REPORT = ROOT / "outputs/phase6_public_claims_review_latest.json"
DEFAULT_RESPONSIVE_REPORT = ROOT / "outputs/phase6_responsive_mobile_qa_latest.json"
DEFAULT_LOCAL_INFERENCE_REPORT = ROOT / "outputs/phase6_local_inference_preview_latest.json"
DEFAULT_RATE_LIMITS_QUOTAS_REPORT = ROOT / "outputs/phase6_rate_limits_quotas_latest.json"
DEFAULT_FEEDBACK_REVIEW_REPORT = ROOT / "outputs/phase6_feedback_review_latest.json"
DEFAULT_ACCOUNT_BACKLOG_REPORT = ROOT / "outputs/phase6_account_backlog_latest.json"
DEFAULT_ACCOUNT_PRIVACY_RIGHTS_REPORT = ROOT / "outputs/phase6_account_privacy_rights_latest.json"
DEFAULT_ADMIN_TRACE_ACCESS_REPORT = ROOT / "outputs/phase6_admin_trace_access_latest.json"
DEFAULT_REPORTS_SOURCE_PROVENANCE_REPORT = ROOT / "outputs/phase6_reports_source_provenance_latest.json"
DEFAULT_ACCESSIBILITY_PRIMARY_FLOWS_REPORT = ROOT / "outputs/phase6_accessibility_primary_flows_latest.json"
DEFAULT_DEMO_ASSETS_REPORT = ROOT / "outputs/phase6_demo_assets_latest.json"
DEFAULT_UI_INFORMATION_ARCHITECTURE_REPORT = ROOT / "outputs/phase6_ui_information_architecture_latest.json"
DEFAULT_PWA_OFFLINE_LITE_REPORT = ROOT / "outputs/phase6_pwa_offline_lite_latest.json"
DEFAULT_EPIC_COVERAGE_REPORT = ROOT / "outputs/phase6_epic_coverage_latest.json"
DEFAULT_FIELD_CONTEXT_REHEARSAL_REPORT = ROOT / "outputs/phase6_field_context_rehearsal_latest.json"
DEFAULT_HUMAN_SIGNOFF_PACKET_REPORT = ROOT / "outputs/phase6_human_signoff_packet_latest.json"
DEFAULT_AGNO_PROMOTION_GATE_REPORT = ROOT / "outputs/agno_rag_promotion_gate_latest.json"

ALLOWED_OPEN_LAUNCH_GATES = {
    "hidden_prompt_checklist_tool_routing_leakage",
    "frontend_performance_budget",
    "desktop_tablet_mobile_chat",
    "public_claims_caveats",
    "runbook_owners_rollback",
}
ALLOWED_OPEN_BLOCKERS = {"hidden_scaffolding_leakage", "public_claims_review"}
ALLOWED_PENDING_SIGNOFFS = EXPECTED_SIGNOFF_DECISION_IDS
EXPECTED_SIGNOFF_DECISION_ID_LIST = tuple(sorted(EXPECTED_SIGNOFF_DECISION_IDS))
ALLOWED_PENDING_EXTERNAL_LINKS = EXPECTED_LINK_IDS
EXPECTED_EXTERNAL_LINK_ID_LIST = tuple(sorted(EXPECTED_LINK_IDS))
ALLOWED_DEFERRED_ACCOUNT_FEATURES = {"passkey login", "API keys"}
EXPECTED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION = {
    section: list(snippets)
    for section, snippets in sorted(REQUIRED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION.items())
}
EXPECTED_FRONTEND_QA_MATRIX_COLUMNS = ("test_area", "scenario", "tooling", "pass_condition", "launch_gate")
EXPECTED_RATE_LIMIT_QUOTA_KEYS = (
    "max_attachment_bytes",
    "max_attachments",
    "max_data_sources",
    "max_eval_runs",
    "max_exports",
    "max_messages",
    "max_threads",
)
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
EXPECTED_HUMAN_SIGNOFF_PACKET_ITEMS = {
    "hidden_scaffolding_leakage",
    "public_claims_review",
    "named_owner_replacement",
}
EXPECTED_HUMAN_SIGNOFF_REHEARSAL_ITEMS = {
    "field_context_readiness_rehearsal",
    "final_host_lighthouse_lab",
    "real_device_mobile_review",
    "local_inference_research_signoff",
    "external_links_and_owner_replacement",
}
EXPECTED_OWNER_ROLE_IDS = tuple(sorted(EXPECTED_ROLES))
EXPECTED_OWNER_ROLLBACK_ACTION_IDS = tuple(sorted(EXPECTED_ROLLBACK_ACTIONS))
EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS = tuple(sorted(EXPECTED_SIGNOFF_DEPENDENCIES))
EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCIES = (
    "product/science review of public claims and generated launch artifacts",
    "human review of the 200-turn hidden-scaffolding leak artifact",
    "chosen hosting target plus final Lighthouse/lab run",
    "real-device or BrowserStack mobile/tablet usability review",
    "named launch owners, backups, channels, and provider access",
    "provider Redis rate limiter wiring and final public-demo quota values",
    "final public repository, contribution, and support links",
)
EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCY_DETAILS = (
    {
        "dependency_id": "public_claims_review",
        "category": "human_signoff",
        "summary": "product/science review of public claims and generated launch artifacts",
        "source_ids": ["public_claims_review", "public_claims_caveats"],
    },
    {
        "dependency_id": "hidden_scaffolding_leakage_review",
        "category": "human_signoff",
        "summary": "human review of the 200-turn hidden-scaffolding leak artifact",
        "source_ids": ["hidden_scaffolding_leakage", "hidden_prompt_checklist_tool_routing_leakage"],
    },
    {
        "dependency_id": "final_host_lighthouse_lab",
        "category": "provider_target",
        "summary": "chosen hosting target plus final Lighthouse/lab run",
        "source_ids": ["final_host_lighthouse_lab", "frontend_performance_budget"],
    },
    {
        "dependency_id": "real_device_mobile_review",
        "category": "manual_review",
        "summary": "real-device or BrowserStack mobile/tablet usability review",
        "source_ids": ["real_device_mobile_review", "desktop_tablet_mobile_chat"],
    },
    {
        "dependency_id": "named_owner_replacement",
        "category": "provider_staffing",
        "summary": "named launch owners, backups, channels, and provider access",
        "source_ids": ["named_owner_replacement", "runbook_owners_rollback"],
    },
    {
        "dependency_id": "provider_rate_limit_quota_review",
        "category": "provider_configuration",
        "summary": "provider Redis rate limiter wiring and final public-demo quota values",
        "source_ids": ["rate_limits_quotas"],
    },
    {
        "dependency_id": "final_public_links",
        "category": "external_links",
        "summary": "final public repository, contribution, and support links",
        "source_ids": ["github_repository", "contribution_guide", "support_issue_tracker"],
    },
)


def validate_phase6_pre_provider_readiness(
    *,
    launch_gate_matrix_report: Path = DEFAULT_LAUNCH_GATE_MATRIX_REPORT,
    readiness_board_report: Path = DEFAULT_READINESS_BOARD_REPORT,
    container_report: Path = DEFAULT_CONTAINER_REPORT,
    final_host_report: Path = DEFAULT_FINAL_HOST_REPORT,
    frontend_events_report: Path = DEFAULT_FRONTEND_EVENTS_REPORT,
    frontend_qa_matrix_report: Path = DEFAULT_FRONTEND_QA_MATRIX_REPORT,
    frontend_performance_report: Path = DEFAULT_FRONTEND_PERFORMANCE_REPORT,
    frontend_bundle_report: Path = DEFAULT_FRONTEND_BUNDLE_REPORT,
    human_signoff_report: Path = DEFAULT_HUMAN_SIGNOFF_REPORT,
    owner_staffing_report: Path = DEFAULT_OWNER_STAFFING_REPORT,
    external_links_report: Path = DEFAULT_EXTERNAL_LINKS_REPORT,
    launch_leak_report: Path = DEFAULT_LAUNCH_LEAK_REPORT,
    public_claims_report: Path = DEFAULT_PUBLIC_CLAIMS_REPORT,
    responsive_report: Path = DEFAULT_RESPONSIVE_REPORT,
    local_inference_report: Path = DEFAULT_LOCAL_INFERENCE_REPORT,
    rate_limits_quotas_report: Path = DEFAULT_RATE_LIMITS_QUOTAS_REPORT,
    feedback_review_report: Path = DEFAULT_FEEDBACK_REVIEW_REPORT,
    account_backlog_report: Path = DEFAULT_ACCOUNT_BACKLOG_REPORT,
    account_privacy_rights_report: Path = DEFAULT_ACCOUNT_PRIVACY_RIGHTS_REPORT,
    admin_trace_access_report: Path = DEFAULT_ADMIN_TRACE_ACCESS_REPORT,
    reports_source_provenance_report: Path = DEFAULT_REPORTS_SOURCE_PROVENANCE_REPORT,
    accessibility_primary_flows_report: Path = DEFAULT_ACCESSIBILITY_PRIMARY_FLOWS_REPORT,
    demo_assets_report: Path = DEFAULT_DEMO_ASSETS_REPORT,
    ui_information_architecture_report: Path = DEFAULT_UI_INFORMATION_ARCHITECTURE_REPORT,
    pwa_offline_lite_report: Path = DEFAULT_PWA_OFFLINE_LITE_REPORT,
    epic_coverage_report: Path = DEFAULT_EPIC_COVERAGE_REPORT,
    field_context_rehearsal_report: Path = DEFAULT_FIELD_CONTEXT_REHEARSAL_REPORT,
    human_signoff_packet_report: Path = DEFAULT_HUMAN_SIGNOFF_PACKET_REPORT,
    agno_promotion_gate_report: Path = DEFAULT_AGNO_PROMOTION_GATE_REPORT,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    launch_gate = _load_json(launch_gate_matrix_report, "launch_gate_matrix", failures)
    readiness = _load_json(readiness_board_report, "readiness_board", failures)
    container = _load_json(container_report, "container_launch_preflight", failures)
    final_host = _load_json(final_host_report, "final_host_performance_review", failures)
    frontend_events = _load_json(frontend_events_report, "frontend_events", failures)
    frontend_qa_matrix = _load_json(frontend_qa_matrix_report, "frontend_qa_matrix", failures)
    frontend_performance = _load_json(frontend_performance_report, "frontend_performance_budget", failures)
    frontend_bundle = _load_json(frontend_bundle_report, "frontend_bundle_budget", failures)
    human_signoff = _load_json(human_signoff_report, "human_signoff_decisions", failures)
    owner_staffing = _load_json(owner_staffing_report, "owner_staffing", failures)
    external_links = _load_json(external_links_report, "external_links", failures)
    launch_leak = _load_json(launch_leak_report, "launch_leak_qa", failures)
    public_claims = _load_json(public_claims_report, "public_claims_review", failures)
    responsive = _load_json(responsive_report, "responsive_mobile_qa", failures)
    local_inference = _load_json(local_inference_report, "local_inference_preview", failures)
    rate_limits_quotas = _load_json(rate_limits_quotas_report, "rate_limits_quotas", failures)
    feedback_review = _load_json(feedback_review_report, "feedback_review", failures)
    account_backlog = _load_json(account_backlog_report, "account_backlog", failures)
    account_privacy_rights = _load_json(account_privacy_rights_report, "account_privacy_rights", failures)
    admin_trace_access = _load_json(admin_trace_access_report, "admin_trace_access", failures)
    reports_source_provenance = _load_json(reports_source_provenance_report, "reports_source_provenance", failures)
    accessibility_primary_flows = _load_json(accessibility_primary_flows_report, "accessibility_primary_flows", failures)
    demo_assets = _load_json(demo_assets_report, "demo_assets", failures)
    ui_information_architecture = _load_json(ui_information_architecture_report, "ui_information_architecture", failures)
    pwa_offline_lite = _load_json(pwa_offline_lite_report, "pwa_offline_lite", failures)
    epic_coverage = _load_json(epic_coverage_report, "epic_coverage", failures)
    field_context_rehearsal = _load_json(field_context_rehearsal_report, "field_context_rehearsal", failures)
    human_signoff_packet = _load_json(human_signoff_packet_report, "human_signoff_packet", failures)
    agno_promotion_gate = _load_json(agno_promotion_gate_report, "agno_promotion_gate", failures)

    _expect(launch_gate.get("schema_version") == "phase6.launch_gate_matrix.v1", "launch_gate_matrix", "unexpected launch-gate schema", failures)
    _expect(launch_gate.get("tracking_gate_passed") is True, "launch_gate_matrix", "tracking gate must pass", failures)
    _expect(int(launch_gate.get("failure_count") or 0) == 0, "launch_gate_matrix", "failure_count must be zero", failures)
    _expect(tuple(_string_list(launch_gate, "expected_gate_ids", "launch_gate_matrix", failures)) == EXPECTED_LAUNCH_GATE_IDS, "launch_gate_matrix", "launch gate expected ids must be reported", failures)
    _expect(tuple(_string_list(launch_gate, "observed_gate_ids", "launch_gate_matrix", failures)) == EXPECTED_LAUNCH_GATE_IDS, "launch_gate_matrix", "launch gate ids must stay packet-exact", failures)
    _expect(launch_gate.get("expected_status_by_gate_id") == EXPECTED_STATUS_BY_GATE_ID, "launch_gate_matrix", "launch gate expected statuses must be reported", failures)
    _expect(launch_gate.get("status_by_gate_id") == EXPECTED_STATUS_BY_GATE_ID, "launch_gate_matrix", "launch gate statuses must stay packet-exact", failures)
    _expect(launch_gate.get("expected_evidence_by_gate_id") == EXPECTED_LAUNCH_GATE_EVIDENCE_BY_GATE_ID, "launch_gate_matrix", "launch gate expected evidence must be reported", failures)
    _expect(launch_gate.get("evidence_by_gate_id") == EXPECTED_LAUNCH_GATE_EVIDENCE_BY_GATE_ID, "launch_gate_matrix", "launch gate evidence must stay packet-exact", failures)
    _expect(launch_gate.get("gate_inventory_exact") is True, "launch_gate_matrix", "launch gate inventory must be exact", failures)
    _expect(
        not any(_string_list(launch_gate, key, "launch_gate_matrix", failures) for key in ("missing_gate_ids", "extra_gate_ids")) and not any(launch_gate.get(key) for key in ("status_mismatches", "packet_text_mismatches", "evidence_mismatches")),
        "launch_gate_matrix",
        "launch gate matrix must not report inventory deltas",
        failures,
    )
    open_launch_gates = set(_string_list(launch_gate, "open_gate_ids", "launch_gate_matrix", failures))
    _expect(open_launch_gates == ALLOWED_OPEN_LAUNCH_GATES, "launch_gate_matrix", f"open launch gates must exactly match pre-provider dependencies: {sorted(open_launch_gates)}", failures)
    _expect(launch_gate.get("launch_ready") is False, "launch_gate_matrix", "pre-provider report must not claim external launch readiness", failures)

    _expect(readiness.get("schema_version") == "phase6.launch_readiness_board.v1", "readiness_board", "unexpected readiness-board schema", failures)
    _expect(readiness.get("tracking_gate_passed") is True, "readiness_board", "tracking gate must pass", failures)
    _expect(int(readiness.get("failure_count") or 0) == 0, "readiness_board", "failure_count must be zero", failures)
    _expect(tuple(_string_list(readiness, "expected_blocker_ids", "readiness_board", failures)) == EXPECTED_READINESS_BLOCKER_IDS, "readiness_board", "readiness board expected blocker ids must be reported", failures)
    _expect(tuple(_string_list(readiness, "observed_blocker_ids", "readiness_board", failures)) == EXPECTED_READINESS_BLOCKER_IDS, "readiness_board", "readiness board blocker ids must stay packet-exact", failures)
    _expect(readiness.get("expected_blocker_status_by_id") == EXPECTED_READINESS_BLOCKER_STATUS_BY_ID, "readiness_board", "readiness board expected blocker statuses must be reported", failures)
    _expect(readiness.get("blocker_status_by_id") == EXPECTED_READINESS_BLOCKER_STATUS_BY_ID, "readiness_board", "readiness board blocker statuses must stay packet-exact", failures)
    _expect(readiness.get("expected_blocker_evidence_by_id") == EXPECTED_READINESS_BLOCKER_EVIDENCE_BY_ID, "readiness_board", "readiness board expected blocker evidence must be reported", failures)
    _expect(readiness.get("blocker_evidence_by_id") == EXPECTED_READINESS_BLOCKER_EVIDENCE_BY_ID, "readiness_board", "readiness board blocker evidence must stay packet-exact", failures)
    _expect(tuple(_string_list(readiness, "expected_demo_asset_ids", "readiness_board", failures)) == EXPECTED_DEMO_ASSET_IDS, "readiness_board", "readiness board expected demo asset ids must be reported", failures)
    _expect(tuple(_string_list(readiness, "observed_demo_asset_ids", "readiness_board", failures)) == EXPECTED_DEMO_ASSET_IDS, "readiness_board", "readiness board demo asset ids must stay packet-exact", failures)
    _expect(readiness.get("expected_demo_asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID, "readiness_board", "readiness board expected demo asset statuses must be reported", failures)
    _expect(readiness.get("demo_asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID, "readiness_board", "readiness board demo asset statuses must stay packet-exact", failures)
    _expect(tuple(_string_list(readiness, "expected_rollback_action_ids", "readiness_board", failures)) == EXPECTED_READINESS_ROLLBACK_ACTION_IDS, "readiness_board", "readiness board expected rollback action ids must be reported", failures)
    _expect(tuple(_string_list(readiness, "observed_rollback_action_ids", "readiness_board", failures)) == EXPECTED_READINESS_ROLLBACK_ACTION_IDS, "readiness_board", "readiness board rollback action ids must stay packet-exact", failures)
    _expect(readiness.get("board_inventory_exact") is True, "readiness_board", "readiness board inventory must be exact", failures)
    _expect(
        not any(_string_list(readiness, key, "readiness_board", failures) for key in ("missing_blocker_ids", "extra_blocker_ids", "missing_demo_asset_ids", "extra_demo_asset_ids", "missing_rollback_action_ids", "extra_rollback_action_ids")) and not any(readiness.get(key) for key in ("blocker_status_mismatches", "blocker_evidence_mismatches", "demo_asset_status_mismatches")),
        "readiness_board",
        "readiness board must not report inventory deltas",
        failures,
    )
    open_blockers = set(_string_list(readiness, "open_blocker_ids", "readiness_board", failures))
    _expect(open_blockers == ALLOWED_OPEN_BLOCKERS, "readiness_board", f"open blockers must exactly match pre-provider dependencies: {sorted(open_blockers)}", failures)
    _expect(int(readiness.get("open_demo_asset_count") or 0) == 0, "readiness_board", "all must-have demo assets must be tracked complete", failures)
    _expect(readiness.get("launch_ready") is False, "readiness_board", "pre-provider report must not claim external launch readiness", failures)

    _expect(container.get("schema_version") == "phase6.container_launch_preflight.v1", "container_launch_preflight", "unexpected container schema", failures)
    _expect(container.get("gate_passed") is True, "container_launch_preflight", "container preflight must pass", failures)
    _expect(container.get("provider_target_required") is True, "container_launch_preflight", "provider-target boundary must stay explicit", failures)
    _expect(container.get("lighthouse_still_required") is True, "container_launch_preflight", "Lighthouse boundary must stay explicit", failures)
    _expect(container.get("sensitive_env_inline_secret_check") is True, "container_launch_preflight", "container preflight must reject inline sensitive env values", failures)
    _expect(container.get("worker_healthcheck_required") is True, "container_launch_preflight", "container preflight must require async worker healthcheck", failures)
    _expect(container.get("worker_healthcheck_non_mutating") is True, "container_launch_preflight", "container worker healthcheck must not consume queued jobs", failures)
    _expect(int(container.get("required_api_env_placeholder_count") or 0) >= 18, "container_launch_preflight", "container preflight must track API provider/env placeholders", failures)
    _expect(int(container.get("required_worker_env_placeholder_count") or 0) >= 7, "container_launch_preflight", "container preflight must track worker provider/env placeholders", failures)

    _validate_agno_promotion_gate(agno_promotion_gate, failures)

    _expect(final_host.get("schema_version") == "phase6.final_host_performance_review.v1", "final_host_performance_review", "unexpected final-host schema", failures)
    _expect(final_host.get("gate_passed") is True, "final_host_performance_review", "final-host performance review gate must pass", failures)
    _expect(final_host.get("automated_prerequisites_passed") is True, "final_host_performance_review", "automated final-host prerequisites must pass", failures)
    _expect(final_host.get("provider_target_required") is True, "final_host_performance_review", "provider target must still be required", failures)
    _expect(final_host.get("lighthouse_still_required") is True, "final_host_performance_review", "Lighthouse must still be required", failures)
    _expect(final_host.get("manual_review_required") is True, "final_host_performance_review", "manual final-host review must remain required", failures)
    final_host_browser_lab = final_host.get("browser_lab_summary") if isinstance(final_host.get("browser_lab_summary"), dict) else {}
    _expect(bool(final_host_browser_lab), "final_host_performance_review", "browser lab artifact boundary must be tracked", failures)
    _expect(final_host_browser_lab.get("required_for_final_host_review") is True, "final_host_performance_review", "browser lab artifact must remain required for final-host review", failures)
    _expect(final_host_browser_lab.get("required_for_pre_provider") is False, "final_host_performance_review", "browser lab artifact must not block provider-neutral readiness", failures)
    _expect(
        final_host_browser_lab.get("artifact_status") in {"missing", "validated"},
        "final_host_performance_review",
        "browser lab artifact status must be explicit",
        failures,
    )

    _expect(frontend_events.get("schema_version") == "phase6.frontend_events.v1", "frontend_events", "unexpected frontend-events schema", failures)
    _expect(frontend_events.get("gate_passed") is True, "frontend_events", "frontend event taxonomy/privacy gate must pass", failures)
    _expect(int(frontend_events.get("failure_count") or 0) == 0, "frontend_events", "frontend event failure_count must be zero", failures)
    _expect(int(frontend_events.get("packet_event_group_count") or 0) == 13, "frontend_events", "frontend event gate must track all 13 packet event rows", failures)
    _expect(int(frontend_events.get("required_event_count") or 0) == 25, "frontend_events", "frontend event gate must expand to all 25 concrete events", failures)
    _expect(int(frontend_events.get("frontend_event_count") or 0) == 25, "frontend_events", "frontend event gate must keep frontend taxonomy parity", failures)
    _expect(int(frontend_events.get("server_schema_event_count") or 0) == 25, "frontend_events", "frontend event gate must keep backend schema parity", failures)
    required_event_names = tuple(_string_list(frontend_events, "required_event_names", "frontend_events", failures))
    _expect(tuple(_string_list(frontend_events, "frontend_event_names", "frontend_events", failures)) == required_event_names, "frontend_events", "frontend event names must exactly match packet expansion", failures)
    _expect(tuple(_string_list(frontend_events, "server_schema_event_names", "frontend_events", failures)) == required_event_names, "frontend_events", "backend event names must exactly match packet expansion", failures)
    _expect(frontend_events.get("event_taxonomy_exact") is True, "frontend_events", "frontend/backend event taxonomy must be exact", failures)
    _expect(not _string_list(frontend_events, "missing_frontend_event_names", "frontend_events", failures), "frontend_events", "frontend event taxonomy must not miss packet events", failures)
    _expect(not _string_list(frontend_events, "extra_frontend_event_names", "frontend_events", failures), "frontend_events", "frontend event taxonomy must not include non-packet events", failures)
    _expect(not _string_list(frontend_events, "missing_server_schema_event_names", "frontend_events", failures), "frontend_events", "backend event taxonomy must not miss packet events", failures)
    _expect(not _string_list(frontend_events, "extra_server_schema_event_names", "frontend_events", failures), "frontend_events", "backend event taxonomy must not include non-packet events", failures)
    required_privacy_keys = tuple(_string_list(frontend_events, "required_privacy_keys", "frontend_events", failures))
    _expect(tuple(_string_list(frontend_events, "frontend_privacy_keys", "frontend_events", failures)) == required_privacy_keys, "frontend_events", "frontend privacy keys must exactly match the required restricted-key set", failures)
    _expect(tuple(_string_list(frontend_events, "server_privacy_keys", "frontend_events", failures)) == required_privacy_keys, "frontend_events", "backend privacy keys must exactly match the required restricted-key set", failures)
    _expect(frontend_events.get("privacy_key_taxonomy_exact") is True, "frontend_events", "frontend/backend privacy key taxonomy must be exact", failures)
    _expect(not _string_list(frontend_events, "missing_frontend_privacy_keys", "frontend_events", failures), "frontend_events", "frontend privacy key taxonomy must not miss restricted keys", failures)
    _expect(not _string_list(frontend_events, "extra_frontend_privacy_keys", "frontend_events", failures), "frontend_events", "frontend privacy key taxonomy must not include non-required keys", failures)
    _expect(not _string_list(frontend_events, "missing_server_privacy_keys", "frontend_events", failures), "frontend_events", "backend privacy key taxonomy must not miss restricted keys", failures)
    _expect(not _string_list(frontend_events, "extra_server_privacy_keys", "frontend_events", failures), "frontend_events", "backend privacy key taxonomy must not include non-required keys", failures)
    _expect(frontend_events.get("frontend_private_metadata_rejection_covered") is True, "frontend_events", "frontend event metadata privacy test must stay covered", failures)
    _expect(frontend_events.get("backend_private_metadata_rejection_covered") is True, "frontend_events", "backend event metadata privacy test must stay covered", failures)
    _expect(frontend_events.get("frontend_rum_metadata_redaction_covered") is True, "frontend_events", "frontend RUM metadata redaction test must stay covered", failures)
    _expect(frontend_events.get("frontend_telemetry_failure_event_covered") is True, "frontend_events", "frontend telemetry failure observability test must stay covered", failures)
    _expect(frontend_events.get("backend_rum_metadata_redaction_covered") is True, "frontend_events", "backend RUM metadata redaction test must stay covered", failures)
    _expect(frontend_events.get("backend_unknown_event_rejection_covered") is True, "frontend_events", "backend unknown-event rejection test must stay covered", failures)

    _expect(frontend_qa_matrix.get("schema_version") == "phase6.frontend_qa_matrix.v1", "frontend_qa_matrix", "unexpected frontend QA matrix schema", failures)
    _expect(frontend_qa_matrix.get("gate_passed") is True, "frontend_qa_matrix", "frontend QA matrix gate must pass", failures)
    _expect(int(frontend_qa_matrix.get("failure_count") or 0) == 0, "frontend_qa_matrix", "frontend QA matrix failure_count must be zero", failures)
    _expect(int(frontend_qa_matrix.get("row_count") or 0) == 10, "frontend_qa_matrix", "frontend QA matrix must track all 10 packet rows", failures)
    _expect(
        tuple(_string_list(frontend_qa_matrix, "columns", "frontend_qa_matrix", failures)) == EXPECTED_FRONTEND_QA_MATRIX_COLUMNS,
        "frontend_qa_matrix",
        "frontend QA matrix columns must stay packet-exact",
        failures,
    )
    _expect(int(frontend_qa_matrix.get("blocker_count") or 0) == 9, "frontend_qa_matrix", "frontend QA matrix must keep 9 blocker rows", failures)
    _expect(int(frontend_qa_matrix.get("monitor_count") or 0) == 1, "frontend_qa_matrix", "frontend QA matrix must keep 1 monitor row", failures)
    _expect(tuple(_string_list(frontend_qa_matrix, "expected_test_areas", "frontend_qa_matrix", failures)) == EXPECTED_TEST_AREA_IDS, "frontend_qa_matrix", "frontend QA matrix expected test areas must be reported", failures)
    _expect(tuple(_string_list(frontend_qa_matrix, "observed_test_areas", "frontend_qa_matrix", failures)) == EXPECTED_TEST_AREA_IDS, "frontend_qa_matrix", "frontend QA matrix test areas must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_qa_matrix, "expected_blocker_test_areas", "frontend_qa_matrix", failures)) == EXPECTED_BLOCKER_TEST_AREA_IDS, "frontend_qa_matrix", "frontend QA matrix expected blocker areas must be reported", failures)
    _expect(tuple(_string_list(frontend_qa_matrix, "observed_blocker_test_areas", "frontend_qa_matrix", failures)) == EXPECTED_BLOCKER_TEST_AREA_IDS, "frontend_qa_matrix", "frontend QA matrix blocker areas must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_qa_matrix, "expected_monitor_test_areas", "frontend_qa_matrix", failures)) == EXPECTED_MONITOR_TEST_AREA_IDS, "frontend_qa_matrix", "frontend QA matrix expected monitor areas must be reported", failures)
    _expect(tuple(_string_list(frontend_qa_matrix, "observed_monitor_test_areas", "frontend_qa_matrix", failures)) == EXPECTED_MONITOR_TEST_AREA_IDS, "frontend_qa_matrix", "frontend QA matrix monitor areas must stay packet-exact", failures)
    _expect(frontend_qa_matrix.get("row_inventory_exact") is True, "frontend_qa_matrix", "frontend QA matrix row inventory must be exact", failures)
    _expect(
        not any(_string_list(frontend_qa_matrix, key, "frontend_qa_matrix", failures) for key in ("missing_test_areas", "extra_test_areas")),
        "frontend_qa_matrix",
        "frontend QA matrix must not report row deltas",
        failures,
    )
    _expect(frontend_qa_matrix.get("evidence_inventory_exact") is True, "frontend_qa_matrix", "frontend QA matrix evidence inventory must be exact", failures)
    _expect(
        not any(_string_list(frontend_qa_matrix, key, "frontend_qa_matrix", failures) for key in ("missing_evidence_areas", "extra_evidence_areas")) and not any(frontend_qa_matrix.get(key) for key in ("missing_evidence_by_area", "extra_evidence_by_area")),
        "frontend_qa_matrix",
        "frontend QA matrix must not report evidence deltas",
        failures,
    )
    _expect(
        not _string_list(frontend_qa_matrix, "extra_evidence_areas", "frontend_qa_matrix", failures),
        "frontend_qa_matrix",
        "frontend QA matrix must not carry non-packet evidence areas",
        failures,
    )
    _expect(frontend_qa_matrix.get("all_evidence_paths_exist") is True, "frontend_qa_matrix", "frontend QA matrix evidence paths must exist", failures)

    _expect(frontend_performance.get("schema_version") == "phase6.frontend_performance_budget_gate.v1", "frontend_performance_budget", "unexpected frontend performance-budget schema", failures)
    _expect(frontend_performance.get("gate_passed") is True, "frontend_performance_budget", "frontend performance budget gate must pass", failures)
    _expect(int(frontend_performance.get("failure_count") or 0) == 0, "frontend_performance_budget", "frontend performance budget failure_count must be zero", failures)
    _expect(int(frontend_performance.get("packet_blocker_row_count") or 0) == 11, "frontend_performance_budget", "frontend performance budget must track all 11 blocker rows", failures)
    _expect(int(frontend_performance.get("mapped_budget_count") or 0) == 11, "frontend_performance_budget", "frontend performance budget must map all 11 blocker rows", failures)
    _expect(tuple(_string_list(frontend_performance, "packet_metric_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_PACKET_METRIC_IDS, "frontend_performance_budget", "frontend performance packet metrics must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_performance, "expected_packet_metric_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_PACKET_METRIC_IDS, "frontend_performance_budget", "frontend performance expected packet metrics must be reported", failures)
    _expect(tuple(_string_list(frontend_performance, "packet_blocker_metric_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BLOCKER_PACKET_METRIC_IDS, "frontend_performance_budget", "frontend performance blocker packet metrics must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_performance, "expected_blocker_packet_metric_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BLOCKER_PACKET_METRIC_IDS, "frontend_performance_budget", "frontend performance expected blocker packet metrics must be reported", failures)
    _expect(tuple(_string_list(frontend_performance, "expected_budget_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS, "frontend_performance_budget", "frontend performance expected budget ids must be reported", failures)
    _expect(tuple(_string_list(frontend_performance, "required_budget_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS, "frontend_performance_budget", "frontend performance required budget ids must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_performance, "frontend_budget_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS, "frontend_performance_budget", "frontend performance frontend budget ids must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_performance, "server_budget_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS, "frontend_performance_budget", "frontend performance backend budget ids must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_performance, "schema_metric_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS, "frontend_performance_budget", "frontend performance schema metric ids must stay packet-exact", failures)
    _expect(int(frontend_performance.get("documented_exception_count") or 0) == 1, "frontend_performance_budget", "frontend performance budget must keep the monitor-only exception documented", failures)
    _expect(tuple(_string_list(frontend_performance, "documented_exception_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_EXCEPTION_IDS, "frontend_performance_budget", "frontend performance documented exception ids must stay packet-exact", failures)
    _expect(tuple(_string_list(frontend_performance, "expected_documented_exception_ids", "frontend_performance_budget", failures)) == EXPECTED_FRONTEND_PERFORMANCE_EXCEPTION_IDS, "frontend_performance_budget", "frontend performance expected exception ids must be reported", failures)
    _expect(frontend_performance.get("budget_manifest_exact") is True, "frontend_performance_budget", "frontend performance budget manifest must be exact", failures)
    _expect(
        not any(
            _string_list(frontend_performance, key, "frontend_performance_budget", failures)
            for key in (
                "missing_packet_metric_ids",
                "extra_packet_metric_ids",
                "missing_blocker_packet_metric_ids",
                "extra_blocker_packet_metric_ids",
                "missing_frontend_budget_ids",
                "extra_frontend_budget_ids",
                "missing_server_budget_ids",
                "extra_server_budget_ids",
                "missing_schema_metric_ids",
                "extra_schema_metric_ids",
                "missing_documented_exception_ids",
                "extra_documented_exception_ids",
            )
        ),
        "frontend_performance_budget",
        "frontend performance budget must not report contract deltas",
        failures,
    )

    _expect(frontend_bundle.get("schema_version") == "phase6.frontend_bundle_budget.v1", "frontend_bundle_budget", "unexpected frontend-bundle schema", failures)
    _expect(frontend_bundle.get("gate_passed") is True, "frontend_bundle_budget", "frontend bundle budget gate must pass", failures)
    _expect(int(frontend_bundle.get("failure_count") or 0) == 0, "frontend_bundle_budget", "frontend bundle failure_count must be zero", failures)
    bundle_budget_ids = tuple(_string_list(frontend_bundle, "budget_ids", "frontend_bundle_budget", failures))
    _expect(bundle_budget_ids == EXPECTED_BUNDLE_BUDGET_IDS, "frontend_bundle_budget", f"frontend bundle budget ids must exactly match {list(EXPECTED_BUNDLE_BUDGET_IDS)}", failures)
    _expect(tuple(_string_list(frontend_bundle, "expected_budget_ids", "frontend_bundle_budget", failures)) == EXPECTED_BUNDLE_BUDGET_IDS, "frontend_bundle_budget", "frontend bundle expected budget ids must be reported", failures)
    _expect(frontend_bundle.get("budget_manifest_exact") is True, "frontend_bundle_budget", "frontend bundle budget manifest must be exact", failures)
    _expect(int(frontend_bundle.get("route_budget_count") or 0) == len(EXPECTED_BUNDLE_BUDGET_IDS), "frontend_bundle_budget", "route-level bundle budgets must exactly cover app, hosted, public, and CSS assets", failures)
    _expect(not _string_list(frontend_bundle, "unbudgeted_assets", "frontend_bundle_budget", failures), "frontend_bundle_budget", "frontend bundle must not include unbudgeted JS/CSS assets", failures)
    _expect(not _string_list(frontend_bundle, "html_reference_missing", "frontend_bundle_budget", failures), "frontend_bundle_budget", "app shell entry assets must be referenced by index.html", failures)
    _expect(int(frontend_bundle.get("asset_count") or 0) == int(frontend_bundle.get("budgeted_asset_count") or -1), "frontend_bundle_budget", "all frontend JS/CSS assets must be covered by a budget row", failures)

    _expect(human_signoff.get("schema_version") == "phase6.human_signoff_decisions.v1", "human_signoff_decisions", "unexpected human-signoff schema", failures)
    _expect(human_signoff.get("tracking_gate_passed") is True, "human_signoff_decisions", "tracking gate must pass", failures)
    _expect(int(human_signoff.get("failure_count") or 0) == 0, "human_signoff_decisions", "failure_count must be zero", failures)
    _expect(tuple(_string_list(human_signoff, "expected_decision_ids", "human_signoff_decisions", failures)) == EXPECTED_SIGNOFF_DECISION_ID_LIST, "human_signoff_decisions", "expected signoff decision ids must be reported", failures)
    _expect(tuple(_string_list(human_signoff, "observed_decision_ids", "human_signoff_decisions", failures)) == EXPECTED_SIGNOFF_DECISION_ID_LIST, "human_signoff_decisions", "observed signoff decision ids must stay exact", failures)
    _expect(human_signoff.get("expected_pre_provider_status_by_decision_id") == EXPECTED_SIGNOFF_PRE_PROVIDER_STATUS_BY_DECISION, "human_signoff_decisions", "expected pre-provider signoff statuses must be reported", failures)
    _expect(human_signoff.get("status_by_decision_id") == EXPECTED_SIGNOFF_PRE_PROVIDER_STATUS_BY_DECISION, "human_signoff_decisions", "pre-provider signoff statuses must stay exact", failures)
    _expect(human_signoff.get("expected_item_type_by_decision_id") == EXPECTED_SIGNOFF_ITEM_TYPE_BY_DECISION, "human_signoff_decisions", "expected signoff item types must be reported", failures)
    _expect(human_signoff.get("item_type_by_decision_id") == EXPECTED_SIGNOFF_ITEM_TYPE_BY_DECISION, "human_signoff_decisions", "signoff item types must stay exact", failures)
    _expect(human_signoff.get("expected_owner_role_by_decision_id") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DECISION, "human_signoff_decisions", "expected signoff owner roles must be reported", failures)
    _expect(human_signoff.get("owner_role_by_decision_id") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DECISION, "human_signoff_decisions", "signoff owner roles must stay exact", failures)
    _expect(human_signoff.get("pre_provider_decision_inventory_exact") is True, "human_signoff_decisions", "pre-provider signoff decision inventory must be exact", failures)
    _expect(
        not any(_string_list(human_signoff, key, "human_signoff_decisions", failures) for key in ("missing_decision_ids", "extra_decision_ids"))
        and not any(human_signoff.get(key) for key in ("status_mismatches", "item_type_mismatches", "owner_role_mismatches")),
        "human_signoff_decisions",
        "human signoff decisions must not report inventory deltas",
        failures,
    )
    _expect(not _string_list(human_signoff, "blocked_ids", "human_signoff_decisions", failures), "human_signoff_decisions", "no signoff item may be blocked", failures)
    pending_signoffs = set(_string_list(human_signoff, "pending_ids", "human_signoff_decisions", failures))
    _expect(pending_signoffs == ALLOWED_PENDING_SIGNOFFS, "human_signoff_decisions", f"pending signoffs must exactly match pre-provider dependencies: {sorted(pending_signoffs)}", failures)
    _expect(human_signoff.get("launch_signoff_complete") is False, "human_signoff_decisions", "pre-provider report must not claim launch signoff complete", failures)

    _expect(human_signoff_packet.get("schema_version") == "phase6.human_signoff_packet.v1", "human_signoff_packet", "unexpected human-signoff packet schema", failures)
    _expect(human_signoff_packet.get("gate_passed") is True, "human_signoff_packet", "human signoff packet gate must pass", failures)
    _expect(human_signoff_packet.get("review_ready") is True, "human_signoff_packet", "human signoff packet must be review-ready", failures)
    _expect(human_signoff_packet.get("launch_signoff_complete") is False, "human_signoff_packet", "human signoff packet must not self-approve external launch", failures)
    _expect(int(human_signoff_packet.get("failure_count") or 0) == 0, "human_signoff_packet", "human signoff packet failure_count must be zero", failures)
    packet_signoff_ids = {str(item.get("item_id") or "") for item in human_signoff_packet.get("signoff_items") or [] if isinstance(item, dict)}
    packet_rehearsal_ids = {str(item.get("item_id") or "") for item in human_signoff_packet.get("rehearsal_items") or [] if isinstance(item, dict)}
    _expect(packet_signoff_ids == EXPECTED_HUMAN_SIGNOFF_PACKET_ITEMS, "human_signoff_packet", "human signoff packet must expose the expected signoff items", failures)
    _expect(packet_rehearsal_ids == EXPECTED_HUMAN_SIGNOFF_REHEARSAL_ITEMS, "human_signoff_packet", "human signoff packet must expose the expected rehearsal items", failures)
    packet_summaries = human_signoff_packet.get("summaries") if isinstance(human_signoff_packet.get("summaries"), dict) else {}
    packet_rate_limits = packet_summaries.get("rate_limits_quotas") if isinstance(packet_summaries.get("rate_limits_quotas"), dict) else {}
    _expect(packet_rate_limits.get("gate_passed") is True, "human_signoff_packet", "human signoff packet must summarize passing rate-limit/quota gate", failures)
    _expect(
        packet_rate_limits.get("public_demo_requires_redis_rate_limit") is True,
        "human_signoff_packet",
        "human signoff packet must expose public Redis limiter dependency",
        failures,
    )
    _expect(
        packet_rate_limits.get("provider_quota_review_required") is True,
        "human_signoff_packet",
        "human signoff packet must expose provider quota review dependency",
        failures,
    )
    packet_dependencies = packet_summaries.get("pre_provider_dependencies") if isinstance(packet_summaries.get("pre_provider_dependencies"), dict) else {}
    packet_dependency_details = packet_dependencies.get("dependency_details") if isinstance(packet_dependencies.get("dependency_details"), list) else []
    _expect(
        int(packet_dependencies.get("remaining_dependency_count") or 0) == len(EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCIES),
        "human_signoff_packet",
        "human signoff packet must summarize all remaining human/provider dependencies",
        failures,
    )
    _expect(
        _normalize_dependency_details(packet_dependency_details) == _remaining_dependency_details(),
        "human_signoff_packet",
        "human signoff packet dependency details must match pre-provider readiness contract",
        failures,
    )
    _expect(
        packet_dependencies.get("external_launch_ready") is False,
        "human_signoff_packet",
        "human signoff packet dependency summary must not claim external launch readiness",
        failures,
    )
    _expect(
        not list(packet_dependencies.get("missing_source_ids") or []),
        "human_signoff_packet",
        "human signoff packet dependency summary must have no missing source ids",
        failures,
    )

    _expect(owner_staffing.get("schema_version") == "phase6.launch_owner_staffing.v1", "owner_staffing", "unexpected owner-staffing schema", failures)
    _expect(owner_staffing.get("tracking_gate_passed") is True, "owner_staffing", "owner staffing tracking must pass", failures)
    _expect(int(owner_staffing.get("failure_count") or 0) == 0, "owner_staffing", "failure_count must be zero", failures)
    _expect(owner_staffing.get("staffing_ready") is False, "owner_staffing", "named owner replacement must remain open before provider choice", failures)
    _expect(not _string_list(owner_staffing, "missing_roles", "owner_staffing", failures), "owner_staffing", "role coverage must be complete even before names are assigned", failures)
    _expect(not _string_list(owner_staffing, "extra_roles", "owner_staffing", failures), "owner_staffing", "owner staffing must not include non-packet roles", failures)
    _expect(tuple(_string_list(owner_staffing, "expected_role_ids", "owner_staffing", failures)) == EXPECTED_OWNER_ROLE_IDS, "owner_staffing", "owner staffing expected role ids must be reported", failures)
    _expect(tuple(_string_list(owner_staffing, "observed_role_ids", "owner_staffing", failures)) == EXPECTED_OWNER_ROLE_IDS, "owner_staffing", "owner staffing observed role ids must stay exact", failures)
    _expect(tuple(_string_list(owner_staffing, "role_ids", "owner_staffing", failures)) == EXPECTED_OWNER_ROLE_IDS, "owner_staffing", "launch role ids must exactly match the packet staffing contract", failures)
    _expect(owner_staffing.get("expected_role_status_by_id") == EXPECTED_ROLE_STATUS_BY_ID, "owner_staffing", "owner staffing expected role statuses must be reported", failures)
    _expect(owner_staffing.get("role_status_by_id") == EXPECTED_ROLE_STATUS_BY_ID, "owner_staffing", "owner staffing role statuses must stay pre-provider exact", failures)
    _expect(owner_staffing.get("role_inventory_exact") is True, "owner_staffing", "owner staffing role inventory must be exact", failures)
    _expect(int(owner_staffing.get("role_count") or 0) == len(EXPECTED_OWNER_ROLE_IDS), "owner_staffing", "all 10 launch roles must remain tracked", failures)
    _expect(tuple(_string_list(owner_staffing, "expected_rollback_action_ids", "owner_staffing", failures)) == EXPECTED_OWNER_ROLLBACK_ACTION_IDS, "owner_staffing", "owner staffing expected rollback ids must be reported", failures)
    _expect(tuple(_string_list(owner_staffing, "observed_rollback_action_ids", "owner_staffing", failures)) == EXPECTED_OWNER_ROLLBACK_ACTION_IDS, "owner_staffing", "owner staffing observed rollback ids must stay exact", failures)
    _expect(tuple(_string_list(owner_staffing, "rollback_action_ids", "owner_staffing", failures)) == EXPECTED_OWNER_ROLLBACK_ACTION_IDS, "owner_staffing", "rollback action ids must exactly match the packet staffing contract", failures)
    _expect(owner_staffing.get("expected_rollback_owner_role_by_action") == EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION, "owner_staffing", "owner staffing expected rollback owner roles must be reported", failures)
    _expect(owner_staffing.get("rollback_owner_role_by_action") == EXPECTED_ROLLBACK_OWNER_ROLE_BY_ACTION, "owner_staffing", "owner staffing rollback owner roles must stay exact", failures)
    _expect(owner_staffing.get("expected_rollback_backup_role_by_action") == EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION, "owner_staffing", "owner staffing expected rollback backup roles must be reported", failures)
    _expect(owner_staffing.get("rollback_backup_role_by_action") == EXPECTED_ROLLBACK_BACKUP_ROLE_BY_ACTION, "owner_staffing", "owner staffing rollback backup roles must stay exact", failures)
    _expect(owner_staffing.get("rollback_inventory_exact") is True, "owner_staffing", "owner staffing rollback inventory must be exact", failures)
    _expect(int(owner_staffing.get("rollback_action_count") or 0) == len(EXPECTED_OWNER_ROLLBACK_ACTION_IDS), "owner_staffing", "all 5 rollback actions must remain tracked", failures)
    _expect(tuple(_string_list(owner_staffing, "expected_signoff_dependency_ids", "owner_staffing", failures)) == EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS, "owner_staffing", "owner staffing expected signoff dependency ids must be reported", failures)
    _expect(tuple(_string_list(owner_staffing, "observed_signoff_dependency_ids", "owner_staffing", failures)) == EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS, "owner_staffing", "owner staffing observed signoff dependency ids must stay exact", failures)
    _expect(tuple(_string_list(owner_staffing, "signoff_dependency_ids", "owner_staffing", failures)) == EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS, "owner_staffing", "signoff dependency ids must exactly match the packet staffing contract", failures)
    _expect(owner_staffing.get("expected_signoff_owner_role_by_dependency") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY, "owner_staffing", "owner staffing expected signoff owner roles must be reported", failures)
    _expect(owner_staffing.get("signoff_owner_role_by_dependency") == EXPECTED_SIGNOFF_OWNER_ROLE_BY_DEPENDENCY, "owner_staffing", "owner staffing signoff owner roles must stay exact", failures)
    _expect(owner_staffing.get("expected_signoff_status_by_dependency") == EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY, "owner_staffing", "owner staffing expected signoff statuses must be reported", failures)
    _expect(owner_staffing.get("signoff_status_by_dependency") == EXPECTED_SIGNOFF_STATUS_BY_DEPENDENCY, "owner_staffing", "owner staffing signoff statuses must stay exact", failures)
    _expect(owner_staffing.get("signoff_dependency_inventory_exact") is True, "owner_staffing", "owner staffing signoff dependency inventory must be exact", failures)
    _expect(int(owner_staffing.get("signoff_dependency_count") or 0) == len(EXPECTED_OWNER_SIGNOFF_DEPENDENCY_IDS), "owner_staffing", "all 3 external signoff dependencies must remain tracked", failures)
    _expect(not _string_list(owner_staffing, "missing_rollback_actions", "owner_staffing", failures), "owner_staffing", "rollback action coverage must be complete", failures)
    _expect(not _string_list(owner_staffing, "extra_rollback_actions", "owner_staffing", failures), "owner_staffing", "rollback action coverage must not include non-packet actions", failures)
    _expect(not _string_list(owner_staffing, "missing_signoff_dependencies", "owner_staffing", failures), "owner_staffing", "signoff dependency coverage must be complete", failures)
    _expect(not _string_list(owner_staffing, "extra_signoff_dependencies", "owner_staffing", failures), "owner_staffing", "signoff dependency coverage must not include non-packet dependencies", failures)
    _expect(owner_staffing.get("pre_provider_staffing_inventory_exact") is True, "owner_staffing", "owner staffing pre-provider inventory must be exact", failures)
    _expect(
        not any(
            owner_staffing.get(key)
            for key in (
                "role_status_mismatches",
                "rollback_owner_role_mismatches",
                "rollback_backup_role_mismatches",
                "signoff_owner_role_mismatches",
                "signoff_status_mismatches",
            )
        ),
        "owner_staffing",
        "owner staffing must not report inventory mismatches",
        failures,
    )

    _expect(external_links.get("schema_version") == "phase6.external_links.v1", "external_links", "unexpected external-links schema", failures)
    _expect(external_links.get("tracking_gate_passed") is True, "external_links", "external-link tracking must pass", failures)
    _expect(int(external_links.get("failure_count") or 0) == 0, "external_links", "failure_count must be zero", failures)
    _expect(tuple(_string_list(external_links, "expected_link_ids", "external_links", failures)) == EXPECTED_EXTERNAL_LINK_ID_LIST, "external_links", "external links expected ids must be reported", failures)
    _expect(tuple(_string_list(external_links, "observed_link_ids", "external_links", failures)) == EXPECTED_EXTERNAL_LINK_ID_LIST, "external_links", "external links observed ids must stay exact", failures)
    _expect(external_links.get("expected_label_by_link_id") == EXPECTED_LABEL_BY_LINK_ID, "external_links", "external links expected labels must be reported", failures)
    _expect(external_links.get("label_by_link_id") == EXPECTED_LABEL_BY_LINK_ID, "external_links", "external link labels must stay exact", failures)
    _expect(external_links.get("expected_owner_role_by_link_id") == EXPECTED_EXTERNAL_LINK_OWNER_ROLE_BY_LINK_ID, "external_links", "external links expected owner roles must be reported", failures)
    _expect(external_links.get("owner_role_by_link_id") == EXPECTED_EXTERNAL_LINK_OWNER_ROLE_BY_LINK_ID, "external_links", "external link owner roles must stay exact", failures)
    _expect(external_links.get("expected_pre_provider_status_by_link_id") == EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID, "external_links", "external links expected pre-provider statuses must be reported", failures)
    _expect(external_links.get("status_by_link_id") == EXPECTED_PRE_PROVIDER_STATUS_BY_LINK_ID, "external_links", "external link statuses must stay pre-provider exact", failures)
    _expect(external_links.get("expected_required_before_by_link_id") == EXPECTED_REQUIRED_BEFORE_BY_LINK_ID, "external_links", "external links expected required-before map must be reported", failures)
    _expect(external_links.get("required_before_by_link_id") == EXPECTED_REQUIRED_BEFORE_BY_LINK_ID, "external_links", "external link required-before map must stay exact", failures)
    _expect(external_links.get("expected_pre_provider_has_url_by_link_id") == EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID, "external_links", "external links expected pre-provider URL state must be reported", failures)
    _expect(external_links.get("has_url_by_link_id") == EXPECTED_PRE_PROVIDER_HAS_URL_BY_LINK_ID, "external_links", "external links must not claim URLs before public launch inputs exist", failures)
    _expect(
        external_links.get("required_evidence_by_link_id")
        == {link_id: sorted(values) for link_id, values in sorted(REQUIRED_EXTERNAL_LINK_EVIDENCE_BY_LINK_ID.items())},
        "external_links",
        "external links required evidence map must be reported",
        failures,
    )
    _expect(external_links.get("pre_provider_link_inventory_exact") is True, "external_links", "external link pre-provider inventory must be exact", failures)
    pending_links = set(_string_list(external_links, "pending_ids", "external_links", failures))
    _expect(pending_links == ALLOWED_PENDING_EXTERNAL_LINKS, "external_links", f"pending external links must exactly match pre-provider dependencies: {sorted(pending_links)}", failures)
    _expect(external_links.get("external_links_ready") is False, "external_links", "external links should remain pending until final public URLs exist", failures)
    _expect(
        not any(_string_list(external_links, key, "external_links", failures) for key in ("missing_link_ids", "extra_link_ids"))
        and not any(
            external_links.get(key)
            for key in (
                "label_mismatches",
                "owner_role_mismatches",
                "status_mismatches",
                "required_before_mismatches",
                "has_url_mismatches",
                "missing_required_evidence_by_link_id",
            )
        ),
        "external_links",
        "external links must not report inventory deltas",
        failures,
    )

    _expect(launch_leak.get("schema_version") == "phase6.launch_leak_qa.v1", "launch_leak_qa", "unexpected launch leak QA schema", failures)
    _expect(launch_leak.get("gate_passed") is True, "launch_leak_qa", "200-turn launch leak QA must pass", failures)
    _expect(int(launch_leak.get("case_count") or 0) >= 200, "launch_leak_qa", "launch leak QA must cover at least 200 turns", failures)
    _expect(int(launch_leak.get("failure_count") or 0) == 0, "launch_leak_qa", "launch leak QA failure_count must be zero", failures)

    _expect(public_claims.get("schema_version") == "phase6.public_claims_review.v1", "public_claims_review", "unexpected public-claims schema", failures)
    _expect(public_claims.get("gate_passed") is True, "public_claims_review", "public claims automated gate must pass", failures)
    _expect(int(public_claims.get("failure_count") or 0) == 0, "public_claims_review", "public claims failure_count must be zero", failures)
    _expect(public_claims.get("human_signoff_required") is True, "public_claims_review", "human claims signoff must remain explicit", failures)

    _expect(responsive.get("schema_version") == "phase6.responsive_mobile_qa.v1", "responsive_mobile_qa", "unexpected responsive QA schema", failures)
    _expect(responsive.get("automated_gate_passed") is True, "responsive_mobile_qa", "responsive automated gate must pass", failures)
    _expect(responsive.get("manual_review_required") is True, "responsive_mobile_qa", "manual responsive/device review must remain explicit", failures)

    _expect(local_inference.get("schema_version") == "phase6.local_inference_preview.v1", "local_inference_preview", "unexpected local inference schema", failures)
    _expect(local_inference.get("gate_passed") is True, "local_inference_preview", "local inference automated gate must pass", failures)
    _expect(local_inference.get("launch_gate_complete") is True, "local_inference_preview", "launch matrix must mark local inference boundary complete", failures)
    _expect(local_inference.get("human_research_signoff_required") is True, "local_inference_preview", "manual local inference research signoff must remain explicit", failures)
    _expect(local_inference.get("no_download_boundary") is True, "local_inference_preview", "local inference no-download boundary must remain true", failures)
    _expect(local_inference.get("explicit_download_consent_required") is True, "local_inference_preview", "local inference downloads must require explicit consent", failures)
    _expect(local_inference.get("canonical_answer_path") == "server_harness", "local_inference_preview", "canonical local inference answer path must remain server_harness", failures)

    _expect(rate_limits_quotas.get("schema_version") == "phase6.rate_limits_quotas.v1", "rate_limits_quotas", "unexpected rate-limit/quota schema", failures)
    _expect(rate_limits_quotas.get("gate_passed") is True, "rate_limits_quotas", "rate-limit/quota automated gate must pass", failures)
    _expect(rate_limits_quotas.get("checklist_blocker_tracked") is True, "rate_limits_quotas", "packet rate-limit/quota blocker must be tracked", failures)
    _expect(rate_limits_quotas.get("readiness_board_complete") is True, "rate_limits_quotas", "readiness board must mark rate limits/quotas complete", failures)
    _expect(rate_limits_quotas.get("rate_limit_fail_closed_default") is True, "rate_limits_quotas", "rate limiting must fail closed by default", failures)
    _expect(rate_limits_quotas.get("public_demo_requires_redis_rate_limit") is True, "rate_limits_quotas", "public-demo readiness must require Redis-backed rate limiting", failures)
    _expect(rate_limits_quotas.get("provider_quota_review_required") is True, "rate_limits_quotas", "provider quota review must remain explicit", failures)
    _expect(rate_limits_quotas.get("frontend_quota_visible") is True, "rate_limits_quotas", "hosted UI must expose quota status", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "expected_rate_limit_backends", "rate_limits_quotas", failures)) == EXPECTED_RATE_LIMIT_BACKENDS, "rate_limits_quotas", "expected rate-limit backends must be reported", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "rate_limit_backends", "rate_limits_quotas", failures)) == EXPECTED_RATE_LIMIT_BACKENDS, "rate_limits_quotas", "rate-limit backends must stay exact", failures)
    _expect(rate_limits_quotas.get("required_readiness_flags") == REQUIRED_RATE_LIMIT_READINESS_FLAGS, "rate_limits_quotas", "required rate-limit readiness flags must be reported", failures)
    _expect(rate_limits_quotas.get("readiness_flags") == REQUIRED_RATE_LIMIT_READINESS_FLAGS, "rate_limits_quotas", "rate-limit readiness flags must stay exact", failures)
    _expect(not rate_limits_quotas.get("readiness_flag_mismatches"), "rate_limits_quotas", "rate-limit readiness flags must not mismatch", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "quota_keys", "rate_limits_quotas", failures)) == EXPECTED_RATE_LIMIT_QUOTA_KEYS, "rate_limits_quotas", "workspace quota keys must stay packet-exact", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "required_quota_keys", "rate_limits_quotas", failures)) == EXPECTED_RATE_LIMIT_QUOTA_KEYS, "rate_limits_quotas", "required workspace quota keys must be reported", failures)
    _expect(not _string_list(rate_limits_quotas, "missing_quota_keys", "rate_limits_quotas", failures), "rate_limits_quotas", "workspace quota keys must not be missing", failures)
    _expect(not _string_list(rate_limits_quotas, "extra_quota_keys", "rate_limits_quotas", failures), "rate_limits_quotas", "workspace quota keys must not include non-packet keys", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "enforced_quota_keys", "rate_limits_quotas", failures)) == EXPECTED_RATE_LIMIT_QUOTA_KEYS, "rate_limits_quotas", "enforced workspace quota keys must stay packet-exact", failures)
    _expect(not _string_list(rate_limits_quotas, "missing_enforced_quota_keys", "rate_limits_quotas", failures), "rate_limits_quotas", "enforced workspace quota keys must not be missing", failures)
    _expect(not _string_list(rate_limits_quotas, "extra_enforced_quota_keys", "rate_limits_quotas", failures), "rate_limits_quotas", "enforced workspace quota keys must not include non-packet keys", failures)
    _expect(rate_limits_quotas.get("quota_inventory_exact") is True, "rate_limits_quotas", "workspace quota inventory must be exact", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "required_board_evidence_ids", "rate_limits_quotas", failures)) == REQUIRED_RATE_LIMIT_BOARD_EVIDENCE, "rate_limits_quotas", "required rate-limit board evidence ids must be reported", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "board_evidence_ids", "rate_limits_quotas", failures)) == REQUIRED_RATE_LIMIT_BOARD_EVIDENCE, "rate_limits_quotas", "rate-limit board evidence ids must stay exact", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "required_rate_limit_test_ids", "rate_limits_quotas", failures)) == REQUIRED_RATE_LIMIT_TESTS, "rate_limits_quotas", "required rate-limit tests must be reported", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "covered_rate_limit_test_ids", "rate_limits_quotas", failures)) == REQUIRED_RATE_LIMIT_TESTS, "rate_limits_quotas", "rate-limit tests must stay exact", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "required_quota_test_snippets", "rate_limits_quotas", failures)) == REQUIRED_QUOTA_TEST_SNIPPETS, "rate_limits_quotas", "required quota test snippets must be reported", failures)
    _expect(tuple(_string_list(rate_limits_quotas, "covered_quota_test_snippets", "rate_limits_quotas", failures)) == REQUIRED_QUOTA_TEST_SNIPPETS, "rate_limits_quotas", "quota test snippets must stay exact", failures)
    _expect(rate_limits_quotas.get("evidence_inventory_exact") is True, "rate_limits_quotas", "rate-limit evidence inventory must be exact", failures)
    _expect(rate_limits_quotas.get("pre_provider_rate_limit_inventory_exact") is True, "rate_limits_quotas", "rate-limit pre-provider inventory must be exact", failures)
    _expect(
        not any(
            _string_list(rate_limits_quotas, key, "rate_limits_quotas", failures)
            for key in (
                "missing_board_evidence_ids",
                "extra_board_evidence_ids",
                "missing_rate_limit_test_ids",
                "missing_quota_test_snippets",
            )
        ),
        "rate_limits_quotas",
        "rate-limit evidence inventory must not report deltas",
        failures,
    )

    _expect(feedback_review.get("schema_version") == "phase6.feedback_review.v1", "feedback_review", "unexpected feedback-review schema", failures)
    _expect(feedback_review.get("gate_passed") is True, "feedback_review", "feedback review automated gate must pass", failures)
    _expect(feedback_review.get("launch_gate_complete") is True, "feedback_review", "launch matrix must mark feedback review gate complete", failures)
    _expect(feedback_review.get("feedback_endpoint_access_controlled") is True, "feedback_review", "hosted feedback endpoint must stay access-controlled", failures)
    _expect(feedback_review.get("feedback_trace_event_recorded") is True, "feedback_review", "feedback must record trace events", failures)
    _expect(feedback_review.get("eval_candidate_created_from_feedback") is True, "feedback_review", "feedback must create reviewable eval candidates", failures)
    _expect(feedback_review.get("review_and_replay_covered") is True, "feedback_review", "feedback review/replay tests must stay covered", failures)
    _expect(feedback_review.get("quick_feedback_taxonomy_visible") is True, "feedback_review", "quick feedback taxonomy must stay visible", failures)
    _expect(feedback_review.get("admin_triage_taxonomy_visible") is True, "feedback_review", "admin triage taxonomy must stay visible", failures)
    _expect(feedback_review.get("detailed_feedback_controls_visible") is True, "feedback_review", "detailed feedback controls must stay visible", failures)
    _expect(feedback_review.get("frontend_triage_visible") is True, "feedback_review", "hosted UI must expose feedback triage records", failures)
    _expect(feedback_review.get("expected_snippets_by_section") == EXPECTED_FEEDBACK_SNIPPETS_BY_SECTION, "feedback_review", "feedback expected snippet inventory must be reported", failures)
    _expect(feedback_review.get("observed_snippets_by_section") == EXPECTED_FEEDBACK_SNIPPETS_BY_SECTION, "feedback_review", "feedback snippet inventory must stay exact", failures)
    _expect(feedback_review.get("snippet_inventory_exact") is True, "feedback_review", "feedback snippet inventory must be exact", failures)
    _expect(not any(feedback_review.get("missing_snippets_by_section", {}).values()), "feedback_review", "feedback snippet inventory must not report missing snippets", failures)

    _expect(account_backlog.get("schema_version") == "phase6.account_backlog_readiness.v1", "account_backlog", "unexpected account-backlog schema", failures)
    _expect(account_backlog.get("tracking_gate_passed") is True, "account_backlog", "account backlog tracking gate must pass", failures)
    _expect(account_backlog.get("launch_required_features_ready") is True, "account_backlog", "launch-required account features must be ready", failures)
    _expect(int(account_backlog.get("failure_count") or 0) == 0, "account_backlog", "account backlog failure_count must be zero", failures)
    _expect(tuple(_string_list(account_backlog, "expected_feature_ids", "account_backlog", failures)) == EXPECTED_FEATURE_IDS, "account_backlog", "account backlog expected feature ids must be reported", failures)
    _expect(tuple(_string_list(account_backlog, "observed_feature_ids", "account_backlog", failures)) == EXPECTED_FEATURE_IDS, "account_backlog", "account backlog observed feature ids must exactly match the packet", failures)
    _expect(not _string_list(account_backlog, "missing_features", "account_backlog", failures), "account_backlog", "account backlog must not miss packet features", failures)
    _expect(not _string_list(account_backlog, "extra_features", "account_backlog", failures), "account_backlog", "account backlog must not include non-packet features", failures)
    _expect(tuple(_string_list(account_backlog, "feature_ids", "account_backlog", failures)) == EXPECTED_FEATURE_IDS, "account_backlog", "account backlog feature ids must exactly match the packet", failures)
    _expect(account_backlog.get("expected_priority_by_feature") == EXPECTED_PRIORITY_BY_FEATURE, "account_backlog", "account backlog expected priorities must be reported", failures)
    _expect(account_backlog.get("priority_by_feature") == EXPECTED_PRIORITY_BY_FEATURE, "account_backlog", "account backlog priorities must stay packet-exact", failures)
    _expect(account_backlog.get("expected_phase_by_feature") == EXPECTED_PHASE_BY_FEATURE, "account_backlog", "account backlog expected phases must be reported", failures)
    _expect(account_backlog.get("phase_by_feature") == EXPECTED_PHASE_BY_FEATURE, "account_backlog", "account backlog phases must stay packet-exact", failures)
    _expect(account_backlog.get("expected_status_by_feature") == EXPECTED_STATUS_BY_FEATURE, "account_backlog", "account backlog expected statuses must be reported", failures)
    _expect(account_backlog.get("status_by_feature") == EXPECTED_STATUS_BY_FEATURE, "account_backlog", "account backlog statuses must stay packet-exact", failures)
    _expect(account_backlog.get("expected_acceptance_criteria_by_feature") == EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE, "account_backlog", "account backlog expected acceptance criteria must be reported", failures)
    _expect(account_backlog.get("acceptance_criteria_by_feature") == EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE, "account_backlog", "account backlog acceptance criteria must stay packet-exact", failures)
    _expect(account_backlog.get("account_backlog_inventory_exact") is True, "account_backlog", "account backlog inventory must be exact", failures)
    _expect(
        not any(
            account_backlog.get(key)
            for key in ("priority_mismatches", "phase_mismatches", "acceptance_criteria_mismatches")
        ),
        "account_backlog",
        "account backlog inventory must not report field mismatches",
        failures,
    )
    _expect(int(account_backlog.get("feature_count") or 0) == len(EXPECTED_FEATURE_IDS), "account_backlog", "account backlog must track all 10 packet features", failures)
    _expect(tuple(_string_list(account_backlog, "implemented_features", "account_backlog", failures)) == EXPECTED_IMPLEMENTED_FEATURES, "account_backlog", "account backlog implemented features must exactly match launch scope", failures)
    _expect(int(account_backlog.get("implemented_count") or 0) == len(EXPECTED_IMPLEMENTED_FEATURES), "account_backlog", "account backlog must keep 8 implemented launch-scope features", failures)
    deferred_account_features = set(_string_list(account_backlog, "deferred_features", "account_backlog", failures))
    _expect(tuple(_string_list(account_backlog, "deferred_features", "account_backlog", failures)) == EXPECTED_DEFERRED_FEATURES, "account_backlog", "account backlog deferrals must exactly match the packet order", failures)
    _expect(deferred_account_features == ALLOWED_DEFERRED_ACCOUNT_FEATURES, "account_backlog", "account backlog deferred set must match allowed pre-provider account features", failures)

    _expect(account_privacy_rights.get("schema_version") == "phase6.account_privacy_rights.v1", "account_privacy_rights", "unexpected account/privacy-rights schema", failures)
    _expect(account_privacy_rights.get("gate_passed") is True, "account_privacy_rights", "account/privacy-rights automated gate must pass", failures)
    _expect(tuple(_strings(account_privacy_rights.get("expected_control_ids") or [])) == EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS, "account_privacy_rights", "account/privacy control expected IDs must be reported", failures)
    _expect(tuple(_strings(account_privacy_rights.get("observed_control_ids") or [])) == EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS, "account_privacy_rights", "account/privacy control IDs must match expected Phase 6 controls", failures)
    _expect(int(account_privacy_rights.get("control_count") or 0) == len(EXPECTED_ACCOUNT_PRIVACY_CONTROL_IDS), "account_privacy_rights", "account/privacy control count must match expected Phase 6 controls", failures)
    _expect(account_privacy_rights.get("expected_control_status_by_id") == EXPECTED_ACCOUNT_PRIVACY_CONTROL_STATUS_BY_ID, "account_privacy_rights", "account/privacy expected control statuses must be reported", failures)
    _expect(account_privacy_rights.get("control_status_by_id") == EXPECTED_ACCOUNT_PRIVACY_CONTROL_STATUS_BY_ID, "account_privacy_rights", "account/privacy control statuses must remain ready", failures)
    _expect(account_privacy_rights.get("control_evidence_by_id") == EXPECTED_ACCOUNT_PRIVACY_CONTROL_EVIDENCE_BY_ID, "account_privacy_rights", "account/privacy control evidence map must stay exact", failures)
    _expect(account_privacy_rights.get("account_privacy_control_inventory_exact") is True, "account_privacy_rights", "account/privacy control inventory must stay exact", failures)
    _expect(not any(_strings(account_privacy_rights.get(key) or []) for key in ("missing_control_ids", "extra_control_ids")) and not account_privacy_rights.get("control_status_mismatches"), "account_privacy_rights", "account/privacy control inventory must not report deltas", failures)
    _expect(account_privacy_rights.get("expected_snippets_by_section") == EXPECTED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION, "account_privacy_rights", "account/privacy expected snippet inventory must be reported", failures)
    _expect(account_privacy_rights.get("observed_snippets_by_section") == EXPECTED_ACCOUNT_PRIVACY_SNIPPETS_BY_SECTION, "account_privacy_rights", "account/privacy snippet inventory must stay exact", failures)
    _expect(account_privacy_rights.get("snippet_inventory_exact") is True, "account_privacy_rights", "account/privacy snippet inventory must be exact", failures)
    _expect(not any(account_privacy_rights.get("missing_snippets_by_section", {}).values()), "account_privacy_rights", "account/privacy snippet inventory must not report missing snippets", failures)
    _expect(account_privacy_rights.get("auth_gate_complete") is True, "account_privacy_rights", "launch matrix must mark auth/session/privacy gate complete", failures)
    _expect(account_privacy_rights.get("data_gate_complete") is True, "account_privacy_rights", "launch matrix must mark data export/delete gate complete", failures)
    _expect(account_privacy_rights.get("account_backlog_gate_passed") is True, "account_privacy_rights", "account backlog gate must pass", failures)
    _expect(account_privacy_rights.get("password_auth_token_gated") is True, "account_privacy_rights", "password auth/reset flows must stay token gated", failures)
    _expect(account_privacy_rights.get("account_export_covered") is True, "account_privacy_rights", "account export privacy scope must stay covered", failures)
    _expect(account_privacy_rights.get("data_export_excludes_object_bytes_and_vectors") is True, "account_privacy_rights", "account export must keep object bytes and embedding vectors excluded", failures)
    _expect(account_privacy_rights.get("consent_and_retention_covered") is True, "account_privacy_rights", "consent/retention controls must stay covered", failures)
    _expect(account_privacy_rights.get("session_management_covered") is True, "account_privacy_rights", "auth session management must stay covered", failures)
    _expect(account_privacy_rights.get("delete_account_covered") is True, "account_privacy_rights", "account deletion must stay covered", failures)
    _expect(account_privacy_rights.get("delete_workspace_covered") is True, "account_privacy_rights", "workspace deletion must stay covered", failures)
    _expect(account_privacy_rights.get("delete_thread_covered") is True, "account_privacy_rights", "thread deletion must stay covered", failures)
    _expect(account_privacy_rights.get("data_deletion_covered") is True, "account_privacy_rights", "account/workspace/thread data deletion must stay covered", failures)
    _expect(account_privacy_rights.get("sensitive_action_reauth_covered") is True, "account_privacy_rights", "sensitive account actions must require reauth confirmation", failures)
    _expect(account_privacy_rights.get("frontend_privacy_controls_visible") is True, "account_privacy_rights", "hosted UI must expose account privacy controls", failures)

    _expect(admin_trace_access.get("schema_version") == "phase6.admin_trace_access.v1", "admin_trace_access", "unexpected admin-trace-access schema", failures)
    _expect(admin_trace_access.get("gate_passed") is True, "admin_trace_access", "admin trace access automated gate must pass", failures)
    _expect(admin_trace_access.get("launch_gate_complete") is True, "admin_trace_access", "launch matrix must mark admin trace access complete", failures)
    _expect(admin_trace_access.get("admin_roles_restricted") is True, "admin_trace_access", "backend admin routes must remain owner/admin restricted", failures)
    _expect(admin_trace_access.get("phase5_admin_trace_access_controlled") is True, "admin_trace_access", "admin trace allow/deny tests must stay covered", failures)
    _expect(admin_trace_access.get("cross_workspace_denial_covered") is True, "admin_trace_access", "cross-role admin metrics/monitoring denial must stay covered", failures)
    _expect(admin_trace_access.get("admin_ops_frontend_gated") is True, "admin_trace_access", "hosted admin ops UI must remain canAdmin gated", failures)
    _expect(admin_trace_access.get("normal_user_admin_panel_hidden") is True, "admin_trace_access", "normal-user admin panel hidden test must stay covered", failures)
    _expect(admin_trace_access.get("expected_snippets_by_section") == EXPECTED_ADMIN_TRACE_SNIPPETS_BY_SECTION, "admin_trace_access", "admin trace expected snippet inventory must be reported", failures)
    _expect(admin_trace_access.get("observed_snippets_by_section") == EXPECTED_ADMIN_TRACE_SNIPPETS_BY_SECTION, "admin_trace_access", "admin trace snippet inventory must stay exact", failures)
    _expect(admin_trace_access.get("snippet_inventory_exact") is True, "admin_trace_access", "admin trace snippet inventory must be exact", failures)
    _expect(not any(admin_trace_access.get("missing_snippets_by_section", {}).values()), "admin_trace_access", "admin trace snippet inventory must not report missing snippets", failures)

    _expect(reports_source_provenance.get("schema_version") == "phase6.reports_source_provenance.v1", "reports_source_provenance", "unexpected report source/provenance schema", failures)
    _expect(reports_source_provenance.get("gate_passed") is True, "reports_source_provenance", "report source/provenance automated gate must pass", failures)
    _expect(reports_source_provenance.get("launch_gate_complete") is True, "reports_source_provenance", "launch matrix must mark report source/provenance complete", failures)
    _expect(reports_source_provenance.get("schema_covers_all_report_types") is True, "reports_source_provenance", "report manifest schema must cover all Phase 6 report types", failures)
    _expect(reports_source_provenance.get("export_service_covers_all_report_types") is True, "reports_source_provenance", "export service must dispatch all Phase 6 report types", failures)
    _expect(reports_source_provenance.get("tests_cover_all_report_types") is True, "reports_source_provenance", "report regression tests must cover all Phase 6 report types", failures)
    _expect(reports_source_provenance.get("sample_reports_validate") is True, "reports_source_provenance", "public sample reports must validate", failures)
    _expect(reports_source_provenance.get("sample_data_origins_covered") is True, "reports_source_provenance", "public sample reports must mark user-entered, retrieved-prior, and generated-text sections", failures)
    _expect(reports_source_provenance.get("hidden_scaffolding_excluded") is True, "reports_source_provenance", "reports must exclude hidden scaffolding", failures)
    _expect(reports_source_provenance.get("source_provenance_covered") is True, "reports_source_provenance", "reports must keep source/provenance coverage", failures)
    _expect(reports_source_provenance.get("async_export_jobs_covered") is True, "reports_source_provenance", "report async export job status/progress coverage must stay covered", failures)
    _expect(reports_source_provenance.get("expected_snippets_by_section") == EXPECTED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION, "reports_source_provenance", "report provenance expected snippet inventory must be reported", failures)
    _expect(reports_source_provenance.get("observed_snippets_by_section") == EXPECTED_REPORT_PROVENANCE_SNIPPETS_BY_SECTION, "reports_source_provenance", "report provenance snippet inventory must stay exact", failures)
    _expect(reports_source_provenance.get("snippet_inventory_exact") is True, "reports_source_provenance", "report provenance snippet inventory must be exact", failures)
    _expect(not any(reports_source_provenance.get("missing_snippets_by_section", {}).values()), "reports_source_provenance", "report provenance snippet inventory must not report missing snippets", failures)

    _expect(accessibility_primary_flows.get("schema_version") == "phase6.accessibility_primary_flows.v1", "accessibility_primary_flows", "unexpected accessibility primary-flows schema", failures)
    _expect(accessibility_primary_flows.get("gate_passed") is True, "accessibility_primary_flows", "accessibility primary-flows automated gate must pass", failures)
    _expect(accessibility_primary_flows.get("launch_gate_complete") is True, "accessibility_primary_flows", "launch matrix must mark accessibility primary flows complete", failures)
    _expect(accessibility_primary_flows.get("audit_rules_covered") is True, "accessibility_primary_flows", "accessibility audit rules must stay covered", failures)
    _expect(accessibility_primary_flows.get("primary_flow_audited") is True, "accessibility_primary_flows", "real app primary launch flow audit must stay covered", failures)
    _expect(accessibility_primary_flows.get("semantic_tokens_covered") is True, "accessibility_primary_flows", "semantic design tokens must stay covered", failures)
    _expect(accessibility_primary_flows.get("keyboard_and_alert_affordances") is True, "accessibility_primary_flows", "keyboard and alert affordances must stay covered", failures)
    _expect(accessibility_primary_flows.get("low_bandwidth_accessibility_covered") is True, "accessibility_primary_flows", "low-bandwidth accessibility boundary must stay covered", failures)
    _expect(accessibility_primary_flows.get("docs_current") is True, "accessibility_primary_flows", "accessibility documentation must stay current", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "required_audit_rule_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_AUDIT_RULES, "accessibility_primary_flows", "required accessibility audit rules must be reported", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "covered_audit_rule_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_AUDIT_RULES, "accessibility_primary_flows", "accessibility audit rule inventory must stay exact", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "required_primary_flow_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_PRIMARY_FLOW_IDS, "accessibility_primary_flows", "required accessibility primary-flow ids must be reported", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "covered_primary_flow_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_PRIMARY_FLOW_IDS, "accessibility_primary_flows", "accessibility primary-flow inventory must stay exact", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "required_semantic_token_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_SEMANTIC_TOKEN_IDS, "accessibility_primary_flows", "required accessibility semantic tokens must be reported", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "covered_semantic_token_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_SEMANTIC_TOKEN_IDS, "accessibility_primary_flows", "accessibility semantic token inventory must stay exact", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "required_low_bandwidth_reasons", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_LOW_BANDWIDTH_REASONS, "accessibility_primary_flows", "required low-bandwidth reasons must be reported", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "covered_low_bandwidth_reasons", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_LOW_BANDWIDTH_REASONS, "accessibility_primary_flows", "accessibility low-bandwidth reason inventory must stay exact", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "required_launch_gate_evidence_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_LAUNCH_GATE_EVIDENCE, "accessibility_primary_flows", "required accessibility launch-gate evidence ids must be reported", failures)
    _expect(tuple(_string_list(accessibility_primary_flows, "launch_gate_evidence_ids", "accessibility_primary_flows", failures)) == REQUIRED_ACCESSIBILITY_LAUNCH_GATE_EVIDENCE, "accessibility_primary_flows", "accessibility launch-gate evidence inventory must stay exact", failures)
    _expect(accessibility_primary_flows.get("accessibility_inventory_exact") is True, "accessibility_primary_flows", "accessibility inventory must be exact", failures)
    _expect(
        not any(
            _string_list(accessibility_primary_flows, key, "accessibility_primary_flows", failures)
            for key in (
                "missing_audit_rule_ids",
                "missing_primary_flow_ids",
                "missing_semantic_token_ids",
                "missing_low_bandwidth_reasons",
                "missing_launch_gate_evidence_ids",
                "extra_launch_gate_evidence_ids",
            )
        ),
        "accessibility_primary_flows",
        "accessibility inventory must not report deltas",
        failures,
    )

    _expect(demo_assets.get("schema_version") == "phase6.demo_assets.v1", "demo_assets", "unexpected demo-assets schema", failures)
    _expect(demo_assets.get("gate_passed") is True, "demo_assets", "demo-assets automated gate must pass", failures)
    _expect(demo_assets.get("all_assets_complete") is True, "demo_assets", "demo assets must remain complete", failures)
    _expect(tuple(_string_list(demo_assets, "expected_asset_ids", "demo_assets", failures)) == EXPECTED_DEMO_ASSET_ID_LIST, "demo_assets", "demo-assets expected ids must be reported", failures)
    _expect(tuple(_string_list(demo_assets, "observed_asset_ids", "demo_assets", failures)) == EXPECTED_DEMO_ASSET_ID_LIST, "demo_assets", "demo-assets inventory must stay packet-exact", failures)
    _expect(demo_assets.get("expected_asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID, "demo_assets", "demo-assets expected statuses must be reported", failures)
    _expect(demo_assets.get("asset_status_by_id") == EXPECTED_DEMO_ASSET_STATUS_BY_ID, "demo_assets", "demo-assets statuses must stay packet-exact", failures)
    _expect(demo_assets.get("expected_asset_owner_role_by_id") == EXPECTED_DEMO_ASSET_OWNER_ROLE_BY_ID, "demo_assets", "demo-assets expected owner roles must be reported", failures)
    _expect(demo_assets.get("asset_owner_role_by_id") == EXPECTED_DEMO_ASSET_OWNER_ROLE_BY_ID, "demo_assets", "demo-assets owner roles must stay packet-exact", failures)
    _expect(demo_assets.get("expected_asset_packet_text_by_id") == EXPECTED_DEMO_ASSET_PACKET_TEXT_BY_ID, "demo_assets", "demo-assets expected packet text must be reported", failures)
    _expect(demo_assets.get("asset_packet_text_by_id") == EXPECTED_DEMO_ASSET_PACKET_TEXT_BY_ID, "demo_assets", "demo-assets packet text must stay packet-exact", failures)
    _expect(demo_assets.get("demo_asset_inventory_exact") is True, "demo_assets", "demo-assets inventory must be exact", failures)
    _expect(
        not any(_string_list(demo_assets, key, "demo_assets", failures) for key in ("missing_asset_ids", "extra_asset_ids"))
        and not any(demo_assets.get(key) for key in ("status_mismatches", "owner_role_mismatches", "packet_text_mismatches")),
        "demo_assets",
        "demo-assets inventory must not report deltas",
        failures,
    )
    _expect(demo_assets.get("human_review_required") is True, "demo_assets", "human demo-asset review must remain explicit", failures)
    _expect(int(demo_assets.get("public_page_count") or 0) >= 8, "demo_assets", "public demo pages must cover the packet pages", failures)
    sample_report_types = set(_string_list(demo_assets, "sample_report_types", "demo_assets", failures))
    _expect({"thread_report", "field_context_brief", "demo_eval_snapshot"} <= sample_report_types, "demo_assets", "sample reports must cover all Phase 6 public-safe report types", failures)
    _expect(demo_assets.get("data_source_coverage_ready") is True, "demo_assets", "data-source coverage assets must remain ready", failures)
    _expect(demo_assets.get("sample_field_contexts_visible") is True, "demo_assets", "sample field contexts must remain visible", failures)
    _expect(demo_assets.get("demo_script_ready") is True, "demo_assets", "demo script must remain ready", failures)

    _expect(field_context_rehearsal.get("schema_version") == "phase6.field_context_rehearsal_gate.v1", "field_context_rehearsal", "unexpected field-context rehearsal schema", failures)
    _expect(field_context_rehearsal.get("automated_gate_passed") is True, "field_context_rehearsal", "field-context rehearsal automated gate must pass", failures)
    _expect(field_context_rehearsal.get("manual_review_required") is True, "field_context_rehearsal", "manual field-context rehearsal must remain explicit", failures)
    _expect(int(field_context_rehearsal.get("failure_count") or 0) == 0, "field_context_rehearsal", "field-context rehearsal failure_count must be zero", failures)
    required_field_context_surfaces = tuple(_string_list(field_context_rehearsal, "required_surfaces", "field_context_rehearsal", failures))
    _expect(
        required_field_context_surfaces == EXPECTED_FIELD_CONTEXT_REHEARSAL_SURFACES,
        "field_context_rehearsal",
        "field-context rehearsal surfaces must stay packet-exact",
        failures,
    )
    _expect(
        "phase6.browser_field_context_rehearsal.v1" == str(field_context_rehearsal.get("browser_rehearsal_schema") or ""),
        "field_context_rehearsal",
        "field-context browser rehearsal schema must remain explicit",
        failures,
    )
    field_context_evidence = tuple(_string_list(field_context_rehearsal, "evidence", "field_context_rehearsal", failures))
    _expect(
        field_context_evidence == EXPECTED_FIELD_CONTEXT_REHEARSAL_EVIDENCE,
        "field_context_rehearsal",
        "field-context rehearsal evidence paths must stay packet-exact",
        failures,
    )
    _expect(
        tuple(_string_list(field_context_rehearsal, "manual_review_items", "field_context_rehearsal", failures)) == EXPECTED_FIELD_CONTEXT_REHEARSAL_MANUAL_ITEMS,
        "field_context_rehearsal",
        "field-context rehearsal manual review items must stay packet-exact",
        failures,
    )

    _expect(ui_information_architecture.get("schema_version") == "phase6.ui_information_architecture.v1", "ui_information_architecture", "unexpected UI information architecture schema", failures)
    _expect(ui_information_architecture.get("gate_passed") is True, "ui_information_architecture", "UI information architecture automated gate must pass", failures)
    _expect(int(ui_information_architecture.get("area_count") or 0) == 8, "ui_information_architecture", "UI IA must track all eight packet areas", failures)
    _expect(int(ui_information_architecture.get("component_count") or 0) >= 39, "ui_information_architecture", "UI IA must track all packet components", failures)
    _expect(tuple(_string_list(ui_information_architecture, "expected_area_ids", "ui_information_architecture", failures)) == EXPECTED_UI_AREA_IDS, "ui_information_architecture", "UI IA expected area ids must be reported", failures)
    _expect(tuple(_string_list(ui_information_architecture, "observed_area_ids", "ui_information_architecture", failures)) == EXPECTED_UI_AREA_IDS, "ui_information_architecture", "UI IA area inventory must stay exact", failures)
    _expect(ui_information_architecture.get("expected_route_by_area") == EXPECTED_UI_ROUTE_BY_AREA, "ui_information_architecture", "UI IA expected routes must be reported", failures)
    _expect(ui_information_architecture.get("observed_route_by_area") == EXPECTED_UI_ROUTE_BY_AREA, "ui_information_architecture", "UI IA route inventory must stay exact", failures)
    _expect(ui_information_architecture.get("expected_audience_by_area") == EXPECTED_UI_AUDIENCE_BY_AREA, "ui_information_architecture", "UI IA expected audiences must be reported", failures)
    _expect(ui_information_architecture.get("observed_audience_by_area") == EXPECTED_UI_AUDIENCE_BY_AREA, "ui_information_architecture", "UI IA audience inventory must stay exact", failures)
    _expect(tuple(_string_list(ui_information_architecture, "expected_component_ids", "ui_information_architecture", failures)) == EXPECTED_UI_COMPONENT_IDS, "ui_information_architecture", "UI IA expected component ids must be reported", failures)
    _expect(tuple(_string_list(ui_information_architecture, "observed_component_ids", "ui_information_architecture", failures)) == EXPECTED_UI_COMPONENT_IDS, "ui_information_architecture", "UI IA component inventory must stay exact", failures)
    _expect(tuple(_string_list(ui_information_architecture, "component_evidence_ids", "ui_information_architecture", failures)) == EXPECTED_UI_COMPONENT_IDS, "ui_information_architecture", "UI IA component evidence inventory must stay exact", failures)
    _expect(tuple(_string_list(ui_information_architecture, "expected_pending_component_ids", "ui_information_architecture", failures)) == EXPECTED_UI_PENDING_COMPONENT_IDS, "ui_information_architecture", "UI IA expected pending component ids must be reported", failures)
    _expect(tuple(_string_list(ui_information_architecture, "pending_external_component_ids", "ui_information_architecture", failures)) == EXPECTED_UI_PENDING_COMPONENT_IDS, "ui_information_architecture", "UI IA pending component inventory must stay exact", failures)
    _expect(ui_information_architecture.get("pending_component_inventory_exact") is True, "ui_information_architecture", "UI IA pending component inventory must be exact", failures)
    _expect(ui_information_architecture.get("ui_inventory_exact") is True, "ui_information_architecture", "UI IA inventory must be exact", failures)
    _expect(
        not any(
            _string_list(ui_information_architecture, key, "ui_information_architecture", failures)
            for key in (
                "missing_area_ids",
                "extra_area_ids",
                "missing_component_ids",
                "extra_component_ids",
                "missing_component_evidence_ids",
                "extra_component_evidence_ids",
            )
        )
        and not any(
            ui_information_architecture.get(key)
            for key in ("route_mismatches", "audience_mismatches")
        ),
        "ui_information_architecture",
        "UI IA inventory must not report deltas",
        failures,
    )
    _expect(ui_information_architecture.get("all_packet_areas_tracked") is True, "ui_information_architecture", "all packet IA areas must stay tracked", failures)
    _expect(ui_information_architecture.get("all_packet_components_tracked") is True, "ui_information_architecture", "all packet IA components must stay tracked", failures)
    _expect(ui_information_architecture.get("route_projection_review_required") is True, "ui_information_architecture", "single-shell route projection review must remain explicit", failures)
    _expect(ui_information_architecture.get("react_frontend_cutover_verified") is True, "ui_information_architecture", "UI IA must verify React frontend cutover", failures)
    _expect(ui_information_architecture.get("gradio_dependency_removed") is True, "ui_information_architecture", "Gradio dependency must stay removed", failures)
    _expect(int(ui_information_architecture.get("gradio_source_import_count") or 0) == 0, "ui_information_architecture", "Gradio source imports must stay removed", failures)
    _expect(ui_information_architecture.get("literal_packet_routes_implemented") is False, "ui_information_architecture", "pre-provider report must not claim literal route implementation", failures)
    _expect(ui_information_architecture.get("external_launch_ready") is False, "ui_information_architecture", "UI IA must not claim external launch readiness", failures)

    _expect(pwa_offline_lite.get("schema_version") == "phase6.pwa_offline_lite.v1", "pwa_offline_lite", "unexpected PWA/offline-lite schema", failures)
    _expect(pwa_offline_lite.get("gate_passed") is True, "pwa_offline_lite", "PWA/offline-lite automated gate must pass", failures)
    _expect(pwa_offline_lite.get("packet_scope_covered") is True, "pwa_offline_lite", "PWA/offline-lite must cover all packet scope items", failures)
    _expect(pwa_offline_lite.get("installable_shell_ready") is True, "pwa_offline_lite", "installable shell must remain ready", failures)
    _expect(pwa_offline_lite.get("service_worker_cache_bounded") is True, "pwa_offline_lite", "service worker must keep cache boundary bounded", failures)
    _expect(pwa_offline_lite.get("draft_preservation_ready") is True, "pwa_offline_lite", "offline draft preservation must remain ready", failures)
    _expect(pwa_offline_lite.get("scratchpad_local_only") is True, "pwa_offline_lite", "scratchpad must remain local-only", failures)
    _expect(pwa_offline_lite.get("deferred_queue_ready") is True, "pwa_offline_lite", "deferred feedback/report queue must remain ready", failures)
    _expect(pwa_offline_lite.get("deferred_queue_privacy_guarded") is True, "pwa_offline_lite", "deferred feedback/report queue must omit raw user text", failures)
    _expect(pwa_offline_lite.get("no_offline_model_generation") is True, "pwa_offline_lite", "offline model generation must remain blocked in default demo path", failures)
    _expect(pwa_offline_lite.get("external_launch_ready") is False, "pwa_offline_lite", "PWA gate must not claim external launch readiness", failures)
    _expect(pwa_offline_lite.get("expected_snippets_by_section") == EXPECTED_PWA_SNIPPETS_BY_SECTION, "pwa_offline_lite", "PWA expected snippet inventory must be reported", failures)
    _expect(pwa_offline_lite.get("observed_snippets_by_section") == EXPECTED_PWA_SNIPPETS_BY_SECTION, "pwa_offline_lite", "PWA snippet inventory must stay exact", failures)
    _expect(pwa_offline_lite.get("snippet_inventory_exact") is True, "pwa_offline_lite", "PWA snippet inventory must be exact", failures)
    _expect(not any(pwa_offline_lite.get("missing_snippets_by_section", {}).values()), "pwa_offline_lite", "PWA snippet inventory must not report missing snippets", failures)

    _expect(epic_coverage.get("schema_version") == "phase6.epic_coverage.v1", "epic_coverage", "unexpected epic-coverage schema", failures)
    _expect(epic_coverage.get("gate_passed") is True, "epic_coverage", "Phase 6 roadmap epic coverage gate must pass", failures)
    _expect(int(epic_coverage.get("phase_count") or 0) == 7, "epic_coverage", "Phase 6 roadmap coverage must include all seven phases", failures)
    _expect(set(_string_list(epic_coverage, "complete_phase_ids", "epic_coverage", failures)) == {"6.0", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6"}, "epic_coverage", "Phase 6 roadmap coverage must pass phases 6.0 through 6.6", failures)
    _expect(not _string_list(epic_coverage, "incomplete_phase_ids", "epic_coverage", failures), "epic_coverage", "Phase 6 roadmap coverage must not report incomplete phases", failures)
    _expect(_phase_results_are_reconciled(epic_coverage.get("phase_results")), "epic_coverage", "Phase 6 phase-result counts must reconcile with check status maps", failures)
    _expect(epic_coverage.get("manual_or_provider_dependencies_required") is True, "epic_coverage", "epic coverage must keep manual/provider dependencies explicit", failures)
    _expect(epic_coverage.get("external_launch_ready") is False, "epic_coverage", "epic coverage must not claim external launch readiness", failures)

    evidence = {
        "launch_gate_matrix": _display_path(launch_gate_matrix_report),
        "readiness_board": _display_path(readiness_board_report),
        "container_launch_preflight": _display_path(container_report),
        "final_host_performance_review": _display_path(final_host_report),
        "frontend_events": _display_path(frontend_events_report),
        "frontend_qa_matrix": _display_path(frontend_qa_matrix_report),
        "frontend_performance_budget": _display_path(frontend_performance_report),
        "frontend_bundle_budget": _display_path(frontend_bundle_report),
        "human_signoff_decisions": _display_path(human_signoff_report),
        "human_signoff_packet": _display_path(human_signoff_packet_report),
        "owner_staffing": _display_path(owner_staffing_report),
        "external_links": _display_path(external_links_report),
        "launch_leak_qa": _display_path(launch_leak_report),
        "public_claims_review": _display_path(public_claims_report),
        "responsive_mobile_qa": _display_path(responsive_report),
        "local_inference_preview": _display_path(local_inference_report),
        "rate_limits_quotas": _display_path(rate_limits_quotas_report),
        "feedback_review": _display_path(feedback_review_report),
        "account_backlog": _display_path(account_backlog_report),
        "account_privacy_rights": _display_path(account_privacy_rights_report),
        "admin_trace_access": _display_path(admin_trace_access_report),
        "reports_source_provenance": _display_path(reports_source_provenance_report),
        "accessibility_primary_flows": _display_path(accessibility_primary_flows_report),
        "demo_assets": _display_path(demo_assets_report),
        "field_context_rehearsal": _display_path(field_context_rehearsal_report),
        "ui_information_architecture": _display_path(ui_information_architecture_report),
        "pwa_offline_lite": _display_path(pwa_offline_lite_report),
        "epic_coverage": _display_path(epic_coverage_report),
        "agno_promotion_gate": _display_path(agno_promotion_gate_report),
    }
    return {
        "schema_version": REPORT_VERSION,
        "pre_provider_ready": not failures,
        "external_launch_ready": False,
        "provider_target_required": True,
        "human_signoff_required": True,
        "allowed_open_launch_gates": sorted(ALLOWED_OPEN_LAUNCH_GATES),
        "observed_open_launch_gates": sorted(open_launch_gates),
        "allowed_open_blockers": sorted(ALLOWED_OPEN_BLOCKERS),
        "observed_open_blockers": sorted(open_blockers),
        "remaining_dependency_count": len(EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCIES),
        "remaining_provider_or_human_dependencies": list(EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCIES),
        "remaining_provider_or_human_dependency_details": _remaining_dependency_details(),
        "final_host_browser_lab_summary": dict(final_host_browser_lab),
        "evidence": evidence,
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_pre_provider_readiness_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _validate_agno_promotion_gate(report: dict[str, Any], failures: list[dict[str, str]]) -> None:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    rollback = metrics.get("rollback_evidence") if isinstance(metrics.get("rollback_evidence"), dict) else {}
    rollback_checks = rollback.get("checks") if isinstance(rollback.get("checks"), dict) else {}
    _expect(report.get("report_version") == "agno_rag_promotion_gate_v1", "agno_promotion_gate", "unexpected Agno promotion gate schema", failures)
    _expect(report.get("promotion_allowed") is True, "agno_promotion_gate", "Agno promotion gate must pass", failures)
    _expect(int(report.get("gate_count") or 0) == 10, "agno_promotion_gate", "Agno promotion gate must keep all 10 foundation gates", failures)
    _expect(not _string_list(report, "reasons", "agno_promotion_gate", failures), "agno_promotion_gate", "Agno promotion gate reasons must be empty", failures)
    _expect(metrics.get("profile_recommendation") == "promote_agno_replace_legacy", "agno_promotion_gate", "Agno profile must recommend replacement", failures)
    _expect(metrics.get("agno_dependency_available") is True, "agno_promotion_gate", "Agno dependency must be available", failures)
    _expect(metrics.get("legacy_profile_scope") == "benchmark_only_retired_serving_path_removed", "agno_promotion_gate", "legacy profile must remain benchmark-only", failures)
    _expect(metrics.get("resource_singleton_reused") is True, "agno_promotion_gate", "Agno resource singleton reuse must be verified", failures)
    _expect(metrics.get("resource_singleton_reuse_within_budget") is True, "agno_promotion_gate", "Agno resource singleton reuse must stay within budget", failures)
    _expect(metrics.get("agno_index_max_eligible_docs_within_budget") is True, "agno_promotion_gate", "Agno eligible fanout must stay within budget", failures)
    _expect(metrics.get("agno_index_max_scored_candidates_within_budget") is True, "agno_promotion_gate", "Agno scored candidate fanout must stay within budget", failures)
    _expect(metrics.get("agno_index_runtime_caches_within_budget") is True, "agno_promotion_gate", "Agno runtime index caches must stay within budget", failures)
    _expect(not _string_list(metrics, "case_latency_regression_case_ids", "agno_promotion_gate", failures), "agno_promotion_gate", "Agno case latency regressions must be absent", failures)
    _expect(metrics.get("rollback_verified") is True, "agno_promotion_gate", "Agno rollback evidence must be verified", failures)
    _expect(rollback_checks.get("agno_primary_selects_agno") is True, "agno_promotion_gate", "Agno primary runtime must select Agno", failures)
    _expect(rollback_checks.get("legacy_runtime_removed") is True, "agno_promotion_gate", "legacy runtime must remain removed", failures)


def _remaining_dependency_details() -> list[dict[str, Any]]:
    return [
        {
            "dependency_id": str(item["dependency_id"]),
            "category": str(item["category"]),
            "summary": str(item["summary"]),
            "source_ids": list(item["source_ids"]),
        }
        for item in EXPECTED_PENDING_PROVIDER_OR_HUMAN_DEPENDENCY_DETAILS
    ]


def _normalize_dependency_details(value: list[Any]) -> list[dict[str, Any]]:
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


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> None:
    if not condition:
        failures.append({"section": section, "reason": reason})


def _string_list(payload: dict[str, Any], field: str, section: str, failures: list[dict[str, str]]) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list):
        failures.append({"section": section, "reason": f"{field} must be a list"})
        return []
    return _strings(value)


def _strings(value: list[Any]) -> list[str]:
    return [str(item) for item in value if str(item).strip()]


def _phase_results_are_reconciled(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    expected_phases = {"6.0", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6"}
    observed_phases: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            return False
        phase = str(row.get("phase") or "")
        observed_phases.add(phase)
        check_status = row.get("check_status_by_name")
        failed_checks = row.get("failed_checks")
        if not isinstance(check_status, dict) or not isinstance(failed_checks, list):
            return False
        check_count = _int_or_negative_one(row.get("check_count"))
        passed_count = _int_or_negative_one(row.get("passed_check_count"))
        failed_count = _int_or_negative_one(row.get("failed_check_count"))
        observed_failed = sorted(name for name, passed in check_status.items() if passed is not True)
        if check_count != len(check_status):
            return False
        if passed_count != sum(1 for passed in check_status.values() if passed is True):
            return False
        if failed_count != len(failed_checks):
            return False
        if sorted(str(item) for item in failed_checks) != observed_failed:
            return False
        if bool(row.get("automated_gate_passed")) != (failed_count == 0):
            return False
    return observed_phases == expected_phases


def _int_or_negative_one(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
