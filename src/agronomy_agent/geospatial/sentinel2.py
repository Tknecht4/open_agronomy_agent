"""Strict, bounded Earth Search Sentinel-2 C1 L2A single-scene preparation.

STAC admission and raster interpretation are separate. No network occurs here;
callers supply already admitted local or bounded-proxy COG hrefs. Heavy raster
libraries load only when a scene is prepared.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

from agronomy_agent.field_imagery import _clean_asset, _valid_geometry
from .raster import fractional_weights, weighted_statistics

PROVIDER_ID = "sentinel2-c1-earth-search"
COLLECTION = "sentinel-2-c1-l2a"
PROCESS_VERSION = "sentinel2-c1-l2a-chip-v2-native20m-source-qa"
BAND_KEYS = ("blue", "green", "red", "nir08", "swir16", "swir22")
BAND_CODES = ("B02", "B03", "B04", "B8A", "B11", "B12")
ALL_KEYS = (*BAND_KEYS, "scl")
RESOLUTIONS = {"blue": 10, "green": 10, "red": 10, "nir08": 20,
               "swir16": 20, "swir22": 20, "scl": 20}
MAX_SIDE = 256
MAX_NATIVE_CELLS = 512 * 512
CLEAR_SCL = (4, 5, 6)
CLOUD_SHADOW_SCL = (2, 3, 8, 9, 10)


def _finite(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _instant(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError(f"{name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{name} must be UTC")
    return value


def _raster_band(asset: dict[str, Any], key: str) -> dict[str, Any]:
    rows = asset.get("raster:bands")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"{key} needs one raster:bands declaration")
    band = rows[0]
    dtype = "uint8" if key == "scl" else "uint16"
    if (band.get("data_type") != dtype or type(band.get("nodata")) is not int or
            band.get("nodata") != 0):
        raise ValueError(f"{key} unsupported dtype/nodata")
    if _finite(band.get("spatial_resolution"), f"{key} resolution") != RESOLUTIONS[key]:
        raise ValueError(f"{key} resolution mismatch")
    if key == "scl":
        if "scale" in band and _finite(band["scale"], "SCL scale") != 1:
            raise ValueError("SCL must be unscaled")
        if "offset" in band and _finite(band["offset"], "SCL offset") != 0:
            raise ValueError("SCL must be unscaled")
    else:
        # Current C1 encoding is independently evidenced in STAC, ESA product
        # XML and sampled TIFF headers. New encodings require a new admission.
        if not math.isclose(_finite(band.get("scale"), f"{key} scale"), .0001, abs_tol=1e-12):
            raise ValueError(f"{key} unsupported reflectance scale")
        if not math.isclose(_finite(band.get("offset"), f"{key} offset"), -.1, abs_tol=1e-9):
            raise ValueError(f"{key} unsupported reflectance offset")
    return dict(band)


def _validate_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Admit only evidenced C1 L2A metadata; preserve exact source identity."""
    if not isinstance(raw, dict) or raw.get("collection") != COLLECTION:
        raise ValueError("unexpected Sentinel-2 collection")
    item_id = raw.get("id")
    if not isinstance(item_id, str) or not re.fullmatch(r"S2[ABC]_T[0-9A-Z]{5}_\d{8}T\d{6}_L2A", item_id):
        raise ValueError("unexpected Sentinel-2 item identity")
    props, source_assets = raw.get("properties"), raw.get("assets")
    if not isinstance(props, dict) or not isinstance(source_assets, dict):
        raise ValueError("incomplete Sentinel-2 item")
    if props.get("s2:product_type") != "S2MSI2A":
        raise ValueError("unexpected Sentinel-2 product type")
    baseline = props.get("s2:processing_baseline")
    if baseline not in {"05.00", "05.09", "05.10", "05.11", "05.12", "05.13"}:
        raise ValueError("unsupported or unknown processing baseline")
    product_uri = props.get("s2:product_uri")
    product_match = re.fullmatch(
        r"(S2[ABC])_MSIL2A_(\d{8}T\d{6})_N(\d{4})_R(\d{3})_T([0-9A-Z]{5})_(\d{8}T\d{6})\.SAFE",
        product_uri if isinstance(product_uri, str) else "")
    if (not product_match or product_match[1] != item_id[:3] or
            product_match[3] != baseline.replace(".", "") or
            product_match[5] != item_id[5:10]):
        raise ValueError("mission, tile or baseline and product URI disagree")
    # SAFE names use datatake time; STAC item names use granule time. These
    # timestamps need not match, but both SAFE timestamps must be real dates.
    for stamp in (product_match[2], product_match[6]):
        datetime.strptime(stamp, "%Y%m%dT%H%M%S")
    acquired = _instant(props.get("datetime"), "acquisition")
    available = _instant(props.get("created"), "availability")
    cloud = _finite(props.get("eo:cloud_cover"), "scene cloud cover")
    if not 0 <= cloud <= 100:
        raise ValueError("scene cloud cover outside 0..100")
    elevation = _finite(props.get("view:sun_elevation"), "sun elevation")
    if not 0 <= elevation <= 90:
        raise ValueError("sun elevation outside 0..90")
    zenith = 90 - elevation
    if zenith > 70:
        raise ValueError("mean solar zenith exceeds 70 degrees")
    epsg = props.get("proj:epsg")
    if type(epsg) is not int or not 1 <= epsg <= 999999:
        raise ValueError("missing projected CRS metadata")
    clean: dict[str, dict[str, Any]] = {}
    for key in ALL_KEYS:
        asset = source_assets.get(key)
        if not isinstance(asset, dict):
            raise ValueError(f"missing {key} asset")
        href = _clean_asset(asset.get("href"), PROVIDER_ID)
        if (not href or href != asset.get("href") or
                not href.endswith("/" + item_id + "/" +
                                  ("SCL" if key == "scl" else BAND_CODES[BAND_KEYS.index(key)]) + ".tif")):
            raise ValueError(f"{key} asset host/path mismatch")
        if asset.get("roles") != (["data"] if key == "scl" else ["data", "reflectance"]):
            raise ValueError(f"{key} asset roles mismatch")
        band = _raster_band(asset, key)
        if _finite(asset.get("gsd"), f"{key} gsd") != RESOLUTIONS[key]:
            raise ValueError(f"{key} GSD mismatch")
        declared_shape, declared_transform = asset.get("proj:shape"), asset.get("proj:transform")
        if (not isinstance(declared_shape, list) or len(declared_shape) != 2 or
                any(type(v) is not int or v < 1 for v in declared_shape) or
                not isinstance(declared_transform, list) or len(declared_transform) != 6 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in declared_transform)):
            raise ValueError(f"{key} incomplete projected grid")
        if (not math.isclose(declared_transform[0], RESOLUTIONS[key], abs_tol=1e-9) or
                not math.isclose(declared_transform[4], -RESOLUTIONS[key], abs_tol=1e-9) or
                declared_transform[1] != 0 or declared_transform[3] != 0):
            raise ValueError(f"{key} unsupported projected grid")
        if key != "scl":
            eo = asset.get("eo:bands")
            if (not isinstance(eo, list) or len(eo) != 1 or
                    not isinstance(eo[0], dict) or
                    eo[0].get("name") != BAND_CODES[BAND_KEYS.index(key)]):
                raise ValueError(f"{key} spectral role mismatch")
        clean[key] = {"href": href, "id": f"{COLLECTION}:{item_id}:{key}",
                      "raster_bands": [band], "gsd": RESOLUTIONS[key],
                      "proj:shape": declared_shape, "proj:transform": declared_transform,
                      "roles": asset["roles"]}
    reference = clean["scl"]["proj:transform"]
    for key in ALL_KEYS:
        tr = clean[key]["proj:transform"]
        if not math.isclose(tr[2], reference[2], abs_tol=1e-6) or not math.isclose(tr[5], reference[5], abs_tol=1e-6):
            raise ValueError("Sentinel-2 band origins disagree")
    try:
        source_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ValueError("nonserializable or nonfinite source metadata") from exc
    return {"id": f"{COLLECTION}:{item_id}", "collection": COLLECTION,
            "acquired_at": acquired, "availability_at": available,
            "scene_cloud_percent": cloud, "baseline": baseline,
            "product_uri": product_uri, "sun_zenith_deg": zenith,
            "projected_epsg": epsg, "assets": clean,
            "source_metadata_sha256": source_hash,
            "processing_generation": "ESA_reprocessed_unknown" if baseline == "05.09" else "baseline_recorded_not_inferred"}


