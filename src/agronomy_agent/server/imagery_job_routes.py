"""Authorized durable imagery jobs; client locations and worker paths are rejected."""
from __future__ import annotations

import threading
from typing import Any, Callable
from uuid import UUID, uuid5, NAMESPACE_URL

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from agronomy_agent.server.field_data_routes import FieldImageryAnalyzeRequest
from agronomy_agent.server.storage import imagery_job_store as jobs
from agronomy_agent.server.services import imagery_service

_SLOT = threading.BoundedSemaphore(1)


class ImageRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    season: int | None = Field(default=None, ge=1900, le=2200, strict=True)


class ImageryJobRequest(FieldImageryAnalyzeRequest):
    operation_id: UUID
    expected_geometry_revision_id: str = Field(min_length=1, max_length=80)


def execute_job(store: Any, settings: Any, job_id: str) -> None:
    with _SLOT:
        job = jobs.get_job(store, job_id)
        if not job or job["status"] != "queued":
            return
        field = store.get_phase4_field_context(job["field_id"])
        if not field:
            jobs.set_status(store, job_id, "failed", {"status": "unavailable", "reason": "Field no longer available"})
            return
        jobs.set_status(store, job_id, "running")
        try:
            result = imagery_service.analyze(settings, field, job["geometry"], job["request"])
            with store._cursor() as cursor:
                current = cursor.execute("SELECT revision_id FROM field_geometry_current WHERE field_id=?", (field["id"],)).fetchone()
            status = "completed" if result["status"] in {"available", "empty_valid_area"} else "failed"
            if not current or current[0] != job["geometry_revision_id"]:
                status = "superseded"
            jobs.set_status(store, job_id, status, result)
        except Exception:
            jobs.set_status(store, job_id, "failed", {"status": "unavailable", "reason": "The bounded image worker failed. Review setup or retry."})


def register_imagery_job_routes(app: FastAPI, *, store: Any, settings: Any, authorize: Callable) -> None:
    def local() -> None:
        from agronomy_agent.server.storage.db import TraceStore
        if not isinstance(store, TraceStore):
            raise HTTPException(503, "Image history requires the migrated local runtime")

    def accessible(request: Request, job_id: str, write: bool = False) -> tuple[dict, dict]:
        local()
        job = jobs.get_job(store, job_id)
        if not job:
            raise HTTPException(404, "Image analysis not found")
        field, _ = authorize(request, job["field_id"], write)
        return field, job

    def public(job: dict) -> dict:
        with store._cursor() as cursor:
            current = cursor.execute("SELECT revision_id FROM field_geometry_current WHERE field_id=?", (job["field_id"],)).fetchone()
        result = {**job, "current_geometry": bool(current and current[0] == job["geometry_revision_id"])}
        if job["result"]:
            result["result"] = {**job["result"], "preview_url": f"/api/imagery-jobs/{job['id']}/preview.png" if job["result"].get("chip_hash") else None}
        return result

    @app.post("/api/fields/{field_id}/imagery-jobs", status_code=202)
    def create_job(field_id: str, payload: ImageryJobRequest, request: Request, background: BackgroundTasks) -> dict:
        field, _ = authorize(request, field_id, True)
        local()
        values = payload.model_dump(exclude={"operation_id", "expected_geometry_revision_id"})
        try:
            # Validate provider/scene/dates/support before accepting a durable job.
            from agronomy_agent.server.field_data_routes import _stored_geometry
            imagery_service.request_identity(_stored_geometry(field), values)
            job, created = jobs.queue(store, field, values, str(payload.operation_id), payload.expected_geometry_revision_id)
        except ValueError as exc:
            raise HTTPException(409 if "changed" in str(exc) or "identity" in str(exc) else 422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        if created:
            background.add_task(execute_job, store, settings, job["id"])
        return public(job)

    @app.get("/api/fields/{field_id}/imagery-jobs")
    def history(field_id: str, request: Request) -> dict:
        authorize(request, field_id, False)
        local()
        return {"jobs": [public(job) for job in jobs.list_jobs(store, field_id)], "limit": 30}

    @app.get("/api/imagery-jobs/{job_id}")
    def status(job_id: str, request: Request) -> dict:
        _, job = accessible(request, job_id)
        return public(job)

    @app.post("/api/imagery-jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request) -> dict:
        accessible(request, job_id, True)
        jobs.cancel(store, job_id)
        return public(jobs.get_job(store, job_id))

    @app.post("/api/imagery-jobs/{job_id}/record", status_code=201)
    def record_reference(job_id: str, payload: ImageRecordRequest, request: Request) -> dict:
        field, job = accessible(request, job_id, True)
        _, actor = authorize(request, field["id"], True)
        result = job.get("result") or {}
        if job["status"] not in {"completed", "superseded"} or not result.get("chip_hash"):
            raise HTTPException(409, "Only a verified completed analysis can be linked")
        if imagery_service.preview(settings, field, job["geometry"], result["chip_hash"]) is None:
            raise HTTPException(409, "The retained analysis failed artifact verification")
        from agronomy_agent.server.storage.field_record_store import append_bundle
        source = result.get("source") or {}
        if not source.get("acquired_at"):
            raise HTTPException(409, "The retained analysis has no acquisition date; it cannot become a dated record")
        event = {"event_type": "note", "occurred_at": source["acquired_at"],
            "payload": {"summary": f"Satellite analysis reference: {source.get('scene_id')}, acquired {source.get('acquired_at')}. Processed spectral observation only; not a grower observation, diagnosis or management recommendation.",
                **({"season": payload.season} if payload.season is not None else {}),
                "imagery_analysis": {"job_id": job_id, "geometry_revision_id": job["geometry_revision_id"],
                    "chip_hash": result["chip_hash"], "provider_id": result["provider_id"], "scene_id": result["scene_id"],
                    "process_version": result["process_version"], "support_assessment": result.get("support_assessment"), "zonal_stats": result.get("zonal_stats")}},
            "provenance": {"capture_method": "linked_processed_imagery", "evidence_role": "processed_observation", "field_action_authority": "not_authorized", "result_sha256": job["result_sha256"]}}
        operation = str(uuid5(NAMESPACE_URL, f"open-agronomy:image-reference:{job_id}:{payload.season}"))
        return append_bundle(store, field, actor["id"], operation, [event])

    @app.get("/api/imagery-jobs/{job_id}/overlay")
    def overlay(job_id: str, request: Request) -> dict:
        field, job = accessible(request, job_id)
        result = job.get("result") or {}
        if job["status"] not in {"completed", "superseded"} or not result.get("chip_hash"):
            raise HTTPException(404, "No verified map overlay for this analysis")
        image = imagery_service.map_overlay(settings, field, job["geometry"], result["chip_hash"])
        if image is None:
            raise HTTPException(404, "Verified map overlay is unavailable; use the native preview")
        return {**image, "geometry_revision_id": job["geometry_revision_id"], "current_geometry": public(job)["current_geometry"]}

    @app.get("/api/imagery-jobs/{job_id}/preview.png")
    def preview(job_id: str, request: Request) -> Response:
        field, job = accessible(request, job_id)
        result = job.get("result") or {}
        if job["status"] not in {"completed", "superseded"} or not result.get("chip_hash"):
            raise HTTPException(404, "No verified preview for this analysis")
        # Historical previews bind to the original authorized geometry, not today's shape.
        image = imagery_service.preview(settings, field, job["geometry"], result["chip_hash"])
        if image is None:
            raise HTTPException(404, "Verified preview is unavailable")
        return Response(content=image, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
