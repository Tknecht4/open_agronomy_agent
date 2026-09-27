"""Private SQLite field-source bytes, scoped to one workspace and verified on every read.

``source_bytes`` is empty only for ``workspace-blob-v1``. Inline-v1 retains the
original bytes. The compressed representation is an internal storage detail;
source_sha256 always names the immutable original bytes.
"""

from __future__ import annotations

import hashlib
import sqlite3
import zlib
from typing import Any

from agronomy_agent.field_data import MAX_SOURCE_BYTES

INLINE = "inline-v1"
BLOB = "workspace-blob-v1"
CODEC = "zlib-v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_source_schema(cursor: sqlite3.Cursor) -> None:
    """Add the format marker without converting or deleting legacy payloads."""
    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(field_data_imports)")}
    if "source_storage" not in columns:
        cursor.execute("ALTER TABLE field_data_imports ADD COLUMN source_storage TEXT NOT NULL DEFAULT 'inline-v1'")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS field_data_source_blobs (
            workspace_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            codec TEXT NOT NULL,
            raw_size INTEGER NOT NULL,
            encoded_sha256 TEXT NOT NULL,
            encoded_size INTEGER NOT NULL,
            encoded_bytes BLOB NOT NULL,
            PRIMARY KEY (workspace_id, source_sha256)
        )"""
    )


def _decode(blob: Any, expected_sha: str) -> bytes:
    if blob["codec"] != CODEC:
        raise ValueError("unknown source blob codec")
    raw_size, encoded_size = blob["raw_size"], blob["encoded_size"]
    encoded = bytes(blob["encoded_bytes"])
    if (not isinstance(raw_size, int) or not 1 <= raw_size <= MAX_SOURCE_BYTES
            or not isinstance(encoded_size, int) or encoded_size != len(encoded)
            or encoded_size > MAX_SOURCE_BYTES + 4096
            or _sha(encoded) != blob["encoded_sha256"]):
        raise ValueError("stored source blob size or checksum mismatch")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(encoded, MAX_SOURCE_BYTES + 1)
        if (len(raw) > MAX_SOURCE_BYTES or not decoder.eof or decoder.unused_data
                or decoder.unconsumed_tail):
            raise ValueError("stored source decompression limit or framing mismatch")
        raw += decoder.flush()
    except zlib.error as exc:
        raise ValueError("stored source blob decompression failed") from exc
    if len(raw) != raw_size or _sha(raw) != expected_sha:
        raise ValueError("stored source checksum mismatch")
    return raw


def put_source_blob(cursor: sqlite3.Cursor, workspace_id: str, source_sha256: str, content: bytes) -> None:
    if not workspace_id or not 1 <= len(content) <= MAX_SOURCE_BYTES or _sha(content) != source_sha256:
        raise ValueError("stored source checksum or size mismatch")
    encoded = zlib.compress(content, level=6)
    cursor.execute(
        """INSERT OR IGNORE INTO field_data_source_blobs
        (workspace_id, source_sha256, codec, raw_size, encoded_sha256, encoded_size, encoded_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, source_sha256, CODEC, len(content), _sha(encoded), len(encoded), encoded),
    )
    blob = cursor.execute(
        "SELECT * FROM field_data_source_blobs WHERE workspace_id = ? AND source_sha256 = ?",
        (workspace_id, source_sha256),
    ).fetchone()
    if blob is None or _decode(blob, source_sha256) != content:
        raise ValueError("stored source blob collision or mismatch")


