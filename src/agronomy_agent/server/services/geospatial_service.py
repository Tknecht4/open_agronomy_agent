from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sqlite3
import struct
import tempfile
import threading
import time
import zipfile
import zlib
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agronomy_agent.paths import repo_path


GEO_SERVICE_SCHEMA_VERSION = "open_agronomy_agent.geo_service.v1"
BOUNDARY_UPLOAD_SCHEMA_VERSION = "open_agronomy_agent.boundary_upload.v1"
CACHE_DIR = repo_path(os.getenv("AGRONOMY_AGENT_GEO_CACHE_DIR", "data/derived/geo_cache"))
HTTP_TIMEOUT_SECONDS = 25
MAX_FEATURES_PER_LAYER = 80
MAX_BBOX_SPAN_DEGREES = 12.0
MAX_BOUNDARY_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_BOUNDARY_UPLOAD_FEATURES = 250
MAX_ZIP_MEMBERS = 40
MAX_ZIP_MEMBER_BYTES = 30 * 1024 * 1024
OFFLINE_INTERSECTION_CACHE_TTL_SECONDS = 300
OFFLINE_INTERSECTION_CACHE_MAX_ENTRIES = 8
_OFFLINE_INTERSECTION_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_OFFLINE_INTERSECTION_CACHE_LOCK = threading.Lock()
WGS84_REPROJECT_UPLOAD_ERROR = (
    "boundary coordinates must be WGS84 longitude/latitude (EPSG:4326); "
    "found a coordinate outside lon/lat bounds. Reproject UTM, State Plane, "
    "Web Mercator, or local grid boundaries to EPSG:4326 before upload."
)
UPLOAD_LABEL_FIELDS = (
    "name",
    "Name",
    "NAME",
    "field",
    "FIELD",
    "field_name",
    "FieldName",
    "FIELD_NAME",
    "farm",
    "FARM",
)


@dataclass(frozen=True)
class RegionLayer:
    id: str
    label: str
    system: str
    service_url: str
    source_url: str
    color: str
    code_fields: tuple[str, ...]
    name_fields: tuple[str, ...]
    query_backend: str = "arcgis_feature_service"
    local_database: str | None = None
    local_match_reason: str = "Bundled official polygon intersection"
    boundary: str = "Official regional map context; not field truth or a legal boundary."


REGION_LAYERS: dict[str, RegionLayer] = {
    "nrcs_mlra": RegionLayer(
        id="nrcs_mlra",
        label="USDA NRCS Major Land Resource Areas",
        system="NRCS MLRA",
        service_url="https://services.arcgis.com/SXbDpmb7xQkk44JV/ArcGIS/rest/services/Major_Land_Resource_Areas/FeatureServer/0",
        source_url="https://www.nrcs.usda.gov/resources/data-and-reports/major-land-resource-area-mlra",
        color="#f1c84b",
        code_fields=("MLRARSYM", "MLRA_ID"),
        name_fields=("MLRA_NAME",),
    ),
    "epa_l3_us": RegionLayer(
        id="epa_l3_us",
        label="EPA Level III Ecoregions of the Continental United States",
        system="EPA Level III Ecoregion",
        service_url="https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/Level_III_Ecoregions_in_the_US_v1/FeatureServer/0",
        source_url="https://www.epa.gov/eco-research/level-iii-and-iv-ecoregions-continental-united-states",
        color="#65a9d4",
        code_fields=("US_L3CODE", "NA_L3CODE"),
        name_fields=("US_L3NAME", "NA_L3NAME"),
    ),
    "canada_ecozones": RegionLayer(
        id="canada_ecozones",
        label="Terrestrial Ecozones of Canada",
        system="AAFC Canada Ecozone",
        service_url="https://services.arcgis.com/lGOekm0RsNxYnT3j/ArcGIS/rest/services/National_ecological_framework_of_Canada_ecozones/FeatureServer/0",
        source_url="https://open.canada.ca/data/en/dataset/3ef8e8a9-8d05-4fea-a8bf-7f5023d2b6e1",
        color="#80b26d",
        code_fields=("ECOZONE_ID", "EZ_CODE", "ECONUM", "OBJECTID"),
        name_fields=("ECOZONE_NAME_EN", "ECOZONE_NAME", "EZ_NAME", "ENAME", "NAME"),
    ),
    "bc_agriculture_capability": RegionLayer(
        id="bc_agriculture_capability",
        label="BC Agriculture Capability Mapping",
        system="BC Agriculture Capability",
        service_url="",
        source_url="https://catalogue.data.gov.bc.ca/dataset/agriculture-capability-mapping",
        color="#cc9d45",
        code_fields=("code",),
        name_fields=("capability_summary", "capability_label"),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_BC_AG_CAP_DB_PATH",
            str(repo_path("data/derived/geo_layers/bc_agriculture_capability.sqlite3")),
        ),
        local_match_reason="Bundled OGL-BC polygon intersection",
        boundary=(
            "Legacy generalized capability mapping from the 1960s through 1990s. It does not establish "
            "crop-specific suitability, yield, required inputs, feasible improvements, current field condition, "
            "or field truth. Confirm with current local evidence before management decisions."
        ),
    ),
    "sk_thematic_soil": RegionLayer(
        id="sk_thematic_soil",
        label="Saskatchewan Thematic Soil Maps",
        system="AAFC Saskatchewan Thematic Soil",
        service_url="",
        source_url="https://open.canada.ca/data/en/dataset/ed36f4f3-2fb9-4241-8e29-6741e8b9e400",
        color="#6f8f70",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_SK_THEMATIC_SOIL_DB_PATH",
            str(repo_path("data/derived/geo_layers/sk_thematic_soil.sqlite3")),
        ),
        local_match_reason="Bundled OGL-Canada thematic-soil intersection",
        boundary=(
            "Dominant generalized thematic values derived from the Saskatchewan Detailed Soils Database. "
            "A polygon can contain variation and does not establish current field condition, an exact soil "
            "component at a point, crop-specific suitability, nutrient status, drainage performance, erosion "
            "outcome, or a management rate. Confirm with field observations, sampling, detailed survey evidence, "
            "and current Saskatchewan guidance."
        ),
    ),
    "ab_detailed_soil": RegionLayer(
        id="ab_detailed_soil",
        label="Alberta Detailed Soil Survey (DSS v3, 1:100,000)",
        system="AAFC Alberta Detailed Soil Survey",
        service_url="",
        source_url="https://sis.agr.gc.ca/cansis/nsdb/dss/v3/index.html",
        color="#7d876e",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_AB_DETAILED_SOIL_DB_PATH",
            str(repo_path("data/derived/geo_layers/ab_detailed_soil.sqlite3")),
        ),
        local_match_reason="Bundled OGL-Canada Alberta DSS v3 intersection",
        boundary=(
            "Historical DSS v3 soil-landscape mapping at 1:100,000 for Alberta's agricultural region. "
            "A polygon and its listed components are mapped priors, not proof of soil at a point or present "
            "nutrient supply, pH, drainage performance, compaction, salinity, crop suitability, or a management "
            "rate. Ground-truth mapped differences and use current soil tests and Alberta guidance."
        ),
    ),
    "mb_detailed_soil": RegionLayer(
        id="mb_detailed_soil",
        label="Manitoba Detailed Soil Survey (DSS v3, multiple scales)",
        system="AAFC Manitoba Detailed Soil Survey",
        service_url="",
        source_url="https://sis.agr.gc.ca/cansis/nsdb/dss/v3/index.html",
        color="#7d8875",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_MB_DETAILED_SOIL_DB_PATH",
            str(repo_path("data/derived/geo_layers/mb_detailed_soil.sqlite3")),
        ),
        local_match_reason="Bundled OGL-Canada Manitoba DSS v3 intersection",
        boundary=(
            "Historical stitched DSS v3 soil-landscape compilation at multiple published scales, concentrated "
            "in agricultural Manitoba with additional mapped areas. A polygon and its listed components are "
            "mapped priors, not proof of soil at a point or present nutrient supply, pH, drainage performance, "
            "compaction, salinity, crop suitability, or a management rate. Ground-truth mapped differences and "
            "use current soil tests and Manitoba guidance."
        ),
    ),
    "pei_detailed_soil": RegionLayer(
        id="pei_detailed_soil",
        label="PEI Detailed Soil Survey (1:75,000)",
        system="AAFC PEI Detailed Soil Survey",
        service_url="",
        source_url="https://open.canada.ca/data/en/dataset/7fa18ce7-6c14-438a-95c6-bb0906ddfb30",
        color="#7c8b72",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_PEI_DETAILED_SOIL_DB_PATH",
            str(repo_path("data/derived/geo_layers/pei_detailed_soil.sqlite3")),
        ),
        local_match_reason="Bundled OGL-Canada PEI detailed-soil intersection",
        boundary=(
            "Historical 1:75,000 soil-landscape mapping with linked map-unit components, soil names, and "
            "layer attributes. A polygon is a mapped prior, not proof of the soil at a point or of present "
            "nutrient supply, pH, drainage performance, compaction, erosion, crop suitability, or a management "
            "rate. Ground-truth mapped differences and use current soil tests and local guidance."
        ),
    ),
    "ns_pictou_detailed_soil": RegionLayer(
        id="ns_pictou_detailed_soil",
        label="Pictou County Detailed Soil Survey (1:50,000)",
        system="AAFC Nova Scotia Detailed Soil Survey",
        service_url="",
        source_url="https://open.canada.ca/data/en/dataset/083534ca-d5b0-46f5-b540-f3a706dbc2de",
        color="#667f8c",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_NS_PICTOU_DETAILED_SOIL_DB_PATH",
            str(repo_path("data/derived/geo_layers/ns_pictou_detailed_soil.sqlite3")),
        ),
        local_match_reason="Bundled OGL-Canada Pictou County detailed-soil intersection",
        boundary=(
            "Historical Version 1 soil-landscape mapping at 1:50,000 for Pictou County only; this is not "
            "province-wide Nova Scotia coverage. A polygon is a mapped prior, not proof of the soil at a point "
            "or of present nutrient supply, pH, drainage performance, compaction, erosion, crop suitability, "
            "or a management rate. Ground-truth mapped differences and use current soil tests and local guidance."
        ),
    ),
    "ca_soil_erosion_risk": RegionLayer(
        id="ca_soil_erosion_risk",
        label="AAFC Soil Erosion Risk 2021",
        system="AAFC Soil Erosion Risk",
        service_url="",
        source_url="https://open.canada.ca/data/en/dataset/b52b3c91-e0eb-47d1-aea5-fa5428254512",
        color="#df823f",
        code_fields=("code",),
        name_fields=("name",),
        query_backend="local_sqlite",
        local_database=os.getenv(
            "AGRONOMY_AGENT_CA_EROSION_RISK_DB_PATH",
            str(repo_path("data/derived/geo_layers/ca_soil_erosion_risk.sqlite3")),
        ),
        local_match_reason="Bundled OGL-Canada soil-erosion-risk intersection",
        boundary=(
            "AAFC modelled combined wind, water, and tillage erosion risk for agricultural Soil Landscapes "
            "of Canada through 2021. It is regional historical context, not current erosion observation, "
            "event prediction, measured field loss, field diagnosis, or management-prescription authority."
        ),
    ),
}


