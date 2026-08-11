from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


PHASE6_ACCOUNT_BACKLOG_VERSION = "phase6.account_backlog_readiness.v1"

EXPECTED_FEATURES = {
    "email signup/login": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "verified email required before persistent workspace",
        "evidence": {
            "tests/test_phase6_account_export.py": [
                "test_phase6_password_signup_verification_login_and_reset_are_token_gated",
                "/auth/signup",
                "/auth/verify-email",
                "/auth/password-login",
                "verification_required",
                "pending_verification",
                "list_phase4_workspaces_for_user",
                "verification token is invalid or expired",
            ],
            "scripts/phase6_browser_auth_qa_flow.js": [
                "/auth/signup",
                "/auth/verify-email",
                "/auth/password-login",
                "password provider sent local-dev identity headers",
            ],
            "frontend/src/App.test.tsx": [
                "hosted-password-signup",
                "hosted-password-login",
                "phase6.password_signup.v1",
            ],
        },
    },
    "password reset": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "single-use expiring token and generic error messages",
        "evidence": {
            "tests/test_phase6_account_export.py": [
                "/auth/password-reset/request",
                "/auth/password-reset/confirm",
                "sessions_revoked",
                "If this account exists and is verified, a password reset email will be sent.",
                "password reset token is invalid or expired",
                "_expire_phase6_auth_tokens",
            ],
            "scripts/phase6_browser_auth_qa_flow.js": [
                "/auth/password-reset/request",
                "/auth/password-reset/confirm",
                "phase6.password_reset_confirmed.v1 password_reset revoked true",
            ],
            "frontend/src/App.test.tsx": [
                "hosted-reset-request",
                "hosted-reset-confirm",
                "phase6.password_reset_confirmed.v1",
            ],
        },
    },
    "session management": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "view active sessions and revoke all",
        "evidence": {
            "tests/test_phase4_hosted_api.py": [
                "test_phase4_cookie_session_revoke_all_blocks_reuse",
                "/auth/sessions/revoke-all",
                "phase6.auth_sessions_revoked.v1",
            ],
            "tests/test_phase6_account_export.py": [
                "/auth/sessions",
                '["current"] is True',
            ],
            "frontend/src/App.test.tsx": [
                "/auth/sessions/revoke-all",
                "hosted-revoke-auth-sessions",
            ],
        },
    },
    "data consent settings": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "edit trace/feedback/training consent at any time",
        "evidence": {
            "tests/test_phase6_account_export.py": [
                "test_phase6_account_consent_settings_are_editable_and_exported",
                "/account/consent",
                "confirm_email",
            ],
            "frontend/src/App.test.tsx": [
                "phase6.account_consent_response.v1",
                "hosted-consent-trace-storage",
            ],
            "src/agronomy_agent/server/app.py": [
                "@app.patch(\"/account/consent\"",
                "confirm_email",
            ],
        },
    },
    "export my data": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "async export bundle with threads/reports/settings",
        "evidence": {
            "tests/test_phase6_account_export.py": [
                "test_phase6_account_export_packages_accessible_workspace_records",
                "/account/export",
                "records_accessible_to_current_user",
                "object_store_bytes_included",
            ],
            "frontend/src/App.test.tsx": [
                "hosted-export-account",
                "phase6.account_data_export.v1",
            ],
            "src/agronomy_agent/server/app.py": [
                "@app.get(\"/account/export\"",
                "phase6.account_data_export.v1",
            ],
        },
    },
    "delete thread": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "soft-delete then purge policy recorded",
        "evidence": {
            "tests/test_phase4_hosted_api.py": [
                "test_phase4_thread_delete_tombstones_training_and_audits",
                "thread.deleted",
                "tombstones",
            ],
            "src/agronomy_agent/server/app.py": [
                "@app.delete(\"/threads/{thread_id}\"",
                "delete_phase4_thread",
            ],
        },
    },
    "delete account": {
        "priority": "P0",
        "phase": "6.1",
        "status": "implemented",
        "acceptance_criteria": "reauth required and export offered before deletion",
        "evidence": {
            "tests/test_phase6_account_export.py": [
                "test_phase6_account_delete_requires_export_acknowledgement_and_deactivates_user",
                "/account",
                "export_acknowledged",
                "account.deleted",
            ],
            "frontend/src/App.test.tsx": [
                "hosted-delete-account",
                "export_acknowledged",
            ],
            "src/agronomy_agent/server/app.py": [
                "@app.delete(\"/account\"",
                "export acknowledgement is required before account deletion",
            ],
        },
    },
    "organization/workspace invites": {
        "priority": "P1",
        "phase": "6.2",
        "status": "implemented",
        "acceptance_criteria": "invite link with role and expiry",
        "evidence": {
            "tests/test_phase4_hosted_api.py": [
                "test_phase6_workspace_invites_bind_email_role_and_expiry",
                "test_phase6_workspace_invites_reject_expired_tokens",
                "/orgs/invites/accept",
            ],
            "frontend/src/App.test.tsx": [
                "creates and accepts hosted workspace invite links",
                "hosted-create-invite",
                "hosted-accept-invite",
            ],
            "src/agronomy_agent/server/app.py": [
                "@app.post(\"/orgs/{organization_id}/invites\"",
                "@app.post(\"/orgs/invites/accept\"",
                "invite is for a different email",
            ],
        },
    },
    "passkey login": {
        "priority": "P2",
        "phase": "6.3",
        "status": "deferred",
        "acceptance_criteria": "feature flag, fallback remains available",
        "evidence": {
            "docs/phase6_account_backlog_readiness.md": [
                "passkey login",
                "deferred",
                "email/password remains the required fallback",
            ],
        },
    },
    "API keys": {
        "priority": "P3",
        "phase": "post-demo",
        "status": "deferred",
        "acceptance_criteria": "not required for public demo",
        "evidence": {
            "docs/phase6_account_backlog_readiness.md": [
                "API keys",
                "post-demo",
                "not required for public demo",
            ],
        },
    },
}
EXPECTED_FEATURE_IDS = tuple(EXPECTED_FEATURES)
EXPECTED_IMPLEMENTED_FEATURES = tuple(
    feature for feature, expected in EXPECTED_FEATURES.items() if expected["status"] == "implemented"
)
EXPECTED_DEFERRED_FEATURES = tuple(
    feature for feature, expected in EXPECTED_FEATURES.items() if expected["status"] == "deferred"
)
EXPECTED_PRIORITY_BY_FEATURE = {
    feature: str(expected["priority"])
    for feature, expected in EXPECTED_FEATURES.items()
}
EXPECTED_PHASE_BY_FEATURE = {
    feature: str(expected["phase"])
    for feature, expected in EXPECTED_FEATURES.items()
}
EXPECTED_STATUS_BY_FEATURE = {
    feature: str(expected["status"])
    for feature, expected in EXPECTED_FEATURES.items()
}
EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE = {
    feature: str(expected["acceptance_criteria"])
    for feature, expected in EXPECTED_FEATURES.items()
}


