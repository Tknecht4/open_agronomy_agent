from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


OWNER = {
    "X-Agronomy-User-Email": "field-owner@example.test",
    "X-Agronomy-User-Name": "Field Owner",
}
OUTSIDER = {
    "X-Agronomy-User-Email": "field-outsider@example.test",
    "X-Agronomy-User-Name": "Field Outsider",
}


def _field_payload(*, name: str = "North quarter", crop: str = "canola") -> dict[str, object]:
    return {
        "name": name,
        "field": {
            "crop": crop,
            "region": "Leduc County",
            "jurisdiction": "Alberta",
            "acres": "160",
            "concern": "Uneven early growth",
            "notes": "Compare normal and weak areas.",
        },
        "geometry": {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}},
        "regionalContext": "Alberta local soil context",
        "geoPriors": {"regional_intersections": []},
        "sourceBoundary": "Map context is a prior, not field truth.",
    }


def test_demo_field_library_creates_updates_and_lists_distinct_workspace_fields(tmp_path: Path) -> None:
    settings = build_settings(db_path=tmp_path / "field-library.sqlite3", artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(settings))

    created = client.post("/api/demo/fields", headers=OWNER, json=_field_payload())
    assert created.status_code == 201
    first = created.json()["field"]
    assert first["name"] == "North quarter"
    first_snapshot = first["fieldRevision"]["snapshot_sha256"]

    updated_payload = _field_payload(name="North quarter west", crop="barley")
    updated = client.patch(f"/api/demo/fields/{first['field_context_id']}", headers=OWNER, json=updated_payload)
    assert updated.status_code == 200
    field = updated.json()["field"]
    assert field["id"] == first["id"]
    assert field["field_context_id"] == first["field_context_id"]
    assert field["name"] == "North quarter west"
    assert field["crop"] == "barley"
    assert field["updatedAt"] >= field["createdAt"]
    assert field["fieldRevision"]["update_kind"] == "updated"
    assert field["fieldRevision"]["previous_snapshot_sha256"] == first_snapshot
    assert field["fieldRevision"]["snapshot_sha256"] != first_snapshot

    copied = client.post("/api/demo/fields", headers=OWNER, json=_field_payload(name="North quarter east"))
    assert copied.status_code == 201

    listed = client.get("/api/demo/fields", headers=OWNER)
    assert listed.status_code == 200
    fields = listed.json()["fields"]
    assert {item["name"] for item in fields} == {"North quarter west", "North quarter east"}
    assert {item["id"] for item in fields} == {first["id"], copied.json()["field"]["id"]}
    assert listed.json()["storage"]["mode"] == "account_workspace"


def test_demo_field_library_update_is_workspace_authorized(tmp_path: Path) -> None:
    settings = build_settings(db_path=tmp_path / "field-library-auth.sqlite3", artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(settings))
    created = client.post("/api/demo/fields", headers=OWNER, json=_field_payload())
    field_id = created.json()["field"]["field_context_id"]

    denied = client.patch(f"/api/demo/fields/{field_id}", headers=OUTSIDER, json=_field_payload(name="Do not rename"))
    assert denied.status_code == 403

    persisted = client.get("/api/demo/fields", headers=OWNER).json()["fields"]
    assert persisted[0]["name"] == "North quarter"


def test_explicit_unknown_field_details_remain_blank_after_create_list_and_reload(tmp_path: Path) -> None:
    settings = build_settings(db_path=tmp_path / "unknown-field.sqlite3", artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(settings))
    payload = {
        "name": "Named point field",
        "field": {
            "crop": "",
            "region": "",
            "jurisdiction": "",
            "acres": "",
            "concern": "Scout uneven growth before interpreting it.",
            "notes": "",
        },
        "geometry": {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}},
    }
    created = client.post("/api/demo/fields", headers=OWNER, json=payload)
    assert created.status_code == 201
    field_id = created.json()["field"]["field_context_id"]

    def assert_unknowns(field: dict) -> None:
        assert field["field_context_id"] == field_id
        assert field["name"] == "Named point field"
        assert field["concern"] == payload["field"]["concern"]
        assert {key: field[key] for key in ("crop", "region", "jurisdiction", "acres", "notes")} == {
            "crop": "", "region": "", "jurisdiction": "", "acres": "", "notes": "",
        }

    assert_unknowns(created.json()["field"])
    assert_unknowns(client.get("/api/demo/fields", headers=OWNER).json()["fields"][0])
    reloaded = TestClient(create_app(settings))
    assert_unknowns(reloaded.get("/api/demo/fields", headers=OWNER).json()["fields"][0])

    store = reloaded.app.state.trace_store
    stored = store.get_phase4_field_context(field_id)
    assert stored is not None
    legacy = store.create_phase4_field_context(
        workspace={"id": stored["workspace_id"], "organization_id": stored["organization_id"]},
        created_by_user_id=created.json()["storage"]["user_id"],
        payload={
            "display_name": "Legacy field",
            "region_text": "Legacy region",
            "country": "Canada",
            "province_state": "Alberta",
            "crop_current": "wheat",
            "management_notes": "Legacy note",
            "metadata": {"open_agronomy_agent": {"kind": "map_field", "field": {}, "acres": "42"}},
        },
    )
    legacy_view = next(
        row for row in reloaded.get("/api/demo/fields", headers=OWNER).json()["fields"]
        if row["field_context_id"] == legacy["id"]
    )
    assert {key: legacy_view[key] for key in ("crop", "region", "jurisdiction", "acres", "notes")} == {
        "crop": "wheat", "region": "Legacy region", "jurisdiction": "Alberta", "acres": "42", "notes": "Legacy note",
    }


