from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_us_nrcs_full_release.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_us_nrcs_full_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_release_is_portable_sharded_and_context_only(tmp_path: Path) -> None:
    raw = tmp_path / "data" / "raw" / "documents" / "nrcs_esd_json" / "001X" / "site.json"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"example": true}', encoding="utf-8")
    raw_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    inventory = {"inventory_sha256": "b" * 64, "files": [{"path": raw.relative_to(tmp_path).as_posix(), "sha256": raw_sha}]}
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    full = tmp_path / "full.jsonl"
    source = {
        "doc_id": "site-1",
        "title": "Site",
        "text": "A long enough ecological-site statement to retain.",
        "source": "https://example.test/catalog",
        "download_url": "https://example.test/source.json",
        "source_id": "legacy",
        "mlra": "001X",
        "ecological_site_id": "site-1",
        "chunk_index": 1,
        "extraction": {"raw_path": "/" + "Volumes" + "/ext/agronomy_agent/" + raw.relative_to(tmp_path).as_posix()},
    }
    full.write_text(json.dumps(source) + "\n" + json.dumps({**source, "doc_id": "site-2"}) + "\n", encoding="utf-8")
    output = tmp_path / "release"
    result = _module()._write_release(
        full_corpus=full,
        raw_inventory=inventory_path,
        output_root=output,
        release_id="test",
        maximum_shard_bytes=5_000,
    )
    assert result["rows"] == 1  # normalized exact duplicate is retained once
    shard = output / result["shards"][0]["path"]
    row = json.loads(shard.read_text(encoding="utf-8"))
    assert row["jurisdiction"] == ["United States"]
    assert row["retrieval_policy"] == "context_only"
    assert row["source_locator"]["archive_relative_path"] == raw.relative_to(tmp_path).as_posix()
    assert "/" + "Volumes" + "/" not in shard.read_text(encoding="utf-8")
    assert result["mlra_shards"] == {"001X": [result["shards"][0]["path"]]}


def test_finalizer_rejects_partial_or_duplicate_existing_shards(tmp_path: Path) -> None:
    module = _module()
    release = tmp_path / "release"
    shards = release / "shards"
    shards.mkdir(parents=True)
    record = {
        "doc_id": "site-1",
        "text": "Complete source-bound text.",
        "source_id": "nrcs",
        "retrieval_policy": "context_only",
        "quality": {
            "extraction_fidelity": "test",
            "language": "English",
            "authority_tier": "US_government_reference",
            "jurisdiction": "United States",
            "temporal_scope": "historical",
            "risk_class": "context_only",
            "retrieval_eligibility": "context_only",
            "duplicate_disposition": "retained",
            "near_duplicate_disposition": "not_clustered",
        },
        "source_locator": {
            "precision": "json_document_chunk",
            "archive_relative_path": "data/raw/site.json",
            "raw_sha256": "a" * 64,
            "source_url": "https://example.test/site.json",
            "extraction_method": "test",
            "json_document_id": "site-1",
            "chunk_index": 0,
            "chunk_text_sha256": "d" * 64,
        },
    }
    (shards / "context_only-test-0001.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    raw_inventory = tmp_path / "raw.json"
    raw_inventory.write_text(json.dumps({"inventory_sha256": "b" * 64}), encoding="utf-8")
    result = module._finalize_existing_release(
        raw_inventory=raw_inventory,
        output_root=release,
        release_id="test",
        maximum_shard_bytes=2_000,
        source_full_corpus_sha256="c" * 64,
    )
    assert result["rows"] == 1
    (shards / "context_only-test-0002.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    try:
        module._finalize_existing_release(
            raw_inventory=raw_inventory,
            output_root=release,
            release_id="test",
            maximum_shard_bytes=2_000,
            source_full_corpus_sha256="c" * 64,
        )
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate source rows must fail finalization")


def test_raw_inventory_rebinding_preserves_verified_shard_identity(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    release = tmp_path / "release"
    release.mkdir()
    store = {
        "schema_version": "open_agronomy_agent.offline_corpus_release.v1",
        "release_id": "test",
        "rows": 1,
        "shards": [{"path": "shards/one.jsonl", "sha256": "a" * 64}],
        "raw_inventory_path": "old.json",
        "raw_inventory_sha256": "b" * 64,
    }
    store["store_sha256"] = module.sha256_bytes(module.canonical_json(store).encode("utf-8"))
    (release / "store_manifest.json").write_text(json.dumps(store), encoding="utf-8")
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"inventory_sha256": "c" * 64}), encoding="utf-8")
    result = module._refresh_raw_inventory_binding(raw_inventory=raw, output_root=release)
    assert result["raw_inventory_sha256"] == "c" * 64
    assert result["shards"] == store["shards"]
    assert result["source_binding_refresh"]["previous_store_sha256"] == store["store_sha256"]
