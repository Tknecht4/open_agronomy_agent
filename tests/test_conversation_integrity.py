from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from agronomy_agent.execution_core import AgentExecutionRequest
from agronomy_agent.server.app import create_app, _completed_hosted_reference_turn_ids
from agronomy_agent.server.services.chat_service import (
    ConversationOperationConflict, execute_agent_request, run_turn,
)
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.backup import create_backup, restore_backup
from agronomy_agent.server.storage.db import TraceStore


OWNER = {"X-Agronomy-User-Email": "integrity-owner@example.test"}


class WaitingBackend:
    measured_capability_profile = "balanced"

    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release
        self.prompts: list[list[dict[str, str]]] = []

    def generate(self, messages):  # noqa: ANN001, ANN201
        self.prompts.append(messages)
        if "First question" in messages[-1]["content"]:
            self.started.set()
            assert self.release.wait(10)
        return "Synthetic answer."


def _ask(store, settings, session_id, message, backend):  # noqa: ANN001, ANN202
    request = AgentExecutionRequest(
        store=store, settings=settings, session_id=session_id, message=message,
        mode="baseline", model_id="mock", rag_config="configs/rag.yaml",
        max_tokens=50, generation_backend=backend,
        execution_class="observed_system_execution_nonclaim",
    )
    return execute_agent_request(request).turn


def test_same_session_turns_serialize_without_blocking_another_session(tmp_path):  # noqa: ANN001
    store = TraceStore(tmp_path / "turns.sqlite3")
    settings = build_settings(db_path=tmp_path / "turns.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")
    first_session = store.create_session("First", {}, {})["session_id"]
    other_session = store.create_session("Other", {}, {})["session_id"]
    started, release = Event(), Event()
    backend = WaitingBackend(started, release)
    with ThreadPoolExecutor(max_workers=3) as workers:
        first = workers.submit(_ask, store, settings, first_session, "First question about crops?", backend)
        assert started.wait(10)
        second = workers.submit(_ask, store, settings, first_session, "Second question about crops?", backend)
        other = workers.submit(_ask, store, settings, other_session, "Independent question about crops?", backend)
        try:
            assert other.result(timeout=10)["trace"]["metadata"]["context_budget"]["history_turns_available"] == 0
            assert not second.done()
        finally:
            release.set()
        first_result = first.result(timeout=15)
        second_result = second.result(timeout=15)
    budget = second_result["trace"]["metadata"]["context_budget"]
    assert budget["history_turns_available"] == 1
    assert budget["history_included_turn_ids"] == [first_result["turn_id"]]


def test_operation_replay_conflict_and_reopen(tmp_path):  # noqa: ANN001
    db_path = tmp_path / "retry.sqlite3"
    store = TraceStore(db_path)
    settings = build_settings(db_path=db_path, artifact_root=tmp_path / "artifacts", network_mode="offline")
    session_id = store.create_session("Retry", {}, {})["session_id"]
    operation_id = str(uuid4())

    def ask(current_store, question, digest):  # noqa: ANN001, ANN202
        return run_turn(
            store=current_store, settings=settings, session_id=session_id,
            message=question, mode="agronomic_rag", model_id="mock",
            rag_config="configs/rag.yaml", max_tokens=50, trace_options={},
            client_operation_id=operation_id, operation_request_sha256=digest,
        )

    first = ask(store, "Convert 100 lb/ac to kg/ha", "exact-request-hash")
    replay = ask(store, "Convert 100 lb/ac to kg/ha", "exact-request-hash")
    assert replay["turn_id"] == first["turn_id"]
    assert replay["operation_replayed"] is True
    assert store.count_session_turns(session_id) == 1
    assert store.get_session(session_id)["turns"][0]["metadata"]["client_operation_id"] == operation_id
    with pytest.raises(ConversationOperationConflict):
        ask(store, "Convert 200 lb/ac to kg/ha", "changed-request-hash")
    store._conn.close()
    reopened = TraceStore(db_path)
    assert ask(reopened, "Convert 100 lb/ac to kg/ha", "exact-request-hash")["turn_id"] == first["turn_id"]
    assert reopened.count_session_turns(session_id) == 1
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    backup = create_backup(
        db_path=db_path, artifact_root=tmp_path / "artifacts", backup_root=tmp_path / "backups",
    )
    restored_path = tmp_path / "restored" / "chat.sqlite3"
    restore_backup(
        backup_dir=backup.backup_dir, target_db_path=restored_path,
        target_artifact_root=tmp_path / "restored" / "artifacts",
    )
    restored = TraceStore(restored_path)
    assert restored.get_turn_operation(session_id, operation_id) == {
        "request_sha256": "exact-request-hash", "turn_id": first["turn_id"],
    }


