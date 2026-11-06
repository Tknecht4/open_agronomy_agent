"""Bounded client-declared boundary provenance, separate from source authority.

An upload receipt returned to the browser is not a signed server attestation.
Saving its snapshot retains useful source identity without verifying that the
saved shape came from those bytes, or making its attributes field measurements.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from agronomy_agent.geospatial.geometry import canonical_geometry
from agronomy_agent.geospatial.json_properties import bounded_json_properties
from agronomy_agent.geospatial.vector_io import MAX_FEATURES, MAX_UPLOAD_BYTES, MAX_ZIP_MEMBERS


BOUNDARY_IMPORT_SCHEMA = "open_agronomy_agent.boundary_import_lineage.v1"
BOUNDARY_IMPORT_UNSET = object()
MAX_LINEAGE_BYTES = 96 * 1024
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_INPUT_KEYS = {"import_receipt", "coordinate_reference", "selected_feature"}


def _object(value: Any, *, name: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"boundaryImport {name} must be an object with string keys")
    if set(value) - allowed:
        raise ValueError(f"boundaryImport {name} contains unsupported fields")
    if required - set(value):
        raise ValueError(f"boundaryImport {name} is missing required fields")
    return value


def _text(value: Any, *, name: str, max_bytes: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"boundaryImport {name} requires a nonempty string of at most {max_bytes} UTF-8 bytes")
    return value


def _sha256(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"boundaryImport {name} requires a SHA-256 hex digest")
    return value.lower()


def _boolean(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"boundaryImport {name} requires a boolean")
    return value


def geometry_sha256(geometry: dict[str, Any]) -> str:
    """Hash validated shape coordinates, excluding mutable UI acreage or labels."""
    if not isinstance(geometry, dict):
        raise ValueError("boundaryImport requires normalized field geometry")
    kind = geometry.get("kind")
    if kind == "none":
        canonical = {"kind": "none"}
    elif kind == "point":
        point = geometry.get("point")
        if not isinstance(point, dict):
            raise ValueError("boundaryImport point geometry requires lat/lon")
        canonical = canonical_geometry({"type": "Point", "coordinates": [point.get("lon"), point.get("lat")]})
    elif kind == "geojson":
        canonical = canonical_geometry(geometry.get("geojson"), allowed_types=("Polygon", "MultiPolygon"))
    elif kind == "polygon":
        points = geometry.get("points")
        if not isinstance(points, list) or not points or any(not isinstance(point, dict) for point in points):
            raise ValueError("boundaryImport polygon geometry requires points")
        ring = [[point.get("lon"), point.get("lat")] for point in points]
        canonical = canonical_geometry({"type": "Polygon", "coordinates": [[*ring, ring[0]]]})
    else:
        raise ValueError("boundaryImport requires point, polygon, or none field geometry")
    encoded = json.dumps(canonical, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_snapshot(value: Any) -> dict[str, Any]:
    incoming = _object(value, name="snapshot", allowed=_INPUT_KEYS, required=_INPUT_KEYS)
    receipt = _object(incoming["import_receipt"], name="import_receipt", allowed={"schema_version", "source_sha256", "source_bytes"}, required={"schema_version", "source_sha256", "source_bytes"})
    if receipt["schema_version"] != "open_agronomy_agent.vector_import.v1":
        raise ValueError("boundaryImport import_receipt schema_version is unsupported")
    byte_count = receipt["source_bytes"]
    if type(byte_count) is not int or not 0 < byte_count <= MAX_UPLOAD_BYTES:
        raise ValueError("boundaryImport source_bytes must be a positive integer within the upload byte limit")
    normalized_receipt = {
        "schema_version": receipt["schema_version"],
        "source_sha256": _sha256(receipt["source_sha256"], name="source_sha256"),
        "source_bytes": byte_count,
    }

    reference_keys = {"target_crs", "label", "reprojected", "sources"}
    reference = _object(incoming["coordinate_reference"], name="coordinate_reference", allowed=reference_keys, required=reference_keys)
    if reference["target_crs"] != "EPSG:4326":
        raise ValueError("boundaryImport coordinate_reference target_crs must be EPSG:4326")
    sources = reference["sources"]
    if not isinstance(sources, list) or not 0 < len(sources) <= MAX_ZIP_MEMBERS:
        raise ValueError("boundaryImport coordinate_reference sources requires a bounded nonempty array")
    required_crs = {"layer", "source_crs", "crs_basis", "target_crs", "reprojected"}
    allowed_crs = required_crs | {"source_crs_wkt", "transform_policy"}
    normalized_sources = []
    for row in sources:
        source = _object(row, name="coordinate_reference source", allowed=allowed_crs, required=required_crs)
        if source["target_crs"] != "EPSG:4326":
            raise ValueError("boundaryImport source target_crs must be EPSG:4326")
        if source["crs_basis"] not in {"RFC7946", "declared_dataset_metadata"}:
            raise ValueError("boundaryImport source crs_basis is unsupported")
        normalized = {
            "layer": _text(source["layer"], name="source layer"),
            "source_crs": _text(source["source_crs"], name="source_crs", max_bytes=16 * 1024),
            "crs_basis": source["crs_basis"],
            "target_crs": source["target_crs"],
            "reprojected": _boolean(source["reprojected"], name="source reprojected"),
        }
        if normalized["crs_basis"] == "RFC7946" and (normalized["source_crs"] != "EPSG:4326" or normalized["reprojected"]):
            raise ValueError("boundaryImport RFC7946 source CRS and reprojection flags disagree")
        for key in ("source_crs_wkt", "transform_policy"):
            if key in source:
                normalized[key] = _text(source[key], name=key, max_bytes=16 * 1024)
        normalized_sources.append(normalized)
    reprojected = _boolean(reference["reprojected"], name="coordinate_reference reprojected")
    if reprojected != any(source["reprojected"] for source in normalized_sources):
        raise ValueError("boundaryImport coordinate_reference reprojection flags disagree")
    normalized_reference = {
        "target_crs": reference["target_crs"],
        "label": _text(reference["label"], name="coordinate_reference label"),
        "reprojected": reprojected,
        "sources": normalized_sources,
    }

    required_feature = {"id", "source_layer", "source_feature_index", "properties"}
    feature = _object(incoming["selected_feature"], name="selected_feature", allowed=required_feature | {"source_feature_id"}, required=required_feature)
    source_layer = _text(feature["source_layer"], name="selected source_layer")
    if source_layer not in {source["layer"] for source in normalized_sources}:
        raise ValueError("boundaryImport selected source_layer is absent from the CRS receipt")
    index = feature["source_feature_index"]
    if type(index) is not int or not 0 <= index < MAX_FEATURES:
        raise ValueError("boundaryImport source_feature_index requires a zero-based index within the upload feature limit")
    normalized_feature = {
        "id": _text(feature["id"], name="selected feature id"),
        "source_layer": source_layer,
        "source_feature_index": index,
        "properties": bounded_json_properties(feature["properties"]),
    }
    if "source_feature_id" in feature:
        feature_id = feature["source_feature_id"]
        if feature_id is not None:
            if isinstance(feature_id, str):
                if len(feature_id.encode("utf-8")) > 512:
                    raise ValueError("boundaryImport source_feature_id exceeds 512 UTF-8 bytes")
            elif type(feature_id) not in {int, float}:
                raise ValueError("boundaryImport source_feature_id requires a string, finite number, or null")
            else:
                try:
                    finite = math.isfinite(feature_id)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("boundaryImport source_feature_id requires a finite number")
        normalized_feature["source_feature_id"] = feature_id
    properties = normalized_feature["properties"]
    for property_key, feature_key in (
        ("upload_source_layer", "source_layer"),
        ("upload_source_feature_index", "source_feature_index"),
        ("upload_source_feature_id", "source_feature_id"),
    ):
        if property_key in properties and feature_key in normalized_feature and (
            properties[property_key] != normalized_feature[feature_key]
            or type(properties[property_key]) is not type(normalized_feature[feature_key])
        ):
            raise ValueError(f"boundaryImport selected feature {feature_key} disagrees with upload properties")
    return {"import_receipt": normalized_receipt, "coordinate_reference": normalized_reference, "selected_feature": normalized_feature}


def normalize_boundary_import(
    value: Any = BOUNDARY_IMPORT_UNSET,
    *,
    geometry: dict[str, Any],
    previous_lineage: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize a new client snapshot, preserve it, supersede it, or clear it.

    Omission preserves the original shape binding across metadata edits. A shape
    edit retains historical source identity with explicit superseded validity.
    Explicit null clears the snapshot. Only a new supplied snapshot can create a
    new binding; no source bytes are verified or retained by this function.
    """
    if value is None:
        return None
    if value is BOUNDARY_IMPORT_UNSET and previous_lineage is None:
        return None
    current_sha = geometry_sha256(geometry)
    if value is BOUNDARY_IMPORT_UNSET:
        if not isinstance(previous_lineage, dict) or previous_lineage.get("schema_version") != BOUNDARY_IMPORT_SCHEMA:
            raise ValueError("boundaryImport previous lineage schema is unsupported")
        snapshot = _source_snapshot({key: previous_lineage.get(key) for key in _INPUT_KEYS})
        bound_sha = _sha256(previous_lineage.get("geometry_sha256"), name="previous geometry_sha256")
        superseded = previous_lineage.get("validity") == "superseded" or bound_sha != current_sha
    else:
        if geometry.get("kind") == "none":
            raise ValueError("boundaryImport cannot bind an import to an unknown field location")
        snapshot = _source_snapshot(value)
        bound_sha, superseded = current_sha, False
    result = {
        "schema_version": BOUNDARY_IMPORT_SCHEMA,
        **snapshot,
        "geometry_sha256": bound_sha,
        "current_geometry_sha256": current_sha,
        "validity": "superseded" if superseded else "bound",
        "binding_status": "superseded_geometry_edit" if superseded else "client_snapshot_context_only",
        "source_attested": False,
        "authority": "context_only",
        "not_field_measurement": True,
        "not_current_crop_authority": True,
        "not_training_data": True,
        "boundary": "Client-declared import snapshot; source bytes and source-to-shape correspondence are unverified. Source attributes are historical context, not field measurements, current crop authority, cadastral evidence, or training admission.",
    }
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_LINEAGE_BYTES:
        raise ValueError(f"boundaryImport exceeds {MAX_LINEAGE_BYTES} encoded JSON bytes")
    return result
