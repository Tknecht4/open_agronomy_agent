#!/usr/bin/env python3
"""Build the source-exact, stable-path offline corpus used by development.

The builder intentionally does not copy legacy retrieval chunks into a new
schema.  Canadian prose is re-extracted from the archived raw PDF page that
was previously admitted, Ontario data is reconstructed as table records from
the raw workbook, and project/ontology records retain an exact hash of their
checked-in source artifact.  Records that cannot be regenerated from an
identified raw artifact are left out of the active product and remain
historical evidence only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

import fitz


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import (  # noqa: E402
    CORPUS_RELEASE_SCHEMA,
    canonical_json,
    normalized_text_sha256,
    quality_ledger_row,
    sha256_text,
    shard_records,
    write_jsonl,
)


DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "offline_agronomy" / "active"
MAX_SHARD_BYTES = 16 * 1024 * 1024
_PAGE = re.compile(r"\[page\s+(\d+)\]", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(value: str) -> str:
    return _SPACE.sub(" ", value).strip().casefold()


def _portable_archive_path(path: Path, archive: Path) -> str:
    return path.relative_to(archive).as_posix()


def _legacy_canadian_rows() -> list[dict[str, Any]]:
    paths = (
        ROOT / "data/derived/rag/curated_canada/releases/2026-08-14/shards/context_only-canada-offline-master-0001.jsonl",
        ROOT / "data/derived/rag/curated_canada/releases/2026-08-14/shards/requires_live_authority-canada-offline-master-0001.jsonl",
    )
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _raw_by_hash(archive: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in archive.glob("data/raw/**/*"):
        if not path.is_file() or path.name.startswith("._"):
            continue
        # Only raw source types used by the present Canadian corpus need to
        # be hashed.  This keeps the rebuild bounded while the separate intake
        # receipt inventories every archive file.
        if path.suffix.lower() not in {".pdf", ".xlsx"}:
            continue
        result.setdefault(_sha256(path), path)
    return result


def _source_metadata(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("source_id") or "")].append(row)
    metadata: dict[str, dict[str, Any]] = {}
    for source_id, source_rows in grouped.items():
        first = source_rows[0]
        lineage = first.get("lineage") if isinstance(first.get("lineage"), dict) else {}
        metadata[source_id] = {
            "source_id": source_id,
            "source": str(first.get("source") or lineage.get("canonical_url") or ""),
            "download_url": str(first.get("download_url") or lineage.get("download_url") or first.get("source") or ""),
            "publisher": str(first.get("publisher") or ""),
            "source_type": str(first.get("source_type") or "extension_document"),
            "jurisdiction": list(first.get("jurisdiction") or first.get("region") or []),
            "license": str(first.get("license") or (first.get("license_snapshot") or {}).get("status") or ""),
            "license_snapshot": first.get("license_snapshot") or lineage.get("license_snapshot") or {},
            "raw_sha256": str(lineage.get("raw_sha256") or ""),
            "requires_live_authority": any(
                str(row.get("retrieval_policy") or "") == "requires_live_authority" for row in source_rows
            ),
            "tags": sorted({str(tag) for row in source_rows for tag in row.get("tags") or []}),
            "buckets": sorted({str(tag) for row in source_rows for tag in row.get("buckets") or []}),
            "legacy_rows": source_rows,
        }
    return metadata


def _page_candidates(rows: Iterable[dict[str, Any]], pages: list[str]) -> set[int]:
    """Select only raw pages anchored by legacy admitted records.

    A source page is selected when a 12-token normalized excerpt from a legacy
    chunk occurs in its raw page text.  The resulting runtime text is the raw
    page text itself; legacy chunks never become evidence records by copy.
    """

    selected: set[int] = set()
    normalized_pages = [_normalize(value) for value in pages]
    for row in rows:
        words = _normalize(_PAGE.sub(" ", str(row.get("text") or ""))).split()
        anchors = [" ".join(words[offset : offset + 12]) for offset in (0, len(words) // 3, (2 * len(words)) // 3)]
        anchors = [anchor for anchor in anchors if len(anchor.split()) == 12]
        page_numbers = [int(value) - 1 for value in _PAGE.findall(str(row.get("text") or ""))]
        candidate_indexes = [index for index in page_numbers if 0 <= index < len(pages)] or list(range(len(pages)))
        for index in candidate_indexes:
            if any(anchor in normalized_pages[index] for anchor in anchors):
                selected.add(index)
    return selected


def _chunk_page_text(text: str, *, words_per_chunk: int = 200) -> list[tuple[int, int, str]]:
    """Return exact contiguous character spans, respecting page text order."""

    matches = list(re.finditer(r"\S+", text))
    result: list[tuple[int, int, str]] = []
    for start_index in range(0, len(matches), words_per_chunk):
        group = matches[start_index : start_index + words_per_chunk]
        if not group:
            continue
        start, end = group[0].start(), group[-1].end()
        value = text[start:end].strip()
        if len(_normalize(value)) >= 24:
            result.append((start, end, value))
    return result


def _canadian_pdf_records(archive: Path, metadata: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_by_hash = _raw_by_hash(archive)
    records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for source_id, item in sorted(metadata.items()):
        raw_path = raw_by_hash.get(str(item["raw_sha256"]))
        if raw_path is None or raw_path.suffix.lower() != ".pdf":
            continue
        document = fitz.open(raw_path)
        pages = [page.get_text("text") for page in document]
        selected = _page_candidates(item["legacy_rows"], pages)
        if not selected:
            continue
        policy = "requires_live_authority" if item["requires_live_authority"] else "context_only"
        sources.append(
            {
                "source_id": source_id,
                "archive_relative_path": _portable_archive_path(raw_path, archive),
                "raw_sha256": item["raw_sha256"],
                "source_url": item["download_url"],
                "selected_pages": [number + 1 for number in sorted(selected)],
                "extraction_method": "pymupdf_page_text_v1",
                "legacy_chunk_count": len(item["legacy_rows"]),
            }
        )
        for page_index in sorted(selected):
            page_text = pages[page_index]
            page_sha = sha256_text(page_text)
            for chunk_index, (start, end, text) in enumerate(_chunk_page_text(page_text), start=1):
                records.append(
                    {
                        "doc_id": f"{source_id}:page-{page_index + 1}:chunk-{chunk_index}",
                        "title": f"{source_id} — page {page_index + 1}, excerpt {chunk_index}",
                        "text": text,
                        "source": item["source"],
                        "source_id": source_id,
                        "publisher": item["publisher"],
                        "source_type": item["source_type"],
                        "jurisdiction": item["jurisdiction"],
                        "authority_tier": "Canadian_official_or_provincial_source",
                        "rights_status": item["license"],
                        "license": item["license"],
                        "license_snapshot": item["license_snapshot"],
                        "retrieval_policy": policy,
                        "knowledge_bucket": "canadian_official_guidance",
                        "knowledge_domains": item["buckets"],
                        "tags": item["tags"],
                        "raw_sha256": item["raw_sha256"],
                        "chunk_sha256": sha256_text(text),
                        "source_locator": {
                            "precision": "page_char_span",
                            "archive_relative_path": _portable_archive_path(raw_path, archive),
                            "raw_sha256": item["raw_sha256"],
                            "source_url": item["download_url"],
                            "extraction_method": "pymupdf_page_text_v1",
                            "page": page_index + 1,
                            "char_start": start,
                            "char_end": end,
                            "page_text_sha256": page_sha,
                        },
                        "quality": {
                            "extraction_fidelity": "raw_pdf_page_text_exact_character_span",
                            "language": "English",
                            "authority_tier": "Canadian_official_or_provincial_source",
                            "jurisdiction": "; ".join(item["jurisdiction"]),
                            "temporal_scope": "source_publication_snapshot; live authority policy retained separately",
                            "risk_class": "requires_live_authority" if policy == "requires_live_authority" else "context_only",
                            "retrieval_eligibility": policy,
                            "duplicate_disposition": "pending_global_deduplication",
                            "near_duplicate_disposition": "pending_global_near_duplicate_clustering",
                        },
                    }
                )
    return records, sources


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read(path))
    return ["".join(value.itertext()) for value in root.findall(f"{_XML_NS}si")]


def _xlsx_records(archive_root: Path, metadata: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for source_id, item in sorted(metadata.items()):
        if source_id != "on_field_crop_production_current":
            continue
        raw_path = next(
            (
                path
                for path in archive_root.glob("data/raw/**/*.xlsx")
                if not path.name.startswith("._") and _sha256(path) == item["raw_sha256"]
            ),
            None,
        )
        if raw_path is None:
            continue
        with zipfile.ZipFile(raw_path) as workbook:
            shared = _xlsx_shared_strings(workbook)
            worksheet_paths = sorted(path for path in workbook.namelist() if path.startswith("xl/worksheets/sheet") and path.endswith(".xml"))
            for sheet_number, path in enumerate(worksheet_paths, start=1):
                root = ElementTree.fromstring(workbook.read(path))
                rows: list[list[tuple[int, str]]] = []
                for row in root.findall(f".//{_XML_NS}row"):
                    cells: list[tuple[int, str]] = []
                    for cell in row.findall(f"{_XML_NS}c"):
                        reference = str(cell.get("r") or "A1")
                        column_letters = re.match(r"[A-Z]+", reference)
                        if not column_letters:
                            continue
                        column = 0
                        for character in column_letters.group(0):
                            column = column * 26 + ord(character) - ord("A") + 1
                        cell_type = cell.get("t")
                        value_node = cell.find(f"{_XML_NS}v")
                        inline = cell.find(f"{_XML_NS}is")
                        raw_value = "" if value_node is None else str(value_node.text or "")
                        if cell_type == "s" and raw_value.isdigit() and int(raw_value) < len(shared):
                            value = shared[int(raw_value)]
                        elif cell_type == "inlineStr" and inline is not None:
                            value = "".join(inline.itertext())
                        else:
                            value = raw_value
                        if value.strip():
                            cells.append((column, value.strip()))
                    if cells:
                        rows.append(cells)
                if len(rows) < 2:
                    continue
                headers = [value for _column, value in rows[0]]
                for row_number, cells in enumerate(rows[1:], start=2):
                    values = "; ".join(f"{headers[index] if index < len(headers) else f'column_{column}'}: {value}" for index, (column, value) in enumerate(cells))
                    if len(_normalize(values)) < 24:
                        continue
                    result.append(
                        {
                            "doc_id": f"{source_id}:sheet-{sheet_number}:row-{row_number}",
                            "title": f"Ontario field crop production workbook — sheet {sheet_number}, row {row_number}",
                            "text": values,
                            "source": item["source"],
                            "source_id": source_id,
                            "publisher": item["publisher"],
                            "source_type": "structured_table",
                            "jurisdiction": item["jurisdiction"],
                            "authority_tier": "Canadian_official_or_provincial_source",
                            "rights_status": item["license"],
                            "license": item["license"],
                            "license_snapshot": item["license_snapshot"],
                            "retrieval_policy": "context_only",
                            "knowledge_bucket": "canadian_official_guidance",
                            "knowledge_domains": item["buckets"],
                            "tags": item["tags"],
                            "raw_sha256": item["raw_sha256"],
                            "chunk_sha256": sha256_text(values),
                            "source_locator": {
                                "precision": "table_cells",
                                "archive_relative_path": _portable_archive_path(raw_path, archive_root),
                                "raw_sha256": item["raw_sha256"],
                                "source_url": item["download_url"],
                                "extraction_method": "xlsx_xml_table_rows_v1",
                                "table_title": f"sheet-{sheet_number}",
                                "column_headers": headers,
                                "cells": [{"row": row_number, "column": column - 1} for column, _value in cells],
                            },
                            "quality": {
                                "extraction_fidelity": "raw_xlsx_structured_cell_projection",
                                "language": "English",
                                "authority_tier": "Canadian_official_or_provincial_source",
                                "jurisdiction": "; ".join(item["jurisdiction"]),
                                "temporal_scope": "workbook_snapshot",
                                "risk_class": "context_only",
                                "retrieval_eligibility": "context_only",
                                "duplicate_disposition": "pending_global_deduplication",
                                "near_duplicate_disposition": "pending_global_near_duplicate_clustering",
                            },
                        }
                    )
        sources.append(
            {
                "source_id": source_id,
                "archive_relative_path": _portable_archive_path(raw_path, archive_root),
                "raw_sha256": item["raw_sha256"],
                "source_url": item["download_url"],
                "extraction_method": "xlsx_xml_table_rows_v1",
            }
        )
    return result, sources


def _project_records(path: Path, *, evidence_tier: str, eligibility: str, source_kind: str) -> list[dict[str, Any]]:
    raw_sha = _sha256(path)
    source_url = f"https://github.com/Tknecht4/open_agronomy_agent/blob/main/{path.relative_to(ROOT).as_posix()}"
    records: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        source = json.loads(line)
        text = str(source.get("text") or "").strip()
        if not text:
            continue
        source_id = str(source.get("source_id") or source_kind)
        records.append(
            {
                **source,
                "doc_id": str(source.get("doc_id") or f"{source_kind}:{index + 1}"),
                "text": text,
                "source_id": source_id,
                "authority_tier": evidence_tier,
                "rights_status": "project_authored" if source_kind != "soilwise" else "CC-BY-4.0",
                "jurisdiction": list(source.get("jurisdiction") or ["not_jurisdiction_specific"]),
                "retrieval_policy": eligibility,
                "raw_sha256": raw_sha,
                "chunk_sha256": sha256_text(text),
                "source_locator": {
                    "precision": "json_document_chunk",
                    "archive_relative_path": path.relative_to(ROOT).as_posix(),
                    "raw_sha256": raw_sha,
                    "source_url": str(source.get("source") if source_kind == "soilwise" else source_url),
                    "extraction_method": "checked_in_jsonl_record_v1",
                    "json_document_id": str(source.get("doc_id") or f"{source_kind}:{index + 1}"),
                    "chunk_index": index,
                    "chunk_text_sha256": sha256_text(text),
                },
                "quality": {
                    "extraction_fidelity": "checked_in_source_record_exact_hash",
                    "language": "English",
                    "authority_tier": evidence_tier,
                    "jurisdiction": "; ".join(source.get("jurisdiction") or ["not_jurisdiction_specific"]),
                    "temporal_scope": "repository_source_snapshot",
                    "risk_class": eligibility,
                    "retrieval_eligibility": eligibility,
                    "duplicate_disposition": "pending_global_deduplication",
                    "near_duplicate_disposition": "pending_global_near_duplicate_clustering",
                },
            }
        )
    return records


def _deduplicate(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = list(records)
    kept: list[dict[str, Any]] = []
    clusters: dict[str, list[str]] = defaultdict(list)
    for record in sorted(records, key=lambda value: (str(value.get("source_id")), str(value.get("doc_id")))):
        normalized = normalized_text_sha256(str(record.get("text") or ""))
        clusters[normalized].append(str(record.get("doc_id") or ""))
    for normalized, members in sorted(clusters.items()):
        winner = sorted(members)[0]
        for record in records:
            if str(record.get("doc_id")) != winner:
                continue
            record = dict(record)
            quality = dict(record["quality"])
            quality["duplicate_disposition"] = "retained_first_exact_normalized_text"
            quality["near_duplicate_disposition"] = "not_clustered"
            record["quality"] = quality
            kept.append(record)
            break
    cluster_rows = [
        {
            "cluster_id": f"exact-{index:06d}",
            "normalized_text_sha256": normalized,
            "member_doc_ids": sorted(members),
            "disposition": "retained_first_exact_normalized_text",
            "retained_doc_id": sorted(members)[0],
        }
        for index, (normalized, members) in enumerate(sorted(clusters.items()), start=1)
        if len(members) > 1
    ]
    return sorted(kept, key=lambda value: str(value["doc_id"])), cluster_rows


def _write_component(output: Path, name: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    for index, shard in enumerate(shard_records(records, maximum_bytes=MAX_SHARD_BYTES), start=1):
        path = output / "shards" / f"{name}-{index:04d}.jsonl"
        rows, digest, size = write_jsonl(path, shard)
        policies = {str(row.get("retrieval_policy") or "") for row in shard}
        shards.append({"path": path.relative_to(output).as_posix(), "rows": rows, "bytes": size, "sha256": digest, "retrieval_policies": sorted(policies)})
    return shards


def build(*, archive: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    rows = _legacy_canadian_rows()
    metadata = _source_metadata(rows)
    canadian, pdf_sources = _canadian_pdf_records(archive, metadata)
    tables, table_sources = _xlsx_records(archive, metadata)
    project = _project_records(ROOT / "data/seed/agronomy_rag_corpus.jsonl", evidence_tier="internal_synthesis", eligibility="context_only", source_kind="project_seed")
    boundary = _project_records(ROOT / "data/seed/boundary_rag_corpus.jsonl", evidence_tier="project_safety_policy", eligibility="decisive", source_kind="project_boundary")
    soilwise = _project_records(ROOT / "data/derived/rag/soilwise_rag_corpus.jsonl", evidence_tier="open_ontology", eligibility="context_only", source_kind="soilwise")
    components = {
        "canadian_context": [row for row in [*canadian, *tables] if row["retrieval_policy"] == "context_only"],
        "canadian_live": [row for row in canadian if row["retrieval_policy"] == "requires_live_authority"],
        "project_context": project,
        "project_decisive": boundary,
        "soilwise_context": soilwise,
    }
    all_records, exact_clusters = _deduplicate(record for records in components.values() for record in records)
    by_component: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_ids = {str(record["doc_id"]): record for record in all_records}
    for name, records in components.items():
        by_component[name] = [all_ids[str(record["doc_id"])] for record in records if str(record["doc_id"]) in all_ids]
    shards = [entry for name in sorted(by_component) for entry in _write_component(output, name, by_component[name])]
    ledger: list[dict[str, Any]] = []
    for shard in shards:
        path = output / shard["path"]
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            ledger.append(quality_ledger_row(record, corpus_path=shard["path"], duplicate_cluster=normalized_text_sha256(record["text"]), duplicate_disposition=record["quality"]["duplicate_disposition"]))
    ledger_path = output / "quality_ledger.json"
    ledger_path.write_text(json.dumps({"schema_version": "open_agronomy_agent.corpus_quality_ledger.v1", "rows": ledger}, indent=2) + "\n", encoding="utf-8")
    clusters_path = output / "exact_duplicate_clusters.json"
    clusters_path.write_text(json.dumps({"schema_version": "open_agronomy_agent.corpus_exact_duplicate_clusters.v1", "clusters": exact_clusters}, indent=2) + "\n", encoding="utf-8")
    source_receipt = {
        "schema_version": "open_agronomy_agent.active_corpus_source_receipt.v1",
        "archive_root_label": "Lexar historical archive; path intentionally not persisted",
        "admitted_raw_sources": [*pdf_sources, *table_sources],
        "excluded_legacy_rows": len(rows) - sum(len(item["legacy_rows"]) for item in metadata.values() if item["source_id"] in {source["source_id"] for source in [*pdf_sources, *table_sources]}),
        "reason": "Rows not regenerated from a hash-identified raw source remain historical and are not active runtime evidence.",
    }
    source_receipt_path = output / "source_receipt.json"
    source_receipt_path.write_text(json.dumps(source_receipt, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": CORPUS_RELEASE_SCHEMA,
        "store_id": "offline-agronomy",
        "profile": "active-development-offline-corpus",
        "shards": shards,
        "row_count": sum(item["rows"] for item in shards),
        "component_rows": {name: len(values) for name, values in sorted(by_component.items())},
        "quality_ledger_path": ledger_path.relative_to(output).as_posix(),
        "quality_ledger_sha256": _sha256(ledger_path),
        "exact_duplicate_clusters_path": clusters_path.relative_to(output).as_posix(),
        "exact_duplicate_clusters_sha256": _sha256(clusters_path),
        "source_receipt_path": source_receipt_path.relative_to(output).as_posix(),
        "source_receipt_sha256": _sha256(source_receipt_path),
        "unrecoverable_legacy_rows_excluded": source_receipt["excluded_legacy_rows"],
        "jurisdiction_policy": "Canadian official sources rank before U.S. analogue context; community sources are not loaded.",
    }
    manifest["store_sha256"] = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
    (output / "store_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="mounted historical source archive")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build(archive=args.archive, output=args.output)
    print(json.dumps({"output": str(args.output), "rows": manifest["row_count"], "sha256": manifest["store_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
