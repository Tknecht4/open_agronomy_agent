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
