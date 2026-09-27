from __future__ import annotations

import json

import pytest

from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools
from agronomy_agent.tool_planner import CALCULATOR_VERSION
from agronomy_agent.capability_registry import capability_registry


def test_planner_calculator_version_matches_canonical_registry() -> None:
    assert CALCULATOR_VERSION == capability_registry().require("agronomic_calculator").version


def test_frozen_operation_identity_and_current_extension_are_distinct() -> None:
    legacy = plan_tools("Calculate one day's GDD from Tmax 25 C, Tmin 9 C and base 7 C.")
    extension = plan_tools(
        "Calculate break-even price from total cost CAD 900/ha and expected yield 3 tonnes/ha."
    )

    assert legacy.invocations[0].tool_version == "agronomic_calculator_v1"
    assert extension.invocations[0].tool_version == "agronomic_calculator_v2"


@pytest.mark.parametrize("row", [json.loads(line) for line in open("data/eval/canadian_agronomic_calculations_v1.jsonl", encoding="utf-8") if line.strip()])
def test_planner_executes_every_frozen_calculation_case(row: dict) -> None:
    plan, results = plan_and_execute_tools(row["question"], field_context=row.get("field_context"))

    assert plan.status == "ready", row["eval_id"]
    assert len(results) == 1
    result = results[0]
    assert result.status == "calculated"
    assert result.tool_id == "agronomic_calculator"
    assert result.invocation_id == plan.invocations[0].invocation_id
    assert result.result_id.startswith("tool_result_")
    assert abs(float(result.payload["value"]) - float(row["reference_numeric"])) <= float(row["absolute_tolerance"])
    assert result.answer.startswith(str(result.payload["value_decimal"]).rstrip("0").rstrip(".")) or result.answer


def test_planner_does_not_choose_an_agronomic_target() -> None:
    plan = plan_tools("How much nitrogen should I apply to my canola field?")

    assert plan.status == "not_applicable"
    assert not plan.invocations


def test_planner_does_not_turn_a_benign_nutrient_definition_into_a_calculation() -> None:
    plan = plan_tools(
        "What is the difference between kilograms of nitrogen per hectare and kilograms of urea product per hectare?"
    )

    assert plan.status == "not_applicable"
    assert not plan.invocations


def test_planner_requests_only_missing_calculation_inputs() -> None:
    plan = plan_tools("How many kg of urea supplies 80 kg N/ha?")

    assert plan.status == "clarification_required"
    assert plan.invocations[0].operation == "fertilizer_product_mass"
    assert plan.invocations[0].missing_inputs == ("nutrient_percent",)
    assert "nutrient_percent" in str(plan.clarification)


def test_planner_identity_is_deterministic() -> None:
    question = "Convert a fertilizer rate of 100 lb/ac to kg/ha."
    first, first_results = plan_and_execute_tools(question)
    second, second_results = plan_and_execute_tools(question)

    assert first.invocations[0].invocation_id == second.invocations[0].invocation_id
    assert first_results[0].result_id == second_results[0].result_id
    assert first_results[0].payload_sha256 == second_results[0].payload_sha256
    assert first.schema_version == "open_agronomy_agent.tool_plan.v1"


@pytest.mark.parametrize(
    ("question", "operation", "value", "unit"),
    [
        ("Calculate wheat seed mass from 260 plants/m² target, TKW 40 g, germination 90%, and field survival 85% in kg/ha.", "seed_rate_mass", 135.9477, "kg/ha"),
        ("Using the Manitoba guide's factor-10 method, calculate seed mass for 28 plants/ft² target, 39 g thousand-kernel weight, 99% germination and 15% post-germination mortality in lb/ac.", "seed_rate_mass_imperial", 129.76827, "lb/ac"),
        ("Calculate one day's GDD from Tmax 25 C, Tmin 9 C and base 7 C.", "daily_gdd", 10, "GDD"),
        ("Calculate a partial-budget net change: added revenue USD 100/ac, saved costs USD 25/ac, added costs USD 80/ac and lost revenue USD 15/ac.", "partial_budget", 30, "USD/ac"),
        ("Calculate total-cost break-even price from total cost CAD 900/ha and expected yield 3 tonnes/ha.", "break_even_price", 300, "CAD/tonne"),
        ("Calculate operating-cost break-even yield from operating cost USD 480/ac and an assumed price USD 8/bu.", "break_even_yield", 60, "bu/ac"),
        ("Calculate current ratio from current assets USD 300,000 and current liabilities USD 120,000.", "current_ratio", 2.5, "ratio"),
        ("Calculate debt-to-asset ratio from total debt CAD 275,000 and total assets CAD 1,100,000.", "debt_to_asset_percent", 25, "%"),
    ],
)
def test_planner_paraphrases_execute_one_typed_result(
    question: str, operation: str, value: float, unit: str
) -> None:
    plan, results = plan_and_execute_tools(question)

    assert plan.status == "ready"
    assert len(plan.invocations) == len(results) == 1
    assert plan.invocations[0].operation == operation
    assert float(results[0].payload["value"]) == pytest.approx(value, rel=1e-4)
    assert results[0].payload["unit"] == unit


@pytest.mark.parametrize(
    ("question", "expected_status"),
    [
        ("Calculate break-even price from total cost CAD 500/ac without an expected yield.", "clarification_required"),
        ("Calculate break-even price from total cost CAD 500/ac and expected yield 0 bu/ac.", "clarification_required"),
        ("Calculate break-even price from total cost CAD 500/ac and operating cost CAD 300/ac with expected yield 50 bu/ac.", "clarification_required"),
        ("What does a current ratio mean?", "not_applicable"),
        ("What is today's cash bid for canola?", "not_applicable"),
        ("Calculate the recommended herbicide rate for my canola field.", "not_applicable"),
        ("Calculate a break-even price from total cost CAD 500/ac and yield 50 bu/ac; should I sell now?", "not_applicable"),
    ],
)
def test_planner_avoids_ambiguous_or_action_seeking_math(question: str, expected_status: str) -> None:
    plan = plan_tools(question)

    assert plan.status == expected_status
    if expected_status != "ready":
        assert not any(invocation.status == "planned" for invocation in plan.invocations)
