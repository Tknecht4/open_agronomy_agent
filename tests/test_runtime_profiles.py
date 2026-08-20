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


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CORPORA = {
    "data/derived/rag/offline_agronomy/active/shards/canadian_context-0001.jsonl",
    "data/derived/rag/offline_agronomy/active/shards/canadian_live-0001.jsonl",
    "data/derived/rag/offline_agronomy/active/shards/project_context-0001.jsonl",
    "data/derived/rag/offline_agronomy/active/shards/project_decisive-0001.jsonl",
    "data/derived/rag/offline_agronomy/active/shards/soilwise_context-0001.jsonl",
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
    assert (ROOT / "configs/rag.yaml").is_file()
    assert not list((ROOT / "configs").glob("rag_canada_v*_candidate.yaml"))


def test_active_product_profile_is_source_exact_without_legacy_duplicates() -> None:
    config = yaml.safe_load((ROOT / DEFAULT_RAG_CONFIG).read_text(encoding="utf-8"))
    retrieval = config["retrieval"]

    assert retrieval["corpus_policy_manifest"] == "data/manifests/runtime_corpus_policy.json"
    assert set(retrieval["corpus_paths"]) == ACTIVE_CORPORA
    assert set(retrieval["graph_paths"]) == ACTIVE_GRAPHS
    assert retrieval["require_graph_manifests"] is True
    assert not any("canada_agronomy_distributable" in path for path in retrieval["corpus_paths"])
    assert not any("supplement" in path for path in retrieval["corpus_paths"])
    assert not any("forum" in path for path in retrieval["corpus_paths"])
    assert not any("compact" in path for path in retrieval["corpus_paths"])
    assert retrieval["on_demand_corpus_releases"][0]["release_id"] == "us-nrcs-full-reference"


def test_composite_policy_covers_active_and_on_demand_corpora() -> None:
    policy = json.loads((ROOT / "data/manifests/runtime_corpus_policy.json").read_text(encoding="utf-8"))
    assert ACTIVE_CORPORA <= {row["path"] for row in policy["corpora"]}
    report = audit_runtime_corpora(
        root=ROOT,
        rag_config_path=ROOT / DEFAULT_RAG_CONFIG,
    )
    assert report["status"] == "pass", report["errors"]
    assert report["configured_corpus_count"] == 56


def test_portable_bundle_carries_the_active_store_proof_set() -> None:
    release_root = ROOT / "data/derived/rag/offline_agronomy/active"
    selected = select_curated_store_artifacts(ROOT, ROOT / DEFAULT_RAG_CONFIG)

    assert {path.relative_to(ROOT).as_posix() for path in selected} == {
        path.relative_to(ROOT).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    }


def test_active_runtime_loads_source_exact_corpus_and_both_governed_graphs() -> None:
    resources = load_agent_resources(DEFAULT_RAG_CONFIG)
    source_counts: dict[str, int] = {}
    for row in resources.retriever.docs:
        source_id = str(row.get("source_id") or row.get("source") or "")
        source_counts[source_id] = source_counts.get(source_id, 0) + 1

    assert len(resources.retriever.docs) == 3086
    assert len(resources.graph.nodes) == 1794
    assert len(resources.graph.edges) == 1458
    assert source_counts["ab_nutrient_management_planning_guide_2008"] > 0
    assert source_counts["on_field_crop_production_current"] > 0


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
