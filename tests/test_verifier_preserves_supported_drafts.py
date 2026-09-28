from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import (
    _decision_route_failure_answer,
    assess_claim_risk,
    verify_answer,
)
from agronomy_agent.decision_route import build_decision_route_state


class NeverEdit:
    def generate(self, messages):
        raise AssertionError("advisory completeness is not a replacement defect")


@pytest.mark.parametrize("map_name", ["crop inventory map", "yield map", "satellite map"])
def test_advisory_checklist_does_not_replace_a_product_explanation(map_name):
    question = f"Why can the {map_name} not tell me which corn hybrid succeeded next door?"
    draft = (
        f"The {map_name} does not identify individual hybrids and their performance. "
        "Use the grower's records to establish what was grown and how it performed."
    )
    assessment = assess_claim_risk(draft, question=question, question_type="crop_management")
    assert assessment.reasons == ("missing_decision_content",)
    result = verify_answer(
        draft, question=question, evidence_text="", question_type="crop_management",
        risk_level="low", editor=NeverEdit(), review_mode="risk_conditioned_selective_v3",
    )
    assert result.answer == draft
    assert not result.triggered and not result.fallback_applied
    assert result.draft_assessment.missing_intent_facets  # Retain the advisory evidence.
    assert result.risk_threshold_receipt["advisory_only_preserved"] is True
    assert result.as_record()["claim_edit_ledger"]["changed_claim_count"] == 0


def test_concrete_numeric_defect_still_requires_review_despite_checklist_omissions():
    class Editor:
        calls = 0

        def generate(self, messages):
            self.calls += 1
            return "The crop inventory map cannot establish which hybrid succeeded."

    editor = Editor()
    result = verify_answer(
        "The crop inventory map proves the corn hybrid yielded 20 kg/ha.",
        question="Why can the crop inventory map not tell me which corn hybrid succeeded?",
        evidence_text="", question_type="crop_management", risk_level="low",
        editor=editor, review_mode="risk_conditioned_selective_v3",
    )
    assert result.triggered
    assert "unsupported_numeric_specificity" in result.draft_assessment.reasons
    assert result.risk_threshold_receipt["advisory_only_preserved"] is False
    assert "20 kg/ha" not in result.answer


@pytest.mark.parametrize("map_name", ["crop inventory map", "yield map", "satellite map"])
def test_unknown_map_type_is_not_renamed_by_emergency_variety_fallback(map_name):
    state = build_decision_route_state(f"Which corn hybrid should I choose from this {map_name}?", "crop_management")
    assert state.decision == "variety_trial_selection"
    answer = _decision_route_failure_answer(state)
    assert answer and "cannot select" in answer
    assert "suitability map" not in answer
    assert "favourable" not in answer

