from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agronomy_agent.agno_runtime.knowledge_graph import (
    GRAPH_MANIFEST_SCHEMA_VERSION,
    GraphManifest,
    GraphSpec as RuntimeGraphSpec,
    GraphValidationError,
    KnowledgeGraph,
    graph_artifact_paths,
    load_graph_manifests,
    load_graph_specs,
)
from agronomy_agent.capability_registry import (
    GRAPH_REGISTRY_SCHEMA_VERSION,
    GraphSpec as RegistryGraphSpec,
)
from agronomy_agent.evals import build_rag_artifact_identity
from agronomy_agent.evidence_contracts import capability_evidence_from_records, sha256_text, canonical_json


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_graph(
    path: Path,
    *,
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "nodes": nodes
                if nodes is not None
                else [
                    {
                        "id": "soil_n",
                        "name": "soil nitrogen",
                        "kind": "nutrient",
                        "description": "Nitrogen in soil.",
                        "aliases": ["N"],
                    }
                ],
                "edges": edges if edges is not None else [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_manifest(
    graph_path: Path,
    *,
    graph_id: str,
    priority: int = 10,
    collision_policy: str = "error",
    relations: list[str] | None = None,
    source: str = "https://example.test/graph",
    extra: dict | None = None,
) -> Path:
    payload = {
        "schema_version": GRAPH_MANIFEST_SCHEMA_VERSION,
        "graph_id": graph_id,
        "version": "1.0.0",
        "data_path": graph_path.name,
        "namespaces": ["soil_health"],
        "source": source,
        "license": "CC-BY-4.0",
        "sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
        "authority_role": "vocabulary_hint",
        "priority": priority,
        "collision_policy": collision_policy,
        "relation_vocabulary": relations or ["related_to"],
    }
    payload.update(extra or {})
    manifest_path = graph_path.with_name(f"{graph_path.stem}.manifest.json")
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def test_missing_configured_graph_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    with pytest.raises(GraphValidationError, match="does not exist"):
        KnowledgeGraph.from_paths([missing])


def test_runtime_strict_mode_requires_a_manifest(tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path / "graph.json")

    with pytest.raises(GraphValidationError, match="requires provenance manifest"):
        KnowledgeGraph.from_paths([graph_path], require_manifests=True)


def test_manifest_checksum_is_verified_before_graph_load(tmp_path: Path) -> None:
    graph_path = _write_graph(tmp_path / "graph.json")
    _write_manifest(graph_path, graph_id="test.checksum")
    graph_path.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    with pytest.raises(GraphValidationError, match="checksum mismatch"):
        KnowledgeGraph.from_paths([graph_path], require_manifests=True)


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        ([{"id": "x", "kind": "concept"}], [], "name must be a non-empty string"),
        (
            [{"id": "x", "name": "X", "kind": "concept", "aliases": "not-an-array"}],
            [],
            "aliases must be an array of strings",
        ),
        (
            [{"id": "x", "name": "X", "kind": "concept"}],
            [{"source": "x", "target": "x", "relation": "NOT VALID"}],
            "invalid relation",
        ),
    ],
)
def test_malformed_nodes_and_edges_fail_validation(
    tmp_path: Path,
    nodes: list[dict],
    edges: list[dict],
    message: str,
) -> None:
    graph_path = _write_graph(tmp_path / "graph.json", nodes=nodes, edges=edges)

    with pytest.raises(GraphValidationError, match=message):
        KnowledgeGraph.from_paths([graph_path])


def test_dangling_edges_fail_after_bundle_composition(tmp_path: Path) -> None:
    graph_path = _write_graph(
        tmp_path / "graph.json",
        edges=[{"source": "soil_n", "target": "missing", "relation": "related_to"}],
    )

    with pytest.raises(GraphValidationError, match="dangling edge"):
        KnowledgeGraph.from_paths([graph_path])


def test_manifest_relation_vocabulary_and_node_namespaces_are_enforced(tmp_path: Path) -> None:
    graph_path = _write_graph(
        tmp_path / "graph.json",
        nodes=[
            {
                "id": "soil_n",
                "name": "soil nitrogen",
                "kind": "nutrient",
                "aliases": [],
                "namespaces": ["plant_health"],
            }
        ],
        edges=[{"source": "soil_n", "target": "soil_n", "relation": "broader"}],
    )
    _write_manifest(graph_path, graph_id="test.declarations", relations=["related_to"])

    with pytest.raises(GraphValidationError, match="namespaces absent from manifest"):
        KnowledgeGraph.from_paths([graph_path], require_manifests=True)

    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    payload["nodes"][0]["namespaces"] = ["soil_health"]
    graph_path.write_text(json.dumps(payload), encoding="utf-8")
    _write_manifest(graph_path, graph_id="test.declarations", relations=["related_to"])

    with pytest.raises(GraphValidationError, match="absent from manifest relation_vocabulary"):
        KnowledgeGraph.from_paths([graph_path], require_manifests=True)


