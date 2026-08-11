from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib import metadata as importlib_metadata
from typing import Any, Iterable

from agronomy_agent.agno_runtime.local_index import LexicalRetriever, RetrievedDoc, tokenize


def _detect_agno_version() -> str:
    try:
        return importlib_metadata.version("agno")
    except importlib_metadata.PackageNotFoundError:
        return "not_installed"


AGNO_VERSION = _detect_agno_version()


@lru_cache(maxsize=1)
def agno_sdk_available() -> bool:
    return importlib.util.find_spec("agno") is not None


@dataclass(frozen=True)
class AgnoKnowledgeConfig:
    knowledge_base: str = "agronomy_public"
    contents_table: str = "agno_knowledge_contents"
    vector_table: str = "agno_knowledge_vectors"
    search_type: str = "hybrid"
    embedder_profile: str = "local_default"
    top_k: int = 8
    final_context_k: int = 5
    reranker: str | None = None
    enable_agentic_search: bool = False
    max_agentic_subqueries: int = 2
    agentic_candidate_multiplier: int = 2
    min_agentic_candidates: int = 16
    use_custom_retriever: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "AgnoKnowledgeConfig":
        agno = (config or {}).get("agno") or {}
        knowledge = agno.get("knowledge") or {}
        retrieval = agno.get("retrieval") or {}
        search_type = str(knowledge.get("search_type", "hybrid")).strip().lower()
        if search_type not in {"keyword", "vector", "hybrid"}:
            raise ValueError("agno.knowledge.search_type must be keyword, vector, or hybrid")
        top_k = int(retrieval.get("top_k", 8))
        final_context_k = int(retrieval.get("final_context_k", min(5, top_k)))
        if top_k <= 0 or final_context_k <= 0:
            raise ValueError("agno.retrieval top_k and final_context_k must be positive")
        max_agentic_subqueries = int(retrieval.get("max_agentic_subqueries", 2))
        if max_agentic_subqueries <= 0:
            raise ValueError("agno.retrieval.max_agentic_subqueries must be positive")
        agentic_candidate_multiplier = int(retrieval.get("agentic_candidate_multiplier", 2))
        min_agentic_candidates = int(retrieval.get("min_agentic_candidates", 16))
        if agentic_candidate_multiplier <= 0 or min_agentic_candidates <= 0:
            raise ValueError("agno.retrieval agentic candidate settings must be positive")
        return cls(
            knowledge_base=str(knowledge.get("default_base", "agronomy_public")),
            contents_table=str(knowledge.get("contents_table", "agno_knowledge_contents")),
            vector_table=str(knowledge.get("vector_table", "agno_knowledge_vectors")),
            search_type=search_type,
            embedder_profile=str(knowledge.get("embedder_profile", "local_default")),
            top_k=top_k,
            final_context_k=final_context_k,
            reranker=knowledge.get("reranker"),
            enable_agentic_search=bool(retrieval.get("enable_agentic_search", False)),
            max_agentic_subqueries=max_agentic_subqueries,
            agentic_candidate_multiplier=agentic_candidate_multiplier,
            min_agentic_candidates=min_agentic_candidates,
            use_custom_retriever=bool(retrieval.get("use_custom_retriever", True)),
            metadata=dict(knowledge.get("metadata") or {}),
        )


@dataclass(frozen=True)
class KnowledgeSearchResult:
    docs: tuple[RetrievedDoc, ...]
    latency_ms: float
    filters: dict[str, Any]
    knowledge: dict[str, Any]


class LocalAgnoKnowledge:
    """Dependency-free Agno Knowledge stand-in for CI and rollback evidence.

    It deliberately uses the existing lexical engine under an Agno-shaped
    interface so default installs do not silently require network downloads or a
    live PgVector service.
    """

    def __init__(self, docs: Iterable[dict[str, Any]] | LexicalRetriever, config: AgnoKnowledgeConfig) -> None:
        self.config = config
        self.retriever = docs if isinstance(docs, LexicalRetriever) else LexicalRetriever(docs)

    def search(self, query: str, *, filters: dict[str, Any] | None = None, top_k: int | None = None) -> KnowledgeSearchResult:
        filters = dict(filters or {})
        start = time.perf_counter()
        resolved_top_k = top_k or self.config.top_k
        agentic_search_enabled = _should_use_agentic_search(query, filters, config=self.config)
        agentic_pruned_after_primary = False
        if agentic_search_enabled:
            docs, subquery_count, candidate_k, agentic_pruned_after_primary, index_stats = self._agentic_search(
                query,
                filters=filters,
                top_k=resolved_top_k,
            )
        else:
            subquery_count = 1
            candidate_k = max(resolved_top_k, self.config.min_agentic_candidates) if self.config.reranker else resolved_top_k
            docs = self.retriever.search(
                query,
                top_k=candidate_k,
                allowed_roles=_list_filter(filters.get("audience")),
                knowledge_domains=_list_filter(filters.get("knowledge_domains")),
                knowledge_bucket=_str_filter(filters.get("knowledge_bucket")),
                namespaces=_list_filter(filters.get("namespaces")),
                query_expansion=_list_filter(filters.get("query_expansion")),
                source_types=_list_filter(filters.get("source_type")),
                retrieval_policies=_list_filter(filters.get("retrieval_policy")),
            )
            index_stats = [_search_stats_record(self.retriever)]
        docs = _apply_metadata_filters(docs, filters)
        if not agentic_pruned_after_primary and (agentic_search_enabled or self.config.reranker):
            docs = _rerank_and_select_for_coverage(docs, query=query, filters=filters, top_k=resolved_top_k)
        return KnowledgeSearchResult(
            docs=tuple(docs),
            latency_ms=round((time.perf_counter() - start) * 1000, 3),
            filters=filters,
            knowledge={
                "mode": "agentic_search_tool" if agentic_search_enabled else "custom_retriever",
                "knowledge_base": self.config.knowledge_base,
                "contents_table": self.config.contents_table,
                "vector_table": self.config.vector_table,
                "search_type": self.config.search_type,
                "filters": filters,
                "reranker": self.config.reranker,
                "top_k": resolved_top_k,
                "agentic_search_configured": self.config.enable_agentic_search,
                "agentic_search_enabled": agentic_search_enabled,
                "agentic_pruned_after_primary": agentic_pruned_after_primary,
                "agentic_subquery_count": subquery_count,
                "agentic_subquery_limit": self.config.max_agentic_subqueries,
                "agentic_candidate_k": candidate_k,
                "agentic_candidate_multiplier": self.config.agentic_candidate_multiplier,
                "min_agentic_candidates": self.config.min_agentic_candidates,
                "index_search_count": len(index_stats),
                "index_scoring_strategies": sorted(
                    {
                        str(stats.get("scoring_strategy") or "")
                        for stats in index_stats
                        if str(stats.get("scoring_strategy") or "").strip()
                    }
                ),
                "index_total_eligible_docs": sum(int(stats.get("eligible_doc_count") or 0) for stats in index_stats),
                "index_max_eligible_docs": max((int(stats.get("eligible_doc_count") or 0) for stats in index_stats), default=0),
                "index_total_scored_candidates": sum(int(stats.get("scored_candidate_count") or 0) for stats in index_stats),
                "index_max_scored_candidates": max((int(stats.get("scored_candidate_count") or 0) for stats in index_stats), default=0),
                "index_deferred_low_signal_term_count": sum(int(stats.get("deferred_low_signal_term_count") or 0) for stats in index_stats),
                "index_deferred_high_fanout_term_count": sum(int(stats.get("deferred_high_fanout_term_count") or 0) for stats in index_stats),
                "index_runtime_cache_stats": self.retriever.runtime_cache_stats(),
                "index_search_stats": index_stats,
                "embedder_profile": self.config.embedder_profile,
                "agno_sdk_available": agno_sdk_available(),
                "agno_version": None if AGNO_VERSION == "not_installed" else AGNO_VERSION,
            },
        )

    def _agentic_search(self, query: str, *, filters: dict[str, Any], top_k: int) -> tuple[list[RetrievedDoc], int, int, bool, list[dict[str, Any]]]:
        candidate_k = max(top_k * self.config.agentic_candidate_multiplier, self.config.min_agentic_candidates)
        common = {
            "allowed_roles": _list_filter(filters.get("audience")),
            "knowledge_domains": _list_filter(filters.get("knowledge_domains")),
            "knowledge_bucket": _str_filter(filters.get("knowledge_bucket")),
            "namespaces": _list_filter(filters.get("namespaces")),
            "source_types": _list_filter(filters.get("source_type")),
            "retrieval_policies": _list_filter(filters.get("retrieval_policy")),
            "min_score": 0.0,
        }
        merged: dict[str, RetrievedDoc] = {}
        subqueries = _agentic_subqueries(query, filters, max_subqueries=self.config.max_agentic_subqueries)
        executed_subqueries = 0
        index_stats: list[dict[str, Any]] = []
        route_namespaces = set(common["namespaces"])
        for subquery_index, (subquery, expansion) in enumerate(subqueries):
            executed_subqueries += 1
            subquery_docs = self.retriever.search(subquery, top_k=candidate_k, query_expansion=expansion, **common)
            index_stats.append(_search_stats_record(self.retriever))
            for doc in subquery_docs:
                existing = merged.get(doc.doc_id)
                if existing is None or doc.score > existing.score:
                    merged[doc.doc_id] = doc
            primary_selection = _primary_agentic_selection_if_sufficient(
                query,
                filters=filters,
                docs=list(merged.values()),
                top_k=top_k,
            )
            if subquery_index == 0 and "regional_environment" not in route_namespaces and primary_selection is not None:
                return primary_selection, executed_subqueries, candidate_k, True, index_stats
        return list(merged.values()), executed_subqueries, candidate_k, False, index_stats