def layer_catalog(*, network_mode: str = "online") -> dict[str, Any]:
    _validate_network_mode(network_mode)
    return {
        "schema_version": GEO_SERVICE_SCHEMA_VERSION,
        "network_mode": network_mode,
        "layers": [
            {
                "id": layer.id,
                "label": layer.label,
                "system": layer.system,
                "source_url": layer.source_url,
                "color": layer.color,
                "source_mode": layer.query_backend,
                "available_in_current_mode": (
                    network_mode == "online" or layer.query_backend == "local_sqlite"
                ),
                "boundary": layer.boundary,
            }
            for layer in REGION_LAYERS.values()
        ],
    }


def parse_boundary_upload(*, filename: str, content_type: str | None, raw: bytes) -> dict[str, Any]:
    """Parse a public-demo field boundary upload into normalized WGS84 GeoJSON.

    This intentionally handles the common farm-field exchange formats without
    requiring GDAL in the local demo container. It supports GeoJSON, zipped
    shapefile point/polygon layers, and GeoPackage geometry tables using a
    small WKB reader. Coordinate reprojection is not attempted; uploads must
    already be WGS84 lon/lat.
    """

    safe_filename = Path(filename or "boundary").name
    if not raw:
        raise ValueError("boundary upload is empty")
    if len(raw) > MAX_BOUNDARY_UPLOAD_BYTES:
        raise ValueError("boundary upload exceeds 25 MB limit")

    suffix = Path(safe_filename).suffix.lower()
    if suffix in {".geojson", ".json"} or (content_type or "").lower() in {
        "application/geo+json",
        "application/json",
        "geojson",
    }:
        features = _parse_geojson_upload(raw)
        source_format = "geojson"
    elif suffix == ".zip":
        features = _parse_zipped_shapefile_upload(raw)
        source_format = "zipped_shapefile"
    elif suffix == ".shp":
        features = _parse_shapefile_bytes(raw, properties_by_record=[])
        source_format = "shapefile"
    elif suffix == ".gpkg":
        features = _parse_geopackage_upload(raw)
        source_format = "geopackage"
    else:
        raise ValueError("boundary upload must be GeoJSON, zipped shapefile, .shp, or GeoPackage")

    if not features:
        raise ValueError("boundary upload did not contain supported Point, Polygon, or MultiPolygon geometry")
    parsed_feature_count = len(features)
    truncated = parsed_feature_count > MAX_BOUNDARY_UPLOAD_FEATURES
    if truncated:
        features = features[:MAX_BOUNDARY_UPLOAD_FEATURES]

    primary_feature, primary_geometry = _primary_upload_feature(features)
    selected_feature_id = str(primary_feature.get("id") or "")
    bbox = _geometry_bbox(primary_geometry)
    acres = _geometry_area_acres(primary_geometry)
    warnings = _upload_warnings(
        source_format=source_format,
        parsed_feature_count=parsed_feature_count,
        retained_feature_count=len(features),
        primary_geometry=primary_geometry,
        truncated=truncated,
    )
    return {
        "schema_version": BOUNDARY_UPLOAD_SCHEMA_VERSION,
        "filename": safe_filename,
        "content_type": content_type or "application/octet-stream",
        "source_format": source_format,
        "feature_count": len(features),
        "parsed_feature_count": parsed_feature_count,
        "selected_feature_id": selected_feature_id,
        "geometry": primary_geometry,
        "geometry_type": primary_geometry["type"],
        "bbox": [round(value, 7) for value in bbox],
        "acres": round(acres, 2) if acres else 0,
        "feature_collection": {"type": "FeatureCollection", "features": features},
        "feature_summaries": _upload_feature_summaries(features, selected_feature_id=selected_feature_id),
        "warnings": warnings,
        "coordinate_reference": {
            "assumed": "EPSG:4326",
            "label": "WGS84 longitude/latitude",
            "reprojected": False,
        },
        "status_message": _upload_status_message(safe_filename, source_format, len(features), primary_geometry, acres),
        "boundary": (
            "Uploaded boundaries are treated as user-provided field context in WGS84 coordinates; "
            "they are not cadastral, legal, or surveyed acreage evidence."
        ),
    }


