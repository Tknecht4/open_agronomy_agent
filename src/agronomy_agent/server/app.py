from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
import zlib
import uuid
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

import yaml
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.staticfiles import StaticFiles

from agronomy_agent.agent import load_model_config, local_model_snapshot_status, phase5_cache_stats
from agronomy_agent.field_events import FieldEventSyncError
from agronomy_agent.knowledge_updates import read_activation, validate_activation_freshness
from agronomy_agent.paths import repo_path
from agronomy_agent.phase5_optimization import candidate_promotion_gate
from agronomy_agent.phase5_reports import model_registry_comparison, stage_latency_report
from agronomy_agent.phase5_sft import (
    contains_private_field_data,
    has_explicit_private_training_consent,
    is_held_out_eval_trace,
    redact_training_text,
    source_evidence_from_trace_payload,
)
from agronomy_agent.server.schemas import (
    AccountConsentUpdate,
    AccountDeleteRequest,
    AttachmentCreate,
    ChangeProposalCreate,
    ChangeProposalReviewRequest,
    ChatRequest,
    CreateSessionRequest,
    CreateTurnRequest,
    DataSourceRequest,
    EmailVerificationRequest,
    EvalCandidateReviewRequest,
    EvalRunCreate,
    ExportRequest,
    FeedbackRequest,
    FieldContextCreate,
    FieldEventCreate,
    FieldEventSyncRequest,
    FieldContextUpdate,
    FrontendEventRequest,
    FrontendRumMetricRequest,
    GeoPriorsQuery,
    HostedDataSourceCreate,
    HostedDataSourceUpdate,
    HostedFeedbackCreate,
    ImageEvalRequest,
    ImageRagQuery,
    LocalPairingRequest,
    MembershipCreate,
    OrganizationCreate,
    PasswordLoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordSignupRequest,
    Phase5AdapterRegistryUpsert,
    Phase5ModelRegistryUpsert,
    Phase5OptimizationCandidateCreate,
    Phase5OptimizationCandidateReview,
    Phase5SftCandidateCreate,
    Phase5SftCandidateReview,
    ReplayRequest,
    ReflectionCandidateCreate,
    ReflectionReviewRequest,
    ReflectionRequest,
    SessionUpdateRequest,
    ThreadCreate,
    ThreadConsentUpdate,
    ThreadExportRequest,
    WorkspaceInviteAccept,
    WorkspaceInviteCreate,
    WorkspaceCreate,
)
from agronomy_agent.server.services.chat_service import run_turn
from agronomy_agent.server.services.answer_renderer import render_structured_answer
from agronomy_agent.server.services.attachment_scanner import (
    AttachmentRejected,
    AttachmentScanError,
    AttachmentScanInput,
    LocalAttachmentScanner,
    build_attachment_scanner,
)
from agronomy_agent.server.services.benchmark_service import (
    aiagribench_submission_freeze_manifest,
    benchmark_artifact_download,
    human_review_batches_summary,
    human_review_outcome_summary,
    human_review_queue_packet,
    latest_aiagribench_proxy_summary,
    open_agronomy_benchmark_summary,
    public_demo_rehearsal_packet,
    public_shadow_heldout_packet,
)
from agronomy_agent.server.services.datasource_service import inspect_source, read_checksum, run_local_data_source_ingest
from agronomy_agent.server.services.eval_service import eval_run_gates, eval_run_metrics
from agronomy_agent.server.services.export_service import build_export_bundle, create_phase4_thread_export
from agronomy_agent.server.services.geospatial_service import (
    REGION_LAYERS,
    attach_region_intersections_to_upload,
    intersect_region_layers,
    layer_catalog,
    official_layer_status,
    parse_boundary_upload,
    query_region_layers,
    validate_geojson_geometry,
)
from agronomy_agent.server.services.image_eval_service import evaluate_image_research_samples
from agronomy_agent.server.services.image_observation import HttpVlmObservationAdapter, LocalImageObservationAdapter
from agronomy_agent.server.services.image_rag_service import image_embedding_search, image_quality_payload
from agronomy_agent.server.services.knowledge_coverage_service import canadian_knowledge_coverage
from agronomy_agent.server.services.leak_guard import LEAK_GUARD_VERSION, detect_prompt_leaks
from agronomy_agent.server.services.model_decision_service import conference_model_decision
from agronomy_agent.server.services.model_adaptation_service import (
    model_adaptation_readiness,
)
from agronomy_agent.server.services.privacy_boundary import (
    data_use_statement,
    minimized_field_context_snapshot,
    public_export_record,
)
from agronomy_agent.server.services.replay_service import replay_turn
from agronomy_agent.server.services.retrieval_service import retrieve_only
from agronomy_agent.server.services.router_service import route_query
from agronomy_agent.server.services.tool_service import public_adapter_readiness, run_local_tool
from agronomy_agent.server.observability import build_telemetry, log_request, request_id
from agronomy_agent.server.queue import JobQueueUnavailable, build_job_queue
from agronomy_agent.server.rate_limit import FixedWindowRateLimiter, RateLimiterUnavailable, RedisFixedWindowRateLimiter
from agronomy_agent.server.settings import ServerSettings, build_settings, make_corpus_audit_id
from agronomy_agent.server.storage.object_store import build_object_store
from agronomy_agent.server.storage.runtime import build_trace_store, storage_db_path_for, storage_label_for
from agronomy_agent.server.trace_timer import PHASE5_TURN_METRICS_SCHEMA_VERSION, TraceProfiler


_ANSWER_TIME_COVERAGE_LIST_FIELDS = (
    "registered_source_ids",
    "distributable_source_ids",
    "retrieved_source_ids",
    "retrieved_context_source_ids",
)


def _answer_time_knowledge_coverage(trace: Any) -> dict[str, Any]:
    """Return a minimized snapshot of the Canadian coverage state stored with a turn."""

    metadata = trace.get("metadata") if isinstance(trace, dict) and isinstance(trace.get("metadata"), dict) else {}
    agno_runtime = metadata.get("agno_runtime") if isinstance(metadata.get("agno_runtime"), dict) else {}
    if "canadian_coverage_boundaries" in metadata:
        raw_boundaries = metadata.get("canadian_coverage_boundaries")
        record_source = "trace_metadata"
    elif "canadian_coverage_boundaries" in agno_runtime:
        raw_boundaries = agno_runtime.get("canadian_coverage_boundaries")
        record_source = "legacy_agno_runtime_metadata"
    else:
        return {
            "schema_version": "open_agronomy_agent.answer_time_knowledge_coverage.v1",
            "capture_status": "not_captured",
            "record_source": None,
            "boundaries": [],
        }

    if not isinstance(raw_boundaries, list):
        return {
            "schema_version": "open_agronomy_agent.answer_time_knowledge_coverage.v1",
            "capture_status": "invalid_snapshot",
            "record_source": record_source,
            "boundaries": [],
        }

    boundaries: list[dict[str, Any]] = []
    for raw_boundary in raw_boundaries[:20]:
        if not isinstance(raw_boundary, dict):
            continue
        jurisdiction = str(raw_boundary.get("jurisdiction") or "").strip()[:120]
        status = str(raw_boundary.get("status") or "").strip()[:120]
        if not jurisdiction or not status:
            continue
        boundary: dict[str, Any] = {
            "jurisdiction": jurisdiction,
            "status": status,
            "requires_prompt_boundary": (
                raw_boundary.get("requires_prompt_boundary")
                if isinstance(raw_boundary.get("requires_prompt_boundary"), bool)
                else None
            ),
        }
        for field in _ANSWER_TIME_COVERAGE_LIST_FIELDS:
            values = raw_boundary.get(field)
            boundary[field] = (
                list(dict.fromkeys(str(value).strip()[:240] for value in values if str(value).strip()))[:100]
                if isinstance(values, list)
                else []
            )
        boundaries.append(boundary)

    return {
        "schema_version": "open_agronomy_agent.answer_time_knowledge_coverage.v1",
        "capture_status": (
            "captured"
            if boundaries
            else ("captured_no_boundary" if not raw_boundaries else "invalid_snapshot")
        ),
        "record_source": record_source,
        "boundaries": boundaries,
    }


def _plan_quebec_lidar_pack_for_web(
    field_geometry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from agronomy_agent.offline_context_packs import (
        plan_quebec_lidar_field_pack,
        public_quebec_lidar_pack_receipt,
    )

    plan = plan_quebec_lidar_field_pack(field_geometry=field_geometry)
    return plan, public_quebec_lidar_pack_receipt(plan)


def _read_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    loaded = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _corpus_audit(settings: ServerSettings, store: Any) -> str:
    cfg = _read_json(repo_path("configs/rag.yaml"))
    retrieval = cfg.get("retrieval", {})
    corpus_paths = retrieval.get("corpus_paths") or [
        retrieval.get("corpus_path", "data/seed/agronomy_rag_corpus.jsonl"),
    ]
    corpus_paths = [str(path) for path in corpus_paths]
    digest = hashlib.sha256()
    corpus_count = 0
    for path in corpus_paths:
        p = repo_path(path)
        if p.exists() and p.is_file():
            digest.update(p.read_bytes())
            with p.open("r", encoding="utf-8") as handle:
                corpus_count += sum(1 for line in handle if line.strip())
    audit_id = make_corpus_audit_id(corpus_paths)
    store.create_corpus_audit(audit_id, ",".join(corpus_paths), digest.hexdigest(), corpus_count)
    return audit_id


def _build_image_observation_adapter(settings: ServerSettings) -> LocalImageObservationAdapter | HttpVlmObservationAdapter:
    if settings.vlm_observation_backend == "http":
        if not settings.vlm_observation_endpoint:
            raise ValueError("AGRONOMY_AGENT_VLM_OBSERVATION_ENDPOINT is required when VLM observation backend is http")
        return HttpVlmObservationAdapter(
            endpoint=settings.vlm_observation_endpoint,
            api_key=settings.vlm_observation_api_key,
            timeout_seconds=settings.vlm_observation_timeout_seconds,
        )
    return LocalImageObservationAdapter()


def _coerce_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("value must be integer")
    return int(value)


def _safe_int_from_request(value: Any, *, default: int, min_value: int, max_value: int | None = None) -> int:
    try:
        parsed = _coerce_int(value, default=default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value}") from exc
    if parsed < min_value:
        raise ValueError(f"value must be >= {min_value}")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"value must be <= {max_value}")
    return parsed


def _chunk_text_for_stream(value: str, *, chunk_size: int = 120) -> list[str]:
    if not value:
        return []
    if chunk_size <= 0:
        return [value]
    return [value[index : index + chunk_size] for index in range(0, len(value), chunk_size)]


STREAM_PROGRESS_STAGE_COPY: dict[str, dict[str, Any]] = {
    "agent.route.classify": {
        "label": "Routing agronomic question",
        "detail": "Classified topic, risk, and answer boundary before retrieval.",
        "progress": 18,
        "category": "routing",
    },
    "agent.tools.public_adapters": {
        "label": "Checking public sources",
        "detail": "Ran configured field-context source checks such as soil, weather, crop-cover, ET, or crop statistics.",
        "progress": 30,
        "category": "public sources",
    },
    "agent.tools.public_label_adapter": {
        "label": "Checking product source",
        "detail": "Checked public product metadata when the question included a product, ingredient, or registration clue.",
        "progress": 34,
        "category": "public sources",
    },
    "agent.tools.public_source_cards": {
        "label": "Checking public guidance cards",
        "detail": "Matched deterministic public guidance lanes for disease, economics, conservation, records, or storage context.",
        "progress": 38,
        "category": "public sources",
    },
    "agent.rag.lexical_search": {
        "label": "Retrieving local guidance",
        "detail": "Searched the local public-domain RAG corpus for evidence to support the answer.",
        "progress": 46,
        "category": "retrieval",
    },
    "agent.kg.search": {
        "label": "Checking knowledge graph",
        "detail": "Looked for graph context connected to the routed agronomy topic.",
        "progress": 50,
        "category": "retrieval",
    },
    "agent.tools.run_guard_notes": {
        "label": "Running guard checks",
        "detail": "Applied deterministic agronomy boundaries for labels, rates, diagnosis, weather, and missing field evidence.",
        "progress": 56,
        "category": "guard checks",
    },
    "agent.context.pack": {
        "label": "Building answer context",
        "detail": "Packed map context, retrieved evidence, graph hints, public-source notes, and field details for the local model.",
        "progress": 64,
        "category": "context",
    },
    "agent.prompt.build_messages": {
        "label": "Preparing local model input",
        "detail": "Prepared the final local-model input without exposing hidden prompt text in the UI.",
        "progress": 70,
        "category": "context",
    },
    "model.queue_wait": {
        "label": "Checking local model queue",
        "detail": "Verified the local generation queue is inside the configured wait budget.",
        "progress": 74,
        "category": "model",
    },
    "model.load_or_reuse": {
        "label": "Loading local model",
        "detail": "Loaded or reused the configured local model for this answer.",
        "progress": 78,
        "category": "model",
    },
    "model.decode_stream": {
        "label": "Generating answer locally",
        "detail": "Generated the draft answer on the local model.",
        "progress": 84,
        "category": "model",
    },
    "agent.answer.postprocess": {
        "label": "Formatting evidence",
        "detail": "Converted the draft into the public answer contract with evidence cards and missing-data prompts.",
        "progress": 88,
        "category": "answer",
    },
    "agent.answer.leak_check": {
        "label": "Checking answer boundaries",
        "detail": "Checked the answer for hidden prompt leakage and unsupported internal wording.",
        "progress": 90,
        "category": "answer",
    },
    "thread.persist_trace": {
        "label": "Saving trace",
        "detail": "Saved the answer, evidence trace, and metrics for review.",
        "progress": 91,
        "category": "trace",
    },
}


def _stream_progress_event_from_span(
    span: dict[str, Any],
    *,
    started: float,
    emitted_stages: set[str],
) -> dict[str, Any] | None:
    stage = str(span.get("stage") or "")
    copy = STREAM_PROGRESS_STAGE_COPY.get(stage)
    if not copy or stage in emitted_stages:
        return None
    status = str(span.get("status") or "ok")
    if status == "skipped":
        return None
    emitted_stages.add(stage)
    duration_ms = span.get("duration_ms")
    label = str(copy["label"])
    detail = str(copy["detail"])
    if status == "error":
        label = f"{label} needs attention"
        detail = "That backend stage reported an error; the final answer should show the missing evidence or failure boundary."
    return {
        "label": label,
        "detail": detail,
        "progress": copy["progress"],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "stage_id": stage,
        "stage_status": status,
        "duration_ms": duration_ms,
        "category": copy["category"],
    }


def _stream_field_context_detail(payload: CreateTurnRequest) -> str:
    field_context = payload.session_context.get("field_context") if isinstance(payload.session_context, dict) else None
    if not isinstance(field_context, dict):
        return "Preparing the user question; no map field context was attached to this request."
    context_bits = []
    if field_context.get("representative_point"):
        context_bits.append("representative point")
    if field_context.get("geometry"):
        context_bits.append("field geometry")
    if field_context.get("regional_intersections"):
        context_bits.append("regional intersections")
    if field_context.get("selected_upload_feature"):
        context_bits.append("selected upload feature")
    if not context_bits:
        context_bits.append("field notes")
    return f"Preparing {', '.join(context_bits)} for retrieval, public-source checks, and trace capture."


def _merge_context(base: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update({key: value for key, value in updates.items() if value is not None})
    return merged


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or f"org-{uuid.uuid4().hex[:8]}"


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _field_event_sync_http_error(exc: FieldEventSyncError) -> HTTPException:
    conflict_codes = {
        "divergent_head",
        "partial_overlap",
        "event_id_collision",
        "local_chain_invalid",
        "unknown_base_head",
    }
    return HTTPException(
        status_code=409 if exc.code in conflict_codes else 422,
        detail={
            "code": exc.code,
            "message": str(exc),
            **exc.context,
            "boundary": (
                "Field-history synchronization is fast-forward only. Divergent histories are preserved "
                "for human reconciliation and are never silently merged."
            ),
        },
    )


def _hash_phase6_auth_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_phase6_auth_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_phase6_password(password: str, *, salt: bytes | None = None, iterations: int = 210_000) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        ]
    )


def _verify_phase6_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = _b64url_decode(salt_raw)
        expected = _b64url_decode(digest_raw)
    except (ValueError, binascii.Error):
        return False
    observed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(observed, expected)


def _estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return max(1, int(len(str(text)) / 4)) if text else 0


def _answer_has_risk_banner(answer: str) -> bool:
    lowered = answer.lower()
    return any(term in lowered for term in ["label", "verify", "caution", "risk", "do not", "before any product"])


def _answer_has_missing_data(answer: str) -> bool:
    lowered = answer.lower()
    return any(term in lowered for term in ["missing", "ask for", "need", "check", "before making", "field history"])


def _model_quantization(model_id: str) -> str | None:
    lowered = model_id.lower()
    if "4bit" in lowered or "4-bit" in lowered:
        return "4-bit"
    if "8bit" in lowered or "8-bit" in lowered:
        return "8-bit"
    if model_id == "mock":
        return "mock"
    return None


def _phase5_tool_precision_recall(trace: dict[str, Any]) -> tuple[float | None, float | None]:
    route = trace.get("route", {}) if isinstance(trace, dict) else {}
    expected = {
        str(item)
        for item in (route.get("required_tools") or [])
        if str(item).strip()
    }
    actual = {
        str(item.get("name") or item.get("tool_name") or "")
        for item in (trace.get("tool_invocations", []) or [])
        if isinstance(item, dict) and str(item.get("name") or item.get("tool_name") or "").strip()
    }
    if not expected and not actual:
        return None, None
    true_positive = len(expected & actual)
    precision = true_positive / max(1, len(actual)) if actual else 0.0
    recall = true_positive / max(1, len(expected)) if expected else None
    return round(precision, 4), round(recall, 4) if recall is not None else None


def _phase5_feedback_score(rating: str | None) -> float | None:
    return {
        "good": 1.0,
        "needs_work": 0.4,
        "irrelevant": 0.2,
        "unsafe": 0.0,
    }.get(str(rating or "").strip().lower())


def _latest_phase5_metrics_for_thread(store: Any, thread: dict[str, Any]) -> dict[str, Any] | None:
    for metrics in store.list_phase5_turn_metrics(thread["workspace_id"], limit=5000):
        if metrics.get("thread_id") == thread["id"]:
            return metrics
    return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(float(ordered[index]), 3)


