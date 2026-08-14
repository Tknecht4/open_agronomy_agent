from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.paths import REPO_ROOT


RUNTIME_PROFILE_REGISTRY = Path("configs/runtime_profiles.json")
RUNTIME_PROFILE_REGISTRY_SCHEMA = "open_agronomy_agent.runtime_profiles.v1"
DEFAULT_MODEL_CONFIG = "configs/model_gemma4_e2b_interface_v2.yaml"
DEFAULT_RAG_CONFIG = "configs/rag_governed_runtime_v2.yaml"


@dataclass(frozen=True)
class RuntimeProfileRegistry:
    release_model_config: str
    default_rag_config: str
    selectable_rag_configs: tuple[str, ...]
    historical_rag_configs: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_path(root: Path, value: Any, *, label: str) -> tuple[str, Path]:
    rendered = str(value or "").strip()
    relative = Path(rendered)
    if (
        not rendered
        or relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 2
        or relative.parts[0] != "configs"
        or relative.suffix not in {".yaml", ".yml"}
    ):
        raise ValueError(f"{label} must be a direct YAML path under configs/: {rendered!r}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"{label} does not exist: {rendered}")
    return relative.as_posix(), path


def _repository_file(root: Path, value: Any, *, label: str) -> tuple[str, Path]:
    rendered = str(value or "").strip()
    relative = Path(rendered)
    if not rendered or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must be a repository-relative file: {rendered!r}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"{label} does not exist: {rendered}")
    return relative.as_posix(), path


def _validate_sha256(path: Path, expected: Any, *, label: str) -> None:
    rendered = str(expected or "").strip().lower()
    if len(rendered) != 64 or any(character not in "0123456789abcdef" for character in rendered):
        raise ValueError(f"{label} must declare a lowercase SHA-256")
    actual = _sha256(path)
    if actual != rendered:
        raise ValueError(f"{label} SHA-256 mismatch: expected {rendered}, observed {actual}")


def _validate_active_rag_config(path: Path, *, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a YAML object")
    retrieval = payload.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ValueError(f"{label} must contain a retrieval object")
    corpus_paths = retrieval.get("corpus_paths")
    if not isinstance(corpus_paths, list) or not corpus_paths or any(
        not isinstance(value, str) or not value.strip() for value in corpus_paths
    ):
        raise ValueError(f"{label} must declare non-empty corpus_paths")
    if not str(retrieval.get("corpus_policy_manifest") or "").strip():
        raise ValueError(f"{label} must declare corpus_policy_manifest")
    return retrieval


def load_runtime_profile_registry(
    *,
    root: Path = REPO_ROOT,
    registry_path: Path | None = None,
) -> RuntimeProfileRegistry:
    """Load the explicit release profile registry and reject accidental discovery.

    Runtime YAML presence is not activation. A profile becomes selectable only
    through this registry, and every registered active profile must also pass
    the runtime corpus audit when the application starts.
    """

    root = root.resolve()
    path = registry_path or root / RUNTIME_PROFILE_REGISTRY
    if not path.is_absolute():
        path = root / path
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != RUNTIME_PROFILE_REGISTRY_SCHEMA:
        raise ValueError("unsupported runtime profile registry schema")

    release_model = payload.get("release_model")
    if not isinstance(release_model, dict) or release_model.get("status") != "active":
        raise ValueError("runtime profile registry must declare one active release_model")
    model_config, model_path = _config_path(
        root,
        release_model.get("path"),
        label="release_model.path",
    )
    _validate_sha256(model_path, release_model.get("sha256"), label="release_model")

    active_rows = payload.get("active_rag_profiles")
    if not isinstance(active_rows, list) or not active_rows:
        raise ValueError("runtime profile registry must declare active_rag_profiles")
    selectable: list[str] = []
    for index, row in enumerate(active_rows):
        label = f"active_rag_profiles[{index}]"
        if not isinstance(row, dict) or row.get("status") != "active":
            raise ValueError(f"{label} must have status active")
        if row.get("runtime_corpus_audit_required") is not True:
            raise ValueError(f"{label} must require the runtime corpus audit")
        config, config_path = _config_path(root, row.get("path"), label=f"{label}.path")
        _validate_sha256(config_path, row.get("sha256"), label=label)
        retrieval = _validate_active_rag_config(config_path, label=label)
        policy = row.get("runtime_policy")
        if not isinstance(policy, dict):
            raise ValueError(f"{label} must bind runtime_policy")
        policy_reference, policy_path = _repository_file(
            root,
            policy.get("path"),
            label=f"{label}.runtime_policy.path",
        )
        _validate_sha256(
            policy_path,
            policy.get("sha256"),
            label=f"{label}.runtime_policy",
        )
        if retrieval.get("corpus_policy_manifest") != policy_reference:
            raise ValueError(f"{label} runtime policy does not match its RAG config")
        knowledge_release = row.get("knowledge_release")
        if not isinstance(knowledge_release, dict):
            raise ValueError(f"{label} must bind knowledge_release")
        manifest_reference, manifest_path = _repository_file(
            root,
            knowledge_release.get("manifest_path"),
            label=f"{label}.knowledge_release.manifest_path",
        )
        _validate_sha256(
            manifest_path,
            knowledge_release.get("manifest_sha256"),
            label=f"{label}.knowledge_release",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("store_id") != knowledge_release.get("store_id"):
            raise ValueError(f"{label} knowledge release store_id mismatch")
        release_root = Path(manifest_reference).parent.as_posix() + "/"
        if not any(str(value).startswith(release_root) for value in retrieval["corpus_paths"]):
            raise ValueError(f"{label} does not reference its bound knowledge release")
        selectable.append(config)
    if len(selectable) != len(set(selectable)):
        raise ValueError("runtime profile registry contains duplicate active RAG paths")

    default_rag_config = str(payload.get("default_rag_config") or "").strip()
    if default_rag_config not in selectable:
        raise ValueError("default_rag_config must be one of the active RAG profiles")

    historical_rows = payload.get("historical_rag_profiles") or []
    if not isinstance(historical_rows, list):
        raise ValueError("historical_rag_profiles must be a list")
    historical: list[str] = []
    for index, row in enumerate(historical_rows):
        label = f"historical_rag_profiles[{index}]"
        if not isinstance(row, dict) or row.get("status") != "frozen_historical":
            raise ValueError(f"{label} must have status frozen_historical")
        if row.get("selectable") is not False:
            raise ValueError(f"{label} must explicitly set selectable=false")
        config, config_path = _config_path(root, row.get("path"), label=f"{label}.path")
        _validate_sha256(config_path, row.get("sha256"), label=label)
        historical.append(config)
    if len(historical) != len(set(historical)) or set(historical) & set(selectable):
        raise ValueError("runtime profile registry has duplicate or active historical RAG paths")

    if model_config != DEFAULT_MODEL_CONFIG:
        raise ValueError(
            f"release model registry drift: expected {DEFAULT_MODEL_CONFIG}, observed {model_config}"
        )
    if default_rag_config != DEFAULT_RAG_CONFIG:
        raise ValueError(
            f"default RAG registry drift: expected {DEFAULT_RAG_CONFIG}, observed {default_rag_config}"
        )
    return RuntimeProfileRegistry(
        release_model_config=model_config,
        default_rag_config=default_rag_config,
        selectable_rag_configs=tuple(selectable),
        historical_rag_configs=tuple(historical),
    )
