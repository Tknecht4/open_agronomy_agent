from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.execution_core import AgentExecutionRequest, EXECUTION_STAGE_IDS
from agronomy_agent.server.app import create_app
from agronomy_agent.server.services.chat_service import execute_agent_request, _with_stored_field_data
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


OWNER = {"X-Agronomy-User-Email": "import-owner@example.test"}
OUTSIDER = {"X-Agronomy-User-Email": "import-outsider@example.test"}
CONTENT = b"Field,sample,yield_kg_ha\nA,one,2000\nB,two,9999\nA,three,4000\n"


def mapping():
    return {"filters": {"Field": "A"}, "record_key": ["sample"], "source": {"title": "Reviewed upload"}, "columns": [
        {"column": "sample", "label": "sample", "unit": None, "role": "identifier", "aggregation": "none", "evidence_role": "observation"},
        {"column": "yield_kg_ha", "label": "yield_kg_ha", "unit": "kg/ha", "role": "measurement", "aggregation": "mean", "evidence_role": "observation"},
    ]}


@pytest.fixture
def runtime(tmp_path: Path):
    settings = build_settings(db_path=tmp_path / "fields.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")
    client = TestClient(create_app(settings))
    created = client.post("/api/demo/fields", headers=OWNER, json={"name": "Imported field", "field": {"crop": "wheat", "region": "Colorado", "jurisdiction": "United States"}, "geometry": {"kind": "none"}})
    assert created.status_code == 201, created.text
    yield client, created.json()["field"]["field_context_id"], settings
    client.close()


def preview(client, field_id):
    response = client.post(f"/api/demo/fields/{field_id}/data/preview", headers=OWNER,
        json={"filename": "yield.csv", "base64_content": base64.b64encode(CONTENT).decode()})
    assert response.status_code == 201, response.text
    return response.json()["import_id"]


def test_upload_review_commit_query_and_reload(runtime):
    client, field_id, _ = runtime
    import_id = preview(client, field_id)
    path = f"/api/demo/fields/{field_id}/data"
    assert client.get(path, headers=OWNER).json() == {"imports": []}
    denied = client.post(f"{path}/{import_id}/query", headers=OWNER, json={"operation": "mean", "column": "yield_kg_ha"})
    assert denied.status_code == 422
    committed = client.post(f"{path}/{import_id}/commit", headers=OWNER, json={"mapping": mapping()})
    assert committed.status_code == 200, committed.text
    assert committed.json()["import"]["row_count"] == 2
    assert len(client.get(path, headers=OWNER).json()["imports"]) == 1
    result = client.post(f"{path}/{import_id}/query", headers=OWNER, json={"operation": "mean", "column": "yield_kg_ha"})
    assert result.status_code == 200, result.text
    assert result.json()["value"] == 3000
    assert [x["record"] for x in result.json()["locators"]] == [2, 4]
    assert "source_bytes" not in committed.text


def test_every_field_route_checks_workspace_and_deleted_field(runtime):
    client, field_id, _ = runtime
    import_id = preview(client, field_id)
    path = f"/api/demo/fields/{field_id}/data"
    for response in (
        client.get(path, headers=OUTSIDER),
        client.post(f"{path}/preview", headers=OUTSIDER, json={"filename": "x.csv", "base64_content": "YQo="}),
        client.post(f"{path}/{import_id}/commit", headers=OUTSIDER, json={"mapping": mapping()}),
        client.post(f"{path}/{import_id}/query", headers=OUTSIDER, json={"operation": "count"}),
        client.post(f"/api/demo/fields/{field_id}/imagery/search", headers=OUTSIDER,
            json={"provider_id": "sentinel2-c1-earth-search", "start_date": "2025-06-01", "end_date": "2025-06-10"}),
    ):
        assert response.status_code == 403, response.text
    assert client.delete(f"/api/demo/fields/{field_id}", headers=OWNER).status_code == 200
    assert client.get(path, headers=OWNER).status_code == 404


def test_invalid_upload_and_mapping_remain_noncommitted(runtime):
    client, field_id, _ = runtime
    path = f"/api/demo/fields/{field_id}/data"
    assert client.post(path + "/preview", headers=OWNER, json={"filename": "x.csv", "base64_content": "not base64"}).status_code == 422
    import_id = preview(client, field_id)
    unsafe = mapping()
    unsafe["filters"] = {}
    result = client.post(f"{path}/{import_id}/commit", headers=OWNER, json={"mapping": unsafe})
    assert result.status_code == 422
    assert client.get(path, headers=OWNER).json() == {"imports": []}


def test_malformed_xlsx_is_a_validation_response_not_server_error(runtime):
    client, field_id, _ = runtime
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("foo.txt", "This ZIP is not a workbook")
    result = client.post(f"/api/demo/fields/{field_id}/data/preview", headers=OWNER,
        json={"filename": "malformed.xlsx", "base64_content": base64.b64encode(stream.getvalue()).decode()})
    assert result.status_code == 422, result.text
    assert client.get(f"/api/demo/fields/{field_id}/data", headers=OWNER).json() == {"imports": []}


