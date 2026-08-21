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
import tempfile
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
    source_license_snapshot as registry_source_license_snapshot,
)
from agronomy_agent.query_context import extract_crop_entities, extract_topic_entities  # noqa: E402

DEFAULT_MANIFEST = ROOT / "data" / "manifests" / "rag_corpus_expansion_sources.json"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "documents"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "document_expansion_rag_corpus.jsonl"
DEFAULT_SUMMARY = ROOT / "data" / "derived" / "rag" / "document_expansion_summary.json"
DEFAULT_SHARD_DIR = ROOT / "data" / "derived" / "rag" / "document_expansion_shards"
EXTRACTOR_SCHEMA_VERSION = 10
SOURCE_SHARD_RECEIPT_SCHEMA_VERSION = "open_agronomy_agent.document_source_shard_receipt.v1"
SOURCE_SHARD_INDEX_SCHEMA_VERSION = "open_agronomy_agent.document_source_shard_index.v1"
SOURCE_SHARD_SUMMARY_SCHEMA_VERSION = "open_agronomy_agent.document_source_shard_summary.v1"
LEGACY_LOCAL_RAG_LICENSE_STATUSES = {
    "CC-BY-4.0",
    "CC-BY-IGO-3.0_for_listed_languages",
    "us_government_public_source_with_citation",
}

_SAFE_SOURCE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RawSha256MismatchError(RuntimeError):
    """A source's fetched or reused raw bytes differ from its declared pin."""


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
    ingest_policy = source.get("ingest_policy") or {}
    companion_value = str(ingest_policy.get("semantic_companion_path") or "").strip()
    if not companion_value:
        return None
    companion_path = Path(companion_value)
    if not companion_path.is_absolute():
        companion_path = ROOT / companion_path
    if not companion_path.is_file():
        raise ValueError(f"semantic companion does not exist for {source.get('id')}: {companion_value}")
    actual_sha256 = sha256_path(companion_path)
    expected_sha256 = str(ingest_policy.get("semantic_companion_sha256") or "").strip()
    if not expected_sha256:
        raise ValueError(f"semantic companion SHA-256 is not declared for {source.get('id')}")
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"semantic companion SHA-256 mismatch for {source.get('id')}: "
            f"expected {expected_sha256}, observed {actual_sha256}"
        )
    return actual_sha256


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


def source_expected_raw_sha256(source: dict[str, Any]) -> str | None:
    """Return a source's optional pinned raw SHA-256 in canonical lowercase."""

    value = source.get("expected_raw_sha256")
    if value is None:
        return None
    expected = str(value).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError(
            f"source {source.get('id', '<unknown>')} expected_raw_sha256 must be a "
            "64-character hexadecimal SHA-256"
        )
    return expected.lower()


