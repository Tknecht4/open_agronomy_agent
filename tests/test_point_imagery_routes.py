"""Point HTTP/cache scope contracts; numerical pixels have separate COG tests."""
from __future__ import annotations

import copy
import json
import math
import sys
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.imagery_analytics import _request_identity, POINT_PROCESS_VERSION, PREVIEW_VERSION
from agronomy_agent.imagery_receipts import validate_point_receipt
from agronomy_agent.imagery_store import ImageryStore
from agronomy_agent.server.app import create_app
from agronomy_agent.server.services import imagery_service as service
from agronomy_agent.server.settings import build_settings

OWNER = {"X-Agronomy-User-Email": "point-owner@example.test"}
OUTSIDER = {"X-Agronomy-User-Email": "point-outsider@example.test"}
POINT = {"kind": "point", "point": {"lat": 40.15, "lon": -103.15}}
INPUT = {"type": "Point", "coordinates": [-103.15, 40.15]}
BODY = {"provider_id": "hls-s30-planetary-computer", "start_date": "2021-06-01", "end_date": "2021-06-15"}


@pytest.fixture
def runtime(tmp_path):
    settings = build_settings(db_path=tmp_path / "db.sqlite3", artifact_root=tmp_path / "artifacts",
        imagery_cache_root=tmp_path / "cache", imagery_worker_python=sys.executable, network_mode="online")
    app = create_app(settings)
    with TestClient(app) as client:
        made = client.post("/api/demo/fields", headers=OWNER, json={"name": "Research point", "field": {}, "geometry": POINT})
        assert made.status_code == 201, made.text
        yield client, made.json()["field"]["field_context_id"], settings


def receipt(geometry=INPUT, payload=None):
    geometry = copy.deepcopy(geometry)
    payload = payload or BODY
    mode = payload.get("sampling_mode") or "point_pixel"
    radius = payload.get("sample_radius_m")
    _, _, geometry_hash, request_hash = _request_identity(geometry, payload["provider_id"], payload.get("scene_id"),
        payload["start_date"], payload["end_date"], 0, None, sampling_mode=mode, sample_radius_m=radius)
    lon, lat = geometry["coordinates"]
    footprint = {"type": "Polygon", "coordinates": [[[lon-.001,lat-.001],[lon+.001,lat-.001],
        [lon+.001,lat+.001],[lon-.001,lat+.001],[lon-.001,lat-.001]]]}
    chip = request_hash
    area = 900 if mode == "point_pixel" else math.pi * radius**2
    count = 1 if mode == "point_pixel" else math.ceil(area / 900)
    side = 1 if mode == "point_pixel" else math.ceil(math.sqrt(count))
    return {"status": "available", "evidence_role": "observation", "provider_id": payload["provider_id"],
        "scene_id": "hls2-s30:fixture", "source": {"collection": "hls2-s30", "scene_id": "hls2-s30:fixture", "asset_ids": {}},
        "source_native_grid": True, "process_version": POINT_PROCESS_VERSION, "preview_version": PREVIEW_VERSION,
        "process_hash": "b"*64, "chip_hash": chip, "geometry_hash": geometry_hash, "request_hash": request_hash,
        "request": {"provider_id": payload["provider_id"], "scene_id": payload.get("scene_id"),
            "start_date": payload["start_date"], "end_date": payload["end_date"], "buffer_m": 0,
            "context_pixels": None, "sampling_mode": mode, "sample_radius_m": radius},
        "sampling": {"schema_version": "imagery_sampling.v1", "mode": mode,
            "support_kind": "native_pixel" if mode == "point_pixel" else "point_buffer", "original_geometry": geometry,
            "footprint": footprint, "footprint_crs": "EPSG:4326", "sample_radius_m": radius, "native_resolution_m": 30,
            "pixel_count": count, "valid_pixel_count": count, "positional_uncertainty_m": None, "point_role": "unspecified",
            "area_basis": "native_grid_projected_metres", "edge_policy": "containing_pixel_floor", "limitation": "Synthetic sample only; not a field boundary."},
        "qa": {"sample_area_m2": area, "valid_area_m2": area, "valid_area_fraction": 1.,
            "excluded_area_m2_by_reason": {}, "nodata_area_m2": 0, "overlap_note": "May overlap"},
        "grid": {"width": side, "height": side, "resolution_m": 30},
        "zonal_stats": {name: {"mean": .5, "min": .5, "max": .5, "area_m2": area}
                        for name in ("NDVI", "NDMI")}, "model_refs": [],
        "cache_files": {"npz": chip+".npz", "png": chip+".png", "receipt": chip+".json"}, "created_at": "2026-09-27"}


