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
    from agronomy_agent.imagery_analytics import PREVIEW_VERSION, PROCESS_VERSION
    _, bounds, geom, request = _request_identity(geometry, payload["provider_id"], payload.get("scene_id"),
        payload["start_date"], payload["end_date"], payload.get("buffer_m", 0), None)
    store = ImageryStore(cache)
    chip = "a" * 64
    names = {"npz": chip + ".npz", "png": chip + ".png", "receipt": chip + ".json"}
    result = {"status": "available", "chip_hash": chip, "request_hash": request, "preview_version": PREVIEW_VERSION,
        "geometry_hash": geom, "process_hash": "b" * 64, "provider_id": payload["provider_id"],
        "source": {"collection": "hls2-s30", "scene_id": "hls2-s30:fixture", "asset_ids": {}},
        "scene_id": "hls2-s30:fixture", "process_version": PROCESS_VERSION, "source_native_grid": True,
        "grid": {"width": 2, "height": 2, "resolution_m": 30},
        "qa": {"field_area_m2": 3600, "valid_area_m2": 2700, "valid_area_fraction": .75,
            "nodata_area_m2": 0, "water_flag_area_m2": 0,
            "excluded_area_m2_by_reason": {"cloud": 900, "adjacent": 900}, "overlap_note": "May overlap",
            "index_undefined_area_m2_by_reason": {"ndvi_negative_reflectance": 0, "ndvi_nonpositive_denominator": 0,
                "ndmi_negative_reflectance": 0, "ndmi_nonpositive_denominator": 0}},
        "zonal_stats": {name: {"mean": .5, "min": .5, "max": .5, "area_m2": 2700} for name in ("NDVI", "NDMI")},
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
        assert command[1:3] == ["-m", "agronomy_agent.imagery_worker"]
        assert command[command.index("--max-cache-bytes") + 1] == str(settings.imagery_cache_max_bytes)
        assert command[command.index("--min-free-bytes") + 1] == str(settings.imagery_min_free_bytes)
        assert "--online" not in command
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in kwargs["env"]
        assert "HF_TOKEN" not in kwargs["env"]
        assert kwargs["timeout"] == 150
        kwargs["stdout"].write(b'{"status":"blocked_offline"}')
        return type("Completed", (), {"returncode": 2})()
    monkeypatch.setattr(service.subprocess, "run", run)
    assert service._run_worker(settings, tmp_path / "c", {}, PAYLOAD)["status"] == "blocked_offline"


def test_storage_policy_survives_app_settings_and_returns_typed_refusal(runtime, monkeypatch):
    client, field_id, settings = runtime
    monkeypatch.setattr(service, "_run_worker", lambda *a: {"status": "storage_limit", "reason": "free_disk_reserve_reached"})
    base = f"/api/demo/fields/{field_id}/imagery"
    availability = client.get(base + "/analytics", headers=OWNER).json()
    assert availability["storage_policy"]["max_cache_bytes"] == settings.imagery_cache_max_bytes
    assert availability["storage_policy"]["eviction"] == "none"
    result = client.post(base + "/analyze", headers=OWNER, json=PAYLOAD)
    assert result.json()["status"] == "storage_limit"
    assert "preview_url" not in result.json()


# Corrupt semantic claims, then deliberately reindex the bytes. Checksums alone
# must not authorize an observation or a direct preview URL.
@pytest.mark.parametrize("path,value", [
    (("qa", "valid_area_m2"), 5400),
    (("qa", "valid_area_fraction"), 1.5),
    (("qa", "field_area_m2"), 4000),
    (("qa", "sample_area_m2"), 3600),
    (("qa", "nodata_area_m2"), -1),
    (("qa", "nodata_area_m2"), 3600),
    (("qa", "excluded_area_m2_by_reason", "cloud"), 3600),
    (("qa", "excluded_area_m2_by_reason"), {}),
    (("qa", "valid_area_m2"), 10**400),
    (("qa", "water_flag_area_m2"), 4000),
    (("qa", "excluded_area_m2_by_reason", "cloud"), 4000),
    (("qa", "index_undefined_area_m2_by_reason", "ndvi_negative_reflectance"), 900),
    (("zonal_stats", "NDVI", "mean"), 1.2),
    (("zonal_stats", "NDVI", "min"), -1.2),
    (("zonal_stats", "NDMI", "max"), None),
    (("zonal_stats", "NDMI", "area_m2"), 3000),
    (("status",), "empty_valid_area"),
    (("process_version",), "hls-chip-v2"),
    (("source_native_grid",), False),
    (("grid", "width"), True),
    (("source", "collection"), "hls2-l30"),
])
def test_contradictory_polygon_receipts_block_worker_cache_and_preview(runtime, monkeypatch, path, value):
    client, field_id, settings = runtime
    captured = {}
    def bad_worker(settings, cache, geometry, payload):
        result = _worker(settings, cache, geometry, payload)
        target = result
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        (cache / result["cache_files"]["receipt"]).write_text(json.dumps(result))
        bounds = _request_identity(geometry, payload["provider_id"], None, payload["start_date"], payload["end_date"], 0, None)[1]
        ImageryStore(cache).put(result, bounds)
        captured.update(cache=cache, geometry=geometry)
        return result
    monkeypatch.setattr(service, "_run_worker", bad_worker)
    base = f"/api/demo/fields/{field_id}/imagery"
    assert client.post(base + "/analyze", headers=OWNER, json=PAYLOAD).json()["status"] == "unavailable"
    # The store remains a byte/provenance reader; serving applies current QA.
    assert ImageryStore(captured["cache"], read_only=True).get_by_chip_hash("a" * 64) is not None
    assert client.get(base + "/analyses/" + "a" * 64 + "/preview.png", headers=OWNER).status_code == 404
    monkeypatch.setattr(service, "_run_worker", lambda *a: pytest.fail("invalid cache launched worker"))
    reply = client.post(base + "/analyze", headers=OWNER, json=PAYLOAD).json()
    assert reply["status"] == "storage_unavailable"
    assert "preview_url" not in reply and "zonal_stats" not in reply


@pytest.mark.parametrize("empty", [False, True])
def test_polygon_index_support_can_be_smaller_than_clear_support(runtime, monkeypatch, empty):
    client, field_id, _ = runtime
    def worker(settings, cache, geometry, payload):
        result = _worker(settings, cache, geometry, payload)
        qa = result["qa"]
        if empty:
            result["status"] = "empty_valid_area"
            qa.update(valid_area_m2=0, valid_area_fraction=0, nodata_area_m2=3600)
        # Every QA-clear pixel may have undefined NDMI; this is not missing QA.
        qa["index_undefined_area_m2_by_reason"]["ndmi_nonpositive_denominator"] = qa["valid_area_m2"]
        for name in (("NDVI", "NDMI") if empty else ("NDMI",)):
            result["zonal_stats"][name] = {"mean": None, "min": None, "max": None, "area_m2": 0}
        (cache / result["cache_files"]["receipt"]).write_text(json.dumps(result))
        bounds = _request_identity(geometry, payload["provider_id"], None, payload["start_date"], payload["end_date"], 0, None)[1]
        ImageryStore(cache).put(result, bounds)
        return result
    monkeypatch.setattr(service, "_run_worker", worker)
    response = client.post(f"/api/demo/fields/{field_id}/imagery/analyze", headers=OWNER, json=PAYLOAD).json()
    assert response["status"] == ("empty_valid_area" if empty else "available")
    assert response["zonal_stats"]["NDMI"]["mean"] is None
    assert client.get(response["preview_url"], headers=OWNER).status_code == 200


def test_water_flag_does_not_include_nodata(tmp_path):
    from agronomy_agent.imagery_receipts import validate_hls_receipt
    from types import SimpleNamespace
    geometry = {"type": "Polygon", "coordinates": [[[-103.15, 40.15], [-103.14, 40.15], [-103.14, 40.16], [-103.15, 40.15]]]}
    receipt = _worker(SimpleNamespace(), tmp_path, geometry, PAYLOAD)
    receipt["qa"].update(nodata_area_m2=900, water_flag_area_m2=3600)
    with pytest.raises(ValueError, match="index QA area breakdown"):
        validate_hls_receipt(receipt, geometry=geometry)
