#!/usr/bin/env python3
"""Build the full historical NRCS corpus into portable, bounded source shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import (  # noqa: E402
    CORPUS_RELEASE_SCHEMA,
    canonical_json,
    normalized_text_sha256,
    quality_ledger_row,
    quality_ledger_status,
    sha256_bytes,
    sha256_text,
    source_locator_status,
)


DEFAULT_FULL_CORPUS = "data/derived/rag/nrcs_esd_rag_corpus.jsonl"
DEFAULT_RAW_INVENTORY = ROOT / "data" / "manifests" / "nrcs_full_raw_source_inventory_20260819.json"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "derived" / "rag" / "offline_agronomy" / "us_nrcs"
MAX_SHARD_BYTES = 16 * 1024 * 1024
RELEASE_ID = "us-nrcs-full-reference"


def _raw_hashes(inventory_path: Path) -> dict[str, str]:
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for item in payload.get("files") or []:
        relative = str(item.get("path") or "")
        if relative.endswith(".json") and "/._" not in relative and not Path(relative).name.startswith("._"):
            result[relative] = str(item.get("sha256") or "")
    if not result:
        raise ValueError("raw inventory contains no NRCS JSON file hashes")
    return result


def _portable_raw_path(value: str) -> str:
    marker = "data/raw/"
    position = value.replace("\\", "/").find(marker)
    if position < 0:
        raise ValueError(f"cannot derive portable raw locator from {value!r}")
    return value.replace("\\", "/")[position:]


def _manifest_path(path: Path) -> str:
    """Use a repo-relative path in production, without constraining test fixtures."""

    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_records(
    full_corpus: Path,
    raw_hashes: dict[str, str],
    *,
    near_duplicate_memberships: Mapping[str, str] | None = None,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    retained_normalized: set[str] = set()
    with full_corpus.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source = json.loads(line)
            text = str(source.get("text") or "").strip()
            if not text:
                continue
            extraction = source.get("extraction") if isinstance(source.get("extraction"), dict) else {}
            raw_relative_path = _portable_raw_path(str(extraction.get("raw_path") or ""))
            raw_sha256 = raw_hashes.get(raw_relative_path)
            if not raw_sha256:
                raise ValueError(f"raw hash not found for {raw_relative_path}")
            normalized = normalized_text_sha256(text)
            if normalized in retained_normalized:
                continue
            retained_normalized.add(normalized)
            doc_id = str(source.get("doc_id") or "")
            if not doc_id:
                raise ValueError(f"missing doc_id at full corpus line {line_number}")
            near_cluster = str((near_duplicate_memberships or {}).get(doc_id) or "none")
            record = {
            "doc_id": doc_id,
            "title": str(source.get("title") or "NRCS ecological-site context"),
            "text": text,
            "source": str(source.get("source") or "https://edit.sc.egov.usda.gov"),
            "source_id": "nrcs_edit_ecological_site_description_json",
            "publisher": "USDA NRCS Ecological Site Description Catalog",
            "source_type": "regional_environment_profile",
            "jurisdiction": ["United States"],
            "authority_tier": "US_government_reference",
            "rights_status": "US_government_public_source",
            "license": "us_government_public_source_with_citation",
            "retrieval_policy": "context_only",
            "transfer_scope": "US_analogue_context_only",
            "applicability_boundary": (
                "For Canadian questions this U.S. ecological-site material is labelled analogue context only. "
                "It cannot establish Canadian labels, legal authority, rates, thresholds, calibration, or field conditions."
            ),
            "knowledge_bucket": "regional_environment_context",
            "knowledge_domains": list(source.get("buckets") or ["regional_environment_context"]),
            "tags": list(source.get("tags") or []),
            "mlra": str(source.get("mlra") or ""),
            "ecological_site_id": str(source.get("ecological_site_id") or ""),
            "chunk_index": int(source.get("chunk_index") or 0),
            "raw_sha256": raw_sha256,
            "chunk_sha256": sha256_text(text),
            "source_locator": {
                "precision": "json_document_chunk",
                "archive_relative_path": raw_relative_path,
                "raw_sha256": raw_sha256,
                "source_url": str(source.get("download_url") or source.get("source") or ""),
                "extraction_method": "official_edit_json_historical_full_projection_v2",
                "json_document_id": str(source.get("ecological_site_id") or ""),
                "chunk_index": int(source.get("chunk_index") or 0),
                "chunk_text_sha256": sha256_text(text),
            },
            "quality": {
                "extraction_fidelity": "official_structured_json_with_document_and_chunk_locator",
                "language": "English",
                "authority_tier": "US_government_reference",
                "jurisdiction": "United States",
                "temporal_scope": "historical_archive_snapshot; currentness_not_inferred",
                "risk_class": "US_analogue_context_only",
                "retrieval_eligibility": "context_only",
                "source_offset_status": "historical_document_and_chunk_locator_no_original_char_span",
                "text_normalized_sha256": normalized,
                "duplicate_disposition": "retained_first_exact_normalized_text",
                "near_duplicate_method": "normalized_boundary_signature_v1(first_256_and_last_256_characters)",
                "near_duplicate_cluster_id": near_cluster,
                "near_duplicate_disposition": (
                    "split_retained_source_distinct" if near_cluster != "none" else "not_clustered"
                ),
            },
        }
            ledger = quality_ledger_row(
                record,
                corpus_path="",
                duplicate_cluster=normalized,
                duplicate_disposition="retained_first_exact_normalized_text",
            )
            yield record, ledger


def _near_duplicate_clusters(
    full_corpus: Path,
    raw_hashes: dict[str, str],
    *,
    progress_every: int = 0,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Find high-precision near-duplicate candidates without altering source text.

    The fixed method intentionally uses both normalized leading and trailing
    256-character windows.  It catches otherwise-identical extraction records
    that differ in a bounded middle span while avoiding a broad lexical merge
    of independently authored agronomic passages.  Exact normalized duplicates
    are already removed by ``_iter_records``.  Every detected cluster is kept
    as a split, source-distinct group until an evidence reviewer records a
    stronger merge decision.
    """

    groups: dict[str, list[str]] = {}
    for ordinal, (record, _ledger) in enumerate(_iter_records(full_corpus, raw_hashes), start=1):
        normalized = " ".join(str(record.get("text") or "").casefold().split())
        if len(normalized) < 512:
            continue
        signature = sha256_text(f"{normalized[:256]}\n{normalized[-256:]}")
        groups.setdefault(signature, []).append(str(record["doc_id"]))
        if progress_every and ordinal % progress_every == 0:
            print(json.dumps({"event": "near_duplicate_scanned", "rows": ordinal}), flush=True)
    memberships: dict[str, str] = {}
    clusters: list[dict[str, Any]] = []
    for sequence, signature in enumerate(sorted(key for key, values in groups.items() if len(values) > 1), start=1):
        cluster_id = f"nrcs-near-{sequence:06d}"
        members = sorted(groups[signature])
        memberships.update({member: cluster_id for member in members})
        clusters.append(
            {
                "cluster_id": cluster_id,
                "method": "normalized_boundary_signature_v1(first_256_and_last_256_characters)",
                "normalized_boundary_signature_sha256": signature,
                "member_doc_ids": members,
                "disposition": "split_retained_source_distinct",
                "reason": "Source-exact locators differ; no content is merged or removed by near-duplicate clustering.",
            }
        )
    return memberships, clusters


