from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from agronomy_agent.field_measurements import validate_field_event_payload


Mode = Literal["baseline", "agronomic_rag", "mock"]
SessionStatus = Literal["active", "paused", "archived"]
AnswerStatus = Literal["draft", "reviewed", "approved", "rejected", "exported"]
RedactionMode = Literal["none", "identifiers", "snippets_hashed", "training_safe"]
EventName = Literal[
    "session.created",
    "turn.started",
    "route.computed",
    "retrieval.completed",
    "tools.completed",
    "prompt.built",
    "answer.completed",
    "feedback.submitted",
    "reflection.created",
    "export.completed",
    "error",
]
ReplayMode = Literal["full", "route_only", "retrieve_only", "answer_only"]
ReviewScope = Literal["candidate", "approved", "rejected", "needs_more_examples", "promoted"]
AffectedComponent = Literal[
    "router",
    "retriever",
    "knowledge_graph",
    "tool",
    "system_prompt",
    "answer_planning",
    "corpus",
    "eval",
    "generation",
    "unknown",
]

FAILURE_TAGS = {
    "wrong route",
    "wrong retrieval",
    "missing source",
    "hallucinated rate",
    "evidence irrelevant",
    "bad safety",
    "insufficient proof",
    "wrong crop",
    "wrong region",
    "wrong crop/region",
    "label/legal risk",
    "missing field data",
    "unsafe certainty",
    "too vague",
    "too verbose",
    "repeated phrasing",
    "bad economics",
    "bad weather reasoning",
    "bad geospatial context",
    "bad fertility calibration",
    "missed tool",
    "good answer",
    "other",
}
ROUTE_CORRECTION_LABELS = {
    "wrong_route",
    "wrong_retrieval",
    "missing_source",
    "evidence_irrelevant",
    "hallucinated_rate",
    "label_legal_risk",
    "missing_field_data",
    "unsafe_certainty",
    "wrong_crop_region",
    "bad_weather_reasoning",
    "bad_fertility_calibration",
    "bad_economics",
    "bad_geospatial_context",
    "too_vague",
    "too_verbose",
    "repeated_phrasing",
    "good_answer",
}
EVIDENCE_FEEDBACK_ASPECTS = {
    "helpful",
    "irrelevant",
    "missing",
    "stale",
    "unsafe",
    "licensing_restricted",
}


class ConsentSchema(BaseModel):
    local_trace_capture: bool = True
    research_export_allowed: bool = False
    training_export_allowed: bool = False
    redaction_required: bool = False


class SessionContextSchema(BaseModel):
    crop: str | None = None
    region: str | None = None
    jurisdiction: str | None = None
    soil_context: str | None = None
    season: str | None = None
    notes: str | None = None
    field_context_id: str | None = None
    field_conversation_key: str | None = None
    field_record_updated_at: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    def _merge_extra(cls, values: dict[str, Any]) -> dict[str, Any]:
        known = {
            "crop",
            "region",
            "jurisdiction",
            "soil_context",
            "season",
            "notes",
            "field_context_id",
            "field_conversation_key",
            "field_record_updated_at",
        }
        extra = {k: v for k, v in values.items() if k not in known}
        values = {k: v for k, v in values.items() if k in known}
        values["extra"] = extra
        return values


class CreateSessionRequest(BaseModel):
    title: str
    user_pseudonym: str | None = None
    tags: list[str] = Field(default_factory=list)
    context: SessionContextSchema = Field(default_factory=SessionContextSchema)
    consent: ConsentSchema


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    user_pseudonym: str | None = None
    tags: list[str] | None = None
    context: SessionContextSchema | None = None
    consent: ConsentSchema | None = None
    archived: bool | None = None
    status: SessionStatus | None = None


class AccountDeleteRequest(BaseModel):
    confirm_email: str
    export_acknowledged: bool = False

    @field_validator("confirm_email")
    def _validate_confirm_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("confirm_email is required")
        return normalized


class PasswordSignupRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None

    @field_validator("email")
    def _validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("valid email is required")
        return normalized

    @field_validator("password")
    def _validate_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("password must be at least 12 characters")
        if len(value) > 512:
            raise ValueError("password is too long")
        if not value.strip():
            raise ValueError("password is required")
        return value

    @field_validator("display_name")
    def _validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class PasswordLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    def _validate_login_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("valid email is required")
        return normalized


