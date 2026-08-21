#!/usr/bin/env python3
"""Build deterministic exact-token BM25 statistics for an offline JSONL store.

The index intentionally stores no duplicate source text.  It records exact
document lengths and per-shard document frequencies, so query-time BM25 uses
persisted statistics while loading only the shards selected by policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.agno_runtime.local_index import tokenize  # noqa: E402
from agronomy_agent.corpus_release import canonical_json  # noqa: E402


DEFAULT_STORE = ROOT / "data/derived/rag/offline_agronomy/us_nrcs/store_manifest.json"
INDEX_NAME = "bm25_statistics_index.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(store_path: Path) -> dict[str, Any]:
    store_path = store_path.resolve()
    store = json.loads(store_path.read_text(encoding="utf-8"))
    root = store_path.parent
    shard_entries: list[dict[str, Any]] = []
    for shard in store.get("shards") or []:
        relative = str(shard.get("path") or "")
        path = root / relative
        if not path.is_file() or _sha256(path) != str(shard.get("sha256") or ""):
            raise ValueError(f"shard failed hash validation: {path}")
        lengths: dict[str, int] = {}
        frequencies: Counter[str] = Counter()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            record = json.loads(line)
            doc_id = str(record.get("doc_id") or "")
            if not doc_id or doc_id in lengths:
                raise ValueError(f"missing or duplicate document id in {path}")
            tokens = tokenize(
                " ".join(
                    [
                        str(record.get("title") or ""),
                        str(record.get("mlra") or ""),
                        *[str(value) for value in record.get("tags") or ()],
                        str(record.get("text") or ""),
                    ]
                )
            )
            lengths[doc_id] = len(tokens)
            frequencies.update(set(tokens))
        shard_entries.append(
            {
                "path": relative,
                "shard_sha256": str(shard["sha256"]),
                "document_count": len(lengths),
                "average_token_count": (sum(lengths.values()) / len(lengths)) if lengths else 0.0,
                "document_token_counts": dict(sorted(lengths.items())),
                "document_frequencies": dict(sorted(frequencies.items())),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.offline_bm25_statistics.v1",
        "tokenizer": "agronomy_agent.agno_runtime.local_index.tokenize",
        "corpus_shard_set_sha256": hashlib.sha256(
            canonical_json(
                [
                    {"path": str(shard["path"]), "sha256": str(shard["sha256"])}
                    for shard in store.get("shards") or []
                ]
            ).encode("utf-8")
        ).hexdigest(),
        "shards": shard_entries,
    }
    payload["index_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


def write_index(store_path: Path) -> dict[str, Any]:
    """Write the index and rebind the self-hashed store manifest."""

    store_path = store_path.resolve()
    payload = build(store_path)
    index_path = store_path.parent / INDEX_NAME
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["bm25_statistics_index"] = {"path": INDEX_NAME, "sha256": _sha256(index_path)}
    store.pop("store_sha256", None)
    store["store_sha256"] = hashlib.sha256(canonical_json(store).encode("utf-8")).hexdigest()
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"index": index_path, "index_sha256": _sha256(index_path), "store": store}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args()
    result = write_index(args.store)
    print(json.dumps({"index": str(result["index"]), "sha256": result["index_sha256"], "store_sha256": result["store"]["store_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
