from __future__ import annotations

import json
import math
import pickle
import re
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from heapq import nlargest
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.paths import minimized_path_reference


TOKEN_RE = re.compile(r"[^\W\d_][\w+-]{2,}", re.UNICODE)
MLRA_CODE_RE = re.compile(r"\b0?(\d{2,3}[A-Za-z])\b")
INDEX_CACHE_VERSION = "agno_lexical_index_v21"
LOW_SIGNAL_SCORING_IDF = 0.25
HIGH_FANOUT_SCORING_RATIO = 0.35
HIGH_FANOUT_SCORING_MIN_POSTINGS = 1000
DIRECT_SCORING_ALWAYS_ELIGIBLE_DOCS = 64
DIRECT_SCORING_MAX_ELIGIBLE_DOCS = 512
DIRECT_SCORING_COST_RATIO = 0.75
STATIC_FILTER_CACHE_MAX_ENTRIES = 512
QUERY_SCORING_PLAN_CACHE_MAX_ENTRIES = 512
QUERY_FOCUS_ELIGIBLE_CACHE_MAX_ENTRIES = 512
REGIONAL_MLRA_ELIGIBLE_CACHE_MAX_ENTRIES = 512
NAMESPACE_PREFILTER_MIN_ELIGIBLE_DOCS = 65
NAMESPACE_PREFILTER_MIN_MATCHES = 8
QUERY_FOCUS_NAMESPACE_PREFILTER_MIN_MATCHES = 8
STOPWORDS = {
    "after",
    "before",
    "can",
    "heavy",
    "how",
    "near",
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "field",
    "what",
    "when",
    "where",
    "should",
    "verify",
    "would",
    "could",
    "need",
    "avec",
    "avant",
    "comment",
    "dans",
    "des",
    "dois",
    "doit",
    "est",
    "les",
    "pour",
    "pourquoi",
    "quelle",
    "quelles",
    "quels",
    "sont",
    "une",
    "vérifier",
}
FRENCH_QUERY_ANCHORS = {
    "avec",
    "comment",
    "cultures",
    "données",
    "dans",
    "des",
    "dois",
    "est",
    "les",
    "prévisions",
    "pourquoi",
    "quelle",
    "quelles",
    "quels",
    "rendement",
    "santé",
    "sont",
    "une",
    "vérifier",
}


@dataclass(frozen=True)
class RetrievedDoc:
    doc_id: str
    title: str
    text: str
    source: str
    score: float
    tags: tuple[str, ...]
    namespaces: tuple[str, ...]
    source_type: str
    allowed_roles: tuple[str, ...]
    crops: tuple[str, ...] = ()
    knowledge_domains: tuple[str, ...] = ()
    knowledge_bucket: str = ""
    token_set: tuple[str, ...] = ()
    source_id: str = ""
    jurisdictions: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    currency_status: str = "unspecified"
    retrieval_policy: str = "standard"
    content_risk_tags: tuple[str, ...] = ()
    license_status: str = "unknown"
    license_identifier: str = ""
    license_evidence_url: str = ""
    license_attribution: str = ""
    raw_sha256: str = ""
    chunk_sha256: str = ""
    manifest_sha256: str = ""
    corpus_path: str = ""
    distribution_scope: str = ""
    answer_role: str = ""


@dataclass(frozen=True)
class SearchStats:
    query_token_count: int
    eligible_doc_count: int
    scoring_term_count: int
    deferred_low_signal_term_count: int
    deferred_high_fanout_term_count: int
    scoring_strategy: str
    scored_candidate_count: int
    result_count: int

    def as_record(self) -> dict[str, Any]:
        return {
            "query_token_count": self.query_token_count,
            "eligible_doc_count": self.eligible_doc_count,
            "scoring_term_count": self.scoring_term_count,
            "deferred_low_signal_term_count": self.deferred_low_signal_term_count,
            "deferred_high_fanout_term_count": self.deferred_high_fanout_term_count,
            "scoring_strategy": self.scoring_strategy,
            "scored_candidate_count": self.scored_candidate_count,
            "result_count": self.result_count,
        }