def build_knowledge(config: dict[str, Any] | None, docs: Iterable[dict[str, Any]] | LexicalRetriever) -> LocalAgnoKnowledge:
    return LocalAgnoKnowledge(docs, AgnoKnowledgeConfig.from_config(config))


def _search_stats_record(retriever: LexicalRetriever) -> dict[str, Any]:
    stats = getattr(retriever, "last_search_stats", None)
    if stats is None:
        return {}
    if hasattr(stats, "as_record"):
        return stats.as_record()
    if isinstance(stats, dict):
        return dict(stats)
    return {}


def _apply_metadata_filters(docs: list[RetrievedDoc], filters: dict[str, Any]) -> list[RetrievedDoc]:
    source_types = set(_list_filter(filters.get("source_type")))
    if source_types:
        docs = [doc for doc in docs if doc.source_type in source_types]
    license_status = str(filters.get("license_status") or "").strip().lower()
    if license_status and license_status not in {"approved", "review_required"}:
        return []
    visibility = str(filters.get("source_visibility") or filters.get("access_level") or "").strip().lower()
    if visibility == "private":
        workspace_id = str(filters.get("workspace_id") or "").strip()
        docs = [doc for doc in docs if workspace_id and workspace_id in doc.tags]
    return docs


def _should_use_agentic_search(query: str, filters: dict[str, Any], *, config: AgnoKnowledgeConfig) -> bool:
    if not config.enable_agentic_search:
        return False
    namespaces = set(_list_filter(filters.get("namespaces")))
    focus_tokens = set(tokenize(" ".join([query, " ".join(_list_filter(filters.get("query_expansion")))])))
    if filters.get("risk_level") == "regulated":
        return True
    if namespaces & {"label_boundary", "product_stewardship", "field_data_boundary"}:
        return True
    if {"salinity", "sodicity", "sodium", "sar", "esp"} & focus_tokens:
        return True
    if "fertility" in namespaces and {"nitrogen", "nitrate"} & focus_tokens:
        return False
    if {"runoff", "leaching", "drainage", "ditch", "water", "table"} & focus_tokens and namespaces & {"soil_water", "soil_health"}:
        return True
    return False


