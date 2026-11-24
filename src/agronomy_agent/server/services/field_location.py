"""Local administrative suggestions; cartographic matches never confirm jurisdiction."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
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


_ADMIN_LAYERS = {
    "ca_statcan_2021_provinces_territories": ("CA", "Province or territory", "https://www150.statcan.gc.ca/n1/en/catalogue/92-160-X2021001"),
    "ca_statcan_2021_census_subdivisions": ("CA", "Census subdivision", "https://www150.statcan.gc.ca/n1/en/catalogue/92-160-X2021001"),
    "ab_municipal_districts": ("CA", "Municipal district or county", "https://open.canada.ca/data/dataset/1d1376c6-8bf8-4c3a-a87e-6b176d8c6a39"),
    "us_tiger_2026_states": ("US", "State or equivalent", "https://www.census.gov/geographies/mapping-files/2026/geo/tiger-line-file.html"),
    "us_tiger_2026_counties": ("US", "County or equivalent", "https://www.census.gov/geographies/mapping-files/2026/geo/tiger-line-file.html"),
}


def _pack_root() -> Path | None:
    raw = os.getenv("AGRONOMY_AGENT_ADMINISTRATIVE_PACK_ROOT")
    return Path(raw).expanduser() if raw else None


def _candidates(layer_id: str, field_shape: Any, root: Path | None) -> tuple[dict[str, Any], list[tuple[dict, Any]]]:
    from shapely.geometry import box, shape
    from agronomy_agent.server.services.geospatial_service import REGION_LAYERS, RegionLayer, verified_local_candidates

    code, name, source = _ADMIN_LAYERS[layer_id]
    if root is None:
        if layer_id != LAYER:
            return {"status": "missing"}, []
        layer = REGION_LAYERS[LAYER]
    else:
        layer = RegionLayer(
            id=layer_id, label=name, system=name, service_url="", source_url=source, color="#667f94",
            code_fields=("code",), name_fields=("name",), query_backend="local_sqlite",
            local_database=str(root / f"{layer_id}.sqlite3"), country_code=code,
        )
    receipt, rows = verified_local_candidates(layer, field_shape.bounds)
    candidates = []
    for item in rows:
        boundary = shape(item["geometry"])
        properties = item["properties"]
        if not boundary.is_valid:
            # A rounded source ring can become invalid on reprojection.
            properties = {**properties, "invalid_source_boundary": True}
            boundary = box(*boundary.bounds)
        if (boundary.intersects(field_shape) if field_shape.geom_type == "Point"
                else boundary.intersection(field_shape).area > 0):
            candidates.append((properties, boundary))
    return receipt, candidates


def mapped_location(field: dict[str, Any], *, geometry_revision_id: str | None = None, pack_root: Path | None = None) -> dict[str, Any]:
    """Resolve location from authorized saved geometry without changing the field."""
    from shapely import union_all
    from shapely.errors import GEOSException
    from shapely.geometry import shape
    from agronomy_agent.geospatial.geometry import canonical_geometry
    from agronomy_agent.server.storage.farm_store import geometry_identity

    saved = field.get("metadata", {}).get("open_agronomy_agent", {}).get("geometry") or {"kind": "none"}
    identities: list[dict[str, Any]] = []
    geometry = geometry_geojson(saved)
    base = {"geometry_revision_id": geometry_revision_id, "geometry_sha256": geometry_identity(saved),
            "country": None, "province_state": None, "county_rm": None, "label": "", "sources": identities}
    if geometry is None:
        return {**base, "status": "location_required"}
    root = pack_root if pack_root is not None else _pack_root()
    try:
        field_shape = shape(canonical_geometry(geometry))

        def lookup(layer: str) -> list[tuple[dict, Any]]:
            receipt, candidates = _candidates(layer, field_shape, root)
            identities.append({"layer_id": layer, "status": receipt.get("status"),
                               "source_url": _ADMIN_LAYERS[layer][2],
                               "source_sha256": receipt.get("expected", {}).get("source_sha256"),
                               "database_sha256": receipt.get("observed", {}).get("database_sha256")})
            return candidates

        ca, us = lookup(LAYER), lookup("us_tiger_2026_states")
        if any(properties.get("invalid_source_boundary") for properties, _ in (*ca, *us)):
            return {**base, "status": "ambiguous", "message": "A local boundary could not be matched reliably."}
        if ca and us:
            return {**base, "status": "ambiguous", "message": "The field crosses a country boundary."}
        regions = ca or us
        if not regions:
            if any(row["status"] in {"integrity_failed", "coverage_limited"} for row in identities):
                return {**base, "status": "unavailable", "message": "A local boundary layer could not be verified."}
            missing = any(row["status"] == "missing" for row in identities)
            return {**base, "status": "pack_missing" if missing else "no_match",
                    "message": "Install the local boundary pack to look up this field." if missing else "No verified administrative match."}
        # Country coverage is the union of the matched provinces/states, including multipart support.
        footprint = regions[0][1] if len(regions) == 1 else union_all([region for _, region in regions])
        if not footprint.covers(field_shape):
            return {**base, "status": "ambiguous", "message": "The local boundaries cover only part of this field."}
        country = "Canada" if ca else "United States"
        region = regions[0][0] if len(regions) == 1 else None
        region_name = region["name"] if region else None
        locality = None
        if region:
            if ca and region["code"] == "PR_48":
                districts = lookup("ab_municipal_districts")
                locality = _one_containing(districts, field_shape)
                # Partial district coverage must not be filled with a coarser statistical name.
                if not districts:
                    locality = _one_containing(lookup("ca_statcan_2021_census_subdivisions"), field_shape, "48")
            else:
                layer = "ca_statcan_2021_census_subdivisions" if ca else "us_tiger_2026_counties"
                locality = _one_containing(lookup(layer), field_shape, region["code"].split("_", 1)[1])
        locality_name = locality["name"] if locality else None
        reported_country = field.get("country")
        reported_region = field.get("province_state")
        conflict = bool(
            reported_country and reported_country != country
            or region and reported_region and reported_region.rstrip(".").casefold() not in {
                region_name.casefold(), str(region.get("province_abbreviation", "")).rstrip(".").casefold(),
                str(region.get("abbreviation", "")).casefold(),
            }
        )
        return {
            **base, "status": "conflict" if conflict else "resolved" if region and locality else "partial",
            "country": country, "province_state": region_name, "county_rm": locality_name,
            "locality_code": locality.get("code") if locality else None,
            "locality_type": locality.get("area_type") if locality else None,
            "label": ", ".join(value for value in (locality_name, region_name, country) if value),
            **({"message": "The mapped location differs from the saved location."} if conflict else {}),
        }
    except (ValueError, TypeError, KeyError, OSError, GEOSException, sqlite3.Error):
        return {**base, "status": "unavailable", "message": "The local boundary lookup is unavailable."}


def _one_containing(candidates: list[tuple[dict, Any]], field_shape: Any, parent: str | None = None) -> dict | None:
    if len(candidates) != 1:
        return None
    properties, boundary = candidates[0]
    if properties.get("invalid_source_boundary") or parent is not None and properties.get("parent_code") != parent:
        return None
    return properties if boundary.covers(field_shape) else None


def routing_location(field: dict[str, Any], location: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    """Use mapped geography for source eligibility, preserving recorded values."""
    location = mapped_location(field) if location is None else location
    if location["status"] in {"conflict", "ambiguous"}:
        return None, None
    if location["country"]:
        return location["country"], location["province_state"]
    return field.get("country"), field.get("province_state")


def probe_pack(root: Path) -> dict[str, Any]:
    examples = [
        ("alberta", {"lat": 53.207, "lon": -113.757}, ("Canada", "Alberta", "Leduc County")),
        ("iowa", {"lat": 42.041, "lon": -93.646}, ("United States", "Iowa", "Story County")),
    ]
    rows = []
    errors = []
    for name, point, expected in examples:
        located = mapped_location({"metadata": {"open_agronomy_agent": {"geometry": {"kind": "point", "point": point}}}}, pack_root=root)
        actual = tuple(located[key] for key in ("country", "province_state", "county_rm"))
        rows.append({"id": name, "expected": expected, "observed": actual})
        if actual != expected:
            errors.append(f"{name}: {actual!r} != {expected!r}")
    return {"status": "fail" if errors else "pass", "probes": rows, "errors": errors}
