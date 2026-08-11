from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from agronomy_agent.paths import minimized_path_reference
from agronomy_agent.persisted_path_audit import (
    ABSOLUTE_PATH_RE,
    SCANNED_COLUMNS,
    audit_persisted_path_references,
    open_read_only_database,
)


PERSISTED_PATH_MIGRATION_SCHEMA = (
    "open_agronomy_agent.persisted_path_reference_migration.v1"
)
OBJECT_KEY_ANCHORS = ("phase4", "phase6")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_object_reference(value: str) -> str:
    parts = Path(value).parts
    for anchor in OBJECT_KEY_ANCHORS:
        if anchor in parts:
            return Path(*parts[parts.index(anchor) :]).as_posix()
    return f"<legacy-object>/{Path(value).name}"


def _reference_class(*, table: str, json_path: str) -> str:
    lowered = json_path.lower()
    if "model_identity" in lowered or lowered.endswith(
        (".model_config_path", ".receipt_path")
    ):
        return "lineage"
    if lowered.endswith(".corpus_path"):
        return "lineage"
    if table == "phase4_exports" or "storage_uri" in lowered or ".files." in lowered:
        return "object"
    return "unsupported"


def _rewrite_json_value(
    value: Any,
    *,
    table: str,
    path: str = "$",
) -> tuple[Any, list[tuple[str, str]]]:
    replacements: list[tuple[str, str]] = []
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            rewritten[key], child = _rewrite_json_value(
                item,
                table=table,
                path=f"{path}.{key}",
            )
            replacements.extend(child)
        return rewritten, replacements
    if isinstance(value, list):
        rewritten_list: list[Any] = []
        for index, item in enumerate(value):
            rewritten_item, child = _rewrite_json_value(
                item,
                table=table,
                path=f"{path}[{index}]",
            )
            rewritten_list.append(rewritten_item)
            replacements.extend(child)
        return rewritten_list, replacements
    if not isinstance(value, str) or not ABSOLUTE_PATH_RE.match(value):
        return value, replacements

    reference_class = _reference_class(table=table, json_path=path)
    if reference_class == "lineage":
        return minimized_path_reference(value), [(path, reference_class)]
    if reference_class == "object":
        return _portable_object_reference(value), [(path, reference_class)]
    raise ValueError(f"unsupported absolute path location: {table}:{path}")


def _validate_export_artifacts(
    *,
    database: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    root = artifact_root.resolve()
    total = 0
    existing = 0
    hash_checked = 0
    errors: list[dict[str, str]] = []
    with sqlite3.connect(database) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "phase4_exports" not in tables:
            return {
                "status": "not_applicable",
                "artifact_root_name": root.name,
                "absolute_path_included": False,
                "file_count": 0,
                "existing_file_count": 0,
                "hash_checked_count": 0,
                "errors": [],
            }
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(phase4_exports)"
            ).fetchall()
        }
        identifier = '"id"' if "id" in columns else "rowid"
        rows = connection.execute(
            f"SELECT {identifier}, metadata FROM phase4_exports"
        ).fetchall()
    for export_id, raw_metadata in rows:
        try:
            metadata = json.loads(raw_metadata)
        except (TypeError, json.JSONDecodeError):
            errors.append(
                {"export_id": str(export_id), "file": "<metadata>", "error": "invalid_metadata"}
            )
            continue
        files = metadata.get("files") if isinstance(metadata, dict) else None
        manifest = metadata.get("file_manifest") if isinstance(metadata, dict) else None
        if not isinstance(files, dict):
            continue
        for filename, reference in sorted(files.items()):
            total += 1
            target = (root / str(reference)).resolve()
            if root != target and root not in target.parents:
                errors.append(
                    {"export_id": str(export_id), "file": str(filename), "error": "object_key_escape"}
                )
                continue
            if not target.is_file():
                errors.append(
                    {"export_id": str(export_id), "file": str(filename), "error": "missing"}
                )
                continue
            existing += 1
            record = manifest.get(filename) if isinstance(manifest, dict) else None
            expected_sha = record.get("sha256") if isinstance(record, dict) else None
            if expected_sha:
                hash_checked += 1
                if sha256_file(target) != str(expected_sha):
                    errors.append(
                        {"export_id": str(export_id), "file": str(filename), "error": "sha256_mismatch"}
                    )
    return {
        "status": "pass" if not errors else "fail",
        "artifact_root_name": root.name,
        "absolute_path_included": False,
        "file_count": total,
        "existing_file_count": existing,
        "hash_checked_count": hash_checked,
        "errors": errors,
    }


