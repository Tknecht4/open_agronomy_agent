from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_offline_agronomy_composite_profile.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_offline_agronomy_composite_profile", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_replaces_compact_nrcs_with_source_exact_active_and_on_demand_shards(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    base_config = tmp_path / "base.yaml"
    base_config.write_text(yaml.safe_dump({"retrieval": {"corpus_paths": ["data/a.jsonl"]}}), encoding="utf-8")
    active_shard = tmp_path / "data" / "active" / "shards" / "canadian_context-0001.jsonl"
    active_shard.parent.mkdir(parents=True)
    active_shard.write_text('{"doc_id":"canada"}\n', encoding="utf-8")
    active = tmp_path / "data" / "active" / "store_manifest.json"
    active.write_text(json.dumps({"store_id": "offline-agronomy", "store_sha256": "y", "shards": [{"path": "shards/canadian_context-0001.jsonl", "sha256": hashlib.sha256(active_shard.read_bytes()).hexdigest(), "retrieval_policies": ["context_only"]}]}), encoding="utf-8")
    shard = tmp_path / "data" / "release" / "shards" / "one.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_text('{"doc_id":"one"}\n', encoding="utf-8")
    store = tmp_path / "data" / "release" / "store_manifest.json"
    store.write_text(json.dumps({"release_id": "us", "store_sha256": "x", "shards": [{"path": "shards/one.jsonl", "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}]}), encoding="utf-8")
    config, policy = module.build_profile(base_config=base_config, active_store=active, us_store=store)
    assert config["retrieval"]["corpus_paths"] == ["data/active/shards/canadian_context-0001.jsonl"]
    assert config["retrieval"]["on_demand_corpus_releases"] == [
        {
            "release_id": "us",
            "manifest_path": "data/release/store_manifest.json",
            "activation": "explicit_us_nrcs_or_mlra",
            "jurisdiction": "United States",
            "retrieval_policy": "context_only",
            "authority_boundary": "U.S. material is analogue/context only for Canadian questions.",
        }
    ]
    entry = policy["corpora"][-1]
    assert entry["runtime_eligibility"] == "context_only"
    assert entry["evidence_tier"] == "US_government_analogue_reference"
    assert entry["activation"] == "explicit_us_nrcs_or_mlra"
