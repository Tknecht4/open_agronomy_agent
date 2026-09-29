"""Bounded public metadata discovery; never a pixel acquisition or coverage claim.

One page is intentional. Provider pagination links and supplied asset URLs are
untrusted data, not instructions to make additional network requests.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any
from urllib.parse import urlsplit

import httpx

from .catalog import imagery_provider_catalog, source_definition
from .geometry import canonical_geometry, project_geometry

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _query_geometry(geometry: dict[str, Any], buffer_m: int) -> tuple[dict[str, Any], list[float]]:
    from shapely.geometry import shape, mapping

    if type(buffer_m) is not int or not 0 <= buffer_m <= 5000:
        raise ValueError("context_buffer_m must be an integer from 0 to 5000")
    geometry = canonical_geometry(geometry, max_vertices=500)
    original = shape(geometry)
    w, s, e, n = original.bounds
    if e - w > .3 or n - s > .3 or original.area > .03:
        raise ValueError("geometry exceeds bounded field discovery extent")
    query = original
    if buffer_m:
        point = original.representative_point()
        if abs(point.y) > 85:
            raise ValueError("buffered discovery is unsupported above 85 degrees latitude")
        crs = f"+proj=aeqd +lat_0={point.y} +lon_0={point.x} +datum=WGS84 +units=m"
        query = project_geometry(project_geometry(geometry, crs).buffer(buffer_m), "EPSG:4326", crs)
    query_json = canonical_geometry(mapping(query))
    return query_json, list(query.bounds)


def _request(source: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    # Endpoint is resolved only from the static catalog; no caller URL enters IO.
    endpoint = source["discovery_endpoint"]
    protocol = source["discovery_protocol"]
    method = "POST" if protocol == "stac" else "GET"
    kwargs = {"json": query} if protocol == "stac" else {"params": query}
    with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
        with client.stream(method, endpoint, **kwargs) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError("unexpected provider response")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("provider metadata exceeds byte budget")
    value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(value, dict) or value.get("error"):
        raise RuntimeError("provider returned an error or invalid document")
    return value


def _text(value: Any, maximum: int = 240) -> str | None:
    return value if isinstance(value, str) and len(value) <= maximum else None


def _asset_href(href: Any, source: dict[str, Any]) -> str | None:
    if not isinstance(href, str) or len(href) > 2048:
        return None
    try:
        parts = urlsplit(href)
        if parts.username or parts.password or parts.port or parts.query or parts.fragment:
            return None
        if source["id"] == "cop-dem-glo-30-earth-search" and parts.scheme == "s3" and parts.netloc == "copernicus-dem-30m":
            return "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com" + parts.path if parts.path.endswith(".tif") else None
        if parts.scheme != "https" or parts.hostname not in source.get("asset_hosts", []):
            return None
        # Catalog links are returned for review only, never followed here.
        return href if parts.path.endswith((".tif", ".tiff", ".zip")) else None
    except ValueError:
        return None


def _bounds(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        return None
    w, s, e, n = value
    return value if -180 <= w <= e <= 180 and -90 <= s <= n <= 90 else None


def _stac_item(item: Any, source: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("collection") != source["collection"]:
        return None
    item_id, properties, assets = _text(item.get("id")), item.get("properties"), item.get("assets")
    if not item_id or not isinstance(properties, dict) or not isinstance(assets, dict):
        return None
    key = source.get("preferred_asset")
    asset = assets.get(key, {})
    if not isinstance(asset, dict):
        asset = {}
    requester_pays = asset.get("storage:requester_pays", properties.get("storage:requester_pays", source.get("payment_required")))
    href = _asset_href(asset.get("href"), source) if requester_pays is not True else None
    return {
        "item_id": item_id, "collection": source["collection"], "bbox": _bounds(item.get("bbox")),
        "catalog_datetime": _text(properties.get("datetime")), "catalog_updated": _text(properties.get("updated")),
        "acquisition_interval": None,  # Mosaic/product publication dates are not acquisition dates.
        "asset_key": key, "asset_href": href,
        "asset_status": "metadata_link_only" if href else "not_qualified",
        "requester_pays": requester_pays if type(requester_pays) is bool else None,
        "declared_horizontal_epsg": properties.get("proj:epsg") if type(properties.get("proj:epsg")) is int else None,
        "declared_vertical_datum": source.get("vertical_datum"),
        "native_grid_verified": False, "pixel_coverage_verified": False,
        "source_metadata_sha256": hashlib.sha256(json.dumps(item, sort_keys=True, allow_nan=False).encode()).hexdigest(),
        "warnings": ["Read the actual raster header; STAC transforms/nominal resolution are not a verified grid.",
                     "A catalog footprint can contain voids. No pixel support or upstream catchment is established."],
    }


def _tnm_item(item: Any, source: dict[str, Any]) -> dict[str, Any] | None:
    # Conservative documented TNM fields; incomplete records never become qualified assets.
    if not isinstance(item, dict):
        return None
    item_id = _text(item.get("sourceId"))
    if not item_id:
        return None
    href = _asset_href(item.get("downloadURL"), source)
    return {"item_id": item_id, "title": _text(item.get("title")), "dataset": source["dataset"],
            "asset_key": "downloadURL", "asset_href": href,
            "asset_status": "metadata_link_only" if href else "not_qualified",
            "catalog_publication_date": _text(item.get("publicationDate")), "acquisition_interval": None,
            "native_grid_verified": False, "pixel_coverage_verified": False,
            "declared_vertical_datum": None,
            "source_metadata_sha256": hashlib.sha256(json.dumps(item, sort_keys=True, allow_nan=False).encode()).hexdigest(),
            "warnings": ["Inspect product metadata for acquisition, CRS, vertical datum and units before processing."]}


def discover_sources(geometry: dict[str, Any], source_id: str, *, network_mode: str = "offline",
                     limit: int = 5, context_buffer_m: int = 0,
                     start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """Return a finite catalog page, preserving failed/empty/incomplete distinctions."""
    source = source_definition(source_id)
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer from 1 to 10")
    search_geometry, bbox = _query_geometry(geometry, context_buffer_m)
    original = canonical_geometry(geometry, max_vertices=500)
    result = {"schema_version": "geospatial.discovery.v1", "source": source,
              "status": "blocked_offline", "records": [], "count": 0,
              "geometry_sha256": hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest(),
              "query": {"bbox": bbox, "context_buffer_m": context_buffer_m, "limit": limit,
                        "start_date": start_date, "end_date": end_date},
              "observed_at": datetime.now(timezone.utc).isoformat(), "pages_requested": 0,
              "coverage_status": "unverified", "pixel_bytes_read": 0,
              "limitations": "Metadata only. No absence-of-coverage conclusion, raster acquisition, model authority or runtime admission."}
    legacy = {p["id"] for p in imagery_provider_catalog()}
    if source_id in legacy:
        from agronomy_agent.field_imagery import search_field_imagery
        if source_id == "hls-earth-engine":
            result["status"] = "not_configured"
            return result
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required for imagery discovery")
        if context_buffer_m or original["type"] == "MultiPolygon":
            raise ValueError("legacy imagery discovery accepts an unbuffered point or polygon")
        old = search_field_imagery(original, source_id, start_date, end_date, limit, network_mode)
        result.update(status={"unavailable": "provider_unavailable"}.get(old["status"], old["status"]),
                      records=old["scenes"], count=old["count"], pages_requested=int(network_mode == "online"))
        return result
    if start_date is not None or end_date is not None:
        raise ValueError("date filtering is not qualified for these product catalogs; review item dates")
    if network_mode == "offline":
        return result
    if source["discovery_protocol"] == "stac":
        query = {"collections": [source["collection"]], "intersects": search_geometry, "limit": limit}
        field, normalize = "features", _stac_item
    else:
        query = {"datasets": source["dataset"], "bbox": ",".join(map(str, bbox)), "max": limit, "outputFormat": "JSON"}
        field, normalize = "items", _tnm_item
    result["pages_requested"] = 1
    try:
        response = _request(source, query)
        rows = response.get(field)
        if response.get("error") or not isinstance(rows, list) or len(rows) > limit:
            raise RuntimeError("invalid provider metadata page")
        records = [record for row in rows if (record := normalize(row, source)) is not None]
        result.update(status="available" if records else "no_records" if not rows else "provider_unavailable",
                      records=records, count=len(records), rejected_records=len(rows) - len(records),
                      page_limit_reached=len(rows) == limit,
                      response_sha256=hashlib.sha256(json.dumps(response, sort_keys=True, allow_nan=False).encode()).hexdigest())
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError, OverflowError):
        # Never echo upstream URLs, response bodies or exception strings into the API.
        result["status"] = "provider_unavailable"
    return result
