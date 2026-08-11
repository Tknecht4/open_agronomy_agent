from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.rate_limits_quotas.v1"
PACKET_BLOCKER_TEXT = "Rate limiting and quotas configured"
BOARD_BLOCKER_ID = "rate_limits_quotas"

REQUIRED_QUOTA_KEYS = (
    "max_threads",
    "max_messages",
    "max_attachments",
    "max_attachment_bytes",
    "max_data_sources",
    "max_eval_runs",
    "max_exports",
)
REQUIRED_BOARD_EVIDENCE = (
    "docs/phase6_rate_limits_quotas.md",
    "scripts/validate_phase6_rate_limits_quotas.py",
    "tests/test_phase6_rate_limits_quotas.py",
    "tests/test_rate_limit.py",
    "tests/test_phase4_hosted_api.py",
)
REQUIRED_RATE_LIMIT_TESTS = (
    "test_fixed_window_rate_limiter_resets_after_window",
    "test_redis_fixed_window_rate_limiter_uses_shared_counter",
    "test_server_settings_rejects_invalid_rate_limit_configuration",
    "test_phase4_api_rate_limits_by_authenticated_actor",
    "test_phase4_api_redis_rate_limiter_fails_closed_by_default",
)
REQUIRED_QUOTA_TEST_SNIPPETS = (
    "test_phase4_workspace_quotas_are_reported_and_enforced",
    "max_threads",
    "max_messages",
    "max_attachment_bytes",
    "max_data_sources",
    "max_exports",
    "denied_quota_read.status_code == 403",
)
EXPECTED_RATE_LIMIT_BACKENDS = ("memory", "redis")
REQUIRED_READINESS_FLAGS = {
    "rate_limit_fail_closed_default": True,
    "public_demo_requires_redis_rate_limit": True,
    "provider_quota_review_required": True,
    "frontend_quota_visible": True,
}


