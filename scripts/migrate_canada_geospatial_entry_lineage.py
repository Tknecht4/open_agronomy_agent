#!/usr/bin/env python3
"""Migrate bundled Canadian geospatial artifacts to per-source entry lineage.

The original v1 contract embedded the hash of the complete registry in every
lineage record and derived artifact. That made an unrelated source addition
invalidate all existing layers. This bounded migration adds a canonical hash
of each source's own registry entry and refreshes the derived manifest's
lineage hash. Existing acquisition-time registry hashes remain unchanged as
historical snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _entry_sha256(source: dict[str, Any]) -> str:
    payload = json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def migrate(manifest_path: Path, *, root: Path, apply: bool) -> dict[str, Any]:
    registry = json.loads(manifest_path.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    for source in registry.get("sources", []):
        runtime = source.get("runtime") if isinstance(source, dict) else None
        if not isinstance(runtime, dict) or runtime.get("status") != "bundled":
            continue
        source_id = str(source["id"])
        entry_sha256 = _entry_sha256(source)
        lineage_path = _resolve(root, runtime["lineage_path"])
        derived_manifest_path = _resolve(root, runtime["derived_manifest_path"])
        database_path = _resolve(root, runtime["derived_path"])
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        derived = json.loads(derived_manifest_path.read_text(encoding="utf-8"))
        previous = {
            "lineage": lineage.get("source_entry_sha256"),
            "derived_manifest": derived.get("source_entry_sha256"),
        }
        if apply:
            lineage["source_entry_sha256"] = entry_sha256
            lineage_path.write_text(json.dumps(lineage, indent=2) + "\n", encoding="utf-8")
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value_json) VALUES (?, ?)",
                    ("source_entry_sha256", json.dumps(entry_sha256)),
                )
                connection.commit()
            finally:
                connection.close()
            derived["source_entry_sha256"] = entry_sha256
            derived["lineage_sha256"] = _sha256(lineage_path)
            derived["output_bytes"] = database_path.stat().st_size
            derived["output_sha256"] = _sha256(database_path)
            derived_manifest_path.write_text(
                json.dumps(derived, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        changes.append(
            {
                "source_id": source_id,
                "source_entry_sha256": entry_sha256,
                "previous": previous,
                "changed": any(value != entry_sha256 for value in previous.values()),
            }
        )
    return {
        "schema_version": "open_agronomy_agent.geospatial_entry_lineage_migration.v1",
        "mode": "apply" if apply else "dry_run",
        "registry": str(manifest_path.relative_to(root)),
        "bundled_source_count": len(changes),
        "changed_source_count": sum(bool(item["changed"]) for item in changes),
        "sources": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/manifests/canada_geospatial_sources.json"
    )
    parser.add_argument("--apply", action="store_true", help="write the migration; default is dry-run")
    args = parser.parse_args()
    report = migrate(args.manifest.resolve(), root=ROOT, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
