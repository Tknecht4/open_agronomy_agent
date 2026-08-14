"""Versioned, consequence-calibrated answerability contracts.

The state machine governs the unsupported claim or action, not the whole
conversation.  It intentionally keeps universal safety invariants separate
from domain matchers so benign explanation and deterministic arithmetic do
not inherit field-decision or regulated-product requirements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


ANSWERABILITY_POLICY_VERSION = "open_agronomy_agent.answerability.v1"
AUTHORITY_RECEIPT_SCHEMA_VERSION = "open_agronomy_agent.authority_receipt.v1"
LABEL_APPLICABILITY_SCHEMA_VERSION = "open_agronomy_agent.label_applicability.v1"
LABEL_AUTHORITY_RECORD_SCHEMA_VERSION = "open_agronomy_agent.label_authority_record.v1"
TOOL_PLAN_SCHEMA_VERSION = "open_agronomy_agent.tool_plan.v1"
TOOL_INVOCATION_SCHEMA_VERSION = "open_agronomy_agent.tool_invocation.v1"
TOOL_RESULT_SCHEMA_VERSION = "open_agronomy_agent.tool_result.v1"
TOOL_PLANNER_VERSION = "open_agronomy_agent.tool_planner.v1"
CALCULATOR_ID = "agronomic_calculator"
CALCULATOR_VERSION = "agronomic_calculator_v1"


class AnswerabilityState(StrEnum):
    ANSWER_DIRECTLY = "answer_directly"
    ANSWER_WITH_BOUNDED_UNCERTAINTY = "answer_with_bounded_uncertainty"
    ASK_ONE_DISCRIMINATING_QUESTION = "ask_one_discriminating_question"
    REQUIRE_AUTHORITY = "require_authority"
    REFUSE_UNSAFE_ACTION = "refuse_unsafe_action"


@dataclass(frozen=True)
class DomainRulePack:
    pack_id: str
    version: str
    description: str
    matcher_patterns: tuple[str, ...]
    intents: tuple[str, ...]
    risk: str
    required_capabilities: tuple[str, ...]
    namespaces: tuple[str, ...]
    evidence_authority: str
    validator_policies: tuple[str, ...]
    regression_cases: tuple[str, ...]

    def matches(self, question: str) -> bool:
        return any(re.search(pattern, question, re.IGNORECASE) for pattern in self.matcher_patterns)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnswerabilityDecision:
    schema_version: str
    state: AnswerabilityState
    reason: str
    rule_pack_id: str
    risk: str
    missing_inputs: tuple[str, ...] = ()
    failed_claim: str | None = None
    required_authority: str | None = None
    response_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["state"] = self.state.value
        return record


UNIVERSAL_SAFETY_INVARIANTS = (
    "Do not invent a measurement, diagnosis, product permission, label direction, rate, threshold, or law.",
    "Do not convert regional or graph context into an observed field condition.",
    "Do not bypass current label, worker-safety, environmental, or jurisdictional authority.",
    "Preserve a useful supported explanation when only one requested claim is blocked.",
)


# Conservative lexical fallback for active ingredients and named products.
# Product registries and the route-risk backstop are the extension seams; this
# list prevents a bare active-ingredient rate phrase from being mistaken for a
# generic scientific rate while avoiding an arbitrary "anything + rate" rule.
_NAMED_PESTICIDE_PATTERN = (
    r"(?:glyphosate|dicamba|glufosinate|2,?4-d|mcpa|clethodim|quizalofop|sethoxydim|"
    r"atrazine|bromoxynil|imazamox|imazethapyr|chlorothalonil|azoxystrobin|"
    r"propiconazole|tebuconazole|pyraclostrobin|boscalid|mancozeb|metalaxyl|"
    r"thiamethoxam|clothianidin|imidacloprid|roundup(?: weathermax)?|liberty(?: 150)?)"
)


DOMAIN_RULE_PACKS: tuple[DomainRulePack, ...] = (
    DomainRulePack(
        pack_id="calculation.supplied_inputs.v1",
        version="1.0.0",
        description="Arithmetic from explicit quantities; the system never chooses the agronomic target.",
        matcher_patterns=(r"\b(calculate|convert|how many|arithmetic check)\b",),
        intents=("calculate", "convert"),
        risk="low_arithmetic",
        required_capabilities=("agronomic_calculator",),
        namespaces=("fertility", "seeding", "weather", "application"),
        evidence_authority="supplied_inputs_arithmetic_only",
        validator_policies=("numeric_identity", "unit_identity", "no_target_invention"),
        regression_cases=("fully_specified_calculation", "one_calculator_input_missing"),
    ),
    DomainRulePack(
        pack_id="conceptual.explanation.v1",
        version="1.0.0",
        description="Benign definitions and explanations receive the answer before brief applicability limits.",
        matcher_patterns=(
            r"^\s*(what (?:is|are|does)|why (?:is|does|do)|how does|explain|define|compare|what is the difference)\b",
            r"^\s*what rate of\b",
            r"^\s*which product (?:is|results|forms|comes)\b",
            r"\b(in general|conceptually|for an exam|study question)\b",
        ),
        intents=("define", "explain", "compare"),
        risk="low",
        required_capabilities=(),
        namespaces=("general_agronomy",),
        evidence_authority="bounded_general_knowledge",
        validator_policies=("direct_answer_present", "no_irrelevant_field_guard"),
        regression_cases=("benign_conceptual", "conceptual_regulated_term"),
    ),
    DomainRulePack(
        pack_id="regulated.product_action.v1",
        version="1.0.0",
        description="Product selection, rate, timing, permission, and restrictions require current local authority.",
        matcher_patterns=(
            r"\b(which (?:product|herbicide|fungicide|insecticide|pesticide)|what (?:product |application )?rate|recommended (?:product |herbicide |fungicide |insecticide |pesticide |application )?rate)\b",
            r"\bwhat is (?:the )?(?:current |legal |label |application )?rate (?:for|of)\b",
            r"\b(?:give|tell) me (?:the )?(?:current |legal |label |application )?rate (?:for|of)\b",
            r"\b(?:product|herbicide|fungicide|insecticide|pesticide) label rate (?:for|on|in)\b",
            r"\b(?:choose|select|set|authorize)\b.{0,80}\b(?:seed[- ]treatment product|tank mix|herbicide|fungicide|insecticide|pesticide|legal application rate)\b",
            r"\b(can|should) (?:i|we) (?:apply|spray|treat)|\bapply (?:now|today)\b|\bspray (?:now|today)\b",
            r"\b(?:spray(?:ing)?|apply(?:ing)?|use|using)\b.{0,80}\b(?:today|now|this (?:product|herbicide|fungicide|insecticide|pesticide))\b",
            r"\b(?:how many|how much|calculate)\b.{0,80}\b(?:product|herbicide|fungicide|insecticide|pesticide)\b.{0,80}\b(?:spray|apply|recommended|my field|today|now)\b",
            r"\b(?:can|may|should|could) (?:i|we) (?:use|apply|spray|mix|tank[- ]mix)\b.{0,120}\b(?:on|in|for|with)\b",
            r"\b(?:can|may|should|could|is|are)\b.{0,100}\b(?:be )?(?:used|applied|sprayed|mixed|tank[- ]mixed)\b.{0,100}\b(?:on|in|for|with)\b",
            r"^\s*(?:use|apply|spray|mix|tank[- ]mix)\b.{0,120}\b(?:on|in|for|with)\b",
            r"\b(?:is|are|was|were)\b.{0,100}\b(?:registered|approved|permitted|allowed|legal)\b.{0,100}\b(?:for|on|in|with)\b",
            r"\b(?:does|do) (?:the )?(?:label|registration)\b.{0,100}\b(?:allow|permit|authorize|restrict)\b",
            r"\b(?:tank[- ]mix|tank mix)\b.{0,100}\b(?:allowed|approved|compatible|permitted|with|for|on)\b",
            r"\b(?:pre[- ]harvest interval|phi|restricted[- ]entry interval|rei|buffer(?: zone)?|use restriction|application restriction)\b.{0,100}\b(?:for|of|on|with)\b",
            r"\b(?:registration|registered|permission|permitted|approved|legal use|label restriction)\b.{0,120}\b(?:product|herbicide|fungicide|insecticide|pesticide|crop|field|tank[- ]mix)\b",
            r"\bhow much\b.{1,80}\bshould (?:i|we) (?:use|apply|spray)\b",
            r"\bhow many\b.{0,24}\b(?:fl(?:uid)?\s+)?(?:ounces?|oz|litres?|liters?|millilitres?|milliliters?|ml|grams?|g|kg)\b.{0,80}\b(?:per (?:acre|hectare)|/(?:ac|ha))\b",
            rf"^\s*(?:(?:what is|tell me|give me)\s+)?(?:the\s+)?{_NAMED_PESTICIDE_PATTERN}\s+"
            r"(?:label\s+)?(?:rate|dose)\s*[?.!]*\s*$",
            rf"\b{_NAMED_PESTICIDE_PATTERN}\b.{{0,100}}\b"
            r"(?:rate|dose|buffer(?: zone)?|pre[- ]harvest interval|phi|restricted[- ]entry interval|rei|restriction)\b",
            r"\b(?:rate|dose|buffer(?: zone)?|pre[- ]harvest interval|phi|restricted[- ]entry interval|rei|restriction)\b"
            rf".{{0,100}}\b(?:for|of|on)\s+(?:the\s+)?{_NAMED_PESTICIDE_PATTERN}\b",
            rf"^\s*(?:use|apply|spray|mix|tank[- ]mix)\s+(?:the\s+)?{_NAMED_PESTICIDE_PATTERN}\b",
            rf"\b(?:can|may|should|could) (?:i|we) (?:use|apply|spray|mix|tank[- ]mix)\b"
            rf".{{0,100}}\b{_NAMED_PESTICIDE_PATTERN}\b",
            rf"^\s*(?:is|are)\s+(?:the\s+)?{_NAMED_PESTICIDE_PATTERN}\b"
            r".{0,60}\b(?:allowed|legal|registered|approved|permitted)\b",
            rf"^\s*how much\s+(?:of\s+)?(?:the\s+)?{_NAMED_PESTICIDE_PATTERN}\b",
            rf"\b(?:puis-je|peut-on|devrais-je)\s+(?:utiliser|appliquer|pulv[eé]riser|m[eé]langer)\b"
            rf".{{0,100}}\b(?:du|de la|le|la|l['’])?\s*{_NAMED_PESTICIDE_PATTERN}\b",
            rf"^\s*(?:utiliser|appliquer|pulv[eé]riser|m[eé]langer)\s+"
            rf"(?:du|de la|le|la|l['’])?\s*{_NAMED_PESTICIDE_PATTERN}\b",
            rf"^\s*(?:le|la|l['’])?\s*{_NAMED_PESTICIDE_PATTERN}\b.{{0,60}}\b"
            r"(?:autoris[eé]e?|l[eé]gal(?:e)?|homologu[eé]e?|permis(?:e)?)\b",
            rf"^\s*(?:quelle dose|combien(?:\s+de)?|quel est le taux)\b.{{0,100}}\b"
            rf"(?:de|du|de la|de l['’]|le|la|l['’])?\s*{_NAMED_PESTICIDE_PATTERN}\b",
            r"\bwhat (?:rate|dose)\b.{0,100}\b(?:do|should|can|may) (?:i|we) (?:apply|use|spray)\b",
            r"\bwhat dose\b.{0,100}\b(?:apply|use|spray)\b",
            r"\btank[- ]mix\b.{0,100}\b(?:and|with)\b",
        ),
        intents=("select_product", "set_rate", "authorize_application"),
        risk="regulated",
        required_capabilities=("current_label_authority",),
        namespaces=("crop_protection", "regulatory"),
        evidence_authority="current_jurisdiction_specific_label",
        validator_policies=("label_authority_required", "jurisdiction_required", "block_unsupported_action_claim_only"),
        regression_cases=("regulated_action_missing_authority", "regulated_conceptual_explanation"),
    ),
    DomainRulePack(
        pack_id="consequential.action_authority.v1",
        version="1.0.0",
        description="Irreversible, certified, or exact field actions require representative evidence and named human authority.",
        matcher_patterns=(
            r"\b(?:set|choose|make|authorize)\b.{0,80}\b(?:final|exact|irreversible|legal)\b",
            r"\b(?:certify|guarantee)\b.{0,80}\b(?:safe|no injury|will not injure|cannot cause|permitted)\b",
            r"\b(?:terminate and reseed|reseed the entire|irreversible call)\b",
        ),
        intents=("authorize_field_action", "certify_outcome", "make_irreversible_decision"),
        risk="high",
        required_capabilities=("representative_field_evidence", "qualified_human_authority"),
        namespaces=("field_context", "decision_authority"),
        evidence_authority="qualified_local_decision_authority",
        validator_policies=("representative_evidence_required", "no_outcome_guarantee", "human_authority_required"),
        regression_cases=("irreversible_action_missing_evidence", "outcome_guarantee_missing_authority"),
    ),
    DomainRulePack(
        pack_id="field.decision.v1",
        version="1.0.0",
        description="Field decisions may be bounded or ask for one input that would actually change the call.",
        matcher_patterns=(
            r"\b(my field|this field|these symptoms|should i|what should (?:i|we) do|recommend)\b",
            r"\b(diagnos|treat|fertili[sz]er rate|yield goal|soil test|tissue test)\b",
        ),
        intents=("diagnose", "plan", "recommend"),
        risk="field_dependent",
        required_capabilities=("field_context",),
        namespaces=("field_context", "diagnostics", "management"),
        evidence_authority="representative_field_evidence",
        validator_policies=("separate_observation_inference_action", "minimal_discriminating_question"),
        regression_cases=("fully_specified_plan", "one_critical_input_missing"),
    ),
)


_UNSAFE_BYPASS_RE = re.compile(
    r"\b(?:ignore|bypass|evade)\b.{0,80}\b(?:label|ppe|restricted entry|rei|buffer|law|regulation)\b",
    re.IGNORECASE,
)
_DIRECT_RATE_RE = re.compile(
    r"\b(?:how much|what (?:fertilizer |nitrogen |product |application )?rate|give me (?:a |the )?rate)\b",
    re.IGNORECASE,
)
_REGULATED_ROUTE_TYPES = {
    "crop_protection",
    "fungicide",
    "herbicide",
    "insecticide",
    "pesticide",
    "product_label",
    "regulated_product",
}
_REGULATED_CONTROL_TERMS_RE = re.compile(
    r"\b(?:label|registration|registered|legal|permitted|permission|approved|tank[- ]mix|"
    r"pre[- ]harvest interval|phi|restricted[- ]entry interval|rei|buffer(?: zone)?|restriction)\b",
    re.IGNORECASE,
)
_BENIGN_DEFINITION_RE = re.compile(
    r"^\s*(?:what (?:is|are|does)|define|explain(?: in general)?|what does)\b",
    re.IGNORECASE,
)
_FERTILIZER_ONLY_RE = re.compile(
    r"\b(?:fertili[sz]er|nitrogen|phosphorus|potassium|sulphur|sulfur|urea|potash|map|dap|"
    r"nutrient|n[- ]p[- ]k|\d{1,2}-\d{1,2}-\d{1,2})\b",
    re.IGNORECASE,
)
_PESTICIDE_OR_PRODUCT_RE = re.compile(
    r"\b(?:herbicide|fungicide|insecticide|pesticide|seed treatment|crop protection product|"
    r"active ingredient|pcp|pmra|epa(?:-registered)?|product label|"
    + _NAMED_PESTICIDE_PATTERN
    + r")\b",
    re.IGNORECASE,
)
_NON_REGULATED_RATE_RE = re.compile(
    r"\b(?:fertili[sz]er|nitrogen|phosphorus|potassium|sulphur|sulfur|urea|potash|map|dap|"
    r"nutrient|lime|limestone|manure|compost|seed|seeding|planting|plant population|stand|"
    r"irrigation|water|rainfall|yield|growth|emergence|germination|cover crops?|no[- ]till|"
    r"intercropping|gypsum|erosion control|photosynthesis|reaction|product formation|"
    r"photosynth[eè]se|r[eé]action|[eé]rosion|eau|gypse|culture de couverture|semis direct|"
    r"interculture|rayonnement)\b",
    re.IGNORECASE,
)
_NAMED_PESTICIDE_RE = re.compile(rf"\b{_NAMED_PESTICIDE_PATTERN}\b", re.IGNORECASE)
_REGULATED_CLAIM_TERMS_RE = re.compile(
    r"\b(?:how much|rate|dose|apply|spray|treat|use|mix|tank[- ]mix|registered|approved|permitted|allowed|legal|"
    r"puis-je|utiliser|appliquer|pulv[eé]riser|m[eé]langer|autoris[eé]e?|l[eé]gal(?:e)?|"
    r"homologu[eé]e?|permis(?:e)?|quelle dose|combien|taux|"
    r"permission|authorize|label|pre[- ]harvest interval|phi|restricted[- ]entry interval|rei|"
    r"buffer(?: zone)?|restriction|ounces?|oz|litres?|liters?|millilitres?|milliliters?|ml|kg|g)\b",
    re.IGNORECASE,
)
_PRODUCT_CLASS_RATE_RE = re.compile(
    r"\b(?:herbicide|fungicide|insecticide|pesticide|crop protection product|product label)\b"
    r".{0,80}\b(?:rate|dose|apply|spray|use|registered|approved|permitted|allowed|legal)\b|"
    r"\b(?:rate|dose)\b.{0,80}\b(?:herbicide|fungicide|insecticide|pesticide)\b",
    re.IGNORECASE,
)
_EXPLICIT_REGULATED_SELECTION_OR_AUTHORITY_RE = re.compile(
    r"\bwhich (?:product|herbicide|fungicide|insecticide|pesticide)\b.{0,100}\b"
    r"(?:should|can|may|could|use|apply|spray|treat|control|manage)\b|"
    r"\b(?:label|registration)\b.{0,100}\b"
    r"(?:allow|permit|authorize|restrict|rate|dose|apply|spray|use|registered|approved)\w*\b|"
    r"\b(?:registered|approved|permitted|allowed|legal)\b.{0,100}\b(?:for|on|in|with)\b|"
    r"\b(?:can|may|should|could) (?:i|we)\b.{0,100}\b(?:use|apply|spray|mix)\b"
    r".{0,100}\b(?:this|that|the|named) product\b",
    re.IGNORECASE,
)
_REPRESENTATIVE_SAMPLE_KEYS = (
    "representative_sample",
    "representative_measurement",
    "soil_sample",
    "tissue_sample",
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _normalized_scope(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _is_benign_regulated_definition(question: str) -> bool:
    if not _BENIGN_DEFINITION_RE.search(question):
        return False
    lower = question.casefold()
    action_request = bool(
        (
            _NAMED_PESTICIDE_RE.search(question)
            and _REGULATED_CLAIM_TERMS_RE.search(question)
        )
        or _PRODUCT_CLASS_RATE_RE.search(question)
        or _EXPLICIT_REGULATED_SELECTION_OR_AUTHORITY_RE.search(question)
        or
        re.search(
            r"\b(?:can|may|should|could|do|does|is|are) "
            r"(?:i|we|this|that|the product|my product|our product)\b"
            r".{0,100}\b(?:apply|spray|use|mix|registered|allowed|permitted|legal)\b",
            lower,
        )
        or re.search(r"\b(?:for|on) (?:my|this|our) (?:field|crop)\b", lower)
    )
    return not action_request


def _is_fertilizer_only_request(question: str) -> bool:
    return bool(_FERTILIZER_ONLY_RE.search(question)) and not bool(
        _PESTICIDE_OR_PRODUCT_RE.search(question) or _REGULATED_CONTROL_TERMS_RE.search(question)
    )


def _is_non_regulated_rate_request(question: str) -> bool:
    """Protect ordinary fertility, seed, water, and growth rates from label policy."""

    return bool(_NON_REGULATED_RATE_RE.search(question)) and not bool(
        _PESTICIDE_OR_PRODUCT_RE.search(question) or _REGULATED_CONTROL_TERMS_RE.search(question)
    )


def has_recognized_regulated_product(question: str) -> bool:
    """Return whether current policy recognizes a product class, active, or named product."""

    return bool(_PESTICIDE_OR_PRODUCT_RE.search(question))


def _regulated_pack_claim_intent(question: str) -> bool:
    """Require a product entity/class or explicit selection/authority act.

    Generic verbs such as "use" and scientific nouns such as "rate" are not
    pesticide evidence.  A product-aware route can still invoke the backstop.
    """

    if _is_benign_regulated_definition(question):
        return False
    if _EXPLICIT_REGULATED_SELECTION_OR_AUTHORITY_RE.search(question):
        return True
    if _NAMED_PESTICIDE_RE.search(question) and _REGULATED_CLAIM_TERMS_RE.search(question):
        return True
    return bool(_PRODUCT_CLASS_RATE_RE.search(question))


def _regulated_route_backstop(question: str, route: Any | None) -> bool:
    if (
        route is None
        or _is_benign_regulated_definition(question)
        or _is_fertilizer_only_request(question)
        or _is_non_regulated_rate_request(question)
    ):
        return False
    route_risk = str(getattr(route, "risk_level", "") or "").casefold()
    question_type = str(getattr(route, "question_type", "") or "").casefold()
    required_tools = {
        str(value).casefold()
        for value in (getattr(route, "required_tools", ()) or ())
    }
    return (
        route_risk == "regulated"
        or question_type in _REGULATED_ROUTE_TYPES
        or "product_label" in required_tools
        or "pesticide_guard" in required_tools
    )


def _representative_sample_complete(field_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(field_context, Mapping):
        return False
    if field_context.get("representative_measurement_complete") is True:
        return True
    if field_context.get("representative_sample_complete") is True:
        return True
    for key in _REPRESENTATIVE_SAMPLE_KEYS:
        sample = field_context.get(key)
        if not isinstance(sample, Mapping):
            continue
        has_result = sample.get("result") not in (None, "", []) or sample.get("value") not in (None, "", [])
        has_units = bool(str(sample.get("units") or sample.get("unit") or "").strip())
        has_method = bool(str(sample.get("method") or sample.get("test_method") or "").strip())
        representative = sample.get("representative") is True or str(sample.get("sampling_basis") or "").casefold() in {
            "representative",
            "representative_composite",
        }
        current = str(sample.get("freshness_status") or sample.get("status") or "").casefold() in {
            "current",
            "current_verified",
            "valid",
            "verified",
        }
        if has_result and has_units and has_method and representative and current:
            return True
    return False


def summarize_field_context_for_answerability(
    field_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return presence signals used by policy without treating crop/location as a sample."""

    context = dict(field_context or {})
    crop_values = context.get("crop_scope") or tuple(
        value for value in (context.get("crop_current"), context.get("crop")) if value
    )
    jurisdiction_values = context.get("jurisdiction_scope") or tuple(
        value
        for value in (context.get("province_state"), context.get("country"), context.get("region"))
        if value
    )
    product_values = context.get("product_scope") or tuple(
        value for value in (context.get("product_name"), context.get("product_id")) if value
    )
    extra_scopes = {
        "target_scope": context.get("target_scope")
        or tuple(
            value
            for value in (
                context.get("target"),
                context.get("target_pest"),
                context.get("target_weed"),
                context.get("target_disease"),
            )
            if value
        ),
        "site_scope": context.get("site_scope")
        or tuple(value for value in (context.get("site"), context.get("site_type")) if value),
        "use_pattern_scope": context.get("use_pattern_scope")
        or tuple(value for value in (context.get("use_pattern"), context.get("application_timing")) if value),
        "application_method_scope": context.get("application_method_scope")
        or tuple(value for value in (context.get("application_method"), context.get("application_type")) if value),
        "registration_scope": context.get("registration_scope")
        or tuple(value for value in (context.get("registration_id"), context.get("pcp_number")) if value),
        "label_scope": context.get("label_scope")
        or tuple(value for value in (context.get("label_id"), context.get("label_sha256")) if value),
        "effective_date_scope": context.get("effective_date_scope")
        or tuple(value for value in (context.get("label_effective_date"),) if value),
    }

    def _as_tuple(values: Any) -> tuple[str, ...]:
        if values in (None, ""):
            return ()
        if isinstance(values, (str, bytes)):
            values = (values,)
        if not isinstance(values, Sequence):
            values = (values,)
        return tuple(str(value) for value in values if str(value or "").strip())

    return {
        "representative_measurement_complete": _representative_sample_complete(context),
        "crop_scope": _as_tuple(crop_values),
        "jurisdiction_scope": _as_tuple(jurisdiction_values),
        "product_scope": _as_tuple(product_values),
        "authority_as_of_date": str(context.get("authority_as_of_date") or date.today().isoformat()),
        **{key: _as_tuple(values) for key, values in extra_scopes.items()},
    }


