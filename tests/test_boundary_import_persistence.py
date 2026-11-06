"""HTTP save/update/reload retains bounded import identity without source authority."""
from copy import deepcopy
import hashlib
import importlib
import json

from fastapi.testclient import TestClient
import pytest

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


OWNER = {"X-Agronomy-User-Email": "import-lineage@example.test"}


def payload():
    return {
        "name": "Historic source field", "field": {"crop": "", "jurisdiction": "Alberta"},
        "geometry": {"kind": "point", "point": {"lat": 49.0, "lon": -111.0}},
        "boundaryImport": {
            "import_receipt": {"schema_version": "open_agronomy_agent.vector_import.v1", "source_sha256": "a" * 64, "source_bytes": 1234},
            "coordinate_reference": {"target_crs": "EPSG:4326", "label": "WGS84 longitude/latitude", "reprojected": False,
                "sources": [{"layer": "geojson", "source_crs": "EPSG:4326", "crs_basis": "RFC7946", "target_crs": "EPSG:4326", "reprojected": False}]},
            "selected_feature": {"id": "geojson:0", "source_layer": "geojson", "source_feature_index": 0, "source_feature_id": 955,
                "properties": {"year_list": [1980, 2022], "Crop22": "Barley", "crop": None, "irrigated": None}},
        },
    }


@pytest.fixture
def settings(tmp_path, monkeypatch):
    module = importlib.import_module("agronomy_agent.server.app")
    monkeypatch.setattr(module, "intersect_region_layers", lambda **_: {"intersections": [], "feature_collection": {"features": []}, "errors": [], "queried_layers": []})
    return build_settings(db_path=tmp_path / "workspace.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")


def create(client, body):
    result = client.post("/api/demo/fields", headers=OWNER, json=body)
    assert result.status_code == 201, result.text
    return result.json()["field"]


def test_client_import_snapshot_survives_save_reload_and_metadata_edit(settings):
    original = payload()
    with TestClient(create_app(settings)) as client:
        field = create(client, original)
        lineage = field["boundaryImport"]
        assert lineage["import_receipt"] == original["boundaryImport"]["import_receipt"]
        assert lineage["selected_feature"]["properties"] == original["boundaryImport"]["selected_feature"]["properties"]
        assert lineage["coordinate_reference"] == original["boundaryImport"]["coordinate_reference"]
        assert lineage["selected_feature"]["source_feature_id"] == 955
        assert lineage["binding_status"] == "client_snapshot_context_only"
        assert lineage["source_attested"] is False and lineage["authority"] == "context_only"
        assert lineage["not_training_data"] is True and lineage["not_field_measurement"] is True
        assert field["crop"] == ""
        body = deepcopy(original)
        del body["boundaryImport"]
        body["name"] = "Renamed historic source field"
        updated = client.patch(f"/api/demo/fields/{field['id']}", headers=OWNER, json=body)
        assert updated.status_code == 200, updated.text
        assert updated.json()["field"]["boundaryImport"] == lineage
        assert updated.json()["field"]["fieldRevision"]["snapshot_sha256"] == field["fieldRevision"]["snapshot_sha256"]
        record = client.app.state.trace_store.get_phase4_field_context(field["id"])
        assert record["metadata"]["open_agronomy_agent"]["boundary_import"] == lineage
        assert record["crop_current"] is None
    with TestClient(create_app(settings)) as reloaded:
        saved = reloaded.get("/api/demo/fields", headers=OWNER).json()["fields"][0]
        assert saved["boundaryImport"] == lineage
        assert saved["crop"] == ""


