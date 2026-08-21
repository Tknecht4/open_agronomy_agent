from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs/public/development-benchmark-rc3-20260815"
SCRIPT = CHECKPOINT / "scripts/analyze_rc3_checkpoint.py"


def _module():
    spec = importlib.util.spec_from_file_location("analyze_rc3_checkpoint", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def test_published_checkpoint_verifies_without_private_benchmark_outputs() -> None:
    result = _module()._verify_published(CHECKPOINT)

    assert result["status"] == "verified"
    assert result["canonical_observations"] == 8_676
    assert result["semantic_judgments"] == 0
    assert result["posthoc_semantic_review_rows"] == 1_620


def test_public_response_projection_is_answer_free_and_score_typed() -> None:
    path = CHECKPOINT / "source_data/public_safe_response_measurements.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 8_676
    assert not {"answer", "response", "prompt", "question", "messages"}.intersection(
        rows[0]
    )
    assert sum(bool(row["objective_accuracy"]) for row in rows) == 576
    assert sum(bool(row["deterministic_diagnostic_score"]) for row in rows) == 1_188
    assert all(
        not row["objective_accuracy"]
        or row["benchmark_lane"] == "objective_agronomic_calculation"
        for row in rows
    )
    assert all(
        not row["deterministic_diagnostic_score"]
        or row["benchmark_lane"] == "official_source_answer_boundary"
        for row in rows
    )


def test_checkpoint_receipt_preserves_nonclaim_and_frozen_run_identity() -> None:
    receipt = json.loads(
        (CHECKPOINT / "source_data/checkpoint_validation_receipt.json").read_text(
            encoding="utf-8"
        )
    )

    assert receipt["status"] == "complete_nonclaim_development_checkpoint"
    assert receipt["claim_eligible"] is False
    assert receipt["suite_exposure_status"] == "exposed_and_used_for_system_tuning"
    assert receipt["canonical_trials"] == 9
    assert receipt["canonical_arm_executions"] == 36
    assert receipt["canonical_observations"] == 8_676
    assert receipt["semantic_judgments"] == 0
    assert receipt["automated_semantic_judge_requested"] is False
    posthoc = receipt["posthoc_semantic_review"]
    assert posthoc["rows"] == 1_620
    assert posthoc["promotion_eligible"] is False
    assert posthoc["human_calibration_status"] == "missing"
    assert receipt["independent_human_reviews_completed"] == 0
    assert receipt["final_partial_identical_arms"] == 36
    assert receipt["review_packets"] == 9
    assert receipt["review_packet_rows"] == 1_620
    assert receipt["review_rows_completed"] == 0
    assert receipt["implementation_commit"] == "3e30fb5de38105fa5bba3845411eb2174c21d3c4"


def test_checkpoint_paper_and_vector_figures_are_present() -> None:
    paper = CHECKPOINT / "paper.pdf"
    assert paper.read_bytes().startswith(b"%PDF-")
    assert paper.stat().st_size > 100_000

    figures = sorted((CHECKPOINT / "figures").glob("*.svg"))
    assert len(figures) == 5
    for figure in figures:
        text = figure.read_text(encoding="utf-8")
        assert "<svg" in text
        assert "<script" not in text.lower()

    instructions = (CHECKPOINT / "README.md").read_text(encoding="utf-8")
    assert "tectonic main.tex\nmv main.pdf paper.pdf" in instructions


def test_posthoc_semantic_projection_is_aggregate_only_and_explicitly_uncalibrated() -> None:
    path = CHECKPOINT / "source_data/posthoc_semantic_review_summary.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert {row["source_label"] for row in rows} == {"model_only", "full_system"}
    assert all(int(row["responses"]) == 270 and int(row["cases"]) == 90 for row in rows)
    assert all(0 <= float(row["semantic_score_mean_0_to_100"]) <= 100 for row in rows)
    assert not {"answer", "question", "rationale", "review_id"}.intersection(rows[0])
    controls = json.loads((CHECKPOINT / "source_data/posthoc_semantic_review_quality_controls.json").read_text(encoding="utf-8"))
    assert controls["rows"] == 1_620
    assert controls["promotion_eligible"] is False
    assert controls["human_calibration_status"] == "missing"


def test_published_verifier_rejects_an_unlisted_package_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "PUBLISHED_FILES", ("README.md",))
    (tmp_path / "README.md").write_text("bounded fixture\n", encoding="utf-8")
    module._finalize_package(tmp_path)
    (tmp_path / "unexpected-private-output.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="published package inventory mismatch"):
        module._verify_published(tmp_path)


def test_public_measurement_validator_rejects_duplicate_observation_identity() -> None:
    module = _module()
    path = CHECKPOINT / "source_data/public_safe_response_measurements.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    rows[1]["observation_id"] = rows[0]["observation_id"]

    with pytest.raises(ValueError, match="observation identities"):
        module._validate_public_measurements(rows, fieldnames)
