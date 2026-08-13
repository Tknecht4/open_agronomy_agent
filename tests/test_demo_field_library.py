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
