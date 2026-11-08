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
import sys
import sqlite3
import tempfile
import threading
import time
import base64
import math
import logging
from functools import lru_cache
from typing import Any

from agronomy_agent.field_imagery import _valid_search_geometry
from agronomy_agent.imagery_analytics import _request_identity
from agronomy_agent.imagery_receipts import validate_hls_receipt
from agronomy_agent.sentinel2_receipts import request_identity as sentinel_request, validate_sentinel2_receipt
from agronomy_agent.imagery_store import ImageryStore
from agronomy_agent.paths import REPO_ROOT

_WORKER_SLOT = threading.BoundedSemaphore(1)
_PUBLIC_KEYS = frozenset((
    "status", "evidence_role", "interpretation", "provider_id", "scene_id",
    "request_hash", "geometry_hash", "process_version", "source_native_grid",
    "process_hash", "chip_hash", "source", "grid", "qa", "zonal_stats",
    "process_spec", "limitations", "scientific_qualification", "interior_zonal_stats", "field_action_authority",
    "model_refs", "created_at", "elapsed_seconds", "cog_transfer_bytes", "preview_version",
    "cog_range_requests", "cog_transfer_limit_bytes", "cache_hit", "reason", "sampling", "request",
))


def _run_process(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Avoid macOS fork handlers in a server with loaded native GIS libraries.

    CPython 3.11+ uses posix_spawn with an absolute executable, no cwd and
    close_fds=False. A fresh isolated interpreter closes inherited descriptors
    before executing the worker, retaining the worker's private environment.
    """
    if sys.platform == "darwin":
        directory = str(kwargs.pop("cwd", REPO_ROOT))
        executable = os.path.abspath(command[0])
        bootstrap = (
            "import os,sys; "
            "os.closerange(3, os.sysconf('SC_OPEN_MAX')); "
            "os.chdir(sys.argv[1]); "
            "os.execv(sys.argv[2], sys.argv[2:])"
        )
        command = [executable, "-I", "-c", bootstrap, directory, executable, *command[1:]]
        kwargs["close_fds"] = False
    return subprocess.run(command, **kwargs)


def geometry_hash(geometry: dict[str, Any]) -> str:
    polygon, _ = _valid_search_geometry(geometry)
    return hashlib.sha256(json.dumps(polygon, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=8)
def _worker_health(executable: str, modified_ns: int, check_minute: int = 0) -> dict[str, Any]:
    try:
        code = """import json,numpy,rasterio,pyproj,shapely,PIL,httpx
versions={'numpy':numpy.__version__,'rasterio':rasterio.__version__,'pyproj':pyproj.__version__,'shapely':shapely.__version__,'Pillow':PIL.__version__,'httpx':httpx.__version__}
try:
 import scipy.ndimage
 versions['scipy']=__import__('scipy').__version__
except ImportError:
 pass
print(json.dumps(versions))"""
        result = _run_process([executable, "-I", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, timeout=30, env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1"}, check=False)
        if result.returncode == 0 and len(result.stdout) < 4096:
            return {"status": "healthy", "versions": json.loads(result.stdout)}
        logging.getLogger(__name__).warning("Image worker check exited %s: %s", result.returncode, result.stderr.decode(errors="replace")[-1000:])
        missing = b"ModuleNotFoundError" in result.stderr or b"ImportError" in result.stderr
        return {"status": "unavailable", "reason": "missing_dependency" if missing else "worker_check_failed", "exit_code": result.returncode,
                "message": "The image worker could not import a required dependency. Repair the optional installation." if missing else "The image worker setup check failed. Retry after current work finishes; see the local server log if it persists."}
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "reason": "setup_check_timeout", "message": "The image setup check timed out. Retry when the local runtime is less busy; installed dependencies have not been ruled out."}
    except OSError as exc:
        logging.getLogger(__name__).warning("Image worker could not start: %s", exc)
        return {"status": "unavailable", "reason": "worker_start_failed", "message": "The image worker could not start. Check the configured executable and local runtime resources, then retry."}
    except ValueError:
        return {"status": "unavailable", "reason": "invalid_worker_check", "message": "The image worker returned an invalid setup response. Check the configured executable."}


def readiness(settings: Any) -> dict[str, Any]:
    configured = bool(settings.imagery_cache_root and settings.imagery_worker_python)
    health = {"status": "not_configured"}
    if configured:
        try:
            health = _worker_health(str(settings.imagery_worker_python), Path(settings.imagery_worker_python).stat().st_mtime_ns, int(time.monotonic() // 60))
        except OSError:
            health = {"status": "unavailable", "message": "The configured image worker is missing."}
    healthy = health["status"] == "healthy"
    return {"status": "ready" if healthy else "worker_unavailable" if configured else "not_configured", "network_mode": settings.network_mode,
            "worker": health, "configured": configured, "pixel_access": "not_live_verified",
            "providers": [{"id": provider, "discovery": True, "analysis": healthy and (provider != "sentinel2-c1-earth-search" or "scipy" in health.get("versions", {})), "preview": healthy,
                "sampling_modes": ["field_polygon"] if provider == "sentinel2-c1-earth-search" else ["field_polygon", "point_pixel", "point_buffer"], "cache": bool(settings.imagery_cache_root)}
                for provider in ("hls-s30-planetary-computer", "hls-l30-planetary-computer", "sentinel2-c1-earth-search")],
            "sampling_modes": ["field_polygon", "point_pixel", "point_buffer"],
            "sample_radius_bounds_m": {"min": 15, "max": 1500},
            "storage_policy": {"max_cache_bytes": settings.imagery_cache_max_bytes,
                               "min_free_bytes": settings.imagery_min_free_bytes,
                               "eviction": "none"}}


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
    return child


def public_receipt(result: dict[str, Any], field_id: str) -> dict[str, Any]:
    public = {key: result[key] for key in _PUBLIC_KEYS if key in result}
    if result.get("status") in {"available", "empty_valid_area"} and result.get("chip_hash"):
        # This is a current serving interpretation of already validated support,
        # not an alteration to the retained acquisition/process receipt. Recompute
        # it for old cache hits too; a cached interpretation cannot grant quality.
        public["support_assessment"] = _support_assessment(result)
        public["preview_url"] = f"/api/demo/fields/{field_id}/imagery/analyses/{result['chip_hash']}/preview.png"
    return public


def _support_assessment(result: dict[str, Any]) -> dict[str, Any]:
    """Describe supported pixels without inventing a field-utility threshold.

    ``analyze`` validates HLS support before this projection. The processing
    ``available`` status only establishes positive QA-clear area, while each
    index may describe less area or have no eligible pixels at all.
    """
    sampling = result.get("sampling")
    support_kind = sampling["support_kind"] if sampling else "field_polygon"
    qa = result["qa"]
    area = qa["sample_area_m2" if sampling else "field_area_m2"]
    clear = qa["valid_area_m2"]
    indices = {}
    for name in ("NDVI", "NDMI"):
        supported = result["zonal_stats"][name]["area_m2"]
        indices[name] = {"valid_area_m2": supported,
                         "valid_fraction": min(1.0, supported / area),
                         "status": "supported_pixels_only" if supported > 0 else "no_valid_index_support"}
    return {"schema_version": "imagery_support.v1", "evidence_role": "interpretation",
            "support_kind": support_kind, "support_area_m2": area,
            "qa_clear_area_m2": clear, "qa_clear_fraction": min(1.0, clear / area),
            "index_support": indices, "minimum_valid_fraction": None,
            "coverage_admission": "not_assessed", "representativeness": "not_assessed",
            "field_action_authority": "not_authorized",
            "limitations": [
                "Available means some QA-clear support was processed; no minimum coverage policy was applied.",
                "Scene cloud percentage is scene-wide metadata, not valid support for this field or sample.",
                "Each index summary describes its supported pixels only; QA-clear and index-valid areas can differ.",
                "A single-scene receipt does not establish coverage-based scene selection, representative crop conditions or stress diagnosis.",
            ]}


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
        command = [str(settings.imagery_worker_python), "-m", "agronomy_agent.imagery_worker",
                   "--geometry", str(geometry_path), "--cache-root", str(cache),
                   "--provider", payload["provider_id"], "--buffer-m", str(payload.get("buffer_m", 0)),
                   "--budget-root", str(settings.imagery_cache_root),
                   "--max-cache-bytes", str(settings.imagery_cache_max_bytes),
                   "--min-free-bytes", str(settings.imagery_min_free_bytes)]
        for name in ("scene_id", "start_date", "end_date", "sampling_mode", "sample_radius_m"):
            if payload.get(name) is not None:
                command.extend(["--" + name.replace("_", "-"), str(payload[name])])
        if settings.network_mode == "online":
            command.append("--online")
        with tempfile.TemporaryFile() as output:
            completed = _run_process(command, cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.DEVNULL, timeout=150, check=False)
            output.seek(0)
            data = output.read(128 * 1024 + 1)
        if completed.returncode not in (0, 2) or len(data) > 128 * 1024:
            raise ValueError("imagery worker failed")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("imagery worker returned invalid result")
        return result


def request_identity(geometry: dict, payload: dict) -> tuple[str, str]:
    if payload['provider_id'] == 'sentinel2-c1-earth-search':
        request = sentinel_request(geometry, payload)
        return request['geometry_hash'], request['request_hash']
    _, _, geo, request = _request_identity(geometry, payload['provider_id'], payload.get('scene_id'), payload.get('start_date'), payload.get('end_date'), payload.get('buffer_m', 0), None, sampling_mode=payload.get('sampling_mode'), sample_radius_m=payload.get('sample_radius_m'))
    return geo, request


def validate_receipt(receipt: dict, **kwargs: Any) -> None:
    validator = validate_sentinel2_receipt if receipt.get('provider_id') == 'sentinel2-c1-earth-search' else validate_hls_receipt
    validator(receipt, **kwargs)


def analyze(settings: Any, field: dict[str, Any], geometry: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    expected_geometry, expected_request = request_identity(geometry, payload)
    cache = field_cache(settings, field)
    if cache is None or settings.imagery_worker_python is None:
        return {"status": "not_configured"}
    try:
        cached = ImageryStore(cache, read_only=True).get(expected_request, scene_id=payload.get("scene_id")) if (cache / "imagery-v1.sqlite3").exists() else None
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        return {"status": "storage_unavailable", "reason": "imagery_cache_unavailable"}
    if cached:
        try:
            validate_receipt(cached, geometry=geometry, provider_id=payload["provider_id"],
                sampling_mode=payload.get("sampling_mode") or ("point_pixel" if geometry["type"] == "Point" else "field_polygon"),
                sample_radius_m=payload.get("sample_radius_m"))
        except (ValueError, TypeError, KeyError):
            return {"status": "storage_unavailable", "reason": "imagery_sample_binding_failed"}
        return public_receipt({**cached, "cache_hit": True}, field["id"])
    if settings.network_mode == "offline":
        return {"status": "blocked_offline", "reason": "no matching local chip"}
    if not _WORKER_SLOT.acquire(blocking=False):
        return {"status": "busy"}
    try:
        result = _run_worker(settings, cache, geometry, payload)
        if result.get("status") in {"available", "empty_valid_area"}:
            # Read back independently rather than trust worker stdout or paths.
            stored = ImageryStore(cache, read_only=True).get_by_chip_hash(result.get("chip_hash", ""))
            if not stored or stored.get("geometry_hash") != expected_geometry or stored.get("request_hash") != expected_request:
                raise ValueError("imagery worker result binding failed")
            validate_receipt(stored, geometry=geometry, provider_id=payload["provider_id"],
                sampling_mode=payload.get("sampling_mode") or ("point_pixel" if geometry["type"] == "Point" else "field_polygon"),
                sample_radius_m=payload.get("sample_radius_m"))
            result = stored
        return public_receipt(result, field["id"])
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "imagery worker failed or exceeded its time limit"}
    finally:
        _WORKER_SLOT.release()


def preview(settings: Any, field: dict[str, Any], geometry: dict[str, Any], chip_hash: str) -> bytes | None:
    from agronomy_agent.imagery_analytics import PREVIEW_VERSION
    cache = field_cache(settings, field)
    if cache is None or not cache.exists():
        return None
    try:
        store = ImageryStore(cache, read_only=True)
        result = store.get_by_chip_hash(chip_hash)
    except (OSError, RuntimeError, sqlite3.Error, ValueError):
        return None
    if (result is None or result.get("geometry_hash") != geometry_hash(geometry)
            or result.get("preview_version") != PREVIEW_VERSION):
        return None
    try:
        validate_receipt(result, geometry=geometry)
    except (ValueError, TypeError, KeyError):
        return None
    return store.preview_bytes(chip_hash)


def map_overlay(settings: Any, field: dict[str, Any], geometry: dict[str, Any], chip_hash: str) -> dict[str, Any] | None:
    original = preview(settings, field, geometry, chip_hash)
    if original is None or not settings.imagery_worker_python:
        return None
    cache = field_cache(settings, field)
    command = [str(settings.imagery_worker_python), "-m", "agronomy_agent.imagery_overlay", "--cache-root", str(cache), "--chip-hash", chip_hash]
    try:
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            completed = _run_process(command, cwd=REPO_ROOT, env={"PATH": os.defpath, "PYTHONPATH": str(REPO_ROOT / "src"), "PYTHONNOUSERSITE": "1"},
                stdin=subprocess.DEVNULL, stdout=output, stderr=errors, timeout=30, check=False)
            if completed.returncode:
                errors.seek(0)
                logging.getLogger(__name__).warning("Image overlay worker exited %s: %s", completed.returncode, errors.read(2048).decode("utf-8", errors="replace"))
            output.seek(0)
            data = output.read(4 * 1024 * 1024 + 1)
        if completed.returncode or len(data) > 4 * 1024 * 1024:
            return None
        result = json.loads(data)
        bounds = result["bounds"]
        image = base64.b64decode(result["png_base64"], validate=True)
        if (result["chip_hash"] != chip_hash or result["source_preview_sha256"] != hashlib.sha256(original).hexdigest()
            or result["display_crs"] != "EPSG:3857" or result["display_resampling"] != "nearest"
            or len(bounds) != 2 or any(len(point) != 2 for point in bounds)
            or any(type(value) not in (int, float) or not math.isfinite(value) for point in bounds for value in point)
            or not -85.06 <= bounds[0][0] < bounds[1][0] <= 85.06 or not -180 <= bounds[0][1] < bounds[1][1] <= 180
            or not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > 2 * 1024 * 1024):
            return None
        return result
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired):
        return None
