"""Bounded, anonymous STAC discovery for a saved point or field polygon.

This module returns *metadata*, not field pixels or a vegetation diagnosis.
Planetary Computer asset signing is confined to a single bounded range probe;
signed URLs and tokens are never returned or logged.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from shapely.geometry import shape
from agronomy_agent.geospatial.geometry import canonical_geometry


_EARTH_SEARCH = "https://earth-search.aws.element84.com/v1/search"
_PLANETARY_COMPUTER = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
_PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/hls2euwest/hls2"
_EARTH_ASSET_HOST = "e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"
_PC_ASSET_HOST = "hls2euwest.blob.core.windows.net"
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_RANGE_BYTES = 16 * 1024
MAX_SCENE_CLOUD_PERCENT = 70
MAX_SERIES_SCENES = 320
_SERIES_PAGE_SIZE = 64
_MAX_SERIES_PAGES = 8
HLS_SERIES_PROVIDERS = {
    "hls2-s30": "hls-s30-planetary-computer",
    "hls2-l30": "hls-l30-planetary-computer",
}


def scene_cloud_percent(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and 0 <= value <= 100 else None


def scene_cloud_exceeds_limit(value: Any) -> bool:
    cloud = scene_cloud_percent(value)
    return cloud is not None and cloud > MAX_SCENE_CLOUD_PERCENT


_SERIES_BANDS = ("B02", "B03", "B04", "B05", "B06", "B07", "B8A", "B11", "B12", "Fmask")


def _series_features(body: dict[str, Any]) -> list[dict[str, Any]] | None:
    features = []
    tokens = set()
    for _ in range(_MAX_SERIES_PAGES):
        payload = _request_json(_PLANETARY_COMPUTER, body=body)
        page, links = payload.get("features"), payload.get("links", [])
        if not isinstance(page, list) or len(page) > _SERIES_PAGE_SIZE or not isinstance(links, list):
            raise RuntimeError("invalid imagery catalog response")
        features.extend(page)
        if len(features) > MAX_SERIES_SCENES:
            return None
        following = [link for link in links if isinstance(link, dict) and link.get("rel") == "next"]
        if not following:
            return features
        if len(following) != 1:
            raise RuntimeError("invalid imagery catalog continuation")
        link = following[0]
        values = link.get("body")
        token = values.get("token") if isinstance(values, dict) else None
        if (link.get("href") != _PLANETARY_COMPUTER or link.get("method") != "POST"
                or not isinstance(token, str) or not re.fullmatch(r"next:[A-Za-z0-9_.:-]{1,256}", token)
                or token in tokens or not page):
            raise RuntimeError("invalid imagery catalog continuation")
        # Only the cursor comes from the link. Keep the original geometry,
        # dates, cloud filter and endpoint on every page.
        tokens.add(token)
        body = {**body, "token": token}
    return None


def search_hls_series(geometry: dict, start_date: str, end_date: str) -> dict[str, Any]:
    polygon, _ = _valid_search_geometry(geometry)
    start, end = _dates(start_date, end_date)
    features = _series_features({
        "collections": list(HLS_SERIES_PROVIDERS),
        "intersects": polygon,
        "datetime": f"{start}/{end}",
        "query": {"eo:cloud_cover": {"lte": MAX_SCENE_CLOUD_PERCENT}},
        "fields": {"include": ["id", "collection", "properties.datetime", "properties.created",
                               "properties.eo:cloud_cover", *(f"assets.{key}" for key in _SERIES_BANDS)],
                   "exclude": ["geometry", "bbox", "links"]},
        "limit": _SERIES_PAGE_SIZE,
    })
    if features is None:
        return {"status": "range_too_large", "scenes": []}
    scenes = {}
    for item in features:
        if not isinstance(item, dict) or not isinstance(item.get("properties"), dict):
            raise RuntimeError("invalid imagery catalog item")
        collection = item.get("collection")
        item_id = item.get("id")
        if not isinstance(collection, str) or collection not in HLS_SERIES_PROVIDERS or not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", item_id):
            raise RuntimeError("invalid HLS scene identity")
        props = item["properties"]
        cloud = scene_cloud_percent(props.get("eo:cloud_cover"))
        if cloud is None or cloud > MAX_SCENE_CLOUD_PERCENT:
            continue
        acquired = props.get("datetime")
        if not isinstance(acquired, str) or len(acquired) > 40:
            raise RuntimeError("invalid HLS acquisition time")
        instant = datetime.fromisoformat(acquired.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise RuntimeError("invalid HLS acquisition timezone")
        utc = instant.astimezone(timezone.utc)
        if not start_date <= utc.date().isoformat() <= end_date:
            raise RuntimeError("imagery catalog returned dates outside the requested range")
        scene_id = f"{collection}:{item_id}"
        scene = {"scene_id": scene_id, "provider_id": HLS_SERIES_PROVIDERS[collection],
                 "acquired_at": utc.isoformat(timespec="microseconds"), "scene_cloud_percent": cloud}
        # Retain only unsigned asset metadata for the internal worker handoff.
        assets = {}
        raw_assets = item.get("assets")
        for key, asset in (raw_assets if isinstance(raw_assets, dict) else {}).items():
            if not isinstance(asset, dict):
                continue
            href = _clean_asset(asset.get("href"), scene["provider_id"])
            if href and key in _SERIES_BANDS:
                assets[key] = {k: asset.get(k) for k in ("type", "raster:bands")} | {"href": href}
        if assets:
            scene["catalog_item"] = {"id": item_id, "collection": collection, "assets": assets,
                                     "properties": {k: props.get(k) for k in ("datetime", "created", "eo:cloud_cover")}}
        if scenes.setdefault(scene_id, scene) != scene:
            raise RuntimeError("imagery catalog returned conflicting scene metadata")
    return {"status": "available", "scenes": sorted(scenes.values(), key=lambda scene: (scene["acquired_at"], scene["scene_id"]))}


def provider_catalog() -> list[dict[str, Any]]:
    """Credential-free legacy imagery view of the shared source catalog."""
    from agronomy_agent.geospatial.catalog import imagery_provider_catalog
    return imagery_provider_catalog()


def _provider(provider_id: str) -> dict[str, Any]:
    for provider in provider_catalog():
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
        polygon = shape(canonical_geometry({"type": "Polygon", "coordinates": coordinates}, allowed_types=("Polygon",), max_vertices=500))
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
    canonical_geometry({"type": "Point", "coordinates": [lon, lat]}, allowed_types=("Point",))
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
            "datetime": f"{start}/{end}", "limit": limit}
    if endpoint == _PLANETARY_COMPUTER:
        body["query"] = {"eo:cloud_cover": {"lte": MAX_SCENE_CLOUD_PERCENT}}
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
            cloud = scene_cloud_percent(properties.get("eo:cloud_cover"))
            if scene_cloud_exceeds_limit(cloud):
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
                "scene_cloud_percent": cloud,
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
