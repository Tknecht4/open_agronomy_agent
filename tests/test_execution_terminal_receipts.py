from __future__ import annotations

import pytest

from agronomy_agent.execution_core import (
    EXECUTION_STAGE_IDS,
    ExecutionTerminalReceipt,
    StageBudget,
)


def test_failure_receipt_retains_prefix_and_pending_topology() -> None:
    completed = tuple({"stage_id": stage_id} for stage_id in EXECUTION_STAGE_IDS[:3])
    receipt = ExecutionTerminalReceipt.failure(
        execution_id="observation-1",
        failed_stage=EXECUTION_STAGE_IDS[3],
        completed_stage_receipts=completed,
        failure_class="timeout",
        error_type="TimeoutError",
        elapsed_seconds=5.0,
        timeout_seconds=5.0,
        cancellation="terminate_then_kill",
    )
    assert receipt.status == "failed"
    assert receipt.pending_stage_ids == EXECUTION_STAGE_IDS[4:]
    assert len(receipt.receipt_sha256) == 64


def test_failure_receipt_rejects_fabricated_nonprefix_completion() -> None:
    with pytest.raises(ValueError, match="ordered topology prefix"):
        ExecutionTerminalReceipt.failure(
            execution_id="observation-1",
            failed_stage="document_retrieval",
            completed_stage_receipts=({"stage_id": "routing"}, {"stage_id": "tool_planning"}),
            failure_class="exception",
            error_type="RuntimeError",
            elapsed_seconds=1.0,
            cancellation="not_required",
        )


def test_stage_budget_fails_closed_after_deadline() -> None:
    budget = StageBudget(
        "routing",
        timeout_seconds=0.001,
        started_monotonic=0.0,
    )
    with pytest.raises(TimeoutError):
        budget.check()
