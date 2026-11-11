from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
APPROVED_REVIEW_STATUSES = {"approved", "reviewed", "expert_reviewed", "accepted"}
HELD_OUT_SPLIT_VALUES = {"heldout", "held_out", "holdout", "eval", "evaluation", "test"}
EVALUATION_FLAGS = {
    "held_out_eval", "is_held_out", "held_out", "is_evaluation", "is_evaluation_case",
    "is_evaluation_answer", "is_evaluation_trace", "evaluation_case", "evaluation_answer",
}
EVALUATION_IDS = {
    "evaluation_suite_id", "evaluation_case_id", "evaluation_answer_id", "evaluation_trace_id",
    "evaluation_run_id", "eval_suite_id", "eval_case_id", "eval_answer_id", "eval_run_id",
    "benchmark_suite_id", "benchmark_case_id", "benchmark_answer_id",
    "eval_id", "benchmark_id", "source_eval_id", "evaluation_partition",
}
SPLIT_KEYS = {"split", "dataset_split", "eval_split", "data_split"}
LINEAGE_STATUS_KEYS = {"lineage_status", "evaluation_lineage_status", "provenance_status"}
UNRESOLVED_LINEAGE_VALUES = {"unknown", "unresolved", "unverified", "pending", "missing"}
# Follow provenance-bearing structures, never arbitrary document or message text.
LINEAGE_CONTAINERS = {
    "labels", "review_labels", "trace", "metadata", "metrics", "lineage", "source_lineage",
    "evaluation_lineage", "answer_lineage", "provenance", "structured_answer", "source_evidence",
    "trace_events", "spans", "messages", "payload", "attributes",
    "eval_metadata", "evaluation_metadata", "benchmark_generation_input", "benchmark_egress_receipt",
}
EVALUATION_CONTAINERS = {"eval_metadata", "evaluation_metadata", "benchmark_generation_input", "benchmark_egress_receipt"}
PROVENANCE_CONTAINERS = {"lineage", "source_lineage", "evaluation_lineage", "answer_lineage", "provenance"}
EVALUATION_SCHEMAS = {
    "open_agronomy_agent.release_product_cell.v1", "open_agronomy_agent.benchmark_generation_input.v1",
}
LINEAGE_SNAPSHOT_KEYS = EVALUATION_FLAGS | EVALUATION_IDS | SPLIT_KEYS | LINEAGE_STATUS_KEYS | {
    "exposure", "source_dataset", "source_family", "source_version", "source_suite",
    "suite_id", "case_id", "schema_version", "distribution_scope",
}


@dataclass(frozen=True)
class SftCandidate:
    candidate_id: str
    trace_id: str
    messages: tuple[dict[str, str], ...]
    labels: dict[str, Any]
    dataset_card: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "trace_id": self.trace_id,
            "messages": list(self.messages),
            "labels": self.labels,
            "dataset_card": self.dataset_card,
            "schema_version": "phase5_sft_candidate_v1",
        }


def redact_training_text(value: str) -> str:
    redacted = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    redacted = PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


