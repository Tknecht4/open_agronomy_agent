"""Workspace-authorized HTTP boundary for reviewed field tables and imagery.

Parsing, persistence and provider access live in their owning modules. No
caller-supplied filesystem path, remote URL or credential is accepted here.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class FieldTablePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=240)
    base64_content: str = Field(min_length=1, max_length=11_184_812)
    encoding: str | None = Field(default=None, max_length=32)


class FieldTableCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, Any]


class FieldImagerySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=80)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    limit: int = Field(default=5, ge=1, le=10)


def _stored_polygon(field: dict[str, Any]) -> dict[str, Any]:
    """Use the persisted geometry; a point or centroid cannot become a field."""
    metadata = field.get("metadata") or {}
    entry = metadata.get("open_agronomy_agent") or {}
    geometry = entry.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("Save a field polygon before searching imagery; a field point is insufficient.")
    if geometry.get("kind") == "polygon":
        points = geometry.get("points")
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError("Stored field polygon is incomplete.")
        ring = [[point["lon"], point["lat"]] for point in points]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}
    if geometry.get("type") in {"Polygon", "MultiPolygon"}:
        return geometry
    raise ValueError("Save a field polygon before searching imagery; a field point is insufficient.")


def register_field_data_routes(
    app: FastAPI,
    *,
    store: Any,
    settings: Any,
    authorize: Callable[[Request, str, bool], tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    from agronomy_agent.server.storage.field_data_store import (
        commit_import,
        list_imports,
        preview_import,
        query_import,
    )
    from agronomy_agent.field_imagery import provider_catalog, search_field_imagery

    @app.post("/api/demo/fields/{field_id}/data/preview", status_code=201)
    def preview_field_table(field_id: str, payload: FieldTablePreviewRequest, request: Request) -> dict[str, Any]:
        field, user = authorize(request, field_id, True)
        try:
            content = base64.b64decode(payload.base64_content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=422, detail="Upload content must be valid base64.") from exc
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Field table must be 8 MiB or smaller.")
        try:
            return preview_import(store, field, user["id"], payload.filename, content, encoding=payload.encoding)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/demo/fields/{field_id}/data/{import_id}/commit")
    def commit_field_table(field_id: str, import_id: str, payload: FieldTableCommitRequest, request: Request) -> dict[str, Any]:
        field, _ = authorize(request, field_id, True)
        if len(json.dumps(payload.mapping)) > 100_000:
            raise HTTPException(status_code=413, detail="Column mapping is too large.")
        try:
            return commit_import(store, field, import_id, payload.mapping)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Import not found for this field.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/demo/fields/{field_id}/data")
    def list_field_tables(field_id: str, request: Request) -> dict[str, Any]:
        authorize(request, field_id, False)
        return list_imports(store, field_id)

    @app.post("/api/demo/fields/{field_id}/data/{import_id}/query")
    def query_field_table(field_id: str, import_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
        authorize(request, field_id, False)
        if len(json.dumps(payload)) > 20_000:
            raise HTTPException(status_code=413, detail="Field query is too large.")
        try:
            return query_import(store, field_id, import_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Import not found for this field.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/imagery/providers")
    def imagery_providers() -> dict[str, Any]:
        return {"providers": provider_catalog(), "network_mode": settings.network_mode}

    @app.post("/api/demo/fields/{field_id}/imagery/search")
    def search_field_scenes(field_id: str, payload: FieldImagerySearchRequest, request: Request) -> dict[str, Any]:
        field, _ = authorize(request, field_id, False)
        try:
            return search_field_imagery(
                _stored_polygon(field),
                provider_id=payload.provider_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                limit=payload.limit,
                network_mode=settings.network_mode,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
