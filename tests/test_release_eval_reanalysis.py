from __future__ import annotations

import json
import sys
import hashlib
from pathlib import Path

import pytest

from test_release_eval_diagnostic_inputs import closeout  # Shared synthetic sealed fixture.

from agronomy_agent.release_eval_analysis import summarize
from agronomy_agent.release_eval_reanalysis import reanalyze


@pytest.mark.parametrize("flag", [True, None])
def test_projection_preserves_recorded_length_with_legacy_missing_stats(flag):
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    from agronomy_agent.release_eval_model_metrics import termination_evidence
    cell = {"observation_id": "synthetic", "arm_id": "raw_model", "backend": "fixture"}
    plan = {"model": {"id": "fixture", "revision": "fixture-revision"}, "matrix": [cell]}
    original = {**cell, "finish_reason": "length", "truncated": flag, "turns": [{"answer": "Synthetic answer"}]}
    _, rows = _model_matrix({"plan": plan, "observations": [original]})
    assert rows[0]["finish_reason"] == "length"
    assert rows[0]["truncated"] is flag
    assert rows[0]["termination"]["status"] == "unknown"
    assert termination_evidence(rows[0])["truncated"] is True
    assert original["turns"] == [{"answer": "Synthetic answer"}]


@pytest.mark.parametrize("recorded,derived", [("stop", "length"), ("length", "stop")])
def test_projection_rejects_conflicting_known_terminals(recorded, derived):
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    cell = {"observation_id": "synthetic", "arm_id": "raw_model", "backend": "fixture"}
    plan = {"model": {"id": "fixture", "revision": "fixture-revision"}, "matrix": [cell]}
    row = {**cell, "finish_reason": recorded, "turns": [{"generation_stats": {"finish_reason": derived}}]}
    with pytest.raises(ValueError, match="contradictory recorded and derived"):
        _model_matrix({"plan": plan, "observations": [row]})


def test_projection_preserves_nested_only_length_and_actual_zero():
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    from agronomy_agent.release_eval_executor import observation_termination
    from agronomy_agent.release_eval_model_metrics import score_model_matrix
    from test_release_eval_model_metrics import packet
    plan, rows, rubrics, reviews, policy = packet()
    plan.update(model={"id": "fixture_model", "revision": "fixture_revision"})
    for cell in plan["matrix"]:
        cell["backend"] = "synthetic"
    for row in rows:
        row["termination"] = observation_termination([{"generation_stats": {"finish_reason": "stop"}}])
        row["turns"] = [{"answer": row["answer"]}]
    rows[0]["termination"] = observation_termination([{"generation_stats": {"finish_reason": "length"}}])
    frozen = json.loads(json.dumps(rows[0]))
    projected_plan, projected_rows = _model_matrix({"plan": plan, "observations": rows})
    assert projected_rows[0]["finish_reason"] == "length"
    assert projected_rows[0]["truncated"] is True
    assert projected_rows[0]["termination"] == frozen["termination"]
    assert projected_rows[0]["derived_termination"]["status"] == "unknown"
    policy["truncated_outcome"] = "zero"
    report = score_model_matrix(projected_plan, projected_rows, rubrics=rubrics, reviews=reviews, policy=policy)
    assert report["cells"][0]["penalty_zero"] is True
    assert report["groups"][0]["primary"]["score"] == pytest.approx(0.3)
    assert rows[0] == frozen


@pytest.mark.parametrize("recorded,derived", [("length", "stop"), ("stop", "length")])
def test_projection_rejects_nested_only_conflicting_known_terminal(recorded, derived):
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    from agronomy_agent.release_eval_executor import observation_termination
    cell = {"observation_id": "synthetic", "arm_id": "raw_model", "backend": "fixture"}
    plan = {"model": {"id": "fixture", "revision": "fixture-revision"}, "matrix": [cell]}
    row = {**cell, "termination": observation_termination([{"generation_stats": {"finish_reason": recorded}}]),
           "turns": [{"generation_stats": {"finish_reason": derived}}]}
    with pytest.raises(ValueError, match="contradictory recorded and derived"):
        _model_matrix({"plan": plan, "observations": [row]})


