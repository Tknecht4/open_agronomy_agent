"""Conditional seed arithmetic without resolving an unknown survival basis.

Only actual execution builds these records. Planning/readiness retain the
missing denominator; neither scenario is a selected rate or a new field fact.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any

from agronomy_agent.agronomic_calculations import _format_decimal, validate_seed_rate_inputs
from agronomy_agent.seed_establishment import SEED_SURVIVAL_BASIS_GAP, SEED_SURVIVAL_BASES, parse_seed_establishment

SCHEMA_VERSION = "open_agronomy_agent.seed_survival_clarification.v1"
STATUS = "clarification_scenarios"


def conditional_seed_payload(invocation: Any, *, question: str) -> dict[str, Any] | None:
    """Execute both explicit assumptions only when this is the sole input gap."""
    if (invocation.tool_id != "agronomic_calculator"
            or invocation.operation not in {"seed_rate_mass", "seed_rate_mass_imperial"}
            or invocation.status != "clarification_required"
            or tuple(invocation.missing_inputs) != (SEED_SURVIVAL_BASIS_GAP,)
            or "survival_basis" in invocation.inputs
            or "germination_pct" not in invocation.inputs):
        return None
    from agronomy_agent.calculator_contracts import calculation_request_is_complete
    qualifiers: list[bool] = []
    parse_seed_establishment(" ".join(question.replace("−", "-").split()), unqualified_basis=qualifiers)
    if (hashlib.sha256(question.encode()).hexdigest() != invocation.question_sha256
            or not calculation_request_is_complete(question, invocation.operation)
            or not qualifiers or not all(qualifiers)):
        # Explicit/negated denominator language is not unqualified survival.
        # Use the parser's role-bound cue handling, never a whole-query word.
        return None
    inputs = dict(invocation.inputs)
    # Validate BOTH before dispatch; an invalid conditional branch must not
    # silently leave an apparently selected overall-emergence result.
    try:
        for basis in SEED_SURVIVAL_BASES:
            validate_seed_rate_inputs(invocation.operation, {**inputs, "survival_basis": basis})
    except (ArithmeticError, TypeError, ValueError):
        return None
    from agronomy_agent.capability_registry import execute_registered_capability
    scenarios = []
    for basis in SEED_SURVIVAL_BASES:
        calculation = execute_registered_capability("agronomic_calculator", {
            "operation": invocation.operation, "inputs": {**inputs, "survival_basis": basis},
        })
        canonical = json.dumps(calculation, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        scenarios.append({"assumed_survival_basis": basis, "calculation": calculation,
                          "calculation_sha256": hashlib.sha256(canonical.encode()).hexdigest()})
    survival = _format_decimal(Decimal(str(inputs["field_survival_pct"])))
    germination = _format_decimal(Decimal(str(inputs["germination_pct"])))
    lines = ["The survival denominator is unresolved. These are two conditional calculations, not a selected rate:"]
    for scenario in scenarios:
        calculation = scenario["calculation"]
        condition = (f"{survival}% of all seeds sown establish (germination already included)"
                     if scenario["assumed_survival_basis"] == "seeds_sown" else
                     f"{survival}% of germinated seeds survive, after {germination}% germination")
        value = _format_decimal(Decimal(calculation["value_decimal"]))
        lines.append(f"- If {condition}: {value} {calculation['unit']}. Calculation: {calculation['formula']}.")
        if invocation.operation == "seed_rate_mass_imperial":
            # Preserve the exact dimensional/published-factor distinction;
            # the canonical child owns its alternate-method calculation.
            lines.append("  Method notes: " + "; ".join(calculation["assumptions"][2:]) + ".")
    boundary = scenarios[0]["calculation"]["boundary"]
    lines.append("Does the survival percentage refer to all seeds sown, or only germinated seeds? " + boundary)
    return {"schema_version": SCHEMA_VERSION, "status": STATUS,
            "operation": invocation.operation, "supplied_inputs": inputs,
            "missing_inputs": list(invocation.missing_inputs), "survival_basis_status": "unresolved",
            "selected_scenario": None, "scenarios": scenarios,
            "answer": "\n\n".join(lines), "boundary": boundary}