class LocalPairingRequest(BaseModel):
    token: str

    @field_validator("token")
    def _validate_token(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 32 or len(stripped) > 256:
            raise ValueError("pairing token is invalid")
        return stripped


class EmailVerificationRequest(BaseModel):
    token: str

    @field_validator("token")
    def _validate_token(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 32:
            raise ValueError("token is invalid")
        return stripped


class PasswordResetRequest(BaseModel):
    email: str

    @field_validator("email")
    def _validate_reset_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("valid email is required")
        return normalized


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("token")
    def _validate_token(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 32:
            raise ValueError("token is invalid")
        return stripped

    @field_validator("new_password")
    def _validate_new_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("password must be at least 12 characters")
        if len(value) > 512:
            raise ValueError("password is too long")
        if not value.strip():
            raise ValueError("password is required")
        return value


class TraceOptions(BaseModel):
    store_prompt_messages: bool = False
    store_retrieved_text: bool = False
    redaction_mode: RedactionMode = "none"


class CreateTurnRequest(BaseModel):
    message: str
    mode: Mode
    model_id: str | None = None
    rag_config: str | None = None
    max_tokens: int = 360
    session_context: dict[str, Any] = Field(default_factory=dict)
    trace_options: TraceOptions = Field(default_factory=TraceOptions)

    @field_validator("message")
    def _validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is required")
        return value

    @field_validator("max_tokens")
    def _validate_max_tokens(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_tokens must be greater than 0")
        return value


class FeedbackRequest(BaseModel):
    session_id: str
    turn_id: str
    rating: int | None = None
    accepted: bool | None = None
    failure_tags: list[str] = Field(default_factory=list)
    correction: str | None = None
    ideal_answer: str | None = None
    reviewer_notes: str | None = None
    route_correct: bool | None = None
    route_correction_labels: list[str] = Field(default_factory=list)
    evidence_feedback: list[dict[str, Any]] = Field(default_factory=list)
    answer_status: AnswerStatus | None = None

    @field_validator("rating")
    def _validate_rating(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 1 or value > 5:
            raise ValueError("rating must be between 1 and 5")
        return value

    @field_validator("failure_tags")
    def _validate_failure_tags(cls, value: list[str]) -> list[str]:
        invalid = [tag for tag in value if tag not in FAILURE_TAGS]
        if invalid:
            raise ValueError(f"invalid failure tags: {', '.join(sorted(set(invalid)))}")
        return value

    @field_validator("route_correction_labels")
    def _validate_route_correction_labels(cls, value: list[str]) -> list[str]:
        invalid = [tag for tag in value if tag not in ROUTE_CORRECTION_LABELS]
        if invalid:
            raise ValueError(
                f"invalid route correction labels: {', '.join(sorted(set(invalid)))}",
            )
        return value


class ReflectionRequest(BaseModel):
    session_id: str
    turn_id: str
    observation: str
    evidence: list[str] = Field(default_factory=list)
    failure_hypothesis: str
    proposed_rule: str
    affected_component: AffectedComponent
    counterexample_risk: str | None = None
    confidence: float | None = None
    review_status: ReviewScope = "candidate"
    reviewer_id: str = "local_user"

    @field_validator("confidence")
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("observation", "failure_hypothesis", "proposed_rule")
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be empty")
        return value


class RouteSnapshot(BaseModel):
    question_type: str
    risk_level: str
    namespaces: list[str]
    required_tools: list[str]
    query_expansion: list[str] = Field(default_factory=list)
    answer_style: str | None = None
    audience: str | None = None
    guidance: str | None = None


class RetrievedDocSnapshot(BaseModel):
    rank: int
    doc_id: str
    title: str
    source_type: str
    source: str
    score: float
    snippet: str | None = None
    tags: list[str] = Field(default_factory=list)


class GraphHitSnapshot(BaseModel):
    rank: int
    node_id: str
    name: str
    kind: str
    evidence: str
    neighbors: list[str] = Field(default_factory=list)


class ToolInvocationSnapshot(BaseModel):
    name: str
    text: str | None = None
    payload: dict[str, Any] | None = None


class TurnTracePayload(BaseModel):
    route: RouteSnapshot | dict | None = None
    coverage_checklist: list[str] = Field(default_factory=list)
    retrieved_docs: list[RetrievedDocSnapshot] = Field(default_factory=list)
    graph_hits: list[GraphHitSnapshot] = Field(default_factory=list)
    tool_invocations: list[ToolInvocationSnapshot] = Field(default_factory=list)
    prompt_messages: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class ObjectivesPayload(BaseModel):
    safety: float | None = None
    correctness: float | None = None
    completeness: float | None = None
    relevance: float | None = None
    conciseness: float | None = None
    uncertainty_calibration: float | None = None
    route_correctness: float | None = None
    retrieval_support: float | None = None
    tool_use: float | None = None
    latency_ms: int | None = None


class ReflectionPayload(BaseModel):
    observation: str | None = None
    evidence: list[str] = Field(default_factory=list)
    failure_hypothesis: str | None = None
    proposed_rule: str | None = None
    affected_component: AffectedComponent | None = None
    counterexample_risk: str | None = None
    confidence: float | None = None
    review_status: ReviewScope = "candidate"
    reviewer_id: str = "local_user"


class FeedbackPayload(BaseModel):
    rating: int | None = None
    accepted: bool | None = None
    failure_tags: list[str] = Field(default_factory=list)
    correction: str | None = None
    ideal_answer: str | None = None
    reviewer_notes: str | None = None
    route_correct: bool | None = None
    route_correction_labels: list[str] = Field(default_factory=list)
    evidence_feedback: list[dict[str, Any]] = Field(default_factory=list)
    answer_status: AnswerStatus | None = None


class TurnPayload(BaseModel):
    turn_id: str
    parent_turn_id: str | None = None
    created_at: str
    user_message: str
    answer: str
    answer_status: AnswerStatus = "draft"
    system_state: dict[str, Any]
    trace: TurnTracePayload
    feedback: FeedbackPayload = Field(default_factory=FeedbackPayload)
    reflection: ReflectionPayload | None = None
    objectives: ObjectivesPayload = Field(default_factory=ObjectivesPayload)


class SessionRecord(BaseModel):
    session_id: str
    created_at: str
    updated_at: str | None = None
    title: str
    user_pseudonym: str | None = None
    tags: list[str] = Field(default_factory=list)
    consent: ConsentSchema
    context: SessionContextSchema
    turns: list[TurnPayload] = Field(default_factory=list)
    archived: bool = False
    status: str = "active"


class DataSourceRequest(BaseModel):
    source_id: str | None = None
    source_type: str
    path: str | None = None
    url: str | None = None
    owner: str | None = None
    license_status: str | None = None
    refresh_policy: str = "manual"
    training_eligible: bool = False

    @model_validator(mode="after")
    def _validate_source(self) -> "DataSourceRequest":
        if not self.path and not self.url:
            raise ValueError("either path or url is required")
        return self


class DataSourceRecord(BaseModel):
    source_id: str
    source_type: str
    path: str | None = None
    url: str | None = None
    owner: str | None = None
    license_status: str = "unknown"
    training_eligible: bool = False
    refresh_policy: str = "manual"
    checksum: str | None = None
    inspection: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ReplayRequest(BaseModel):
    base_turn_id: str
    mode: Mode | None = None
    model_id: str | None = None
    rag_config: str | None = None
    max_tokens: int | None = None
    top_k: int | None = None
    trace_options: TraceOptions = Field(default_factory=TraceOptions)
    pipeline: ReplayMode = "full"
    override_session_context: dict[str, Any] | None = None

    @field_validator("max_tokens")
    def _validate_max_tokens(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("max_tokens must be greater than 0")
        return value

    @field_validator("top_k")
    def _validate_top_k(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("top_k must be greater than 0")
        return value


class ExportRequest(BaseModel):
    session_id: str
    turn_ids: list[str] | None = None
    redaction_mode: RedactionMode = "snippets_hashed"
    include_turns: bool = True
    include_data_sources: bool = True
    include_artifacts: bool = True


class ExportManifestItem(BaseModel):
    file: str
    checksum: str


class ExportManifestPayload(BaseModel):
    export_id: str
    created_at: str
    session_id: str
    redaction_mode: RedactionMode
    training_eligible: bool
    training_exclusion_reason: str | None = None
    files: list[ExportManifestItem]
    checksums: dict[str, str]
    model_id: str | None = None
    prompt_version: str
    rag_config: str | None = None
    corpus_audit_id: str | None = None
    source_manifest_hashes: list[str] = Field(default_factory=list)


class EventPayload(BaseModel):
    id: int | None = None
    session_id: str
    turn_id: str | None = None
    event_name: EventName
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class HealthPayload(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    backend_version: str
    corpus_audit_id: str | None = None
    model_configured: str
    default_rag_config: str
    db_path: str


HostedMode = Literal["baseline", "agronomic_rag", "image_rag_research"]
TraceCaptureLevel = Literal["none", "operational", "research_opt_in"]
HostedRole = Literal["owner", "admin", "researcher", "adviser", "viewer"]
HostedActor = Literal["user", "assistant", "system", "worker", "reviewer"]
HostedRating = Literal["good", "needs_work", "unsafe", "irrelevant", "unknown"]
ChangeProposalComponent = Literal["prompt", "router", "retriever", "tool", "corpus", "eval", "image_adapter"]
ChangeProposalType = Literal[
    "prompt_patch",
    "router_patch",
    "retriever_patch",
    "tool_patch",
    "corpus_patch",
    "eval_patch",
    "image_adapter_patch",
]
ChangeProposalStatus = Literal["candidate", "needs_eval", "approved_for_rollout", "rejected", "retired"]


class OrganizationCreate(BaseModel):
    name: str
    slug: str | None = None
    plan: str = "demo"

    @field_validator("name")
    def _validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value.strip()


class WorkspaceCreate(BaseModel):
    organization_id: UUID
    name: str
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    def _validate_workspace_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value.strip()


class MembershipCreate(BaseModel):
    email: str
    display_name: str | None = None
    role: HostedRole = "viewer"

    @field_validator("email")
    def _validate_member_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("valid email is required")
        return value


class WorkspaceInviteCreate(BaseModel):
    email: str
    role: HostedRole = "viewer"
    expires_in_hours: int = 72

    @field_validator("email")
    def _validate_invite_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("valid email is required")
        return value

    @field_validator("expires_in_hours")
    def _validate_invite_expiry(cls, value: int) -> int:
        if value < 1 or value > 720:
            raise ValueError("expires_in_hours must be between 1 and 720")
        return value


class WorkspaceInviteAccept(BaseModel):
    token: str

    @field_validator("token")
    def _validate_invite_token(cls, value: str) -> str:
        token = value.strip()
        if len(token) < 32 or "." not in token:
            raise ValueError("invite token is invalid")
        return token


class ThreadCreate(BaseModel):
    workspace_id: UUID
    title: str
    field_context_id: UUID | None = None
    mode: HostedMode = "agronomic_rag"
    trace_capture_level: TraceCaptureLevel = "operational"
    model_profile_id: str | None = None
    rag_config_id: str | None = None
    training_eligible: bool = False

    @field_validator("title")
    def _validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title is required")
        return value.strip()


class ThreadConsentUpdate(BaseModel):
    trace_capture_level: TraceCaptureLevel | None = None
    training_eligible: bool | None = None
    redaction_status: Literal["not_required", "pending", "redacted", "reviewed", "rejected"] | None = None

    @model_validator(mode="after")
    def _require_update(self) -> "ThreadConsentUpdate":
        if self.trace_capture_level is None and self.training_eligible is None and self.redaction_status is None:
            raise ValueError("at least one thread consent field is required")
        return self


class AccountConsentUpdate(BaseModel):
    confirm_email: str
    trace_storage_enabled: bool | None = None
    feedback_use_allowed: bool | None = None
    training_candidate_allowed: bool | None = None
    public_anonymized_examples_allowed: bool | None = None
    product_updates_allowed: bool | None = None
    retention_preference: Literal["default", "short", "delete_on_request"] | None = None

    @model_validator(mode="after")
    def _require_update(self) -> "AccountConsentUpdate":
        if (
            self.trace_storage_enabled is None
            and self.feedback_use_allowed is None
            and self.training_candidate_allowed is None
            and self.public_anonymized_examples_allowed is None
            and self.product_updates_allowed is None
            and self.retention_preference is None
        ):
            raise ValueError("at least one account consent field is required")
        return self

    @field_validator("confirm_email")
    def _validate_confirm_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email:
            raise ValueError("confirm_email must be an email address")
        return email


class ChatRequest(BaseModel):
    thread_id: UUID | None = None
    workspace_id: UUID
    message: str
    field_context_id: UUID | None = None
    attachment_ids: list[UUID] = Field(default_factory=list)
    mode: HostedMode = "agronomic_rag"
    model_profile_id: str | None = None
    trace_capture_level: TraceCaptureLevel = "operational"
    research_consent: bool = False
    rag_config_id: str | None = None
    max_tokens: int = 360

    @field_validator("message")
    def _validate_chat_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is required")
        return value

    @field_validator("max_tokens")
    def _validate_chat_max_tokens(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_tokens must be greater than 0")
        return value


class FieldContextCreate(BaseModel):
    workspace_id: UUID
    display_name: str
    region_text: str
    country: str | None = None
    province_state: str | None = None
    county_rm: str | None = None
    crop_current: str | None = None
    crop_year: int | None = None
    soil_series_or_texture: str | None = None
    drainage_class: str | None = None
    irrigation_status: str | None = None
    soil_test_summary: str | None = None
    crop_rotation_notes: str | None = None
    management_notes: str | None = None
    known_constraints: list[str] = Field(default_factory=list)
    sensitivity: Literal["low", "medium", "high"] = "medium"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display_name", "region_text")
    def _validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value.strip()


class FieldContextUpdate(BaseModel):
    display_name: str | None = None
    region_text: str | None = None
    country: str | None = None
    province_state: str | None = None
    county_rm: str | None = None
    crop_current: str | None = None
    crop_year: int | None = None
    soil_series_or_texture: str | None = None
    drainage_class: str | None = None
    irrigation_status: str | None = None
    soil_test_summary: str | None = None
    crop_rotation_notes: str | None = None
    management_notes: str | None = None
    known_constraints: list[str] | None = None
    sensitivity: Literal["low", "medium", "high"] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("display_name", "region_text")
    def _validate_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value

    @model_validator(mode="after")
    def _require_update(self) -> "FieldContextUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field context field is required")
        return self


class FieldEventCreate(BaseModel):
    event_type: Literal["observation", "sample", "operation", "decision", "outcome", "note", "correction"]
    occurred_at: datetime | None = None
    payload: dict[str, Any]
    provenance: dict[str, Any] = Field(default_factory=dict)
    corrects_event_id: UUID | None = None

    @field_validator("payload")
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload is required")
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 50_000:
            raise ValueError("payload is too large")
        validate_field_event_payload(value)
        return value

    @field_validator("provenance")
    def _validate_provenance(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 20_000:
            raise ValueError("provenance is too large")
        return value

    @model_validator(mode="after")
    def _validate_correction(self) -> "FieldEventCreate":
        if self.event_type == "correction" and self.corrects_event_id is None:
            raise ValueError("correction events require corrects_event_id")
        if self.event_type != "correction" and self.corrects_event_id is not None:
            raise ValueError("corrects_event_id is only valid for correction events")
        return self


class FieldEventSyncRecord(BaseModel):
    schema_version: Literal["open_agronomy_agent.field_event.v1"]
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    field_context_id: UUID
    recorded_by_user_id: UUID
    event_type: Literal["observation", "sample", "operation", "decision", "outcome", "note", "correction"]
    occurred_at: str
    payload: dict[str, Any]
    provenance: dict[str, Any] = Field(default_factory=dict)
    corrects_event_id: UUID | None = None
    previous_event_sha256: str | None = None
    integrity_sha256: str
    recorded_at: str

    @field_validator("previous_event_sha256", "integrity_sha256")
    def _validate_sync_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError("field-event synchronization hashes must be 64 lowercase hexadecimal characters")
        return normalized

    @field_validator("occurred_at", "recorded_at")
    def _validate_sync_timestamp(cls, value: str) -> str:
        normalized = value.strip()
        parsed_value = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        try:
            parsed = datetime.fromisoformat(parsed_value)
        except ValueError as exc:
            raise ValueError("field-event synchronization timestamps must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("field-event synchronization timestamps must include a timezone")
        return normalized

    @field_validator("payload")
    def _validate_sync_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload is required")
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 50_000:
            raise ValueError("payload is too large")
        validate_field_event_payload(value)
        return value

    @field_validator("provenance")
    def _validate_sync_provenance(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 20_000:
            raise ValueError("provenance is too large")
        return value

    @model_validator(mode="after")
    def _validate_sync_correction(self) -> "FieldEventSyncRecord":
        if self.event_type == "correction" and self.corrects_event_id is None:
            raise ValueError("correction events require corrects_event_id")
        if self.event_type != "correction" and self.corrects_event_id is not None:
            raise ValueError("corrects_event_id is only valid for correction events")
        return self


class FieldEventSyncRequest(BaseModel):
    schema_version: Literal["open_agronomy_agent.field_event_sync.v1"]
    source_device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    base_head_sha256: str | None = None
    events: list[FieldEventSyncRecord] = Field(min_length=1, max_length=100)

    @field_validator("base_head_sha256")
    def _validate_base_head_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError("base_head_sha256 must be 64 lowercase hexadecimal characters")
        return normalized


class HostedDataSourceCreate(BaseModel):
    workspace_id: UUID
    source_id: str
    title: str
    publisher: str | None = None
    canonical_url: str | None = None
    source_path: str | None = None
    text_content: str | None = None
    license_state: str = "unknown"
    rag_eligible: bool = False
    sft_eligible: bool = False
    source_kind: str
    crops: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    buckets: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id", "title", "source_kind")
    def _validate_data_source_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value


class HostedDataSourceUpdate(BaseModel):
    title: str | None = None
    publisher: str | None = None
    canonical_url: str | None = None
    source_path: str | None = None
    text_content: str | None = None
    license_state: str | None = None
    rag_eligible: bool | None = None
    sft_eligible: bool | None = None
    source_kind: str | None = None
    crops: list[str] | None = None
    regions: list[str] | None = None
    buckets: list[str] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("title", "source_kind", "license_state")
    def _validate_optional_data_source_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value

    @model_validator(mode="after")
    def _require_update(self) -> "HostedDataSourceUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one data source field is required")
        return self


class AttachmentCreate(BaseModel):
    workspace_id: UUID
    thread_id: UUID | None = None
    filename: str = "field-notes.txt"
    content_type: str = "text/plain"
    text_content: str | None = None
    base64_content: str | None = None
    modality: Literal["text", "image", "multimodal"] = "text"
    sensitivity: Literal["low", "medium", "high"] = "medium"
    retention_policy: Literal["default", "short", "extended", "delete_on_request"] = "delete_on_request"
    crop: str | None = None
    region: str | None = None

    @field_validator("filename")
    def _validate_filename(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("filename is required")
        if "/" in value or "\\" in value:
            raise ValueError("filename must not contain path separators")
        return value

    @field_validator("content_type")
    def _validate_content_type(cls, value: str) -> str:
        allowed = {"text/plain", "text/markdown", "application/json", "application/pdf", "image/jpeg", "image/png", "image/webp"}
        if value not in allowed:
            raise ValueError(f"unsupported content_type: {value}")
        return value

    @model_validator(mode="after")
    def _validate_attachment_content(self) -> "AttachmentCreate":
        is_image = self.content_type.startswith("image/") or self.modality in {"image", "multimodal"}
        if is_image:
            if not self.base64_content:
                raise ValueError("base64_content is required for image attachments")
            if len(self.base64_content.encode("utf-8")) > 7_000_000:
                raise ValueError("base64_content must be 7MB or smaller")
            if self.modality == "text":
                self.modality = "image"
            return self
        if self.content_type == "application/pdf":
            if not self.base64_content:
                raise ValueError("base64_content is required for PDF attachments")
            if len(self.base64_content.encode("utf-8")) > 7_000_000:
                raise ValueError("base64_content must be 7MB or smaller")
            return self
        if not self.text_content or not self.text_content.strip():
            raise ValueError("text_content is required")
        encoded_len = len(self.text_content.encode("utf-8"))
        if encoded_len > 1_000_000:
            raise ValueError("text_content must be 1MB or smaller")
        return self


class GeoPriorsQuery(BaseModel):
    workspace_id: UUID
    location_text: str
    field_context_id: UUID | None = None

    @field_validator("location_text")
    def _validate_location_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("location_text is required")
        if len(value) > 500:
            raise ValueError("location_text must be 500 characters or fewer")
        return value


class HostedFeedbackCreate(BaseModel):
    rating: HostedRating
    failure_tags: list[str] = Field(default_factory=list)
    human_correction: str | None = None
    ideal_answer: str | None = None
    training_consent: bool = False


class ReflectionCandidateCreate(BaseModel):
    thread_id: UUID
    target_component: Literal["router", "retriever", "tool", "prompt", "corpus", "eval", "image_adapter"]
    lesson: str
    candidate_rule: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("lesson")
    def _validate_lesson(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("lesson is required")
        return value.strip()


class ReflectionReviewRequest(BaseModel):
    status: Literal["candidate", "approved_for_eval", "promoted", "rejected", "retired"]
    notes: str | None = None


class EvalCandidateReviewRequest(BaseModel):
    review_status: Literal["pending", "approved_for_suite", "rejected", "retired"]
    notes: str | None = None


class EvalRunCreate(BaseModel):
    workspace_id: UUID
    name: str = "Hosted eval replay"
    include_statuses: list[Literal["approved_for_suite", "promoted"]] = Field(default_factory=lambda: ["approved_for_suite"])

    @field_validator("name")
    def _validate_eval_run_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value.strip()


class ChangeProposalCreate(BaseModel):
    workspace_id: UUID
    title: str
    target_component: ChangeProposalComponent
    proposal_type: ChangeProposalType
    summary: str
    rationale: str | None = None
    linked_reflection_id: UUID | None = None
    linked_eval_run_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "summary")
    def _validate_change_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value.strip()

    @field_validator("rationale")
    def _normalize_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class Phase5OptimizationCandidateCreate(BaseModel):
    workspace_id: UUID
    candidate_type: Literal["router_rule", "query_expansion", "retrieval_ranking", "context_packing", "tool_contract", "answer_renderer", "prompt_template"]
    parent_version: str | None = None
    candidate_version: str
    generated_from_trace_ids: list[UUID] = Field(default_factory=list)
    reflection_summary: str | None = None
    patch: dict[str, Any]
    eval_summary: dict[str, Any] = Field(default_factory=dict)
    rollback_plan: str

    @field_validator("candidate_version", "rollback_plan")
    def _validate_candidate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value.strip()


class Phase5OptimizationCandidateReview(BaseModel):
    eval_summary: dict[str, Any] = Field(default_factory=dict)


class Phase5SftCandidateCreate(BaseModel):
    trace_id: UUID
    repair_layer: Literal[
        "router_rule",
        "query_expansion",
        "retrieval_ranking",
        "corpus_gap",
        "context_packing",
        "tool_contract",
        "answer_renderer",
        "prompt_template",
        "model_generation",
        "ui_confusion",
        "user_missing_context",
        "training_candidate",
    ] = "training_candidate"
    failure_class: str | None = None
    labels: dict[str, Any] = Field(default_factory=dict)


class Phase5SftCandidateReview(BaseModel):
    review_status: Literal["approved", "rejected", "pending"]
    labels: dict[str, Any] = Field(default_factory=dict)


class Phase5AdapterRegistryUpsert(BaseModel):
    workspace_id: UUID
    adapter_id: str
    base_model_id: str
    method: Literal["lora", "qlora", "prompt_only", "none"] = "qlora"
    status: Literal["planned", "candidate", "demo", "blocked", "archived"] = "planned"
    artifact_uri: str | None = None
    eval_summary: dict[str, Any] = Field(default_factory=dict)
    rollback_plan: str

    @field_validator("adapter_id", "base_model_id", "rollback_plan")
    def _validate_adapter_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value.strip()


class Phase5ModelRegistryUpsert(BaseModel):
    workspace_id: UUID
    model_id: str
    quantization: str
    context_window: int
    hardware_profile: str
    license: str
    latency_profile: dict[str, Any] = Field(default_factory=dict)
    eval_profile: dict[str, Any] = Field(default_factory=dict)
    release_status: Literal["demo", "candidate", "blocked", "archived"] = "candidate"
    notes: str | None = None

    @field_validator("model_id", "quantization", "hardware_profile", "license")
    def _validate_model_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value.strip()

    @field_validator("context_window")
    def _validate_context_window(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("context_window must be greater than 0")
        return value

    @field_validator("notes")
    def _normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ChangeProposalReviewRequest(BaseModel):
    review_status: ChangeProposalStatus
    notes: str | None = None


class ThreadExportRequest(BaseModel):
    export_type: Literal[
        "json",
        "markdown",
        "csv",
        "zip",
        "thread_report",
        "field_context_brief",
        "source_evidence_bundle",
        "diagnostic_checklist",
        "learning_trace_export",
        "data_source_audit",
        "demo_eval_snapshot",
    ] = "json"
    redaction_status: Literal["not_required", "pending", "redacted", "reviewed", "rejected"] = "not_required"


class FrontendRumMetricRequest(BaseModel):
    schema_version: Literal["phase6.frontend_rum.v1"] = "phase6.frontend_rum.v1"
    metric_name: Literal[
        "LCP",
        "CLS",
        "INP",
        "TTI",
        "long_task",
        "render_time",
        "open_time",
        "first_visible_progress",
        "open_interaction",
        "standard_thread_report_preview",
        "model_download_notice",
    ]
    value: float = Field(ge=0)
    unit: Literal["ms", "score", "count"] = "ms"
    rating: Literal["good", "needs_improvement", "poor", "unknown"] = "unknown"
    route: str = Field(default="/", min_length=1, max_length=160)
    workspace_id: str | None = Field(default=None, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    navigation_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FrontendEventRequest(BaseModel):
    schema_version: Literal["phase6.frontend_event.v1"] = "phase6.frontend_event.v1"
    event_name: Literal[
        "app_shell_loaded",
        "auth_flow_started",
        "auth_flow_completed",
        "auth_flow_failed",
        "field_context_created",
        "field_context_edited",
        "field_context_used",
        "thread_created",
        "message_submitted",
        "answer_stream_started",
        "answer_stream_first_token",
        "answer_stream_completed",
        "answer_stream_cancelled",
        "evidence_drawer_opened",
        "report_export_started",
        "report_export_completed",
        "report_export_failed",
        "feedback_submitted",
        "webgpu_probe_completed",
        "local_model_download_started",
        "local_model_download_completed",
        "local_model_download_cancelled",
        "local_model_download_failed",
        "error_boundary_triggered",
        "hidden_template_leak_detected_client",
    ]
    route: str = Field(default="/", min_length=1, max_length=160)
    workspace_id: str | None = Field(default=None, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    navigation_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageRagQuery(BaseModel):
    workspace_id: UUID
    thread_id: UUID | None = None
    question: str
    attachment_ids: list[UUID] = Field(default_factory=list)
    crop: str | None = None
    region: str | None = None

    @field_validator("question")
    def _validate_image_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question is required")
        return value.strip()


class ImageEvalSample(BaseModel):
    sample_id: str
    expected_label: str
    predicted_label: str | None = None
    predicted_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    relevant_attachment_ids: list[str] = Field(default_factory=list)
    retrieved_attachment_ids: list[str] = Field(default_factory=list)
    expected_ood: bool = False
    abstained: bool = False
    answer_text: str = ""

    @field_validator("sample_id", "expected_label")
    def _validate_eval_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value

    @model_validator(mode="after")
    def _validate_prediction(self) -> "ImageEvalSample":
        if not self.abstained and not self.predicted_label:
            raise ValueError("predicted_label is required unless abstained is true")
        if not self.abstained and self.predicted_confidence is None:
            raise ValueError("predicted_confidence is required unless abstained is true")
        return self


class ImageEvalRequest(BaseModel):
    workspace_id: UUID
    top_k: int = Field(default=5, ge=1, le=50)
    confidence_bins: int = Field(default=10, ge=1, le=25)
    samples: list[ImageEvalSample] = Field(min_length=1)
