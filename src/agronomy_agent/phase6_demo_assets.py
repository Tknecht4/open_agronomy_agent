from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.demo_assets.v1"

EXPECTED_ASSET_IDS = {
    "landing_page",
    "known_limitations_page",
    "data_source_coverage_page",
    "sample_field_contexts",
    "example_prompt_library",
    "sample_reports",
    "demo_script",
    "privacy_data_use_page",
    "support_feedback_page",
}
EXPECTED_ASSET_ID_LIST = (
    "landing_page",
    "known_limitations_page",
    "data_source_coverage_page",
    "sample_field_contexts",
    "example_prompt_library",
    "sample_reports",
    "demo_script",
    "privacy_data_use_page",
    "support_feedback_page",
)
EXPECTED_ASSET_STATUS_BY_ID = {asset_id: "complete" for asset_id in EXPECTED_ASSET_ID_LIST}
EXPECTED_ASSET_OWNER_ROLE_BY_ID = {
    "landing_page": "product_owner",
    "known_limitations_page": "product_science_lead",
    "data_source_coverage_page": "product_science_lead",
    "sample_field_contexts": "frontend_lead",
    "example_prompt_library": "product_owner",
    "sample_reports": "full_stack_lead",
    "demo_script": "product_owner",
    "privacy_data_use_page": "privacy_owner",
    "support_feedback_page": "product_owner",
}
EXPECTED_ASSET_PACKET_TEXT_BY_ID = {
    "landing_page": "landing page",
    "known_limitations_page": "known limitations page",
    "data_source_coverage_page": "data-source coverage page",
    "sample_field_contexts": "sample field contexts",
    "example_prompt_library": "example prompt library",
    "sample_reports": "sample reports",
    "demo_script": "demo script",
    "privacy_data_use_page": "privacy/data-use page",
    "support_feedback_page": "support/feedback page",
}
EXPECTED_PUBLIC_PAGE_IDS = {
    "landing",
    "how-it-works",
    "what-it-is-not",
    "source-coverage",
    "known-limitations",
    "prompt-library",
    "sample-reports",
    "privacy-data-use",
    "feedback-help",
    "changelog-contribute",
}
REQUIRED_HOMEPAGE_CONCEPTS = (
    "field context",
    "public sources",
    "missing data",
    "transparent advisory-style answers and reports",
    "decision support",
)
REQUIRED_PUBLIC_PAGE_SNIPPETS = (
    "Open Agronomy Agent is decision support for discussion",
    "Synthetic sample fields are available",
    "prompt/context policy version",
    "eval limitations",
    "Coverage varies by crop, region, source freshness",
    "Request source additions or takedowns",
    "Browser local preview is disabled by default",
    "Nutrient and water-quality risk",
    "Thread report: public answer",
    "Account export packages accessible records",
    "Use feedback to flag wrong route",
)
REQUIRED_DEMO_SCRIPT_SNIPPETS = (
    "Open the landing page.",
    "field-context advisory support, not label/rate/legal automation",
    "Corn Belt corn with high soil-test phosphorus and runoff risk",
    "Open \"What I used\" evidence cards.",
    "Export the thread report as PDF.",
    "Show data-source coverage page and known gaps.",
    "\"diagnoses your crop\"",
    "\"field-context reasoning\"",
)
EXPECTED_SAMPLE_REPORT_TYPES = {"thread_report", "field_context_brief", "demo_eval_snapshot"}
EXPECTED_SOURCE_CARD_FIELDS = {
    "title",
    "publisher",
    "url_or_source_id",
    "source_type",
    "region_crop",
    "license_status",
    "updated_or_ingested_date",
    "why_used",
    "known_limitations",
}
EXPECTED_SAMPLE_REPORT_FILES = {
    "thread_report": {"thread_report.md", "thread_report.pdf", "thread_report.json", "phase6_report_manifest.json"},
    "field_context_brief": {"field_context_brief.md", "field_context_brief.pdf", "phase6_report_manifest.json"},
    "demo_eval_snapshot": {"demo_eval_snapshot.md", "demo_eval_snapshot.pdf", "phase6_report_manifest.json"},
}
REQUIRED_SAMPLE_FIELD_SNIPPETS = (
    "phase6SampleFieldContexts",
    "Corn Belt phosphorus field",
    "Prairie canola low pH",
    "hosted-sample-field-context",
    "Use as a water-quality and missing-data demo context",
)
REQUIRED_TEST_SNIPPETS = (
    "creates a selected safe sample field context for demo onboarding",
    "test_phase6_sample_report_builder_writes_public_safe_launch_artifacts",
    "test_phase6_data_source_coverage_builder_writes_public_safe_launch_artifacts",
)


