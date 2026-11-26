"""Bounded, deterministic field geometry and official mapped-zone analysis.

The result is context from source polygons, never a field observation or survey.
Spatial libraries are imported only when an analysis is requested.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from agronomy_agent.server.services import geospatial_service as geo
from agronomy_agent.geospatial.geometry import MAX_GEOMETRY_VERTICES, checked_positions, geodesic_metrics, geojson_area_m2


SCHEMA_VERSION = "open_agronomy_agent.field_map_analysis.v1"
MAX_LAYERS = 4
MAX_REQUEST_BYTES = 1024 * 1024
MAX_REMOTE_SOURCE_VERTICES = 20_000
MAX_ZONES_SHOWN = 10
ACRES_PER_HECTARE = 2.471053814671653


def _empty_layer(layer: Any, status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "layer_id": layer.id,
        "label": layer.label,
        "source_url": layer.source_url,
        "source_mode": layer.query_backend,
        "boundary": layer.boundary,
        "coverage_method": "WGS84 ellipsoidal area using the GeoJSON edges of the clipped source union",
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


def _area_in_field_m2(geometry: Any, field_area_m2: float) -> float:
    area_m2 = geojson_area_m2(geometry)
    if area_m2 > field_area_m2 and not math.isclose(area_m2, field_area_m2, rel_tol=1e-10, abs_tol=0.001):
        raise ValueError("clipped area exceeds the field area")
    return min(area_m2, field_area_m2)


def _load_remote_features(
    layer: Any, geometry: dict[str, Any], network_mode: str
) -> tuple[list[dict[str, Any]] | None, int | None, list[str], bool | None]:
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


def _measure_layer_features(
    item: dict[str, Any], features: Iterable[dict[str, Any] | None], field_shape: Any, area_m2: float,
    *, remote: bool,
) -> int:
    """Measure exact intersections as candidates arrive, retaining only clipped geometry."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from shapely.prepared import prep

    prepared_field = prep(field_shape)
    point = field_shape.geom_type == "Point"
    scanned = matched = 0
    remaining = MAX_REMOTE_SOURCE_VERTICES if remote else None
    zones = []
    clipped_by_zone: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for feature in features:
        scanned += 1
        geometry = feature.get("geometry") if feature else None
        if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            _record_incomplete(item, "malformed_source_feature")
            continue
        try:
            positions = checked_positions(geometry, maximum=remaining, label="source geometry")
        except ValueError as exc:
            if "exceeds" in str(exc):
                _record_incomplete(item, "source_vertex_limit_reached")
                item["reason"] = "source_vertex_limit_reached"
                item["processed_feature_count"] = matched
                return scanned
            _record_incomplete(item, "malformed_source_feature")
            continue
        if remaining is not None:
            remaining -= positions
        try:
            region = shape(geometry)
        except (TypeError, ValueError, KeyError):
            _record_incomplete(item, "invalid_source_geometry")
            continue
        if (region.is_empty or not region.is_valid or region.geom_type not in {"Polygon", "MultiPolygon"}
            or region.bounds[2] - region.bounds[0] >= 180):
            _record_incomplete(item, "invalid_source_geometry")
            continue
        if not prepared_field.intersects(region):
            continue
        matched += 1
        properties = feature["properties"]
        code = str(properties.get("code") or "")
        name = str(properties.get("name") or "")
        if point:
            if len(zones) < MAX_ZONES_SHOWN:
                zones.append({"code": code, "name": name, "area_ha": None, "fraction_of_field": None})
        else:
            clipped = field_shape.intersection(region)
            if not clipped.is_empty:
                clipped_by_zone[code, name].append(clipped)

    item["processed_feature_count"] = matched
    if point:
        item["zones"] = zones
        item["omitted_zone_count"] = matched - len(zones)
        return scanned

    coverage_pieces = []
    complete = item["status"] == "complete"
    for (code, name), pieces in clipped_by_zone.items():
        merged = pieces[0] if len(pieces) == 1 else unary_union(pieces)
        zone_m2 = _area_in_field_m2(merged, area_m2)
        coverage_pieces.append(merged)
        zones.append({
            "code": code,
            "name": name,
            "area_ha": round(zone_m2 / 10_000, 6),
            "fraction_of_field": round(zone_m2 / area_m2, 6),
        })
    if complete:
        covered_m2 = _area_in_field_m2(unary_union(coverage_pieces), area_m2) if coverage_pieces else 0.0
        item["covered_area_ha"] = round(covered_m2 / 10_000, 6)
        item["coverage_fraction"] = round(covered_m2 / area_m2, 6)
    zones.sort(key=lambda zone: (-zone["area_ha"], zone["code"], zone["name"]))
    item["zones"] = zones[:MAX_ZONES_SHOWN]
    if not complete:
        for zone in item["zones"]:
            zone["area_ha"] = zone["fraction_of_field"] = None
    item["omitted_zone_count"] = max(0, len(zones) - MAX_ZONES_SHOWN)
    return scanned


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
        raise ValueError("geometry exceeds 1 MiB limit")
    checked_positions(geometry)
    layers = [geo.REGION_LAYERS[layer_id] for layer_id in layer_ids]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "geometry": {
            "type": geometry["type"],
            "status": "unavailable",
            "area_ha": None,
            "area_ac": None,
            "perimeter_m": None,
            "location": None,
            "method": "WGS84 ellipsoidal area using GeoJSON edges, geodesic boundary length, and an interior representative point",
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
            "max_input_vertices": MAX_GEOMETRY_VERTICES,
            "max_remote_source_vertices": MAX_REMOTE_SOURCE_VERTICES,
            "max_remote_features_per_layer": geo.MAX_FEATURES_PER_LAYER,
            "max_zones_shown": MAX_ZONES_SHOWN,
            "remote_timeout_seconds_per_layer": geo.HTTP_TIMEOUT_SECONDS,
        },
        "elapsed_ms": None,
        "warnings": ["Mapped context is not a field measurement, survey, or current management recommendation."],
    }
    try:
        import pyproj  # noqa: F401 - explicit optional dependency readiness check
        from shapely.geometry import shape
    except ImportError:
        result["layers"] = [_empty_layer(layer, "unavailable", "spatial_dependencies_missing") for layer in layers]
        result["warnings"].append("Install the supported runtime requirements to enable field analysis.")
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        return result

    parsed = geo.validate_geojson_geometry(geometry)
    field_shape = shape(parsed)
    bounds = field_shape.bounds
    envelopes = tuple(part.bounds for part in field_shape.geoms) if parsed["type"] == "MultiPolygon" else (bounds,)
    remote_span_supported = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) <= geo.MAX_BBOX_SPAN_DEGREES
    metrics = geodesic_metrics(field_shape)
    area_m2, perimeter_m = geojson_area_m2(field_shape), metrics["perimeter_m"]
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
        local = layer.query_backend == "local_sqlite"
        if network_mode == "offline" and not local:
            blocked = _empty_layer(layer, "blocked_offline", "offline_network_policy")
            blocked["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
            result["layers"].append(blocked)
            continue
        if local:
            readiness = geo._local_layer_readiness(layer)
            if readiness["status"] != "verified":
                unavailable = _empty_layer(
                    layer, "not_installed" if readiness["status"] == "missing" else "integrity_failed",
                    "local_layer_not_installed" if readiness["status"] == "missing" else "local_source_identity_failed",
                )
                unavailable["source_integrity"] = readiness
                unavailable["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
                result["layers"].append(unavailable)
                continue
        item = _empty_layer(layer, "complete")
        try:
            if local:
                with geo.local_coverage_features(layer, envelopes, readiness=readiness) as candidates:
                    item["feature_count"] = _measure_layer_features(
                        item, candidates, field_shape, area_m2, remote=False,
                    )
                item["source_integrity"] = readiness
                item["source_exceeded_transfer_limit"] = False
            elif not remote_span_supported:
                item.update(status="unavailable", reason="remote_geometry_span_unsupported")
            else:
                features, feature_count, incomplete, transfer = _load_remote_features(layer, parsed, network_mode)
                item["feature_count"] = feature_count
                item["source_exceeded_transfer_limit"] = transfer
                item["incomplete_reasons"] = incomplete
                if features is None:
                    item.update(status="unavailable", reason=incomplete[0])
                    result["warnings"].append(f"{layer.label}: source query or collection unavailable.")
                else:
                    if incomplete:
                        item.update(status="partial", reason=incomplete[0])
                    _measure_layer_features(item, features, field_shape, area_m2, remote=True)
        except geo.LocalLayerIntegrityError as exc:
            item = _empty_layer(layer, "integrity_failed", "local_source_identity_failed")
            item["source_integrity"] = exc.receipt
            result["warnings"].append(f"{layer.label}: local source identity changed during analysis.")
        except Exception as exc:
            item = _empty_layer(layer, "unavailable", "analysis_failed")
            result["warnings"].append(f"{layer.label}: analysis failed ({type(exc).__name__}).")
        item["elapsed_ms"] = round((time.monotonic() - layer_started) * 1000, 2)
        result["layers"].append(item)

    result["status"] = "complete" if all(item["status"] == "complete" for item in result["layers"]) else "partial"
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result
