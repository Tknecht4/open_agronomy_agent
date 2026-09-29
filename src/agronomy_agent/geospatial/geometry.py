"""Shared WGS84 geometry policy backed by Shapely and PyProj.

No repair, ring/member selection, or coordinate guessing is performed. Z values
are preserved when supplied; area and topology use the horizontal coordinates.
"""
from __future__ import annotations

import json
import math
from typing import Any


def checked_positions(value: Any, *, maximum: int = 10_000, label: str = "geometry") -> int:
    """Bound exact GeoJSON nesting and finite JSON numbers before library work."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a GeoJSON geometry object")
    count = 0

    def position(item: Any) -> None:
        nonlocal count
        if not isinstance(item, (list, tuple)) or len(item) not in {2, 3}:
            raise ValueError(f"{label} positions must contain two or three numeric coordinates")
        for number in item:
            try:
                finite = type(number) in {int, float} and math.isfinite(number)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{label} coordinates must be finite JSON numbers")
        if not (-180 <= item[0] <= 180 and -90 <= item[1] <= 90):
            raise ValueError(f"{label} coordinates must be WGS84 longitude/latitude (EPSG:4326)")
        count += 1
        if count > maximum:
            raise ValueError(f"{label} exceeds {maximum} coordinate positions")

    def polygon(rings: Any) -> None:
        if not isinstance(rings, (list, tuple)) or not rings:
            raise ValueError(f"{label} polygon rings are required")
        for ring in rings:
            if not isinstance(ring, (list, tuple)) or len(ring) < 4:
                raise ValueError(f"{label} polygon rings require at least four positions")
            for item in ring:
                position(item)
            if list(ring[0]) != list(ring[-1]):
                raise ValueError(f"{label} polygon rings must be closed")

    kind, coordinates = value.get("type"), value.get("coordinates")
    if kind == "Point":
        position(coordinates)
    elif kind == "Polygon":
        polygon(coordinates)
    elif kind == "MultiPolygon":
        if not isinstance(coordinates, (list, tuple)) or not coordinates:
            raise ValueError(f"{label} multipolygon coordinates are required")
        for rings in coordinates:
            polygon(rings)
    else:
        raise ValueError(f"{label} type must be Point, Polygon, or MultiPolygon")
    return count


def canonical_geometry(value: Any, allowed_types: tuple[str, ...] = ("Point", "Polygon", "MultiPolygon"), max_vertices: int = 10_000) -> dict[str, Any]:
    """Validate complete RFC 7946 geometry without silently fixing topology."""
    from shapely.geometry import mapping, shape
    from shapely.validation import explain_validity

    if isinstance(value, dict) and value.get("type") == "Feature":
        if "crs" in value:
            raise ValueError("GeoJSON CRS declarations are unsupported; RFC 7946 requires WGS84")
        value = value.get("geometry")
    if not isinstance(value, dict) or value.get("type") not in allowed_types:
        raise ValueError(f"geometry type must be one of {', '.join(allowed_types)}")
    if "crs" in value:
        raise ValueError("GeoJSON CRS declarations are unsupported; RFC 7946 requires WGS84")
    checked_positions(value, maximum=max_vertices)
    try:
        geometry = shape(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("geometry could not be interpreted") from exc
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError(f"geometry is empty or invalid: {explain_validity(geometry)}")
    if geometry.geom_type != "Point" and geometry.area <= 0:
        raise ValueError("polygon geometry must have positive area")
    if geometry.bounds[2] - geometry.bounds[0] >= 180:
        raise ValueError("antimeridian-crossing geometry is unsupported")
    return json.loads(json.dumps(mapping(geometry), allow_nan=False))


def project_geometry(geometry: Any, target_crs: Any, source_crs: Any = "EPSG:4326") -> Any:
    """Transform horizontal coordinates with explicit CRS and always-XY axes."""
    from pyproj import CRS, Transformer, network
    from shapely.geometry import shape
    from shapely.ops import transform

    try:
        source, target = CRS.from_user_input(source_crs), CRS.from_user_input(target_crs)
    except Exception as exc:
        raise ValueError("source and target CRS must be explicitly defined") from exc
    original = geometry if hasattr(geometry, "geom_type") else shape(geometry)
    if source.equals(CRS.from_epsg(4326), ignore_axis_order=True):
        from shapely.geometry import mapping
        original = shape(canonical_geometry(mapping(original)))
    if original.is_empty or not original.is_valid:
        raise ValueError("source geometry is empty or invalid")
    if network.is_network_enabled():
        raise ValueError("CRS transformations require PROJ network access to be disabled")
    transformer = Transformer.from_crs(source, target, always_xy=True, allow_ballpark=False, only_best=True)
    try:
        projected = transform(lambda x, y, z=None: transformer.transform(x, y, z, errcheck=True) if z is not None else transformer.transform(x, y, errcheck=True), original)
    except Exception as exc:
        raise ValueError("geometry CRS transformation failed") from exc
    if projected.is_empty or not projected.is_valid or not all(math.isfinite(v) for v in projected.bounds):
        raise ValueError("geometry CRS transformation produced invalid coordinates")
    return projected


def geodesic_metrics(geometry: Any) -> dict[str, Any]:
    """Ellipsoidal area, full boundary length, and interior representative point.

    Shapely GeometryCollections from intersections are accepted: non-area parts
    contribute zero area/perimeter. An empty intersection has no location.
    """
    from pyproj import Geod
    from shapely.geometry import shape
    from shapely.geometry.polygon import orient

    parsed = geometry if hasattr(geometry, "geom_type") else shape(canonical_geometry(geometry))
    if not parsed.is_valid:
        raise ValueError("cannot measure invalid geometry")
    if not parsed.is_empty:
        west, south, east, north = parsed.bounds
        if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90) or east - west >= 180:
            raise ValueError("geodesic measurement requires bounded WGS84 geometry")
    geod = Geod(ellps="WGS84")

    def measure(part: Any) -> tuple[float, float]:
        if part.is_empty:
            return 0.0, 0.0
        if part.geom_type == "Polygon":
            area, _ = geod.geometry_area_perimeter(orient(part, sign=1.0))
            return abs(float(area)), float(geod.geometry_length(part.boundary))
        if part.geom_type in {"MultiPolygon", "GeometryCollection"}:
            measured = [measure(member) for member in part.geoms]
            return sum(row[0] for row in measured), sum(row[1] for row in measured)
        return 0.0, 0.0

    area, perimeter = measure(parsed)
    point = parsed.representative_point()
    return {"area_m2": area, "perimeter_m": perimeter, "representative_point": None if point.is_empty else {"longitude": float(point.x), "latitude": float(point.y)}}


def geometries_intersect(left: Any, right: Any) -> bool:
    from shapely.geometry import shape
    return bool(shape(canonical_geometry(left)).intersects(shape(canonical_geometry(right))))
