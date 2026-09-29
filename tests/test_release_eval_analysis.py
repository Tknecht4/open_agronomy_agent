from __future__ import annotations

from copy import deepcopy
import json

import pytest

from agronomy_agent.release_eval_analysis import (
    bind_reviews,
    compare,
    public_projection,
    summarize,
)
from agronomy_agent.release_evaluation import COMPONENTS, digest

REVISION = "a" * 40
HASH = "b" * 64
POLICY = {
    "maximum_new_failed_checks": 0,
    "maximum_numeric_accuracy_regression": 0,
    "maximum_positive_recall_at_7_regression": 0,
    "maximum_introduced_material_errors": 0,
    "maximum_required_completion_regression": 0,
    "maximum_latency_p95_ratio": 1.25,
    "maximum_peak_memory_ratio": 1.25,
    "minimum_performance_samples": 2,
}


def fixture(
    *, profile="baseline", scores=(100, 100), review_required=False, required_coverage=0
):
    cases, matrix, rows = [], [], []
    for index, score in enumerate(scores):
        case = {
            "suite_id": "synthetic",
            "case_id": f"case-{index}",
            "question": f"Synthetic quantity {index}",
            "scoring": {"method": "numeric_tolerance"},
            "review_required": review_required,
        }
        cases.append(case)
        cell = {
            "observation_id": f"observation-{index}",
            "suite_id": "synthetic",
            "case_id": case["case_id"],
            "case_sha256": digest(case),
            "scenario_family": f"family-{index}",
            "lane": "agronomy",
            "arm_id": "production_full",
            "trial_id": "trial-001",
            "backend": "mlx",
        }
        matrix.append(cell)
        stages = {
            stage: {"sha256": digest([index, stage]), "text": f"Private {stage} answer"}
            for stage in ("draft", "post_verification", "final")
        }
        turn = {
            "status": "completed",
            "execution_kind": "production",
            "model_execution": {
                "model_generation_eligible": True,
                "synthetic": False,
                "disposition": "model_generated",
            },
            "model_identity": {"status": "verified_runtime_receipt"},
            "model_revision_observation": {
                "configured": REVISION,
                "resolved": REVISION,
                "verified": True,
            },
            "generation_stats": {"generation_tokens": 10, "time_to_first_token_ms": 10},
            "verification_generation_stats": {"generation_tokens": 2},
            "elapsed_ms": 100,
            "peak_memory_bytes": 1000,
            "answer_stages": stages,
            "profiler_spans": [
                {"stage": "model.decode_stream", "duration_ms": 70, "status": "ok"}
            ],
            "source_receipts": [{"doc_id": "private-source"}],
            "graph_receipts": [],
            "tool_results": [],
        }
        rows.append(
            {
                **cell,
                "status": "completed",
                "answer_sha256": digest([index, "final"]),
                "review_required": review_required,
                "checks": [],
                "turns": [turn],
                "independent_score": {"rubric": "numeric_tolerance", "score": score},
            }
        )
    plan = {
        "suite_id": "synthetic_release",
        "run_id": "test-run",
        "profile": profile,
        "matrix": matrix,
        "cases": cases,
        "required_components": sorted(COMPONENTS),
        "source": {"commit": REVISION, "source_sha256": HASH},
        "registry_sha256": HASH,
        "cohort_sha256": HASH,
        "scorer_version": "scoring_v1",
        "model": {"id": "fixture/model", "revision": REVISION, "config_sha256": HASH},
        "sampling": {"seed": 42, "trials": 1, "max_tokens": 640},
        "counts": {
            "cases": len(cases),
            "observations": len(matrix),
            "families": len(matrix),
        },
        "domain_policy": {"required_review_coverage": required_coverage},
    }
    components = [
        {
            "component": name,
            "status": "pass",
            "metrics": {"positive_recall_at_7": 1} if name == "retrieval" else {},
        }
        for name in sorted(COMPONENTS)
    ]
    return plan, rows, components