def test_duplicate_node_ids_require_shared_declared_collision_policy(tmp_path: Path) -> None:
    first = _write_graph(tmp_path / "first.json")
    second = _write_graph(tmp_path / "second.json")
    _write_manifest(first, graph_id="test.first")
    _write_manifest(second, graph_id="test.second")

    with pytest.raises(GraphValidationError, match="without shared precedence policy"):
        KnowledgeGraph.from_paths([first, second], require_manifests=True)


def test_declared_priority_is_deterministic_independent_of_path_order(tmp_path: Path) -> None:
    low = _write_graph(
        tmp_path / "low.json",
        nodes=[{"id": "shared", "name": "low", "kind": "concept", "aliases": []}],
    )
    high = _write_graph(
        tmp_path / "high.json",
        nodes=[
            {"id": "shared", "name": "high", "kind": "concept", "aliases": []},
            {"id": "high_target", "name": "winner target", "kind": "concept", "aliases": []},
        ],
        edges=[{"source": "shared", "target": "high_target", "relation": "related_to"}],
    )
    _write_manifest(low, graph_id="test.low", priority=10, collision_policy="prefer_higher_priority")
    _write_manifest(high, graph_id="test.high", priority=20, collision_policy="prefer_higher_priority")

    forward = KnowledgeGraph.from_paths([low, high], require_manifests=True)
    reverse = KnowledgeGraph.from_paths([high, low], require_manifests=True)

    assert forward.nodes["shared"]["name"] == "high"
    assert reverse.nodes["shared"]["name"] == "high"
    assert forward.lookup_names(["high"])[0].graph_id == "test.high"
    assert forward.edges == reverse.edges == [
        {"source": "shared", "target": "high_target", "relation": "related_to"}
    ]
    assert forward.catalog() == reverse.catalog()


@pytest.mark.parametrize(
    "edge",
    (
        {"source": "shared", "target": "low_target", "relation": "related_to"},
        {"source": "low_target", "target": "shared", "relation": "related_to"},
    ),
)
def test_losing_graph_edge_cannot_reattach_to_semantically_different_winner(
    tmp_path: Path,
    edge: dict[str, str],
) -> None:
    low = _write_graph(
        tmp_path / "low.json",
        nodes=[
            {
                "id": "shared",
                "name": "fungal disease",
                "kind": "plant_health_condition",
                "aliases": [],
            },
            {
                "id": "low_target",
                "name": "fungicide response",
                "kind": "management_action",
                "aliases": [],
            },
        ],
        edges=[edge],
    )
    high = _write_graph(
        tmp_path / "high.json",
        nodes=[
            {
                "id": "shared",
                "name": "soil nitrogen",
                "kind": "nutrient",
                "aliases": [],
            }
        ],
    )
    _write_manifest(
        low,
        graph_id="test.low",
        priority=10,
        collision_policy="prefer_higher_priority",
    )
    _write_manifest(
        high,
        graph_id="test.high",
        priority=20,
        collision_policy="prefer_higher_priority",
    )

    errors: list[str] = []
    for graph_paths in ([low, high], [high, low]):
        with pytest.raises(
            GraphValidationError,
            match=(
                "edge in losing graph 'test.low' would reattach a collided node.*"
                "'shared' -> winner 'test.high'.*do not declare identity equivalence"
            ),
        ) as exc_info:
            KnowledgeGraph.from_paths(graph_paths, require_manifests=True)
        errors.append(str(exc_info.value))

    assert errors[0] == errors[1]


def test_equal_priority_collision_is_rejected_as_ambiguous(tmp_path: Path) -> None:
    first = _write_graph(tmp_path / "first.json")
    second = _write_graph(tmp_path / "second.json")
    _write_manifest(first, graph_id="test.first", collision_policy="prefer_higher_priority")
    _write_manifest(second, graph_id="test.second", collision_policy="prefer_higher_priority")

    with pytest.raises(GraphValidationError, match="ambiguous priority"):
        KnowledgeGraph.from_paths([first, second], require_manifests=True)


def test_graph_hit_preserves_origin_and_relation_path(tmp_path: Path) -> None:
    graph_path = _write_graph(
        tmp_path / "graph.json",
        nodes=[
            {"id": "a", "name": "alpha", "kind": "concept", "aliases": []},
            {"id": "b", "name": "beta", "kind": "concept", "aliases": []},
        ],
        edges=[{"source": "a", "target": "b", "relation": "related_to"}],
    )
    _write_manifest(graph_path, graph_id="test.provenance", source="https://example.test/source")

    hit = KnowledgeGraph.from_paths([graph_path], require_manifests=True).lookup_names(["alpha"])[0]

    assert hit.graph_id == "test.provenance"
    assert hit.graph_version == "1.0.0"
    assert hit.graph_source == "https://example.test/source"
    assert hit.graph_license == "CC-BY-4.0"
    assert len(hit.graph_sha256) == 64
    assert hit.authority_role == "vocabulary_hint"
    assert hit.relation_paths == ("test.provenance:a-[related_to]->b",)


