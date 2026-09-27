from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from agronomy_agent.v3_candidate_runner import AppendOnlyObservationLedger, build_matrix, execute_in_fresh_process, matrix_manifest, run_matrix


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_candidate_matrix_has_declared_model_arm_shape() -> None:
    config = json.loads((ROOT / "configs/open_agronomy_v3_competence_candidate.json").read_text())
    # This checks matrix orchestration, not benchmark content. Use unique,
    # synthetic case identities so a clean checkout needs no ignored inputs.
    external_cases = [
        {"eval_id": f"fixture-external-{index:03d}", "question": "Synthetic matrix question."}
        for index in range(config["external_dataset"]["rows"])
    ]
    regional_cases = [
        {"eval_id": f"fixture-regional-{index:03d}", "question": "Synthetic matrix question."}
        for index in range(config["regional_case_count"])
    ]
    matrix = build_matrix(
        config=config,
        external_cases=external_cases,
        regional_cases=regional_cases,
    )
    assert len(matrix) == 17_640
    counts = Counter((row.model_key, row.lane) for row in matrix)
    assert counts[("gemma4_e2b_production", "public_external_competence_candidate")] == 7_200
    assert counts[("gemma4_e2b_production", "canadian_regional_competence_candidate")] == 2_592
    assert counts[("luna_remote_comparator", "public_external_competence_candidate")] == 7_200
    assert counts[("luna_remote_comparator", "canadian_regional_competence_candidate")] == 648
    luna_regional = {row.arm for row in matrix if row.model_key == "luna_remote_comparator" and row.lane.startswith("canadian_")}
    assert luna_regional == {"raw_model", "kernel_only", "production_full"}
    assert matrix_manifest(matrix)["claim_eligible"] is False


def test_ledger_requires_an_exact_resume_prefix(tmp_path: Path) -> None:
    config = {
        "benchmark_id": "fixture",
        "candidate_models": [{"model_key": "m", "model_id": "id", "model_revision": "r", "backend": "mock", "external_arms": ["raw_model"], "regional_arms": []}],
        "trial_ids": ["trial-001"],
    }
    matrix = build_matrix(config=config, external_cases=[{"eval_id": "one", "question": "q"}], regional_cases=[])
    ledger = AppendOnlyObservationLedger(tmp_path / "observations.jsonl", matrix)
    ledger.append({"observation_id": matrix[0].observation_id, "status": "terminal_failure"})
    assert ledger.completed_prefix() == 1
    with pytest.raises(ValueError, match="already complete"):
        ledger.append({"observation_id": matrix[0].observation_id})
    (tmp_path / "observations.jsonl").write_text('{"observation_id":"wrong"}\n')
    with pytest.raises(ValueError, match="exact frozen-matrix prefix"):
        ledger.completed_prefix()


def test_matrix_runner_resumes_without_retrying_completed_rows(tmp_path: Path) -> None:
    config = {
        "benchmark_id": "fixture",
        "candidate_models": [{"model_key": "m", "model_id": "id", "model_revision": "r", "backend": "mock", "external_arms": ["raw_model"], "regional_arms": []}],
        "trial_ids": ["trial-001"],
    }
    matrix = build_matrix(config=config, external_cases=[{"eval_id": "one", "question": "q"}, {"eval_id": "two", "question": "q2"}], regional_cases=[])
    ledger = AppendOnlyObservationLedger(tmp_path / "observations.jsonl", matrix)
    ledger.append({"observation_id": matrix[0].observation_id, "status": "complete"})
    calls: list[str] = []

    def execute(request):
        calls.append(request.observation_id)
        return {"observation_id": request.observation_id, "status": "complete"}

    assert run_matrix(matrix=matrix, ledger=ledger, executor=execute) == 1
    assert calls == [matrix[1].observation_id]


def test_fresh_process_executor_preserves_identity_and_bounds_stalls() -> None:
    config = {
        "benchmark_id": "fixture",
        "candidate_models": [{"model_key": "m", "model_id": "id", "model_revision": "r", "backend": "mock", "external_arms": ["raw_model"], "regional_arms": []}],
        "trial_ids": ["trial-001"],
    }
    request = build_matrix(config=config, external_cases=[{"eval_id": "one", "question": "q"}], regional_cases=[])[0]
    completed = execute_in_fresh_process(
        request,
        executor_ref="agronomy_agent.mock_candidate_executor:echo_observation",
        timeout_seconds=5,
    )
    assert completed["observation_id"] == request.observation_id
    timed_out = execute_in_fresh_process(
        request,
        executor_ref="agronomy_agent.mock_candidate_executor:stalled_observation",
        timeout_seconds=0.1,
    )
    assert timed_out["status"] == "terminal_failure"
    assert timed_out["terminal_receipt"]["failure_class"] == "timeout"