def _agentic_subqueries(query: str, filters: dict[str, Any], *, max_subqueries: int | None = None) -> list[tuple[str, list[str]]]:
    namespaces = set(_list_filter(filters.get("namespaces")))
    expansions = _list_filter(filters.get("query_expansion"))
    focus_tokens = set(tokenize(" ".join([query, " ".join(expansions)])))
    subqueries: list[tuple[str, list[str]]] = []
    seed_treatment_focus = _seed_treatment_focus(focus_tokens)
    aphid_focus = _aphid_focus(focus_tokens)
    fungicide_roi_focus = _fungicide_roi_focus(focus_tokens)
    ipm_threshold_focus = _ipm_threshold_focus(focus_tokens)
    nitrate_leaching_focus = _nitrate_leaching_focus(focus_tokens)
    cover_crop_water_focus = _cover_crop_water_focus(focus_tokens)
    precision_economics_focus = _precision_economics_focus(focus_tokens)
    erosion_control_focus = _erosion_control_focus(focus_tokens)
    conservation_plan_focus = _conservation_plan_focus(focus_tokens)
    soil_survey_prior_focus = _soil_survey_prior_focus(focus_tokens)
    crop_statistics_focus = _crop_statistics_focus(focus_tokens)
    cdl_history_focus = _cdl_history_focus(focus_tokens)
    forage_livestock_focus = _forage_livestock_focus(focus_tokens)
    horticulture_specialty_focus = _horticulture_specialty_focus(focus_tokens)
    source_availability_focus = _source_availability_focus(focus_tokens)
    postharvest_storage_focus = _postharvest_storage_focus(focus_tokens)
    white_mold_focus = _white_mold_focus(focus_tokens)
    has_mlra_focus = any(_looks_like_mlra_token(token) for token in focus_tokens)
    if "regional_environment" in namespaces and has_mlra_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append((_regional_environment_subquery(focus_tokens), []))
    elif source_availability_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("source card checked not checked unavailable not configured failed timeout cached cache timestamp missing point missing boundary geometry field location soil survey CDL weather label metadata public prior not field truth exact rate", []))
    elif seed_treatment_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("insecticide seed treatment early planting soil temperature cool wet soils pest history field history planting conditions pest pressure seedcorn maggot bean leaf beetle wireworm grub threshold risk label", []))
    elif aphid_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("aphid scouting count aphids per plant species crop stage economic threshold natural enemies beneficial insects insecticide label", []))
    elif ipm_threshold_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("IPM insect scouting count sampling pest species crop stage economic threshold beneficial natural enemies current label", []))
    elif fungicide_roi_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("fungicide ROI disease severity scouting hybrid variety susceptibility growth stage weather yield potential economics label price alone", []))
    elif namespaces & {"product_stewardship", "label_boundary"}:
        subqueries.append((_regulated_product_boundary_subquery(query, focus_tokens), []))
    elif forage_livestock_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("forage pasture nitrate prussic acid hydrocyanic acid drought frost stress regrowth forage test lab test feed test sorghum sudan millet grass legume grazing hay silage livestock safety withdrawal", []))
    elif soil_survey_prior_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("NRCS soil survey SDA map unit component drainage class hydrologic group hydric rating prior screening regional context soil test field observation ground truth not replacement", []))
    elif conservation_plan_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("runoff erosion residue cover crop waterway buffer setback grassed outlet slope soil texture drainage NRCS conservation plan local guidance", []))
    elif crop_statistics_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("USDA NASS Quick Stats regional statistics yield acreage production county state field records yield map grower records not field-specific prior", []))
    elif cdl_history_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("USDA NASS Cropland Data Layer CDL boundary sample sample points crop-cover class multi-year recent years rotation grower planting record field history prior not acreage not crop insurance not field truth", []))
    elif horticulture_specialty_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("specialty crop vegetable irrigation soil moisture disease risk humidity leaf wetness field scouting crop stage local extension label market quality", []))
    elif postharvest_storage_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("postharvest cooling cold chain field heat handling sanitation storage temperature humidity disease decay quality market quality mycotoxin sampling testing lot segregation drying aeration storage plan marketing risk", []))
    elif nitrate_leaching_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("nitrate leaching sandy soil heavy rain crop uptake split timing sidedress cover crop nitrification inhibitor stabilizer irrigation scheduling root zone credits", []))
    elif cover_crop_water_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("cover crop water use soil moisture stored water termination timing termination method species mix residue erosion planting window crop rotation rainfall irrigation", []))
    elif precision_economics_focus:
        nutrient_terms = [
            term
            for term in expansions
            if set(tokenize(term)) & {"phosphorus", "potassium"}
        ]
        primary_expansion = list(dict.fromkeys([*nutrient_terms, *expansions]))[:8]
        subqueries.append((query, primary_expansion))
        nutrient_probe = " phosphorus potassium" if {"phosphorus", "potassium"} & focus_tokens else ""
        subqueries.append((f"variable rate fertilizer{nutrient_probe} economic defensibility soil test zones yield response crop price fertilizer cost application cost partial budget ROI profit check strips on-farm trial audit trail", []))
    elif erosion_control_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("erosion control residue cover crop contour farming strip cropping terrace grassed waterway runoff slope tillage reduction no-till buffer stable outlet", []))
    elif white_mold_focus:
        subqueries.append((query, _short_terms(expansions, limit=8)))
        subqueries.append(("white mold soybean variety tolerance ratings canopy row spacing population field history rotation fungicide timing risk", []))
    subqueries.append((query, _short_terms(expansions, limit=8)))
    if "field_data_boundary" in namespaces:
        subqueries.append(("yield map as-applied records audit trail validated layers calibration check strip", []))
    if "regional_environment" in namespaces:
        subqueries.append((_regional_environment_subquery(focus_tokens), []))
    if expansions:
        subqueries.append((query, _short_terms(expansions, limit=6)))
    if {"salinity", "sodicity", "sodium", "sar", "esp"} & focus_tokens:
        subqueries.append(("salinity sodicity electrical conductivity SAR ESP sodium drainage leaching irrigation water", []))
    if forage_livestock_focus:
        subqueries.append(("forage nitrate prussic acid lab feed test grazing hay silage livestock safety", []))
    if crop_statistics_focus:
        subqueries.append(("NASS Quick Stats county state regional statistics field records yield maps not prediction", []))
    if cdl_history_focus:
        subqueries.append(("CDL crop-cover sample recent years grower planting record not acreage not field truth", []))
    if source_availability_focus:
        subqueries.append(("source status source card unavailable adapter failed not configured cached timestamp missing boundary geometry checked sources not field truth", []))
    if postharvest_storage_focus:
        subqueries.append(("postharvest cooling cold chain storage temperature humidity mycotoxin sampling lot segregation drying aeration quality market requirement", []))
    if namespaces & {"soil_water", "soil_health"}:
        subqueries.append(("runoff drainage leaching infiltration water table soil texture erosion", []))
    for chunk in _chunks(_short_terms(expansions, limit=12), size=4):
        if chunk:
            subqueries.append((" ".join(chunk), []))
    unique: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for subquery, expansion in subqueries:
        key = (subquery.lower(), tuple(expansion))
        if key not in seen:
            seen.add(key)
            unique.append((subquery, expansion))
    limit = max_subqueries or len(unique)
    return unique[: max(1, limit)]


def _regulated_product_boundary_subquery(query: str, focus_tokens: set[str]) -> str:
    if _seed_treatment_focus(focus_tokens):
        return "current product label crop target pest insecticide seed treatment threshold risk"
    terms = [
        "current",
        "product",
        "label",
        "wind",
        "drift",
        "buffer",
    ]
    if "herbicide" in focus_tokens or "spray" in focus_tokens or "spraying" in query.lower():
        terms.extend(["herbicide", "spray"])
    if {"runoff", "drainage", "ditch", "leaching", "water", "table", "infiltration"} & focus_tokens:
        terms.extend(["runoff", "drainage", "ditch", "water", "quality"])
    else:
        terms.extend(["jurisdiction", "crop", "site", "target", "pest", "application", "method"])
    return " ".join(dict.fromkeys(terms))


def _primary_agentic_selection_if_sufficient(
    query: str,
    *,
    filters: dict[str, Any],
    docs: list[RetrievedDoc],
    top_k: int,
) -> list[RetrievedDoc] | None:
    if not docs or top_k <= 0:
        return None
    token_cache = _build_doc_token_cache(docs)
    selected = _select_coverage_balanced(
        _rerank_for_coverage(docs, query=query, filters=filters, token_cache=token_cache),
        query=query,
        filters=filters,
        top_k=top_k,
        token_cache=token_cache,
    )
    covered = _covered_doc_tokens(selected, token_cache=token_cache)
    namespaces = set(_list_filter(filters.get("namespaces")))
    focus_tokens = set(tokenize(" ".join([query, " ".join(_list_filter(filters.get("query_expansion")))])))
    if _seed_treatment_focus(focus_tokens):
        if {"seed", "treatment"} <= covered and {"pest", "history", "temperature", "threshold", "label"} & covered:
            return selected
        return None
    if _aphid_focus(focus_tokens):
        if "aphid" in covered and {"count", "threshold", "stage", "beneficial", "enemies", "label"} & covered:
            return selected
        return None
    if _ipm_threshold_focus(focus_tokens):
        if {"scout", "threshold", "stage"} & covered and {"beneficial", "enemies", "natural", "label"} & covered:
            return selected
        return None
    if _fungicide_roi_focus(focus_tokens):
        if "fungicide" in covered and {"severity", "scouting", "susceptibility", "stage", "economics", "roi", "label"} & covered:
            return selected
        return None
    if filters.get("risk_level") == "regulated" or namespaces & {"label_boundary", "product_stewardship"}:
        if "label" in covered and {"wind", "drift", "buffer"} & covered:
            return selected
        return None
    if _forage_livestock_focus(focus_tokens):
        if (
            {"nitrate", "prussic"} & covered
            and {"drought", "frost", "stress", "regrowth"} & covered
            and {"forage", "feed", "lab", "test"} & covered
            and {"grazing", "hay", "silage", "livestock", "withdrawal"} & covered
        ):
            return selected
        return None
    if _soil_survey_prior_focus(focus_tokens):
        if (
            {"soil", "survey", "nrcs", "map", "unit", "component"} & covered
            and {"prior", "screening", "regional"} & covered
            and {"test", "observation", "ground", "truth", "replacement"} & covered
        ):
            return selected
        return None
    if _conservation_plan_focus(focus_tokens):
        if (
            {"runoff", "erosion"} & covered
            and {"residue", "cover"} & covered
            and {"waterway", "buffer", "setback", "grass"} & covered
            and {"nrcs", "conservation", "plan", "local", "guidance"} & covered
        ):
            return selected
        return None
    if _crop_statistics_focus(focus_tokens):
        if (
            {"nass", "quick", "stats"} & covered
            and {"yield", "acreage", "production"} & covered
            and {"field", "records", "map", "grower"} & covered
            and {"regional", "prior", "field-specific", "predict"} & covered
        ):
            return selected
        return None
    if _cdl_history_focus(focus_tokens):
        if (
            {"cdl", "cropland", "layer", "nass"} & covered
            and {"sample", "points", "crop-cover"} & covered
            and {"grower", "planting", "record", "history"} & covered
            and {"acreage", "insurance", "truth", "prior"} & covered
        ):
            return selected
        return None
    if _horticulture_specialty_focus(focus_tokens):
        if (
            {"irrigation", "moisture"} & covered
            and {"humidity", "wetness", "disease"} & covered
            and {"scouting", "stage"} & covered
            and {"extension", "label", "quality"} & covered
        ):
            return selected
        return None
    if _nitrate_leaching_focus(focus_tokens):
        if (
            "nitrate" in covered
            and {"leaching", "loss"} & covered
            and {"crop", "uptake"} <= covered
            and bool({"split", "sidedress"} & covered)
            and bool({"cover", "inhibitor", "stabilizer"} & covered)
        ):
            return selected
        return None
    if _cover_crop_water_focus(focus_tokens):
        selected_cover_priorities = [_cover_crop_water_priority(token_cache.get(doc.doc_id) or _doc_tokens(doc)) for doc in selected]
        if (
            max(selected_cover_priorities, default=0) >= 60
            and any(_is_reviewed_cover_crop_water_doc(doc, token_cache=token_cache) for doc in selected)
            and {"cover", "crop"} <= covered
            and bool({"water", "moisture", "stored"} & covered)
            and "termination" in covered
            and bool({"species", "mix"} & covered)
            and bool({"planting", "window"} & covered)
        ):
            return selected
        return None
    if _precision_economics_focus(focus_tokens):
        if {"variable", "rate"} <= covered and {"crop", "price", "fertilizer", "cost", "partial", "budget", "roi", "check", "strip"} & covered:
            return selected
        return None
    if _erosion_control_focus(focus_tokens):
        if "erosion" in covered and {"residue", "cover", "contour", "strip", "terrace", "waterway", "tillage", "no-till"} & covered:
            return selected
        return None
    if "field_data_boundary" in namespaces:
        field_terms = {"audit", "calibration", "check", "layers", "records", "strip", "validated", "yield"}
        if "calibration" in covered and len(covered & field_terms) >= 3:
            return selected
        return None
    if {"salinity", "sodicity", "sodium", "sar", "esp"} & set(tokenize(query)):
        if {"salinity", "sodicity"} <= covered and {"sar", "sodium", "conductivity", "drainage"} & covered:
            return selected
        return None
    if "regional_environment" in namespaces:
        if (
            "mlra" in covered
            and bool({"climate", "precipitation"} & covered)
            and bool({"dryland", "erosion", "ecological", "site"} & covered)
        ):
            return selected
        return None
    if namespaces & {"soil_water", "soil_health"}:
        if {"drainage", "infiltration", "leaching", "runoff"} & covered:
            return selected
        return None
    return None


