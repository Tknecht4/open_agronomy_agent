from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.admin_trace_access.v1"

BACKEND_PATH = ROOT / "src/agronomy_agent/server/app.py"
FRONTEND_PATH = ROOT / "frontend/src/HostedPlatform.tsx"
FRONTEND_TEST_PATH = ROOT / "frontend/src/App.test.tsx"
OBSERVABILITY_TEST_PATH = ROOT / "tests/test_phase5_observability.py"
HOSTED_API_TEST_PATH = ROOT / "tests/test_phase4_hosted_api.py"
MATRIX_PATH = ROOT / "docs/phase6_launch_gate_matrix.yaml"

REQUIRED_SNIPPETS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "backend": (
        'ORG_ADMIN_ROLES = {"owner", "admin"}',
        'workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)',
        '@app.get("/admin/metrics")',
        '@app.get("/admin/monitoring")',
        '@app.get("/api/admin/frontend-rum")',
        '@app.get("/api/admin/frontend-events")',
        '@app.get("/admin/audit-events")',
        '@app.get("/api/admin/traces/{trace_id}")',
        'trace_payload = store.get_phase5_admin_trace(trace_id)',
        'require_workspace_role(user, str(workspace_id), ORG_ADMIN_ROLES)',
        '@app.get("/api/admin/latency")',
        '@app.get("/api/admin/latency/export")',
        '@app.get("/api/admin/threads/{thread_id}/phase5-traces")',
        'require_workspace_role(user, thread["workspace_id"], ORG_ADMIN_ROLES)',
    ),
    "observability_test": (
        'admin_trace = client.get(f"/api/admin/traces/{trace_id}", headers=USER_A)',
        "assert admin_trace.status_code == 200",
        'thread_bundle = client.get(f"/api/admin/threads/{metrics[\'thread_id\']}/phase5-traces", headers=USER_A)',
        "assert thread_bundle.status_code == 200",
        'denied = client.get(f"/api/admin/traces/{trace_id}", headers=USER_B)',
        "assert denied.status_code == 403",
        'denied_bundle = client.get(f"/api/admin/threads/{metrics[\'thread_id\']}/phase5-traces", headers=USER_B)',
        "assert denied_bundle.status_code == 403",
    ),
    "hosted_api_test": (
        'denied_viewer = client.get(f"/admin/metrics?workspace_id={ids[\'workspace_id\']}", headers=USER_B)',
        "assert denied_viewer.status_code == 403",
        'denied_monitoring = client.get(f"/admin/monitoring?workspace_id={ids[\'workspace_id\']}", headers=USER_B)',
        "assert denied_monitoring.status_code == 403",
    ),
    "frontend": (
        "canAdmin: ['owner', 'admin'].includes(normalized)",
        "if (phase5TraceId && capabilities.canAdmin)",
        "const loadAdminOps = async () =>",
        "/admin/metrics?workspace_id=${workspaceId}",
        "/admin/monitoring?workspace_id=${workspaceId}",
        "/api/admin/latency?workspace_id=${workspaceId}",
        "/api/admin/frontend-rum?workspace_id=${workspaceId}",
        "/api/admin/frontend-events?workspace_id=${workspaceId}",
        "optionalAdminOps",
        "failure: `${label}: ${errorMessage(error)}`",
        "adminOps.failures.length > 0",
        'data-testid="hosted-admin-ops-failures"',
        "/admin/audit-events?workspace_id=${workspaceId}&limit=10",
        "{capabilities.canAdmin ? (",
        'data-testid="hosted-admin-panel"',
    ),
    "frontend_test": (
        "shows admin operations only for owner or admin roles",
        "expect(screen.getByTestId('hosted-admin-panel')).toBeInTheDocument()",
        "expect(screen.queryByTestId('hosted-admin-panel')).not.toBeInTheDocument()",
        "hosted-load-admin-ops",
        "hosted-phase5-latency",
        "hosted-frontend-rum",
        "hosted-frontend-events",
        "surfaces partial admin observability load failures",
        "hosted-admin-ops-failures",
        "Admin operations loaded with 1 observability warning",
    ),
    "launch_gate_matrix": (
        "id: admin_trace_access_control",
        "status: complete",
        "Admin trace view works but is access controlled.",
    ),
}


