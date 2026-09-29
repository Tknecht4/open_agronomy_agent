"""Discovery is metadata evidence, with access/errors/coverage kept separate."""
import pytest

from agronomy_agent.geospatial import discovery as d
from agronomy_agent.geospatial.catalog import source_catalog, source_definition

POINT = {"type": "Point", "coordinates": [-106.65, 52.15]}


def item(**changes):
    return {"id": "fixture", "collection": "hrdem-mosaic-1m", "properties": {"proj:epsg": 3979, "datetime": "2025-01-01T00:00:00Z"},
            "assets": {"dtm": {"href": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-mosaic-1m/fixture-dtm.tif"}}, **changes}


def test_catalog_copy_and_access_distinction():
    first = source_catalog()
    first["sources"][0]["id"] = "mutated"
    assert source_catalog()["sources"][0]["id"] != "mutated"
    assert source_definition("naip-earth-search")["payment_required"] is True
    assert source_definition("cop-dem-glo-30-earth-search")["surface_type"] == "DSM"
    assert source_definition("ca-hrdem-lidar")["resolution_m"] is None
    assert not source_definition("ca-hrdem-mosaic-1m")["api_key_required"]


def test_offline_is_no_network_and_no_coverage_claim(monkeypatch):
    monkeypatch.setattr(d, "_request", lambda *a: pytest.fail("offline network"))
    result = d.discover_sources(POINT, "ca-hrdem-mosaic-1m", context_buffer_m=100)
    assert result["status"] == "blocked_offline"
    assert result["coverage_status"] == "unverified"
    assert result["pixel_bytes_read"] == result["pages_requested"] == 0
    assert result["query"]["bbox"][0] < POINT["coordinates"][0]
    assert result["query"]["bbox"][2] > POINT["coordinates"][0]


def test_native_grid_and_acquisition_not_invented(monkeypatch):
    monkeypatch.setattr(d, "_request", lambda source, query: {"features": [item()]})
    result = d.discover_sources(POINT, "ca-hrdem-mosaic-1m", network_mode="online", limit=1)
    assert result["status"] == "available" and result["page_limit_reached"]
    record = result["records"][0]
    assert record["acquisition_interval"] is None
    assert record["native_grid_verified"] is record["pixel_coverage_verified"] is False
    assert record["declared_horizontal_epsg"] == 3979
    assert record["asset_href"].endswith("fixture-dtm.tif")
    assert len(record["source_metadata_sha256"]) == 64


@pytest.mark.parametrize("response, status", [
    ({"features": []}, "no_records"),
    ({"error": "upstream failed", "features": []}, "provider_unavailable"),
    ({"features": [item(collection="unknown")]}, "provider_unavailable"),
    ({"features": ["invalid"]}, "provider_unavailable"),
    ({"items": []}, "provider_unavailable"),
])
def test_empty_malformed_and_provider_error_remain_distinct(monkeypatch, response, status):
    monkeypatch.setattr(d, "_request", lambda *a: response)
    result = d.discover_sources(POINT, "ca-hrdem-mosaic-1m", network_mode="online")
    assert result["status"] == status and result["coverage_status"] == "unverified"


@pytest.mark.parametrize("href", [
    "http://canelevation-dem.s3.ca-central-1.amazonaws.com/a.tif",
    "https://attacker.example/a.tif",
    "https://canelevation-dem.s3.ca-central-1.amazonaws.com/a.tif?secret=123",
    "https://user:secret@canelevation-dem.s3.ca-central-1.amazonaws.com/a.tif",
    "https://canelevation-dem.s3.ca-central-1.amazonaws.com:broken/a.tif",
    "file:///private/field.tif", "s3://naip-analytic/a.tif",
])
def test_untrusted_or_signed_asset_links_not_returned(monkeypatch, href):
    monkeypatch.setattr(d, "_request", lambda *a: {"features": [item(assets={"dtm": {"href": href}})]})
    result = d.discover_sources(POINT, "ca-hrdem-mosaic-1m", network_mode="online")
    assert result["records"][0]["asset_href"] is None
    assert result["records"][0]["asset_status"] == "not_qualified"


def test_dsm_not_substituted_for_dtm(monkeypatch):
    monkeypatch.setattr(d, "_request", lambda *a: {"features": [item(assets={"dsm": {"href": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/a.tif"}})]})
    result = d.discover_sources(POINT, "ca-hrdem-mosaic-1m", network_mode="online")
    assert result["records"][0]["asset_key"] == "dtm" and result["records"][0]["asset_href"] is None


def test_tnm_http_200_error_not_empty_coverage(monkeypatch):
    monkeypatch.setattr(d, "_request", lambda *a: {"error": "Expecting value: line 1 column 1 (char 0)"})
    assert d.discover_sources(POINT, "us-3dep-1m", network_mode="online")["status"] == "provider_unavailable"


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 11}, {"context_buffer_m": -1},
                                     {"context_buffer_m": 2.5}, {"start_date": "2025-01-01"}, {"network_mode": "maybe"}])
def test_invalid_policy_rejected_before_network(monkeypatch, kwargs):
    monkeypatch.setattr(d, "_request", lambda *a: pytest.fail("invalid request network"))
    with pytest.raises(ValueError):
        d.discover_sources(POINT, "ca-hrdem-mosaic-1m", **kwargs)


def test_legacy_imagery_routes_through_existing_contract(monkeypatch):
    from agronomy_agent import field_imagery
    monkeypatch.setattr(field_imagery, "search_field_imagery", lambda *a: {"status": "available", "scenes": [], "count": 0})
    assert d.discover_sources(POINT, "hls-s30-planetary-computer", start_date="2025-01-01", end_date="2025-01-02")["status"] == "available"
    assert d.discover_sources(POINT, "hls-earth-engine")["status"] == "not_configured"


@pytest.mark.parametrize("status, body", [(200, b"x" * (d.MAX_RESPONSE_BYTES + 1)),
    (302, b""), (200, b'{"error":"upstream failure"}'), (200, b'{"features":[],"value":NaN}')])
def test_transport_rejects_oversize_redirects_errors_and_nonfinite_json(monkeypatch, status, body):
    import httpx
    real_client = httpx.Client
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=body, headers={"Location": "https://attacker.example/next"})
    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(d.httpx, "Client", factory)
    result = d.discover_sources(POINT, "ca-hrdem-mosaic-1m", network_mode="online")
    assert result["status"] == "provider_unavailable"
    assert len(calls) == 1 and calls[0].url.host == "datacube.services.geo.ca"
