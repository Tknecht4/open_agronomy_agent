"""Synthetic controls, never model observations or scientific grades."""
import copy
import math

import pytest

from agronomy_agent.release_eval_model_metrics import (
    OUTCOME_DIMENSIONS, POLICY_SCHEMA, bind_fixture_review, canonical_digest,
    rubric_digest, score_model_matrix, score_numeric_oracle,
)


def packet():
    rubrics = []; cases = []; matrix = []; rows = []; reviews = []
    for case_id, domain in (("one", "seed"), ("two", "water")):
        case = {"case_id": case_id, "case_sha256": canonical_digest({"question": case_id})}; cases.append(case)
        rubric = {**case, "domain_id": domain, "cluster_id": case_id,
                  "answerability": "answerable", "review_status": "synthetic_qa",
                  "criteria": [{"criterion_id": d, "dimension": d, "description": "synthetic " + d,
                                "weight": 1, "applicable_arms": ["raw_model", "production_full"]}
                               for d in OUTCOME_DIMENSIONS], "fatal_conditions": ["invented_rate"]}
        rubric["criteria"].append({"criterion_id": "tool", "dimension": "tool_correctness", "description": "tool QA",
                                   "weight": 1, "applicable_arms": ["production_full"]})
        rubric["rubric_sha256"] = rubric_digest(rubric); rubrics.append(rubric)
        for arm in ("raw_model", "production_full"):
            cell = {**case, "observation_id": case_id + arm, "suite_id": "qa", "trial_id": "trial-001",
                    "arm_id": arm, "model_id": "fixture_model", "model_revision": "fixture_revision", "backend_id": "synthetic",
                    "analysis_condition": {'model_config_sha256': canonical_digest('config'), 'source_sha256': canonical_digest('source'),
                                           'runtime_config_sha256': canonical_digest('runtime'), 'arm_recipe_sha256': canonical_digest(arm)}}
            matrix.append(cell)
            observation = {**cell, "status": "completed", "answer": "Synthetic QA answer", "answer_sha256": canonical_digest("Synthetic QA answer"),
                           "comparison_cohort": "qa-matched-v1", "task_input_sha256": canonical_digest(case_id)}
            rows.append(observation)
            scores = {d: 0.8 if arm == "production_full" else 0.6 for d in OUTCOME_DIMENSIONS}
            if arm == "production_full":
                scores["tool"] = 0.1
            fixture = {"case_id": case_id, "arm_id": arm, "fixture_id": case_id + arm, "synthetic_fixture": True,
                       "answer": observation["answer"], "criterion_scores": scores, "fatal_failures": [], "fatal_review_complete": True}
            reviews.append(bind_fixture_review(observation, rubric, fixture))
    policy = {"schema_version": POLICY_SCHEMA, "weight_authority": "project_choice", "missingness": "unknown_fixed_denominator",
              "failed_outcome": "zero", "truncated_outcome": "retain_labels", "domain_weights": {"seed": 1, "water": 1},
              "dimension_weights": {d: 1 for d in OUTCOME_DIMENSIONS},
              "sensitivity_profiles": [{"profile_id": "restraint_emphasis", "domain_weights": {"seed": 2, "water": 1},
                                         "dimension_weights": {d: 2 if d == "restraint" else 1 for d in OUTCOME_DIMENSIONS}}]}
    plan = {"cases": cases, "matrix": matrix, "model_scoring_policy_sha256": canonical_digest(policy)}
    return plan, rows, rubrics, reviews, policy


def run(data):
    p, o, r, v, w = data
    return score_model_matrix(p, o, rubrics=r, reviews=v, policy=w)


def test_equal_domain_common_outcomes_separate_tool_dimension():
    report = run(packet())
    assert report["status"] == "descriptive_complete"
    assert report["policy_bound_to_plan"] is True
    raw, full = report["groups"]
    assert raw["primary"]["score"] == pytest.approx(0.6)
    assert full["primary"]["score"] == pytest.approx(0.8)
    assert full["sensitivity"][0]["score"] == pytest.approx(0.8)
    assert report["cells"][1]["dimensions"]["tool_correctness"] == 0.1
    assert report["contrasts"][0]["paired_scored_n"] == 2
    assert report["contrasts"][0]["interval"]["mean_delta"] == pytest.approx(0.2)
    assert report["promotion_allowed"] is False
    assert report["policy_preregistration_verified"] is False
    assert report["contrasts"][0]["ranking_authorized"] is False


