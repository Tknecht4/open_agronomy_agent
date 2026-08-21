from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from agronomy_agent.v3_competence_candidate import (
    build_bundle,
    explicit_regions,
    load_external_csv,
    project_external_rows,
    select_regional_cases,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "configs/open_agronomy_v3_competence_candidate.json").read_text())


def _csv(path: Path, rows: list[dict[str, str]]) -> dict[str, object]:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["question", "answer"])
        writer.writeheader()
        writer.writerows(rows)
    payload = path.read_bytes()
    return {
        "dataset_id": "fixture/agronomy",
        "revision": "fixture-revision",
        "columns": ["question", "answer"],
        "rows": len(rows),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_external_projection_keeps_every_row_and_never_infers_region(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    contract = _csv(
        path,
        [
            {"question": "Why does crop rotation help soil?", "answer": "It changes residue and pest cycles."},
            {"question": "What is the current herbicide rate in Alberta?", "answer": "Check the current label."},
        ],
    )
    rows = project_external_rows(load_external_csv(path, contract), contract)
    assert len(rows) == 2
    assert rows[0]["explicit_regions"] == []
    assert rows[0]["region_provenance"] == "none"
    assert rows[1]["explicit_regions"] == ["Alberta"]
    assert rows[1]["authority_sensitive"] is True
    assert {row["disposition"] for row in rows} == {
        "included_reference_grounded",
        "included_diagnostic_authority_sensitive",
    }


def test_external_contract_rejects_byte_drift(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    contract = _csv(path, [{"question": "What is loam?", "answer": "A soil texture class."}])
    path.write_text(path.read_text() + "drift", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        load_external_csv(path, contract)


def test_region_matching_requires_explicit_place_text() -> None:
    assert explicit_regions("How should canola residue be managed?") == []
    assert explicit_regions("How is residue handled in Saskatchewan?") == ["Saskatchewan"]


def test_regional_projection_has_frozen_language_quota() -> None:
    rows = select_regional_cases(
        ROOT / CONFIG["regional_source_suite"],
        strata=CONFIG["regional_strata"],
        priority_jurisdictions=CONFIG["regional_priority_jurisdictions"],
        count=CONFIG["regional_case_count"],
        french=CONFIG["regional_language_counts"]["French"],
    )
    assert len(rows) == 72
    assert sum(row.get("language") == "French" for row in rows) == 12
    assert len({row["eval_id"] for row in rows}) == 72
    assert all(row["claim_eligible"] is False for row in rows)
    assert all(row["source_eval_id"].startswith("oasdev::") for row in rows)
    assert {row["construct_stratum"] for row in rows} == set(CONFIG["regional_strata"])
    assert all(
        sum(row["construct_stratum"] == lane for row in rows) == quota
        for lane, quota in CONFIG["regional_strata"].items()
    )
    assert not {"field_history_lineage"} & {row["benchmark_lane"] for row in rows}
    assert {"Alberta", "Saskatchewan", "Manitoba", "Canada"} <= {
        region for row in rows for region in row["explicit_regions"]
    }


def test_build_bundle_records_duplicates_without_excluding_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    external_contract = _csv(
        source,
        [
            {"question": "Why does crop rotation help soil?", "answer": "It changes cycles."},
            {"question": "What is loam?", "answer": "A soil texture class."},
        ],
    )
    comparison = tmp_path / "comparison.jsonl"
    comparison.write_text(json.dumps({"eval_id": "old-1", "question": "Why does crop rotation help soil?"}) + "\n")
    config = {
        **CONFIG,
        "external_dataset": external_contract,
        "regional_case_count": 2,
        "regional_language_counts": {"English": 1, "French": 1},
        "regional_strata": {"canadian_decision_quality": 2},
    }
    manifest, external, regional = build_bundle(
        config=config,
        source_csv=source,
        regional_source=ROOT / CONFIG["regional_source_suite"],
        comparison_paths=[comparison],
    )
    assert len(external) == 2
    assert len(regional) == 2
    assert manifest["duplicate_audit"]["match_count"] == 1
    assert sum(manifest["external_dispositions"].values()) == 2
    assert manifest["sealed_v3_satisfied"] is False
