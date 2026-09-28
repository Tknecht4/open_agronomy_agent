"""Lossless workspace source storage and explicit SQLite migration contracts."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tracemalloc
import zlib
from pathlib import Path

import pytest

from agronomy_agent.field_data import MAX_SOURCE_BYTES
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.field_data_store import commit_import, preview_import, query_import
from agronomy_agent.server.storage.field_source_blobs import BLOB, INLINE, migrate_sources, read_source

SOURCE = b"Field,Sample,Value\nA,one,2\nA,two,4\n"


def _field(store: TraceStore, workspace: str) -> dict:
    return store.create_phase4_field_context(
        workspace={"id": workspace, "organization_id": "org"},
        created_by_user_id="owner", payload={"display_name": workspace, "region_text": "Saskatchewan"},
    )


def _mapping() -> dict:
    return {"filters": {"Field": "A"}, "record_key": ["Sample"], "columns": [
        {"column": "Sample", "label": "Sample", "unit": None, "role": "identifier",
         "aggregation": "none", "evidence_role": "observation"},
        {"column": "Value", "label": "Value", "unit": "kg/ha", "role": "measurement",
         "aggregation": "mean", "evidence_role": "observation"},
    ], "source": {"title": "Test source"}}


def _row(store: TraceStore, import_id: str):
    return store._conn.execute("SELECT * FROM field_data_imports WHERE id = ?", (import_id,)).fetchone()


def test_new_previews_deduplicate_only_inside_workspace(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "sources.sqlite3")
    fields = [_field(store, "a"), _field(store, "a"), _field(store, "b")]
    ids = [preview_import(store, f, "owner", "source.csv", SOURCE)["import_id"] for f in fields]
    assert store._conn.execute("SELECT COUNT(*) FROM field_data_source_blobs").fetchone()[0] == 2
    assert {(_row(store, item)["workspace_id"], _row(store, item)["source_storage"]) for item in ids} == {
        ("a", BLOB), ("b", BLOB),
    }
    assert all(_row(store, item)["source_bytes"] == b"" for item in ids)
    assert all(read_source(store._conn.cursor(), _row(store, item)) == SOURCE for item in ids)
    receipts = []
    for field, item in zip(fields, ids):
        commit_import(store, field, item, _mapping())
        receipts.append(query_import(store, field["id"], item, {"operation": "mean", "column": "Value"}))
    assert [receipt["value"] for receipt in receipts] == [3, 3, 3]


def test_migration_preserves_receipts_and_is_reversible(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "sources.sqlite3")
    field = _field(store, "a")
    item = preview_import(store, field, "owner", "source.csv", SOURCE)["import_id"]
    commit_import(store, field, item, _mapping())
    store._conn.execute("UPDATE field_data_imports SET source_bytes = ?, source_storage = ? WHERE id = ?", (SOURCE, INLINE, item))
    store._conn.commit()
    before = query_import(store, field["id"], item, {"operation": "mean", "column": "Value"})
    dry = migrate_sources(store._conn)
    assert dry["applied"] is False and dry["rows_changed"] == 1
    assert _row(store, item)["source_storage"] == INLINE
    applied = migrate_sources(store._conn, apply=True)
    assert applied["rows_changed"] == 1 and _row(store, item)["source_bytes"] == b""
    assert query_import(store, field["id"], item, {"operation": "mean", "column": "Value"}) == before
    assert migrate_sources(store._conn, apply=True)["rows_changed"] == 0
    restored = migrate_sources(store._conn, apply=True, restore_inline=True)
    assert restored["rows_changed"] == 1 and _row(store, item)["source_bytes"] == SOURCE
    assert query_import(store, field["id"], item, {"operation": "mean", "column": "Value"}) == before
    assert migrate_sources(store._conn, apply=True, restore_inline=True)["rows_changed"] == 0


def test_old_schema_inline_import_upgrades_without_converting(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE field_data_imports (
        id TEXT PRIMARY KEY, field_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        actor_id TEXT NOT NULL, filename TEXT NOT NULL, source_bytes BLOB NOT NULL,
        source_sha256 TEXT NOT NULL, profile_json TEXT NOT NULL, status TEXT NOT NULL,
        mapping_json TEXT, mapping_sha256 TEXT, manifest_json TEXT,
        created_at TEXT NOT NULL, committed_at TEXT)""")
    conn.execute("""INSERT INTO field_data_imports
        (id, field_id, workspace_id, actor_id, filename, source_bytes, source_sha256,
         profile_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("legacy", "old-field", "a", "owner", "source.csv", SOURCE,
         hashlib.sha256(SOURCE).hexdigest(), "{}", "preview", "2026-01-01"))
    conn.commit()
    before_schema = list(conn.execute("PRAGMA table_info(field_data_imports)"))
    before_source = conn.execute("SELECT source_bytes, source_sha256 FROM field_data_imports WHERE id = 'legacy'").fetchone()
    dry = migrate_sources(conn)
    assert dry["rows_changed"] == 1
    assert [tuple(row) for row in conn.execute("PRAGMA table_info(field_data_imports)")] == before_schema
    assert tuple(conn.execute("SELECT source_bytes, source_sha256 FROM field_data_imports WHERE id = 'legacy'").fetchone()) == before_source
    root = Path(__file__).resolve().parents[1]
    cli = subprocess.run(
        [sys.executable, str(root / "scripts/migrate_field_source_blobs.py"), "--database", str(path)],
        cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
        check=True, capture_output=True, text=True,
    )
    assert json.loads(cli.stdout) == dry
    assert [tuple(row) for row in conn.execute("PRAGMA table_info(field_data_imports)")] == before_schema
    assert tuple(conn.execute("SELECT source_bytes, source_sha256 FROM field_data_imports WHERE id = 'legacy'").fetchone()) == before_source
    conn.close()
    store = TraceStore(path)
    assert _row(store, "legacy")["source_storage"] == INLINE
    assert read_source(store._conn.cursor(), _row(store, "legacy")) == SOURCE
    field = _field(store, "a")
    item = preview_import(store, field, "owner", "source.csv", SOURCE)["import_id"]
    store._conn.execute("UPDATE field_data_imports SET source_bytes = ?, source_storage = ? WHERE id = ?", (SOURCE, INLINE, item))
    store._conn.commit()
    assert _row(store, item)["source_storage"] == INLINE
    assert read_source(store._conn.cursor(), _row(store, item)) == SOURCE
    commit_import(store, field, item, _mapping())
    assert query_import(store, field["id"], item, {"operation": "count"})["value"] == 2


def test_cli_dry_run_reads_committed_wal_without_logical_changes(tmp_path: Path) -> None:
    path = tmp_path / "wal-sources.sqlite3"
    store = TraceStore(path)
    assert store._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    source_sha = hashlib.sha256(SOURCE).hexdigest()
    store._conn.execute(
        """INSERT INTO field_data_imports
        (id, field_id, workspace_id, actor_id, filename, source_bytes, source_sha256,
         profile_json, status, created_at) VALUES
        ('wal-import', 'field', 'workspace', 'owner', 'source.csv', ?, ?, '{}', 'preview', '2026-01-01')""",
        (SOURCE, source_sha),
    )
    store._conn.commit()
    assert path.with_name(path.name + "-wal").exists()
    before_schema = list(store._conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"))
    before_row = tuple(store._conn.execute(
        "SELECT source_bytes, source_storage, source_sha256 FROM field_data_imports WHERE id = 'wal-import'"
    ).fetchone())
    root = Path(__file__).resolve().parents[1]
    cli = subprocess.run(
        [sys.executable, str(root / "scripts/migrate_field_source_blobs.py"), "--database", str(path)],
        cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
        check=True, capture_output=True, text=True,
    )
    receipt = json.loads(cli.stdout)
    assert receipt["applied"] is False
    assert receipt["rows_scanned"] == receipt["rows_changed"] == 1
    assert receipt["verified_raw_bytes"] == len(SOURCE)
    assert receipt["source_inventory_sha256"] == hashlib.sha256(
        f"wal-import:workspace:{source_sha}".encode()
    ).hexdigest()
    assert "sidecars may be created" in receipt["dry_run_boundary"]
    assert list(store._conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")) == before_schema
    assert tuple(store._conn.execute(
        "SELECT source_bytes, source_storage, source_sha256 FROM field_data_imports WHERE id = 'wal-import'"
    ).fetchone()) == before_row


def test_corrupt_blob_and_unexpected_inline_bytes_fail_closed(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "sources.sqlite3")
    field = _field(store, "a")
    item = preview_import(store, field, "owner", "source.csv", SOURCE)["import_id"]
    commit_import(store, field, item, _mapping())
    store._conn.execute("UPDATE field_data_imports SET source_bytes = ? WHERE id = ?", (SOURCE, item))
    store._conn.commit()
    with pytest.raises(ValueError, match="unexpected inline"):
        query_import(store, field["id"], item, {"operation": "count"})
    store._conn.execute("UPDATE field_data_imports SET source_bytes = X'' WHERE id = ?", (item,))
    store._conn.execute("UPDATE field_data_source_blobs SET encoded_bytes = ?", (b"corrupt",))
    store._conn.commit()
    with pytest.raises(ValueError, match="blob size or checksum"):
        query_import(store, field["id"], item, {"operation": "count"})
    with pytest.raises(ValueError, match="blob size or checksum"):
        migrate_sources(store._conn, apply=True, restore_inline=True)
    assert _row(store, item)["source_storage"] == BLOB


def test_decompression_limit_and_unknown_formats_fail_closed(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "sources.sqlite3")
    field = _field(store, "a")
    item = preview_import(store, field, "owner", "source.csv", SOURCE)["import_id"]
    expanded = b"x" * (MAX_SOURCE_BYTES + 1)
    encoded = zlib.compress(expanded)
    store._conn.execute(
        "UPDATE field_data_source_blobs SET raw_size = ?, encoded_size = ?, encoded_sha256 = ?, encoded_bytes = ?",
        (len(SOURCE), len(encoded), hashlib.sha256(encoded).hexdigest(), encoded),
    )
    store._conn.commit()
    with pytest.raises(ValueError, match="decompression limit"):
        read_source(store._conn.cursor(), _row(store, item))
    store._conn.execute("UPDATE field_data_imports SET source_storage = 'future-v2' WHERE id = ?", (item,))
    store._conn.commit()
    with pytest.raises(ValueError, match="unknown source storage"):
        read_source(store._conn.cursor(), _row(store, item))


def test_conversion_rolls_back_on_later_corruption(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "sources.sqlite3")
    field = _field(store, "a")
    first = preview_import(store, field, "owner", "first.csv", SOURCE)["import_id"]
    second = preview_import(store, field, "owner", "second.csv", SOURCE + b"A,three,6\n")["import_id"]
    if first > second:
        first, second = second, first
        good = SOURCE + b"A,three,6\n"
    else:
        good = SOURCE
    store._conn.execute("UPDATE field_data_imports SET source_bytes = ?, source_storage = ? WHERE id = ?", (good, INLINE, first))
    store._conn.execute("UPDATE field_data_imports SET source_bytes = ?, source_storage = ? WHERE id = ?", (b"bad", INLINE, second))
    store._conn.commit()
    with pytest.raises(ValueError, match="source checksum"):
        migrate_sources(store._conn, apply=True)
    assert _row(store, first)["source_storage"] == INLINE
    assert _row(store, first)["source_bytes"] == good


def test_migration_peak_python_memory_does_not_scale_with_duplicate_payloads(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "many-inline.sqlite3")
    # A valid source of about 0.5 MiB repeated in 64 imports occupies over
    # 30 MiB inline. The migrator should retain only the current payload.
    source = b"Field,Sample,Value\n" + b"".join(
        f"A,{index},".encode() + b"x" * 30_000 + b"\n" for index in range(17)
    )
    source_sha = hashlib.sha256(source).hexdigest()
    count = 64
    store._conn.executemany(
        """INSERT INTO field_data_imports
        (id, field_id, workspace_id, actor_id, filename, source_bytes, source_sha256,
         profile_json, status, created_at) VALUES (?, 'field', 'workspace', 'owner',
         'source.csv', ?, ?, '{}', 'preview', '2026-01-01')""",
        ((f"{index:04d}", source, source_sha) for index in range(count)),
    )
    store._conn.commit()
    expected_inventory = hashlib.sha256("\n".join(
        f"{index:04d}:workspace:{source_sha}" for index in range(count)
    ).encode()).hexdigest()
    gc.collect()
    tracemalloc.start()
    try:
        receipt = migrate_sources(store._conn, apply=True)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024
    assert receipt["rows_scanned"] == receipt["rows_changed"] == count
    assert receipt["workspace_sources"] == 1
    assert receipt["verified_raw_bytes"] == count * len(source)
    assert receipt["source_inventory_sha256"] == expected_inventory
    assert store._conn.execute("SELECT COUNT(*) FROM field_data_source_blobs").fetchone()[0] == 1