def test_geometry_edit_supersedes_and_explicit_clear_removes_source_snapshot(settings):
    with TestClient(create_app(settings)) as client:
        original = payload()
        field = create(client, original)
        body = deepcopy(original)
        del body["boundaryImport"]
        body["geometry"]["point"]["lon"] = -112.0
        updated = client.patch(f"/api/demo/fields/{field['id']}", headers=OWNER, json=body)
        assert updated.status_code == 200, updated.text
        changed = updated.json()["field"]["boundaryImport"]
        assert changed["binding_status"] == "superseded_geometry_edit"
        assert changed["validity"] == "superseded"
        assert changed["geometry_sha256"] == field["boundaryImport"]["geometry_sha256"]
        assert changed["current_geometry_sha256"] != changed["geometry_sha256"]
        assert changed["selected_feature"] == field["boundaryImport"]["selected_feature"]
        assert updated.json()["field"]["fieldRevision"]["snapshot_sha256"] != field["fieldRevision"]["snapshot_sha256"]
        body["boundaryImport"] = None
        cleared = client.patch(f"/api/demo/fields/{field['id']}", headers=OWNER, json=body)
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["field"]["boundaryImport"] is None


def test_actual_upload_selected_feature_receipt_reaches_saved_field(settings):
    raw = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "source-first", "geometry": {"type": "Point", "coordinates": [-111.0, 49.0]}, "properties": {"Crop22": "Barley", "year_list": [2021, 2022]}},
        {"type": "Feature", "id": "source-second", "geometry": {"type": "Point", "coordinates": [-112.0, 48.0]}, "properties": {"Crop22": "Wheat", "crop": None, "year_list": [1980, 2022], "irrigation": None}},
    ]}).encode()
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/geo/boundary-upload", files={"file": ("historical-fields.geojson", raw, "application/geo+json")})
        assert response.status_code == 200, response.text
        uploaded = response.json()
        selected = uploaded["feature_collection"]["features"][1]
        props = selected["properties"]
        body = payload()
        lon, lat = selected["geometry"]["coordinates"]
        body["geometry"] = {"kind": "point", "point": {"lat": lat, "lon": lon}}
        body["boundaryImport"] = {
            "import_receipt": uploaded["import_receipt"], "coordinate_reference": uploaded["coordinate_reference"],
            "selected_feature": {"id": selected["id"], "source_layer": props["upload_source_layer"],
                "source_feature_index": props["upload_source_feature_index"], "source_feature_id": props["upload_source_feature_id"], "properties": props},
        }
        field = create(client, body)
        lineage = field["boundaryImport"]
        assert lineage["import_receipt"]["source_sha256"] == hashlib.sha256(raw).hexdigest()
        assert lineage["import_receipt"]["source_bytes"] == len(raw)
        assert lineage["coordinate_reference"] == uploaded["coordinate_reference"]
        assert lineage["selected_feature"]["source_feature_id"] == "source-second"
        assert lineage["selected_feature"]["source_feature_index"] == 1
        assert lineage["selected_feature"]["id"] == "geojson:1"
        assert lineage["selected_feature"]["properties"] == props
        assert lineage["selected_feature"]["properties"]["year_list"] == [1980, 2022]
        assert lineage["selected_feature"]["properties"]["crop"] is None
        assert field["crop"] == ""
        assert field["geometry"] == body["geometry"]


@pytest.mark.parametrize("bad", [None, True, "invalid", 0, 25 * 1024 * 1024 + 1])
def test_invalid_receipt_refuses_entire_field_create(settings, bad):
    with TestClient(create_app(settings)) as client:
        body = payload()
        body["boundaryImport"]["import_receipt"]["source_bytes"] = bad
        response = client.post("/api/demo/fields", headers=OWNER, json=body)
        assert response.status_code == 422, response.text
        assert client.get("/api/demo/fields", headers=OWNER).json()["fields"] == []


def test_invalid_import_update_preserves_original_field_and_lineage(settings):
    with TestClient(create_app(settings)) as client:
        original = payload()
        field = create(client, original)
        body = deepcopy(original)
        body["name"] = "Invalid replacement"
        body["geometry"]["point"]["lon"] = -112.0
        body["boundaryImport"]["import_receipt"]["source_sha256"] = "not-a-digest"
        response = client.patch(f"/api/demo/fields/{field['id']}", headers=OWNER, json=body)
        assert response.status_code == 422, response.text
        saved = client.get("/api/demo/fields", headers=OWNER).json()["fields"][0]
        assert saved["name"] == field["name"]
        assert saved["geometry"] == field["geometry"]
        assert saved["boundaryImport"] == field["boundaryImport"]
        assert saved["fieldRevision"] == field["fieldRevision"]
