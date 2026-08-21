from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "mb_2026_crop_disease_scouting"
RAW_SHA256 = "9552dd91b8bb7bbd20748c866e1ea691bb9b9507251a1a176e6b49d6c71d4483"
SOURCE_MANIFEST = ROOT / "data/manifests/canada_agronomy_sources.json"
COMPANION_PATH = ROOT / "data/curated/canada_agronomy/mb_2026_crop_disease_scouting.2026-08-13.semantic.json"
PROFILE_SPEC_PATH = ROOT / "data/manifests/curated_canada_offline_master_v1.json"
STORE_ROOT = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14"
MASTER_RAG_CONFIG_PATH = STORE_ROOT / "profiles/canada-offline-master/rag.yaml"

# These terms or units would turn the reviewed context-only companion into a
# product/label or rate-bearing source.  The source may retain a plain-language
# boundary such as "not a rate recommendation"; this check is intentionally
# aimed at product terms and usable rate/threshold syntax that could reach
# retrieval text.
PROHIBITED_MODEL_TEXT_PATTERNS = (
    re.compile(
        r"\b(?:product label|registered product|fungicide|herbicide|insecticide|pesticide)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:kg|g|lb|l|ml)\s*/\s*(?:ha|ac)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:percent|%)\b", re.IGNORECASE),
    re.compile(r"(?:\d+\s*°\s*[CF]|\b\d+\s*degrees?\s+celsius\b)", re.IGNORECASE),
)
PROHIBITED_RETRIEVAL_TAGS = {
    "corn",
    "fertility",
    "nutrient_management",
    "precision_economics",
    "product",
}


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


def test_manitoba_disease_companion_is_hash_pinned_and_context_only() -> None:
    source = _source_record()
    companion = _load_json(COMPANION_PATH)

    assert source["expected_raw_sha256"] == RAW_SHA256
    assert re.fullmatch(r"[0-9a-f]{64}", source["expected_raw_sha256"])
    assert source["jurisdiction"] == ["Manitoba"]
    assert source["default_retrieval_policy"] == "context_only"
    assert source["regulatory"] == {
        "regulated_advice": True,
        "require_live_authority": True,
    }
    assert source["ingest_policy"]["emit_source_chunks"] is False
    assert source["ingest_policy"]["semantic_companion_path"] == (
        "data/curated/canada_agronomy/mb_2026_crop_disease_scouting.2026-08-13.semantic.json"
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
    assert [record["source_pages"] for record in companion["records"]] == [[1], [1], [2], [3]]
    assert len(companion["records"]) == 4


def test_manitoba_disease_master_rows_emit_only_reviewed_nonprescriptive_companion_text() -> None:
    companion = _load_json(COMPANION_PATH)
    profiles = _load_json(PROFILE_SPEC_PATH)["profiles"]
    store = _load_json(STORE_ROOT / "store_manifest.json")
    rows = _source_rows()

    assert [profile["id"] for profile in profiles] == ["canada-offline-master"]
    master = profiles[0]
    assert master["source_ids"].count(SOURCE_ID) == 1
    assert store["store_id"] == "curated-canada-2026-08-14"
    assert store["training_authorization"]["granted"] is False

    # The master is the only active physical Canadian store. Historical
    # supplemental corpora are not additive runtime dependencies.
    master_rag_config = MASTER_RAG_CONFIG_PATH.read_text(encoding="utf-8")
    assert "canada_agronomy_supplement_v3" not in master_rag_config
    assert "artifact_root: ../.." in master_rag_config

    expected_records = {
        f"{SOURCE_ID}_semantic_{index:04d}": record
        for index, record in enumerate(companion["records"], start=1)
    }
    assert {row["doc_id"] for row in rows} == set(expected_records)
    assert len(rows) == 4

    for row in rows:
        expected_record = expected_records[row["doc_id"]]
        lineage = row["lineage"]
        semantic_lineage = lineage["semantic_companion"]

        assert row["title"] == expected_record["title"]
        assert row["text"] == expected_record["text"]
        assert row["jurisdiction"] == ["Manitoba"]
        assert row["retrieval_policy"] == "context_only"
        assert lineage["raw_sha256"] == RAW_SHA256
        assert lineage["expected_raw_sha256"] == RAW_SHA256
        assert lineage["retrieval_policy"] == "context_only"
        assert lineage["extractor"]["transform"] == "reviewed_semantic_companion"
        assert semantic_lineage["parent_raw_sha256"] == RAW_SHA256
        assert semantic_lineage["source_pages"] == expected_record["source_pages"]

        retrieval_metadata = {
            value.casefold()
            for field in ("tags", "chunk_topics", "crops", "buckets")
            for value in row[field]
        }
        assert not (retrieval_metadata & PROHIBITED_RETRIEVAL_TAGS)
        for pattern in PROHIBITED_MODEL_TEXT_PATTERNS:
            assert pattern.search(row["text"]) is None, pattern.pattern
