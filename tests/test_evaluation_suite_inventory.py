from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("suite_inventory", ROOT / "scripts/inventory_agronomy_evaluation_suites.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def test_nested_origins_external_questions_and_scenarios_are_separate():
    rows = [
        {"question": "What rate?", "origin": {"question_origin": "real_user_farmer_question_from_peer_reviewed_external_dataset", "source_url": "https://example.org/dataset"}, "scenario_id": "one"},
        {"question": "What rate?", "provenance": {"question_origin": "deidentified_grower_query"}, "scenario_id": "two"},
        {"question": "What rate?", "bundle_id": "field-a"},
        {"turns": [{"role": "user", "content": "First?"}, {"role": "assistant", "content": "Answer"}, {"role": "user", "content": "Then?"}], "bundle_id": "field-a"},
    ]
    result = inventory.summarize_suite(Path("fixture"), rows)
    assert result["rows"] == 4
    assert result["question_text_count"] == 5
    assert result["unique_questions"] == 3
    assert result["scenario_identity_count"] == 2
    assert result["field_bundle_count"] == 1
    assert result["external_farmer_question_rows"] == 1
    assert result["traceable_real_user_rows"] == 1
    assert result["target_user_validation_established"] is False
    assert result["external_usefulness_claim_eligible"] is False


def test_inventory_deduplicates_file_paths_and_reports_actual_origin_boundary(tmp_path):
    path = tmp_path / "suite.jsonl"
    path.write_text(json.dumps({"question": "What rate?", "question_origin": "real_user_farmer_question_from_peer_reviewed_external_dataset", "source_url": "https://example.org"}) + "\n")
    result = inventory.build_inventory([path, path])
    assert result["suite_files"] == 1
    assert result["external_farmer_question_rows"] == 1
    assert "No row carries" not in result["boundary"]
    assert "target users" in result["boundary"]


def test_nested_metadata_origin_is_preserved_but_scenario_kind_is_not_origin():
    assert inventory._origin({"metadata": {"origin": {"type": "farmer_survey"}}}) == "farmer_survey"
    assert inventory._traceable({"metadata": {"origin": {"type": "farmer_survey", "source_record_id": "survey-1"}}}) is True
    assert inventory._origin({"kind": "transfer", "question": "Question?"}) == "missing"
    texts = inventory._question_texts({"question": "Final?", "turns": [{"question": "First?"}, {"question": "Final?"}]})
    assert texts == ["First?", "Final?"]
