from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path
from agronomy_agent.server.services.datasource_service import run_local_data_source_ingest
from agronomy_agent.server.storage.db import TraceStore


DEMO_OWNER_EMAIL = "demo.adviser@example.test"
DEMO_OWNER_NAME = "Demo Adviser"
DEMO_ORG_SLUG = "agronomy-agent-public-demo"
DEMO_ORG_NAME = "Agronomy Agent Public Demo"
DEMO_WORKSPACE_NAME = "Source-attributed demo workspace"
DEMO_FIELD_CONTEXT_NAME = "Red River Valley soybean field"


@dataclass(frozen=True)
class DemoSourceSpec:
    source_id: str
    title: str
    publisher: str
    canonical_url: str
    crops: tuple[str, ...]
    regions: tuple[str, ...]
    buckets: tuple[str, ...]
    doc_ids: tuple[str, ...]


DEMO_SOURCES = (
    DemoSourceSpec(
        source_id="demo_crop_establishment",
        title="Demo crop establishment checklist",
        publisher="Agronomy Agent curated seed corpus",
        canonical_url="repo://data/seed/agronomy_rag_corpus.jsonl#crop-establishment",
        crops=("corn", "soybean"),
        regions=("US Midwest", "Canadian Prairies"),
        buckets=("crop_management", "soil_water"),
        doc_ids=("crop_establishment_risk", "planting_window_establishment_decision", "replant_decision_workflow"),
    ),
    DemoSourceSpec(
        source_id="demo_nutrient_stewardship",
        title="Demo nutrient stewardship boundaries",
        publisher="Agronomy Agent curated seed corpus",
        canonical_url="repo://data/seed/agronomy_rag_corpus.jsonl#nutrient-stewardship",
        crops=("corn", "soybean", "wheat"),
        regions=("US Midwest", "Canada"),
        buckets=("nutrient_management", "water_quality"),
        doc_ids=("soil_fertility_n_rate", "high_phosphorus_water_quality", "manure_credit_tile_nitrogen"),
    ),
    DemoSourceSpec(
        source_id="demo_product_stewardship",
        title="Demo product stewardship guardrails",
        publisher="Agronomy Agent curated seed corpus",
        canonical_url="repo://data/seed/agronomy_rag_corpus.jsonl#product-stewardship",
        crops=("corn", "soybean", "canola", "grass seed"),
        regions=("US", "Canada"),
        buckets=("product_stewardship", "pest_management"),
        doc_ids=("label_bound_product_advice", "spray_weather_window", "fungicide_roi_decision", "photo_diagnosis_boundary"),
    ),
)


def seed_demo_workspace(store: TraceStore, *, corpus_path: str | Path = "data/seed/agronomy_rag_corpus.jsonl") -> dict[str, Any]:
    """Create a reproducible, source-attributed Phase 4 public demo workspace."""

    docs_by_id = _load_seed_docs(corpus_path)
    owner = store.upsert_phase4_user(email=DEMO_OWNER_EMAIL, display_name=DEMO_OWNER_NAME)
    organization = _get_or_create_demo_org(store, owner["id"])
    workspace = _get_or_create_demo_workspace(store, organization["id"], owner["id"])
    field_context = _get_or_create_demo_field_context(store, workspace, owner["id"])
    data_sources = _get_or_create_demo_sources(store, workspace, docs_by_id)
    ingest_jobs = [_ensure_ingested(store, data_source, owner["id"]) for data_source in data_sources]
    thread = _get_or_create_demo_thread(store, workspace, field_context, data_sources, owner["id"])
    _ensure_demo_feedback_and_eval(store, thread, owner["id"])

    chunk_counts = store.count_phase4_document_chunks_by_source(workspace["id"])
    return {
        "status": "ok",
        "owner_user_id": owner["id"],
        "organization_id": organization["id"],
        "workspace_id": workspace["id"],
        "field_context_id": field_context["id"],
        "data_source_ids": [source["id"] for source in data_sources],
        "source_ids": [source["source_id"] for source in data_sources],
        "ingest_job_ids": [job["id"] for job in ingest_jobs],
        "completed_ingest_jobs": sum(1 for job in ingest_jobs if job["status"] == "completed"),
        "chunk_count": sum(chunk_counts.get(source["id"], 0) for source in data_sources),
        "thread_id": thread["id"],
        "message_count": len(store.list_phase4_messages(thread["id"])),
        "trace_event_count": len(store.list_phase4_trace_events(thread["id"])),
        "eval_candidate_count": len(store.list_phase4_eval_candidates(workspace["id"])),
    }


