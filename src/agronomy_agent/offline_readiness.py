from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.agno_runtime.knowledge_graph import graph_artifact_paths
from agronomy_agent.corpus_governance import (
    load_corpus_policy,
    partition_runtime_corpus_paths,
)

from agronomy_agent.model_identity import sha256_path
from agronomy_agent.runtime_profiles import DEFAULT_MODEL_CONFIG, DEFAULT_RAG_CONFIG


OFFLINE_READINESS_SCHEMA = "open_agronomy_agent.offline_readiness.v1"
RUNTIME_MANIFEST_SCHEMA = "open_agronomy_agent.edge_runtime_manifest.v1"
IGNORED_TREE_NAMES = {".DS_Store", ".pytest_cache", "__pycache__", "dist", "node_modules"}


def _tree_digest(root: Path, path: Path) -> dict[str, Any]:
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file()
        and not any(part in IGNORED_TREE_NAMES for part in item.relative_to(path).parts)
        and item.suffix != ".pyc"
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        relative = str(item.relative_to(root))
        file_sha = sha256_path(item)
        total_bytes += item.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return {"file_count": len(files), "bytes": total_bytes, "sha256": digest.hexdigest()}


def _model_snapshot(hub_cache: Path, model_id: str, revision: str) -> Path:
    model_dir = hub_cache / ("models--" + model_id.replace("/", "--"))
    snapshot = model_dir / "snapshots" / revision
    if snapshot.is_dir():
        return snapshot
    ref = model_dir / "refs" / "main"
    if ref.is_file():
        resolved = ref.read_text(encoding="utf-8").strip()
        if resolved != revision:
            raise ValueError(f"cached revision {resolved} does not match configured revision {revision}")
        snapshot = model_dir / "snapshots" / resolved
    if not snapshot.is_dir():
        raise FileNotFoundError(f"model snapshot is missing: {snapshot}")
    return snapshot


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    detail: str,
    *,
    evidence: dict[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "passed": bool(passed),
            "detail": detail,
            "evidence": evidence or {},
        }
    )


def _resolve_profile_path(root: Path, value: Path | None, default: Path) -> Path:
    """Resolve an optional profile artifact without treating cwd as authority."""

    path = value or default
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_external_spatial_pack(
    *,
    root: Path,
    pack_root: Path,
    profile_id: str,
    profile_manifest_path: Path,
) -> dict[str, Any]:
    """Call the profile-bound pack validator without importing developer data.

    Spatial profile construction lives in the checked-in setup scripts because
    it is intentionally an explicit post-clone operation.  Readiness loads
    only that deterministic validator and never downloads, derives, or alters
    a selected pack.
    """

    script_path = root / "scripts" / "build_prairie_spatial_pack.py"
    scripts_dir = script_path.parent
    if not script_path.is_file():
        raise FileNotFoundError(f"offline spatial pack validator is missing: {script_path}")
    inserted = str(scripts_dir) not in sys.path
    if inserted:
        sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_offline_spatial_pack_validator",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load offline spatial pack validator: {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validate_pack = getattr(module, "validate_pack", None)
        if not callable(validate_pack):
            raise RuntimeError("offline spatial pack validator does not expose validate_pack")
        return validate_pack(
            pack_root.resolve(),
            profile_id=profile_id,
            profile_manifest_path=profile_manifest_path.resolve(),
        )
    finally:
        if inserted:
            sys.path.remove(str(scripts_dir))