def _bounded_distance(buffer_m: int, name: str) -> int:
    if type(buffer_m) is not int or not 0 <= buffer_m <= 200 or (name == "cloud_buffer_m" and buffer_m % 20):
        raise ValueError(f"{name} must be an integer from 0 to 200" +
                         (" in 20 m steps" if name == "cloud_buffer_m" else ""))
    return buffer_m


def _validate_header(src: Any, asset: dict[str, Any], key: str, expected_epsg: int, reference: Any = None) -> None:
    from rasterio.crs import CRS
    from rasterio.transform import Affine
    if src.count != 1 or src.crs is None or not src.crs.is_projected:
        raise RuntimeError(f"{key} needs one projected COG band")
    if (src.width > 12000 or src.height > 12000 or not src.block_shapes or
            any(rows * cols * (1 if key == "scl" else 2) > 16 * 1024 * 1024
                for rows, cols in src.block_shapes)):
        raise RuntimeError(f"{key} source block exceeds memory budget")
    if not math.isclose(src.crs.linear_units_factor[1], 1, abs_tol=1e-9):
        raise RuntimeError(f"{key} CRS is not metre based")
    expected = Affine.from_gdal(asset["proj:transform"][2], asset["proj:transform"][0],
                                 asset["proj:transform"][1], asset["proj:transform"][5],
                                 asset["proj:transform"][3], asset["proj:transform"][4])
    if (src.height != asset["proj:shape"][0] or src.width != asset["proj:shape"][1] or
            any(not math.isclose(a, b, abs_tol=1e-6) for a, b in zip(src.transform[:6], expected[:6]))):
        raise RuntimeError(f"{key} COG grid contradicts STAC")
    if reference is not None and src.crs != reference:
        raise RuntimeError(f"{key} COG CRS disagrees")
    band = asset["raster_bands"][0]
    if src.dtypes[0] != band["data_type"] or src.nodata != 0:
        raise RuntimeError(f"{key} COG dtype/nodata contradicts STAC")
    expected_scale = 1 if key == "scl" else band["scale"]
    expected_offset = 0 if key == "scl" else band["offset"]
    if (not math.isclose(src.scales[0], expected_scale, abs_tol=1e-10) or
            not math.isclose(src.offsets[0], expected_offset, abs_tol=1e-9)):
        raise RuntimeError(f"{key} COG scale/offset contradicts STAC")
    if src.crs != CRS.from_epsg(expected_epsg):
        raise RuntimeError(f"{key} COG CRS contradicts STAC")


