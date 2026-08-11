"""Typed, offline decision contract for multi-obligation agronomy questions.

The live router remains authoritative.  This module builds a monotonic shadow
contract that keeps the primary route while making simultaneous intents,
authority requirements, missing evidence, and retrieval obligations explicit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from agronomy_agent.query_context import QueryContextSignals, analyze_query_context


POLICY_ID = "open_agronomy_agent.decision_contract.v1"
SCHEMA_VERSION = "open_agronomy_agent.decision_contract.v1"


@dataclass(frozen=True)
class EvidenceObligation:
    key: str
    description: str
    authority: str
    retrieval_terms: tuple[str, ...]
    required_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    required_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgronomyDecisionContract:
    schema_version: str
    policy_id: str
    question_sha256: str
    primary_intent: str
    intent_set: tuple[str, ...]
    action: str
    crop_scope: tuple[str, ...]
    jurisdiction_scope: tuple[str, ...]
    authority_flags: tuple[str, ...]
    evidence_obligations: tuple[EvidenceObligation, ...]
    missing_inputs: tuple[str, ...]
    required_tools: tuple[str, ...]
    original_required_tools: tuple[str, ...]
    safety_tools_preserved: bool
    retrieval_queries: tuple[str, ...]
    answer_mode: str
    applied_to_authoritative_route: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_obligations"] = [
            obligation.to_dict() for obligation in self.evidence_obligations
        ]
        return payload

    def prompt_checklist(self) -> tuple[str, ...]:
        return tuple(obligation.description for obligation in self.evidence_obligations)


@dataclass(frozen=True)
class EvidenceSelectionResult:
    selected: tuple[Any, ...]
    trace: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _ObligationRule:
    key: str
    trigger: str
    description: str
    authority: str
    intents: tuple[str, ...]
    tools: tuple[str, ...]
    retrieval_terms: tuple[str, ...]
    required_inputs: tuple[tuple[str, str], ...] = ()


_ACTION_RE = re.compile(
    r"\b(?:advise|adviser|recommend|approve|support|decide|decision|apply|application|"
    r"spray|treat|rate|timing|plant|harvest|irrigat\w*|diagnos\w*|manage|management|"
    r"what (?:should|has to|is needed)|what do (?:i|we)|how (?:much|many)|"
    r"is (?:this|that|it) enough|can (?:i|we|the grower)|should (?:i|we|the grower)|"
    r"recommander|appliquer|pulv[eé]riser|traiter|diagnostiquer|combien)\b",
    re.IGNORECASE,
)

_RULES: tuple[_ObligationRule, ...] = (
    _ObligationRule(
        key="field_observation",
        trigger=(
            r"\b(?:field|crop|plant|soil|root|leaf|leaves|stand|patch|symptom|map pin|"
            r"grower|farm|champ|culture|sol|racine|feuille)\b"
        ),
        description=(
            "Separate field observation from regional inference and identify the "
            "representative measurement, sample, count, or record needed."
        ),
        authority="field_specific_evidence",
        intents=("field_data",),
        tools=("field_data_guard",),
        retrieval_terms=(
            "representative field observations",
            "affected and normal comparison",
            "sampling scouting records",
        ),
        required_inputs=(
            ("field_measurement", r"\b(?:sample|test|count|measure|record|stage|inspection|scout|photo|image)\w*\b"),
        ),
    ),
    _ObligationRule(
        key="plant_health_differential",
        trigger=(
            r"\b(?:disease|pathogen|pest|insect|weed|rust|blight|rot|mildew|wilt|"
            r"lesion|pustule|aphid|beetle|worm|maggot|weevil|chlorosis|yellow|pale|"
            r"stunt|collapse|injury|symptom|maladie|ravageur|insecte|mauvaise herbe)\w*\b"
        ),
        description=(
            "Keep a differential diagnosis until symptoms, field pattern, crop "
            "stage, and representative confirmation support one cause."
        ),
        authority="diagnostic_evidence",
        intents=("plant_health",),
        tools=("field_data_guard",),
        retrieval_terms=(
            "differential diagnosis symptoms signs",
            "field pattern crop stage",
            "representative diagnostic sample",
        ),
        required_inputs=(
            ("crop_stage", r"\b(?:V|R)\d{1,2}\b|\b(?:crop|growth|development) stage\b"),
            ("diagnostic_observation", r"\b(?:lesion|pustule|gall|root|stem|leaf|tuber|sample|lab|photo)\w*\b"),
        ),
    ),
    _ObligationRule(
        key="regulated_product_authority",
        trigger=(
            r"\b(?:pesticide|herbicide|fungicide|insecticide|nematicide|product|"
            r"spray|tank mix|active ingredient|registration number|PMRA|label|"
            r"seed treatment|pulv[eé]ris\w*|fongicide|herbicide|insecticide|[eé]tiquette)\b"
        ),
        description=(
            "Do not authorize a regulated treatment without the exact current "
            "Canadian label, crop, target, stage, rate, timing, and restrictions."
        ),
        authority="current_regulated_product_label",
        intents=("product_label",),
        tools=("label_guard", "pesticide_safety_guard"),
        retrieval_terms=(
            "current PMRA registered product label",
            "crop target stage rate timing restrictions",
            "preharvest reentry buffer weather",
        ),
        required_inputs=(
            ("exact_product", r"\b(?:registration|reg\.?\s*no|product (?:name|number)|active ingredient|PMRA)\b"),
            ("crop_stage", r"\b(?:V|R)\d{1,2}\b|\b(?:crop|growth|development) stage\b"),
            ("target", r"\b(?:target|disease|pest|weed|insect|pathogen)\b"),
        ),
    ),
    _ObligationRule(
        key="resistance_stewardship",
        trigger=(
            r"\b(?:resistan\w*|mode of action|herbicide|fungicide|insecticide|"
            r"repeat(?:ed)? (?:spray|application)|same product|trait system)\b"
        ),
        description=(
            "Include resistance-management and treatment-history constraints when "
            "a pesticide action is being considered."
        ),
        authority="resistance_management_guidance",
        intents=("integrated_management",),
        tools=("resistance_management_guard",),
        retrieval_terms=(
            "resistance management mode of action",
            "treatment history integrated management",
        ),
        required_inputs=(
            ("treatment_history", r"\b(?:previous|prior|last|history|already|repeat|same)\b"),
        ),
    ),
    _ObligationRule(
        key="fertility_diagnosis",
        trigger=(
            r"\b(?:fertili[sz]\w*|nutrient|nitrogen|phosphorus|potassium|sul(?:f|ph)ur|"
            r"lime|soil pH|Olsen P|nitrate|manure|rescue N|deficien\w*|engrais|azote|phosphore)\b"
        ),
        description=(
            "Use current representative soil or plant evidence and local calibration "
            "before attributing symptoms or changing nutrient management."
        ),
        authority="provincial_fertility_calibration",
        intents=("fertility_diagnostic",),
        tools=("fertility_guard",),
        retrieval_terms=(
            "current provincial nutrient recommendation",
            "representative soil test plant analysis",
            "crop stage credits local calibration",
        ),
        required_inputs=(
            ("soil_or_plant_test", r"\b(?:soil|tissue|plant) (?:test|sample|analysis)\b|\bnitrate\b"),
            ("crop_or_rotation", r"\b(?:crop|rotation|previous crop|pulse|legume)\b"),
        ),
    ),
    _ObligationRule(
        key="nutrient_rate_4r",
        trigger=(
            r"\b(?:how (?:much|many)|rate|pounds?|lbs?|kg/?ha|lb/?acre|rescue N|"
            r"apply|application|placement|banded|broadcast|seed[- ]placed)\b"
            r"[\s\S]{0,100}\b(?:fertili[sz]\w*|nitrogen|phosphorus|lime|manure|nutrient|rescue N)\b|"
            r"\b(?:fertili[sz]\w*|nitrogen|phosphorus|lime|manure|nutrient|rescue N)\b"
            r"[\s\S]{0,100}\b(?:rate|apply|application|placement|banded|broadcast|pounds?|kg/?ha|lb/?acre)\b"
        ),
        description=(
            "Bind any nutrient rate to source, rate, timing, placement, credits, "
            "units, realistic yield target, and current local calibration."
        ),
        authority="nutrient_4r_and_local_rate_guidance",
        intents=("fertility_rate",),
        tools=("fertility_guard", "nutrient_4r_guard"),
        retrieval_terms=(
            "nutrient source rate timing placement",
            "manure legume residual nutrient credits",
            "yield target economics local calibration",
        ),
        required_inputs=(
            ("units", r"\b(?:kg/?ha|lb/?acre|lbs?/?acre|ppm|pounds?|kilograms?)\b"),
            ("credits", r"\b(?:manure|previous crop|pulse|legume|residual|credit)\w*\b"),
        ),
    ),
    _ObligationRule(
        key="current_weather",
        trigger=(
            r"\b(?:weather|forecast|rain|rainfall|wet|dry|drought|wind|gust|frost|"
            r"freeze|temperature|humidity|leaf wetness|storm|snow|m[eé]t[eé]o|pluie|vent|gel)\b"
        ),
        description=(
            "Treat weather as current, time-bounded evidence and distinguish risk "
            "context from a measured field condition."
        ),
        authority="current_weather_observation_or_forecast",
        intents=(),
        tools=("weather_guard",),
        retrieval_terms=(
            "current local weather observation forecast",
            "application conditions field trafficability",
        ),
        required_inputs=(
            ("decision_time", r"\b(?:today|tomorrow|date|time|hour|day|week|maintenant|demain)\b"),
        ),
    ),
    _ObligationRule(
        key="soil_water_condition",
        trigger=(
            r"\b(?:soil moisture|waterlog\w*|drainage|pond\w*|flood\w*|irrigat\w*|"
            r"salin\w*|sodic\w*|gypsum|runoff|erosion|compaction|trafficability|"
            r"water table|humidité du sol|drainage|irrigation|salinit[eé]|sodicit[eé])\b"
        ),
        description=(
            "Confirm the relevant soil-water or physical condition with field "
            "measurements before prescribing drainage, irrigation, amendment, or traffic."
        ),
        authority="field_soil_water_evidence",
        intents=("soil_water",),
        tools=("field_data_guard",),
        retrieval_terms=(
            "field soil water measurement",
            "drainage rooting infiltration trafficability",
        ),
        required_inputs=(
            ("soil_water_measurement", r"\b(?:sensor|probe|test|sample|depth|infiltration|EC|SAR|ESP|water table)\b"),
        ),
    ),
    _ObligationRule(
        key="salinity_sodicity",
        trigger=r"\b(?:salin\w*|sodic\w*|gypsum|soil[- ]?EC|SAR|ESP|salinit[eé]|sodicit[eé]|gypse)\b",
        description=(
            "Separate salinity from sodicity and require the applicable EC, SAR/ESP, "
            "water, drainage, and leaching evidence before amendment."
        ),
        authority="salinity_sodicity_diagnostic_guidance",
        intents=("soil_water",),
        tools=("salinity_sodicity_guard", "field_data_guard"),
        retrieval_terms=(
            "soil salinity electrical conductivity",
            "sodicity SAR ESP gypsum",
            "drainage leaching water quality",
        ),
        required_inputs=(
            ("salinity_or_sodicity_test", r"\b(?:EC|SAR|ESP|electrical conductivity|sodium|soil test|water test)\b"),
        ),
    ),
    _ObligationRule(
        key="soil_structure",
        trigger=r"\b(?:compaction|trafficability|soil structure|aggregate|slake|deep[- ]?rip|tillage|wheel track)\w*\b",
        description=(
            "Confirm depth, extent, moisture condition, rooting response, and traffic "
            "history before prescribing a soil-structure intervention."
        ),
        authority="soil_structure_field_evidence",
        intents=("soil_water",),
        tools=("soil_structure_guard", "field_data_guard"),
        retrieval_terms=(
            "soil compaction depth rooting",
            "traffic moisture soil structure",
            "field diagnosis before tillage",
        ),
        required_inputs=(
            ("compaction_measurement", r"\b(?:penetrometer|bulk density|pit|roots?|depth|traffic history)\b"),
        ),
    ),
    _ObligationRule(
        key="regional_or_mapped_context",
        trigger=(
            r"\b(?:map|mapped|mapping|polygon|layer|atlas|regional alert|regional report|"
            r"soil survey|ecozone|ecodistrict|SLC|AAFC|Stat(?:istics)? Canada|"
            r"carte|cartograph\w*|polygone|couche|atlas)\b"
        ),
        description=(
            "Use mapped or regional products as context, preserve their lineage and "
            "resolution, and do not treat them as current field truth."
        ),
        authority="official_regional_data_with_lineage",
        intents=("regional_context", "field_data"),
        tools=("field_data_guard",),
        retrieval_terms=(
            "official data product specification lineage resolution",
            "regional context not field truth",
        ),
        required_inputs=(
            ("field_confirmation", r"\b(?:field|ground truth|sample|inspection|record|confirm)\w*\b"),
        ),
    ),
    _ObligationRule(
        key="crop_management",
        trigger=(
            r"\b(?:planting|seeding|emergence|stand|replant|harvest|storage|ventilat\w*|"
            r"variety|hybrid|cultivar|maturity|graz\w*|rotation|plantation|semis|"
            r"r[eé]colte|entreposage|vari[eé]t[eé])\b"
        ),
        description=(
            "Bind crop-management advice to crop stage, intended use, field condition, "
            "equipment or storage system, and locally current guidance."
        ),
        authority="locally_applicable_crop_management_guidance",
        intents=("crop_management",),
        tools=(),
        retrieval_terms=(
            "crop stage field condition management",
            "equipment intended use local guidance",
        ),
        required_inputs=(
            ("crop_stage_or_timing", r"\b(?:stage|maturity|planting date|harvest date|days?|week|month)\b"),
        ),
    ),
)


def _route_value(route: Any, key: str, default: Any) -> Any:
    if isinstance(route, Mapping):
        return route.get(key, default)
    return getattr(route, key, default)


def _action(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(?:how much|how many|rate|combien)\b", lower):
        return "calculate_or_prescribe"
    if re.search(r"\b(?:diagnos\w*|is (?:this|that|it) enough|does .* prove|call .*(?:disease|deficiency))\b", lower):
        return "diagnose"
    if re.search(r"\b(?:spray|apply|treat|pulv[eé]ris\w*|appliquer|traiter)\b", lower):
        return "authorize_treatment"
    if re.search(r"\b(?:compare|choose|select|which|best)\b", lower):
        return "compare_or_select"
    if _ACTION_RE.search(text):
        return "advise"
    return "inform"


def _scope_terms(signals: QueryContextSignals) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *signals.crops[:2],
                *signals.target_jurisdictions[:2],
                *((signals.country,) if signals.country else ()),
            )
        )
    )


def _retrieval_query(
    question: str,
    signals: QueryContextSignals,
    obligation: EvidenceObligation,
) -> str:
    scope = " ".join(_scope_terms(signals))
    terms = " ".join(obligation.retrieval_terms)
    return " ".join(part for part in (question.strip(), scope, terms) if part).strip()


def build_decision_contract(
    question: str,
    route: Any,
    *,
    field_context: dict[str, Any] | None = None,
) -> AgronomyDecisionContract:
    """Build a deterministic, monotonic decision contract.

    Gold labels, eval metadata, retrieved documents, and answer text are not
    inputs.  The existing route remains the primary intent and every existing
    tool is retained.
    """

    signals = analyze_query_context(question, field_context)
    primary = str(_route_value(route, "question_type", "conceptual"))
    original_tools = tuple(
        sorted({str(value) for value in _route_value(route, "required_tools", ())})
    )
    action = _action(question)
    active_rules: list[_ObligationRule] = []
    for rule in _RULES:
        if re.search(rule.trigger, question, re.IGNORECASE):
            active_rules.append(rule)

    if _ACTION_RE.search(question) and not any(
        rule.key == "field_observation" for rule in active_rules
    ):
        active_rules.insert(0, _RULES[0])

    obligations: list[EvidenceObligation] = []
    intents = {primary}
    tools = set(original_tools)
    authorities: set[str] = set()
    missing: set[str] = set()
    for rule in active_rules:
        missing_inputs = tuple(
            name
            for name, pattern in rule.required_inputs
            if re.search(pattern, question, re.IGNORECASE) is None
        )
        obligation = EvidenceObligation(
            key=rule.key,
            description=rule.description,
            authority=rule.authority,
            retrieval_terms=rule.retrieval_terms,
            required_inputs=tuple(name for name, _ in rule.required_inputs),
            missing_inputs=missing_inputs,
            required_tools=rule.tools,
        )
        obligations.append(obligation)
        intents.update(rule.intents)
        tools.update(rule.tools)
        authorities.add(rule.authority)
        missing.update(missing_inputs)

    if len({intent for intent in intents if intent not in {"field_data", "regional_context"}}) >= 3:
        intents.add("integrated_management")

    retrieval_queries = tuple(
        dict.fromkeys(
            _retrieval_query(question, signals, obligation)
            for obligation in obligations
            if obligation.retrieval_terms
        )
    )
    if not retrieval_queries:
        retrieval_queries = (question.strip(),)

    high_consequence = bool(
        tools
        & {
            "fertility_guard",
            "label_guard",
            "pesticide_safety_guard",
            "salinity_sodicity_guard",
            "nutrient_4r_guard",
        }
    )
    answer_mode = (
        "collect_missing_evidence"
        if high_consequence and missing
        else "conditional_advice"
        if obligations
        else "inform"
    )
    required_tools = tuple(sorted(tools))
    return AgronomyDecisionContract(
        schema_version=SCHEMA_VERSION,
        policy_id=POLICY_ID,
        question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
        primary_intent=primary,
        intent_set=tuple(sorted(intents)),
        action=action,
        crop_scope=signals.crops,
        jurisdiction_scope=signals.target_jurisdictions,
        authority_flags=tuple(sorted(authorities)),
        evidence_obligations=tuple(obligations),
        missing_inputs=tuple(sorted(missing)),
        required_tools=required_tools,
        original_required_tools=original_tools,
        safety_tools_preserved=set(original_tools).issubset(required_tools),
        retrieval_queries=retrieval_queries,
        answer_mode=answer_mode,
    )


def _normalized_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", text.lower())
        if len(token) >= 3
    }


def obligation_coverage(
    doc: Any,
    contract: AgronomyDecisionContract,
) -> tuple[str, ...]:
    """Return obligation keys supported lexically by a retrieved document."""

    haystack = " ".join(
        (
            str(getattr(doc, "title", "")),
            str(getattr(doc, "text", "")),
            " ".join(str(value) for value in getattr(doc, "tags", ()) or ()),
            " ".join(str(value) for value in getattr(doc, "namespaces", ()) or ()),
        )
    )
    tokens = _normalized_tokens(haystack)
    covered: list[str] = []
    for obligation in contract.evidence_obligations:
        term_sets = [
            _normalized_tokens(term) for term in obligation.retrieval_terms
        ]
        if any(
            term_tokens
            and len(term_tokens & tokens) / len(term_tokens) >= 0.5
            for term_tokens in term_sets
        ):
            covered.append(obligation.key)
    return tuple(covered)


def select_evidence_for_contract(
    ranked_docs: Sequence[Any],
    contract: AgronomyDecisionContract,
    *,
    limit: int,
    preserve_doc_ids: Iterable[str] = (),
) -> tuple[Any, ...]:
    """Compatibility wrapper for obligation-aware selection with receipts."""

    return select_evidence_for_contract_with_trace(
        ranked_docs,
        contract,
        limit=limit,
        preserve_doc_ids=preserve_doc_ids,
    ).selected


def select_evidence_for_contract_with_trace(
    ranked_docs: Sequence[Any],
    contract: AgronomyDecisionContract,
    *,
    limit: int,
    preserve_doc_ids: Iterable[str] = (),
) -> EvidenceSelectionResult:
    """Cover distinct obligations and retain a disposition receipt per candidate."""

    if limit <= 0:
        return EvidenceSelectionResult(
            selected=(),
            trace=tuple(
                {
                    "doc_id": str(getattr(doc, "doc_id", "")),
                    "input_rank": rank,
                    "selected": False,
                    "reason": "selection_limit_zero",
                    "obligations": list(obligation_coverage(doc, contract)),
                }
                for rank, doc in enumerate(ranked_docs, start=1)
            ),
        )
    ordered = list(ranked_docs)
    by_id = {str(getattr(doc, "doc_id", "")): doc for doc in ordered}
    selected: list[Any] = []
    selected_ids: set[str] = set()
    reasons: dict[str, str] = {}
    for doc_id in preserve_doc_ids:
        doc = by_id.get(str(doc_id))
        if doc is None or str(doc_id) in selected_ids:
            continue
        selected.append(doc)
        selected_ids.add(str(doc_id))
        reasons[str(doc_id)] = "preserved_reference_source"
        if len(selected) >= limit:
            break

    covered = {
        key
        for doc in selected
        for key in obligation_coverage(doc, contract)
    }
    remaining = [doc for doc in ordered if str(getattr(doc, "doc_id", "")) not in selected_ids]
    while remaining and len(selected) < limit:
        scored: list[tuple[int, int, Any]] = []
        for rank, doc in enumerate(remaining):
            gain = len(set(obligation_coverage(doc, contract)) - covered)
            scored.append((gain, -rank, doc))
        gain, _, best = max(scored, key=lambda item: (item[0], item[1]))
        if gain <= 0:
            break
        selected.append(best)
        doc_id = str(getattr(best, "doc_id", ""))
        selected_ids.add(doc_id)
        gained_keys = sorted(set(obligation_coverage(best, contract)) - covered)
        covered.update(gained_keys)
        reasons[doc_id] = "obligation_gain:" + ",".join(gained_keys)
        remaining = [
            doc for doc in remaining if str(getattr(doc, "doc_id", "")) != doc_id
        ]

    for doc in ordered:
        if len(selected) >= limit:
            break
        doc_id = str(getattr(doc, "doc_id", ""))
        if doc_id in selected_ids:
            continue
        selected.append(doc)
        selected_ids.add(doc_id)
        reasons[doc_id] = "rank_fill_after_obligation_coverage"
    final = tuple(selected[:limit])
    selected_rank = {
        str(getattr(doc, "doc_id", "")): rank
        for rank, doc in enumerate(final, start=1)
    }
    trace = tuple(
        {
            "doc_id": str(getattr(doc, "doc_id", "")),
            "input_rank": rank,
            "selected": str(getattr(doc, "doc_id", "")) in selected_rank,
            "selected_rank": selected_rank.get(str(getattr(doc, "doc_id", ""))),
            "reason": reasons.get(
                str(getattr(doc, "doc_id", "")),
                "selection_budget_or_no_obligation_gain",
            ),
            "obligations": list(obligation_coverage(doc, contract)),
        }
        for rank, doc in enumerate(ordered, start=1)
    )
    return EvidenceSelectionResult(selected=final, trace=trace)
