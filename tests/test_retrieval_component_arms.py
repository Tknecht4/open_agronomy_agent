from __future__ import annotations

import pytest

import agronomy_agent.agent as agent_module
from agronomy_agent.agent import (
    build_context,
    load_agent_resources,
    reset_phase5_query_caches,
)
from agronomy_agent.phase5_cache import CacheResult


QUESTION = "What soil health evidence is relevant to soil erosion?"
RAG_CONFIG = "configs/rag.yaml"


@pytest.mark.parametrize(
    ("document_enabled", "graph_enabled"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_build_context_executes_only_the_enabled_retrieval_components(
    monkeypatch: pytest.MonkeyPatch,
    document_enabled: bool,
    graph_enabled: bool,
) -> None:
    reset_phase5_query_caches()
    resources = load_agent_resources(RAG_CONFIG)
    calls = {"document": 0, "graph": 0}
    original_search_agno = agent_module._search_agno
    original_graph_search = resources.graph.search

    def search_agno_spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls["document"] += 1
        return original_search_agno(*args, **kwargs)

    def graph_search_spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls["graph"] += 1
        return original_graph_search(*args, **kwargs)

    monkeypatch.setattr(agent_module, "_search_agno", search_agno_spy)
    monkeypatch.setattr(resources.graph, "search", graph_search_spy)

    context = build_context(
        QUESTION,
        resources=resources,
        use_context_cache=False,
        use_search_cache=False,
        document_retrieval_enabled=document_enabled,
        graph_retrieval_enabled=graph_enabled,
    )
    receipts = context.runtime_metadata["retrieval_component_receipts"]

    assert calls["document"] == int(document_enabled)
    assert calls["graph"] == int(graph_enabled)
    assert bool(context.retrieved_docs) is document_enabled
    assert bool(context.graph_hits) is graph_enabled
    assert receipts["document_retrieval"]["executed"] is document_enabled
    assert receipts["graph_retrieval"]["executed"] is graph_enabled
    assert receipts["document_retrieval"]["state"] == (
        "completed" if document_enabled else "disabled_by_arm"
    )
    assert receipts["graph_retrieval"]["state"] == (
        "completed" if graph_enabled else "disabled_by_arm"
    )
    evidence_packet = context.runtime_metadata["evidence_fabric"]["evidence_packet"]
    assert bool(evidence_packet["selected_document_order"]) is document_enabled
    graph_evidence = [
        row
        for row in evidence_packet["capability_evidence"]
        if row["evidence_kind"] == "graph_assertion"
    ]
    assert bool(graph_evidence) is graph_enabled


@pytest.mark.parametrize(
    "order",
    [
        [(True, True), (False, False), (True, False), (False, True)],
        [(False, False), (False, True), (True, False), (True, True)],
    ],
)
def test_retrieval_arm_context_cache_is_order_independent(
    order: list[tuple[bool, bool]],
) -> None:
    reset_phase5_query_caches()
    first_pass: dict[tuple[bool, bool], tuple[list[str], list[str]]] = {}
    for document_enabled, graph_enabled in order:
        context = build_context(
            QUESTION,
            rag_config=RAG_CONFIG,
            document_retrieval_enabled=document_enabled,
            graph_retrieval_enabled=graph_enabled,
        )
        first_pass[(document_enabled, graph_enabled)] = (
            [doc.doc_id for doc in context.retrieved_docs],
            [hit.node_id for hit in context.graph_hits],
        )

    for document_enabled, graph_enabled in reversed(order):
        context = build_context(
            QUESTION,
            rag_config=RAG_CONFIG,
            document_retrieval_enabled=document_enabled,
            graph_retrieval_enabled=graph_enabled,
        )
        observed = (
            [doc.doc_id for doc in context.retrieved_docs],
            [hit.node_id for hit in context.graph_hits],
        )
        assert observed == first_pass[(document_enabled, graph_enabled)]
        assert bool(observed[0]) is document_enabled
        assert bool(observed[1]) is graph_enabled
        assert context.cache_status == {
            "route": "hit",
            "agno": "hit" if document_enabled else "disabled_by_arm",
            "kg": "hit" if graph_enabled else "disabled_by_arm",
        }


def test_miskeyed_cached_context_is_rejected_before_disabled_outputs_can_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_phase5_query_caches()
    contaminated = build_context(
        QUESTION,
        rag_config=RAG_CONFIG,
        document_retrieval_enabled=True,
        graph_retrieval_enabled=True,
    )
    assert contaminated.retrieved_docs
    assert contaminated.graph_hits

    monkeypatch.setattr(
        agent_module._AGNO_CONTEXT_CACHE,
        "get",
        lambda _key: CacheResult(value=contaminated, cache_status="hit"),
    )
    with pytest.raises(ValueError, match="cached context retrieval controls mismatch"):
        build_context(
            QUESTION,
            rag_config=RAG_CONFIG,
            document_retrieval_enabled=False,
            graph_retrieval_enabled=False,
        )


def test_retrieval_controls_require_real_booleans() -> None:
    with pytest.raises(TypeError, match="document_retrieval_enabled must be a bool"):
        build_context(
            QUESTION,
            rag_config=RAG_CONFIG,
            document_retrieval_enabled=0,  # type: ignore[arg-type]
        )