def worker(settings, cache, geometry, payload):
    result = receipt(geometry, payload)
    store = ImageryStore(cache)
    for kind, data in (("npz", b"synthetic cache envelope"), ("png", b"synthetic PNG"), ("receipt", json.dumps(result).encode())):
        (cache / result["cache_files"][kind]).write_bytes(data)
    store.put(result, validate_point_receipt(result))
    return result


def test_point_sampling_http_cache_authority_and_saved_geometry(runtime, monkeypatch):
    client, field_id, settings = runtime
    monkeypatch.setattr(service, "_run_worker", worker)
    path = f"/api/demo/fields/{field_id}"
    availability = client.get(path+"/imagery/analytics", headers=OWNER).json()
    assert availability["sampling_modes"] == ["field_polygon", "point_pixel", "point_buffer"]
    assert availability["sample_radius_bounds_m"] == {"min": 15, "max": 1500}
    result = client.post(path+"/imagery/analyze", headers=OWNER, json=BODY)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result["sampling"]["original_geometry"] == INPUT
    assert result["sampling"]["mode"] == "point_pixel"
    assert result["request"] == {"provider_id": BODY["provider_id"], "scene_id": None,
        "start_date": BODY["start_date"], "end_date": BODY["end_date"], "buffer_m": 0,
        "context_pixels": None, "sampling_mode": "point_pixel", "sample_radius_m": None}
    request = result["request"]
    assert _request_identity(result["sampling"]["original_geometry"], request["provider_id"],
        request["scene_id"], request["start_date"], request["end_date"], request["buffer_m"],
        request["context_pixels"], sampling_mode=request["sampling_mode"],
        sample_radius_m=request["sample_radius_m"])[3] == result["request_hash"]
    assert "field_area_m2" not in result["qa"]
    assert client.get(result["preview_url"], headers=OWNER).status_code == 200
    assert client.get(result["preview_url"], headers=OUTSIDER).status_code == 403
    assert client.post(path+"/imagery/analyze", headers=OUTSIDER, json=BODY).status_code == 403
    fields = client.get("/api/demo/fields", headers=OWNER).json()["fields"]
    assert next(f for f in fields if f["field_context_id"] == field_id)["geometry"] == POINT
    monkeypatch.setattr(service, "_run_worker", lambda *args: pytest.fail("verified cache invoked worker"))
    cached = client.post(path+"/imagery/analyze", headers=OWNER, json={**BODY,"sampling_mode":"point_pixel"})
    assert cached.json()["cache_hit"] is True
    assert service.analyze(replace(settings, network_mode="offline"), {"workspace_id":"other", "id":field_id}, INPUT, BODY)["status"] == "blocked_offline"
    changed = client.patch(path, headers=OWNER, json={"name":"Moved point", "field":{}, "geometry":{
        "kind":"point", "point":{"lat":40.15,"lon":-103.151}}})
    assert changed.status_code == 200
    assert client.get(result["preview_url"], headers=OWNER).status_code == 404


@pytest.mark.parametrize("extra", [
    {"sampling_mode":"field_polygon"}, {"sampling_mode":"point_buffer"},
    {"sampling_mode":"point_pixel", "sample_radius_m":60},
    {"sampling_mode":"point_buffer", "sample_radius_m":True},
    {"sampling_mode":"point_buffer", "sample_radius_m":60.5},
    {"sampling_mode":"point_buffer", "sample_radius_m":1501},
    {"sampling_mode":"point_buffer", "sample_radius_m":14}, {"buffer_m":30},
    {"geometry": {"type":"Point","coordinates":[0,0]}},
])
def test_invalid_point_requests_never_reach_worker(runtime, monkeypatch, extra):
    client, field_id, _ = runtime
    monkeypatch.setattr(service, "_run_worker", lambda *args: pytest.fail("invalid request invoked worker"))
    response = client.post(f"/api/demo/fields/{field_id}/imagery/analyze", headers=OWNER, json=BODY|extra)
    assert response.status_code == 422, response.text


