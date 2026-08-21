#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "derived" / "rag" / "nrcs_esd_rag_corpus.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "nrcs_esd_rag_corpus_compact_v2.jsonl"
DEFAULT_SUMMARY = ROOT / "data" / "derived" / "rag" / "nrcs_esd_compact_v2_summary.json"

PRIORITY_TERMS = (
    "ecological site",
    "general information",
    "mlra notes",
    "physiographic",
    "climatic",
    "water features",
    "soil features",
    "soil texture",
    "drainage",
    "water table",
    "slope",
    "precipitation",
    "temperature",
    "plant community",
    "management",
)

# The full EDIT record is ordered by section. A global keyword score tended to
# choose three adjacent climate/soil chunks and discard nearly every site's
# ecological-dynamics and interpretation sections. These facets preserve the
# minimum useful ecological-site model while keeping the offline projection
# bounded. Order is intentional when ``--chunks-per-site`` is constrained.
FACET_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("site_context", (r"\bgeneral information\b",)),
    ("soil_water", (r"\bwater features\b", r"\bsoil features\b")),
    ("ecological_dynamics", (r"\becological dynamics\b",)),
    ("interpretations", (r"\binterpretations\b",)),
    ("physiography_climate", (r"\bphysiographic features\b", r"\bclimatic features\b")),
)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def priority(row: dict[str, Any]) -> tuple[int, int]:
    text = " ".join([str(row.get("title", "")), str(row.get("text", ""))]).lower()
    score = sum(1 for term in PRIORITY_TERMS if term in text)
    # Keep early chunks when scores tie because they usually contain the site concept and MLRA context.
    return score, -int(row.get("chunk_index", 9999))


def matched_facets(row: dict[str, Any]) -> tuple[str, ...]:
    text = str(row.get("text") or "").lower()
    return tuple(
        name
        for name, patterns in FACET_PATTERNS
        if any(re.search(pattern, text) for pattern in patterns)
    )


def portable_extraction(row: dict[str, Any]) -> dict[str, Any] | None:
    """Remove ingest-host paths while retaining a reproducible raw-file locator."""

    original = row.get("extraction")
    if not isinstance(original, dict):
        return None
    extraction = dict(original)
    legacy_raw_path = extraction.pop("raw_path", None)
    locator = extraction.get("raw_locator")
    if legacy_raw_path is not None or locator is not None:
        mlra = str(row.get("mlra") or "").strip()
        site_id = str(row.get("ecological_site_id") or "").strip()
        if not mlra or not site_id:
            raise ValueError("NRCS row with raw provenance is missing MLRA or ecological-site ID")
        extraction["raw_locator"] = {
            "base": "nrcs_esd_ingest_raw_dir",
            "path": f"{mlra}/{site_id}.json",
        }
    return extraction


def portable_path_hint(path: Path) -> str:
    """Describe a generated artifact without serializing a workstation path."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def select_site_rows(
    candidates: list[dict[str, Any]],
    *,
    chunks_per_site: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    facets_by_id = {
        str(row.get("doc_id") or id(row)): matched_facets(row)
        for row in candidates
    }
    for facet, _patterns in FACET_PATTERNS:
        if len(selected) >= chunks_per_site:
            break
        matches = [
            row
            for row in candidates
            if facet in facets_by_id[str(row.get("doc_id") or id(row))]
            and str(row.get("doc_id") or id(row)) not in selected_ids
        ]
        if not matches:
            continue
        # The first chunk carrying a section heading contains the section's
        # definition or central concept; later chunks usually contain tables.
        chosen = min(matches, key=lambda row: int(row.get("chunk_index", 9999)))
        selected.append(chosen)
        selected_ids.add(str(chosen.get("doc_id") or id(chosen)))

    if len(selected) < chunks_per_site:
        for row in sorted(candidates, key=priority, reverse=True):
            row_id = str(row.get("doc_id") or id(row))
            if row_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(row_id)
            if len(selected) >= chunks_per_site:
                break

    projected: list[dict[str, Any]] = []
    for rank, row in enumerate(
        sorted(selected, key=lambda item: int(item.get("chunk_index", 9999))),
        start=1,
    ):
        item = dict(row)
        extraction = portable_extraction(item)
        if extraction is not None:
            item["extraction"] = extraction
        item.update(
            {
                "jurisdiction": ["United States"],
                "language": ["en-US"],
                "retrieval_policy": "context_only",
                "answer_role": "cross_border_analogue",
                "transfer_scope": "cross_border_analogue",
                "applicability_boundary": "US analogue only; Canadian field validation required.",
                "content_risk_tags": [
                    "cross_jurisdiction_analogue_requires_canadian_validation"
                ],
                "retrieval_projection": "nrcs_esd_section_balanced_compact_v2",
                "compact_rank": rank,
                "compact_facets": list(matched_facets(row)),
            }
        )
        projected.append(item)
    return projected


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact NRCS ESD retrieval projection from the full JSON corpus.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--chunks-per-site", type=int, default=4)
    args = parser.parse_args()

    if args.chunks_per_site < 1:
        raise ValueError("--chunks-per-site must be at least 1")
    if not args.input.exists():
        raise FileNotFoundError(f"missing NRCS ESD corpus: {args.input}")

    input_rows = 0
    sites = 0
    compact: list[dict[str, Any]] = []
    facet_counts: Counter[str] = Counter()
    current_key: tuple[str, str] | None = None
    current_candidates: list[dict[str, Any]] = []

    def flush_site() -> None:
        nonlocal sites, current_candidates
        if not current_candidates:
            return
        selected = select_site_rows(
            current_candidates,
            chunks_per_site=args.chunks_per_site,
        )
        compact.extend(selected)
        sites += 1
        for facet in {
            facet
            for row in selected
            for facet in row.get("compact_facets") or []
        }:
            facet_counts[facet] += 1
        current_candidates = []

    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            input_rows += 1
            row = json.loads(line)
            key = (str(row.get("mlra", "")), str(row.get("ecological_site_id", row.get("doc_id", ""))))
            if current_key is not None and key != current_key:
                flush_site()
            current_key = key
            current_candidates.append(row)
    flush_site()

    write_jsonl(args.output, compact)
    summary = {
        "input_rows": input_rows,
        "output_rows": len(compact),
        "sites": sites,
        "chunks_per_site": args.chunks_per_site,
        "selection_method": "section_balanced_v2",
        "site_facet_counts": dict(sorted(facet_counts.items())),
        "transfer_scope": "cross_border_analogue",
        "deletion_gate": "full corpus must be retained until this projection passes source coverage and retrieval validation",
        "output": portable_path_hint(args.output),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
