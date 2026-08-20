"""Deterministic, source-bound helpers for offline corpus releases.

The helpers in this module deliberately separate an archival source from a
runtime record.  A record is only eligible for a runtime release when its
source identity, jurisdiction, rights disposition, and extraction locator are
all present.  Historical records with a document-level locator remain useful,
but are labelled as such rather than pretending to have page/character spans
that were never captured by the old extractor.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


CORPUS_RELEASE_SCHEMA = "open_agronomy_agent.offline_corpus_release.v1"
QUALITY_LEDGER_SCHEMA = "open_agronomy_agent.corpus_quality_ledger.v1"
QUALITY_LEDGER_REQUIRED_FIELDS = (
    "extraction_fidelity",
    "language",
    "authority_tier",
    "jurisdiction",
    "temporal_scope",
    "risk_class",
    "retrieval_eligibility",
    "duplicate_disposition",
    "near_duplicate_disposition",
)
_SPACE = re.compile(r"\s+")
_PAGE_MARKER = re.compile(r"^\[page\s+\d+\]$", re.IGNORECASE)
_REFERENCE_HEADING = re.compile(r"^(references|bibliography|works cited|citations?)\b", re.IGNORECASE)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def normalize_text(value: str) -> str:
    """Normalize only whitespace/case for duplicate detection, never output."""

    return _SPACE.sub(" ", value).strip().casefold()


def normalized_text_sha256(value: str) -> str:
    return sha256_text(normalize_text(value))


def answer_evidence_disposition(text: str, *, title: str = "") -> str:
    """Conservatively identify boilerplate that must not enter answer context."""

    stripped = text.strip()
    title_or_text = title.strip() or stripped.splitlines()[0] if stripped else ""
    if _PAGE_MARKER.fullmatch(stripped):
        return "provenance_only_page_marker"
    if _REFERENCE_HEADING.match(title_or_text):
        return "provenance_only_references"
    if len(normalize_text(stripped)) < 24:
        return "low_signal_review_required"
    return "answer_evidence_candidate"


def source_locator_status(locator: Mapping[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(locator, Mapping):
        return False, "missing_source_locator"
    raw_sha = str(locator.get("raw_sha256") or "")
    source_url = str(locator.get("source_url") or "")
    method = str(locator.get("extraction_method") or "")
    precision = str(locator.get("precision") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_sha):
        return False, "invalid_raw_sha256"
    if not source_url.startswith(("https://", "http://")):
        return False, "missing_source_url"
    if not method:
        return False, "missing_extraction_method"
    if precision not in {"page_char_span", "section_char_span", "table_cells", "json_document_chunk"}:
        return False, "unsupported_locator_precision"
    if precision == "json_document_chunk":
        if not locator.get("archive_relative_path") or not locator.get("json_document_id"):
            return False, "missing_document_locator"
        if not isinstance(locator.get("chunk_index"), int) or int(locator["chunk_index"]) < 0:
            return False, "invalid_chunk_index"
        if not re.fullmatch(r"[0-9a-f]{64}", str(locator.get("chunk_text_sha256") or "")):
            return False, "invalid_chunk_text_sha256"
    if precision in {"page_char_span", "section_char_span"}:
        start, end = locator.get("char_start"), locator.get("char_end")
        if not isinstance(start, int) or start < 0:
            return False, "missing_char_start"
        if not isinstance(end, int) or end <= start:
            return False, "invalid_char_end"
        if precision == "page_char_span" and (not isinstance(locator.get("page"), int) or int(locator["page"]) < 1):
            return False, "invalid_page"
        heading_path = locator.get("heading_path")
        if precision == "section_char_span" and (
            not isinstance(heading_path, list) or not all(isinstance(value, str) and value for value in heading_path)
        ):
            return False, "missing_heading_path"
    if precision == "table_cells":
        if not isinstance(locator.get("table_title"), str) or not locator["table_title"]:
            return False, "missing_table_title"
        headers = locator.get("column_headers")
        cells = locator.get("cells")
        if not isinstance(headers, list) or not headers or not all(isinstance(value, str) and value for value in headers):
            return False, "invalid_table_headers"
        if not isinstance(cells, list) or not cells:
            return False, "missing_table_cells"
        for cell in cells:
            if not isinstance(cell, Mapping) or not isinstance(cell.get("row"), int) or not isinstance(cell.get("column"), int):
                return False, "invalid_table_cell_coordinates"
    return True, "complete"


def quality_ledger_status(record: Mapping[str, Any]) -> tuple[bool, str]:
    """Ensure every successor runtime row carries its compact quality ledger."""

    quality = record.get("quality")
    if not isinstance(quality, Mapping):
        return False, "missing_quality_ledger"
    for field in QUALITY_LEDGER_REQUIRED_FIELDS:
        value = quality.get(field)
        if not isinstance(value, str) or not value.strip():
            return False, f"missing_quality_{field}"
    if str(quality.get("retrieval_eligibility")) != str(record.get("retrieval_policy") or ""):
        return False, "quality_retrieval_eligibility_mismatch"
    return True, "complete"


def quality_ledger_row(
    record: Mapping[str, Any],
    *,
    corpus_path: str,
    duplicate_cluster: str,
    duplicate_disposition: str,
) -> dict[str, Any]:
    text = str(record.get("text") or "")
    locator = record.get("source_locator") if isinstance(record.get("source_locator"), Mapping) else None
    locator_complete, locator_status = source_locator_status(locator)
    quality_complete, quality_status = quality_ledger_status(record)
    return {
        "doc_id": str(record.get("doc_id") or ""),
        "source_id": str(record.get("source_id") or ""),
        "corpus_path": corpus_path,
        "text_sha256": sha256_text(text),
        "normalized_text_sha256": normalized_text_sha256(text),
        "source_locator_complete": locator_complete,
        "source_locator_status": locator_status,
        "quality_ledger_complete": quality_complete,
        "quality_ledger_status": quality_status,
        "source_locator_precision": str((locator or {}).get("precision") or ""),
        "extraction_method": str((locator or {}).get("extraction_method") or ""),
        "answer_evidence_disposition": answer_evidence_disposition(text, title=str(record.get("title") or "")),
        "duplicate_cluster": duplicate_cluster,
        "duplicate_disposition": duplicate_disposition,
        "near_duplicate_cluster_id": str((record.get("quality") or {}).get("near_duplicate_cluster_id") or "none"),
        "near_duplicate_disposition": str((record.get("quality") or {}).get("near_duplicate_disposition") or ""),
        "jurisdiction": list(record.get("jurisdiction") or record.get("jurisdictions") or []),
        "authority_tier": str(record.get("authority_tier") or ""),
        "rights_status": str(record.get("rights_status") or record.get("license") or ""),
        "language": str(record.get("language") or "unknown"),
        "extraction_fidelity": str((record.get("quality") or {}).get("extraction_fidelity") or "unknown"),
        "temporal_scope": str(record.get("temporal_scope") or ""),
        "risk_class": str(record.get("risk_class") or ""),
        "retrieval_eligibility": str(record.get("retrieval_policy") or ""),
    }


def shard_records(records: Iterable[Mapping[str, Any]], *, maximum_bytes: int) -> list[list[dict[str, Any]]]:
    """Return deterministic JSONL shards whose serialized lines fit a byte cap."""

    if maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be positive")
    shards: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0
    for source in records:
        record = dict(source)
        line_size = len((canonical_json(record) + "\n").encode("utf-8"))
        if line_size > maximum_bytes:
            raise ValueError(f"record exceeds shard size cap: {record.get('doc_id')}")
        if current and current_size + line_size > maximum_bytes:
            shards.append(current)
            current = []
            current_size = 0
        current.append(record)
        current_size += line_size
    if current:
        shards.append(current)
    return shards


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> tuple[int, str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    rows = 0
    total_bytes = 0
    with path.open("wb") as handle:
        for record in records:
            line = (canonical_json(dict(record)) + "\n").encode("utf-8")
            handle.write(line)
            digest.update(line)
            rows += 1
            total_bytes += len(line)
    return rows, digest.hexdigest(), total_bytes
