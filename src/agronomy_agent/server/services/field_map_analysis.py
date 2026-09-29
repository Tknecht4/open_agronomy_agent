"""Bounded, deterministic field geometry and official mapped-zone analysis.

The result is context from source polygons, never a field observation or survey.
Spatial libraries are imported only when an analysis is requested.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from agronomy_agent.server.services import geospatial_service as geo
from agronomy_agent.geospatial.geometry import checked_positions as _checked_positions, geodesic_metrics


SCHEMA_VERSION = "open_agronomy_agent.field_map_analysis.v1"
MAX_LAYERS = 4
MAX_REQUEST_BYTES = 128 * 1024
MAX_INPUT_VERTICES = 1024
MAX_SOURCE_VERTICES = 20_000
MAX_ZONES_SHOWN = 10
ACRES_PER_HECTARE = 2.471053814671653


def _empty_layer(layer: Any, status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "layer_id": layer.id,
        "label": layer.label,
        "source_url": layer.source_url,
        "source_mode": layer.query_backend,
        "boundary": layer.boundary,
        "coverage_method": "WGS84 geodesic area of field clipped to union of returned source polygons",
        "uncertainty": "Mapped source geometry and scale limit precision; remote geometry may be generalized.",
        "status": status,
        "reason": reason,
        "feature_count": None,
        "processed_feature_count": None,
        "source_exceeded_transfer_limit": None,
        "incomplete_reasons": [],
        "covered_area_ha": None,
        "coverage_fraction": None,
        "zones": [],
        "omitted_zone_count": 0,
        "elapsed_ms": None,
    }


def _record_incomplete(item: dict[str, Any], reason: str) -> None:
    item["status"] = "partial"
    if reason not in item["incomplete_reasons"]:
        item["incomplete_reasons"].append(reason)
    if item["reason"] is None:
        item["reason"] = reason


def _local_candidate_limit_reached(layer: Any, geometry: dict[str, Any]) -> bool:
    """Detect the adapter's 8x feature candidate scan cap for installed packs."""
    path = Path(str(layer.local_database or ""))
    if layer.query_backend != "local_sqlite" or not path.is_file():
        return False
    west, south, east, north = geo.geometry_bbox(geometry)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT 1 FROM feature_bounds WHERE max_lon >= ? AND min_lon <= ? "
            "AND max_lat >= ? AND min_lat <= ? LIMIT 1 OFFSET ?",
            (west, east, south, north, geo.MAX_FEATURES_PER_LAYER * 8 - 1),
        ).fetchone() is not None