def trace_to_sft_candidate(trace_payload: dict[str, Any], *, reviewer_id: str, consented: bool) -> SftCandidate | None:
    if not consented:
        return None
    labels = dict(trace_payload.get("labels") or trace_payload.get("review_labels") or {})
    if training_lineage_block_reason(trace_payload, labels=labels):
        return None
    if contains_private_field_data(trace_payload, labels=labels) and not has_explicit_private_training_consent(
        trace_payload,
        labels=labels,
    ):
        return None
    review_status = _first_text(
        trace_payload.get("review_status"),
        trace_payload.get("human_review_status"),
        labels.get("review_status"),
        labels.get("human_review_status"),
    )
    if review_status.lower() not in APPROVED_REVIEW_STATUSES:
        return None
    repair_layer = _first_text(trace_payload.get("repair_layer"), labels.get("repair_layer"))
    failure_class = _first_text(trace_payload.get("failure_class"), labels.get("failure_class"))
    if not repair_layer or not failure_class:
        return None
    metrics = trace_payload.get("metrics") or {}
    if not metrics.get("leak_check_passed", False):
        return None
    trace = trace_payload.get("trace") or {}
    prompt_messages = trace.get("prompt_messages") or []
    structured = trace.get("structured_answer") or {}
    answer = structured.get("answer") or trace_payload.get("answer") or ""
    ideal_answer = _first_text(trace_payload.get("ideal_answer"), structured.get("ideal_answer"), labels.get("ideal_answer"), answer)
    rejected_answer = _first_text(trace_payload.get("rejected_answer"), labels.get("rejected_answer"))
    if not rejected_answer and ideal_answer != answer:
        rejected_answer = str(answer)
    if not prompt_messages or not answer:
        return None
    source_evidence = source_evidence_from_trace_payload(trace_payload, labels=labels)
    if not source_evidence:
        return None
    messages = tuple(
        {"role": str(item.get("role", "")), "content": redact_training_text(str(item.get("content", "")))}
        for item in prompt_messages
        if item.get("role") and item.get("content")
    )
    messages = (*messages, {"role": "assistant", "content": redact_training_text(str(ideal_answer))})
    trace_id = _first_text(trace_payload.get("trace_id"), metrics.get("trace_id"))
    if not trace_id:
        return None
    return SftCandidate(
        candidate_id=hashlib.sha256(json.dumps(messages, sort_keys=True).encode("utf-8")).hexdigest()[:24],
        trace_id=trace_id,
        messages=messages,
        labels={
            **labels,
            "reviewer_id": reviewer_id,
            "review_status": review_status,
            "consent_state": "training_opt_in",
            "redaction_status": "redacted",
            "route_question_type": metrics.get("route_question_type"),
            "risk_level": metrics.get("risk_level"),
            "repair_layer": repair_layer,
            "failure_class": failure_class,
            "ideal_answer": redact_training_text(str(ideal_answer)),
            "rejected_answer": redact_training_text(str(rejected_answer)) if rejected_answer else None,
            "source_evidence": source_evidence,
            "source_trace_id": trace_id,
            "source_lineage": training_lineage_snapshot(trace_payload, labels=labels),
        },
        dataset_card={
            "purpose": "Phase 5 reviewed, consented agronomy-agent answer-discipline candidate.",
            "consent": "research_and_training_opt_in",
            "redaction": "email_phone_regex_v1",
            "excluded": "all evaluation cases/answers/traces, unresolved lineage, unreviewed traces, prompt leaks, private field facts without consent",
        },
    )


def is_held_out_eval_trace(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> bool:
    """Compatibility name: identify *all* explicit evaluation lineage, including development.

    Exposure and original source-family names alone do not identify evaluation
    cases. A false flag cannot override a suite, case, answer, or trace identity.
    Training consumers must also use ``training_lineage_block_reason`` to block
    explicitly unresolved lineage; absence of a marker is not authorization.
    """
    return training_lineage_block_reason(trace_payload, labels=labels) == "evaluation_lineage"


def training_lineage_block_reason(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> str | None:
    unresolved = False
    for path, container in _lineage_containers(trace_payload, labels=labels):
        if _first_text(container.get("schema_version")) in EVALUATION_SCHEMAS or container.get("distribution_scope") == "machine_local_benchmark_only":
            return "evaluation_lineage"
        # These named containers are native evaluation artifacts, not original
        # source datasets. Retain their presence even after compacting lineage.
        for key in EVALUATION_CONTAINERS:
            if key in container:
                if isinstance(container[key], dict) and container[key]:
                    return "evaluation_lineage"
                unresolved = True
        if container.get("suite_id") and container.get("case_id") and _first_text(container.get("exposure")) in {"exposed_development", "prospective_confirmation"}:
            return "evaluation_lineage"
        for key in PROVENANCE_CONTAINERS:
            if key in container and not isinstance(container[key], (dict, list, tuple)):
                unresolved = True
        if "evaluation_lineage" in container and not container["evaluation_lineage"]:
            unresolved = True
        provenance_kind = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if provenance_kind in PROVENANCE_CONTAINERS and "status" in container:
            if str(container["status"] or "").strip().lower() in UNRESOLVED_LINEAGE_VALUES | {""}:
                unresolved = True
        for key in EVALUATION_FLAGS:
            if key not in container:
                continue
            value = container[key]
            if value is True or value == 1 or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}):
                return "evaluation_lineage"
            if value is not False and value != 0 and not (isinstance(value, str) and value.strip().lower() in {"false", "no", "0"}):
                unresolved = True
        for key in EVALUATION_IDS:
            if key not in container:
                continue
            value = container[key]
            if value is not None and str(value).strip().lower() not in {"", "unknown", "unresolved", "none", "null"}:
                return "evaluation_lineage"
            unresolved = True
        for key in SPLIT_KEYS:
            value = str(container.get(key) or "").strip().lower()
            if value in HELD_OUT_SPLIT_VALUES:
                return "evaluation_lineage"
            if key in container and (not value or value in UNRESOLVED_LINEAGE_VALUES):
                unresolved = True
        for key in LINEAGE_STATUS_KEYS:
            if key in container and str(container[key] or "").strip().lower() in UNRESOLVED_LINEAGE_VALUES | {""}:
                unresolved = True
    return "unresolved_lineage" if unresolved else None


