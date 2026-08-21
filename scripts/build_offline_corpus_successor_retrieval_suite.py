#!/usr/bin/env python3
"""Build the fixed source-grounded retrieval suite for the corpus successor.

This suite measures retrieval lineage and authority boundaries, not answer
quality.  Cases without an admitted source type are retained as explicit
blocked partitions rather than fabricated from an unreviewed archive asset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import canonical_json, sha256_bytes  # noqa: E402


ACTIVE_STORE = ROOT / "data/derived/rag/offline_agronomy/active/store_manifest.json"
US_STORE = ROOT / "data/derived/rag/offline_agronomy/us_nrcs/store_manifest.json"
OUTPUT_CASES = ROOT / "data/eval/offline_corpus_retrieval.jsonl"
OUTPUT_MANIFEST = ROOT / "data/manifests/offline_corpus_retrieval_suite.json"


CANADIAN_CASES = (
    (
        "ca_official_nasdi_indicator_scope",
        "For a Canadian agricultural region, retrieve the official context that defines the National Agroclimate Series of Derived Indicators and its spatial interpretation boundary.",
        "ca_aafc_nasdi_specification",
    ),
    (
        "ca_official_slc_polygon_boundary",
        "For a Canadian field that intersects a Soil Landscapes polygon, retrieve the official source context about polygon components and the limit of point-scale inference.",
        "ca_cansis_soil_landscapes",
    ),
    (
        "ca_official_ab_nutrient_sampling",
        "Retrieve the Alberta nutrient management planning guide context for soil sampling before a variable-rate decision.",
        "ab_nutrient_management_planning_guide_2008",
    ),
    (
        "ca_official_mb_rotation_context",
        "Retrieve the Manitoba soil fertility guide context about field conditions before interpreting a current issue.",
        "mb_soil_fertility_guide",
    ),
    (
        "ca_official_canola_insect_observation",
        "For Alberta canola scouting, retrieve the official source context about clubroot risk and the limit of an unverified field observation.",
        "ab_clubroot_canola_mustard_2015",
    ),
    (
        "ca_official_alberta_range_context",
        "For an Alberta lentil field, retrieve the official source context before giving a production-management interpretation.",
        "ab_red_lentil_management_2020",
    ),
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_suite(*, active_store_path: Path, us_store_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_store = json.loads(active_store_path.read_text(encoding="utf-8"))
    canada_rows = []
    for shard in active_store.get("shards") or []:
        path = active_store_path.parent / str(shard["path"])
        canada_rows.extend(_read_jsonl(path))
    canadian_sources = {str(row.get("source_id") or "") for row in canada_rows}
    us_store = json.loads(us_store_path.read_text(encoding="utf-8"))
    mlras = sorted(str(value) for value in (us_store.get("mlra_shards") or {}))
    needed_mlras = ("001X", "002X", "003X", "004A", "005X", "006X", "007X", "008X", "009X", "010X", "011X", "012X")
    if any(source not in canadian_sources for _case, _question, source in CANADIAN_CASES):
        raise ValueError("Canadian master does not contain every preregistered source")
    if any(mlra not in mlras for mlra in needed_mlras):
        raise ValueError("U.S. store does not contain every preregistered MLRA")

    cases: list[dict[str, Any]] = []
    for case_id, question, source_id in CANADIAN_CASES:
        cases.append(
            {
                "schema_version": "open_agronomy_agent.source_grounded_retrieval_case.v1",
                "case_id": case_id,
                "partition": "canadian_official_source",
                "case_status": "active",
                "question": question,
                "question_origin": "project_authored_source_grounded_not_real_user",
                "claim_eligible": False,
                "expected_source_ids": [source_id],
                "forbidden_evidence_tiers": ["US_government_analogue_reference", "community_experience"],
                "expected_retrieval_policy": ["context_only", "requires_live_authority"],
                "expected_locator_precision": "page_char_span",
            }
        )
    for mlra in needed_mlras:
        cases.append(
            {
                "schema_version": "open_agronomy_agent.source_grounded_retrieval_case.v1",
                "case_id": f"us_analogue_{mlra.casefold()}",
                "partition": "us_analogue_context",
                "case_status": "active",
                "question": f"For a United States USDA NRCS ecological-site comparison, retrieve analogue context for MLRA {mlra}.",
                "question_origin": "project_authored_source_grounded_not_real_user",
                "claim_eligible": False,
                "expected_source_ids": ["nrcs_edit_ecological_site_description_json"],
                "expected_mlra": mlra,
                "required_transfer_scope": "US_analogue_context_only",
                "required_applicability_boundary_fragment": "cannot establish Canadian",
                "expected_retrieval_policy": ["context_only"],
                "expected_locator_precision": "json_document_chunk",
            }
        )
    cases.extend(
        [
            {
                "schema_version": "open_agronomy_agent.source_grounded_retrieval_case.v1",
                "case_id": "table_ontario_field_crop_context",
                "partition": "table_and_layout",
                "case_status": "active",
                "question": "Retrieve the Ontario field crop production workbook table context for a Canadian crop statistics question.",
                "question_origin": "project_authored_source_grounded_not_real_user",
                "claim_eligible": False,
                "expected_source_ids": ["on_field_crop_production_current"],
                "expected_locator_precision": "table_cells",
                "expected_retrieval_policy": ["context_only"],
                "forbidden_evidence_tiers": ["US_government_analogue_reference", "community_experience"],
            },
            {
                "schema_version": "open_agronomy_agent.source_grounded_retrieval_case.v1",
                "case_id": "community_boundary_negative",
                "partition": "community_boundary_negative",
                "case_status": "active",
                "question": "What do archived community forum posts say about a Canadian fertilizer recommendation?",
                "question_origin": "project_authored_boundary_control_not_real_user",
                "claim_eligible": False,
                "expected_source_ids": [],
                "forbidden_evidence_tiers": ["community_experience"],
                "expect_no_admitted_community_context": True,
            },
            {
                "schema_version": "open_agronomy_agent.source_grounded_retrieval_case.v1",
                "case_id": "canadian_authority_negative",
                "partition": "negative_retrieval",
                "case_status": "active",
                "question": "Set the exact legal fertilizer rate for a Saskatchewan canola field using a U.S. ecological-site description.",
                "question_origin": "project_authored_boundary_control_not_real_user",
                "claim_eligible": False,
                "expected_source_ids": [],
                "forbidden_evidence_tiers": ["US_government_analogue_reference"],
                "expect_no_us_analogue_context": True,
            },
            {
                "schema_version": "open_agronomy_agent.source_grounded_retrieval_case.v1",
                "case_id": "spatial_context_blocked",
                "partition": "spatial_context_boundary",
                "case_status": "blocked_no_admitted_portable_spatial_source",
                "blocking_reason": "Historical spatial layers remain optional-pack candidates pending source and field-boundary review.",
            },
        ]
    )
    cases.sort(key=lambda value: str(value["case_id"]))
    active = [case for case in cases if case["case_status"] == "active"]
    manifest: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.source_grounded_retrieval_suite.v1",
        "suite_id": "offline-agronomy-corpus-successor-retrieval-v1",
        "status": "frozen_before_retriever_tuning",
        "case_file": "data/eval/offline_corpus_retrieval.jsonl",
        "case_count": len(cases),
        "active_case_count": len(active),
        "blocked_case_count": len(cases) - len(active),
        "partitions": sorted({str(case["partition"]) for case in cases}),
        "active_store": active_store_path.relative_to(ROOT).as_posix(),
        "active_store_sha256": active_store["store_sha256"],
        "us_reference_store": us_store_path.relative_to(ROOT).as_posix(),
        "us_reference_store_sha256": us_store["store_sha256"],
        "case_file_sha256": sha256_bytes("".join(canonical_json(case) + "\n" for case in cases).encode("utf-8")),
        "interpretation": "Source-grounded retrieval and authority-boundary measurement only; no answer-quality, population, or agronomist-equivalence claim.",
    }
    manifest["suite_sha256"] = sha256_bytes(canonical_json(manifest).encode("utf-8"))
    return cases, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-store", type=Path, default=ACTIVE_STORE)
    parser.add_argument("--us-store", type=Path, default=US_STORE)
    parser.add_argument("--output-cases", type=Path, default=OUTPUT_CASES)
    parser.add_argument("--output-manifest", type=Path, default=OUTPUT_MANIFEST)
    args = parser.parse_args()
    cases, manifest = build_suite(active_store_path=args.active_store, us_store_path=args.us_store)
    args.output_cases.parent.mkdir(parents=True, exist_ok=True)
    args.output_cases.write_text("".join(canonical_json(case) + "\n" for case in cases), encoding="utf-8")
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": manifest["case_count"], "active": manifest["active_case_count"], "suite_sha256": manifest["suite_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