def _prepare_scene(item: dict[str, Any], local_hrefs: dict[str, str], geometry: dict[str, Any], *,
                  cloud_buffer_m: int = 60, edge_buffer_m: int = 20) -> dict[str, Any]:
    """Prepare one bounded 20 m scene with native DN, QA and fractional support."""
    import numpy as np
    import rasterio
    import scipy
    import shapely
    import pyproj
    from rasterio.windows import Window
    from rasterio.warp import reproject, Resampling
    from scipy.ndimage import binary_dilation
    from shapely.geometry import shape
    from shapely.ops import transform as shapely_transform
    from pyproj import Transformer

    cloud_buffer_m = _bounded_distance(cloud_buffer_m, "cloud_buffer_m")
    edge_buffer_m = _bounded_distance(edge_buffer_m, "edge_buffer_m")
    if item.get("collection") != COLLECTION or set(local_hrefs) != set(ALL_KEYS):
        raise ValueError("incomplete Sentinel-2 source/transport")
    polygon_json, _ = _valid_geometry(geometry)
    for key in ALL_KEYS:
        if key not in item.get("assets", {}):
            raise ValueError(f"missing normalized {key} asset")
    with rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024,
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                      GDAL_HTTP_MAX_RETRY="0", VSI_CACHE="FALSE"), ExitStack() as stack:
        sources = {key: stack.enter_context(rasterio.open(local_hrefs[key], sharing=False)) for key in ALL_KEYS}
        reference = sources["scl"]
        for key in ALL_KEYS:
            _validate_header(sources[key], item["assets"][key], key, item["projected_epsg"], reference.crs)
        t = reference.transform
        for key in ALL_KEYS:
            src = sources[key]
            ratio = 2 if RESOLUTIONS[key] == 10 else 1
            if (src.width != reference.width * ratio or src.height != reference.height * ratio or
                    not math.isclose(src.transform.c, t.c, abs_tol=1e-6) or
                    not math.isclose(src.transform.f, t.f, abs_tol=1e-6)):
                raise RuntimeError("Sentinel-2 native grids do not share footprint")
        projector = Transformer.from_crs("EPSG:4326", reference.crs, always_xy=True)
        projected = shapely_transform(projector.transform, shape(polygon_json))
        if not projected.is_valid or projected.is_empty:
            raise ValueError("projected field is invalid")
        halo = cloud_buffer_m + edge_buffer_m + 20
        west, south, east, north = projected.buffer(halo).bounds
        col0 = math.floor((west - t.c) / 20)
        col1 = math.ceil((east - t.c) / 20)
        row0 = math.floor((t.f - north) / 20)
        row1 = math.ceil((t.f - south) / 20)
        height, width = row1 - row0, col1 - col0
        if height < 1 or width < 1 or height > MAX_SIDE or width > MAX_SIDE:
            raise ValueError("Sentinel-2 output exceeds 256 x 256 cells")
        if 4 * height * width > MAX_NATIVE_CELLS:
            raise ValueError("Sentinel-2 native read exceeds cell budget")
        window = Window(col0, row0, width, height)
        grid_transform = reference.window_transform(window)
        source_meta: dict[str, Any] = {}
        native: dict[str, Any] = {}
        invalids: dict[str, Any] = {}
        saturated: dict[str, Any] = {}
        for key in ALL_KEYS:
            src = sources[key]
            ratio = 2 if RESOLUTIONS[key] == 10 else 1
            native_window = Window(col0 * ratio, row0 * ratio, width * ratio, height * ratio)
            masked = src.read(1, window=native_window, boundless=True, masked=True, fill_value=0)
            raw = np.asarray(masked.data).copy()
            saturated[key] = (raw == 65535) if key != "scl" else np.zeros(raw.shape, dtype=bool)
            invalid = np.ma.getmaskarray(masked).copy() | (raw == 0) | saturated[key]
            native[key] = raw
            invalids[key] = invalid
            source_meta[key] = {"asset_id": item["assets"][key]["id"],
                                "crs": src.crs.to_string(), "dtype": src.dtypes[0],
                                "nodata": src.nodata, "scale": src.scales[0],
                                "offset": src.offsets[0], "shape": list(raw.shape),
                                "window": [int(native_window.col_off), int(native_window.row_off),
                                           int(native_window.width), int(native_window.height)],
                                "transform": list(src.window_transform(native_window)[:6]),
                                "raster_bands": item["assets"][key]["raster_bands"]}
        scl = native["scl"]
        source_invalid = invalids["scl"].copy()
        source_saturated = np.zeros((height, width), dtype=bool)
        prepared = []
        for key in BAND_KEYS:
            src = sources[key]
            raw = native[key]
            invalid = invalids[key]
            if RESOLUTIONS[key] == 10:
                reduced = np.zeros((height, width), dtype=np.float64)
                fraction = np.zeros((height, width), dtype=np.float64)
                source_window = Window(col0 * 2, row0 * 2, width * 2, height * 2)
                source_transform = src.window_transform(source_window)
                reproject(np.where(invalid, 0, raw).astype(np.float64), reduced,
                          src_transform=source_transform, src_crs=src.crs,
                          dst_transform=grid_transform, dst_crs=src.crs,
                          src_nodata=None, dst_nodata=None,
                          resampling=Resampling.average)
                reproject((~invalid).astype(np.float64), fraction,
                          src_transform=source_transform, src_crs=src.crs,
                          dst_transform=grid_transform, dst_crs=src.crs,
                          src_nodata=None, dst_nodata=None,
                          resampling=Resampling.average)
                source_invalid |= ~np.isclose(fraction, 1, rtol=0, atol=1e-12)
                source_saturated |= saturated[key].reshape(height, 2, width, 2).any(axis=(1, 3))
            else:
                reduced = raw.astype(np.float64)
                source_invalid |= invalid
                source_saturated |= saturated[key]
            meta = item["assets"][key]["raster_bands"][0]
            prepared.append(reduced * meta["scale"] + meta["offset"])
        bands = np.stack(prepared)
        # A halo is available only where every band and SCL has source support.
        # Padding marks any missing context beyond the requested bounded window.
        obscured = np.isin(scl, CLOUD_SHADOW_SCL)
        radius = cloud_buffer_m // 20
        if radius:
            yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
            structure = (xx * xx + yy * yy) <= radius * radius
            cloud_adjacent = binary_dilation(obscured, structure=structure, border_value=1)
            unsupported_halo = binary_dilation(source_invalid, structure=structure, border_value=1)
        else:
            cloud_adjacent = obscured
            unsupported_halo = source_invalid
        # Fixed one-cell source guard. A user-selected interior buffer cannot
        # turn this source-quality screening off. The raster boundary is unknown
        # unless the requested halo proves source support around it.
        edge_guard = binary_dilation(source_invalid,
                                     structure=np.ones((3, 3), dtype=bool),
                                     border_value=1)
        clear_class = np.isin(scl, CLEAR_SCL)
        valid = (~source_invalid) & (~unsupported_halo) & (~edge_guard) & clear_class & (~cloud_adjacent)
        bands[:, ~valid] = np.nan
        weights = fractional_weights(projected, grid_transform, width, height)
        interior_geometry = projected.buffer(-edge_buffer_m) if edge_buffer_m else projected
        interior_weights = fractional_weights(interior_geometry, grid_transform, width, height)
        cell_area = 400.0
        support = weights > 0
        def area(mask: Any, chosen: Any = weights) -> float:
            return float(chosen[mask & (chosen > 0)].sum(dtype=np.float64)) * cell_area
        ndvi = np.full((height, width), np.nan, dtype=np.float64)
        ndmi = np.full((height, width), np.nan, dtype=np.float64)
        index_reasons: dict[str, Any] = {}
        index_eligible_areas: dict[str, float] = {}
        stats: dict[str, Any] = {}
        interior_stats: dict[str, Any] = {}
        for label, other, output in (("NDVI", bands[2], ndvi), ("NDMI", bands[4], ndmi)):
            nir = bands[3]
            negative = valid & ((nir < 0) | (other < 0))
            small_sum = valid & ~negative & ((nir + other) <= 1e-6)
            eligible = valid & ~negative & ~small_sum
            np.divide(nir - other, nir + other, out=output, where=eligible)
            index_reasons[label] = {"negative_reflectance": area(negative),
                                    "nonpositive_denominator": area(small_sum)}
            index_eligible_areas[label] = area(eligible)
            if not math.isclose(index_eligible_areas[label] + sum(index_reasons[label].values()),
                                area(valid), rel_tol=0, abs_tol=1e-6):
                raise RuntimeError("index support partition contradiction")
            stats[label] = weighted_statistics(output, weights, valid=eligible, cell_area=cell_area)
            interior_stats[label] = weighted_statistics(output, interior_weights, valid=eligible, cell_area=cell_area)
        arrays = {"bands": bands, "ndvi": ndvi, "ndmi": ndmi, "valid_mask": valid,
                  "field_weights": weights, "field_mask": support,
                  "interior_weights": interior_weights, "scl": scl,
                  "source_invalid_mask": source_invalid,
                  "source_saturated_mask": source_saturated}
        for key in ALL_KEYS:
            arrays[f"raw_dn_{key}"] = native[key]
            arrays[f"source_invalid_{key}"] = invalids[key]
            if key != "scl":
                arrays[f"source_saturated_{key}"] = saturated[key]
        excluded = {"source_invalid": source_invalid,
                    "source_saturated": source_saturated, "scl_no_data": scl == 0,
                    "scl_defective": scl == 1, "scl_cast_shadow": scl == 2,
                    "scl_cloud_shadow": scl == 3, "scl_unclassified": scl == 7,
                    "scl_medium_cloud": scl == 8, "scl_high_cloud": scl == 9,
                    "scl_unknown_class": ~np.isin(scl, np.arange(12)),
                    "scl_cirrus": scl == 10, "scl_snow_ice": scl == 11,
                    "cloud_shadow_adjacency": cloud_adjacent & ~obscured,
                    "unsupported_qa_halo": unsupported_halo,
                    "source_edge_guard": edge_guard}
        qa = {"field_area_m2": area(support), "valid_area_m2": area(valid),
              "valid_area_fraction": area(valid) / area(support) if area(support) else None,
              "interior_field_area_m2": area(interior_weights > 0, interior_weights),
              "interior_valid_area_m2": area(valid, interior_weights),
              "water_area_m2": area(valid & (scl == 6)),
              "excluded_area_m2_by_reason": {k: area(v) for k, v in excluded.items()},
              "index_eligible_area_m2": index_eligible_areas,
              "index_undefined_area_m2_by_reason": index_reasons,
              "overlap_note": "Exclusion reason areas overlap; index undefined reasons are disjoint within each index."}
        return {"arrays": arrays,
                "grid": {"crs": reference.crs.to_string(), "transform": list(grid_transform[:6]),
                         "width": width, "height": height, "resolution_m": 20},
                "source_band_metadata": source_meta, "qa": qa,
                "zonal_stats": stats, "interior_zonal_stats": interior_stats,
                "process_spec": {"version": PROCESS_VERSION, "band_keys": list(BAND_KEYS),
                                 "ndvi_nir_band": "B8A", "ndmi_nir_band": "B8A",
                                 "cloud_buffer_m": cloud_buffer_m, "edge_buffer_m": edge_buffer_m,
                                 "source_edge_guard_m": 20,
                                 "spectral_special_values": {"nodata_dn": 0, "saturated_dn": 65535},
                                 "native_alignment": "10m complete 2x2 area mean to source 20m grid; categorical native",
                                 "libraries": {"numpy": np.__version__, "rasterio": rasterio.__version__,
                                               "gdal": rasterio.__gdal_version__,
                                               "pyproj": pyproj.__version__, "proj": pyproj.proj_version_str,
                                               "shapely": shapely.__version__, "scipy": scipy.__version__}},
                "limitations": ["SCL screening does not prove cloud-free crop observations.",
                                "PB <05.13 may contain nonzero artificial 10m swath-edge pixels; detector footprint masks are unavailable from these STAC assets.",
                                "No registration, temporal harmonization, field truth or agronomic validation is inferred."]}


