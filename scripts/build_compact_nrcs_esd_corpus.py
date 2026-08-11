#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "derived" / "rag" / "nrcs_esd_rag_corpus.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "nrcs_esd_rag_corpus_compact.jsonl"
DEFAULT_SUMMARY = ROOT / "data" / "derived" / "rag" / "nrcs_esd_compact_summary.json"

PRIORITY_TERMS = (
    "ecological site",
    "general information",
    "mlra notes",
    "physiographic",
    "climatic",
    "water features",
    "soil features",
    "soil texture",
    "drainage",
    "water table",
    "slope",
    "precipitation",
    "temperature",
    "plant community",
    "management",
)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def priority(row: dict[str, Any]) -> tuple[int, int]:
    text = " ".join([str(row.get("title", "")), str(row.get("text", ""))]).lower()
    score = sum(1 for term in PRIORITY_TERMS if term in text)
    # Keep early chunks when scores tie because they usually contain the site concept and MLRA context.
    return score, -int(row.get("chunk_index", 9999))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact NRCS ESD retrieval projection from the full JSON corpus.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--chunks-per-site", type=int, default=3)
    args = parser.parse_args()

    if args.chunks_per_site < 1:
        raise ValueError("--chunks-per-site must be at least 1")
    if not args.input.exists():
        raise FileNotFoundError(f"missing NRCS ESD corpus: {args.input}")

    input_rows = 0
    by_site: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            input_rows += 1
            row = json.loads(line)
            key = (str(row.get("mlra", "")), str(row.get("ecological_site_id", row.get("doc_id", ""))))
            candidates = by_site.setdefault(key, [])
            candidates.append(row)
            if len(candidates) > args.chunks_per_site * 4:
                by_site[key] = sorted(candidates, key=priority, reverse=True)[: args.chunks_per_site]

    compact: list[dict[str, Any]] = []
    for key in sorted(by_site):
        candidates = sorted(by_site[key], key=priority, reverse=True)
        selected = sorted(candidates[: args.chunks_per_site], key=lambda row: int(row.get("chunk_index", 9999)))
        for index, row in enumerate(selected, start=1):
            item = dict(row)
            item["retrieval_projection"] = "nrcs_esd_compact"
            item["compact_rank"] = index
            compact.append(item)

    write_jsonl(args.output, compact)
    summary = {
        "input_rows": input_rows,
        "output_rows": len(compact),
        "sites": len(by_site),
        "chunks_per_site": args.chunks_per_site,
        "output": str(args.output),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
