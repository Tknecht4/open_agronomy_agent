"""Authorized farm/season endpoints; local persistence is an explicit capability."""
from __future__ import annotations

from datetime import date
from uuid import UUID
from typing import Any, Callable, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agronomy_agent.server.storage import farm_store, field_record_store
from agronomy_agent.server.schemas import FieldEventCreate
from agronomy_agent.server.services import farm_summary, field_enrichment
from agronomy_agent.server.storage import field_context_store


class FarmCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)


class FarmUpdate(FarmCreate):
    expected_revision: int = Field(ge=1, strict=True)
    archived: bool = False


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    farm_id: str | None = Field(default=None, max_length=80)
    expected_revision: int = Field(ge=0, strict=True)


class SeasonCrop(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    crop: str = Field(min_length=1, max_length=120)
    cultivar: str | None = Field(default=None, max_length=120)


class SeasonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, strict=True)
    crop: str | None = Field(default=None, max_length=120)
    cultivar: str | None = Field(default=None, max_length=120)
    crops: list[SeasonCrop] | None = Field(default=None, max_length=12)
    crop_system: Literal["unknown", "single", "intercrop", "sequence", "separate_areas"] = "unknown"
    planted_at: date | None = None
    harvested_at: date | None = None

    @field_validator("crop", "cultivar")
    @classmethod
    def empty_is_unknown(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def dates_in_order(self) -> "SeasonUpdate":
        if self.planted_at and self.harvested_at and self.harvested_at < self.planted_at:
            raise ValueError("Harvest cannot precede planting")
        if self.crops is not None:
            if self.crop or self.cultivar:
                raise ValueError("Use structured crops or the single crop fields, not both")
            names = [item.crop.casefold() for item in self.crops]
            if len(names) != len(set(names)):
                raise ValueError("Enter each crop once")
            count = len(self.crops)
            if count > 1 and self.crop_system not in {"intercrop", "sequence", "separate_areas"}:
                raise ValueError("Select how the multiple crops share the field")
            if count <= 1 and self.crop_system not in {"unknown", "single"}:
                raise ValueError("This crop system requires at least two crops")
            self.crop_system = "single" if count == 1 else "unknown" if count == 0 else self.crop_system
        elif self.crop_system not in {"unknown", "single"}:
            raise ValueError("Multiple crop systems require structured crops")
        return self


class EnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str] = Field(min_length=1, max_length=4)

    @field_validator("sources")
    @classmethod
    def allowlisted(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or not set(values) <= field_context_store.SOURCES:
            raise ValueError("Select distinct weather, soil, crop_cover or imagery sources")
        return values


class RecordBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    events: list[FieldEventCreate] = Field(min_length=1, max_length=50)


class LocationConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_updated_at: str = Field(min_length=1, max_length=80)


def register_farm_routes(app: FastAPI, *, store: Any, settings: Any,
    workspace_authorize: Callable[[Request, bool, str | None], tuple[dict[str, Any], dict[str, Any]]],
    field_authorize: Callable[[Request, str, bool], tuple[dict[str, Any], dict[str, Any]]],
    normalize_field: Callable[..., dict[str, Any]],
) -> None:
    def local() -> None:
        from agronomy_agent.server.storage.db import TraceStore
        if not isinstance(store, TraceStore):
            raise HTTPException(503, "Farm persistence is available on the local SQLite runtime; this backend has not been migrated.")

    def call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/farms")
    def farms(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
        workspace, _ = workspace_authorize(request, False, workspace_id)
        local()
        return {"workspace_id": workspace["id"], "farms": farm_store.list_farms(store, workspace["id"]), "unassigned_label": "Unassigned fields"}

    @app.post("/api/farms", status_code=201)
    def create_farm(payload: FarmCreate, request: Request, workspace_id: str | None = None) -> dict[str, Any]:
        workspace, actor = workspace_authorize(request, True, workspace_id)
        local()
        return call(farm_store.save_farm, store, workspace["id"], actor["id"], payload.name)

    @app.get("/api/farms/overview")
    def all_farms_overview(request: Request, season: int | None = Query(default=None, ge=1900, le=2200),
                           workspace_id: str | None = None, unassigned: bool = False) -> dict[str, Any]:
        workspace, _ = workspace_authorize(request, False, workspace_id)
        local()
        return farm_summary.overview(store, workspace["id"], season=season, unassigned=unassigned)

    @app.get("/api/farms/{farm_id}")
    def farm(farm_id: str, request: Request, workspace_id: str | None = None) -> dict[str, Any]:
        workspace, _ = workspace_authorize(request, False, workspace_id)
        local()
        return call(farm_store.get_farm, store, workspace["id"], farm_id)

    @app.patch("/api/farms/{farm_id}")
    def update_farm(farm_id: str, payload: FarmUpdate, request: Request, workspace_id: str | None = None) -> dict[str, Any]:
        workspace, actor = workspace_authorize(request, True, workspace_id)
        local()
        return call(farm_store.save_farm, store, workspace["id"], actor["id"], payload.name,
            farm_id=farm_id, expected_revision=payload.expected_revision, archived=payload.archived)

    @app.get("/api/farms/{farm_id}/overview")
    def farm_overview(farm_id: str, request: Request, season: int | None = Query(default=None, ge=1900, le=2200), workspace_id: str | None = None) -> dict[str, Any]:
        workspace, _ = workspace_authorize(request, False, workspace_id)
        local()
        selected = call(farm_store.get_farm, store, workspace["id"], farm_id)
        return {**farm_summary.overview(store, workspace["id"], farm_id=farm_id, season=season), "farm": selected}

    @app.patch("/api/fields/{field_id}/farm")
    def move_field(field_id: str, payload: Assignment, request: Request) -> dict[str, Any]:
        field, actor = field_authorize(request, field_id, True)
        local()
        return call(farm_store.assign_field, store, field["workspace_id"], actor["id"], field_id, payload.farm_id, payload.expected_revision)

    @app.put("/api/fields/{field_id}/seasons/{season}")
    def update_season(field_id: str, season: int, payload: SeasonUpdate, request: Request) -> dict[str, Any]:
        field, actor = field_authorize(request, field_id, True)
        local()
        if not 1900 <= season <= 2200:
            raise HTTPException(422, "Season must be a year between 1900 and 2200")
        return call(farm_store.save_season, store, field["workspace_id"], actor["id"], field_id, season,
            payload.model_dump(mode="json", exclude={"expected_revision"}), payload.expected_revision)

    @app.get("/api/fields/{field_id}/summary")
    def summary(field_id: str, request: Request, season: int | None = Query(default=None, ge=1900, le=2200)) -> dict[str, Any]:
        field, _ = field_authorize(request, field_id, False)
        local()
        return farm_summary.field_summary(store, field, season)

    @app.get("/api/records")
    def records(request: Request, workspace_id: str | None = None, farm_id: str | None = None,
                field_id: str | None = None, season: int | None = Query(default=None, ge=1900, le=2200),
                event_type: Literal["observation", "sample", "operation", "decision", "outcome", "note", "correction"] | None = None,
                offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200)) -> dict[str, Any]:
        if field_id:
            field, _ = field_authorize(request, field_id, False)
            workspace_id = field["workspace_id"]
        workspace, _ = workspace_authorize(request, False, workspace_id)
        local()
        if farm_id and farm_id != "unassigned":
            call(farm_store.get_farm, store, workspace["id"], farm_id)
        return field_record_store.timeline(store, workspace["id"], farm_id=farm_id, field_id=field_id, season=season, event_type=event_type, offset=offset, limit=limit)

    @app.get("/api/fields/{field_id}/location-suggestions")
    def location_suggestions(field_id: str, request: Request) -> dict[str, Any]:
        field, _ = field_authorize(request, field_id, False)
        from agronomy_agent.server.services.field_location import suggestions
        return suggestions(field)

    @app.post("/api/fields/{field_id}/confirm-location")
    def confirm_location(field_id: str, payload: LocationConfirmation, request: Request) -> dict[str, Any]:
        field, actor = field_authorize(request, field_id, True)
        local()
        from agronomy_agent.server.services.field_location import suggestions
        candidate = next((row for row in suggestions(field)["candidates"] if row["id"] == payload.suggestion_id and row["confirmable"]), None)
        if candidate is None:
            raise HTTPException(409, "The mapped suggestion changed or is ambiguous. Check the saved boundary and source again.")
        previous = field["metadata"]["open_agronomy_agent"]
        confirmation = {"role": "grower_confirmed_location", "suggestion": candidate, "confirmed_by": actor["id"],
            "boundary": "User confirmation of location for source routing; not legal jurisdiction or cadastral authority."}
        normalized = normalize_field({"name": field["display_name"], "field": {**previous["field"], "jurisdiction": candidate["province"]},
            "geometry": previous["geometry"], "regionalContext": previous.get("regional_context_label"),
            "sourceBoundary": previous.get("source_boundary")}, previous_open_metadata=previous, confirmed_location=confirmation)
        updated = call(store.update_phase4_field_context, field_context_id=field_id, actor_user_id=actor["id"],
            expected_updated_at=payload.expected_updated_at, payload=normalized)
        return {"id": field_id, "country": updated["country"], "province": updated["province_state"]}

    @app.post("/api/fields/{field_id}/records", status_code=201)
    def save_records(field_id: str, payload: RecordBundle, request: Request) -> dict[str, Any]:
        field, actor = field_authorize(request, field_id, True)
        local()
        return call(field_record_store.append_bundle, store, field, actor["id"], str(payload.operation_id),
            [event.model_dump(mode="json", exclude_none=True) for event in payload.events])

    @app.post("/api/fields/{field_id}/enrichment-jobs", status_code=202)
    def request_enrichment(field_id: str, payload: EnrichmentRequest, request: Request, background: BackgroundTasks) -> dict[str, Any]:
        field, _ = field_authorize(request, field_id, True)
        local()
        try:
            job, created = field_context_store.queue_job(store, field, payload.sources, settings.network_mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        if created:
            background.add_task(field_enrichment.execute_job, store, settings, job["id"])
        return job

    def authorized_job(request: Request, job_id: str, write: bool) -> dict[str, Any]:
        local()
        job = field_context_store.get_job(store, job_id)
        if not job:
            raise HTTPException(404, "Field update not found")
        field_authorize(request, job["field_id"], write)
        return job

    @app.get("/api/enrichment-jobs/{job_id}")
    def enrichment_status(job_id: str, request: Request) -> dict[str, Any]:
        return authorized_job(request, job_id, False)

    @app.post("/api/enrichment-jobs/{job_id}/cancel")
    def cancel_enrichment(job_id: str, request: Request) -> dict[str, Any]:
        authorized_job(request, job_id, True)
        field_context_store.cancel_job(store, job_id)
        return field_context_store.get_job(store, job_id)