def test_projection_rejects_stage_conflict_even_when_both_aggregates_length():
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    from agronomy_agent.release_eval_executor import observation_termination
    cell = {"observation_id": "synthetic", "arm_id": "production_full", "backend": "fixture"}
    plan = {"model": {"id": "fixture", "revision": "fixture-revision"}, "matrix": [cell]}
    row = {**cell, "termination": observation_termination([{
        "generation_stats": {"finish_reason": "length"}, "editor_generation_stats": {"finish_reason": "stop"}}]),
        "turns": [{"generation_stats": {"finish_reason": "stop"}, "editor_generation_stats": {"finish_reason": "length"}}]}
    with pytest.raises(ValueError, match="terminal stage"):
        _model_matrix({"plan": plan, "observations": [row]})


def test_projection_keeps_derived_length_when_recorded_terminal_unknown():
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    from agronomy_agent.release_eval_executor import observation_termination
    from agronomy_agent.release_eval_model_metrics import score_model_matrix
    from test_release_eval_model_metrics import packet
    plan, rows, rubrics, reviews, policy = packet()
    plan.update(model={"id": "fixture_model", "revision": "fixture_revision"})
    for cell in plan["matrix"]:
        cell["backend"] = "synthetic"
    for row in rows:
        row["turns"] = [{"generation_stats": {"finish_reason": "stop"}}]
    unknown = observation_termination([{"generation_stats": {"generation_tokens": 2}}])
    rows[0]["termination"] = unknown
    rows[0]["turns"][0]["generation_stats"]["finish_reason"] = "length"
    projected_plan, projected_rows = _model_matrix({"plan": plan, "observations": rows})
    assert projected_rows[0]["finish_reason"] == "length" and projected_rows[0]["truncated"] is True
    assert projected_rows[0]["recorded_termination"] == unknown
    assert projected_rows[0]["derived_termination"]["status"] == "observed"
    policy["truncated_outcome"] = "zero"
    report = score_model_matrix(projected_plan, projected_rows, rubrics=rubrics, reviews=reviews, policy=policy)
    assert report["cells"][0]["penalty_zero"] is True
    assert report["groups"][0]["primary"]["score"] == pytest.approx(0.3)


@pytest.mark.parametrize("editor_output", ["Rejected synthetic output", ""])
def test_projection_actual_editor_attempt_cannot_remain_recorded_na(editor_output):
    from agronomy_agent.release_eval_reanalysis import _model_matrix
    from agronomy_agent.release_eval_executor import observation_termination
    from agronomy_agent.release_eval_model_metrics import score_model_matrix
    from test_release_eval_model_metrics import packet
    plan, rows, rubrics, reviews, policy = packet()
    plan.update(model={"id": "fixture_model", "revision": "fixture_revision"})
    for cell in plan["matrix"]:
        cell["backend"] = "synthetic"
    for row in rows:
        row["turns"] = [{"generation_stats": {"finish_reason": "stop"}}]
    rows[0]["termination"] = observation_termination(rows[0]["turns"])
    assert rows[0]["termination"]["stages"][1]["status"] == "not_applicable"
    rows[0]["turns"][0]["editor"] = {"editor_output": editor_output, "rewrite_accepted": False}
    projected_plan, projected_rows = _model_matrix({"plan": plan, "observations": rows})
    assert projected_rows[0]["recorded_termination"]["stages"][1]["status"] == "not_applicable"
    assert projected_rows[0]["termination"]["stages"][1]["required"] is True
    assert projected_rows[0]["termination"]["status"] == "unknown"
    policy["truncated_outcome"] = "zero"
    report = score_model_matrix(projected_plan, projected_rows, rubrics=rubrics, reviews=reviews, policy=policy)
    assert report["cells"][0]["termination_status"] == "unknown"
    assert report["groups"][0]["primary"]["score"] is None
