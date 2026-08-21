"""Recipient-bound authorization gate for external semantic judging."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "open_agronomy_agent.semantic_judge_egress_authorization.v1"
REQUIRED_PAYLOAD_CLASSES = frozenset({
    "project_owned_frozen_benchmark_questions",
    "candidate_answers",
    "benchmark_reference_and_rubric_for_judging",
})
REQUIRED_CONTROL_IDS = frozenset({
    "answer_order_reversal",
    "concise_correct_vs_verbose_vague",
    "supported_vs_cosmetic_citation",
    "useful_caution_vs_blanket_refusal",
    "corrupted_reference_negative",
})


def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("authorization timestamps must include a timezone")
    return parsed.astimezone(dt.UTC)


@dataclass(frozen=True)
class JudgeAuthorizationGrant:
    authorization_source: str
    recipient_backend: str
    model_id: str
    generator_judge_relationship: str
    promotion_eligible: bool
    authorization_sha256: str


def validate_semantic_controls(controls: Mapping[str, Any]) -> str:
    rows = controls.get("controls") or []
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, Mapping)}
    missing = REQUIRED_CONTROL_IDS - set(by_id)
    failed = {key for key in REQUIRED_CONTROL_IDS & set(by_id) if by_id[key].get("passed") is not True}
    if missing or failed:
        raise ValueError(f"semantic controls not satisfied: missing={sorted(missing)} failed={sorted(failed)}")
    return canonical_sha256(controls)


def validate_judge_authorization(
    authorization: Mapping[str, Any],
    *,
    benchmark_contract_sha256: str,
    selected_rows_sha256: str,
    judge_prompt_sha256: str,
    judge_output_schema_sha256: str,
    semantic_controls_sha256: str,
    recipient_backend: str,
    model_id: str,
    source_model_ids: set[str],
    now: dt.datetime | None = None,
) -> JudgeAuthorizationGrant:
    if authorization.get("schema_version") != SCHEMA_VERSION or authorization.get("authorization_decision") != "authorized":
        raise ValueError("judge egress receipt is not an authorized v1 contract")
    expected = {
        "benchmark_contract_sha256": benchmark_contract_sha256,
        "selected_rows_sha256": selected_rows_sha256,
        "judge_prompt_sha256": judge_prompt_sha256,
        "judge_output_schema_sha256": judge_output_schema_sha256,
        "semantic_controls_sha256": semantic_controls_sha256,
        "recipient_backend": recipient_backend,
        "model_id": model_id,
    }
    for field, value in expected.items():
        if authorization.get(field) != value:
            raise ValueError(f"judge authorization {field} mismatch")
    authorized_classes = set(authorization.get("authorized_payload_classes") or [])
    if authorized_classes != REQUIRED_PAYLOAD_CLASSES:
        raise ValueError("judge authorization payload classes differ from the permitted taxonomy")
    current = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    if not (_utc(str(authorization["authorized_at"])) <= current < _utc(str(authorization["expires_at"]))):
        raise ValueError("judge authorization is outside its UTC validity interval")
    judge = model_id.strip().lower()
    sources = {value.strip().lower() for value in source_model_ids if value.strip()}
    relationship = "same_exact_model" if judge in sources else "cross_model"
    requested_relationship = str(authorization.get("generator_judge_relationship") or "")
    if requested_relationship != relationship:
        raise ValueError("judge authorization generator/judge relationship mismatch")
    promotion_eligible = bool(authorization.get("promotion_eligible"))
    if relationship == "same_exact_model" and promotion_eligible:
        raise ValueError("self-judged diagnostics cannot be promotion eligible")
    return JudgeAuthorizationGrant(
        authorization_source=str(authorization.get("authorization_source") or ""),
        recipient_backend=recipient_backend,
        model_id=model_id,
        generator_judge_relationship=relationship,
        promotion_eligible=promotion_eligible,
        authorization_sha256=canonical_sha256(authorization),
    )


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


__all__ = ["JudgeAuthorizationGrant", "canonical_sha256", "load_json_object", "validate_judge_authorization", "validate_semantic_controls"]
