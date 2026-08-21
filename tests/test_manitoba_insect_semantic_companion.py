from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from agronomy_agent.agno_runtime.local_index import LexicalRetriever


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "mb_2026_canola_insect_scouting"
RAW_SHA256 = "1faefa12d43bed5565c175bf41b672e9d437c7d0021a4db970e17d569ab9909c"
SOURCE_MANIFEST = ROOT / "data/manifests/canada_agronomy_sources.json"
COMPANION_PATH = (
    ROOT
    / "data/curated/canada_agronomy/mb_2026_canola_insect_scouting.2026-08-14.semantic.json"
)
STORE_ROOT = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_record() -> dict:
    manifest = _load_json(SOURCE_MANIFEST)
    return next(source for source in manifest["sources"] if source["id"] == SOURCE_ID)


def _source_rows() -> list[dict]:
    rows: list[dict] = []
    for shard_path in sorted((STORE_ROOT / "shards").glob("*.jsonl")):
        for line in shard_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("source_id") == SOURCE_ID:
                rows.append(row)
    return rows


def test_manitoba_insect_source_is_exactly_pinned_openmb_companion_only() -> None:
    source = _source_record()
    companion = _load_json(COMPANION_PATH)

    assert source["download_url"] == (
        "https://www.gov.mb.ca/agriculture/crops/guides-and-publications/"
        "pubs/guide-crop-protection-insects-2026.pdf"
    )
    assert source["expected_raw_sha256"] == RAW_SHA256
    assert source["jurisdiction"] == ["Manitoba"]
    assert source["default_retrieval_policy"] == "context_only"
    assert source["currency"] == {
        "status": "current_2026_edition",
        "review_interval_days": 90,
        "volatile": True,
    }
    assert source["regulatory"] == {
        "regulated_advice": True,
        "require_live_authority": True,
    }

    licence = source["license"]
    assert licence["status"] == "redistributable"
    assert licence["identifier"] == "OpenMB Information and Data Use Licence"
    assert licence["scope_verified"] is True
    assert licence["scope_basis"] == "jurisdiction_wide_open_licence"
    assert licence["scope_evidence_url"] == "https://www.gov.mb.ca/legal/copyright.html"
    assert licence["permits_modification"] is True
    assert licence["permits_commercial"] is True
    assert licence["permits_redistribution"] is True
    assert licence["third_party_risk"] is True

    ingest = source["ingest_policy"]
    assert ingest["emit_source_chunks"] is False
    assert ingest["include_page_ranges"] == [[1, 1], [12, 13]]
    assert ingest["semantic_companion_path"] == (
        "data/curated/canada_agronomy/"
        "mb_2026_canola_insect_scouting.2026-08-14.semantic.json"
    )
    assert ingest["semantic_companion_sha256"] == hashlib.sha256(
        COMPANION_PATH.read_bytes()
    ).hexdigest()
    assert source["use_policy"] == {
        "discover": True,
        "download": True,
        "local_rag": True,
        "distributable_bundle": True,
        "training": False,
        "live_retrieval": True,
    }

    assert companion["source_raw_sha256"] == RAW_SHA256
    assert companion["reviewed_on"] == "2026-08-14"
    assert [record["source_pages"] for record in companion["records"]] == [
        [1],
        [12, 13],
        [12, 13],
        [13],
        [13],
    ]


def test_manitoba_insect_model_text_excludes_products_marks_and_third_party_image() -> None:
    companion = _load_json(COMPANION_PATH)
    model_text = "\n".join(record["text"] for record in companion["records"])

    assert not re.search(
        r"\b(?:Fortenza|Coragen|Shenzi|Cosayr|Vermis|Rorvik|Maxunitech|"
        r"Lagon|Cygon|Diamante|Malathion)\b",
        model_text,
        re.IGNORECASE,
    )
    assert not re.search(r"\b\d+(?:\.\d+)?\s*(?:mL|L|g)\s*/", model_text)
    assert "North Dakota State University" not in model_text
    assert "Manitoba logo" not in model_text
    assert "PMRA label" in model_text


def test_manitoba_insect_master_separates_methods_from_current_thresholds() -> None:
    source = _source_record()
    companion = _load_json(COMPANION_PATH)
    rows = _source_rows()

    assert len(rows) == 5
    assert Counter(row["retrieval_policy"] for row in rows) == {
        "context_only": 3,
        "requires_live_authority": 2,
    }
    assert {
        row["doc_id"]
        for row in rows
        if row["retrieval_policy"] == "context_only"
    } == {
        f"{SOURCE_ID}_semantic_0001",
        f"{SOURCE_ID}_semantic_0002",
        f"{SOURCE_ID}_semantic_0004",
    }
    assert {
        row["doc_id"]
        for row in rows
        if row["retrieval_policy"] == "requires_live_authority"
    } == {
        f"{SOURCE_ID}_semantic_0003",
        f"{SOURCE_ID}_semantic_0005",
    }

    expected_records = {
        f"{SOURCE_ID}_semantic_{index:04d}": record
        for index, record in enumerate(companion["records"], start=1)
    }
    for row in rows:
        expected = expected_records[row["doc_id"]]
        assert row["title"] == expected["title"]
        assert row["text"] == expected["text"]
        assert row["lineage"]["raw_sha256"] == RAW_SHA256
        assert row["lineage"]["expected_raw_sha256"] == RAW_SHA256
        assert row["license_snapshot"] == row["lineage"]["license_snapshot"]
        assert row["license_snapshot"]["attribution"] == source["license"]["attribution"]
        assert row["semantic_companion"]["companion_sha256"] == source["ingest_policy"][
            "semantic_companion_sha256"
        ]
        assert row["lineage"]["semantic_companion"]["parent_raw_sha256"] == RAW_SHA256
        if row["retrieval_policy"] == "requires_live_authority":
            assert "numeric_pest_threshold_requires_current_local_authority" in row[
                "content_risk_tags"
            ]
            assert "live_authority_required" in row["content_risk_tags"]


def test_context_filter_can_answer_scouting_method_without_admitting_threshold_rows() -> None:
    retriever = LexicalRetriever(_source_rows())

    method_hits = retriever.search(
        "How should I scout Manitoba seedling canola for flea beetle leaf damage?",
        jurisdictions=("Manitoba",),
        strict_jurisdictions=True,
        retrieval_policies=("context_only",),
        top_k=5,
    )
    assert method_hits
    assert method_hits[0].doc_id == f"{SOURCE_ID}_semantic_0002"
    assert all(hit.retrieval_policy == "context_only" for hit in method_hits)
    assert not {
        f"{SOURCE_ID}_semantic_0003",
        f"{SOURCE_ID}_semantic_0005",
    } & {hit.doc_id for hit in method_hits}

    threshold_hits = retriever.search(
        "What is the Manitoba canola lygus threshold per ten sweeps?",
        jurisdictions=("Manitoba",),
        strict_jurisdictions=True,
        retrieval_policies=("requires_live_authority",),
        top_k=5,
    )
    assert threshold_hits
    assert threshold_hits[0].doc_id == f"{SOURCE_ID}_semantic_0005"
    assert all(hit.retrieval_policy == "requires_live_authority" for hit in threshold_hits)