from agronomy_agent.release_eval_runner import retention_manifest, verify_retention
from agronomy_agent.release_evaluation import (
    build_plan,
    digest,
    file_digest,
    load_registry,
    plan_identity,
    write_new_json,
)


def retained_run(tmp_path: Path, name: str = "raw") -> Path:
    directory = tmp_path / name
    directory.mkdir()
    plan = build_plan(load_registry(), profile="baseline", run_id=name)
    case = next(
        case
        for case in plan["cases"]
        if case["lane"] == "agronomy" and case["review_required"]
    )
    case = {**case, "reference_answer": "PRIVATE_GOLD_ANSWER"}
    cell = next(
        cell
        for cell in plan["matrix"]
        if cell["case_id"] == case["case_id"] and cell["suite_id"] == case["suite_id"]
    )
    plan.update(
        cases=[case],
        matrix=[cell],
        counts={"cases": 1, "observations": 1, "families": 1, "lanes": {"agronomy": 1}},
        environment={"performance_environment_sha256": "fixture"},
    )
    identity = plan_identity(plan)
    stages = {
        key: {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        for key, text in (
            ("draft", "PRIVATE_DRAFT"),
            ("post_verification", "PRIVATE_EDITOR"),
            ("final", "PRIVATE_FINAL_ANSWER"),
        )
    }
    observation = {
        **cell,
        "status": "completed",
        "review_required": True,
        "answer_sha256": digest("PRIVATE_FINAL_ANSWER"),
        "checks": [],
        "turns": [
            {
                "question": case["question"],
                "answer": "PRIVATE_FINAL_ANSWER",
                "answer_stages": stages,
            }
        ],
        "plan_sha256": identity,
    }
    observation["record_sha256"] = digest(observation)
    components = []
    for component in plan["required_components"]:
        row = {"component": component, "status": "pass", "plan_sha256": identity}
        row["record_sha256"] = digest(row)
        components.append(row)
    write_new_json(directory / "plan.json", plan)
    (directory / "observations.jsonl").write_text(json.dumps(observation) + "\n")
    (directory / "components.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in components)
    )
    report = summarize(plan, [observation], components, environment=plan["environment"])
    report.update(plan_sha256=identity, source_stable=True)
    write_new_json(directory / "report.json", report)
    write_new_json(directory / "retention.json", retention_manifest(directory))
    return directory


def review_for(raw: Path) -> dict:
    row = json.loads((raw / "observations.jsonl").read_text())
    return {
        key: row[key] for key in ("observation_id", "answer_sha256", "case_sha256")
    } | {
        "reviewer_id": "fixture-reviewer",
        "reviewer_type": "human_domain_reviewer",
        "rubric_sha256": "a" * 64,
        "required_complete": True,
        "material_error": False,
        "source_supported": True,
        "optional_usefulness": 0.5,
        "unnecessary_abstention": False,
    }


def test_offline_reanalysis_binds_reviews_and_never_runs_models(tmp_path, monkeypatch):
    import agronomy_agent.release_eval_runner as runner

    monkeypatch.setattr(
        runner,
        "run_suite",
        lambda **_: pytest.fail("reanalysis regenerated a model run"),
    )
    monkeypatch.setattr(
        runner, "execute_worker", lambda *_: pytest.fail("reanalysis invoked inference")
    )
    raw = retained_run(tmp_path)
    original = {path.name: file_digest(path) for path in raw.iterdir()}
    reviews = tmp_path / "reviews.jsonl"
    reviews.write_text(json.dumps(review_for(raw)) + "\n")
    out = tmp_path / "derived"
    report = reanalyze(
        run_dir=raw, output_dir=out, reviews_path=reviews, export_review_packet=True
    )
    assert report["domain_review_coverage"] == 1
    assert report["reanalysis"]["inference_executed"] is False
    assert {path.name: file_digest(path) for path in raw.iterdir()} == original
    lineage = json.loads((out / "lineage.json").read_text())
    assert lineage["raw_run"]["files"]["observations.jsonl"] == file_digest(
        raw / "observations.jsonl"
    )
    assert lineage["reviews"]["file_sha256"] == file_digest(reviews)
    assert lineage["analysis_source_sha256"] == digest(lineage["analysis_source"])
    assert (
        report["reanalysis"]["derived_analysis_sha256"]
        == lineage["analysis_source_sha256"]
    )
    frozen_plan = json.loads((raw / "plan.json").read_text())
    assert report.get("scorer_sha256") == frozen_plan.get("scorer_sha256")
    public = (out / "public-summary.json").read_text()
    assert (
        "PRIVATE_GOLD" not in public
        and "PRIVATE_FINAL" not in public
        and "PRIVATE_DRAFT" not in public
    )
    assert str(raw) not in public and "fixture-reviewer" not in public
    packet = json.loads((out / "review-packet.private.json").read_text())
    observed = packet["observations"][0]
    assert observed["answer_stages"]["draft"]["text"] == "PRIVATE_DRAFT"
    assert observed["answer_stages"]["post_verification"]["text"] == "PRIVATE_EDITOR"
    assert (
        observed["controller_only_reference"]["reference_answer"]
        == "PRIVATE_GOLD_ANSWER"
    )
    assert observed["review_example"]["required_complete"] is None
    assert (
        observed["review_example"]["stage_labels"]["draft"]["required_complete"] is None
    )
    assert (
        observed["review_example"]["stage_labels"]["draft"]["sha256"]
        == observed["answer_stages"]["draft"]["sha256"]
    )
    assert "stage_labels" not in packet["label_schema"]["required"]
    assert packet["label_schema"]["properties"]["optional_usefulness"]["maximum"] == 1
    verify_retention(raw)
    verify_retention(out)
    with pytest.raises(FileExistsError):
        reanalyze(run_dir=raw, output_dir=out)


def test_raw_tamper_and_review_hash_mismatch_reject_before_output(tmp_path):
    raw = retained_run(tmp_path)
    reviews = tmp_path / "reviews.jsonl"
    bad_review = review_for(raw) | {"answer_sha256": "wrong"}
    reviews.write_text(json.dumps(bad_review) + "\n")
    out = tmp_path / "derived"
    with pytest.raises(ValueError, match="binding"):
        reanalyze(run_dir=raw, output_dir=out, reviews_path=reviews)
    assert not out.exists()
    with (raw / "observations.jsonl").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        reanalyze(run_dir=raw, output_dir=out)
    assert not out.exists()


def test_reference_retention_and_lineage_are_bound(tmp_path):
    raw, reference = retained_run(tmp_path, "candidate"), retained_run(
        tmp_path, "reference"
    )
    out = tmp_path / "derived"
    report = reanalyze(
        run_dir=raw, output_dir=out, reference_path=reference / "report.json"
    )
    assert report["comparison"]["reference_run_id"] == "reference"
    lineage = json.loads((out / "lineage.json").read_text())
    assert lineage["reference_run"]["retention_sha256"] == file_digest(
        reference / "retention.json"
    )
    verify_retention(reference)
    with (reference / "report.json").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        reanalyze(
            run_dir=raw, output_dir=tmp_path / "another", reference_path=reference
        )


def test_reanalysis_cannot_write_inside_raw_or_reference(tmp_path):
    raw = retained_run(tmp_path)
    with pytest.raises(ValueError, match="immutable original"):
        reanalyze(run_dir=raw, output_dir=raw / "derived")
    assert not (raw / "derived").exists()


def test_sealed_ledger_and_final_answer_bindings_are_checked(tmp_path):
    raw = retained_run(tmp_path)
    path = raw / "observations.jsonl"
    row = json.loads(path.read_text())
    row["turns"][0]["answer"] = "changed"
    row["record_sha256"] = digest(
        {key: value for key, value in row.items() if key != "record_sha256"}
    )
    path.write_text(json.dumps(row) + "\n")
    (raw / "retention.json").unlink()
    write_new_json(raw / "retention.json", retention_manifest(raw))
    with pytest.raises(ValueError, match="final answer hash"):
        reanalyze(run_dir=raw, output_dir=tmp_path / "derived")


def test_cli_uses_retained_evidence_and_exports_private_packet(tmp_path):
    import subprocess

    raw = retained_run(tmp_path)
    out = tmp_path / "cli-derived"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[1]
                / "scripts/analyze_release_evaluation.py"
            ),
            "--run-dir",
            str(raw),
            "--output-dir",
            str(out),
            "--export-review-packet",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1, completed.stderr
    assert json.loads(completed.stdout)["status"] == "blocked"
    assert json.loads((out / "report.json").read_text())["failures"][
        "model_execution_missing"
    ]
    assert json.loads(completed.stdout)["inference_executed"] is False
    verify_retention(out)


