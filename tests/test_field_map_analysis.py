"""Synthetic mapped polygons exercise area and incomplete-source semantics."""

from __future__ import annotations

import builtins
import asyncio
import json
import math
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agronomy_agent.server import map_analysis_routes
from agronomy_agent.server.services import field_map_analysis as analysis
from agronomy_agent.server.services import geospatial_service as geo


pytest.importorskip("shapely")
pytest.importorskip("pyproj")


def polygon(west: float, south: float, east: float, north: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [west, south], [east, south], [east, north], [west, north], [west, south],
    ]]}


FIELD = polygon(0, 0, 0.02, 0.02)


def _layer(monkeypatch, *, backend: str = "local_sqlite") -> geo.RegionLayer:
    layer = geo.RegionLayer(
        id="synthetic_zone", label="Synthetic mapped zones", system="fixture",
        service_url="https://example.invalid/service", source_url="https://example.invalid/source",
        color="#123456", code_fields=("code",), name_fields=("name",),
        query_backend=backend, local_database="/fixture/exists.sqlite3",
        boundary="Mapped context only.",
    )
    monkeypatch.setitem(geo.REGION_LAYERS, layer.id, layer)
    monkeypatch.setattr(geo, "_local_layer_installed", lambda candidate: candidate.id == layer.id)
    monkeypatch.setattr(geo, "_local_layer_readiness", lambda candidate: {
        "status": "verified" if candidate.id == layer.id else "missing",
        "errors": [] if candidate.id == layer.id else ["database_missing"],
    })
    return layer


def _feature(code: str, geometry: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": {"code": code, "name": code}}


def _source(monkeypatch, features: list[dict]) -> None:
    @contextmanager
    def fake_query(layer, envelopes, *, readiness):
        assert layer.id == "synthetic_zone"
        assert envelopes and all(len(bbox) == 4 for bbox in envelopes)
        assert readiness["status"] == "verified"
        yield iter(features)

    monkeypatch.setattr(geo, "local_coverage_features", fake_query)


def test_geodesic_union_prevents_overlapping_zones_from_double_counting(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    _source(monkeypatch, [
        _feature("whole", FIELD),
        _feature("half", polygon(0, 0, 0.01, 0.02)),
    ])
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="offline")
    field = result["geometry"]
    mapped = result["layers"][0]
    assert result["status"] == "complete"
    assert field["area_ha"] > 0 and field["area_ac"] == pytest.approx(field["area_ha"] * analysis.ACRES_PER_HECTARE, abs=2e-6)
    assert field["perimeter_m"] > 0
    assert mapped["coverage_fraction"] == pytest.approx(1, abs=1e-6)
    assert mapped["covered_area_ha"] == pytest.approx(field["area_ha"], abs=1e-5)
    assert sum(zone["area_ha"] for zone in mapped["zones"]) > mapped["covered_area_ha"]
    assert mapped["source_url"] == "https://example.invalid/source"
    assert result["network_policy"]["external_requests_attempted"] == 0
    assert "coverage_estimate" not in str(result)


def test_holes_multipart_and_reversed_winding_are_measured(monkeypatch) -> None:
    outer = [[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]
    hole = [[0.005, 0.005], [0.015, 0.005], [0.015, 0.015], [0.005, 0.015], [0.005, 0.005]]
    field = {"type": "MultiPolygon", "coordinates": [
        [list(reversed(outer)), list(reversed(hole))],
        polygon(0.03, 0, 0.035, 0.005)["coordinates"],
    ]}
    result = analysis.analyze_field_map(geometry=field, layer_ids=[], network_mode="offline")
    full = analysis.analyze_field_map(geometry=FIELD, layer_ids=[], network_mode="offline")
    assert result["status"] == "complete"
    assert result["layers"] == []
    assert result["geometry"]["area_ha"] < full["geometry"]["area_ha"]
    assert result["geometry"]["perimeter_m"] > full["geometry"]["perimeter_m"]
    assert result["geometry"]["location"] is not None


@pytest.mark.parametrize("bad", [
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], [[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]},
    {"type": "MultiPolygon", "coordinates": []},
    polygon(179, 0, -179, 1),
])
def test_invalid_or_unsupported_geometry_fails_closed(bad) -> None:
    with pytest.raises(ValueError):
        analysis.analyze_field_map(geometry=bad, layer_ids=[], network_mode="offline")


def test_explicit_layer_selection_and_input_cap(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    with pytest.raises(ValueError, match="explicit"):
        analysis.analyze_field_map(geometry=FIELD, layer_ids=None, network_mode="offline")
    with pytest.raises(ValueError, match="duplicates"):
        analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id, layer.id], network_mode="offline")
    with pytest.raises(ValueError, match="0 to 4"):
        analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id] * 5, network_mode="offline")
    large_ring = [[i / 100000, 0] for i in range(10_001)]
    with pytest.raises(ValueError, match="10000"):
        analysis.analyze_field_map(
            geometry={"type": "Polygon", "coordinates": [large_ring]}, layer_ids=[], network_mode="offline"
        )


