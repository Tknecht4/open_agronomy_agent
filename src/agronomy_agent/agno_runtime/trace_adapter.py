from __future__ import annotations

import hashlib
from typing import Any

from agronomy_agent.agent import AgentContext
from agronomy_agent.agno_runtime.knowledge_factory import AGNO_VERSION


def build_agno_trace(
    *,
    trace_id: str,
    turn_id: str,
    context: AgentContext,
    runtime_mode: str,
    total_latency_ms: float,
    retrieval_latency_ms: float,
    model_id: str = "mock",
    answer_status: str = "generated",
    leak_check_passed: bool = True,
    risk_banner_present: bool = False,
    missing_data_present: bool = False,
) -> dict[str, Any]:
    metadata = context.runtime_metadata or {}
    knowledge = metadata.get("agno_knowledge") or {
        "mode": "custom_retriever",
        "knowledge_base": "agno_local",
        "contents_table": "",
        "vector_table": "",
        "search_type": "keyword",
        "filters": {},
        "top_k": len(context.retrieved_docs) or 1,
    }
    filters = knowledge.get("filters") or {}
    return {
        "schema_version": "agno_rag_trace_v1",
        "trace_id": trace_id,
        "turn_id": turn_id,
        "runtime": {
            "agent_runtime": runtime_mode,
            "agno_version": None if AGNO_VERSION == "not_installed" else AGNO_VERSION,
            "model_adapter": "agronomy_agent.agno_runtime.model_adapter",
            "model_id": model_id,
        },
        "route": {
            "question_type": context.route.question_type,
            "risk_level": context.route.risk_level,
            "namespaces": list(context.route.namespaces),
            "required_tools": list(context.route.required_tools),
            "knowledge_filters": filters,
        },
        "knowledge": knowledge,
        "evidence": [_evidence_doc(index, doc, metadata.get("selected_retriever", "agno")) for index, doc in enumerate(context.retrieved_docs, 1)],
        "tools": [
            {
                "name": note.name,
                "source": "agronomy_guard",
                "status": "called",
                "payload_hash": hashlib.sha256(note.text.encode("utf-8")).hexdigest(),
                "skill_id": note.skill_id,
                "boundary": note.boundary,
                "risk_class": note.risk_class,
                "provenance": list(note.provenance),
                "eval_tags": list(note.eval_tags),
            }
            for note in context.tool_notes
        ],
        "answer": {
            "answer_status": answer_status,
            "leak_check_passed": leak_check_passed,
            "risk_banner_present": risk_banner_present,
            "missing_data_present": missing_data_present,
        },
        "metrics": {
            "total_latency_ms": total_latency_ms,
            "retrieval_latency_ms": retrieval_latency_ms,
            "retrieval_doc_count": len(context.retrieved_docs),
            "source_diversity": len({doc.source for doc in context.retrieved_docs}),
            "top_doc_score": context.retrieved_docs[0].score if context.retrieved_docs else None,
            "context_packer_version": context.packed_context.version if context.packed_context else None,
            "context_tokens_est": context.packed_context.token_estimate if context.packed_context else None,
        },
    }


def _evidence_doc(rank: int, doc: Any, selected_retriever: str) -> dict[str, Any]:
    return {
        "rank": rank,
        "doc_id": doc.doc_id,
        "source_id": doc.source,
        "title": doc.title,
        "source": doc.source,
        "score": float(doc.score),
        "retriever": "legacy" if selected_retriever == "legacy_benchmark" else "agno",
        "metadata": {
            "namespaces": list(doc.namespaces),
            "source_type": doc.source_type,
            "knowledge_domains": list(doc.knowledge_domains),
            "knowledge_bucket": doc.knowledge_bucket,
            "source_id": doc.source_id,
            "jurisdictions": list(doc.jurisdictions),
            "languages": list(doc.languages),
            "currency_status": doc.currency_status,
            "retrieval_policy": doc.retrieval_policy,
            "content_risk_tags": list(doc.content_risk_tags),
            "license_status": doc.license_status,
            "license_identifier": doc.license_identifier,
            "license_evidence_url": doc.license_evidence_url,
            "raw_sha256": doc.raw_sha256,
            "chunk_sha256": doc.chunk_sha256,
            "manifest_sha256": doc.manifest_sha256,
        },
    }