def validate_phase6_demo_assets(
    *,
    board_path: Path = ROOT / "docs/phase6_launch_readiness_board.yaml",
    public_pages_path: Path = ROOT / "frontend/src/PublicDemoPages.tsx",
    hosted_platform_path: Path = ROOT / "frontend/src/HostedPlatform.tsx",
    frontend_tests_path: Path = ROOT / "frontend/src/App.test.tsx",
    sample_reports_dir: Path = ROOT / "docs/phase6_sample_reports",
    data_source_coverage_dir: Path = ROOT / "docs/phase6_data_source_coverage",
    demo_script_path: Path = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_public_demo_script.md",
    sample_reports_test_path: Path = ROOT / "tests/test_phase6_sample_reports.py",
    data_source_coverage_test_path: Path = ROOT / "tests/test_phase6_data_source_coverage_assets.py",
    docs_path: Path = ROOT / "docs/phase6_demo_assets.md",
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    board = _load_yaml(board_path, "readiness_board", failures)
    public_pages = _read_text(public_pages_path, "public_pages", failures)
    hosted_platform = _read_text(hosted_platform_path, "hosted_platform", failures)
    frontend_tests = _read_text(frontend_tests_path, "frontend_tests", failures)
    demo_script = _read_text(demo_script_path, "demo_script", failures)
    sample_reports_manifest = _load_json(sample_reports_dir / "sample_reports_manifest.json", "sample_reports", failures)
    data_source_manifest = _load_json(data_source_coverage_dir / "data_source_coverage_manifest.json", "data_source_coverage", failures)
    sample_reports_tests = _read_text(sample_reports_test_path, "sample_reports_tests", failures)
    data_source_tests = _read_text(data_source_coverage_test_path, "data_source_coverage_tests", failures)
    docs_text = _read_text(docs_path, "docs", failures)

    assets = [row for row in board.get("must_have_demo_assets") or [] if isinstance(row, dict)]
    asset_ids = [str(row.get("id")) for row in assets]
    asset_id_set = set(asset_ids)
    missing_asset_ids = sorted(EXPECTED_ASSET_IDS - asset_id_set)
    extra_asset_ids = sorted(asset_id_set - EXPECTED_ASSET_IDS)
    asset_status_by_id = {str(row.get("id")): str(row.get("status") or "") for row in assets}
    asset_owner_role_by_id = {str(row.get("id")): str(row.get("owner_role") or "") for row in assets}
    asset_packet_text_by_id = {str(row.get("id")): str(row.get("packet_text") or "") for row in assets}
    asset_evidence_by_id = {
        str(row.get("id")): [str(item) for item in row.get("evidence") or []]
        for row in assets
    }
    status_mismatches = _dict_mismatches(EXPECTED_ASSET_STATUS_BY_ID, asset_status_by_id)
    owner_role_mismatches = _dict_mismatches(EXPECTED_ASSET_OWNER_ROLE_BY_ID, asset_owner_role_by_id)
    packet_text_mismatches = _dict_mismatches(EXPECTED_ASSET_PACKET_TEXT_BY_ID, asset_packet_text_by_id)
    _expect(asset_id_set == EXPECTED_ASSET_IDS, "readiness_board", f"demo asset ids must match packet assets: {sorted(asset_id_set)}", failures)
    _expect(asset_ids == list(EXPECTED_ASSET_ID_LIST), "readiness_board", "demo asset order must match packet launch asset order", failures)
    _expect(not status_mismatches, "readiness_board", f"demo asset statuses drifted: {status_mismatches}", failures)
    _expect(not owner_role_mismatches, "readiness_board", f"demo asset owner roles drifted: {owner_role_mismatches}", failures)
    _expect(not packet_text_mismatches, "readiness_board", f"demo asset packet text drifted: {packet_text_mismatches}", failures)
    for row in assets:
        asset_id = str(row.get("id") or "")
        _expect(row.get("status") == "complete", "readiness_board", f"{asset_id} must remain complete", failures)
        _expect(bool(row.get("evidence")), "readiness_board", f"{asset_id} must keep evidence", failures)
    demo_asset_inventory_exact = (
        asset_ids == list(EXPECTED_ASSET_ID_LIST)
        and not missing_asset_ids
        and not extra_asset_ids
        and not status_mismatches
        and not owner_role_mismatches
        and not packet_text_mismatches
    )

    _validate_public_pages(public_pages, failures)
    _validate_demo_script(demo_script, failures)
    _validate_sample_reports(sample_reports_manifest, sample_reports_dir, failures)
    _validate_data_source_coverage(data_source_manifest, data_source_coverage_dir, failures)
    for snippet in REQUIRED_SAMPLE_FIELD_SNIPPETS:
        _expect(snippet in hosted_platform, "hosted_platform", f"sample field context UI missing {snippet}", failures)
    for snippet in REQUIRED_TEST_SNIPPETS:
        text = "\n".join([frontend_tests, sample_reports_tests, data_source_tests])
        _expect(snippet in text, "tests", f"demo asset regression coverage missing {snippet}", failures)
    for snippet in ("landing page", "sample reports", "demo script", "privacy/data-use", "support/feedback"):
        _expect(snippet in docs_text.lower(), "docs", f"demo assets doc missing {snippet}", failures)

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "asset_count": len(assets),
        "expected_asset_ids": list(EXPECTED_ASSET_ID_LIST),
        "observed_asset_ids": asset_ids,
        "asset_ids": sorted(asset_id_set),
        "missing_asset_ids": missing_asset_ids,
        "extra_asset_ids": extra_asset_ids,
        "expected_asset_status_by_id": dict(EXPECTED_ASSET_STATUS_BY_ID),
        "asset_status_by_id": asset_status_by_id,
        "status_mismatches": status_mismatches,
        "expected_asset_owner_role_by_id": dict(EXPECTED_ASSET_OWNER_ROLE_BY_ID),
        "asset_owner_role_by_id": asset_owner_role_by_id,
        "owner_role_mismatches": owner_role_mismatches,
        "expected_asset_packet_text_by_id": dict(EXPECTED_ASSET_PACKET_TEXT_BY_ID),
        "asset_packet_text_by_id": asset_packet_text_by_id,
        "packet_text_mismatches": packet_text_mismatches,
        "asset_evidence_by_id": asset_evidence_by_id,
        "demo_asset_inventory_exact": demo_asset_inventory_exact,
        "all_assets_complete": bool(assets) and all(row.get("status") == "complete" for row in assets),
        "public_page_count": len(_public_page_ids(public_pages)),
        "public_page_ids": sorted(_public_page_ids(public_pages)),
        "homepage_word_count": _homepage_word_count(public_pages),
        "sample_report_types": sorted(_sample_report_types(sample_reports_manifest)),
        "data_source_coverage_ready": data_source_manifest.get("schema_version") == "phase6.data_source_coverage_assets.v1",
        "sample_field_contexts_visible": all(snippet in hosted_platform for snippet in REQUIRED_SAMPLE_FIELD_SNIPPETS),
        "demo_script_ready": all(snippet in demo_script for snippet in REQUIRED_DEMO_SCRIPT_SNIPPETS),
        "human_review_required": True,
        "human_review_reason": "Automated asset checks do not replace final copy, sample-report, and public-claims review.",
        "evidence": {
            "readiness_board": _display_path(board_path),
            "public_pages": _display_path(public_pages_path),
            "hosted_platform": _display_path(hosted_platform_path),
            "frontend_tests": _display_path(frontend_tests_path),
            "sample_reports": _display_path(sample_reports_dir),
            "data_source_coverage": _display_path(data_source_coverage_dir),
            "demo_script": _display_path(demo_script_path),
            "sample_reports_tests": _display_path(sample_reports_test_path),
            "data_source_coverage_tests": _display_path(data_source_coverage_test_path),
            "docs": _display_path(docs_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_demo_assets_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_public_pages(text: str, failures: list[dict[str, str]]) -> None:
    page_ids = _public_page_ids(text)
    _expect(EXPECTED_PUBLIC_PAGE_IDS <= page_ids, "public_pages", f"public pages missing ids {sorted(EXPECTED_PUBLIC_PAGE_IDS - page_ids)}", failures)
    _expect(page_ids <= EXPECTED_PUBLIC_PAGE_IDS, "public_pages", f"public pages include non-packet ids {sorted(page_ids - EXPECTED_PUBLIC_PAGE_IDS)}", failures)
    _expect(_homepage_word_count(text) <= 120, "public_pages", "homepage explanation must stay under 120 words", failures)
    lowered = text.lower()
    for concept in REQUIRED_HOMEPAGE_CONCEPTS:
        _expect(concept in lowered, "public_pages", f"homepage explanation missing {concept}", failures)
    for snippet in REQUIRED_PUBLIC_PAGE_SNIPPETS:
        _expect(snippet in text, "public_pages", f"public page copy missing {snippet}", failures)


def _validate_demo_script(text: str, failures: list[dict[str, str]]) -> None:
    step_count = len(re.findall(r"^\d+\.\s+", text, flags=re.MULTILINE))
    _expect(step_count >= 14, "demo_script", "demo script must keep at least 14 walkthrough steps", failures)
    for snippet in REQUIRED_DEMO_SCRIPT_SNIPPETS:
        _expect(snippet in text, "demo_script", f"demo script missing {snippet}", failures)


def _validate_sample_reports(manifest: dict[str, Any], sample_reports_dir: Path, failures: list[dict[str, str]]) -> None:
    _expect(manifest.get("schema_version") == "phase6.sample_reports.v1", "sample_reports", "unexpected sample reports schema", failures)
    data_policy = manifest.get("data_policy")
    _expect(isinstance(data_policy, dict) and data_policy.get("contains_real_user_private_data") is False, "sample_reports", "sample reports must declare no real user private data", failures)
    _expect(isinstance(data_policy, dict) and data_policy.get("contains_hidden_prompt_or_trace_scaffolding") is False, "sample_reports", "sample reports must declare hidden scaffolding excluded", failures)
    by_type = {str(row.get("report_type")): row for row in manifest.get("reports") or [] if isinstance(row, dict)}
    _expect(set(by_type) == EXPECTED_SAMPLE_REPORT_TYPES, "sample_reports", f"sample report types must be {sorted(EXPECTED_SAMPLE_REPORT_TYPES)}", failures)
    for report_type, expected_files in EXPECTED_SAMPLE_REPORT_FILES.items():
        report = by_type.get(report_type) or {}
        files = {str(file.get("filename")) for file in report.get("files") or [] if isinstance(file, dict)}
        _expect(expected_files <= files, "sample_reports", f"{report_type} missing files {sorted(expected_files - files)}", failures)
        _expect(files <= expected_files, "sample_reports", f"{report_type} manifest lists non-packet files {sorted(files - expected_files)}", failures)
        directory = sample_reports_dir / str(report.get("directory") or "")
        if directory.exists():
            disk_files = {path.name for path in directory.iterdir() if path.is_file()}
            _expect(disk_files <= expected_files, "sample_reports", f"{report_type} directory contains non-packet files {sorted(disk_files - expected_files)}", failures)
        for filename in expected_files:
            _expect((directory / filename).exists(), "sample_reports", f"{report_type} file missing on disk: {filename}", failures)


def _validate_data_source_coverage(manifest: dict[str, Any], data_source_dir: Path, failures: list[dict[str, str]]) -> None:
    _expect(manifest.get("schema_version") == "phase6.data_source_coverage_assets.v1", "data_source_coverage", "unexpected data-source coverage schema", failures)
    data_policy = manifest.get("data_policy")
    _expect(isinstance(data_policy, dict) and data_policy.get("contains_raw_source_text") is False, "data_source_coverage", "data-source coverage must exclude raw source text", failures)
    _expect(isinstance(data_policy, dict) and data_policy.get("contains_hidden_prompt_or_trace_scaffolding") is False, "data_source_coverage", "data-source coverage must exclude hidden scaffolding", failures)
    coverage = manifest.get("coverage_summary") if isinstance(manifest.get("coverage_summary"), dict) else {}
    _expect(int(coverage.get("source_count") or 0) >= 3, "data_source_coverage", "data-source coverage must keep public review sample sources", failures)
    _expect(set(_strings(manifest.get("source_card_fields"))) == EXPECTED_SOURCE_CARD_FIELDS, "data_source_coverage", "data-source coverage must expose every packet source-card field", failures)
    _expect(_strings(manifest.get("retrieval_not_training_source_ids")), "data_source_coverage", "data-source coverage must identify retrieval-only non-training sources", failures)
    lifecycle_policy = manifest.get("source_lifecycle_policy") if isinstance(manifest.get("source_lifecycle_policy"), dict) else {}
    _expect(
        bool(lifecycle_policy.get("source_addition_request")) and bool(lifecycle_policy.get("source_takedown_request")),
        "data_source_coverage",
        "data-source coverage must expose source addition and takedown request policy",
        failures,
    )
    _expect(
        lifecycle_policy.get("requires_audit_rerun") is True,
        "data_source_coverage",
        "source lifecycle policy must require audit rerun after source changes",
        failures,
    )
    readme_text = _read_text(data_source_dir / "README.md", "data_source_coverage", failures)
    _expect(
        "Request source additions or takedowns" in readme_text and "regenerates the source audit" in readme_text,
        "data_source_coverage",
        "data-source coverage README must explain source addition/takedown requests",
        failures,
    )
    csv_path = data_source_dir / "data_source_audit.csv"
    rows = _load_csv(csv_path, "data_source_coverage", failures)
    if rows:
        missing_fields = EXPECTED_SOURCE_CARD_FIELDS - set(rows[0])
        _expect(not missing_fields, "data_source_coverage", f"data-source audit CSV missing source-card fields: {sorted(missing_fields)}", failures)
        _expect(any("retrieval_only_not_training" in str(row.get("known_limitations") or "") for row in rows), "data_source_coverage", "data-source audit CSV must mark retrieval-only/non-training sources", failures)
    for filename in ("README.md", "data_source_audit.csv", "data_source_audit.pdf", "phase6_report_manifest.json"):
        _expect((data_source_dir / filename).exists(), "data_source_coverage", f"data-source coverage file missing: {filename}", failures)


def _public_page_ids(text: str) -> set[str]:
    return set(re.findall(r"id:\s+'([^']+)'", text))


def _homepage_word_count(text: str) -> int:
    match = re.search(r"phase6HomepageExplanation\s*=\s*\n?\s*'([^']+)'", text)
    if not match:
        return 10_000
    return len(re.findall(r"\b[\w/-]+\b", match.group(1)))


def _sample_report_types(manifest: dict[str, Any]) -> set[str]:
    return {str(row.get("report_type")) for row in manifest.get("reports") or [] if isinstance(row, dict)}


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dict_mismatches(expected: dict[str, str], observed: dict[str, str]) -> dict[str, dict[str, str]]:
    mismatches: dict[str, dict[str, str]] = {}
    for key, expected_value in expected.items():
        observed_value = observed.get(key, "")
        if observed_value != expected_value:
            mismatches[key] = {"expected": expected_value, "observed": observed_value}
    return mismatches


def _load_csv(path: Path, section: str, failures: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
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