def _load_layer_features(
    layer: Any, geometry: dict[str, Any], network_mode: str
) -> tuple[list[dict[str, Any]] | None, int | None, list[str], bool | None]:
    """Use a raw envelope only for installed local packs; keep remote egress unchanged."""
    if layer.query_backend == "local_sqlite":
        bounds = geo.geometry_bbox(geometry)
        raw = geo._query_layer(
            layer, geometry=geo._arcgis_envelope(*bounds), geometry_type="esriGeometryEnvelope"
        )
        if (not isinstance(raw, dict) or raw.get("type") != "FeatureCollection"
            or not isinstance(raw.get("features"), list)):
            return None, None, ["malformed_source_collection"], None
        raw_features = raw["features"]
        transfer = raw.get("exceededTransferLimit")
        reasons: list[str] = []
        if transfer is True:
            reasons.append("source_transfer_limit_reached")
        elif transfer is not None and transfer is not False:
            reasons.append("malformed_source_transfer_flag")
        if len(raw_features) >= geo.MAX_FEATURES_PER_LAYER:
            reasons.append("source_feature_limit_reached")
        valid_raw: list[dict[str, Any]] = []
        for feature in raw_features[:geo.MAX_FEATURES_PER_LAYER]:
            if (not isinstance(feature, dict) or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)
                or not isinstance(feature.get("geometry"), dict)):
                if "malformed_source_feature" not in reasons:
                    reasons.append("malformed_source_feature")
                continue
            valid_raw.append(feature)
        normalized = geo._normalize_feature_collection(
            {"type": "FeatureCollection", "features": valid_raw}, layer
        )
        if len(normalized) != len(valid_raw) and "malformed_source_feature" not in reasons:
            reasons.append("malformed_source_feature")
        return normalized, len(raw_features), reasons, transfer if isinstance(transfer, bool) else None

    # This is the existing field-intersection adapter and its existing egress.
    # Completeness metadata is inspected before its normalized subset can be
    # promoted to a complete area statistic.
    source = geo.intersect_region_layers(
        geometry=geometry, layer_ids=[layer.id], network_mode=network_mode
    )
    if not isinstance(source, dict) or source.get("errors"):
        return None, None, ["source_query_failed"], None
    collection = source.get("feature_collection")
    if not isinstance(collection, dict) or not isinstance(collection.get("features"), list):
        return None, None, ["malformed_source_collection"], None
    features = collection["features"]
    statuses = source.get("source_collection_status")
    status = next(
        (row for row in statuses if isinstance(row, dict) and row.get("layer_id") == layer.id),
        None,
    ) if isinstance(statuses, list) else None
    if not isinstance(status, dict) or status.get("valid") is not True:
        return None, None, ["malformed_source_collection"], None
    raw_count = status.get("raw_feature_count")
    invalid_count = status.get("invalid_feature_count")
    transfer = status.get("exceeded_transfer_limit")
    if type(raw_count) is not int or type(invalid_count) is not int or raw_count < 0 or invalid_count < 0:
        return None, None, ["malformed_source_collection"], None
    reasons = []
    if transfer is True:
        reasons.append("source_transfer_limit_reached")
    if invalid_count:
        reasons.append("malformed_source_feature")
    if raw_count >= geo.MAX_FEATURES_PER_LAYER or len(features) >= geo.MAX_FEATURES_PER_LAYER:
        reasons.append("source_feature_limit_reached")
    if raw_count - invalid_count != len(features):
        reasons.append("source_normalization_incomplete")
    return features[:geo.MAX_FEATURES_PER_LAYER], raw_count, reasons, transfer


