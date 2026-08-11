from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.ui_information_architecture.v1"
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
SOURCE_SCAN_DIRS = ("src", "scripts", "frontend/src", "tests")
DEPENDENCY_FILES = ("pyproject.toml", "requirements.txt", "requirements-phase4-ci.txt")
GRADIO_SOURCE_IMPORT_RE = re.compile(
    r"^\s*(import\s+gradio\b|from\s+gradio\b|(?:const|let|var)\s+\w+\s*=\s*require\([\"']gradio[\"']\))",
    re.IGNORECASE,
)

EXPECTED_AREAS: tuple[dict[str, Any], ...] = (
    {
        "id": "home",
        "route": "/",
        "audience": "public",
        "components": ["hero", "limitations", "example_prompts", "source_coverage_summary", "github_link"],
    },
    {
        "id": "chat",
        "route": "/app/threads/:thread_id",
        "audience": "user",
        "components": ["thread_list", "chat_stream", "field_context_panel", "evidence_drawer", "feedback_panel", "report_actions"],
    },
    {
        "id": "field_context",
        "route": "/app/field-context",
        "audience": "user",
        "components": ["field_profile_list", "field_profile_editor", "regional_prior_card", "context_quality_meter"],
    },
    {
        "id": "reports",
        "route": "/app/reports",
        "audience": "user",
        "components": ["report_list", "report_preview", "export_jobs", "share_controls"],
    },
    {
        "id": "sources",
        "route": "/sources",
        "audience": "public/user",
        "components": ["coverage_map", "source_table", "license_status", "known_gaps"],
    },
    {
        "id": "account",
        "route": "/app/account",
        "audience": "user",
        "components": ["profile", "security", "sessions", "consent", "data_export", "delete_account"],
    },
    {
        "id": "admin_eval",
        "route": "/admin/eval",
        "audience": "admin/reviewer",
        "components": ["trace_explorer", "feedback_queue", "eval_replay", "leakage_audit", "source_gap_queue"],
    },
    {
        "id": "local_preview",
        "route": "/labs/local-preview",
        "audience": "opt_in_user",
        "components": ["webgpu_probe", "local_model_status", "task_allowlist", "download_consent", "local_output_comparison"],
    },
)
EXPECTED_AREA_IDS = tuple(str(area["id"]) for area in EXPECTED_AREAS)
EXPECTED_ROUTE_BY_AREA = {str(area["id"]): str(area["route"]) for area in EXPECTED_AREAS}
EXPECTED_AUDIENCE_BY_AREA = {str(area["id"]): str(area["audience"]) for area in EXPECTED_AREAS}
EXPECTED_COMPONENT_IDS = tuple(
    f"{area['id']}.{component}"
    for area in EXPECTED_AREAS
    for component in area["components"]
)


@dataclass(frozen=True)
class ComponentEvidence:
    area_id: str
    component_id: str
    source: str
    snippets: tuple[str, ...]
    status: str = "implemented"


