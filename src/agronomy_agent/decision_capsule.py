from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class _DomainRule:
    name: str
    primary_intent: str
    signals: tuple[tuple[str, int], ...]
    evidence_anchors: tuple[tuple[str, ...], ...]
    retrieval_terms: tuple[str, ...]
    incompatible_patterns: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DecisionCapsule:
    """Small, observable state for preserving the user's decision through RAG."""

    question: str
    domain: str
    action: str
    crop: str | None
    decision_clause: str
    management_objects: tuple[str, ...]
    retrieval_topics: tuple[str, ...]
    retrieval_terms: tuple[str, ...]
    primary_intent: str
    confidence: float
    incompatible_patterns: tuple[tuple[str, str], ...] = ()

    @property
    def is_specific(self) -> bool:
        return self.domain != "general" and self.confidence >= 0.55

    @property
    def retrieval_query(self) -> str:
        additions = [term for term in self.retrieval_terms if term.lower() not in self.question.lower()]
        return " ".join((self.question, *additions[:8])).strip()

    def prompt_block(self) -> str:
        objects = ", ".join(self.management_objects) or "the named field decision"
        domain_guidance = {
            "fall_banded_nitrogen": (
                "- For a fall-nitrogen comparison, cover the conditions that change loss risk: soil temperature, "
                "nitrogen form or transformation, spring saturation and drainage, and band placement. Distinguish "
                "those risks from the spring seedbed-moisture tradeoff.\n"
            ),
            "high_p_starter_decision": (
                "- For high soil-test phosphorus, separate expected crop response and maintenance economics from "
                "seed-placement safety. High Olsen P lowers expected response; it does not by itself establish a "
                "universally safe starter rate. Bind any placement statement to the evidence conditions such as "
                "rate, opener or spread, row spacing, and soil moisture.\n"
            ),
        }.get(self.domain, "")
        return (
            "Decision focus:\n"
            f"- Resolve: {self.decision_clause}\n"
            f"- Keep the answer centered on: {objects}.\n"
            f"{domain_guidance}"
            "- Answer that decision first, then give only the observations and constraints that change it. "
            "Do not name or describe this instruction in the answer, and do not switch crop or production system."
        )

    def evidence_alignment(self, text: str) -> float:
        lower = text.lower()
        if self.domain == "general":
            return 0.0
        anchor_hits = sum(any(re.search(pattern, lower, re.IGNORECASE) for pattern in group) for group in _anchor_groups(self.domain))
        incompatible_hits = sum(bool(re.search(pattern, lower, re.IGNORECASE)) for _, pattern in self.incompatible_patterns)
        crop_hit = bool(self.crop and re.search(rf"\b{re.escape(self.crop)}s?\b", lower))
        return float(2.0 * anchor_hits + crop_hit - 2.5 * incompatible_hits)

    def classify_evidence(self, text: str) -> tuple[str, str] | None:
        lower = text.lower()
        for reason, pattern in self.incompatible_patterns:
            if re.search(pattern, lower, re.IGNORECASE):
                return "distractor", reason
        if self.is_specific and self.evidence_alignment(lower) >= 3.0:
            return "decisive", f"{self.domain}_decision_evidence"
        return None

    def answer_violations(self, answer: str) -> tuple[str, ...]:
        if not self.is_specific:
            return ()
        lower = answer.lower()
        violations: list[str] = []
        groups = _anchor_groups(self.domain)
        if groups and not any(any(re.search(pattern, lower, re.IGNORECASE) for pattern in group) for group in groups):
            violations.append("decision_capsule_anchor_missing")
        for reason, pattern in self.incompatible_patterns:
            if re.search(pattern, lower, re.IGNORECASE):
                violations.append(reason)
        if self.domain == "produce_safety":
            universal_requirement = bool(
                re.search(
                    r"\b(?:hold|segregate)\b[^.]{0,45}\bimmediately\b|"
                    r"\bmust\b[^.]{0,55}\b(?:hold|segregate|obtain|test|sample)\b",
                    lower,
                )
            )
            requirement_qualified = bool(
                re.search(
                    r"\b(?:when|as|if) required\b[^.]{0,120}\b(?:plan|authority|buyer|requirement)\b|"
                    r"\b(?:plan|authority|buyer|requirement)\b[^.]{0,120}\b(?:requires?|mandates?)\b",
                    lower,
                )
            )
            if universal_requirement and not requirement_qualified:
                violations.append("produce_safety_requirement_overstated")
        if self.domain == "high_p_starter_decision":
            categorical_seed_safety = bool(
                re.search(
                    r"\b(?:a )?low rate of seed[- ]placed phosphorus is safe\b|"
                    r"\bno seed[- ]placed phosphorus is safe\b",
                    lower,
                )
            )
            placement_conditions = bool(
                re.search(r"\b(?:opener|spread|soil moisture|fertilizer product|product and rate)\b", lower)
            )
            if categorical_seed_safety and not placement_conditions:
                violations.append("seed_placed_phosphorus_safety_overstated")
        if re.search(r"\bstatistically similar\b", self.question, re.IGNORECASE) and re.search(
            r"\bstatistically (?:different|separated)\b|\bsignificantly (?:different|higher|lower)\b",
            answer,
            re.IGNORECASE,
        ):
            violations.append("stated_statistical_premise_reversed")
        return tuple(dict.fromkeys(violations))

    def as_record(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "action": self.action,
            "crop": self.crop,
            "decision_clause": self.decision_clause,
            "management_objects": list(self.management_objects),
            "retrieval_topics": list(self.retrieval_topics),
            "retrieval_terms": list(self.retrieval_terms),
            "primary_intent": self.primary_intent,
            "confidence": self.confidence,
        }


