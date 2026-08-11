#!/usr/bin/env python3
"""Build a self-contained source-and-knowledge bundle for local demo work."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

import yaml

from agronomy_agent.corpus_governance import (
    corpus_policy_for_path,
    load_corpus_policy,
    partition_runtime_corpus_paths,
)
from agronomy_agent.paths import repo_path


SCHEMA_VERSION = "open_agronomy_agent.portable_runtime_bundle.v4"
DEFAULT_RAG_CONFIG = "configs/rag_governed_runtime_v1.yaml"
DEFAULT_MODEL_CONFIG = "configs/model_gemma4_e2b_interface_v2.yaml"
DEFAULT_OUTPUT_DIR = "outputs/portable_agent"
DEFAULT_BUNDLE_NAME = "open_agronomy_agent_portable_knowledge_latest.tar.gz"
ARCHIVE_ROOT = "open_agronomy_agent"
TREE_ROOTS = (
    "src",
    "scripts",
    "tests",
    "configs",
    "container",
    "frontend/src",
    "frontend/public",
    "data/manifests",
)
CONFERENCE_EVAL_FILES = (
    "data/eval/open_agronomy_canadian_performance_v1.jsonl",
    "data/eval/open_agronomy_canadian_performance_v1_manifest.json",
    "data/eval/open_agronomy_canadian_external_agroqa_separation_manifest.json",
    "data/eval/open_agronomy_canadian_public_separation_manifest.json",
    "data/eval/canadian_semantic_reserve_v2.jsonl",
    "data/eval/canadian_semantic_reserve_v2_manifest.json",
    "data/eval/canadian_conference_transfer_gate_v2.jsonl",
    "data/eval/canadian_conference_transfer_gate_v2_manifest.json",
    "data/eval/decision_card_pilot_prospective_v1.jsonl",
    "data/eval/canadian_crop_health_indices_answer_gate_v1.jsonl",
    "data/eval/canadian_v9_candidate_answer_gate.jsonl",
    "data/eval/canadian_v9_candidate_answer_gate_manifest.json",
    "data/eval/canadian_v10_candidate_answer_gate.jsonl",
    "data/eval/canadian_v10_candidate_answer_gate_manifest.json",
    "data/eval/canadian_v11_candidate_answer_gate.jsonl",
    "data/eval/canadian_v11_candidate_answer_gate_manifest.json",
    "data/eval/canadian_v12_candidate_answer_gate.jsonl",
    "data/eval/canadian_v12_candidate_answer_gate_manifest.json",
    "data/eval/canadian_ab_nutrient_planning_retrieval_probe_v1.jsonl",
    "data/eval/canadian_alberta_retrieval_probe_v1.jsonl",
    "data/eval/canadian_nasdi_retrieval_probe_v1.jsonl",
    "data/eval/canadian_slc_retrieval_probe_v1.jsonl",
    "data/eval/canadian_agronomic_calculations_v1.jsonl",
    "data/eval/open_agronomy_external_agroqa_v1.jsonl",
    "data/eval/open_agronomy_external_agroqa_v1_manifest.json",
    "data/eval/public/agroqa_external_256_v1_source.jsonl",
    "data/eval/public/agroqa_external_256_v1_audit.json",
    "data/eval/public/agroqa_dataset_91b5ae1c.csv",
    "data/eval/public/agroqa_dataset_LICENSE.txt",
    "data/eval/public/NOTICE.md",
    "data/eval/public/README.md",
    "data/eval/preconference_demo_scenarios_v1.jsonl",
)
BENCHMARK_EVIDENCE_SETS = {
    "internal_canadian": (
        "outputs/open_agronomy_canadian_performance_v1/full_system_benchmark.sqlite3",
        "outputs/open_agronomy_canadian_performance_v1/benchmark_report.json",
        "outputs/open_agronomy_canadian_performance_v1/benchmark_report.md",
        "outputs/open_agronomy_canadian_performance_v1/cost_ledger.sqlite3",
        "outputs/open_agronomy_canadian_performance_v1/cost_ledger_manifest.json",
        "outputs/open_agronomy_canadian_performance_v1/benchmark_invocation.json",
        "outputs/open_agronomy_canadian_performance_v1/benchmark_lock.json",
        "outputs/open_agronomy_canadian_performance_v1/invocations/gemma3_270m.json",
        "outputs/open_agronomy_canadian_performance_v1/invocations/gemma4_e2b.json",
        "outputs/open_agronomy_canadian_performance_v1/invocations/luna_high.json",
    ),
    "external_agroqa": (
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/full_system_benchmark.sqlite3",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/benchmark_report.json",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/benchmark_report.md",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/cost_ledger.sqlite3",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/cost_ledger_manifest.json",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/benchmark_invocation.json",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/benchmark_lock.json",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/invocations/gemma3_270m.json",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/invocations/gemma4_e2b.json",
        "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/invocations/luna_high.json",
    ),
}
ROOT_FILES = (
    "Containerfile",
    "Containerfile.overlay",
    ".dockerignore",
    ".gitignore",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-docs.txt",
    "requirements-phase4-ci.txt",
    "requirements-container.txt",
    "docker-compose.edge.yml",
    "docker-compose.phase4.local.yml",
    "docker-compose.phase6.launch.yml",
    "frontend/Dockerfile",
    "frontend/Dockerfile.launch",
    "frontend/index.html",
    "frontend/nginx.launch.conf",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "docs/setup_guide.md",
    "docs/generation_latency_optimization.md",
    "docs/agent_closeout_20260713.md",
    "docs/demo_distribution_guide.md",
    "docs/conference_demo_operator_quick_card_20260810.md",
    "docs/conference_demo_operator_runbook_20260810.md",
    "docs/open_agronomy_benchmark_v2.md",
    "docs/open_agronomy_performance_brief_20260810.md",
    "docs/open_agronomy_architecture_paper_20260810/main.tex",
    "docs/open_agronomy_architecture_paper_20260810/main.pdf",
    "docs/open_agronomy_architecture_paper_20260810/references.bib",
    "docs/open_agronomy_architecture_paper_20260810/paper_evidence_manifest.yaml",
    "docs/open_agronomy_architecture_paper_20260810/Makefile",
    "docs/open_agronomy_architecture_paper_20260810/figures/manifest.txt",
    "docs/open_agronomy_architecture_paper_20260810/source_data/manifest.txt",
    "docs/open_agronomy_architecture_paper_20260810/source_data/tab_release_evidence.csv",
    "docs/canadian_dss_offline_integration_20260809.md",
)
EXCLUDED_PARTS = {
    ".DS_Store",
    ".git",
    ".hf_cache",
    ".playwright-cli",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "outputs",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _line_count(path: Path) -> int | None:
    if path.suffix not in {".jsonl", ".json", ".yaml", ".yml", ".md", ".py", ".tsx", ".ts"}:
        return None
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


@dataclass(frozen=True)
class RuntimeKnowledgeSelection:
    included_paths: tuple[Path, ...]
    included_corpus_paths: tuple[Path, ...]
    graph_paths: tuple[Path, ...]
    excluded_corpora: tuple[dict[str, Any], ...]
    configured_corpus_count: int
    policy_path: Path | None


@dataclass(frozen=True)
class RuntimeGeospatialSelection:
    included_paths: tuple[Path, ...]
    layer_ids: tuple[str, ...]
    source_manifest_path: Path | None
    national_soil_context_gate: dict[str, Any]


def _manifest_path(repo_root: Path, value: Any) -> Path:
    relative = Path(str(value or ""))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe runtime path in manifest: {value!r}")
    path = (repo_root / relative).resolve()
    if not path.is_relative_to(repo_root.resolve()):
        raise ValueError(f"runtime path escapes repository: {value!r}")
    return path


def select_runtime_geospatial(
    repo_root: Path,
    manifest_path: Path | None = None,
) -> RuntimeGeospatialSelection:
    """Select verified redistributable local map indexes for the portable bundle."""

    source_manifest_path = manifest_path or repo_root / "data/manifests/canada_geospatial_sources.json"
    if not source_manifest_path.is_file():
        return RuntimeGeospatialSelection((), (), None, {})
    payload = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    paths: set[Path] = {source_manifest_path}
    layer_ids: list[str] = []
    for source in payload.get("sources", []):
        runtime = source.get("runtime") if isinstance(source, dict) else None
        if not isinstance(runtime, dict) or runtime.get("status") != "bundled":
            continue
        if not bool((source.get("license") or {}).get("permits_redistribution")):
            raise ValueError(f"bundled geospatial source is not redistributable: {source.get('id')}")
        derived_path = _manifest_path(repo_root, runtime.get("derived_path"))
        derived_manifest_path = _manifest_path(repo_root, runtime.get("derived_manifest_path"))
        lineage_path = _manifest_path(repo_root, runtime.get("lineage_path"))
        missing = [
            str(path.relative_to(repo_root))
            for path in (derived_path, derived_manifest_path, lineage_path)
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(
                f"bundled geospatial runtime is incomplete for {source.get('id')}: {', '.join(missing)}"
            )
        derived_manifest = json.loads(derived_manifest_path.read_text(encoding="utf-8"))
        if derived_manifest.get("output_path") != str(derived_path.relative_to(repo_root)):
            raise ValueError(f"geospatial output path mismatch: {source.get('id')}")
        if int(derived_manifest.get("output_bytes") or -1) != derived_path.stat().st_size:
            raise ValueError(f"geospatial output byte count mismatch: {source.get('id')}")
        if derived_manifest.get("output_sha256") != sha256(derived_path):
            raise ValueError(f"geospatial output SHA-256 mismatch: {source.get('id')}")
        if derived_manifest.get("lineage_sha256") != sha256(lineage_path):
            raise ValueError(f"geospatial lineage SHA-256 mismatch: {source.get('id')}")
        if (derived_manifest.get("license_snapshot") or {}).get("status") != "redistributable":
            raise ValueError(f"geospatial derived licence is not redistributable: {source.get('id')}")
        paths.update((derived_path, derived_manifest_path, lineage_path))
        layer_ids.append(str(runtime.get("layer_id") or source.get("id")))
    return RuntimeGeospatialSelection(
        included_paths=tuple(sorted(paths)),
        layer_ids=tuple(sorted(layer_ids)),
        source_manifest_path=source_manifest_path,
        national_soil_context_gate=dict(payload.get("national_soil_context_gate") or {}),
    )


def select_runtime_knowledge(repo_root: Path, rag_config: Path) -> RuntimeKnowledgeSelection:
    payload = yaml.safe_load(rag_config.read_text(encoding="utf-8")) or {}
    retrieval = payload.get("retrieval") or {}
    configured_corpora = [str(value) for value in retrieval.get("corpus_paths") or []]
    configured_graphs = [str(value) for value in retrieval.get("graph_paths") or []]
    policy_value = retrieval.get("corpus_policy_manifest")
    policy = load_corpus_policy(repo_root, policy_value)
    included_corpora, excluded = partition_runtime_corpus_paths(
        configured_corpora,
        policy,
    )
    corpus_paths = tuple(repo_root / str(value) for value in included_corpora)
    graph_paths = tuple(repo_root / value for value in configured_graphs)
    paths = [*corpus_paths, *graph_paths]
    missing = [str(path.relative_to(repo_root)) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"configured runtime knowledge is missing: {', '.join(missing)}")
    excluded_records: list[dict[str, Any]] = []
    for row in excluded:
        policy_row = corpus_policy_for_path(row.get("path") or "", policy) or {}
        excluded_records.append(
            {
                **row,
                "rights_status": policy_row.get("rights_status"),
                "expected_sha256": policy_row.get("sha256"),
                "included": False,
            }
        )
    for path in corpus_paths:
        relative = str(path.relative_to(repo_root))
        policy_row = corpus_policy_for_path(relative, policy)
        if policy_row and policy_row.get("sha256") != sha256(path):
            raise ValueError(f"runtime corpus failed policy SHA-256 validation: {relative}")
    policy_path = repo_root / str(policy_value) if policy_value else None
    if policy_path is not None and not policy_path.is_file():
        raise FileNotFoundError(f"runtime corpus policy is missing: {policy_path.relative_to(repo_root)}")
    return RuntimeKnowledgeSelection(
        included_paths=tuple(paths),
        included_corpus_paths=corpus_paths,
        graph_paths=graph_paths,
        excluded_corpora=tuple(excluded_records),
        configured_corpus_count=len(configured_corpora),
        policy_path=policy_path,
    )


def runtime_knowledge_paths(repo_root: Path, rag_config: Path) -> list[Path]:
    return list(select_runtime_knowledge(repo_root, rag_config).included_paths)


def _tree_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return (
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def collect_bundle_files(repo_root: Path, rag_config: Path) -> list[Path]:
    files: set[Path] = set()
    for value in TREE_ROOTS:
        files.update(_tree_files(repo_root / value))
    for value in ROOT_FILES:
        path = repo_root / value
        if path.is_file():
            files.add(path)
    for value in CONFERENCE_EVAL_FILES:
        path = repo_root / value
        if not path.is_file():
            raise FileNotFoundError(f"conference evaluation asset is missing: {value}")
        files.add(path)
    files.add(rag_config)
    selection = select_runtime_knowledge(repo_root, rag_config)
    files.update(selection.included_paths)
    files.update(select_runtime_geospatial(repo_root).included_paths)
    if selection.policy_path is not None:
        files.add(selection.policy_path)
    snapshot = repo_root / "data/snapshots/nass_quickstats_state_crop_stats.jsonl"
    snapshot_manifest = repo_root / "data/snapshots/nass_quickstats_state_crop_stats_manifest.json"
    if snapshot.is_file() and snapshot_manifest.is_file():
        files.update({snapshot, snapshot_manifest})
    statcan_snapshot = repo_root / "data/snapshots/statcan_field_crop_statistics.jsonl"
    statcan_manifest = repo_root / "data/snapshots/statcan_field_crop_statistics_manifest.json"
    if statcan_snapshot.is_file() and statcan_manifest.is_file():
        files.update({statcan_snapshot, statcan_manifest})
    return sorted(files, key=lambda path: str(path.relative_to(repo_root)))


def select_benchmark_evidence(
    repo_root: Path,
    *,
    required: bool,
) -> tuple[tuple[Path, ...], dict[str, Any]]:
    """Select only frozen result receipts needed by the offline benchmark page."""

    selected: list[Path] = []
    sets: dict[str, Any] = {}
    for set_id, relative_paths in BENCHMARK_EVIDENCE_SETS.items():
        paths = [repo_root / relative for relative in relative_paths]
        present = [path for path in paths if path.is_file()]
        missing = [str(path.relative_to(repo_root)) for path in paths if not path.is_file()]
        if present and missing:
            raise FileNotFoundError(
                f"benchmark evidence set {set_id} is partial: {', '.join(missing)}"
            )
        if required and missing:
            raise FileNotFoundError(
                f"required benchmark evidence set {set_id} is missing: {', '.join(missing)}"
            )
        included = not missing
        if included:
            selected.extend(paths)
        sets[set_id] = {
            "included": included,
            "file_count": len(paths) if included else 0,
            "bytes": sum(path.stat().st_size for path in paths) if included else 0,
            "paths": [str(path.relative_to(repo_root)) for path in paths] if included else [],
            "missing": missing,
        }
    return tuple(sorted(selected)), sets


def _entry(
    repo_root: Path,
    path: Path,
    *,
    knowledge_paths: set[Path],
    geospatial_paths: set[Path],
    benchmark_evidence_paths: set[Path],
) -> dict[str, Any]:
    relative = str(path.relative_to(repo_root))
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "line_count": _line_count(path),
        "role": (
            "runtime_knowledge"
            if path in knowledge_paths
            else "offline_geospatial_context"
            if path in geospatial_paths
            else "benchmark_evidence"
            if path in benchmark_evidence_paths
            else "runtime_source"
        ),
    }


def _validate_snapshot(repo_root: Path) -> dict[str, Any]:
    snapshot = repo_root / "data/snapshots/nass_quickstats_state_crop_stats.jsonl"
    manifest_path = repo_root / "data/snapshots/nass_quickstats_state_crop_stats_manifest.json"
    if not snapshot.is_file() or not manifest_path.is_file():
        return {"included": False, "valid": False, "reason": "snapshot_or_manifest_missing"}
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256(snapshot)
    return {
        "included": True,
        "valid": actual_sha == source_manifest.get("sha256"),
        "path": str(snapshot.relative_to(repo_root)),
        "manifest_path": str(manifest_path.relative_to(repo_root)),
        "sha256": actual_sha,
        "row_count": source_manifest.get("row_count"),
        "source_url": source_manifest.get("source_url"),
        "scope": source_manifest.get("scope"),
    }


def _validate_statcan_snapshot(repo_root: Path) -> dict[str, Any]:
    snapshot = repo_root / "data/snapshots/statcan_field_crop_statistics.jsonl"
    manifest_path = repo_root / "data/snapshots/statcan_field_crop_statistics_manifest.json"
    if not snapshot.is_file() or not manifest_path.is_file():
        return {"included": False, "valid": False, "reason": "snapshot_or_manifest_missing"}
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256(snapshot)
    snapshot_metadata = source_manifest.get("snapshot") or {}
    source_metadata = source_manifest.get("source") or {}
    return {
        "included": True,
        "valid": actual_sha == snapshot_metadata.get("sha256"),
        "path": str(snapshot.relative_to(repo_root)),
        "manifest_path": str(manifest_path.relative_to(repo_root)),
        "sha256": actual_sha,
        "row_count": snapshot_metadata.get("row_count"),
        "source_url": source_metadata.get("archive_url"),
        "source_release_date": source_metadata.get("release_date"),
        "scope": snapshot_metadata.get("scope"),
    }


def _write_archive(
    repo_root: Path,
    files: list[Path],
    bundle_path: Path,
    content_manifest: dict[str, Any],
) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = bundle_path.with_suffix(bundle_path.suffix + ".partial")
    with tarfile.open(temporary, "w:gz", format=tarfile.PAX_FORMAT, dereference=True) as archive:
        for path in files:
            relative = path.relative_to(repo_root)
            archive.add(path, arcname=str(Path(ARCHIVE_ROOT) / relative), recursive=False)
        manifest_bytes = (json.dumps(content_manifest, indent=2) + "\n").encode("utf-8")
        info = tarfile.TarInfo(str(Path(ARCHIVE_ROOT) / "PORTABLE_BUNDLE_MANIFEST.json"))
        info.size = len(manifest_bytes)
        info.mode = 0o644
        info.mtime = 0
        archive.addfile(info, BytesIO(manifest_bytes))
    temporary.replace(bundle_path)


def _model_contract(repo_root: Path, model_config: Path) -> dict[str, Any]:
    payload = yaml.safe_load(model_config.read_text(encoding="utf-8")) or {}
    model_id = str(payload.get("serving_model_id") or payload.get("model_id") or "").strip()
    revision = str(payload.get("model_revision") or "").strip()
    if not model_id or not revision:
        raise ValueError("portable model profile must pin serving_model_id and model_revision")
    relative = str(model_config.relative_to(repo_root))
    return {
        "included": False,
        "reason": "Model weights are a user-managed, machine-local download and are never embedded in the application or knowledge archive.",
        "config_path": relative,
        "config_sha256": sha256(model_config),
        "model_id": model_id,
        "revision": revision,
        "license": payload.get("license"),
        "download_command": f"python scripts/download_model.py --model-config {relative}",
        "offline_requirement": "Run the download command once while online, then verify the offline-readiness gate before entering the field.",
    }


def build_bundle(
    *,
    repo_root: Path,
    rag_config: Path,
    model_config: Path,
    output_dir: Path,
    bundle_name: str,
    dry_run: bool = False,
    require_benchmark_evidence: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    rag_config = rag_config.resolve()
    model_config = model_config.resolve()
    output_dir = output_dir.resolve()
    bundle_path = output_dir / bundle_name
    selection = select_runtime_knowledge(repo_root, rag_config)
    knowledge_paths = set(selection.included_paths)
    geospatial_selection = select_runtime_geospatial(repo_root)
    geospatial_paths = set(geospatial_selection.included_paths)
    benchmark_evidence_selection, benchmark_evidence_sets = select_benchmark_evidence(
        repo_root,
        required=require_benchmark_evidence,
    )
    benchmark_evidence_paths = set(benchmark_evidence_selection)
    files = collect_bundle_files(repo_root, rag_config)
    files = sorted(
        {*files, model_config, *benchmark_evidence_paths},
        key=lambda path: str(path.relative_to(repo_root)),
    )
    entries = [
        _entry(
            repo_root,
            path,
            knowledge_paths=knowledge_paths,
            geospatial_paths=geospatial_paths,
            benchmark_evidence_paths=benchmark_evidence_paths,
        )
        for path in files
    ]
    snapshot = _validate_snapshot(repo_root)
    statcan_snapshot = _validate_statcan_snapshot(repo_root)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "status": "dry_run" if dry_run else "pass",
        "archive_root": ARCHIVE_ROOT,
        "bundle_path": str(bundle_path.relative_to(repo_root)),
        "bundle_exists": False,
        "bundle_bytes": 0,
        "bundle_sha256": None,
        "file_count": len(entries),
        "uncompressed_bytes": sum(int(entry["bytes"]) for entry in entries),
        "runtime_knowledge_file_count": len(knowledge_paths),
        "runtime_knowledge_bytes": sum(path.stat().st_size for path in knowledge_paths),
        "offline_geospatial_layer_count": len(geospatial_selection.layer_ids),
        "offline_geospatial_layer_ids": list(geospatial_selection.layer_ids),
        "offline_geospatial_file_count": len(geospatial_paths),
        "offline_geospatial_bytes": sum(path.stat().st_size for path in geospatial_paths),
        "benchmark_evidence_required": require_benchmark_evidence,
        "benchmark_evidence_file_count": len(benchmark_evidence_paths),
        "benchmark_evidence_bytes": sum(
            path.stat().st_size for path in benchmark_evidence_paths
        ),
        "benchmark_evidence_sets": benchmark_evidence_sets,
        "national_soil_context_gate": geospatial_selection.national_soil_context_gate,
        "configured_corpus_count": selection.configured_corpus_count,
        "included_corpus_count": len(selection.included_corpus_paths),
        "included_graph_count": len(selection.graph_paths),
        "excluded_corpus_count": len(selection.excluded_corpora),
        "excluded_corpora": list(selection.excluded_corpora),
        "corpus_policy_manifest": (
            str(selection.policy_path.relative_to(repo_root))
            if selection.policy_path is not None
            else None
        ),
        "rag_config": str(rag_config.relative_to(repo_root)),
        "snapshot": snapshot,
        "statcan_snapshot": statcan_snapshot,
        "model": _model_contract(repo_root, model_config),
        "runtime_boundary": (
            "The archive is self-contained for application source, policy-approved RAG/KG knowledge, the frozen Canadian benchmark and external AgroQA diagnostic fixtures, governed derived offline geospatial indexes, and the "
            "offline USDA NASS and Statistics Canada snapshots. When requested, it also carries the frozen canonical internal and external benchmark databases and receipts used by the offline benchmark page. It excludes model weights, raw geospatial downloads, secrets, user data, mutable session/trace databases, caches, and non-canonical historical outputs. "
            "Historical plan archives, retired evaluation suites, and quarantined or rights-unresolved corpora are excluded; governed corpus exclusions remain named in lineage. "
            "The external conference release authority is published beside the archive rather than embedded, because it records the completed archive's SHA-256 and Git reference. "
            "Apple Metal inference must run on the macOS host; Linux Docker containers cannot expose MLX Metal acceleration."
        ),
        "entries": entries,
    }
    if not snapshot.get("valid"):
        raise ValueError(f"offline NASS snapshot failed validation: {snapshot.get('reason') or 'sha256 mismatch'}")
    if not statcan_snapshot.get("valid"):
        raise ValueError(
            f"offline Statistics Canada snapshot failed validation: "
            f"{statcan_snapshot.get('reason') or 'sha256 mismatch'}"
        )
    if not dry_run:
        _write_archive(repo_root, files, bundle_path, manifest)
        manifest.update(
            {
                "bundle_exists": True,
                "bundle_bytes": bundle_path.stat().st_size,
                "bundle_sha256": sha256(bundle_path),
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "portable_bundle_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag-config", default=DEFAULT_RAG_CONFIG)
    parser.add_argument("--model-config", default=DEFAULT_MODEL_CONFIG)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bundle-name", default=DEFAULT_BUNDLE_NAME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--require-benchmark-evidence",
        action="store_true",
        help="Fail unless both frozen conference result sets are complete and include them.",
    )
    args = parser.parse_args()
    manifest = build_bundle(
        repo_root=repo_path("."),
        rag_config=repo_path(args.rag_config),
        model_config=repo_path(args.model_config),
        output_dir=repo_path(args.output_dir),
        bundle_name=args.bundle_name,
        dry_run=args.dry_run,
        require_benchmark_evidence=args.require_benchmark_evidence,
    )
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "status",
                    "bundle_path",
                    "bundle_exists",
                    "bundle_bytes",
                    "bundle_sha256",
                    "file_count",
                    "uncompressed_bytes",
                    "runtime_knowledge_file_count",
                    "runtime_knowledge_bytes",
                    "offline_geospatial_layer_count",
                    "offline_geospatial_layer_ids",
                    "offline_geospatial_file_count",
                    "offline_geospatial_bytes",
                    "benchmark_evidence_required",
                    "benchmark_evidence_file_count",
                    "benchmark_evidence_bytes",
                    "benchmark_evidence_sets",
                    "national_soil_context_gate",
                    "snapshot",
                    "statcan_snapshot",
                    "model",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
