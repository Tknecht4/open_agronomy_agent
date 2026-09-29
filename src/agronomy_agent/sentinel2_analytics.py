"""Bounded, keyless Sentinel-2 C1 L2A polygon products.

This operator adapter shares transport, storage and spatial reductions with HLS.
Its source-specific radiometry and QA remain independent of HLS corrections.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from typing import Any

import httpx

from agronomy_agent.field_imagery import _EARTH_SEARCH, _request_json, _valid_geometry, _dates
from agronomy_agent.geospatial.catalog import source_definition
from agronomy_agent.geospatial.cog import bounded_cog_proxy, MAX_COG_TRANSFER_BYTES
from agronomy_agent.geospatial.products import cached_product, write_chip_bundle
from agronomy_agent.geospatial.raster import ndvi_preview
from agronomy_agent.geospatial.sentinel2 import (
    PROVIDER_ID, COLLECTION, PROCESS_VERSION, Sentinel2Refusal, validate_item, prepare_scene,
)
from agronomy_agent.imagery_store import ImageryStore

PREVIEW_VERSION = "ndvi-preview-v2-finite-alpha"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _request(geometry: dict[str, Any], scene_id: str | None, start_date: str | None,
             end_date: str | None, cloud_buffer_m: int, edge_buffer_m: int) -> dict[str, Any]:
    geometry, bounds = _valid_geometry(geometry)
    for name, value in (("cloud_buffer_m", cloud_buffer_m), ("edge_buffer_m", edge_buffer_m)):
        if type(value) is not int or not 0 <= value <= 200:
            raise ValueError(f"{name} must be an integer from 0 to 200")
    if cloud_buffer_m % 20:
        raise ValueError("cloud_buffer_m must be a multiple of the 20 m QA grid")
    if scene_id is not None:
        if not isinstance(scene_id, str) or not re.fullmatch(re.escape(COLLECTION) + r":[A-Za-z0-9._-]{1,160}", scene_id):
            raise ValueError("scene_id must identify the Sentinel-2 C1 provider")
    if (start_date is None) != (end_date is None) or (scene_id is None and start_date is None):
        raise ValueError("provide an exact scene or both dates")
    if start_date is not None:
        _dates(start_date, end_date)
    geometry_hash = _hash(geometry)
    identity = {"version": PROCESS_VERSION, "provider": PROVIDER_ID,
                "preview_version": PREVIEW_VERSION, "geometry_hash": geometry_hash,
                "scene_id": scene_id, "start_date": start_date, "end_date": end_date,
                "cloud_buffer_m": cloud_buffer_m, "edge_buffer_m": edge_buffer_m,
                "sampling_mode": "field_polygon", "analysis_resolution_m": 20}
    return {"geometry": geometry, "bounds": tuple(bounds), "geometry_hash": geometry_hash,
            "request_hash": _hash(identity), "identity": identity}


def _scene(request: dict[str, Any]) -> dict[str, Any]:
    identity = request["identity"]
    body: dict[str, Any] = {"collections": [COLLECTION], "intersects": request["geometry"], "limit": 1}
    if identity["scene_id"]:
        body["ids"] = [identity["scene_id"].split(":", 1)[1]]
    else:
        body["sortby"] = [{"field": "properties.datetime", "direction": "desc"}]
    if identity["start_date"]:
        start, end = _dates(identity["start_date"], identity["end_date"])
        body["datetime"] = f"{start}/{end}"
    raw = _request_json(_EARTH_SEARCH, body=body)
    features = raw.get("features")
    if not isinstance(features, list) or len(features) > 1:
        raise RuntimeError("invalid Sentinel-2 scene response")
    if not features:
        raise LookupError("no matching Sentinel-2 scene")
    item = validate_item(features[0])
    if identity["scene_id"] and item["id"] != identity["scene_id"]:
        raise RuntimeError("provider returned a different Sentinel-2 scene")
    acquired = datetime.fromisoformat(item["acquired_at"].replace("Z", "+00:00"))
    if acquired.tzinfo is None:
        raise RuntimeError("source acquisition must have a timezone")
    day = acquired.astimezone(timezone.utc).date().isoformat()
    if identity["start_date"] and not identity["start_date"] <= day <= identity["end_date"]:
        raise RuntimeError("source acquisition outside requested dates")
    return item


def _array_identity(arrays: dict[str, Any]) -> dict[str, Any]:
    """Bind each grid's array name, dtype, shape and bytes; no object arrays."""
    import numpy as np
    result = {}
    for name, array in sorted(arrays.items()):
        a = np.asarray(array)
        if a.dtype.hasobject:
            raise ValueError("object arrays are not permitted in chips")
        result[name] = {"dtype": a.dtype.str, "shape": list(a.shape),
                        "sha256": hashlib.sha256(a.tobytes(order="C")).hexdigest()}
    return result


