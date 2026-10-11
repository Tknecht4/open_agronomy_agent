from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from agronomy_agent.cscap_intake import DEFAULT_CONTRACT, prepare_cscap_intake
from agronomy_agent.field_data import parse_table
from agronomy_agent.paths import repo_path
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.field_data_store import commit_import, field_data_snapshot, preview_import, query_import


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
                                                payload={"display_name": "CSCAP ARL archival research study", "region_text": "Wisconsin research site; no farmer-field identity or geometry",
                                                         "metadata": {"research_context": mapping["research_context"]}})
        preview = preview_import(store, field, "owner", "cscap-arl.csv", (output / "cscap-arl.csv").read_bytes())
        committed = commit_import(store, field, preview["import_id"], mapping)
        assert committed["import"]["row_count"] == 2
        mean = query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "corn_yield_kg_ha", "filters": {"year": "2011"}})
        assert mean["value"] == 0 and mean["numeric_count"] == 1
        assert mean["unit"] == "kg/ha" and mean["evidence_role"] == "interpretation"
        assert mean["source_evidence_role"] == "observation"
        assert mean["label"] == "Corn grain yield at 15.5% MB"
        assert mean["research_context"] == mapping["research_context"]
        assert mean["aggregation_basis"] == "unweighted_selected_record_mean"
        missing = query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "soybean_yield_kg_ha", "filters": {"year": "2012"}})
        assert missing["value"] == 300 and missing["numeric_count"] == 1 and missing["missing_count"] == 0
        assert missing["label"] == "Soybean grain yield at 13.0% MB"
        assert receipt["raw_sha256"] in mean["source"]["citation"]
        assert mean["source"]["license"] == "CC0-1.0"
        rows = query_import(store, field["id"], preview["import_id"], {"operation": "rows", "filters": {"plot_id": "101"}, "limit": 10})
        assert len(rows["rows"]) == 2
        assert all(receipt["raw_sha256"] in row["values"]["source_row"] for row in rows["rows"])
        other_plot = query_import(store, field["id"], preview["import_id"], {"operation": "rows", "filters": {"plot_id": "104"}, "limit": 10})
        assert other_plot["rows"] == []
        second_field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
                                                       payload={"display_name": "CSCAP ARL source plot 104", "region_text": "Historical study only",
                                                                "metadata": {"research_context": {**mapping["research_context"], "plot_id": "104"}}})
        second_preview = preview_import(store, second_field, "owner", "cscap-arl.csv", (output / "cscap-arl.csv").read_bytes())
        second_mapping = json.loads((output / "cscap-arl-104.mapping.json").read_text())
        commit_import(store, second_field, second_preview["import_id"], second_mapping)
        unknown = query_import(store, second_field["id"], second_preview["import_id"], {"operation": "mean", "column": "soybean_yield_kg_ha", "filters": {"year": "2012"}})
        assert unknown["value"] is None and unknown["numeric_count"] == 0 and unknown["missing_count"] == 1
        assert unknown["source_evidence_role"] == "observation" and unknown["evidence_role"] == "interpretation"
        from agronomy_agent.tool_planner import plan_and_execute_tools
        context = {"field_data": field_data_snapshot(store, field["id"])}
        for column, basis in (("corn_yield_kg_ha", "15.5% MB"), ("soybean_yield_kg_ha", "13.0% MB")):
            plan, results = plan_and_execute_tools(f"What is the mean {column} in my uploaded data?", field_context=context)
            assert plan.status == "ready"
            assert basis in results[0].answer and "kg/ha" in results[0].answer
            assert "Derived descriptive calculation" in results[0].answer
            assert "Historical research context" in results[0].answer
            assert "no current farmer-field measurement or prediction" in results[0].answer
        _, rows_results = plan_and_execute_tools("Show rows from my uploaded data", field_context=context)
        assert all(basis in rows_results[0].answer for basis in ("15.5% MB", "13.0% MB", "13.5% MB"))
        store.update_phase4_field_context(field_context_id=field["id"], actor_user_id="owner", payload={"metadata": {}})
        with pytest.raises(ValueError, match="persisted matching historical_research"):
            query_import(store, field["id"], preview["import_id"], {"operation": "count"})
    finally:
        store._conn.close()


