from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import _decision_route_failure_answer, assess_claim_risk
from agronomy_agent.decision_route import build_decision_route_state


def test_erosion_fallback_preserves_mapped_terrain_limits_and_local_authority():
    from agronomy_agent.answer_verifier import _conservative_failure_answer
    answer = _conservative_failure_answer("soil_water", question="A Quebec LiDAR tile clips mapped depressions and flow paths. Does that prove active erosion or prescribe a drainage design?")
    assert "does not establish active erosion" in answer
    assert "local conservation guidance" in answer
    assert "NRCS guidance" not in answer
    assert "before selecting" in answer


@pytest.mark.parametrize("map_name", ["crop inventory map", "yield map", "satellite map"])
def test_unknown_map_type_is_not_renamed_by_emergency_variety_fallback(map_name):
    state = build_decision_route_state(f"Which corn hybrid should I choose from this {map_name}?", "crop_management")
    assert state.decision == "variety_trial_selection"
    answer = _decision_route_failure_answer(state)
    assert answer and "cannot select" in answer
    assert "suitability map" not in answer
    assert "favourable" not in answer


@pytest.mark.parametrize("wording,missing", [("does not replace", False), ("replaces", True)])
def test_soil_survey_boundary_recognizes_singular_negation(wording, missing):
    assessment = assess_claim_risk(
        f"The soil survey map {wording} soil tests or field observations.",
        question="How should I interpret this soil survey map?", question_type="field_data",
    )
    assert ("map_not_replacement" in assessment.missing_intent_facets) is missing