def test_no_policy_or_labels_remains_unknown():
    p, o, r, _, _ = packet()
    report = score_model_matrix(p, o, rubrics=r)
    assert report["status"] == "blocked_missing_policy"
    assert report["reviewed_n"] == 0
    assert all(g["primary"] is None for g in report["groups"])
    assert all(c["safety_unknown"] for c in report["cells"])
    assert report['cells'][0]['dimension_status']['tool_correctness'] == 'not_applicable'
    assert report['cells'][0]['dimension_status']['restraint'] == 'unknown_labels'


def test_supplied_policy_without_case_rubrics_is_partial_unknown():
    p, o, _, _, policy = packet()
    report = score_model_matrix(p, o, rubrics=[], policy=policy)
    assert report['status'] == 'partial_unknown'
    assert all(g['primary'] is None for g in report['groups'])
    assert report['missing_rubric_case_ids'] == ['one', 'two']
    assert all(c['dimension_status']['restraint'] == 'unknown_rubric' for c in report['cells'])


def test_missing_observation_fixed_denominator_not_renormalized():
    data = packet(); data[1].pop(2); data[3].pop(2)
    report = run(data); group = report["groups"][0]
    assert group["planned"] == 2 and group["missing"] == 1
    assert group["primary"]["score"] is None
    assert group["primary"]["fixed_denominator_bounds"] == pytest.approx([0.3, 0.8])
    assert report["status"] == "partial_unknown"


def test_failed_worker_zero_outcome_preserves_semantic_unknown():
    data = packet(); data[1][0]["status"] = "failed"; data[3].pop(0)
    report = run(data); group = report["groups"][0]
    assert group["failed"] == 1 and group["primary"]["score"] == pytest.approx(0.3)
    assert report["cells"][0]["dimensions"]["usefulness"] is None
    assert report["cells"][0]["safety_unknown"] is True
    assert report["contrasts"][0]["paired_scored_n"] == 2
    assert report["contrasts"][0]["interval"]["mean_delta"] == pytest.approx(0.5)


@pytest.mark.parametrize("mode,expected", [("retain_labels", 0.6), ("zero", 0.3)])
def test_truncation_explicit_policy(mode, expected):
    data = packet(); data[1][0]["finish_reason"] = "length"; data[4]["truncated_outcome"] = mode
    report = run(data)
    assert report["groups"][0]["truncated"] == 1
    assert report["groups"][0]["primary"]["score"] == pytest.approx(expected)
    assert report["policy_bound_to_plan"] is (mode == "retain_labels")
    assert report["contrasts"][0]["interval"]["mean_delta"] == pytest.approx(0.2 if mode == "retain_labels" else 0.5)


def test_missing_single_criterion_cannot_hide_in_mean():
    data = packet(); data[3][0]["criterion_scores"]["restraint"] = None
    report = run(data)
    assert report["groups"][0]["primary"]["score"] is None
    assert report["cells"][0]["dimensions"]["restraint"] is None


def test_safety_failure_stays_visible_above_high_average():
    data = packet(); data[3][1]["fatal_failures"] = ["invented_rate"]
    report = run(data)
    assert report["groups"][1]["primary"]["score"] == pytest.approx(0.8)
    assert report["groups"][1]["fatal_failures_n"] == 1
    assert report["promotion_allowed"] is False


@pytest.mark.parametrize("field,value", [("comparison_cohort", None), ("comparison_cohort", "other"), ("task_input_sha256", "a" * 64)])
def test_unknown_cohort_or_changed_facts_blocks_contrast(field, value):
    data = packet(); data[1][1][field] = value
    report = run(data)
    assert report["contrasts"][0]["incomparable_n"] == 1
    assert report["contrasts"][0]["paired_scored_n"] == 1
    assert report["contrasts"][0]["interval"]["lower_95"] is None


def test_different_outcome_mask_blocks_composite_pair():
    data = packet(); rubric = data[2][0]
    rubric["criteria"][0]["applicable_arms"] = ["raw_model"]
    rubric["rubric_sha256"] = rubric_digest(rubric)
    for review in data[3][:2]:
        review["rubric_sha256"] = rubric["rubric_sha256"]
    data[3][1]["criterion_scores"].pop("usefulness")
    report = run(data)
    assert report["contrasts"][0]["incomparable_n"] == 1
    assert report["groups"][1]["primary"]["score"] is None


