"""Exposed pilot identity, leakage boundary, and failure-retaining replay."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from agronomy_agent import field_data_benchmark as benchmark

PILOT = Path(__file__).resolve().parents[1] / "data/eval/field_data_pilot_v1"


def test_manifest_fixtures_are_source_bound_and_gold_separate() -> None:
    manifest, cases = benchmark.load_pilot(PILOT)
    assert manifest["bundle_count"] == 24 and len(cases) == 96
    assert manifest["source_group_counts"] == {"akron": 12, "nitrate": 12}
    assert all(bundle["independent_farm_verified"] is False for bundle in manifest["bundles"])
    assert len({bundle["source_sha256"] for bundle in manifest["bundles"]}) == 2
    assert all(bundle["source_csv_records_with_header_1"] for bundle in manifest["bundles"])
    for bundle in manifest["bundles"]:
        fixture = PILOT / bundle["fixture_path"]
        with fixture.open(newline="", encoding="utf-8") as stream:
            assert len(list(csv.DictReader(stream))) == bundle["row_count"]
        assert bundle["source_row_lineage"] == [
            {"fixture_csv_record_with_header_1": fixture_row,
             "source_csv_record_with_header_1": source_row}
            for fixture_row, source_row in enumerate(bundle["source_csv_records_with_header_1"], start=2)
        ]
        assert bundle["license"] in {"CC0 1.0", "CC BY 4.0"}
        assert bundle["attribution"] and bundle["derivation"]
    runtime_manifest = (PILOT / "manifest.json").read_text()
    assert '"expected"' not in runtime_manifest
    assert '"question"' not in runtime_manifest
    assert all("expected" in case and "question" in case for case in cases)
    assert {case["score_layer"] for case in cases} == {"query", "query_only"}


def test_loader_rejects_tampered_fixture(tmp_path: Path) -> None:
    manifest, _ = benchmark.load_pilot(PILOT)
    (tmp_path / "manifest.json").write_bytes((PILOT / "manifest.json").read_bytes())
    (tmp_path / "gold_cases.jsonl").write_bytes((PILOT / "gold_cases.jsonl").read_bytes())
    (tmp_path / "fixtures").mkdir()
    for bundle in manifest["bundles"]:
        path = tmp_path / bundle["fixture_path"]
        path.write_bytes((PILOT / bundle["fixture_path"]).read_bytes())
    changed = tmp_path / manifest["bundles"][0]["fixture_path"]
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        benchmark.load_pilot(tmp_path)


def test_runner_retains_failures_and_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = benchmark.query_import
    seen = 0

    def fail_once(*args, **kwargs):
        nonlocal seen
        seen += 1
        if seen == 1:
            raise RuntimeError("injected query failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(benchmark, "query_import", fail_once)
    output = tmp_path / "run"
    summary = benchmark.run_pilot(PILOT, output, limit=2, product=False)
    rows = [json.loads(line) for line in (output / "cases.jsonl").read_text().splitlines()]
    assert summary["case_count"] == len(rows) == 2
    assert rows[0]["query_layer"]["status"] == "fail"
    assert rows[0]["query_layer"]["error"] == "injected query failure"
    assert rows[1]["query_layer"]["status"] == "pass"
    assert all(row["source_sha256"] and row["fixture_sha256"] for row in rows)
    with pytest.raises(ValueError, match="empty"):
        benchmark.run_pilot(PILOT, output, limit=1, product=False)


def test_query_only_missing_column_stays_explicit(tmp_path: Path) -> None:
    output = tmp_path / "run"
    summary = benchmark.run_pilot(PILOT, output, limit=4, product=False)
    rows = [json.loads(line) for line in (output / "cases.jsonl").read_text().splitlines()]
    assert summary["source_group_case_counts"]["akron"] == {"pass": 4}
    assert rows[-1]["score_layer"] == "query_only"
    assert rows[-1]["query_layer"]["error_type"] == "ValueError"
    assert rows[-1]["production_layer"]["status"] == "not_run"


def test_product_result_must_reach_final_answer(tmp_path: Path) -> None:
    output = tmp_path / "product"
    summary = benchmark.run_pilot(PILOT, output, limit=3, product=True)
    rows = [json.loads(line) for line in (output / "cases.jsonl").read_text().splitlines()]
    assert summary["runtime_code_stable"]
    assert summary["source_group_product_contract_counts"]["akron"] == {"pass": 3}
    assert all(row["production_layer"]["contract_score"]["result_id"] for row in rows)
    altered = rows[0]["production_layer"]
    score = benchmark._judge_product_contract(
        benchmark.load_pilot(PILOT)[1][0], rows[0]["query_layer"]["receipt"],
        "unbound replacement", altered["trace"], rows[0]["raw_layer"]["fixture_sha256"])
    assert score["status"] == "fail" and "answer_binding" in score["failed_checks"]