TOKEN_NORMALIZATIONS = {
    "sulphur": "sulfur",
    "sulphate": "sulfate",
    "sulphuric": "sulfuric",
    "mobilisation": "mobilization",
    "mineralisation": "mineralization",
}
NUTRIENT_TOKENS = {
    "boron",
    "calcium",
    "copper",
    "iron",
    "magnesium",
    "manganese",
    "molybdenum",
    "nitrogen",
    "phosphorus",
    "potassium",
    "sulfate",
    "sulfur",
    "zinc",
}
NAMESPACE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "fertility",
        ("fertil", "nutrient", "nitrogen", "phosphorus", "potassium", "sulfur", "lime", "manure", "soil test", "crop removal", "nitrate"),
    ),
    (
        "soil_water",
        (
            "soil water",
            "drainage",
            "tile",
            "salinity",
            "sodicity",
            "irrigat",
            "compaction",
            "erosion",
            "runoff",
            "leaching",
            "cover crop",
            "dryland",
            "water table",
        ),
    ),
    (
        "product_stewardship",
        ("product", "herbicide", "fungicide", "insecticide", "pesticide", "spray", "mode of action", "threshold", "seed treatment"),
    ),
    ("label_boundary", ("label", "registration", "jurisdiction", "regulated", "buffer", "ppe", "restricted entry", "preharvest")),
    ("plant_health", ("disease", "pest", "aphid", "leaf", "chlorosis", "gray leaf spot", "white mold", "photo diagnosis", "scouting", "fungicide")),
    ("crop_management", ("hybrid", "variety", "planting", "stand", "replant", "harvest", "storage", "establishment", "crop management")),
    ("precision_ag", ("variable rate", "prescription", "yield map", "ndvi", "soil ec", "as-applied", "georeference", "field data", "precision")),
    ("economics", ("economics", "profit", "roi", "partial budget", "cost", "price", "yield response", "check strip")),
    ("soil_health", ("soil health", "soilwise", "soil organic", "soil function", "soil property", "soil attribute")),
    (
        "regional_environment",
        (
            "mlra",
            "major land resource",
            "ecological site",
            "ecoregion",
            "ecodistrict",
            "ecozone",
            "physiograph",
            "landform",
            "geology",
            "soil landscape",
            "climate",
            "water table",
        ),
    ),
    ("exam_review", ("cca", "certified crop adviser", "exam", "performance objective", "review", "checklist")),
    ("field_data_boundary", ("audit trail", "records", "boundary", "validated layers", "raw layers")),
)
BOUNDARY_SOURCE_RE = re.compile(r"\b(boundary|label|registration|jurisdiction|validated layers|audit trail)\b")
EXAM_SOURCE_RE = re.compile(r"\b(cca|exam|performance objective|review)\b")
PREFIX_NAMESPACE_HINTS = {"fertil", "irrigat", "susceptib"}
NAMESPACE_TOKEN_HINTS: tuple[tuple[str, frozenset[str]], ...] = tuple(
    (name, frozenset(hint for hint in hints if " " not in hint and hint not in PREFIX_NAMESPACE_HINTS))
    for name, hints in NAMESPACE_HINTS
)
NAMESPACE_PREFIX_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (name, tuple(hint for hint in hints if hint in PREFIX_NAMESPACE_HINTS))
    for name, hints in NAMESPACE_HINTS
)
NAMESPACE_PHRASE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (name, tuple(hint for hint in hints if " " in hint))
    for name, hints in NAMESPACE_HINTS
)
NAMESPACE_HINT_TABLE: tuple[tuple[str, frozenset[str], tuple[str, ...], tuple[str, ...]], ...] = tuple(
    (name, token_hints, prefix_hints, phrase_hints)
    for (name, token_hints), (_, prefix_hints), (_, phrase_hints) in zip(
        NAMESPACE_TOKEN_HINTS,
        NAMESPACE_PREFIX_HINTS,
        NAMESPACE_PHRASE_HINTS,
    )
)
NAMESPACE_PHRASE_TOKEN_TABLE: tuple[tuple[str, frozenset[str], tuple[str, ...], tuple[frozenset[str], ...]], ...] = tuple(
    (
        name,
        token_hints,
        prefix_hints,
        tuple(frozenset(phrase.split()) for phrase in phrase_hints),
    )
    for name, token_hints, prefix_hints, phrase_hints in NAMESPACE_HINT_TABLE
)


def tokenize(text: str) -> list[str]:
    return list(_tokenize_cached(text))


def _detect_query_language(text: str) -> str | None:
    """Return a conservative language preference for retrieval reranking.

    This is intentionally not a general language classifier. It only detects a
    sufficiently strong French signal so bilingual government documents are not
    buried by a much larger English corpus. A preference changes ranking, never
    eligibility, so relevant English evidence remains available.
    """

    lowered = text.casefold()
    raw_tokens = {
        token.casefold()
        for token in re.findall(r"[^\W\d_][\w+-]{1,}", lowered, re.UNICODE)
    }
    anchor_count = len(raw_tokens & FRENCH_QUERY_ANCHORS)
    has_french_diacritic = bool(re.search(r"[àâçéèêëîïôùûüÿœæ]", lowered))
    if anchor_count >= 3 or (anchor_count >= 2 and has_french_diacritic):
        return "fr"
    return None


@lru_cache(maxsize=4096)
def _tokenize_cached(text: str) -> tuple[str, ...]:
    tokens = []
    for raw in TOKEN_RE.findall(text):
        token = TOKEN_NORMALIZATIONS.get(raw.lower(), raw.lower())
        if token not in STOPWORDS:
            tokens.append(token)
    for raw in MLRA_CODE_RE.findall(text):
        tokens.append(raw.lower().zfill(4))
    return tuple(tokens)


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


