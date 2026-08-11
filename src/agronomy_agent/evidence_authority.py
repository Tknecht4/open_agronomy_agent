"""Canonical two-axis authority classification for retrieved evidence.

The first axis answers whether a source can explain what the source itself
means.  The second answers whether it can support a current field action.  A
document may be authoritative on the first axis while explicitly unauthorized
on the second; keeping those judgments separate prevents regional products and
historical sources from being rendered as field prescriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_BOUNDARY_SOURCE_TYPES = {
    "boundary",
    "ontology",
    "regional_environment",
    "regional_environment_profile",
}


@dataclass(frozen=True)
class EvidenceAuthorityProfile:
    factual_interpretation_authority: str
    field_action_authority: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "factual_interpretation_authority": self.factual_interpretation_authority,
            "field_action_authority": self.field_action_authority,
            "reason": self.reason,
        }


def classify_evidence_authority(
    doc: Any,
    *,
    evidence_role: str = "supporting",
    evidence_reason: str = "",
) -> EvidenceAuthorityProfile:
    """Classify source-meaning authority separately from action authority."""

    policy = str(getattr(doc, "retrieval_policy", "standard") or "standard").strip().lower()
    source_type = str(getattr(doc, "source_type", "") or "").strip().lower()
    role = str(evidence_role or "supporting").strip().lower()
    reason = str(evidence_reason or "").strip().lower()
    currency = str(getattr(doc, "currency_status", "unspecified") or "unspecified").strip().lower()
    risks = {str(value).strip().lower() for value in getattr(doc, "content_risk_tags", ())}

    if policy == "requires_live_authority":
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="constraint_only",
            field_action_authority="requires_live_authority",
            reason="live_authority_required",
        )

    named_product_interpretation = (
        role == "interpretive"
        or reason in {
            "named_regional_product_interpretation",
            "selected_primary_source_interpretation",
        }
    )
    if named_product_interpretation:
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="authoritative_for_source_meaning",
            field_action_authority="not_authorized",
            reason="source_meaning_only_not_field_action",
        )

    if policy == "context_only":
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="supporting_context",
            field_action_authority="not_authorized",
            reason="context_only_not_current_action_authority",
        )

    if source_type in _BOUNDARY_SOURCE_TYPES or role == "boundary":
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="constraint_only",
            field_action_authority="not_authorized",
            reason="boundary_evidence_not_action_authority",
        )

    if any(token in currency for token in ("stale", "historical", "expired")):
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="supporting_context",
            field_action_authority="requires_live_authority",
            reason="source_currency_requires_current_validation",
        )

    if "pesticide_guidance_requires_current_pmra_label" in risks:
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="supporting_context",
            field_action_authority="requires_live_authority",
            reason="current_pmra_label_required",
        )

    if role == "decisive":
        return EvidenceAuthorityProfile(
            factual_interpretation_authority="authoritative_for_source_meaning",
            field_action_authority="bounded_source_support",
            reason="current_applied_source_within_recorded_scope",
        )

    return EvidenceAuthorityProfile(
        factual_interpretation_authority="supporting_context",
        field_action_authority="bounded_source_support",
        reason="supporting_applied_source_within_recorded_scope",
    )
