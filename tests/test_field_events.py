from __future__ import annotations

import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.field_events import (
    field_event_integrity_sha256,
    validate_field_event_fast_forward,
    verify_field_event_chain,
)
from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


USER_A = {
    "X-Agronomy-User-Email": "advisor@example.test",
    "X-Agronomy-User-Name": "Advisor One",
}
USER_B = {
    "X-Agronomy-User-Email": "outsider@example.test",
    "X-Agronomy-User-Name": "Outsider",
}


def _field(store: TraceStore, *, workspace_id: str = "workspace-1") -> dict[str, object]:
    return store.create_phase4_field_context(
        workspace={"id": workspace_id, "organization_id": "organization-1"},
        created_by_user_id="user-1",
        payload={
            "display_name": f"Field {workspace_id}",
            "region_text": "Saskatchewan",
            "crop_current": "canola",
        },
    )


def test_sqlite_field_events_are_hash_chained_append_only_and_corrected_by_reference(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "events.sqlite3")
    field = _field(store)

    observation = store.append_phase4_field_event(
        field_context=field,
        recorded_by_user_id="user-1",
        payload={
            "event_type": "observation",
            "occurred_at": "2026-07-20T14:00:00+00:00",
            "payload": {"summary": "Water ponding in the northwest corner"},
            "provenance": {"capture_method": "farmer_observation"},
        },
    )
    operation = store.append_phase4_field_event(
        field_context=field,
        recorded_by_user_id="user-1",
        payload={
            "event_type": "operation",
            "occurred_at": "2026-07-21T14:00:00+00:00",
            "payload": {"summary": "Seeded canola", "rate": "5 lb/ac"},
        },
    )
    correction = store.append_phase4_field_event(
        field_context=field,
        recorded_by_user_id="user-1",
        payload={
            "event_type": "correction",
            "corrects_event_id": operation["id"],
            "payload": {
                "reason": "Rate entered from the wrong monitor screen",
                "replacement": {"rate": "4.7 lb/ac"},
            },
        },
    )

    events = store.list_phase4_field_events(str(field["id"]))
    assert [event["event_type"] for event in events] == ["observation", "operation", "correction"]
    assert operation["previous_event_sha256"] == observation["integrity_sha256"]
    assert correction["previous_event_sha256"] == operation["integrity_sha256"]
    assert correction["corrects_event_id"] == operation["id"]
    assert store.verify_phase4_field_event_chain(str(field["id"])) == {
        "schema_version": "open_agronomy_agent.field_event_chain.v1",
        "valid": True,
        "event_count": 3,
        "head_sha256": correction["integrity_sha256"],
        "failure_count": 0,
        "failures": [],
    }

    tampered = [dict(event) for event in events]
    tampered[1]["payload"] = {"summary": "silently altered"}
    assert verify_field_event_chain(tampered)["valid"] is False

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with store._cursor() as cursor:
            cursor.execute(
                "UPDATE phase4_field_events SET event_type = 'note' WHERE id = ?",
                (observation["id"],),
            )


def test_field_event_correction_cannot_cross_field_boundary(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "events.sqlite3")
    first_field = _field(store, workspace_id="workspace-1")
    second_field = _field(store, workspace_id="workspace-2")
    event = store.append_phase4_field_event(
        field_context=first_field,
        recorded_by_user_id="user-1",
        payload={"event_type": "note", "payload": {"summary": "First field only"}},
    )

    with pytest.raises(ValueError, match="does not exist in this field"):
        store.append_phase4_field_event(
            field_context=second_field,
            recorded_by_user_id="user-1",
            payload={
                "event_type": "correction",
                "corrects_event_id": event["id"],
                "payload": {"reason": "must not cross fields"},
            },
        )


