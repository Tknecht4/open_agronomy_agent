from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import _decision_route_failure_answer
from agronomy_agent.decision_route import build_decision_route_state


@pytest.mark.parametrize("map_name", ["crop inventory map", "yield map", "satellite map"])
def test_unknown_map_type_is_not_renamed_by_emergency_variety_fallback(map_name):
    state = build_decision_route_state(f"Which corn hybrid should I choose from this {map_name}?", "crop_management")
    assert state.decision == "variety_trial_selection"
    answer = _decision_route_failure_answer(state)
    assert answer and "cannot select" in answer
    assert "suitability map" not in answer
    assert "favourable" not in answer
