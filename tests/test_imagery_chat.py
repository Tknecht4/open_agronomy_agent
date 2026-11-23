"""A selected retained scene reaches the same draft, verifier and saved evidence."""
from dataclasses import replace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from agronomy_agent.server.app import create_app
from agronomy_agent.server.services import chat_service, imagery_service
from test_imagery_jobs import body
from test_imagery_routes import GEOMETRY, OUTSIDER, OWNER, _worker, runtime

QUESTION = "For this field, what are the NDVI and NDMI averages in the selected satellite image, and what area do those averages describe?"


def _session(client, field_id=None, headers=OWNER):
    response = client.post("/api/sessions", headers=headers, json={
        "title": "Synthetic imagery question",
        "consent": {"local_trace_capture": True, "research_export_allowed": False, "training_export_allowed": False},
        "context": {"field_context_id": field_id, "field_season": 2021} if field_id else {},
    })
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _preview(client, sid, turn, headers=OWNER):
    return client.post("/api/turn-readiness", headers=headers, json={
        "session_id": sid, "request_id": str(uuid4()), "turn": turn,
    })


def _fail_if_worker(*args):
    pytest.fail("Reading a retained analysis must never invoke the imagery worker")


@pytest.fixture
def saved_job(runtime, monkeypatch):
    client, field_id, settings = runtime
    monkeypatch.setattr(imagery_service, "_run_worker", _worker)
    response = client.post(f"/api/fields/{field_id}/imagery-jobs", headers=OWNER, json=body(client, field_id))
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    job = client.get(f"/api/imagery-jobs/{job_id}", headers=OWNER).json()
    assert job["status"] == "completed"
    monkeypatch.setattr(imagery_service, "_run_worker", _fail_if_worker)
    return client, field_id, settings, job


def test_selected_job_reaches_actual_turn_prompt_verifier_and_source_card_offline(saved_job, monkeypatch):
    _, field_id, settings, job = saved_job
    prompts, verifier_inputs = [], []
    verify = chat_service.verify_answer

    class CapturingBackend:
        def generate(self, messages):
            prompts.append(messages[-1]["content"])
            return "The NDVI average was 0.5 for the pixels that passed quality checks. Check the affected patch and a nearby comparison area."

    def observe_verifier(*args, **kwargs):
        verifier_inputs.append(kwargs["evidence_text"])
        return verify(*args, **kwargs)

    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "mlx")
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args: CapturingBackend())
    monkeypatch.setattr(chat_service, "verify_answer", observe_verifier)
    request = {"message": QUESTION, "mode": "agronomic_rag", "imagery_job_id": job["id"],
               "trace_options": {"store_prompt_messages": True}, "client_operation_id": str(uuid4())}
    with TestClient(create_app(replace(settings, network_mode="offline"))) as client:
        sid = _session(client, field_id)
        preview = _preview(client, sid, request)
        assert preview.status_code == 200, preview.text
        assert preview.json()["binding"]["imagery_job_id"] == job["id"]
        assert client.app.state.trace_store.count_session_turns(sid) == 0
        request["readiness_binding"] = preview.json()["readiness_binding"]

        response = client.post(f"/api/sessions/{sid}/turns/stream", headers=OWNER, json=request)
        assert response.status_code == 200, response.text
        session = client.get(f"/api/sessions/{sid}", headers=OWNER).json()
        assert len(session["turns"]) == 1, response.text
        turn = session["turns"][0]
        assert "Selected satellite image (2021-06-10)" in turn["answer"]
        assert "75% of the analyzed area passed the quality checks" in turn["answer"]
        assert "NDVI mean 0.5 from 2700 m² (75% of the analyzed area)" in turn["answer"]
        assert len(verifier_inputs) == 1, response.text
        for projection in (prompts[0], verifier_inputs[0]):
            assert "hls2-s30:fixture" in projection
            assert "NDVI mean 0.5 from 2700 m²" in projection
            assert "QA-clear 2700 m² of 3600 m² total support" in projection
            assert job["geometry_revision_id"] in projection
        trace = turn["trace"]
        imagery = trace["metadata"]["field_context_compiler"]["imagery_observation"]
        assert imagery["result_sha256"] == job["result_sha256"]
        assert imagery["geometry_status"] == "current"
        assert imagery["indices"]["NDVI"] == {"mean": 0.5, "valid_area_m2": 2700}
        card = next(card for card in trace["structured_answer"]["evidence"] if card["source_type"] == "processed_observation")
        assert card["source_id"] == job["result_sha256"]
        assert card["imagery_observation"] == imagery
        assert "imagery_observation" not in session["context"]["field_context"]
        assert client.app.state.trace_store.list_phase4_field_events(field_id) == []

        stored_field = client.get("/api/demo/fields", headers=OWNER).json()["fields"][0]
        changed = client.patch(f"/api/demo/fields/{field_id}", headers=OWNER, json={
            "name": "Moved", "field": {}, "geometry": {"kind": "point", "point": {"lat": 40.2, "lon": -103.2}},
            "expectedUpdatedAt": stored_field["updatedAt"],
        })
        assert changed.status_code == 200, changed.text
        replay = client.post("/api/replay", headers=OWNER, json={"base_turn_id": turn["turn_id"], "pipeline": "full"})
        assert replay.status_code == 200, replay.text
        replay_imagery = replay.json()["turn"]["trace"]["metadata"]["field_context_compiler"]["imagery_observation"]
        assert replay_imagery["geometry_status"] == "historical"
        assert replay_imagery["result_sha256"] == imagery["result_sha256"]
        assert "original historical boundary" in verifier_inputs[-1]

        store = client.app.state.trace_store
        with store._cursor() as cursor:
            cursor.execute("UPDATE field_imagery_jobs SET result_json='{' WHERE id=?", (job["id"],))
        repeated = client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json=request)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["turn_id"] == turn["turn_id"]
        assert len(verifier_inputs) == 2
        conflict = client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json={**request, "imagery_job_id": str(uuid4())})
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "operation_conflict"
        corrupt = _preview(client, sid, request)
        assert corrupt.status_code == 409
        assert corrupt.json()["detail"]["code"] == "imagery_evidence_unavailable"


def test_selection_is_scoped_and_client_payload_cannot_supply_an_observation(saved_job):
    client, field_id, _, job = saved_job
    turn = {"message": QUESTION, "mode": "agronomic_rag", "imagery_job_id": job["id"]}
    sid = _session(client, field_id)
    assert _preview(client, sid, turn, OUTSIDER).status_code in (403, 404)
    assert _preview(client, _session(client), turn).status_code == 404
    other = client.post("/api/demo/fields", headers=OWNER, json={"name": "Other", "field": {}, "geometry": GEOMETRY})
    assert other.status_code == 201, other.text
    assert _preview(client, _session(client, other.json()["field"]["field_context_id"]), turn).status_code == 404

    text_only = {"message": QUESTION + " " + job["id"], "mode": "agronomic_rag", "session_context": {
        "field_context": {"imagery_observation": {"job_id": job["id"], "indices": {"NDVI": {"mean": 0.99}}}},
    }}
    result = _preview(client, sid, text_only)
    assert result.status_code == 200, result.text
    assert "imagery_job_id" not in result.json()["binding"]