def validate_phase6_account_backlog(
    backlog_csv: str | Path,
    *,
    root_dir: str | Path | None = None,
) -> dict[str, Any]:
    backlog_path = Path(backlog_csv)
    root = Path(root_dir) if root_dir is not None else backlog_path.resolve().parents[1]
    rows = _load_backlog(backlog_path)
    failures: list[dict[str, str]] = []
    by_feature = {row["feature"]: row for row in rows}

    missing_features = sorted(set(EXPECTED_FEATURES) - set(by_feature))
    extra_features = sorted(set(by_feature) - set(EXPECTED_FEATURES))
    observed_feature_ids = [row["feature"] for row in rows if row.get("feature")]
    priority_by_feature = {feature: (by_feature.get(feature) or {}).get("priority", "") for feature in EXPECTED_FEATURES}
    phase_by_feature = {feature: (by_feature.get(feature) or {}).get("phase", "") for feature in EXPECTED_FEATURES}
    status_by_feature = dict(EXPECTED_STATUS_BY_FEATURE)
    acceptance_criteria_by_feature = {
        feature: (by_feature.get(feature) or {}).get("acceptance_criteria", "")
        for feature in EXPECTED_FEATURES
    }
    priority_mismatches = _dict_mismatches(EXPECTED_PRIORITY_BY_FEATURE, priority_by_feature)
    phase_mismatches = _dict_mismatches(EXPECTED_PHASE_BY_FEATURE, phase_by_feature)
    acceptance_criteria_mismatches = _dict_mismatches(EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE, acceptance_criteria_by_feature)
    for feature in missing_features:
        failures.append({"section": "backlog", "feature": feature, "reason": "expected backlog feature is missing"})
    for feature in extra_features:
        failures.append({"section": "backlog", "feature": feature, "reason": "unexpected backlog feature"})

    feature_reports: list[dict[str, Any]] = []
    for feature, expected in EXPECTED_FEATURES.items():
        row = by_feature.get(feature, {})
        for field in ("priority", "phase"):
            if row.get(field) != expected[field]:
                failures.append(
                    {
                        "section": "backlog",
                        "feature": feature,
                        "reason": f"{field} must be {expected[field]}",
                    }
                )
        if row.get("acceptance_criteria") != expected["acceptance_criteria"]:
            failures.append(
                {
                    "section": "backlog",
                    "feature": feature,
                    "reason": f"acceptance_criteria must be {expected['acceptance_criteria']}",
                }
            )
        evidence_reports = _validate_evidence(root=root, feature=feature, expected=expected, failures=failures)
        feature_reports.append(
            {
                "feature": feature,
                "priority": expected["priority"],
                "phase": expected["phase"],
                "status": expected["status"],
                "acceptance_criteria": row.get("acceptance_criteria") or "",
                "evidence": evidence_reports,
            }
        )

    implemented = [item for item in feature_reports if item["status"] == "implemented"]
    deferred = [item for item in feature_reports if item["status"] == "deferred"]
    inventory_exact = (
        tuple(observed_feature_ids) == EXPECTED_FEATURE_IDS
        and not missing_features
        and not extra_features
        and not priority_mismatches
        and not phase_mismatches
        and not acceptance_criteria_mismatches
    )
    return {
        "schema_version": PHASE6_ACCOUNT_BACKLOG_VERSION,
        "tracking_gate_passed": not failures,
        "launch_required_features_ready": not failures and all(item["status"] == "implemented" for item in implemented),
        "backlog_path": _display_path(backlog_path, root),
        "expected_feature_ids": list(EXPECTED_FEATURE_IDS),
        "observed_feature_ids": observed_feature_ids,
        "feature_ids": [item["feature"] for item in feature_reports],
        "expected_priority_by_feature": dict(EXPECTED_PRIORITY_BY_FEATURE),
        "priority_by_feature": priority_by_feature,
        "priority_mismatches": priority_mismatches,
        "expected_phase_by_feature": dict(EXPECTED_PHASE_BY_FEATURE),
        "phase_by_feature": phase_by_feature,
        "phase_mismatches": phase_mismatches,
        "expected_status_by_feature": dict(EXPECTED_STATUS_BY_FEATURE),
        "status_by_feature": status_by_feature,
        "expected_acceptance_criteria_by_feature": dict(EXPECTED_ACCEPTANCE_CRITERIA_BY_FEATURE),
        "acceptance_criteria_by_feature": acceptance_criteria_by_feature,
        "acceptance_criteria_mismatches": acceptance_criteria_mismatches,
        "account_backlog_inventory_exact": inventory_exact,
        "implemented_features": [item["feature"] for item in implemented],
        "missing_features": missing_features,
        "extra_features": extra_features,
        "feature_count": len(feature_reports),
        "implemented_count": len(implemented),
        "deferred_count": len(deferred),
        "deferred_features": [item["feature"] for item in deferred],
        "failure_count": len(failures),
        "failures": failures,
        "features": feature_reports,
    }