def _write_release(
    *,
    full_corpus: Path,
    raw_inventory: Path,
    output_root: Path,
    release_id: str,
    maximum_shard_bytes: int,
    progress_every: int = 5_000,
    resume: bool = False,
) -> dict[str, Any]:
    if output_root.exists() and not resume:
        shutil.rmtree(output_root)
    if resume and (output_root / "store_manifest.json").exists():
        raise ValueError("refusing to resume a release that already has a store manifest")
    print(json.dumps({"event": "build_started", "output_root": str(output_root), "resume": resume}), flush=True)
    shards_dir = output_root / "shards"
    raw_hashes = _raw_hashes(raw_inventory)
    near_duplicate_memberships, near_duplicate_clusters = _near_duplicate_clusters(
        full_corpus,
        raw_hashes,
        progress_every=progress_every,
    )
    print(
        json.dumps({"event": "near_duplicate_clusters", "clusters": len(near_duplicate_clusters)}),
        flush=True,
    )
    shard_index: list[dict[str, Any]] = []
    ledger_digest = hashlib.sha256()
    source_count: Counter[str] = Counter()
    mlra_shards: dict[str, set[str]] = {}
    total_rows = 0
    current_handle = None
    current_digest = None
    current_path: Path | None = None
    current_rows = 0
    current_bytes = 0

    def close_shard() -> None:
        nonlocal current_handle, current_digest, current_path, current_rows, current_bytes
        if current_handle is None or current_digest is None or current_path is None:
            return
        current_handle.close()
        shard_index.append(
            {
                "path": current_path.relative_to(output_root).as_posix(),
                "sha256": current_digest.hexdigest(),
                "rows": current_rows,
                "bytes": current_bytes,
                "retrieval_policy": "context_only",
            }
        )
        current_handle = None
        current_digest = None
        current_path = None
        current_rows = 0
        current_bytes = 0

    existing_paths = sorted(shards_dir.glob("nrcs-*.jsonl")) if resume else []
    for existing in existing_paths:
        # A killed foreground build can leave only the last buffered JSONL
        # fragment.  Trim that fragment before validating prior rows; do not
        # invent a repaired record.
        data = existing.read_bytes()
        if data and not data.endswith(b"\n"):
            last_newline = data.rfind(b"\n")
            with existing.open("r+b") as handle:
                handle.truncate(last_newline + 1 if last_newline >= 0 else 0)
            data = existing.read_bytes()
            print(json.dumps({"event": "truncated_incomplete_jsonl_fragment", "path": str(existing)}), flush=True)
        digest = hashlib.sha256(data).hexdigest()
        rows = 0
        for line_number, line in enumerate(data.splitlines(), start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed resumable JSONL in {existing}:{line_number}") from exc
            complete, status = source_locator_status(record.get("source_locator"))
            quality_complete, quality_status = quality_ledger_status(record)
            if not complete or not quality_complete:
                raise ValueError(f"invalid resumable row in {existing}:{line_number}:{status}:{quality_status}")
            rows += 1
            total_rows += 1
            source_count[str(record.get("source_id") or "")] += 1
            mlra = str(record.get("mlra") or "").strip().upper()
            if mlra:
                mlra_shards.setdefault(mlra, set()).add(existing.relative_to(output_root).as_posix())
            ledger = quality_ledger_row(
                record,
                corpus_path=existing.relative_to(output_root).as_posix(),
                duplicate_cluster=str((record.get("quality") or {}).get("text_normalized_sha256") or ""),
                duplicate_disposition=str((record.get("quality") or {}).get("duplicate_disposition") or ""),
            )
            ledger_digest.update((canonical_json(ledger) + "\n").encode("utf-8"))
        shard_index.append(
            {
                "path": existing.relative_to(output_root).as_posix(),
                "sha256": digest,
                "rows": rows,
                "bytes": len(data),
                "retrieval_policy": "context_only",
            }
        )
    if existing_paths:
        print(json.dumps({"event": "resume_validated", "rows": total_rows, "shards": len(existing_paths)}), flush=True)

    def open_shard(sequence: int) -> None:
        nonlocal current_handle, current_digest, current_path
        shards_dir.mkdir(parents=True, exist_ok=True)
        current_path = shards_dir / f"nrcs-{sequence:04d}.jsonl"
        current_handle = current_path.open("wb")
        current_digest = hashlib.sha256()

    sequence = len(existing_paths)
    source_ordinal = 0
    for record, ledger in _iter_records(
        full_corpus,
        raw_hashes,
        near_duplicate_memberships=near_duplicate_memberships,
    ):
        source_ordinal += 1
        if source_ordinal <= total_rows:
            continue
        serialized = (canonical_json(record) + "\n").encode("utf-8")
        if len(serialized) > maximum_shard_bytes:
            raise ValueError(f"record exceeds shard cap: {record['doc_id']}")
        if current_handle is None or current_bytes + len(serialized) > maximum_shard_bytes:
            close_shard()
            sequence += 1
            open_shard(sequence)
        assert current_handle is not None and current_digest is not None and current_path is not None
        current_handle.write(serialized)
        current_digest.update(serialized)
        current_rows += 1
        current_bytes += len(serialized)
        total_rows += 1
        if progress_every and total_rows % progress_every == 0:
            print(json.dumps({"event": "records_written", "rows": total_rows, "shards": sequence}), flush=True)
        source_count[str(record["source_id"])] += 1
        mlra = str(record.get("mlra") or "").strip().upper()
        if mlra:
            mlra_shards.setdefault(mlra, set()).add(current_path.relative_to(output_root).as_posix())
        ledger["corpus_path"] = current_path.relative_to(output_root).as_posix()
        ledger_digest.update((canonical_json(ledger) + "\n").encode("utf-8"))
    close_shard()
    ledger_payload = {
        "schema_version": "open_agronomy_agent.corpus_quality_ledger.v1",
        "release_id": release_id,
        "rows": total_rows,
        "source_locator_complete_rate": 1.0,
        "source_offset_precision_counts": {"json_document_chunk": total_rows},
        "duplicate_policy": "normalized_text_sha256; retain first occurrence in frozen source order",
        "near_duplicate_policy": (
            "Exact normalized duplicates are removed globally. High-precision normalized-boundary clusters are "
            "retained as source-distinct splits pending an evidence-specific merge decision."
        ),
        "per_row_ledger": {
            "storage": "embedded runtime row quality object plus source_locator",
            "required_fields": [
                "extraction_fidelity",
                "language",
                "authority_tier",
                "jurisdiction",
                "temporal_scope",
                "risk_class",
                "retrieval_eligibility",
                "duplicate_disposition",
                "near_duplicate_disposition",
            ],
        },
        "answer_evidence_policy": "No boilerplate-only NRCS records were admitted; exact source text remains source-bound.",
        "rows_sha256": ledger_digest.hexdigest(),
    }
    (output_root / "quality_ledger.json").write_text(json.dumps(ledger_payload, indent=2) + "\n", encoding="utf-8")
    near_duplicate_path = output_root / "near_duplicate_clusters.json"
    near_duplicate_payload = {
        "schema_version": "open_agronomy_agent.near_duplicate_clusters.v1",
        "release_id": release_id,
        "method": "normalized_boundary_signature_v1(first_256_and_last_256_characters)",
        "cluster_count": len(near_duplicate_clusters),
        "clusters": near_duplicate_clusters,
    }
    near_duplicate_payload["clusters_sha256"] = sha256_bytes(canonical_json(near_duplicate_payload).encode("utf-8"))
    near_duplicate_path.write_text(json.dumps(near_duplicate_payload, indent=2) + "\n", encoding="utf-8")
    store = {
        "schema_version": CORPUS_RELEASE_SCHEMA,
        "release_id": release_id,
        "source_inventory_path": "data/manifests/historical_archive_lexar_20260819.json",
        "raw_inventory_path": _manifest_path(raw_inventory),
        "source_full_corpus_sha256": sha256_bytes(full_corpus.read_bytes()),
        "raw_inventory_sha256": json.loads(raw_inventory.read_text(encoding="utf-8")).get("inventory_sha256"),
        "jurisdiction_policy": "US analogue context only for Canadian questions",
        "rights_status": "US_government_public_source",
        "rows": total_rows,
        "sources": dict(source_count),
        "mlra_shards": {key: sorted(value) for key, value in sorted(mlra_shards.items())},
        "shards": shard_index,
        "quality_ledger": {
            "path": "quality_ledger.json",
            "sha256": sha256_bytes((output_root / "quality_ledger.json").read_bytes()),
        },
        "near_duplicate_clusters": {
            "path": "near_duplicate_clusters.json",
            "sha256": sha256_bytes(near_duplicate_path.read_bytes()),
            "clusters": len(near_duplicate_clusters),
        },
    }
    store["store_sha256"] = sha256_bytes(canonical_json(store).encode("utf-8"))
    (output_root / "store_manifest.json").write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return store


def _finalize_existing_release(
    *,
    raw_inventory: Path,
    output_root: Path,
    release_id: str,
    maximum_shard_bytes: int,
    source_full_corpus_sha256: str,
) -> dict[str, Any]:
    """Validate prewritten shards before publishing their manifest.

    This is intentionally recovery-only: it never repairs or appends shard
    bytes.  Any malformed, oversized, or provenance-incomplete row fails the
    successor release rather than making an interrupted build look complete.
    """

    shards_dir = output_root / "shards"
    shard_paths = sorted(shards_dir.glob("context_only-*.jsonl"))
    if not shard_paths:
        raise ValueError("no prewritten shards to finalize")
    shard_index: list[dict[str, Any]] = []
    total_rows = 0
    source_count: Counter[str] = Counter()
    mlra_shards: dict[str, set[str]] = {}
    locator_complete = 0
    normalized_seen: set[str] = set()
    for path in shard_paths:
        if path.stat().st_size > maximum_shard_bytes:
            raise ValueError(f"shard exceeds cap: {path}")
        digest = hashlib.sha256()
        rows = 0
        with path.open("rb") as handle:
            for line_number, line in enumerate(handle, start=1):
                digest.update(line)
                if not line.endswith(b"\n"):
                    raise ValueError(f"unterminated JSONL line in {path}:{line_number}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"malformed JSONL in {path}:{line_number}") from exc
                if record.get("retrieval_policy") != "context_only":
                    raise ValueError(f"non-context record in {path}:{line_number}")
                complete, status = source_locator_status(record.get("source_locator"))
                if not complete:
                    raise ValueError(f"invalid source locator ({status}) in {path}:{line_number}")
                quality_complete, quality_status = quality_ledger_status(record)
                if not quality_complete:
                    raise ValueError(f"invalid quality ledger ({quality_status}) in {path}:{line_number}")
                normalized = normalized_text_sha256(str(record.get("text") or ""))
                if normalized in normalized_seen:
                    raise ValueError(f"exact normalized duplicate in {path}:{line_number}")
                normalized_seen.add(normalized)
                rows += 1
                total_rows += 1
                locator_complete += 1
                source_count[str(record.get("source_id") or "")] += 1
                mlra = str(record.get("mlra") or "").strip().upper()
                if mlra:
                    mlra_shards.setdefault(mlra, set()).add(path.relative_to(output_root).as_posix())
        shard_index.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "sha256": digest.hexdigest(),
                "rows": rows,
                "bytes": path.stat().st_size,
                "retrieval_policy": "context_only",
            }
        )
    raw_inventory_payload = json.loads(raw_inventory.read_text(encoding="utf-8"))
    ledger_payload = {
        "schema_version": "open_agronomy_agent.corpus_quality_ledger.v1",
        "release_id": release_id,
        "rows": total_rows,
        "source_locator_complete_rate": locator_complete / total_rows if total_rows else 0.0,
        "source_offset_precision_counts": {"json_document_chunk": total_rows},
        "duplicate_policy": "normalized_text_sha256; retain first occurrence in frozen source order",
        "answer_evidence_policy": "No boilerplate-only NRCS records were admitted; exact source text remains source-bound.",
        "verified_existing_shards": True,
    }
    ledger_path = output_root / "quality_ledger.json"
    ledger_path.write_text(json.dumps(ledger_payload, indent=2) + "\n", encoding="utf-8")
    store = {
        "schema_version": CORPUS_RELEASE_SCHEMA,
        "release_id": release_id,
        "source_inventory_path": "data/manifests/historical_archive_lexar_20260819.json",
        "raw_inventory_path": _manifest_path(raw_inventory),
        "source_full_corpus_sha256": source_full_corpus_sha256,
        "raw_inventory_sha256": raw_inventory_payload.get("inventory_sha256"),
        "jurisdiction_policy": "US analogue context only for Canadian questions",
        "rights_status": "US_government_public_source",
        "rows": total_rows,
        "sources": dict(source_count),
        "mlra_shards": {key: sorted(value) for key, value in sorted(mlra_shards.items())},
        "shards": shard_index,
        "quality_ledger": {
            "path": "quality_ledger.json",
            "sha256": sha256_bytes(ledger_path.read_bytes()),
        },
    }
    store["store_sha256"] = sha256_bytes(canonical_json(store).encode("utf-8"))
    (output_root / "store_manifest.json").write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return store