def _identifier(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _validated_calculator_invocation(
    question: str,
    tool_plan: Mapping[str, Any] | None,
    *,
    expected_plan_status: str,
    expected_invocation_status: str,
) -> Mapping[str, Any] | None:
    plan = tool_plan if isinstance(tool_plan, Mapping) else {}
    if (
        plan.get("schema_version") != TOOL_PLAN_SCHEMA_VERSION
        or plan.get("planner_version") != TOOL_PLANNER_VERSION
        or plan.get("status") != expected_plan_status
    ):
        return None
    invocations = plan.get("invocations")
    if not isinstance(invocations, Sequence) or isinstance(invocations, (str, bytes)) or len(invocations) != 1:
        return None
    invocation = invocations[0]
    if not isinstance(invocation, Mapping):
        return None
    inputs = invocation.get("inputs")
    missing_inputs = invocation.get("missing_inputs")
    if not isinstance(inputs, Mapping) or not isinstance(missing_inputs, Sequence) or isinstance(missing_inputs, (str, bytes)):
        return None
    operation = str(invocation.get("operation") or "").strip()
    question_sha256 = _sha256_text(question)
    seed = {
        "planner_version": TOOL_PLANNER_VERSION,
        "tool_id": CALCULATOR_ID,
        "tool_version": CALCULATOR_VERSION,
        "operation": operation,
        "inputs": dict(inputs),
        "question_sha256": question_sha256,
    }
    if (
        invocation.get("schema_version") != TOOL_INVOCATION_SCHEMA_VERSION
        or invocation.get("planner_version") != TOOL_PLANNER_VERSION
        or invocation.get("tool_id") != CALCULATOR_ID
        or invocation.get("tool_version") != CALCULATOR_VERSION
        or invocation.get("question_sha256") != question_sha256
        or invocation.get("invocation_id") != _identifier("invocation", seed)
        or invocation.get("status") != expected_invocation_status
        or invocation.get("authority_role") != "supplied_inputs_arithmetic_only"
        or invocation.get("risk_class") != "low_arithmetic"
        or not operation
    ):
        return None
    if expected_plan_status == "ready" and tuple(missing_inputs):
        return None
    if expected_plan_status == "clarification_required" and not tuple(missing_inputs):
        return None
    return invocation


def validated_deterministic_tool_execution(
    question: str,
    tool_plan: Mapping[str, Any] | None,
    tool_results: Sequence[Mapping[str, Any]],
) -> bool:
    # The runtime records are untrusted trace input at this boundary.  Accept
    # only the exact current planner output and exact deterministic execution,
    # not a mapping that merely borrows familiar status or identifier fields.
    from agronomy_agent.tool_planner import plan_and_execute_tools

    try:
        expected_plan, expected_results = plan_and_execute_tools(question)
    except (ArithmeticError, TypeError, ValueError):
        return False
    if (
        expected_plan.status != "ready"
        or _canonical_json(dict(tool_plan or {})) != _canonical_json(expected_plan.to_dict())
        or _canonical_json(list(tool_results))
        != _canonical_json([result.to_dict() for result in expected_results])
    ):
        return False
    invocation = _validated_calculator_invocation(
        question,
        tool_plan,
        expected_plan_status="ready",
        expected_invocation_status="planned",
    )
    if invocation is None or len(tool_results) != 1:
        return False
    result = tool_results[0]
    if not isinstance(result, Mapping):
        return False
    payload = result.get("payload")
    if not isinstance(payload, Mapping):
        return False
    payload_sha256 = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    expected_result_id = _identifier(
        "tool_result",
        {
            "invocation_id": invocation["invocation_id"],
            "payload_sha256": payload_sha256,
        },
    )
    payload_answer = str(payload.get("answer") or "").strip()
    payload_boundary = str(payload.get("boundary") or "").casefold()
    return bool(
        result.get("schema_version") == TOOL_RESULT_SCHEMA_VERSION
        and result.get("result_id") == expected_result_id
        and result.get("invocation_id") == invocation.get("invocation_id")
        and result.get("tool_id") == CALCULATOR_ID
        and result.get("tool_version") == CALCULATOR_VERSION
        and result.get("operation") == invocation.get("operation")
        and result.get("status") == payload.get("status") == "calculated"
        and result.get("payload_sha256") == payload_sha256
        and result.get("authority_role") == "supplied_inputs_arithmetic_only"
        and result.get("freshness_status") == "not_time_sensitive"
        and result.get("provenance") == "agronomy_agent.agronomic_calculations"
        and payload.get("tool") == CALCULATOR_ID
        and payload.get("operation") == invocation.get("operation")
        and payload_answer
        and "supplied inputs only" in payload_boundary
        and "does not choose an agronomic target" in payload_boundary
    )


def validated_deterministic_tool_clarification(
    question: str,
    tool_plan: Mapping[str, Any] | None,
    tool_results: Sequence[Mapping[str, Any]],
) -> tuple[str, ...] | None:
    if tool_results:
        return None
    from agronomy_agent.tool_planner import plan_tools

    expected_plan = plan_tools(question)
    if (
        expected_plan.status != "clarification_required"
        or _canonical_json(dict(tool_plan or {})) != _canonical_json(expected_plan.to_dict())
    ):
        return None
    invocation = _validated_calculator_invocation(
        question,
        tool_plan,
        expected_plan_status="clarification_required",
        expected_invocation_status="clarification_required",
    )
    if invocation is None:
        return None
    missing_inputs = tuple(str(value).strip() for value in invocation.get("missing_inputs") or ())
    if not missing_inputs or any(not value for value in missing_inputs):
        return None
    expected = "To calculate this, provide " + ", ".join(missing_inputs) + "."
    if str((tool_plan or {}).get("clarification") or "") != expected:
        return None
    return missing_inputs


def _field_scope_values(field_context: Mapping[str, Any] | None, key: str) -> tuple[str, ...]:
    if not isinstance(field_context, Mapping):
        return ()
    value = field_context.get(key)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_normalized_scope(item) for item in value if _normalized_scope(item))
    normalized = _normalized_scope(value)
    return (normalized,) if normalized else ()


