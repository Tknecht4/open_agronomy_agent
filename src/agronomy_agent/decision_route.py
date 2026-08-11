from __future__ import annotations

import re
from dataclasses import dataclass

from agronomy_agent.decision_capsule import DecisionCapsule, build_decision_capsule
from agronomy_agent.query_context import analyze_query_context
from agronomy_agent.router import request_focus


_US_ONLY_SOURCE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("nass", r"\b(?:USDA )?NASS\b|\bQuick Stats\b|\bCensus of Agriculture\b"),
    ("cdl", r"\b(?:USDA )?(?:Cropland Data Layer|CDL)\b"),
    ("nrcs", r"\bNRCS\b|\bSSURGO\b|\bSoil Data Access\b"),
    ("openet", r"\bOpenET\b"),
)

_CANADA_SOURCE_ACKNOWLEDGMENTS = {
    "nass": r"\b(?:U\.?S\.?[- ]only|United States|not (?:a )?Canadian|does not (?:cover|provide).{0,40}Canad|Statistics Canada)\b",
    "cdl": r"\b(?:U\.?S\.?[- ]only|United States|not (?:a )?Canadian|does not (?:cover|include).{0,40}Canad|Annual Crop Inventory|AAFC)\b",
    "nrcs": r"\b(?:U\.?S\.?[- ]only|United States|not (?:a )?Canadian|does not (?:cover|include).{0,40}Canad|CanSIS|Canadian Soil Information Service|provincial soil)\b",
    "openet": r"\b(?:U\.?S\.?[- ]only|United States|not (?:a )?Canadian|does not (?:cover|include).{0,40}Canad|local (?:weather|ET|evapotranspiration))\b",
}

_NONGRAIN_CROPS = {"cotton", "potato", "sugar beet", "tomato"}
_INTEGRATED_SPECIALTY_CROPS = {"almond", "apple", "cucumber", "grape", "lettuce", "pepper", "spinach", "strawberry", "tomato"}
_DISEASE_ENTITY_RE = re.compile(
    r"\b(?:white mold|late blight|early blight|gray leaf spot|grey leaf spot|fusarium wilt|verticillium wilt|stripe rust|leaf rust|root rot)\b",
    re.IGNORECASE,
)

_CAPSULE_OVERRIDEABLE_DECISIONS = {
    "agronomic_advice",
    "conceptual",
    "crop_management",
    "fertility_diagnostic",
    "fertility_rate",
    "field_data",
    "plant_health",
    "product_label",
    "soil_water",
}


@dataclass(frozen=True)
class PremiseAnchor:
    """One decision premise that a committed answer must preserve."""

    name: str
    description: str
    patterns: tuple[str, ...]

    def is_present(self, answer: str) -> bool:
        return any(re.search(pattern, answer, re.IGNORECASE) for pattern in self.patterns)


