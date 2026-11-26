"""Thin HTTP boundary for deterministic field map analysis."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from agronomy_agent.server.services import geospatial_service as geo
from agronomy_agent.server.services.field_map_analysis import MAX_REQUEST_BYTES, analyze_field_map


def register_map_analysis_routes(app: FastAPI, settings: Any) -> None:
    local_analysis = asyncio.Lock()

    @app.post("/api/geo/field-analysis")
    async def field_analysis(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="request exceeds 1 MiB limit")
        if set(payload) - {"geometry", "layers"}:
            raise HTTPException(status_code=422, detail="only geometry and layers are accepted")
        layer_ids = payload.get("layers")
        uses_local_pack = isinstance(layer_ids, list) and any(
            isinstance(layer_id, str) and (layer := geo.REGION_LAYERS.get(layer_id)) is not None
            and layer.query_backend == "local_sqlite"
            for layer_id in layer_ids
        )
        arguments = {"geometry": payload.get("geometry"), "layer_ids": layer_ids, "network_mode": settings.network_mode}
        try:
            if uses_local_pack:
                # Large unions wait off the worker pool and cannot run in parallel.
                async with local_analysis:
                    if await request.is_disconnected():
                        raise HTTPException(status_code=408, detail="request closed before analysis started")
                    return await run_in_threadpool(analyze_field_map, **arguments)
            return await run_in_threadpool(analyze_field_map, **arguments)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
