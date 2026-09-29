from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import zlib
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agronomy_agent.paths import repo_path
from agronomy_agent.geospatial.geometry import canonical_geometry, geodesic_metrics
from agronomy_agent.geospatial.vector_io import read_vector_upload


GEO_SERVICE_SCHEMA_VERSION = "open_agronomy_agent.geo_service.v1"
BOUNDARY_UPLOAD_SCHEMA_VERSION = "open_agronomy_agent.boundary_upload.v1"
CACHE_DIR = repo_path(os.getenv("AGRONOMY_AGENT_GEO_CACHE_DIR", "data/derived/geo_cache"))
HTTP_TIMEOUT_SECONDS = 25
MAX_FEATURES_PER_LAYER = 80
MAX_BBOX_SPAN_DEGREES = 12.0
OFFLINE_INTERSECTION_CACHE_TTL_SECONDS = 300
OFFLINE_INTERSECTION_CACHE_MAX_ENTRIES = 8
_OFFLINE_INTERSECTION_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_OFFLINE_INTERSECTION_CACHE_LOCK = threading.Lock()
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


def _local_database_path(*, environment_variable: str, filename: str) -> str:
    explicit = os.getenv(environment_variable)
    if explicit:
        return explicit
    spatial_pack_root = os.getenv("AGRONOMY_AGENT_SPATIAL_PACK_ROOT")
    if spatial_pack_root:
        return str(Path(spatial_pack_root).expanduser() / filename)
    return str(repo_path(f"data/derived/geo_layers/{filename}"))


def _local_layer_installed(layer: RegionLayer) -> bool:
    return layer.query_backend == "local_sqlite" and Path(str(layer.local_database or "")).is_file()


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
    "ca_statcan_2021_provinces_territories": RegionLayer(
        id="ca_statcan_2021_provinces_territories",
        label="Statistics Canada Provinces and Territories (2021 Census)",
        system="Statistics Canada 2021 Census geography",
        service_url="",
        source_url="https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21",
        color="#667f94",
        code_fields=("code",),
        name_fields=("province_name",),
        query_backend="local_sqlite",
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_CA_STATCAN_2021_PR_DB_PATH",
            filename="ca_statcan_2021_provinces_territories.sqlite3",
        ),
        local_match_reason="Installed Statistics Canada 2021 cartographic-boundary intersection",
        boundary=(
            "A 2021 Census cartographic boundary for geographic orientation and source routing. It is not a "
            "surveyed farm boundary, proof of legal land location or jurisdiction, crop-production evidence, "
            "current field condition, or management authorization."
        ),
    ),
    "ca_statcan_2021_census_agricultural_regions": RegionLayer(
        id="ca_statcan_2021_census_agricultural_regions",
        label="Statistics Canada Census Agricultural Regions (2021 Census)",
        system="Statistics Canada 2021 Census agricultural geography",
        service_url="",
        source_url="https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21",
        color="#849668",
        code_fields=("code",),
        name_fields=("census_agricultural_region",),
        query_backend="local_sqlite",
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_CA_STATCAN_2021_CAR_DB_PATH",
            filename="ca_statcan_2021_census_agricultural_regions.sqlite3",
        ),
        local_match_reason="Installed Statistics Canada 2021 Census Agricultural Region intersection",
        boundary=(
            "A 2021 Census statistical dissemination geography for organizing region-tagged evidence. It is not "
            "an agronomic management zone, a field boundary, proof of crop production or farm practice, or "
            "authority for a field-specific recommendation."
        ),
    ),
    "ca_aafc_terrestrial_ecoregions_v2_2": RegionLayer(
        id="ca_aafc_terrestrial_ecoregions_v2_2",
        label="AAFC Terrestrial Ecoregions of Canada (v2.2)",
        system="AAFC National Ecological Framework",
        service_url="",
        source_url="https://open.canada.ca/data/en/dataset/ade80d26-61f5-439e-8966-73b352811fe6",
        color="#80b26d",
        code_fields=("code",),
        name_fields=("ecoregion",),
        query_backend="local_sqlite",
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_CA_AAFC_ECOREGION_DB_PATH",
            filename="ca_aafc_terrestrial_ecoregions_v2_2.sqlite3",
        ),
        local_match_reason="Installed AAFC National Ecological Framework ecoregion intersection",
        boundary=(
            "A National Ecological Framework ecoregion is broad ecological context for organizing evidence by "
            "regional climate, physiography, vegetation, soil, water, and fauna. It is not a current field "
            "observation, a soil test, a crop-suitability decision, a diagnosis, or management-rate authority."
        ),
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_BC_AG_CAP_DB_PATH",
            filename="bc_agriculture_capability.sqlite3",
        ),
        local_match_reason="Bundled OGL-BC polygon intersection",
        boundary=(
            "Legacy generalized capability mapping from the 1960s through 1990s. It does not establish "
            "crop-specific suitability, yield, required inputs, feasible improvements, current field condition, "
            "or field truth. Confirm with current local evidence before management decisions."
        ),
    ),
    "sk_detailed_soil": RegionLayer(
        id="sk_detailed_soil",
        label="Saskatchewan Detailed Soil Survey (DSS v3, 1:100,000)",
        system="AAFC Saskatchewan Detailed Soil Survey",
        service_url="",
        source_url="https://open.canada.ca/data/en/dataset/3734623c-25c5-4e69-936d-26f764a2807f",
        color="#637d68",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_SK_DETAILED_SOIL_DB_PATH",
            filename="sk_detailed_soil.sqlite3",
        ),
        local_match_reason="Installed OGL-Canada Saskatchewan DSS v3 intersection",
        boundary=(
            "Historical 1:100,000 soil-landscape mapping for nearly all agricultural areas in southern "
            "Saskatchewan. A polygon and its listed components are mapped priors, not proof of soil at a "
            "point or present nutrient supply, pH, drainage performance, compaction, salinity, crop "
            "suitability, or a management rate. Ground-truth mapped differences and use current soil tests "
            "and Saskatchewan guidance."
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_SK_THEMATIC_SOIL_DB_PATH",
            filename="sk_thematic_soil.sqlite3",
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_AB_DETAILED_SOIL_DB_PATH",
            filename="ab_detailed_soil.sqlite3",
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_MB_DETAILED_SOIL_DB_PATH",
            filename="mb_detailed_soil.sqlite3",
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_PEI_DETAILED_SOIL_DB_PATH",
            filename="pei_detailed_soil.sqlite3",
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_NS_PICTOU_DETAILED_SOIL_DB_PATH",
            filename="ns_pictou_detailed_soil.sqlite3",
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
        local_database=_local_database_path(
            environment_variable="AGRONOMY_AGENT_CA_EROSION_RISK_DB_PATH",
            filename="ca_soil_erosion_risk.sqlite3",
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
                    network_mode == "online"
                    if layer.query_backend != "local_sqlite"
                    else _local_layer_installed(layer)
                ),
                "installation_status": (
                    "installed"
                    if _local_layer_installed(layer)
                    else "not_installed"
                    if layer.query_backend == "local_sqlite"
                    else "remote"
                ),
                "local_asset": Path(str(layer.local_database or "")).name
                if layer.query_backend == "local_sqlite"
                else None,
                "boundary": layer.boundary,
            }
            for layer in REGION_LAYERS.values()
        ],
    }