def _phase5_latency_dashboard(metrics: list[dict[str, Any]], spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    latencies = [float(row["total_latency_ms"]) for row in metrics if row.get("total_latency_ms") is not None]
    by_route: dict[str, list[float]] = {}
    for row in metrics:
        route = str(row.get("route_question_type") or "unknown")
        if row.get("total_latency_ms") is not None:
            by_route.setdefault(route, []).append(float(row["total_latency_ms"]))
    return {
        "turn_count": len(metrics),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "by_route": {
            route: {
                "turn_count": len(values),
                "p50": _percentile(values, 0.50),
                "p95": _percentile(values, 0.95),
            }
            for route, values in sorted(by_route.items())
        },
        "stage_latency": stage_latency_report(spans or []),
        "leak_failures": sum(1 for row in metrics if not row.get("leak_check_passed")),
        "cache": phase5_cache_stats(),
    }


PHASE6_FRONTEND_RUM_BUDGETS: dict[str, dict[str, Any]] = {
    "LCP": {"target": 2500.0, "unit": "ms", "area": "home/app shell", "launch_gate": "blocker"},
    "INP": {"target": 200.0, "unit": "ms", "area": "all primary routes", "launch_gate": "blocker"},
    "CLS": {"target": 0.1, "unit": "score", "area": "all primary routes", "launch_gate": "blocker"},
    "TTI": {"target": 2000.0, "unit": "ms", "area": "login -> app shell", "launch_gate": "blocker"},
    "render_time": {"target": 500.0, "unit": "ms", "area": "thread list", "launch_gate": "blocker"},
    "open_time": {"target": 800.0, "unit": "ms", "area": "existing thread", "launch_gate": "blocker"},
    "first_visible_progress": {"target": 500.0, "unit": "ms", "area": "answer stream", "launch_gate": "blocker"},
    "long_task": {"target": 50.0, "unit": "ms", "area": "trace/debug drawer", "launch_gate": "blocker"},
    "open_interaction": {"target": 150.0, "unit": "ms", "area": "evidence drawer", "launch_gate": "blocker"},
    "standard_thread_report_preview": {"target": 3000.0, "unit": "ms", "area": "report preview", "launch_gate": "blocker"},
    "model_download_notice": {"target": 1.0, "unit": "count", "area": "local model preview", "launch_gate": "blocker"},
}


def _frontend_rum_budget_status(metric_name: str, value: float) -> dict[str, Any]:
    budget = PHASE6_FRONTEND_RUM_BUDGETS.get(metric_name)
    if not budget:
        return {"budgeted": False, "status": "monitor", "target": None, "unit": None}
    target = float(budget["target"])
    return {
        "budgeted": True,
        "status": "pass" if (value >= target if metric_name == "model_download_notice" else value <= target) else "fail",
        "target": target,
        "unit": budget["unit"],
        "area": budget["area"],
        "launch_gate": budget["launch_gate"],
    }


def _frontend_rum_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_metric: dict[str, list[float]] = {}
    for record in records:
        by_metric.setdefault(str(record.get("metric_name") or "unknown"), []).append(float(record.get("value") or 0.0))
    return {
        "schema_version": "phase6.frontend_rum_summary.v1",
        "sample_count": len(records),
        "budgets": PHASE6_FRONTEND_RUM_BUDGETS,
        "metrics": {
            metric_name: {
                "count": len(values),
                "p75": _percentile(values, 0.75),
                "max": round(max(values), 3) if values else None,
                "budget_status": _frontend_rum_budget_status(metric_name, _percentile(values, 0.75) or 0.0),
            }
            for metric_name, values in sorted(by_metric.items())
        },
    }


def _safe_frontend_rum_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    redacted_fields: list[str] = []
    for key, value in list(metadata.items())[:20]:
        key_text = _safe_frontend_metadata_key(key)
        restricted_reason = _restricted_frontend_metadata_reason(key_text)
        if restricted_reason:
            safe[key_text] = {"type": type(value).__name__, "redacted": True, "reason": restricted_reason}
            redacted_fields.append(key_text)
            continue
        if isinstance(value, str):
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{0,80}", value):
                safe[key_text] = {"type": "str", "redacted": True, "reason": "restricted_value"}
                redacted_fields.append(key_text)
            else:
                safe[key_text] = value[:80]
        elif isinstance(value, bool) or isinstance(value, (int, float)):
            safe[key_text] = value
        elif value is None:
            safe[key_text] = None
        else:
            safe[key_text] = {"type": type(value).__name__, "redacted": True, "reason": "unsupported_value"}
            redacted_fields.append(key_text)
    if redacted_fields:
        safe["redacted_fields"] = redacted_fields
    return safe


PHASE6_FRONTEND_EVENT_RESTRICTED_KEYS = {
    "answer",
    "email",
    "field_note",
    "file",
    "message",
    "note",
    "private",
    "prompt",
    "raw",
    "text",
    "upload",
}


def _safe_frontend_metadata_key(key: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
    return (normalized or "field")[:80]


def _restricted_frontend_metadata_reason(key_text: str) -> str | None:
    key_tokens = {token for token in key_text.split("_") if token}
    return "restricted_key" if key_tokens.intersection(PHASE6_FRONTEND_EVENT_RESTRICTED_KEYS) else None


def _safe_frontend_event_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:20]:
        key_text = _safe_frontend_metadata_key(key)
        if _restricted_frontend_metadata_reason(key_text):
            raise HTTPException(status_code=422, detail=f"frontend event metadata field is restricted: {key_text}")
        if isinstance(value, str):
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{0,80}", value):
                raise HTTPException(status_code=422, detail=f"frontend event metadata value is restricted: {key_text}")
            safe[key_text] = value[:80]
        elif isinstance(value, bool) or isinstance(value, (int, float)):
            safe[key_text] = value
        elif value is None:
            safe[key_text] = None
        else:
            safe[key_text] = {"type": type(value).__name__, "redacted": True}
    return safe


def _frontend_event_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for record in records:
        event_name = str(record.get("event_name") or "unknown")
        counts[event_name] = counts.get(event_name, 0) + 1
    return {
        "schema_version": "phase6.frontend_event_summary.v1",
        "sample_count": len(records),
        "events": {event_name: {"count": count} for event_name, count in sorted(counts.items())},
    }


def _phase5_dataset_card(workspace_id: str, *, candidate_count: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "phase5_sft_dataset_card_v1",
        "workspace_id": workspace_id,
        "candidate_count": candidate_count,
        "purpose": "Reviewed, consented agronomy-agent answer discipline and missing-data behavior candidates.",
        "redaction": "email_phone_regex_v1 plus hosted consent gate",
        "exclusions": [
            "unreviewed traces",
            "prompt leaks",
            "raw private field facts without explicit training consent",
            "held-out eval rows",
        ],
        "training_plan": "LoRA/QLoRA only after readiness gates pass; adapters remain independently rollbackable.",
    }


def _phase5_lora_plan(base_model_id: str) -> dict[str, Any]:
    return {
        "schema_version": "phase5_lora_qlora_plan_v1",
        "base_model_id": base_model_id,
        "first_experiment": "QLoRA adapter over reviewed SFT candidates, evaluated against the no-SFT harness baseline.",
        "rollback": "Disable adapter and route traffic to the base model plus Phase 5 harness without changing base weights.",
        "blocked_until": [
            "500-1000 reviewed consented candidates",
            "prompt leak near zero",
            "safety eval stable",
            "harness changes plateaued",
        ],
    }


def _latest_phase4_retrieved_docs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in reversed(events):
        if event.get("event_type") != "retrieval_result":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        docs = payload.get("retrieved_docs") or []
        return [doc for doc in docs if isinstance(doc, dict)]
    return []


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


TEXT_EMBEDDING_DIMENSIONS = 64


def _text_terms(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def _local_text_embedding(value: str, *, dimensions: int = TEXT_EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for term in _text_terms(value):
        bucket = int(hashlib.sha256(term.encode("utf-8")).hexdigest()[:8], 16) % dimensions
        vector[bucket] += 1.0
    norm = sum(component * component for component in vector) ** 0.5
    if not norm:
        return vector
    return [round(component / norm, 8) for component in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _lexical_overlap_score(query: str, text: str) -> float:
    query_terms = set(_text_terms(query))
    if not query_terms:
        return 0.0
    text_terms = set(_text_terms(text))
    return len(query_terms & text_terms) / len(query_terms)


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("invalid base64url segment") from exc


def _jwt_claims_checks(payload: dict[str, Any], *, issuer: str | None = None, audience: str | None = None) -> None:
    now = int(time.time())
    if payload.get("exp") is not None and int(payload["exp"]) < now:
        raise ValueError("JWT is expired")
    if payload.get("nbf") is not None and int(payload["nbf"]) > now:
        raise ValueError("JWT is not yet valid")
    if issuer and payload.get("iss") != issuer:
        raise ValueError("JWT issuer mismatch")
    if audience:
        aud = payload.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if audience not in audiences:
            raise ValueError("JWT audience mismatch")


def _decode_hs256_jwt(token: str, *, secret: str, issuer: str | None = None, audience: str | None = None) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT must have three segments")
    header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
    payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    if header.get("alg") != "HS256":
        raise ValueError("only HS256 JWTs are supported in local verifier mode")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(parts[2])
    if not hmac.compare_digest(expected, actual):
        raise ValueError("JWT signature verification failed")
    _jwt_claims_checks(payload, issuer=issuer, audience=audience)
    return payload


def _b64url_uint(value: str) -> int:
    return int.from_bytes(_b64url_decode(value), "big")


def _load_jwks(settings: ServerSettings) -> dict[str, Any]:
    if settings.jwt_jwks_json:
        loaded = json.loads(settings.jwt_jwks_json)
    elif settings.jwt_jwks_url:
        with urlopen(settings.jwt_jwks_url, timeout=5) as response:
            loaded = json.loads(response.read().decode("utf-8"))
    else:
        raise ValueError("JWT JWKS is not configured")
    if not isinstance(loaded, dict) or not isinstance(loaded.get("keys"), list):
        raise ValueError("JWT JWKS must contain a keys array")
    return loaded


def _select_jwks_key(jwks: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    keys = [key for key in jwks.get("keys", []) if isinstance(key, dict) and key.get("kty") == "RSA"]
    kid = header.get("kid")
    if kid:
        keys = [key for key in keys if key.get("kid") == kid]
    if not keys:
        raise ValueError("JWT signing key not found in JWKS")
    return keys[0]


def _verify_rs256_signature(signing_input: bytes, signature: bytes, jwk: dict[str, Any]) -> None:
    n = _b64url_uint(str(jwk.get("n") or ""))
    e = _b64url_uint(str(jwk.get("e") or ""))
    key_size = (n.bit_length() + 7) // 8
    if len(signature) != key_size:
        raise ValueError("JWT signature size mismatch")
    encoded = pow(int.from_bytes(signature, "big"), e, n).to_bytes(key_size, "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signing_input).digest()
    padding_len = key_size - len(digest_info) - 3
    if padding_len < 8:
        raise ValueError("JWT RSA key is too small")
    expected = b"\x00\x01" + (b"\xff" * padding_len) + b"\x00" + digest_info
    if not hmac.compare_digest(encoded, expected):
        raise ValueError("JWT signature verification failed")


def _decode_rs256_jwt(token: str, *, jwks: dict[str, Any], issuer: str | None = None, audience: str | None = None) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT must have three segments")
    header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
    payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    if header.get("alg") != "RS256":
        raise ValueError("only RS256 JWTs are supported in JWKS verifier mode")
    jwk = _select_jwks_key(jwks, header)
    _verify_rs256_signature(f"{parts[0]}.{parts[1]}".encode("ascii"), _b64url_decode(parts[2]), jwk)
    _jwt_claims_checks(payload, issuer=issuer, audience=audience)
    return payload


def _decode_configured_jwt(token: str, *, settings: ServerSettings) -> dict[str, Any]:
    header = json.loads(_b64url_decode(token.split(".")[0]).decode("utf-8"))
    if header.get("alg") == "HS256" and settings.jwt_secret:
        return _decode_hs256_jwt(
            token,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    if header.get("alg") == "RS256" and (settings.jwt_jwks_json or settings.jwt_jwks_url):
        return _decode_rs256_jwt(
            token,
            jwks=_load_jwks(settings),
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    raise ValueError("JWT auth is not configured for token algorithm")


def _auth_mode(settings: ServerSettings) -> str:
    local_pairing = bool(
        settings.local_pairing_token_sha256 and settings.oidc_session_secret
    )
    if _oidc_enabled(settings) and settings.allow_local_dev_auth:
        return "oidc_session_or_jwt_or_local_dev_headers"
    if _oidc_enabled(settings):
        return (
            "oidc_session_or_jwt_or_local_pairing"
            if local_pairing
            else "oidc_session_or_jwt"
        )
    if settings.jwt_secret or settings.jwt_jwks_json or settings.jwt_jwks_url:
        if settings.allow_local_dev_auth:
            return "jwt_or_local_dev_headers"
        return "jwt_or_local_pairing" if local_pairing else "jwt_only"
    if local_pairing:
        return "local_pairing_session"
    return "local_dev_headers" if settings.allow_local_dev_auth else "auth_not_configured"


def _jwt_verifier_configured(settings: ServerSettings) -> bool:
    return bool(settings.jwt_secret or settings.jwt_jwks_json or settings.jwt_jwks_url)


def _oidc_enabled(settings: ServerSettings) -> bool:
    return bool(
        settings.oidc_authorization_endpoint
        and settings.oidc_token_endpoint
        and settings.oidc_client_id
        and settings.oidc_redirect_uri
        and settings.oidc_session_secret
        and _jwt_verifier_configured(settings)
    )


def _signed_cookie_value(payload: dict[str, Any], *, secret: str) -> str:
    body = _b64url_json(payload)
    signature = hmac.new(secret.encode("utf-8"), _b64url_decode(body), hashlib.sha256).digest()
    signed = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{body}.{signed}"


def _b64url_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_signed_cookie(value: str, *, secret: str) -> dict[str, Any]:
    body, sep, signature = value.partition(".")
    if not sep:
        raise ValueError("signed cookie is missing signature")
    body_bytes = _b64url_decode(body)
    if base64.urlsafe_b64encode(body_bytes).decode("ascii").rstrip("=") != body:
        raise ValueError("signed cookie payload is not canonical base64url")
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    actual = _b64url_decode(signature)
    if base64.urlsafe_b64encode(actual).decode("ascii").rstrip("=") != signature:
        raise ValueError("signed cookie signature mismatch")
    if not hmac.compare_digest(expected, actual):
        raise ValueError("signed cookie signature mismatch")
    payload = json.loads(body_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("signed cookie payload must be an object")
    if payload.get("exp") is not None and int(payload["exp"]) < int(time.time()):
        raise ValueError("signed cookie is expired")
    return payload


def _encode_oidc_state_cookie(state: str, nonce: str, *, settings: ServerSettings) -> str:
    if not settings.oidc_session_secret:
        raise ValueError("OIDC session secret is not configured")
    return _signed_cookie_value(
        {"state": state, "nonce": nonce, "exp": int(time.time()) + 600},
        secret=settings.oidc_session_secret,
    )


def _decode_oidc_state_cookie(value: str, *, settings: ServerSettings) -> dict[str, Any]:
    if not settings.oidc_session_secret:
        raise ValueError("OIDC session secret is not configured")
    payload = _decode_signed_cookie(value, secret=settings.oidc_session_secret)
    if not payload.get("state") or not payload.get("nonce"):
        raise ValueError("OIDC state cookie is incomplete")
    return payload


def _iso_from_epoch(value: int | float) -> str:
    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()


def _encode_session_cookie(claims: dict[str, Any], *, settings: ServerSettings, session_id: str | None = None) -> str:
    if not settings.oidc_session_secret:
        raise ValueError("OIDC session secret is not configured")
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        raise ValueError("OIDC id_token must include email or preferred_username")
    name = str(claims.get("name") or claims.get("given_name") or email.split("@")[0])
    now = int(time.time())
    claim_exp = int(claims["exp"]) if claims.get("exp") is not None else now + 8 * 60 * 60
    return _signed_cookie_value(
        {
            "sub": str(claims.get("sub") or email),
            "sid": session_id or str(uuid.uuid4()),
            "email": email,
            "display_name": name,
            "csrf": secrets.token_urlsafe(24),
            "iat": now,
            "exp": min(claim_exp, now + 8 * 60 * 60),
        },
        secret=settings.oidc_session_secret,
    )


def _decode_session_cookie(value: str, *, settings: ServerSettings) -> dict[str, Any]:
    if not settings.oidc_session_secret:
        raise ValueError("OIDC session secret is not configured")
    payload = _decode_signed_cookie(value, secret=settings.oidc_session_secret)
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise ValueError("session cookie is missing email")
    exp = int(payload.get("exp") or int(time.time()))
    issued_at = int(payload.get("iat") or max(0, exp - 8 * 60 * 60))
    session_id = str(payload.get("sid") or "").strip()
    if not session_id:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"agronomy-session:{email}:{payload.get('csrf')}:{exp}"))
    return {
        "session_id": session_id,
        "email": email,
        "display_name": str(payload.get("display_name") or email.split("@")[0]),
        "sub": str(payload.get("sub") or email),
        "csrf": str(payload.get("csrf") or ""),
        "issued_at": _iso_from_epoch(issued_at),
        "expires_at": _iso_from_epoch(exp),
    }


PHASE6_WORKSPACE_INVITE_SCHEMA_VERSION = "phase6.workspace_invite.v1"


def _workspace_invite_secret(settings: ServerSettings) -> str:
    if settings.oidc_session_secret:
        return settings.oidc_session_secret
    if settings.jwt_secret:
        return settings.jwt_secret
    if settings.allow_local_dev_auth:
        return "phase6-local-dev-invite-secret"
    raise ValueError("invite signing secret is not configured")


def _encode_workspace_invite(
    *,
    settings: ServerSettings,
    organization_id: str,
    email: str,
    role: str,
    invited_by_user_id: str,
    expires_in_hours: int,
) -> tuple[str, int]:
    now = int(time.time())
    exp = now + expires_in_hours * 60 * 60
    payload = {
        "schema_version": PHASE6_WORKSPACE_INVITE_SCHEMA_VERSION,
        "organization_id": organization_id,
        "email": email.strip().lower(),
        "role": role,
        "invited_by_user_id": invited_by_user_id,
        "nonce": secrets.token_urlsafe(16),
        "iat": now,
        "exp": exp,
    }
    return _signed_cookie_value(payload, secret=_workspace_invite_secret(settings)), exp


def _decode_workspace_invite(token: str, *, settings: ServerSettings) -> dict[str, Any]:
    try:
        payload = _decode_signed_cookie(token, secret=_workspace_invite_secret(settings))
    except ValueError as exc:
        detail = "invite token is expired" if "expired" in str(exc).lower() else "invite token is invalid"
        raise HTTPException(status_code=400, detail=detail) from exc
    except (binascii.Error, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="invite token is invalid") from exc
    if payload.get("schema_version") != PHASE6_WORKSPACE_INVITE_SCHEMA_VERSION:
        raise HTTPException(status_code=400, detail="invite token is invalid")
    if not payload.get("organization_id") or not payload.get("email") or not payload.get("role"):
        raise HTTPException(status_code=400, detail="invite token is incomplete")
    return payload


def _csrf_token_from_session_cookie(value: str, *, settings: ServerSettings) -> str:
    payload = _decode_session_cookie(value, settings=settings)
    token = str(payload.get("csrf") or "")
    if not token:
        raise ValueError("session cookie is missing CSRF token")
    return token


def _requires_cookie_csrf(request: Request) -> bool:
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if request.url.path in {
        "/auth/signup",
        "/auth/verify-email",
        "/auth/password-login",
        "/auth/local-pair",
        "/auth/password-reset/request",
        "/auth/password-reset/confirm",
    }:
        return False
    if not request.cookies.get("agronomy_session"):
        return False
    if request.headers.get("authorization"):
        return False
    if request.headers.get("x-agronomy-user-email"):
        return False
    return True


def _exchange_oidc_code(code: str, *, settings: ServerSettings) -> dict[str, Any]:
    if not settings.oidc_token_endpoint or not settings.oidc_client_id or not settings.oidc_redirect_uri:
        raise ValueError("OIDC token endpoint is not configured")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
    }
    if settings.oidc_client_secret:
        form["client_secret"] = settings.oidc_client_secret
    request = UrlRequest(
        settings.oidc_token_endpoint,
        data=urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise ValueError("OIDC token response did not include id_token")
    return payload


def _cookie_secure(settings: ServerSettings) -> bool:
    return bool(
        settings.local_pairing_token_sha256
        or (settings.oidc_redirect_uri and settings.oidc_redirect_uri.startswith("https://"))
    )


def _validate_oidc_url(value: str, *, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an https URL")
    return value


def _oidc_logout_redirect_url(settings: ServerSettings, *, logout_hint: str | None = None) -> str | None:
    if not settings.oidc_logout_endpoint:
        return None
    endpoint = _validate_oidc_url(settings.oidc_logout_endpoint, label="OIDC logout endpoint")
    query: dict[str, str] = {}
    if settings.oidc_client_id:
        query["client_id"] = settings.oidc_client_id
    if settings.oidc_post_logout_redirect_uri:
        query["post_logout_redirect_uri"] = _validate_oidc_url(
            settings.oidc_post_logout_redirect_uri,
            label="OIDC post-logout redirect URI",
        )
    if logout_hint:
        query["logout_hint"] = logout_hint
    return f"{endpoint}?{urlencode(query)}" if query else endpoint


def _rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        return "bearer:" + hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    email = request.headers.get("x-agronomy-user-email", "").strip().lower()
    if email:
        return f"local:{email}"
    client_host = request.client.host if request.client else "unknown"
    return f"client:{client_host}"


def _rate_limit_exempt_path(path: str) -> bool:
    return path in {"/health", "/api/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"} or path.startswith("/assets/")


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return cleaned or f"attachment-{uuid.uuid4().hex[:8]}.txt"


def _safe_export_filename(value: str) -> str:
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid export filename")
    cleaned = _safe_filename(value)
    if cleaned != value:
        raise HTTPException(status_code=400, detail="invalid export filename")
    return cleaned


_ACCOUNT_EXPORT_INTERNAL_HANDLE_KEYS = frozenset(
    {
        "storage_uri",
        "object_uri",
        "vector",
        "embedding_vector",
    }
)


def _phase6_account_export_attachment(record: dict[str, Any]) -> dict[str, Any]:
    return _phase6_redact_account_export_internal_handles(record)


def _phase6_account_export_export(record: dict[str, Any]) -> dict[str, Any]:
    redacted = _phase6_redact_account_export_internal_handles(record)
    metadata = dict(redacted.get("metadata") or {})
    files = metadata.get("files")
    if isinstance(files, dict):
        metadata["files"] = {
            str(name): {"object_store_uri_included": False}
            for name in sorted(files)
        }
    redacted["metadata"] = metadata
    return redacted


def _phase6_redact_account_export_internal_handles(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _phase6_redact_account_export_internal_handles(item)
            for key, item in value.items()
            if str(key) not in _ACCOUNT_EXPORT_INTERNAL_HANDLE_KEYS
        }
    if isinstance(value, list):
        return [_phase6_redact_account_export_internal_handles(item) for item in value]
    return value


def _image_dimensions(content: bytes, content_type: str) -> tuple[int | None, int | None]:
    if content_type == "image/png" and len(content) >= 24 and content.startswith(b"\x89PNG\r\n\x1a\n"):
        return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
    if content_type == "image/jpeg" and content.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(content):
                break
            segment_length = int.from_bytes(content[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(content):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return int.from_bytes(content[index + 5 : index + 7], "big"), int.from_bytes(content[index + 3 : index + 5], "big")
            index += segment_length
    return None, None


def _image_fingerprint(content: bytes, width: int | None, height: int | None) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    vector = [
        float(width or 0),
        float(height or 0),
        float(len(content)),
        float(int(digest[:4], 16)),
        float(int(digest[4:8], 16)),
        float(int(digest[8:12], 16)),
    ]
    return {
        "algorithm": "sha256_dimension_stub",
        "hash": digest,
        "vector": vector,
        "dimensions": len(vector),
    }


def _scan_attachment_bytes(content: bytes, *, filename: str, content_type: str, scanner: Any) -> dict[str, Any]:
    try:
        return scanner.scan(AttachmentScanInput(content=content, filename=filename, content_type=content_type))
    except AttachmentRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AttachmentScanError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "attachment scanner unavailable",
                "backend": getattr(scanner, "backend", "unknown"),
                "fail_open": False,
                "reason": str(exc),
            },
        ) from exc


def _decode_pdf_literal_string(value: bytes) -> str:
    out = bytearray()
    index = 0
    while index < len(value):
        byte = value[index]
        if byte == 0x5C and index + 1 < len(value):
            index += 1
            escaped = value[index]
            escapes = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f"}
            out.extend(escapes.get(escaped, bytes([escaped])))
        else:
            out.append(byte)
        index += 1
    return out.decode("utf-8", errors="ignore")


def _pdf_stream_payloads(content: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    for match in re.finditer(rb"(<<.*?>>)\s*stream\r?\n?(.*?)\r?\n?endstream", content, flags=re.DOTALL):
        header, stream = match.groups()
        if b"/FlateDecode" in header:
            try:
                payloads.append(zlib.decompress(stream.strip()))
            except zlib.error:
                payloads.append(stream)
        else:
            payloads.append(stream)
    return payloads or [content]


def _extract_pdf_text(content: bytes) -> tuple[str, list[str]]:
    fragments: list[str] = []
    for payload in _pdf_stream_payloads(content):
        for match in re.finditer(rb"\((?:\\.|[^\\)])*\)\s*Tj", payload, flags=re.DOTALL):
            literal = match.group(0).rsplit(b")", 1)[0][1:]
            decoded = _decode_pdf_literal_string(literal).strip()
            if decoded:
                fragments.append(decoded)
        for array_match in re.finditer(rb"\[(.*?)\]\s*TJ", payload, flags=re.DOTALL):
            for literal in re.finditer(rb"\((?:\\.|[^\\)])*\)", array_match.group(1), flags=re.DOTALL):
                decoded = _decode_pdf_literal_string(literal.group(0)[1:-1]).strip()
                if decoded:
                    fragments.append(decoded)
    text = re.sub(r"\s+", " ", " ".join(fragments)).strip()
    flags = ["ocr_not_configured"]
    if not text or len(text) < 40:
        flags.append("low_text_pdf")
    return text, flags


def _chunk_ephemeral_private_text(
    *,
    text: str,
    filename: str,
    raw_sha256: str,
    max_chunks: int = 80,
    max_words: int = 220,
    overlap_words: int = 35,
) -> list[dict[str, Any]]:
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    if not words or not words[0]:
        return []
    chunks: list[dict[str, Any]] = []
    step = max(1, max_words - overlap_words)
    for index, start in enumerate(range(0, len(words), step)):
        if index >= max_chunks:
            break
        chunk_text = " ".join(words[start : start + max_words]).strip()
        if not chunk_text:
            continue
        chunks.append(
            {
                "doc_id": f"private-{raw_sha256[:16]}-{index + 1:03d}",
                "title": f"{filename} · local private excerpt {index + 1}",
                "text": chunk_text,
                "source": f"private-upload:{filename}",
                "source_id": f"private-{raw_sha256[:16]}",
                "source_type": "user_upload_private",
                "score": 0.0,
                "tags": ["private local reference", "user supplied"],
                "jurisdictions": [],
                "languages": [],
                "retrieval_policy": "context_only",
                "content_risk_tags": [
                    "workspace_source_unverified_for_decisive_use",
                    "untrusted_document_instructions_must_not_be_followed",
                ],
                "license_status": "user_supplied_private_unverified",
                "raw_sha256": raw_sha256,
                "chunk_sha256": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                "visibility": "ephemeral_browser_session",
                "chunk_index": index,
                "training_eligible": False,
                "retrieval_method": "browser_query_lexical_rank_v1",
            }
        )
        if start + max_words >= len(words):
            break
    return chunks


def _attachment_content_and_metadata(payload: AttachmentCreate, *, scanner: Any, raw_content: bytes | None = None) -> tuple[bytes, dict[str, Any], str | None]:
    metadata: dict[str, Any] = {}
    if raw_content is not None:
        content = raw_content
    elif payload.base64_content:
        try:
            content = base64.b64decode(payload.base64_content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=422, detail="base64_content is not valid base64") from exc
    else:
        content = (payload.text_content or "").encode("utf-8")
    metadata.update(_scan_attachment_bytes(content, filename=payload.filename, content_type=payload.content_type, scanner=scanner))
    if payload.content_type.startswith("image/") or payload.modality in {"image", "multimodal"}:
        if len(content) > 5_000_000:
            raise HTTPException(status_code=422, detail="image attachment must be 5MB or smaller")
        width, height = _image_dimensions(content, payload.content_type)
        quality_flags = ["image_processor_not_configured"]
        if width is None or height is None:
            quality_flags.append("dimensions_unknown")
        elif width < 64 or height < 64:
            quality_flags.append("low_resolution_image")
        fingerprint = _image_fingerprint(content, width, height)
        metadata["image"] = {
            "width": width,
            "height": height,
            "quality_flags": quality_flags,
            "observation_status": "not_extracted_local_stub",
            "fingerprint": fingerprint,
        }
        metadata["filters"] = {
            "crop": payload.crop.strip().lower() if payload.crop else None,
            "region": payload.region.strip().lower() if payload.region else None,
        }
        return content, metadata, None
    if payload.content_type == "application/pdf":
        if len(content) > 5_000_000:
            raise HTTPException(status_code=422, detail="PDF attachment must be 5MB or smaller")
        extracted_text, quality_flags = _extract_pdf_text(content)
        extracted = bool(extracted_text and "low_text_pdf" not in quality_flags)
        metadata["document"] = {
            "parse_status": "text_extracted" if extracted else "low_text_pdf_blocked",
            "parse_method": "local_pdf_text_stub",
            "quality_flags": quality_flags if extracted else [*quality_flags, "not_indexed_for_private_rag"],
            "bytes_received": len(content),
            "text_length": len(extracted_text),
            "text_preview": extracted_text[:200],
        }
        return content, metadata, extracted_text if extracted else None
    if len(content) > 1_000_000:
        raise HTTPException(status_code=422, detail="text attachment must be 1MB or smaller")
    return content, metadata, None


def _parse_multipart_body(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, tuple[str, str, bytes]]]:
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=422, detail="invalid multipart upload")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, str, bytes]] = {}
    for part in message.iter_parts():
        params = dict(part.get_params(header="content-disposition") or [])
        name = str(params.get("name") or "")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = params.get("filename")
        if filename is not None:
            files[name] = (str(filename), part.get_content_type(), payload)
        else:
            fields[name] = payload.decode(part.get_content_charset() or "utf-8")
    return fields, files


async def _attachment_payload_from_request(request: Request) -> tuple[AttachmentCreate, bytes | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
            upload = form.get("file")
            if not isinstance(upload, (UploadFile, StarletteUploadFile)):
                raise HTTPException(status_code=422, detail="multipart upload requires a file field")
            raw = await upload.read()
            uploaded_content_type = str(upload.content_type or "application/octet-stream")
            filename = str(form.get("filename") or upload.filename or "attachment").strip()
            field = lambda name, default=None: form.get(name) or default
        except AssertionError:
            fields, files = _parse_multipart_body(content_type, await request.body())
            if "file" not in files:
                raise HTTPException(status_code=422, detail="multipart upload requires a file field")
            uploaded_filename, uploaded_content_type, raw = files["file"]
            filename = str(fields.get("filename") or uploaded_filename or "attachment").strip()
            field = lambda name, default=None: fields.get(name) or default
        is_text = uploaded_content_type in {"text/plain", "text/markdown", "application/json"}
        is_pdf = uploaded_content_type == "application/pdf"
        payload = AttachmentCreate(
            workspace_id=field("workspace_id"),
            thread_id=field("thread_id") or None,
            message_id=field("message_id") or None,
            filename=filename,
            content_type=uploaded_content_type,
            text_content=raw.decode("utf-8") if is_text else None,
            base64_content=base64.b64encode(raw).decode("ascii") if (uploaded_content_type.startswith("image/") or is_pdf) else None,
            modality=str(field("modality", "image" if uploaded_content_type.startswith("image/") else "text")),
            sensitivity=str(field("sensitivity", "medium")),
            retention_policy=str(field("retention_policy", "delete_on_request")),
            crop=str(field("crop")) if field("crop") else None,
            region=str(field("region")) if field("region") else None,
        )
        return payload, raw
    payload = AttachmentCreate.model_validate(await request.json())
    return payload, None


def _phase4_thread_trace_bundle(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]],
    field_context: dict[str, Any] | None,
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_feedback = feedback[-1] if feedback else None
    return {
        "schema_version": "phase4.thread_trace.v1",
        "trajectory_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"phase4-thread:{thread['id']}")),
        "workspace_id": thread["workspace_id"],
        "organization_id": thread["organization_id"],
        "thread": {
            "thread_id": thread["id"],
            "title": thread["title"],
            "mode": thread["mode"],
            "task_family": thread.get("task_family"),
            "risk_level": thread.get("risk_level") or "unknown",
            "field_context_id": thread.get("field_context_id"),
            "model_profile_id": thread.get("model_profile_id"),
            "rag_config_id": thread.get("rag_config_id"),
            "created_at": thread["created_at"],
            "updated_at": thread.get("updated_at"),
        },
        "field_context_snapshot": minimized_field_context_snapshot(field_context),
        "events": events,
        "feedback_summary": None
        if latest_feedback is None
        else {
            "rating": latest_feedback.get("rating"),
            "failure_tags": latest_feedback.get("failure_tags", []),
            "human_correction": latest_feedback.get("human_correction"),
            "ideal_answer": latest_feedback.get("ideal_answer"),
            "reviewed_by_user_id": latest_feedback.get("created_by_user_id"),
        },
        "training_candidate": None,
        "privacy": {
            "trace_capture_level": thread.get("trace_capture_level", "operational"),
            "training_eligible": bool(thread.get("training_eligible", False)),
            "redaction_status": thread.get("redaction_status", "not_required"),
            "retention_policy": "default",
            "contains_user_uploads": any(event.get("event_type") == "attachment_event" for event in events),
            "contains_location_data": bool(field_context and field_context.get("region_text")),
            "contains_proprietary_data": bool(field_context and field_context.get("sensitivity") == "high"),
            "license_state": "user_workspace_private" if thread.get("training_eligible") else "not_training_eligible",
        },
    }


def _markdown_thread_export(thread: dict[str, Any], events: list[dict[str, Any]]) -> str:
    lines = [f"# {thread['title']}", "", f"Thread ID: {thread['id']}", f"Workspace ID: {thread['workspace_id']}", ""]
    for message in thread.get("messages", []):
        lines.extend([f"## {message['actor'].title()} message", "", message["content"], ""])
    lines.extend(["## Trace events", ""])
    for event in events:
        lines.append(f"- {event['created_at']} `{event['event_type']}`")
    return "\n".join(lines)


def _eval_run_metrics(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return eval_run_metrics(candidates)


def _eval_run_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    return eval_run_gates(metrics)


def _change_proposal_gates(eval_run: dict[str, Any] | None) -> dict[str, Any]:
    gates: dict[str, Any] = {
        "requires_reviewed_eval_run": True,
        "requires_passing_regression": True,
        "reviewed_eval_run": False,
        "regression_suite": None,
        "candidate_count": 0,
        "promotion_allowed": False,
        "reason": "candidate proposals require reviewed eval evidence",
    }
    if not eval_run:
        return gates
    run_gates = eval_run.get("gates") or {}
    run_metrics = eval_run.get("metrics") or {}
    promotion_allowed = bool(run_gates.get("promotion_allowed"))
    gates.update(
        {
            "reviewed_eval_run": eval_run.get("status") == "completed",
            "regression_suite": run_gates.get("regression_suite"),
            "candidate_count": int(run_metrics.get("candidate_count") or 0),
            "promotion_allowed": promotion_allowed,
            "reason": "linked eval run permits rollout" if promotion_allowed else "linked eval run has not passed promotion gates",
        },
    )
    return gates


def _workspace_quotas(workspace: dict[str, Any]) -> dict[str, int]:
    configured = (workspace.get("settings") or {}).get("quotas") or {}
    quotas = dict(DEFAULT_WORKSPACE_QUOTAS)
    for key, default_value in DEFAULT_WORKSPACE_QUOTAS.items():
        value = configured.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        quotas[key] = max(0, parsed)
    return quotas


def _quota_report(workspace: dict[str, Any], usage: dict[str, int]) -> dict[str, Any]:
    quotas = _workspace_quotas(workspace)
    limits = []
    for quota_key, usage_key in QUOTA_USAGE_KEYS.items():
        limit = quotas[quota_key]
        used = int(usage.get(usage_key, 0))
        limits.append(
            {
                "quota": quota_key,
                "usage_key": usage_key,
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used),
                "exceeded": used > limit,
            },
        )
    return {
        "workspace_id": workspace["id"],
        "organization_id": workspace["organization_id"],
        "quotas": quotas,
        "usage": usage,
        "limits": limits,
        "blocked": any(item["exceeded"] for item in limits),
    }


def _corpus_health_summary(
    *,
    workspace: dict[str, Any],
    data_sources: list[dict[str, Any]],
    ingest_jobs: list[dict[str, Any]],
    chunk_counts: dict[str, int],
) -> dict[str, Any]:
    jobs_by_source: dict[str, list[dict[str, Any]]] = {}
    for job in ingest_jobs:
        source_id = str(job.get("data_source_id") or "")
        jobs_by_source.setdefault(source_id, []).append(job)

    source_health: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    for source in data_sources:
        jobs = jobs_by_source.get(source["id"], [])
        latest_job = jobs[0] if jobs else None
        chunk_count = int(chunk_counts.get(source["id"], 0))
        issues: list[str] = []
        license_state = str(source.get("license_state") or "unknown").lower()
        if license_state in {"unknown", "review_required"} or "review" in license_state:
            issues.append("license_review_required")
        if source.get("rag_eligible") and not jobs:
            issues.append("missing_ingest_job")
        if source.get("rag_eligible") and chunk_count == 0:
            issues.append("no_chunks_indexed")
        if latest_job and latest_job.get("status") in {"failed", "error"}:
            issues.append("ingest_failed")
        if latest_job and latest_job.get("status") in {"queued", "running"}:
            issues.append(f"ingest_{latest_job['status']}")
        for issue in issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        source_health.append(
            {
                "data_source_id": source["id"],
                "source_id": source["source_id"],
                "title": source["title"],
                "license_state": source["license_state"],
                "rag_eligible": source["rag_eligible"],
                "sft_eligible": source["sft_eligible"],
                "source_kind": source["source_kind"],
                "chunk_count": chunk_count,
                "latest_ingest_status": latest_job.get("status") if latest_job else "not_started",
                "latest_ingest_error": latest_job.get("error_message") if latest_job else None,
                "issue_flags": issues,
            },
        )

    status = "healthy"
    if issue_counts:
        status = "blocked" if issue_counts.get("ingest_failed") or issue_counts.get("missing_ingest_job") else "warning"
    if not data_sources:
        status = "blocked"
        issue_counts["no_data_sources"] = 1

    return {
        "workspace_id": workspace["id"],
        "status": status,
        "source_count": len(data_sources),
        "rag_eligible_count": sum(1 for source in data_sources if source.get("rag_eligible")),
        "sft_eligible_count": sum(1 for source in data_sources if source.get("sft_eligible")),
        "ingest_job_count": len(ingest_jobs),
        "queued_ingest_count": sum(1 for job in ingest_jobs if job.get("status") == "queued"),
        "failed_ingest_count": sum(1 for job in ingest_jobs if job.get("status") in {"failed", "error"}),
        "chunk_count": sum(chunk_counts.values()),
        "issue_counts": issue_counts,
        "sources": source_health,
    }


def _attachment_chunks_as_retrieved_docs(
    *,
    store: Any,
    attachments: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    query_embedding = _local_text_embedding(query)
    for attachment in attachments:
        for chunk in store.list_phase4_attachment_chunks_with_embeddings(attachment["id"]):
            embedding = chunk.get("embedding") or {}
            vector_score = _cosine_similarity(query_embedding, embedding.get("vector") or [])
            lexical_score = _lexical_overlap_score(query, chunk["text_content"])
            score = round((0.75 * vector_score) + (0.25 * lexical_score), 6)
            docs.append(
                {
                    "rank": 0,
                    "doc_id": chunk["id"],
                    "title": attachment["filename"],
                    "source_type": "user_upload_private",
                    "source": f"attachment:{attachment['id']}",
                    "score": score,
                    "text": chunk["text_content"],
                    "snippet": chunk["text_content"][:500],
                    "tags": ["private_upload", "workspace_scoped"],
                    "attachment_id": attachment["id"],
                    "chunk_index": chunk["chunk_index"],
                    "license_state": "user_workspace_private",
                    "license_status": "user_workspace_private",
                    "retrieval_policy": "context_only",
                    "content_risk_tags": ["user_provided_unverified"],
                    "chunk_sha256": hashlib.sha256(chunk["text_content"].encode("utf-8")).hexdigest(),
                    "training_eligible": False,
                    "visibility": "private",
                    "retrieval_method": "local_hash_embedding_v1",
                    "lexical_overlap": round(lexical_score, 6),
                    "embedding": {
                        "encoder_name": embedding.get("encoder_name"),
                        "encoder_version": embedding.get("encoder_version"),
                        "dimensions": embedding.get("dimensions"),
                        "status": (embedding.get("metadata") or {}).get("embedding_status"),
                    },
                },
            )
    ranked_docs = sorted(docs, key=lambda item: (-float(item["score"]), str(item["title"]), int(item["chunk_index"])))
    for rank, doc in enumerate(ranked_docs, start=1):
        doc["rank"] = rank
    return ranked_docs


def _data_source_chunks_as_retrieved_docs(
    *,
    store: Any,
    workspace_id: str,
    query: str,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    query_embedding = _local_text_embedding(query)
    for chunk in store.list_phase4_data_source_chunks_with_embeddings(workspace_id):
        source = chunk.get("data_source") or {}
        embedding = chunk.get("embedding") or {}
        vector_score = _cosine_similarity(query_embedding, embedding.get("vector") or [])
        lexical_score = _lexical_overlap_score(query, chunk["text_content"])
        score = round((0.75 * vector_score) + (0.25 * lexical_score), 6)
        source_metadata = source.get("metadata") or {}
        docs.append(
            {
                "rank": 0,
                "doc_id": chunk["id"],
                "title": chunk.get("title") or source.get("source_id") or "Workspace source",
                "source_type": source.get("source_kind") or "workspace_data_source",
                "source": chunk.get("source_url") or f"data-source:{chunk['data_source_id']}",
                "source_id": source.get("source_id") or chunk.get("source_doc_id") or "",
                "score": score,
                "text": chunk["text_content"],
                "snippet": chunk["text_content"][:500],
                "tags": ["workspace_source", "private_local_cache"],
                "jurisdictions": list(source.get("regions") or []),
                "crops": list(source.get("crops") or []),
                "languages": list(source_metadata.get("languages") or []),
                "data_source_id": chunk["data_source_id"],
                "chunk_index": chunk["chunk_index"],
                "license_state": chunk["license_state"],
                "license_status": chunk["license_state"],
                "license_identifier": str(source_metadata.get("license_identifier") or ""),
                "license_evidence_url": str(source_metadata.get("license_evidence_url") or ""),
                "license_attribution": str(source_metadata.get("license_attribution") or ""),
                "retrieval_policy": "context_only",
                "content_risk_tags": ["workspace_source_unverified_for_decisive_use"],
                "raw_sha256": str(source_metadata.get("raw_sha256") or ""),
                "chunk_sha256": hashlib.sha256(chunk["text_content"].encode("utf-8")).hexdigest(),
                "manifest_sha256": str(source_metadata.get("manifest_sha256") or ""),
                "training_eligible": False,
                "visibility": "workspace",
                "retrieval_method": "local_hash_embedding_v1",
                "lexical_overlap": round(lexical_score, 6),
                "embedding": {
                    "encoder_name": embedding.get("encoder_name"),
                    "encoder_version": embedding.get("encoder_version"),
                    "dimensions": embedding.get("dimensions"),
                    "status": (embedding.get("metadata") or {}).get("embedding_status"),
                },
            }
        )
    ranked_docs = sorted(
        docs,
        key=lambda item: (-float(item["score"]), str(item["title"]), int(item["chunk_index"])),
    )
    for rank, doc in enumerate(ranked_docs, start=1):
        doc["rank"] = rank
    return ranked_docs


def _image_quality_payload(
    *,
    attachments: list[dict[str, Any]],
    question: str,
    crop: str | None,
    region: str | None,
    observation_adapter: Any,
    similar_examples: list[dict[str, Any]] | None = None,
    image_retrieval_eval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return image_quality_payload(
        attachments=attachments,
        question=question,
        crop=crop,
        region=region,
        observation_adapter=observation_adapter,
        similar_examples=similar_examples,
        image_retrieval_eval=image_retrieval_eval,
    )


def _fingerprint_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    bits = min(len(left), len(right)) * 4
    if bits == 0:
        return 0.0
    distance = sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(left, right))
    return round(max(0.0, 1.0 - distance / bits), 4)


def _vector_similarity(left: list[Any], right: list[Any]) -> float:
    left_numbers = [float(value) for value in left if isinstance(value, (int, float))]
    right_numbers = [float(value) for value in right if isinstance(value, (int, float))]
    if not left_numbers or len(left_numbers) != len(right_numbers):
        return 0.0
    distance = sum((a - b) ** 2 for a, b in zip(left_numbers, right_numbers)) ** 0.5
    scale = (sum(a**2 for a in left_numbers) ** 0.5) + (sum(b**2 for b in right_numbers) ** 0.5) + 1.0
    return round(max(0.0, 1.0 - distance / scale), 4)


def _similar_image_examples(
    *,
    query_attachments: list[dict[str, Any]],
    candidate_attachments: list[dict[str, Any]],
    crop: str | None,
    region: str | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_images = [
        attachment
        for attachment in query_attachments
        if str(attachment.get("content_type") or "").startswith("image/") or attachment.get("modality") in {"image", "multimodal"}
    ]
    query_hashes = [
        (((attachment.get("metadata") or {}).get("image") or {}).get("fingerprint") or {}).get("hash")
        for attachment in query_images
    ]
    query_hashes = [str(item) for item in query_hashes if item]
    if not query_hashes:
        return []
    query_ids = {attachment["id"] for attachment in query_images}
    crop_filter = crop.strip().lower() if crop else None
    region_filter = region.strip().lower() if region else None
    examples: list[dict[str, Any]] = []
    for candidate in candidate_attachments:
        if candidate["id"] in query_ids or candidate.get("deleted_at"):
            continue
        metadata = candidate.get("metadata") or {}
        image = metadata.get("image") or {}
        if not image:
            continue
        filters = metadata.get("filters") or {}
        if crop_filter and filters.get("crop") != crop_filter:
            continue
        if region_filter and filters.get("region") != region_filter:
            continue
        fingerprint_hash = (image.get("fingerprint") or {}).get("hash")
        score = max(_fingerprint_similarity(query_hash, fingerprint_hash) for query_hash in query_hashes)
        examples.append(
            {
                "attachment_id": candidate["id"],
                "filename": candidate["filename"],
                "content_type": candidate["content_type"],
                "score": score,
                "encoder": "local-image-fingerprint-stub",
                "metadata_filters": filters,
                "image": {
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "quality_flags": image.get("quality_flags", []),
                },
            },
        )
    return sorted(examples, key=lambda item: item["score"], reverse=True)[:limit]


def _image_embedding_search(
    *,
    query_attachments: list[dict[str, Any]],
    candidate_embeddings: list[dict[str, Any]],
    crop: str | None,
    region: str | None,
    limit: int = 5,
) -> dict[str, Any]:
    return image_embedding_search(
        query_attachments=query_attachments,
        candidate_embeddings=candidate_embeddings,
        crop=crop,
        region=region,
        limit=limit,
    )


def _geo_priors_for_location(location_text: str) -> dict[str, Any]:
    text = location_text.strip()
    q = text.lower()
    candidates: list[dict[str, Any]] = []
    boosted_namespaces = {"regional_environment"}
    evidence_labels: list[str] = []
    missing_context = ["province/state", "county/RM", "soil series or texture", "drainage class"]

    def has_token(*terms: str) -> bool:
        return any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", q) for term in terms)

    def add_candidate(
        *,
        label: str,
        layer: str,
        system: str,
        code: str,
        confidence: float,
        match_reason: str,
        priors: list[str],
        evidence_terms: list[str],
    ) -> None:
        candidates.append(
            {
                "label": label,
                "name": label,
                "layer": layer,
                "system": system,
                "code": code,
                "match_reason": match_reason,
                "confidence": confidence,
                "priors": priors,
                "evidence_terms": evidence_terms,
                "source": "local_rule_stub",
            },
        )

    if has_token("iowa", "des moines lobe", "ia"):
        add_candidate(
            label="Central Iowa and Minnesota Till Prairies",
            layer="mlra_candidate",
            system="NRCS MLRA",
            code="MLRA_103",
            confidence=0.74 if "des moines lobe" in q else 0.58,
            match_reason="Iowa or Des Moines Lobe text match",
            priors=["glacial till soils", "tile drainage common", "corn-soy systems", "runoff and drainage pathways matter"],
            evidence_terms=[term for term in ["iowa", "des moines lobe", "ia"] if has_token(term)],
        )
        add_candidate(
            label="Western Corn Belt Plains",
            layer="ecoregion_candidate",
            system="EPA Level III Ecoregion",
            code="47",
            confidence=0.55,
            match_reason="Iowa administrative-region text match",
            priors=["row-crop dominated landscape", "erosion and runoff context can be important"],
            evidence_terms=[term for term in ["iowa", "ia"] if has_token(term)],
        )
        boosted_namespaces.update({"soil_water", "fertility"})
        evidence_labels.extend(["string_match:iowa", "string_match:des_moines_lobe" if "des moines lobe" in q else "string_match:ia"])
        missing_context = ["county", "soil series or texture", "drainage class"]
    if has_token("manitoba", "prairie", "prairies", "red river"):
        add_candidate(
            label="Canadian Prairies / Manitoba candidate",
            layer="ecodistrict/soil_landscape_candidate",
            system="AAFC/Statistics Canada regional proxy",
            code="CA_PRAIRIES_STUB",
            confidence=0.68 if "manitoba" in q else 0.52,
            match_reason="Manitoba, Prairie, or Red River text match",
            priors=["cold-season constraints", "salinity and drainage can matter", "short-season crop timing", "prairie soil-zone context"],
            evidence_terms=[term for term in ["manitoba", "prairie", "prairies", "red river"] if has_token(term)],
        )
        boosted_namespaces.update({"regional_environment", "soil_water", "fertility"})
        evidence_labels.append("string_match:canadian_prairies")
        missing_context = ["RM/county", "soil zone", "drainage class"]
    if has_token("ontario", "great lakes", "on"):
        add_candidate(
            label="Great Lakes / Ontario candidate",
            layer="ecoregion_candidate",
            system="Great Lakes regional proxy",
            code="GL_ON_STUB",
            confidence=0.6,
            match_reason="Ontario or Great Lakes text match",
            priors=["humid temperate risk context", "lake-effect weather can matter", "mixed field crop systems"],
            evidence_terms=[term for term in ["ontario", "great lakes", "on"] if has_token(term)],
        )
        boosted_namespaces.update({"regional_environment", "crop_management"})
        evidence_labels.append("string_match:great_lakes")
        missing_context = ["county", "soil series or texture", "drainage class"]
    if has_token("illinois", "corn belt", "mollisol"):
        add_candidate(
            label="Central Corn Belt candidate",
            layer="mlra_candidate",
            system="NRCS MLRA proxy",
            code="CORN_BELT_STUB",
            confidence=0.62,
            match_reason="Illinois, Corn Belt, or Mollisol text match",
            priors=["mollisol-dominant cropping context", "corn-soy rotation common", "nutrient loss pathways vary by drainage"],
            evidence_terms=[term for term in ["illinois", "corn belt", "mollisol"] if has_token(term)],
        )
        boosted_namespaces.update({"fertility", "soil_water"})
        evidence_labels.append("string_match:central_corn_belt")
    if not candidates:
        add_candidate(
            label="Unresolved generalized region",
            layer="unknown",
            system="unknown",
            code="UNKNOWN",
            confidence=0.2,
            match_reason="No supported region text matched",
            priors=["ask for province/state, county/RM, soil texture, drainage class, and crop zone before using regional assumptions"],
            evidence_terms=[],
        )

    confidence = max(candidate["confidence"] for candidate in candidates)
    disclaimer = "Regional context used as prior, not field-specific fact."
    uncertainty = "medium" if confidence >= 0.55 else "high"
    return {
        "location_text": text,
        "candidate_regions": candidates,
        "boosted_namespaces": sorted(boosted_namespaces),
        "evidence": evidence_labels,
        "missing_context": missing_context,
        "uncertainty": uncertainty,
        "used_as_prior_only": True,
        "not_field_specific_fact": True,
        "disclaimer": disclaimer,
        "ui_notice": disclaimer,
        "recommended_followups": [
            "Confirm administrative region and nearest extension jurisdiction.",
            "Confirm soil texture, drainage class, and field-specific management before recommendations.",
        ],
    }


ORG_ADMIN_ROLES = {"owner", "admin"}
WORKSPACE_WRITE_ROLES = {"owner", "admin", "researcher", "adviser"}
RESEARCH_REVIEW_ROLES = {"owner", "admin", "researcher"}
DEFAULT_WORKSPACE_QUOTAS = {
    "max_threads": 100,
    "max_messages": 2_000,
    "max_attachments": 100,
    "max_attachment_bytes": 50_000_000,
    "max_data_sources": 100,
    "max_eval_runs": 100,
    "max_exports": 200,
}
QUOTA_USAGE_KEYS = {
    "max_threads": "thread_count",
    "max_messages": "message_count",
    "max_attachments": "attachment_count",
    "max_attachment_bytes": "attachment_bytes",
    "max_data_sources": "data_source_count",
    "max_eval_runs": "eval_run_count",
    "max_exports": "export_count",
}


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    settings = settings or build_settings()
    store = build_trace_store(settings)
    settings = ServerSettings(
        db_path=settings.db_path,
        artifact_root=settings.artifact_root,
        model_config_path=settings.model_config_path,
        default_rag_config=settings.default_rag_config,
        prompt_version=settings.prompt_version,
        redaction_mode_default=settings.redaction_mode_default,
        static_dir=settings.static_dir,
        database_backend=settings.database_backend,
        database_url=settings.database_url,
        jwt_secret=settings.jwt_secret,
        jwt_issuer=settings.jwt_issuer,
        jwt_audience=settings.jwt_audience,
        jwt_jwks_json=settings.jwt_jwks_json,
        jwt_jwks_url=settings.jwt_jwks_url,
        allow_local_dev_auth=settings.allow_local_dev_auth,
        local_pairing_token_sha256=settings.local_pairing_token_sha256,
        oidc_authorization_endpoint=settings.oidc_authorization_endpoint,
        oidc_token_endpoint=settings.oidc_token_endpoint,
        oidc_client_id=settings.oidc_client_id,
        oidc_client_secret=settings.oidc_client_secret,
        oidc_redirect_uri=settings.oidc_redirect_uri,
        oidc_session_secret=settings.oidc_session_secret,
        oidc_logout_endpoint=settings.oidc_logout_endpoint,
        oidc_post_logout_redirect_uri=settings.oidc_post_logout_redirect_uri,
        oidc_scopes=settings.oidc_scopes,
        rate_limit_requests=settings.rate_limit_requests,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
        rate_limit_backend=settings.rate_limit_backend,
        redis_url=settings.redis_url,
        rate_limit_fail_open=settings.rate_limit_fail_open,
        job_queue_backend=settings.job_queue_backend,
        job_queue_name=settings.job_queue_name,
        eval_queue_name=settings.eval_queue_name,
        export_queue_name=settings.export_queue_name,
        embedding_queue_name=settings.embedding_queue_name,
        image_queue_name=settings.image_queue_name,
        job_queue_fail_open=settings.job_queue_fail_open,
        structured_access_logs=settings.structured_access_logs,
        otel_enabled=settings.otel_enabled,
        otel_service_name=settings.otel_service_name,
        network_mode=settings.network_mode,
        object_store_backend=settings.object_store_backend,
        object_store_endpoint=settings.object_store_endpoint,
        object_store_bucket=settings.object_store_bucket,
        object_store_region=settings.object_store_region,
        object_store_access_key=settings.object_store_access_key,
        object_store_secret_key=settings.object_store_secret_key,
        vlm_observation_backend=settings.vlm_observation_backend,
        vlm_observation_endpoint=settings.vlm_observation_endpoint,
        vlm_observation_api_key=settings.vlm_observation_api_key,
        vlm_observation_timeout_seconds=settings.vlm_observation_timeout_seconds,
        attachment_scan_backend=settings.attachment_scan_backend,
        attachment_scan_endpoint=settings.attachment_scan_endpoint,
        attachment_scan_api_key=settings.attachment_scan_api_key,
        attachment_scan_timeout_seconds=settings.attachment_scan_timeout_seconds,
        model_queue_max_wait_ms=settings.model_queue_max_wait_ms,
        model_queue_wait_ms_estimate=settings.model_queue_wait_ms_estimate,
        agent_runtime=settings.agent_runtime,
        knowledge_update_root=settings.knowledge_update_root,
        knowledge_update_public_key=settings.knowledge_update_public_key,
        knowledge_update_trust_policy=settings.knowledge_update_trust_policy,
        knowledge_update_allow_unsigned=settings.knowledge_update_allow_unsigned,
        allow_rag_config_override=settings.allow_rag_config_override,
        allow_model_id_override=settings.allow_model_id_override,
        corpus_audit_id=_corpus_audit(settings, store),
    )
    app = FastAPI(title="Agronomy Agent Cockpit")
    app.state.trace_store = store
    app.state.frontend_rum_records = []
    app.state.frontend_event_records = []
    app.state.local_pairing_consumed = False
    local_pairing_lock = asyncio.Lock()
    object_store = build_object_store(settings)
    job_queue = build_job_queue(settings)
    attachment_scanner = build_attachment_scanner(settings)
    ephemeral_private_scanner = LocalAttachmentScanner()
    image_observation_adapter = _build_image_observation_adapter(settings)
    telemetry = build_telemetry(enabled=settings.otel_enabled, service_name=settings.otel_service_name)
    runtime_model_config = load_model_config(settings.model_config_path)
    operator_model_ids = {
        str(model_id)
        for model_id in (
            runtime_model_config.get("serving_model_id"),
            runtime_model_config.get("model_id"),
            runtime_model_config.get("assistant_model_id"),
            runtime_model_config.get("draft_model_id"),
        )
        if model_id
    }

    def runtime_rag_config(requested: str | None) -> str:
        if settings.knowledge_update_root is not None:
            activation = read_activation(settings.knowledge_update_root)
            if activation is not None:
                try:
                    validate_activation_freshness(activation)
                    if settings.knowledge_update_trust_policy is not None:
                        settings.knowledge_update_trust_policy.validate_freshness()
                except ValueError as exc:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "The active knowledge release or its signer trust policy has expired; "
                            "install a current signed release and reviewed trust policy."
                        ),
                    ) from exc
        selected = str(requested or settings.default_rag_config)
        if settings.allow_rag_config_override:
            return selected
        if repo_path(selected).resolve() != repo_path(settings.default_rag_config).resolve():
            raise HTTPException(
                status_code=409,
                detail=(
                    "RAG configuration is operator-managed. Activate a reviewed signed knowledge release "
                    "instead of selecting a client-supplied configuration."
                ),
            )
        return settings.default_rag_config

    def runtime_model_id(requested: str | None, *, mode: str | None) -> str:
        selected = str(requested or settings.default_model_id)
        if mode == "mock" and selected == "mock":
            return selected
        if settings.allow_model_id_override or selected in operator_model_ids:
            return selected
        raise HTTPException(
            status_code=409,
            detail=(
                "Model selection is operator-managed. Promote a reviewed model profile "
                "instead of selecting a client-supplied model."
            ),
        )

    def runtime_mode(mode: str) -> str:
        if mode == "mock" and not settings.allow_model_id_override:
            raise HTTPException(
                status_code=409,
                detail="Mock mode is development-only and is disabled on the operator-managed runtime.",
            )
        return mode

    if settings.rate_limit_backend == "redis":
        rate_limiter = RedisFixedWindowRateLimiter(
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
            redis_url=str(settings.redis_url or ""),
        )
    else:
        rate_limiter = FixedWindowRateLimiter(
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )

    @app.middleware("http")
    async def enforce_rate_limit(request: Request, call_next: Any) -> Any:
        if _rate_limit_exempt_path(request.url.path):
            return await call_next(request)
        try:
            result = rate_limiter.check(_rate_limit_key(request), now=time.monotonic())
        except RateLimiterUnavailable as exc:
            if settings.rate_limit_fail_open:
                response = await call_next(request)
                response.headers["X-RateLimit-Backend"] = settings.rate_limit_backend
                response.headers["X-RateLimit-Fail-Open"] = "true"
                return response
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "error": "rate limiter unavailable",
                        "backend": settings.rate_limit_backend,
                        "fail_open": False,
                        "reason": str(exc),
                    }
                },
                headers={"Retry-After": "1", "X-RateLimit-Backend": settings.rate_limit_backend},
            )
        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(result.reset_after_seconds),
            "X-RateLimit-Backend": settings.rate_limit_backend,
        }
        if not result.allowed:
            headers["Retry-After"] = str(result.reset_after_seconds)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "error": "rate limit exceeded",
                        "limit": result.limit,
                        "window_seconds": settings.rate_limit_window_seconds,
                        "retry_after_seconds": result.reset_after_seconds,
                    }
                },
                headers=headers,
            )
        response = await call_next(request)
        response.headers.update(headers)
        return response

    @app.middleware("http")
    async def enforce_cookie_csrf(request: Request, call_next: Any) -> Any:
        if not _requires_cookie_csrf(request):
            return await call_next(request)
        try:
            expected = _csrf_token_from_session_cookie(str(request.cookies.get("agronomy_session") or ""), settings=settings)
        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            return JSONResponse(status_code=401, content={"detail": f"invalid session: {exc}"})
        observed = request.headers.get("x-csrf-token") or request.headers.get("x-agronomy-csrf-token")
        if not observed or not hmac.compare_digest(str(observed), expected):
            return JSONResponse(status_code=403, content={"detail": "CSRF token is required for cookie-authenticated unsafe requests"})
        return await call_next(request)

    @app.middleware("http")
    async def structured_access_log(request: Request, call_next: Any) -> Any:
        request_id_value = request_id(request)
        started_at = time.perf_counter()
        span = None
        try:
            with telemetry.start_http_span(request, request_id_value) as span:
                response = await call_next(request)
                if span is not None:
                    span.set_attribute("http.response.status_code", response.status_code)
        except Exception as exc:
            if span is not None:
                span.record_exception(exc)
                span.set_attribute("http.response.status_code", 500)
            if settings.structured_access_logs:
                log_request(
                    request=request,
                    request_id_value=request_id_value,
                    status_code=500,
                    started_at=started_at,
                    error_type=exc.__class__.__name__,
                )
            raise
        response.headers["X-Request-ID"] = request_id_value
        if settings.structured_access_logs:
            log_request(
                request=request,
                request_id_value=request_id_value,
                status_code=response.status_code,
                started_at=started_at,
                rate_limited=response.status_code == 429,
            )
        return response

    def _register_cookie_session(session: dict[str, Any], request: Request) -> dict[str, Any]:
        user = store.upsert_phase4_user(email=session["email"], display_name=session["display_name"])
        if user.get("status") != "active":
            raise HTTPException(status_code=403, detail="user is not active")
        persisted = store.get_phase6_auth_session(session["session_id"])
        if persisted and persisted.get("revoked_at"):
            raise HTTPException(status_code=401, detail="session has been revoked")
        if persisted:
            store.touch_phase6_auth_session(session["session_id"])
        else:
            store.upsert_phase6_auth_session(
                session_id=session["session_id"],
                user_id=user["id"],
                auth_subject=session["sub"],
                email=session["email"],
                display_name=session["display_name"],
                issued_at=session["issued_at"],
                expires_at=session["expires_at"],
                user_agent=request.headers.get("user-agent"),
            )
        return user

    def _auth_sessions_payload(user: dict[str, Any], current_session_id: str | None) -> dict[str, Any]:
        sessions = []
        for session in store.list_phase6_auth_sessions(user["id"]):
            sessions.append(
                {
                    "id": session["id"],
                    "issued_at": session["issued_at"],
                    "expires_at": session["expires_at"],
                    "last_seen_at": session["last_seen_at"],
                    "revoked_at": session.get("revoked_at"),
                    "current": bool(current_session_id and session["id"] == current_session_id),
                    "user_agent_hash": session.get("user_agent_hash"),
                }
            )
        return {"schema_version": "phase6.auth_sessions.v1", "sessions": sessions}

    def _dev_token_payload(token: str) -> dict[str, Any] | None:
        if not settings.allow_local_dev_auth:
            return None
        return {"token": token, "delivery": "local_dev_response_only"}

    def _issue_password_session_response(
        user: dict[str, Any],
        request: Request,
        *,
        auth_subject_prefix: str = "password",
        schema_version: str = "phase6.password_login.v1",
    ) -> JSONResponse:
        if not settings.oidc_session_secret:
            raise HTTPException(status_code=503, detail="session cookies require AGRONOMY_AGENT_OIDC_SESSION_SECRET")
        session_id = str(uuid.uuid4())
        session_cookie = _encode_session_cookie(
            {
                "sub": f"{auth_subject_prefix}:{user['id']}",
                "email": user["email"],
                "name": user["display_name"],
                "exp": int(time.time()) + 8 * 60 * 60,
            },
            settings=settings,
            session_id=session_id,
        )
        session_payload = _decode_session_cookie(session_cookie, settings=settings)
        store.upsert_phase6_auth_session(
            session_id=session_payload["session_id"],
            user_id=user["id"],
            auth_subject=session_payload["sub"],
            email=session_payload["email"],
            display_name=session_payload["display_name"],
            issued_at=session_payload["issued_at"],
            expires_at=session_payload["expires_at"],
            user_agent=request.headers.get("user-agent"),
        )
        csrf_token = _csrf_token_from_session_cookie(session_cookie, settings=settings)
        response = JSONResponse(
            {
                "schema_version": schema_version,
                "user": user,
                "csrf_token": csrf_token,
            }
        )
        response.set_cookie(
            "agronomy_session",
            session_cookie,
            max_age=8 * 60 * 60,
            httponly=True,
            secure=_cookie_secure(settings),
            samesite="lax",
        )
        response.set_cookie(
            "agronomy_csrf",
            csrf_token,
            max_age=8 * 60 * 60,
            httponly=False,
            secure=_cookie_secure(settings),
            samesite="lax",
        )
        return response

    def _ensure_personal_workspace(user: dict[str, Any]) -> None:
        if store.list_phase4_workspaces_for_user(user["id"]):
            return
        org = store.create_phase4_organization(
            name="Personal Workspace",
            slug=f"personal-{str(user['id'])[:8]}",
            plan="demo",
            created_by_user_id=user["id"],
        )
        store.create_phase4_workspace(
            organization_id=org["id"],
            name="My agronomy workspace",
            created_by_user_id=user["id"],
            settings={"workspace_type": "personal", "phase": "6"},
        )

    async def current_user(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_agronomy_user_email: str | None = Header(default=None, alias="X-Agronomy-User-Email"),
        x_agronomy_user_name: str | None = Header(default=None, alias="X-Agronomy-User-Name"),
    ) -> dict[str, Any]:
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                raise HTTPException(status_code=401, detail="Authorization must use Bearer token")
            if not settings.jwt_secret and not settings.jwt_jwks_json and not settings.jwt_jwks_url:
                raise HTTPException(status_code=401, detail="JWT auth is not configured")
            try:
                claims = _decode_configured_jwt(token.strip(), settings=settings)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                raise HTTPException(status_code=401, detail=f"invalid JWT: {exc}") from exc
            email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
            if not email:
                raise HTTPException(status_code=401, detail="JWT must include email or preferred_username")
            name = str(claims.get("name") or claims.get("given_name") or email.split("@")[0])
            user = store.upsert_phase4_user(email=email, display_name=name)
            if user.get("status") != "active":
                raise HTTPException(status_code=403, detail="user is not active")
            return user
        session_cookie = request.cookies.get("agronomy_session")
        if session_cookie:
            try:
                session = _decode_session_cookie(session_cookie, settings=settings)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                raise HTTPException(status_code=401, detail=f"invalid session: {exc}") from exc
            return _register_cookie_session(session, request)
        if not settings.allow_local_dev_auth:
            raise HTTPException(status_code=401, detail="Bearer JWT or OIDC session is required")
        if not x_agronomy_user_email:
            raise HTTPException(status_code=401, detail="Bearer JWT, OIDC session, or X-Agronomy-User-Email is required")
        user = store.upsert_phase4_user(email=x_agronomy_user_email, display_name=x_agronomy_user_name)
        if user.get("status") != "active":
            raise HTTPException(status_code=403, detail="user is not active")
        return user

    def require_workspace_for_user(user: dict[str, Any], workspace_id: str) -> dict[str, Any]:
        workspace = store.get_phase4_workspace(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="workspace not found")
        if not store.phase4_user_can_access_workspace(user["id"], workspace_id):
            raise HTTPException(status_code=403, detail="workspace access denied")
        return workspace

    def require_org_role(user: dict[str, Any], organization_id: str, allowed_roles: set[str]) -> dict[str, Any]:
        organization = store.get_phase4_organization(organization_id)
        if not organization:
            raise HTTPException(status_code=404, detail="organization not found")
        membership = store.get_phase4_membership(user_id=user["id"], organization_id=organization_id)
        if not membership:
            raise HTTPException(status_code=403, detail="organization access denied")
        if membership["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"requires one of roles: {', '.join(sorted(allowed_roles))}")
        return membership

    def require_workspace_role(user: dict[str, Any], workspace_id: str, allowed_roles: set[str]) -> dict[str, Any]:
        workspace = require_workspace_for_user(user, workspace_id)
        require_org_role(user, workspace["organization_id"], allowed_roles)
        return workspace

    def _demo_field_user(request: Request) -> dict[str, Any]:
        authorization = str(request.headers.get("Authorization") or "").strip()
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                raise HTTPException(status_code=401, detail="Authorization must use Bearer token")
            if not settings.jwt_secret and not settings.jwt_jwks_json and not settings.jwt_jwks_url:
                raise HTTPException(status_code=401, detail="JWT auth is not configured")
            try:
                claims = _decode_configured_jwt(token.strip(), settings=settings)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                raise HTTPException(status_code=401, detail=f"invalid JWT: {exc}") from exc
            email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
            if not email:
                raise HTTPException(status_code=401, detail="JWT must include email or preferred_username")
            name = str(claims.get("name") or claims.get("given_name") or email.split("@")[0])
            user = store.upsert_phase4_user(email=email, display_name=name)
            if user.get("status") != "active":
                raise HTTPException(status_code=403, detail="user is not active")
            _ensure_personal_workspace(user)
            return user
        session_cookie = request.cookies.get("agronomy_session")
        if session_cookie:
            try:
                session = _decode_session_cookie(session_cookie, settings=settings)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                raise HTTPException(status_code=401, detail=f"invalid session: {exc}") from exc
            user = _register_cookie_session(session, request)
            _ensure_personal_workspace(user)
            return user
        if not settings.allow_local_dev_auth:
            raise HTTPException(status_code=401, detail="sign in before storing demo fields")
        email = str(request.headers.get("X-Agronomy-User-Email") or "local-demo@open-agronomy.local").strip().lower()
        display_name = str(request.headers.get("X-Agronomy-User-Name") or "Open Agronomy local reviewer").strip()
        user = store.upsert_phase4_user(email=email, display_name=display_name)
        if user.get("status") != "active":
            raise HTTPException(status_code=403, detail="user is not active")
        _ensure_personal_workspace(user)
        return user

    _SESSION_OWNER_CONTEXT_KEY = "_session_owner_user_id"

    def _session_owner_id(session: dict[str, Any]) -> str | None:
        context = session.get("context") if isinstance(session.get("context"), dict) else {}
        extra = context.get("extra") if isinstance(context.get("extra"), dict) else {}
        owner_id = str(extra.get(_SESSION_OWNER_CONTEXT_KEY) or "").strip()
        return owner_id or None

    def _context_with_session_owner(context: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
        owned = dict(context or {})
        extra = dict(owned.get("extra") or {}) if isinstance(owned.get("extra"), dict) else {}
        extra[_SESSION_OWNER_CONTEXT_KEY] = str(user_id)
        owned["extra"] = extra
        return owned

    def _uses_anonymous_local_profile(request: Request) -> bool:
        return bool(
            settings.allow_local_dev_auth
            and not request.cookies.get("agronomy_session")
            and not request.headers.get("Authorization")
            and not request.headers.get("X-Agronomy-User-Email")
        )

    def _session_visible_to_user(
        session: dict[str, Any],
        *,
        request: Request,
        user: dict[str, Any],
    ) -> bool:
        owner_id = _session_owner_id(session)
        if owner_id:
            return owner_id == str(user["id"])
        return _uses_anonymous_local_profile(request)

    def _session_response(session: dict[str, Any]) -> dict[str, Any]:
        response = dict(session)
        context = dict(response.get("context") or {}) if isinstance(response.get("context"), dict) else {}
        extra = dict(context.get("extra") or {}) if isinstance(context.get("extra"), dict) else {}
        extra.pop(_SESSION_OWNER_CONTEXT_KEY, None)
        context["extra"] = extra
        response["context"] = context
        response["turns"] = [
            {
                **turn,
                "knowledge_coverage": _answer_time_knowledge_coverage(turn.get("trace")),
            }
            for turn in response.get("turns", [])
            if isinstance(turn, dict)
        ]
        return response

    def _require_owned_session(
        request: Request,
        session_id: str,
        *,
        user: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resolved_user = user or _demo_field_user(request)
        session = store.get_session(session_id)
        if not session or not _session_visible_to_user(session, request=request, user=resolved_user):
            raise HTTPException(status_code=404, detail="session not found")
        return session, resolved_user

    def _require_local_cockpit_research(request: Request) -> dict[str, Any]:
        if not settings.allow_local_dev_auth:
            raise HTTPException(status_code=404, detail="local cockpit endpoint not available")
        return _demo_field_user(request)

    def _demo_field_workspace(user: dict[str, Any]) -> dict[str, Any]:
        _ensure_personal_workspace(user)
        workspaces = store.list_phase4_workspaces_for_user(user["id"])
        if not workspaces:
            raise HTTPException(status_code=500, detail="demo workspace could not be created")
        return workspaces[0]

    def _authorize_demo_turn_field_context(
        request: Request,
        session_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        def canonical_geometry(value: Any) -> Any:
            if not isinstance(value, dict):
                return value
            if value.get("kind") == "point":
                point = value.get("point")
                if isinstance(point, dict):
                    value = {
                        "type": "Point",
                        "coordinates": [point.get("lon"), point.get("lat")],
                    }
            elif value.get("kind") == "polygon":
                points = value.get("points")
                if isinstance(points, list) and points:
                    ring = [
                        [point.get("lon"), point.get("lat")]
                        for point in points
                        if isinstance(point, dict)
                    ]
                    if ring and ring[0] != ring[-1]:
                        ring.append(ring[0])
                    value = {"type": "Polygon", "coordinates": [ring]}
            try:
                return validate_geojson_geometry(value)
            except (TypeError, ValueError):
                return value

        if not isinstance(session_context, dict):
            return session_context
        outer = dict(session_context)
        inner_value = outer.get("field_context")
        inner = dict(inner_value) if isinstance(inner_value, dict) else {}
        # These are server-owned context surfaces. Never accept client-authored
        # history as though it came from the integrity-checked field store.
        inner.pop("field_history", None)
        inner.pop("field_answer_history", None)
        outer_field_id = str(outer.get("field_context_id") or "").strip()
        inner_field_id = str(inner.get("field_context_id") or "").strip()
        if outer_field_id and inner_field_id and outer_field_id != inner_field_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "field_context_binding_mismatch",
                    "boundary": "The turn cannot bind two different field identifiers.",
                },
            )
        field_context_id = outer_field_id or inner_field_id
        if not field_context_id:
            return outer

        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_for_user(user, record["workspace_id"])
        stored = _demo_field_record(record)

        mismatch_fields: list[str] = []
        for inner_key, stored_key in (
            ("crop", "crop"),
            ("region", "region"),
            ("jurisdiction", "jurisdiction"),
            ("concern", "concern"),
        ):
            supplied = str(inner.get(inner_key) or "").strip()
            authoritative = str(stored.get(stored_key) or "").strip()
            if supplied and authoritative and supplied != authoritative:
                mismatch_fields.append(inner_key)
        if inner.get("geometry") is not None and stored.get("geometry") is not None:
            supplied_geometry = json.dumps(
                canonical_geometry(inner.get("geometry")),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            stored_geometry = json.dumps(
                canonical_geometry(stored.get("geometry")),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if supplied_geometry != stored_geometry:
                mismatch_fields.append("geometry")
        if mismatch_fields:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "field_context_snapshot_mismatch",
                    "mismatch_fields": sorted(set(mismatch_fields)),
                    "boundary": (
                        "The client-supplied field snapshot differs from the authorized stored field. "
                        "Reload the field before asking so another crop, concern, or geometry is not "
                        "silently attached to its history."
                    ),
                },
            )

        inner.update(
            {
                "field_context_id": field_context_id,
                "field_conversation_key": f"field:{field_context_id}",
                "crop": stored.get("crop") or inner.get("crop"),
                "region": stored.get("region") or inner.get("region"),
                "jurisdiction": stored.get("jurisdiction") or inner.get("jurisdiction"),
                "concern": stored.get("concern") or inner.get("concern"),
                "geometry": canonical_geometry(stored.get("geometry") or inner.get("geometry")),
                "regional_context": stored.get("regionalContext") or inner.get("regional_context"),
            }
        )
        stored_geo_priors = stored.get("geoPriors") if isinstance(stored.get("geoPriors"), dict) else {}
        for key in (
            "candidate_regions",
            "regional_intersections",
            "regional_feature_collection",
            "geo_errors",
            "official_layer_status",
            "uncertainty",
            "used_as_prior_only",
            "not_field_specific_fact",
            "disclaimer",
        ):
            if key in stored_geo_priors:
                inner[key] = stored_geo_priors[key]
        geo_context_lineage = (
            stored.get("geoContextLineage")
            if isinstance(stored.get("geoContextLineage"), dict)
            else {}
        )
        field_answer_history = _demo_field_answer_context(
            request=request,
            user=user,
            field_context_id=field_context_id,
        )
        if field_answer_history["records"]:
            inner["field_answer_history"] = field_answer_history
        outer.update(
            {
                "field_context_id": field_context_id,
                "field_conversation_key": f"field:{field_context_id}",
                "field_record_updated_at": record.get("updated_at"),
                "field_access_authorized": True,
                "field_access_workspace_id": record["workspace_id"],
                "geo_context_binding_status": (
                    "stored_field_snapshot" if stored_geo_priors else "not_available"
                ),
                "geo_context_snapshot_sha256": geo_context_lineage.get("snapshot_sha256"),
                "field_context": inner,
            }
        )
        return outer

    def _persistable_demo_turn_context(session_context: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(session_context, dict):
            return session_context
        persisted = dict(session_context)
        persisted.pop("workspace_retrieved_docs", None)
        persisted.pop("ephemeral_private_source_summary", None)
        return persisted

    def _demo_field_metadata(record: dict[str, Any]) -> dict[str, Any]:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        open_metadata = metadata.get("open_agronomy_agent") if isinstance(metadata.get("open_agronomy_agent"), dict) else {}
        return open_metadata

    def _demo_field_record(record: dict[str, Any]) -> dict[str, Any]:
        open_metadata = _demo_field_metadata(record)
        field = open_metadata.get("field") if isinstance(open_metadata.get("field"), dict) else {}
        return {
            "id": record["id"],
            "field_context_id": record["id"],
            "name": record.get("display_name") or field.get("name") or "Stored field",
            "crop": record.get("crop_current") or field.get("crop") or "",
            "region": field.get("region") or record.get("region_text") or "",
            "jurisdiction": field.get("jurisdiction") or record.get("province_state") or record.get("country") or "",
            "acres": str(field.get("acres") or open_metadata.get("acres") or ""),
            "concern": field.get("concern") or "",
            "notes": field.get("notes") or record.get("management_notes") or "",
            "geometry": open_metadata.get("geometry") or {"kind": "none"},
            "regionalContext": open_metadata.get("regional_context_label") or record.get("region_text") or "",
            "geoPriors": open_metadata.get("geo_priors"),
            "geoContextLineage": open_metadata.get("geo_context_lineage"),
            "sourceBoundary": open_metadata.get("source_boundary"),
            "createdAt": record.get("created_at"),
            "updatedAt": record.get("updated_at"),
            "storageMode": "account_workspace",
        }

    def _demo_field_answer_context(
        *,
        request: Request,
        user: dict[str, Any],
        field_context_id: str,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Return bounded, reviewed continuity notes for an authorized field.

        Prior model output is never promoted to evidence. Only explicitly accepted,
        integrity-verified answers may contribute a short continuity excerpt; rejected
        answers contribute only their rejection and human correction/reviewer note.
        """
        records: list[dict[str, Any]] = []
        for session in store.list_sessions(include_archived=True):
            if not _session_visible_to_user(session, request=request, user=user):
                continue
            for turn in session.get("turns", []):
                if not isinstance(turn, dict):
                    continue
                trace = turn.get("trace") if isinstance(turn.get("trace"), dict) else {}
                metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
                lineage = metadata.get("field_lineage") if isinstance(metadata.get("field_lineage"), dict) else {}
                if str(lineage.get("field_context_id") or "") != field_context_id:
                    continue

                stored_turn = store.get_turn(str(turn.get("turn_id") or ""))
                if not isinstance(stored_turn, dict):
                    continue
                feedback = (
                    stored_turn.get("feedback")
                    if isinstance(stored_turn.get("feedback"), dict)
                    else {}
                )
                answer_status = str(stored_turn.get("answer_status") or "draft")
                accepted = feedback.get("accepted")
                has_human_review = any(
                    feedback.get(key) not in (None, "", [], {})
                    for key in (
                        "rating",
                        "accepted",
                        "correction",
                        "ideal_answer",
                        "reviewer_notes",
                        "route_correct",
                        "route_correction_labels",
                        "evidence_feedback",
                        "answer_status",
                    )
                )
                if accepted is True or answer_status == "approved":
                    review_status = "accepted"
                elif accepted is False or answer_status == "rejected":
                    review_status = "rejected"
                elif has_human_review or answer_status in {"reviewed", "exported"}:
                    review_status = "reviewed"
                else:
                    review_status = "unreviewed"

                receipt = (
                    stored_turn.get("answer_integrity_receipt")
                    if isinstance(stored_turn.get("answer_integrity_receipt"), dict)
                    else {}
                )
                record = {
                    "turn_id": str(turn.get("turn_id") or ""),
                    "created_at": turn.get("created_at"),
                    "question": str(turn.get("user_message") or "").strip()[:500],
                    "answer_status": answer_status,
                    "review_status": review_status,
                    "answer_integrity_status": receipt.get("status") or "not_captured",
                    "answer_receipt_sha256": receipt.get("receipt_sha256"),
                }
                correction = str(feedback.get("correction") or "").strip()
                reviewer_notes = str(feedback.get("reviewer_notes") or "").strip()
                if correction:
                    record["human_correction"] = correction[:800]
                if reviewer_notes:
                    record["reviewer_notes"] = reviewer_notes[:800]
                if review_status == "accepted" and receipt.get("status") == "verified":
                    accepted_excerpt = str(stored_turn.get("answer") or "").strip()
                    if accepted_excerpt:
                        record["accepted_answer_excerpt"] = accepted_excerpt[:1000]
                records.append(record)

        records.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("turn_id") or "")))
        bounded = records[-max(1, limit):]
        return {
            "schema_version": "open_agronomy_agent.field_answer_context.v1",
            "total_bound_turn_count": len(records),
            "included_turn_count": len(bounded),
            "records": bounded,
            "policy": (
                "Prior questions and human review support continuity only. Prior model answers are not "
                "agronomic evidence; rejected outputs must not be repeated, and accepted excerpts still "
                "require current source and field verification."
            ),
        }

    def _field_payload_text(value: Any, *, fallback: str = "", max_length: int = 500) -> str:
        text = str(value or fallback).strip()
        return text[:max_length]

    def _validate_demo_field_geometry(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise HTTPException(status_code=422, detail="field geometry is required")
        kind = str(value.get("kind") or "")
        if kind == "point":
            point = value.get("point")
            if not isinstance(point, dict) or not isinstance(point.get("lat"), (int, float)) or not isinstance(point.get("lon"), (int, float)):
                raise HTTPException(status_code=422, detail="point field geometry requires lat/lon")
            try:
                normalized = validate_geojson_geometry({"type": "Point", "coordinates": [point["lon"], point["lat"]]})
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"kind": "point", "point": {"lat": normalized["coordinates"][1], "lon": normalized["coordinates"][0]}}
        if kind == "polygon":
            points = value.get("points")
            if not isinstance(points, list) or len(points) < 3:
                raise HTTPException(status_code=422, detail="polygon field geometry requires at least three points")
            for point in points[:250]:
                if not isinstance(point, dict) or not isinstance(point.get("lat"), (int, float)) or not isinstance(point.get("lon"), (int, float)):
                    raise HTTPException(status_code=422, detail="polygon field geometry points require lat/lon")
            retained = points[:250]
            ring = [[point["lon"], point["lat"]] for point in retained]
            ring.append(ring[0])
            try:
                normalized = validate_geojson_geometry({"type": "Polygon", "coordinates": [ring]})
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            normalized_points = [
                {"lat": position[1], "lon": position[0]}
                for position in normalized["coordinates"][0][:-1]
            ]
            return {**value, "points": normalized_points}
        raise HTTPException(status_code=422, detail="field geometry must be point or polygon")

    def _demo_country_for_jurisdiction(jurisdiction: str) -> str | None:
        lowered = jurisdiction.strip().lower()
        if not lowered:
            return None
        canadian = {
            "alberta",
            "british columbia",
            "manitoba",
            "new brunswick",
            "newfoundland and labrador",
            "nova scotia",
            "ontario",
            "prince edward island",
            "quebec",
            "saskatchewan",
            "northwest territories",
            "nunavut",
            "yukon",
        }
        return "Canada" if lowered in canadian else "United States"

    def _demo_geometry_geojson(geometry: dict[str, Any]) -> dict[str, Any]:
        if geometry.get("kind") == "point":
            point = geometry["point"]
            return {"type": "Point", "coordinates": [point["lon"], point["lat"]]}
        points = geometry.get("points") or []
        ring = [[point["lon"], point["lat"]] for point in points]
        return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}

    def _governed_demo_geo_priors(
        geometry: dict[str, Any],
        supplied: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Bind browser context to a server-recomputed bundled-layer snapshot."""

        supplied_priors = dict(supplied) if isinstance(supplied, dict) else {}
        local_layer_ids = [
            layer_id
            for layer_id, layer in REGION_LAYERS.items()
            if layer.query_backend == "local_sqlite"
        ]
        server_result = intersect_region_layers(
            geometry=_demo_geometry_geojson(geometry),
            layer_ids=local_layer_ids,
            network_mode=settings.network_mode,
        )
        server_intersections = [
            {**item, "binding_status": "server_recomputed_bundled_source"}
            for item in server_result.get("intersections", [])
            if isinstance(item, dict)
        ]
        supplied_intersections = supplied_priors.get("regional_intersections")
        retained_remote = [
            {**item, "binding_status": "client_snapshot_context_only"}
            for item in (supplied_intersections if isinstance(supplied_intersections, list) else [])
            if isinstance(item, dict) and str(item.get("layer_id") or "") not in local_layer_ids
        ][:20]

        supplied_status = supplied_priors.get("official_layer_status")
        retained_remote_status = [
            item
            for item in (supplied_status if isinstance(supplied_status, list) else [])
            if isinstance(item, dict) and str(item.get("layer_id") or "") not in local_layer_ids
        ][:20]
        supplied_errors = supplied_priors.get("geo_errors")
        retained_remote_errors = [
            item
            for item in (supplied_errors if isinstance(supplied_errors, list) else [])
            if isinstance(item, dict) and str(item.get("layer_id") or "") not in local_layer_ids
        ][:20]

        supplied_features = supplied_priors.get("regional_feature_collection")
        remote_features = [
            feature
            for feature in (
                supplied_features.get("features", [])
                if isinstance(supplied_features, dict)
                else []
            )
            if isinstance(feature, dict)
            and str((feature.get("properties") or {}).get("layer_id") or "") not in local_layer_ids
        ][:80]
        intersections = [*server_intersections, *retained_remote]
        governed = {
            **supplied_priors,
            "candidate_regions": [
                {
                    "label": item.get("name") or item.get("label") or item.get("code"),
                    "name": item.get("name") or item.get("label") or item.get("code"),
                    "layer": item.get("layer_id"),
                    "system": item.get("system"),
                    "code": item.get("code"),
                    "confidence": item.get("confidence"),
                    "match_reason": item.get("match_reason"),
                    "priors": ["official polygon intersection", "use as regional context prior"],
                    "evidence_terms": [item.get("code"), item.get("name")],
                    "source": item.get("source"),
                    "binding_status": item.get("binding_status"),
                }
                for item in intersections
            ],
            "regional_intersections": intersections,
            "regional_feature_collection": {
                "type": "FeatureCollection",
                "features": [
                    *server_result.get("feature_collection", {}).get("features", []),
                    *remote_features,
                ],
            },
            "geo_errors": [*server_result.get("errors", []), *retained_remote_errors],
            "official_layer_status": [
                *official_layer_status(server_result),
                *retained_remote_status,
            ],
            "used_as_prior_only": True,
            "not_field_specific_fact": True,
            "disclaimer": (
                "Bundled intersections were recomputed by the server at field save. "
                "Remote-only intersections remain client-snapshot context. All mapped "
                "polygons are priors, not field truth or management authority."
            ),
        }
        canonical = json.dumps(governed, sort_keys=True, separators=(",", ":"), default=str)
        lineage = {
            "schema_version": "open_agronomy_agent.geo_context_lineage.v1",
            "snapshot_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "server_recomputed_layer_ids": local_layer_ids,
            "server_recomputed_match_count": len(server_intersections),
            "client_snapshot_remote_match_count": len(retained_remote),
            "binding_boundary": (
                "Bundled-layer matches are server-recomputed. Remote matches are retained "
                "only as context-only client snapshots and are not source attestation."
            ),
        }
        return governed, lineage

    def workspace_quota_report(workspace: dict[str, Any]) -> dict[str, Any]:
        return _quota_report(workspace, store.phase4_workspace_usage(workspace["id"]))

    def workspace_corpus_health(workspace: dict[str, Any]) -> dict[str, Any]:
        return _corpus_health_summary(
            workspace=workspace,
            data_sources=store.list_phase4_data_sources(workspace["id"]),
            ingest_jobs=store.list_phase4_ingest_jobs(workspace["id"]),
            chunk_counts=store.count_phase4_document_chunks_by_source(workspace["id"]),
        )

    def admin_workspace_metrics(workspace: dict[str, Any]) -> dict[str, Any]:
        usage = store.phase4_workspace_usage(workspace["id"])
        quota_report = _quota_report(workspace, usage)
        data_sources = store.list_phase4_data_sources(workspace["id"])
        ingest_jobs = store.list_phase4_ingest_jobs(workspace["id"])
        eval_candidates = store.list_phase4_eval_candidates(workspace["id"])
        eval_runs = store.list_phase4_eval_runs(workspace["id"])
        exports = store.list_phase4_exports(workspace_id=workspace["id"], limit=25)
        audit_events = store.list_phase4_audit_events(workspace_id=workspace["id"], limit=10)
        corpus_health = _corpus_health_summary(
            workspace=workspace,
            data_sources=data_sources,
            ingest_jobs=ingest_jobs,
            chunk_counts=store.count_phase4_document_chunks_by_source(workspace["id"]),
        )
        return {
            "workspace_id": workspace["id"],
            "organization_id": workspace["organization_id"],
            "storage": {
                "backend": "sqlite-local-dev",
                "db_path": str(settings.db_path),
                "artifact_root": str(settings.artifact_root),
            },
            "usage": usage,
            "quota": quota_report,
            "corpus_health": corpus_health,
            "ingest": {
                "job_count": len(ingest_jobs),
                "queued": sum(1 for job in ingest_jobs if job.get("status") == "queued"),
                "running": sum(1 for job in ingest_jobs if job.get("status") == "running"),
                "failed": sum(1 for job in ingest_jobs if job.get("status") in {"failed", "error"}),
            },
            "eval": {
                "candidate_count": len(eval_candidates),
                "pending_candidates": sum(1 for item in eval_candidates if item.get("review_status") == "pending"),
                "approved_candidates": sum(1 for item in eval_candidates if item.get("review_status") == "approved_for_suite"),
                "run_count": len(eval_runs),
                "latest_run_status": eval_runs[0]["status"] if eval_runs else None,
            },
            "exports": {
                "recent_count": len(exports),
                "latest_sha256": exports[0].get("sha256") if exports else None,
            },
            "audit": {
                "recent_count": len(audit_events),
                "latest_event_type": audit_events[0].get("event_type") if audit_events else None,
            },
        }

    def admin_monitoring_dashboard(workspace: dict[str, Any]) -> dict[str, Any]:
        metrics = admin_workspace_metrics(workspace)
        alerts: list[dict[str, Any]] = []

        def add_alert(key: str, severity: str, message: str, evidence: dict[str, Any]) -> None:
            alerts.append({"key": key, "severity": severity, "message": message, "evidence": evidence})

        exhausted_limits = [item for item in metrics["quota"]["limits"] if item["exceeded"] or item["remaining"] == 0]
        if exhausted_limits:
            add_alert(
                "workspace_quota_exhausted",
                "critical",
                "One or more workspace quotas are exhausted.",
                {"blocked_limits": exhausted_limits},
            )
        if metrics["corpus_health"]["status"] == "blocked":
            add_alert(
                "corpus_health_blocked",
                "critical",
                "Corpus health is blocked by missing, failed, or non-indexed source artifacts.",
                {"issues": metrics["corpus_health"].get("issues", [])},
            )
        if int(metrics["ingest"]["failed"]) > 0:
            add_alert(
                "ingest_failures_present",
                "warning",
                "One or more ingest jobs failed and need operator review.",
                {"failed": metrics["ingest"]["failed"]},
            )
        if int(metrics["ingest"]["queued"]) > 0:
            add_alert(
                "ingest_queue_not_empty",
                "info",
                "Ingest work is queued; watch worker freshness during demos.",
                {"queued": metrics["ingest"]["queued"]},
            )
        if metrics["eval"]["latest_run_status"] in {"failed", "error"}:
            add_alert(
                "latest_eval_failed",
                "warning",
                "Latest eval replay did not complete successfully.",
                {"latest_run_status": metrics["eval"]["latest_run_status"]},
            )
        if settings.rate_limit_fail_open:
            add_alert(
                "rate_limit_fail_open",
                "critical",
                "Rate limiter is configured fail-open, which is unsafe for public demos.",
                {"backend": settings.rate_limit_backend},
            )
        if settings.job_queue_fail_open:
            add_alert(
                "job_queue_fail_open",
                "critical",
                "Job queue enqueue failures are configured fail-open.",
                {"backend": job_queue.backend},
            )
        if not settings.structured_access_logs:
            add_alert(
                "structured_access_logs_disabled",
                "warning",
                "Structured access logs are disabled, reducing incident traceability.",
                {},
            )
        if not settings.otel_enabled:
            add_alert(
                "otel_exporter_not_configured",
                "info",
                "OpenTelemetry export is disabled; local dashboards rely on admin endpoints and access logs.",
                {"service_name": settings.otel_service_name},
            )

        severity_rank = {"critical": 3, "warning": 2, "info": 1}
        max_severity = max((severity_rank.get(str(alert["severity"]), 0) for alert in alerts), default=0)
        status = "critical" if max_severity >= 3 else "degraded" if max_severity >= 2 else "ok"
        panels = [
            {
                "key": "service_health",
                "title": "Service health",
                "status": "degraded" if exhausted_limits or metrics["corpus_health"]["status"] == "blocked" else "ok",
                "metrics": {
                    "storage": metrics["storage"]["backend"],
                    "database_backend": settings.database_backend,
                    "rate_limit_backend": settings.rate_limit_backend,
                    "job_queue_backend": job_queue.backend,
                },
            },
            {
                "key": "workspace_usage",
                "title": "Workspace usage and quotas",
                "status": "degraded" if exhausted_limits else "ok",
                "metrics": metrics["quota"],
            },
            {
                "key": "corpus_ingest",
                "title": "Corpus and ingest",
                "status": metrics["corpus_health"]["status"],
                "metrics": {"corpus_health": metrics["corpus_health"], "ingest": metrics["ingest"]},
            },
            {
                "key": "research_eval_exports",
                "title": "Research, eval, and exports",
                "status": "degraded" if metrics["eval"]["latest_run_status"] in {"failed", "error"} else "ok",
                "metrics": {"eval": metrics["eval"], "exports": metrics["exports"]},
            },
            {
                "key": "audit_traceability",
                "title": "Audit traceability",
                "status": "ok" if metrics["audit"]["recent_count"] else "degraded",
                "metrics": {"audit": metrics["audit"], "structured_access_logs": settings.structured_access_logs},
            },
        ]
        return {
            "workspace_id": workspace["id"],
            "organization_id": workspace["organization_id"],
            "status": status,
            "alert_count": len(alerts),
            "alerts": alerts,
            "panels": panels,
            "slo_targets": {
                "api_availability": "99.5% successful non-health requests during demo windows",
                "chat_latency_p95_seconds": 12,
                "export_success_rate": "99% successful JSON/Markdown/CSV/ZIP exports",
                "queue_freshness_seconds": 120,
                "tenant_isolation_incidents": 0,
            },
        }

    def enforce_workspace_quota(workspace: dict[str, Any], quota_key: str, *, increment: int = 1) -> None:
        usage_key = QUOTA_USAGE_KEYS[quota_key]
        quotas = _workspace_quotas(workspace)
        usage = store.phase4_workspace_usage(workspace["id"])
        limit = quotas[quota_key]
        used = int(usage.get(usage_key, 0))
        if used + increment > limit:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "workspace quota exceeded",
                    "quota": quota_key,
                    "usage_key": usage_key,
                    "used": used,
                    "increment": increment,
                    "limit": limit,
                    "workspace_id": workspace["id"],
                },
            )

    def require_thread_for_user(user: dict[str, Any], thread_id: str) -> dict[str, Any]:
        thread = store.get_phase4_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        if not store.phase4_user_can_access_thread(user["id"], thread_id):
            raise HTTPException(status_code=403, detail="thread access denied")
        return thread

    def require_eval_candidate_for_user(user: dict[str, Any], candidate_id: str) -> dict[str, Any]:
        candidate = store.get_phase4_eval_candidate(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="eval candidate not found")
        require_workspace_for_user(user, candidate["workspace_id"])
        return candidate

    def require_attachment_for_workspace(workspace: dict[str, Any], attachment_id: str) -> dict[str, Any]:
        attachment = store.get_phase4_attachment(attachment_id)
        if not attachment or attachment["workspace_id"] != workspace["id"]:
            raise HTTPException(status_code=404, detail="attachment not found")
        return attachment

    def require_field_context_for_workspace(workspace: dict[str, Any], field_context_id: str) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context or field_context["workspace_id"] != workspace["id"]:
            raise HTTPException(status_code=404, detail="field context not found")
        return field_context

    def ensure_legacy_session(thread: dict[str, Any]) -> tuple[dict[str, Any], str]:
        metadata = dict(thread.get("metadata", {}))
        legacy_session_id = metadata.get("legacy_session_id")
        if legacy_session_id:
            existing = store.get_session(str(legacy_session_id))
            if existing:
                if not _session_owner_id(existing):
                    store.update_session(
                        str(legacy_session_id),
                        context=_context_with_session_owner(
                            existing.get("context"),
                            str(thread["created_by_user_id"]),
                        ),
                    )
                return metadata, str(legacy_session_id)
        field_context = store.get_phase4_field_context(thread["field_context_id"]) if thread.get("field_context_id") else None
        legacy = store.create_session(
            title=f"Hosted thread: {thread['title']}",
            user_pseudonym=thread["created_by_user_id"],
            tags=["phase4", "hosted"],
            context=_context_with_session_owner(
                {
                    "crop": (field_context or {}).get("crop_current"),
                    "region": (field_context or {}).get("region_text"),
                    "jurisdiction": (field_context or {}).get("province_state") or (field_context or {}).get("country"),
                    "notes": (field_context or {}).get("management_notes"),
                },
                str(thread["created_by_user_id"]),
            ),
            consent={
                "local_trace_capture": thread.get("trace_capture_level") != "none",
                "research_export_allowed": thread.get("trace_capture_level") == "research_opt_in",
                "training_export_allowed": bool(thread.get("training_eligible")),
                "redaction_required": False,
            },
        )
        metadata["legacy_session_id"] = legacy["session_id"]
        updated = store.update_phase4_thread_metadata(thread["id"], metadata=metadata)
        return dict((updated or thread).get("metadata", metadata)), legacy["session_id"]

    def phase4_trace_payload(thread_id: str) -> dict[str, Any]:
        thread = store.get_phase4_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        events = store.list_phase4_trace_events(thread_id)
        field_context = store.get_phase4_field_context(thread["field_context_id"]) if thread.get("field_context_id") else None
        feedback = store.list_phase4_feedback_for_thread(thread_id)
        return _phase4_thread_trace_bundle(thread=thread, events=events, field_context=field_context, feedback=feedback)

    def persist_phase5_turn_record(
        *,
        profiler: TraceProfiler,
        thread_id: str,
        turn_id: str,
        user_id: str | None,
        workspace_id: str | None,
        answer_text: str,
        trace: dict[str, Any],
        system_state: dict[str, Any],
        model_id: str,
        rag_config_id: str | None,
        max_tokens: int,
        route_question_type_fallback: str | None = None,
        risk_level_fallback: str | None = None,
    ) -> dict[str, Any]:
        profiler.set_thread_id(thread_id)
        profiler.set_turn_id(turn_id)
        leak_findings = []
        with profiler.span("agent.answer.leak_check", input_size=len(answer_text), component_version=LEAK_GUARD_VERSION):
            leak_findings = [finding.as_record() for finding in detect_prompt_leaks(answer_text)]
        if leak_findings:
            store.create_phase5_prompt_leak_events(
                trace_id=profiler.trace_id,
                thread_id=thread_id,
                turn_id=turn_id,
                findings=leak_findings,
            )
        profiler.ensure_stages()
        docs = trace.get("retrieved_docs", []) if isinstance(trace, dict) else []
        route = trace.get("route", {}) if isinstance(trace, dict) else {}
        top_doc_score = None
        if docs and isinstance(docs[0], dict) and docs[0].get("score") is not None:
            try:
                top_doc_score = float(docs[0]["score"])
            except (TypeError, ValueError):
                top_doc_score = None
        quality_flags = [f"prompt_leak:{finding['leak_class']}" for finding in leak_findings]
        if any(span.status == "error" for span in profiler.spans):
            quality_flags.append("span_error")
        if system_state.get("model_circuit_breaker"):
            quality_flags.append("model_circuit_breaker")
        prompt_messages = trace.get("prompt_messages", []) if isinstance(trace, dict) else []
        tool_precision_proxy, tool_recall_proxy = _phase5_tool_precision_recall(trace)
        metrics = {
            "schema_version": PHASE5_TURN_METRICS_SCHEMA_VERSION,
            "trace_id": profiler.trace_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "route_question_type": route.get("question_type") or route_question_type_fallback,
            "risk_level": route.get("risk_level") or risk_level_fallback,
            "namespaces": list(route.get("namespaces", [])) if isinstance(route.get("namespaces"), list) else [],
            "required_tools": list(route.get("required_tools", [])) if isinstance(route.get("required_tools"), list) else [],
            "rag_config_version": rag_config_id,
            "corpus_bundle_version": settings.corpus_audit_id,
            "prompt_template_version": settings.prompt_version,
            "context_packer_version": system_state.get("context_packer_version") or "phase5_context_packer_v1",
            "model_id": model_id,
            "quantization": _model_quantization(model_id),
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "top_p": 0.9,
            "top_k": 0,
            "total_latency_ms": profiler.total_latency_ms(),
            "time_to_first_token_ms": None,
            "decode_tokens_per_sec": None,
            "prompt_tokens_est": _estimate_tokens(prompt_messages),
            "completion_tokens_est": _estimate_tokens(answer_text),
            "context_tokens_est": _estimate_tokens(docs),
            "retrieval_doc_count": len(docs),
            "top_doc_score": top_doc_score,
            "source_diversity": len({doc.get("source") or doc.get("source_type") for doc in docs if isinstance(doc, dict)}),
            "required_support_rate": system_state.get("retrieval_support"),
            "tool_notes_count": len(trace.get("tool_invocations", [])) if isinstance(trace, dict) else 0,
            "tool_precision_proxy": tool_precision_proxy,
            "tool_recall_proxy": tool_recall_proxy,
            "answer_word_count": len(re.findall(r"\b\w+\b", answer_text)),
            "leak_check_passed": not leak_findings,
            "risk_banner_present": _answer_has_risk_banner(answer_text),
            "missing_data_present": _answer_has_missing_data(answer_text),
            "quality_flags": quality_flags,
            "user_feedback_score": None,
            "human_review_status": "unreviewed",
            "reflection_status": "not_created",
        }
        store.create_phase5_trace_spans(profiler.span_records())
        saved_metrics = store.create_phase5_turn_metrics(metrics)
        return saved_metrics

    def persist_phase5_turn_observability(
        *,
        profiler: TraceProfiler,
        thread: dict[str, Any],
        user: dict[str, Any],
        assistant_message: dict[str, Any],
        answer_text: str,
        trace: dict[str, Any],
        system_state: dict[str, Any],
        model_id: str,
        rag_config_id: str | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        return persist_phase5_turn_record(
            profiler=profiler,
            thread_id=thread["id"],
            turn_id=assistant_message["id"],
            user_id=user["id"],
            workspace_id=thread["workspace_id"],
            answer_text=answer_text,
            trace=trace,
            system_state=system_state,
            model_id=model_id,
            rag_config_id=rag_config_id,
            max_tokens=max_tokens,
            route_question_type_fallback=thread.get("task_family"),
            risk_level_fallback=thread.get("risk_level"),
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "backend_version": settings.prompt_version,
            "corpus_audit_id": settings.corpus_audit_id,
            "model_configured": settings.default_model_id,
            "default_rag_config": settings.default_rag_config,
            "storage": storage_label_for(store),
            "db_path": storage_db_path_for(store, settings.db_path),
            "database_backend": settings.database_backend,
            "database_url_configured": bool(settings.database_url),
            "allow_local_dev_auth": settings.allow_local_dev_auth,
            "local_pairing": {
                "enabled": bool(settings.local_pairing_token_sha256),
                "consumed": bool(app.state.local_pairing_consumed),
                "transport_required": "https",
            },
            "network": {
                "mode": settings.network_mode,
                "external_calls_allowed": settings.network_mode == "online",
            },
            "telemetry": telemetry.status(),
            "object_store": {"backend": settings.object_store_backend},
            "vlm_observation": {"backend": settings.vlm_observation_backend},
            "rate_limit": {"backend": settings.rate_limit_backend, "fail_open": settings.rate_limit_fail_open},
            "job_queue": {
                "backend": job_queue.backend,
                "fail_open": settings.job_queue_fail_open,
                "ingest_queue": settings.job_queue_name,
                "eval_queue": settings.eval_queue_name,
                "export_queue": settings.export_queue_name,
                "embedding_queue": settings.embedding_queue_name,
                "image_queue": settings.image_queue_name,
            },
        }

    @app.get("/api/configs")
    async def configs() -> dict[str, Any]:
        config_dir = repo_path("configs")
        rag_configs = (
            sorted([f"configs/{p.name}" for p in config_dir.glob("*.yaml") if p.name.startswith("rag")])
            if settings.allow_rag_config_override
            else [settings.default_rag_config]
        )
        model_config = _read_json(repo_path(settings.model_config_path))
        model_ids = [
            model_config.get("serving_model_id") or settings.default_model_id,
            model_config.get("model_id"),
            model_config.get("assistant_model_id"),
            model_config.get("draft_model_id"),
        ]
        serving_model_id = str(model_config.get("serving_model_id") or settings.default_model_id)
        assistant_model_id = str(model_config.get("assistant_model_id") or "")
        serving_revision = str(model_config.get("model_revision") or "").strip() or None
        assistant_revision = str(model_config.get("assistant_model_revision") or "").strip() or None
        serving_readiness = local_model_snapshot_status(serving_model_id, revision=serving_revision)
        model_profiles = [
            {
                "id": serving_model_id,
                "label": str(model_config.get("serving_label") or serving_model_id),
                "role": str(model_config.get("serving_role") or "default"),
                "max_tokens": int(model_config.get("serving_max_tokens") or 140),
                "quality_gate": str(model_config.get("serving_quality_gate") or "answer_default"),
                "local_ready": bool(serving_readiness["ready"]),
                "local_status": str(serving_readiness["status"]),
                "local_detail": str(serving_readiness["detail"]),
            }
        ]
        if assistant_model_id:
            assistant_readiness = local_model_snapshot_status(assistant_model_id, revision=assistant_revision)
            model_profiles.append(
                {
                    "id": assistant_model_id,
                    "label": str(model_config.get("assistant_label") or assistant_model_id),
                    "role": str(model_config.get("assistant_role") or "fast"),
                    "max_tokens": int(model_config.get("assistant_max_tokens") or 35),
                    "quality_gate": str(model_config.get("assistant_quality_gate") or "fast_repaired"),
                    "local_ready": bool(assistant_readiness["ready"]),
                    "local_status": str(assistant_readiness["status"]),
                    "local_detail": str(assistant_readiness["detail"]),
                }
            )
        knowledge_activation = (
            read_activation(settings.knowledge_update_root)
            if settings.knowledge_update_root is not None
            else None
        )
        knowledge_freshness: dict[str, Any] | None = None
        knowledge_freshness_error: str | None = None
        if knowledge_activation is not None:
            try:
                knowledge_freshness = validate_activation_freshness(knowledge_activation)
            except ValueError as exc:
                knowledge_freshness_error = str(exc)
        return {
            "modes": (
                ["baseline", "agronomic_rag", "mock"]
                if settings.allow_model_id_override
                else ["baseline", "agronomic_rag"]
            ),
            "rag_configs": rag_configs,
            "models": list(dict.fromkeys(str(model_id) for model_id in model_ids if model_id)),
            "model_profiles": model_profiles,
            "prompt_versions": [settings.prompt_version],
            "default_rag_config": settings.default_rag_config,
            "network": {
                "mode": settings.network_mode,
                "external_calls_allowed": settings.network_mode == "online",
                "telemetry_enabled": settings.otel_enabled,
            },
            "knowledge_update": {
                "configured": settings.knowledge_update_root is not None,
                "status": (
                    "expired"
                    if knowledge_freshness_error
                    else "active"
                    if knowledge_activation
                    else "no_active_update"
                    if settings.knowledge_update_root is not None
                    else "not_configured"
                ),
                "package_id": (knowledge_activation or {}).get("package_id"),
                "previous_package_id": (knowledge_activation or {}).get("previous_package_id"),
                "activated_at": (knowledge_activation or {}).get("activated_at"),
                "operation": (knowledge_activation or {}).get("operation"),
                "release_sequence": (knowledge_activation or {}).get("release_sequence"),
                "highest_release_sequence": (knowledge_activation or {}).get("highest_release_sequence"),
                "expires_at": (knowledge_activation or {}).get("expires_at"),
                "freshness_checked_at": (knowledge_freshness or {}).get("checked_at"),
                "signature_required": (
                    settings.knowledge_update_root is not None
                    and not settings.knowledge_update_allow_unsigned
                ),
                "signature_mode": (
                    "threshold_policy"
                    if settings.knowledge_update_trust_policy is not None
                    else "legacy_single_key"
                    if settings.knowledge_update_public_key is not None
                    else "unsigned_development"
                    if settings.knowledge_update_allow_unsigned
                    else "not_configured"
                ),
                "trust_policy_id": (
                    settings.knowledge_update_trust_policy.policy_id
                    if settings.knowledge_update_trust_policy is not None
                    else None
                ),
                "trust_policy_sequence": (
                    settings.knowledge_update_trust_policy.policy_sequence
                    if settings.knowledge_update_trust_policy is not None
                    else None
                ),
                "trust_policy_threshold": (
                    settings.knowledge_update_trust_policy.threshold
                    if settings.knowledge_update_trust_policy is not None
                    else None
                ),
                "trust_policy_sha256": (
                    settings.knowledge_update_trust_policy.sha256
                    if settings.knowledge_update_trust_policy is not None
                    else None
                ),
                "startup_validation": (
                    "failed_runtime_freshness"
                    if knowledge_freshness_error
                    else "passed"
                    if knowledge_activation
                    else "not_applicable"
                ),
            },
            "rag_config_control": {
                "operator_managed": not settings.allow_rag_config_override,
                "client_override_allowed": settings.allow_rag_config_override,
            },
            "model_control": {
                "operator_managed": not settings.allow_model_id_override,
                "client_override_allowed": settings.allow_model_id_override,
            },
        }

    @app.get("/api/data-use")
    async def api_data_use() -> dict[str, Any]:
        return data_use_statement(network_mode=settings.network_mode, telemetry_enabled=settings.otel_enabled)

    @app.get("/api/knowledge/coverage")
    async def api_knowledge_coverage(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return canadian_knowledge_coverage()

    @app.get("/api/advisory/readiness")
    async def api_advisory_readiness(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return canadian_knowledge_coverage()["advisory_readiness"]

    @app.get("/api/models/conference-decision")
    async def api_conference_model_decision(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return conference_model_decision(
            active_model_config_path=repo_path(settings.model_config_path),
        )

    @app.get("/api/models/adaptation-readiness")
    async def api_model_adaptation_readiness(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return model_adaptation_readiness(
            active_model_config_path=repo_path(settings.model_config_path),
        )

    @app.get("/api/benchmarks/aiagribench-proxy/latest")
    async def aiagribench_proxy_latest(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return latest_aiagribench_proxy_summary()

    @app.get("/api/benchmarks/open-agronomy/latest")
    async def open_agronomy_benchmark_latest(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return open_agronomy_benchmark_summary()

    @app.get("/api/benchmarks/aiagribench-proxy/freeze-manifest")
    async def aiagribench_proxy_freeze_manifest(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return aiagribench_submission_freeze_manifest()

    @app.get("/api/benchmarks/public-demo-rehearsal")
    async def public_demo_rehearsal(
        request: Request,
        limit: int = Query(default=12, ge=0, le=200),
    ) -> dict[str, Any]:
        _demo_field_user(request)
        return public_demo_rehearsal_packet(limit=limit)

    @app.get("/api/benchmarks/public-shadow-heldout")
    async def public_shadow_heldout(
        request: Request,
        limit: int = Query(default=12, ge=0, le=200),
    ) -> dict[str, Any]:
        _demo_field_user(request)
        return public_shadow_heldout_packet(limit=limit)

    @app.get("/api/benchmarks/human-review-queue")
    async def human_review_queue(
        request: Request,
        limit: int = Query(default=12, ge=0, le=200),
    ) -> dict[str, Any]:
        _demo_field_user(request)
        return human_review_queue_packet(limit=limit)

    @app.get("/api/benchmarks/human-review-batches")
    async def human_review_batches(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return human_review_batches_summary()

    @app.get("/api/benchmarks/human-review-outcomes")
    async def human_review_outcomes(request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        return human_review_outcome_summary()

    @app.get("/api/benchmarks/artifacts/{artifact_id}", response_model=None)
    async def benchmark_artifact(artifact_id: str, request: Request) -> FileResponse:
        _demo_field_user(request)
        try:
            artifact = benchmark_artifact_download(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown benchmark artifact") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Benchmark artifact is not available on disk") from exc
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return FileResponse(
            artifact["path"],
            media_type=artifact["media_type"],
            filename=artifact["filename"],
        )

    @app.get("/api/tools/public-adapter-readiness")
    async def public_adapter_readiness_status() -> dict[str, Any]:
        return public_adapter_readiness()

    @app.get("/health")
    async def phase4_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "phase": "4-hosted-platform",
            "auth_mode": _auth_mode(settings),
            "storage": storage_label_for(store),
            "database_backend": settings.database_backend,
            "database_url_configured": bool(settings.database_url),
            "allow_local_dev_auth": settings.allow_local_dev_auth,
            "local_pairing": {
                "enabled": bool(settings.local_pairing_token_sha256),
                "consumed": bool(app.state.local_pairing_consumed),
                "transport_required": "https",
            },
            "network": {
                "mode": settings.network_mode,
                "external_calls_allowed": settings.network_mode == "online",
            },
            "object_store": {"backend": settings.object_store_backend},
            "vlm_observation": {"backend": settings.vlm_observation_backend},
            "rate_limit": {"backend": settings.rate_limit_backend, "fail_open": settings.rate_limit_fail_open},
            "job_queue": {
                "backend": job_queue.backend,
                "fail_open": settings.job_queue_fail_open,
                "ingest_queue": settings.job_queue_name,
                "eval_queue": settings.eval_queue_name,
                "export_queue": settings.export_queue_name,
                "embedding_queue": settings.embedding_queue_name,
                "image_queue": settings.image_queue_name,
            },
            "corpus_audit_id": settings.corpus_audit_id,
            "telemetry": telemetry.status(),
        }

    @app.get("/admin/health")
    async def phase4_admin_health(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        quota_report = workspace_quota_report(workspace)
        corpus_health = workspace_corpus_health(workspace)
        status = "ok"
        if quota_report["blocked"] or corpus_health["status"] == "blocked":
            status = "degraded"
        return {
            "status": status,
            "phase": "4-hosted-platform",
            "workspace_id": workspace["id"],
            "organization_id": workspace["organization_id"],
            "auth_mode": _auth_mode(settings),
            "storage": storage_label_for(store),
            "database_backend": settings.database_backend,
            "database_url_configured": bool(settings.database_url),
            "allow_local_dev_auth": settings.allow_local_dev_auth,
            "network": {
                "mode": settings.network_mode,
                "external_calls_allowed": settings.network_mode == "online",
            },
            "object_store": {"backend": settings.object_store_backend},
            "vlm_observation": {"backend": settings.vlm_observation_backend},
            "rate_limit": {"backend": settings.rate_limit_backend, "fail_open": settings.rate_limit_fail_open},
            "job_queue": {
                "backend": job_queue.backend,
                "fail_open": settings.job_queue_fail_open,
                "ingest_queue": settings.job_queue_name,
                "eval_queue": settings.eval_queue_name,
                "export_queue": settings.export_queue_name,
                "embedding_queue": settings.embedding_queue_name,
                "image_queue": settings.image_queue_name,
            },
            "quota_blocked": quota_report["blocked"],
            "corpus_status": corpus_health["status"],
            "corpus_audit_id": settings.corpus_audit_id,
            "telemetry": telemetry.status(),
        }

    @app.get("/admin/metrics")
    async def phase4_admin_metrics(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        return admin_workspace_metrics(workspace)

    @app.get("/admin/monitoring")
    async def phase4_admin_monitoring(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        return admin_monitoring_dashboard(workspace)

    @app.post("/api/rum", status_code=202)
    async def phase6_frontend_rum(payload: FrontendRumMetricRequest, request: Request) -> dict[str, Any]:
        record = payload.model_dump()
        record["metadata"] = _safe_frontend_rum_metadata(payload.metadata)
        record["received_at"] = datetime.now(timezone.utc).isoformat()
        record["request_id"] = getattr(request.state, "request_id", None)
        record["budget_status"] = _frontend_rum_budget_status(payload.metric_name, payload.value)
        records = list(getattr(app.state, "frontend_rum_records", []))
        records.append(record)
        app.state.frontend_rum_records = records[-1000:]
        return {"accepted": True, "budget_status": record["budget_status"]}

    @app.post("/api/frontend-events", status_code=202)
    async def phase6_frontend_event(payload: FrontendEventRequest, request: Request) -> dict[str, Any]:
        record = payload.model_dump()
        record["metadata"] = _safe_frontend_event_metadata(payload.metadata)
        record["received_at"] = datetime.now(timezone.utc).isoformat()
        record["request_id"] = getattr(request.state, "request_id", None)
        records = list(getattr(app.state, "frontend_event_records", []))
        records.append(record)
        app.state.frontend_event_records = records[-1000:]
        return {"accepted": True}

    @app.get("/api/admin/frontend-rum")
    async def phase6_frontend_rum_summary(
        workspace_id: str,
        limit: int = Query(default=500, ge=1, le=1000),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        records = [
            record
            for record in list(getattr(app.state, "frontend_rum_records", []))[-limit:]
            if record.get("workspace_id") in {None, "", workspace["id"]}
        ]
        return {"workspace_id": workspace["id"], **_frontend_rum_summary(records), "records": records}

    @app.get("/api/admin/frontend-events")
    async def phase6_frontend_event_summary(
        workspace_id: str,
        limit: int = Query(default=500, ge=1, le=1000),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        records = [
            record
            for record in list(getattr(app.state, "frontend_event_records", []))[-limit:]
            if record.get("workspace_id") in {None, "", workspace["id"]}
        ]
        return {"workspace_id": workspace["id"], **_frontend_event_summary(records), "records": records}

    @app.get("/admin/audit-events")
    async def phase4_admin_audit_events(
        workspace_id: str,
        event_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        return store.list_phase4_audit_events(workspace_id=workspace["id"], event_type=event_type, limit=limit)

    @app.get("/api/admin/traces/{trace_id}")
    async def phase5_admin_trace(trace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        trace_payload = store.get_phase5_admin_trace(trace_id)
        if not trace_payload:
            raise HTTPException(status_code=404, detail="trace not found")
        metrics = trace_payload.get("metrics", {})
        workspace_id = metrics.get("workspace_id")
        if not workspace_id:
            raise HTTPException(status_code=404, detail="trace workspace not found")
        require_workspace_role(user, str(workspace_id), ORG_ADMIN_ROLES)
        return trace_payload

    @app.get("/api/admin/latency")
    async def phase5_latency_dashboard(
        workspace_id: str,
        limit: int = Query(default=500, ge=1, le=5000),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        metrics = store.list_phase5_turn_metrics(workspace["id"], limit=limit)
        spans = [span for metric in metrics for span in store.list_phase5_trace_spans(metric["trace_id"])]
        return {
            "workspace_id": workspace["id"],
            "schema_version": PHASE5_TURN_METRICS_SCHEMA_VERSION,
            "dashboard": _phase5_latency_dashboard(metrics, spans),
        }

    @app.get("/api/admin/latency/export")
    async def phase5_latency_export(
        workspace_id: str,
        limit: int = Query(default=500, ge=1, le=5000),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        metrics = store.list_phase5_turn_metrics(workspace["id"], limit=limit)
        spans = [span for metric in metrics for span in store.list_phase5_trace_spans(metric["trace_id"])]
        return {
            "workspace_id": workspace["id"],
            "schema_version": PHASE5_TURN_METRICS_SCHEMA_VERSION,
            "summary": _phase5_latency_dashboard(metrics, spans),
            "turn_metrics": metrics,
            "spans": spans,
        }

    @app.get("/api/admin/threads/{thread_id}/phase5-traces")
    async def phase5_thread_trace_bundle(thread_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        thread = store.get_phase4_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        require_workspace_role(user, thread["workspace_id"], ORG_ADMIN_ROLES)
        metrics = [metric for metric in store.list_phase5_turn_metrics(thread["workspace_id"], limit=5000) if metric.get("thread_id") == thread_id]
        traces = [
            {
                "trace_id": metric["trace_id"],
                "metrics": metric,
                "spans": store.list_phase5_trace_spans(metric["trace_id"]),
                "prompt_leak_events": store.list_phase5_prompt_leak_events(metric["trace_id"]),
            }
            for metric in metrics
        ]
        return {
            "schema_version": "phase5.thread_trace_bundle.v1",
            "thread_id": thread_id,
            "workspace_id": thread["workspace_id"],
            "trace_count": len(traces),
            "traces": traces,
        }

    @app.post("/api/phase5/optimization-candidates", status_code=201)
    async def phase5_create_optimization_candidate(
        payload: Phase5OptimizationCandidateCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), RESEARCH_REVIEW_ROLES)
        candidate = store.create_phase5_optimization_candidate(
            {
                "workspace_id": workspace["id"],
                "created_by_user_id": user["id"],
                "candidate_type": payload.candidate_type,
                "parent_version": payload.parent_version,
                "candidate_version": payload.candidate_version,
                "generated_from_trace_ids": [str(item) for item in payload.generated_from_trace_ids],
                "reflection_summary": payload.reflection_summary,
                "patch": payload.patch,
                "eval_summary": payload.eval_summary,
                "rollback_plan": payload.rollback_plan,
            }
        )
        return {**candidate, "promotion_gate": candidate_promotion_gate(candidate)}

    @app.get("/api/phase5/optimization-candidates")
    async def phase5_list_optimization_candidates(
        workspace_id: str,
        pareto_status: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_role(user, workspace_id, RESEARCH_REVIEW_ROLES)
        return store.list_phase5_optimization_candidates(workspace["id"], pareto_status=pareto_status)

    @app.post("/api/phase5/optimization-candidates/{candidate_id}/promote")
    async def phase5_promote_optimization_candidate(
        candidate_id: str,
        payload: Phase5OptimizationCandidateReview,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        candidate = store.get_phase5_optimization_candidate(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="optimization candidate not found")
        require_workspace_role(user, candidate["workspace_id"], RESEARCH_REVIEW_ROLES)
        merged_candidate = {**candidate, "eval_summary": {**candidate.get("eval_summary", {}), **payload.eval_summary}}
        gate = candidate_promotion_gate(merged_candidate)
        if not gate["promotion_allowed"]:
            raise HTTPException(status_code=400, detail={"error": "candidate failed Phase 5 Pareto promotion gate", "gate": gate})
        promoted = store.update_phase5_optimization_candidate_status(
            candidate_id,
            pareto_status="promoted",
            promoted_at=datetime.now(timezone.utc).isoformat(),
            eval_summary=merged_candidate["eval_summary"],
        )
        return {**(promoted or candidate), "promotion_gate": gate}

    @app.post("/api/phase5/sft-candidates/from-trace", status_code=201)
    async def phase5_create_sft_candidate_from_trace(
        payload: Phase5SftCandidateCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        trace_payload = store.get_phase5_admin_trace(str(payload.trace_id))
        if not trace_payload:
            raise HTTPException(status_code=404, detail="trace not found")
        metrics = trace_payload["metrics"]
        thread = store.get_phase4_thread(metrics["thread_id"])
        if not thread:
            raise HTTPException(status_code=404, detail="thread not found")
        require_workspace_role(user, thread["workspace_id"], RESEARCH_REVIEW_ROLES)
        if not thread.get("training_eligible"):
            raise HTTPException(status_code=400, detail="thread is not training eligible")
        if not metrics.get("leak_check_passed"):
            raise HTTPException(status_code=400, detail="trace failed prompt leak check")
        if not (payload.failure_class or "").strip():
            raise HTTPException(status_code=400, detail="failure_class is required for SFT candidates")
        trace_events = store.list_phase4_trace_events(thread["id"])
        source_trace = {
            "trace_id": metrics["trace_id"],
            "metrics": metrics,
            "labels": payload.labels,
            "trace": {
                "retrieved_docs": _latest_phase4_retrieved_docs(trace_events),
                "metadata": thread.get("metadata") or {},
            },
        }
        if is_held_out_eval_trace(source_trace, labels=payload.labels):
            raise HTTPException(status_code=400, detail="held-out eval rows cannot become SFT candidates")
        private_field_training_blocked = contains_private_field_data(
            source_trace,
            labels=payload.labels,
        ) and not has_explicit_private_training_consent(source_trace, labels=payload.labels)
        if private_field_training_blocked:
            raise HTTPException(status_code=400, detail="private field data requires explicit training consent")
        source_evidence = source_evidence_from_trace_payload({"source_evidence": payload.labels.get("source_evidence")}, labels={})
        if not source_evidence:
            raise HTTPException(status_code=400, detail="source_evidence is required for SFT candidates")
        messages = store.list_phase4_messages(thread["id"])
        assistant_index = next((idx for idx, message in enumerate(messages) if message["id"] == metrics["turn_id"]), None)
        if assistant_index is None:
            raise HTTPException(status_code=400, detail="assistant message for trace was not found")
        user_message = next((message for message in reversed(messages[:assistant_index]) if message["actor"] == "user"), None)
        assistant_message = messages[assistant_index]
        if not user_message:
            raise HTTPException(status_code=400, detail="user message for trace was not found")
        training_messages = [
            {"role": "user", "content": redact_training_text(user_message["content"])},
            {"role": "assistant", "content": redact_training_text(assistant_message["content"])},
        ]
        labels = {
            **payload.labels,
            "route_question_type": metrics.get("route_question_type"),
            "risk_level": metrics.get("risk_level"),
            "repair_layer": payload.repair_layer,
            "failure_class": payload.failure_class,
            "source_trace_id": metrics["trace_id"],
            "reviewer_user_id": user["id"],
            "source_evidence": source_evidence,
        }
        candidate = store.create_phase5_training_candidate(
            {
                "workspace_id": thread["workspace_id"],
                "thread_id": thread["id"],
                "trace_id": metrics["trace_id"],
                "reviewer_user_id": user["id"],
                "review_status": "pending",
                "consent_scope": "research_and_training_opt_in",
                "redaction_status": "redacted",
                "repair_layer": payload.repair_layer,
                "failure_class": payload.failure_class,
                "messages": training_messages,
                "labels": labels,
                "dataset_card": _phase5_dataset_card(thread["workspace_id"], candidate_count=1),
            }
        )
        return candidate

    @app.get("/api/phase5/sft-candidates")
    async def phase5_list_sft_candidates(
        workspace_id: str,
        review_status: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_role(user, workspace_id, RESEARCH_REVIEW_ROLES)
        return store.list_phase5_training_candidates(workspace["id"], review_status=review_status)

    @app.patch("/api/phase5/sft-candidates/{candidate_id}/review")
    async def phase5_review_sft_candidate(
        candidate_id: str,
        payload: Phase5SftCandidateReview,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        candidate = store.get_phase5_training_candidate(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="training candidate not found")
        require_workspace_role(user, candidate["workspace_id"], RESEARCH_REVIEW_ROLES)
        updated = store.update_phase5_training_candidate_review(
            candidate_id,
            review_status=payload.review_status,
            reviewer_user_id=user["id"],
            labels=payload.labels,
        )
        return updated or {}

    @app.get("/api/phase5/sft-candidates/export")
    async def phase5_export_sft_candidates(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, RESEARCH_REVIEW_ROLES)
        approved = store.list_phase5_training_candidates(workspace["id"], review_status="approved")
        deduped_records: list[dict[str, Any]] = []
        excluded_records: list[dict[str, str]] = []
        seen_hashes: set[str] = set()
        for candidate in approved:
            labels = candidate.get("labels") if isinstance(candidate.get("labels"), dict) else {}
            if is_held_out_eval_trace(candidate, labels=labels):
                excluded_records.append({"candidate_id": str(candidate.get("id")), "reason": "held_out_eval"})
                continue
            if not labels.get("source_evidence"):
                excluded_records.append({"candidate_id": str(candidate.get("id")), "reason": "missing_source_evidence"})
                continue
            payload_hash = _hash_payload(candidate.get("messages", []))
            if payload_hash in seen_hashes:
                excluded_records.append({"candidate_id": str(candidate.get("id")), "reason": "duplicate_messages"})
                continue
            seen_hashes.add(payload_hash)
            deduped_records.append(candidate)
        store.mark_phase5_training_candidates_exported([candidate["id"] for candidate in deduped_records])
        return {
            "schema_version": "phase5_sft_dataset_export_v1",
            "workspace_id": workspace["id"],
            "candidate_count": len(deduped_records),
            "dataset_card": _phase5_dataset_card(workspace["id"], candidate_count=len(deduped_records)),
            "lora_qlora_plan": _phase5_lora_plan(settings.default_model_id),
            "excluded_count": len(excluded_records),
            "excluded_records": excluded_records,
            "records": deduped_records,
            "jsonl": "\n".join(json.dumps(candidate, sort_keys=True) for candidate in deduped_records),
        }

    @app.put("/api/phase5/adapter-registry/{adapter_id}")
    async def phase5_upsert_adapter_registry(
        adapter_id: str,
        payload: Phase5AdapterRegistryUpsert,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace_id = str(payload.workspace_id)
        require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        if payload.adapter_id != adapter_id:
            raise HTTPException(status_code=400, detail="adapter id mismatch")
        return store.upsert_phase5_adapter_registry(
            {
                "workspace_id": workspace_id,
                "adapter_id": adapter_id,
                "base_model_id": payload.base_model_id,
                "method": payload.method,
                "status": payload.status,
                "artifact_uri": payload.artifact_uri,
                "eval_summary": payload.eval_summary,
                "rollback_plan": payload.rollback_plan,
            }
        )

    @app.get("/api/phase5/adapter-registry")
    async def phase5_list_adapter_registry(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        require_workspace_for_user(user, workspace_id)
        return store.list_phase5_adapter_registry(workspace_id)

    @app.put("/api/phase5/model-registry")
    async def phase5_upsert_model_registry(
        payload: Phase5ModelRegistryUpsert,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace_id = str(payload.workspace_id)
        require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        return store.upsert_phase5_model_registry(
            {
                "workspace_id": workspace_id,
                "model_id": payload.model_id,
                "quantization": payload.quantization,
                "context_window": payload.context_window,
                "hardware_profile": payload.hardware_profile,
                "license": payload.license,
                "latency_profile": payload.latency_profile,
                "eval_profile": payload.eval_profile,
                "release_status": payload.release_status,
                "notes": payload.notes,
            }
        )

    @app.get("/api/phase5/model-registry")
    async def phase5_list_model_registry(
        workspace_id: str,
        release_status: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        require_workspace_for_user(user, workspace_id)
        return store.list_phase5_model_registry(workspace_id, release_status=release_status)

    @app.get("/api/phase5/model-registry/comparison")
    async def phase5_model_registry_comparison(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        require_workspace_for_user(user, workspace_id)
        models = store.list_phase5_model_registry(workspace_id)
        report = model_registry_comparison(models)
        return {
            **report,
            "workspace_id": workspace_id,
            "demo_model_policy": (
                "Keep mlx-community/Qwen3.5-2B-OptiQ-4bit as public demo default until a candidate beats "
                "the Phase 5 release gate and preserves the local/open story."
            ),
        }

    @app.post("/auth/local-pair", response_model=None)
    async def local_pairing(
        payload: LocalPairingRequest,
        request: Request,
    ) -> Response:
        expected = settings.local_pairing_token_sha256
        if not expected:
            raise HTTPException(status_code=404, detail="local pairing is not enabled")
        observed = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
        async with local_pairing_lock:
            if app.state.local_pairing_consumed:
                raise HTTPException(
                    status_code=409,
                    detail="local pairing token has already been consumed; restart field-LAN mode to pair again",
                )
            if not hmac.compare_digest(observed, expected):
                raise HTTPException(status_code=401, detail="invalid local pairing token")
            user = store.upsert_phase4_user(
                email="local-demo@open-agronomy.local",
                display_name="Open Agronomy paired field client",
            )
            if user.get("status") != "active":
                raise HTTPException(status_code=403, detail="local paired user is not active")
            _ensure_personal_workspace(user)
            response = _issue_password_session_response(
                user,
                request,
                auth_subject_prefix="local-pairing",
                schema_version="open_agronomy_agent.local_pairing_session.v1",
            )
            app.state.local_pairing_consumed = True
            response.headers["Cache-Control"] = "no-store"
            return response

    @app.post("/auth/signup", status_code=201)
    async def password_signup(payload: PasswordSignupRequest) -> dict[str, Any]:
        verification_token = _new_phase6_auth_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        result = store.create_phase6_password_signup(
            email=payload.email,
            display_name=payload.display_name,
            password_hash=_hash_phase6_password(payload.password),
            token_hash=_hash_phase6_auth_token(verification_token),
            expires_at=expires_at,
        )
        response = {
            "schema_version": "phase6.password_signup.v1",
            "status": "verification_required",
            "email": payload.email,
            "verification_expires_at": expires_at if result["verification_token_created"] else None,
            "message": "If this address can sign up, a verification email will be sent.",
        }
        dev_delivery = _dev_token_payload(verification_token) if result["verification_token_created"] else None
        if dev_delivery:
            response["dev_delivery"] = dev_delivery
        return response

    @app.post("/auth/verify-email")
    async def verify_email(payload: EmailVerificationRequest) -> dict[str, Any]:
        user = store.verify_phase6_email_token(token_hash=_hash_phase6_auth_token(payload.token))
        if not user:
            raise HTTPException(status_code=400, detail="verification token is invalid or expired")
        _ensure_personal_workspace(user)
        return {
            "schema_version": "phase6.email_verification.v1",
            "status": "verified",
            "user": user,
        }

    @app.post("/auth/password-login", response_model=None)
    async def password_login(payload: PasswordLoginRequest, request: Request) -> Response:
        credential = store.get_phase6_password_credential(payload.email)
        if not credential or not _verify_phase6_password(payload.password, credential["password_hash"]):
            raise HTTPException(status_code=401, detail="invalid email or password")
        if credential.get("status") != "active" or not credential.get("email_verified_at"):
            raise HTTPException(status_code=403, detail="email verification is required before login")
        user = store.get_phase4_user(str(credential["user_id"]))
        if not user or user.get("status") != "active":
            raise HTTPException(status_code=403, detail="user is not active")
        _ensure_personal_workspace(user)
        return _issue_password_session_response(user, request)

    @app.post("/auth/password-reset/request", status_code=202)
    async def password_reset_request(payload: PasswordResetRequest) -> dict[str, Any]:
        reset_token = _new_phase6_auth_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        created = store.create_phase6_password_reset_token(
            email=payload.email,
            token_hash=_hash_phase6_auth_token(reset_token),
            expires_at=expires_at,
        )
        response = {
            "schema_version": "phase6.password_reset_requested.v1",
            "status": "accepted",
            "message": "If this account exists and is verified, a password reset email will be sent.",
        }
        dev_delivery = _dev_token_payload(reset_token) if created else None
        if dev_delivery:
            response["dev_delivery"] = dev_delivery
            response["reset_expires_at"] = expires_at
        return response

    @app.post("/auth/password-reset/confirm")
    async def password_reset_confirm(payload: PasswordResetConfirmRequest) -> dict[str, Any]:
        user = store.reset_phase6_password(
            token_hash=_hash_phase6_auth_token(payload.token),
            password_hash=_hash_phase6_password(payload.new_password),
        )
        if not user:
            raise HTTPException(status_code=400, detail="password reset token is invalid or expired")
        store.revoke_phase6_auth_sessions(user_id=user["id"], revoked_by_user_id=user["id"])
        return {
            "schema_version": "phase6.password_reset_confirmed.v1",
            "status": "password_reset",
            "sessions_revoked": True,
        }

    @app.get("/auth/oidc/login")
    async def oidc_login() -> RedirectResponse:
        if not _oidc_enabled(settings):
            raise HTTPException(status_code=503, detail="OIDC login is not configured")
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": settings.oidc_client_id,
                "redirect_uri": settings.oidc_redirect_uri,
                "scope": settings.oidc_scopes,
                "state": state,
                "nonce": nonce,
            }
        )
        response = RedirectResponse(f"{settings.oidc_authorization_endpoint}?{query}", status_code=302)
        response.set_cookie(
            "agronomy_oidc_state",
            _encode_oidc_state_cookie(state, nonce, settings=settings),
            max_age=600,
            httponly=True,
            secure=_cookie_secure(settings),
            samesite="lax",
        )
        return response

    @app.get("/auth/oidc/callback")
    async def oidc_callback(request: Request, code: str, state: str) -> RedirectResponse:
        if not _oidc_enabled(settings):
            raise HTTPException(status_code=503, detail="OIDC login is not configured")
        state_cookie = request.cookies.get("agronomy_oidc_state")
        if not state_cookie:
            raise HTTPException(status_code=401, detail="OIDC state cookie is missing")
        try:
            state_payload = _decode_oidc_state_cookie(state_cookie, settings=settings)
        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=401, detail=f"invalid OIDC state cookie: {exc}") from exc
        if not hmac.compare_digest(str(state_payload["state"]), state):
            raise HTTPException(status_code=401, detail="OIDC state mismatch")
        try:
            token_response = _exchange_oidc_code(code, settings=settings)
            claims = _decode_configured_jwt(str(token_response["id_token"]), settings=settings)
        except (json.JSONDecodeError, OSError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=401, detail=f"OIDC callback failed: {exc}") from exc
        token_nonce = claims.get("nonce")
        if token_nonce is None:
            raise HTTPException(status_code=401, detail="OIDC nonce is missing")
        if not hmac.compare_digest(str(token_nonce), str(state_payload["nonce"])):
            raise HTTPException(status_code=401, detail="OIDC nonce mismatch")
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie("agronomy_oidc_state", secure=_cookie_secure(settings), httponly=True, samesite="lax")
        session_id = str(uuid.uuid4())
        session_cookie = _encode_session_cookie(claims, settings=settings, session_id=session_id)
        session_payload = _decode_session_cookie(session_cookie, settings=settings)
        user = store.upsert_phase4_user(email=session_payload["email"], display_name=session_payload["display_name"])
        store.upsert_phase6_auth_session(
            session_id=session_payload["session_id"],
            user_id=user["id"],
            auth_subject=session_payload["sub"],
            email=session_payload["email"],
            display_name=session_payload["display_name"],
            issued_at=session_payload["issued_at"],
            expires_at=session_payload["expires_at"],
            user_agent=request.headers.get("user-agent"),
        )
        csrf_token = _csrf_token_from_session_cookie(session_cookie, settings=settings)
        response.set_cookie(
            "agronomy_session",
            session_cookie,
            max_age=8 * 60 * 60,
            httponly=True,
            secure=_cookie_secure(settings),
            samesite="lax",
        )
        response.set_cookie(
            "agronomy_csrf",
            csrf_token,
            max_age=8 * 60 * 60,
            httponly=False,
            secure=_cookie_secure(settings),
            samesite="lax",
        )
        return response

    @app.post("/auth/logout", response_model=None)
    async def auth_logout(request: Request) -> Response:
        logout_hint = None
        session_cookie = request.cookies.get("agronomy_session")
        if session_cookie:
            try:
                session_payload = _decode_session_cookie(session_cookie, settings=settings)
                logout_hint = str(session_payload.get("email") or "")
                persisted_session = store.get_phase6_auth_session(str(session_payload.get("session_id") or ""))
                if persisted_session and not persisted_session.get("revoked_at"):
                    store.revoke_phase6_auth_session(
                        session_id=persisted_session["id"],
                        revoked_by_user_id=persisted_session["user_id"],
                    )
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                logout_hint = None
        try:
            provider_logout_url = _oidc_logout_redirect_url(settings, logout_hint=logout_hint)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=f"OIDC logout is misconfigured: {exc}") from exc
        response: Response
        if provider_logout_url:
            response = RedirectResponse(provider_logout_url, status_code=302)
        else:
            response = JSONResponse({"status": "logged_out"})
        response.delete_cookie("agronomy_session", secure=_cookie_secure(settings), httponly=True, samesite="lax")
        response.delete_cookie("agronomy_oidc_state", secure=_cookie_secure(settings), httponly=True, samesite="lax")
        response.delete_cookie("agronomy_csrf", secure=_cookie_secure(settings), httponly=False, samesite="lax")
        return response

    @app.get("/auth/me")
    async def auth_me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return {
            "user": user,
            "account_consent": user.get("account_consent"),
            "organizations": store.list_phase4_organizations_for_user(user["id"]),
            "workspaces": store.list_phase4_workspaces_for_user(user["id"]),
        }

    @app.get("/account/consent")
    async def phase6_get_account_consent(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        consent = store.get_phase6_account_consent(user["id"])
        if consent is None:
            raise HTTPException(status_code=404, detail="account not found")
        return {"schema_version": "phase6.account_consent_response.v1", "consent": consent}

    @app.patch("/account/consent")
    async def phase6_update_account_consent(
        payload: AccountConsentUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if str(payload.confirm_email).strip().lower() != str(user["email"]).strip().lower():
            raise HTTPException(status_code=400, detail="email confirmation does not match current account")
        updates = payload.model_dump(exclude={"confirm_email"}, exclude_none=True)
        consent = store.update_phase6_account_consent(
            user_id=user["id"],
            actor_user_id=user["id"],
            payload=updates,
        )
        if consent is None:
            raise HTTPException(status_code=404, detail="account not found")
        return {"schema_version": "phase6.account_consent_response.v1", "consent": consent}

    @app.get("/account/export")
    async def phase6_account_data_export(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        orgs = store.list_phase4_organizations_for_user(user["id"])
        workspaces = store.list_phase4_workspaces_for_user(user["id"])
        workspace_exports: list[dict[str, Any]] = []
        for workspace in workspaces:
            workspace_id = workspace["id"]
            threads = [
                store.get_phase4_thread(thread["id"]) or thread
                for thread in store.list_phase4_threads(workspace_id)
            ]
            workspace_exports.append(
                {
                    "workspace": workspace,
                    "field_contexts": store.list_phase4_field_contexts(workspace_id),
                    "threads": threads,
                    "attachments": [
                        _phase6_account_export_attachment(attachment)
                        for attachment in store.list_phase4_attachments(workspace_id, include_deleted=True)
                    ],
                    "data_sources": store.list_phase4_data_sources(workspace_id),
                    "eval_candidates": store.list_phase4_eval_candidates(workspace_id),
                    "eval_runs": store.list_phase4_eval_runs(workspace_id),
                    "exports": [
                        _phase6_account_export_export(export)
                        for export in store.list_phase4_exports(workspace_id=workspace_id, limit=500)
                    ],
                }
            )
        return {
            "schema_version": "phase6.account_data_export.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "account_consent": user.get("account_consent"),
            "organizations": orgs,
            "workspaces": workspace_exports,
            "data_policy": {
                "scope": "records_accessible_to_current_user",
                "object_store_bytes_included": False,
                "object_store_uris_included": False,
                "export_file_uris_included": False,
                "embedding_vectors_included": False,
                "deleted_attachment_metadata_included": True,
            },
        }

    @app.delete("/account")
    async def phase6_delete_account(
        payload: AccountDeleteRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if payload.confirm_email != str(user["email"]).strip().lower():
            raise HTTPException(status_code=400, detail="email confirmation does not match current account")
        if not payload.export_acknowledged:
            raise HTTPException(status_code=400, detail="export acknowledgement is required before account deletion")
        deleted = store.delete_phase6_account(user_id=user["id"], deleted_by_user_id=user["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="account not found")
        return deleted

    @app.get("/auth/session")
    async def auth_session(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return {
            "user": user,
            "organizations": store.list_phase4_organizations_for_user(user["id"]),
            "workspaces": store.list_phase4_workspaces_for_user(user["id"]),
            "csrf_token": request.cookies.get("agronomy_csrf") if request.cookies.get("agronomy_session") else None,
        }

    @app.get("/auth/sessions")
    async def auth_sessions(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        current_session_id = None
        if request.cookies.get("agronomy_session"):
            try:
                current_session_id = _decode_session_cookie(str(request.cookies["agronomy_session"]), settings=settings)["session_id"]
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                current_session_id = None
        return _auth_sessions_payload(user, current_session_id)

    @app.post("/auth/sessions/revoke-all", response_model=None)
    async def revoke_auth_sessions(user: dict[str, Any] = Depends(current_user)) -> Response:
        revoked = store.revoke_phase6_auth_sessions(user_id=user["id"], revoked_by_user_id=user["id"])
        response = JSONResponse(
            {
                "schema_version": "phase6.auth_sessions_revoked.v1",
                "revoked_at": revoked["revoked_at"],
                "revoked_count": revoked["revoked_count"],
            }
        )
        response.delete_cookie("agronomy_session", secure=_cookie_secure(settings), httponly=True, samesite="lax")
        response.delete_cookie("agronomy_oidc_state", secure=_cookie_secure(settings), httponly=True, samesite="lax")
        response.delete_cookie("agronomy_csrf", secure=_cookie_secure(settings), httponly=False, samesite="lax")
        return response

    @app.get("/orgs")
    async def list_orgs(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        return store.list_phase4_organizations_for_user(user["id"])

    @app.post("/orgs", status_code=201)
    async def create_org(payload: OrganizationCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        slug = payload.slug or _slugify(payload.name)
        try:
            return store.create_phase4_organization(
                name=payload.name,
                slug=slug,
                plan=payload.plan,
                created_by_user_id=user["id"],
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"organization create failed: {exc}") from exc

    @app.get("/orgs/{organization_id}/memberships")
    async def list_memberships(organization_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        require_org_role(user, organization_id, ORG_ADMIN_ROLES)
        return store.list_phase4_memberships(organization_id)

    @app.post("/orgs/{organization_id}/memberships", status_code=201)
    async def upsert_membership(
        organization_id: str,
        payload: MembershipCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_org_role(user, organization_id, ORG_ADMIN_ROLES)
        member = store.upsert_phase4_user(email=payload.email, display_name=payload.display_name)
        return store.upsert_phase4_membership(
            organization_id=organization_id,
            user_id=member["id"],
            role=payload.role,
            actor_user_id=user["id"],
        )

    @app.post("/orgs/{organization_id}/invites", status_code=201)
    async def create_workspace_invite(
        organization_id: str,
        payload: WorkspaceInviteCreate,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_org_role(user, organization_id, ORG_ADMIN_ROLES)
        token, expires_at_epoch = _encode_workspace_invite(
            settings=settings,
            organization_id=organization_id,
            email=payload.email,
            role=payload.role,
            invited_by_user_id=user["id"],
            expires_in_hours=payload.expires_in_hours,
        )
        return {
            "schema_version": PHASE6_WORKSPACE_INVITE_SCHEMA_VERSION,
            "invite_token": token,
            "invite_url": f"{str(request.base_url).rstrip('/')}/invite?token={token}",
            "organization_id": organization_id,
            "email": payload.email,
            "role": payload.role,
            "expires_at": _iso_from_epoch(expires_at_epoch),
        }

    @app.post("/orgs/invites/accept")
    async def accept_workspace_invite(
        payload: WorkspaceInviteAccept,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        invite = _decode_workspace_invite(payload.token, settings=settings)
        invite_email = str(invite["email"]).strip().lower()
        if invite_email != str(user["email"]).strip().lower():
            raise HTTPException(status_code=403, detail="invite is for a different email")
        organization_id = str(invite["organization_id"])
        organization = store.get_phase4_organization(organization_id)
        if not organization:
            raise HTTPException(status_code=404, detail="organization not found")
        role = str(invite["role"])
        if role not in {"owner", "admin", "researcher", "adviser", "viewer"}:
            raise HTTPException(status_code=400, detail="invite token role is invalid")
        membership = store.upsert_phase4_membership(
            organization_id=organization_id,
            user_id=user["id"],
            role=role,
            actor_user_id=str(invite.get("invited_by_user_id") or user["id"]),
        )
        organization_with_role = dict(organization)
        organization_with_role["role"] = membership["role"]
        return {
            "schema_version": PHASE6_WORKSPACE_INVITE_SCHEMA_VERSION,
            "accepted": True,
            "organization": organization_with_role,
            "membership": membership,
            "expires_at": _iso_from_epoch(int(invite["exp"])),
        }

    @app.get("/workspaces")
    async def list_workspaces(
        organization_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        if organization_id and not store.phase4_user_can_access_org(user["id"], organization_id):
            raise HTTPException(status_code=403, detail="organization access denied")
        return store.list_phase4_workspaces_for_user(user["id"], organization_id=organization_id)

    @app.post("/workspaces", status_code=201)
    async def create_workspace(payload: WorkspaceCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        organization_id = str(payload.organization_id)
        require_org_role(user, organization_id, ORG_ADMIN_ROLES)
        return store.create_phase4_workspace(
            organization_id=organization_id,
            name=payload.name,
            created_by_user_id=user["id"],
            settings=payload.settings,
        )

    @app.delete("/workspaces/{workspace_id}")
    async def delete_workspace(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, workspace_id, ORG_ADMIN_ROLES)
        deleted = store.delete_phase4_workspace(workspace_id=workspace["id"], deleted_by_user_id=user["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="workspace not found")
        return deleted

    @app.get("/quotas")
    async def phase4_workspace_quotas(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_for_user(user, workspace_id)
        return workspace_quota_report(workspace)

    @app.get("/field-contexts")
    async def list_field_contexts(
        workspace_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_field_contexts(workspace["id"])

    @app.post("/field-contexts", status_code=201)
    async def create_field_context(payload: FieldContextCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), WORKSPACE_WRITE_ROLES)
        return store.create_phase4_field_context(
            workspace=workspace,
            created_by_user_id=user["id"],
            payload=payload.model_dump(mode="json"),
        )

    @app.get("/field-contexts/{field_context_id}")
    async def get_field_context(field_context_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_for_user(user, field_context["workspace_id"])
        return field_context

    @app.patch("/field-contexts/{field_context_id}")
    async def update_field_context(
        field_context_id: str,
        payload: FieldContextUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_role(user, field_context["workspace_id"], WORKSPACE_WRITE_ROLES)
        updated = store.update_phase4_field_context(
            field_context_id=field_context_id,
            actor_user_id=user["id"],
            payload=payload.model_dump(mode="json", exclude_unset=True),
        )
        return updated or {}

    @app.delete("/field-contexts/{field_context_id}")
    async def delete_field_context(field_context_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_role(user, field_context["workspace_id"], WORKSPACE_WRITE_ROLES)
        deleted = store.delete_phase4_field_context(field_context_id=field_context_id, deleted_by_user_id=user["id"])
        return deleted or {}

    @app.get("/field-contexts/{field_context_id}/events")
    async def list_field_context_events(
        field_context_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_for_user(user, field_context["workspace_id"])
        events = store.list_phase4_field_events(field_context_id)
        return {
            "schema_version": "open_agronomy_agent.field_events.v1",
            "field_context_id": field_context_id,
            "event_count": len(events),
            "events": events,
            "chain": store.verify_phase4_field_event_chain(field_context_id),
            "boundary": (
                "Field events are append-only. Record mistakes as correction events that point to the prior event."
            ),
        }

    @app.post("/field-contexts/{field_context_id}/events", status_code=201)
    async def append_field_context_event(
        field_context_id: str,
        payload: FieldEventCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_role(user, field_context["workspace_id"], WORKSPACE_WRITE_ROLES)
        try:
            event = store.append_phase4_field_event(
                field_context=field_context,
                recorded_by_user_id=user["id"],
                payload=payload.model_dump(mode="json", exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema_version": "open_agronomy_agent.field_event_appended.v1",
            "event": event,
            "chain": store.verify_phase4_field_event_chain(field_context_id),
        }

    @app.get("/field-contexts/{field_context_id}/events/sync")
    async def export_field_context_event_sync(
        field_context_id: str,
        after_sha256: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_for_user(user, field_context["workspace_id"])
        try:
            return store.export_phase4_field_event_sync(
                field_context_id,
                after_sha256=after_sha256,
            )
        except FieldEventSyncError as exc:
            raise _field_event_sync_http_error(exc) from exc

    @app.post("/field-contexts/{field_context_id}/events/sync")
    async def import_field_context_event_sync(
        field_context_id: str,
        payload: FieldEventSyncRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        field_context = store.get_phase4_field_context(field_context_id)
        if not field_context:
            raise HTTPException(status_code=404, detail="field context not found")
        require_workspace_role(user, field_context["workspace_id"], WORKSPACE_WRITE_ROLES)
        try:
            return store.import_phase4_field_event_sync(
                field_context=field_context,
                syncing_user_id=user["id"],
                source_device_id=payload.source_device_id,
                base_head_sha256=payload.base_head_sha256,
                events=[
                    event.model_dump(mode="json", exclude_none=False)
                    for event in payload.events
                ],
            )
        except FieldEventSyncError as exc:
            raise _field_event_sync_http_error(exc) from exc

    @app.post("/geo/priors")
    async def phase4_geo_priors(payload: GeoPriorsQuery, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_for_user(user, str(payload.workspace_id))
        if payload.field_context_id:
            require_field_context_for_workspace(workspace, str(payload.field_context_id))
        priors = _geo_priors_for_location(payload.location_text)
        return {
            "workspace_id": workspace["id"],
            "field_context_id": str(payload.field_context_id) if payload.field_context_id else None,
            **priors,
        }

    @app.get("/threads")
    async def list_threads(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_threads(workspace["id"])

    @app.post("/threads", status_code=201)
    async def create_thread(payload: ThreadCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        runtime_mode(payload.mode)
        workspace = require_workspace_role(user, str(payload.workspace_id), WORKSPACE_WRITE_ROLES)
        enforce_workspace_quota(workspace, "max_threads")
        field_context_id = str(payload.field_context_id) if payload.field_context_id else None
        if field_context_id:
            require_field_context_for_workspace(workspace, field_context_id)
        return store.create_phase4_thread(
            workspace=workspace,
            created_by_user_id=user["id"],
            title=payload.title,
            mode=payload.mode,
            trace_capture_level=payload.trace_capture_level,
            field_context_id=field_context_id,
            model_profile_id=runtime_model_id(payload.model_profile_id, mode=payload.mode),
            rag_config_id=runtime_rag_config(payload.rag_config_id),
            training_eligible=payload.training_eligible,
        )

    @app.get("/threads/{thread_id}")
    async def get_thread(thread_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return require_thread_for_user(user, thread_id)

    @app.patch("/threads/{thread_id}")
    async def update_thread_consent(
        thread_id: str,
        payload: ThreadConsentUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        thread = require_thread_for_user(user, thread_id)
        require_workspace_role(user, thread["workspace_id"], WORKSPACE_WRITE_ROLES)
        updated = store.update_phase4_thread_consent(
            thread_id=thread_id,
            actor_user_id=user["id"],
            trace_capture_level=payload.trace_capture_level,
            training_eligible=payload.training_eligible,
            redaction_status=payload.redaction_status,
        )
        return updated or {}

    @app.delete("/threads/{thread_id}")
    async def delete_thread(thread_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        thread = require_thread_for_user(user, thread_id)
        require_workspace_role(user, thread["workspace_id"], WORKSPACE_WRITE_ROLES)
        deleted = store.delete_phase4_thread(thread_id=thread_id, deleted_by_user_id=user["id"])
        return deleted or {}

    @app.get("/threads/{thread_id}/trace")
    async def get_thread_trace(thread_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        require_thread_for_user(user, thread_id)
        return phase4_trace_payload(thread_id)

    @app.post("/chat/stream")
    async def phase4_chat_stream(payload: ChatRequest, user: dict[str, Any] = Depends(current_user)) -> StreamingResponse:
        runtime_mode(payload.mode)
        profiler = TraceProfiler()
        with profiler.span("thread.load", input_size=len(payload.message)):
            workspace = require_workspace_role(user, str(payload.workspace_id), WORKSPACE_WRITE_ROLES)
            enforce_workspace_quota(workspace, "max_messages", increment=2)
            field_context_id = str(payload.field_context_id) if payload.field_context_id else None
            if field_context_id:
                require_field_context_for_workspace(workspace, field_context_id)
            attachments = [require_attachment_for_workspace(workspace, str(item)) for item in payload.attachment_ids]
            if payload.thread_id:
                thread = require_thread_for_user(user, str(payload.thread_id))
            else:
                enforce_workspace_quota(workspace, "max_threads")
                thread = store.create_phase4_thread(
                    workspace=workspace,
                    created_by_user_id=user["id"],
                    title=payload.message[:80],
                    mode=payload.mode,
                    trace_capture_level=payload.trace_capture_level,
                    field_context_id=field_context_id,
                    model_profile_id=runtime_model_id(payload.model_profile_id, mode=payload.mode),
                    rag_config_id=runtime_rag_config(payload.rag_config_id),
                    training_eligible=payload.research_consent,
                )
        profiler.set_thread_id(thread["id"])
        if thread["workspace_id"] != workspace["id"]:
            raise HTTPException(status_code=403, detail="thread is outside workspace")

        with profiler.span("field_context.load", metadata={"field_context_id": field_context_id}):
            effective_field_context_id = field_context_id or thread.get("field_context_id")
            active_field_context = store.get_phase4_field_context(str(effective_field_context_id)) if effective_field_context_id else None

        with profiler.span("thread.persist_trace", metadata={"phase": "user_message"}):
            metadata, legacy_session_id = ensure_legacy_session(thread)
            user_message = store.create_phase4_message(
                thread=thread,
                actor="user",
                content=payload.message,
                metadata={
                    "attachment_ids": [str(item) for item in payload.attachment_ids],
                    "field_context_id": field_context_id or thread.get("field_context_id"),
                },
            )
            store.append_phase4_trace_event(
                thread=thread,
                event_type="user_message",
                actor="user",
                message_id=user_message["id"],
                payload={"message_id": user_message["id"], "text_len": len(payload.message)},
            )
            for attachment in attachments:
                store.append_phase4_trace_event(
                    thread=thread,
                    event_type="attachment_event",
                    actor="user",
                    message_id=user_message["id"],
                    payload={
                        "attachment_id": attachment["id"],
                        "filename": attachment["filename"],
                        "parse_status": attachment["parse_status"],
                        "chunk_count": attachment["metadata"].get("chunk_count", 0),
                        "private_rag_scope": "workspace",
                    },
                    source_hash=attachment["sha256"],
                )

        answer_text: str
        assistant_message: dict[str, Any]
        trace: dict[str, Any] = {}
        system_state: dict[str, Any] = {}
        selected_rag_config = runtime_rag_config(
            payload.rag_config_id or thread.get("rag_config_id")
        )
        selected_model_id = runtime_model_id(
            payload.model_profile_id or thread.get("model_profile_id"),
            mode=payload.mode,
        )
        if payload.mode == "image_rag_research":
            image_field_context = store.get_phase4_field_context(field_context_id) if field_context_id else None
            image_crop = (image_field_context or {}).get("crop_current")
            image_region = (image_field_context or {}).get("region_text")
            image_search = _image_embedding_search(
                query_attachments=attachments,
                candidate_embeddings=store.list_phase4_image_embeddings(workspace["id"]),
                crop=image_crop,
                region=image_region,
            )
            image_payload = _image_quality_payload(
                attachments=attachments,
                question=payload.message,
                crop=image_crop,
                region=image_region,
                observation_adapter=image_observation_adapter,
                similar_examples=image_search["examples"],
                image_retrieval_eval=image_search["eval_summary"],
            )
            answer_text = (
                "Research preview: image-RAG is limited to visual triage and similar-example retrieval. "
                "Upload processing is not enabled in this local foundation, so no diagnosis or treatment recommendation is made."
            )
            assistant_message = store.create_phase4_message(
                thread=thread,
                actor="assistant",
                content=answer_text,
                metadata={"research_preview": True},
            )
            store.append_phase4_trace_event(
                thread=thread,
                event_type="image_observation",
                actor="system",
                message_id=assistant_message["id"],
                payload=image_payload,
            )
        else:
            workspace_retrieved_docs = sorted(
                [
                    *_attachment_chunks_as_retrieved_docs(
                        store=store,
                        attachments=attachments,
                        query=payload.message,
                    ),
                    *_data_source_chunks_as_retrieved_docs(
                        store=store,
                        workspace_id=workspace["id"],
                        query=payload.message,
                    ),
                ],
                key=lambda item: (-float(item.get("score") or 0.0), str(item.get("title") or "")),
            )
            workspace_retrieved_docs = [
                doc for doc in workspace_retrieved_docs if float(doc.get("score") or 0.0) >= 0.05
            ][:6]
            for rank, doc in enumerate(workspace_retrieved_docs, start=1):
                doc["rank"] = rank
            result = run_turn(
                store=store,
                settings=settings,
                session_id=legacy_session_id,
                message=payload.message,
                mode=payload.mode,
                model_id=selected_model_id,
                rag_config=selected_rag_config,
                max_tokens=payload.max_tokens,
                trace_options={
                    "store_prompt_messages": payload.trace_capture_level == "research_opt_in",
                    "store_retrieved_text": payload.trace_capture_level == "research_opt_in",
                    "redaction_mode": "none",
                },
                session_context={
                    "field_context_id": str(effective_field_context_id) if effective_field_context_id else None,
                    "field_record_updated_at": (active_field_context or {}).get("updated_at"),
                    "field_access_authorized": bool(active_field_context),
                    "field_access_workspace_id": workspace["id"] if active_field_context else None,
                    "field_context": active_field_context,
                    "workspace_retrieved_docs": workspace_retrieved_docs,
                },
                profiler=profiler,
            )
            turn = result["turn"]
            answer_text = turn["answer"]
            trace = turn.get("trace", {}) or {}
            system_state = turn.get("system_state", {}) or {}
            if active_field_context and isinstance(trace, dict):
                trace["field_context_snapshot"] = minimized_field_context_snapshot(active_field_context)
            route = trace.get("route") or {}
            if route:
                store.append_phase4_trace_event(thread=thread, event_type="route_result", actor="system", payload=route)
                store.update_phase4_thread_metadata(
                    thread["id"],
                    metadata={**metadata, "legacy_session_id": legacy_session_id, "latest_legacy_turn_id": result["turn_id"]},
                    task_family=route.get("question_type"),
                    risk_level=route.get("risk_level") or "unknown",
                )
            docs = trace.get("retrieved_docs", [])
            workspace_doc_count = int((trace.get("metadata") or {}).get("workspace_doc_count") or 0)
            store.append_phase4_trace_event(
                thread=thread,
                event_type="retrieval_result",
                actor="system",
                payload={
                    "retrieved_docs": docs,
                    "doc_count": len(docs),
                    "private_doc_count": workspace_doc_count,
                    "source_diversity": len({doc.get("source") for doc in docs if isinstance(doc, dict)}),
                },
            )
            kg_hits = trace.get("graph_hits", [])
            if kg_hits:
                store.append_phase4_trace_event(thread=thread, event_type="kg_result", actor="system", payload={"graph_hits": kg_hits})
            for tool in trace.get("tool_invocations", []):
                store.append_phase4_trace_event(thread=thread, event_type="tool_result", actor="system", payload=tool)
            store.append_phase4_trace_event(
                thread=thread,
                event_type="answer_plan",
                actor="system",
                payload={"coverage_checklist": trace.get("coverage_checklist", [])},
            )
            structured = render_structured_answer(answer_text, trace=trace)
            answer_text = structured.answer
            trace["structured_answer"] = structured.as_record()
            structured_answer = trace["structured_answer"]
            assistant_message = store.create_phase4_message(
                thread=thread,
                actor="assistant",
                content=answer_text,
                metadata={
                    "legacy_turn_id": result["turn_id"],
                    "system_state": system_state,
                    "structured_answer": structured_answer,
                },
            )
            store.append_phase4_trace_event(
                thread=thread,
                event_type="model_call",
                actor="system",
                message_id=assistant_message["id"],
                payload=system_state,
                prompt_hash=_hash_payload(trace.get("prompt_messages", [])),
                output_hash=_hash_payload(answer_text),
                elapsed_ms=system_state.get("latency_ms"),
            )
        refreshed_for_trace = store.get_phase4_thread(thread["id"]) or thread
        with profiler.span("thread.persist_trace", metadata={"phase": "assistant_answer"}):
            store.append_phase4_trace_event(
                thread=refreshed_for_trace,
                event_type="assistant_answer",
                actor="assistant",
                message_id=assistant_message["id"],
                payload={"message_id": assistant_message["id"], "answer": answer_text},
                output_hash=_hash_payload(answer_text),
            )
        profiler.add_observed("http.request", start_ns=profiler.started_ns, metadata={"path": "/chat/stream", "mode": payload.mode})
        profiler.add_skipped("ui.stream_response", reason="streaming_after_metric_flush")
        phase5_metrics = persist_phase5_turn_observability(
            profiler=profiler,
            thread=refreshed_for_trace,
            user=user,
            assistant_message=assistant_message,
            answer_text=answer_text,
            trace=trace,
            system_state=system_state,
            model_id=selected_model_id,
            rag_config_id=selected_rag_config,
            max_tokens=payload.max_tokens,
        )

        async def phase4_events() -> Any:
            refreshed_thread = store.get_phase4_thread(thread["id"]) or thread
            route_payload = (trace.get("route") or {}) if trace else {}
            if route_payload:
                yield "event: route.completed\n"
                yield f"data: {json.dumps(route_payload)}\n\n"
            yield "event: retrieval.completed\n"
            yield f"data: {json.dumps({'doc_count': len(trace.get('retrieved_docs', [])) if trace else 0})}\n\n"
            for chunk in _chunk_text_for_stream(answer_text, chunk_size=64):
                yield "event: model.delta\n"
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "event: model.completed\n"
            yield f"data: {json.dumps({'thread_id': refreshed_thread['id'], 'message_id': assistant_message['id']})}\n\n"
            structured_payload = trace.get("structured_answer", {}) if isinstance(trace, dict) else {}
            if structured_payload:
                yield "event: answer.structured\n"
                yield f"data: {json.dumps(structured_payload)}\n\n"
            yield "event: trace.persisted\n"
            yield f"data: {json.dumps({'thread_id': refreshed_thread['id'], 'event_count': len(store.list_phase4_trace_events(refreshed_thread['id'])), 'phase5_trace_id': phase5_metrics['trace_id']})}\n\n"

        return StreamingResponse(phase4_events(), media_type="text/event-stream")

    @app.post("/route")
    async def phase4_route(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace_id = payload.get("workspace_id")
        if workspace_id:
            require_workspace_for_user(user, str(workspace_id))
        message = str(payload.get("message", "")).strip() or str(payload.get("question", "")).strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        return {"route": route_query(message)}

    @app.post("/retrieve")
    async def phase4_retrieve(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace_id = payload.get("workspace_id")
        if workspace_id:
            require_workspace_for_user(user, str(workspace_id))
        return await context_retrieve(payload)

    @app.post("/tools/{tool_name}/run")
    async def phase4_run_tool(tool_name: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace_id = payload.get("workspace_id")
        if workspace_id:
            require_workspace_for_user(user, str(workspace_id))
        return run_local_tool(tool_name, payload, network_mode=settings.network_mode)

    @app.get("/attachments")
    async def phase4_list_attachments(
        workspace_id: str,
        include_deleted: bool = False,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_attachments(workspace["id"], include_deleted=include_deleted)

    @app.post(
        "/attachments",
        status_code=201,
        openapi_extra={
            "requestBody": {
                "content": {
                    "application/json": {"schema": AttachmentCreate.model_json_schema()},
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["workspace_id", "file"],
                            "properties": {
                                "workspace_id": {"type": "string", "format": "uuid"},
                                "thread_id": {"type": "string", "format": "uuid"},
                                "message_id": {"type": "string", "format": "uuid"},
                                "file": {"type": "string", "format": "binary"},
                                "filename": {"type": "string"},
                                "modality": {"type": "string", "enum": ["text", "image", "multimodal"]},
                                "sensitivity": {"type": "string", "enum": ["low", "medium", "high"]},
                                "retention_policy": {
                                    "type": "string",
                                    "enum": ["default", "short", "extended", "delete_on_request"],
                                },
                                "crop": {"type": "string"},
                                "region": {"type": "string"},
                            },
                        }
                    },
                }
            }
        },
    )
    async def phase4_create_attachment(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        payload, raw_content = await _attachment_payload_from_request(request)
        workspace = require_workspace_role(user, str(payload.workspace_id), WORKSPACE_WRITE_ROLES)
        thread = None
        if payload.thread_id:
            thread = require_thread_for_user(user, str(payload.thread_id))
            if thread["workspace_id"] != workspace["id"]:
                raise HTTPException(status_code=403, detail="thread is outside workspace")
        content_bytes, derived_metadata, extracted_text = _attachment_content_and_metadata(
            payload,
            scanner=attachment_scanner,
            raw_content=raw_content,
        )
        enforce_workspace_quota(workspace, "max_attachments")
        enforce_workspace_quota(workspace, "max_attachment_bytes", increment=len(content_bytes))
        digest = hashlib.sha256(content_bytes).hexdigest()
        attachment_id = str(uuid.uuid4())
        stored_object = object_store.put_bytes(
            f"phase4/attachments/{workspace['id']}/{attachment_id}-{_safe_filename(payload.filename)}",
            content_bytes,
        )
        attachment_payload = payload.model_dump(mode="json")
        attachment_payload["id"] = attachment_id
        if extracted_text:
            attachment_payload["text_content"] = extracted_text
        attachment_payload["metadata"] = derived_metadata
        attachment = store.create_phase4_attachment(
            workspace=workspace,
            created_by_user_id=user["id"],
            payload=attachment_payload,
            storage_uri=stored_object.uri,
            size_bytes=stored_object.size_bytes,
            sha256=digest,
        )
        if thread:
            store.append_phase4_trace_event(
                thread=thread,
                event_type="attachment_event",
                actor="user",
                payload={
                    "attachment_id": attachment["id"],
                    "filename": attachment["filename"],
                    "parse_status": attachment["parse_status"],
                    "retention_policy": attachment["metadata"].get("retention_policy"),
                    "modality": attachment["modality"],
                    "image": attachment["metadata"].get("image"),
                    "private_rag_scope": "workspace",
                },
                source_hash=digest,
            )
        if settings.job_queue_backend == "redis":
            try:
                embedding_job = store.create_phase4_embedding_job(
                    attachment=attachment,
                    created_by_user_id=user["id"],
                    queue_name=settings.embedding_queue_name,
                )
                enqueue = job_queue.enqueue_embedding_job(embedding_job["id"])
            except JobQueueUnavailable as exc:
                if not settings.job_queue_fail_open:
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "job queue unavailable",
                            "backend": job_queue.backend,
                            "fail_open": False,
                            "reason": str(exc),
                            "attachment_id": attachment["id"],
                        },
                    ) from exc
                attachment["embedding_job"] = {"enqueued": False, "fail_open": True, "reason": str(exc)}
            else:
                attachment["embedding_job"] = {**embedding_job, "queue_enqueue": enqueue}
        return attachment

    @app.delete("/attachments/{attachment_id}")
    async def phase4_delete_attachment(attachment_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        attachment = store.get_phase4_attachment(attachment_id)
        if not attachment:
            raise HTTPException(status_code=404, detail="attachment not found")
        require_workspace_role(user, attachment["workspace_id"], WORKSPACE_WRITE_ROLES)
        deleted = store.delete_phase4_attachment(attachment_id=attachment_id, deleted_by_user_id=user["id"])
        if deleted:
            object_store.delete_uri(deleted["storage_uri"])
            if deleted.get("thread_id"):
                thread = store.get_phase4_thread(deleted["thread_id"])
                if thread:
                    store.append_phase4_trace_event(
                        thread=thread,
                        event_type="attachment_event",
                        actor="user",
                        payload={
                            "attachment_id": attachment_id,
                            "deleted": True,
                            "derived_chunks_tombstoned": True,
                            "derived_embeddings_tombstoned": True,
                        },
                    )
        return deleted or {}

    @app.post("/messages/{message_id}/feedback", status_code=201)
    async def phase4_message_feedback(
        message_id: str,
        payload: HostedFeedbackCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        message = store.get_phase4_message(message_id)
        if not message:
            raise HTTPException(status_code=404, detail="message not found")
        thread = require_thread_for_user(user, message["thread_id"])
        require_workspace_role(user, thread["workspace_id"], WORKSPACE_WRITE_ROLES)
        feedback = store.create_phase4_feedback(
            thread=thread,
            message_id=message_id,
            created_by_user_id=user["id"],
            rating=payload.rating,
            failure_tags=payload.failure_tags,
            human_correction=payload.human_correction,
            ideal_answer=payload.ideal_answer,
            training_consent=payload.training_consent,
        )
        phase5_metrics = store.update_phase5_turn_feedback(
            turn_id=message_id,
            user_feedback_score=_phase5_feedback_score(payload.rating),
            human_review_status="feedback_received",
        )
        if phase5_metrics:
            feedback_profiler = TraceProfiler(trace_id=phase5_metrics["trace_id"])
            feedback_profiler.set_thread_id(thread["id"])
            feedback_profiler.set_turn_id(message_id)
            with feedback_profiler.span(
                "feedback.capture",
                metadata={
                    "feedback_id": feedback["id"],
                    "rating": payload.rating,
                    "failure_tag_count": len(payload.failure_tags),
                    "training_consent": payload.training_consent,
                },
            ):
                pass
            store.create_phase5_trace_spans(feedback_profiler.span_records())
        if payload.failure_tags or payload.training_consent:
            store.create_phase4_eval_candidate(
                thread=thread,
                created_by_user_id=user["id"],
                payload={
                    "message_id": message_id,
                    "candidate_type": "eval_row",
                    "target_component": "eval",
                    "question": next((m["content"] for m in reversed(thread.get("messages", [])) if m["actor"] == "user"), ""),
                    "answer": message["content"],
                    "feedback": feedback,
                },
            )
        return feedback

    @app.get("/eval-candidates")
    async def phase4_list_eval_candidates(
        workspace_id: str,
        review_status: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_eval_candidates(workspace["id"], review_status=review_status)

    @app.post("/eval-candidates/{candidate_id}/review")
    async def phase4_review_eval_candidate(
        candidate_id: str,
        payload: EvalCandidateReviewRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        candidate = require_eval_candidate_for_user(user, candidate_id)
        require_workspace_role(user, candidate["workspace_id"], RESEARCH_REVIEW_ROLES)
        updated = store.update_phase4_eval_candidate_status(
            candidate_id=candidate_id,
            reviewed_by_user_id=user["id"],
            review_status=payload.review_status,
        )
        return updated or {}

    @app.get("/eval-runs")
    async def phase4_list_eval_runs(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_eval_runs(workspace["id"])

    @app.get("/eval-runs/{run_id}")
    async def phase4_get_eval_run(run_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        run = store.get_phase4_eval_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="eval run not found")
        require_workspace_for_user(user, run["workspace_id"])
        return run

    @app.post("/eval-runs", status_code=202)
    async def phase4_create_eval_run(payload: EvalRunCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), RESEARCH_REVIEW_ROLES)
        enforce_workspace_quota(workspace, "max_eval_runs")
        candidates: list[dict[str, Any]] = []
        for status in payload.include_statuses:
            candidates.extend(store.list_phase4_eval_candidates(workspace["id"], review_status=status))
        candidates = sorted({candidate["id"]: candidate for candidate in candidates}.values(), key=lambda item: item["created_at"])
        if not candidates:
            raise HTTPException(status_code=400, detail="eval run requires at least one reviewed candidate")
        candidate_ids = [candidate["id"] for candidate in candidates]
        eval_corpus_audit_id = _corpus_audit(settings, store)
        if settings.job_queue_backend == "redis":
            run = store.create_phase4_eval_run(
                workspace=workspace,
                created_by_user_id=user["id"],
                name=payload.name,
                candidate_ids=candidate_ids,
                metadata={
                    "include_statuses": payload.include_statuses,
                    "queue_backend": job_queue.backend,
                    "queue_name": settings.eval_queue_name,
                    "corpus_audit_id": eval_corpus_audit_id,
                },
                status="queued",
            )
            try:
                enqueue = job_queue.enqueue_eval_run(run["id"])
            except JobQueueUnavailable as exc:
                store.update_phase4_eval_run(
                    run_id=run["id"],
                    status="failed",
                    metadata={"queue_enqueue_error": str(exc), "queue_backend": job_queue.backend},
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                if not settings.job_queue_fail_open:
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "job queue unavailable",
                            "backend": job_queue.backend,
                            "fail_open": False,
                            "reason": str(exc),
                            "run_id": run["id"],
                        },
                    ) from exc
                enqueue = {"backend": job_queue.backend, "enqueued": False, "fail_open": True, "reason": str(exc)}
            return {**(store.get_phase4_eval_run(run["id"]) or run), "queue_enqueue": enqueue}

        metrics = _eval_run_metrics(candidates)
        gates = _eval_run_gates(metrics)
        run = store.create_phase4_eval_run(
            workspace=workspace,
            created_by_user_id=user["id"],
            name=payload.name,
            candidate_ids=candidate_ids,
            metrics=metrics,
            gates=gates,
            metadata={"include_statuses": payload.include_statuses, "queue_backend": job_queue.backend, "corpus_audit_id": eval_corpus_audit_id},
        )
        return run

    @app.get("/change-proposals")
    async def phase4_list_change_proposals(
        workspace_id: str,
        review_status: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_change_proposals(workspace["id"], review_status=review_status)

    @app.post("/change-proposals", status_code=201)
    async def phase4_create_change_proposal(
        payload: ChangeProposalCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), RESEARCH_REVIEW_ROLES)
        eval_run = None
        if payload.linked_eval_run_id:
            eval_run = store.get_phase4_eval_run(str(payload.linked_eval_run_id))
            if not eval_run or eval_run["workspace_id"] != workspace["id"]:
                raise HTTPException(status_code=404, detail="linked eval run not found")
        if payload.linked_reflection_id:
            reflection = store.get_phase4_reflection(str(payload.linked_reflection_id))
            if not reflection or reflection.get("workspace_id") != workspace["id"]:
                raise HTTPException(status_code=404, detail="linked reflection not found")
        return store.create_phase4_change_proposal(
            workspace=workspace,
            created_by_user_id=user["id"],
            payload=payload.model_dump(mode="json"),
            gates=_change_proposal_gates(eval_run),
        )

    @app.post("/change-proposals/{proposal_id}/review")
    async def phase4_review_change_proposal(
        proposal_id: str,
        payload: ChangeProposalReviewRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        proposal = store.get_phase4_change_proposal(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="change proposal not found")
        require_workspace_role(user, proposal["workspace_id"], RESEARCH_REVIEW_ROLES)
        if payload.review_status == "approved_for_rollout" and not proposal.get("gates", {}).get("promotion_allowed"):
            raise HTTPException(status_code=400, detail="rollout approval requires a linked eval run with passing promotion gates")
        updated = store.update_phase4_change_proposal_status(
            proposal_id=proposal_id,
            reviewed_by_user_id=user["id"],
            review_status=payload.review_status,
            notes=payload.notes,
        )
        return updated or {}

    @app.post("/threads/{thread_id}/reflections", status_code=201)
    async def phase4_create_reflection(
        thread_id: str,
        payload: ReflectionCandidateCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if str(payload.thread_id) != thread_id:
            raise HTTPException(status_code=400, detail="thread_id mismatch")
        thread = require_thread_for_user(user, thread_id)
        require_workspace_role(user, thread["workspace_id"], WORKSPACE_WRITE_ROLES)
        return store.create_phase4_reflection_candidate(
            thread=thread,
            created_by_user_id=user["id"],
            target_component=payload.target_component,
            lesson=payload.lesson,
            candidate_rule=payload.candidate_rule,
            evidence=payload.evidence,
        )

    @app.post("/reflections/{reflection_id}/review")
    async def phase4_review_reflection(
        reflection_id: str,
        payload: ReflectionReviewRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        reflection = store.get_phase4_reflection(reflection_id)
        if not reflection:
            raise HTTPException(status_code=404, detail="reflection not found")
        if reflection.get("thread_id"):
            thread = require_thread_for_user(user, reflection["thread_id"])
            require_workspace_role(user, thread["workspace_id"], RESEARCH_REVIEW_ROLES)
        elif reflection.get("workspace_id"):
            require_workspace_role(user, reflection["workspace_id"], RESEARCH_REVIEW_ROLES)
        updated = store.update_phase4_reflection_status(
            reflection_id=reflection_id,
            reviewed_by_user_id=user["id"],
            status=payload.status,
        )
        return updated or {}

    @app.get("/data-sources")
    async def phase4_list_data_sources(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_data_sources(workspace["id"])

    @app.get("/data-sources/{data_source_id}")
    async def phase4_get_data_source(data_source_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        data_source = store.get_phase4_data_source(data_source_id)
        if not data_source:
            raise HTTPException(status_code=404, detail="data source not found")
        require_workspace_for_user(user, data_source["workspace_id"])
        return data_source

    @app.get("/corpus-health")
    async def phase4_corpus_health(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_for_user(user, workspace_id)
        return _corpus_health_summary(
            workspace=workspace,
            data_sources=store.list_phase4_data_sources(workspace["id"]),
            ingest_jobs=store.list_phase4_ingest_jobs(workspace["id"]),
            chunk_counts=store.count_phase4_document_chunks_by_source(workspace["id"]),
        )

    @app.get("/audit-events")
    async def phase4_list_audit_events(
        workspace_id: str,
        event_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_audit_events(workspace_id=workspace["id"], event_type=event_type, limit=limit)

    @app.post("/data-sources", status_code=201)
    async def phase4_create_data_source(payload: HostedDataSourceCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), ORG_ADMIN_ROLES)
        enforce_workspace_quota(workspace, "max_data_sources")
        try:
            return store.create_phase4_data_source(workspace=workspace, payload=payload.model_dump(mode="json"))
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"data source create failed: {exc}") from exc

    @app.patch("/data-sources/{data_source_id}")
    async def phase4_update_data_source(
        data_source_id: str,
        payload: HostedDataSourceUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        data_source = store.get_phase4_data_source(data_source_id)
        if not data_source:
            raise HTTPException(status_code=404, detail="data source not found")
        require_workspace_role(user, data_source["workspace_id"], ORG_ADMIN_ROLES)
        updated = store.update_phase4_data_source(
            data_source_id=data_source_id,
            actor_user_id=user["id"],
            payload=payload.model_dump(mode="json", exclude_unset=True),
        )
        return updated or {}

    @app.delete("/data-sources/{data_source_id}")
    async def phase4_delete_data_source(data_source_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        data_source = store.get_phase4_data_source(data_source_id)
        if not data_source:
            raise HTTPException(status_code=404, detail="data source not found")
        require_workspace_role(user, data_source["workspace_id"], ORG_ADMIN_ROLES)
        deleted = store.delete_phase4_data_source(data_source_id=data_source_id, deleted_by_user_id=user["id"])
        return deleted or {}

    @app.post("/data-sources/{data_source_id}/ingest", status_code=202)
    async def phase4_ingest_data_source(data_source_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        data_source = store.get_phase4_data_source(data_source_id)
        if not data_source:
            raise HTTPException(status_code=404, detail="data source not found")
        require_workspace_role(user, data_source["workspace_id"], ORG_ADMIN_ROLES)
        job = store.create_phase4_ingest_job(data_source=data_source, created_by_user_id=user["id"])
        try:
            enqueue = job_queue.enqueue_ingest_job(job["id"])
        except JobQueueUnavailable as exc:
            if not settings.job_queue_fail_open:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "job queue unavailable",
                        "backend": job_queue.backend,
                        "fail_open": False,
                        "reason": str(exc),
                        "job_id": job["id"],
                    },
                ) from exc
            enqueue = {"backend": job_queue.backend, "enqueued": False, "fail_open": True, "reason": str(exc)}
        return {**job, "queue_enqueue": enqueue}

    @app.get("/ingest-jobs")
    async def phase4_list_ingest_jobs(workspace_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        return store.list_phase4_ingest_jobs(workspace["id"])

    @app.get("/ingest-jobs/{job_id}")
    async def phase4_get_ingest_job(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        job = store.get_phase4_ingest_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="ingest job not found")
        require_workspace_for_user(user, job["workspace_id"])
        return job

    @app.post("/ingest-jobs/{job_id}/run")
    async def phase4_run_ingest_job(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        job = store.get_phase4_ingest_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="ingest job not found")
        require_workspace_role(user, job["workspace_id"], ORG_ADMIN_ROLES)
        return run_local_data_source_ingest(store, job_id)

    @app.get("/exports")
    async def phase4_list_exports(
        workspace_id: str,
        thread_id: str | None = None,
        export_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        if thread_id:
            thread = require_thread_for_user(user, thread_id)
            if thread["workspace_id"] != workspace["id"]:
                raise HTTPException(status_code=403, detail="thread is outside workspace")
        return [
            public_export_record(export)
            for export in store.list_phase4_exports(
                workspace_id=workspace["id"],
                thread_id=thread_id,
                export_type=export_type,
                limit=limit,
            )
        ]

    @app.get("/export-jobs")
    async def phase4_list_export_jobs(
        workspace_id: str,
        thread_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        workspace = require_workspace_for_user(user, workspace_id)
        if thread_id:
            thread = require_thread_for_user(user, thread_id)
            if thread["workspace_id"] != workspace["id"]:
                raise HTTPException(status_code=403, detail="thread is outside workspace")
        return store.list_phase4_export_jobs(
            workspace_id=workspace["id"],
            thread_id=thread_id,
            status=status,
            limit=limit,
        )

    @app.get("/export-jobs/{job_id}")
    async def phase4_get_export_job(
        job_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = store.get_phase4_export_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="export job not found")
        require_workspace_for_user(user, job["workspace_id"])
        return job

    @app.get("/exports/{export_id}/download", response_model=None)
    async def phase4_download_export(
        export_id: str,
        filename: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any] | FileResponse:
        export = store.get_phase4_export(export_id)
        if not export:
            raise HTTPException(status_code=404, detail="export not found")
        require_workspace_for_user(user, export["workspace_id"])

        files = export.get("metadata", {}).get("files") or {}
        if not isinstance(files, dict) or not files:
            raise HTTPException(status_code=404, detail="export files not found")

        if filename is None:
            file_manifest = []
            for name, uri in sorted(files.items()):
                try:
                    path = object_store.file_path_for_uri(str(uri))
                except FileNotFoundError:
                    try:
                        content = object_store.get_bytes(str(uri))
                    except FileNotFoundError:
                        file_manifest.append({"file": name, "missing": True})
                        continue
                    file_manifest.append(
                        {
                            "file": name,
                            "size_bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "remote": True,
                        }
                    )
                else:
                    file_manifest.append(
                        {
                            "file": name,
                            "size_bytes": path.stat().st_size,
                            "sha256": _hash_file(path),
                        }
                    )
            return {
                "export": public_export_record(export),
                "files": file_manifest,
            }

        safe_name = _safe_export_filename(filename)
        uri = files.get(safe_name)
        if not uri:
            raise HTTPException(status_code=404, detail="export file not found")
        try:
            path = object_store.file_path_for_uri(str(uri))
        except FileNotFoundError as exc:
            try:
                content = object_store.get_bytes(str(uri))
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="export file not found") from exc
            media_type = (
                "application/json"
                if safe_name.endswith(".json")
                else "application/x-ndjson"
                if safe_name.endswith(".jsonl")
                else "text/markdown"
                if safe_name.endswith(".md")
                else "text/csv"
                if safe_name.endswith(".csv")
                else "application/zip"
                if safe_name.endswith(".zip")
                else "application/pdf"
                if safe_name.endswith(".pdf")
                else "application/octet-stream"
            )
            return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})
        media_type = (
            "application/json"
            if path.suffix == ".json"
            else "application/x-ndjson"
            if path.suffix == ".jsonl"
            else "text/markdown"
            if path.suffix == ".md"
            else "text/csv"
            if path.suffix == ".csv"
            else "application/zip"
            if path.suffix == ".zip"
            else "application/pdf"
            if path.suffix == ".pdf"
            else "application/octet-stream"
        )
        return FileResponse(path, media_type=media_type, filename=safe_name)

    @app.post("/threads/{thread_id}/exports", status_code=202)
    async def phase4_thread_export(
        thread_id: str,
        payload: ThreadExportRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        thread = require_thread_for_user(user, thread_id)
        workspace = require_workspace_role(user, thread["workspace_id"], WORKSPACE_WRITE_ROLES)
        if payload.export_type in {"learning_trace_export", "demo_eval_snapshot"}:
            require_workspace_role(user, thread["workspace_id"], RESEARCH_REVIEW_ROLES)
        if payload.export_type == "data_source_audit":
            require_workspace_role(user, thread["workspace_id"], ORG_ADMIN_ROLES)
        enforce_workspace_quota(workspace, "max_exports")
        if settings.job_queue_backend == "redis":
            job = store.create_phase4_export_job(
                thread=thread,
                created_by_user_id=user["id"],
                export_type=payload.export_type,
                redaction_status=payload.redaction_status,
                queue_name=settings.export_queue_name,
            )
            try:
                enqueue = job_queue.enqueue_export_job(job["id"])
            except JobQueueUnavailable as exc:
                store.update_phase4_export_job(
                    job_id=job["id"],
                    status="failed",
                    result={"queue_backend": job_queue.backend},
                    error_message=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                if not settings.job_queue_fail_open:
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "job queue unavailable",
                            "backend": job_queue.backend,
                            "fail_open": False,
                            "reason": str(exc),
                            "job_id": job["id"],
                        },
                    ) from exc
                enqueue = {"backend": job_queue.backend, "enqueued": False, "fail_open": True, "reason": str(exc)}
            return {"export_job": store.get_phase4_export_job(job["id"]) or job, "queue_enqueue": enqueue}

        phase5_metrics = _latest_phase5_metrics_for_thread(store, thread)
        if not phase5_metrics:
            result = create_phase4_thread_export(
                store=store,
                object_store=object_store,
                thread=thread,
                created_by_user_id=user["id"],
                export_type=payload.export_type,
                redaction_status=payload.redaction_status,
                storage_backend=settings.object_store_backend,
            )
            return {
                **result,
                "export": public_export_record(result["export"]),
            }
        export_profiler = TraceProfiler(trace_id=phase5_metrics["trace_id"])
        export_profiler.set_thread_id(thread["id"])
        export_profiler.set_turn_id(phase5_metrics["turn_id"])
        result: dict[str, Any] | None = None
        try:
            with export_profiler.span(
                "export.generate",
                metadata={
                    "export_type": payload.export_type,
                    "redaction_status": payload.redaction_status,
                    "storage_backend": settings.object_store_backend,
                },
            ) as export_span:
                result = create_phase4_thread_export(
                    store=store,
                    object_store=object_store,
                    thread=thread,
                    created_by_user_id=user["id"],
                    export_type=payload.export_type,
                    redaction_status=payload.redaction_status,
                    storage_backend=settings.object_store_backend,
                )
                export = result["export"]
                files = (export.get("metadata") or {}).get("files") or {}
                export_span.output_size = len(files)
                export_span.metadata.update({"export_id": export["id"], "file_count": len(files)})
        finally:
            if export_profiler.spans:
                store.create_phase5_trace_spans(export_profiler.span_records())
        if result is None:
            raise HTTPException(status_code=500, detail="thread export did not produce a result")
        return {
            **result,
            "export": public_export_record(result["export"]),
        }

    @app.post("/image-rag/query")
    async def phase4_image_rag_query(payload: ImageRagQuery, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), WORKSPACE_WRITE_ROLES)
        thread = None
        if payload.thread_id:
            thread = require_thread_for_user(user, str(payload.thread_id))
            if thread["workspace_id"] != workspace["id"]:
                raise HTTPException(status_code=403, detail="thread is outside workspace")
        attachments = []
        for attachment_id in payload.attachment_ids:
            attachments.append(require_attachment_for_workspace(workspace, str(attachment_id)))
        if settings.job_queue_backend == "redis":
            job = store.create_phase4_image_job(
                workspace=workspace,
                created_by_user_id=user["id"],
                question=payload.question,
                attachment_ids=[attachment["id"] for attachment in attachments],
                thread_id=thread["id"] if thread else None,
                crop=payload.crop,
                region=payload.region,
                queue_name=settings.image_queue_name,
            )
            try:
                enqueue = job_queue.enqueue_image_job(job["id"])
            except JobQueueUnavailable as exc:
                store.update_phase4_image_job(
                    job_id=job["id"],
                    status="failed",
                    result={"queue_backend": job_queue.backend},
                    error_message=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                if not settings.job_queue_fail_open:
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "job queue unavailable",
                            "backend": job_queue.backend,
                            "fail_open": False,
                            "reason": str(exc),
                            "job_id": job["id"],
                        },
                    ) from exc
                enqueue = {"backend": job_queue.backend, "enqueued": False, "fail_open": True, "reason": str(exc)}
            return {"image_job": store.get_phase4_image_job(job["id"]) or job, "queue_enqueue": enqueue}
        image_search = _image_embedding_search(
            query_attachments=attachments,
            candidate_embeddings=store.list_phase4_image_embeddings(workspace["id"]),
            crop=payload.crop,
            region=payload.region,
        )
        image_payload = _image_quality_payload(
            attachments=attachments,
            question=payload.question,
            crop=payload.crop,
            region=payload.region,
            observation_adapter=image_observation_adapter,
            similar_examples=image_search["examples"],
            image_retrieval_eval=image_search["eval_summary"],
        )
        if thread:
            store.append_phase4_trace_event(
                thread=thread,
                event_type="image_observation",
                actor="system",
                payload=image_payload,
            )
        return {
            "research_preview": True,
            **image_payload,
            "next_steps": [
                "Provide crop, growth stage, region, scouting pattern, and recent weather.",
                "Do not choose a product or rate before diagnosis and current label checks.",
            ],
        }

    @app.post("/image-rag/evals")
    async def phase4_image_rag_eval(payload: ImageEvalRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        workspace = require_workspace_role(user, str(payload.workspace_id), RESEARCH_REVIEW_ROLES)
        try:
            report = evaluate_image_research_samples(
                samples=[sample.model_dump(mode="json") for sample in payload.samples],
                top_k=payload.top_k,
                confidence_bins=payload.confidence_bins,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "workspace_id": workspace["id"],
            "research_preview": True,
            "not_for_diagnosis_or_treatment": True,
            **report,
        }

    @app.get("/api/sessions")
    async def list_sessions(request: Request, include_archived: bool = False) -> list[dict[str, Any]]:
        user = _demo_field_user(request)
        return [
            _session_response(session)
            for session in store.list_sessions(include_archived=include_archived)
            if _session_visible_to_user(session, request=request, user=user)
        ]

    @app.get("/api/geo/layers")
    async def public_geo_layer_catalog() -> dict[str, Any]:
        return layer_catalog(network_mode=settings.network_mode)

    @app.get("/api/geo/regions")
    async def public_geo_regions(bbox: str, layers: str | None = None) -> dict[str, Any]:
        try:
            bbox_values = tuple(float(value.strip()) for value in bbox.split(","))
            if len(bbox_values) != 4:
                raise ValueError("bbox must contain four comma-separated values")
            layer_ids = [value.strip() for value in layers.split(",") if value.strip()] if layers else None
            return query_region_layers(
                bbox=bbox_values,
                layer_ids=layer_ids,
                network_mode=settings.network_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/demo/fields")
    async def public_demo_fields(request: Request) -> dict[str, Any]:
        user = _demo_field_user(request)
        workspace = _demo_field_workspace(user)
        contexts = [
            context
            for context in store.list_phase4_field_contexts(workspace["id"])
            if _demo_field_metadata(context).get("kind") == "map_field"
        ]
        return {
            "schema_version": "open_agronomy_agent.demo_fields.v1",
            "storage": {
                "mode": "account_workspace",
                "workspace_id": workspace["id"],
                "workspace_name": workspace["name"],
                "user_id": user["id"],
                "user_email": user["email"],
                "boundary": "Stored fields are local workspace records for demo review; they are not benchmark, RAG, KG, or training data.",
            },
            "fields": [_demo_field_record(context) for context in contexts],
        }

    @app.post("/api/demo/fields", status_code=201)
    async def create_public_demo_field(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        if len(json.dumps(payload, default=str)) > 200_000:
            raise HTTPException(status_code=413, detail="demo field payload is too large")
        user = _demo_field_user(request)
        workspace = _demo_field_workspace(user)
        field = payload.get("field") if isinstance(payload.get("field"), dict) else {}
        geometry = _validate_demo_field_geometry(payload.get("geometry"))
        name = _field_payload_text(payload.get("name"), fallback=f"{field.get('crop') or 'Field'} map context", max_length=160)
        crop = _field_payload_text(field.get("crop"), max_length=120)
        jurisdiction = _field_payload_text(field.get("jurisdiction"), max_length=120)
        region = _field_payload_text(field.get("region"), max_length=160)
        regional_context = _field_payload_text(payload.get("regionalContext"), fallback="regional context pending", max_length=240)
        concern = _field_payload_text(field.get("concern"), max_length=500)
        notes = _field_payload_text(field.get("notes"), max_length=1000)
        acres = _field_payload_text(field.get("acres"), max_length=40)
        source_boundary = _field_payload_text(
            payload.get("sourceBoundary"),
            fallback="Map and public-source context are decision-support priors, not field truth.",
            max_length=500,
        )
        geo_priors, geo_context_lineage = _governed_demo_geo_priors(
            geometry,
            payload.get("geoPriors"),
        )
        metadata = {
            "open_agronomy_agent": {
                "schema_version": "open_agronomy_agent.demo_field_metadata.v1",
                "kind": "map_field",
                "field": {
                    "crop": crop,
                    "region": region,
                    "jurisdiction": jurisdiction,
                    "acres": acres,
                    "concern": concern,
                    "notes": notes,
                },
                "geometry": geometry,
                "regional_context_label": regional_context,
                "geo_priors": geo_priors,
                "geo_context_lineage": geo_context_lineage,
                "source_boundary": source_boundary,
                "created_from": "map_first_public_demo",
                "not_training_data": True,
            }
        }
        record = store.create_phase4_field_context(
            workspace=workspace,
            created_by_user_id=user["id"],
            payload={
                "display_name": name,
                "region_text": regional_context,
                "country": _demo_country_for_jurisdiction(jurisdiction),
                "province_state": jurisdiction or None,
                "crop_current": crop or None,
                "management_notes": notes or concern or None,
                "known_constraints": [
                    "regional context is prior-only",
                    "not cadastral boundary evidence",
                    "not benchmark/training data",
                ],
                "sensitivity": "medium",
                "metadata": metadata,
            },
        )
        return {
            "schema_version": "open_agronomy_agent.demo_field_saved.v1",
            "storage": {
                "mode": "account_workspace",
                "workspace_id": workspace["id"],
                "workspace_name": workspace["name"],
                "user_id": user["id"],
            },
            "field": _demo_field_record(record),
        }

    @app.delete("/api/demo/fields/{field_context_id}")
    async def delete_public_demo_field(field_context_id: str, request: Request) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        workspace = require_workspace_role(user, record["workspace_id"], WORKSPACE_WRITE_ROLES)
        deleted = store.delete_phase4_field_context(field_context_id=field_context_id, deleted_by_user_id=user["id"])
        return {
            "schema_version": "open_agronomy_agent.demo_field_deleted.v1",
            "storage": {"mode": "account_workspace", "workspace_id": workspace["id"], "user_id": user["id"]},
            "field": _demo_field_record(deleted or record),
        }

    @app.post("/api/demo/fields/{field_context_id}/context-packs/quebec-lidar/plan")
    async def plan_public_demo_quebec_lidar_context_pack(
        field_context_id: str,
        request: Request,
    ) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_for_user(user, record["workspace_id"])
        field_record = _demo_field_record(record)
        jurisdiction = str(field_record.get("jurisdiction") or "").strip().lower()
        if jurisdiction not in {"quebec", "québec", "qc"}:
            raise HTTPException(
                status_code=422,
                detail="Quebec LiDAR context packs require a saved Quebec field",
            )
        try:
            geometry = _demo_geometry_geojson(field_record["geometry"])
            plan, receipt = _plan_quebec_lidar_pack_for_web(geometry)
        except ValueError as exc:
            message = str(exc)
            if any(
                marker in message.lower()
                for marker in ("is missing", "byte count mismatch", "sha256 mismatch")
            ):
                raise HTTPException(
                    status_code=503,
                    detail={
                        "status": "source_index_not_prepared",
                        "message": (
                            "The verified Quebec LiDAR index is unavailable or changed. "
                            "An operator must run the fetch-index command while connected."
                        ),
                        "network_request_attempted": False,
                    },
                ) from exc
            raise HTTPException(status_code=422, detail=message) from exc
        return {
            "schema_version": "open_agronomy_agent.demo_quebec_lidar_pack_plan.v1",
            "status": receipt["status"],
            "field_context_id": field_context_id,
            "plan_sha256": plan["plan_sha256"],
            "receipt": receipt,
            "preparation": {
                "planning_network_request_attempted": False,
                "private_plan_retained_by_server": False,
                "automatic_download_started": False,
                "download_requires_explicit_operator_network_permission": True,
                "operator_workflow": "docs/quebec_lidar_offline_pack_workflow_20260725.md",
            },
            "boundary": (
                "This local check reports source availability only. It does not download "
                "tiles, establish current field conditions, or create recommendation-grade evidence."
            ),
        }

    @app.get("/api/demo/fields/{field_context_id}/events")
    async def list_public_demo_field_events(field_context_id: str, request: Request) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_for_user(user, record["workspace_id"])
        events = store.list_phase4_field_events(field_context_id)
        return {
            "schema_version": "open_agronomy_agent.demo_field_events.v1",
            "field_context_id": field_context_id,
            "event_count": len(events),
            "events": events,
            "chain": store.verify_phase4_field_event_chain(field_context_id),
            "boundary": (
                "Field records are append-only. A correction points to an earlier record without erasing it."
            ),
        }

    @app.post("/api/demo/fields/{field_context_id}/events", status_code=201)
    async def append_public_demo_field_event(
        field_context_id: str,
        payload: FieldEventCreate,
        request: Request,
    ) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_role(user, record["workspace_id"], WORKSPACE_WRITE_ROLES)
        try:
            event = store.append_phase4_field_event(
                field_context=record,
                recorded_by_user_id=user["id"],
                payload=payload.model_dump(mode="json", exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema_version": "open_agronomy_agent.demo_field_event_appended.v1",
            "event": event,
            "chain": store.verify_phase4_field_event_chain(field_context_id),
        }

    @app.get("/api/demo/fields/{field_context_id}/events/sync")
    async def export_public_demo_field_event_sync(
        field_context_id: str,
        request: Request,
        after_sha256: str | None = None,
    ) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_for_user(user, record["workspace_id"])
        try:
            return store.export_phase4_field_event_sync(
                field_context_id,
                after_sha256=after_sha256,
            )
        except FieldEventSyncError as exc:
            raise _field_event_sync_http_error(exc) from exc

    @app.post("/api/demo/fields/{field_context_id}/events/sync")
    async def import_public_demo_field_event_sync(
        field_context_id: str,
        payload: FieldEventSyncRequest,
        request: Request,
    ) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_role(user, record["workspace_id"], WORKSPACE_WRITE_ROLES)
        try:
            return store.import_phase4_field_event_sync(
                field_context=record,
                syncing_user_id=user["id"],
                source_device_id=payload.source_device_id,
                base_head_sha256=payload.base_head_sha256,
                events=[
                    event.model_dump(mode="json", exclude_none=False)
                    for event in payload.events
                ],
            )
        except FieldEventSyncError as exc:
            raise _field_event_sync_http_error(exc) from exc

    @app.get("/api/demo/fields/{field_context_id}/history")
    async def public_demo_field_history(field_context_id: str, request: Request) -> dict[str, Any]:
        user = _demo_field_user(request)
        record = store.get_phase4_field_context(field_context_id)
        if not record or _demo_field_metadata(record).get("kind") != "map_field":
            raise HTTPException(status_code=404, detail="demo field not found")
        require_workspace_for_user(user, record["workspace_id"])

        history: list[dict[str, Any]] = []
        for session in store.list_sessions(include_archived=True):
            if not _session_visible_to_user(session, request=request, user=user):
                continue
            session_context = session.get("context") if isinstance(session.get("context"), dict) else {}
            session_extra = session_context.get("extra") if isinstance(session_context.get("extra"), dict) else {}
            session_field_id = session_context.get("field_context_id") or session_extra.get("field_context_id")
            for turn in session.get("turns", []):
                trace = turn.get("trace") if isinstance(turn.get("trace"), dict) else {}
                metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
                lineage = metadata.get("field_lineage") if isinstance(metadata.get("field_lineage"), dict) else {}
                stored_turn = store.get_turn(str(turn.get("turn_id") or ""))
                feedback = (
                    stored_turn.get("feedback")
                    if isinstance(stored_turn, dict) and isinstance(stored_turn.get("feedback"), dict)
                    else {}
                )
                lineage_field_id = lineage.get("field_context_id")
                if lineage_field_id != field_context_id and not (
                    not lineage_field_id and session_field_id == field_context_id
                ):
                    continue
                history.append(
                    {
                        "session_id": session["session_id"],
                        "session_title": session.get("title"),
                        "turn_id": turn.get("turn_id"),
                        "created_at": turn.get("created_at"),
                        "question": turn.get("user_message"),
                        "answer": turn.get("answer"),
                        "answer_status": turn.get("answer_status"),
                        "answer_integrity_receipt": (
                            stored_turn.get("answer_integrity_receipt")
                            if isinstance(stored_turn, dict)
                            else turn.get("answer_integrity_receipt")
                        ),
                        "feedback": {
                            key: feedback.get(key)
                            for key in (
                                "rating",
                                "accepted",
                                "correction",
                                "reviewer_notes",
                                "answer_status",
                            )
                            if feedback.get(key) is not None
                        },
                        "route": trace.get("route"),
                        "field_lineage": lineage or None,
                        "binding_status": "verified_snapshot" if lineage_field_id == field_context_id else "legacy_session_binding",
                        "knowledge_coverage": _answer_time_knowledge_coverage(trace),
                        "retrieved_document_count": len(trace.get("retrieved_docs") or []),
                        "tool_invocation_count": len(trace.get("tool_invocations") or []),
                    }
                )
        history.sort(key=lambda item: str(item.get("created_at") or ""))
        field_events = store.list_phase4_field_events(field_context_id)
        field_event_chain = store.verify_phase4_field_event_chain(field_context_id)
        field_record = _demo_field_record(record)
        return {
            "schema_version": "open_agronomy_agent.demo_field_history.v4",
            "field": {
                key: field_record.get(key)
                for key in (
                    "id",
                    "field_context_id",
                    "name",
                    "crop",
                    "region",
                    "jurisdiction",
                    "acres",
                    "createdAt",
                    "updatedAt",
                    "storageMode",
                )
            },
            "event_count": len(field_events),
            "events": field_events,
            "event_chain": field_event_chain,
            "turn_count": len(history),
            "turns": history,
            "boundary": (
                "Field records are append-only and corrections preserve the prior record. "
                "verified_snapshot answers carry a hash of the exact field context used; "
                "verified answer_integrity_receipt records bind immutable answer content and trace hashes; "
                "this verifies context lineage, not answer correctness. "
                "Later turns may use prior questions and human review for continuity, but prior model answers "
                "are never promoted to agronomic evidence and rejected outputs must not be repeated. "
                "Canadian knowledge coverage is the minimized answer-time trace snapshot, not a current-coverage lookup. "
                "legacy_session_binding, legacy_not_captured receipts, or not_captured coverage must be reviewed before action."
            ),
        }

    @app.post("/api/geo/intersections")
    async def public_geo_intersections(payload: dict[str, Any]) -> dict[str, Any]:
        geometry = payload.get("geometry")
        layers = payload.get("layers")
        layer_ids = [str(value) for value in layers] if isinstance(layers, list) else None
        try:
            return intersect_region_layers(
                geometry=geometry,
                layer_ids=layer_ids,
                network_mode=settings.network_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/geo/boundary-upload")
    async def public_geo_boundary_upload(file: UploadFile = File(...), intersect: bool = False) -> dict[str, Any]:
        raw = await file.read()
        try:
            parsed = parse_boundary_upload(
                filename=str(file.filename or "boundary"),
                content_type=str(file.content_type or "application/octet-stream"),
                raw=raw,
            )
            if intersect:
                return attach_region_intersections_to_upload(
                    parsed,
                    network_mode=settings.network_mode,
                )
            return parsed
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/private-knowledge/inspect")
    async def inspect_ephemeral_private_knowledge(
        request: Request,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        _require_local_cockpit_research(request)
        filename = _safe_filename(str(file.filename or "private-reference"))
        content_type = str(file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        allowed = {"text/plain", "text/markdown", "application/json", "application/pdf"}
        if content_type not in allowed:
            raise HTTPException(
                status_code=422,
                detail="private references must be PDF, plain text, Markdown, or JSON",
            )
        raw = await file.read()
        limit = 5_000_000 if content_type == "application/pdf" else 1_000_000
        if not raw:
            raise HTTPException(status_code=422, detail="private reference is empty")
        if len(raw) > limit:
            raise HTTPException(
                status_code=422,
                detail=f"private reference must be {limit // 1_000_000}MB or smaller",
            )
        scan = _scan_attachment_bytes(
            raw,
            filename=filename,
            content_type=content_type,
            scanner=ephemeral_private_scanner,
        )
        quality_flags: list[str] = []
        if content_type == "application/pdf":
            text, quality_flags = _extract_pdf_text(raw)
            if not text or "low_text_pdf" in quality_flags:
                return {
                    "schema_version": "open_agronomy_agent.ephemeral_private_knowledge.v1",
                    "filename": filename,
                    "content_type": content_type,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "parse_status": "blocked",
                    "persisted": False,
                    "training_eligible": False,
                    "retrieval_policy": "context_only",
                    "quality_flags": [*quality_flags, "not_loaded_into_browser_session"],
                    "chunks": [],
                    "scan": scan,
                    "boundary": (
                        "The PDF did not contain enough locally extractable text. OCR is not silently "
                        "attempted and the file was not retained."
                    ),
                }
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=422, detail="text reference must be UTF-8") from exc
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        chunks = _chunk_ephemeral_private_text(
            text=text,
            filename=filename,
            raw_sha256=raw_sha256,
        )
        return {
            "schema_version": "open_agronomy_agent.ephemeral_private_knowledge.v1",
            "filename": filename,
            "content_type": content_type,
            "raw_sha256": raw_sha256,
            "parse_status": "ready" if chunks else "blocked",
            "persisted": False,
            "training_eligible": False,
            "retrieval_policy": "context_only",
            "quality_flags": quality_flags,
            "chunks": chunks,
            "scan": scan,
            "boundary": (
                "The document was parsed on this device and was not retained by the server. It is "
                "unverified context, never decisive authority. Saved answers may paraphrase it."
            ),
        }
    @app.post("/api/geo/priors")
    async def public_geo_priors(payload: dict[str, Any]) -> dict[str, Any]:
        location_text = str(payload.get("location_text") or "").strip()
        if not location_text:
            raise HTTPException(status_code=422, detail="location_text is required")
        if len(location_text) > 500:
            raise HTTPException(status_code=422, detail="location_text must be 500 characters or fewer")
        priors = _geo_priors_for_location(location_text)
        geometry = payload.get("geometry")
        if isinstance(geometry, dict):
            try:
                intersections = intersect_region_layers(
                    geometry=geometry,
                    layer_ids=None,
                    network_mode=settings.network_mode,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if intersections["intersections"]:
                priors["candidate_regions"] = [
                    {
                        "label": item["name"],
                        "name": item["name"],
                        "layer": item["layer_id"],
                        "system": item["system"],
                        "code": item["code"],
                        "confidence": item["confidence"],
                        "match_reason": item["match_reason"],
                        "priors": ["official polygon intersection", "use as regional context prior"],
                        "evidence_terms": [item["code"], item["name"]],
                        "source": item["source"],
                    }
                    for item in intersections["intersections"]
                ]
                priors["evidence"] = [*priors.get("evidence", []), "official_polygon_intersection"]
                priors["uncertainty"] = "low" if intersections["intersections"][0]["confidence"] >= 0.9 else "medium"
            priors["regional_intersections"] = intersections["intersections"]
            priors["regional_feature_collection"] = intersections["feature_collection"]
            priors["geo_errors"] = intersections["errors"]
            priors["official_layer_status"] = official_layer_status(intersections)
        return priors

    @app.post("/api/sessions")
    async def create_session(payload: CreateSessionRequest, request: Request) -> dict[str, Any]:
        user = _demo_field_user(request)
        session = store.create_session(
            title=payload.title,
            user_pseudonym=payload.user_pseudonym,
            tags=payload.tags,
            context=_context_with_session_owner(payload.context.model_dump(), str(user["id"])),
            consent=payload.consent.model_dump(),
        )
        return _session_response(session)

    @app.get("/api/sessions/{session_id}")
    async def load_session(session_id: str, request: Request) -> dict[str, Any]:
        session, _ = _require_owned_session(request, session_id)
        return _session_response(session)

    @app.patch("/api/sessions/{session_id}")
    async def patch_session(session_id: str, payload: SessionUpdateRequest, request: Request) -> dict[str, Any]:
        session, user = _require_owned_session(request, session_id)

        merged_context = None
        if payload.context:
            merged_context = _context_with_session_owner(
                _merge_context(session.get("context"), payload.context.model_dump()),
                str(user["id"]),
            )

        updated = store.update_session(
            session_id,
            title=payload.title,
            user_pseudonym=payload.user_pseudonym,
            tags=payload.tags,
            context=merged_context,
            consent=payload.consent.model_dump() if payload.consent else None,
            archived=payload.archived,
            status=payload.status,
        )
        return _session_response(updated or session)

    @app.post("/api/sessions/{session_id}/turns")
    async def create_turn(
        session_id: str,
        payload: CreateTurnRequest,
        request: Request,
    ) -> dict[str, Any]:
        session, user = _require_owned_session(request, session_id)
        if payload.mode not in {"baseline", "agronomic_rag", "mock"}:
            raise HTTPException(status_code=400, detail="invalid mode")
        runtime_mode(payload.mode)
        selected_rag_config = runtime_rag_config(payload.rag_config)
        selected_model_id = runtime_model_id(payload.model_id, mode=payload.mode)

        authorized_session_context = _authorize_demo_turn_field_context(
            request,
            payload.session_context,
        )
        persistable_session_context = _persistable_demo_turn_context(authorized_session_context)
        if persistable_session_context:
            store.update_session(
                session_id,
                context=_context_with_session_owner(
                    _merge_context(session.get("context"), persistable_session_context),
                    str(user["id"]),
                ),
            )

        profiler = TraceProfiler()
        try:
            result = run_turn(
                store=store,
                settings=settings,
                session_id=session_id,
                message=payload.message,
                mode=payload.mode,
                model_id=selected_model_id,
                rag_config=selected_rag_config,
                max_tokens=payload.max_tokens,
                trace_options=payload.trace_options.model_dump(),
                session_context=authorized_session_context,
                profiler=profiler,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404 if "session not found" in str(exc) else 400,
                detail=str(exc),
            )
        turn = result.get("turn") if isinstance(result, dict) else None
        if not isinstance(turn, dict):
            raise HTTPException(status_code=500, detail="turn persistence failed")
        profiler.add_observed(
            "http.request",
            start_ns=profiler.started_ns,
            metadata={"path": f"/api/sessions/{session_id}/turns", "mode": payload.mode},
        )
        phase5_metrics = persist_phase5_turn_record(
            profiler=profiler,
            thread_id=session_id,
            turn_id=result["turn_id"],
            user_id=None,
            workspace_id=None,
            answer_text=str(turn.get("answer") or ""),
            trace=turn.get("trace", {}) or {},
            system_state=turn.get("system_state", {}) or {},
            model_id=str(
                (turn.get("system_state") or {}).get("model_id")
                or selected_model_id
                or settings.default_model_id,
            ),
            rag_config_id=selected_rag_config,
            max_tokens=payload.max_tokens,
        )
        turn.setdefault("metadata", {})["phase5_trace_id"] = phase5_metrics["trace_id"]
        turn["knowledge_coverage"] = _answer_time_knowledge_coverage(turn.get("trace"))
        return {"turn_id": result["turn_id"], "turn": turn}

    @app.post("/api/sessions/{session_id}/turns/stream")
    async def create_turn_stream(
        session_id: str,
        payload: CreateTurnRequest,
        request: Request,
    ) -> StreamingResponse:
        session, user = _require_owned_session(request, session_id)
        if payload.mode not in {"baseline", "agronomic_rag", "mock"}:
            raise HTTPException(status_code=400, detail="invalid mode")
        runtime_mode(payload.mode)
        selected_rag_config = runtime_rag_config(payload.rag_config)
        selected_model_id = runtime_model_id(payload.model_id, mode=payload.mode)
        authorized_session_context = _authorize_demo_turn_field_context(
            request,
            payload.session_context,
        )
        persistable_session_context = _persistable_demo_turn_context(authorized_session_context)
        if persistable_session_context:
            store.update_session(
                session_id,
                context=_context_with_session_owner(
                    _merge_context(session.get("context"), persistable_session_context),
                    str(user["id"]),
                ),
            )

        model_id = None if payload.mode == "mock" else selected_model_id

        async def event_stream() -> Any:
            def sse(event_name: str, data: dict[str, Any]) -> str:
                return f"event: {event_name}\n" f"data: {json.dumps(data)}\n\n"

            loop = asyncio.get_running_loop()
            progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            def on_span(span: Any) -> None:
                if span.stage not in STREAM_PROGRESS_STAGE_COPY:
                    return
                loop.call_soon_threadsafe(progress_queue.put_nowait, span.as_record())

            profiler = TraceProfiler(on_span=on_span)
            emitted_stages: set[str] = set()
            yield sse(
                "progress.step",
                {
                    "label": "Preparing field context",
                    "detail": _stream_field_context_detail(payload),
                    "progress": 8,
                    "elapsed_ms": 0,
                    "stage_id": "request.field_context",
                    "stage_status": "ok",
                    "category": "field context",
                },
            )

            started = time.perf_counter()
            stream_started_ns = time.monotonic_ns()
            task = asyncio.create_task(
                asyncio.to_thread(
                    run_turn,
                    store=store,
                    settings=settings,
                    session_id=session_id,
                    message=payload.message,
                    mode=payload.mode,
                    model_id=model_id,
                    rag_config=selected_rag_config,
                    max_tokens=payload.max_tokens,
                    trace_options=payload.trace_options.model_dump(),
                    session_context=authorized_session_context,
                    profiler=profiler,
                )
            )
            heartbeat_count = 0
            while not task.done():
                try:
                    span_record = await asyncio.wait_for(progress_queue.get(), timeout=0.8)
                    progress_event = _stream_progress_event_from_span(
                        span_record,
                        started=started,
                        emitted_stages=emitted_stages,
                    )
                    if progress_event:
                        yield sse("progress.step", progress_event)
                except TimeoutError:
                    elapsed = time.perf_counter() - started
                    heartbeat_count += 1
                    yield sse(
                        "progress.heartbeat",
                        {
                            "label": "Working locally",
                            "detail": "The backend is still running the current stage; no field data has left this dev server.",
                            "progress": min(88, 18 + heartbeat_count * 4),
                            "elapsed_ms": int(elapsed * 1000),
                            "stage_id": "backend.heartbeat",
                            "stage_status": "running",
                            "category": "local runtime",
                        },
                    )
                    continue

            try:
                result = task.result()
            except Exception as exc:
                yield sse(
                    "error",
                    {
                        "message": str(exc),
                        "label": "Generation failed",
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
                return

            turn_id = result.get("turn_id")
            if not turn_id:
                yield sse(
                    "error",
                    {
                        "message": "turn persistence failed",
                        "label": "Generation failed",
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
                return
            turn = result["turn"] if isinstance(result.get("turn"), dict) else {}
            answer = str(turn.get("answer") or "")
            profiler.add_observed(
                "http.request",
                start_ns=profiler.started_ns,
                metadata={"path": f"/api/sessions/{session_id}/turns/stream", "mode": payload.mode},
            )
            profiler.add_observed(
                "ui.stream_response",
                start_ns=stream_started_ns,
                metadata={"chunk_size": 48},
            )
            phase5_metrics = persist_phase5_turn_record(
                profiler=profiler,
                thread_id=session_id,
                turn_id=str(turn_id),
                user_id=None,
                workspace_id=None,
                answer_text=answer,
                trace=turn.get("trace", {}) or {},
                system_state=turn.get("system_state", {}) or {},
                model_id=str(
                    (turn.get("system_state") or {}).get("model_id")
                    or selected_model_id
                    or settings.default_model_id,
                ),
                rag_config_id=selected_rag_config,
                max_tokens=payload.max_tokens,
            )
            turn.setdefault("metadata", {})["phase5_trace_id"] = phase5_metrics["trace_id"]
            turn["knowledge_coverage"] = _answer_time_knowledge_coverage(turn.get("trace"))

            while not progress_queue.empty():
                progress_event = _stream_progress_event_from_span(
                    progress_queue.get_nowait(),
                    started=started,
                    emitted_stages=emitted_stages,
                )
                if progress_event:
                    yield sse("progress.step", progress_event)

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            yield sse(
                "progress.step",
                {
                    "label": "Writing answer",
                    "detail": "Streaming the final answer into the chat panel.",
                    "progress": 92,
                    "elapsed_ms": elapsed_ms,
                    "stage_id": "ui.stream_response",
                    "stage_status": "ok",
                    "category": "answer",
                },
            )
            for chunk in _chunk_text_for_stream(answer, chunk_size=64):
                yield sse("generation.token", {"token": chunk, "turn_id": turn_id, "elapsed_ms": elapsed_ms})
                await asyncio.sleep(0.01)
            yield sse(
                "progress.step",
                {
                    "label": "Answer ready",
                    "detail": "Answer, trace, evidence cards, and metrics are saved.",
                    "progress": 100,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "stage_id": "answer.completed",
                    "stage_status": "ok",
                    "category": "answer",
                },
            )
            completed = {
                "turn_id": turn_id,
                "turn": turn,
                "phase5_trace_id": phase5_metrics["trace_id"],
            }
            yield sse("answer.completed", completed)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/sessions/{session_id}/events")
    async def stream_session_events(
        session_id: str,
        request: Request,
        since_id: int | None = Query(default=None),
        block_ms: int = Query(default=0, ge=0, le=120000),
    ):
        _require_owned_session(request, session_id)

        async def event_generator() -> Any:
            cursor = since_id
            while True:
                emitted = 0
                for event in store.list_events(session_id, cursor):
                    cursor = event["id"]
                    payload = json.dumps(event["payload"], ensure_ascii=False)
                    yield f"event: {event['event_name']}\n" + f"id: {event['id']}\n" + f"data: {payload}\n\n"
                    emitted += 1
                if block_ms <= 0 or emitted == 0:
                    break
                await asyncio.sleep(block_ms / 1000)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/api/context/route")
    async def context_route(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        message = str(payload.get("message", "")).strip() or str(payload.get("question", "")).strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        return {"route": route_query(message)}

    @app.post("/api/context/retrieve")
    async def context_retrieve(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        message = str(payload.get("message", "")).strip() or str(payload.get("question", "")).strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        try:
            top_k = _safe_int_from_request(payload.get("top_k"), default=5, min_value=1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rag_config = runtime_rag_config(
            str(payload["rag_config"]) if payload.get("rag_config") else None
        )
        result = retrieve_only(message, top_k=top_k, rag_config=rag_config)
        docs = result.get("retrieved_docs", [])
        route = result.get("route", {})
        result["diagnostics"] = {
            "route": route,
            "doc_count": len(docs),
            "source_diversity": len({doc.get("source") for doc in docs if isinstance(doc, dict)}),
            "top_doc_score": max((doc.get("score", 0.0) for doc in docs if isinstance(doc, dict)), default=0.0),
        }
        return result

    @app.post("/api/tools/{tool_name}")
    async def run_tool(tool_name: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
        _demo_field_user(request)
        try:
            return run_local_tool(tool_name, payload, network_mode=settings.network_mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/feedback")
    async def submit_feedback(payload: FeedbackRequest, request: Request) -> dict[str, Any]:
        _require_owned_session(request, payload.session_id)
        turn = store.get_turn(payload.turn_id)
        if not turn:
            raise HTTPException(status_code=404, detail="turn not found")
        if str(turn.get("session_id") or "") != payload.session_id:
            raise HTTPException(status_code=404, detail="turn not found in session")
        saved = store.set_feedback(payload.session_id, payload.turn_id, payload.model_dump())
        return {"status": "ok", "feedback": saved}

    @app.post("/api/reflections")
    async def submit_reflection(payload: ReflectionRequest, request: Request) -> dict[str, Any]:
        _require_owned_session(request, payload.session_id)
        turn = store.get_turn(payload.turn_id)
        if not turn:
            raise HTTPException(status_code=404, detail="turn not found")
        if str(turn.get("session_id") or "") != payload.session_id:
            raise HTTPException(status_code=404, detail="turn not found in session")
        saved = store.set_reflection(payload.session_id, payload.turn_id, payload.model_dump())
        return {"status": "ok", "reflection": saved}

    @app.post("/api/exports")
    async def create_export(payload: ExportRequest, request: Request) -> dict[str, Any]:
        session, _ = _require_owned_session(request, payload.session_id)

        if payload.redaction_mode not in {"none", "identifiers", "snippets_hashed", "training_safe"}:
            raise HTTPException(status_code=400, detail="invalid redaction mode")
        if payload.redaction_mode == "training_safe" and not session.get("consent", {}).get("training_export_allowed"):
            raise HTTPException(status_code=403, detail="training_safe requires training_export_allowed")
        if not payload.include_turns and payload.turn_ids:
            raise HTTPException(status_code=400, detail="turn_ids requires include_turns=true")
        if payload.include_turns and payload.turn_ids:
            known_turn_ids = {turn["turn_id"] for turn in session.get("turns", [])}
            missing = [turn_id for turn_id in payload.turn_ids if turn_id not in known_turn_ids]
            if missing:
                raise HTTPException(
                status_code=400,
                detail=f"unknown turn ids: {', '.join(sorted(missing))}",
            )

        export_id = store._new_id("exp")
        try:
            manifest, file_map = build_export_bundle(
                session,
                store,
                settings.artifact_root,
                export_id=export_id,
                redaction_mode=payload.redaction_mode,
                include_turn_ids=payload.turn_ids,
                include_turns=payload.include_turns,
                include_data_sources=payload.include_data_sources,
                include_artifacts=payload.include_artifacts,
                prompt_version=settings.prompt_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        store.create_export(payload.session_id, payload.redaction_mode, manifest, export_id=export_id)
        return {
            "export_id": export_id,
            "manifest": manifest,
            "files": file_map,
        }

    @app.get("/api/exports/{export_id}/download", response_model=None)
    async def download_export(
        export_id: str,
        request: Request,
        filename: str | None = None,
    ) -> dict[str, Any] | FileResponse:
        export_record = store.get_export(export_id)
        if not export_record:
            raise HTTPException(status_code=404, detail="export not found")
        _require_owned_session(request, str(export_record["session_id"]))
        if filename is None:
            return export_record["manifest"]
        export_dir = settings.artifact_root / export_id
        export_root = export_dir.resolve()
        if not export_dir.exists():
            raise HTTPException(status_code=404, detail="export not found")
        target = (export_dir / filename).resolve()
        if not target.is_relative_to(export_root):
            raise HTTPException(status_code=400, detail="invalid filename")
        if not target.exists():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(target, filename=target.name)

    @app.get("/api/data-sources")
    async def list_data_sources(request: Request) -> list[dict[str, Any]]:
        _require_local_cockpit_research(request)
        return store.list_data_sources()

    @app.post("/api/data-sources")
    async def register_data_source(payload: DataSourceRequest, request: Request) -> dict[str, Any]:
        _require_local_cockpit_research(request)
        inspection = inspect_source(path=payload.path, url=payload.url)
        checksum = read_checksum(payload.path) if payload.path else None
        source = store.create_data_source(
            source_type=payload.source_type,
            path=payload.path,
            url=payload.url,
            owner=payload.owner,
            license_status=payload.license_status or "unknown",
            training_eligible=payload.training_eligible,
            refresh_policy=payload.refresh_policy,
            checksum=checksum,
            inspection=inspection,
        )
        return source

    @app.post("/api/replay")
    async def replay(payload: ReplayRequest, request: Request) -> dict[str, Any]:
        base_turn = store.get_turn(payload.base_turn_id)
        if not base_turn:
            raise HTTPException(status_code=404, detail="turn not found")
        _require_owned_session(request, str(base_turn.get("session_id") or ""))
        replay_rag_config = (
            None
            if settings.allow_rag_config_override and payload.rag_config is None
            else runtime_rag_config(payload.rag_config)
        )
        replay_model_id = (
            None
            if settings.allow_model_id_override and payload.model_id is None
            else runtime_model_id(payload.model_id, mode=payload.mode)
        )
        try:
            output = replay_turn(
                store=store,
                settings=settings,
                base_turn_id=payload.base_turn_id,
                override={
                    "session_id": "",  # resolved from base turn
                    "mode": payload.mode,
                    "model_id": replay_model_id,
                    "rag_config": replay_rag_config,
                    "max_tokens": payload.max_tokens,
                    "trace_options": payload.trace_options.model_dump(),
                    "top_k": payload.top_k,
                    "pipeline": payload.pipeline,
                    "override_session_context": payload.override_session_context,
                },
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=404 if "not found" in str(exc) else 400,
                detail=str(exc),
            )
        return {
            "turn_id": output["turn_id"],
            "turn": output.get("turn"),
            "base_turn": output.get("base_turn"),
            "config_delta": output.get("config_delta", {}),
            "pipeline": payload.pipeline,
        }

    if settings.static_dir is not None and settings.static_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(settings.static_dir), html=True),
            name="frontend",
        )

    return app
