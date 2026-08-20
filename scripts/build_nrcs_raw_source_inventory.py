#!/usr/bin/env python3
"""Derive the hash-bound raw NRCS source inventory from archive intake."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import canonical_json, sha256_bytes  # noqa: E402


DEFAULT_ARCHIVE_INVENTORY = ROOT / "data" / "manifests" / "historical_archive_lexar_20260819.json"
DEFAULT_OUTPUT = ROOT / "data" / "manifests" / "nrcs_full_raw_source_inventory_20260819.json"
RAW_PREFIX = "data/raw/documents/nrcs_esd_json/"


def build_raw_inventory(archive_inventory: Path) -> dict[str, object]:
    archive = json.loads(archive_inventory.read_text(encoding="utf-8"))
    files = []
    for entry in archive.get("files") or []:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "")
        if path.startswith(RAW_PREFIX) and path.endswith(".json") and not Path(path).name.startswith("._"):
            files.append({"path": path, "sha256": str(entry.get("sha256") or ""), "bytes": int(entry.get("bytes") or 0)})
    files.sort(key=lambda entry: str(entry["path"]))
    if not files or any(len(str(entry["sha256"])) != 64 for entry in files):
        raise ValueError("archive intake lacks complete raw NRCS JSON hash records")
    payload: dict[str, object] = {
        "schema_version": "open_agronomy_agent.raw_source_inventory.v1",
        "source_archive_inventory_path": "data/manifests/historical_archive_lexar_20260819.json",
        "source_archive_inventory_sha256": archive.get("inventory_sha256"),
        "source_prefix": RAW_PREFIX,
        "files": files,
    }
    payload["inventory_sha256"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-inventory", type=Path, default=DEFAULT_ARCHIVE_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_raw_inventory(args.archive_inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "files": len(payload["files"]), "inventory_sha256": payload["inventory_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
