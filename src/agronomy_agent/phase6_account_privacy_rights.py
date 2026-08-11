from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.account_privacy_rights.v1"
AUTH_GATE_ID = "auth_session_privacy_bugs"
DATA_GATE_ID = "data_export_delete"

REQUIRED_MATRIX_EVIDENCE = (
    "docs/phase6_account_privacy_rights.md",
    "scripts/validate_phase6_account_privacy_rights.py",
    "tests/test_phase6_account_privacy_rights.py",
    "outputs/phase6_account_privacy_rights_latest.json",
)
REQUIRED_BACKLOG_EVIDENCE = (
    "scripts/validate_phase6_account_backlog.py",
    "outputs/phase6_account_backlog_latest.json",
    "tests/test_phase6_account_backlog.py",
)
REQUIRED_ENDPOINT_SNIPPETS = (
    '@app.post("/auth/signup"',
    '@app.post("/auth/verify-email"',
    '@app.post("/auth/password-login"',
    '@app.post("/auth/password-reset/request"',
    '@app.post("/auth/password-reset/confirm"',
    '@app.get("/auth/sessions"',
    '@app.post("/auth/sessions/revoke-all"',
    '@app.get("/account/consent"',
    '@app.patch("/account/consent"',
    '@app.get("/account/export"',
    '@app.delete("/account"',
    '@app.delete("/workspaces/{workspace_id}"',
    '@app.delete("/threads/{thread_id}"',
)
REQUIRED_PRIVACY_BOUNDARY_SNIPPETS = (
    "PasswordSignupRequest",
    "PasswordLoginRequest",
    "PasswordResetRequest",
    "PasswordResetConfirmRequest",
    "payload.confirm_email",
    "email confirmation does not match current account",
    "export acknowledgement is required before account deletion",
    '"object_store_bytes_included": False',
    '"object_store_uris_included": False',
    '"export_file_uris_included": False',
    '"embedding_vectors_included": False',
    "_phase6_account_export_attachment",
    "_phase6_account_export_export",
    "_phase6_redact_account_export_internal_handles",
    "records_accessible_to_current_user",
    "store.revoke_phase6_auth_sessions",
    "response.delete_cookie(\"agronomy_session\"",
)
REQUIRED_SCHEMA_SNIPPETS = (
    "class AccountDeleteRequest",
    "confirm_email: str",
    "export_acknowledged: bool = False",
    "class AccountConsentUpdate",
    "retention_preference",
)
REQUIRED_BACKEND_TEST_SNIPPETS = (
    "test_phase6_password_signup_verification_login_and_reset_are_token_gated",
    "verification_required",
    "pending_verification",
    "list_phase4_workspaces_for_user",
    "verification token is invalid or expired",
    "/auth/verify-email",
    "/auth/password-login",
    "/auth/password-reset/request",
    "/auth/password-reset/confirm",
    "If this account exists and is verified, a password reset email will be sent.",
    "password reset token is invalid or expired",
    "_expire_phase6_auth_tokens",
    "sessions_revoked",
    "test_phase6_account_export_packages_accessible_workspace_records",
    "records_accessible_to_current_user",
    "object_store_bytes_included",
    "object_store_uris_included",
    "export_file_uris_included",
    "embedding_vectors_included",
    "_assert_no_account_export_internal_handles",
    "test_phase6_account_consent_settings_are_editable_and_exported",
    "confirm_email",
    "test_phase6_account_delete_requires_export_acknowledgement_and_deactivates_user",
    "test_phase6_workspace_delete_soft_deletes_workspace_children_and_blocks_access",
    "export_acknowledged",
    "workspace.deleted",
    "soft_delete_then_purge_policy",
    "account.deleted",
    "reauth_method",
)
REQUIRED_HOSTED_API_TEST_SNIPPETS = (
    "test_phase4_cookie_session_revoke_all_blocks_reuse",
    "test_phase4_thread_delete_tombstones_training_and_audits",
    "/auth/sessions/revoke-all",
    "/threads/{thread['id']}",
    "thread.deleted",
    "phase6.auth_sessions_revoked.v1",
)
REQUIRED_BROWSER_AUTH_QA_SNIPPETS = (
    "/auth/signup",
    "/auth/verify-email",
    "/auth/password-login",
    "/auth/password-reset/request",
    "/auth/password-reset/confirm",
    "Password signup verification required",
    "Password email verified",
    "Password login complete",
    "Password reset requested",
    "Password reset complete",
    "password provider sent local-dev identity headers",
    "reset endpoints did not carry CSRF after login",
    "phase6.password_reset_confirmed.v1 password_reset revoked true",
)
REQUIRED_FRONTEND_SNIPPETS = (
    "exportAccountData",
    "saveAccountConsent",
    "deleteAccount",
    "deleteWorkspace",
    "deleteHostedThread",
    "loadAuthSessions",
    "revokeAuthSessions",
    "/account/export",
    "/account/consent",
    "/auth/sessions",
    "/auth/sessions/revoke-all",
    "/workspaces/${workspaceId}",
    "/threads/${threadId}",
    "confirm_email: user.email",
    "export_acknowledged: true",
)
REQUIRED_FRONTEND_TEST_SNIPPETS = (
    "loads hosted account data export evidence",
    "edits hosted account consent settings with email confirmation",
    "lists and revokes hosted auth sessions",
    "requires account export before deleting the hosted account",
    "deletes the selected workspace and clears workspace scoped state",
    "deletes hosted thread and surfaces audit evidence",
    "phase6.account_data_export.v1",
    "phase6.account_consent_response.v1",
    "phase6.auth_sessions.v1",
    "phase6.auth_sessions_revoked.v1",
    "phase6.account_delete.v1",
    "hosted-account-export",
    "hosted-save-account-consent",
    "hosted-auth-sessions",
    "hosted-delete-account",
    "hosted-delete-workspace",
    "hosted-delete-thread",
)
REQUIRED_DOC_SNIPPETS = (
    "account data export",
    "email confirmation",
    "export acknowledgement",
    "object-store bytes",
    "object-store uris",
    "export file uris",
    "embedding vectors",
    "workspace deletion",
    "thread deletion",
    "soft-delete",
    "session revocation",
)
REQUIRED_LAUNCH_GATE_SNIPPETS = (
    AUTH_GATE_ID,
    DATA_GATE_ID,
    "status: complete",
    *REQUIRED_MATRIX_EVIDENCE,
    *REQUIRED_BACKLOG_EVIDENCE,
)
REQUIRED_SNIPPETS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "account_tests": REQUIRED_BACKEND_TEST_SNIPPETS,
    "browser_auth_qa": REQUIRED_BROWSER_AUTH_QA_SNIPPETS,
    "docs": REQUIRED_DOC_SNIPPETS,
    "frontend": REQUIRED_FRONTEND_SNIPPETS,
    "frontend_tests": REQUIRED_FRONTEND_TEST_SNIPPETS,
    "hosted_api_tests": REQUIRED_HOSTED_API_TEST_SNIPPETS,
    "launch_gate_matrix": REQUIRED_LAUNCH_GATE_SNIPPETS,
    "schemas": REQUIRED_SCHEMA_SNIPPETS,
    "server_app": (*REQUIRED_ENDPOINT_SNIPPETS, *REQUIRED_PRIVACY_BOUNDARY_SNIPPETS),
}
EXPECTED_CONTROL_IDS = (
    "password_auth_token_gate",
    "account_export_scope",
    "account_export_object_vector_exclusion",
    "account_export_internal_handle_redaction",
    "consent_retention_controls",
    "session_management",
    "delete_account",
    "delete_workspace",
    "delete_thread",
    "data_deletion_rollup",
    "sensitive_action_reauth",
    "frontend_privacy_controls",
)
EXPECTED_CONTROL_STATUS_BY_ID = {control_id: True for control_id in EXPECTED_CONTROL_IDS}
EXPECTED_CONTROL_EVIDENCE_BY_ID = {
    "password_auth_token_gate": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/app.py",
        "scripts/phase6_browser_auth_qa_flow.js",
        "frontend/src/App.test.tsx",
    ],
    "account_export_scope": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/app.py",
    ],
    "account_export_object_vector_exclusion": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/app.py",
    ],
    "account_export_internal_handle_redaction": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/app.py",
    ],
    "consent_retention_controls": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/schemas.py",
    ],
    "session_management": [
        "tests/test_phase4_hosted_api.py",
        "src/agronomy_agent/server/app.py",
        "frontend/src/App.test.tsx",
    ],
    "delete_account": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/app.py",
        "frontend/src/HostedPlatform.tsx",
    ],
    "delete_workspace": [
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/server/app.py",
        "frontend/src/App.test.tsx",
    ],
    "delete_thread": [
        "tests/test_phase4_hosted_api.py",
        "src/agronomy_agent/server/app.py",
        "frontend/src/App.test.tsx",
    ],
    "data_deletion_rollup": [
        "tests/test_phase6_account_export.py",
        "tests/test_phase4_hosted_api.py",
    ],
    "sensitive_action_reauth": [
        "src/agronomy_agent/server/schemas.py",
        "src/agronomy_agent/server/app.py",
    ],
    "frontend_privacy_controls": [
        "frontend/src/HostedPlatform.tsx",
        "frontend/src/App.test.tsx",
    ],
}


