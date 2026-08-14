from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.tool_planner import plan_and_execute_tools


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "data/eval/open_agronomy_benchmark_v2_cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def test_all_complete_v2_calculations_execute_declared_operation_within_tolerance() -> None:
    calculations = [row for row in CASES if row["stratum"] == "fully_specified_calculation"]
    assert len(calculations) >= 5

    for row in calculations:
        plan, results = plan_and_execute_tools(row["question"], field_context=row["field_context"])
        assert row["expected_tools"] == ["agronomic_calculator"]
        assert plan.status == "ready", row["eval_id"]
        assert len(results) == 1, row["eval_id"]
        assert results[0].operation == row["expected_tool_operation"]
        assert abs(float(results[0].payload["value"]) - float(row["scoring"]["reference_numeric"])) <= float(
            row["scoring"]["absolute_tolerance"]
        )


def test_all_missing_input_v2_calculations_request_exactly_one_declared_field() -> None:
    incomplete = [row for row in CASES if row["stratum"] == "one_critical_input_missing"]
    assert len(incomplete) >= 5

    for row in incomplete:
        plan, results = plan_and_execute_tools(row["question"], field_context=row["field_context"])
        assert row["expected_tools"] == ["agronomic_calculator"]
        assert plan.status == "clarification_required", row["eval_id"]
        assert not results
        assert len(plan.invocations) == 1
        assert plan.invocations[0].operation == row["expected_tool_operation"]
        assert list(plan.invocations[0].missing_inputs) == row["expected_response"]["clarification_fields"]
