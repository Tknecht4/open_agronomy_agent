"""Explicit, reversible SQLite field-source storage migration.

Dry run is the default and opens the database in SQLite read-only mode. It
preserves logical data, schema and source payloads; SQLite may create WAL/SHM
coordination sidecars. Apply converts inline imports to workspace-scoped
compressed blobs in one transaction. --restore-inline copies verified original
bytes back into import rows; it retains blob records. Back up the private
database with the normal operator backup procedure first.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from agronomy_agent.server.storage.field_source_blobs import migrate_sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Existing local SQLite database path")
    parser.add_argument("--apply", action="store_true", help="Commit the verified conversion (default: dry run)")
    parser.add_argument("--restore-inline", action="store_true", help="Reverse blob-backed rows to verified inline bytes")
    args = parser.parse_args()
    database = args.database.expanduser().resolve(strict=True)
    if not database.is_file():
        parser.error("database must be an existing SQLite file")
    if args.apply:
        connection = sqlite3.connect(database)
    else:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        receipt = migrate_sources(connection, restore_inline=args.restore_inline, apply=args.apply)
    finally:
        connection.close()
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