@pytest.mark.parametrize("coordinates", [[None, 0], [{}, 0], ["0", "0"], [True, False]])
def test_non_numeric_point_is_422(coordinates) -> None:
    app = FastAPI()
    map_analysis_routes.register_map_analysis_routes(app, SimpleNamespace(network_mode="offline"))
    response = TestClient(app).post(
        "/api/geo/field-analysis",
        json={"geometry": {"type": "Point", "coordinates": coordinates}, "layers": []},
    )
    assert response.status_code == 422


def test_string_positions_cannot_bypass_vertex_cap() -> None:
    ring = [[str(i / 100_000), "0"] for i in range(1025)]
    with pytest.raises(ValueError, match="finite JSON numbers"):
        analysis.analyze_field_map(
            geometry={"type": "Polygon", "coordinates": [ring]}, layer_ids=[], network_mode="offline"
        )


def test_real_local_adapter_finds_second_component_and_east_edge(tmp_path, monkeypatch, qualified_spatial_layer) -> None:
    db = tmp_path / "review-local-fixture.sqlite3"
    zone = polygon(0.042, 0.002, 0.043, 0.003)
    with sqlite3.connect(db) as connection:
        connection.executescript(
            "CREATE TABLE metadata(key TEXT, value_json TEXT);"
            "CREATE TABLE features(fid INTEGER, code TEXT, name TEXT, properties_json TEXT, geometry_json TEXT);"
            "CREATE TABLE feature_bounds(fid INTEGER, min_lon REAL, max_lon REAL, min_lat REAL, max_lat REAL);"
        )
        connection.execute(
            "INSERT INTO features VALUES(1, ?, ?, ?, ?)",
            ("second", "Second component", "{}", json.dumps(zone)),
        )
        connection.execute("INSERT INTO feature_bounds VALUES(1, .042, .043, .002, .003)")
    layer = geo.RegionLayer(
        id="real_local_fixture", label="Real local fixture", system="fixture",
        service_url="", source_url="https://example.invalid/source", color="#123456",
        code_fields=("code",), name_fields=("name",), query_backend="local_sqlite",
        local_database=str(db),
    )
    monkeypatch.setitem(geo.REGION_LAYERS, layer.id, layer)
    qualified_spatial_layer(db, layer.id)
    multi = {"type": "MultiPolygon", "coordinates": [
        FIELD["coordinates"], polygon(0.04, 0, 0.06, 0.02)["coordinates"],
    ]}
    area = analysis.analyze_field_map(geometry=multi, layer_ids=[layer.id], network_mode="offline")
    assert area["layers"][0]["status"] == "complete"
    assert area["layers"][0]["covered_area_ha"] > 0
    assert 0 < area["layers"][0]["coverage_fraction"] < 1
    assert area["layers"][0]["zones"][0]["code"] == "second"
    boundary = analysis.analyze_field_map(
        geometry={"type": "Point", "coordinates": [0.043, 0.0025]},
        layer_ids=[layer.id], network_mode="offline",
    )
    assert boundary["layers"][0]["status"] == "complete"
    assert [zone["code"] for zone in boundary["layers"][0]["zones"]] == ["second"]
    holed = {"type": "Polygon", "coordinates": [
        polygon(0.04, 0, 0.06, 0.02)["coordinates"][0],
        polygon(0.041, 0.001, 0.044, 0.004)["coordinates"][0],
    ]}
    gap = analysis.analyze_field_map(geometry=holed, layer_ids=[layer.id], network_mode="offline")
    assert gap["layers"][0]["status"] == "complete"
    assert gap["layers"][0]["coverage_fraction"] == 0
    same_zone = {"type": "MultiPolygon", "coordinates": [
        polygon(.0421, .0021, .0422, .0022)["coordinates"],
        polygon(.0424, .0024, .0425, .0025)["coordinates"],
    ]}
    once = analysis.analyze_field_map(geometry=same_zone, layer_ids=[layer.id], network_mode="offline")
    assert once["layers"][0]["coverage_fraction"] == 1
    assert once["layers"][0]["feature_count"] == once["layers"][0]["processed_feature_count"] == 1
    wide = {"type": "MultiPolygon", "coordinates": [
        multi["coordinates"][1], polygon(14, 0, 14.01, .01)["coordinates"],
    ]}
    prior = geo.intersect_region_layers(geometry=wide, layer_ids=[layer.id], network_mode="offline")
    assert prior["errors"] == []
    assert [item["code"] for item in prior["intersections"]] == ["second"]


