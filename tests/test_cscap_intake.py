from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from agronomy_agent.cscap_intake import DEFAULT_CONTRACT, prepare_cscap_intake
from agronomy_agent.field_data import parse_table
from agronomy_agent.paths import repo_path
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.field_data_store import commit_import, preview_import, query_import


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def source(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    contract = json.loads(repo_path(DEFAULT_CONTRACT).read_text())
    contract["selection"].update(years=[2011, 2012], expected_plot_count=2, expected_record_count=4, expected_records_per_year=2)
    book = openpyxl.Workbook()
    plots = book.active
    plots.title = "Plot Identifiers"
    plots.append(["uniqueid", "plotid", "rep", "tillage", "rotation", "2011crop", "2012crop"])
    plots.append(["description"])
    plots.append(["units"])
    plots.append(["ARL", "101", "1", "TIL1", "ROT4", "Corn", "Soybean"])
    plots.append(["ARL", "104", "2", "TIL1", "ROT4", "Corn", "Soybean"])
    plots.append(["OTHER", "101", "1", "TIL2", "ROT5", "Corn", "Corn"])
    agro = book.create_sheet("Agronomic")
    agro.append(["uniqueid", "plotid", "year", "AGR17", "AGR19", "AGR21"])
    agro.append(["description", None, None, *[spec["description"] for spec in contract["yield_columns"].values()]])
    agro.append(["units", None, None, "kg ha-1", "kg ha-1", "kg ha-1"])
    agro.append(["ARL", "101", 2011, 0, " ", None])
    agro.append(["ARL", "104", 2011, 200, None, " "])
    agro.append(["ARL", "101", 2012, None, 300, None])
    agro.append(["ARL", "104", 2012, None, " ", None])
    agro.append(["OTHER", "101", 2011, 99999, None, None])
    # Unselected sheets are never parsed or converted into runtime evidence.
    book.create_sheet("Field Operations").append(["=1/0", "Do not invent a plot join"])
    raw = tmp_path / "raw"
    raw.mkdir()
    article = {"id": contract["article_id"], "version": contract["article_version"], "doi": contract["doi"],
               "license": {"name": "CC0", "url": contract["rights"]["licence_url"]}, "files": []}
    contract_path = tmp_path / "contract.json"

    def save():
        buffer = io.BytesIO()
        book.save(buffer)
        content = buffer.getvalue()
        item = contract["source_files"]["workbook"]
        item.update(bytes=len(content), sha256=_sha(content), publisher_md5=hashlib.md5(content).hexdigest())
        (raw / item["name"]).write_bytes(content)
        article["files"] = [{"id": item["publisher_file_id"], "size": len(content), "is_link_only": False, "supplied_md5": item["publisher_md5"]}]
        article_content = (json.dumps(article) + "\n").encode()
        contract["source_files"]["article"].update(bytes=len(article_content), sha256=_sha(article_content))
        (raw / contract["source_files"]["article"]["name"]).write_bytes(article_content)
        contract_path.write_text(json.dumps(contract))
        return content

    save()
    return raw, contract_path, contract, book, article, save


def test_pinned_source_drift_refuses_before_output(source, tmp_path):
    raw, contract_path, contract, _, _, _ = source
    workbook = raw / contract["source_files"]["workbook"]["name"]
    changed = bytearray(workbook.read_bytes())
    changed[-1] ^= 1
    workbook.write_bytes(changed)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        prepare_cscap_intake(raw, tmp_path / "out", contract_path=contract_path)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("failure", ["unit", "formula", "duplicate", "missing_plot", "wrong_crop", "negative_yield", "year", "plot_count", "rights", "admission"])
def test_semantic_or_admission_conflicts_fail_closed(source, tmp_path, failure):
    raw, contract_path, contract, book, article, save = source
    if failure == "unit":
        book["Agronomic"]["D3"] = "bu/acre"
    elif failure == "formula":
        book["Agronomic"]["D4"] = "=1+1"
    elif failure == "duplicate":
        book["Agronomic"]["B5"] = "101"
    elif failure == "missing_plot":
        book["Agronomic"]["B4"] = "404"
    elif failure == "wrong_crop":
        book["Agronomic"]["E4"] = 100
    elif failure == "negative_yield":
        book["Agronomic"]["D4"] = -9999
    elif failure == "year":
        book["Agronomic"]["C4"] = 2026
    elif failure == "plot_count":
        contract["selection"]["expected_plot_count"] = 3
    elif failure == "rights":
        article["license"]["name"] = "permission_required"
    else:
        contract["admission"]["runtime_rag"] = True
    save()
    with pytest.raises(ValueError):
        prepare_cscap_intake(raw, tmp_path / "out", contract_path=contract_path)
    assert not (tmp_path / "out").exists()


def test_deterministic_native_projection_preserves_zero_missingness_and_provenance(source, tmp_path):
    raw, contract_path, contract, _, _, _ = source
    first = prepare_cscap_intake(raw, tmp_path / "one", contract_path=contract_path)
    prepare_cscap_intake(raw, tmp_path / "two", contract_path=contract_path)
    assert {path.name: path.read_bytes() for path in (tmp_path / "one").iterdir()} == {path.name: path.read_bytes() for path in (tmp_path / "two").iterdir()}
    assert first["row_count"] == 4 and first["plot_count"] == 2
    assert first["numeric_counts"] == {"corn_yield_kg_ha": 2, "soybean_yield_kg_ha": 1, "wheat_yield_kg_ha": 0}
    assert first["runtime_rag_chunks"] == 0
    assert first["admission"] == contract["admission"]
    assert first["source_columns"]["Agronomic"]["AGR17"] == 4
    assert first["definition_rows"] == {"descriptions": 2, "units": 3}
    parsed = parse_table("cscap-arl.csv", (tmp_path / "one/cscap-arl.csv").read_bytes())
    rows = [row["values"] for row in parsed["rows"]]
    assert rows[0]["corn_yield_kg_ha"] == "0"
    assert rows[0]["soybean_yield_kg_ha"] == ""
    assert rows[-1]["soybean_yield_kg_ha"] == ""
    assert all(row["study_site"] == "ARL" for row in rows)
    assert all(row["source_row"].startswith(f"sha256:{first['raw_sha256']}#Agronomic!row=") for row in rows)
    assert rows[0]["plot_source_row"].endswith("Plot Identifiers!row=4")
    assert first["row_dispositions"][0]["null_cells"][0] == {"column": "AGR19", "raw": " ", "value": None}
    with pytest.raises(FileExistsError, match="overwrites forbidden"):
        prepare_cscap_intake(raw, tmp_path / "one", contract_path=contract_path)


def test_source_native_rows_are_queryable_through_existing_product_import(source, tmp_path):
    raw, contract_path, _, _, _, _ = source
    output = tmp_path / "prepared"
    receipt = prepare_cscap_intake(raw, output, contract_path=contract_path)
    mapping = json.loads((output / "cscap-arl-101.mapping.json").read_text())
    store = TraceStore(tmp_path / "source-study.sqlite3")
    try:
        field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
                                                payload={"display_name": "CSCAP ARL archival research study", "region_text": "Wisconsin research site; no farmer-field identity or geometry"})
        preview = preview_import(store, field, "owner", "cscap-arl.csv", (output / "cscap-arl.csv").read_bytes())
        committed = commit_import(store, field, preview["import_id"], mapping)
        assert committed["import"]["row_count"] == 2
        mean = query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "corn_yield_kg_ha", "filters": {"year": "2011"}})
        assert mean["value"] == 0 and mean["numeric_count"] == 1
        assert mean["unit"] == "kg/ha" and mean["evidence_role"] == "observation"
        assert mean["aggregation_basis"] == "unweighted_selected_record_mean"
        missing = query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "soybean_yield_kg_ha", "filters": {"year": "2012"}})
        assert missing["value"] == 300 and missing["numeric_count"] == 1 and missing["missing_count"] == 0
        assert receipt["raw_sha256"] in mean["source"]["citation"]
        assert mean["source"]["license"] == "CC0-1.0"
        rows = query_import(store, field["id"], preview["import_id"], {"operation": "rows", "filters": {"plot_id": "101"}, "limit": 10})
        assert len(rows["rows"]) == 2
        assert all(receipt["raw_sha256"] in row["values"]["source_row"] for row in rows["rows"])
        other_plot = query_import(store, field["id"], preview["import_id"], {"operation": "rows", "filters": {"plot_id": "104"}, "limit": 10})
        assert other_plot["rows"] == []
        second_field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
                                                       payload={"display_name": "CSCAP ARL source plot 104", "region_text": "Historical study only"})
        second_preview = preview_import(store, second_field, "owner", "cscap-arl.csv", (output / "cscap-arl.csv").read_bytes())
        second_mapping = json.loads((output / "cscap-arl-104.mapping.json").read_text())
        commit_import(store, second_field, second_preview["import_id"], second_mapping)
        unknown = query_import(store, second_field["id"], second_preview["import_id"], {"operation": "mean", "column": "soybean_yield_kg_ha", "filters": {"year": "2012"}})
        assert unknown["value"] is None and unknown["numeric_count"] == 0 and unknown["missing_count"] == 1
    finally:
        store._conn.close()
