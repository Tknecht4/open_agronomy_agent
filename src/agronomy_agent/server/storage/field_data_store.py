"""Private, field-bound table imports and deterministic query receipts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from agronomy_agent.field_data import parse_table, safe_number

MAX_QUERY_ROWS = 100
MAX_SNAPSHOT_ROWS = 8
MAX_SNAPSHOT_IMPORTS = 12
MAX_SNAPSHOT_BYTES = 64 * 1024
MAX_SNAPSHOT_COLUMNS = 16
MAX_SNAPSHOT_SUMMARIES = 4
MAX_SNAPSHOT_VALUE_CHARS = 160
FIELD_IDENTITY_COLUMNS = {
    "field", "field_id", "field_code", "field_name", "field_number",
    "farm", "farm_id", "farm_name", "site", "site_id", "site_code", "site_name",
    "location", "location_id", "plot", "plot_id", "plot_code",
}
ROLES = {"measurement", "context", "identifier"}
EVIDENCE_ROLES = {"observation", "model_output", "interpretation", "regional_prior"}
AGGREGATIONS = {"none", "mean", "sum", "unique"}
VALUE_SCOPES = {"record", "field_season", "unknown"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field_id(field: dict[str, Any]) -> str:
    field_id = field.get("id") or field.get("field_context_id")
    if not isinstance(field_id, str) or not field_id:
        raise ValueError("field identity required")
    return field_id


def _assert_field(cursor: Any, field_id: str, field: dict[str, Any] | None = None) -> dict[str, Any]:
    row = cursor.execute("SELECT id, workspace_id FROM phase4_field_contexts WHERE id = ? AND deleted_at IS NULL", (field_id,)).fetchone()
    if row is None:
        raise ValueError("unknown or deleted field")
    if field is not None and field.get("workspace_id") != row["workspace_id"]:
        raise ValueError("field workspace mismatch")
    return dict(row)


def _profile(parsed: dict[str, Any], content_sha256: str) -> dict[str, Any]:
    return {
        "filename": parsed["filename"], "content_sha256": content_sha256,
        "member_name": parsed["member_name"], "member_sha256": parsed["member_sha256"],
        "columns": parsed["columns"], "row_count": parsed["row_count"],
        "preview_rows": parsed["rows"][:MAX_SNAPSHOT_ROWS],
        "encoding": parsed["encoding"], "delimiter": parsed["delimiter"],
        "warnings": parsed["warnings"],
    }


def preview_import(
    store: Any, field: dict[str, Any], actor_id: str, filename: str,
    content: bytes, encoding: str | None = None,
) -> dict[str, Any]:
    """Persist source bytes privately; no row is queryable until commit."""
    if not isinstance(content, bytes) or not actor_id:
        raise ValueError("source bytes and actor required")
    parsed = parse_table(filename, content, encoding)
    field_id = _field_id(field)
    source_sha256 = hashlib.sha256(content).hexdigest()
    profile = _profile(parsed, source_sha256)
    import_id = str(uuid.uuid4())
    with store._field_event_lock:
        with store._cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            bound = _assert_field(cursor, field_id, field)
            cursor.execute(
                """INSERT INTO field_data_imports
                (id, field_id, workspace_id, actor_id, filename, source_bytes, source_sha256,
                 profile_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preview', ?)""",
                (import_id, field_id, bound["workspace_id"], actor_id, parsed["filename"], content,
                 source_sha256, _json(profile), _now()),
            )
    return {
        "import_id": import_id, "status": "preview", "profile": profile,
        "mapping_suggestion": {"filters": {}, "record_key": [], "columns": [
            {"column": column, "label": column, "unit": None, "role": "context",
             "aggregation": "none", "evidence_role": "observation", "value_scope": "unknown"}
            for column in parsed["columns"]
        ], "source": {"title": parsed["filename"]}},
    }


