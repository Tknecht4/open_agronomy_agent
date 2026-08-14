from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest
from fastapi.testclient import TestClient

from agronomy_agent.agent import load_agent_resources
from agronomy_agent.corpus_governance import audit_runtime_corpora
from agronomy_agent.runtime_profiles import (
    DEFAULT_MODEL_CONFIG,
    DEFAULT_RAG_CONFIG,
    load_runtime_profile_registry,
)
from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from scripts.build_portable_agent_bundle import select_curated_store_artifacts
from scripts.build_runtime_corpus_policy import build_policy


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CORPORA = {
    "data/seed/agronomy_rag_corpus.jsonl",
    "data/seed/boundary_rag_corpus.jsonl",
    "data/derived/rag/soilwise_rag_corpus.jsonl",
    "data/derived/rag/curated_canada/releases/2026-08-14/shards/context_only-canada-offline-master-0001.jsonl",
    "data/derived/rag/curated_canada/releases/2026-08-14/shards/requires_live_authority-canada-offline-master-0001.jsonl",
    "data/derived/rag/nrcs_esd_rag_corpus_compact_v2.jsonl",
}
ACTIVE_GRAPHS = {
    "data/seed/agronomy_knowledge_graph.json",
    "data/derived/rag/soilwise_knowledge_graph.json",
}


def test_runtime_registry_has_one_explicit_active_product_profile() -> None:
    registry = load_runtime_profile_registry()

    assert registry.release_model_config == DEFAULT_MODEL_CONFIG
    assert registry.default_rag_config == DEFAULT_RAG_CONFIG
    assert registry.selectable_rag_configs == (DEFAULT_RAG_CONFIG,)
    assert set(registry.historical_rag_configs) == {
        "configs/rag_final_mvp.yaml",
        "configs/rag_governed_runtime_v1.yaml",
    }
    assert not (ROOT / "configs/rag.yaml").exists()
    assert not list((ROOT / "configs").glob("rag_canada_v*_candidate.yaml"))


def test_active_product_profile_is_the_cumulative_master_without_legacy_duplicates() -> None:
    config = yaml.safe_load((ROOT / DEFAULT_RAG_CONFIG).read_text(encoding="utf-8"))
    retrieval = config["retrieval"]

    assert retrieval["corpus_policy_manifest"] == "data/manifests/runtime_corpus_policy_v2.json"
    assert set(retrieval["corpus_paths"]) == ACTIVE_CORPORA
    assert set(retrieval["graph_paths"]) == ACTIVE_GRAPHS
    assert retrieval["require_graph_manifests"] is True
    assert not any("canada_agronomy_distributable" in path for path in retrieval["corpus_paths"])
    assert not any("supplement" in path for path in retrieval["corpus_paths"])
    assert not any("forum" in path for path in retrieval["corpus_paths"])


def test_composite_policy_is_reproducible_and_audits_cleanly() -> None:
    expected = json.loads(
        (ROOT / "data/manifests/runtime_corpus_policy_v2.json").read_text(encoding="utf-8")
    )
    rebuilt = build_policy(root=ROOT)

    assert rebuilt == expected
    assert {row["path"] for row in rebuilt["corpora"]} == ACTIVE_CORPORA
    report = audit_runtime_corpora(
        root=ROOT,
        rag_config_path=ROOT / DEFAULT_RAG_CONFIG,
    )
    assert report["status"] == "pass", report["errors"]
    assert report["configured_corpus_count"] == 6


def test_portable_bundle_carries_the_master_store_proof_set() -> None:
    release_root = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14"
    selected = select_curated_store_artifacts(ROOT, ROOT / DEFAULT_RAG_CONFIG)

    assert {path.relative_to(ROOT).as_posix() for path in selected} == {
        path.relative_to(ROOT).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    }


def test_active_runtime_loads_master_additions_and_both_governed_graphs() -> None:
    resources = load_agent_resources(DEFAULT_RAG_CONFIG)
    source_counts: dict[str, int] = {}
    for row in resources.retriever.docs:
        source_id = str(row.get("source_id") or row.get("source") or "")
        source_counts[source_id] = source_counts.get(source_id, 0) + 1

    assert len(resources.retriever.docs) == 35419
    assert len(resources.graph.nodes) == 1794
    assert len(resources.graph.edges) == 1458
    assert source_counts["mb_2026_crop_disease_scouting"] == 4
    assert source_counts["mb_2023_crop_rotation_context"] == 4
    assert source_counts["ab_tame_pasture_range_health_2017"] == 4
    assert source_counts["mb_2026_canola_insect_scouting"] == 5


def test_server_defaults_and_override_discovery_use_only_registered_profiles(tmp_path: Path) -> None:
    settings = build_settings(
        db_path=tmp_path / "runtime-profiles.sqlite3",
        artifact_root=tmp_path / "artifacts",
        allow_rag_config_override=True,
    )

    assert settings.model_config_path == DEFAULT_MODEL_CONFIG
    assert settings.default_rag_config == DEFAULT_RAG_CONFIG
    response = TestClient(create_app(settings)).get("/api/configs")
    assert response.status_code == 200
    assert response.json()["rag_configs"] == [DEFAULT_RAG_CONFIG]
    assert response.json()["default_rag_config"] == DEFAULT_RAG_CONFIG


def test_server_rejects_a_historical_profile_as_an_unsigned_product_default(tmp_path: Path) -> None:
    settings = build_settings(
        db_path=tmp_path / "historical-runtime.sqlite3",
        artifact_root=tmp_path / "artifacts",
        default_rag_config="configs/rag_final_mvp.yaml",
        allow_rag_config_override=True,
    )

    with pytest.raises(ValueError, match="not an active registered runtime profile"):
        create_app(settings)