_DOMAIN_RULES: tuple[_DomainRule, ...] = (
    _DomainRule(
        name="clubroot_containment",
        primary_intent="plant_health",
        signals=(
            (r"\bclubroot\b", 7),
            (r"\b(?:swollen roots?|galls?|dying patch)\b", 4),
            (r"\b(?:approach|entrance|what do I do|today|contain|sanitation)\b", 3),
            (r"\b(?:soil[- ]movement|precautions?|restrict\w* traffic|equipment clean\w*)\b", 4),
        ),
        evidence_anchors=(
            (r"\bclubroot\b", r"\bswollen roots?\b", r"\bgalls?\b"),
            (r"\bcontain", r"\bmark (?:the )?patch\b", r"\brestrict (?:traffic|movement)\b"),
            (r"\bclean(?:ing)? (?:soil|equipment|machinery)\b", r"\bsanitation\b"),
            (r"\brepresentative sample\b", r"\bconfirm", r"\bdiagnostic"),
        ),
        retrieval_terms=(
            "clubroot swollen roots field confirmation",
            "clubroot containment restrict soil movement",
            "clubroot equipment cleaning sanitation",
            "mark patch representative sample",
        ),
        incompatible_patterns=(("clubroot_action_delayed_until_confirmation", r"\bdelay(?:ing)? any immediate field action\b"),),
    ),
    _DomainRule(
        name="fall_banded_nitrogen",
        primary_intent="fertility_rate",
        signals=(
            (r"\bfall[- ](?:banded|applied)\b[^.]{0,45}\bnitrogen\b|\bnitrogen\b[^.]{0,45}\bfall[- ](?:banded|applied)\b", 8),
            (r"\b(?:spring application|spring banded|poor bet|compared with spring)\b", 4),
            (r"\b(?:saturat|drainage|soil temperature|loss risk|denitrif)\w*\b", 2),
        ),
        evidence_anchors=(
            (r"\bfall[- ](?:banded|applied)\b", r"\bspring banded\b"),
            (r"\bsoil temperature\b", r"\bnitrification\b", r"\bammonium\b", r"\bnitrate\b"),
            (r"\bsaturat", r"\bdrainage\b", r"\bdenitrif", r"\bover[- ]winter loss\b"),
            (r"\bband(?:ed|ing)\b", r"\bbroadcast\b", r"\bplacement\b"),
        ),
        retrieval_terms=(
            "fall-applied nitrogen risks benefits",
            "fall-banded spring-banded nitrogen",
            "spring saturation drainage denitrification",
            "soil temperature nitrogen form placement",
        ),
        incompatible_patterns=(("fall_n_sulphur_distractor", r"\bsulphur fertilizer application\b|\bsulfur deficiency\b"),),
    ),
    _DomainRule(
        name="high_p_starter_decision",
        primary_intent="fertility_rate",
        signals=(
            (r"\b(?:high|very high)\b[^.]{0,35}\b(?:Olsen P|soil[- ]test phosphorus|soil P)\b|\bOlsen P\b[^.]{0,35}\bhigh\b", 7),
            (r"\b(?:starter phosphorus|starter P|seed[- ]placed phosphorus)\b", 5),
            (r"\b(?:insurance|decide that pass|soybeans?)\b", 2),
        ),
        evidence_anchors=(
            (r"\bOlsen\b", r"\bsoil[- ]test P\b", r"\bresponse category\b", r"\blocal calibration\b"),
            (r"\bprobability (?:and degree )?of response\b", r"\bresponse decreases?\b", r"\bmaintenance\b", r"\bcrop removal\b"),
            (r"\bseed[- ]placed phosphorus\b", r"\bseed safety\b", r"\bstand reduction\b"),
            (r"\brow width\b", r"\bopener\b", r"\bseed[- ]fertilizer separation\b", r"\bsoil moisture\b"),
        ),
        retrieval_terms=(
            "high Olsen phosphorus response probability",
            "soybean starter phosphorus seed safety",
            "seed-placed phosphorus row width stand reduction",
            "local calibration crop removal maintenance",
        ),
        incompatible_patterns=(("jumpstart_substituted_for_starter_p_decision", r"\bjumpstart\b"),),
    ),
    _DomainRule(
        name="ambiguous_product_followup",
        primary_intent="product_label",
        signals=(
            (
                r"\b(?:same rate|go at the same rate|same (?:insecticide|herbicide|fungicide|product|spray|treatment))\b",
                7,
            ),
            (r"\bafter (?:the )?rain\b", 3),
            (r"\b(?:product|target|label)\b", 1),
        ),
        evidence_anchors=(
            (r"\bexact product\b", r"\bfull product name\b", r"\bregistration number\b"),
            (r"\btarget (?:pest|weed|disease)\b", r"\bcrop stage\b", r"\bprior application\b"),
            (r"\brain timing\b", r"\brainfast", r"\bcurrent label\b"),
            (r"\bdo not (?:apply|repeat|assume)\b", r"\bcannot confirm (?:the )?(?:rate|timing)\b"),
        ),
        retrieval_terms=("current product label", "rainfast timing", "exact product and target", "prior application record"),
        incompatible_patterns=(("unsupported_same_rate_permission", r"\bcan still apply (?:the )?same rate\b"),),
    ),
    _DomainRule(
        name="plant_health_diagnostic",
        primary_intent="plant_health",
        signals=(
            (r"\b(?:stripe rust|stem rust|leaf rust|clubroot|blackleg|sclerotinia|ascochyta|anthracnose|root rot|leaf spot|powdery mildew|downy mildew|blight)\b", 6),
            (r"\b(?:lesions?|pustules?|galls?|sporulation|mycelium)\b", 4),
            (r"\b(?:disease|pathogen|fungicide)\b", 3),
            (r"\b(?:confirm|distinguish|differentiate|diagnos\w*)\b", 2),
        ),
        evidence_anchors=(
            (r"\bsymptoms?\b", r"\bsigns?\b", r"\blesions?\b", r"\bpustules?\b", r"\bgalls?\b"),
            (r"\bfield pattern\b", r"\bdistribution\b", r"\baffected and normal\b"),
            (r"\bcrop stage\b", r"\bweather\b", r"\bleaf wetness\b", r"\bvariety\b", r"\bresistance\b"),
            (r"\bdiagnostic (?:sample|lab)\b", r"\brepresentative sample\b", r"\bconfirmation\b"),
            (r"\bcurrent (?:PMRA )?label\b", r"\bscouting\b", r"\beconomic return\b", r"\btreatment threshold\b"),
        ),
        retrieval_terms=(
            "crop disease differential symptoms signs field pattern",
            "crop stage weather susceptibility disease risk",
            "representative diagnostic sample confirmation",
            "current PMRA label treatment economics",
        ),
    ),
    _DomainRule(
        name="crop_stress_differential",
        primary_intent="fertility_diagnostic",
        signals=(
            (r"\b(?:pale|yellow(?:ing)?|chlorosis|stunt\w*|patchy|poor stand|stand loss)\b", 4),
            (
                r"\buneven\b[^.]{0,35}\b(?:crop|stand|growth|emergence)\b|"
                r"\b(?:crop|corn|wheat|canola|soybeans?|potato(?:es)?)\b[^.]{0,20}\buneven\b",
                4,
            ),
            (r"\b(?:field read|agronomic read|what matters|what should|what do|diagnos\w*|cause|evidence)\b", 2),
            (r"\b(?:cool|wet|heavy rain|waterlog\w*|poor drainage)\b", 1),
        ),
        evidence_anchors=(
            (r"\b(?:pale|yellow(?:ing)?|chlorosis|stunt\w*|patchy|uneven)\b",),
            (r"\bfield pattern\b", r"\baffected and normal\b", r"\bslope position\b"),
            (r"\bsul(?:f|ph)ur deficiency\b", r"\bnitrogen deficiency\b", r"\byoung leaves\b", r"\bolder leaves\b"),
            (r"\broots?\b", r"\bwetness\b", r"\bdrainage\b", r"\bcompaction\b", r"\bestablishment\b"),
            (r"\bsoil (?:test|sample)\b", r"\btissue (?:test|sample)\b", r"\bplant samples?\b"),
        ),
        retrieval_terms=(
            "crop stress differential field pattern",
            "sulfur versus nitrogen young older leaves",
            "rooting wetness drainage compaction",
            "affected and normal soil tissue samples",
        ),
    ),
    _DomainRule(
        name="produce_safety",
        primary_intent="crop_management",
        signals=(
            (r"\b(?:crop[- ]contact|preharvest|agricultural)[- ]water\b|\bwater intake\b", 4),
            (r"\b(?:produce|food)[- ]safety\b", 3),
            (r"\b(?:livestock|animal|manure)\b[^.]{0,90}\b(?:upstream|water|intake|source)\b", 3),
            (r"\bwash(?:ing)?\b[^.]{0,80}\b(?:harvest|safe|water|concern)\b", 2),
        ),
        evidence_anchors=(
            (r"\bcrop[- ]contact water\b", r"\bagricultural water\b", r"\bwater source\b"),
            (r"\bproduce[- ]safety\b", r"\bfood[- ]safety\b", r"\bcontaminat"),
            (r"\bhold\b", r"\bsegregat", r"\bdiscontinue\b", r"\bisolat"),
            (r"\bwash", r"\bharvest"),
        ),
        retrieval_terms=("produce safety agricultural water", "changed water source hazard", "hold segregate harvest", "postharvest washing limitation"),
        incompatible_patterns=(("produce_safety_grain_template_drift", r"\b(?:grain moisture|kernel damage|ear mold|aeration|grain drying|mycotoxin)\b"),),
    ),
    _DomainRule(
        name="transplant_establishment",
        primary_intent="crop_management",
        signals=(
            (r"\btransplants?\b", 5),
            (r"\broot[- ]bound\b|\broot ball\b|\bhardening\b|\btrays?\b", 4),
            (r"\b(?:plant|establish)\w*\b[^.]{0,80}\b(?:heat|hot|wind|starter fertilizer)\b", 2),
        ),
        evidence_anchors=(
            (r"\btransplant", r"\broot[- ]bound\b", r"\broot ball\b"),
            (r"\bharden", r"\bplant quality\b", r"\bcull\b", r"\bsegregat"),
            (r"\bsoil moisture\b", r"\birrigat", r"\bheat\b", r"\bweather\b"),
            (r"\bstarter fertilizer\b", r"\broot[- ]zone EC\b", r"\bmedia EC\b"),
        ),
        retrieval_terms=("vegetable transplant quality", "root-bound root ball", "hardening transplant shock", "hot weather establishment irrigation"),
        incompatible_patterns=(("transplant_decision_reduced_to_fertility", r"\bnutrient diagnosis\b[^.]{0,160}\b(?:soil test|tissue test)\b(?![\s\S]{0,160}\btransplant)"),),
    ),
    _DomainRule(
        name="seed_treatment",
        primary_intent="seed_treatment",
        signals=(
            (r"\bseed[- ]treat(?:ment|ed)\b|\btreated[- ]seed\b|\bseed[- ]applied\b", 4),
            (r"\b(?:insecticide|fungicide)[- ]treated\b[^.]{0,35}\bseed\b", 5),
            (r"\bseed\b[^.]{0,35}\b(?:insecticide|fungicide)[- ]treated\b", 5),
            (r"\b(?:buy|purchase|order|discount|worthwhile|value)\b[^.]{0,100}\b(?:treated|treatment)\b", 2),
        ),
        evidence_anchors=(
            (r"\bseed treatment\b", r"\btreated seed\b", r"\bseed[- ]applied\b"),
            (r"\bpest history\b", r"\bearly[- ]insect\b", r"\btarget pests?\b", r"\bseedling loss\b"),
            (r"\bplanting conditions\b", r"\bsoil temperature\b", r"\bcool[- ]wet\b"),
            (r"\bcost\b", r"\bvalue\b", r"\bavoided loss\b", r"\buntreated\b"),
        ),
        retrieval_terms=("seed treatment risk decision", "early insect loss history", "planting conditions seedling protection", "treated versus untreated seed economics"),
        incompatible_patterns=(("seed_treatment_shifted_to_foliar_ipm", r"\b(?:whole[- ]canopy defoliation|foliar spray|spray from pest presence|insect count per plant)\b"),),
    ),
    _DomainRule(
        name="planting_establishment",
        primary_intent="crop_management",
        signals=(
            (r"\bseed[- ]zone\b|\bseedbed\b|\bplanting depth\b|\btrafficability\b|\bsidewall smearing\b", 4),
            (r"\b(?:plant|planting)\w*\b[^.]{0,90}\b(?:cold|wet|rain|surface|emergence)\b", 3),
            (r"\b(?:cold|wet)\b[^.]{0,60}\b(?:soil|seed zone|planting)\b", 2),
        ),
        evidence_anchors=(
            (r"\bseed[- ]zone\b", r"\bplanting depth\b", r"\bseedbed\b"),
            (r"\btrafficab", r"\bcompaction\b", r"\bsidewall\b", r"\bfurrow\b"),
            (r"\bsoil temperature\b", r"\bcold\b", r"\bsoil moisture\b", r"\bwet\b"),
            (r"\bforecast\b", r"\brain\b", r"\bdelay\b", r"\brecheck\b", r"\bemergence\b"),
        ),
        retrieval_terms=("seedbed fitness planting", "seed-zone temperature moisture", "wet soil compaction sidewall smearing", "emergence risk short forecast"),
        incompatible_patterns=(("planting_decision_replaced_by_abstention", r"\bevidence is not specific enough\b|\badd the field observations\b"),),
    ),
)


