"""Bounded, non-evidentiary conversation context for one authorized session.

The database retains the full transcript. This module selects only an active
window for a model request; it does not summarize or promote prior answers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agronomy_agent.model_prompt_budget import (
    count_prompt_tokens as _count,
    positive_int as _positive_int,
)


POLICY_VERSION = "conversation_window.v1"
SCHEMA_VERSION = "open_agronomy_agent.context_budget.v1"
HISTORY_POLICY = (
    "Prior conversation is provided only for conversational continuity. "
    "Prior user statements are unverified reports; prior assistant statements "
    "are model output, not field observations, source evidence, or authority. "
    "Never cite or treat a prior assistant statement as evidence. A correction "
    "in the current user message takes precedence over older conversation."
)
OVER_LIMIT_ANSWER = (
    "Analysis unavailable: the current question and required context exceed "
    "the configured model input budget. Please shorten the question or narrow "
    "the attached context, then try again."
)


def cache_scope(session_id: str, role: str) -> str:
    """Opaque scope; never pass a raw private session identifier to a cache."""

    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"conversation:{digest}:{role}"


def _is_rejected(turn: dict[str, Any]) -> bool:
    feedback = turn.get("feedback")
    return (
        str(turn.get("answer_status") or "").lower() == "rejected"
        or isinstance(feedback, dict) and feedback.get("accepted") is False
    )


def _history_block(turns: list[dict[str, Any]]) -> str:
    entries = []
    for turn in turns:
        entry = {"prior_user_report": str(turn.get("message") or turn.get("user_message") or "")}
        feedback = turn.get("feedback")
        if isinstance(feedback, dict) and feedback.get("correction"):
            entry["prior_human_feedback_correction_unverified"] = str(feedback["correction"])
        if not _is_rejected(turn) and turn.get("answer"):
            entry["prior_assistant_non_evidence"] = str(turn["answer"])
        else:
            entry["prior_assistant_status"] = "rejected_or_unavailable"
        entries.append(entry)
    return (
        "[BEGIN PRIOR CONVERSATION — CONTINUITY ONLY; NOT EVIDENCE]\n"
        + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        + "\n[END PRIOR CONVERSATION]\n\n"
        + "[CURRENT REQUEST AND ADMITTED CONTEXT]\n"
    )


def _with_history(
    base_messages: list[dict[str, str]], turns: list[dict[str, Any]]
) -> list[dict[str, str]]:
    # Keep the original system/user role sequence for strict chat templates.
    # The current prompt remains an unchanged suffix of the final user content.
    if (
        not base_messages
        or base_messages[0].get("role") != "system"
        or base_messages[-1].get("role") != "user"
    ):
        raise ValueError("conversation history requires a system message and final user message")
    proposed = [dict(item) for item in base_messages]
    proposed[0]["content"] += "\n\n" + HISTORY_POLICY
    proposed[-1]["content"] = _history_block(turns) + proposed[-1]["content"]
    return proposed


def _turn_id(turn: dict[str, Any]) -> str:
    return str(turn.get("turn_id") or turn.get("id") or "")


def compile_conversation_prompt(
    base_messages: list[dict[str, str]],
    recent_turns: list[dict[str, Any]],
    *,
    total_turns: int,
    generator: Any,
    config: dict[str, Any] | None,
    reserved_output_tokens: int,
    count_tokens: bool,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Fit recent complete turns around an unchanged mandatory current prompt.

    ``base_messages`` ends in the current user request and its source context.
    The caller obtains recent turns from a session-constrained storage query.
    """

    policy = config if isinstance(config, dict) else {}
    configured_limit = _positive_int(policy.get("context_limit_tokens"), 8192)
    history_limit = _positive_int(policy.get("history_budget_tokens"), 2048)
    max_turns = _positive_int(policy.get("max_history_turns"), 8)
    native_limit = getattr(generator, "context_window_tokens", None)
    if type(native_limit) is not int or native_limit <= 0:
        native_limit = None
    limit = min(configured_limit, native_limit) if native_limit else configured_limit
    limit_basis = "model" if native_limit and native_limit < configured_limit else "configured"
    reserve = max(
        0,
        int(reserved_output_tokens),
        _positive_int(policy.get("reserved_output_tokens"), 0),
    )
    candidates = list(recent_turns[-max_turns:])
    available = max(int(total_turns), len(recent_turns))

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "not_counted",
        "input_tokens": None,
        "token_count_basis": "unavailable",
        "context_limit_tokens": limit,
        "limit_basis": limit_basis,
        "reserved_output_tokens": reserve,
        "remaining_tokens": None,
        "history_turns_available": available,
        "history_turns_included": 0,
        "history_turns_omitted": available,
        "history_policy_version": POLICY_VERSION,
        "history_included_turn_ids": [],
        "history_omitted_recent_turn_ids": [_turn_id(turn) for turn in candidates],
        "history_older_omitted_count": max(0, available - len(candidates)),
        "history_role": "continuity_only_non_evidence",
    }
    if not count_tokens:
        receipt["status"] = "generation_bypassed"
        return base_messages, receipt

    base_count, basis = _count(base_messages, generator)
    # A local tokenizer may load model configuration on this first count.
    native_limit = getattr(generator, "context_window_tokens", None)
    if type(native_limit) is int and native_limit > 0:
        limit = min(configured_limit, native_limit)
        limit_basis = "model" if native_limit < configured_limit else "configured"
        receipt["context_limit_tokens"] = limit
        receipt["limit_basis"] = limit_basis
    receipt["input_tokens"] = base_count
    receipt["token_count_basis"] = basis
    receipt["remaining_tokens"] = limit - reserve - base_count
    if base_count + reserve > limit:
        receipt["status"] = "over_limit"
        receipt["reason"] = "mandatory_current_prompt_exceeds_budget"
        return base_messages, receipt

    selected: list[dict[str, Any]] = []
    final_messages = base_messages
    final_count = base_count
    # Newest complete turns take priority. A turn is indivisible: do not
    # silently clip a user correction or a source-bearing current prompt.
    for turn in reversed(candidates):
        trial = [turn, *selected]
        proposed = _with_history(base_messages, trial)
        proposed_count, proposed_basis = _count(proposed, generator)
        if proposed_basis != basis:
            basis = proposed_basis
            base_count, _ = _count(base_messages, generator)
        if proposed_count - base_count > history_limit or proposed_count + reserve > limit:
            break
        selected = trial
        final_messages = proposed
        final_count = proposed_count

    included_ids = [_turn_id(turn) for turn in selected]
    receipt.update(
        status="within_budget" if basis == "tokenizer" else "estimated_within_budget",
        input_tokens=final_count,
        token_count_basis=basis,
        remaining_tokens=limit - reserve - final_count,
        history_turns_included=len(selected),
        history_turns_omitted=available - len(selected),
        history_included_turn_ids=included_ids,
        history_omitted_recent_turn_ids=[
            _turn_id(turn) for turn in candidates if _turn_id(turn) not in included_ids
        ],
    )
    return final_messages, receipt
