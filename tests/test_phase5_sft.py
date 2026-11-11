from __future__ import annotations

import copy

import pytest

from agronomy_agent.phase5_sft import (
    is_held_out_eval_trace, trace_to_sft_candidate, training_lineage_block_reason,
    training_lineage_snapshot,
)


EVALUATION_LINEAGE = {
    "is_evaluation_case": True,
    "evaluation_suite_id": "synthetic_exposed_evaluation_suite",
    "evaluation_case_id": "synthetic_eval_case_01",
    "exposure": "exposed_development",
}


def _trace():
    return {
        "trace_id": "synthetic-trace", "review_status": "approved",
        "repair_layer": "answer_discipline", "failure_class": "unsupported_answer",
        "source_evidence": [{"doc_id": "synthetic-source"}],
        "metrics": {"leak_check_passed": True},
        "trace": {
            "prompt_messages": [{"role": "user", "content": "Synthetic question."}],
            "structured_answer": {"answer": "Synthetic answer."}, "metadata": {},
        },
    }


@pytest.mark.parametrize("container", [
    "top", "labels", "review_labels", "metrics", "trace", "metadata", "source_lineage",
    "answer_lineage", "structured_answer", "source_evidence", "span", "trace_event", "message",
])
def test_all_evaluation_lineage_locations_block_candidate(container):
    trace = _trace()
    lineage = copy.deepcopy(EVALUATION_LINEAGE)
    if container == "top":
        trace.update(lineage)
    elif container in {"labels", "review_labels", "metrics"}:
        trace.setdefault(container, {}).update(lineage)
    elif container in {"source_lineage", "answer_lineage"}:
        trace[container] = {"metadata": lineage}
    elif container == "trace":
        trace["trace"].update(lineage)
    elif container in {"metadata", "structured_answer"}:
        trace["trace"][container].update(lineage)
    elif container == "source_evidence":
        trace[container][0]["provenance"] = lineage
    elif container == "span":
        trace["spans"] = [{"metadata": lineage}]
    elif container == "trace_event":
        trace["trace_events"] = [{"payload": {"metadata": lineage}}]
    else:
        trace["messages"] = [{"metadata": lineage, "content": "Synthetic message."}]
    assert is_held_out_eval_trace(trace)
    assert training_lineage_block_reason(trace) == "evaluation_lineage"
    assert trace_to_sft_candidate(trace, reviewer_id="synthetic-reviewer", consented=True) is None


@pytest.mark.parametrize("marker", [
    {"is_evaluation_case": True}, {"is_evaluation_answer": "true"}, {"is_evaluation_trace": 1},
    {"evaluation_suite_id": "suite"}, {"evaluation_case_id": "case"},
    {"evaluation_answer_id": "answer"}, {"evaluation_trace_id": "trace"},
    {"benchmark_case_id": "case"}, {"held_out_eval": True}, {"held_out": True},
    {"split": "test"}, {"split": "train", "dataset_split": "evaluation"},
    {"is_evaluation_case": False, "evaluation_suite_id": "suite", "split": "train"},
    {"eval_id": "synthetic-native-eval"}, {"benchmark_id": "synthetic-native-benchmark"},
    {"source_eval_id": "synthetic-source-eval"}, {"evaluation_partition": "internal"},
    {"eval_metadata": {"benchmark_lane": "synthetic-lane"}},
    {"benchmark_generation_input": {"schema_version": "open_agronomy_agent.benchmark_generation_input.v1"}},
    {"suite_id": "synthetic-suite", "case_id": "synthetic-case", "exposure": "exposed_development"},
    {"schema_version": "open_agronomy_agent.release_product_cell.v1", "case_id": "synthetic-case"},
])
def test_evaluation_identity_cannot_be_overridden_by_training_or_false_flags(marker):
    assert is_held_out_eval_trace({"metadata": marker})


@pytest.mark.parametrize("marker", [
    {"is_evaluation_case": None}, {"is_evaluation_answer": "unknown"},
    {"evaluation_case_id": "unknown"}, {"evaluation_suite_id": None},
    {"lineage_status": "unverified"}, {"provenance_status": "pending"}, {"split": "unknown"},
    {"lineage": {"status": "unknown"}}, {"provenance": {"status": "unverified"}},
    {"source_lineage": "unknown"}, {"eval_metadata": {}},
    {"evaluation_lineage": {}}, {"evaluation_lineage": []},
    {"evaluation_lineage": False}, {"evaluation_lineage": None},
])
def test_explicitly_unresolved_lineage_is_not_training_authorization(marker):
    trace = _trace()
    trace["trace"]["metadata"] = marker
    assert training_lineage_block_reason(trace) == "unresolved_lineage"
    assert trace_to_sft_candidate(trace, reviewer_id="synthetic-reviewer", consented=True) is None


def test_original_source_family_and_exposure_are_not_evaluation_case_identity():
    trace = _trace()
    metadata = {
        "is_evaluation_case": False, "split": "train", "exposure": "exposed_research",
        "source_dataset": "When2Call", "source_version": "synthetic-pin",
        "source_case_id": "original-training-row", "case_id": "original-source-case",
    }
    trace["trace"]["metadata"] = metadata
    candidate = trace_to_sft_candidate(trace, reviewer_id="synthetic-reviewer", consented=True)
    assert not is_held_out_eval_trace(trace)
    assert candidate is not None
    assert any(item.get("source_dataset") == "When2Call" for item in candidate.labels["source_lineage"])
    assert any(item.get("is_evaluation_case") is False for item in candidate.labels["source_lineage"])
    # Content that quotes a marker is not a provenance declaration.
    trace["trace"]["prompt_messages"][0]["content"] = '{"is_evaluation_case": true}'
    assert trace_to_sft_candidate(trace, reviewer_id="synthetic-reviewer", consented=True) is not None


@pytest.mark.parametrize("missing_gate", ["consent", "review", "leak", "evidence", "trace_id", "private_consent"])
def test_nominal_training_gates_remain_required(missing_gate):
    trace = _trace()
    consented = missing_gate != "consent"
    if missing_gate == "review":
        trace["review_status"] = "pending"
    elif missing_gate == "leak":
        trace["metrics"]["leak_check_passed"] = False
    elif missing_gate == "evidence":
        trace["source_evidence"] = []
    elif missing_gate == "trace_id":
        trace.pop("trace_id")
    elif missing_gate == "private_consent":
        trace["trace"]["metadata"]["private_field_data"] = True
    assert trace_to_sft_candidate(trace, reviewer_id="synthetic-reviewer", consented=consented) is None


def test_lineage_walk_handles_shared_and_cyclic_metadata_without_scanning_text():
    metadata = {"source_dataset": "synthetic-source"}
    metadata["lineage"] = metadata
    trace = {"metadata": metadata, "labels": metadata, "content": {"is_evaluation_case": True}}
    assert training_lineage_block_reason(trace) is None
    metadata["is_evaluation_answer"] = True
    assert is_held_out_eval_trace(trace)


@pytest.mark.parametrize("declaration", [
    {"lineage": {"status": "unknown"}}, {"eval_metadata": {}}, {"source_lineage": "unknown"},
    {"evaluation_lineage": {}}, {"evaluation_lineage": []}, {"evaluation_lineage": False}, {"evaluation_lineage": None},
])
def test_compact_snapshot_preserves_unresolved_declarations(declaration):
    snapshot = training_lineage_snapshot({"metadata": declaration})
    assert training_lineage_block_reason({"labels": {"source_lineage": snapshot}}) == "unresolved_lineage"
    assert training_lineage_snapshot({"labels": {"source_lineage": snapshot}}) == snapshot
