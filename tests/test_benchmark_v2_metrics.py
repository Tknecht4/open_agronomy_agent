from __future__ import annotations

import json
from pathlib import Path

import pytest

from agronomy_agent.benchmark_harness_compatibility import stable_sha256
from agronomy_agent.benchmark_v2_metrics import (
    FROZEN_CONSTRUCT_SEMANTIC_PROFILE_SHA256,
    score_case_observation,
    summarize_measurements,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "data/eval/open_agronomy_benchmark_v2_cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
HARNESS_CONTRACT = json.loads(
    (ROOT / "configs/open_agronomy_benchmark_v2_harness_contract.json").read_text(
        encoding="utf-8"
    )
)


def _case(eval_id: str) -> dict:
    return next(row for row in CASES if row["eval_id"] == eval_id)


def _semantic_profile(*, tool_id: str = "agronomic_calculator") -> dict:
    construct = HARNESS_CONTRACT["semantic_profile"]
    family = construct["tool_semantics"]["families"][
        "supplied_input_arithmetic"
    ]
    return {
        "schema_version": construct["schema_version"],
        "construct_profile_sha256": stable_sha256(construct),
        "construct_semantics": construct,
        "tool_implementations": {
            tool_id: {
                "implementation_version": f"{tool_id}_v1",
                "family": "supplied_input_arithmetic",
                "operations": list(family["operations"]),
                "authority_roles": list(family["authority_roles"]),
            }
        },
        "evidence_implementations": {},
    }


def _observation(
    case: dict,
    values: dict[str, object] | None = None,
    **overrides: object,
) -> dict:
    if values:
        overrides = {**values, **overrides}
    arm_id = str(overrides.get("arm_id") or "production_full")
    run_id = str(overrides.get("run_id") or "test-run")
    sample_id = str(overrides.get("sample_id") or "single_sample")
    tool_id = str(overrides.pop("semantic_tool_id", "agronomic_calculator"))
    result = {
        "run_id": run_id,
        "observation_id": str(
            overrides.get("observation_id")
            or f"obs::{run_id}::{sample_id}::{case['eval_id']}::{arm_id}"
        ),
        "sample_id": sample_id,
        "eval_id": case["eval_id"],
        "arm_id": arm_id,
        "model_id": "mock",
        "model_revision": "deterministic-v1",
        "model_backend": "test",
        "model_configuration_sha256": "1" * 64,
        "construct_fingerprint": "2" * 64,
        "cohort_fingerprint": "3" * 64,
        "system_id": "test-system",
        "system_revision": "v1",
        "system_configuration_sha256": "5" * 64,
        "executor_id": "test-executor",
        "executor_version": "v1",
        "result_class": "observed_system_execution_nonclaim",
        "executor_capabilities_sha256": "6" * 64,
        "semantic_profile": _semantic_profile(tool_id=tool_id),
        "implementation_receipts": {"runtime": "7" * 64},
        "component_configuration_receipts": {"runtime": "8" * 64},
        "component_contract_versions": {"runtime": "v1"},
        "feature_contract_versions": {"runtime_feature": "v1"},
    }
    result.update(overrides)
    if "selected_tools" in result and "tool_invocations" not in result:
        operation = str(case.get("expected_tool_operation") or "unit_conversion")
        result["tool_invocations"] = [
            {"tool_id": selected, "operation": operation}
            for selected in result["selected_tools"]
        ]
    result["system_fingerprint"] = stable_sha256(
        {
            "system_identity": {
                "system_id": result["system_id"],
                "system_revision": result["system_revision"],
                "system_configuration_sha256": result[
                    "system_configuration_sha256"
                ],
            },
            "executor_identity": {
                "executor_id": result["executor_id"],
                "executor_version": result["executor_version"],
                "result_class": result["result_class"],
            },
            "implementation_receipts": result["implementation_receipts"],
            "component_configuration_receipts": result[
                "component_configuration_receipts"
            ],
            "semantic_profile": result["semantic_profile"],
            "executor_capabilities_sha256": result[
                "executor_capabilities_sha256"
            ],
        }
    )
    result["observation_sha256"] = stable_sha256(result)
    return result


def test_complete_calculation_metrics_remain_separate_and_trace_tool_execution() -> None:
    case = _case("oab2::spring_wheat_stand::fully_specified_calculation")
    measured = score_case_observation(
        case,
        _observation(case, {
            "eval_id": case["eval_id"],
            "arm_id": "production_full",
            "model_id": "mock",
            "model_revision": "deterministic-v1",
            "direct_answer": True,
            "abstained": False,
            "clarifying_questions": [],
            "clarification_fields": [],
            "selected_tools": ["agronomic_calculator"],
            "tool_results": [
                {
                    "tool_id": "agronomic_calculator",
                    "operation": "seed_rate_mass",
                    "status": "calculated",
                }
            ],
            "pre_generation_intervened": False,
            "verifier_had_opportunity": True,
            "draft_verifier_intervention_required": False,
            "verifier_intervened": False,
            "draft_utility": 0.8,
            "final_utility": 0.9,
            "answer_numeric": 126.0,
            "answer_origin": "deterministic_tool_result",
            "fallback_used": False,
            "answerability_state": "answer_directly",
            "action_commitment_made": False,
        }),
    )

    values = measured["values"]
    assert values["direct_answer_rate"] == 1.0
    assert values["unnecessary_abstention"] == 0.0
    assert values["tool_selection_precision"] == 1.0
    assert values["tool_selection_recall"] == 1.0
    assert values["tool_execution_success"] == 1.0
    assert values["objective_numeric_accuracy"] == 1.0
    assert values["objective_numeric_absolute_error"] == pytest.approx(0.2)
    assert values["verifier_false_positive"] == 0.0
    assert values["verifier_false_negative"] is None
    assert values["draft_final_utility_delta"] == pytest.approx(0.1)
    assert values["risk_calibration"] == 1.0
    assert measured["observed"]["answer_origin"] == "deterministic_tool_result"


def test_missing_input_rewards_one_minimal_question_and_no_execution() -> None:
    case = _case("oab2::corn_heat_units::one_critical_input_missing")
    measured = score_case_observation(
        case,
        _observation(case, {
            "direct_answer": False,
            "abstained": False,
            "clarifying_questions": ["What was the minimum temperature?"],
            "clarification_fields": ["min_temp_c"],
            "selected_tools": ["agronomic_calculator"],
            "tool_results": [],
            "pre_generation_intervened": True,
            "verifier_had_opportunity": False,
            "verifier_intervened": False,
            "answerability_state": "ask_one_discriminating_question",
            "answer_origin": "answerability_intervention",
            "fallback_used": False,
        }),
    )

    values = measured["values"]
    assert values["clarification_question_count"] == 1
    assert values["clarification_excess_burden"] == 0
    assert values["clarification_field_precision"] == 1.0
    assert values["clarification_field_recall"] == 1.0
    assert values["clarification_minimality"] == 1.0
    assert values["unexpected_tool_execution"] == 0.0
    assert values["tool_selection_precision"] == 1.0
    assert values["tool_selection_recall"] == 1.0
    assert values["risk_calibration"] == 1.0
    assert values["unnecessary_abstention"] is None


def test_authority_case_exposes_verifier_false_negative_and_unsafe_commitment() -> None:
    case = _case("oab2::sprayer_calibration::high_consequence_authority")
    measured = score_case_observation(
        case,
        _observation(case, {
            "direct_answer": True,
            "abstained": False,
            "clarifying_questions": [],
            "clarification_fields": [],
            "selected_tools": [],
            "tool_results": [],
            "pre_generation_intervened": False,
            "verifier_had_opportunity": True,
            "draft_verifier_intervention_required": True,
            "verifier_intervened": False,
            "answerability_state": "answer_directly",
            "action_commitment_made": True,
            "answer_origin": "model",
            "fallback_used": False,
        }),
    )

    values = measured["values"]
    assert values["verifier_false_positive"] is None
    assert values["verifier_false_negative"] == 1.0
    assert values["risk_calibration"] == 0.0
    assert values["unsafe_authority_commitment"] == 1.0
    assert values["direct_answer_expectation_match"] == 0.0


def test_unknown_observations_are_missing_not_false() -> None:
    case = _case("oab2::potato_potash::benign_explanation")
    measured = score_case_observation(case, _observation(case))

    assert measured["values"]["direct_answer_rate"] is None
    assert measured["values"]["unnecessary_abstention"] is None
    assert measured["values"]["tool_selection_precision"] is None
    assert measured["values"]["verifier_false_positive"] is None
    assert measured["values"]["risk_calibration"] is None
    assert measured["values"]["fallback_rate"] is None


def test_safe_pre_generation_prevention_is_not_a_verifier_false_negative() -> None:
    case = _case("oab2::canola_nitrogen::high_consequence_authority")
    measured = score_case_observation(
        case,
        _observation(case, {
            "direct_answer": False,
            "abstained": False,
            "pre_generation_intervened": True,
            "verifier_had_opportunity": False,
            "verifier_intervened": False,
            "answerability_state": "require_authority",
            "action_commitment_made": False,
        }),
    )

    assert measured["values"]["pre_generation_intervention_rate"] == 1.0
    assert measured["values"]["verifier_opportunity_rate"] == 0.0
    assert measured["values"]["verifier_false_negative"] is None
    assert measured["values"]["verifier_false_positive"] is None


def test_unsafe_benign_draft_can_require_verifier_intervention_without_false_positive() -> None:
    case = _case("oab2::spring_wheat_stand::benign_explanation")
    measured = score_case_observation(
        case,
        _observation(case, {
            "verifier_had_opportunity": True,
            "draft_verifier_intervention_required": True,
            "verifier_intervened": True,
            "answerability_state": "answer_directly",
        }),
    )

    assert measured["values"]["verifier_false_positive"] is None
    assert measured["values"]["verifier_false_negative"] == 0.0


def test_non_tool_case_is_excluded_from_tool_selection_denominators() -> None:
    case = _case("oab2::potato_potash::benign_explanation")
    measured = score_case_observation(
        case,
        _observation(case, selected_tools=[], tool_results=[]),
    )

    assert measured["values"]["tool_selection_precision"] is None
    assert measured["values"]["tool_selection_recall"] is None


def test_summary_preserves_metric_denominators_origins_and_no_composite() -> None:
    case = _case("oab2::potato_potash::benign_explanation")
    missing_case = _case("oab2::soybean_stand::benign_explanation")
    observed = score_case_observation(
        case,
        _observation(case, {
            "arm_id": "production_full",
            "model_id": "mock",
            "model_revision": "deterministic-v1",
            "direct_answer": True,
            "abstained": False,
            "clarifying_questions": [],
            "clarification_fields": [],
            "selected_tools": [],
            "tool_results": [],
            "verifier_intervened": False,
            "answerability_state": "answer_directly",
            "pre_generation_intervened": False,
            "answer_origin": "model",
            "fallback_used": False,
        }),
    )
    missing = score_case_observation(
        missing_case,
        _observation(missing_case, {
            "arm_id": "production_full",
            "model_id": "mock",
            "model_revision": "deterministic-v1",
        }),
    )

    other_arm = score_case_observation(
        case,
        _observation(case, {
            "arm_id": "kernel_only",
            "model_id": "mock",
            "model_revision": "deterministic-v1",
            "direct_answer": False,
            "answer_origin": "mock_model",
        }),
    )
    summary = summarize_measurements([observed, missing, other_arm])

    production = next(system for system in summary["systems"] if system["arm_id"] == "production_full")
    direct = production["summary"]["metrics"]["direct_answer_rate"]
    assert direct == {"eligible_n": 1, "missing_n": 1, "sum": 1.0, "mean": 1.0}
    assert production["summary"]["answer_origin_counts"] == {"model": 1}
    assert summary["composite_score"] is None
    assert summary["composite_score_policy"] == "prohibited"
    assert summary["cross_system_overall"] is None
    assert summary["cross_system_pooling_policy"] == "prohibited"
    assert len(summary["systems"]) == 2
    assert summary["paired_contrast_status"] == "not_requested"
    assert summary["paired_contrasts"] == []
    assert set(production["by_stratum"]) == {"benign_explanation"}


def test_summary_never_pools_different_harness_cohorts_or_system_fingerprints() -> None:
    case = _case("oab2::potato_potash::benign_explanation")
    base = {
        "arm_id": "production_full",
        "model_id": "same-model",
        "model_revision": "same-revision",
        "cohort_fingerprint": "a" * 64,
        "direct_answer": True,
    }
    system_a = score_case_observation(
        case,
        _observation(
            case,
            {**base, "run_id": "run-a", "system_revision": "system-a"},
        ),
    )
    system_b = score_case_observation(
        case,
        _observation(
            case,
            {**base, "run_id": "run-b", "system_revision": "system-b"},
        ),
    )
    new_cohort = score_case_observation(
        case,
        _observation(case, {
            **base,
            "run_id": "run-c",
            "cohort_fingerprint": "d" * 64,
            "system_revision": "system-a",
        }),
    )

    summary = summarize_measurements([system_a, system_b, new_cohort])

    assert len(summary["systems"]) == 3
    assert all(item["summary"]["cases"] == 1 for item in summary["systems"])
    assert system_a["system_fingerprint"] != system_b["system_fingerprint"]


def test_metric_input_validation_rejects_out_of_range_utility_and_wrong_case() -> None:
    case = _case("oab2::soybean_stand::benign_explanation")

    with pytest.raises(ValueError, match="draft_utility"):
        score_case_observation(case, _observation(case, draft_utility=1.1))
    with pytest.raises(ValueError, match="does not match"):
        score_case_observation(case, _observation(case, eval_id="another-case"))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_metric_input_and_summary_reject_non_finite_numbers(value: float) -> None:
    case = _case("oab2::spring_wheat_stand::fully_specified_calculation")

    with pytest.raises(ValueError, match="answer_numeric must be finite"):
        score_case_observation(case, _observation(case, answer_numeric=value))

    measured = score_case_observation(case, _observation(case, direct_answer=True))
    measured["values"]["direct_answer_rate"] = value
    with pytest.raises(ValueError, match="finite numeric measurement"):
        summarize_measurements([measured])


def test_metrics_require_complete_hash_validated_identity() -> None:
    case = _case("oab2::soybean_stand::benign_explanation")

    with pytest.raises(ValueError, match="run_id"):
        score_case_observation(case, {})
    with pytest.raises(ValueError, match="model_configuration_sha256"):
        score_case_observation(
            case,
            _observation(case, model_configuration_sha256="not-a-digest"),
        )

    with pytest.raises(ValueError, match="allowed nonclaim"):
        score_case_observation(
            case,
            _observation(case, result_class="claim_eligible_performance"),
        )


def test_metrics_bind_to_frozen_construct_not_a_caller_self_hash() -> None:
    assert stable_sha256(HARNESS_CONTRACT["semantic_profile"]) == (
        FROZEN_CONSTRUCT_SEMANTIC_PROFILE_SHA256
    )
    case = _case("oab2::soybean_stand::benign_explanation")
    observation = _observation(case)
    attacker_construct = json.loads(
        json.dumps(observation["semantic_profile"]["construct_semantics"])
    )
    attacker_construct["answerability_states"].append("attacker_defined_state")
    observation["semantic_profile"]["construct_semantics"] = attacker_construct
    observation["semantic_profile"]["construct_profile_sha256"] = stable_sha256(
        attacker_construct
    )

    with pytest.raises(ValueError, match="frozen v2 construct"):
        score_case_observation(case, observation)

    valid = score_case_observation(case, _observation(case))
    valid["semantic_profile"] = observation["semantic_profile"]
    with pytest.raises(ValueError, match="frozen v2 construct"):
        summarize_measurements([valid])


def test_equivalent_tool_implementation_scores_by_frozen_semantics() -> None:
    case = _case("oab2::spring_wheat_stand::fully_specified_calculation")
    measured = score_case_observation(
        case,
        _observation(
            case,
            semantic_tool_id="equivalent_calculator",
            selected_tools=["equivalent_calculator"],
            tool_results=[
                {
                    "tool_id": "equivalent_calculator",
                    "operation": "seed_rate_mass",
                    "status": "calculated",
                }
            ],
        ),
    )

    assert measured["values"]["tool_selection_precision"] == 1.0
    assert measured["values"]["tool_selection_recall"] == 1.0
    assert measured["values"]["tool_execution_success"] == 1.0
    assert measured["observed"]["selected_tools"] == ["equivalent_calculator"]
    assert measured["observed"]["selected_tool_semantics"] == [
        "supplied_input_arithmetic:seed_rate_mass"
    ]
    assert measured["result_class"] == "observed_system_execution_nonclaim"
    assert measured["source_observation_sha256"]


def test_metrics_reject_stale_system_identity_for_new_implementation_mapping() -> None:
    case = _case("oab2::spring_wheat_stand::fully_specified_calculation")
    baseline = _observation(
        case,
        selected_tools=["agronomic_calculator"],
        tool_results=[],
    )
    replacement = _observation(
        case,
        semantic_tool_id="equivalent_calculator",
        selected_tools=["equivalent_calculator"],
        tool_results=[],
    )
    assert replacement["system_fingerprint"] != baseline["system_fingerprint"]
    replacement["system_fingerprint"] = baseline["system_fingerprint"]
    replacement["observation_sha256"] = stable_sha256(
        {
            key: value
            for key, value in replacement.items()
            if key != "observation_sha256"
        }
    )

    with pytest.raises(ValueError, match="canonical system receipt"):
        score_case_observation(case, replacement)


def test_metrics_validate_observation_to_measurement_content_lineage() -> None:
    case = _case("oab2::potato_potash::benign_explanation")
    observation = _observation(case)
    observation["direct_answer"] = True
    with pytest.raises(ValueError, match="observation content"):
        score_case_observation(case, observation)

    measured = score_case_observation(case, _observation(case))
    measured["source_observation_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="measurement lineage"):
        summarize_measurements([measured])


def test_summary_rejects_duplicate_run_sample_eval_arm_cells() -> None:
    case = _case("oab2::potato_potash::benign_explanation")
    first = score_case_observation(case, _observation(case, direct_answer=True))
    second = score_case_observation(
        case,
        _observation(case, observation_id="distinct-observation", direct_answer=False),
    )

    with pytest.raises(ValueError, match="duplicate run/sample/eval/arm"):
        summarize_measurements([first, second])


@pytest.mark.parametrize(
    ("answerability_state", "pre_generation_intervened"),
    [("require_authority", False), ("answer_directly", True)],
)
def test_risk_calibration_rejects_state_action_mismatch(
    answerability_state: str,
    pre_generation_intervened: bool,
) -> None:
    case = _case("oab2::canola_nitrogen::high_consequence_authority")

    with pytest.raises(ValueError, match="answerability_state and pre_generation"):
        score_case_observation(
            case,
            _observation(
                case,
                answerability_state=answerability_state,
                pre_generation_intervened=pre_generation_intervened,
                direct_answer=not pre_generation_intervened,
                action_commitment_made=False,
            ),
        )
