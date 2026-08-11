from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

from agronomy_agent.agno_runtime.local_index import tokenize


CONCEPT_ALIASES = {
    "sar": (("sodium", "adsorption", "ratio"),),
    "esp": (("exchangeable", "sodium", "percentage"),),
    "ec": (("electrical", "conductivity"),),
    "ece": (("soil", "electrical", "conductivity"), ("electrical", "conductivity", "soil")),
    "climate": (("climatic",), ("precipitation",), ("temperature",)),
}


def diagnose_retrieval(
    *,
    question: str,
    docs: Iterable[Any],
    route_namespaces: Iterable[str] | None = None,
    required_patterns: Iterable[str] | None = None,
    required_concepts: Iterable[str] | None = None,
    gold_doc_ids: Iterable[str] | None = None,
    cache_status: str | None = None,
    latency_ms: float | None = None,
    rag_score: float | None = None,
    no_rag_score: float | None = None,
) -> dict[str, Any]:
    """Return packet-level Phase 5 retrieval diagnostics for one query."""

    doc_list = list(docs)
    joined = "\n".join(f"{_field(doc, 'title', '')}\n{_field(doc, 'text', '')}" for doc in doc_list)
    joined_tokens = set(tokenize(joined))
    patterns = [str(pattern) for pattern in required_patterns or []]
    concepts = [str(concept) for concept in required_concepts or []]
    supported_patterns = [pattern for pattern in patterns if re.search(pattern, joined, re.I | re.M)]
    supported_concepts = [concept for concept in concepts if _concept_supported(concept, joined_tokens, joined)]
    required_total = len(patterns) + len(concepts)
    supported_total = len(supported_patterns) + len(supported_concepts)

    retrieved_ids = [str(_field(doc, "doc_id", "")) for doc in doc_list]
    gold_ids = {str(doc_id) for doc_id in gold_doc_ids or [] if str(doc_id)}
    relevance = [1 if doc_id in gold_ids else 0 for doc_id in retrieved_ids]
    source_types = Counter(str(_field(doc, "source_type", "unknown") or "unknown") for doc in doc_list)
    route_set = {str(namespace) for namespace in route_namespaces or [] if str(namespace)}
    source_diversity = len({str(_field(doc, "source", "")) for doc in doc_list if str(_field(doc, "source", ""))})
    context_token_est = sum(len(tokenize(f"{_field(doc, 'title', '')} {_field(doc, 'text', '')}")) for doc in doc_list)
    route_matches = sum(1 for doc in doc_list if route_set and route_set.intersection(_namespaces(doc)))
    applied_count = source_types.get("applied_guidance", 0)
    ontology_count = source_types.get("ontology", 0)

    result: dict[str, Any] = {
        "diagnostic_version": "phase5_retrieval_diagnostics_v1",
        "question_token_count": len(tokenize(question)),
        "doc_count": len(doc_list),
        "retrieved_doc_ids": retrieved_ids,
        "source_diversity": source_diversity,
        "top_doc_score": float(_field(doc_list[0], "score", 0.0)) if doc_list else 0.0,
        "source_type_counts": dict(sorted(source_types.items())),
        "applied_vs_ontology_ratio": round(applied_count / max(1, ontology_count), 4),
        "applied_guidance_share": round(applied_count / max(1, len(doc_list)), 4),
        "route_namespace_match_rate": round(route_matches / len(doc_list), 4) if doc_list and route_set else None,
        "context_token_est": context_token_est,
        "required_patterns": len(patterns),
        "required_concepts": len(concepts),
        "required_patterns_supported_by_retrieval": len(supported_patterns),
        "required_concepts_supported_by_retrieval": len(supported_concepts),
        "retrieved_required_patterns": supported_patterns,
        "retrieved_required_concepts": supported_concepts,
        "retrieval_required_support_rate": round(supported_total / max(1, required_total), 4),
        "support_per_context_token": round(supported_total / max(1, context_token_est), 6),
        "cache_status": cache_status,
        "cache_hit": cache_status == "hit",
        "retrieval_latency_ms": round(float(latency_ms), 3) if latency_ms is not None else None,
        "gold_doc_count": len(gold_ids),
        "recall_at_k": round(sum(relevance) / len(gold_ids), 4) if gold_ids else None,
        "mrr": _reciprocal_rank(relevance) if gold_ids else None,
        "ndcg_at_k": _ndcg(relevance, len(gold_ids)) if gold_ids else None,
        "answer_gain_over_no_rag": round(float(rag_score) - float(no_rag_score), 4)
        if rag_score is not None and no_rag_score is not None
        else None,
    }
    return result


def _field(doc: Any, name: str, default: Any = None) -> Any:
    if isinstance(doc, dict):
        return doc.get(name, default)
    return getattr(doc, name, default)


def _namespaces(doc: Any) -> set[str]:
    raw = _field(doc, "namespaces", ())
    if raw is None:
        return set()
    return {str(namespace) for namespace in raw if str(namespace)}


def _concept_supported(concept: str, joined_tokens: set[str], joined_text: str) -> bool:
    tokens = tokenize(concept)
    if tokens and set(tokens).issubset(joined_tokens):
        return True
    if len(tokens) == 1 and re.search(rf"\b{re.escape(tokens[0])}(?:\b|-)", joined_text, re.I):
        return True
    alias_groups = CONCEPT_ALIASES.get(concept.strip().lower(), ())
    if alias_groups:
        return any(set(alias).issubset(joined_tokens) for alias in alias_groups)
    if tokens:
        return set(tokens).issubset(joined_tokens)
    return bool(concept and concept.lower() in joined_text.lower())


def _reciprocal_rank(relevance: list[int]) -> float:
    for index, value in enumerate(relevance, start=1):
        if value:
            return round(1.0 / index, 4)
    return 0.0


def _ndcg(relevance: list[int], gold_count: int) -> float:
    if not relevance or gold_count <= 0:
        return 0.0
    dcg = sum(value / math.log2(rank + 1) for rank, value in enumerate(relevance, start=1) if value)
    ideal_hits = min(gold_count, len(relevance))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return round(dcg / max(idcg, 1e-9), 4)
