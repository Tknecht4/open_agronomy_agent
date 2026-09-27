from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from agronomy_agent import field_source_preparation as prep
from agronomy_agent.field_data import parse_table
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.field_data_store import _validate_mapping, commit_import, preview_import, query_import


@pytest.fixture
def pinned_source(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "records"
    book.active.append(["Trial", "Value", "Date", "Year", "Method", "Derived"])
    book.active.append(["A", 2, "2025-07-29", 2025, "SGS_Lab", "=1+1"])
    book.active.append(["A", ".", "2025-07-29", 2025, "SGS_Lab", 1])
    book.active.append(["A", -9999, "2025-07-29", 2025, "SGS_Lab", 2])
    book.active.append(["A", 1000, "2026-07-29", 2025, "SGS_Lab", 3])
    book.active.append(["B", "=1/0", "July 15 - 19", 2025, "Picketa_LENS", 4])
    book.active.append(["A", 4, "2025-07-29", 2025, "SGS_Lab", 5])
    book.create_sheet("dictionary").append(["literal metadata"])
    out = io.BytesIO()
    book.save(out)
    # A poisonous cached result must never be used, even when available.
    rewritten = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as original, zipfile.ZipFile(rewritten, "w") as target:
        for member in original.infolist():
            data = original.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<f>1/0</f><v></v>", b"<f>1/0</f><v>9999</v>")
            target.writestr(member, data)
    content = rewritten.getvalue()
    source = tmp_path / "raw"
    source.mkdir()
    (source / "input.tab").write_bytes(content)
    profile = dict(id="fixture", path="input.tab", sheet="records", group=["Trial", "Method"], context=["Trial", "Date", "Year", "Method"], measurements={"Value": "kg"}, dictionary="input.tab#dictionary", notes="Synthetic contract fixture", url="https://example.invalid", license="synthetic")
    monkeypatch.setattr(prep, "PINS", {"input.tab": hashlib.sha256(content).hexdigest()})
    monkeypatch.setattr(prep, "PROFILES", [profile])
    return source, content


def test_pinned_hash_mismatch_refuses_before_output(pinned_source, tmp_path):
    root, content = pinned_source
    (root / "input.tab").write_bytes(content+b"modified")
    with pytest.raises(ValueError, match="pinned SHA-256 mismatch"):
        prep.prepare_sources(root, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_dispositions_formulas_missingness_conflict_and_lineage(pinned_source, tmp_path):
    root, content = pinned_source
    index = prep.prepare_sources(root, tmp_path / "out")
    assert [g["row_count"] for g in index["groups"]] == [4, 1]
    manifest = json.loads((tmp_path / "out/fixture.manifest.json").read_text())
    assert manifest["disposition_counts"] == {"header": 2, "prepared": 5, "held": 1}
    held = [d for d in manifest["row_dispositions"] if d["disposition"] == "held"]
    assert held[0]["record"] == 5 and held[0]["reason"] == "date_year_conflict"
    assert held[0]["source_date"] == "2026-07-29"
    assert manifest["formula_cells_excluded"] == {"Derived": 1, "Value": 1}
    nulls = [n for d in manifest["row_dispositions"] for n in d.get("null_cells", [])]
    assert {n["raw"] for n in nulls} == {".", "-9999", None}
    assert all(n["value"] is None for n in nulls)
    assert manifest["source_columns"][4]["column_number"] == 2
    for group in index["groups"]:
        parsed = parse_table(group["csv"], (tmp_path / "out" / group["csv"]).read_bytes())
        mapping = json.loads((tmp_path / "out" / group["mapping"]).read_text())
        _validate_mapping(mapping, parsed)
        for row in parsed["rows"]:
            assert row["values"]["source_row"].startswith(f"sha256:{hashlib.sha256(content).hexdigest()}#records!record=")
            assert "=1/0" not in row["values"].values()
        if group["study_unit"].startswith("B"):
            assert parsed["rows"][0]["values"]["source_value"] == ""
            assert group["summaries"]["source_value"]["mean"] is None
            assert next(c for c in mapping["columns"] if c["column"] == "source_value")["evidence_role"] == "model_output"


def test_deterministic_new_outputs_and_no_overwrite(pinned_source, tmp_path):
    root, _ = pinned_source
    prep.prepare_sources(root, tmp_path / "one")
    prep.prepare_sources(root, tmp_path / "two")
    assert {p.name: p.read_bytes() for p in (tmp_path / "one").iterdir()} == {p.name: p.read_bytes() for p in (tmp_path / "two").iterdir()}
    with pytest.raises(ValueError, match="overwrites forbidden"):
        prep.prepare_sources(root, tmp_path / "one")


def test_mapping_commits_and_queries_through_existing_product_contract(pinned_source, tmp_path):
    root, _ = pinned_source
    output = tmp_path / "out"
    index = prep.prepare_sources(root, output)
    group = index["groups"][0]
    store = TraceStore(tmp_path / "store.sqlite3")
    try:
        field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner", payload={"display_name": "Source study A", "region_text": "Unknown geometry"})
        preview = preview_import(store, field, "owner", group["csv"], (output / group["csv"]).read_bytes())
        mapping = json.loads((output / group["mapping"]).read_text())
        result = commit_import(store, field, preview["import_id"], mapping)
        assert result["import"]["row_count"] == 4
        receipt = query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "source_value"})
        assert receipt["value"] == 3
        assert receipt["numeric_count"] == 2 and receipt["missing_count"] == 2
        assert group["raw_sha256"] in result["import"]["source"]["citation"]
        assert group["manifest_sha256"] in result["import"]["source"]["citation"]
    finally:
        store._conn.close()