def _validate_mapping(mapping: dict[str, Any], parsed: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(mapping, dict):
        raise ValueError("mapping must be an object")
    available = set(parsed["columns"])
    filters = mapping.get("filters")
    if not isinstance(filters, dict) or any(not isinstance(k, str) or k not in available or not isinstance(v, str) for k, v in filters.items()):
        raise ValueError("filters must give exact source column values")
    record_key = mapping.get("record_key")
    if (not isinstance(record_key, list) or any(not isinstance(k, str) or k not in available for k in record_key)
            or len(record_key) != len(set(record_key))):
        raise ValueError("record_key must list distinct source columns")
    columns = mapping.get("columns")
    if not isinstance(columns, list) or not columns or len(columns) > len(available):
        raise ValueError("mapping requires selected columns")
    selected = set()
    normalized_columns = []
    for spec in columns:
        required = {"column", "label", "unit", "role", "aggregation", "evidence_role"}
        if not isinstance(spec, dict) or not required <= set(spec) or not set(spec) <= required | {"value_scope"}:
            raise ValueError("column metadata must be explicit")
        name = spec["column"]
        if not isinstance(name, str) or name not in available or name in selected:
            raise ValueError("unknown or duplicate mapped column")
        selected.add(name)
        if not isinstance(spec["label"], str) or not spec["label"].strip() or len(spec["label"]) > 256:
            raise ValueError("column label required")
        if spec["unit"] is not None and (not isinstance(spec["unit"], str) or not spec["unit"].strip() or len(spec["unit"]) > 64):
            raise ValueError("unit must be explicit text or null")
        if (not isinstance(spec["role"], str) or spec["role"] not in ROLES
                or not isinstance(spec["aggregation"], str) or spec["aggregation"] not in AGGREGATIONS
                or not isinstance(spec["evidence_role"], str) or spec["evidence_role"] not in EVIDENCE_ROLES):
            raise ValueError("invalid column role, aggregation or evidence role")
        value_scope = spec.get("value_scope", "unknown")
        if not isinstance(value_scope, str) or value_scope not in VALUE_SCOPES:
            raise ValueError("invalid value_scope")
        if spec["aggregation"] in {"mean", "sum"} and (spec["unit"] is None or spec["role"] != "measurement"):
            raise ValueError("numeric aggregation requires measurement role and declared unit")
        if value_scope == "field_season" and spec["aggregation"] not in {"none", "unique"}:
            raise ValueError("field_season values permit only none or unique aggregation")
        if spec["aggregation"] == "sum" and (value_scope != "record" or not record_key):
            raise ValueError("sum requires record value_scope and nonempty record_key")
        normalized_columns.append({**spec, "value_scope": value_scope})
    source = mapping.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not source["title"].strip():
        raise ValueError("source title required")
    if set(source) - {"title", "url", "license", "citation"} or any(
        not isinstance(v, str) or len(v) > 2048 for v in source.values()
    ):
        raise ValueError("invalid source metadata")
    rows = parsed["rows"]
    for name, exact in filters.items():
        if exact not in {row["values"][name] for row in rows}:
            raise ValueError("filter value does not occur in source")
    for name in available:
        normalized_name = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if normalized_name in FIELD_IDENTITY_COLUMNS:
            values = {row["values"][name] for row in rows if row["values"][name].strip()}
            if values and name not in filters:
                if len(values) > 1:
                    raise ValueError(f"multi-field source requires exact filter on {name}")
                raise ValueError(f"field identity column {name} requires an explicit exact filter")
    selected_rows = [row for row in rows if all(row["values"][k] == v for k, v in filters.items())]
    if not selected_rows:
        raise ValueError("filters select no rows")
    if record_key:
        keys = [tuple(row["values"][name] for name in record_key) for row in selected_rows]
        if any(not all(key) for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("record key is blank or duplicated")
    normalized = {"filters": filters, "record_key": record_key, "columns": normalized_columns, "source": source}
    return normalized, selected_rows


def _manifest(import_row: Any, mapping: dict[str, Any], row_count: int, committed_at: str) -> dict[str, Any]:
    return {
        "import_id": import_row["id"], "status": "committed", "field_id": import_row["field_id"],
        "workspace_id": import_row["workspace_id"], "filename": import_row["filename"],
        "source_sha256": import_row["source_sha256"], "content_sha256": import_row["source_sha256"],
        "member_name": json.loads(import_row["profile_json"])["member_name"],
        "member_sha256": json.loads(import_row["profile_json"])["member_sha256"],
        "mapping_sha256": _hash(mapping), "source": mapping["source"], "columns": mapping["columns"],
        "filters": mapping["filters"], "record_key": mapping["record_key"],
        "row_count": row_count, "committed_at": committed_at,
        "limitations": ["User-asserted source metadata; rights and field measurement meaning are not independently verified."],
    }


def commit_import(store: Any, field: dict[str, Any], import_id: str, mapping: dict[str, Any]) -> dict[str, Any]:
    field_id = _field_id(field)
    with store._field_event_lock:
        with store._cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            _assert_field(cursor, field_id, field)
            imported = cursor.execute("SELECT * FROM field_data_imports WHERE id = ? AND field_id = ?", (import_id, field_id)).fetchone()
            if imported is None:
                raise ValueError("unknown import for field")
            if hashlib.sha256(bytes(imported["source_bytes"])).hexdigest() != imported["source_sha256"]:
                raise ValueError("stored source checksum mismatch")
            parsed = parse_table(imported["filename"], bytes(imported["source_bytes"]), json.loads(imported["profile_json"])["encoding"] if imported["filename"].lower().endswith(("csv", "tsv", "tab")) else None)
            normalized, rows = _validate_mapping(mapping, parsed)
            mapping_hash = _hash(normalized)
            if imported["status"] == "committed":
                if imported["mapping_sha256"] != mapping_hash:
                    raise ValueError("committed mapping is immutable; create a new preview")
                return {"import": json.loads(imported["manifest_json"])}
            prior = cursor.execute(
                """SELECT manifest_json FROM field_data_imports WHERE field_id = ? AND source_sha256 = ?
                AND mapping_sha256 = ? AND status = 'committed'""",
                (field_id, imported["source_sha256"], mapping_hash),
            ).fetchone()
            if prior is not None:
                return {"import": json.loads(prior["manifest_json"])}
            committed_at = _now()
            manifest = _manifest(imported, normalized, len(rows), committed_at)
            for ordinal, row in enumerate(rows, start=1):
                cursor.execute(
                    """INSERT INTO field_data_rows(import_id, field_id, row_number, locator_json, values_json, row_sha256)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (import_id, field_id, ordinal, _json(row["locator"]), _json(row["values"]), _hash(row)),
                )
            cursor.execute(
                """UPDATE field_data_imports SET status = 'committed', mapping_json = ?, mapping_sha256 = ?,
                manifest_json = ?, committed_at = ? WHERE id = ? AND status = 'preview'""",
                (_json(normalized), mapping_hash, _json(manifest), committed_at, import_id),
            )
            return {"import": manifest}


def list_imports(store: Any, field_id: str) -> dict[str, Any]:
    with store._field_event_lock:
        with store._cursor() as cursor:
            _assert_field(cursor, field_id)
            rows = cursor.execute(
                "SELECT manifest_json FROM field_data_imports WHERE field_id = ? AND status = 'committed' ORDER BY committed_at, id",
                (field_id,),
            ).fetchall()
    return {"imports": [json.loads(row["manifest_json"]) for row in rows]}


def _selected_rows(cursor: Any, field_id: str, import_id: str, filters: dict[str, str]) -> list[dict[str, Any]]:
    records = cursor.execute(
        "SELECT locator_json, values_json, row_sha256 FROM field_data_rows WHERE field_id = ? AND import_id = ? ORDER BY row_number",
        (field_id, import_id),
    ).fetchall()
    selected = []
    for row in records:
        values = json.loads(row["values_json"])
        if all(values.get(k) == v for k, v in filters.items()):
            selected.append({"locator": json.loads(row["locator_json"]), "values": values,
                             "row_sha256": row["row_sha256"]})
    return selected


def query_import(store: Any, field_id: str, import_id: str, query: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(query, dict):
        raise ValueError("query must be an object")
    operation = query.get("operation")
    if not isinstance(operation, str) or operation not in {"rows", "count", "mean", "sum", "unique"}:
        raise ValueError("unsupported operation")
    limit = query.get("limit", MAX_QUERY_ROWS)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_QUERY_ROWS:
        raise ValueError("query limit out of bounds")
    filters = query.get("filters", {})
    if not isinstance(filters, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in filters.items()):
        raise ValueError("filters must be exact strings")
    if query.get("column") is not None and not isinstance(query["column"], str):
        raise ValueError("query column must be text")
    with store._field_event_lock:
        with store._cursor() as cursor:
            _assert_field(cursor, field_id)
            imported = cursor.execute("SELECT * FROM field_data_imports WHERE id = ? AND field_id = ? AND status = 'committed'", (import_id, field_id)).fetchone()
            if imported is None:
                raise ValueError("committed import not found for field")
            if hashlib.sha256(bytes(imported["source_bytes"])).hexdigest() != imported["source_sha256"]:
                raise ValueError("stored source checksum mismatch")
            mapping = json.loads(imported["mapping_json"])
            if _hash(mapping) != imported["mapping_sha256"]:
                raise ValueError("stored mapping checksum mismatch")
            columns = {col["column"]: col for col in mapping["columns"]}
            if any(name not in columns for name in filters):
                raise ValueError("filter column was not mapped")
            column = query.get("column")
            if operation in {"mean", "sum", "unique"} and (not isinstance(column, str) or column not in columns):
                raise ValueError("mapped query column required")
            if operation in {"mean", "sum", "unique"} and columns[column]["aggregation"] != operation:
                raise ValueError("aggregation was not declared for column")
            if operation == "sum" and (columns[column].get("value_scope", "unknown") != "record" or not mapping["record_key"]):
                raise ValueError("sum requires record value_scope and nonempty record_key")
            if operation == "mean" and columns[column].get("value_scope", "unknown") == "field_season":
                raise ValueError("field_season values cannot be averaged across rows")
            rows = _selected_rows(cursor, field_id, import_id, filters)
            total_rows = cursor.execute(
                "SELECT COUNT(*) FROM field_data_rows WHERE import_id = ? AND field_id = ?", (import_id, field_id),
            ).fetchone()[0]
            if total_rows != json.loads(imported["manifest_json"])["row_count"]:
                raise ValueError("stored row count mismatch")
            for row in rows:
                if _hash({"locator": row["locator"], "values": row["values"]}) != row["row_sha256"]:
                    raise ValueError("stored row checksum mismatch")
    spec = columns.get(column) if column else None
    values = [row["values"][column] for row in rows] if spec else []
    missing = sum(not value.strip() for value in values)
    invalid = 0
    result: dict[str, Any] = {}
    if operation == "rows":
        result["rows"] = [{"locator": row["locator"], "values": {name: row["values"][name][:512] for name in columns},
                           "row_sha256": row["row_sha256"]} for row in rows[:limit]]
        result["truncated"] = len(rows) > limit or any(
            len(row["values"][name]) > 512 for row in rows[:limit] for name in columns
        )
    elif operation == "count":
        result["value"] = len(rows)
    elif operation == "unique":
        distinct = sorted({value for value in values if value.strip()})
        result["value"] = [value[:512] for value in distinct[:limit]]
        result["distinct_count"] = len(distinct)
        result["distinct_values_sha256"] = _hash(distinct)
        result["truncated"] = len(distinct) > limit or any(len(value) > 512 for value in distinct[:limit])
    else:
        numeric = [safe_number(value) for value in values if value.strip()]
        invalid = sum(value is None for value in numeric)
        clean = [value for value in numeric if value is not None]
        if clean:
            try:
                if operation == "mean":
                    # Scale before summing: 1e308 + 1e308 overflows, but its mean is finite.
                    aggregate = math.fsum(value / len(clean) for value in clean)
                else:
                    aggregate = math.fsum(clean)
            except OverflowError as exc:
                raise ValueError("numeric aggregation exceeds finite range") from exc
            if not math.isfinite(aggregate):
                raise ValueError("numeric aggregation exceeds finite range")
            result["value"] = aggregate
        else:
            result["value"] = None
        result["numeric_count"] = len(clean)
    receipt = {
        "schema_version": "field_data.query.v1", "field_id": field_id, "import_id": import_id,
        "source_sha256": imported["source_sha256"], "mapping_sha256": imported["mapping_sha256"],
        "member_sha256": json.loads(imported["profile_json"])["member_sha256"],
        "source": mapping["source"], "operation": operation, "column": column,
        "record_key": mapping["record_key"],
        "aggregation_basis": {
            "rows": "selected_source_rows", "count": "selected_row_count",
            "unique": "distinct_nonmissing_source_strings",
            "mean": "unweighted_selected_record_mean", "sum": "distinct_record_key_sum",
        }[operation],
        "filters": filters, "selected_row_count": len(rows), "missing_count": missing,
        "invalid_count": invalid, "unit": spec["unit"] if spec else None,
        "role": spec["role"] if spec else None, "evidence_role": spec["evidence_role"] if spec else None,
        "value_scope": spec.get("value_scope", "unknown") if spec else None,
        "locators": [row["locator"] for row in rows[:limit]],
        "locators_truncated": len(rows) > limit,
        "selected_rows_sha256": _hash([row["row_sha256"] for row in rows]), **result,
    }
    if operation == "mean" and spec and spec.get("value_scope", "unknown") == "unknown":
        receipt["limitations"] = ["Value scope is unknown; this unweighted row mean is not a field-season estimate."]
    receipt["receipt_sha256"] = _hash(receipt)
    return receipt


def field_data_snapshot(store: Any, field_id: str) -> dict[str, Any]:
    all_manifests = list_imports(store, field_id)["imports"]
    manifests = list(reversed(all_manifests[-MAX_SNAPSHOT_IMPORTS:]))
    imports = []
    for manifest in manifests:
        import_id = manifest["import_id"]
        rows = query_import(store, field_id, import_id, {"operation": "rows", "limit": MAX_SNAPSHOT_ROWS})
        selected_columns = manifest["columns"][:MAX_SNAPSHOT_COLUMNS]
        selected_names = {column["column"] for column in selected_columns}
        preview_rows = [{
            "locator": row["locator"], "row_sha256": row["row_sha256"],
            "values": {name: value[:MAX_SNAPSHOT_VALUE_CHARS] for name, value in row["values"].items()
                       if name in selected_names},
        } for row in rows["rows"][:2]]
        preview_cell_clipped = any(
            len(value) > MAX_SNAPSHOT_VALUE_CHARS
            for row in rows["rows"][:2] for name, value in row["values"].items() if name in selected_names
        )
        def compact(receipt: dict[str, Any]) -> dict[str, Any]:
            compacted = {key: receipt.get(key) for key in (
                "operation", "column", "value", "selected_row_count", "record_key", "aggregation_basis",
                "missing_count", "invalid_count", "numeric_count", "unit", "role",
                "evidence_role", "value_scope", "selected_rows_sha256", "source_sha256", "member_sha256",
                "mapping_sha256", "distinct_count", "truncated", "limitations",
            ) if key in receipt} | {
                "locators": receipt["locators"][:2],
                "locators_truncated": receipt["locators_truncated"] or len(receipt["locators"]) > 2,
                "query_receipt_sha256": receipt["receipt_sha256"],
                "field_id": receipt["field_id"], "import_id": receipt["import_id"],
                "schema_version": "field_data.query_snapshot.v1",
                "filters": receipt["filters"],
            }
            compacted["receipt_sha256"] = _hash(compacted)
            return compacted
        summaries = [compact(query_import(store, field_id, import_id, {"operation": "count", "limit": 2}))]
        aggregate_columns = [column for column in manifest["columns"] if column["aggregation"] != "none"]
        for column in aggregate_columns[:MAX_SNAPSHOT_SUMMARIES]:
            if column["aggregation"] != "none":
                try:
                    summaries.append(compact(query_import(store, field_id, import_id, {
                        "operation": column["aggregation"], "column": column["column"], "limit": 2,
                    })))
                except ValueError as exc:
                    summaries.append({"column": column["column"], "status": "blocked", "reason": str(exc)})
        item = {
            "import_id": import_id, "filename": manifest["filename"],
            "source_sha256": manifest["source_sha256"], "mapping_sha256": manifest["mapping_sha256"],
            "member_sha256": manifest["member_sha256"],
            "source": manifest["source"], "columns": selected_columns,
            "column_count": len(manifest["columns"]), "columns_truncated": len(manifest["columns"]) > len(selected_columns),
            "filters": manifest["filters"], "record_key": manifest["record_key"],
            "row_count": manifest["row_count"], "preview_rows": preview_rows,
            "preview_rows_truncated": manifest["row_count"] > len(preview_rows) or rows["truncated"] or preview_cell_clipped,
            "rows_receipt": compact(rows), "summaries": summaries,
            "summary_count": 1 + len(aggregate_columns),
            "summaries_truncated": len(aggregate_columns) > MAX_SNAPSHOT_SUMMARIES,
        }
        proposed = {"field_id": field_id, "imports": [*imports, item], "import_count": len(all_manifests),
                    "imports_truncated": len(all_manifests) > len(imports) + 1}
        if len(_json(proposed).encode("utf-8")) + 256 > MAX_SNAPSHOT_BYTES:
            break
        imports.append(item)
    snapshot = {"field_id": field_id, "imports": imports,
                "import_count": len(all_manifests), "imports_truncated": len(all_manifests) > len(imports),
                "omitted_import_count": len(all_manifests) - len(imports)}
    snapshot["snapshot_sha256"] = _hash(snapshot)
    return snapshot