def test_dependent_repeat_does_not_count_as_independent_cluster():
    data = packet()
    # Repeat one case within one cluster: only one independent observed family.
    data[0]["cases"] = data[0]["cases"][:1]; data[0]["matrix"] = data[0]["matrix"][:2]
    data[1][:] = data[1][:2]; data[2][:] = data[2][:1]; data[3][:] = data[3][:2]
    data[4]["domain_weights"] = {"seed": 1}
    data[4]["sensitivity_profiles"] = []
    report = run(data)
    assert report["contrasts"][0]["interval"]["clusters_n"] == 1
    assert report["contrasts"][0]["interval"]["lower_95"] is None


@pytest.mark.parametrize("target,key,value", [
    ("review", "answer_sha256", "a" * 64), ("review", "case_sha256", "b" * 64),
    ("review", "rubric_sha256", "c" * 64), ("observation", "answer", "mutated"),
    ("observation", "model_revision", "other"), ("observation", "case_sha256", "d" * 64)])
def test_hash_and_identity_drift_refuses(target, key, value):
    data = packet(); (data[3] if target == "review" else data[1])[0][key] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.1, 1.1, True, "1"])
def test_invalid_criterion_score_refuses(value):
    data = packet(); data[3][0]["criterion_scores"]["restraint"] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan, True])
def test_invalid_policy_weight_refuses(value):
    data = packet(); data[4]["domain_weights"]["seed"] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("target", [0, 1, 2, 3])
def test_duplicate_identity_refuses(target):
    data = packet()
    rows = data[0]["matrix"] if target == 0 else data[target]
    rows.append(copy.deepcopy(rows[0]))
    with pytest.raises(ValueError):
        run(data)


def test_unknown_and_inapplicable_labels_refuse():
    for cid in ("not_a_criterion", "tool"):
        data = packet(); data[3][0]["criterion_scores"][cid] = 1
        with pytest.raises(ValueError):
            run(data)


def test_distinct_observation_ids_cannot_duplicate_logical_cell():
    data = packet(); duplicate = dict(data[0]["matrix"][0]); duplicate["observation_id"] = "different-id"
    data[0]["matrix"].append(duplicate)
    with pytest.raises(ValueError, match="logical"):
        run(data)


def test_same_named_model_with_different_config_is_not_pooled():
    data = packet(); cell = copy.deepcopy(data[0]['matrix'][0]); cell['observation_id'] = 'second-config'
    cell['analysis_condition']['model_config_sha256'] = canonical_digest('second config')
    row = {**cell, 'status': 'completed', 'answer': 'Synthetic QA answer', 'answer_sha256': canonical_digest('Synthetic QA answer')}
    data[0]['matrix'].append(cell); data[1].append(row)
    report = run(data)
    assert len(report['groups']) == 3
    raw_groups = [g for g in report['groups'] if g['arm_id'] == 'raw_model']
    assert len(raw_groups) == 2
    assert len({g['analysis_condition_sha256'] for g in raw_groups}) == 2


def test_missing_recipe_binding_blocks_otherwise_matching_contrast():
    data = packet()
    for cell in data[0]['matrix']:
        if cell['arm_id'] == 'production_full':
            cell['analysis_condition'].pop('arm_recipe_sha256')
    for row in data[1]:
        if row['arm_id'] == 'production_full':
            row['analysis_condition'].pop('arm_recipe_sha256', None)
    report = run(data)
    assert report['contrasts'][0]['paired_scored_n'] == 0
    assert report['contrasts'][0]['identity_incomplete_n'] == 2


def test_source_mismatch_blocks_contrast_but_recipe_difference_is_visible():
    data = packet()
    baseline = run(data)
    assert baseline['contrasts'][0]['condition_differences'] == ['arm_recipe_sha256']
    assert baseline['contrasts'][0]['paired_scored_n'] == 2
    for cell in data[0]['matrix']:
        if cell['arm_id'] == 'production_full':
            cell['analysis_condition']['source_sha256'] = canonical_digest('different source')
    report = run(data)
    assert report['contrasts'][0]['paired_scored_n'] == 0
    assert report['contrasts'][0]['source_mismatch_n'] == 2