def test_field_event_chain_serializes_independent_sqlite_writers(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent-events.sqlite3"
    first_store = TraceStore(db_path)
    second_store = TraceStore(db_path)
    field = _field(first_store)
    barrier = threading.Barrier(2)

    def append(store: TraceStore, summary: str) -> dict[str, object]:
        barrier.wait(timeout=5)
        return store.append_phase4_field_event(
            field_context=field,
            recorded_by_user_id="user-1",
            payload={
                "event_type": "observation",
                "payload": {"summary": summary},
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(append, first_store, "Writer one"),
            executor.submit(append, second_store, "Writer two"),
        ]
        results = [future.result(timeout=10) for future in futures]

    events = first_store.list_phase4_field_events(str(field["id"]))
    chain = first_store.verify_phase4_field_event_chain(str(field["id"]))
    assert len(results) == 2
    assert len(events) == 2
    assert chain["valid"] is True
    assert {event["payload"]["summary"] for event in events} == {"Writer one", "Writer two"}
    assert events[1]["previous_event_sha256"] == events[0]["integrity_sha256"]


def test_full_branch_export_can_fast_forward_an_identical_local_prefix(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "prefix-sync.sqlite3")
    field = _field(store)
    base = store.append_phase4_field_event(
        field_context=field,
        recorded_by_user_id="user-1",
        payload={
            "event_type": "observation",
            "payload": {"summary": "Shared base"},
        },
    )
    recorded_at = (datetime.fromisoformat(base["recorded_at"]) + timedelta(seconds=1)).isoformat()
    suffix = {
        **base,
        "id": str(uuid.uuid4()),
        "event_type": "note",
        "occurred_at": recorded_at,
        "payload": {"summary": "New offline suffix"},
        "provenance": {"capture_method": "offline_field_device"},
        "corrects_event_id": None,
        "previous_event_sha256": base["integrity_sha256"],
        "recorded_at": recorded_at,
    }
    suffix["integrity_sha256"] = field_event_integrity_sha256(suffix)

    validation = validate_field_event_fast_forward(
        local_events=[base],
        incoming_events=[base, suffix],
        field_context=field,
        syncing_user_id="user-1",
        base_head_sha256=None,
    )
    assert validation["status"] == "ready"
    assert validation["accepted_full_prefix"] is True
    assert validation["events"] == [suffix]
    assert validation["event_count"] == 1


def test_hosted_field_event_api_enforces_workspace_access_and_returns_chain_state(tmp_path: Path) -> None:
    settings = build_settings(db_path=tmp_path / "api.sqlite3", artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(settings))
    organization = client.post("/orgs", headers=USER_A, json={"name": "Field history org"}).json()
    workspace = client.post(
        "/workspaces",
        headers=USER_A,
        json={"organization_id": organization["id"], "name": "Field history workspace"},
    ).json()
    field = client.post(
        "/field-contexts",
        headers=USER_A,
        json={
            "workspace_id": workspace["id"],
            "display_name": "North quarter",
            "region_text": "Saskatchewan",
            "crop_current": "canola",
        },
    ).json()

    appended = client.post(
        f"/field-contexts/{field['id']}/events",
        headers=USER_A,
        json={
            "event_type": "sample",
            "occurred_at": "2026-07-20T08:30:00-06:00",
            "payload": {"summary": "0-6 inch composite soil sample", "sample_id": "NQ-2026-01"},
            "provenance": {"recorded_from": "paper_lab_submission"},
        },
    )
    assert appended.status_code == 201
    assert appended.json()["chain"]["valid"] is True
    assert appended.json()["event"]["integrity_sha256"]

    listed = client.get(f"/field-contexts/{field['id']}/events", headers=USER_A)
    assert listed.status_code == 200
    assert listed.json()["event_count"] == 1
    assert listed.json()["chain"]["failure_count"] == 0
    assert "append-only" in listed.json()["boundary"]

    denied_read = client.get(f"/field-contexts/{field['id']}/events", headers=USER_B)
    assert denied_read.status_code == 403
    denied_write = client.post(
        f"/field-contexts/{field['id']}/events",
        headers=USER_B,
        json={"event_type": "note", "payload": {"summary": "unauthorized"}},
    )
    assert denied_write.status_code == 403

    invalid_correction = client.post(
        f"/field-contexts/{field['id']}/events",
        headers=USER_A,
        json={"event_type": "correction", "payload": {"reason": "missing target"}},
    )
    assert invalid_correction.status_code == 422


def test_field_event_api_validates_typed_soil_measurement_contract(tmp_path: Path) -> None:
    settings = build_settings(
        db_path=tmp_path / "typed-measurement.sqlite3",
        artifact_root=tmp_path / "artifacts",
    )
    client = TestClient(create_app(settings))
    organization = client.post(
        "/orgs",
        headers=USER_A,
        json={"name": "Measurement org"},
    ).json()
    workspace = client.post(
        "/workspaces",
        headers=USER_A,
        json={
            "organization_id": organization["id"],
            "name": "Measurement workspace",
        },
    ).json()
    field = client.post(
        "/field-contexts",
        headers=USER_A,
        json={
            "workspace_id": workspace["id"],
            "display_name": "North quarter",
            "region_text": "Saskatchewan",
            "crop_current": "canola",
        },
    ).json()
    measurement = {
        "schema_version": "open_agronomy_agent.field_measurement.v1",
        "kind": "soil_test",
        "sample_id": "NQ-2026-01",
        "metric": "soil_ph",
        "label": "Soil pH",
        "value": 6.4,
        "unit": "pH",
        "method": "1:1 water",
        "sample_depth": {"top": 0, "bottom": 15, "unit": "cm"},
        "spatial_scope": "composite",
        "source_quality": "user_transcribed_lab_report",
        "lab_name": "Example Lab",
    }

    created = client.post(
        f"/field-contexts/{field['id']}/events",
        headers=USER_A,
        json={
            "event_type": "sample",
            "payload": {
                "summary": "Soil-test result transcribed from the lab report",
                "measurement": measurement,
            },
            "provenance": {
                "capture_method": "user_transcribed",
                "original_report_retained": True,
            },
        },
    )

    assert created.status_code == 201
    assert created.json()["event"]["payload"]["measurement"] == measurement
    assert created.json()["chain"]["valid"] is True

    invalid = dict(measurement)
    invalid.pop("method")
    rejected = client.post(
        f"/field-contexts/{field['id']}/events",
        headers=USER_A,
        json={
            "event_type": "sample",
            "payload": {"measurement": invalid},
        },
    )
    assert rejected.status_code == 422
    assert "measurement is missing required fields: method" in rejected.text


def test_field_event_sync_is_atomic_idempotent_and_refuses_divergent_histories(tmp_path: Path) -> None:
    settings = build_settings(db_path=tmp_path / "sync.sqlite3", artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(settings))
    organization = client.post("/orgs", headers=USER_A, json={"name": "Sync org"}).json()
    workspace = client.post(
        "/workspaces",
        headers=USER_A,
        json={"organization_id": organization["id"], "name": "Sync workspace"},
    ).json()
    field = client.post(
        "/field-contexts",
        headers=USER_A,
        json={
            "workspace_id": workspace["id"],
            "display_name": "North quarter",
            "region_text": "Saskatchewan",
            "crop_current": "canola",
        },
    ).json()
    other_field = client.post(
        "/field-contexts",
        headers=USER_A,
        json={
            "workspace_id": workspace["id"],
            "display_name": "South quarter",
            "region_text": "Saskatchewan",
            "crop_current": "wheat",
        },
    ).json()
    base = client.post(
        f"/field-contexts/{field['id']}/events",
        headers=USER_A,
        json={
            "event_type": "observation",
            "payload": {"summary": "Base observation"},
        },
    ).json()["event"]

    full_export = client.get(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
    )
    assert full_export.status_code == 200
    assert full_export.json()["events"] == [base]
    incremental_export = client.get(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        params={"after_sha256": base["integrity_sha256"]},
    )
    assert incremental_export.status_code == 200
    assert incremental_export.json()["events"] == []

    recorded_at = (datetime.fromisoformat(base["recorded_at"]) + timedelta(seconds=1)).isoformat()
    incoming = {
        "schema_version": "open_agronomy_agent.field_event.v1",
        "id": str(uuid.uuid4()),
        "organization_id": base["organization_id"],
        "workspace_id": base["workspace_id"],
        "field_context_id": base["field_context_id"],
        "recorded_by_user_id": base["recorded_by_user_id"],
        "event_type": "note",
        "occurred_at": recorded_at,
        "payload": {"summary": "Offline scouting note"},
        "provenance": {"capture_method": "offline_field_device"},
        "corrects_event_id": None,
        "previous_event_sha256": base["integrity_sha256"],
        "recorded_at": recorded_at,
    }
    incoming["integrity_sha256"] = field_event_integrity_sha256(incoming)
    envelope = {
        "schema_version": "open_agronomy_agent.field_event_sync.v1",
        "source_device_id": "field-phone-1",
        "base_head_sha256": base["integrity_sha256"],
        "events": [incoming],
    }
    imported = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json=envelope,
    )
    assert imported.status_code == 200
    assert imported.json()["status"] == "imported"
    assert imported.json()["imported_event_count"] == 1
    assert imported.json()["chain"]["valid"] is True
    assert "not device attestation" in imported.json()["boundary"]
    audit = client.get(
        "/admin/audit-events",
        headers=USER_A,
        params={
            "workspace_id": workspace["id"],
            "event_type": "field_event.sync_imported",
        },
    )
    assert audit.status_code == 200
    assert audit.json()[0]["payload"]["source_device_id"] == "field-phone-1"
    assert audit.json()[0]["payload"]["imported_event_count"] == 1

    retried = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json=envelope,
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "already_applied"
    assert retried.json()["imported_event_count"] == 0

    divergent = dict(incoming)
    divergent["id"] = str(uuid.uuid4())
    divergent["payload"] = {"summary": "Conflicting offline branch"}
    divergent["recorded_at"] = (
        datetime.fromisoformat(incoming["recorded_at"]) + timedelta(seconds=1)
    ).isoformat()
    divergent["occurred_at"] = divergent["recorded_at"]
    divergent["integrity_sha256"] = field_event_integrity_sha256(divergent)
    conflict = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={**envelope, "events": [divergent]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "divergent_head"
    assert "never silently merged" in conflict.json()["detail"]["boundary"]

    cross_field = dict(divergent)
    cross_field["id"] = str(uuid.uuid4())
    cross_field["field_context_id"] = other_field["id"]
    cross_field["integrity_sha256"] = field_event_integrity_sha256(cross_field)
    rejected_scope = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={**envelope, "events": [cross_field]},
    )
    assert rejected_scope.status_code == 422
    assert rejected_scope.json()["detail"]["code"] == "field_context_id_mismatch"

    collision = dict(incoming)
    collision["payload"] = {"summary": "Different content under an existing id"}
    collision["integrity_sha256"] = field_event_integrity_sha256(collision)
    rejected_collision = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={**envelope, "events": [collision]},
    )
    assert rejected_collision.status_code == 409
    assert rejected_collision.json()["detail"]["code"] == "event_id_collision"

    descendant = dict(divergent)
    descendant["id"] = str(uuid.uuid4())
    descendant["previous_event_sha256"] = incoming["integrity_sha256"]
    descendant["payload"] = {"summary": "New descendant after the imported event"}
    descendant["integrity_sha256"] = field_event_integrity_sha256(descendant)
    partial_overlap = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={
            **envelope,
            "base_head_sha256": base["integrity_sha256"],
            "events": [incoming, descendant],
        },
    )
    assert partial_overlap.status_code == 409
    assert partial_overlap.json()["detail"]["code"] == "partial_overlap"

    valid_next = dict(descendant)
    valid_next["id"] = str(uuid.uuid4())
    valid_next["recorded_at"] = (
        datetime.fromisoformat(incoming["recorded_at"]) + timedelta(seconds=2)
    ).isoformat()
    valid_next["occurred_at"] = valid_next["recorded_at"]
    valid_next["integrity_sha256"] = field_event_integrity_sha256(valid_next)
    invalid_second = dict(valid_next)
    invalid_second["id"] = str(uuid.uuid4())
    invalid_second["previous_event_sha256"] = "0" * 64
    invalid_second["recorded_at"] = (
        datetime.fromisoformat(valid_next["recorded_at"]) + timedelta(seconds=1)
    ).isoformat()
    invalid_second["occurred_at"] = invalid_second["recorded_at"]
    invalid_second["integrity_sha256"] = field_event_integrity_sha256(invalid_second)
    rejected_batch = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={
            **envelope,
            "base_head_sha256": incoming["integrity_sha256"],
            "events": [valid_next, invalid_second],
        },
    )
    assert rejected_batch.status_code == 422
    assert rejected_batch.json()["detail"]["code"] == "previous_event_sha256_mismatch"

    invalid_correction = dict(valid_next)
    invalid_correction["id"] = str(uuid.uuid4())
    invalid_correction["event_type"] = "correction"
    invalid_correction["corrects_event_id"] = str(uuid.uuid4())
    invalid_correction["integrity_sha256"] = field_event_integrity_sha256(invalid_correction)
    rejected_correction = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={
            **envelope,
            "base_head_sha256": incoming["integrity_sha256"],
            "events": [invalid_correction],
        },
    )
    assert rejected_correction.status_code == 422
    assert rejected_correction.json()["detail"]["code"] == "unknown_correction_target"

    cross_user = dict(valid_next)
    cross_user["id"] = str(uuid.uuid4())
    cross_user["recorded_by_user_id"] = str(uuid.uuid4())
    cross_user["integrity_sha256"] = field_event_integrity_sha256(cross_user)
    rejected_user = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        json={
            **envelope,
            "base_head_sha256": incoming["integrity_sha256"],
            "events": [cross_user],
        },
    )
    assert rejected_user.status_code == 422
    assert rejected_user.json()["detail"]["code"] == "recorded_by_user_id_mismatch"

    unknown_export = client.get(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_A,
        params={"after_sha256": "0" * 64},
    )
    assert unknown_export.status_code == 409
    assert unknown_export.json()["detail"]["code"] == "unknown_base_head"

    denied = client.post(
        f"/field-contexts/{field['id']}/events/sync",
        headers=USER_B,
        json=envelope,
    )
    assert denied.status_code == 403

    listed = client.get(f"/field-contexts/{field['id']}/events", headers=USER_A).json()
    assert listed["event_count"] == 2
    assert listed["chain"]["valid"] is True
