from __future__ import annotations

import pytest

from agronomy_agent.evals import enrich_eval_metadata_with_expected_source_trace
from agronomy_agent.router import classify_query, refine_query_route


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
    assert required_tools.issubset(route.required_tools)
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