class Sentinel2Refusal(ValueError):
    """Public-safe refusal with a fixed, source-independent reason code."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "zenith" in message or "sun elevation" in message:
        return "solar_zenith_exceeds_limit" if "exceeds" in message else "solar_geometry_unknown"
    if "scale" in message or "offset" in message or "radiometry" in message or "dtype/nodata" in message:
        return "source_radiometry_mismatch"
    if "256" in message or "cell budget" in message or "block exceeds memory budget" in message:
        return "resource_limit"
    if "grid" in message or "crs" in message or "origin" in message or "footprint" in message:
        return "source_grid_mismatch"
    if "asset" in message or "band" in message:
        return "source_asset_unavailable"
    if "polygon" in message or "field" in message:
        return "invalid_geometry"
    return "source_metadata_invalid"


def validate_item(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return _validate_item(raw)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise Sentinel2Refusal(_reason(exc)) from exc


def prepare_scene(item: dict[str, Any], local_hrefs: dict[str, str], geometry: dict[str, Any], *,
                  cloud_buffer_m: int = 60, edge_buffer_m: int = 20) -> dict[str, Any]:
    try:
        return _prepare_scene(item, local_hrefs, geometry,
                              cloud_buffer_m=cloud_buffer_m, edge_buffer_m=edge_buffer_m)
    except (ValueError, RuntimeError, TypeError, KeyError, OSError, OverflowError) as exc:
        raise Sentinel2Refusal(_reason(exc)) from exc