def validate_phase6_account_privacy_rights(
    *,
    matrix_path: Path = ROOT / "docs/phase6_launch_gate_matrix.yaml",
    app_path: Path = ROOT / "src/agronomy_agent/server/app.py",
    schema_path: Path = ROOT / "src/agronomy_agent/server/schemas.py",
    account_tests_path: Path = ROOT / "tests/test_phase6_account_export.py",
    hosted_api_tests_path: Path = ROOT / "tests/test_phase4_hosted_api.py",
    browser_auth_qa_path: Path = ROOT / "scripts/phase6_browser_auth_qa_flow.js",
    frontend_path: Path = ROOT / "frontend/src/HostedPlatform.tsx",
    frontend_tests_path: Path = ROOT / "frontend/src/App.test.tsx",
    backlog_report_path: Path = ROOT / "outputs/phase6_account_backlog_latest.json",
    docs_path: Path = ROOT / "docs/phase6_account_privacy_rights.md",
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    matrix = _load_yaml(matrix_path, "launch_gate_matrix", failures)
    matrix_text = _read_text(matrix_path, "launch_gate_matrix", failures)
    app_text = _read_text(app_path, "server_app", failures)
    schema_text = _read_text(schema_path, "schemas", failures)
    account_tests = _read_text(account_tests_path, "account_tests", failures)
    hosted_api_tests = _read_text(hosted_api_tests_path, "hosted_api_tests", failures)
    browser_auth_qa = _read_text(browser_auth_qa_path, "browser_auth_qa", failures)
    frontend_text = _read_text(frontend_path, "frontend", failures)
    frontend_tests = _read_text(frontend_tests_path, "frontend_tests", failures)
    backlog_report = _load_json(backlog_report_path, "account_backlog_report", failures)
    doc_text = _read_text(docs_path, "docs", failures)
    texts_by_section = {
        "account_tests": account_tests,
        "browser_auth_qa": browser_auth_qa,
        "docs": doc_text.lower(),
        "frontend": frontend_text,
        "frontend_tests": frontend_tests,
        "hosted_api_tests": hosted_api_tests,
        "launch_gate_matrix": matrix_text,
        "schemas": schema_text,
        "server_app": app_text,
    }

    auth_gate = _launch_gate(matrix, AUTH_GATE_ID)
    data_gate = _launch_gate(matrix, DATA_GATE_ID)
    for gate_id, gate in ((AUTH_GATE_ID, auth_gate), (DATA_GATE_ID, data_gate)):
        _expect(gate is not None, "launch_gate_matrix", f"launch matrix must track {gate_id}", failures)
        if gate is None:
            continue
        _expect(gate.get("status") == "complete", "launch_gate_matrix", f"{gate_id} must remain complete", failures)
        evidence = {str(item) for item in gate.get("evidence") or []}
        for required in (*REQUIRED_MATRIX_EVIDENCE, *REQUIRED_BACKLOG_EVIDENCE):
            _expect(required in evidence, "launch_gate_matrix", f"{gate_id} evidence must include {required}", failures)
            if not required.startswith("outputs/"):
                _expect((ROOT / required).exists(), "launch_gate_matrix", f"{gate_id} evidence path missing: {required}", failures)

    for snippet in REQUIRED_ENDPOINT_SNIPPETS:
        _expect(snippet in app_text, "server_app", f"account/auth endpoint missing {snippet}", failures)
    for snippet in REQUIRED_PRIVACY_BOUNDARY_SNIPPETS:
        _expect(snippet in app_text, "server_app", f"account privacy boundary missing {snippet}", failures)
    for snippet in REQUIRED_SCHEMA_SNIPPETS:
        _expect(snippet in schema_text, "schemas", f"account schema boundary missing {snippet}", failures)
    for snippet in REQUIRED_BACKEND_TEST_SNIPPETS:
        _expect(snippet in account_tests, "account_tests", f"account privacy regression test missing {snippet}", failures)
    for snippet in REQUIRED_HOSTED_API_TEST_SNIPPETS:
        _expect(snippet in hosted_api_tests, "hosted_api_tests", f"auth session regression test missing {snippet}", failures)
    for snippet in REQUIRED_BROWSER_AUTH_QA_SNIPPETS:
        _expect(snippet in browser_auth_qa, "browser_auth_qa", f"browser auth QA flow missing {snippet}", failures)
    for snippet in REQUIRED_FRONTEND_SNIPPETS:
        _expect(snippet in frontend_text, "frontend", f"hosted account privacy UI missing {snippet}", failures)
    for snippet in REQUIRED_FRONTEND_TEST_SNIPPETS:
        _expect(snippet in frontend_tests, "frontend_tests", f"frontend account privacy coverage missing {snippet}", failures)
    for snippet in REQUIRED_DOC_SNIPPETS:
        _expect(snippet in doc_text.lower(), "docs", f"account privacy doc missing {snippet}", failures)

    _expect(backlog_report.get("schema_version") == "phase6.account_backlog_readiness.v1", "account_backlog_report", "unexpected account backlog schema", failures)
    _expect(backlog_report.get("tracking_gate_passed") is True, "account_backlog_report", "account backlog gate must pass", failures)
    _expect(backlog_report.get("launch_required_features_ready") is True, "account_backlog_report", "launch-required account features must remain ready", failures)
    _expect(int(backlog_report.get("failure_count") or 0) == 0, "account_backlog_report", "account backlog failure_count must be zero", failures)

    account_export_covered = all(snippet in account_tests + app_text for snippet in ("records_accessible_to_current_user", "object_store_bytes_included", "embedding_vectors_included"))
    data_export_excludes_object_bytes_and_vectors = (
        '"object_store_bytes_included": False' in app_text
        and '"embedding_vectors_included": False' in app_text
        and '"object_store_bytes_included": False' in account_tests
        and '"embedding_vectors_included": False' in account_tests
    )
    data_export_excludes_internal_storage_handles = (
        '"object_store_uris_included": False' in app_text
        and '"export_file_uris_included": False' in app_text
        and "_phase6_redact_account_export_internal_handles" in app_text
        and "_assert_no_account_export_internal_handles" in account_tests
        and '"object_store_uris_included": False' in account_tests
        and '"export_file_uris_included": False' in account_tests
    )
    consent_and_retention_covered = all(snippet in account_tests + schema_text for snippet in ("confirm_email", "retention_preference"))
    session_management_covered = all(snippet in app_text + hosted_api_tests + frontend_tests for snippet in ("/auth/sessions", "/auth/sessions/revoke-all", "phase6.auth_sessions_revoked.v1"))
    delete_account_covered = all(snippet in account_tests + app_text + frontend_text for snippet in ("export_acknowledged", "account.deleted", "confirm_email"))
    delete_workspace_covered = all(
        snippet in account_tests + app_text + frontend_text + frontend_tests
        for snippet in (
            '@app.delete("/workspaces/{workspace_id}"',
            "test_phase6_workspace_delete_soft_deletes_workspace_children_and_blocks_access",
            "workspace.deleted",
            "hosted-delete-workspace",
            "soft_delete_then_purge_policy",
        )
    )
    delete_thread_covered = all(
        snippet in hosted_api_tests + app_text + frontend_text + frontend_tests
        for snippet in (
            '@app.delete("/threads/{thread_id}"',
            "test_phase4_thread_delete_tombstones_training_and_audits",
            "thread.deleted",
            "hosted-delete-thread",
            "training_eligible",
        )
    )
    data_deletion_covered = delete_account_covered and delete_workspace_covered and delete_thread_covered
    password_auth_token_gated = all(
        snippet in account_tests
        for snippet in (
            "verification_required",
            "pending_verification",
            "list_phase4_workspaces_for_user",
            "verification token is invalid or expired",
            "password reset token is invalid or expired",
            "sessions_revoked",
            "/auth/password-reset/confirm",
        )
    ) and all(snippet in browser_auth_qa for snippet in REQUIRED_BROWSER_AUTH_QA_SNIPPETS)
    _expect(
        data_export_excludes_object_bytes_and_vectors,
        "account_export_policy",
        "account export must explicitly exclude object-store bytes and embedding vectors in code and tests",
        failures,
    )
    _expect(
        data_export_excludes_internal_storage_handles,
        "account_export_policy",
        "account export must explicitly exclude internal object-store and export-file URIs in code and tests",
        failures,
    )
    control_status_by_id = {
        "password_auth_token_gate": password_auth_token_gated,
        "account_export_scope": account_export_covered,
        "account_export_object_vector_exclusion": data_export_excludes_object_bytes_and_vectors,
        "account_export_internal_handle_redaction": data_export_excludes_internal_storage_handles,
        "consent_retention_controls": consent_and_retention_covered,
        "session_management": session_management_covered,
        "delete_account": delete_account_covered,
        "delete_workspace": delete_workspace_covered,
        "delete_thread": delete_thread_covered,
        "data_deletion_rollup": data_deletion_covered,
        "sensitive_action_reauth": "confirm_email" in schema_text and "email confirmation does not match current account" in app_text,
        "frontend_privacy_controls": all(snippet in frontend_text for snippet in ("hosted-account-export", "hosted-auth-sessions", "hosted-delete-account")),
    }
    control_status_mismatches = {
        control_id: {
            "expected": EXPECTED_CONTROL_STATUS_BY_ID[control_id],
            "observed": control_status_by_id.get(control_id),
        }
        for control_id in EXPECTED_CONTROL_IDS
        if control_status_by_id.get(control_id) != EXPECTED_CONTROL_STATUS_BY_ID[control_id]
    }
    expected_snippets_by_section = _json_snippet_map(REQUIRED_SNIPPETS_BY_SECTION)
    observed_snippets_by_section = _observed_snippets_by_section(texts_by_section)
    missing_snippets_by_section = _missing_snippets_by_section(observed_snippets_by_section)
    snippet_inventory_exact = observed_snippets_by_section == expected_snippets_by_section and not any(missing_snippets_by_section.values())

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "auth_gate_complete": auth_gate is not None and auth_gate.get("status") == "complete",
        "data_gate_complete": data_gate is not None and data_gate.get("status") == "complete",
        "account_backlog_gate_passed": backlog_report.get("tracking_gate_passed") is True,
        "password_auth_token_gated": password_auth_token_gated,
        "account_export_covered": account_export_covered,
        "consent_and_retention_covered": consent_and_retention_covered,
        "session_management_covered": session_management_covered,
        "delete_account_covered": delete_account_covered,
        "delete_workspace_covered": delete_workspace_covered,
        "delete_thread_covered": delete_thread_covered,
        "data_deletion_covered": data_deletion_covered,
        "sensitive_action_reauth_covered": "confirm_email" in schema_text and "email confirmation does not match current account" in app_text,
        "frontend_privacy_controls_visible": all(snippet in frontend_text for snippet in ("hosted-account-export", "hosted-auth-sessions", "hosted-delete-account")),
        "data_export_excludes_object_bytes_and_vectors": data_export_excludes_object_bytes_and_vectors,
        "data_export_excludes_internal_storage_handles": data_export_excludes_internal_storage_handles,
        "expected_control_ids": list(EXPECTED_CONTROL_IDS),
        "observed_control_ids": list(control_status_by_id),
        "control_count": len(control_status_by_id),
        "expected_control_status_by_id": EXPECTED_CONTROL_STATUS_BY_ID,
        "control_status_by_id": control_status_by_id,
        "control_status_mismatches": control_status_mismatches,
        "control_evidence_by_id": EXPECTED_CONTROL_EVIDENCE_BY_ID,
        "expected_snippets_by_section": expected_snippets_by_section,
        "observed_snippets_by_section": observed_snippets_by_section,
        "missing_snippets_by_section": missing_snippets_by_section,
        "snippet_inventory_exact": snippet_inventory_exact,
        "account_privacy_control_inventory_exact": (
            tuple(control_status_by_id) == EXPECTED_CONTROL_IDS
            and not control_status_mismatches
        ),
        "missing_control_ids": sorted(set(EXPECTED_CONTROL_IDS) - set(control_status_by_id)),
        "extra_control_ids": sorted(set(control_status_by_id) - set(EXPECTED_CONTROL_IDS)),
        "evidence": {
            "launch_gate_matrix": _display_path(matrix_path),
            "server_app": _display_path(app_path),
            "schemas": _display_path(schema_path),
            "account_tests": _display_path(account_tests_path),
            "hosted_api_tests": _display_path(hosted_api_tests_path),
            "browser_auth_qa": _display_path(browser_auth_qa_path),
            "frontend": _display_path(frontend_path),
            "frontend_tests": _display_path(frontend_tests_path),
            "account_backlog_report": _display_path(backlog_report_path),
            "docs": _display_path(docs_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_account_privacy_rights_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _launch_gate(matrix: dict[str, Any], gate_id: str) -> dict[str, Any] | None:
    for row in matrix.get("launch_gates") or []:
        if isinstance(row, dict) and row.get("id") == gate_id:
            return row
    return None


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
