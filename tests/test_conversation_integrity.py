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
from agronomy_agent.server.app import create_app, _HOSTED_TURN_LOCKS, _completed_hosted_reference_turn_ids
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


def test_rejected_or_replayed_operation_does_not_change_saved_context(tmp_path: Path):
    settings = build_settings(db_path=tmp_path / "context.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline", allow_model_id_override=True)
    client = TestClient(create_app(settings))
    created = client.post("/api/sessions", headers=OWNER, json={"title": "Context", "consent": {}, "context": {"field_conversation_key": "sample:review"}})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    endpoint = f"/api/sessions/{session_id}/turns"
    first = {"message": "What is a cover crop?", "mode": "mock", "client_operation_id": str(uuid4()), "session_context": {"notes": "first accepted"}}
    second = {**first, "message": "What is a green manure?", "client_operation_id": str(uuid4()), "session_context": {"notes": "second accepted"}}
    assert client.post(endpoint, headers=OWNER, json=first).status_code == 200
    assert client.post(endpoint, headers=OWNER, json=second).status_code == 200
    before = client.get(f"/api/sessions/{session_id}", headers=OWNER).json()["context"]
    assert before["notes"] == "second accepted"

    assert client.post(endpoint, headers=OWNER, json=first).status_code == 200
    conflict = {**first, "session_context": {"notes": "rejected"}}
    assert client.post(endpoint, headers=OWNER, json=conflict).status_code == 409
    assert client.post(endpoint + "/stream", headers=OWNER, json=conflict).status_code == 409
    replay_stream = client.post(endpoint + "/stream", headers=OWNER, json=first)
    assert replay_stream.status_code == 200
    assert "event: answer.completed" in replay_stream.text
    after = client.get(f"/api/sessions/{session_id}", headers=OWNER).json()["context"]
    assert after == before


def test_inflight_conflicting_operation_cannot_persist_context(tmp_path, monkeypatch):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "inflight-context.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline", allow_model_id_override=True,
    )
    app = create_app(settings)
    started, release = Event(), Event()
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: WaitingBackend(started, release),
    )

    async def exercise() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            created = await client.post("/api/sessions", headers=OWNER, json={"title": "Inflight", "consent": {}, "context": {"field_conversation_key": "sample:review"}})
            assert created.status_code == 200
            sid = created.json()["session_id"]
            endpoint = f"/api/sessions/{sid}/turns"
            payload = {"message": "First question about crops?", "mode": "baseline", "client_operation_id": str(uuid4()), "session_context": {"notes": "accepted"}}
            first = asyncio.create_task(client.post(endpoint, headers=OWNER, json=payload))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                conflict = asyncio.create_task(client.post(endpoint, headers=OWNER, json={**payload, "session_context": {"notes": "rejected"}}))
                assert (await asyncio.wait_for(client.get("/api/health"), timeout=3)).status_code == 200
                pending_context = (await client.get(f"/api/sessions/{sid}", headers=OWNER)).json()["context"]
                assert pending_context.get("notes") is None
                assert not conflict.done()
            finally:
                release.set()
            assert (await asyncio.wait_for(first, timeout=15)).status_code == 200
            assert (await asyncio.wait_for(conflict, timeout=15)).status_code == 409
            saved = (await client.get(f"/api/sessions/{sid}", headers=OWNER)).json()
            assert saved["context"]["notes"] == "accepted"
            assert len(saved["turns"]) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["omitted", "adoption"])
def test_queued_turn_rebinds_latest_session_context(tmp_path, monkeypatch, kind):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / f"queued-{kind}.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline", allow_model_id_override=True,
    )
    app = create_app(settings)
    started, release = Event(), Event()
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: WaitingBackend(started, release),
    )

    async def exercise() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            initial = {"field_conversation_key": "sample:review", "notes": "old"} if kind == "omitted" else {}
            created = await client.post("/api/sessions", headers=OWNER, json={"title": "Queued", "context": initial, "consent": {}})
            assert created.status_code == 200
            sid = created.json()["session_id"]
            endpoint = f"/api/sessions/{sid}/turns"
            first_context = {"notes": "fresh"} if kind == "omitted" else {"field_conversation_key": "sample:alpha"}
            second_context = {} if kind == "omitted" else {"field_conversation_key": "sample:beta"}
            first = asyncio.create_task(client.post(endpoint, headers=OWNER, json={"message": "First question about crops?", "mode": "baseline", "session_context": first_context}))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                second = asyncio.create_task(client.post(endpoint, headers=OWNER, json={"message": "Second question about crops?", "mode": "baseline", "session_context": second_context}))
                await asyncio.sleep(0.1)
                assert not second.done()
            finally:
                release.set()
            first_result = await asyncio.wait_for(first, timeout=15)
            second_result = await asyncio.wait_for(second, timeout=15)
            saved = (await client.get(f"/api/sessions/{sid}", headers=OWNER)).json()
            assert first_result.status_code == 200
            if kind == "omitted":
                assert second_result.status_code == 200
                assert saved["context"]["notes"] == "fresh"
                assert len(saved["turns"]) == 2
            else:
                assert second_result.status_code == 409
                assert second_result.json()["detail"]["code"] == "conversation_scope_mismatch"
                assert saved["context"]["field_conversation_key"] == "sample:alpha"
                assert len(saved["turns"]) == 1

    asyncio.run(exercise())