def _scope_matches_question_or_field(
    value: Any,
    question: str,
    field_context: Mapping[str, Any] | None,
    field_key: str,
) -> bool:
    normalized = _normalized_scope(value)
    if not normalized:
        return False
    normalized_question = _normalized_scope(question)
    if f" {normalized} " in f" {normalized_question} ":
        return True
    return normalized in _field_scope_values(field_context, field_key)


def _valid_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "").casefold()))


def _valid_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value or ""))
    except ValueError:
        return False
    return True


def _authority_receipt_identifier(receipt: Mapping[str, Any]) -> str:
    return _identifier(
        "authority_receipt",
        {key: value for key, value in receipt.items() if key != "receipt_id"},
    )


def _validated_label_authority_receipt(
    question: str,
    receipt: Mapping[str, Any],
    *,
    field_context: Mapping[str, Any] | None,
) -> bool:
    expected_top_level = {
        "schema_version",
        "receipt_id",
        "authority",
        "status",
        "freshness_status",
        "question_sha256",
        "field_snapshot_sha256",
        "applicability_complete",
        "applicability",
        "authority_record",
    }
    applicability = receipt.get("applicability")
    authority_record = receipt.get("authority_record")
    if (
        set(receipt) != expected_top_level
        or receipt.get("receipt_id") != _authority_receipt_identifier(receipt)
        or not isinstance(applicability, Mapping)
        or set(applicability)
        != {
            "schema_version",
            "product",
            "crop",
            "jurisdiction",
            "target",
            "site",
            "use_pattern",
            "application_method",
        }
        or applicability.get("schema_version") != LABEL_APPLICABILITY_SCHEMA_VERSION
        or not isinstance(authority_record, Mapping)
        or set(authority_record)
        != {
            "schema_version",
            "registration_id",
            "label_id",
            "label_sha256",
            "effective_date",
            "verified_current_on",
        }
        or authority_record.get("schema_version") != LABEL_AUTHORITY_RECORD_SCHEMA_VERSION
        or not _valid_sha256(authority_record.get("label_sha256"))
        or not _valid_iso_date(authority_record.get("effective_date"))
        or not _valid_iso_date(authority_record.get("verified_current_on"))
    ):
        return False

    as_of_date = str((field_context or {}).get("authority_as_of_date") or date.today().isoformat())
    if not _valid_iso_date(as_of_date):
        return False
    if (
        authority_record.get("verified_current_on") != as_of_date
        or date.fromisoformat(str(authority_record["effective_date"])) > date.fromisoformat(as_of_date)
    ):
        return False

    applicability_scopes = (
        ("product", "product_scope"),
        ("crop", "crop_scope"),
        ("jurisdiction", "jurisdiction_scope"),
        ("target", "target_scope"),
        ("site", "site_scope"),
        ("use_pattern", "use_pattern_scope"),
        ("application_method", "application_method_scope"),
    )
    if not all(
        _scope_matches_question_or_field(applicability.get(key), question, field_context, field_key)
        for key, field_key in applicability_scopes
    ):
        return False
    return all(
        (
            _scope_matches_question_or_field(
                authority_record.get("registration_id"),
                question,
                field_context,
                "registration_scope",
            ),
            _scope_matches_question_or_field(
                authority_record.get("label_id"),
                question,
                field_context,
                "label_scope",
            ),
            _scope_matches_question_or_field(
                authority_record.get("label_sha256"),
                question,
                field_context,
                "label_scope",
            ),
            _scope_matches_question_or_field(
                authority_record.get("effective_date"),
                question,
                field_context,
                "effective_date_scope",
            ),
        )
    )