def _load_seed_docs(corpus_path: str | Path) -> dict[str, dict[str, Any]]:
    path = repo_path(str(corpus_path)) if not Path(corpus_path).is_absolute() else Path(corpus_path)
    if not path.is_file():
        raise FileNotFoundError(f"demo corpus not found: {path}")
    docs: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid demo corpus JSON on line {line_no}: {exc.msg}") from exc
        doc_id = str(payload.get("doc_id") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not doc_id or not text:
            raise ValueError(f"demo corpus line {line_no} is missing doc_id or text")
        docs[doc_id] = payload
    missing = sorted({doc_id for spec in DEMO_SOURCES for doc_id in spec.doc_ids} - set(docs))
    if missing:
        raise ValueError(f"demo corpus missing required docs: {', '.join(missing)}")
    return docs


def _get_or_create_demo_org(store: TraceStore, owner_user_id: str) -> dict[str, Any]:
    for organization in store.list_phase4_organizations_for_user(owner_user_id):
        if organization["slug"] == DEMO_ORG_SLUG:
            return organization
    return store.create_phase4_organization(
        name=DEMO_ORG_NAME,
        slug=DEMO_ORG_SLUG,
        plan="demo",
        created_by_user_id=owner_user_id,
    )


def _get_or_create_demo_workspace(store: TraceStore, organization_id: str, owner_user_id: str) -> dict[str, Any]:
    for workspace in store.list_phase4_workspaces_for_user(owner_user_id, organization_id):
        if workspace["name"] == DEMO_WORKSPACE_NAME:
            return workspace
    return store.create_phase4_workspace(
        organization_id=organization_id,
        name=DEMO_WORKSPACE_NAME,
        created_by_user_id=owner_user_id,
        settings={
            "quota_overrides": {"threads": 25, "messages": 200, "data_sources": 10, "exports": 25},
            "demo_seed": {"version": "phase4_public_demo_v1"},
        },
    )


def _get_or_create_demo_field_context(store: TraceStore, workspace: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    for field_context in store.list_phase4_field_contexts(workspace["id"]):
        if field_context["display_name"] == DEMO_FIELD_CONTEXT_NAME:
            return field_context
    return store.create_phase4_field_context(
        workspace=workspace,
        created_by_user_id=owner_user_id,
        payload={
            "display_name": DEMO_FIELD_CONTEXT_NAME,
            "region_text": "Red River Valley, North Dakota / Manitoba transition",
            "country": "US/Canada",
            "province_state": "ND/MB",
            "crop_current": "soybean",
            "crop_year": 2026,
            "soil_series_or_texture": "heavy clay with slow drainage",
            "drainage_class": "poorly drained",
            "irrigation_status": "rainfed",
            "soil_test_summary": "High pH and high soil-test phosphorus near drainage outlet; method/unit details required before rates.",
            "crop_rotation_notes": "Corn-soybean rotation with cover-crop trial strips.",
            "management_notes": "Demo-only field context for source-attributed workflows; no prescriptions.",
            "known_constraints": ["water-quality boundary", "slow spring drying", "product label required"],
            "sensitivity": "low",
        },
    )


def _get_or_create_demo_sources(store: TraceStore, workspace: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {source["source_id"]: source for source in store.list_phase4_data_sources(workspace["id"])}
    sources: list[dict[str, Any]] = []
    for spec in DEMO_SOURCES:
        source = existing.get(spec.source_id)
        if source is None:
            text_content = _source_text(spec, docs_by_id)
            source = store.create_phase4_data_source(
                workspace=workspace,
                payload={
                    "source_id": spec.source_id,
                    "title": spec.title,
                    "publisher": spec.publisher,
                    "canonical_url": spec.canonical_url,
                    "license_state": "public",
                    "rag_eligible": True,
                    "sft_eligible": False,
                    "source_kind": "extension_public",
                    "crops": list(spec.crops),
                    "regions": list(spec.regions),
                    "buckets": list(spec.buckets),
                    "text_content": text_content,
                    "metadata": {
                        "demo_seed": "phase4_public_demo_v1",
                        "required_doc_ids": list(spec.doc_ids),
                        "source_attribution": "repo curated seed corpus",
                    },
                },
            )
        sources.append(source)
    return sources


def _source_text(spec: DemoSourceSpec, docs_by_id: dict[str, dict[str, Any]]) -> str:
    sections = []
    for doc_id in spec.doc_ids:
        doc = docs_by_id[doc_id]
        sections.append(f"{doc['title']}\nSource: {doc.get('source', spec.publisher)}\n{doc['text']}")
    return "\n\n".join(sections)


def _ensure_ingested(store: TraceStore, data_source: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
    counts = store.count_phase4_document_chunks_by_source(data_source["workspace_id"])
    if counts.get(data_source["id"], 0) > 0:
        return {"id": "already-indexed", "status": "completed", "result": {"chunk_count": counts[data_source["id"]]}}
    job = store.create_phase4_ingest_job(data_source=data_source, created_by_user_id=owner_user_id)
    return run_local_data_source_ingest(store, job["id"], worker_name="demo_seed")


def _get_or_create_demo_thread(
    store: TraceStore,
    workspace: dict[str, Any],
    field_context: dict[str, Any],
    data_sources: list[dict[str, Any]],
    owner_user_id: str,
) -> dict[str, Any]:
    for thread in store.list_phase4_threads(workspace["id"]):
        if thread.get("metadata", {}).get("demo_seed_id") == "phase4_public_demo_v1":
            return store.get_phase4_thread(thread["id"]) or thread
    thread = store.create_phase4_thread(
        workspace=workspace,
        created_by_user_id=owner_user_id,
        title="Demo: high-phosphorus field near drainage outlet",
        mode="agronomic_rag",
        trace_capture_level="research_opt_in",
        field_context_id=field_context["id"],
        model_profile_id="mock",
        rag_config_id="configs/rag.yaml",
        training_eligible=True,
        metadata={"demo_seed_id": "phase4_public_demo_v1", "source_ids": [source["source_id"] for source in data_sources]},
    )
    user_message = store.create_phase4_message(
        thread=thread,
        actor="user",
        content=(
            "Demo question: soybean field has very high soil-test phosphorus near a drainage outlet, "
            "slow spring drying, and pressure to plant early. What should an adviser verify before giving advice?"
        ),
        metadata={"demo_seed": True},
    )
    assistant_message = store.create_phase4_message(
        thread=thread,
        actor="assistant",
        content=(
            "Use this as a source-attributed demo workflow: confirm soil-test method/units and water-quality risk, "
            "avoid adding phosphorus until the runoff pathway is understood, check soil temperature/moisture and "
            "sidewall-smearing risk before planting, and keep pesticide or nutrient rates at decision-framework level "
            "until labels, calibration, and local field data are available."
        ),
        metadata={"demo_seed": True, "source_ids": [source["source_id"] for source in data_sources]},
    )
    store.append_phase4_trace_event(
        thread=thread,
        message_id=user_message["id"],
        event_type="route",
        actor="system",
        payload={"route": "agronomic_rag", "risk_level": "regulated_advice_boundary", "demo_seed": True},
    )
    store.append_phase4_trace_event(
        thread=thread,
        message_id=assistant_message["id"],
        event_type="retrieval",
        actor="system",
        payload={
            "demo_seed": True,
            "retrieved_sources": [
                {
                    "source_id": source["source_id"],
                    "title": source["title"],
                    "canonical_url": source["canonical_url"],
                    "license_state": source["license_state"],
                    "buckets": source["buckets"],
                }
                for source in data_sources
            ],
        },
    )
    store.append_phase4_trace_event(
        thread=thread,
        message_id=assistant_message["id"],
        event_type="model_answer",
        actor="assistant",
        payload={"demo_seed": True, "answer_kind": "cautious_decision_support", "message_id": assistant_message["id"]},
    )
    return store.get_phase4_thread(thread["id"]) or thread


def _ensure_demo_feedback_and_eval(store: TraceStore, thread: dict[str, Any], owner_user_id: str) -> None:
    messages = store.list_phase4_messages(thread["id"])
    assistant = next((message for message in reversed(messages) if message["actor"] == "assistant"), None)
    if not assistant:
        return
    existing_candidates = [
        candidate
        for candidate in store.list_phase4_eval_candidates(thread["workspace_id"])
        if candidate["thread_id"] == thread["id"] and candidate.get("payload", {}).get("demo_seed_id") == "phase4_public_demo_v1"
    ]
    if existing_candidates:
        return
    store.create_phase4_feedback(
        thread=thread,
        message_id=assistant["id"],
        created_by_user_id=owner_user_id,
        rating="good",
        failure_tags=[],
        ideal_answer="Verify soil-test method/units, runoff pathway, crop context, establishment risk, and label/local calibration before advice.",
        training_consent=True,
        metadata={"demo_seed_id": "phase4_public_demo_v1"},
    )
    candidate = store.create_phase4_eval_candidate(
        thread=thread,
        created_by_user_id=owner_user_id,
        payload={
            "demo_seed_id": "phase4_public_demo_v1",
            "candidate_type": "eval_row",
            "target_component": "hosted_demo",
            "message_id": assistant["id"],
            "prompt": messages[0]["content"] if messages else "",
            "ideal_answer": "Decision-support answer with source attribution, missing-data checks, and regulated-advice boundaries.",
            "required_patterns": ["soil-test method", "runoff", "soil temperature|moisture", "label|calibration", "source"],
        },
    )
    store.update_phase4_eval_candidate_status(
        candidate_id=candidate["id"],
        reviewed_by_user_id=owner_user_id,
        review_status="approved_for_suite",
    )
