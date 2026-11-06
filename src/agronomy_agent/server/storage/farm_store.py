"""Local farm grouping, explicit seasons, and immutable geometry revisions.

Farm membership never grants workspace access. Callers authorize the workspace
first; every write also checks field/farm workspace identity transactionally.
Legacy fields remain unassigned and their undated crop assertions stay undated.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def geometry_geojson(geometry: dict[str, Any]) -> dict[str, Any] | None:
    if geometry.get("kind") == "none":
        return None
    if geometry.get("kind") == "geojson":
        return geometry["geojson"]
    if geometry.get("kind") == "point":
        point = geometry["point"]
        return {"type": "Point", "coordinates": [point["lon"], point["lat"]]}
    if geometry.get("kind") == "polygon":
        ring = [[point["lon"], point["lat"]] for point in geometry["points"]]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}
    raise ValueError("Unsupported saved field geometry")


def geometry_identity(geometry: dict[str, Any]) -> str:
    return hashlib.sha256(_json(geometry_geojson(geometry)).encode()).hexdigest()


def ensure_schema(cursor: Any) -> None:
    # Additive migration: existing field, event and conversation tables are intact.
    statements = [
        """CREATE TABLE IF NOT EXISTS field_creation_operations (
            workspace_id TEXT NOT NULL, operation_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
            field_id TEXT NOT NULL, PRIMARY KEY(workspace_id, operation_id),
            FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""",
        """CREATE TABLE IF NOT EXISTS farm_schema_migrations (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS farms (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id) REFERENCES phase4_workspaces(id))""",
        "CREATE INDEX IF NOT EXISTS farms_workspace ON farms(workspace_id, archived)",
        """CREATE TABLE IF NOT EXISTS field_farm_memberships (
            field_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, farm_id TEXT,
            revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
            FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id),
            FOREIGN KEY(farm_id) REFERENCES farms(id))""",
        "CREATE INDEX IF NOT EXISTS field_farms_farm ON field_farm_memberships(workspace_id, farm_id)",
        """CREATE TABLE IF NOT EXISTS field_seasons (
            field_id TEXT NOT NULL, season INTEGER NOT NULL, workspace_id TEXT NOT NULL,
            crop TEXT, cultivar TEXT, planted_at TEXT, harvested_at TEXT,
            revision INTEGER NOT NULL DEFAULT 1, actor_id TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(field_id, season), FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""",
        """CREATE TABLE IF NOT EXISTS field_geometry_revisions (
            id TEXT PRIMARY KEY, field_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
            geometry_sha256 TEXT NOT NULL, geometry_json TEXT NOT NULL,
            source_json TEXT, supersedes_id TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""",
        "CREATE INDEX IF NOT EXISTS field_geometry_history ON field_geometry_revisions(field_id, created_at)",
        """CREATE TABLE IF NOT EXISTS field_geometry_current (
            field_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL,
            FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id),
            FOREIGN KEY(revision_id) REFERENCES field_geometry_revisions(id))""",
    ]
    for statement in statements:
        cursor.execute(statement)
    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(field_seasons)").fetchall()}
    if "crops_json" not in columns:
        cursor.execute("ALTER TABLE field_seasons ADD COLUMN crops_json TEXT")
    if "crop_system" not in columns:
        cursor.execute("ALTER TABLE field_seasons ADD COLUMN crop_system TEXT NOT NULL DEFAULT 'unknown'")
    if cursor.execute("SELECT 1 FROM farm_schema_migrations WHERE version = 1").fetchone() is None:
        for row in cursor.execute("SELECT id, workspace_id, metadata FROM phase4_field_contexts WHERE deleted_at IS NULL").fetchall():
            metadata = json.loads(row["metadata"] or "{}")
            entry = metadata.get("open_agronomy_agent", {})
            if entry.get("kind") == "map_field":
                record_geometry(cursor, row["id"], row["workspace_id"], entry)
        cursor.execute("INSERT INTO farm_schema_migrations VALUES (1, ?, ?)", (_now(), "Additive farms/seasons; legacy membership and crop years remain unknown"))


def record_geometry(cursor: Any, field_id: str, workspace_id: str, entry: dict[str, Any]) -> str | None:
    if entry.get("kind") != "map_field":
        return None
    geometry = entry.get("geometry") or {"kind": "none"}
    digest = geometry_identity(geometry)
    previous = cursor.execute("""SELECT r.id, r.geometry_sha256 FROM field_geometry_current c
        JOIN field_geometry_revisions r ON r.id = c.revision_id WHERE c.field_id = ?""", (field_id,)).fetchone()
    if previous and previous["geometry_sha256"] == digest:
        return str(previous["id"])
    revision_id = str(uuid.uuid4())
    cursor.execute("""INSERT INTO field_geometry_revisions
        (id, field_id, workspace_id, geometry_sha256, geometry_json, source_json, supersedes_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (revision_id, field_id, workspace_id, digest,
        _json(geometry), _json(entry.get("boundary_import")), previous["id"] if previous else None, _now()))
    cursor.execute("""INSERT INTO field_geometry_current(field_id, revision_id) VALUES (?, ?)
        ON CONFLICT(field_id) DO UPDATE SET revision_id = excluded.revision_id""", (field_id, revision_id))
    return revision_id


def _field(cursor: Any, field_id: str, workspace_id: str) -> Any:
    row = cursor.execute("SELECT * FROM phase4_field_contexts WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL", (field_id, workspace_id)).fetchone()
    if not row or json.loads(row["metadata"] or "{}").get("open_agronomy_agent", {}).get("kind") != "map_field":
        raise LookupError("Field not found in this workspace")
    return row


def list_farms(store: Any, workspace_id: str) -> list[dict[str, Any]]:
    with store._cursor() as cursor:
        return [dict(row) for row in cursor.execute("SELECT * FROM farms WHERE workspace_id = ? ORDER BY archived, name, id", (workspace_id,)).fetchall()]


def get_farm(store: Any, workspace_id: str, farm_id: str) -> dict[str, Any]:
    with store._cursor() as cursor:
        row = cursor.execute("SELECT * FROM farms WHERE id = ? AND workspace_id = ?", (farm_id, workspace_id)).fetchone()
        if not row:
            raise LookupError("Farm not found in this workspace")
        return dict(row)


def save_farm(store: Any, workspace_id: str, actor_id: str, name: str, *, farm_id: str | None = None,
              expected_revision: int | None = None, archived: bool = False) -> dict[str, Any]:
    now = _now()
    with store._cursor() as cursor:
        if farm_id is None:
            farm_id = str(uuid.uuid4())
            cursor.execute("INSERT INTO farms(id, workspace_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (farm_id, workspace_id, name, now, now))
        else:
            current = get_farm(store, workspace_id, farm_id)
            if current["revision"] != expected_revision:
                raise ValueError("Farm changed. Reload before saving.")
            if archived and cursor.execute("SELECT 1 FROM field_farm_memberships m JOIN phase4_field_contexts f ON f.id=m.field_id WHERE m.farm_id=? AND f.deleted_at IS NULL LIMIT 1", (farm_id,)).fetchone():
                raise ValueError("Move the farm's fields before archiving it.")
            cursor.execute("UPDATE farms SET name=?, archived=?, revision=revision+1, updated_at=? WHERE id=? AND revision=?", (name, int(archived), now, farm_id, expected_revision))
        workspace = cursor.execute("SELECT organization_id FROM phase4_workspaces WHERE id=?", (workspace_id,)).fetchone()
        store._insert_phase4_audit(cursor, event_type="farm.saved", actor_user_id=actor_id,
            organization_id=workspace["organization_id"], workspace_id=workspace_id, target_type="farm",
            target_id=farm_id, payload={"name": name, "archived": archived}, created_at=now)
    return get_farm(store, workspace_id, farm_id)


def assign_field(store: Any, workspace_id: str, actor_id: str, field_id: str, farm_id: str | None, expected_revision: int) -> dict[str, Any]:
    now = _now()
    with store._cursor() as cursor:
        field = _field(cursor, field_id, workspace_id)
        if farm_id:
            farm = get_farm(store, workspace_id, farm_id)
            if farm["archived"]:
                raise ValueError("Archived farms cannot receive fields")
        current = cursor.execute("SELECT * FROM field_farm_memberships WHERE field_id=?", (field_id,)).fetchone()
        revision = int(current["revision"]) if current else 0
        if revision != expected_revision:
            raise ValueError("Field assignment changed. Reload before saving.")
        cursor.execute("""INSERT INTO field_farm_memberships(field_id, workspace_id, farm_id, revision, updated_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(field_id) DO UPDATE SET farm_id=excluded.farm_id, revision=excluded.revision, updated_at=excluded.updated_at""",
            (field_id, workspace_id, farm_id, revision + 1, now))
        store._insert_phase4_audit(cursor, event_type="field.farm_assigned", actor_user_id=actor_id,
            organization_id=field["organization_id"], workspace_id=workspace_id, target_type="field_context", target_id=field_id,
            payload={"farm_id": farm_id, "previous_farm_id": current["farm_id"] if current else None}, created_at=now)
    return {"field_id": field_id, "farm_id": farm_id, "revision": revision + 1}


def season_record(row: Any) -> dict[str, Any]:
    result = dict(row)
    raw = result.pop("crops_json", None)
    crops = json.loads(raw) if raw is not None else ([{"crop": result["crop"], "cultivar": result.get("cultivar")}] if result.get("crop") else [])
    result["crops"] = crops
    result["crop_system"] = result.get("crop_system") if len(crops) > 1 else "single" if crops else "unknown"
    return result


def save_season(store: Any, workspace_id: str, actor_id: str, field_id: str, season: int,
                values: dict[str, Any], expected_revision: int) -> dict[str, Any]:
    now = _now()
    crops = values.get("crops")
    if crops is None:
        crops = [{"crop": values["crop"], "cultivar": values.get("cultivar")}] if values.get("crop") else []
    system = values.get("crop_system", "unknown") if len(crops) > 1 else "single" if crops else "unknown"
    crop_label = " + ".join(item["crop"] for item in crops) or None
    with store._cursor() as cursor:
        field = _field(cursor, field_id, workspace_id)
        current = cursor.execute("SELECT * FROM field_seasons WHERE field_id=? AND season=?", (field_id, season)).fetchone()
        revision = int(current["revision"]) if current else 0
        if revision != expected_revision:
            raise ValueError("Season changed. Reload before saving.")
        cursor.execute("""INSERT INTO field_seasons(field_id, season, workspace_id, crop, cultivar, planted_at, harvested_at, revision, actor_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(field_id, season) DO UPDATE SET
            crop=excluded.crop, cultivar=excluded.cultivar, planted_at=excluded.planted_at, harvested_at=excluded.harvested_at,
            revision=excluded.revision, actor_id=excluded.actor_id, updated_at=excluded.updated_at""",
            (field_id, season, workspace_id, crop_label, crops[0].get("cultivar") if len(crops) == 1 else None, values.get("planted_at"), values.get("harvested_at"), revision + 1, actor_id, current["created_at"] if current else now, now))
        cursor.execute("UPDATE field_seasons SET crops_json=?, crop_system=? WHERE field_id=? AND season=?", (_json(crops), system, field_id, season))
        store._insert_phase4_audit(cursor, event_type="field.season_saved", actor_user_id=actor_id,
            organization_id=field["organization_id"], workspace_id=workspace_id, target_type="field_context", target_id=field_id,
            payload={"season": season, "previous": dict(current) if current else None, "values": values}, created_at=now)
        return season_record(cursor.execute("SELECT * FROM field_seasons WHERE field_id=? AND season=?", (field_id, season)).fetchone())


def workspace_rows(store: Any, workspace_id: str, season: int | None) -> list[dict[str, Any]]:
    # Field, grouped record and source-status queries are independent of field count.
    from agronomy_agent.server.storage.field_context_store import scope_identity, SOURCES, SUCCESS, verified_snapshot
    from agronomy_agent.server.storage.field_record_store import EVENT_SEASON_SQL
    with store._cursor() as cursor:
        rows = cursor.execute("""SELECT f.*, m.farm_id, COALESCE(m.revision,0) AS assignment_revision,
            s.crop AS season_crop, s.crop_system AS crop_system, s.revision AS season_revision, r.id AS geometry_revision_id,
            r.geometry_sha256 FROM phase4_field_contexts f
            LEFT JOIN field_farm_memberships m ON m.field_id=f.id
            LEFT JOIN field_seasons s ON s.field_id=f.id AND s.season=?
            LEFT JOIN field_geometry_current c ON c.field_id=f.id
            LEFT JOIN field_geometry_revisions r ON r.id=c.revision_id
            WHERE f.workspace_id=? AND f.deleted_at IS NULL ORDER BY f.display_name, f.id""", (season, workspace_id)).fetchall()
        events = {row["field_context_id"]: dict(row) for row in cursor.execute(f"""SELECT e.field_context_id,
            COUNT(*) AS record_count, MAX(e.occurred_at) AS last_record_at FROM phase4_field_events e
            JOIN phase4_field_contexts f ON f.id=e.field_context_id WHERE f.workspace_id=? AND f.deleted_at IS NULL
            AND (? IS NULL OR ({EVENT_SEASON_SQL})=?) GROUP BY e.field_context_id""", (workspace_id, season, season)).fetchall()}
        snapshots = {}
        for snapshot in cursor.execute("SELECT field_id,scope_sha256,source_id,availability,fetched_at,expires_at,geometry_revision_id,result_json,receipt_sha256 FROM field_context_snapshots WHERE workspace_id=? ORDER BY fetched_at DESC,id DESC", (workspace_id,)).fetchall():
            key = (snapshot['field_id'], snapshot['scope_sha256'], snapshot['source_id'])
            if key in snapshots:
                continue
            raw = verified_snapshot(snapshot)
            snapshots[key] = {'availability': snapshot['availability'] if raw is not None else 'integrity_failed',
                'freshness': 'stale' if snapshot['expires_at'] < _now() else 'current', 'fetched_at': snapshot['fetched_at']}
        result = []
        for row in rows:
            metadata = json.loads(row["metadata"] or "{}").get("open_agronomy_agent", {})
            if metadata.get("kind") != "map_field":
                continue
            geometry = metadata.get("geometry") or {"kind": "none"}
            scope = scope_identity({'metadata': json.loads(row['metadata'] or '{}'), 'country': row['country'], 'province_state': row['province_state']})
            statuses = {source: snapshots.get((row['id'], scope, source), {'availability': 'not_requested', 'freshness': 'unknown'}) for source in sorted(SOURCES)}
            checked = [value for value in statuses.values() if value['availability'] != 'not_requested']
            review = sum(value['availability'] not in SUCCESS or value['freshness'] == 'stale' for value in checked)
            result.append({"context_status": statuses, "context_checked_count": len(checked), "context_review_count": review,
                "id": row["id"], "name": row["display_name"], "farm_id": row["farm_id"],
                "assignment_revision": row["assignment_revision"], "season": season, "crop": row["season_crop"],
                "crop_system": row["crop_system"] or "unknown", "crop_status": "grower_confirmed" if row["season_crop"] else "unknown",
                "season_revision": row["season_revision"] or 0, "legacy_undated_crop": row["crop_current"] if row["crop_year"] is None else None,
                "geometry": geometry, "geometry_revision_id": row["geometry_revision_id"], "geometry_sha256": row["geometry_sha256"],
                "updated_at": row["updated_at"], "country": row["country"],
                **events.get(row["id"], {"record_count": 0, "last_record_at": None})})
        return result


def create_field_in_farm(store: Any, workspace: dict[str, Any], actor_id: str, normalized: dict[str, Any],
                         farm_id: str | None, operation_id: str | None, original: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(_json(original).encode()).hexdigest()
    with store._cursor() as cursor:
        cursor.execute("BEGIN IMMEDIATE")
        if operation_id:
            prior = cursor.execute("SELECT * FROM field_creation_operations WHERE workspace_id=? AND operation_id=?", (workspace["id"], operation_id)).fetchone()
            if prior:
                if prior["payload_sha256"] != digest:
                    raise ValueError("This field save identity belongs to a different draft.")
                existing = store.get_phase4_field_context(prior["field_id"])
                if not existing:
                    raise ValueError("This field was saved and later deleted. Start a new draft.")
                return existing
        if farm_id:
            farm = get_farm(store, workspace["id"], farm_id)
            if farm["archived"]:
                raise ValueError("Archived farms cannot receive fields")
        record = store.create_phase4_field_context(workspace=workspace, created_by_user_id=actor_id, payload=normalized)
        if farm_id:
            assign_field(store, workspace["id"], actor_id, record["id"], farm_id, 0)
        if original.get("season") is not None:
            save_season(store, workspace["id"], actor_id, record["id"], original["season"],
                {"crop": normalized.get("crop_current"), "cultivar": None, "planted_at": None, "harvested_at": None}, 0)
        if operation_id:
            cursor.execute("INSERT INTO field_creation_operations VALUES (?, ?, ?, ?)", (workspace["id"], operation_id, digest, record["id"]))
        return record


def get_season(store: Any, field_id: str, season: int) -> dict[str, Any] | None:
    with store._cursor() as cursor:
        row = cursor.execute("SELECT * FROM field_seasons WHERE field_id=? AND season=?", (field_id, season)).fetchone()
        return season_record(row) if row else None
