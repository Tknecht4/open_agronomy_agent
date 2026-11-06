"""Local map projections bind the source identity actually read, including cache reuse."""
import hashlib
import json
import os
import shutil
import sqlite3

import pytest

from agronomy_agent.geospatial.source_integrity import LAYER_SCHEMA_VERSION, local_layer_integrity
from agronomy_agent.server.services import geospatial_service as geo

POINT = {"type": "Point", "coordinates": [-93.5, 42.5]}


@pytest.fixture
def qualified_source(tmp_path, monkeypatch):
    database = tmp_path / "synthetic.sqlite3"
    source = {"id": "synthetic_source", "runtime": {"layer_id": "synthetic"}}
    metadata = {"schema_version": LAYER_SCHEMA_VERSION, "source_id": source["id"],
        "source_sha256": "a" * 64,
        "source_entry_sha256": hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "output_crs": "EPSG:4326", "feature_count": 1}
    polygon = {"type": "Polygon", "coordinates": [[[-94,42],[-93,42],[-93,43],[-94,43],[-94,42]]]}
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value_json TEXT); CREATE TABLE features(fid INTEGER,code TEXT,name TEXT,properties_json TEXT,geometry_json TEXT); CREATE VIRTUAL TABLE feature_bounds USING rtree(fid,min_lon,max_lon,min_lat,max_lat);")
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v)) for k,v in metadata.items()])
        connection.execute("INSERT INTO features VALUES (1,'synthetic','Admitted source','{}',?)", (json.dumps(polygon),))
        connection.execute("INSERT INTO feature_bounds VALUES (1,-94,-93,42,43)")
    manifest = database.with_name("synthetic_manifest.json")
    manifest.write_text(json.dumps({**metadata, "output_bytes": database.stat().st_size,
        "output_sha256": hashlib.sha256(database.read_bytes()).hexdigest()}))
    registry = tmp_path / "registry.json"; registry.write_text(json.dumps({"sources": [source]}))
    profiles = tmp_path / "profiles.json"; profiles.write_text(json.dumps({"profiles": [{"sources": [{"source_id": source["id"], "expected_raw_sha256": "a" * 64}]}]}))
    def inspect(database, *, layer_id):
        return local_layer_integrity(database, layer_id=layer_id, registry_path=registry, profile_manifest_path=profiles)
    monkeypatch.setattr(geo, "local_layer_integrity", inspect)
    layer = geo.RegionLayer(id="synthetic", label="synthetic", system="synthetic", source_url="https://example.invalid/source", service_url="https://example.invalid/service", color="#000000", code_fields=("code",), name_fields=("name",), query_backend="local_sqlite", local_database=str(database), country_code="US")
    monkeypatch.setattr(geo, "REGION_LAYERS", {layer.id: layer})
    geo._clear_offline_intersection_cache()
    assert inspect(database, layer_id=layer.id)["status"] == "verified"
    return database, manifest, layer, inspect


def mutate(database, *, replacement=False, restored_mtime=False):
    target = database.with_name("replacement.sqlite3") if replacement else database
    stamp = database.stat()
    if replacement:
        shutil.copyfile(database, target)
    with sqlite3.connect(target) as connection:
        connection.execute("UPDATE features SET name='Unadmitted replacement'")
    if restored_mtime:
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    if replacement:
        os.replace(target, database)


def request(*, viewport=False):
    if viewport:
        return geo.query_region_layers(bbox=(-94, 42, -93, 43), layer_ids=["synthetic"], network_mode="offline", country_scope="United States")
    return geo.intersect_region_layers(geometry=POINT, layer_ids=["synthetic"], network_mode="offline", country_scope="United States")


def assert_refused(result):
    assert result["feature_count"] == 0
    assert result["feature_collection"]["features"] == []
    assert result.get("intersections", []) == []
    assert result["source_integrity"]["synthetic"]["status"] == "integrity_failed"
    assert result["source_qualified_layer_ids"] == []
    status = geo.official_layer_status(result)[0]
    assert status["status"] == "integrity_failed"
    assert status["match_count"] is None
    assert status["observed_match_count"] == 0