def report(*, scores=(100, 100), reviews=(), **kwargs):
    plan, rows, components = fixture(scores=scores, **kwargs)
    return summarize(
        plan,
        rows,
        components,
        environment={"performance_environment_sha256": HASH},
        reviews=reviews,
    )


def label(row, **updates):
    return {
        "observation_id": row["observation_id"],
        "case_sha256": row["case_sha256"],
        "answer_sha256": row["answer_sha256"],
        "reviewer_id": "fixture-reviewer",
        "reviewer_type": "human_domain_reviewer",
        "rubric_sha256": HASH,
        "required_complete": True,
        "optional_usefulness": None,
        "source_supported": True,
        "material_error": False,
        "unnecessary_abstention": False,
        **updates,
    }


def check(comparison, identifier):
    return next(item for item in comparison["checks"] if item["id"] == identifier)


def test_baseline_requires_real_verified_generation_and_required_components():
    plan, rows, components = fixture()
    good = summarize(plan, rows, components, environment={})
    assert good["status"] == "engineering_pass"
    for mutation in ("mock", "no_stats", "revision_mismatch", "synthetic"):
        bad_rows = deepcopy(rows)
        for row in bad_rows:
            turn = row["turns"][0]
            if mutation == "mock":
                row["backend"] = "mock"
            elif mutation == "no_stats":
                turn["generation_stats"] = {}
            elif mutation == "revision_mismatch":
                turn["model_revision_observation"]["resolved"] = "wrong"
            else:
                turn["model_execution"]["synthetic"] = True
        result = summarize(plan, bad_rows, components, environment={})
        assert result["status"] == "blocked"
        assert result["failures"]["model_execution_missing"] is True
    missing_component = summarize(plan, rows, components[:-1], environment={})
    assert missing_component["status"] == "blocked"
    assert "required_component_coverage" in missing_component["failures"]["components"]


def test_planned_numeric_scores_never_drop_failed_or_missing_cells():
    plan, rows, components = fixture(scores=(100, 100, 100))
    rows[1]["status"] = "failed"
    rows[1].pop("independent_score")
    rows.pop()
    result = summarize(plan, rows, components, environment={})
    metric = result["metrics"]["numeric_accuracy"]
    assert metric == {"denominator_n": 3, "eligible_n": 2, "missing_n": 1, "mean": 0.5}
    assert result["status"] == "blocked"
    assert result["counts"]["numeric_scores_missing"] == 2
    assert result["family_summaries"]["family-1"]["failed_n"] == 1
    assert result["family_summaries"]["family-2"]["missing_n"] == 1


def test_nonfinite_measurements_are_explicit_blockers_and_serializable():
    plan, rows, components = fixture()
    rows[0]["independent_score"]["score"] = float("nan")
    rows[1]["turns"][0]["elapsed_ms"] = float("inf")
    result = summarize(plan, rows, components, environment={})
    assert result["status"] == "blocked"
    assert result["failures"]["invalid_measurements"]
    assert result["metrics"]["numeric_accuracy"]["denominator_n"] == 2
    assert result["metrics"]["numeric_accuracy"]["missing_n"] == 1
    json.dumps(result, allow_nan=False)


def test_lane_and_family_semantic_unknowns_and_instrument_counts_are_explicit():
    result = report(review_required=True)
    assert result["status"] == "engineering_pass"
    assert result["domain_status"] == "review_pending"
    assert result["lane_summaries"]["agronomy"]["semantic"]["unknown_n"] == 2
    assert (
        result["family_summaries"]["family-0"]["semantic"]["status"] == "review_pending"
    )
    assert result["metrics"]["model_execution"]["verified_generated_turns"] == 2
    assert result["metrics"]["source_coverage"]["document_receipts_n"] == 2
    assert result["metrics"]["stage_timings"]["model.decode_stream"]["samples"] == 2
    assert result["metrics"]["cost"]["currency_cost"] is None


