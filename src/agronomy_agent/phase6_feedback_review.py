from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.feedback_review.v1"
LAUNCH_GATE_ID = "feedback_reviewable_records"
LAUNCH_GATE_TEXT = "Feedback creates reviewable improvement records."

REQUIRED_MATRIX_EVIDENCE = (
    "docs/phase6_feedback_review.md",
    "scripts/validate_phase6_feedback_review.py",
    "tests/test_phase6_feedback_review.py",
    "tests/test_phase4_hosted_api.py",
    "tests/test_phase6_reports.py",
    "frontend/src/HostedPlatform.tsx",
    "frontend/src/App.test.tsx",
)
REQUIRED_ENDPOINT_SNIPPETS = (
    '@app.post("/messages/{message_id}/feedback", status_code=201)',
    "require_thread_for_user(user, message[\"thread_id\"])",
    "require_workspace_role(user, thread[\"workspace_id\"], WORKSPACE_WRITE_ROLES)",
    "store.create_phase4_feedback(",
    "store.update_phase5_turn_feedback(",
    "human_review_status=\"feedback_received\"",
    "TraceProfiler(trace_id=phase5_metrics[\"trace_id\"])",
    "\"feedback.capture\"",
    "if payload.failure_tags or payload.training_consent:",
    "store.create_phase4_eval_candidate(",
    "\"candidate_type\": \"eval_row\"",
    "\"target_component\": \"eval\"",
    "\"feedback\": feedback",
)
REQUIRED_SQLITE_STORAGE_SNIPPETS = (
    "CREATE TABLE IF NOT EXISTS phase4_feedback_events",
    "training_consent INTEGER NOT NULL DEFAULT 0",
    "INSERT INTO phase4_feedback_events",
    "event_type=\"user_feedback\"",
    "append_phase4_trace_event(",
    "list_phase4_feedback_for_thread",
)
REQUIRED_POSTGRES_STORAGE_SNIPPETS = (
    "def create_phase4_feedback(",
    "INSERT INTO feedback_events",
    "training_consent",
    "event_type=\"user_feedback\"",
    "append_phase4_trace_event(",
    "list_phase4_feedback_for_thread",
)
REQUIRED_EVAL_SNIPPETS = (
    "feedback_event_id",
    "review_status",
    "expected_behavior = payload.get(\"ideal_answer\") or feedback.get(\"ideal_answer\")",
    "event_type=\"eval_candidate\"",
    "local_trace_feedback_regression_v1",
)
REQUIRED_FRONTEND_SNIPPETS = (
    "hostedFeedbackQuickTags",
    "missing_important_context",
    "wrong_source_or_weak_evidence",
    "too_generic",
    "too_cautious",
    "exposed_internal_wording",
    "hostedFeedbackTriageTags",
    "safety_issue",
    "retrieval_miss",
    "routing_error",
    "context_packing_error",
    "tool_miss",
    "ui_leak",
    "source_gap",
    "model_generation_failure",
    "saveHostedFeedback",
    "failure_tags: [hostedFeedbackQuickTag, hostedFeedbackTriageTag].filter(Boolean)",
    "training_consent: hostedFeedbackTrainingConsent",
    "sendFrontendEvent('feedback_submitted'",
    "hosted-feedback-rating",
    "hosted-feedback-quick-tag",
    "hosted-feedback-triage-tag",
    "hosted-feedback-correction",
    "hosted-feedback-ideal",
    "hosted-feedback-training-consent",
    "loadEvalCandidates",
    "hosted-eval-candidates",
    "hosted-eval-candidate-evidence",
    "hosted-approve-eval-candidate",
    "hosted-run-eval",
)
REQUIRED_TEST_SNIPPETS = (
    "test_phase4_hosted_thread_chat_trace_feedback_export_flow",
    "failure_tags\": [\"missed_local_calibration\"]",
    "training_consent\": True",
    "assert feedback.status_code == 201",
    "assert candidate[\"review_status\"] == \"pending\"",
    "approved_for_suite",
    "Hosted feedback replay",
    "local_trace_feedback_regression_v1",
    "regression_failures_present",
    "user_feedback",
)
REQUIRED_FRONTEND_TEST_SNIPPETS = (
    "persists hosted feedback and export events into trace view",
    "hosted-feedback",
    "wrong_source_or_weak_evidence",
    "source_gap",
    "Ask for local source coverage first.",
    "Start with source coverage, then explain uncertainty.",
    "user_feedback",
    "eval_candidate",
    "hosted-eval-candidates",
    "hosted-approve-eval-candidate",
    "Hosted feedback replay",
    "regression_failures_present",
    "hosted-eval-candidate-evidence",
)
REQUIRED_REPORT_SNIPPETS = (
    "learning_trace_export",
    "feedback",
    "training_consent",
    "ideal_answer",
    "feedback_training_consent_count",
)
REQUIRED_SCHEMA_SNIPPETS = (
    "rating: HostedRating",
    "failure_tags: list[str]",
    "human_correction: str | None",
    "ideal_answer: str | None",
    "training_consent: bool = False",
)
REQUIRED_DOC_SNIPPETS = (
    "reviewable improvement records",
    "training_consent",
    "quick feedback",
    "admin triage",
)
REQUIRED_LAUNCH_GATE_SNIPPETS: tuple[str, ...] = (
    LAUNCH_GATE_ID,
    "status: complete",
    LAUNCH_GATE_TEXT,
    *REQUIRED_MATRIX_EVIDENCE,
)
REQUIRED_SNIPPETS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "docs": REQUIRED_DOC_SNIPPETS,
    "eval_review": REQUIRED_EVAL_SNIPPETS,
    "frontend": REQUIRED_FRONTEND_SNIPPETS,
    "frontend_tests": REQUIRED_FRONTEND_TEST_SNIPPETS,
    "hosted_api_tests": REQUIRED_TEST_SNIPPETS,
    "launch_gate_matrix": REQUIRED_LAUNCH_GATE_SNIPPETS,
    "reports_exports": REQUIRED_REPORT_SNIPPETS,
    "schemas": REQUIRED_SCHEMA_SNIPPETS,
    "server_app": REQUIRED_ENDPOINT_SNIPPETS,
    "sqlite_store": REQUIRED_SQLITE_STORAGE_SNIPPETS,
    "postgres_store": REQUIRED_POSTGRES_STORAGE_SNIPPETS,
}