def test_in_flight_duplicate_operation_waits_and_reuses_one_turn(tmp_path):  # noqa: ANN001
    store = TraceStore(tmp_path / "inflight.sqlite3")
    settings = build_settings(db_path=tmp_path / "inflight.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")
    session_id = store.create_session("Inflight", {}, {})["session_id"]
    started, release = Event(), Event()
    backend = WaitingBackend(started, release)
    operation_id = str(uuid4())

    def ask():  # noqa: ANN202
        request = AgentExecutionRequest(
            store=store, settings=settings, session_id=session_id,
            message="First question about crops?", mode="baseline", model_id="mock",
            rag_config="configs/rag.yaml", max_tokens=50, generation_backend=backend,
            client_operation_id=operation_id, operation_request_sha256="same-request",
            execution_class="observed_system_execution_nonclaim",
        )
        return execute_agent_request(request)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(ask)
        assert started.wait(10)
        retry = workers.submit(ask)
        assert not retry.done()
        release.set()
        first_result = first.result(timeout=15)
        retry_result = retry.result(timeout=15)
    assert first_result.turn_id == retry_result.turn_id
    assert retry_result.operation_replayed is True
    assert len(backend.prompts) == 1
    assert store.count_session_turns(session_id) == 1


def test_http_replay_keeps_completed_turn_shape_and_conflict_is_409(tmp_path: Path):
    settings = build_settings(db_path=tmp_path / "api.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline", allow_model_id_override=True)
    client = TestClient(create_app(settings))
    created = client.post("/api/sessions", headers=OWNER, json={"title": "Retry", "consent": {}, "context": {"field_conversation_key": "general"}})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    operation_id = str(uuid4())
    payload = {"message": "Convert 100 lb/ac to kg/ha", "mode": "mock", "client_operation_id": operation_id}
    endpoint = f"/api/sessions/{session_id}/turns"
    first = client.post(endpoint, headers=OWNER, json=payload)
    replay = client.post(endpoint, headers=OWNER, json=payload)
    assert first.status_code == replay.status_code == 200
    assert first.json()["turn_id"] == replay.json()["turn_id"]
    assert replay.json()["turn"]["metadata"]["client_operation_id"] == operation_id
    streamed = client.post(endpoint + "/stream", headers=OWNER, json=payload)
    assert streamed.status_code == 200
    assert f'"turn_id": "{first.json()["turn_id"]}"' in streamed.text
    assert "event: answer.completed" in streamed.text
    conflict = client.post(endpoint, headers=OWNER, json={**payload, "message": "Convert 200 lb/ac to kg/ha"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "operation_conflict"
    stream_conflict = client.post(endpoint + "/stream", headers=OWNER, json={**payload, "message": "Convert 300 lb/ac to kg/ha"})
    assert stream_conflict.status_code == 409
    assert len(client.get(f"/api/sessions/{session_id}", headers=OWNER).json()["turns"]) == 1


def test_hosted_reference_suffix_uses_receipt_id_not_duplicate_text():
    turn = {"turn_id": "turn-new", "user_message": "Convert 100 lb/ac to kg/ha"}
    user = {"actor": "user", "content": turn["user_message"]}
    assistant = {"actor": "assistant", "content": "answer", "metadata": {"legacy_turn_id": "turn-old"}}
    assert _completed_hosted_reference_turn_ids([user, assistant], [turn]) == []
    assistant["metadata"]["legacy_turn_id"] = "turn-new"
    assert _completed_hosted_reference_turn_ids([user, assistant], [turn]) == ["turn-new"]
    assert _completed_hosted_reference_turn_ids([user, assistant, user], [turn]) == []


def test_blocked_same_session_http_turn_keeps_health_responsive(tmp_path, monkeypatch):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "async.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline", allow_model_id_override=True,
    )
    app = create_app(settings)
    started, release = Event(), Event()
    backend = WaitingBackend(started, release)
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: backend,
    )

    async def exercise() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            created = await client.post("/api/sessions", headers=OWNER, json={"title": "Async", "consent": {}, "context": {"field_conversation_key": "general"}})
            assert created.status_code == 200
            sid = created.json()["session_id"]
            first = asyncio.create_task(client.post(
                f"/api/sessions/{sid}/turns", headers=OWNER,
                json={"message": "First question about crops?", "mode": "baseline"},
            ))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                health = await asyncio.wait_for(client.get("/api/health"), timeout=3)
                assert health.status_code == 200
            finally:
                release.set()
            assert (await asyncio.wait_for(first, timeout=15)).status_code == 200

    asyncio.run(exercise())


def test_saved_conversation_routes_fail_explicitly_for_unported_store(tmp_path, monkeypatch):  # noqa: ANN001
    from agronomy_agent.server import app as app_module

    monkeypatch.setattr(app_module, "build_trace_store", lambda _settings: object())
    monkeypatch.setattr(app_module, "_corpus_audit", lambda _settings, _store: "synthetic-audit")
    app = create_app(build_settings(db_path=tmp_path / "unused.sqlite3", artifact_root=tmp_path / "artifacts"))
    client = TestClient(app)
    for response in (
        client.get("/api/sessions"),
        client.post("/api/sessions", json={"title": "Unsupported", "consent": {}, "context": {}}),
    ):
        assert response.status_code == 501
        assert response.json()["detail"]["code"] == "conversation_storage_unavailable"
