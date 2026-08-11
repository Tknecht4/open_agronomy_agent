from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agronomy_agent.server.services.field_context_quality import evaluate_field_context_quality
from agronomy_agent.server.services.privacy_boundary import minimized_field_context_snapshot

PHASE6_REPORT_RENDERER_VERSION = "phase6_report_renderer_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object_reference(object_store: Any, stored_object: Any) -> str:
    reference_for_uri = getattr(object_store, "reference_for_uri", None)
    if callable(reference_for_uri):
        return str(reference_for_uri(stored_object.uri))
    return str(stored_object.uri)


def _object_parent_reference(object_store: Any, stored_object: Any) -> str:
    return _object_reference(object_store, stored_object).rsplit("/", 1)[0]


def build_phase4_thread_trace_bundle(
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


def build_phase4_markdown_thread_export(thread: dict[str, Any], events: list[dict[str, Any]]) -> str:
    lines = [f"# {thread['title']}", "", f"Thread ID: {thread['id']}", f"Workspace ID: {thread['workspace_id']}", ""]
    for message in thread.get("messages", []):
        lines.extend([f"## {message['actor'].title()} message", "", message["content"], ""])
    lines.extend(["## Trace events", ""])
    for event in events:
        lines.append(f"- {event['created_at']} `{event['event_type']}`")
    return "\n".join(lines)


def build_phase4_csv_thread_exports(thread: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, str]:
    messages_buffer = io.StringIO()
    message_writer = csv.DictWriter(
        messages_buffer,
        fieldnames=["thread_id", "message_id", "sequence_no", "actor", "created_at", "content"],
        lineterminator="\n",
    )
    message_writer.writeheader()
    for message in thread.get("messages", []):
        message_writer.writerow(
            {
                "thread_id": thread["id"],
                "message_id": message.get("id"),
                "sequence_no": message.get("sequence_no"),
                "actor": message.get("actor"),
                "created_at": message.get("created_at"),
                "content": message.get("content"),
            }
        )

    events_buffer = io.StringIO()
    event_writer = csv.DictWriter(
        events_buffer,
        fieldnames=["thread_id", "event_id", "event_type", "actor", "created_at", "payload_json"],
        lineterminator="\n",
    )
    event_writer.writeheader()
    for event in events:
        event_writer.writerow(
            {
                "thread_id": thread["id"],
                "event_id": event.get("id") or event.get("event_id"),
                "event_type": event.get("event_type"),
                "actor": event.get("actor"),
                "created_at": event.get("created_at"),
                "payload_json": json.dumps(event.get("payload") or {}, sort_keys=True, separators=(",", ":")),
            }
        )
    return {"thread_messages.csv": messages_buffer.getvalue(), "thread_events.csv": events_buffer.getvalue()}


def create_phase6_thread_report_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    events = store.list_phase4_trace_events(thread["id"])
    field_context = store.get_phase4_field_context(thread["field_context_id"]) if thread.get("field_context_id") else None
    feedback = store.list_phase4_feedback_for_thread(thread["id"])
    export_id = str(uuid.uuid4())
    report = build_phase6_thread_report(thread=thread, events=events, field_context=field_context, feedback=feedback)
    report["reproducibility"] = _phase6_report_reproducibility(
        thread=thread,
        events=events,
        field_context=field_context,
        feedback=feedback,
    )
    manifest = build_phase6_report_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    json_payload = json.dumps({"manifest": manifest, "report": report}, indent=2)
    markdown_payload = build_phase6_thread_report_markdown(report, manifest)
    pdf_payload = build_phase6_simple_pdf(markdown_payload)

    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", json.dumps(manifest, indent=2))
    report_object = object_store.put_text(f"phase6/{export_id}/thread_report.json", json_payload)
    markdown_object = object_store.put_text(f"phase6/{export_id}/thread_report.md", markdown_payload)
    pdf_object = object_store.put_bytes(f"phase6/{export_id}/thread_report.pdf", pdf_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "thread_report.json": _object_reference(object_store, report_object),
        "thread_report.md": _object_reference(object_store, markdown_object),
        "thread_report.pdf": _object_reference(object_store, pdf_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, json.dumps(manifest, indent=2).encode("utf-8"), "application/json"),
        "thread_report.json": _file_record(report_object.size_bytes, json_payload.encode("utf-8"), "application/json"),
        "thread_report.md": _file_record(markdown_object.size_bytes, markdown_payload.encode("utf-8"), "text/markdown"),
        "thread_report.pdf": _file_record(pdf_object.size_bytes, pdf_payload, "application/pdf"),
    }
    digest_payload = json_payload.encode("utf-8") + markdown_payload.encode("utf-8") + pdf_payload
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="thread_report",
        storage_uri=_object_parent_reference(object_store, report_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.thread_report.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def create_phase6_field_context_brief_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    events = store.list_phase4_trace_events(thread["id"])
    field_context = store.get_phase4_field_context(thread["field_context_id"]) if thread.get("field_context_id") else None
    export_id = str(uuid.uuid4())
    report = build_phase6_field_context_brief(thread=thread, events=events, field_context=field_context)
    report["reproducibility"] = _phase6_report_reproducibility(thread=thread, events=events, field_context=field_context)
    manifest = build_phase6_field_context_brief_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    markdown_payload = build_phase6_field_context_brief_markdown(report, manifest)
    pdf_payload = build_phase6_simple_pdf(markdown_payload)

    manifest_text = json.dumps(manifest, indent=2)
    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", manifest_text)
    markdown_object = object_store.put_text(f"phase6/{export_id}/field_context_brief.md", markdown_payload)
    pdf_object = object_store.put_bytes(f"phase6/{export_id}/field_context_brief.pdf", pdf_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "field_context_brief.md": _object_reference(object_store, markdown_object),
        "field_context_brief.pdf": _object_reference(object_store, pdf_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, manifest_text.encode("utf-8"), "application/json"),
        "field_context_brief.md": _file_record(markdown_object.size_bytes, markdown_payload.encode("utf-8"), "text/markdown"),
        "field_context_brief.pdf": _file_record(pdf_object.size_bytes, pdf_payload, "application/pdf"),
    }
    digest_payload = manifest_text.encode("utf-8") + markdown_payload.encode("utf-8") + pdf_payload
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="field_context_brief",
        storage_uri=_object_parent_reference(object_store, markdown_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.field_context_brief.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def create_phase6_source_evidence_bundle_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    events = store.list_phase4_trace_events(thread["id"])
    export_id = str(uuid.uuid4())
    report = build_phase6_source_evidence_bundle(thread=thread, events=events)
    report["reproducibility"] = _phase6_report_reproducibility(thread=thread, events=events)
    manifest = build_phase6_source_evidence_bundle_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    manifest_text = json.dumps(manifest, indent=2)
    json_payload = json.dumps({"manifest": manifest, "report": report}, indent=2)
    csv_payload = build_phase6_source_evidence_bundle_csv(report)
    markdown_payload = build_phase6_source_evidence_bundle_markdown(report, manifest)

    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", manifest_text)
    report_object = object_store.put_text(f"phase6/{export_id}/source_evidence_bundle.json", json_payload)
    csv_object = object_store.put_text(f"phase6/{export_id}/source_evidence_bundle.csv", csv_payload)
    markdown_object = object_store.put_text(f"phase6/{export_id}/source_evidence_bundle.md", markdown_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "source_evidence_bundle.json": _object_reference(object_store, report_object),
        "source_evidence_bundle.csv": _object_reference(object_store, csv_object),
        "source_evidence_bundle.md": _object_reference(object_store, markdown_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, manifest_text.encode("utf-8"), "application/json"),
        "source_evidence_bundle.json": _file_record(report_object.size_bytes, json_payload.encode("utf-8"), "application/json"),
        "source_evidence_bundle.csv": _file_record(csv_object.size_bytes, csv_payload.encode("utf-8"), "text/csv"),
        "source_evidence_bundle.md": _file_record(markdown_object.size_bytes, markdown_payload.encode("utf-8"), "text/markdown"),
    }
    digest_payload = manifest_text.encode("utf-8") + json_payload.encode("utf-8") + csv_payload.encode("utf-8") + markdown_payload.encode("utf-8")
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="source_evidence_bundle",
        storage_uri=_object_parent_reference(object_store, report_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.source_evidence_bundle.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def create_phase6_diagnostic_checklist_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    events = store.list_phase4_trace_events(thread["id"])
    field_context = store.get_phase4_field_context(thread["field_context_id"]) if thread.get("field_context_id") else None
    export_id = str(uuid.uuid4())
    report = build_phase6_diagnostic_checklist(thread=thread, events=events, field_context=field_context)
    report["reproducibility"] = _phase6_report_reproducibility(thread=thread, events=events, field_context=field_context)
    manifest = build_phase6_diagnostic_checklist_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    manifest_text = json.dumps(manifest, indent=2)
    csv_payload = build_phase6_diagnostic_checklist_csv(report)
    markdown_payload = build_phase6_diagnostic_checklist_markdown(report, manifest)
    pdf_payload = build_phase6_simple_pdf(markdown_payload)

    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", manifest_text)
    csv_object = object_store.put_text(f"phase6/{export_id}/diagnostic_checklist.csv", csv_payload)
    markdown_object = object_store.put_text(f"phase6/{export_id}/diagnostic_checklist.md", markdown_payload)
    pdf_object = object_store.put_bytes(f"phase6/{export_id}/diagnostic_checklist.pdf", pdf_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "diagnostic_checklist.csv": _object_reference(object_store, csv_object),
        "diagnostic_checklist.md": _object_reference(object_store, markdown_object),
        "diagnostic_checklist.pdf": _object_reference(object_store, pdf_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, manifest_text.encode("utf-8"), "application/json"),
        "diagnostic_checklist.csv": _file_record(csv_object.size_bytes, csv_payload.encode("utf-8"), "text/csv"),
        "diagnostic_checklist.md": _file_record(markdown_object.size_bytes, markdown_payload.encode("utf-8"), "text/markdown"),
        "diagnostic_checklist.pdf": _file_record(pdf_object.size_bytes, pdf_payload, "application/pdf"),
    }
    digest_payload = manifest_text.encode("utf-8") + csv_payload.encode("utf-8") + markdown_payload.encode("utf-8") + pdf_payload
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="diagnostic_checklist",
        storage_uri=_object_parent_reference(object_store, markdown_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.diagnostic_checklist.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def create_phase6_learning_trace_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    events = store.list_phase4_trace_events(thread["id"])
    feedback = store.list_phase4_feedback_for_thread(thread["id"])
    phase5_metrics = [
        metric
        for metric in store.list_phase5_turn_metrics(thread["workspace_id"], limit=5000)
        if metric.get("thread_id") == thread["id"]
    ]
    phase5_spans = [
        span
        for metric in phase5_metrics
        for span in store.list_phase5_trace_spans(metric["trace_id"])
    ]
    export_id = str(uuid.uuid4())
    report = build_phase6_learning_trace_export(
        thread=thread,
        events=events,
        feedback=feedback,
        phase5_metrics=phase5_metrics,
        phase5_spans=phase5_spans,
        redaction_status=redaction_status,
    )
    report["reproducibility"] = _phase6_report_reproducibility(
        thread=thread,
        events=events,
        feedback=feedback,
        extra_inputs={"phase5_metrics": phase5_metrics, "phase5_span_count": len(phase5_spans)},
    )
    manifest = build_phase6_learning_trace_export_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    manifest_text = json.dumps(manifest, indent=2)
    jsonl_payload = build_phase6_learning_trace_jsonl(report)

    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", manifest_text)
    jsonl_object = object_store.put_text(f"phase6/{export_id}/learning_trace_export.jsonl", jsonl_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "learning_trace_export.jsonl": _object_reference(object_store, jsonl_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, manifest_text.encode("utf-8"), "application/json"),
        "learning_trace_export.jsonl": _file_record(jsonl_object.size_bytes, jsonl_payload.encode("utf-8"), "application/x-ndjson"),
    }
    digest_payload = manifest_text.encode("utf-8") + jsonl_payload.encode("utf-8")
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="learning_trace_export",
        storage_uri=_object_parent_reference(object_store, jsonl_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.learning_trace_export.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def create_phase6_data_source_audit_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    data_sources = store.list_phase4_data_sources(thread["workspace_id"])
    ingest_jobs = store.list_phase4_ingest_jobs(thread["workspace_id"])
    chunk_counts = store.count_phase4_document_chunks_by_source(thread["workspace_id"])
    export_id = str(uuid.uuid4())
    report = build_phase6_data_source_audit(
        thread=thread,
        data_sources=data_sources,
        ingest_jobs=ingest_jobs,
        chunk_counts=chunk_counts,
    )
    report["reproducibility"] = _phase6_report_reproducibility(
        thread=thread,
        extra_inputs={"data_sources": data_sources, "ingest_jobs": ingest_jobs, "chunk_counts": chunk_counts},
    )
    manifest = build_phase6_data_source_audit_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    manifest_text = json.dumps(manifest, indent=2)
    csv_payload = build_phase6_data_source_audit_csv(report)
    pdf_payload = build_phase6_simple_pdf(build_phase6_data_source_audit_text(report, manifest))

    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", manifest_text)
    csv_object = object_store.put_text(f"phase6/{export_id}/data_source_audit.csv", csv_payload)
    pdf_object = object_store.put_bytes(f"phase6/{export_id}/data_source_audit.pdf", pdf_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "data_source_audit.csv": _object_reference(object_store, csv_object),
        "data_source_audit.pdf": _object_reference(object_store, pdf_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, manifest_text.encode("utf-8"), "application/json"),
        "data_source_audit.csv": _file_record(csv_object.size_bytes, csv_payload.encode("utf-8"), "text/csv"),
        "data_source_audit.pdf": _file_record(pdf_object.size_bytes, pdf_payload, "application/pdf"),
    }
    digest_payload = manifest_text.encode("utf-8") + csv_payload.encode("utf-8") + pdf_payload
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="data_source_audit",
        storage_uri=_object_parent_reference(object_store, csv_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.data_source_audit.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def create_phase6_demo_eval_snapshot_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    events = store.list_phase4_trace_events(thread["id"])
    eval_runs = store.list_phase4_eval_runs(thread["workspace_id"])
    eval_candidates = store.list_phase4_eval_candidates(thread["workspace_id"])
    export_id = str(uuid.uuid4())
    report = build_phase6_demo_eval_snapshot(
        thread=thread,
        events=events,
        eval_runs=eval_runs,
        eval_candidates=eval_candidates,
    )
    report["reproducibility"] = _phase6_report_reproducibility(
        thread=thread,
        events=events,
        extra_inputs={"eval_runs": eval_runs, "eval_candidates": eval_candidates},
    )
    manifest = build_phase6_demo_eval_snapshot_manifest(
        report_id=export_id,
        thread=thread,
        report=report,
        redaction_status=redaction_status,
    )
    manifest_text = json.dumps(manifest, indent=2)
    markdown_payload = build_phase6_demo_eval_snapshot_markdown(report, manifest)
    pdf_payload = build_phase6_simple_pdf(markdown_payload)

    manifest_object = object_store.put_text(f"phase6/{export_id}/phase6_report_manifest.json", manifest_text)
    markdown_object = object_store.put_text(f"phase6/{export_id}/demo_eval_snapshot.md", markdown_payload)
    pdf_object = object_store.put_bytes(f"phase6/{export_id}/demo_eval_snapshot.pdf", pdf_payload)
    files = {
        "phase6_report_manifest.json": _object_reference(object_store, manifest_object),
        "demo_eval_snapshot.md": _object_reference(object_store, markdown_object),
        "demo_eval_snapshot.pdf": _object_reference(object_store, pdf_object),
    }
    file_manifest = {
        "phase6_report_manifest.json": _file_record(manifest_object.size_bytes, manifest_text.encode("utf-8"), "application/json"),
        "demo_eval_snapshot.md": _file_record(markdown_object.size_bytes, markdown_payload.encode("utf-8"), "text/markdown"),
        "demo_eval_snapshot.pdf": _file_record(pdf_object.size_bytes, pdf_payload, "application/pdf"),
    }
    digest_payload = manifest_text.encode("utf-8") + markdown_payload.encode("utf-8") + pdf_payload
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type="demo_eval_snapshot",
        storage_uri=_object_parent_reference(object_store, markdown_object),
        redaction_status=redaction_status,
        sha256=hashlib.sha256(digest_payload).hexdigest(),
        metadata={
            "files": files,
            "manifest": manifest,
            "file_manifest": file_manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase6.demo_eval_snapshot.v1",
        },
    )
    return {"export": export, "report": report, "manifest": manifest}


def build_phase6_thread_report(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]],
    field_context: dict[str, Any] | None,
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    user_message = _latest_message(thread, "user")
    assistant_message = _latest_message(thread, "assistant")
    structured = _latest_structured_answer(thread)
    retrieval_docs = _latest_event_payload(events, "retrieval_result").get("retrieved_docs") or []
    model_context = _model_context(thread, events, structured)
    public_answer = structured.get("public_answer_markdown") or assistant_message.get("content") or ""
    return {
        "schema_version": "phase6.thread_report.v1",
        "title": thread.get("title") or "Thread report",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "Open Agronomy Agent is decision support, not a substitute for local agronomists, current labels, "
            "certified recommendations, legal requirements, or field diagnosis."
        ),
        "model_context": model_context,
        "field_context_used": structured.get("field_context_used") or _field_context_summary(field_context),
        "user_question": user_message.get("content") or "",
        "public_answer": public_answer,
        "risk_level": structured.get("risk_level") or thread.get("risk_level") or "unknown",
        "answer_type": structured.get("answer_type") or "conceptual",
        "evidence_cards": structured.get("evidence_cards") or _evidence_cards_from_docs(retrieval_docs),
        "missing_data": structured.get("missing_data_prompts") or [],
        "caveats": structured.get("caveats") or [],
        "next_steps": structured.get("recommended_next_steps") or [],
        "source_list": _source_list(structured.get("evidence_cards") or _evidence_cards_from_docs(retrieval_docs)),
        "feedback_summary": _feedback_summary(feedback),
        "system_context_footer": {
            "prompt_version": model_context.get("prompt_version"),
            "context_policy_version": model_context.get("context_policy_version"),
            "corpus_version": model_context.get("corpus_version"),
            "redaction_status": thread.get("redaction_status", "not_required"),
        },
    }


def build_phase6_source_evidence_bundle(*, thread: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_payload = _latest_event_payload(events, "retrieval_result")
    route_payload = _latest_event_payload(events, "route_result")
    kg_payload = _latest_event_payload(events, "kg_result")
    docs = [doc for doc in retrieval_payload.get("retrieved_docs") or [] if isinstance(doc, dict)]
    kg_hits = [hit for hit in kg_payload.get("graph_hits") or [] if isinstance(hit, dict)]
    source_metadata = [_source_metadata_from_doc(doc, rank=index + 1) for index, doc in enumerate(docs)]
    return {
        "schema_version": "phase6.source_evidence_bundle.v1",
        "title": f"Source Evidence Bundle - {thread.get('title') or thread['id']}",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "This bundle supports source review. It preserves public evidence metadata and relevance notes, "
            "but excludes hidden prompts, internal checklists, raw prompt messages, and trace spans."
        ),
        "model_context": _model_context(thread, events, {}),
        "retrieved_docs": source_metadata,
        "kg_hits": [_kg_hit_record(hit, rank=index + 1) for index, hit in enumerate(kg_hits)],
        "source_metadata": source_metadata,
        "license_status": _license_status_summary(source_metadata),
        "ranking_context": {
            "route_question_type": route_payload.get("question_type") or thread.get("task_family") or "unknown",
            "risk_level": route_payload.get("risk_level") or thread.get("risk_level") or "unknown",
            "namespaces": route_payload.get("namespaces") or [],
            "retrieval_doc_count": len(docs),
            "private_doc_count": int(retrieval_payload.get("private_doc_count") or 0),
            "top_doc_score": source_metadata[0].get("score") if source_metadata else None,
        },
        "excluded_internal_fields": [
            "prompt_messages",
            "coverage_checklist",
            "tool_invocations",
            "answer_plan",
            "raw_model_prompt",
            "trace_spans",
        ],
    }


def build_phase6_diagnostic_checklist(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]],
    field_context: dict[str, Any] | None,
) -> dict[str, Any]:
    structured = _latest_structured_answer(thread)
    retrieval_payload = _latest_event_payload(events, "retrieval_result")
    route_payload = _latest_event_payload(events, "route_result")
    docs = [doc for doc in retrieval_payload.get("retrieved_docs") or [] if isinstance(doc, dict)]
    quality = (
        field_context.get("quality_meter")
        if isinstance(field_context, dict) and isinstance(field_context.get("quality_meter"), dict)
        else evaluate_field_context_quality(field_context or {})
    )
    missing_data = list(structured.get("missing_data_prompts") or [])
    if not missing_data:
        missing_data = list(quality.get("missing_minimum_next_prompts") or [])
    evidence_refs = [_source_metadata_from_doc(doc, rank=index + 1) for index, doc in enumerate(docs[:8])]
    return {
        "schema_version": "phase6.diagnostic_checklist.v1",
        "title": f"Diagnostic Checklist - {thread.get('title') or thread['id']}",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "This checklist is a triage and measurement plan. It is not a diagnosis, product recommendation, "
            "rate recommendation, legal requirement, or substitute for local field review."
        ),
        "model_context": _model_context(thread, events, structured),
        "diagnostic_scope": {
            "question_type": route_payload.get("question_type") or thread.get("task_family") or structured.get("answer_type") or "unknown",
            "risk_level": route_payload.get("risk_level") or structured.get("risk_level") or thread.get("risk_level") or "unknown",
            "field_context_quality": quality.get("summary", "insufficient_context"),
        },
        "field_context_snapshot": _field_profile_for_brief(field_context),
        "triage_steps": _diagnostic_triage_steps(route_payload, structured, quality),
        "measurement_plan": _diagnostic_measurement_plan(field_context, missing_data, route_payload),
        "safety_boundaries": _diagnostic_safety_boundaries(route_payload, structured),
        "evidence_refs": evidence_refs,
        "generated_from": {
            "thread_snapshot": True,
            "hidden_prompts_excluded": True,
            "internal_checklists_excluded": True,
        },
    }


def build_phase6_learning_trace_export(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
    phase5_metrics: list[dict[str, Any]],
    phase5_spans: list[dict[str, Any]],
    redaction_status: str,
) -> dict[str, Any]:
    structured = _latest_structured_answer(thread)
    event_counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or "unknown")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    feedback_training_count = sum(1 for item in feedback if item.get("training_consent"))
    reflection_events = [
        _redacted_reflection_record(event.get("payload") or {})
        for event in events
        if event.get("event_type") in {"reflection_candidate", "reflection_review"} and isinstance(event.get("payload"), dict)
    ]
    eval_events = [
        _redacted_eval_candidate_record(event.get("payload") or {})
        for event in events
        if event.get("event_type") == "eval_candidate" and isinstance(event.get("payload"), dict)
    ]
    latest_metrics = phase5_metrics[0] if phase5_metrics else {}
    return {
        "schema_version": "phase6.learning_trace_export.v1",
        "title": f"Learning Trace Export - {thread['id']}",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "This internal reviewer export is redacted for learning review. It preserves route, retrieval, tool, "
            "model, feedback, consent, and review metadata without raw prompts, hidden instructions, or message text."
        ),
        "model_context": _model_context(thread, events, structured),
        "redacted_thread": {
            "thread_id": thread["id"],
            "workspace_id": thread["workspace_id"],
            "title_sha256": _hash_text(str(thread.get("title") or "")) if thread.get("title") else None,
            "title_redacted": True,
            "mode": thread.get("mode"),
            "task_family": thread.get("task_family"),
            "risk_level": thread.get("risk_level") or structured.get("risk_level") or latest_metrics.get("risk_level") or "unknown",
            "field_context_id": thread.get("field_context_id"),
            "trace_capture_level": thread.get("trace_capture_level", "operational"),
            "messages": [_redacted_message_record(message) for message in thread.get("messages", [])],
            "phase4_event_counts": dict(sorted(event_counts.items())),
            "phase4_events": [_redacted_trace_event(event) for event in events],
        },
        "trace_spans": {
            "turn_metrics": [_redacted_phase5_metric(metric) for metric in phase5_metrics],
            "spans": [_redacted_phase5_span(span) for span in phase5_spans],
        },
        "feedback": [_redacted_feedback_record(item) for item in feedback],
        "reflection_candidates": reflection_events,
        "consent_state": {
            "trace_capture_level": thread.get("trace_capture_level", "operational"),
            "training_eligible": bool(thread.get("training_eligible")),
            "feedback_training_consent_count": feedback_training_count,
            "feedback_count": len(feedback),
            "redaction_status": redaction_status,
            "raw_message_text_included": False,
            "hidden_prompts_excluded": True,
        },
        "review_status": {
            "human_review_statuses": sorted({str(metric.get("human_review_status") or "unreviewed") for metric in phase5_metrics}) or ["unreviewed"],
            "reflection_statuses": sorted({str(metric.get("reflection_status") or "not_created") for metric in phase5_metrics}) or ["not_created"],
            "eval_candidates": eval_events,
            "prompt_leak_flags": sorted({flag for metric in phase5_metrics for flag in (metric.get("quality_flags") or []) if "leak" in str(flag)}),
        },
        "redaction_policy": {
            "dropped_fields": [
                "message.content",
                "raw_prompt_messages",
                "raw_model_prompt",
                "hidden_instructions",
                "coverage_checklist",
                "tool_note_text",
                "human_correction_text",
                "ideal_answer_text",
            ],
            "hash_algorithm": "sha256",
        },
    }


