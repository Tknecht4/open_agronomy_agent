from __future__ import annotations

from pathlib import Path
import json
import hashlib

import pytest

from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.field_data_store import (
    commit_import,
    field_data_snapshot,
    list_imports,
    preview_import,
    query_import,
)


def _field(store: TraceStore, workspace_id: str) -> dict:
    return store.create_phase4_field_context(
        workspace={"id": workspace_id, "organization_id": "org"},
        created_by_user_id="owner",
        payload={"display_name": workspace_id, "region_text": "Saskatchewan"},
    )


def _mapping(*, filter_field: str = "A", aggregation: str = "mean", value_scope: str | None = None,
             record_key: bool = True) -> dict:
    mapping = {
        "filters": {"Field": filter_field}, "record_key": ["Sample"] if record_key else [],
        "columns": [
            {"column": "Sample", "label": "Sample", "unit": None, "role": "identifier",
             "aggregation": "none", "evidence_role": "observation"},
            {"column": "Value", "label": "Value", "unit": "kg/ha", "role": "measurement",
             "aggregation": aggregation, "evidence_role": "observation"},
        ],
        "source": {"title": "Test source", "license": "user asserted"},
    }
    if value_scope is not None:
        mapping["columns"][1]["value_scope"] = value_scope
    return mapping


SOURCE = b"Field,Sample,Value\nA,one,2\nB,two,999\nA,three,4\n"