def training_lineage_snapshot(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Preserve declarations, without certifying rights, consent, or non-evaluation status."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, container in _lineage_containers(trace_payload, labels=labels):
        markers = {key: value for key, value in container.items() if key in LINEAGE_SNAPSHOT_KEYS}
        for key in EVALUATION_CONTAINERS:
            if key in container:
                if isinstance(container[key], dict) and container[key]:
                    markers["is_evaluation_trace"] = True
                else:
                    markers["lineage_status"] = "unresolved"
        for key in PROVENANCE_CONTAINERS:
            if key in container and not isinstance(container[key], (dict, list, tuple)):
                markers["lineage_status"] = "unresolved"
        if "evaluation_lineage" in container and not container["evaluation_lineage"]:
            markers["lineage_status"] = "unresolved"
        provenance_kind = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if provenance_kind in PROVENANCE_CONTAINERS and "status" in container:
            markers["lineage_status"] = container["status"]
        if not markers:
            continue
        # Existing snapshots retain their original path rather than acquiring
        # an ever-growing labels.source_lineage prefix on every review.
        record = {"lineage_path": _first_text(container.get("lineage_path"), path), **markers}
        identity = json.dumps(record, sort_keys=True, default=str)
        if identity not in seen:
            seen.add(identity)
            records.append(record)
    return sorted(records, key=lambda record: json.dumps(record, sort_keys=True, default=str))


def _lineage_containers(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None):
    pending = [("payload", trace_payload), ("labels", labels or {})]
    seen: set[int] = set()
    while pending:
        path, value = pending.pop()
        if not isinstance(value, (dict, list, tuple)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, (list, tuple)):
            pending.extend((f"{path}[{index}]", item) for index, item in enumerate(value))
            continue
        yield path, value
        pending.extend((f"{path}.{key}", item) for key, item in value.items() if key in LINEAGE_CONTAINERS)


def contains_private_field_data(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> bool:
    labels = labels or {}
    trace = trace_payload.get("trace") if isinstance(trace_payload.get("trace"), dict) else {}
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    for container in (trace_payload, labels, trace, metadata):
        if bool(container.get("private_field_data") or container.get("contains_private_field_data")):
            return True
    return False


def has_explicit_private_training_consent(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> bool:
    labels = labels or {}
    for container in (trace_payload, labels):
        if bool(container.get("explicit_private_field_training_consent")):
            return True
        consent_scope = _first_text(container.get("consent_scope"), container.get("training_consent_scope")).lower()
        if consent_scope in {"private_field_training_opt_in", "explicit_private_field_training_opt_in"}:
            return True
    return False


def source_evidence_from_trace_payload(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> list[Any]:
    labels = labels or {}
    direct = trace_payload.get("source_evidence") or labels.get("source_evidence")
    if direct:
        return _as_evidence_list(direct)
    trace = trace_payload.get("trace") if isinstance(trace_payload.get("trace"), dict) else {}
    docs = trace.get("retrieved_docs") if isinstance(trace, dict) else []
    evidence = []
    for doc in docs or []:
        if isinstance(doc, dict):
            doc_id = _first_text(doc.get("doc_id"), doc.get("id"), doc.get("title"), doc.get("source"))
            if doc_id:
                evidence.append(
                    {
                        "doc_id": doc_id,
                        "title": doc.get("title"),
                        "source": doc.get("source"),
                        "source_type": doc.get("source_type"),
                    }
                )
        elif str(doc).strip():
            evidence.append(str(doc).strip())
    return evidence


def dedupe_candidates(candidates: list[SftCandidate]) -> list[SftCandidate]:
    seen: set[str] = set()
    deduped: list[SftCandidate] = []
    for candidate in candidates:
        if candidate.candidate_id in seen:
            continue
        seen.add(candidate.candidate_id)
        deduped.append(candidate)
    return deduped


def _as_evidence_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [item for item in value if str(item).strip()]
    if str(value).strip():
        return [str(value).strip()]
    return []


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