@pytest.mark.parametrize("raw,expected_status,expected_reason", [
    ({"type": "FeatureCollection", "features": [_feature("whole", FIELD)], "exceededTransferLimit": True}, "partial", "source_transfer_limit_reached"),
    ({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": {}}]}, "partial", "malformed_source_feature"),
    ({"unexpected": "payload"}, "unavailable", "malformed_source_collection"),
    ({"type": "FeatureCollection", "features": [_feature("whole", FIELD)]}, "complete", None),
])
def test_existing_remote_adapter_retains_raw_completeness(
    monkeypatch, raw, expected_status, expected_reason
) -> None:
    layer = _layer(monkeypatch, backend="arcgis_feature_service")

    def fake_source(candidate, *, geometry, geometry_type):
        assert candidate.id == layer.id
        assert geometry_type == "esriGeometryPolygon"  # existing guarded request shape
        return raw

    monkeypatch.setattr(geo, "_query_layer", fake_source)
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="online")
    mapped = result["layers"][0]
    assert mapped["status"] == expected_status
    assert mapped["reason"] == expected_reason
    if expected_status == "complete":
        assert mapped["coverage_fraction"] == pytest.approx(1)
    else:
        assert mapped["coverage_fraction"] is None


def test_remote_complete_multipart_query_preserves_all_rings(monkeypatch) -> None:
    layer = _layer(monkeypatch, backend="arcgis_feature_service")
    def source(*args, **kwargs):
        payload = json.loads(kwargs["geometry"])
        assert len(payload["rings"]) == 2
        from shapely.geometry import LinearRing
        assert all(not LinearRing(ring).is_ccw for ring in payload["rings"])
        return {"type": "FeatureCollection", "features": []}
    monkeypatch.setattr(geo, "_query_layer", source)
    multi = {"type": "MultiPolygon", "coordinates": [
        FIELD["coordinates"], polygon(0.04, 0, 0.06, 0.02)["coordinates"],
    ]}
    result = analysis.analyze_field_map(geometry=multi, layer_ids=[layer.id], network_mode="online")
    mapped = result["layers"][0]
    assert mapped["status"] == "complete"
    assert mapped["reason"] is None
    assert mapped["coverage_fraction"] == 0


def test_remote_feature_cap_never_reports_complete_coverage(monkeypatch) -> None:
    layer = _layer(monkeypatch, backend="arcgis_feature_service")
    monkeypatch.setattr(geo, "_query_layer", lambda *args, **kwargs: {
        "type": "FeatureCollection",
        "features": [_feature(str(i), FIELD) for i in range(geo.MAX_FEATURES_PER_LAYER)],
    })
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="online")
    mapped = result["layers"][0]
    assert result["status"] == "partial"
    assert mapped["status"] == "partial"
    assert mapped["reason"] == "source_feature_limit_reached"
    assert mapped["covered_area_ha"] is None
    assert mapped["coverage_fraction"] is None
    assert all(zone["area_ha"] is None for zone in mapped["zones"])
    assert mapped["omitted_zone_count"] == geo.MAX_FEATURES_PER_LAYER - analysis.MAX_ZONES_SHOWN