def test_aggregate_numeric_improvement_cannot_conceal_case_regression():
    result = compare(report(scores=(0, 100)), report(scores=(100, 50)), POLICY)
    assert check(result, "numeric_accuracy")["passed"] is True
    assert check(result, "no_paired_numeric_case_regression")["passed"] is False
    assert result["status"] == "blocked"


def test_comparison_requires_planned_observation_and_question_contract():
    original = report()
    for key in ("planned_observations", "observations"):
        altered = deepcopy(original)
        altered[key].pop()
        result = compare(original, altered, POLICY)
        assert check(result, "planned_production_identity_coverage")["passed"] is False
        assert result["status"] == "blocked"
    changed_question = deepcopy(original)
    changed_question["observations"][0]["question_sha256"] = "different-question"
    assert (
        check(
            compare(original, changed_question, POLICY),
            "paired_question_and_case_contract",
        )["passed"]
        is False
    )
    nonfinite = deepcopy(original)
    nonfinite["metrics"]["performance"]["elapsed_ms"]["p95"] = float("inf")
    assert compare(original, nonfinite, POLICY)["status"] == "blocked"


def test_optional_unreviewed_semantics_remain_pending_without_assessed_pass():
    result = compare(report(review_required=True), report(review_required=True), POLICY)
    assert result["status"] == "pass"
    assert result["semantic_status"] == "review_pending_not_assessed"
    assert check(result, "required_completion")["passed"] is None
    assert check(result, "required_completion")["required"] is False
    assert result["paired_completion_uncertainty"]["status"] == "pending_no_pairs"


def test_required_review_coverage_uses_policy_and_rubric_contract():
    plan, rows, components = fixture(review_required=True, required_coverage=1)
    missing = summarize(
        plan, rows, components, environment={"performance_environment_sha256": HASH}
    )
    assert missing["status"] == "blocked"
    assert missing["domain_status"] == "required_review_missing"
    labels = [label(row) for row in rows]
    reference = summarize(
        plan,
        rows,
        components,
        environment={"performance_environment_sha256": HASH},
        reviews=labels,
    )
    candidate_labels = deepcopy(labels)
    candidate_labels[0]["rubric_sha256"] = "c" * 64
    candidate = summarize(
        plan,
        rows,
        components,
        environment={"performance_environment_sha256": HASH},
        reviews=candidate_labels,
    )
    result = compare(reference, candidate, POLICY)
    assert check(result, "paired_review_rubric")["passed"] is False
    assert check(result, "paired_required_review_coverage")["passed"] is False
    assert result["status"] == "blocked"


def test_cluster_uncertainty_is_deterministic_and_repetitions_stay_clustered():
    reference, candidate = report(scores=(0, 0)), report(scores=(100, 50))
    first = compare(reference, candidate, POLICY)
    second = compare(reference, candidate, POLICY)
    assert first["paired_numeric_uncertainty"] == second["paired_numeric_uncertainty"]
    assert first["paired_numeric_uncertainty"]["clusters_n"] == 2
    for target in (reference, candidate):
        for key in ("planned_observations", "observations"):
            for row in target[key]:
                row["scenario_family"] = "one-shared-family"
    result = compare(reference, candidate, POLICY)
    assert result["paired_numeric_uncertainty"]["clusters_n"] == 1
    assert result["paired_numeric_uncertainty"]["paired_n"] == 2
    assert (
        result["paired_numeric_uncertainty"]["status"]
        == "insufficient_independent_clusters"
    )


def test_nonproduction_arms_do_not_contaminate_release_numeric_gate():
    reference, candidate = report(), report()
    for target, score in ((reference, 100), (candidate, 0)):
        for key in ("planned_observations", "observations"):
            reference_arm = deepcopy(target[key][0])
            reference_arm.update(arm_id="raw_model", observation_id="raw-observation")
            if key == "observations":
                reference_arm["independent_score"]["score"] = score
            target[key].append(reference_arm)
    result = compare(reference, candidate, POLICY)
    assert result["status"] == "pass"
    assert result["paired_numeric_uncertainty"]["paired_n"] == 2
    benefit = result["arm_benefit_diagnostics"]["candidate"]["raw_model"]
    assert benefit["status"] == "diagnostic_only"
    assert benefit["numeric_benefit"]["mean_delta"] == 1


