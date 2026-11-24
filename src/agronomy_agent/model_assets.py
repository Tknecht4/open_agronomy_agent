"""Asset identities and integrity checks for the two local answer-model downloads."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from agronomy_agent.paths import repo_path

_MANIFESTS = {
    ("mlx-community/gemma-4-e2b-it-4bit", "238767527555cb75a05732a84dff5d6ba0dd6809"): (
        "configs/model_assets_gemma4_e2b_mlx.json",
        "20eb23b66581b7d61ea66cb9d79f84a9f18de95844b96089a64ff814b06ee238",
    ),
    ("mlx-community/gemma-4-e4b-it-4bit", "475b9088d29754a3379866cf5aeb6b41acd313c2"): (
        "configs/model_assets_gemma4_e4b_mlx.json",
        "f3df6a52323995800a9aeb78948a2074d080521b5b15146a3352dc4965b737af",
    ),
}


@dataclass(frozen=True)
class ModelAsset:
    name: str
    size: int
    sha256: str
    blob_id: str


@lru_cache(maxsize=4)
def _assets(path: Path, digest: str, model_id: str, revision: str) -> tuple[ModelAsset, ...]:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Model asset manifest failed verification.")
    manifest = json.loads(data)
    if (manifest["schema_version"], manifest["repo_id"], manifest["revision"]) != (
        "open_agronomy_agent.pinned_model_assets.v1", model_id, revision,
    ):
        raise ValueError("Model asset manifest does not match the configured model.")
    assets = tuple(ModelAsset(row["path"], row["bytes"], row["sha256"], row.get("lfs_sha256") or row["git_blob_id"])
                   for row in manifest["files"])
    if not assets or len({asset.name for asset in assets}) != len(assets) or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]+", asset.name) or asset.name in {".", ".."}
        or type(asset.size) is not int or asset.size <= 0
        or not re.fullmatch(r"[0-9a-f]{64}", asset.sha256)
        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", asset.blob_id)
        for asset in assets
    ):
        raise ValueError("Model asset manifest contains invalid files.")
    return assets


def pinned_model_assets(model_id: str, revision: str | None) -> tuple[ModelAsset, ...]:
    spec = _MANIFESTS.get((model_id, revision))
    return _assets(repo_path(spec[0]), spec[1], model_id, revision) if spec and revision else ()


@lru_cache(maxsize=128)
def _digest(path: Path, identity: tuple[int, int, int, int, int]) -> str:
    # Cache by file identity as well as path, so atomically replacing a blob
    # or modifying it triggers verification before the snapshot serves again.
    with path.open("rb") as handle:
        result = hashlib.file_digest(handle, "sha256").hexdigest()
    stat = path.stat()
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != identity:
        raise OSError("A model asset changed during verification.")
    return result


def verified_model_asset(path: Path, root: Path, asset: ModelAsset) -> bool:
    try:
        target = path.resolve(strict=True)
        if not target.is_relative_to(root) and not _shared_asset(target, root, asset):
            return False
        if not target.is_file():
            return False
        stat = target.stat()
        return stat.st_size == asset.size and _digest(
            target, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
        ) == asset.sha256
    except (OSError, RuntimeError):
        return False


def _shared_asset(target: Path, root: Path, asset: ModelAsset) -> bool:
    # Recent Hub clients may link the repository blob into the cache-wide
    # Xet store. Limit that exception to the canonical two-level blob layout.
    shared = root.parent / "blobs"
    if not target.is_relative_to(shared):
        return False
    parts = target.relative_to(shared).parts
    if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[1]) or parts[0] != parts[1][:2]:
        return False
    blob = root / "blobs" / asset.blob_id
    return blob.is_symlink() and blob.resolve(strict=True) == target
