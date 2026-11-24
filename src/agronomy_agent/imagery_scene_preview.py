"""Bounded true-color display of the exact selected HLS or Sentinel-2 scene."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import httpx

from agronomy_agent.field_imagery import _dates, _valid_search_geometry
from agronomy_agent.geospatial.cog import bounded_cog_proxy, transfer_budget
from agronomy_agent.imagery_budget import StorageRefusal, reserve_cache

MAX_PREVIEW_BYTES = 1536 * 1024
_MAX_SIDE = 384
_VERSION = "true-color-v1"
_SENTINEL = "sentinel2-c1-earth-search"
_PNG = b"\x89PNG\r\n\x1a\n"


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def request_identity(geometry: dict, provider: str, scene: str, start: str, end: str) -> tuple[dict, dict]:
    from agronomy_agent.field_imagery import _provider
    import re

    geometry, _ = _valid_search_geometry(geometry)
    if provider not in {_SENTINEL, "hls-s30-planetary-computer", "hls-l30-planetary-computer"}:
        raise ValueError("Unsupported image provider.")
    collection = _provider(provider)["collection"]
    if not re.fullmatch(re.escape(collection) + r":[A-Za-z0-9._-]{1,160}", scene):
        raise ValueError("Scene does not belong to the selected provider.")
    _dates(start, end)
    if provider == _SENTINEL and geometry["type"] != "Polygon":
        raise ValueError("Sentinel-2 preview requires a saved field polygon.")
    return geometry, {"version": _VERSION, "provider_id": provider, "scene_id": scene,
                      "geometry_sha256": _digest(geometry), "start_date": start, "end_date": end}


def valid_preview(value: Any, identity: dict) -> bool:
    try:
        if not isinstance(value, dict) or any(value.get(key) != expected for key, expected in identity.items()):
            return False
        png = base64.b64decode(value["png_base64"], validate=True)
        (south, west), (north, east) = value["bounds"]
        date = datetime.fromisoformat(value["acquired_at"].replace("Z", "+00:00")).date().isoformat()
        return (
            value["status"] == "available" and value["display_crs"] == "EPSG:3857"
            and value["display_resampling"] == "nearest" and value["role"] == "display_only"
            and identity["start_date"] <= date <= identity["end_date"]
            and all(type(item) in {int, float} and math.isfinite(item) for item in (south, west, north, east))
            and -85.06 <= south < north <= 85.06 and -180 <= west < east <= 180
            and png.startswith(_PNG) and len(png) <= MAX_PREVIEW_BYTES
            and hashlib.sha256(png).hexdigest() == value["image_sha256"]
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _cached(path: Path, identity: dict) -> dict | None:
    try:
        if path.is_symlink():
            return None
        with path.open("rb") as source:
            data = source.read(2 * MAX_PREVIEW_BYTES + 1)
        if len(data) > 2 * MAX_PREVIEW_BYTES:
            return None
        receipt = json.loads(data)
        image = receipt["image"]
        if _digest(image) == receipt["sha256"] and valid_preview(image, identity):
            return {**image, "cache_hit": True}
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return None


def _render(geometry: dict, identity: dict) -> dict:
    import numpy as np
    from PIL import Image
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform_bounds
    from shapely.geometry import shape
    from agronomy_agent.imagery_analytics import _scene_item, _signed_hrefs, _validate_cog_radiometry, _validate_scale
    from agronomy_agent.sentinel2_analytics import _request, _scene
    from agronomy_agent.geospatial.sentinel2 import _validate_header

    provider, scene = identity["provider_id"], identity["scene_id"]
    start, end = identity["start_date"], identity["end_date"]
    is_sentinel = provider == _SENTINEL
    keys = ("red", "green", "blue") if is_sentinel else ("B04", "B03", "B02")
    if is_sentinel:
        item = _scene(_request(geometry, scene, start, end, 60, 20))
        hrefs = {key: item["assets"][key]["href"] for key in keys}
    else:
        item = _scene_item(geometry, provider, scene, start, end, preview_bands=keys)
        hrefs = _signed_hrefs(item)

    west, south, east, north = transform_bounds("EPSG:4326", "EPSG:3857", *shape(geometry).bounds)
    margin = max(100, .1 * max(east - west, north - south))
    bounds = west - margin, south - margin, east + margin, north + margin
    span_x, span_y = bounds[2] - bounds[0], bounds[3] - bounds[1]
    resolution = max(10 if is_sentinel else 30, max(span_x, span_y) / _MAX_SIDE)
    width, height = min(_MAX_SIDE, math.ceil(span_x / resolution)), min(_MAX_SIDE, math.ceil(span_y / resolution))
    transform = from_bounds(*bounds, width, height)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    valid = np.ones((height, width), dtype=bool)
    first_grid = None
    limit = 32 * 1024 * 1024
    with transfer_budget(limit, limit, max_requests=256), bounded_cog_proxy(hrefs) as (local, transfer):
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="0", GDAL_HTTP_TIMEOUT="12", VSI_CACHE="FALSE"):
            for index, key in enumerate(keys):
                with rasterio.open(local[key]) as source:
                    if is_sentinel:
                        _validate_header(source, item["assets"][key], key, item["projected_epsg"], source.crs)
                        nodata, offset = 0, -.1
                    else:
                        _validate_scale(item["assets"][key]["raster_bands"], key)
                        _validate_cog_radiometry(source, key)
                        if not source.crs or not source.crs.is_projected or source.count != 1 or not math.isclose(source.res[0], 30, abs_tol=.01) or not math.isclose(source.res[1], 30, abs_tol=.01):
                            raise ValueError("Unexpected HLS display grid.")
                        nodata, offset = -9999, 0.
                    grid = (source.crs, source.transform, source.width, source.height)
                    if first_grid is not None and first_grid != grid:
                        raise ValueError("The true-color bands use different grids.")
                    first_grid = grid
                    with WarpedVRT(source, crs="EPSG:3857", transform=transform, width=width, height=height,
                                   src_nodata=nodata, nodata=nodata, resampling=Resampling.nearest) as raster:
                        values = raster.read(1, masked=True)
                    valid &= ~np.ma.getmaskarray(values)
                    reflectance = values.filled(0).astype(np.float32) * .0001 + offset
                    rgba[:, :, index] = np.round(np.sqrt(np.clip(reflectance / .32, 0, 1)) * 255).astype(np.uint8)
    if transfer.get("budget_rejected") or transfer.get("protocol_errors"):
        raise RuntimeError("Image reads did not complete.")
    if not valid.any():
        return {"status": "no_pixels", "message": "This scene has no image pixels at the saved field."}
    rgba[~valid] = 0
    rgba[:, :, 3] = np.where(valid, 255, 0)
    image = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(image, format="PNG")
    png = image.getvalue()
    west, south, east, north = transform_bounds("EPSG:3857", "EPSG:4326", *bounds)
    return {**identity, "status": "available", "role": "display_only", "display_crs": "EPSG:3857",
            "display_resampling": "nearest", "bounds": [[south, west], [north, east]],
            "width": width, "height": height, "acquired_at": item["acquired_at"],
            "asset_ids": {key: item["assets"][key]["id"] for key in keys}, "png_base64": base64.b64encode(png).decode(),
            "image_sha256": hashlib.sha256(png).hexdigest(), "boundary": "True-color display of the selected acquisition."}


def scene_preview(geometry: dict, provider: str, scene: str, start: str, end: str,
                  cache: Path, budget: Path, *, online: bool, max_bytes: int, min_free_bytes: int) -> dict:
    geometry, identity = request_identity(geometry, provider, scene, start, end)
    directory = cache / "scene-previews"
    target = directory / (_digest(identity) + ".json")
    if directory.is_symlink() or cache.is_symlink():
        return {"status": "storage_unavailable", "message": "The preview cache could not be verified."}
    cached = _cached(target, identity)
    if cached:
        return cached
    if not online:
        return {"status": "cache_miss", "message": "This scene has no saved preview. Connect to load it."}
    try:
        with reserve_cache(budget, max_cache_bytes=max_bytes, min_free_bytes=min_free_bytes) as admission:
            cached = _cached(target, identity)
            if cached:
                return cached
            result = _render(geometry, identity)
            if result["status"] != "available":
                return result
            if not valid_preview(result, identity):
                raise ValueError("The preview did not validate.")
            payload = json.dumps({"image": result, "sha256": _digest(result)}, separators=(",", ":")).encode()
            admission.ensure(len(payload))
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp:
                name = Path(temp.name)
                try:
                    temp.write(payload)
                    temp.flush()
                    os.replace(name, target)
                finally:
                    name.unlink(missing_ok=True)
            return result
    except StorageRefusal as exc:
        return {"status": exc.status, "message": "The imagery cache is busy or has reached its storage limit."}
    except LookupError:
        return {"status": "scene_unavailable", "message": "The selected scene is no longer available for this field."}
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        return {"status": "preview_unavailable", "message": "The selected image could not be read. Retry or choose another scene."}