def validate_phase6_admin_trace_access(
    *,
    backend_path: Path = BACKEND_PATH,
    frontend_path: Path = FRONTEND_PATH,
    frontend_test_path: Path = FRONTEND_TEST_PATH,
    observability_test_path: Path = OBSERVABILITY_TEST_PATH,
    hosted_api_test_path: Path = HOSTED_API_TEST_PATH,
    matrix_path: Path = MATRIX_PATH,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    backend = _read(backend_path, "backend", failures)
    frontend = _read(frontend_path, "frontend", failures)
    frontend_test = _read(frontend_test_path, "frontend_test", failures)
    observability_test = _read(observability_test_path, "observability_test", failures)
    hosted_api_test = _read(hosted_api_test_path, "hosted_api_test", failures)
    matrix = _read(matrix_path, "launch_gate_matrix", failures)
    texts_by_section = {
        "backend": backend,
        "frontend": frontend,
        "frontend_test": frontend_test,
        "observability_test": observability_test,
        "hosted_api_test": hosted_api_test,
        "launch_gate_matrix": matrix,
    }

    admin_roles_restricted = _require_all(
        backend,
        "backend",
        failures,
        REQUIRED_SNIPPETS_BY_SECTION["backend"],
    )
    phase5_admin_trace_access_controlled = _require_all(
        observability_test,
        "observability_test",
        failures,
        REQUIRED_SNIPPETS_BY_SECTION["observability_test"],
    )
    cross_workspace_denial_covered = _require_all(
        hosted_api_test,
        "hosted_api_test",
        failures,
        REQUIRED_SNIPPETS_BY_SECTION["hosted_api_test"],
    )
    admin_ops_frontend_gated = _require_all(
        frontend,
        "frontend",
        failures,
        REQUIRED_SNIPPETS_BY_SECTION["frontend"],
    )
    admin_ops_failures_visible = _require_all(
        frontend,
        "frontend",
        failures,
        (
            "optionalAdminOps",
            "failure: `${label}: ${errorMessage(error)}`",
            "adminOps.failures.length > 0",
            'data-testid="hosted-admin-ops-failures"',
        ),
    ) and _require_all(
        frontend_test,
        "frontend_test",
        failures,
        (
            "surfaces partial admin observability load failures",
            "hosted-admin-ops-failures",
            "Admin operations loaded with 1 observability warning",
        ),
    )
    frontend_admin_role_tests = _require_all(
        frontend_test,
        "frontend_test",
        failures,
        REQUIRED_SNIPPETS_BY_SECTION["frontend_test"],
    )
    launch_gate_complete = _require_all(
        matrix,
        "launch_gate_matrix",
        failures,
        REQUIRED_SNIPPETS_BY_SECTION["launch_gate_matrix"],
    )
    expected_snippets_by_section = _json_snippet_map(REQUIRED_SNIPPETS_BY_SECTION)
    observed_snippets_by_section = _observed_snippets_by_section(texts_by_section)
    missing_snippets_by_section = _missing_snippets_by_section(observed_snippets_by_section)
    snippet_inventory_exact = (
        observed_snippets_by_section == expected_snippets_by_section
        and not any(missing_snippets_by_section.values())
    )

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "snippet_inventory_exact": snippet_inventory_exact,
        "expected_snippets_by_section": expected_snippets_by_section,
        "observed_snippets_by_section": observed_snippets_by_section,
        "missing_snippets_by_section": missing_snippets_by_section,
        "launch_gate_complete": launch_gate_complete,
        "admin_roles_restricted": admin_roles_restricted,
        "phase5_admin_trace_access_controlled": phase5_admin_trace_access_controlled,
        "cross_workspace_denial_covered": cross_workspace_denial_covered,
        "admin_ops_frontend_gated": admin_ops_frontend_gated,
        "admin_ops_failures_visible": admin_ops_failures_visible,
        "normal_user_admin_panel_hidden": frontend_admin_role_tests,
        "evidence": {
            "backend": _display_path(backend_path),
            "frontend": _display_path(frontend_path),
            "frontend_test": _display_path(frontend_test_path),
            "observability_test": _display_path(observability_test_path),
            "hosted_api_test": _display_path(hosted_api_test_path),
            "launch_gate_matrix": _display_path(matrix_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_admin_trace_access_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _require_all(text: str, section: str, failures: list[dict[str, str]], snippets: tuple[str, ...]) -> bool:
    missing = [snippet for snippet in snippets if snippet not in text]
    for snippet in missing:
        failures.append({"section": section, "reason": f"missing required evidence snippet: {snippet}"})
    return not missing


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