@pytest.mark.parametrize("replacement,restored_mtime", [(False, False), (False, True), (True, True)])
@pytest.mark.parametrize("viewport", [False, True])
def test_changed_source_after_gate_cannot_publish_rows(qualified_source, monkeypatch, replacement, restored_mtime, viewport):
    database, _, _, _ = qualified_source
    original = geo._local_query_geometry
    changed = False
    def mutate_after_identity(**kwargs):
        nonlocal changed
        if not changed:
            mutate(database, replacement=replacement, restored_mtime=restored_mtime)
            changed = True
        return original(**kwargs)
    monkeypatch.setattr(geo, "_local_query_geometry", mutate_after_identity)
    assert_refused(request(viewport=viewport))


@pytest.mark.parametrize("target", ["database", "manifest"])
def test_source_change_during_cache_lookup_refuses_stale_verified_projection(qualified_source, monkeypatch, target):
    database, manifest, _, _ = qualified_source
    first = request()
    assert first["feature_count"] == 1 and first["source_query_cache_hit"] is False
    original = geo._offline_intersection_cache_get
    def lookup_then_mutate(key):
        cached = original(key)
        assert cached is not None
        if target == "database":
            mutate(database, replacement=True, restored_mtime=True)
        else:
            manifest.write_text(manifest.read_text() + "\n")
        return cached
    monkeypatch.setattr(geo, "_offline_intersection_cache_get", lookup_then_mutate)
    second = request()
    assert_refused(second)
    assert second["query_attempted_layer_ids"] == []
    assert second["source_query_cache_hit"] is False
    assert second["source_query_cache_rejected"] is True


def test_unchanged_cache_reuse_keeps_verified_observations_without_new_queries(qualified_source, monkeypatch):
    first = request()
    monkeypatch.setattr(geo, "_query_layer", lambda *a, **kw: pytest.fail("unchanged source should reuse exact cached rows"))
    second = request()
    assert second["intersections"] == first["intersections"]
    assert second["source_integrity"] == first["source_integrity"]
    assert second["source_query_cache_hit"] is True
    assert second["query_attempted_layer_ids"] == []
    assert geo.official_layer_status(second)[0]["status"] == "matched"


@pytest.mark.parametrize("viewport", [False, True])
def test_source_change_after_rows_read_cannot_publish_under_earlier_receipt(qualified_source, monkeypatch, viewport):
    database, _, _, _ = qualified_source
    original = geo._normalize_feature_collection
    def normalize_then_mutate(collection, layer):
        result = original(collection, layer)
        mutate(database)
        return result
    monkeypatch.setattr(geo, "_normalize_feature_collection", normalize_then_mutate)
    assert_refused(request(viewport=viewport))


def test_transient_mutation_restored_before_postcheck_still_changes_read_identity(qualified_source, monkeypatch):
    database, _, layer, inspect = qualified_source
    admitted = database.read_bytes()
    original_geometry = geo._local_query_geometry
    original_connect = sqlite3.connect
    pending = False
    class RestoreOnClose:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def __setattr__(self, name, value):
            if name == "connection": object.__setattr__(self, name, value)
            else: setattr(self.connection, name, value)
        def close(self):
            self.connection.close()
            database.write_bytes(admitted)
    def mutate_after_identity(**kwargs):
        nonlocal pending
        mutate(database)
        pending = True
        return original_geometry(**kwargs)
    def connect_then_restore(*args, **kwargs):
        nonlocal pending
        connection = original_connect(*args, **kwargs)
        if pending and "immutable=1" in str(args[0]):
            pending = False
            return RestoreOnClose(connection)
        return connection
    monkeypatch.setattr(geo, "_local_query_geometry", mutate_after_identity)
    monkeypatch.setattr(sqlite3, "connect", connect_then_restore)
    result = request()
    assert inspect(database, layer_id=layer.id)["status"] == "verified"
    assert_refused(result)


def test_map_analysis_source_change_keeps_unknown_coverage_and_explicit_integrity_failure(qualified_source, monkeypatch):
    from agronomy_agent.server.services.field_map_analysis import analyze_field_map
    database, _, _, _ = qualified_source
    original = geo._normalize_feature_collection
    def normalize_then_mutate(collection, layer):
        result = original(collection, layer)
        mutate(database)
        return result
    monkeypatch.setattr(geo, "_normalize_feature_collection", normalize_then_mutate)
    result = analyze_field_map(geometry=POINT, layer_ids=["synthetic"], network_mode="offline")
    item = result["layers"][0]
    assert item["status"] == "integrity_failed"
    assert item["source_integrity"]["status"] == "integrity_failed"
    assert item["coverage_fraction"] is None and item["covered_area_ha"] is None
    assert item["zones"] == [] and item["feature_count"] is None
