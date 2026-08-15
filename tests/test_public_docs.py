from __future__ import annotations

import json
from pathlib import Path

import check_public_docs


ROOT = Path(__file__).resolve().parents[1]


def test_public_documentation_contract_passes() -> None:
    report = check_public_docs.run()
    assert report["status"] == "pass", report["errors"]
    assert report["markdown_file_count"] >= 10


def test_optional_capability_manifest_rejects_unknown_documented_id(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("<!-- capability:known -->\n<!-- capability:missing -->\n", encoding="utf-8")
    manifest = tmp_path / "capabilities.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.capability_registry.v1",
                "capability_count": 1,
                "capabilities": [
                    {
                        "capability_id": "known",
                        "docs_path": "docs/public/capabilities.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors, source = check_public_docs.audit_runtime_capabilities([page], manifest)
    assert source == str(manifest)
    assert errors == ["capability_registry:unknown_doc_capability:missing"]


def test_link_audit_rejects_missing_local_target(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("[missing](not-there.md)\n", encoding="utf-8")
    errors = check_public_docs.audit_links([page])
    assert errors == [f"broken_link:{page}:not-there.md"]


def test_script_reference_audit_rejects_missing_entrypoint(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "Run `scripts/definitely_missing_release_tool.py` from the repository root.\n",
        encoding="utf-8",
    )

    errors = check_public_docs.audit_script_references([page])

    assert errors == [
        f"missing_script_reference:{page}:scripts/definitely_missing_release_tool.py"
    ]


def test_script_reference_audit_accepts_nested_repository_entrypoint(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "Run `docs/public/development-benchmark-rc3-20260815/scripts/"
        "analyze_rc3_checkpoint.py`.\n",
        encoding="utf-8",
    )

    assert check_public_docs.audit_script_references([page]) == []


def test_repository_link_audit_rejects_escape_and_forbidden_target(tmp_path: Path) -> None:
    page = ROOT / f".tmp_public_docs_link_audit_{tmp_path.name}.md"
    page.write_text(
        "[escape](../../outside.md)\n[private](outputs/private.sqlite3)\n",
        encoding="utf-8",
    )
    try:
        link_errors = check_public_docs.audit_links([page])
        scope_errors = check_public_docs.audit_scope(
            [page], ROOT / "configs/public_repository_manifest.json"
        )
    finally:
        page.unlink()

    assert link_errors == [
        f"outside_repository_link:{page.name}:../../outside.md",
        f"broken_link:{page.name}:outputs/private.sqlite3",
    ]
    assert f"forbidden_link_target:{page.name}:outputs/private.sqlite3" in scope_errors


def test_rendered_site_audit_rejects_private_runtime_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "outputs/private.sqlite3"
    artifact.parent.mkdir()
    artifact.write_bytes(b"not actually sqlite")
    errors, file_count = check_public_docs.audit_rendered_site(tmp_path)
    assert file_count == 1
    assert errors == [
        "rendered_site:forbidden_path:outputs/private.sqlite3",
        "rendered_site:forbidden_suffix:outputs/private.sqlite3",
    ]


def test_rendered_site_audit_rejects_rc3_reproducibility_sources(tmp_path: Path) -> None:
    package = tmp_path / "development-benchmark-rc3-20260815"
    source_data = package / "source_data/summary.csv"
    analysis_script = package / "scripts/analyze_rc3_checkpoint.py"
    latex_source = package / "main.tex"
    figure_pdf = package / "figures/diagnostic.pdf"
    figure_manifest = package / "figures/manifest.json"
    evidence_manifest = package / "paper_evidence_manifest.yaml"
    published_paper = package / "paper.pdf"
    published_svg = package / "figures/diagnostic.svg"
    for path in (
        source_data,
        analysis_script,
        latex_source,
        figure_pdf,
        figure_manifest,
        evidence_manifest,
        published_paper,
        published_svg,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")

    errors, file_count = check_public_docs.audit_rendered_site(tmp_path)

    assert file_count == 8
    assert errors == [
        "rendered_site:forbidden_figure_pdf:development-benchmark-rc3-20260815/figures/diagnostic.pdf",
        "rendered_site:forbidden_name:development-benchmark-rc3-20260815/figures/manifest.json",
        "rendered_site:forbidden_name:development-benchmark-rc3-20260815/main.tex",
        "rendered_site:forbidden_name:development-benchmark-rc3-20260815/paper_evidence_manifest.yaml",
        "rendered_site:forbidden_path:development-benchmark-rc3-20260815/scripts/analyze_rc3_checkpoint.py",
        "rendered_site:forbidden_path:development-benchmark-rc3-20260815/source_data/summary.csv",
    ]


def test_pages_workflow_audit_rejects_floating_action(tmp_path: Path) -> None:
    source = ROOT / ".github/workflows/docs.yml"
    workflow = tmp_path / "docs.yml"
    workflow.write_text(
        source.read_text(encoding="utf-8").replace(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            "actions/checkout@v6",
        ),
        encoding="utf-8",
    )

    errors = check_public_docs.audit_pages_workflow(workflow)

    assert "pages_workflow:action_not_commit_pinned:v6" in errors
