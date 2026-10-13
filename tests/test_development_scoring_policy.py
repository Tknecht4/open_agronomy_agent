"""Public synthetic controls exercise the documented CLI, never a model grade."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys

import pytest

from agronomy_agent.release_eval_model_metrics import OUTCOME_DIMENSIONS, validate_policy
from agronomy_agent.release_eval_reanalysis import analyze_development_panel
from agronomy_agent.release_evaluation import normalize_case, worker_case

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / 'tests/fixtures/development_scoring_v1'
POLICY = ROOT / 'configs/model_scoring_development_v1.json'


def test_provisional_policy_covers_ten_domains_and_five_common_outcomes():
    policy = json.loads(POLICY.read_text())
    normalized = validate_policy(policy, set(policy['domain_weights']))
    assert policy['policy_id'] == 'agronomic_development_balanced_v1'
    assert policy['status'] == 'provisional_exposed_development'
    assert len(normalized['domain_weights']) == 10
    assert set(normalized['dimension_weights']) == set(OUTCOME_DIMENSIONS)
    assert set(normalized['domain_weights'].values()) == {0.1}
    assert set(normalized['dimension_weights'].values()) == {0.2}
    assert normalized['truncated_outcome'] == 'zero'
    assert normalized['missingness'] == 'unknown_fixed_denominator'


def test_documented_cli_reports_composite_domains_criteria_unknowns_and_failures(tmp_path, monkeypatch, capsys):
    output = tmp_path / 'new-analysis'
    monkeypatch.setattr(sys, 'argv', ['analyze_release_evaluation.py', '--development-panel', str(PANEL),
                                     '--model-policy', str(POLICY), '--output-dir', str(output)])
    with pytest.raises(SystemExit) as exit:
        runpy.run_path(str(ROOT / 'scripts/analyze_release_evaluation.py'), run_name='__main__')
    assert exit.value.code == 1  # Intentional unknown controls cannot become a pass.
    assert json.loads(capsys.readouterr().out)['status'] == 'partial_unknown'
    report = json.loads((output / 'model-metrics.json').read_text())
    groups = {row['arm_id']: row for row in report['groups']}
    raw, full = groups['raw_model'], groups['production_full']
    assert report['synthetic_fixture_only'] and report['inference_executed'] is False
    assert report['planned_n'] == report['observed_n'] == 40
    assert report['reviewed_n'] == 30  # Failed rows have no fabricated semantic review.
    assert raw['primary']['score'] == pytest.approx(0.5)
    assert raw['failed'] == 10 and raw['missing'] == 0
    assert raw['fatal_failures_n'] == 1 and raw['safety_unknown_n'] == 10
    assert all(d['observed_complete_cluster_mean'] == pytest.approx(0.5)
               for d in raw['primary']['domains'].values())
    assert full['primary']['score'] is None
    assert full['primary']['fixed_denominator_bounds'] == pytest.approx([0.375, 0.875])
    unknown = [c for c in report['cells'] if c['status'] == 'completed'
               and c['dimension_status']['usefulness'] == 'unknown_labels']
    assert len(unknown) == 10 and all(c['safety_unknown'] for c in unknown)
    assert all(c['dimension_status']['tool_correctness'] == 'not_applicable' for c in report['cells'])
    reviews = json.loads((output / 'fixture-reviews.private.json').read_text())
    assert all(r['reviewer_type'] == 'synthetic_fixture' for r in reviews)
    assert reviews[0]['criterion_scores'] == {'USE': 1, 'CAL': 1, 'NUM': 1, 'ENT': 1, 'APP': 1}
    assert report['promotion_allowed'] is False and report['policy_preregistration_verified'] is False
    assert all(p['ranking_authorized'] is False and p['paired_scored_n'] == 0 for p in report['contrasts'])


def test_public_fixture_references_do_not_cross_the_real_worker_allowlist():
    suite = {'id': 'instrument', 'format': 'scenario', 'exposure': 'exposed_development'}
    for line in (PANEL / 'cases.jsonl').read_text().splitlines():
        case = normalize_case(json.loads(line), suite)
        assert 'reference_answer' in case
        assert 'reference_answer' not in worker_case(case)
        assert case['assertions'] == {} and case['review_required'] is True


def test_incomplete_domain_policy_refuses_before_writing_results(tmp_path):
    policy = json.loads(POLICY.read_text())
    policy['domain_weights'].pop('crop_quality')
    bad = tmp_path / 'missing-domain.json'
    bad.write_text(json.dumps(policy))
    output = tmp_path / 'refused'
    with pytest.raises(ValueError):
        analyze_development_panel(directory=PANEL, output_dir=output, policy_path=bad)
    assert not output.exists()


def test_source_tamper_refuses_before_writing_results(tmp_path):
    panel = tmp_path / 'changed-input'
    shutil.copytree(PANEL, panel)
    with (panel / 'cases.jsonl').open('a') as stream:
        stream.write('\n')
    output = tmp_path / 'refused'
    with pytest.raises(ValueError, match='source pin mismatch'):
        analyze_development_panel(directory=panel, output_dir=output, policy_path=POLICY)
    assert not output.exists()


def test_complete_synthetic_labels_still_grant_no_ranking_or_promotion(tmp_path):
    panel = tmp_path / 'complete-controls'
    shutil.copytree(PANEL, panel)
    fixtures = [json.loads(line) for line in (panel / 'deterministic-fixtures.jsonl').read_text().splitlines()]
    for fixture in fixtures:
        if fixture['arm_id'] == 'production_full':
            fixture['criterion_scores'] = {key: 0.75 for key in fixture['criterion_scores']}
            fixture['fatal_review_complete'] = True
    file = panel / 'deterministic-fixtures.jsonl'
    file.write_text(''.join(json.dumps(row) + '\n' for row in fixtures))
    handoff = json.loads((panel / 'handoff.json').read_text())
    handoff['files'][file.name] = {'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                 'size_bytes': file.stat().st_size}
    (panel / 'handoff.json').write_text(json.dumps(handoff))
    report = analyze_development_panel(directory=panel, output_dir=tmp_path / 'complete', policy_path=POLICY)
    assert report['status'] == 'descriptive_complete'
    groups = {row['arm_id']: row for row in report['groups']}
    assert groups['production_full']['primary']['score'] == pytest.approx(0.75)
    assert groups['raw_model']['fatal_failures_n'] == 1
    assert report['promotion_allowed'] is False
    assert all(pair['ranking_authorized'] is False for pair in report['contrasts'])


def test_failed_fixture_cannot_smuggle_a_semantic_grade(tmp_path):
    panel = tmp_path / 'invalid-failed-grade'
    shutil.copytree(PANEL, panel)
    file = panel / 'deterministic-fixtures.jsonl'
    fixtures = [json.loads(line) for line in file.read_text().splitlines()]
    failed = next(f for f in fixtures if f['status'] == 'failed')
    failed['criterion_scores']['NUM'] = 1
    file.write_text(''.join(json.dumps(row) + '\n' for row in fixtures))
    handoff = json.loads((panel / 'handoff.json').read_text())
    handoff['files'][file.name] = {'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                 'size_bytes': file.stat().st_size}
    (panel / 'handoff.json').write_text(json.dumps(handoff))
    output = tmp_path / 'refused'
    with pytest.raises(ValueError, match='noncompleted fixtures'):
        analyze_development_panel(directory=panel, output_dir=output, policy_path=POLICY)
    assert not output.exists()
