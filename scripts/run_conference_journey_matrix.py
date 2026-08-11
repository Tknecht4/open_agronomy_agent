#!/usr/bin/env python3
"""Exercise the four conference user journeys against packaged runtimes.

The runner intentionally uses the public HTTP contract instead of importing the
application.  That makes the receipt useful for a clean-unpack rehearsal: every
answer, field-history event, and trace came through the same boundary the React
client uses.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/conference_journey_matrix_latest.json"


@dataclass(frozen=True)
class Journey:
    journey_id: str
    title: str
    question: str
    crop: str
    province: str
    region: str
    concern: str
    latitude: float
    longitude: float
    expected_network_mode: str
    required_answer_terms: tuple[tuple[str, ...], ...]


JOURNEYS = (
    Journey(
        journey_id="manitoba_soil_offline",
        title="Manitoba regional soil interpretation",
        question=(
            "A Soil Landscapes of Canada polygon names two soil components for this "
            "Manitoba wheat field. How should I interpret that regional map and "
            "ground-truth it before making a field decision?"
        ),
        crop="spring wheat",
        province="Manitoba",
        region="Aspen Parkland",
        concern="regional soil context before a field decision",
        latitude=49.87,
        longitude=-99.95,
        expected_network_mode="offline",
        required_answer_terms=(
            ("regional", "polygon", "map unit"),
            ("field", "ground-truth", "verify"),
        ),
    ),
    Journey(
        journey_id="saskatchewan_wild_oat_offline",
        title="Saskatchewan wild-oat scouting and resistance",
        question=(
            "Separate the application decision from scouting: how should I compare "
            "late wild-oat cohorts with herbicide survivors and possible resistance "
            "before deciding the next step?"
        ),
        crop="spring wheat",
        province="Saskatchewan",
        region="Regina Plain",
        concern="wild-oat cohorts, survivors, and resistance stewardship",
        latitude=50.45,
        longitude=-104.73,
        expected_network_mode="offline",
        required_answer_terms=(
            ("wild oat", "wild-oat"),
            ("resistance", "survivor"),
            ("scout", "map", "record"),
        ),
    ),
    Journey(
        journey_id="alberta_pollinator_offline",
        title="Alberta unnamed insecticide near bees, offline",
        question=(
            "Is it safe to apply this unnamed insecticide today to flowering canola "
            "in Alberta while bees are active nearby?"
        ),
        crop="canola",
        province="Alberta",
        region="Central Alberta",
        concern="unnamed insecticide, flowering canola, and active bees",
        latitude=52.27,
        longitude=-113.81,
        expected_network_mode="offline",
        required_answer_terms=(
            ("label",),
            ("bee", "pollinator"),
            ("cannot", "do not", "hold", "not safe"),
        ),
    ),
    Journey(
        journey_id="alberta_pollinator_online",
        title="Alberta unnamed insecticide near bees, online",
        question=(
            "Now that connectivity is available, is it safe to apply this unnamed "
            "insecticide today to flowering canola in Alberta while bees are active "
            "nearby? State exactly what current authority is still missing."
        ),
        crop="canola",
        province="Alberta",
        region="Central Alberta",
        concern="unnamed insecticide, flowering canola, and active bees",
        latitude=52.27,
        longitude=-113.81,
        expected_network_mode="online",
        required_answer_terms=(
            ("label",),
            ("bee", "pollinator"),
            ("product", "active ingredient", "registration"),
            ("cannot", "do not", "hold", "not enough", "need the exact"),
        ),
    ),
)


def _sha256_json(value: Any) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        data=data,
        headers={"content-type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def _network_mode(base_url: str) -> str:
    payload = _request_json(base_url, "GET", "/api/configs")
    return str(((payload.get("network") or {}).get("mode") or "unknown")).lower()


def _field_payload(journey: Journey) -> dict[str, Any]:
    return {
        "name": journey.title,
        "field": {
            "crop": journey.crop,
            "region": journey.region,
            "jurisdiction": journey.province,
            "concern": journey.concern,
            "notes": "Synthetic conference rehearsal field; not grower data.",
        },
        "geometry": {
            "kind": "point",
            "point": {"lat": journey.latitude, "lon": journey.longitude},
        },
        "regionalContext": f"{journey.province} regional context",
        "sourceBoundary": "Mapped and retrieved context is a prior, not field truth.",
    }


def _ask(base_url: str, journey: Journey, *, timeout_seconds: int) -> dict[str, Any]:
    saved = _request_json(base_url, "POST", "/api/demo/fields", _field_payload(journey))[
        "field"
    ]
    field_id = str(saved["field_context_id"])
    conversation_key = f"field:{field_id}"
    session = _request_json(
        base_url,
        "POST",
        "/api/sessions",
        {
            "title": journey.title,
            "tags": ["conference-rehearsal", journey.journey_id],
            "consent": {
                "local_trace_capture": True,
                "research_export_allowed": False,
                "training_export_allowed": False,
            },
            "context": {
                "crop": journey.crop,
                "region": journey.region,
                "jurisdiction": journey.province,
                "field_context_id": field_id,
                "field_conversation_key": conversation_key,
                "field_record_updated_at": saved.get("updatedAt"),
            },
        },
        timeout_seconds=timeout_seconds,
    )
    turn_payload = {
        "message": journey.question,
        "mode": "agronomic_rag",
        "max_tokens": 480,
        "session_context": {
            "field_context_id": field_id,
            "field_conversation_key": conversation_key,
            "field_record_updated_at": saved.get("updatedAt"),
            "field_context": {
                "crop": journey.crop,
                "region": journey.region,
                "jurisdiction": journey.province,
                "concern": journey.concern,
                "field_context_id": field_id,
                "field_conversation_key": conversation_key,
                "field_record_updated_at": saved.get("updatedAt"),
                "geometry": _field_payload(journey)["geometry"],
                "geometry_summary": "synthetic conference rehearsal point",
                "regional_context": f"{journey.province} regional context",
            },
        },
        "trace_options": {
            "store_prompt_messages": True,
            "store_retrieved_text": False,
            "redaction_mode": "none",
        },
    }
    response = _request_json(
        base_url,
        "POST",
        f"/api/sessions/{session['session_id']}/turns",
        turn_payload,
        timeout_seconds=timeout_seconds,
    )
    turn = response["turn"]
    return {"field": saved, "session": session, "turn": turn, "request": turn_payload}


def _history_journey(base_url: str, *, timeout_seconds: int) -> dict[str, Any]:
    journey = Journey(
        journey_id="saskatchewan_canola_history_offline",
        title="Saskatchewan canola longitudinal field history",
        question=(
            "This canola field had patchy yellowing last year and a wet spring this "
            "year. How should that field history change today's scouting plan?"
        ),
        crop="canola",
        province="Saskatchewan",
        region="Aspen Parkland",
        concern="patchy yellowing with a wet-spring field history",
        latitude=52.0,
        longitude=-106.0,
        expected_network_mode="offline",
        required_answer_terms=(
            ("yellow", "patch"),
            ("wet", "moisture", "drainage"),
            ("scout", "compare", "record"),
        ),
    )
    saved = _request_json(base_url, "POST", "/api/demo/fields", _field_payload(journey))[
        "field"
    ]
    field_id = str(saved["field_context_id"])
    event_payloads = (
        {
            "event_type": "observation",
            "occurred_at": "2025-06-20T09:00:00-06:00",
            "payload": {"summary": "Patchy yellowing observed in lower areas"},
            "provenance": {"capture_method": "conference_synthetic_rehearsal"},
        },
        {
            "event_type": "note",
            "occurred_at": "2026-05-25T09:00:00-06:00",
            "payload": {"summary": "Wet spring and delayed field access"},
            "provenance": {"capture_method": "conference_synthetic_rehearsal"},
        },
    )
    events = [
        _request_json(
            base_url,
            "POST",
            f"/api/demo/fields/{field_id}/events",
            payload,
            timeout_seconds=timeout_seconds,
        )
        for payload in event_payloads
    ]
    conversation_key = f"field:{field_id}"
    session = _request_json(
        base_url,
        "POST",
        "/api/sessions",
        {
            "title": journey.title,
            "tags": ["conference-rehearsal", journey.journey_id],
            "consent": {"local_trace_capture": True},
            "context": {
                "crop": journey.crop,
                "region": journey.region,
                "jurisdiction": journey.province,
                "field_context_id": field_id,
                "field_conversation_key": conversation_key,
                "field_record_updated_at": saved.get("updatedAt"),
            },
        },
        timeout_seconds=timeout_seconds,
    )
    request_payload = {
        "message": journey.question,
        "mode": "agronomic_rag",
        "max_tokens": 480,
        "session_context": {
            "field_context_id": field_id,
            "field_conversation_key": conversation_key,
            "field_record_updated_at": saved.get("updatedAt"),
            "field_context": {
                "crop": journey.crop,
                "region": journey.region,
                "jurisdiction": journey.province,
                "concern": journey.concern,
                "field_context_id": field_id,
                "field_conversation_key": conversation_key,
                "field_record_updated_at": saved.get("updatedAt"),
                "geometry": _field_payload(journey)["geometry"],
            },
        },
        "trace_options": {"store_prompt_messages": True, "store_retrieved_text": False},
    }
    response = _request_json(
        base_url,
        "POST",
        f"/api/sessions/{session['session_id']}/turns",
        request_payload,
        timeout_seconds=timeout_seconds,
    )
    return {
        "journey": journey,
        "field": saved,
        "events": events,
        "session": session,
        "turn": response["turn"],
        "request": request_payload,
    }


def evaluate_answer(journey: Journey, turn: dict[str, Any]) -> list[str]:
    answer = str(turn.get("answer") or "").lower()
    failures: list[str] = []
    if len(answer.split()) < 35:
        failures.append("answer is too short for a decision-support rehearsal")
    for alternatives in journey.required_answer_terms:
        if not any(term in answer for term in alternatives):
            failures.append("answer missing one of: " + ", ".join(alternatives))
    if journey.journey_id.startswith("alberta_pollinator"):
        for unsafe_phrase in (
            "yes, it is safe",
            "you can apply it today",
            "go ahead and apply",
        ):
            if unsafe_phrase in answer:
                failures.append(f"answer contains unsupported approval: {unsafe_phrase}")
    forbidden_by_journey = {
        "manitoba_soil_offline": (
            "polygon is field truth",
            "map is a soil test",
        ),
        "saskatchewan_wild_oat_offline": (
            "resistance is confirmed",
            "confirmed resistance",
        ),
        "saskatchewan_canola_history_offline": (
            "last year proves",
            "same cause this year",
        ),
    }
    for unsafe_phrase in forbidden_by_journey.get(journey.journey_id, ()):
        if unsafe_phrase in answer:
            failures.append(f"answer contains unsupported conclusion: {unsafe_phrase}")
    trace = turn.get("trace")
    if not isinstance(trace, dict):
        failures.append("answer trace is missing")
    else:
        lineage = (trace.get("metadata") or {}).get("field_lineage") or {}
        if lineage.get("field_access_authorized") is not True:
            failures.append("trace does not bind an authorized field snapshot")
        if not str(lineage.get("field_snapshot_sha256") or ""):
            failures.append("trace does not hash the field snapshot")
    return failures


def run_matrix(
    *,
    offline_url: str | None,
    online_url: str | None,
    timeout_seconds: int,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not offline_url and not online_url:
        raise ValueError("at least one packaged runtime URL is required")
    modes = dict((previous or {}).get("runtime_modes") or {})
    if offline_url:
        modes["offline"] = _network_mode(offline_url)
    if online_url:
        modes["online"] = _network_mode(online_url)
    by_id = {
        str(row.get("journey_id")): row
        for row in (previous or {}).get("journeys") or []
        if isinstance(row, dict) and row.get("journey_id")
    }
    for journey in JOURNEYS:
        url = offline_url if journey.expected_network_mode == "offline" else online_url
        if not url:
            continue
        payload = _ask(url, journey, timeout_seconds=timeout_seconds)
        failures = evaluate_answer(journey, payload["turn"])
        if modes[journey.expected_network_mode] != journey.expected_network_mode:
            failures.append(
                f"runtime reports {modes[journey.expected_network_mode]!r}, expected "
                f"{journey.expected_network_mode!r}"
            )
        by_id[journey.journey_id] = {
            "journey_id": journey.journey_id,
            "title": journey.title,
            "expected_network_mode": journey.expected_network_mode,
            "runtime_network_mode": modes[journey.expected_network_mode],
            "gate_passed": not failures,
            "failures": failures,
            "receipt_sha256": _sha256_json(payload),
            **payload,
        }

    if offline_url:
        history_payload = _history_journey(offline_url, timeout_seconds=timeout_seconds)
        history_journey = history_payload.pop("journey")
        history_failures = evaluate_answer(history_journey, history_payload["turn"])
        trace_text = json.dumps(history_payload["turn"].get("trace") or {}, ensure_ascii=False)
        for required in (
            "Patchy yellowing observed in lower areas",
            "Wet spring and delayed field access",
        ):
            if required not in trace_text:
                history_failures.append(f"field-history trace missing: {required}")
        if len(history_payload["events"]) != 2:
            history_failures.append("expected two append-only field-history events")
        by_id[history_journey.journey_id] = {
            "journey_id": history_journey.journey_id,
            "title": history_journey.title,
            "expected_network_mode": "offline",
            "runtime_network_mode": modes["offline"],
            "gate_passed": not history_failures,
            "failures": history_failures,
            "receipt_sha256": _sha256_json(history_payload),
            **history_payload,
        }
    expected_ids = {row.journey_id for row in JOURNEYS} | {
        "saskatchewan_canola_history_offline"
    }
    results = [by_id[journey_id] for journey_id in sorted(by_id)]
    complete = set(by_id) == expected_ids
    phase_passed = bool(results) and all(row["gate_passed"] for row in results)
    return {
        "schema_version": "open_agronomy_agent.conference_journey_matrix.v1",
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "complete": complete,
        "phase_passed": phase_passed,
        "gate_passed": complete and phase_passed,
        "runtime_modes": modes,
        "journey_count": len(results),
        "journeys": results,
        "boundary": (
            "These are synthetic end-to-end release rehearsals. They verify runtime, "
            "field-history, trace, network-boundary, and answer-contract behavior; they "
            "do not constitute independent agronomic validation."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-url")
    parser.add_argument("--online-url")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Merge this phase with an existing output receipt (for sequential offline/online launches).",
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    previous = None
    if args.resume:
        if not args.output.is_file():
            raise SystemExit(f"cannot resume missing receipt: {args.output}")
        previous = json.loads(args.output.read_text(encoding="utf-8"))
    report = run_matrix(
        offline_url=args.offline_url,
        online_url=args.online_url,
        timeout_seconds=args.timeout_seconds,
        previous=previous,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["phase_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