def migrate_persisted_path_references(
    *,
    source_database: str | Path,
    output_database: str | Path,
    expected_source_sha256: str,
    artifact_root: str | Path | None = None,
    require_artifacts: bool = False,
) -> dict[str, Any]:
    """Create a migrated copy while proving the source database was not changed."""
    source = Path(source_database).resolve()
    output = Path(output_database).resolve()
    if source == output:
        raise ValueError("source and output databases must differ")
    if output.exists():
        raise FileExistsError(output)
    if not source.is_file():
        raise FileNotFoundError(2, "source database not found", str(source))

    source_sha256_before = sha256_file(source)
    if source_sha256_before != expected_source_sha256:
        raise ValueError("source database SHA-256 does not match the expected value")
    before_audit = audit_persisted_path_references(source)
    unsupported = int(before_audit.get("class_counts", {}).get("other", 0))
    if unsupported:
        raise ValueError(
            f"source contains {unsupported} unsupported absolute path references"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    replacement_counts: dict[str, int] = {}
    changed_rows: set[tuple[str, int]] = set()
    try:
        with open_read_only_database(source) as source_connection:
            with sqlite3.connect(output) as output_connection:
                source_connection.backup(output_connection)

        with sqlite3.connect(output) as connection:
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
                    f'SELECT rowid, "{column}" FROM "{table}"'
                ).fetchall()
                for row_id, raw in rows:
                    if raw in (None, ""):
                        continue
                    if json_encoded:
                        try:
                            value = json.loads(raw) if isinstance(raw, str) else raw
                        except (TypeError, json.JSONDecodeError):
                            continue
                        rewritten, replacements = _rewrite_json_value(
                            value,
                            table=table,
                        )
                        next_raw = json.dumps(
                            rewritten,
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    else:
                        rewritten, replacements = _rewrite_json_value(
                            str(raw),
                            table=table,
                        )
                        next_raw = str(rewritten)
                    if not replacements:
                        continue
                    connection.execute(
                        f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?',
                        (next_raw, row_id),
                    )
                    changed_rows.add((table, int(row_id)))
                    for path, reference_class in replacements:
                        key = f"{table}.{column}:{path}:{reference_class}"
                        replacement_counts[key] = replacement_counts.get(key, 0) + 1
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            integrity_check = str(integrity[0]) if integrity else "missing"

        after_audit = audit_persisted_path_references(output)
        if int(after_audit["absolute_path_reference_count"]) != 0:
            raise ValueError("migrated database still contains absolute path references")
        if integrity_check != "ok":
            raise ValueError(f"migrated database integrity check failed: {integrity_check}")
        source_sha256_after = sha256_file(source)
        if source_sha256_after != source_sha256_before:
            raise RuntimeError("source database changed during copy-only migration")
        artifact_validation = (
            _validate_export_artifacts(
                database=output,
                artifact_root=Path(artifact_root),
            )
            if artifact_root is not None
            else {
                "status": "not_checked",
                "absolute_path_included": False,
                "errors": [],
            }
        )
        if require_artifacts and artifact_validation["status"] != "pass":
            raise ValueError("migrated export artifact validation failed")

        return {
            "schema_version": PERSISTED_PATH_MIGRATION_SCHEMA,
            "source": {
                "filename": source.name,
                "sha256_before": source_sha256_before,
                "sha256_after": source_sha256_after,
                "unchanged": True,
                "opened_read_only": True,
                "absolute_path_included": False,
            },
            "output": {
                "filename": output.name,
                "sha256": sha256_file(output),
                "sqlite_integrity_check": integrity_check,
                "absolute_path_included": False,
            },
            "before_audit": before_audit,
            "after_audit": after_audit,
            "changed_row_count": len(changed_rows),
            "replacement_count": sum(replacement_counts.values()),
            "replacements": [
                {"location": key, "count": count}
                for key, count in sorted(replacement_counts.items())
            ],
            "artifact_bytes_copied": False,
            "artifact_validation": artifact_validation,
            "operational_boundary": (
                "The migrated database retains root-relative phase4/phase6 object "
                "keys and must be paired with the same private artifact root."
            ),
        }
    except Exception:
        output.unlink(missing_ok=True)
        raise
