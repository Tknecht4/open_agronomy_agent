import json
import sqlite3
from pathlib import Path

from agronomy_agent.server.services import geospatial_service as geo


def _write_local_layer(path: Path) -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-104.8, 50.4], [-104.7, 50.4], [-104.7, 50.5], [-104.8, 50.5], [-104.8, 50.4]]],
    }
    properties = {
        "soil_summary": "Synthetic Saskatchewan soil context",
        "source_scale": "1:100,000",
        "dominant_components": [{"soil_name": "REGINA", "proportion_percent": 70}],
    }
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE TABLE features (
              fid INTEGER PRIMARY KEY,
              code TEXT NOT NULL,
              name TEXT NOT NULL,
              properties_json TEXT NOT NULL,
              geometry_json TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, min_lon, max_lon, min_lat, max_lat);
            """
        )
        connection.execute(
            "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
            ("source_scale_range", json.dumps("1:100,000")),
        )
        connection.execute(
            "INSERT INTO features VALUES (?, ?, ?, ?, ?)",
            (1, "SK_SOIL_TEST", "Synthetic Saskatchewan soil context", json.dumps(properties), json.dumps(geometry)),
        )
        connection.execute(
            "INSERT INTO feature_bounds VALUES (?, ?, ?, ?, ?)",
            (1, -104.8, -104.7, 50.4, 50.5),
        )
        connection.commit()
    finally:
        connection.close()


def test_spatial_pack_root_and_per_layer_override_precedence(tmp_path: Path, monkeypatch) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    monkeypatch.setenv("AGRONOMY_AGENT_SPATIAL_PACK_ROOT", str(pack))
    monkeypatch.delenv("AGRONOMY_AGENT_SK_DETAILED_SOIL_DB_PATH", raising=False)

    assert geo._local_database_path(
        environment_variable="AGRONOMY_AGENT_SK_DETAILED_SOIL_DB_PATH",
        filename="sk_detailed_soil.sqlite3",
    ) == str(pack / "sk_detailed_soil.sqlite3")

    explicit = tmp_path / "explicit.sqlite3"
    monkeypatch.setenv("AGRONOMY_AGENT_SK_DETAILED_SOIL_DB_PATH", str(explicit))
    assert geo._local_database_path(
        environment_variable="AGRONOMY_AGENT_SK_DETAILED_SOIL_DB_PATH",
        filename="sk_detailed_soil.sqlite3",
    ) == str(explicit)


def test_local_soil_layer_intersects_offline_and_preserves_components(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "sk_detailed_soil.sqlite3"
    _write_local_layer(database)
    layer = geo.RegionLayer(
        id="synthetic_sk_soil",
        label="Synthetic Saskatchewan Soil",
        system="test",
        service_url="",
        source_url="https://example.invalid/source",
        color="#637d68",
        code_fields=("code",),
        name_fields=("soil_summary",),
        query_backend="local_sqlite",
        local_database=str(database),
        local_match_reason="Synthetic local intersection",
    )
    monkeypatch.setitem(geo.REGION_LAYERS, layer.id, layer)

    result = geo.intersect_region_layers(
        geometry={
            "type": "Polygon",
            "coordinates": [[[-104.76, 50.44], [-104.74, 50.44], [-104.74, 50.46], [-104.76, 50.46], [-104.76, 50.44]]],
        },
        layer_ids=[layer.id],
        network_mode="offline",
    )

    assert result["errors"] == []
    assert result["feature_count"] == 1
    assert result["intersections"][0]["source_scale"] == "1:100,000"
    assert result["intersections"][0]["dominant_components"][0]["soil_name"] == "REGINA"
    assert result["network_policy"]["external_requests_attempted"] == 0


def test_default_layer_selection_omits_uninstalled_and_prefers_detailed_sk(
    tmp_path: Path, monkeypatch
) -> None:
    installed = tmp_path / "installed.sqlite3"
    installed.touch()
    layers = {
        "sk_detailed_soil": geo.RegionLayer(
            id="sk_detailed_soil",
            label="detailed",
            system="test",
            service_url="",
            source_url="",
            color="#000000",
            code_fields=("code",),
            name_fields=("name",),
            query_backend="local_sqlite",
            local_database=str(installed),
        ),
        "sk_thematic_soil": geo.RegionLayer(
            id="sk_thematic_soil",
            label="thematic",
            system="test",
            service_url="",
            source_url="",
            color="#000000",
            code_fields=("code",),
            name_fields=("name",),
            query_backend="local_sqlite",
            local_database=str(installed),
        ),
        "missing": geo.RegionLayer(
            id="missing",
            label="missing",
            system="test",
            service_url="",
            source_url="",
            color="#000000",
            code_fields=("code",),
            name_fields=("name",),
            query_backend="local_sqlite",
            local_database=str(tmp_path / "missing.sqlite3"),
        ),
    }
    monkeypatch.setattr(geo, "REGION_LAYERS", layers)

    assert [layer.id for layer in geo._selected_layers(None)] == ["sk_detailed_soil"]
    catalog = {row["id"]: row for row in geo.layer_catalog(network_mode="offline")["layers"]}
    assert catalog["sk_detailed_soil"]["installation_status"] == "installed"
    assert catalog["missing"]["available_in_current_mode"] is False
