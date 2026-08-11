from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from agronomy_agent.agno_runtime.local_index import RetrievedDoc, tokenize
from agronomy_agent.decision_route import DecisionRouteState, build_decision_route_state
from agronomy_agent.decision_contract import AgronomyDecisionContract, obligation_coverage
from agronomy_agent.evidence_authority import classify_evidence_authority


_GENERIC_TAGS = {
    "agronomy",
    "crop management",
    "diagnosis",
    "field history",
    "field pattern",
    "farmer knowledge",
    "label",
    "local guidance",
    "management",
    "monitoring",
    "plant health",
    "aafc crop development stage",
    "corn soybean stage table",
    "scouting",
    "soil test",
}
_CROP_ENTITY_TAGS = {
    "alfalfa",
    "barley",
    "canola",
    "chickpea",
    "corn",
    "cotton",
    "cucumber",
    "dry bean",
    "field pea",
    "flax",
    "forage",
    "lentil",
    "lettuce",
    "maize",
    "oat",
    "oats",
    "potato",
    "sorghum",
    "soybean",
    "soybeans",
    "spring wheat",
    "strawberry",
    "tomato",
    "wheat",
    "winter wheat",
}
_NON_DECISION_TOKENS = {
    "about",
    "actual",
    "available",
    "before",
    "current",
    "field",
    "following",
    "guidance",
    "local",
    "management",
    "question",
    "should",
    "source",
    "using",
}
_PHRASE_ANCHOR_STOPWORDS = {
    "answer",
    "before",
    "current",
    "decision",
    "field",
    "guidance",
    "label",
    "local",
    "management",
    "public",
    "question",
    "should",
    "source",
}
_BOUNDARY_TYPES = {"boundary", "ontology", "regional_environment_profile", "regional_environment"}
_STRONG_PRIMARY_MIN_SCORE = 4.2
_DECISIVE_EVIDENCE_REQUIRED = {"fungicide_decision"}
_NAMED_CANADIAN_REGIONAL_PRODUCT_RE = re.compile(
    r"(?:\baafc\b.{0,100}\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index|crop development stage|crop[- ]stage raster|growth[- ]stage raster)\b|"
    r"\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index)\b|"
    r"\b(?:crop development|crop[- ]stage|growth[- ]stage) (?:layer|raster|product|values?)\b|"
    r"\b(?:indices? de sant[eé] des cultures|indice de stress des cultures|"
    r"stade de d[eé]veloppement (?:de la culture|des cultures))\b|"
    r"\b(?:british columbia|nova scotia|prince edward island|pei) detailed soil survey\b|"
    r"\b(?:quebec|québec) agro[- ]pedological atlas\b|\bagro[- ]pedological atlas of (?:quebec|québec)\b|"
    r"\b(?:geonb|new brunswick) agricultural soil classes\b|"
    r"\bnewfoundland and labrador weather station climate monitoring data\b)",
    re.IGNORECASE,
)
_REGIONAL_PRODUCT_PRESCRIPTION_RE = re.compile(
    r"\b(?:prescrib|recommend|apply|application|spray|fungicide|herbicide|insecticide|pesticide|"
    r"exact (?:rate|timing|depth|date|interval)|irrigation (?:depth|timing|schedule)|"
    r"prescri|recommand|appliqu|pulvéris|fongicide|herbicide|insecticide|pesticide|"
    r"(?:taux|dose|moment|profondeur|date|délai) exact)\w*\b",
    re.IGNORECASE,
)
_REGIONAL_PRODUCT_BOUNDARY_QUESTION_RE = re.compile(
    r"\b(?:not|isn't|is not|cannot|can't|why is it not|without)\b.{0,80}"
    r"\b(?:prescription|recommendation|field measurement|field truth|observations? of every plant)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceHandshake:
    decision: str
    preserve_entities: tuple[str, ...]
    required_entities: tuple[str, ...]
    primary_doc_id: str | None
    primary_title: str | None
    supporting_doc_ids: tuple[str, ...]
    decisive_terms: tuple[str, ...]
    primary_query_coverage: float
    primary_relevance_score: float
    evidence_roles: tuple[tuple[str, str, str], ...] = ()
    authority_profiles: tuple[tuple[str, str, str, str], ...] = ()

    @property
    def has_strong_primary(self) -> bool:
        return bool(
            self.primary_doc_id
            and (
                self.primary_query_coverage >= 0.25
                or (
                    self.primary_query_coverage >= 0.16
                    and self.primary_relevance_score >= _STRONG_PRIMARY_MIN_SCORE
                )
            )
        )

    @property
    def primary_field_action_authority(self) -> str:
        if not self.primary_doc_id:
            return "not_authorized"
        return self.authority_for(self.primary_doc_id)[1]

    @property
    def has_field_action_primary(self) -> bool:
        """Whether the strong primary may support an action within its scope.

        An interpretive regional product can be a strong primary for explaining
        that product while remaining explicitly unauthorized for a field action.
        Consumers must use this property, rather than ``has_strong_primary``,
        when the requested conclusion changes management.
        """

        return bool(
            self.has_strong_primary
            and self.primary_field_action_authority == "bounded_source_support"
        )

    @property
    def commit_check_enabled(self) -> bool:
        return self.has_strong_primary and len(self.decisive_terms) >= 4

    def answer_alignment(self, answer: str) -> float | None:
        if not self.commit_check_enabled:
            return None
        answer_tokens = set(tokenize(answer))
        hits = sum(_phrase_is_covered(term, answer, answer_tokens) for term in self.decisive_terms)
        return round(hits / len(self.decisive_terms), 4)

    def missing_decisive_terms(self, answer: str, *, limit: int = 5) -> tuple[str, ...]:
        if not self.primary_doc_id or not self.decisive_terms:
            return ()
        answer_tokens = set(tokenize(answer))
        return tuple(
            term
            for term in self.decisive_terms
            if not _phrase_is_covered(term, answer, answer_tokens)
        )[:limit]

    def role_for(self, doc_id: str) -> str:
        return next((role for candidate, role, _ in self.evidence_roles if candidate == doc_id), "supporting")

    def authority_for(self, doc_id: str) -> tuple[str, str, str]:
        return next(
            (
                (factual_authority, action_authority, reason)
                for candidate, factual_authority, action_authority, reason in self.authority_profiles
                if candidate == doc_id
            ),
            ("supporting_context", "not_authorized", "authority_profile_not_captured"),
        )

    @property
    def distractor_doc_ids(self) -> tuple[str, ...]:
        return tuple(doc_id for doc_id, role, _ in self.evidence_roles if role == "distractor")

    def prompt_block(self) -> str:
        entities = ", ".join(self.preserve_entities) or "the named crop, problem, and operation"
        primary = (
            f"[{self.primary_doc_id}] {self.primary_title}"
            if self.primary_doc_id and self.primary_title
            else "none; hold unsupported factual commitments"
        )
        supporting = ", ".join(f"[{doc_id}]" for doc_id in self.supporting_doc_ids) or "none"
        roles = "; ".join(
            f"[{doc_id}]={role} ({reason})" for doc_id, role, reason in self.evidence_roles
        ) or "none"
        authorities = "; ".join(
            f"[{doc_id}]=meaning:{factual}; field-action:{action} ({reason})"
            for doc_id, factual, action, reason in self.authority_profiles
        ) or "none"
        return (
            "Compact evidence handshake:\n"
            f"- Decision: {self.decision}\n"
            f"- Preserve: {entities}.\n"
            f"- Primary decision evidence: {primary}. Supporting or boundary evidence: {supporting}.\n"
            f"- Evidence roles: {roles}.\n"
            f"- Authority axes: {authorities}.\n"
            "- Commit rule: answer the named decision first; use primary evidence for agronomic logic, use boundary evidence only to constrain it, "
            "and do not switch crop, problem, or operation. If primary evidence does not support the decision, state the hold explicitly."
        )


def rerank_evidence_docs(
    question: str,
    docs: Iterable[RetrievedDoc],
    *,
    crops: Iterable[str] = (),
    pest_entities: Iterable[str] = (),
    topics: Iterable[str] = (),
    route_namespaces: Iterable[str] = (),
    raw_query_ranks: Mapping[str, int] | None = None,
    required_entities: Iterable[str] = (),
    jurisdictions: Iterable[str] = (),
    decision_contract: AgronomyDecisionContract | None = None,
) -> tuple[RetrievedDoc, ...]:
    """Rank a merged candidate set by raw question/entity fit.

    The upstream retriever score remains a weak tie-breaker. This keeps the raw
    question as the stable retrieval surface while route expansion contributes
    candidates rather than silently redefining the user's decision.
    """

    question_tokens = set(tokenize(question))
    entities = tuple(_ordered_unique((*crops, *pest_entities)))
    required = tuple(_ordered_unique(required_entities))
    jurisdiction_set = {
        str(value).strip().casefold() for value in jurisdictions if str(value).strip()
    }
    topic_set = {str(value).strip().lower() for value in topics if str(value).strip()}
    namespace_set = {str(value).strip().lower() for value in route_namespaces if str(value).strip()}
    capsule = build_decision_route_state(question).capsule
    unique: dict[str, RetrievedDoc] = {}
    for doc in docs:
        existing = unique.get(doc.doc_id)
        if existing is None or float(doc.score) > float(existing.score):
            unique[doc.doc_id] = doc

    scored: list[tuple[float, int, RetrievedDoc]] = []
    for index, doc in enumerate(unique.values()):
        title_tags = " ".join((doc.title, *doc.tags)).lower()
        full_text = " ".join((doc.title, doc.text, *doc.tags)).lower()
        title_tokens = set(tokenize(title_tags))
        doc_tokens = set(doc.token_set) if doc.token_set else set(tokenize(full_text))
        meaningful_question = {token for token in question_tokens if token not in _NON_DECISION_TOKENS}
        denominator = max(1, len(meaningful_question))
        title_coverage = len(meaningful_question & title_tokens) / denominator
        text_coverage = len(meaningful_question & doc_tokens) / denominator
        exact_entities = sum(bool(re.search(rf"\b{re.escape(entity.lower())}\b", full_text)) for entity in entities)
        required_matches = sum(
            bool(re.search(rf"\b{re.escape(entity.lower())}\b", full_text)) for entity in required
        )
        required_misses = len(required) - required_matches
        namespace_overlap = len(namespace_set & set(doc.namespaces))
        topic_overlap = sum(topic in full_text for topic in topic_set)
        normalized_title_tags = _phrase_normalized_text(title_tags)
        phrase_bonus = sum(1 for phrase in _question_phrases(question) if phrase in normalized_title_tags)
        boundary_route = bool(namespace_set & {"label_boundary", "field_data_boundary"})
        if doc.source_type == "boundary" and boundary_route:
            source_bonus = 1.0
        elif doc.source_type == "applied_guidance":
            source_bonus = 0.8
        else:
            source_bonus = 0.2
        authority_bonus = 0.35 if re.search(r"(?:extension|university|\.edu|\.gov|canolacouncil)", doc.source, re.I) else 0.0
        original_score = min(2.0, max(0.0, float(doc.score))) * 0.15
        raw_rank = int((raw_query_ranks or {}).get(doc.doc_id, 0))
        raw_query_bonus = 2.4 / raw_rank if raw_rank > 0 else 0.0
        capsule_bonus = capsule.evidence_alignment(full_text) if capsule is not None else 0.0
        obligation_matches = (
            obligation_coverage(doc, decision_contract)
            if decision_contract is not None
            else ()
        )
        doc_jurisdictions = {
            str(value).strip().casefold()
            for value in doc.jurisdictions
            if str(value).strip()
        }
        jurisdiction_bonus = 0.0
        if jurisdiction_set and doc_jurisdictions:
            if jurisdiction_set & doc_jurisdictions:
                jurisdiction_bonus = 1.5
            elif doc_jurisdictions <= {"canada", "canadian", "federal"}:
                jurisdiction_bonus = 0.35
            else:
                jurisdiction_bonus = -1.5
        doc_crops = {str(value).strip().casefold() for value in doc.crops if str(value).strip()}
        crop_set = {str(value).strip().casefold() for value in crops if str(value).strip()}
        crop_scope_bonus = 0.0
        if crop_set and doc_crops:
            crop_scope_bonus = 1.0 if crop_set & doc_crops else -1.0
        currency = str(doc.currency_status or "unspecified").strip().casefold()
        if any(token in currency for token in ("stale", "historical", "expired")):
            currency_bonus = -1.25
        elif any(token in currency for token in ("current", "maintained", "active")):
            currency_bonus = 0.6
        else:
            currency_bonus = 0.0
        policy = str(doc.retrieval_policy or "standard").strip().casefold()
        authority_fit_bonus = 0.0
        if obligation_matches:
            if policy == "standard" and doc.source_type == "applied_guidance":
                authority_fit_bonus = 0.75
            elif policy == "context_only":
                authority_fit_bonus = -0.5
        score = (
            5.0 * title_coverage
            + 2.5 * text_coverage
            + 1.25 * exact_entities
            + 1.75 * required_matches
            - 2.0 * required_misses
            + 0.35 * namespace_overlap
            + 0.2 * topic_overlap
            + 0.45 * phrase_bonus
            + source_bonus
            + authority_bonus
            + original_score
            + raw_query_bonus
            + capsule_bonus
            + 1.6 * len(obligation_matches)
            + jurisdiction_bonus
            + crop_scope_bonus
            + currency_bonus
            + authority_fit_bonus
        )
        scored.append((score, -index, replace(doc, score=round(score, 6))))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return tuple(item[2] for item in scored)


def filter_decision_distractors(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> tuple[tuple[RetrievedDoc, ...], tuple[dict[str, str], ...]]:
    """Remove documents whose semantic role conflicts with the active decision."""

    state = build_decision_route_state(question)
    kept: list[RetrievedDoc] = []
    dropped: list[dict[str, str]] = []
    for doc in docs:
        role, reason = _classify_evidence_role(state, doc)
        if role == "distractor":
            dropped.append({"doc_id": doc.doc_id, "reason": reason})
        else:
            kept.append(doc)
    return tuple(kept), tuple(dropped)


def build_evidence_handshake(
    question: str,
    docs: Iterable[RetrievedDoc],
    *,
    preserve_entities: Iterable[str] = (),
    required_entities: Iterable[str] = (),
) -> EvidenceHandshake:
    ordered = tuple(docs)
    decision_state = build_decision_route_state(question)
    classified = tuple((doc, *_classify_evidence_role(decision_state, doc)) for doc in ordered)
    route_requires_decisive = bool(decision_state.premise_anchors) or decision_state.decision in _DECISIVE_EVIDENCE_REQUIRED
    candidate_match = next(
        (
            (doc, reason)
            for doc, role, reason in classified
            if role in {"decisive", "interpretive"}
            and (
                doc.source_type not in _BOUNDARY_TYPES
                or reason == "named_regional_product_interpretation"
            )
        ),
        None,
    )
    candidate = candidate_match[0] if candidate_match is not None else None
    candidate_reason = candidate_match[1] if candidate_match is not None else ""
    if candidate is None and not route_requires_decisive:
        candidate = next(
            (
                doc
                for doc, role, _ in classified
                if role not in {"boundary", "distractor"} and doc.source_type not in _BOUNDARY_TYPES
            ),
            None,
        )
        candidate_reason = "fallback_non_boundary"
    decision = _decision_clause(question)
    entities = tuple(_ordered_unique(str(value).strip().lower() for value in preserve_entities if str(value).strip()))
    required = tuple(_ordered_unique(str(value).strip().lower() for value in required_entities if str(value).strip()))
    coverage = _query_coverage(question, candidate) if candidate is not None else 0.0
    relevance_score = float(candidate.score) if candidate is not None else 0.0
    entity_fit = candidate is not None and _required_entities_present(candidate, required)
    primary = candidate if entity_fit and (
        candidate_reason == "named_regional_product_interpretation"
        or coverage >= 0.25
        or (coverage >= 0.16 and relevance_score >= _STRONG_PRIMARY_MIN_SCORE)
    ) else None
    decisive_terms = _decisive_terms(question, primary) if primary is not None else ()
    evidence_roles = tuple(
        (
            doc.doc_id,
            (
                "interpretive"
                if primary is not None and doc.doc_id == primary.doc_id and role == "interpretive"
                else "decisive"
                if primary is not None and doc.doc_id == primary.doc_id
                else role
            ),
            (
                "selected_primary_source_interpretation"
                if primary is not None and doc.doc_id == primary.doc_id and role == "interpretive"
                else "selected_primary"
                if primary is not None and doc.doc_id == primary.doc_id
                else reason
            ),
        )
        for doc, role, reason in classified
    )
    roles_by_doc_id = {doc_id: (role, reason) for doc_id, role, reason in evidence_roles}
    authority_profiles = tuple(
        (
            doc.doc_id,
            profile.factual_interpretation_authority,
            profile.field_action_authority,
            profile.reason,
        )
        for doc, _role, _reason in classified
        for role, reason in (roles_by_doc_id[doc.doc_id],)
        for profile in (classify_evidence_authority(doc, evidence_role=role, evidence_reason=reason),)
    )
    supporting = tuple(
        doc.doc_id
        for doc, role, _ in classified
        if (primary is None or doc.doc_id != primary.doc_id) and role != "distractor"
    )[:3]
    return EvidenceHandshake(
        decision=decision,
        preserve_entities=entities,
        required_entities=required,
        primary_doc_id=primary.doc_id if primary else None,
        primary_title=primary.title if primary else None,
        supporting_doc_ids=supporting,
        decisive_terms=decisive_terms,
        primary_query_coverage=round(coverage, 4),
        primary_relevance_score=round(relevance_score, 4),
        evidence_roles=evidence_roles,
        authority_profiles=authority_profiles,
    )


def evidence_grounded_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
    *,
    preserve_entities: Iterable[str] = (),
    required_entities: Iterable[str] = (),
    max_words: int = 190,
) -> str | None:
    """Return the primary reviewed guidance when generation cannot be trusted."""

    ordered = tuple(docs)
    state = build_evidence_handshake(
        question,
        ordered,
        preserve_entities=preserve_entities,
        required_entities=required_entities,
    )
    if not state.has_strong_primary or not state.primary_doc_id:
        return None
    primary = next((doc for doc in ordered if doc.doc_id == state.primary_doc_id), None)
    if primary is None or primary.source_type in _BOUNDARY_TYPES:
        return None
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", primary.text.strip()) if part.strip()]
    if not sentences:
        return None
    selected: list[str] = []
    words = 0
    for sentence in sentences:
        sentence_words = len(sentence.split())
        if selected and words + sentence_words > max_words:
            break
        selected.append(sentence)
        words += sentence_words
    if not selected:
        return None
    midpoint = max(1, min(len(selected) - 1, round(len(selected) * 0.55))) if len(selected) > 1 else 1
    if len(selected) == 1:
        return selected[0]
    return " ".join(selected[:midpoint]) + "\n\n" + " ".join(selected[midpoint:])


def _classify_evidence_role(
    state: DecisionRouteState,
    doc: RetrievedDoc,
) -> tuple[str, str]:
    retrieval_policy = str(doc.retrieval_policy or "standard").strip().lower()
    if retrieval_policy == "requires_live_authority":
        return "boundary", "live_authority_not_decisive"
    if retrieval_policy == "context_only":
        if _is_named_regional_product_interpretation(state, doc):
            return "interpretive", "named_regional_product_interpretation"
        return "boundary", "context_only_not_decisive"

    if doc.source_type in _BOUNDARY_TYPES:
        if _is_named_regional_product_interpretation(state, doc):
            return "interpretive", "named_regional_product_interpretation"
        return "boundary", "source_type_boundary"

    identifier = " ".join((doc.doc_id, doc.title, *doc.tags)).lower()
    text = " ".join((identifier, doc.text)).lower()
    decision = state.decision
    if decision == "openet_irrigation_decision":
        if re.search(r"\b(?:openet|satellite|evapotranspiration|crop water use)\b", text):
            return "decisive", "satellite_et_context"
        if re.search(r"\b(?:probe|sensor|root[- ]zone|field capacity|applied water|flowmeter)\b", text):
            return "supporting", "field_water_measurement"
    elif decision == "irrigation_water_nitrate_credit":
        if re.search(r"\b(?:forage|graz|prussic|hydrocyanic|livestock)\b", text):
            return "distractor", "forage_hazard_not_water_credit"
        if re.search(r"\bnitrate\b", text) and re.search(
            r"\b(?:irrigation|well[- ]?water|applied water|flowmeter|nitrogen credit)\b", text
        ):
            return "decisive", "irrigation_water_nitrate_credit"
    elif decision == "drip_irrigation_uniformity":
        if re.search(r"\b(?:drip|lateral|emitter|pressure|flow|plugging|distribution uniformity)\b", text):
            return "decisive", "drip_hydraulic_delivery"
        if re.search(r"\b(?:salinity|water quality|root[- ]zone|food safety|harvest)\b", text):
            return "supporting", "root_zone_or_harvest_constraint"
    elif decision == "tile_drainage_decision":
        if re.search(r"\b(?:tile|drainage|water table|outlet|poorly drained|saturation)\b", text):
            return "decisive", "drainage_mechanism_or_design"
        if re.search(r"\b(?:openet|evapotranspiration|irrigation prescription|crop water use)\b", text):
            return "distractor", "atmospheric_water_demand_not_drainage_design"
        if re.search(r"\b(?:soil survey|map unit|topography|wetland)\b", text):
            return "supporting", "screening_or_boundary_context"
    elif decision == "spray_weather_window":
        if re.search(r"\b(?:wind|gust|drift|inversion|rainfast|sensitive area|shelterbelt|product label)\b", text):
            return "decisive", "application_weather_and_label"
        if re.search(r"\b(?:tank mix|adjuvant|nozzle|recordkeeping|weather)\b", text):
            return "supporting", "application_support"
    elif decision == "forage_defoliator_harvest_decision":
        if re.search(r"\b(?:economic threshold|action threshold|beneficial|natural enemies|representative sampling)\b", text):
            return "decisive", "pest_pressure_threshold_and_beneficials"
        if re.search(r"\b(?:preharvest|PHI|cutting|harvest|forage stage|drought stress)\b", text, re.IGNORECASE):
            return "supporting", "harvest_timing_and_crop_stress"
    elif decision == "high_tunnel_yellowing":
        if re.search(r"\b(?:high[- ]tunnel|specialty crop)\b", text) and re.search(
            r"\b(?:fertigation|injector|emitter|root[- ]zone|EC|salinity)\b", text, re.IGNORECASE
        ):
            return "decisive", "integrated_high_tunnel_diagnosis"
        if re.search(r"\b(?:salinity|EC|irrigation uniformity|root[- ]zone moisture|soil test|tissue test)\b", text, re.IGNORECASE):
            return "supporting", "water_salt_or_nutrient_evidence"
    elif decision == "weed_preharvest_escape":
        if re.search(r"\b(?:preharvest|phi|harvest aid|residue|buyer|crop and target|current label)\b", text):
            return "decisive", "near_harvest_label_and_market_fit"
        if re.search(r"\b(?:seed return|resistance|mode of action|integrated weed)\b", text):
            return "supporting", "seed_return_or_next_cycle"
    elif decision == "water_limited_nitrogen_increase":
        if "manure" not in state.question.lower() and re.search(r"\bmanure\b", identifier):
            return "distractor", "unstated_manure_credit"
        if re.search(r"\b(?:forage|feed safety|prussic|hydrocyanic|livestock)\b", identifier):
            return "distractor", "forage_hazard_not_crop_nitrogen_response"
        crop_match = bool(state.crop and re.search(rf"\b{re.escape(state.crop)}\b", text))
        nitrogen_match = bool(re.search(r"\b(?:nitrogen|nitrate|UAN|N response)\b", text, re.IGNORECASE))
        water_match = bool(re.search(
            r"\b(?:drought|dryland|water[- ]limit|limited (?:irrigation )?water|irrigation capacity|water allocation|salinity)\b",
            text,
        ))
        if crop_match and nitrogen_match and water_match:
            return "decisive", "crop_specific_water_limited_nitrogen_response"
        if nitrogen_match:
            return "supporting", "general_nitrogen_context"
    elif decision == "fungicide_decision":
        if re.search(r"\b(?:freeze|frost|subfreezing)\b", identifier) and not re.search(
            r"\b(?:freeze|frost|subfreezing)\b", state.question, re.IGNORECASE
        ):
            return "distractor", "freeze_recovery_not_fungicide_decision"
        if re.search(r"\b(?:insect|aphid|economic threshold|weed|herbicide resistance)\b", identifier):
            return "distractor", "pest_or_weed_decision_not_fungicide_decision"
        disease_evidence = bool(
            re.search(
                r"\b(?:diagnos|disease (?:incidence|severity|pressure)|leaf wetness|hybrid susceptibility|"
                r"variety susceptibility|fusarium|rust|blight|mildew|mold|fungal disease)\b",
                text,
            )
        )
        fungicide_evidence = bool(re.search(r"\bfungicide\b", text))
        if disease_evidence and fungicide_evidence:
            return "decisive", "disease_risk_and_fungicide_fit"
        if re.search(
            r"\b(?:current label|rainfast|wind|drift|inversion|buffer|preharvest interval|restricted entry)\b",
            text,
        ):
            return "supporting", "application_or_label_constraint"

    if state.capsule is not None:
        capsule_role = state.capsule.classify_evidence(text)
        if capsule_role is not None:
            return capsule_role

    return "supporting", "general_support"


def _is_named_regional_product_interpretation(
    state: DecisionRouteState,
    doc: RetrievedDoc,
) -> bool:
    """Let a named context-only specification decide product meaning, never a field prescription."""

    if doc.source_type not in {"regional_environment_profile", "regional_environment"}:
        return False
    if not _NAMED_CANADIAN_REGIONAL_PRODUCT_RE.search(state.question):
        return False
    if _REGIONAL_PRODUCT_PRESCRIPTION_RE.search(state.question) and not _REGIONAL_PRODUCT_BOUNDARY_QUESTION_RE.search(state.question):
        return False
    identity = " ".join((doc.source_id, doc.doc_id, doc.title, doc.source)).lower()
    crop_health_product = bool(
        "ca_aafc_crop_health_indices_specification" in identity
        or (
            re.search(r"\b(?:agriculture and agri-food canada|aafc)\b", identity, re.IGNORECASE)
            and re.search(r"\bcrop health indices?\b", identity, re.IGNORECASE)
        )
    )
    detailed_soil_product = bool(
        re.search(r"ca_aafc_(?:bc|ns|pei)_detailed_soil_survey_specification", identity)
        or "ca_aafc_qc_agropedological_atlas_specification" in identity
        or "nb_geonb_agricultural_soil_classes" in identity
        or "nl_historical_weather_station_climate_metadata" in identity
        or re.search(
            r"\b(?:british columbia|nova scotia|prince edward island) detailed soil survey\b|"
            r"\bagro[- ]pedological atlas of (?:quebec|québec)\b|"
            r"\bnew brunswick agricultural soil classes\b|"
            r"\bnewfoundland and labrador weather station climate monitoring data\b",
            identity,
            re.IGNORECASE,
        )
    )
    return crop_health_product or detailed_soil_product


def _query_coverage(question: str, doc: RetrievedDoc) -> float:
    question_tokens = {
        token
        for token in tokenize(question)
        if token not in _NON_DECISION_TOKENS
    }
    if not question_tokens:
        return 0.0
    title_text = " ".join((doc.title, *doc.tags))
    title_tags = set(tokenize(title_text)) | set(tokenize(title_text.replace("-", " ")))
    text_tokens = set(doc.token_set) if doc.token_set else set(tokenize(doc.text))
    text_tokens.update(tokenize(doc.text.replace("-", " ")))
    normalized_title = _phrase_normalized_text(title_text)
    phrase_hits = sum(phrase in normalized_title for phrase in _question_phrases(question))
    weighted_hits = (
        2 * len(question_tokens & title_tags)
        + len(question_tokens & text_tokens)
        + min(2, phrase_hits)
    )
    coverage = min(1.0, weighted_hits / (3 * len(question_tokens)))
    if phrase_hits:
        coverage = max(0.4, coverage)
    return coverage


def _decisive_terms(question: str, doc: RetrievedDoc) -> tuple[str, ...]:
    question_lower = " ".join(question.lower().split())
    candidates: list[str] = []
    for raw in doc.tags:
        term = " ".join(str(raw).lower().replace("-", " ").split())
        tokens = tokenize(term)
        if not term or term in _GENERIC_TAGS or term in _CROP_ENTITY_TAGS or not 1 <= len(tokens) <= 5:
            continue
        if term in question_lower:
            continue
        if not all(token in set(tokenize(f"{doc.title} {doc.text}")) for token in tokens):
            continue
        candidates.append(term)
    candidates.sort(key=lambda term: (len(tokenize(term)) > 1, len(term)), reverse=True)
    return tuple(_ordered_unique(candidates))[:10]


def _required_entities_present(doc: RetrievedDoc, required_entities: tuple[str, ...]) -> bool:
    if not required_entities:
        return True
    haystack = " ".join((doc.title, *doc.tags)).lower().replace("-", " ")
    return all(
        re.search(rf"\b{re.escape(entity.lower().replace('-', ' '))}s?\b", haystack)
        for entity in required_entities
    )


def _decision_clause(question: str) -> str:
    text = " ".join(question.split())
    final = re.split(r"(?<=[.!?])\s+", text)[-1]
    if len(final.split()) >= 5:
        return final[:240]
    return text[:240]


def _question_phrases(question: str) -> tuple[str, ...]:
    tokens = [_phrase_token(token) for token in tokenize(question.replace("-", " "))]
    return tuple(
        " ".join(tokens[index : index + 2])
        for index in range(max(0, len(tokens) - 1))
        if not all(token in _PHRASE_ANCHOR_STOPWORDS for token in tokens[index : index + 2])
    )


def _phrase_normalized_text(text: str) -> str:
    return " ".join(_phrase_token(token) for token in tokenize(text.replace("-", " ")))


def _phrase_token(token: str) -> str:
    if len(token) > 5 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _phrase_is_covered(term: str, answer: str, answer_tokens: set[str]) -> bool:
    normalized = _fidelity_normalized_text(term)
    normalized_answer = _fidelity_normalized_text(answer)
    if normalized in normalized_answer:
        return True
    if normalized == "0 to 100 stress bands" and all(
        band in normalized_answer
        for band in ("0 25", "26 50", "51 75", "76 100")
    ):
        return True
    tokens = set(tokenize(normalized))
    normalized_answer_tokens = set(tokenize(normalized_answer))
    return bool(tokens) and (tokens <= answer_tokens or tokens <= normalized_answer_tokens)


def _fidelity_normalized_text(text: str) -> str:
    normalized = str(text).lower().replace(",", "")
    normalized = re.sub(r"(?<=\d)\s*:\s*(?=\d)", " to ", normalized)
    return " ".join(normalized.replace("-", " ").split())


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered
