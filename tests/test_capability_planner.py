from __future__ import annotations

from agronomy_agent.agent import load_agent_resources, build_context
from agronomy_agent.capability_planner import PLANNER_VERSION


def test_production_context_retains_registry_planner_identity() -> None:
    context = build_context(
        "How many kg of urea supplies 80 kg N/ha from a 46% N product?",
        resources=load_agent_resources("configs/rag_final_mvp.yaml"),
    )
    metadata = context.runtime_metadata or {}
    planner_input = metadata["planner_input"]
    plan = metadata["capability_plan"]

    assert plan["planner_version"] == PLANNER_VERSION
    assert plan["planning_context_id"] == planner_input["planning_context_id"]
    calculator = next(
        item for item in plan["invocations"]
        if item["capability_id"] == "agronomic_calculator"
    )
    legacy = metadata["tool_plan"]["invocations"][0]
    assert calculator["invocation_id"] == legacy["invocation_id"]
    assert calculator["selector_id"] == "explicit_arithmetic_parser_v2"


def test_planner_selects_registered_guards_without_model_or_answer_inputs() -> None:
    context = build_context(
        "Should I spray this herbicide today beside a flowering shelterbelt?",
        resources=load_agent_resources("configs/rag_final_mvp.yaml"),
    )
    plan = (context.runtime_metadata or {})["capability_plan"]
    selected = {
        item["capability_id"]
        for item in plan["invocations"]
        if item["operation"] == "guard_note"
    }

    assert {"label_guard", "pesticide_safety_guard"} <= selected
    assert "model_id" not in (context.runtime_metadata or {})["planner_input"]
    assert "answer" not in (context.runtime_metadata or {})["planner_input"]
