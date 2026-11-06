import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from agronomy_agent.geospatial import source_integrity as integrity


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def qualified_layer(tmp_path: Path):
    source = {"id": "synthetic_soil_source", "runtime": {"layer_id": "synthetic_soil"}}
    registry = tmp_path / "registry.json"
    profiles = tmp_path / "profiles.json"
    database = tmp_path / "soil.sqlite3"
    manifest = tmp_path / "soil_manifest.json"
    _write_json(registry, {"sources": [source]})
    _write_json(profiles, {"profiles": [{"sources": [{"source_id": source["id"], "expected_raw_sha256": "a" * 64}]}]})
    entry_sha = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    metadata = {
        "schema_version": integrity.LAYER_SCHEMA_VERSION,
        "source_id": source["id"],
        "source_sha256": "a" * 64,
        "source_entry_sha256": entry_sha,
        "output_crs": "EPSG:4326",
        "feature_count": 1,
    }
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY, value_json TEXT); CREATE TABLE features(fid INTEGER PRIMARY KEY); CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, min_lon,max_lon,min_lat,max_lat);")
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", [(k, json.dumps(v)) for k, v in metadata.items()])
        connection.execute("INSERT INTO features VALUES (1)")
        connection.execute("INSERT INTO feature_bounds VALUES (1,-105,-104,50,51)")
    descriptor = {**metadata, "output_sha256": _sha(database), "output_bytes": database.stat().st_size}
    _write_json(manifest, descriptor)
    def inspect():
        return integrity.local_layer_integrity(database, layer_id="synthetic_soil", registry_path=registry, profile_manifest_path=profiles)
    return database, manifest, registry, profiles, descriptor, inspect


def test_verified_receipt_is_read_only_and_cached_by_content_identity(qualified_layer, monkeypatch):
    database, manifest, registry, profiles, _, inspect = qualified_layer
    before = {p: (_sha(p), p.stat().st_mtime_ns) for p in (database, manifest, registry, profiles)}
    first = inspect()
    assert first["status"] == "verified"
    assert first["observed"]["sqlite_quick_check"] == ["ok"]
    assert first["observed"]["feature_count"] == 1
    monkeypatch.setattr(integrity, "_sha256", lambda _: pytest.fail("unchanged identity should reuse verification"))
    second = inspect()
    assert second == first
    second["observed"]["feature_count"] = 0
    assert inspect()["observed"]["feature_count"] == 1
    assert {p: (_sha(p), p.stat().st_mtime_ns) for p in before} == before


def test_database_missing_is_distinct_from_missing_receipt(qualified_layer):
    database, manifest, _, _, _, inspect = qualified_layer
    manifest.unlink()
    assert inspect()["status"] == "integrity_failed"
    assert inspect()["errors"] == ["identity_receipt_missing"]
    database.unlink()
    assert inspect()["status"] == "missing"
    assert inspect()["errors"] == ["database_missing"]


@pytest.mark.parametrize("field,value,error", [
    ("output_sha256", "0" * 64, "database_sha256_mismatch"),
    ("output_bytes", True, "database_byte_count_mismatch"),
    ("source_id", "another_source", "derivation_source_identity_mismatch"),
    ("source_entry_sha256", "0" * 64, "derivation_source_entry_mismatch"),
    ("source_sha256", "0" * 64, "derivation_raw_source_identity_mismatch"),
    ("output_crs", "EPSG:32100", "derivation_crs_mismatch"),
    ("feature_count", 0, "derivation_feature_count_invalid"),
    ("schema_version", "unknown", "derivation_schema_mismatch"),
])
def test_manifest_claims_do_not_override_identity(qualified_layer, field, value, error):
    _, manifest, _, _, descriptor, inspect = qualified_layer
    descriptor[field] = value
    _write_json(manifest, descriptor)
    result = inspect()
    assert result["status"] == "integrity_failed"
    assert error in result["errors"]