def test_stage_hash_tamper_rejects_even_if_outer_ledger_is_resealed(tmp_path):
    raw = retained_run(tmp_path)
    path = raw / "observations.jsonl"
    row = json.loads(path.read_text())
    row["turns"][0]["answer_stages"]["draft"]["text"] = "changed draft"
    row["record_sha256"] = digest(
        {key: value for key, value in row.items() if key != "record_sha256"}
    )
    path.write_text(json.dumps(row) + "\n")
    (raw / "retention.json").unlink()
    write_new_json(raw / "retention.json", retention_manifest(raw))
    with pytest.raises(ValueError, match="answer-stage hash"):
        reanalyze(run_dir=raw, output_dir=tmp_path / "derived")


def test_review_packet_includes_review_required_harness_and_binds_stage_labels(
    tmp_path,
):
    from agronomy_agent.release_eval_analysis import bind_reviews
    from agronomy_agent.release_eval_reanalysis import read_completed_run, review_packet

    raw = retained_run(tmp_path)
    run = read_completed_run(raw)
    observation = run["observations"][0]
    observation["lane"] = "harness"
    observation["arm_id"] = "production_full"
    packet = review_packet(run)
    assert len(packet["observations"]) == 1
    assert packet["observations"][0]["lane"] == "harness"
    review = review_for(raw)
    review["stage_labels"] = packet["observations"][0]["review_example"]["stage_labels"]
    # Keep null final-stage judgments consistent with the supplied final labels.
    review["stage_labels"].pop("final")
    assert bind_reviews(run["observations"], [review])
    review["stage_labels"]["draft"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="stage label hash"):
        bind_reviews(run["observations"], [review])


