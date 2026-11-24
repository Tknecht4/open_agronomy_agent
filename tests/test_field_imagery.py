"""Anonymous field imagery discovery and network boundary contracts."""

from __future__ import annotations

import json

import httpx
import pytest

from agronomy_agent import field_imagery as imagery


FIELD = {"type": "Polygon", "coordinates": [[
    [-106.7, 52.1], [-106.69, 52.1], [-106.69, 52.11],
    [-106.7, 52.11], [-106.7, 52.1],
]]}


def test_catalog_is_detached_and_account_requirements_are_explicit() -> None:
    catalog = imagery.provider_catalog()
    assert [row["id"] for row in catalog] == [
        "sentinel2-c1-earth-search", "hls-s30-planetary-computer",
        "hls-l30-planetary-computer", "hls-earth-engine",
    ]
    assert all(row["account_required"] is False and row["payment_required"] is False for row in catalog[:3])
    assert catalog[3]["account_required"] is True and catalog[3]["project_required"] is True
    catalog[0]["capabilities"].clear()
    assert imagery.provider_catalog()[0]["capabilities"]
    assert "token" not in json.dumps(catalog).lower()


def test_offline_and_unconfigured_providers_do_not_make_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imagery, "_request_json", lambda *_a, **_k: pytest.fail("network attempted"))
    result = imagery.search_field_imagery(FIELD, "sentinel2-c1-earth-search", "2025-07-01", "2025-07-15")
    assert result["status"] == "blocked_offline" and result["scenes"] == []
    gee = imagery.search_field_imagery(FIELD, "hls-earth-engine", "2025-07-01", "2025-07-15", network_mode="online")
    assert gee["status"] == "not_configured"


def test_saved_point_discovery_does_not_invent_a_polygon(monkeypatch):
    point = {"type": "Point", "coordinates": [-106.7, 52.1]}
    seen = []
    def request(url, *, body):
        seen.append(body)
        return {"features": []}
    monkeypatch.setattr(imagery, "_request_json", request)
    result = imagery.search_field_imagery(point, "hls-s30-planetary-computer",
        "2025-07-01", "2025-07-15", network_mode="offline")
    assert result["status"] == "blocked_offline" and not seen
    result = imagery.search_field_imagery(point, "hls-s30-planetary-computer",
        "2025-07-01", "2025-07-15", network_mode="online")
    assert seen[0]["intersects"] == point
    assert "bbox" not in seen[0]
    assert result["query"]["geometry_type"] == "Point"
    assert result["query"]["spatial_scope"] == "at_location"
    assert result["query"]["bbox"] == [-106.7, 52.1, -106.7, 52.1]


@pytest.mark.parametrize("point", [
    {"type": "Point", "coordinates": [True, 52]},
    {"type": "Point", "coordinates": [-106, float("nan")]},
    {"type": "Point", "coordinates": [-181, 52]},
    {"type": "Point", "coordinates": [-106, 91]},
    {"type": "Point", "coordinates": [-106, 52, 100]},
    {"type": "Point", "coordinates": ["-106", 52]},
    {"type": "Point", "coordinates": [-106, 52], "crs": "EPSG:3857"},
])
def test_invalid_points_fail_before_discovery(point, monkeypatch):
    monkeypatch.setattr(imagery, "_request_json", lambda *a, **k: pytest.fail("invalid point egress"))
    with pytest.raises(ValueError):
        imagery.search_field_imagery(point, "hls-s30-planetary-computer",
            "2025-07-01", "2025-07-15", network_mode="online")


@pytest.mark.parametrize("change", [
    {"type": "Point"},
    {"crs": "EPSG:3857"},
    {"coordinates": [[[-106.7, 52.1], [-106.69, 52.11], [-106.7, 52.11], [-106.69, 52.1], [-106.7, 52.1]]]},
    {"coordinates": [[[-106.7, 52.1], [-105.7, 52.1], [-105.7, 52.11], [-106.7, 52.1]]]},
])
def test_rejects_invalid_or_unbounded_geometry(change: dict) -> None:
    with pytest.raises(ValueError):
        imagery.search_field_imagery(FIELD | change, "sentinel2-c1-earth-search", "2025-07-01", "2025-07-15")


@pytest.mark.parametrize("start,end,limit", [
    ("2025-07-15", "2025-07-01", 1),
    ("2024-01-01", "2025-07-01", 1),
    ("2025-07-01", "2025-07-15", 11),
    ("2025-07-01", "2025-07-15", True),
])
def test_rejects_unbounded_search(start: str, end: str, limit: int) -> None:
    with pytest.raises(ValueError):
        imagery.search_field_imagery(FIELD, "sentinel2-c1-earth-search", start, end, limit)


