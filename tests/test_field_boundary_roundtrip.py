"""Dense field boundaries must survive save/update, or fail explicitly."""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


OWNER = {"X-Agronomy-User-Email": "boundary-roundtrip@example.test"}


@pytest.fixture
def client(tmp_path):
    settings = build_settings(
        db_path=tmp_path / "boundaries.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _payload(count=320, *, offset=0.0):
    # Deterministic synthetic field with enough vertices to expose prefix loss.
    points = [
        {"lat": 49.02 + .003 * math.sin(2 * math.pi * index / count),
         "lon": -111.05 + offset + .003 * math.cos(2 * math.pi * index / count)}
        for index in range(count)
    ]
    return {"name": "Synthetic dense field", "field": {"jurisdiction": "Alberta"},
            "geometry": {"kind": "polygon", "points": points}}


def _saved(client, payload):
    response = client.post("/api/demo/fields", headers=OWNER, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["field"]


def _assert_complete_geometry(field, expected):
    actual = field["geometry"]["points"]
    assert actual == expected["geometry"]["points"]
    actual_polygon = Polygon([(point["lon"], point["lat"]) for point in actual])
    expected_polygon = Polygon([
        (point["lon"], point["lat"]) for point in expected["geometry"]["points"]
    ])
    assert actual_polygon.equals_exact(expected_polygon, tolerance=0)


def test_dense_boundary_create_patch_and_reload_preserve_complete_support(client):
    original = _payload()
    created = _saved(client, original)
    field_id = created["field_context_id"]
    _assert_complete_geometry(created, original)

    replacement = _payload(370, offset=.001)
    updated = client.patch(f"/api/demo/fields/{field_id}", headers=OWNER, json=replacement)
    assert updated.status_code == 200, updated.text
    _assert_complete_geometry(updated.json()["field"], replacement)
    listing = client.get("/api/demo/fields", headers=OWNER)
    assert listing.status_code == 200
    reloaded = next(field for field in listing.json()["fields"] if field["field_context_id"] == field_id)
    _assert_complete_geometry(reloaded, replacement)
    stored = client.app.state.trace_store.get_phase4_field_context(field_id)
    assert stored["metadata"]["open_agronomy_agent"]["geometry"] == replacement["geometry"]


@pytest.mark.parametrize("invalid", ["not-a-coordinate", 95, True])
def test_vertex_after_old_prefix_is_validated_on_create_and_patch(client, invalid):
    valid = _payload()
    created = _saved(client, valid)
    field_id = created["field_context_id"]
    invalid_payload = _payload()
    invalid_payload["geometry"]["points"][275]["lat"] = invalid
    response = client.post("/api/demo/fields", headers=OWNER, json=invalid_payload)
    assert response.status_code == 422, response.text
    response = client.patch(f"/api/demo/fields/{field_id}", headers=OWNER, json=invalid_payload)
    assert response.status_code == 422, response.text
    stored = client.app.state.trace_store.get_phase4_field_context(field_id)
    assert stored["metadata"]["open_agronomy_agent"]["geometry"] == valid["geometry"]


def test_saved_boundary_above_imagery_vertex_budget_is_refused_without_rewriting(client):
    payload = _payload(510)
    created = _saved(client, payload)
    field_id = created["field_context_id"]
    _assert_complete_geometry(created, payload)
    response = client.post(f"/api/demo/fields/{field_id}/imagery/analyze", headers=OWNER, json={
        "provider_id": "hls-s30-planetary-computer", "start_date": "2022-06-01",
        "end_date": "2022-06-15",
    })
    assert response.status_code == 422, response.text
    stored = client.app.state.trace_store.get_phase4_field_context(field_id)
    assert stored["metadata"]["open_agronomy_agent"]["geometry"] == payload["geometry"]
