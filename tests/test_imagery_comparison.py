"""Two saved imagery jobs through the real offline worker and mounted chat."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import base64
import json
import os
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from agronomy_agent.imagery_comparison_presentation import COMPARISON_QUESTION
from agronomy_agent.server.app import create_app
from agronomy_agent.server.services import chat_service, imagery_service
from agronomy_agent.server.settings import build_settings
from test_imagery_routes import GEOMETRY, OWNER, OUTSIDER, PAYLOAD


def make_saved_arrays(settings, cache, geometry, payload):
    """Provider-free input fixture. Processing after the job is real."""
    import numpy as np
    from PIL import Image
    from agronomy_agent.geospatial.geometry import project_geometry
    from agronomy_agent.geospatial.raster import weighted_statistics
    from agronomy_agent.imagery_analytics import _request_identity, PREVIEW_VERSION, PROCESS_VERSION
    from agronomy_agent.imagery_store import ImageryStore

    store = ImageryStore(cache)
    scene = payload["scene_id"]
    version = scene.split(":")[-1]
    early = version == "early"
    clear = {
        "early": [[True, True], [False, False]],
        "late": [[True, False], [True, False]],
        "cloud": [[False, False], [True, True]],
    }[version]
    qa = np.array(clear)
    weights = np.ones(qa.shape)
    ndvi = np.where(qa, .2 if early else .5, np.nan)
    ndmi = np.where(qa, .1 if early else .3, np.nan)
    _, bounds, digest, request = _request_identity(geometry, payload["provider_id"], scene,
        payload["start_date"], payload["end_date"], 0, None)
    key = sha256(scene.encode()).hexdigest()
    filenames = {"npz": key + ".npz", "png": key + ".png", "receipt": key + ".json"}
    crs = "EPSG:32613"
    center = project_geometry(geometry, crs).representative_point()
    grid = {"crs": crs, "transform": [30, 0, center.x - 30, 0, -30, center.y + 30],
            "width": 2, "height": 2, "resolution_m": 30}
    receipt = {
        "status": "available", "chip_hash": key, "request_hash": request, "preview_version": PREVIEW_VERSION,
        "geometry_hash": digest, "process_hash": "b" * 64, "provider_id": payload["provider_id"],
        "source": {"collection": "hls2-s30", "scene_id": scene,
                   "acquired_at": f"2021-06-{1 if early else 15:02}T12:00:00Z", "asset_ids": {}},
        "scene_id": scene, "process_version": PROCESS_VERSION, "source_native_grid": True, "grid": grid,
        "qa": {
            "field_area_m2": 3600, "valid_area_m2": 1800, "valid_area_fraction": .5, "nodata_area_m2": 0,
            "water_flag_area_m2": 0, "excluded_area_m2_by_reason": {"cloud": 1800}, "overlap_note": "May overlap",
            "index_undefined_area_m2_by_reason": {f"{index}_{reason}": 0 for index in ("ndvi", "ndmi")
                                                 for reason in ("negative_reflectance", "nonpositive_denominator")},
        },
        "zonal_stats": {name: weighted_statistics(values, weights, cell_area=900)
                        for name, values in (("NDVI", ndvi), ("NDMI", ndmi))},
        "cache_files": filenames, "created_at": "2021-06-15T00:00:00Z",
    }
    np.savez_compressed(cache / filenames["npz"], valid_mask=qa, field_weights=weights, ndvi=ndvi, ndmi=ndmi)
    Image.new("RGBA", (2, 2)).save(cache / filenames["png"])
    (cache / filenames["receipt"]).write_text(json.dumps(receipt))
    store.put(receipt, bounds)
    return receipt


@pytest.fixture
def comparison_app(tmp_path, monkeypatch):
    pytest.importorskip("rasterio")
    pytest.importorskip("pyproj")
    executable = os.environ.get("OAA_COMPARISON_TEST_EXECUTABLE")
    settings = build_settings(
        db_path=tmp_path / "db.sqlite", artifact_root=tmp_path / "artifacts",
        imagery_cache_root=tmp_path / "imagery",
        imagery_worker_python=None if executable else os.environ.get("OAA_COMPARISON_TEST_PYTHON", sys.executable),
        imagery_worker_executable=executable, network_mode="online",
    )
    monkeypatch.setattr(imagery_service, "_run_worker", make_saved_arrays)
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/demo/fields", headers=OWNER, json={"name": "Two dates", "field": {}, "geometry": GEOMETRY})
        assert created.status_code == 201, created.text
        field = created.json()["field"]["id"]
        base = f"/api/fields/{field}"
        revision = client.get(base + "/summary", headers=OWNER).json()["geometry_revision_id"]
        selections = []
        for label in ("early", "late", "cloud"):
            response = client.post(base + "/imagery-jobs", headers=OWNER, json={
                **PAYLOAD, "scene_id": f"hls2-s30:{label}", "expected_geometry_revision_id": revision,
                "operation_id": str(uuid4()),
            })
            assert response.status_code == 202, response.text
            job = client.get(f"/api/imagery-jobs/{response.json()['id']}", headers=OWNER).json()
            assert job["status"] == "completed", job
            selections.append(job["id"])
    monkeypatch.setattr(imagery_service, "_run_worker", lambda *args: pytest.fail("comparison fetched source imagery"))
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args: pytest.fail("comparison constructed a model"))
    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "mlx")
    with TestClient(create_app(replace(settings, network_mode="offline"))) as client:
        yield client, field, {"first_job_id": selections[0], "second_job_id": selections[1], "geometry_revision_id": revision}, selections[2]


def test_map_mask_and_dated_scouting_record_reach_the_saved_answer(comparison_app):
    import numpy as np
    from PIL import Image

    client, field, selection, cloud = comparison_app
    base = f"/api/fields/{field}"
    response = client.post(base + "/imagery-comparison", headers=OWNER, json=selection)
    assert response.status_code == 200, response.text
    change = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert change["status"] == "descriptive_only", change
    assert change["indices"]["NDVI"]["area_m2"] == 900
    assert change["indices"]["NDVI"]["mean_delta"] == pytest.approx(.3)
    assert change["scouting_observation"] is None
    image = np.asarray(Image.open(BytesIO(base64.b64decode(change["maps"]["NDVI"]["png_base64"]))))
    alpha = image[:, :, 3]
    assert 0 < np.count_nonzero(alpha) < alpha.size / 2
    assert set(np.unique(alpha)) == {0, 255}
    not_comparable = client.post(base + "/imagery-comparison", headers=OWNER, json={**selection, "second_job_id": cloud}).json()
    assert not_comparable["status"] == "no_common_valid_pixels" and not not_comparable.get("maps")
    assert "No comparison shown" in not_comparable["overview"]
    assert client.post(base + "/imagery-comparison", headers=OUTSIDER, json=selection).status_code == 403

    undated = client.post(base + "/records", headers=OWNER, json={"operation_id": str(uuid4()), "events": [
        {"event_type": "observation", "payload": {"scouting_location": "Missing time"},
         "provenance": {"capture_method": "grower_entry", "observation_time_status": "user_supplied"}},
    ]})
    assert undated.status_code == 422
    saved = client.post(base + "/records", headers=OWNER, json={"operation_id": str(uuid4()), "events": [
        {"event_type": "observation", "occurred_at": "2021-06-16T00:30:00Z",
         "payload": {"season": 2021, "summary": "Leaves were pale.", "scouting_location": "West edge beside the gate"},
         "provenance": {"capture_method": "grower_entry", "observation_time_status": "user_supplied",
                        "observation_utc_offset_minutes": -360}},
        {"event_type": "observation", "occurred_at": "2021-06-08T12:00:00Z",
         "payload": {"season": 2021, "summary": "Uploaded image.", "scouting_location": "East edge"},
         "provenance": {"capture_method": "linked_processed_imagery", "observation_time_status": "user_supplied"}},
        {"event_type": "observation",
         "payload": {"season": 2021, "summary": "Date unknown.", "scouting_location": "North edge"},
         "provenance": {"capture_method": "grower_entry", "observation_time_status": "unknown"}},
    ]})
    assert saved.status_code == 201, saved.text
    source = saved.json()["events"][0]
    session = client.post("/api/sessions", headers=OWNER, json={
        "title": "Comparison", "consent": {}, "context": {"field_context_id": field, "field_season": 2021},
    }).json()["session_id"]
    request = {"message": COMPARISON_QUESTION, "mode": "agronomic_rag", "imagery_comparison": selection,
               "client_operation_id": str(uuid4())}
    readiness = client.post("/api/turn-readiness", headers=OWNER, json={"request_id": str(uuid4()), "session_id": session, "turn": request})
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["requires_model"] is False
    assert readiness.json()["calculator"] is None
    store = client.app.state.trace_store
    assert store.count_session_turns(session) == 0
    request["readiness_binding"] = readiness.json()["readiness_binding"]
    turns = f"/api/sessions/{session}/turns"
    response = client.post(turns + "/stream", headers=OWNER, json=request)
    assert response.status_code == 200, response.text
    turn = client.get(f"/api/sessions/{session}", headers=OWNER).json()["turns"][0]
    assert "Your dated field observation on 2021-06-15 recorded **West edge beside the gate**" in turn["answer"]
    assert "East edge" not in turn["answer"] and "North edge" not in turn["answer"]
    trace = turn["trace"]
    assert trace["metadata"]["generation_bypass"]["renderer"] == "imagery_comparison.v1"
    comparison = trace["metadata"]["field_context_compiler"]["imagery_comparison"]
    assert comparison["scouting_observation"]["integrity_sha256"] == source["integrity_sha256"]
    assert comparison["scouting_observation"]["date_basis"] == "recorded_local"
    assert "maps" not in comparison
    assert client.post(turns, headers=OWNER, json=request).json()["turn_id"] == turn["turn_id"]
    assert store.count_session_turns(session) == 1
    replay = client.post("/api/replay", headers=OWNER, json={"base_turn_id": turn["turn_id"], "pipeline": "full"})
    assert replay.status_code == 200, replay.text
    assert "West edge beside the gate" in replay.json()["turn"]["answer"]

    assert client.post(turns, headers=OWNER, json={**request, "message": "Tell me where to spray."}).status_code == 422
    corrected = client.post(base + "/records", headers=OWNER, json={"operation_id": str(uuid4()), "events": [
        {"event_type": "correction", "corrects_event_id": source["id"],
         "payload": {"season": 2021, "summary": "The location was uncertain."},
         "provenance": {"capture_method": "grower_entry", "observation_time_status": "unknown"}},
    ]})
    assert corrected.status_code == 201, corrected.text
    result = client.post(base + "/imagery-comparison", headers=OWNER, json=selection).json()
    assert result["scouting_observation"] is None
    assert "West edge" not in result["message"]

    legacy = client.post(base + "/records", headers=OWNER, json={"operation_id": str(uuid4()), "events": [
        {"event_type": "observation", "occurred_at": "2021-06-15T18:30:00Z",
         "payload": {"season": 2021, "summary": "Scouted the entrance.", "scouting_location": "North gate"},
         "provenance": {"capture_method": "grower_entry", "observation_time_status": "user_supplied"}},
    ]})
    assert legacy.status_code == 201, legacy.text
    result = client.post(base + "/imagery-comparison", headers=OWNER, json=selection).json()
    assert result["scouting_observation"]["date_basis"] == "utc"
    assert "2021-06-15 (UTC) recorded **North gate**" in result["message"]



def test_pair_is_bound_to_same_field_and_current_revision(comparison_app):
    client, field, selection, _ = comparison_app
    base = f"/api/fields/{field}"
    assert client.post(base + "/imagery-comparison", headers=OWNER,
        json={**selection, "geometry_revision_id": "superseded"}).status_code == 409
    assert client.post(base + "/imagery-comparison", headers=OWNER,
        json={**selection, "second_job_id": str(uuid4())}).status_code == 404
    with client.app.state.trace_store._cursor() as cursor:
        cursor.execute("UPDATE field_imagery_jobs SET result_json='{}' WHERE id=?", (selection["second_job_id"],))
    result = client.post(base + "/imagery-comparison", headers=OWNER, json=selection).json()
    assert result["status"] == "unavailable_source" and not result.get("maps")
