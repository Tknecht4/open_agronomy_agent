#!/usr/bin/env python3
"""Normalize active U.S. NRCS shard filenames without changing shard bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "data" / "derived" / "rag" / "offline_agronomy" / "us_nrcs" / "store_manifest.json"
ACTIVE_RELEASE_ID = "us-nrcs-full-reference"
_SEQUENCE = re.compile(r"(?:-|_)(\d{4})\.jsonl$")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize(store_path: Path) -> dict[str, Any]:
    store = json.loads(store_path.read_text(encoding="utf-8"))
    root = store_path.parent
    rename: dict[str, str] = {}
    for item in store.get("shards") or []:
        old = str(item.get("path") or "")
        match = _SEQUENCE.search(old)
        if not old or match is None:
            raise ValueError(f"unsupported shard path: {old!r}")
        new = f"shards/nrcs-{match.group(1)}.jsonl"
        if old != new:
            rename[old] = new
    for old, new in rename.items():
        source, target = root / old, root / new
        if not source.is_file():
            raise FileNotFoundError(source)
        if target.exists() and target != source:
            raise FileExistsError(target)
    for old, new in rename.items():
        (root / old).rename(root / new)
    for item in store.get("shards") or []:
        item["path"] = rename.get(str(item.get("path") or ""), str(item.get("path") or ""))
    store["mlra_shards"] = {
        key: [rename.get(str(value), str(value)) for value in values]
        for key, values in (store.get("mlra_shards") or {}).items()
    }
    store["active_shard_naming"] = "nrcs-NNNN.jsonl; stable development path; shard bytes unchanged"
    store["release_id"] = ACTIVE_RELEASE_ID
    store.pop("store_sha256", None)
    store["store_sha256"] = hashlib.sha256(_canonical(store).encode("utf-8")).hexdigest()
    store_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args()
    store = normalize(args.store)
    print(json.dumps({"store": str(args.store), "shards": len(store.get("shards") or []), "sha256": store["store_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