def parse_boundary_upload(*, filename: str, content_type: str | None, raw: bytes) -> dict[str, Any]:
    """Read bounded vector bytes with explicit CRS and no lost topology.

    The current field editor supports points and single-ring polygons. Complex
    topology remains available in vector_io and must be explicitly rejected here
    until the editor can round-trip it without dropping holes or members.
    """
    safe_filename = Path(filename or "boundary").name
    imported = read_vector_upload(filename=safe_filename, raw=raw, content_type=content_type)
    source_format = imported["source_format"]
    features = [
        _upload_feature(feature["geometry"], {
            **feature["properties"],
            "upload_source_layer": feature["source_layer"],
            "upload_source_feature_index": feature["source_feature_index"],
        }, index=index, source_format=source_format)
        for index, feature in enumerate(imported["features"])
    ]
    if any(feature["geometry"]["type"] == "MultiPolygon" or (
        feature["geometry"]["type"] == "Polygon" and len(feature["geometry"]["coordinates"]) > 1
    ) for feature in features):
        raise ValueError("The field editor currently supports only points and single-ring polygons; "
                         "this upload contains multipart geometry or holes. No components were dropped. "
                         "Prepare an explicitly selected simple field boundary in a GIS tool before import.")

    parsed_feature_count = len(features)

    primary_feature, primary_geometry = _primary_upload_feature(features)
    selected_feature_id = str(primary_feature.get("id") or "")
    bbox = _geometry_bbox(primary_geometry)
    acres = _geometry_area_acres(primary_geometry)
    warnings = _upload_warnings(
        parsed_feature_count=parsed_feature_count,
        primary_geometry=primary_geometry,
    )
    return {
        "schema_version": BOUNDARY_UPLOAD_SCHEMA_VERSION,
        "filename": safe_filename,
        "content_type": content_type or "application/octet-stream",
        "source_format": source_format,
        "import_receipt": {key: imported[key] for key in ("schema_version", "source_sha256", "source_bytes")},
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
        "coordinate_reference": imported["coordinate_reference"],
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
    source_collection_status: list[dict[str, Any]] = []
    for layer in layers:
        try:
            if layer.query_backend == "local_sqlite":
                collection = _query_layer(layer, geometry=_arcgis_envelope(*bbox), geometry_type="esriGeometryEnvelope")
                if isinstance(collection, dict) and isinstance(collection.get("features"), list):
                    candidates = collection["features"]
                    selected = []
                    for feature in candidates:
                        try:
                            if _geometries_intersect(parsed_geometry, feature["geometry"]):
                                selected.append(feature)
                        except (ValueError, TypeError, KeyError):
                            selected.append(feature)  # Preserve invalid-source accounting.
                    collection = {**collection, "features": selected}
            else:
                collection = _query_layer(layer, geometry=_arcgis_geometry(parsed_geometry), geometry_type=_arcgis_geometry_type(parsed_geometry))
            source_collection_status.append(_source_collection_status(collection, layer_id=layer.id))
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
        "source_collection_status": source_collection_status,
        "source_mode": _source_mode(layers),
        "network_policy": _network_policy_payload(
            network_mode=network_mode,
            skipped_layers=skipped_layers,
        ),
    }
    if offline_cache_key and not errors:
        _offline_intersection_cache_put(offline_cache_key, result)
    return result


