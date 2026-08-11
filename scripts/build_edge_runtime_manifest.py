#!/usr/bin/env python3
"""Build a deterministic inventory of assets shipped in the edge image."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from agronomy_agent.corpus_governance import (  # noqa: E402
    corpus_policy_for_path,
    load_corpus_policy,
    partition_runtime_corpus_paths,
)


SCHEMA_VERSION = "open_agronomy_agent.edge_runtime_manifest.v1"
RAG_CONFIG = "configs/rag_governed_runtime_v1.yaml"
MODEL_CONFIG = "configs/model_gemma4_e2b_interface_v2.yaml"
CONTROL_PATHS = (
    "Containerfile",
    "Containerfile.overlay",
    ".dockerignore",
    "requirements-container.txt",
    "pyproject.toml",
    "docker-compose.edge.yml",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "container/.env.example",
    "container/runtime-defaults.env",
    "container/README.md",
    "container/runtime-common.sh",
    "container/build-image.sh",
    "container/build-overlay-image.sh",
    "container/entrypoint.sh",
    "container/model-host.sh",
    "container/apple.sh",
    "container/docker.sh",
    "container/import-release.sh",
    "container/release.sh",
    "scripts/stage_edge_build_context.py",
    "scripts/verify_edge_release.py",
    "scripts/validate_edge_runtime_translation.py",
    "data/manifests/canada_agronomy_sources.json",
    "data/manifests/canada_geospatial_sources.json",
    "data/manifests/source_licensing_matrix.json",
)
BENCHMARK_ROOTS: tuple[str, ...] = ()
RUNTIME_POLICY_ROOTS: tuple[str, ...] = ()
RUNTIME_ASSET_ROOTS = (
    "src/agronomy_agent",
    "frontend/src",
    "frontend/public",
    "scripts",
    "configs",
    "data/manifests",
    "data/eval",
    "data/snapshots",
    "docs/public",
)
IGNORED_TREE_NAMES = {".DS_Store", ".pytest_cache", "__pycache__", "dist", "node_modules"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_entry(root: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _tree_digest(root: Path, path: Path, *, manifests_only: bool = False) -> dict[str, Any]:
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file()
        and not any(part in IGNORED_TREE_NAMES for part in item.relative_to(path).parts)
        and item.suffix != ".pyc"
        and (not manifests_only or item.name.endswith("_manifest.json"))
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        relative = str(item.relative_to(root))
        file_sha = _sha256(item)
        total_bytes += item.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return {
        "path": str(path.relative_to(root)),
        "file_count": len(files),
        "bytes": total_bytes,
        "sha256": digest.hexdigest(),
    }


def build_manifest(root: Path) -> dict[str, Any]:
    rag_path = root / RAG_CONFIG
    rag = yaml.safe_load(rag_path.read_text(encoding="utf-8")) or {}
    retrieval = rag.get("retrieval") or {}
    configured_corpora = [str(value) for value in retrieval.get("corpus_paths") or []]
    graph_values = [str(value) for value in retrieval.get("graph_paths") or []]
    policy_value = retrieval.get("corpus_policy_manifest")
    policy = load_corpus_policy(root, policy_value)
    included_corpora, excluded_corpora = partition_runtime_corpus_paths(
        configured_corpora,
        policy,
    )
    knowledge_values = [*map(str, included_corpora), *graph_values]
    required = [
        RAG_CONFIG,
        MODEL_CONFIG,
        *CONTROL_PATHS,
        *([str(policy_value)] if policy_value else []),
        *knowledge_values,
    ]
    missing = [value for value in required if not (root / value).is_file()]
    missing.extend(value for value in BENCHMARK_ROOTS if not (root / value).is_dir())
    missing.extend(value for value in RUNTIME_POLICY_ROOTS if not (root / value).is_dir())
    missing.extend(value for value in RUNTIME_ASSET_ROOTS if not (root / value).is_dir())
    if missing:
        raise FileNotFoundError("edge runtime inputs are missing: " + ", ".join(missing))

    knowledge_entries = [_file_entry(root, root / value, "runtime_knowledge") for value in knowledge_values]
    for value in included_corpora:
        policy_row = corpus_policy_for_path(value, policy)
        expected_sha = str((policy_row or {}).get("sha256") or "")
        actual_sha = _sha256(root / str(value))
        if expected_sha != actual_sha:
            raise ValueError(f"runtime corpus failed policy SHA-256 validation: {value}")
    excluded_entries = []
    for row in excluded_corpora:
        policy_row = corpus_policy_for_path(row.get("path") or "", policy) or {}
        excluded_entries.append(
            {
                **row,
                "rights_status": policy_row.get("rights_status"),
                "expected_sha256": policy_row.get("sha256"),
                "included": False,
            }
        )
    control_entries = [_file_entry(root, root / value, "runtime_control") for value in required if value not in knowledge_values]
    geo_cache = _tree_digest(root, root / "data/derived/geo_cache")
    bundled_geo_layers = _tree_digest(
        root,
        root / "data/derived/geo_layers",
        manifests_only=True,
    )
    benchmark_entries = [_tree_digest(root, root / value) for value in BENCHMARK_ROOTS]
    policy_entries = [_tree_digest(root, root / value) for value in RUNTIME_POLICY_ROOTS]
    asset_entries = [_tree_digest(root, root / value) for value in RUNTIME_ASSET_ROOTS]
    all_digests = [
        entry["sha256"]
        for entry in (
            *control_entries,
            *knowledge_entries,
            *policy_entries,
            *asset_entries,
            *benchmark_entries,
            geo_cache,
            bundled_geo_layers,
        )
    ]
    contract_digest = hashlib.sha256("\n".join(all_digests).encode("ascii")).hexdigest()
    source_epoch = os.getenv("SOURCE_DATE_EPOCH")
    generated_at = (
        dt.datetime.fromtimestamp(int(source_epoch), tz=dt.UTC)
        if source_epoch
        else dt.datetime.now(dt.UTC)
    ).replace(microsecond=0).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "pass",
        "contract_sha256": contract_digest,
        "image_contract": {
            "containerfile": "Containerfile",
            "application_port": 8080,
            "state_mount": "/state",
            "model_protocol": "openai_compatible_http",
            "model_endpoint_path": "/v1/chat/completions",
            "model_weights_in_image": False,
            "native_host_inference": "mlx_lm.server",
            "apple_launcher": "container/apple.sh",
            "docker_launcher": "container/docker.sh",
            "docker_compose": "docker-compose.edge.yml",
        },
        "model": {
            "config_path": MODEL_CONFIG,
            "configured_model_id": (yaml.safe_load((root / MODEL_CONFIG).read_text(encoding="utf-8")) or {}).get("serving_model_id"),
            "included": False,
            "reason": "MLX and Metal run natively on the macOS host; the Linux image calls the host over loopback-only HTTP.",
        },
        "rag_config": RAG_CONFIG,
        "corpus_policy_manifest": str(policy_value) if policy_value else None,
        "configured_corpus_count": len(configured_corpora),
        "included_corpus_count": len(included_corpora),
        "excluded_corpus_count": len(excluded_entries),
        "excluded_corpora": excluded_entries,
        "runtime_knowledge": knowledge_entries,
        "runtime_knowledge_bytes": sum(entry["bytes"] for entry in knowledge_entries),
        "runtime_policies": policy_entries,
        "runtime_assets": asset_entries,
        "geo_cache_seed": geo_cache,
        "bundled_geo_layers": bundled_geo_layers,
        "benchmark_evidence": benchmark_entries,
        "control_files": control_entries,
    }


def _preserve_generated_at(output: Path, manifest: dict[str, Any]) -> None:
    if not output.is_file():
        return
    try:
        existing = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if existing.get("contract_sha256") == manifest.get("contract_sha256") and existing.get("generated_at"):
        manifest["generated_at"] = existing["generated_at"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("container/runtime_manifest.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    manifest = build_manifest(root)
    _preserve_generated_at(output, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("status", "contract_sha256", "runtime_knowledge_bytes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