@dataclass(frozen=True)
class DecisionRouteState:
    question: str
    decision: str
    crop: str | None
    country: str | None
    decisive_evidence: tuple[str, ...]
    constraints: tuple[str, ...]
    premise_anchors: tuple[PremiseAnchor, ...] = ()
    source_boundary: str | None = None
    capsule: DecisionCapsule | None = None

    def prompt_block(self) -> str:
        lines = [f"Decision control state: {self.decision}."]
        if self.crop:
            lines.append(f"Crop frame: {self.crop}.")
        if self.decisive_evidence:
            lines.append("Decisive evidence: " + "; ".join(self.decisive_evidence) + ".")
        if self.constraints:
            lines.append("Constraints: " + "; ".join(self.constraints) + ".")
        if self.premise_anchors:
            lines.append(
                "Must preserve: "
                + "; ".join(anchor.description for anchor in self.premise_anchors)
                + "."
            )
        if self.capsule and self.capsule.is_specific:
            lines.append(self.capsule.prompt_block())
        lines.append("Answer the decision directly. Do not expose this control state or turn it into a checklist.")
        return "\n".join(lines)

    def missing_premise_anchors(self, answer: str) -> tuple[str, ...]:
        return tuple(anchor.name for anchor in self.premise_anchors if not anchor.is_present(answer))

    def premise_coverage(self, answer: str) -> float | None:
        if not self.premise_anchors:
            return None
        missing = len(self.missing_premise_anchors(answer))
        return round((len(self.premise_anchors) - missing) / len(self.premise_anchors), 4)

    def premise_correction_answer(self) -> str | None:
        if self.country != "canada" or not self.source_boundary:
            return None
        if self.source_boundary == "nass":
            return (
                "USDA NASS Quick Stats and the USDA Census of Agriculture are United States sources; they do not provide Canadian county or provincial statistics. "
                "For a Canadian field, use Statistics Canada agricultural census or crop-production tables and, where appropriate, AAFC or provincial crop-insurance and extension data. Treat those regional statistics as context only, then compare them with the grower's field history, current crop condition, weather, and management records before changing the plan."
            )
        if self.source_boundary == "cdl":
            return (
                "The USDA Cropland Data Layer covers the United States and should not be presented as crop-history evidence for a Canadian field. Use the AAFC Annual Crop Inventory or another documented Canadian land-cover source, verify the field boundary and crop year, and treat mapped classes as uncertain screening evidence rather than a planting record. Compare the map with grower records before inferring rotation."
            )
        if self.source_boundary == "nrcs":
            return (
                "NRCS SSURGO and Soil Data Access are United States soil-survey sources and do not cover this Canadian field. Use CanSIS, a provincial soil survey, or another documented Canadian soil source. Treat the mapped unit as a prior, then ground-truth texture, drainage, restrictive layers, and current field condition before changing management."
            )
        if self.source_boundary == "openet":
            return (
                "OpenET should not be claimed as field coverage for this Canadian location. Use an available local evapotranspiration or weather source and pair it with root-zone soil moisture, rainfall and applied-water records, crop stage, and irrigation-system capacity. Regional or modeled ET remains context, not an irrigation prescription."
            )
        return None

    def answer_violations(self, answer: str) -> tuple[str, ...]:
        lower = answer.lower()
        violations: list[str] = []
        if self.decision == "clubroot_containment":
            confirmation = bool(re.search(r"\b(?:representative sample|diagnostic lab|confirm(?:ation)?)\b", lower))
            sanitation = bool(re.search(r"\b(?:clean|remove) soil\b[^.]{0,80}\b(?:equipment|machinery|boots?)\b|\bsanitation\b", lower))
            if not confirmation or not sanitation:
                violations.append("clubroot_today_actions_incomplete")
        if self.decision == "ambiguous_product_followup" and re.search(
            r"\b(?:should|must) hold off\b|\bdo not apply\b",
            lower,
        ) and not re.search(r"\b(?:cannot confirm|cannot determine|do not know)\b", lower):
            violations.append("missing_product_treated_as_automatic_hold")
        if self.country == "canada" and self.source_boundary:
            acknowledgment = _CANADA_SOURCE_ACKNOWLEDGMENTS[self.source_boundary]
            if not re.search(acknowledgment, answer, re.IGNORECASE):
                violations.append("source_coverage_premise_not_rejected")
        if self.crop == "corn" and re.search(r"\bboot(?:ing)?\b", lower):
            violations.append("crop_stage_biology_mismatch")
        if self.crop == "tomato" and re.search(r"\b[VR]\d{1,2}\b", answer):
            violations.append("crop_stage_biology_mismatch")
        if (
            self.crop == "soybean"
            and re.search(r"\blim(?:e|ing)\b", lower)
            and re.search(r"\biron deficiency chlorosis\b", lower)
            and re.search(r"\bprevent(?:s|ed|ing)?\b", lower)
        ):
            violations.append("crop_physiology_mismatch")
        if self.crop == "sorghum" and re.search(r"\bsorghum (?:is|as) (?:a )?c3 crop\b|\bc3 crop\b", lower):
            violations.append("crop_physiology_mismatch")
        if self.decision == "cold_wet_purple_corn" and re.search(
            r"(?<!not )\b(?:apply|needs?|requires?|add)\b[^.]{0,45}\bphosphorus\b[^.]{0,25}\b(?:immediately|right away|now)\b|"
            r"\bphosphorus\b[^.]{0,35}\b(?:apply|needed|required)\b[^.]{0,25}\b(?:immediately|right away|now)\b",
            lower,
        ):
            violations.append("transient_stress_treated_as_confirmed_deficiency")
        if self.decision == "soybean_idc" and re.search(
            r"\b(?:apply|add)\b[^.]{0,45}\b(?:iron|iron sulfate|lime)\b|"
            r"\blower (?:the )?soil ph\b|\belemental sulfur\b",
            lower,
        ):
            violations.append("unsupported_idc_remediation")
        if self.decision == "weed_seed_return_management" and re.search(
            r"\bmust\b[^.]{0,45}\b(?:remove|eliminate)\b[^.]{0,25}\ball\b|"
            r"\bremove all surviving\b|\bensure\b[^.]{0,40}\bnot re[- ]?infest",
            lower,
        ):
            violations.append("overstated_weed_control_certainty")
        if self.decision == "freeze_recovery" and re.search(
            r"\b(?:variety|hybrid) trials?\b|\bleast significant difference\b|\btrial coefficient of variation\b|\bLSD\b",
            answer,
            re.IGNORECASE,
        ):
            violations.append("domain_template_leakage")
        if self.decision == "fruit_set_diagnostic" and self.crop == "cucumber" and re.search(
            r"\bcucumbers? (?:are|is) self[- ]pollinat",
            lower,
        ):
            violations.append("crop_physiology_mismatch")
        if re.search(r"\blow ph\b", self.question, re.IGNORECASE) and re.search(
            r"\bcalcareous\b", self.question, re.IGNORECASE
        ) and not re.search(
            r"\b(?:unexpected|inconsistent|contradict|apparent|unusual)\b.{0,100}\b(?:calcareous|carbonate|sampling|horizon)\b|"
            r"\b(?:calcareous|carbonate)\b.{0,100}\b(?:unexpected|inconsistent|contradict|apparent|unusual)\b|"
            r"\b(?:verify|confirm)\b.{0,60}\b(?:whether|if)\b.{0,50}\b(?:calcareous|carbonate)\b",
            lower,
        ):
            violations.append("calcareous_low_ph_premise_unresolved")
        if re.search(r"\bglacial[- ]till\b", self.question, re.IGNORECASE) and re.search(
            r"\blower water[- ]holding capacity than (?:typical )?loess\b", lower
        ):
            violations.append("false_soil_property_generalization")
        if not re.search(r"\bhumid", self.question, re.IGNORECASE) and re.search(r"\bhigh humidity\b", lower):
            violations.append("unstated_weather_condition")
        if self.crop == "cotton" and re.search(r"\btexas high plains\b", self.question, re.IGNORECASE) and re.search(
            r"\b(?:soil is|soil is not|confirm.{0,25}soil is not) frozen\b", lower
        ):
            violations.append("climate_context_mismatch")
        if self.crop in _NONGRAIN_CROPS and self.decision == "harvest_storage" and re.search(
            r"\b(?:grain moisture|test weight|aeration|kernel damage|ear mold|grain drying)\b", lower
        ):
            violations.append("nongrain_storage_template_mismatch")
        if self.decision == "sweet_corn_harvest_timing" and re.search(
            r"\b(?:grain moisture|test weight|grain drying|drying capacity|bin storage|aeration|storage plan)\b",
            lower,
        ) and not re.search(
            r"\b(?:do not|not|never|rather than)\b[^.]{0,90}\b(?:grain moisture|grain drying|aeration|bin[- ]storage|storage plan)\b",
            lower,
        ):
            violations.append("sweet_corn_grain_template_mismatch")
        if self.decision == "greenhouse_substrate_irrigation" and re.search(
            r"\b(?:soil survey|map unit|tile maps?|tile drainage|field capacity|available water capacity|soil profile depth)\b",
            lower,
        ) and not re.search(
            r"\b(?:do not|not|never|rather than)\b[^.]{0,100}\b(?:field[- ]soil|soil survey|tile[- ]drainage|field capacity|available water capacity)\b",
            lower,
        ):
            violations.append("greenhouse_field_soil_template_mismatch")
        if self.decision == "fusarium_head_blight_risk" and re.search(
            r"\b(?:pest species|insect count|natural enemies|economic threshold)\b", lower
        ):
            violations.append("insect_template_substituted_for_fhb_risk")
        if self.decision == "fleabane_management" and re.search(
            r"\b(?:wind direction|gusts|inversion|rainfast|sensitive crops?|spray window)\b", lower
        ) and not re.search(r"\b(?:cohort|emergence|growth stage|resistance|forage|fleabane|horseweed)\b", lower):
            violations.append("application_weather_substituted_for_weed_plan")
        if self.decision == "seeding_depth_decision" and re.search(
            r"\b(?:plant now|delay planting|plant only the areas|trafficability)\b", lower
        ) and not re.search(r"\b(?:seed(?:ing)? depth|placement depth|depth to moisture|opener depth)\b", lower):
            violations.append("planting_window_substituted_for_seeding_depth")
        if self.decision == "sidedress_n_credit_reconciliation":
            lanes = (
                r"\bmanure\b[^.]{0,80}\b(?:analysis|credit|available|mineraliz)",
                r"\b(?:previous[- ]crop|legume|rotation)\b[^.]{0,80}\b(?:credit|nitrogen|N)\b",
                r"\b(?:soil nitrate|crop demand|yield potential|nitrogen status)\b",
                r"\b(?:timing|rain|loss risk|leaching|denitrification|sidedress window)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("sidedress_credit_reconciliation_missing")
            if re.search(r"\bgreater (?:alfalfa )?crown density\b[^.]{0,80}\blesser (?:nitrogen )?credit\b", lower):
                violations.append("previous_crop_credit_direction_reversed")
            if re.search(r"\b(?:peas?|pulse|legume)\b", self.question, re.IGNORECASE) and re.search(
                r"\b(?:consistent|fixed|automatic|known) (?:nitrogen )?(?:credit|contribution)\b",
                lower,
            ):
                violations.append("previous_crop_credit_overstated")
        if self.decision == "seed_row_fertilizer_safety":
            lanes = (
                r"\b(?:product|analysis|nutrient|fertilizer source)\b[^.]{0,80}\b(?:rate|amount|salt|ammonia|nitrogen|phosph)",
                r"\b(?:row spacing|seedbed utilization|opener|spread|band width|seed[- ]fertilizer separation)\b",
                r"\b(?:texture|moisture|organic matter|salinity|seedbed condition)\b",
                r"\b(?:current|provincial|local)\b[^.]{0,70}\b(?:seed[- ]row|fertilizer|safety table|guidance)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("seed_row_fertilizer_evidence_missing")
        if self.decision == "wet_area_drainage_differential":
            lanes = (
                r"\b(?:profile|horizon|mottle|gley|restrictive layer|root depth|rooting)\b",
                r"\b(?:water table|saturation duration|ponding duration|soil moisture by depth)\b",
                r"\b(?:topograph|inflow|run[- ]on|outlet|existing drainage|tile)\b",
                r"\b(?:affected|wet)\b[^.]{0,60}\b(?:normal|dry|healthy)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("drainage_differential_evidence_missing")
        if self.decision == "hail_disease_differential":
            hail = re.search(r"\b(?:tear|shred|bruise|break|impact|storm path|windward|hail scar)\w*\b", lower)
            disease = re.search(r"\b(?:expand|progress|spor|pustule|fruiting|ooze|signs?|lesion margin)\w*\b", lower)
            if not hail or not disease:
                violations.append("hail_and_disease_signs_not_separated")
        if self.decision == "corn_common_rust_differential":
            rust = re.search(r"\b(?:raised pustules?|powdery spores?|rub[- ]?off|orange[- ]brown spores?)\b", lower)
            alternatives = re.search(r"\b(?:spray (?:overlap|pattern|injury)|overlaps?|nutrient pattern|field (?:pattern|distribution)|lesion shape|progression)\b", lower)
            if not rust or not alternatives:
                violations.append("common_rust_differential_missing")
        if self.decision == "wild_oat_post_application":
            lanes = (
                r"\b(?:cohort|late emerg|density|patch distribution|weed stage)\w*\b",
                r"\b(?:product|rate|adjuvant|application timing|coverage|weather)\b",
                r"\b(?:herbicide group|mode of action|resistan|survivor pattern)\w*\b",
                r"\b(?:seed return|crop competition|harvest|current label|in[- ]crop window)\b",
            )
            application_record_present = bool(re.search(lanes[1], answer, re.IGNORECASE))
            if (
                sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3
                or not application_record_present
            ):
                violations.append("wild_oat_post_application_evidence_missing")
        if self.decision == "herbicide_injury_control_failure":
            lanes = (
                r"\b(?:overlap|skip|headland|spray pattern|boom section|treated and untreated)\b",
                r"\b(?:product|rate|adjuvant|tank mix|cleanout|application record|nozzle|coverage)\b",
                r"\b(?:weed identity|weed stage|late emergence|survivor pattern|resistan)\w*\b",
                r"\b(?:crop stage|symptom progression|recovery|current label|follow[- ]up restriction)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("herbicide_injury_and_control_failure_not_separated")
        if self.decision == "herbicide_injury_drift_differential":
            lanes = (
                r"\b(?:onset|timing|hours?|days?)\b[^.]{0,80}\b(?:spray|application|symptom)|\b(?:spray|application)\b[^.]{0,80}\b(?:onset|timing|hours?|days?)\b",
                r"\b(?:exact product|rate|tank mix|adjuvant|cleanout|spray record|application record|prior load)\b",
                r"\b(?:drift direction|field edge|edge gradient|downwind gradient|overlap|boom section|treated and untreated)\b",
                r"\b(?:wind|temperature|inversion|cold|rain|weather)\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if sum(hits) < 3 or not hits[1] or not hits[2]:
                violations.append("spray_injury_source_reconstruction_missing")
        if self.decision == "crop_stress_differential":
            lanes = (
                r"\b(?:field pattern|affected and normal|affected.{0,45}(?:healthy|normal)|strip|depression|low areas?)\b",
                r"\b(?:roots?|stand count|plant count|growing point|crown|establishment)\b",
                r"\b(?:waterlog|saturat|pond|wetness|drainage|compaction|oxygen)\w*\b",
                r"\b(?:fertilizer history|application history|manure|previous crop|nutrient credit|placement)\b",
                r"\b(?:soil|tissue|plant) (?:test|sample)\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if sum(hits) < 3 or not hits[0] or not hits[1]:
                violations.append("crop_stress_field_differential_incomplete")
        if self.decision == "weed_escape_management":
            lanes = (
                r"\b(?:identify|identity|species)\w*\b[^.]{0,60}\bweed|\bweed (?:identity|species)\b",
                r"\b(?:application record|product|rate|coverage|weather|resistan)\w*\b",
                r"\b(?:seed return|seed production|spread|seedbank)\b",
                r"\b(?:chemical and nonchemical|integrated|crop rotation|cultural|mechanical)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("weed_escape_decision_evidence_missing")
        if self.decision == "sulfur_nitrogen_differential":
            lanes = (
                r"\b(?:young|new) leaves?\b[^.]{0,80}\bsul(?:f|ph)ur|\bsul(?:f|ph)ur\b[^.]{0,80}\b(?:young|new) leaves?\b",
                r"\b(?:older|lower) leaves?\b[^.]{0,80}\bnitrogen|\bnitrogen\b[^.]{0,80}\b(?:older|lower) leaves?\b",
                r"\b(?:affected and normal|affected.{0,45}(?:healthy|normal)|field pattern)\b",
                r"\b(?:soil|tissue|plant) samples?\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if sum(hits) < 3 or not hits[0] or not hits[1]:
                violations.append("sulfur_nitrogen_differential_incomplete")
        if self.decision == "greenhouse_tomato_leaf_curl":
            lanes = (
                r"\b(?:temperature|humidity|VPD|radiation|air movement)\b",
                r"\b(?:substrate|root[- ]zone|irrigation|drainage|EC|pH|roots?)\b",
                r"\b(?:mites?|whiteflies?|aphids?|pests?|vectors?|insects?|arthropods?|pest scouting)\b",
                r"\b(?:virus|mosaic|biosecurity|herbicide|growth regulator|chemical exposure)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("tomato_leaf_curl_differential_missing")
        if self.decision == "winter_injury_differential":
            lanes = (
                r"\b(?:snow cover|exposure|low area|windward|winter temperature)\b",
                r"\b(?:cut buds?|cambium|crown|live tissue|viab)\w*\b",
                r"\b(?:wait for regrowth|prune to live|delay pruning|avoid (?:forcing|excess nitrogen)|recovery)\b",
                r"\b(?:lesion|canker|ooze|progression|diagnostic sample)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("winter_injury_confirmation_and_management_missing")
        if self.crop == "potato" and self.decision == "seed_quality" and re.search(
            r"\b(?:accelerated[- ]aging|germination percentage|seeding rate|existing stand|stand count|replanting)\b",
            lower,
        ) and not re.search(r"\b(?:seed tuber|seed piece|physiological age|sprout|cutting|healing)\b", lower):
            violations.append("potato_seed_biology_mismatch")
        if self.decision == "fungicide_decision" and re.search(r"\beconomic threshold\b|\binsect count", lower):
            if not re.search(r"\b(?:disease|diagnos|severity|incidence|susceptib|fungicide label|crop stage|weather risk)\b", lower):
                violations.append("insect_threshold_substituted_for_fungicide_logic")
        if self.decision == "plant_health_diagnostic" and re.search(r"\bstripe rust\b", self.question, re.IGNORECASE):
            lanes = (
                r"\b(?:yellow[- ]orange|linear) (?:stripes?|pustules?)\b|\bpowdery (?:spores?|pustules?)\b",
                r"\b(?:field pattern|distribution|canopy|upper leaves?|lower leaves?)\b",
                r"\b(?:crop stage|variety susceptib|recent (?:rain|weather)|leaf wetness|regional risk)\b",
                r"\b(?:representative (?:photo|sample)|diagnostic (?:sample|lab)|submit)\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if sum(hits) < 3 or not hits[0] or not hits[3]:
                violations.append("stripe_rust_confirmation_evidence_missing")
        if (
            self.decision == "plant_health_diagnostic"
            and self.crop == "potato"
            and re.search(r"\b(?:lesions?|disease program)\b", self.question, re.IGNORECASE)
        ):
            lanes = (
                r"\b(?:representative|fresh) (?:lesion|leaf|stem|diagnostic) sample\b|\bdiagnostic lab\b",
                r"\b(?:lesion margin|underside|upper and lower|incidence|severity|canopy position)\b",
                r"\b(?:crop stage|weather|leaf wetness|irrigation|field history)\b",
                r"\b(?:current (?:PMRA )?(?:product )?label|disease program|resistance group|provincial)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("potato_disease_program_evidence_missing")
        if (
            self.decision == "fungicide_decision"
            and self.crop == "potato"
            and re.search(r"\blate blight\b", self.question, re.IGNORECASE)
            and not re.search(r"\b(?:representative|fresh) (?:diagnostic )?sample\b|\bdiagnostic (?:sample|lab)\b", lower)
        ):
            violations.append("late_blight_confirmation_sample_missing")
        if self.decision == "freeze_recovery":
            lanes = (
                r"\b(?:crop stage|growing point|developing head|crown)\b",
                r"\b(?:new growth|warm(?:er)? (?:weather|conditions)|recovery period|revisit)\b",
                r"\b(?:firm|yellow[- ]green|water[- ]soaked|white|brown|soft)\b[^.]{0,55}\b(?:tissue|growing point|head|crown)\b",
                r"\b(?:stand count|plant count|tiller count|surviving stand|stand uniformity|representative stand)\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if sum(hits) < 3 or not hits[3]:
                violations.append("freeze_recovery_stand_evidence_missing")
        if self.decision == "seeding_rate_calculation":
            lanes = (
                r"\btarget (?:plant )?stand\b|\bplants? per (?:square metre|square meter|m2|m²)\b",
                r"\b(?:expected )?(?:mortality|field emergence|establishment percentage|establishment loss)\b",
                r"\b(?:germination|germ)\b",
                r"\b(?:thousand[- ]kernel weight|TKW|seed weight)\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if not all(hits):
                violations.append("seeding_rate_inputs_incomplete")
        if self.decision == "erosion_control_plan":
            lanes = (
                r"\b(?:flow path|concentrated flow|runoff|outlet|watercourse|slope length|slope grade)\b",
                r"\b(?:residue|cover|rotation|tillage direction|contour|perennial)\b",
                r"\b(?:rill|gully|sheet erosion|deposition|observed erosion|field observation)\b",
                r"\b(?:map|polygon|landscape unit)\b[^.]{0,100}\b(?:screening|prior|not (?:field )?truth|ground[- ]truth)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes) < 3:
                violations.append("erosion_plan_field_evidence_missing")
        if self.decision == "drought_nitrogen_adjustment":
            lanes = (
                r"\b(?:NASDI|regional|district|map|index)\b[^.]{0,100}\b(?:context|screening|prior|not field|does not establish)\b",
                r"\b(?:root[- ]zone|soil moisture|available water|rainfall|crop condition|rooting)\b",
                r"\b(?:soil nitrate|nitrogen already applied|application record|nitrogen budget|nutrient credit)\b",
                r"\b(?:yield response|response potential|uptake window|partial budget|economics?)\b",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in lanes]
            if sum(hits) < 3 or not hits[0] or not hits[1]:
                violations.append("drought_nitrogen_field_evidence_missing")
        if self.decision == "underspecified_spray":
            required = (
                r"\bcrop\b",
                r"\btarget (?:weed|pest|disease)\b",
                r"\b(?:crop|target) stage\b",
                r"\bjurisdiction\b",
                r"\bcurrent (?:PMRA )?(?:product )?label\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in required) < 4:
                violations.append("underspecified_spray_context_missing")
        if self.decision == "boundary_only_fertility_rate":
            required = (
                r"\bboundary\b[^.]{0,80}\b(?:not enough|cannot|does not)\b|\b(?:not enough|cannot)\b[^.]{0,80}\bboundary\b",
                r"\b(?:province|provincial|local calibration)\b",
                r"\b(?:yield goal|yield potential|crop demand)\b",
                r"\b(?:soil nitrate|soil test)\b",
                r"\b(?:manure|previous[- ]crop|fertilizer) credits?\b|\bprevious[- ]crop history\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in required) < 4:
                violations.append("boundary_only_rate_inputs_missing")
        if self.decision == "pesticide_rate_request":
            required = (
                r"\bexact product\b|\bregistration\b",
                r"\bcrop stage\b",
                r"\btarget (?:weed|pest|disease)\b[^.]{0,70}\b(?:stage|size)\b|\b(?:weed|pest) stage\b",
                r"\b(?:conditions|weather|wind|rain)\b",
                r"\b(?:resistan|previous (?:product|herbicide)|application history)\w*\b",
                r"\bcurrent (?:PMRA )?(?:product )?label\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in required) < 5:
                violations.append("pesticide_rate_context_incomplete")
        if self.decision == "fertility_rate" and re.search(
            r"\b(?:how much|what (?:nitrogen|N) rate|how many (?:pounds?|kilograms?))\b",
            self.question,
            re.IGNORECASE,
        ) and re.search(r"\b(?:nitrogen|N)\b", self.question, re.IGNORECASE):
            required = (
                r"\b(?:cannot set|cannot give|cannot calculate|not enough|depends)\b",
                r"\bcrop species\b|\b(?:specific|exact) crop\b",
                r"\b(?:crop stage|growth stage)\b",
                r"\b(?:yield goal|yield target|expected yield|realistic yield)\b",
                r"\b(?:soil nitrate|soil test)\b",
                r"\b(?:texture|organic matter|rooting)\b",
                r"\b(?:irrigation|drainage|water|weather|loss risk)\b",
                r"\b(?:manure|previous[- ]crop) credits?\b",
                r"\b(?:provincial|local|locally)\b[^.]{0,80}\bcalibrat",
            )
            hits = [bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in required]
            if sum(hits) < 7 or not hits[0] or not hits[1] or not hits[4] or not hits[8]:
                violations.append("underspecified_nitrogen_rate_context_incomplete")
        if self.decision == "slc_map_interpretation":
            required = (
                r"\b(?:dominant|component)\b",
                r"\b(?:unresolved|not located|not mapped within|cannot tell where)\b",
                r"\b(?:regional|generalized|screening|prior)\b",
                r"\b(?:soil pit|auger|field observation|ground[- ]truth|site investigation)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in required) < 3:
                violations.append("slc_component_resolution_boundary_missing")
        if self.decision == "map_based_rescue_n":
            required = (
                r"\b(?:regional soil map|mapped unit|map)\b[^.]{0,90}\b(?:screening|prior|not field truth|cannot set)\b",
                r"\b(?:affected and normal|field pattern)\b",
                r"\b(?:roots?|saturation duration|drainage|waterlog)\w*\b",
                r"\b(?:nitrogen already applied|application history|previous[- ]crop|manure|fertilizer history)\b",
                r"\b(?:response|uptake window|local calibration|provincial)\b",
            )
            if sum(bool(re.search(pattern, answer, re.IGNORECASE)) for pattern in required) < 4:
                violations.append("map_based_rescue_n_evidence_missing")
        if self.decision == "salinity_management" and re.search(
            r"\b(?:map|regional saline[- ]soil class|polygon|intersects?)\b",
            self.question,
            re.IGNORECASE,
        ):
            map_boundary = bool(re.search(r"\b(?:screening|prior|does not prove|cannot prescribe|not enough)\b", lower))
            ambiguous_permission = bool(re.search(r"\byou can prescribe\b", lower))
            root_zone = bool(re.search(r"\b(?:root[- ]zone|sampling depth|crop tolerance|infiltration|outlet)\b", lower))
            if not map_boundary or ambiguous_permission or not root_zone:
                violations.append("mapped_salinity_prescription_boundary_missing")
        if self.decision == "planting_window" and re.search(
            r"\b(?:plant now|proceed with planting|the planting window is (?:open|suitable|acceptable))\b", lower
        ):
            violations.append("unsupported_planting_permission")
        if self.decision == "field_trafficability":
            if re.search(
                r"\b(?:seed[- ]zone|seedbed|plant(?:ing)?|opener|furrow|seed[- ]to[- ]soil|emergence)\b",
                lower,
            ):
                violations.append("planting_template_substituted_for_field_trafficability")
            trafficability_lanes = (
                r"\b(?:standing water|ponding|drainage|recent rain|recent irrigation)\b",
                r"\b(?:below the surface|subsurface|soil moisture|soil condition|probe)\b",
                r"\b(?:intended (?:equipment )?load|axle load|tire pressure|track pressure)\b",
                r"\b(?:rut(?:ting)?|smear(?:ing)?|compact(?:ion|ing)?|soil displacement)\b",
                r"\b(?:delay|do not enter|stay out|recheck|stop condition)\b",
            )
            if sum(bool(re.search(pattern, lower)) for pattern in trafficability_lanes) < 4:
                violations.append("field_trafficability_checks_missing")
        if _requires_scout_application_separation(self.question):
            if not re.search(
                r"\b(?:can|may|should|proceed with|continue)\b[^.]{0,35}\bscout\w*\b|"
                r"\bscout\w*\b[^.]{0,45}\b(?:can|may|proceed|continue|field access|worker safety)\b",
                lower,
            ):
                violations.append("scouting_decision_not_answered")
            if not re.search(r"\b(?:spray|application|fungicide)\b", lower) or not re.search(
                r"\b(?:current (?:product )?label|label constraints?|do not spray|delay|withhold)\b",
                lower,
            ):
                violations.append("application_decision_not_separated")
        if self.crop in _INTEGRATED_SPECIALTY_CROPS and _requires_integrated_specialty_decision(self.question):
            lane_patterns = (
                r"\b(?:soil moisture|root[- ]zone|irrigation record|applied water)\b",
                r"\b(?:soil test|tissue test|fertility|fertilizer|nutrient)\b",
                r"\b(?:scout|diagnos|pest|disease|severity|density)\b",
                r"\b(?:current (?:product )?label|preharvest interval|restricted[- ]entry|PHI|REI)\b",
                r"\b(?:food safety|produce safety|irrigation[- ]water|water quality)\b",
                r"\b(?:market quality|buyer|processor specification|quality defects?)\b",
            )
            if any(not re.search(pattern, lower) for pattern in lane_patterns):
                violations.append("integrated_specialty_lanes_missing")
        if self.decision == "regional_statistics":
            spatial_request = bool(re.search(r"\b(?:boundary|geometry|map|spatial|polygon|point)\b", self.question, re.IGNORECASE))
            geometry_made_mandatory = bool(
                re.search(
                    r"\b(?:must|required|needs? to|cannot|without)\b[^.]{0,100}\b(?:field )?(?:geometry|boundary)\b|"
                    r"\b(?:field )?(?:geometry|boundary)\b[^.]{0,80}\b(?:must|required|needed)\b",
                    answer,
                    re.IGNORECASE,
                )
            )
            if geometry_made_mandatory and not spatial_request:
                violations.append("unnecessary_geometry_requirement")
            unstated_compaction_tangent = "compaction" not in self.question.lower() and bool(
                re.search(r"\bcompaction\b", lower)
            )
            if re.search(r"\bdiagnos(?:is|e|ed|ing|tic)\b", lower) or unstated_compaction_tangent:
                violations.append("domain_template_leakage")
        if self.decision == "practice_economics":
            if re.search(r"\bdiagnos(?:is|e|ed|ing|tic)\b", lower):
                violations.append("domain_template_leakage")
            if re.search(
                r"\b(?:must|required|needs? to)\b[^.]{0,100}\b(?:program eligibility|cost[- ]share|incentive)\b|"
                r"\bonly with\b[^.]{0,120}\b(?:program eligibility|cost[- ]share|incentive)\b",
                lower,
            ):
                violations.append("optional_program_context_made_mandatory")
        if self.decision == "forage_frost_safety":
            if not re.search(r"\b(?:prussic|hydrocyanic|cyanide)\b", lower):
                violations.append("prussic_acid_hazard_omitted")
            if not re.search(r"\bnitrate\b", lower):
                violations.append("forage_nitrate_hazard_omitted")
            if re.search(r"\b(?:mycotoxin|mold)\b", lower) and not re.search(
                r"\b(?:prussic|hydrocyanic|cyanide|nitrate)\b", lower
            ):
                violations.append("wrong_forage_hazard")
        if self.decision == "furrow_irrigation_uniformity" and re.search(
            r"\b(?:nozzle|sprinkler|pivot|drip emitter)\b", lower
        ):
            violations.append("irrigation_system_mismatch")
        if self.decision == "soil_water_sensor_interpretation" and re.search(
            r"\b(?:flood|submerg|oxygen depletion|salinity|sodicity)\b", lower
        ):
            violations.append("soil_water_decision_mismatch")
        if self.decision == "variable_rate_pk" and re.search(r"\bnitrogen\b", lower) and not re.search(
            r"\b(?:phosphorus|potassium|P|K)\b", answer, re.IGNORECASE
        ):
            violations.append("nutrient_entity_mismatch")
        if self.decision == "variety_trial_selection":
            question_diseases = {match.lower() for match in _DISEASE_ENTITY_RE.findall(self.question)}
            answer_diseases = {match.lower() for match in _DISEASE_ENTITY_RE.findall(answer)}
            if answer_diseases - question_diseases:
                violations.append("unsupported_disease_entity_in_variety_decision")
        if self.decision == "physiological_disorder" and re.search(
            r"\b(?:blossom[- ]end rot|dark,? sunken blossom ends?)\b[^.]{0,100}\bcaused by calcium deficiency\b|"
            r"\btissue (?:test|sampling)\b[^.]{0,80}\bdefinitively confirm\b",
            lower,
        ):
            violations.append("calcium_transport_disorder_misstated_as_simple_deficiency")
        if self.decision == "postharvest_cooling" and re.search(
            r"\b(?:later|evening) cooling\b[^.]{0,50}\b(?:enough|adequate|fine|revers)\b", lower
        ):
            violations.append("delayed_cooling_treated_as_reversible")

        assumption_patterns = (
            (
                r"\bmanure\b",
                r"\b(?:specific|exact|current|the) manure (?:analysis|credit|application)\b|"
                r"\b(?:must|should|needs? to)\b.{0,45}\b(?:account for|subtract|include)\b.{0,25}\bmanure\b|"
                r"\bmanure credits?\b.{0,30}\b(?:must|should|need)\b|"
                r"\b(?:apply|subtract|calculate|obtain|review|verify|check)\b.{0,45}\bmanure (?:analysis|credits?)\b",
            ),
            (r"\b(?:tile|tile drainage|tile-drainage)\b", r"\b(?:account(?:s|ing)? for|review|ensure|check(?: for)?)\b.{0,45}\btile(?: drainage|-drainage)?\b|\btile[- ]drainage\b.{0,35}\bmust\b"),
            (
                r"\birrigat",
                r"\b(?:confirm|verify|check)\b.{0,35}\birrigation water\b|"
                r"\b(?:forecast(?:ed)?|specific|current|the)\b.{0,35}\birrigation schedule\b|"
                r"\birrigation schedule\b",
            ),
            (r"\bhumid", r"\b(?:high|increased) humidity\b"),
            (r"\bfrozen\b", r"\b(?:soil is|soil is not|confirm.{0,25}soil is not) frozen\b"),
        )
        absent_assumptions = 0
        for question_pattern, answer_pattern in assumption_patterns:
            if not re.search(question_pattern, self.question, re.IGNORECASE) and re.search(
                answer_pattern, answer, re.IGNORECASE
            ):
                absent_assumptions += 1
        if absent_assumptions == 1 and self.crop:
            violations.append("unstated_field_assumption")
        elif absent_assumptions >= 2:
            violations.append("multiple_unstated_field_assumptions")
        violations.extend(
            f"premise_anchor_missing:{anchor}"
            for anchor in self.missing_premise_anchors(answer)
        )
        if self.capsule is not None:
            violations.extend(self.capsule.answer_violations(answer))
        return tuple(dict.fromkeys(violations))


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


def build_decision_route_state(question: str, question_type: str = "") -> DecisionRouteState:
    signals = analyze_query_context(question)
    lower = question.lower()
    crop = signals.primary_crop
    capsule = build_decision_capsule(question, crop=crop)
    source_boundary = None
    if signals.country == "canada":
        for name, pattern in _US_ONLY_SOURCE_PATTERNS:
            if re.search(pattern, question, re.IGNORECASE):
                source_boundary = name
                break

    decision = _decision_name(lower, question_type)
    capsule_can_override = not (
        decision == "plant_health" and capsule.domain == "crop_stress_differential"
    )
    if capsule.is_specific and capsule_can_override and decision in _CAPSULE_OVERRIDEABLE_DECISIONS:
        decision = {
            "planting_establishment": "planting_window",
        }.get(capsule.domain, capsule.domain)
    decisive = _decisive_evidence(decision, crop)
    premise_anchors = _premise_anchors(decision)
    constraints = [f"Use only field conditions stated in the question: {question.strip()}"]
    if source_boundary:
        constraints.append(f"Reject the {source_boundary.upper()} coverage premise before giving field advice")
    if decision == "fertility_rate":
        constraints.append("Do not assume manure, irrigation, or tile drainage unless the record states it")
    if decision == "crop_irrigation_scheduling":
        constraints.append("Keep the decision on root-zone depletion, crop demand, forecast water, and irrigation-system limits; do not substitute fertility guidance")
    if decision == "greenhouse_substrate_irrigation":
        constraints.append("Use greenhouse substrate, emitter, drain-fraction, and root-zone EC evidence; do not substitute field-soil survey, tile, or soil-profile logic")
    if decision == "sweet_corn_harvest_timing":
        constraints.append("Use fresh-market sweet-corn ear maturity and buyer quality, not grain moisture, drying, aeration, or bin-storage logic")
    if decision == "fusarium_head_blight_risk":
        constraints.append("Assess FHB risk through flowering stage, weather, residue and rotation, variety, and current local risk guidance before any label decision")
    if decision == "fleabane_management":
        constraints.append("Keep Canada fleabane identity, cohort, growth stage, resistance history, and the forage system central; do not substitute a generic spray-weather checklist")
    if decision == "forage_stand_thinning_differential":
        constraints.append("Compare affected and healthy crowns, roots, and soil before assigning insect, disease, winter, compaction, or water cause")
    if decision == "cutworm_stand_loss":
        constraints.append("Confirm active cutworm injury and quantify the remaining corn stand before treatment or replant discussion")
    if decision == "seeding_depth_decision":
        constraints.append("Set depth from moisture access, texture and crust risk, seed vigour, and opener consistency; do not substitute a plant-or-delay permission")
    if decision == "nutrient_runoff_risk":
        constraints.append("Answer the runoff and nutrient-loss decision from current field pathways, nutrient placement, forecast intensity, and current local requirements; do not substitute irrigation scheduling")
    if decision == "sidedress_n_credit_reconciliation":
        constraints.append("Reconcile measured manure and previous-crop credits with current soil nitrogen, crop demand, timing, and loss risk before any sidedress rate")
    if decision == "seed_row_fertilizer_safety":
        constraints.append("Keep the decision on product analysis, nutrient rate, row geometry, opener spread and separation, seedbed condition, and the current local seed-row safety table")
    if decision == "wet_area_drainage_differential":
        constraints.append("Separate inherent fine-texture storage from correctable excess-water mechanisms using paired profiles, saturation timing, topography, drainage, and outlet evidence")
    if decision == "hail_disease_differential":
        constraints.append("Compare immediate storm-aligned physical injury with lesions that expand or develop pathogen signs; do not invent a named disease")
    if decision == "corn_common_rust_differential":
        constraints.append("Explain raised rub-off rust pustules and field progression before comparing spray, nutrient, and other leaf-disease patterns")
    if decision == "wild_oat_post_application":
        constraints.append("Separate late cohorts from survivors of the application and resistance before deciding whether any in-crop tactic remains useful")
    if decision == "herbicide_injury_control_failure":
        constraints.append("Diagnose crop injury and weed survival as related but separate spatial and application-record questions before any follow-up treatment")
    if decision == "herbicide_injury_drift_differential":
        constraints.append("Reconstruct symptom timing, product and tank records, field pattern, neighbour activity, and weather before assigning drift or tank contamination")
    if decision == "crop_stress_differential":
        constraints.append("Compare affected and normal plants, roots, stand, wetness, field pattern, and input history before treating crop colour as a nutrient rate")
    if decision == "seeding_rate_calculation":
        constraints.append("Do not finish the calculation without target stand and expected field establishment or mortality in compatible units")
    if decision == "erosion_control_plan":
        constraints.append("Treat mapped slope as screening context and ground-truth flow paths, cover, rotation, tillage, and observed erosion before selecting controls")
    if decision == "drought_nitrogen_adjustment":
        constraints.append("Treat the regional drought index as context, then use field water, crop response, nitrogen-budget, timing, and economic evidence before changing rate")
    if decision == "underspecified_spray":
        constraints.append("Decline product selection until crop, target, crop and target stage, jurisdiction, conditions, and the current label are known")
    if decision == "boundary_only_fertility_rate":
        constraints.append("Treat geometry as location context only; require province, crop demand, soil nitrogen, applied inputs and credits, water, and local calibration before a numeric rate")
    if decision == "pesticide_rate_request":
        constraints.append("Do not state a pesticide rate until the exact registered product, crop, target and stages, jurisdiction, conditions, application history, and current label are known")
    if decision == "slc_map_interpretation":
        constraints.append("Explain that SLC polygons are generalized associations whose component soils are not resolved within the polygon or field")
    if decision == "slc_attribute_interpretation":
        constraints.append("Separate SLC screening attributes from current field measurements needed for fertilizer placement or drainage")
    if decision == "mapped_wet_strip_irrigation":
        constraints.append("Treat a mapped wet-looking strip as a hypothesis; verify root-zone water and the cause before changing irrigation by zone")
    if decision == "ambiguous_pump_direction":
        constraints.append("Do not invent whether the pump supplies irrigation or removes drainage water; resolve its direction and purpose before giving a runtime")
    if decision == "nasdi_index_interpretation":
        constraints.append("Keep SPI precipitation-only and SPEI precipitation-minus-evaporative-demand semantics distinct, and explain the accumulation window")
    if decision == "manure_credit_boundary":
        constraints.append("Do not transfer an Alberta manure credit into Saskatchewan or invent a credit without current analysis, application records, soil evidence, and Saskatchewan calibration")
    if decision == "map_based_rescue_n":
        constraints.append("Use the regional soil map only as a prior; separate waterlogging and root injury from nitrogen shortage before any rescue decision")
    if decision == "map_crop_selection":
        constraints.append("Treat land-suitability mapping as screening context; choose a crop from field limits, rotation, climate, market, equipment, and economics")
    if decision == "greenhouse_tomato_leaf_curl":
        constraints.append("Keep tomato leaf curl as an integrated climate, root-zone, pest-vector, virus, and chemical-exposure differential; do not substitute cucumber irrigation scheduling")
    if decision == "winter_injury_differential":
        constraints.append("Confirm winter injury from exposure pattern and live-tissue checks, then support recovery while requiring disease signs before an infectious diagnosis")
    if decision == "planting_window":
        constraints.append("Do not make one measurement a universal planting gate")
    if decision == "field_trafficability":
        constraints.append(
            "Do not substitute a planting decision or treat surface dryness as permission to enter; use a fresh "
            "affected-versus-normal field inspection and the intended equipment load"
        )
    if decision == "seed_treatment":
        constraints.append("Keep the decision on seed-applied protection, target risk, and value; do not substitute a foliar scouting or spray workflow")
    if decision == "transplant_establishment":
        constraints.append("Resolve transplant quality and establishment fitness before discussing starter fertilizer")
    if decision == "produce_safety":
        constraints.append("Keep changed crop-contact water conditions separate from grain harvest and storage logic")
    if decision == "regional_statistics":
        constraints.append("Do not require field geometry unless the user asks for a spatial lookup")
        constraints.append("Do not import diagnosis or treatment language into a statistics answer")
    if decision == "practice_economics":
        constraints.append("Treat cost-share and program eligibility as optional scenario inputs, not prerequisites")
        constraints.append("Use economic decision language, not diagnosis language")
    if decision == "forage_frost_safety":
        constraints.append("Treat animal exposure as the immediate decision and do not substitute a grain mycotoxin workflow")
    if decision == "furrow_irrigation_uniformity":
        constraints.append("Keep the recommendation specific to surface furrow irrigation, not sprinkler or drip hardware")
    if decision == "soil_water_sensor_interpretation":
        constraints.append("Do not compare raw volumetric water content across soils without field capacity and rooting depth")
    if decision == "openet_irrigation_decision":
        constraints.append("Keep satellite-modeled ET separate from the field sensor and the irrigation decision")
    if decision == "drip_irrigation_uniformity":
        constraints.append("Diagnose lateral hydraulics and emitter delivery before changing every zone runtime")
    if decision == "irrigation_water_nitrate_credit":
        constraints.append("Keep irrigation-water nitrate and the nitrogen credit as the governing production system")
    if decision == "tile_drainage_decision":
        constraints.append("Ground-truth the wetness mechanism and outlet before placing drainage")
    if decision == "spray_weather_window":
        constraints.append("Answer the application-window decision from the exact label, wind, sensitive area, and rainfast conditions")
    if decision == "water_limited_nitrogen_increase":
        constraints.append("Preserve water-limited crop response, current nitrogen evidence, and the economics of any added rate")
    if decision == "lime_sampling_rate":
        constraints.append("Resolve sampling representativeness before calculating a lime requirement or uniform rate")
    if decision == "forage_defoliator_harvest_decision":
        constraints.append("Resolve spraying, early cutting, or continued scouting from representative pressure, crop stress, harvest timing, beneficials, and a local threshold")
    if decision == "high_tunnel_yellowing":
        constraints.append("Do not raise nitrogen from yellowing alone; diagnose fertigation delivery, salinity, root-zone water, roots, and current nutrient evidence together")
    if decision == "variable_rate_pk":
        constraints.append("Preserve phosphorus and potassium as the nutrients under review; do not substitute nitrogen")
    if decision == "cover_crop_termination":
        constraints.append("Preserve the next-crop establishment window, stored soil water, grazing value, and erosion protection as one tradeoff")
    if decision in {
        "corn_rootworm_silk_clipping",
        "pest_treatment",
        "wheat_aphid_treatment",
        "weed_burndown_survivor",
        "weed_escape_management",
        "weed_preharvest_escape",
        "weed_seed_return_management",
    }:
        constraints.append("Answer the biological treatment decision before product-label and application-weather constraints")
    if decision in {"soil_crusting", "compaction_tillage", "flood_recovery", "freeze_recovery"}:
        constraints.append("Give the field assessment and recovery or operation boundary, not a generic request for more data")
    if decision in {
        "cold_wet_purple_corn",
        "fruit_set_diagnostic",
        "physiological_disorder",
        "soybean_idc",
        "sulfur_nitrogen_differential",
        "wilt_differential",
        "salinity_management",
        "wheat_flag_leaf_fungicide",
    }:
        constraints.append("Explain the crop-specific causal distinction before listing tests or caveats")
    if decision in {"maturity_switch", "pollination_stress"}:
        constraints.append("Give the crop-development logic before local calibration or uncertainty caveats")
    if decision == "potato_storage_conditioning":
        constraints.append("Balance field-heat removal with skin set, bruising, dehydration, condensation, lot condition, and the actual storage system")
    if crop in _NONGRAIN_CROPS and decision == "harvest_storage":
        constraints.append(f"Use {crop}-specific harvest and storage biology, not a grain-storage template")
    if crop == "potato" and decision == "seed_quality":
        constraints.append("Treat planting material as seed tubers or seed pieces, not botanical seed")
    return DecisionRouteState(
        question=question,
        decision=decision,
        crop=crop,
        country=signals.country,
        decisive_evidence=decisive,
        constraints=tuple(constraints),
        premise_anchors=premise_anchors,
        source_boundary=source_boundary,
        capsule=capsule,
    )


def _decision_name(lower: str, question_type: str) -> str:
    focus = request_focus(lower)
    if re.search(r"\b(?:hail|storm|frost|rain|wind)\b", lower) and re.search(
        r"\b(?:tomorrow|tonight|at \d{1,2}(?::\d{2})?\s*(?:am|pm)|this afternoon|this evening)\b",
        lower,
    ) and re.search(r"\b(?:my|this)\b[^?]{0,60}\b(?:field|farm|quarter section|parcel)\b", lower):
        return "localized_weather_event"
    if re.search(r"\b(?:soil )?(?:sample|sampling|composite)\b", lower) and re.search(
        r"\b(?:knolls?|depressions?|manure strip|management zones?|contrasting|variable|variability)\b",
        lower,
    ):
        return "stratified_soil_sampling"
    if re.search(r"\b(?:potatoes?|pommes? de terre)\b", lower) and re.search(
        r"\b(?:storage|store|ventilat\w*|airflow|field heat|pulp temperature|skin set|bruis\w*|"
        r"stockage|ventil\w*|chaud\w*|peau|meurtriss\w*)\b",
        lower,
    ):
        return "potato_storage_conditioning"
    if re.search(r"\b(?:PPC|soil landscapes(?: of canada)?|SLC)\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:composantes?|components?|polygone|polygon|tout mon champ|whole field)\b",
        lower,
    ):
        return "slc_map_interpretation"
    if re.search(r"\bsoil landscapes(?: of canada)?\b|\bSLC\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:attributes?|measurements?|fertilizer placement|drainage)\b", lower
    ):
        return "slc_attribute_interpretation"
    if re.search(r"\bNASDI\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:SPI|standardized precipitation index)\b", lower, re.IGNORECASE
    ) and re.search(
        r"\b(?:SPEI|standardized precipitation evapotranspiration index)\b", lower, re.IGNORECASE
    ):
        return "nasdi_index_interpretation"
    if re.search(r"\b(?:map|mapped|carte)\b", lower) and re.search(r"\b(?:wet|dark strip|bande sombre|humide)\b", lower) and re.search(
        r"\b(?:cut|reduce|stop|change|réduire|arrêter)\b.{0,45}\birrigat", lower
    ):
        return "mapped_wet_strip_irrigation"
    if re.search(r"\bpump\b", lower) and re.search(r"\birrigat", lower) and re.search(r"\bdrain", lower) and re.search(
        r"\b(?:haven't said|have not said|unknown|unclear|whether)\b", lower
    ):
        return "ambiguous_pump_direction"
    if re.search(r"\b(?:manure|digestate|compost)\b", lower) and re.search(r"\b(?:credit|nitrogen credit|N credit)\b", lower, re.IGNORECASE) and (
        re.search(r"\bexact\b", lower)
        or re.search(r"\bwithout\b.{0,100}\b(?:test|analysis|history|calibration)\b", lower)
    ):
        return "manure_credit_boundary"
    if re.search(
        r"(?:\btrafficability\b|\bfield traffic\b|"
        r"\bdriv(?:e|es|en|ing)\b[^.?\n]{0,35}\b(?:equipment|machinery|tractor|vehicle|field|corner|area)\b|"
        r"\b(?:equipment|machinery|tractor|vehicle)\b[^.?\n]{0,35}"
        r"\b(?:enter(?:s|ed|ing)?|driv(?:e|es|en|ing)|traffic(?:s|ked|king)?)\b|"
        r"\benter(?:s|ed|ing)?\b[^.?\n]{0,25}\b(?:field|corner|area)\b)",
        focus,
    ) and not re.search(
        r"\b(?:plant|planting|seed[- ]zone|seedbed|opener|furrow|emergence)\b",
        focus,
    ):
        return "field_trafficability"
    if re.search(r"\b(?:land suitability|agricultural suitability|capability|soil|regional) (?:map|mapping)\b", lower) and re.search(
        r"\b(?:which|what) crop\b|\bcrop should (?:i|we) (?:plant|grow|choose)\b",
        lower,
    ):
        return "map_crop_selection"
    if re.search(r"\bsoil landscapes of canada\b|\bSLC polygon\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:polygon|intersect|dominant soil|drainage class)\b", lower
    ):
        return "slc_map_interpretation"
    if re.search(r"\bregional soil map\b", lower) and re.search(r"\b(?:rescue nitrogen|nitrogen pass)\b", lower):
        return "map_based_rescue_n"
    if re.search(r"\b(?:what|which)(?:\s+\w+){0,3}\s+rate\b|\bhow much\b", lower) and re.search(
        r"\b(?:herbicide|insecticide|fungicide|pesticide|spray)\b", lower
    ):
        return "pesticide_rate_request"
    if re.fullmatch(r"\s*(?:what|which) (?:should|do) i spray\??\s*", lower):
        return "underspecified_spray"
    if re.search(r"\b(?:boundary|polygon|drew|drawn)\b", lower) and re.search(
        r"\b(?:how many|pounds?|rate|amount)\b", lower
    ) and re.search(r"\b(?:nitrogen|fertiliz)\w*\b", lower):
        return "boundary_only_fertility_rate"
    if re.search(r"\b(?:seeding|seed)[- ]rate (?:calculation|formula)\b|\bfinish (?:the )?seeding[- ]rate calculation\b", lower) and re.search(
        r"\b(?:germ(?:ination)?|thousand[- ]kernel weight|tkw|target stand|mortality|establishment)\b",
        lower,
    ):
        return "seeding_rate_calculation"
    if re.search(r"\b(?:twist|curl|injur|symptom)\w*\b", lower) and re.search(
        r"\b(?:spray|sprayed|application)\w*\b", lower
    ) and re.search(r"\b(?:drift|neighbou?r|tank|cleanout|overlap)\b", lower):
        return "herbicide_injury_drift_differential"
    if re.search(r"\b(?:erosion|erosion[- ]control)\b", lower) and re.search(
        r"\b(?:slope|sloping|landscape unit|polygon|tillage|flow path)\b", lower
    ):
        return "erosion_control_plan"
    if re.search(r"\b(?:NASDI|drought|dryness index|moisture deficit)\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:nitrogen|N rate|fertiliz)\w*\b", lower, re.IGNORECASE
    ) and re.search(r"\b(?:cut|reduce|increase|change|adjust|rate)\w*\b", lower):
        return "drought_nitrogen_adjustment"
    if re.search(r"\bclubroot\b", lower) and re.search(
        r"\b(?:swollen roots?|galls?|dying patch|approach|what do i do|today|contain|sanitation)\b",
        lower,
    ):
        return "clubroot_containment"
    if re.search(
        r"\bfall[- ](?:banded|applied)\b[^.]{0,45}\bnitrogen\b|\bnitrogen\b[^.]{0,45}\bfall[- ](?:banded|applied)\b",
        lower,
    ):
        return "fall_banded_nitrogen"
    if re.search(r"\bOlsen P\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:high|starter phosphorus|starter P|insurance)\b", lower, re.IGNORECASE
    ):
        return "high_p_starter_decision"
    if re.search(r"\b(?:same rate|go at the same rate)\b", lower) and re.search(r"\bafter (?:the )?rain\b", lower):
        return "ambiguous_product_followup"
    if re.search(r"\bgreenhouse\b", lower) and re.search(r"\btomato(?:es)?\b", lower) and re.search(
        r"\bleaf curl\b|\bcurl(?:ing|ed)? leaves?\b", lower
    ):
        return "greenhouse_tomato_leaf_curl"
    if re.search(r"\bsidedress\b", lower) and re.search(r"\b(?:manure|previous crop|nitrogen credit|legume credit)\b", lower):
        return "sidedress_n_credit_reconciliation"
    if re.search(r"\bseed[- ]row fertilizer\b", lower) and re.search(r"\b(?:opener|seedbed|safe|placement)\b", lower):
        return "seed_row_fertilizer_safety"
    if re.search(r"\b(?:weak|poor)\b[^?]{0,40}\bgrowth\b", lower) and re.search(r"\bwet areas?\b", lower) and re.search(
        r"\b(?:texture|drainage)\b", lower
    ):
        return "wet_area_drainage_differential"
    if re.search(r"\b(?:hail|storm)\b", lower) and re.search(r"\b(?:lesions?|disease|damaged leaves?)\b", lower):
        return "hail_disease_differential"
    if re.search(r"\bcommon rust\b", lower) and re.search(r"\b(?:spray injury|nutrient stress|leaf disease|distinguish)\b", lower):
        return "corn_common_rust_differential"
    if re.search(r"\bwild[- ]oats?\b", lower) and re.search(r"\b(?:cohorts?|in[- ]crop application|herbicide history)\b", lower):
        return "wild_oat_post_application"
    if re.search(r"\bherbicide (?:pass|application)\b", lower) and re.search(r"\bcrop (?:is )?injur", lower) and re.search(
        r"\b(?:weeds? remain|failed weed control|another treatment)\b", lower
    ):
        return "herbicide_injury_control_failure"
    if (
        re.search(r"\bsevere winter\b", lower)
        and re.search(r"\b(?:bud break|dieback|winter injury)\b", lower)
    ) or (
        re.search(r"\bwinter injury\b", lower)
        and re.search(r"\b(?:saskatoon|berry|berries|buds?|canes?|woody|orchard|vineyard)\b", lower)
    ):
        return "winter_injury_differential"
    if re.search(r"\bgreenhouse\b", lower) and re.search(r"\b(?:cucumber|tomato|pepper|produce)\b", lower) and re.search(
        r"\b(?:substrate|media|root[- ]zone|drain(?:age| fraction)?|irrigation (?:frequency|volume)|fertigation)\b",
        lower,
    ):
        return "greenhouse_substrate_irrigation"
    if re.search(r"\bsweet[- ]corn\b", lower) and re.search(
        r"\b(?:harvest|maturity|buyer|ears?|kernel|milk stage|cooling)\b", lower
    ):
        return "sweet_corn_harvest_timing"
    if re.search(r"\b(?:fusarium head blight|FHB)\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:flowering|anthesis|heading|risk|moisture|residue|rotation|variety)\b", lower
    ):
        return "fusarium_head_blight_risk"
    if re.search(r"\b(?:canada fleabane|horseweed)\b", lower) and re.search(
        r"\b(?:management|emergence|cohort|growth stage|resistan|control)\w*\b", lower
    ):
        return "fleabane_management"
    if re.search(r"\b(?:forage|alfalfa|hay stand)\b", lower) and re.search(
        r"\b(?:thinning|thin|weak|patches|stand decline)\b", lower
    ) and re.search(r"\b(?:crown|root|winter injury|compaction|water stress|insect|disease)\b", lower):
        return "forage_stand_thinning_differential"
    if re.search(r"\bcutworms?\b", lower) and re.search(
        r"\b(?:cut plants?|stand loss|uneven emergence|scout|active injury|act)\w*\b", lower
    ):
        return "cutworm_stand_loss"
    if re.search(r"\bseed(?:ing)? depth\b", lower) and re.search(
        r"\b(?:moisture|texture|crust|vigou?r|opener|seedbed)\b", lower
    ):
        return "seeding_depth_decision"
    if re.search(r"\b(?:nutrient|fertiliz\w*) (?:application|applied)\b", lower) and re.search(
        r"\b(?:runoff|nutrient[- ]loss|loss risk)\b", lower
    ):
        return "nutrient_runoff_risk"
    if re.search(r"\b(?:next irrigation|irrigation (?:timing|frequency|volume|schedule))\b", lower) and re.search(
        r"\b(?:root[- ]zone|soil water|water[- ]holding|crop stage|forecast|depletion)\b", lower
    ):
        return "crop_irrigation_scheduling"
    if re.search(r"\bhigh[- ]tunnel\b", lower) and re.search(r"\btomato(?:es)?\b", lower) and re.search(
        r"\b(?:yellow|chloros|pale)\w*\b", lower
    ) and re.search(r"\b(?:fertigat|drip|emitter|nitrogen|EC|salinity)\w*\b", lower, re.IGNORECASE):
        return "high_tunnel_yellowing"
    if re.search(r"\bopenet\b", lower) and re.search(
        r"\b(?:irrigat|probe|sensor|field capacity|crop water use)\w*\b", lower
    ):
        return "openet_irrigation_decision"
    if re.search(r"\b(?:well|irrigation)[- ]?water\b|\bwell[- ]?water\b", lower) and re.search(
        r"\bnitrate\b", lower
    ) and re.search(r"\b(?:credit|fertilizer|nitrogen budget|count every)\b", lower):
        return "irrigation_water_nitrate_credit"
    if re.search(r"\bdrip\b", lower) and re.search(
        r"\b(?:laterals?|ends?|pressure|flow|runtime|zones?|plugging|uniformity)\b", lower
    ):
        return "drip_irrigation_uniformity"
    drainage_installation = bool(
        re.search(
            r"\b(?:contractor|install|place|placing|design|layout)\w*\b[^?]{0,70}\b(?:tile|drain)\b|"
            r"\b(?:tile|drain)\b[^?]{0,70}\b(?:contractor|install|place|placing|design|layout)\w*\b",
            lower,
        )
    )
    if drainage_installation and re.search(
        r"\b(?:wet|pond|poorly drained|water table|outlet|low area)\w*\b", lower
    ):
        return "tile_drainage_decision"
    if not re.search(r"\b(?:injury|off[- ]target|symptom|separat)\w*\b", lower) and re.search(
        r"\b(?:spray|application|custom rig)\b", lower
    ) and re.search(
        r"\b(?:wind|gust|drift|storm|rainfast|shelterbelt|sensitive)\w*\b", lower
    ):
        return "spray_weather_window"
    if re.search(r"\b(?:variable[- ]rate|increase|raise|additional)\w*\b", lower) and re.search(
        r"\b(?:nitrogen|UAN|nitrate)\b", lower, re.IGNORECASE
    ) and re.search(r"\b(?:drought|dry spell|water allocation|water[- ]limit|irrigated)\b", lower):
        return "water_limited_nitrogen_increase"
    if re.search(r"\b(?:lime|liming)\b", lower) and re.search(
        r"\b(?:composite(?: sample)?|sampling|uniform (?:lime )?rate|buffer pH|lime requirement)\b",
        lower,
        re.IGNORECASE,
    ):
        return "lime_sampling_rate"
    if re.search(r"\b(?:sorghum[- ]?sudan(?:grass)?|sudangrass)\b", lower) and re.search(
        r"\b(?:frost|freeze|drought|regrowth)\b", lower
    ) and re.search(r"\b(?:graz|cattle|feed|hay|cut)\w*\b", lower):
        return "forage_frost_safety"
    if re.search(r"\b(?:field heat|postharvest|pre[- ]?cool|cold chain|cooler)\b", lower) and re.search(
        r"\b(?:fresh[- ]market|strawberr|berry|produce|tote|cool)\w*\b", lower
    ):
        return "postharvest_cooling"
    if re.search(r"\b(?:nematodes?|nematicide)\b", lower):
        return "nematode_management"
    if re.search(r"\b(?:pre[- ]?emergence|residual)\b", lower) and re.search(
        r"\b(?:activation|no rain|almost no rain|incorporat|emerg)\w*\b", lower
    ):
        return "residual_activation"
    if re.search(r"\bvolunteer canola\b", lower) and re.search(
        r"\b(?:trait|tolerance|system|records?|appearance|post product)\b", lower
    ):
        return "volunteer_trait_unknown"
    if re.search(r"\bvariable[- ]rate\b", lower) and (
        re.search(r"\bP\s*(?:and|&)\s*K\b", lower, re.IGNORECASE)
        or (re.search(r"\bphosphorus\b", lower) and re.search(r"\bpotassium\b", lower))
    ):
        return "variable_rate_pk"
    if re.search(r"\b(?:variety|hybrid)\b", lower) and (
        (
            re.search(r"\btrials?\b", lower)
            and re.search(
                r"\b(?:one (?:dry )?(?:year|trial)|top(?:ped)?|highest[- ]yield|nearby trial|trial result|stable across|main silage|grain trial)\b",
                lower,
            )
        )
        or (
            re.search(r"\b(?:atlas|map|polygon|polygone|carte)\b", lower)
            and re.search(r"\b(?:which|what|choose|select|order|recommend)\b", lower)
        )
    ):
        return "variety_trial_selection"
    if re.search(r"\b(?:leafy greens?|fresh produce)\b", lower) and re.search(
        r"\b(?:harvest|buyer|workers?|irrigation source|leaf spots?)\b", lower
    ):
        return "integrated_preharvest_specialty"
    if re.search(r"\bfurrow[- ]irrigat", lower) and re.search(
        r"\b(?:tailwater|tail end|head|advance|set time|runoff)\b", lower
    ):
        return "furrow_irrigation_uniformity"
    if re.search(r"\b(?:volumetric water content|soil[- ]moisture sensor|sensor reading|VWC)\b", lower, re.IGNORECASE) and re.search(
        r"\b(?:texture|sandy|silt|gravel|rooting depth|roots?)\b", lower
    ):
        return "soil_water_sensor_interpretation"
    if re.search(r"\bcorn rootworm(?: beetles?)?\b|\brootworm beetles?\b", lower) and re.search(
        r"\bclip(?:ped|ping)?\b[^.]{0,30}\bsilks?\b|\bsilk clipp(?:ing|ed)\b|\bpollinat\w*\b",
        lower,
    ):
        return "corn_rootworm_silk_clipping"
    if re.search(r"\baphids?\b", lower) and re.search(r"\bwheat\b", lower) and re.search(
        r"\b(?:heads?|tillers?|grain fill|lady beetles?|beneficials?|treat|spray)\b", lower
    ):
        return "wheat_aphid_treatment"
    if re.search(r"\bwheat\b", lower) and re.search(r"\b(?:leaf spots?|fungicide)\b", lower) and re.search(
        r"\b(?:flag leaf|upper canop|lower canop|pay|profitable)\b", lower
    ):
        return "wheat_flag_leaf_fungicide"
    if re.search(r"\bweeds?|\bescapes?\b", lower) and re.search(
        r"\b(?:preharvest|close to harvest|near harvest|harvest is [^.]{0,30}(?:away|soon)|days? (?:before|from) harvest)\b",
        lower,
    ):
        return "weed_preharvest_escape"
    if re.search(r"\b(?:ryegrass|weed)\b", lower) and re.search(r"\b(?:burndown|glyphosate)\b", lower) and re.search(
        r"\b(?:surviv|failed|raise|increase|rate|resistan)\w*\b", lower
    ):
        return "weed_burndown_survivor"
    if re.search(r"\b(?:waterhemp|pigweed|palmer(?: amaranth)?|amaranth|weed)\b", lower) and re.search(
        r"\b(?:set(?:ting)? seed|shed(?:ding)? seed|seed return|seed production)\b", lower
    ):
        return "weed_seed_return_management"
    if re.search(r"\bcorn\b", lower) and re.search(r"\bpurpl\w*\b", lower) and re.search(
        r"\b(?:cold|cool)\b", lower
    ) and re.search(r"\bwet\b", lower):
        return "cold_wet_purple_corn"
    if re.search(r"\bsoybeans?\b", lower) and re.search(
        r"\b(?:interveinal|between (?:the |green )?veins)\b", lower
    ) and re.search(r"\b(?:high[- ]?ph|high ph|wet|carbonate|bicarbonate)\b", lower):
        return "soybean_idc"
    if re.search(r"\bcanola\b", lower) and re.search(r"\bsul(?:fur|phur)\b", lower) and (
        re.search(r"\bnitrogen\b", lower)
        or re.search(r"\b(?:pale|yellow|chloros)\w*\b", lower)
    ):
        return "sulfur_nitrogen_differential"
    if re.search(r"\b(?:poor fruit set|set(?:ting)? (?:very )?(?:little|few) fruit|few fruit)\b", lower) or (
        re.search(r"\bflower\w*\b", lower) and re.search(r"\b(?:little|poor|few)\b[^.]{0,20}\bfruit\b", lower)
    ):
        return "fruit_set_diagnostic"
    if re.search(r"\b(?:hay field|hay crop|alfalfa|forage)\b", lower) and re.search(
        r"\b(?:caterpillars?|defoliat\w*|chewed leaves?|leaf feeding)\b", lower
    ) and re.search(r"\b(?:cut|cutting|harvest|spray|watch)\w*\b", lower):
        return "forage_defoliator_harvest_decision"
    if not re.search(r"\b(?:seed treatment|treated seed)\b", lower) and re.search(
        r"\b(?:insects?|pests?|caterpillars?|moths?|trap captures?|aphids?|rootworm beetles?|defoliat\w*)\b", lower
    ) and re.search(
        r"\b(?:spray|treat)\w*\b|\b(?:insecticide|threshold)\b", lower
    ):
        return "pest_treatment"
    if (
        re.search(r"\b(?:water test|irrigation[- ]water|pivot)\b", lower)
        and re.search(r"\b(?:EC|electrical conductivity|SAR|sodium adsorption ratio)\b", lower, re.IGNORECASE)
        and re.search(r"\b(?:one|single|snapshot|all season|season[- ]long|unchanged)\b", lower)
    ):
        return "salinity_management"
    if re.search(r"\b(?:gypsum|gypse)\b", lower) and (
        re.search(r"\b(?:salin\w*|sodic\w*|SAR|ESP|soil EC|electrical conductivity)\b", lower, re.IGNORECASE)
        or re.search(r"\b(?:map|carte|polygon|polygone)\b", lower)
        or re.search(r"\b(?:white (?:crust|rings?)|thinning|bare patches?|poor infiltration|ponding)\b", lower)
    ):
        return "salinity_management"
    if (
        re.search(r"\b(?:weeds?|waterhemp|pigweed|ryegrass)\b", lower)
        and re.search(r"\b(?:escape\w*|surviv\w*|resistan\w*|seed set|seedbank|control plan|burndown)\b", lower)
    ) or (
        re.search(r"\bherbicide\b", lower)
        and re.search(r"\b(?:escape\w*|surviv\w*|seed set|seedbank|control plan|burndown)\b", lower)
    ):
        return "weed_escape_management"
    if re.search(r"\b(?:soil |surface )?crust\w*\b", lower) and re.search(
        r"\b(?:emerg|hypocotyl|rotary[- ]hoe)\w*\b", lower
    ):
        return "soil_crusting"
    if re.search(r"\b(?:deep[- ]?rip|deep till|subsoil)\w*\b", lower) or (
        re.search(r"\b(?:compaction|wheel tracks?)\b", focus)
        and re.search(r"\b(?:till|rip|alleviat|remediat|management options?)\w*\b", focus)
    ):
        return "compaction_tillage"
    if re.search(r"\b(?:blossom[- ]end rot|tipburn)\b", lower) or re.search(
        r"\b(?:dark|black|brown),?\s+sunken\b[^.]{0,45}\bblossom ends?\b", lower
    ) or (
        re.search(r"\blettuce\b", lower)
        and re.search(r"\b(?:brown|necrotic) inner leaf margins?|\binner (?:lettuce )?leaves?\b[^.]{0,45}\b(?:brown|necrotic|margins?)\b", lower)
        and re.search(r"\bcalcium\b", lower)
    ):
        return "physiological_disorder"
    if (
        not re.search(r"\b(?:high[- ]tunnel|root rot|root disease|root discoloration)\b", lower)
        and re.search(r"\b(?:saline|salinity|salty|salt)\b", lower)
        and (
            re.search(r"\bsalty irrigation water\b|\bsaline (?:irrigation )?water\b|\birrigation water (?:is|looks) salty\b", lower)
            or re.search(r"\b(?:saline|salinity|sodic|salt|leach)\w*\b", focus)
        )
    ):
        return "salinity_management"
    if re.search(r"\bcover[- ]crop\b", lower) and re.search(r"\b(?:terminat|wait|biomass|graz)\w*\b", lower) and re.search(
        r"\b(?:dry spring|water[- ]limit|soil moisture|stored water|next crop|winter wheat|planting window|erosion)\b",
        lower,
    ):
        return "cover_crop_termination"
    if re.search(r"\b(?:ponded|ponding|flooded|flooding|standing water)\b", lower) and re.search(
        r"\b(?:recover|surviv|replant|young corn|crop)\w*\b", lower
    ):
        return "flood_recovery"
    if re.search(r"\b(?:freeze|frozen|frost|subfreezing)\b", lower) and re.search(
        r"\b(?:recover|replant|stand|injur|terminat|collapsed|translucent)\w*\b", lower
    ):
        return "freeze_recovery"
    if re.search(r"\b(?:corn|silk|pollen|kernel set)\w*\b", lower) and re.search(
        r"\b(?:pollinat|silk|pollen|kernel set)\w*\b", lower
    ) and re.search(
        r"\b(?:heat|hot|dry|drought|water stress)\b", lower
    ):
        return "pollination_stress"
    if re.search(r"\b(?:relative[- ]maturity|maturity group)\b", lower) and re.search(
        r"\b(?:late|delay\w*|planting date|switch)\b", lower
    ):
        return "maturity_switch"
    if re.search(r"\bwilt\w*\b", lower) and re.search(r"\b(?:water stress|disease|vascular|irrigat)\w*\b", lower):
        return "wilt_differential"
    if re.search(r"\bfungicide\b", lower):
        return "fungicide_decision"
    if re.search(r"\b(?:harvest|storage|drying|grain moisture)\b", lower):
        return "harvest_storage"
    if re.search(r"\b(?:seed lots?|seed quality|germination|seed vigor|vigor test)\b", lower):
        return "seed_quality"
    if re.search(r"\b(?:planting window|plant into|wants? to plant|before planting|crop establishment)\b", lower):
        return "planting_window"
    if question_type == "fertility_rate" or re.search(r"\b(?:increase|change|adjust).{0,30}\bnitrogen\b", lower):
        return "fertility_rate"
    if re.search(r"\b(?:NASS|Quick Stats|Census of Agriculture|regional (?:yield|acreage|production|statistics))\b", lower, re.IGNORECASE):
        return "regional_statistics"
    if re.search(r"\b(?:will (?:it|the practice) pay|payback|partial budget|net return|farm(?:'s)? books?)\b", lower) or (
        re.search(r"\b(?:conservation|precision) practice\b", lower)
        and re.search(r"\b(?:pay|profit|economics?|cost|return|ROI)\b", lower)
    ):
        return "practice_economics"
    if question_type == "field_data" or re.search(r"\b(?:NASS|Quick Stats|CDL|NRCS|SSURGO|OpenET)\b", lower, re.IGNORECASE):
        return "source_interpretation"
    return question_type or "agronomic_advice"


def _decisive_evidence(decision: str, crop: str | None) -> tuple[str, ...]:
    if decision == "pesticide_rate_request":
        return ("exact product name and registration", "crop and target weed, pest or disease plus crop and target stage", "jurisdiction and current PMRA product label", "on-site conditions, prior application, efficacy and resistance history")
    if decision == "slc_map_interpretation":
        return ("SLC polygon as a generalized regional soil-landscape association", "dominant and minor components not spatially resolved within the polygon", "field-boundary overlap not proving whole-field component identity", "ground-truthed soil profiles, drainage observations and finer local survey evidence")
    if decision == "slc_attribute_interpretation":
        return ("polygon and component scale, proportions and complexity", "mapped slope, surface form, stoniness, soil name and water-table or drainage attributes", "current soil-test method, depth and nutrient measurements", "field profiles, rooting, compaction, drainage and water-table observations")
    if decision == "mapped_wet_strip_irrigation":
        return ("map date, resolution, classification and uncertainty", "representative root-zone water measurements inside and outside the strip", "topography, soil, drainage, crop and irrigation-uniformity cause", "a bounded zone test with crop-response and water-balance follow-up")
    if decision == "ambiguous_pump_direction":
        return ("whether the pump adds irrigation water or removes drainage water", "pump flow and destination or source", "field area, crop stage and current root-zone water", "system capacity, outlet or intake constraints and a measured stop condition")
    if decision == "nasdi_index_interpretation":
        return ("SPI as a precipitation anomaly", "SPEI as precipitation balanced against atmospheric evaporative demand", "the selected accumulation window", "regional index context checked against current field water, crop stage and observations")
    if decision == "manure_credit_boundary":
        return ("current representative manure analysis and source", "application rate, method, timing and field history", "current soil nitrogen and crop demand", "current Saskatchewan calibration and regulatory requirements")
    if decision == "map_based_rescue_n":
        return ("regional soil map as screening context rather than field truth", "affected-versus-normal field pattern, roots and saturation duration", "nitrogen applications, manure and previous-crop credits", "current crop response, uptake window and provincial calibration")
    if decision == "map_crop_selection":
        return ("land-suitability map as screening context rather than a crop prescription", "verified soil, drainage, topography, and field limitations", "rotation, climate and growing-season fit", "market, equipment, labour, input, and economic fit")
    if decision == "underspecified_spray":
        return ("crop and production site", "target weed, pest, or disease plus crop and target stage", "jurisdiction, exact product, and current PMRA label", "scouting need, on-site weather, application history, and resistance context")
    if decision == "boundary_only_fertility_rate":
        return ("field geometry as location context rather than a fertility measurement", "province, crop stage, realistic yield goal or crop demand", "current soil nitrate or locally appropriate soil test", "fertilizer, manure and previous-crop credits plus water and loss risk")
    if decision == "seeding_rate_calculation":
        return ("target live-plant stand in explicit area units", "seed-lot germination and purity", "thousand-kernel or seed weight in compatible units", "expected field establishment or mortality plus equipment and seedbed loss")
    if decision == "herbicide_injury_drift_differential":
        return ("symptom onset relative to both applications", "the grower's and neighbour's exact product, rate, tank, cleanout, and application records", "edge gradient, drift direction, overlaps, boom pattern, and treated-versus-untreated plants", "wind, inversion, temperature, rain, and crop-stage evidence")
    if decision == "erosion_control_plan":
        return ("ground-truthed slope length, grade, flow paths, outlets, and water connection", "observed sheet, rill, gully, or deposition evidence", "surface cover, residue, rotation, tillage direction, and traffic history", "a control matched to the confirmed erosion pathway and current local requirements")
    if decision == "drought_nitrogen_adjustment":
        return ("regional drought index as screening context rather than field water truth", "field root-zone water, rainfall, rooting, crop stage, and response potential", "current soil or crop nitrogen evidence plus all applied nitrogen and credits", "remaining uptake window, locally calibrated response probability, and partial-budget economics")
    if decision == "crop_stress_differential":
        return ("affected-versus-normal field pattern and symptom position", "stand, roots, crowns or growing points in affected and normal areas", "saturation duration, drainage, compaction, and recovery after drying", "fertilizer, manure, previous-crop, placement, and paired soil or tissue evidence")
    if decision == "clubroot_containment":
        return ("suspected clubroot symptoms and a representative confirmation sample", "marking the patch and restricting traffic or soil movement", "cleaning soil from equipment before leaving the area", "current provincial clubroot containment and sanitation guidance")
    if decision == "fall_banded_nitrogen":
        return ("soil temperature and nitrogen form at fall application", "banded versus broadcast placement", "spring saturation, drainage and denitrification loss risk", "local moisture, seedbed and crop-response tradeoffs versus spring banding")
    if decision == "high_p_starter_decision":
        return ("Olsen phosphorus method, units and locally calibrated response category", "yield response probability versus maintenance or crop-removal goals", "soybean seed-placed phosphorus safety, row width and opener placement", "soil moisture, seed-fertilizer separation and stand-reduction risk")
    if decision == "ambiguous_product_followup":
        return ("the exact product and current label", "the target and crop stage", "the prior application rate and timing", "rain timing, rainfast interval and reapplication restrictions")
    if decision == "sidedress_n_credit_reconciliation":
        return ("current manure analysis, application record, timing, and plant-available nitrogen estimate", "previous-crop identity, stand quality, termination timing, and locally calibrated nitrogen credit", "current soil nitrate or crop nitrogen status plus realistic crop demand and yield potential", "sidedress uptake window, rainfall, drainage, leaching or denitrification risk, and a complete nitrogen budget")
    if decision == "seed_row_fertilizer_safety":
        return ("fertilizer product analysis, nutrient amount, and salt or ammonia-forming risk", "row spacing, opener type, spread or seedbed utilization, and actual seed-fertilizer separation", "seedbed texture, moisture, organic matter, salinity, seed quality, and expected emergence stress", "the current locally calibrated seed-row safety table plus equipment calibration and post-pass placement checks")
    if decision == "wet_area_drainage_differential":
        return ("paired wet-area and normal-area soil profiles, roots, colour, mottles, structure, and restrictive layers", "soil moisture and water-table depth by time plus ponding or saturation duration", "topography, run-on, compaction, existing drainage, outlet elevation and capacity", "crop timing and recovery pattern showing whether excess water, texture, roots, fertility, or disease is limiting growth")
    if decision == "hail_disease_differential":
        return ("storm path and immediate tearing, shredding, bruising, breakage, and impact-facing injury", "marked lesions revisited for expansion, margins, sporulation, pustules, ooze, or other pathogen signs", "affected-versus-unaffected plants across windward, sheltered, edge, and interior zones", "crop stage, storm timing, subsequent wetness, hybrid, prior disease, and representative diagnostic samples when progression remains ambiguous")
    if decision == "corn_common_rust_differential":
        return ("raised orange-brown pustules and powdery spores that rub from both leaf surfaces", "lesion shape, margins, canopy position, field distribution, and progression on new leaves", "spray overlaps or skips, application record, nutrient pattern, hybrid susceptibility, and weather", "representative photographs or samples and current local disease guidance before any fungicide decision")
    if decision == "wild_oat_post_application":
        return ("wild-oat density, patch distribution, emergence cohort, and crop and weed stages", "product, herbicide group, rate, adjuvant, timing, weather, coverage, and antagonism record", "survivor injury and pattern, prior group history, resistance risk, and any local testing", "remaining crop-safe label window, crop competition, harvest or patch tactics, and seed-return prevention")
    if decision == "herbicide_injury_control_failure":
        return ("crop and weed patterns across overlaps, skips, headlands, boom sections, soil zones, and drainage", "product, rate, adjuvant, tank mix, cleanout, nozzle, coverage, timing, and weather records", "crop symptoms and recovery versus weed identity, stage, injury, late emergence, and survivor pattern", "resistance history, current crop stage and label restrictions, and a bounded follow-up or seed-return plan")
    if decision == "greenhouse_tomato_leaf_curl":
        return ("symptom age and distribution by cultivar, bay, row, irrigation zone, and new versus old growth", "temperature, humidity or VPD, light, air movement, substrate water, roots, drainage, EC, pH, and fertigation changes", "representative scouting for mites, whiteflies, aphids, vectors, lesions, mosaics, and distorted growing points", "virus biosecurity and plant movement plus herbicide, growth-regulator, cleaner, or other chemical-exposure records")
    if decision == "winter_injury_differential":
        return ("dieback pattern versus exposure, snow cover, low areas, windward zones, cultivar, and plant age", "cut buds, shoots, cambium, crowns, and roots showing live versus dead tissue", "time for symptoms and regrowth to express plus pruning to live tissue and avoidance of forced weak growth", "lesions, cankers, ooze, progression, and representative diagnostics only where infectious disease remains plausible")
    if decision == "greenhouse_substrate_irrigation":
        return ("container or substrate water content and weight through the irrigation cycle", "emitter flow and distribution uniformity", "applied volume, drain volume or fraction, and drainage timing", "root-zone and drain EC or pH plus crop stage, radiation, temperature, humidity, and VPD")
    if decision == "sweet_corn_harvest_timing":
        return ("representative ears across the block", "kernel fill, milk stage, tenderness, and ear uniformity", "the buyer's maturity and quality specification", "harvest-to-cooling capacity, labour, transport, and field heat")
    if decision == "fusarium_head_blight_risk":
        return ("field-specific heading and flowering or anthesis stage", "recent and forecast moisture, rain, humidity, and temperature through the susceptible window", "host-crop residue, rotation, and local inoculum pressure", "variety susceptibility, current local risk guidance, and label timing if treatment is considered")
    if decision == "fleabane_management":
        return ("confirmed Canada fleabane or horseweed identity", "emergence cohort, current growth stage, density, and distribution", "forage species, stand condition, harvest or grazing constraints, and current crop label", "application history, resistance evidence, seed-return prevention, and integrated cultural or mechanical tactics")
    if decision == "forage_stand_thinning_differential":
        return ("stand age, establishment, winter, harvest, traffic, fertility, and pesticide history", "affected-versus-healthy crown and root condition", "soil moisture, drainage, compaction, restrictive layers, and rooting", "insect signs, disease signs, representative sampling, and stand or stem density")
    if decision == "cutworm_stand_loss":
        return ("freshly cut or wilted plants and active larvae near the soil surface", "representative row-length stand counts across damaged and normal areas", "larvae and injury trend by field zone, crop stage, and remaining stand", "current local action threshold, natural enemies, forecast, and label fit if treatment is justified")
    if decision == "seeding_depth_decision":
        return ("depth to reliable moisture across representative seedbed zones", "texture, aggregation, crusting, and expected rainfall", "seed vigour, seed size, coleoptile or emergence capacity, and seed treatment", "opener depth consistency, furrow closure, seed-to-soil contact, and a post-pass depth check")
    if decision == "crop_irrigation_scheduling":
        return ("calibrated representative root-zone water by depth", "field capacity, available water-holding capacity, rooting depth, and allowable depletion", "crop stage, current stress, and expected crop water use", "recent applied water and rain, short-term forecast, system capacity, infiltration, runoff, and drainage")
    if decision == "nutrient_runoff_risk":
        return ("current soil saturation, frost, infiltration, residue, slope, and concentrated flow paths", "surface-water proximity, setbacks, buffers, and applicable nutrient-management conditions", "nutrient source, form, rate, placement, incorporation, and application timing", "forecast rainfall amount, intensity, timing, uncertainty, and the option to modify or delay")
    if decision == "seed_treatment":
        return ("target pest and field or regional loss history", "planting timing, soil temperature, moisture, and seedling risk", "the exact seed treatment, target pests, current label, and stewardship", "added cost or discount versus expected avoided loss and an untreated comparison")
    if decision == "transplant_establishment":
        return ("transplant uniformity, root-ball condition, root binding, hardening, and source history", "soil and root-zone moisture plus irrigation capacity", "heat, wind, and establishment-weather stress", "culling or segregating weak plants and using starter fertilizer only from crop-specific root-zone evidence")
    if decision == "produce_safety":
        return ("the changed crop-contact water source and timing", "animal or other hazard entry upstream of the intake", "applicable assessment, sampling, records, and food-safety process", "holding or segregating harvest as required rather than treating washing as proof of safety")
    if decision == "openet_irrigation_decision":
        return ("OpenET satellite-model crop-water-use context", "probe calibration, placement, depths, and representative root-zone moisture", "recent rain, applied water, flowmeter records, crop stage, and rooting depth", "forecast demand, system capacity, infiltration, drainage, and water quality")
    if decision == "drip_irrigation_uniformity":
        return ("head-to-end lateral pressure and flow", "emitter output, plugging, leaks, filters, and injector condition", "affected-versus-normal root-zone moisture, salinity, roots, and disease pattern", "zone design, crop stage, weather demand, capacity, drainage, harvest, and food-safety constraints")
    if decision == "irrigation_water_nitrate_credit":
        return ("current representative irrigation-water nitrate analysis with units and well identity", "measured applied-water volume and timing", "crop uptake, nonuniformity, drainage, leaching, denitrification, and local credit guidance", "soil and crop evidence plus all fertilizer, manure, and previous-crop credits")
    if decision == "tile_drainage_decision":
        return ("affected-versus-normal soil and crop observations", "topography, water table, restrictive layers, and saturation timing", "existing drainage, outlet capacity, and survey or design evidence", "downstream, wetland, and local drainage constraints")
    if decision == "spray_weather_window":
        return ("exact crop, target, product, adjuvant, and current label", "on-site wind speed, direction, gusts, inversion, and sensitive areas", "rain and rainfast timing plus efficacy and runoff risk", "delay or reschedule boundary and complete application records")
    if decision == "water_limited_nitrogen_increase":
        return ("current crop condition, rooting, and realistic yield response", "current soil nitrate or representative tissue evidence", "complete nitrogen, irrigation, and applied-input records", "water allocation, remaining uptake window, response trial, and partial budget")
    if decision == "lime_sampling_rate":
        return ("representative sampling zones and sample depth", "measured soil pH plus buffer pH or local lime-requirement method", "crop-rotation target pH and incorporation depth", "lime source neutralizing value, fineness, local calibration, and variable-rate evidence")
    if decision == "forage_defoliator_harvest_decision":
        return ("pest identity and representative edge-versus-interior density and injury", "forage stage, remaining leaf area, drought stress, and injury trend", "natural enemies plus a current local threshold", "planned cutting, treatment cost, current label PHI, and continued scouting")
    if decision == "high_tunnel_yellowing":
        return ("symptom position and pattern, crop stage, fruit load, roots, and root disease", "current fertigation recipe, injector calibration, emitter output, and irrigation uniformity", "current source-water and root-zone EC, root-zone moisture, and drainage", "current soil or tissue evidence plus heat, water, salt, and nutrient differential")
    if decision == "forage_frost_safety":
        return ("frost, drought, and fresh-regrowth prussic-acid risk", "nitrate risk and representative forage testing", "time since frost and plant recovery", "animal class, ration, and local livestock guidance")
    if decision == "postharvest_cooling":
        return ("harvest and pulp temperature", "time in sun or shade before cooling", "crop-appropriate precooling capacity and package airflow", "cold-chain continuity and buyer quality specification")
    if decision == "nematode_management":
        return ("field pattern and affected-normal comparison", "properly timed soil and root samples", "nematode species and population density", "host status, resistance, rotation, treatment value, and economics")
    if decision == "residual_activation":
        return ("rainfall or mechanical incorporation after application", "soil texture, organic matter, pH, rate, and placement", "weed species and emergence timing", "current label, seasonal maximum, emerged-weed control, and overlapping residual")
    if decision == "volunteer_trait_unknown":
        return ("confirmed volunteer crop identity", "previous crop and herbicide-tolerance records", "current crop stage plus volunteer size and density", "current local crop label and integrated seed-return plan")
    if decision == "variable_rate_pk":
        return ("clean calibrated yield data", "representative phosphorus and potassium soil tests with local calibration", "stable ground-truthed management zones and response probability", "replicated checks plus a partial budget and sensitivity analysis")
    if decision == "variety_trial_selection":
        return ("replicated multi-year and multi-location trial evidence", "statistical separation and yield stability", "crop-purpose quality, maturity, disease, lodging, and adaptation", "seed cost, downside risk, and an on-farm comparison where uncertainty remains")
    if decision == "integrated_preharvest_specialty":
        return ("leaf-spot diagnosis and severity", "harvest interval, buyer quality, and worker-entry constraints", "irrigation-water safety and crop-contact history", "current label fit, PHI, REI, and a nonchemical or harvest alternative")
    if decision == "furrow_irrigation_uniformity":
        return ("verified root-zone moisture and infiltrated depth from head to tail", "advance and recession time showing that water reached the tail", "inflow rate, set time, slope, length, and intake rate", "diagnosed infiltration or distribution cause plus a tested correction that limits tailwater")
    if decision == "soil_water_sensor_interpretation":
        return ("sensor calibration and depth", "field capacity and allowable depletion for each soil", "effective rooting depth and crop stage", "current depletion, weather demand, irrigation capacity, and runoff risk")
    if decision == "corn_rootworm_silk_clipping":
        return ("rootworm beetle density", "silk length and clipping severity", "pollination progress and fresh silk emergence", "local threshold and current label fit")
    if decision == "wheat_aphid_treatment":
        return ("aphid species and density per head or tiller", "wheat stage and grain-fill timing", "population trend and natural enemies", "local threshold and current label fit")
    if decision == "wheat_flag_leaf_fungicide":
        return ("likely disease and lower-to-upper canopy movement", "flag-leaf emergence and protection window", "variety susceptibility and weather risk", "severity, label fit, expected yield benefit, and application cost")
    if decision == "weed_preharvest_escape":
        return ("weed identity and seed maturity", "crop stage and harvest timing", "current crop-and-weed label, PHI, and residue restrictions", "nonchemical containment, harvestability, and market constraints")
    if decision == "weed_burndown_survivor":
        return ("weed identity, size, and growth stage", "application record and growing conditions", "resistance versus application failure", "labeled alternative tactics and seed-return prevention")
    if decision == "weed_seed_return_management":
        return ("weed identity and seed maturity", "practical seed-return reduction in patches", "application record and resistance evidence", "integrated residual, postemergence, cultural, and sanitation plan")
    if decision == "cold_wet_purple_corn":
        return ("temporary cold-wet restriction of phosphorus uptake", "hybrid expression and field pattern", "roots, drainage, compaction, and fertilizer placement", "calibrated soil test and recovery as soils warm")
    if decision == "soybean_idc":
        return ("young-leaf interveinal chlorosis and field pattern", "high-pH carbonate or bicarbonate soil", "wetness, drainage, salinity, and root health", "IDC-tolerant varieties and locally validated field management")
    if decision == "sulfur_nitrogen_differential":
        return ("young-versus-old leaf symptom position", "flowering and field uniformity", "soil texture, organic matter, rainfall, and fertilizer history", "paired affected-normal plant and soil samples")
    if decision == "localized_weather_event":
        return ("current authoritative forecast and alerts", "radar or nowcast storm movement", "forecast probability and timing uncertainty", "field observations and a low-regret operational contingency")
    if decision == "stratified_soil_sampling":
        return ("stable contrasting landscape and management zones", "separate representative samples for each zone", "consistent depth, timing, and laboratory method", "georeferenced results interpreted with current local calibration")
    if decision == "potato_storage_conditioning":
        return ("intended market and harvest maturity", "pulp temperature, skin set, bruising, and disease risk", "lot condition and the actual storage and airflow system", "conditioning response from representative tubers and storage sensors")
    if decision == "fruit_set_diagnostic":
        return (f"{crop or 'crop'} flower type and reproductive biology", "effective pollination or parthenocarpic cultivar status", "temperature and root-zone water stress", "bloom-time pesticide exposure, nutrition, disease, and fruit abortion")
    if decision == "pest_treatment":
        return ("pest identity and active life stage", "representative population or injury measurement", "crop stage and economic threshold", "population trend, natural enemies, and current label fit")
    if decision == "weed_escape_management":
        return ("weed identity, growth stage, and escape map", "application record and resistance-versus-application-failure evidence", "preventing seed return and spread", "multiple effective chemical and nonchemical tactics for the next cycle")
    if decision == "soil_crusting":
        return ("whether a true surface crust is sealing emergence", "seedling depth, injury, and remaining energy", "surface moisture and crop injury from a test pass", "stand recovery and replant evidence")
    if decision == "compaction_tillage":
        return ("root and traffic pattern", "restriction depth measured at comparable soil moisture", "drainage versus mechanical compaction", "whether tillage can fracture the layer without smearing and re-compaction")
    if decision == "physiological_disorder":
        return ("the affected crop tissue and growth pattern", "water and calcium transport through roots and transpiration", "growth rate, salinity, fertility, and root stress", "management of the transport constraint rather than automatic calcium application")
    if decision == "salinity_management":
        return ("irrigation-water and root-zone salinity tests", "sodium and infiltration risk", "crop tolerance and symptom pattern", "irrigation uniformity, leaching-water quality, and drainage capacity")
    if decision == "flood_recovery":
        return ("crop stage and growing-point position", "depth and duration of submergence", "water and air temperature plus oxygen stress", "new growth, root health, disease, and surviving stand after drainage")
    if decision == "freeze_recovery":
        return ("crop stage and growing-point position", "freeze severity and duration", "new growth after warm recovery weather", "healthy growing points and representative surviving stand")
    if decision == "pollination_stress":
        return ("root-zone water stress", "silk emergence and receptivity relative to pollen shed", "tassel and pollen activity", "early fertilization and kernel-set observations")
    if decision == "maturity_switch":
        return ("actual planting date", "hybrid relative maturity or heat-unit requirement", "heat units and frost risk remaining", "yield, drydown, harvest-moisture, and drying-cost tradeoffs")
    if decision == "wilt_differential":
        return ("root-zone moisture and irrigation response", "field pattern and overnight recovery", "root, crown, and vascular symptoms", "representative diagnostic sample when disease signs persist")
    if decision == "cover_crop_termination":
        return ("soil moisture by depth and rainfall outlook", "cover-crop species, water use, and termination method", "erosion protection, residue, and grazing tradeoffs", "the next-crop planting and establishment window")
    if decision == "fertility_rate":
        return (
            f"current {crop or 'crop'} condition and realistic response potential",
            "current soil or tissue evidence",
            "actual nutrient applications and credits stated in the record",
            "the field's stated water and loss pathway",
        )
    if decision == "planting_window":
        return (
            "seed-zone moisture and temperature",
            "trafficability and seedbed fitness",
            f"{crop or 'crop'}-specific establishment risk",
            "the short forecast and cost of delay",
        )
    if decision == "field_trafficability":
        return (
            "a fresh comparison of the affected and normal areas",
            "standing water, ponding or drainage, and recent rain or irrigation",
            "soil condition below the surface under the intended equipment load",
            "rutting, smearing, compaction, crop-damage, and operator-safety stop conditions",
        )
    if decision == "fungicide_decision":
        return ("diagnosis", "disease incidence and severity", "crop stage and susceptibility", "weather risk, current label fit, and economics")
    if decision == "harvest_storage":
        return (f"{crop or 'crop'} maturity and harvest condition", "weather window", "handling damage and quality", "crop-specific storage conditions")
    if decision == "seed_quality":
        return (f"{crop or 'crop'} planting-material biology", "lot health and quality", "storage and handling history", "field establishment conditions")
    if decision == "source_interpretation":
        return ("source geographic coverage", "measure and crop-year definition", "spatial resolution", "field records needed to ground the prior")
    if decision == "regional_statistics":
        return (
            "the statistic's crop, measure, units, geography, and year",
            "suppression, revision, and aggregation limits",
            "the regional trend or comparison the statistic can support",
            "field records needed before changing this year's plan",
        )
    if decision == "practice_economics":
        return (
            "added and reduced costs",
            "added and reduced returns or risk reduction",
            "field response evidence and time horizon",
            "sensitivity to response, price, cost, and weather",
        )
    return ("the user's stated observation", "the evidence that changes the decision", "the next field action")


def _premise_anchors(decision: str) -> tuple[PremiseAnchor, ...]:
    anchors: dict[str, tuple[PremiseAnchor, ...]] = {
        "clubroot_containment": (
            PremiseAnchor(
                "clubroot_confirmation",
                "suspected clubroot with representative confirmation",
                (r"\bsuspected clubroot\b", r"\brepresentative (?:sample|confirmation)\b", r"\bconfirm(?:ation)?\b"),
            ),
            PremiseAnchor(
                "clubroot_immediate_containment",
                "immediate patch, traffic, soil-movement, or sanitation containment",
                (r"\bmark (?:the )?patch\b", r"\brestrict (?:traffic|movement)\b", r"\bclean (?:soil from )?(?:equipment|machinery)\b", r"\bsanitation\b"),
            ),
        ),
        "fall_banded_nitrogen": (
            PremiseAnchor(
                "fall_n_loss_mechanism",
                "soil temperature, nitrogen form, saturation, drainage, or denitrification loss risk",
                (r"\bsoil temperature\b", r"\bnitrogen form\b", r"\bsaturat", r"\bdrainage\b", r"\bdenitrif"),
            ),
            PremiseAnchor(
                "fall_n_placement_tradeoff",
                "fall-banded versus spring-banded placement and local moisture tradeoffs",
                (r"\bfall[- ]banded\b[^.]{0,100}\bspring[- ]banded\b", r"\bband(?:ed|ing)\b[^.]{0,80}\bplacement\b", r"\bseedbed moisture\b"),
            ),
            PremiseAnchor(
                "fall_n_form_or_placement",
                "nitrogen form, transformation, soil temperature, or band-placement loss conditions",
                (r"\bsoil temperature\b", r"\bnitrogen form\b", r"\bnitrification\b", r"\bammonium\b", r"\bnitrate\b", r"\b(?:band|placement)\b[^.]{0,80}\b(?:shallow|cloddy|volatiliz)"),
            ),
        ),
        "high_p_starter_decision": (
            PremiseAnchor(
                "high_p_response_logic",
                "Olsen phosphorus calibration and response probability",
                (r"\bOlsen\b", r"\blocal calibration\b", r"\bresponse (?:probability|category)\b", r"\bcrop removal\b"),
            ),
            PremiseAnchor(
                "soybean_starter_safety",
                "seed-placed phosphorus safety and placement constraints",
                (r"\bseed[- ]placed phosphorus\b", r"\bseed safety\b", r"\brow width\b", r"\bopener\b", r"\bseed[- ]fertilizer separation\b", r"\bstand reduction\b"),
            ),
            PremiseAnchor(
                "high_p_response_economics",
                "the lower expected response at high Olsen phosphorus and the maintenance or crop-removal objective",
                (r"\bresponse\b[^.]{0,90}\b(?:decrease|lower|unlikely|probability)\b", r"\bmaintenance\b", r"\bcrop removal\b", r"\binsurance\b[^.]{0,80}\b(?:response|economic|maintenance)"),
            ),
        ),
        "ambiguous_product_followup": (
            PremiseAnchor(
                "missing_product_context",
                "the exact product, target, prior application, and current label",
                (r"\bexact product\b", r"\btarget (?:pest|weed|disease)\b", r"\bprior application\b", r"\bcurrent label\b"),
            ),
            PremiseAnchor(
                "rain_rate_hold",
                "a hold on rate or timing until rainfast and reapplication constraints are known",
                (r"\bcannot confirm (?:the )?(?:rate|timing)\b", r"\bdo not (?:repeat|assume|apply)\b", r"\brainfast", r"\breapplication\b"),
            ),
        ),
        "openet_irrigation_decision": (
            PremiseAnchor(
                "satellite_et_source",
                "OpenET as satellite or modeled ET context",
                (r"\bopenet\b", r"\bsatellite(?:[- ]model(?:ed)?)?\b", r"\bmodel(?:ed)?\s+(?:ET|evapotranspiration)\b"),
            ),
            PremiseAnchor(
                "field_water_measurement",
                "the field probe or representative root-zone measurement",
                (r"\bprobe\b", r"\bsensors?\b", r"\broot[- ]zone (?:moisture|water)\b"),
            ),
        ),
        "drip_irrigation_uniformity": (
            PremiseAnchor(
                "drip_delivery_system",
                "the drip lateral or emitter delivery system",
                (r"\bdrip\b", r"\blaterals?\b", r"\bemitters?\b"),
            ),
            PremiseAnchor(
                "hydraulic_uniformity",
                "pressure, flow, plugging, or distribution uniformity",
                (r"\bpressure\b", r"\bflow\b", r"\bplug(?:ged|ging)?\b", r"\bdistribution uniformity\b"),
            ),
        ),
        "irrigation_water_nitrate_credit": (
            PremiseAnchor(
                "irrigation_water_nitrate",
                "nitrate measured in irrigation or well water",
                (r"\b(?:irrigation|well)[- ]?water\b[^.]{0,80}\bnitrate\b", r"\bnitrate\b[^.]{0,80}\b(?:irrigation|well)[- ]?water\b"),
            ),
            PremiseAnchor(
                "nitrogen_credit",
                "the fertilizer or nitrogen-budget credit decision",
                (r"\bnitrogen credit\b", r"\bfertilizer credit\b", r"\bnitrogen budget\b", r"\bcredit(?:ed|ing)?\b"),
            ),
        ),
        "tile_drainage_decision": (
            PremiseAnchor(
                "drainage_installation",
                "the tile or drainage-placement decision",
                (r"\btile\b", r"\bdrain(?:age|s|ed|ing)?\b"),
            ),
            PremiseAnchor(
                "wetness_ground_truth",
                "ground-truth evidence for persistent wetness",
                (r"\bground[- ]truth\b", r"\bwater table\b", r"\bsoil (?:profile|pit)\b", r"\baffected and (?:normal|unaffected)\b", r"\boutlet\b"),
            ),
        ),
        "spray_weather_window": (
            PremiseAnchor(
                "application_label",
                "the exact product and label application window",
                (r"\b(?:product )?label\b", r"\bexact (?:crop|target|product)\b"),
            ),
            PremiseAnchor(
                "wind_sensitive_area",
                "wind, drift, and the sensitive area",
                (r"\bwind\b", r"\bgusts?\b", r"\bdrift\b", r"\bsensitive (?:area|crop|site|shelterbelt)\b", r"\bshelterbelt\b"),
            ),
            PremiseAnchor(
                "rainfast_or_delay",
                "rainfast timing or a delay decision",
                (r"\brainfast\b", r"\bstorm\b", r"\bdelay\b", r"\breschedul\w*\b"),
            ),
        ),
        "weed_preharvest_escape": (
            PremiseAnchor(
                "preharvest_interval",
                "harvest timing, PHI, or preharvest restrictions",
                (r"\bPHI\b", r"\bpreharvest interval\b", r"\bharvest (?:timing|interval|restriction)\b", r"\btime to harvest\b"),
            ),
            PremiseAnchor(
                "current_crop_target_label",
                "the current crop, target, and product label fit",
                (r"\bcurrent (?:product )?label\b", r"\bexact (?:crop|target|product)\b", r"\bcrop and (?:weed|target)\b", r"\blabel(?:ed)? for\b"),
            ),
            PremiseAnchor(
                "harvest_containment",
                "a practical harvest, segregation, removal, or equipment-cleaning containment action",
                (r"\bharvest (?:infested areas? )?(?:last|separately)\b", r"\bsegregat\w*\b", r"\bclean (?:the )?equipment\b", r"\bremove isolated (?:plants|patches)\b"),
            ),
        ),
        "forage_defoliator_harvest_decision": (
            PremiseAnchor(
                "representative_edge_interior_sampling",
                "representative pest and injury sampling across the edge and interior",
                (r"\brepresentative\b[^.]{0,80}\b(?:edge|interior|field)\b", r"\bedge\b[^.]{0,80}\binterior\b"),
            ),
            PremiseAnchor(
                "cutting_stress_tradeoff",
                "planned cutting together with forage stage or drought stress",
                (r"\b(?:cut|cutting|harvest)\b[^.]{0,100}\b(?:drought|stress|regrowth|crop stage|forage stage)\b", r"\b(?:drought|stress|regrowth)\b[^.]{0,100}\b(?:cut|cutting|harvest)\b"),
            ),
            PremiseAnchor(
                "threshold_beneficials",
                "a current local threshold and natural enemies or beneficials",
                (r"\bthreshold\b[^.]{0,100}\b(?:beneficial|natural enem)\w*\b", r"\b(?:beneficial|natural enem)\w*\b[^.]{0,100}\bthreshold\b"),
            ),
        ),
        "high_tunnel_yellowing": (
            PremiseAnchor(
                "nitrogen_hold",
                "a hold on raising nitrogen until the cause is diagnosed",
                (r"\bdo not (?:raise|increase|add)\b[^.]{0,35}\bnitrogen\b", r"\bcannot determine (?:whether|if)\b[^.]{0,45}\bnitrogen\b", r"\bbefore (?:raising|increasing|changing)\b[^.]{0,35}\bnitrogen\b"),
            ),
            PremiseAnchor(
                "fertigation_delivery",
                "the fertigation recipe or injector plus emitter output or uniformity",
                (r"\bfertigation recipe\b[^.]{0,100}\b(?:injector|emitter|uniformity)\b", r"\binjector\b[^.]{0,100}\b(?:emitter|uniformity)\b", r"\bemitter\b[^.]{0,100}\b(?:fertigation|injector)\b"),
            ),
            PremiseAnchor(
                "water_salt_root_evidence",
                "current EC, root-zone moisture, roots, or soil and tissue evidence",
                (r"\b(?:source[- ]water|root[- ]zone|soil) EC\b", r"\broot[- ]zone (?:soil )?moisture\b", r"\bcurrent (?:soil|tissue) (?:test|evidence|result)\b", r"\broot (?:condition|health|disease|inspection)\b"),
            ),
        ),
        "water_limited_nitrogen_increase": (
            PremiseAnchor(
                "nitrogen_rate_decision",
                "the nitrogen or variable-rate increase decision",
                (r"\bnitrogen\b", r"\bUAN\b", r"\bvariable[- ]rate\b"),
            ),
            PremiseAnchor(
                "water_limited_response",
                "water limitation or drought-constrained crop response",
                (r"\bwater[- ]limit\w*\b", r"\bwater allocation\b", r"\bdrought\b", r"\bdry spell\b", r"\birrigation capacity\b"),
            ),
            PremiseAnchor(
                "current_nitrogen_evidence",
                "current nitrate or tissue evidence and response economics",
                (r"\bsoil nitrate\b", r"\btissue (?:test|evidence|result)\b", r"\bpartial budget\b", r"\bcheck strips?\b", r"\bfield trial\b"),
            ),
        ),
        "lime_sampling_rate": (
            PremiseAnchor(
                "representative_lime_sampling",
                "representative sampling or management zones",
                (r"\brepresentative sampl\w*\b", r"\bmanagement zones?\b", r"\bseparate sampl\w*\b", r"\bvariability\b"),
            ),
            PremiseAnchor(
                "lime_requirement_and_quality",
                "buffer pH or lime requirement plus lime-source quality",
                (r"\bbuffer pH\b", r"\blime requirement\b", r"\bneutralizing value\b", r"\bCCE\b", r"\bECCE\b", r"\bfineness\b"),
            ),
        ),
        "soil_crusting": (
            PremiseAnchor(
                "surface_crust",
                "the surface crust and emerging seedlings",
                (r"\bsurface crust\b", r"\bsoil crust\b", r"\bhypocotyl\b"),
            ),
            PremiseAnchor(
                "test_pass_and_stand",
                "a test pass, seedling injury check, or representative stand assessment",
                (r"\btest (?:a |one )?(?:short )?pass\b", r"\bseedling (?:injury|loss)\b", r"\bstand count\b", r"\brotary hoe\b"),
            ),
        ),
        "maturity_switch": (
            PremiseAnchor(
                "planting_date_and_maturity",
                "actual planting date and relative maturity",
                (r"\bactual planting date\b", r"\brelative[- ]maturity\b", r"\bmaturity group\b"),
            ),
            PremiseAnchor(
                "remaining_season_tradeoff",
                "remaining heat or frost risk and harvest drydown tradeoff",
                (r"\bheat units?\b", r"\bfrost risk\b", r"\bdrydown\b", r"\bharvest moisture\b", r"\bdrying cost\b"),
            ),
        ),
        "physiological_disorder": (
            PremiseAnchor(
                "calcium_transport_disorder",
                "blossom-end rot or a calcium-delivery disorder",
                (r"\bblossom[- ]end rot\b", r"\btipburn\b", r"\bcalcium[- ]delivery\b", r"\bcalcium[- ]transport\b"),
            ),
            PremiseAnchor(
                "root_zone_driver",
                "root-zone water, salinity, or root function",
                (r"\broot[- ]zone moisture\b", r"\birrigation\b", r"\bsalinity\b", r"\broot (?:injury|function|stress)\b"),
            ),
        ),
        "freeze_recovery": (
            PremiseAnchor(
                "growing_point_recovery",
                "growing-point condition and new growth after recovery weather",
                (r"\bgrowing points?\b", r"\bnew (?:leaf )?growth\b"),
            ),
            PremiseAnchor(
                "surviving_stand_decision",
                "surviving stand and replant or termination economics",
                (r"\bsurviving plants?\b", r"\bstand (?:count|uniformity)\b", r"\breplant(?:ing)?\b"),
            ),
        ),
        "weed_seed_return_management": (
            PremiseAnchor(
                "current_seed_return",
                "current-season seed return and patch containment",
                (r"\bseed return\b", r"\bseed production\b", r"\bharvest infested\b", r"\bclean equipment\b"),
            ),
            PremiseAnchor(
                "resistance_and_integrated_plan",
                "application-failure or resistance evidence and an integrated next plan",
                (r"\bapplication failure\b", r"\bresistance\b", r"\bintegrated labeled tactics\b", r"\bmultiple effective tactics\b"),
            ),
        ),
    }
    if decision == "drought_nitrogen_adjustment":
        return anchors["water_limited_nitrogen_increase"]
    return anchors.get(decision, ())