def build_phase6_data_source_audit(
    *,
    thread: dict[str, Any],
    data_sources: list[dict[str, Any]],
    ingest_jobs: list[dict[str, Any]],
    chunk_counts: dict[str, int],
) -> dict[str, Any]:
    jobs_by_source: dict[str, list[dict[str, Any]]] = {}
    for job in ingest_jobs:
        jobs_by_source.setdefault(str(job.get("data_source_id") or ""), []).append(job)
    source_rows = [
        _data_source_audit_row(source, jobs_by_source.get(source["id"], []), int(chunk_counts.get(source["id"], 0)))
        for source in data_sources
    ]
    license_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for row in source_rows:
        license_state = str(row.get("license_state") or "unknown")
        license_counts[license_state] = license_counts.get(license_state, 0) + 1
        source_kind = str(row.get("source_kind") or "unknown")
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        for issue in row.get("gap_flags") or []:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    if not source_rows:
        issue_counts["no_data_sources"] = 1
    return {
        "schema_version": "phase6.data_source_audit.v1",
        "title": f"Data Source Audit - {thread['workspace_id']}",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "This audit summarizes workspace data-source coverage, license posture, ingest state, and gaps. "
            "It is source-governance evidence, not agronomic advice."
        ),
        "model_context": _model_context(thread, [], {}),
        "source_coverage": {
            "source_count": len(source_rows),
            "rag_eligible_count": sum(1 for row in source_rows if row.get("rag_eligible")),
            "sft_eligible_count": sum(1 for row in source_rows if row.get("sft_eligible")),
            "indexed_chunk_count": sum(int(row.get("chunk_count") or 0) for row in source_rows),
            "source_kind_counts": dict(sorted(source_kind_counts.items())),
        },
        "license_status": dict(sorted(license_counts.items())) or {"none_recorded": 0},
        "update_dates": {
            "newest_source_update": max((str(row.get("updated_at") or "") for row in source_rows), default=""),
            "oldest_source_update": min((str(row.get("updated_at") or "") for row in source_rows if row.get("updated_at")), default=""),
            "latest_ingest_finished": max((str(row.get("latest_ingest_finished_at") or "") for row in source_rows), default=""),
        },
        "gaps": {
            "issue_counts": dict(sorted(issue_counts.items())),
            "sources_with_gaps": [row["source_id"] for row in source_rows if row.get("gap_flags")],
        },
        "source_card_fields": [
            "title",
            "publisher",
            "url_or_source_id",
            "source_type",
            "region_crop",
            "license_status",
            "updated_or_ingested_date",
            "why_used",
            "known_limitations",
        ],
        "sources": source_rows,
        "excluded_fields": [
            "metadata.text_content",
            "raw_document_text",
            "embedding_vectors",
            "private_upload_bytes",
            "internal_ingest_logs",
        ],
    }