def test_session_summary_list_preserves_visibility_without_loading_turns(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    settings = build_settings(db_path=tmp_path / "session-summary.sqlite3", artifact_root=tmp_path / "artifacts")
    app = create_app(settings)
    client = TestClient(app)
    owner_session = client.post("/api/sessions", headers=OWNER, json={"title": "Owner session", "consent": {}}).json()
    outsider_session = client.post("/api/sessions", headers=OUTSIDER, json={"title": "Outsider session", "consent": {}}).json()
    store = app.state.trace_store
    for session in (owner_session, outsider_session):
        store.create_turn(
            session["session_id"],
            "Synthetic question",
            "Synthetic answer",
            parent_turn_id=None,
            system_state={"mode": "mock"},
            trace={"retrieved_docs": [], "graph_hits": [], "tool_invocations": []},
            objectives={},
            event_stream=False,
        )
    loaded_sessions: list[str] = []
    original_get_turns = store._get_turns_for_session

    def counted_get_turns(session_id: str):  # noqa: ANN202
        loaded_sessions.append(session_id)
        return original_get_turns(session_id)

    monkeypatch.setattr(store, "_get_turns_for_session", counted_get_turns)
    summary = client.get("/api/sessions?include_archived=true&include_turns=false", headers=OWNER)
    assert summary.status_code == 200
    assert loaded_sessions == []
    assert len(summary.json()) == 1
    assert summary.json()[0]["session_id"] == owner_session["session_id"]
    assert summary.json()[0]["turns"] == []
    assert summary.json()[0]["turns_included"] is False
    assert "_session_owner_user_id" not in summary.json()[0]["context"]["extra"]

    outsider_summary = client.get("/api/sessions?include_turns=false", headers=OUTSIDER)
    assert [row["session_id"] for row in outsider_summary.json()] == [outsider_session["session_id"]]
    assert loaded_sessions == []

    full = client.get("/api/sessions?include_archived=true", headers=OWNER)
    assert full.status_code == 200
    assert [row["session_id"] for row in full.json()] == [owner_session["session_id"]]
    assert len(full.json()[0]["turns"]) == 1
    assert "turns_included" not in full.json()[0]
    assert set(loaded_sessions) == {owner_session["session_id"], outsider_session["session_id"]}
    loaded = client.get(f"/api/sessions/{owner_session['session_id']}", headers=OWNER)
    assert loaded.status_code == 200
    assert len(loaded.json()["turns"]) == 1


def test_field_history_loads_full_turn_only_after_field_binding_matches(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    settings = build_settings(db_path=tmp_path / "field-history.sqlite3", artifact_root=tmp_path / "artifacts")
    app = create_app(settings)
    client = TestClient(app)
    selected = client.post("/api/demo/fields", headers=OWNER, json=_field_payload()).json()
    other = client.post("/api/demo/fields", headers=OWNER, json=_field_payload(name="South quarter")).json()
    selected_id = selected["field"]["field_context_id"]
    other_id = other["field"]["field_context_id"]
    owner_id = selected["storage"]["user_id"]
    store = app.state.trace_store

    def add_turn(field_id: str, *, lineage: bool) -> str:
        session = store.create_session(
            "Synthetic field history",
            {},
            {"field_context_id": field_id, "extra": {"_session_owner_user_id": owner_id}},
        )
        return store.create_turn(
            session["session_id"],
            "Synthetic question",
            "Synthetic answer",
            parent_turn_id=None,
            system_state={"mode": "mock"},
            trace={
                "metadata": {"field_lineage": {"field_context_id": field_id}} if lineage else {},
                "retrieved_docs": [],
                "graph_hits": [],
                "tool_invocations": [],
            },
            objectives={},
            feedback={"rating": 1} if field_id == selected_id else None,
            event_stream=False,
        )

    matching = add_turn(selected_id, lineage=True)
    add_turn(other_id, lineage=True)
    add_turn(other_id, lineage=False)
    loaded_ids: list[str] = []
    original_get_turn = store.get_turn

    def counted_get_turn(turn_id: str):  # noqa: ANN202
        loaded_ids.append(turn_id)
        return original_get_turn(turn_id)

    monkeypatch.setattr(store, "get_turn", counted_get_turn)
    response = client.get(f"/api/demo/fields/{selected_id}/history", headers=OWNER)
    assert response.status_code == 200
    assert loaded_ids == [matching]
    assert response.json()["turn_count"] == 1
    assert response.json()["turns"][0]["feedback"]["rating"] == 1
    assert response.json()["turns"][0]["answer_integrity_receipt"]["status"] == "verified"
