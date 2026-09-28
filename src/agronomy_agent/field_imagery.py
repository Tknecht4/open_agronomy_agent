"""Bounded, anonymous STAC discovery for a saved point or field polygon.

This module returns *metadata*, not field pixels or a vegetation diagnosis.
Planetary Computer asset signing is confined to a single bounded range probe;
signed URLs and tokens are never returned or logged.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Any
from urllib.parse import urlsplit

import httpx
from shapely.geometry import shape


_EARTH_SEARCH = "https://earth-search.aws.element84.com/v1/search"
_PLANETARY_COMPUTER = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
_PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/hls2euwest/hls2"
_EARTH_ASSET_HOST = "e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"
_PC_ASSET_HOST = "hls2euwest.blob.core.windows.net"
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_RANGE_BYTES = 16 * 1024

_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "sentinel2-c1-earth-search",
        "name": "Sentinel-2 Collection 1 L2A COGs (Earth Search)",
        "source": "ESA/Copernicus Sentinel-2; Element 84 Earth Search COG hosting",
        "collection": "sentinel-2-c1-l2a",
        "catalog_url": "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a",
        "access": "anonymous_metadata_and_cog",
        "account_required": False,
        "payment_required": False,
        "rights": "Copernicus Sentinel Data Terms and Conditions; attribution required. STAC collection declares license=proprietary; inspect source terms before redistribution.",
        "rights_url": "https://sentinels.copernicus.eu/web/sentinel/data-access-and-products/legal-notices",
        "capabilities": ["scene_discovery", "anonymous_cog_range_read"],
        "limitations": "Scene cloud cover is scene-wide, not clear field coverage; C1 historical gaps exist. No pixel analysis in this module.",
    },
    {
        "id": "hls-s30-planetary-computer",
        "name": "NASA HLS S30 v2 (Planetary Computer mirror)",
        "source": "NASA LP DAAC HLS S30; Microsoft Planetary Computer mirror",
        "collection": "hls2-s30",
        "catalog_url": "https://planetarycomputer.microsoft.com/api/stac/v1/collections/hls2-s30",
        "access": "anonymous_metadata_public_short_lived_sas_for_cog",
        "account_required": False,
        "payment_required": False,
        "rights": "HLS source data CC BY 4.0 per NASA AWS Registry; Planetary Computer STAC collection declares license=proprietary and links LP DAAC policies. Preserve attribution and verify redistribution terms.",
        "rights_url": "https://lpdaac.usgs.gov/data/data-citation-and-policies/",
        "capabilities": ["scene_discovery", "public_sas_cog_range_read"],
        "limitations": "Public SAS expires; scene metadata is not field coverage or validated reflectance.",
    },
    {
        "id": "hls-l30-planetary-computer",
        "name": "NASA HLS L30 v2 (Planetary Computer mirror)",
        "source": "NASA LP DAAC HLS L30; Microsoft Planetary Computer mirror",
        "collection": "hls2-l30",
        "catalog_url": "https://planetarycomputer.microsoft.com/api/stac/v1/collections/hls2-l30",
        "access": "anonymous_metadata_public_short_lived_sas_for_cog",
        "account_required": False,
        "payment_required": False,
        "rights": "HLS source data CC BY 4.0 per NASA AWS Registry; Planetary Computer STAC collection declares license=proprietary and links LP DAAC policies. Preserve attribution and verify redistribution terms.",
        "rights_url": "https://lpdaac.usgs.gov/data/data-citation-and-policies/",
        "capabilities": ["scene_discovery", "public_sas_cog_range_read"],
        "limitations": "Public SAS expires; scene metadata is not field coverage or validated reflectance.",
    },
    {
        "id": "hls-earth-engine",
        "name": "NASA HLS v2 (Google Earth Engine)",
        "source": "NASA HLS via Google Earth Engine",
        "collection": None,
        "catalog_url": "https://developers.google.com/earth-engine/datasets/tags/hls",
        "access": "account_and_project_required_not_configured",
        "account_required": True,
        "project_required": True,
        "payment_required": "depends_on_Earth_Engine_eligibility_and_quota",
        "rights": "NASA HLS source terms and Google Earth Engine platform terms apply separately.",
        "rights_url": "https://developers.google.com/earth-engine/guides/access",
        "capabilities": [],
        "limitations": "Optional provider declaration only; no Earth Engine credentials are read or configured.",
    },
)


def provider_catalog() -> list[dict[str, Any]]:
    """Return a detached, credential-free provider inventory."""
    import copy

    return copy.deepcopy(list(_PROVIDERS))


def _provider(provider_id: str) -> dict[str, Any]:
    for provider in _PROVIDERS:
        if provider["id"] == provider_id:
            return provider
    raise ValueError("unknown imagery provider")


def _valid_geometry(geometry: dict[str, Any]) -> tuple[dict[str, Any], list[float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("WGS84 GeoJSON Polygon required")
    crs = geometry.get("crs")
    if crs not in (None, "EPSG:4326", {"type": "name", "properties": {"name": "EPSG:4326"}}):
        raise ValueError("only WGS84 EPSG:4326 polygons are supported")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates or sum(len(ring) for ring in coordinates if isinstance(ring, list)) > 500:
        raise ValueError("polygon must have 1-500 vertices")
    for ring in coordinates:
        if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError("polygon rings must be closed")
        for point in ring:
            if (not isinstance(point, (list, tuple)) or len(point) != 2 or
                    any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                        not math.isfinite(value) for value in point)):
                raise ValueError("finite two-dimensional coordinates required")
    try:
        polygon = shape({"type": "Polygon", "coordinates": coordinates})
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("invalid field polygon") from exc
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("invalid or empty field polygon")
    west, south, east, north = polygon.bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("polygon coordinates must be WGS84 longitude/latitude")
    if east - west > 0.3 or north - south > 0.3:
        raise ValueError("field extent exceeds 0.3 degrees")
    if polygon.area > 0.03:
        raise ValueError("field area exceeds search limit")
    return {"type": "Polygon", "coordinates": coordinates}, [west, south, east, north]


def _valid_search_geometry(geometry: dict[str, Any]) -> tuple[dict[str, Any], list[float]]:
    """Validate a location without expanding a point into a field boundary."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return _valid_geometry(geometry)
    crs = geometry.get("crs")
    if crs not in (None, "EPSG:4326", {"type": "name", "properties": {"name": "EPSG:4326"}}):
        raise ValueError("only WGS84 EPSG:4326 points are supported")
    coordinates = geometry.get("coordinates")
    if (not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in coordinates)):
        raise ValueError("finite two-dimensional point coordinates required")
    lon, lat = map(float, coordinates)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("point coordinates must be WGS84 longitude/latitude")
    return {"type": "Point", "coordinates": [lon, lat]}, [lon, lat, lon, lat]