def test_preview_commit_query_reload_and_field_binding(tmp_path: Path) -> None:
    path = tmp_path / "field-data.sqlite3"
    store = TraceStore(path)
    a = _field(store, "workspace-a")
    b = _field(store, "workspace-b")
    preview = preview_import(store, a, "owner", "values.csv", SOURCE)
    import_id = preview["import_id"]
    assert preview["profile"]["content_sha256"]
    assert list_imports(store, a["id"]) == {"imports": []}
    with pytest.raises(ValueError, match="committed"):
        query_import(store, a["id"], import_id, {"operation": "count"})
    with pytest.raises(ValueError, match="field"):
        commit_import(store, b, import_id, _mapping())
    manifest = commit_import(store, a, import_id, _mapping())["import"]
    assert manifest["row_count"] == 2
    assert commit_import(store, a, import_id, _mapping(value_scope="unknown"))["import"] == manifest
    with pytest.raises(ValueError, match="immutable"):
        commit_import(store, a, import_id, _mapping(aggregation="sum", value_scope="record"))
    with pytest.raises(ValueError, match="field"):
        query_import(store, b["id"], import_id, {"operation": "count"})
    with pytest.raises(ValueError, match="field"):
        preview_import(store, {**a, "workspace_id": "workspace-b"}, "owner", "values.csv", SOURCE)
    store._conn.close()

    reloaded = TraceStore(path)
    assert len(list_imports(reloaded, a["id"])["imports"]) == 1
    receipt = query_import(reloaded, a["id"], import_id, {"operation": "mean", "column": "Value"})
    assert receipt["value"] == 3
    assert receipt["selected_row_count"] == 2
    assert receipt["unit"] == "kg/ha"
    assert receipt["value_scope"] == "unknown"
    assert receipt["aggregation_basis"] == "unweighted_selected_record_mean"
    assert "not a field-season estimate" in receipt["limitations"][0]
    assert receipt["locators"] == [
        {"record": 2, "physical_line_end": 2}, {"record": 4, "physical_line_end": 4},
    ]
    assert receipt["receipt_sha256"] and receipt["selected_rows_sha256"]
    snapshot = field_data_snapshot(reloaded, a["id"])
    assert snapshot["snapshot_sha256"]
    assert snapshot["imports"][0]["summaries"][0]["value"] == 2
    assert snapshot["imports"][0]["summaries"][1]["value"] == 3
    compact = snapshot["imports"][0]["summaries"][1]
    assert compact["receipt_sha256"] == hashlib.sha256(
        json.dumps({key: value for key, value in compact.items() if key != "receipt_sha256"},
                   ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_scope_key_aggregation_and_atomic_failure(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    preview = preview_import(store, field, "owner", "values.csv", SOURCE)
    import_id = preview["import_id"]
    no_filter = _mapping()
    no_filter["filters"] = {}
    with pytest.raises(ValueError, match="multi-field"):
        commit_import(store, field, import_id, no_filter)
    single_id = preview_import(store, field, "owner", "single.csv", b"Field,Sample,Value\nA,one,2\n")["import_id"]
    with pytest.raises(ValueError, match="field identity"):
        commit_import(store, field, single_id, no_filter)
    assert store._conn.execute("SELECT COUNT(*) FROM field_data_rows WHERE import_id = ?", (import_id,)).fetchone()[0] == 0
    duplicate = b"Field,Sample,Value\nA,one,2\nA,one,4\n"
    duplicate_id = preview_import(store, field, "owner", "duplicate.csv", duplicate)["import_id"]
    with pytest.raises(ValueError, match="duplicated"):
        commit_import(store, field, duplicate_id, _mapping())
    assert store._conn.execute("SELECT COUNT(*) FROM field_data_rows WHERE import_id = ?", (duplicate_id,)).fetchone()[0] == 0
    manifest = commit_import(store, field, import_id, _mapping())["import"]
    other_preview = preview_import(store, field, "owner", "values.csv", SOURCE)
    assert commit_import(store, field, other_preview["import_id"], _mapping())["import"] == manifest
    assert len(list_imports(store, field["id"])["imports"]) == 1


def test_value_scope_blocks_field_season_sum_and_allows_equal_distinct_records(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    source = b"Field,Sample,Value\nA,one,5\nA,two,5\nA,three,NA\nA,four,\n"
    import_id = preview_import(store, field, "owner", "rates.csv", source)["import_id"]
    with pytest.raises(ValueError, match="field_season"):
        commit_import(store, field, import_id, _mapping(aggregation="sum", value_scope="field_season"))
    with pytest.raises(ValueError, match="field_season"):
        commit_import(store, field, import_id, _mapping(aggregation="mean", value_scope="field_season"))
    with pytest.raises(ValueError, match="record value_scope"):
        commit_import(store, field, import_id, _mapping(aggregation="sum"))
    with pytest.raises(ValueError, match="record_key"):
        commit_import(store, field, import_id, _mapping(aggregation="sum", value_scope="record", record_key=False))
    mixed_id = preview_import(store, field, "owner", "mixed.csv",
                              b"Field,Sample,Value\nA,one,5\nA,two,7\n")["import_id"]
    with pytest.raises(ValueError, match="field_season"):
        commit_import(store, field, mixed_id, _mapping(aggregation="sum", value_scope="field_season"))
    commit_import(store, field, import_id, _mapping(aggregation="sum", value_scope="record"))
    summed = query_import(store, field["id"], import_id, {"operation": "sum", "column": "Value"})
    assert summed["value"] == 10
    assert summed["value_scope"] == "record"
    assert summed["aggregation_basis"] == "distinct_record_key_sum"
    assert summed["numeric_count"] == 2
    assert summed["invalid_count"] == 1
    assert summed["missing_count"] == 1
    with pytest.raises(ValueError, match="declared"):
        query_import(store, field["id"], import_id, {"operation": "mean", "column": "Value"})
    rows = query_import(store, field["id"], import_id, {"operation": "rows", "limit": 2})
    assert rows["truncated"] is True
    assert rows["selected_row_count"] == 4
    assert rows["locators_truncated"] is True
    snapshot = field_data_snapshot(store, field["id"])
    assert snapshot["imports"][0]["summaries"][1]["value"] == 10
    assert snapshot["imports"][0]["summaries"][1]["value_scope"] == "record"


def test_field_season_unique_is_permitted(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    source = b"Field,Sample,Value\nA,one,5\nA,two,5\n"
    import_id = preview_import(store, field, "owner", "season.csv", source)["import_id"]
    commit_import(store, field, import_id, _mapping(aggregation="unique", value_scope="field_season"))
    receipt = query_import(store, field["id"], import_id, {"operation": "unique", "column": "Value"})
    assert receipt["value"] == ["5"]
    assert receipt["value_scope"] == "field_season"


def test_invalid_numeric_and_missing_counts_are_explicit(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    source = b"Field,Sample,Value\nA,one,2\nA,two,NA\nA,three,\nA,four,1e999\n"
    import_id = preview_import(store, field, "owner", "numbers.csv", source)["import_id"]
    commit_import(store, field, import_id, _mapping())
    receipt = query_import(store, field["id"], import_id, {"operation": "mean", "column": "Value"})
    assert receipt["value"] == 2
    assert receipt["numeric_count"] == 1
    assert receipt["missing_count"] == 1
    assert receipt["invalid_count"] == 2
    assert receipt["selected_row_count"] == 4


def test_extreme_finite_mean_stays_finite_and_overflowing_sum_fails(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    source = b"Field,Sample,Value\nA,one,1e308\nA,two,1e308\n"
    mean_id = preview_import(store, field, "owner", "large.csv", source)["import_id"]
    commit_import(store, field, mean_id, _mapping())
    mean = query_import(store, field["id"], mean_id, {"operation": "mean", "column": "Value"})
    assert mean["value"] == 1e308
    json.dumps(mean, allow_nan=False)

    sum_id = preview_import(store, field, "owner", "large.csv", source)["import_id"]
    commit_import(store, field, sum_id, _mapping(aggregation="sum", value_scope="record"))
    with pytest.raises(ValueError, match="finite range"):
        query_import(store, field["id"], sum_id, {"operation": "sum", "column": "Value"})
    snapshot = field_data_snapshot(store, field["id"])
    json.dumps(snapshot, allow_nan=False)
    assert snapshot["imports"][0]["summaries"][1]["status"] == "blocked"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda mapping: mapping.update(record_key=[["Sample"]]), "record_key"),
        (lambda mapping: mapping["columns"][0].update(column=["Sample"]), "mapped column"),
        (lambda mapping: mapping["columns"][1].update(aggregation=["mean"]), "invalid column"),
        (lambda mapping: mapping["columns"][1].update(value_scope=["record"]), "invalid value_scope"),
        (lambda mapping: mapping.update(filters={"Field": ["A"]}), "filters"),
    ],
)
def test_malformed_mapping_fails_as_validation_error(tmp_path: Path, mutate, match: str) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    import_id = preview_import(store, field, "owner", "values.csv", SOURCE)["import_id"]
    mapping = _mapping()
    mutate(mapping)
    with pytest.raises(ValueError, match=match):
        commit_import(store, field, import_id, mapping)
    assert store._conn.execute("SELECT COUNT(*) FROM field_data_rows WHERE import_id = ?", (import_id,)).fetchone()[0] == 0


def test_stored_source_and_rows_are_verified_on_read(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    import_id = preview_import(store, field, "owner", "values.csv", SOURCE)["import_id"]
    store._conn.execute("UPDATE field_data_imports SET source_bytes = ? WHERE id = ?", (b"corrupted", import_id))
    store._conn.commit()
    with pytest.raises(ValueError, match="unexpected inline bytes"):
        commit_import(store, field, import_id, _mapping())
    store._conn.execute("UPDATE field_data_imports SET source_bytes = X'' WHERE id = ?", (import_id,))
    store._conn.commit()
    commit_import(store, field, import_id, _mapping())
    store._conn.execute(
        "UPDATE field_data_rows SET values_json = ? WHERE import_id = ? AND row_number = 1",
        ('{"Field":"A","Sample":"one","Value":"900"}', import_id),
    )
    store._conn.commit()
    with pytest.raises(ValueError, match="row checksum"):
        query_import(store, field["id"], import_id, {"operation": "count"})


def test_new_preview_allows_changed_mapping_and_snapshot_stays_bounded(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    for index in range(16):
        import_id = preview_import(store, field, "owner", f"values-{index}.csv", SOURCE)["import_id"]
        mapping = _mapping(aggregation="mean" if index % 2 else "sum",
                           value_scope="record" if index % 2 == 0 else None)
        mapping["source"]["title"] = f"Source {index}"
        commit_import(store, field, import_id, mapping)
    snapshot = field_data_snapshot(store, field["id"])
    assert snapshot["import_count"] == 16
    assert snapshot["imports_truncated"] is True
    assert snapshot["omitted_import_count"] >= 4
    assert len(json.dumps(snapshot, ensure_ascii=False).encode()) <= 64 * 1024
    assert snapshot["imports"][0]["source"]["title"] == "Source 15"


def test_snapshot_marks_cell_projection_as_truncated(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    source = b"Field,Sample,Value\nA,one," + b"1" * 300 + b"\n"
    import_id = preview_import(store, field, "owner", "wide.csv", source)["import_id"]
    commit_import(store, field, import_id, _mapping())
    item = field_data_snapshot(store, field["id"])["imports"][0]
    assert item["row_count"] == 1
    assert item["preview_rows_truncated"] is True
    assert len(item["preview_rows"][0]["values"]["Value"]) == 160


def test_field_word_inside_measurement_name_is_not_identity_scope(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "field-data.sqlite3")
    field = _field(store, "workspace-a")
    source = b"date_field_transplant,field_capacity,Sample,Value\n2026-05-01,0.2,one,2\n"
    import_id = preview_import(store, field, "owner", "transplants.csv", source)["import_id"]
    mapping = _mapping()
    mapping["filters"] = {}
    assert commit_import(store, field, import_id, mapping)["import"]["row_count"] == 1
