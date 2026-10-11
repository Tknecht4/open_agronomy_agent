from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.backup import create_backup, restore_backup


OWNER = {"X-Agronomy-User-Email": "retry-owner@example.test"}
OUTSIDER = {"X-Agronomy-User-Email": "retry-outsider@example.test"}


def runtime(tmp_path):
    settings = build_settings(db_path=tmp_path / "retry.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")
    return TestClient(create_app(settings)), settings


def field(client):
    response = client.post("/api/demo/fields", headers=OWNER, json={"name": "Retry field", "field": {}, "geometry": {"kind": "none"}})
    assert response.status_code == 201, response.text
    return response.json()["field"]["field_context_id"]


def payload(operation_id=None):
    return {"event_type": "observation", "payload": {"summary": "Scouted north edge"},
            **({"client_operation_id": operation_id} if operation_id else {})}


def test_response_loss_retry_and_restart_return_one_durable_event(tmp_path):
    client, settings = runtime(tmp_path)
    field_id = field(client)
    path = f"/api/demo/fields/{field_id}/events"
    request = payload(str(uuid4()))
    # Simulate acknowledgement loss: the accepted first response is ignored by
    # the client, which resubmits the original durable operation identifier.
    first = client.post(path, headers=OWNER, json=request)
    assert first.status_code == 201, first.text
    retry = client.post(path, headers=OWNER, json=request)
    assert retry.status_code == 201, retry.text
    assert retry.json()["event"]["id"] == first.json()["event"]["id"]
    client.close()
    reopened = TestClient(create_app(settings))
    after_restart = reopened.post(path, headers=OWNER, json=request)
    assert after_restart.json()["event"] == first.json()["event"]
    history = reopened.get(path, headers=OWNER).json()
    assert history["event_count"] == 1
    assert history["chain"]["valid"] is True
    reopened.close()


def test_distinct_ids_and_legacy_requests_preserve_legitimate_identical_saves(tmp_path):
    client, _ = runtime(tmp_path)
    path = f"/api/demo/fields/{field(client)}/events"
    responses = [client.post(path, headers=OWNER, json=payload(str(uuid4()))) for _ in range(2)]
    responses += [client.post(path, headers=OWNER, json=payload()) for _ in range(2)]
    assert len({response.json()["event"]["id"] for response in responses}) == 4
    assert client.get(path, headers=OWNER).json()["event_count"] == 4
    client.close()


def test_conflicting_reuse_and_cross_field_scope_do_not_mutate_history(tmp_path):
    client, _ = runtime(tmp_path)
    first_field, other_field = field(client), field(client)
    request = payload(str(uuid4()))
    path = f"/api/demo/fields/{first_field}/events"
    accepted = client.post(path, headers=OWNER, json=request)
    changed = {**request, "payload": {"summary": "Changed contents"}}
    conflict = client.post(path, headers=OWNER, json=changed)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "field_event_operation_conflict"
    wrong_field = client.post(f"/api/demo/fields/{other_field}/events", headers=OWNER, json=request)
    assert wrong_field.status_code == 409, wrong_field.text
    assert client.get(path, headers=OWNER).json()["events"] == [accepted.json()["event"]]
    assert client.get(f"/api/demo/fields/{other_field}/events", headers=OWNER).json()["event_count"] == 0
    client.close()


def test_authorization_precedes_receipt_lookup_even_for_a_known_operation(tmp_path):
    client, _ = runtime(tmp_path)
    field_id = field(client)
    path = f"/api/demo/fields/{field_id}/events"
    request = payload(str(uuid4()))
    assert client.post(path, headers=OWNER, json=request).status_code == 201
    assert client.post(path, headers=OUTSIDER, json=request).status_code == 403
    assert client.post(path, headers=OWNER, json={**request, "client_operation_id": "invalid"}).status_code == 422
    assert client.get(path, headers=OWNER).json()["event_count"] == 1
    assert client.delete(f"/api/demo/fields/{field_id}", headers=OWNER).status_code == 200
    assert client.post(path, headers=OWNER, json=request).status_code == 404
    client.close()


def test_independent_sqlite_handles_serialize_operation_and_event_receipt(tmp_path):
    database = tmp_path / "writers.sqlite3"
    store = TraceStore(database)
    field_record = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="actor", payload={"display_name": "Field", "region_text": ""})
    stores = [TraceStore(database) for _ in range(2)]
    request = payload(str(uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda candidate: candidate.append_phase4_field_event(field_context=field_record, recorded_by_user_id="actor", payload=request), stores))
    assert results[0]["id"] == results[1]["id"]
    assert len(store.list_phase4_field_events(field_record["id"])) == 1
    assert store.verify_phase4_field_event_chain(field_record["id"])["valid"]
    for handle in [store, *stores]:
        handle._conn.close()


