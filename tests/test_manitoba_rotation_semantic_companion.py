from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "mb_2023_crop_rotation_context"
RAW_SHA256 = "920892c21ce1ddf6a4331b70b60540429f5547cbab4fc2f9eb44a525d1b6427f"
SOURCE_MANIFEST = ROOT / "data/manifests/canada_agronomy_sources.json"
COMPANION_PATH = ROOT / "data/curated/canada_agronomy/mb_2023_crop_rotation_context.2026-08-13.semantic.json"
MASTER_PROFILE_SPEC_PATH = ROOT / "data/manifests/curated_canada_offline_master_v1.json"
INGEST_SCRIPT_PATH = ROOT / "scripts/ingest_document_sources.py"


# These patterns would turn the reviewed context-only companion into a raw
# table, named external dataset, visual description, input, nutrient/rate,
# procedure, or regulatory source.  Page references remain provenance only and
# are intentionally checked separately from model-visible text.
PROHIBITED_MODEL_TEXT_PATTERNS = (
    re.compile(r"\d"),
    re.compile(r"\bmasc\b", re.IGNORECASE),
    re.compile(r"\b(?:table|figure|image|logo|photograph|visual)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:product|chemical|pesticide|herbicide|fungicide|insecticide|nutrient|fertili[sz]er|rate)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:procedure|regulat\w*|legal|permit|compliance)\b", re.IGNORECASE),
    re.compile(r"\b(?:canola|wheat|barley|oat|corn|soybean|potato|pea|bean|lentil)\b", re.IGNORECASE),
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_record() -> dict:
    manifest = _load_json(SOURCE_MANIFEST)
    return next(source for source in manifest["sources"] if source["id"] == SOURCE_ID)


def _load_ingestor():
    spec = importlib.util.spec_from_file_location(
        "manitoba_rotation_ingestor_test", INGEST_SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_visible_companion_text(companion: dict) -> str:
    return "\n".join(
        " ".join(
            [record["title"], *record["tags"], record["text"]]
        )
        for record in companion["records"]
    )


def _semantic_rows() -> list[dict]:
    ingestor = _load_ingestor()
    source = _source_record()
    base_source_row = {
        "doc_id": "fixture-parent-row",
        "title": "Fixture parent row",
        "text": "Fixture source text retained only to establish semantic-companion lineage.",
        "source": source["url"],
        "source_id": SOURCE_ID,
        "source_type": "applied_guidance",
        "document_type": source["runtime_document_type"],
        "language": ["en-CA"],
        "jurisdiction": ["Manitoba"],
        "crops": source["crops"],
        "buckets": source["buckets"],
        "tags": [],
        "lineage": {
            "extractor": {
                "name": "fixture-extractor",
                "schema_version": 1,
                "max_words": 220,
                "overlap_words": 35,
            }
        },
    }
    return ingestor.make_semantic_companion_rows(
        source,
        [base_source_row],
        raw_source_lineage={"raw_sha256": RAW_SHA256},
        manifest_sha256="a" * 64,
        ingested_at="2026-08-13T00:00:00+00:00",
    )


def test_manitoba_rotation_companion_is_hash_pinned_historical_and_context_only() -> None:
    source = _source_record()
    companion = _load_json(COMPANION_PATH)

    assert source["expected_raw_sha256"] == RAW_SHA256
    assert re.fullmatch(r"[0-9a-f]{64}", source["expected_raw_sha256"])
    assert source["jurisdiction"] == ["Manitoba"]
    assert source["default_retrieval_policy"] == "context_only"
    assert source["currency"] == {
        "status": "historical_2023_document_with_2011_2020_aggregate_observations",
        "review_interval_days": 365,
        "volatile": False,
    }
    assert source["regulatory"] == {
        "regulated_advice": False,
        "require_live_authority": False,
    }
    assert source["license"]["status"] == "redistributable"
    assert source["license"]["identifier"] == "OpenMB Information and Data Use Licence"
    assert source["license"]["third_party_risk"] is True
    assert source["ingest_policy"]["emit_source_chunks"] is False
    assert source["ingest_policy"]["semantic_companion_path"] == (
        "data/curated/canada_agronomy/mb_2023_crop_rotation_context.2026-08-13.semantic.json"
    )
    assert source["ingest_policy"]["semantic_companion_sha256"] == hashlib.sha256(
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

    assert companion["source_id"] == SOURCE_ID
    assert companion["source_raw_sha256"] == RAW_SHA256
    assert [record["source_pages"] for record in companion["records"]] == [[1], [1], [2], [2]]
    assert len(companion["records"]) == 4


def test_manitoba_rotation_companion_has_no_raw_or_prescriptive_model_text() -> None:
    companion = _load_json(COMPANION_PATH)
    model_visible_text = _model_visible_companion_text(companion)
    rows = _semantic_rows()

    assert all(len(record["text"].split()) >= 40 for record in companion["records"])
    for pattern in PROHIBITED_MODEL_TEXT_PATTERNS:
        assert pattern.search(model_visible_text) is None, pattern.pattern

    record_text = [record["text"] for record in companion["records"]]
    assert any("previous crop" in text.casefold() for text in record_text)
    assert any("stubble" in text.casefold() for text in record_text)
    assert any("disease" in text.casefold() for text in record_text)
    assert any("carryover" in text.casefold() for text in record_text)
    assert any("water use" in text.casefold() for text in record_text)
    assert any("emergence" in text.casefold() for text in record_text)
    assert any("does not predict an individual field" in text.casefold() for text in record_text)
    assert any("does not prescribe a crop sequence" in text.casefold() for text in record_text)

    assert len(rows) == len(companion["records"])
    assert {row["retrieval_policy"] for row in rows} == {"context_only"}
    assert {tuple(row["content_risk_tags"]) for row in rows} == {
        ("historical_source_requires_current_validation",)
    }
    assert all(row["lineage"]["raw_sha256"] == RAW_SHA256 for row in rows)
    assert all(
        row["lineage"]["extractor"]["transform"] == "reviewed_semantic_companion"
        for row in rows
    )


def test_manitoba_rotation_is_admitted_once_to_the_cumulative_master() -> None:
    master = _load_json(MASTER_PROFILE_SPEC_PATH)

    assert [profile["id"] for profile in master["profiles"]] == [
        "canada-offline-master"
    ]
    assert master["profiles"][0]["source_ids"].count(SOURCE_ID) == 1
