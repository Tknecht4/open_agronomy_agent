"""Read authoritative Phase 5 training provenance; never certify source rights."""
from __future__ import annotations

from typing import Any

from agronomy_agent.phase5_sft import training_lineage_block_reason


def resolve_sft_source_lineage(
    store: Any, trace_id: str, *, thread_id: str | None = None, workspace_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fail closed on missing or inconsistent original identities, including legacy rows."""
    if not trace_id:
        return None, "unresolved_lineage"
    source = store.get_phase5_admin_trace(trace_id)
    if not isinstance(source, dict) or str(source.get("trace_id") or "") != trace_id:
        return None, "unresolved_lineage"
    metrics = source.get("metrics")
    if not isinstance(metrics, dict) or str(metrics.get("trace_id") or "") != trace_id:
        return None, "unresolved_lineage"
    original_thread_id = str(metrics.get("thread_id") or "")
    if not original_thread_id or (thread_id is not None and original_thread_id != thread_id):
        return None, "unresolved_lineage"
    thread = store.get_phase4_thread(original_thread_id)
    if not isinstance(thread, dict) or str(thread.get("id") or "") != original_thread_id:
        return None, "unresolved_lineage"
    original_workspace_id = str(thread.get("workspace_id") or "")
    if not original_workspace_id or (workspace_id is not None and original_workspace_id != workspace_id):
        return None, "unresolved_lineage"
    if metrics.get("workspace_id") and str(metrics["workspace_id"]) != original_workspace_id:
        return None, "unresolved_lineage"
    events = store.list_phase4_trace_events(original_thread_id)
    messages = store.list_phase4_messages(original_thread_id)
    turn_id = str(metrics.get("turn_id") or "")
    if not turn_id or not any(
        str(message.get("id") or "") == turn_id and message.get("actor") == "assistant"
        for message in messages
    ):
        return None, "unresolved_lineage"
    # Keep the original structures separate so client labels cannot overwrite them.
    lineage = {
        "trace": source,
        "metadata": thread.get("metadata") or {},
        "trace_events": events,
        "messages": messages,
    }
    reason = training_lineage_block_reason(lineage)
    if reason:
        return lineage, reason
    if not thread.get("training_eligible"):
        return lineage, "thread_not_training_eligible"
    if not metrics.get("leak_check_passed"):
        return lineage, "prompt_leak_check_failed"
    return lineage, None


def candidate_training_block_reason(
    store: Any, candidate: dict[str, Any], *, proposed_labels: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    # Evaluate current and proposed declarations independently; false/new labels
    # must never erase an earlier evaluation identity or unresolved declaration.
    reason = training_lineage_block_reason(candidate) or training_lineage_block_reason({"labels": proposed_labels or {}})
    if reason:
        return None, reason
    trace_id = str(candidate.get("trace_id") or "")
    labels = candidate.get("labels") if isinstance(candidate.get("labels"), dict) else {}
    if labels.get("source_trace_id") and str(labels["source_trace_id"]) != trace_id:
        return None, "unresolved_lineage"
    if proposed_labels and proposed_labels.get("source_trace_id") and str(proposed_labels["source_trace_id"]) != trace_id:
        return None, "unresolved_lineage"
    thread_id = str(candidate.get("thread_id") or "")
    workspace_id = str(candidate.get("workspace_id") or "")
    if not thread_id or not workspace_id:
        return None, "unresolved_lineage"
    return resolve_sft_source_lineage(store, trace_id, thread_id=thread_id, workspace_id=workspace_id)