def test_graph_capability_payload_hash_is_distinct_from_source_graph_hash(tmp_path: Path) -> None:
    graph_path = _write_graph(
        tmp_path / "graph.json",
        nodes=[
            {"id": "a", "name": "alpha", "kind": "concept", "aliases": []},
            {"id": "b", "name": "beta", "kind": "concept", "aliases": []},
        ],
    )
    _write_manifest(graph_path, graph_id="test.payload")
    graph = KnowledgeGraph.from_paths([graph_path], require_manifests=True)
    first, second = graph.lookup_names(["alpha", "beta"])

    def record(hit):  # noqa: ANN001, ANN202
        payload = {"node_id": hit.node_id, "evidence": hit.evidence}
        return {
            "evidence_kind": "graph_assertion",
            "capability_id": hit.graph_id,
            "capability_version": hit.graph_version,
            "result_id": f"graph_hit:{hit.graph_id}:{hit.node_id}",
            "payload": payload,
            "graph_sha256": hit.graph_sha256,
        }

    evidence = capability_evidence_from_records((record(first), record(second)))

    assert evidence[0].record["graph_sha256"] == evidence[1].record["graph_sha256"]
    assert evidence[0].payload_sha256 != evidence[1].payload_sha256
    assert evidence[0].payload_sha256 == sha256_text(canonical_json(evidence[0].record["payload"]))


def test_active_graph_bundle_has_manifests_and_preserves_retrieval_behavior() -> None:
    graph_paths = [
        REPO_ROOT / "data/seed/agronomy_knowledge_graph.json",
        REPO_ROOT / "data/derived/rag/soilwise_knowledge_graph.json",
    ]

    artifacts = graph_artifact_paths(graph_paths, require_manifests=True)
    graph = KnowledgeGraph.from_paths(graph_paths, require_manifests=True)
    hits = graph.search("gray leaf spot", namespaces=["plant_health"])

    assert len(artifacts) == 4
    assert {spec.graph_id for spec in graph.graph_specs} == {
        "open_agronomy.curated_seed",
        "soilwise.soil_health",
    }
    assert [entry["graph_id"] for entry in graph.catalog()] == [
        "open_agronomy.curated_seed",
        "soilwise.soil_health",
    ]
    assert all(entry["manifest_declared"] for entry in graph.catalog())
    assert hits[0].node_id == "disease_gls"
    assert hits[0].graph_id == "open_agronomy.curated_seed"


def test_runtime_graph_manifests_adapt_to_the_canonical_registry_contract() -> None:
    graph_paths = [
        REPO_ROOT / "data/seed/agronomy_knowledge_graph.json",
        REPO_ROOT / "data/derived/rag/soilwise_knowledge_graph.json",
    ]

    manifests = load_graph_manifests(graph_paths, require_manifests=True)
    specs = load_graph_specs(graph_paths, require_manifests=True)
    graph = KnowledgeGraph.from_paths(graph_paths, require_manifests=True)

    assert RuntimeGraphSpec is RegistryGraphSpec
    assert all(isinstance(manifest, GraphManifest) for manifest in manifests)
    assert all(isinstance(spec, RegistryGraphSpec) for spec in specs)
    assert graph.graph_specs == specs
    assert graph.registry_catalog() == {
        "schema_version": GRAPH_REGISTRY_SCHEMA_VERSION,
        "graph_count": 2,
        "graphs": [spec.as_record() for spec in specs],
    }

    manifests_by_id = {manifest.graph_id: manifest for manifest in manifests}
    catalog_by_id = {row["graph_id"]: row for row in graph.catalog()}
    for spec in specs:
        manifest = manifests_by_id[spec.graph_id]
        row = catalog_by_id[spec.graph_id]
        assert spec.checksum == manifest.sha256 == row["checksum"] == row["sha256"]
        assert spec.merge_priority == manifest.priority == row["merge_priority"] == row["priority"]
        assert spec.relation_vocabulary == manifest.relation_vocabulary
        assert spec.manifest_declared is manifest.manifest_declared is True
        assert spec.paths == (
            manifest.data_path.as_posix(),
            manifest.manifest_path.as_posix(),
        )


def test_evaluation_identity_binds_active_graph_manifests() -> None:
    class Resources:
        rag_config = {
            "retrieval": {
                "corpus_paths": [],
                "graph_paths": [
                    "data/seed/agronomy_knowledge_graph.json",
                    "data/derived/rag/soilwise_knowledge_graph.json",
                ],
                "require_graph_manifests": True,
            }
        }

    records = build_rag_artifact_identity(Resources())

    assert [record["kind"] for record in records] == [
        "graph",
        "graph_manifest",
        "graph",
        "graph_manifest",
    ]
