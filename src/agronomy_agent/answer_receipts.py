from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping


ANSWER_RECEIPT_SCHEMA_VERSION = "open_agronomy_agent.answer_integrity_receipt.v1"
ANSWER_RECEIPT_METADATA_KEY = "answer_integrity_receipt"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _field_snapshot_sha256(trace: Any) -> str | None:
    if not isinstance(trace, Mapping):
        return None
    metadata = trace.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    lineage = metadata.get("field_lineage")
    if not isinstance(lineage, Mapping):
        return None
    value = lineage.get("field_snapshot_sha256")
    if not isinstance(value, str) or len(value) != 64:
        return None
    return value.lower()


def _normalized_trace(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(trace or {})
    normalized.setdefault("route", None)
    for key in ("retrieved_docs", "graph_hits", "tool_invocations"):
        normalized.setdefault(key, [])
    return normalized


def build_answer_integrity_receipt(
    *,
    session_id: str,
    turn_id: str,
    created_at: str,
    user_message: str,
    answer: str,
    system_state: Mapping[str, Any] | None,
    trace: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the immutable content receipt stored beside a new answer turn."""

    receipt: dict[str, Any] = {
        "schema_version": ANSWER_RECEIPT_SCHEMA_VERSION,
        "session_id": session_id,
        "turn_id": turn_id,
        "created_at": created_at,
        "question_sha256": _sha256_text(user_message),
        "answer_sha256": _sha256_text(answer),
        "trace_sha256": _sha256_json(_normalized_trace(trace)),
        "system_state_sha256": _sha256_json(system_state or {}),
        "field_snapshot_sha256": _field_snapshot_sha256(trace),
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return receipt


def verify_answer_integrity_receipt(turn: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a stored receipt without treating legacy turns as verified."""

    expected = build_answer_integrity_receipt(
        session_id=str(turn.get("session_id") or ""),
        turn_id=str(turn.get("turn_id") or turn.get("id") or ""),
        created_at=str(turn.get("created_at") or ""),
        user_message=str(turn.get("user_message") or ""),
        answer=str(turn.get("answer") or ""),
        system_state=turn.get("system_state") if isinstance(turn.get("system_state"), Mapping) else {},
        trace=turn.get("trace") if isinstance(turn.get("trace"), Mapping) else {},
    )
    metadata = turn.get("metadata")
    stored = (
        metadata.get(ANSWER_RECEIPT_METADATA_KEY)
        if isinstance(metadata, Mapping)
        else None
    )
    boundary = (
        "Application-level immutable content receipt; not a digital signature, "
        "trusted timestamp, or external attestation."
    )
    if not isinstance(stored, Mapping):
        return {
            "schema_version": ANSWER_RECEIPT_SCHEMA_VERSION,
            "status": "legacy_not_captured",
            "receipt_sha256": None,
            "current_answer_sha256": expected["answer_sha256"],
            "current_trace_sha256": expected["trace_sha256"],
            "field_snapshot_sha256": expected["field_snapshot_sha256"],
            "boundary": boundary,
        }

    stored_receipt = dict(stored)
    valid = (
        stored_receipt.get("schema_version") == ANSWER_RECEIPT_SCHEMA_VERSION
        and hmac.compare_digest(
            _canonical_json(stored_receipt),
            _canonical_json(expected),
        )
    )
    return {
        **stored_receipt,
        "status": "verified" if valid else "invalid",
        "boundary": boundary,
    }
