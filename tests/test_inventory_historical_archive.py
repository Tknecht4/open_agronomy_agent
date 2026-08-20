from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "inventory_historical_archive.py"


def _module():
    spec = importlib.util.spec_from_file_location("inventory_historical_archive", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_is_hash_bound_and_quarantines_private_and_forum_material(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    (archive / "data" / "derived" / "rag").mkdir(parents=True)
    (archive / "data" / "derived" / "private_knowledge").mkdir(parents=True)
    (archive / "data" / "derived" / "rag" / "forum_test.jsonl").write_text(
        json.dumps({"source_id": "forum", "license": "public_forum", "text": "example"}) + "\n",
        encoding="utf-8",
    )
    (archive / "data" / "derived" / "private_knowledge" / "notes.txt").write_text("private", encoding="utf-8")
    (archive / "data" / "derived" / "rag" / "nrcs_esd.jsonl").write_text(
        json.dumps({"source_id": "nrcs", "license": "us_government_public_source_with_citation"}) + "\n",
        encoding="utf-8",
    )
    module = _module()
    report = module.build_inventory(archive)
    assert report["summary"]["safe_for_automatic_promotion"] is False
    by_path = {entry["path"]: entry for entry in report["files"]}
    assert by_path["data/derived/rag/forum_test.jsonl"]["classification"] == "candidate"
    assert by_path["data/derived/rag/forum_test.jsonl"]["archive_role"] == "derived_artifact"
    assert by_path["data/derived/rag/forum_test.jsonl"]["licence_evidence"] == "public_forum"
    assert by_path["data/derived/private_knowledge/notes.txt"]["classification"] == "quarantined"
    assert by_path["data/derived/rag/nrcs_esd.jsonl"]["reproducibility"] == "rebuildable_from_hashed_archive"
    assert len(report["inventory_sha256"]) == 64


def test_partial_inventories_merge_without_losing_identity(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    (archive / "data").mkdir(parents=True)
    (archive / "configs").mkdir()
    (archive / "data" / "one.txt").write_text("one", encoding="utf-8")
    (archive / "configs" / "two.txt").write_text("two", encoding="utf-8")
    module = _module()
    first = module.build_inventory(archive, include_roots=("data",))
    second = module.build_inventory(archive, include_roots=("configs",))
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    second_path.write_text(json.dumps(second), encoding="utf-8")
    merged = module.merge_inventories([first_path, second_path])
    assert [entry["path"] for entry in merged["files"]] == ["configs/two.txt", "data/one.txt"]


def test_reclassification_preserves_hashed_bytes_and_updates_policy_only(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    (archive / "data" / "derived" / "rag").mkdir(parents=True)
    path = archive / "data" / "derived" / "rag" / "curated_canada_v4.jsonl"
    path.write_text('{"doc_id":"d"}\n', encoding="utf-8")
    module = _module()
    original = module.build_inventory(archive)
    original["files"][0]["classification"] = "rejected"
    original_path = tmp_path / "prior.json"
    original_path.write_text(json.dumps(original), encoding="utf-8")
    repaired = module.reclassify_inventory(original_path)
    assert repaired["files"][0]["sha256"] == original["files"][0]["sha256"]
    assert repaired["files"][0]["classification"] == "candidate"
    assert repaired["classification_recomputed_from_inventory_sha256"] == original["inventory_sha256"]


def test_secret_pattern_is_quarantined_without_exposing_contents(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    (archive / "tests").mkdir(parents=True)
    (archive / "tests" / "fixture.txt").write_text("Bearer abcdefghijklmnopqrstuvwxyz1234", encoding="utf-8")
    report = _module().build_inventory(archive, include_roots=("tests",))
    assert report["files"][0]["classification"] == "quarantined"
    assert report["files"][0]["classification_reason"] == "secret_pattern_requires_manual_review"


def test_top_level_file_scan_does_not_recurse_the_directory(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    (archive / "data" / "nested").mkdir(parents=True)
    (archive / "data" / ".DS_Store").write_text("metadata", encoding="utf-8")
    (archive / "data" / "nested" / "source.txt").write_text("source", encoding="utf-8")
    report = _module().build_inventory(archive, include_roots=(), include_top_level_files=("data",))
    assert [entry["path"] for entry in report["files"]] == ["data/.DS_Store"]


def test_merge_deduplicates_same_hashed_path_from_overlapping_scan_scopes(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    (archive / "data").mkdir(parents=True)
    (archive / "data" / "one.txt").write_text("one", encoding="utf-8")
    module = _module()
    first = module.build_inventory(archive, include_roots=("data",))
    second = module.build_inventory(archive, include_roots=("data/one.txt",))
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    second_path.write_text(json.dumps(second), encoding="utf-8")
    merged = module.merge_inventories([first_path, second_path])
    assert len(merged["files"]) == 1
