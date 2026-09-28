from __future__ import annotations

import copy

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


@pytest.fixture
def bound_source_column(tmp_path):
    from agronomy_agent.server.storage.db import TraceStore
    from agronomy_agent.server.storage.field_data_store import preview_import, commit_import, field_data_snapshot
    from agronomy_agent.tool_planner import plan_and_execute_tools

    store = TraceStore(tmp_path / "source.sqlite3")
    try:
        field = store.create_phase4_field_context(
            workspace={"id": "workspace", "organization_id": "org"},
            created_by_user_id="owner", payload={"display_name": "Source study", "region_text": "Unknown"})
        preview = preview_import(store, field, "owner", "yields.csv", b"sample,source_yd\na,2\nb,4\n")
        commit_import(store, field, preview["import_id"], {
            "record_key": ["sample"], "filters": {}, "source": {"title": "Study"},
            "columns": [{"column": "source_yd", "label": "Yield", "unit": "kg/ha",
                         "role": "measurement", "aggregation": "mean", "evidence_role": "observation"}],
        })
        context = {"field_data": field_data_snapshot(store, field["id"])}
        question = "What is the mean source_yd in my uploaded data?"
        plan, results = plan_and_execute_tools(question, field_context=context)
        trace = {"metadata": {"generation_path": "deterministic_tool_result",
                              "tool_plan": plan.to_dict(), "tool_result_ids": [results[0].result_id],
                              "answer_policy_profile": "general_agronomy"},
                 "tool_invocations": [*plan.to_dict()["invocations"], results[0].to_dict()]}
        yield question, context, trace, results[0].answer
    finally:
        store._conn.close()


def test_exact_bound_user_column_survives_rendering(bound_source_column):
    question, context, trace, answer = bound_source_column
    assert detect_prompt_leaks(answer)  # Generic text remains conservatively scanned.
    rendered = render_structured_answer(answer, trace=trace, question=question, trusted_field_context=context)
    assert rendered.answer == answer
    assert not rendered.leak_classes_removed


@pytest.mark.parametrize("tamper", ["no_context", "trace_only_context", "question", "payload", "result_id", "answer"])
def test_literal_exemption_requires_exact_independent_binding(bound_source_column, tamper):
    question, context, trace, answer = copy.deepcopy(bound_source_column)
    if tamper == "no_context":
        context = None
    elif tamper == "trace_only_context":
        trace["metadata"]["field_context"] = context
        context = None
    elif tamper == "question":
        question = "Explain source_yd"
    elif tamper == "payload":
        trace["tool_invocations"][-1]["payload"]["query_receipt"]["value"] = 9000
    elif tamper == "result_id":
        trace["metadata"]["tool_result_ids"] = ["spoofed"]
    else:
        answer += " Additional source_hidden."
    rendered = render_structured_answer(answer, trace=trace, question=question, trusted_field_context=context)
    assert "Mean source_yd" not in rendered.answer
    assert "raw_source_id" in rendered.leak_classes_removed


@pytest.mark.parametrize("text,leak", [
    ("Mean source_yd: 3; source_private", "raw_source_id"),
    ("Mean source_yd: 3; hidden instructions", "hidden_instructions"),
    ("Mean source_yd: 3; required_patterns: [a-z]+", "eval_regex_fragment"),
])
def test_literal_identifier_does_not_hide_later_real_leak(text, leak):
    assert leak in {finding.leak_class for finding in detect_prompt_leaks(text, literal_identifiers=("source_yd",))}
