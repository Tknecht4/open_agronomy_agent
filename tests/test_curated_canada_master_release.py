from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from agronomy_agent.agent import load_agent_resources
from agronomy_agent.corpus_governance import audit_runtime_corpora
from agronomy_agent.curated_knowledge_store import validate_curated_knowledge_store


ROOT = Path(__file__).resolve().parents[1]
STORE_ROOT = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14"
SOURCE_MANIFEST = ROOT / "data/manifests/canada_agronomy_sources.json"
PROFILE_SPEC = ROOT / "data/manifests/curated_canada_offline_master_v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted((STORE_ROOT / "shards").glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return rows


def test_master_release_is_the_single_complete_policy_segregated_profile() -> None:
    manifest = _load_json(STORE_ROOT / "store_manifest.json")
    profile_spec = _load_json(PROFILE_SPEC)
    rows = _rows()

    assert manifest["store_id"] == "curated-canada-2026-08-14"
    assert manifest["builder"]["version"] == 2
    assert manifest["training_authorization"]["granted"] is False
    assert manifest["totals"] == {
        "bytes": 5_603_844,
        "rows": 969,
        "shards": 2,
        "unique_content_fingerprints": 969,
        "unique_doc_ids": 969,
    }
    assert [profile["profile_id"] for profile in manifest["profiles"]] == [
        "canada-offline-master"
    ]
    assert [profile["id"] for profile in profile_spec["profiles"]] == [
        "canada-offline-master"
    ]
    assert manifest["included_source_ids"] == sorted(
        profile_spec["profiles"][0]["source_ids"]
    )
    assert len(manifest["included_source_ids"]) == 20
    assert Counter(row["retrieval_policy"] for row in rows) == {
        "context_only": 955,
        "requires_live_authority": 14,
    }
    assert len({row["doc_id"] for row in rows}) == 969
    assert all(row["license_snapshot"]["permits_redistribution"] is True for row in rows)

    rows_by_source = Counter(row["source_id"] for row in rows)
    assert set(rows_by_source) == set(manifest["included_source_ids"])
    assert rows_by_source["mb_2026_crop_disease_scouting"] == 4
    assert rows_by_source["mb_2026_canola_insect_scouting"] == 5
    assert rows_by_source["mb_2023_crop_rotation_context"] == 4
    assert rows_by_source["ab_tame_pasture_range_health_2017"] == 4


def test_master_release_and_standalone_runtime_policy_validate_offline() -> None:
    report = validate_curated_knowledge_store(
        store_root=STORE_ROOT,
        source_manifest_path=SOURCE_MANIFEST,
        expected_profile_ids={"canada-offline-master"},
        repository_root=ROOT,
    )
    assert report["status"] == "pass", report["errors"]

    runtime_report = audit_runtime_corpora(
        root=STORE_ROOT,
        rag_config_path=STORE_ROOT / "profiles/canada-offline-master/rag.yaml",
    )
    assert runtime_report["status"] == "pass", runtime_report["errors"]
    assert runtime_report["configured_corpus_count"] == 2


def test_master_profile_makes_every_admitted_row_available_to_retrieval() -> None:
    resources = load_agent_resources(
        STORE_ROOT / "profiles/canada-offline-master/rag.yaml"
    )
    assert len(resources.retriever.docs) == 969
    assert {row["source_id"] for row in resources.retriever.docs} == set(
        _load_json(STORE_ROOT / "store_manifest.json")["included_source_ids"]
    )
    assert resources.load_time_excluded_corpora == ()


def test_every_declared_semantic_companion_is_versioned_present_and_hash_bound() -> None:
    declarations: list[tuple[str, dict]] = []
    for source in _load_json(SOURCE_MANIFEST)["sources"]:
        policy = source.get("ingest_policy") or {}
        if policy.get("semantic_companion_path"):
            declarations.append((source["id"], policy))

    assert len(declarations) == 7
    for source_id, policy in declarations:
        relative_path = policy["semantic_companion_path"]
        assert re.search(r"\.20\d{2}-\d{2}-\d{2}\.semantic\.json$", relative_path)
        path = ROOT / relative_path
        assert path.is_file(), source_id
        assert re.fullmatch(r"[0-9a-f]{64}", policy["semantic_companion_sha256"])
        assert _sha256(path) == policy["semantic_companion_sha256"], source_id
        companion = _load_json(path)
        assert companion["source_id"] == source_id
        assert companion["records"]


