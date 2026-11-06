"""Local administrative suggestions; cartographic matches never confirm jurisdiction."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from agronomy_agent.server.services.geospatial_service import intersect_region_layers
from agronomy_agent.server.storage.farm_store import geometry_geojson

LAYER = "ca_statcan_2021_provinces_territories"
BOUNDARY = "2021 Census cartographic context for orientation, not a surveyed boundary or proof of legal jurisdiction. Confirm the field location before using country-specific sources."


def suggestions(field: dict[str, Any]) -> dict[str, Any]:
    geometry = geometry_geojson(field.get("metadata", {}).get("open_agronomy_agent", {}).get("geometry") or {"kind": "none"})
    base = {"candidates": [], "boundary": BOUNDARY, "source_id": LAYER, "network_used": False}
    if geometry is None:
        return {**base, "status": "location_required", "message": "Save a point or boundary first."}
    response = intersect_region_layers(geometry=geometry, layer_ids=[LAYER], network_mode="offline")
    integrity = response.get("source_integrity", {}).get(LAYER, {})
    if integrity.get("status") != "verified":
        status = integrity.get("status") or "not_installed"
        return {**base, "status": status, "message": "A verified Canadian province boundary pack is needed for mapped suggestions. Enter the location manually if known."}
    if response.get("errors"):
        return {**base, "status": "provider_error", "message": "The installed administrative map could not be read. Confirm the location manually or retry the local source."}
    rows = [row for row in response.get("intersections", []) if row.get("province_name") and row.get("coverage_estimate", 0) > 0]
    candidates = []
    for row in rows:
        receipt = {"source_id": LAYER, "source_integrity": integrity, "geometry": geometry,
                   "province": row["province_name"], "coverage": row["coverage_estimate"], "source_url": row.get("source_url")}
        identity = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        candidates.append({"id": identity, "country": "Canada", "province": row["province_name"],
            "coverage": row["coverage_estimate"], "support": row.get("coverage_support_type"),
            "confirmable": len(rows) == 1 and row["coverage_estimate"] >= 0.999999,
            "source_url": row.get("source_url"), "receipt": receipt})
    status = "suggested" if len(candidates) == 1 and candidates[0]["confirmable"] else "ambiguous" if candidates else "no_match"
    return {**base, "status": status, "candidates": candidates, "message": {
        "suggested": "A mapped location is available for your confirmation.",
        "ambiguous": "The complete saved geometry is not contained in one mapped province. Review its location; no country or province was chosen.",
        "no_match": "No Canadian province matched. This does not establish a US or other jurisdiction; confirm the location manually.",
    }[status]}