def test_queued_patch_cannot_rebind_a_turns_accepted_scope(tmp_path, monkeypatch):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "queued-patch.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline", allow_model_id_override=True,
    )
    app = create_app(settings)
    started, release = Event(), Event()
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *_args, **_kwargs: WaitingBackend(started, release),
    )

    async def exercise() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            created = await client.post("/api/sessions", headers=OWNER, json={"title": "Patch", "context": {}, "consent": {}})
            assert created.status_code == 200
            sid = created.json()["session_id"]
            first = asyncio.create_task(client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json={
                "message": "First question about crops?", "mode": "baseline",
                "session_context": {"field_conversation_key": "sample:alpha"},
            }))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                patch = asyncio.create_task(client.patch(f"/api/sessions/{sid}", headers=OWNER, json={
                    "context": {"field_conversation_key": "sample:beta"},
                }))
                assert (await asyncio.wait_for(client.get("/api/health"), timeout=3)).status_code == 200
                await asyncio.sleep(0.1)
                assert not patch.done()
            finally:
                release.set()
            assert (await asyncio.wait_for(first, timeout=15)).status_code == 200
            patched = await asyncio.wait_for(patch, timeout=15)
            assert patched.status_code == 409
            assert patched.json()["detail"]["code"] == "conversation_scope_mismatch"
            saved = (await client.get(f"/api/sessions/{sid}", headers=OWNER)).json()
            assert saved["context"]["field_conversation_key"] == "sample:alpha"
            assert len(saved["turns"]) == 1

    asyncio.run(exercise())


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


def test_hosted_concurrent_turns_keep_visible_pairs_and_health_responsive(tmp_path, monkeypatch):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "hosted.sqlite3", artifact_root=tmp_path / "artifacts",
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
            org = await client.post("/orgs", headers=OWNER, json={"name": "Host"})
            workspace = await client.post("/workspaces", headers=OWNER, json={"organization_id": org.json()["id"], "name": "Host"})
            wid = workspace.json()["id"]
            thread = await client.post("/threads", headers=OWNER, json={"workspace_id": wid, "title": "Host", "mode": "baseline"})
            tid = thread.json()["id"]

            def payload(message):  # noqa: ANN001, ANN202
                return {"workspace_id": wid, "thread_id": tid, "message": message, "mode": "baseline"}

            first = asyncio.create_task(client.post("/chat/stream", headers=OWNER, json=payload("First question about crops?")))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                second = asyncio.create_task(client.post("/chat/stream", headers=OWNER, json=payload("Second question about crops?")))
                health = await asyncio.wait_for(client.get("/api/health"), timeout=3)
                assert health.status_code == 200
                assert not second.done()
            finally:
                release.set()
            assert (await asyncio.wait_for(first, timeout=15)).status_code == 200
            assert (await asyncio.wait_for(second, timeout=15)).status_code == 200
            saved = await client.get(f"/threads/{tid}", headers=OWNER)
            assert saved.status_code == 200
            assert [(item["actor"], item["content"]) for item in saved.json()["messages"] if item["actor"] == "user"] == [
                ("user", "First question about crops?"), ("user", "Second question about crops?"),
            ]
            assert [item["actor"] for item in saved.json()["messages"]] == ["user", "assistant", "user", "assistant"]

    asyncio.run(exercise())


def test_cancelled_hosted_request_finishes_ordered_visible_pair(tmp_path, monkeypatch):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "hosted-cancel.sqlite3", artifact_root=tmp_path / "artifacts",
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
            org = await client.post("/orgs", headers=OWNER, json={"name": "Host"})
            workspace = await client.post("/workspaces", headers=OWNER, json={"organization_id": org.json()["id"], "name": "Host"})
            wid = workspace.json()["id"]
            thread = await client.post("/threads", headers=OWNER, json={"workspace_id": wid, "title": "Host", "mode": "baseline"})
            tid = thread.json()["id"]

            def payload(message):  # noqa: ANN001, ANN202
                return {"workspace_id": wid, "thread_id": tid, "message": message, "mode": "baseline"}

            first = asyncio.create_task(client.post("/chat/stream", headers=OWNER, json=payload("First question about crops?")))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                second = asyncio.create_task(client.post("/chat/stream", headers=OWNER, json=payload("Second question about crops?")))
                await asyncio.sleep(0.1)
                mid = await client.get(f"/threads/{tid}", headers=OWNER)
                assert [item["actor"] for item in mid.json()["messages"]] == ["user"]
                assert not second.done()
            finally:
                release.set()
            assert (await asyncio.wait_for(second, timeout=15)).status_code == 200
            saved = await client.get(f"/threads/{tid}", headers=OWNER)
            assert [item["actor"] for item in saved.json()["messages"]] == ["user", "assistant", "user", "assistant"]
            assert not app.state.hosted_turn_tasks
            assert tid not in _HOSTED_TURN_LOCKS

    asyncio.run(exercise())


def test_replay_generation_keeps_health_responsive(tmp_path, monkeypatch):  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "replay.sqlite3", artifact_root=tmp_path / "artifacts",
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
            created = await client.post("/api/sessions", headers=OWNER, json={"title": "Replay", "consent": {}, "context": {"field_conversation_key": "general"}})
            sid = created.json()["session_id"]
            original = await client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json={"message": "First question about crops?", "mode": "mock"})
            assert original.status_code == 200
            replay = asyncio.create_task(client.post("/api/replay", headers=OWNER, json={
                "base_turn_id": original.json()["turn_id"], "pipeline": "full", "mode": "baseline",
                "model_id": settings.default_model_id,
            }))
            try:
                assert await asyncio.to_thread(started.wait, 10)
                health = await asyncio.wait_for(client.get("/api/health"), timeout=3)
                assert health.status_code == 200
            finally:
                release.set()
            assert (await asyncio.wait_for(replay, timeout=15)).status_code == 200

    asyncio.run(exercise())
