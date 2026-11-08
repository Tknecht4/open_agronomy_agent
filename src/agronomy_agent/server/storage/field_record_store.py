"""Idempotent, atomic record bundles and bounded workspace timelines."""
from __future__ import annotations

import hashlib
import json
from typing import Any


# Unknown observation times may have a storage timestamp for ordering. They
# cannot supply a crop season. Keep SQL summaries and prompt admission aligned.
EVENT_SEASON_SQL = """CASE
    WHEN json_type(e.payload,'$.season')='integer' THEN json_extract(e.payload,'$.season')
    WHEN COALESCE(json_extract(e.provenance,'$.sampling_time_status'),'')='unknown'
      OR COALESCE(json_extract(e.provenance,'$.observation_time_status'),'')='unknown' THEN NULL
    ELSE CAST(substr(e.occurred_at,1,4) AS INTEGER) END"""


def event_season(event: dict[str, Any]) -> int | None:
    value = (event.get("payload") or {}).get("season")
    if type(value) is int:
        return value
    provenance = event.get("provenance") or {}
    if any(provenance.get(key) == "unknown" for key in ("sampling_time_status", "observation_time_status")):
        return None
    year = str(event.get("occurred_at") or "")[:4]
    return int(year) if len(year) == 4 and year.isdigit() else None


def ensure_schema(cursor: Any) -> None:
    cursor.execute("""CREATE TABLE IF NOT EXISTS field_record_operations (
        field_id TEXT NOT NULL, operation_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        event_ids_json TEXT NOT NULL, PRIMARY KEY(field_id, operation_id),
        FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""")


def append_bundle(store: Any, field: dict[str, Any], actor_id: str, operation_id: str,
                  events: list[dict[str, Any]]) -> dict[str, Any]:
    digest = hashlib.sha256(json.dumps(events, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    with store._cursor() as cursor:
        cursor.execute("BEGIN IMMEDIATE")
        existing = cursor.execute("SELECT * FROM field_record_operations WHERE field_id=? AND operation_id=?", (field["id"], operation_id)).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise ValueError("This save identity already belongs to different records. Start a new entry.")
            saved = [store.get_phase4_field_event(event_id) for event_id in json.loads(existing["event_ids_json"])]
            return {"status": "already_saved", "events": saved}
        saved = [store.append_phase4_field_event(field_context=field, recorded_by_user_id=actor_id, payload=event) for event in events]
        cursor.execute("INSERT INTO field_record_operations VALUES (?, ?, ?, ?)", (field["id"], operation_id, digest, json.dumps([event["id"] for event in saved])))
        return {"status": "saved", "events": saved}


def timeline(store: Any, workspace_id: str, *, field_id: str | None = None, farm_id: str | None = None,
             season: int | None = None, event_type: str | None = None,
             offset: int = 0, limit: int = 100) -> dict[str, Any]:
    clauses = ["f.workspace_id=?", "f.deleted_at IS NULL"]
    params: list[Any] = [workspace_id]
    if field_id:
        clauses.append("f.id=?"); params.append(field_id)
    if farm_id:
        if farm_id == "unassigned":
            clauses.append("m.farm_id IS NULL")
        else:
            clauses.append("m.farm_id=?"); params.append(farm_id)
    if season is not None:
        clauses.append(f"({EVENT_SEASON_SQL})=?")
        params.append(season)
    if event_type == "correction":
        clauses.append("e.event_type=?")
        params.append(event_type)
    elif event_type:
        # Include the entire correction chain in its original record category.
        # UNION deduplicates even malformed cyclic legacy history.
        clauses.append("""e.id IN (WITH RECURSIVE matching(id,field_id) AS (
            SELECT id,field_context_id FROM phase4_field_events WHERE event_type=?
            UNION SELECT c.id,c.field_context_id FROM phase4_field_events c
            JOIN matching p ON c.corrects_event_id=p.id AND c.field_context_id=p.field_id
        ) SELECT id FROM matching)""")
        params.append(event_type)
    query = """FROM phase4_field_events e JOIN phase4_field_contexts f ON f.id=e.field_context_id
        LEFT JOIN field_farm_memberships m ON m.field_id=f.id WHERE """ + " AND ".join(clauses)
    with store._cursor() as cursor:
        count = cursor.execute("SELECT COUNT(*) " + query, params).fetchone()[0]
        rows = cursor.execute("SELECT e.*, f.display_name AS field_name " + query + " ORDER BY e.occurred_at DESC,e.recorded_at DESC,e.id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        result = []
        for row in rows:
            event = store._normalize_phase4_field_event(dict(row))
            event["field_name"] = row["field_name"]
            event["season_binding"] = "explicit" if type(event["payload"].get("season")) is int else "observation_year" if event_season(event) is not None else "unknown"
            correction = cursor.execute("SELECT id FROM phase4_field_events WHERE corrects_event_id=? ORDER BY recorded_at DESC LIMIT 1", (event["id"],)).fetchone()
            event["corrected_by"] = correction["id"] if correction else None
            result.append(event)
        return {"events": result, "total": count, "offset": offset, "next_offset": offset + limit if offset + limit < count else None}
