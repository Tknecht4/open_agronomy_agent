from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agronomy_agent.corpus_release import canonical_json
from agronomy_agent.agno_runtime.local_index import tokenize
from agronomy_agent.on_demand_corpus import OnDemandCorpusRelease


def _release(tmp_path: Path) -> OnDemandCorpusRelease:
    shard = tmp_path / "shards" / "one.jsonl"
    shard.parent.mkdir()
    records = [
        {
            "doc_id": "us-1",
            "mlra": "001X",
            "title": "MLRA context",
            "text": "Ecological site context for the named MLRA.",
            "source": "https://example.test/nrcs",
            "source_id": "nrcs",
            "jurisdiction": ["United States"],
            "retrieval_policy": "context_only",
            "raw_sha256": "a" * 64,
            "chunk_sha256": "b" * 64,
            "source_locator": {"json_document_id": "site-1", "raw_sha256": "a" * 64},
            "transfer_scope": "US_analogue_context_only",
            "applicability_boundary": "Historical regional context; no Canadian action authority.",
        },
        {
            "doc_id": "us-2",
            "mlra": "002X",
            "title": "Other MLRA climate",
            "text": "Ecological site climate context from a different region.",
            "source": "https://example.test/nrcs/other",
            "retrieval_policy": "context_only",
        },
    ]
    shard.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    tokens_by_doc = {
        record["doc_id"]: tokenize(" ".join([record["title"], record["mlra"], record["text"]]))
        for record in records
    }
    frequencies = {
        token: sum(token in tokens for tokens in tokens_by_doc.values())
        for token in {token for tokens in tokens_by_doc.values() for token in tokens}
    }
    index = {
        "schema_version": "open_agronomy_agent.offline_bm25_statistics.v1",
        "tokenizer": "agronomy_agent.agno_runtime.local_index.tokenize",
        "corpus_shard_set_sha256": hashlib.sha256(canonical_json([{"path": "shards/one.jsonl", "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}]).encode("utf-8")).hexdigest(),
        "shards": [{
            "path": "shards/one.jsonl",
            "shard_sha256": hashlib.sha256(shard.read_bytes()).hexdigest(),
            "document_count": len(records),
            "average_token_count": sum(map(len, tokens_by_doc.values())) / len(records),
            "document_token_counts": {doc_id: len(tokens) for doc_id, tokens in tokens_by_doc.items()},
            "document_frequencies": frequencies,
        }],
    }
    index["index_sha256"] = hashlib.sha256(canonical_json(index).encode("utf-8")).hexdigest()
    index_path = tmp_path / "bm25_statistics_index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    manifest = {
        "schema_version": "open_agronomy_agent.offline_corpus_release.v1",
        "release_id": "us-test",
        "shards": [{"path": "shards/one.jsonl", "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}],
        "mlra_shards": {"001X": ["shards/one.jsonl"], "002X": ["shards/one.jsonl"]},
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


@pytest.mark.parametrize("code", ["1X", "01x", "001X", "1", "001"])
def test_mlra_aliases_select_only_requested_records_with_provenance(tmp_path: Path, code: str) -> None:
    release = _release(tmp_path)
    docs = release.search(f"NRCS MLRA {code} ecological site climate", top_k=10)

    assert [doc.doc_id for doc in docs] == ["us-1"]
    doc = docs[0]
    assert doc.source == "https://example.test/nrcs"
    assert doc.raw_sha256 == "a" * 64
    assert doc.chunk_sha256 == "b" * 64
    assert doc.source_locator == {"json_document_id": "site-1", "raw_sha256": "a" * 64}
    assert doc.retrieval_policy == "context_only"
    assert doc.transfer_scope == "US_analogue_context_only"
    assert "no Canadian action authority" in doc.applicability_boundary


def test_unknown_mlra_does_not_load_any_shard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(tmp_path)

    def unexpected_read(*args: object) -> None:
        pytest.fail("unknown MLRA must not read corpus or statistics")

    monkeypatch.setattr(release, "_documents_for", unexpected_read)
    monkeypatch.setattr(release, "_statistics_for", unexpected_read)
    assert release._selected_relative_shards("NRCS MLRA 999Z climate") == ()
    assert release.search("NRCS MLRA 999Z climate") == []


def test_multiple_mlras_select_union_without_unrelated_records(tmp_path: Path) -> None:
    release = _release(tmp_path)
    docs = release.search("Compare NRCS MLRA 1 and MLRA 2 ecological sites", top_k=10)
    assert {doc.doc_id for doc in docs} == {"us-1", "us-2"}


@pytest.mark.parametrize("question", [
    "What is crop rotation?",
    "NRCS soil at 100 kg/ha and 20 mm rain",
    "What is the climate in 001X?",
    "Can NRCS MLRA 1 establish Saskatchewan fertilizer rates?",
    "Can NRCS MLRA 1 establish legal thresholds in Canada?",
    "Use NRCS MLRA 1 to set thresholds for Canada.",
    "NRCS MLRA 1: Saskatchewan\nfertilizer rates?",
])
def test_inactive_and_canadian_decisive_requests_remain_blocked(tmp_path: Path, question: str) -> None:
    assert _release(tmp_path).search(question, top_k=10) == []


def test_requested_mlra_cannot_override_retrieval_policy(tmp_path: Path) -> None:
    assert _release(tmp_path).search("NRCS MLRA 1", retrieval_policies=("decisive",)) == []