def _dates(start_date: str, end_date: str) -> tuple[str, str]:
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("ISO calendar dates required") from exc
    if end < start or (end - start).days > 366:
        raise ValueError("date interval must be ordered and at most 366 days")
    return f"{start.isoformat()}T00:00:00Z", f"{end.isoformat()}T23:59:59Z"


def _read_bounded(response: httpx.Response, max_bytes: int) -> bytes:
    if response.status_code != 200:
        raise RuntimeError(f"provider HTTP {response.status_code}")
    data = bytearray()
    for chunk in response.iter_bytes():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise RuntimeError("provider response exceeds byte limit")
    return bytes(data)


def _request_json(url: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if url not in (_EARTH_SEARCH, _PLANETARY_COMPUTER, _PC_TOKEN):
        raise ValueError("non-allowlisted endpoint")
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        with client.stream("POST" if body is not None else "GET", url, json=body) as response:
            import json

            payload = json.loads(_read_bounded(response, _MAX_JSON_BYTES))
    if not isinstance(payload, dict):
        raise RuntimeError("provider response is not a JSON object")
    return payload


def _clean_asset(href: Any, provider_id: str) -> str | None:
    if not isinstance(href, str):
        return None
    parsed = urlsplit(href)
    host = _EARTH_ASSET_HOST if provider_id == "sentinel2-c1-earth-search" else _PC_ASSET_HOST
    path_prefix = "/sentinel-2-c1-l2a/" if provider_id == "sentinel2-c1-earth-search" else "/hls2/"
    if parsed.scheme != "https" or parsed.hostname != host or parsed.port is not None or parsed.username or parsed.password or not parsed.path.startswith(path_prefix) or not parsed.path.endswith(".tif"):
        return None
    # A provider's transient query signature is never returned to callers.
    return f"https://{host}{parsed.path}"


def search_field_imagery(
    geometry: dict[str, Any], provider_id: str, start_date: str, end_date: str,
    limit: int = 5, network_mode: str = "offline",
) -> dict[str, Any]:
    """Discover up to ten scenes; no pixels are fetched or interpreted."""
    provider = _provider(provider_id)
    polygon, bbox = _valid_search_geometry(geometry)
    start, end = _dates(start_date, end_date)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer from 1 to 10")
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    result: dict[str, Any] = {
        "status": "blocked_offline", "provider": dict(provider), "count": 0, "scenes": [],
        "query": {"start_date": start_date, "end_date": end_date, "limit": limit, "bbox": bbox,
                  "geometry_type": polygon["type"],
                  "spatial_scope": "at_location" if polygon["type"] == "Point" else "field_polygon"},
        "limitations": provider["limitations"],
    }
    if provider_id == "hls-earth-engine":
        result["status"] = "not_configured"
        return result
    if network_mode == "offline":
        return result
    endpoint = _EARTH_SEARCH if provider_id == "sentinel2-c1-earth-search" else _PLANETARY_COMPUTER
    body = {"collections": [provider["collection"]], "intersects": polygon,
            "bbox": bbox, "datetime": f"{start}/{end}", "limit": limit}
    # STAC does not permit intersects and bbox simultaneously in a search.
    del body["bbox"]
    try:
        payload = _request_json(endpoint, body=body)
        features = payload.get("features")
        if not isinstance(features, list) or len(features) > limit:
            raise RuntimeError("invalid or oversized STAC feature list")
        scenes: list[dict[str, Any]] = []
        wanted = (("red", "nir", "scl") if endpoint == _EARTH_SEARCH else
                  ("B04", "B05", "Fmask") if provider_id == "hls-l30-planetary-computer" else
                  ("B04", "B8A", "Fmask"))
        for item in features:
            if not isinstance(item, dict) or item.get("collection") != provider["collection"]:
                continue
            item_id = item.get("id")
            properties = item.get("properties") or {}
            if not isinstance(item_id, str) or len(item_id) > 160 or not isinstance(properties, dict):
                continue
            assets: dict[str, dict[str, str]] = {}
            item_assets = item.get("assets") or {}
            if not isinstance(item_assets, dict):
                continue
            for key in wanted:
                asset = item_assets.get(key)
                href = _clean_asset(asset.get("href"), provider_id) if isinstance(asset, dict) else None
                if href:
                    assets[key] = {"id": f"{provider['collection']}:{item_id}:{key}", "href": href}
            scenes.append({
                "id": f"{provider['collection']}:{item_id}", "source_item_id": item_id,
                "collection": provider["collection"], "acquired_at": properties.get("datetime"),
                "scene_cloud_percent": properties.get("eo:cloud_cover"),
                "assets": assets, "evidence_role": "observation_metadata",
                "field_clear_fraction": None,
            })
        result.update(status="available", count=len(scenes), scenes=scenes)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        result.update(status="unavailable", error=type(exc).__name__)
    return result


def probe_asset_range(scene: dict[str, Any], asset_key: str, provider_id: str, network_mode: str = "offline") -> dict[str, Any]:
    """Read <=16 KiB of an allowlisted COG for an anonymous access proof.

    The receipt contains no pixel interpretation, token, or signed URL.
    """
    provider = _provider(provider_id)
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    receipt: dict[str, Any] = {"status": "blocked_offline", "provider_id": provider_id,
                               "scene_id": scene.get("id"), "asset_key": asset_key,
                               "bytes_read": 0, "http_status": None}
    if provider_id == "hls-earth-engine":
        receipt["status"] = "not_configured"
        return receipt
    if network_mode == "offline":
        return receipt
    expected_keys = (("red", "nir", "scl") if provider_id == "sentinel2-c1-earth-search" else
                     ("B04", "B05", "Fmask") if provider_id == "hls-l30-planetary-computer" else
                     ("B04", "B8A", "Fmask"))
    if asset_key not in expected_keys or not isinstance(scene, dict):
        raise ValueError("unsupported asset")
    assets = scene.get("assets")
    asset = assets.get(asset_key) if isinstance(assets, dict) else None
    href = _clean_asset(asset.get("href"), provider_id) if isinstance(asset, dict) else None
    if not href or scene.get("collection") != provider["collection"]:
        raise ValueError("invalid allowlisted scene asset")
    try:
        if provider_id.startswith("hls-"):
            token = _request_json(_PC_TOKEN).get("token")
            if not isinstance(token, str) or not token or len(token) > 2048:
                raise RuntimeError("public SAS unavailable")
            href = f"{href}?{token.lstrip('?')}"
        with httpx.Client(timeout=12, follow_redirects=False) as client:
            with client.stream("GET", href, headers={"Range": f"bytes=0-{_MAX_RANGE_BYTES - 1}"}) as response:
                receipt["http_status"] = response.status_code
                if response.status_code != 206:
                    receipt["status"] = "unavailable"
                    return receipt
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith("bytes 0-"):
                    receipt["status"] = "invalid_range_response"
                    return receipt
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > _MAX_RANGE_BYTES:
                        raise RuntimeError("range exceeded byte limit")
                receipt.update(status="available", bytes_read=len(data), tiff_header=bytes(data[:4]) in (b"II*\x00", b"MM\x00*"))
    except (httpx.HTTPError, RuntimeError, ValueError):
        receipt["status"] = "unavailable"
    return receipt
