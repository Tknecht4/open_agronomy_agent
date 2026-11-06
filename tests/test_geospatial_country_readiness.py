"""Automatic mapped context respects source jurisdiction and unknown coverage."""
from __future__ import annotations

import json
import importlib
import os
import sqlite3

import pytest

from agronomy_agent.server.services import geospatial_service as geo
from agronomy_agent.server.services.field_map_analysis import analyze_field_map

POINT = {"type": "Point", "coordinates": [-93.5, 42.1]}


def _layer(layer_id, *, country="CA", backend="local_sqlite", database="/missing.sqlite3"):
    return geo.RegionLayer(id=layer_id, label=layer_id, system="synthetic source",
        source_url="https://example.invalid/source", service_url="https://example.invalid/service",
        color="#000000", code_fields=("code",), name_fields=("name",),
        country_code=country, query_backend=backend, local_database=str(database))


@pytest.fixture
def scoped_sources(monkeypatch):
    layers = {"ca": _layer("ca"), "us": _layer("us", country="US")}
    monkeypatch.setattr(geo, "REGION_LAYERS", layers)
    monkeypatch.setattr(geo, "_local_layer_readiness", lambda layer: {"status": "verified", "errors": [], "fingerprint": layer.id})
    calls = []
    def query(layer, **kwargs):
        calls.append(layer.id)
        return {"type": "FeatureCollection", "features": [], "exceededTransferLimit": False}
    monkeypatch.setattr(geo, "_query_layer", query)
    geo._clear_offline_intersection_cache()
    return calls


@pytest.mark.parametrize("country,attempted,skipped", [
    ("Canada", ["ca"], "us"), ("United States", ["us"], "ca"),
])
def test_country_scoped_query_cannot_report_foreign_layer_as_empty_coverage(scoped_sources, country, attempted, skipped):
    result = geo.intersect_region_layers(geometry=POINT, layer_ids=["ca", "us"], network_mode="offline", country_scope=country)
    assert scoped_sources == attempted
    assert result["query_attempted_layer_ids"] == attempted
    status = {item["layer_id"]: item for item in geo.official_layer_status(result)}
    assert status[attempted[0]]["status"] == "no_match"
    assert status[attempted[0]]["match_count"] == 0
    assert status[skipped]["status"] == "inapplicable_country"
    assert status[skipped]["match_count"] is None


@pytest.mark.parametrize("country", ["unknown", "", "Mexico"])
def test_unknown_or_unsupported_country_does_not_query_any_source(scoped_sources, country):
    result = geo.intersect_region_layers(geometry=POINT, layer_ids=["ca", "us"], network_mode="offline", country_scope=country)
    assert scoped_sources == []
    assert result["query_attempted_layer_ids"] == []
    assert all(item["status"] == "jurisdiction_unknown" and item["match_count"] is None for item in geo.official_layer_status(result))


def test_manual_gis_scope_is_explicit_and_cache_hits_do_not_claim_new_queries(scoped_sources):
    first = geo.intersect_region_layers(geometry=POINT, layer_ids=["ca", "us"], network_mode="offline")
    second = geo.intersect_region_layers(geometry=POINT, layer_ids=["ca", "us"], network_mode="offline")
    assert scoped_sources == ["ca", "us"]
    assert first["query_attempted_layer_ids"] == ["ca", "us"]
    assert second["query_attempted_layer_ids"] == []
    assert second["source_qualified_layer_ids"] == ["ca", "us"]
    assert second["source_query_cache_hit"] is True


def test_country_skips_and_unknown_skips_have_distinct_cache_identity(scoped_sources):
    for country, expected in [("United States", "inapplicable_country"), ("unknown", "jurisdiction_unknown")]:
        result = geo.intersect_region_layers(geometry=POINT, layer_ids=["ca"], network_mode="offline", country_scope=country)
        assert geo.official_layer_status(result)[0]["status"] == expected
    assert scoped_sources == []


@pytest.mark.parametrize("readiness,expected", [("missing", "not_installed"), ("integrity_failed", "integrity_failed")])
def test_source_unreadiness_retains_unknown_and_prevents_query(monkeypatch, readiness, expected):
    layer = _layer("ca")
    monkeypatch.setattr(geo, "REGION_LAYERS", {layer.id: layer})
    monkeypatch.setattr(geo, "_local_layer_readiness", lambda layer: {"status": readiness, "errors": ["synthetic_failure"]})
    monkeypatch.setattr(geo, "_query_layer", lambda *a, **k: pytest.fail("unready source was queried"))
    result = geo.intersect_region_layers(geometry=POINT, layer_ids=[layer.id], network_mode="offline", country_scope="Canada")
    status = geo.official_layer_status(result)[0]
    assert status["status"] == expected and status["match_count"] is None
    assert result["query_attempted_layer_ids"] == []
    catalog = geo.layer_catalog(network_mode="offline")["layers"][0]
    assert catalog["installation_status"] == expected
    assert catalog["available_in_current_mode"] is False
    analysis = analyze_field_map(geometry=POINT, layer_ids=[layer.id], network_mode="offline")
    assert analysis["layers"][0]["status"] == expected
    assert analysis["layers"][0]["coverage_fraction"] is None


def test_offline_remote_source_and_query_failure_do_not_report_zero(scoped_sources, monkeypatch):
    remote = _layer("remote", country="US", backend="arcgis_feature_service")
    monkeypatch.setitem(geo.REGION_LAYERS, remote.id, remote)
    blocked = geo.intersect_region_layers(geometry=POINT, layer_ids=[remote.id], network_mode="offline", country_scope="United States")
    assert geo.official_layer_status(blocked)[0]["match_count"] is None
    monkeypatch.setattr(geo, "_query_layer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic source unavailable")))
    failed = geo.intersect_region_layers(geometry=POINT, layer_ids=["us"], country_scope="United States")
    status = geo.official_layer_status(failed)[0]
    assert status["status"] == "error" and status["match_count"] is None