def build_decision_capsule(question: str, *, crop: str | None = None) -> DecisionCapsule:
    lower = " ".join(question.lower().split())
    scored: list[tuple[int, int, _DomainRule]] = []
    for order, rule in enumerate(_DOMAIN_RULES):
        score = sum(weight for pattern, weight in rule.signals if re.search(pattern, lower, re.IGNORECASE))
        scored.append((score, -order, rule))
    score, _, rule = max(scored, key=lambda item: (item[0], item[1]))
    if score < 4:
        return DecisionCapsule(
            question=question,
            domain="general",
            action=_decision_action(lower),
            crop=crop,
            decision_clause=_decision_clause(question),
            management_objects=(),
            retrieval_topics=(),
            retrieval_terms=(),
            primary_intent="",
            confidence=0.0,
        )
    groups = rule.evidence_anchors
    objects = tuple(_display_anchor(group[0]) for group in groups)
    confidence = min(1.0, 0.45 + score / 14)
    return DecisionCapsule(
        question=question,
        domain=rule.name,
        action=_decision_action(lower),
        crop=crop,
        decision_clause=_decision_clause(question),
        management_objects=objects,
        retrieval_topics=_domain_topics(rule.name),
        retrieval_terms=rule.retrieval_terms,
        primary_intent=rule.primary_intent,
        confidence=round(confidence, 3),
        incompatible_patterns=rule.incompatible_patterns,
    )


