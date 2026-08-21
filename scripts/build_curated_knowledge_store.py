#!/usr/bin/env python3
"""Build a deterministic, Git-suitable curated Canadian RAG store.

This command has no downloader.  It accepts only already extracted JSONL rows
whose source IDs are admitted by ``canada_agronomy_sources.json`` and whose
rights allow a distributable local-RAG bundle.  Raw documents and extraction
work directories are intentionally outside this command's output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.curated_knowledge_store import (  # noqa: E402
    DEFAULT_MAX_SHARD_BYTES,
    CuratedStoreError,
    build_curated_knowledge_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a hash-bound, policy-segregated curated knowledge store from "
            "pre-extracted JSONL. This command never downloads source material."
        )
    )
    parser.add_argument("--store-id", required=True, help="Versioned stable store identifier.")
    parser.add_argument(
        "--release-date",
        required=True,
        help="Explicit YYYY-MM-DD release date; no current timestamp is injected.",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=ROOT / "data" / "manifests" / "canada_agronomy_sources.json",
        help="Canadian source registry that provides rights and provenance gates.",
    )
    parser.add_argument(
        "--profile-spec",
        type=Path,
        required=True,
        help="Explicit core/extended profile source-ID contract.",
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        action="append",
        required=True,
        help="Pre-extracted source-aware JSONL; repeat for multiple input shards.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="New versioned output directory. It must not already exist.",
    )
    parser.add_argument(
        "--max-shard-bytes",
        type=int,
        default=DEFAULT_MAX_SHARD_BYTES,
        help="Maximum complete-record JSONL shard size (default: 24 MiB; cannot be raised).",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=ROOT,
        help="Optional root used only to make receipt path hints portable.",
    )
    parser.add_argument(
        "--rebind-semantic-companions",
        action="store_true",
        help=(
            "Repair legacy semantic-companion path/hash metadata only after exact reviewed "
            "record and parent-source agreement with the registry-pinned companion."
        ),
    )
    args = parser.parse_args()
    try:
        result = build_curated_knowledge_store(
            store_id=args.store_id,
            release_date=args.release_date,
            source_manifest_path=args.source_manifest,
            profile_spec_path=args.profile_spec,
            input_paths=args.input_jsonl,
            output_root=args.output_root,
            max_shard_bytes=args.max_shard_bytes,
            repository_root=args.repository_root,
            allow_semantic_rebind=args.rebind_semantic_companions,
        )
    except CuratedStoreError as exc:
        print(f"curated-store build failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "store_root": result["store_root"],
                "store_id": result["manifest"]["store_id"],
                "profiles": [
                    profile["profile_id"] for profile in result["manifest"]["profiles"]
                ],
                "shards": result["manifest"]["totals"]["shards"],
                "rows": result["manifest"]["totals"]["rows"],
                "validation": result["validation"]["status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