def test_workbook_dimensions_are_bounded(pinned_source, monkeypatch, tmp_path):
    root, _ = pinned_source
    monkeypatch.setattr(prep, "MAX_ROWS", 2)
    with pytest.raises(ValueError, match="bounds"):
        prep.prepare_sources(root, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_acquired_sources_all_groups_and_counts(tmp_path):
    raw = Path(__file__).resolve().parents[1] / prep.RAW_DIRECTORY
    if not all((raw / name).exists() for name in prep.PINS):
        pytest.skip("Ignored acquired sources unavailable; synthetic adapter contracts still run")
    output = tmp_path / "prepared"
    index = prep.prepare_sources(raw, output)
    assert {s["source_id"]: s["group_count"] for s in index["sources"]} == {"bean": 4, "onion-grower": 36, "onion-trial-tissue": 4, "onion-trial-yield": 2, "soybean": 39}
    assert sum(g["row_count"] for g in index["groups"]) == 4008
    assert all(g["row_count"] == 484 for g in index["groups"] if g["source_id"] == "bean")
    for g in index["groups"]:
        data = (output / g["csv"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == g["csv_sha256"]
        _validate_mapping(json.loads((output / g["mapping"]).read_text()), parse_table(g["csv"], data))
    tissue = json.loads((output / "onion-trial-tissue.manifest.json").read_text())
    assert [(d["record"], d["reason"]) for d in tissue["row_dispositions"] if d["disposition"] == "held"] == [(100, "date_year_conflict")]
    soy = json.loads((output / "soybean.manifest.json").read_text())
    assert sum(soy["formula_cells_excluded"].values()) == 6183
    assert soy["disposition_counts"]["metadata_excluded"] == 81
    # Independent source-CSV mean, without reading adapter summary/CSV values.
    source_rows = list(csv.DictReader((raw / prep.ONION / "growerFieldOnion_2024And2025.tab").open()))
    group = next(g for g in index["groups"] if g["source_id"] == "onion-grower" and g["study_unit"] == "Davis_Onion | 2024 | SGS_Lab")
    values = [float(r["Nitrogen (%)"]) for r in source_rows if (r["Field"], r["Year"], r["Method"]) == ("Davis_Onion", "2024", "SGS_Lab")]
    assert group["summaries"]["source_nitrogen"]["mean"] == pytest.approx(sum(values)/len(values))
