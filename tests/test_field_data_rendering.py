from __future__ import annotations

import pytest

from agronomy_agent.leak_guard import detect_prompt_leaks
from agronomy_agent.server.services.answer_renderer import render_structured_answer


@pytest.mark.parametrize("text", ['Unique crop: ["Wheat"].', 'Row locators: [{"record":2}].', 'Values: [1, 2, 3].'])
def test_valid_data_arrays_are_not_erased_as_evaluation_regex(text):
    assert not detect_prompt_leaks(text)
    rendered = render_structured_answer(text, trace={"metadata": {"answer_policy_profile": "general_agronomy"}})
    assert text in rendered.answer
    assert not rendered.leak_classes_removed


@pytest.mark.parametrize("text", ['required_patterns: ["Wheat"]', '["required_patterns"]', '[a-z]+', '[abc]', '["Wheat"]+'])
def test_real_evaluation_markers_and_regex_are_still_detected(text):
    assert "eval_regex_fragment" in {x.leak_class for x in detect_prompt_leaks(text)}


def test_benign_array_does_not_hide_later_regex_on_the_same_line():
    text = 'Unique crop: ["Wheat"]; required_patterns: [a-z]+'
    assert "eval_regex_fragment" in {x.leak_class for x in detect_prompt_leaks(text)}