@pytest.mark.parametrize("failure", ["absent", "name_only", "wrong_kind", "wrong_source", "wrong_site", "wrong_plot", "forged_caller", "missing_mapping"])
def test_cscap_wrong_context_refuses_atomically(source, tmp_path, failure):
    raw, contract_path, _, _, _, _ = source
    output = tmp_path / "candidate"
    prepare_cscap_intake(raw, output, contract_path=contract_path)
    mapping = json.loads((output / "cscap-arl-101.mapping.json").read_text())
    research = copy.deepcopy(mapping["research_context"])
    metadata = {"research_context": research}
    if failure in {"absent", "name_only", "forged_caller"}:
        metadata = {}
    elif failure.startswith("wrong_"):
        research[{"wrong_kind": "kind", "wrong_source": "source_id", "wrong_site": "study_site", "wrong_plot": "plot_id"}[failure]] = "wrong"
    elif failure == "missing_mapping":
        mapping.pop("research_context")
    store = TraceStore(tmp_path / "wrong-context.sqlite3")
    try:
        field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
            payload={"display_name": "CSCAP historical research" if failure == "name_only" else "Current farmer field",
                     "region_text": "Wisconsin", "metadata": metadata})
        if failure == "forged_caller":
            field["metadata"] = {"research_context": mapping["research_context"]}
        preview = preview_import(store, field, "owner", "cscap-arl.csv", (output / "cscap-arl.csv").read_bytes())
        with pytest.raises(ValueError, match="historical_research"):
            commit_import(store, field, preview["import_id"], mapping)
        assert store._conn.execute("SELECT COUNT(*) FROM field_data_rows").fetchone()[0] == 0
        assert store._conn.execute("SELECT status FROM field_data_imports WHERE id = ?", (preview["import_id"],)).fetchone()[0] == "preview"
    finally:
        store._conn.close()


def test_cscap_native_provenance_guard_survives_removed_source_metadata(tmp_path):
    from agronomy_agent.server.storage.field_data_store import CSCAP_ROW_PREFIX
    store = TraceStore(tmp_path / "native-provenance.sqlite3")
    try:
        field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
                                                 payload={"display_name": "Current field", "region_text": "Wisconsin"})
        content = b"sample,source_row\na," + CSCAP_ROW_PREFIX + b"Agronomic!row=4\n"
        preview = preview_import(store, field, "owner", "renamed.csv", content)
        mapping = {"filters": {}, "record_key": ["sample"], "source": {"title": "Renamed"}, "columns": [
            {"column": "sample", "label": "Sample", "unit": None, "role": "identifier", "aggregation": "none", "evidence_role": "observation"}]}
        with pytest.raises(ValueError, match="historical_research"):
            commit_import(store, field, preview["import_id"], mapping)
        assert store._conn.execute("SELECT COUNT(*) FROM field_data_rows").fetchone()[0] == 0
    finally:
        store._conn.close()


