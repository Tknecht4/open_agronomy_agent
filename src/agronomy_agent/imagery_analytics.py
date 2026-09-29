"""Bounded HLS COG chips, spatial QA and observed spectral indices.

One request processes one public HLS scene. Raster dependencies are optional;
the serving environment need not install them to import this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import sqlite3
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qsl

import httpx

from agronomy_agent.field_imagery import (
    _PC_TOKEN, _PLANETARY_COMPUTER, _clean_asset, _request_json, _valid_search_geometry,
)
from agronomy_agent.imagery_store import ImageryStore
from agronomy_agent.geospatial.raster import fractional_weights, weighted_statistics
from agronomy_agent.imagery_sampling import (
    MAX_SAMPLE_RADIUS_M, MIN_SAMPLE_RADIUS_M, POINT_PROCESS_VERSION,
    outside_source_mask, point_grid_and_weights,
)

PROCESS_VERSION = "hls-chip-v3-native-grid-source-extent-float64-qa"
PREVIEW_VERSION = "ndvi-preview-v2-finite-alpha"
SCALE = 0.0001
MAX_SIDE = 256
MAX_BUFFER_M = 3000
MAX_COG_TRANSFER_BYTES = 256 * 1024 * 1024
MAX_SINGLE_RANGE_BYTES = 64 * 1024 * 1024
_PROXY_CHUNK_BYTES = 16 * 1024
BAND_NAMES = ("Blue", "Green", "Red", "NarrowNIR", "SWIR1", "SWIR2")
BAND_KEYS = {
    "hls-s30-planetary-computer": ("hls2-s30", ("B02", "B03", "B04", "B8A", "B11", "B12")),
    "hls-l30-planetary-computer": ("hls2-l30", ("B02", "B03", "B04", "B05", "B06", "B07")),
}
EXCLUDE_BITS = {"cirrus": 0, "cloud": 1, "adjacent_cloud_shadow": 2,
                "shadow": 3, "snow_ice": 4}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _dependencies() -> tuple[Any, Any, Any, Any, Any, Any]:
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.features import geometry_mask
        from rasterio.transform import from_origin
        from rasterio.vrt import WarpedVRT
        from pyproj import CRS, Transformer
        from shapely.geometry import box, shape
        from shapely.ops import transform as shapely_transform
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("optional imagery dependencies unavailable") from exc
    return np, rasterio, (Resampling, geometry_mask, from_origin, WarpedVRT), (CRS, Transformer), (box, shape, shapely_transform), Image


def _request_identity(geometry: dict[str, Any], provider_id: str, scene_id: str | None,
                      start_date: str | None, end_date: str | None, buffer_m: int,
                      context_pixels: int | None, *, sampling_mode: str | None = None,
                      sample_radius_m: int | None = None,
                      ) -> tuple[dict[str, Any], tuple[float, float, float, float], str, str]:
    if provider_id not in BAND_KEYS:
        raise ValueError("only anonymous HLS S30/L30 analytics is supported")
    canonical_geometry, bounds = _valid_search_geometry(geometry)
    is_point = canonical_geometry["type"] == "Point"
    mode = sampling_mode if sampling_mode is not None else ("point_pixel" if is_point else "field_polygon")
    if (is_point and mode not in ("point_pixel", "point_buffer")) or (not is_point and mode != "field_polygon"):
        raise ValueError("sampling_mode does not match saved geometry")
    if type(buffer_m) is not int or not 0 <= buffer_m <= MAX_BUFFER_M:
        raise ValueError("buffer_m must be an integer from 0 to 3000")
    if is_point:
        if buffer_m != 0 or context_pixels is not None:
            raise ValueError("point samples do not support polygon buffer or model context")
        if mode == "point_buffer":
            if (type(sample_radius_m) is not int or
                    not MIN_SAMPLE_RADIUS_M <= sample_radius_m <= MAX_SAMPLE_RADIUS_M):
                raise ValueError("sample_radius_m must be an integer from 15 to 1500 for point_buffer")
        elif sample_radius_m is not None:
            raise ValueError("sample_radius_m applies only to point_buffer")
    else:
        if sample_radius_m is not None:
            raise ValueError("sample_radius_m applies only to point_buffer")
        if context_pixels not in (None, 224) or (context_pixels is not None and buffer_m):
            raise ValueError("context_pixels supports 224 with buffer_m=0")
    if scene_id is None:
        if not start_date or not end_date:
            raise ValueError("scene_id or bounded date interval required")
        from agronomy_agent.field_imagery import _dates
        _dates(start_date, end_date)
    else:
        collection, _ = BAND_KEYS[provider_id]
        if not re.fullmatch(re.escape(collection) + r":[A-Za-z0-9._-]{1,160}", scene_id):
            raise ValueError("scene_id does not match HLS provider")
        if (start_date is None) != (end_date is None):
            raise ValueError("both dates are required when constraining a scene")
        if start_date is not None:
            from agronomy_agent.field_imagery import _dates
            _dates(start_date, end_date)
    geometry_hash = _hash(canonical_geometry)
    identity = {"version": POINT_PROCESS_VERSION if is_point else PROCESS_VERSION,
                "preview_version": PREVIEW_VERSION, "geometry_hash": geometry_hash,
                "provider": provider_id, "scene_id": scene_id,
                "start_date": start_date, "end_date": end_date,
                "buffer_m": buffer_m, "context_pixels": context_pixels}
    if is_point:
        identity.update({"sampling_mode": mode, "sample_radius_m": sample_radius_m})
    return canonical_geometry, tuple(bounds), geometry_hash, _hash(identity)


def _scene_item(geometry: dict[str, Any], provider_id: str, scene_id: str | None,
                start_date: str | None, end_date: str | None) -> dict[str, Any]:
    collection, band_keys = BAND_KEYS[provider_id]
    body: dict[str, Any] = {"collections": [collection], "limit": 1, "intersects": geometry}
    if scene_id:
        body["ids"] = [scene_id.split(":", 1)[1]]
    else:
        from agronomy_agent.field_imagery import _dates
        start, end = _dates(start_date, end_date)
        body["datetime"] = f"{start}/{end}"
        body["sortby"] = [{"field": "properties.datetime", "direction": "desc"}]
    response = _request_json(_PLANETARY_COMPUTER, body=body)
    features = response.get("features")
    if not isinstance(features, list) or len(features) > 1:
        raise RuntimeError("invalid STAC scene response")
    if not features:
        raise LookupError("no matching HLS scene")
    item = features[0]
    if not isinstance(item, dict) or item.get("collection") != collection:
        raise RuntimeError("unexpected STAC collection")
    item_id = item.get("id")
    if not isinstance(item_id, str) or len(item_id) > 160 or (scene_id and scene_id != f"{collection}:{item_id}"):
        raise RuntimeError("unexpected STAC item")
    properties = item.get("properties")
    assets = item.get("assets")
    if not isinstance(properties, dict) or not isinstance(assets, dict):
        raise RuntimeError("incomplete STAC item")
    acquired = properties.get("datetime")
    if not isinstance(acquired, str) or len(acquired) > 40:
        raise RuntimeError("missing acquisition time")
    if start_date is not None and end_date is not None:
        acquired_date = datetime.fromisoformat(acquired.replace("Z", "+00:00")).date().isoformat()
        if not start_date <= acquired_date <= end_date:
            raise RuntimeError("HLS acquisition outside requested date interval")
    wanted = (*band_keys, "Fmask")
    clean: dict[str, dict[str, Any]] = {}
    for key in wanted:
        asset = assets.get(key)
        href = _clean_asset(asset.get("href"), provider_id) if isinstance(asset, dict) else None
        if not href:
            raise RuntimeError("required HLS asset unavailable")
        bands_metadata = asset.get("raster:bands") if isinstance(asset.get("raster:bands"), list) else None
        clean[key] = {"href": href, "id": f"{collection}:{item_id}:{key}",
                      "raster_bands": bands_metadata,
                      "type": asset.get("type")}
    return {"id": f"{collection}:{item_id}", "collection": collection,
            "acquired_at": acquired, "availability_at": properties.get("created"),
            "scene_cloud_percent": properties.get("eo:cloud_cover"), "assets": clean}


def _signed_hrefs(item: dict[str, Any]) -> dict[str, str]:
    token = _request_json(_PC_TOKEN).get("token")
    if not isinstance(token, str) or not 1 <= len(token) <= 2048:
        raise RuntimeError("public HLS SAS unavailable")
    token = token.lstrip("?")
    pairs = parse_qsl(token, keep_blank_values=True)
    if not pairs or not all(k and v for k, v in pairs) or any(x in token for x in ("#", "\n", "\r")):
        raise RuntimeError("invalid public HLS SAS")
    return {key: f"{asset['href']}?{token}" for key, asset in item["assets"].items()}


@contextmanager
def _bounded_cog_proxy(hrefs: dict[str, str]):
    """Serve fixed public COG assets to GDAL through a capped loopback proxy.

    All outward requests use httpx without redirects. This also prevents SAS
    query strings from entering GDAL paths, errors, and receipts.
    """
    state = {"bytes": 0, "reserved": 0, "requests": 0, "rejected": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_HEAD(self) -> None:
            self._forward(head=True)

        def do_GET(self) -> None:
            self._forward(head=False)

        def _reject(self, status: int) -> None:
            with lock:
                state["rejected"] += 1
            self.send_error(status)

        def _forward(self, *, head: bool) -> None:
            key = self.path.removeprefix("/").removesuffix(".tif")
            if self.path != f"/{key}.tif" or key not in hrefs:
                self._reject(404)
                return
            requested = self.headers.get("Range")
            if not head:
                match = re.fullmatch(r"bytes=(\d+)-(\d+)", requested or "")
                if not match or int(match[2]) < int(match[1]) or int(match[2]) - int(match[1]) + 1 > MAX_SINGLE_RANGE_BYTES:
                    self._reject(416)
                    return
            try:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    with client.stream("HEAD" if head else "GET", hrefs[key],
                                       headers={"Accept-Encoding": "identity", **({"Range": requested} if requested else {})}) as upstream:
                        if upstream.status_code != (200 if head else 206):
                            self._reject(502)
                            return
                        if upstream.headers.get("Content-Encoding", "identity").lower() != "identity":
                            self._reject(502)
                            return
                        length_text = upstream.headers.get("Content-Length")
                        if not length_text or not length_text.isdigit():
                            self._reject(502)
                            return
                        length = int(length_text)
                        if not head:
                            content_range = upstream.headers.get("Content-Range", "")
                            returned = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                            if (not returned or int(returned[1]) != int(match[1]) or
                                    int(returned[2]) != int(match[2]) or
                                    int(returned[2]) - int(returned[1]) + 1 != length or
                                    length > MAX_SINGLE_RANGE_BYTES):
                                self._reject(502)
                                return
                        reserved = 0
                        if not head:
                            with lock:
                                # Reserve the advertised body plus one raw chunk.
                                # A malformed Content-Length can overdeliver at
                                # most that chunk before we stop forwarding.
                                allowance = length + _PROXY_CHUNK_BYTES
                                if state["bytes"] + state["reserved"] + allowance <= MAX_COG_TRANSFER_BYTES:
                                    state["reserved"] += allowance
                                    reserved = allowance
                            if not reserved:
                                self._reject(429)
                                return
                        try:
                            self.send_response(200 if head else 206)
                            self.send_header("Content-Length", str(length))
                            self.send_header("Content-Type", "image/tiff")
                            self.send_header("Accept-Ranges", "bytes")
                            if not head:
                                self.send_header("Content-Range", content_range)
                            self.end_headers()
                            if head:
                                return
                            with lock:
                                state["requests"] += 1
                            remaining_declared = length
                            for chunk in upstream.iter_raw(_PROXY_CHUNK_BYTES):
                                if not chunk:
                                    continue
                                with lock:
                                    state["bytes"] += len(chunk)
                                    if len(chunk) > reserved or len(chunk) > remaining_declared:
                                        # A provider violated Content-Length. Count the bytes
                                        # already fetched, stop forwarding, and fail the chip.
                                        state["reserved"] -= min(len(chunk), reserved)
                                        reserved -= min(len(chunk), reserved)
                                        overrun = True
                                    else:
                                        state["reserved"] -= len(chunk)
                                        reserved -= len(chunk)
                                        overrun = False
                                remaining_declared -= len(chunk)
                                if overrun:
                                    self.close_connection = True
                                    return
                                self.wfile.write(chunk)
                        finally:
                            if reserved:
                                with lock:
                                    state["reserved"] -= reserved
            except (httpx.HTTPError, OSError, BrokenPipeError):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        local = {key: f"http://127.0.0.1:{server.server_port}/{key}.tif" for key in hrefs}
        yield local, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _source_grid(hrefs: dict[str, str], deps: tuple[Any, ...]) -> tuple[Any, Any, int, int]:
    _, rasterio, _, _, _, _ = deps
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="0",
                      GDAL_HTTP_TIMEOUT="20", CPL_DEBUG="OFF", VSI_CACHE="FALSE"):
        with rasterio.open(hrefs["B02"]) as src:
            if src.crs is None or src.count != 1 or src.width < 1 or src.height < 1:
                raise RuntimeError("invalid HLS source grid")
            if not src.crs.is_projected:
                raise RuntimeError("HLS source grid must use projected metres")
            try:
                metre_factor = src.crs.linear_units_factor[1]
            except rasterio.errors.CRSError as exc:
                raise RuntimeError("HLS source grid has unknown linear units") from exc
            if not math.isclose(metre_factor, 1.0, rel_tol=0, abs_tol=1e-9):
                raise RuntimeError("HLS source grid must use metre units")
            affine = src.transform
            if (not math.isclose(affine.a, 30, abs_tol=1e-6) or
                    not math.isclose(affine.e, -30, abs_tol=1e-6) or
                    abs(affine.b) > 1e-9 or abs(affine.d) > 1e-9):
                raise RuntimeError("HLS source is not a north-up native 30 m grid")
            return src.crs, affine, src.width, src.height


def _grid(polygon: dict[str, Any], buffer_m: int, context_pixels: int | None,
          source_grid: tuple[Any, Any, int, int],
          deps: tuple[Any, ...]) -> tuple[Any, Any, int, int, Any, Any]:
    _, _, (_, _, from_origin, _), (_, Transformer), (_, shape, shapely_transform), _ = deps
    geom = shape(polygon)
    crs, source_transform, _, _ = source_grid
    projector = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    projected = shapely_transform(projector.transform, geom)
    buffered = projected.buffer(buffer_m) if buffer_m else projected
    if context_pixels is not None:
        size = context_pixels * 30
        left = source_transform.c + math.floor((projected.centroid.x - size / 2 - source_transform.c) / 30) * 30
        top = source_transform.f + math.ceil((projected.centroid.y + size / 2 - source_transform.f) / 30) * 30
        field_left, field_bottom, field_right, field_top = projected.bounds
        if field_left < left or field_right > left + size or field_bottom < top - size or field_top > top:
            raise ValueError("field exceeds centered 224 pixel context")
        return crs, from_origin(left, top, 30, 30), context_pixels, context_pixels, projected, buffered
    left, bottom, right, top = buffered.bounds
    left = source_transform.c + math.floor((left - source_transform.c) / 30) * 30
    bottom = source_transform.f + math.floor((bottom - source_transform.f) / 30) * 30
    right = source_transform.c + math.ceil((right - source_transform.c) / 30) * 30
    top = source_transform.f + math.ceil((top - source_transform.f) / 30) * 30
    width, height = int((right - left) / 30), int((top - bottom) / 30)
    if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE:
        raise ValueError("requested HLS chip exceeds 256 x 256 pixels")
    return crs, from_origin(left, top, 30, 30), width, height, projected, buffered


def _field_weights(projected: Any, transform: Any, width: int, height: int, deps: tuple[Any, ...]) -> Any:
    """Preserve float32 support for the frozen assessment collector consumer."""
    return fractional_weights(projected, transform, width, height).astype(deps[0].float32)


def _validate_scale(metadata: Any, key: str) -> None:
    if key == "Fmask" or not metadata:
        return
    if len(metadata) != 1 or not isinstance(metadata[0], dict):
        raise RuntimeError("unsupported HLS raster metadata")
    scale = metadata[0].get("scale")
    offset = metadata[0].get("offset")
    if scale is not None and not math.isclose(float(scale), SCALE, rel_tol=1e-6):
        raise RuntimeError("unexpected HLS reflectance scale")
    if offset is not None and not math.isclose(float(offset), 0, abs_tol=1e-9):
        raise RuntimeError("unexpected HLS reflectance offset")


def _read_assets(item: dict[str, Any], hrefs: dict[str, str], grid: tuple[Any, ...],
                 provider_id: str, source_grid: tuple[Any, Any, int, int],
                 deps: tuple[Any, ...]) -> tuple[Any, Any, dict[str, Any]]:
    np, rasterio, (Resampling, _, _, WarpedVRT), _, _, _ = deps
    crs, transform, width, height, _, _ = grid
    _, band_keys = BAND_KEYS[provider_id]
    arrays = []
    masks = []
    source_meta: dict[str, Any] = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="0",
                      GDAL_HTTP_TIMEOUT="20", CPL_DEBUG="OFF", VSI_CACHE="FALSE"):
        for key in (*band_keys, "Fmask"):
            _validate_scale(item["assets"][key]["raster_bands"], key)
            with rasterio.open(hrefs[key]) as src:
                if src.count != 1 or src.crs is None or src.width < 1 or src.height < 1:
                    raise RuntimeError("invalid HLS COG band")
                if (src.crs != source_grid[0] or src.transform != source_grid[1] or
                        src.width != source_grid[2] or src.height != source_grid[3]):
                    raise RuntimeError("HLS band grids are inconsistent")
                source_meta[key] = {"asset_id": item["assets"][key]["id"],
                                    "crs": src.crs.to_string(), "dtype": src.dtypes[0],
                                    "nodata": src.nodata, "scale": None if key == "Fmask" else SCALE,
                                    "offset": None if key == "Fmask" else 0,
                                    "raster_bands": item["assets"][key]["raster_bands"]}
                with WarpedVRT(src, crs=crs, transform=transform, width=width, height=height,
                               resampling=Resampling.nearest) as vrt:
                    data = vrt.read(1, masked=True)
                    arrays.append(np.asarray(data.data))
                    masks.append(np.ma.getmaskarray(data).copy())
    raw = np.stack(arrays[:6]).astype(np.float32)
    invalid = np.any(np.stack(masks[:6]), axis=0)
    invalid |= np.any(~np.isfinite(raw), axis=0)
    # HLS fill is -9999; metadata can be absent or inconsistent in old granules.
    invalid |= np.any(raw == -9999, axis=0)
    fmask = np.asarray(arrays[6]).astype(np.uint8)
    invalid |= masks[6] | (fmask == 255)
    # Absent nodata metadata must never turn off-tile VRT zeros into observations.
    invalid |= outside_source_mask(grid, source_grid)
    return raw, fmask, {"source_meta": source_meta, "nodata_invalid": invalid}


def _qa_indices(raw: Any, fmask: Any, invalid: Any, weights: Any, deps: tuple[Any, ...]) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any]]:
    np = deps[0]
    reasons = {name: (fmask & (1 << bit)) != 0 for name, bit in EXCLUDE_BITS.items()}
    reasons["high_aerosol"] = (fmask & 0xC0) == 0xC0
    valid = ~invalid
    for mask in reasons.values():
        valid &= ~mask
    bands = raw * SCALE
    bands[:, ~valid] = np.nan
    def index(a: Any, b: Any) -> Any:
        denominator = a + b
        result = np.full(a.shape, np.nan, dtype=np.float32)
        np.divide(a - b, denominator, out=result, where=valid & (np.abs(denominator) > 1e-6))
        return result
    ndvi = index(bands[3], bands[2])
    ndmi = index(bands[3], bands[4])
    # Use the same positive support sequence for every reduction, so an
    # excluded zero-weight bounding-box corner cannot change the denominator.
    weights = np.asarray(weights, dtype=np.float64)
    support = weights > 0
    total = float(weights[support].sum(dtype=np.float64))
    clear = float(weights[valid & support].sum(dtype=np.float64))
    def stat(values: Any) -> dict[str, Any]:
        return weighted_statistics(values, weights, valid=valid, cell_area=900)
    qa = {"field_area_m2": total * 900, "valid_area_m2": clear * 900,
          "valid_area_fraction": clear / total if total > 0 else None,
          "excluded_area_m2_by_reason": {
              name: float(weights[mask & support].sum(dtype=np.float64)) * 900
              for name, mask in reasons.items()},
          "nodata_area_m2": float(weights[invalid & support].sum(dtype=np.float64)) * 900,
          "overlap_note": "QA reason areas may overlap; do not sum them"}
    return bands, valid, ndvi, qa, {"NDVI": stat(ndvi), "NDMI": stat(ndmi)}


def _png(ndvi: Any, valid: Any, weights: Any, Image: Any) -> bytes:
    import numpy as np
    tone = np.clip((np.nan_to_num(ndvi, nan=-1) + 1) / 2, 0, 1)
    rgba = np.zeros((*ndvi.shape, 4), dtype=np.uint8)
    rgba[..., 0] = (185 * (1 - tone)).astype(np.uint8)
    rgba[..., 1] = (60 + 170 * tone).astype(np.uint8)
    rgba[..., 2] = (95 * (1 - tone)).astype(np.uint8)
    rgba[..., 3] = np.where(valid & np.isfinite(ndvi) & (weights > 0), 255, 0).astype(np.uint8)
    output = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(output, format="PNG")
    return output.getvalue()


def analyze_scene(
    geometry: dict[str, Any], provider_id: str, scene_id: str | None = None, *,
    cache_root: str | Path, network_mode: str = "offline",
    start_date: str | None = None, end_date: str | None = None,
    buffer_m: int = 0, context_pixels: int | None = None,
    sampling_mode: str | None = None, sample_radius_m: int | None = None,
    budget_root: str | Path | None = None,
    max_cache_bytes: int = 2 * 1024**3, min_free_bytes: int = 1024**3,
) -> dict[str, Any]:
    """Reuse verified chips or admit one bounded writer before public egress."""
    from agronomy_agent.imagery_budget import reserve_cache, StorageRefusal, validate_policy
    validate_policy(max_cache_bytes, min_free_bytes)
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    _, _, _, request_hash = _request_identity(
        geometry, provider_id, scene_id, start_date, end_date, buffer_m, context_pixels,
        sampling_mode=sampling_mode, sample_radius_m=sample_radius_m)
    supplied = Path(cache_root).expanduser()
    if supplied.is_symlink():
        raise ValueError("imagery cache root cannot be a symlink")
    root = supplied.resolve()
    repository = Path(__file__).resolve().parents[2]
    if root.is_relative_to(repository):
        raise ValueError("imagery cache must be outside the repository")
    budget = Path(budget_root).expanduser() if budget_root is not None else supplied
    if budget.is_symlink() or budget.resolve().is_relative_to(repository) or not root.is_relative_to(budget.resolve()):
        raise ValueError("imagery budget root must contain the cache outside the repository")
    try:
        if (root / "imagery-v1.sqlite3").exists():
            cached = ImageryStore(root, read_only=True).get(request_hash, scene_id=scene_id)
            if cached:
                return {**cached, "cache_hit": True}
        if network_mode == "offline":
            return {"status": "blocked_offline", "provider_id": provider_id,
                    "scene_id": scene_id, "request_hash": request_hash,
                    "reason": "no matching local chip"}
        with reserve_cache(budget, max_cache_bytes=max_cache_bytes, min_free_bytes=min_free_bytes) as admission:
            return _analyze_scene_admitted(
                geometry, provider_id, scene_id, cache_root=root, network_mode=network_mode,
                start_date=start_date, end_date=end_date, buffer_m=buffer_m,
                context_pixels=context_pixels, sampling_mode=sampling_mode,
                sample_radius_m=sample_radius_m, admission=admission)
    except StorageRefusal as exc:
        return {"status": exc.status, "reason": exc.reason, "request_hash": request_hash}
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        return {"status": "storage_unavailable", "reason": "imagery_cache_unavailable",
                "error_type": type(exc).__name__, "request_hash": request_hash}


def _analyze_scene_admitted(
    geometry: dict[str, Any], provider_id: str, scene_id: str | None = None, *,
    cache_root: str | Path, network_mode: str = "offline",
    start_date: str | None = None, end_date: str | None = None,
    buffer_m: int = 0, context_pixels: int | None = None,
    sampling_mode: str | None = None, sample_radius_m: int | None = None,
    admission: Any,
) -> dict[str, Any]:
    """Return a source-bound single-scene receipt; offline reuses exact cached work.

    The cache root must be outside the repository. Signed URLs stay in memory.
    The loopback proxy measures outward COG payload bytes and caps one chip at
    256 MiB; HTTP headers and STAC/token JSON are outside that byte count.
    """
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    canonical_geometry, bounds, geometry_hash, request_hash = _request_identity(
        geometry, provider_id, scene_id, start_date, end_date, buffer_m, context_pixels,
        sampling_mode=sampling_mode, sample_radius_m=sample_radius_m)
    is_point = canonical_geometry["type"] == "Point"
    mode = sampling_mode if sampling_mode is not None else ("point_pixel" if is_point else "field_polygon")
    process_version = POINT_PROCESS_VERSION if is_point else PROCESS_VERSION
    point_request = ({"provider_id": provider_id, "scene_id": scene_id,
                      "start_date": start_date, "end_date": end_date,
                      "buffer_m": 0, "context_pixels": None,
                      "sampling_mode": mode, "sample_radius_m": sample_radius_m}
                     if is_point else None)
    root = Path(cache_root).expanduser().resolve()
    repository = Path(__file__).resolve().parents[2]
    if root == repository or repository in root.parents:
        raise ValueError("imagery cache must be outside the repository")
    store = ImageryStore(root)
    cached = store.get(request_hash, scene_id=scene_id)
    if cached:
        return {**cached, "cache_hit": True}
    if network_mode == "offline":
        return {"status": "blocked_offline", "provider_id": provider_id,
                "scene_id": scene_id, "request_hash": request_hash,
                "reason": "no matching local chip"}
    started = time.monotonic()
    try:
        deps = _dependencies()
        item = _scene_item(canonical_geometry, provider_id, scene_id, start_date, end_date)
        hrefs = _signed_hrefs(item)
        with _bounded_cog_proxy(hrefs) as (local_hrefs, transfer):
            source_grid = _source_grid(local_hrefs, deps)
            if is_point:
                grid, weights, sampling, bounds = point_grid_and_weights(
                    canonical_geometry, mode, sample_radius_m, source_grid, deps)
            else:
                grid = _grid(canonical_geometry, buffer_m, context_pixels, source_grid, deps)
                crs, transform, width, height, projected, _ = grid
                weights = fractional_weights(projected, transform, width, height)
                sampling = None
            crs, transform, width, height, _, _ = grid
            if float(weights.sum()) <= 0:
                return {"status": "empty_valid_area" if is_point else "empty_field_mask",
                        "provider_id": provider_id,
                        "scene_id": item["id"], "request_hash": request_hash}
            raw, fmask, source = _read_assets(item, local_hrefs, grid, provider_id, source_grid, deps)
        np = deps[0]
        bands, valid, ndvi, qa, zonal = _qa_indices(
            raw, fmask, source["nodata_invalid"], weights, deps)
        np, _, _, _, _, Image = deps
        if is_point:
            sampling["valid_pixel_count"] = int(np.count_nonzero(valid & (weights > 0)))
            qa["sample_area_m2"] = qa.pop("field_area_m2")
        process_spec = {"version": process_version, "band_keys": BAND_KEYS[provider_id][1],
                        "scale": SCALE, "excluded_bits": EXCLUDE_BITS, "aerosol_high": 3,
                        "resampling_method": "nearest", "preview_version": PREVIEW_VERSION}
        if is_point:
            process_spec["sampling_schema_version"] = "imagery_sampling.v1"
            process_spec["qa_accumulator_dtype"] = "float64"
        process_hash = _hash(process_spec)
        native_grid = {"crs": source_grid[0].to_string(),
                       "transform": list(source_grid[1])[:6],
                       "width": source_grid[2], "height": source_grid[3],
                       "resolution_m": 30}
        chip_grid = {"crs": crs.to_string(), "transform": list(transform)[:6],
                     "width": width, "height": height, "resolution_m": 30,
                     "resampling_method": "nearest", "native_asset_grid": native_grid}
        array_hash = hashlib.sha256(bands.tobytes() + fmask.tobytes() + weights.tobytes()).hexdigest()
        chip_binding = {"request": request_hash, "scene": item["id"], "asset_ids":
                        [v["id"] for v in item["assets"].values()], "process": process_hash,
                        "arrays": array_hash, "grid": chip_grid}
        if is_point:
            chip_binding["sampling"] = sampling
        chip_hash = _hash(chip_binding)
        names = {"npz": f"{chip_hash}.npz", "png": f"{chip_hash}.png",
                 "receipt": f"{chip_hash}.json"}
        metadata = {"process_version": process_version, "preview_version": PREVIEW_VERSION,
                    "source_native_grid": True,
                    "resampling_method": "nearest", "native_asset_grid": native_grid,
                    "band_names": list(BAND_NAMES), "band_keys": list(BAND_KEYS[provider_id][1]),
                    "crs": crs.to_string(), "transform": list(transform)[:6],
                    "width": width, "height": height, "resolution_m": 30,
                    "source": {"provider_id": provider_id, "collection": item["collection"],
                               "scene_id": item["id"], "acquired_at": item["acquired_at"],
                               "availability_at": item["availability_at"],
                               "scene_cloud_percent": item["scene_cloud_percent"],
                               "asset_ids": {key: value["id"] for key, value in item["assets"].items()},
                               "band_metadata": source["source_meta"]}}
        if is_point:
            metadata["sampling"] = sampling
            metadata["request"] = point_request
            metadata["qa_accumulator_dtype"] = "float64"
        receipt = {"status": "available" if qa["valid_area_m2"] > 0 else "empty_valid_area",
                   "evidence_role": "observation", "interpretation": "spectral indices only; no stress diagnosis",
                   "provider_id": provider_id, "scene_id": item["id"],
                   "request_hash": request_hash, "geometry_hash": geometry_hash,
                   "process_version": process_version, "preview_version": PREVIEW_VERSION,
                   "source_native_grid": True,
                   "process_hash": process_hash, "chip_hash": chip_hash,
                   "source": metadata["source"], "grid": chip_grid,
                   "qa": qa, "zonal_stats": zonal, "cache_files": names,
                   "model_refs": [], "created_at": datetime.now(timezone.utc).isoformat(),
                   "elapsed_seconds": time.monotonic() - started,
                   "cog_transfer_bytes": transfer["bytes"],
                   "cog_range_requests": transfer["requests"],
                   "cog_transfer_limit_bytes": MAX_COG_TRANSFER_BYTES,
                   "cache_hit": False}
        if is_point:
            receipt["sampling"] = sampling
            receipt["request"] = point_request
        temp_names = {ext: root / f".{chip_hash}.{os.getpid()}.{threading.get_ident()}{ext}"
                      for ext in (".npz", ".png", ".json")}
        try:
            packed = io.BytesIO()
            if is_point:
                np.savez_compressed(packed, bands=bands, valid_mask=valid,
                                    sample_mask=weights > 0, sample_weights=weights,
                                    fmask=fmask, ndvi=ndvi,
                                    metadata_json=_canonical(metadata).decode())
            else:
                np.savez_compressed(packed, bands=bands, valid_mask=valid, field_mask=weights > 0,
                                    field_weights=weights, fmask=fmask, ndvi=ndvi,
                                    metadata_json=_canonical(metadata).decode())
            payloads = {".npz": packed.getvalue(), ".png": _png(ndvi, valid, weights, Image),
                        ".json": _canonical(receipt)}
            # Reserve enough for temporary files and index/journal overhead.
            admission.ensure(sum(len(value) for value in payloads.values()) + 1024**2)
            for ext, payload in payloads.items():
                temp_names[ext].write_bytes(payload)
            for ext, name in ((".npz", names["npz"]), (".png", names["png"]), (".json", names["receipt"])):
                os.replace(temp_names[ext], root / name)
        finally:
            for path in temp_names.values():
                path.unlink(missing_ok=True)
        store.put(receipt, bounds)
        return receipt
    except LookupError:
        return {"status": "no_scene", "provider_id": provider_id, "scene_id": scene_id,
                "request_hash": request_hash}
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        from agronomy_agent.imagery_budget import StorageRefusal
        if isinstance(exc, StorageRefusal):
            raise
        # Never render GDAL/httpx exception strings: they can contain a SAS URL.
        return {"status": "unavailable", "provider_id": provider_id, "scene_id": scene_id,
                "request_hash": request_hash, "error_type": type(exc).__name__,
                "elapsed_seconds": time.monotonic() - started}
