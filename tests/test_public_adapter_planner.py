from __future__ import annotations

from agronomy_agent.capability_planner import select_public_capability_plan
from agronomy_agent.router import classify_query, refine_query_route


def test_source_card_selection_is_content_addressed_by_planner_v2() -> None:
    question = "What disease risk and diagnostic sample evidence should I check for canola lesions?"
    route = refine_query_route(question, classify_query(question))
    plan = select_public_capability_plan(
        question,
        route=route,
        field_context={
            "enable_public_adapters": True,
            "enable_public_source_cards": True,
            "crop": "canola",
            "province": "SK",
        },
    )
    selected = {item.capability_id for item in plan.invocations}
    assert "saskatchewan_official_crop_guidance" in selected
    assert "disease_risk_context_adapter" in selected
    assert "diagnostic_lab_and_sample_quality" in selected
    assert all(item.invocation_id.startswith("invocation_") for item in plan.invocations)
