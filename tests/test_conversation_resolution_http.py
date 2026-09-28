from __future__ import annotations

from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


OWNER = {"X-Agronomy-User-Email": "continuity-owner@example.test"}


class StubGenerator:
    measured_capability_profile = "balanced"

    def generate(self, messages):  # noqa: ANN001, ANN201
        return "Please restate the complete request."


def test_contiguous_visible_stream_turns_can_resolve_reference(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "trace.sqlite3", artifact_root=tmp_path / "artifacts",
        allow_model_id_override=True, network_mode="offline",
    )
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    organization = client.post("/orgs", headers=OWNER, json={"name": "Contiguous"})
    assert organization.status_code == 201, organization.text
    workspace = client.post(
        "/workspaces", headers=OWNER,
        json={"organization_id": organization.json()["id"], "name": "Contiguous"},
    )
    assert workspace.status_code == 201, workspace.text
    workspace_id = workspace.json()["id"]
    thread = client.post(
        "/threads", headers=OWNER,
        json={"workspace_id": workspace_id, "title": "Conversions", "mode": "agronomic_rag"},
    )
    assert thread.status_code == 201, thread.text
    thread_id = thread.json()["id"]
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: StubGenerator(),
    )

    for question, answer in (
        ("Convert 100 lb/ac to kg/ha", "112.085 kg/ha"),
        ("What about 200 instead?", "224.17 kg/ha"),
    ):
        response = client.post(
            "/chat/stream", headers=OWNER,
            json={"workspace_id": workspace_id, "thread_id": thread_id,
                  "message": question, "mode": "agronomic_rag"},
        )
        assert response.status_code == 200, response.text
        assert answer in response.text

    saved = client.get(f"/threads/{thread_id}", headers=OWNER).json()
    legacy_id = saved["metadata"]["legacy_session_id"]
    last = client.app.state.trace_store.get_recent_session_turns(legacy_id, limit=1)[0]
    resolution = client.app.state.trace_store.get_turn(last["turn_id"])["trace"]["metadata"]["conversation_resolution"]
    assert resolution["status"] == "resolved_unique_user_number"
    assert resolution["effective_question"] == "Convert 200 lb/ac to kg/ha"


def test_failed_visible_stream_turn_breaks_legacy_reference_chain(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "trace.sqlite3",
        artifact_root=tmp_path / "artifacts",
        allow_model_id_override=True,
        network_mode="offline",
    )
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    organization = client.post("/orgs", headers=OWNER, json={"name": "Continuity"})
    assert organization.status_code == 201, organization.text
    workspace = client.post(
        "/workspaces", headers=OWNER,
        json={"organization_id": organization.json()["id"], "name": "Continuity"},
    )
    assert workspace.status_code == 201, workspace.text
    workspace_id = workspace.json()["id"]
    thread = client.post(
        "/threads", headers=OWNER,
        json={"workspace_id": workspace_id, "title": "Conversions", "mode": "agronomic_rag"},
    )
    assert thread.status_code == 201, thread.text
    thread_id = thread.json()["id"]

    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: StubGenerator(),
    )

    def ask(question):  # noqa: ANN001, ANN202
        return client.post(
            "/chat/stream", headers=OWNER,
            json={
                "workspace_id": workspace_id,
                "thread_id": thread_id,
                "message": question,
                "mode": "agronomic_rag",
            },
        )

    first = ask("Convert 100 lb/ac to kg/ha")
    assert first.status_code == 200, first.text
    assert "112.085 kg/ha" in first.text

    with monkeypatch.context() as patch:
        def fail_after_visible_user_message(**_kwargs):  # noqa: ANN202
            raise ValueError("controlled failure after visible user message")

        patch.setattr("agronomy_agent.server.app.run_turn", fail_after_visible_user_message)
        failed = ask("Now, how is my canola doing?")
    assert failed.status_code == 500

    third = ask("What about 200 instead?")
    assert third.status_code == 200, third.text
    saved = client.get(f"/threads/{thread_id}", headers=OWNER)
    assert saved.status_code == 200, saved.text
    visible_users = [
        message["content"] for message in saved.json()["messages"]
        if message["actor"] == "user"
    ]
    assert visible_users == [
        "Convert 100 lb/ac to kg/ha",
        "Now, how is my canola doing?",
        "What about 200 instead?",
    ]

    store = client.app.state.trace_store
    legacy_id = saved.json()["metadata"]["legacy_session_id"]
    legacy_turns = store.get_recent_session_turns(legacy_id, limit=8, exclude_replays=True)
    assert [turn["user_message"] for turn in legacy_turns] == [
        "Convert 100 lb/ac to kg/ha", "What about 200 instead?",
    ]
    final_trace = store.get_turn(legacy_turns[-1]["turn_id"])["trace"]
    resolution = final_trace["metadata"]["conversation_resolution"]
    assert resolution["status"] == "conversation_reference_gap"
    assert resolution["effective_question"] == "What about 200 instead?"
    assert resolution["source_turn_id"] is None
    assert final_trace["tool_invocations"] == []