def test_semantic_rows_in_master_bind_the_current_registry_companions() -> None:
    source_by_id = {
        source["id"]: source for source in _load_json(SOURCE_MANIFEST)["sources"]
    }
    semantic_rows = [row for row in _rows() if row.get("semantic_companion")]
    assert len(semantic_rows) == 27

    for row in semantic_rows:
        policy = source_by_id[row["source_id"]]["ingest_policy"]
        row_binding = row["semantic_companion"]
        lineage_binding = row["lineage"]["semantic_companion"]
        assert row_binding["companion_path"] == policy["semantic_companion_path"]
        assert row_binding["companion_sha256"] == policy["semantic_companion_sha256"]
        assert lineage_binding["path"] == policy["semantic_companion_path"]
        assert lineage_binding["sha256"] == policy["semantic_companion_sha256"]
        assert lineage_binding["parent_raw_sha256"] == row["lineage"]["raw_sha256"]


def test_recovery_receipt_preserves_observed_hashes_and_current_successors() -> None:
    receipt = _load_json(
        ROOT
        / "data/curated/canada_agronomy/semantic_companion_recovery_receipt_v1.json"
    )
    source_by_id = {
        source["id"]: source for source in _load_json(SOURCE_MANIFEST)["sources"]
    }
    assert receipt["status"] == "recovered_from_hash_bound_derived_rows_not_original_bytes"
    assert receipt["training_authorization"]["granted"] is False
    assert len(receipt["recoveries"]) == 5

    for recovery in receipt["recoveries"]:
        derived_rows = ROOT / recovery["derived_rows_path"]
        recovered_companion = ROOT / recovery["recovered_companion_path"]
        if derived_rows.is_file():
            assert _sha256(derived_rows) == recovery["derived_rows_sha256"]
        if recovered_companion.is_file():
            assert _sha256(recovered_companion) == recovery["recovered_companion_sha256"]
        else:
            current_policy = source_by_id[recovery["source_id"]]["ingest_policy"]
            current_companion = ROOT / current_policy["semantic_companion_path"]
            assert current_companion != recovered_companion
            assert _sha256(current_companion) == current_policy[
                "semantic_companion_sha256"
            ]
        assert recovery["missing_companion_sha256_recorded_in_rows"] != recovery[
            "recovered_companion_sha256"
        ]


def test_portable_retention_receipt_binds_current_master_without_claiming_fresh_raw_audit() -> None:
    receipt_path = ROOT / "data/manifests/source_retention_receipt.json"
    receipt = _load_json(receipt_path)
    manifest_path = STORE_ROOT / "store_manifest.json"
    manifest = _load_json(manifest_path)
    boundary = receipt["evidence_boundary"]
    release = receipt["current_release_binding"]

    assert receipt["schema_version"] == "open_agronomy_agent.source_retention_receipt.v2"
    assert receipt["status"] == "pass"
    assert receipt["deletion_authorized"] is False
    assert boundary["current_runtime_and_store_revalidated"] is True
    assert boundary["raw_source_archive_mounted"] is False
    assert boundary["raw_source_bytes_revalidated_in_this_release_pass"] is False
    assert release["store_manifest_sha256"] == _sha256(manifest_path)
    assert release["source_registry_sha256"] == _sha256(SOURCE_MANIFEST)
    assert release["master_spec_sha256"] == _sha256(PROFILE_SPEC)
    assert release["rows"] == manifest["totals"]["rows"]
    assert release["sources"] == len(manifest["included_source_ids"])

    expected_hashes: dict[str, set[str]] = {}
    for row in _rows():
        expected_hashes.setdefault(row["source_id"], set()).add(
            row["lineage"]["raw_sha256"]
        )
    receipts = {
        item["source_id"]: set(item["expected_raw_hashes"])
        for item in receipt["governed_canadian_rag"]["exact_source_byte_receipts"]
    }
    assert receipts == expected_hashes