def build_offline_readiness(
    *,
    root: Path,
    runtime_manifest_path: Path | None = None,
    model_config_path: Path | None = None,
    rag_config_path: Path | None = None,
    hub_cache: Path | None = None,
    state_dir: Path | None = None,
    spatial_pack_root: Path | None = None,
    spatial_profile_id: str | None = None,
    spatial_profile_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the assets needed after internet connectivity is removed.

    This function never performs a network request. A passing receipt means the
    selected local files are present and hash-consistent; a launch smoke with
    the network disabled is still recorded separately.
    """

    root = root.resolve()
    runtime_manifest_path = (runtime_manifest_path or root / "container/runtime_manifest.json").resolve()
    model_config_path = (model_config_path or root / DEFAULT_MODEL_CONFIG).resolve()
    rag_config_path = (rag_config_path or root / DEFAULT_RAG_CONFIG).resolve()
    hub_cache = (
        hub_cache
        or Path(os.getenv("HF_HUB_CACHE") or root / ".hf_cache/hub")
    ).resolve()
    checks: list[dict[str, Any]] = []

    try:
        runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        runtime_manifest = {}
        _check(checks, "runtime_manifest", False, f"runtime manifest unreadable: {exc}")
    else:
        runtime_schema = runtime_manifest.get("schema_version")
        supported_runtime_schema = runtime_schema in {
            RUNTIME_MANIFEST_SCHEMA,
            "open_agronomy_agent.portable_runtime_bundle.v2",
        }
        _check(
            checks,
            "runtime_manifest",
            supported_runtime_schema
            and runtime_manifest.get("status") == "pass",
            "runtime manifest schema and status verified",
            evidence={
                "path": str(runtime_manifest_path),
                "sha256": sha256_path(runtime_manifest_path),
                "contract_sha256": runtime_manifest.get("contract_sha256"),
            },
        )

    try:
        model_config = yaml.safe_load(model_config_path.read_text(encoding="utf-8")) or {}
        model_id = str(model_config.get("serving_model_id") or model_config.get("model_id") or "")
        revision = str(model_config.get("model_revision") or "")
        if not model_id or not revision:
            raise ValueError("serving model ID and immutable revision are required")
        snapshot = _model_snapshot(hub_cache, model_id, revision)
        snapshot_files = [item for item in snapshot.rglob("*") if item.is_file()]
        names = {item.name for item in snapshot_files}
        tokenizer_ready = "tokenizer.json" in names or "tokenizer.model" in names
        weights = [item for item in snapshot_files if item.name.endswith((".safetensors", ".gguf", ".npz"))]
        model_ready = (
            "config.json" in names
            and "tokenizer_config.json" in names
            and tokenizer_ready
            and bool(weights)
            and all(item.resolve().stat().st_size > 0 for item in weights)
        )
        _check(
            checks,
            "model_snapshot",
            model_ready,
            "configured model weights and tokenizer are locally cached",
            evidence={
                "model_id": model_id,
                "revision": revision,
                "snapshot": str(snapshot),
                "file_count": len(snapshot_files),
                "bytes": sum(item.resolve().stat().st_size for item in snapshot_files),
                "model_config_sha256": sha256_path(model_config_path),
            },
        )
    except (OSError, ValueError) as exc:
        model_id = ""
        revision = ""
        _check(checks, "model_snapshot", False, str(exc))

    try:
        rag = yaml.safe_load(rag_config_path.read_text(encoding="utf-8")) or {}
        retrieval = rag.get("retrieval") if isinstance(rag.get("retrieval"), dict) else {}
        artifact_root_value = retrieval.get("artifact_root")
        artifact_root = (
            (rag_config_path.resolve().parent / str(artifact_root_value)).resolve()
            if artifact_root_value
            else root
        )
        try:
            artifact_root.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"RAG artifact_root escapes the offline repository: {artifact_root_value!r}"
            ) from exc
        corpus_policy = load_corpus_policy(artifact_root, retrieval.get("corpus_policy_manifest"))
        loadable_corpora, _ = partition_runtime_corpus_paths(
            retrieval.get("corpus_paths") or [],
            corpus_policy,
        )
        graph_artifacts = graph_artifact_paths(
            [artifact_root / str(value) for value in retrieval.get("graph_paths") or []],
            require_manifests=bool(retrieval.get("require_graph_manifests", False)),
        )
        knowledge_paths = [
            *[
                Path(value).resolve()
                if Path(str(value)).is_absolute()
                else (artifact_root / str(value)).resolve()
                for value in loadable_corpora
            ],
            *graph_artifacts,
        ]
        manifest_knowledge_rows = runtime_manifest.get("runtime_knowledge", [])
        if runtime_manifest.get("schema_version") == "open_agronomy_agent.portable_runtime_bundle.v2":
            manifest_knowledge_rows = [
                item
                for item in runtime_manifest.get("entries") or []
                if isinstance(item, dict) and item.get("role") == "runtime_knowledge"
            ]
        manifest_knowledge = {
            str(item.get("path")): item
            for item in manifest_knowledge_rows
            if isinstance(item, dict)
        }
        knowledge_failures: list[str] = []
        for path in knowledge_paths:
            try:
                relative = str(path.relative_to(root))
            except ValueError:
                relative = str(path)
            entry = manifest_knowledge.get(relative)
            if not path.is_file():
                knowledge_failures.append(f"missing:{relative}")
            elif not entry or entry.get("sha256") != sha256_path(path):
                knowledge_failures.append(f"hash_mismatch:{relative}")
        _check(
            checks,
            "local_knowledge",
            not knowledge_failures and bool(knowledge_paths),
            "all configured RAG and graph files match the runtime manifest",
            evidence={
                "artifact_root": str(artifact_root),
                "file_count": len(knowledge_paths),
                "failures": knowledge_failures,
            },
        )
    except (OSError, ValueError) as exc:
        _check(checks, "local_knowledge", False, f"RAG configuration unreadable: {exc}")

    runtime_tree_failures: list[str] = []
    if runtime_manifest.get("schema_version") == "open_agronomy_agent.portable_runtime_bundle.v2":
        for entry in runtime_manifest.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            relative = str(entry.get("path") or "")
            path = root / relative
            if not path.is_file():
                runtime_tree_failures.append(f"missing:{relative}")
            elif sha256_path(path) != entry.get("sha256"):
                runtime_tree_failures.append(f"hash_mismatch:{relative}")
    else:
        for section in ("runtime_policies", "runtime_assets"):
            for entry in runtime_manifest.get(section, []):
                if not isinstance(entry, dict):
                    continue
                relative = str(entry.get("path") or "")
                path = root / relative
                if not path.is_dir():
                    runtime_tree_failures.append(f"missing:{relative}")
                    continue
                actual = _tree_digest(root, path)
                if actual["sha256"] != entry.get("sha256"):
                    runtime_tree_failures.append(f"hash_mismatch:{relative}")
    _check(
        checks,
        "runtime_assets",
        not runtime_tree_failures,
        "application, configuration, scripts, and policy trees match the runtime manifest",
        evidence={"failures": runtime_tree_failures},
    )

    selected_spatial_profile = str(spatial_profile_id or "").strip()
    if spatial_pack_root is None and selected_spatial_profile:
        _check(
            checks,
            "map_packs_and_licenses",
            False,
            "an offline spatial profile was selected without an installed spatial pack root",
            evidence={"profile_id": selected_spatial_profile},
        )
    elif spatial_pack_root is None:
        _check(
            checks,
            "map_packs_and_licenses",
            True,
            "no optional spatial profile selected; offline map queries will report not_installed",
            evidence={"profile_id": None, "optional": True},
        )
    else:
        selected_spatial_profile = selected_spatial_profile or "prairie-dss-v1"
        profile_manifest = _resolve_profile_path(
            root,
            spatial_profile_manifest_path,
            root / "data/manifests/offline_spatial_profiles_v1.json",
        )
        try:
            validation = _validate_external_spatial_pack(
                root=root,
                pack_root=spatial_pack_root,
                profile_id=selected_spatial_profile,
                profile_manifest_path=profile_manifest,
            )
            _check(
                checks,
                "map_packs_and_licenses",
                validation.get("status") == "pass",
                "selected external spatial pack matches its pinned profile and install receipt",
                evidence={
                    "profile_id": selected_spatial_profile,
                    "pack_root": str(spatial_pack_root.resolve()),
                    "profile_manifest": str(profile_manifest),
                    "validation": validation,
                },
            )
        except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            _check(
                checks,
                "map_packs_and_licenses",
                False,
                f"selected external spatial pack is not ready: {exc}",
                evidence={
                    "profile_id": selected_spatial_profile,
                    "pack_root": str(spatial_pack_root),
                    "profile_manifest": str(profile_manifest),
                },
            )

    if state_dir is not None:
        state_dir = state_dir.resolve()
        writable = state_dir.is_dir() and os.access(state_dir, os.W_OK)
        _check(
            checks,
            "state_directory",
            writable,
            "local state directory is writable",
            evidence={"path": str(state_dir)},
        )

    failures = [check for check in checks if not check["passed"]]
    return {
        "schema_version": OFFLINE_READINESS_SCHEMA,
        "status": "ready" if not failures else "blocked",
        "offline_ready": not failures,
        "network_requests_performed": 0,
        "root": str(root),
        "model_id": model_id or None,
        "model_revision": revision or None,
        "runtime_manifest_path": str(runtime_manifest_path),
        "check_count": len(checks),
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "boundary": (
            "This receipt proves local asset presence and integrity without making a network request. "
            "A release claim also requires a recorded cold launch with external connectivity disabled."
        ),
    }
