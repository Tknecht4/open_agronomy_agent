"""Portable, deterministic matching for quarantined agronomy Decision Cards.

Decision Cards are an evidence representation, not a shortcut around source
review.  The matcher may identify relevant cards and missing evidence, but it
cannot promote a card or turn context-only evidence into advisory authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from agronomy_agent.decision_contract import AgronomyDecisionContract


SCHEMA_VERSION = "open_agronomy_agent.decision_card.v1"
MATCHER_POLICY_ID = "open_agronomy_agent.decision_card_matcher.v1"

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:[-/][A-Za-zÀ-ÿ0-9]+)*")
_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "before",
    "could",
    "does",
    "field",
    "from",
    "have",
    "into",
    "need",
    "should",
    "that",
    "the",
    "their",
    "there",
    "this",
    "using",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}
_NORMALIZE = {
    "fertiliser": "fertilizer",
    "fertilisation": "fertilization",
    "manures": "manure",
    "meters": "metre",
    "metres": "metre",
    "pesticides": "pesticide",
    "saline": "salinity",
    "sulphur": "sulfur",
    "watercourse": "water",
    "watercourses": "water",
}
_QUERY_EXPANSIONS = {
    "bugs": ("insect", "pest"),
    "crop-map": ("annual", "crop", "inventory", "classification"),
    "disease": ("scouting", "plant_health"),
    "frozen": ("winter", "snow"),
    "growth": ("development", "stage"),
    "map": ("mapped", "regional", "raster"),
    "moisture": ("soil_water", "weather"),
    "record": ("recordkeeping", "compliance"),
    "regulation": ("legal_freshness", "compliance"),
    "satellite": ("raster", "classification", "regional"),
    "spray": ("pesticide", "label", "product"),
}


def _tokens(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        token = _NORMALIZE.get(raw, raw)
        if len(token) < 2 or token in _STOPWORDS:
            continue
        values.append(token)
    return tuple(values)


def _expanded_query_tokens(text: str) -> tuple[str, ...]:
    values = list(_tokens(text))
    for token in tuple(values):
        values.extend(_QUERY_EXPANSIONS.get(token, ()))
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class DecisionCard:
    card_id: str
    card_kind: str
    title: str
    jurisdictions: tuple[str, ...]
    languages: tuple[str, ...]
    decision_families: tuple[str, ...]
    applicability_terms: tuple[str, ...]
    required_observations: tuple[str, ...]
    supported_claims: tuple[str, ...]
    prohibited_inferences: tuple[str, ...]
    live_authority_dependencies: tuple[str, ...]
    source_id: str
    source_pages: tuple[int, ...]
    review_status: str
    retrieval_policy: str
    advisory_authority: bool
    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DecisionCard":
        source = payload.get("source", {})
        review = payload.get("review", {})
        runtime = payload.get("runtime", {})
        return cls(
            card_id=str(payload["card_id"]),
            card_kind=str(payload["card_kind"]),
            title=str(payload["title"]),
            jurisdictions=tuple(str(value) for value in payload["jurisdictions"]),
            languages=tuple(str(value) for value in payload["languages"]),
            decision_families=tuple(
                str(value) for value in payload["decision_families"]
            ),
            applicability_terms=tuple(
                str(value) for value in payload["applicability_terms"]
            ),
            required_observations=tuple(
                str(value) for value in payload["required_observations"]
            ),
            supported_claims=tuple(
                str(value) for value in payload["supported_claims"]
            ),
            prohibited_inferences=tuple(
                str(value) for value in payload["prohibited_inferences"]
            ),
            live_authority_dependencies=tuple(
                str(value) for value in payload["live_authority_dependencies"]
            ),
            source_id=str(source["source_id"]),
            source_pages=tuple(int(value) for value in source["source_pages"]),
            review_status=str(review["status"]),
            retrieval_policy=str(runtime["retrieval_policy"]),
            advisory_authority=bool(runtime["advisory_authority"]),
            raw=payload,
        )


@dataclass(frozen=True)
class CardMatch:
    card_id: str
    source_id: str
    score: float
    lexical_score: float
    contract_score: float
    jurisdiction_score: float
    obligations_covered: tuple[str, ...]
    review_status: str
    retrieval_policy: str
    advisory_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "source_id": self.source_id,
            "score": round(self.score, 8),
            "lexical_score": round(self.lexical_score, 8),
            "contract_score": round(self.contract_score, 8),
            "jurisdiction_score": round(self.jurisdiction_score, 8),
            "obligations_covered": list(self.obligations_covered),
            "review_status": self.review_status,
            "retrieval_policy": self.retrieval_policy,
            "advisory_authority": self.advisory_authority,
        }


@dataclass(frozen=True)
class DecisionCardMatchResult:
    policy_id: str
    matches: tuple[CardMatch, ...]
    obligations_required: tuple[str, ...]
    obligations_covered: tuple[str, ...]
    obligations_missing: tuple[str, ...]
    evidence_match: bool
    evidence_sufficient: bool
    advisory_authority_available: bool
    disposition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "matches": [match.to_dict() for match in self.matches],
            "obligations_required": list(self.obligations_required),
            "obligations_covered": list(self.obligations_covered),
            "obligations_missing": list(self.obligations_missing),
            "evidence_match": self.evidence_match,
            "evidence_sufficient": self.evidence_sufficient,
            "advisory_authority_available": self.advisory_authority_available,
            "disposition": self.disposition,
        }


def _weighted_card_tokens(card: DecisionCard) -> dict[str, float]:
    weights: dict[str, float] = {}

    def add(texts: Iterable[str], weight: float) -> None:
        for text in texts:
            for token in _tokens(text):
                weights[token] = max(weights.get(token, 0.0), weight)

    add((card.title,), 4.0)
    add(card.decision_families, 4.0)
    add(card.applicability_terms, 3.0)
    add(card.required_observations, 2.0)
    add(card.supported_claims, 1.0)
    add((card.source_id,), 1.5)
    return weights


def _lexical_score(question: str, card: DecisionCard) -> float:
    query = set(_expanded_query_tokens(question))
    if not query:
        return 0.0
    weights = _weighted_card_tokens(card)
    matched = sum(weights.get(token, 0.0) for token in query)
    normalizer = sum(4.0 if token in weights else 1.0 for token in query)
    return matched / max(normalizer, 1.0)


def _contract_score(
    contract: AgronomyDecisionContract,
    card: DecisionCard,
) -> tuple[float, tuple[str, ...]]:
    families = set(card.decision_families)
    application_tokens = set(_tokens(" ".join(card.applicability_terms)))
    covered: list[str] = []
    for obligation in contract.evidence_obligations:
        if obligation.key in families:
            covered.append(obligation.key)
            continue
        terms = set(_tokens(" ".join(obligation.retrieval_terms)))
        if terms and len(terms & application_tokens) / len(terms) >= 0.25:
            covered.append(obligation.key)
    required = len(contract.evidence_obligations)
    coverage = len(covered) / required if required else 0.0
    intent_overlap = len(set(contract.intent_set) & families) / max(
        len(set(contract.intent_set)), 1
    )
    return min(1.0, 0.75 * coverage + 0.25 * intent_overlap), tuple(covered)


def _jurisdiction_score(
    contract: AgronomyDecisionContract,
    card: DecisionCard,
) -> float:
    requested = {value.lower() for value in contract.jurisdiction_scope}
    if not requested:
        return 0.5
    card_values = {value.lower() for value in card.jurisdictions}
    if requested & card_values:
        return 1.0
    if "canada" in card_values:
        return 0.65
    return 0.0


def match_decision_cards(
    question: str,
    contract: AgronomyDecisionContract,
    cards: Sequence[DecisionCard | Mapping[str, Any]],
    *,
    top_k: int = 5,
    minimum_match_score: float = 0.18,
) -> DecisionCardMatchResult:
    """Rank cards and expose evidence sufficiency without granting authority."""

    normalized = [
        card if isinstance(card, DecisionCard) else DecisionCard.from_mapping(card)
        for card in cards
    ]
    ranked: list[CardMatch] = []
    for card in normalized:
        lexical = _lexical_score(question, card)
        contract_value, covered = _contract_score(contract, card)
        jurisdiction = _jurisdiction_score(contract, card)
        if jurisdiction == 0.0:
            score = 0.15 * lexical + 0.15 * contract_value
        else:
            score = 0.62 * lexical + 0.28 * contract_value + 0.10 * jurisdiction
        ranked.append(
            CardMatch(
                card_id=card.card_id,
                source_id=card.source_id,
                score=score,
                lexical_score=lexical,
                contract_score=contract_value,
                jurisdiction_score=jurisdiction,
                obligations_covered=covered,
                review_status=card.review_status,
                retrieval_policy=card.retrieval_policy,
                advisory_authority=card.advisory_authority,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.card_id))
    selected = tuple(ranked[: max(0, top_k)])
    evidence_match = bool(selected and selected[0].score >= minimum_match_score)
    required = tuple(obligation.key for obligation in contract.evidence_obligations)
    covered = tuple(
        dict.fromkeys(
            key
            for match in selected
            if match.score >= minimum_match_score
            for key in match.obligations_covered
        )
    )
    missing = tuple(key for key in required if key not in set(covered))
    evidence_sufficient = evidence_match and not missing
    authority = bool(
        evidence_sufficient
        and selected
        and any(
            match.advisory_authority
            and match.review_status == "independently_reviewed"
            and match.retrieval_policy != "context_only"
            for match in selected
        )
    )
    if not evidence_match:
        disposition = "no_card_match"
    elif not evidence_sufficient:
        disposition = "collect_missing_evidence"
    elif not authority:
        disposition = "context_only"
    else:
        disposition = "conditional_advice"
    return DecisionCardMatchResult(
        policy_id=MATCHER_POLICY_ID,
        matches=selected,
        obligations_required=required,
        obligations_covered=covered,
        obligations_missing=missing,
        evidence_match=evidence_match,
        evidence_sufficient=evidence_sufficient,
        advisory_authority_available=authority,
        disposition=disposition,
    )


def compactness_bytes(cards: Sequence[DecisionCard | Mapping[str, Any]]) -> int:
    """Approximate in-memory searchable text size without serialization coupling."""

    normalized = [
        card if isinstance(card, DecisionCard) else DecisionCard.from_mapping(card)
        for card in cards
    ]
    return sum(
        len(
            " ".join(
                (
                    card.title,
                    *card.decision_families,
                    *card.applicability_terms,
                    *card.required_observations,
                    *card.supported_claims,
                )
            ).encode("utf-8")
        )
        for card in normalized
    )


def reciprocal_rank(matches: Sequence[CardMatch], expected_card_ids: set[str]) -> float:
    for rank, match in enumerate(matches, start=1):
        if match.card_id in expected_card_ids:
            return 1.0 / rank
    return 0.0


def mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else 0.0