def test_point_to_polygon_change_during_analysis_holds_result(runtime, monkeypatch):
    client, field_id, _ = runtime
    path = f"/api/demo/fields/{field_id}"
    def changing_worker(*args):
        result = worker(*args)
        assert client.patch(path, headers=OWNER, json={"name":"Reviewed boundary","field":{},"geometry":{
            "kind":"polygon","points":[{"lat":40.15,"lon":-103.15},{"lat":40.15,"lon":-103.14},{"lat":40.16,"lon":-103.15}]}}).status_code == 200
        return result
    monkeypatch.setattr(service, "_run_worker", changing_worker)
    result = client.post(path+"/imagery/analyze", headers=OWNER, json=BODY)
    assert result.status_code == 409, result.text


@pytest.mark.parametrize("change", ["missing", "field_area", "radius", "request_radius", "geometry", "role", "pixel_count", "hash", "footprint", "grid_type", "index_unsupported", "index_area", "index_order", "nodata_negative"])
def test_point_receipt_meaning_rejects_corruption(change):
    result = receipt()
    if change == "missing": result.pop("sampling")
    elif change == "field_area": result["qa"]["field_area_m2"] = 900
    elif change == "radius": result["sampling"]["sample_radius_m"] = 60
    elif change == "request_radius": result["request"]["sample_radius_m"] = 60
    elif change == "geometry": result["sampling"]["original_geometry"]["coordinates"] = [0.,0.]
    elif change == "role": result["sampling"]["point_role"] = "field_interior"
    elif change == "pixel_count": result["sampling"]["valid_pixel_count"] = 2
    elif change == "hash": result["request_hash"] = "f"*64
    elif change == "footprint": result["sampling"]["footprint"]["coordinates"] = [[[0,0],[.001,0],[0,.001],[0,0]]]
    elif change == "grid_type": result["grid"] = [1]
    elif change == "index_unsupported": result["zonal_stats"]["NDVI"]["area_m2"] = 0
    elif change == "index_area": result["zonal_stats"]["NDVI"]["area_m2"] = 901
    elif change == "index_order": result["zonal_stats"]["NDVI"]["max"] = .1
    else: result["qa"]["nodata_area_m2"] = -1
    with pytest.raises((ValueError, TypeError)):
        validate_point_receipt(result)


def test_point_worker_arguments_keep_sampling_separate_from_polygon_buffer(tmp_path, monkeypatch):
    settings = build_settings(db_path=tmp_path/'db', artifact_root=tmp_path/'artifacts',
        imagery_cache_root=tmp_path/'cache', imagery_worker_python=sys.executable, network_mode="offline")
    def run(command, **kwargs):
        assert command[command.index('--sampling-mode')+1] == 'point_buffer'
        assert command[command.index('--sample-radius-m')+1] == '60'
        assert command[command.index('--buffer-m')+1] == '0'
        assert '--online' not in command
        kwargs['stdout'].write(b'{"status":"blocked_offline"}')
        return type('Completed', (), {'returncode':2})()
    monkeypatch.setattr(service.subprocess, 'run', run)
    assert service._run_worker(settings, tmp_path/'cache', INPUT,
        BODY|{"sampling_mode":"point_buffer","sample_radius_m":60})["status"] == "blocked_offline"


def test_buffer_radius_must_match_reported_area_and_valid_pixel_support():
    result = receipt(payload=BODY|{"sampling_mode":"point_buffer", "sample_radius_m":60})
    validate_point_receipt(result)
    wrong_area = copy.deepcopy(result)
    wrong_area["qa"].update(sample_area_m2=900, valid_area_m2=900)
    with pytest.raises(ValueError, match="circle radius"):
        validate_point_receipt(wrong_area)
    wrong_count = copy.deepcopy(result)
    wrong_count["sampling"]["valid_pixel_count"] = 1
    with pytest.raises(ValueError, match="valid pixel support"):
        validate_point_receipt(wrong_count)
