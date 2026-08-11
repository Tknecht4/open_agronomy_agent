#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "manifests" / "rag_corpus_expansion_sources.json"
DEFAULT_CORPORA = [
    ROOT / "data" / "seed" / "agronomy_rag_corpus.jsonl",
    ROOT / "data" / "seed" / "boundary_rag_corpus.jsonl",
    ROOT / "data" / "seed" / "cca_objective_rag_corpus.jsonl",
    ROOT / "data" / "derived" / "rag" / "soilwise_rag_corpus.jsonl",
    ROOT / "data" / "derived" / "rag" / "document_expansion_rag_corpus.jsonl",
    ROOT / "data" / "derived" / "rag" / "nrcs_esd_rag_corpus.jsonl",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize current and planned RAG corpus coverage by expansion bucket.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--target", type=int, default=150)
    parser.add_argument("--corpus", action="append", type=Path, default=[])
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    corpora = args.corpus or DEFAULT_CORPORA
    current = collections.Counter()
    current_sources = collections.defaultdict(set)
    for corpus in corpora:
        for row in read_jsonl(corpus):
            buckets = row.get("buckets") or row.get("tags") or []
            for bucket in buckets:
                if bucket in {item["id"] for item in manifest["buckets"]}:
                    current[bucket] += 1
                    current_sources[bucket].add(row.get("source_id") or row.get("source") or corpus.name)

    planned = collections.Counter()
    planned_sources = collections.defaultdict(list)
    for source in manifest["sources"]:
        expected = int(source.get("expected_chunks", 0))
        for bucket in source.get("buckets", []):
            planned[bucket] += expected
            planned_sources[bucket].append(source["id"])

    rows = []
    for bucket in [item["id"] for item in manifest["buckets"]]:
        rows.append(
            {
                "bucket": bucket,
                "current_chunks": current[bucket],
                "planned_chunks": planned[bucket],
                "target_chunks": args.target,
                "current_gap": max(0, args.target - current[bucket]),
                "planned_surplus": planned[bucket] - args.target,
                "planned_sources": len(planned_sources[bucket]),
            }
        )
    print(json.dumps({"target_chunks_per_bucket": args.target, "buckets": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
