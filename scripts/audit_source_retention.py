#!/usr/bin/env python3
"""Reconcile source bytes, governed knowledge surfaces, and retention gates.

This audit never deletes data. It is the evidence gate that must pass before a
source, full corpus, shard set, or historical build can be proposed for removal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml

from agronomy_agent.corpus_governance import audit_runtime_corpora, load_corpus_policy


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_WORKSPACE = ROOT.parents[1]
FACETS: dict[str, str] = {
    "site_context": r"\bgeneral information\b",
    "soil_water": r"\bwater features\b|\bsoil features\b",
    "ecological_dynamics": r"\becological dynamics\b",
    "interpretations": r"\binterpretations\b",
    "physiography_climate": r"\bphysiographic features\b|\bclimatic features\b",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
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


def content_fingerprint(row: dict[str, Any]) -> str:
    payload = "\0".join(
        [
            str(row.get("source_id") or row.get("source") or ""),
            str(row.get("title") or ""),
            str(row.get("text") or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_id(row: dict[str, Any]) -> str:
    return str(row.get("source_id") or row.get("source") or "")


def admitted_canadian_sources(
    artifact_root: Path,
    config: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    by_policy = {str(item["path"]): item for item in policy.get("corpora") or []}
    records: list[dict[str, Any]] = []
    paths: list[str] = []
    for relative in config["retrieval"]["corpus_paths"]:
        item = by_policy.get(str(relative)) or {}
        if item.get("runtime_eligibility") not in {"decisive", "context_only"}:
            continue
        if not (
            item.get("evidence_tier") == "curated_canadian_source"
            or item.get("store_profile_id") == "canada-offline-master"
        ):
            continue
        path = artifact_root / str(relative)
        if not path.is_file():
            continue
        paths.append(str(relative))
        records.extend(jsonl_rows(path))

    source_rows: Counter[str] = Counter(source_id(row) for row in records)
    lineage_complete = 0
    expected_raw_hashes: dict[str, set[str]] = defaultdict(set)
    for row in records:
        lineage = row.get("lineage") if isinstance(row.get("lineage"), dict) else {}
        if all(lineage.get(key) for key in ("source_id", "raw_sha256", "chunk_sha256", "manifest_sha256")):
            lineage_complete += 1
        if lineage.get("raw_sha256"):
            expected_raw_hashes[source_id(row)].add(str(lineage["raw_sha256"]))
    return {
        "paths": paths,
        "records": records,
        "rows": len(records),
        "source_rows": dict(sorted(source_rows.items())),
        "unique_sources": len(source_rows),
        "lineage_complete_rows": lineage_complete,
        "lineage_complete_rate": round(lineage_complete / max(1, len(records)), 6),
        "expected_raw_hashes": expected_raw_hashes,
    }


def verify_source_bytes(source_workspace: Path, expected: dict[str, set[str]]) -> dict[str, Any]:
    raw_root = source_workspace / "data/raw"
    rows: list[dict[str, Any]] = []
    for source, expected_hashes in sorted(expected.items()):
        directories = [path for path in raw_root.rglob(source) if path.is_dir()]
        candidates = [
            path
            for directory in directories
            for path in directory.rglob("*")
            if path.is_file()
            and not path.name.endswith(".lineage.json")
            and path.name not in {"manifest.json", "ingest_summary.json"}
        ]
        matched: dict[str, str] = {}
        for path in candidates:
            actual = sha256(path)
            if actual in expected_hashes:
                matched[actual] = str(path)
        missing = sorted(expected_hashes - set(matched))
        rows.append(
            {
                "source_id": source,
                "expected_raw_hashes": sorted(expected_hashes),
                "matched_paths": matched,
                "missing_raw_hashes": missing,
                "status": "verified" if not missing else "missing_exact_source_bytes",
            }
        )
    return {
        "sources_checked": len(rows),
        "sources_verified": sum(row["status"] == "verified" for row in rows),
        "sources_missing_exact_bytes": [
            row["source_id"] for row in rows if row["status"] != "verified"
        ],
        "rows": rows,
    }


def nrcs_projection_audit(source_workspace: Path, compact_path: Path) -> dict[str, Any]:
    full_path = source_workspace / "data/derived/rag/nrcs_esd_rag_corpus.jsonl"
    summary_path = source_workspace / "data/derived/rag/nrcs_esd_summary.json"
    raw_dir = source_workspace / "data/raw/documents/nrcs_esd_json"
    full_rows: dict[str, dict[str, Any]] = {}
    full_sites: dict[tuple[str, str], set[str]] = defaultdict(set)
    full_facets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in jsonl_rows(full_path):
        doc_id = str(row.get("doc_id") or "")
        full_rows[doc_id] = row
        site = (str(row.get("mlra") or ""), str(row.get("ecological_site_id") or ""))
        full_sites[site].add(doc_id)
        text = str(row.get("text") or "")
        for facet, pattern in FACETS.items():
            if re.search(pattern, text, re.IGNORECASE):
                full_facets[site].add(facet)

    compact_sites: dict[tuple[str, str], set[str]] = defaultdict(set)
    compact_facets: dict[tuple[str, str], set[str]] = defaultdict(set)
    exact_text_matches = 0
    boundary_rows = 0
    compact_rows = 0
    for row in jsonl_rows(compact_path):
        compact_rows += 1
        doc_id = str(row.get("doc_id") or "")
        site = (str(row.get("mlra") or ""), str(row.get("ecological_site_id") or ""))
        compact_sites[site].add(doc_id)
        compact_facets[site].update(str(value) for value in row.get("compact_facets") or [])
        source_row = full_rows.get(doc_id)
        exact_text_matches += int(source_row is not None and source_row.get("text") == row.get("text"))
        boundary_rows += int(
            row.get("retrieval_policy") == "context_only"
            and row.get("transfer_scope") == "cross_border_analogue"
            and row.get("jurisdiction") == ["United States"]
        )

    facet_coverage: dict[str, dict[str, Any]] = {}
    for facet in FACETS:
        available = {site for site, values in full_facets.items() if facet in values}
        preserved = {site for site in available if facet in compact_facets.get(site, set())}
        facet_coverage[facet] = {
            "available_sites": len(available),
            "preserved_sites": len(preserved),
            "coverage_rate": round(len(preserved) / max(1, len(available)), 6),
        }

    acquisition = json.loads(summary_path.read_text(encoding="utf-8"))
    raw_json_count = sum(1 for _ in raw_dir.glob("*/*.json"))
    required_facets = ("site_context", "soil_water", "ecological_dynamics", "interpretations")
    checks = {
        "all_discovered_sites_ingested": (
            len(full_sites) == int(acquisition.get("ecoclasses_available") or 0)
            and not acquisition.get("failures")
        ),
        "all_full_sites_represented": set(full_sites) == set(compact_sites),
        "all_compact_text_exact_from_full": exact_text_matches == compact_rows,
        "all_rows_cross_border_context_bounded": boundary_rows == compact_rows,
        "all_raw_site_json_present": raw_json_count == len(full_sites),
        "required_facets_fully_preserved": all(
            facet_coverage[facet]["coverage_rate"] == 1.0 for facet in required_facets
        ),
    }
    return {
        "full_path": str(full_path),
        "full_sha256": sha256(full_path),
        "full_rows": len(full_rows),
        "full_sites": len(full_sites),
        "source_catalog_sites": acquisition.get("ecoclasses_available"),
        "source_failures": acquisition.get("failures") or [],
        "raw_site_json_files": raw_json_count,
        "compact_path": str(compact_path),
        "compact_sha256": sha256(compact_path),
        "compact_rows": compact_rows,
        "compact_sites": len(compact_sites),
        "exact_text_matches": exact_text_matches,
        "boundary_rows": boundary_rows,
        "facet_coverage": facet_coverage,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "blocked",
        "retention_decision": (
            "retain_full_reference_and_raw_json; compact_v2_is_promotable_but_no_deletion_authorized"
        ),
    }


def historical_candidate_audit(
    source_workspace: Path,
    admitted_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    admitted_fingerprints = {content_fingerprint(row) for row in admitted_records}
    admitted_sources = {source_id(row) for row in admitted_records}
    rag_dir = source_workspace / "data/derived/rag"
    candidates = sorted(rag_dir.glob("canada_agronomy_distributable*.jsonl"))
    rows: list[dict[str, Any]] = []
    for path in candidates:
        if path.name == "canada_agronomy_distributable_v13.jsonl":
            continue
        records = list(jsonl_rows(path))
        fingerprints = [content_fingerprint(row) for row in records]
        sources = {source_id(row) for row in records}
        exact = sum(value in admitted_fingerprints for value in fingerprints)
        missing_sources = sorted(sources - admitted_sources)
        admitted_source_rows = [
            row for row in records if source_id(row) in admitted_sources
        ]
        admitted_source_exact = sum(
            content_fingerprint(row) in admitted_fingerprints
            for row in admitted_source_rows
        )
        missing_source_row_counts = Counter(
            source_id(row) for row in records if source_id(row) in missing_sources
        )
        admitted_source_coverage = round(
            admitted_source_exact / max(1, len(admitted_source_rows)), 6
        )
        only_explicitly_unadmitted_content_missing = bool(
            missing_sources
            and admitted_source_coverage == 1.0
            and exact + sum(missing_source_row_counts.values()) == len(records)
        )
        rows.append(
            {
                "path": str(path),
                "sha256": sha256(path),
                "rows": len(records),
                "unique_sources": len(sources),
                "exact_content_rows_in_admitted_runtime": exact,
                "exact_content_coverage_rate": round(exact / max(1, len(records)), 6),
                "admitted_source_rows": len(admitted_source_rows),
                "admitted_source_exact_rows": admitted_source_exact,
                "admitted_source_exact_coverage_rate": admitted_source_coverage,
                "source_ids_absent_from_admitted_runtime": missing_sources,
                "unadmitted_source_row_counts": dict(sorted(missing_source_row_counts.items())),
                "only_explicitly_unadmitted_content_missing": only_explicitly_unadmitted_content_missing,
                "retention_decision": (
                    "archive_redundant_build_after_unadmitted_source_receipt_is_retained"
                    if only_explicitly_unadmitted_content_missing
                    else "blocked_from_deletion_pending_source_disposition"
                    if missing_sources or admitted_source_coverage != 1.0
                    else "reproducible_duplicate_candidate"
                ),
            }
        )
    return rows


def unadmitted_candidate_source_receipts(
    source_workspace: Path,
    admitted_sources: set[str],
) -> dict[str, Any]:
    latest = source_workspace / "data/derived/rag/canada_agronomy_distributable_v12_candidate.jsonl"
    expected: dict[str, set[str]] = defaultdict(set)
    for row in jsonl_rows(latest):
        source = source_id(row)
        if source in admitted_sources:
            continue
        lineage = row.get("lineage") if isinstance(row.get("lineage"), dict) else {}
        if lineage.get("raw_sha256"):
            expected[source].add(str(lineage["raw_sha256"]))
    byte_receipts = verify_source_bytes(source_workspace, expected)
    rights_files: dict[str, list[str]] = defaultdict(list)
    manifest_root = source_workspace / "data/manifests"
    candidates = [
        *manifest_root.glob("*rights*review*.json"),
        *manifest_root.glob("*admission*queue*.json"),
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        for source in expected:
            if source in text:
                rights_files[source].append(str(path))
    return {
        "latest_candidate": str(latest),
        "source_bytes": byte_receipts,
        "rights_or_admission_receipts": dict(sorted(rights_files.items())),
        "status": (
            "verified"
            if not byte_receipts["sources_missing_exact_bytes"]
            and all(rights_files.get(source) for source in expected)
            else "blocked"
        ),
    }


def graph_audit(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in config["retrieval"].get("graph_paths") or []:
        path = root / str(relative)
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "path": str(relative),
                "sha256": sha256(path),
                "nodes": len(payload.get("nodes") or []),
                "edges": len(payload.get("edges") or []),
                "knowledge_role": (
                    "soil_ontology_and_relations"
                    if "soilwise" in str(relative)
                    else "project_authored_domain_relations"
                ),
            }
        )
    return rows


def markdown(report: dict[str, Any]) -> str:
    nrcs = report["nrcs"]
    source = report["canadian_source_bytes"]
    graphs = report["knowledge_graphs"]
    lines = [
        "# Source retention audit",
        "",
        f"Status: **{report['status']}**. No deletion was performed or authorized.",
        "",
        "## Governed runtime",
        "",
        f"- Corpus audit: {report['runtime_corpus_audit']['status']}",
        f"- Admitted Canadian rows checked: {report['canadian_rag']['rows']}",
        f"- Canadian sources with complete row lineage: {report['canadian_rag']['lineage_complete_rate']:.1%}",
        f"- Exact source-byte sets verified: {source['sources_verified']}/{source['sources_checked']}",
        *[
            f"- Knowledge graph `{row['path']}`: {row['nodes']} nodes, {row['edges']} edges, SHA-256 `{row['sha256']}`"
            for row in graphs
        ],
        "",
        "## NRCS reference and compact projection",
        "",
        f"- Official catalog/source sites: {nrcs['source_catalog_sites']}",
        f"- Full rows: {nrcs['full_rows']}; compact rows: {nrcs['compact_rows']}",
        f"- Compact site coverage: {nrcs['compact_sites']}/{nrcs['full_sites']}",
        f"- Exact source-text projection: {nrcs['exact_text_matches']}/{nrcs['compact_rows']}",
    ]
    for facet, values in nrcs["facet_coverage"].items():
        lines.append(
            f"- {facet}: {values['preserved_sites']}/{values['available_sites']} "
            f"({values['coverage_rate']:.1%})"
        )
    lines.extend(
        [
            "",
            "The full NRCS corpus and raw JSON remain retained as the reference. The compact projection is an explicit US cross-border analogue, not Canadian field truth or authority.",
            "",
            "## Historical Canadian builds",
            "",
        ]
    )
    for row in report["historical_canadian_candidates"]:
        lines.append(
            f"- `{Path(row['path']).name}`: {row['admitted_source_exact_coverage_rate']:.1%} exact coverage "
            f"for admitted sources; {row['unadmitted_source_row_counts']}; {row['retention_decision']}."
        )
    lines.extend(
        [
            "",
            "## Knowledge-surface boundary",
            "",
            "Official document claims live in governed RAG with row lineage. SoilWise contributes both RAG concepts and an ontology graph. Spatial survey values remain queryable spatial evidence. A source does not need to be duplicated into the ontology graph to count as processed, but it must be reachable through its appropriate governed surface.",
            "",
            "## Deletion gate",
            "",
            "No artifact is approved for deletion by this report. A later deletion manifest must identify exact paths, hashes, replacement artifacts, rebuild commands, and passing retrieval/package tests.",
            "",
        ]
    )
    unadmitted = report["unadmitted_candidate_source_receipts"]
    lines.append(
        f"Unadmitted candidate-source receipts: {unadmitted['status']}; exact bytes and rights/admission records are retained separately from historical generated corpora."
    )
    lines.append("")
    return "\n".join(lines)


def portable_receipt(report: dict[str, Any]) -> dict[str, Any]:
    """Remove workstation paths while retaining the deletion-gate evidence."""

    source_rows = report["canadian_source_bytes"]["rows"]
    unadmitted = report["unadmitted_candidate_source_receipts"]
    nrcs = report["nrcs"]
    return {
        "schema_version": "open_agronomy_agent.source_retention_receipt.v2",
        "status": report["status"],
        "deletion_authorized": False,
        "evidence_boundary": {
            "receipt_mode": "fresh_maintainer_source_workspace_audit",
            "current_runtime_and_store_revalidated": True,
            "raw_source_archive_mounted": True,
            "raw_source_bytes_revalidated_in_this_audit": True,
            "note": (
                "This output is produced only after the requested maintainer source "
                "workspace and full NRCS reference have been read and verified."
            ),
        },
        "checks": report["checks"],
        "governed_canadian_rag": {
            "configured_paths": report["canadian_rag"]["paths"],
            "rows": report["canadian_rag"]["rows"],
            "sources": report["canadian_rag"]["unique_sources"],
            "lineage_complete_rate": report["canadian_rag"]["lineage_complete_rate"],
            "exact_source_byte_receipts": [
                {
                    "source_id": row["source_id"],
                    "expected_raw_hashes": row["expected_raw_hashes"],
                    "status": row["status"],
                    "verification_basis": "fresh_exact_source_byte_match",
                }
                for row in source_rows
            ],
        },
        "knowledge_graphs": report["knowledge_graphs"],
        "nrcs_reference_projection": {
            key: nrcs[key]
            for key in (
                "status",
                "source_catalog_sites",
                "source_failures",
                "raw_site_json_files",
                "full_rows",
                "full_sites",
                "full_sha256",
                "compact_path",
                "compact_rows",
                "compact_sites",
                "compact_sha256",
                "exact_text_matches",
                "facet_coverage",
                "checks",
                "retention_decision",
            )
        },
        "unadmitted_candidate_sources": {
            "status": unadmitted["status"],
            "source_receipts": [
                {
                    "source_id": row["source_id"],
                    "expected_raw_hashes": row["expected_raw_hashes"],
                    "status": row["status"],
                    "rights_or_admission_receipt_count": len(
                        unadmitted["rights_or_admission_receipts"].get(row["source_id"], [])
                    ),
                }
                for row in unadmitted["source_bytes"]["rows"]
            ],
        },
        "historical_canadian_builds": [
            {
                "name": Path(row["path"]).name,
                "sha256": row["sha256"],
                "rows": row["rows"],
                "admitted_source_exact_coverage_rate": row[
                    "admitted_source_exact_coverage_rate"
                ],
                "unadmitted_source_row_counts": row["unadmitted_source_row_counts"],
                "retention_decision": row["retention_decision"],
            }
            for row in report["historical_canadian_candidates"]
        ],
        "deletion_gate": (
            "No deletion is authorized. A separate approval must bind exact paths, hashes, "
            "replacement artifacts, rebuild commands, and passing retrieval/package tests."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-workspace", type=Path, default=DEFAULT_SOURCE_WORKSPACE)
    parser.add_argument("--rag-config", default="configs/rag.yaml")
    parser.add_argument("--json-output", type=Path, default=Path("outputs/pre_demo_core/source_retention_audit.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("outputs/pre_demo_core/source_retention_audit.md"))
    parser.add_argument(
        "--receipt-output",
        type=Path,
        default=Path("data/manifests/source_retention_receipt.json"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    source_workspace = args.source_workspace.resolve()
    config_path = root / args.rag_config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    retrieval = config["retrieval"]
    artifact_root_value = retrieval.get("artifact_root")
    artifact_root = (
        (config_path.parent / str(artifact_root_value)).resolve()
        if artifact_root_value
        else root
    )
    policy = load_corpus_policy(artifact_root, retrieval["corpus_policy_manifest"])
    runtime_audit = audit_runtime_corpora(root=root, rag_config_path=config_path)
    canadian = admitted_canadian_sources(artifact_root, config, policy)
    source_bytes = verify_source_bytes(source_workspace, canadian["expected_raw_hashes"])
    nrcs = nrcs_projection_audit(
        source_workspace,
        root / "data/derived/rag/nrcs_esd_rag_corpus_compact_v2.jsonl",
    )
    nrcs["compact_path"] = "data/derived/rag/nrcs_esd_rag_corpus_compact_v2.jsonl"
    historical = historical_candidate_audit(source_workspace, canadian["records"])
    unadmitted_receipts = unadmitted_candidate_source_receipts(
        source_workspace,
        set(canadian["source_rows"]),
    )
    knowledge_graphs = graph_audit(root, config)
    checks = {
        "runtime_corpus_audit_passed": runtime_audit.get("status") == "pass",
        "canadian_lineage_complete": canadian["lineage_complete_rate"] == 1.0,
        "canadian_exact_source_bytes_verified": not source_bytes["sources_missing_exact_bytes"],
        "nrcs_projection_passed": nrcs["status"] == "pass",
        "knowledge_graphs_verified": bool(knowledge_graphs)
        and all(row["nodes"] > 0 and row["edges"] > 0 for row in knowledge_graphs),
        "unadmitted_candidate_source_receipts_verified": unadmitted_receipts["status"] == "verified",
    }
    report = {
        "schema_version": "open_agronomy_agent.source_retention_audit.v1",
        "root": str(root),
        "source_workspace": str(source_workspace),
        "deletion_authorized": False,
        "runtime_corpus_audit": runtime_audit,
        "canadian_rag": {key: value for key, value in canadian.items() if key not in {"records", "expected_raw_hashes"}},
        "canadian_source_bytes": source_bytes,
        "knowledge_graphs": knowledge_graphs,
        "nrcs": nrcs,
        "historical_canadian_candidates": historical,
        "unadmitted_candidate_source_receipts": unadmitted_receipts,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "blocked",
    }
    json_output = args.json_output if args.json_output.is_absolute() else root / args.json_output
    markdown_output = args.markdown_output if args.markdown_output.is_absolute() else root / args.markdown_output
    receipt_output = args.receipt_output if args.receipt_output.is_absolute() else root / args.receipt_output
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_output.write_text(markdown(report), encoding="utf-8")
    receipt_output.write_text(json.dumps(portable_receipt(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": checks, "json": str(json_output), "markdown": str(markdown_output), "receipt": str(receipt_output)}, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
