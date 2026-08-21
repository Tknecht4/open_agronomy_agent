from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "ab_tame_pasture_range_health_2017"
RAW_SHA256 = "1cd9179add78838adc6c5343e4bb413dfa9be4a60788a4ce40bb231aba9290a0"
SOURCE_MANIFEST = ROOT / "data/manifests/canada_agronomy_sources.json"
COMPANION_PATH = ROOT / "data/curated/canada_agronomy/ab_tame_pasture_range_health_2017.2026-08-14.semantic.json"
MASTER_PROFILE_SPEC_PATH = ROOT / "data/manifests/curated_canada_offline_master_v1.json"
MASTER_SHARD_ROOT = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14/shards"
INGEST_SCRIPT_PATH = ROOT / "scripts/ingest_document_sources.py"


# The raw worksheet includes visual material, numeric scoring, named plants,
# noxious-weed and legal content, and management directions. Page references
# below are provenance only; none of that material may become model-visible
# companion text.
PROHIBITED_MODEL_TEXT_PATTERNS = (
    re.compile(r"\d"),
    re.compile(r"\b(?:score|threshold|percent|range health|bare soil)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:weed|herbicide|pesticide|chemical|fertili[sz]er|nutrient rate|grazing|stocking|renovat\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:regulat\w*|legal|compliance|act|permit|noxious)\b", re.IGNORECASE),
    re.compile(r"\b(?:table|figure|image|logo|photograph|visual)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:alfalfa|brome|timothy|clover|fescue|quackgrass|foxtail|mustard)\b",
        re.IGNORECASE,
    ),
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_record() -> dict:
    manifest = _load_json(SOURCE_MANIFEST)
    return next(source for source in manifest["sources"] if source["id"] == SOURCE_ID)


def _load_ingestor():
    spec = importlib.util.spec_from_file_location(
        "alberta_tame_pasture_ingestor_test", INGEST_SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_visible_companion_text(companion: dict) -> str:
    return "\n".join(
        " ".join([record["title"], *record["tags"], record["text"]])
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
        "jurisdiction": ["Alberta"],
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
        ingested_at="2026-08-14T00:00:00+00:00",
    )


def test_alberta_tame_pasture_companion_is_hash_pinned_historical_and_context_only() -> None:
    source = _source_record()
    companion = _load_json(COMPANION_PATH)

    assert source["expected_raw_sha256"] == RAW_SHA256
    assert re.fullmatch(r"[0-9a-f]{64}", source["expected_raw_sha256"])
    assert source["jurisdiction"] == ["Alberta"]
    assert source["default_retrieval_policy"] == "context_only"
    assert source["currency"] == {
        "status": "historical_2017_tame_pasture_assessment_tool",
        "review_interval_days": 365,
        "volatile": False,
    }
    assert source["regulatory"] == {
        "regulated_advice": True,
        "require_live_authority": True,
    }
    assert source["license"]["status"] == "redistributable"
    assert source["license"]["identifier"] == "Open Government Licence - Alberta"
    assert source["license"]["scope_verified"] is True
    assert source["license"]["third_party_risk"] is True
    assert source["ingest_policy"]["emit_source_chunks"] is False
    assert source["ingest_policy"]["semantic_companion_path"] == (
        "data/curated/canada_agronomy/ab_tame_pasture_range_health_2017.2026-08-14.semantic.json"
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
        "live_retrieval": False,
    }

    assert companion["source_id"] == SOURCE_ID
    assert companion["source_raw_sha256"] == RAW_SHA256
    assert [record["source_pages"] for record in companion["records"]] == [
        [1],
        [1],
        [1, 2],
        [1, 2],
    ]
    assert len(companion["records"]) == 4


def test_alberta_tame_pasture_companion_excludes_raw_scoring_and_action_content() -> None:
    companion = _load_json(COMPANION_PATH)
    model_visible_text = _model_visible_companion_text(companion)
    rows = _semantic_rows()

    assert all(len(record["text"].split()) >= 40 for record in companion["records"])
    for pattern in PROHIBITED_MODEL_TEXT_PATTERNS:
        assert pattern.search(model_visible_text) is None, pattern.pattern

    record_text = [record["text"].casefold() for record in companion["records"]]
    assert any("uniform site potential" in text for text in record_text)
    assert any("plant vigour" in text for text in record_text)
    assert any("water capture and release" in text for text in record_text)
    assert any("preserve the location" in text for text in record_text)
    assert any("cannot replace current records" in text for text in record_text)

    assert len(rows) == len(companion["records"])
    assert {row["retrieval_policy"] for row in rows} == {"context_only"}
    assert {tuple(row["content_risk_tags"]) for row in rows} == {
        ("historical_source_requires_current_validation", "source_contains_live_authority_content")
    }
    assert all(row["lineage"]["raw_sha256"] == RAW_SHA256 for row in rows)
    assert all(
        row["lineage"]["extractor"]["transform"] == "reviewed_semantic_companion"
        for row in rows
    )


def test_alberta_tame_pasture_is_admitted_once_to_the_cumulative_master() -> None:
    master = _load_json(MASTER_PROFILE_SPEC_PATH)

    assert [profile["id"] for profile in master["profiles"]] == [
        "canada-offline-master"
    ]
    assert master["profiles"][0]["source_ids"].count(SOURCE_ID) == 1


def test_alberta_tame_pasture_master_rows_remain_context_only() -> None:
    rows = [
        json.loads(line)
        for shard in MASTER_SHARD_ROOT.glob("*.jsonl")
        for line in shard.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_rows = [row for row in rows if row["source_id"] == SOURCE_ID]

    assert len(source_rows) == 4
    assert {row["retrieval_policy"] for row in source_rows} == {"context_only"}
    assert all(row["lineage"]["raw_sha256"] == RAW_SHA256 for row in source_rows)
