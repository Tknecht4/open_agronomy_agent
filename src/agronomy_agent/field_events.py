from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable


FIELD_EVENT_SCHEMA = "open_agronomy_agent.field_event.v1"
FIELD_EVENT_CHAIN_SCHEMA = "open_agronomy_agent.field_event_chain.v1"
FIELD_EVENT_SYNC_SCHEMA = "open_agronomy_agent.field_event_sync.v1"
FIELD_EVENT_TYPES = frozenset(
    {
        "observation",
        "sample",
        "operation",
        "decision",
        "outcome",
        "note",
        "correction",
    }
)


class FieldEventSyncError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def timestamp_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def canonical_field_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return the exact immutable record covered by the event integrity hash."""

    return {
        "schema_version": FIELD_EVENT_SCHEMA,
        "id": str(event["id"]),
        "organization_id": str(event["organization_id"]),
        "workspace_id": str(event["workspace_id"]),
        "field_context_id": str(event["field_context_id"]),
        "recorded_by_user_id": (
            str(event["recorded_by_user_id"]) if event.get("recorded_by_user_id") is not None else None
        ),
        "event_type": str(event["event_type"]),
        "occurred_at": timestamp_text(event.get("occurred_at")),
        "payload": event.get("payload") if isinstance(event.get("payload"), dict) else {},
        "provenance": event.get("provenance") if isinstance(event.get("provenance"), dict) else {},
        "corrects_event_id": (
            str(event["corrects_event_id"]) if event.get("corrects_event_id") is not None else None
        ),
        "previous_event_sha256": event.get("previous_event_sha256"),
        "recorded_at": timestamp_text(event.get("recorded_at")),
    }


def field_event_integrity_sha256(event: dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_field_event(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_field_event_chain(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    failures: list[dict[str, Any]] = []
    previous_sha256: str | None = None
    seen_ids: set[str] = set()

    for position, event in enumerate(rows):
        event_id = str(event.get("id") or "")
        actual_previous = event.get("previous_event_sha256")
        actual_integrity = event.get("integrity_sha256")
        expected_integrity = field_event_integrity_sha256(event)
        if not event_id or event_id in seen_ids:
            failures.append(
                {
                    "position": position,
                    "event_id": event_id or None,
                    "reason": "missing_or_duplicate_event_id",
                }
            )
        seen_ids.add(event_id)
        if actual_previous != previous_sha256:
            failures.append(
                {
                    "position": position,
                    "event_id": event_id or None,
                    "reason": "previous_event_sha256_mismatch",
                    "expected": previous_sha256,
                    "actual": actual_previous,
                }
            )
        if actual_integrity != expected_integrity:
            failures.append(
                {
                    "position": position,
                    "event_id": event_id or None,
                    "reason": "integrity_sha256_mismatch",
                    "expected": expected_integrity,
                    "actual": actual_integrity,
                }
            )
        previous_sha256 = actual_integrity

    return {
        "schema_version": FIELD_EVENT_CHAIN_SCHEMA,
        "valid": not failures,
        "event_count": len(rows),
        "head_sha256": previous_sha256,
        "failure_count": len(failures),
        "failures": failures,
    }


def field_event_sync_export(
    events: Iterable[dict[str, Any]],
    *,
    field_context_id: str,
    after_sha256: str | None = None,
) -> dict[str, Any]:
    rows = list(events)
    chain = verify_field_event_chain(rows)
    if not chain["valid"]:
        raise FieldEventSyncError(
            "local_chain_invalid",
            "local field-event chain is invalid and cannot be exported for synchronization",
            chain=chain,
        )
    start = 0
    if after_sha256 is not None:
        matches = [
            index
            for index, event in enumerate(rows)
            if event.get("integrity_sha256") == after_sha256
        ]
        if len(matches) != 1:
            raise FieldEventSyncError(
                "unknown_base_head",
                "requested synchronization base is not present in this field history",
                requested_base_head_sha256=after_sha256,
                local_head_sha256=chain["head_sha256"],
            )
        start = matches[0] + 1
    exported = rows[start:]
    return {
        "schema_version": FIELD_EVENT_SYNC_SCHEMA,
        "field_context_id": field_context_id,
        "base_head_sha256": after_sha256,
        "head_sha256": chain["head_sha256"],
        "event_count": len(exported),
        "events": exported,
        "chain": chain,
        "boundary": (
            "This is an append-only fast-forward envelope. A receiver must reject a divergent local head "
            "and preserve both branches for human reconciliation; branches are never silently merged."
        ),
    }


def validate_field_event_fast_forward(
    *,
    local_events: Iterable[dict[str, Any]],
    incoming_events: Iterable[dict[str, Any]],
    field_context: dict[str, Any],
    syncing_user_id: str,
    base_head_sha256: str | None,
) -> dict[str, Any]:
    local = list(local_events)
    incoming = list(incoming_events)
    local_chain = verify_field_event_chain(local)
    if not local_chain["valid"]:
        raise FieldEventSyncError(
            "local_chain_invalid",
            "local field-event chain is invalid and cannot accept synchronization",
            chain=local_chain,
        )
    if not incoming:
        raise FieldEventSyncError("empty_batch", "field-event synchronization requires at least one event")
    if len(incoming) > 100:
        raise FieldEventSyncError("batch_too_large", "field-event synchronization accepts at most 100 events")

    local_by_id = {str(event.get("id") or ""): event for event in local}
    incoming_ids: set[str] = set()
    for event in incoming:
        event_id = str(event.get("id") or "")
        if not event_id or event_id in incoming_ids:
            raise FieldEventSyncError(
                "duplicate_event_id",
                "synchronization events must have unique non-empty ids",
                event_id=event_id or None,
            )
        incoming_ids.add(event_id)
        _validate_sync_event_identity(
            event,
            field_context=field_context,
            syncing_user_id=syncing_user_id,
        )
        expected = field_event_integrity_sha256(event)
        if event.get("integrity_sha256") != expected:
            raise FieldEventSyncError(
                "integrity_sha256_mismatch",
                "synchronization event integrity hash does not match its canonical content",
                event_id=event_id,
                expected=expected,
                actual=event.get("integrity_sha256"),
            )

    overlap = incoming_ids & local_by_id.keys()
    accepted_full_prefix = False
    if overlap:
        collisions = [
            event_id
            for event_id in sorted(overlap)
            if local_by_id[event_id].get("integrity_sha256")
            != next(
                event.get("integrity_sha256")
                for event in incoming
                if str(event.get("id") or "") == event_id
            )
        ]
        if collisions:
            raise FieldEventSyncError(
                "event_id_collision",
                "an incoming event id already exists with different canonical content",
                event_ids=collisions,
            )
        if overlap == incoming_ids:
            return {
                "status": "already_applied",
                "local_head_sha256": local_chain["head_sha256"],
                "event_count": 0,
                "events": [],
            }
        accepted_full_prefix = (
            base_head_sha256 is None
            and len(incoming) > len(local)
            and all(
                str(incoming[index].get("id") or "") == str(local[index].get("id") or "")
                and incoming[index].get("integrity_sha256") == local[index].get("integrity_sha256")
                for index in range(len(local))
            )
        )
        if accepted_full_prefix:
            incoming = incoming[len(local):]
            incoming_ids = {str(event["id"]) for event in incoming}
            base_head_sha256 = local_chain["head_sha256"]
        else:
            raise FieldEventSyncError(
                "partial_overlap",
                "incoming synchronization batch partially overlaps local history without matching its complete prefix",
                overlapping_event_ids=sorted(overlap),
                local_head_sha256=local_chain["head_sha256"],
            )

    if base_head_sha256 != local_chain["head_sha256"]:
        raise FieldEventSyncError(
            "divergent_head",
            "local and incoming field histories have diverged; automatic merge is refused",
            requested_base_head_sha256=base_head_sha256,
            local_head_sha256=local_chain["head_sha256"],
            resolution=(
                "Export and preserve both branches. Review the conflicting observations, then append a new "
                "note or correction to the chosen local branch; do not rewrite either history."
            ),
        )

    known_correction_targets = set(local_by_id)
    expected_previous = base_head_sha256
    previous_order = _event_order(local[-1]) if local else None
    for event in incoming:
        event_id = str(event["id"])
        if event.get("previous_event_sha256") != expected_previous:
            raise FieldEventSyncError(
                "previous_event_sha256_mismatch",
                "incoming events do not form a fast-forward chain from the requested base",
                event_id=event_id,
                expected=expected_previous,
                actual=event.get("previous_event_sha256"),
            )
        corrects_event_id = (
            str(event["corrects_event_id"]) if event.get("corrects_event_id") is not None else None
        )
        if corrects_event_id and corrects_event_id not in known_correction_targets:
            raise FieldEventSyncError(
                "unknown_correction_target",
                "an incoming correction does not reference local or earlier incoming history",
                event_id=event_id,
                corrects_event_id=corrects_event_id,
            )
        order = _event_order(event)
        if previous_order is not None and order <= previous_order:
            raise FieldEventSyncError(
                "recorded_order_conflict",
                "incoming recorded_at/id order would invalidate the append-only chain",
                event_id=event_id,
            )
        previous_order = order
        expected_previous = str(event["integrity_sha256"])
        known_correction_targets.add(event_id)

    combined_chain = verify_field_event_chain([*local, *incoming])
    if not combined_chain["valid"]:
        raise FieldEventSyncError(
            "combined_chain_invalid",
            "incoming events do not produce a valid combined field-event chain",
            chain=combined_chain,
        )
    return {
        "status": "ready",
        "local_head_sha256": local_chain["head_sha256"],
        "result_head_sha256": combined_chain["head_sha256"],
        "event_count": len(incoming),
        "events": incoming,
        "accepted_full_prefix": accepted_full_prefix,
    }


def _validate_sync_event_identity(
    event: dict[str, Any],
    *,
    field_context: dict[str, Any],
    syncing_user_id: str,
) -> None:
    expected = {
        "organization_id": str(field_context["organization_id"]),
        "workspace_id": str(field_context["workspace_id"]),
        "field_context_id": str(field_context["id"]),
        "recorded_by_user_id": str(syncing_user_id),
    }
    for key, value in expected.items():
        actual = str(event.get(key) or "")
        if actual != value:
            raise FieldEventSyncError(
                f"{key}_mismatch",
                f"incoming event {key} does not match the authenticated field synchronization scope",
                event_id=str(event.get("id") or "") or None,
                expected=value,
                actual=actual or None,
            )
    event_type = str(event.get("event_type") or "")
    corrects_event_id = event.get("corrects_event_id")
    if event_type not in FIELD_EVENT_TYPES:
        raise FieldEventSyncError("unsupported_event_type", f"unsupported field event type: {event_type}")
    if (event_type == "correction") != bool(corrects_event_id):
        raise FieldEventSyncError(
            "invalid_correction_shape",
            "correction events must identify exactly one corrected field event",
        )


def _event_order(event: dict[str, Any]) -> tuple[datetime, str]:
    value = timestamp_text(event.get("recorded_at"))
    if not value:
        raise FieldEventSyncError("missing_recorded_at", "synchronization events require recorded_at")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        recorded_at = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise FieldEventSyncError(
            "invalid_recorded_at",
            "synchronization event recorded_at must be ISO-8601",
        ) from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise FieldEventSyncError(
            "invalid_recorded_at",
            "synchronization event recorded_at must include a timezone",
        )
    return recorded_at, str(event.get("id") or "")
