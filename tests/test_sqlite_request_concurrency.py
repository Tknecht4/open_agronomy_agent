"""One TraceStore SQLite connection must not share transactions across threads."""

from __future__ import annotations

import threading
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


def test_cursor_serializes_rollback_visibility_across_threads(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "serialized.sqlite3")
    with store._cursor() as cursor:
        cursor.execute("CREATE TABLE transaction_probe (value TEXT)")
    inserted = threading.Event()
    release = threading.Event()
    reader_entered = threading.Event()
    reader_finished = threading.Event()

    def writer() -> None:
        try:
            with store._cursor() as cursor:
                cursor.execute("INSERT INTO transaction_probe(value) VALUES ('uncommitted')")
                inserted.set()
                assert release.wait(timeout=5)
                raise RuntimeError("force rollback")
        except RuntimeError as exc:
            assert str(exc) == "force rollback"

    def reader() -> int:
        reader_entered.set()
        try:
            with store._cursor() as cursor:
                return cursor.execute("SELECT COUNT(*) FROM transaction_probe").fetchone()[0]
        finally:
            reader_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer_result = pool.submit(writer)
        assert inserted.wait(timeout=5)
        reader_result = pool.submit(reader)
        try:
            assert reader_entered.wait(timeout=5)
            assert not reader_finished.wait(timeout=0.1), "reader entered another thread's open SQLite transaction"
        finally:
            release.set()
        writer_result.result(timeout=5)
        assert reader_result.result(timeout=5) == 0
    assert store._conn.execute("SELECT COUNT(*) FROM transaction_probe").fetchone()[0] == 0


def test_concurrent_auth_upserts_and_lists_use_one_user(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "auth.sqlite3")
    barrier = threading.Barrier(8)

    def request() -> str:
        barrier.wait(timeout=5)
        identities = set()
        for _ in range(16):
            user = store.upsert_phase4_user(email="Parallel@example.test", display_name="Parallel")
            identities.add(user["id"])
            assert store.list_phase4_organizations_for_user(user["id"]) == []
        assert len(identities) == 1
        return next(iter(identities))

    with ThreadPoolExecutor(max_workers=8) as pool:
        identities = list(pool.map(lambda _: request(), range(8)))
    assert len(set(identities)) == 1
    assert store._conn.execute("SELECT COUNT(*) FROM phase4_users WHERE email = 'parallel@example.test'").fetchone()[0] == 1


def test_nested_getters_leave_outer_write_uncommitted(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "nested.sqlite3")
    session = store.create_session("Nested", {}, {})
    turn_id = store.create_turn(
        session["session_id"], "Question", "Answer", parent_turn_id=None,
        system_state={"mode": "mock"}, trace={}, objectives={}, event_stream=False,
    )
    with store._cursor() as cursor:
        cursor.execute("CREATE TABLE transaction_probe (value TEXT)")
    with pytest.raises(RuntimeError, match="outer rollback"):
        with store._cursor() as cursor:
            cursor.execute("INSERT INTO transaction_probe(value) VALUES ('pending')")
            assert store.get_session(session["session_id"])["session_id"] == session["session_id"]
            assert store.get_turn(turn_id)["turn_id"] == turn_id
            raise RuntimeError("outer rollback")
    assert store._conn.execute("SELECT COUNT(*) FROM transaction_probe").fetchone()[0] == 0


def test_swallowed_nested_failure_refuses_outer_commit(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "nested-failure.sqlite3")
    with store._cursor() as cursor:
        cursor.execute("CREATE TABLE transaction_probe (value TEXT)")
    with pytest.raises(RuntimeError, match="nested cursor failure"):
        with store._cursor() as cursor:
            cursor.execute("INSERT INTO transaction_probe(value) VALUES ('pending')")
            try:
                with store._cursor() as nested:
                    nested.execute("INSERT INTO no_such_table(value) VALUES ('failure')")
            except sqlite3.OperationalError:
                pass
    assert store._conn.execute("SELECT COUNT(*) FROM transaction_probe").fetchone()[0] == 0


def test_failed_outer_commit_rolls_back_before_reuse(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "deferred-fk.sqlite3")
    with store._cursor() as cursor:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        cursor.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
    with pytest.raises(sqlite3.IntegrityError):
        with store._cursor() as cursor:
            cursor.execute("INSERT INTO child(parent_id) VALUES (999)")
    assert store._conn.in_transaction is False
    with store._cursor() as cursor:
        assert cursor.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0
        cursor.execute("INSERT INTO parent(id) VALUES (1)")


def test_parallel_http_field_data_history_and_imagery_readiness(tmp_path: Path) -> None:
    settings = build_settings(
        db_path=tmp_path / "mixed-http.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline",
    )
    with TestClient(create_app(settings)) as client:
        headers = {"X-Agronomy-User-Email": "shared-owner@example.test"}
        created = client.post("/api/demo/fields", headers=headers, json={
            "name": "Mixed requests", "field": {"region": "Alberta"}, "geometry": {"kind": "none"},
        })
        assert created.status_code == 201, created.text
        field_id = created.json()["field"]["field_context_id"]
        paths = [
            f"/api/demo/fields/{field_id}/data",
            f"/api/demo/fields/{field_id}/history",
            f"/api/demo/fields/{field_id}/imagery/analytics",
        ]

        def request(index: int) -> int:
            response = client.get(paths[index % len(paths)], headers=headers)
            return response.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(request, range(48)))
        assert statuses == [200] * 48


def test_concurrent_personal_workspace_creation_is_single_transaction(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "personal.sqlite3")
    user_id = store.upsert_phase4_user(email="personal@example.test")["id"]
    barrier = threading.Barrier(8)

    def ensure() -> None:
        barrier.wait(timeout=5)
        store.ensure_personal_workspace(user_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: ensure(), range(8)))
    workspaces = store.list_phase4_workspaces_for_user(user_id)
    assert len(workspaces) == 1
    assert len(store.list_phase4_organizations_for_user(user_id)) == 1


def test_failed_personal_workspace_creation_rolls_back_organization(tmp_path: Path, monkeypatch) -> None:
    store = TraceStore(tmp_path / "personal-failure.sqlite3")
    user_id = store.upsert_phase4_user(email="personal@example.test")["id"]
    original_create = store.create_phase4_workspace

    def fail_workspace(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("workspace creation failed")

    monkeypatch.setattr(store, "create_phase4_workspace", fail_workspace)
    with pytest.raises(RuntimeError, match="workspace creation failed"):
        store.ensure_personal_workspace(user_id)
    assert store.list_phase4_organizations_for_user(user_id) == []
    assert store.list_phase4_workspaces_for_user(user_id) == []
    monkeypatch.setattr(store, "create_phase4_workspace", original_create)
    store.ensure_personal_workspace(user_id)
    assert len(store.list_phase4_workspaces_for_user(user_id)) == 1