def _regional_environment_subquery(focus_tokens: set[str]) -> str:
    mlra_tokens = sorted(token for token in focus_tokens if _looks_like_mlra_token(token))
    if mlra_tokens:
        focus = [*mlra_tokens, "regional", "climate", "erosion", "dryland", "ecological", "site"]
        return "MLRA " + " ".join(focus)
    return "MLRA ecological site ecoregion climate precipitation soil texture physiography landform erosion"


def _looks_like_mlra_token(token: str) -> bool:
    return len(token) == 4 and token[:3].isdigit() and token[3].isalpha()


def _rerank_and_select_for_coverage(
    docs: list[RetrievedDoc],
    *,
    query: str,
    filters: dict[str, Any],
    top_k: int,
) -> list[RetrievedDoc]:
    token_cache = _build_doc_token_cache(docs)
    return _select_coverage_balanced(
        _rerank_for_coverage(docs, query=query, filters=filters, token_cache=token_cache),
        query=query,
        filters=filters,
        top_k=top_k,
        token_cache=token_cache,
    )


def _rerank_for_coverage(
    docs: list[RetrievedDoc],
    *,
    query: str,
    filters: dict[str, Any],
    token_cache: dict[str, set[str]] | None = None,
) -> list[RetrievedDoc]:
    query_tokens = set(tokenize(query))
    expansion_terms = _list_filter(filters.get("query_expansion"))
    expansion_tokens = set(tokenize(" ".join(expansion_terms)))
    route_namespaces = set(_list_filter(filters.get("namespaces")))
    source_type_filter = set(_list_filter(filters.get("source_type")))
    token_cache = token_cache or _build_doc_token_cache(docs)
    ranked: list[RetrievedDoc] = []
    for doc in docs:
        text = " ".join([doc.title, doc.text, " ".join(doc.tags)]).lower()
        doc_tokens = token_cache.get(doc.doc_id) or _doc_tokens(doc)
        direct_overlap = len(query_tokens & doc_tokens)
        expansion_overlap = len(expansion_tokens & doc_tokens)
        phrase_overlap = sum(1 for term in expansion_terms if " " in term and term.lower() in text)
        namespace_overlap = len(route_namespaces & set(doc.namespaces))
        source_bonus = 0.0
        if source_type_filter and doc.source_type in source_type_filter:
            source_bonus += 0.35
        if filters.get("risk_level") == "regulated" and doc.source_type == "boundary":
            source_bonus += 5.0
        if doc.source_type == "boundary" and route_namespaces & {"label_boundary", "field_data_boundary"}:
            source_bonus += 1.5
        if doc.source_type == "regional_environment_profile" and "regional_environment" in route_namespaces:
            source_bonus += 1.0
        if doc.source_type == "applied_guidance" and route_namespaces & {"fertility", "soil_water", "crop_management", "plant_health"}:
            source_bonus += 0.2
        if _reviewed_public_source(doc):
            source_bonus += 0.45
        coverage_score = (
            doc.score
            + direct_overlap * 0.35
            + expansion_overlap * 0.22
            + phrase_overlap * 0.5
            + namespace_overlap * 0.28
            + source_bonus
        )
        ranked.append(replace(doc, score=round(coverage_score, 4)))
    return sorted(ranked, key=lambda doc: (-doc.score, doc.doc_id))


