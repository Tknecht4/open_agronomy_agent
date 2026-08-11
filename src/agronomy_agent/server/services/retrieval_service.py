from __future__ import annotations

from typing import Any

from agronomy_agent.local_tools import retrieve_context
from agronomy_agent.phase5_retrieval_diagnostics import diagnose_retrieval


def retrieve_only(message: str, top_k: int, rag_config: str) -> dict[str, Any]:
    return retrieve_context(message, top_k=top_k, rag_config=rag_config)


def retrieval_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = diagnose_retrieval(
        question=str(payload.get("question") or payload.get("message") or ""),
        docs=payload.get("retrieved_docs", []),
        route_namespaces=(payload.get("route") or {}).get("namespaces") or payload.get("route_namespaces"),
        required_patterns=payload.get("required_patterns", []),
        required_concepts=payload.get("required_concepts", []),
        gold_doc_ids=payload.get("gold_support_doc_ids", payload.get("support_doc_ids", [])),
        cache_status=payload.get("cache_status"),
        latency_ms=payload.get("retrieval_latency_ms"),
        rag_score=payload.get("rag_score"),
        no_rag_score=payload.get("no_rag_score"),
    )
    return {**diagnostics, "tool_notes": len(payload.get("tool_notes", []))}
