"""Thin HTTP boundary for deterministic field map analysis."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException

from agronomy_agent.server.services.field_map_analysis import MAX_REQUEST_BYTES, analyze_field_map


def register_map_analysis_routes(app: FastAPI, settings: Any) -> None:
    @app.post("/api/geo/field-analysis")
    def field_analysis(payload: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="request exceeds 128 KiB limit")
        if set(payload) - {"geometry", "layers"}:
            raise HTTPException(status_code=422, detail="only geometry and layers are accepted")
        try:
            return analyze_field_map(
                geometry=payload.get("geometry"),
                layer_ids=payload.get("layers"),
                network_mode=settings.network_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