def _source_collection_status(collection: Any, *, layer_id: str) -> dict[str, Any]:
    """Retain raw completeness signals lost during feature normalization.

    This does not change the existing provider request or normalized results.
    The bounded analysis consumer can distinguish true empty coverage from a
    malformed or transfer-limited source response.
    """
    valid = (
        isinstance(collection, dict)
        and collection.get("type") == "FeatureCollection"
        and isinstance(collection.get("features"), list)
    )
    if not valid:
        return {
            "layer_id": layer_id,
            "valid": False,
            "raw_feature_count": None,
            "invalid_feature_count": None,
            "exceeded_transfer_limit": None,
        }
    raw_features = collection["features"]
    invalid_count = sum(
        not isinstance(feature, dict)
        or feature.get("type") != "Feature"
        or not isinstance(feature.get("geometry"), dict)
        or not isinstance(feature.get("properties"), dict)
        for feature in raw_features
    )
    transfer = collection.get("exceededTransferLimit")
    return {
        "layer_id": layer_id,
        "valid": isinstance(transfer, bool) or transfer is None,
        "raw_feature_count": len(raw_features),
        "invalid_feature_count": invalid_count,
        "exceeded_transfer_limit": transfer if isinstance(transfer, bool) else None,
    }


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
        selected = [
            layer
            for layer in REGION_LAYERS.values()
            if layer.query_backend != "local_sqlite" or _local_layer_installed(layer)
        ]
        selected_ids = {layer.id for layer in selected}
        if "sk_detailed_soil" in selected_ids and "sk_thematic_soil" in selected_ids:
            selected = [layer for layer in selected if layer.id != "sk_thematic_soil"]
        return selected
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
    return {
        "type": "FeatureCollection", "features": features,
        "exceededTransferLimit": len(rows) >= MAX_FEATURES_PER_LAYER * 8 or len(features) >= MAX_FEATURES_PER_LAYER,
    }


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
        "coverage_method": "WGS84 geodesic intersection area / complete input area; point uses polygon covers",
        "confidence_kind": "heuristic_not_calibrated",
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
        "province_uid",
        "province_name",
        "province_abbreviation",
        "census_agricultural_region_code",
        "census_agricultural_region",
        "ecoregion_id",
        "ecoregion",
        "ecozone_id",
        "ecoprovince_id",
        "dissemination_geography_id",
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
    if geometry["type"] in {"Polygon", "MultiPolygon"}:
        from shapely.geometry import shape, mapping
        from shapely.geometry.polygon import orient
        parsed = shape(canonical_geometry(geometry))
        polygons = [parsed] if parsed.geom_type == "Polygon" else parsed.geoms
        rings = [ring for polygon in polygons for ring in mapping(orient(polygon, sign=-1.0))["coordinates"]]
        return json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}, separators=(",", ":"))
    raise ValueError(f"unsupported geometry type: {geometry['type']}")


def _arcgis_geometry_type(geometry: dict[str, Any]) -> str:
    return "esriGeometryPoint" if geometry["type"] == "Point" else "esriGeometryPolygon"


def _validate_geojson_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    return canonical_geometry(geometry)


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
    from shapely.geometry import shape
    field = shape(canonical_geometry(input_geometry))
    region = shape(canonical_geometry(region_geometry, max_vertices=20_000))
    if field.geom_type == "Point":
        return 1.0 if region.covers(field) else 0.0
    total = geodesic_metrics(field)["area_m2"]
    covered = geodesic_metrics(field.intersection(region))["area_m2"]
    return round(min(1.0, max(0.0, covered / total)), 6)


def _geometries_intersect(left: dict[str, Any], right: dict[str, Any]) -> bool:
    from shapely.geometry import shape
    return bool(shape(canonical_geometry(left, max_vertices=20_000)).intersects(
        shape(canonical_geometry(right, max_vertices=20_000))))


def _upload_feature(
    geometry: dict[str, Any],
    properties: dict[str, Any],
    *,
    index: int,
    source_format: str,
) -> dict[str, Any]:
    normalized = canonical_geometry(geometry)
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
    return [geometry] if geometry.get("type") in {"Polygon", "MultiPolygon"} else []


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
    parsed_feature_count: int,
    primary_geometry: dict[str, Any],
) -> list[str]:
    warnings = ["Coordinates are validated as WGS84 longitude/latitude (EPSG:4326); "
                "the coordinate_reference receipt records original CRS and any reprojection."]
    if parsed_feature_count > 1:
        warnings.append(
            f"{parsed_feature_count} upload features were detected; the largest polygon or first point was selected by default."
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
    return geodesic_metrics(geometry)["area_m2"] / 4046.8564224


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