def _select_coverage_balanced(
    docs: list[RetrievedDoc],
    *,
    query: str,
    filters: dict[str, Any],
    top_k: int,
    token_cache: dict[str, set[str]] | None = None,
) -> list[RetrievedDoc]:
    if not docs or top_k <= 0:
        return []
    query_tokens = set(tokenize(query))
    target_tokens = query_tokens | _priority_expansion_tokens(filters)
    if not target_tokens:
        return docs[:top_k]
    remaining = list(docs)
    selected: list[RetrievedDoc] = []
    covered: set[str] = set()
    token_cache = token_cache or _build_doc_token_cache(docs)
    doc_tokens = lambda doc: token_cache.get(doc.doc_id) or _doc_tokens(doc)
    source_availability_focus = _source_availability_focus(target_tokens)
    if source_availability_focus:
        source_priorities = {item.doc_id: _source_availability_priority(doc_tokens(item)) for item in remaining}
        source_candidates = sorted(
            [item for item in remaining if source_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -source_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in source_candidates[: min(2, top_k)]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    postharvest_storage_focus = _postharvest_storage_focus(target_tokens)
    if postharvest_storage_focus and len(selected) < top_k:
        postharvest_priorities = {item.doc_id: _postharvest_storage_priority(doc_tokens(item)) for item in remaining}
        postharvest_candidates = sorted(
            [item for item in remaining if postharvest_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -postharvest_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in postharvest_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    if filters.get("risk_level") == "regulated":
        seed_treatment_focus = _seed_treatment_focus(target_tokens)
        aphid_focus = _aphid_focus(target_tokens)
        ipm_threshold_focus = _ipm_threshold_focus(target_tokens)
        fungicide_roi_focus = _fungicide_roi_focus(target_tokens)
        cover_crop_water_focus = _cover_crop_water_focus(target_tokens)
        precision_economics_focus = _precision_economics_focus(target_tokens)
        focused_product_decision = seed_treatment_focus or aphid_focus or ipm_threshold_focus or fungicide_roi_focus
        if seed_treatment_focus:
            seed_priorities = {item.doc_id: _seed_treatment_priority(doc_tokens(item)) for item in remaining}
            seed_candidates = sorted(
                [item for item in remaining if seed_priorities[item.doc_id] > 0],
                key=lambda doc: (
                    -seed_priorities[doc.doc_id],
                    -len(doc_tokens(doc) & target_tokens),
                    -doc.score,
                    doc.doc_id,
                ),
            )
            for doc in seed_candidates[: min(2, top_k)]:
                selected.append(doc)
                remaining.remove(doc)
                covered.update(doc_tokens(doc) & target_tokens)
        if aphid_focus and len(selected) < top_k:
            aphid_priorities = {item.doc_id: _aphid_priority(doc_tokens(item)) for item in remaining}
            aphid_candidates = sorted(
                [item for item in remaining if aphid_priorities[item.doc_id] > 0],
                key=lambda doc: (
                    -aphid_priorities[doc.doc_id],
                    -len(doc_tokens(doc) & target_tokens),
                    -doc.score,
                    doc.doc_id,
                ),
            )
            for doc in aphid_candidates[: min(2, top_k - len(selected))]:
                selected.append(doc)
                remaining.remove(doc)
                covered.update(doc_tokens(doc) & target_tokens)
        if ipm_threshold_focus and len(selected) < top_k:
            ipm_priorities = {item.doc_id: _ipm_threshold_priority(doc_tokens(item)) for item in remaining}
            ipm_candidates = sorted(
                [item for item in remaining if ipm_priorities[item.doc_id] > 0],
                key=lambda doc: (
                    -ipm_priorities[doc.doc_id],
                    -len(doc_tokens(doc) & target_tokens),
                    -doc.score,
                    doc.doc_id,
                ),
            )
            for doc in ipm_candidates[: min(2, top_k - len(selected))]:
                selected.append(doc)
                remaining.remove(doc)
                covered.update(doc_tokens(doc) & target_tokens)
        if fungicide_roi_focus and len(selected) < top_k:
            fungicide_priorities = {item.doc_id: _fungicide_roi_priority(doc_tokens(item)) for item in remaining}
            fungicide_candidates = sorted(
                [item for item in remaining if fungicide_priorities[item.doc_id] > 0],
                key=lambda doc: (
                    -fungicide_priorities[doc.doc_id],
                    -len(doc_tokens(doc) & target_tokens),
                    -doc.score,
                    doc.doc_id,
                ),
            )
            for doc in fungicide_candidates[: min(2, top_k - len(selected))]:
                selected.append(doc)
                remaining.remove(doc)
                covered.update(doc_tokens(doc) & target_tokens)
        boundary_candidates = sorted(
            [item for item in remaining if item.source_type == "boundary"],
            key=lambda doc: (
                -_regulated_boundary_priority_score(doc_tokens(doc)),
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        boundary_limit = max(0, min(1 if focused_product_decision else 3, top_k - len(selected)))
        required_boundary_docs = boundary_candidates[:boundary_limit]
        weather_boundary = next(
            (doc for doc in boundary_candidates if {"wind", "drift", "buffer"} & doc_tokens(doc) and doc not in required_boundary_docs),
            None,
        )
        if not focused_product_decision and weather_boundary is not None and len(required_boundary_docs) < min(4, top_k):
            required_boundary_docs.append(weather_boundary)
        for doc in required_boundary_docs:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    cover_crop_water_focus = _cover_crop_water_focus(target_tokens)
    if cover_crop_water_focus and len(selected) < top_k:
        cover_priorities = {item.doc_id: _cover_crop_water_priority(doc_tokens(item)) for item in remaining}
        cover_candidates = sorted(
            [item for item in remaining if cover_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -cover_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in cover_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    forage_livestock_focus = _forage_livestock_focus(target_tokens)
    if forage_livestock_focus and len(selected) < top_k:
        forage_priorities = {item.doc_id: _forage_livestock_priority(doc_tokens(item)) for item in remaining}
        forage_candidates = sorted(
            [item for item in remaining if forage_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -forage_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in forage_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    soil_survey_prior_focus = _soil_survey_prior_focus(target_tokens)
    if soil_survey_prior_focus and len(selected) < top_k:
        soil_survey_priorities = {item.doc_id: _soil_survey_prior_priority(doc_tokens(item)) for item in remaining}
        soil_survey_candidates = sorted(
            [item for item in remaining if soil_survey_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -soil_survey_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in soil_survey_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    conservation_plan_focus = _conservation_plan_focus(target_tokens)
    if conservation_plan_focus and len(selected) < top_k:
        conservation_priorities = {item.doc_id: _conservation_plan_priority(doc_tokens(item)) for item in remaining}
        conservation_candidates = sorted(
            [item for item in remaining if conservation_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -conservation_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in conservation_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    crop_statistics_focus = _crop_statistics_focus(target_tokens)
    if crop_statistics_focus and len(selected) < top_k:
        crop_stats_priorities = {item.doc_id: _crop_statistics_priority(doc_tokens(item)) for item in remaining}
        crop_stats_candidates = sorted(
            [item for item in remaining if crop_stats_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -crop_stats_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in crop_stats_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    cdl_history_focus = _cdl_history_focus(target_tokens)
    if cdl_history_focus and len(selected) < top_k:
        cdl_priorities = {item.doc_id: _cdl_history_priority(doc_tokens(item)) for item in remaining}
        cdl_candidates = sorted(
            [item for item in remaining if cdl_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -cdl_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in cdl_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    horticulture_specialty_focus = _horticulture_specialty_focus(target_tokens)
    if horticulture_specialty_focus and len(selected) < top_k:
        horticulture_priorities = {item.doc_id: _horticulture_specialty_priority(doc_tokens(item)) for item in remaining}
        horticulture_candidates = sorted(
            [item for item in remaining if horticulture_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -horticulture_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in horticulture_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    ipm_threshold_focus = _ipm_threshold_focus(target_tokens)
    if ipm_threshold_focus and len(selected) < top_k:
        ipm_priorities = {item.doc_id: _ipm_threshold_priority(doc_tokens(item)) for item in remaining}
        ipm_candidates = sorted(
            [item for item in remaining if ipm_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -ipm_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in ipm_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    precision_economics_focus = _precision_economics_focus(target_tokens)
    if precision_economics_focus and len(selected) < top_k:
        precision_priorities = {item.doc_id: _precision_economics_priority(doc_tokens(item)) for item in remaining}
        precision_candidates = sorted(
            [item for item in remaining if precision_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -precision_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in precision_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    nitrate_leaching_focus = _nitrate_leaching_focus(target_tokens)
    if nitrate_leaching_focus and len(selected) < top_k:
        nitrate_priorities = {item.doc_id: _nitrate_leaching_priority(doc_tokens(item)) for item in remaining}
        nitrate_candidates = sorted(
            [item for item in remaining if nitrate_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -nitrate_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in nitrate_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    erosion_control_focus = _erosion_control_focus(target_tokens)
    if erosion_control_focus and len(selected) < top_k:
        erosion_priorities = {item.doc_id: _erosion_control_priority(doc_tokens(item)) for item in remaining}
        erosion_candidates = sorted(
            [item for item in remaining if erosion_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -erosion_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in erosion_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    salinity_focus = {"salinity", "sodicity", "sodium", "sar", "esp"} & target_tokens
    if salinity_focus and len(selected) < top_k:
        salinity_priorities = {
            item.doc_id: _salinity_sodicity_priority(doc_tokens(item))
            for item in remaining
        }
        salinity_candidates = sorted(
            [item for item in remaining if salinity_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -salinity_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in salinity_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    white_mold_focus = _white_mold_focus(target_tokens)
    if white_mold_focus and len(selected) < top_k:
        white_mold_priorities = {item.doc_id: _white_mold_priority(doc_tokens(item)) for item in remaining}
        white_mold_candidates = sorted(
            [item for item in remaining if white_mold_priorities[item.doc_id] > 0],
            key=lambda doc: (
                -white_mold_priorities[doc.doc_id],
                -len(doc_tokens(doc) & target_tokens),
                -doc.score,
                doc.doc_id,
            ),
        )
        for doc in white_mold_candidates[: min(2, top_k - len(selected))]:
            selected.append(doc)
            remaining.remove(doc)
            covered.update(doc_tokens(doc) & target_tokens)
    while remaining and len(selected) < top_k:
        if not selected:
            choice = remaining[0]
        else:
            selected_namespaces = {namespace for item in selected for namespace in item.namespaces}
            choice = sorted(
                remaining,
                key=lambda doc: (
                    -len((doc_tokens(doc) & target_tokens) - covered),
                    -len(doc_tokens(doc) & query_tokens),
                    -len(set(doc.namespaces) - selected_namespaces),
                    -doc.score,
                    doc.doc_id,
                ),
            )[0]
        selected.append(choice)
        remaining.remove(choice)
        covered.update(doc_tokens(choice) & target_tokens)
    return selected


def _doc_tokens(doc: RetrievedDoc) -> set[str]:
    if doc.token_set:
        return set(doc.token_set)
    return set(tokenize(" ".join([doc.title, doc.text, " ".join(doc.tags)])))


def _build_doc_token_cache(docs: list[RetrievedDoc]) -> dict[str, set[str]]:
    return {doc.doc_id: _doc_tokens(doc) for doc in docs}


def _covered_doc_tokens(docs: list[RetrievedDoc], *, token_cache: dict[str, set[str]] | None = None) -> set[str]:
    covered: set[str] = set()
    token_cache = token_cache or {}
    for doc in docs:
        covered.update(token_cache.get(doc.doc_id) or _doc_tokens(doc))
    return covered


def _reviewed_public_source(doc: RetrievedDoc) -> bool:
    source = str(getattr(doc, "source", "") or "").lower()
    return any(term in source for term in ("extension", ".edu", ".gov", "university", "nrcs"))


def _is_reviewed_cover_crop_water_doc(doc: RetrievedDoc, *, token_cache: dict[str, set[str]]) -> bool:
    tokens = token_cache.get(doc.doc_id) or _doc_tokens(doc)
    return (
        _reviewed_public_source(doc)
        and _cover_crop_water_priority(tokens) >= 60
        and {"cover", "crop"} <= tokens
        and bool({"water", "moisture", "stored"} & tokens)
        and "termination" in tokens
        and bool({"species", "mix"} & tokens)
        and bool({"planting", "window"} & tokens)
    )


def _regulated_boundary_priority(tokens: set[str]) -> tuple[int, int, int]:
    label_product = int({"product", "label"} <= tokens)
    required_context = len(tokens & {"current", "jurisdiction", "registration", "crop", "site", "target", "pest"})
    weather_boundary = len(tokens & {"wind", "drift", "buffer", "rainfast", "downwind"})
    return (label_product, required_context, weather_boundary)


def _regulated_boundary_priority_score(tokens: set[str]) -> int:
    label_product, required_context, weather_boundary = _regulated_boundary_priority(tokens)
    return label_product * 100 + required_context * 10 + weather_boundary


def _salinity_sodicity_priority(tokens: set[str]) -> int:
    core = len(tokens & {"salinity", "sodicity", "sodium", "sar", "esp"})
    measurements = len(tokens & {"conductivity", "ece", "irrigation", "drainage", "leaching"})
    return core * 2 + measurements


def _seed_treatment_focus(tokens: set[str]) -> bool:
    return {"seed", "treatment"} <= tokens or "seedcorn" in tokens or "wireworm" in tokens or "grub" in tokens


def _seed_treatment_priority(tokens: set[str]) -> int:
    core = len(tokens & {"seed", "treatment", "insecticide"})
    risk = len(tokens & {"early", "planting", "temperature", "cool", "wet", "pest", "history", "pressure", "threshold", "risk"})
    pests = len(tokens & {"seedcorn", "maggot", "beetle", "wireworm", "grub", "insect"})
    return core * 20 + risk * 4 + pests * 3


def _aphid_focus(tokens: set[str]) -> bool:
    return "aphid" in tokens or "aphids" in tokens


def _aphid_priority(tokens: set[str]) -> int:
    core = len(tokens & {"aphid", "aphids", "soybean"})
    evidence = len(tokens & {"scout", "scouting", "count", "threshold", "economic", "stage", "species", "natural", "enemies", "beneficial", "label"})
    return core * 20 + evidence * 5


def _ipm_threshold_focus(tokens: set[str]) -> bool:
    insect = bool(tokens & {"insect", "insects", "insecticide", "aphid", "aphids", "pest"})
    evidence = bool(tokens & {"threshold", "scout", "scouting", "sampling", "count", "beneficial", "enemies", "stage"})
    return insect and evidence


def _ipm_threshold_priority(tokens: set[str]) -> int:
    core = len(tokens & {"ipm", "insect", "insects", "insecticide", "pest", "aphid", "aphids"})
    evidence = len(tokens & {"scout", "scouting", "sampling", "count", "density", "threshold", "economic", "stage", "species", "beneficial", "natural", "enemies", "label"})
    return core * 18 + evidence * 5


def _fungicide_roi_focus(tokens: set[str]) -> bool:
    return "fungicide" in tokens and bool(tokens & {"roi", "return", "price", "justified", "economics", "economic", "yield"})


def _fungicide_roi_priority(tokens: set[str]) -> int:
    core = len(tokens & {"fungicide", "roi", "economics", "economic"})
    evidence = len(tokens & {"disease", "severity", "scouting", "hybrid", "variety", "susceptibility", "susceptib", "stage", "weather", "yield", "potential", "label", "price"})
    return core * 20 + evidence * 4


def _cover_crop_water_focus(tokens: set[str]) -> bool:
    cover_crop = "cover" in tokens and bool(tokens & {"crop", "crops"})
    return (cover_crop or bool(tokens & {"cover-crop", "cover-crops"})) and bool(
        tokens
        & {
            "water",
            "moisture",
            "stored",
            "termination",
            "planting",
            "residue",
            "erosion",
            "dryland",
            "irrigation",
            "rainfall",
        }
    )


def _cover_crop_water_priority(tokens: set[str]) -> int:
    core = len(tokens & {"cover", "crop", "crops", "cover-crop", "cover-crops"})
    water = len(tokens & {"water", "moisture", "stored", "dryland", "irrigation", "rainfall"})
    management = len(tokens & {"termination", "method", "species", "mix", "residue", "erosion", "planting", "window", "rotation"})
    return core * 20 + water * 5 + management * 4


def _forage_livestock_focus(tokens: set[str]) -> bool:
    forage = bool(tokens & {"forage", "pasture", "graze", "grazing", "hay", "silage", "livestock", "cattle"})
    toxicity = bool(tokens & {"nitrate", "prussic", "hydrocyanic", "drought", "frost", "stress", "regrowth"})
    return forage and toxicity


def _forage_livestock_priority(tokens: set[str]) -> int:
    core = len(tokens & {"forage", "pasture", "nitrate", "prussic", "hydrocyanic"})
    stress = len(tokens & {"drought", "frost", "stress", "regrowth", "warm", "wet"})
    testing = len(tokens & {"test", "testing", "lab", "feed", "forage"})
    livestock = len(tokens & {"grazing", "graze", "hay", "silage", "livestock", "cattle", "withdrawal", "safety"})
    species = len(tokens & {"species", "sorghum", "sudan", "millet", "grass", "legume"})
    return core * 18 + stress * 5 + testing * 5 + livestock * 4 + species * 4


def _soil_survey_prior_focus(tokens: set[str]) -> bool:
    return bool(tokens & {"nrcs", "sda"}) or {"soil", "survey"} <= tokens or {"map", "unit"} <= tokens or "component" in tokens


def _soil_survey_prior_priority(tokens: set[str]) -> int:
    core = len(tokens & {"nrcs", "sda", "soil", "survey", "map", "unit", "component"})
    interpretations = len(tokens & {"drainage", "class", "hydrologic", "group", "hydric", "texture", "slope", "restrictive"})
    boundary = len(tokens & {"prior", "screening", "regional", "context", "test", "observation", "ground", "truth", "replacement"})
    return core * 14 + interpretations * 5 + boundary * 5


def _conservation_plan_focus(tokens: set[str]) -> bool:
    conservation = bool(tokens & {"conservation", "nrcs", "waterway", "buffer", "setback", "residue"})
    runoff = bool(tokens & {"runoff", "erosion", "ditch", "drainage", "slope"})
    return conservation and runoff


def _conservation_plan_priority(tokens: set[str]) -> int:
    runoff = len(tokens & {"runoff", "erosion", "ditch", "drainage"})
    cover = len(tokens & {"residue", "cover", "crop", "crops"})
    practices = len(tokens & {"waterway", "buffer", "setback", "grass", "grassed", "outlet"})
    planning = len(tokens & {"nrcs", "conservation", "plan", "local", "guidance"})
    field = len(tokens & {"slope", "texture", "drainage", "soil"})
    return runoff * 18 + cover * 5 + practices * 5 + planning * 7 + field * 4


def _crop_statistics_focus(tokens: set[str]) -> bool:
    nass = bool(tokens & {"nass", "quickstats"}) or {"quick", "stats"} <= tokens
    stats = bool(tokens & {"statistics", "yield", "acreage", "production", "county", "state", "regional"})
    return nass or (stats and bool(tokens & {"regional", "county", "state"}))


def _crop_statistics_priority(tokens: set[str]) -> int:
    source = len(tokens & {"usda", "nass", "quick", "stats", "quickstats"})
    stats = len(tokens & {"regional", "statistics", "yield", "acreage", "production", "county", "state"})
    field = len(tokens & {"field", "records", "record", "yield", "map", "grower", "history"})
    boundary = len(tokens & {"prior", "prediction", "predict", "field-specific", "specific", "replace", "guarantee"})
    return source * 20 + stats * 5 + field * 4 + boundary * 4


def _cdl_history_focus(tokens: set[str]) -> bool:
    return "cdl" in tokens or {"cropland", "layer"} <= tokens or ({"crop", "cover"} <= tokens and bool(tokens & {"sample", "history", "rotation"}))


def _cdl_history_priority(tokens: set[str]) -> int:
    source = len(tokens & {"usda", "nass", "cdl", "cropland", "data", "layer"})
    sampling = len(tokens & {"boundary", "sample", "points", "pixel", "class", "crop-cover", "classification", "multi-year", "recent"})
    records = len(tokens & {"grower", "record", "records", "planting", "history", "rotation"})
    boundary = len(tokens & {"prior", "screening", "acreage", "insurance", "truth", "mismatch", "overrule"})
    return source * 20 + sampling * 5 + records * 5 + boundary * 4


def _horticulture_specialty_focus(tokens: set[str]) -> bool:
    specialty = bool(tokens & {"specialty", "vegetable", "tomato", "horticulture"})
    disease_water = bool(tokens & {"irrigation", "moisture", "humidity", "wetness", "disease", "scouting", "stage"})
    return specialty and disease_water


def _horticulture_specialty_priority(tokens: set[str]) -> int:
    specialty = len(tokens & {"specialty", "vegetable", "tomato", "horticulture"})
    water = len(tokens & {"irrigation", "moisture", "water", "soil"})
    disease = len(tokens & {"disease", "risk", "humidity", "leaf", "wetness", "scouting", "scout"})
    decision = len(tokens & {"stage", "extension", "label", "market", "quality", "local"})
    return specialty * 18 + water * 5 + disease * 5 + decision * 5


def _source_availability_focus(tokens: set[str]) -> bool:
    source_state = bool(tokens & {"source", "sources", "provenance", "trace", "adapter", "unavailable", "configured", "cached", "failed", "timeout"})
    checked_source = "checked" in tokens and bool(tokens & {"source", "sources", "adapter", "boundary", "geometry", "point", "soil", "weather", "cdl"})
    geometry_or_public = bool(tokens & {"geometry", "boundary", "point", "location", "cdl", "weather", "label", "survey"})
    return (source_state or checked_source) and geometry_or_public


def _source_availability_priority(tokens: set[str]) -> int:
    source_state = len(tokens & {"source", "sources", "card", "checked", "provenance", "trace", "adapter", "unavailable", "configured", "failed", "timeout", "cached", "timestamp"})
    geometry = len(tokens & {"missing", "point", "boundary", "geometry", "location", "usable", "confirm"})
    public_sources = len(tokens & {"soil", "survey", "cdl", "weather", "label", "metadata", "public", "prior"})
    boundaries = len(tokens & {"not", "field", "truth", "exact", "rate", "legal", "interpretation", "fabricate"})
    return source_state * 18 + geometry * 8 + public_sources * 6 + boundaries * 5


def _postharvest_storage_focus(tokens: set[str]) -> bool:
    postharvest = bool(tokens & {"postharvest", "harvest", "storage", "drying", "aeration", "mycotoxin", "cooling", "cold", "chain"})
    quality = bool(tokens & {"quality", "market", "moisture", "temperature", "humidity", "disease", "decay", "sampling", "segregation"})
    return postharvest and quality


def _postharvest_storage_priority(tokens: set[str]) -> int:
    core = len(tokens & {"postharvest", "harvest", "storage", "drying", "aeration", "cooling", "cold", "chain"})
    quality = len(tokens & {"field", "heat", "temperature", "humidity", "disease", "decay", "quality", "market", "requirement"})
    mycotoxin = len(tokens & {"mycotoxin", "mold", "sampling", "testing", "lot", "segregation", "test", "method", "lab"})
    management = len(tokens & {"storage", "plan", "drying", "aeration", "marketing", "risk", "safe", "acceptance"})
    return core * 18 + quality * 5 + mycotoxin * 6 + management * 5


def _precision_economics_focus(tokens: set[str]) -> bool:
    return bool(tokens & {"variable", "variable-rate", "prescription"}) and bool(
        tokens & {"profit", "roi", "economic", "economics", "defensible", "spend", "cost", "price", "budget"}
    )


def _precision_economics_priority(tokens: set[str]) -> int:
    core = len(tokens & {"variable", "variable-rate", "rate", "prescription", "fertilizer"})
    economics = len(tokens & {"profit", "roi", "economic", "economics", "defensible", "spend", "cost", "price", "budget"})
    evidence = len(tokens & {"soil", "test", "zones", "yield", "response", "curve", "crop", "fertilizer", "application", "check", "strip", "trial", "audit"})
    return core * 15 + economics * 6 + evidence * 4


def _nitrate_leaching_focus(tokens: set[str]) -> bool:
    return bool(tokens & {"nitrate", "nitrogen"}) and bool(tokens & {"leach", "leaching", "loss", "losses"})


def _nitrate_leaching_priority(tokens: set[str]) -> int:
    core = len(tokens & {"nitrate", "nitrogen", "leach", "leaching", "loss", "losses"})
    risk = len(tokens & {"sandy", "sand", "rain", "rainfall", "heavy", "irrigation", "drainage", "root", "zone"})
    management = len(tokens & {"crop", "uptake", "split", "sidedress", "timing", "cover", "crops", "inhibitor", "stabilizer", "credits"})
    return core * 20 + risk * 5 + management * 5


def _erosion_control_focus(tokens: set[str]) -> bool:
    return "erosion" in tokens and bool(
        tokens
        & {
            "residue",
            "cover",
            "crop",
            "crops",
            "contour",
            "strip",
            "terrace",
            "terraces",
            "waterway",
            "waterways",
            "tillage",
            "no-till",
            "runoff",
            "slope",
            "sloping",
        }
    )


def _erosion_control_priority(tokens: set[str]) -> int:
    core = len(tokens & {"erosion", "runoff", "slope", "sloping"})
    cover = len(tokens & {"residue", "cover", "crop", "crops", "perennial", "sod"})
    structures = len(tokens & {"contour", "strip", "terrace", "terraces", "waterway", "waterways", "buffer", "outlet"})
    tillage = len(tokens & {"tillage", "reduced", "no-till"})
    return core * 20 + cover * 5 + structures * 5 + tillage * 4


def _white_mold_focus(tokens: set[str]) -> bool:
    return {"white", "mold"} <= tokens


def _white_mold_priority(tokens: set[str]) -> int:
    core = len(tokens & {"white", "mold", "soybean"})
    evidence = len(tokens & {"variety", "ratings", "tolerance", "canopy", "row", "spacing", "population", "field", "history", "rotation", "fungicide", "timing", "risk"})
    return core * 20 + evidence * 4


def _priority_expansion_tokens(filters: dict[str, Any]) -> set[str]:
    namespaces = set(_list_filter(filters.get("namespaces")))
    expansions = set(tokenize(" ".join(_list_filter(filters.get("query_expansion")))))
    priority: set[str] = set()
    if _seed_treatment_focus(expansions):
        priority.update({"seed", "treatment", "insecticide", "early", "planting", "soil", "temperature", "cool", "wet", "pest", "history", "pressure", "seedcorn", "maggot", "beetle", "wireworm", "grub", "threshold", "risk", "label"})
    elif _aphid_focus(expansions):
        priority.update({"aphid", "aphids", "scout", "count", "threshold", "economic", "stage", "species", "natural", "enemies", "beneficial", "label"})
    elif _ipm_threshold_focus(expansions):
        priority.update({"ipm", "insect", "insects", "insecticide", "pest", "scout", "count", "sampling", "species", "crop", "stage", "threshold", "economic", "beneficial", "natural", "enemies", "label"})
    elif _fungicide_roi_focus(expansions):
        priority.update({"fungicide", "roi", "disease", "severity", "scouting", "hybrid", "variety", "susceptibility", "growth", "stage", "weather", "yield", "potential", "economics", "label"})
    elif _forage_livestock_focus(expansions):
        priority.update({"forage", "pasture", "nitrate", "prussic", "hydrocyanic", "drought", "frost", "stress", "regrowth", "test", "lab", "feed", "species", "sorghum", "sudan", "millet", "grass", "legume", "grazing", "hay", "silage", "livestock", "safety", "withdrawal"})
    elif _soil_survey_prior_focus(expansions):
        priority.update({"soil", "survey", "nrcs", "sda", "map", "unit", "component", "drainage", "hydrologic", "hydric", "prior", "screening", "regional", "context", "test", "observation", "ground", "truth", "replacement"})
    elif _conservation_plan_focus(expansions):
        priority.update({"runoff", "erosion", "residue", "cover", "crop", "waterway", "buffer", "setback", "grass", "grassed", "slope", "texture", "drainage", "nrcs", "conservation", "plan", "local", "guidance"})
    elif _crop_statistics_focus(expansions):
        priority.update({"usda", "nass", "quick", "stats", "regional", "statistics", "yield", "acreage", "production", "county", "state", "field", "records", "map", "grower", "prior", "field-specific", "predict"})
    elif _cdl_history_focus(expansions):
        priority.update({"usda", "nass", "cdl", "cropland", "data", "layer", "boundary", "sample", "points", "crop-cover", "class", "multi-year", "recent", "rotation", "grower", "planting", "record", "history", "prior", "acreage", "insurance", "truth"})
    elif _horticulture_specialty_focus(expansions):
        priority.update({"specialty", "vegetable", "tomato", "irrigation", "moisture", "disease", "risk", "humidity", "leaf", "wetness", "scouting", "crop", "stage", "local", "extension", "label", "market", "quality"})
    elif _source_availability_focus(expansions):
        priority.update({"source", "card", "checked", "not", "unavailable", "configured", "adapter", "cached", "timestamp", "missing", "point", "boundary", "geometry", "soil", "survey", "cdl", "weather", "label", "metadata", "public", "prior", "field", "truth", "exact", "rate"})
    elif _postharvest_storage_focus(expansions):
        priority.update({"postharvest", "harvest", "storage", "cooling", "cold", "chain", "field", "heat", "handling", "sanitation", "temperature", "humidity", "disease", "decay", "quality", "market", "mycotoxin", "sampling", "testing", "lot", "segregation", "drying", "aeration"})
    elif _cover_crop_water_focus(expansions):
        priority.update({"cover", "crop", "crops", "cover-crop", "cover-crops", "water", "moisture", "stored", "termination", "method", "species", "mix", "residue", "erosion", "planting", "window", "rotation", "dryland", "irrigation", "rainfall"})
    elif _precision_economics_focus(expansions):
        priority.update({"variable", "variable-rate", "rate", "prescription", "fertilizer", "economic", "defensible", "profit", "roi", "crop", "price", "fertilizer", "cost", "application", "partial", "budget", "soil", "test", "zones", "yield", "response", "check", "strip", "trial", "audit"})
    elif _nitrate_leaching_focus(expansions):
        priority.update({"nitrate", "nitrogen", "leaching", "loss", "sandy", "rain", "soil", "test", "yield", "goal", "crop", "uptake", "split", "sidedress", "timing", "cover", "crops", "inhibitor", "stabilizer", "irrigation", "root", "zone", "credits"})
    elif _erosion_control_focus(expansions):
        priority.update({"erosion", "residue", "cover", "crop", "crops", "contour", "farming", "strip", "cropping", "terrace", "terraces", "grassed", "waterway", "waterways", "runoff", "slope", "tillage", "reduction", "no-till", "buffer", "outlet"})
    elif _white_mold_focus(expansions):
        priority.update({"white", "mold", "variety", "ratings", "tolerance", "canopy", "row", "spacing", "population", "field", "history", "rotation", "fungicide", "timing", "risk"})
    elif namespaces & {"product_stewardship", "label_boundary"}:
        priority.update({"label", "wind", "buffer", "drift", "gust", "downwind", "runoff", "drainage"})
    if namespaces & {"soil_water", "soil_health"} and not priority:
        priority.update({"drainage", "runoff", "leaching", "infiltration", "salinity", "sodicity", "sodium"})
    if "regional_environment" in namespaces:
        priority.update({"mlra", "ecoregion", "climate", "precipitation", "physiography", "landform", "erosion", "ecological", "site"})
    if "field_data_boundary" in namespaces:
        priority.update({"yield", "maps", "records", "audit", "validated", "layers", "calibration", "calibrated", "check", "strip"})
    return priority & expansions if priority else expansions


def _short_terms(values: Iterable[str], *, limit: int) -> list[str]:
    terms = [str(value).strip() for value in values if str(value).strip()]
    return terms[:limit]


def _chunks(values: list[str], *, size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _list_filter(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def _str_filter(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
