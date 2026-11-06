"""Bounded, durable field-context jobs. Results never modify grower facts.

A geometry revision, confirmed jurisdiction, source set and policy bind every
job. Per-source failures remain independent; old successful snapshots survive.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from typing import Any

from agronomy_agent.server.storage.farm_store import geometry_geojson, geometry_identity

POLICY_VERSION = "field-dossier.v2"
SOURCES = frozenset({"weather", "soil", "crop_cover", "imagery"})
SUCCESS = {"available", "partial", "no_match", "not_applicable"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def snapshot_digest(*, scope: str, source: str, result: dict, fetched_at: str, expires_at: str, geometry_revision_id: str) -> str:
    return hashlib.sha256(_json({"scope": scope, "source": source, "result": result, "fetched_at": fetched_at,
        "expires_at": expires_at, "geometry_revision_id": geometry_revision_id, "policy": POLICY_VERSION}).encode()).hexdigest()


def verified_snapshot(row: Any) -> dict[str, Any] | None:
    try:
        raw = json.loads(row["result_json"])
        if not isinstance(raw, dict) or raw.get("availability") != row["availability"]:
            return None
        digest = snapshot_digest(scope=row["scope_sha256"], source=row["source_id"], result=raw,
            fetched_at=row["fetched_at"], expires_at=row["expires_at"], geometry_revision_id=row["geometry_revision_id"])
        return raw if digest == row["receipt_sha256"] else None
    except (ValueError, TypeError, KeyError):
        return None


def scope_identity(field: dict[str, Any]) -> str:
    entry = field.get("metadata", {}).get("open_agronomy_agent", {})
    return hashlib.sha256(_json({"geometry": geometry_identity(entry.get("geometry") or {"kind": "none"}),
        "country": field.get("country"), "province": field.get("province_state"), "policy": POLICY_VERSION}).encode()).hexdigest()


def ensure_schema(cursor: Any) -> None:
    for statement in [
        """CREATE TABLE IF NOT EXISTS field_enrichment_jobs (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, field_id TEXT NOT NULL,
            geometry_revision_id TEXT NOT NULL, scope_sha256 TEXT NOT NULL, dedupe_key TEXT NOT NULL,
            sources_json TEXT NOT NULL, status TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, policy_version TEXT NOT NULL,
            FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""",
        "CREATE INDEX IF NOT EXISTS field_jobs_scope ON field_enrichment_jobs(dedupe_key, status)",
        """CREATE TABLE IF NOT EXISTS field_context_snapshots (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, field_id TEXT NOT NULL, job_id TEXT NOT NULL,
            geometry_revision_id TEXT NOT NULL, scope_sha256 TEXT NOT NULL, source_id TEXT NOT NULL,
            availability TEXT NOT NULL, fetched_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            result_json TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
            FOREIGN KEY(field_id) REFERENCES phase4_field_contexts(id))""",
        "CREATE INDEX IF NOT EXISTS field_snapshots_scope ON field_context_snapshots(field_id, scope_sha256, source_id, fetched_at)",
    ]:
        cursor.execute(statement)


def recover_interrupted(store: Any) -> None:
    # Startup never invents completion or silently replays external requests.
    with store._cursor() as cursor:
        cursor.execute("UPDATE field_enrichment_jobs SET status='interrupted', updated_at=? WHERE status IN ('queued','running')", (_now(),))


def _job(row: Any) -> dict[str, Any]:
    value = dict(row)
    value["sources"] = json.loads(value.pop("sources_json"))
    value["results"] = json.loads(value.pop("results_json"))
    return value


def get_job(store: Any, job_id: str) -> dict[str, Any] | None:
    with store._cursor() as cursor:
        row = cursor.execute("SELECT * FROM field_enrichment_jobs WHERE id=?", (job_id,)).fetchone()
        return _job(row) if row else None


def queue_job(store: Any, field: dict[str, Any], sources: list[str], network_mode: str) -> tuple[dict[str, Any], bool]:
    entry = field.get("metadata", {}).get("open_agronomy_agent", {})
    if geometry_geojson(entry.get("geometry") or {"kind": "none"}) is None:
        raise ValueError("Add a saved location or boundary before requesting public context")
    scope = scope_identity(field)
    key = hashlib.sha256(_json({"workspace": field["workspace_id"], "field": field["id"], "scope": scope,
        "sources": sorted(sources), "date": _now()[:10], "mode": network_mode}).encode()).hexdigest()
    with store._cursor() as cursor:
        existing = cursor.execute("SELECT * FROM field_enrichment_jobs WHERE dedupe_key=? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1", (key,)).fetchone()
        if existing:
            return _job(existing), False
        if cursor.execute("SELECT COUNT(*) FROM field_enrichment_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 8:
            raise RuntimeError("Eight field updates are already pending. Wait for one to finish.")
        revision = cursor.execute("SELECT revision_id FROM field_geometry_current WHERE field_id=?", (field["id"],)).fetchone()
        if revision is None:
            raise ValueError("The saved geometry has no revision. Reload or save the field first.")
        job_id, now = str(uuid.uuid4()), _now()
        cursor.execute("""INSERT INTO field_enrichment_jobs(id,workspace_id,field_id,geometry_revision_id,scope_sha256,dedupe_key,sources_json,status,created_at,updated_at,policy_version)
            VALUES (?,?,?,?,?,?,?,'queued',?,?,?)""", (job_id, field["workspace_id"], field["id"], revision["revision_id"], scope, key, _json(sources), now, now, POLICY_VERSION))
        return get_job(store, job_id), True


def current_sources(store: Any, field: dict[str, Any]) -> dict[str, Any]:
    scope = scope_identity(field)
    result: dict[str, Any] = {source: {"availability": "not_requested", "freshness": "unknown"} for source in sorted(SOURCES)}
    with store._cursor() as cursor:
        rows = cursor.execute("SELECT * FROM field_context_snapshots WHERE field_id=? AND scope_sha256=? ORDER BY fetched_at DESC,id DESC", (field["id"], scope)).fetchall()
        seen = set()
        for row in rows:
            source = row["source_id"]
            raw = verified_snapshot(row)
            if raw is None:
                if source not in seen:
                    result[source] = {"availability": "integrity_failed", "freshness": "unknown", "message": "Retained source receipt failed verification. Refresh this source."}
                    seen.add(source)
                continue
            snapshot = {**raw, "snapshot_id": row["id"], "fetched_at": row["fetched_at"],
                "expires_at": row["expires_at"], "freshness": "stale" if row["expires_at"] < _now() else "current", "receipt_sha256": row["receipt_sha256"]}
            if source not in seen:
                result[source] = snapshot; seen.add(source)
            elif row["availability"] in SUCCESS and result[source]["availability"] not in SUCCESS and "last_success" not in result[source]:
                result[source]["last_success"] = snapshot
        active = cursor.execute("SELECT * FROM field_enrichment_jobs WHERE field_id=? AND scope_sha256=? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1", (field["id"], scope)).fetchone()
        if active:
            job = _job(active)
            for source in job["sources"]:
                result[source]["refresh_status"] = job["status"]
    return result


def cancel_job(store: Any, job_id: str) -> None:
    with store._cursor() as cursor:
        cursor.execute("UPDATE field_enrichment_jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (_now(), job_id))


def update_job(store: Any, job_id: str, status: str | None = None, results: dict[str, Any] | None = None) -> None:
    with store._cursor() as cursor:
        if status is not None:
            cursor.execute("UPDATE field_enrichment_jobs SET status=?,updated_at=? WHERE id=? AND status!='cancelled'", (status, _now(), job_id))
        if results is not None:
            cursor.execute("UPDATE field_enrichment_jobs SET results_json=?,updated_at=? WHERE id=?", (_json(results), _now(), job_id))


def save_snapshot(store: Any, job: dict[str, Any], field: dict[str, Any], source: str, value: dict[str, Any]) -> str:
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=6 if source in {"weather", "imagery"} else 24 * 30)).isoformat()
    snapshot_id = str(uuid.uuid4())
    receipt = snapshot_digest(scope=job["scope_sha256"], source=source, result=value, fetched_at=now,
        expires_at=expires, geometry_revision_id=job["geometry_revision_id"])
    with store._cursor() as cursor:
        cursor.execute("INSERT INTO field_context_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (snapshot_id, field["workspace_id"], field["id"], job["id"], job["geometry_revision_id"], job["scope_sha256"], source, value["availability"], now, expires, _json(value), receipt))
    return snapshot_id