def verify_expected_raw_sha256(
    source: dict[str, Any],
    path: Path,
    *,
    phase: str,
) -> str:
    """Hash a raw file and fail closed when its registry pin does not match."""

    actual = sha256_path(path)
    expected = source_expected_raw_sha256(source)
    if expected is not None and actual != expected:
        raise RawSha256MismatchError(
            f"{phase} raw SHA-256 mismatch for {source['id']}: "
            f"expected {expected}, got {actual}"
        )
    return actual


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def raw_lineage(source: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    sidecar_path = raw_path.with_suffix(raw_path.suffix + ".lineage.json")
    raw_sha256 = verify_expected_raw_sha256(source, raw_path, phase="raw lineage")
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
        "expected_raw_sha256": source_expected_raw_sha256(source),
        "raw_bytes": raw_path.stat().st_size,
        "raw_path": str(raw_path),
    }
    sidecar_path.write_text(json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lineage


def _download_with_curl(url: str, destination: Path, timeout: int) -> None:
    subprocess.run(
        [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "2",
            "--retry-delay",
            "2",
            "--max-time",
            str(timeout),
            "-o",
            str(destination),
            url,
        ],
        check=True,
    )


def _validate_downloaded_raw(source: dict[str, Any], path: Path) -> None:
    if path.stat().st_size < 1024:
        preview = path.read_text(encoding="utf-8", errors="ignore")[:300]
        raise RuntimeError(f"download for {source['id']} was too small; preview={preview!r}")
    if source.get("format") == "pdf":
        head = path.read_bytes()[:1024]
        if not head.startswith(b"%PDF"):
            preview = path.read_text(encoding="utf-8", errors="ignore")[:300]
            raise RuntimeError(
                f"download for {source['id']} did not return a PDF; preview={preview!r}"
            )
    verify_expected_raw_sha256(source, path, phase="downloaded")


def source_raw_path(source: dict[str, Any], raw_dir: Path) -> Path:
    url = source.get("download_url") or source["url"]
    suffix = Path(urlparse(url).path).suffix
    if not suffix:
        suffix = ".pdf" if source.get("format") == "pdf" else ".html"
    return raw_dir / source["id"] / f"source{suffix}"


def verify_existing_pinned_raw(source: dict[str, Any], raw_dir: Path) -> None:
    """Reject on-disk raw drift before reusing an existing extraction shard."""

    if source_expected_raw_sha256(source) is None:
        return
    raw_path = source_raw_path(source, raw_dir)
    if raw_path.is_file():
        verify_expected_raw_sha256(source, raw_path, phase="reused")


def download_source(source: dict[str, Any], raw_dir: Path, force: bool = False, timeout: int = 180) -> Path:
    # Validate the optional registry pin before treating a pre-existing local
    # artifact as trusted.  Existing source records without a pin retain the
    # historical reuse behavior.
    source_expected_raw_sha256(source)
    url = source.get("download_url") or source["url"]
    out = source_raw_path(source, raw_dir)
    if out.exists() and not force:
        verify_expected_raw_sha256(source, out, phase="reused")
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
                _download_with_curl(url, tmp, timeout)
                break
            except subprocess.CalledProcessError as curl_exc:
                errors.append(f"curl attempt {attempt}: {curl_exc!r}")
                tmp.unlink(missing_ok=True)
                time.sleep(min(10, attempt * 2))
    if not tmp.exists():
        raise RuntimeError(f"download failed for {source['id']}: {' | '.join(errors)}")

    # A successful transport can still be an HTML error page, a truncated body,
    # or a changed edition.  Validate the temporary bytes before they replace a
    # known-good raw artifact.  Keep the historical curl fallback for a bad
    # response, but apply the same checks before promotion.
    try:
        _validate_downloaded_raw(source, tmp)
    except RawSha256MismatchError:
        tmp.unlink(missing_ok=True)
        raise
    except RuntimeError as initial_validation_error:
        errors.append(f"download validation: {initial_validation_error}")
        tmp.unlink(missing_ok=True)
        try:
            _download_with_curl(url, tmp, timeout)
            _validate_downloaded_raw(source, tmp)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"download validation failed for {source['id']}: {' | '.join(errors)} | {exc!r}"
            ) from exc
    tmp.replace(out)
    return out