def read_source(cursor: sqlite3.Cursor, imported: Any) -> bytes:
    storage = imported["source_storage"] if "source_storage" in imported.keys() else INLINE
    inline = bytes(imported["source_bytes"])
    if storage == INLINE:
        if not 1 <= len(inline) <= MAX_SOURCE_BYTES or _sha(inline) != imported["source_sha256"]:
            raise ValueError("stored source checksum or size mismatch")
        return inline
    if storage != BLOB:
        raise ValueError("unknown source storage format")
    if inline:
        raise ValueError("blob-backed source has unexpected inline bytes")
    blob = cursor.execute(
        "SELECT * FROM field_data_source_blobs WHERE workspace_id = ? AND source_sha256 = ?",
        (imported["workspace_id"], imported["source_sha256"]),
    ).fetchone()
    if blob is None:
        raise ValueError("stored source blob missing")
    return _decode(blob, imported["source_sha256"])


def migrate_sources(conn: sqlite3.Connection, *, restore_inline: bool = False, apply: bool = False) -> dict[str, Any]:
    """Verify then convert every applicable row in one SQLite transaction.

    A dry run preserves logical data, schema and source payloads, including for
    an old schema. SQLite may create WAL/SHM coordination sidecars even for a
    read-only connection. Restore leaves blob records intact for inspection.
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        if cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='field_data_imports'").fetchone() is None:
            raise ValueError("field_data_imports table missing")
        if apply:
            ensure_source_schema(cursor)
        # Keyset scanning keeps only one payload in Python memory at a time.
        # Use a separate lookup per key so updates cannot disturb an active
        # SQLite result iterator over the same table.
        changed = 0
        rows_scanned = 0
        total_raw_bytes = 0
        inventory = hashlib.sha256()
        last_id: str | None = None
        while True:
            if last_id is None:
                identity = cursor.execute("SELECT id FROM field_data_imports ORDER BY id LIMIT 1").fetchone()
            else:
                identity = cursor.execute(
                    "SELECT id FROM field_data_imports WHERE id > ? ORDER BY id LIMIT 1", (last_id,),
                ).fetchone()
            if identity is None:
                break
            last_id = identity["id"]
            row = cursor.execute("SELECT * FROM field_data_imports WHERE id = ?", (last_id,)).fetchone()
            if row is None:
                raise ValueError("field source disappeared during migration")
            raw = read_source(cursor, row)
            if rows_scanned:
                inventory.update(b"\n")
            inventory.update(f"{row['id']}:{row['workspace_id']}:{row['source_sha256']}".encode())
            rows_scanned += 1
            total_raw_bytes += len(raw)
            storage = row["source_storage"] if "source_storage" in row.keys() else INLINE
            target = INLINE if restore_inline else BLOB
            if storage != target:
                changed += 1
                if apply:
                    if target == BLOB:
                        put_source_blob(cursor, row["workspace_id"], row["source_sha256"], raw)
                        cursor.execute("UPDATE field_data_imports SET source_bytes = X'', source_storage = ? WHERE id = ?", (BLOB, row["id"]))
                    else:
                        cursor.execute("UPDATE field_data_imports SET source_bytes = ?, source_storage = ? WHERE id = ?", (raw, INLINE, row["id"]))
                    updated = cursor.execute("SELECT * FROM field_data_imports WHERE id = ?", (row["id"],)).fetchone()
                    if read_source(cursor, updated) != raw:
                        raise ValueError("source migration verification failed")
                    del updated
            del raw, row
        workspace_sources = cursor.execute(
            """SELECT COUNT(*) FROM (
                SELECT workspace_id, source_sha256 FROM field_data_imports
                GROUP BY workspace_id, source_sha256
            )"""
        ).fetchone()[0]
        receipt = {
            "format": "field-source-migration-v1", "action": "restore-inline" if restore_inline else "to-workspace-blobs",
            "applied": apply, "rows_scanned": rows_scanned, "rows_changed": changed,
            "workspace_sources": workspace_sources, "verified_raw_bytes": total_raw_bytes,
            "source_inventory_sha256": inventory.hexdigest(),
            "dry_run_boundary": "No logical data, schema or source-payload changes; SQLite WAL/SHM sidecars may be created.",
        }
        if apply:
            conn.commit()
        else:
            conn.rollback()
        return receipt
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
