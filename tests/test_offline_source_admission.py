from __future__ import annotations

import copy

import pytest

from agronomy_agent.offline_source_admission import (
    EXPECTED_PROPOSED_USE,
    load_offline_source_admission_candidates,
    source_admission_candidate_summary,
    validate_offline_source_admission_candidates,
)


def test_default_offline_source_admission_queue_is_candidate_only() -> None:
    payload = load_offline_source_admission_candidates()
    summary = source_admission_candidate_summary(payload)

    assert summary["candidate_count"] == 11
    assert summary["all_material_use_disabled"] is True
    assert summary["training_rights_statuses"] == {"not_assessed_no_training_authorization": 11}
    assert {row["proposed_use"] == EXPECTED_PROPOSED_USE for row in payload["candidate_sources"]} == {
        True
    }


def test_candidate_queue_rejects_model_training_enablement() -> None:
    payload = copy.deepcopy(load_offline_source_admission_candidates())
    payload["candidate_sources"][0]["proposed_use"]["training"] = True

    with pytest.raises(ValueError, match="material use disabled"):
        validate_offline_source_admission_candidates(payload)


def test_candidate_queue_rejects_runtime_admission_enablement() -> None:
    payload = copy.deepcopy(load_offline_source_admission_candidates())
    payload["universal_boundary"]["runtime_admission"] = True

    with pytest.raises(ValueError, match="universal_boundary"):
        validate_offline_source_admission_candidates(payload)


def test_candidate_queue_requires_the_exact_record_or_page_identifier() -> None:
    payload = copy.deepcopy(load_offline_source_admission_candidates())
    payload["candidate_sources"][0]["source_identity"]["identifier"] = "not-a-catalogue-id"

    with pytest.raises(ValueError, match="Open Canada UUID"):
        validate_offline_source_admission_candidates(payload)