@pytest.mark.parametrize("container", ["xlsx", "zip"])
@pytest.mark.parametrize("map_provenance", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_decoded_native_provenance_refuses_compressed_farmer_imports(tmp_path, monkeypatch, container, map_provenance, legacy):
    from agronomy_agent.server.storage import field_data_store
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["study_site", "plot_id", "year", "yield", "source_row"])
    locator = field_data_store.CSCAP_ROW_PREFIX.decode() + "Agronomic!row=4"
    book.active.append(["ARL", "101", "2011", 0, locator])
    buffer = io.BytesIO()
    book.save(buffer)
    content = buffer.getvalue()
    filename = "renamed.xlsx"
    if container == "zip":
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr(filename, content)
        content, filename = archive.getvalue(), "renamed.zip"
    assert field_data_store.CSCAP_ROW_PREFIX not in content
    assert parse_table(filename, content)["rows"][0]["values"]["source_row"] == locator
    mapping = {"filters": {"study_site": "ARL", "plot_id": "101"}, "record_key": ["study_site", "plot_id", "year"],
               "source": {"title": "Renamed table"}, "columns": [
                   {"column": "yield", "label": "Yield", "unit": "kg/ha", "role": "measurement", "aggregation": "mean", "evidence_role": "observation"}]}
    if map_provenance:
        mapping["columns"].append({"column": "source_row", "label": "Locator", "unit": None, "role": "context", "aggregation": "none", "evidence_role": "observation"})
    store = TraceStore(tmp_path / "compressed.sqlite3")
    try:
        field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
                                                 payload={"display_name": "Current farmer field", "region_text": "Wisconsin"})
        preview = preview_import(store, field, "owner", filename, content)
        if legacy:
            with monkeypatch.context() as old:
                old.setattr(field_data_store, "_require_research_context", lambda *args: None)
                manifest = commit_import(store, field, preview["import_id"], mapping)["import"]
            with pytest.raises(ValueError, match="historical_research"):
                query_import(store, field["id"], preview["import_id"], {"operation": "count"})
            with pytest.raises(ValueError, match="historical_research"):
                field_data_snapshot(store, field["id"])
            assert field_data_store.list_imports(store, field["id"])["imports"] == [manifest]
        else:
            with pytest.raises(ValueError, match="historical_research"):
                commit_import(store, field, preview["import_id"], mapping)
            assert store._conn.execute("SELECT COUNT(*) FROM field_data_rows").fetchone()[0] == 0
            assert store._conn.execute("SELECT status FROM field_data_imports WHERE id = ?", (preview["import_id"],)).fetchone()[0] == "preview"
            context = {"kind": "historical_research", "source_id": field_data_store.CSCAP_SOURCE_ID, "study_site": "ARL", "plot_id": "101"}
            store.update_phase4_field_context(field_context_id=field["id"], actor_user_id="owner", payload={"metadata": {"research_context": context}})
            mapping["research_context"] = context
            commit_import(store, field, preview["import_id"], mapping)
            result = query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "yield"})
            assert result["value"] == 0 and result["research_context"] == context
            assert result["source_evidence_role"] == "observation" and result["evidence_role"] == "interpretation"
    finally:
        store._conn.close()


def test_legacy_committed_cscap_is_not_readable_without_research_context(source, tmp_path, monkeypatch):
    from agronomy_agent.server.storage import field_data_store
    raw, contract_path, _, _, _, _ = source
    output = tmp_path / "candidate"
    prepare_cscap_intake(raw, output, contract_path=contract_path)
    mapping = json.loads((output / "cscap-arl-101.mapping.json").read_text())
    mapping.pop("research_context")
    store = TraceStore(tmp_path / "legacy.sqlite3")
    try:
        field = store.create_phase4_field_context(workspace={"id": "workspace", "organization_id": "org"}, created_by_user_id="owner",
                                                 payload={"display_name": "Existing field", "region_text": "Wisconsin"})
        preview = preview_import(store, field, "owner", "cscap-arl.csv", (output / "cscap-arl.csv").read_bytes())
        # Emulate the previously accepted storage state, retaining its original
        # source/mapping identities. The current query path must refuse it.
        with monkeypatch.context() as legacy:
            legacy.setattr(field_data_store, "_require_research_context", lambda *args: None)
            manifest = commit_import(store, field, preview["import_id"], mapping)["import"]
        with pytest.raises(ValueError, match="historical_research"):
            query_import(store, field["id"], preview["import_id"], {"operation": "mean", "column": "corn_yield_kg_ha"})
        assert field_data_store.list_imports(store, field["id"])["imports"] == [manifest]
    finally:
        store._conn.close()
