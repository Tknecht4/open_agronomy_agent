from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.reports_source_provenance.v1"

SCHEMA_PATH = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_report_manifest_schema.json"
REPORT_TEMPLATES_PATH = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_report_templates.yaml"
EXPORT_SERVICE_PATH = ROOT / "src/agronomy_agent/server/services/export_service.py"
APP_PATH = ROOT / "src/agronomy_agent/server/app.py"
REPORTS_TEST_PATH = ROOT / "tests/test_phase6_reports.py"
FRONTEND_TEST_PATH = ROOT / "frontend/src/App.test.tsx"
SAMPLE_REPORTS_DIR = ROOT / "docs/phase6_sample_reports"
MATRIX_PATH = ROOT / "docs/phase6_launch_gate_matrix.yaml"

EXPECTED_REPORTS: dict[str, dict[str, Any]] = {
    "thread_report": {
        "formats": ["pdf", "markdown", "json"],
        "files": {"phase6_report_manifest.json", "thread_report.json", "thread_report.md", "thread_report.pdf"},
        "export_function": "create_phase6_thread_report_export",
        "sample": True,
    },
    "field_context_brief": {
        "formats": ["pdf", "markdown"],
        "files": {"phase6_report_manifest.json", "field_context_brief.md", "field_context_brief.pdf"},
        "export_function": "create_phase6_field_context_brief_export",
        "sample": True,
    },
    "diagnostic_checklist": {
        "formats": ["pdf", "markdown", "csv"],
        "files": {"phase6_report_manifest.json", "diagnostic_checklist.csv", "diagnostic_checklist.md", "diagnostic_checklist.pdf"},
        "export_function": "create_phase6_diagnostic_checklist_export",
        "sample": False,
    },
    "source_evidence_bundle": {
        "formats": ["json", "csv", "markdown"],
        "files": {"phase6_report_manifest.json", "source_evidence_bundle.json", "source_evidence_bundle.csv", "source_evidence_bundle.md"},
        "export_function": "create_phase6_source_evidence_bundle_export",
        "sample": False,
    },
    "learning_trace_export": {
        "formats": ["jsonl"],
        "files": {"phase6_report_manifest.json", "learning_trace_export.jsonl"},
        "export_function": "create_phase6_learning_trace_export",
        "sample": False,
    },
    "data_source_audit": {
        "formats": ["pdf", "csv"],
        "files": {"phase6_report_manifest.json", "data_source_audit.csv", "data_source_audit.pdf"},
        "export_function": "create_phase6_data_source_audit_export",
        "sample": False,
    },
    "demo_eval_snapshot": {
        "formats": ["pdf", "markdown"],
        "files": {"phase6_report_manifest.json", "demo_eval_snapshot.md", "demo_eval_snapshot.pdf"},
        "export_function": "create_phase6_demo_eval_snapshot_export",
        "sample": True,
    },
}

