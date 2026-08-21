from __future__ import annotations

import json

import pytest

from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools
from agronomy_agent.tool_planner import CALCULATOR_VERSION
from agronomy_agent.capability_registry import capability_registry


def test_planner_calculator_version_matches_canonical_registry() -> None:
    assert CALCULATOR_VERSION == capability_registry().require("agronomic_calculator").version


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
