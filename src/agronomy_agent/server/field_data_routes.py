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
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


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


class FieldImageryAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: Literal["hls-s30-planetary-computer", "hls-l30-planetary-computer"]
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    scene_id: str | None = Field(default=None, max_length=180)
    buffer_m: int = Field(default=0, ge=0, le=3000, strict=True)
    sampling_mode: Literal["field_polygon", "point_pixel", "point_buffer"] | None = None
    sample_radius_m: int | None = Field(default=None, ge=15, le=1500, strict=True)


def _stored_geometry(field: dict[str, Any]) -> dict[str, Any]:
    """Use the saved input geometry; never expand a point into a boundary."""
    from agronomy_agent.field_imagery import _valid_search_geometry
    metadata = field.get("metadata") or {}
    entry = metadata.get("open_agronomy_agent") or {}
    geometry = entry.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("Save a point location or field polygon before requesting imagery.")
    if geometry.get("kind") == "polygon":
        points = geometry.get("points")
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError("Stored field polygon is incomplete.")
        ring = [[point["lon"], point["lat"]] for point in points]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return _valid_search_geometry({"type": "Polygon", "coordinates": [ring]})[0]
    if geometry.get("kind") == "point":
        point = geometry.get("point")
        if not isinstance(point, dict):
            raise ValueError("Stored point location is incomplete.")
        return _valid_search_geometry({"type": "Point", "coordinates": [point.get("lon"), point.get("lat")]})[0]
    if geometry.get("type") in {"Polygon", "Point"}:
        return _valid_search_geometry(geometry)[0]
    raise ValueError("Save a point location or field polygon before requesting imagery.")


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
    from agronomy_agent.server.services import imagery_service

    @app.get("/api/demo/fields/{field_id}/imagery/analytics")
    def field_imagery_readiness(field_id: str, request: Request) -> dict[str, Any]:
        authorize(request, field_id, False)
        return imagery_service.readiness(settings)

    @app.post("/api/demo/fields/{field_id}/imagery/analyze")
    def analyze_field_scene(field_id: str, payload: FieldImageryAnalyzeRequest, request: Request) -> dict[str, Any]:
        field, _ = authorize(request, field_id, True)
        try:
            geometry = _stored_geometry(field)
            before = imagery_service.geometry_hash(geometry)
            result = imagery_service.analyze(settings, field, geometry, payload.model_dump())
            current, _ = authorize(request, field_id, True)
            if imagery_service.geometry_hash(_stored_geometry(current)) != before:
                raise HTTPException(status_code=409, detail="Field boundary changed during analysis. Run it again for the saved boundary.")
            return result
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid field geometry, imagery request or local cache configuration.") from exc

    @app.get("/api/demo/fields/{field_id}/imagery/analyses/{chip_hash}/preview.png")
    def field_imagery_preview(field_id: str, chip_hash: str, request: Request) -> Response:
        field, _ = authorize(request, field_id, False)
        try:
            geometry = _stored_geometry(field)
            image = imagery_service.preview(settings, field, geometry, chip_hash)
            current, _ = authorize(request, field_id, False)
            if imagery_service.geometry_hash(_stored_geometry(current)) != imagery_service.geometry_hash(geometry):
                image = None
        except (ValueError, KeyError, TypeError, OSError):
            image = None
        if image is None:
            raise HTTPException(status_code=404, detail="Verified imagery preview not found for the saved field boundary.")
        return Response(content=image, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

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
            geometry = _stored_geometry(field)
            result = search_field_imagery(
                geometry,
                provider_id=payload.provider_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                limit=payload.limit,
                network_mode=settings.network_mode,
            )
            current, _ = authorize(request, field_id, False)
            if imagery_service.geometry_hash(_stored_geometry(current)) != imagery_service.geometry_hash(geometry):
                raise HTTPException(status_code=409, detail="Saved field geometry changed during imagery search; try again.")
            return result
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