def validate_phase6_feedback_review(
    *,
    matrix_path: Path = ROOT / "docs/phase6_launch_gate_matrix.yaml",
    app_path: Path = ROOT / "src/agronomy_agent/server/app.py",
    schema_path: Path = ROOT / "src/agronomy_agent/server/schemas.py",
    sqlite_store_path: Path = ROOT / "src/agronomy_agent/server/storage/db.py",
    postgres_store_path: Path = ROOT / "src/agronomy_agent/server/storage/runtime.py",
    eval_service_path: Path = ROOT / "src/agronomy_agent/server/services/eval_service.py",
    export_service_path: Path = ROOT / "src/agronomy_agent/server/services/export_service.py",
    frontend_path: Path = ROOT / "frontend/src/HostedPlatform.tsx",
    frontend_test_path: Path = ROOT / "frontend/src/App.test.tsx",
    hosted_api_test_path: Path = ROOT / "tests/test_phase4_hosted_api.py",
    reports_test_path: Path = ROOT / "tests/test_phase6_reports.py",
    doc_path: Path = ROOT / "docs/phase6_feedback_review.md",
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    matrix = _load_yaml(matrix_path, "launch_gate_matrix", failures)
    matrix_text = _read_text(matrix_path, "launch_gate_matrix", failures)
    app_text = _read_text(app_path, "server_app", failures)
    schema_text = _read_text(schema_path, "schemas", failures)
    sqlite_text = _read_text(sqlite_store_path, "sqlite_store", failures)
    postgres_text = _read_text(postgres_store_path, "postgres_store", failures)
    eval_text = _read_text(eval_service_path, "eval_service", failures)
    export_text = _read_text(export_service_path, "export_service", failures)
    frontend_text = _read_text(frontend_path, "frontend", failures)
    frontend_test_text = _read_text(frontend_test_path, "frontend_tests", failures)
    hosted_api_test_text = _read_text(hosted_api_test_path, "hosted_api_tests", failures)
    reports_test_text = _read_text(reports_test_path, "report_tests", failures)
    doc_text = _read_text(doc_path, "docs", failures)
    texts_by_section = {
        "docs": doc_text,
        "eval_review": "\n".join([postgres_text, sqlite_text, eval_text]),
        "frontend": frontend_text,
        "frontend_tests": frontend_test_text,
        "hosted_api_tests": hosted_api_test_text,
        "launch_gate_matrix": matrix_text,
        "reports_exports": "\n".join([export_text, reports_test_text]),
        "schemas": schema_text,
        "server_app": app_text,
        "sqlite_store": sqlite_text,
        "postgres_store": postgres_text,
    }

    gate = _launch_gate(matrix)
    _expect(gate is not None, "launch_gate_matrix", "launch matrix must track feedback_reviewable_records", failures)
    if gate is not None:
        _expect(gate.get("packet_text") == LAUNCH_GATE_TEXT, "launch_gate_matrix", "feedback gate packet_text must match packet launch gate", failures)
        _expect(gate.get("status") == "complete", "launch_gate_matrix", "feedback gate must remain complete", failures)
        evidence = {str(item) for item in gate.get("evidence") or []}
        for required in REQUIRED_MATRIX_EVIDENCE:
            _expect(required in evidence, "launch_gate_matrix", f"feedback gate evidence must include {required}", failures)
            _expect((ROOT / required).exists(), "launch_gate_matrix", f"feedback gate evidence path missing: {required}", failures)

    for field in REQUIRED_SCHEMA_SNIPPETS:
        _expect(field in schema_text, "schemas", f"HostedFeedbackCreate missing {field}", failures)
    for snippet in REQUIRED_ENDPOINT_SNIPPETS:
        _expect(snippet in app_text, "server_app", f"hosted feedback endpoint missing {snippet}", failures)
    for snippet in REQUIRED_SQLITE_STORAGE_SNIPPETS:
        _expect(snippet in sqlite_text, "sqlite_store", f"SQLite feedback storage missing {snippet}", failures)
    for snippet in REQUIRED_POSTGRES_STORAGE_SNIPPETS:
        _expect(snippet in postgres_text, "postgres_store", f"Postgres feedback storage missing {snippet}", failures)
    for snippet in REQUIRED_EVAL_SNIPPETS:
        _expect(snippet in postgres_text or snippet in sqlite_text or snippet in eval_text, "eval_review", f"feedback eval/review path missing {snippet}", failures)
    for snippet in REQUIRED_FRONTEND_SNIPPETS:
        _expect(snippet in frontend_text, "frontend", f"hosted feedback UI missing {snippet}", failures)
    for snippet in REQUIRED_TEST_SNIPPETS:
        _expect(snippet in hosted_api_test_text, "hosted_api_tests", f"hosted feedback regression coverage missing {snippet}", failures)
    for snippet in REQUIRED_FRONTEND_TEST_SNIPPETS:
        _expect(snippet in frontend_test_text, "frontend_tests", f"frontend feedback regression coverage missing {snippet}", failures)
    for snippet in REQUIRED_REPORT_SNIPPETS:
        _expect(snippet in export_text or snippet in reports_test_text, "reports_exports", f"feedback report/export coverage missing {snippet}", failures)
    _expect(
        all(snippet in doc_text for snippet in REQUIRED_DOC_SNIPPETS),
        "docs",
        "feedback review doc must state reviewability, consent, quick feedback, and admin triage boundaries",
        failures,
    )
    expected_snippets_by_section = _json_snippet_map(REQUIRED_SNIPPETS_BY_SECTION)
    observed_snippets_by_section = _observed_snippets_by_section(texts_by_section)
    missing_snippets_by_section = _missing_snippets_by_section(observed_snippets_by_section)
    snippet_inventory_exact = observed_snippets_by_section == expected_snippets_by_section and not any(missing_snippets_by_section.values())

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "launch_gate_complete": gate is not None and gate.get("status") == "complete",
        "feedback_endpoint_access_controlled": "require_workspace_role(user, thread[\"workspace_id\"], WORKSPACE_WRITE_ROLES)" in app_text,
        "feedback_trace_event_recorded": "event_type=\"user_feedback\"" in sqlite_text and "event_type=\"user_feedback\"" in postgres_text,
        "feedback_phase5_trace_span_recorded": "\"feedback.capture\"" in app_text,
        "eval_candidate_created_from_feedback": (
            "store.create_phase4_eval_candidate(" in app_text
            and "\"feedback\": feedback" in app_text
            and "INSERT INTO phase4_eval_candidates" in sqlite_text
            and "feedback_event_id" in postgres_text
        ),
        "review_and_replay_covered": "approved_for_suite" in hosted_api_test_text and "local_trace_feedback_regression_v1" in hosted_api_test_text,
        "quick_feedback_taxonomy_visible": all(
            snippet in frontend_text
            for snippet in (
                "hostedFeedbackQuickTags",
                "missing_important_context",
                "wrong_source_or_weak_evidence",
                "exposed_internal_wording",
                "hosted-feedback-quick-tag",
            )
        ),
        "admin_triage_taxonomy_visible": all(snippet in frontend_text for snippet in ("hostedFeedbackTriageTags", "safety_issue", "model_generation_failure", "hosted-feedback-triage-tag")),
        "detailed_feedback_controls_visible": all(snippet in frontend_text for snippet in ("hosted-feedback-correction", "hosted-feedback-ideal", "hosted-feedback-training-consent")),
        "frontend_triage_visible": "hosted-eval-candidate-evidence" in frontend_text and "hosted-eval-runs" in frontend_text,
        "report_exports_include_feedback": "feedback_training_consent_count" in export_text,
        "expected_snippets_by_section": expected_snippets_by_section,
        "observed_snippets_by_section": observed_snippets_by_section,
        "missing_snippets_by_section": missing_snippets_by_section,
        "snippet_inventory_exact": snippet_inventory_exact,
        "evidence": {
            "launch_gate_matrix": _display_path(matrix_path),
            "server_app": _display_path(app_path),
            "schemas": _display_path(schema_path),
            "sqlite_store": _display_path(sqlite_store_path),
            "postgres_store": _display_path(postgres_store_path),
            "eval_service": _display_path(eval_service_path),
            "export_service": _display_path(export_service_path),
            "frontend": _display_path(frontend_path),
            "frontend_tests": _display_path(frontend_test_path),
            "hosted_api_tests": _display_path(hosted_api_test_path),
            "report_tests": _display_path(reports_test_path),
            "docs": _display_path(doc_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_feedback_review_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _launch_gate(matrix: dict[str, Any]) -> dict[str, Any] | None:
    for row in matrix.get("launch_gates") or []:
        if isinstance(row, dict) and row.get("id") == LAUNCH_GATE_ID:
            return row
    return None


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


def _read_text(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> None:
    if not condition:
        failures.append({"section": section, "reason": reason})


def _json_snippet_map(snippets_by_section: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    return {section: list(snippets) for section, snippets in sorted(snippets_by_section.items())}


def _observed_snippets_by_section(texts_by_section: dict[str, str]) -> dict[str, list[str]]:
    observed: dict[str, list[str]] = {}
    for section, snippets in sorted(REQUIRED_SNIPPETS_BY_SECTION.items()):
        text = texts_by_section.get(section, "")
        observed[section] = [snippet for snippet in snippets if snippet in text]
    return observed


def _missing_snippets_by_section(observed_snippets_by_section: dict[str, list[str]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for section, snippets in sorted(REQUIRED_SNIPPETS_BY_SECTION.items()):
        observed = set(observed_snippets_by_section.get(section, []))
        missing[section] = [snippet for snippet in snippets if snippet not in observed]
    return missing


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
