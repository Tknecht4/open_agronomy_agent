from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def test_execution_catalog_separates_product_historical_and_protocol_paths():
    from agronomy_agent.release_evaluation import evaluation_entrypoints

    report = evaluation_entrypoints()
    surfaces = {row["id"]: row for row in report["surfaces"]}
    assert report["inference_executed"] is False
    assert not any(row["missing_paths"] for row in surfaces.values())
    assert surfaces["release_suite"]["classification"] == "implemented_wired"
    assert surfaces["historical_four_arm"]["classification"] == "preserved_historical_only"
    assert surfaces["benchmark_v2"]["execution_contract"] == "deterministic_contract_qa"
    assert "production adapter" in surfaces["benchmark_v2"]["boundary"]
    assert surfaces["competence_v3"]["execution_contract"] == "explicit_executor_binding_required"
    assert all(not row["model_evidence_established"] for row in surfaces.values())
    assert all(not row["tests_executed_by_inventory"] for row in surfaces.values())


def test_absent_declared_sources_are_blocked_not_reported_complete(tmp_path):
    from agronomy_agent.release_evaluation import evaluation_entrypoints

    report = evaluation_entrypoints(root=tmp_path)
    assert all(row["classification"] == "blocked_missing_declared_input" for row in report["surfaces"])
    assert all(row["source_files"] == {} and row["missing_paths"] for row in report["surfaces"])


def test_canonical_inventory_does_not_import_inference_or_reanalysis(monkeypatch, capsys):
    import builtins

    spec = importlib.util.spec_from_file_location("canonical_analysis", ROOT / "scripts/analyze_release_evaluation.py")
    module = importlib.util.module_from_spec(spec)
    original_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        assert name not in {"agronomy_agent.release_eval_reanalysis", "mlx", "mlx.core", "torch"}
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", ["analyze_release_evaluation.py", "--inventory"])
    assert module.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["canonical_analysis"] == "scripts/analyze_release_evaluation.py"


def test_inventory_rejects_overwriting_a_retained_record(tmp_path):
    retained = tmp_path / "inventory.json"
    retained.write_text("original retained record")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/inventory_agronomy_evaluation_suites.py"),
         "--root", str(tmp_path), "--output", str(retained)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "preserve previous inventories" in result.stderr
    assert retained.read_text() == "original retained record"


def test_app_benchmark_metadata_routes_to_current_suite_and_labels_history():
    from agronomy_agent.server.services.benchmark_service import open_agronomy_benchmark_summary

    report = open_agronomy_benchmark_summary()
    assert report["claim_eligible"] is False
    assert report["execution_contract"] == "historical_legacy_agent_path"
    assert "run_release_evaluation.py" in report["canonical_command"]
    assert "--dry-run" in report["canonical_command"]
    assert "run_open_agronomy_benchmark.py" in report["historical_command"]
    assert report["external_diagnostic"]["execution_contract"] == "historical_legacy_agent_path"