def test_imagery_requires_stored_polygon_and_offline_blocks(runtime):
    client, field_id, _ = runtime
    providers = client.get("/api/imagery/providers").json()["providers"]
    assert any(not p["account_required"] for p in providers)
    body = {"provider_id": "hls-s30-planetary-computer", "start_date": "2025-06-01", "end_date": "2025-06-10"}
    assert client.post(f"/api/demo/fields/{field_id}/imagery/search", headers=OWNER, json=body).status_code == 422
    saved = client.patch(f"/api/demo/fields/{field_id}", headers=OWNER, json={"name": "Polygon field", "field": {}, "geometry": {"kind": "polygon", "points": [
        {"lat": 40.15, "lon": -103.15}, {"lat": 40.15, "lon": -103.14}, {"lat": 40.16, "lon": -103.14}, {"lat": 40.16, "lon": -103.15}]}})
    assert saved.status_code == 200, saved.text
    result = client.post(f"/api/demo/fields/{field_id}/imagery/search", headers=OWNER, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "blocked_offline"


def test_stored_table_reaches_production_receipts_and_client_cannot_supply_it(runtime):
    client, field_id, settings = runtime
    import_id = preview(client, field_id)
    assert client.post(f"/api/demo/fields/{field_id}/data/{import_id}/commit", headers=OWNER, json={"mapping": mapping()}).status_code == 200
    store = TraceStore(settings.db_path)
    field = store.get_phase4_field_context(field_id)
    session = store.create_session("Import query", {}, {})
    context = {"field_context_id": field_id, "field_access_authorized": True, "field_access_workspace_id": field["workspace_id"], "field_context": {"field_context_id": field_id, "field_data": {"fabricated": True}}}
    response = execute_agent_request(AgentExecutionRequest(
        store=store, settings=settings, session_id=session["session_id"],
        message="What is the mean yield_kg_ha in my uploaded data?", mode="agronomic_rag", model_id="mock",
        rag_config="configs/rag.yaml", max_tokens=100, session_context=context,
        trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
    ))
    assert "3000" in response.answer
    assert [x["stage_id"] for x in response.stage_receipts] == list(EXECUTION_STAGE_IDS)
    trace = response.turn["trace"]
    assert trace["metadata"]["field_context"]["field_data"]["imports"][0]["import_id"] == import_id
    assert trace["metadata"]["field_context_compiler"]["imported_data"]["import_count"] == 1
    assert "fabricated" not in str(trace)
    untrusted = _with_stored_field_data(store, session_context={}, field_context={"field_data": {"fabricated": True}})
    assert "field_data" not in untrusted
    with pytest.raises(ValueError, match="workspace binding"):
        _with_stored_field_data(store, session_context={**context, "field_access_workspace_id": "different"}, field_context=context["field_context"])
    store._conn.close()


def test_source_named_column_answer_survives_http_and_persistence(runtime):
    client, field_id, settings = runtime
    from dataclasses import replace
    client = TestClient(create_app(replace(settings, allow_model_id_override=True)))
    content = CONTENT.replace(b"yield_kg_ha", b"source_yd")
    uploaded = client.post(f"/api/demo/fields/{field_id}/data/preview", headers=OWNER,
        json={"filename": "study.csv", "base64_content": base64.b64encode(content).decode()})
    assert uploaded.status_code == 201
    reviewed = mapping()
    reviewed["columns"][1].update(column="source_yd", label="Seed yield")
    import_id = uploaded.json()["import_id"]
    assert client.post(f"/api/demo/fields/{field_id}/data/{import_id}/commit", headers=OWNER,
                       json={"mapping": reviewed}).status_code == 200
    session = client.post("/api/sessions", headers=OWNER, json={"title": "Source column", "consent": {}}).json()
    response = client.post(f"/api/sessions/{session['session_id']}/turns", headers=OWNER, json={
        "message": "What is the mean source_yd in my uploaded data?", "mode": "agronomic_rag",
        "model_id": "mock", "session_context": {"field_context_id": field_id}, "max_tokens": 80})
    assert response.status_code == 200, response.text
    turn = response.json()["turn"]
    executed = next(item for item in turn["trace"]["tool_invocations"]
                    if item["tool_id"] == "field_table_query" and item["status"] == "success")
    assert turn["answer"] == executed["payload"]["answer"]
    assert "Mean source_yd: 3000" in turn["answer"]
    assert turn["trace"]["structured_answer"]["answer"] == turn["answer"]
    import sqlite3
    with sqlite3.connect(settings.db_path) as connection:
        saved = connection.execute("SELECT answer FROM turns WHERE id = ?", (response.json()["turn_id"],)).fetchone()[0]
    assert saved == turn["answer"]
    client.close()