FORBIDDEN_PUBLIC_SNIPPETS = (
    "Routing notes",
    "Tool notes",
    "Answer coverage checklist",
    "hidden instructions",
    "prompt_messages",
)
EXPECTED_DATA_ORIGINS = {
    "user_entered_field_data",
    "retrieved_regional_prior",
    "retrieved_evidence",
    "generated_text",
    "system_metadata",
    "internal_trace",
    "mixed",
}
REQUIRED_SAMPLE_DATA_ORIGINS = {
    "thread_report": {"user_entered_field_data", "retrieved_evidence", "generated_text"},
    "field_context_brief": {"user_entered_field_data", "retrieved_regional_prior", "generated_text"},
    "demo_eval_snapshot": {"generated_text", "system_metadata"},
}
REQUIRED_MODEL_CONTEXT_FIELDS = {"model_id", "prompt_version", "context_policy_version", "corpus_version"}
DISCLAIMER_PATTERNS = (
    ("not a substitute", "local agronom"),
    ("does not create a diagnosis", "local agronomy review"),
    ("not an independent benchmark", "not a product claim", "local agronomy review"),
)
SYSTEM_CONTEXT_SNIPPETS = ("Created:", "prompt_version:", "context_policy_version:", "corpus_version:")
EXPECTED_TEMPLATE_SECTIONS = {
    "thread_report": {
        "title",
        "field_context_used",
        "user_question",
        "public_answer",
        "evidence_cards",
        "missing_data",
        "caveats",
        "next_steps",
        "source_list",
        "system_context_footer",
    },
    "field_context_brief": {
        "field_profile",
        "regional_prior",
        "soil_water_context",
        "known_unknowns",
        "data_quality_meter",
        "next_measurements",
    },
    "diagnostic_checklist": {
        "field_context_used",
        "triage_steps",
        "measurement_plan",
        "missing_data",
        "caveats",
        "next_steps",
        "source_list",
        "system_context_footer",
    },
    "source_evidence_bundle": {
        "retrieved_docs",
        "kg_hits",
        "source_metadata",
        "license_status",
        "ranking_context",
        "excluded_internal_fields",
    },
    "learning_trace_export": {
        "redacted_thread",
        "trace_spans",
        "feedback",
        "reflection_candidates",
        "consent_state",
        "review_status",
    },
    "data_source_audit": {
        "source_coverage",
        "license_status",
        "update_dates",
        "gaps",
        "sources",
        "excluded_fields",
    },
    "demo_eval_snapshot": {
        "eval_summary",
        "limitations",
        "model_context",
        "corpus_context",
        "included_metrics",
        "caveats",
        "system_context_footer",
    },
}
REQUIRED_EXPORT_SERVICE_SNIPPETS: tuple[str, ...] = tuple(
    [
        "build_phase6_report_manifest",
        '"hidden_prompts_excluded": True',
        '"source": "phase4_thread_snapshot"',
        "_file_record(",
    ]
    + [
        snippet
        for report_type, spec in EXPECTED_REPORTS.items()
        for snippet in (
            spec["export_function"],
            f'if export_type == "{report_type}":',
            f'export_type="{report_type}"',
            f'"phase6.{report_type}.v1"',
        )
    ]
)
REQUIRED_REPORTS_TEST_SNIPPETS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            "_assert_reproducibility(",
            'validate(manifest, schema)',
            'assert "Routing notes" not in markdown_download.text',
            "assert denied.status_code == 403",
        ]
        + [
            snippet
            for report_type, spec in EXPECTED_REPORTS.items()
            for snippet in (
                f'json={{"export_type": "{report_type}"}}',
                f'assert manifest["report_type"] == "{report_type}"',
                f'assert manifest["formats"] == {json.dumps(spec["formats"])}',
                *tuple(sorted(spec["files"])),
            )
        ]
        + [
            '"prompt_messages" in report["excluded_internal_fields"]',
            '"coverage_checklist" in report["excluded_internal_fields"]',
            'assert private_source_text not in csv_download.text',
        ]
    )
)
REQUIRED_SOURCE_PROVENANCE_SNIPPETS: tuple[str, ...] = (
    '"source_refs"',
    'assert report["evidence_cards"]',
    'assert report["source_metadata"][0]["license_status"] == "review_required"',
    'assert "row_type,rank,id,title,source,source_type,license_status,score,note" in csv_download.text',
    'assert report["source_coverage"]["source_count"] == 2',
    'assert "source_id,title,publisher,source_kind,source_type,license_state,license_status" in csv_download.text',
    '"source_list"',
    '"model_context"',
    '"data_policy"',
    '"reproducibility"',
)
REQUIRED_ASYNC_EXPORT_JOB_SNIPPETS: tuple[str, ...] = (
    '@app.get("/export-jobs")',
    '@app.get("/export-jobs/{job_id}")',
    "store.list_phase4_export_jobs(",
    'require_workspace_for_user(user, job["workspace_id"])',
    "test_phase6_report_export_jobs_expose_scoped_async_progress",
    'f"/export-jobs?workspace_id={workspace_id}&thread_id={thread_id}"',
    'f"/export-jobs/{job',
    "hosted-load-export-jobs",
    "hosted-export-jobs",
    "/export-jobs?workspace_id=workspace_1&limit=1&thread_id=thread_1",
)
REQUIRED_LAUNCH_GATE_SNIPPETS: tuple[str, ...] = (
    "id: reports_source_provenance",
    "status: complete",
    "Reports render correctly and include source/provenance metadata.",
)
REQUIRED_SNIPPETS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "async_export_jobs": REQUIRED_ASYNC_EXPORT_JOB_SNIPPETS,
    "export_service": REQUIRED_EXPORT_SERVICE_SNIPPETS,
    "launch_gate_matrix": REQUIRED_LAUNCH_GATE_SNIPPETS,
    "reports_test": REQUIRED_REPORTS_TEST_SNIPPETS,
    "source_provenance": REQUIRED_SOURCE_PROVENANCE_SNIPPETS,
}


