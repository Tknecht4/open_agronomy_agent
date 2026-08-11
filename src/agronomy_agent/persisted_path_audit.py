from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


PERSISTED_PATH_AUDIT_SCHEMA = "open_agronomy_agent.persisted_path_reference_audit.v1"
ABSOLUTE_PATH_RE = re.compile(
    r"^(?:/(?:Users|Volumes|private|var|tmp)(?:/|$)|[A-Za-z]:[\\/])"
)
ARRAY_INDEX_RE = re.compile(r"\[\d+\]")
SCANNED_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("turns", "system_state", True),
    ("turns", "trace", True),
    ("phase4_trace_events", "payload", True),
    ("phase4_exports", "storage_uri", False),
    ("phase4_exports", "metadata", True),
)


def _json_values(value: Any, *, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _json_values(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _json_values(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def _normalized_json_path(path: str) -> str:
    return ARRAY_INDEX_RE.sub("[]", path)


def _path_class(*, table: str, json_path: str) -> str:
    lowered = json_path.lower()
    if "model_identity" in lowered or lowered.endswith((".model_config_path", ".receipt_path")):
        return "model_identity"
    if lowered.endswith(".corpus_path"):
        return "corpus_lineage"
    if table == "phase4_exports" or "storage_uri" in lowered or ".files." in lowered:
        return "export_handle"
    return "other"


def open_read_only_database(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(2, "database file not found", str(resolved))
    return sqlite3.connect(f"file:{quote(str(resolved))}?mode=ro", uri=True)


def _contains_model_identity(value: Any) -> bool:
    if isinstance(value, dict):
        return "model_identity" in value or any(
            _contains_model_identity(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_model_identity(item) for item in value)
    return False


def audit_persisted_path_references(database_path: str | Path) -> dict[str, Any]:
    """Count absolute persisted paths without returning their private values."""
    target = Path(database_path)
    locations: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    affected_row_keys: set[tuple[str, str, int]] = set()
    model_identity_rows: set[tuple[str, int]] = set()
    scanned_rows: Counter[str] = Counter()
    malformed_json: Counter[str] = Counter()

    with open_read_only_database(target) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table, column, json_encoded in SCANNED_COLUMNS:
            if table not in tables:
                continue
            rows = connection.execute(
                f'SELECT rowid, "{column}" FROM "{table}"'  # fixed allow-listed identifiers
            ).fetchall()
            location = f"{table}.{column}"
            scanned_rows[location] += len(rows)
            for row_id, raw in rows:
                if raw in (None, ""):
                    continue
                row_classes: set[str] = set()
                if json_encoded:
                    try:
                        value = json.loads(raw) if isinstance(raw, str) else raw
                    except (TypeError, json.JSONDecodeError):
                        malformed_json[location] += 1
                        continue
                    if table == "turns" and _contains_model_identity(value):
                        model_identity_rows.add((table, int(row_id)))
                    values = _json_values(value)
                else:
                    values = (("$", str(raw)),)
                for json_path, value in values:
                    if not ABSOLUTE_PATH_RE.match(value):
                        continue
                    normalized = _normalized_json_path(json_path)
                    locations[f"{location}:{normalized}"] += 1
                    path_class = _path_class(table=table, json_path=normalized)
                    classes[path_class] += 1
                    row_classes.add(path_class)
                for path_class in row_classes:
                    affected_row_keys.add((table, path_class, int(row_id)))

    affected_rows = Counter(
        f"{table}:{path_class}"
        for table, path_class, _row_id in affected_row_keys
    )

    return {
        "schema_version": PERSISTED_PATH_AUDIT_SCHEMA,
        "database": {
            "filename": target.name,
            "opened_read_only": True,
            "absolute_path_included": False,
        },
        "absolute_path_reference_count": sum(locations.values()),
        "class_counts": dict(sorted(classes.items())),
        "affected_rows_by_table_class": dict(sorted(affected_rows.items())),
        "model_identity_turn_count": len(model_identity_rows),
        "locations": [
            {"location": location, "count": count}
            for location, count in sorted(locations.items())
        ],
        "scanned_rows": dict(sorted(scanned_rows.items())),
        "malformed_json_rows": dict(sorted(malformed_json.items())),
        "private_values_included": False,
    }
