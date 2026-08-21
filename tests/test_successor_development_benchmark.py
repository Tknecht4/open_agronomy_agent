"""Regression checks for the exposed successor-corpus development suite."""

from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.benchmark_contract import validate_benchmark


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/open_agronomy_successor_development.json"
SUITE = ROOT / "data/eval/open_agronomy_successor_development.jsonl"


def _rows() -> list[dict[str, object]]:
    return [json.loads(line) for line in SUITE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_successor_development_contract_rebuilds_and_is_nonclaim() -> None:
    manifest = validate_benchmark(ROOT, CONTRACT)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert manifest["rows"] == 256
    assert manifest["lane_counts"]["successor_retrieval_lineage"] == 15
    assert contract["claim_eligible"] is False
    assert contract["rag_config"] == "configs/rag.yaml"
    assert "RC3 remains frozen" in contract["evaluation_policy"]["claim_boundary"]


def test_successor_extension_covers_us_context_and_authority_boundaries() -> None:
    rows = _rows()
    extension = [row for row in rows if row["benchmark_lane"] == "successor_retrieval_lineage"]
    us_rows = [row for row in extension if row["task_family"] == "source_grounded_retrieval"]

    assert len(us_rows) == 12
    assert {row["field_context"]["region_text"] for row in us_rows} == {
        f"MLRA {value}" for value in ("001X", "002X", "003X", "004A", "005X", "006X", "007X", "008X", "009X", "010X", "011X", "012X")
    }
    assert all(row["preferred_source_ids"] == ["nrcs_edit_ecological_site_description_json"] for row in us_rows)
    assert all("cannot establish Canadian" in row["source_use_boundary"] for row in us_rows)

    boundary = next(row for row in extension if row["source_eval_id"] == "canadian_authority_negative")
    assert boundary["forbidden_source_ids"] == ["nrcs_edit_ecological_site_description_json"]
    assert boundary["wrong_jurisdiction_policy"] == "block_us_analogue_for_canadian_decisive_request"
    assert all(row["source_eval_id"] != "spatial_context_blocked" for row in extension)
