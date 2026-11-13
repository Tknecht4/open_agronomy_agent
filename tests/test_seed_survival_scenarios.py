"""Hypothetical arithmetic retains an unresolved denominator and real lineage."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from agronomy_agent.answerability import validated_deterministic_tool_clarification
from agronomy_agent.agent import deterministic_tool_response
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools

QUESTION = "Calculate seed rate for 240 plants/m2, TKW 36 g, germination 92%, and field survival 80%."


def test_both_scenarios_are_canonical_and_no_rate_or_basis_is_selected():
    plan, results = plan_and_execute_tools(QUESTION)
    assert plan.status == "clarification_required"
    assert "survival_basis" not in plan.invocations[0].inputs
    assert len(results) == 1 and results[0].status == "clarification_scenarios"
    payload = results[0].payload
    assert "value" not in payload and "survival_basis" not in payload
    assert payload["selected_scenario"] is None
    assert payload["survival_basis_status"] == "unresolved"
    scenarios = payload["scenarios"]
    assert [s["assumed_survival_basis"] for s in scenarios] == ["seeds_sown", "germinated_seeds"]
    assert [s["calculation"]["value"] for s in scenarios] == pytest.approx([108, 108 / .92])
    assert all(s["calculation"]["inputs"]["germination_pct"] == 92 for s in scenarios)
    assert "all seeds sown" in results[0].answer and "after 92% germination" in results[0].answer
    assert validated_deterministic_tool_clarification(QUESTION, plan.to_dict(), [r.to_dict() for r in results])
    context = SimpleNamespace(runtime_metadata={"tool_plan":plan.to_dict(),"tool_results":[r.to_dict() for r in results]})
    assert deterministic_tool_response(context, question=QUESTION) == (results[0].answer, "deterministic_tool_clarification")


@pytest.mark.parametrize("mutation", ["value", "basis", "child_hash", "parent_answer", "result_id", "missing_child"])
def test_changed_scenario_or_lineage_cannot_be_replayed(mutation):
    plan, results = plan_and_execute_tools(QUESTION)
    altered = deepcopy([r.to_dict() for r in results])
    if mutation == "value":altered[0]["payload"]["scenarios"][0]["calculation"]["value"] = 1
    elif mutation == "basis":altered[0]["payload"]["scenarios"][0]["assumed_survival_basis"] = "germinated_seeds"
    elif mutation == "child_hash":altered[0]["payload"]["scenarios"][0]["calculation_sha256"] = "0" * 64
    elif mutation == "parent_answer":altered[0]["payload"]["answer"] = "Apply this selected rate."
    elif mutation == "result_id":altered[0]["result_id"] = "foreign"
    else:altered[0]["payload"]["scenarios"].pop()
    assert validated_deterministic_tool_clarification(QUESTION, plan.to_dict(), altered) is None


@pytest.mark.parametrize("question", [
    QUESTION.replace("germination 92%, and ", ""),
    QUESTION.replace("92%", "110%"),
    QUESTION.replace("TKW 36 g", "TKW is missing"),
    QUESTION.replace("field survival 80%", "emergence 80%, excluding germination"),
    QUESTION + " Also choose an appropriate herbicide and application rate.",
    QUESTION + " Should I use that rate on my field?",
])
def test_missing_invalid_excluded_basis_and_mixed_actions_do_not_gain_scenarios(question):
    _, results = plan_and_execute_tools(question)
    assert not any(r.status == "clarification_scenarios" for r in results)


@pytest.mark.parametrize("method", ["dimensional", "published_factor_10", "compare"])
def test_imperial_scenarios_keep_each_requested_method(method):
    modifier = {"dimensional":"", "published_factor_10":" using the Manitoba guide's factor-10 method", "compare":" using the Manitoba guide"}[method]
    query = (f"Calculate seed mass{modifier} for 7 plants/ft2 target, 5 g thousand-kernel weight, "
             "90% germination and 20% seedling mortality in lb/ac.")
    plan, results = plan_and_execute_tools(query)
    assert plan.status == "clarification_required" and len(results) == 1
    for scenario in results[0].payload["scenarios"]:
        assert scenario["calculation"]["unit"] == "lb/ac"
        assert scenario["calculation"]["inputs"]["method"] == method
    assert "Method notes" in results[0].answer


def test_preview_planning_never_executes_either_scenario(monkeypatch):
    from agronomy_agent import capability_registry as registry
    def forbidden(*args, **kwargs):raise AssertionError("preview cannot execute a capability")
    monkeypatch.setattr(registry, "execute_registered_capability", forbidden)
    assert plan_tools(QUESTION).status == "clarification_required"


@pytest.mark.parametrize("question", [
    QUESTION.replace("germination 92%", "overall germination 92%"),
    QUESTION + " Compute the overall seed rate.",
])
def test_other_quantity_or_later_output_qualifier_does_not_suppress_scenarios(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "clarification_required" and len(results) == 1
    assert results[0].status == "clarification_scenarios"
