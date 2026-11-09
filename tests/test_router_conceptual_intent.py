from __future__ import annotations

import pytest

from agronomy_agent.evals import enrich_eval_metadata_with_expected_source_trace
from agronomy_agent.router import classify_query, refine_query_route
from agronomy_agent.capability_planner import build_planner_input, plan_capabilities
from agronomy_agent.capability_registry import capability_registry
from agronomy_agent.decision_contract import build_decision_contract
from agronomy_agent.execution_core import stable_sha256
from agronomy_agent.evidence_contracts import question_frame_from_runtime


@pytest.mark.parametrize(
    "question",
    [
        "What is crop rotation, and why can it help manage disease pressure?",
        "How does rotating crops interrupt a pathogen's life cycle?",
        "Explain why planting diverse crops over time can reduce pest pressure.",
        "What is nitrogen fixation, and why does it matter in a rotation?",
    ],
)
def test_benign_practice_and_mechanism_explanations_stay_conceptual(
    question: str,
) -> None:
    broad_route = classify_query(question)
    route = refine_query_route(question, broad_route)

    assert broad_route.question_type == "exam_review"
    assert route.question_type == "exam_review"
    assert route.risk_level == "low"
    assert route.answer_style == "exam_review"
    assert route.required_tools == ()
    assert "exam_review" in route.namespaces
    assert not {
        "field_data_boundary",
        "label_boundary",
        "plant_health",
        "product_stewardship",
    }.intersection(route.namespaces)


@pytest.mark.parametrize(
    ("question", "expected_type", "expected_risk", "required_tools"),
    [
        (
            "How does this field's disease pattern change the diagnosis?",
            "plant_health",
            "low",
            {"field_data_guard"},
        ),
        (
            "My canola has lesions after wheat; what disease is this and what should I do?",
            "plant_health",
            "low",
            {"field_data_guard"},
        ),
        (
            "How should I manage disease pressure in this field this week?",
            "plant_health",
            "low",
            {"field_data_guard"},
        ),
        (
            "What disease threshold should trigger treatment in this crop?",
            "plant_health",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "Should I spray a fungicide for disease in this field?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "What is the PHI for glyphosate?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "What is the REI for Roundup?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "Can I use Authority in peas?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "What rate of Liberty can I apply in canola?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "What is the Liberty rate?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "Is Roundup allowed on this crop?",
            "product_label",
            "regulated",
            {"field_data_guard", "label_guard", "pesticide_safety_guard"},
        ),
        (
            "What is the nitrogen rate?",
            "fertility_rate",
            "medium",
            {"fertility_guard", "field_data_guard", "nutrient_4r_guard"},
        ),
    ],
)
def test_conceptual_gate_preserves_field_and_regulated_decision_routes(
    question: str,
    expected_type: str,
    expected_risk: str,
    required_tools: set[str],
) -> None:
    route = refine_query_route(question, classify_query(question))

    assert route.question_type == expected_type
    assert route.risk_level == expected_risk
    # The router owns intent/risk/style only. Guard applicability is selected
    # by the registered selector used by capability planner v2.
    assert route.required_tools == ()
    contract = build_decision_contract(question, route, field_context=None)
    frame = question_frame_from_runtime(
        question=question,
        route=route,
        query_context={},
        decision_contract=contract.to_dict(),
        field_context=None,
    )
    planner_input = build_planner_input(
        question,
        question_frame=frame.to_dict(),
        decision_contract=contract.to_dict(),
        capability_registry_sha256=stable_sha256([spec.as_record() for spec in capability_registry().specs]),
        arm_id="production_full",
        phase="tool_planning",
    )
    selected_guards = {item.capability_id for item in plan_capabilities(planner_input).invocations}
    assert required_tools.issubset(selected_guards)
    assert route.question_type != "exam_review"


def test_eval_trace_uses_benign_conceptual_route_without_safety_tool_inflation() -> None:
    question = "What is crop rotation, and why can it help manage disease pressure?"
    item = {
        "eval_id": "conceptual_rotation_mechanism",
        "task_family": "crop_management",
        "question": question,
        "required_patterns": [],
        "forbidden_patterns": [],
    }

    metadata = enrich_eval_metadata_with_expected_source_trace({"tool_notes": []}, item)

    assert metadata["route"]["question_type"] == "exam_review"
    assert metadata["route"]["risk_level"] == "low"
    assert metadata["route"]["required_tools"] == ()
    assert metadata["route_tool_notes"] == []


@pytest.mark.parametrize("question", [
    "In Canadian Prairie rotation research, are 500 simulated economic returns the same as 500 independent field trials?",
    "Does running a simulation a thousand times count as independent replication?",
    "What must I check before comparing wheat grain yield per plot with yield at 15 percent moisture per hectare?",
    "Can I compare my feed analyses on an as-fed and dry matter basis?",
    "What do different units in two yield reports mean?",
    "Are wheat grain masses per plant and per plot interchangeable?",
])
def test_evidence_interpretation_has_no_operational_expansion(question):
    from agronomy_agent.router import evidence_interpretation_kind
    route = refine_query_route(question, classify_query(question))
    assert evidence_interpretation_kind(question)
    assert route.question_type == "exam_review"
    assert route.risk_level == "low"
    assert not {"planting window", "trafficability", "soil test", "yield goal"}.intersection(route.query_expansion)


@pytest.mark.parametrize("question", [
    "Compare yield units and recommend a herbicide rate for my wheat.",
    "Are these independent field trials enough to prescribe nitrogen for my field?",
    "How much fertilizer should I apply when yield per plot differs?",
    "Compare moisture bases and tell me whether I should spray Roundup now.",
])
def test_interpretation_gate_does_not_erase_mixed_operational_intent(question):
    from agronomy_agent.router import evidence_interpretation_kind
    assert evidence_interpretation_kind(question) is None
    route = refine_query_route(question, classify_query(question))
    assert route.question_type != "exam_review"


def test_stale_field_data_route_never_replaces_study_question_with_prescription():
    from agronomy_agent.answer_verifier import _conservative_failure_answer
    answer = _conservative_failure_answer("field_data", question=
        "Are simulated economic returns the same as independent field trials?")
    assert "Evaluate the prescription" not in answer
    assert "soil survey" not in answer.lower()


@pytest.mark.parametrize("question", [
    "Compare soil-test results and tell me what nitrogen rate to use.",
    "What do moisture units mean and should I irrigate today?",
    "Are these independent field trials and what should I do in my field?",
])
def test_mixed_non_pesticide_actions_are_not_interpretation(question):
    from agronomy_agent.router import evidence_interpretation_kind
    assert evidence_interpretation_kind(question) is None
