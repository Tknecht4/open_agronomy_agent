"""Resolve bounded calculator follow-ups from authorized same-session user text.

This is a pre-routing text operation, not a source of field evidence. The caller
supplies the recent, session-scoped turns it already authorized for conversation
continuity. Assistant answers and feedback never supply an operand or a task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agronomy_agent.tool_planner import plan_tools
from agronomy_agent.seed_establishment import SEED_SURVIVAL_BASIS_GAP, SEED_GERMINATION_GAP


POLICY_VERSION = "conversation_calculation_reference.v3"
_MAX_CHAIN_DEPTH = 8
_NUMBER = r"(?<![\w.])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?!\w)"
_NUMBER_RE = re.compile(_NUMBER)
_ELLIPTICAL_SUBSTITUTION = re.compile(
    rf"\s*(?:what\s+about\s+)?(?P<value>{_NUMBER})\s+instead\s*[?.!]?\s*",
    re.IGNORECASE,
)
_SEED_BASIS_SELECTION = re.compile(
    r"\s*(?:(?:it|that|(?:the\s+)?(?:field\s+)?survival)\s+is\s+|use\s+)?"
    r"(?P<choice>overall(?:\s*,?\s*(?:of\s+)?(?:all\s+)?seeds?\s+(?:sown|planted))?"
    r"|(?:of\s+)?(?:all\s+)?seeds?\s+(?:sown|planted)"
    r"|(?:of\s+)?(?:only\s+)?(?:the\s+)?germinated\s+seeds?"
    r"|post[- ]germination|after\s+germination)\s*[.!]?\s*",
    re.IGNORECASE,
)
_SEED_GERMINATION_SELECTION = re.compile(
    r"\s*(?:(?:(?:seed[- ]lot|lab(?:oratory)?)\s+)?germination\s*(?:is|of|:)?\s*)?"
    r"(?P<percent>[0-9]+(?:\.[0-9]+)?)\s*%"
    r"(?:\s+(?:(?:seed[- ]lot|lab(?:oratory)?)\s+)?germination)?\s*[.!]?\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConversationResolution:
    effective_question: str
    status: str
    source_turn_id: str | None = None
    chain_depth: int = 0
    policy_version: str = POLICY_VERSION


def resolve_calculation_follow_up(
    current_question: str, recent_turns: list[dict[str, Any]]
) -> ConversationResolution:
    """Resolve a bounded seed clarification or unique numeric substitution.

    A prior elliptical request may itself be resolved through consecutive,
    validated user calculation turns. Seed replies may select a denominator
    and, if that makes laboratory germination the only gap, supply that one
    percentage. Other requests stay authoritative as written. An intervening
    topic, rejected turn or missing root breaks the chain.
    """

    basis = _SEED_BASIS_SELECTION.fullmatch(current_question)
    if basis is not None:
        return _resolve_seed_basis(current_question, recent_turns, basis.group("choice"))
    germination = _SEED_GERMINATION_SELECTION.fullmatch(current_question)
    if germination is not None:
        return _resolve_seed_germination(current_question, recent_turns, germination.group("percent"))
    return _resolve(current_question, recent_turns, depth=0)


def _prior_user_question(
    current_question: str, recent_turns: list[dict[str, Any]],
) -> tuple[dict[str, Any], str] | ConversationResolution:
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
    question = message or user_message
    if not isinstance(question, str) or not question.strip():
        return ConversationResolution(current_question, "no_user_antecedent")
    if len(question) > 2048:
        return ConversationResolution(current_question, "antecedent_out_of_bounds")
    return prior, question


def _resolve_seed_basis(
    current_question: str, recent_turns: list[dict[str, Any]], choice: str,
) -> ConversationResolution:
    antecedent = _prior_user_question(current_question, recent_turns)
    if isinstance(antecedent, ConversationResolution):
        return antecedent
    prior, question = antecedent
    original = plan_tools(question)
    if original.status != "clarification_required" or len(original.invocations) != 1:
        return ConversationResolution(current_question, "antecedent_not_seed_basis_clarification")
    invocation = original.invocations[0]
    if (invocation.tool_id != "agronomic_calculator"
            or invocation.operation not in {"seed_rate_mass", "seed_rate_mass_imperial"}
            or invocation.missing_inputs != (SEED_SURVIVAL_BASIS_GAP,)):
        return ConversationResolution(current_question, "antecedent_not_seed_basis_clarification")
    conditional = bool(re.search(r"germinat", choice, re.IGNORECASE))
    basis = "germinated_seeds" if conditional else "seeds_sown"
    denominator = "germinated seeds" if conditional else "all seeds sown"
    # Restate only the existing user-supplied percentage with the newly chosen
    # denominator. Keep the complete original request, including any directives.
    percentage = format(Decimal(str(invocation.inputs["field_survival_pct"])), "f")
    effective = question + f"\nFor this calculation, field survival is {percentage}% of {denominator}."
    resolved = plan_tools(effective)
    if resolved.status not in {"ready", "clarification_required"} or len(resolved.invocations) != 1:
        return ConversationResolution(current_question, "basis_not_same_calculation")
    completed = resolved.invocations[0]
    if resolved.status == "clarification_required" and completed.missing_inputs != (SEED_GERMINATION_GAP,):
        return ConversationResolution(current_question, "basis_not_same_calculation")
    if (completed.tool_id != invocation.tool_id or completed.operation != invocation.operation
            or completed.inputs.get("survival_basis") != basis
            or {k: v for k, v in completed.inputs.items() if k != "survival_basis"} != invocation.inputs):
        return ConversationResolution(current_question, "basis_not_same_calculation")
    return ConversationResolution(effective, "resolved_seed_survival_basis",
                                  source_turn_id=str(prior.get("turn_id") or prior.get("id") or "") or None,
                                  chain_depth=1)


def _resolve_seed_germination(
    current_question: str, recent_turns: list[dict[str, Any]], percentage: str,
) -> ConversationResolution:
    if len(percentage) > 32 or not 0 < Decimal(percentage) <= 100:
        return ConversationResolution(current_question, "seed_germination_out_of_bounds")
    antecedent = _prior_user_question(current_question, recent_turns)
    if isinstance(antecedent, ConversationResolution):
        return antecedent
    prior, question = antecedent
    chain_depth = 1
    basis = _SEED_BASIS_SELECTION.fullmatch(question)
    if basis is not None:
        # Reconstruct the adjacent basis turn from authorized user text again;
        # never recover operands from its assistant answer or stored metadata.
        previous = _resolve_seed_basis(question, recent_turns[:-1], basis.group("choice"))
        if previous.status != "resolved_seed_survival_basis":
            return ConversationResolution(current_question, "unresolved_reference_chain")
        question = previous.effective_question
        chain_depth += previous.chain_depth
    original = plan_tools(question)
    if original.status != "clarification_required" or len(original.invocations) != 1:
        return ConversationResolution(current_question, "antecedent_not_seed_germination_clarification")
    invocation = original.invocations[0]
    if (invocation.tool_id != "agronomic_calculator"
            or invocation.operation not in {"seed_rate_mass", "seed_rate_mass_imperial"}
            or invocation.missing_inputs != (SEED_GERMINATION_GAP,)
            or "germination_pct" in invocation.inputs):
        return ConversationResolution(current_question, "antecedent_not_seed_germination_clarification")
    effective = question + f"\nThe laboratory germination is {percentage}%."
    resolved = plan_tools(effective)
    if resolved.status != "ready" or len(resolved.invocations) != 1:
        return ConversationResolution(current_question, "germination_not_same_calculation")
    completed = resolved.invocations[0]
    expected = {**invocation.inputs, "germination_pct": float(percentage)}
    if (completed.tool_id != invocation.tool_id or completed.operation != invocation.operation
            or completed.inputs != expected):
        return ConversationResolution(current_question, "germination_not_same_calculation")
    return ConversationResolution(effective, "resolved_seed_germination",
                                  source_turn_id=str(prior.get("turn_id") or prior.get("id") or "") or None,
                                  chain_depth=chain_depth)


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
    antecedent = _prior_user_question(current_question, recent_turns)
    if isinstance(antecedent, ConversationResolution):
        return antecedent
    prior, prior_question = antecedent
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