def build_phase6_demo_eval_snapshot(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]],
    eval_runs: list[dict[str, Any]],
    eval_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    completed_runs = [run for run in eval_runs if run.get("status") == "completed"]
    latest_run = completed_runs[0] if completed_runs else None
    latest_metrics = latest_run.get("metrics", {}) if latest_run else {}
    latest_gates = latest_run.get("gates", {}) if latest_run else {}
    candidate_status_counts = _counts_by_key(eval_candidates, "review_status")
    promotion_ready_runs = sum(1 for run in completed_runs if (run.get("gates") or {}).get("promotion_allowed"))
    regression_failure_count = sum(int((run.get("metrics") or {}).get("failure_case_count") or 0) for run in completed_runs)
    limitations = _demo_eval_limitations(completed_runs=completed_runs, latest_gates=latest_gates)
    model_context = _model_context(thread, events, {})
    corpus_audit_id = (
        (latest_run.get("metadata") or {}).get("corpus_audit_id")
        if latest_run
        else None
    )
    return {
        "schema_version": "phase6.demo_eval_snapshot.v1",
        "title": f"Demo Eval Snapshot - {thread['workspace_id']}",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "This public-demo snapshot is a redacted readiness summary. It is not an independent benchmark, "
            "not a product claim, and not a substitute for local agronomy review."
        ),
        "model_context": model_context,
        "eval_summary": {
            "eval_run_count": len(eval_runs),
            "completed_eval_run_count": len(completed_runs),
            "promotion_ready_run_count": promotion_ready_runs,
            "reviewed_candidate_count": sum(
                int(candidate_status_counts.get(status, 0))
                for status in ("approved_for_suite", "promoted")
            ),
            "candidate_status_counts": candidate_status_counts,
            "latest_candidate_count": int(latest_metrics.get("candidate_count") or 0),
            "latest_pass_rate": float(latest_metrics.get("pass_rate") or 0.0),
            "latest_failure_case_count": int(latest_metrics.get("failure_case_count") or 0),
            "regression_failure_count": regression_failure_count,
            "public_claim": (
                "No public quality claim is supported yet."
                if not completed_runs or not promotion_ready_runs
                else "At least one local trace-feedback regression run met the current promotion gate."
            ),
        },
        "model_and_corpus_versions": {
            "model_id": model_context.get("model_id") or "unknown",
            "prompt_version": model_context.get("prompt_version") or "unknown",
            "context_policy_version": model_context.get("context_policy_version") or "unknown",
            "corpus_version": corpus_audit_id or model_context.get("corpus_version") or "unknown",
            "eval_suite": latest_gates.get("regression_suite") or "local_trace_feedback_regression_v1",
        },
        "gate_status": {
            "latest_eval_run_status": latest_run.get("status") if latest_run else "missing",
            "promotion_allowed": bool(latest_gates.get("promotion_allowed")) if latest_run else False,
            "reasons": list(latest_gates.get("reasons") or ["no_completed_eval_runs"]),
            "requires_reviewed_candidates": bool(latest_gates.get("requires_reviewed_candidates", True)),
            "requires_passing_regression": bool(latest_gates.get("requires_passing_regression", True)),
            "requires_ideal_answers": bool(latest_gates.get("requires_ideal_answers", True)),
        },
        "included_eval_runs": [_demo_eval_run_record(run) for run in eval_runs[:10]],
        "limitations": limitations,
        "generated_from": {
            "workspace_eval_runs": True,
            "candidate_text_redacted": True,
            "hidden_prompts_excluded": True,
            "raw_trace_spans_excluded": True,
            "source": "phase4_eval_runs_and_candidates",
        },
    }


def build_phase6_field_context_brief(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]],
    field_context: dict[str, Any] | None,
) -> dict[str, Any]:
    model_context = _model_context(thread, events, {})
    quality = (
        field_context.get("quality_meter")
        if isinstance(field_context, dict) and isinstance(field_context.get("quality_meter"), dict)
        else evaluate_field_context_quality(field_context or {})
    )
    region_text = (field_context or {}).get("region_text") or ""
    return {
        "schema_version": "phase6.field_context_brief.v1",
        "title": f"Field Context Brief - {(field_context or {}).get('display_name') or thread.get('title') or 'Unattached profile'}",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": _now(),
        "disclaimer": (
            "This field context brief is planning support. It does not create a diagnosis, product recommendation, "
            "rate recommendation, legal requirement, or substitute for local agronomy review."
        ),
        "model_context": model_context,
        "field_profile": _field_profile_for_brief(field_context),
        "regional_prior": {
            "region_text": region_text,
            "source": "user_entered_field_profile" if region_text else "not_available",
            "used_as_prior_only": True,
            "notice": "Regional context is a prior for discussion, not a field-specific fact.",
        },
        "soil_water_context": _soil_water_context(field_context),
        "known_unknowns": _known_unknowns(field_context, quality),
        "data_quality_meter": quality,
        "next_measurements": _next_measurements(quality),
    }


def build_phase6_report_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    evidence_refs = [str(card.get("doc_id")) for card in report.get("evidence_cards", []) if card.get("doc_id")]
    return {
        "report_id": report_id,
        "report_type": "thread_report",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["pdf", "markdown", "json"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": bool(thread.get("training_eligible")),
            "redaction_status": redaction_status,
            "shareable": False,
            "training_candidate_allowed": bool(thread.get("training_eligible")),
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("field_context_used", "Field Context Used", "public_user", "user_entered_field_data"),
            _report_section("user_question", "User Question", "public_user", "user_entered_field_data"),
            _report_section("public_answer", "Public Answer", "public_user", "generated_text"),
            _report_section("evidence_cards", "Evidence Cards", "public_user", "retrieved_evidence", source_refs=evidence_refs),
            _report_section("missing_data", "What Is Missing", "public_user", "generated_text"),
            _report_section("caveats", "Caveats", "public_user", "generated_text"),
            _report_section("next_steps", "Next Steps", "public_user", "generated_text"),
            _report_section("source_list", "Source List", "public_user", "retrieved_evidence", source_refs=evidence_refs),
            _report_section("system_context_footer", "System Context", "public_user", "system_metadata"),
        ],
    }


def build_phase6_source_evidence_bundle_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    refs = [str(doc.get("doc_id")) for doc in report.get("retrieved_docs", []) if doc.get("doc_id")]
    return {
        "report_id": report_id,
        "report_type": "source_evidence_bundle",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["json", "csv", "markdown"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": bool(report["ranking_context"].get("private_doc_count")),
            "redaction_status": redaction_status,
            "shareable": False,
            "training_candidate_allowed": False,
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("retrieved_docs", "Retrieved Documents", "workspace_admin", "retrieved_evidence", source_refs=refs),
            _report_section("kg_hits", "Knowledge Graph Hits", "workspace_admin", "retrieved_evidence"),
            _report_section("source_metadata", "Source Metadata", "workspace_admin", "system_metadata", source_refs=refs),
            _report_section("license_status", "License Status", "workspace_admin", "system_metadata", source_refs=refs),
            _report_section("ranking_context", "Ranking Context", "workspace_admin", "system_metadata"),
            _report_section("excluded_internal_fields", "Excluded Internal Fields", "workspace_admin", "system_metadata"),
        ],
    }


def build_phase6_diagnostic_checklist_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    refs = [str(doc.get("doc_id")) for doc in report.get("evidence_refs", []) if doc.get("doc_id")]
    return {
        "report_id": report_id,
        "report_type": "diagnostic_checklist",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["pdf", "markdown", "csv"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": bool(report["field_context_snapshot"].get("attached")),
            "redaction_status": redaction_status,
            "shareable": False,
            "training_candidate_allowed": bool(thread.get("training_eligible")),
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("diagnostic_scope", "Diagnostic Scope", "public_user", "generated_text"),
            _report_section("field_context_snapshot", "Field Context Snapshot", "public_user", "user_entered_field_data"),
            _report_section("triage_steps", "Triage Steps", "public_user", "generated_text"),
            _report_section("measurement_plan", "Measurement Plan", "public_user", "generated_text"),
            _report_section("safety_boundaries", "Safety Boundaries", "public_user", "generated_text"),
            _report_section("evidence_refs", "Evidence References", "public_user", "retrieved_evidence", source_refs=refs),
            _report_section("generated_from", "Generation Provenance", "public_user", "system_metadata"),
        ],
    }


def build_phase6_learning_trace_export_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "report_type": "learning_trace_export",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["jsonl"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": True,
            "redaction_status": redaction_status,
            "shareable": False,
            "training_candidate_allowed": bool(report["consent_state"].get("training_eligible"))
            and bool(report["consent_state"].get("feedback_training_consent_count")),
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("redacted_thread", "Redacted Thread", "internal_reviewer", "user_entered_field_data"),
            _report_section("trace_spans", "Trace Spans", "internal_reviewer", "internal_trace"),
            _report_section("feedback", "Feedback", "internal_reviewer", "user_entered_field_data"),
            _report_section("reflection_candidates", "Reflection Candidates", "internal_reviewer", "generated_text"),
            _report_section("consent_state", "Consent State", "internal_reviewer", "system_metadata"),
            _report_section("review_status", "Review Status", "internal_reviewer", "system_metadata"),
        ],
    }


def build_phase6_data_source_audit_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    refs = [str(source.get("source_id")) for source in report.get("sources", []) if source.get("source_id")]
    return {
        "report_id": report_id,
        "report_type": "data_source_audit",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["pdf", "csv"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": False,
            "redaction_status": redaction_status,
            "shareable": False,
            "training_candidate_allowed": False,
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("source_coverage", "Source Coverage", "workspace_admin", "system_metadata", source_refs=refs),
            _report_section("license_status", "License Status", "workspace_admin", "system_metadata", source_refs=refs),
            _report_section("update_dates", "Update Dates", "workspace_admin", "system_metadata", source_refs=refs),
            _report_section("gaps", "Gaps", "workspace_admin", "generated_text", source_refs=refs),
            _report_section("sources", "Sources", "workspace_admin", "retrieved_evidence", source_refs=refs),
            _report_section("excluded_fields", "Excluded Fields", "workspace_admin", "system_metadata"),
        ],
    }


def build_phase6_demo_eval_snapshot_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "report_type": "demo_eval_snapshot",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["pdf", "markdown"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": False,
            "redaction_status": redaction_status,
            "shareable": True,
            "training_candidate_allowed": False,
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("eval_summary", "Eval Summary", "public_user", "generated_text"),
            _report_section("model_and_corpus_versions", "Model and Corpus Versions", "public_user", "system_metadata"),
            _report_section("gate_status", "Gate Status", "public_user", "system_metadata"),
            _report_section("included_eval_runs", "Included Eval Runs", "public_user", "system_metadata"),
            _report_section("limitations", "Limitations", "public_user", "generated_text"),
            _report_section("generated_from", "Generation Provenance", "public_user", "system_metadata"),
        ],
    }