def _process(request: dict[str, Any], root: Path, admission: Any) -> dict[str, Any]:
    started = time.monotonic()
    identity = request["identity"]
    try:
        import numpy as np
        from PIL import Image
        store = ImageryStore(root)
        # Recheck after acquiring the shared writer lock.
        cached = store.get(request["request_hash"], scene_id=identity["scene_id"])
        if cached:
            return {**cached, "cache_hit": True}
        item = _scene(request)
        hrefs = {key: asset["href"] for key, asset in item["assets"].items()}
        with bounded_cog_proxy(hrefs) as (local_hrefs, transfer):
            prepared = prepare_scene(item, local_hrefs, request["geometry"],
                                     cloud_buffer_m=identity["cloud_buffer_m"],
                                     edge_buffer_m=identity["edge_buffer_m"])
        arrays = prepared["arrays"]
        array_manifest = _array_identity(arrays)
        source = {"provider_id": PROVIDER_ID, "collection": COLLECTION,
                  "scene_id": item["id"], "acquired_at": item["acquired_at"],
                  "availability_at": item.get("availability_at"),
                  "scene_cloud_percent": item.get("scene_cloud_percent"),
                  "processing_baseline": item["baseline"], "sun_zenith_deg": item["sun_zenith_deg"],
                  "product_uri": item["product_uri"],
                  "processing_generation": item["processing_generation"],
                  "asset_ids": {k: v["id"] for k, v in item["assets"].items()},
                  "asset_hrefs": {k: v["href"] for k, v in item["assets"].items()},
                  "item_metadata_sha256": _hash(item),
                  "stac_item_sha256": item.get("source_metadata_sha256"),
                  "rights": source_definition(PROVIDER_ID)["rights"],
                  "rights_url": source_definition(PROVIDER_ID)["rights_url"],
                  "band_metadata": prepared["source_band_metadata"]}
        process_spec = {**prepared["process_spec"], "preview_version": PREVIEW_VERSION}
        process_hash = _hash(process_spec)
        chip_hash = _hash({"request": request["request_hash"], "source": source,
                           "process": process_hash, "grid": prepared["grid"], "arrays": array_manifest})
        names = {"npz": chip_hash + ".npz", "png": chip_hash + ".png", "receipt": chip_hash + ".json"}
        metadata = {"process_version": PROCESS_VERSION, "process_spec": process_spec,
                    "source": source, "admitted_source_item": item,
                    "grid": prepared["grid"], "array_manifest": array_manifest,
                    "native_windows": "per-band raw DN and validity use the source window grids in band_metadata",
                    "qa": prepared["qa"], "request": identity, "processing_metadata": prepared.get("metadata", {})}
        receipt = {"status": "available" if prepared["qa"]["valid_area_m2"] > 0 else "empty_valid_area",
                   "evidence_role": "processed_observation", "interpretation": "source-specific spectral indices; no stress diagnosis",
                   "provider_id": PROVIDER_ID, "scene_id": item["id"],
                   "request_hash": request["request_hash"], "geometry_hash": request["geometry_hash"],
                   "process_version": PROCESS_VERSION, "preview_version": PREVIEW_VERSION,
                   "process_hash": process_hash, "process_spec": process_spec, "chip_hash": chip_hash,
                   "source": source, "source_native_grid": False, "grid": prepared["grid"],
                   "qa": prepared["qa"], "zonal_stats": prepared["zonal_stats"],
                   "interior_zonal_stats": prepared["interior_zonal_stats"],
                   "array_manifest": array_manifest, "cache_files": names, "request": identity,
                   "limitations": prepared["limitations"], "model_refs": [],
                   "scientific_qualification": "source_screened_not_field_validated",
                   "field_action_authority": "not_authorized",
                   "created_at": datetime.now(timezone.utc).isoformat(), "cache_hit": False,
                   "elapsed_seconds": time.monotonic() - started,
                   "cog_transfer_bytes": transfer["bytes"], "cog_range_requests": transfer["requests"],
                   "cog_transfer_limit_bytes": MAX_COG_TRANSFER_BYTES}
        packed = io.BytesIO()
        np.savez_compressed(packed, **arrays, metadata_json=_canonical(metadata).decode())
        write_chip_bundle(store, receipt, request["bounds"], npz=packed.getvalue(),
                          png=ndvi_preview(arrays["ndvi"], arrays["valid_mask"], arrays["field_weights"], Image),
                          admission=admission)
        return receipt
    except LookupError:
        return {"status": "no_scene", "provider_id": PROVIDER_ID, "scene_id": identity["scene_id"],
                "request_hash": request["request_hash"]}
    except (ImportError, OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        from agronomy_agent.imagery_budget import StorageRefusal
        if isinstance(exc, StorageRefusal):
            raise
        # Error strings can contain provider URLs; expose only the type.
        return {"status": "unavailable", "provider_id": PROVIDER_ID, "scene_id": identity["scene_id"],
                "request_hash": request["request_hash"], "error_type": type(exc).__name__,
                "reason": exc.reason if isinstance(exc, Sentinel2Refusal) else
                          "optional_dependencies_unavailable" if isinstance(exc, ImportError) else "processing_unavailable",
                "elapsed_seconds": time.monotonic() - started}


def analyze_sentinel2_scene(geometry: dict[str, Any], scene_id: str | None = None, *,
                            cache_root: str | Path, network_mode: str = "offline",
                            start_date: str | None = None, end_date: str | None = None,
                            cloud_buffer_m: int = 60, edge_buffer_m: int = 20,
                            budget_root: str | Path | None = None,
                            max_cache_bytes: int = 2 * 1024**3,
                            min_free_bytes: int = 1024**3) -> dict[str, Any]:
    request = _request(geometry, scene_id, start_date, end_date, cloud_buffer_m, edge_buffer_m)
    return cached_product(request_hash=request["request_hash"], provider_id=PROVIDER_ID, scene_id=scene_id,
                          cache_root=cache_root, network_mode=network_mode, budget_root=budget_root,
                          max_cache_bytes=max_cache_bytes, min_free_bytes=min_free_bytes,
                          process=lambda root, admission: _process(request, root, admission))
