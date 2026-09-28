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
        session_id, kwargs.pop("message", f"Question {index}"), f"Answer {index}", parent_turn_id=None,
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


def _hosted_workspace(client):
    org = client.post("/orgs", headers=OWNER, json={"name": "Scope regression org"})
    assert org.status_code == 201, org.text
    workspace = client.post("/workspaces", headers=OWNER, json={
        "organization_id": org.json()["id"], "name": "Scope regression workspace",
    })
    assert workspace.status_code == 201, workspace.text
    return workspace.json()["id"]


def _hosted_field(client, workspace_id, name):
    response = client.post("/field-contexts", headers=OWNER, json={
        "workspace_id": workspace_id, "display_name": name,
        "region_text": "Alberta", "crop_current": "canola",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _hosted_thread(client, workspace_id, field_id=None):
    response = client.post("/threads", headers=OWNER, json={
        "workspace_id": workspace_id, "title": "Scope regression",
        "field_context_id": field_id, "mode": "baseline",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _chat(client, workspace_id, thread_id, message, field_id=None):
    payload = {"workspace_id": workspace_id, "thread_id": thread_id,
               "message": message, "mode": "baseline"}
    if field_id is not None:
        payload["field_context_id"] = field_id
    return client.post("/chat/stream", headers=OWNER, json=payload)


def _record_hosted_prompts(monkeypatch):
    prompts = []

    class RecordingGenerator:
        model_id = "synthetic-local-model"
        last_generation_stats = None

        def generate(self, messages):
            prompts.append(str(messages))
            return "Synthetic response."

        def count_prompt_tokens(self, messages):
            return sum(len(str(item.get("content", ""))) for item in messages) // 4

    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: RecordingGenerator(),
    )
    return prompts


def test_legacy_stream_keeps_field_scope_and_resolves_omitted_field(client, monkeypatch):
    workspace_id = _hosted_workspace(client)
    north = _hosted_field(client, workspace_id, "North")
    south = _hosted_field(client, workspace_id, "South")
    thread_id = _hosted_thread(client, workspace_id, north)
    prompts = _record_hosted_prompts(monkeypatch)
    first = _chat(client, workspace_id, thread_id, "FIELD_A_ONLY_MARKER", north)
    assert first.status_code == 200, first.text
    before = client.get(f"/threads/{thread_id}", headers=OWNER).json()
    legacy_id = before["metadata"]["legacy_session_id"]
    store = client.app.state.trace_store
    assert store.get_session(legacy_id, include_turns=False)["context"]["field_context_id"] == north
    denied = _chat(client, workspace_id, thread_id, "FIELD_B_SECRET", south)
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["code"] == "conversation_scope_mismatch"
    assert len(client.get(f"/threads/{thread_id}", headers=OWNER).json()["messages"]) == 2
    assert store.count_session_turns(legacy_id) == 1
    omitted = _chat(client, workspace_id, thread_id, "Continue on this field")
    assert omitted.status_code == 200, omitted.text
    assert "FIELD_A_ONLY_MARKER" in prompts[-1]
    assert "FIELD_B_SECRET" not in prompts[-1]
    assert store.get_session(legacy_id, include_turns=False)["context"]["field_context_id"] == north


def test_legacy_stream_general_thread_cannot_acquire_field(client, monkeypatch):
    _record_hosted_prompts(monkeypatch)
    workspace_id = _hosted_workspace(client)
    field_id = _hosted_field(client, workspace_id, "North")
    thread_id = _hosted_thread(client, workspace_id)
    denied = _chat(client, workspace_id, thread_id, "Move to North", field_id)
    assert denied.status_code == 409, denied.text
    assert client.get(f"/threads/{thread_id}", headers=OWNER).json()["messages"] == []
    accepted = _chat(client, workspace_id, thread_id, "General crop question")
    assert accepted.status_code == 200, accepted.text
    thread = client.get(f"/threads/{thread_id}", headers=OWNER).json()
    legacy = client.app.state.trace_store.get_session(thread["metadata"]["legacy_session_id"], include_turns=False)
    assert legacy["context"]["field_conversation_key"] == "general"
    assert "field_context_id" not in legacy["context"] or legacy["context"]["field_context_id"] is None


def test_legacy_bridge_quarantines_untrusted_mixed_history_without_deleting_receipts(client, monkeypatch):
    workspace_id = _hosted_workspace(client)
    north = _hosted_field(client, workspace_id, "North")
    south = _hosted_field(client, workspace_id, "South")
    thread_id = _hosted_thread(client, workspace_id, north)
    store = client.app.state.trace_store
    thread = store.get_phase4_thread(thread_id)
    old = store.create_session(title="Old bridge", context={
        "field_context_id": north,
        "field_conversation_key": f"field:{north}",
        "_legacy_bridge_scope_version": 1,
        "extra": {"_session_owner_user_id": thread["created_by_user_id"]},
    }, consent={})["session_id"]
    _turn(store, old, 1, message="OLD_NORTH_MARKER", metadata={"scope": north})
    _turn(store, old, 2, message="OLD_SOUTH_MARKER", metadata={"scope": south})
    store.create_phase4_message(thread=thread, actor="user", content="OLD_NORTH_MARKER",
                                metadata={"field_context_id": north})
    store.create_phase4_message(thread=thread, actor="user", content="OLD_SOUTH_MARKER",
                                metadata={"field_context_id": south})
    store.update_phase4_thread_metadata(thread_id, metadata={"legacy_session_id": old})
    prompts = _record_hosted_prompts(monkeypatch)
    response = _chat(client, workspace_id, thread_id, "Fresh North question")
    assert response.status_code == 200, response.text
    refreshed = store.get_phase4_thread(thread_id)
    new = refreshed["metadata"]["legacy_session_id"]
    assert new != old
    assert old in refreshed["metadata"]["quarantined_legacy_session_ids"]
    assert store.count_session_turns(old) == 2
    assert len(store.list_phase4_messages(thread_id)) == 4
    assert store.count_session_turns(new) == 1
    assert store.get_session(new, include_turns=False)["context"]["field_context_id"] == north
    assert "OLD_NORTH_MARKER" not in prompts[-1]
    assert "OLD_SOUTH_MARKER" not in prompts[-1]


def test_replay_override_cannot_rebind_or_persist_a_used_general_session(client):
    created = client.post("/api/sessions", headers=OWNER, json={
        "title": "General replay", "consent": {},
        "context": {"field_conversation_key": "general:chat:one"},
    })
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    store = client.app.state.trace_store
    base_turn_id = _turn(store, session_id, 1)
    original_context = store.get_session(session_id, include_turns=False)["context"]
    denied = client.post("/api/replay", headers=OWNER, json={
        "base_turn_id": base_turn_id, "pipeline": "route_only", "mode": "mock",
        "override_session_context": {
            "field_context_id": "not-an-authorized-field",
            "field_conversation_key": "field:not-an-authorized-field",
        },
    })
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["code"] == "conversation_scope_mismatch"
    assert store.get_session(session_id, include_turns=False)["context"] == original_context
    assert store.count_session_turns(session_id) == 1

    allowed = client.post("/api/replay", headers=OWNER, json={
        "base_turn_id": base_turn_id, "pipeline": "route_only", "mode": "mock",
        "override_session_context": {"crop": "canola"},
    })
    assert allowed.status_code == 200, allowed.text
    assert store.get_session(session_id, include_turns=False)["context"] == original_context
    assert store.count_session_turns(session_id) == 2


def test_replay_cannot_promote_used_unbound_general_session_to_field(client):
    created = client.post("/api/sessions", headers=OWNER, json={
        "title": "Field replay", "consent": {}, "context": {},
    })
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    store = client.app.state.trace_store
    base_turn_id = _turn(store, session_id, 1)
    # A used legacy general session is immutable even if its stored context was
    # empty; field authorization cannot turn unknown history into field history.
    denied = client.post("/api/replay", headers=OWNER, json={
        "base_turn_id": base_turn_id, "pipeline": "route_only", "mode": "mock",
        "override_session_context": {"field_context_id": "missing"},
    })
    assert denied.status_code == 409, denied.text
    assert store.count_session_turns(session_id) == 1


def test_replay_without_override_rechecks_saved_field_authority(client, monkeypatch):
    field_id = _field(client, "Replay field")
    created = client.post("/api/sessions", headers=OWNER, json={
        "title": "Field replay", "consent": {},
        "context": {"field_context_id": field_id},
    })
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    store = client.app.state.trace_store
    base_turn_id = _turn(store, session_id, 1)
    original_context = store.get_session(session_id, include_turns=False)["context"]
    get_field = store.get_phase4_field_context
    monkeypatch.setattr(store, "get_phase4_field_context",
                        lambda candidate: None if candidate == field_id else get_field(candidate))
    denied = client.post("/api/replay", headers=OWNER, json={
        "base_turn_id": base_turn_id, "pipeline": "route_only", "mode": "mock",
    })
    assert denied.status_code == 404, denied.text
    assert store.get_session(session_id, include_turns=False)["context"] == original_context
    assert store.count_session_turns(session_id) == 1
