"""Date-range execution over the existing field-bound imagery job and chip stores."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import logging
import math
import time
from typing import Any, Callable
from uuid import UUID, uuid5

import httpx

from agronomy_agent.field_imagery import search_hls_series
from agronomy_agent.server.storage import imagery_job_store as jobs

_LOG = logging.getLogger(__name__)
_MAX_PROCESSING_SECONDS = 30 * 60
SERIES_WORKERS = 3
MIN_USABLE_COVERAGE = 0.60


def _number(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def quality(result: dict) -> dict[str, Any]:
    qa = result.get("qa") or {}
    excluded = qa.get("excluded_area_m2_by_reason") or {}
    area = _number(qa.get("field_area_m2", qa.get("sample_area_m2")))
    sentinel = result.get("provider_id") == "sentinel2-c1-earth-search"
    cloud_keys = ("scl_medium_cloud", "scl_high_cloud", "scl_cirrus") if sentinel else ("cloud",)
    cloud = [_number(excluded.get(key)) for key in cloud_keys]
    missing = _number(excluded.get("source_invalid") if sentinel else qa.get("nodata_area_m2"))
    fraction = None
    status = "unknown"
    if area and area > 0 and missing is not None and all(value is not None for value in cloud):
        flagged = sum(cloud)
        # The flag counts can include invalid pixels. No coverage is inferred
        # through missing data, even when every observed pixel is clear.
        if flagged > missing + 1e-6:
            status = "detected"
        if missing <= 1e-6:
            fraction = min(1.0, max(0.0, flagged / area))
            status = "detected" if fraction > 0 else "clear"
    reasons = (
        ("Snow or ice", ("snow_ice", "scl_snow_ice")),
        ("Cloud", cloud_keys),
        ("Cloud shadow or nearby cloud", ("shadow", "adjacent_cloud_shadow", "scl_cloud_shadow", "cloud_shadow_adjacency")),
        ("High aerosol", ("high_aerosol",)),
        ("Missing data", ("source_invalid",)),
    )
    largest_reason = max(
        ((max((_number(excluded.get(key)) or 0) for key in keys), name) for name, keys in reasons),
        default=(0, ""),
    )
    if missing is not None and missing > largest_reason[0]:
        largest_reason = (missing, "Missing data")
    return {"field_cloud_fraction": fraction, "field_cloud_status": status,
            "usable_fraction": _number(qa.get("valid_area_fraction")),
            "main_exclusion": largest_reason[1] if largest_reason[0] > 0 else None}


def observation(scene: dict, child: dict) -> dict[str, Any]:
    receipt = child.get("result") or {}
    source = receipt.get("source") or {}
    try:
        acquired = datetime.fromisoformat(source["acquired_at"].replace("Z", "+00:00"))
        matched = (receipt.get("scene_id") == scene["scene_id"] and receipt.get("provider_id") == scene["provider_id"]
                   and acquired.tzinfo is not None
                   and acquired.astimezone(timezone.utc).isoformat(timespec="microseconds") == scene["acquired_at"])
    except (KeyError, ValueError, AttributeError):
        matched = False
    indices = {name: None for name in ("NDVI", "NDMI")}
    public_scene = {key: value for key, value in scene.items() if key != "catalog_item"}
    row = {**public_scene, "indices": indices, **quality({}), "status": "unavailable"}
    if not matched or child["status"] != "completed" or receipt.get("status") not in {"available", "empty_valid_area"}:
        return row
    for name in indices:
        index = (receipt.get("zonal_stats") or {}).get(name) or {}
        if (_number(index.get("area_m2")) or 0) > 0:
            indices[name] = _number(index.get("mean"))
    return {**row, **quality(receipt), "job_id": child["id"],
            "status": "observed" if any(value is not None for value in indices.values()) else "no_usable_pixels"}


def public_series_result(result: dict) -> dict[str, Any]:
    """Apply the coverage rule to both analysis progress and saved series."""
    scenes = result["scenes"]
    accepted = []
    exclusions = {"low_coverage": 0, "unknown_coverage": 0, "no_usable_pixels": 0, "unavailable": 0}
    for scene in scenes:
        coverage = _number(scene.get("usable_fraction"))
        if scene["status"] == "unavailable":
            exclusions["unavailable"] += 1
        elif coverage is None or not 0 <= coverage <= 1:
            exclusions["unknown_coverage"] += 1
        elif coverage <= MIN_USABLE_COVERAGE:
            exclusions["low_coverage"] += 1
        elif scene["status"] != "observed":
            exclusions["no_usable_pixels"] += 1
        else:
            accepted.append(scene)
    return {**result, "scenes": accepted, "processed": len(scenes),
            "minimum_usable_fraction": MIN_USABLE_COVERAGE, "exclusions": exclusions}


def execute_series(store: Any, field: dict, parent: dict, execute_single: Callable[[dict], None]) -> None:
    request = parent["request"]
    job_id = parent["id"]
    revision = parent["geometry_revision_id"]
    start_date, end_date = request["start_date"], request["end_date"]
    try:
        discovery = search_hls_series(parent["geometry"], start_date, end_date)
    except (httpx.HTTPError, RuntimeError, ValueError):
        jobs.set_status(store, job_id, "failed", {"status": "catalog_unavailable", "scenes": [], "total": 0})
        return
    if discovery["status"] != "available":
        jobs.set_status(store, job_id, "failed", {"status": discovery["status"], "scenes": [], "total": 0})
        return

    candidates = discovery["scenes"]
    queue = iter(enumerate(candidates))
    deadline = time.monotonic() + _MAX_PROCESSING_SECONDS
    rows: dict[int, dict] = {}

    def progress(status: str) -> dict:
        return {"status": status, "scenes": [rows[index] for index in sorted(rows)], "total": len(candidates)}

    def check_stop() -> str | None:
        if not jobs.is_running(store, job_id):
            return "cancelled"
        if jobs.current_geometry_revision(store, field["id"]) != revision:
            return "boundary_changed"
        if time.monotonic() >= deadline:
            return "time_limit"
        return None

    def analyze(scene: dict) -> dict:
        # Date-specific requests reuse verified chips across overlapping ranges.
        day = scene["acquired_at"][:10]
        payload = {"provider_id": scene["provider_id"], "scene_id": scene["scene_id"],
                   "start_date": day, "end_date": day, "buffer_m": 0,
                   "series_job_id": job_id,
                   "sampling_mode": "point_pixel" if parent["geometry"]["type"] == "Point" else "field_polygon"}
        operation = str(uuid5(UUID(job_id), scene["scene_id"]))
        try:
            child, _ = jobs.queue(store, field, payload, operation, revision, series_child=True)
            if child["status"] == "queued":
                execute_single({**child, "catalog_item": scene.get("catalog_item")})
            child = jobs.get_job(store, child["id"])
        except (RuntimeError, ValueError):
            _LOG.warning("Could not analyze an image in series %s", job_id)
            child = None
        return observation(scene, child or {"status": "unavailable"})

    jobs.set_status(store, job_id, "running", progress("processing"))
    with ThreadPoolExecutor(max_workers=SERIES_WORKERS) as pool:
        pending = {}
        while True:
            stopped = check_stop()
            if stopped == "cancelled":
                return
            if stopped == "boundary_changed":
                jobs.set_status(store, job_id, "superseded", progress(stopped))
                return
            if stopped == "time_limit":
                jobs.set_status(store, job_id, "completed", progress(stopped))
                return
            while len(pending) < SERIES_WORKERS:
                item = next(queue, None)
                if item is None:
                    break
                index, scene = item
                pending[pool.submit(analyze, scene)] = index
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED, timeout=.5)
            for future in done:
                rows[pending.pop(future)] = future.result()
            if done:
                jobs.set_status(store, job_id, "running", progress("processing"))
    jobs.set_status(store, job_id, "completed", progress("complete"))
