"""The optional worker must not bypass workspace, boundary or offline rules."""
import json
import sys
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.imagery_analytics import _request_identity
from agronomy_agent.imagery_store import ImageryStore
from agronomy_agent.server.app import create_app
from agronomy_agent.server.services import imagery_service as service
from agronomy_agent.server.settings import build_settings

OWNER = {"X-Agronomy-User-Email": "imagery-owner@example.test"}
OUTSIDER = {"X-Agronomy-User-Email": "imagery-outsider@example.test"}
GEOMETRY = {"kind": "polygon", "points": [{"lat": 40.15, "lon": -103.15},
    {"lat": 40.15, "lon": -103.14}, {"lat": 40.16, "lon": -103.14}]}
PAYLOAD = {"provider_id": "hls-s30-planetary-computer", "start_date": "2021-06-01", "end_date": "2021-06-15"}


@pytest.fixture
def runtime(tmp_path):
    settings = build_settings(db_path=tmp_path / "db.sqlite", artifact_root=tmp_path / "artifacts",
        imagery_cache_root=tmp_path / "imagery", imagery_worker_python=sys.executable, network_mode="online")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/demo/fields", headers=OWNER,
            json={"name": "Imagery fixture", "field": {}, "geometry": GEOMETRY})
        assert response.status_code == 201, response.text
        field_id = response.json()["field"]["field_context_id"]
        yield client, field_id, settings


def _worker(settings, cache, geometry, payload):
    from agronomy_agent.imagery_analytics import PREVIEW_VERSION
    _, bounds, geom, request = _request_identity(geometry, payload["provider_id"], payload.get("scene_id"),
        payload["start_date"], payload["end_date"], payload.get("buffer_m", 0), None)
    store = ImageryStore(cache)
    chip = "a" * 64
    names = {"npz": chip + ".npz", "png": chip + ".png", "receipt": chip + ".json"}
    result = {"status": "available", "chip_hash": chip, "request_hash": request, "preview_version": PREVIEW_VERSION,
        "geometry_hash": geom, "process_hash": "b" * 64, "provider_id": payload["provider_id"],
        "source": {"collection": "hls2-s30", "scene_id": "hls2-s30:fixture", "asset_ids": {}},
        "qa": {"valid_area_fraction": .75}, "zonal_stats": {"NDVI": {"mean": .5}},
        "cache_files": names, "created_at": "2021-06-10T00:00:00Z"}
    (cache / names["npz"]).write_bytes(b"fixture")
    (cache / names["png"]).write_bytes(b"fixture PNG")
    (cache / names["receipt"]).write_text(json.dumps(result))
    store.put(result, bounds)
    return result


def test_authenticated_analysis_preview_and_cache_integrity(runtime, monkeypatch):
    client, field_id, settings = runtime
    monkeypatch.setattr(service, "_run_worker", _worker)
    base = f"/api/demo/fields/{field_id}/imagery"
    assert client.get(base + "/analytics", headers=OWNER).json()["status"] == "ready"
    result = client.post(base + "/analyze", headers=OWNER, json=PAYLOAD)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "available"
    assert "cache_files" not in result.json()
    assert str(settings.imagery_cache_root) not in result.text
    url = result.json()["preview_url"]
    image = client.get(url, headers=OWNER)
    assert image.status_code == 200 and image.content == b"fixture PNG"
    assert image.headers["cache-control"] == "private, no-store"
    assert client.get(url, headers=OUTSIDER).status_code == 403
    assert client.post(base + "/analyze", headers=OUTSIDER, json=PAYLOAD).status_code == 403
    assert client.get(base + "/analytics", headers=OUTSIDER).status_code == 403
    monkeypatch.setattr(service, "_run_worker", lambda *a: pytest.fail("cached work invoked worker"))
    assert client.post(base + "/analyze", headers=OWNER, json=PAYLOAD).json()["cache_hit"]
    next(settings.imagery_cache_root.glob("*/*.png")).write_bytes(b"corrupt")
    assert client.get(url, headers=OWNER).status_code == 404


def test_saved_boundary_change_invalidates_preview_and_inflight_result(runtime, monkeypatch):
    client, field_id, _ = runtime
    path = f"/api/demo/fields/{field_id}"
    def worker(*args):
        result = _worker(*args)
        update = client.patch(path, headers=OWNER, json={"name": "Changed", "field": {},
            "geometry": {**GEOMETRY, "points": [{**p, "lon": p["lon"] + .001} for p in GEOMETRY["points"]]}})
        assert update.status_code == 200
        return result
    monkeypatch.setattr(service, "_run_worker", worker)
    assert client.post(path + "/imagery/analyze", headers=OWNER, json=PAYLOAD).status_code == 409
    assert client.get(path + "/imagery/analyses/" + "a" * 64 + "/preview.png", headers=OWNER).status_code == 404


def test_offline_miss_never_launches_worker_and_fields_are_isolated(runtime, monkeypatch):
    _, _, settings = runtime
    field = {"workspace_id": "workspace", "id": "field"}
    geometry = {"type": "Polygon", "coordinates": [[[p["lon"], p["lat"]] for p in GEOMETRY["points"]]]}
    geometry["coordinates"][0].append(geometry["coordinates"][0][0])
    monkeypatch.setattr(service, "_run_worker", lambda *a: pytest.fail("offline invoked worker"))
    assert service.analyze(replace(settings, network_mode="offline"), field, geometry, PAYLOAD)["status"] == "blocked_offline"
    assert service.field_cache(settings, field) != service.field_cache(settings, {**field, "workspace_id": "other"})
    assert service.analyze(replace(settings, imagery_worker_python=None), field, geometry, PAYLOAD)["status"] == "not_configured"


def test_worker_failure_and_unbound_result_are_sanitized(runtime, monkeypatch):
    client, field_id, _ = runtime
    monkeypatch.setattr(service, "_run_worker", lambda *a: {"status": "available", "chip_hash": "f" * 64,
        "cache_files": {"png": "/private/token?secret=foo"}})
    response = client.post(f"/api/demo/fields/{field_id}/imagery/analyze", headers=OWNER, json=PAYLOAD)
    assert response.json()["status"] == "unavailable"
    assert "secret" not in response.text
    assert client.post(f"/api/demo/fields/{field_id}/imagery/analyze", headers=OWNER,
        json={**PAYLOAD, "cache_root": "/private"}).status_code == 422


def test_worker_environment_has_no_account_credentials(tmp_path, monkeypatch):
    settings = build_settings(db_path=tmp_path / "d", artifact_root=tmp_path / "a",
        imagery_cache_root=tmp_path / "c", imagery_worker_python=sys.executable, network_mode="offline")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/private/credentials")
    monkeypatch.setenv("HF_TOKEN", "private")
    def run(command, **kwargs):
        assert "--online" not in command
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in kwargs["env"]
        assert "HF_TOKEN" not in kwargs["env"]
        assert kwargs["timeout"] == 150
        kwargs["stdout"].write(b'{"status":"blocked_offline"}')
        return type("Completed", (), {"returncode": 2})()
    monkeypatch.setattr(service.subprocess, "run", run)
    assert service._run_worker(settings, tmp_path / "c", {}, PAYLOAD)["status"] == "blocked_offline"
