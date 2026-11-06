from __future__ import annotations

import sys
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def loopback_test_client_default():
    """Exercise the real loopback guard; explicit hostile/LAN origins stay explicit."""
    original = TestClient.__init__
    def initialize(self, app, *args, **kwargs):
        if not args and "base_url" not in kwargs:
            kwargs["base_url"] = "http://127.0.0.1:8000"
        original(self, app, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TestClient, "__init__", initialize)
        yield


@pytest.fixture
def qualified_spatial_layer(monkeypatch):
    """Bind synthetic spatial databases through the production identity gate."""
    from agronomy_agent.geospatial.source_integrity import LAYER_SCHEMA_VERSION, local_layer_integrity
    from agronomy_agent.server.services import geospatial_service as geo
    bound_paths = {}

    def inspect(database, *, layer_id, **kwargs):
        paths = bound_paths.get((str(Path(database).resolve()), layer_id))
        if paths is not None:
            kwargs.update(registry_path=paths[0], profile_manifest_path=paths[1])
        return local_layer_integrity(database, layer_id=layer_id, **kwargs)

    monkeypatch.setattr(geo, "local_layer_integrity", inspect)

    def qualify(database: Path, layer_id: str) -> None:
        source = {"id": f"synthetic:{layer_id}", "runtime": {"layer_id": layer_id}}
        entry_sha = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        with sqlite3.connect(database) as connection:
            count = connection.execute("SELECT COUNT(*) FROM features").fetchone()[0]
            metadata = {"schema_version": LAYER_SCHEMA_VERSION, "source_id": source["id"],
                        "source_sha256": "a" * 64, "source_entry_sha256": entry_sha,
                        "output_crs": "EPSG:4326", "feature_count": count}
            connection.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)",
                                   [(key, json.dumps(value)) for key, value in metadata.items()])
        manifest = database.with_name(f"{database.stem}_manifest.json")
        manifest.write_text(json.dumps({**metadata, "output_bytes": database.stat().st_size,
            "output_sha256": hashlib.sha256(database.read_bytes()).hexdigest()}))
        registry = database.with_name(f"{database.stem}_registry.json")
        profiles = database.with_name(f"{database.stem}_profiles.json")
        registry.write_text(json.dumps({"sources": [source]}))
        profiles.write_text(json.dumps({"profiles": [{"sources": [{"source_id": source["id"],
            "expected_raw_sha256": "a" * 64}]}]}))
        bound_paths[(str(database.resolve()), layer_id)] = (registry, profiles)

    return qualify
