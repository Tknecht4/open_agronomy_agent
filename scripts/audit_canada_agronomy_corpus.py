#!/usr/bin/env python3
"""Audit the distributable Canadian agronomy corpus and render coverage evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.canada_sources import load_canada_source_manifest, source_allowed_for


SCHEMA_VERSION = "open_agronomy_agent.canada_corpus_promotion_audit.v1"
EXPECTED_EXTRACTOR_SCHEMA_VERSION = 10
VALID_RETRIEVAL_POLICIES = {"standard", "context_only", "requires_live_authority"}
PAGE_RE = re.compile(r"\[page\s+(\d+)\]", re.IGNORECASE)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if value and count > 1)


def audit_corpus(
    *,
    manifest_path: Path,
    corpus_path: Path,
    raw_dir: Path,
    expected_extractor_schema: int,
) -> dict[str, Any]:
    manifest = load_canada_source_manifest(manifest_path)
    manifest_sha256 = sha256_path(manifest_path)
    source_registry = {source["id"]: source for source in manifest["sources"]}
    rows = load_jsonl(corpus_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def error(code: str, detail: str, *, doc_id: str = "", source_id: str = "") -> None:
        errors.append({"code": code, "detail": detail, "doc_id": doc_id, "source_id": source_id})

    doc_ids = [str(row.get("doc_id") or "") for row in rows]
    chunk_hashes = [str((row.get("lineage") or {}).get("chunk_sha256") or "") for row in rows]
    text_hashes = [sha256_text(str(row.get("text") or "")) for row in rows]
    for duplicate in _duplicates(doc_ids):
        error("duplicate_doc_id", duplicate, doc_id=duplicate)
    for duplicate in _duplicates(chunk_hashes):
        error("duplicate_chunk_sha256", duplicate)
    for duplicate in _duplicates(text_hashes):
        error("duplicate_chunk_text", duplicate)

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    policy_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    chunk_crop_counts: Counter[str] = Counter()
    chunk_topic_counts: Counter[str] = Counter()
    jurisdiction_chunk_counts: Counter[str] = Counter()
    extractor_versions: Counter[int] = Counter()
    source_type_counts: Counter[str] = Counter()

    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        source_id = str(row.get("source_id") or "")
        by_source[source_id].append(row)
        source = source_registry.get(source_id)
        if source is None:
            error("source_not_registered", "Chunk source_id is absent from the registry.", doc_id=doc_id, source_id=source_id)
            continue
        if not source_allowed_for(source, "distributable_bundle"):
            error("source_not_distributable", "Registry does not permit distributable_bundle use.", doc_id=doc_id, source_id=source_id)
        lineage = row.get("lineage") if isinstance(row.get("lineage"), dict) else {}
        extractor = lineage.get("extractor") if isinstance(lineage.get("extractor"), dict) else {}
        extractor_version = int(extractor.get("schema_version") or 0)
        extractor_versions[extractor_version] += 1
        if extractor_version != expected_extractor_schema:
            error(
                "extractor_schema_mismatch",
                f"Expected {expected_extractor_schema}, found {extractor_version}.",
                doc_id=doc_id,
                source_id=source_id,
            )
        if lineage.get("manifest_sha256") != manifest_sha256:
            error("manifest_sha256_mismatch", "Chunk lineage does not match the current source registry.", doc_id=doc_id, source_id=source_id)
        actual_chunk_hash = sha256_text(str(row.get("text") or ""))
        if lineage.get("chunk_sha256") != actual_chunk_hash:
            error("chunk_sha256_mismatch", actual_chunk_hash, doc_id=doc_id, source_id=source_id)
        expected_source_type = str(source.get("runtime_source_type") or "applied_guidance")
        if row.get("source_type") != expected_source_type:
            error(
                "runtime_source_type_mismatch",
                f"Expected {expected_source_type}, found {row.get('source_type')}",
                doc_id=doc_id,
                source_id=source_id,
            )
        source_type_counts[str(row.get("source_type") or "unspecified")] += 1

        policy = str(row.get("retrieval_policy") or "")
        policy_counts[policy] += 1
        if policy not in VALID_RETRIEVAL_POLICIES:
            error("invalid_retrieval_policy", policy, doc_id=doc_id, source_id=source_id)
        risks = [str(value) for value in row.get("content_risk_tags") or []]
        risk_counts.update(risks)
        chunk_crop_counts.update(str(value) for value in row.get("chunk_crops") or [])
        chunk_topic_counts.update(str(value) for value in row.get("chunk_topics") or [])
        jurisdiction_chunk_counts.update(str(value) for value in row.get("jurisdiction") or [])

        excluded_pages = set(int(value) for value in (row.get("extraction") or {}).get("excluded_pages") or [])
        leaked_pages = sorted(excluded_pages & {int(value) for value in PAGE_RE.findall(str(row.get("text") or ""))})
        if leaked_pages:
            error("excluded_page_leakage", str(leaked_pages), doc_id=doc_id, source_id=source_id)

        license_snapshot = row.get("license_snapshot") if isinstance(row.get("license_snapshot"), dict) else {}
        if license_snapshot.get("scope_verified") is not True:
            error("distribution_scope_unverified", "scope_verified", doc_id=doc_id, source_id=source_id)
        if license_snapshot.get("scope_basis") not in {
            "source_specific_record",
            "jurisdiction_wide_open_licence",
        }:
            error(
                "distribution_scope_basis_missing",
                str(license_snapshot.get("scope_basis") or ""),
                doc_id=doc_id,
                source_id=source_id,
            )
        if not str(license_snapshot.get("scope_evidence_url") or "").startswith("https://"):
            error(
                "distribution_scope_evidence_missing",
                str(license_snapshot.get("scope_evidence_url") or ""),
                doc_id=doc_id,
                source_id=source_id,
            )
        for permission in ("permits_modification", "permits_commercial", "permits_redistribution"):
            if license_snapshot.get(permission) is not True:
                error("distribution_permission_missing", permission, doc_id=doc_id, source_id=source_id)

    raw_evidence: dict[str, Any] = {}
    for source_id, source_rows in sorted(by_source.items()):
        source = source_registry.get(source_id)
        if source is None:
            continue
        candidates = sorted((raw_dir / source_id).glob("source.*"))
        raw_path = next((path for path in candidates if not path.name.endswith(".lineage.json")), None)
        expected_hashes = {str((row.get("lineage") or {}).get("raw_sha256") or "") for row in source_rows}
        if raw_path is None:
            error("raw_source_missing", str(raw_dir / source_id), source_id=source_id)
            continue
        actual_hash = sha256_path(raw_path)
        raw_evidence[source_id] = {
            "path": str(raw_path),
            "bytes": raw_path.stat().st_size,
            "sha256": actual_hash,
            "lineage_sha256_values": sorted(expected_hashes),
            "matches_all_chunks": expected_hashes == {actual_hash},
        }
        if expected_hashes != {actual_hash}:
            error("raw_sha256_mismatch", actual_hash, source_id=source_id)

    required_jurisdictions = [str(value) for value in manifest["required_jurisdictions"]]
    bundled_jurisdictions = sorted(jurisdiction_chunk_counts)
    unbundled_jurisdictions = [value for value in required_jurisdictions if value not in bundled_jurisdictions]
    if unbundled_jurisdictions:
        warnings.append(
            {
                "code": "registered_but_not_bundled",
                "detail": (
                    "These jurisdictions have no chunks in this audited corpus. Their registry entries may be "
                    "live-only, rights-limited, unsupported by this extractor, or admitted through a separately "
                    "audited runtime corpus: " + ", ".join(unbundled_jurisdictions)
                ),
            }
        )

    registry_by_jurisdiction: dict[str, Any] = {}
    for jurisdiction in required_jurisdictions:
        sources = [source for source in manifest["sources"] if jurisdiction in source["jurisdiction"]]
        registry_by_jurisdiction[jurisdiction] = {
            "registered_sources": len(sources),
            "distributable_sources": sum(source_allowed_for(source, "distributable_bundle") for source in sources),
            "local_rag_sources": sum(source_allowed_for(source, "local_rag") for source in sources),
            "live_retrieval_sources": sum(source_allowed_for(source, "live_retrieval") for source in sources),
            "bundled_chunks": jurisdiction_chunk_counts[jurisdiction],
            "source_ids": [source["id"] for source in sources],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "pass" if not errors else "fail",
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "corpus": str(corpus_path),
        "corpus_sha256": sha256_path(corpus_path),
        "expected_extractor_schema": expected_extractor_schema,
        "row_count": len(rows),
        "source_count": len(by_source),
        "bundled_source_ids": sorted(by_source),
        "bundled_jurisdictions": bundled_jurisdictions,
        "required_jurisdictions": required_jurisdictions,
        "registered_but_not_bundled_jurisdictions": unbundled_jurisdictions,
        "duplicate_doc_ids": _duplicates(doc_ids),
        "duplicate_chunk_sha256": _duplicates(chunk_hashes),
        "duplicate_chunk_text_sha256": _duplicates(text_hashes),
        "extractor_versions": dict(sorted(extractor_versions.items())),
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "retrieval_policy_counts": dict(sorted(policy_counts.items())),
        "content_risk_tag_counts": dict(sorted(risk_counts.items())),
        "chunk_crop_counts": dict(sorted(chunk_crop_counts.items())),
        "chunk_topic_counts": dict(sorted(chunk_topic_counts.items())),
        "jurisdiction_chunk_counts": dict(sorted(jurisdiction_chunk_counts.items())),
        "registry_coverage": registry_by_jurisdiction,
        "raw_evidence": raw_evidence,
        "errors": errors,
        "warnings": warnings,
        "distribution_boundary": (
            "Only chunks from sources explicitly approved for distributable_bundle are included. Registered local-only, "
            "permission-required, review-required, and live-reference sources remain outside this corpus."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    bundled_jurisdictions = ", ".join(report["bundled_jurisdictions"])
    required_jurisdictions = report.get("required_jurisdictions") or list(report["registry_coverage"])
    registry_scope = ", ".join(required_jurisdictions)
    lines = [
        "# Canadian Agronomy Corpus Promotion Audit",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Status: **{report['status'].upper()}**",
        "",
        "## Bundle",
        "",
        f"- Rows: **{report['row_count']:,}**",
        f"- Sources: **{report['source_count']}** (`{', '.join(report['bundled_source_ids'])}`)",
        f"- Bundled jurisdictions: **{', '.join(report['bundled_jurisdictions'])}**",
        f"- Corpus SHA256: `{report['corpus_sha256']}`",
        f"- Manifest SHA256: `{report['manifest_sha256']}`",
        "",
        "## Jurisdiction Coverage",
        "",
        "| Jurisdiction | Registered | Distributable | Local RAG | Live | Bundled chunks |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for jurisdiction, payload in report["registry_coverage"].items():
        lines.append(
            f"| {jurisdiction} | {payload['registered_sources']} | {payload['distributable_sources']} | "
            f"{payload['local_rag_sources']} | {payload['live_retrieval_sources']} | {payload['bundled_chunks']} |"
        )
    lines.extend(
        [
            "",
            f"The registry scope for this audit is {registry_scope}. "
            f"The distributable payload contains sources from {bundled_jurisdictions}. "
            "Other registered sources remain discovery, local-only, permission-required, review-required, "
            "or live-reference material until their reuse rights permit redistribution.",
            "",
            "## Retrieval Policy",
            "",
            "| Policy | Chunks |",
            "|---|---:|",
        ]
    )
    for policy, count in report["retrieval_policy_counts"].items():
        lines.append(f"| `{policy}` | {count:,} |")
    lines.extend(["", "## Crop Coverage", "", "| Crop | Chunks mentioning crop |", "|---|---:|"])
    for crop, count in sorted(report["chunk_crop_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {crop} | {count:,} |")
    lines.extend(["", "## Topic Coverage", "", "| Topic | Chunks |", "|---|---:|"])
    for topic, count in sorted(report["chunk_topic_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{topic}` | {count:,} |")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            f"- Duplicate document IDs: **{len(report['duplicate_doc_ids'])}**",
            f"- Duplicate chunk hashes: **{len(report['duplicate_chunk_sha256'])}**",
            f"- Duplicate chunk text hashes: **{len(report['duplicate_chunk_text_sha256'])}**",
            f"- Errors: **{len(report['errors'])}**",
            f"- Warnings: **{len(report['warnings'])}**",
            "",
            "## Distribution Boundary",
            "",
            report["distribution_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/canada_agronomy_sources.json"))
    parser.add_argument("--corpus", type=Path, default=Path("data/derived/rag/canada_agronomy_distributable.jsonl"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/canada_agronomy"))
    parser.add_argument(
        "--expected-extractor-schema",
        type=int,
        default=EXPECTED_EXTRACTOR_SCHEMA_VERSION,
    )
    parser.add_argument("--output-json", type=Path, default=Path("docs/canadian_agronomy_corpus_promotion_audit_20260718.json"))
    parser.add_argument("--output-markdown", type=Path, default=Path("docs/canadian_agronomy_corpus_promotion_audit_20260718.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_corpus(
        manifest_path=args.manifest,
        corpus_path=args.corpus,
        raw_dir=args.raw_dir,
        expected_extractor_schema=args.expected_extractor_schema,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
