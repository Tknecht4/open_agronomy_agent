from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from agronomy_agent.release_eval_analysis import summarize
from agronomy_agent.release_eval_reanalysis import reanalyze
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
            str(Path(__file__).resolve().parents[1] / ".venv/bin/python"),
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
