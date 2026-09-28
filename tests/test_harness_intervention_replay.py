"""Offline stage-attribution diagnostics preserve source and missingness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agronomy_agent.harness_intervention_replay import (
    python_source_tree_identity,
    replay_files,
    replay_trace,
)
from scripts.replay_harness_interventions import main


def _stage(text: str) -> dict[str, str]:
    return {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def _row() -> dict:
    return {
        "question": "What should I check?",
        "model_id": "fixture-model",
        "run_identity_sha256": "a" * 64,
        "metadata": {
            "answer_stages": {
                "schema_version": "open_agronomy_agent.answer_stages.v1",
                "draft": _stage("Check the soil test."),
                "post_verification": _stage("Check the soil test."),
                "final": _stage("Check the soil test first."),
            },
            "answer_verification": {
                "triggered": False,
                "fallback_applied": False,
                "draft_output": "Check the soil test.",
                "editor_output": None,
            },
            "route": {"question_type": "field", "risk_level": "low"},
        },
    }


def test_unchanged_draft_attribution_and_missing_shadow_evidence() -> None:
    receipt = replay_trace(_row(), source_sha256="b" * 64, row_number=1)
    assert receipt["transitions"]["draft_to_post_verification"] == {
        "status": "observed", "changed": False,
        "inserted": 0, "deleted": 0, "replaced_before": 0, "replaced_after": 0,
    }
    assert receipt["transitions"]["post_verification_to_final"]["changed"] is True
    assert receipt["verifier_draft_echo"] == "matches_stage"
    assert receipt["shadow_claim_risk"]["status"] == "unavailable"
    assert "input_path" not in receipt["source"]
    assert "Check the soil" not in json.dumps(receipt)


def test_missing_stage_is_unknown_not_unchanged() -> None:
    row = _row()
    del row["metadata"]["answer_stages"]["post_verification"]
    receipt = replay_trace(row, source_sha256="b" * 64, row_number=1)
    assert receipt["stages"]["post_verification"] == {
        "status": "unavailable", "reason": "stage_missing",
    }
    assert receipt["transitions"]["draft_to_post_verification"]["status"] == "unavailable"
    assert receipt["transitions"]["post_verification_to_final"]["status"] == "unavailable"


def test_shadow_risk_uses_same_captured_question_and_evidence() -> None:
    row = _row()
    row["metadata"]["answer_verification"]["evidence"] = "A recent soil test is available."
    row["metadata"]["answer_verification"]["editor_output"] = "Check the soil test first."
    receipt = replay_trace(row, source_sha256="b" * 64, row_number=1)
    shadow = receipt["shadow_claim_risk"]
    assert shadow["status"] == "shadow_diagnostic"
    assert shadow["input_identity"]["captured_verifier_evidence_sha256"] == hashlib.sha256(
        b"A recent soil test is available."
    ).hexdigest()
    assert shadow["assessments"]["draft"] == shadow["assessments"]["post_verification"]
    assert shadow["assessments"]["editor_candidate"]["status"] == "shadow_diagnostic"
    assert receipt["transitions"]["draft_to_editor_candidate"]["changed"] is True


def test_file_receipt_hash_and_cli_refuses_overwrite(tmp_path: Path, capsys) -> None:
    source = tmp_path / "private-traces.jsonl"
    source.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    receipt = replay_files([source])
    assert receipt["observations"][0]["source"]["input_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    assert receipt["current_implementation"]["source_tree"]["sha256"]
    assert receipt["current_implementation"]["historical_assessor_equivalence"] == "unavailable"
    output = tmp_path / "receipt.json"
    assert main(["--input", str(source), "--output", str(output)]) == 0
    assert str(source) not in output.read_text()
    assert str(source) not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--input", str(source), "--output", str(output)])


def test_source_identity_changes_with_relative_path_or_file_bytes(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    source = package / "risk.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    first = python_source_tree_identity(package)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    second = python_source_tree_identity(package)
    assert first["sha256"] != second["sha256"]
    (package / "risk.py").rename(package / "assessor.py")
    third = python_source_tree_identity(package)
    assert second["sha256"] != third["sha256"]


def test_unsupported_schema_and_bad_hash_fail_closed() -> None:
    row = _row()
    row["metadata"]["answer_stages"]["schema_version"] = "other"
    with pytest.raises(ValueError, match="unsupported"):
        replay_trace(row, source_sha256="b" * 64, row_number=1)
    row = _row()
    row["metadata"]["answer_stages"]["draft"]["text"] += "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_trace(row, source_sha256="b" * 64, row_number=1)


def test_observed_rehearsal_wrapper_and_stage_disagreement() -> None:
    sample = _row()
    stages = sample["metadata"]["answer_stages"]
    wrapped = {
        "result_class": "observed_system_execution_nonclaim",
        "execution": {
            "turn_id": "turn-1",
            "answer_stages": stages,
            "turn": {
                "user_message": sample["question"],
                "trace": {
                    "metadata": sample["metadata"],
                    "route": sample["metadata"]["route"],
                    "prompt_messages": [{"role": "user", "content": sample["question"]}],
                },
            },
        },
    }
    receipt = replay_trace(wrapped, source_sha256="b" * 64, row_number=1)
    assert receipt["source"]["turn_id"] == "turn-1"
    assert receipt["source"]["result_class"] == "observed_system_execution_nonclaim"
    assert receipt["source"]["prompt_messages_sha256"] is not None
    wrapped["execution"]["answer_stages"] = {**stages, "draft": _stage("Different draft")}
    with pytest.raises(ValueError, match="disagree"):
        replay_trace(wrapped, source_sha256="b" * 64, row_number=1)