@pytest.mark.parametrize('condition', [{'source_sha256':'bad'}, {'source_sha256':123}, {'extra_pin':'a'*64}, []])
def test_invalid_condition_pin_refuses(condition):
    data = packet(); data[0]['matrix'][0]['analysis_condition'] = condition
    with pytest.raises(ValueError, match='SHA256|condition'):
        run(data)


def test_row_condition_cannot_drift_from_frozen_plan_binding():
    data = packet(); data[1][0] = copy.deepcopy(data[1][0])
    data[1][0]['analysis_condition']['runtime_config_sha256'] = canonical_digest('other runtime')
    with pytest.raises(ValueError, match='planned analysis condition'):
        run(data)


def test_outcome_contrast_does_not_require_hardware_runtime_equality():
    data = packet()
    for cell in data[0]['matrix']:
        if cell['arm_id'] == 'production_full':
            cell['analysis_condition']['runtime_config_sha256'] = canonical_digest('different hardware runtime')
    report = run(data)
    assert report['contrasts'][0]['paired_scored_n'] == 2
    assert 'runtime_config_sha256' in report['contrasts'][0]['condition_differences']


def test_right_only_case_is_retained_in_pair_coverage():
    data = packet()
    data[0]['matrix'].pop(2); data[1].pop(2); data[3].pop(2)
    contrast = run(data)['contrasts'][0]
    assert contrast['unmatched_left_n'] == 0
    assert contrast['unmatched_right_n'] == 1


def test_declared_no_tool_attempt_is_na_and_failed_unassessable_is_unknown():
    data = packet(); rubric = data[2][0]
    rubric['criteria'][-1]['applicability_condition'] = 'actual_assessable_tool_attempt'
    rubric['rubric_sha256'] = rubric_digest(rubric)
    for review in data[3][:2]:
        review['rubric_sha256'] = rubric['rubric_sha256']
    review = data[3][1]; review['criterion_scores']['tool'] = None
    review['criterion_applicability'] = {'tool': False}
    assert run(data)['cells'][1]['dimension_status']['tool_correctness'] == 'not_applicable'
    review['criterion_applicability']['tool'] = None
    assert run(data)['cells'][1]['dimension_status']['tool_correctness'] == 'unknown_labels'
    review['criterion_scores']['tool'] = 1
    with pytest.raises(ValueError, match='cannot receive a score'):
        run(data)


def test_applicability_label_cannot_remove_common_outcome_criterion():
    data = packet(); data[3][0]['criterion_applicability'] = {'usefulness': False}
    with pytest.raises(ValueError, match='conditional tool'):
        run(data)


def test_conditional_tool_grade_requires_assessable_attempt():
    data = packet(); rubric = data[2][0]
    rubric['criteria'][-1]['applicability_condition'] = 'actual_assessable_tool_attempt'
    rubric['rubric_sha256'] = rubric_digest(rubric)
    for review in data[3][:2]:
        review['rubric_sha256'] = rubric['rubric_sha256']
    with pytest.raises(ValueError, match='assessable-attempt'):
        run(data)


@pytest.mark.parametrize('field', ['case_sha256', 'answer_sha256', 'rubric_sha256'])
def test_fixture_supplied_hash_cannot_be_silently_rebound(field):
    _, observations, rubrics, _, _ = packet()
    fixture = {'case_id': observations[0]['case_id'], 'arm_id': observations[0]['arm_id'],
               'fixture_id': 'qa', 'synthetic_fixture': True, 'answer': observations[0]['answer'], field: 'f' * 64}
    with pytest.raises(ValueError, match='supplied binding'):
        bind_fixture_review(observations[0], rubrics[0], fixture)


@pytest.mark.parametrize('execution', ['unknown', {}, math.nan, math.inf, -1, 2])
def test_malformed_execution_correctness_cannot_claim_assessable_attempt(execution):
    _, observations, rubrics, _, _ = packet()
    fixture = {'case_id': observations[0]['case_id'], 'arm_id': observations[0]['arm_id'],
               'fixture_id': 'qa', 'synthetic_fixture': True, 'answer': observations[0]['answer'],
               'trace_expectations': {'attempted': True, 'execution_correctness': execution}}
    with pytest.raises(ValueError):
        bind_fixture_review(observations[0], rubrics[0], fixture)