def test_stage_reviews_bind_hashes_and_measure_intervention_without_inference():
    plan, rows, components = fixture(review_required=True)
    stage_hashes = rows[0]["turns"][0]["answer_stages"]
    review = label(
        rows[0],
        stage_labels={
            "draft": {
                "sha256": stage_hashes["draft"]["sha256"],
                "required_complete": False,
                "material_error": True,
                "optional_usefulness": 0.2,
            },
            "final": {
                "sha256": stage_hashes["final"]["sha256"],
                "required_complete": True,
                "material_error": False,
                "optional_usefulness": 0.7,
            },
        },
        optional_usefulness=0.7,
    )
    result = summarize(plan, rows, components, environment={}, reviews=[review])
    benefit = result["metrics"]["intervention_benefit"]
    assert benefit["completion_delta"] == {
        "denominator_n": 2,
        "eligible_n": 1,
        "missing_n": 1,
        "mean": 1,
    }
    assert benefit["material_error"]["removed_n"] == 1
    assert benefit["material_error"]["unknown_pair_n"] == 1
    invalid = deepcopy(review)
    invalid["stage_labels"]["draft"]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="stage label hash"):
        bind_reviews(rows, [invalid])
    incompatible = deepcopy(review)
    incompatible["stage_labels"]["final"]["material_error"] = True
    with pytest.raises(ValueError, match="conflict"):
        bind_reviews(rows, [incompatible])


def test_public_projection_excludes_nested_private_data_and_check_details():
    result = report(review_required=True)
    secret = "/private/farmer/farm-answer-and-prompt"
    result["environment"] = {"hardware": {"processor": secret}}
    result["model"]["cache_path"] = secret
    result["metrics"]["private_raw_answer"] = secret
    result["metrics"]["performance"]["elapsed_ms"]["private_detail"] = secret
    result["components"][0]["metrics"]["raw_answer"] = secret
    result["failures"]["failed_checks"] = [{"id": "private", "detail": secret}]
    result["family_summaries"][secret] = deepcopy(
        result["family_summaries"]["family-0"]
    )
    result["comparison"] = {
        "status": "blocked",
        "semantic_status": "review_pending_not_assessed",
        "checks": [
            {
                "id": "required_completion",
                "passed": None,
                "required": False,
                "detail": {"answer": secret},
            },
            {"id": secret, "passed": False},
        ],
    }
    public = public_projection(result)
    encoded = json.dumps(public, allow_nan=False)
    assert secret not in encoded
    assert "Private final answer" not in encoded
    assert "semantic_reviews" not in public
    assert public["comparison"]["status"] == "blocked"
    assert public["comparison"]["checks"] == [
        {"id": "required_completion", "passed": None, "required": False}
    ]
    assert all("family_sha256" in row for row in public["family_summaries"])


def test_completed_reference_numeric_failure_is_retained_as_diagnostic_score():
    plan, rows, components = fixture()
    raw_cell = deepcopy(plan["matrix"][0])
    raw_cell.update(arm_id="raw_model", observation_id="raw-reference")
    plan["matrix"].append(raw_cell)
    raw_row = deepcopy(rows[0])
    raw_row.update(raw_cell)
    raw_row["independent_score"]["score"] = 0
    raw_row["checks"] = []
    rows.append(raw_row)
    result = summarize(plan, rows, components, environment={})
    assert result["status"] == "engineering_pass"
    assert result["metrics"]["numeric_accuracy"]["mean"] == 1
    assert result["metrics"]["numeric_accuracy"]["denominator_n"] == 2
    raw = next(row for row in result["observations"] if row["arm_id"] == "raw_model")
    assert raw["independent_score"]["score"] == 0
    assert raw["numeric_score_status"] == "observed"
    assert result["failures"]["numeric_scores_missing"] == []