def analyze_field_map(
    *, geometry: dict[str, Any], layer_ids: list[str], network_mode: str = "online"
) -> dict[str, Any]:
    started = time.monotonic()
    if not isinstance(layer_ids, list) or len(layer_ids) > MAX_LAYERS:
        raise ValueError("layers must name 0 to 4 explicit catalog layers")
    if any(not isinstance(layer_id, str) or layer_id not in geo.REGION_LAYERS for layer_id in layer_ids):
        raise ValueError("layers contains an unknown geospatial layer")
    if len(set(layer_ids)) != len(layer_ids):
        raise ValueError("layers must not contain duplicates")
    geo._validate_network_mode(network_mode)
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Point", "Polygon", "MultiPolygon"}:
        raise ValueError("geometry must be a GeoJSON Point, Polygon, or MultiPolygon")
    if len(json.dumps(geometry, separators=(",", ":")).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("geometry exceeds 128 KiB limit")
    _checked_positions(geometry, maximum=MAX_INPUT_VERTICES, label="geometry")
    parsed = geometry
    raw_bounds = geo._geometry_bbox(parsed)
    # The official adapters use ordinary WGS84 envelopes and cannot represent a wrap.
    if raw_bounds[2] - raw_bounds[0] >= 180:
        raise ValueError("antimeridian-crossing geometry is unsupported")
    if raw_bounds[2] - raw_bounds[0] > 12 or raw_bounds[3] - raw_bounds[1] > 12:
        raise ValueError("geometry span exceeds 12 degrees")

    layers = [geo.REGION_LAYERS[layer_id] for layer_id in layer_ids]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "geometry": {
            "type": parsed["type"],
            "status": "unavailable",
            "area_ha": None,
            "area_ac": None,
            "perimeter_m": None,
            "location": None,
            "method": "WGS84 ellipsoid geodesic area/perimeter; representative point for polygons",
        },
        "layers": [],
        "network_policy": {
            "mode": network_mode,
            "external_calls_allowed": network_mode == "online",
            "external_requests_attempted": 0 if network_mode == "offline" else None,
        },
        "limits": {
            "max_layers": MAX_LAYERS,
            "max_request_bytes": MAX_REQUEST_BYTES,
            "max_input_vertices": MAX_INPUT_VERTICES,
            "max_source_vertices": MAX_SOURCE_VERTICES,
            "max_features_per_layer": geo.MAX_FEATURES_PER_LAYER,
            "max_zones_shown": MAX_ZONES_SHOWN,
            "remote_timeout_seconds_per_layer": geo.HTTP_TIMEOUT_SECONDS,
        },
        "elapsed_ms": None,
        "warnings": ["Mapped context is not a field measurement, survey, or current management recommendation."],
    }
    try:
        import pyproj  # noqa: F401 - explicit optional dependency readiness check
        from shapely.geometry import shape
        from shapely.ops import unary_union
    except ImportError:
        result["layers"] = [_empty_layer(layer, "unavailable", "spatial_dependencies_missing") for layer in layers]
        result["warnings"].append("Install the supported runtime requirements to enable field analysis.")
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        return result

    parsed = geo.validate_geojson_geometry(parsed)
    field_shape = shape(parsed)
    metrics = geodesic_metrics(field_shape)
    area_m2, perimeter_m = metrics["area_m2"], metrics["perimeter_m"]
    location = metrics["representative_point"]
    result["geometry"].update(
        status="complete",
        area_ha=round(area_m2 / 10_000, 6) if parsed["type"] != "Point" else None,
        area_ac=round(area_m2 / 10_000 * ACRES_PER_HECTARE, 6) if parsed["type"] != "Point" else None,
        perimeter_m=round(perimeter_m, 3) if parsed["type"] != "Point" else None,
        location={"longitude": round(location["longitude"], 7), "latitude": round(location["latitude"], 7)},
    )

    # Query each requested layer independently so failures and feature caps remain
    # attached to their source. The adapter enforces the active network policy.
    for layer in layers:
        layer_started = time.monotonic()
        if network_mode == "offline" and layer.query_backend != "local_sqlite":
            blocked = _empty_layer(layer, "blocked_offline", "offline_network_policy")
            blocked["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
            result["layers"].append(blocked)
            continue
        if layer.query_backend == "local_sqlite" and not geo._local_layer_installed(layer):
            missing = _empty_layer(layer, "not_installed", "local_layer_not_installed")
            missing["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
            result["layers"].append(missing)
            continue
        item = _empty_layer(layer, "unavailable")
        try:
            if _local_candidate_limit_reached(layer, parsed):
                item["status"] = "partial"
                item["reason"] = "source_candidate_limit_reached"
                item["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
                result["layers"].append(item)
                continue
            features, feature_count, incomplete, transfer = _load_layer_features(
                layer, parsed, network_mode
            )
            item["feature_count"] = feature_count
            item["source_exceeded_transfer_limit"] = transfer
            item["incomplete_reasons"] = incomplete
            if features is None:
                item["reason"] = incomplete[0]
                result["warnings"].append(f"{layer.label}: source query or collection unavailable.")
                item["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
                result["layers"].append(item)
                continue
            item["processed_feature_count"] = len(features)
            vertex_total = 0
            checked_features: list[dict[str, Any]] = []
            for feature in features:
                source_geometry = feature.get("geometry") if isinstance(feature, dict) else None
                if not isinstance(source_geometry, dict) or source_geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                    if "malformed_source_feature" not in incomplete:
                        incomplete.append("malformed_source_feature")
                    continue
                try:
                    source_vertices = _checked_positions(
                        source_geometry, maximum=MAX_SOURCE_VERTICES, label="source geometry"
                    )
                except ValueError as exc:
                    reason = "source_vertex_limit_reached" if "exceeds" in str(exc) else "malformed_source_feature"
                    if reason not in incomplete:
                        incomplete.append(reason)
                    continue
                vertex_total += source_vertices
                if vertex_total > MAX_SOURCE_VERTICES:
                    if "source_vertex_limit_reached" not in incomplete:
                        incomplete.append("source_vertex_limit_reached")
                    break
                checked_features.append(feature)
            features = checked_features
            item["processed_feature_count"] = len(features)
            item["status"] = "partial" if incomplete else "complete"
            item["reason"] = incomplete[0] if incomplete else None
            if "source_vertex_limit_reached" in incomplete:
                item["status"] = "partial"
                item["reason"] = "source_vertex_limit_reached"
                item["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
                result["layers"].append(item)
                continue
            if parsed["type"] == "Point":
                matched_zones = []
                for feature in features:
                    try:
                        region_shape = shape(feature["geometry"])
                    except (TypeError, ValueError, KeyError):
                        _record_incomplete(item, "invalid_source_geometry")
                        continue
                    if (region_shape.is_empty or not region_shape.is_valid
                        or region_shape.geom_type not in {"Polygon", "MultiPolygon"}
                        or region_shape.bounds[2] - region_shape.bounds[0] >= 180):
                        _record_incomplete(item, "invalid_source_geometry")
                        continue
                    if not region_shape.covers(field_shape):
                        continue
                    properties = feature.get("properties") or {}
                    matched_zones.append({
                        "code": str(properties.get("code") or ""),
                        "name": str(properties.get("name") or ""),
                        "area_ha": None,
                        "fraction_of_field": None,
                    })
                item["zones"] = matched_zones[:MAX_ZONES_SHOWN]
                item["omitted_zone_count"] = max(0, len(matched_zones) - MAX_ZONES_SHOWN)
                item["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
                result["layers"].append(item)
                continue
            clipped_by_zone: dict[tuple[str, str], list[Any]] = defaultdict(list)
            all_clipped: list[Any] = []
            for feature in features:
                try:
                    region_shape = shape(feature["geometry"])
                except (TypeError, ValueError, KeyError):
                    _record_incomplete(item, "invalid_source_geometry")
                    continue
                if (region_shape.is_empty or not region_shape.is_valid
                    or region_shape.geom_type not in {"Polygon", "MultiPolygon"}
                    or region_shape.bounds[2] - region_shape.bounds[0] >= 180):
                    _record_incomplete(item, "invalid_source_geometry")
                    continue
                clipped = field_shape.intersection(region_shape)
                if clipped.is_empty:
                    continue
                properties = feature.get("properties") or {}
                key = (str(properties.get("code") or ""), str(properties.get("name") or ""))
                clipped_by_zone[key].append(clipped)
                all_clipped.append(clipped)
            # A capped or invalid source leaves unknown coverage; showing a
            # numeric fraction would misrepresent it as a complete layer.
            if item["status"] == "complete":
                covered_m2 = geodesic_metrics(unary_union(all_clipped))["area_m2"] if all_clipped else 0.0
                item["covered_area_ha"] = round(covered_m2 / 10_000, 6)
                item["coverage_fraction"] = round(min(1.0, covered_m2 / area_m2), 6)
            zones = []
            for (code, name), pieces in clipped_by_zone.items():
                zone_m2 = geodesic_metrics(unary_union(pieces))["area_m2"]
                zones.append({
                    "code": code,
                    "name": name,
                    "area_ha": round(zone_m2 / 10_000, 6),
                    "fraction_of_field": round(min(1.0, zone_m2 / area_m2), 6),
                })
            zones.sort(key=lambda zone: zone["area_ha"], reverse=True)
            if item["status"] != "complete":
                for zone in zones:
                    zone["area_ha"] = None
                    zone["fraction_of_field"] = None
            item["zones"] = zones[:MAX_ZONES_SHOWN]
            item["omitted_zone_count"] = max(0, len(zones) - MAX_ZONES_SHOWN)
        except Exception as exc:
            item["status"] = "unavailable"
            item["reason"] = "analysis_failed"
            result["warnings"].append(f"{layer.label}: analysis failed ({type(exc).__name__}).")
        item["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
        result["layers"].append(item)

    result["status"] = "complete" if all(item["status"] == "complete" for item in result["layers"]) else "partial"
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result