def test_unsupported_rubric_condition_refuses():
    data = packet(); rubric = data[2][0]
    rubric['criteria'][0]['applicability_condition'] = 'magic_condition'
    rubric['rubric_sha256'] = rubric_digest(rubric)
    with pytest.raises(ValueError, match='unsupported applicability'):
        run(data)


def test_reused_case_id_cannot_reuse_old_rubric():
    data = packet(); data[2][0]["case_sha256"] = "f" * 64
    data[2][0]["rubric_sha256"] = rubric_digest(data[2][0])
    with pytest.raises(ValueError, match="rubric planned case"):
        run(data)


def test_ambiguous_cluster_text_does_not_merge_independent_units():
    data = packet(); a, b = data[2]
    a['domain_id'], a['cluster_id'] = 'a:b', 'c'
    b['domain_id'], b['cluster_id'] = 'a', 'b:c'
    for rubric in data[2]:
        rubric['rubric_sha256'] = rubric_digest(rubric)
        for review in data[3]:
            if review['observation_id'].startswith(rubric['case_id']):
                review['rubric_sha256'] = rubric['rubric_sha256']
    data[4]['domain_weights'] = {'a:b': 1, 'a': 1}; data[4]['sensitivity_profiles'] = []
    assert run(data)['contrasts'][0]['interval']['clusters_n'] == 2


def test_recorded_telemetry_preserves_phases_unknown_and_explicit_scope():
    data = packet(); data[1][0].update(elapsed_seconds=4.0, prompt_tokens=90, generation_tokens=120,
                                    performance={'load_seconds': 2.0}, performance_scope='load includes tokenizer')
    cell = run(data)['cells'][0]
    assert cell['source_observed_metrics']['load_seconds'] == 2.0
    assert cell['source_observed_metrics']['elapsed_seconds'] == 4.0
    assert cell['source_observed_metrics']['input_tokens'] == 90
    assert cell['source_observed_metrics']['compile_seconds'] is None
    assert cell['source_observed_metrics']['prefill_seconds'] is None
    assert cell['metrics_scope'] == 'load includes tokenizer'


@pytest.mark.parametrize('field,value', [('load_seconds', -1), ('input_tokens', 1.2), ('compile_seconds', math.nan)])
def test_invalid_telemetry_refuses(field, value):
    data = packet(); data[1][0]['performance'] = {field: value}
    with pytest.raises(ValueError):
        run(data)


def test_finite_weights_with_overflowing_sum_refuse():
    data = packet(); rubric = data[2][0]
    for criterion in rubric['criteria']:
        criterion['weight'] = 1e308
    rubric['rubric_sha256'] = rubric_digest(rubric)
    with pytest.raises(ValueError, match='weight sum'):
        run(data)


@pytest.mark.parametrize('key', ['value_decimal', 'absolute_tolerance_decimal'])
def test_missing_oracle_gold_does_not_become_zero(key):
    oracle = {'case_id': 'qa', 'criterion_id': 'water', 'quantity_id': 'water_volume',
              'value_decimal': '0', 'unit': 'L/ha', 'absolute_tolerance_decimal': '0'}
    oracle.pop(key)
    with pytest.raises(ValueError, match='explicit oracle'):
        score_numeric_oracle('0 L/ha', oracle)


def test_scalar_oracle_existing_unit_and_contradiction_contract():
    oracle = {"case_id": "qa", "criterion_id": "water", "quantity_id": "water_volume",
              "value_decimal": "120", "unit": "L/ha", "absolute_tolerance_decimal": "0.1"}
    for answer, score in (("Apply 120 L/ha.", 1), ("Apply 120 kg/ha.", 0), ("120", 0),
                          ("120 L/ha or 300 L/ha.", 0), ("Do not apply 120 L/ha.", 0)):
        assert score_numeric_oracle(answer, oracle)["score"] == score


@pytest.mark.parametrize("key,value", [("value_decimal", "NaN"), ("value_decimal", "1e999"),
                                      ("value_decimal", "1e-1000"),
                                      ("absolute_tolerance_decimal", "-1"), ("value_decimal", 120)])
def test_invalid_decimal_oracle_refuses(key, value):
    oracle = {"case_id": "qa", "criterion_id": "water", "quantity_id": "water_volume",
              "value_decimal": "120", "unit": "L/ha", "absolute_tolerance_decimal": "0.1"}
    oracle[key] = value
    with pytest.raises(ValueError):
        score_numeric_oracle("120 L/ha", oracle)
