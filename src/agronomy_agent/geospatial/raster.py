"""Shared raster support, reductions and GIS interchange.

Optional NumPy, Rasterio and Shapely imports occur only when an operation is
called. Geometries and affine grids must already use the same coordinate
reference system; callers own reprojection and scientific support policy.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


def _validate_grid(transform: Any, width: int, height: int) -> float:
    if (isinstance(width, bool) or isinstance(height, bool) or
            not isinstance(width, int) or not isinstance(height, int) or
            width < 1 or height < 1):
        raise ValueError("raster dimensions must be positive integers")
    if not all(math.isfinite(v) for v in tuple(transform)[:6]):
        raise ValueError("raster transform must be finite")
    area = abs(transform.a * transform.e - transform.b * transform.d)
    if area == 0:
        raise ValueError("raster transform must be invertible")
    return area


def fractional_weights(geometry_in_raster_crs: Any, transform: Any,
                       width: int, height: int) -> Any:
    """Exact planar cell-intersection fractions, accumulated as float64.

    Shapely performs topology, including holes and multipolygons. Rasterio's
    all-touched mask restricts intersections; vectorized Shapely handles affine
    cell quadrilaterals in bounded batches, including rotation and shear.
    These fractions are planar support, not geodesic or surveyed field area.
    """
    import numpy as np
    import shapely
    from rasterio.features import geometry_mask

    cell_area = _validate_grid(transform, width, height)
    geometry = (shapely.geometry.shape(geometry_in_raster_crs)
                if isinstance(geometry_in_raster_crs, Mapping) else geometry_in_raster_crs)
    if geometry.geom_type not in ("Polygon", "MultiPolygon") or not geometry.is_valid:
        raise ValueError("raster support must be a valid Polygon or MultiPolygon")
    weights = np.zeros((height, width), dtype=np.float64)
    if geometry.is_empty:
        return weights
    candidate = geometry_mask([geometry.__geo_interface__], out_shape=(height, width),
                              transform=transform, all_touched=True, invert=True)
    rows, cols = np.nonzero(candidate)
    offsets = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], dtype=np.float64)
    for start in range(0, len(rows), 65536):
        r, c = rows[start:start + 65536], cols[start:start + 65536]
        x = c[:, None] + offsets[:, 0]
        y = r[:, None] + offsets[:, 1]
        coordinates = np.stack((transform.a * x + transform.b * y + transform.c,
                                transform.d * x + transform.e * y + transform.f), axis=-1)
        if transform.b == 0 and transform.d == 0:
            # Shapely boxes preserve the existing HLS intersection geometry,
            # while the general path also supports rotated/sheared rasters.
            cells = shapely.box(coordinates[..., 0].min(axis=1), coordinates[..., 1].min(axis=1),
                                coordinates[..., 0].max(axis=1), coordinates[..., 1].max(axis=1))
        else:
            cells = shapely.polygons(coordinates)
        fractions = shapely.area(shapely.intersection(cells, geometry)) / cell_area
        weights[r, c] = np.clip(fractions, 0.0, 1.0)
    return weights


def source_extent_mask(transform: Any, width: int, height: int, *,
                       source_transform: Any, source_width: int,
                       source_height: int) -> Any:
    """Return True for target pixel centres inside the source footprint.

    Both grids must use the same CRS. This is exact full-cell coverage when
    source and target share a native lattice (as HLS requires). For different
    lattices it is a nearest-neighbour coverage mask, not fractional coverage.
    It is independent of nodata tags, which may be absent on source rasters.
    """
    from rasterio.features import geometry_mask

    _validate_grid(transform, width, height)
    _validate_grid(source_transform, source_width, source_height)
    corners = [source_transform * point for point in (
        (0, 0), (source_width, 0), (source_width, source_height),
        (0, source_height), (0, 0))]
    footprint = {"type": "Polygon", "coordinates": [corners]}
    return geometry_mask([footprint], out_shape=(height, width), transform=transform,
                         all_touched=False, invert=True)


def weighted_statistics(values: Any, weights: Any, *, valid: Any = None,
                        cell_area: float = 1.0) -> dict[str, Any]:
    """Finite positive-support statistics with float64 means and area sums.

    ``cell_area`` must be in square metres for the returned ``area_m2`` key.
    Undefined values do not contribute to the index-specific denominator.
    """
    import numpy as np

    data = np.ma.asarray(values, dtype=np.float64)
    support = np.asarray(weights, dtype=np.float64)
    if data.shape != support.shape:
        raise ValueError("values and support weights must have matching shapes")
    if (not np.all(np.isfinite(support)) or np.any(support < 0) or
            not math.isfinite(cell_area) or cell_area <= 0):
        raise ValueError("weights must be finite/nonnegative and cell area positive")
    use = np.isfinite(data.data) & ~np.ma.getmaskarray(data) & (support > 0)
    if valid is not None:
        validity = np.asarray(valid, dtype=bool)
        if validity.shape != data.shape:
            raise ValueError("validity and values must have matching shapes")
        use &= validity
    area = float(support[use].sum(dtype=np.float64)) * cell_area
    if not np.any(use):
        return {"mean": None, "min": None, "max": None, "area_m2": 0.0}
    selected = data.data[use]
    return {"mean": float(np.average(selected, weights=support[use])),
            "min": float(selected.min()), "max": float(selected.max()), "area_m2": area}


def write_geotiff(path: str | Path, array: Any, *, crs: Any, transform: Any,
                  nodata: float = -9999.0, band_names: Sequence[str] | None = None,
                  metadata: Mapping[str, Any] | None = None) -> Path:
    """Write georeferenced float64 GeoTIFF, mapping masked/nonfinite cells to nodata.

    Inputs are 2D or band-first 3D numeric arrays. CRS is required, descriptions
    name bands, and optional lineage is serialized as the ``metadata_json`` tag.
    Nodata may be a finite sentinel or NaN. Valid finite sentinel collisions
    are rejected. This standard GeoTIFF writer does not claim to produce a COG.
    """
    import numpy as np
    import rasterio

    data = np.ma.asarray(array, dtype=np.float64)
    if data.ndim == 2:
        data = data[None, ...]
    if data.ndim != 3 or data.shape[0] < 1:
        raise ValueError("GeoTIFF array must be 2D or band-first 3D")
    _validate_grid(transform, data.shape[2], data.shape[1])
    if crs is None or math.isinf(nodata):
        raise ValueError("GeoTIFF requires a CRS and finite or NaN nodata value")
    output_crs = rasterio.crs.CRS.from_user_input(crs)
    if band_names is not None and (len(band_names) != data.shape[0] or
                                  any(not isinstance(name, str) or not name for name in band_names)):
        raise ValueError("GeoTIFF needs one nonempty name per band")
    metadata_json = json.dumps(dict(metadata), sort_keys=True, allow_nan=False) if metadata is not None else None
    invalid = np.ma.getmaskarray(data) | ~np.isfinite(data.data)
    if np.any((data.data == nodata) & ~invalid):
        raise ValueError("GeoTIFF nodata collides with a valid data value")
    packed = np.where(invalid, nodata, data.data)
    destination = Path(path)
    with rasterio.open(destination, "w", driver="GTiff", count=packed.shape[0],
                       height=packed.shape[1], width=packed.shape[2], dtype="float64",
                       crs=output_crs, transform=transform, nodata=nodata,
                       compress="deflate") as dst:
        dst.write(packed)
        if band_names is not None:
            for index, name in enumerate(band_names, 1):
                dst.set_band_description(index, name)
        if metadata_json is not None:
            dst.update_tags(metadata_json=metadata_json)
    return destination