def test_derived_review_reference_and_chained_reviews_bind_original_raw(
    tmp_path, monkeypatch
):
    from agronomy_agent.release_eval_reanalysis import load_reference_report
    import agronomy_agent.release_eval_runner as runner

    raw = retained_run(tmp_path)
    before = file_digest(raw / "retention.json")
    first_reviews = tmp_path / "first-reviews.jsonl"
    first_review = review_for(raw)
    first_reviews.write_text(json.dumps(first_review) + "\n")
    first = tmp_path / "first-analysis"
    reanalyze(run_dir=raw, output_dir=first, reviews_path=first_reviews)
    reference = load_reference_report(first / "report.json")
    assert reference["domain_review_coverage"] == 1
    assert reference["semantic_reviews"][0]["reviewer_id"] == "fixture-reviewer"
    # The production runner's lazy derived-reference entry uses the same validator.
    assert (
        runner.load_retained_report(first)["semantic_reviews"]
        == reference["semantic_reviews"]
    )
    monkeypatch.setattr(
        runner, "execute_worker", lambda *_: pytest.fail("chaining executed inference")
    )
    second_reviews = tmp_path / "second-reviews.jsonl"
    row = json.loads((raw / "observations.jsonl").read_text())
    second_review = first_review | {
        "stage_labels": {
            "draft": {
                "sha256": row["turns"][0]["answer_stages"]["draft"]["sha256"],
                "required_complete": False,
            }
        }
    }
    second_reviews.write_text(json.dumps(second_review) + "\n")
    second = tmp_path / "second-analysis"
    reanalyze(run_dir=first, output_dir=second, reviews_path=second_reviews)
    loaded = load_reference_report(second)
    assert loaded["semantic_reviews"][0]["required_complete"] is True
    assert (
        loaded["semantic_reviews"][0]["stage_labels"]["draft"]["required_complete"]
        is False
    )
    lineage = json.loads((second / "lineage.json").read_text())
    assert lineage["raw_run"]["directory"] == str(raw)
    assert lineage["parent_analysis"]["report_sha256"] == file_digest(
        first / "report.json"
    )
    assert file_digest(raw / "retention.json") == before
    assert not (second / "observations.jsonl").exists()
    candidate = tmp_path / "candidate-analysis"
    compared = reanalyze(
        run_dir=raw,
        output_dir=candidate,
        reviews_path=first_reviews,
        reference_path=second,
    )
    assert compared["comparison"]["reference_run_id"] == raw.name
    assert json.loads((candidate / "lineage.json").read_text())["reference_analysis"][
        "directory"
    ] == str(second)
    assert load_reference_report(candidate)["comparison"] == compared["comparison"]