def query_region_layers(
    *,
    bbox: tuple[float, float, float, float],
    layer_ids: list[str] | None = None,
    network_mode: str = "online",
) -> dict[str, Any]:
    west, south, east, north = _validate_bbox(bbox)
    requested_layers = _selected_layers(layer_ids)
    layers, skipped_layers = _layers_for_network_mode(
        requested_layers,
        network_mode=network_mode,
    )
    features: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for layer in layers:
        try:
            collection = _query_layer(layer, geometry=_arcgis_envelope(west, south, east, north), geometry_type="esriGeometryEnvelope")
            features.extend(_normalize_feature_collection(collection, layer))
        except Exception as exc:  # pragma: no cover - network failures vary.
            errors.append({"layer_id": layer.id, "message": str(exc)})
    return {
        "schema_version": GEO_SERVICE_SCHEMA_VERSION,
        "query": {"bbox": [west, south, east, north], "mode": "viewport"},
        "layers": _layer_payload(layers),
        "skipped_layers": _skipped_layer_payload(skipped_layers),
        "feature_collection": {"type": "FeatureCollection", "features": features},
        "feature_count": len(features),
        "errors": errors,
        "source_mode": _source_mode(layers),
        "network_policy": _network_policy_payload(
            network_mode=network_mode,
            skipped_layers=skipped_layers,
        ),
    }


def intersect_region_layers(
    *,
    geometry: dict[str, Any],
    layer_ids: list[str] | None = None,
    network_mode: str = "online",
) -> dict[str, Any]:
    parsed_geometry = _validate_geojson_geometry(geometry)
    bbox = _geometry_bbox(parsed_geometry)
    west, south, east, north = _expanded_bbox(bbox)
    requested_layers = _selected_layers(layer_ids)
    layers, skipped_layers = _layers_for_network_mode(
        requested_layers,
        network_mode=network_mode,
    )
    offline_cache_key = (
        _offline_intersection_cache_key(parsed_geometry=parsed_geometry, layers=layers)
        if network_mode == "offline"
        else None
    )
    if offline_cache_key:
        cached = _offline_intersection_cache_get(offline_cache_key)
        if cached is not None:
            return cached
    features: list[dict[str, Any]] = []
    intersections: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for layer in layers:
        try:
            collection = _query_layer(layer, geometry=_arcgis_geometry(parsed_geometry), geometry_type=_arcgis_geometry_type(parsed_geometry))
            normalized = _normalize_feature_collection(collection, layer)
            features.extend(normalized)
            for feature in normalized:
                intersections.append(_intersection_record(feature=feature, layer=layer, input_geometry=parsed_geometry))
        except Exception as exc:  # pragma: no cover - network failures vary.
            errors.append({"layer_id": layer.id, "message": str(exc)})
    intersections.sort(key=lambda item: (item["confidence"], item["coverage_estimate"]), reverse=True)
    result = {
        "schema_version": GEO_SERVICE_SCHEMA_VERSION,
        "query": {"bbox": [west, south, east, north], "mode": "field_intersection"},
        "layers": _layer_payload(layers),
        "skipped_layers": _skipped_layer_payload(skipped_layers),
        "input_geometry": parsed_geometry,
        "intersections": intersections,
        "feature_collection": {"type": "FeatureCollection", "features": features},
        "feature_count": len(features),
        "errors": errors,
        "source_mode": _source_mode(layers),
        "network_policy": _network_policy_payload(
            network_mode=network_mode,
            skipped_layers=skipped_layers,
        ),
    }
    if offline_cache_key and not errors:
        _offline_intersection_cache_put(offline_cache_key, result)
    return result