def _refresh_raw_inventory_binding(*, raw_inventory: Path, output_root: Path) -> dict[str, Any]:
    """Rebind a verified immutable release to a successor archive receipt.

    This recovery path is intentionally narrow: it cannot alter shard bytes,
    row counts, source corpus identity, or policy.  A full finalization and the
    runtime corpus audit remain the mechanisms that verify all rows/shards.
    """

    manifest_path = output_root / "store_manifest.json"
    store = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous_store_sha256 = str(store.pop("store_sha256", ""))
    if sha256_bytes(canonical_json(store).encode("utf-8")) != previous_store_sha256:
        raise ValueError("existing store manifest is not self-consistent")
    raw_payload = json.loads(raw_inventory.read_text(encoding="utf-8"))
    raw_sha = str(raw_payload.get("inventory_sha256") or "")
    if len(raw_sha) != 64:
        raise ValueError("raw source inventory is not hash-bound")
    store["raw_inventory_path"] = _manifest_path(raw_inventory)
    store["raw_inventory_sha256"] = raw_sha
    store["source_binding_refresh"] = {
        "mode": "manifest_only_after_full_shard_finalization",
        "previous_store_sha256": previous_store_sha256,
        "raw_inventory_sha256": raw_sha,
        "boundary": "Shard bytes, source corpus hash, rows, policies, and shard hashes are unchanged; this refresh does not claim a new build.",
    }
    store["store_sha256"] = sha256_bytes(canonical_json(store).encode("utf-8"))
    manifest_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True, help="mounted historical source archive")
    parser.add_argument("--full-corpus", default=DEFAULT_FULL_CORPUS)
    parser.add_argument("--raw-inventory", type=Path, default=DEFAULT_RAW_INVENTORY)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--release-id", default=RELEASE_ID)
    parser.add_argument("--maximum-shard-bytes", type=int, default=MAX_SHARD_BYTES)
    parser.add_argument("--progress-every", type=int, default=5_000)
    parser.add_argument("--resume", action="store_true", help="continue a manifest-less interrupted build")
    parser.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--refresh-raw-inventory-binding", action="store_true")
    parser.add_argument("--source-full-corpus-sha256", default="")
    args = parser.parse_args()
    full_corpus = args.archive_root.resolve(strict=True) / args.full_corpus
    if args.finalize_existing and args.refresh_raw_inventory_binding:
        raise ValueError("--finalize-existing and --refresh-raw-inventory-binding are mutually exclusive")
    if args.refresh_raw_inventory_binding:
        result = _refresh_raw_inventory_binding(
            raw_inventory=args.raw_inventory,
            output_root=args.output_root,
        )
    elif args.finalize_existing:
        source_sha = args.source_full_corpus_sha256.strip().lower()
        if len(source_sha) != 64:
            raise ValueError("--source-full-corpus-sha256 must be a SHA-256 digest when finalizing")
        result = _finalize_existing_release(
            raw_inventory=args.raw_inventory,
            output_root=args.output_root,
            release_id=args.release_id,
            maximum_shard_bytes=args.maximum_shard_bytes,
            source_full_corpus_sha256=source_sha,
        )
    else:
        result = _write_release(
            full_corpus=full_corpus,
            raw_inventory=args.raw_inventory,
            output_root=args.output_root,
            release_id=args.release_id,
            maximum_shard_bytes=args.maximum_shard_bytes,
            progress_every=args.progress_every,
            resume=args.resume,
        )
    from build_offline_bm25_statistics_index import write_index

    indexed = write_index(args.output_root / "store_manifest.json")
    result = indexed["store"]
    print(json.dumps({"output_root": str(args.output_root), "rows": result["rows"], "shards": len(result["shards"]), "store_sha256": result["store_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