def test_derived_reference_rejects_raw_missing_and_tampered_derived(tmp_path):
    from agronomy_agent.release_eval_reanalysis import load_reference_report

    raw = retained_run(tmp_path)
    derived = tmp_path / "derived"
    reanalyze(run_dir=raw, output_dir=derived)
    missing = tmp_path / "moved-raw"
    raw.rename(missing)
    with pytest.raises(FileNotFoundError):
        load_reference_report(derived)
    missing.rename(raw)
    with (derived / "report.json").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_reference_report(derived)


def test_derived_reference_rejects_resealed_raw_and_resealed_report_changes(tmp_path):
    from agronomy_agent.release_eval_reanalysis import load_reference_report

    raw = retained_run(tmp_path)
    derived = tmp_path / "derived"
    reanalyze(run_dir=raw, output_dir=derived)
    # Global byte tamper is rejected even if the individual root is resealed.
    with (raw / "report.json").open("a") as handle:
        handle.write("\n")
    (raw / "retention.json").unlink()
    write_new_json(raw / "retention.json", retention_manifest(raw))
    with pytest.raises(ValueError, match="binding mismatch"):
        load_reference_report(derived)
    raw2 = retained_run(tmp_path, "raw2")
    derived2 = tmp_path / "derived2"
    reanalyze(run_dir=raw2, output_dir=derived2)
    report_path = derived2 / "report.json"
    report = json.loads(report_path.read_text())
    report["domain_review_coverage"] = 1
    report_path.unlink()
    write_new_json(report_path, report)
    (derived2 / "retention.json").unlink()
    write_new_json(derived2 / "retention.json", retention_manifest(derived2))
    with pytest.raises(ValueError, match="controlled retained-evidence"):
        load_reference_report(derived2)