def _offline_intersection_cache_key(
    *,
    parsed_geometry: dict[str, Any],
    layers: list[RegionLayer],
) -> str:
    layer_fingerprints: list[dict[str, Any]] = []
    for layer in layers:
        database = Path(str(layer.local_database or ""))
        try:
            stat = database.stat()
            database_identity: dict[str, Any] = {
                "path": str(database.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        except OSError:
            database_identity = {"path": str(database)}
        layer_fingerprints.append({"id": layer.id, "database": database_identity})
    payload = {
        "geometry": parsed_geometry,
        "layers": layer_fingerprints,
        "schema_version": GEO_SERVICE_SCHEMA_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _offline_intersection_cache_get(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _OFFLINE_INTERSECTION_CACHE_LOCK:
        cached = _OFFLINE_INTERSECTION_CACHE.get(key)
        if cached is None:
            return None
        created_at, result = cached
        if now - created_at > OFFLINE_INTERSECTION_CACHE_TTL_SECONDS:
            _OFFLINE_INTERSECTION_CACHE.pop(key, None)
            return None
        _OFFLINE_INTERSECTION_CACHE.move_to_end(key)
        return deepcopy(result)


def _offline_intersection_cache_put(key: str, result: dict[str, Any]) -> None:
    with _OFFLINE_INTERSECTION_CACHE_LOCK:
        _OFFLINE_INTERSECTION_CACHE[key] = (time.monotonic(), deepcopy(result))
        _OFFLINE_INTERSECTION_CACHE.move_to_end(key)
        while len(_OFFLINE_INTERSECTION_CACHE) > OFFLINE_INTERSECTION_CACHE_MAX_ENTRIES:
            _OFFLINE_INTERSECTION_CACHE.popitem(last=False)


def _clear_offline_intersection_cache() -> None:
    with _OFFLINE_INTERSECTION_CACHE_LOCK:
        _OFFLINE_INTERSECTION_CACHE.clear()


def attach_region_intersections_to_upload(
    parsed_upload: dict[str, Any],
    *,
    layer_ids: list[str] | None = None,
    network_mode: str = "online",
) -> dict[str, Any]:
    """Attach official regional polygon intersections to a parsed upload payload."""

    intersections = intersect_region_layers(
        geometry=parsed_upload["geometry"],
        layer_ids=layer_ids,
        network_mode=network_mode,
    )
    return {
        **parsed_upload,
        "regional_intersections": intersections["intersections"],
        "regional_feature_collection": intersections["feature_collection"],
        "geo_errors": intersections["errors"],
        "official_layer_status": official_layer_status(intersections),
        "regional_source_mode": intersections["source_mode"],
        "geo_network_policy": intersections["network_policy"],
    }


def _selected_layers(layer_ids: list[str] | None) -> list[RegionLayer]:
    if not layer_ids:
        return list(REGION_LAYERS.values())
    selected: list[RegionLayer] = []
    for layer_id in layer_ids:
        if layer_id not in REGION_LAYERS:
            raise ValueError(f"unknown geospatial layer: {layer_id}")
        selected.append(REGION_LAYERS[layer_id])
    return selected


def _validate_network_mode(network_mode: str) -> None:
    if network_mode not in {"online", "offline"}:
        raise ValueError("network_mode must be 'online' or 'offline'")


def _layers_for_network_mode(
    layers: list[RegionLayer],
    *,
    network_mode: str,
) -> tuple[list[RegionLayer], list[RegionLayer]]:
    _validate_network_mode(network_mode)
    if network_mode == "online":
        return layers, []
    return (
        [layer for layer in layers if layer.query_backend == "local_sqlite"],
        [layer for layer in layers if layer.query_backend != "local_sqlite"],
    )


def _skipped_layer_payload(layers: list[RegionLayer]) -> list[dict[str, Any]]:
    return [
        {
            **payload,
            "status": "blocked_offline",
            "reason": "offline_network_policy",
        }
        for payload in _layer_payload(layers)
    ]


def _network_policy_payload(
    *,
    network_mode: str,
    skipped_layers: list[RegionLayer],
) -> dict[str, Any]:
    return {
        "mode": network_mode,
        "external_calls_allowed": network_mode == "online",
        "external_requests_attempted": 0 if network_mode == "offline" else None,
        "remote_layers_skipped": len(skipped_layers),
        "boundary": (
            "Offline mode skips remote geospatial adapters before any request is made."
            if network_mode == "offline"
            else "Online mode may query configured official geospatial services."
        ),
    }


def _layer_payload(layers: list[RegionLayer]) -> list[dict[str, Any]]:
    return [
        {
            "id": layer.id,
            "label": layer.label,
            "system": layer.system,
            "source_url": layer.source_url,
            "color": layer.color,
            "source_mode": layer.query_backend,
            "boundary": layer.boundary,
        }
        for layer in layers
    ]


def _query_layer(layer: RegionLayer, *, geometry: str, geometry_type: str) -> dict[str, Any]:
    if layer.query_backend == "local_sqlite":
        return _query_local_sqlite_layer(layer, geometry=geometry, geometry_type=geometry_type)
    params = {
        "where": "1=1",
        "geometry": geometry,
        "geometryType": geometry_type,
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": "0.001",
        "geometryPrecision": "5",
        "resultRecordCount": str(MAX_FEATURES_PER_LAYER),
        "f": "geojson",
    }
    url = f"{layer.service_url}/query?{urlencode(params)}"
    return _fetch_json_cached(url)


def _source_mode(layers: list[RegionLayer]) -> str:
    modes = {layer.query_backend for layer in layers}
    if not modes:
        return "no_geospatial_layers_available_in_current_mode"
    if modes == {"arcgis_feature_service"}:
        return "official_arcgis_feature_services"
    if modes == {"local_sqlite"}:
        return "bundled_official_geospatial_layers"
    return "hybrid_official_remote_and_bundled_layers"


def _query_local_sqlite_layer(layer: RegionLayer, *, geometry: str, geometry_type: str) -> dict[str, Any]:
    database = Path(str(layer.local_database or ""))
    if not database.is_file():
        raise FileNotFoundError(f"bundled layer database is missing: {database}")
    query_geometry, bbox = _local_query_geometry(geometry=geometry, geometry_type=geometry_type)
    west, south, east, north = bbox
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata = {
            str(row["key"]): json.loads(str(row["value_json"]))
            for row in connection.execute("SELECT key, value_json FROM metadata").fetchall()
        }
        feature_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(features)").fetchall()
        }
        if {"properties_zlib", "geometry_zlib"} <= feature_columns:
            payload_columns = "f.properties_zlib, f.geometry_zlib"
            compressed_payloads = True
        elif {"properties_json", "geometry_json"} <= feature_columns:
            payload_columns = "f.properties_json, f.geometry_json"
            compressed_payloads = False
        else:
            raise ValueError("bundled layer has no supported feature payload encoding")
        rows = connection.execute(
            f"""
            SELECT f.fid, f.code, f.name, {payload_columns}
            FROM feature_bounds AS bounds
            JOIN features AS f ON f.fid = bounds.fid
            WHERE bounds.max_lon >= ? AND bounds.min_lon <= ?
              AND bounds.max_lat >= ? AND bounds.min_lat <= ?
            ORDER BY f.fid
            LIMIT ?
            """,
            (west, east, south, north, MAX_FEATURES_PER_LAYER * 8),
        ).fetchall()
    finally:
        connection.close()

    features: list[dict[str, Any]] = []
    for row in rows:
        if compressed_payloads:
            region_geometry = json.loads(zlib.decompress(bytes(row["geometry_zlib"])).decode("utf-8"))
            properties = json.loads(zlib.decompress(bytes(row["properties_zlib"])).decode("utf-8"))
        else:
            region_geometry = json.loads(str(row["geometry_json"]))
            properties = json.loads(str(row["properties_json"]))
        if query_geometry is not None and not _geometries_intersect(query_geometry, region_geometry):
            continue
        properties.setdefault("source_scale_range", metadata.get("source_scale_range"))
        properties.setdefault("source_scale_note", metadata.get("source_scale_note"))
        properties.setdefault("source_attribution", metadata.get("attribution"))
        properties.update({"code": str(row["code"]), "name": str(row["name"])})
        features.append(
            {
                "type": "Feature",
                "id": int(row["fid"]),
                "geometry": region_geometry,
                "properties": properties,
            }
        )
        if len(features) >= MAX_FEATURES_PER_LAYER:
            break
    return {"type": "FeatureCollection", "features": features}


def _local_query_geometry(*, geometry: str, geometry_type: str) -> tuple[dict[str, Any] | None, tuple[float, float, float, float]]:
    if geometry_type == "esriGeometryEnvelope":
        values = tuple(float(value) for value in geometry.split(","))
        if len(values) != 4:
            raise ValueError("local layer envelope must contain four coordinates")
        return None, _validate_bbox(values)
    payload = json.loads(geometry)
    if geometry_type == "esriGeometryPoint":
        parsed = _validate_geojson_geometry({"type": "Point", "coordinates": [payload["x"], payload["y"]]})
    elif geometry_type == "esriGeometryPolygon":
        parsed = _validate_geojson_geometry({"type": "Polygon", "coordinates": payload["rings"]})
    else:
        raise ValueError(f"unsupported local layer geometry type: {geometry_type}")
    return parsed, _geometry_bbox(parsed)


def _fetch_json_cached(url: str) -> dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < 86_400:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    request = Request(url, headers={"User-Agent": "OpenAgronomyAgent/0.1 geospatial-proxy"})
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        payload = response.read().decode("utf-8")
    loaded = json.loads(payload)
    if isinstance(loaded, dict) and loaded.get("error"):
        raise ValueError(str(loaded["error"]))
    cache_path.write_text(json.dumps(loaded), encoding="utf-8")
    return loaded


def _normalize_feature_collection(collection: dict[str, Any], layer: RegionLayer) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, feature in enumerate(collection.get("features") or []):
        if not isinstance(feature, dict) or not feature.get("geometry"):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        raw_code = _first_property(properties, layer.code_fields) or str(feature.get("id") or index)
        name = _first_property(properties, layer.name_fields) or layer.label
        code = _normalize_code(layer, raw_code)
        feature_color = str(properties.get("style_color") or layer.color)
        normalized.append(
            {
                "type": "Feature",
                "id": f"{layer.id}:{code}:{feature.get('id', index)}",
                "geometry": feature["geometry"],
                "properties": {
                    **properties,
                    "layer_id": layer.id,
                    "layer_label": layer.label,
                    "system": layer.system,
                    "code": code,
                    "name": name,
                    "label": name,
                    "source_url": layer.source_url,
                    "stroke": feature_color,
                    "fill": feature_color,
                },
            }
        )
    return normalized


def _intersection_record(*, feature: dict[str, Any], layer: RegionLayer, input_geometry: dict[str, Any]) -> dict[str, Any]:
    properties = feature["properties"]
    coverage = _coverage_estimate(input_geometry, feature["geometry"])
    record = {
        "layer_id": layer.id,
        "layer_label": layer.label,
        "system": layer.system,
        "code": properties["code"],
        "name": properties["name"],
        "label": properties["label"],
        "source_url": layer.source_url,
        "confidence": 0.94 if coverage >= 0.5 else 0.82,
        "coverage_estimate": coverage,
        "match_reason": (
            layer.local_match_reason
            if layer.query_backend == "local_sqlite"
            else "Official ArcGIS FeatureServer spatial intersection"
        ),
        "source": (
            "bundled_official_geospatial_layer"
            if layer.query_backend == "local_sqlite"
            else "official_arcgis_feature_service"
        ),
        "boundary": layer.boundary,
    }
    for key in (
        "capability_label",
        "improved_capability_label",
        "primary_class",
        "components",
        "source_scale",
        "source_scale_label",
        "source_scale_range",
        "capability_summary",
        "polygon_comment",
        "source_scale_note",
        "map_unit",
        "map_name",
        "map_key",
        "hectares",
        "dominant_components",
        "mapping_basis",
        "drainage_class",
        "capability_class",
        "capability_interpretation",
        "erosion_risk",
        "erosion_indicator_2021",
        "erosion_risk_1981",
        "erosion_indicator_1981",
        "erosion_change_1981_2021",
        "erosion_change_indicator",
        "erosion_summary",
        "soil_landscape_id",
        "source_year",
        "publication_year",
        "coverage_area",
        "slope_class",
        "surface_texture_group",
        "salinity_class",
        "salinity_class_source_value",
        "management_limitations",
        "soil_summary",
    ):
        if properties.get(key) not in (None, "", []):
            record[key] = properties[key]
    return record


def _first_property(properties: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = properties.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _normalize_code(layer: RegionLayer, raw_code: str) -> str:
    code = raw_code.strip()
    if layer.id == "nrcs_mlra" and not code.startswith("MLRA_"):
        return f"MLRA_{code}"
    return code


def _validate_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    west, south, east, north = bbox
    values = [west, south, east, north]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("bbox must contain finite numbers")
    if west >= east or south >= north:
        raise ValueError("bbox must be west,south,east,north")
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError("bbox coordinates are outside WGS84 bounds")
    if east - west > MAX_BBOX_SPAN_DEGREES or north - south > MAX_BBOX_SPAN_DEGREES:
        raise ValueError(f"bbox span must be {MAX_BBOX_SPAN_DEGREES} degrees or less")
    return west, south, east, north


def _expanded_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    west, south, east, north = bbox
    pad = max(0.01, min(0.1, max(east - west, north - south) * 0.2))
    return _validate_bbox((west - pad, south - pad, east + pad, north + pad))


def _arcgis_envelope(west: float, south: float, east: float, north: float) -> str:
    return f"{west},{south},{east},{north}"


def _arcgis_geometry(geometry: dict[str, Any]) -> str:
    if geometry["type"] == "Point":
        lon, lat = geometry["coordinates"][:2]
        return json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}, separators=(",", ":"))
    if geometry["type"] == "Polygon":
        return json.dumps({"rings": geometry["coordinates"], "spatialReference": {"wkid": 4326}}, separators=(",", ":"))
    if geometry["type"] == "MultiPolygon":
        rings: list[list[list[float]]] = []
        for polygon in geometry["coordinates"]:
            rings.extend(polygon)
        return json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}, separators=(",", ":"))
    raise ValueError(f"unsupported geometry type: {geometry['type']}")