def test_discovery_returns_stable_ids_and_strips_signed_asset_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    href = "https://hls2euwest.blob.core.windows.net/hls2/S30/example.B04.tif?sig=SECRET"
    payload = {"features": [{
        "id": "HLS.S30.example", "collection": "hls2-s30",
        "properties": {"datetime": "2025-07-15T12:00:00Z", "eo:cloud_cover": 15},
        "assets": {"B04": {"href": href}, "B8A": {"href": "http://evil.invalid/file.tif"}},
    }]}
    seen = []

    def fake_request(url: str, *, body: dict) -> dict:
        seen.append((url, body))
        return payload

    monkeypatch.setattr(imagery, "_request_json", fake_request)
    result = imagery.search_field_imagery(FIELD, "hls-s30-planetary-computer", "2025-07-01", "2025-07-15", limit=1, network_mode="online")
    assert result["status"] == "available" and result["count"] == 1
    scene = result["scenes"][0]
    assert scene["id"] == "hls2-s30:HLS.S30.example"
    assert scene["assets"]["B04"]["id"] == "hls2-s30:HLS.S30.example:B04"
    assert scene["field_clear_fraction"] is None
    assert "SECRET" not in json.dumps(result)
    assert "B8A" not in scene["assets"]
    assert seen[0][1]["collections"] == ["hls2-s30"]
    assert "intersects" in seen[0][1] and "bbox" not in seen[0][1]


def test_l30_uses_landsat_near_infrared_band(monkeypatch: pytest.MonkeyPatch) -> None:
    base = "https://hls2euwest.blob.core.windows.net/hls2/L30/example."
    monkeypatch.setattr(imagery, "_request_json", lambda *_a, **_k: {"features": [{
        "id": "HLS.L30.example", "collection": "hls2-l30", "properties": {},
        "assets": {key: {"href": f"{base}{key}.tif"} for key in ("B04", "B05", "B8A", "Fmask")},
    }]})
    result = imagery.search_field_imagery(FIELD, "hls-l30-planetary-computer", "2025-07-01", "2025-07-15", network_mode="online")
    assert set(result["scenes"][0]["assets"]) == {"B04", "B05", "Fmask"}


def test_series_pushes_down_cloud_limit_and_checks_catalog_response(monkeypatch):
    acquisitions = [
        {"collection": collection, "id": name,
         "properties": {"datetime": f"2025-07-{day:02d}T12:00:00Z", "eo:cloud_cover": cloud}}
        for collection, name, day, cloud in (
            ("hls2-l30", "landsat", 15, 70),
            ("hls2-s30", "too-cloudy", 12, 70.01),
            ("hls2-s30", "sentinel", 10, 0),
            ("hls2-s30", "unknown", 14, None),
        )
    ]

    calls = []

    def response(url, *, body):
        assert url == imagery._PLANETARY_COMPUTER
        assert body["query"] == {"eo:cloud_cover": {"lte": 70}}
        assert body["collections"] == ["hls2-s30", "hls2-l30"]
        assert body["intersects"] == FIELD
        assert "assets.B04" in body["fields"]["include"]
        calls.append(body)
        if "token" not in body:
            return {"features": acquisitions[:2], "links": [
                {"rel": "next", "method": "POST", "href": url,
                 "body": {"token": "next:hls2-l30:landsat", "intersects": {"type": "Point", "coordinates": [0, 0]}}},
            ]}
        assert body["token"] == "next:hls2-l30:landsat"
        sentinel = acquisitions[2] | {"assets": {"B04": {
            "href": "https://hls2euwest.blob.core.windows.net/hls2/test.tif?sig=redacted"}}}
        return {"features": [sentinel, acquisitions[3]]}

    monkeypatch.setattr(imagery, "_request_json", response)
    scenes = imagery.search_hls_series(FIELD, "2025-07-01", "2025-07-15")["scenes"]
    assert [row["scene_id"] for row in scenes] == ["hls2-s30:sentinel", "hls2-l30:landsat"]
    assert scenes[1]["scene_cloud_percent"] == 70
    assert len(calls) == 2
    assert scenes[0]["catalog_item"]["assets"]["B04"]["href"].endswith("/test.tif")
    monkeypatch.setattr(imagery, "_request_json", lambda *args, **kwargs: {
        "features": acquisitions, "links": [{"rel": "next", "href": "https://fixture.invalid"}],
    })
    with pytest.raises(RuntimeError, match="invalid imagery catalog continuation"):
        imagery.search_hls_series(FIELD, "2025-07-01", "2025-07-15")
    monkeypatch.setattr(imagery, "MAX_SERIES_SCENES", 1)
    monkeypatch.setattr(imagery, "_request_json", lambda *args, **kwargs: {"features": acquisitions})
    assert imagery.search_hls_series(FIELD, "2025-07-01", "2025-07-15") == {"status": "range_too_large", "scenes": []}


def test_redirects_are_rejected_and_range_receipt_has_no_sas(monkeypatch: pytest.MonkeyPatch) -> None:
    href = "https://hls2euwest.blob.core.windows.net/hls2/S30/example.B04.tif"
    scene = {"id": "hls2-s30:example", "collection": "hls2-s30", "assets": {"B04": {"href": href}}}
    monkeypatch.setattr(imagery, "_request_json", lambda *_a, **_k: {"token": "sig=SECRET"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "hls2euwest.blob.core.windows.net"
        assert request.headers["Range"] == "bytes=0-16383"
        return httpx.Response(206, headers={"Content-Range": "bytes 0-3/100"}, content=b"II*\x00")

    original_client = httpx.Client
    monkeypatch.setattr(imagery.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    receipt = imagery.probe_asset_range(scene, "B04", "hls-s30-planetary-computer", "online")
    assert receipt["status"] == "available" and receipt["bytes_read"] == 4
    assert "SECRET" not in json.dumps(receipt)

    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://example.com/"})

    monkeypatch.setattr(imagery.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(redirect), **kwargs))
    assert imagery.probe_asset_range(scene, "B04", "hls-s30-planetary-computer", "online")["status"] == "unavailable"