class LexicalRetriever:
    """Local BM25-like index used by the Agno compatibility Knowledge layer."""

    def __init__(self, docs: Iterable[dict]) -> None:
        self.docs = list(docs)
        doc_texts = [_doc_search_text(doc) for doc in self.docs]
        doc_tokens = [
            tokenize(text)
            for text in doc_texts
        ]
        self.doc_lengths = [len(toks) for toks in doc_tokens]
        self.doc_counts = [dict(Counter(toks)) for toks in doc_tokens]
        self.doc_token_sets = [tuple(sorted(set(toks))) for toks in doc_tokens]
        doc_freq: dict[str, int] = {}
        self.inverted_index: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for idx, counts in enumerate(self.doc_counts):
            for token, count in counts.items():
                doc_freq[token] = doc_freq.get(token, 0) + 1
                self.inverted_index[token].append((idx, count))
        self.avg_len = sum(self.doc_lengths) / max(1, len(self.doc_lengths))
        avg_len = max(1.0, self.avg_len)
        self.bm25_length_norms = [
            1.2 * (1 - 0.75 + 0.75 * doc_len / avg_len)
            for doc_len in self.doc_lengths
        ]
        total_docs = max(1, len(self.docs))
        self.idf = {
            token: math.log(1 + (total_docs - freq + 0.5) / (freq + 0.5))
            for token, freq in doc_freq.items()
        }
        self.doc_namespaces = [
            tuple(_infer_namespaces_from_token_set(doc, text, set(token_set)))
            for doc, text, token_set in zip(self.docs, doc_texts, self.doc_token_sets)
        ]
        self.doc_namespace_sets = [set(namespaces) for namespaces in self.doc_namespaces]
        self._namespace_index = _multi_value_index(self.doc_namespaces)[0]
        self.doc_source_types = [infer_source_type(doc) for doc in self.docs]
        self.doc_allowed_roles = [tuple(self._normalize_roles(doc.get("allowed_roles", []))) for doc in self.docs]
        self.doc_allowed_role_sets = [set(roles) for roles in self.doc_allowed_roles]
        self.doc_knowledge_domains = [tuple(self._normalize_knowledge_domains(doc.get("knowledge_domains", []))) for doc in self.docs]
        self.doc_knowledge_domain_sets = [set(domains) for domains in self.doc_knowledge_domains]
        self.doc_knowledge_buckets = [str(doc.get("knowledge_bucket", "")).strip().lower() for doc in self.docs]
        self.doc_retrieval_policies = [str(doc.get("retrieval_policy") or "standard").strip().lower() for doc in self.docs]
        self.doc_jurisdictions = [
            tuple(_normalize_string_values(doc.get("jurisdiction") or doc.get("region")))
            for doc in self.docs
        ]
        self.doc_languages = [
            tuple(_normalize_string_values(doc.get("language")))
            for doc in self.docs
        ]
        self._all_doc_indices = frozenset(range(len(self.docs)))
        self._source_type_index = _single_value_index(self.doc_source_types)
        self._allowed_role_index, self._empty_allowed_role_indices = _multi_value_index(self.doc_allowed_roles)
        self._knowledge_domain_index, self._empty_knowledge_domain_indices = _multi_value_index(self.doc_knowledge_domains)
        self._knowledge_bucket_index, self._empty_knowledge_bucket_indices = _single_value_index_with_empty(self.doc_knowledge_buckets)
        self._retrieval_policy_index = _single_value_index(self.doc_retrieval_policies)
        self._jurisdiction_index, self._empty_jurisdiction_indices = _multi_value_index(self.doc_jurisdictions)
        self._static_filter_cache: OrderedDict[
            tuple[
                tuple[str, ...],
                tuple[str, ...],
                str,
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
                bool,
            ],
            frozenset[int],
        ] = OrderedDict()
        self._query_scoring_plan_cache: OrderedDict[
            tuple[tuple[str, ...], int],
            tuple[
                tuple[tuple[str, int, float, int], ...],
                tuple[tuple[str, int, float], ...],
                tuple[tuple[str, int, float], ...],
            ],
        ] = {}
        self._query_focus_eligible_cache: OrderedDict[
            tuple[frozenset[int], tuple[str, ...], tuple[str, ...]],
            frozenset[int],
        ] = OrderedDict()
        self._regional_mlra_eligible_cache: OrderedDict[
            tuple[frozenset[int], tuple[str, ...], tuple[str, ...]],
            frozenset[int],
        ] = OrderedDict()
        self.last_search_stats = SearchStats(
            query_token_count=0,
            eligible_doc_count=0,
            scoring_term_count=0,
            deferred_low_signal_term_count=0,
            deferred_high_fanout_term_count=0,
            scoring_strategy="not_run",
            scored_candidate_count=0,
            result_count=0,
        )

    @staticmethod
    def _normalize_knowledge_domains(values: Iterable[str] | None) -> list[str]:
        if not values:
            return []
        return sorted({str(value).strip().lower() for value in values if str(value).strip()})

    @staticmethod
    def _normalize_roles(values: Iterable[str] | None) -> list[str]:
        if not values:
            return []
        return sorted({str(value).strip().lower() for value in values if str(value).strip()})

    @classmethod
    def from_jsonl(cls, path: Path) -> "LexicalRetriever":
        return cls(load_jsonl(path))

    @classmethod
    def from_jsonl_paths(cls, paths: Iterable[Path]) -> "LexicalRetriever":
        docs: list[dict] = []
        for path in paths:
            if path.exists():
                for row in load_jsonl(path):
                    docs.append(
                        {
                            **row,
                            "_corpus_path": minimized_path_reference(path),
                        }
                    )
        return cls(docs)

    @classmethod
    def from_compiled_cache(cls, path: Path) -> "LexicalRetriever":
        with path.open("rb") as handle:
            payload = pickle.load(handle)
        if not isinstance(payload, dict) or payload.get("version") != INDEX_CACHE_VERSION:
            raise ValueError("compiled lexical index cache version mismatch")
        retriever = payload.get("retriever")
        if not isinstance(retriever, cls):
            raise ValueError("compiled lexical index cache payload is invalid")
        return retriever

    def write_compiled_cache(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        with tmp_path.open("wb") as handle:
            pickle.dump({"version": INDEX_CACHE_VERSION, "retriever": self}, handle, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(path)

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        allowed_roles: Iterable[str] | None = None,
        knowledge_domains: Iterable[str] | None = None,
        knowledge_bucket: str | None = None,
        namespaces: Iterable[str] | None = None,
        query_expansion: Iterable[str] | None = None,
        source_types: Iterable[str] | None = None,
        retrieval_policies: Iterable[str] | None = None,
        jurisdictions: Iterable[str] | None = None,
        strict_jurisdictions: bool = False,
    ) -> list[RetrievedDoc]:
        route_namespaces = set(namespaces or [])
        allowed_role_set = set(self._normalize_roles(allowed_roles))
        knowledge_domain_set = set(self._normalize_knowledge_domains(knowledge_domains))
        knowledge_bucket = knowledge_bucket or ""
        source_type_set = {str(value).strip().lower() for value in (source_types or []) if str(value).strip()}
        retrieval_policy_set = {
            str(value).strip().lower() for value in (retrieval_policies or []) if str(value).strip()
        }
        jurisdiction_set = set(_normalize_string_values(jurisdictions))
        expanded_query = " ".join([query, " ".join(query_expansion or [])]).strip()
        query_tokens = tokenize(expanded_query)
        if not query_tokens:
            self._record_search_stats(
                query_token_count=0,
                eligible_doc_count=0,
                scoring_term_count=0,
                deferred_low_signal_term_count=0,
                deferred_high_fanout_term_count=0,
                scoring_strategy="empty_query",
                scored_candidate_count=0,
                result_count=0,
            )
            return []
        self._ensure_runtime_caches()
        query_token_set = set(query_tokens)
        eligible_indices = self._eligible_indices_for_filters(
            allowed_role_set=allowed_role_set,
            knowledge_domain_set=knowledge_domain_set,
            knowledge_bucket=knowledge_bucket,
            source_type_set=source_type_set,
            route_namespace_set=route_namespaces,
            retrieval_policy_set=retrieval_policy_set,
            jurisdiction_set=jurisdiction_set,
            strict_jurisdictions=strict_jurisdictions,
        )
        eligible_indices = self._query_focus_namespace_eligible_indices(
            eligible_indices,
            route_namespaces=route_namespaces,
            query_token_set=query_token_set,
        )
        eligible_indices = self._regional_mlra_eligible_indices(
            eligible_indices,
            route_namespaces=route_namespaces,
            query_token_set=query_token_set,
        )
        query_nutrients = query_token_set & NUTRIENT_TOKENS
        query_language = _detect_query_language(query)
        score_normalizer = 1.0 / max(1.0, len(query_tokens))
        candidate_scores: dict[int, float] = {}
        eligible_contains = eligible_indices.__contains__
        inverted_index = self.inverted_index
        doc_counts = self.doc_counts
        doc_lengths = self.doc_lengths
        bm25_length_norms = self.bm25_length_norms
        high_fanout_limit = max(HIGH_FANOUT_SCORING_MIN_POSTINGS, int(len(eligible_indices) * HIGH_FANOUT_SCORING_RATIO))
        if len(eligible_indices) <= DIRECT_SCORING_ALWAYS_ELIGIBLE_DOCS:
            scoring_terms = tuple(
                (token, query_count, self.idf[token], len(inverted_index.get(token, ())))
                for token, query_count in Counter(query_tokens).items()
                if token in self.idf
            )
            deferred_low_signal_terms = ()
            deferred_high_fanout_terms = ()
        else:
            scoring_terms, deferred_low_signal_terms, deferred_high_fanout_terms = self._query_scoring_plan(
                tuple(query_tokens),
                high_fanout_limit=high_fanout_limit,
            )
        scoring_strategy = "none"
        if _should_score_eligible_docs_directly(eligible_indices, scoring_terms):
            scoring_strategy = "direct"
            _score_eligible_docs(
                candidate_scores,
                eligible_indices=eligible_indices,
                doc_counts=doc_counts,
                doc_lengths=doc_lengths,
                bm25_length_norms=bm25_length_norms,
                scoring_terms=scoring_terms,
            )
        else:
            scoring_strategy = "postings" if scoring_terms else "none"
            for token, query_count, idf, _posting_count in scoring_terms:
                _score_token_postings(
                    candidate_scores,
                    postings=inverted_index.get(token, ()),
                    eligible_contains=eligible_contains,
                    doc_lengths=doc_lengths,
                    bm25_length_norms=bm25_length_norms,
                    query_count=query_count,
                    idf=idf,
                )
        deferred_fallback_terms = [*deferred_high_fanout_terms, *deferred_low_signal_terms]
        if not candidate_scores and deferred_fallback_terms:
            fallback_terms = [
                (token, query_count, idf, len(inverted_index.get(token, ())))
                for token, query_count, idf in deferred_fallback_terms
            ]
            if _should_score_eligible_docs_directly(eligible_indices, fallback_terms):
                scoring_strategy = "fallback_direct"
                _score_eligible_docs(
                    candidate_scores,
                    eligible_indices=eligible_indices,
                    doc_counts=doc_counts,
                    doc_lengths=doc_lengths,
                    bm25_length_norms=bm25_length_norms,
                    scoring_terms=fallback_terms,
                )
            else:
                scoring_strategy = "fallback_postings"
                for token, query_count, idf, _posting_count in fallback_terms:
                    _score_token_postings(
                        candidate_scores,
                        postings=inverted_index.get(token, ()),
                        eligible_contains=eligible_contains,
                        doc_lengths=doc_lengths,
                        bm25_length_norms=bm25_length_norms,
                        query_count=query_count,
                        idf=idf,
                    )
        scored: list[tuple[float, int]] = []
        doc_token_sets = self.doc_token_sets
        doc_namespace_sets = self.doc_namespace_sets
        doc_source_types = self.doc_source_types
        doc_languages = self.doc_languages
        applied_route = bool(
            route_namespaces
            & {"crop_management", "fertility", "plant_health", "product_stewardship", "soil_water"}
        )
        route_label_boundary = bool(route_namespaces & {"label_boundary", "field_data_boundary"})
        sulfur_context_absent = not ({"dioxide", "acid"} & query_token_set)
        for idx, score in candidate_scores.items():
            doc_token_set = doc_token_sets[idx]
            if query_nutrients and not any(token in doc_token_set for token in query_nutrients):
                score *= 0.72
            if "sulfur" in query_nutrients and sulfur_context_absent and any(token in doc_token_set for token in ("dioxide", "acid")):
                score *= 0.25
            doc_namespace_set = doc_namespace_sets[idx]
            if route_namespaces:
                overlap = len(route_namespaces & doc_namespace_set)
                if overlap:
                    score *= 1.0 + min(0.45, 0.18 * overlap)
                else:
                    score *= 0.82
            source_type = doc_source_types[idx]
            if source_type == "ontology" and applied_route and not route_namespaces <= {"soil_health", "exam_review"}:
                score *= 0.55
            elif source_type == "applied_guidance" and applied_route:
                score *= 1.12
            elif source_type == "boundary" and route_label_boundary:
                score *= 1.12
            if query_language:
                language_prefixes = {
                    language.split("-", 1)[0]
                    for language in doc_languages[idx]
                    if language
                }
                if query_language in language_prefixes:
                    score *= 1.35
                elif language_prefixes:
                    score *= 0.78
            normalized = score * score_normalizer
            if normalized >= min_score:
                scored.append((normalized, idx))
        results: list[RetrievedDoc] = []
        for score, idx in nlargest(top_k, scored):
            doc = self.docs[idx]
            license_snapshot = doc.get("license_snapshot") if isinstance(doc.get("license_snapshot"), dict) else {}
            lineage = doc.get("lineage") if isinstance(doc.get("lineage"), dict) else {}
            currency = doc.get("currency") if isinstance(doc.get("currency"), dict) else {}
            results.append(
                RetrievedDoc(
                    doc_id=str(doc.get("doc_id", f"doc_{idx}")),
                    title=str(doc.get("title", "")),
                    text=str(doc.get("text", "")),
                    source=str(doc.get("source", "seed")),
                    score=round(score, 4),
                    tags=tuple(str(tag) for tag in doc.get("tags", [])),
                    namespaces=self.doc_namespaces[idx],
                    source_type=self.doc_source_types[idx],
                    allowed_roles=self.doc_allowed_roles[idx],
                    crops=tuple(_preserve_string_values(doc.get("crops"))),
                    knowledge_domains=self.doc_knowledge_domains[idx],
                    knowledge_bucket=self.doc_knowledge_buckets[idx],
                    token_set=self.doc_token_sets[idx],
                    source_id=str(doc.get("source_id") or doc.get("source") or ""),
                    jurisdictions=tuple(_preserve_string_values(doc.get("jurisdiction") or doc.get("region"))),
                    languages=tuple(_preserve_string_values(doc.get("language"))),
                    currency_status=str(currency.get("status") or "unspecified"),
                    retrieval_policy=str(doc.get("retrieval_policy") or "standard").strip().lower(),
                    content_risk_tags=tuple(_normalize_string_values(doc.get("content_risk_tags"))),
                    license_status=str(license_snapshot.get("status") or doc.get("license") or "unknown"),
                    license_identifier=str(license_snapshot.get("identifier") or ""),
                    license_evidence_url=str(license_snapshot.get("evidence_url") or ""),
                    license_attribution=str(license_snapshot.get("attribution") or ""),
                    raw_sha256=str(lineage.get("raw_sha256") or ""),
                    chunk_sha256=str(lineage.get("chunk_sha256") or ""),
                    manifest_sha256=str(lineage.get("manifest_sha256") or ""),
                    corpus_path=str(doc.get("_corpus_path") or ""),
                    distribution_scope=str(doc.get("distribution_scope") or ""),
                    answer_role=str(doc.get("answer_role") or ""),
                )
            )
        self._record_search_stats(
            query_token_count=len(query_tokens),
            eligible_doc_count=len(eligible_indices),
            scoring_term_count=len(scoring_terms),
            deferred_low_signal_term_count=len(deferred_low_signal_terms),
            deferred_high_fanout_term_count=len(deferred_high_fanout_terms),
            scoring_strategy=scoring_strategy,
            scored_candidate_count=len(scored),
            result_count=len(results),
        )
        return results

    def _query_scoring_plan(
        self,
        query_token_tuple: tuple[str, ...],
        *,
        high_fanout_limit: int,
    ) -> tuple[
        tuple[tuple[str, int, float, int], ...],
        tuple[tuple[str, int, float], ...],
        tuple[tuple[str, int, float], ...],
    ]:
        self._ensure_runtime_caches()
        key = (query_token_tuple, high_fanout_limit)
        cached = self._query_scoring_plan_cache.get(key)
        if cached is not None:
            self._query_scoring_plan_cache.move_to_end(key)
            return cached
        plan = self._build_query_scoring_plan(query_token_tuple, high_fanout_limit=high_fanout_limit)
        if len(self._query_scoring_plan_cache) >= QUERY_SCORING_PLAN_CACHE_MAX_ENTRIES:
            self._query_scoring_plan_cache.popitem(last=False)
        self._query_scoring_plan_cache[key] = plan
        return plan

    def _ensure_runtime_caches(self) -> None:
        if not hasattr(self, "_static_filter_cache"):
            self._static_filter_cache = OrderedDict()
        elif not isinstance(self._static_filter_cache, OrderedDict):
            self._static_filter_cache = OrderedDict(self._static_filter_cache)
        if not hasattr(self, "_query_scoring_plan_cache"):
            self._query_scoring_plan_cache = OrderedDict()
        elif not isinstance(self._query_scoring_plan_cache, OrderedDict):
            self._query_scoring_plan_cache = OrderedDict(self._query_scoring_plan_cache)
        if not hasattr(self, "_query_focus_eligible_cache"):
            self._query_focus_eligible_cache = OrderedDict()
        elif not isinstance(self._query_focus_eligible_cache, OrderedDict):
            self._query_focus_eligible_cache = OrderedDict(self._query_focus_eligible_cache)
        if not hasattr(self, "_regional_mlra_eligible_cache"):
            self._regional_mlra_eligible_cache = OrderedDict()
        elif not isinstance(self._regional_mlra_eligible_cache, OrderedDict):
            self._regional_mlra_eligible_cache = OrderedDict(self._regional_mlra_eligible_cache)

    def _build_query_scoring_plan(
        self,
        query_token_tuple: tuple[str, ...],
        *,
        high_fanout_limit: int,
    ) -> tuple[
        tuple[tuple[str, int, float, int], ...],
        tuple[tuple[str, int, float], ...],
        tuple[tuple[str, int, float], ...],
    ]:
        scoring_terms: list[tuple[str, int, float, int]] = []
        deferred_low_signal_terms: list[tuple[str, int, float]] = []
        deferred_high_fanout_terms: list[tuple[str, int, float]] = []
        for token, query_count in Counter(query_token_tuple).items():
            idf = self.idf.get(token, 0.0)
            if idf <= 0:
                continue
            postings = self.inverted_index.get(token, ())
            if idf < LOW_SIGNAL_SCORING_IDF:
                deferred_low_signal_terms.append((token, query_count, idf))
                continue
            if len(postings) > high_fanout_limit:
                deferred_high_fanout_terms.append((token, query_count, idf))
                continue
            scoring_terms.append((token, query_count, idf, len(postings)))
        return (
            tuple(scoring_terms),
            tuple(deferred_low_signal_terms),
            tuple(deferred_high_fanout_terms),
        )

    def _record_search_stats(
        self,
        *,
        query_token_count: int,
        eligible_doc_count: int,
        scoring_term_count: int,
        deferred_low_signal_term_count: int,
        deferred_high_fanout_term_count: int,
        scoring_strategy: str,
        scored_candidate_count: int,
        result_count: int,
    ) -> None:
        self.last_search_stats = SearchStats(
            query_token_count=query_token_count,
            eligible_doc_count=eligible_doc_count,
            scoring_term_count=scoring_term_count,
            deferred_low_signal_term_count=deferred_low_signal_term_count,
            deferred_high_fanout_term_count=deferred_high_fanout_term_count,
            scoring_strategy=scoring_strategy,
            scored_candidate_count=scored_candidate_count,
            result_count=result_count,
        )

    def _eligible_indices_for_filters(
        self,
        *,
        allowed_role_set: set[str],
        knowledge_domain_set: set[str],
        knowledge_bucket: str,
        source_type_set: set[str],
        route_namespace_set: set[str],
        retrieval_policy_set: set[str],
        jurisdiction_set: set[str],
        strict_jurisdictions: bool,
    ) -> frozenset[int]:
        key = (
            tuple(sorted(allowed_role_set)),
            tuple(sorted(knowledge_domain_set)),
            knowledge_bucket,
            tuple(sorted(source_type_set)),
            tuple(sorted(route_namespace_set)),
            tuple(sorted(retrieval_policy_set)),
            tuple(sorted(jurisdiction_set)),
            strict_jurisdictions,
        )
        cached = self._static_filter_cache.get(key)
        if cached is not None:
            self._static_filter_cache.move_to_end(key)
            return cached
        eligible = self._all_doc_indices
        if source_type_set:
            eligible &= _union_index_values(self._source_type_index, source_type_set)
        if retrieval_policy_set:
            eligible &= _union_index_values(self._retrieval_policy_index, retrieval_policy_set)
        if jurisdiction_set:
            jurisdiction_matches = _union_index_values(self._jurisdiction_index, jurisdiction_set)
            eligible &= jurisdiction_matches if strict_jurisdictions else self._empty_jurisdiction_indices | jurisdiction_matches
        if allowed_role_set:
            eligible &= self._empty_allowed_role_indices | _union_index_values(self._allowed_role_index, allowed_role_set)
        if knowledge_domain_set:
            eligible &= self._empty_knowledge_domain_indices | _union_index_values(self._knowledge_domain_index, knowledge_domain_set)
        if knowledge_bucket:
            eligible &= self._empty_knowledge_bucket_indices | self._knowledge_bucket_index.get(knowledge_bucket, frozenset())
        if route_namespace_set and len(eligible) >= NAMESPACE_PREFILTER_MIN_ELIGIBLE_DOCS:
            namespace_matches = _union_index_values(self._namespace_index, route_namespace_set)
            narrowed = eligible & namespace_matches
            if len(narrowed) >= NAMESPACE_PREFILTER_MIN_MATCHES:
                eligible = narrowed
        if len(self._static_filter_cache) >= STATIC_FILTER_CACHE_MAX_ENTRIES:
            self._static_filter_cache.popitem(last=False)
        self._static_filter_cache[key] = eligible
        return eligible

    def runtime_cache_stats(self) -> dict[str, dict[str, int | bool]]:
        self._ensure_runtime_caches()
        return {
            "static_filter": _cache_budget_record(
                len(self._static_filter_cache),
                STATIC_FILTER_CACHE_MAX_ENTRIES,
            ),
            "query_scoring_plan": _cache_budget_record(
                len(self._query_scoring_plan_cache),
                QUERY_SCORING_PLAN_CACHE_MAX_ENTRIES,
            ),
            "query_focus_eligible": _cache_budget_record(
                len(self._query_focus_eligible_cache),
                QUERY_FOCUS_ELIGIBLE_CACHE_MAX_ENTRIES,
            ),
            "regional_mlra_eligible": _cache_budget_record(
                len(self._regional_mlra_eligible_cache),
                REGIONAL_MLRA_ELIGIBLE_CACHE_MAX_ENTRIES,
            ),
        }

    def _query_focus_namespace_eligible_indices(
        self,
        eligible_indices: frozenset[int],
        *,
        route_namespaces: set[str],
        query_token_set: set[str],
    ) -> frozenset[int]:
        if len(eligible_indices) < NAMESPACE_PREFILTER_MIN_ELIGIBLE_DOCS or len(route_namespaces) <= 1:
            return eligible_indices
        key = (
            eligible_indices,
            tuple(sorted(route_namespaces)),
            tuple(sorted(query_token_set)),
        )
        cached = self._query_focus_eligible_cache.get(key)
        if cached is not None:
            self._query_focus_eligible_cache.move_to_end(key)
            return cached
        query_namespaces = set(_infer_namespaces_from_token_set({}, "", query_token_set))
        focus_namespaces = (query_namespaces & route_namespaces) - {"general"}
        focus_namespaces = _prioritized_query_focus_namespaces(focus_namespaces, query_token_set)
        if not focus_namespaces or focus_namespaces == route_namespaces:
            self._put_query_focus_eligible_cache(key, eligible_indices)
            return eligible_indices
        narrowed = eligible_indices & _union_index_values(self._namespace_index, focus_namespaces)
        if len(narrowed) >= QUERY_FOCUS_NAMESPACE_PREFILTER_MIN_MATCHES:
            self._put_query_focus_eligible_cache(key, narrowed)
            return narrowed
        self._put_query_focus_eligible_cache(key, eligible_indices)
        return eligible_indices

    def _regional_mlra_eligible_indices(
        self,
        eligible_indices: frozenset[int],
        *,
        route_namespaces: set[str],
        query_token_set: set[str],
    ) -> frozenset[int]:
        if "regional_environment" not in route_namespaces:
            return eligible_indices
        mlra_tokens = {token for token in query_token_set if _looks_like_mlra_token(token)}
        if not mlra_tokens:
            return eligible_indices
        key = (
            eligible_indices,
            tuple(sorted(route_namespaces)),
            tuple(sorted(mlra_tokens)),
        )
        cached = self._regional_mlra_eligible_cache.get(key)
        if cached is not None:
            self._regional_mlra_eligible_cache.move_to_end(key)
            return cached
        focused_indices: set[int] = set()
        for token in mlra_tokens:
            focused_indices.update(idx for idx, _count in self.inverted_index.get(token, ()))
        if not focused_indices:
            self._put_regional_mlra_eligible_cache(key, eligible_indices)
            return eligible_indices
        narrowed = eligible_indices & frozenset(focused_indices)
        result = narrowed or eligible_indices
        self._put_regional_mlra_eligible_cache(key, result)
        return result

    def _put_query_focus_eligible_cache(
        self,
        key: tuple[frozenset[int], tuple[str, ...], tuple[str, ...]],
        value: frozenset[int],
    ) -> None:
        if len(self._query_focus_eligible_cache) >= QUERY_FOCUS_ELIGIBLE_CACHE_MAX_ENTRIES:
            self._query_focus_eligible_cache.popitem(last=False)
        self._query_focus_eligible_cache[key] = value

    def _put_regional_mlra_eligible_cache(
        self,
        key: tuple[frozenset[int], tuple[str, ...], tuple[str, ...]],
        value: frozenset[int],
    ) -> None:
        if len(self._regional_mlra_eligible_cache) >= REGIONAL_MLRA_ELIGIBLE_CACHE_MAX_ENTRIES:
            self._regional_mlra_eligible_cache.popitem(last=False)
        self._regional_mlra_eligible_cache[key] = value

def infer_namespaces(doc: dict) -> list[str]:
    return _infer_namespaces_from_text(doc, _doc_search_text(doc))


def _prioritized_query_focus_namespaces(focus_namespaces: set[str], query_token_set: set[str]) -> set[str]:
    if "soil_health" in focus_namespaces and {"soil", "health"} <= query_token_set:
        return {"soil_health"}
    return focus_namespaces


def _infer_namespaces_from_text(doc: dict, text: str) -> list[str]:
    return _infer_namespaces_from_token_set(doc, text, set(tokenize(text)))


def _infer_namespaces_from_token_set(doc: dict, text: str, token_set: set[str]) -> list[str]:
    explicit = _normalize_string_values(doc.get("namespaces"))
    if explicit:
        return explicit
    namespaces: list[str] = []
    for name, token_hints, prefix_hints, phrase_token_hints in NAMESPACE_PHRASE_TOKEN_TABLE:
        if token_hints and token_hints & token_set:
            namespaces.append(name)
            continue
        if prefix_hints and any(token.startswith(prefix) for prefix in prefix_hints for token in token_set):
            namespaces.append(name)
            continue
        if phrase_token_hints and any(phrase_tokens <= token_set for phrase_tokens in phrase_token_hints):
            namespaces.append(name)
    return namespaces or ["general"]


def infer_source_type(doc: dict) -> str:
    explicit = str(doc.get("source_type", "")).strip().lower()
    if explicit:
        if explicit in {"diagnostic_guidance", "measurement_guidance", "extension_document"}:
            return "applied_guidance"
        return explicit
    text = " ".join(
        [
            str(doc.get("doc_id", "")),
            str(doc.get("title", "")),
            str(doc.get("source", "")),
            " ".join(str(tag) for tag in doc.get("tags", [])),
        ]
    ).lower()
    if "soilwise" in text or "knowledge graph" in text or "ontology" in text:
        return "ontology"
    if BOUNDARY_SOURCE_RE.search(text):
        return "boundary"
    if EXAM_SOURCE_RE.search(text):
        return "exam"
    return "applied_guidance"


def _single_value_index(values: Iterable[str]) -> dict[str, frozenset[int]]:
    buckets: dict[str, set[int]] = defaultdict(set)
    for idx, value in enumerate(values):
        text = str(value).strip().lower()
        if text:
            buckets[text].add(idx)
    return {value: frozenset(indices) for value, indices in buckets.items()}


def _single_value_index_with_empty(values: Iterable[str]) -> tuple[dict[str, frozenset[int]], frozenset[int]]:
    buckets: dict[str, set[int]] = defaultdict(set)
    empty: set[int] = set()
    for idx, value in enumerate(values):
        text = str(value).strip().lower()
        if text:
            buckets[text].add(idx)
        else:
            empty.add(idx)
    return {value: frozenset(indices) for value, indices in buckets.items()}, frozenset(empty)


def _multi_value_index(values: Iterable[Iterable[str]]) -> tuple[dict[str, frozenset[int]], frozenset[int]]:
    buckets: dict[str, set[int]] = defaultdict(set)
    empty: set[int] = set()
    for idx, row in enumerate(values):
        normalized = [str(value).strip().lower() for value in row if str(value).strip()]
        if not normalized:
            empty.add(idx)
            continue
        for value in normalized:
            buckets[value].add(idx)
    return {value: frozenset(indices) for value, indices in buckets.items()}, frozenset(empty)


def _cache_budget_record(entries: int, max_entries: int) -> dict[str, int | bool]:
    return {
        "entries": entries,
        "max_entries": max_entries,
        "within_budget": entries <= max_entries,
    }


def _union_index_values(index: dict[str, frozenset[int]], values: Iterable[str]) -> frozenset[int]:
    selected: set[int] = set()
    for value in values:
        selected.update(index.get(str(value).strip().lower(), ()))
    return frozenset(selected)


def _looks_like_mlra_token(token: str) -> bool:
    return len(token) == 4 and token[:3].isdigit() and token[3].isalpha()


def _score_token_postings(
    candidate_scores: dict[int, float],
    *,
    postings: Iterable[tuple[int, int]],
    eligible_contains: Any,
    doc_lengths: list[int],
    bm25_length_norms: list[float],
    query_count: int,
    idf: float,
) -> None:
    for idx, tf in postings:
        if eligible_contains(idx):
            if not doc_lengths[idx]:
                continue
            denom = tf + bm25_length_norms[idx]
            candidate_scores[idx] = (
                candidate_scores.get(idx, 0.0)
                + idf * ((tf * 2.2) / denom) * query_count
            )


def _should_score_eligible_docs_directly(
    eligible_indices: frozenset[int],
    scoring_terms: list[tuple[str, int, float, int]],
) -> bool:
    if not scoring_terms or len(eligible_indices) > DIRECT_SCORING_MAX_ELIGIBLE_DOCS:
        return False
    if len(eligible_indices) <= DIRECT_SCORING_ALWAYS_ELIGIBLE_DOCS:
        return True
    direct_cost = len(eligible_indices) * len(scoring_terms)
    postings_cost = sum(posting_count for _token, _query_count, _idf, posting_count in scoring_terms)
    return direct_cost < postings_cost * DIRECT_SCORING_COST_RATIO


def _score_eligible_docs(
    candidate_scores: dict[int, float],
    *,
    eligible_indices: frozenset[int],
    doc_counts: list[dict[str, int]],
    doc_lengths: list[int],
    bm25_length_norms: list[float],
    scoring_terms: list[tuple[str, int, float, int]],
) -> None:
    for idx in eligible_indices:
        if not doc_lengths[idx]:
            continue
        counts = doc_counts[idx]
        norm = bm25_length_norms[idx]
        score = 0.0
        for token, query_count, idf, _posting_count in scoring_terms:
            tf = counts.get(token, 0)
            if tf:
                score += idf * ((tf * 2.2) / (tf + norm)) * query_count
        if score:
            candidate_scores[idx] = candidate_scores.get(idx, 0.0) + score


def _doc_search_text(doc: dict) -> str:
    return " ".join(
        [
            str(doc.get("doc_id", "")),
            str(doc.get("title", "")),
            str(doc.get("text", "")),
            " ".join(str(tag) for tag in doc.get("tags", [])),
        ]
    )


def _normalize_string_values(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _preserve_string_values(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return [str(value).strip() for value in values if str(value).strip()]
