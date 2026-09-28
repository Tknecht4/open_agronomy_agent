"""Resolve a narrow numeric follow-up from authorized same-session user text.

This is a pre-routing text operation, not a source of field evidence. The caller
supplies the recent, session-scoped turns it already authorized for conversation
continuity. Assistant answers and feedback never supply an operand or a task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agronomy_agent.tool_planner import plan_tools


POLICY_VERSION = "conversation_numeric_reference.v2"
_MAX_CHAIN_DEPTH = 8
_NUMBER = r"(?<![\w.])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?!\w)"
_NUMBER_RE = re.compile(_NUMBER)
_ELLIPTICAL_SUBSTITUTION = re.compile(
    rf"\s*(?:what\s+about\s+)?(?P<value>{_NUMBER})\s+instead\s*[?.!]?\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConversationResolution:
    effective_question: str
    status: str
    source_turn_id: str | None = None
    chain_depth: int = 0
    policy_version: str = POLICY_VERSION


def resolve_numeric_follow_up(
    current_question: str, recent_turns: list[dict[str, Any]]
) -> ConversationResolution:
    """Replace one unique prior user number when the whole turn asks for it.

    A prior elliptical request may itself be resolved through consecutive,
    validated user calculation turns. A current turn with units, a topic, or
    other text stays authoritative as written. An intervening non-calculation,
    rejected turn or missing root breaks the chain.
    """

    return _resolve(current_question, recent_turns, depth=0)


def _resolve(
    current_question: str, recent_turns: list[dict[str, Any]], *, depth: int
) -> ConversationResolution:

    match = _ELLIPTICAL_SUBSTITUTION.fullmatch(current_question)
    if match is None:
        return ConversationResolution(current_question, "current_request_explicit")
    if len(match.group("value")) > 32:
        return ConversationResolution(current_question, "reference_out_of_bounds")
    if depth >= _MAX_CHAIN_DEPTH:
        return ConversationResolution(current_question, "reference_chain_too_long")
    if not recent_turns:
        return ConversationResolution(current_question, "no_antecedent")

    prior = recent_turns[-1]
    status = str(prior.get("answer_status") or "").casefold()
    feedback = prior.get("feedback")
    if status in {"failed", "error", "rejected"} or (
        isinstance(feedback, dict) and feedback.get("accepted") is False
    ):
        return ConversationResolution(current_question, "prior_turn_not_usable")
    message = prior.get("message")
    user_message = prior.get("user_message")
    if message and user_message and message != user_message:
        return ConversationResolution(current_question, "conflicting_user_antecedent")
    prior_question = message or user_message
    if not isinstance(prior_question, str) or not prior_question.strip():
        return ConversationResolution(current_question, "no_user_antecedent")
    if len(prior_question) > 2048:
        return ConversationResolution(current_question, "antecedent_out_of_bounds")
    chain_depth = 1
    if _ELLIPTICAL_SUBSTITUTION.fullmatch(prior_question):
        previous = _resolve(prior_question, recent_turns[:-1], depth=depth + 1)
        if previous.status != "resolved_unique_user_number":
            return ConversationResolution(current_question, "unresolved_reference_chain")
        prior_question = previous.effective_question
        chain_depth += previous.chain_depth
    occurrences = list(_NUMBER_RE.finditer(prior_question))
    if len(occurrences) != 1:
        return ConversationResolution(current_question, "ambiguous_antecedent")

    old = occurrences[0]
    if len(old.group()) > 32:
        return ConversationResolution(current_question, "antecedent_out_of_bounds")
    effective = prior_question[: old.start()] + match.group("value") + prior_question[old.end() :]
    if effective == prior_question:
        return ConversationResolution(current_question, "unchanged_value")
    original_plan = plan_tools(prior_question)
    resolved_plan = plan_tools(effective)
    if (
        original_plan.status != "ready"
        or len(original_plan.invocations) != 1
        or original_plan.invocations[0].tool_id != "agronomic_calculator"
    ):
        return ConversationResolution(current_question, "antecedent_not_complete_calculation")
    if (
        resolved_plan.status != "ready"
        or len(resolved_plan.invocations) != 1
        or resolved_plan.invocations[0].tool_id != original_plan.invocations[0].tool_id
        or resolved_plan.invocations[0].operation != original_plan.invocations[0].operation
    ):
        return ConversationResolution(current_question, "substitution_not_same_calculation")
    original_inputs = original_plan.invocations[0].inputs
    resolved_inputs = resolved_plan.invocations[0].inputs
    if original_inputs.keys() != resolved_inputs.keys():
        return ConversationResolution(current_question, "substitution_not_same_calculation")
    changed = [key for key in original_inputs if original_inputs[key] != resolved_inputs[key]]
    if len(changed) != 1:
        return ConversationResolution(current_question, "substitution_not_same_calculation")
    key = changed[0]
    old_number = float(old.group().replace(",", ""))
    new_number = float(match.group("value").replace(",", ""))
    if (
        type(original_inputs[key]) not in {int, float}
        or type(resolved_inputs[key]) not in {int, float}
        or float(original_inputs[key]) != old_number
        or float(resolved_inputs[key]) != new_number
    ):
        return ConversationResolution(current_question, "substitution_not_same_calculation")
    return ConversationResolution(
        effective,
        "resolved_unique_user_number",
        source_turn_id=str(prior.get("turn_id") or prior.get("id") or "") or None,
        chain_depth=chain_depth,
    )
