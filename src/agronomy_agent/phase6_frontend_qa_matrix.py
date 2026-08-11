from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.frontend_qa_matrix.v1"
DEFAULT_MATRIX = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_frontend_qa_matrix.csv"
EXPECTED_COLUMNS = ("test_area", "scenario", "tooling", "pass_condition", "launch_gate")

EXPECTED_ROWS: tuple[dict[str, str], ...] = (
    {
        "test_area": "leakage",
        "scenario": "200 launch QA turns",
        "tooling": "automated regex + human review",
        "pass_condition": "0 public leaks of hidden scaffolding",
        "launch_gate": "blocker",
    },
    {
        "test_area": "auth",
        "scenario": "signup/login/reset/session revoke",
        "tooling": "Playwright + unit tests",
        "pass_condition": "all flows pass",
        "launch_gate": "blocker",
    },
    {
        "test_area": "chat",
        "scenario": "streaming success/error/cancel",
        "tooling": "Playwright",
        "pass_condition": "correct states and no layout break",
        "launch_gate": "blocker",
    },
    {
        "test_area": "reports",
        "scenario": "PDF/MD/JSON exports",
        "tooling": "snapshot + render inspection",
        "pass_condition": "no missing sections/citations",
        "launch_gate": "blocker",
    },
    {
        "test_area": "accessibility",
        "scenario": "primary routes",
        "tooling": "axe + manual keyboard",
        "pass_condition": "no critical violations",
        "launch_gate": "blocker",
    },
    {
        "test_area": "performance",
        "scenario": "CWV lab and RUM",
        "tooling": "Lighthouse + web-vitals",
        "pass_condition": "meets budget or documented exception",
        "launch_gate": "blocker",
    },
    {
        "test_area": "desktop-tablet-mobile",
        "scenario": "chat/evidence/report flows",
        "tooling": "automated viewport matrix + BrowserStack/manual",
        "pass_condition": "usable at 375px 768px and 1120px widths",
        "launch_gate": "blocker",
    },
    {
        "test_area": "security",
        "scenario": "markdown and source rendering",
        "tooling": "fuzz tests",
        "pass_condition": "no raw HTML/script execution",
        "launch_gate": "blocker",
    },
    {
        "test_area": "local preview",
        "scenario": "WebGPU unsupported path",
        "tooling": "Playwright feature flag",
        "pass_condition": "clear fallback and no crash",
        "launch_gate": "monitor",
    },
    {
        "test_area": "data deletion",
        "scenario": "delete account/workspace/thread",
        "tooling": "integration test",
        "pass_condition": "data unavailable after purge window",
        "launch_gate": "blocker",
    },
)
EXPECTED_TEST_AREA_IDS = tuple(row["test_area"] for row in EXPECTED_ROWS)
EXPECTED_BLOCKER_TEST_AREA_IDS = tuple(row["test_area"] for row in EXPECTED_ROWS if row["launch_gate"] == "blocker")
EXPECTED_MONITOR_TEST_AREA_IDS = tuple(row["test_area"] for row in EXPECTED_ROWS if row["launch_gate"] == "monitor")