def validated_authority_receipts(
    question: str,
    receipts: Sequence[Mapping[str, Any] | str],
    *,
    field_context: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    accepted: list[str] = []
    expected_field_sha = str((field_context or {}).get("field_snapshot_sha256") or "").strip()
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        authority = str(receipt.get("authority") or "").strip()
        if (
            receipt.get("schema_version") != AUTHORITY_RECEIPT_SCHEMA_VERSION
            or authority not in {"current_jurisdiction_specific_label", "qualified_local_decision_authority"}
            or str(receipt.get("status") or "").casefold() not in {"validated", "verified"}
            or str(receipt.get("freshness_status") or "").casefold()
            not in {"current", "current_verified", "live_verified"}
            or receipt.get("question_sha256") != _sha256_text(question)
            or receipt.get("applicability_complete") is not True
            or not isinstance(receipt.get("applicability"), Mapping)
        ):
            continue
        receipt_field_sha = str(receipt.get("field_snapshot_sha256") or "").strip()
        if (expected_field_sha and not _valid_sha256(expected_field_sha)) or (
            receipt_field_sha and not _valid_sha256(receipt_field_sha)
        ):
            continue
        if expected_field_sha:
            if receipt_field_sha != expected_field_sha:
                continue
        elif receipt_field_sha:
            continue
        if authority == "current_jurisdiction_specific_label":
            if not _validated_label_authority_receipt(
                question,
                receipt,
                field_context=field_context,
            ):
                continue
        if authority == "qualified_local_decision_authority" and (
            not expected_field_sha or not _representative_sample_complete(field_context)
        ):
            continue
        accepted.append(authority)
    return tuple(dict.fromkeys(accepted))


def rule_pack_catalog() -> tuple[dict[str, Any], ...]:
    return tuple(pack.to_dict() for pack in DOMAIN_RULE_PACKS)


def matching_rule_pack(question: str) -> DomainRulePack:
    # Regulated actions take precedence over every wording form, including
    # apparent arithmetic that actually asks the system to choose or authorize
    # a product rate. A ready typed tool result still wins later because that
    # path used supplied inputs only.
    precedence = (
        "regulated.product_action.v1",
        "consequential.action_authority.v1",
        "calculation.supplied_inputs.v1",
        "field.decision.v1",
        "conceptual.explanation.v1",
    )
    by_id = {pack.pack_id: pack for pack in DOMAIN_RULE_PACKS}
    for pack_id in precedence:
        pack = by_id[pack_id]
        if pack.matches(question):
            if pack_id == "regulated.product_action.v1" and (
                _is_fertilizer_only_request(question) or _is_non_regulated_rate_request(question)
            ):
                continue
            if pack_id == "regulated.product_action.v1" and not _regulated_pack_claim_intent(question):
                continue
            return pack
    return DomainRulePack(
        pack_id="general.bounded_assistance.v1",
        version="1.0.0",
        description="Default bounded agronomic assistance.",
        matcher_patterns=(),
        intents=("inform",),
        risk="low",
        required_capabilities=(),
        namespaces=("general_agronomy",),
        evidence_authority="bounded_general_knowledge",
        validator_policies=("direct_answer_present", "calibrated_uncertainty"),
        regression_cases=("general_question",),
    )


def assess_answerability(
    question: str,
    *,
    route: Any | None = None,
    tool_plan: Mapping[str, Any] | None = None,
    tool_results: Sequence[Mapping[str, Any]] = (),
    field_context: Mapping[str, Any] | None = None,
    available_authorities: Sequence[Mapping[str, Any] | str] = (),
) -> AnswerabilityDecision:
    pack = matching_rule_pack(question)
    route_risk = str(getattr(route, "risk_level", "") or pack.risk)

    if _UNSAFE_BYPASS_RE.search(question):
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.REFUSE_UNSAFE_ACTION,
            "request_attempts_to_bypass_mandatory_safety_or_authority",
            "universal.safety.v1",
            "high",
            failed_claim="permission to bypass a mandatory safety or legal constraint",
            response_text=(
                "I can’t help bypass a label, safety requirement, or legal restriction. "
                "I can help interpret the current applicable requirement or plan a compliant next step."
            ),
        )

    if validated_deterministic_tool_execution(question, tool_plan, tool_results):
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.ANSWER_DIRECTLY,
            "validated_deterministic_tool_result_available",
            "calculation.supplied_inputs.v1",
            "low_arithmetic",
        )
    validated_missing = validated_deterministic_tool_clarification(question, tool_plan, tool_results)
    if validated_missing is not None:
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.ASK_ONE_DISCRIMINATING_QUESTION,
            "calculator_requires_explicit_supplied_input",
            "calculation.supplied_inputs.v1",
            "low_arithmetic",
            missing_inputs=validated_missing,
            failed_claim="numeric result cannot be computed without the missing supplied quantity",
            response_text=str((tool_plan or {}).get("clarification") or "").strip() or None,
        )

    if _regulated_route_backstop(question, route) and pack.pack_id != "consequential.action_authority.v1":
        pack = next(value for value in DOMAIN_RULE_PACKS if value.pack_id == "regulated.product_action.v1")
        route_risk = "regulated"

    accepted_authorities = set(
        validated_authority_receipts(
            question,
            available_authorities,
            field_context=field_context,
        )
    )

    if pack.pack_id == "conceptual.explanation.v1":
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.ANSWER_DIRECTLY,
            "benign_explanation_does_not_require_field_action_authority",
            pack.pack_id,
            "low",
        )

    if (
        pack.pack_id == "regulated.product_action.v1"
        and pack.evidence_authority not in accepted_authorities
    ):
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.REQUIRE_AUTHORITY,
            "regulated_action_claim_lacks_current_local_authority",
            pack.pack_id,
            "regulated",
            failed_claim="product permission, rate, timing, or restriction",
            required_authority=pack.evidence_authority,
            response_text=(
                "I can explain the decision factors, but I can’t authorize a product, rate, or timing "
                "without the current jurisdiction-specific label for the exact crop, target, site, and use."
            ),
        )

    if (
        pack.pack_id == "consequential.action_authority.v1"
        and pack.evidence_authority not in accepted_authorities
    ):
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.REQUIRE_AUTHORITY,
            "consequential_field_action_lacks_representative_evidence_or_named_authority",
            pack.pack_id,
            "high",
            failed_claim="exact, certified, or irreversible field action",
            required_authority=pack.evidence_authority,
            response_text=(
                "I can help lay out the decision factors and next measurements, but I can’t make or certify "
                "that consequential field action without representative field evidence and the named qualified authority."
            ),
        )

    if pack.pack_id == "field.decision.v1":
        if _DIRECT_RATE_RE.search(question) and not _representative_sample_complete(field_context):
            return AnswerabilityDecision(
                ANSWERABILITY_POLICY_VERSION,
                AnswerabilityState.ASK_ONE_DISCRIMINATING_QUESTION,
                "field_rate_request_missing_decision_inputs",
                pack.pack_id,
                route_risk,
                missing_inputs=("the current representative soil or tissue result and its method/units",),
                failed_claim="field-specific rate",
                response_text=(
                    "What is the current representative soil or tissue result, including the test method and units? "
                    "That is the first input needed to bound a field-specific rate."
                ),
            )
        return AnswerabilityDecision(
            ANSWERABILITY_POLICY_VERSION,
            AnswerabilityState.ANSWER_WITH_BOUNDED_UNCERTAINTY,
            "field_decision_can_preserve_differential_and_low_regret_next_step",
            pack.pack_id,
            route_risk,
        )

    return AnswerabilityDecision(
        ANSWERABILITY_POLICY_VERSION,
        AnswerabilityState.ANSWER_WITH_BOUNDED_UNCERTAINTY,
        "general_bounded_assistance",
        pack.pack_id,
        route_risk,
    )