def test_hosted_and_workspace_routes_share_the_same_operation_receipt(tmp_path):
    client, _ = runtime(tmp_path)
    field_id = field(client)
    request = payload(str(uuid4()))
    first = client.post(f"/api/demo/fields/{field_id}/events", headers=OWNER, json=request)
    retry = client.post(f"/field-contexts/{field_id}/events", headers=OWNER, json=request)
    assert retry.status_code == 201, retry.text
    assert retry.json()["event"] == first.json()["event"]
    changed = {**request, "provenance": {"capture_method": "changed"}}
    assert client.post(f"/field-contexts/{field_id}/events", headers=OWNER, json=changed).status_code == 409
    assert client.post(f"/field-contexts/{field_id}/events", headers=OUTSIDER, json=request).status_code == 403
    client.close()


def test_operation_mapping_failure_rolls_back_event_and_audit_before_retry(tmp_path):
    store = TraceStore(tmp_path / "atomic.sqlite3")
    record = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="actor", payload={"display_name": "Field", "region_text": ""})
    request = payload(str(uuid4()))
    with store._cursor() as cursor:
        cursor.execute("""CREATE TRIGGER synthetic_operation_failure BEFORE INSERT ON phase4_field_event_operations
                          BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic receipt failure"):
        store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request)
    assert store.list_phase4_field_events(record["id"]) == []
    with store._cursor() as cursor:
        assert cursor.execute("SELECT COUNT(*) FROM phase4_field_event_operations").fetchone()[0] == 0
        assert cursor.execute("SELECT COUNT(*) FROM phase4_audit_events WHERE event_type = 'field_event.appended'").fetchone()[0] == 0
        cursor.execute("DROP TRIGGER synthetic_operation_failure")
    accepted = store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request)
    assert store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request) == accepted
    with store._cursor() as cursor:
        assert cursor.execute("SELECT COUNT(*) FROM phase4_field_event_operations").fetchone()[0] == 1
        assert cursor.execute("SELECT COUNT(*) FROM phase4_audit_events WHERE event_type = 'field_event.appended'").fetchone()[0] == 1
    store._conn.close()


def test_operation_identifiers_are_actor_scoped(tmp_path):
    store = TraceStore(tmp_path / "actors.sqlite3")
    record = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="actor", payload={"display_name": "Field", "region_text": ""})
    request = payload(str(uuid4()))
    first = store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request)
    second = store.append_phase4_field_event(field_context=record, recorded_by_user_id="other-actor", payload=request)
    assert first["id"] != second["id"]
    assert store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request) == first
    assert store.append_phase4_field_event(field_context=record, recorded_by_user_id="other-actor", payload=request) == second
    assert store.verify_phase4_field_event_chain(record["id"])["valid"]
    store._conn.close()


def test_existing_database_startup_adds_receipts_without_rewriting_events(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    store = TraceStore(database)
    record = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="actor", payload={"display_name": "Field", "region_text": ""})
    original = store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=payload())
    # Build an older-schema fixture, with no receipt table, from this test's DB.
    with store._cursor() as cursor:
        cursor.execute("DROP TABLE phase4_field_event_operations")
    store._conn.close()
    migrated = TraceStore(database)
    assert migrated.get_phase4_field_event(original["id"]) == original
    request = payload(str(uuid4()))
    accepted = migrated.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request)
    assert migrated.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request) == accepted
    assert len(migrated.list_phase4_field_events(record["id"])) == 2
    assert migrated.verify_phase4_field_event_chain(record["id"])["valid"]
    migrated._conn.close()


def test_backup_restore_retains_the_event_and_its_retry_receipt(tmp_path):
    database = tmp_path / "original.sqlite3"
    artifacts = tmp_path / "original-artifacts"
    artifacts.mkdir()
    store = TraceStore(database)
    record = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="actor", payload={"display_name": "Field", "region_text": ""})
    request = payload(str(uuid4()))
    accepted = store.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request)
    store._conn.close()
    backup = create_backup(db_path=database, artifact_root=artifacts, backup_root=tmp_path / "backups")
    restored_path = tmp_path / "restored.sqlite3"
    restore_backup(backup_dir=backup.backup_dir, target_db_path=restored_path, target_artifact_root=tmp_path / "restored-artifacts")
    restored = TraceStore(restored_path)
    assert restored.append_phase4_field_event(field_context=record, recorded_by_user_id="actor", payload=request) == accepted
    assert len(restored.list_phase4_field_events(record["id"])) == 1
    assert restored.verify_phase4_field_event_chain(record["id"])["valid"]
    restored._conn.close()


def test_unsupported_storage_rejects_idempotency_instead_of_ignoring_it(tmp_path, monkeypatch):
    client, _ = runtime(tmp_path)
    field_id = field(client)
    monkeypatch.setattr(client.app.state.trace_store, "backend", "postgres", raising=False)
    for prefix in ["/api/demo/fields", "/field-contexts"]:
        response = client.post(f"{prefix}/{field_id}/events", headers=OWNER, json=payload(str(uuid4())))
        assert response.status_code == 501, response.text
        assert response.json()["detail"]["code"] == "field_event_idempotency_unavailable"
    assert client.get(f"/api/demo/fields/{field_id}/events", headers=OWNER).json()["event_count"] == 0
    client.close()


def test_scope_handshake_and_receipt_bind_actor_workspace_field_and_protocol(tmp_path):
    client, _ = runtime(tmp_path)
    field_id = field(client)
    scope = client.get(f"/api/demo/fields/{field_id}/events/operation-scope", headers=OWNER).json()
    request = {**payload(str(uuid4())), "expected_actor_user_id": scope["actor_user_id"],
               "expected_workspace_id": scope["workspace_id"], "expected_operation_protocol": scope["protocol"]}
    first = client.post(f"/api/demo/fields/{field_id}/events", headers=OWNER, json=request)
    assert first.status_code == 201
    receipt = first.json()["operation"]
    assert receipt == {**scope, "operation_id": request["client_operation_id"], "event_id": first.json()["event"]["id"]}
    retry = client.post(f"/field-contexts/{field_id}/events", headers=OWNER, json=request)
    assert retry.json()["operation"] == receipt
    assert retry.json()["event"] == first.json()["event"]
    assert client.get(f"/api/demo/fields/{field_id}/events/operation-scope", headers=OUTSIDER).status_code == 403
    client.close()


def test_authorized_actor_change_between_scope_read_and_post_cannot_replay(tmp_path):
    client, _ = runtime(tmp_path)
    field_id = field(client)
    record = client.get(f"/field-contexts/{field_id}", headers=OWNER).json()
    assert client.post(f"/orgs/{record['organization_id']}/memberships", headers=OWNER,
                       json={"email": OUTSIDER["X-Agronomy-User-Email"], "display_name": "Other adviser", "role": "adviser"}).status_code == 201
    scope = client.get(f"/api/demo/fields/{field_id}/events/operation-scope", headers=OWNER).json()
    request = {**payload(str(uuid4())), "expected_actor_user_id": scope["actor_user_id"],
               "expected_workspace_id": scope["workspace_id"], "expected_operation_protocol": scope["protocol"]}
    accepted = client.post(f"/api/demo/fields/{field_id}/events", headers=OWNER, json=request)
    for prefix in ["/api/demo/fields", "/field-contexts"]:
        changed = client.post(f"{prefix}/{field_id}/events", headers=OUTSIDER, json=request)
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "field_event_actor_changed"
    assert client.get(f"/api/demo/fields/{field_id}/events", headers=OWNER).json()["events"] == [accepted.json()["event"]]
    client.close()


@pytest.mark.parametrize("changed,code", [({"expected_workspace_id": str(uuid4())}, "field_event_workspace_changed"),
                                           ({"expected_operation_protocol": "old-or-new-unsupported"}, "field_event_protocol_changed"),
                                           ({"expected_actor_user_id": None}, "field_event_scope_required")])
def test_incomplete_or_changed_scope_does_not_append(tmp_path, changed, code):
    client, _ = runtime(tmp_path)
    field_id = field(client)
    scope = client.get(f"/api/demo/fields/{field_id}/events/operation-scope", headers=OWNER).json()
    request = {**payload(str(uuid4())), "expected_actor_user_id": scope["actor_user_id"],
               "expected_workspace_id": scope["workspace_id"], "expected_operation_protocol": scope["protocol"], **changed}
    response = client.post(f"/api/demo/fields/{field_id}/events", headers=OWNER, json=request)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert client.get(f"/api/demo/fields/{field_id}/events", headers=OWNER).json()["event_count"] == 0
    client.close()
