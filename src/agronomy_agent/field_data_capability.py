"""Registered, conservative queries over a server-authorized import snapshot.

This module has no file/network access. Its snapshot must come from the private
store at the product authorization boundary; hashes establish identity, not
permission. Table cells are data and are never instructions to an executor.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

CAPABILITY_ID = "field_table_query"
CAPABILITY_VERSION = "field_table_query_v1"
AUTHORITY_ROLE = "reviewed_private_table_only"
BOUNDARY = (
    "Describes the reviewed imported records only. Source metadata and observation labels are user-asserted; "
    "this is not independent field verification, agronomic advice, or decision authority."
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _known_unit(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in {"", "unknown", "unspecified", "n/a", "na", "none", "?"}


def _contains(text: str, value: str) -> bool:
    return bool(value and re.search(r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", text))


def select_query(question: str, field_context: Mapping[str, Any] | None):
    """Return operation/inputs/missing/clarification, or None when unrelated.

    Deliberately accept a small full-question grammar. Filters, compound requests,
    weighting, time scopes and recommendations must not silently become an
    unfiltered arithmetic answer.
    """
    snapshot = (field_context or {}).get("field_data")
    text = " ".join(question.casefold().strip(" ?.!").split())
    imports = snapshot.get("imports", []) if isinstance(snapshot, Mapping) else []
    mentioned = [(imp, col) for imp in imports for col in imp.get("columns", [])
                 if any(_contains(text, str(col.get(key) or "")) for key in ("column", "label"))]
    named_ids = [imp for imp in imports if _contains(text, str(imp.get("import_id") or ""))]
    named = [imp for imp in imports if any(_contains(text, str(imp.get(k) or "")) for k in ("filename", "import_id"))]
    data_request = bool(named) or bool(re.search(r"\b(?:uploaded|imported|my (?:data|dataset|table|spreadsheet))\b", text))
    if not data_request and not mentioned:
        return None
    operation = next((op for op, pattern in (
        ("mean", r"\b(?:mean|average)\b"), ("sum", r"\b(?:sum|total)\b"),
        ("unique", r"\b(?:unique|distinct)\b"), ("count", r"\b(?:count|how many)\b"),
        ("rows", r"\b(?:show|list|records|rows|values)\b"),
    ) if re.search(pattern, text)), "overview")

    if operation == "overview" and not data_request:
        return None

    def clarify(reason: str):
        return operation, {}, (reason,), reason

    if not imports:
        return clarify("Upload and commit a reviewed field table before querying its records.")
    if snapshot.get("imports_truncated") and len(named_ids) != 1:
        return clarify("The import index is incomplete. Specify one exact retained import ID; a filename or column name cannot disambiguate omitted imports.")
    candidates = named_ids or named or list({imp["import_id"]: imp for imp, _ in mentioned}.values()) or imports
    if len(candidates) != 1:
        return clarify("Specify one imported filename or import ID; multiple tables match this request.")
    imported = candidates[0]
    columns = [col for imp, col in mentioned if imp["import_id"] == imported["import_id"]]
    if len(columns) > 1:
        return clarify("Specify one exact column name; multiple columns match this request.")
    column = columns[0] if columns else None
    if imported.get("columns_truncated"):
        if column is not None or operation in {"mean", "sum", "unique"}:
            return clarify("The column index is incomplete and may hide matching names or labels. Use the explicit table query to select the source column.")
        if len(named_ids) != 1:
            return clarify("The column index is incomplete. Specify the exact import ID for a count or partial row preview.")
    if operation in {"mean", "sum", "unique"} and column is None:
        return clarify("Specify one exact mapped column name for the requested calculation.")
    # Replace only recognized identifiers, then require the complete remaining
    # question to have a supported shape. Never discard a filter clause.
    normalized = text
    if column:
        for label in sorted({str(column.get("column") or ""), str(column.get("label") or "")}, key=len, reverse=True):
            if label:
                normalized = re.sub(r"(?<!\w)" + re.escape(label.casefold()) + r"(?!\w)", "COLUMN", normalized)
    for key in ("filename", "import_id"):
        value = str(imported.get(key) or "")
        if value:
            normalized = re.sub(r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", "TABLE", normalized)
    normalized = normalized.replace('`', '').replace('"', '').replace("'", '')
    suffix = r"(?: (?:in|from|of) (?:(?:my|the|this) )?(?:(?:uploaded|imported|field) )?(?:data|table|dataset|spreadsheet|records|TABLE))?"
    patterns = {
        "mean": r"(?:what is |calculate |compute )?(?:the )?(?:mean|average)(?: of)? COLUMN",
        "sum": r"(?:what is |calculate |compute )?(?:the )?(?:sum|total)(?: of)? COLUMN",
        "unique": r"(?:what are |show |list )?(?:the )?(?:unique|distinct)(?: values)?(?: of| for| in)? COLUMN",
        "count": r"(?:how many (?:rows|records)(?: are there)?|(?:what is |show )?(?:the )?(?:row |record )?count)",
        "rows": r"(?:show|list)(?: me)?(?: the)?(?: (?:rows|records|values)(?: of| for| in)?)?(?: COLUMN)?",
        "overview": r"(?:describe|summarize|show)(?: my| the)?(?: uploaded| imported)? (?:data|table|dataset)",
    }
    if operation == "rows" and column is None and re.fullmatch(patterns["overview"] + suffix, normalized):
        operation = "overview"
    if not re.fullmatch(patterns[operation] + suffix, normalized):
        return clarify("Use a single unfiltered count, mean, sum, unique-values, or rows request with an exact column name. Filters, weighting, comparisons and compound questions require an explicit table query.")
    if operation == "overview":
        operation = "count"
    if operation == "rows":
        receipt = imported.get("rows_receipt")
        if not isinstance(receipt, Mapping):
            return clarify("The snapshot has no row query receipt; reload the committed import.")
        if any(c.get("evidence_role") != "observation" for c in (columns or imported.get("columns", []))):
            return clarify("These records include non-observation evidence; inspect their explicit role labels in the table query.")
        # The store's bounded row projection is a separate receipt: bind the
        # preview and preserve both its parent snapshot and source query identity.
        if "rows" not in receipt:
            receipt = dict(receipt)
            receipt["parent_snapshot_receipt_sha256"] = receipt.pop("receipt_sha256", None)
            receipt["rows"] = imported.get("preview_rows", [])
            receipt["truncated"] = bool(imported.get("preview_rows_truncated") or imported.get("columns_truncated"))
            receipt["receipt_sha256"] = _hash(receipt)
    else:
        if column and column.get("evidence_role") != "observation":
            return clarify("This column is not mapped as an observation; model output, interpretation and regional priors cannot be reported as observed field data.")
        if operation in {"mean", "sum"} and (not _known_unit(column.get("unit")) or column.get("role") != "measurement"):
            return clarify("Review and declare the measurement unit before calculating a mean or sum.")
        if operation == "sum" and (column.get("value_scope") != "record" or not imported.get("record_key")):
            return clarify("Sum requires reviewed per-record value scope and a nonempty unique record key; unknown or field-season scalar scope cannot be summed across rows.")
        if operation == "mean" and column.get("value_scope") == "field_season":
            return clarify("Field-season scalar values cannot be averaged across repeated records; inspect distinct values instead.")
        if operation in {"mean", "sum", "unique"} and column.get("aggregation") != operation:
            return clarify("The requested aggregation is not allowed by the reviewed column mapping; review the mapping first. Repeated field-level values must not be silently summed.")
        receipt = next((r for r in imported.get("summaries", [])
                        if r.get("operation") == operation and r.get("column") == (column.get("column") if column else None)), None)
        if not isinstance(receipt, Mapping) or not receipt.get("receipt_sha256"):
            return clarify("No complete permitted query receipt is available for this operation; use the explicit table query to inspect the block.")
        if operation == "unique" and receipt.get("truncated"):
            return clarify("The distinct-values result exceeds the bounded snapshot. Use the explicit table query; the preview is not the complete set.")
        if operation in {"mean", "sum"} and receipt.get("value") is None:
            return clarify("This column has no valid numeric records for the requested calculation.")
    if operation == "rows" and column and column.get("evidence_role") != "observation":
        return clarify("This column is not mapped as an observation; inspect its labeled records in the explicit table query.")
    if any(receipt.get(key) != imported.get(key) for key in ("import_id", "source_sha256", "mapping_sha256")):
        return clarify("The query receipt does not match the committed import identity; reload the field data.")
    if receipt.get("selected_row_count") != imported.get("row_count"):
        return clarify("The query receipt does not cover the full committed row selection; reload the field data.")
    inputs = {"receipt": dict(receipt), "filename": imported["filename"],
              "column": column.get("column") if column else None,
              "snapshot_sha256": snapshot.get("snapshot_sha256")}
    return operation, inputs, (), None


def execute_field_query(operation: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and render a store-computed receipt without recomputing previews."""
    receipt = dict(inputs["receipt"])
    claimed = receipt.pop("receipt_sha256", None)
    if not claimed or claimed != _hash(receipt) or receipt.get("operation") != operation:
        raise ValueError("invalid field query receipt identity")
    receipt["receipt_sha256"] = claimed
    column = inputs.get("column")
    if operation in {"mean", "sum", "unique"} and receipt.get("evidence_role") != "observation":
        raise ValueError("non-observation query cannot supply observed evidence")
    if operation in {"mean", "sum"} and not _known_unit(receipt.get("unit")):
        raise ValueError("unknown measurement unit")
    if operation == "sum" and (receipt.get("value_scope") != "record" or not receipt.get("record_key")):
        raise ValueError("sum requires reviewed record scope and unique record key")
    if operation == "mean" and receipt.get("value_scope") == "field_season":
        raise ValueError("field-season scalars cannot be averaged across rows")
    if receipt.get("filters"):
        raise ValueError("snapshot queries must be unfiltered within the committed import")
    if operation == "count":
        summary = f"{receipt['value']} imported records."
    elif operation in {"mean", "sum", "unique"}:
        value = _json(receipt["value"]) if isinstance(receipt["value"], list) else str(receipt["value"])
        summary = f"{operation.capitalize()} {column}: {value} {receipt.get('unit') or ''}.".replace(" .", ".")
        summary += (f" Selected records: {receipt['selected_row_count']}; missing: {receipt['missing_count']}; "
                    f"invalid: {receipt['invalid_count']}.")
        if "numeric_count" in receipt:
            summary += f" Numeric records used: {receipt['numeric_count']}."
    elif operation == "rows":
        rows = [{"locator": r["locator"], "values": ({column: r["values"].get(column)} if column else r["values"])} for r in receipt["rows"]]
        summary = f"Imported records {('(partial preview)' if receipt.get('truncated') else '(complete selection)')}: {_json(rows)}."
        summary += f" Showing {len(rows)} of {receipt['selected_row_count']} records."
    else:
        raise ValueError("unsupported field query operation")
    limitations = tuple(str(item) for item in receipt.get("limitations", ()))
    if operation in {"mean", "sum"}:
        summary += f" Value scope: {receipt.get('value_scope', 'unknown')}; basis: {receipt.get('aggregation_basis', 'unavailable')}."
    if limitations:
        summary += " " + " ".join(limitations)
    locator_text = _json(receipt.get("locators", []))
    summary += (f" Source: {_json(inputs['filename'])}; import ID: {receipt['import_id']}; "
                f"source SHA-256: {receipt['source_sha256']}; snapshot receipt: {claimed}; "
                f"source query receipt: {receipt.get('query_receipt_sha256', claimed)}. "
                f"Row locators (bounded): {locator_text}. "
                f"Selection locator digest: {receipt.get('selected_rows_sha256', 'unavailable')}. {BOUNDARY}")
    return {"tool": CAPABILITY_ID, "operation": operation, "status": "success", "answer": summary,
            "boundary": BOUNDARY, "limitations": list(limitations), "query_receipt": receipt, "snapshot_sha256": inputs.get("snapshot_sha256")}
