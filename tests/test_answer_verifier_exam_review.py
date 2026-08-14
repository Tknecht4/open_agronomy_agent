from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import (
    _conservative_failure_answer,
    verify_answer,
)


_BROKEN_DRAFT = "Answer the question directly.\n```json\n" + (
    "import math_utils_utils as math_utils_utils\n" * 12
)
_BROKEN_REWRITE = "True False " * 40


class _BrokenEditor:
    def generate(self, messages: list[dict[str, str]]) -> str:
        return _BROKEN_REWRITE


def _verify_broken_exam_draft(question: str):
    return verify_answer(
        _BROKEN_DRAFT,
        question=question,
        evidence_text="",
        question_type="exam_review",
        risk_level="low",
        editor=_BrokenEditor(),
        review_mode="risk_gated",
    )


@pytest.mark.parametrize(
    "question",
    (
        "What is crop rotation, and why can it help manage disease pressure?",
        "How does rotating crops interrupt a pathogen's life cycle?",
        "Explain why planting diverse crops over time can reduce pest pressure.",
    ),
)
def test_failed_rotation_exam_answer_uses_topic_matched_mechanism_capsule(
    question: str,
) -> None:
    result = _verify_broken_exam_draft(question)

    assert result.fallback_applied is True
    assert result.final_assessment is not None
    assert result.final_assessment.requires_review is False
    assert "Crop rotation is the planned sequence" in result.answer
    assert "non-host crop interrupts reproduction and infection" in result.answer
    assert "Rotation is suppression, not a guarantee" in result.answer
    assert "broad host ranges" in result.answer
    assert "soil test" not in result.answer.lower()
    assert "tissue test" not in result.answer.lower()


def test_failed_nutrient_exam_answer_retains_nutrient_capsule() -> None:
    result = _verify_broken_exam_draft(
        "What are primary and secondary macronutrients, and how does nutrient mobility affect symptom location?"
    )

    assert result.fallback_applied is True
    assert "Primary macronutrients are nitrogen, phosphorus, and potassium" in result.answer
    assert "secondary macronutrients are calcium, magnesium, and sulfur" in result.answer
    assert "mobile nutrients" in result.answer
    assert "older leaves" in result.answer
    assert "younger leaves" in result.answer


def test_unknown_exam_topic_degrades_honestly_without_nutrient_leakage() -> None:
    result = _verify_broken_exam_draft("What is apomixis?")

    assert result.fallback_applied is True
    assert result.answer.startswith(
        "I do not have enough reliable topic-specific information to answer this conceptual question accurately."
    )
    assert "will not substitute an unrelated agronomy concept" in result.answer
    assert "does not require field samples" in result.answer
    for unrelated in (
        "macronutrient",
        "micronutrient",
        "nitrogen",
        "phosphorus",
        "potassium",
        "soil test",
        "tissue test",
    ):
        assert unrelated not in result.answer.lower()


@pytest.mark.parametrize(
    ("question_type", "question", "expected"),
    (
        (
            "product_label",
            "Can I spray glyphosate on canola today?",
            "Confirm the exact product and current label",
        ),
        (
            "plant_health",
            "My canola leaves are yellow; what disease is this?",
            "Do not diagnose from symptoms alone",
        ),
    ),
)
def test_exam_topic_dispatch_does_not_change_product_or_field_fallbacks(
    question_type: str,
    question: str,
    expected: str,
) -> None:
    answer = _conservative_failure_answer(question_type, question=question)

    assert expected in answer
    assert "I do not have enough reliable topic-specific information" not in answer
    assert "Primary macronutrients" not in answer