def test_self_consistent_metadata_must_match_current_registry(qualified_layer):
    _, _, registry, _, _, inspect = qualified_layer
    source = json.loads(registry.read_text())["sources"][0]
    source["publisher"] = "changed registered source"
    _write_json(registry, {"sources": [source]})
    result = inspect()
    assert result["status"] == "integrity_failed"
    assert "derivation_source_entry_mismatch" in result["errors"]
    assert "database_source_entry_mismatch" in result["errors"]


def test_same_size_database_mutation_with_restored_mtime_invalidates_cache(qualified_layer):
    database, _, _, _, _, inspect = qualified_layer
    first = inspect()
    original_stat = database.stat()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE metadata SET value_json = ? WHERE key='output_crs'", (json.dumps("EPSG:9999"),))
    assert database.stat().st_size == original_stat.st_size
    os.utime(database, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    result = inspect()
    assert result["status"] == "integrity_failed"
    assert result["fingerprint"] != first["fingerprint"]
    assert "database_sha256_mismatch" in result["errors"]
    assert "database_metadata_output_crs_mismatch" in result["errors"]


def test_manifest_mutation_with_restored_mtime_invalidates_cache(qualified_layer):
    _, manifest, _, _, descriptor, inspect = qualified_layer
    assert inspect()["status"] == "verified"
    original = manifest.stat()
    descriptor["source_entry_sha256"] = "0" * 64
    _write_json(manifest, descriptor)
    assert manifest.stat().st_size == original.st_size
    os.utime(manifest, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert "derivation_source_entry_mismatch" in inspect()["errors"]


def test_even_a_rehashed_database_must_match_metadata_and_rtree_contract(qualified_layer):
    database, manifest, _, _, descriptor, inspect = qualified_layer
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM feature_bounds")
        connection.execute("UPDATE metadata SET value_json=? WHERE key='source_id'", (json.dumps("another_source"),))
    descriptor["output_sha256"] = _sha(database)
    _write_json(manifest, descriptor)
    result = inspect()
    assert result["status"] == "integrity_failed"
    assert "database_feature_count_mismatch" in result["errors"]
    assert "database_metadata_source_id_mismatch" in result["errors"]


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sqlite_sidecar_cannot_bypass_base_file_identity_after_cache_hit(qualified_layer, suffix):
    database, _, _, _, _, inspect = qualified_layer
    assert inspect()["status"] == "verified"
    Path(str(database) + suffix).write_bytes(b"unchecked transaction")
    assert "database_sidecar_present" in inspect()["errors"]


def test_legacy_receipt_requires_exact_current_registry_hash(qualified_layer):
    database, manifest, registry, _, descriptor, inspect = qualified_layer
    registry_sha = _sha(registry)
    descriptor.pop("source_entry_sha256")
    descriptor["source_registry_sha256"] = registry_sha
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM metadata WHERE key='source_entry_sha256'")
        connection.execute("INSERT INTO metadata VALUES ('source_registry_sha256', ?)", (json.dumps(registry_sha),))
    descriptor["output_sha256"] = _sha(database)
    _write_json(manifest, descriptor)
    assert inspect()["status"] == "verified"
    registry.write_text(registry.read_text() + "\n")
    assert "derivation_legacy_registry_mismatch" in inspect()["errors"]


@pytest.mark.parametrize("raw", ["[]", '{"output_bytes": NaN}', '{"output_bytes":'])
def test_malformed_receipts_fail_closed(qualified_layer, raw):
    _, manifest, _, _, _, inspect = qualified_layer
    manifest.write_text(raw)
    result = inspect()
    assert result["status"] == "integrity_failed"
    assert any(error.startswith("identity_unreadable:") for error in result["errors"])


def test_file_changed_during_hash_is_not_admitted_or_cached(qualified_layer, monkeypatch):
    database, manifest, _, _, _, inspect = qualified_layer
    original = integrity._sha256
    def hash_then_mutate(path):
        value = original(path)
        if path == database:
            manifest.write_text(manifest.read_text() + "\n")
        return value
    monkeypatch.setattr(integrity, "_sha256", hash_then_mutate)
    result = inspect()
    assert result["status"] == "integrity_failed"
    assert "source_changed_during_verification" in result["errors"]
    monkeypatch.setattr(integrity, "_sha256", original)
    assert inspect()["status"] == "verified"