DEFAULT_EVIDENCE_BY_AREA: dict[str, tuple[str, ...]] = {
    "leakage": (
        "src/agronomy_agent/phase6_launch_qa.py",
        "scripts/run_phase6_launch_leak_qa.py",
        "tests/test_phase6_launch_qa.py",
        "outputs/phase6_launch_leak_qa_latest.json",
    ),
    "auth": (
        "src/agronomy_agent/phase6_account_privacy_rights.py",
        "scripts/phase6_browser_auth_qa_flow.js",
        "scripts/validate_phase6_account_privacy_rights.py",
        "tests/test_phase6_account_privacy_rights.py",
        "outputs/phase6_account_privacy_rights_latest.json",
    ),
    "chat": (
        "tests/test_phase6_answer_contract.py",
        "frontend/src/App.test.tsx",
        "scripts/phase6_browser_performance_lab.js",
    ),
    "reports": (
        "tests/test_phase6_reports.py",
        "src/agronomy_agent/phase6_reports_source_provenance.py",
        "scripts/validate_phase6_reports_source_provenance.py",
        "outputs/phase6_reports_source_provenance_latest.json",
    ),
    "accessibility": (
        "src/agronomy_agent/phase6_accessibility_primary_flows.py",
        "scripts/validate_phase6_accessibility_primary_flows.py",
        "frontend/src/accessibilityAudit.test.ts",
        "outputs/phase6_accessibility_primary_flows_latest.json",
    ),
    "performance": (
        "scripts/validate_phase6_frontend_performance_budget.py",
        "scripts/run_phase6_browser_performance_lab.py",
        "frontend/src/rum.test.ts",
        "outputs/phase6_frontend_performance_budget_latest.json",
    ),
    "desktop-tablet-mobile": (
        "scripts/validate_phase6_responsive_mobile_qa.py",
        "scripts/phase6_browser_responsive_qa_flow.js",
        "frontend/src/responsiveAudit.test.ts",
        "outputs/phase6_responsive_mobile_qa_latest.json",
    ),
    "security": (
        "tests/test_phase6_answer_contract.py",
        "frontend/src/renderingSecurityAudit.ts",
        "frontend/src/renderingSecurityAudit.test.ts",
    ),
    "local preview": (
        "src/agronomy_agent/phase6_local_inference_preview.py",
        "scripts/validate_phase6_local_inference_preview.py",
        "frontend/src/localPreview.test.ts",
        "outputs/phase6_local_inference_preview_latest.json",
    ),
    "data deletion": (
        "tests/test_phase6_account_export.py",
        "src/agronomy_agent/phase6_account_privacy_rights.py",
        "scripts/validate_phase6_account_privacy_rights.py",
        "outputs/phase6_account_privacy_rights_latest.json",
    ),
}