def test_remote_vertex_limit_still_withholds_coverage(monkeypatch) -> None:
    layer = _layer(monkeypatch, backend="arcgis_feature_service")
    monkeypatch.setattr(analysis, "MAX_REMOTE_SOURCE_VERTICES", 9)
    monkeypatch.setattr(geo, "_query_layer", lambda *args, **kwargs: {
        "type": "FeatureCollection",
        "features": [_feature("first", FIELD), _feature("second", FIELD)],
    })
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="online")
    layer_result = result["layers"][0]
    assert layer_result["status"] == "partial"
    assert layer_result["reason"] == "source_vertex_limit_reached"
    assert layer_result["coverage_fraction"] is None
    assert layer_result["zones"] == []


@pytest.mark.parametrize("compressed", [False, True])
def test_local_analysis_streams_past_candidate_feature_and_vertex_cutoffs(
    tmp_path, monkeypatch, qualified_spatial_layer, compressed,
) -> None:
    from shapely import segmentize
    from shapely.geometry import mapping, shape

    # The original viewport cap would have stopped inside these 641 envelope
    # false positives. The whole field lies in their polygon holes.
    hole = {"type": "Polygon", "coordinates": [
        polygon(-.02, -.02, .04, .04)["coordinates"][0],
        polygon(-.01, -.01, .03, .03)["coordinates"][0],
    ]}
    left = polygon(-.01, -.01, .01, .03)
    right = mapping(segmentize(shape(polygon(.01, -.01, .03, .03)), .000004))
    assert len(right["coordinates"][0]) > 20_000
    rows = [(f"miss-{index}", hole) for index in range(641)]
    rows += [(f"left-{index}", left) for index in range(82)]
    rows.append(("right", right))
    db = tmp_path / "coverage.sqlite3"
    encoding = "zlib" if compressed else "json"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            "CREATE TABLE metadata(key TEXT, value_json TEXT);"
            f"CREATE TABLE features(fid INTEGER PRIMARY KEY, code TEXT, name TEXT, properties_{encoding}, geometry_{encoding});"
            "CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, min_lon, max_lon, min_lat, max_lat);"
        )
        for fid, (code, geometry) in enumerate(rows, 1):
            w, s, e, n = shape(geometry).bounds
            properties, payload = "{}", json.dumps(geometry)
            if compressed:
                properties, payload = zlib.compress(properties.encode()), zlib.compress(payload.encode())
            connection.execute("INSERT INTO features VALUES(?, ?, ?, ?, ?)", (fid, code, code, properties, payload))
            connection.execute("INSERT INTO feature_bounds VALUES(?, ?, ?, ?, ?)", (fid, w, e, s, n))
    layer = geo.RegionLayer(
        id="coverage_fixture", label="Soils", system="fixture", service_url="",
        source_url="https://example.invalid/source", color="#123456", code_fields=("code",),
        name_fields=("name",), query_backend="local_sqlite", local_database=str(db),
    )
    monkeypatch.setitem(geo.REGION_LAYERS, layer.id, layer)
    qualified_spatial_layer(db, layer.id)

    positions = 4_000
    ring = [[.01 + .008 * math.cos(2 * math.pi * i / positions),
             .01 + .008 * math.sin(2 * math.pi * i / positions)] for i in range(positions)]
    field = {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}
    assert len(json.dumps(field, separators=(",", ":"))) > 128 * 1024
    app = FastAPI()
    map_analysis_routes.register_map_analysis_routes(app, SimpleNamespace(network_mode="offline"))
    response = TestClient(app).post("/api/geo/field-analysis", json={"geometry": field, "layers": [layer.id]})
    assert response.status_code == 200
    result = response.json()
    mapped = result["layers"][0]
    assert result["status"] == mapped["status"] == "complete"
    assert mapped["feature_count"] == 724
    assert mapped["processed_feature_count"] == 83
    assert mapped["coverage_fraction"] == 1
    assert mapped["covered_area_ha"] == result["geometry"]["area_ha"]
    assert mapped["omitted_zone_count"] == 83 - analysis.MAX_ZONES_SHOWN


