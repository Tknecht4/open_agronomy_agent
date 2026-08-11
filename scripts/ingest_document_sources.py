#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html.parser
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.canada_sources import (  # noqa: E402
    SCHEMA_VERSION as CANADA_SOURCE_SCHEMA_VERSION,
    load_canada_source_manifest,
    source_allowed_for,
    source_license_snapshot,
)
from agronomy_agent.query_context import extract_crop_entities, extract_topic_entities  # noqa: E402

DEFAULT_MANIFEST = ROOT / "data" / "manifests" / "rag_corpus_expansion_sources.json"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "documents"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "document_expansion_rag_corpus.jsonl"
DEFAULT_SUMMARY = ROOT / "data" / "derived" / "rag" / "document_expansion_summary.json"
DEFAULT_SHARD_DIR = ROOT / "data" / "derived" / "rag" / "document_expansion_shards"
EXTRACTOR_SCHEMA_VERSION = 10
LEGACY_LOCAL_RAG_LICENSE_STATUSES = {
    "CC-BY-4.0",
    "CC-BY-IGO-3.0_for_listed_languages",
    "us_government_public_source_with_citation",
}


class VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)

    def text(self) -> str:
        raw = " ".join(self.parts)
        raw = re.sub(r"\s*\n\s*", "\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def safe_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}" if slug else digest


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") == CANADA_SOURCE_SCHEMA_VERSION:
        return load_canada_source_manifest(path)
    return payload


def semantic_companion_sha256(source: dict[str, Any]) -> str | None:
    companion_value = str((source.get("ingest_policy") or {}).get("semantic_companion_path") or "").strip()
    if not companion_value:
        return None
    companion_path = Path(companion_value)
    if not companion_path.is_absolute():
        companion_path = ROOT / companion_path
    return sha256_path(companion_path)


def selected_sources(
    manifest: dict[str, Any],
    source_ids: set[str],
    buckets: set[str],
    priority: set[str],
    *,
    use_case: str = "local_rag",
) -> list[dict[str, Any]]:
    sources = manifest.get("sources", [])
    if source_ids:
        sources = [source for source in sources if source["id"] in source_ids]
    if buckets:
        sources = [source for source in sources if buckets.intersection(source.get("buckets", []))]
    if priority:
        sources = [source for source in sources if source.get("priority") in priority]
    if manifest.get("schema_version") == CANADA_SOURCE_SCHEMA_VERSION:
        sources = [
            source
            for source in sources
            if source.get("content_mode") != "structured_snapshot"
            and source_allowed_for(source, use_case)
            and source_allowed_for(source, "download")
        ]
    else:
        sources = [
            source
            for source in sources
            if source.get("license_status") in LEGACY_LOCAL_RAG_LICENSE_STATUSES
        ]
    return sources


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def raw_lineage(source: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    sidecar_path = raw_path.with_suffix(raw_path.suffix + ".lineage.json")
    raw_sha256 = sha256_path(raw_path)
    cached = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.is_file() else {}
    fetched_at = cached.get("fetched_at")
    if cached.get("raw_sha256") != raw_sha256 or not fetched_at:
        fetched_at = dt.datetime.fromtimestamp(raw_path.stat().st_mtime, tz=dt.timezone.utc).isoformat(timespec="seconds")
    lineage = {
        "source_id": source["id"],
        "canonical_url": source.get("url"),
        "download_url": source.get("download_url") or source.get("url"),
        "fetched_at": fetched_at,
        "raw_sha256": raw_sha256,
        "raw_bytes": raw_path.stat().st_size,
        "raw_path": str(raw_path),
    }
    sidecar_path.write_text(json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lineage


def download_source(source: dict[str, Any], raw_dir: Path, force: bool = False, timeout: int = 180) -> Path:
    url = source.get("download_url") or source["url"]
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix
    if not suffix:
        suffix = ".pdf" if source.get("format") == "pdf" else ".html"
    out = raw_dir / source["id"] / f"source{suffix}"
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) agronomy-agent-corpus-builder/0.1",
            "Accept": "text/html,application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    tmp = out.with_suffix(out.suffix + ".part")
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            with urlopen(req, timeout=timeout) as response, tmp.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            break
        except Exception as exc:  # noqa: BLE001 - collect retry diagnostics
            errors.append(f"urlopen attempt {attempt}: {exc!r}")
            tmp.unlink(missing_ok=True)
            try:
                subprocess.run(["curl", "-L", "--fail", "--retry", "2", "--retry-delay", "2", "--max-time", str(timeout), "-o", str(tmp), url], check=True)
                break
            except subprocess.CalledProcessError as curl_exc:
                errors.append(f"curl attempt {attempt}: {curl_exc!r}")
                tmp.unlink(missing_ok=True)
                time.sleep(min(10, attempt * 2))
    if not tmp.exists():
        raise RuntimeError(f"download failed for {source['id']}: {' | '.join(errors)}")
    tmp.replace(out)
    if out.stat().st_size < 1024:
        preview = out.read_text(encoding="utf-8", errors="ignore")[:300]
        out.unlink(missing_ok=True)
        subprocess.run(["curl", "-L", "--fail", "--retry", "2", "--retry-delay", "2", "--max-time", str(timeout), "-o", str(out), url], check=True)
        if out.stat().st_size < 1024:
            preview = out.read_text(encoding="utf-8", errors="ignore")[:300]
            out.unlink(missing_ok=True)
            raise RuntimeError(f"download for {source['id']} was too small; preview={preview!r}")
    if source.get("format") == "pdf":
        head = out.read_bytes()[:1024]
        if not head.startswith(b"%PDF"):
            out.unlink(missing_ok=True)
            subprocess.run(["curl", "-L", "--fail", "--retry", "2", "--retry-delay", "2", "--max-time", str(timeout), "-o", str(out), url], check=True)
            head = out.read_bytes()[:1024]
            if not head.startswith(b"%PDF"):
                preview = out.read_text(encoding="utf-8", errors="ignore")[:300]
                out.unlink(missing_ok=True)
                raise RuntimeError(f"download for {source['id']} did not return a PDF; preview={preview!r}")
    return out


def extract_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency varies by machine
        raise RuntimeError("PDF extraction requires PyMuPDF/fitz in the local environment") from exc

    doc = fitz.open(str(path))
    page_text: list[str] = []
    low_text_pages = 0
    low_text_page_numbers: list[int] = []
    for page in doc:
        text = page.get_text("text").strip()
        if len(text) < 120:
            low_text_pages += 1
            low_text_page_numbers.append(page.number + 1)
        page_text.append(f"\n\n[page {page.number + 1}]\n{text}")
    return "\n".join(page_text).strip(), {
        "pages": doc.page_count,
        "low_text_pages": low_text_pages,
        "low_text_page_numbers": low_text_page_numbers,
    }


def extract_html(path: Path) -> tuple[str, dict[str, Any]]:
    parser = VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return parser.text(), {"pages": None, "low_text_pages": 0}


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = text.replace("\u00ad", "")
    text = re.sub(r"([a-z])-\s+([a-z])", r"\1\2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def apply_source_ingest_policy(text: str, source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    policy = source.get("ingest_policy") or {}
    include_ranges = policy.get("include_page_ranges") or []
    exclude_ranges = policy.get("exclude_page_ranges") or []
    excluded_pages: list[int] = []
    included_pages: list[int] = []
    kept_blocks: list[str] = []
    blocks = re.split(r"(?=\n*\[page \d+\]\n)", text)
    for block in blocks:
        if not block.strip():
            continue
        match = re.match(r"\n*\[page (\d+)\]", block)
        page = int(match.group(1)) if match else None
        outside_allowlist = bool(
            page is not None
            and include_ranges
            and not any(int(start) <= page <= int(end) for start, end in include_ranges)
        )
        explicitly_excluded = bool(
            page is not None
            and any(int(start) <= page <= int(end) for start, end in exclude_ranges)
        )
        excluded = outside_allowlist or explicitly_excluded
        if excluded:
            excluded_pages.append(page)
        else:
            if page is not None:
                included_pages.append(page)
            kept_blocks.append(block)
    filtered = "".join(kept_blocks).strip()
    patterns = [re.compile(str(pattern)) for pattern in policy.get("exclude_line_patterns") or []]
    excluded_lines = 0
    if patterns:
        kept_lines: list[str] = []
        for line in filtered.splitlines():
            if any(pattern.search(line) for pattern in patterns):
                excluded_lines += 1
            else:
                kept_lines.append(line)
        filtered = "\n".join(kept_lines).strip()
    return filtered, {
        "included_pages": included_pages,
        "include_page_ranges": include_ranges,
        "excluded_pages": excluded_pages,
        "excluded_page_ranges": exclude_ranges,
        "excluded_line_patterns": [pattern.pattern for pattern in patterns],
        "excluded_lines": excluded_lines,
    }


def chunk_risk(source: dict[str, Any], chunk: str) -> tuple[list[str], str]:
    lowered = chunk.lower()
    tags: list[str] = []
    currency = source.get("currency") or {}
    regulatory = source.get("regulatory") or {}
    pesticide_language = bool(
        re.search(
            r"\b(herbicide|fungicide|insecticide|pesticide|product label|registered product|tank mix|rainfast|preharvest interval)\b",
            lowered,
        )
    )
    pesticide_action_specific = bool(
        pesticide_language
        and re.search(
            r"\b(product label|registered product|registration|tank mix|rainfast|preharvest interval|"
            r"restricted-entry interval|rate|rates|lb/ac|kg/ha|days? before harvest|application timing)\b",
            lowered,
        )
    )
    nutrient_rate_language = bool(
        re.search(r"\b(fertilizer|nitrogen|phosph(?:ate|orus)|potash|sulph(?:ate|ur))\b", lowered)
        and re.search(r"\b(lb/ac|kg/ha|rate|rates|recommendation|guideline)\b", lowered)
    )
    numeric_pest_threshold_language = bool(
        re.search(r"\b(?:economic|action|treatment) thresholds?\b", lowered)
        and re.search(
            r"\b(?:\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?|percent|per (?:plant|seedling|sweep|metre|meter))\b",
            lowered,
        )
    )
    regulatory_action_specific = bool(
        regulatory.get("require_live_authority")
        and re.search(
            r"\b(setbacks?|permits?|legal requirements?|regulations?|restricted[- ]entry|"
            r"preharvest|application (?:rate|timing)|days? before harvest)\b",
            lowered,
        )
    )
    if str(currency.get("status") or "").startswith("historical_"):
        tags.append("historical_source_requires_current_validation")
    if currency.get("volatile"):
        tags.append("volatile_source_requires_currency_check")
    if regulatory.get("require_live_authority"):
        tags.append("source_contains_live_authority_content")
    if regulatory_action_specific:
        tags.append("live_authority_required")
    if nutrient_rate_language:
        tags.append("numeric_fertility_guidance_requires_local_calibration")
    if pesticide_language:
        tags.append("pesticide_context_requires_current_pmra_check")
        if pesticide_action_specific:
            tags.append("pesticide_guidance_requires_current_pmra_label")
        if pesticide_action_specific:
            tags.append("live_authority_required")
    if numeric_pest_threshold_language:
        tags.append("numeric_pest_threshold_requires_current_local_authority")
        tags.append("live_authority_required")
    if "live_authority_required" in tags or "pesticide_guidance_requires_current_pmra_label" in tags:
        policy = "requires_live_authority"
    elif (
        "historical_source_requires_current_validation" in tags
        or "numeric_fertility_guidance_requires_local_calibration" in tags
        or "volatile_source_requires_currency_check" in tags
    ):
        policy = "context_only"
    else:
        policy = "standard"
    default_policy = str(source.get("default_retrieval_policy") or "")
    if default_policy == "context_only" and policy == "standard":
        policy = "context_only"
    return sorted(set(tags)), policy


def chunk_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        # PDF page markers are hard provenance boundaries. Carrying overlap
        # across them can attach a threshold or organism from the previous page
        # to the next page's crop heading.
        if re.match(r"^\[page \d+\]", paragraph, re.IGNORECASE) and current:
            chunks.append(" ".join(current).strip())
            current, current_words = [], 0
        words = paragraph.split()
        if len(words) > max_words:
            if current:
                chunks.append(" ".join(current).strip())
                current, current_words = [], 0
            step = max_words - overlap_words
            for i in range(0, len(words), step):
                piece = words[i : i + max_words]
                if len(piece) >= 50:
                    chunks.append(" ".join(piece).strip())
            continue
        if current_words + len(words) > max_words and current:
            chunks.append(" ".join(current).strip())
            tail = " ".join(current).split()[-overlap_words:] if overlap_words else []
            current = [" ".join(tail)] if tail else []
            current_words = len(tail)
        current.append(paragraph)
        current_words += len(words)
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if len(chunk.split()) >= 50]


def make_rows(
    source: dict[str, Any],
    text: str,
    extraction: dict[str, Any],
    max_words: int,
    overlap_words: int,
    *,
    raw_source_lineage: dict[str, Any] | None = None,
    manifest_sha256: str | None = None,
    ingested_at: str | None = None,
) -> list[dict[str, Any]]:
    filtered_text, filter_report = apply_source_ingest_policy(text, source)
    extraction = {**extraction, **filter_report}
    cleaned_text = clean_text(filtered_text)
    chunks = chunk_text(cleaned_text, max_words=max_words, overlap_words=overlap_words)
    rows: list[dict[str, Any]] = []
    source_url = source.get("url", "")
    runtime_source_type = str(source.get("runtime_source_type") or "applied_guidance")
    runtime_document_type = str(source.get("runtime_document_type") or "extension_document")
    license_record = source.get("license") if isinstance(source.get("license"), dict) else {}
    license_status = license_record.get("status") or source.get("license_status", "unknown")
    license_snapshot = source_license_snapshot(source) if license_record else {
        "status": license_status,
        "identifier": license_status,
        "evidence_url": None,
        "reviewed_on": None,
        "attribution": source.get("publisher", ""),
        "permits_modification": None,
        "permits_commercial": None,
        "permits_redistribution": None,
    }
    raw_source_lineage = raw_source_lineage or {}
    extracted_text_sha256 = sha256_text(cleaned_text)
    ingested_at = ingested_at or utc_now()
    jurisdiction = source.get("jurisdiction") or source.get("region", [])
    language = source.get("language") or ["unspecified"]
    for index, chunk in enumerate(chunks, start=1):
        chunk_sha256 = sha256_text(chunk)
        risk_tags, retrieval_policy = chunk_risk(source, chunk)
        chunk_crops = list(extract_crop_entities(chunk))
        chunk_topics = list(extract_topic_entities(chunk))
        title_facets = [*chunk_crops[:3], *(topic.replace("_", " ") for topic in chunk_topics[:3])]
        title_suffix = f" :: {'; '.join(title_facets)}" if title_facets else ""
        rows.append(
            {
                "doc_id": f"{source['id']}_{index:04d}",
                "title": f"{source['title']}{title_suffix} :: chunk {index}",
                "text": chunk,
                "source": source_url,
                "source_id": source["id"],
                "download_url": source.get("download_url", source_url),
                "publisher": source.get("publisher", ""),
                "license": license_status,
                "license_snapshot": license_snapshot,
                "sft_status": source.get("sft_status", "unknown"),
                "source_type": runtime_source_type,
                "document_type": runtime_document_type,
                "format": source.get("format", "unknown"),
                "region": source.get("region", jurisdiction),
                "jurisdiction": jurisdiction,
                "language": language,
                "currency": source.get("currency") or {"status": "unspecified"},
                "regulatory": source.get("regulatory") or {
                    "regulated_advice": False,
                    "require_live_authority": False,
                },
                "content_risk_tags": risk_tags,
                "retrieval_policy": retrieval_policy,
                "crops": source.get("crops", []),
                "chunk_crops": chunk_crops,
                "chunk_topics": chunk_topics,
                "buckets": source.get("buckets", []),
                "tags": sorted(
                    set(source.get("buckets", []) + chunk_crops + chunk_topics + list(jurisdiction))
                ),
                "chunk_index": index,
                "extraction": extraction,
                "lineage": {
                    "source_id": source["id"],
                    "canonical_url": source_url,
                    "download_url": source.get("download_url", source_url),
                    "fetched_at": raw_source_lineage.get("fetched_at"),
                    "raw_sha256": raw_source_lineage.get("raw_sha256"),
                    "raw_bytes": raw_source_lineage.get("raw_bytes"),
                    "extracted_text_sha256": extracted_text_sha256,
                    "chunk_sha256": chunk_sha256,
                    "manifest_sha256": manifest_sha256,
                    "ingested_at": ingested_at,
                    "license_snapshot": license_snapshot,
                    "language": language,
                    "jurisdiction": jurisdiction,
                    "currency": source.get("currency") or {"status": "unspecified"},
                    "content_risk_tags": risk_tags,
                    "retrieval_policy": retrieval_policy,
                    "extractor": {
                        "name": "scripts/ingest_document_sources.py",
                        "schema_version": EXTRACTOR_SCHEMA_VERSION,
                        "format": source.get("format", "unknown"),
                        "max_words": max_words,
                        "overlap_words": overlap_words,
                    },
                },
            }
        )
    companion_rows = make_semantic_companion_rows(
        source,
        rows,
        raw_source_lineage=raw_source_lineage,
        manifest_sha256=manifest_sha256,
        ingested_at=ingested_at,
    )
    if (source.get("ingest_policy") or {}).get("emit_source_chunks", True) is False:
        for index, row in enumerate(companion_rows, start=1):
            row["chunk_index"] = index
        return companion_rows
    rows.extend(companion_rows)
    return rows


def make_semantic_companion_rows(
    source: dict[str, Any],
    source_rows: list[dict[str, Any]],
    *,
    raw_source_lineage: dict[str, Any],
    manifest_sha256: str | None,
    ingested_at: str,
) -> list[dict[str, Any]]:
    """Emit reviewed semantic records while preserving their exact source lineage."""

    companion_value = str((source.get("ingest_policy") or {}).get("semantic_companion_path") or "").strip()
    if not companion_value:
        return []
    companion_path = Path(companion_value)
    if not companion_path.is_absolute():
        companion_path = ROOT / companion_path
    payload = json.loads(companion_path.read_text(encoding="utf-8"))
    if payload.get("source_id") != source.get("id"):
        raise ValueError(f"semantic companion source_id mismatch for {source.get('id')}")
    expected_raw_sha256 = str(payload.get("source_raw_sha256") or "")
    actual_raw_sha256 = str(raw_source_lineage.get("raw_sha256") or "")
    if expected_raw_sha256 and expected_raw_sha256 != actual_raw_sha256:
        raise ValueError(f"semantic companion raw SHA-256 mismatch for {source.get('id')}")
    if not source_rows:
        raise ValueError(f"semantic companion requires at least one extracted source row for {source.get('id')}")

    companion_sha256 = sha256_path(companion_path)
    companion_display_path = (
        str(companion_path.relative_to(ROOT))
        if companion_path.is_relative_to(ROOT)
        else str(companion_path)
    )
    base = source_rows[0]
    records = payload.get("records") or []
    if not isinstance(records, list) or not records:
        raise ValueError(f"semantic companion contains no records for {source.get('id')}")
    companion_rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        text = clean_text(str(record.get("text") or ""))
        if len(text.split()) < 40:
            raise ValueError(f"semantic companion record {index} is too short for {source.get('id')}")
        chunk_sha256 = sha256_text(text)
        risk_tags, retrieval_policy = chunk_risk(source, text)
        chunk_crops = list(extract_crop_entities(text))
        chunk_topics = list(extract_topic_entities(text))
        title = str(record.get("title") or f"{source['title']}: reviewed semantic companion {index}").strip()
        source_pages = [int(page) for page in record.get("source_pages") or payload.get("source_pages") or []]
        row = {
            **base,
            "doc_id": f"{source['id']}_semantic_{index:04d}",
            "title": title,
            "text": text,
            "content_risk_tags": risk_tags,
            "retrieval_policy": retrieval_policy,
            "chunk_crops": chunk_crops,
            "chunk_topics": chunk_topics,
            "tags": sorted(
                set(
                    source.get("buckets", [])
                    + chunk_crops
                    + chunk_topics
                    + list(base.get("jurisdiction") or [])
                    + list(record.get("tags") or [])
                )
            ),
            "chunk_index": len(source_rows) + index,
            "semantic_companion": {
                "schema_version": payload.get("schema_version"),
                "reviewed_on": payload.get("reviewed_on"),
                "review_method": payload.get("review_method"),
                "source_pages": source_pages,
                "companion_path": companion_display_path,
                "companion_sha256": companion_sha256,
            },
            "lineage": {
                **base["lineage"],
                "raw_sha256": actual_raw_sha256,
                "chunk_sha256": chunk_sha256,
                "manifest_sha256": manifest_sha256,
                "ingested_at": ingested_at,
                "content_risk_tags": risk_tags,
                "retrieval_policy": retrieval_policy,
                "semantic_companion": {
                    "schema_version": payload.get("schema_version"),
                    "reviewed_on": payload.get("reviewed_on"),
                    "review_method": payload.get("review_method"),
                    "source_pages": source_pages,
                    "path": companion_display_path,
                    "sha256": companion_sha256,
                    "parent_raw_sha256": actual_raw_sha256,
                },
                "extractor": {
                    **base["lineage"]["extractor"],
                    "schema_version": EXTRACTOR_SCHEMA_VERSION,
                    "transform": "reviewed_semantic_companion",
                },
            },
        }
        companion_rows.append(row)
    return companion_rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def combine_shards(shard_dir: Path, output: Path, source_ids: set[str] | None = None) -> int:
    rows: list[dict[str, Any]] = []
    for shard in sorted(shard_dir.glob("*.jsonl")):
        if source_ids is not None and shard.stem not in source_ids:
            continue
        rows.extend(read_jsonl(shard))
    write_jsonl(output, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and chunk extension HTML/PDF sources into a derived RAG corpus.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--shard-dir", type=Path, default=DEFAULT_SHARD_DIR)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--priority", action="append", default=[])
    parser.add_argument(
        "--use-case",
        choices=["local_rag", "distributable_bundle", "training"],
        default="local_rag",
        help="Enforce the source registry use policy before downloading or emitting chunks.",
    )
    parser.add_argument("--max-sources", type=int, default=0)
    parser.add_argument("--max-words", type=int, default=220)
    parser.add_argument("--overlap-words", type=int, default=35)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--download-timeout", type=int, default=180)
    parser.add_argument("--fail-on-source-error", action="store_true")
    parser.add_argument("--no-combine", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    manifest_hash = sha256_path(args.manifest)
    requested_source_ids = set(args.source_id)
    sources = selected_sources(
        manifest,
        requested_source_ids,
        set(args.bucket),
        set(args.priority),
        use_case=args.use_case,
    )
    sources = [source for source in sources if source.get("format") in {"pdf", "html"}]
    if args.max_sources:
        sources = sources[: args.max_sources]

    if args.dry_run:
        selected_ids = [source["id"] for source in sources]
        unavailable_requested = sorted(requested_source_ids - set(selected_ids))
        print(
            json.dumps(
                {
                    "manifest": str(args.manifest),
                    "manifest_sha256": manifest_hash,
                    "use_case": args.use_case,
                    "selected": selected_ids,
                    "count": len(sources),
                    "requested_but_ineligible_or_unsupported": unavailable_requested,
                },
                indent=2,
            )
        )
        return 0

    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.document_ingest_summary.v2",
        "generated_at": utc_now(),
        "manifest": str(args.manifest),
        "manifest_sha256": manifest_hash,
        "use_case": args.use_case,
        "sources_attempted": len(sources),
        "sources": [],
        "chunks": 0,
        "failures": [],
    }
    selected_ids = {source["id"] for source in sources}
    for source in sources:
        try:
            shard_path = args.shard_dir / f"{source['id']}.jsonl"
            if shard_path.exists() and not args.force:
                rows = read_jsonl(shard_path)
                shard_manifest_hashes = {str((row.get("lineage") or {}).get("manifest_sha256") or "") for row in rows}
                shard_extractor_versions = {
                    int((((row.get("lineage") or {}).get("extractor") or {}).get("schema_version") or 0))
                    for row in rows
                }
                shard_chunking = {
                    (
                        int((((row.get("lineage") or {}).get("extractor") or {}).get("max_words") or 0)),
                        int((((row.get("lineage") or {}).get("extractor") or {}).get("overlap_words") or 0)),
                    )
                    for row in rows
                }
                expected_companion_sha256 = semantic_companion_sha256(source)
                shard_companion_sha256 = {
                    str((row.get("semantic_companion") or {}).get("companion_sha256") or "")
                    for row in rows
                    if row.get("semantic_companion")
                }
                companion_is_current = (
                    shard_companion_sha256 == {expected_companion_sha256}
                    if expected_companion_sha256
                    else not shard_companion_sha256
                )
                if (
                    rows
                    and shard_manifest_hashes == {manifest_hash}
                    and shard_extractor_versions == {EXTRACTOR_SCHEMA_VERSION}
                    and shard_chunking == {(args.max_words, args.overlap_words)}
                    and companion_is_current
                ):
                    all_rows.extend(rows)
                    summary["sources"].append(
                        {
                            "id": source["id"],
                            "title": source["title"],
                            "raw_path": None,
                            "raw_sha256": (rows[0].get("lineage") or {}).get("raw_sha256"),
                            "extracted_text_sha256": (rows[0].get("lineage") or {}).get("extracted_text_sha256"),
                            "chunks": len(rows),
                            "words": None,
                            "extraction": None,
                            "needs_ocr_review": False,
                            "status": "skipped_current_lineage_shard",
                        }
                    )
                    print(f"{source['id']}: skipped current lineage shard ({len(rows)} chunks)", file=sys.stderr)
                    continue
            raw_path = download_source(source, args.raw_dir, force=args.force, timeout=args.download_timeout)
            source_raw_lineage = raw_lineage(source, raw_path)
            if source.get("format") == "pdf" or raw_path.suffix.lower() == ".pdf":
                text, extraction = extract_pdf(raw_path)
            else:
                text, extraction = extract_html(raw_path)
            rows = make_rows(
                source,
                text,
                extraction,
                args.max_words,
                args.overlap_words,
                raw_source_lineage=source_raw_lineage,
                manifest_sha256=manifest_hash,
            )
            if not rows:
                raise RuntimeError(f"source {source['id']} produced zero chunks from {len(clean_text(text).split())} extracted words")
            effective_extraction = rows[0]["extraction"]
            retrieval_policy_counts = Counter(row["retrieval_policy"] for row in rows)
            risk_tag_counts = Counter(tag for row in rows for tag in row["content_risk_tags"])
            write_jsonl(shard_path, rows)
            all_rows.extend(rows)
            summary["sources"].append(
                {
                    "id": source["id"],
                    "title": source["title"],
                    "raw_path": str(raw_path),
                    "raw_sha256": source_raw_lineage["raw_sha256"],
                    "extracted_text_sha256": rows[0]["lineage"]["extracted_text_sha256"],
                    "chunks": len(rows),
                    "words": len(clean_text(text).split()),
                    "extraction": effective_extraction,
                    "retrieval_policy_counts": dict(sorted(retrieval_policy_counts.items())),
                    "content_risk_tag_counts": dict(sorted(risk_tag_counts.items())),
                    "needs_ocr_review": effective_extraction.get("pages") and effective_extraction.get("low_text_pages", 0) / max(1, effective_extraction.get("pages", 1)) > 0.2,
                }
            )
            print(f"{source['id']}: {len(rows)} chunks", file=sys.stderr)
        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            summary["failures"].append({"id": source["id"], "error": repr(exc)})
            print(f"{source['id']}: failed {exc!r}", file=sys.stderr)

    write_jsonl(args.output, all_rows)
    summary["chunks"] = len(all_rows)
    if not args.no_combine:
        summary["combined_chunks"] = combine_shards(args.shard_dir, args.output, selected_ids)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["failures"] and args.fail_on_source_error:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
