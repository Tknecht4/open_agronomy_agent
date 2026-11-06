"""Bounded field-dossier execution; results never modify confirmed grower facts."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import threading
from typing import Any
from agronomy_agent.geospatial.geometry import geodesic_metrics
from agronomy_agent.server.services.tool_service import run_local_tool
from agronomy_agent.field_imagery import search_field_imagery
from agronomy_agent.server.storage.farm_store import geometry_geojson
from agronomy_agent.server.storage.field_context_store import (
    SOURCES, SUCCESS, get_job, scope_identity, current_sources, cancel_job, update_job, save_snapshot,
)
_SLOTS = threading.BoundedSemaphore(2)

def _normalize(source: str, value: dict[str, Any]) -> dict[str, Any]:
    status = str(value.get("status") or "unknown")
    aliases = {"ok": "available", "ready": "available", "partial_available": "partial", "blocked_offline": "offline", "no_data": "no_match", "empty": "no_match", "no_scene": "no_match", "error": "provider_error", "unavailable": "provider_error", "source_unavailable": "provider_error", "location_required": "invalid_geometry"}
    availability = aliases.get(status, status)
    if availability not in SUCCESS | {"offline", "provider_error", "rate_limited", "invalid_geometry", "not_installed", "integrity_failed", "credentials_required", "jurisdiction_unknown"}:
        availability = "provider_error"
    message = str(value.get("message") or value.get("boundary") or value.get("reason") or "")
    if source == "weather":
        available = value.get("available_days_by_parameter", {})
        expected = value.get("requested_day_count")
        if available and expected:
            message = f"{min(available.values())}–{max(available.values())} of {expected} requested days available across parameters. Partial totals exclude missing days. Gridded weather, not a field station or forecast."
            if min(available.values()) < expected and availability == "available":
                availability = "partial"
    return {"availability": availability, "observed_at": value.get("observation_end") or value.get("year"),
        "message": message, "role": "regional_prior" if source != "imagery" else "scene_metadata", "values": value}


def run_source(source: str, field: dict[str, Any], network_mode: str) -> dict[str, Any]:
    geometry = geometry_geojson(field["metadata"]["open_agronomy_agent"]["geometry"])
    point = geodesic_metrics(geometry)["representative_point"]
    country, province = field.get("country"), field.get("province_state")
    today = datetime.now(timezone.utc).date()
    if source == "weather":
        end = today - timedelta(days=3)
        value = run_local_tool("weather-power", {"lat": point["latitude"], "lon": point["longitude"], "start": (end - timedelta(days=6)).strftime("%Y%m%d"), "end": end.strftime("%Y%m%d")}, network_mode=network_mode)
    elif source == "imagery":
        if geometry.get("type") == "MultiPolygon":
            return {"availability": "unsupported_geometry", "message": "This imagery source currently accepts one polygon or a point. Your complete multipart boundary is retained unchanged; it has not been simplified or split for this check.", "role": "scene_metadata"}
        value = search_field_imagery(geometry, "hls-s30-planetary-computer", (today - timedelta(days=30)).isoformat(), today.isoformat(), limit=5, network_mode=network_mode)
        value["message"] = f"{len(value.get('scenes', []))} scenes returned (limit 5). Field pixel coverage has not been assessed." if value.get("status") == "available" else value.get("message", "")
    elif country not in {"Canada", "United States"}:
        return {"availability": "jurisdiction_unknown", "message": "Confirm the country in field details. No country-specific source was selected.", "role": "regional_prior"}
    elif source == "soil":
        if country == "Canada":
            value = run_local_tool("cansis-soil-landscapes-canada", {"lat": point["latitude"], "lon": point["longitude"], "geometry": geometry, "province": province}, network_mode=network_mode)
        else:
            value = run_local_tool("nrcs-soil-survey-geometry", {"geometry": geometry}, network_mode=network_mode)
    else:
        tool = "aafc-annual-crop-inventory" if country == "Canada" else "cropland-data-layer-geometry"
        value = run_local_tool(tool, {"geometry": geometry, "sample_points": 3, "province": province, **({"year": "latest"} if country == "Canada" else {})}, network_mode=network_mode)
    return _normalize(source, value)


def _execute_job(store: Any, settings: Any, job_id: str) -> None:
    with _SLOTS:
        job = get_job(store, job_id)
        if not job or job["status"] != "queued":
            return
        field = store.get_phase4_field_context(job["field_id"])
        if not field:
            cancel_job(store, job_id); return
        update_job(store, job_id, "running")
        results = {}
        for source in job["sources"]:
            current_job = get_job(store, job_id)
            if not current_job or current_job["status"] == "cancelled":
                return
            latest = store.get_phase4_field_context(field["id"])
            if not latest or scope_identity(latest) != job["scope_sha256"]:
                update_job(store, job_id, "superseded")
                return
            cached = current_sources(store, field).get(source, {})
            if cached.get("availability") in SUCCESS and cached.get("freshness") == "current":
                results[source] = {"availability": cached["availability"], "snapshot_id": cached["snapshot_id"], "cache_hit": True}
                continue
            try:
                value = run_source(source, field, settings.network_mode)
            except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                value = {"availability": "invalid_geometry" if isinstance(exc, ValueError) else "provider_error", "message": str(exc), "role": "regional_prior"}
            snapshot_id = save_snapshot(store, job, field, source, value)
            results[source] = {"availability": value["availability"], "snapshot_id": snapshot_id}
            update_job(store, job_id, results=results)
        successful = sum(value["availability"] in SUCCESS for value in results.values())
        latest = store.get_phase4_field_context(field["id"])
        status = "superseded" if not latest or scope_identity(latest) != job["scope_sha256"] else "completed" if successful == len(results) else "partial" if successful else "failed"
        update_job(store, job_id, status, results)


def execute_job(store: Any, settings: Any, job_id: str) -> None:
    try:
        _execute_job(store, settings, job_id)
    except Exception:
        # Persist interruption rather than leaving a permanent running spinner.
        update_job(store, job_id, "failed")