COMPONENT_EVIDENCE: tuple[ComponentEvidence, ...] = (
    ComponentEvidence("home", "hero", "frontend/src/PublicDemoPages.tsx", ("phase6HomepageExplanation", "Open Agronomy Agent helps users structure agronomy questions")),
    ComponentEvidence("home", "limitations", "frontend/src/PublicDemoPages.tsx", ("Known Limitations",)),
    ComponentEvidence("home", "example_prompts", "frontend/src/PublicDemoPages.tsx", ("Prompt Library",)),
    ComponentEvidence("home", "source_coverage_summary", "frontend/src/PublicDemoPages.tsx", ("Data Source Coverage",)),
    ComponentEvidence("home", "github_link", "docs/phase6_external_links.yaml", ("github_repository", "Insert final public repository URL"), "tracked_pending_final_url"),
    ComponentEvidence("chat", "thread_list", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-load-threads"', 'data-testid="hosted-thread"')),
    ComponentEvidence("chat", "chat_stream", "frontend/src/HostedPlatform.tsx", ("/chat/stream", 'data-testid="hosted-stream-events"')),
    ComponentEvidence("chat", "field_context_panel", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-field-context"',)),
    ComponentEvidence("chat", "evidence_drawer", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-evidence-panel"', 'data-testid="hosted-open-evidence"')),
    ComponentEvidence("chat", "feedback_panel", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-feedback"',)),
    ComponentEvidence("chat", "report_actions", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-export"',)),
    ComponentEvidence("field_context", "field_profile_list", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-field-context"', 'data-testid="hosted-load-field-contexts"')),
    ComponentEvidence("field_context", "field_profile_editor", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-create-field-context"', 'data-testid="hosted-update-field-context"', 'data-testid="hosted-delete-field-context"')),
    ComponentEvidence("field_context", "regional_prior_card", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-geo-priors"',)),
    ComponentEvidence("field_context", "context_quality_meter", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-field-context-quality"', 'data-testid="hosted-field-context-readiness"')),
    ComponentEvidence("reports", "report_list", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-exports"',)),
    ComponentEvidence("reports", "report_preview", "docs/phase6_sample_reports/README.md", ("thread_report", "field_context_brief", "demo_eval_snapshot")),
    ComponentEvidence("reports", "export_jobs", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-export"', 'data-testid="hosted-load-exports"')),
    ComponentEvidence("reports", "share_controls", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-export-scope"', 'data-testid="hosted-export-type-filter"')),
    ComponentEvidence("sources", "coverage_map", "docs/phase6_data_source_coverage/README.md", ("Sources registered:", "Sources with open gaps:")),
    ComponentEvidence("sources", "source_table", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-data-sources"',)),
    ComponentEvidence("sources", "license_status", "frontend/src/HostedPlatform.tsx", ("license_state",)),
    ComponentEvidence("sources", "known_gaps", "frontend/src/HostedPlatform.tsx", ("issue_flags",)),
    ComponentEvidence("account", "profile", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-user"', 'data-testid="hosted-email"')),
    ComponentEvidence("account", "security", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-password-auth"', 'data-testid="hosted-reset-confirm"')),
    ComponentEvidence("account", "sessions", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-auth-sessions"', 'data-testid="hosted-revoke-auth-sessions"')),
    ComponentEvidence("account", "consent", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-account-consent"',)),
    ComponentEvidence("account", "data_export", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-account-export"',)),
    ComponentEvidence("account", "delete_account", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-delete-account"',)),
    ComponentEvidence("admin_eval", "trace_explorer", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-trace"', 'data-testid="phase5-admin-trace"')),
    ComponentEvidence("admin_eval", "feedback_queue", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-eval-candidates"', 'data-testid="hosted-eval-candidate-evidence"')),
    ComponentEvidence("admin_eval", "eval_replay", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-run-eval"', 'data-testid="hosted-eval-runs"')),
    ComponentEvidence("admin_eval", "leakage_audit", "frontend/src/HostedPlatform.tsx", ("leak check", 'data-testid="hosted-phase5-latency"')),
    ComponentEvidence("admin_eval", "source_gap_queue", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-corpus-health"', "issue_flags")),
    ComponentEvidence("local_preview", "webgpu_probe", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-probe-local-preview"',)),
    ComponentEvidence("local_preview", "local_model_status", "frontend/src/HostedPlatform.tsx", ('data-testid="hosted-local-inference-matrix"',)),
    ComponentEvidence("local_preview", "task_allowlist", "frontend/src/localPreview.ts", ("LocalPreviewTaskId", "taskMatrix")),
    ComponentEvidence("local_preview", "download_consent", "frontend/src/localPreview.ts", ("downloadConsent", "downloadAllowed")),
    ComponentEvidence("local_preview", "local_output_comparison", "frontend/src/localPreview.ts", ("serverHarnessRequired", "hybridFallbackReason")),
)
EXPECTED_PENDING_COMPONENT_IDS = tuple(
    f"{item.area_id}.{item.component_id}"
    for item in COMPONENT_EVIDENCE
    if item.status.startswith("tracked_pending")
)

ROUTE_PROJECTIONS: dict[str, dict[str, str]] = {
    "home": {"surface": "PublicDemoPages", "source": "frontend/src/PublicDemoPages.tsx"},
    "chat": {"surface": "HostedPlatform chat and App cockpit chat workspace", "source": "frontend/src/HostedPlatform.tsx"},
    "field_context": {"surface": "HostedPlatform field-context controls", "source": "frontend/src/HostedPlatform.tsx"},
    "reports": {"surface": "HostedPlatform export and sample-report controls", "source": "frontend/src/HostedPlatform.tsx"},
    "sources": {"surface": "HostedPlatform data-source controls and public coverage assets", "source": "frontend/src/HostedPlatform.tsx"},
    "account": {"surface": "HostedPlatform account/privacy controls", "source": "frontend/src/HostedPlatform.tsx"},
    "admin_eval": {"surface": "HostedPlatform canAdmin-gated admin/eval controls", "source": "frontend/src/HostedPlatform.tsx"},
    "local_preview": {"surface": "HostedPlatform local-preview panel", "source": "frontend/src/HostedPlatform.tsx"},
}


def validate_phase6_ui_information_architecture(
    *,
    packet_path: Path = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_ui_information_architecture.json",
    docs_path: Path = ROOT / "docs/phase6_ui_information_architecture.md",
    readme_path: Path = ROOT / "README.md",
    dependency_files: tuple[Path, ...] | None = None,
    source_scan_dirs: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    packet = _load_json(packet_path, "packet", failures)
    dependency_paths = dependency_files or tuple(ROOT / path for path in DEPENDENCY_FILES)
    scan_dirs = source_scan_dirs or tuple(ROOT / path for path in SOURCE_SCAN_DIRS)
    areas = packet.get("areas") if isinstance(packet.get("areas"), list) else []
    _expect(packet.get("phase") == "6", "packet", "phase6 UI IA packet must declare phase 6", failures)
    _validate_expected_areas(areas, failures)

    expected_components = {(area["id"], component) for area in EXPECTED_AREAS for component in area["components"]}
    evidence_by_component = {(item.area_id, item.component_id): item for item in COMPONENT_EVIDENCE}
    observed_area_ids = tuple(str(area.get("id")) for area in areas if isinstance(area, dict) and area.get("id"))
    observed_route_by_area = {
        str(area.get("id")): str(area.get("route"))
        for area in areas
        if isinstance(area, dict) and area.get("id")
    }
    observed_audience_by_area = {
        str(area.get("id")): str(area.get("audience"))
        for area in areas
        if isinstance(area, dict) and area.get("id")
    }
    observed_component_ids = tuple(
        f"{area.get('id')}.{component}"
        for area in areas
        if isinstance(area, dict) and area.get("id") and isinstance(area.get("components"), list)
        for component in area["components"]
    )
    component_evidence_ids = tuple(f"{item.area_id}.{item.component_id}" for item in COMPONENT_EVIDENCE)
    missing_area_ids = sorted(set(EXPECTED_AREA_IDS) - set(observed_area_ids))
    extra_area_ids = sorted(set(observed_area_ids) - set(EXPECTED_AREA_IDS))
    route_mismatches = {
        area_id: {"expected": expected, "observed": observed_route_by_area.get(area_id)}
        for area_id, expected in EXPECTED_ROUTE_BY_AREA.items()
        if observed_route_by_area.get(area_id) != expected
    }
    audience_mismatches = {
        area_id: {"expected": expected, "observed": observed_audience_by_area.get(area_id)}
        for area_id, expected in EXPECTED_AUDIENCE_BY_AREA.items()
        if observed_audience_by_area.get(area_id) != expected
    }
    missing_component_ids = sorted(set(EXPECTED_COMPONENT_IDS) - set(observed_component_ids))
    extra_component_ids = sorted(set(observed_component_ids) - set(EXPECTED_COMPONENT_IDS))
    missing_component_evidence_ids = sorted(set(EXPECTED_COMPONENT_IDS) - set(component_evidence_ids))
    extra_component_evidence_ids = sorted(set(component_evidence_ids) - set(EXPECTED_COMPONENT_IDS))
    for key in sorted(expected_components):
        item = evidence_by_component.get(key)
        if item is None:
            failures.append({"section": "component_evidence", "reason": f"{key[0]}.{key[1]} missing component evidence mapping"})
            continue
        _validate_component_evidence(item, failures)

    for area in EXPECTED_AREAS:
        projection = ROUTE_PROJECTIONS.get(str(area["id"]))
        _expect(bool(projection), "route_projection", f"{area['id']} missing route projection mapping", failures)
        if projection:
            _expect((ROOT / projection["source"]).exists(), "route_projection", f"{area['id']} projection source missing: {projection['source']}", failures)

    docs_text = _read_text(docs_path, "docs", failures)
    for snippet in ("single hosted React shell", "Packet route", "github_repository", "route_projection_review_required"):
        _expect(snippet in docs_text, "docs", f"phase6 UI IA docs missing {snippet}", failures)
    react_cutover = _validate_react_cutover(
        readme_path=readme_path,
        dependency_files=dependency_paths,
        source_scan_dirs=scan_dirs,
        failures=failures,
    )

    area_rows = []
    for area in EXPECTED_AREAS:
        component_rows = []
        for component in area["components"]:
            evidence = evidence_by_component.get((area["id"], component))
            component_rows.append(
                {
                    "id": component,
                    "status": evidence.status if evidence else "missing",
                    "source": evidence.source if evidence else "",
                    "snippet_count": len(evidence.snippets) if evidence else 0,
                }
            )
        area_rows.append(
            {
                "id": area["id"],
                "route": area["route"],
                "audience": area["audience"],
                "projected_surface": ROUTE_PROJECTIONS.get(area["id"], {}).get("surface", ""),
                "components": component_rows,
            }
        )

    pending_components = [
        f"{item.area_id}.{item.component_id}"
        for item in COMPONENT_EVIDENCE
        if item.status.startswith("tracked_pending")
    ]
    ui_inventory_exact = (
        not missing_area_ids
        and not extra_area_ids
        and not route_mismatches
        and not audience_mismatches
        and not missing_component_ids
        and not extra_component_ids
        and not missing_component_evidence_ids
        and not extra_component_evidence_ids
        and tuple(pending_components) == EXPECTED_PENDING_COMPONENT_IDS
    )
    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "packet_phase": packet.get("phase"),
        "area_count": len(areas),
        "expected_area_count": len(EXPECTED_AREAS),
        "expected_area_ids": list(EXPECTED_AREA_IDS),
        "observed_area_ids": list(observed_area_ids),
        "missing_area_ids": missing_area_ids,
        "extra_area_ids": extra_area_ids,
        "expected_route_by_area": EXPECTED_ROUTE_BY_AREA,
        "observed_route_by_area": observed_route_by_area,
        "route_mismatches": route_mismatches,
        "expected_audience_by_area": EXPECTED_AUDIENCE_BY_AREA,
        "observed_audience_by_area": observed_audience_by_area,
        "audience_mismatches": audience_mismatches,
        "component_count": len(expected_components),
        "expected_component_count": len(expected_components),
        "expected_component_ids": list(EXPECTED_COMPONENT_IDS),
        "observed_component_ids": list(observed_component_ids),
        "missing_component_ids": missing_component_ids,
        "extra_component_ids": extra_component_ids,
        "component_evidence_ids": list(component_evidence_ids),
        "missing_component_evidence_ids": missing_component_evidence_ids,
        "extra_component_evidence_ids": extra_component_evidence_ids,
        "tracked_component_count": len(expected_components) - len([failure for failure in failures if failure["section"] == "component_evidence"]),
        "expected_pending_component_ids": list(EXPECTED_PENDING_COMPONENT_IDS),
        "pending_external_component_ids": pending_components,
        "pending_component_inventory_exact": tuple(pending_components) == EXPECTED_PENDING_COMPONENT_IDS,
        "ui_inventory_exact": ui_inventory_exact,
        "route_projection_mode": "single_spa_shell_with_public_sections",
        "react_frontend_cutover_verified": react_cutover["verified"],
        "gradio_dependency_removed": react_cutover["dependency_removed"],
        "gradio_source_import_count": react_cutover["source_import_count"],
        "literal_packet_routes_implemented": False,
        "route_projection_review_required": True,
        "all_packet_areas_tracked": not any(failure["section"] == "packet" for failure in failures),
        "all_packet_components_tracked": not any(failure["section"] == "component_evidence" for failure in failures),
        "external_launch_ready": False,
        "areas": area_rows,
        "evidence": {
            "packet": _display_path(packet_path),
            "docs": _display_path(docs_path),
            "readme": _display_path(readme_path),
            "frontend_app": "frontend/src/App.tsx",
            "hosted_platform": "frontend/src/HostedPlatform.tsx",
            "public_demo_pages": "frontend/src/PublicDemoPages.tsx",
            "gradio_dependency_files": [_display_path(path) for path in dependency_paths],
            "gradio_source_scan_dirs": [_display_path(path) for path in scan_dirs],
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_ui_information_architecture_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_expected_areas(areas: list[Any], failures: list[dict[str, str]]) -> None:
    _expect(len(areas) == len(EXPECTED_AREAS), "packet", f"expected {len(EXPECTED_AREAS)} UI areas, found {len(areas)}", failures)
    for index, expected in enumerate(EXPECTED_AREAS):
        actual = areas[index] if index < len(areas) and isinstance(areas[index], dict) else {}
        for key in ("id", "route", "audience"):
            _expect(actual.get(key) == expected[key], "packet", f"area {index} {key} must be {expected[key]}", failures)
        actual_components = actual.get("components") if isinstance(actual.get("components"), list) else []
        _expect(actual_components == expected["components"], "packet", f"area {expected['id']} components must match packet contract", failures)
    routes = [str(area.get("route")) for area in areas if isinstance(area, dict) and area.get("route")]
    _expect(len(routes) == len(set(routes)), "packet", "packet routes must be unique", failures)


def _validate_component_evidence(item: ComponentEvidence, failures: list[dict[str, str]]) -> None:
    source_path = ROOT / item.source
    text = _read_text(source_path, "component_evidence", failures)
    for snippet in item.snippets:
        _expect(snippet in text, "component_evidence", f"{item.area_id}.{item.component_id} missing snippet {snippet!r} in {item.source}", failures)


def _validate_react_cutover(
    *,
    readme_path: Path,
    dependency_files: tuple[Path, ...],
    source_scan_dirs: tuple[Path, ...],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    readme_text = _read_text(readme_path, "react_cutover", failures)
    _expect("old prototype Gradio UI has been removed" in readme_text, "react_cutover", "README must keep the Gradio removal note", failures)
    dependency_hits: list[str] = []
    for path in dependency_files:
        text = _read_text(path, "react_cutover", failures)
        for line_number, line in enumerate(text.splitlines(), start=1):
            normalized = line.strip().lower()
            if normalized and not normalized.startswith("#") and normalized.split(";", 1)[0].split("#", 1)[0].strip().startswith("gradio"):
                dependency_hits.append(f"{_display_path(path)}:{line_number}")
    source_hits: list[str] = []
    for directory in source_scan_dirs:
        if not directory.exists():
            failures.append({"section": "react_cutover", "reason": f"source scan directory missing: {_display_path(directory)}"})
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix not in SOURCE_EXTENSIONS or "__pycache__" in path.parts:
                continue
            text = _read_text(path, "react_cutover", failures)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if GRADIO_SOURCE_IMPORT_RE.search(line):
                    source_hits.append(f"{_display_path(path)}:{line_number}")
    _expect(not dependency_hits, "react_cutover", f"Gradio dependency entries must stay removed: {dependency_hits}", failures)
    _expect(not source_hits, "react_cutover", f"Gradio source imports must stay removed: {source_hits}", failures)
    return {
        "verified": not dependency_hits and not source_hits and "old prototype Gradio UI has been removed" in readme_text,
        "dependency_removed": not dependency_hits,
        "source_import_count": len(source_hits),
    }


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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
