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
