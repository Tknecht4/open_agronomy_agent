#!/usr/bin/env python3
"""Build the bounded, source-linked production foundations context shard.

The checked-in text is project-authored synthesis. External source snapshots
are separately identified by URL and hash in the source registry; this builder
does not treat their pages as verbatim corpus text or decisive authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import (  # noqa: E402
    CORPUS_RELEASE_SCHEMA,
    canonical_json,
    normalized_text_sha256,
    quality_ledger_row,
    sha256_text,
    source_locator_status,
    write_jsonl,
)

DEFAULT_SEED = ROOT / "data/seed/production_foundations_v1.jsonl"
DEFAULT_SOURCES = ROOT / "data/manifests/production_foundations_sources_v1.json"
DEFAULT_OUTPUT = ROOT / "data/derived/rag/offline_agronomy/production_foundations/v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(seed_path: Path, sources_path: Path, output: Path) -> dict:
    seed_path = seed_path.resolve()
    sources_path = sources_path.resolve()
    output = output.resolve()
    if not seed_path.is_relative_to(ROOT) or not sources_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        raise ValueError("seed, source registry and output must be inside this repository")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty output: {output}")
    registry = json.loads(sources_path.read_text(encoding="utf-8"))
    sources = {str(row["source_id"]): row for row in registry["sources"]}
    if len(sources) != len(registry["sources"]):
        raise ValueError("duplicate source ID")
    for row in sources.values():
        if len(str(row.get("snapshot_sha256") or "")) != 64 or not row.get("url") or not row.get("rights"):
            raise ValueError(f"incomplete external source receipt: {row.get('source_id')}")
    raw_sha = sha256(seed_path)
    source_url = f"https://github.com/Tknecht4/open_agronomy_agent/blob/main/{seed_path.relative_to(ROOT).as_posix()}"
    records = []
    seen_ids = set()
    seen_texts = set()
    for index, line in enumerate(seed_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        item = json.loads(line)
        doc_id = str(item.get("doc_id") or "")
        content = str(item.get("text") or "").strip()
        support = item.get("supporting_source_ids") or []
        if not doc_id or doc_id in seen_ids or not content or not support or not set(support) <= set(sources):
            raise ValueError(f"invalid or duplicate seed record at line {index + 1}")
        if len(content) > 1800:
            raise ValueError(f"overlong summary card: {doc_id}")
        normalized = normalized_text_sha256(content)
        if normalized in seen_texts:
            raise ValueError(f"duplicate card text: {doc_id}")
        seen_ids.add(doc_id)
        seen_texts.add(normalized)
        record = {
            **item,
            "text": content,
            # These values are retrieval facets, not evidence authority. The
            # router's live farmer_knowledge lane admits applied_guidance;
            # the separate tier and policy below keep this synthesis contextual.
            "source_kind": "project_authored_source_linked_synthesis",
            "source_type": "applied_guidance",
            "knowledge_bucket": "farmer_knowledge",
            "knowledge_domains": sorted(set(item.get("knowledge_domains") or []) | {"farmer_knowledge"}),
            "authority_tier": "internal_synthesis",
            "rights_status": "project_authored",
            "license": "Apache-2.0_project_text_only",
            "retrieval_policy": "context_only",
            "raw_sha256": raw_sha,
            "chunk_sha256": sha256_text(content),
            "source_locator": {
                "precision": "json_document_chunk",
                "archive_relative_path": seed_path.relative_to(ROOT).as_posix(),
                "raw_sha256": raw_sha,
                "source_url": source_url,
                "extraction_method": "checked_in_project_summary_record_v1",
                "json_document_id": doc_id,
                "chunk_index": index,
                "chunk_text_sha256": sha256_text(content),
            },
            "quality": {
                "extraction_fidelity": "checked_in_project_summary_exact_hash_not_verbatim_external_source",
                "language": "English",
                "authority_tier": "internal_synthesis",
                "jurisdiction": "; ".join(item.get("jurisdiction") or []),
                "temporal_scope": "stable_method_summary; current farm and market inputs required",
                "risk_class": "context_only",
                "retrieval_eligibility": "context_only",
                "duplicate_disposition": "unique_normalized_text",
                "near_duplicate_disposition": "reviewed_small_card_set_not_clustered",
            },
        }
        if not source_locator_status(record["source_locator"])[0]:
            raise ValueError(f"incomplete source locator: {doc_id}")
        records.append(record)
    records.sort(key=lambda row: row["doc_id"])
    if not records:
        raise ValueError("no summary cards")
    output.mkdir(parents=True)
    shard_path = output / "shards/foundations-0001.jsonl"
    row_count, shard_hash, shard_bytes = write_jsonl(shard_path, records)
    ledger_path = output / "quality_ledger.json"
    ledger = [quality_ledger_row(row, corpus_path="shards/foundations-0001.jsonl", duplicate_cluster=normalized_text_sha256(row["text"]), duplicate_disposition="unique_normalized_text") for row in records]
    ledger_path.write_text(json.dumps({"schema_version": "open_agronomy_agent.corpus_quality_ledger.v1", "rows": ledger}, indent=2) + "\n", encoding="utf-8")
    receipt_path = output / "source_receipt.json"
    receipt_path.write_text(json.dumps({
        "schema_version": "open_agronomy_agent.production_foundations_source_receipt.v1",
        "seed_path": seed_path.relative_to(ROOT).as_posix(),
        "seed_sha256": raw_sha,
        "external_source_registry_path": sources_path.relative_to(ROOT).as_posix(),
        "external_source_registry_sha256": sha256(sources_path),
        "external_snapshots_in_public_package": False,
        "source_ids": sorted(sources),
        "rights_boundary": "Only project-authored summaries are distributed; source-specific terms remain with the publishers.",
    }, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": CORPUS_RELEASE_SCHEMA,
        "store_id": "production-foundations-v1",
        "profile": "source-linked-context-only",
        "shards": [{"path": "shards/foundations-0001.jsonl", "rows": row_count, "bytes": shard_bytes, "sha256": shard_hash, "retrieval_policies": ["context_only"]}],
        "row_count": row_count,
        "quality_ledger_path": "quality_ledger.json",
        "quality_ledger_sha256": sha256(ledger_path),
        "source_receipt_path": "source_receipt.json",
        "source_receipt_sha256": sha256(receipt_path),
        "authority_boundary": "Project-authored context only. No current price, field rate, legal authority, or local calibration.",
    }
    manifest["store_sha256"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    (output / "store_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build(args.seed, args.sources, args.output)
    print(json.dumps({"output": str(args.output), "rows": manifest["row_count"], "store_sha256": manifest["store_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
