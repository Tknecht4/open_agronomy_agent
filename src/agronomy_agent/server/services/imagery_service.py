"""Bounded optional EO worker and field-scoped private imagery cache.

Only the operator supplies executable/cache paths. HTTP callers supply an
allowlisted provider, dates and a scene ID; geometry comes from saved state.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Any

from agronomy_agent.field_imagery import _valid_geometry
from agronomy_agent.imagery_analytics import _request_identity
from agronomy_agent.imagery_store import ImageryStore
from agronomy_agent.paths import REPO_ROOT

_WORKER_SLOT = threading.BoundedSemaphore(1)
_PUBLIC_KEYS = frozenset((
    "status", "evidence_role", "interpretation", "provider_id", "scene_id",
    "request_hash", "geometry_hash", "process_version", "source_native_grid",
    "process_hash", "chip_hash", "source", "grid", "qa", "zonal_stats",
    "model_refs", "created_at", "elapsed_seconds", "cog_transfer_bytes", "preview_version",
    "cog_range_requests", "cog_transfer_limit_bytes", "cache_hit", "reason",
))


def geometry_hash(geometry: dict[str, Any]) -> str:
    polygon, _ = _valid_geometry(geometry)
    return hashlib.sha256(json.dumps(polygon, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def readiness(settings: Any) -> dict[str, Any]:
    configured = bool(settings.imagery_cache_root and settings.imagery_worker_python)
    return {"status": "ready" if configured else "not_configured", "network_mode": settings.network_mode}


def field_cache(settings: Any, field: dict[str, Any]) -> Path | None:
    if settings.imagery_cache_root is None:
        return None
    root = Path(settings.imagery_cache_root)
    if root.is_symlink() or root.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("imagery cache location is invalid")
    identity = json.dumps([field["workspace_id"], field["id"]], separators=(",", ":"))
    child = root / hashlib.sha256(identity.encode()).hexdigest()
    if child.is_symlink():
        raise ValueError("imagery field cache is invalid")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return child


def public_receipt(result: dict[str, Any], field_id: str) -> dict[str, Any]:
    public = {key: result[key] for key in _PUBLIC_KEYS if key in result}
    if result.get("status") in {"available", "empty_valid_area"} and result.get("chip_hash"):
        public["preview_url"] = f"/api/demo/fields/{field_id}/imagery/analyses/{result['chip_hash']}/preview.png"
    return public


def _run_worker(settings: Any, cache: Path, geometry: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    # Credentials, private overlays, proxy configuration and user-site Python
    # state are deliberately absent from this public-imagery subprocess.
    env = {"PATH": os.defpath, "PYTHONPATH": str(REPO_ROOT / "src"),
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "HF_HUB_OFFLINE": "1", "OMP_NUM_THREADS": "1"}
    with tempfile.TemporaryDirectory(prefix="agronomy-imagery-") as temporary:
        geometry_path = Path(temporary) / "geometry.json"
        geometry_path.write_text(json.dumps(geometry), encoding="utf-8")
        geometry_path.chmod(0o600)
        command = [str(settings.imagery_worker_python), str(REPO_ROOT / "scripts/analyze_field_imagery.py"),
                   "--geometry", str(geometry_path), "--cache-root", str(cache),
                   "--provider", payload["provider_id"], "--buffer-m", str(payload.get("buffer_m", 0))]
        for name in ("scene_id", "start_date", "end_date"):
            if payload.get(name):
                command.extend(["--" + name.replace("_", "-"), payload[name]])
        if settings.network_mode == "online":
            command.append("--online")
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(command, cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.DEVNULL, timeout=150, check=False)
            output.seek(0)
            data = output.read(128 * 1024 + 1)
        if completed.returncode not in (0, 2) or len(data) > 128 * 1024:
            raise ValueError("imagery worker failed")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("imagery worker returned invalid result")
        return result


def analyze(settings: Any, field: dict[str, Any], geometry: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    _, _, expected_geometry, expected_request = _request_identity(
        geometry, payload["provider_id"], payload.get("scene_id"), payload.get("start_date"),
        payload.get("end_date"), payload.get("buffer_m", 0), None)
    cache = field_cache(settings, field)
    if cache is None or settings.imagery_worker_python is None:
        return {"status": "not_configured"}
    cached = ImageryStore(cache).get(expected_request, scene_id=payload.get("scene_id"))
    if cached:
        return public_receipt({**cached, "cache_hit": True}, field["id"])
    if settings.network_mode == "offline":
        return {"status": "blocked_offline", "reason": "no matching local chip"}
    if not _WORKER_SLOT.acquire(blocking=False):
        return {"status": "busy"}
    try:
        result = _run_worker(settings, cache, geometry, payload)
        if result.get("status") in {"available", "empty_valid_area"}:
            # Read back independently rather than trust worker stdout or paths.
            stored = ImageryStore(cache).get_by_chip_hash(result.get("chip_hash", ""))
            if not stored or stored.get("geometry_hash") != expected_geometry or stored.get("request_hash") != expected_request:
                raise ValueError("imagery worker result binding failed")
            result = stored
        return public_receipt(result, field["id"])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "imagery worker failed or exceeded its time limit"}
    finally:
        _WORKER_SLOT.release()


def preview(settings: Any, field: dict[str, Any], geometry: dict[str, Any], chip_hash: str) -> bytes | None:
    from agronomy_agent.imagery_analytics import PREVIEW_VERSION
    cache = field_cache(settings, field)
    if cache is None or not cache.exists():
        return None
    store = ImageryStore(cache)
    result = store.get_by_chip_hash(chip_hash)
    if (result is None or result.get("geometry_hash") != geometry_hash(geometry)
            or result.get("preview_version") != PREVIEW_VERSION):
        return None
    return store.preview_bytes(chip_hash)
