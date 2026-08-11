"""Factorized shadow routing policy for diagnosis-before-treatment decisions.

This is intentionally narrower than a complete RouteDecisionV2 architecture.
It tests one development-derived hypothesis without changing the authoritative
router: primary workflow intent and safety/tool authority must be independent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from agronomy_agent.lfm_prompt_router import LfmRouteResult


POLICY_ID = "open_agronomy_agent.factorized_route.diagnostic_before_treatment.v1"


@dataclass(frozen=True)
class FactorizedRouteDecision:
    policy_id: str
    current_primary_intent: str
    primary_intent: str
    model_selected_intent: str | None
    primary_changed: bool
    policy_reason: str
    authority_flags: tuple[str, ...]
    evidence_readiness: str
    required_tools: tuple[str, ...]
    original_required_tools: tuple[str, ...]
    safety_tools_preserved: bool
    applied_to_authoritative_route: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def factorized_route_decision(
    current_route: Mapping[str, Any],
    lfm_result: LfmRouteResult,
) -> FactorizedRouteDecision:
    """Apply the frozen diagnosis-before-treatment shadow gate.

    The gate may change only the primary intent. Existing tools are monotonic:
    they can be retained or strengthened, never removed.
    """

    current_primary = str(current_route["question_type"])
    original_tools = tuple(
        sorted(str(tool) for tool in current_route.get("required_tools", ()))
    )
    tools = set(original_tools)
    if current_primary == "product_label":
        tools.add("label_guard")

    model_selected = (
        lfm_result.selected_route
        if lfm_result.available and not lfm_result.abstained
        else None
    )
    primary = current_primary
    reason = "current_primary_preserved"
    readiness = "not_assessed"
    if current_primary == "product_label" and model_selected == "plant_health":
        primary = "plant_health"
        reason = "diagnosis_before_treatment_primary_override"
        readiness = "diagnosis_required_before_treatment_selection"

    authority: set[str] = set()
    if current_primary == "product_label" or "label_guard" in tools:
        authority.add("regulated_product_label_required")
    if "pesticide_safety_guard" in tools:
        authority.add("pesticide_safety_required")
    if "weather_guard" in tools:
        authority.add("current_weather_evidence_required")
    if "field_data_guard" in tools:
        authority.add("field_evidence_required")
    if "fertility_guard" in tools:
        authority.add("calibrated_fertility_evidence_required")

    required_tools = tuple(sorted(tools))
    return FactorizedRouteDecision(
        policy_id=POLICY_ID,
        current_primary_intent=current_primary,
        primary_intent=primary,
        model_selected_intent=model_selected,
        primary_changed=primary != current_primary,
        policy_reason=reason,
        authority_flags=tuple(sorted(authority)),
        evidence_readiness=readiness,
        required_tools=required_tools,
        original_required_tools=original_tools,
        safety_tools_preserved=set(original_tools).issubset(required_tools),
    )

