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
    if is_held_out_eval_trace(trace_payload, labels=labels):
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
    trace_id = str(trace_payload.get("trace_id") or metrics.get("trace_id"))
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
        },
        dataset_card={
            "purpose": "Phase 5 reviewed, consented agronomy-agent answer-discipline candidate.",
            "consent": "research_and_training_opt_in",
            "redaction": "email_phone_regex_v1",
            "excluded": "unreviewed traces, prompt leaks, private field facts without consent",
        },
    )


def is_held_out_eval_trace(trace_payload: dict[str, Any], *, labels: dict[str, Any] | None = None) -> bool:
    labels = labels or {}
    trace = trace_payload.get("trace") if isinstance(trace_payload.get("trace"), dict) else {}
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    for container in (trace_payload, labels, trace, metadata):
        if bool(container.get("held_out_eval") or container.get("is_held_out") or container.get("held_out")):
            return True
        split = _first_text(
            container.get("split"),
            container.get("dataset_split"),
            container.get("eval_split"),
            container.get("data_split"),
        ).lower()
        if split in HELD_OUT_SPLIT_VALUES:
            return True
    return False


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