def test_diagnostic_analysis_preserves_unknowns_and_immutable_source(closeout, tmp_path):
    from agronomy_agent.release_eval_reanalysis import analyze_diagnostic_closeout

    pins = {path.name: file_digest(path) for path in closeout.iterdir()}
    output = tmp_path / "diagnostic-analysis"
    report = analyze_diagnostic_closeout(directory=closeout, output_dir=output)
    assert report["planned_n"] == report["observed_n"] == 6
    assert report["reviewed_n"] == 0
    assert report["status"] == "blocked_missing_policy"
    assert report["full_suite_executed"] is False
    assert report["current_JLens_executed"] is False
    assert report["promotion_allowed"] is False
    assert all(group["primary"] is None for group in report["groups"])
    assert all(pair["paired_scored_n"] == 0 for pair in report["contrasts"])
    assert "synthetic answer" not in json.dumps(report)
    assert pins == {path.name: file_digest(path) for path in closeout.iterdir()}
    verify_retention(output)
    with pytest.raises(FileExistsError):
        analyze_diagnostic_closeout(directory=closeout, output_dir=output)
    with pytest.raises(ValueError, match="outside immutable"):
        analyze_diagnostic_closeout(directory=closeout, output_dir=closeout / "analysis")


def test_optional_model_metrics_do_not_replace_release_scores(tmp_path):
    from agronomy_agent.release_eval_model_metrics import rubric_digest
    from agronomy_agent.release_eval_reanalysis import load_reference_report

    raw = retained_run(tmp_path)
    pins = {path.name: file_digest(path) for path in raw.iterdir()}
    original = reanalyze(run_dir=raw, output_dir=tmp_path / "ordinary")
    case = json.loads((raw / "plan.json").read_text())["cases"][0]
    rubric = {
        "case_id": case["case_id"], "case_sha256": case["case_sha256"],
        "domain_id": "synthetic", "cluster_id": "one", "answerability": "answerable",
        "review_status": "synthetic_qa", "fatal_conditions": [],
        "criteria": [{"criterion_id": "USE", "dimension": "usefulness",
                      "description": "Synthetic QA only", "weight": 1,
                      "applicable_arms": ["production_full"]}],
    }
    rubric["rubric_sha256"] = rubric_digest(rubric)
    labels = tmp_path / "rubric.jsonl"
    labels.write_text(json.dumps(rubric) + "\n")
    derived = tmp_path / "with-metrics"
    report = reanalyze(run_dir=raw, output_dir=derived, model_rubrics_path=labels)
    assert {k: v for k, v in report.items() if k != "reanalysis"} == {
        k: v for k, v in original.items() if k != "reanalysis"
    }
    metrics = json.loads((derived / "model-metrics.json").read_text())
    assert metrics["status"] == "blocked_missing_policy"
    assert metrics["reviewed_n"] == 0
    assert "PRIVATE_FINAL_ANSWER" not in json.dumps(metrics)
    assert (derived / "model-rubrics.private.jsonl").read_bytes() == labels.read_bytes()
    assert load_reference_report(derived) == report
    assert pins == {path.name: file_digest(path) for path in raw.iterdir()}


def test_duplicate_metric_input_refused_before_publishing(closeout, tmp_path):
    from agronomy_agent.release_eval_reanalysis import analyze_diagnostic_closeout

    labels = tmp_path / "ambiguous.jsonl"
    labels.write_text('{"case_id":"one","case_id":"two"}\n')
    output = tmp_path / "refused"
    with pytest.raises(ValueError, match="duplicate model metric"):
        analyze_diagnostic_closeout(directory=closeout, output_dir=output, rubrics_path=labels)
    assert not output.exists()


def test_model_projection_binds_frozen_config_and_preserves_timing_scope(tmp_path):
    from agronomy_agent.release_eval_reanalysis import _model_matrix, read_completed_run

    raw = retained_run(tmp_path)
    run = read_completed_run(raw)
    run["observations"][0]["turns"][-1]["generation_stats"] = {
        "model_load_ms": 1200, "time_to_first_token_ms": 200,
        "stream_time_to_first_token_ms": 150, "decode_ms": 300,
        "prompt_tokens": 10, "generation_tokens": 4, "generation_tps": 10,
    }
    original = json.loads(json.dumps(run["observations"]))
    plan, rows = _model_matrix(run)
    condition = plan["matrix"][0]["analysis_condition"]
    assert condition["model_config_sha256"] == run["plan"]["model"]["config_sha256"]
    assert condition["source_sha256"] == run["plan"]["source"]["source_sha256"]
    assert condition["arm_recipe_sha256"]
    assert rows[0]["observation_id"] == original[0]["observation_id"]
    assert rows[0]["case_sha256"] == original[0]["case_sha256"]
    assert rows[0]["answer_sha256"] == original[0]["answer_sha256"]
    assert rows[0]["performance"]["load_seconds"] == 1.2
    assert rows[0]["performance"]["ttft_seconds"] == 0.2
    assert rows[0]["performance"]["output_tokens"] == 4
    assert "prefill_seconds" not in rows[0]["performance"]
    assert rows[0].get("comparison_cohort") is None
    assert run["observations"] == original


