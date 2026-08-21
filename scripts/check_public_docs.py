#!/usr/bin/env python3
"""Deterministically audit public documentation links and publication scope."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = ROOT / "docs/public"
DEFAULT_MANIFEST = ROOT / "configs/public_repository_manifest.json"
DEFAULT_MKDOCS = ROOT / "mkdocs.yml"
DEFAULT_WORKFLOW = ROOT / ".github/workflows/docs.yml"
DEFAULT_CAPABILITY_MANIFEST = ROOT / "configs/capability_registry.json"
GENERATED_CAPABILITY_CATALOG = DOCS_ROOT / "capability-catalog.md"
GENERATED_GRAPH_CATALOG = DOCS_ROOT / "graph-catalog.md"
GENERATED_CAPABILITY_BEGIN = "<!-- BEGIN GENERATED CAPABILITY REGISTRY -->"
GENERATED_CAPABILITY_END = "<!-- END GENERATED CAPABILITY REGISTRY -->"
CAPABILITY_REGISTRY_SCHEMA = "open_agronomy_agent.capability_registry.v1"
ACTIVE_RAG_CONFIG = ROOT / "configs/rag.yaml"
PUBLIC_SUBSYSTEM_READMES = (
    ROOT / "README.md",
    ROOT / "container/README.md",
    ROOT / "configs/README.md",
    ROOT / "data/README.md",
    ROOT / "data/manifests/README.md",
    ROOT / "frontend/README.md",
    ROOT / "scripts/README.md",
    ROOT / "src/agronomy_agent/README.md",
    ROOT / "src/agronomy_agent/agno_runtime/README.md",
    ROOT / "src/agronomy_agent/server/README.md",
    ROOT / "src/agronomy_agent/tools/README.md",
    ROOT / "tests/README.md",
)
PUBLIC_REVIEW = ROOT / "docs/reviews/open-agronomy-benchmark-system-review-20260813.md"
RC2_PUBLIC_REVIEW = ROOT / "docs/reviews/open-agronomy-benchmark-rc2-readiness-record-20260814.md"
PUBLIC_BENCHMARK_PACKAGES = (
    "final-benchmark-20260812",
    "development-benchmark-rc3-20260815",
)

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\((?P<target>[^)]+)\)")
REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(?P<target>\S+)", re.MULTILINE)
HTML_LINK_RE = re.compile(r"\b(?:href|src)=[\"'](?P<target>[^\"']+)[\"']", re.IGNORECASE)
HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+?)\s*$", re.MULTILINE)
CAPABILITY_DECL_RE = re.compile(r"<!--\s*capability:(?P<capability>[a-z0-9_.-]+)\s*-->")
SCRIPT_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:\./)?(?P<path>(?:[A-Za-z0-9_.-]+/)*scripts/[A-Za-z0-9_.-]+\.(?:py|sh))(?![A-Za-z0-9_.-])"
)

PUBLIC_FORBIDDEN_PREFIXES = (
    ".git/",
    ".hf_cache/",
    "adapters/",
    "models/",
    "outputs/",
    "plans/",
    "data/derived/private_knowledge/",
)
PUBLIC_FORBIDDEN_SUFFIXES = (
    ".sqlite",
    ".sqlite3",
    ".db",
    ".safetensors",
    ".gguf",
    ".pt",
    ".pth",
    ".npz",
)
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "openai_token": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    "hugging_face_token": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
}


def _markdown_files() -> list[Path]:
    return sorted(path for path in DOCS_ROOT.rglob("*.md") if path.is_file())


def _publication_markdown_files(docs_files: Iterable[Path]) -> list[Path]:
    return sorted(
        {
            *docs_files,
            *PUBLIC_SUBSYSTEM_READMES,
            PUBLIC_REVIEW,
            RC2_PUBLIC_REVIEW,
        }
    )


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _slug(text: str) -> str:
    value = re.sub(r"<[^>]+>", "", text)
    value = re.sub(r"[`*_~]", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value)
    return re.sub(r"[-\s]+", "-", value).strip("-")


def _anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for match in HEADING_RE.finditer(text):
        base = _slug(match.group("text"))
        if not base:
            continue
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}_{count}")
        anchors.add(base if count == 0 else f"{base}-{count}")
    anchors.update(re.findall(r"\{#([A-Za-z0-9_.:-]+)\}", text))
    anchors.update(re.findall(r"\bid=[\"']([A-Za-z0-9_.:-]+)[\"']", text))
    return anchors


def _link_targets(text: str) -> Iterable[str]:
    for pattern in (LINK_RE, REFERENCE_LINK_RE, HTML_LINK_RE):
        for match in pattern.finditer(text):
            target = match.group("target").strip().strip("<>")
            if " " in target and not target.startswith(("http://", "https://")):
                target = target.split()[0]
            yield target


def audit_links(files: Iterable[Path]) -> list[str]:
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in files:
        for raw_target in _link_targets(source.read_text(encoding="utf-8")):
            if not raw_target or raw_target.startswith(("mailto:", "tel:", "data:", "javascript:")):
                continue
            parsed = urlsplit(raw_target)
            if parsed.scheme in {"http", "https"} or raw_target.startswith("//"):
                continue
            raw_path = unquote(parsed.path)
            if source.resolve().is_relative_to(ROOT.resolve()) and raw_path:
                if Path(raw_path).is_absolute():
                    errors.append(f"absolute_local_link:{_display(source)}:{raw_target}")
                    continue
                repository_target = (source.parent / raw_path).resolve()
                if not repository_target.is_relative_to(ROOT.resolve()):
                    errors.append(f"outside_repository_link:{_display(source)}:{raw_target}")
                    continue
            target = source if not raw_path else (source.parent / raw_path).resolve()
            if raw_path.endswith("/"):
                target = target / "index.md"
            if not target.exists():
                errors.append(f"broken_link:{_display(source)}:{raw_target}")
                continue
            if parsed.fragment and target.suffix.lower() == ".md":
                anchors = anchor_cache.setdefault(target, _anchors(target))
                fragment = unquote(parsed.fragment)
                if fragment not in anchors:
                    errors.append(
                        f"broken_anchor:{_display(source)}:{raw_target}:available={','.join(sorted(anchors)[:8])}"
                    )
    return errors


def audit_script_references(files: Iterable[Path]) -> list[str]:
    """Reject documentation that presents a missing repository script as usable."""

    errors: list[str] = []
    for source in files:
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in SCRIPT_REFERENCE_RE.finditer(text):
            relative = match.group("path")
            if not any(
                candidate.is_file()
                for candidate in (ROOT / relative, source.parent / relative)
            ):
                errors.append(f"missing_script_reference:{_display(source)}:{relative}")
    return errors


def audit_scope(files: Iterable[Path], manifest_path: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "open_agronomy_agent.public_repository_manifest.v1":
        errors.append("manifest:unsupported_schema")
        return errors
    manifest_paths = {str(value) for value in manifest.get("paths") or []}
    manifest_trees = {str(value).rstrip("/") for value in manifest.get("trees") or []}
    required_public_paths = {
        ".github/workflows/docs.yml",
        "README.md",
        "configs/benchmark_capability_conformance_v1.json",
        "configs/benchmark_egress_authorization.template.json",
        "configs/benchmark_judge_calibration.template.json",
        "configs/final_benchmark_round_rc2.json",
        "configs/final_benchmark_round_rc3.json",
        "configs/open_agronomy_benchmark_v2.json",
        "configs/open_agronomy_benchmark_v2_harness_contract.json",
        "configs/open_agronomy_benchmark_v2_interface.json",
        "configs/open_agronomy_benchmark_v2_preregistration.json",
        "configs/open_agronomy_benchmark_v3_holdout_commitment.template.json",
        "configs/open_agronomy_benchmark_v3_protocol.json",
        "configs/open_agronomy_canadian_performance_v1_runtime_v2.json",
        "configs/public_repository_manifest.json",
        "configs/model.yaml",
        "configs/rag.yaml",
        "configs/runtime_profiles.json",
        "configs/schemas/benchmark_judge_calibration_v1.schema.json",
        "configs/schemas/benchmark_v2_case.schema.json",
        "configs/schemas/benchmark_v3_holdout_commitment_v1.schema.json",
        "data/README.md",
        "data/eval/open_agronomy_benchmark_v2_cases.jsonl",
        "data/eval/open_agronomy_benchmark_v2_manifest.json",
        "data/eval/open_agronomy_canadian_performance_v1_runtime_v2_manifest.json",
        "data/manifests/README.md",
        "data/manifests/curated_canada_offline_master_v1.json",
        "data/manifests/runtime_corpus_policy.json",
        "docs/reviews/open-agronomy-benchmark-system-review-20260813.md",
        "docs/reviews/open-agronomy-benchmark-rc2-readiness-record-20260814.md",
        "docs/public/development-benchmark-rc3-20260815/README.md",
        "docs/public/development-benchmark-rc3-20260815/paper.pdf",
        "docs/public/development-benchmark-rc3-20260815/scripts/analyze_rc3_checkpoint.py",
        "docs/public/development-benchmark-rc3-20260815/source_data/public_safe_response_measurements.csv",
        "mkdocs.yml",
        "requirements-benchmark-analysis.txt",
        "requirements-docs.txt",
        "scripts/README.md",
        "scripts/audit_open_agronomy_benchmark_v2.py",
        "scripts/audit_open_agronomy_benchmark_v3_readiness.py",
        "scripts/check_public_docs.py",
        "scripts/run_benchmark_capability_conformance.py",
        "scripts/run_observed_system_rehearsal.py",
        "tests/README.md",
        "tests/test_rc3_checkpoint_analysis.py",
    }
    for required in sorted(required_public_paths):
        if required not in manifest_paths and not any(
            required == tree or required.startswith(f"{tree}/") for tree in manifest_trees
        ):
            errors.append(f"manifest:missing_public_path:{required}")
    if "docs/public" not in manifest_trees:
        errors.append("manifest:docs_public_tree_missing")
    forbidden_manifest_prefixes = {str(value) for value in manifest.get("forbidden_release_prefixes") or []}
    if "outputs/" not in forbidden_manifest_prefixes:
        errors.append("manifest:outputs_not_forbidden")
    if "data/derived/private_knowledge/" not in forbidden_manifest_prefixes:
        errors.append("manifest:private_knowledge_not_forbidden")

    for path in files:
        relative = _display(path)
        for prefix in PUBLIC_FORBIDDEN_PREFIXES:
            if relative.startswith(prefix):
                errors.append(f"forbidden_public_path:{relative}")
        if relative.lower().endswith(PUBLIC_FORBIDDEN_SUFFIXES):
            errors.append(f"forbidden_public_suffix:{relative}")
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"secret_signature:{name}:{relative}")
        for raw_target in _link_targets(text):
            parsed = urlsplit(raw_target)
            if parsed.scheme or not parsed.path:
                continue
            raw_path = unquote(parsed.path)
            normalized = str(PurePosixPath(raw_path))
            if not Path(raw_path).is_absolute():
                resolved = (path.parent / raw_path).resolve()
                if resolved.is_relative_to(ROOT.resolve()):
                    normalized = resolved.relative_to(ROOT.resolve()).as_posix()
            if any(normalized.startswith(prefix) for prefix in PUBLIC_FORBIDDEN_PREFIXES):
                errors.append(f"forbidden_link_target:{relative}:{raw_target}")
    return errors


def audit_rendered_site(site_dir: Path) -> tuple[list[str], int]:
    if not site_dir.is_dir():
        return [f"rendered_site:missing:{_display(site_dir)}"], 0
    files = sorted(path for path in site_dir.rglob("*") if path.is_file())
    errors: list[str] = []
    forbidden_rendered_prefixes = (
        "outputs/",
        "models/",
        "adapters/",
        "private_knowledge/",
        *(f"{package}/source_data/" for package in PUBLIC_BENCHMARK_PACKAGES),
        *(f"{package}/scripts/" for package in PUBLIC_BENCHMARK_PACKAGES),
    )
    forbidden_rendered_names = {
        "open_agronomy_agent_conference_20260812.pptx",
        "main.tex",
        "references.bib",
    }
    for path in files:
        relative = path.relative_to(site_dir).as_posix()
        if any(relative.startswith(prefix) for prefix in forbidden_rendered_prefixes):
            errors.append(f"rendered_site:forbidden_path:{relative}")
        if path.name in forbidden_rendered_names:
            errors.append(f"rendered_site:forbidden_name:{relative}")
        if path.suffix == ".tex" and path.name not in forbidden_rendered_names:
            errors.append(f"rendered_site:forbidden_suffix:{relative}")
        if (
            relative.startswith("development-benchmark-rc3-20260815/figures/")
            and path.suffix.lower() == ".pdf"
        ):
            errors.append(f"rendered_site:forbidden_figure_pdf:{relative}")
        if relative in {
            "development-benchmark-rc3-20260815/paper_evidence_manifest.yaml",
            "development-benchmark-rc3-20260815/figures/manifest.json",
        }:
            errors.append(f"rendered_site:forbidden_name:{relative}")
        if relative.lower().endswith(PUBLIC_FORBIDDEN_SUFFIXES):
            errors.append(f"rendered_site:forbidden_suffix:{relative}")
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"rendered_site:secret_signature:{name}:{relative}")
    return errors, len(files)


def _load_runtime_capability_contract() -> tuple[dict[str, Any], str]:
    src_path = str(ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from agronomy_agent.capability_registry import capability_catalog, render_capability_markdown

    return capability_catalog("docs"), render_capability_markdown()


def audit_runtime_capabilities(
    files: Iterable[Path],
    capability_manifest: Path | None,
) -> tuple[list[str], str]:
    errors: list[str] = []
    generated_markdown: str | None = None
    if capability_manifest is not None:
        if not capability_manifest.is_file():
            return [f"capability_manifest:missing:{_display(capability_manifest)}"], _display(capability_manifest)
        payload = json.loads(capability_manifest.read_text(encoding="utf-8"))
        source = _display(capability_manifest)
    else:
        try:
            payload, generated_markdown = _load_runtime_capability_contract()
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as exc:
            return [f"capability_registry:load_failed:{type(exc).__name__}:{exc}"], "runtime"
        source = "src/agronomy_agent/capability_registry.py"

    if not isinstance(payload, dict) or payload.get("schema_version") != CAPABILITY_REGISTRY_SCHEMA:
        errors.append("capability_registry:unsupported_schema")
        return errors, source
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("capability_registry:no_capabilities")
        return errors, source
    if payload.get("capability_count") != len(capabilities):
        errors.append("capability_registry:count_mismatch")

    ids: list[str] = []
    for record in capabilities:
        if not isinstance(record, dict) or not record.get("capability_id"):
            errors.append("capability_registry:record_missing_id")
            continue
        capability_id = str(record["capability_id"])
        ids.append(capability_id)
        docs_path = str(record.get("docs_path") or "").strip()
        if not docs_path:
            errors.append(f"capability_registry:missing_docs_path:{capability_id}")
        elif not (ROOT / docs_path).is_file():
            errors.append(f"capability_registry:broken_docs_path:{capability_id}:{docs_path}")
    duplicates = sorted({capability_id for capability_id in ids if ids.count(capability_id) > 1})
    errors.extend(f"capability_registry:duplicate_id:{capability_id}" for capability_id in duplicates)

    declarations: set[str] = set()
    for path in files:
        declarations.update(CAPABILITY_DECL_RE.findall(path.read_text(encoding="utf-8")))
    registry_ids = set(ids)
    errors.extend(
        f"capability_registry:unknown_doc_capability:{capability_id}"
        for capability_id in sorted(declarations - registry_ids)
    )

    if generated_markdown is not None:
        if not GENERATED_CAPABILITY_CATALOG.is_file():
            errors.append("capability_registry:generated_catalog_missing")
        else:
            text = GENERATED_CAPABILITY_CATALOG.read_text(encoding="utf-8")
            if GENERATED_CAPABILITY_BEGIN not in text or GENERATED_CAPABILITY_END not in text:
                errors.append("capability_registry:generated_catalog_markers_missing")
            else:
                actual = text.split(GENERATED_CAPABILITY_BEGIN, 1)[1].split(GENERATED_CAPABILITY_END, 1)[0].strip()
                if actual != generated_markdown.strip():
                    errors.append("capability_registry:generated_catalog_drift")
    return errors, source


def _runtime_graph_catalog() -> tuple[tuple[dict[str, Any], ...], str]:
    src_path = str(ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from agronomy_agent.agno_runtime.knowledge_graph import KnowledgeGraph

    config = yaml.safe_load(ACTIVE_RAG_CONFIG.read_text(encoding="utf-8")) or {}
    retrieval = config.get("retrieval") or {}
    paths = [ROOT / str(value) for value in retrieval.get("graph_paths") or []]
    graph = KnowledgeGraph.from_paths(
        paths,
        require_manifests=bool(retrieval.get("require_graph_manifests", False)),
    )
    rows = graph.catalog()
    lines = [
        "| Graph | Version | Namespaces | Authority | Nodes | Edges | Source | License | SHA-256 |",
        "|---|---|---|---|---:|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['graph_id']}` | `{row['version']}` | {', '.join(row['namespaces'])} | "
            f"{row['authority_role']} | {row['node_count']} | {row['edge_count']} | {row['source']} | "
            f"{row['license']} | `{row['sha256']}` |"
        )
    return rows, "\n".join(lines) + "\n"


def audit_runtime_graph_catalog() -> list[str]:
    try:
        rows, expected = _runtime_graph_catalog()
    except (FileNotFoundError, ImportError, AttributeError, RuntimeError, TypeError, ValueError) as exc:
        return [f"graph_catalog:load_failed:{type(exc).__name__}:{exc}"]
    if not rows:
        return ["graph_catalog:no_active_graphs"]
    if not GENERATED_GRAPH_CATALOG.is_file():
        return ["graph_catalog:generated_catalog_missing"]
    text = GENERATED_GRAPH_CATALOG.read_text(encoding="utf-8")
    if GENERATED_CAPABILITY_BEGIN not in text or GENERATED_CAPABILITY_END not in text:
        return ["graph_catalog:generated_catalog_markers_missing"]
    actual = text.split(GENERATED_CAPABILITY_BEGIN, 1)[1].split(GENERATED_CAPABILITY_END, 1)[0].strip()
    return [] if actual == expected.strip() else ["graph_catalog:generated_catalog_drift"]


def audit_mkdocs_config(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    errors: list[str] = []
    if not text:
        return [f"mkdocs:missing:{_display(path)}"]
    if not re.search(r"(?m)^docs_dir:\s*docs/public\s*$", text):
        errors.append("mkdocs:docs_dir_must_be_docs_public")
    if not re.search(r"(?m)^strict:\s*true\s*$", text):
        errors.append("mkdocs:strict_must_be_true")
    if "site_dir: build/docs-site" not in text:
        errors.append("mkdocs:site_dir_must_be_build_docs_site")
    return errors


def audit_pages_workflow(path: Path) -> list[str]:
    if not path.is_file():
        return [f"pages_workflow:missing:{_display(path)}"]
    text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"pages_workflow:invalid_yaml:{type(exc).__name__}"]
    errors: list[str] = []
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, dict) or set(jobs) != {"build", "deploy"}:
        errors.append("pages_workflow:expected_build_and_deploy_jobs")
        return errors
    if payload.get("permissions") != {"contents": "read"}:
        errors.append("pages_workflow:global_permissions_not_read_only")
    build = jobs.get("build") or {}
    deploy = jobs.get("deploy") or {}
    if build.get("permissions") is not None:
        errors.append("pages_workflow:build_must_inherit_read_only_permissions")
    if deploy.get("permissions") != {"pages": "write", "id-token": "write"}:
        errors.append("pages_workflow:deploy_permissions_not_least_privilege")
    expected_gate = "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    if deploy.get("if") != expected_gate:
        errors.append("pages_workflow:deploy_not_default_branch_push_only")
    if (deploy.get("environment") or {}).get("name") != "github-pages":
        errors.append("pages_workflow:missing_github_pages_environment")
    build_steps = build.get("steps") or []
    upload_steps = [step for step in build_steps if "actions/upload-pages-artifact@" in str(step.get("uses") or "")]
    if len(upload_steps) != 1 or upload_steps[0].get("if") != expected_gate:
        errors.append("pages_workflow:artifact_upload_not_default_branch_push_only")
    action_refs = re.findall(r"\buses:\s*[^@\s]+@([^\s#]+)", text)
    for ref in action_refs:
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            errors.append(f"pages_workflow:action_not_commit_pinned:{ref}")
    if not re.search(r"(?m)^\s{2}pull_request:\s*$", text):
        errors.append("pages_workflow:pull_request_build_missing")
    if not re.search(r"(?ms)^\s{2}push:\s*\n\s{4}branches:\s*\n\s{6}- main\s*$", text):
        errors.append("pages_workflow:main_push_build_missing")
    return errors


def run(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    mkdocs_path: Path = DEFAULT_MKDOCS,
    workflow_path: Path = DEFAULT_WORKFLOW,
    capability_manifest: Path | None = None,
    site_dir: Path | None = None,
) -> dict[str, Any]:
    files = _markdown_files()
    publication_files = _publication_markdown_files(files)
    capability_errors, capability_source = audit_runtime_capabilities(files, capability_manifest)
    rendered_errors, rendered_file_count = audit_rendered_site(site_dir) if site_dir else ([], None)
    errors = [
        *audit_links(publication_files),
        *audit_script_references(publication_files),
        *audit_scope(publication_files, manifest_path),
        *audit_mkdocs_config(mkdocs_path),
        *audit_pages_workflow(workflow_path),
        *capability_errors,
        *audit_runtime_graph_catalog(),
        *rendered_errors,
    ]
    return {
        "schema_version": "open_agronomy_agent.public_docs_audit.v1",
        "status": "pass" if not errors else "fail",
        "markdown_file_count": len(files),
        "rendered_site_file_count": rendered_file_count,
        "capability_source": capability_source,
        "errors": sorted(set(errors)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mkdocs-config", type=Path, default=DEFAULT_MKDOCS)
    parser.add_argument(
        "--site-dir",
        type=Path,
        help="Optional rendered site directory to audit after `mkdocs build --strict`.",
    )
    parser.add_argument(
        "--capability-manifest",
        type=Path,
        default=DEFAULT_CAPABILITY_MANIFEST if DEFAULT_CAPABILITY_MANIFEST.exists() else None,
        help="Optional exported canonical capability registry JSON.",
    )
    args = parser.parse_args(argv)
    report = run(
        manifest_path=args.manifest.resolve(),
        mkdocs_path=args.mkdocs_config.resolve(),
        capability_manifest=args.capability_manifest.resolve() if args.capability_manifest else None,
        site_dir=args.site_dir.resolve() if args.site_dir else None,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
