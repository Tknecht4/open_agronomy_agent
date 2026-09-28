"""Validate point sampling meaning at cache and serving boundaries.

Checksums bind stored bytes; these checks prevent a point receipt from being
presented with a polygon's field-area meaning or a different requested radius.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from agronomy_agent.field_imagery import _valid_geometry, _valid_search_geometry
from agronomy_agent.imagery_sampling import POINT_PROCESS_VERSION


def _finite(value: Any, *, minimum: float = 0) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= minimum)


def validate_point_receipt(
    receipt: dict[str, Any], *, geometry: dict[str, Any] | None = None,
    sampling_mode: str | None = None, sample_radius_m: int | None = None,
) -> tuple[float, float, float, float]:
    """Return validated support bounds, or raise for a contradictory receipt."""
    sampling = receipt.get("sampling")
    if receipt.get("process_version") != POINT_PROCESS_VERSION or receipt.get("source_native_grid") is not True:
        raise ValueError("unsupported point processing version")
    if not isinstance(sampling, dict) or sampling.get("schema_version") != "imagery_sampling.v1":
        raise ValueError("point sampling receipt required")
    mode = sampling.get("mode")
    if mode not in ("point_pixel", "point_buffer") or (sampling_mode is not None and mode != sampling_mode):
        raise ValueError("point sampling mode mismatch")
    if sampling.get("support_kind") != ("native_pixel" if mode == "point_pixel" else "point_buffer"):
        raise ValueError("point support kind mismatch")
    radius = sampling.get("sample_radius_m")
    if mode == "point_pixel":
        if radius is not None:
            raise ValueError("pixel sampling cannot declare a buffer radius")
    elif type(radius) is not int or not 15 <= radius <= 1500:
        raise ValueError("point sample radius out of bounds")
    if sampling_mode is not None and radius != sample_radius_m:
        raise ValueError("point sample radius mismatch")
    original, _ = _valid_search_geometry(sampling.get("original_geometry"))
    if original["type"] != "Point":
        raise ValueError("point sampling must preserve a point")
    if geometry is not None and original != _valid_search_geometry(geometry)[0]:
        raise ValueError("point input geometry mismatch")
    identity = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if receipt.get("geometry_hash") != identity:
        raise ValueError("point geometry hash mismatch")
    request = receipt.get("request")
    keys = {"provider_id", "scene_id", "start_date", "end_date", "buffer_m", "context_pixels", "sampling_mode", "sample_radius_m"}
    if not isinstance(request, dict) or set(request) != keys:
        raise ValueError("point request provenance required")
    if (request["sampling_mode"] != mode or request["sample_radius_m"] != radius
            or request["provider_id"] != receipt.get("provider_id")
            or request["scene_id"] not in (None, receipt.get("scene_id"))):
        raise ValueError("point request contradicts sampling receipt")
    from agronomy_agent.imagery_analytics import _request_identity
    _, _, _, expected_request_hash = _request_identity(
        original, request["provider_id"], request["scene_id"], request["start_date"], request["end_date"],
        request["buffer_m"], request["context_pixels"], sampling_mode=mode, sample_radius_m=radius)
    if receipt.get("request_hash") != expected_request_hash:
        raise ValueError("point request hash mismatch")
    footprint, bounds = _valid_geometry(sampling.get("footprint"))
    if sampling.get("footprint_crs") != "EPSG:4326":
        raise ValueError("unknown sample footprint CRS")
    from shapely.geometry import shape
    if not shape(footprint).buffer(1e-10).covers(shape(original)):
        raise ValueError("sample footprint does not cover the input point")
    if (sampling.get("native_resolution_m") != 30
            or sampling.get("point_role") != "unspecified"
            or "positional_uncertainty_m" not in sampling
            or sampling["positional_uncertainty_m"] is not None
            or sampling.get("area_basis") != "native_grid_projected_metres"
            or sampling.get("edge_policy") != "containing_pixel_floor"
            or not isinstance(sampling.get("limitation"), str)
            or not sampling["limitation"].strip()):
        raise ValueError("unsupported sampling meaning")
    grid = receipt.get("grid") or {}
    if not isinstance(grid, dict):
        raise ValueError("invalid sample grid")
    width, height = grid.get("width"), grid.get("height")
    if grid.get("resolution_m") != 30 or any(type(size) is not int or not 1 <= size <= 256 for size in (width, height)):
        raise ValueError("invalid sample grid dimensions")
    count, valid_count = sampling.get("pixel_count"), sampling.get("valid_pixel_count")
    if (type(count) is not int or not 1 <= count <= width * height
            or type(valid_count) is not int or not 0 <= valid_count <= count):
        raise ValueError("invalid sampled pixel counts")
    qa = receipt.get("qa") or {}
    if not isinstance(qa, dict):
        raise ValueError("invalid sample QA")
    area, valid_area, fraction = qa.get("sample_area_m2"), qa.get("valid_area_m2"), qa.get("valid_area_fraction")
    if ("field_area_m2" in qa or not _finite(area, minimum=1e-9)
            or not _finite(valid_area) or valid_area > area + 1e-5
            or area > count * 900 + 1e-3 or not _finite(fraction)
            or fraction > 1 or not math.isclose(fraction, valid_area / area, abs_tol=1e-6)):
        raise ValueError("invalid sample areas")
    if (valid_count == 0) != (valid_area == 0):
        raise ValueError("sample validity contradicts pixel count")
    if mode == "point_pixel" and (width != 1 or height != 1 or count != 1
            or not math.isclose(area, 900, abs_tol=1e-4)
            or not math.isclose(valid_area, valid_count * 900, abs_tol=1e-4)):
        raise ValueError("pixel mode must describe one native pixel")
    if mode == "point_buffer" and not math.isclose(area, math.pi * radius**2, rel_tol=2e-4, abs_tol=1e-3):
        raise ValueError("sample area contradicts requested circle radius")
    if receipt.get("status") not in ("available", "empty_valid_area") or (
            receipt["status"] == "empty_valid_area") != (valid_count == 0):
        raise ValueError("sample status contradicts QA")
    nodata = qa.get("nodata_area_m2")
    exclusions = qa.get("excluded_area_m2_by_reason")
    tolerance = max(1e-5, area * 1e-6)
    if valid_area > valid_count * 900 + tolerance:
        raise ValueError("valid sample area exceeds valid pixel support")
    if (not _finite(nodata) or nodata > area + tolerance
            or not isinstance(exclusions, dict)
            or any(not isinstance(key, str) or not _finite(value) or value > area + tolerance
                   for key, value in exclusions.items())
            or not isinstance(qa.get("overlap_note"), str)):
        raise ValueError("invalid point QA area breakdown")
    indices = receipt.get("zonal_stats")
    if not isinstance(indices, dict):
        raise ValueError("point index statistics required")
    for name in ("NDVI", "NDMI"):
        stats = indices.get(name)
        if not isinstance(stats, dict) or not {"mean", "min", "max", "area_m2"}.issubset(stats):
            raise ValueError("complete point index statistics required")
        support = stats["area_m2"]
        values = [stats[key] for key in ("min", "mean", "max")]
        if not _finite(support) or support > valid_area + tolerance:
            raise ValueError("index support exceeds QA-valid sample area")
        if support == 0:
            if any(value is not None for value in values):
                raise ValueError("unsupported index cannot have numeric values")
        else:
            if valid_area == 0 or not all(_finite(value, minimum=-math.inf) for value in values):
                raise ValueError("index values contradict their support")
            order_tolerance = 1e-6 * max(1., *(abs(value) for value in values))
            if values[0] > values[1] + order_tolerance or values[1] > values[2] + order_tolerance:
                raise ValueError("index values contradict their support")
    return tuple(bounds)