def test_private_panel_fixture_binding_is_not_model_execution(tmp_path):
    from agronomy_agent.release_eval_model_metrics import OUTCOME_DIMENSIONS, rubric_digest
    from agronomy_agent.release_eval_reanalysis import analyze_development_panel
    from agronomy_agent.release_evaluation import worker_case

    panel = tmp_path / "panel"
    panel.mkdir()
    case = {"case_id": "QA-one", "scenario_family": "quantity-basis", "lane": "agronomy",
            "question": "What is 2 kg plus 3 kg?", "field_context": {}, "assertions": {},
            "review_required": True, "reference_answer": "PRIVATE_CONTROLLER_REFERENCE"}
    rubric = {"case_id": case["case_id"], "case_sha256": digest(case),
              "domain_id": "quantity", "cluster_id": "one", "answerability": "answerable",
              "review_status": "synthetic_qa", "fatal_conditions": [],
              "criteria": [{"criterion_id": dim, "dimension": dim, "description": "QA " + dim,
                            "weight": 1, "applicable_arms": ["production_full"]}
                           for dim in OUTCOME_DIMENSIONS]}
    rubric["rubric_sha256"] = rubric_digest(rubric)
    fixture = {"case_id": case["case_id"], "case_sha256": digest(case),
               "rubric_sha256": rubric["rubric_sha256"], "arm_id": "production_full",
               "fixture_id": "qa-fixture", "synthetic_fixture": True, "status": "completed",
               "answer": "5 kg", "answer_sha256": digest("5 kg"),
               "criterion_scores": {dim: 1 for dim in OUTCOME_DIMENSIONS},
               "fatal_failures": [], "fatal_review_complete": True}
    for name, value in (("cases", case), ("rubrics", rubric), ("deterministic-fixtures", fixture)):
        (panel / f"{name}.jsonl").write_text(json.dumps(value) + "\n")
    (panel / "numeric-oracles.jsonl").write_text("")
    (panel / "source-support.json").write_text("{}")
    (panel / "verify-panel.py").write_text("raise AssertionError('must never execute packet code')\n")
    handoff = {
        "schema_version": "open_agronomy_agent.agronomic_skill_panel_handoff.development.v1",
        "panel_id": "synthetic-qa", "primary_arms": ["production_full"],
        "files": {path.name: {"sha256": file_digest(path), "size_bytes": path.stat().st_size}
                  for path in panel.iterdir()},
    }
    write_new_json(panel / "handoff.json", handoff)
    report = analyze_development_panel(directory=panel, output_dir=tmp_path / "qa-analysis")
    assert report["synthetic_fixture_only"] is True
    assert report["inference_executed"] is False
    assert report["promotion_allowed"] is False
    assert report["planned_n"] == report["reviewed_n"] == 1
    assert report["status"] == "blocked_missing_policy"
    plan = json.loads((tmp_path / "qa-analysis/fixture-plan.private.json").read_text())
    assert "PRIVATE_CONTROLLER_REFERENCE" not in json.dumps(worker_case(plan["cases"][0]))
    assert "PRIVATE_CONTROLLER_REFERENCE" not in json.dumps(report)
    (panel / "cases.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="source pin mismatch"):
        analyze_development_panel(directory=panel, output_dir=tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