def test_wide_multipart_local_coverage_is_independent_of_remote_extent(monkeypatch) -> None:
    local = _layer(monkeypatch)
    remote = geo.REGION_LAYERS["nrcs_mlra"]
    distant = polygon(14, 0, 14.02, .02)
    field = {"type": "MultiPolygon", "coordinates": [FIELD["coordinates"], distant["coordinates"]]}
    _source(monkeypatch, [_feature("first", FIELD), _feature("distant", distant)])
    monkeypatch.setattr(geo, "_query_layer", lambda *args, **kwargs: pytest.fail("remote extent is unsupported"))
    result = analysis.analyze_field_map(geometry=field, layer_ids=[local.id, remote.id], network_mode="online")
    assert result["geometry"]["status"] == "complete"
    assert result["layers"][0]["coverage_fraction"] == 1
    assert result["layers"][1]["reason"] == "remote_geometry_span_unsupported"
    prior = geo.intersect_region_layers(geometry=field, layer_ids=[remote.id], network_mode="online")
    assert prior["query"]["bbox"] == [0, 0, 14.02, .02]
    assert prior["query_attempted_layer_ids"] == prior["source_qualified_layer_ids"] == []
    assert prior["skipped_layers"][0]["reason"] == "remote_geometry_span_unsupported"


