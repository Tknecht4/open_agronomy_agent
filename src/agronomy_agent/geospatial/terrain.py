"""Bounded, offline terrain model products; never a drainage diagnosis.

Rasterio owns raster IO, shared geometry owns topology/CRS, and PyFlwDir owns
conditioning, slope and D8 routing. The rectangular processing domain is never
masked to the field before hydrology. Source declarations are operator assertions.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "field-terrain.v1"
METHOD_VERSION = "pyflwdir-d8-context-edge-screened-v1"
MAX_CELLS = 1_000_000
MAX_SOURCE_BYTES = 512 * 1024 * 1024


class TerrainError(ValueError):
    """A scientific input or local resource contract was not met."""


def terrain_readiness() -> dict[str, Any]:
    """Inspect installed distributions without importing optional heavy packages."""
    versions, missing = {}, []
    for name in ("numpy", "rasterio", "shapely", "pyproj", "pyflwdir"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    return {
        "status": "setup_required" if missing else "installed_not_exercised",
        "missing_dependencies": missing,
        "versions": versions,
        "network_required": False,
        "scientific_status": "model_derived_context_only",
    }


def _dependencies():
    names = ("numpy", "rasterio", "pyflwdir")
    try:
        for name in ("shapely", "pyproj"):
            importlib.import_module(name)
        return tuple(importlib.import_module(name) for name in names)
    except ImportError as exc:
        raise TerrainError(
            "Terrain dependencies unavailable; install requirements-geospatial.txt "
            "in an isolated operator environment."
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TerrainError("source_metadata must be a JSON object")
    result = dict(value)
    if result.get("terrain_type") != "DTM" or result.get("bare_earth") is not True:
        raise TerrainError("An explicit bare-earth DTM is required; DSM/unknown are unsupported")
    if result.get("vertical_units") != "m":
        raise TerrainError("vertical_units must explicitly be m; no implicit vertical conversion")
    for key in ("source_id", "source_url", "source_date", "license", "vertical_datum"):
        item = result.get(key)
        if not isinstance(item, str) or not item.strip() or item.strip().lower() in {
            "unknown", "none", "null", "n/a", "unspecified",
        }:
            raise TerrainError(f"Explicit source metadata required: {key}")
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise TerrainError("source_metadata must contain finite JSON values") from exc
    return result


def _local_tiff(value: str | Path) -> Path:
    text = str(value)
    if "://" in text or text.startswith("/vsi"):
        raise TerrainError("DEM must be a local GeoTIFF; URLs and GDAL virtual paths are unsupported")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() not in {".tif", ".tiff"} or not path.is_file():
        raise TerrainError("DEM must be an existing local .tif or .tiff file")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise TerrainError(f"DEM exceeds bounded source size of {MAX_SOURCE_BYTES} bytes")
    return path


def run_terrain_analysis(
    dem_path: str | Path,
    geometry: Mapping[str, Any],
    output_dir: str | Path,
    *,
    source_metadata: Mapping[str, Any],
    context_buffer_m: float,
    include_twi: bool = False,
    max_cells: int = MAX_CELLS,
) -> dict[str, Any]:
    """Write a new terrain bundle for a WGS84 Polygon/MultiPolygon.

    Inputs must be a single-band, unscaled, north-up square-cell projected-metre
    GeoTIFF with complete data across the field's buffered bounding rectangle.
    ``max_cells`` may lower, but cannot raise, the one-million-cell hard limit.
    The source raster is not modified. Rejected inputs create no output directory.
    """
    metadata = _source_metadata(source_metadata)
    if isinstance(context_buffer_m, bool) or not isinstance(context_buffer_m, (int, float)):
        raise TerrainError("context_buffer_m must be a finite positive number")
    if not math.isfinite(context_buffer_m) or context_buffer_m <= 0:
        raise TerrainError("context_buffer_m must be a finite positive number")
    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or not 1 <= max_cells <= MAX_CELLS:
        raise TerrainError(f"max_cells must be an integer from 1 to {MAX_CELLS}")
    if not isinstance(include_twi, bool):
        raise TerrainError("include_twi must be boolean")
    source = _local_tiff(dem_path)
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise TerrainError("Output directory already exists; terrain bundles never overwrite")
    np, rasterio, pyflwdir = _dependencies()
    from pyproj import CRS
    from rasterio.windows import Window, from_bounds
    from .geometry import canonical_geometry, project_geometry
    from .raster import fractional_weights, weighted_statistics, write_geotiff

    canonical = canonical_geometry(geometry, allowed_types=("Polygon", "MultiPolygon"))
    source_stat = source.stat()
    source_hash = _sha256(source)
    with rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024), rasterio.open(source, sharing=False) as dataset:
        if dataset.driver != "GTiff" or dataset.count != 1:
            raise TerrainError("A single-band GeoTIFF DTM is required")
        if any(rows * cols > MAX_CELLS for rows, cols in dataset.block_shapes):
            raise TerrainError("DEM native storage blocks exceed the bounded decode cell budget")
        if dataset.crs is None:
            raise TerrainError("DEM horizontal CRS is missing")
        crs = CRS.from_user_input(dataset.crs)
        if not crs.is_projected or len(crs.axis_info) < 2 or any(
            not math.isclose(axis.unit_conversion_factor, 1.0, abs_tol=1e-12)
            or axis.unit_name.lower() not in {"metre", "meter", "metres", "meters"}
            for axis in crs.axis_info[:2]
        ):
            raise TerrainError("DEM must use a projected horizontal CRS with metre axes")
        affine = dataset.transform
        if not all(math.isfinite(item) for item in affine[:6]) or (
            affine.b != 0 or affine.d != 0 or affine.a <= 0 or affine.e >= 0
            or not math.isclose(affine.a, -affine.e, rel_tol=1e-10)
        ):
            raise TerrainError("DEM requires north-up, unrotated, square cells")
        resolution = float(affine.a)
        if context_buffer_m < 2 * resolution:
            raise TerrainError("Insufficient context: buffer must span at least two native cells")
        if dataset.scales != (1.0,) or dataset.offsets != (0.0,):
            raise TerrainError("Scaled/offset elevations are unsupported; supply explicit metre elevations")
        if dataset.units[0] not in (None, "", "m", "metre", "meter"):
            raise TerrainError("Raster band vertical units contradict declared metres")
        if np.dtype(dataset.dtypes[0]).kind not in "fiu":
            raise TerrainError("DEM requires real numeric elevations")
        projected = project_geometry(canonical, crs)
        left, bottom, right, top = projected.bounds
        buffered = (left - context_buffer_m, bottom - context_buffer_m,
                    right + context_buffer_m, top + context_buffer_m)
        candidate = from_bounds(*buffered, transform=affine)
        col0, row0 = math.floor(candidate.col_off), math.floor(candidate.row_off)
        col1 = math.ceil(candidate.col_off + candidate.width)
        row1 = math.ceil(candidate.row_off + candidate.height)
        if col0 < 0 or row0 < 0 or col1 > dataset.width or row1 > dataset.height:
            raise TerrainError("Insufficient DEM context: complete buffered rectangle is outside source extent")
        width, height = col1 - col0, row1 - row0
        if width * height > max_cells:
            raise TerrainError(f"Context rectangle exceeds max_cells={max_cells}; no resampling performed")
        window = Window(col0, row0, width, height)
        transform = dataset.window_transform(window)
        original = dataset.read(1, window=window, masked=True).astype("float64")
        if np.any(np.ma.getmaskarray(original)) or not np.all(np.isfinite(original.data)):
            raise TerrainError("DEM context contains nodata/voids; implicit void filling is prohibited")
        elevation = np.asarray(original.data)
        if np.any(np.abs(elevation) > np.finfo("float32").max / 4):
            raise TerrainError("DEM elevations exceed the finite precision range of PyFlwDir")
        source_grid = {"width": dataset.width, "height": dataset.height,
                       "transform": list(affine[:6]), "dtype": dataset.dtypes[0],
                       "nodata": str(dataset.nodata), "horizontal_crs_wkt": crs.to_wkt()}
    if source.stat().st_size != source_stat.st_size or source.stat().st_mtime_ns != source_stat.st_mtime_ns:
        raise TerrainError("DEM changed during analysis input read")
    weights = fractional_weights(projected, transform, width, height)
    field = weights > 0
    if not np.any(field):
        raise TerrainError("Field has no native-grid support")
    edge = np.zeros(elevation.shape, dtype=bool)
    edge[[0, -1], :] = True
    edge[:, [0, -1]] = True
    if np.any(field & edge):
        raise TerrainError("Insufficient context: field intersects processing boundary")

    # NaN is the sentinel; finite elevations including -9999 remain valid data.
    conditioned, directions = pyflwdir.dem.fill_depressions(
        elevation, outlets="edge", nodata=float("nan"), max_depth=-1.0, connectivity=8,
    )
    # Plain numeric affine coefficients are accepted by Numba across Affine versions.
    slope = pyflwdir.dem.slope(elevation, nodata=float("nan"), latlon=False,
                              transform=tuple(float(v) for v in transform))
    flow = pyflwdir.from_array(directions, ftype="d8", transform=transform, latlon=False)
    if not flow.isvalid:
        raise TerrainError("PyFlwDir produced an invalid flow network")
    cell_area = resolution * resolution
    area_raw = flow.accuflux(np.full(elevation.shape, cell_area, dtype="float64"))
    edge_influence = flow.accuflux(edge.astype("float64")) > 0
    area = np.where(~edge_influence, area_raw, np.nan)
    slope = np.asarray(slope, dtype="float64")
    if not np.all(np.isfinite(slope)):
        raise TerrainError("Slope calculation exceeded finite numeric range")
    slope[edge] = np.nan
    fill_depth = np.asarray(conditioned, dtype="float64") - elevation
    twi_valid = ~edge_influence & np.isfinite(slope) & (slope > 0) & (area > 0)
    twi = np.full(elevation.shape, np.nan)
    if include_twi:
        twi[twi_valid] = np.log((area[twi_valid] / resolution) / slope[twi_valid])
    if not np.all(np.isfinite(conditioned)) or np.any(fill_depth < 0):
        raise TerrainError("Conditioning output failed finite/nonnegative depth checks")

    def summary(array):
        return weighted_statistics(array, weights, valid=np.isfinite(array), cell_area=cell_area)

    grid = {"width": width, "height": height, "transform": list(transform[:6]),
            "horizontal_crs_wkt": crs.to_wkt(), "resolution_m": resolution,
            "cell_area_m2": cell_area, "source_window": [col0, row0, width, height]}
    geometry_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = {
        "schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION,
        "status": "completed_model_context", "observation_status": "not_field_observation",
        "source": {"file_name": source.name, "sha256": source_hash, "bytes": source_stat.st_size,
                   "declarations": metadata, "declaration_status": "operator_asserted_not_provider_verified",
                   "grid": source_grid},
        "field": {"geometry": canonical,
                  "geometry_sha256": hashlib.sha256(geometry_json.encode()).hexdigest(),
                  "support_area_m2": float(np.sum(weights) * cell_area)},
        "processing": {"grid": grid, "context_buffer_m": context_buffer_m,
                       "implementation_sha256": _sha256(Path(__file__)),
                       "domain": "buffered_field_bounding_rectangle",
                       "max_cells": max_cells, "gdal_cache_max_bytes": 64 * 1024 * 1024,
                       "resampling": "none", "void_filling": "none",
                       "dependencies": terrain_readiness()["versions"],
                       "conditioning": "pyflwdir.dem.fill_depressions; outlets=edge; connectivity=8; max_depth=-1",
                       "routing": "PyFlwDir D8 on filled DEM; each cell contributes its full projected area",
                       "slope": "pyflwdir.dem.slope on unconditioned DEM; 3x3 gradient in m/m; boundary unknown",
                       "edge_policy": "all rectangle-edge cells and downstream recipients flagged by PyFlwDir accuflux",
                       "twi": {"requested": include_twi, "formula": "ln((A / cell_width_m) / slope_m_per_m)",
                               "area_convention": "A includes the cell itself; D8 accumulated projected area in m2",
                               "contour_width_convention": "one square-cell width for all D8 directions",
                               "slope_floor": None, "pseudocount": None,
                               "sensitivity_status": "single_D8_grid_convention_not_sensitivity_validated"}},
        "field_summary": {"slope_m_per_m": summary(slope),
                          "potential_depression_fill_depth_m": summary(fill_depth),
                          "contributing_area_m2": summary(area),
                          "edge_influenced_support_area_m2": float(np.sum(weights[edge_influence]) * cell_area),
                          "flat_slope_support_area_m2": float(np.sum(weights[slope == 0]) * cell_area),
                          "twi": summary(twi) if include_twi else None},
        "limitations": [
            "Model-derived topographic screening only; no drainage diagnosis, ponding observation, or design authority.",
            "A finite buffer does not establish catchment completeness; edge-screened area is conditional on this DEM extent.",
            "Fill depth is a conditioning model delta, not water depth or evidence of an actual depression holding water.",
            "D8 routing, cell size, vertical uncertainty, source age and outlet assumptions affect all derivatives.",
            "PyFlwDir conditioning uses float32 priority elevations and slope output; subprecision features are unresolved.",
            "TWI uses unconditioned local slope and a fixed cell-width contour convention; no hydraulic calibration.",
        ],
        "artifacts": {},
    }
    # Create only after validation/computation; exclusive mkdir enforces no clobber.
    destination.mkdir(parents=True, exist_ok=False)
    products = {
        "dem_unconditioned_m": (elevation, "m"),
        "dem_conditioned_m": (conditioned, "m"),
        "potential_depression_fill_depth_m": (fill_depth, "m"),
        "slope_m_per_m": (slope, "m/m"),
        "d8_flow_direction": (directions, "PyFlwDir D8 codes"),
        "contributing_area_m2": (area, "m2"),
        "field_fraction": (weights, "fraction"),
        "dem_valid_mask": (np.ones(elevation.shape, dtype="uint8"), "boolean"),
        "edge_influence_mask": (edge_influence.astype("uint8"), "boolean"),
    }
    if include_twi:
        products["twi"] = (twi, "dimensionless conventional index")
        products["twi_valid_mask"] = (twi_valid.astype("uint8"), "boolean")
    for name, (array, unit) in products.items():
        path = destination / f"{name}.tif"
        write_geotiff(path, np.asarray(array, dtype="float64"), crs=crs, transform=transform,
                      nodata=float("nan"), band_names=[name],
                      metadata={"schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION,
                                "source_sha256": source_hash, "units": unit,
                                "evidence_kind": "model_output" if name != "dem_unconditioned_m" else "source_raster_copy"})
        result["artifacts"][name] = {"path": path.name, "sha256": _sha256(path),
                                     "bytes": path.stat().st_size, "units": unit}
    manifest = destination / "terrain.json"
    manifest.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
