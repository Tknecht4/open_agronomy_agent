"""Reviewed multi-feature import. Commit reads server-retained geometry and receipts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from agronomy_agent.geospatial.vector_io import MAX_UPLOAD_BYTES, MAX_FEATURES
from agronomy_agent.server.storage import farm_store


def ensure_schema(cursor: Any) -> None:
    cursor.execute("""CREATE TABLE IF NOT EXISTS field_import_previews (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL, parsed_json TEXT NOT NULL, parsed_sha256 TEXT NOT NULL,
        commit_sha256 TEXT, result_json TEXT)""")


class ImportChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    feature_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)


class ImportCommit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_id: UUID
    farm_id: str | None = Field(default=None, max_length=80)
    jurisdiction: str = Field(default="", max_length=120)
    features: list[ImportChoice] = Field(min_length=1, max_length=MAX_FEATURES)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _geometry(feature: dict[str, Any]) -> dict[str, Any]:
    shape = feature["geometry"]
    if shape["type"] == "Point":
        return {"kind": "point", "point": {"lon": shape["coordinates"][0], "lat": shape["coordinates"][1]}}
    return {"kind": "geojson", "geojson": shape}


def register_field_import_routes(app: FastAPI, *, store: Any, authorize: Callable,
                                parse: Callable, normalize: Callable) -> None:
    def access(request: Request, workspace_id: str | None) -> tuple[dict, dict]:
        workspace, actor = authorize(request, True, workspace_id)
        from agronomy_agent.server.storage.db import TraceStore
        if not isinstance(store, TraceStore):
            raise HTTPException(503, "Boundary import requires the migrated local runtime")
        return workspace, actor

    @app.post("/api/field-imports/preview", status_code=201)
    async def preview(request: Request, file: UploadFile = File(...), workspace_id: str | None = None) -> dict:
        workspace, _ = access(request, workspace_id)
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
        try:
            parsed = parse(filename=str(file.filename or "boundary"), content_type=str(file.content_type or "application/octet-stream"), raw=raw)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        features = parsed.get("feature_collection", {}).get("features", [])
        if not features:
            raise HTTPException(422, "No individual field features were returned")
        # Identity is bound to the full accepted shape, including holes and parts.
        existing = {row["geometry_sha256"]: row["id"] for row in farm_store.workspace_rows(store, workspace["id"], None)}
        seen = set()
        dispositions = []
        summaries = {row["id"]: row for row in parsed.get("feature_summaries", [])}
        for feature in features:
            digest = farm_store.geometry_identity(_geometry(feature))
            row = summaries.get(str(feature["id"]), {})
            duplicate = digest in existing or digest in seen
            dispositions.append({**row, "id": str(feature["id"]), "duplicate": duplicate,
                "existing_field_id": existing.get(digest), "geometry_sha256": digest})
            seen.add(digest)
        now = datetime.now(timezone.utc)
        preview_id = str(uuid4())
        encoded = _json(parsed)
        with store._cursor() as cursor:
            # Only expired, uncommitted previews are disposable. Committed receipts stay.
            cursor.execute("DELETE FROM field_import_previews WHERE expires_at < ? AND result_json IS NULL", (now.isoformat(),))
            pending = cursor.execute("SELECT COUNT(*) FROM field_import_previews WHERE workspace_id=? AND result_json IS NULL", (workspace["id"],)).fetchone()[0]
            if pending >= 20:
                raise HTTPException(429, "Too many pending boundary previews. Finish an import or wait for previews to expire.")
            cursor.execute("INSERT INTO field_import_previews(id,workspace_id,created_at,expires_at,parsed_json,parsed_sha256) VALUES (?,?,?,?,?,?)",
                (preview_id, workspace["id"], now.isoformat(), (now + timedelta(days=1)).isoformat(), encoded, hashlib.sha256(encoded.encode()).hexdigest()))
        return {**parsed, "id": preview_id, "features": dispositions, "expires_at": (now + timedelta(days=1)).isoformat()}

    @app.post("/api/field-imports/{preview_id}/commit")
    def commit(preview_id: str, payload: ImportCommit, request: Request, workspace_id: str | None = None) -> dict:
        workspace, actor = access(request, workspace_id)
        commit_hash = hashlib.sha256(_json(payload.model_dump(mode="json")).encode()).hexdigest()
        ids = [choice.feature_id for choice in payload.features]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "Each source feature can only be selected once")
        with store._cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            row = cursor.execute("SELECT * FROM field_import_previews WHERE id=? AND workspace_id=?", (preview_id, workspace["id"])).fetchone()
            if not row:
                raise HTTPException(404, "Boundary preview not found")
            if row["result_json"]:
                if row["commit_sha256"] != commit_hash:
                    raise HTTPException(409, "This preview was already committed with different selections")
                return json.loads(row["result_json"])
            if row["expires_at"] < datetime.now(timezone.utc).isoformat():
                raise HTTPException(409, "Boundary preview expired. Import the source file again")
            if hashlib.sha256(row["parsed_json"].encode()).hexdigest() != row["parsed_sha256"]:
                raise HTTPException(409, "Boundary preview integrity check failed. Import the source file again")
            parsed = json.loads(row["parsed_json"])
            features = {str(feature["id"]): feature for feature in parsed["feature_collection"]["features"]}
            if any(key not in features for key in ids):
                raise HTTPException(422, "A selected feature is not in this preview")
            if payload.farm_id:
                try:
                    farm = farm_store.get_farm(store, workspace["id"], payload.farm_id)
                except LookupError as exc:
                    raise HTTPException(404, str(exc)) from exc
                if farm["archived"]:
                    raise HTTPException(409, "Choose an active farm")
            existing = {item["geometry_sha256"]: item["id"] for item in farm_store.workspace_rows(store, workspace["id"], None)}
            results = []
            for choice in payload.features:
                feature = features[choice.feature_id]
                geometry = _geometry(feature)
                digest = farm_store.geometry_identity(geometry)
                if digest in existing:
                    results.append({"feature_id": choice.feature_id, "field_id": existing[digest], "status": "duplicate_skipped"})
                    continue
                properties = feature.get("properties", {})
                lineage = {"import_receipt": parsed["import_receipt"], "coordinate_reference": parsed["coordinate_reference"],
                    "selected_feature": {"id": choice.feature_id, "source_layer": properties["upload_source_layer"],
                        "source_feature_index": properties["upload_source_feature_index"],
                        "source_feature_id": properties.get("upload_source_feature_id"), "properties": properties}}
                normalized = normalize({"name": choice.name, "geometry": geometry, "boundaryImport": lineage,
                    "field": {"jurisdiction": payload.jurisdiction}, "sourceBoundary": "Reviewed source-file boundary; not a cadastral survey. File attributes are not confirmed season facts."})
                record = store.create_phase4_field_context(workspace=workspace, created_by_user_id=actor["id"], payload=normalized)
                if payload.farm_id:
                    farm_store.assign_field(store, workspace["id"], actor["id"], record["id"], payload.farm_id, 0)
                existing[digest] = record["id"]
                results.append({"feature_id": choice.feature_id, "field_id": record["id"], "status": "created"})
            result = {"preview_id": preview_id, "source_sha256": parsed["import_receipt"]["source_sha256"], "features": results}
            cursor.execute("UPDATE field_import_previews SET commit_sha256=?,result_json=? WHERE id=?", (commit_hash, _json(result), preview_id))
            return result