def test_incomplete_collection_does_not_become_verified_empty_coverage(scoped_sources, monkeypatch):
    monkeypatch.setattr(geo, "_query_layer", lambda *a, **k: {"type": "FeatureCollection", "features": [], "exceededTransferLimit": True})
    result = geo.intersect_region_layers(geometry=POINT, layer_ids=["us"], country_scope="United States")
    status = geo.official_layer_status(result)[0]
    assert status["status"] == "partial" and status["match_count"] is None
    assert status["observed_match_count"] == 0


def test_same_size_database_mutation_with_restored_mtime_blocks_cached_intersections(tmp_path, monkeypatch, qualified_spatial_layer):
    database = tmp_path / "layer.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY, value_json TEXT); CREATE TABLE features(fid INTEGER,code TEXT,name TEXT,properties_json TEXT,geometry_json TEXT); CREATE TABLE feature_bounds(fid INTEGER,min_lon REAL,max_lon REAL,min_lat REAL,max_lat REAL);")
        connection.execute("INSERT INTO features VALUES (1,'synthetic','Synthetic source','{}',?)", (json.dumps(POINT),))
        connection.execute("INSERT INTO feature_bounds VALUES (1,-93.5,-93.5,42.1,42.1)")
    layer = _layer("synthetic", country="US", database=database)
    monkeypatch.setattr(geo, "REGION_LAYERS", {layer.id: layer})
    qualified_spatial_layer(database, layer.id)
    geo._clear_offline_intersection_cache()
    first = geo.intersect_region_layers(geometry=POINT, layer_ids=[layer.id], network_mode="offline", country_scope="United States")
    assert first["feature_count"] == 1 and first["source_query_cache_hit"] is False
    stamp = database.stat()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE features SET name='Corrupted source'")
    assert database.stat().st_size == stamp.st_size
    os.utime(database, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    second = geo.intersect_region_layers(geometry=POINT, layer_ids=[layer.id], network_mode="offline", country_scope="United States")
    assert second["feature_count"] == 0
    assert second["query_attempted_layer_ids"] == []
    assert second["source_query_cache_hit"] is False
    assert geo.official_layer_status(second)[0]["status"] == "integrity_failed"
    with pytest.raises(ValueError, match="integrity_failed"):
        geo._query_local_sqlite_layer(layer, geometry="-93.6,42.0,-93.4,42.2", geometry_type="esriGeometryEnvelope")


@pytest.mark.parametrize("jurisdiction,status,attempted", [
    ("Iowa", "inapplicable_country", []), ("Atlantis", "jurisdiction_unknown", []),
    ("Alberta", "no_match", ["synthetic_ca"]),
])
def test_saved_field_country_and_import_snapshot_survive_api_reload_without_crop_promotion(tmp_path, monkeypatch, jurisdiction, status, attempted):
    from fastapi.testclient import TestClient
    from agronomy_agent.server.settings import build_settings
    app_module = importlib.import_module("agronomy_agent.server.app")
    layer = _layer("synthetic_ca")
    layers = {layer.id: layer}
    monkeypatch.setattr(geo, "REGION_LAYERS", layers)
    monkeypatch.setattr(app_module, "REGION_LAYERS", layers)
    monkeypatch.setattr(geo, "_local_layer_readiness", lambda layer: {"status": "verified", "errors": []})
    calls = []
    def query(layer, **kwargs):
        calls.append(layer.id)
        return {"type": "FeatureCollection", "features": [], "exceededTransferLimit": False}
    monkeypatch.setattr(geo, "_query_layer", query)
    geo._clear_offline_intersection_cache()
    raw = json.dumps({"type": "Feature", "id": "native-field-17", "geometry": POINT,
        "properties": {"year_list": [2021, 2022], "Crop22": "Barley", "crop": None}}).encode()
    parsed = geo.parse_boundary_upload(filename="field.geojson", content_type=None, raw=raw)
    selected = parsed["feature_collection"]["features"][0]
    original_properties = selected["properties"]
    snapshot = {"import_receipt": parsed["import_receipt"], "coordinate_reference": parsed["coordinate_reference"],
        "selected_feature": {"id": selected["id"], "source_layer": "geojson", "source_feature_index": 0,
            "source_feature_id": "native-field-17", "properties": original_properties}}
    headers = {"X-Agronomy-User-Email": "synthetic-ingestion@example.test"}
    client = TestClient(app_module.create_app(build_settings(db_path=tmp_path / "state.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")))
    created = client.post("/api/demo/fields", headers=headers, json={"name": "Synthetic imported field",
        "field": {"jurisdiction": jurisdiction}, "geometry": {"kind": "point", "point": {"lon": -93.5, "lat": 42.1}},
        "boundaryImport": snapshot})
    assert created.status_code == 201, created.text
    saved = created.json()["field"]
    assert calls == attempted
    source_status = saved["geoPriors"]["official_layer_status"][0]
    assert source_status["status"] == status
    assert source_status["match_count"] == (0 if attempted else None)
    assert saved["geoContextLineage"]["server_recomputed_layer_ids"] == attempted
    assert saved["crop"] == ""
    assert saved["boundaryImport"]["selected_feature"]["properties"] == original_properties
    assert saved["boundaryImport"]["source_attested"] is False
    listed = client.get("/api/demo/fields", headers=headers)
    assert listed.status_code == 200
    reloaded = listed.json()["fields"][0]
    assert reloaded["boundaryImport"] == saved["boundaryImport"]
    assert reloaded["geoContextLineage"] == saved["geoContextLineage"]
