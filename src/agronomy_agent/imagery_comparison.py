"""Compare two integrity-checked polygon chips on shared native pixels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from math import isclose, isfinite

import numpy as np
from pyproj import CRS

from agronomy_agent.geospatial.raster import weighted_statistics
from agronomy_agent.imagery_store import ImageryStore

INDICES = ("NDVI", "NDMI")
GRID_EPS_M = 1e-6
WEIGHT_EPS = 1e-8
RECIPE = "two_date_overlap.v1"
PROVIDERS = {
    "hls-s30-planetary-computer": 30,
    "hls-l30-planetary-computer": 30,
    "sentinel2-c1-earth-search": 20,
}


@dataclass(frozen=True)
class Chip:
    receipt: dict
    weights: np.ndarray
    qa_clear: np.ndarray
    indices: dict[str, np.ndarray]


def _instant(receipt: dict) -> datetime:
    instant = datetime.fromisoformat(receipt["source"]["acquired_at"])
    if instant.tzinfo is None:
        raise ValueError("acquisition time has no timezone")
    return instant.astimezone(timezone.utc)


def _grid(receipt: dict) -> tuple[CRS, float, float, float, int, int]:
    grid = receipt["grid"]
    crs = CRS.from_user_input(grid["crs"])
    a, b, west, d, e, north = grid["transform"]
    width, height = grid["width"], grid["height"]
    if (
        not crs.is_projected or len(crs.axis_info) != 2
        or any(axis.unit_conversion_factor != 1 for axis in crs.axis_info)
        or not all(isfinite(value) for value in (a, b, west, d, e, north))
        or a != PROVIDERS[receipt["provider_id"]] or a != -e
        or a != grid["resolution_m"] or b != 0 or d != 0
        or type(width) is not int or type(height) is not int or not 0 < width <= 4096
        or not 0 < height <= 4096 or width * height > 4_000_000
    ):
        raise ValueError("unsupported comparison grid")
    return crs, a, west, north, width, height


def _validate_arrays(chip: Chip, shape: tuple[int, int]) -> None:
    if (
        chip.qa_clear.dtype != np.bool_ or chip.qa_clear.shape != shape
        or chip.weights.shape != shape or not np.isfinite(chip.weights).all()
        or np.any((chip.weights < 0) | (chip.weights > 1))
        or set(chip.indices) != set(INDICES)
    ):
        raise ValueError("invalid analysis arrays")
    for values in chip.indices.values():
        if (
            values.shape != shape or values.dtype.kind != "f"
            or np.isinf(values).any()
            or np.any(np.isfinite(values) & ((values < -1) | (values > 1)))
        ):
            raise ValueError("invalid analysis index")


def _offset(distance_m: float, cell_m: float) -> int | None:
    if not isfinite(distance_m):
        return None
    offset = round(distance_m / cell_m)
    return offset if isclose(distance_m, offset * cell_m, abs_tol=GRID_EPS_M, rel_tol=0) else None


def _axis_overlap(offset: int, first_size: int, second_size: int) -> tuple[slice, slice]:
    start, stop = max(0, offset), min(first_size, offset + second_size)
    return slice(start, stop), slice(start - offset, stop - offset)


def _source_ref(chip: Chip, instant: datetime) -> dict:
    return {
        "scene_id": chip.receipt["scene_id"],
        "chip_hash": chip.receipt["chip_hash"],
        "process_hash": chip.receipt["process_hash"],
        "acquired_at": instant.isoformat(),
    }


def compare(first: Chip, second: Chip, *, field_area_m2: float) -> tuple[dict, dict[str, np.ndarray]]:
    """Return a bounded evidence receipt and NaN-masked native delta arrays."""
    result = {
        "recipe": RECIPE,
        "evidence_role": "processed_observation",
        "scouting_support": "no_imagery_target",
        "field_action_authority": "not_authorized",
        "indices": {},
    }

    def unavailable(status: str, **details) -> tuple[dict, dict]:
        return {**result, "status": status, **details}, {}

    if type(field_area_m2) not in (int, float) or not isfinite(field_area_m2) or field_area_m2 <= 0:
        return unavailable("invalid_input")
    try:
        (before_time, before), (after_time, after) = sorted(
            [(_instant(first.receipt), first), (_instant(second.receipt), second)],
            key=lambda item: item[0],
        )
        a, b = before.receipt, after.receipt
        for receipt in (a, b):
            if not all(receipt.get(key) for key in (
                "geometry_hash", "chip_hash", "process_hash", "process_version", "scene_id",
            )):
                raise ValueError("missing lineage")
            if receipt["source"]["scene_id"] != receipt["scene_id"]:
                raise ValueError("scene identity mismatch")
        result.update(before=_source_ref(before, before_time), after=_source_ref(after, after_time))
        if a["scene_id"] == b["scene_id"] or before_time.date() == after_time.date():
            return unavailable("same_acquisition_date")
        if a.get("sampling") is not None or b.get("sampling") is not None:
            return unavailable("polygon_required")
        if a["geometry_hash"] != b["geometry_hash"]:
            return unavailable("different_field_geometry")
        provider = a["provider_id"]
        if (
            provider not in PROVIDERS or provider != b["provider_id"]
            or a["source"]["collection"] != b["source"]["collection"]
            or a["process_hash"] != b["process_hash"]
            or a["process_version"] != b["process_version"]
        ):
            return unavailable("different_processing")
        if provider == "sentinel2-c1-earth-search":
            baseline = a["source"].get("processing_baseline")
            if not baseline or baseline != b["source"].get("processing_baseline"):
                return unavailable("different_or_unknown_baseline")
        if not all(receipt["status"] in ("available", "empty_valid_area") for receipt in (a, b)):
            return unavailable("unavailable_source")
        a_crs, cell, ax, ay, aw, ah = _grid(a)
        b_crs, _, bx, by, bw, bh = _grid(b)
        _validate_arrays(before, (ah, aw))
        _validate_arrays(after, (bh, bw))
    except (KeyError, TypeError, ValueError, OverflowError, RuntimeError):
        return unavailable("invalid_input")

    result.update(provider_id=provider, geometry_hash=a["geometry_hash"], field_area_m2=field_area_m2)
    if not a_crs.equals(b_crs):
        return unavailable("different_grid", grid_reason="different_crs")
    col = _offset(bx - ax, cell)
    row = _offset(ay - by, cell)
    if col is None or row is None:
        return unavailable("different_grid", grid_reason="subpixel_shift")
    ar, br = _axis_overlap(row, ah, bh)
    ac, bc = _axis_overlap(col, aw, bw)
    if ar.stop <= ar.start or ac.stop <= ac.start:
        return unavailable("no_grid_overlap")
    a_sl, b_sl = (ar, ac), (br, bc)
    w0, w1 = before.weights[a_sl], after.weights[b_sl]
    if not np.allclose(w0, w1, atol=WEIGHT_EPS, rtol=0):
        return unavailable("inconsistent_field_weights")
    weights = np.minimum(w0, w1).astype(np.float64)
    cell_area = cell * cell
    grid_area = float(weights.sum()) * cell_area
    if grid_area > field_area_m2 and not isclose(grid_area, field_area_m2, rel_tol=1e-7, abs_tol=1e-7):
        return unavailable("inconsistent_field_area")
    if grid_area == 0:
        return unavailable("no_field_overlap")

    qa = before.qa_clear[a_sl] & after.qa_clear[b_sl]
    result.update(
        grid={
            "crs": a_crs.to_string(), "resolution_m": cell,
            "transform": [cell, 0, ax + ac.start * cell, 0, -cell, ay - ar.start * cell],
            "width": ac.stop - ac.start, "height": ar.stop - ar.start,
        },
        overlap_field_area_m2=grid_area,
        common_qa_area_m2=float(weights[qa].sum()) * cell_area,
    )
    arrays = {}
    for index in INDICES:
        old = before.indices[index][a_sl].astype(np.float64)
        new = after.indices[index][b_sl].astype(np.float64)
        use = (weights > 0) & qa & np.isfinite(old) & np.isfinite(new)
        if not use.any():
            result["indices"][index] = {"status": "no_common_valid_pixels", "area_m2": 0.0, "field_fraction": 0.0}
            continue
        change = np.full(weights.shape, np.nan)
        np.subtract(new, old, where=use, out=change)
        summary = weighted_statistics(change, weights, cell_area=cell_area)
        result["indices"][index] = {
            "status": "observed_on_overlap",
            "area_m2": summary["area_m2"],
            "field_fraction": min(1.0, summary["area_m2"] / field_area_m2),
            "pixel_count": int(use.sum()),
            "before_mean": weighted_statistics(old, weights, valid=use, cell_area=cell_area)["mean"],
            "after_mean": weighted_statistics(new, weights, valid=use, cell_area=cell_area)["mean"],
            "mean_delta": summary["mean"],
        }
        arrays[index] = change
    return {**result, "status": "descriptive_only" if arrays else "no_common_valid_pixels"}, arrays


def _load_chip(store: ImageryStore, chip_hash: str) -> Chip | None:
    receipt = store.get_by_chip_hash(chip_hash)
    data = store.read_verified_artifact(chip_hash, "npz")
    if receipt is None or data is None:
        return None
    # Validate the native allocation cap before decompressing arrays.
    _grid(receipt)
    with np.load(BytesIO(data), allow_pickle=False) as arrays:
        qa = arrays["valid_mask"]
        ndvi = arrays["ndvi"]
        if "ndmi" in arrays:
            ndmi = arrays["ndmi"]
        else:
            # Polygon HLS receipts predating this comparison retain the decoded bands.
            nir, swir = arrays["bands"][[3, 4]].astype(np.float64)
            denominator = nir + swir
            eligible = qa & np.isfinite(nir) & np.isfinite(swir) & (nir >= 0) & (swir >= 0) & (denominator > 1e-6)
            ndmi = np.full(nir.shape, np.nan)
            np.divide(nir - swir, denominator, out=ndmi, where=eligible)
        return Chip(receipt, arrays["field_weights"], qa, {"NDVI": ndvi, "NDMI": ndmi})


def _change_overlay(delta: np.ndarray, grid: dict, geometry: dict) -> dict:
    from PIL import Image
    from agronomy_agent.imagery_overlay import reproject_preview

    # Fixed signed scale, shared across dates and both indices.
    level = np.clip(np.nan_to_num(delta) / .2, -1, 1)
    center = np.array([242, 242, 242])
    negative, positive = np.array([164, 53, 18]), np.array([25, 108, 176])
    rgb = center + np.abs(level[..., None]) * (np.where(level[..., None] < 0, negative, positive) - center)
    rgba = np.empty((*delta.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb.astype(np.uint8)
    rgba[:, :, 3] = np.where(np.isfinite(delta), 255, 0)
    output = BytesIO()
    Image.fromarray(rgba).save(output, format="PNG")
    overlay = reproject_preview(output.getvalue(), grid, clip_geometry=geometry)
    if not overlay["display_has_support"]:
        raise ValueError("No supported cells at display resolution")
    return overlay


def main() -> None:
    import argparse
    import json
    from pathlib import Path

    from agronomy_agent.geospatial.geometry import project_geometry
    from shapely.errors import GEOSException

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--chips", required=True, nargs=2)
    parser.add_argument("--maps", action="store_true")
    args = parser.parse_args()
    store = ImageryStore(args.cache_root, read_only=True)
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    try:
        first, second = (_load_chip(store, identity) for identity in args.chips)
        if first is None or second is None:
            print(json.dumps({"status": "unavailable_source", "indices": {}}))
            return
        field = project_geometry(geometry, first.receipt["grid"]["crs"])
        result, deltas = compare(first, second, field_area_m2=field.area)
        if args.maps and deltas:
            maps = {}
            for name, delta in deltas.items():
                try:
                    maps[name] = _change_overlay(delta, result["grid"], geometry)
                except (OSError, RuntimeError, ValueError, GEOSException):
                    # Display availability is independent of valid native values.
                    continue
            result["maps"] = maps
            result["map_status"] = "available" if len(maps) == len(deltas) else "limited"
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        result = {"status": "unavailable_source", "indices": {}}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
