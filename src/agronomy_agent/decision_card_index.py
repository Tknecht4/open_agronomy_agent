"""Decision Card retrieval using the existing portable lexical index.

The frozen V1 pilot showed that a bespoke contract-weighted reranker degraded
retrieval.  This module therefore keeps the established lexical ranking and
uses the Decision Contract only after retrieval, where it belongs: to expose
missing evidence, current-authority dependencies, and the hard advisory gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from agronomy_agent.agno_runtime.local_index import LexicalRetriever
from agronomy_agent.decision_cards import (
    CardMatch,
    DecisionCard,
    DecisionCardMatchResult,
)
from agronomy_agent.decision_contract import AgronomyDecisionContract


POLICY_ID = "open_agronomy_agent.decision_card_lexical_index.v1"

_NAMED_AUTHORITIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("statistics_canada", re.compile(r"\b(?:statistics canada|statcan)\b", re.I)),
    (
        "aafc",
        re.compile(
            r"\b(?:AAFC|Agriculture and Agri-Food Canada|Agriculture Canada)\b",
            re.I,
        ),
    ),
    ("pmra", re.compile(r"\b(?:PMRA|pesticide label|product label)\b", re.I)),
    ("nrcb", re.compile(r"\b(?:NRCB|Natural Resources Conservation Board)\b", re.I)),
)
_CURRENT_AUTHORITY_OBLIGATIONS = {
    "current_weather",
    "regulated_product_authority",
}


def _flat_doc(card: DecisionCard) -> dict[str, Any]:
    return {
        "doc_id": card.card_id,
        "title": card.title,
        "text": " ".join(card.supported_claims),
        "tags": [
            *card.applicability_terms,
            *card.decision_families,
            *card.required_observations,
        ],
        "source_id": card.source_id,
        "jurisdiction": list(card.jurisdictions),
        "language": list(card.languages),
        "retrieval_policy": card.retrieval_policy,
    }


def _authority_match(
    authority: str,
    card: DecisionCard,
) -> bool:
    identity = " ".join(
        (
            card.source_id,
            str(card.raw.get("source", {}).get("publisher", "")),
            " ".join(card.live_authority_dependencies),
        )
    ).lower()
    if authority == "statistics_canada":
        return "statistics canada" in identity or "statcan" in identity
    if authority == "aafc":
        return "aafc" in identity or "agriculture and agri-food canada" in identity
    if authority == "pmra":
        return "pmra" in identity and card.advisory_authority
    if authority == "nrcb":
        return "nrcb" in identity or "natural resources conservation board" in identity
    return False


@dataclass(frozen=True)
class DecisionCardIndex:
    """Pure-local card index plus a non-promotable authority gate."""

    cards: tuple[DecisionCard, ...]
    retriever: LexicalRetriever

    @classmethod
    def build(
        cls,
        cards: Sequence[DecisionCard | Mapping[str, Any]],
    ) -> "DecisionCardIndex":
        normalized = tuple(
            card if isinstance(card, DecisionCard) else DecisionCard.from_mapping(card)
            for card in cards
        )
        return cls(
            cards=normalized,
            retriever=LexicalRetriever(_flat_doc(card) for card in normalized),
        )

    def search(
        self,
        question: str,
        contract: AgronomyDecisionContract,
        *,
        top_k: int = 5,
        query_expansion: Sequence[str] = (),
    ) -> DecisionCardMatchResult:
        by_id = {card.card_id: card for card in self.cards}
        jurisdictions = tuple(
            dict.fromkeys((*contract.jurisdiction_scope, "Canada"))
        )
        hits = self.retriever.search(
            question,
            top_k=top_k,
            query_expansion=query_expansion,
            jurisdictions=jurisdictions or None,
            strict_jurisdictions=bool(contract.jurisdiction_scope),
        )
        required = tuple(
            obligation.key for obligation in contract.evidence_obligations
        )
        required_set = set(required)
        matches: list[CardMatch] = []
        for hit in hits:
            card = by_id[hit.doc_id]
            covered = tuple(
                key for key in required if key in set(card.decision_families)
            )
            matches.append(
                CardMatch(
                    card_id=card.card_id,
                    source_id=card.source_id,
                    score=float(hit.score),
                    lexical_score=float(hit.score),
                    contract_score=(
                        len(covered) / len(required) if required else 0.0
                    ),
                    jurisdiction_score=(
                        1.0
                        if set(value.lower() for value in contract.jurisdiction_scope)
                        & set(value.lower() for value in card.jurisdictions)
                        else 0.65
                        if "Canada" in card.jurisdictions
                        else 0.0
                    ),
                    obligations_covered=covered,
                    review_status=card.review_status,
                    retrieval_policy=card.retrieval_policy,
                    advisory_authority=card.advisory_authority,
                )
            )

        named = [
            name for name, pattern in _NAMED_AUTHORITIES if pattern.search(question)
        ]
        authority_identity_match = all(
            any(_authority_match(name, by_id[match.card_id]) for match in matches)
            for name in named
        )
        covered = tuple(
            dict.fromkeys(
                key for match in matches for key in match.obligations_covered
            )
        )
        missing = tuple(key for key in required if key not in set(covered))
        has_obligation_match = not required_set or bool(set(covered) & required_set)
        evidence_match = bool(matches) and authority_identity_match and has_obligation_match
        evidence_sufficient = evidence_match and not missing

        current_authority_required = bool(
            required_set & _CURRENT_AUTHORITY_OBLIGATIONS
        )
        authority_available = bool(
            evidence_sufficient
            and any(
                match.advisory_authority
                and match.review_status == "independently_reviewed"
                and match.retrieval_policy != "context_only"
                for match in matches
            )
        )
        if current_authority_required and not authority_available:
            disposition = "current_authority_required"
        elif named and not authority_identity_match:
            disposition = "named_authority_not_in_card_set"
        elif not evidence_match:
            disposition = "no_card_match"
        elif not evidence_sufficient:
            disposition = "collect_missing_evidence"
        elif not authority_available:
            disposition = "context_only"
        else:
            disposition = "conditional_advice"
        return DecisionCardMatchResult(
            policy_id=POLICY_ID,
            matches=tuple(matches),
            obligations_required=required,
            obligations_covered=covered,
            obligations_missing=missing,
            evidence_match=evidence_match,
            evidence_sufficient=evidence_sufficient,
            advisory_authority_available=authority_available,
            disposition=disposition,
        )