def _anchor_groups(domain: str) -> tuple[tuple[str, ...], ...]:
    return next((rule.evidence_anchors for rule in _DOMAIN_RULES if rule.name == domain), ())


def _domain_topics(domain: str) -> tuple[str, ...]:
    return {
        "plant_health_diagnostic": ("plant_health", "disease", "product", "crop_management"),
        "crop_stress_differential": ("fertility", "plant_health", "soil_water", "crop_management"),
        "produce_safety": ("crop_management", "soil_water", "produce_safety"),
        "transplant_establishment": ("crop_management", "transplant_establishment"),
        "seed_treatment": ("seed_treatment", "product", "insect"),
        "planting_establishment": ("crop_management", "soil_water", "planting_establishment"),
    }.get(domain, ())


def _decision_action(lower: str) -> str:
    patterns: tuple[tuple[str, str], ...] = (
        ("select_or_purchase", r"\b(?:buy|purchase|order|select|choose|discount|worthwhile)\b"),
        ("plant_or_establish", r"\b(?:plant|transplant|establish|replant)\w*\b"),
        ("harvest_or_hold", r"\b(?:harvest|hold|segregate|wash)\w*\b"),
        ("treat_or_apply", r"\b(?:treat|apply|spray|fertiliz)\w*\b"),
        ("diagnose", r"\b(?:diagnos|identify|cause|symptom)\w*\b"),
        ("interpret", r"\b(?:interpret|mean|enough reason|substitute)\b"),
    )
    return next((name for name, pattern in patterns if re.search(pattern, lower)), "advise")


def _decision_clause(question: str) -> str:
    text = " ".join(question.split())
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text) if part]
    return (sentences[-1] if sentences else text)[:260]


def _display_anchor(pattern: str) -> str:
    value = re.sub(r"\\b|\(\?:|\(|\)|\?|\*|\+", "", pattern)
    value = value.replace("[- ]", " ").replace("\\", "")
    return value.split("|")[0].strip()


def merge_topics(*values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for group in values for item in group if str(item).strip()))
