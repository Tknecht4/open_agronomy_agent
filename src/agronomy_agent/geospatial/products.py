"""Shared private chip admission, cache reuse and publication.

Source adapters own identity, scientific policy and processing. Existing
ImageryStore owns indexed integrity; no second cache or eviction policy is added.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable

from agronomy_agent.imagery_store import ImageryStore


def cached_product(*, request_hash: str, provider_id: str, scene_id: str | None,
                   cache_root: str | Path, network_mode: str,
                   budget_root: str | Path | None, max_cache_bytes: int,
                   min_free_bytes: int,
                   process: Callable[[Path, Any], dict[str, Any]]) -> dict[str, Any]:
    """Reuse an intact exact identity before optional dependencies or network."""
    from agronomy_agent.imagery_budget import reserve_cache, StorageRefusal, validate_policy
    validate_policy(max_cache_bytes, min_free_bytes)
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    supplied = Path(cache_root).expanduser()
    if supplied.is_symlink():
        raise ValueError("imagery cache root cannot be a symlink")
    root = supplied.resolve()
    repository = Path(__file__).resolve().parents[3]
    if root.is_relative_to(repository):
        raise ValueError("imagery cache must be outside the repository")
    budget = Path(budget_root).expanduser() if budget_root is not None else supplied
    if budget.is_symlink() or budget.resolve().is_relative_to(repository) or not root.is_relative_to(budget.resolve()):
        raise ValueError("imagery budget root must contain the cache outside the repository")
    try:
        if (root / "imagery-v1.sqlite3").exists():
            cached = ImageryStore(root, read_only=True).get(request_hash, scene_id=scene_id)
            if cached:
                return {**cached, "cache_hit": True}
        if network_mode == "offline":
            return {"status": "blocked_offline", "provider_id": provider_id,
                    "scene_id": scene_id, "request_hash": request_hash,
                    "reason": "no matching local chip"}
        with reserve_cache(budget, max_cache_bytes=max_cache_bytes, min_free_bytes=min_free_bytes) as admission:
            return process(root, admission)
    except StorageRefusal as exc:
        return {"status": exc.status, "reason": exc.reason, "request_hash": request_hash}
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        return {"status": "storage_unavailable", "reason": "imagery_cache_unavailable",
                "error_type": type(exc).__name__, "request_hash": request_hash}


def write_chip_bundle(store: ImageryStore, receipt: dict[str, Any],
                      bounds: tuple[float, float, float, float], *,
                      npz: bytes, png: bytes, admission: Any) -> None:
    """Publish the standard NPZ/PNG/receipt bundle under the writer admission.

    Random private temporary files avoid following pre-existing temporary paths.
    The index is written only after all artifact files are in place. An interrupted
    publication may leave an unindexed orphan, never a verified cache hit.
    """
    names = store._names(receipt)
    payloads = {"npz": npz, "png": png,
                "receipt": json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()}
    admission.ensure(sum(map(len, payloads.values())) + 1024**2)
    staged: dict[str, Path] = {}
    try:
        for kind, payload in payloads.items():
            with tempfile.NamedTemporaryFile(prefix=".chip-", dir=store.root, delete=False) as handle:
                staged[kind] = Path(handle.name)
                handle.write(payload)
        for kind, path in staged.items():
            os.replace(path, store.root / names[kind])
        store.put(receipt, bounds)
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
