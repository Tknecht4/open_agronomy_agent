#!/usr/bin/env python3
"""Audit governed runtime knowledge for provenance, balance, and offline sufficiency.

This is deliberately a corpus audit, not an answer-quality score. It reports what
the runtime can actually admit into model context and keeps sealed release corpora
separate from unpromoted candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml


REQUIRED_LINEAGE_FIELDS = {
    "source_id",
    "canonical_url",
    "download_url",
    "fetched_at",
    "raw_sha256",
    "extracted_text_sha256",
    "chunk_sha256",
    "manifest_sha256",
    "license_snapshot",
    "language",
    "jurisdiction",
    "currency",
    "extractor",
}
CANADIAN_PROVINCES = {
    "Alberta",
    "British Columbia",
    "Manitoba",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Nova Scotia",
    "Ontario",
    "Prince Edward Island",
    "Quebec",
    "Saskatchewan",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/rag_governed_runtime_v1.yaml")
    parser.add_argument("--policy", default="data/manifests/runtime_corpus_policy.json")
    parser.add_argument(
        "--candidate",
        default="data/derived/rag/canada_agronomy_distributable_v12_candidate.jsonl",
    )
    parser.add_argument(
        "--json-output",
        default="outputs/knowledge_store_review_20260723/runtime_knowledge_sufficiency.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="docs/runtime_knowledge_sufficiency_audit_20260723.md",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            yield value


def normalized_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def count_values(records: list[dict[str, Any]], *keys: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        values: list[str] = []
        for key in keys:
            values.extend(normalized_values(record.get(key)))
        for value in set(values):
            counts[value] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def likely_french_text(text: str) -> bool:
    tokens = re.findall(r"[a-zàâçéèêëîïôùûüÿœæ-]+", text.lower())
    anchors = {
        "avec",
        "aux",
        "culture",
        "cultures",
        "dans",
        "des",
        "du",
        "est",
        "les",
        "pour",
        "sol",
        "sols",
        "une",
    }
    return sum(token in anchors for token in tokens) >= 6


def corpus_summary(path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    records = list(rows(path))
    lineage_complete = 0
    rights_complete = 0
    for record in records:
        lineage = record.get("lineage") or {}
        if REQUIRED_LINEAGE_FIELDS.issubset(lineage):
            lineage_complete += 1
        license_snapshot = record.get("license_snapshot") or lineage.get("license_snapshot") or {}
        if (
            license_snapshot.get("scope_verified") is True
            and license_snapshot.get("scope_basis")
            in {"source_specific_record", "jurisdiction_wide_open_licence"}
            and str(license_snapshot.get("scope_evidence_url") or "").startswith("https://")
            and
            license_snapshot.get("permits_modification") is True
            and license_snapshot.get("permits_commercial") is True
            and license_snapshot.get("permits_redistribution") is True
        ):
            rights_complete += 1
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256(path),
        "sha256_matches_policy": sha256(path) == str(policy.get("sha256") or ""),
        "runtime_eligibility": policy.get("runtime_eligibility", "quarantined"),
        "evidence_tier": policy.get("evidence_tier", "unknown"),
        "rights_status": policy.get("rights_status", "unknown"),
        "rows": len(records),
        "unique_sources": len({str(row.get("source_id") or row.get("source") or "") for row in records}),
        "lineage_complete_rows": lineage_complete,
        "lineage_complete_rate": round(lineage_complete / len(records), 4) if records else 0.0,
        "explicit_open_rights_rows": rights_complete,
        "explicit_open_rights_rate": round(rights_complete / len(records), 4) if records else 0.0,
        "jurisdictions": count_values(records, "jurisdiction", "jurisdictions", "region"),
        "languages": count_values(records, "language"),
        "likely_text_languages": {
            "fr": sum(likely_french_text(str(record.get("text") or "")) for record in records),
            "other_or_unknown": sum(not likely_french_text(str(record.get("text") or "")) for record in records),
        },
        "crops": count_values(records, "chunk_crops", "crops"),
        "topics": count_values(records, "chunk_topics"),
        "source_types": count_values(records, "source_type"),
        "retrieval_policies": count_values(records, "retrieval_policy"),
        "sources": count_values(records, "source_id"),
    }


def graph_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    kinds = Counter(str(node.get("kind") or "unknown") for node in nodes)
    sources = Counter(str(node.get("source") or "project_authored") for node in nodes)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "nodes": len(nodes),
        "edges": len(edges),
        "node_kinds": dict(kinds.most_common()),
        "node_sources": dict(sources.most_common()),
    }


def candidate_summary(path: Path, active_sources: set[str]) -> dict[str, Any]:
    records = list(rows(path))
    source_ids = {str(row.get("source_id") or "") for row in records}
    return {
        "path": str(path),
        "sha256": sha256(path),
        "rows": len(records),
        "unique_sources": len(source_ids),
        "added_source_ids": sorted(source_ids - active_sources),
        "added_sources": len(source_ids - active_sources),
        "jurisdictions": count_values(records, "jurisdiction", "jurisdictions", "region"),
        "languages": count_values(records, "language"),
        "topics": count_values(records, "chunk_topics"),
    }


def build_report(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    config_path = root / args.config
    policy_path = root / args.policy
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    policy_manifest = json.loads(policy_path.read_text(encoding="utf-8"))
    policies = {str(item["path"]): item for item in policy_manifest["corpora"]}

    configured_paths = [str(item) for item in config["retrieval"]["corpus_paths"]]
    corpus_reports: list[dict[str, Any]] = []
    for relative in configured_paths:
        path = root / relative
        policy = policies.get(relative, {"runtime_eligibility": policy_manifest["default_eligibility"]})
        if not path.exists():
            corpus_reports.append(
                {
                    "path": relative,
                    "exists": False,
                    "runtime_eligibility": policy.get("runtime_eligibility"),
                }
            )
            continue
        corpus_reports.append(corpus_summary(path, policy))

    eligibility_rows: Counter[str] = Counter()
    for corpus in corpus_reports:
        eligibility_rows[str(corpus.get("runtime_eligibility") or "quarantined")] += int(corpus.get("rows") or 0)

    decisive = [item for item in corpus_reports if item.get("runtime_eligibility") == "decisive"]
    applied_context_records: list[dict[str, Any]] = []
    applied_corpus_paths: list[str] = []
    for corpus in decisive:
        relative = str(corpus["path"])
        corpus_applied = [
            record
            for record in rows(root / relative)
            if str(record.get("source_type") or "") == "applied_guidance"
            and (
                "Canada" in normalized_values(record.get("jurisdiction"))
                or "Canada" in normalized_values(record.get("jurisdictions"))
                or any(
                    province
                    in {
                        *normalized_values(record.get("jurisdiction")),
                        *normalized_values(record.get("jurisdictions")),
                        *normalized_values(record.get("region")),
                    }
                    for province in CANADIAN_PROVINCES
                )
            )
        ]
        if corpus_applied:
            applied_corpus_paths.append(relative)
            applied_context_records.extend(corpus_applied)
    applied_records = [
        record
        for record in applied_context_records
        if str(record.get("retrieval_policy") or "standard").lower() == "standard"
    ]

    applied_source_ids = {str(item.get("source_id") or "") for item in applied_records}
    applied_jurisdictions = count_values(applied_records, "jurisdiction", "jurisdictions", "region")
    applied_languages = count_values(applied_records, "language")
    applied_sources = count_values(applied_records, "source_id")
    applied_crops = count_values(applied_records, "chunk_crops", "crops")
    applied_topics = count_values(applied_records, "chunk_topics")
    applied_retrieval_policies = count_values(applied_records, "retrieval_policy")
    applied_lineage_complete = sum(
        REQUIRED_LINEAGE_FIELDS.issubset(record.get("lineage") or {})
        for record in applied_records
    )
    applied_rights_complete = sum(
        (
            (
                record.get("license_snapshot")
                or (record.get("lineage") or {}).get("license_snapshot")
                or {}
            ).get("scope_verified")
            is True
            and (
                record.get("license_snapshot")
                or (record.get("lineage") or {}).get("license_snapshot")
                or {}
            ).get("scope_basis")
            in {"source_specific_record", "jurisdiction_wide_open_licence"}
            and str(
                (
                    record.get("license_snapshot")
                    or (record.get("lineage") or {}).get("license_snapshot")
                    or {}
                ).get("scope_evidence_url")
                or ""
            ).startswith("https://")
            and (record.get("license_snapshot") or (record.get("lineage") or {}).get("license_snapshot") or {}).get(
                "permits_modification"
            )
            is True
            and (record.get("license_snapshot") or (record.get("lineage") or {}).get("license_snapshot") or {}).get(
                "permits_commercial"
            )
            is True
            and (record.get("license_snapshot") or (record.get("lineage") or {}).get("license_snapshot") or {}).get(
                "permits_redistribution"
            )
            is True
        )
        for record in applied_records
    )
    applied = {
        "path": applied_corpus_paths[0] if len(applied_corpus_paths) == 1 else "configured_decisive_canadian_applied_aggregate",
        "paths": applied_corpus_paths,
        "rows": len(applied_records),
        "unique_sources": len(applied_source_ids),
        "jurisdictions": applied_jurisdictions,
        "languages": applied_languages,
        "likely_text_languages": {
            "fr": sum(likely_french_text(str(record.get("text") or "")) for record in applied_records),
            "other_or_unknown": sum(
                not likely_french_text(str(record.get("text") or "")) for record in applied_records
            ),
        },
        "sources": applied_sources,
        "crops": applied_crops,
        "topics": applied_topics,
        "retrieval_policies": applied_retrieval_policies,
        "lineage_complete_rate": (
            round(applied_lineage_complete / len(applied_records), 4) if applied_records else 0.0
        ),
        "explicit_open_rights_rate": (
            round(applied_rights_complete / len(applied_records), 4) if applied_records else 0.0
        ),
    }
    province_counts = {
        province: applied["jurisdictions"].get(province, 0)
        for province in sorted(CANADIAN_PROVINCES)
    }
    missing_applied_provinces = [province for province, count in province_counts.items() if count == 0]
    source_counts = applied["sources"]
    largest_source_rows = max(source_counts.values(), default=0)
    largest_source_share = largest_source_rows / applied["rows"] if applied["rows"] else 0.0
    french_metadata_rows = sum(
        count for language, count in applied["languages"].items() if language.lower().startswith("fr")
    )
    french_text_rows = int(applied["likely_text_languages"]["fr"])

    graph_reports = [
        graph_summary(root / item) for item in config["retrieval"].get("graph_paths", [])
    ]
    candidate_path = root / args.candidate
    candidate = candidate_summary(candidate_path, applied_source_ids) if candidate_path.exists() else None
    candidate_policy = policies.get(args.candidate)
    candidate_activation_declared = (
        args.candidate not in configured_paths
        or (
            candidate_policy is not None
            and candidate_path.exists()
            and str(candidate_policy.get("sha256") or "") == sha256(candidate_path)
        )
    )

    tests = {
        "all_configured_corpora_exist": all(item["exists"] for item in corpus_reports),
        "all_configured_hashes_match_policy": all(
            item.get("sha256_matches_policy", True) for item in corpus_reports
        ),
        "decisive_applied_lineage_complete": applied["lineage_complete_rate"] == 1.0,
        "decisive_applied_rights_complete": applied["explicit_open_rights_rate"] == 1.0,
        "all_canadian_provinces_have_applied_chunks": not missing_applied_provinces,
        "french_applied_chunks_present": french_text_rows > 0,
        "largest_source_below_35_percent": largest_source_share <= 0.35,
        "candidate_is_not_silently_active": candidate_activation_declared,
    }
    minimum_sufficient = all(tests.values())

    findings = []
    if not applied_records:
        findings.append(
            "No Canadian applied-guidance row is eligible as standard decisive evidence; all "
            f"{len(applied_context_records)} active applied rows are context-only or require a live authority "
            "for high-consequence use."
        )
    if not tests["french_applied_chunks_present"]:
        findings.append(
            "The decisive Canadian corpus declares some bilingual source metadata but has no chunks detected as French text; French query support is routing-only."
        )
    if missing_applied_provinces:
        findings.append(
            "No decisive applied-guidance chunks exist for: " + ", ".join(missing_applied_provinces) + "."
        )
    if largest_source_share > 0.35:
        findings.append(
            f"The largest source supplies {largest_source_share:.1%} of decisive Canadian chunks, creating retrieval dominance."
        )
    findings.append(
        "Knowledge-graph size is not counted as evidence sufficiency; ontology nodes can improve vocabulary while degrading answer context."
    )
    findings.append(
        "Passing provenance and hash checks establishes fidelity to source artifacts, not agronomic correctness or local applicability."
    )

    return {
        "schema_version": "open_agronomy_agent.runtime_knowledge_sufficiency.v1",
        "audit_date": "2026-07-23",
        "config": args.config,
        "policy": args.policy,
        "policy_id": policy_manifest.get("policy_id"),
        "configured_corpora": len(configured_paths),
        "runtime_rows_by_eligibility": dict(eligibility_rows),
        "corpora": corpus_reports,
        "graphs": graph_reports,
        "decisive_canadian_applied": {
            "path": applied["path"],
            "paths": applied["paths"],
            "rows": applied["rows"],
            "unique_sources": applied["unique_sources"],
            "province_rows": province_counts,
            "missing_applied_provinces": missing_applied_provinces,
            "languages": applied["languages"],
            "french_source_metadata_rows": french_metadata_rows,
            "likely_french_text_rows": french_text_rows,
            "largest_source_share": round(largest_source_share, 4),
            "largest_sources": dict(list(source_counts.items())[:10]),
            "top_crops": dict(list(applied["crops"].items())[:20]),
            "topics": applied["topics"],
            "retrieval_policies": applied["retrieval_policies"],
            "lineage_complete_rate": applied["lineage_complete_rate"],
            "explicit_open_rights_rate": applied["explicit_open_rights_rate"],
        },
        "canadian_applied_context_rows": len(applied_context_records),
        "unpromoted_candidate": candidate,
        "sufficiency_tests": tests,
        "minimum_sufficient": minimum_sufficient,
        "findings": findings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    applied = report["decisive_canadian_applied"]
    candidate = report.get("unpromoted_candidate") or {}
    lines = [
        "# Runtime knowledge sufficiency audit",
        "",
        f"Audit date: {report['audit_date']}",
        "",
        "## Verdict",
        "",
        (
            "**Not yet sufficient as a balanced Canadian offline advisory knowledge base.**"
            if not report["minimum_sufficient"]
            else "**The minimum corpus-governance sufficiency checks pass.**"
        ),
        "",
        "The governed runtime is substantially safer than its configured row count suggests: quarantined rows do not enter model context. "
        "The decisive Canadian corpus has strong artifact lineage, but coverage is geographically and linguistically uneven. "
        "This audit does not treat corpus size, ontology size, or benchmark-shaped synthetic rows as evidence of correctness.",
        "",
        "## Governed runtime inventory",
        "",
        f"- Configured corpora: {report['configured_corpora']}",
        f"- Rows by eligibility: `{json.dumps(report['runtime_rows_by_eligibility'], sort_keys=True)}`",
        f"- Decisive Canadian applied corpus: {applied['rows']} chunks from {applied['unique_sources']} sources",
        f"- Complete source lineage: {applied['lineage_complete_rate']:.1%}",
        f"- Explicit modification/commercial/redistribution rights: {applied['explicit_open_rights_rate']:.1%}",
        f"- Rows declaring French in source metadata: {applied['french_source_metadata_rows']}",
        f"- Chunks detected as French text: {applied['likely_french_text_rows']}",
        f"- Largest-source share: {applied['largest_source_share']:.1%}",
        "",
        "## Provincial applied-guidance coverage",
        "",
        "| Province | Decisive chunks |",
        "|---|---:|",
    ]
    lines.extend(f"| {province} | {count} |" for province, count in applied["province_rows"].items())
    lines.extend(
        [
            "",
            "## Sufficiency checks",
            "",
            "| Check | Result |",
            "|---|---|",
        ]
    )
    lines.extend(
        f"| `{name}` | {'PASS' if value else 'FAIL'} |"
        for name, value in report["sufficiency_tests"].items()
    )
    lines.extend(["", "## Findings", ""])
    lines.extend(f"- {finding}" for finding in report["findings"])
    if candidate:
        lines.extend(
            [
                "",
                "## Unpromoted candidate",
                "",
                f"The candidate contains {candidate['rows']} chunks from {candidate['unique_sources']} sources "
                f"and adds {candidate['added_sources']} source IDs. It remains outside the configured runtime, as required.",
                "",
                "Its presence is evidence of a prepared promotion path, not evidence that active retrieval improved. "
                "Promotion still requires disjoint retrieval/answer evaluation, agronomic review, and runtime-image parity.",
            ]
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "A complete hash chain proves that a chunk is traceable to the reviewed source artifact. "
            "It does not prove that an old numeric recommendation is current, that a regional document applies to a field, "
            "or that the retriever selected the right passage. Those are separate currency, applicability, retrieval, and answer tests.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    report = build_report(root, args)
    json_output = root / args.json_output
    markdown_output = root / args.markdown_output
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_output), "markdown": str(markdown_output), "minimum_sufficient": report["minimum_sufficient"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