def test_area_is_additive_when_clipping_inserts_vertices(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    field = polygon(-120, 50, -104, 51)
    west = polygon(-120, 50, -112, 51)
    east = polygon(-112, 50, -104, 51)
    _source(monkeypatch, [_feature("west", west), _feature("east", east)])
    result = analysis.analyze_field_map(geometry=field, layer_ids=[layer.id], network_mode="offline")
    mapped = result["layers"][0]
    assert mapped["status"] == "complete"
    assert mapped["coverage_fraction"] == 1
    assert mapped["covered_area_ha"] == result["geometry"]["area_ha"]
    assert [zone["fraction_of_field"] for zone in mapped["zones"]] == [0.5, 0.5]


def test_point_matches_zones_without_inventing_area(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    _source(monkeypatch, [_feature("zone", FIELD)])
    result = analysis.analyze_field_map(
        geometry={"type": "Point", "coordinates": [0.01, 0.01]},
        layer_ids=[layer.id], network_mode="offline",
    )
    assert result["geometry"]["location"] == {"longitude": 0.01, "latitude": 0.01}
    assert result["geometry"]["area_ha"] is None
    assert result["geometry"]["perimeter_m"] is None
    assert result["layers"][0]["zones"][0]["name"] == "zone"
    assert result["layers"][0]["coverage_fraction"] is None


def test_point_requires_actual_polygon_coverage_and_includes_boundary(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    _source(monkeypatch, [
        _feature("distant", polygon(0.03, 0.03, 0.04, 0.04)),
        _feature("boundary", FIELD),
    ])
    result = analysis.analyze_field_map(
        geometry={"type": "Point", "coordinates": [0.02, 0.01]},
        layer_ids=[layer.id], network_mode="offline",
    )
    assert result["layers"][0]["status"] == "complete"
    assert [zone["code"] for zone in result["layers"][0]["zones"]] == ["boundary"]


def test_invalid_returned_point_source_is_partial_not_a_match(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    invalid = {"type": "Polygon", "coordinates": [[
        [0, 0], [0.02, 0.02], [0, 0.02], [0.02, 0], [0, 0],
    ]]}
    _source(monkeypatch, [_feature("invalid", invalid)])
    result = analysis.analyze_field_map(
        geometry={"type": "Point", "coordinates": [0.01, 0.01]},
        layer_ids=[layer.id], network_mode="offline",
    )
    assert result["status"] == "partial"
    assert result["layers"][0]["reason"] == "invalid_source_geometry"
    assert result["layers"][0]["zones"] == []
    assert result["layers"][0]["coverage_fraction"] is None


def test_complete_empty_source_is_a_measured_zero_overlap(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    _source(monkeypatch, [])
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="offline")
    assert result["layers"][0]["status"] == "complete"
    assert result["layers"][0]["covered_area_ha"] == 0
    assert result["layers"][0]["coverage_fraction"] == 0


def test_offline_remote_and_missing_local_report_unavailable_without_query(monkeypatch) -> None:
    remote = _layer(monkeypatch, backend="arcgis_feature_service")
    monkeypatch.setattr(geo, "intersect_region_layers", lambda **kwargs: pytest.fail("unexpected source query"))
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[remote.id], network_mode="offline")
    assert result["layers"][0]["status"] == "blocked_offline"
    assert result["layers"][0]["coverage_fraction"] is None
    monkeypatch.setattr(geo, "_local_layer_installed", lambda candidate: False)
    local = geo.RegionLayer(
        id="missing_synthetic", label="Missing", system="fixture", service_url="",
        source_url="https://example.invalid/source", color="#123456",
        code_fields=("code",), name_fields=("name",), query_backend="local_sqlite",
        local_database="/missing.sqlite3",
    )
    monkeypatch.setitem(geo.REGION_LAYERS, local.id, local)
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[local.id], network_mode="offline")
    assert result["layers"][0]["status"] == "not_installed"


def test_source_error_and_missing_spatial_dependencies_preserve_unknown(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    monkeypatch.setattr(geo, "local_coverage_features", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    result = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="offline")
    assert result["geometry"]["status"] == "complete"
    assert result["layers"][0]["status"] == "unavailable"
    assert result["layers"][0]["covered_area_ha"] is None
    original_import = builtins.__import__

    def missing_import(name, *args, **kwargs):
        if name == "pyproj":
            raise ImportError("fixture")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_import)
    absent = analysis.analyze_field_map(geometry=FIELD, layer_ids=[layer.id], network_mode="offline")
    assert absent["status"] == "unavailable"
    assert absent["geometry"]["area_ha"] is None
    assert absent["layers"][0]["reason"] == "spatial_dependencies_missing"


def test_route_validation_is_422() -> None:
    app = FastAPI()
    map_analysis_routes.register_map_analysis_routes(app, SimpleNamespace(network_mode="offline"))
    client = TestClient(app)
    assert client.post("/api/geo/field-analysis", json={"geometry": FIELD, "layers": []}).json()["status"] == "complete"
    assert client.post("/api/geo/field-analysis", json={"geometry": FIELD}).status_code == 422
    assert client.post("/api/geo/field-analysis", json={"geometry": FIELD, "layers": [], "extra": "ignored?"}).status_code == 422


def test_local_route_queues_large_work_without_blocking_geometry_requests(monkeypatch) -> None:
    layer = _layer(monkeypatch)
    app = FastAPI()
    map_analysis_routes.register_map_analysis_routes(app, SimpleNamespace(network_mode="offline"))
    first_started, second_started, release_first = (threading.Event() for _ in range(3))

    def analyze(**payload):
        if payload["layer_ids"]:
            if not first_started.is_set():
                first_started.set()
                assert release_first.wait(5)
            else:
                second_started.set()
        return {"status": "complete"}

    monkeypatch.setattr(map_analysis_routes, "analyze_field_map", analyze)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            path = "/api/geo/field-analysis"
            field_request = {"geometry": FIELD, "layers": [layer.id]}
            first = asyncio.create_task(client.post(path, json=field_request))
            second = None
            try:
                assert await asyncio.to_thread(first_started.wait, 5)
                second = asyncio.create_task(client.post(path, json=field_request))
                measure = await asyncio.wait_for(client.post(path, json={"geometry": FIELD, "layers": []}), 3)
                assert measure.status_code == 200
                assert not second_started.is_set()
            finally:
                release_first.set()
                await first
                if second is not None:
                    await second
            assert first.result().status_code == second.result().status_code == 200
            assert second_started.is_set()

    asyncio.run(exercise())