def build_phase6_field_context_brief_manifest(
    *,
    report_id: str,
    thread: dict[str, Any],
    report: dict[str, Any],
    redaction_status: str,
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "report_type": "field_context_brief",
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "created_at": report["created_at"],
        "formats": ["pdf", "markdown"],
        "model_context": report["model_context"],
        "data_policy": {
            "contains_user_private_data": bool(report["field_profile"].get("attached")),
            "redaction_status": redaction_status,
            "shareable": False,
            "training_candidate_allowed": bool(thread.get("training_eligible")),
        },
        "reproducibility": report.get("reproducibility", _phase6_report_reproducibility(thread=thread)),
        "sections": [
            _report_section("field_profile", "Field Profile", "public_user", "user_entered_field_data"),
            _report_section("regional_prior", "Regional Prior", "public_user", "retrieved_regional_prior"),
            _report_section("soil_water_context", "Soil and Water Context", "public_user", "mixed"),
            _report_section("known_unknowns", "Known Unknowns", "public_user", "mixed"),
            _report_section("data_quality_meter", "Data Quality Meter", "public_user", "generated_text"),
            _report_section("next_measurements", "Next Measurements", "public_user", "generated_text"),
        ],
    }


def _report_section(
    section_id: str,
    title: str,
    visibility: str,
    data_origin: str,
    *,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    section = {
        "section_id": section_id,
        "title": title,
        "visibility": visibility,
        "data_origin": data_origin,
    }
    if source_refs is not None:
        section["source_refs"] = source_refs
    return section


def build_phase6_thread_report_markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Report ID: `{manifest['report_id']}`",
        f"Thread ID: `{report['thread_id']}`",
        f"Created: {report['created_at']}",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Field Context Used",
    ]
    if report["field_context_used"]:
        for item in report["field_context_used"]:
            lines.append(f"- {item.get('field')}: {item.get('value')} ({item.get('source', 'unknown')})")
    else:
        lines.append("- No reusable field profile was attached to this thread.")
    lines.extend(["", "## Question", "", str(report["user_question"]), "", "## Answer", "", str(report["public_answer"])])
    lines.extend(["", "## Evidence"])
    for card in report["evidence_cards"]:
        lines.append(f"- [{card.get('doc_id')}] {card.get('title')} - {card.get('source') or card.get('publisher')} ({card.get('source_type')})")
    if not report["evidence_cards"]:
        lines.append("- No evidence cards were available.")
    _append_list_section(lines, "What Is Missing", report["missing_data"])
    _append_list_section(lines, "Caveats", report["caveats"])
    _append_list_section(lines, "Next Steps", report["next_steps"])
    lines.extend(["", "## System Context"])
    footer = report["system_context_footer"]
    for key in ("prompt_version", "context_policy_version", "corpus_version", "redaction_status"):
        lines.append(f"- {key}: {footer.get(key) or 'unknown'}")
    return "\n".join(lines).strip() + "\n"


def build_phase6_source_evidence_bundle_csv(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["row_type", "rank", "id", "title", "source", "source_type", "license_status", "score", "note"],
        lineterminator="\n",
    )
    writer.writeheader()
    for doc in report["retrieved_docs"]:
        writer.writerow(
            {
                "row_type": "retrieved_doc",
                "rank": doc.get("rank"),
                "id": doc.get("doc_id"),
                "title": doc.get("title"),
                "source": doc.get("source"),
                "source_type": doc.get("source_type"),
                "license_status": doc.get("license_status"),
                "score": doc.get("score"),
                "note": doc.get("relevance_note"),
            }
        )
    for hit in report["kg_hits"]:
        writer.writerow(
            {
                "row_type": "kg_hit",
                "rank": hit.get("rank"),
                "id": hit.get("node_id"),
                "title": hit.get("name"),
                "source": "knowledge_graph",
                "source_type": hit.get("kind"),
                "license_status": "n/a",
                "score": "",
                "note": hit.get("evidence"),
            }
        )
    return buffer.getvalue()


def build_phase6_source_evidence_bundle_markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Report ID: `{manifest['report_id']}`",
        f"Thread ID: `{report['thread_id']}`",
        f"Created: {report['created_at']}",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Retrieved Documents",
    ]
    for doc in report["retrieved_docs"]:
        lines.append(
            f"- {doc.get('rank')}. [{doc.get('doc_id')}] {doc.get('title')} - "
            f"{doc.get('source')} ({doc.get('source_type')}, {doc.get('license_status')}, score {doc.get('score')})"
        )
    if not report["retrieved_docs"]:
        lines.append("- No retrieved documents were recorded.")
    lines.extend(["", "## Knowledge Graph Hits"])
    for hit in report["kg_hits"]:
        lines.append(f"- {hit.get('rank')}. {hit.get('name')} ({hit.get('kind')}): {hit.get('evidence')}")
    if not report["kg_hits"]:
        lines.append("- No knowledge graph hits were recorded.")
    lines.extend(["", "## License Status"])
    _append_key_values(lines, report["license_status"])
    lines.extend(["", "## Ranking Context"])
    _append_key_values(lines, report["ranking_context"])
    lines.extend(["", "## Excluded Internal Fields"])
    _append_list(lines, report["excluded_internal_fields"])
    return "\n".join(lines).strip() + "\n"


def build_phase6_diagnostic_checklist_csv(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["section", "sequence", "item", "why", "evidence_ref"],
        lineterminator="\n",
    )
    writer.writeheader()
    for idx, step in enumerate(report["triage_steps"], 1):
        writer.writerow(
            {
                "section": "triage_steps",
                "sequence": idx,
                "item": step.get("action"),
                "why": step.get("why"),
                "evidence_ref": step.get("evidence_ref") or "",
            }
        )
    for idx, item in enumerate(report["measurement_plan"], 1):
        writer.writerow(
            {
                "section": "measurement_plan",
                "sequence": idx,
                "item": item.get("measurement"),
                "why": item.get("reason"),
                "evidence_ref": "",
            }
        )
    for idx, item in enumerate(report["safety_boundaries"], 1):
        writer.writerow(
            {
                "section": "safety_boundaries",
                "sequence": idx,
                "item": item,
                "why": "Keep the checklist inside public-demo advice boundaries.",
                "evidence_ref": "",
            }
        )
    return buffer.getvalue()


def build_phase6_diagnostic_checklist_markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Report ID: `{manifest['report_id']}`",
        f"Thread ID: `{report['thread_id']}`",
        f"Created: {report['created_at']}",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Diagnostic Scope",
    ]
    _append_key_values(lines, report["diagnostic_scope"])
    lines.extend(["", "## Triage Steps"])
    for step in report["triage_steps"]:
        evidence = f" Evidence: {step['evidence_ref']}." if step.get("evidence_ref") else ""
        lines.append(f"- {step['action']} Why: {step['why']}.{evidence}")
    lines.extend(["", "## Measurement Plan"])
    for item in report["measurement_plan"]:
        lines.append(f"- {item['measurement']}: {item['reason']}")
    lines.extend(["", "## Safety Boundaries"])
    _append_list(lines, report["safety_boundaries"])
    lines.extend(["", "## Evidence References"])
    for ref in report["evidence_refs"]:
        lines.append(f"- [{ref.get('doc_id')}] {ref.get('title')} ({ref.get('source')})")
    if not report["evidence_refs"]:
        lines.append("- No evidence references were recorded.")
    lines.extend(["", "## Generated From"])
    _append_key_values(lines, report["generated_from"])
    return "\n".join(lines).strip() + "\n"


