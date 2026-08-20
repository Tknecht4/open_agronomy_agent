from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agronomy_agent.corpus_release import canonical_json
from agronomy_agent.agno_runtime.local_index import tokenize
from agronomy_agent.on_demand_corpus import OnDemandCorpusRelease


def _release(tmp_path: Path) -> OnDemandCorpusRelease:
    shard = tmp_path / "shards" / "one.jsonl"
    shard.parent.mkdir()
    shard.write_text(
        json.dumps(
            {
                "doc_id": "us-1",
                "title": "MLRA context",
                "text": "Ecological site context for the named MLRA.",
                "source": "https://example.test/nrcs",
                "source_id": "nrcs",
                "jurisdiction": ["United States"],
                "retrieval_policy": "context_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tokens = tokenize("MLRA context Ecological site context for the named MLRA.")
    index = {
        "schema_version": "open_agronomy_agent.offline_bm25_statistics.v1",
        "tokenizer": "agronomy_agent.agno_runtime.local_index.tokenize",
        "corpus_shard_set_sha256": hashlib.sha256(canonical_json([{"path": "shards/one.jsonl", "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}]).encode("utf-8")).hexdigest(),
        "shards": [{
            "path": "shards/one.jsonl",
            "shard_sha256": hashlib.sha256(shard.read_bytes()).hexdigest(),
            "document_count": 1,
            "average_token_count": len(tokens),
            "document_token_counts": {"us-1": len(tokens)},
            "document_frequencies": {token: 1 for token in set(tokens)},
        }],
    }
    index["index_sha256"] = hashlib.sha256(canonical_json(index).encode("utf-8")).hexdigest()
    index_path = tmp_path / "bm25_statistics_index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    manifest = {
        "schema_version": "open_agronomy_agent.offline_corpus_release.v1",
        "release_id": "us-test",
        "shards": [{"path": "shards/one.jsonl", "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}],
        "mlra_shards": {"001X": ["shards/one.jsonl"]},
        "bm25_statistics_index": {"path": "bm25_statistics_index.json", "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()},
    }
    manifest["store_sha256"] = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
    path = tmp_path / "store_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return OnDemandCorpusRelease.from_config(
        {
            "release_id": "us-test",
            "manifest_path": str(path),
            "activation": "explicit_us_nrcs_or_mlra",
            "jurisdiction": "United States",
            "retrieval_policy": "context_only",
        }
    )


def test_on_demand_release_is_inactive_without_explicit_us_request(tmp_path: Path) -> None:
    release = _release(tmp_path)
    assert release.search("What is crop rotation?", top_k=1) == []
    assert release.search("NRCS MLRA 001X ecological site", top_k=1)[0].doc_id == "us-1"
    assert release._selected_relative_shards("NRCS MLRA 001X ecological site") == ("shards/one.jsonl",)


def test_on_demand_release_rejects_a_tampered_shard_before_retrieval(tmp_path: Path) -> None:
    release = _release(tmp_path)
    (tmp_path / "shards" / "one.jsonl").write_text("tampered\n", encoding="utf-8")
    try:
        release.search("USDA NRCS MLRA 001X", top_k=1)
    except ValueError as exc:
        assert "hash validation" in str(exc)
    else:
        raise AssertionError("tampered on-demand shard must fail closed")
