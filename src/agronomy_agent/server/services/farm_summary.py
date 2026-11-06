"""Read-only grower summaries from retained, authorized workspace records."""
from __future__ import annotations

from typing import Any

from agronomy_agent.geospatial.geometry import geodesic_metrics
from agronomy_agent.server.storage.field_context_store import current_sources
from agronomy_agent.server.storage.farm_store import geometry_geojson, workspace_rows, season_record


def overview(store: Any, workspace_id: str, *, farm_id: str | None = None,
             unassigned: bool = False, season: int | None = None) -> dict[str, Any]:
    from shapely.geometry import shape
    from shapely.ops import unary_union

    rows = workspace_rows(store, workspace_id, season)
    if farm_id is not None or unassigned:
        rows = [row for row in rows if row["farm_id"] == farm_id]
    boundaries = []
    for row in rows:
        geometry = geometry_geojson(row["geometry"])
        row["boundary_area_m2"] = None
        row["boundary_perimeter_m"] = None
        row["geometry_status"] = "unknown" if geometry is None else "point" if geometry["type"] == "Point" else "boundary"
        if geometry and geometry["type"] in {"Polygon", "MultiPolygon"}:
            metrics = geodesic_metrics(geometry)
            row["boundary_area_m2"] = metrics["area_m2"]
            row["boundary_perimeter_m"] = metrics["perimeter_m"]
            boundaries.append(shape(geometry))
    summed_area = sum(row["boundary_area_m2"] or 0 for row in rows)
    # The union avoids silently counting shared ground twice. Unknown is not zero.
    union_area = geodesic_metrics(unary_union(boundaries))["area_m2"] if boundaries else None
    farm_coverage = {}
    for key in {row['farm_id'] for row in rows}:
        members = [row for row in rows if row['farm_id'] == key]
        shapes = [shape(geometry_geojson(row['geometry'])) for row in members if row['geometry_status'] == 'boundary']
        total = sum(row['boundary_area_m2'] or 0 for row in members)
        area = geodesic_metrics(unary_union(shapes))['area_m2'] if shapes else None
        farm_coverage[key or 'unassigned'] = {'boundary_area_m2': area, 'unknown_area_count': len(members) - len(shapes),
            'overlapping_area_m2': max(0., total-area) if area is not None else None}
    return {"farm_coverage": farm_coverage, "workspace_id": workspace_id, "farm_id": farm_id, "season": season, "fields": rows,
        "coverage": {"field_count": len(rows), "boundary_count": len(boundaries),
            "unknown_area_count": len(rows) - len(boundaries), "boundary_area_m2": union_area,
            "summed_boundary_area_m2": summed_area if boundaries else None,
            "overlapping_area_m2": max(0.0, summed_area - union_area) if union_area is not None else None},
        "record_count": sum(row["record_count"] for row in rows),
        "last_record_at": max((row["last_record_at"] for row in rows if row["last_record_at"]), default=None),
        "boundary": "Calculated boundary coverage; points and unknown boundaries are excluded. Public context is not a field measurement."}


def field_summary(store: Any, field: dict[str, Any], season: int | None) -> dict[str, Any]:
    # No provider calls, and nothing is promoted into the question compiler here.
    rows = overview(store, field["workspace_id"], season=season)["fields"]
    result = next(row for row in rows if row["id"] == field["id"])
    entry = field.get("metadata", {}).get("open_agronomy_agent", {})
    from agronomy_agent.server.storage.imagery_job_store import list_jobs
    image_jobs = list_jobs(store, field["id"])
    completed = next((job for job in image_jobs if job["status"] in {"completed", "superseded"} and job.get("result")), None)
    latest_image = None
    if completed:
        image = completed["result"]
        latest_image = {"job_id": completed["id"], "acquired_at": (image.get("source") or {}).get("acquired_at"),
            "provider_id": image.get("provider_id"), "scene_id": image.get("scene_id"),
            "geometry_revision_id": completed["geometry_revision_id"],
            "current_geometry": completed["geometry_revision_id"] == result["geometry_revision_id"],
            "support": image.get("support_assessment"), "completed_at": completed["updated_at"]}
    with store._cursor() as cursor:
        latest_job = cursor.execute("SELECT id,status FROM field_enrichment_jobs WHERE field_id=? ORDER BY created_at DESC LIMIT 1", (field["id"],)).fetchone()
        seasons = [season_record(row) for row in cursor.execute("SELECT * FROM field_seasons WHERE field_id=? ORDER BY season DESC", (field["id"],)).fetchall()]
        revisions = [dict(row) for row in cursor.execute("SELECT id, geometry_sha256, supersedes_id, created_at FROM field_geometry_revisions WHERE field_id=? ORDER BY created_at DESC", (field["id"],)).fetchall()]
    return {**result, "latest_context_job": dict(latest_job) if latest_job else None, "latest_image": latest_image,
        "location_confirmation": entry.get("location_confirmation"), "seasons": seasons, "geometry_revisions": revisions,
        "confirmed_facts": {"country": field.get("country"), "province_state": field.get("province_state"),
            "crop": result["crop"], "season": season, "legacy_undated_crop": result["legacy_undated_crop"]},
        "public_context": {"regional": entry.get("geo_priors"), "lineage": entry.get("geo_context_lineage"),
            "role": "regional_prior", "freshness": "unassessed"},
        "source_status": current_sources(store, field),
        "boundary_import": entry.get("boundary_import"),
        "boundary": "Grower records, mapped context and model output remain distinct. An undated crop is not a confirmed season."}