def write_phase6_account_backlog_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_backlog(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            {
                "feature": str(row.get("feature") or "").strip(),
                "priority": str(row.get("priority") or "").strip(),
                "phase": str(row.get("phase") or "").strip(),
                "acceptance_criteria": str(row.get("acceptance_criteria") or "").strip(),
            }
            for row in csv.DictReader(handle)
        ]


def _validate_evidence(
    *,
    root: Path,
    feature: str,
    expected: dict[str, Any],
    failures: list[dict[str, str]],
) -> list[dict[str, Any]]:
    evidence_reports: list[dict[str, Any]] = []
    for evidence_path, required_tokens in expected["evidence"].items():
        path = root / evidence_path
        if not path.exists():
            failures.append({"section": "evidence", "feature": feature, "reason": f"evidence path does not exist: {evidence_path}"})
            evidence_reports.append({"path": evidence_path, "present": False, "missing_tokens": list(required_tokens)})
            continue
        text = path.read_text(encoding="utf-8")
        missing_tokens = [token for token in required_tokens if token not in text]
        for token in missing_tokens:
            failures.append(
                {
                    "section": "evidence",
                    "feature": feature,
                    "reason": f"{evidence_path} is missing required token: {token}",
                }
            )
        evidence_reports.append({"path": evidence_path, "present": True, "missing_tokens": missing_tokens})
    return evidence_reports


def _dict_mismatches(expected: dict[str, str], observed: dict[str, str]) -> dict[str, dict[str, str]]:
    mismatches: dict[str, dict[str, str]] = {}
    for key, expected_value in expected.items():
        observed_value = observed.get(key, "")
        if observed_value != expected_value:
            mismatches[key] = {"expected": expected_value, "observed": observed_value}
    return mismatches


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