def _arcgis_geometry_type(geometry: dict[str, Any]) -> str:
    return "esriGeometryPoint" if geometry["type"] == "Point" else "esriGeometryPolygon"


def _validate_geojson_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a GeoJSON geometry object")
    geometry_type = geometry.get("type")
    if geometry_type == "Feature":
        inner = geometry.get("geometry")
        if not isinstance(inner, dict):
            raise ValueError("feature geometry is required")
        return _validate_geojson_geometry(inner)
    if geometry_type == "Point":
        point = _validate_position(geometry.get("coordinates"))
        return {"type": "Point", "coordinates": point}
    if geometry_type == "Polygon":
        rings = _validate_polygon_coordinates(geometry.get("coordinates"))
        return {"type": "Polygon", "coordinates": rings}
    if geometry_type == "MultiPolygon":
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("multipolygon coordinates are required")
        return {"type": "MultiPolygon", "coordinates": [_validate_polygon_coordinates(polygon) for polygon in coordinates]}
    raise ValueError("geometry type must be Point, Polygon, MultiPolygon, or Feature")


def validate_geojson_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize user-supplied WGS84 field geometry."""

    return _validate_geojson_geometry(geometry)


def geometry_bbox(
    geometry: dict[str, Any],
) -> tuple[float, float, float, float]:
    """Return the WGS84 bounding box for validated point or polygon geometry."""

    return _geometry_bbox(_validate_geojson_geometry(geometry))


def geometries_intersect(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    """Return whether two validated WGS84 point/polygon geometries intersect."""

    return _geometries_intersect(
        _validate_geojson_geometry(left),
        _validate_geojson_geometry(right),
    )


def _validate_polygon_coordinates(coordinates: Any) -> list[list[list[float]]]:
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("polygon coordinates are required")
    rings: list[list[list[float]]] = []
    for ring in coordinates:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValueError("polygon rings must contain at least four positions")
        positions = [_validate_position(position) for position in ring]
        if positions[0] != positions[-1]:
            positions.append(positions[0])
        if _ring_self_intersects(positions):
            raise ValueError("polygon rings must not self-intersect")
        if abs(_signed_ring_area(positions)) <= 1e-12:
            raise ValueError("polygon rings must enclose a non-zero area")
        rings.append(positions)
    return rings


def _signed_ring_area(ring: list[list[float]]) -> float:
    return sum(
        ring[index][0] * ring[index + 1][1] - ring[index + 1][0] * ring[index][1]
        for index in range(len(ring) - 1)
    ) / 2


def _ring_self_intersects(ring: list[list[float]]) -> bool:
    segment_count = len(ring) - 1
    for left in range(segment_count):
        for right in range(left + 1, segment_count):
            if abs(left - right) <= 1 or (left == 0 and right == segment_count - 1):
                continue
            if _segments_intersect(ring[left], ring[left + 1], ring[right], ring[right + 1]):
                return True
    return False


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    epsilon = 1e-12

    def orient(start: list[float], end: list[float], point: list[float]) -> float:
        return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])

    def on_segment(start: list[float], end: list[float], point: list[float]) -> bool:
        return (
            abs(orient(start, end, point)) <= epsilon
            and min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
        )

    ab_c = orient(a, b, c)
    ab_d = orient(a, b, d)
    cd_a = orient(c, d, a)
    cd_b = orient(c, d, b)
    proper = (
        ((ab_c > epsilon and ab_d < -epsilon) or (ab_c < -epsilon and ab_d > epsilon))
        and ((cd_a > epsilon and cd_b < -epsilon) or (cd_a < -epsilon and cd_b > epsilon))
    )
    return proper or on_segment(a, b, c) or on_segment(a, b, d) or on_segment(c, d, a) or on_segment(c, d, b)


def _validate_position(position: Any) -> list[float]:
    if not isinstance(position, list) or len(position) < 2:
        raise ValueError("position must be [longitude, latitude]")
    lon = float(position[0])
    lat = float(position[1])
    if not math.isfinite(lon) or not math.isfinite(lat):
        raise ValueError("position coordinates must be finite")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError(WGS84_REPROJECT_UPLOAD_ERROR)
    return [lon, lat]


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    positions = list(_iter_positions(geometry))
    west = min(position[0] for position in positions)
    south = min(position[1] for position in positions)
    east = max(position[0] for position in positions)
    north = max(position[1] for position in positions)
    if west == east:
        west -= 0.01
        east += 0.01
    if south == north:
        south -= 0.01
        north += 0.01
    return west, south, east, north


def _iter_positions(geometry: dict[str, Any]) -> Any:
    if geometry["type"] == "Point":
        yield geometry["coordinates"]
    elif geometry["type"] == "Polygon":
        for ring in geometry["coordinates"]:
            yield from ring
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            for ring in polygon:
                yield from ring


def _coverage_estimate(input_geometry: dict[str, Any], region_geometry: dict[str, Any]) -> float:
    if input_geometry["type"] == "Point":
        return 1.0 if _point_in_geometry(input_geometry["coordinates"], region_geometry) else 0.0
    sample_points = _sample_points(input_geometry)
    if not sample_points:
        return 0.0
    hits = sum(1 for point in sample_points if _point_in_geometry(point, region_geometry))
    return round(hits / len(sample_points), 3)


def _sample_points(geometry: dict[str, Any]) -> list[list[float]]:
    rings: list[list[list[float]]] = []
    if geometry["type"] == "Polygon":
        rings = geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    points: list[list[float]] = []
    for ring in rings[:2]:
        open_ring = ring[:-1] if ring and ring[0] == ring[-1] else ring
        points.extend(open_ring)
        for index, point in enumerate(open_ring):
            next_point = open_ring[(index + 1) % len(open_ring)]
            points.append([(point[0] + next_point[0]) / 2, (point[1] + next_point[1]) / 2])
        points.append(_ring_centroid(open_ring))
    return points[:60]


def _ring_centroid(ring: list[list[float]]) -> list[float]:
    return [sum(point[0] for point in ring) / len(ring), sum(point[1] for point in ring) / len(ring)]


def _point_in_geometry(point: list[float], geometry: dict[str, Any]) -> bool:
    if geometry.get("type") == "Polygon":
        return _point_in_polygon(point, geometry["coordinates"])
    if geometry.get("type") == "MultiPolygon":
        return any(_point_in_polygon(point, polygon) for polygon in geometry["coordinates"])
    return False


def _geometries_intersect(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("type") == "Point":
        return _point_in_geometry(left["coordinates"], right)
    if right.get("type") == "Point":
        return _point_in_geometry(right["coordinates"], left)
    left_bbox = _geometry_bbox(left)
    right_bbox = _geometry_bbox(right)
    if (
        left_bbox[2] < right_bbox[0]
        or left_bbox[0] > right_bbox[2]
        or left_bbox[3] < right_bbox[1]
        or left_bbox[1] > right_bbox[3]
    ):
        return False
    if any(_point_in_geometry(point, right) for point in _sample_points(left)):
        return True
    if any(_point_in_geometry(point, left) for point in _sample_points(right)):
        return True
    for left_ring in _outer_rings(left):
        for right_ring in _outer_rings(right):
            for left_start, left_end in _ring_segments(left_ring):
                for right_start, right_end in _ring_segments(right_ring):
                    if _segments_intersect(left_start, left_end, right_start, right_end):
                        return True
    return False


def _outer_rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        coordinates = geometry.get("coordinates") or []
        return [coordinates[0]] if coordinates else []
    if geometry.get("type") == "MultiPolygon":
        return [polygon[0] for polygon in geometry.get("coordinates") or [] if polygon]
    return []


def _ring_segments(ring: list[list[float]]) -> list[tuple[list[float], list[float]]]:
    if len(ring) < 2:
        return []
    closed = ring if ring[0] == ring[-1] else [*ring, ring[0]]
    return list(zip(closed, closed[1:]))


def _point_in_polygon(point: list[float], rings: list[list[list[float]]]) -> bool:
    if not rings or not _point_in_ring(point, rings[0]):
        return False
    return not any(_point_in_ring(point, hole) for hole in rings[1:])


def _point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    j = len(ring) - 1
    for i, current in enumerate(ring):
        xi, yi = current
        xj, yj = ring[j]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def _parse_geojson_upload(raw: bytes) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError("GeoJSON upload must be UTF-8 text") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("GeoJSON upload is not valid JSON") from exc
    return _features_from_geojson_like(parsed, source_format="geojson")


def _features_from_geojson_like(parsed: Any, *, source_format: str) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    if not isinstance(parsed, dict):
        raise ValueError("GeoJSON root must be an object")
    root_type = parsed.get("type")
    if root_type == "FeatureCollection":
        for index, feature in enumerate(parsed.get("features") or []):
            features.extend(_features_from_geojson_feature(feature, index=index, source_format=source_format))
        return features
    if root_type == "Feature":
        return _features_from_geojson_feature(parsed, index=0, source_format=source_format)
    geometry = _validate_geojson_geometry(parsed)
    return [_upload_feature(geometry, {}, index=0, source_format=source_format)]


def _features_from_geojson_feature(feature: Any, *, index: int, source_format: str) -> list[dict[str, Any]]:
    if not isinstance(feature, dict):
        return []
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return []
    try:
        normalized = _validate_geojson_geometry(geometry)
    except ValueError as exc:
        if _is_upload_coordinate_error(exc):
            raise
        return []
    properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return [_upload_feature(normalized, _json_safe_properties(properties), index=index, source_format=source_format)]


def _parse_zipped_shapefile_upload(raw: bytes) -> list[dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("zip upload is not a valid zip archive") from exc
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ValueError(f"zip upload must contain {MAX_ZIP_MEMBERS} files or fewer")
    for info in infos:
        if info.file_size > MAX_ZIP_MEMBER_BYTES:
            raise ValueError("zip member exceeds boundary upload size limit")
    shp_members = [info for info in infos if info.filename.lower().endswith(".shp") and not info.is_dir()]
    if not shp_members:
        raise ValueError("zipped shapefile upload must contain a .shp member")
    shp_info = sorted(shp_members, key=lambda item: item.filename)[0]
    base = shp_info.filename.rsplit(".", 1)[0].lower()
    dbf_info = next((info for info in infos if info.filename.lower() == f"{base}.dbf"), None)
    properties_by_record = _parse_dbf_bytes(archive.read(dbf_info)) if dbf_info else []
    return _parse_shapefile_bytes(archive.read(shp_info), properties_by_record=properties_by_record)


def _parse_shapefile_bytes(raw: bytes, *, properties_by_record: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(raw) < 100:
        raise ValueError("shapefile .shp content is too small")
    try:
        file_code = struct.unpack(">i", raw[0:4])[0]
        version = struct.unpack("<i", raw[28:32])[0]
    except struct.error as exc:
        raise ValueError("shapefile header is malformed") from exc
    if file_code != 9994 or version != 1000:
        raise ValueError("shapefile header is not recognized")
    features: list[dict[str, Any]] = []
    offset = 100
    record_index = 0
    while offset + 8 <= len(raw) and len(features) < MAX_BOUNDARY_UPLOAD_FEATURES:
        try:
            _record_number, content_words = struct.unpack(">ii", raw[offset : offset + 8])
        except struct.error as exc:
            raise ValueError("shapefile record header is malformed") from exc
        offset += 8
        content_length = content_words * 2
        content = raw[offset : offset + content_length]
        offset += content_length
        if len(content) < 4:
            continue
        geometry = _parse_shapefile_record_geometry(content)
        if not geometry:
            record_index += 1
            continue
        properties = properties_by_record[record_index] if record_index < len(properties_by_record) else {}
        features.append(_upload_feature(geometry, properties, index=record_index, source_format="shapefile"))
        record_index += 1
    return features


def _parse_shapefile_record_geometry(content: bytes) -> dict[str, Any] | None:
    shape_type = struct.unpack("<i", content[0:4])[0]
    if shape_type == 0:
        return None
    if shape_type in {1, 11, 21}:
        if len(content) < 20:
            return None
        x, y = struct.unpack("<dd", content[4:20])
        return _validate_geojson_geometry({"type": "Point", "coordinates": [x, y]})
    if shape_type in {5, 15, 25}:
        if len(content) < 44:
            return None
        num_parts, num_points = struct.unpack("<ii", content[36:44])
        if num_parts <= 0 or num_points <= 0:
            return None
        parts_offset = 44
        points_offset = parts_offset + num_parts * 4
        if len(content) < points_offset + num_points * 16:
            return None
        parts = list(struct.unpack(f"<{num_parts}i", content[parts_offset:points_offset]))
        points: list[list[float]] = []
        for index in range(num_points):
            start = points_offset + index * 16
            x, y = struct.unpack("<dd", content[start : start + 16])
            points.append([x, y])
        rings: list[list[list[float]]] = []
        for part_index, start_index in enumerate(parts):
            end_index = parts[part_index + 1] if part_index + 1 < len(parts) else len(points)
            ring = points[start_index:end_index]
            if len(ring) >= 3:
                if ring[0] != ring[-1]:
                    ring = [*ring, ring[0]]
                rings.append(ring)
        if not rings:
            return None
        return _validate_geojson_geometry({"type": "Polygon", "coordinates": rings})
    return None


def _parse_dbf_bytes(raw: bytes) -> list[dict[str, Any]]:
    if len(raw) < 33:
        return []
    record_count = struct.unpack("<I", raw[4:8])[0]
    header_length = struct.unpack("<H", raw[8:10])[0]
    record_length = struct.unpack("<H", raw[10:12])[0]
    fields: list[dict[str, Any]] = []
    offset = 32
    while offset + 32 <= min(header_length, len(raw)) and raw[offset] != 0x0D:
        descriptor = raw[offset : offset + 32]
        name = descriptor[0:11].split(b"\x00", 1)[0].decode("latin-1", errors="ignore").strip()
        field_type = chr(descriptor[11])
        length = int(descriptor[16])
        decimal_count = int(descriptor[17])
        if name:
            fields.append({"name": name, "type": field_type, "length": length, "decimal_count": decimal_count})
        offset += 32
    records: list[dict[str, Any]] = []
    offset = header_length
    for _ in range(min(record_count, MAX_BOUNDARY_UPLOAD_FEATURES)):
        if offset + record_length > len(raw):
            break
        record = raw[offset : offset + record_length]
        offset += record_length
        if not record or record[0:1] == b"*":
            records.append({})
            continue
        cursor = 1
        properties: dict[str, Any] = {}
        for field in fields:
            length = int(field["length"])
            raw_value = record[cursor : cursor + length]
            cursor += length
            text = raw_value.decode("latin-1", errors="ignore").strip()
            if text == "":
                properties[str(field["name"])] = None
            elif field["type"] in {"N", "F"}:
                properties[str(field["name"])] = _parse_dbf_number(text, int(field["decimal_count"]))
            elif field["type"] == "L":
                properties[str(field["name"])] = text.upper() in {"Y", "T"}
            else:
                properties[str(field["name"])] = text
        records.append(properties)
    return records


def _parse_dbf_number(text: str, decimal_count: int) -> int | float | str:
    try:
        return float(text) if decimal_count else int(text)
    except ValueError:
        return text


def _parse_geopackage_upload(raw: bytes) -> list[dict[str, Any]]:
    with tempfile.NamedTemporaryFile(prefix="open-agronomy-boundary-", suffix=".gpkg") as handle:
        handle.write(raw)
        handle.flush()
        connection = sqlite3.connect(handle.name)
        connection.row_factory = sqlite3.Row
        try:
            geometry_columns = _geopackage_geometry_columns(connection)
            if not geometry_columns:
                raise ValueError("GeoPackage does not advertise geometry columns")
            features: list[dict[str, Any]] = []
            for table_name, geometry_column in geometry_columns:
                features.extend(_read_geopackage_features(connection, table_name, geometry_column))
                if len(features) >= MAX_BOUNDARY_UPLOAD_FEATURES:
                    break
            return features[:MAX_BOUNDARY_UPLOAD_FEATURES]
        finally:
            connection.close()


def _geopackage_geometry_columns(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        "SELECT table_name, column_name FROM gpkg_geometry_columns ORDER BY table_name"
    ).fetchall()
    columns: list[tuple[str, str]] = []
    for row in rows:
        table = str(row["table_name"])
        column = str(row["column_name"])
        if _sqlite_identifier_exists(connection, table, column):
            columns.append((table, column))
    return columns


def _sqlite_identifier_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    try:
        columns = connection.execute(f"PRAGMA table_info({_quote_sql_identifier(table_name)})").fetchall()
    except sqlite3.DatabaseError:
        return False
    return any(str(row["name"]) == column_name for row in columns)


def _read_geopackage_features(
    connection: sqlite3.Connection,
    table_name: str,
    geometry_column: str,
) -> list[dict[str, Any]]:
    table_sql = _quote_sql_identifier(table_name)
    rows = connection.execute(f"SELECT * FROM {table_sql} LIMIT ?", (MAX_BOUNDARY_UPLOAD_FEATURES,)).fetchall()
    features: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        geometry_blob = row[geometry_column]
        if not isinstance(geometry_blob, (bytes, bytearray, memoryview)):
            continue
        try:
            geometry = _parse_geopackage_geometry(bytes(geometry_blob))
        except ValueError as exc:
            if _is_upload_coordinate_error(exc):
                raise
            continue
        properties = {
            key: _json_safe_value(row[key])
            for key in row.keys()
            if key != geometry_column and _json_safe_value(row[key]) is not None
        }
        properties.setdefault("gpkg_table", table_name)
        features.append(_upload_feature(geometry, properties, index=index, source_format="geopackage"))
    return features


def _quote_sql_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _parse_geopackage_geometry(blob: bytes) -> dict[str, Any]:
    if blob.startswith(b"GP"):
        if len(blob) < 8:
            raise ValueError("GeoPackage geometry blob is too short")
        flags = blob[3]
        endian = "<" if flags & 0x01 else ">"
        envelope_code = (flags >> 1) & 0x07
        envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_code)
        if envelope_bytes is None:
            raise ValueError("GeoPackage envelope code is unsupported")
        start = 8 + envelope_bytes
        if start >= len(blob):
            raise ValueError("GeoPackage geometry blob has no WKB payload")
        return _validate_geojson_geometry(_parse_wkb_geometry(blob[start:], endian_hint=endian)[0])
    return _validate_geojson_geometry(_parse_wkb_geometry(blob, endian_hint=None)[0])


def _parse_wkb_geometry(blob: bytes, *, offset: int = 0, endian_hint: str | None = None) -> tuple[dict[str, Any], int]:
    if offset + 5 > len(blob):
        raise ValueError("WKB geometry is truncated")
    byte_order = blob[offset]
    endian = "<" if byte_order == 1 else ">" if byte_order == 0 else endian_hint
    if endian is None:
        raise ValueError("WKB byte order is invalid")
    type_raw = struct.unpack(endian + "I", blob[offset + 1 : offset + 5])[0]
    geometry_type, dimensions, has_srid = _normalize_wkb_type(type_raw)
    cursor = offset + 5
    if has_srid:
        cursor += 4
    if geometry_type == 1:
        coordinates, cursor = _read_wkb_position(blob, cursor, endian=endian, dimensions=dimensions)
        return {"type": "Point", "coordinates": coordinates}, cursor
    if geometry_type == 2:
        count = _read_wkb_count(blob, cursor, endian=endian)
        cursor += 4
        line: list[list[float]] = []
        for _ in range(count):
            position, cursor = _read_wkb_position(blob, cursor, endian=endian, dimensions=dimensions)
            line.append(position)
        if len(line) < 2:
            raise ValueError("WKB linestring requires at least two positions")
        return {"type": "LineString", "coordinates": line}, cursor
    if geometry_type == 3:
        ring_count = _read_wkb_count(blob, cursor, endian=endian)
        cursor += 4
        rings: list[list[list[float]]] = []
        for _ in range(ring_count):
            point_count = _read_wkb_count(blob, cursor, endian=endian)
            cursor += 4
            ring: list[list[float]] = []
            for _ in range(point_count):
                position, cursor = _read_wkb_position(blob, cursor, endian=endian, dimensions=dimensions)
                ring.append(position)
            rings.append(ring)
        return {"type": "Polygon", "coordinates": rings}, cursor
    if geometry_type in {4, 5, 6, 7}:
        count = _read_wkb_count(blob, cursor, endian=endian)
        cursor += 4
        geometries: list[dict[str, Any]] = []
        for _ in range(count):
            geometry, cursor = _parse_wkb_geometry(blob, offset=cursor, endian_hint=endian)
            geometries.append(geometry)
        if geometry_type == 6:
            polygons = [geometry["coordinates"] for geometry in geometries if geometry.get("type") == "Polygon"]
            return {"type": "MultiPolygon", "coordinates": polygons}, cursor
        if geometry_type == 4:
            points = [geometry["coordinates"] for geometry in geometries if geometry.get("type") == "Point"]
            return {"type": "MultiPoint", "coordinates": points}, cursor
        if geometry_type == 5:
            lines = [geometry["coordinates"] for geometry in geometries if geometry.get("type") == "LineString"]
            return {"type": "MultiLineString", "coordinates": lines}, cursor
        return {"type": "GeometryCollection", "geometries": geometries}, cursor
    raise ValueError(f"unsupported WKB geometry type: {geometry_type}")


def _normalize_wkb_type(type_raw: int) -> tuple[int, int, bool]:
    has_z = bool(type_raw & 0x80000000)
    has_m = bool(type_raw & 0x40000000)
    has_srid = bool(type_raw & 0x20000000)
    type_code = type_raw & 0x1FFFFFFF
    dimensions = 2 + int(has_z) + int(has_m)
    if 3000 <= type_code < 4000:
        return type_code - 3000, 4, has_srid
    if 2000 <= type_code < 3000:
        return type_code - 2000, 3, has_srid
    if 1000 <= type_code < 2000:
        return type_code - 1000, 3, has_srid
    return type_code, dimensions, has_srid


def _read_wkb_count(blob: bytes, offset: int, *, endian: str) -> int:
    if offset + 4 > len(blob):
        raise ValueError("WKB count is truncated")
    return struct.unpack(endian + "I", blob[offset : offset + 4])[0]


def _read_wkb_position(blob: bytes, offset: int, *, endian: str, dimensions: int) -> tuple[list[float], int]:
    byte_count = dimensions * 8
    if offset + byte_count > len(blob):
        raise ValueError("WKB coordinate is truncated")
    values = struct.unpack(endian + ("d" * dimensions), blob[offset : offset + byte_count])
    return [float(values[0]), float(values[1])], offset + byte_count


def _upload_feature(
    geometry: dict[str, Any],
    properties: dict[str, Any],
    *,
    index: int,
    source_format: str,
) -> dict[str, Any]:
    normalized = _normalize_upload_geometry(geometry)
    return {
        "type": "Feature",
        "id": f"{source_format}:{index}",
        "geometry": normalized,
        "properties": {
            **_json_safe_properties(properties),
            "upload_source_format": source_format,
            "upload_feature_index": index,
        },
    }


def _normalize_upload_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    geometry_type = geometry.get("type")
    if geometry_type in {"Point", "Polygon", "MultiPolygon"}:
        return _validate_geojson_geometry(geometry)
    if geometry_type == "MultiPoint":
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, list) and coordinates:
            return _validate_geojson_geometry({"type": "Point", "coordinates": coordinates[0]})
    if geometry_type == "GeometryCollection":
        for candidate in geometry.get("geometries") or []:
            try:
                return _normalize_upload_geometry(candidate)
            except ValueError as exc:
                if _is_upload_coordinate_error(exc):
                    raise
                continue
    raise ValueError("uploaded geometry must contain Point, Polygon, or MultiPolygon geometry")


def _is_upload_coordinate_error(exc: ValueError) -> bool:
    text = str(exc)
    return (
        "WGS84 longitude/latitude" in text
        or "outside WGS84 bounds" in text
        or "position coordinates must be finite" in text
        or "position must be [longitude, latitude]" in text
        or "polygon coordinates are required" in text
        or "polygon rings must contain at least four positions" in text
        or "multipolygon coordinates are required" in text
    )


def _primary_upload_feature(features: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    best_feature: dict[str, Any] | None = None
    best_geometry: dict[str, Any] | None = None
    best_area = -1.0
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        for candidate in _polygon_upload_candidates(geometry):
            area = _geometry_area_acres(candidate)
            if area > best_area:
                best_feature = feature
                best_geometry = candidate
                best_area = area
    if best_feature and best_geometry:
        return best_feature, best_geometry
    for feature in features:
        geometry = feature.get("geometry")
        if isinstance(geometry, dict) and geometry.get("type") == "Point":
            return feature, geometry
    raise ValueError("boundary upload did not contain a usable field polygon or point")


def _polygon_upload_candidates(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    if geometry.get("type") == "Polygon":
        return [geometry]
    if geometry.get("type") == "MultiPolygon":
        return [
            {"type": "Polygon", "coordinates": polygon}
            for polygon in geometry.get("coordinates", [])
            if polygon
        ]
    return []


def _upload_feature_summaries(features: list[dict[str, Any]], *, selected_feature_id: str) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        feature_id = str(feature.get("id") or f"upload:{index}")
        bbox = _geometry_bbox(geometry)
        acres = _geometry_area_acres(geometry)
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        summaries.append(
            {
                "id": feature_id,
                "label": _upload_feature_label(properties, index=index),
                "geometry_type": str(geometry.get("type") or "Geometry"),
                "bbox": [round(value, 7) for value in bbox],
                "acres": round(acres, 2) if acres else 0,
                "selected": feature_id == selected_feature_id,
                "properties": properties,
            }
        )
    return summaries


def _upload_feature_label(properties: dict[str, Any], *, index: int) -> str:
    label = _first_property(properties, UPLOAD_LABEL_FIELDS)
    return label or f"Uploaded feature {index + 1}"


def _upload_warnings(
    *,
    source_format: str,
    parsed_feature_count: int,
    retained_feature_count: int,
    primary_geometry: dict[str, Any],
    truncated: bool,
) -> list[str]:
    warnings = [
        (
            "Coordinates were interpreted as WGS84 longitude/latitude (EPSG:4326); "
            "reproject UTM, State Plane, or local grid boundaries before upload."
        )
    ]
    if source_format in {"zipped_shapefile", "shapefile", "geopackage"}:
        warnings.append("Projection metadata is not transformed in the local parser; coordinates must already be lon/lat.")
    if parsed_feature_count > 1:
        warnings.append(
            f"{parsed_feature_count} upload features were detected; the largest polygon or first point was selected by default."
        )
    if truncated:
        warnings.append(
            f"Only the first {retained_feature_count} features were retained from {parsed_feature_count} parsed features."
        )
    if primary_geometry["type"] == "Point":
        warnings.append("A point can seed regional priors, but field-specific acreage and edge effects need a drawn or uploaded polygon.")
    return warnings


def official_layer_status(intersections: dict[str, Any]) -> list[dict[str, Any]]:
    errors_by_layer = {str(error.get("layer_id")): str(error.get("message")) for error in intersections.get("errors", [])}
    counts: dict[str, int] = {}
    for item in intersections.get("intersections", []):
        layer_id = str(item.get("layer_id") or "")
        counts[layer_id] = counts.get(layer_id, 0) + 1
    status: list[dict[str, Any]] = []
    for layer in intersections.get("layers", []):
        layer_id = str(layer.get("id") or "")
        matched_count = counts.get(layer_id, 0)
        error_message = errors_by_layer.get(layer_id)
        status.append(
            {
                "layer_id": layer_id,
                "label": layer.get("label") or layer_id,
                "system": layer.get("system") or layer_id,
                "source_url": layer.get("source_url"),
                "status": "matched" if matched_count else "error" if error_message else "no_match",
                "match_count": matched_count,
                "message": error_message or ("matched official polygon" if matched_count else "no polygon intersected the field geometry"),
            }
        )
    for layer in intersections.get("skipped_layers", []):
        layer_id = str(layer.get("id") or "")
        status.append(
            {
                "layer_id": layer_id,
                "label": layer.get("label") or layer_id,
                "system": layer.get("system") or layer_id,
                "source_url": layer.get("source_url"),
                "status": "blocked_offline",
                "match_count": 0,
                "message": "remote layer skipped before request because runtime network mode is offline",
            }
        )
    return status


def _geometry_area_acres(geometry: dict[str, Any]) -> float:
    if geometry["type"] == "Point":
        return 0.0
    if geometry["type"] == "Polygon":
        return max(0.0, _ring_area_acres(geometry["coordinates"][0]) - sum(_ring_area_acres(ring) for ring in geometry["coordinates"][1:]))
    if geometry["type"] == "MultiPolygon":
        return sum(_geometry_area_acres({"type": "Polygon", "coordinates": polygon}) for polygon in geometry["coordinates"])
    return 0.0


def _ring_area_acres(ring: list[list[float]]) -> float:
    open_ring = ring[:-1] if ring and ring[0] == ring[-1] else ring
    if len(open_ring) < 3:
        return 0.0
    mean_lat = sum(point[1] for point in open_ring) / len(open_ring)
    meters_per_degree_lat = 111_320
    meters_per_degree_lon = math.cos((mean_lat * math.pi) / 180) * 111_320
    projected = [(point[0] * meters_per_degree_lon, point[1] * meters_per_degree_lat) for point in open_ring]
    square_meters = abs(
        sum(
            point[0] * projected[(index + 1) % len(projected)][1]
            - projected[(index + 1) % len(projected)][0] * point[1]
            for index, point in enumerate(projected)
        )
        / 2
    )
    return square_meters / 4046.8564224


def _upload_status_message(filename: str, source_format: str, feature_count: int, geometry: dict[str, Any], acres: float) -> str:
    if geometry["type"] == "Point":
        return f"{filename} loaded as a point boundary source ({source_format}, {feature_count} feature{'s' if feature_count != 1 else ''})."
    return (
        f"{filename} loaded ({source_format}, {feature_count} feature{'s' if feature_count != 1 else ''}); "
        f"using primary field polygon at approximately {round(acres):,} acres."
    )


def _json_safe_properties(properties: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in properties.items():
        safe_value = _json_safe_value(value)
        if safe_value is not None:
            cleaned[str(key)] = safe_value
    return cleaned


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
