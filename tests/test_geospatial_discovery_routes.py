import pytest
from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from agronomy_agent.geospatial import discovery

OWNER = {"X-Agronomy-User-Email": "geo-owner@example.test"}
OUTSIDER = {"X-Agronomy-User-Email": "geo-outsider@example.test"}
GEOMETRY = {"kind": "point", "point": {"lat": 52.15, "lon": -106.65}}
PAYLOAD = {"source_id": "ca-hrdem-mosaic-1m", "context_buffer_m": 100}


@pytest.fixture
def runtime(tmp_path):
    settings = build_settings(db_path=tmp_path / "db.sqlite", artifact_root=tmp_path / "artifacts", network_mode="offline")
    with TestClient(create_app(settings)) as client:
        result = client.post("/api/demo/fields", headers=OWNER, json={"name": "Source discovery fixture", "field": {}, "geometry": GEOMETRY})
        assert result.status_code == 201
        yield client, result.json()["field"]["field_context_id"]


def test_authorized_offline_discovery_and_catalog(runtime, monkeypatch):
    client, field_id = runtime
    monkeypatch.setattr(discovery, "_request", lambda *a: pytest.fail("offline network"))
    catalog = client.get("/api/geo/sources").json()
    assert catalog["schema_version"] == "geospatial.source_catalog.v1"
    assert catalog["network_mode"] == "offline"
    url = f"/api/demo/fields/{field_id}/geospatial/discover"
    response = client.post(url, headers=OWNER, json=PAYLOAD)
    assert response.status_code == 200 and response.json()["status"] == "blocked_offline"
    assert client.post(url, headers=OUTSIDER, json=PAYLOAD).status_code == 403
    assert client.post(url, headers=OWNER, json={**PAYLOAD, "url": "http://localhost/"}).status_code == 422
    assert client.post(url, headers=OWNER, json={**PAYLOAD, "source_id": "arbitrary"}).status_code == 422


def test_geometry_race_drops_inflight_metadata(runtime, monkeypatch):
    client, field_id = runtime
    def changed(*args, **kwargs):
        result = client.patch(f"/api/demo/fields/{field_id}", headers=OWNER,
            json={"name": "Moved", "field": {}, "geometry": {"kind": "point", "point": {"lat": 53, "lon": -107}}})
        assert result.status_code == 200
        return {"status": "available", "records": []}
    monkeypatch.setattr(discovery, "discover_sources", changed)
    assert client.post(f"/api/demo/fields/{field_id}/geospatial/discover", headers=OWNER, json=PAYLOAD).status_code == 409