def validate_phase6_rate_limits_quotas(
    *,
    checklist_path: Path = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_launch_readiness_checklist.yaml",
    board_path: Path = ROOT / "docs/phase6_launch_readiness_board.yaml",
    settings_path: Path = ROOT / "src/agronomy_agent/server/settings.py",
    app_path: Path = ROOT / "src/agronomy_agent/server/app.py",
    deployment_readiness_path: Path = ROOT / "src/agronomy_agent/server/deployment_readiness.py",
    frontend_path: Path = ROOT / "frontend/src/HostedPlatform.tsx",
    frontend_test_path: Path = ROOT / "frontend/src/App.test.tsx",
    rate_limit_test_path: Path = ROOT / "tests/test_rate_limit.py",
    hosted_api_test_path: Path = ROOT / "tests/test_phase4_hosted_api.py",
    doc_path: Path = ROOT / "docs/phase6_rate_limits_quotas.md",
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    checklist = _load_yaml(checklist_path, "checklist", failures)
    board = _load_yaml(board_path, "readiness_board", failures)
    settings_text = _read_text(settings_path, "settings", failures)
    app_text = _read_text(app_path, "server_app", failures)
    deployment_text = _read_text(deployment_readiness_path, "deployment_readiness", failures)
    frontend_text = _read_text(frontend_path, "frontend", failures)
    frontend_test_text = _read_text(frontend_test_path, "frontend_tests", failures)
    rate_limit_test_text = _read_text(rate_limit_test_path, "rate_limit_tests", failures)
    hosted_api_test_text = _read_text(hosted_api_test_path, "hosted_api_tests", failures)
    doc_text = _read_text(doc_path, "docs", failures)

    checklist_blockers = {str(item) for item in checklist.get("blockers") or []}
    checklist_blocker_tracked = PACKET_BLOCKER_TEXT in checklist_blockers
    _expect(checklist_blocker_tracked, "checklist", "packet checklist must include rate limiting and quotas blocker", failures)

    board_row = _board_row(board)
    _expect(board_row is not None, "readiness_board", "readiness board must track rate_limits_quotas blocker", failures)
    if board_row is not None:
        _expect(board_row.get("packet_text") == PACKET_BLOCKER_TEXT, "readiness_board", "rate_limits_quotas packet_text must match checklist", failures)
        _expect(board_row.get("status") == "complete", "readiness_board", "rate_limits_quotas must be complete before pre-provider readiness", failures)
        evidence = {str(item) for item in board_row.get("evidence") or []}
        for required in REQUIRED_BOARD_EVIDENCE:
            _expect(required in evidence, "readiness_board", f"rate_limits_quotas evidence must include {required}", failures)
            _expect((ROOT / required).exists(), "readiness_board", f"rate_limits_quotas evidence path missing: {required}", failures)

    default_limit = _default_int(settings_text, "rate_limit_requests")
    default_window = _default_int(settings_text, "rate_limit_window_seconds")
    _expect(default_limit == 600, "settings", "default rate-limit request budget must remain 600 per window", failures)
    _expect(default_window == 60, "settings", "default rate-limit window must remain 60 seconds", failures)
    _expect("rate_limit_fail_open: bool = False" in settings_text, "settings", "rate limiter must fail closed by default", failures)
    _expect('limiter_backend not in {"memory", "redis"}' in settings_text, "settings", "settings must restrict rate-limit backends to memory or redis", failures)
    _expect("limiter_backend == \"redis\" and not limiter_redis_url" in settings_text, "settings", "redis rate limiting must require Redis URL", failures)

    _expect("RedisFixedWindowRateLimiter" in app_text and "FixedWindowRateLimiter" in app_text, "server_app", "server must install memory and redis rate limiter implementations", failures)
    _expect("RateLimiterUnavailable" in app_text and "rate limiter unavailable" in app_text, "server_app", "server must handle unavailable rate limiter", failures)
    _expect("settings.rate_limit_fail_open" in app_text and "X-RateLimit-Fail-Open" in app_text, "server_app", "server must make fail-open explicit when enabled", failures)
    _expect("X-RateLimit-Remaining" in app_text and "Retry-After" in app_text, "server_app", "rate-limit responses must expose remaining/reset headers", failures)
    _expect("response.status_code == 429" in app_text and "rate_limited=response.status_code == 429" in app_text, "server_app", "rate-limited requests must be observable", failures)
    _expect("_rate_limit_exempt_path" in app_text and '"/health"' in app_text and '"/api/health"' in app_text, "server_app", "health endpoints must remain rate-limit exempt", failures)

    _expect("Public demos need Redis-backed rate limiting" in deployment_text, "deployment_readiness", "public-demo readiness must require Redis-backed shared rate limiting", failures)
    _expect("Rate limiting must fail closed" in deployment_text, "deployment_readiness", "public-demo readiness must reject fail-open rate limiting", failures)
    _expect("rate_limit_requests > 600" in deployment_text, "deployment_readiness", "public-demo readiness must warn above the demo rate-limit budget", failures)

    quota_keys = _quota_keys(app_text)
    enforced_quota_keys = _enforced_quota_keys(app_text)
    missing_quota_keys = sorted(set(REQUIRED_QUOTA_KEYS) - quota_keys)
    extra_quota_keys = sorted(quota_keys - set(REQUIRED_QUOTA_KEYS))
    missing_enforced_quota_keys = sorted(set(REQUIRED_QUOTA_KEYS) - enforced_quota_keys)
    extra_enforced_quota_keys = sorted(enforced_quota_keys - set(REQUIRED_QUOTA_KEYS))
    for key in REQUIRED_QUOTA_KEYS:
        _expect(key in quota_keys, "server_app", f"default workspace quota missing: {key}", failures)
        _expect(key in enforced_quota_keys, "server_app", f"workspace quota enforcement missing: {key}", failures)
    _expect(not extra_quota_keys, "server_app", f"default workspace quotas include non-packet keys: {extra_quota_keys}", failures)
    _expect(not extra_enforced_quota_keys, "server_app", f"workspace quota enforcement includes non-packet keys: {extra_enforced_quota_keys}", failures)
    _expect("@app.get(\"/quotas\")" in app_text, "server_app", "server must expose /quotas endpoint", failures)
    _expect("workspace = require_workspace_for_user(user, workspace_id)" in app_text, "server_app", "/quotas endpoint must enforce workspace access", failures)
    _expect("workspace_quota_report(workspace)" in app_text, "server_app", "/quotas endpoint must use canonical quota report", failures)

    _expect("GET /quotas?workspace_id=" in frontend_test_text, "frontend_tests", "frontend tests must mock /quotas", failures)
    _expect("/quotas?workspace_id=${nextWorkspaceId}" in frontend_text, "frontend", "hosted UI must load /quotas", failures)
    _expect("hosted-load-quotas" in frontend_text and "hosted-quotas" in frontend_text, "frontend", "hosted UI must expose quota controls and status", failures)
    _expect("quotaReport.limits.map" in frontend_text, "frontend", "hosted UI must render individual quota limits", failures)
    _expect("max_exports" in frontend_test_text and "1/200" in frontend_test_text, "frontend_tests", "frontend tests must assert rendered quota values", failures)

    board_evidence_ids = [str(item) for item in (board_row or {}).get("evidence") or []]
    missing_board_evidence_ids = sorted(set(REQUIRED_BOARD_EVIDENCE) - set(board_evidence_ids))
    extra_board_evidence_ids = sorted(set(board_evidence_ids) - set(REQUIRED_BOARD_EVIDENCE))
    covered_rate_limit_tests = tuple(test_name for test_name in REQUIRED_RATE_LIMIT_TESTS if test_name in rate_limit_test_text)
    missing_rate_limit_tests = tuple(test_name for test_name in REQUIRED_RATE_LIMIT_TESTS if test_name not in rate_limit_test_text)
    covered_quota_test_snippets = tuple(snippet for snippet in REQUIRED_QUOTA_TEST_SNIPPETS if snippet in hosted_api_test_text)
    missing_quota_test_snippets = tuple(snippet for snippet in REQUIRED_QUOTA_TEST_SNIPPETS if snippet not in hosted_api_test_text)
    for test_name in REQUIRED_RATE_LIMIT_TESTS:
        _expect(test_name in rate_limit_test_text, "rate_limit_tests", f"missing rate-limit regression test {test_name}", failures)
    for snippet in REQUIRED_QUOTA_TEST_SNIPPETS:
        _expect(snippet in hosted_api_test_text, "hosted_api_tests", f"missing quota regression coverage for {snippet}", failures)
    _expect("Redis-backed shared limiter" in doc_text and "workspace quota" in doc_text, "docs", "rate-limit/quota doc must state shared limiter and workspace quota boundary", failures)

    readiness_flags = {
        "rate_limit_fail_closed_default": "rate_limit_fail_open: bool = False" in settings_text,
        "public_demo_requires_redis_rate_limit": "Public demos need Redis-backed rate limiting" in deployment_text,
        "provider_quota_review_required": True,
        "frontend_quota_visible": "/quotas?workspace_id=${nextWorkspaceId}" in frontend_text and "hosted-quotas" in frontend_text,
    }
    readiness_flag_mismatches = {
        key: {"expected": expected, "observed": readiness_flags.get(key)}
        for key, expected in sorted(REQUIRED_READINESS_FLAGS.items())
        if readiness_flags.get(key) is not expected
    }
    evidence_inventory_exact = (
        not missing_board_evidence_ids
        and not extra_board_evidence_ids
        and not missing_rate_limit_tests
        and not missing_quota_test_snippets
    )
    quota_inventory_exact = not missing_quota_keys and not extra_quota_keys and not missing_enforced_quota_keys and not extra_enforced_quota_keys

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "checklist_blocker_tracked": checklist_blocker_tracked,
        "readiness_board_complete": board_row is not None and board_row.get("status") == "complete",
        "default_rate_limit_requests": default_limit,
        "default_rate_limit_window_seconds": default_window,
        "expected_rate_limit_backends": list(EXPECTED_RATE_LIMIT_BACKENDS),
        "rate_limit_backends": list(EXPECTED_RATE_LIMIT_BACKENDS),
        **readiness_flags,
        "required_readiness_flags": REQUIRED_READINESS_FLAGS,
        "readiness_flags": readiness_flags,
        "readiness_flag_mismatches": readiness_flag_mismatches,
        "quota_keys": sorted(quota_keys),
        "required_quota_keys": sorted(REQUIRED_QUOTA_KEYS),
        "missing_quota_keys": missing_quota_keys,
        "extra_quota_keys": extra_quota_keys,
        "enforced_quota_keys": sorted(enforced_quota_keys),
        "missing_enforced_quota_keys": missing_enforced_quota_keys,
        "extra_enforced_quota_keys": extra_enforced_quota_keys,
        "quota_inventory_exact": quota_inventory_exact,
        "required_board_evidence_ids": list(REQUIRED_BOARD_EVIDENCE),
        "board_evidence_ids": board_evidence_ids,
        "missing_board_evidence_ids": missing_board_evidence_ids,
        "extra_board_evidence_ids": extra_board_evidence_ids,
        "required_rate_limit_test_ids": list(REQUIRED_RATE_LIMIT_TESTS),
        "covered_rate_limit_test_ids": list(covered_rate_limit_tests),
        "missing_rate_limit_test_ids": list(missing_rate_limit_tests),
        "required_quota_test_snippets": list(REQUIRED_QUOTA_TEST_SNIPPETS),
        "covered_quota_test_snippets": list(covered_quota_test_snippets),
        "missing_quota_test_snippets": list(missing_quota_test_snippets),
        "evidence_inventory_exact": evidence_inventory_exact,
        "pre_provider_rate_limit_inventory_exact": evidence_inventory_exact
        and quota_inventory_exact
        and not readiness_flag_mismatches,
        "evidence": {
            "checklist": _display_path(checklist_path),
            "readiness_board": _display_path(board_path),
            "settings": _display_path(settings_path),
            "server_app": _display_path(app_path),
            "deployment_readiness": _display_path(deployment_readiness_path),
            "frontend": _display_path(frontend_path),
            "frontend_tests": _display_path(frontend_test_path),
            "rate_limit_tests": _display_path(rate_limit_test_path),
            "hosted_api_tests": _display_path(hosted_api_test_path),
            "docs": _display_path(doc_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_rate_limits_quotas_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _board_row(board: dict[str, Any]) -> dict[str, Any] | None:
    for row in board.get("blockers") or []:
        if isinstance(row, dict) and row.get("id") == BOARD_BLOCKER_ID:
            return row
    return None


def _quota_keys(app_text: str) -> set[str]:
    match = re.search(r"DEFAULT_WORKSPACE_QUOTAS\s*=\s*\{(?P<body>.*?)\n\}", app_text, re.S)
    if not match:
        return set()
    return set(re.findall(r'"(max_[a-z_]+)"\s*:', match.group("body")))


def _enforced_quota_keys(app_text: str) -> set[str]:
    return set(re.findall(r'enforce_workspace_quota\(workspace,\s*"([^"]+)"', app_text))


def _default_int(text: str, field: str) -> int | None:
    match = re.search(rf"{re.escape(field)}:\s*int\s*=\s*([0-9_]+)", text)
    if not match:
        return None
    return int(match.group(1).replace("_", ""))


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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
