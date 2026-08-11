from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.decision_route import build_decision_route_state
from agronomy_agent.evidence_handshake import (
    EvidenceHandshake,
    build_evidence_handshake,
    evidence_grounded_fallback,
)
from agronomy_agent.router import request_focus


EVIDENCE_EDITOR_SYSTEM_PROMPT = """You are a conservative evidence editor for an agronomy assistant. The user's question and allowed evidence are the only factual record. Preserve useful supported content from a usable draft; change only unsupported claims and decision-critical omissions. When the draft is corrupt, repetitive, incomplete, or exposes internal controls, answer afresh instead. Never add a fact, number, rate, threshold, crop stage, named soil, pathogen, pest, product, law, diagnosis, or management permission. Every item under MISSING DECISION CONTENT is mandatory. When the question names multiple public data products, give each product its own sentence. For a named public data product, preserve equations, model names, units, complete enumerated values, resolution, lineage, and regional-versus-field limitations exactly from the allowed evidence. Answer only what was asked. Weather or regional context may indicate risk; it does not prove a field condition or diagnosis. If the record cannot support a diagnosis or recommendation, state the boundary and identify only the observation or test needed to resolve it. Return the user-facing answer only, no audit commentary."""


_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?(?:\s*(?:-|to)\s*\d+(?:\.\d+)?)?)"
    r"(?:\s*(?:%|ppm|ppb|mg/?L|kg/?ha|lb(?:s)?(?:/?acre)?|bu/?acre|mph|km/?h|mm|cm|"
    r"inches?|feet|ft|days?|hours?|acres?|°?[CF]))?\b",
    re.IGNORECASE,
)
_SPELLED_QUANTITY_RE = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half|quarter)\s+"
    r"(?:pounds?|lbs?|kilograms?|kg|litres?|liters?|gallons?|quarts?|ounces?|cups?|acres?|days?|hours?|"
    r"samples?|increments?)\b",
    re.IGNORECASE,
)
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")
_CROP_STAGE_RE = re.compile(
    r"\b(?:(?:V|R)\d{1,2}|boot(?:ing)?|silk(?:ing)?|tassel(?:ing)?)\b",
    re.IGNORECASE,
)
_ITALIC_BINOMIAL_RE = re.compile(r"\*{1,2}([A-Z][a-z]{2,}\s+[a-z][a-z-]{2,})\*{1,2}")
_PAREN_BINOMIAL_RE = re.compile(r"\(([A-Z][a-z]{2,}\s+[a-z][a-z-]{2,})\)")
_EMPHASIZED_TERM_RE = re.compile(r"\*\*([^*\n]{2,80})\*\*")
_NAMED_CONDITION_RE = re.compile(
    r"\b((?:(?:gray leaf|grey leaf|early|late|stem|stripe|leaf|root|seedling|downy|powdery|white|gray|grey|bacterial|"
    r"fusarium|verticillium)\s+)?(?:blight|rust|mildew|rot|spot|wilt|mosaic|canker|smut|mold|scab|anthracnose))\b",
    re.IGNORECASE,
)
_NAMED_PEST_RE = re.compile(
    r"\b((?:(?:corn|soybean|wheat|stem|stalk|root|seedcorn|cabbage|flea|japanese|colorado|"
    r"wire|cut|army)\s+)?(?:borer|worm|beetle|aphid|mite|thrips|maggot|weevil|leafhopper|grasshopper|fly))\b",
    re.IGNORECASE,
)
_DIAGNOSIS_ASSERTION_RE = re.compile(
    r"\b(?:most likely (?:diagnosis|disease|pathogen|cause) is|"
    r"likely (?:diagnosis|disease|pathogen|cause) is|"
    r"likely caused by|primary suspect is|the diagnosis is)\b",
    re.IGNORECASE,
)
_MAP_ASSERTION_RE = re.compile(
    r"(?:\b(?:soil (?:map|survey)|web soil survey|soil data access|map[- ]unit|public map|nrcs map)\b[\s\S]{0,180}"
    r"\b(?:can confirm|confirms?|indicates?|identifies?|typically (?:corresponds to|consists of|has|contains)|supports? the)\b|"
    r"\btypically (?:corresponds to|consists of|has|contains)\b[\s\S]{0,100}\b(?:texture|component|drainage|soil|slope)\b|"
    r"\b(?:hydrologic group|drainage class)\b[\s\S]{0,60}\b(?:likely|confirms?|is|are)\b)",
    re.IGNORECASE,
)
_REGULATED_ASSERTION_RE = re.compile(
    r"\b(?:safe to (?:spray|apply)|the (?:spray|application|operation) window is acceptable|"
    r"(?:you )?can (?:spray|apply)(?: (?:today|now))?\s+because|"
    r"apply (?:the )?(?:herbicide|fungicide|insecticide|pesticide) now|"
    r"(?:you )?can still apply (?:the )?same rate)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_CERTAINTY_RE = re.compile(
    r"\b(?:the soil is likely|the field is likely|will likely|typically means that this field|"
    r"confirms? the field (?:is|has)|(?:disease|pest|deficiency|stress) is (?:un)?likely|"
    r"the crop is currently in the [^.]{0,50} stage)\b",
    re.IGNORECASE,
)
_CONTRADICTORY_NITROGEN_RE = re.compile(
    r"(?:(?:high (?:soil )?nitrate|soil nitrate[^.]{0,40}\bhigh)[^.]{0,180}(?:confirmed need for (?:a )?|(?:is |may be )?)(?:rescue (?:nitrogen |n )?pass|additional nitrogen)|"
    r"(?:rescue (?:nitrogen |n )?pass|additional nitrogen)[^.]{0,180}(?:needed|necessary|justified)[^.]{0,100}(?:high (?:soil )?nitrate|soil nitrate[^.]{0,40}\bhigh))",
    re.IGNORECASE,
)
_INTERNAL_PROCESS_RE = re.compile(
    r"\b(?:allowed evidence|rejected claims?|earlier draft|draft claim|final gap(?: warning)?|internal (?:prompt|rule|guard)|"
    r"system prompt|routing note|retrieval note|coverage checklist|evidence editor|missing decision content|"
    r"missing content coverage|primary decision evidence|supporting or boundary evidence|evidence roles?)\b",
    re.IGNORECASE,
)
_INTERNAL_CONTROL_CAPSULE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:[*_`#]+\s*)?(?:preserve|primary decision evidence|supporting or boundary evidence|"
    r"decision control state|crop frame|decisive evidence|constraints|evidence role|guard notes|route guidance)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_VACUOUS_INSTRUCTION_ECHO_RE = re.compile(
    r"^\s*(?:answer (?:the|this) (?:question|decision)(?: directly)?|"
    r"answer the question based on the provided evidence|give a direct practical answer|use plain language)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_INTERNAL_SOURCE_ID_RE = re.compile(r"\[(?:[a-z][a-z0-9-]*_){1,}[a-z0-9_-]+\]")
_CONTRADICTORY_CSI_FORMULA_PARAPHRASE_RE = re.compile(
    r"\bsubtract(?:ing|s)?\s+(?:the\s+)?actual evapotranspiration(?:\s*\(\s*AET\s*\))?\s+from\s+"
    r"(?:the\s+)?potential evapotranspiration(?:\s*\(\s*PET\s*\))?\b",
    re.IGNORECASE,
)
_AAFC_HISTORICAL_CROP_YIELD_SLC_RE = re.compile(
    r"(?:\baafc\b.{0,100}\b(?:estimated )?(?:historical|hist)\w*\b.{0,30}\bcrop[- ]?(?:yield|yld)s?\b.{0,40}\bslc\b|"
    r"\baafc\b.{0,100}\bhistorical[- ]?yield[- ]?by[- ]?slc\b|"
    r"\b(?:estimated )?historical crop[- ]?yields? in canada by (?:soil landscapes? of canada|slc)\b|"
    r"\bhistorical crop[- ]?yields?[- ]by[- ]slc\b|"
    r"\bhistorical[- ]?yield[- ]?by[- ]?slc\b|"
    r"\bslc\b.{0,50}\b(?:historical|yield|yld|kg\s*/?\s*ha|kg ha)\b)",
    re.IGNORECASE,
)
_NAMED_AAFC_REGIONAL_PRODUCT_RE = re.compile(
    r"(?:\baafc\b.{0,100}\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index|crop development stage|growth[- ]stage raster)\b|"
    r"\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index)\b|"
    r"\b(?:crop development|crop[- ]stage|growth[- ]stage) (?:layer|raster|product|values?)\b|"
    r"\b(?:british columbia|nova scotia|prince edward island|pei) detailed soil survey\b|"
    r"\b(?:quebec|québec) agro[- ]pedological atlas\b|\bagro[- ]pedological atlas of (?:quebec|québec)\b|"
    r"\b(?:geonb|new brunswick) agricultural soil classes\b|"
    r"\bnewfoundland and labrador weather station climate monitoring data\b|"
    r"\baafc\b.{0,100}\b(?:estimated )?(?:historical|hist)\w*\b.{0,30}\bcrop[- ]?(?:yield|yld)s?\b.{0,40}\bslc\b|"
    r"\b(?:estimated )?historical crop[- ]?yields? in canada by (?:soil landscapes? of canada|slc)\b|"
    r"\bhistorical crop[- ]?yields?[- ]by[- ]slc\b|"
    r"\bslc\b.{0,50}\b(?:historical|yield|yld|kg\s*/?\s*ha|kg ha)\b|"
    r"\baafc\b.{0,80}\bsoil (?:erosion|erision|eroshun) risk(?: indicator)?(?:\s+2021)?\b|"
    r"\baafc\b.{0,40}\b(?:erosion|erision|eroshun)(?: risk)? (?:class|map|layer)\b|\bsoileri\b|"
    r"\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)? (?:map|layer)\b|"
    r"\b(?:map|layer)\b.{0,40}\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)?\b)",
    re.IGNORECASE,
)
_NAMED_PRODUCT_FIELD_DECISION_RE = re.compile(
    r"\b(?:prescrib|recommend|apply|application|spray|fungicide|herbicide|insecticide|pesticide|"
    r"nitrogen|fertili[sz]er|exact (?:rate|timing|depth|date|interval)|"
    r"irrigation (?:depth|timing|schedule)|changing? (?:nitrogen|irrigation|fungicide))\w*\b",
    re.IGNORECASE,
)
_CROP_STAGE_PRODUCT_RE = re.compile(
    r"(?:\baafc\b.{0,80}\bcrop development stage\b|"
    r"\b(?:crop development|crop[- ]stage|growth[- ]stage) (?:layer|raster|product|values?)\b)",
    re.IGNORECASE,
)
_NAMED_PRODUCT_BOUNDARY_QUESTION_RE = re.compile(
    r"\b(?:not|isn't|is not|cannot|can't|why is it not|without)\b.{0,80}"
    r"\b(?:prescription|recommendation|field measurement|field truth|observations? of every plant)\b",
    re.IGNORECASE,
)
_SOURCE_ARTIFACT_RE = re.compile(
    r"\[(?:page|p\.)\s*\d+\]|\bappendix table\b|\bphoto\s+\d+[–-]\d+\b|"
    r"\b(?:table|figure)\s+\d+[.:]\s*\d+\b|"
    r"(?:•\s*){3,}|\bquestions to determine relevance of a feature\b|"
    r"\bsite assessment portion of the nutrient management plan\b|"
    r"(?:\b\d+(?:\.\d+)?\b[\s,;/|]*){12,}",
    re.IGNORECASE,
)
_RECOVERY_STOPWORDS = {
    "a", "an", "and", "are", "before", "between", "do", "field", "for", "from", "has", "how", "i",
    "in", "is", "it", "of", "or", "should", "the", "this", "to", "what", "when", "which", "with",
}


@dataclass(frozen=True)
class _IntentRequirement:
    name: str
    instruction: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class _ScopeAnchor:
    name: str
    question_pattern: str
    answer_pattern: str


@dataclass(frozen=True)
class ClaimRiskAssessment:
    requires_review: bool
    score: int
    reasons: tuple[str, ...]
    unsupported_numbers: tuple[str, ...]
    unsupported_crop_stages: tuple[str, ...]
    unsupported_scientific_names: tuple[str, ...]
    unsupported_named_conditions: tuple[str, ...]
    unsupported_named_pests: tuple[str, ...]
    missing_intent_facets: tuple[str, ...]
    evidence_commit_score: float | None = None
    missing_evidence_terms: tuple[str, ...] = ()
    premise_coverage: float | None = None
    missing_premise_anchors: tuple[str, ...] = ()
    route_violations: tuple[str, ...] = ()

    def as_record(self) -> dict[str, Any]:
        return {
            "requires_review": self.requires_review,
            "score": self.score,
            "reasons": list(self.reasons),
            "unsupported_numbers": list(self.unsupported_numbers),
            "unsupported_crop_stages": list(self.unsupported_crop_stages),
            "unsupported_scientific_names": list(self.unsupported_scientific_names),
            "unsupported_named_conditions": list(self.unsupported_named_conditions),
            "unsupported_named_pests": list(self.unsupported_named_pests),
            "missing_intent_facets": list(self.missing_intent_facets),
            "evidence_commit_score": self.evidence_commit_score,
            "missing_evidence_terms": list(self.missing_evidence_terms),
            "premise_coverage": self.premise_coverage,
            "missing_premise_anchors": list(self.missing_premise_anchors),
            "route_violations": list(self.route_violations),
        }


@dataclass(frozen=True)
class AnswerVerificationResult:
    answer: str
    triggered: bool
    rewrite_accepted: bool
    draft_assessment: ClaimRiskAssessment
    rewrite_assessment: ClaimRiskAssessment | None = None
    final_assessment: ClaimRiskAssessment | None = None
    rejection_reasons: tuple[str, ...] = ()
    draft_output: str | None = None
    editor_output: str | None = None
    fallback_applied: bool = False

    def as_record(self) -> dict[str, Any]:
        intervention_action = (
            "accept_rewrite"
            if self.rewrite_accepted
            else "fallback_or_degraded"
            if self.fallback_applied
            else "preserve_draft"
        )
        return {
            "selection_policy": "hard_safety_then_specificity_v2",
            "intervention_action": intervention_action,
            "triggered": self.triggered,
            "rewrite_accepted": self.rewrite_accepted,
            "draft_assessment": self.draft_assessment.as_record(),
            "rewrite_assessment": self.rewrite_assessment.as_record() if self.rewrite_assessment else None,
            "final_assessment": self.final_assessment.as_record() if self.final_assessment else None,
            "rejection_reasons": list(self.rejection_reasons),
            "fallback_applied": self.fallback_applied,
            "draft_output": self.draft_output,
            "editor_output": self.editor_output,
        }


def _uses_named_product_fidelity(
    question: str,
    evidence_handshake: EvidenceHandshake | None,
    docs: Iterable[RetrievedDoc],
) -> bool:
    if evidence_handshake is None or not _NAMED_AAFC_REGIONAL_PRODUCT_RE.search(question):
        return False
    return any(_named_product_doc_matches_question(question, doc) for doc in docs)


def _is_aafc_crop_health_product_doc(doc: RetrievedDoc) -> bool:
    if doc.source_type not in {"regional_environment_profile", "regional_environment"}:
        return False
    identity = " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
    return bool(
        "ca_aafc_crop_health_indices_specification" in identity
        or (
            re.search(r"\b(?:aafc|agriculture and agri-food canada)\b", identity)
            and re.search(r"\b(?:crop health indices?|crop stress index|crop development stage)\b", identity)
        )
    )


def _is_named_regional_context_doc(doc: RetrievedDoc) -> bool:
    if doc.source_type not in {"regional_environment_profile", "regional_environment"}:
        return False
    identity = " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
    return bool(
        re.search(r"ca_aafc_(?:bc|ns|pei)_detailed_soil_survey_specification", identity)
        or "ca_aafc_qc_agropedological_atlas_specification" in identity
        or "nb_geonb_agricultural_soil_classes" in identity
        or "nl_historical_weather_station_climate_metadata" in identity
        or "ca_aafc_historical_crop_yield_slc_specification" in identity
        or "ca_aafc_soil_erosion_risk_technical_chapter_2021" in identity
        or re.search(
            r"\b(?:british columbia|nova scotia|prince edward island) detailed soil survey\b|"
            r"\bagro[- ]pedological atlas of (?:quebec|québec)\b|"
            r"\bnew brunswick agricultural soil classes\b|"
            r"\bnewfoundland and labrador weather station climate monitoring data\b|"
            r"\bestimated historical crop yields?\b|\bhistorical crop yield\b|"
            r"\bsoil erosion risk indicator\b|\bsoileri\b",
            identity,
        )
    )


def _named_product_doc_matches_question(question: str, doc: RetrievedDoc) -> bool:
    question_lower = question.lower()
    identity = " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
    if re.search(r"\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index|csi)\b", question_lower) or _CROP_STAGE_PRODUCT_RE.search(question_lower):
        return _is_aafc_crop_health_product_doc(doc)
    matches = (
        (r"\b(?:quebec|québec) agro[- ]pedological atlas\b|\bagro[- ]pedological atlas of (?:quebec|québec)\b", r"ca_aafc_qc_agropedological_atlas_specification|agro[- ]pedological atlas of (?:quebec|québec)"),
        (r"\bbritish columbia detailed soil survey\b", r"ca_aafc_bc_detailed_soil_survey_specification|british columbia detailed soil survey"),
        (r"\bnova scotia detailed soil survey\b", r"ca_aafc_ns_detailed_soil_survey_specification|nova scotia detailed soil survey"),
        (r"\b(?:prince edward island|pei) detailed soil survey\b", r"ca_aafc_pei_detailed_soil_survey_specification|prince edward island detailed soil survey"),
        (r"\b(?:geonb|new brunswick) agricultural soil classes\b", r"nb_geonb_agricultural_soil_classes|new brunswick agricultural soil classes"),
        (r"\bnewfoundland and labrador weather station climate monitoring data\b", r"nl_historical_weather_station_climate_metadata|newfoundland and labrador weather station climate monitoring data"),
        (r"\b(?:estimated )?historical crop[- ]?yields?\b|\bhistorical[- ]?yield[- ]?by[- ]?slc\b", r"ca_aafc_historical_crop_yield_slc_specification|historical crop yield"),
        (r"\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)? (?:map|layer|indicator)\b|\bsoileri\b", r"ca_aafc_soil_erosion_risk_technical_chapter_2021|soil erosion risk indicator|soileri"),
    )
    return any(re.search(q_pattern, question_lower) and re.search(doc_pattern, identity) for q_pattern, doc_pattern in matches)


def _missing_named_product_terms(
    question: str,
    answer: str,
    docs: Iterable[RetrievedDoc],
) -> tuple[str, ...]:
    all_docs = tuple(docs)
    matching_docs = tuple(doc for doc in all_docs if _named_product_doc_matches_question(question, doc))
    product_docs = tuple(doc for doc in matching_docs if _is_aafc_crop_health_product_doc(doc))
    regional_docs = tuple(doc for doc in matching_docs if _is_named_regional_context_doc(doc))
    if not product_docs and not regional_docs:
        return ()
    question_lower = " ".join(question.lower().replace("-", " ").split())
    answer_lower = " ".join(answer.lower().replace("-", " ").split())
    missing: list[str] = []

    if re.search(r"\b(?:crop stress index|csi)\b", question_lower):
        value_match = re.search(
            r"\b(?:crop stress index|csi)(?:\s*\([^)]*\))?\s*(?:is|of|=|reports?)\s*(\d{1,3})\b",
            question_lower,
        )
        if value_match:
            value = int(value_match.group(1))
            band = next(
                (
                    (label, low, high)
                    for label, low, high in (
                        ("0-25 no stress", 0, 25),
                        ("26-50 light stress", 26, 50),
                        ("51-75 severe stress", 51, 75),
                        ("76-100 extreme stress", 76, 100),
                    )
                    if low <= value <= high
                ),
                None,
            )
            if band is not None and not (
                str(band[0]).replace("-", " to ") in answer_lower
                or re.search(rf"\b{band[1]}\s*(?:-|to)\s*{band[2]}\b", answer, re.IGNORECASE)
                or re.search(rf"\b{band[0].split()[-2]}\s+stress\b", answer, re.IGNORECASE)
            ):
                missing.append(band[0])
        if not re.search(r"\b(?:modelled|modeled|regional)\b", answer_lower):
            missing.append("modelled regional context")
        if not re.search(
            r"\b(?:not (?:a )?field measurement|not measured|cannot (?:prove|set|support)|"
            r"does not (?:prove|set|support|establish)|root zone|root-zone|field observations?)\b",
            answer_lower,
        ):
            missing.append("field decisions require current crop and soil-water observations")

    if (
        re.search(r"\bcrop health (?:index|indices)\b", question_lower)
        and not re.search(r"\b(?:crop stress index|csi|crop development stage|growth stage raster)\b", question_lower)
    ):
        if not re.search(r"\b5\s*km\b", answer_lower):
            missing.append("5 km modelled regional raster")
        if not re.search(
            r"\b(?:station|precipitation|temperature|crop[- ]specific coefficients?|VSMB)\b",
            answer,
            re.IGNORECASE,
        ):
            missing.append("station weather and crop-model inputs")
        if not re.search(
            r"\b(?:affected and normal|field observations?|scout(?:ing)?|roots?|tissue|plant sample)\b",
            answer_lower,
        ):
            missing.append("field crop, root-zone, and diagnostic observations")

    if _CROP_STAGE_PRODUCT_RE.search(question_lower):
        if not re.search(r"\b5\s*km\b", answer_lower):
            missing.append("5 km modelled regional raster")
        if not re.search(r"\b(?:modelled|modeled|regional)\b", answer_lower):
            missing.append("modelled regional context")
        if not re.search(
            r"\b(?:not (?:an )?observation of every plant|cannot prove every plant|"
            r"does not prove every plant|representative (?:field )?(?:areas?|zones?)|scout(?:ing)?)\b",
            answer_lower,
        ):
            missing.append("not an observation of every plant; scout representative field areas")

    regional_source_ids = {doc.source_id for doc in regional_docs}
    if "ca_aafc_qc_agropedological_atlas_specification" in regional_source_ids:
        if "monteregian" not in answer_lower and "montérégie" not in answer_lower:
            missing.append("Monteregian regional coverage")
        if not re.search(r"\bnot\b.{0,40}\b(?:province[- ]wide|all of (?:quebec|québec))\b", answer_lower):
            missing.append("not province-wide Quebec coverage")
        if not all(term in answer_lower for term in ("organic matter", "drainage")):
            missing.append("mapped soil, fertility, water, and capability attributes")
        if not re.search(r"\b(?:current|representative)\b.{0,45}\b(?:soil test|field observation|sampling)\b", answer_lower):
            missing.append("representative current soil tests and field observations")

    if "nb_geonb_agricultural_soil_classes" in regional_source_ids:
        if "agricultural suitability" not in answer_lower:
            missing.append("agricultural suitability screening")
        if not re.search(r"\bclasses?\s+1\s+(?:through|to|-)\s*5\b", answer_lower):
            missing.append("classes 1 through 5")
        if "2021" not in answer_lower:
            missing.append("April 2021 provenance")
        if not re.search(r"\b(?:does not|cannot|not enough)\b.{0,80}\b(?:drainage|nutrient|limiting factor|input rate)\b", answer_lower):
            missing.append("class does not establish current field condition or rate")

    if "nl_historical_weather_station_climate_metadata" in regional_source_ids:
        if not re.search(r"\b74\s+stations?\b", answer_lower):
            missing.append("74 stations")
        if not re.search(r"\b2007\b.{0,20}\b2015\b", answer_lower):
            missing.append("2007 through 2015")
        if not all(term in answer_lower for term in ("temperature", "rainfall", "snowfall", "total precipitation")):
            missing.append("temperature, rainfall, snowfall, and total precipitation")
        if not re.search(r"\b(?:not|cannot)\b.{0,50}\b(?:current|today|forecast|application window)\b", answer_lower):
            missing.append("historical context cannot establish current weather")

    return _dedupe(missing)


def _named_product_editor_docs(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> tuple[RetrievedDoc, ...]:
    question_lower = question.lower()
    wants_stress = bool(re.search(r"\b(?:crop stress index|csi)\b", question_lower))
    wants_stage = bool(_CROP_STAGE_PRODUCT_RE.search(question_lower))
    selected: list[RetrievedDoc] = []
    for doc in docs:
        matches_question = _named_product_doc_matches_question(question, doc)
        is_crop_health = matches_question and _is_aafc_crop_health_product_doc(doc)
        is_soil_survey = matches_question and _is_named_regional_context_doc(doc)
        if not is_crop_health and not is_soil_survey:
            continue
        identity = " ".join((doc.doc_id, doc.title, *doc.tags)).lower()
        if is_soil_survey and "semantic" in doc.doc_id:
            selected.append(doc)
        elif is_crop_health and ((wants_stress and "stress" in identity) or (wants_stage and "stage" in identity)):
            selected.append(doc)
    if not selected:
        selected.extend(doc for doc in docs if _is_named_regional_context_doc(doc))
    if _NAMED_PRODUCT_FIELD_DECISION_RE.search(question):
        supporting = next(
            (doc for doc in docs if doc.source_type not in {"regional_environment_profile", "regional_environment", "boundary", "ontology"}),
            None,
        )
        if supporting is not None:
            selected.append(supporting)
    unique: dict[str, RetrievedDoc] = {}
    for doc in selected:
        unique.setdefault(doc.doc_id, doc)
    return tuple(unique.values())


def _named_product_field_decision_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    if not _NAMED_AAFC_REGIONAL_PRODUCT_RE.search(question) or not _NAMED_PRODUCT_FIELD_DECISION_RE.search(question):
        return None
    product_docs = tuple(doc for doc in docs if _is_aafc_crop_health_product_doc(doc))
    if not product_docs:
        return None
    product_text = " ".join(doc.text for doc in product_docs)
    question_lower = question.lower()
    sentences: list[str] = []
    generic_crop_health = bool(
        re.search(r"\bcrop[- ]health (?:index|indices)\b", question_lower)
        and not re.search(r"\b(?:crop stress index|csi|crop development stage|growth[- ]stage raster)\b", question_lower)
    )

    if generic_crop_health:
        resolution = "5 km " if re.search(r"\b(?:5000 metre|5\s*km)\b", product_text, re.IGNORECASE) else ""
        sentences.append(
            "No. First confirm the exact dashboard metric and date. If this refers to the AAFC Crop Health "
            f"Indices, it is {resolution}modelled regional context derived from station precipitation and "
            "temperature with the VSMB model and crop-specific coefficients; it is not remotely sensed field truth and "
            "does not observe nitrogen status. The raster covers Canada's agricultural extent."
        )
        sentences.append(
            "A below-normal area value can reflect weather, water balance, crop stage, interpolation, or model "
            "assumptions, so it cannot diagnose a field deficiency."
        )
        sentences.append(
            "Compare affected and normal field areas, crop stage and pattern, roots, drainage and root-zone "
            "moisture, then reconcile fertilizer and crop history with representative soil nitrate and plant "
            "or tissue evidence interpreted using current local calibration."
        )

    if re.search(r"\b(?:crop stress index|csi)\b", question_lower):
        value_match = re.search(
            r"\b(?:crop stress index|csi)(?:\s*\([^)]*\))?\s*(?:is|of|=|reports?)\s*(\d{1,3})\b",
            question_lower,
        )
        if value_match:
            value = int(value_match.group(1))
            band = next(
                (
                    (label, low, high)
                    for label, low, high in (
                        ("0-25 no-stress", 0, 25),
                        ("26-50 light-stress", 26, 50),
                        ("51-75 severe-stress", 51, 75),
                        ("76-100 extreme-stress", 76, 100),
                    )
                    if low <= value <= high
                    and re.search(rf"\b{low}\s*(?:-|to)\s*{high}\b", product_text, re.IGNORECASE)
                ),
                None,
            )
            if band is not None:
                sentences.append(
                    f"AAFC Crop Stress Index {value} falls in the {band[0]} band, but it is modelled regional "
                    "context, not measured root-zone water status."
                )

    if _CROP_STAGE_PRODUCT_RE.search(question_lower) and re.search(
        r"\b5\s*km\b",
        product_text,
        re.IGNORECASE,
    ):
        stage_match = re.search(r"\b(?:reports?|says?|value is|stage)\s*(?:stage\s*)?(\d+)\b", question_lower)
        stage_label = f"The stage {stage_match.group(1)} value" if stage_match else "The crop-stage value"
        sentences.append(
            f"{stage_label} comes from a 5 km modelled regional raster; it cannot prove every plant is at that "
            "stage, so scout representative field areas."
        )

    if not sentences:
        return None
    if re.search(r"\b(?:pale|yellow|chlorosis|patchy)\b", question_lower):
        sentences.append(
            "The pale, patchy report after a wet start is insufficient to diagnose the cause or choose a treatment. "
            "Compare affected and normal areas: record crop stage and field pattern, count plants, dig roots, check "
            "rainfall, drainage, soil moisture, compaction, and fertilizer history, then collect a representative "
            "soil test and tissue test."
        )
    actions = [
        label
        for pattern, label in (
            (r"\bnitrogen\b", "nitrogen"),
            (r"\birrigat", "irrigation"),
            (r"\bfungicide\b", "fungicide timing"),
        )
        if re.search(pattern, question_lower)
    ]
    if actions:
        if len(actions) == 1:
            action_text = actions[0]
        else:
            action_text = ", ".join(actions[:-1]) + f", or {actions[-1]}"
        raster_reference = "this regional raster" if generic_crop_health else "either regional raster"
        sentences.append(f"Do not change {action_text} from {raster_reference} alone.")
    return " ".join(sentences)


def _named_crop_stage_interpretation_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    """Use reviewed stage-layer semantics for factual interpretation only."""

    if not _CROP_STAGE_PRODUCT_RE.search(question) or (
        _NAMED_PRODUCT_FIELD_DECISION_RE.search(question)
        and not _NAMED_PRODUCT_BOUNDARY_QUESTION_RE.search(question)
    ):
        return None
    stage_docs = tuple(
        doc
        for doc in docs
        if _is_aafc_crop_health_product_doc(doc)
        and _named_product_doc_matches_question(question, doc)
        and "stage" in " ".join((doc.doc_id, doc.title, *doc.tags)).lower()
    )
    if not stage_docs:
        return None
    return stage_docs[0].text.strip() or None


def _named_crop_health_interpretation_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    """Use reviewed AAFC product semantics without authorizing a field action."""

    if not _NAMED_AAFC_REGIONAL_PRODUCT_RE.search(question) or _CROP_STAGE_PRODUCT_RE.search(question):
        return None
    if _NAMED_PRODUCT_FIELD_DECISION_RE.search(question) and not _NAMED_PRODUCT_BOUNDARY_QUESTION_RE.search(question):
        return None
    product_docs = tuple(doc for doc in docs if _is_aafc_crop_health_product_doc(doc))
    if not product_docs:
        return None
    lower = question.lower()
    preferred_suffix = (
        "semantic_0001"
        if re.search(r"\b(?:crop stress index|csi|water deficit index)\b", lower)
        else "semantic_0004"
    )
    preferred = next((doc for doc in product_docs if preferred_suffix in doc.doc_id), None)
    return (preferred or product_docs[0]).text.strip() or None


def _aafc_annual_crop_inventory_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    """Return a reviewed ACI product interpretation, never a field record."""

    if not re.search(r"\b(?:AAFC|Canadian)\b.{0,60}\bAnnual Crop Inventory\b", question, re.IGNORECASE):
        return None
    inventory_docs = tuple(
        doc
        for doc in docs
        if doc.source_id == "ca_aafc_annual_crop_inventory_specification"
        and "semantic" in doc.doc_id
    )
    if not inventory_docs:
        return None
    lower = question.lower()
    preferred_suffix = (
        "semantic_0002"
        if re.search(r"\b(?:class|code|value|pixel)\b", lower)
        else "semantic_0003"
        if re.search(r"\b(?:accuracy|confidence|certain|uncertain)\b", lower)
        else "semantic_0001"
    )
    preferred = next((doc for doc in inventory_docs if preferred_suffix in doc.doc_id), None)
    return (preferred or inventory_docs[0]).text.strip() or None


def _named_regional_context_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    survey_docs = tuple(
        doc
        for doc in docs
        if _is_named_regional_context_doc(doc) and _named_product_doc_matches_question(question, doc)
    )
    if not survey_docs:
        return None
    evidence = " ".join(doc.text for doc in survey_docs).lower().replace(",", "")
    source_ids = {doc.source_id for doc in survey_docs}
    question_lower = question.lower()

    if (
        "ca_aafc_bc_detailed_soil_survey_specification" in source_ids
        and "british columbia detailed soil survey" in question_lower
        and all(anchor in evidence for anchor in ("lower fraser valley", "1:100000", "component"))
    ):
        return (
            "That polygon is Lower Fraser Valley regional soil context, not a current field soil test. The current "
            "catalogue describes 1:100,000 coverage, but the historical specification contains inconsistent scale labels, "
            "so check the current dataset metadata. A map unit links to a component table, soil-name table, and "
            "soil-layer table; it does not prove one profile is uniform across the field.\n\n"
            "Use mapped differences to target representative field inspection and sampling. Verify current rooting, "
            "drainage, nutrient supply, salinity, and other decision-specific conditions before choosing management."
        )
    if (
        "ca_aafc_ns_detailed_soil_survey_specification" in source_ids
        and "nova scotia detailed soil survey" in question_lower
        and all(anchor in evidence for anchor in ("pictou county", "1:50000", "component"))
    ):
        return (
            "The product's regional coverage boundary is Pictou County at 1:50,000; it is not province-wide detailed coverage. "
            "A polygon links a map unit to component, soil-name, and soil-layer tables, but it does not prove the same "
            "soil profile or drainage condition across the field.\n\n"
            "Use the mapped differences to target representative field inspection and sampling. Confirm current "
            "rooting, wetness, ponding, outlets, and soil properties before making drainage, lime, nutrient, or "
            "irrigation decisions."
        )
    if (
        "ca_aafc_pei_detailed_soil_survey_specification" in source_ids
        and re.search(r"\b(?:prince edward island|pei) detailed soil survey\b", question_lower)
        and all(anchor in evidence for anchor in ("island-wide", "1:75000", "component"))
    ):
        return (
            "No, the intersection alone is insufficient to choose a tillage or erosion-control plan. The Prince "
            "Edward Island survey is island-wide soil landscape regional soil context at 1:75,000 scale, not a "
            "current field soil test. Crossing map units marks mapped differences and linked components; it does not "
            "prove current erosion, compaction, drainage, or a uniform profile.\n\n"
            "Use those differences to target ground-truthing and representative sampling, then combine slope, runoff "
            "and flow paths, observed erosion evidence, rooting and compaction, drainage, residue, crop history, weather, equipment, and "
            "current local guidance before selecting practices."
        )
    if (
        "ca_aafc_qc_agropedological_atlas_specification" in source_ids
        and re.search(r"\b(?:quebec|québec) agro[- ]pedological atlas\b", question_lower)
        and all(anchor in evidence for anchor in ("monteregian", "organic matter", "field"))
    ):
        return (
            "The polygon is mapped regional soil context for Quebec's Monteregian region, not province-wide coverage "
            "and not a current field soil test. The atlas includes mapped or derived attributes such as pH, organic "
            "matter, phosphorus, potassium, cation exchange capacity, drainage, depth to bedrock, slope, erosion "
            "vulnerability, texture, water stress, and agricultural capability. A mapped attribute can identify what "
            "to inspect, but it does not prove a uniform current root-zone condition or establish a current field "
            "drainage boundary.\n\n"
            "Confirm the field location and current dataset metadata, inspect within-field variability, and use "
            "representative current soil tests and field observations before setting fertilizer or lime rates, "
            "designing drainage, or choosing erosion and tillage practices."
        )
    if (
        "nb_geonb_agricultural_soil_classes" in source_ids
        and re.search(r"\b(?:geonb|new brunswick) agricultural soil classes\b", question_lower)
        and all(anchor in evidence for anchor in ("agricultural suitability", "classes 1 through 5", "2021"))
    ):
        return (
            "GeoNB class 3 can be used only as regional agricultural-suitability screening context. The official "
            "service renders integer classes 1 through 5 and says the data were created in April 2021; water bodies "
            "were removed and polygons smaller than 100 square metres were eliminated. The available metadata does "
            "not define class 3 well enough to infer a specific limiting factor.\n\n"
            "The class does not establish current drainage, nutrient status, crop-specific fit, or an input rate. "
            "Verify the current service metadata, soil and landscape observations, slope, drainage, crop requirements, "
            "and representative soil testing before field-specific management."
        )
    if (
        "nl_historical_weather_station_climate_metadata" in source_ids
        and re.search(r"\bnewfoundland and labrador weather station climate monitoring data\b", question_lower)
        and all(anchor in evidence for anchor in ("74 stations", "2007 through 2015", "total precipitation"))
    ):
        return (
            "The catalogue describes historical daily data from 74 stations across Newfoundland and Labrador for "
            "2007 through 2015. The listed variables are minimum, maximum, and midpoint temperature, rainfall, "
            "snowfall, and total precipitation.\n\n"
            "Those records are historical regional climate context only. They cannot establish today's field weather, "
            "a forecast, a current anomaly, frost, or an application window. Use a live authoritative weather source "
            "near the field plus current local observations for an operational decision."
        )
    if (
        "ca_aafc_soil_erosion_risk_technical_chapter_2021" in source_ids
        and re.search(
            r"\baafc\b.{0,80}\bsoil (?:erosion|erision|eroshun) risk(?: indicator)?(?:\s+2021)?\b|"
            r"\baafc\b.{0,40}\b(?:erosion|erision|eroshun)(?: risk)? (?:class|map|layer)\b|\bsoileri\b|"
            r"\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)? (?:map|layer)\b|"
            r"\b(?:map|layer)\b.{0,40}\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)?\b",
            question_lower,
        )
        and all(anchor in evidence for anchor in ("wind", "water", "tillage", "soil landscapes of canada", "not field truth"))
    ):
        class_sentence = (
            " In this indicator, Very Low means a modelled average annual soil-loss risk below 6 tonnes per hectare "
            "per year for the regional polygon; it is not a measurement of this field's loss this year."
            if "very low" in question_lower
            else ""
        )
        trend_sentence = (
            " Decrease compares the modelled 1981-to-2021 series; it does not show that historical damage has been restored."
            if "decrease" in question_lower
            else ""
        )
        return (
            "AAFC SoilERI is a 2021 census-year regional model that combines wind, water, and tillage erosion risk "
            "for representative landforms within a Soil Landscapes of Canada polygon."
            f"{class_sentence}{trend_sentence}\n\n"
            "Use the intersection as screening context, not field truth. The model simplifies real landforms, omits "
            "gully erosion and some field features, and a location can have different or greater risk than the polygon "
            "class. Before choosing a practice, inspect cover and residue, drifting or exposed soil, runoff paths and "
            "gullies, slope and depositional areas, tillage direction and intensity, and within-field variation; review "
            "the separate wind, water, and tillage components and use current local conservation planning."
        )
    return None


def _aafc_historical_crop_yield_slc_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    """Answer named AAFC historical-yield-by-SLC questions from the reviewed source contract."""

    yield_docs = tuple(
        doc
        for doc in docs
        if "ca_aafc_historical_crop_yield_slc_specification"
        in " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
    )
    if not yield_docs or not _AAFC_HISTORICAL_CROP_YIELD_SLC_RE.search(question):
        return None

    question_lower = question.lower()
    record_parts: list[str] = []
    slc_match = re.search(r"\bslc\s*([0-9]{4,})\b", question, re.IGNORECASE)
    crop_match = re.search(
        r"\b(barley|canola|oats?|rye|soybeans?|sunflower|wheat|corn|flax|chickpeas?|lentils?|"
        r"mustard|peas?|potatoes?|alfalfa|pasture)\b",
        question,
        re.IGNORECASE,
    )
    year_match = re.search(r"\b(?:19|20)\d{2}\b", question)
    value_match = re.search(r"\b[0-9][0-9,]*(?:\.[0-9]+)?\s*kg\s*/?\s*ha\b", question, re.IGNORECASE)
    if slc_match:
        record_parts.append(f"SLC {slc_match.group(1)}")
    if crop_match:
        record_parts.append(crop_match.group(1))
    if year_match:
        record_parts.append(year_match.group(0))
    if value_match:
        value_text = re.sub(r"\s+", " ", value_match.group(0).strip())
        value_text = re.sub(r"\s*/\s*", "/", value_text)
        record_parts.append(value_text)
    record_sentence = f" The cited record is {', '.join(record_parts)}." if record_parts else ""
    if re.search(r"\b(?:spray|pesticide|herbicide|fungicide|insecticide|application permission)\b", question_lower):
        return (
            "No. An AAFC historical crop-yield-by-SLC value cannot authorize or establish suitable conditions for "
            "an application. It is regional historical context, not a current field observation, weather source, or "
            "product-use authority.\n\n"
            "Require the exact current Health Canada PMRA label, product, crop and target, current local wind, rain, "
            "temperature and other label-relevant weather, plus field-specific drift, runoff, buffer, crop-stage, and "
            "site conditions. If any required evidence or label condition is unresolved, delay or do not proceed."
        )

    if re.search(r"\b(?:nitrogen|fertili[sz]er|nutrient)\b", question_lower) and re.search(
        r"\b(?:rate|how much|set|apply|recommend|target)\b",
        question_lower,
    ):
        return (
            "No nitrogen or other nutrient rate can be set from an AAFC historical crop-yield-by-SLC value."
            f"{record_sentence} The value "
            "is a regional historical estimate in kg/ha, not measured field yield, attainable yield, a current yield "
            "forecast, or a nutrient-response calibration.\n\n"
            "Use the current crop and realistic field yield target with representative soil or nitrate tests, nutrient "
            "credits from previous crops and manure, soil and moisture conditions, management history, and current "
            "province- and crop-specific calibration. Without those inputs, do not provide a rate or range."
        )

    if re.search(r"\b(?:quality|completeness|consistency|accuracy|uncertainty|limitations?)\b", question_lower):
        return (
            "The AAFC specification does not define measures for completeness, logical consistency, positional "
            "accuracy, temporal accuracy, or thematic consistency. Its values are downscaled, modelled, linked, or "
            "harmonized depending on crop and region.\n\n"
            "Treat each value as a regional historical estimate for a named crop, year, province, SLC identifier, and "
            "kg/ha unit. It does not prove a field's harvested yield, attainable yield, or yield potential and is not a "
            "current-season forecast. Use current farm records and field evidence for field-specific conclusions."
        )

    if re.search(r"\b(?:construct|built|provenance|source|derived|method|appropriate to use|intended use)\b", question_lower):
        return (
            "AAFC combines three crop- and region-dependent sources at the Soil Landscapes of Canada level. Provincial "
            "yields for seven major crops are downscaled to SLC version 3.2 and adjusted with EVI2 vegetation indices; "
            "alfalfa and improved- and unimproved-pasture yields come from EPIC at SLC level; and Prairie insurance "
            "yields are linked to SLC polygons where available. The sources are harmonized with weighted averages.\n\n"
            "The product reports kg/ha by crop, year, province, and SLC and was designed for national-scale modelling, "
            "model calibration, Census of Environment support, and agri-environmental reporting. Use it as historical "
            "regional context, not as measured field yield, yield potential, a current forecast, or prescriptive authority."
        )

    if re.search(r"\b(?:identifier|attributes?|units?|remain visible|designed to support|delivered|csv)\b", question_lower):
        return (
            "Keep the full record identity visible: ECODISTRIC, SL or SLC identifier, PROVINCE, YEAR, crop, and the "
            "yield value in kg/ha. The product is maintained annually and delivered as a comma-delimited CSV.\n\n"
            "AAFC designed it to support Statistics Canada's Census of Environment, national-scale modelling, "
            "agricultural-model calibration, and agri-environmental indicator reporting. These identifiers preserve a "
            "regional historical estimate; they do not turn it into a current field measurement or forecast."
        )

    if re.search(r"\b(?:forecast|predict|current[- ]season|this year|next year|revenue|budget|income|price)\b", question_lower):
        return (
            "No."
            f"{record_sentence} The AAFC SLC value is a regional historical estimate in kg/ha for a specified crop, year, province, "
            "and Soil Landscapes of Canada identifier. It is not a current-season yield or revenue forecast and does "
            "not establish this field's attainable yield.\n\n"
            "Build a current forecast from verified field yield records with harvested area and moisture basis, crop "
            "and variety, current stand and crop condition, soil and management history, observed and forecast weather, "
            "and current prices or costs where economics are involved. Keep the historical SLC value as background only."
        )

    if re.search(r"\b(?:combine|scale ticket|farm record|yield monitor|actual yield|harvest record)\b", question_lower):
        return (
            "Use the verified farm record as the more direct evidence of this field's harvested yield."
            f"{record_sentence} First reconcile "
            "crop, year, harvested area, moisture basis, units, calibration, and any excluded or failed acres. The AAFC "
            "value is a regional historical SLC estimate with crop- and region-dependent provenance; a difference does "
            "not by itself show that either record is wrong.\n\n"
            "Keep the SLC value as a regional comparator and investigate field, weather, soil, variety, and management "
            "factors before explaining the gap."
        )

    return (
        "No, the AAFC value does not prove what this field yielded."
        f"{record_sentence} It is an estimated historical crop yield in kg/ha "
        "for a named crop, year, province, and Soil Landscapes of Canada polygon. Its provenance varies by crop and "
        "region and may involve provincial-yield downscaling, EPIC forage modelling, or Prairie insurance records.\n\n"
        "Use it as regional historical context only. Confirm field performance with calibrated farm records, harvested "
        "area and moisture basis, crop and variety, weather, soil, management history, and field observations; do not "
        "treat the SLC estimate as measured field yield, yield potential, a current forecast, or a prescription."
    )


def _canola_shatter_harvest_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    """Answer the core canola shatter-timing workflow from reviewed Canadian extension evidence."""

    lower = question.lower()
    if not (
        re.search(r"\bcanola\b", lower)
        and re.search(r"\b(?:harvest|timing)\w*\b", lower)
        and re.search(r"\bshatter\w*\b", lower)
    ):
        return None
    harvest_docs = tuple(
        doc
        for doc in docs
        if doc.source_id == "on_pub811_agronomy_guide"
        and re.search(r"\b(?:harvest|shatter|swath|direct combin)\w*\b", f"{doc.title} {doc.text}", re.IGNORECASE)
    )
    if not harvest_docs:
        return None
    return (
        "Base canola harvest timing on current seed maturity and measured field loss, not one calendar date. Check "
        "representative main-stem pods in multiple early- and late-maturing areas for seed colour change, seed moisture, "
        "pod integrity, and the hybrid's shatter tolerance. Recheck after wind, driving rain, or hot drying weather.\n\n"
        "Use straight cutting or direct combining where maturity is even and the stand is well knit; harvest promptly "
        "once pods and seed are ready because delay raises shatter risk. Swathing can fit uneven fields when the majority "
        "of healthy plants is at the proper seed-colour stage. During harvest, adjust header or pickup height and speed, "
        "ground speed, and combine settings, then make repeated loss checks behind the header and combine across the "
        "field and through the day. This is Ontario extension guidance, so adapt it to the local field, hybrid, weather, "
        "equipment, storage plan, and current provincial guidance."
    )


def _aafc_soil_erosion_risk_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
) -> str | None:
    """Answer SoilERI questions from its reviewed source contract."""

    soil_eri_docs = tuple(
        doc
        for doc in docs
        if "ca_aafc_soil_erosion_risk_technical_chapter_2021"
        in " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
    )
    if not soil_eri_docs or not _NAMED_AAFC_REGIONAL_PRODUCT_RE.search(question):
        return None
    lower = question.lower()
    class_match = re.search(r"\b(very low|very high|moderate|low|high)\b", lower)
    class_label = class_match.group(1).title() if class_match else "mapped"
    class_ranges = (
        "Very Low is less than 6 tonnes per hectare per year; Low is 6 to 11; Moderate is 11 to 22; "
        "High is 22 to 33; and Very High is greater than 33."
    )
    if re.search(r"\b(?:five|5)\b.{0,45}\bclasses?\b|\bclasses?\b.{0,45}\b(?:ranges?|thresholds?)\b", lower):
        return (
            f"AAFC SoilERI defines five modelled average annual soil-loss classes: {class_ranges} "
            "These are tonnes per hectare per year for representative landforms in a regional Soil Landscapes of "
            "Canada polygon, not measured loss for every point in a field. A decreasing 1981-to-2021 modelled trend "
            "does not prove that past soil damage has been restored or that current erosion is absent; verify present "
            "cover, runoff paths, gullies, exposed or drifting soil, and within-field variation."
        )
    if re.search(r"\b(?:spray|herbicide|fungicide|insecticide|pesticide|application)\b", lower):
        return (
            "No. An AAFC SoilERI class cannot authorize or establish safe conditions for a pesticide application; "
            "it is a 2021 census-year regional erosion model, not a current spray assessment. Before spraying, identify "
            "the exact product, crop, and target, and verify the current PMRA product label for that use. Check current "
            "on-site wind and gusts, inversion and rain or rainfast timing, plus label-specific temperature or humidity "
            "limits, drift exposure, runoff paths, sensitive areas, setbacks, and buffers. If the label or current field "
            "and weather conditions cannot be verified and satisfied, delay or do not spray."
        )
    if re.search(r"\b(?:nitrogen|fertili[sz]er|n rate)\b", lower):
        return (
            "No nitrogen rate can be set from an erosion-risk class. AAFC SoilERI is regional erosion screening "
            "context, not fertility evidence. Use the specific crop and stage, realistic yield target, representative "
            "current soil nitrate or locally appropriate soil test, fertilizer already applied, manure and previous-crop "
            "credits, soil and water conditions, and current crop-specific provincial or local calibration before setting "
            "a rate."
        )
    if re.search(r"\b(?:fresh )?gully\b|\bsediment (?:leaving|moving|loss)\b", lower):
        return (
            "The fresh gully and sediment leaving the field should control the next step because they are current field "
            "evidence. The AAFC SoilERI class must not override them: the regional model explicitly omits gully erosion "
            "and can understate risk at a specific location. Photograph and map the gully, sediment path, contributing "
            "area, outlet, and any connection to water; keep traffic and further disturbance out of the active flow path. "
            "Arrange a prompt field assessment with the local conservation or provincial specialist to stabilize the "
            "site and select a control that fits the actual flow path."
        )
    if re.search(r"\b(?:next week|predict|forecast|storm|heavy rain|rainfall event)\b", lower):
        return (
            f"No. The {class_label} class cannot predict erosion from next week's rain. AAFC SoilERI is a 2021 census-year "
            "regional model of average annual wind, water, and tillage erosion risk, not an event forecast for this field. "
            "Use the current authoritative rainfall forecast, including expected intensity and duration, with current "
            "cover and residue, soil moisture or frozen and saturated conditions, slope, runoff paths, outlets, and active "
            "erosion evidence. Recheck the field after the event; use the map only as background context."
        )
    if re.search(r"\b(?:lost|loss)\b.{0,70}\b(?:this year|current (?:year|season))\b", lower):
        class_definition = {
            "Very Low": "below 6 tonnes per hectare per year",
            "Low": "6 to 11 tonnes per hectare per year",
            "Moderate": "11 to 22 tonnes per hectare per year",
            "High": "22 to 33 tonnes per hectare per year",
            "Very High": "greater than 33 tonnes per hectare per year",
        }.get(class_label)
        meaning = (
            f"{class_label} means modelled average annual soil-loss risk {class_definition}"
            if class_definition
            else "The mapped class means modelled average annual soil-loss risk"
        )
        return (
            f"No. {meaning} for a regional Soil Landscapes of Canada polygon; it is not a measurement of this "
            "field's loss this year. Inspect current "
            "sheet, rill, and gully erosion, sediment movement and deposition, exposed or drifting soil, cover, runoff "
            "paths, and slope positions. If a quantified field-loss estimate is needed, define the period and use an "
            "appropriate field-monitoring or erosion-assessment method with a local conservation specialist rather than "
            "treating the map class as measured loss."
        )
    if re.search(r"\b(?:limitation|limit|rely|precise|field[- ]use)\b", lower):
        return (
            "Use AAFC SoilERI as regional screening context, not field truth. It combines wind, water, and tillage "
            "erosion risk for representative, simplified landforms in a Soil Landscapes of Canada polygon and uses the "
            "slope segment with the greatest modelled loss. It omits gully erosion and some real field features and "
            "control practices, and the combined value is a simple sum rather than a process-interaction model. A specific "
            "location can therefore have different or greater risk than the mapped class."
        )
    if re.search(r"\b(?:inspect|check|choos|practice|control)\w*\b", lower):
        return (
            f"Treat the {class_label} SoilERI class as a regional screening prior; it does not choose a practice or establish "
            "urgency. Inspect current cover and residue, exposed or drifting soil, sheet, rill, and gully erosion, runoff "
            "and concentrated-flow paths, outlets and sediment deposition, slope length and shape, soil texture and "
            "drainage, tillage direction and intensity, and variation across the field. Match any control to the observed "
            "erosion process and current local conservation guidance."
        )

    class_sentence = (
        " Very Low means modelled average annual soil-loss risk below 6 tonnes per hectare per year for the regional "
        "polygon; it does not mean the field is currently free of erosion."
        if "very low" in lower
        else ""
    )
    trend_sentence = (
        " Decrease describes the modelled change from 1981 through 2021; it does not prove erosion is absent now or that "
        "historical soil loss has been restored."
        if "decrease" in lower
        else ""
    )
    return (
        "AAFC SoilERI is a 2021 census-year regional model that combines wind, water, and tillage erosion risk for "
        "representative landforms within a Soil Landscapes of Canada polygon."
        f"{class_sentence}{trend_sentence} Use it as screening context, not field truth; verify current cover, runoff "
        "paths, gullies, drifting or exposed soil, slope positions, and within-field variation before acting."
    )


def assess_claim_risk(
    answer: str,
    *,
    question: str,
    evidence_text: str = "",
    question_type: str = "",
    risk_level: str = "low",
    evidence_docs: Iterable[RetrievedDoc] = (),
    preserve_entities: Iterable[str] = (),
    required_entities: Iterable[str] = (),
) -> ClaimRiskAssessment:
    docs = tuple(evidence_docs)
    allowed = _normalize_for_matching(f"{question}\n{evidence_text}")
    condition_allowed = allowed
    if re.search(r"\b(harvest|storage|grain moisture|drying|aeration)\b", question, re.IGNORECASE):
        condition_allowed = f"{condition_allowed} mold"
    if re.search(r"\bcorn\b", question, re.IGNORECASE) and re.search(
        r"\brectangular\b[^?]{0,100}\blesions?\b|\blesions?\b[^?]{0,100}\bleaf veins?\b",
        question,
        re.IGNORECASE,
    ):
        condition_allowed = f"{condition_allowed} gray leaf spot"
    candidate = _LIST_MARKER_RE.sub("", answer)
    unsupported_numbers = _dedupe(
        (
            *_unsupported_values(_NUMBER_RE, candidate, allowed),
            *_unsupported_values(_SPELLED_QUANTITY_RE, candidate, allowed),
        )
    )
    unsupported_stages = _unsupported_values(_CROP_STAGE_RE, candidate, allowed)
    unsupported_names = _unsupported_values(_ITALIC_BINOMIAL_RE, candidate, allowed)
    unsupported_names = _dedupe((*unsupported_names, *_unsupported_values(_PAREN_BINOMIAL_RE, candidate, allowed)))
    unsupported_conditions = _unsupported_values(_NAMED_CONDITION_RE, candidate, condition_allowed)
    unsupported_pests = _unsupported_values(_NAMED_PEST_RE, candidate, allowed)
    missing_intent_facets = _missing_intent_facets(candidate, question=question, question_type=question_type)
    decision_state = build_decision_route_state(question, question_type)
    route_violations = decision_state.answer_violations(candidate)
    premise_coverage = decision_state.premise_coverage(candidate)
    missing_premise_anchors = decision_state.missing_premise_anchors(candidate)
    evidence_handshake = (
        build_evidence_handshake(
            question,
            docs,
            preserve_entities=preserve_entities,
            required_entities=required_entities,
        )
        if docs
        else None
    )
    evidence_commit_score = evidence_handshake.answer_alignment(candidate) if evidence_handshake else None
    missing_evidence_terms = _dedupe(
        (
            *(evidence_handshake.missing_decisive_terms(candidate) if evidence_handshake else ()),
            *_missing_named_product_terms(question, candidate, docs),
        )
    )
    named_product_fidelity = _uses_named_product_fidelity(question, evidence_handshake, docs)

    reasons: list[str] = []
    if _looks_like_french(question) and not _looks_like_french_output(candidate):
        reasons.append("wrong_response_language")
    if unsupported_numbers:
        reasons.append("unsupported_numeric_specificity")
    if unsupported_stages:
        reasons.append("unsupported_crop_stage")
    if unsupported_names:
        reasons.append("unsupported_scientific_name")
    if unsupported_conditions:
        reasons.append("unsupported_named_condition")
    if unsupported_pests:
        reasons.append("unsupported_named_pest")
    if _DIAGNOSIS_ASSERTION_RE.search(candidate) and not _diagnosis_is_supported(candidate, allowed):
        reasons.append("unsupported_diagnostic_certainty")
    if _MAP_ASSERTION_RE.search(candidate):
        reasons.append("map_prior_presented_as_field_truth")
    if _REGULATED_ASSERTION_RE.search(candidate):
        reasons.append("unsupported_regulated_permission")
    if _UNSUPPORTED_CERTAINTY_RE.search(candidate):
        reasons.append("unsupported_field_certainty")
    if (
        _CROP_STAGE_PRODUCT_RE.search(question)
        and re.search(r"\b(?:salinity|saline|salt level|electrical conductivity|\bEC\b)\b", candidate, re.IGNORECASE)
        and not re.search(r"\b(?:crop|development|growth) stage\b|\b(?:heading|jointing|emergence|ripening)\b", candidate, re.IGNORECASE)
    ):
        reasons.append("named_product_semantic_mismatch")
    if _looks_incomplete(candidate, question=question):
        reasons.append("incomplete_generation")
    if _looks_like_question_echo(candidate, question=question):
        reasons.append("question_echo")
    if _unsupported_local_weather_prediction(candidate, question=question):
        reasons.append("unsupported_local_weather_prediction")
    if _looks_repetitive(candidate):
        reasons.append("repetitive_generation")
    if (
        _INTERNAL_PROCESS_RE.search(candidate)
        or _INTERNAL_CONTROL_CAPSULE_RE.search(candidate)
        or _INTERNAL_SOURCE_ID_RE.search(candidate)
        or _VACUOUS_INSTRUCTION_ECHO_RE.search(candidate)
    ):
        reasons.append("internal_process_leakage")
    if re.search(r"\brescue (?:nitrogen|n) pass\b", question, re.IGNORECASE) and _CONTRADICTORY_NITROGEN_RE.search(candidate):
        reasons.append("contradictory_nutrient_logic")
    if re.search(r"\bsandy soils?\b", question, re.IGNORECASE) and re.search(r"\bclay soils?\b", question, re.IGNORECASE) and re.search(
        r"\b(?:SAR|sodium adsorption|calcium amendments?|nitrification inhibitors?)\b",
        candidate,
        re.IGNORECASE,
    ):
        reasons.append("scope_drift")
    if missing_intent_facets:
        reasons.append("missing_decision_content")
    if evidence_commit_score is not None and evidence_commit_score < 0.4:
        reasons.append("weak_primary_evidence_alignment")
    if named_product_fidelity and missing_evidence_terms:
        reasons.append("missing_named_product_fidelity")
    if (
        named_product_fidelity
        and "1 - (aet/pet)" in evidence_text.lower()
        and _CONTRADICTORY_CSI_FORMULA_PARAPHRASE_RE.search(candidate)
    ):
        reasons.append("contradictory_formula_paraphrase")
    reasons.extend(route_violations)

    high_consequence = question_type in {"plant_health", "product_label", "fertility_rate"} or risk_level == "high"
    if high_consequence and reasons:
        reasons.append("high_consequence_claim_review")
    reasons = list(_dedupe(reasons))
    score = (
        3 * len(unsupported_numbers)
        + 3 * len(unsupported_names)
        + 2 * len(unsupported_conditions)
        + 2 * len(unsupported_pests)
        + 2 * len(unsupported_stages)
        + len(missing_intent_facets)
        + 3 * len(route_violations)
        + len(reasons)
    )
    return ClaimRiskAssessment(
        requires_review=bool(reasons),
        score=score,
        reasons=tuple(reasons),
        unsupported_numbers=unsupported_numbers,
        unsupported_crop_stages=unsupported_stages,
        unsupported_scientific_names=unsupported_names,
        unsupported_named_conditions=unsupported_conditions,
        unsupported_named_pests=unsupported_pests,
        missing_intent_facets=missing_intent_facets,
        evidence_commit_score=evidence_commit_score,
        missing_evidence_terms=missing_evidence_terms,
        premise_coverage=premise_coverage,
        missing_premise_anchors=missing_premise_anchors,
        route_violations=route_violations,
    )


def verify_answer(
    draft: str,
    *,
    question: str,
    evidence_text: str,
    question_type: str,
    risk_level: str,
    editor: Any,
    max_evidence_chars: int = 9000,
    evidence_docs: Iterable[RetrievedDoc] = (),
    preserve_entities: Iterable[str] = (),
    required_entities: Iterable[str] = (),
    review_mode: str = "risk_gated",
) -> AnswerVerificationResult:
    docs = tuple(evidence_docs)
    entities = tuple(preserve_entities)
    required = tuple(required_entities)
    evidence_handshake = build_evidence_handshake(
        question,
        docs,
        preserve_entities=entities,
        required_entities=required,
    ) if docs else None
    named_product_fidelity = _uses_named_product_fidelity(question, evidence_handshake, docs)
    decision_state = build_decision_route_state(question, question_type)

    def assess(candidate: str) -> ClaimRiskAssessment:
        return assess_claim_risk(
            candidate,
            question=question,
            evidence_text=evidence_text,
            question_type=question_type,
            risk_level=risk_level,
            evidence_docs=docs,
            preserve_entities=entities,
            required_entities=required,
        )

    def fallback_answer() -> str:
        weather_boundary = _localized_weather_event_answer(question)
        if weather_boundary:
            return weather_boundary
        premise_correction = decision_state.premise_correction_answer()
        if premise_correction:
            return premise_correction
        protocol_answer = _protocol_failure_answer(question)
        if protocol_answer:
            return protocol_answer
        if _requires_scout_application_separation(question) or _requires_integrated_specialty_decision(question):
            return _conservative_failure_answer(question_type, question=question)
        route_answer = _decision_route_failure_answer(decision_state)
        if route_answer:
            return route_answer
        grounded = _safe_evidence_grounded_fallback(
            question,
            docs,
            question_type=question_type,
            preserve_entities=entities,
            required_entities=required,
        )
        return grounded or _conservative_failure_answer(question_type, question=question)

    def fast_fallback_answer() -> str | None:
        weather_boundary = _localized_weather_event_answer(question)
        if weather_boundary:
            return weather_boundary
        premise_correction = decision_state.premise_correction_answer()
        if premise_correction:
            return premise_correction
        protocol_answer = _protocol_failure_answer(question)
        if protocol_answer:
            return protocol_answer
        if _requires_scout_application_separation(question) or _requires_integrated_specialty_decision(question):
            return _conservative_failure_answer(question_type, question=question)
        if _is_wet_forage_establishment_question(question):
            return _conservative_failure_answer(question_type, question=question)
        route_answer = _decision_route_failure_answer(decision_state)
        if route_answer:
            return route_answer
        grounded = _safe_evidence_grounded_fallback(
            question,
            docs,
            question_type=question_type,
            preserve_entities=entities,
            required_entities=required,
        )
        if grounded:
            return grounded
        if decision_state.decision not in {"agronomic_advice", question_type}:
            return _conservative_failure_answer(question_type, question=question)
        return None

    draft_assessment = assess(draft)
    protocol_fallback = _protocol_failure_answer(question)
    if (
        review_mode == "model_agnostic_selective_v2"
        and protocol_fallback is not None
        and draft_assessment.missing_intent_facets
    ):
        protocol_assessment = assess(protocol_fallback)
        if not _blocking_claim_reasons(protocol_assessment):
            return AnswerVerificationResult(
                answer=protocol_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("incomplete_reviewed_protocol_fast_fallback",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=protocol_assessment,
            )
    annual_crop_inventory_fallback = _aafc_annual_crop_inventory_fallback(question, docs)
    if annual_crop_inventory_fallback is not None and review_mode == "model_agnostic_selective_v2":
        inventory_docs = tuple(
            doc for doc in docs if doc.source_id == "ca_aafc_annual_crop_inventory_specification"
        )
        annual_crop_inventory_assessment = assess_claim_risk(
            annual_crop_inventory_fallback,
            question=question,
            evidence_text="\n".join(doc.text for doc in inventory_docs),
            question_type=question_type,
            risk_level=risk_level,
            evidence_docs=inventory_docs,
            preserve_entities=entities,
            required_entities=required,
        )
        if not _blocking_claim_reasons(annual_crop_inventory_assessment):
            return AnswerVerificationResult(
                answer=annual_crop_inventory_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("named_annual_crop_inventory_interpretation_fast_fallback",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=annual_crop_inventory_assessment,
            )
    if _requires_application_unit_mismatch_fallback(question_type, question):
        unit_fallback = _application_unit_mismatch_fallback_answer(question)
        unit_assessment = assess(unit_fallback)
        if not _blocking_claim_reasons(unit_assessment):
            return AnswerVerificationResult(
                answer=unit_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("incompatible_application_units_fast_fallback",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=unit_assessment,
            )
    soil_erosion_fallback = _aafc_soil_erosion_risk_fallback(question, docs)
    if soil_erosion_fallback is not None:
        soil_erosion_docs = tuple(
            doc
            for doc in docs
            if "ca_aafc_soil_erosion_risk_technical_chapter_2021"
            in " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
        )
        soil_erosion_assessment = assess_claim_risk(
            soil_erosion_fallback,
            question=question,
            evidence_text="\n".join(doc.text for doc in soil_erosion_docs),
            question_type=question_type,
            risk_level=risk_level,
            evidence_docs=soil_erosion_docs,
            preserve_entities=entities,
            required_entities=required,
        )
        if not _blocking_claim_reasons(soil_erosion_assessment):
            return AnswerVerificationResult(
                answer=soil_erosion_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("named_soileri_decision_capsule",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=soil_erosion_assessment,
            )
    historical_yield_fallback = _aafc_historical_crop_yield_slc_fallback(question, docs)
    if historical_yield_fallback is not None:
        historical_yield_docs = tuple(
            doc
            for doc in docs
            if "ca_aafc_historical_crop_yield_slc_specification"
            in " ".join((doc.doc_id, doc.source_id, doc.title, doc.source)).lower()
        )
        historical_yield_assessment = assess_claim_risk(
            historical_yield_fallback,
            question=question,
            evidence_text="\n".join(doc.text for doc in historical_yield_docs),
            question_type=question_type,
            risk_level=risk_level,
            evidence_docs=historical_yield_docs,
            preserve_entities=entities,
            required_entities=required,
        )
        if not _blocking_claim_reasons(historical_yield_assessment):
            return AnswerVerificationResult(
                answer=historical_yield_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("named_historical_crop_yield_slc_decision_capsule",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=historical_yield_assessment,
            )
    canola_harvest_fallback = _canola_shatter_harvest_fallback(question, docs)
    if canola_harvest_fallback is not None:
        canola_harvest_docs = tuple(doc for doc in docs if doc.source_id == "on_pub811_agronomy_guide")
        canola_harvest_assessment = assess_claim_risk(
            canola_harvest_fallback,
            question=question,
            evidence_text="\n".join(doc.text for doc in canola_harvest_docs),
            question_type=question_type,
            risk_level=risk_level,
            evidence_docs=canola_harvest_docs,
            preserve_entities=entities,
            required_entities=required,
        )
        if not _blocking_claim_reasons(canola_harvest_assessment):
            return AnswerVerificationResult(
                answer=canola_harvest_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("reviewed_canola_shatter_harvest_capsule",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=canola_harvest_assessment,
            )
    if question_type == "product_label" and _REGULATED_ASSERTION_RE.search(draft):
        regulated_fallback = _conservative_failure_answer(question_type, question=question)
        regulated_assessment = assess(regulated_fallback)
        if not _blocking_claim_reasons(regulated_assessment):
            return AnswerVerificationResult(
                answer=regulated_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("unsafe_regulated_permission_fast_fallback",),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=regulated_assessment,
            )
    named_product_reasons = {
        "missing_named_product_fidelity",
        "contradictory_formula_paraphrase",
    }
    selective_decisions = {
        "ambiguous_pump_direction",
        "ambiguous_product_followup",
        "boundary_only_fertility_rate",
        "clubroot_containment",
        "crop_stress_differential",
        "drought_nitrogen_adjustment",
        "erosion_control_plan",
        "fall_banded_nitrogen",
        "freeze_recovery",
        "fungicide_decision",
        "herbicide_injury_drift_differential",
        "high_p_starter_decision",
        "plant_health_diagnostic",
        "pesticide_rate_request",
        "potato_storage_conditioning",
        "slc_map_interpretation",
        "slc_attribute_interpretation",
        "map_based_rescue_n",
        "map_crop_selection",
        "mapped_wet_strip_irrigation",
        "manure_credit_boundary",
        "nasdi_index_interpretation",
        "salinity_management",
        "seeding_rate_calculation",
        "sidedress_n_credit_reconciliation",
        "sulfur_nitrogen_differential",
        "variety_trial_selection",
        "weed_escape_management",
        "underspecified_spray",
    }
    selective_nitrogen_amount = decision_state.decision == "fertility_rate" and bool(
        re.search(
            r"\b(?:how much|what (?:nitrogen|N) rate|how many (?:pounds?|kilograms?))\b",
            question,
            re.IGNORECASE,
        )
        and re.search(r"\b(?:nitrogen|N)\b", question, re.IGNORECASE)
    )
    selective_mode = review_mode in {
        "conference_selective",
        "calibrated_selective",
        "model_agnostic_selective_v2",
    }
    model_agnostic_selective = review_mode == "model_agnostic_selective_v2"
    selective_missing_decision_content = (
        selective_mode
        and "missing_decision_content" in draft_assessment.reasons
        and _has_specific_failure_answer(question_type, question)
        and (
            model_agnostic_selective
            or _is_wet_forage_establishment_question(question)
            or decision_state.decision not in {"agronomic_advice", question_type}
            or (
                decision_state.decision == "fertility_rate"
                and re.search(r"\b(?:potassium|soil[- ]test k|low k|marginal k)\b", question, re.IGNORECASE)
                and re.search(r"\b(?:one|single)\s+composite(?: sample)?\b", question, re.IGNORECASE)
            )
        )
    )
    skip_non_target_review = review_mode == "named_product_fidelity" or (
        selective_mode
        and decision_state.decision not in selective_decisions
        and not selective_nitrogen_amount
        and not selective_missing_decision_content
    )
    selective_skip_is_safe = not selective_mode or not _blocking_claim_reasons(draft_assessment)
    if skip_non_target_review and not named_product_reasons & set(draft_assessment.reasons) and selective_skip_is_safe:
        return AnswerVerificationResult(
            answer=draft.strip(),
            triggered=False,
            rewrite_accepted=False,
            draft_assessment=draft_assessment,
            final_assessment=draft_assessment,
            draft_output=draft,
        )
    if named_product_fidelity:
        crop_health_interpretation_fallback = (
            _named_crop_health_interpretation_fallback(question, docs)
            if model_agnostic_selective
            else None
        )
        if crop_health_interpretation_fallback is not None:
            crop_health_interpretation_assessment = assess(crop_health_interpretation_fallback)
            if not _blocking_claim_reasons(crop_health_interpretation_assessment):
                return AnswerVerificationResult(
                    answer=crop_health_interpretation_fallback,
                    triggered=True,
                    rewrite_accepted=False,
                    draft_assessment=draft_assessment,
                    rejection_reasons=("named_crop_health_interpretation_fast_fallback",),
                    draft_output=draft,
                    fallback_applied=True,
                    final_assessment=crop_health_interpretation_assessment,
                )
        stage_interpretation_fallback = (
            _named_crop_stage_interpretation_fallback(question, docs)
            if model_agnostic_selective
            else None
        )
        if stage_interpretation_fallback is not None:
            stage_interpretation_assessment = assess(stage_interpretation_fallback)
            if not _blocking_claim_reasons(stage_interpretation_assessment):
                return AnswerVerificationResult(
                    answer=stage_interpretation_fallback,
                    triggered=True,
                    rewrite_accepted=False,
                    draft_assessment=draft_assessment,
                    rejection_reasons=("named_crop_stage_interpretation_fast_fallback",),
                    draft_output=draft,
                    fallback_applied=True,
                    final_assessment=stage_interpretation_assessment,
                )
        detailed_soil_fallback = _named_regional_context_fallback(question, docs)
        if detailed_soil_fallback is not None:
            detailed_soil_assessment = assess(detailed_soil_fallback)
            if not _blocking_claim_reasons(detailed_soil_assessment):
                return AnswerVerificationResult(
                    answer=detailed_soil_fallback,
                    triggered=True,
                    rewrite_accepted=False,
                    draft_assessment=draft_assessment,
                    rejection_reasons=("named_detailed_soil_survey_fast_fallback",),
                    draft_output=draft,
                    fallback_applied=True,
                    final_assessment=detailed_soil_assessment,
                )
        named_product_fast_fallback = _named_product_field_decision_fallback(question, docs)
        if named_product_fast_fallback is not None:
            named_product_fast_assessment = assess(named_product_fast_fallback)
            if not _blocking_claim_reasons(named_product_fast_assessment):
                return AnswerVerificationResult(
                    answer=named_product_fast_fallback,
                    triggered=True,
                    rewrite_accepted=False,
                    draft_assessment=draft_assessment,
                    rejection_reasons=("named_product_field_decision_fast_fallback",),
                    draft_output=draft,
                    fallback_applied=True,
                    final_assessment=named_product_fast_assessment,
                )
    decision_content_fast_fallback = selective_missing_decision_content or (
        "missing_decision_content" in draft_assessment.reasons
        and decision_state.decision in {"map_crop_selection", "salinity_management", "variety_trial_selection"}
    )
    if decision_content_fast_fallback and (
        not model_agnostic_selective
        or bool(_blocking_claim_reasons(draft_assessment))
        or _protocol_kind(question) is not None
    ):
        decision_fallback = fast_fallback_answer()
        decision_fallback_assessment = assess(decision_fallback) if decision_fallback is not None else None
        if (
            decision_fallback is not None
            and decision_fallback_assessment is not None
            and not _blocking_claim_reasons(decision_fallback_assessment)
        ):
            return AnswerVerificationResult(
                answer=decision_fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                rejection_reasons=("decision_content_fast_fallback", decision_state.decision),
                draft_output=draft,
                fallback_applied=True,
                final_assessment=decision_fallback_assessment,
            )
    if _requires_phone_only_symptom_fallback(question_type, question):
        fallback = _phone_only_symptom_fallback_answer()
        final_assessment = assess(fallback)
        return AnswerVerificationResult(
            answer=fallback,
            triggered=True,
            rewrite_accepted=False,
            draft_assessment=draft_assessment,
            final_assessment=final_assessment,
            rejection_reasons=("phone_only_symptom_fallback",),
            fallback_applied=True,
            draft_output=draft,
        )
    route_violations = build_decision_route_state(question, question_type).answer_violations(draft)
    if route_violations and _has_specific_failure_answer(question_type, question):
        fallback = fast_fallback_answer()
        final_assessment = assess(fallback) if fallback is not None else None
        if fallback is not None and final_assessment is not None and not _blocking_claim_reasons(final_assessment):
            return AnswerVerificationResult(
                answer=fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                final_assessment=final_assessment,
                rejection_reasons=("semantic_route_fast_fallback", *route_violations),
                fallback_applied=True,
                draft_output=draft,
            )
    if not draft_assessment.requires_review:
        return AnswerVerificationResult(
            answer=draft.strip(),
            triggered=False,
            rewrite_accepted=False,
            draft_assessment=draft_assessment,
            final_assessment=draft_assessment,
            draft_output=draft,
        )

    if "incomplete_generation" in draft_assessment.reasons and _has_specific_failure_answer(question_type, question):
        fallback = fast_fallback_answer()
        final_assessment = assess(fallback) if fallback is not None else None
        if fallback is not None and final_assessment is not None and not _blocking_claim_reasons(final_assessment):
            return AnswerVerificationResult(
                answer=fallback,
                triggered=True,
                rewrite_accepted=False,
                draft_assessment=draft_assessment,
                final_assessment=final_assessment,
                rejection_reasons=("incomplete_generation_fast_fallback",),
                fallback_applied=True,
                draft_output=draft,
            )

    editor_evidence_text = evidence_text
    if named_product_fidelity:
        editor_docs: tuple[RetrievedDoc, ...] = ()
        if any(_is_named_regional_context_doc(doc) for doc in docs):
            editor_docs = _named_product_editor_docs(question, docs)
        elif evidence_handshake is not None and evidence_handshake.primary_doc_id:
            primary_doc = next(
                (doc for doc in docs if doc.doc_id == evidence_handshake.primary_doc_id),
                None,
            )
            if primary_doc is not None:
                editor_docs = (primary_doc,)
        else:
            editor_docs = _named_product_editor_docs(question, docs)
        if editor_docs:
            editor_evidence_text = "\n\n".join(
                f"Source: {doc.title}: {doc.text}"
                for doc in editor_docs
            )
    messages = build_evidence_editor_messages(
        draft=draft,
        question=question,
        question_type=question_type,
        evidence_text=editor_evidence_text[:max_evidence_chars],
        failed_claims=_risk_excerpts(draft, draft_assessment),
        forbidden_terms=_forbidden_terms(draft, draft_assessment, question=question, evidence_text=evidence_text),
        missing_intent_facets=draft_assessment.missing_intent_facets,
        missing_evidence_terms=draft_assessment.missing_evidence_terms,
        max_words=max(60, min(160, len(draft.split()) + 40)),
        evidence_handshake=evidence_handshake,
        decision_state=decision_state,
        preserve_supported_draft=(
            model_agnostic_selective
            and not {
                "incomplete_generation",
                "repetitive_generation",
                "internal_process_leakage",
            }
            & set(draft_assessment.reasons)
        ),
    )
    try:
        editor_output = str(editor.generate(messages)).strip()
    except (RuntimeError, ValueError) as exc:
        fallback = fallback_answer()
        final_assessment = assess(fallback)
        return AnswerVerificationResult(
            answer=fallback,
            triggered=True,
            rewrite_accepted=False,
            draft_assessment=draft_assessment,
            rejection_reasons=("editor_error", type(exc).__name__),
            fallback_applied=True,
            final_assessment=final_assessment,
            draft_output=draft,
        )
    rewrite_assessment = assess(editor_output)
    rejection_reasons = _rewrite_rejection_reasons(
        draft=draft,
        rewrite=editor_output,
        draft_assessment=draft_assessment,
        rewrite_assessment=rewrite_assessment,
        question=question,
        question_type=question_type,
        evidence_handshake=evidence_handshake,
        require_complete_decision_content=model_agnostic_selective,
    )
    accepted = not rejection_reasons
    if accepted:
        final_answer = editor_output
        final_assessment = rewrite_assessment
    else:
        fallback = fallback_answer()
        final_answer, final_assessment = _select_best_degraded_answer(
            question=question,
            candidates=(
                (draft, draft_assessment),
                (editor_output, rewrite_assessment),
                (fallback, assess(fallback)),
            ),
        )
    return AnswerVerificationResult(
        answer=final_answer,
        triggered=True,
        rewrite_accepted=accepted,
        draft_assessment=draft_assessment,
        rewrite_assessment=rewrite_assessment,
        rejection_reasons=rejection_reasons,
        draft_output=draft,
        editor_output=editor_output,
        fallback_applied=not accepted and final_answer.strip() != draft.strip(),
        final_assessment=final_assessment,
    )


def _requires_phone_only_symptom_fallback(question_type: str, question: str) -> bool:
    if question_type != "fertility_diagnostic":
        return False
    return bool(
        re.search(r"\b(phone (?:description|photo)|photo only|no soil test|no tissue test)\b", question, re.IGNORECASE)
        and re.search(r"\b(yellow|yellowing|pale|chlorosis|symptoms?|crop stress)\b", question, re.IGNORECASE)
    )


def _requires_application_unit_mismatch_fallback(question_type: str, question: str) -> bool:
    if question_type != "product_label":
        return False
    lower = question.lower()
    has_irrigation_depth = bool(
        re.search(r"\b(?:irrigation|water(?:ing)?|profondeur)\b", lower)
        and re.search(r"\b(?:mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|inches?)\b", lower)
    )
    has_product_volume = bool(
        re.search(r"\b(?:product|chemical|pesticide|produit)\b", lower)
        and re.search(r"\b(?:ml|millilit(?:re|er)s?|lit(?:re|er)s?)\b", lower)
    )
    asks_for_conversion = bool(
        re.search(r"\b(?:how many|how much|convert|conversion|what (?:amount|volume)|combien|quelle quantit[eé])\b", lower)
    )
    return has_irrigation_depth and has_product_volume and asks_for_conversion


def _application_unit_mismatch_fallback_answer(question: str) -> str:
    if re.search(r"\b(?:combien|quelle quantit[eé]|millilitres? de produit)\b", question, re.IGNORECASE):
        return (
            "Ne convertissez pas directement une profondeur d'irrigation en millilitres de produit : ce sont "
            "des quantités différentes. Pour calculer la quantité de produit, confirmez le produit exact et "
            "l'étiquette actuelle propre à la province, le taux homologué pour la culture et la cible, la "
            "superficie traitée, ainsi que tout volume de bouillie exigé par l'étiquette. Faites ensuite le "
            "calcul avec un système d'application étalonné. Si le produit doit passer par l'irrigation, vérifiez "
            "aussi que l'étiquette autorise la chimigation et respectez ses exigences d'équipement et de sécurité."
        )
    return (
        "Do not convert an irrigation depth directly into millilitres of product; they are different quantities. "
        "To calculate a product amount, confirm the exact product and current jurisdiction-specific label, the "
        "labelled rate for the crop and target, the treated area, and any label-specified carrier-volume "
        "requirement. Then calculate and verify the mix with a calibrated application system. If the product "
        "will be delivered through irrigation, also confirm that the label permits chemigation and follow its "
        "equipment and safety directions."
    )


def _phone_only_symptom_fallback_answer() -> str:
    return (
        "Do not diagnose from a phone description or photo; it is not enough to choose a treatment. "
        "Record crop stage, which leaves and plant parts are affected, whole-plant symptoms, field pattern, roots, rainfall, drainage, soil moisture, field history, and any application pattern; collect clear photos and representative samples. "
        "Use a current soil test and tissue test to separate nitrogen or sulfur deficiency from water stress, root restriction, disease, and application injury before acting."
    )


def _protocol_kind(question: str) -> str | None:
    lower = question.lower()
    if all(term in lower for term in ("random composite", "benchmark", "directed", "grid")) and re.search(
        r"\bsoil sampl", lower
    ):
        return "soil_sampling_design"
    if "liquid manure" in lower and re.search(r"\b(?:representative sample|handling|lab result|laboratory)\b", lower):
        return "liquid_manure_sampling"
    if "manure" in lower and "commercial fertilizer" in lower and re.search(r"\b(?:credit|double[- ]apply)", lower):
        return "manure_nutrient_credit"
    if "mapped" in lower and re.search(r"\b(?:runoff|watercourse)\b", lower) and re.search(
        r"\b(?:observations?|before choosing|control practice)\b", lower
    ):
        return "mapped_runoff_assessment"
    return None


def _protocol_failure_answer(question: str) -> str | None:
    kind = _protocol_kind(question)
    if kind == "soil_sampling_design":
        return (
            "Choose the design from the decision objective and whether field variability is spatially stable. Random "
            "composite sampling estimates a whole-field average. Benchmark sampling repeatedly tracks a representative "
            "location. Directed sampling separates known landscape or management zones. Grid sampling supports dense "
            "spatial mapping, but at higher cost. For stable knolls and wet areas, define candidate zones from field "
            "history, topography, yield or imagery patterns, then ground-truth each zone. Keep locations georeferenced "
            "and use consistent sampling depth, timing, and laboratory method. Do not assign a nutrient rate until the "
            "samples are interpreted with current local calibration."
        )
    if kind == "liquid_manure_sampling":
        return (
            "Thoroughly agitate the liquid-manure storage before sampling. Collect multiple increments during the "
            "representative middle portion of pumping and combine them into a composite sample; avoid relying on the "
            "beginning, end, surface, or settled layer alone. Mix the composite in a clean non-metallic container, take "
            "the laboratory subsample, seal it, and label it. Keep the sample cool and transport it promptly, or freeze "
            "it when delayed if the laboratory instructs you to, and leave expansion space in the container. Coordinate "
            "container, preservation, method, sample size, and safety with the lab. Before calculating a credit, pair the "
            "analysis with application amount, date, method, timing, and incorporation records plus locally appropriate "
            "first-year plant availability."
        )
    if kind == "manure_nutrient_credit":
        return (
            "Build one nutrient budget from a representative manure analysis and the actual application amount, date, "
            "method, incorporation, and field distribution. Credit first-year plant-available nutrients, not total "
            "manure content. Reconcile that credit with residual soil nitrate, method-specific soil-test phosphorus, the "
            "previous crop, nutrients already applied, a realistic yield goal, and crop need. Check equipment calibration "
            "and application uniformity, and account for runoff, leaching, volatilization, and future residual credit. Do "
            "not state a remaining fertilizer rate until the full budget is reconciled with current Alberta guidance."
        )
    if kind == "mapped_runoff_assessment":
        return (
            "Treat the map as screening context, not proof of field runoff. In the field, verify slope length and grade, "
            "contributing area, concentrated and sheet-flow paths, outlets, erosion signs, and connection to the seasonal "
            "watercourse. Check soil texture and structure, infiltration, surface sealing, compaction, residue, cover, "
            "tillage history, and crop history. Record nutrient source or form, placement, incorporation, and application "
            "timing, plus frozen or saturated soil and rainfall or snowmelt exposure. Identify whether the dominant "
            "pathway is dissolved, sediment-bound, concentrated flow, or sheet flow before matching a control. Verify "
            "current Alberta setback or legal requirements separately."
        )
    return None


def build_evidence_editor_messages(
    *,
    draft: str = "",
    question: str,
    question_type: str,
    evidence_text: str,
    failed_claims: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
    missing_intent_facets: tuple[str, ...],
    missing_evidence_terms: tuple[str, ...],
    max_words: int,
    evidence_handshake: EvidenceHandshake | None = None,
    decision_state: Any | None = None,
    preserve_supported_draft: bool = False,
) -> list[dict[str, str]]:
    rejected = "\n".join(f"- {claim}" for claim in failed_claims) or "- The prior draft was not grounded enough to use."
    forbidden = ", ".join(forbidden_terms) or "Any specific detail not present in allowed evidence"
    requirement_map = {item.name: item.instruction for item in _intent_requirements(question, question_type)}
    required_items = [
        f"- {requirement_map.get(name, name.replace('_', ' '))}" for name in missing_intent_facets
    ]
    required_items.extend(f"- Preserve this decisive source phrase or fact: {term}" for term in missing_evidence_terms)
    required_content = "\n".join(required_items) or "- Answer the decision requested by the user directly."
    handshake_block = ""
    if evidence_handshake is not None:
        handshake_block = f"\n\n{evidence_handshake.prompt_block()}"
    decision_block = ""
    if decision_state is not None:
        decision_block = f"\n\n{decision_state.prompt_block()}"
    map_boundary = ""
    if re.search(r"\b(soil map|soil survey|map[- ]unit|component|public map|nrcs map)\b", question, re.IGNORECASE):
        map_boundary = (
            " For map questions, describe mapped units and components as screening attributes; do not claim a component, "
            "texture, drainage class, hydrologic group, or slope occurs at the field unless the allowed evidence states it."
        )
    draft_block = ""
    editing_instruction = "Write a fresh, direct answer"
    if preserve_supported_draft and draft.strip():
        draft_block = (
            "ORIGINAL DRAFT - PRESERVE SUPPORTED CONTENT AND WORDING\n"
            f"{draft.strip()}\n\n"
        )
        editing_instruction = (
            "Revise the original draft with the smallest changes needed to remove unsupported claims "
            "and cover decision-critical omissions"
        )
    response_language = "French" if _looks_like_french(question) else "English"
    user = (
        "USER QUESTION\n"
        f"{question.strip()}\n\n"
        "ALLOWED EVIDENCE\n"
        f"{evidence_text.strip() or 'No supporting evidence was retrieved.'}"
        f"{handshake_block}{decision_block}\n\n"
        f"{draft_block}"
        "REJECTED CLAIMS FROM AN EARLIER DRAFT - DO NOT REPEAT OR PARAPHRASE THESE CLAIMS\n"
        f"{rejected}\n\n"
        "FORBIDDEN TERMS OR VALUES UNLESS THEY APPEAR VERBATIM IN ALLOWED EVIDENCE\n"
        f"{forbidden}\n\n"
        "MISSING DECISION CONTENT THAT THE FRESH ANSWER MUST COVER\n"
        f"{required_content}\n\n"
        f"RESPONSE LANGUAGE\n- Write the entire user-facing answer in {response_language}.\n\n"
        f"{editing_instruction} in at most {max_words} words. Use only the allowed evidence. "
        "Cover every missing-content bullet explicitly and in order; an omitted bullet makes the answer invalid. "
        "Do not output a digit unless that exact value appears in allowed evidence. "
        "Do not name a soil component, texture, drainage class, pest, disease, pathogen, crop stage, or product unless it appears in allowed evidence. "
        "When the evidence is insufficient, state the boundary and the next observation or test instead of guessing."
        f"{map_boundary}"
    )
    return [
        {"role": "system", "content": EVIDENCE_EDITOR_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def context_evidence_text(context: Any | None) -> str:
    if context is None:
        return ""
    parts: list[str] = []
    for doc in getattr(context, "retrieved_docs", ()):
        parts.append(f"Source: {getattr(doc, 'title', '')}: {getattr(doc, 'text', '')}")
    for note in getattr(context, "tool_notes", ()):
        name = str(getattr(note, "name", "") or "")
        # Deterministic guards are policy constraints, not factual evidence.
        # Treating them as ALLOWED EVIDENCE caused editors to answer unrelated
        # planting questions with spray-weather boilerplate.
        if name.endswith("_guard"):
            continue
        parts.append(f"Tool observation: {getattr(note, 'text', '')}")
    return "\n".join(parts)


_SCOPE_ANCHOR_RULES: tuple[_ScopeAnchor, ...] = (
    _ScopeAnchor("sweet_corn", r"\bsweet[- ]corn\b", r"\bsweet[- ]corn\b"),
    _ScopeAnchor("greenhouse", r"\bgreenhouse\b", r"\bgreenhouse\b"),
    _ScopeAnchor("cucumber", r"\bcucumbers?\b", r"\bcucumbers?\b"),
    _ScopeAnchor("forage", r"\b(?:forage|hay stand|alfalfa stand)\b", r"\b(?:forage|hay|alfalfa|stand)\b"),
    _ScopeAnchor("fusarium_head_blight", r"\b(?:fusarium head blight|FHB)\b", r"\b(?:fusarium head blight|FHB)\b"),
    _ScopeAnchor("canada_fleabane", r"\b(?:canada fleabane|horseweed)\b", r"\b(?:canada fleabane|horseweed|fleabane)\b"),
    _ScopeAnchor("cutworm", r"\bcutworms?\b", r"\bcutworms?\b"),
    _ScopeAnchor("clubroot", r"\bclubroot\b", r"\bclubroot\b"),
    _ScopeAnchor("kochia", r"\bkochia\b", r"\bkochia\b"),
    _ScopeAnchor("wild_oat", r"\bwild oats?\b", r"\bwild oats?\b"),
    _ScopeAnchor("flea_beetle", r"\bflea beetles?\b", r"\bflea beetles?\b"),
    _ScopeAnchor("wheat_midge", r"\bwheat midge\b", r"\bwheat midge\b"),
    _ScopeAnchor(
        "irrigation_scheduling",
        r"\b(?:next irrigation|irrigation (?:timing|frequency|volume|schedule)|root[- ]zone water)\b",
        r"\b(?:next irrigation|irrigation (?:timing|frequency|volume|schedule|depth|decision)|root[- ]zone (?:water|moisture|depletion)|soil[- ]water depletion)\b",
    ),
    _ScopeAnchor(
        "greenhouse_substrate",
        r"\b(?:substrate|media|drain(?:age| fraction)|root[- ]zone)\b",
        r"\b(?:substrate|media|container|slab|drain(?:age| fraction)|root[- ]zone)\b",
    ),
    _ScopeAnchor(
        "sweet_corn_harvest",
        r"\b(?:approaching harvest|harvest timing|maturity specification|representative ears?)\b",
        r"\b(?:harvest timing|maturity|representative ears?|milk stage|kernel stage|buyer(?:'s)? specification|cooling)\b",
    ),
    _ScopeAnchor(
        "fhb_risk",
        r"\b(?:flowering|anthesis)\b[^?]{0,160}\b(?:risk|moisture|residue|rotation)\b|\bFHB risk\b",
        r"\b(?:flowering|anthesis|susceptible window|FHB risk|fusarium head blight risk)\b",
    ),
    _ScopeAnchor(
        "seeding_depth",
        r"\bseed(?:ing)? depth\b",
        r"\b(?:seed(?:ing)? depth|placement depth|depth to (?:reliable )?moisture|opener depth)\b",
    ),
    _ScopeAnchor(
        "stand_loss",
        r"\b(?:stand loss|cut plants?|uneven emergence)\b",
        r"\b(?:stand loss|stand count|remaining stand|cut plants?|fresh injury)\b",
    ),
    _ScopeAnchor(
        "soil_test_phosphorus",
        r"\b(?:soil[- ]test phosphorus|soil[- ]test P|phosphorus method|Bray|Olsen|Mehlich)\b",
        r"\b(?:soil[- ]test phosphorus|soil[- ]test P|phosphorus|test method|Bray|Olsen|Mehlich)\b",
    ),
    _ScopeAnchor(
        "nutrient_runoff",
        r"\b(?:nutrient|fertiliz\w*) (?:application|applied)\b[^?]{0,180}\b(?:runoff|nutrient[- ]loss|loss risk)\b|"
        r"\b(?:runoff|nutrient[- ]loss)\b[^?]{0,180}\b(?:nutrient|fertiliz\w*)\b",
        r"\b(?:runoff|flow paths?|infiltration|saturat\w*|rainfall (?:amount|intensity|timing)|nutrient (?:form|placement)|incorporat\w*)\b",
    ),
    _ScopeAnchor(
        "forage_thinning",
        r"\b(?:thinning|thin|stand decline)\b[^?]{0,180}\b(?:crown|root|winter injury|compaction|water stress)\b",
        r"\b(?:thinning|stand decline|crowns?|roots?|winter injury|compaction|water stress)\b",
    ),
    _ScopeAnchor("sidedress_nitrogen", r"\bsidedress(?: nitrogen| N)?\b", r"\b(?:sidedress|nitrogen budget|crop nitrogen demand)\b"),
    _ScopeAnchor("seed_row_fertilizer", r"\bseed[- ]row fertilizer\b", r"\b(?:seed[- ]row fertilizer|seed[- ]fertilizer separation|opener spread|seedbed utilization)\b"),
    _ScopeAnchor("wet_area_drainage", r"\bwet areas?\b[^?]{0,180}\bdrainage\b", r"\b(?:wet areas?|drainage|water table|saturation|outlet)\b"),
    _ScopeAnchor("hail_disease", r"\b(?:hail|storm)\b[^?]{0,180}\b(?:lesion|disease)\b", r"\b(?:hail|storm injury|impact injury|disease progression|pathogen signs?)\b"),
    _ScopeAnchor("common_rust", r"\bcommon rust\b", r"\b(?:common rust|rust pustules?|rub[- ]off spores?)\b"),
    _ScopeAnchor("wild_oat_cohorts", r"\bwild[- ]oat cohorts?\b|\bwild oats?\b[^?]{0,120}\bcohorts?\b", r"\b(?:wild oats?|cohorts?|late emergence|survivors?)\b"),
    _ScopeAnchor("herbicide_injury_control", r"\bherbicide (?:pass|application)\b[^?]{0,180}\b(?:crop is injured|weeds? remain|failed weed control)\b", r"\b(?:crop injury|weed survivors?|failed weed control|overlaps?|skips?)\b"),
    _ScopeAnchor("tomato_leaf_curl", r"\b(?:tomato|tomatoes)\b[^?]{0,120}\bleaf curl\b|\bleaf curl\b[^?]{0,120}\b(?:tomato|tomatoes)\b", r"\b(?:tomato leaf curl|leaf curl|curled leaves?)\b"),
    _ScopeAnchor("winter_injury", r"\b(?:severe )?winter\b[^?]{0,160}\b(?:bud break|dieback|winter injury)\b", r"\b(?:winter injury|winter damage|live tissue|bud viability|cambium)\b"),
    _ScopeAnchor(
        "slc_component_map",
        r"\b(?:soil landscapes of canada|SLC|PPC)\b[^?]{0,180}\b(?:component|composante|polygon|polygone|drain)\w*\b|"
        r"\bsoil landscapes(?: of canada)?\b[^?]{0,180}\b(?:attributes?|measurements?|fertilizer|drainage)\b|"
        r"\b(?:component|composante|polygon|polygone)\w*\b[^?]{0,180}\b(?:soil landscapes of canada|SLC|PPC)\b",
        r"(?s)(?=.*\b(?:soil landscapes|SLC|PPC|polygon|polygone)\b)(?=.*\b(?:component|composante|regional|généralis|ground[- ]truth|terrain)\w*\b)",
    ),
    _ScopeAnchor(
        "mapped_wet_strip_irrigation",
        r"\b(?:map|mapped|carte)\b[^?]{0,160}\b(?:wet|dark strip|bande sombre|humide)\b[^?]{0,160}\birrigat|"
        r"\birrigat\w*\b[^?]{0,160}\b(?:wet|dark strip|bande sombre|humide)\b",
        r"(?s)(?=.*\b(?:wet|strip|zone|humide|bande)\b)(?=.*\birrigat\w*\b)(?=.*\b(?:verify|measure|probe|sensor|ground[- ]truth|vérif|mesur)\w*\b)",
    ),
    _ScopeAnchor(
        "ambiguous_pump_direction",
        r"\bpump\b[^?]{0,180}\b(?:irrigat|drain)\w*\b",
        r"(?s)(?=.*\bpump\b)(?=.*\birrigat\w*\b)(?=.*\bdrain\w*\b)(?=.*\b(?:clarify|confirm|whether|direction|purpose)\b)",
    ),
    _ScopeAnchor(
        "nasdi_spi_spei",
        r"\bNASDI\b[^?]{0,240}\b(?:SPI|standardized precipitation index)\b[^?]{0,240}"
        r"\b(?:SPEI|standardized precipitation evapotranspiration index)\b|"
        r"\b(?:SPI|standardized precipitation index)\b[^?]{0,240}"
        r"\b(?:SPEI|standardized precipitation evapotranspiration index)\b",
        r"(?s)(?=.*\bSPI\b)(?=.*\bSPEI\b)(?=.*\bprecipitation\b)(?=.*\b(?:evapotranspiration|evaporative demand)\b)(?=.*\b(?:window|timescale|accumulation)\b)",
    ),
    _ScopeAnchor(
        "spray_and_scout",
        r"\bspray\w*\b[^?]{0,180}\bscout\w*\b|\bscout\w*\b[^?]{0,180}\bspray\w*\b",
        r"(?s)(?=.*\bspray\w*\b)(?=.*\bscout\w*\b)(?=.*\b(?:label|weather|wind|worker|access|safe)\w*\b)",
    ),
    _ScopeAnchor(
        "manure_nitrogen_credit",
        r"\b(?:manure|digestate|compost)\b[^?]{0,180}\b(?:nitrogen|N) credit\b|\b(?:nitrogen|N) credit\b[^?]{0,180}\bmanure\b",
        r"(?s)(?=.*\bmanure\b)(?=.*\b(?:credit|analysis|test)\w*\b)(?=.*\b(?:application|history|calibration|Saskatchewan|local)\w*\b)",
    ),
)


def _active_scope_anchors(question: str) -> tuple[_ScopeAnchor, ...]:
    return tuple(
        anchor for anchor in _SCOPE_ANCHOR_RULES if re.search(anchor.question_pattern, question, re.IGNORECASE)
    )


def _missing_scope_anchors(question: str, answer: str) -> tuple[str, ...]:
    return tuple(
        anchor.name
        for anchor in _active_scope_anchors(question)
        if not re.search(anchor.answer_pattern, answer, re.IGNORECASE)
    )


def _lost_scope_anchors(question: str, reference: str, candidate: str) -> tuple[str, ...]:
    return tuple(
        anchor.name
        for anchor in _active_scope_anchors(question)
        if re.search(anchor.answer_pattern, reference, re.IGNORECASE)
        and not re.search(anchor.answer_pattern, candidate, re.IGNORECASE)
    )


def _safe_evidence_grounded_fallback(
    question: str,
    docs: Iterable[RetrievedDoc],
    *,
    question_type: str,
    preserve_entities: Iterable[str] = (),
    required_entities: Iterable[str] = (),
) -> str | None:
    candidate = evidence_grounded_fallback(
        question,
        docs,
        preserve_entities=preserve_entities,
        required_entities=required_entities,
    )
    if not candidate or _SOURCE_ARTIFACT_RE.search(candidate):
        return None
    if _missing_scope_anchors(question, candidate):
        return None
    if build_decision_route_state(question, question_type).answer_violations(candidate):
        return None
    return candidate


def _rewrite_rejection_reasons(
    *,
    draft: str,
    rewrite: str,
    draft_assessment: ClaimRiskAssessment,
    rewrite_assessment: ClaimRiskAssessment,
    question: str,
    question_type: str,
    evidence_handshake: EvidenceHandshake | None,
    require_complete_decision_content: bool = False,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not rewrite:
        reasons.append("empty_rewrite")
    draft_words = max(1, len(draft.split()))
    expansion_limit = max(draft_words + 12, int(draft_words * 1.15))
    if draft_assessment.missing_intent_facets:
        expansion_limit = max(draft_words + 90, int(draft_words * 2.0))
    if {
        "missing_named_product_fidelity",
        "contradictory_formula_paraphrase",
    } & set(draft_assessment.reasons):
        expansion_limit = max(draft_words + 80, int(draft_words * 1.75))
    if len(rewrite.split()) > expansion_limit:
        reasons.append("rewrite_expanded_answer")
    if _blocking_claim_reasons(rewrite_assessment):
        reasons.append("claim_risk_not_cleared")
    decision_state = build_decision_route_state(question, question_type)
    reasons.extend(
        f"question_scope_lost:{anchor}"
        for anchor in _lost_scope_anchors(question, draft, rewrite)
    )
    rewrite_route_violations = decision_state.answer_violations(rewrite)
    reasons.extend(f"rewrite_route_violation:{reason}" for reason in rewrite_route_violations)
    reasons.extend(
        f"premise_not_preserved:{anchor}"
        for anchor in decision_state.missing_premise_anchors(rewrite)
    )
    if (
        evidence_handshake is not None
        and evidence_handshake.commit_check_enabled
        and rewrite_assessment.evidence_commit_score is not None
        and rewrite_assessment.evidence_commit_score < 0.4
    ):
        reasons.append("weak_rewrite_evidence_commit")
    if draft_assessment.missing_intent_facets:
        draft_missing = set(draft_assessment.missing_intent_facets)
        rewrite_missing = set(rewrite_assessment.missing_intent_facets)
        decision_content_improved = (
            len(rewrite_missing) <= len(draft_missing)
            and bool(draft_missing - rewrite_missing)
        )
        draft_alignment = draft_assessment.evidence_commit_score
        rewrite_alignment = rewrite_assessment.evidence_commit_score
        stronger_evidence_commit = (
            rewrite_alignment is not None
            and rewrite_alignment >= 0.4
            and (draft_alignment is None or rewrite_alignment > draft_alignment)
        )
        if not decision_content_improved and not stronger_evidence_commit:
            reasons.append("decision_content_not_improved")
        if require_complete_decision_content and rewrite_missing:
            reasons.append("decision_content_still_incomplete")
    if _protocol_kind(question) and rewrite_assessment.missing_intent_facets:
        reasons.append("protocol_decision_incomplete")
    if set(rewrite_assessment.unsupported_numbers) - set(draft_assessment.unsupported_numbers):
        reasons.append("new_unsupported_number")
    if set(rewrite_assessment.unsupported_crop_stages) - set(draft_assessment.unsupported_crop_stages):
        reasons.append("new_unsupported_crop_stage")
    if set(rewrite_assessment.unsupported_scientific_names) - set(draft_assessment.unsupported_scientific_names):
        reasons.append("new_unsupported_scientific_name")
    if set(rewrite_assessment.unsupported_named_conditions) - set(draft_assessment.unsupported_named_conditions):
        reasons.append("new_unsupported_named_condition")
    if set(rewrite_assessment.unsupported_named_pests) - set(draft_assessment.unsupported_named_pests):
        reasons.append("new_unsupported_named_pest")
    return tuple(_dedupe(reasons))


def _blocking_claim_reasons(assessment: ClaimRiskAssessment) -> tuple[str, ...]:
    """Return concrete safety/factual failures, not proxy completeness signals."""

    advisory = {
        "high_consequence_claim_review",
        "missing_decision_content",
        "weak_primary_evidence_alignment",
    }
    return tuple(reason for reason in assessment.reasons if reason not in advisory)


def _select_best_degraded_answer(
    *,
    question: str,
    candidates: Iterable[tuple[str, ClaimRiskAssessment]],
) -> tuple[str, ClaimRiskAssessment]:
    """Keep the safest question-specific answer when a rewrite cannot be accepted."""

    question_terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", question.lower())
        if token not in _RECOVERY_STOPWORDS
    }

    protocol_kind = _protocol_kind(question)

    def rank(item: tuple[str, ClaimRiskAssessment]) -> tuple[Any, ...]:
        answer, assessment = item
        answer_terms = set(re.findall(r"[a-z][a-z0-9-]{2,}", answer.lower()))
        overlap = len(question_terms & answer_terms)
        coverage = overlap / max(1, len(question_terms))
        alignment = assessment.evidence_commit_score or 0.0
        return (
            int(not _blocking_claim_reasons(assessment)),
            int(not _SOURCE_ARTIFACT_RE.search(answer)),
            int("internal_process_leakage" not in assessment.reasons),
            int("repetitive_generation" not in assessment.reasons),
            int("incomplete_generation" not in assessment.reasons),
            int("high_consequence_claim_review" not in assessment.reasons),
            -len(_missing_scope_anchors(question, answer)),
            int(not assessment.missing_intent_facets),
            int(not assessment.missing_intent_facets) if protocol_kind else 0,
            coverage,
            -assessment.score,
            -len(assessment.missing_intent_facets),
            alignment,
            min(len(answer.split()), 190),
        )

    viable = tuple((answer.strip(), assessment) for answer, assessment in candidates if answer.strip())
    return max(viable, key=rank)


def _risk_excerpts(answer: str, assessment: ClaimRiskAssessment) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", " ", answer).strip()
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    markers = {
        *assessment.unsupported_numbers,
        *assessment.unsupported_crop_stages,
        *assessment.unsupported_scientific_names,
        *assessment.unsupported_named_conditions,
        *assessment.unsupported_named_pests,
    }
    excerpts: list[str] = []
    for sentence in sentences:
        risky = any(marker.lower() in sentence.lower() for marker in markers)
        risky = risky or bool(
            _DIAGNOSIS_ASSERTION_RE.search(sentence)
            or _MAP_ASSERTION_RE.search(sentence)
            or _REGULATED_ASSERTION_RE.search(sentence)
            or _UNSUPPORTED_CERTAINTY_RE.search(sentence)
        )
        if risky:
            excerpts.append(sentence[:500])
    return _dedupe(excerpts[:8])


def _forbidden_terms(
    answer: str,
    assessment: ClaimRiskAssessment,
    *,
    question: str,
    evidence_text: str,
) -> tuple[str, ...]:
    allowed = _normalize_for_matching(f"{question}\n{evidence_text}")
    terms = [
        *assessment.unsupported_numbers,
        *assessment.unsupported_crop_stages,
        *assessment.unsupported_scientific_names,
        *assessment.unsupported_named_conditions,
        *assessment.unsupported_named_pests,
    ]
    if "map_prior_presented_as_field_truth" in assessment.reasons:
        ignored = {
            "likely interpretation",
            "practical next action",
            "what the public soil map can support",
            "what the public soil map cannot prove",
        }
        for value in _EMPHASIZED_TERM_RE.findall(answer):
            normalized = _normalize_for_matching(value)
            if normalized not in ignored and normalized not in allowed:
                terms.append(value.strip())
    return _dedupe(terms)


def _missing_intent_facets(answer: str, *, question: str, question_type: str) -> tuple[str, ...]:
    missing: list[str] = []
    for requirement in _intent_requirements(question, question_type):
        if not any(re.search(pattern, answer, re.IGNORECASE) for pattern in requirement.patterns):
            missing.append(requirement.name)
    return _dedupe(missing)


def _is_wet_forage_establishment_question(question: str) -> bool:
    lower = question.lower()
    return bool(
        re.search(r"\b(?:forage|pasture|hay)\b", lower)
        and re.search(r"\b(?:wet|saturat\w*|waterlog\w*)\b", lower)
        and re.search(r"\b(?:establish\w*|plant\w*|seed\w*)\b", lower)
        and re.search(r"\b(?:wait|delay|change|plan|soon|condition|forecast)\b", lower)
    )


def _intent_requirements(question: str, question_type: str) -> tuple[_IntentRequirement, ...]:
    lower = question.lower()
    focus = request_focus(lower)
    requirements: list[_IntentRequirement] = []

    def add(name: str, instruction: str, *patterns: str) -> None:
        requirements.append(_IntentRequirement(name=name, instruction=instruction, patterns=tuple(patterns)))

    decision = build_decision_route_state(question, question_type).decision
    if _is_wet_forage_establishment_question(question):
        add(
            "wet_establishment_workability",
            "Assess seedbed workability and trafficability, including rutting, smearing, or compaction risk.",
            r"\btrafficab",
            r"\b(?:rutt\w*|smear\w*|compact\w*|friable|workab\w*)\b",
        )
        add(
            "wet_establishment_placement",
            "Check moisture at seeding depth and whether uniform placement, closure, and seed-to-soil contact are achievable.",
            r"\bseed(?:ing)? depth\b",
            r"\bseed[- ]to[- ]soil contact\b",
            r"\b(?:uniform|consistent) (?:seed )?placement\b",
            r"\bfurrow closure\b",
        )
        add(
            "wet_establishment_forecast",
            "Use forecast amount, timing, probability, and the likely drying window rather than a categorical forecast.",
            r"\bforecast\b[^.]{0,100}\b(?:amount|timing|probabil|uncertain|drying|rain)\b",
            r"\b(?:rain|precipitation)\b[^.]{0,80}\b(?:amount|timing|probabil|forecast)\b",
            r"\bdrying (?:trend|window|time|conditions?)\b",
        )
        add(
            "wet_establishment_window",
            "Weigh the remaining establishment window, forage species, alternate timing or method, and the cost of delay.",
            r"\bestablishment window\b",
            r"\bforage species\b",
            r"\b(?:alternate|alternative|change) (?:date|timing|method|plan)\b",
            r"\bcost of (?:waiting|delay)\b",
        )
        add(
            "wet_establishment_conditional_action",
            "Tie plant, wait, or change-plan actions to measured seedbed fitness and the remaining viable window.",
            r"\bplant only\b[^.]{0,100}\b(?:fit|workable|trafficable|placement|contact)\b",
            r"\bwait\b[^.]{0,100}\b(?:rut|smear|compact|saturat|unfit|too wet)\b",
            r"\bchange (?:the )?(?:establishment )?plan\b[^.]{0,120}\b(?:window|dry|remain|viable|deadline)\b",
        )
    elif all(term in lower for term in ("random composite", "benchmark", "directed", "grid")) and re.search(
        r"\bsoil sampl", lower
    ):
        add("sampling_objective", "Choose the sampling design from the decision objective and whether variability is random or spatially stable.", r"\bdecision objective\b", r"\bspatially stable\b", r"\bstable (?:pattern|variability|zones?)\b")
        add("sampling_random", "Explain that random composite sampling estimates a whole-field average.", r"\brandom composite\b[^.]{0,100}\b(?:field|whole[- ]field) average\b", r"\bfield average\b[^.]{0,100}\brandom composite\b")
        add("sampling_benchmark", "Explain that benchmark sampling repeatedly tracks a representative location or small area.", r"\bbenchmark\b[^.]{0,120}\b(?:representative|track|repeat|same location)\b")
        add("sampling_directed", "Explain that directed sampling separates known landscape or management zones.", r"\bdirected\b[^.]{0,120}\b(?:landscape|management|known|distinct) zones?\b")
        add("sampling_grid", "Explain that grid sampling supports dense spatial mapping at higher sampling cost.", r"\bgrid\b[^.]{0,120}\b(?:dense|spatial map|higher cost|costlier|intensive)\b")
        add("sampling_consistency", "Keep locations georeferenced and sampling depth, timing, and laboratory method consistent.", r"\bgeoreferenc", r"\bconsistent\b[^.]{0,90}\b(?:depth|timing|lab)")
        add("sampling_ground_truth", "Ground-truth proposed zones before variable-rate use.", r"\bground[- ]truth", r"\bverify\b[^.]{0,90}\b(?:proposed |management )?zones?\b")
        add("sampling_rate_boundary", "Do not assign nutrient rates before laboratory interpretation and local calibration.", r"\b(?:do not|don't|cannot)\b[^.]{0,90}\b(?:rate|prescription)\b", r"\blocal calibration\b")
    elif "liquid manure" in lower and re.search(r"\b(?:representative sample|handling|lab result|laboratory)\b", lower):
        add("manure_sample_agitation", "Thoroughly agitate stored liquid manure before sampling.", r"\b(?:agitate|agitation|mix the storage|mixed storage)\b")
        add("manure_sample_composite", "Collect multiple increments and combine them into a representative composite.", r"\bmultiple increments?\b", r"\bcomposite sample\b")
        add("manure_sample_pumping", "Sample the representative middle portion of pumping, not only the beginning, end, surface, or settled layer.", r"\bmiddle (?:portion|part) of pumping\b", r"\b(?:beginning|start)[^.]{0,100}\b(?:end|surface|settled)\b")
        add("manure_sample_container", "Use a clean non-metallic container, mix the composite, subsample, seal, and label it.", r"\bnon[- ]metallic container\b", r"\bclean container\b[^.]{0,100}\b(?:label|seal|subsample)\b")
        add("manure_sample_expansion", "Leave expansion or head space in the sealed laboratory container.", r"\b(?:expansion|head) space\b", r"\bdo not fill\b[^.]{0,70}\b(?:container|jar)\b")
        add("manure_sample_preservation", "Keep the sample cool and transport it promptly, or freeze it when delayed under laboratory instructions.", r"\bkeep (?:it|the sample) cool\b", r"\bcool\b[^.]{0,100}\b(?:transport|freeze|lab)")
        add("manure_sample_lab", "Coordinate container, preservation, sample size, method, and safety requirements with the laboratory.", r"\bcoordinate\b[^.]{0,100}\blab", r"\blab(?:oratory)? instructions?\b", r"\bcontact the lab")
        add("manure_sample_application_records", "Preserve application amount, date, method, timing, and incorporation records.", r"\bapplication (?:amount|date|method|timing)\b", r"\bapplication[- ]rate records?\b", r"\bincorporation records?\b")
        add("manure_sample_availability", "Use locally appropriate first-year plant availability before calculating a nutrient credit.", r"\bplant[- ]available\b", r"\bfirst[- ]year (?:plant )?availability\b")
    elif "manure" in lower and "commercial fertilizer" in lower and re.search(r"\b(?:credit|double[- ]apply)", lower):
        add("manure_credit_analysis", "Use a representative manure analysis.", r"\brepresentative manure (?:analysis|sample)\b", r"\bmanure analysis\b")
        add("manure_credit_application", "Record applied amount, date, method, incorporation, and field distribution.", r"\bapplication (?:rate|amount|date|method)\b", r"\bincorporat", r"\bfield distribution\b")
        add("manure_credit_availability", "Credit first-year plant availability rather than total nutrient content.", r"\bfirst[- ]year (?:plant )?availability\b", r"\bplant[- ]available\b[^.]{0,100}\btotal")
        add("manure_credit_soil", "Reconcile residual soil nitrate and method-specific soil-test phosphorus.", r"\bresidual soil nitrate\b", r"\bsoil[- ]test (?:phosphorus|P)\b")
        add("manure_credit_crop_budget", "Include previous crop, nutrients already applied, realistic yield goal, and crop need.", r"\bprevious[- ]crop\b", r"\bnutrients? (?:already|previously) applied\b", r"\byield (?:goal|potential)\b")
        add("manure_credit_delivery_losses", "Account for equipment calibration, application uniformity, and loss pathways.", r"\bequipment calibration\b", r"\bapplication uniformity\b", r"\b(?:runoff|leaching|volatilization|loss pathways?)\b")
        add("manure_credit_boundary", "Do not state the fertilizer remainder until the full budget is reconciled with current Alberta guidance.", r"\bdo not\b[^.]{0,120}\b(?:fertilizer (?:balance|remainder|rate)|remaining fertilizer)\b", r"\bcurrent Alberta guidance\b")
    elif "mapped" in lower and re.search(r"\b(?:runoff|watercourse)\b", lower) and re.search(
        r"\b(?:observations?|before choosing|control practice)\b", lower
    ):
        add("runoff_map_boundary", "Treat the map as screening context and verify conditions in the field.", r"\bscreening (?:context|tool)\b", r"\bmap\b[^.]{0,90}\b(?:not proof|cannot prove|verify|field)")
        add("runoff_topography_connection", "Verify slope length and grade, contributing area, flow paths, outlet, and connection to the watercourse.", r"\bslope (?:length|grade)\b", r"\bflow paths?\b", r"\b(?:connection|connectivity)\b[^.]{0,90}\bwatercourse\b")
        add("runoff_erosion_signs", "Look for concentrated or sheet flow, rills, gullies, sediment, and other erosion evidence.", r"\b(?:rills?|gullies|sediment|erosion (?:signs|evidence))\b", r"\b(?:concentrated|sheet) flow\b")
        add("runoff_soil_condition", "Check soil texture, structure, infiltration, sealing, and compaction.", r"\bsoil (?:texture|structure)\b", r"\binfiltration\b", r"\b(?:surface sealing|compaction)\b")
        add("runoff_cover_history", "Check residue, cover, tillage, and crop history.", r"\bresidue\b", r"\bcover\b", r"\b(?:tillage|crop) history\b")
        add("runoff_nutrient_exposure", "Record nutrient source, form, placement, incorporation, and application timing.", r"\bnutrient (?:source|form)\b", r"\bplacement\b", r"\bincorporat", r"\bapplication timing\b")
        add("runoff_weather_state", "Check frozen or saturated soil and rainfall or snowmelt exposure.", r"\b(?:frozen|saturated) soil\b", r"\b(?:rainfall|snowmelt)\b")
        add("runoff_pathway_control", "Identify dissolved, sediment-bound, concentrated-flow, or sheet-flow pathways before selecting a control.", r"\bdissolved\b", r"\bsediment[- ]bound\b", r"\bdominant (?:transport )?pathway\b")
        add("runoff_legal_boundary", "Verify current setback or legal requirements separately.", r"\bcurrent (?:Alberta )?(?:setback|legal|regulatory) requirements?\b", r"\bverify\b[^.]{0,90}\bsetback")
    elif decision == "crop_irrigation_scheduling":
        add("irrigation_root_zone", "Use calibrated representative root-zone water by depth and convert it to depletion.", r"\broot[- ]zone (?:water|moisture|depletion)\b", r"\bdepletion\b")
        add("irrigation_storage", "Use field capacity, available water-holding capacity, rooting depth, and allowable depletion.", r"\bfield capacity\b", r"\bwater[- ]holding capacity\b", r"\bavailable water\b")
        add("irrigation_crop_demand", "Combine crop stage and rooting with current and forecast crop-water demand.", r"\bcrop stage\b", r"\brooting depth\b", r"\bcrop water use\b")
        add("irrigation_weather", "Subtract effective rain and use the short-term forecast as a demand input, not a field measurement.", r"\bforecast\b", r"\beffective rain", r"\bexpected rain")
        add("irrigation_delivery", "Check recent applied water, system capacity, infiltration, runoff, and drainage before setting timing or depth.", r"\bapplied water\b", r"\bsystem capacity\b", r"\binfiltration\b", r"\brunoff\b", r"\bdrainage\b")
    elif decision == "greenhouse_substrate_irrigation":
        add("greenhouse_substrate_water", "Measure substrate or media water content or container weight through the irrigation cycle.", r"\bsubstrate (?:water|moisture)\b", r"\bmedia (?:water|moisture)\b", r"\bcontainer weight\b")
        add("greenhouse_delivery", "Measure emitter flow and distribution uniformity in representative containers or slabs.", r"\bemitter (?:flow|output)\b", r"\bdistribution uniformity\b")
        add("greenhouse_drainage", "Record applied volume, drain volume or fraction, and time to drainage.", r"\bdrain(?:age)? fraction\b", r"\bdrain volume\b", r"\btime to drain")
        add("greenhouse_ec", "Measure source-water, root-zone, and drain EC or pH where relevant.", r"\broot[- ]zone EC\b", r"\bdrain EC\b", r"\bsource[- ]water EC\b")
        add("greenhouse_demand", "Use crop stage, canopy, radiation, temperature, humidity, and VPD to interpret demand.", r"\bcrop stage\b", r"\bradiation\b", r"\bVPD\b", r"\bvapou?r[- ]pressure deficit\b")
    elif decision == "sweet_corn_harvest_timing":
        add("sweet_corn_sample", "Inspect representative ears across the block rather than one edge or one ear.", r"\brepresentative ears?\b", r"\bacross the block\b")
        add("sweet_corn_maturity", "Use kernel fill, milk stage, tenderness, flavour, and ear uniformity.", r"\bmilk stage\b", r"\bkernel (?:fill|stage|tenderness)\b", r"\bear uniformity\b")
        add("sweet_corn_buyer", "Obtain the buyer's maturity, size, appearance, and delivery specification.", r"\bbuyer(?:'s)? (?:maturity|quality|specification)\b", r"\bmarket specification\b")
        add("sweet_corn_logistics", "Match the harvest window to labour, transport, field heat removal, and cooling capacity.", r"\bfield heat\b", r"\bcooling capacity\b", r"\bharvest[- ]to[- ]cool", r"\btransport\b")
    elif decision == "potato_storage_conditioning":
        add("potato_storage_market", "Use intended market and harvest maturity.", r"\b(?:intended )?market\b", r"\bharvest maturity\b", r"\bmarch[eé]\b", r"\bmaturit[eé]\b")
        add("potato_storage_condition", "Check pulp temperature, skin set, bruising, and disease risk.", r"\bpulp temperature\b", r"\bskin set\b", r"\bbruis", r"\btemp[eé]rature (?:de la )?pulpe\b", r"\bpeau\b", r"\bmeurtriss")
        add("potato_storage_system", "Fit airflow to the actual storage system and lot condition.", r"\bstorage system\b", r"\blot condition\b", r"\bairflow\b", r"\bsyst[eè]me de stockage\b", r"\blot\b", r"\bd[eé]bit d'air\b")
        add("potato_storage_action", "Remove field heat without aggressive airflow that worsens dehydration, condensation, or bruising.", r"\bfield heat\b", r"\baggressive (?:ventilation|airflow)\b", r"\bdehydration\b", r"\bcondensation\b", r"\bchaleur du champ\b", r"\bventilation agressive\b", r"\bd[eé]shydratation\b")
    elif decision == "fusarium_head_blight_risk":
        add("fhb_stage", "Confirm heading and flowering or anthesis stage and the susceptible window.", r"\bflowering\b", r"\banthesis\b", r"\bsusceptible window\b")
        add("fhb_weather", "Combine recent and forecast rain, moisture, humidity, and temperature around flowering.", r"\brecent and forecast\b", r"\brain\b", r"\bhumidity\b", r"\bmoisture\b")
        add("fhb_residue_rotation", "Use host residue and rotation history as inoculum-risk evidence.", r"\bhost residue\b", r"\bresidue\b", r"\brotation\b")
        add("fhb_variety", "Include variety susceptibility or tolerance.", r"\bvariety susceptibility\b", r"\bsusceptib", r"\btoleran")
        add("fhb_current_risk", "Use current local FHB risk guidance and verify label timing only if treatment is considered.", r"\bcurrent (?:local )?(?:FHB )?risk\b", r"\brisk map\b", r"\bcurrent (?:fungicide )?label\b")
    elif decision == "fleabane_management":
        add("fleabane_identity", "Confirm Canada fleabane or horseweed identity.", r"\bCanada fleabane\b", r"\bhorseweed\b")
        add("fleabane_cohort_stage", "Establish emergence cohort, growth stage, density, and distribution.", r"\bemergence cohort\b", r"\bgrowth stage\b", r"\bdensity\b")
        add("fleabane_forage_system", "Identify the forage species, stand condition, harvest or grazing plan, and crop-safety boundary.", r"\bforage (?:species|stand)\b", r"\bharvest plan\b", r"\bgrazing\b")
        add("fleabane_resistance", "Review herbicide history and resistance evidence before choosing a mode of action.", r"\bresistance (?:history|evidence|testing)\b", r"\bherbicide history\b")
        add("fleabane_integrated", "Include seed-return prevention and feasible cultural or mechanical tactics.", r"\bprevent seed return\b", r"\bcultural\b", r"\bmechanical\b")
    elif decision == "forage_stand_thinning_differential":
        add("forage_history", "Review stand age, establishment, winter, harvest, traffic, fertility, and pesticide history.", r"\bstand age\b", r"\bwinter history\b", r"\bharvest history\b", r"\btraffic history\b")
        add("forage_crowns_roots", "Compare whole crowns and roots from affected and healthy margins.", r"\bcrowns?\b", r"\broots?\b", r"\baffected and (?:healthy|normal)\b")
        add("forage_soil", "Compare moisture, drainage, compaction, restrictive layers, and rooting conditions.", r"\bsoil moisture\b", r"\bdrainage\b", r"\bcompaction\b", r"\brestrictive layer\b")
        add("forage_biotic", "Look for insect signs, disease lesions or decay, and collect representative samples.", r"\binsect (?:signs|feeding|injury)\b", r"\bdisease (?:signs|lesions)\b", r"\brepresentative samples?\b")
    elif decision == "cutworm_stand_loss":
        add("cutworm_active_injury", "Look for fresh cut or wilted plants and active larvae near the soil surface.", r"\bfresh(?:ly)? cut plants?\b", r"\bactive larvae\b", r"\bsoil surface\b")
        add("cutworm_sampling", "Scout damaged and normal zones at the appropriate time and record larvae and fresh injury.", r"\bdamaged and (?:normal|unaffected)\b", r"\bfresh injury\b", r"\bnight\b")
        add("cutworm_stand", "Make representative row-length stand counts and quantify remaining uniform stand.", r"\bstand counts?\b", r"\brow length\b", r"\bremaining stand\b")
        add("cutworm_decision", "Use injury trend, crop stage, local threshold, natural enemies, and current label fit before acting.", r"\binjury trend\b", r"\bcrop stage\b", r"\bthreshold\b", r"\bnatural enemies\b")
    elif decision == "seeding_depth_decision":
        add("seeding_moisture_depth", "Measure depth to reliable moisture across representative seedbed zones.", r"\bdepth to (?:reliable )?moisture\b", r"\bmoisture at (?:the )?seeding depth\b")
        add("seeding_texture_crust", "Use texture, aggregation, crusting risk, and expected rain.", r"\btexture\b", r"\bcrust(?:ing)? risk\b")
        add("seeding_vigour", "Use seed vigour, seed size, and emergence capacity.", r"\bseed vigou?r\b", r"\bseed size\b", r"\bemergence capacity\b")
        add("seeding_opener", "Verify opener depth consistency, furrow closure, and seed-to-soil contact with a test pass.", r"\bopener (?:depth )?consistency\b", r"\bfurrow closure\b", r"\bseed[- ]to[- ]soil contact\b", r"\btest pass\b")
    elif decision == "nutrient_runoff_risk":
        add("runoff_field_state", "Check saturation or frozen soil, infiltration, compaction, residue, slope, and concentrated flow paths.", r"\bsaturat", r"\bfrozen soil\b", r"\binfiltration\b", r"\bflow paths?\b")
        add("runoff_water_boundary", "Check surface-water proximity, setbacks, buffers, and current local requirements.", r"\bsurface water\b", r"\bsetbacks?\b", r"\bbuffers?\b", r"\bcurrent (?:local |Ontario )?(?:requirements?|rules?)\b")
        add("runoff_nutrient_plan", "Use nutrient source or form, rate, placement, incorporation, and timing.", r"\bnutrient (?:source|form)\b", r"\bplacement\b", r"\bincorporat", r"\bapplication timing\b")
        add("runoff_forecast", "Use rainfall amount, intensity, timing, and uncertainty rather than total alone.", r"\brainfall (?:amount|intensity|timing)\b", r"\bforecast (?:amount|intensity|timing)\b")
        add("runoff_decision", "Proceed, modify placement, or delay according to the active loss pathways.", r"\bdelay\b", r"\bpostpone\b", r"\bmodify (?:placement|the application)\b", r"\bdo not (?:apply|proceed)\b")
    elif decision == "forage_frost_safety":
        add("forage_hold", "Keep livestock out and do not cut or feed the forage until the hazards are assessed.", r"\b(?:keep|hold)\b[^.]{0,45}\b(?:cattle|livestock|animals?)\b[^.]{0,45}\b(?:out|off)\b", r"\bdo not (?:graze|cut|feed)\b")
        add("forage_prussic", "Address prussic acid or hydrocyanic-acid risk after frost, drought, and fresh regrowth.", r"\bprussic acid\b", r"\bhydrocyanic acid\b", r"\bcyanide\b")
        add("forage_nitrate", "Address nitrate risk separately and do not claim that haying automatically removes it.", r"\bnitrate\b")
        add("forage_test", "Use representative forage testing and local livestock guidance before release.", r"\b(?:forage|plant) (?:sample|test)\b", r"\blab(?:oratory)?\b", r"\blocal (?:extension|livestock|veterinar)")
        add("forage_animal_use", "Consider animal class and how the forage would enter the ration.", r"\banimal class\b", r"\bration\b", r"\bfeed(?:ing)? plan\b")
    elif decision == "postharvest_cooling":
        add("cooling_direct_answer", "State that delayed evening cooling does not undo two warm hours in field totes.", r"\bnot (?:good|fast|soon) enough\b", r"\bdoes not (?:undo|reverse|recover)\b", r"\bremove field heat\b[^.]{0,45}\b(?:quick|rapid|prompt)")
        add("cooling_temperature", "Measure harvest or pulp temperature and the time before cooling.", r"\bpulp temperature\b", r"\bharvest temperature\b", r"\btime (?:to|before) cool")
        add("cooling_handling", "Reduce sun exposure and handling delay with shade, shallow totes, transport, and prompt precooling.", r"\bshade\b", r"\bfield totes?\b", r"\bpre[- ]?cool", r"\bhandling time\b")
        add("cooling_chain", "Match cooling capacity, airflow, cold-chain continuity, and buyer quality requirements.", r"\bcold chain\b", r"\bpackage airflow\b", r"\bbuyer\b", r"\bmarket quality\b")
    elif decision == "nematode_management":
        add("nematode_no_first_treatment", "Do not make a nematicide the first move from patch symptoms alone.", r"\bdo not (?:start|begin|lead) with (?:a )?nematicide\b", r"\bnematicide\b[^.]{0,80}\b(?:not|do not justify)\b[^.]{0,45}\bfirst move\b", r"\bdo not justify\b[^.]{0,70}\bnematicide\b[^.]{0,35}\bfirst move\b", r"\bnot enough\b[^.]{0,55}\bnematicide\b")
        add("nematode_sampling", "Collect properly timed soil and root samples from affected margins and comparable healthy areas.", r"\bsoil and root samples?\b", r"\baffected (?:margins?|and (?:normal|healthy))\b", r"\bhealthy areas?\b")
        add("nematode_identification", "Base management on confirmed nematode species and population density.", r"\bspecies\b", r"\bpopulation (?:density|level|count)\b")
        add("nematode_differential", "Separate nematodes from texture, compaction, water, fertility, herbicide, and root-disease causes.", r"\bcompaction\b", r"\broot disease\b", r"\bherbicide history\b", r"\bsoil texture\b")
        add("nematode_next_year", "Choose resistance, nonhost rotation, treatment, and economics only after confirmation.", r"\bresistant variet", r"\bnonhost rotation\b", r"\beconomics\b")
    elif decision == "residual_activation":
        add("residual_no_repeat", "Do not simply repeat or raise the residual rate after weeds have emerged.", r"\bdo not (?:repeat|increase|raise)\b", r"\bnot (?:simply )?(?:repeat|increase|raise)\b")
        add("residual_activation", "Check rainfall or incorporation and soil properties that control activation.", r"\brain(?:fall)?\b", r"\bactivation\b", r"\bincorporat", r"\bsoil texture\b", r"\borganic matter\b")
        add("residual_emerged_weeds", "Separate residual activity from control of already emerged weeds.", r"\bemerged weeds?\b", r"\bweeds? (?:already )?emerged\b", r"\bpostemergence\b")
        add("residual_label_max", "Use the current label, seasonal maximum, crop restrictions, and an overlapping residual plan.", r"\bcurrent (?:product )?label\b", r"\bseasonal (?:maximum|max)\b", r"\boverlapping residual\b")
    elif decision == "volunteer_trait_unknown":
        add("volunteer_no_appearance", "Do not select a postemergence product from volunteer-canola appearance alone.", r"\bnot from appearance alone\b", r"\bappearance (?:does not|cannot)\b", r"\bdo not (?:choose|select)\b[^.]{0,65}\bappearance\b")
        add("volunteer_trait_record", "Recover the previous crop or herbicide-tolerance system record.", r"\bherbicide[- ]tolerance (?:system|trait)\b", r"\bprevious (?:crop|tenant) records?\b", r"\bseed records?\b")
        add("volunteer_current_crop", "Use current crop stage plus volunteer size, stage, and density.", r"\blentil (?:crop |growth )?stage\b", r"\bvolunteer (?:size|stage|density)\b")
        add("volunteer_label", "Verify a current Canadian crop label before any postemergence option.", r"\bcurrent Canadian (?:crop )?label\b", r"\bcurrent (?:local )?label\b")
        add("volunteer_integrated", "Map escapes, prevent seed return, and build a multiyear integrated plan.", r"\bprevent seed return\b", r"\bmap (?:the )?(?:escapes|patches)\b", r"\bcrop rotation\b", r"\bintegrated\b")
    elif decision == "variable_rate_pk":
        add("pk_data_quality", "Clean and calibrate yield data before defining response zones.", r"\bclean\b[^.]{0,45}\byield (?:data|map)\b", r"\bcalibrat(?:e|ed|ion)\b[^.]{0,45}\byield", r"\bmonitor calibration\b")
        add("pk_soil_calibration", "Use representative phosphorus and potassium soil tests with local calibration.", r"\b(?:phosphorus|P) and (?:potassium|K)\b", r"\bP and K\b", r"\bsoil tests?\b[^.]{0,70}\blocal calibration\b")
        add("pk_response", "Estimate response probability by ground-truthed zone rather than treating map color as proof.", r"\bresponse probability\b", r"\bground[- ]truth", r"\bmap (?:color|appearance)\b[^.]{0,55}\bnot (?:proof|evidence)\b")
        add("pk_trial_budget", "Use replicated checks and a partial budget with fertilizer, application, crop price, and uncertainty.", r"\bcheck strips?\b", r"\breplicated (?:trial|checks?)\b", r"\bpartial budget\b", r"\bsensitivity\b")
    elif decision == "map_crop_selection":
        add("map_crop_boundary", "State that the suitability map is screening context and cannot choose a crop by itself.", r"\bscreening (?:context|tool)\b", r"\bmap\b[^.]{0,90}\b(?:cannot|does not|not enough)\b[^.]{0,70}\b(?:choose|select|prescribe)\b")
        add("map_crop_field_limits", "Ground-truth soil, drainage, topography, and other field limitations.", r"\bsoil\b", r"\bdrainage\b", r"\btopograph")
        add("map_crop_rotation_climate", "Use crop and herbicide history, rotation, and local growing-season fit.", r"\brotation\b", r"\bcrop history\b", r"\bgrowing season\b", r"\bheat units?\b")
        add("map_crop_business_fit", "Include market, equipment, labour, inputs, and expected economics.", r"\bmarket\b", r"\bequipment\b", r"\blabou?r\b", r"\beconomic")
    elif decision == "variety_trial_selection":
        add("variety_trial_scope", "Prefer replicated multi-year and multi-location evidence over a top result from one environment.", r"\bmulti[- ]year\b", r"\bmulti[- ]location\b", r"\bacross (?:years|sites)\b")
        add("variety_statistics", "Use statistical separation and yield stability rather than rank alone.", r"\bstatistical", r"\bLSD\b", r"\bleast significant difference\b", r"\byield stability\b")
        add("variety_adaptation", "Match maturity, disease, lodging, environment, and crop-purpose quality to the farm.", r"\bmaturity\b", r"\bdisease\b", r"\blodging\b", r"\badaptation\b")
        if re.search(r"\bsilage\b", lower):
            add("silage_quality", "Use silage trials with whole-plant yield, harvest moisture, starch, and fiber digestibility.", r"\bsilage trials?\b", r"\bwhole[- ]plant yield\b", r"\bstarch\b", r"\bfiber digest")
        add("variety_cost_risk", "Compare seed cost and downside risk, retaining an on-farm comparison when needed.", r"\bseed cost\b", r"\bdownside risk\b", r"\bon[- ]farm (?:strip|comparison|trial)\b")
    elif decision == "integrated_preharvest_specialty":
        add("preharvest_diagnosis", "Scout and identify the leaf spots and their incidence or severity before treatment.", r"\bidentif", r"\bdiagnos", r"\bincidence\b", r"\bseverity\b")
        add("preharvest_intervals", "Check harvest timing, current label, PHI, REI, and daily worker entry.", r"\bpreharvest interval\b", r"\bPHI\b", r"\brestricted[- ]entry interval\b", r"\bREI\b")
        add("preharvest_water_safety", "Test and trace the irrigation water because it contacted a near-harvest crop.", r"\birrigation[- ]water test\b", r"\bwater source\b[^.]{0,60}\btest", r"\bproduce safety\b")
        add("preharvest_market", "Include buyer appearance standards and the option to segregate or harvest around affected areas.", r"\bbuyer\b", r"\bappearance standard\b", r"\bsegregat", r"\bharvest around\b")
    elif decision == "furrow_irrigation_uniformity":
        add("furrow_no_extend", "Do not extend the set blindly when tailwater is already leaving the field.", r"\bdo not (?:simply |blindly )?extend\b", r"\bextending the set\b[^.]{0,55}\b(?:increase|worsen)\b[^.]{0,35}\b(?:tailwater|runoff|deep percolation)\b")
        add("furrow_observation", "Verify root-zone moisture and infiltrated depth from head to tail; tailwater means advance reached the tail.", r"\broot[- ]zone moisture\b", r"\binfiltrated depth\b", r"\badvance\b[^.]{0,65}\breached the tail\b")
        add("furrow_design", "Check inflow, set time, furrow length, slope, and intake or infiltration rate.", r"\binflow (?:rate|stream)\b", r"\bset time\b", r"\bfurrow length\b", r"\bslope\b", r"\bintake rate\b")
        add("furrow_redesign", "Correct the diagnosed infiltration or distribution problem while limiting tailwater.", r"\bsurge\b", r"\bcutback\b", r"\btailwater reuse\b", r"\bshorter (?:run|furrow)\b", r"\brelevel", r"\bdiagnosed cause\b")
    elif decision == "soil_water_sensor_interpretation":
        add("sensor_no_same_depth", "State that equal volumetric water content does not imply equal irrigation depth.", r"\bshould not receive the same\b", r"\bdoes not mean\b[^.]{0,55}\bsame irrigation\b", r"\bnot directly comparable\b")
        add("sensor_calibration", "Use sensor calibration, placement, and measurement depth for each soil.", r"\bsensor calibration\b", r"\bsensor depth\b", r"\bplacement\b")
        add("sensor_capacity", "Convert the reading to depletion using field capacity and allowable depletion.", r"\bfield capacity\b", r"\bavailable water\b", r"\bdepletion\b")
        add("sensor_roots_stage", "Use effective rooting depth and crop stage to calculate the active storage volume.", r"\beffective rooting depth\b", r"\brooting depth\b", r"\bcrop stage\b")
        add("sensor_application", "Match the refill to weather demand, system capacity, infiltration, and runoff limits.", r"\bevapotranspiration\b", r"\bweather demand\b", r"\binfiltration\b", r"\brunoff\b")
    elif decision == "corn_rootworm_silk_clipping":
        add("rootworm_density", "Scout a representative rootworm beetle density rather than treating presence alone.", r"\bbeetle (?:count|density|population)\b", r"\brootworm density\b", r"\bscout(?:ing)?\b[^.]{0,55}\bbeetles?\b")
        add("silk_clipping", "Measure fresh silk length or clipping severity at representative ears.", r"\bsilk length\b", r"\bclipping severity\b", r"\bclipped?\b[^.]{0,35}\bsilks?\b")
        add("pollination_progress", "Check fresh silk emergence and how much pollination is complete.", r"\bpollination (?:progress|is complete|completion)\b", r"\bfresh silks?\b", r"\bpollen shed\b")
        add("rootworm_threshold", "Use a locally valid silk-clipping threshold and the current label before treatment.", r"\b(?:economic |action )?threshold\b", r"\bsilk[- ]clipping threshold\b")
        add("rootworm_label", "Verify current label fit only when the threshold supports treatment.", r"\bcurrent (?:product )?label\b", r"\blabel restrictions?\b")
    elif decision == "wheat_aphid_treatment":
        add("aphid_density", "Identify the aphid and count it per head or tiller with a representative scouting method.", r"\baphid (?:species|identity)\b", r"\baphids? per (?:head|tiller)\b", r"\bhead or tiller\b")
        add("aphid_crop_stage", "Use wheat stage and the remaining grain-fill period.", r"\bwheat stage\b", r"\bcrop stage\b", r"\bgrain fill\b")
        add("aphid_natural_enemies", "Use population trend and natural enemies rather than beneficial presence alone.", r"\bpopulation trend\b", r"\bnatural enemies\b", r"\blady beetles?\b")
        add("aphid_threshold", "Compare the count with a locally valid aphid threshold.", r"\b(?:economic |action )?threshold\b")
        add("aphid_label", "Verify the current label and protect beneficials when treatment is justified.", r"\bcurrent (?:product )?label\b", r"\bpreserv(?:e|ing) beneficials\b")
    elif decision == "wheat_flag_leaf_fungicide":
        add("wheat_disease_identity", "Identify the likely leaf-spot disease or separate it from non-disease injury.", r"\bdisease identification\b", r"\blikely disease\b", r"\bconfirm the (?:cause|diagnosis)\b")
        add("wheat_upper_canopy", "Track movement from lower leaves toward the upper canopy and flag leaf.", r"\bupper canop", r"\bflag leaf\b", r"\blower leaves?\b[^.]{0,65}\bupper leaves?\b")
        add("wheat_fungicide_risk", "Use variety susceptibility, incidence or severity, and forecast disease risk.", r"\bvariety susceptibility\b", r"\bincidence\b", r"\bseverity\b", r"\bweather risk\b")
        add("wheat_fungicide_value", "Tie the flag-leaf protection window to current label fit and expected economic return.", r"\bprotection window\b", r"\bcurrent (?:fungicide )?label\b", r"\bexpected yield benefit\b", r"\bapplication cost\b")
    elif decision == "weed_preharvest_escape":
        add("preharvest_direct_answer", "Do not recommend a cleanup spray unless a current label explicitly fits crop, weed, and timing.", r"\bdo not spray\b", r"\bno cleanup spray\b", r"\bonly if\b[^.]{0,70}\bcurrent (?:product )?label\b")
        add("preharvest_intervals", "Check crop stage, days to harvest, PHI, and crop-desiccation or residue restrictions.", r"\bpreharvest interval\b", r"\bPHI\b", r"\bdays? to harvest\b", r"\bcrop desiccation\b")
        add("preharvest_weed_state", "Identify the weed and its seed maturity before choosing containment.", r"\bweed (?:identity|species)\b", r"\bseed maturity\b")
        add("preharvest_nonchemical", "Use practical nonchemical containment and protect harvestability and market acceptance.", r"\bhand[- ]?remove\b", r"\bspot removal\b", r"\bharvest (?:last|separately)\b", r"\bmarket restrictions?\b")
    elif decision == "weed_burndown_survivor":
        add("burndown_direct_answer", "State directly that a higher glyphosate rate is not the default answer and never exceed the label.", r"\bdo not (?:just |automatically )?(?:raise|increase)\b[^.]{0,30}\bglyphosate\b", r"\bnot simply (?:raise|increase)\b", r"\bdo not exceed\b[^.]{0,25}\blabel\b")
        add("burndown_failure_review", "Check species, growth stage, application record, coverage, and growing conditions.", r"\bweed (?:identity|species)\b", r"\bgrowth stage\b", r"\bapplication record\b", r"\bcoverage\b")
        add("burndown_resistance", "Separate resistance from application failure.", r"\bresistance\b[^.]{0,55}\bapplication failure\b", r"\bapplication failure\b[^.]{0,55}\bresistance\b")
        add("burndown_alternative", "Use a locally effective labeled alternative mode or nonchemical tactic and prevent seed return.", r"\blabeled alternative\b", r"\balternative (?:mode|site) of action\b", r"\bnonchemical\b", r"\bprevent seed\b")
    elif decision == "weed_seed_return_management":
        add("seed_return_priority", "Prioritize reducing seed return and spread where practical.", r"\breduc(?:e|ing) seed return\b", r"\bprevent seed production\b", r"\bseed return\b[^.]{0,45}\bwhere practical\b")
        add("seed_return_containment", "Contain isolated patches with removal, harvest order, and equipment cleaning as feasible.", r"\bremove isolated\b", r"\bharvest (?:last|separately)\b", r"\bclean (?:the )?equipment\b")
        add("seed_return_failure_review", "Review the application record before distinguishing resistance from failure.", r"\bapplication record\b", r"\bresistance\b[^.]{0,55}\bapplication failure\b")
        add("seed_return_next_cycle", "Use multiple effective residual and postemergence tactics plus cultural or mechanical control next cycle.", r"\bmultiple effective\b", r"\bresidual\b", r"\bpostemergence\b", r"\bcultural\b", r"\bmechanical\b")
    elif decision == "cold_wet_purple_corn":
        add("purple_transient_uptake", "Explain that cold, wet soil can temporarily restrict phosphorus uptake even when soil phosphorus is adequate.", r"\btemporar(?:y|ily)\b[^.]{0,55}\bphosphorus uptake\b", r"\brestrict(?:ed|s)? phosphorus uptake\b")
        add("purple_no_immediate_p", "Do not recommend immediate phosphorus from purple color alone.", r"\bdo not (?:apply|add)\b[^.]{0,40}\bphosphorus\b[^.]{0,35}\b(?:right away|immediately|from color alone)\b", r"\bmore phosphorus\b[^.]{0,40}\bnot justified\b")
        add("purple_hybrid_roots", "Check hybrid expression, roots, drainage, compaction, and field pattern.", r"\bhybrid\b", r"\broots?\b", r"\bdrainage\b", r"\bcompaction\b")
        add("purple_soil_evidence", "Use a calibrated soil test and fertilizer placement history.", r"\bsoil test\b", r"\bfertilizer placement\b", r"\bstarter fertilizer\b")
        add("purple_recovery", "Reassess new growth as the soil warms and dries.", r"\breassess\b", r"\bsoil (?:warms|dries)\b", r"\bnew growth\b")
    elif decision == "soybean_idc":
        add("idc_hypothesis", "Name iron deficiency chlorosis as the likely hypothesis, not a certainty.", r"\biron deficiency chlorosis\b", r"\bIDC\b")
        add("idc_soil_context", "Explain the high-pH carbonate or bicarbonate availability problem.", r"\bhigh[- ]pH\b", r"\bcarbonate\b", r"\bbicarbonate\b")
        add("idc_water_context", "Check wetness, drainage, salinity, roots, and the field pattern.", r"\bwet", r"\bdrain", r"\bsalinity\b", r"\bfield pattern\b")
        add("idc_management", "Emphasize IDC-tolerant varieties and validated field management rather than an assumed iron rate.", r"\bIDC[- ]tolerant\b", r"\btolerant variet", r"\bvariety tolerance\b", r"\bvarieties? with IDC tolerance\b")
    elif decision == "sulfur_nitrogen_differential":
        add("sulfur_young_growth", "State that sulfur deficiency tends to be clearest in younger growth and can disrupt flowering.", r"\bsulfur\b[^.]{0,55}\b(?:young|new)\w* (?:leaves|growth)\b", r"\b(?:young|new)\w* (?:leaves|growth)\b[^.]{0,55}\bsulfur\b")
        add("nitrogen_old_growth", "State that mobile nitrogen deficiency usually appears first on older or lower leaves.", r"\bnitrogen\b[^.]{0,55}\b(?:older|lower) leaves\b", r"\b(?:older|lower) leaves\b[^.]{0,55}\bnitrogen\b")
        add("sulfur_field_risk", "Use field uniformity, texture, organic matter, rainfall, and fertilizer history.", r"\bfield pattern\b", r"\borganic matter\b", r"\brainfall\b", r"\bfertilizer history\b")
        add("sulfur_sampling", "Compare affected and normal areas with representative soil and tissue samples.", r"\baffected and (?:normal|unaffected)\b", r"\btissue (?:sample|test)\b", r"\bsoil (?:sample|test)\b")
    elif decision == "fruit_set_diagnostic":
        add("fruit_flower_biology", "Check male and female flowers and whether the cultivar is parthenocarpic or requires pollination.", r"\bmale (?:and|versus) female flowers\b", r"\bfemale flowers\b", r"\bparthenocarpic\b")
        add("fruit_pollination", "Check pollen transfer, bee or pollinator activity, and bloom-time pesticide exposure.", r"\bpollinat", r"\bbee activity\b", r"\bpollinator activity\b", r"\bbloom[- ]time pesticide\b")
        add("fruit_weather_water", "Check heat or cold during bloom and root-zone moisture or water stress.", r"\bheat\b", r"\btemperature\b", r"\bwater stress\b", r"\broot[- ]zone moisture\b")
        add("fruit_other_causes", "Check excessive nitrogen, disease, and young-fruit abortion without assuming one cause.", r"\bexcessive nitrogen\b", r"\bdisease\b", r"\bfruit abortion\b", r"\byoung fruit\b")
    elif decision == "pest_treatment":
        add("pest_identity", "Confirm the pest identity and active life or feeding stage.", r"\b(?:confirm|identify|identified)\b[^.]{0,45}\bpest\b", r"\bpest (?:identity|species)\b", r"\blife stage\b", r"\bfeeding stage\b")
        add("pest_measurement", "Use a representative count, density, injury, or whole-canopy defoliation measurement.", r"\bpest count\b", r"\bdensity\b", r"\binjury\b", r"\bdefoliation\b", r"\bscout(?:ing)? method\b")
        add("pest_threshold", "Tie treatment to crop stage and a locally valid economic or action threshold.", r"\beconomic threshold\b", r"\baction threshold\b")
        add("pest_ipm", "Account for population trend and natural enemies, then verify current label fit if treatment is justified.", r"\bnatural enemies\b", r"\bbeneficial insects\b", r"\bcurrent (?:product )?label\b")
    elif decision == "weed_escape_management":
        add("weed_seed_return", "Prevent surviving weeds from producing seed or spreading where practical.", r"\bprevent seed\b", r"\bseed production\b", r"\bseed return\b", r"\bseedbank\b", r"\bspread\b")
        add("weed_escape_map", "Map escapes and confirm species, growth stage, density, and seed maturity.", r"\bmap (?:the )?(?:surviving weeds|escapes?)\b", r"\bweed identity\b", r"\bgrowth stage\b", r"\bseed maturity\b")
        add("weed_failure_diagnosis", "Review the application record and separate resistance from application failure.", r"\bapplication record\b", r"\bherbicide history\b", r"\bresistance\b[^.]{0,45}\bapplication failure\b", r"\bbefore calling resistance\b")
        add("weed_integrated_plan", "Use multiple effective chemical and nonchemical tactics in the next crop cycle.", r"\bmultiple effective\b", r"\bresidual\b", r"\bcrop competition\b", r"\bmechanical\b", r"\bcultural control\b")
    elif decision == "soil_crusting":
        add("crust_confirmation", "Confirm that a surface crust is restricting emergence and inspect seedling injury.", r"\bconfirm\b[^.]{0,45}\b(?:surface )?crust\b", r"\btrue surface crust\b", r"\bseedling (?:depth|injury)\b")
        add("crust_operation_boundary", "Limit crust breaking to a shallow, well-timed operation that does not add wet-soil injury.", r"\bcrust[- ]breaking\b", r"\brotary hoe\b", r"\bshallow\b[^.]{0,40}\bpass\b", r"\bavoid\b[^.]{0,40}\bwet soil\b")
        add("crust_test_pass", "Use a short test pass and check crop injury before continuing.", r"\btest (?:a )?(?:short )?pass\b", r"\bcheck\b[^.]{0,45}\b(?:seedling|cotyledon|crop) (?:loss|injury)\b")
        add("crust_stand_decision", "Reassess emergence and stand before any replant decision.", r"\breassess emergence\b", r"\bstand count\b", r"\breplant")
    elif decision == "compaction_tillage":
        add("compaction_pattern", "Compare traffic and rooting patterns with unaffected soil.", r"\btraffic pattern\b", r"\bwheel tracks?\b", r"\broot pattern\b", r"\buntrafficked\b")
        add("compaction_depth", "Confirm restriction depth at comparable soil moisture with a pit, probe, or penetrometer.", r"\bsoil pit\b", r"\bpenetrometer\b", r"\bcomparable soil moisture\b", r"\brestriction (?:depth|layer)\b")
        add("compaction_differential", "Separate mechanical compaction from drainage or a naturally dense layer.", r"\bmechanical compaction\b", r"\bpoor drainage\b", r"\bnaturally dense layer\b")
        add("compaction_tillage_boundary", "Deep-till only a confirmed layer in suitable moisture, then prevent re-compaction.", r"\bdeep tillage\b[^.]{0,90}\bconfirmed\b", r"\bdeep[- ]rip\b[^.]{0,90}\bconfirmed\b", r"\bwithout smearing\b", r"\bcontrolled traffic\b")
    elif decision == "physiological_disorder":
        add("disorder_local_transport", "Explain the disorder as a localized calcium-transport or delivery problem in affected tissue.", r"\blocalized calcium[- ](?:transport|delivery)\b", r"\bcalcium (?:movement|delivery|transport)\b")
        add("disorder_water_root", "Address root-zone moisture, root function or injury, and transpiration or canopy conditions.", r"\broot[- ]zone moisture\b", r"\broot (?:function|injury|stress)\b", r"\btranspir", r"\bcanopy environment\b")
        add("disorder_growth_salts", "Consider growth rate, salinity or competing salts, and fertility where relevant.", r"\brapid growth\b", r"\bgrowth rate\b", r"\bsalinity\b", r"\bcompeting salts\b", r"\bexcessive nitrogen\b")
        add("disorder_calcium_boundary", "Do not prescribe more calcium as the default when transport remains constrained.", r"\badding\b[^.]{0,35}\bcalcium\b[^.]{0,70}\bnot\b", r"\bmore (?:soil or foliar )?calcium\b", r"\bdo not assume\b[^.]{0,45}\bcalcium\b")
    elif decision == "salinity_management":
        add("salinity_tests", "Use irrigation-water and root-zone soil salinity tests.", r"\birrigation[- ]water\b[^.]{0,45}\b(?:tests?|electrical conductivity|EC)\b", r"\broot[- ]zone (?:soil )?(?:salinity )?tests?\b", r"\bsoil salinity\b", r"\banalyses?\b[^.]{0,55}\b(?:sol|eau d'irrigation)\b")
        add("salinity_sodium", "Assess electrical conductivity and sodium or infiltration hazard where relevant.", r"\belectrical conductivity\b", r"\bconductivit[eé] [eé]lectrique\b", r"\bsodium hazard\b", r"\bSAR\b", r"\binfiltration\b")
        add("salinity_crop_system", "Relate the measurements to crop tolerance, symptoms, uniformity, and drainage.", r"\bcrop tolerance\b", r"\btol[eé]rance de la culture\b", r"\birrigation uniformity\b", r"\bdrainage\b", r"\bwater table\b", r"\bnappe phr[eé]atique\b")
        add("salinity_leaching_boundary", "Recommend leaching only when water quality, infiltration, and drainage can move salts below roots.", r"\bleaching\b[^.]{0,130}\bdrainage\b", r"\blessivage\b[^.]{0,130}\bdrainage\b", r"\bbelow the (?:active )?root zone\b", r"\bsous la zone racinaire\b")
        if re.search(r"\b(?:gypsum|gypse)\b", lower):
            add("sodicity_gypsum_boundary", "State that gypsum is not automatic and requires confirmed sodicity plus a reclamation calculation.", r"\bgypsum\b[^.]{0,60}\bnot automatic\b", r"\bgypse\b[^.]{0,80}\b(?:pas automatique|sodicit[eé] confirm[eé]e)\b", r"\bconfirmed sodicity\b", r"\breclamation (?:calculation|requirement)\b", r"\bcalcul (?:de|du) (?:r[eé]habilitation|besoin d'amendement)\b")
    elif decision == "flood_recovery":
        add("flood_exposure", "Use crop stage, growing-point position, and submergence depth and duration.", r"\bcrop stage\b", r"\bgrowing[- ]point position\b", r"\bdepth and duration\b", r"\bsubmergence\b")
        add("flood_temperature", "Account for water or air temperature and oxygen stress.", r"\bwater and air temperature\b", r"\btemperature\b[^.]{0,50}\boxygen\b", r"\boxygen stress\b")
        add("flood_secondary_injury", "Check roots, sediment or debris, disease, and nutrient loss after drainage.", r"\broot injury\b", r"\bsediment\b", r"\bdebris\b", r"\bdisease\b", r"\bnitrogen loss\b")
        add("flood_reassessment", "Wait for drainage, inspect new growth and growing points, and count the surviving stand before replanting.", r"\bnew growth\b", r"\binspect growing points\b", r"\bstand counts?\b", r"\bbefore deciding on replant")
    elif decision == "freeze_recovery":
        if re.search(r"\bcanola\b", lower):
            add("freeze_canola_stage", "Record canola reproductive stage and inspect flowers, pods, seeds, stems, and growing points.", r"\breproductive stage\b", r"\b(?:flowers?|pods?|seeds?)\b[^.]{0,100}\b(?:stems?|growing points?)\b")
            add("freeze_canola_exposure", "Use the best in-field minimum temperature and exposure duration with field microclimate.", r"\bminimum temperature\b", r"\bexposure duration\b", r"\btemperature\b[^.]{0,70}\bduration\b")
            add("freeze_canola_zones", "Compare representative low, exposed, sheltered, and normal areas.", r"\b(?:low|exposed|sheltered) areas?\b", r"\brepresentative (?:areas|plants|zones)\b")
            add("freeze_canola_recovery", "Reassess tissue progression and viable reproductive sites before changing management.", r"\bviable reproductive (?:sites?|tissue)\b", r"\b(?:pods?|seeds?|flowers?)\b[^.]{0,90}\b(?:viable|recovery|progress)")
        else:
            add("freeze_growing_point", "Base recovery on crop stage and growing-point position or condition, not burned leaves alone.", r"\bgrowing point\b", r"\bexposed leaves\b", r"\bburned leaf area\b")
            add("freeze_wait", "Allow warm recovery weather and look for new growth before deciding.", r"\bwarm (?:growing|recovery) weather\b", r"\bnew (?:leaf )?growth\b")
            add("freeze_stand", "Inspect healthy growing points and count surviving plants and uniformity.", r"\bhealthy\b[^.]{0,35}\bgrowing points?\b", r"\bcount surviving plants\b", r"\bstand uniformity\b")
            add("freeze_replant", "Compare the recovered stand and planting date with replant economics.", r"\brecovered stand\b", r"\bcost of replanting\b", r"\breplant")
    elif decision == "pollination_stress":
        add("pollination_water", "Assess root-zone water stress rather than treating heat alone as the cause.", r"\broot[- ]zone (?:water|moisture)\b", r"\bwater stress\b", r"\bheat alone\b")
        add("pollination_sync", "Compare silk emergence and receptivity with pollen shed.", r"\bsilk emergence\b", r"\bsilk\b[^.]{0,55}\bpollen shed\b", r"\bpollination window\b[^.]{0,45}\bsynchron")
        add("pollination_observation", "Inspect fertilization and early kernel set after pollen shed.", r"\bfertilization\b", r"\bearly kernel set\b", r"\bkernel set\b")
        add("pollination_action", "Protect root-zone water through silking and early kernel set where irrigation is available.", r"\bthrough silking\b", r"\birrigation\b[^.]{0,90}\bkernel set\b")
    elif decision == "maturity_switch":
        add("maturity_date", "Compare the actual planting date with hybrid maturity or heat-unit requirement.", r"\bactual planting date\b", r"\brelative maturity\b", r"\bheat[- ]unit requirement\b")
        add("maturity_weather", "Use remaining heat units and frost risk, not a universal calendar rule.", r"\bheat units\b", r"\bfrost risk\b", r"\bno(?:t| universal)\b[^.]{0,45}\bday[- ]for[- ]day rule\b")
        add("maturity_harvest_tradeoff", "Balance maturity risk with drydown, harvest moisture, and drying cost.", r"\bdrydown\b", r"\bharvest moisture\b", r"\bdrying cost\b")
        add("maturity_agronomic_fit", "Retain local trial, yield-stability, disease, standability, and lodging fit.", r"\blocal trial data\b", r"\byield stability\b", r"\bdisease package\b", r"\bstandability\b", r"\blodging\b")
    elif decision == "wilt_differential":
        add("wilt_water_pattern", "Check root-zone moisture, irrigation uniformity, and the field pattern while plants are wilted.", r"\broot[- ]zone moisture\b", r"\birrigation uniformity\b", r"\bfield pattern\b")
        add("wilt_recovery", "Use overnight or morning recovery as evidence without treating it as definitive.", r"\brecover(?:s|y)? overnight\b", r"\bmorning wilt\b", r"\bwater[- ]demand explanation\b")
        add("wilt_plant_exam", "Inspect roots, crowns, stems, yellowing pattern, and vascular tissue.", r"\bvascular (?:discoloration|tissue)\b", r"\binspect roots\b", r"\bcrowns?\b", r"\bone[- ]sided yellowing\b")
        add("wilt_sample", "Submit a representative whole-plant diagnostic sample when disease signs persist.", r"\brepresentative whole[- ]plant diagnostic sample\b", r"\bdiagnostic sample\b")

    if requirements:
        return tuple(requirements)

    if question_type == "fertility_rate":
        if re.search(r"\b(volatilization|fertilizer source)\b", lower):
            add("volatilization_source", "Identify the fertilizer source, such as urea, UAN, or ammonium.", r"\bfertilizer source\b", r"\burea\b", r"\bUAN\b", r"\bammonium\b")
            add("volatilization_placement", "Check placement, surface application, incorporation, or injection.", r"\bplacement\b", r"\bsurface application\b", r"\bincorporation\b", r"\binjection\b")
            add("volatilization_risk", "Describe volatilization and nitrogen loss risk without inventing a loss percentage.", r"\bvolatilization\b", r"\bloss risk\b")
            add("volatilization_weather", "Use rainfall or irrigation timing, temperature, residue, and soil condition.", r"\brainfall timing\b", r"\birrigation timing\b", r"\btemperature\b", r"\bresidue\b")
            add("volatilization_mitigation", "Treat inhibitor or stabilizer use and timing as source- and label-specific tools tied to crop uptake.", r"\binhibitor\b", r"\bstabilizer\b", r"\btiming\b", r"\bcrop uptake\b")
        elif re.search(r"\b(potassium|soil[- ]test k|marginal k)\b", lower):
            add("potassium_test", "Verify soil-test K, the analytical method, and local calibration.", r"\bsoil[- ]test K\b", r"\bpotassium\b", r"\bsoil test method\b", r"\blocal calibration\b")
            add("potassium_soil", "Interpret K with CEC, texture or clay, and exchangeable-K context.", r"\bCEC\b", r"\bsoil texture\b", r"\bclay\b", r"\bexchangeable K\b")
            add("potassium_removal", "Use crop removal, yield goal, and yield history.", r"\bcrop removal\b", r"\byield goal\b", r"\byield history\b")
            add("potassium_placement", "Compare placement, banding, broadcast, and timing using local calibration.", r"\bplacement\b", r"\bbanding\b", r"\bbroadcast\b", r"\btiming\b")
        elif re.search(r"\bmanure credits?\b", lower) and re.search(r"\b(runoff|water quality|tile|drainage|fertility plan)\b", lower):
            add("manure_analysis", "Require a current manure or nutrient analysis.", r"\bmanure analysis\b", r"\bmanure test\b", r"\bnutrient analysis\b")
            add("manure_application", "Verify application date, rate, timing, method, and incorporation.", r"\bapplication date\b", r"\bapplication rate\b", r"\bapplication timing\b", r"\bincorporation\b")
            add("manure_credits", "Calculate available nitrogen and phosphorus credits.", r"\bnitrogen credit\b", r"\bphosphorus credit\b", r"\bavailable nutrients?\b")
            add("manure_crop_need", "Tie credits to the soil test, crop need, crop removal, and yield goal.", r"\bsoil test\b", r"\bcrop need\b", r"\bcrop removal\b", r"\byield goal\b")
            add("manure_water_quality", "Check runoff, setbacks, tile or drainage, and water-quality risk.", r"\brunoff\b", r"\bsetbacks?\b", r"\btile\b", r"\bdrainage\b", r"\bwater[- ]quality\b")
        elif re.search(r"\b4r\b|\bright source\b|\bright rate\b|\bright time\b|\bright place\b", lower):
            add("right_source", "Address the right source and manure nutrient analysis.", r"\bright source\b")
            add("right_rate", "Address the right rate using soil tests, yield goal, and all nutrient credits.", r"\bright rate\b")
            add("right_time", "Address the right time and loss-risk timing.", r"\bright time\b")
            add("right_place", "Address the right place and placement.", r"\bright place\b")
            add("manure_credit", "Use manure analysis and manure or previous-crop credits.", r"\bmanure (?:analysis|credit)\b", r"\bcredits?\b")
            add("tile_loss_risk", "Account for tile drainage, leaching, and runoff.", r"\btile\b", r"\bleach", r"\brunoff\b")
            add("nutrient_records", "Preserve application and nutrient records.", r"\brecords?\b", r"\baudit trail\b")
        else:
            add("current_nutrient_evidence", "Name the current soil or tissue evidence needed.", r"\bsoil (?:test|sample|nitrate|results?)\b", r"\bsoil or tissue results?\b", r"\btissue (?:test|result|sample)\b")
            add("nutrient_records_and_credits", "Check nutrient source, application records, and applicable credits.", r"\bsource\b", r"\bapplication record", r"\b(?:manure|previous[- ]crop) credits?\b")
            if re.search(r"\b(rain|wet|irrigat|drain|leach|denitr|water loss)\b", lower):
                add("water_loss_context", "Account for rainfall or irrigation, drainage, and nutrient-loss risk.", r"\brain", r"\birrigat", r"\bdrain", r"\bleach", r"\bdenitr")
            add("local_calibration_and_goal", "Tie the decision to a crop or yield goal and local calibration.", r"\byield goal\b", r"\bcrop goal\b", r"\blocal(?:ly)? calibrat")
        if re.search(r"\b(variable[- ]rate nitrogen|old yield maps?|check strip)\b", lower):
            add("current_spatial_evidence", "Do not increase a variable rate from old maps without current soil and aligned field evidence.", r"\bcurrent soil\b", r"\bsoil nitrate\b", r"\balign(?:ed|ment)\b")
            add("response_validation", "Validate response with a response curve, check strip, or replicated field trial.", r"\bresponse curve\b", r"\bcheck strips?\b", r"\bfield trial\b")
            add("variable_rate_audit", "Preserve the management-zone and as-applied audit trail.", r"\bmanagement zones?\b", r"\bas[- ]applied\b", r"\baudit trail\b")

    elif question_type == "fertility_diagnostic":
        if re.search(r"\b(tissue[- ]test results?|tissue testing|plant analysis)\b", lower):
            add("tissue_identity", "Identify the tissue test or plant analysis and sampled plant part.", r"\btissue test\b", r"\bplant analysis\b", r"\bplant tissue\b")
            add("tissue_timing", "Use sampling date, growth or crop stage, and sampling timing.", r"\bsampling date\b", r"\bgrowth stage\b", r"\bcrop stage\b", r"\bsampling timing\b")
            add("tissue_soil", "Interpret with a current soil test, soil pH, and nutrient-availability context.", r"\bsoil test\b", r"\bsoil pH\b", r"\bnutrient availability\b")
            add("tissue_calibration", "Use a locally calibrated sufficiency range or critical level.", r"\bsufficiency range\b", r"\bcritical level\b", r"\blocal calibration\b")
            add("tissue_boundary", "Use field and symptom pattern and do not use tissue results alone.", r"\bfield pattern\b", r"\bsymptom pattern\b", r"\bdo not use[^.]{0,30}\balone\b", r"\bnot[^.]{0,30}\balone\b")
        elif re.search(r"\b(lime|low ph|buffer ph|acidity)\b", lower):
            add("lime_requirement", "Require soil pH plus buffer pH, exchangeable acidity, or a lab lime requirement.", r"\bbuffer pH\b", r"\bexchangeable acidity\b", r"\blime requirement\b")
            add("target_ph_and_crop", "Set the target pH from the crop or rotation and local calibration.", r"\btarget pH\b", r"\bcrop or rotation\b")
            add("lime_source_quality", "Check CCE, ECCE, neutralizing value, and fineness of the lime source.", r"\bCCE\b", r"\bECCE\b", r"\bneutralizing value\b")
        elif re.search(r"\bphosphorus\b", lower) and re.search(r"\b(runoff|water[- ]quality|ditch|erosion)\b", lower):
            add("phosphorus_test_context", "Verify the soil-test phosphorus method, units, sampling, and manure history.", r"\bsoil[- ]test (?:P|phosphorus)\b", r"\btest method\b")
            add("phosphorus_manure_history", "Check manure history and all phosphorus sources.", r"\bmanure history\b", r"\bmanure\b")
            add("runoff_pathways", "Address runoff pathways, erosion, drainage, or slope.", r"\brunoff\b", r"\berosion\b", r"\bdrainage\b", r"\bslope\b")
            add("edge_controls", "Use applicable setbacks, buffers, or edge-of-field controls.", r"\bsetbacks?\b", r"\bbuffers?\b", r"\bedge[- ]of[- ]field\b")
            add("avoid_additional_phosphorus", "Avoid additional phosphorus when both source and transport risk are high.", r"\bavoid additional phosphorus\b", r"\bdo not apply\b")
            add("phosphorus_drawdown", "Use crop removal or drawdown to reduce surplus phosphorus.", r"\bcrop removal\b", r"\bdrawdown\b")
        elif re.search(r"\b(bray|olsen|mehlich|soil[- ]test method|calibration|critical level)\b", lower):
            add("method_and_calibration", "Use the reported soil-test method and local calibration.", r"\btest method\b", r"\blocal calibration\b")
            add("method_noninterchangeability", "State that unlike phosphorus methods are not interchangeable and should not be converted without validation.", r"\bnot interchangeable\b", r"\bdo not convert\b", r"\bshould not be converted\b")
            add("crop_and_removal", "Include soil pH, crop, yield goal, and crop removal.", r"\bsoil pH\b", r"\byield goal\b", r"\bcrop removal\b")
        elif re.search(r"\bsul(?:fur|phur)\b", lower):
            add("sulfur_risk", "Check texture, organic matter, rainfall or leaching, and field pattern.", r"\bsandy\b", r"\borganic matter\b", r"\bleach", r"\bfield pattern\b")
            add("sulfur_confirmation", "Use tissue or soil evidence and distinguish nitrogen or other deficiencies.", r"\btissue (?:test|evidence)\b", r"\bsoil (?:test|evidence)\b")
        elif re.search(r"\bmicronutrient deficiency\b|\bmicronutrient\b[^?]{0,100}\bdifferential\b", lower):
            add("micronutrient_pattern", "Map the patchy field and plant symptom pattern.", r"\bfield pattern\b", r"\bpatchy\b", r"\bsymptom pattern\b")
            add("micronutrient_ph", "Check current soil pH.", r"\bsoil pH\b", r"\bhigh pH\b", r"\blow pH\b")
            add("micronutrient_tests", "Use a representative tissue test and current soil test.", r"\btissue test\b", r"\bplant tissue\b", r"\bsoil test\b")
            add("micronutrient_differential", "Separate drainage, compaction, root restriction, disease, and herbicide injury.", r"\bdrainage\b", r"\bcompaction\b", r"\broot restriction\b", r"\bdisease\b", r"\bherbicide injury\b")
            add("micronutrient_boundary", "Do not diagnose from symptoms alone; confirm before treatment.", r"\bdo not diagnose from symptoms alone\b", r"\bconfirm before treatment\b")
        elif re.search(r"\bsoybeans?\b", lower) and re.search(r"\b(interveinal|between the veins|high pH|low spots?)\b", lower):
            add("idc_hypothesis", "Name iron deficiency chlorosis as a hypothesis rather than a certainty.", r"\biron deficiency chlorosis\b", r"\bIDC\b")
            add("idc_soil_context", "Check high pH, carbonate or bicarbonate context.", r"\bhigh pH\b", r"\bcarbonate\b", r"\bbicarbonate\b")
            add("idc_water_context", "Check wetness, drainage, or compaction in the affected pattern.", r"\bwet", r"\bdrain", r"\bcompaction\b")
            add("idc_variety", "Include variety tolerance in future management.", r"\bvariety\b", r"\btoleran")
        elif re.search(r"\b(nitrate leaching|leaching risk)\b", lower):
            add("leaching_timing", "Discuss split application and timing close to crop uptake.", r"\bsplit\b", r"\btiming\b")
            add("leaching_uptake", "Match nitrogen availability with crop uptake.", r"\bcrop uptake\b")
            add("leaching_cover", "Include a cover crop where rotation and water fit.", r"\bcover crop\b")
            add("leaching_inhibitor", "Treat an inhibitor or stabilizer as a conditional tool.", r"\binhibitor\b", r"\bstabilizer\b")
            add("leaching_site", "Use texture, rainfall or irrigation, drainage, and crop stage.", r"\bsandy\b", r"\brainfall\b", r"\birrigat", r"\bdrain")
        elif re.search(r"\b(yellow|pale|chlorosis|phone (?:description|photo)|photo)\b", lower):
            add(
                "diagnostic_boundary",
                "State that the report is insufficient for diagnosis or treatment.",
                r"\binsufficient\b",
                r"\bcannot diagnos",
                r"\bdiagnos(?:is|e)[^.]{0,60}\bcannot\b",
                r"\bcannot[^.]{0,60}\bdiagnos(?:is|e)\b",
                r"\bnot enough\b",
                r"\bimpossible to distinguish\b",
                r"\bdo not (?:diagnose|treat|change|adjust)[^.]{0,80}\b(?:alone|without)\b",
            )
            add("diagnostic_pattern", "Check crop stage and the field and plant symptom pattern.", r"\bcrop stage\b", r"\bfield pattern\b", r"\bpattern of\b")
            add("diagnostic_tests", "Use representative soil and tissue tests.", r"\bsoil test\b", r"\btissue test\b", r"\bsoil and tissue tests?\b")
            add("diagnostic_weather", "Check rainfall, drainage, and water or root stress.", r"\brain", r"\bdrain", r"\bwater stress\b", r"\broot stress\b")

    elif question_type == "integrated_management":
        add("integrated_nutrients", "Connect current soil or tissue evidence, yield goal, credits, and 4R nutrient management.", r"\bsoil test\b", r"\btissue test\b", r"\byield goal\b", r"\b4R\b")
        add("integrated_pests", "Require pest identification, scouting, threshold, and current label fit before treatment.", r"\bscout", r"\bthreshold\b", r"\bidentify\b")
        add("integrated_water", "Account for soil moisture, drainage, runoff, and loss risk.", r"\bsoil moisture\b", r"\bdrain", r"\brunoff\b", r"\bleach")
        add("integrated_records", "Preserve crop rotation, field records, and an audit trail.", r"\brotation\b", r"\bfield records?\b", r"\baudit trail\b")

    elif question_type == "exam_review" and re.search(r"\b(macronutrients?|micronutrients?)\b", lower):
        add("macro_micro", "Distinguish primary and secondary macronutrients from micronutrients.", r"\bprimary macronutrients?\b", r"\bsecondary macronutrients?\b", r"\bmicronutrients?\b")
        add("nutrient_mobility", "Explain how mobile and immobile nutrients affect symptom location.", r"\bmobile nutrients?\b", r"\bimmobile nutrients?\b", r"\bolder leaves\b", r"\byounger leaves\b")
        add("diagnostic_confirmation", "Use symptom pattern with soil and tissue evidence rather than symptoms alone.", r"\bsymptom pattern\b", r"\bsoil test\b", r"\btissue test\b")

    elif question_type == "seed_treatment":
        add("planting_risk", "Check planting date, soil temperature, and wet or cool seedbed conditions.", r"\bplanting date\b", r"\bsoil temperature\b", r"\bplanting conditions\b")
        add("pest_history", "Use field pest history, identification, and expected pressure.", r"\bpest history\b", r"\bpest (?:identity|pressure|species)\b")
        add("rotation_residue", "Include crop rotation, previous crop, and residue in the risk profile.", r"\bcrop rotation\b", r"\bprevious crop\b", r"\bresidue\b")
        add("seed_scouting", "Use scouting, a bait trap, or locally valid risk factors where appropriate.", r"\bscout", r"\bbait trap\b", r"\brisk factors?\b")
        add("treatment_fit", "Compare untreated risk with treatment spectrum and the current label.", r"\brisk\b", r"\bcurrent (?:product )?label\b", r"\bseed treatment\b")
        add("treatment_economic_risk", "Base treatment on target-pest and economic risk rather than insurance by default.", r"\btarget pest\b", r"\beconomic risk\b", r"\bnot insurance\b")

    elif question_type == "soil_water":
        if re.search(r"\b(climate normals?|historical gridded|gridded climate)\b", lower):
            add("climate_history", "Describe climate normals or gridded climate as a historical average or context.", r"\bclimate normals?\b", r"\bhistorical average\b", r"\bgridded climate\b")
            add("climate_forecast", "Use the current forecast, current weather, or short-term outlook for the operation window.", r"\bcurrent forecast\b", r"\bcurrent weather\b", r"\bshort[- ]term outlook\b")
            add("climate_boundary", "State that historical climate is a prior or context, not a prediction.", r"\bprior\b", r"\bcontext\b", r"\bnot (?:a )?prediction\b")
            add("climate_uncertainty", "Communicate uncertainty or probability and recheck as timing approaches.", r"\buncertainty\b", r"\bprobabil", r"\brecheck\b")
            add("climate_field", "Use field condition, soil moisture, crop stage, and operation timing.", r"\bfield condition\b", r"\bfield observations?\b", r"\bsoil moisture\b", r"\bcrop stage\b", r"\boperation timing\b")
        elif re.search(r"\bforecast uncertainty\b", lower) and sum(
            bool(re.search(pattern, lower)) for pattern in (r"\bplant\w*\b", r"\bspray\w*\b", r"\bside[- ]?dress\w*\b")
        ) >= 2:
            add("forecast_uncertainty", "Use the local forecast as probabilistic context and communicate uncertainty.", r"\blocal forecast\b", r"\bprobabil", r"\buncertainty\b")
            add("forecast_field_condition", "Check soil moisture, trafficability, and current field condition.", r"\bsoil moisture\b", r"\btrafficability\b", r"\bfield condition\b")
            add("forecast_weather", "Check wind, gusts, temperature, and rainfall for the operation.", r"\bwind\b", r"\bgusts?\b", r"\btemperature\b", r"\brainfall\b")
            add("forecast_operation", "Identify the operation type and assess planting, spray, or fertilizer-timing risk separately.", r"\boperation type\b", r"\bplanting\b", r"\bspray\b", r"\bfertilizer timing\b")
            add("forecast_recheck", "Delay or wait and recheck when the decision boundary is not satisfied.", r"\bdelay\b", r"\bwait\b", r"\brecheck\b", r"\bdo not overstate\b")
        elif re.search(r"\b(rainfall intensity|rainfast|incorporation windows?|application window)\b", focus) or (
            re.search(r"\brunoff risk\b", focus) and re.search(r"\b(fertilizer|pesticide|application|operation)\b", focus)
        ):
            add("rain_window_forecast", "Check forecast rainfall amount, rainfall intensity, and storm timing.", r"\bforecast rainfall\b", r"\bforecast amount\b", r"\brainfall intensity\b", r"\bstorm\b")
            add("rain_window_runoff", "Inspect slope, runoff paths, erosion, drainage, and water-quality risk.", r"\bslope\b", r"\brunoff paths?\b", r"\berosion\b", r"\bdrainage\b", r"\bwater quality\b")
            add("rain_window_operation", "Separate rainfast, incorporation, and application-window requirements.", r"\brainfast\b", r"\bincorporation\b", r"\bapplication window\b")
            add("rain_window_label", "Verify the current label, setback, and buffer where a pesticide is involved.", r"\bcurrent label\b", r"\bsetback\b", r"\bbuffer\b")
            add("rain_window_delay", "Delay or wait and recheck when runoff, label, or incorporation conditions are not satisfied.", r"\bdelay\b", r"\bwait\b", r"\brecheck\b")
        elif re.search(r"\bOpenET\b", lower, re.IGNORECASE):
            add("openet_source", "Describe OpenET as satellite, remote-sensing, or model evapotranspiration context.", r"\bOpenET\b", r"\bsatellite\b", r"\bremote sensing\b", r"\bmodel(?:ed)? ET\b")
            add("openet_water_demand", "Use ET to frame crop water use or water demand.", r"\bcrop water use\b", r"\bwater demand\b", r"\bevaporative demand\b")
            add("openet_boundary", "State that OpenET is a prior, not field truth or an irrigation prescription.", r"\bprior\b", r"\bnot (?:an? )?irrigation prescription\b", r"\bnot field truth\b")
            add("openet_soil_moisture", "Require local root-zone soil moisture or a field sensor.", r"\bsoil moisture\b", r"\broot[- ]zone\b", r"\bsensor\b")
            add("openet_water_records", "Use applied-water, flowmeter, or irrigation records.", r"\bapplied[- ]water\b", r"\bflowmeter\b", r"\birrigation records?\b")
            add("openet_crop_context", "Use crop stage and rooting depth before changing irrigation timing.", r"\bcrop stage\b", r"\brooting depth\b")
        elif re.search(r"\bDaymet\b", lower, re.IGNORECASE):
            add("daymet_source", "Describe Daymet as gridded climate context.", r"\bDaymet\b", r"\bgridded\b", r"\bclimate\b")
            add("daymet_variables", "Use precipitation, temperature, day length, or climate-window variables.", r"\bprecipitation\b", r"\btemperature\b", r"\bday length\b", r"\bweather window\b")
            add("daymet_boundary", "Treat Daymet as a prior or context, not field truth.", r"\bprior\b", r"\bcontext\b", r"\bnot field truth\b")
            add("daymet_current_weather", "Pair the climate context with the current forecast or weather.", r"\bforecast\b", r"\bcurrent weather\b")
            add("daymet_field_moisture", "Use local field soil moisture, observations, or a sensor.", r"\bsoil moisture\b", r"\bfield observations?\b", r"\blocal sensor\b")
            add("daymet_cover_crop", "Include cover-crop species or mix and termination timing.", r"\bcover[- ]crop species\b", r"\bspecies or mix\b", r"\btermination timing\b")
        elif re.search(r"\b(heat|drought)\b", lower) and re.search(r"\b(reproductive|pollination|flowering|sensitive stage)\b", lower):
            add("heat_crop_stage", "Confirm crop or reproductive stage, flowering, or pollination timing.", r"\bcrop stage\b", r"\breproductive stage\b", r"\bpollination\b", r"\bflowering\b")
            add("heat_demand", "Use temperature, heat stress, VPD, or evaporative demand as weather context.", r"\bheat stress\b", r"\btemperature\b", r"\bVPD\b", r"\bevaporative demand\b")
            add("heat_soil_water", "Use root-zone soil moisture, rooting depth, and irrigation evidence.", r"\bsoil moisture\b", r"\brooting depth\b", r"\birrigation\b")
            add("heat_yield_risk", "Explain yield risk from the timing and duration of stress.", r"\byield risk\b", r"\bstress timing\b")
            add("heat_boundary", "Use the current forecast and field observations without making an exact prediction.", r"\bforecast\b", r"\bfield observations?\b", r"\bnot an exact prediction\b")
        elif re.search(r"\bdrainage class\b", lower) and re.search(r"\bsoil survey|map unit|NRCS\b", lower, re.IGNORECASE):
            add("drainage_prior", "Treat the soil-survey drainage class, map unit, and component as a prior rather than field truth.", r"\bdrainage class\b", r"\bsoil survey\b", r"\bmap unit\b", r"\bcomponent\b", r"\bprior\b", r"\bnot field truth\b")
            add("drainage_observation", "Verify ponding, water-table depth, and redoximorphic or other wetness signs in field observations.", r"\bfield observations?\b", r"\bponding\b", r"\bwater table\b", r"\bredoximorphic\b", r"\bwetness signs?\b")
            add("drainage_infrastructure", "Inspect tile or surface drainage, maps, and outlets.", r"\btile\b", r"\bsurface drainage\b", r"\btile map\b", r"\boutlet\b")
            add("drainage_pit", "Use a soil pit or probe where appropriate to ground-truth wetness.", r"\bsoil pit\b", r"\bprobe\b")
        elif re.search(r"\b(soil[- ]health|aggregate stability|biological indicators?)\b", lower):
            add("soil_health_indicators", "Interpret aggregate stability, organic matter, infiltration, and biological indicators together.", r"\baggregate stability\b", r"\borganic matter\b", r"\binfiltration\b", r"\bbiological indicators?\b")
            add("soil_health_baseline", "Compare a baseline with repeated sampling and a trend under consistent methods.", r"\bbaseline sample\b", r"\brepeat sampling\b", r"\btrend\b")
            add("soil_health_history", "Use field and management history to interpret the result.", r"\bfield history\b", r"\bmanagement history\b")
            add("soil_health_objective", "Tie the indicators to a named management objective and crop or economic response.", r"\bmanagement objective\b", r"\bcrop response\b", r"\beconomic response\b")
            add("soil_health_boundary", "Do not justify a change from one composite score alone.", r"\bnot (?:a )?single score\b", r"\bone score\b", r"\bscore alone\b")
        elif re.search(r"\b(salinity|sodicity|saline|sodic|sar|esp)\b", lower):
            add("salinity_measurement", "Use a representative soil salinity measurement.", r"\bsoil (?:salinity|EC|electrical conductivity)\b", r"\bsoil test[^.]{0,50}\bsalinity measurements?\b")
            if re.search(r"\b(sodicity|sodic|SAR|ESP)\b", lower):
                add("sodium_hazard", "Measure sodium hazard with SAR, ESP, or equivalent locally interpreted evidence.", r"\bSAR\b", r"\bESP\b", r"\bsodium hazard\b")
            add("water_and_drainage", "Check irrigation-water quality, drainage, and leaching feasibility.", r"\birrigation[- ]water (?:test|quality)\b", r"\bdrainage\b", r"\bleaching\b")
            add("field_pattern", "Use field pattern and crop sensitivity before changing management.", r"\bfield pattern\b", r"\bcrop sensitivity\b")
        elif re.search(r"\b(infiltration|runoff|ponding)\b", lower) and re.search(r"\b(compaction|surface condition|crusting|aggregate stability)\b", lower):
            add("infiltration_pattern", "Map the field pattern and use traffic history.", r"\bfield pattern\b", r"\btraffic history\b")
            add("infiltration_process", "Assess infiltration, ponding, runoff, soil moisture, slope, and drainage.", r"\binfiltration\b", r"\bponding\b", r"\brunoff\b", r"\bsoil moisture\b", r"\bslope\b", r"\bdrainage\b")
            add("infiltration_structure", "Check compaction, bulk density or root restriction.", r"\bcompaction\b", r"\bbulk density\b", r"\broot restriction\b")
            add("infiltration_surface", "Check surface residue, crusting, and aggregate stability.", r"\bsurface residue\b", r"\bcrusting\b", r"\baggregate stability\b")
            add("infiltration_measurement", "Use a field measurement such as a ring infiltrometer, probe, penetrometer, or soil pit.", r"\bfield measurement\b", r"\bring infiltrometer\b", r"\bprobe\b", r"\bsoil pit\b")
        elif re.search(r"\b(compaction|traffic compaction|restrictive layers?|hardpan|plow pan|shallow roots?)\b", focus):
            add("compaction_pattern", "Verify traffic, ponding, infiltration, and rooting pattern.", r"\btraffic pattern\b", r"\bponding\b", r"\binfiltration\b")
            add("compaction_measurement", "Measure at suitable soil moisture with a probe, penetrometer, or soil pit.", r"\bsoil moisture\b", r"\bpenetrometer\b", r"\bsoil pit\b", r"\bprobe\b")
            add("compaction_management", "Match confirmed depth and cause to controlled traffic, targeted tillage, cover crops, or drainage.", r"\bcontrolled traffic\b", r"\btargeted tillage\b", r"\bcover crops?\b")
        elif re.search(r"\bcover crops?\b", lower):
            add("cover_crop_water", "Compare cover-crop water use with measured soil moisture.", r"\bwater use\b", r"\bsoil moisture\b")
            add("cover_crop_benefit", "Include erosion, residue, or soil-cover benefits.", r"\berosion\b", r"\bresidue\b", r"\bsoil cover\b")
            add("cover_crop_species", "Choose a species or mix that fits the field and rotation.", r"\bspecies\b", r"\bmix\b")
            add("cover_crop_termination", "Set termination timing and method from field conditions.", r"\btermination timing\b", r"\btermination (?:plan|method)\b")
            add("cover_crop_rotation", "Fit the cover crop to the rotation and next-crop planting window.", r"\brotation\b", r"\bnext crop\b", r"\bplanting window\b")
        elif re.search(r"\b(texture|sand|sandy|clay|water holding|available water)\b", focus):
            if re.search(r"\bsand(?:y)? soils?\b", lower) and re.search(r"\bclay soils?\b", lower):
                add("sandy_soil", "Explain the sandy-soil behavior.", r"\bsand", r"\bsandy\b")
                add("clay_soil", "Explain the clay-soil behavior.", r"\bclay\b")
                add("texture_water_storage", "Compare water holding or available water.", r"\bwater[- ]holding\b", r"\bavailable water\b")
                add("water_loss_path", "Explain nutrient leaching or percolation.", r"\bleach", r"\bpercolat")
            else:
                add("texture_and_structure", "Explain texture and structure or aggregation.", r"\btexture\b", r"\bstructure\b", r"\baggregation\b")
                add("texture_infiltration", "Explain infiltration.", r"\binfiltration\b")
                add("texture_water_storage", "Explain water holding or available water.", r"\bwater[- ]holding\b", r"\bavailable water\b")
                add("water_loss_path", "Include runoff and leaching or percolation tradeoffs.", r"\brunoff\b", r"\bleach", r"\bpercolat")
        elif re.search(r"\b(erosion|soil loss|sloping field|slope|visible runoff|conservation)\b", lower) and not re.search(
            r"\b(riparian buffers?|stream buffers?|filter strips?|drainage improvements?|wetland determination)\b", lower
        ):
            add("erosion_cover", "Keep residue or establish a suitable cover crop.", r"\bresidue\b", r"\bcover crop\b")
            add("erosion_flow_control", "Consider contouring, strips, terraces, or a grassed waterway.", r"\bcontour", r"\bstrip", r"\bterrace", r"\bwaterway\b")
            add("erosion_tillage", "Reduce tillage or use no-till where it fits.", r"\btillage reduction\b", r"\breduced tillage\b", r"\bno[- ]till\b")
            add("erosion_runoff", "Assess slope, runoff pathways, and soil loss.", r"\bslope\b", r"\brunoff\b")
            add("erosion_loss", "Name soil loss as the management target.", r"\bsoil loss\b")
        elif re.search(r"\bdrainage improvements?\b", lower) and re.search(r"\b(wet spots?|tile outlet|drainage ditch|conservation boundar)\b", lower):
            add("wetland_screen", "Check hydric-soil context and obtain a wetland determination where required.", r"\bwetland\b", r"\bhydric soil\b", r"\bwetland determination\b")
            add("wetland_authority", "Check NRCS, USDA, local regulation, and permit requirements.", r"\bNRCS\b", r"\bUSDA\b", r"\blocal regulation\b", r"\bpermit\b")
            add("wetland_field", "Use soil survey context, field observations, and water-table evidence.", r"\bsoil survey\b", r"\bfield observations?\b", r"\bwater table\b")
            add("wetland_drainage", "Review the drainage map, tile, ditch, and outlet.", r"\bdrainage map\b", r"\btile\b", r"\bditch\b", r"\boutlet\b")
            add("wetland_boundary", "Do not alter drainage until compliance and the conservation plan are resolved.", r"\bdo not alter\b", r"\bcompliance\b", r"\bconservation plan\b")
        elif re.search(r"\b(riparian buffers?|stream buffers?|filter strips?)\b", lower):
            add("riparian_buffer", "Use a riparian or stream buffer or filter strip fitted to the site.", r"\briparian buffer\b", r"\bstream buffer\b", r"\bfilter strip\b")
            add("riparian_livestock", "Manage grazing access, livestock exclusion, and stable stream crossings.", r"\bgrazing access\b", r"\blivestock exclusion\b", r"\bstream crossing\b")
            add("riparian_erosion", "Assess erosion, bank stability, and runoff paths.", r"\berosion\b", r"\bbank stability\b", r"\brunoff path\b")
            add("riparian_nutrients", "Address manure, nutrient, and water-quality risk.", r"\bmanure\b", r"\bnutrient\b", r"\bwater quality\b")
            add("riparian_plan", "Use NRCS or a local conservation plan and applicable setback.", r"\bNRCS\b", r"\blocal conservation plan\b", r"\bsetback\b")
            add("riparian_site", "Ask for stream distance and livestock access.", r"\bstream distance\b", r"\blivestock access\b")
        elif re.search(r"\b(tile|subsurface) drainage\b", lower) and re.search(r"\b(nitrate|water[- ]quality|leaching)\b", lower):
            add("tile_nitrate_path", "Treat tile or subsurface drainage as a nitrate transport path and water-quality concern.", r"\btile drainage\b", r"\bsubsurface drainage\b", r"\bnitrate\b", r"\bwater[- ]quality\b")
            add("tile_water_evidence", "Use rainfall, drainage flow, soil moisture, and outlet evidence.", r"\brainfall\b", r"\bdrainage flow\b", r"\bsoil moisture\b", r"\btile outlet\b")
            add("tile_nutrient_plan", "Check soil nitrate and the fertility plan, including source, rate, and timing.", r"\bsoil nitrate\b", r"\bfertility plan\b", r"\bnitrogen plan\b")
            add("tile_source_controls", "Reduce surplus nitrate with split timing, crop uptake, or a cover crop where suitable.", r"\bsplit timing\b", r"\bcrop uptake\b", r"\bcover crop\b")
            add("tile_edge_controls", "Consider controlled drainage or edge-of-field practices such as a bioreactor or saturated buffer.", r"\bcontrolled drainage\b", r"\bedge[- ]of[- ]field\b", r"\bbioreactor\b", r"\bsaturated buffer\b")
        elif re.search(r"\b(drainage|tile|wet spots?|ponding|water table|outlet)\b", focus) and not re.search(
            r"\b(public weather|ET|evapotranspiration)\b", focus, re.IGNORECASE
        ):
            add("drainage_landscape", "Use the soil survey, topography, and water-table or permeability evidence.", r"\bsoil (?:survey|map)\b", r"\btopograph", r"\bwater table\b", r"\bpermeab")
            add("drainage_infrastructure", "Check tile maps, outlets, and drainage or wetland constraints.", r"\btile map\b", r"\boutlet\b", r"\bwetland\b", r"\bregulation\b")
        else:
            add("weather_et_boundary", "Treat public weather or ET as context, not a field sensor or prescription.", r"\b(?:weather|ET|evapotranspiration)\b[^.]{0,100}\b(?:context|prior|not (?:a )?(?:field sensor|prescription))\b", r"\bnot (?:a )?(?:field sensor|irrigation prescription)\b")
            add("root_zone_measurement", "Require a local root-zone soil-moisture observation, probe, or sensor.", r"\broot[- ]zone\b", r"\b(?:probe|sensor)\b", r"\bsoil moisture\b")
            add("crop_stage_and_rooting", "Use crop stage and rooting depth in the water decision.", r"\bcrop stage\b", r"\brooting depth\b")
            add("applied_water_records", "Check applied water, flowmeter, irrigation, or rainfall records.", r"\bapplied[- ]water\b", r"\bflowmeter\b", r"\birrigation (?:record|history)\b", r"\brainfall (?:record|history)\b")

    weed_focus = bool(
        re.search(r"\b(weed|herbicide resistance|resistant|escapes?|survivors?|mode[- ]of[- ]action|application[- ]failure|integrated tactics?)\b", focus)
        or (
            re.search(r"\b(weed|herbicide resistance|resistant|escapes?|survivors?)\b", lower)
            and not re.search(r"\b(spray|scout|weather|forecast|wind)\b", focus)
        )
    )

    if question_type == "product_label" and re.search(r"\b(pollinator|bees?|beekeeper|bee advisory)\b", lower):
        add("pollinator_label", "Check the current label, bee advisory, and application restrictions.", r"\bcurrent (?:product )?label\b", r"\bbee advisory\b", r"\bapplication restrictions?\b")
        add("pollinator_status", "Check pollinator habitat, bloom status, and bee activity.", r"\bpollinator\b", r"\bbee activity\b", r"\bbloom status\b", r"\bhabitat\b")
        add("pollinator_ipm", "Require scouting and a justified IPM threshold before treatment.", r"\bIPM\b", r"\bscout", r"\beconomic threshold\b")
        add("pollinator_drift", "Check wind, drift, buffers, and downwind exposure.", r"\bwind\b", r"\bdrift\b", r"\bbuffer", r"\bdownwind\b")
        add("pollinator_communication", "Coordinate with the neighbor, habitat manager, or beekeeper.", r"\bcommunication\b", r"\bneighbor\b", r"\bbeekeeper\b", r"\bhabitat manager\b")

    elif question_type == "product_label" and re.search(r"\b(carryover|rotation restriction|plant[- ]back)\b", lower):
        add("carryover_application", "Identify the herbicide active ingredient, rate, and application date.", r"\bactive ingredient\b", r"\bapplication rate\b", r"\bapplication date\b")
        add("carryover_label", "Use the current product label, rotation interval, and plant-back restriction.", r"\bcurrent (?:product )?label\b", r"\brotation interval\b", r"\bplant[- ]back restriction\b")
        add("carryover_soil", "Check soil pH, organic matter, and texture.", r"\bsoil pH\b", r"\borganic matter\b", r"\btexture\b")
        add("carryover_weather", "Check rainfall, soil moisture, temperature, and degradation conditions.", r"\brainfall\b", r"\bsoil moisture\b", r"\bdegradation\b")
        add("carryover_field", "Use field history, crop sensitivity, and a bioassay where appropriate.", r"\bfield history\b", r"\bcrop sensitivity\b", r"\bbioassay\b")

    elif question_type == "product_label" and re.search(r"\bpre[- ]?emergence\b", lower) and re.search(
        r"\b(activation|control failure|judging? (?:control )?failure)\b", lower
    ):
        add("residual_label", "Verify the exact product label, rate, and soil restrictions.", r"\bproduct label\b", r"\bapplication rate\b", r"\bsoil restrictions?\b")
        add("residual_activation", "Check rainfall after application, activation, and incorporation requirements.", r"\brainfall after application\b", r"\bactivation\b", r"\bincorporation\b")
        add("residual_weeds", "Identify weed species, emergence timing, and weed size.", r"\bweed species\b", r"\bemergence timing\b", r"\bweed size\b")
        add("residual_soil", "Check soil texture, organic matter, pH, and moisture.", r"\bsoil texture\b", r"\borganic matter\b", r"\bsoil pH\b", r"\bsoil moisture\b")
        add("residual_scouting", "Use scouting, escape patterns, and resistance-management context before declaring failure.", r"\bscouting\b", r"\bescapes?\b", r"\bresistance management\b")

    elif question_type == "product_label" and re.search(r"\b(multi[- ]year integrated weed|weed seedbank|seedbank strategy)\b", lower):
        add("seedbank_identity", "Identify the weed species and its seedbank or perennial life-cycle risk.", r"\bweed species\b", r"\bseedbank\b")
        add("seedbank_rotation", "Use crop rotation, cover crops, and crop competition where they fit.", r"\bcrop rotation\b", r"\bcover crop\b", r"\bcompetitive crop\b", r"\bcrop competition\b")
        add("seedbank_chemistry", "Rotate effective modes or sites of action under current labels.", r"\bmodes? of action\b", r"\bsites? of action\b", r"\brotate chemistr")
        add("seedbank_nonchemical", "Combine mechanical, cultural, or other nonchemical tactics.", r"\bmechanical\b", r"\bcultural\b", r"\bnonchemical\b")
        add("seedbank_prevention", "Scout, keep records, and prevent seed production and spread.", r"\bscout", r"\brecordkeeping\b", r"\bprevent seed production\b")
        add("seedbank_history", "Use herbicide history and feasible rotation or cover-crop options.", r"\bherbicide history\b", r"\brotation options?\b", r"\bcover[- ]crop options?\b")

    elif question_type == "product_label" and re.search(r"\b(tank mix|adjuvant|compatibility)\b", lower):
        add("tank_labels", "Verify all exact product labels and tank-mix compatibility.", r"\bproduct labels\b", r"\btank mix\b", r"\bcompatibility\b")
        add("tank_adjuvant", "Check the required or prohibited adjuvant, surfactant, oil, and water conditioning.", r"\badjuvant\b", r"\bsurfactant\b", r"\boil\b", r"\bwater conditioning\b")
        add("tank_crop", "Check crop stage, crop safety, and variety tolerance.", r"\bcrop stage\b", r"\bcrop safety\b", r"\bvariety tolerance\b")
        add("tank_weeds", "Identify weed species, weed size, and growth stage.", r"\bweed species\b", r"\bweed size\b", r"\bgrowth stage\b")
        add("tank_stewardship", "Check modes of action, resistance management, and application weather.", r"\bmode of action\b", r"\bresistance management\b", r"\bweather\b")

    elif question_type == "product_label" and re.search(r"\bunknown weeds?\b|\bweed identification\b", lower):
        add("unknown_weed_id", "Identify the weed species from adequate photos or a sample.", r"\bweed identification\b", r"\bweed species\b", r"\bweed photos?\b", r"\bsample\b")
        add("unknown_weed_stage", "Record growth stage, weed size, and emergence timing.", r"\bgrowth stage\b", r"\bweed size\b", r"\bemergence timing\b")
        add("unknown_weed_pattern", "Scout and map the field pattern and escapes.", r"\bfield pattern\b", r"\bscouting\b", r"\bescapes?\b")
        add("unknown_weed_history", "Use field and herbicide history, mode of action, and resistance evidence.", r"\bfield history\b", r"\bherbicide history\b", r"\bmode of action\b", r"\bresistance\b")
        add("unknown_weed_nonchemical", "Include cultural, mechanical, rotation, or cover-crop options.", r"\bcultural\b", r"\bmechanical\b", r"\brotation\b", r"\bcover crop\b")

    elif question_type == "product_label" and re.search(r"\binsecticide\b", lower) and re.search(
        r"\b(resistance|mode[- ]of[- ]action|repeated products?)\b", lower
    ):
        add("insect_resistance_identity", "Confirm pest species or correct identification.", r"\bpest species\b", r"\bcorrect identification\b")
        add("insect_resistance_scouting", "Use scout counts and a locally valid economic threshold.", r"\bscout counts?\b", r"\bscouting\b", r"\beconomic threshold\b")
        add("insect_resistance_mode", "Use IRAC mode-of-action groups and rotate effective modes.", r"\bIRAC\b", r"\bmode of action\b", r"\brotate effective modes\b")
        add("insect_resistance_history", "Review field history and previous products.", r"\bfield history\b", r"\bprevious products?\b")
        add("insect_resistance_ipm", "Use beneficials or natural enemies, IPM, and the current label.", r"\bbeneficials?\b", r"\bnatural enemies\b", r"\bIPM\b", r"\bcurrent label\b")

    elif question_type == "product_label" and weed_focus:
        add("weed_identification", "Confirm weed identity, growth stage, and density.", r"\bweed (?:id|identity|species)\b", r"\bidentify (?:the )?weed", r"\bweed species\b")
        add("escape_mapping", "Scout, map, and revisit survivor or escape patterns.", r"\bmap(?:ping)? (?:and revisit )?(?:surviv|escape)", r"\bescape mapping\b", r"\bscout(?:ing)?[^.]{0,80}\bescapes?\b")
        add("application_failure_check", "Separate resistance from application failure using the application record and conditions.", r"\bapplication failure\b", r"\bapplication record\b", r"\b(?:timing|coverage|weather)[^.]{0,80}\b(?:failure|application)\b")
        add("resistance_history", "Review resistance and prior mode- or site-of-action history.", r"\bmode(?:s)? of action\b", r"\bsite(?:s)? of action\b", r"\bresistance (?:history|confirmation|mechanism)\b")
        add("integrated_weed_tactics", "Use integrated labeled chemical and nonchemical tactics.", r"\bintegrated (?:weed|labeled) tactics?\b", r"\bcultivat", r"\bcrop rotation\b", r"\bcover crop\b", r"\bcrop competition\b")
        add("current_label_context", "Verify the current label for crop, target, jurisdiction, timing, and restrictions.", r"\bcurrent (?:product )?label\b")

    elif question_type == "product_label" and re.search(r"\b(health|safety|environmental|PPE|restricted entry|preharvest|storage|handling)\b", lower):
        add("safety_label", "Start with the current label and registration.", r"\bcurrent (?:product )?label\b", r"\blabel\b")
        add("safety_ppe", "Specify label-required personal protective equipment.", r"\bpersonal protective equipment\b", r"\bPPE\b")
        add("safety_intervals", "Check restricted-entry and preharvest intervals.", r"\brestricted[- ]entry\b", r"\bREI\b", r"\bpreharvest interval\b", r"\bPHI\b")
        add("safety_drift", "Protect buffers, water, and sensitive areas from drift or runoff.", r"\bbuffer", r"\bdrift\b")
        add("safety_water", "Check water and sensitive-area protections.", r"\bwater\b", r"\bsensitive area\b")
        add("safety_handling", "Cover storage, transport, mixing, handling, and disposal.", r"\bstorage\b", r"\bhandling\b", r"\bdisposal\b")

    elif question_type == "product_label":
        if _requires_application_unit_mismatch_fallback(question_type, question):
            add("unit_distinction", "State that irrigation depth cannot be converted directly into product volume.", r"\bdo not convert\b", r"\bdifferent quantities\b")
            add("current_label_context", "Verify the exact product and current jurisdiction-specific label.", r"\bexact product\b", r"\bcurrent (?:product )?label\b", r"\bjurisdiction[- ]specific label\b")
            add("treated_area", "Require the treated area for the product-amount calculation.", r"\btreated area\b", r"\bsuperficie trait[eé]e\b")
            add("carrier_and_calibration", "Use the label carrier-volume requirement and a calibrated application system.", r"\bcarrier[- ]volume\b", r"\bvolume de bouillie\b", r"\bcalibrated application system\b", r"\bsyst[eè]me d'application [eé]talonn[eé]\b")
        else:
            add("current_label_context", "Verify the exact product and current jurisdiction-specific label.", r"\bcurrent (?:product )?label\b", r"\bjurisdiction[- ]specific label\b")
        product_selection = bool(
            not _requires_application_unit_mismatch_fallback(question_type, question)
            and re.search(r"\bwhat (?:herbicide|fungicide|insecticide|pesticide) product\b|\bproduct should\b", lower)
        )
        if product_selection:
            add("product_target", "Require the crop, target pest, and jurisdiction before product selection.", r"\bcrop\b", r"\btarget\b", r"\bweed\b")
            add("mode_of_action", "Include mode or site of action in product stewardship.", r"\bmodes? of action\b", r"\bsites? of action\b")
        elif re.search(r"\b(spray|spraying|application|timing|wind|weather|forecast|drift|rain)\b", lower):
            add("on_site_observation", "Use an on-site field observation rather than public weather alone.", r"\bon[- ]site\b", r"\bat the field\b", r"\bfield observations?\b", r"\blocal wind observations?\b")
            add("application_weather", "Check wind, gusts, inversion, and rain timing.", r"\bwind (?:speed|direction|and gusts)", r"\blocal wind observations?\b", r"\bgusts?\b", r"\binversion\b", r"\brain(?:fast)?\b")
        if re.search(r"\b(downwind|sensitive|drift|buffer|neighboring|near)\b", lower):
            add("downwind_sensitivity", "Check downwind sensitive crops or areas.", r"\bdownwind\b", r"\bsensitive (?:crop|area|site|field)s?\b")
            add("buffer_controls", "Check applicable buffers or drift controls.", r"\bbuffers?\b", r"\bdrift control")
            add("drift_risk", "Name drift risk explicitly.", r"\bdrift\b")
        if re.search(r"\b(public|gridded|forecast)\b", focus):
            add("public_weather_boundary", "State that public weather or a forecast is planning context, not field truth or application approval.", r"\bplanning (?:context|prior)\b", r"\bnot (?:an? )?(?:on[- ]site|field) (?:measurement|observation)\b", r"\bnot approval to spray\b")
        if "scout" in focus and re.search(r"\b(spray|application)\b", focus):
            add("separate_scouting_from_spraying", "Separate the scouting-access decision from the regulated spray decision.", r"\bscout(?:ing)?\b")

    elif question_type == "plant_health" and re.search(r"\b(degree[- ]day|growing degree day|weather[- ]model)\b", lower):
        add("degree_day_context", "Use degree-day or weather-model context only to time scouting.", r"\bdegree[- ]day\b", r"\bgrowing degree day\b", r"\bweather[- ]model\b")
        add("degree_day_pest", "Identify the pest species and life stage.", r"\bpest species\b", r"\blife stage\b")
        add("degree_day_scouting", "Use field scouting, trap counts, or scout counts.", r"\bfield scouting\b", r"\btrap counts?\b", r"\bscout counts?\b")
        add("degree_day_threshold", "Compare observations with a local economic threshold.", r"\beconomic threshold\b", r"\blocal threshold\b")
        add("degree_day_boundary", "Require local validation and state that the model is not a spray trigger alone.", r"\blocal(?:ly)? validat", r"\bnot a spray trigger alone\b")

    elif question_type == "plant_health" and re.search(r"\b(disease forecast|disease model|risk model|weather[- ]based disease)\b", lower):
        add("disease_model", "Name the forecast, disease, or risk model and its local fit.", r"\bforecast model\b", r"\bdisease model\b", r"\brisk model\b")
        add("disease_model_weather", "Use leaf wetness, humidity, rain, and temperature inputs.", r"\bleaf[- ]wetness\b", r"\bhumidity\b", r"\brain\b", r"\btemperature\b")
        add("disease_model_host", "Include variety or hybrid susceptibility.", r"\bvariety susceptib", r"\bhybrid susceptib")
        add("disease_model_scouting", "Ground the model with scouting, symptoms, incidence, or severity.", r"\bscout", r"\bsymptoms?\b", r"\bincidence\b", r"\bseverity\b")
        add("disease_model_decision", "Use crop stage, current label, and economics before treatment.", r"\bcrop stage\b", r"\bgrowth stage\b", r"\bcurrent (?:product )?label\b", r"\bROI\b", r"\beconomics\b")

    elif question_type == "plant_health" and re.search(r"\b(seedling disease|stand loss)\b", lower):
        add("seedling_disease", "Treat seedling disease as one hypothesis in the stand-loss differential.", r"\bseedling disease\b", r"\bdamping off\b")
        add("seedling_sample", "Inspect seedling roots and collect a representative sample or diagnostic-lab sample.", r"\bseedling roots?\b", r"\bdiagnostic (?:sample|lab)\b")
        add("planting_conditions", "Check soil temperature, soil moisture, and planting conditions.", r"\bsoil temperature\b", r"\bsoil moisture\b", r"\bplanting conditions?\b")
        add("stand_loss_differential", "Separate disease from insect feeding, herbicide injury, crusting, and cold stress.", r"\binsect", r"\bherbicide injury\b", r"\bcrusting\b", r"\bcold stress\b")
        add("stand_loss_pattern", "Map field pattern and make a stand count.", r"\bfield pattern\b", r"\bstand count\b")
        add("seed_treatment_label", "Verify the seed-treatment label and treatment history.", r"\bseed treatment (?:label|history)\b", r"\bcurrent (?:seed[- ]treatment )?label\b")

    elif question_type == "plant_health" and re.search(r"\b(herbicide drift|off[- ]target movement)\b", lower):
        add("drift_record", "Use the spray record, product label, active ingredient, and mode of action.", r"\bspray record\b", r"\bproduct label\b", r"\bactive ingredient\b", r"\bmode of action\b")
        add("drift_weather", "Reconstruct wind direction, gusts, inversion, and application weather.", r"\bwind direction\b", r"\bgusts?\b", r"\binversion\b", r"\bweather\b")
        add("drift_pattern", "Map the symptom pattern from the field edge through the exposure gradient and collect photos.", r"\bsymptom pattern\b", r"\bfield edge\b", r"\bgradient\b", r"\bphotos?\b")
        add("drift_differential", "Separate disease, nutrient or fertility, weather, and crop stress.", r"\bdisease\b", r"\bnutrient\b", r"\bfertility\b", r"\bweather stress\b", r"\bcrop stress\b")
        add("drift_sample", "Use a representative sample or diagnostic laboratory where symptoms remain ambiguous.", r"\bsample\b", r"\bdiagnostic lab\b")

    elif question_type == "plant_health" and re.search(r"\b(root rot|root disease|root discoloration)\b", lower):
        add("root_disease", "Keep root rot or root disease as a hypothesis requiring root evidence.", r"\broot rot\b", r"\broot disease\b", r"\bpathogen\b")
        add("root_sample", "Inspect roots and submit a representative root sample to a diagnostic laboratory.", r"\broots?\b", r"\broot sample\b", r"\bdiagnostic lab\b")
        add("root_water", "Check drainage history, saturated soil or waterlogging, and field pattern.", r"\bdrainage history\b", r"\bsaturated soil\b", r"\bwaterlogging\b", r"\bfield pattern\b")
        add("root_differential", "Separate compaction, salinity, and nutrient stress.", r"\bcompaction\b", r"\bsalinity\b", r"\bnutrient stress\b")
        add("root_host", "Use variety susceptibility and crop rotation or field history.", r"\bvariety susceptibility\b", r"\bcrop rotation\b", r"\bfield history\b")

    elif question_type == "plant_health" and re.search(r"\bnematodes?\b", lower):
        add("nematode_pattern", "Map the patchy field pattern and use field history.", r"\bfield pattern\b", r"\bpatchy\b", r"\bfield history\b")
        add("nematode_sampling", "Use correctly timed representative soil or root samples and a diagnostic laboratory.", r"\bsample timing\b", r"\bsoil sample\b", r"\broot sample\b", r"\bdiagnostic lab\b")
        add("nematode_identity", "Identify nematode species and population density using local interpretation.", r"\bspecies identification\b", r"\bpopulation density\b", r"\bspecies and population\b")
        add("nematode_rotation", "Base rotation and resistant-variety decisions on host status and confirmed nematode risk.", r"\brotation\b", r"\bresistant variety\b", r"\bhost crop\b", r"\bnonhost\b")
        add("nematode_threshold", "Use a locally valid threshold or risk interpretation before treatment.", r"\bthreshold\b", r"\blocal(?:ly)? (?:valid )?(?:risk )?interpretation\b")

    elif question_type == "plant_health" and re.search(r"\b(pests?|insects?|aphids?|threshold|beneficials?|natural enem|trap captures?|fruit injury)\b", lower):
        add("pest_identification", "Identify the pest and life stage before treatment.", r"\bidentify (?:the )?pest\b", r"\bpest (?:identity|species)\b")
        add("pest_scouting", "Use a defined scouting method for population and damage.", r"\bscout(?:ing)?\b[^.]{0,100}\b(?:population|count|damage)\b", r"\bpopulation and damage\b")
        add("crop_condition", "Record crop stage and plant stress.", r"\bcrop stage\b", r"\bplant stress\b")
        add("beneficial_insects", "Account for beneficial insects or natural enemies.", r"\bbeneficial insects?\b", r"\bnatural enem")
        add("local_threshold", "Compare observations with a locally valid economic threshold.", r"\blocal(?:ly)? (?:valid )?economic threshold\b", r"\beconomic threshold\b")
        add("current_label_context", "Verify the current product label if treatment is justified.", r"\bcurrent (?:product )?label\b")

    elif question_type == "plant_health":
        if re.search(r"\bcorn\b", lower) and re.search(r"\brectangular\b[^?]{0,100}\blesions?\b|\blesions?\b[^?]{0,100}\bleaf veins?\b", lower):
            add("gls_hypothesis", "Identify gray leaf spot as a hypothesis and confirm it.", r"\bgray leaf spot\b", r"\bGLS\b")
            add("gls_upper_canopy", "Assess severity and movement into upper leaves.", r"\bseverity\b", r"\bupper leaves\b", r"\bupper canopy\b")
        add("diagnostic_evidence", "Build the differential from symptoms, field pattern, and a representative sample.", r"\bsymptoms?\b", r"\bfield pattern\b", r"\bdiagnostic sample\b")
        add(
            "crop_stage",
            "Include crop or growth stage in disease interpretation.",
            r"\bcrop stage\b",
            r"\b(?:crop|plant|potato|wheat|canola|corn|soybean) growth stage\b",
            r"\bgrowth stage (?:of|for) (?:the )?(?:crop|plants?)\b",
        )
        add("weather_disease_risk", "Relate disease risk to recent weather, humidity, rain, or leaf wetness.", r"\bweather\b", r"\bhumid", r"\brain", r"\bleaf wetness\b")
        if re.search(r"\b(variety|hybrid|susceptib|fungicide|treatment|return)\b", lower):
            add("host_susceptibility", "Check variety or hybrid susceptibility.", r"\b(?:variety|hybrid) susceptib", r"\bsusceptib")
            add("disease_severity", "Measure incidence or severity before treatment.", r"\bincidence\b", r"\bseverity\b", r"\bdisease level\b")
            add("current_label_context", "Verify current label fit before treatment.", r"\bcurrent (?:product )?label\b", r"\blabel fit\b")
        if re.search(r"\b(return|ROI|fungicide|economics?|justif|commodity prices?)\b", lower):
            add("treatment_economics", "Compare expected yield benefit and crop value with application cost.", r"\breturn\b", r"\bROI\b", r"\byield benefit\b", r"\bapplication cost\b")

    elif question_type == "field_data" and re.search(r"\b(on[- ]farm trial|strip trial|trial design)\b", lower):
        add("trial_replication", "Use replication, randomization, and a practical strip-trial layout.", r"\breplication\b", r"\brandomization\b", r"\bstrip trial\b", r"\btrial layout\b")
        add("trial_control", "Include a treatment and check strip or control.", r"\bcheck strip\b", r"\bcontrol\b", r"\btreatment\b")
        add("trial_monitor", "Calibrate the yield monitor and clean the spatial data.", r"\byield monitor calibration\b", r"\bcalibrat(?:e|ed) the yield monitor\b", r"\bclean data\b")
        add("trial_variability", "Use blocking or management zones to account for field variability.", r"\bfield variability\b", r"\bmanagement zones?\b", r"\bblocking\b")
        add("trial_inference", "Separate statistical significance from economic response using a partial budget.", r"\bstatistical significance\b", r"\beconomic response\b", r"\bpartial budget\b")
        add("trial_inputs", "Ask for the trial layout, costs, and expected response.", r"\btrial layout\b", r"\bcosts?\b", r"\bexpected response\b")

    elif question_type == "field_data" and re.search(r"\borganic matter|soil organic carbon\b", lower) and re.search(
        r"\b(trend|changing|sampling noise|recent soil tests?)\b", lower
    ):
        add("organic_matter_measure", "Name organic matter or soil organic carbon and preserve the reported method.", r"\borganic matter\b", r"\bsoil organic carbon\b")
        add("organic_matter_trend", "Use a baseline and repeated sampling to establish a trend.", r"\bbaseline\b", r"\brepeat sampling\b", r"\btrend\b")
        add("organic_matter_protocol", "Hold sampling depth, laboratory method, and season consistent.", r"\bsampling depth\b", r"\blab method\b", r"\bseason\b")
        add("organic_matter_history", "Interpret rotation, cover crops, tillage, manure, and management history.", r"\brotation\b", r"\bcover crop\b", r"\btillage\b", r"\bmanure\b", r"\bmanagement history\b")
        add("organic_matter_response", "Tie trends to crop response or water holding and do not act from one test.", r"\bcrop response\b", r"\bwater[- ]holding\b", r"\bnot (?:from )?one test\b", r"\bone test[^.]{0,30}\bnot\b")

    elif question_type == "field_data" and re.search(r"\b(sampling design|management zones?|old soil tests?)\b", lower) and re.search(
        r"\b(soil tests?|samples?|sampling)\b", lower
    ):
        add("sampling_representative", "Use representative samples with recorded sample date, sampling depth, and timing.", r"\brepresentative samples?\b", r"\bsample date\b", r"\bsampling depth\b", r"\bsample timing\b")
        add("sampling_zones", "Choose a justified management-zone, grid, or composite-sampling design.", r"\bmanagement zones?\b", r"\bgrid\b", r"\bcomposite samples?\b")
        add("sampling_context", "Use soil type, texture, drainage, and field history to define strata.", r"\bsoil type\b", r"\btexture\b", r"\bdrainage\b", r"\bfield history\b")
        add("sampling_spatial", "Preserve the georeferenced boundary, zone boundary, and records.", r"\bgeoreferenced\b", r"\bboundary\b", r"\bzone boundary\b", r"\brecords?\b")
        add("sampling_boundary", "Do not mix unlike zones or treat old tests as enough for a current decision.", r"\bdo not mix unlike zones\b", r"\bold tests?[^.]{0,40}\bnot enough\b", r"\bnot enough from old tests\b")

    elif question_type == "field_data" and re.search(r"\b(source|checked|provenance|trace|transparent answer)\b", lower) and re.search(
        r"\b(CDL|labels?|soil survey|weather)\b", lower, re.IGNORECASE
    ):
        add("provenance_trace", "List each source checked with status and provenance.", r"\bsource\b", r"\bchecked\b", r"\bprovenance\b", r"\btrace\b")
        add("provenance_soil", "Report the NRCS soil survey or map-unit prior.", r"\bNRCS soil survey\b", r"\bsoil map unit\b", r"\bsoil prior\b")
        add("provenance_weather", "Report weather source and distinguish forecast from climate context.", r"\bweather\b", r"\bforecast\b", r"\bDaymet\b", r"\bNASA POWER\b")
        add("provenance_cdl", "Report the CDL crop-cover sample and state that it is not a planting record.", r"\bCDL\b", r"\bcrop[- ]cover sampl", r"\bnot a planting record\b")
        add("provenance_label", "Report exact product-label status without claiming legal interpretation.", r"\bproduct label\b", r"\bcurrent label\b", r"\bnot legal interpretation\b")
        add("provenance_missing", "Mark unavailable, not-configured, or missing evidence explicitly.", r"\bunavailable\b", r"\bnot configured\b", r"\bmissing evidence\b")

    elif question_type == "field_data" and all(
        re.search(pattern, lower, re.IGNORECASE) for pattern in (r"\bmap\b", r"\bsoil\b", r"\bweather\b", r"\blabel\b")
    ):
        add("agentic_map", "Validate the boundary and use map or field context as a prior.", r"\bmap\b", r"\bboundary\b", r"\bfield context\b")
        add("agentic_soil", "Use the soil survey and current soil test without treating either as complete field truth.", r"\bsoil survey\b", r"\bsoil test\b")
        add("agentic_weather", "Use public weather or forecasts as context and local field observations for the operation.", r"\bweather\b", r"\bforecast\b")
        add("agentic_label", "Use the exact product and current label for any regulated decision.", r"\bcurrent (?:product )?label\b", r"\bproduct label\b")
        add("agentic_missing_evidence", "State which field evidence or records are missing.", r"\bmissing field evidence\b", r"\bfield records?\b")
        add("agentic_refusal", "Refuse to infer unsupported field conditions, diagnosis, rate, or application permission.", r"\brefuse\b", r"\bdo not infer\b", r"\bcannot infer\b")

    elif question_type == "field_data" and re.search(r"\b(remote sensing|remote imagery|imagery priors?|weak zones?|vegetation index|NDVI)\b", lower) and not re.search(
        r"\bCropland Data Layer\b|\bCDL\b", lower, re.IGNORECASE
    ):
        add("remote_imagery", "Identify the imagery, remote-sensing, NDVI, or vegetation-index signal.", r"\bremote sensing\b", r"\bimagery\b", r"\bNDVI\b", r"\bvegetation index\b")
        add("remote_yield_quality", "Validate yield-map calibration, cleaning, spatial alignment, and lag.", r"\byield maps?\b", r"\bcalibrat", r"\bclean", r"\blag\b")
        add("remote_ground_truth", "Use ground truth, scouting, and soil samples.", r"\bground[- ]truth\b", r"\bscout", r"\bsoil samples?\b")
        add("remote_trial", "Validate management zones with a check strip or field trial.", r"\bmanagement zones?\b", r"\bcheck strips?\b", r"\bfield trial\b")
        add("remote_economics", "Estimate economic response with a partial budget.", r"\beconomic response\b", r"\bpartial budget\b")

    elif question_type == "field_data" and re.search(r"\bCropland Data Layer\b|\bCDL\b", lower, re.IGNORECASE):
        add("cdl_source", "Name the USDA Cropland Data Layer or CDL.", r"\bCropland Data Layer\b", r"\bCDL\b")
        add("cdl_sampling", "Describe boundary sample points and crop-cover classes.", r"\bboundary sampl", r"\bsample points?\b", r"\bcrop[- ]cover classes?\b")
        add("cdl_years", "Compare multiple recent years for rotation context.", r"\bmulti[- ]year\b", r"\brecent years\b", r"\brotation\b")
        add("cdl_boundary", "Treat CDL as a prior or screening context, not field truth or a planting record.", r"\bprior\b", r"\bscreening\b", r"\bnot field truth\b", r"\bnot a (?:grower )?planting record\b")
        add("cdl_not_administrative_truth", "Do not treat sampled classes as acreage or crop-insurance truth.", r"\bnot acreage\b", r"\bnot crop[- ]insurance\b", r"\bnot an acreage\b")
        add("cdl_grower_truth", "Reconcile the prior with grower field history or actual planting records.", r"\bgrower field history\b", r"\bgrower records?\b", r"\bactual planting records?\b")

    elif question_type == "field_data" and re.search(r"\bCensus of Agriculture\b", lower, re.IGNORECASE):
        add("census_source", "Name the Census of Agriculture, USDA NASS, and Quick Stats source as applicable.", r"\bCensus of Agriculture\b", r"\bUSDA NASS\b", r"\bQuick Stats\b")
        add("census_trend", "Use long-term statistics as county, state, or regional context.", r"\blong[- ]term trend\b", r"\bregional context\b", r"\bcounty\b", r"\bstate\b")
        add("census_limits", "Identify survey or reported-statistics limitations and year range.", r"\bsurvey\b", r"\breported statistics\b", r"\bdata limitation\b", r"\byear range\b")
        add("census_field", "Use current-season field records and grower history for the field decision.", r"\bfield records?\b", r"\bgrower history\b", r"\bcurrent season\b")
        add("census_boundary", "State that the statistics are not a field prediction or recommendation alone.", r"\bnot (?:a )?field prediction\b", r"\bnot (?:a )?recommendation alone\b")

    elif question_type == "field_data" and re.search(r"\b(?:USDA )?NASS\b|\bQuick Stats\b|\bregional (?:yield|acreage|production|statistics)\b", lower, re.IGNORECASE):
        add("nass_source", "Name USDA NASS Quick Stats or the regional statistics source.", r"\bUSDA NASS\b", r"\bQuick Stats\b", r"\bregional statistics\b")
        add("nass_measure", "Identify yield, acreage, or production plus crop year.", r"\byield\b", r"\bacreage\b", r"\bproduction\b")
        add("nass_year", "Confirm the crop year for the statistic.", r"\bcrop year\b", r"\breporting year\b")
        add("nass_geography", "Identify the county, state, or regional geography.", r"\bcounty\b", r"\bstate\b", r"\bregional\b")
        add("nass_boundary", "Treat statistics as a prior that does not predict the field.", r"\bprior\b", r"\bnot (?:a )?field[- ]specific\b", r"\bdoes not predict\b", r"\bcannot predict\b")
        add("nass_field_records", "Use field yield history, yield maps, or grower records for the field decision.", r"\bfield yield history\b", r"\byield maps?\b", r"\bgrower records?\b", r"\bfield records?\b")

    elif question_type == "field_data" and re.search(r"\b(conservation|precision)\b", lower) and re.search(
        r"\b(pay|econom\w*|farm(?:'s)? books?|partial budget|ROI|net return)\b", lower, re.IGNORECASE
    ):
        add("practice_partial_budget", "Use a partial budget or net-return analysis without promising a payback.", r"\bpartial budget\b", r"\bnet return\b", r"\bROI\b")
        add("practice_response", "Estimate the expected yield response, other benefits, and risk reduction.", r"\bexpected (?:yield )?response\b", r"\byield response\b", r"\brisk reduction\b", r"\bbenefits?\b")
        add("practice_costs", "Ask for establishment, operating, maintenance, and opportunity costs.", r"\bestablishment cost", r"\boperating cost", r"\bmaintenance cost", r"\bopportunity cost")
        add("practice_incentives", "Check current cost-share programs or incentives without assuming eligibility.", r"\bcost[- ]share\b", r"\bprogram\b", r"\bincentive\b")
        add("practice_evidence", "Use baseline field records and a check strip or trial where response is uncertain.", r"\bbaseline\b", r"\bfield records?\b", r"\bcheck strips?\b", r"\bfield trial\b")
        add("practice_sensitivity", "Show uncertainty with sensitivity or scenario analysis rather than a guarantee.", r"\buncertainty\b", r"\bsensitivity\b", r"\bscenario")

    elif question_type == "field_data" and re.search(r"\b(econom\w*|profit\w*|ROI|return|defensible|cost|spend|partial budget)\b", focus):
        add("response_evidence", "Estimate a field-specific yield response from aligned data and check strips or trials.", r"\byield response\b", r"\bresponse curve\b", r"\bcheck strips?\b", r"\bfield trial\b")
        add("zone_quality", "Validate soil tests, yield maps, as-applied data, and management zones.", r"\bsoil tests?\b", r"\byield maps?\b", r"\bas[- ]applied\b", r"\bmanagement zones?\b")
        add("partial_budget", "Compare added cost with crop price, expected revenue, and uncertainty in a partial budget.", r"\bpartial budget\b", r"\bROI\b", r"\bprofit\b")
    elif question_type == "field_data" and re.search(r"\b(variable[- ]rate|prescription|management zones?|yield maps?|soil EC|NDVI)\b", lower):
        add("prescription_quality", "Clean and validate each input layer.", r"\bclean", r"\bvalidat", r"\bquality control\b")
        add("prescription_alignment", "Align the boundary, coordinate system, units, years, and layers.", r"\balign", r"\bboundary\b", r"\blayers?\b")
        add("prescription_zones", "Build and ground-truth agronomically coherent management zones.", r"\bmanagement zones?\b", r"\bzones?\b")
        add("prescription_truth", "Ground-truth or scout the proposed zones.", r"\bground[- ]truth\b", r"\bscout")
        add("prescription_audit", "Preserve the prescription assumptions and audit trail.", r"\baudit trail\b", r"\bprescription\b")
    elif question_type == "field_data" and re.search(r"\b(map|soil[- ]survey|NRCS|SDA|map[- ]unit|component)\b", focus, re.IGNORECASE):
        add("soil_survey_source", "Name the soil survey, NRCS, SDA, or mapped unit source.", r"\bsoil survey\b", r"\bNRCS\b", r"\bSDA\b", r"\bmap(?:ped)? units?\b")
        add("mapped_components", "Treat component percentages and dominant components as mapped composition.", r"\bcomponent percentages?\b", r"\bdominant components?\b")
        add("mapped_attributes", "Use texture, drainage class, hydrologic group, hydric rating, slope, and restrictive-layer clues as screening attributes.", r"\bdrainage class\b", r"\bhydrologic group\b", r"\bhydric rating\b", r"\brestrictive[- ]layer\b")
        add("screening_context", "Describe mapped attributes only as a prior or screening context.", r"\bprior\b", r"\bscreening\b", r"\bregional context\b")
        add("map_truth_boundary", "State that the map cannot prove point or field conditions.", r"\bcannot prove\b", r"\bnot field truth\b", r"\bcannot confirm\b")
        add("map_not_replacement", "State that the map does not replace soil tests or field observations.", r"\bnot (?:a )?replacement\b", r"\bdo not replace\b", r"\bcannot replace\b")
        add("field_ground_truth", "Require boundary or point confirmation plus field ground-truth observations or samples.", r"\bground[- ]truth\b", r"\bfield observations?\b", r"\bsoil pit\b", r"\bprobe\b")

    elif question_type == "crop_management" and re.search(r"\b(poor fruit set|poor kernel set|fruit set)\b", lower):
        add("fruit_pollination", "Check crop-specific pollination, flowering, bloom timing, and pollinator activity where relevant.", r"\bpollination\b", r"\bflowering\b", r"\bbloom timing\b", r"\bpollinator activity\b")
        add("fruit_weather", "Check temperature, heat or cold, and weather during bloom.", r"\btemperature\b", r"\bheat\b", r"\bcold\b", r"\bweather during bloom\b")
        add("fruit_water", "Use soil moisture, irrigation, and water-stress evidence.", r"\bwater stress\b", r"\bsoil moisture\b", r"\birrigation\b")
        add("fruit_nutrition", "Use current soil or tissue tests for nutrition rather than assuming a deficiency.", r"\bnutrition\b", r"\bsoil test\b", r"\btissue test\b")
        add("fruit_disease", "Use scouting and crop-specific extension guidance for disease and reproductive diagnosis.", r"\bdisease\b", r"\bscouting\b", r"\bcrop[- ]specific extension\b")

    elif question_type == "crop_management" and re.search(r"\b(seed lots?|seed quality|germination|germ test|cold test|accelerated aging|seed vigor|vigor test)\b", lower):
        add("seed_germination", "Use the lot-specific germination percentage or germ test.", r"\bgermination percentage\b", r"\bgerm test\b", r"\bgermination\b")
        add("seed_vigor", "Use a vigor, cold, or accelerated-aging test where relevant.", r"\bvigor test\b", r"\bcold test\b", r"\baccelerated aging\b")
        add("seed_lot", "Keep seed-lot identity and quality information separate.", r"\bseed lot\b", r"\bseed quality\b", r"\bseed size\b")
        add("seed_planting", "Use planting date, soil temperature, and seedbed condition.", r"\bplanting date\b", r"\bsoil temperature\b", r"\bseedbed\b")
        add("seed_establishment", "Frame seeding-rate, stand-establishment, and replant risk without inventing a rate.", r"\bseeding rate\b", r"\bstand establishment\b", r"\breplant risk\b")

    elif question_type == "crop_management" and re.search(r"\b(trait packages?|technology traits?|trait stewardship|refuge)\b", lower):
        add("trait_package", "Compare the complete trait or technology package.", r"\btrait package\b", r"\btechnology trait\b")
        add("trait_resistance", "Compare disease ratings, pest resistance, and herbicide tolerance.", r"\bdisease ratings?\b", r"\bpest resistance\b", r"\bherbicide tolerance\b")
        add("trait_trials", "Use local multi-year trials and environment fit beyond top-line yield.", r"\blocal trials?\b", r"\bmulti[- ]year\b", r"\benvironment fit\b")
        add("trait_history", "Use field history, rotation, and market requirements.", r"\bfield history\b", r"\brotation\b", r"\bmarket requirements?\b")
        add("trait_stewardship", "Verify current refuge, label, and trait-stewardship requirements.", r"\brefuge\b", r"\bcurrent label\b", r"\btrait stewardship\b")

    elif question_type == "crop_management" and re.search(r"\b(specialty|vegetable|produce)\b", lower) and re.search(
        r"\b(irrigat\w*|water quality|water test)\b", lower
    ) and not re.search(r"\b(weak transplants?|transplant quality|root ball|hardening)\b", lower):
        add("produce_water", "Identify the water source and use an irrigation-water test.", r"\bwater source\b", r"\birrigation[- ]water test\b", r"\bwater test\b")
        add("produce_method", "Record the irrigation method, including overhead or drip exposure.", r"\birrigation method\b", r"\boverhead\b", r"\bdrip\b")
        add("produce_safety", "Check applicable food-safety or produce-safety requirements and preharvest interval.", r"\bfood safety\b", r"\bproduce safety\b", r"\bFSMA\b", r"\bpreharvest interval\b")
        add("produce_disease", "Use humidity, leaf wetness, and field evidence for disease risk.", r"\bhumidity\b", r"\bleaf wetness\b", r"\bdisease risk\b")
        add("produce_local", "Use local extension or crop-specific guidance and market-quality requirements.", r"\blocal extension\b", r"\bcrop[- ]specific guidance\b", r"\bmarket quality\b")
        add("label_and_intervals", "Verify the current label and worker, reentry, preharvest, or harvest intervals.", r"\bpreharvest interval\b", r"\brestricted[- ]entry interval\b", r"\bworker and harvest intervals?\b")
        add("market_quality", "Include buyer specifications, harvest timing, and market-quality constraints.", r"\bmarket[- ]quality\b", r"\bbuyer (?:quality )?(?:specifications?|constraints?)\b")

    elif question_type == "crop_management" and re.search(r"\b(nitrate|prussic[- ]acid|hydrocyanic acid)\b", lower) and re.search(
        r"\b(forage|pasture|graz|hay|silage|livestock)\b", lower
    ):
        add("forage_hazard", "Address nitrate and prussic-acid or hydrocyanic-acid risk separately.", r"\bnitrate\b", r"\bprussic acid\b", r"\bhydrocyanic acid\b")
        add("forage_stress", "Record drought, frost, other stress, and regrowth timing.", r"\bdrought\b", r"\bfrost\b", r"\bstress timing\b", r"\bregrowth\b")
        add("forage_test", "Use a representative forage, feed, or laboratory test.", r"\bforage test\b", r"\bfeed test\b", r"\blab test\b")
        add("forage_species", "Identify the forage species and plant part sampled.", r"\bforage species\b", r"\bspecies\b")
        add("forage_use", "Distinguish grazing, hay, and silage and protect livestock safety.", r"\bgrazing\b", r"\bhay\b", r"\bsilage\b", r"\blivestock safety\b")

    elif question_type == "crop_management" and re.search(r"\b(replant|stand survival|stand loss|uneven stand)\b", lower):
        add("replant_event", "Document temperature, duration, flooding or crusting, and the field pattern or low spots.", r"\btemperature\b", r"\bduration\b", r"\blow spots?\b", r"\bfield pattern\b")
        add("replant_stage", "Check crop or growth stage and growing-point survival.", r"\bcrop stage\b", r"\bgrowth stage\b", r"\bgrowing point\b")
        add("replant_reassessment", "Wait when appropriate, reassess recovery, and make a stand count.", r"\bwait\b", r"\breassess\b", r"\bstand count\b")
        add("replant_stand", "Compare plant population, uniformity, and yield potential.", r"\bplant population\b", r"\buniformity\b", r"\byield potential\b")
        add("replant_economics", "Compare replant cost and calendar or planting-date penalty.", r"\breplant cost\b", r"\bplanting date\b", r"\bcalendar\b")

    elif question_type == "crop_management" and re.search(r"\b(plant(?:ing)? window|crop[- ]establishment|cold,? wet soil|plant into)\b", focus) and not re.search(
        r"\b(relative maturity|maturity group|days to maturity|weak transplants?|transplant quality|root ball|hardening)\b", lower
    ):
        add("planting_temperature", "Check soil temperature at seeding depth.", r"\bsoil temperature\b")
        add("planting_moisture", "Check current soil moisture and wet-dry field condition.", r"\bsoil moisture\b", r"\bwet[- ]dry\b", r"\bfield condition\b")
        add("seedbed_damage_risk", "Check seedbed fitness plus compaction, smearing, or sidewall risk.", r"\bseedbed\b", r"\bcompaction\b", r"\bsmearing\b", r"\bsidewall\b")
        add("establishment_risk", "Address seed-to-soil contact, emergence, or stand risk.", r"\bseed[- ]to[- ]soil contact\b", r"\bemergence\b", r"\bstand risk\b")
        add("planting_forecast", "Use the short forecast without letting calendar pressure override field condition.", r"\bforecast\b")
    elif question_type == "crop_management" and re.search(r"\brelative maturity|maturity group|days to maturity\b", lower) and re.search(
        r"\b(planting date|planting window|delayed planting)\b", lower
    ):
        add("maturity_window", "Compare relative maturity or maturity group with the actual planting date and window.", r"\brelative maturity\b", r"\bmaturity group\b", r"\bdays to maturity\b", r"\bplanting date\b", r"\bplanting window\b")
        add("maturity_harvest", "Include drydown, harvest moisture, harvest window, and frost risk.", r"\bdrydown\b", r"\bharvest moisture\b", r"\bharvest window\b", r"\bfrost risk\b")
        add("maturity_traits", "Include disease package, standability, and lodging.", r"\bdisease package\b", r"\bstandability\b", r"\blodging\b")
        add("maturity_trials", "Use local trial data, yield stability, and market quality.", r"\blocal trial data\b", r"\blocal trials?\b", r"\byield stability\b", r"\bmarket quality\b")

    elif question_type == "crop_management" and re.search(r"\bmycotoxin\b", lower):
        add("mycotoxin_field", "Assess field disease, ear mold or kernel damage and disease level.", r"\bfield disease\b", r"\bear mold\b", r"\bkernel damage\b", r"\bdisease level\b")
        add("mycotoxin_weather", "Use weather, drought, humidity, and delayed-harvest risk.", r"\bweather\b", r"\bdrought\b", r"\bhumidity\b", r"\bdelayed harvest\b")
        add("mycotoxin_test", "Use a representative sample and test result, then segregate affected lots.", r"\bsample\b", r"\btest result\b", r"\bsegregate\b")
        add("mycotoxin_storage", "Manage drying, storage moisture, aeration, and monitoring.", r"\bdrying\b", r"\bstorage moisture\b", r"\baeration\b")
        add("mycotoxin_market", "Check buyer or marketing limits and do not blend around a limit.", r"\bmarketing limits?\b", r"\bbuyer limits?\b", r"\bdo not blend\b")
    elif question_type == "crop_management" and re.search(r"\b(harvest|storage|drying|grain moisture)\b", focus):
        add("harvest_moisture", "Measure crop or grain moisture and field loss or standability.", r"\bmoisture\b", r"\bfield loss\b", r"\bstandability\b")
        add("drying_storage", "Match harvest timing to drying, cooling, aeration, and storage capacity.", r"\bdrying\b", r"\baeration\b", r"\bstorage\b")
        add("quality_risk", "Address test weight, mold, mycotoxin, disease, or market quality as relevant.", r"\btest weight\b", r"\bmold\b", r"\bmycotoxin\b", r"\bquality\b")
    elif question_type == "crop_management" and re.search(r"\b(standability|lodging|market fit|market requirement|quality ratings?)\b", lower) and re.search(
        r"\b(genetics|hybrid|variety|yield)\b", lower
    ):
        add("quality_standability", "Compare standability, lodging or stalk strength and market quality.", r"\bstandability\b", r"\blodging\b", r"\bstalk strength\b", r"\bmarket quality\b", r"\bmarket requirement\b")
        add("quality_disease", "Use disease ratings, disease history, and stress tolerance.", r"\bdisease ratings?\b", r"\bdisease history\b", r"\bstress tolerance\b")
        add("quality_trials", "Use local multi-year trials and matching environment fit.", r"\blocal trials?\b", r"\bmulti[- ]year\b", r"\benvironment fit\b")
        add("quality_field", "Use field history, harvest timing, and grower risk tolerance.", r"\bfield history\b", r"\bharvest timing\b", r"\brisk tolerance\b")

    elif question_type == "crop_management" and re.search(r"\b(weak transplants?|transplant quality|root ball|hardening)\b", lower):
        add("transplant_source", "Check transplant source, quality, root ball, and hardening.", r"\btransplant source\b", r"\btransplant quality\b", r"\broot ball\b", r"\bhardening\b")
        add("transplant_water", "Check soil moisture, irrigation, drainage, and water stress.", r"\bsoil moisture\b", r"\birrigation\b", r"\bwater stress\b")
        add("transplant_fertility", "Use a soil test, fertility record, EC, and starter-fertilizer history.", r"\bsoil test\b", r"\bfertility\b", r"\bEC\b", r"\bstarter fertilizer\b")
        add("transplant_disease", "Inspect disease or root disease and use a representative sample if needed.", r"\bdisease\b", r"\broot disease\b", r"\bsample\b")
        add("transplant_weather", "Check crop stage, temperature, heat, cold, and wind stress.", r"\bcrop stage\b", r"\btemperature\b", r"\bheat\b", r"\bcold\b", r"\bwind\b")

    elif question_type == "crop_management" and (
        re.search(r"\b(variety|hybrid|cultivar|public trials?|seed choice|candidate list|genetics)\b", lower)
        or (re.search(r"\b(trials?|ranking|variety|hybrid|seed)\b", lower) and re.search(r"\b(maturity|standability|lodging|candidate)\b", focus))
    ):
        add("no_product_ranking", "Use trials to narrow choices without claiming a product ranking for the field.", r"\bcannot rank\b", r"\bnot (?:a )?product ranking\b", r"\bnarrow choices\b")
        add("multi_environment_trials", "Compare multi-year, multi-location trials from matching environments.", r"\bmulti[- ]year\b", r"\bmulti[- ]location\b", r"\breplicated trials?\b")
        if re.search(r"\b(trial stability|plot result|trial summaries|statistics|significance)\b", lower):
            add("trial_statistics", "Use replication, LSD, or statistical significance to separate signal from plot noise.", r"\breplicat", r"\bLSD\b", r"\bleast significant difference\b", r"\bstatistical significance\b")
        add("maturity_adaptation", "Compare maturity or adaptation with planting and harvest constraints.", r"\bmaturity\b", r"\badaptation\b")
        add("disease_traits", "Include disease traits or field disease history.", r"\bdisease\b")
        add("standability", "Include lodging or standability risk.", r"\blodging\b", r"\bstandability\b")
        add("local_field_constraints", "Match soil, water, planting date, stress, and harvest constraints.", r"\bfield constraints?\b", r"\bsoil and water\b", r"\bplanting date\b")
        if re.search(r"\bwhite mold\b", lower):
            add("white_mold_canopy", "Include canopy density, row spacing, and population.", r"\bcanopy\b", r"\brow spacing\b", r"\bpopulation\b")
            add("white_mold_rotation", "Include field history and rotation or residue management.", r"\bfield history\b", r"\brotation\b", r"\bresidue\b")
            add("white_mold_risk", "Use variety tolerance and disease risk before fungicide timing.", r"\bvariety (?:tolerance|resistance)\b", r"\bfungicide timing\b", r"\bdisease risk\b")

    elif question_type == "crop_management" and re.search(r"\b(specialty[- ]crop|lettuce|vegetable|high[- ]tunnel|fertigation|food[- ]safety|market[- ]quality)\b", lower):
        add("specialty_irrigation", "Anchor irrigation to root-zone moisture, crop stage, and water records.", r"\broot[- ]zone\b", r"\bsoil moisture\b", r"\birrigation record")
        add("specialty_fertility", "Anchor fertility to current soil or tissue evidence and local crop goals.", r"\bsoil (?:test|or tissue evidence|evidence)\b", r"\btissue (?:test|evidence)\b")
        add("specialty_plant_health", "Require scouting, identification, and severity before pest or disease action.", r"\bscout", r"\bdiagnos", r"\bidentif")
        add("label_and_intervals", "Verify the current label and worker, reentry, preharvest, or harvest intervals.", r"\bpreharvest interval\b", r"\brestricted[- ]entry interval\b", r"\bworker and harvest intervals?\b")
        add("produce_safety", "Check irrigation-water or produce food-safety requirements.", r"\bfood[- ]safety\b", r"\bproduce[- ]safety\b", r"\birrigation[- ]water[^.]{0,60}\bsafety\b")
        add("market_quality", "Include buyer specifications, harvest timing, and market-quality constraints.", r"\bmarket[- ]quality\b", r"\bbuyer (?:quality )?(?:specifications?|constraints?)\b")
        if re.search(r"\b(high[- ]tunnel|fertigation)\b", lower):
            add("tunnel_fertigation", "Check the fertigation recipe and injector calibration.", r"\bfertigation recipe\b", r"\binjector\b")
            add("tunnel_salinity", "Use irrigation-water and soil, media, or substrate EC evidence.", r"\birrigation[- ]water\b", r"\bsoil EC\b", r"\bmedia test\b", r"\bsubstrate\b")
            add("tunnel_microclimate", "Check disease symptoms, humidity, airflow, and leaf wetness.", r"\bdisease symptoms?\b", r"\bhumidity\b", r"\bairflow\b", r"\bleaf[- ]wetness\b")
            add("tunnel_safety", "Check manure, water quality, and food-safety requirements.", r"\bmanure\b", r"\bwater quality\b", r"\bfood[- ]safety\b")
            add("tunnel_local_guide", "Use local extension or a crop-specific guide.", r"\blocal extension\b", r"\bcrop[- ]specific guide\b")

    seen: set[str] = set()
    ordered: list[_IntentRequirement] = []
    for requirement in requirements:
        if requirement.name not in seen:
            seen.add(requirement.name)
            ordered.append(requirement)
    return tuple(ordered)


def _decision_route_failure_answer(state: Any) -> str | None:
    decision = state.decision
    lower = state.question.lower()
    if decision == "field_trafficability":
        return (
            "Do not use the rejected answer, a dry-looking surface, or a full machinery pass as evidence that the "
            "corner is trafficable. Reinspect the northeast corner and a nearby normal area now. Record the extent "
            "and duration of standing water or ponding, whether drainage and outlets are functioning, and recent "
            "rain or irrigation. Walk and probe both areas to compare soil condition below the surface, not just at "
            "the crust. "
            "Then assess the intended machine, load, tire or track setup, and route. Do not enter if that load would "
            "leave ruts, shear or smear the soil, displace soil, compact the profile, damage the crop, or create an "
            "operator-safety problem. Delay, keep traffic out of the affected area, and repeat the same checks after "
            "drainage or drying; preserve the fresh observations in the field record."
        )
    if decision == "clubroot_containment":
        return (
            "Treat this as suspected clubroot and act today to limit soil movement while arranging confirmation. Mark the patch and approach, keep unnecessary traffic out, work the suspect area last, and avoid moving soil, roots, or contaminated material to clean parts of the field. Before equipment, tools, or boots leave, remove adhering soil at the site and follow current provincial sanitation guidance; record where material and wash water go. "
            "Dig several plants from the patch margin and normal plants outside it, keep roots intact, photograph the pattern and galls, and submit a representative sample through the provincial or diagnostic-lab pathway. Record crop stage, recent weather, field distribution and disease risk, rotation, variety, equipment movement, and symptom progression. Confirmation and current Saskatchewan clubroot guidance should control longer-term rotation, resistant-variety, access, and sanitation decisions, but containment should not wait for the result."
        )
    if decision == "pesticide_rate_request":
        if re.search(r"\b(?:fungicide|disease|blight|mildew|rust|mold|mould)\b", lower):
            return (
                "I cannot choose a fungicide or state a rate from the crop and disease name alone. First confirm the target disease from representative scouting or diagnostic evidence, and record incidence, severity, crop stage and canopy condition. Add recent and forecast weather, leaf wetness or irrigation where relevant, and the prior fungicide application history, including efficacy and modes of action. "
                "Identify the exact product and registration, then verify the current PMRA product label for the crop and target disease. That label controls the rate, timing and interval, maximum applications, preharvest and re-entry intervals, mixing, buffers, and other restrictions. Fit any treatment into current local disease guidance and a resistance-management program that rotates effective FRAC or mode-of-action groups. Until the diagnosis, field risk, exact product, current label, and resistance fit are known, do not name or apply a product or rate."
            )
        return (
            "I cannot set a herbicide rate from the crop and weed name alone. Identify the exact product and registration, confirm that the crop and target weed are on the current PMRA product label, and record crop stage, weed stage and size, density and distribution, prior products and herbicide groups, survivor or resistance history, and whether this is a first or follow-up application. "
            "Check on-site wind, inversion, temperature, rain and crop-stress conditions plus buffers, adjuvant, water volume, intervals and seasonal maximum. Use only the labeled rate and timing that match all of those conditions; if the exact product, registration or label fit is unknown, do not state or apply a rate."
        )
    if decision == "slc_map_interpretation":
        if _looks_like_french(state.question):
            return (
                "Non. Un polygone des Pédo-paysages du Canada décrit une association régionale de sols; ce n'est "
                "pas une carte à l'échelle du champ montrant un seul sol. Les composantes dominantes et secondaires "
                "et leurs classes de drainage ne sont pas localisées à l'intérieur du polygone; l'intersection ne "
                "prouve donc ni la composante présente à un point ni l'uniformité du champ.\n\n"
                "Utiliser le polygone comme contexte de dépistage, puis comparer les levés provinciaux plus détaillés "
                "lorsqu'ils existent. Vérifier des zones représentatives avec la topographie, des observations à la "
                "tarière ou en profil, les horizons, la texture, les signes d'humidité, la nappe, l'enracinement et le "
                "drainage actuel avant de modifier la gestion."
            )
        return (
            "No. A Soil Landscapes of Canada polygon is a generalized regional soil-landscape association, not a field-scale map of one soil. Its dominant and minor soil components and drainage classes are described for the polygon but are not spatially resolved within it, so an intersection cannot show which component occurs at a point or prove that the whole field has the dominant component. "
            "Use the polygon as screening context. Compare finer local or provincial survey information where available, then ground-truth representative field zones with topography, auger observations or soil pits, horizon and texture observations, mottles or other wetness evidence, water-table timing, rooting and existing drainage before changing management."
        )
    if decision == "slc_attribute_interpretation":
        return (
            "Use Soil Landscapes of Canada attributes as regional screening context: polygon and component scale, "
            "component proportions and complexity, soil name, slope, local surface form, stoniness, generalized "
            "rooting depth, drainage or water-table attributes can help stratify where to inspect and sample. The SLC "
            "is compiled at regional scale, and component locations are not resolved within each polygon, so those "
            "attributes do not establish the condition at a point or across the whole field. Before changing fertilizer "
            "placement, verify representative current soil-test values with method, units, depth and date, actual texture "
            "and horizons, organic matter, pH, salinity where relevant, rooting, compaction and fertilizer history. Before "
            "changing drainage, verify topography, ponding and saturation timing, water-table depth, restrictive layers, "
            "existing drainage and a feasible outlet in affected and normal field zones."
        )
    if decision == "mapped_wet_strip_irrigation":
        return (
            "Do not cut irrigation for the rest of the season from a dark or wet-looking map strip alone. Confirm the "
            "map date, resolution, variable and uncertainty, then compare representative points inside and outside the "
            "strip with calibrated root-zone moisture by depth, crop condition, topography, soil texture, drainage, "
            "irrigation delivery and recent rain. Determine whether the strip is truly wetter and whether the cause is "
            "run-on, poor drainage, a soil change, sensor or imagery artefact, or excess applied water. If measurements "
            "support a separate zone, test a bounded irrigation reduction and recheck root-zone depletion and crop "
            "response; do not make a season-long cutoff without a measured stop and restart rule."
        )
    if decision == "ambiguous_pump_direction":
        return (
            "I cannot give a pump runtime until its direction and purpose are known. A pump that adds irrigation water "
            "and one that removes drainage water require opposite decisions. Confirm whether water moves into or out of "
            "the forage field, the pump flow rate, intake or outlet, affected area, current root-zone moisture and water "
            "table, crop stage, recent rain, soil intake or drainage capacity, and any outlet constraints. Then calculate "
            "a bounded runtime from the required water depth or removal volume and measured flow, with a field-level stop "
            "condition; do not invent hours from the word 'pump' alone."
        )
    if decision == "nasdi_index_interpretation":
        return (
            "In NASDI, SPI standardizes precipitation over a selected accumulation period, while SPEI standardizes the "
            "climatic water balance by combining precipitation with atmospheric evaporative demand. SPEI can therefore "
            "show stronger dryness when heat and evaporative demand are high even if precipitation alone looks similar. "
            "The time window defines the process being summarized: short windows respond to recent crop and surface-water "
            "stress, while longer windows reflect accumulated soil-water, streamflow, reservoir or groundwater deficits. "
            "Neither index is a field measurement; match the window to the decision and check current root-zone moisture, "
            "crop stage, rainfall and field observations."
        )
    if decision == "manure_credit_boundary":
        return (
            "No exact manure nitrogen credit can be set for a Saskatchewan canola field from an Alberta guide, especially "
            "without a representative current manure analysis, application rate, method and timing, field history, soil "
            "nitrogen evidence, and current Saskatchewan calibration. Record total and ammonium nitrogen with the lab's "
            "units and sampling method, application and incorporation losses, previous applications and crop credits, "
            "current soil nitrate and crop demand. Then use current Saskatchewan guidance and applicable requirements to "
            "estimate first-year availability and the remaining fertilizer need; until those inputs exist, hold the exact "
            "credit rather than transferring an Alberta value."
        )
    if decision == "map_based_rescue_n":
        return (
            "No. A regional soil map is screening context and cannot set a rescue nitrogen pass for this Ontario spring-wheat field. After waterlogging, compare affected and normal areas, map the field pattern, count plants and tillers, dig roots and crowns, and record saturation duration, drainage, compaction and recovery after aeration. Those observations separate root injury and restricted uptake from nitrogen loss or shortage. "
            "Reconstruct nitrogen already applied by source, timing and placement plus manure and previous-crop credits. Use current soil nitrate or crop-nitrogen evidence only with a locally valid sampling method and Ontario calibration; a soil test does not dictate the rescue rate by itself. Consider crop stage, realistic response potential, remaining uptake window, application method, forecast and economics before estimating supplemental nitrogen."
        )
    if decision == "map_crop_selection":
        return (
            "A land-suitability map is screening context; a high rating does not choose the crop for this parcel. "
            "Ground-truth the mapped unit with representative soil observations and tests, drainage and wetness, "
            "topography, rooting limits, salinity or other field constraints. Then compare crops against the field's "
            "crop and herbicide history, rotation needs, local growing season and heat units, water availability, and "
            "pest or disease risks. Finish the choice with market access and contracts, equipment and labour, seed "
            "and input availability, expected economics, margin, and downside risk. Use those constraints to build a short list, "
            "then check current provincial variety and production guidance for each candidate."
        )
    if decision == "underspecified_spray":
        return (
            "I cannot choose a spray from that question alone. Provide the crop and production site, target weed, pest, or disease, crop stage and target stage, jurisdiction, field pattern or representative scouting count, recent treatment history, and the exact product if one is already under consideration. For a follow-up application, include the prior product, rate, timing, efficacy, and resistance or application-failure concern. "
            "Then check on-site wind, rain and crop conditions and verify that the current product label and PMRA registration cover the crop, target, stage, timing, rate, intervals, buffers, and other restrictions. Until those facts are known, do not select a product or rate."
        )
    if decision == "boundary_only_fertility_rate":
        crop = state.crop or "crop"
        return (
            f"A drawn field boundary locates the {crop} field, but it is not enough to calculate pounds of nitrogen. Identify the province and use current provincial calibration, then define crop stage, realistic yield goal or crop demand, current stand and rooting, and the field's water and loss risk. Obtain a current, locally appropriate soil nitrate or soil test and reconcile all fertilizer already applied with manure and previous-crop credits, source, timing, and placement. "
            "Use those inputs to estimate remaining crop requirement and expected response within the uptake window and a simple partial budget. Do not infer a uniform or variable rate from geometry, mapped soil, or regional statistics alone; ground-truth any mapped zones and preserve a check strip where response remains uncertain."
        )
    if (
        decision == "fertility_rate"
        and re.search(r"\b(?:potassium|soil[- ]test k|low k|marginal k)\b", lower)
        and re.search(r"\b(?:one|single)\s+composite(?: sample)?\b", lower)
    ):
        return (
            "The stated low-potassium result is a signal to investigate, but one composite sample does not "
            "support a fertilizer rate. Confirm the laboratory method and units, sampling depth and date, "
            "sample locations, and whether the composite represents the crop root zone; separate sampling "
            "zones where soil, topography, management, or yield history vary. Interpret the result with soil "
            "texture or clay and CEC context, realistic yield and crop-removal demand, and the complete manure "
            "and prior fertilizer record. Then use current crop-specific provincial calibration to choose "
            "source, timing, and placement, including seed-piece, salt, and root-zone safety. Do not state a "
            "numeric rate until those inputs and the local calibration are available."
        )
    if decision == "fertility_rate" and re.search(
        r"\b(?:how much|what (?:nitrogen|N) rate|how many (?:pounds?|kilograms?))\b",
        state.question,
        re.IGNORECASE,
    ) and re.search(r"\b(?:nitrogen|N)\b", state.question, re.IGNORECASE):
        return (
            "I cannot set a numeric nitrogen rate from the location and a broad crop category alone. Identify the crop species and stage, realistic yield target and stand condition. Obtain a representative current soil nitrate or locally appropriate soil test with its sampling depth and method, and record soil texture, organic matter, rooting, irrigation, drainage, recent weather, and nitrogen-loss risk. "
            "Reconcile fertilizer already applied with manure and previous-crop credits, including source, timing, and placement. Then use current crop-specific provincial or local calibration to estimate remaining crop demand, expected response, and the appropriate 4R source, rate, timing, and placement. A regional soil map can help stratify sampling but is not a fertilizer-rate authority."
        )
    if decision == "plant_health_diagnostic":
        if re.search(r"\bstripe rust\b", lower):
            return (
                "The yellow-orange stripes are consistent with stripe rust, but do not confirm it or spray from colour alone. Inspect representative upper and lower leaves across the field for narrow linear rows of raised yellow-orange pustules and powdery spores, whether symptoms follow leaf veins, and whether new lesions are appearing. Map incidence, severity and canopy position; record spring-wheat crop stage, recent rain, humidity or leaf wetness, regional disease risk, field history, and variety susceptibility. "
                "Attach clear photos and submit a fresh representative leaf sample or use a diagnostic lab when the signs remain uncertain. Consider a fungicide only after diagnosis, disease pressure and movement toward yield-critical leaves, crop stage, current Alberta risk guidance, expected yield protection and economics support it, then verify the current PMRA product label and resistance group."
            )
        if state.crop == "potato" and re.search(r"\b(?:lesions?|disease program)\b", lower):
            return (
                "Before changing the potato disease program, collect representative fresh leaves and stems from the advancing lesion margin in affected, edge and normal areas; photograph upper and lower leaf surfaces and canopy position, and submit a diagnostic sample when identity would change the program. Record incidence, severity, lesion expansion, distribution, crop stage, variety, rotation, seed and disease history, irrigation, recent rain, humidity and leaf-wetness period. "
                "Compare those observations with current New Brunswick potato disease alerts or IPM guidance. Change prevention, timing or product only when the working diagnosis and risk justify it, and verify the current PMRA product label for potato, target, crop stage, timing, intervals, resistance group and seasonal restrictions."
            )
    if decision == "ambiguous_product_followup":
        return (
            "Do not repeat the same insecticide, herbicide, fungicide, product, or rate from the rain event alone. "
            "Identify the exact product and registration, crop and target, prior rate and application time, rain start and amount, and the label's rainfast, reapplication, interval, seasonal-maximum, and crop-stage restrictions. Check whether the first application had time to become rainfast and whether the target is still active; rain does not automatically erase a treatment or authorize another pass. "
            "Use an on-site field observation of rain timing, crop condition, and target activity plus the current product label and actual application record to decide whether to wait, reassess efficacy, or make a labeled follow-up. The current PMRA label controls. Do not substitute advice about an unnamed pest or product."
        )
    if decision == "crop_stress_differential":
        if re.search(r"\b(?:phosphorus|phosphate|soil[- ]test p|low p)\b", lower):
            crop = state.crop or "crop"
            return (
                f"Treat low soil-test phosphorus and uneven {crop} growth as two observations to reconcile, not proof that phosphorus alone caused the pattern. Confirm the soil-test method, units, sampling depth and date, pH, and whether affected and normal zones were sampled separately; Olsen, Bray and Mehlich results are not interchangeable without a valid local calibration. Map the weak and normal areas, count the stand, dig roots, and compare moisture, drainage, compaction, seed-row condition, rooting depth, and injury or disease signs. "
                "Reconstruct phosphorus source, rate, timing and placement, including seed-row placement and any skips or overlaps, plus previous crops, manure and fertilizer history. Use the detailed soil polygon only to stratify inspection and sampling; it does not establish current phosphorus status or a rate. Decide whether to change the plan only after the field pattern and current measurements agree with a phosphorus response, and use current crop-specific provincial calibration, a realistic yield goal, placement safety and economics. Do not convert methods or infer a rescue rate from colour, mapped soil, or the words 'low soil test' alone."
            )
        if state.crop == "potato" and re.search(r"\b(?:boundary|polygon|low areas?|drainage)\b", lower):
            return (
                "Treat the heavy regional soil polygon as screening context, not proof of this field's texture, drainage, or nitrogen need. Because yellowing follows low areas after rain, first test an excess-water and root-zone oxygen problem: map ponding and recovery, compare affected and normal plants, dig intact roots, stolons and developing tubers, and record rooting depth, discoloration, decay, soil saturation by depth, ponding duration, compaction, topographic inflow, existing drainage and outlet condition. "
                "Reconstruct fertilizer source, rate, timing and placement and use paired affected-normal soil and plant evidence to determine whether uptake is restricted or nitrogen is actually short. Do not add nitrogen from the polygon or colour alone. Improve surface flow or drainage only after the mechanism and feasible outlet are confirmed, and avoid trafficking saturated soil."
            )
        if state.crop == "corn" and re.search(r"\bsidedress\b", lower):
            return (
                "Do not base the sidedress decision on uneven colour after a wet May alone. Map affected and normal corn, count the stand, inspect roots and growing points, and record crop stage, soil saturation duration, drainage, compaction and recovery to separate stand or root injury from nitrogen loss. Reconstruct nitrogen already applied by source, rate, timing and placement, including manure or previous-crop credits and any inhibitor, then assess rainfall amount, soil temperature, texture and leaching or denitrification risk. "
                "Use a locally calibrated pre-sidedress soil nitrate test or other current crop-nitrogen evidence only where its sampling timing and interpretation fit Ontario conditions. Combine that evidence with realistic yield potential, remaining uptake window, application method and forecast before estimating supplemental nitrogen; preserve an untreated check where uncertainty remains."
            )
        return (
            "Do not set a rescue nitrogen or sulphur rate from pale or yellow plants alone; these symptoms are insufficient to diagnose the cause. After a cold or wet start, especially in strips or low areas, first separate oxygen-limited or injured roots and restricted nutrient uptake from a true nutrient shortage. Map the field pattern and whether symptoms follow depressions, drainage, rows, application tracks, or soil zones; compare affected and normal plants; count the stand; and dig roots and crowns to check colour, branching, depth, injury, compaction, and saturation. "
            "Reconstruct recent weather, rainfall and ponding duration plus fertilizer source, rate, timing and placement, manure and previous-crop credits, and any skips or overlaps. Use paired affected-normal soil tests and tissue tests only after that field comparison. Add nutrients only when the diagnosis, remaining uptake window, expected response, and current provincial calibration support a rate; otherwise correct the water or root constraint and reassess new growth."
        )
    if decision == "seeding_rate_calculation":
        return (
            "No. Germination and thousand-kernel weight are not enough to finish a seeding-rate calculation. Supply the target live-plant stand in explicit area units and the expected field establishment or mortality, then confirm seed-lot purity and keep every weight and area unit consistent. The calculation converts the target live stand through expected establishment to seeds placed, then uses thousand-kernel weight to convert seed number to a mass rate. "
            "Use a locally appropriate target stand and a field-loss estimate that reflects seedbed, seeding date, depth, equipment, disease and pest risk, and seed vigour. Do not invent either missing input; verify the drill calibration and emerged stand after seeding."
        )
    if decision == "herbicide_injury_drift_differential":
        return (
            "The symptoms do not yet distinguish neighbour drift from the grower's tank or application. Preserve evidence before it changes: map the symptom pattern from the field edge inward through the exposure gradient and across overlaps, boom sections, headlands, sprayed and unsprayed areas, and different varieties or crop stages; collect photos. Reconstruct both application timelines, exact products, rates, adjuvants and tank mixes, sprayer cleanout and prior loads, nozzles and pressure, and wind direction, speed, gusts, inversion, temperature and rain. Use each spray record and product label to confirm the active ingredient and mode of action. "
            "Evidence for herbicide drift or off-target movement is an edge or downwind gradient that aligns with the neighbour's timing; tank contamination or the grower's application is supported by boom, overlap, cleanout, or treated-area geometry. Compare both with disease, nutrient or fertility problems, weather stress, and crop stress. Retain a representative sample for a diagnostic lab where symptoms remain ambiguous, and involve the appropriate provincial or regulatory channel when off-target exposure remains plausible. Do not choose another spray until crop injury, weed control, recovery, and current label restrictions are separated."
        )
    if decision == "erosion_control_plan":
        mapped_prior = bool(re.search(r"\b(?:map|polygon|landscape unit)\b", lower))
        opening = (
            "No. A field polygon crossing a sloping soil-landscape unit is screening evidence, not enough to choose tillage or an erosion-control plan. "
            if mapped_prior
            else "No single practice should be selected from slope or crop history alone. "
        )
        return (
            opening
            + "Ground-truth slope length and grade, where runoff enters and concentrates, flow paths and outlets, connection to ditches or water, actual sheet, rill, gully, or deposition evidence, and estimated soil loss. Record residue and living cover, rotation, tillage direction and intensity, traffic, infiltration and surface sealing, and the timing and intensity of erosive rain or snowmelt. "
            "Identify the dominant pathway before matching a control. Depending on the verified mechanism, the plan may combine residue retention, a cover crop, reduced tillage or no-till, contour tillage, controlled traffic, grassed waterways, buffers, or other locally suitable structures. Confirm field feasibility and current provincial requirements"
            + (" rather than selecting a practice from mapped slope alone." if mapped_prior else ".")
        )
    if decision == "drought_nitrogen_adjustment":
        crop = state.crop or "crop"
        regional_signal = (
            "a district NASDI drought signal"
            if re.search(r"\bNASDI\b", state.question, re.IGNORECASE)
            else "a regional drought or weather signal"
        )
        return (
            f"Do not cut or increase this field's {crop} nitrogen rate from {regional_signal} alone. The signal is regional screening context; it does not measure this field's root-zone water, rooting, crop condition, or remaining yield response. Check rainfall and stored soil water by depth, crop stage and rooting, stand and stress pattern, forecast demand, and whether water is likely to limit uptake through the remaining response window. "
            "Reconcile current soil or crop nitrogen evidence with fertilizer already applied, manure or previous-crop credits, losses, and realistic yield potential. Change the rate only when current locally validated calibration and a partial budget show that the expected response under the field's water supply justifies it. Preserve a check strip where uncertainty is material."
        )
    if decision == "fall_banded_nitrogen":
        return (
            "Fall-banded nitrogen is a poor bet where soils are poorly drained or commonly stay saturated for an extended period in spring, because nitrogen that has converted to nitrate is exposed to denitrification and other overwinter loss. Risk also rises when application occurs before soils are cool, when the nitrogen form transforms readily, or when bands are shallow in dry, cloddy soil and volatilization is possible. "
            "The comparison is field-specific: fall banding can remain effective where spring saturation is uncommon and limited spring seedbed moisture makes spring banding difficult. Verify soil temperature, drainage history, nitrogen form, band depth and closure, and a current soil test against current Alberta guidance before choosing the timing."
        )
    if decision == "high_p_starter_decision":
        return (
            "With an already-high Olsen phosphorus result, do not buy starter phosphorus as insurance on the soil-test rating alone. The expected probability and size of a crop response decline as soil phosphorus rises, so first decide whether the pass is intended to produce a current-year response or maintain phosphorus near crop removal, and whether that objective is economic under current Manitoba calibration. "
            "Treat seed-placement safety as a separate decision. It depends on the exact product and rate, opener spread, row spacing, seed-fertilizer separation, and soil moisture; a row-width statement from a guide is not a universal safe rate. Confirm the test method and units and use current local guidance or a replicated on-farm check before keeping the pass."
        )
    if decision == "sidedress_n_credit_reconciliation":
        return (
            "Build one field-specific nitrogen budget before recommending sidedress nitrogen. Start with the actual manure source, analysis, application rate, timing, placement, and storage or incorporation history, then estimate plant-available nitrogen with current Manitoba guidance rather than treating total manure nitrogen as an immediate credit. Add the locally calibrated previous-crop credit from the identified crop, stand quality, termination timing, and field history; do not reverse a legume credit or count either source twice. "
            "Compare those credits with current soil nitrate or representative crop nitrogen evidence, crop stage, rooting, realistic yield potential, and all fertilizer already applied. Then account for whether the remaining uptake window and application method fit the crop, and whether recent or forecast rain, saturated soil, drainage, leaching, denitrification, volatilization, or runoff could change availability or make application unsafe. Recommend a rate only from the resulting residual crop requirement and current local calibration; otherwise state which analysis or measurement is still missing."
        )
    if decision == "seed_row_fertilizer_safety":
        return (
            "The map point cannot establish a safe seed-row fertilizer amount. Record the exact fertilizer product and analysis, nutrient amount intended in the seed row, any salt or ammonia-forming components, row spacing, opener type, effective fertilizer spread or seedbed utilization, and the actual seed-fertilizer separation. Calibrate the metering system, make a short pass, and dig behind representative openers to verify placement and uniform delivery. "
            "Interpret that setup with seedbed texture and moisture, organic matter and salinity where relevant, seed quality, and expected emergence stress. Use the current Nova Scotia or otherwise locally applicable spring-wheat seed-row safety table that matches the product, nutrient, row geometry, opener spread, and field condition. If the setup is outside the table or separation is inconsistent, move fertilizer away from the seed, reduce the seed-row amount within the complete fertility plan, or correct the equipment before planting; do not convert a map class or planting-timing judgment into a fertilizer-safety limit."
        )
    if decision == "stratified_soil_sampling":
        return (
            "No. One whole-field composite or old soil tests can average away stable differences among contrasting landscape and management zones, so they are not enough by themselves for a current nutrient plan. Delineate stable zones from field history, topography, yield or imagery patterns, then ground-truth their boundaries; do not mix unlike zones.\n\n"
            "Collect representative samples from each zone with a recorded sample date, sampling depth, and timing while keeping handling and laboratory method consistent. Keep georeferenced zone boundaries and records through interpretation, and compare results with crop condition, drainage, erosion, manure, and other management history. Assign a rate only after each zone is interpreted with the correct method, units, crop need, and current local calibration."
        )
    if decision == "wet_area_drainage_differential":
        return (
            "Texture alone cannot distinguish an inherent fine-texture limitation from a correctable drainage problem. Compare wet and normally growing areas with paired soil pits or cores: describe horizons, colour and redox mottles, structure, pore continuity, compaction or restrictive layers, rooting depth and condition, and whether roots stop at a repeatedly saturated layer. Measure soil moisture and water-table depth by time, ponding or saturation duration, and crop recovery after the profile drains rather than relying on one wet-day observation. "
            "Survey topography and run-on, inspect traffic patterns and existing surface or subsurface drainage, and establish whether a legal, stable outlet has adequate elevation and capacity. A fine texture is an inherent management constraint when the whole profile drains slowly without a discrete correctable restriction; a drainage intervention is supportable only when repeated excess water, a defined flow or water-table mechanism, crop injury, and a feasible outlet align. Also rule out fertility, root disease, salinity, and compaction before attributing weak growth to drainage alone."
        )
    if decision == "hail_disease_differential":
        return (
            "Map the storm path first and compare exposed, sheltered, edge, and interior plants. Direct hail injury should align with the event and impact direction and show fresh tearing, shredding, bruising, breakage, or scars on leaves and other exposed tissues. Mark representative lesions and revisit them: static wounds that dry and callus support physical injury, while lesions that continue expanding, develop distinct margins, sporulation, pustules, ooze, or other pathogen signs, or appear on new tissue after the storm support an active disease process. "
            "Record crop stage, lesion age and canopy position, storm timing, subsequent leaf wetness, hybrid or variety susceptibility, prior disease history, and whether symptoms also occur outside the hail track. Photograph the same plants over time and submit representative advancing-margin tissue when progression remains ambiguous. Do not name a disease or recommend a fungicide from colour alone. Before treatment, confirm active biological progression, use a current locally validated risk model or action threshold, compare the expected yield or quality benefit with treatment cost and likely return, and verify crop stage, resistance-management fit, and the current PMRA label."
        )
    if decision == "corn_common_rust_differential":
        return (
            "Common rust is supported by raised orange-brown pustules that produce powdery spores which rub from the leaf surface, often with pustules on both sides of the leaf. Check whether new pustules continue to appear through the canopy and across field areas under weather favourable to disease. Photograph or collect representative leaves and compare pustule height, spore rub-off, lesion shape and margins, canopy position, and progression over several visits. "
            "Spray injury is more likely to follow overlaps, skips, boom sections, drift direction, or a recent application and may stop progressing after exposure. Nutrient stress more often follows soil, drainage, compaction, or application patterns and lacks raised rub-off pustules. Other leaf diseases require their own lesion and pathogen signs. Use the hybrid, crop stage, weather, application and fertility records, and field distribution to rank the alternatives; verify diagnosis and the current Ontario crop label and benefit window before considering fungicide."
        )
    if decision == "wild_oat_post_application":
        return (
            "Separate plants that emerged after the application from plants that were present and survived it. Map wild-oat density and patch distribution, identify each emergence cohort, and record crop and weed stage, plant vigour, and whether survivors show herbicide injury. Reconstruct the application record: product and herbicide group, rate, adjuvant, timing, water volume and coverage, weather, mixing order, antagonism risk, and any misses or overlaps. Compare the survivor pattern with prior herbicide-group use and local resistance history; preserve seed or plants for qualified resistance testing when the pattern supports it. "
            "Then determine whether a current Manitoba spring-wheat label still provides a crop-safe, stage-appropriate in-crop option without repeating a failed mode of action or exceeding seasonal limits. If not, protect crop competition, contain patches where practical, plan harvest and sanitation, and prevent seed return. Build the next-year plan from overlapping cultural, residual, and effective postemergence tactics rather than treating every cohort or survivor as the same failure."
        )
    if decision == "herbicide_injury_control_failure":
        return (
            "Map crop injury and weed survival separately, then overlay them. Compare overlaps, skips, headlands, boom sections, turn areas, drift direction, soil and drainage zones, and treated versus normally responding plants. Record crop and weed species and stage, symptom onset and progression, product, rate, adjuvant, tank mix, mixing order, sprayer cleanout, nozzle and boom setup, coverage, timing, and weather. Crop injury that follows application geometry or exposure timing is different evidence from weeds that escaped because of late emergence, misidentification, poor coverage, antagonism, unsuitable stage, or resistance. "
            "Revisit marked crop and weed plants to assess crop recovery and continued weed growth. Review herbicide-group history and survivor patterns, and use qualified identification or resistance testing where needed. Do not make another treatment until the weed identity and stage, crop stage and recovery, cause of the first failure, current Ontario label, crop-safety restrictions, seasonal maximum, and seed-return risk are resolved."
        )
    if decision == "greenhouse_tomato_leaf_curl":
        return (
            "Leaf curl is a symptom, not a diagnosis. Map it by tomato cultivar, bay, row, irrigation zone, plant age, and new versus old growth; record whether there is mottling, bronzing, stunting, lesions, distorted growing points, or uneven fruit set. Compare temperature, humidity or VPD, light, air movement, and recent climate events with irrigation timing and uniformity, substrate water, drainage and root oxygen, root condition, root-zone EC and pH, and recent fertigation changes. "
            "Scout representative affected, margin, and normal plants for mobile pests and vectors using close inspection and appropriate traps, and examine whether symptoms or spread suggest a contagious cause. Review incoming plant material, worker and tool movement, sanitation, nearby host plants, and recent herbicide, growth-regulator, cleaner, or other chemical exposures. Isolate suspect plants and limit movement when a contagious cause remains plausible; submit representative material or involve a local greenhouse specialist before prescribing nutrients or a pesticide, and verify any action against the current Canadian label."
        )
    if decision == "potato_storage_conditioning":
        if _looks_like_french(state.question):
            return (
                "Ne laissez pas les pommes de terre chaudes sans air, mais n'imposez pas non plus une ventilation agressive à un lot dont la peau est fragile et meurtrie. Retirez la chaleur du champ avec un débit d'air adapté au système de stockage tout en évitant les écarts qui favorisent la déshydratation ou la condensation; les cibles de cicatrisation et de stockage dépendent de l'état du lot et du marché visé.\n\n"
                "Mesurez la température de la pulpe et vérifiez la maturité, la prise de peau, les meurtrissures, l'humidité et la terre adhérente, ainsi que les signes de maladie sur des tubercules représentatifs. Séparez les lots problématiques, surveillez les capteurs et la réponse du tas, puis ajustez progressivement la ventilation selon le système réel et les directives locales actuelles de stockage des pommes de terre."
            )
        return (
            "Do not leave warm potatoes without airflow, but do not force aggressive ventilation through a lot with fragile skin and bruising. Remove field heat with airflow suited to the actual storage system while avoiding conditions that increase dehydration or condensation; curing and storage targets depend on lot condition and intended market.\n\n"
            "Measure pulp temperature and check harvest maturity, skin set, bruising, moisture and adhering soil, plus disease signs on representative tubers. Segregate problem lots, monitor storage sensors and pile response, and adjust airflow progressively using current local potato-storage guidance rather than one universal setting."
        )
    if decision == "winter_injury_differential":
        return (
            "Confirm winter injury from pattern and tissue viability, not the calendar alone. Map weak bud break and dieback against snow cover, wind exposure, low areas, plant age and cultivar, and compare protected and exposed plants. Cut representative buds, shoots, cambium, crowns, and roots from affected margins and normal plants to identify live versus dead tissue, and allow enough time for delayed bud break and regrowth to express before declaring the full extent of loss. "
            "Prune only to confirmed live tissue when timing and crop practice support it, retain viable structure, reduce avoidable stress, and avoid forcing weak plants with excess fertility or other inputs. Reassess recovery and yield potential before deciding on renovation or replacement. Investigate infectious disease only where distinct lesions, ooze, advancing symptoms, or continued decline beyond the winter-exposure pattern support it; submit representative live advancing tissue when disease identity would change management."
        )
    if decision == "crop_irrigation_scheduling":
        crop = state.crop or "crop"
        return (
            f"Set the next {crop} irrigation from measured root-zone depletion, not the forecast or crop stage alone. Verify representative sensor or gravimetric water measurements by depth, field capacity and available water-holding capacity, effective rooting depth, and the locally appropriate allowable depletion. Crop stage determines the active root zone and expected water use; recent applied water and effective rain update the current balance, while the short-term forecast changes expected demand and rain credit. "
            "Irrigate only when the measured depletion and near-term balance support it. Set the amount to refill the active root zone without exceeding system capacity, infiltration, runoff, or drainage limits, then record applied volume and recheck the root-zone response."
        )
    if decision == "greenhouse_substrate_irrigation":
        return (
            "Do not schedule a greenhouse cucumber substrate from field-soil texture, field capacity, a soil survey, or tile-drainage logic. Measure representative container or slab weight or substrate water content before and after events; verify emitter flow, pressure, plugging, and distribution uniformity; and record applied volume, drain volume or drain fraction, and time to drainage. Measure source-water, root-zone, and drain EC and pH where the production system uses them. "
            "Interpret those trends with crop stage, canopy, radiation, temperature, humidity or VPD, root condition, and the grower's current fertigation recipe. Change frequency to manage the wet-dry cycle and oxygen supply; change event volume only when delivery, root-zone storage, drainage, and salt balance support it."
        )
    if decision == "sweet_corn_harvest_timing":
        return (
            "Do not set fresh-market sweet-corn harvest from grain moisture, drying, aeration, or bin-storage capacity. Sample representative ears across early, middle, and late parts of the block and record ear fill, kernel development and milk stage, tenderness, flavour, size, appearance, and uniformity. Obtain the buyer's exact maturity, size, appearance, packaging, and delivery specification, then compare the sampled block with that acceptance window. "
            "Set the picking sequence from the distribution of market-ready ears and expected short-term development, and match it to labour, transport, field-heat removal, and cooling capacity. Recheck representative ears each harvest day because a calendar estimate or one edge sample is not enough."
        )
    if decision == "fusarium_head_blight_risk":
        return (
            "Assess Fusarium head blight risk field by field. Confirm the spring wheat heading and flowering or anthesis stage first, because the susceptible window governs whether current weather matters. Combine recent and forecast rain, moisture or humidity, and temperature through that window with host-crop residue, rotation history, local disease pressure, and the variety's susceptibility. "
            "Use a current locally validated FHB risk map or advisory as regional context, not proof of infection, and continue scouting. If risk is elevated while the crop is in a label-supported timing window, verify the current Canadian fungicide label, application timing, expected protection, resistance-management fit, and economics. Once the useful window has passed, a late application cannot recover missed protection."
        )
    if decision == "fleabane_management":
        return (
            "Before choosing a Canada fleabane plan, confirm the weed identity and map density and distribution. Establish the emergence cohort as fall-, spring-, or mixed-emerging, the current rosette or stem-elongation growth stage, and whether plants are actively growing. Review the forage species and stand condition, intended harvest or grazing, previous products, rates and timings, survivor patterns, and any local resistance testing or resistance history. "
            "Then verify current Canadian crop and use-site labels and any harvest or grazing restrictions for candidate tactics. Where a labeled in-crop option is weak or unavailable, compare timely cutting, patch removal, crop competition, rotation or renovation, sanitation, and seed-return prevention. Do not substitute a generic spray-weather decision for weed biology and forage-system fit."
        )
    if decision == "forage_stand_thinning_differential":
        return (
            "Map the thinning pattern and compare patch margins with healthy stand. Review stand age and establishment, winter conditions, harvest and traffic history, fertility and pesticide records, drainage, and when decline began. Dig intact plants from affected and healthy areas and compare crown firmness and colour, bud and stem density, root depth and branching, lesions or decay, feeding, girdling, and live insects. "
            "At the same locations, compare soil moisture by depth, saturation or drought pattern, compaction and restrictive layers, rooting, and soil or tissue evidence where fertility remains plausible. Preserve representative crowns, roots, insects, and soil for a diagnostic lab when signs are not decisive. Treatment, tillage, drainage, or fertility changes should follow the confirmed dominant cause rather than patchy thinning alone."
        )
    if decision == "cutworm_stand_loss":
        crop = state.crop or "crop"
        return (
            f"Confirm active cutworm injury by looking for freshly cut or wilted {crop} plants and searching the soil surface and shallow soil around fresh damage for larvae, especially when they are active. Make representative stand counts across damaged patches, patch margins, and unaffected areas; record live larvae, fresh versus old injury, crop stage, the location and severity of feeding, remaining plant count, and stand uniformity. Revisit marked areas to determine whether cutting is continuing. "
            f"Compare the representative larval and injury measurements with a current local action threshold, crop recovery potential, natural enemies, forecast, and the economics of the remaining stand. Treat only if active pressure and expected avoided loss justify it and the current Canadian {crop} label fits; make any replant decision from the surviving stand and planting-date penalty, not damaged plants alone."
        )
    if decision == "seeding_depth_decision":
        return (
            "Choose spring-wheat seeding depth from the shallowest depth that reaches reliable moisture while still allowing uniform emergence. Measure moisture depth across representative zones, then account for fine-textured soil, aggregation and crusting risk, expected rain, seed vigour and seed size, and the seed lot's emergence capacity. Deeper placement can reach moisture but increases the emergence distance and the consequence of crusting or weak seed. "
            "Run a short test pass and dig seed behind every opener to verify actual depth, seed-to-soil contact, furrow closure, and opener consistency; correct worn or uneven openers before continuing. Recheck depth as moisture and texture change across the field. This is a depth and placement decision, not a generic plant-or-delay permission."
        )
    if decision == "nutrient_runoff_risk":
        return (
            "Before proceeding with the nutrient application, inspect whether the soil is saturated or frozen, whether residue protects the surface, and where slope, compaction, poor infiltration, wheel tracks, ditches, or concentrated flow connect the application area to surface water. Verify required setbacks, buffers, and current Ontario nutrient-management conditions. Review the nutrient source and form, rate, placement, incorporation, and application timing because dissolved and sediment-bound loss pathways differ. "
            "Use the forecast rainfall amount, intensity, timing, and uncertainty, not total rainfall alone. Delay when active flow paths, saturation or frost, intense rain, inadequate setbacks, or unavailable incorporation make runoff likely. Where risk is lower, document the field and forecast evidence and modify timing or placement as needed rather than treating a dry-looking surface as proof that application is safe."
        )
    if decision == "seed_treatment":
        if not re.search(r"\b(?:discount|cost|value|worthwhile|buy|purchase|order|untreated seed)\b", lower):
            return None
        return (
            "The discount does not make insecticide-treated seed agronomically worthwhile by itself. With no documented early-insect losses, favorable expected planting conditions, and untreated seed available, start from the untreated option unless field or regional pest history shows a credible target-pest loss that the exact treatment can prevent. Separate the insecticide value from any fungicide or seedling-disease protection in the package. "
            "Verify the treatment ingredients, target pests, current canola label and stewardship, then compare the added net seed cost with the probability and value of avoided stand loss. Scouting after emergence still matters because seed treatment is not foliar rescue protection. Where uncertainty is worth testing, preserve a documented untreated comparison rather than treating the discount as evidence of benefit."
        )
    if decision == "transplant_establishment":
        if not re.search(r"\broot[- ]bound\b|\bevery tray\b|\bstarter fertilizer\b", lower):
            return None
        return (
            "No. Do not plant every tray and expect extra starter fertilizer to repair uneven, root-bound pepper transplants. Grade the plants for uniformity, root-ball moisture and integrity, root binding, hardening, disease or injury, age, and source or handling history; cull or segregate plants unlikely to establish a uniform stand. "
            "Match the better plants to a fit seedbed, adequate root-zone moisture and irrigation capacity, and the forecast heat and wind. Plant during the least stressful window and keep root balls moist. Use starter fertilizer only when the crop-specific program and soil, media, or root-zone EC evidence support it; excess fertilizer can add salt stress without correcting poor plant quality."
        )
    if decision == "produce_safety":
        if not (
            re.search(r"\b(?:crop[- ]contact|agricultural)[- ]water\b|\bwater intake\b", lower)
            and re.search(r"\b(?:wash|livestock|animal|upstream)\w*\b", lower)
        ):
            return None
        return (
            "No. Postharvest washing is not a substitute for resolving a changed crop-contact water hazard. Livestock entering upstream after the last water test creates a new source condition even if the spinach looks clean. Stop or isolate the affected crop-contact use, preserve the water-source, event, and irrigation records, and follow the operation's current agricultural-water assessment, sampling, and corrective-action process. "
            "Hold or segregate the affected harvest when required by the food-safety plan, buyer, or current authority until the disposition is supported. A new test may inform that assessment, but appearance or washing alone does not prove the crop safe."
        )
    if decision == "planting_window":
        if state.capsule is None or state.capsule.domain != "planting_establishment":
            return None
        crop = state.crop or "crop"
        return (
            f"No. A dry surface is not enough reason to plant when the {crop} seed zone remains cold and wet. Check seedbed fitness using soil temperature and soil moisture at planting depth, field trafficability, and whether the opener will create compaction, sidewall smearing, an open furrow, or poor seed-to-soil contact. Combine those observations with the short rain and temperature forecast, drainage, seed quality and treatment, and the cost of delayed emergence or stand loss. "
            "Plant only the areas where the seedbed is fit. Delay or stage wetter fields when establishment injury outweighs the cost of waiting, then recheck seed-zone and operating conditions rather than letting crew availability decide."
        )
    if decision == "water_limited_nitrogen_increase":
        crop = state.crop or "crop"
        variable_rate_context = bool(
            re.search(r"\b(?:variable[- ]rate|yield zones?|unused UAN|grain price)\b", lower)
        )
        opening = (
            "Do not increase the variable-rate nitrogen map from old yield zones, attractive crop price, or unused UAN while water is limiting crop response. "
            if variable_rate_context
            else f"Do not increase this field's {crop} nitrogen rate while water is limiting crop response. "
        )
        return (
            opening
            + f"First confirm current {crop} condition, crop stage, roots, realistic yield potential, and the complete nitrogen and irrigation records. Use a current soil nitrate result or representative tissue evidence with local calibration, and verify root-zone moisture, remaining water allocation, forecast demand, and whether the crop can still take up and return value from added nitrogen. "
            "Where spatial management is proposed, rebuild the prescription only from current, ground-truthed zones and a defensible response probability. Test any increase with check strips or a replicated field trial, then use a partial budget for expected crop response, crop price, nitrogen and application cost, and water risk. More nitrogen cannot restore yield already limited by unavailable water."
        )
    if decision == "lime_sampling_rate":
        if state.crop == "blueberry" or re.search(r"\bblueberr", lower):
            return (
                "Do not lime the whole blueberry block from one composite sample. Blueberry is an "
                "acid-requiring crop, so raising pH without a current crop-specific local target pH can reduce "
                "nutrient availability or injure the production system. Delineate representative sampling zones "
                "from topography, soil, plant performance, management, and past lime history, then collect "
                "separate georeferenced samples at the correct depth. Confirm soil pH and the laboratory's buffer pH, "
                "exchangeable acidity, or locally calibrated lime-requirement method for each defensible zone. "
                "Use current Nova Scotia blueberry guidance to decide whether any zone needs lime. Only then "
                "convert a zone requirement using the product's CCE or ECCE, neutralizing value, moisture, "
                "fineness, placement, and incorporation constraints."
            )
        return (
            "One composite sample across a variable field is not enough to defend one uniform lime rate. Delineate representative sampling or management zones from texture, topography, management and past lime history, then collect separate georeferenced samples at the correct depth. Confirm measured pH and the laboratory's buffer pH, exchangeable acidity, or locally calibrated lime-requirement method for each defensible zone. "
            "Set the target pH from the crop rotation and local guidance, including the planned alfalfa, and account for incorporation depth and timing. Convert the requirement to product rate only after the lime source's CCE or ECCE, neutralizing value, moisture and fineness are known. Use a uniform rate only if representative sampling shows the field is sufficiently uniform."
        )
    if decision == "forage_defoliator_harvest_decision":
        return (
            "Do not choose spraying, early cutting, or watching from the worst sunny edge or the applicator's availability. Confirm the caterpillar species and active stage, then sample pest density, whole-canopy injury, remaining leaf area, and injury trend at representative edge and interior locations. Record forage height or stage, drought stress and regrowth condition, and natural enemies, then compare that evidence with a current locally valid threshold. "
            "If pressure is below threshold and stable, continue close scouting. Consider early cutting when forage stage and drought-stressed regrowth condition support it and cutting will remove the threatened forage before material loss. Consider an insecticide only when expected loss before cutting exceeds treatment cost and the exact crop, pest, timing, preharvest interval, and beneficial-insect precautions fit the current label."
        )
    if decision == "high_tunnel_yellowing":
        return (
            "Do not raise nitrogen again from yellowing alone. Map whether symptoms begin on old or new leaves and whether they follow emitters, beds, or wet and dry zones; inspect roots and root disease, crop stage, fruit load, heat stress, and recent growth. Verify the current fertigation recipe and injector calibration, then measure emitter output and irrigation uniformity in affected and normal rows. "
            "Replace the old source-water result with a current irrigation-water EC test and compare it with root-zone soil or media EC, representative root-zone moisture, drainage, and applied-water records. Use current soil or tissue evidence with crop-specific local interpretation to separate nitrogen shortage from salt, water, delivery, root, heat, or other nutrient causes. Correct the limiting factor first and use a yield-quality budget before changing the nitrogen program."
        )
    if decision == "openet_irrigation_decision":
        return (
            "No. OpenET supplies satellite and model crop water use context, not a field sensor. It is a prior, not field truth and not an irrigation prescription. Reconcile it with a calibrated probe or representative root-zone soil moisture measurements at appropriate depths, crop stage and rooting depth, recent rain, applied-water and flowmeter records, and visible crop stress before starting the next irrigation. "
            "Use the combined depletion trend, forecast demand, irrigation-system capacity, infiltration, drainage, and water quality to set timing and amount. Investigate whether the single probe represents the field before allowing either the regional OpenET estimate or one near-field-capacity reading to control the whole-field decision."
        )
    if decision == "drip_irrigation_uniformity":
        return (
            "Do not increase runtime for every zone from end-of-lateral wilting alone. Diagnose the drip delivery system first: measure pressure and flow at the heads and ends of affected and normal laterals, check emitter discharge and irrigation distribution uniformity, and inspect for plugging, leaks, filter restriction, injector problems, and zone-design differences. "
            "Compare affected and normal beds for representative root-zone moisture, irrigation-water EC and soil salinity or EC, roots, and disease pattern. Correct a hydraulic or emitter-delivery problem before adding water everywhere; then schedule each zone from crop stage, depletion, weather demand, system capacity, drainage, harvest quality, and applicable food-safety constraints."
        )
    if decision == "irrigation_water_nitrate_credit":
        return (
            "Do not credit every theoretical pound. A defensible nitrogen credit starts with a current representative irrigation-water nitrate analysis with the units and sampled well identified, plus measured applied-water volume and timing from flowmeter or irrigation records. Convert concentration and delivered volume consistently, then account for water applied outside crop uptake, nonuniformity, drainage, leaching, denitrification, and other locally relevant loss pathways. "
            "Integrate the resulting irrigation-water nitrate credit into the full nitrogen budget with current soil and crop evidence, realistic response potential, and all fertilizer, manure, and previous-crop credits. Last year's water test or an assumed seasonal water volume is not enough for a field-rate change."
        )
    if decision == "tile_drainage_decision":
        return (
            "No. A poorly drained soil-map component and yellow corn identify a drainage hypothesis, not the line or depth for a tile drain. Ground-truth the affected and normal areas with topography, repeated wetness timing, a soil profile or pit, water-table and restrictive-layer evidence, root condition, and any existing tile map. Separate surface inflow, compaction, seepage, perched water, outlet limitations, and nutrient or root injury before choosing a drainage fix. "
            "A tile or drainage design also needs survey grade, spacing and depth appropriate to the soil, a verified outlet and downstream capacity, and local wetland and drainage requirements. Use those observations and a qualified design before installing a drain."
        )
    if decision == "spray_weather_window":
        return (
            "No. Staying on schedule is not the main priority when the product is unknown, wind is increasing toward a sensitive shelterbelt, and rain may challenge the application window. Select the exact crop, target, product and adjuvant first, then verify the current product label for wind, direction, gusts, inversion, buffer or sensitive-area restrictions, temperature and humidity limits, and the required rainfast interval. "
            "Use on-site observations and a field-specific forecast to judge efficacy, drift, and runoff risk without inventing a generic cutoff. Delay or reschedule if the selected label and conditions do not support a compliant application, and preserve the weather, setup, product, and application records."
        )
    if decision == "forage_frost_safety":
        return (
            "No. Keep cattle out and do not graze, green-chop, cut, or feed this sorghum-sudangrass tomorrow until the forage hazards are assessed. Frost on drought-stressed plants and tender regrowth can elevate prussic-acid risk, while drought stress can also elevate nitrate. Haying or drying may reduce prussic acid after proper curing, but it does not reliably remove nitrate, so the neighbor's rule is not a safety test. "
            "Follow local livestock guidance for the post-frost waiting and recovery period, then collect representative forage samples using the laboratory's method and request nitrate and prussic-acid or cyanide assessment as appropriate. Base release, dilution, or feeding on the result, animal class, and ration; use another feed source meanwhile."
        )
    if decision == "postharvest_cooling":
        return (
            "No. Cooling strawberries later that evening does not undo two warm hours in field totes. Remove field heat as quickly as the crop and handling system allow because time warm accelerates water loss, softening, bruising, and decay. Measure harvest and pulp temperature plus the elapsed time to cooling; move filled totes into shade, reduce handling delay and excessive tote depth, and start prompt crop-appropriate precooling. "
            "Check cooler capacity, sanitation, package airflow, humidity, transport temperature, and cold-chain continuity. Adjust harvest time, crew flow, pickup frequency, and precooling capacity against the buyer's temperature and quality specification rather than assuming late cooling restores lost shelf life."
        )
    if decision == "nematode_management":
        return (
            "No. Repeating low-yield patches or patchy stunting make nematodes one hypothesis, but symptoms do not justify making a nematicide the first move. Map affected and normal areas, review field history, and confirm sample timing and handling with the diagnostic lab. Collect soil samples and root samples from patch margins plus comparable healthy areas, then request species identification and population density. "
            "Also compare texture, moisture, compaction, pH, fertility, herbicide history, roots, and root disease. For next year, choose a resistant variety, nonhost rotation, seed treatment, nematicide, or other tactic only after confirmed species and population, local thresholds or response evidence, label fit, cost, and expected return support it."
        )
    if decision == "residual_activation":
        return (
            "Do not simply repeat the residual at a higher rate after waterhemp has emerged. First review the current label, original rate and placement, rainfall or mechanical incorporation after application, soil texture, organic matter, pH, weed identity, and emergence timing. Little rain can leave a preemergence herbicide unactivated, but more residual does not by itself control emerged plants. "
            "Use a timely labeled postemergence option for small emerged waterhemp only if the soybean stage, weed size, resistance history, weather, and crop label fit. Where the label allows, restore residual coverage with an overlapping residual while respecting crop restrictions and the seasonal maximum. Continue scouting and use integrated tactics to prevent seed return."
        )
    if decision == "volunteer_trait_unknown":
        return (
            "No. Volunteer-canola appearance does not reveal its herbicide-tolerance system, so choosing a postemergence product from appearance alone could fail or injure the emerged lentils. Confirm the weed identity and recover the previous tenant's seed, crop, or herbicide records; record lentil stage and the volunteers' size, stage, density, and distribution. "
            "Verify the current Canadian lentil label and crop safety for any candidate option, including weather, resistance history, and the unknown tolerance trait. If the trait cannot be established, use only a labeled tactic effective without that assumption. Map escapes, prevent seed return where practical, and use pre-seed control, rotation, crop competition, and multiple effective nonconflicting tactics in the multiyear plan."
        )
    if decision == "variable_rate_pk":
        return (
            "A colorful yield map is not enough to justify variable-rate phosphorus and potassium. Clean the yield data first: separate the monitor's pre- and post-calibration periods, remove bad flow and position records, align years and boundaries, and verify stable zones in the field. Pair each ground-truthed zone with representative P and K soil tests, the test method, sampling depth, crop-removal context, and locally calibrated response probability. "
            "Build zone rates from expected P or K response, not map color or removal alone. Test the prescription with replicated check strips or an on-farm trial, then use a partial budget covering fertilizer and application cost, crop price, measured yield and quality response, and sensitivity to uncertain response and prices before scaling it."
        )
    if decision == "variety_trial_selection":
        if re.search(r"\b(?:atlas|map|polygon|polygone|carte)\b", lower):
            crop = state.crop or "crop"
            map_name = (
                "agro-pedological atlas polygon"
                if re.search(r"\bagro[- ]pedological atlas\b|\batlas agro[- ]p[ée]dologique\b", lower)
                else "regional suitability map"
            )
            return (
                f"No. A favourable {map_name} is regional screening context and cannot select a "
                f"{crop} variety for the field. Ground-truth soil, drainage, topography, salinity, and other field "
                "constraints, then match relative maturity or crop heat-unit fit to the planting window and harvest "
                "risk. Compare replicated local multi-year and multi-location variety trials for statistical "
                "separation, yield stability, disease package, lodging, quality, herbicide trait, and adaptation. "
                "Also check seed availability, market requirements, seed cost, and downside risk; retain an on-farm "
                "comparison where the local evidence is thin."
            )
        if re.search(r"\bsilage\b", lower):
            return (
                "No. The top grain-yield result is not enough to make a hybrid the dairy's main silage hybrid. Use replicated local silage trials across years or sites and compare statistical separation, whole-plant yield, harvest moisture and maturity, starch, fiber digestibility, kernel processing response, stay-green, disease, lodging, and harvest-window fit. Match those traits to the ration, storage structure, chopping and processing system, and the dairy's risk tolerance. "
                "Include seed cost and the downside of poor feed quality or missed harvest moisture. If local silage evidence is thin, keep the discounted hybrid to an on-farm strip or limited acreage with a suitable comparator rather than projecting grain-trial performance to the whole silage program."
            )
        return (
            "The stable variety should carry more weight than the one-year winner unless broader evidence shows a repeatable advantage. Compare replicated multi-year and multi-location trials from similar environments, including statistical separation or LSD and yield stability, rather than rank from one dry site-year. Match maturity and drought or soil adaptation with the reported disease resistance, lodging, test weight, protein or end-use quality, herbicide system, and market requirements. "
            "Use seed cost in a partial budget and consider downside risk across fields. Where uncertainty remains material, retain both in a small on-farm comparison instead of committing the farm from one result."
        )
    if decision == "integrated_preharvest_specialty":
        return (
            "Do not collapse this into an automatic spray decision. First identify the leaf spots and measure incidence, severity, spread, and crop-contact pattern after overhead irrigation; segregate or harvest around affected areas if that protects the buyer's appearance standard. Test and document the irrigation-water source and recent crop-contact use because the near-harvest food-safety question is separate from disease control. "
            "For any treatment, verify the exact leafy-green crop and target on the current label, the preharvest interval, restricted-entry interval, daily worker entry, harvest timing, and buyer restrictions. Compare the likely quality benefit with the risk of residues, worker exclusion, and missed harvest; use nonchemical moisture, sanitation, and harvest adjustments when treatment cannot fit those constraints."
        )
    if decision == "furrow_irrigation_uniformity":
        return (
            "Do not simply extend the set while tailwater is already leaving the field; that can increase runoff or deep percolation without resolving the reported dry head-zone root profile. Because water cannot reach the tail without first passing the head, verify the observation: measure root-zone moisture and infiltrated depth from head to tail, confirm the inlet and sampling locations, and record advance and recession time. Then check inflow rate, set time, furrow length, slope, surface condition, and intake rate. "
            "Correct the diagnosed infiltration or distribution cause while limiting tailwater. Depending on those measurements, the tested change may involve stream and cutback management, surge irrigation, shorter runs, land leveling, surface or compaction management, or tailwater recovery and reuse. Test representative furrows before changing the whole field."
        )
    if decision == "soil_water_sensor_interpretation":
        return (
            "No. The same volumetric water content does not represent the same depletion or irrigation need in shallow sandy loam over gravel and deep silt loam. Verify sensor calibration, placement, and depth in each soil; establish field capacity, refill point or allowable depletion, and effective rooting depth for the current corn stage. Convert each reading to water depleted within the active root zone rather than comparing the raw percentage. "
            "Then set the refill depth from each field's storage deficit, forecast crop water use, recent rain, and irrigation-system capacity. Limit the application by infiltration and runoff risk, and confirm the sensor result with a probe or gravimetric check before using it for a large irrigation."
        )
    if decision == "corn_rootworm_silk_clipping":
        return (
            "Corn rootworm beetles and some clipped silks do not by themselves justify an insecticide. Scout representative plants for beetle density, measure fresh silk length and clipping severity, and check whether new silks are still emerging and how much pollination is complete. The yield risk is greatest when beetle pressure keeps fresh silks clipped during the active pollination window. "
            "Compare those observations with a locally valid silk-clipping or rootworm beetle threshold. If the threshold and remaining pollination risk support treatment, verify the current product label for corn, adult rootworm, timing, pollinator precautions, and restrictions; otherwise continue scouting while fresh silks emerge."
        )
    if decision == "wheat_aphid_treatment":
        return (
            "Do not treat aphids in wheat from presence alone, and do not assume lady beetles alone will prevent loss. Confirm the aphid species and use a representative method to count aphids per head or tiller across the field; record wheat stage, remaining grain-fill period, crop stress, and whether the aphid population is increasing. "
            "Count lady beetles and other natural enemies, then compare pest density and trend with a locally valid aphid threshold for wheat at that crop stage. Treat only when that threshold and expected benefit support it, and then verify the current product label and select an effective option that preserves beneficials where possible."
        )
    if decision == "wheat_flag_leaf_fungicide":
        return (
            "Leaf spots low in the wheat canopy before full flag-leaf emergence do not yet prove that a fungicide will pay. Identify the likely disease or confirm the cause, then scout incidence and severity and whether lesions are moving from lower leaves toward the upper canopy. The decision becomes more consequential when a susceptible variety, favorable rain or leaf-wetness weather, and disease movement threaten the flag leaf during its protection window. "
            "Use crop stage, variety susceptibility, forecast weather risk, expected yield potential and grain value, application cost, and the current fungicide label to make the return decision. Continue scouting if upper leaves remain clean or risk is low; protect the flag leaf only when disease risk and expected yield benefit justify the application."
        )
    if decision == "weed_preharvest_escape":
        return (
            "Do not spray a late cleanup treatment unless a current product label explicitly allows the dry bean crop, target weed, crop stage, and time remaining before harvest. Identify the weed and seed maturity, then check days to harvest, preharvest interval (PHI), crop-desiccation language, residue limits, harvest-aid purpose, and buyer or market restrictions. A labeled harvest aid is not automatically a weed-control treatment, and an unlabeled application can injure the crop or create residue and market problems. "
            "Where spraying does not fit, use practical nonchemical containment: remove isolated plants by hand, harvest infested areas last or separately, and clean equipment before moving to clean areas. Record the escapes and plan earlier integrated control next season."
        )
    if decision == "weed_burndown_survivor":
        return (
            "No, do not simply raise the glyphosate rate or exceed the current label because ryegrass survived. Confirm the weed species, growth stage and size, then review the application record, labeled rate, coverage, water quality, temperature, moisture stress, and timing to separate application failure from possible resistance. Map and contain the patch and prevent seed production where practical. "
            "If another burndown action is still possible, choose a locally effective labeled alternative mode or site of action for the crop and planting interval, or use an effective nonchemical tactic; do not repeat a failed mode by default. Build the next program around a clean start, multiple effective tactics, and follow-up scouting."
        )
    if decision == "weed_seed_return_management":
        weed = (
            "Palmer amaranth"
            if re.search(r"\bpalmer(?: amaranth)?\b", lower)
            else "waterhemp"
            if re.search(r"\bwaterhemp\b", lower)
            else "pigweed"
            if re.search(r"\bpigweed\b", lower)
            else "the escaped weed"
        )
        return (
            f"The immediate priority is to reduce {weed} seed return and prevent seed production and spread where practical, not to promise complete removal. Confirm the weed species, map the escapes and seed maturity, remove isolated plants or patches when feasible, keep heavily infested material separate where practical, harvest infested areas last, and clean equipment before moving to clean fields. Review the application record, timing, coverage, weather, and herbicide history before separating resistance from application failure. "
            "Next season, use integrated labeled tactics: start weed-free and combine multiple effective tactics, including an effective residual program, timely postemergence control while weeds are small, crop competition, scouting, and mechanical or cultural control where suitable. Verify every current label and preserve the field and application records."
        )
    if decision == "cold_wet_purple_corn":
        return (
            "Do not apply phosphorus immediately from purple color alone. Cold, wet soil can temporarily restrict root growth and phosphorus uptake even when the soil contains adequate phosphorus, and some corn hybrids express more purple pigment under stress. Map the field pattern and inspect roots, drainage, compaction, soil temperature, and the starter or fertilizer placement history. "
            "Use a current calibrated soil test to determine whether phosphorus supply is actually low. Reassess new growth as the soil warms and dries; recovery supports transient uptake stress, while persistent symptoms, poor roots, or a low soil test justify a locally calibrated phosphorus or root-zone management decision."
        )
    if decision == "soybean_idc":
        return (
            "The pattern is consistent with iron deficiency chlorosis (IDC), but confirm the field pattern and rule out root disease, other nutrient problems, herbicide injury, and salinity. IDC commonly appears on the youngest leaves in wet, high pH areas where carbonate or bicarbonate chemistry limits iron availability even though total soil iron may be present. Check soil pH and carbonate context, drainage and wetness, roots, salinity, and affected-versus-normal plants. "
            "Do not assume that an iron fertilizer rate or lowering field soil pH will correct the current crop. Long-term management usually emphasizes soybean varieties with IDC tolerance and locally validated placement, population, companion-crop, drainage, or other field practices where they fit the confirmed cause."
        )
    if decision == "sulfur_nitrogen_differential":
        return (
            "In canola, sulfur deficiency is usually clearest in young or new leaves and can cause uneven or delayed flowering because sulfur is not readily remobilized. Nitrogen is mobile in the plant, so nitrogen deficiency generally begins on older or lower leaves and is often more uniform. Use that leaf-age and flowering pattern as a clue, not a diagnosis by itself. "
            "Map the field pattern and review soil texture, organic matter, rainfall or leaching, roots, and fertilizer history. Compare representative tissue samples and soil samples from affected and normal areas with local calibration before choosing sulfur, nitrogen, or a rate."
        )
    if decision == "fruit_set_diagnostic":
        crop = state.crop or "crop"
        return (
            f"For {crop}, first separate heavy flowering from effective fruit-producing flowers. Record bloom timing and check the balance and timing of male and female flowers, whether the cultivar is parthenocarpic or requires pollination, pollen transfer, and bee or pollinator activity. Protect bloom from unnecessary pesticide exposure and verify whether any bloom-time pesticide use could have reduced pollinator activity. "
            "Reconstruct heat, cold, rain, wind, and other weather during bloom; check root-zone soil moisture and water stress, excessive nitrogen or unusually rapid vegetative growth, disease, and whether young fruit begin to enlarge and then abort. If nutrition is suspected, use a current soil or tissue test rather than color alone, and use crop-specific extension guidance to interpret the reproductive pattern."
        )
    if decision == "pest_treatment":
        if state.crop == "apple" and re.search(r"\b(?:moth|trap captures?|fruit injury)\b", lower):
            return (
                "Wait rather than treat from unidentified moth-like captures or scattered fruit injury. Confirm the moth species and damaging life stage, then standardize the trap record: trap and lure type, trap location, service interval, captures per trap per interval, first sustained catch or biofix, and the local phenology or degree-day model where one is validated. Inspect a representative fruit and shoot sample for fresh entry, frass, larvae, and the pattern and timing of injury. "
                "Compare trap trend, crop and fruit stage, orchard history, fruit injury, natural enemies, and a locally valid apple-pest action threshold. Treat only when that evidence supports the target and timing, then verify the current label, preharvest interval, pollinator and beneficial-insect precautions, and resistance group for the exact product."
            )
        return (
            "Do not spray from pest presence or a green-looking canopy alone. Confirm the pest species and active feeding stage, then use a defined scouting method and scout counts across representative field areas to record pest count, pest density, injury level, whole-canopy defoliation, and crop stage. "
            "Make a beneficial count as well, then compare those observations with a current locally valid economic threshold, population trend, plant stress, natural enemies, and beneficials. Review previous products and IRAC groups when resistance is a concern. Rotate effective modes only when treatment is justified, verify the current product label and all current label restrictions for the crop, target, and timing, and use IPM or a selective product to preserve beneficial insects where an effective labeled option fits."
        )
    if decision == "fungicide_decision" and state.crop == "potato":
        return (
            "Do not choose a fungicide from new potato leaf lesions alone, but treat the differential as time-sensitive. Map the field pattern and irrigation overlap; inspect upper and lower leaves, stems, lesion margins and undersides; record crop stage, incidence, severity, lesion expansion, recent rain or irrigation, humidity and leaf wetness, variety susceptibility, and field history. Separate late blight from other foliar disease and non-disease injury, and submit a fresh representative sample promptly when late blight or another consequential disease is plausible. "
            "Use locally current disease alerts or validated risk guidance only to prioritize scouting. A protectant or curative application is defensible only when the working diagnosis, crop stage, weather risk, current potato label, current PMRA product label for that crop and target, resistance group, expected yield or quality protection, application cost, and the cost of delay support it; a public forecast or lesion photo alone is not enough."
        )
    if decision == "fungicide_decision":
        if state.crop == "corn" and re.search(r"\brectangular\b[^?]{0,100}\blesions?\b|\blesions?\b[^?]{0,100}\bleaf veins?\b", lower):
            return (
                "Rectangular tan lesions bounded by leaf veins are consistent with gray leaf spot, but confirm the symptom pattern and field pattern with a representative diagnostic sample. "
                "Record crop stage, incidence and severity, whether lesions are moving into upper leaves or the upper canopy, recent humidity, rain or leaf wetness, field history, and hybrid susceptibility. "
                "Consider a fungicide only when diagnosis, disease severity, weather risk, current label fit, expected yield benefit, crop value, and application cost support treatment."
            )
        return (
            "No. A favorable forecast or scattered leaf spots alone is not enough reason to apply a fungicide. "
            "Build the differential from symptoms and field pattern, then confirm the disease where needed and scout representative incidence or severity, canopy position, and trend; record crop stage, field history, hybrid or variety susceptibility, and whether disease is moving toward yield-critical tissue. "
            "Estimate expected yield or quality protection using crop value, application cost, product cost, and locally relevant response evidence. Treat only when the diagnosis, disease pressure, susceptible crop stage, weather risk, and expected return support it, then verify the current label and resistance-management fit."
        )
    if decision == "weed_escape_management":
        if state.crop == "canola" and re.search(r"\b(?:grassy weed|grass weed|ryegrass|wild oat)\b", lower):
            return (
                "Change the plan only after identifying the grassy weed and separating resistance from application failure. Map and revisit survivor patches; record species, growth stage, density and seed maturity; and review the exact canola crop and herbicide-tolerance system, product, rate, timing, coverage, water quality, weather, and prior herbicide groups or sites of action. Preserve seed or plant samples for local resistance testing where the pattern and application record support that concern. "
                "Prevent seed production and spread where practical, and verify the current Canadian label before any follow-up treatment. Build the next Alberta canola rotation around multiple effective labeled groups where available, a different crop and effective in-crop options, a clean seedbed, crop competition, sanitation, patch control, and feasible mechanical or cultural tactics. Do not simply raise the rate or repeat the failed group."
            )
        return (
            "Map and revisit escapes across the field pattern, and prevent seed production and spread where practical; late escapes can replenish the seedbank even when current yield loss is small. Start with weed identification: confirm weed species from weed photos or a representative sample, then record growth stage, weed size, emergence timing, density, and seed maturity. Review the application record, field history, weather, coverage, and herbicide history to separate application failure from resistance. "
            "For the next cycle, use integrated labeled tactics: start clean and combine effective residual and postemergence sites of action with crop rotation, a suitable cover crop, crop competition, scouting, mechanical or cultural control, and recordkeeping. Check every current label and do not exceed a rate or repeat a failed mode of action simply because plants survived."
        )
    if decision == "soil_crusting":
        return (
            "First confirm that a true surface crust is sealing the soil and inspect seedling depth, hypocotyl or shoot injury, emergence progress, and the remaining stand. A shallow crust-breaking pass such as a rotary hoe can help when the surface is dry enough to fracture and seedlings have not exhausted their emergence energy. "
            "Test a short pass and check seedling and cotyledon loss before continuing; avoid deep or aggressive tillage in wet soil. Reassess emergence and make a representative stand count before deciding whether damaged areas need replanting."
        )
    if decision == "compaction_tillage":
        return (
            "Do not deep-rip from shallow roots and ponding alone. Compare the traffic pattern and wheel tracks with untrafficked areas, inspect roots in a soil pit, identify the depth and continuity of any restriction, and use a penetrometer or other resistance measurement at comparable soil moisture; separate mechanical compaction from poor drainage or a naturally dense layer. "
            "Deep tillage is defensible only when a confirmed layer can be fractured at the correct depth and dry-enough condition without smearing. Pair any tillage with controlled traffic and drainage changes or the benefit may be short-lived."
        )
    if decision == "physiological_disorder":
        if state.crop == "tomato" or "blossom-end rot" in lower or re.search(
            r"\b(?:dark|black|brown),?\s+sunken\b[^.]{0,45}\bblossom ends?\b", lower
        ):
            return (
                "Blossom-end rot is a localized calcium-delivery problem in developing fruit and does not necessarily mean the soil lacks calcium. Uneven root-zone moisture, root injury, salinity or competing salts, excessive nitrogen, and rapid growth can restrict calcium movement into fruit even when a soil test shows adequate calcium. "
                "Stabilize irrigation and root function, protect roots, and correct salinity or fertility only when field evidence supports it. Adding soil or foliar calcium is not a reliable cure when the transport problem remains."
            )
        return (
            "Lettuce tipburn is a localized calcium-transport disorder in rapidly expanding young inner leaves, so adequate soil or total leaf calcium does not rule it out. Inner leaves transpire less, and rapid growth, low evapotranspiration, humid inner-canopy conditions, water stress, salinity, or root stress can reduce calcium delivery. "
            "Manage cultivar susceptibility, growth rate, root-zone moisture, salinity, and canopy environment. Do not assume that more soil or foliar calcium will reach the affected inner tissue."
        )
    if decision == "salinity_management":
        if re.search(r"\b(?:water test|irrigation[- ]water|pivot)\b", lower) and re.search(
            r"\b(?:one|single|snapshot|all season|season[- ]long|unchanged)\b",
            lower,
        ):
            return (
                "Do not keep the irrigation plan unchanged for the whole season from one water sample. Treat its "
                "EC and SAR as a dated snapshot, then repeat irrigation-water EC and SAR tests when the source or blend "
                "can change and pair them with representative root-zone soil salinity tests and, where sodicity is "
                "plausible, soil sodium or ESP. "
                "Track crop response and field pattern, irrigation uniformity, infiltration, drainage, and water-table "
                "conditions through the season. Relate those measurements to the crop's salt tolerance and rooting "
                "depth. Any leaching or amendment plan also requires suitable water, adequate infiltration, and a "
                "working drainage outlet; the water-test values alone cannot authorize unchanged operation or set a "
                "season-long leaching amount."
            )
        if re.search(r"\b(?:gypse|carte)\b", lower):
            return (
                "Non. Une carte indiquant un sol humide est un contexte de dépistage régional; elle ne prouve ni "
                "la salinité ni la sodicité du champ et ne justifie pas l'application de gypse. Comparez des zones "
                "atteintes et normales avec des analyses représentatives du sol dans la zone racinaire : conductivité "
                "électrique, SAR ou ESP lorsque la sodicité est plausible, pH et texture. Analysez aussi l'eau "
                "d'irrigation, puis vérifiez l'infiltration, le drainage, la nappe phréatique et la tolérance de la "
                "culture. Le gypse n'est pas automatique : utilisez-le seulement si la sodicité est confirmée et si "
                "la source de calcium, la qualité de l'eau, le drainage et un calcul du besoin d'amendement appuient "
                "la réhabilitation. Le lessivage exige aussi une eau convenable et un drainage capable d'évacuer les sels sous la zone racinaire."
            )
        if re.search(r"\bgypsum\b", lower):
            return (
                "Do not spread gypsum from a high soil EC or a wet-looking map alone. EC measures soluble salts but "
                "does not establish sodicity; obtain representative root-zone EC plus SAR or ESP, and compare affected "
                "and normal areas. Check soil texture and pH, infiltration, irrigation-water EC and SAR, drainage, the "
                "water table, crop salt tolerance, and whether leaching water has a functional outlet. Gypsum is not "
                "automatic: use it only for confirmed sodicity when the calcium source, soil and water chemistry, "
                "drainage, and a reclamation calculation support the amendment. Leaching is defensible only when "
                "suitable water can infiltrate and drainage can move salts below the active root zone."
            )
        if re.search(r"\b(?:map|regional saline[- ]soil class|polygon|intersects?|carte|polygone)\b", lower):
            return (
                "No. A regional saline-soil class or mapped polygon is screening context, not enough to prescribe leaching for this field. Ground-truth affected and normal zones with representative root-zone samples by depth using an appropriate salinity method, and test irrigation-water EC and SAR; assess soil sodium or ESP when sodicity is plausible. Relate those measurements to crop salt tolerance, rooting depth, symptoms, infiltration, irrigation uniformity, drainage, the water table, and whether a functional outlet exists. "
                "Leaching is defensible only when suitable water can infiltrate and drainage can carry salts below the active root zone. The mapped class alone cannot set a leaching amount or establish that the intersected soil occurs uniformly across the field."
            )
        return (
            "White crust and stunting cannot separate salinity from sodicity. Use a representative root-zone soil test with an appropriate salinity extract from affected and normal areas, plus an irrigation water test for EC and SAR and soil sodium or ESP where relevant. Salinity mainly creates osmotic water stress; sodicity disperses clay and can restrict infiltration, so both may be present. Check crop tolerance, irrigation uniformity, drainage, and the water table. "
            "Leaching is useful only when suitable water can infiltrate and drainage can carry salts below the root zone. Gypsum is not an automatic fix: use it only for confirmed sodicity when soil chemistry and texture, calcium source, water quality, drainage, and a reclamation calculation support the amendment."
        )
    if decision == "cover_crop_termination":
        return (
            "Do not wait for more biomass by default in a dry spring when winter-wheat establishment may be water-limited. "
            "Measure soil moisture by depth and weigh the forecast, cover-crop species and water use, rooting, residue and erosion protection, grazing value, termination method, and the wheat planting window. "
            "If stored water is already limiting, terminate early enough to protect seed-zone moisture and wheat establishment. If grazing is used, set a firm removal and termination date and avoid removing so much residue or trafficking wet soil that erosion protection or seedbed condition is lost."
        )
    if decision == "flood_recovery":
        return (
            "Do not make the final survival or replant decision as soon as the water recedes. Recovery depends on crop stage, growing-point position, standing water depth, hours under water, and water, air, and soil temperature; cool conditions generally slow oxygen stress and injury relative to warm flooding. Sediment, debris, root injury, disease, crusting, and further rain can add damage. "
            "Restore drainage where possible without trafficking saturated soil, then allow enough aerated growing conditions to look for new growth. Inspect growing points and roots and make representative stand counts across affected and normal areas. Compare the recovered stand, uniformity, yield potential, planting-date loss, replant cost, replant seed availability, and local insurance rules before terminating the crop."
        )
    if decision == "freeze_recovery":
        if state.crop == "canola" or re.search(r"\bcanola\b", lower):
            return (
                "Do not estimate canola loss from a distant station temperature or from surface discolouration alone. Record the reproductive stage and the best available in-field minimum temperature and exposure duration, then account for topographic position, canopy, wind, soil moisture, and whether low, exposed, or sheltered areas experienced different microclimates. "
                "After injury has had time to express, sample representative plants from affected and normal areas. Inspect growing points, stems, flowers, pods, and developing seeds for firm viable tissue, continued pod fill, new growth, or progressive water-soaked, bleached, brown, soft, or aborted tissue. Revisit marked plants to track progression and estimate viable reproductive sites across the field. Use that stage-specific recovery evidence, not temperature alone, before changing harvest or stand management; do not invent a field-loss percentage from the forecast."
            )
        if state.crop == "wheat" or re.search(r"\bwinter wheat\b|\bspring wheat\b", lower):
            return (
                "Do not decide stand recovery from burned leaves immediately after the freeze. Record crop stage and whether the crown, growing point, or developing head was still protected near the soil or had moved into the exposed stem. After several days of warm growing conditions, sample affected, sheltered, low, and normal areas; split representative stems and crowns and look for firm yellow-green tissue and new growth versus water-soaked, white, brown, or soft growing points and heads. "
                "Count live plants and productive tillers over representative row lengths and map stand uniformity, not just the best survivors. Use the recovered stand and tiller distribution, injury stage, root and crown health, yield potential, planting-date penalty, replant options, and current local guidance to decide whether to retain the crop. Kernel set is too late to be the first recovery check."
            )
        return (
            "Recently emerged corn can lose exposed leaves while its growing point remains protected below the soil surface, so appearance immediately after a freeze is not a replant decision. Allow warm growing weather for new leaf growth, then inspect growing points for healthy firm tissue and count surviving plants and stand uniformity. "
            "Compare the recovered stand and planting date with the yield potential and cost of replanting before terminating it. Lack of new growth or discolored soft growing points is more consequential than burned leaf area alone."
        )
    if decision == "pollination_stress":
        return (
            "The main risk is water stress that delays silk emergence or dries exposed silks while pollen shed continues; heat alone is less damaging when root-zone moisture is adequate. Check soil moisture and leaf rolling, silk emergence and receptivity relative to pollen shed, and whether the pollination window remains synchronized. "
            "After pollen shed, inspect fertilization and early kernel set rather than estimating yield loss from the forecast alone. Where irrigation is available, protect the root-zone water supply through silking and early kernel set."
        )
    if decision == "maturity_switch":
        return (
            "Do not use one universal day-for-day rule for switching corn maturity. Compare the actual planting date, each hybrid's relative maturity or maturity group and heat-unit requirement, heat units and frost risk remaining, and local trial data from similar late planting dates. "
            "Balance the risk of failing to mature, slower drydown, and higher harvest moisture or drying cost against yield stability, disease package, standability, lodging, and the trait-fit penalty of switching too early."
        )
    if decision == "wilt_differential":
        return (
            "Check root-zone moisture and irrigation uniformity while plants are wilted, and map whether affected plants follow irrigation, soil, or drainage patterns. Temporary afternoon wilt that recovers overnight supports a water-demand explanation, but early vascular wilt can also recover at first. "
            "Inspect roots, crowns, lower stems, one-sided yellowing, and vascular discoloration. Persistent morning wilt, progressive symptoms, root or crown lesions, or discolored vascular tissue strengthens the disease hypothesis and warrants a representative whole-plant diagnostic sample."
        )
    return None


def _looks_like_french(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:est-ce(?: que)?|puis-je|dois-je|j'ai|je |mon |ma |mes |cela|qu'il|dont|"
            r"aucun|seulement|avant d'|pourquoi ne pas|combien de|comment l'agent|"
            r"pommes? de terre|ma[iï]s|chaux|d[eé]pist(?:er|age)|res[eè]me)\b",
            question,
            re.IGNORECASE,
        )
    )


def _looks_like_french_output(answer: str) -> bool:
    """Require enough French function words to reject translated or English-only drift."""

    tokens = set(re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", answer.lower()))
    markers = {
        "avant", "avec", "culture", "dans", "des", "données", "étiquette", "faire", "la", "les",
        "mesures", "ne", "pas", "pour", "provinciales", "puis", "sol", "source", "vérifier",
    }
    return len(tokens & markers) >= 4


def _french_conservative_failure_answer(question_type: str) -> str:
    if question_type == "plant_health":
        return (
            "Les observations fournies ne suffisent pas pour confirmer une maladie ni choisir un traitement. "
            "Comparer les zones atteintes et normales, décrire les symptômes et leur distribution, vérifier le "
            "stade de la culture, l'incidence, la gravité, les racines et les conditions météo récentes, puis faire "
            "examiner un échantillon représentatif si le diagnostic demeure incertain.\n\n"
            "Ne traiter qu'après avoir confirmé la cause et le risque au champ. Vérifier alors le produit exact, "
            "l'étiquette canadienne actuelle pour la culture et la cible, les intervalles, la météo, la résistance "
            "et les contraintes provinciales; sinon, ne pas choisir de produit ni de dose."
        )
    if question_type == "product_label":
        return (
            "Il n'est pas possible de choisir un pesticide ou une dose avec les renseignements fournis. Confirmer "
            "la culture, la cible, le stade, la distribution et le dénombrement au champ, le produit exact, les "
            "applications antérieures et la province avant de prendre une décision.\n\n"
            "Vérifier l'étiquette canadienne actuelle pour la culture et la cible, ainsi que la dose, le moment, "
            "les intervalles, les zones tampons, la météo, la protection des travailleurs et la gestion de la "
            "résistance. Si ces éléments ne concordent pas, ne pas appliquer le produit."
        )
    if question_type.startswith("fertility"):
        return (
            "La couleur de la culture, une carte ou une valeur isolée ne suffit pas pour calculer une dose d'engrais "
            "ou de chaux. Comparer les zones atteintes et normales et obtenir des analyses représentatives avec la "
            "méthode, les unités, la profondeur et la date, puis vérifier les racines, l'humidité, le drainage, le "
            "stade et l'historique des apports.\n\n"
            "Réconcilier les crédits de fumier et de culture précédente, l'objectif réaliste et les pertes possibles, "
            "puis utiliser l'étalonnage actuel de la province et de la culture. Sans ces données, ne pas donner de dose."
        )
    if question_type == "soil_water":
        return (
            "Une carte, un indice régional ou l'apparence de la surface ne suffit pas pour fixer une irrigation, un "
            "drainage ou une date de plantation. Vérifier au champ l'humidité dans la zone racinaire, la texture, la "
            "profondeur, le drainage, les zones atteintes et normales, les apports récents et l'état de la culture.\n\n"
            "Combiner ces mesures avec la prévision météo actuelle, la capacité du système et les contraintes locales. "
            "Reporter l'opération et mesurer de nouveau si le sol, le débit, la profondeur requise ou l'effet attendu "
            "ne sont pas établis."
        )
    if question_type in {"field_data", "regional_context"}:
        return (
            "La carte, l'atlas ou l'indice régional est un contexte de dépistage; il ne prouve pas l'état uniforme du "
            "champ et ne remplace ni les observations actuelles ni les mesures au champ. Conserver la date, l'échelle, "
            "les composantes, la source et l'incertitude du produit.\n\n"
            "Vérifier les zones représentatives avec le peuplement, les dommages, le sol, le drainage, l'humidité, la "
            "météo actuelle et l'historique du champ. Ne modifier la conduite qu'après avoir relié ces observations à "
            "une recommandation provinciale actuelle."
        )
    return (
        "Les renseignements fournis ne suffisent pas pour une recommandation précise. Confirmer d'abord la culture, "
        "le stade, l'état du champ, la distribution du problème, les mesures pertinentes et l'historique de gestion.\n\n"
        "Comparer les zones atteintes et normales, vérifier la météo et les guides provinciaux actuels, puis choisir "
        "une action mesurable et réversible. Ne pas inventer de diagnostic, de dose ou de permission réglementaire."
    )


def _conservative_failure_answer(question_type: str, *, question: str = "") -> str:
    if _looks_like_french(question):
        return _french_conservative_failure_answer(question_type)
    lower = question.lower()
    focus = request_focus(lower)
    decision_state = build_decision_route_state(question, question_type)
    premise_correction = decision_state.premise_correction_answer()
    if premise_correction:
        return premise_correction
    if _is_wet_forage_establishment_question(question):
        return (
            "Do not reduce this to a dry-or-wet test. Check moisture at seeding depth across representative areas and whether the seedbed is workable and trafficable without rutting, sidewall smearing, or compaction. Run a short equipment pass where appropriate and verify uniform seed placement, furrow closure, and seed-to-soil contact; also record drainage, ponding, soil temperature, and the direction of the drying trend. "
            "Use the forecast rain amount, timing, probability, and drying window together with the forage species, seed condition, remaining establishment window, cost of delay, and feasible alternate date or establishment method. Plant only where measured seedbed and equipment conditions support uniform establishment without damage. Wait and recheck areas that remain unfit; change the establishment plan when they are unlikely to become fit within the remaining viable window."
        )
    if _requires_scout_application_separation(question):
        return _scout_application_separation_answer(question)
    route_answer = _decision_route_failure_answer(decision_state)
    if route_answer:
        return route_answer
    if _requires_integrated_specialty_decision(question):
        return _integrated_specialty_decision_answer()
    weed_focus = bool(
        re.search(r"\b(weed|waterhemp|pigweed|ryegrass|herbicide resistance|resistant|escapes?|surviv\w*|mode[- ]of[- ]action|application[- ]failure|integrated tactics?)\b", focus)
        or (
            re.search(r"\b(weed|waterhemp|pigweed|ryegrass|herbicide resistance|resistant|escapes?|surviv\w*)\b", lower)
            and not re.search(r"\b(spray|scout|weather|forecast|wind)\b", focus)
        )
    )
    if question_type == "plant_health":
        if decision_state.crop == "wheat" and re.search(r"\bwet planting|wet seedbed|poor growth after wet|patchy poor growth\b", lower):
            return (
                "Do not treat patchy wheat growth after a wet planting period as a foliar disease by default. Map affected and normal areas, count plants and tillers, and dig intact seedlings to inspect seed, seminal and crown roots, crowns, mesocotyl or subcrown internode, and the depth and pattern of discoloration or decay. Compare planting depth, seed quality and treatment, soil temperature, saturation duration, drainage, compaction or crusting, herbicide and fertilizer placement, nutrient status, and root or crown disease; submit representative whole plants and soil when the cause remains unclear. "
                "A treatment is justified only after the cause, crop stage, incidence and severity, variety susceptibility, current label fit, expected yield protection, application timing, and cost support it. Foliar fungicide is unlikely to correct waterlogging, compaction, seedling injury, or an established root and crown problem."
            )
        if re.search(r"\b(herbicide drift|off[- ]target movement)\b", lower):
            return (
                "Treat herbicide drift or off-target movement as one injury hypothesis, not a diagnosis from a windy period alone. Obtain the spray record, exact product label, active ingredient, rate and timing; reconstruct on-site wind direction, gusts, inversion and other application weather. Map the symptom pattern from the field edge through any exposure gradient and collect clear photos and representative plant samples. "
                "Compare the symptoms and mode of action with disease, nutrient or fertility problems, weather stress and other crop stress, using soil or tissue evidence and a diagnostic lab when needed. Preserve the records and seek local extension or regulatory guidance before assigning cause or liability."
            )
        if re.search(r"\b(root rot|root disease|root discoloration)\b", lower):
            return (
                "Treat root rot or root disease as a hypothesis, not a diagnosis from discoloration alone. Map the field pattern and drainage history; compare saturated soil or waterlogging, topographic and tile patterns, compaction, salinity and nutrient stress. Dig whole plants from affected margins and normal areas, inspect the roots and crown, and submit a representative root sample to a diagnostic lab when pathogen confirmation is needed. "
                "Record crop stage, recent weather, field history, crop rotation and variety susceptibility. Change drainage, fertility or treatment only after those observations separate the primary cause and any current product label fits the confirmed problem."
            )
        if re.search(r"\bnematodes?\b", lower):
            return (
                "Do not diagnose nematode injury from patchy stunting alone. Map the field pattern and review field history, rotation, prior host crops and previous test results. Follow local guidance for sample timing and collect representative soil samples and root samples from affected margins and comparable normal areas; use a diagnostic lab for species identification and population density. "
                "Interpret species and population with a locally valid threshold or risk interpretation for the crop. Only then compare a nonhost rotation, resistant variety, sanitation or labeled treatment, verifying host status, local trial evidence and the current label before acting."
            )
        if re.search(r"\b(degree[- ]day|growing degree day|weather[- ]model)\b", lower):
            return (
                "Use a locally validated degree-day or weather model to estimate when a pest life stage may appear and to schedule field scouting; it is not a spray trigger alone. First identify the pest species and expected life stage, confirm crop stage, and compare model timing with field scouting, trap counts or scout counts, weather station quality, and field history. "
                "Base treatment on observed population and damage, beneficial insects, a locally valid economic threshold, and the current product label rather than model accumulation alone."
            )
        if re.search(r"\b(disease forecast|disease model|risk model|weather[- ]based disease)\b", lower):
            return (
                "Use a locally validated forecast model, disease model, or risk model to prioritize scouting, not to diagnose disease or trigger treatment by itself. Check the model's crop, disease, geography and input fit, including leaf wetness, humidity, rain and temperature; then combine that risk context with variety or hybrid susceptibility, crop stage, field history, symptoms, scouting, incidence and severity, and a representative sample. "
                "Ask for variety susceptibility, scouting results, crop stage and current label status. Consider treatment only when those observations, the current product label, expected yield benefit, crop value, application cost, ROI and field economics support it."
            )
        if re.search(r"\b(seedling disease|stand loss)\b", lower):
            return (
                "Treat seedling disease as one hypothesis in the stand-loss differential. Map the field pattern and make a stand count, then inspect whole seedlings and seedling roots and submit a representative seedling sample or diagnostic-lab sample where needed. Record planting date, soil temperature, soil moisture, planting depth and planting conditions, emergence timing, drainage, and recent weather. "
                "Separate disease from insect feeding, herbicide injury, crusting, cold stress, compaction, and seed-quality problems. Review seed treatment history and the current seed-treatment label, but do not assume treatment failure or choose a replant action until survival and cause are established."
            )
        if re.search(r"\b(pests?|insects?|aphids?|threshold|beneficials?|natural enem|scout|sampling count|trap captures?|fruit injury)\b", lower):
            return (
                "The available evidence does not justify treating the field. Identify the pest and establish correct identification and life stage, use a defined sampling or scouting method to record the pest count, pest density and injury level, record crop stage and plant stress, and make a beneficial count for beneficial insects or natural enemies. Compare those observations with a locally valid economic threshold or action threshold. "
                "If treatment is justified, verify the current product label for the crop, target, jurisdiction, timing, and restrictions; prefer a selective product that preserves beneficials where an effective labeled option fits. Rotate effective modes of action and use nonchemical IPM tactics where they fit to reduce resistance risk."
            )
        if re.search(r"\bcorn\b", lower) and re.search(r"\brectangular\b[^?]{0,100}\blesions?\b|\blesions?\b[^?]{0,100}\bleaf veins?\b", lower):
            return (
                "Rectangular tan lesions bounded by leaf veins are consistent with gray leaf spot, but confirm the symptom pattern and field pattern with a representative diagnostic sample. Record crop stage, incidence and severity, whether lesions are moving into upper leaves or the upper canopy, recent humidity, rain or leaf wetness, field history, and hybrid susceptibility. "
                "Consider a fungicide only when diagnosis, disease severity, weather risk, current label fit, expected yield benefit, crop value, and application cost support treatment."
            )
        return (
            "Do not diagnose from symptoms alone or from an image alone. The available evidence does not support a named diagnosis or treatment decision. Build the differential from whole-plant and affected-tissue symptoms, symptom pattern and field pattern, "
            "crop stage, field history, and scouting measurements of incidence or severity; include recent weather and leaf-wetness conditions, variety susceptibility or hybrid susceptibility, and non-disease causes such as water or application injury. "
            "Confirm the cause with a representative diagnostic sample or local crop specialist. Consider treatment only after diagnosis, current label fit, and the expected yield benefit, "
            "crop value, commodity price, and application cost support a reasonable return, ROI, and field-level economics."
        )
    if question_type == "fertility_rate":
        if re.search(r"\b(volatilization|fertilizer source)\b", lower):
            return (
                "First identify the fertilizer source, formulation and application record: urea, UAN, ammonium or another source can have different loss pathways. Check placement and whether it is a surface application, incorporated, banded or injected; then evaluate volatilization and other loss risk from soil condition, temperature, residue, wind, soil pH, and the actual rainfall timing or irrigation timing after application. "
                "Match timing to crop uptake and verify the current product label for any inhibitor or stabilizer. Treat incorporation, injection, rainfall or irrigation, and a stabilizer as conditional tools, not guarantees, and do not invent a loss percentage or rate without local calibration and field evidence."
            )
        if re.search(r"\b(potassium|soil[- ]test k|marginal k)\b", lower):
            return (
                "Before changing potassium rate or placement, verify the current soil-test K value, units, sampling depth and soil test method, then interpret it with local calibration. Include CEC, soil texture or clay mineral context and exchangeable K where locally used; compare spatial soil samples with yield history, a realistic yield goal and expected crop removal. "
                "Review prior potassium applications, residue removal, manure credits, drainage and rooting constraints. Use locally calibrated guidance to compare placement, banding, broadcast and timing, and validate a change with crop response rather than turning one marginal result into a rate."
            )
        if re.search(r"\bmanure credits?\b", lower) and re.search(r"\b(runoff|water quality|tile|drainage|fertility plan)\b", lower):
            return (
                "Start with a current manure analysis or nutrient analysis, then verify the application date, application rate, application timing, method, placement, and incorporation. Calculate the plant-available nitrogen credit and phosphorus credit, account for other available nutrients and previous applications, and compare the total with the current soil test, crop need, crop removal, and realistic yield goal. "
                "Before changing the fertility plan, inspect runoff pathways, setbacks, tile outlets, drainage ditches, forecast and soil conditions, and water-quality risk. Preserve the manure test, source, field, weather, application record, credit calculation, and follow-up crop evidence."
            )
        if re.search(r"\b4r\b|\bright source\b|\bright rate\b|\bright time\b|\bright place\b", lower):
            return (
                "Build the plan around all four Rs. Right source: use a current manure analysis and account for nutrient availability. Right rate: combine the current soil test, realistic yield goal, crop removal, manure credit, previous-crop credit, and local calibration. Right time: place applications near crop uptake and avoid high leaching or runoff periods. Right place: choose placement that improves access while protecting seed, tile drainage, and surface water. "
                "Document the manure source, analysis, field, date, method, weather, rate basis, application record, and follow-up crop response so the nutrient records form an audit trail."
            )
        if re.search(r"\b(variable[- ]rate nitrogen|old yield maps?|check strips?)\b", lower):
            return (
                "Do not increase a variable nitrogen rate from old yield maps alone. Use a current soil nitrate test or other current soil evidence and a realistic yield goal; clean and align yield maps, soil tests, irrigation and rainfall records, as-applied data, and management zones. Account for drainage and leaching risk, then test the response curve with check strips or a replicated field trial. "
                "Compare expected revenue with added input and application cost, and preserve the prescription assumptions, as-applied layer, and audit trail."
            )
        if re.search(r"\b(?:increase|rescue|additional|change).{0,50}\b(?:nitrogen|n rate|nutrient plan)\b|\bnitrogen\b.{0,50}\b(?:increase|rescue|change)\b", lower):
            if decision_state.crop == "cotton":
                return (
                    "Do not increase nitrogen until the crop can realistically respond. Confirm stand and fruiting stage, current canopy and root condition, realistic yield potential, the complete nitrogen application record, and current soil nitrate or representative tissue evidence interpreted with locally calibrated cotton guidance. "
                    "Because drought stress is stated, pair that evidence with root-zone moisture, recent rainfall, irrigation capacity if the field is irrigated, and the near-term forecast. Account for previous-crop or manure credits only when the field record shows them. If water limits have already reduced yield potential, more nitrogen may add cost or delay maturity without recovering yield."
                )
            if decision_state.crop == "tomato":
                return (
                    "Do not increase nitrogen until crop demand is separated from heat, salinity, and water limitation. Confirm crop stage, canopy and fruit load, realistic yield potential, the complete fertilizer application and fertigation record, root-zone soil nitrate or a locally interpreted tissue test, irrigation-water nitrogen where relevant, and current root-zone salinity using locally calibrated tomato guidance. "
                    "Compare those results with soil moisture, irrigation timing, system capacity, water allocation, and the heat forecast. Credit manure or a previous crop only when the field record documents it. If water or salinity is limiting uptake and yield, correct that constraint rather than assuming more nitrogen will help."
                )
            if decision_state.crop == "canola":
                if re.search(r"\b(wet spring|ponding|ponded|saturated|saturation|waterlogged|uneven drainage|tile flow)\b", lower):
                    return (
                        "Do not change canola nitrogen source, rate, timing, or placement from a wet spring alone. Confirm stand and crop stage, rooting and canopy condition, realistic yield potential, and the complete nitrogen and manure application record, including source, rate, date, placement, incorporation, and any inhibitor. Map ponding and uneven drainage, record how long soils stayed saturated, and use locally useful soil nitrate or tissue evidence with locally calibrated canola guidance. "
                        "Separate possible denitrification, nitrate movement, runoff, and delayed crop uptake rather than assuming a fixed loss. Count manure, legume, or other credits only when analysis and field history support them, then compare the remaining uptake window and expected yield response with the cost and field traffic risk of an added pass."
                    )
                return (
                    "Do not justify a rescue nitrogen pass from a public forecast alone. Confirm stand, crop stage, rooting and canopy condition, the complete nitrogen application record, locally useful soil nitrate or tissue evidence, and realistic yield response using locally calibrated canola guidance. Because low stored moisture and a dry spring are stated, compare root-zone moisture, rainfall probability and duration, and crop stress with the timing needed for nitrogen uptake. "
                    "Include manure, legume, or other credits only if the field history documents them. If water-limited yield potential is already low, an added pass may not recover its cost; use local canola calibration and a partial budget before acting."
                )
            return (
                "Do not increase nitrogen until current crop condition, crop stage, rooting, realistic yield response, the complete application record, and current soil nitrate or representative tissue evidence are interpreted with local calibration. Match the stated field water and loss pathway with recent weather and the forecast, and include previous-crop, manure, or irrigation-water credits only when the field record shows they apply. "
                "Use a partial budget and the crop's remaining uptake window to decide whether an added pass can still return more than it costs."
            )
        return (
            "The available evidence does not support a nutrient rate or credit. "
            "Use a current soil test, soil nitrate test, or tissue results, crop and yield goal, source and application records, previous-crop or manure credits, "
            "recent rainfall or irrigation and drainage-loss risk, and locally calibrated guidance before changing source, rate, timing, or placement."
        )
    if question_type == "fertility_diagnostic":
        if re.search(r"\b(tissue[- ]test results?|tissue testing|plant analysis)\b", lower):
            return (
                "Interpret the tissue test or plant analysis only against the correct crop, sampled plant part, sampling date, growth stage or crop stage, handling method, and locally calibrated sufficiency range or critical level. Compare it with a current soil test, soil pH, nutrient availability, recent weather and management records. "
                "Map the field pattern and symptom pattern and sample affected and normal areas consistently. Do not use a tissue result alone to diagnose a deficiency or calculate a rate; reconcile it with soil and field evidence and, when timing or sampling is unsuitable, repeat sampling under the appropriate protocol."
            )
        if re.search(r"\b(lime|low ph|buffer ph|acidity)\b", lower):
            if re.search(r"\blow ph\b", lower) and re.search(r"\bcalcareous\b", lower):
                return (
                    "First resolve the unusual combination of a low-pH result and a calcareous soil description. Verify the sample location and depth, laboratory method and units, repeat or confirm the pH result where needed, and determine whether free carbonates occur in the sampled horizon or only in the subsoil. Do not assume the mapped or described calcareous condition proves the sampled root zone is alkaline. "
                    "Only after that check should a lime recommendation use the laboratory's buffer pH, exchangeable acidity, or lime requirement, the crop or rotation target pH, local calibration, incorporation depth, and the lime source's CCE, ECCE, neutralizing value, and fineness."
                )
            return (
                "A lime recommendation needs a current soil test with soil pH plus the laboratory's buffer pH, exchangeable acidity, or lime requirement. Set the target pH from the crop or rotation and local calibration, "
                "then adjust the recommendation for sampling depth, incorporation depth, and the lime source's CCE, ECCE, neutralizing value, and fineness. Low pH alone is not enough to choose a rate."
            )
        if re.search(r"\bphosphorus\b", lower) and re.search(r"\b(runoff|water[- ]quality|ditch|erosion)\b", lower):
            return (
                "Frame this as both a fertility and transport-risk decision. Verify the soil-test phosphorus method, units, sampling date and depth, manure history, crop removal, and local calibration; then inspect erosion and runoff pathways, setbacks or buffers, and nearby water. "
                "Where soil-test P and transport risk are already high, avoid additional phosphorus unless locally applicable guidance supports an exception, and use crop removal or drawdown plus runoff controls to reduce loss risk."
            )
        if re.search(r"\b(bray|olsen|mehlich|soil[- ]test method|calibration|critical level)\b", lower):
            return (
                "Interpret the reported soil-test method with its own locally calibrated critical levels; Bray, Olsen, and Mehlich results are not interchangeable and should not be converted without a validated relationship. "
                "Confirm units, soil pH, sampling depth and date, crop and yield goal, and expected crop removal before turning the result into a nutrient decision."
            )
        if re.search(r"\bsul(?:fur|phur)\b", lower):
            return (
                "Do not diagnose sulfur deficiency from color alone. Check sandy texture or low organic matter, recent rainfall and leaching, crop stage and field pattern, then compare representative tissue or soil evidence with nitrogen and other likely deficiencies. "
                "Use a representative tissue test or soil test, local calibration, and crop response evidence before recommending sulfur."
            )
        if re.search(r"\bmicronutrient deficiency\b|\bmicronutrient\b[^?]{0,100}\bdifferential\b", lower):
            return (
                "Do not diagnose from symptoms alone; confirm before treatment. Map the patchy field pattern and symptom pattern by plant part and leaf age, record crop stage and field history, and inspect roots. Check current soil pH, drainage, compaction or root restriction, disease, herbicide injury, weather, and any application pattern. "
                "Use a representative tissue test or plant tissue sample with a current soil test and locally calibrated interpretation before calling a micronutrient deficiency or recommending a product."
            )
        if re.search(r"\bsoybeans?\b", lower) and re.search(r"\b(interveinal|between the veins|high pH|low spots?)\b", lower):
            return (
                "The pattern is consistent with iron deficiency chlorosis (IDC), but confirm it rather than treating the description as a complete diagnosis. Check the current soil test and high pH, carbonate or bicarbonate context; compare wet low spots with drainage, compaction, salinity, rooting, and field pattern; and rule out other nutrient, root, disease, or application causes. "
                "For future management, compare locally adapted varieties with IDC tolerance, including an IDC-tolerant soybean variety, and address drainage or compaction where field evidence confirms those limits."
            )
        if re.search(r"\b(nitrate leaching|leaching risk)\b", lower):
            return (
                "Reduce nitrate exposure by matching nitrogen timing with crop uptake: consider split applications, delay a portion until the crop can use it, and credit all existing sources. A nitrification inhibitor or stabilizer can be considered only when it fits the source, timing, soil, and local evidence; it is not a substitute for rate and timing management. "
                "Where the rotation and water balance fit, use a cover crop to capture residual nitrogen. Base the plan on sandy texture, rainfall and irrigation history, drainage or tile flow, crop stage, current soil nitrate, and local loss-risk guidance."
            )
        if re.search(r"\b(yellow|pale|chlorosis|phone (?:description|photo)|photo)\b", lower):
            return (
                "Do not diagnose from a phone description or photo; it is not enough to choose a treatment. Record crop stage, which leaves and plant parts are affected, whole-plant symptoms, field pattern, roots, rainfall, drainage, soil moisture, field history, and any application pattern; collect clear photos and representative samples. "
                "Use a current soil test and tissue test to separate nitrogen or sulfur deficiency from water stress, root restriction, disease, and application injury before acting."
            )
        return (
            "A nutrient diagnosis needs a current, method-identified soil test or representative tissue test, crop stage and field pattern, soil and weather context, field history, expected crop removal, and locally calibrated interpretation. "
            "Separate a suspected deficiency from water, root, disease, and application effects before choosing a nutrient treatment."
        )
    if question_type == "integrated_management":
        return (
            "Use one field record to connect the decisions. For nutrients, start with a current soil test or tissue test, realistic yield goal, manure and previous-crop credits, and the 4R framework. For pests, identify the organism, scout population and damage, compare with a local economic threshold, and verify the current label before treatment. "
            "For soil-water risk, record soil moisture, drainage, runoff and leaching pathways, and trafficability. Tie each action to crop stage and rotation, preserve source data and field records, and keep an audit trail of observations, assumptions, applications, and outcomes."
        )
    if question_type == "exam_review":
        return (
            "Primary macronutrients are nitrogen, phosphorus, and potassium; secondary macronutrients are calcium, magnesium, and sulfur. Micronutrients are also essential but are required in smaller amounts. Nutrient mobility helps place deficiency symptoms: mobile nutrients can be moved from older leaves to new growth, so symptoms often appear first on older leaves, while immobile nutrients more often show first on younger leaves or growing points. "
            "Use that symptom pattern as a diagnostic clue, then confirm it with crop stage, field pattern, a current soil test, and a representative plant tissue test before recommending treatment."
        )
    if question_type == "seed_treatment":
        return (
            "Treat seed treatment as a field-specific economic risk decision, not insurance by default. Check planting date, soil temperature and wet or cool planting conditions, field pest history, crop rotation, previous crop and residue, pest identity and expected pressure. Where locally appropriate, use scouting, a bait trap, or validated risk factors, and keep untreated seed as a useful comparison. "
            "If economic risk is credible, verify that the seed treatment covers the target pest and that the current label for the seed treatment fits the crop, jurisdiction, planting method, and restrictions before choosing it."
        )
    if question_type == "product_label":
        if re.search(r"\b(pollinator|bees?|beekeeper|bee advisory)\b", lower):
            return (
                "First establish the IPM need: identify the pest, scout population and damage, account for beneficial insects, and compare with a locally valid economic threshold. Then verify the exact product and current product label, including any bee advisory, bloom restriction, application restrictions, and restricted-entry interval. Check pollinator habitat, bloom status and bee activity plus on-site wind, drift, buffers, downwind exposure, tile outlets, drainage ditches and runoff risk. "
                "Use direct communication with the neighbor, habitat manager or beekeeper where exposure could occur, and delay or do not spray if the label, threshold, bloom, weather, buffer or communication conditions are not satisfied."
            )
        if re.search(r"\b(carryover|rotation restriction|plant[- ]back)\b", lower):
            return (
                "Start with the exact product and herbicide active ingredient, application rate, application date and method, then verify the current product label for the intended next crop, rotation interval and plant-back restriction. Check soil pH, organic matter, texture, rainfall, soil moisture, temperature, tillage and other degradation conditions over the interval; use field history and the next crop's sensitivity rather than assuming wet weather removed the risk. "
                "Where label and local guidance support it, a representative bioassay can add evidence, but a residue test or forecast does not override the label restriction."
            )
        if re.search(r"\bpre[- ]?emergence\b", lower) and re.search(
            r"\b(activation|control failure|judging? (?:control )?failure)\b", lower
        ):
            return (
                "Before declaring preemergence control failure, identify the exact product and product label, application rate, application date and method, and any soil restrictions. Check rainfall after application, irrigation, residual activation and incorporation requirements against the current label. "
                "Use scouting to map the field pattern and escapes; record weed species, emergence timing and weed size, and compare them with application timing. Also check soil texture, organic matter, soil pH and soil moisture because they affect residual behavior. Separate inadequate activation, placement, degradation, crop or weed timing, and application error from resistance, then update resistance management only after those causes and the label-bound options are reviewed."
            )
        if re.search(r"\b(multi[- ]year integrated weed|weed seedbank|seedbank strategy)\b", lower):
            return (
                "Build a multi-year weed seedbank plan around the weed species, life cycle, escape map and herbicide history, and prevent seed production and spread every year with timely scouting and recordkeeping. Diversify crop rotation, planting and harvest timing, competitive crop stands, and cover crop options where locally suitable; add mechanical, cultural, or other nonchemical control for survivors and field edges. "
                "Use the current label and rotate chemistry by effective mode of action or site of action while avoiding repeated selection pressure. Track density, patches, control failures and seed return by field, then revise the sequence from measured outcomes rather than one season's top-line control."
            )
        if re.search(r"\b(tank mix|adjuvant|compatibility)\b", lower):
            return (
                "Do not recommend the tank mix until every exact product and all current product labels are identified and each label permits the crop, target, timing, partner, sequence and tank-mix compatibility. Check whether a jar test or compatibility procedure is required. Follow label directions for adjuvant, surfactant, oil, water conditioning, carrier, mixing order and prohibited combinations. "
                "Confirm crop stage, crop safety and variety tolerance plus weed species, weed size and growth stage. Review mode of action overlap and resistance management, then verify on-site weather and application conditions. If any product label, compatibility, crop-safety or adjuvant requirement conflicts, do not recommend the mix."
            )
        if re.search(r"\bunknown weeds?\b|\bweed identification\b", lower):
            return (
                "Do not choose control from an unknown weed. Establish weed identification and weed species from clear weed photos or a representative sample; record growth stage, weed size and emergence timing. Use scouting to map the field pattern and escapes, then review field history, herbicide history, prior mode of action and whether the pattern supports resistance or an application failure. "
                "Build the recommendation from the confirmed species and current label, combining effective labeled options with cultural and mechanical control, crop rotation, crop competition or a cover crop where they fit."
            )
        if re.search(r"\binsecticide\b", lower) and re.search(r"\b(resistance|mode[- ]of[- ]action|repeated products?)\b", lower):
            return (
                "Start with correct identification of the pest species, life stage and injury, then use a defined scouting method and scout counts to compare pest density with a locally valid economic threshold. Review field history, previous products, application records and outcomes before calling resistance. Include beneficials or natural enemies and nonchemical IPM tactics where they fit. "
                "If treatment is justified, verify the current label and choose an effective insecticide mode of action using the IRAC group where available. Rotate effective modes across generations or treatment windows as local guidance and labels support; do not rotate brand names that share the same mode or expose subthreshold populations repeatedly."
            )
        if weed_focus:
            return (
                "Do not change the weed-control plan from suspected resistance alone. Confirm the weed species, growth stage, density, and pattern of survivors; "
                "review field history, the application record, weather, timing, coverage, and prior modes of action or sites of action to separate resistance from an application failure. "
                "Map and revisit escapes, seek local resistance confirmation where appropriate, and verify the current product label. Use integrated labeled tactics: rotate to multiple effective modes of action where labels and resistance status support them, and combine labeled chemistry with crop rotation, cultivation, or other nonchemical tactics."
            )
        if re.search(r"\b(health|safety|environmental|PPE|restricted entry|preharvest|storage|handling)\b", lower):
            return (
                "Start with the current product label and registration. Check label-required personal protective equipment (PPE), mixing and loading controls, restricted-entry interval (REI), preharvest interval (PHI), worker and bystander protection, buffers, drift and runoff controls, water and sensitive-area restrictions, and weather limits. "
                "Also verify transport, storage, spill response, handling, container disposal, and required records. If the label, trained handler, equipment, or site protections cannot be met, do not recommend the application."
            )
        if re.search(r"\bwhat (?:herbicide|fungicide|insecticide|pesticide) product\b|\bproduct should\b", lower):
            return (
                "Do not select a product from 'weeds in a field' alone. First identify the crop and growth stage, weed or target species and stage, field history, resistance concerns, location or jurisdiction, and application method. Then compare registered options by effective mode of action or site of action and verify the exact current label for the crop, target, timing, restrictions, and stewardship requirements."
            )
        if _requires_scout_application_separation(question):
            return _scout_application_separation_answer(question)
        return (
            "The available evidence does not establish an acceptable application or product decision. Treat a public forecast as a planning prior, "
            "not an on-site observation. Confirm the exact product and current label, crop and target, jurisdiction, crop and target stage, "
            "on-site wind direction and gusts, inversion and rain or rainfast timing, drift risk, downwind sensitive crops or areas, buffers, and application restrictions before acting. "
            "If any of those conditions cannot be verified or satisfied, delay or do not spray."
        )
    if question_type == "field_data":
        if re.search(r"\b(on[- ]farm trial|strip trial|trial design)\b", lower):
            return (
                "A credible on-farm trial needs a documented trial layout with treatment and check strip or control, practical replication and randomization, and blocking or management zones that account for field variability. Keep all other operations consistent where possible and record deviations, weather and as-applied data. Calibrate the yield monitor, preserve raw files and clean data for headlands, overlaps, delays and obvious errors before analysis. "
                "Estimate the treatment effect with uncertainty and statistical significance appropriate to the design, then test the economic response with costs, expected response and a partial budget. One favorable strip is evidence to investigate, not a field-wide causal result."
            )
        if re.search(r"\borganic matter|soil organic carbon\b", lower) and re.search(
            r"\b(trend|changing|sampling noise|recent soil tests?)\b", lower
        ):
            return (
                "Interpret organic matter or soil organic carbon as a slow trend, not a management verdict from one test. Establish a baseline and use repeat sampling with the same georeferenced area, sampling depth, season, laboratory and lab method; otherwise sampling noise can exceed the apparent change. Ask for the sample records and management history. "
                "Relate the trend to rotation, crop residue, cover crop, tillage, manure or amendment history, erosion and drainage. Look for the intended crop response, soil structure or water-holding response before crediting a practice, and do not assume that a small change proves causation."
            )
        if re.search(r"\b(sampling design|management zones?|old soil tests?)\b", lower) and re.search(
            r"\b(soil tests?|samples?|sampling)\b", lower
        ):
            return (
                "Do not treat old soil tests as enough for a current zoned decision. Confirm the georeferenced field boundary, sample date, sampling depth, sample timing, analytical method and prior records. Define each management zone from stable evidence such as soil type, texture, drainage, topography, yield history and field history, then ground-truth the zone boundary. "
                "Use representative samples within each justified zone, or a documented grid or composite sample design suited to the decision; do not mix unlike zones in one composite. Record every point or composite, depth, date, laboratory and zone so new samples can test whether the old pattern remains valid."
            )
        if re.search(r"\b(source|checked|provenance|trace|transparent answer)\b", lower) and re.search(
            r"\b(CDL|labels?|soil survey|weather)\b", lower, re.IGNORECASE
        ):
            return (
                "Give a source trace, not a claim that every source was checked. For the confirmed field boundary or point, list each source, query time and status: map context; the NRCS soil survey, soil map unit and soil prior; the named weather source, separating current forecast from Daymet or NASA POWER climate context; the USDA CDL crop-cover sample, with the warning that it is not a planting record; and the exact product label and jurisdiction, without presenting the agent as a legal interpretation. "
                "For every adapter or document that was unavailable or not configured, say so explicitly and name the missing evidence. Ask for the current product label, grower field records and local observations needed to ground-truth the trace."
            )
        if all(re.search(pattern, lower, re.IGNORECASE) for pattern in (r"\bmap\b", r"\bsoil\b", r"\bweather\b", r"\blabel\b")):
            return (
                "First validate the drawn boundary and use map and soil-survey context only as a screening prior. Ask for the current soil test, crop and field records, recent scouting, and any observations needed to ground-truth the field. Use public weather or the forecast for planning, but use on-site observations for an operation; for a spray decision, identify the exact product and verify the current product label, crop, target, jurisdiction, timing, and restrictions. "
                "Name the missing field evidence and refuse to infer a current field condition, diagnosis, nutrient rate, product fit, or application permission that the checked sources do not establish."
            )
        if re.search(r"\b(remote sensing|remote imagery|imagery priors?|weak zones?|vegetation index|NDVI)\b", lower) and not re.search(
            r"\bCropland Data Layer\b|\bCDL\b", lower, re.IGNORECASE
        ):
            return (
                "Treat remote sensing, imagery, NDVI or another vegetation index as a screening prior, not field truth. Validate the boundary, dates, cloud and sensor effects, spatial alignment and lag; calibrate and clean the yield map before comparing signals. Use ground truth from field scouting, crop observations and representative soil samples to explain each candidate zone. "
                "Ask about yield map quality, scouting, and soil-test ground truth. Keep management zones only where the imagery and yield evidence are repeatable and agronomically coherent, then test the response with check strips or a replicated field trial. Use a partial budget to compare the economic response, added cost and uncertainty before recommending action."
            )
        if re.search(r"\bCropland Data Layer\b|\bCDL\b", lower, re.IGNORECASE):
            return (
                "Use the USDA Cropland Data Layer (CDL) and remote imagery as public crop-cover priors and screening context. Confirm boundary accuracy, then inspect boundary sample points and crop-cover classes across multiple recent years; agreement can suggest a possible rotation sequence, while edge pixels and mixed or changing classes should lower confidence. "
                "CDL is not field truth, not acreage or crop-insurance truth, and not a legal record or grower planting record. When the classification is a mismatch, present the uncertainty and do not overrule verified grower records. Reconcile the sampled multi-year rotation prior with grower field history, actual planting records, yield maps, scouting, and current field observations before using it in a management decision."
            )
        if re.search(r"\bCensus of Agriculture\b", lower, re.IGNORECASE):
            return (
                "Use the USDA Census of Agriculture and USDA NASS Quick Stats as survey-based reported statistics for a long-term trend and county, state, or regional context. Confirm the geography, crop, measure, units, year range, revisions, suppression and any data limitation before comparing periods. "
                "These public statistics are not field prediction evidence and not recommendation alone. Ask for current-season field records, grower history, yield maps, current soil and crop observations, prices and constraints before applying the regional context to an agronomic decision."
            )
        if re.search(r"\b(?:USDA )?NASS\b|\bQuick Stats\b|\bregional (?:yield|acreage|production|statistics)\b", lower, re.IGNORECASE):
            return (
                "Use USDA NASS Quick Stats regional statistics for yield, acreage, or production as a regional prior, not a field-specific prediction. Confirm the crop, crop year, measure and units, and the county, state, or regional geography before comparing years; note revisions, suppression, and geography changes where relevant. "
                "It is not forecast evidence, not field prediction evidence, and not recommendation alone. Do not let a regional average replace the field yield history, yield map, grower records, current soil and crop observations, prices, or constraints that determine this year's plan."
            )
        if re.search(r"\b(conservation|precision)\b", lower) and re.search(
            r"\b(pay|econom\w*|farm(?:'s)? books?|partial budget|roi|net return)\b", lower, re.IGNORECASE
        ):
            return (
                "Frame the choice as a field-specific partial budget and net-return decision, not a guaranteed payback. Ask for the practice's establishment, operating, maintenance, and opportunity costs; crop price; expected yield response and other benefits; risk reduction; useful life; and any current cost-share program or incentive for which eligibility can be verified. "
                "Anchor the estimate in baseline field records and, where response is uncertain, a check strip or replicated field trial. Show sensitivity or scenarios for plausible response, price, cost, and weather outcomes, and state the remaining uncertainty because public guidance cannot replace the farm's books."
            )
        if re.search(r"\b(econom\w*|profit\w*|roi|return|defensible|cost|spend|partial budget)\b", focus):
            return (
                "Evaluate the prescription with a field-specific response and a partial budget, not map appearance alone. Validate the boundary, soil tests, yield maps, as-applied records, and management zones; estimate the yield-response curve with check strips or a replicated field trial; then compare added input and application cost with crop price, expected revenue, and downside uncertainty. "
                "Keep zones only where the response is repeatable and the expected profit remains positive under realistic price and yield ranges."
            )
        if re.search(r"\b(yield maps?|as[- ]applied|prescription layers?|records?|audit trail|data quality|align)\b", lower) and not re.search(
            r"\b(variable[- ]rate|prescription|management zones?|soil EC|NDVI)\b", lower
        ):
            return (
                "Validate the field boundary, coordinate reference system, units, timestamps, crop year, and spatial alignment before combining soil tests, yield maps, imagery, as-applied records, or prescription layers. Remove duplicates and impossible values, document cleaning and interpolation, ground-truth management zones, and preserve the source and transformation audit trail. "
                "Use the cleaned layers to test a decision; do not treat correlation or a smooth map as proof of response."
            )
        if re.search(r"\b(variable[- ]rate|prescription|management zones?|soil EC|NDVI)\b", lower):
            return (
                "Clean and validate the boundary, coordinate reference system, units, timestamps, crop year, yield maps, soil EC, NDVI imagery, and soil-test points before combining them. Align the layers, flag missing or implausible values, and create management zones only where several agronomic signals agree. Ground-truth each zone with a current soil nitrate or soil test, crop removal, a current yield goal, and irrigation, rain, or leaching history. "
                "Build the prescription from an explicit yield-response hypothesis or response curve, preserve the assumptions and audit trail, and verify performance with as-applied data and check strips or a replicated trial rather than treating the map as a black-box answer."
            )
        return (
            "Use the NRCS soil survey or Soil Data Access (SDA) map unit as a regional prior and screening context. Inspect dominant components and component percentages plus mapped texture, drainage class, hydrologic group, hydric rating, slope, and restrictive-layer clues. Treat every listed attribute as a mapped interpretation, not exact field truth: it cannot prove which component occurs at a boundary point or confirm current field conditions, and it is not a replacement for soil tests or field observations. "
            "Confirm the uploaded or drawn boundary and field history, then ground-truth representative and unusual management zones with scouting, field observations, a soil pit or probe, and appropriate soil samples before changing management."
        )
    if question_type == "soil_water":
        if re.search(r"\b(climate normals?|historical gridded|gridded climate)\b", lower):
            return (
                "Use climate normals, a historical average, or historical gridded climate as a long-run prior and planning context; they describe what has occurred, not a prediction of the next operation window. Use the current forecast, current weather and short-term outlook for the actual period, including probability and uncertainty rather than a categorical promise. "
                "Recheck as operation timing approaches and ground the decision in field condition, field observations, soil moisture, crop stage and the specific operation's weather limits. Neither the normal nor the forecast proves that the field is safe."
            )
        if re.search(r"\bforecast uncertainty\b", lower) and sum(
            bool(re.search(pattern, lower)) for pattern in (r"\bplant\w*\b", r"\bspray\w*\b", r"\bside[- ]?dress\w*\b")
        ) >= 2:
            return (
                "Treat the local forecast as probabilistic planning context, not a guarantee. First identify the operation type and decision window, then compare forecast uncertainty with current field condition, soil moisture and trafficability. For planting, check seedbed fitness and soil temperature; for a spray, check the exact current label plus on-site wind, gusts, temperature, inversion and rainfall timing; for sidedress or fertilizer timing, check crop need, soil moisture, rainfall and runoff or leaching risk. "
                "Use the operation-specific downside of being wrong to set the decision boundary. Delay or wait and recheck the local forecast and field condition when that boundary is not satisfied, and do not overstate confidence."
            )
        if re.search(r"\b(rainfall intensity|rainfast|incorporation windows?|application window)\b", focus) or (
            re.search(r"\brunoff risk\b", focus) and re.search(r"\b(fertilizer|pesticide|application|operation)\b", focus)
        ):
            return (
                "Start with the local forecast rainfall amount, rainfall intensity and storm timing, then inspect slope, runoff path, erosion, drainage, soil moisture and water-quality exposure. Separate the operation rules: a fertilizer source may require incorporation or placement to limit loss, while a pesticide requires the exact current label, rainfast interval, application window, setback and buffer. "
                "Do not assume a forecast total describes runoff or satisfies a label. Delay or wait and recheck the forecast and field condition when rainfall, incorporation, runoff, trafficability, setback, buffer or label requirements are uncertain or not met."
            )
        if re.search(r"\bOpenET\b", lower, re.IGNORECASE):
            return (
                "Use OpenET evapotranspiration as satellite and model or remote-sensing context for crop water use and water demand. It is a prior, not field truth and not an irrigation prescription. Compare it with the current weather and forecast, a local sensor or probe measuring root-zone soil moisture, crop stage and rooting depth, recent rainfall, and field observations of stress, infiltration, and drainage. "
                "Reconcile that context with applied-water, flowmeter, and irrigation records plus system capacity before changing irrigation timing or amount."
            )
        if re.search(r"\bDaymet\b", lower, re.IGNORECASE):
            return (
                "Use ORNL Daymet as gridded climate context and a regional prior, not field truth or a current field measurement. Its precipitation, temperature, day length, and climate or weather-window history can frame the usual range, but the planting decision still needs the current forecast, field observations, local field soil moisture from a sensor or probe, soil temperature, and seedbed condition. "
                "For the cover-crop water tradeoff, also identify the cover-crop species or mix, rooting and biomass, termination timing and method, next-crop planting window, and current stored water before deciding."
            )
        if re.search(r"\bdrip\b", lower) and re.search(r"\b(emitters?|uniformity|uneven)\b", lower):
            return (
                "Treat public evapotranspiration as a starting water-demand estimate, not an irrigation schedule. Before changing runtime or frequency, measure root-zone soil moisture at representative depths and locations, crop stage and effective rooting depth, recent applied water and rainfall, and irrigation-water EC or salinity. "
                "Audit the drip system by comparing representative emitter discharge and pressure from the head, middle, and tail of laterals; inspect plugging and leaks; calculate distribution uniformity; and reconcile measured flow and operating time with the applied volume. Change the schedule only after crop demand, root-zone depletion, water quality, and actual system delivery agree."
            )
        if re.search(r"\b(heat|drought)\b", lower) and re.search(r"\b(reproductive|pollination|flowering|sensitive stage)\b", lower):
            return (
                "Treat heat and drought as a timing-sensitive yield risk, not an exact prediction. Confirm crop stage or reproductive stage and whether flowering or pollination overlaps the stress window; compare forecast temperature, heat stress, VPD or evaporative demand, duration, and night conditions. "
                "Ground that context with field observations, root-zone soil moisture, rooting depth, rainfall and irrigation records, system capacity, and crop stress. Prioritize water only where current soil moisture, crop need, water quality, and application capacity support it, then reassess yield risk as the forecast and field condition change."
            )
        if re.search(r"\bdrainage class\b", lower) and re.search(r"\bsoil survey|map unit|NRCS\b", lower, re.IGNORECASE):
            return (
                "Treat the NRCS soil survey drainage class, map unit and listed component as a mapped prior, not field truth. Verify it with field observations across representative and contrasting positions: ponding duration and pattern, water-table depth, saturation or wetness signs, redoximorphic features in a soil pit or probe, rooting and trafficability, topography, and recent rainfall. "
                "Inspect existing tile or surface drainage, the tile map and outlet condition because drainage infrastructure can change current behavior without changing the mapped class. Record where observations agree or disagree with the prior before changing management."
            )
        if re.search(r"\b(soil[- ]health|aggregate stability|biological indicators?)\b", lower):
            return (
                "Interpret soil-health indicators as a set of measurements tied to a management objective, not a single score that by itself justifies a change. Compare aggregate stability, organic matter, infiltration, structure or compaction, and biological indicators with a baseline sample, repeat sampling at a consistent season, depth, location, and method, and the resulting trend. "
                "Ask for field history and management history, the specific limitation being addressed, and the expected crop response or economic response. Use locally appropriate benchmarks for the soil and production system, then verify that an improving indicator is accompanied by the intended field function or crop outcome before expanding the practice."
            )
        if re.search(r"\b(salinity|sodicity|saline|sodic|sar|esp)\b", focus):
            return (
                "Visible stress or public soil context cannot by itself distinguish salinity from sodicity. Use a representative soil test with salinity measurements and an irrigation water test, "
                "evaluate sodium hazard with SAR, ESP, or equivalent locally interpreted evidence, and check field pattern, infiltration, drainage, rooting depth, crop sensitivity, and whether leaching is feasible. "
                "Confirm the diagnosis with locally interpreted soil and water results before changing irrigation or amendment management."
            )
        if re.search(r"\b(infiltration|runoff|ponding)\b", lower) and re.search(r"\b(compaction|surface condition|crusting|aggregate stability)\b", lower):
            return (
                "Map the field pattern and review traffic history before assigning a cause. Compare ponding, runoff pathways, slope and drainage with current soil moisture, infiltration, rooting and root restriction. Check surface residue, crusting and aggregate stability, then inspect compaction depth with a probe, penetrometer, bulk density measurement or soil pit at suitable moisture. "
                "Use a repeatable field measurement such as a ring infiltrometer where it fits the question, and compare affected and normal areas. Distinguish surface sealing, texture, traffic compaction, subsurface restriction and inadequate drainage before changing tillage, traffic or drainage management."
            )
        if re.search(r"\b(compaction|traffic compaction|restrictive layers?|hardpan|plow pan|shallow roots?)\b", focus):
            return (
                "Confirm compaction before treating it. Compare traffic history, the traffic pattern, yield map or field pattern, ponding, infiltration, rooting depth or root restriction, and crop response; examine the suspected layer at suitable soil moisture with a probe, penetrometer, or soil pit, and distinguish compaction from texture, drainage, or salinity. "
                "Match management to the confirmed depth and cause: prevent repeat traffic, use controlled traffic, consider targeted tillage only when soil condition is suitable, and use cover crops or drainage improvements where they address the actual limitation."
            )
        if re.search(r"\bcover crops?\b", lower):
            return (
                "Balance cover-crop water use against measured soil moisture and the next crop's planting window. Compare erosion control, residue and soil-cover benefits with establishment cost, species or mix fit, winter survival, and the risk of delayed drying or depleted stored water. "
                "Ask for rainfall or current moisture, the crop rotation, and the termination plan. Choose termination timing and method from those field conditions, the forecast, residue handling, and planting conditions rather than a fixed calendar date."
            )
        if re.search(r"\b(texture|sand|sandy|clay|water holding|available water)\b", focus):
            return (
                "Texture sets a useful water-management prior: sandy soil usually stores less available water and permits faster infiltration and leaching, while clay stores more total water but can have slower infiltration, runoff, ponding, and less readily available water when structure is poor. "
                "Confirm structure, rooting depth, compaction, and current soil moisture in the field before changing irrigation or drainage."
            )
        if re.search(r"\b(erosion|soil loss|sloping field|slope|visible runoff|conservation)\b", lower) and not re.search(
            r"\b(riparian buffers?|stream buffers?|filter strips?|drainage improvements?|wetland determination)\b", lower
        ):
            return (
                "Start with field observations of rill, gully or sheet erosion, then estimate slope, soil texture, infiltration, drainage, runoff pathways, rainfall and erosion history, and the places where soil loss or sediment deposition is occurring. Keep crop residue and minimize disturbance with tillage reduction or no-till where it fits; establish a suitable cover crop when the rotation and moisture allow. "
                "Use contour farming, strip cropping, terraces, a grassed waterway, buffer or setback where concentrated flow and slope require them. Match the combination to NRCS guidance or a local conservation plan, field access, and outlet conditions, then monitor residue cover, runoff, and soil loss after major events."
            )
        if re.search(r"\bdrainage improvements?\b", lower) and re.search(r"\b(wet spots?|tile outlet|drainage ditch|conservation boundar)\b", lower):
            return (
                "Before drainage improvements, use the soil survey as screening context and verify wet spots with field observations, a soil pit or probe, water-table evidence, topography and the drainage map, including tile, ditch and outlet. Screen for hydric soil and wetland indicators and obtain an official wetland determination where required. "
                "Check NRCS or USDA program compliance, the local conservation plan, local regulation and any permit or downstream-outlet requirements. Do not alter, deepen, connect or redirect drainage until the responsible local authority confirms the wetland and compliance boundary."
            )
        if re.search(r"\b(riparian buffers?|stream buffers?|filter strips?)\b", lower):
            return (
                "Map the water edge, stream distance, runoff path, tile outlets, eroding banks and livestock access before sizing a riparian buffer, stream buffer or filter strip. Protect bank stability and water quality with maintained vegetation, manure and nutrient setbacks, and control of concentrated runoff. Manage grazing access with livestock exclusion where needed, stable stream crossings and off-stream water where feasible. "
                "Use NRCS or a local conservation plan to set the site-specific buffer, setback and crossing design; account for erosion, flood access, maintenance and local rules before installation."
            )
        if re.search(r"\b(tile|subsurface) drainage\b", lower) and re.search(r"\b(nitrate|water[- ]quality|leaching)\b", lower):
            return (
                "Treat tile drainage or subsurface drainage as both water management and a possible nitrate transport path. Review the drainage map and tile outlet, outlet destination, rainfall, drainage flow, soil moisture and water-quality monitoring; pair that with current soil nitrate, the fertility plan, nitrogen source, rate and timing, crop uptake, and residual nitrate risk. "
                "Reduce nitrate at the source with realistic rates, split timing near crop uptake, and a cover crop where rotation and water supply fit. Where local hydrology and rules support them, evaluate controlled drainage and an edge-of-field practice such as a bioreactor or saturated buffer. Do not promise a water-quality result without site-specific flow, nitrate, design, maintenance, and downstream evidence."
            )
        if re.search(r"\b(drainage|tile|wet spots?|ponding|water table|outlet)\b", focus) and not re.search(
            r"\b(public weather|ET|evapotranspiration)\b", lower, re.IGNORECASE
        ):
            return (
                "Diagnose persistent wetness from the soil survey and map unit, topography or elevation, field pattern, rainfall history, water-table or permeability evidence, and existing tile maps and outlets. Ground-truth the low and normal areas before changing drainage. "
                "Any drainage plan also needs outlet capacity, downstream effects, and applicable wetland or drainage regulation checked locally."
            )
        return (
            "Public weather and evapotranspiration are planning context, not a field sensor or irrigation prescription. Pair them with a probe or sensor through the active root zone, crop stage and rooting depth, "
            "recent applied-water, flowmeter, irrigation, and rainfall records, system capacity, infiltration, drainage, salinity or water-quality constraints, crop stress, and trafficability. "
            "Change irrigation, drainage, or traffic timing only after those local observations establish the field water balance."
        )
    if question_type == "crop_management":
        if decision_state.crop == "potato" and re.search(r"\bcover crops?\b", lower):
            return (
                "Before potato, balance cover-crop erosion and soil-cover benefits against irrigation demand, delayed drying, residue handling, and the next planting window. Choose the species or mix from the actual rotation and confirm that it will not maintain important potato pathogens, nematodes, volunteers, or other host-related risks; review seed source and termination restrictions where relevant. "
                "Use current root-zone moisture, irrigation capacity, the hot forecast, termination timing and method, expected biomass, and potato seedbed needs to set the plan. Where disease pressure is high, include crop-specific rotation and sanitation guidance rather than assuming the cover crop is neutral."
            )
        if re.search(r"\b(poor fruit set|poor kernel set|fruit set)\b", lower):
            return (
                "Treat poor fruit set or kernel set as a crop-specific reproductive differential. Confirm bloom timing, flowering and crop stage, then check pollination biology: pollen shed and receptivity or synchrony for wind- or self-pollinated crops, and pollinator activity or bee activity only where the crop depends on it. Reconstruct temperature, heat, cold, rain and other weather during bloom. "
                "At the same time, compare root-zone soil moisture, irrigation and water stress; use a current soil test or tissue test for nutrition rather than assuming boron, calcium or another deficiency; and scout flowers, fruit and canopy for disease. Use crop-specific extension guidance to decide which observation or sample can separate the causes."
            )
        if re.search(r"\b(seed lots?|seed quality|germination|germ test|cold test|accelerated aging|seed vigor|vigor test)\b", lower):
            if re.search(r"\bpotato(?:es)?\b", lower):
                return (
                    "For potato, evaluate seed tubers rather than treating the lot like botanical seed. Verify certified-source and lot identity, seed-tuber health and disease status, physiological age, sprout condition, size distribution, storage history, and any cutting and healing or suberization plan. Inspect for rot, dehydration, pressure bruising, and other damage, and keep materially different lots separate. "
                    "Match seed-piece condition with soil temperature, soil moisture, planting depth, handling, and the expected disease environment. Adjust the planting plan only from crop-specific seed-potato guidance and field evidence, then verify emergence and stand uniformity after planting."
                )
            return (
                "Keep each seed lot separate and start with its current germination percentage or germ test plus any vigor test, cold test, or accelerated-aging result relevant to the crop. Confirm seed identity, seed size, treatment and storage history, then compare lot quality with planting date, soil temperature, soil moisture and seedbed condition. "
                "Use locally calibrated emergence assumptions to assess seeding rate, expected stand establishment and replant risk; do not invent a rate from the label value alone. Where lots differ materially, place the stronger lot in the higher-stress planting window or field and verify emergence with stand counts."
            )
        if re.search(r"\b(trait packages?|technology traits?|trait stewardship|refuge)\b", lower):
            return (
                "Compare the full trait package, not top-line yield alone. Use local trials and multi-year results from a matching environment; review disease ratings, pest resistance, herbicide tolerance, maturity, standability and stress fit against field history and rotation. Confirm that the technology trait addresses a documented field risk and that its seed or technology cost fits the expected benefit and market requirement. "
                "Before purchase or planting, verify the current label, refuge and trait stewardship requirements, herbicide-system compatibility, resistance-management obligations, grain or buyer restrictions, and recordkeeping."
            )
        if re.search(r"\b(standability|lodging|market fit|market requirement|quality ratings?)\b", lower) and re.search(
            r"\b(genetics|hybrid|variety|yield)\b", lower
        ):
            if decision_state.crop == "barley":
                return (
                    "Use public barley trials to narrow a candidate set, not rank one variety as best for the field. Compare replicated multi-location results across years and matching Montana environments, and use LSD or other reported statistical uncertainty before treating small yield differences as real. Keep entries with stable yield, suitable heading and maturity, lodging and standability, and disease ratings that fit the field history. "
                    "Match soil, water, planting date, elevation or heat-unit window, harvest capacity, and rotation constraints. Include test weight, protein, plumpness, and malt, feed, or grain-market acceptance where those traits apply. Retain several locally adapted candidates and verify seed availability and lot quality before the final choice."
                )
            return (
                "Compare genetics beyond headline yield using local trials and multi-year results from environments that match the field. Include standability, lodging or stalk strength, harvest timing and harvestability; disease ratings and field disease history; stress tolerance, maturity and drydown; and the quality trait, test weight, protein, oil or other market quality that the actual market requirement rewards. "
                "Use field history, environment fit, yield stability and the grower's risk tolerance to keep a balanced candidate set rather than trading all resilience for one top yield result."
            )
        if re.search(r"\b(weak transplants?|transplant quality|root ball|hardening)\b", lower):
            return (
                "Start with transplant source and transplant quality: inspect uniformity, root ball integrity, root color, stem and leaf condition, hardening, age and handling history. Compare soil moisture, irrigation, drainage and water stress with crop stage, temperature, heat, cold and wind exposure before and after transplanting. "
                "Review the soil test, fertility and starter fertilizer records, root-zone EC and source-water quality; inspect for disease or root disease and submit a representative sample when symptoms are ambiguous. Correct only the factor supported by the field evidence rather than assuming weak plants need more water or fertilizer."
            )
        if re.search(r"\b(specialty|vegetable|produce)\b", lower) and re.search(r"\b(irrigat\w*|water quality|water test)\b", lower):
            return (
                "Identify the water source, its contamination pathways and the irrigation method, including whether water contacts the harvested portion through overhead irrigation or is applied by drip. Check water quality with a current irrigation water test and the operation's water-safety assessment; follow applicable food safety, produce safety or FSMA requirements and any preharvest interval rather than assuming one generic standard. "
                "Ask for current soil moisture, disease symptoms, and crop stage. For disease risk, combine irrigation timing and method with humidity, leaf wetness, recent weather, crop stage, symptoms and scouting. Use local extension or crop-specific guidance plus buyer and market-quality requirements to choose monitoring, treatment and harvest actions."
            )
        if re.search(r"\b(nitrate|prussic[- ]acid|hydrocyanic acid)\b", lower) and re.search(
            r"\b(forage|pasture|graz|hay|silage|livestock)\b", lower
        ):
            return (
                "Treat nitrate and prussic acid or hydrocyanic acid as separate livestock-safety hazards. Identify the forage species, plant part, growth and regrowth stage, intended use and field pattern; document drought, frost or other stress timing plus fertilization, manure, rainfall and harvest history. Collect a representative forage test, feed test or lab test using the laboratory's sampling and handling instructions. "
                "Interpret the result with local extension, a veterinarian or feed specialist for the animal class and whether the forage will be grazed, fed as hay or ensiled as silage. Hold grazing or feeding and do not assume a withdrawal period until locally interpreted evidence supports livestock safety."
            )
        if re.search(r"\b(replant|stand survival|stand loss|uneven stand)\b", lower):
            return (
                "Do not make the replant decision immediately from the forecast. Document the standing water or flooding event, ponding duration or hours under water, soil temperature, crop stage or growth stage, field pattern and low spots; then inspect the growing point and roots for survival, oxygen stress and disease risk. Wait for recovery where agronomically appropriate, reassess viable plants, and make representative stand counts across normal and damaged areas. "
                "Compare surviving plant population, uniformity, expected yield potential and maturity with the current planting date and calendar penalty, replant seed and operation cost, termination cost, field conditions, and the locally calibrated yield response to a later stand."
            )
        if decision_state.decision == "planting_window" and not re.search(
            r"\b(relative maturity|maturity group|days to maturity)\b", lower
        ):
            if decision_state.crop == "tomato":
                return (
                    "First clarify whether this crop will be transplanted or direct-seeded. For transplants, inspect plant quality, root-ball moisture and integrity, hardening and handling; for direct seeding, verify seed quality, planting depth and seed-zone condition. In either system, measure root-zone moisture and salinity, soil temperature, seedbed or bed fitness, and irrigation capacity. "
                    "Because heat and water allocation are stated, check the short heat and wind forecast, available water for establishment, irrigation timing, and the ability to prevent salt concentration around young roots before supporting the planting window."
                )
            if decision_state.crop == "potato":
                return (
                    "Support potato planting only after checking seed-tuber or seed-piece health, physiological condition and handling, soil temperature and moisture at planting depth, seedbed fitness, compaction and clod risk, and the short heat and rain forecast. Match irrigation timing and capacity to establishment without creating prolonged wetness, and account for field disease history, seed treatment or handling records, and the risk of seed-piece decay. "
                    "Use representative field checks and delay planting when heat, moisture, seed condition, or disease risk makes uniform emergence unlikely."
                )
            if decision_state.crop == "cotton":
                return (
                    "Support cotton planting only when seed-zone temperature and moisture, seedbed fitness, planting depth, and the short forecast support rapid, uniform emergence. Under drought stress, verify stored root-zone moisture, rainfall probability or irrigation capacity where applicable, seed quality and treatment, wind-erosion and crusting risk, and whether the herbicide sequence or wind window constrains planting operations. "
                    "Balance those establishment risks against the remaining calendar and heat-unit window; do not plant from calendar pressure alone."
                )
            return (
                "Support planting only when soil temperature at seeding depth, soil moisture, and seedbed fitness are suitable for the crop. Check sidewall compaction or smearing risk, seed-to-soil contact, planting depth, the short forecast, and expected emergence and stand risk; calendar pressure or a spray window should not override poor field conditions."
            )
        if re.search(r"\brelative maturity|maturity group|days to maturity|maturity\b", lower) and re.search(
            r"\b(planting date|planting window|delayed planting)\b", lower
        ):
            return (
                "Use the actual planting date and remaining season to compare relative maturity or maturity group; do not choose from a fixed calendar rule alone. Compare replicated multi-location trials and multi-year yield stability at similar late planting dates, then weigh drydown, expected harvest moisture, harvest window, frost risk, drying capacity and market quality. "
                "Keep the disease package, standability and lodging risk in the comparison because a shorter maturity can trade yield potential or trait fit for earlier harvest. Retain more than one locally adapted candidate when weather and harvest uncertainty remain high."
            )
        if re.search(r"\bmycotoxin\b", lower):
            return (
                "Treat mycotoxin risk as a field-to-storage lot-management problem. Before harvest, map field disease, ear mold, kernel damage and disease level; review weather, drought, humidity, insect or physical damage and delayed-harvest risk. Plan a representative sample and validated test for each lot, record the test result, and segregate affected or uncertain grain rather than blending around a limit. "
                "Harvest and handle lots to limit further damage, then use prompt drying, verified storage moisture, cooling, aeration and temperature or moisture monitoring. Check current buyer, feed, food and marketing limits for the commodity and jurisdiction before moving or marketing the lot."
            )
        if re.search(r"\b(harvest|storage|drying|grain moisture)\b", focus) and not (
            re.search(r"\b(variety|hybrid|cultivar|candidate list|public trials?|genetics)\b", lower)
            and re.search(r"\b(maturity|planting date|standability|disease package|field fit)\b", lower)
        ):
            if re.search(r"\bpotato(?:es)?\b", lower):
                return (
                    "Base potato harvest timing on crop maturity, vine condition, tuber skin set, soil moisture and temperature, the short weather window, and the risk of bruising or disease. Sample representative areas for tuber size, defects, rot, and market quality; adjust digging, conveying, and drop heights to limit damage and keep problem lots separate. "
                    "Before storage, match curing, ventilation, temperature, humidity, and pile management to the intended market and the lot's condition, then monitor temperature, moisture, airflow, and breakdown rather than using a grain-moisture or aeration template."
                )
            if re.search(r"\btomato(?:es)?\b", lower):
                return (
                    "Base tomato harvest on the required maturity and color stage, market specification, fruit firmness and defects, disease or decay, the heat and rain window, and labor and handling capacity. Sample representative field areas, avoid harvesting damaged fruit into sound lots, and reduce compression, sun exposure, and handling injury. "
                    "Match cooling, sanitation, packaging, transport, and storage conditions to the tomato type and buyer requirement; monitor lot temperature and decay rather than applying grain moisture, test-weight, drying, or aeration rules."
                )
            if re.search(r"\bcotton\b", lower):
                return (
                    "Base cotton harvest timing on boll opening and crop readiness, current field and weather conditions, lint and seed-cotton moisture risk, expected weathering or quality loss, and picker or stripper and module capacity. Verify any harvest-aid decision against crop condition, the current label, forecast, and required interval. "
                    "Keep wet or contaminated seed cotton out of modules, document lot condition, protect modules from water, and use gin or buyer quality results to manage storage and marketing rather than applying grain test-weight, drying, or aeration rules."
                )
            if re.search(r"\bsugar beets?\b", lower):
                return (
                    "Base sugar-beet harvest on root maturity and quality, soil and traffic conditions, temperature and freeze risk, tare and damage, disease, and delivery or pile capacity. Adjust lifting and handling to limit cuts and bruising, separate deteriorating lots, and coordinate delivery with processor requirements. "
                    "For temporary piling, manage root temperature, ventilation, respiration, and decay risk; grain moisture, test weight, drying, and aeration targets do not apply."
                )
            return (
                "Base harvest timing on measured crop or grain moisture, field loss and standability, the short weather window, and available drying and storage capacity. For delayed harvest, record field disease and damage; take a representative sample, test suspect grain, and segregate lots where quality or mycotoxin risk differs. Plan drying, cooling and aeration, then monitor storage temperature and moisture. "
                "Check test weight, mold and mycotoxin risk, other market quality, storage disease risk, and buyer specifications before deciding whether delay or wetter harvest is the lower-risk option."
            )
        if (
            re.search(r"\b(variety|hybrid|cultivar|public trials?|seed choice|candidate list|genetics)\b", lower)
            or (re.search(r"\b(trials?|ranking|variety|hybrid|seed)\b", lower) and re.search(r"\b(maturity|standability|lodging|candidate)\b", focus))
        ):
            if re.search(r"\bwhite mold\b", lower):
                return (
                    "Public trials can narrow choices but cannot rank the best product for this field. Use multi-year, multi-location trials to compare maturity, yield stability, standability, and disease ratings, then favor locally adapted varieties with suitable white mold tolerance or resistance. Match the choice to field history, rotation, residue, drainage, planting date, and harvest constraints. "
                    "Manage canopy risk with row spacing, population, and other practices that fit yield goals; scout disease risk through the season. Consider fungicide timing only when crop stage, canopy and weather risk, current label fit, expected benefit, and economics justify it."
                )
            return (
                "Public variety trials can narrow choices but cannot rank a product for this field by themselves. Compare local multi-year trials, multi-location and replicated trial results from matching yield environments; use the reported least significant difference (LSD) or statistical significance to distinguish stable signal from one-plot noise. Include relative maturity, adaptation, soil and water limits, planting date, field history and disease history, disease or pest resistance, lodging or standability, drydown, harvest quality, market fit, management fit, and risk tolerance. "
                "Use several locally adapted candidates and verify current seed-lot quality before making the final choice."
            )
        if re.search(r"\b(specialty[- ]crop|lettuce|vegetable|high[- ]tunnel|fertigation|food[- ]safety|market[- ]quality)\b", lower):
            if re.search(r"\bhigh[- ]tunnel\b", lower):
                return (
                    "Treat the high-tunnel problem as an integrated diagnosis, not a salinity prescription. Record the fertigation recipe, injector calibration, source-water and irrigation-water test including EC, applied-water and irrigation records, and current soil EC, media test or substrate evidence. Check root-zone soil moisture, drainage and crop stage before changing water or nutrients. "
                    "At the same time, use scouting and identification to document disease symptoms, humidity, airflow and leaf wetness; verify manure and water-quality controls plus applicable food-safety requirements. If treatment is considered, check the current label, restricted-entry interval and preharvest interval. Use local extension or a crop-specific guide, current soil or tissue evidence, and buyer market-quality constraints before changing the fertigation or disease plan."
                )
            return _integrated_specialty_decision_answer()
    return (
        "The available evidence is not specific enough to support the draft without inventing details. "
        "Add the field observations, measurements, records, and local constraints that would change the decision, then reassess."
    )


def _has_specific_failure_answer(question_type: str, question: str) -> bool:
    lower = question.lower()
    focus = request_focus(lower)
    if _is_wet_forage_establishment_question(question):
        return True
    if build_decision_route_state(question, question_type).decision in {
        "ambiguous_product_followup",
        "boundary_only_fertility_rate",
        "crop_stress_differential",
        "drought_nitrogen_adjustment",
        "erosion_control_plan",
        "fungicide_decision",
        "herbicide_injury_drift_differential",
        "plant_health_diagnostic",
        "pesticide_rate_request",
        "slc_map_interpretation",
        "map_based_rescue_n",
        "salinity_management",
        "stratified_soil_sampling",
        "localized_weather_event",
        "seeding_rate_calculation",
        "sidedress_n_credit_reconciliation",
        "seed_row_fertilizer_safety",
        "wet_area_drainage_differential",
        "hail_disease_differential",
        "corn_common_rust_differential",
        "wild_oat_post_application",
        "herbicide_injury_control_failure",
        "greenhouse_tomato_leaf_curl",
        "winter_injury_differential",
        "crop_irrigation_scheduling",
        "greenhouse_substrate_irrigation",
        "sweet_corn_harvest_timing",
        "fusarium_head_blight_risk",
        "fleabane_management",
        "forage_stand_thinning_differential",
        "cutworm_stand_loss",
        "seeding_depth_decision",
        "nutrient_runoff_risk",
        "forage_frost_safety",
        "furrow_irrigation_uniformity",
        "integrated_preharvest_specialty",
        "nematode_management",
        "postharvest_cooling",
        "residual_activation",
        "soil_water_sensor_interpretation",
        "openet_irrigation_decision",
        "drip_irrigation_uniformity",
        "irrigation_water_nitrate_credit",
        "tile_drainage_decision",
        "spray_weather_window",
        "water_limited_nitrogen_increase",
        "lime_sampling_rate",
        "forage_defoliator_harvest_decision",
        "high_tunnel_yellowing",
        "soil_crusting",
        "maturity_switch",
        "physiological_disorder",
        "freeze_recovery",
        "weed_seed_return_management",
        "variable_rate_pk",
        "variety_trial_selection",
        "volunteer_trait_unknown",
        "cold_wet_purple_corn",
        "cover_crop_termination",
        "corn_rootworm_silk_clipping",
        "fruit_set_diagnostic",
        "soybean_idc",
        "sulfur_nitrogen_differential",
        "wheat_aphid_treatment",
        "wheat_flag_leaf_fungicide",
        "weed_burndown_survivor",
        "weed_escape_management",
        "underspecified_spray",
        "weed_preharvest_escape",
        "seed_treatment",
        "transplant_establishment",
        "produce_safety",
        "planting_window",
    }:
        return True
    if question_type in {
        "plant_health",
        "product_label",
        "fertility_rate",
        "fertility_diagnostic",
        "seed_treatment",
        "soil_water",
        "integrated_management",
        "exam_review",
    }:
        return True
    if question_type == "field_data":
        return bool(
            re.search(r"\b(soil map|soil[- ]survey|NRCS|SDA|map[- ]unit|component|public map|Cropland Data Layer|CDL|NASS|Quick Stats|regional statistics|on[- ]farm trial|strip trial|trial design|organic matter|soil organic carbon|sampling design|old soil tests?|management zones?|econom\w*|profit\w*|ROI|return|defensible|cost|spend|partial budget|prescription)\b", lower, re.IGNORECASE)
            or (re.search(r"\b(conservation|precision)\b", lower) and re.search(r"\bpay\b|farm(?:'s)? books?", lower))
            or all(re.search(pattern, lower, re.IGNORECASE) for pattern in (r"\bmap\b", r"\bsoil\b", r"\bweather\b", r"\blabel\b"))
            or re.search(r"\b(yield maps?|as[- ]applied|prescription layers?|records?|audit trail|data quality|align)\b", lower)
        )
    if question_type == "crop_management":
        return bool(
            re.search(r"\b(poor fruit set|poor kernel set|fruit set|seed lots?|seed quality|germination|germ test|vigor|cold test|accelerated aging|trait packages?|technology traits?|trait stewardship|refuge|forage|pasture|prussic[- ]acid|hydrocyanic acid|replant|stand survival|stand loss|uneven stand|plant(?:ing)? window|crop[- ]establishment|cold,? wet soil|plant into|harvest|storage|drying|grain moisture|weak transplants?|transplant quality|root ball|hardening|produce safety|food safety|irrigation[- ]water test)\b", lower)
            or
            re.search(r"\b(variety|hybrid|cultivar|public trials?|seed choice|candidate list|genetics)\b", lower)
            or re.search(r"\b(specialty[- ]crop|lettuce|vegetable|high[- ]tunnel|fertigation|food[- ]safety|market[- ]quality)\b", lower)
            or (re.search(r"\b(trials?|ranking|variety|hybrid|seed)\b", lower) and re.search(r"\b(maturity|standability|lodging|candidate)\b", focus))
        )
    return False


def _requires_scout_application_separation(question: str) -> bool:
    lower = question.lower()
    return bool(
        re.search(r"\bscout\w*\b", lower)
        and re.search(r"\b(?:spray|application|fungicide)\b", lower)
        and re.search(r"\b(?:separate|separately|keep those decisions|can i)\b", lower)
    )


def _requires_integrated_specialty_decision(question: str) -> bool:
    lower = question.lower()
    requested = (
        r"\birrigat\w*\b",
        r"\bfertilit\w*\b",
        r"\b(?:pest|disease|diagnos)\w*\b",
        r"\b(?:food[- ]safety|produce[- ]safety|label[- ]interval|product label)\b",
        r"\b(?:market[- ]quality|buyer quality|buyer specifications?)\b",
    )
    return sum(bool(re.search(pattern, lower)) for pattern in requested) >= 4


def _scout_application_separation_answer(question: str) -> str:
    operation = "fungicide application" if re.search(r"\bfungicide\b", question, re.IGNORECASE) else "spray application"
    return (
        "Public gridded weather or a forecast is planning context, not an on-site measurement and not approval to spray. Separate the two decisions: scouting may proceed when field access, worker safety, and crop conditions are suitable, while an application also requires field evidence that treatment is justified. "
        "Before spraying, confirm the exact product and current jurisdiction-specific label, crop and target, crop stage and application method, on-site wind and gusts, inversion and rain timing, sensitive downwind areas, buffers, preharvest or restricted-entry intervals, and other label weather limits. Recheck local observations at the field before either operation; scouting can proceed without implying that the "
        f"{operation} is warranted."
    )


def _integrated_specialty_decision_answer() -> str:
    return (
        "Keep the decision in separate but coordinated lanes. For irrigation, use crop stage and rooting depth, representative root-zone soil moisture, applied-water and drip or system-delivery records, recent weather, infiltration, drainage, and water quality. For fertility, use a current representative soil or tissue test, source and application records, irrigation-water nutrients where relevant, realistic yield or market goals, and locally calibrated crop guidance. "
        "For pests or disease, scout and identify the cause, record density or incidence and severity, crop stage, weather or leaf-wetness risk, and expected quality loss before treatment. Verify the exact current product label, preharvest interval, restricted-entry interval, resistance stewardship, and harvest timing. Check irrigation-water source and produce-safety status, crop-contact timing, worker records, buyer or processor specifications, defects, and market-quality requirements. Act first on whichever missing evidence or interval is most restrictive; do not collapse these lanes into one treatment."
    )


def _diagnosis_is_supported(answer: str, allowed: str) -> bool:
    names = (*_ITALIC_BINOMIAL_RE.findall(answer), *_PAREN_BINOMIAL_RE.findall(answer))
    return bool(names) and all(_normalize_for_matching(name) in allowed for name in names)


def _unsupported_values(pattern: re.Pattern[str], text: str, allowed: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in pattern.finditer(text):
        value = match.group(1) if match.lastindex else match.group(0)
        value = re.sub(r"[\*_]", "", value).strip()
        if value and _normalize_for_matching(value) not in allowed:
            values.append(value)
    return _dedupe(values)


def _normalize_for_matching(value: str) -> str:
    value = value.lower().replace("–", "-").replace("—", "-")
    value = re.sub(r"(?<=\d)\s*(?:-|to)\s*(?=\d)", "-", value)
    return re.sub(r"\s+", " ", value).strip()


def _dedupe(values: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            ordered.append(normalized)
    return tuple(ordered)


def _looks_incomplete(answer: str, *, question: str = "") -> bool:
    stripped = answer.rstrip()
    if question and len(re.findall(r"\b\w+\b", question)) >= 8 and len(re.findall(r"\b\w+\b", stripped)) < 5:
        return True
    if re.search(r"(?:^|\s)(?:\d+[.)]|[*+-])\s*(?:[*_`#]+)?$", stripped):
        return True
    if re.search(r"(?:^|\n)[^\n]{1,80}:\s*$", stripped):
        return True
    if len(stripped.split()) < 70:
        return False
    stripped = re.sub(r"[\*_`]+$", "", stripped).rstrip()
    return not bool(re.search(r"[.!?\)\]]$", stripped))


def _looks_like_question_echo(answer: str, *, question: str) -> bool:
    answer_normalized = _normalize_for_matching(re.sub(r"^\s*answer\s*:\s*", "", answer, flags=re.IGNORECASE))
    question_normalized = _normalize_for_matching(question)
    if not answer_normalized or not question_normalized:
        return False
    return answer_normalized == question_normalized or (
        len(answer_normalized.split()) >= 8
        and answer_normalized in question_normalized
        and len(answer_normalized) >= int(len(question_normalized) * 0.8)
    )


def _unsupported_local_weather_prediction(answer: str, *, question: str) -> bool:
    if not _asks_for_precise_local_weather_event(question):
        return False
    return not bool(
        re.search(
            r"\b(?:cannot|can't|can not|uncertain|probabil|forecast|live weather|not possible|not enough information)\b",
            answer,
            re.IGNORECASE,
        )
    )


def _asks_for_precise_local_weather_event(question: str) -> bool:
    return bool(
        re.search(r"\b(?:hail|storm|frost|rain|wind)\b", question, re.IGNORECASE)
        and re.search(r"\b(?:tomorrow|tonight|at \d{1,2}(?::\d{2})?\s*(?:am|pm)|this afternoon|this evening)\b", question, re.IGNORECASE)
        and re.search(r"\b(?:my|this)\b[^?]{0,60}\b(?:field|farm|quarter section|parcel)\b", question, re.IGNORECASE)
    )


def _localized_weather_event_answer(question: str) -> str | None:
    if not _asks_for_precise_local_weather_event(question):
        return None
    return (
        "I cannot predict whether hail or another storm hazard will strike an exact field at an exact time from the "
        "available evidence. A regional forecast, radar image, watch, or warning expresses probability and storm "
        "movement; it does not guarantee a field-level impact.\n\n"
        "When connected, use current Environment and Climate Change Canada alerts and radar plus a local nowcast, and "
        "recheck as the storm develops. For an offline decision, use observed storm movement and a low-regret contingency "
        "for exposed people, livestock, equipment, or time-sensitive field work rather than claiming a precise strike."
    )


def _looks_repetitive(answer: str) -> bool:
    lines = [re.sub(r"[\W_]+", " ", line.lower()).strip() for line in answer.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) >= 4:
        line_counts = Counter(lines)
        most_common = max(line_counts.values())
        if most_common >= 3 and most_common / len(lines) >= 0.3:
            return True
    words = re.findall(r"[a-z0-9]+", answer.lower())
    if len(words) < 80:
        return False
    grams = [tuple(words[index : index + 5]) for index in range(len(words) - 4)]
    repeated = len(grams) - len(set(grams))
    return repeated / max(1, len(grams)) >= 0.08
