from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.services.conversation_scope import ConversationScopeError, bind_conversation_context
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


OWNER = {"X-Agronomy-User-Email": "conversation-owner@example.test"}
OTHER = {"X-Agronomy-User-Email": "conversation-other@example.test"}


def _turn(store: TraceStore, session_id: str, index: int, **kwargs):
    return store.create_turn(
        session_id, f"Question {index}", f"Answer {index}", parent_turn_id=None,
        system_state={"mode": "mock"}, trace={"metadata": {"large": "x" * 10000}},
        objectives={}, event_stream=False, **kwargs,
    )


def test_recent_history_is_bounded_chronological_and_excludes_heavy_trace(tmp_path, monkeypatch):
    store = TraceStore(tmp_path / "history.sqlite3")
    session = store.create_session(title="General", context={}, consent={})["session_id"]
    other = store.create_session(title="Other", context={}, consent={})["session_id"]
    ids = [_turn(store, session, i) for i in range(12)]
    _turn(store, other, 99)
    store.set_feedback(session, ids[-1], {"accepted": False, "correction": "It was barley."})

    def no_transcript(*args, **kwargs):
        pytest.fail("Full transcript was loaded for a bounded operation")

    monkeypatch.setattr(store, "_get_turns_for_session", no_transcript)
    monkeypatch.setattr(store, "_normalize_turn_row", no_transcript)
    assert store.session_exists(session)
    assert store.count_session_turns(session) == 12
    assert store.get_session(session, include_turns=False)["session_id"] == session
    assert store.update_session(session, title="Updated", include_turns=False)["title"] == "Updated"
    recent = store.get_recent_session_turns(session, limit=3)
    assert [turn["turn_id"] for turn in recent] == ids[-3:]
    assert all("trace" not in turn and "prompt_messages" not in turn for turn in recent)
    assert recent[-1]["feedback"]["correction"] == "It was barley."
    assert recent[-1]["feedback"]["accepted"] is False
    with pytest.raises(ValueError):
        store.get_recent_session_turns(session, limit=0)


def test_scope_can_hydrate_but_cannot_rebind_used_or_declared_chat():
    context = {"field_context_id": "a", "field_conversation_key": "field:a:chat:one", "field_context": {"crop": "old"}}
    hydrated = bind_conversation_context(context, None, has_turns=True)
    assert hydrated["field_context_id"] == "a"
    assert hydrated["field_conversation_key"] == "field:a:chat:one"
    assert "field_context" not in hydrated
    for incoming in ({"field_context_id": "b"}, {"field_conversation_key": "general"}, {"field_conversation_key": "field:a:chat:two", "field_context_id": "a"}):
        with pytest.raises(ConversationScopeError):
            bind_conversation_context(context, incoming, has_turns=True)
    assert bind_conversation_context({}, {"field_context_id": "a"}, has_turns=False)["field_context_id"] == "a"
    with pytest.raises(ConversationScopeError):
        bind_conversation_context({}, {"field_context_id": "a"}, has_turns=True)


@pytest.fixture
def client(tmp_path: Path):
    return TestClient(create_app(build_settings(db_path=tmp_path / "scope.sqlite3", artifact_root=tmp_path / "artifacts", allow_model_id_override=True)))


def _field(client, name):
    response = client.post("/api/demo/fields", headers=OWNER, json={
        "name": name, "field": {"crop": "canola", "region": "Leduc County", "jurisdiction": "Alberta"},
        "geometry": {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}},
    })
    assert response.status_code == 201, response.text
    return response.json()["field"]["field_context_id"]


@pytest.mark.parametrize("stream", [False, True])
def test_api_scope_is_authorized_and_immutable_on_both_turn_routes(client, stream):
    field_id = _field(client, "North")
    other_id = _field(client, "South")
    key = f"field:{field_id}:chat:one"
    created = client.post("/api/sessions", headers=OWNER, json={"title": "North conversation", "consent": {}, "context": {"field_context_id": field_id, "field_conversation_key": key}})
    assert created.status_code == 200, created.text
    session = created.json()["session_id"]
    assert created.json()["context"]["field_conversation_key"] == key
    denied_create = client.post("/api/sessions", headers=OTHER, json={"title": "Denied", "consent": {}, "context": {"field_context_id": field_id}})
    assert denied_create.status_code == 403
    endpoint = f"/api/sessions/{session}/turns" + ("/stream" if stream else "")
    for context in ({"field_context_id": other_id}, {"field_conversation_key": "general"}):
        response = client.post(endpoint, headers=OWNER, json={"message": "What next?", "mode": "mock", "session_context": context})
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "conversation_scope_mismatch"
    patched = client.patch(f"/api/sessions/{session}", headers=OWNER, json={"context": {"field_context_id": other_id}})
    assert patched.status_code == 409
    assert client.get(f"/api/sessions/{session}", headers=OTHER).status_code == 404
    accepted = client.post(endpoint, headers=OWNER, json={"message": "What is crop rotation?", "mode": "mock"})
    assert accepted.status_code == 200, accepted.text
    reloaded = client.get(f"/api/sessions/{session}", headers=OWNER).json()
    assert reloaded["context"]["field_context_id"] == field_id
    assert reloaded["context"]["field_conversation_key"] == key
    assert len(reloaded["turns"]) == 1


def test_general_turn_never_loads_full_transcript_or_changes_scope(client, monkeypatch):
    response = client.post("/api/sessions", headers=OWNER, json={"title": "General chat", "consent": {}, "context": {"field_conversation_key": "general:chat:one"}})
    session_id = response.json()["session_id"]
    store = client.app.state.trace_store
    for i in range(12):
        _turn(store, session_id, i)

    def no_transcript(*args, **kwargs):
        pytest.fail("New turn should use bounded history, not full transcript")

    monkeypatch.setattr(store, "_get_turns_for_session", no_transcript)
    response = client.post(f"/api/sessions/{session_id}/turns", headers=OWNER, json={"message": "What is soil organic matter?", "mode": "mock"})
    assert response.status_code == 200, response.text
    assert store.get_session(session_id, include_turns=False)["context"]["field_conversation_key"] == "general:chat:one"
    assert store.count_session_turns(session_id) == 13


@pytest.mark.parametrize("shape", ["direct", "extra", "nested_extra"])
def test_creation_authorizes_every_declared_field_identity_shape(client, shape):
    field_id = _field(client, "Owner field")
    context = {"field_context_id": field_id}
    if shape == "extra":
        context = {"extra": context}
    elif shape == "nested_extra":
        context = {"extra": {"field_context": context}}
    denied = client.post("/api/sessions", headers=OTHER, json={
        "title": "Unauthorized alias", "consent": {}, "context": context,
    })
    assert denied.status_code == 403, denied.text
    assert client.get("/api/sessions?include_turns=false", headers=OTHER).json() == []
    allowed = client.post("/api/sessions", headers=OWNER, json={
        "title": "Authorized alias", "consent": {}, "context": context,
    })
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["context"]["field_context_id"] == field_id


def test_creation_rejects_conflicting_direct_and_extra_identity(client):
    field_id = _field(client, "North")
    response = client.post("/api/sessions", headers=OWNER, json={
        "title": "Conflicting", "consent": {}, "context": {
            "field_context_id": field_id, "extra": {"field_context_id": "different-field"},
        },
    })
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "conversation_scope_mismatch"