def extract_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        import pymupdf as fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency varies by machine
        try:
            import fitz  # type: ignore
        except Exception:
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
    license_snapshot = _row_license_snapshot(source) if license_record else {
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
                    "expected_raw_sha256": source_expected_raw_sha256(source),
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
    companion_sha256 = semantic_companion_sha256(source)
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

    assert companion_sha256 is not None
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


def canonical_json_bytes(value: Any) -> bytes:
    """Return a stable representation for source-shard release artifacts."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    """Atomically write a canonical JSON receipt in the destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".part",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(canonical_json_bytes(value))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_canonical_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomically write one source's rows as deterministic JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".part",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        for row in rows:
            handle.write(canonical_json_bytes(row))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _row_license_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    """Mirror the row-level licence snapshot for strict shard reuse checks."""

    license_record = source.get("license") if isinstance(source.get("license"), dict) else {}
    if license_record:
        return registry_source_license_snapshot(source)
    license_status = source.get("license_status", "unknown")
    return {
        "status": license_status,
        "identifier": license_status,
        "evidence_url": None,
        "reviewed_on": None,
        "attribution": source.get("publisher", ""),
        "permits_modification": None,
        "permits_commercial": None,
        "permits_redistribution": None,
    }


def source_artifact_stem(source_id: str) -> str:
    """Return a path-safe, stable source ID or fail before writing an artifact."""

    if not _SAFE_SOURCE_ARTIFACT_ID.fullmatch(source_id):
        raise ValueError(
            f"source-shard output requires a path-safe source ID, got {source_id!r}"
        )
    return source_id


def source_artifact_paths(
    source_id: str,
    *,
    shard_dir: Path,
    receipt_dir: Path,
) -> tuple[Path, Path]:
    stem = source_artifact_stem(source_id)
    return shard_dir / f"{stem}.jsonl", receipt_dir / f"{stem}.receipt.json"


def _source_shard_rows_are_valid(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    manifest_sha256: str,
    max_words: int,
    overlap_words: int,
) -> None:
    """Reject a stale or mixed source shard instead of silently reusing it."""

    if not rows:
        raise RuntimeError(f"source shard for {source['id']} is empty")
    expected_source_id = str(source["id"])
    expected_license = _row_license_snapshot(source)
    expected_raw_sha256 = source_expected_raw_sha256(source)
    document_ids: set[str] = set()
    raw_hashes: set[str] = set()
    extracted_hashes: set[str] = set()
    fetched_times: set[str] = set()
    raw_bytes: set[int] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise RuntimeError(f"source shard {expected_source_id} row {index} is not an object")
        if str(row.get("source_id") or "") != expected_source_id:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has a mixed source_id"
            )
        doc_id = str(row.get("doc_id") or "")
        if not doc_id or doc_id in document_ids:
            raise RuntimeError(
                f"source shard {expected_source_id} has a missing or duplicate document ID"
            )
        document_ids.add(doc_id)
        text = str(row.get("text") or "")
        if not text.strip():
            raise RuntimeError(f"source shard {expected_source_id} row {index} has no text")
        lineage = row.get("lineage")
        if not isinstance(lineage, dict):
            raise RuntimeError(f"source shard {expected_source_id} row {index} has no lineage")
        if str(lineage.get("source_id") or "") != expected_source_id:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} lineage source_id does not match"
            )
        if str(lineage.get("manifest_sha256") or "") != manifest_sha256:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} does not bind the current manifest"
            )
        if str(lineage.get("chunk_sha256") or "") != sha256_text(text):
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} chunk SHA-256 does not match text"
            )
        if row.get("license_snapshot") != expected_license:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} licence snapshot does not match registry"
            )
        if lineage.get("license_snapshot") != expected_license:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} lineage licence snapshot does not match registry"
            )
        if str(lineage.get("retrieval_policy") or "") != str(
            row.get("retrieval_policy") or ""
        ):
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} retrieval policy lineage does not match"
            )
        extractor = lineage.get("extractor")
        if not isinstance(extractor, dict):
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has no extractor lineage"
            )
        if int(extractor.get("schema_version") or 0) != EXTRACTOR_SCHEMA_VERSION:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} extractor schema is stale"
            )
        if int(extractor.get("max_words") or 0) != max_words or int(
            extractor.get("overlap_words") or 0
        ) != overlap_words:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} chunking parameters are stale"
            )
        raw_sha256 = str(lineage.get("raw_sha256") or "")
        extracted_text_sha256 = str(lineage.get("extracted_text_sha256") or "")
        fetched_at = str(lineage.get("fetched_at") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", raw_sha256):
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has no valid raw SHA-256"
            )
        if expected_raw_sha256 is not None and raw_sha256 != expected_raw_sha256:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} raw SHA-256 does not match "
                "the current source pin"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", extracted_text_sha256):
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has no valid extracted-text SHA-256"
            )
        if not fetched_at:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has no raw fetch timestamp"
            )
        try:
            raw_byte_count = int(lineage.get("raw_bytes"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has no valid raw byte count"
            ) from exc
        if raw_byte_count < 1:
            raise RuntimeError(
                f"source shard {expected_source_id} row {index} has no valid raw byte count"
            )
        raw_hashes.add(raw_sha256)
        extracted_hashes.add(extracted_text_sha256)
        fetched_times.add(fetched_at)
        raw_bytes.add(raw_byte_count)
    if len(raw_hashes) != 1 or len(extracted_hashes) != 1 or len(fetched_times) != 1 or len(raw_bytes) != 1:
        raise RuntimeError(
            f"source shard {expected_source_id} contains inconsistent source-level lineage"
        )


def source_shard_receipt(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    shard_path: Path,
    manifest_sha256: str,
    use_case: str,
    max_words: int,
    overlap_words: int,
) -> dict[str, Any]:
    """Build a deterministic provenance receipt for one complete source shard."""

    _source_shard_rows_are_valid(
        source,
        rows,
        manifest_sha256=manifest_sha256,
        max_words=max_words,
        overlap_words=overlap_words,
    )
    first_lineage = rows[0]["lineage"]
    retrieval_policy_counts = Counter(str(row["retrieval_policy"]) for row in rows)
    risk_tag_counts = Counter(
        str(tag) for row in rows for tag in row.get("content_risk_tags") or []
    )
    doc_ids = sorted(str(row["doc_id"]) for row in rows)
    source_use_policy = source.get("use_policy") or {}
    return {
        "schema_version": SOURCE_SHARD_RECEIPT_SCHEMA_VERSION,
        "source": {
            "id": str(source["id"]),
            "title": str(source.get("title") or ""),
            "publisher": str(source.get("publisher") or ""),
            "canonical_url": str(source.get("url") or ""),
            "download_url": str(source.get("download_url") or source.get("url") or ""),
            "source_record_sha256": canonical_json_sha256(source),
            "license_snapshot": _row_license_snapshot(source),
            "use_policy": {
                "download": source_use_policy.get("download") is True,
                "selected_use_case": use_case,
                "selected_use_case_allowed": source_use_policy.get(use_case) is True,
            },
        },
        "training_authorization": {
            "registry_training_allowed": source_use_policy.get("training") is True,
            "artifact_is_training_dataset": False,
            "boundary": (
                "This source-shard extraction is not a training dataset or training approval; "
                "a downstream training workflow must enforce its own authorization."
            ),
        },
        "ingestion": {
            "manifest_sha256": manifest_sha256,
            "use_case": use_case,
            "extractor": {
                "name": "scripts/ingest_document_sources.py",
                "schema_version": EXTRACTOR_SCHEMA_VERSION,
                "max_words": max_words,
                "overlap_words": overlap_words,
            },
        },
        "raw_lineage": {
            "fetched_at": first_lineage["fetched_at"],
            "raw_sha256": first_lineage["raw_sha256"],
            "expected_raw_sha256": source_expected_raw_sha256(source),
            "raw_bytes": first_lineage["raw_bytes"],
            "extracted_text_sha256": first_lineage["extracted_text_sha256"],
        },
        "shard": {
            "path": shard_path.name,
            "sha256": sha256_path(shard_path),
            "bytes": shard_path.stat().st_size,
            "rows": len(rows),
            "document_ids_sha256": sha256_text("\n".join(doc_ids)),
            "retrieval_policy_counts": dict(sorted(retrieval_policy_counts.items())),
            "content_risk_tag_counts": dict(sorted(risk_tag_counts.items())),
        },
    }


def source_shard_summary_row(
    source: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    receipt: dict[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    """Make a stable summary row that does not vary between reuse and extraction."""

    return {
        "id": str(source["id"]),
        "title": str(source.get("title") or ""),
        "chunks": len(rows),
        "raw_sha256": receipt["raw_lineage"]["raw_sha256"],
        "extracted_text_sha256": receipt["raw_lineage"]["extracted_text_sha256"],
        "shard": {
            **receipt["shard"],
            "receipt_path": receipt_path.name,
            "receipt_sha256": sha256_path(receipt_path),
        },
    }


def validate_source_shard_mode(
    *,
    parser: argparse.ArgumentParser,
    manifest: dict[str, Any],
    sources: list[dict[str, Any]],
    requested_source_ids: set[str],
    eligible_source_ids: set[str],
    receipt_dir: Path,
    shard_dir: Path,
    summary_path: Path,
) -> None:
    """Fail before downloads when the governed source-shard contract is incomplete."""

    if manifest.get("schema_version") != CANADA_SOURCE_SCHEMA_VERSION:
        parser.error(
            "--output-mode source-shards requires a valid canada_agronomy_sources.json "
            "registry so download and use-policy gates are explicit"
        )
    unavailable_requested = sorted(requested_source_ids - eligible_source_ids)
    if unavailable_requested:
        parser.error(
            "source-shards refused requested source IDs that are ineligible or unsupported: "
            + ", ".join(unavailable_requested)
        )
    if not sources:
        parser.error("source-shards requires at least one eligible PDF or HTML source")

    seen_paths: set[Path] = set()
    for source in sources:
        try:
            shard_path, receipt_path = source_artifact_paths(
                str(source["id"]), shard_dir=shard_dir, receipt_dir=receipt_dir
            )
        except ValueError as exc:
            parser.error(str(exc))
        for path in (shard_path.resolve(), receipt_path.resolve()):
            if path in seen_paths:
                parser.error(f"source-shards has colliding output paths: {path}")
            seen_paths.add(path)
    index_path = receipt_dir / "source_shards_manifest.json"
    if summary_path.resolve() in seen_paths or summary_path.resolve() == index_path.resolve():
        parser.error("source-shards summary path collides with a source artifact or index")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and chunk extension HTML/PDF sources into a derived RAG corpus."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Legacy combined JSONL path. Defaults to the historical corpus path when "
            "--output-mode=combined; forbidden for source-shards."
        ),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help=(
            "Ingest summary path. Defaults to the historical summary in combined mode, "
            "or to <receipt-dir>/ingest_summary.json in source-shards mode."
        ),
    )
    parser.add_argument("--shard-dir", type=Path, default=DEFAULT_SHARD_DIR)
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=None,
        help=(
            "Directory for source-shard receipts. Only valid with --output-mode source-shards; "
            "defaults to <shard-dir>/receipts."
        ),
    )
    parser.add_argument(
        "--output-mode",
        choices=["combined", "source-shards"],
        default="combined",
        help=(
            "combined preserves the legacy monolithic corpus. source-shards emits only "
            "per-source canonical JSONL and hash-bound receipts."
        ),
    )
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

    source_shard_mode = args.output_mode == "source-shards"
    if source_shard_mode:
        if args.output is not None:
            parser.error("--output is incompatible with --output-mode source-shards")
        if args.no_combine:
            parser.error("--no-combine is redundant and incompatible with --output-mode source-shards")
        receipt_dir = args.receipt_dir or args.shard_dir / "receipts"
        summary_path = args.summary or receipt_dir / "ingest_summary.json"
        output_path = None
    else:
        if args.receipt_dir is not None:
            parser.error("--receipt-dir requires --output-mode source-shards")
        receipt_dir = None
        summary_path = args.summary or DEFAULT_SUMMARY
        output_path = args.output or DEFAULT_OUTPUT

    manifest = load_manifest(args.manifest)
    manifest_hash = sha256_path(args.manifest)
    requested_source_ids = set(args.source_id)
    eligible_sources = selected_sources(
        manifest,
        requested_source_ids,
        set(args.bucket),
        set(args.priority),
        use_case=args.use_case,
    )
    eligible_sources = [
        source for source in eligible_sources if source.get("format") in {"pdf", "html"}
    ]
    eligible_source_ids = {str(source["id"]) for source in eligible_sources}
    if source_shard_mode:
        # A manifest's input order is not a release contract.  Source artifact
        # selection and receipt ordering must not change merely because the
        # registry is reformatted or new sources are appended elsewhere in it.
        eligible_sources.sort(key=lambda source: str(source["id"]))
    sources = list(eligible_sources)
    if args.max_sources:
        sources = sources[: args.max_sources]
    if source_shard_mode:
        assert receipt_dir is not None
        validate_source_shard_mode(
            parser=parser,
            manifest=manifest,
            sources=sources,
            requested_source_ids=requested_source_ids,
            eligible_source_ids=eligible_source_ids,
            receipt_dir=receipt_dir,
            shard_dir=args.shard_dir,
            summary_path=summary_path,
        )

    if args.dry_run:
        selected_ids = [source["id"] for source in sources]
        unavailable_requested = sorted(
            requested_source_ids
            - (eligible_source_ids if source_shard_mode else set(selected_ids))
        )
        dry_run = {
            "manifest": str(args.manifest),
            "manifest_sha256": manifest_hash,
            "use_case": args.use_case,
            "selected": selected_ids,
            "count": len(sources),
            "requested_but_ineligible_or_unsupported": unavailable_requested,
        }
        if source_shard_mode:
            dry_run.update(
                {
                    "output_mode": "source-shards",
                    "combined_corpus_created": False,
                    "shard_paths": [
                        source_artifact_paths(
                            str(source["id"]),
                            shard_dir=args.shard_dir,
                            receipt_dir=receipt_dir,
                        )[0].as_posix()
                        for source in sources
                    ],
                    "receipt_paths": [
                        source_artifact_paths(
                            str(source["id"]),
                            shard_dir=args.shard_dir,
                            receipt_dir=receipt_dir,
                        )[1].as_posix()
                        for source in sources
                    ],
                    "summary_path": summary_path.as_posix(),
                }
            )
        print(json.dumps(dry_run, indent=2, ensure_ascii=False))
        return 0

    all_rows: list[dict[str, Any]] = []
    if source_shard_mode:
        summary: dict[str, Any] = {
            "schema_version": SOURCE_SHARD_SUMMARY_SCHEMA_VERSION,
            "output_mode": "source-shards",
            "combined_corpus_created": False,
            "source_manifest": {
                "schema_version": manifest.get("schema_version"),
                "sha256": manifest_hash,
            },
            "use_case": args.use_case,
            "sources_attempted": len(sources),
            "selected_source_ids": [str(source["id"]) for source in sources],
            "sources": [],
            "chunks": 0,
            "failures": [],
        }
    else:
        summary = {
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
    source_index_rows: list[dict[str, Any]] = []
    source_chunk_count = 0
    integrity_failures = False
    for source in sources:
        try:
            if source_shard_mode:
                assert receipt_dir is not None
                shard_path, receipt_path = source_artifact_paths(
                    str(source["id"]), shard_dir=args.shard_dir, receipt_dir=receipt_dir
                )
            else:
                shard_path = args.shard_dir / f"{source['id']}.jsonl"
                receipt_path = None
            if shard_path.exists() and not args.force:
                verify_existing_pinned_raw(source, args.raw_dir)
                rows = read_jsonl(shard_path)
                shard_manifest_hashes = {
                    str((row.get("lineage") or {}).get("manifest_sha256") or "")
                    for row in rows
                }
                shard_extractor_versions = {
                    int(
                        (((row.get("lineage") or {}).get("extractor") or {}).get(
                            "schema_version"
                        ) or 0)
                    )
                    for row in rows
                }
                shard_chunking = {
                    (
                        int(
                            (((row.get("lineage") or {}).get("extractor") or {}).get(
                                "max_words"
                            ) or 0)
                        ),
                        int(
                            (((row.get("lineage") or {}).get("extractor") or {}).get(
                                "overlap_words"
                            ) or 0)
                        ),
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
                    if source_shard_mode:
                        _source_shard_rows_are_valid(
                            source,
                            rows,
                            manifest_sha256=manifest_hash,
                            max_words=args.max_words,
                            overlap_words=args.overlap_words,
                        )
                        write_canonical_jsonl(shard_path, rows)
                        receipt = source_shard_receipt(
                            source,
                            rows,
                            shard_path=shard_path,
                            manifest_sha256=manifest_hash,
                            use_case=args.use_case,
                            max_words=args.max_words,
                            overlap_words=args.overlap_words,
                        )
                        assert receipt_path is not None
                        write_canonical_json(receipt_path, receipt)
                        summary["sources"].append(
                            source_shard_summary_row(
                                source,
                                rows,
                                receipt=receipt,
                                receipt_path=receipt_path,
                            )
                        )
                        source_index_rows.append(
                            {
                                "source_id": str(source["id"]),
                                "shard_path": receipt["shard"]["path"],
                                "shard_sha256": receipt["shard"]["sha256"],
                                "receipt_path": receipt_path.name,
                                "receipt_sha256": sha256_path(receipt_path),
                                "rows": len(rows),
                            }
                        )
                        source_chunk_count += len(rows)
                    else:
                        all_rows.extend(rows)
                        summary["sources"].append(
                            {
                                "id": source["id"],
                                "title": source["title"],
                                "raw_path": None,
                                "raw_sha256": (rows[0].get("lineage") or {}).get("raw_sha256"),
                                "extracted_text_sha256": (rows[0].get("lineage") or {}).get(
                                    "extracted_text_sha256"
                                ),
                                "chunks": len(rows),
                                "words": None,
                                "extraction": None,
                                "needs_ocr_review": False,
                                "status": "skipped_current_lineage_shard",
                            }
                        )
                    print(
                        f"{source['id']}: skipped current lineage shard ({len(rows)} chunks)",
                        file=sys.stderr,
                    )
                    continue
            raw_path = download_source(
                source, args.raw_dir, force=args.force, timeout=args.download_timeout
            )
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
                # Source-shard rows are reproducible from the raw lineage.  The
                # legacy combined artifact intentionally retains its historical
                # run-time ingestion timestamp behavior.
                ingested_at=source_raw_lineage["fetched_at"] if source_shard_mode else None,
            )
            if not rows:
                raise RuntimeError(
                    f"source {source['id']} produced zero chunks from "
                    f"{len(clean_text(text).split())} extracted words"
                )
            if source_shard_mode:
                _source_shard_rows_are_valid(
                    source,
                    rows,
                    manifest_sha256=manifest_hash,
                    max_words=args.max_words,
                    overlap_words=args.overlap_words,
                )
                write_canonical_jsonl(shard_path, rows)
                receipt = source_shard_receipt(
                    source,
                    rows,
                    shard_path=shard_path,
                    manifest_sha256=manifest_hash,
                    use_case=args.use_case,
                    max_words=args.max_words,
                    overlap_words=args.overlap_words,
                )
                assert receipt_path is not None
                write_canonical_json(receipt_path, receipt)
                summary["sources"].append(
                    source_shard_summary_row(
                        source,
                        rows,
                        receipt=receipt,
                        receipt_path=receipt_path,
                    )
                )
                source_index_rows.append(
                    {
                        "source_id": str(source["id"]),
                        "shard_path": receipt["shard"]["path"],
                        "shard_sha256": receipt["shard"]["sha256"],
                        "receipt_path": receipt_path.name,
                        "receipt_sha256": sha256_path(receipt_path),
                        "rows": len(rows),
                    }
                )
                source_chunk_count += len(rows)
            else:
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
                        "needs_ocr_review": effective_extraction.get("pages")
                        and effective_extraction.get("low_text_pages", 0)
                        / max(1, effective_extraction.get("pages", 1))
                        > 0.2,
                    }
                )
            print(f"{source['id']}: {len(rows)} chunks", file=sys.stderr)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            RuntimeError,
            ValueError,
            OSError,
            subprocess.CalledProcessError,
        ) as exc:
            if isinstance(exc, RawSha256MismatchError):
                integrity_failures = True
            summary["failures"].append({"id": source["id"], "error": repr(exc)})
            print(f"{source['id']}: failed {exc!r}", file=sys.stderr)

    if source_shard_mode:
        assert receipt_dir is not None
        summary["chunks"] = source_chunk_count
        summary["sources"].sort(key=lambda row: str(row["id"]))
        source_index_rows.sort(key=lambda row: str(row["source_id"]))
        if not summary["failures"]:
            index_path = receipt_dir / "source_shards_manifest.json"
            source_index = {
                "schema_version": SOURCE_SHARD_INDEX_SCHEMA_VERSION,
                "output_mode": "source-shards",
                "source_manifest": {
                    "schema_version": manifest.get("schema_version"),
                    "sha256": manifest_hash,
                },
                "use_case": args.use_case,
                "extractor": {
                    "name": "scripts/ingest_document_sources.py",
                    "schema_version": EXTRACTOR_SCHEMA_VERSION,
                    "max_words": args.max_words,
                    "overlap_words": args.overlap_words,
                },
                "sources": source_index_rows,
                "totals": {"sources": len(source_index_rows), "rows": source_chunk_count},
            }
            write_canonical_json(index_path, source_index)
            summary["source_shard_index"] = {
                "path": index_path.name,
                "sha256": sha256_path(index_path),
            }
        write_canonical_json(summary_path, summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
        # A partially emitted source set has no new complete index, so callers
        # cannot mistake it for a prepared store.  This is deliberately stricter
        # than the legacy combined-corpus mode.
        return 2 if summary["failures"] else 0

    assert output_path is not None
    write_jsonl(output_path, all_rows)
    summary["chunks"] = len(all_rows)
    if not args.no_combine:
        summary["combined_chunks"] = combine_shards(args.shard_dir, output_path, selected_ids)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["failures"] and (args.fail_on_source_error or integrity_failures):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
