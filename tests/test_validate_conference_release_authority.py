from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts/validate_conference_release_authority.py"
    spec = importlib.util.spec_from_file_location(
        "validate_conference_release_authority", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_file_record_checks_hash_and_safe_path(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}\n", encoding="utf-8")
    failures: list[str] = []
    path = module.validate_file_record(
        {
            "path": "artifact.json",
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        },
        label="artifact",
        failures=failures,
    )
    assert path == artifact
    assert failures == []

    module.validate_file_record(
        {"path": "../escape", "sha256": "bad"},
        label="escape",
        failures=failures,
    )
    assert any("unsafe" in failure for failure in failures)


def test_benchmark_database_gate_counts_models_arms_and_rows(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    database = tmp_path / "benchmark.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE benchmark_run (
              run_id TEXT PRIMARY KEY,
              model_key TEXT NOT NULL,
              mode TEXT NOT NULL,
              is_canonical INTEGER NOT NULL,
              row_count INTEGER NOT NULL,
              run_identity_json TEXT NOT NULL
            );
            CREATE TABLE response (
              response_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL REFERENCES benchmark_run(run_id),
              output TEXT NOT NULL,
              exact_messages_json TEXT NOT NULL
            );
            CREATE TABLE judge_assessment (response_id TEXT NOT NULL);
            CREATE TABLE semantic_judgment (response_id TEXT NOT NULL);
            INSERT INTO benchmark_run VALUES
              ('r1', 'm1', 'raw_model', 1, 1, '{"suite_sha256":"suite","implementation":{"sha256":"implementation"}}');
            INSERT INTO benchmark_run VALUES
              ('r2', 'm1', 'agronomic_rag', 1, 1, '{"suite_sha256":"suite","implementation":{"sha256":"implementation"}}');
            INSERT INTO response VALUES ('a', 'r1', 'answer a', '[{"role":"user"}]');
            INSERT INTO response VALUES ('b', 'r2', 'answer b', '[{"role":"user"}]');
            INSERT INTO judge_assessment VALUES ('a');
            INSERT INTO judge_assessment VALUES ('b');
            INSERT INTO semantic_judgment VALUES ('a');
            INSERT INTO semantic_judgment VALUES ('b');
            """
        )
    failures: list[str] = []
    report = module.validate_benchmark_database(
        {
            "path": "benchmark.sqlite3",
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "expected_response_count": 2,
            "expected_canonical_run_count": 2,
            "expected_model_count": 1,
            "expected_arm_count": 2,
            "expected_case_count": 1,
            "expected_judge_assessment_count": 2,
            "expected_semantic_judgment_count": 2,
        },
        label="benchmark",
        failures=failures,
        expected_suite_sha256="suite",
    )
    assert failures == []
    assert report["integrity_check"] == "ok"
    assert report["response_count"] == 2
    assert report["judge_assessment_count"] == 2
    assert report["suite_sha256_values"] == ["suite"]
    assert report["implementation_sha256_values"] == ["implementation"]