def validate_phase6_frontend_qa_matrix(
    *,
    matrix_csv: Path = DEFAULT_MATRIX,
    evidence_by_area: Mapping[str, Sequence[str]] = DEFAULT_EVIDENCE_BY_AREA,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    rows, columns = _load_matrix(matrix_csv, failures)
    expected_by_area = {row["test_area"]: row for row in EXPECTED_ROWS}
    rows_by_area = {row.get("test_area", ""): row for row in rows}
    observed_test_areas = [row.get("test_area", "") for row in rows]
    evidence_areas = {str(area) for area in evidence_by_area}
    missing_test_areas = sorted(set(EXPECTED_TEST_AREA_IDS) - set(observed_test_areas))
    extra_test_areas = sorted(set(observed_test_areas) - set(EXPECTED_TEST_AREA_IDS))
    extra_evidence_areas = sorted(evidence_areas - set(expected_by_area))
    missing_evidence_areas = sorted(set(expected_by_area) - evidence_areas)

    _expect(tuple(columns) == EXPECTED_COLUMNS, "matrix", "frontend QA matrix columns drifted", failures)
    _expect(len(rows) == len(EXPECTED_ROWS), "matrix", "frontend QA matrix row count must remain 10", failures)
    _expect(set(rows_by_area) == set(expected_by_area), "matrix", "frontend QA matrix test areas drifted", failures)
    for area in extra_evidence_areas:
        failures.append({"section": "evidence", "reason": f"unexpected evidence mapping for {area}"})

    for expected in EXPECTED_ROWS:
        area = expected["test_area"]
        row = rows_by_area.get(area, {})
        for field, expected_value in expected.items():
            _expect(row.get(field) == expected_value, "matrix", f"{area} {field} drifted from packet value", failures)

    blocker_areas = {row["test_area"] for row in EXPECTED_ROWS if row["launch_gate"] == "blocker"}
    monitor_areas = {row["test_area"] for row in EXPECTED_ROWS if row["launch_gate"] == "monitor"}
    _expect(blocker_areas == set(expected_by_area) - {"local preview"}, "matrix", "all non-local-preview rows must be blockers", failures)
    _expect(monitor_areas == {"local preview"}, "matrix", "only local preview may remain a monitor gate", failures)

    evidence_summary: dict[str, list[str]] = {}
    missing_evidence_by_area: dict[str, list[str]] = {}
    extra_evidence_by_area: dict[str, list[str]] = {}
    missing_evidence: list[str] = []
    for area in sorted(expected_by_area):
        evidence_paths = [str(path) for path in evidence_by_area.get(area, ())]
        expected_evidence_paths = set(DEFAULT_EVIDENCE_BY_AREA[area])
        evidence_path_set = set(evidence_paths)
        missing_for_area = sorted(expected_evidence_paths - evidence_path_set)
        extra_for_area = sorted(evidence_path_set - expected_evidence_paths)
        if missing_for_area:
            missing_evidence_by_area[area] = missing_for_area
            failures.append({"section": "evidence", "reason": f"{area} expected evidence paths missing: {', '.join(missing_for_area)}"})
        if extra_for_area:
            extra_evidence_by_area[area] = extra_for_area
            failures.append({"section": "evidence", "reason": f"{area} unexpected evidence paths: {', '.join(extra_for_area)}"})
        evidence_summary[area] = evidence_paths
        _expect(bool(evidence_paths), "evidence", f"{area} must have mapped evidence", failures)
        _expect(
            any(not evidence_path.startswith("outputs/") for evidence_path in evidence_paths),
            "evidence",
            f"{area} must have source, script, or test evidence",
            failures,
        )
        for evidence_path in evidence_paths:
            if evidence_path.startswith("outputs/"):
                continue
            if not (ROOT / evidence_path).exists():
                missing_evidence.append(evidence_path)
                failures.append({"section": "evidence", "reason": f"{area} evidence path missing: {evidence_path}"})

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "row_count": len(rows),
        "expected_row_count": len(EXPECTED_ROWS),
        "columns": columns,
        "expected_columns": list(EXPECTED_COLUMNS),
        "blocker_count": sum(1 for row in rows if row.get("launch_gate") == "blocker"),
        "monitor_count": sum(1 for row in rows if row.get("launch_gate") == "monitor"),
        "expected_test_areas": list(EXPECTED_TEST_AREA_IDS),
        "observed_test_areas": observed_test_areas,
        "missing_test_areas": missing_test_areas,
        "extra_test_areas": extra_test_areas,
        "expected_blocker_test_areas": list(EXPECTED_BLOCKER_TEST_AREA_IDS),
        "observed_blocker_test_areas": [row.get("test_area", "") for row in rows if row.get("launch_gate") == "blocker"],
        "expected_monitor_test_areas": list(EXPECTED_MONITOR_TEST_AREA_IDS),
        "observed_monitor_test_areas": [row.get("test_area", "") for row in rows if row.get("launch_gate") == "monitor"],
        "row_inventory_exact": observed_test_areas == list(EXPECTED_TEST_AREA_IDS) and not missing_test_areas and not extra_test_areas,
        "evidence_inventory_exact": not missing_evidence_areas and not extra_evidence_areas and not missing_evidence_by_area and not extra_evidence_by_area,
        "missing_evidence_areas": missing_evidence_areas,
        "extra_evidence_areas": extra_evidence_areas,
        "expected_evidence_by_area": {area: list(paths) for area, paths in DEFAULT_EVIDENCE_BY_AREA.items()},
        "missing_evidence_by_area": missing_evidence_by_area,
        "extra_evidence_by_area": extra_evidence_by_area,
        "all_evidence_paths_exist": not missing_evidence,
        "missing_evidence_paths": missing_evidence,
        "evidence": {
            "matrix": _display_path(matrix_csv),
            "by_area": evidence_summary,
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_frontend_qa_matrix_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_matrix(path: Path, failures: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = [str(column) for column in (reader.fieldnames or [])]
            rows = [{str(key): str(value or "") for key, value in row.items()} for row in reader]
            return rows, columns
    except Exception as exc:
        failures.append({"section": "matrix", "reason": f"could not read {_display_path(path)}: {exc}"})
        return [], []


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> None:
    if not condition:
        failures.append({"section": section, "reason": reason})


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