def build_phase6_learning_trace_jsonl(report: dict[str, Any]) -> str:
    records = [
        ("redacted_thread", report["redacted_thread"]),
        ("trace_spans", report["trace_spans"]),
        ("feedback", report["feedback"]),
        ("reflection_candidates", report["reflection_candidates"]),
        ("consent_state", report["consent_state"]),
        ("review_status", report["review_status"]),
    ]
    lines = []
    for sequence, (record_type, payload) in enumerate(records, 1):
        lines.append(
            json.dumps(
                {
                    "schema_version": report["schema_version"],
                    "record_type": record_type,
                    "sequence": sequence,
                    "thread_id": report["thread_id"],
                    "workspace_id": report["workspace_id"],
                    "created_at": report["created_at"],
                    "payload": payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "\n".join(lines) + "\n"


def build_phase6_data_source_audit_csv(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "source_id",
            "title",
            "publisher",
            "source_kind",
            "source_type",
            "license_state",
            "license_status",
            "rag_eligible",
            "sft_eligible",
            "chunk_count",
            "latest_ingest_status",
            "latest_ingest_finished_at",
            "gap_flags",
            "crops",
            "regions",
            "region_crop",
            "buckets",
            "canonical_url",
            "url_or_source_id",
            "updated_or_ingested_date",
            "why_used",
            "known_limitations",
            "updated_at",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for source in report["sources"]:
        writer.writerow(
            {
                "source_id": source.get("source_id"),
                "title": source.get("title"),
                "publisher": source.get("publisher") or "",
                "source_kind": source.get("source_kind"),
                "source_type": source.get("source_type"),
                "license_state": source.get("license_state"),
                "license_status": source.get("license_status"),
                "rag_eligible": source.get("rag_eligible"),
                "sft_eligible": source.get("sft_eligible"),
                "chunk_count": source.get("chunk_count"),
                "latest_ingest_status": source.get("latest_ingest_status"),
                "latest_ingest_finished_at": source.get("latest_ingest_finished_at") or "",
                "gap_flags": "|".join(source.get("gap_flags") or []),
                "crops": "|".join(source.get("crops") or []),
                "regions": "|".join(source.get("regions") or []),
                "region_crop": source.get("region_crop") or "",
                "buckets": "|".join(source.get("buckets") or []),
                "canonical_url": source.get("canonical_url") or "",
                "url_or_source_id": source.get("url_or_source_id") or "",
                "updated_or_ingested_date": source.get("updated_or_ingested_date") or "",
                "why_used": source.get("why_used") or "",
                "known_limitations": source.get("known_limitations") or "",
                "updated_at": source.get("updated_at") or "",
            }
        )
    return buffer.getvalue()


def build_phase6_data_source_audit_text(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Report ID: `{manifest['report_id']}`",
        f"Workspace ID: `{report['workspace_id']}`",
        f"Created: {report['created_at']}",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Source Coverage",
    ]
    _append_key_values(lines, report["source_coverage"])
    lines.extend(["", "## License Status"])
    _append_key_values(lines, report["license_status"])
    lines.extend(["", "## Update Dates"])
    _append_key_values(lines, report["update_dates"])
    lines.extend(["", "## Gaps"])
    _append_key_values(lines, report["gaps"]["issue_counts"])
    lines.extend(["", "## Sources"])
    lines.extend(["", "Source-card fields covered: " + ", ".join(report.get("source_card_fields") or [])])
    for source in report["sources"]:
        gaps = ", ".join(source.get("gap_flags") or []) or "none"
        lines.append(
            f"- {source.get('source_id')}: {source.get('title')} "
            f"({source.get('license_status')}, {source.get('region_crop')}, chunks {source.get('chunk_count')}, gaps {gaps}). "
            f"Why used: {source.get('why_used')}. Limits: {source.get('known_limitations')}."
        )
    if not report["sources"]:
        lines.append("- No data sources are registered for this workspace.")
    lines.extend(["", "## Excluded Fields"])
    _append_list(lines, report["excluded_fields"])
    return "\n".join(lines).strip() + "\n"


def build_phase6_demo_eval_snapshot_markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Report ID: `{manifest['report_id']}`",
        f"Workspace ID: `{report['workspace_id']}`",
        f"Created: {report['created_at']}",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Eval Summary",
    ]
    _append_key_values(lines, report["eval_summary"])
    lines.extend(["", "## Model and Corpus Versions"])
    _append_key_values(lines, report["model_and_corpus_versions"])
    lines.extend(["", "## Gate Status"])
    _append_key_values(lines, report["gate_status"])
    lines.extend(["", "## Included Eval Runs"])
    for run in report["included_eval_runs"]:
        reasons = ", ".join(run.get("gate_reasons") or []) or "none"
        lines.append(
            f"- {run.get('name')} ({run.get('status')}): {run.get('candidate_count')} candidates, "
            f"pass rate {run.get('pass_rate')}, promotion allowed {run.get('promotion_allowed')}, reasons {reasons}"
        )
    if not report["included_eval_runs"]:
        lines.append("- No reviewed eval runs are available.")
    lines.extend(["", "## Limitations"])
    _append_list(lines, report["limitations"])
    lines.extend(["", "## Generated From"])
    _append_key_values(lines, report["generated_from"])
    return "\n".join(lines).strip() + "\n"


def build_phase6_field_context_brief_markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"Report ID: `{manifest['report_id']}`",
        f"Thread ID: `{report['thread_id']}`",
        f"Created: {report['created_at']}",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Field Profile",
    ]
    profile = report["field_profile"]
    if profile.get("attached"):
        for key, value in profile["user_entered_fields"].items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- No reusable field profile was attached to this thread.")
    lines.extend(["", "## Regional Prior"])
    regional = report["regional_prior"]
    lines.append(f"- Region: {regional.get('region_text') or 'not provided'}")
    lines.append(f"- Notice: {regional['notice']}")
    lines.extend(["", "## Soil and Water Context"])
    _append_key_values(lines, report["soil_water_context"])
    lines.extend(["", "## Known Unknowns"])
    _append_list(lines, report["known_unknowns"])
    lines.extend(["", "## Data Quality Meter"])
    meter = report["data_quality_meter"]
    lines.append(f"- Summary: {meter['summary']}")
    for check in meter["checks"]:
        missing = ", ".join(check.get("missing_fields") or []) or "none"
        lines.append(f"- {check['label']}: {check['status']} (missing: {missing})")
    lines.extend(["", "## Next Measurements"])
    _append_list(lines, report["next_measurements"])
    lines.extend(["", "## System Context"])
    for key, value in report["model_context"].items():
        lines.append(f"- {key}: {value or 'unknown'}")
    return "\n".join(lines).strip() + "\n"


def build_phase6_simple_pdf(text: str) -> bytes:
    safe_lines = [_pdf_escape(line[:110]) for line in text.splitlines()[:44]]
    stream_lines = ["BT /F1 10 Tf 50 760 Td 14 TL"]
    for line in safe_lines:
        stream_lines.append(f"({line}) Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("utf-8")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{idx} 0 obj\n".encode("ascii"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return output.getvalue()


def _file_record(size_bytes: int, payload: bytes, content_type: str) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": size_bytes, "content_type": content_type}


def build_phase4_zip_thread_export(
    *,
    trace_payload: str,
    markdown_payload: str,
    csv_payloads: dict[str, str],
    manifest: dict[str, Any],
) -> bytes:
    """Create a deterministic ZIP bundle for hosted thread export artifacts."""

    buffer = io.BytesIO()
    zip_timestamp = (2026, 1, 1, 0, 0, 0)
    files = {
        "thread_trace.json": trace_payload.encode("utf-8"),
        "thread.md": markdown_payload.encode("utf-8"),
        **{name: payload.encode("utf-8") for name, payload in csv_payloads.items()},
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
    }
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(filename=name, date_time=zip_timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def create_phase4_thread_export(
    *,
    store: Any,
    object_store: Any,
    thread: dict[str, Any],
    created_by_user_id: str,
    export_type: str,
    redaction_status: str,
    storage_backend: str,
) -> dict[str, Any]:
    if export_type == "thread_report":
        return create_phase6_thread_report_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    if export_type == "field_context_brief":
        return create_phase6_field_context_brief_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    if export_type == "source_evidence_bundle":
        return create_phase6_source_evidence_bundle_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    if export_type == "diagnostic_checklist":
        return create_phase6_diagnostic_checklist_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    if export_type == "learning_trace_export":
        return create_phase6_learning_trace_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    if export_type == "data_source_audit":
        return create_phase6_data_source_audit_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    if export_type == "demo_eval_snapshot":
        return create_phase6_demo_eval_snapshot_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=created_by_user_id,
            redaction_status=redaction_status,
            storage_backend=storage_backend,
        )
    events = store.list_phase4_trace_events(thread["id"])
    field_context = store.get_phase4_field_context(thread["field_context_id"]) if thread.get("field_context_id") else None
    feedback = store.list_phase4_feedback_for_thread(thread["id"])
    bundle = build_phase4_thread_trace_bundle(thread=thread, events=events, field_context=field_context, feedback=feedback)
    export_id = str(uuid.uuid4())
    trace_payload = json.dumps(bundle, indent=2)
    markdown_payload = build_phase4_markdown_thread_export(thread, events)
    csv_payloads = build_phase4_csv_thread_exports(thread, events)
    trace_object = object_store.put_text(f"phase4/{export_id}/thread_trace.json", trace_payload)
    markdown_object = object_store.put_text(f"phase4/{export_id}/thread.md", markdown_payload)
    manifest = {
        "schema_version": "phase4.thread_export_manifest.v1",
        "export_id": export_id,
        "export_type": export_type,
        "thread_id": thread["id"],
        "workspace_id": thread["workspace_id"],
        "organization_id": thread["organization_id"],
        "redaction_status": redaction_status,
        "files": {
            "thread_trace.json": {
                "sha256": hashlib.sha256(trace_payload.encode("utf-8")).hexdigest(),
                "size_bytes": trace_object.size_bytes,
                "content_type": "application/json",
            },
            "thread.md": {
                "sha256": hashlib.sha256(markdown_payload.encode("utf-8")).hexdigest(),
                "size_bytes": markdown_object.size_bytes,
                "content_type": "text/markdown",
            },
        },
    }
    stored_files = {
        "thread_trace.json": _object_reference(object_store, trace_object),
        "thread.md": _object_reference(object_store, markdown_object),
    }
    csv_digest_payload = b""
    if export_type in {"csv", "zip"}:
        for name, payload in csv_payloads.items():
            csv_object = object_store.put_text(f"phase4/{export_id}/{name}", payload)
            manifest["files"][name] = {
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "size_bytes": csv_object.size_bytes,
                "content_type": "text/csv",
            }
            stored_files[name] = _object_reference(object_store, csv_object)
            csv_digest_payload += payload.encode("utf-8")
    zip_payload = b""
    if export_type == "zip":
        zip_payload = build_phase4_zip_thread_export(
            trace_payload=trace_payload,
            markdown_payload=markdown_payload,
            csv_payloads=csv_payloads,
            manifest=manifest,
        )
        zip_object = object_store.put_bytes(f"phase4/{export_id}/thread_bundle.zip", zip_payload)
        manifest["files"]["thread_bundle.zip"] = {
            "sha256": hashlib.sha256(zip_payload).hexdigest(),
            "size_bytes": zip_object.size_bytes,
            "content_type": "application/zip",
        }
        stored_files["thread_bundle.zip"] = _object_reference(object_store, zip_object)
    export_uri = _object_parent_reference(object_store, trace_object)
    digest_payload = trace_payload.encode("utf-8") + markdown_payload.encode("utf-8") + csv_digest_payload + zip_payload
    digest = hashlib.sha256(digest_payload).hexdigest()
    export = store.create_phase4_export(
        thread=thread,
        created_by_user_id=created_by_user_id,
        export_type=export_type,
        storage_uri=export_uri,
        redaction_status=redaction_status,
        sha256=digest,
        metadata={
            "files": stored_files,
            "manifest": manifest,
            "storage_backend": storage_backend,
            "schema_version": "phase4.thread_trace.v1",
        },
    )
    return {"export": export, "trace": bundle}


def run_phase4_export_job(
    *,
    store: Any,
    object_store: Any,
    job_id: str,
    storage_backend: str,
    worker_name: str = "local_worker",
) -> dict[str, Any]:
    job = store.get_phase4_export_job(job_id)
    if not job:
        raise ValueError(f"export job not found: {job_id}")
    thread = store.get_phase4_thread(job["thread_id"])
    if not thread:
        return store.update_phase4_export_job(
            job_id=job_id,
            status="failed",
            result={"worker": worker_name},
            error_message="thread not found",
            finished_at=_now(),
        ) or {}
    store.update_phase4_export_job(
        job_id=job_id,
        status="running",
        result={**job.get("result", {}), "worker": worker_name},
        started_at=_now(),
    )
    try:
        created = create_phase4_thread_export(
            store=store,
            object_store=object_store,
            thread=thread,
            created_by_user_id=job["created_by_user_id"],
            export_type=job["export_type"],
            redaction_status=job["redaction_status"],
            storage_backend=storage_backend,
        )
    except Exception as exc:
        return store.update_phase4_export_job(
            job_id=job_id,
            status="failed",
            result={"worker": worker_name, "unhandled_error": exc.__class__.__name__},
            error_message=str(exc),
            finished_at=_now(),
        ) or {}
    export = created["export"]
    return store.update_phase4_export_job(
        job_id=job_id,
        status="completed",
        export_id=export["id"],
        result={"worker": worker_name, "export_id": export["id"], "sha256": export.get("sha256")},
        error_message=None,
        finished_at=_now(),
    ) or {}


def run_queued_phase4_export_jobs(
    *,
    store: Any,
    object_store: Any,
    storage_backend: str,
    limit: int = 1,
    worker_name: str = "local_worker",
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be > 0")
    jobs = store.list_phase4_queued_export_jobs(limit=limit)
    return run_phase4_export_job_ids(
        store=store,
        object_store=object_store,
        storage_backend=storage_backend,
        job_ids=[job["id"] for job in jobs],
        requested_limit=limit,
        worker_name=worker_name,
        queue_name="exports",
    )


def run_phase4_export_job_ids(
    *,
    store: Any,
    object_store: Any,
    storage_backend: str,
    job_ids: list[str],
    requested_limit: int,
    worker_name: str = "local_worker",
    queue_name: str = "exports",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for job_id in job_ids:
        try:
            result = run_phase4_export_job(
                store=store,
                object_store=object_store,
                job_id=job_id,
                storage_backend=storage_backend,
                worker_name=worker_name,
            )
        except Exception as exc:
            result = store.update_phase4_export_job(
                job_id=job_id,
                status="failed",
                result={"worker": worker_name, "unhandled_error": exc.__class__.__name__},
                error_message=str(exc),
                finished_at=_now(),
            ) or {"id": job_id, "status": "failed"}
        results.append(result)
    return {
        "queue": queue_name,
        "worker": worker_name,
        "requested_limit": requested_limit,
        "processed": len(results),
        "completed": sum(1 for item in results if item.get("status") == "completed"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "job_ids": [item.get("id") for item in results],
    }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _phase6_report_reproducibility(
    *,
    thread: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
    field_context: dict[str, Any] | None = None,
    feedback: list[dict[str, Any]] | None = None,
    extra_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_list = list(events or [])
    feedback_list = list(feedback or [])
    messages = [message for message in thread.get("messages", []) if isinstance(message, dict)]
    event_type_counts: dict[str, int] = {}
    for event in event_list:
        event_type = str(event.get("event_type") or "unknown")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
    snapshot = {
        "thread": {
            "id": thread.get("id"),
            "workspace_id": thread.get("workspace_id"),
            "organization_id": thread.get("organization_id"),
            "mode": thread.get("mode"),
            "task_family": thread.get("task_family"),
            "risk_level": thread.get("risk_level"),
            "field_context_id": thread.get("field_context_id"),
            "model_profile_id": thread.get("model_profile_id"),
            "rag_config_id": thread.get("rag_config_id"),
            "created_at": thread.get("created_at"),
            "updated_at": thread.get("updated_at"),
            "title_sha256": _hash_text(str(thread.get("title") or "")) if thread.get("title") else None,
            "message_hashes": [
                _hash_payload(
                    {
                        "id": message.get("id"),
                        "sequence_no": message.get("sequence_no"),
                        "actor": message.get("actor"),
                        "created_at": message.get("created_at"),
                        "content_sha256": _hash_text(str(message.get("content") or "")),
                        "metadata_sha256": _hash_payload(message.get("metadata") or {}),
                    }
                )
                for message in messages
            ],
        },
        "events": [
            _hash_payload(
                {
                    "id": event.get("id") or event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "actor": event.get("actor"),
                    "created_at": event.get("created_at"),
                    "payload_sha256": _hash_payload(event.get("payload") or {}),
                }
            )
            for event in event_list
            if isinstance(event, dict)
        ],
        "field_context_sha256": _hash_payload(field_context) if field_context else None,
        "feedback": [
            _hash_payload(
                {
                    "id": item.get("id"),
                    "rating": item.get("rating"),
                    "failure_tags": item.get("failure_tags") or [],
                    "training_consent": bool(item.get("training_consent")),
                    "created_at": item.get("created_at"),
                    "content_sha256": _hash_payload(
                        {
                            "human_correction": item.get("human_correction"),
                            "ideal_answer": item.get("ideal_answer"),
                        }
                    ),
                }
            )
            for item in feedback_list
            if isinstance(item, dict)
        ],
        "extra_inputs_sha256": _hash_payload(extra_inputs or {}),
    }
    return {
        "schema_version": "phase6.report_reproducibility.v1",
        "renderer_version": PHASE6_REPORT_RENDERER_VERSION,
        "hash_algorithm": "sha256",
        "input_snapshot_sha256": _hash_payload(snapshot),
        "source": "phase4_thread_snapshot",
        "input_counts": {
            "messages": len(messages),
            "events": len(event_list),
            "feedback": len(feedback_list),
            "field_contexts": 1 if field_context else 0,
            "extra_inputs": len(extra_inputs or {}),
        },
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "hidden_prompts_excluded": True,
    }


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _latest_message(thread: dict[str, Any], actor: str) -> dict[str, Any]:
    for message in reversed(thread.get("messages", [])):
        if message.get("actor") == actor:
            return message
    return {}


def _latest_structured_answer(thread: dict[str, Any]) -> dict[str, Any]:
    message = _latest_message(thread, "assistant")
    metadata = message.get("metadata") if isinstance(message, dict) else {}
    structured = (metadata or {}).get("structured_answer") if isinstance(metadata, dict) else {}
    return structured if isinstance(structured, dict) else {}


def _latest_event_payload(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("event_type") == event_type and isinstance(event.get("payload"), dict):
            return event["payload"]
    return {}


def _model_context(thread: dict[str, Any], events: list[dict[str, Any]], structured: dict[str, Any]) -> dict[str, str]:
    model_payload = _latest_event_payload(events, "model_call")
    footer = structured.get("system_context_footer") if isinstance(structured, dict) else {}
    metadata = thread.get("metadata") if isinstance(thread.get("metadata"), dict) else {}
    return {
        "model_id": str(model_payload.get("model_id") or thread.get("model_profile_id") or "unknown"),
        "prompt_version": str(model_payload.get("prompt_version") or (footer or {}).get("prompt_version") or "unknown"),
        "context_policy_version": str(model_payload.get("context_packer_version") or (footer or {}).get("context_policy_version") or "phase5_context_packer_v1"),
        "corpus_version": str(model_payload.get("corpus_audit_id") or metadata.get("corpus_audit_id") or "local_configured_corpus"),
    }


def _field_context_summary(field_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not field_context:
        return []
    keys = ("nickname", "crop_current", "crop_stage", "region_text", "soil_texture", "drainage", "irrigation", "data_confidence")
    return [
        {"field": key, "value": field_context[key], "source": field_context.get("source", "user_entered")}
        for key in keys
        if field_context.get(key)
    ]


def _evidence_cards_from_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        source = doc.get("source") or doc.get("source_id") or "unknown"
        cards.append(
            {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "publisher": source,
                "source": source,
                "source_type": doc.get("source_type"),
                "score": doc.get("score"),
            }
        )
    return cards


def _source_list(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        key = str(card.get("source_id") or card.get("source") or card.get("publisher") or card.get("doc_id") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "source_id": key,
                "title": card.get("title"),
                "publisher": card.get("publisher") or card.get("source"),
                "source_type": card.get("source_type"),
                "license_status": _report_license_status(card.get("license_status")),
            }
        )
    return out


def _source_metadata_from_doc(doc: dict[str, Any], *, rank: int) -> dict[str, Any]:
    source = doc.get("source") or doc.get("source_id") or doc.get("publisher") or "unknown"
    score = doc.get("score")
    return {
        "rank": rank,
        "doc_id": doc.get("doc_id"),
        "title": doc.get("title") or "Untitled source",
        "source": source,
        "source_id": doc.get("source_id") or source,
        "url": doc.get("url") or doc.get("source_url"),
        "source_type": doc.get("source_type") or "unknown",
        "license_status": _report_license_status(doc.get("license_status")),
        "score": score,
        "relevance_note": f"Retrieved for this thread with score {score}." if score is not None else "Retrieved for this thread.",
    }


def _kg_hit_record(hit: dict[str, Any], *, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "node_id": hit.get("node_id"),
        "name": hit.get("name"),
        "kind": hit.get("kind"),
        "evidence": hit.get("evidence"),
        "neighbors": hit.get("neighbors") or [],
    }


def _license_status_summary(sources: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for source in sources:
        status = str(source.get("license_status") or "review_required")
        summary[status] = summary.get(status, 0) + 1
    return dict(sorted(summary.items())) or {"none_recorded": 0}


def _report_license_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"", "unknown", "none", "n/a"}:
        return "review_required"
    return status


def _redacted_message_record(message: dict[str, Any]) -> dict[str, Any]:
    content = str(message.get("content") or "")
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    structured = metadata.get("structured_answer") if isinstance(metadata, dict) else {}
    structured = structured if isinstance(structured, dict) else {}
    return {
        "message_id": message.get("id"),
        "actor": message.get("actor"),
        "sequence_no": message.get("sequence_no"),
        "created_at": message.get("created_at"),
        "content_sha256": _hash_text(content) if content else None,
        "content_redacted": True,
        "structured_answer_summary": {
            "risk_level": structured.get("risk_level"),
            "answer_type": structured.get("answer_type"),
            "evidence_card_count": len(structured.get("evidence_cards") or []),
            "missing_data_prompt_count": len(structured.get("missing_data_prompts") or []),
            "debug_ref": structured.get("debug_ref"),
        }
        if structured
        else None,
    }


def _redacted_trace_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {
        "event_id": event.get("event_id") or event.get("id"),
        "event_type": event.get("event_type"),
        "actor": event.get("actor"),
        "message_id": event.get("message_id"),
        "payload_summary": _redacted_event_payload_summary(str(event.get("event_type") or ""), payload),
        "hashes": event.get("hashes") or {},
        "elapsed_ms": event.get("elapsed_ms"),
        "created_at": event.get("created_at"),
    }


def _redacted_event_payload_summary(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type == "route_result":
        return {
            "question_type": payload.get("question_type"),
            "risk_level": payload.get("risk_level"),
            "namespaces": payload.get("namespaces") or [],
            "required_tools": payload.get("required_tools") or [],
        }
    if event_type == "retrieval_result":
        docs = [doc for doc in payload.get("retrieved_docs") or [] if isinstance(doc, dict)]
        return {
            "retrieved_doc_count": len(docs),
            "doc_ids": [doc.get("doc_id") for doc in docs],
            "source_types": [doc.get("source_type") for doc in docs],
            "private_doc_count": int(payload.get("private_doc_count") or 0),
        }
    if event_type == "kg_result":
        hits = [hit for hit in payload.get("graph_hits") or [] if isinstance(hit, dict)]
        return {"graph_hit_count": len(hits), "node_ids": [hit.get("node_id") for hit in hits]}
    if event_type == "assistant_answer":
        answer = str(payload.get("answer") or payload.get("public_answer_markdown") or "")
        return {"answer_sha256": _hash_text(answer) if answer else None, "answer_redacted": True}
    if event_type == "model_call":
        return {
            "model_id": payload.get("model_id"),
            "prompt_version": payload.get("prompt_version"),
            "context_packer_version": payload.get("context_packer_version"),
            "corpus_audit_id": payload.get("corpus_audit_id"),
        }
    if event_type == "user_feedback":
        return _redacted_feedback_record(payload)
    if event_type == "eval_candidate":
        return _redacted_eval_candidate_record(payload)
    if event_type in {"reflection_candidate", "reflection_review"}:
        return _redacted_reflection_record(payload)
    return {"payload_keys": sorted(str(key) for key in payload)}


def _redacted_feedback_record(feedback: dict[str, Any]) -> dict[str, Any]:
    human_correction = str(feedback.get("human_correction") or "")
    ideal_answer = str(feedback.get("ideal_answer") or "")
    return {
        "feedback_id": feedback.get("id"),
        "message_id": feedback.get("message_id"),
        "rating": feedback.get("rating"),
        "failure_tags": feedback.get("failure_tags") or [],
        "training_consent": bool(feedback.get("training_consent")),
        "human_correction_sha256": _hash_text(human_correction) if human_correction else None,
        "ideal_answer_sha256": _hash_text(ideal_answer) if ideal_answer else None,
        "text_fields_redacted": True,
        "created_at": feedback.get("created_at"),
    }


def _redacted_eval_candidate_record(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
    question = str(payload.get("question") or "")
    answer = str(payload.get("answer") or "")
    return {
        "candidate_id": candidate.get("id"),
        "thread_id": candidate.get("thread_id"),
        "message_id": candidate.get("message_id"),
        "candidate_type": candidate.get("candidate_type"),
        "target_component": candidate.get("target_component"),
        "review_status": candidate.get("review_status"),
        "question_sha256": _hash_text(question) if question else None,
        "answer_sha256": _hash_text(answer) if answer else None,
        "failure_tags": payload.get("failure_tags") or [],
        "reviewed_by_user_id": candidate.get("reviewed_by_user_id"),
        "created_at": candidate.get("created_at"),
        "reviewed_at": candidate.get("reviewed_at"),
    }


def _redacted_reflection_record(reflection: dict[str, Any]) -> dict[str, Any]:
    evidence = reflection.get("evidence") if isinstance(reflection.get("evidence"), dict) else {}
    return {
        "reflection_id": reflection.get("id") or reflection.get("memory_id"),
        "thread_id": reflection.get("thread_id"),
        "target_component": reflection.get("target_component"),
        "lesson_sha256": _hash_text(str(reflection.get("lesson") or "")) if reflection.get("lesson") else None,
        "candidate_rule_sha256": _hash_text(str(reflection.get("candidate_rule") or "")) if reflection.get("candidate_rule") else None,
        "evidence_keys": sorted(str(key) for key in evidence),
        "status": reflection.get("status"),
        "reviewed_by_user_id": reflection.get("reviewed_by_user_id"),
        "created_at": reflection.get("created_at"),
        "reviewed_at": reflection.get("reviewed_at"),
    }


def _redacted_phase5_metric(metric: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "trace_id",
        "thread_id",
        "turn_id",
        "workspace_id",
        "route_question_type",
        "risk_level",
        "namespaces",
        "required_tools",
        "rag_config_version",
        "corpus_bundle_version",
        "prompt_template_version",
        "context_packer_version",
        "model_id",
        "quantization",
        "total_latency_ms",
        "time_to_first_token_ms",
        "prompt_tokens_est",
        "completion_tokens_est",
        "context_tokens_est",
        "retrieval_doc_count",
        "source_diversity",
        "required_support_rate",
        "tool_notes_count",
        "quality_flags",
        "human_review_status",
        "reflection_status",
        "created_at",
    )
    return {key: metric.get(key) for key in keep}


def _redacted_phase5_span(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": span.get("trace_id"),
        "thread_id": span.get("thread_id"),
        "turn_id": span.get("turn_id"),
        "span_id": span.get("span_id"),
        "parent_span_id": span.get("parent_span_id"),
        "stage": span.get("stage"),
        "duration_ms": span.get("duration_ms"),
        "status": span.get("status"),
        "error_type": span.get("error_type"),
        "error_message_redacted": span.get("error_message_redacted"),
        "input_size": span.get("input_size"),
        "output_size": span.get("output_size"),
        "token_estimate_in": span.get("token_estimate_in"),
        "token_estimate_out": span.get("token_estimate_out"),
        "cache_status": span.get("cache_status"),
        "component_version": span.get("component_version"),
        "metadata": _redact_mapping(span.get("metadata") if isinstance(span.get("metadata"), dict) else {}),
        "created_at": span.get("created_at"),
    }


def _redact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    blocked = {"prompt", "messages", "content", "answer", "human_correction", "ideal_answer", "raw_text"}
    out: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if any(blocked_key in key_text.lower() for blocked_key in blocked):
            out[key_text] = {"sha256": _hash_text(json.dumps(item, sort_keys=True, default=str)), "redacted": True}
        elif isinstance(item, dict):
            out[key_text] = _redact_mapping(item)
        elif isinstance(item, list):
            out[key_text] = [
                _redact_mapping(entry) if isinstance(entry, dict) else entry
                for entry in item[:20]
            ]
        else:
            out[key_text] = item
    return out


def _counts_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _demo_eval_limitations(*, completed_runs: list[dict[str, Any]], latest_gates: dict[str, Any]) -> list[str]:
    limitations = [
        "This snapshot summarizes local trace-feedback regression only; it is not an independent agronomic benchmark.",
        "Candidate question and answer text is redacted from this public artifact.",
        "Coverage is limited to reviewed examples, registered workspace sources, and the configured local corpus.",
        "It does not validate product labels, legal requirements, rates, or field-specific diagnoses.",
    ]
    if not completed_runs:
        limitations.insert(0, "No reviewed eval runs are available; do not make public quality claims from this snapshot.")
    elif not latest_gates.get("promotion_allowed"):
        reasons = ", ".join(str(reason) for reason in latest_gates.get("reasons") or []) or "gate_not_met"
        limitations.insert(0, f"The latest completed eval run is not promotion-ready: {reasons}.")
    return limitations


def _demo_eval_run_record(run: dict[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    gates = run.get("gates") if isinstance(run.get("gates"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    return {
        "run_id_sha256": _hash_text(str(run.get("id") or "")) if run.get("id") else None,
        "name": run.get("name") or "Unnamed eval run",
        "status": run.get("status"),
        "candidate_count": int(metrics.get("candidate_count") or len(run.get("candidate_ids") or [])),
        "pass_rate": float(metrics.get("pass_rate") or 0.0),
        "failure_case_count": int(metrics.get("failure_case_count") or 0),
        "promotion_allowed": bool(gates.get("promotion_allowed")),
        "gate_reasons": list(gates.get("reasons") or []),
        "regression_suite": gates.get("regression_suite") or "local_trace_feedback_regression_v1",
        "corpus_audit_id": metadata.get("corpus_audit_id"),
        "created_at": run.get("created_at"),
        "finished_at": run.get("finished_at"),
    }


def _data_source_audit_row(source: dict[str, Any], jobs: list[dict[str, Any]], chunk_count: int) -> dict[str, Any]:
    latest_job = jobs[0] if jobs else None
    gap_flags: list[str] = []
    license_state = str(source.get("license_state") or "unknown").lower()
    if license_state in {"unknown", "review_required"} or "review" in license_state:
        gap_flags.append("license_review_required")
    if source.get("rag_eligible") and not jobs:
        gap_flags.append("missing_ingest_job")
    if source.get("rag_eligible") and chunk_count == 0:
        gap_flags.append("no_chunks_indexed")
    if latest_job and latest_job.get("status") in {"failed", "error"}:
        gap_flags.append("ingest_failed")
    if latest_job and latest_job.get("status") in {"queued", "running"}:
        gap_flags.append(f"ingest_{latest_job['status']}")
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    crops = list(source.get("crops") or [])
    regions = list(source.get("regions") or [])
    buckets = list(source.get("buckets") or [])
    latest_ingest_finished_at = latest_job.get("finished_at") if latest_job else None
    updated_or_ingested_date = latest_ingest_finished_at or source.get("updated_at")
    known_limitations = _source_known_limitations(
        license_state=license_state,
        gap_flags=gap_flags,
        rag_eligible=bool(source.get("rag_eligible")),
        sft_eligible=bool(source.get("sft_eligible")),
        chunk_count=chunk_count,
    )
    return {
        "data_source_id": source.get("id"),
        "source_id": source.get("source_id"),
        "title": source.get("title"),
        "publisher": source.get("publisher"),
        "canonical_url": source.get("canonical_url"),
        "url_or_source_id": source.get("canonical_url") or source.get("source_id"),
        "source_kind": source.get("source_kind"),
        "source_type": source.get("source_kind"),
        "license_state": source.get("license_state") or "unknown",
        "license_status": source.get("license_state") or "unknown",
        "rag_eligible": bool(source.get("rag_eligible")),
        "sft_eligible": bool(source.get("sft_eligible")),
        "chunk_count": chunk_count,
        "latest_ingest_status": latest_job.get("status") if latest_job else "not_started",
        "latest_ingest_finished_at": latest_ingest_finished_at,
        "gap_flags": gap_flags,
        "crops": crops,
        "regions": regions,
        "region_crop": _region_crop_summary(regions=regions, crops=crops),
        "buckets": buckets,
        "updated_or_ingested_date": updated_or_ingested_date,
        "why_used": _source_why_used(rag_eligible=bool(source.get("rag_eligible")), sft_eligible=bool(source.get("sft_eligible")), buckets=buckets),
        "known_limitations": known_limitations,
        "metadata_keys": sorted(str(key) for key in metadata if key not in {"text_content", "raw_document_text"}),
        "updated_at": source.get("updated_at"),
    }


def _region_crop_summary(*, regions: list[str], crops: list[str]) -> str:
    region_text = "|".join(str(region) for region in regions) if regions else "region_not_specified"
    crop_text = "|".join(str(crop) for crop in crops) if crops else "crop_not_specified"
    return f"{region_text}; {crop_text}"


def _source_why_used(*, rag_eligible: bool, sft_eligible: bool, buckets: list[str]) -> str:
    uses: list[str] = []
    if rag_eligible:
        uses.append("retrieval")
    if sft_eligible:
        uses.append("training_candidate")
    if not uses:
        uses.append("governance_boundary")
    bucket_text = "|".join(str(bucket) for bucket in buckets) if buckets else "uncategorized"
    return f"{'+'.join(uses)}; lanes={bucket_text}"


def _source_known_limitations(
    *,
    license_state: str,
    gap_flags: list[str],
    rag_eligible: bool,
    sft_eligible: bool,
    chunk_count: int,
) -> str:
    limitations: list[str] = []
    if license_state in {"unknown", "review_required"} or "review" in license_state:
        limitations.append("license_review_required")
    if rag_eligible and chunk_count == 0:
        limitations.append("not_indexed_for_retrieval")
    if rag_eligible and not sft_eligible:
        limitations.append("retrieval_only_not_training")
    if not rag_eligible and not sft_eligible:
        limitations.append("governance_only_not_retrieval_or_training")
    limitations.extend(flag for flag in gap_flags if flag not in limitations)
    return "|".join(limitations) if limitations else "none_recorded"


def _diagnostic_triage_steps(route: dict[str, Any], structured: dict[str, Any], quality: dict[str, Any]) -> list[dict[str, Any]]:
    namespaces = set(route.get("namespaces") or [])
    steps = [
        {
            "action": "Restate the observed symptom, field area, and timing before interpreting causes.",
            "why": "A clear observation boundary prevents the checklist from turning into an unsupported diagnosis",
            "evidence_ref": None,
        },
        {
            "action": "Compare affected and unaffected zones in the same field.",
            "why": "Paired field comparison separates field pattern, weather, soil, and management signals",
            "evidence_ref": None,
        },
    ]
    if "soil_water" in namespaces or "fertility" in namespaces:
        steps.append(
            {
                "action": "Check soil moisture, drainage pathway, compaction signs, and recent rainfall or irrigation.",
                "why": "Soil-water context often controls whether nutrient or stress symptoms are actionable",
                "evidence_ref": None,
            }
        )
    if "plant_health" in namespaces or "product_stewardship" in namespaces:
        steps.append(
            {
                "action": "Scout representative plants and record pest, disease, weed, or injury patterns with photos.",
                "why": "Visual pattern and distribution are needed before treatment decisions",
                "evidence_ref": None,
            }
        )
    if structured.get("evidence_cards"):
        first_card = structured["evidence_cards"][0]
        steps.append(
            {
                "action": "Open the top evidence card and verify it fits the crop, region, and question scope.",
                "why": "Source fit should be confirmed before using an evidence-derived claim",
                "evidence_ref": first_card.get("doc_id"),
            }
        )
    if quality.get("ready", {}).get("diagnostic_triage") is False:
        steps.append(
            {
                "action": "Fill the minimum missing field context before escalating beyond conceptual guidance.",
                "why": "The field profile quality meter is not ready for diagnostic triage",
                "evidence_ref": None,
            }
        )
    return steps


def _diagnostic_measurement_plan(field_context: dict[str, Any] | None, missing_data: list[Any], route: dict[str, Any]) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for item in missing_data[:5]:
        plan.append({"measurement": str(item), "reason": "Needed to narrow the field-specific interpretation."})
    if not field_context or not field_context.get("soil_test_summary"):
        plan.append({"measurement": "soil test date, method, and key values", "reason": "Avoid fertility interpretation without calibrated local evidence."})
    if not field_context or not field_context.get("management_notes"):
        plan.append({"measurement": "recent weather and management notes", "reason": "Weather and operations often explain symptoms or runoff pathways."})
    namespaces = set(route.get("namespaces") or [])
    if "product_stewardship" in namespaces or route.get("risk_level") == "regulated":
        plan.append({"measurement": "current product label and jurisdiction", "reason": "Product, label, or rate decisions require current local authority."})
    return [{"measurement": item["measurement"], "reason": item["reason"]} for item in _dedupe_measurements(plan)]


def _diagnostic_safety_boundaries(route: dict[str, Any], structured: dict[str, Any]) -> list[str]:
    boundaries = [
        "Do not treat this checklist as a diagnosis.",
        "Do not use this checklist as a product, rate, or legal recommendation.",
        "Escalate to a local agronomist or certified adviser when field evidence is ambiguous or risk is regulated.",
    ]
    if route.get("risk_level") == "regulated" or structured.get("risk_level") == "regulated":
        boundaries.append("Verify current label and local jurisdiction before any regulated action.")
    return _dedupe_strings(boundaries)


def _dedupe_measurements(values: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        key = item["measurement"]
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _feedback_summary(feedback: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not feedback:
        return None
    latest = feedback[-1]
    return {
        "rating": latest.get("rating"),
        "failure_tags": latest.get("failure_tags", []),
        "training_consent": bool(latest.get("training_consent", False)),
    }


def _field_profile_for_brief(field_context: dict[str, Any] | None) -> dict[str, Any]:
    if not field_context:
        return {"attached": False, "user_entered_fields": {}}
    field_names = (
        "display_name",
        "region_text",
        "country",
        "province_state",
        "county_rm",
        "crop_current",
        "crop_year",
        "soil_series_or_texture",
        "drainage_class",
        "irrigation_status",
        "soil_test_summary",
        "crop_rotation_notes",
        "management_notes",
        "known_constraints",
        "sensitivity",
    )
    return {
        "attached": True,
        "field_context_id": field_context.get("id"),
        "user_entered_fields": {
            key: value
            for key in field_names
            if (value := field_context.get(key)) not in (None, "", [])
        },
    }


def _soil_water_context(field_context: dict[str, Any] | None) -> dict[str, Any]:
    if not field_context:
        return {"status": "missing_field_profile"}
    keys = ("soil_series_or_texture", "drainage_class", "irrigation_status", "soil_test_summary", "known_constraints")
    context = {key: field_context.get(key) for key in keys if field_context.get(key) not in (None, "", [])}
    return context or {"status": "not_provided"}


def _known_unknowns(field_context: dict[str, Any] | None, quality: dict[str, Any]) -> list[str]:
    unknowns = list(quality.get("missing_minimum_next_prompts") or [])
    if not field_context:
        unknowns.insert(0, "Attach or create a reusable field profile.")
    if field_context and not field_context.get("soil_test_summary"):
        unknowns.append("Soil test availability, date, and method are not recorded.")
    if field_context and not field_context.get("management_notes"):
        unknowns.append("Recent weather, field observations, or management notes are not recorded.")
    return _dedupe_strings(unknowns)


def _next_measurements(quality: dict[str, Any]) -> list[str]:
    prompts = list(quality.get("missing_minimum_next_prompts") or [])
    prompts.append("Record source and date for any soil test or uploaded field note.")
    prompts.append("Keep product/rate decisions separate until current label and local recommendation authority are verified.")
    return _dedupe_strings(prompts)


def _append_key_values(lines: list[str], values: dict[str, Any]) -> None:
    if not values:
        lines.append("- None recorded.")
        return
    for key, value in values.items():
        lines.append(f"- {key}: {value}")


def _append_list(lines: list[str], values: list[Any]) -> None:
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- None recorded.")


def _append_list_section(lines: list[str], title: str, values: list[Any]) -> None:
    lines.extend(["", f"## {title}"])
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- None recorded.")


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _redact_payload(payload: dict[str, Any], mode: str, *, training_safe: bool = False) -> dict[str, Any]:
    if not payload:
        return payload
    redacted = json.loads(json.dumps(payload))
    if mode in {"identifiers", "snippets_hashed", "training_safe"}:
        if "user_pseudonym" in redacted:
            redacted["user_pseudonym"] = "redacted"
        if mode == "training_safe":
            return redacted
        if mode == "snippets_hashed":
            for turn in redacted.get("turns", []):
                if "user_message" in turn:
                    turn["user_message"] = f"[redacted:{_hash_text(str(turn['user_message']))}]"
                if "answer" in turn:
                    turn["answer"] = f"[redacted:{_hash_text(str(turn['answer']))}]"
                for doc in turn.get("trace", {}).get("retrieved_docs", []):
                    if doc.get("snippet"):
                        doc["snippet"] = f"[redacted:{_hash_text(str(doc['snippet']))}]"
    return redacted


def _strip_for_training(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "turn_id": turn.get("turn_id"),
        "answer_status": turn.get("answer_status"),
        "system_state": turn.get("system_state"),
        "trace": turn.get("trace", {}),
    }


def _redact_turn(turn: dict[str, Any], mode: str) -> dict[str, Any]:
    redacted = json.loads(json.dumps(turn))
    if mode == "identifiers":
        redacted["user_message"] = "[redacted]"
    elif mode == "snippets_hashed":
        redacted["user_message"] = f"[redacted:{_hash_text(redacted.get('user_message', ''))}]"
        redacted["answer"] = f"[redacted:{_hash_text(redacted.get('answer', ''))}]"
        trace = redacted.get("trace", {})
        for doc in trace.get("retrieved_docs", []):
            if "snippet" in doc and doc["snippet"]:
                doc["snippet"] = f"[redacted:{_hash_text(doc['snippet'])}]"
    elif mode == "training_safe":
        redacted["user_message"] = "[training-safe]"
        redacted["answer"] = "[training-safe]"
        redacted["trace"] = _strip_sensitive_trace(redacted.get("trace", {}))
    return redacted


def _strip_sensitive_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": trace.get("route"),
        "coverage_checklist": trace.get("coverage_checklist", []),
        "retrieved_doc_ids": [doc.get("doc_id") for doc in trace.get("retrieved_docs", [])],
        "graph_nodes": [hit.get("node_id") for hit in trace.get("graph_hits", [])],
        "tool_invocations": [tool.get("name") for tool in trace.get("tool_invocations", [])],
        "metadata": trace.get("metadata", {}),
    }


def _build_feedback_rows(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for turn in turns:
        feedback = turn.get("feedback") or {}
        if not feedback:
            continue
        out.append({"turn_id": turn["turn_id"], "session_id": turn.get("session_id"), **feedback})
    return out


def _build_message_rows(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for turn in turns:
        rows.append(
            {
                "turn_id": turn["turn_id"],
                "role": "user",
                "content": turn.get("user_message", "[redacted]"),
                "created_at": turn.get("created_at"),
            },
        )
        rows.append(
            {
                "turn_id": turn["turn_id"],
                "role": "assistant",
                "content": turn.get("answer", "[redacted]"),
                "created_at": turn.get("created_at"),
            },
        )
    return rows


def _build_reflection_rows(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for turn in turns:
        reflection = turn.get("reflection")
        if not reflection:
            continue
        out.append(
            {
                "memory_id": f"mem_{turn['turn_id']}",
                "created_from_turn_id": turn["turn_id"],
                "scope": reflection.get("affected_component", "unknown"),
                "lesson": reflection.get("proposed_rule"),
                "positive_example": "",
                "negative_example": "",
                "evidence": reflection.get("evidence", []),
                "status": reflection.get("review_status", "candidate"),
                "reviewer": reflection.get("reviewer_id", "local_user"),
            },
        )
    return out


def _build_eval_rows(session: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    context = session.get("context", {})
    for turn in turns:
        feedback = turn.get("feedback", {}) or {}
        out.append(
            {
                "eval_id": f"eval_{turn['turn_id']}",
                "session_id": session["session_id"],
                "turn_id": turn["turn_id"],
                "question": turn.get("user_message", "[redacted]"),
                "task_family": "unknown",
                "crop": context.get("crop"),
                "region": context.get("region"),
                "required_patterns": [],
                "ask_for_patterns": [],
                "forbidden_patterns": [],
                "expected_tools": list((turn.get("trace") or {}).get("route", {}).get("required_tools", [])),
                "score": {
                    "rating": feedback.get("rating"),
                    "route_correct": feedback.get("route_correct"),
                    "failure_tags": feedback.get("failure_tags", []),
                },
                "score_metadata": turn.get("objectives", {}),
                "answer": turn.get("answer", "[redacted]"),
            },
        )
    return out


def _build_gepa_rows(session: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for turn in turns:
        route = (turn.get("trace") or {}).get("route") or {}
        out.append(
            {
                "trajectory_id": f"traj_{uuid.uuid4().hex}",
                "session_id": session["session_id"],
                "turn_id": turn["turn_id"],
                "task": {
                    "user_question": turn.get("user_message", "[redacted]"),
                    "session_context": session.get("context", {}),
                    "task_family": route.get("question_type", "unknown"),
                    "crop": session.get("context", {}).get("crop"),
                    "region": session.get("context", {}).get("region"),
                    "risk_level": route.get("risk_level"),
                },
                "system_state": {
                    "mode": (turn.get("system_state") or {}).get("mode"),
                    "model_id": (turn.get("system_state") or {}).get("model_id"),
                    "prompt_version": (turn.get("system_state") or {}).get("prompt_version"),
                    "rag_config": (turn.get("system_state") or {}).get("rag_config"),
                    "corpus_audit_id": (turn.get("system_state") or {}).get("corpus_audit_id"),
                },
                "trajectory": {
                    "route": route,
                    "retrieved_docs": (turn.get("trace") or {}).get("retrieved_docs", []),
                    "graph_hits": (turn.get("trace") or {}).get("graph_hits", []),
                    "tool_invocations": (turn.get("trace") or {}).get("tool_invocations", []),
                    "prompt_messages": (turn.get("trace") or {}).get("prompt_messages"),
                    "answer": turn.get("answer", "[redacted]"),
                },
                "feedback": (turn.get("feedback") or {}),
                "reflection": turn.get("reflection"),
                "objectives": turn.get("objectives", {}),
            }
        )
    return out


def _build_retrieval_diagnostics_rows(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for turn in turns:
        trace = turn.get("trace") or {}
        docs = trace.get("retrieved_docs", [])
        row = {
            "turn_id": turn["turn_id"],
            "doc_count": len(docs),
            "source_diversity": len({doc.get("source") for doc in docs}),
            "top_doc_score": max((doc.get("score", 0.0) for doc in docs), default=0.0),
            "route_question_type": (trace.get("route") or {}).get("question_type"),
        }
        rows.append(row)
    return rows


def _build_trace_bundle_payload(
    session: dict[str, Any],
    turns: list[dict[str, Any]],
    data_sources: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    bundle_manifest = dict(manifest)
    bundle_manifest["files"] = []
    bundle_manifest["checksums"] = {}
    return {
        "schema_version": "phase3.trace.v0",
        "session": {
            "session_id": session.get("session_id"),
            "title": session.get("title"),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "user_pseudonym": session.get("user_pseudonym"),
            "tags": session.get("tags", []),
            "consent": session.get("consent", {}),
            "context": session.get("context", {}),
        },
        "turns": turns,
        "data_sources": data_sources,
        "artifacts": [],
        "export_manifest": bundle_manifest,
    }


def _extract_data_sources(store: Any, include_data_sources: bool) -> list[dict[str, Any]]:
    if not include_data_sources or not hasattr(store, "list_data_sources"):
        return []
    return list(store.list_data_sources())


def _contains_private_attachment_text(sources: list[dict[str, Any]]) -> bool:
    for source in sources:
        if source.get("source_type") in {"file", "directory", "attachment"}:
            return True
        if source.get("path"):
            return True
    return False


def _normalize_prompt_messages(turn: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(turn))
    trace = normalized.get("trace")
    if isinstance(trace, dict) and trace.get("prompt_messages") is None:
        trace["prompt_messages"] = []
        normalized["trace"] = trace
    return normalized


def _build_markdown_transcript(title: str, session: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"# {title}", "", f"Session ID: {session.get('session_id')}", f"Created: {session.get('created_at')}"]
    for turn in turns:
        route = (turn.get("trace") or {}).get("route") or {}
        lines.extend(
            [
                "",
                f"## Turn {turn.get('turn_id')}",
                f"- Risk: {route.get('risk_level', 'unknown')}",
                f"- Route: {route.get('question_type', 'unknown')}",
                f"- Namespaces: {', '.join(route.get('namespaces', []))}",
                f"**User:** {turn.get('user_message', '[redacted]')}",
                "",
                f"**Answer:** {turn.get('answer', '[redacted]')}",
                "",
            ]
        )
    return "\n".join(lines)


def _build_advisory_draft(title: str, turns: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"# Advisory draft: {title}", ""]
    reviewed = [turn for turn in turns if ((turn.get("feedback") or {}).get("accepted") is True) or turn.get("answer_status") == "approved"]
    if not reviewed:
        lines.append("No reviewed/approved turns were available for advisory export.")
        return "\n".join(lines)
    for turn in reviewed:
        route = (turn.get("trace") or {}).get("route") or {}
        lines.extend(
            [
                f"## {turn.get('user_message', '[redacted]')}",
                f"- Risk: {route.get('risk_level', 'unknown')}",
                f"- Route: {route.get('question_type', 'unknown')}",
                f"- Source namespaces: {', '.join(route.get('namespaces', [])) or 'none'}",
                f"- Answer: {turn.get('answer', '[redacted]')}",
                "",
            ],
        )
    return "\n".join(lines)


def build_export_bundle(
    session: dict[str, Any],
    store: Any,
    artifact_root: Path,
    *,
    export_id: str | None = None,
    redaction_mode: str = "snippets_hashed",
    include_turn_ids: list[str] | None = None,
    include_turns: bool = True,
    include_data_sources: bool = True,
    include_artifacts: bool = True,
    prompt_version: str = "phase3_default_v0",
) -> tuple[dict[str, Any], dict[str, str]]:
    export_id = export_id or f"exp_{uuid.uuid4().hex[:12]}"
    export_dir = artifact_root / export_id
    turns = session.get("turns", [])
    if include_turn_ids and not include_turns:
        raise ValueError("turn_ids can only be used when include_turns is true")
    if not include_turns:
        turns = []
    if include_turn_ids:
        included = set(include_turn_ids)
        turns = [turn for turn in turns if turn["turn_id"] in included]

    enriched_turns = []
    for turn in turns:
        full_turn = store.get_turn(turn["turn_id"]) if hasattr(store, "get_turn") else None
        enriched_turns.append(_normalize_prompt_messages(json.loads(json.dumps(full_turn or turn))))
    redacted_turns = [_redact_turn(turn, redaction_mode) for turn in enriched_turns]
    redacted_session = json.loads(json.dumps(session))
    redacted_session["turns"] = redacted_turns
    redacted_session = _redact_payload(redacted_session, redaction_mode)

    event_rows = store.list_events(session["session_id"]) if hasattr(store, "list_events") else []
    traces = redacted_session.get("turns", [])
    data_sources = _extract_data_sources(store, include_data_sources=include_data_sources)

    _write_json(export_dir / "session.json", redacted_session)

    if include_artifacts:
        _write_jsonl(export_dir / "turns.jsonl", traces)
        _write_jsonl(export_dir / "messages.jsonl", _build_message_rows(traces))
        _write_jsonl(export_dir / "events.jsonl", event_rows)
        _write_jsonl(export_dir / "routes.jsonl", [t.get("trace", {}).get("route") for t in traces if t.get("trace") is not None and t.get("trace").get("route")])
        _write_jsonl(export_dir / "retrieved_docs.jsonl", [doc for t in traces for doc in t.get("trace", {}).get("retrieved_docs", [])])
        _write_jsonl(export_dir / "graph_hits.jsonl", [hit for t in traces for hit in t.get("trace", {}).get("graph_hits", [])])
        _write_jsonl(export_dir / "tool_invocations.jsonl", [tool for t in traces for tool in t.get("trace", {}).get("tool_invocations", [])])
        _write_jsonl(export_dir / "trace.jsonl", [t.get("trace", {}) for t in traces])
        _write_jsonl(export_dir / "feedback.jsonl", _build_feedback_rows(traces))
        _write_jsonl(export_dir / "reflections.jsonl", _build_reflection_rows(traces))
        _write_jsonl(export_dir / "gepa_trajectories.jsonl", _build_gepa_rows(redacted_session, traces))
        _write_jsonl(export_dir / "reflexion_memory_candidates.jsonl", _build_reflection_rows(redacted_session.get("turns", [])))
        _write_jsonl(export_dir / "eval_items.jsonl", _build_eval_rows(redacted_session, traces))
        _write_json(export_dir / "retrieval_diagnostics.json", _build_retrieval_diagnostics_rows(traces))
        _write_text(export_dir / "advisory_draft.md", _build_advisory_draft(session.get("title", "Session"), traces))

    _write_json(export_dir / "evidence_manifest.json", {
        "session_id": session["session_id"],
        "export_mode": redaction_mode,
        "generated_at": _now(),
        "files": {
            "turn_count": len(traces),
            "event_count": len(event_rows),
        },
        "data_sources": data_sources,
    })
    _write_json(export_dir / "sessions.json", {"sessions": [session.get("session_id")], "session": redacted_session})

    if include_artifacts:
        transcript = _build_markdown_transcript(session.get("title", "Session"), redacted_session, traces)
        _write_text(export_dir / "transcript.md", transcript)

    first_turn = traces[0] if traces else {}
    manifest = {
        "export_id": export_id,
        "created_at": _now(),
        "session_id": session["session_id"],
        "redaction_mode": redaction_mode,
        "training_eligible": bool(
            redaction_mode == "training_safe"
            and redacted_session.get("consent", {}).get("training_export_allowed", False)
        ),
        "training_exclusion_reason": None
        if redaction_mode == "training_safe" and redacted_session.get("consent", {}).get("training_export_allowed", False)
        else "training export requires training_safe redaction and consent",
        "contains_personal_data": bool(redacted_session.get("user_pseudonym")),
        "contains_farm_identifiable_data": bool(redacted_session.get("context", {}).get("farm_id")),
        "contains_private_attachment_text": _contains_private_attachment_text(data_sources),
        "files": [],
        "checksums": {},
        "model_id": first_turn.get("system_state", {}).get("model_id") if first_turn else None,
        "prompt_version": first_turn.get("system_state", {}).get("prompt_version", prompt_version),
        "rag_config": first_turn.get("system_state", {}).get("rag_config") if first_turn else None,
        "corpus_audit_id": first_turn.get("system_state", {}).get("corpus_audit_id") if first_turn else None,
        "source_manifest_hashes": [ds.get("checksum", "") for ds in data_sources if ds.get("checksum")],
    }

    _write_json(export_dir / "trace_bundle.json", _build_trace_bundle_payload(redacted_session, traces, data_sources, manifest))
    for _ in range(2):
        checksums: dict[str, str] = {}
        files: list[dict[str, str]] = []
        for file in sorted(export_dir.iterdir()):
            if file.is_file() and file.name not in {"checksums.sha256", "session_manifest.json"}:
                checksum = _hash_file(file)
                checksums[file.name] = checksum
                files.append({"file": file.name, "checksum": checksum})
        manifest["checksums"] = checksums
        manifest["files"] = files
        _write_json(export_dir / "trace_bundle.json", _build_trace_bundle_payload(redacted_session, traces, data_sources, manifest))
        _write_json(export_dir / "session_manifest.json", manifest)

    checksum_lines = [f"{hash_}  {name}" for name, hash_ in sorted(manifest["checksums"].items())]
    _write_text(export_dir / "checksums.sha256", "\n".join(checksum_lines) + "\n")
    manifest["checksums"]["checksums.sha256"] = _hash_file(export_dir / "checksums.sha256")
    manifest["files"].append({"file": "checksums.sha256", "checksum": manifest["checksums"]["checksums.sha256"]})
    _write_json(export_dir / "session_manifest.json", manifest)
    return manifest, {item["file"]: str(export_dir / item["file"]) for item in manifest["files"]}
