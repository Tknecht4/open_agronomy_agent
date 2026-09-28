"""Source-grid sampling support for a saved WGS84 point.

The support is a native pixel or a projected-metre circle. It is never a
field boundary, and the original saved coordinate remains separate.
"""

from __future__ import annotations

import math
from typing import Any


POINT_PROCESS_VERSION = "hls-point-sample-v3-native-grid-source-extent-float64-qa"
MIN_SAMPLE_RADIUS_M = 15
MAX_SAMPLE_RADIUS_M = 1500


def outside_source_mask(
    grid: tuple[Any, Any, int, int, Any, Any],
    source_grid: tuple[Any, Any, int, int], deps: tuple[Any, ...],
) -> Any:
    """Identify chip cells outside the native tile even without nodata tags.

    Point chips follow the source lattice. An absent nodata tag can make a
    WarpedVRT return valid-looking zeros beyond its extent, so coverage must
    be checked from the observed source grid rather than pixel values.
    """
    np = deps[0]
    _, transform, width, height, _, _ = grid
    _, native, source_width, source_height = source_grid
    col_offset_float = (transform.c - native.c) / 30
    row_offset_float = (native.f - transform.f) / 30
    col_offset, row_offset = round(col_offset_float), round(row_offset_float)
    if (not math.isclose(col_offset_float, col_offset, rel_tol=0, abs_tol=1e-6)
            or not math.isclose(row_offset_float, row_offset, rel_tol=0, abs_tol=1e-6)):
        raise RuntimeError("point chip is not aligned to native HLS grid")
    columns = col_offset + np.arange(width)
    rows = row_offset + np.arange(height)
    covered_columns = (columns >= 0) & (columns < source_width)
    covered_rows = (rows >= 0) & (rows < source_height)
    return ~(covered_rows[:, None] & covered_columns[None, :])


def point_grid_and_weights(
    point: dict[str, Any], mode: str, radius_m: int | None,
    source_grid: tuple[Any, Any, int, int], deps: tuple[Any, ...],
) -> tuple[tuple[Any, Any, int, int, Any, Any], Any, dict[str, Any], tuple[float, float, float, float]]:
    """Select the actual source lattice before deriving a sample footprint."""
    np, _, (_, _, from_origin, _), (_, Transformer), (box, shape, shapely_transform), _ = deps
    crs, source_transform, _, _ = source_grid
    projected = shapely_transform(
        Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform, shape(point))
    if not math.isfinite(projected.x) or not math.isfinite(projected.y):
        raise ValueError("point cannot be projected onto HLS grid")

    if mode == "point_pixel":
        col = math.floor((projected.x - source_transform.c) / 30)
        row = math.floor((source_transform.f - projected.y) / 30)
        left = source_transform.c + col * 30
        top = source_transform.f - row * 30
        transform = from_origin(left, top, 30, 30)
        width = height = 1
        support = box(left, top - 30, left + 30, top)
        weights = np.ones((1, 1), dtype=np.float32)
        limitation = ("One native 30 m HLS pixel at the saved location; it can include "
                      "neighboring land cover and does not describe the whole field.")
    elif mode == "point_buffer" and radius_m is not None:
        # Resolution 64 keeps a 15 m circle's area within 0.011% of pi*r^2.
        support = projected.buffer(radius_m, resolution=64)
        xmin, ymin, xmax, ymax = support.bounds
        left = source_transform.c + math.floor((xmin - source_transform.c) / 30) * 30
        top = source_transform.f + math.ceil((ymax - source_transform.f) / 30) * 30
        right = source_transform.c + math.ceil((xmax - source_transform.c) / 30) * 30
        bottom = source_transform.f + math.floor((ymin - source_transform.f) / 30) * 30
        width, height = int(round((right - left) / 30)), int(round((top - bottom) / 30))
        if width < 1 or height < 1 or width > 256 or height > 256:
            raise ValueError("point sample exceeds bounded HLS chip")
        transform = from_origin(left, top, 30, 30)
        weights = np.zeros((height, width), dtype=np.float32)
        for row in range(height):
            ytop = top - row * 30
            for col in range(width):
                xleft = left + col * 30
                cell = box(xleft, ytop - 30, xleft + 30, ytop)
                if support.intersects(cell):
                    weights[row, col] = support.intersection(cell).area / 900
        limitation = ("An area sampled around the saved location, which can include "
                      "neighboring land cover; it is not a field boundary or whole-field estimate.")
    else:
        raise ValueError("invalid point sampling mode or radius")

    # Coordinate transforms do not preserve straight lines. Densify the pixel
    # edges so its WGS84 footprint describes the whole native cell.
    if mode == "point_pixel":
        x0, y0, x1, y1 = support.bounds
        ring = []
        for ax, ay, bx, by in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                               (x1, y1, x0, y1), (x0, y1, x0, y0)):
            ring.extend((ax + (bx - ax) * k / 8, ay + (by - ay) * k / 8) for k in range(8))
        ring.append(ring[0])
    else:
        ring = list(support.exterior.coords)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lng_lat = [[float(lon), float(lat)] for lon, lat in
               (inverse.transform(x, y) for x, y in ring)]
    footprint = {"type": "Polygon", "coordinates": [lng_lat]}
    bounds = (min(p[0] for p in lng_lat), min(p[1] for p in lng_lat),
              max(p[0] for p in lng_lat), max(p[1] for p in lng_lat))
    sampling = {
        "schema_version": "imagery_sampling.v1", "mode": mode,
        "support_kind": "native_pixel" if mode == "point_pixel" else "point_buffer",
        "original_geometry": point, "footprint": footprint, "footprint_crs": "EPSG:4326",
        "sample_radius_m": radius_m, "native_resolution_m": 30,
        "pixel_count": int(np.count_nonzero(weights > 0)), "valid_pixel_count": 0,
        "positional_uncertainty_m": None, "point_role": "unspecified",
        "area_basis": "native_grid_projected_metres",
        "edge_policy": "containing_pixel_floor", "limitation": limitation,
    }
    grid = (crs, transform, width, height, projected, support)
    return grid, weights, sampling, bounds
