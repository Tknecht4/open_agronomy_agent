"""Durable, field/revision-bound single-scene requests and history."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def ensure_schema(cursor: Any) -> None:
    cursor.execute("""CREATE TABLE IF NOT EXISTS field_imagery_jobs (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, field_id TEXT NOT NULL,
        geometry_revision_id TEXT NOT NULL, geometry_json TEXT NOT NULL,
        operation_id TEXT NOT NULL, request_json TEXT NOT NULL, request_sha256 TEXT NOT NULL,
        status TEXT NOT NULL, result_json TEXT, result_sha256 TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(field_id, operation_id), FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""")
    cursor.execute("CREATE INDEX IF NOT EXISTS imagery_jobs_field ON field_imagery_jobs(field_id, created_at)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS field_imagery_operations (
        field_id TEXT NOT NULL, operation_id TEXT NOT NULL, job_id TEXT NOT NULL,
        request_sha256 TEXT NOT NULL, PRIMARY KEY(field_id, operation_id),
        FOREIGN KEY(job_id) REFERENCES field_imagery_jobs(id))""")
    cursor.execute("""INSERT OR IGNORE INTO field_imagery_operations
        SELECT field_id, operation_id, id, request_sha256 FROM field_imagery_jobs""")


def _decode(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("geometry", "request", "result"):
        raw = result.pop(key + "_json")
        result[key] = json.loads(raw) if raw else None
    if result["result"] is not None and hashlib.sha256(_json(result["result"]).encode()).hexdigest() != result["result_sha256"]:
        result.update(status="integrity_failed", result=None)
    return result


def recover_interrupted(store: Any) -> None:
    with store._cursor() as cursor:
        cursor.execute("UPDATE field_imagery_jobs SET status='interrupted',updated_at=? WHERE status IN ('queued','running')", (_now(),))


def get_job(store: Any, job_id: str) -> dict[str, Any] | None:
    with store._cursor() as cursor:
        row = cursor.execute("SELECT * FROM field_imagery_jobs WHERE id=?", (job_id,)).fetchone()
        return _decode(row) if row else None


def list_jobs(store: Any, field_id: str, limit: int = 30) -> list[dict[str, Any]]:
    with store._cursor() as cursor:
        return [_decode(row) for row in cursor.execute("SELECT * FROM field_imagery_jobs WHERE field_id=? ORDER BY created_at DESC,id DESC LIMIT ?", (field_id, limit)).fetchall()]


def queue(store: Any, field: dict[str, Any], payload: dict[str, Any], operation_id: str, expected_revision: str) -> tuple[dict, bool]:
    from agronomy_agent.server.field_data_routes import _stored_geometry
    geometry = _stored_geometry(field)
    digest = hashlib.sha256(_json({"request": payload, "revision": expected_revision}).encode()).hexdigest()
    with store._cursor() as cursor:
        previous = cursor.execute("""SELECT jobs.* FROM field_imagery_operations operations
            JOIN field_imagery_jobs jobs ON jobs.id=operations.job_id
            WHERE operations.field_id=? AND operations.operation_id=?""", (field["id"], operation_id)).fetchone()
        if previous:
            if previous["request_sha256"] != digest:
                raise ValueError("This analysis save identity belongs to another request")
            return _decode(previous), False
        current = cursor.execute("SELECT revision_id FROM field_geometry_current WHERE field_id=?", (field["id"],)).fetchone()
        if not current or current[0] != expected_revision:
            raise ValueError("Saved boundary changed. Reload the field before analyzing")
        active = cursor.execute("SELECT * FROM field_imagery_jobs WHERE field_id=? AND request_sha256=? AND status IN ('queued','running')", (field["id"], digest)).fetchone()
        if active:
            cursor.execute("INSERT INTO field_imagery_operations VALUES (?,?,?,?)",
                (field["id"], operation_id, active["id"], digest))
            return _decode(active), False
        if cursor.execute("SELECT COUNT(*) FROM field_imagery_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 4:
            raise RuntimeError("Four image analyses are already pending. Wait for one to finish")
        job_id, now = str(uuid4()), _now()
        cursor.execute("""INSERT INTO field_imagery_jobs(id,workspace_id,field_id,geometry_revision_id,geometry_json,operation_id,request_json,request_sha256,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,'queued',?,?)""", (job_id, field["workspace_id"], field["id"], expected_revision, _json(geometry), operation_id, _json(payload), digest, now, now))
        cursor.execute("INSERT INTO field_imagery_operations VALUES (?,?,?,?)",
            (field["id"], operation_id, job_id, digest))
        return get_job(store, job_id), True


def set_status(store: Any, job_id: str, status: str, result: dict | None = None) -> None:
    encoded = _json(result) if result is not None else None
    with store._cursor() as cursor:
        cursor.execute("UPDATE field_imagery_jobs SET status=?,result_json=COALESCE(?,result_json),result_sha256=COALESCE(?,result_sha256),updated_at=? WHERE id=? AND status!='cancelled'",
            (status, encoded, hashlib.sha256(encoded.encode()).hexdigest() if encoded else None, _now(), job_id))


def cancel(store: Any, job_id: str) -> None:
    with store._cursor() as cursor:
        cursor.execute("UPDATE field_imagery_jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (_now(), job_id))
