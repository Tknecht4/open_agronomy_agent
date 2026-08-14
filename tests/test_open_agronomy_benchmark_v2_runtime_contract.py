from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.answerability import assess_answerability
from agronomy_agent.tool_planner import plan_and_execute_tools


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "data/eval/open_agronomy_benchmark_v2_cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def test_all_v2_cases_match_planner_and_answerability_contract() -> None:
    """Table-driven integration gate over the complete frozen v2 topology."""

    assert len(CASES) == 30
    for case in CASES:
        plan, results = plan_and_execute_tools(case["question"], field_context=case["field_context"])
        decision = assess_answerability(
            case["question"],
            tool_plan=plan.to_dict(),
            tool_results=[result.to_dict() for result in results],
            field_context=case["field_context"],
        )
        stratum = case["stratum"]
        expected_states = set(case["expected_response"]["acceptable_answerability_states"])
        assert decision.state.value in expected_states, (
            case["eval_id"],
            plan.to_dict(),
            decision.to_dict(),
        )

        if stratum == "benign_explanation":
            assert plan.status == "not_applicable", case["eval_id"]
            assert not plan.invocations
            assert not results
            assert decision.state.value in {"answer_directly", "answer_with_bounded_uncertainty"}
        elif stratum == "fully_specified_calculation":
            assert plan.status == "ready", case["eval_id"]
            assert len(plan.invocations) == len(results) == 1
            assert plan.invocations[0].tool_id == "agronomic_calculator"
            assert plan.invocations[0].operation == case["expected_tool_operation"]
            assert decision.state.value == "answer_directly"
        elif stratum == "fully_specified_action_plan":
            assert plan.status == "not_applicable", case["eval_id"]
            assert not results
            assert decision.state.value in {"answer_directly", "answer_with_bounded_uncertainty"}
        elif stratum == "one_critical_input_missing":
            assert plan.status == "clarification_required", case["eval_id"]
            assert len(plan.invocations) == 1
            assert not results
            assert list(plan.invocations[0].missing_inputs) == case["expected_response"]["clarification_fields"]
            assert decision.state.value == "ask_one_discriminating_question"
            assert list(decision.missing_inputs) == case["expected_response"]["clarification_fields"]
        elif stratum == "high_consequence_authority":
            assert plan.status == "not_applicable", case["eval_id"]
            assert not results
            assert decision.state.value == "require_authority"
            assert decision.required_authority
        else:  # pragma: no cover - schema/audit prohibit additional strata.
            raise AssertionError(f"unexpected v2 stratum: {stratum}")


def test_benign_nitrogen_product_explanation_is_not_misclassified_as_calculation() -> None:
    case = next(row for row in CASES if row["eval_id"] == "oab2::canola_nitrogen::benign_explanation")
    plan, results = plan_and_execute_tools(case["question"])
    decision = assess_answerability(case["question"], tool_plan=plan.to_dict(), tool_results=[])

    assert plan.status == "not_applicable"
    assert not results
    assert decision.state.value == "answer_directly"


def test_every_high_consequence_case_requires_authority() -> None:
    cases = [row for row in CASES if row["stratum"] == "high_consequence_authority"]
    assert len(cases) == 6

    for case in cases:
        plan, results = plan_and_execute_tools(case["question"])
        decision = assess_answerability(
            case["question"],
            tool_plan=plan.to_dict(),
            tool_results=[result.to_dict() for result in results],
            field_context=case["field_context"],
        )
        assert plan.status == "not_applicable", case["eval_id"]
        assert decision.state.value == "require_authority", (case["eval_id"], decision.to_dict())