def validate_phase6_reports_source_provenance(
    *,
    schema_path: Path = SCHEMA_PATH,
    report_templates_path: Path = REPORT_TEMPLATES_PATH,
    export_service_path: Path = EXPORT_SERVICE_PATH,
    app_path: Path = APP_PATH,
    reports_test_path: Path = REPORTS_TEST_PATH,
    frontend_test_path: Path = FRONTEND_TEST_PATH,
    sample_reports_dir: Path = SAMPLE_REPORTS_DIR,
    matrix_path: Path = MATRIX_PATH,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    schema = _load_json(schema_path, "manifest_schema", failures)
    report_templates = _load_yaml(report_templates_path, "report_templates", failures)
    export_service = _read(export_service_path, "export_service", failures)
    app = _read(app_path, "app", failures)
    reports_test = _read(reports_test_path, "reports_test", failures)
    frontend_test = _read(frontend_test_path, "frontend_test", failures)
    sample_manifest = _load_json(sample_reports_dir / "sample_reports_manifest.json", "sample_reports", failures)
    matrix = _read(matrix_path, "launch_gate_matrix", failures)
    snippet_texts_by_section = {
        "async_export_jobs": "\n".join([app, reports_test, frontend_test]),
        "export_service": export_service,
        "launch_gate_matrix": matrix,
        "reports_test": reports_test,
        "source_provenance": _test_and_service_text(reports_test, export_service),
    }

    schema_covers_all_report_types = _schema_covers_all_report_types(schema, failures)
    template_catalog_covers_all_report_types = _template_catalog_covers_all_report_types(report_templates, failures)
    export_service_covers_all_report_types = _export_service_covers_all_report_types(export_service, failures)
    tests_cover_all_report_types = _tests_cover_all_report_types(reports_test, failures)
    sample_reports_validate = _sample_reports_validate(sample_manifest, schema, sample_reports_dir, failures)
    sample_data_origins_covered = _sample_data_origins_covered(sample_manifest, sample_reports_dir, failures)
    packet_metadata_and_disclaimers_covered = _packet_metadata_and_disclaimers_covered(sample_manifest, sample_reports_dir, failures)
    hidden_scaffolding_excluded = _hidden_scaffolding_excluded(reports_test, sample_reports_dir, failures)
    source_provenance_covered = _source_provenance_covered(reports_test, export_service, failures)
    async_export_jobs_covered = _async_export_jobs_covered(app, reports_test, frontend_test, failures)
    launch_gate_complete = _require_all(matrix, "launch_gate_matrix", failures, list(REQUIRED_LAUNCH_GATE_SNIPPETS))
    expected_snippets_by_section = _json_snippet_map(REQUIRED_SNIPPETS_BY_SECTION)
    observed_snippets_by_section = _observed_snippets_by_section(snippet_texts_by_section)
    missing_snippets_by_section = _missing_snippets_by_section(observed_snippets_by_section)
    snippet_inventory_exact = observed_snippets_by_section == expected_snippets_by_section and not any(missing_snippets_by_section.values())

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "launch_gate_complete": launch_gate_complete,
        "schema_covers_all_report_types": schema_covers_all_report_types,
        "template_catalog_covers_all_report_types": template_catalog_covers_all_report_types,
        "export_service_covers_all_report_types": export_service_covers_all_report_types,
        "tests_cover_all_report_types": tests_cover_all_report_types,
        "sample_reports_validate": sample_reports_validate,
        "sample_data_origins_covered": sample_data_origins_covered,
        "packet_metadata_and_disclaimers_covered": packet_metadata_and_disclaimers_covered,
        "hidden_scaffolding_excluded": hidden_scaffolding_excluded,
        "source_provenance_covered": source_provenance_covered,
        "async_export_jobs_covered": async_export_jobs_covered,
        "expected_snippets_by_section": expected_snippets_by_section,
        "observed_snippets_by_section": observed_snippets_by_section,
        "missing_snippets_by_section": missing_snippets_by_section,
        "snippet_inventory_exact": snippet_inventory_exact,
        "report_types": sorted(EXPECTED_REPORTS),
        "sample_report_types": sorted(
            report.get("report_type")
            for report in sample_manifest.get("reports", [])
            if isinstance(report, dict) and report.get("report_type")
        ),
        "evidence": {
            "manifest_schema": _display_path(schema_path),
            "report_templates": _display_path(report_templates_path),
            "export_service": _display_path(export_service_path),
            "app": _display_path(app_path),
            "reports_test": _display_path(reports_test_path),
            "frontend_test": _display_path(frontend_test_path),
            "sample_reports": _display_path(sample_reports_dir),
            "launch_gate_matrix": _display_path(matrix_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_reports_source_provenance_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _schema_covers_all_report_types(schema: dict[str, Any], failures: list[dict[str, str]]) -> bool:
    report_type_enum = set(
        schema.get("properties", {})
        .get("report_type", {})
        .get("enum", [])
    )
    format_enum = set(
        schema.get("properties", {})
        .get("formats", {})
        .get("items", {})
        .get("enum", [])
    )
    ok = True
    for report_type, spec in EXPECTED_REPORTS.items():
        if report_type not in report_type_enum:
            failures.append({"section": "manifest_schema", "reason": f"report_type enum missing {report_type}"})
            ok = False
        for report_format in spec["formats"]:
            if report_format not in format_enum:
                failures.append({"section": "manifest_schema", "reason": f"formats enum missing {report_format}"})
                ok = False
    for required in ["reproducibility", "model_context", "data_policy", "sections"]:
        if required not in schema.get("properties", {}):
            failures.append({"section": "manifest_schema", "reason": f"schema missing {required} property"})
            ok = False
    model_context = schema.get("properties", {}).get("model_context", {})
    model_required = set(model_context.get("required") or [])
    missing_model_fields = REQUIRED_MODEL_CONTEXT_FIELDS - model_required
    if missing_model_fields:
        failures.append(
            {
                "section": "manifest_schema",
                "reason": f"model_context required fields missing {sorted(missing_model_fields)}",
            }
        )
        ok = False
    section_properties = schema.get("properties", {}).get("sections", {}).get("items", {}).get("properties", {})
    data_origin_enum = set(section_properties.get("data_origin", {}).get("enum", []))
    if not EXPECTED_DATA_ORIGINS <= data_origin_enum:
        failures.append(
            {
                "section": "manifest_schema",
                "reason": f"data_origin enum missing {sorted(EXPECTED_DATA_ORIGINS - data_origin_enum)}",
            }
        )
        ok = False
    return ok


def _template_catalog_covers_all_report_types(templates: dict[str, Any], failures: list[dict[str, str]]) -> bool:
    ok = True
    template_types = set(templates)
    expected_types = set(EXPECTED_REPORTS)
    missing_types = sorted(expected_types - template_types)
    extra_types = sorted(template_types - expected_types)
    for report_type in missing_types:
        failures.append({"section": "report_templates", "reason": f"template catalog missing {report_type}"})
        ok = False
    for report_type in extra_types:
        failures.append({"section": "report_templates", "reason": f"template catalog has unexpected report type {report_type}"})
        ok = False
    for report_type, spec in EXPECTED_REPORTS.items():
        template = templates.get(report_type)
        if not isinstance(template, dict):
            continue
        formats = template.get("formats")
        if formats != spec["formats"]:
            failures.append(
                {
                    "section": "report_templates",
                    "reason": f"{report_type} formats must be {spec['formats']}",
                }
            )
            ok = False
        sections = set(template.get("sections") or [])
        expected_sections = EXPECTED_TEMPLATE_SECTIONS[report_type]
        missing_sections = sorted(expected_sections - sections)
        extra_sections = sorted(sections - expected_sections)
        if missing_sections:
            failures.append(
                {
                    "section": "report_templates",
                    "reason": f"{report_type} sections missing {missing_sections}",
                }
            )
            ok = False
        if extra_sections:
            failures.append(
                {
                    "section": "report_templates",
                    "reason": f"{report_type} sections must not include non-packet entries {extra_sections}",
                }
            )
            ok = False
    return ok


def _export_service_covers_all_report_types(text: str, failures: list[dict[str, str]]) -> bool:
    return _require_all(text, "export_service", failures, list(REQUIRED_EXPORT_SERVICE_SNIPPETS))


def _tests_cover_all_report_types(text: str, failures: list[dict[str, str]]) -> bool:
    test_snippets = [
        snippet
        for snippet in REQUIRED_REPORTS_TEST_SNIPPETS
        if snippet
        not in {
            '"prompt_messages" in report["excluded_internal_fields"]',
            '"coverage_checklist" in report["excluded_internal_fields"]',
            'assert private_source_text not in csv_download.text',
        }
    ]
    return _require_all(text, "reports_test", failures, test_snippets)


def _sample_reports_validate(
    sample_manifest: dict[str, Any],
    schema: dict[str, Any],
    sample_reports_dir: Path,
    failures: list[dict[str, str]],
) -> bool:
    ok = True
    if sample_manifest.get("schema_version") != "phase6.sample_reports.v1":
        failures.append({"section": "sample_reports", "reason": "sample report manifest schema_version must be phase6.sample_reports.v1"})
        ok = False
    data_policy = sample_manifest.get("data_policy")
    if not isinstance(data_policy, dict) or data_policy.get("contains_hidden_prompt_or_trace_scaffolding") is not False:
        failures.append({"section": "sample_reports", "reason": "sample manifest must declare no hidden prompt or trace scaffolding"})
        ok = False
    by_type = {
        str(report.get("report_type")): report
        for report in sample_manifest.get("reports", [])
        if isinstance(report, dict) and report.get("report_type")
    }
    for report_type, spec in EXPECTED_REPORTS.items():
        if not spec["sample"]:
            continue
        sample = by_type.get(report_type)
        if sample is None:
            failures.append({"section": "sample_reports", "reason": f"sample manifest missing {report_type}"})
            ok = False
            continue
        sample_dir = sample_reports_dir / str(sample.get("directory") or "")
        manifest_path = sample_dir / "phase6_report_manifest.json"
        manifest = _load_json(manifest_path, f"sample_reports.{report_type}", failures)
        ok = _manifest_matches_schema_subset(manifest, schema, report_type, spec["formats"], failures) and ok
        ok = _sample_files_match_manifest(sample, sample_dir, spec["files"], failures) and ok
    return ok


def _manifest_matches_schema_subset(
    manifest: dict[str, Any],
    schema: dict[str, Any],
    report_type: str,
    formats: list[str],
    failures: list[dict[str, str]],
) -> bool:
    ok = True
    required = schema.get("required", [])
    for field in required:
        if field not in manifest:
            failures.append({"section": f"sample_reports.{report_type}", "reason": f"manifest missing required field {field}"})
            ok = False
    if manifest.get("report_type") != report_type:
        failures.append({"section": f"sample_reports.{report_type}", "reason": f"manifest report_type must be {report_type}"})
        ok = False
    if manifest.get("formats") != formats:
        failures.append({"section": f"sample_reports.{report_type}", "reason": f"manifest formats must be {formats}"})
        ok = False
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"].strip():
        failures.append({"section": f"sample_reports.{report_type}", "reason": "manifest must include created_at date"})
        ok = False
    model_context = manifest.get("model_context")
    if not isinstance(model_context, dict):
        failures.append({"section": f"sample_reports.{report_type}", "reason": "manifest must include model_context object"})
        ok = False
    else:
        for field in sorted(REQUIRED_MODEL_CONTEXT_FIELDS):
            value = str(model_context.get(field) or "").strip()
            if not value or value == "unknown":
                failures.append({"section": f"sample_reports.{report_type}", "reason": f"model_context.{field} must be populated"})
                ok = False
    reproducibility = manifest.get("reproducibility")
    if not isinstance(reproducibility, dict) or reproducibility.get("hidden_prompts_excluded") is not True:
        failures.append({"section": f"sample_reports.{report_type}", "reason": "manifest must mark hidden prompts excluded"})
        ok = False
    if not isinstance(manifest.get("sections"), list) or not manifest["sections"]:
        failures.append({"section": f"sample_reports.{report_type}", "reason": "manifest sections must be non-empty"})
        ok = False
    for section in manifest.get("sections") or []:
        if not isinstance(section, dict):
            continue
        data_origin = section.get("data_origin")
        if data_origin not in EXPECTED_DATA_ORIGINS:
            failures.append(
                {
                    "section": f"sample_reports.{report_type}",
                    "reason": f"section {section.get('section_id')} has invalid data_origin {data_origin!r}",
                }
            )
            ok = False
    return ok


def _packet_metadata_and_disclaimers_covered(
    sample_manifest: dict[str, Any],
    sample_reports_dir: Path,
    failures: list[dict[str, str]],
) -> bool:
    ok = True
    for sample in sample_manifest.get("reports") or []:
        if not isinstance(sample, dict):
            continue
        report_type = str(sample.get("report_type") or "")
        if report_type not in REQUIRED_SAMPLE_DATA_ORIGINS:
            continue
        sample_dir = sample_reports_dir / str(sample.get("directory") or "")
        manifest = _load_json(sample_dir / "phase6_report_manifest.json", f"sample_reports.{report_type}", failures)
        markdown_path = sample_dir / f"{report_type}.md"
        markdown = _read(markdown_path, f"sample_reports.{report_type}", failures)
        lower_markdown = markdown.lower()
        for snippet in SYSTEM_CONTEXT_SNIPPETS:
            if snippet not in markdown:
                failures.append({"section": f"sample_reports.{report_type}", "reason": f"markdown missing packet metadata snippet {snippet}"})
                ok = False
        if not any(all(term in lower_markdown for term in pattern) for pattern in DISCLAIMER_PATTERNS):
            failures.append({"section": f"sample_reports.{report_type}", "reason": "markdown missing report disclaimer"})
            ok = False
        model_context = manifest.get("model_context") if isinstance(manifest.get("model_context"), dict) else {}
        for field in sorted(REQUIRED_MODEL_CONTEXT_FIELDS):
            value = str(model_context.get(field) or "").strip()
            if value and value in markdown:
                continue
            failures.append({"section": f"sample_reports.{report_type}", "reason": f"markdown missing model_context.{field} value"})
            ok = False
    return ok


def _sample_data_origins_covered(
    sample_manifest: dict[str, Any],
    sample_reports_dir: Path,
    failures: list[dict[str, str]],
) -> bool:
    ok = True
    for sample in sample_manifest.get("reports") or []:
        if not isinstance(sample, dict):
            continue
        report_type = str(sample.get("report_type") or "")
        required_origins = REQUIRED_SAMPLE_DATA_ORIGINS.get(report_type)
        if not required_origins:
            continue
        manifest = _load_json(
            sample_reports_dir / str(sample.get("directory") or "") / "phase6_report_manifest.json",
            f"sample_reports.{report_type}",
            failures,
        )
        origins = {
            str(section.get("data_origin"))
            for section in manifest.get("sections") or []
            if isinstance(section, dict) and section.get("data_origin")
        }
        missing = required_origins - origins
        if missing:
            failures.append(
                {
                    "section": f"sample_reports.{report_type}",
                    "reason": f"sample report data_origin coverage missing {sorted(missing)}",
                }
            )
            ok = False
    return ok


def _sample_files_match_manifest(sample: dict[str, Any], sample_dir: Path, expected_files: set[str], failures: list[dict[str, str]]) -> bool:
    ok = True
    file_records = sample.get("files")
    if not isinstance(file_records, list):
        failures.append({"section": "sample_reports", "reason": f"{sample.get('report_type')} files must be a list"})
        return False
    actual_files = {str(record.get("filename")) for record in file_records if isinstance(record, dict)}
    missing = expected_files - actual_files
    extra = actual_files - expected_files
    if missing or extra:
        failures.append({"section": "sample_reports", "reason": f"{sample.get('report_type')} files mismatch missing={sorted(missing)} extra={sorted(extra)}"})
        ok = False
    for record in file_records:
        if not isinstance(record, dict):
            continue
        filename = str(record.get("filename"))
        path = sample_dir / filename
        if not path.exists():
            failures.append({"section": "sample_reports", "reason": f"sample file missing {path}"})
            ok = False
            continue
        if path.stat().st_size != int(record.get("bytes") or -1):
            failures.append({"section": "sample_reports", "reason": f"sample file byte count drifted for {filename}"})
            ok = False
        if filename.endswith(".pdf") and not path.read_bytes().startswith(b"%PDF-"):
            failures.append({"section": "sample_reports", "reason": f"sample PDF does not start with %PDF-: {filename}"})
            ok = False
    return ok


def _hidden_scaffolding_excluded(text: str, sample_reports_dir: Path, failures: list[dict[str, str]]) -> bool:
    ok = _require_all(
        text,
        "reports_test",
        failures,
        [
            'assert "Routing notes" not in markdown_download.text',
            '"prompt_messages" in report["excluded_internal_fields"]',
            '"coverage_checklist" in report["excluded_internal_fields"]',
            'assert private_source_text not in csv_download.text',
        ],
    )
    for path in sample_reports_dir.rglob("*"):
        if path.suffix.lower() not in {".md", ".json", ".csv"}:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for snippet in FORBIDDEN_PUBLIC_SNIPPETS:
            if snippet in content:
                failures.append({"section": "sample_reports", "reason": f"forbidden scaffolding snippet {snippet!r} found in {_display_path(path)}"})
                ok = False
    return ok


def _source_provenance_covered(test_text: str, service_text: str, failures: list[dict[str, str]]) -> bool:
    return _require_all(
        _test_and_service_text(test_text, service_text),
        "source_provenance",
        failures,
        list(REQUIRED_SOURCE_PROVENANCE_SNIPPETS),
    )


def _async_export_jobs_covered(app: str, reports_test: str, frontend_test: str, failures: list[dict[str, str]]) -> bool:
    return _require_all(
        "\n".join([app, reports_test, frontend_test]),
        "async_export_jobs",
        failures,
        list(REQUIRED_ASYNC_EXPORT_JOB_SNIPPETS),
    )


def _test_and_service_text(test_text: str, service_text: str) -> str:
    return test_text + "\n" + service_text


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


def _read(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _require_all(text: str, section: str, failures: list[dict[str, str]], snippets: list[str]) -> bool:
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
