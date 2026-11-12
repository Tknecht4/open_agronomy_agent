"""Bounded observation methods shared by drafting, holds and verification.

These are project-authored methods, not measurements, diagnoses, current labels
or locally calibrated prescriptions. Source rationale lives in the operations
guide. Never load assessment questions, gold or reviewer labels here.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import re

from agronomy_agent.answerability import preferred_response_language, is_rate_basis_explanation


@dataclass(frozen=True)
class ObservationGuidance:
    key: str
    answer: str
    # Every facet is required; alternatives within a facet accept equivalent prose.
    facets: tuple[tuple[str, str, tuple[str, ...]], ...]
    method_ids: tuple[str, ...] = ()

    def has_method(self, key: str) -> bool:
        return self.key == key or key in self.method_ids

    def missing(self, answer: str) -> tuple[str, ...]:
        return tuple(name for name, _, patterns in self.facets
                     if not any(re.search(p, answer, re.I) for p in patterns))

    def unsupported_inference(self, answer: str) -> bool:
        """Reject bounded contradictions even when a correct check is appended."""
        for sentence in re.split(r"[.!?;]\s*|\n+", answer):
            if self.has_method("scouting_unit_interpretation"):
                if (
                    re.search(r"\bbelow\b[^.!?]{0,70}\bthreshold\b", sentence, re.I)
                    and re.search(r"\b(?:means?|therefore|suggests?|deemed)\b", sentence, re.I)
                    and re.search(r"\b(?:no|not|unnecessary|stop)\b[^.!?]{0,75}\b(?:sampl|scout)\w*|\b(?:sampl|scout)\w*[^.!?]{0,60}\b(?:not|unnecessary)\b", sentence, re.I)
                    and not re.search(r"\b(?:does not mean|doesn't mean|not a reason|rather than|continue|still require|still need)\b", sentence, re.I)
                ):
                    return True
            if self.has_method("empty_terrain_coverage"):
                if re.search(
                    r"\b(?:absence|empty|no (?:mapped )?features?|lack of data)\b[^.!?]{0,160}"
                    r"\b(?:suggest\w*|indicat\w*|means?|proves?|confirms?)\b[^.!?]{0,100}"
                    r"\b(?:low(?:er)?[- ]risk|(?:low|lower|reduced|minimal|no) (?:waterlogging )?risk|lack of coverage|missing coverage|no coverage)\b",
                    sentence, re.I,
                ) and not re.search(r"\b(?:does not|do not|cannot|can't|doesn't|not enough to)\s+(?:by itself\s+)?(?:suggest|indicat|mean|prove|confirm)\w*", sentence, re.I):
                    return True
            if self.has_method("point_area"):
                if re.search(r"\b(?:area|size)\b[^.;]{0,35}\b(?:covered by|of)\b[^.;]{0,25}\b(?:pin|point)\b", sentence, re.I):
                    return True
                if re.search(r"\b(?:simplest|only|sufficient)\b[^.;]{0,160}\b(?:known|single|one) (?:distance|dimension|scale|reference point)\b", sentence, re.I) and not re.search(r"\b(?:not|insufficient|both|length and width|closed boundary|closed polygon)\b", sentence, re.I):
                    return True
                if re.search(r"\b(?:estimate slope length|use benchmark sites|directed benchmark sampling)\b", sentence, re.I) and not re.search(r"\b(?:not|cannot|insufficient|doesn't)\b", sentence, re.I):
                    return True
        return False


def sample_event_roles_stated(question: str) -> bool:
    """The request names collection and report issuance as separate events."""
    return bool(
        re.search(r"\bsampl\w*\b[^.!?;]{0,80}\b(?:collected|collection date)\b", question, re.I)
        and re.search(r"\breport\b[^.!?;]{0,80}\b(?:issued|issuance|issue date)\b", question, re.I)
    )


def observation_guidance(question: str) -> ObservationGuidance | None:
    methods = tuple(_matching_observation_methods(question))
    if not methods:
        return None
    if len(methods) == 1:
        return methods[0]
    return ObservationGuidance(
        "combined_observations",
        "\n\n".join(method.answer for method in methods),
        tuple(facet for method in methods for facet in method.facets),
        tuple(method.key for method in methods),
    )


def _matching_observation_methods(question: str) -> Iterator[ObservationGuidance]:
    q = question.lower()
    has = lambda p: bool(re.search(p, q))
    # English method text must never replace a French answer.
    if preferred_response_language(question) == "fr" or has(r"\b(?:en fran[cç]ais|in french)\b"):
        return None
    if is_rate_basis_explanation(question):
        parts: list[str] = []
        facets: list[tuple[str, str, tuple[str, ...]]] = []
        if has(r"\b(?:label|pesticide)\b"):
            parts.append("A pesticide label rate states the product amount or concentration for a specified labelled use and formulation. Read the label's stated product or active-ingredient basis and units; do not assume they are interchangeable. An application rate is distinct from a maximum residue limit, which concerns residue remaining in food.")
            facets.append(("label_rate_basis", "Explain the amount/concentration basis specified by the product label.", (r"\b(?:amount|quantity|concentration)\b[^.]{0,100}\b(?:product|label|pesticide|formulation)\b", r"\b(?:product|label|pesticide|formulation)\b[^.]{0,100}\b(?:amount|quantity|concentration)\b")))
        elif has(r"\bproduct\b"):
            parts.append("A product rate describes the amount of the commercial formulation on its stated application basis, such as product mass or volume per area.")
            facets.append(("product_rate_basis", "Explain the commercial-product amount basis.", (r"\bproduct\b[^.]{0,100}\b(?:amount|mass|volume|quantity)\b", r"\b(?:amount|mass|volume|quantity)\b[^.]{0,100}\bproduct\b")))
        if has(r"\bnutrient\b"):
            parts.append("For a field application, a fertilizer nutrient rate commonly expresses the mass of a named nutrient per area. Other application systems may use an explicitly stated concentration or volume basis. Use the declared nutrient basis and product analysis to convert nutrient mass into product amount; it is not a nutrient concentration measured in the crop or soil.")
            facets.append(("nutrient_rate_basis", "Explain nutrient mass per area, distinct from product amount or measured crop concentration.", (r"\b(?:mass|amount|kg|kilograms?|lb|pounds?)\b[^.]{0,100}\b(?:nutrient|nitrogen|phosphorus|N|P|K)\b[^.]{0,60}\b(?:area|hectare|ha|acre|ac)\b", r"\bnutrient\b[^.]{0,60}\bmass per (?:unit )?area\b")))
        yield ObservationGuidance("rate_basis_terms", "\n\n".join(parts), tuple(facets))
    if has(r"\b(?:pests?|insects?|aphids?)\b") and has(r"\b(?:regional|area|regional-scale)\s+(?:insect\s+|pest\s+)?alert\b") and has(r"\b(?:count\w*|threshold|infestation)\b"):
        yield ObservationGuidance("regional_pest_alert", (
            "A regional insect alert or map pin does not establish field infestation or that a threshold is exceeded. "
            "Confirm the pest identity and active life stage, then scout representative locations across the field, including interior and normal areas. "
            "Collect representative field counts of pest population density or measure injury with the appropriate crop-and-pest sampling method; identifying the pest alone is not the field measurement. "
            "Compare those observations with a current local economic or action threshold on the same sampling units and crop stage. "
            "Record population trend and natural enemies, and continue or repeat sampling when uncertainty remains. Verify the current product label only if treatment is justified."
        ), (
            ("alert_field_measurement", "Obtain representative field population or injury measurements, not identity alone.", (r"\b(?:representative|field|scout)\b[^.]{0,100}\b(?:count\w*|density|injury)\b", r"\b(?:count\w*|density|injury)\b[^.]{0,100}\b(?:representative|field|scout)\b")),
            ("alert_local_threshold", "Match field observations to the applicable local crop-and-pest threshold.", (r"\b(?:local|economic|action)\b[^.]{0,50}\bthreshold\b",)),
            ("alert_trend_enemies", "Retain population trend and natural-enemy observations.", (r"\b(?:trend|natural enem|beneficial)\w*\b",)),
        ))
    if has(r"\b(?:aphids?|pests?|insects?)\b") and has(r"\b(?:scout\w*|sampl\w*)\b") and has(r"\b(?:threshold units?|counting basis|sampling units?)\b"):
        yield ObservationGuidance("scouting_unit_interpretation", (
            "Scout representative interior locations across the field, including affected and normal areas; an edge hotspot alone is not a field-wide count. "
            "Use the sampling method and units in current local guidance for the crop and pest. Match the same counting basis: counts per plant, tiller or sweep are not interchangeable without a validated relationship. "
            "Record crop and pest stage, population trend, natural enemies and sampling variability. If observations are sparse, patchy, inconsistent or near a decision boundary, follow the applicable resampling or sequential-sampling protocol. "
            "An action threshold does not by itself establish sample adequacy or permission to spray; below-threshold populations can still require monitoring."
        ), (
            ("scouting_representative", "Explain representative field-interior coverage rather than one hotspot.", (r"\bfield interior\b", r"\binterior locations\b", r"\bacross (?:the )?field\b", r"\bnormal areas\b")),
            ("scouting_unit_basis", "Match observations and threshold on the same counting basis.", (r"\bsame (?:counting )?basis\b", r"\bmatching (?:sampling|counting) units\b", r"\b(?:per plant|per tiller|per sweep)\b")),
            ("sampling_adequacy", "Use sampling uncertainty/variability and appropriate repeat sampling, not threshold position alone.", (r"\bsampling (?:uncertainty|variability)\b", r"\b(?:sparse|patchy|precision|representativeness|resampl\w*)\b", r"\badditional representative samples\b")),
        ))
    if sample_event_roles_stated(question) and has(r"\b(?:sampling dates?|sample date|collection date|which date|preserv\w*)\b"):
        yield ObservationGuidance("sample_record_dates", (
            "Use the actual sample collection date as the sampling-event date when comparing seasons. "
            "Preserve the laboratory report issuance date in a separate field linked to the sample identifier "
            "and original report. Keep an analysis or processing date separately if supplied; do not infer it "
            "from report issuance. Compare sampling depth, timing and analytical method as well as the dates."
        ), (
            ("date_collection", "Use the collection event for sampling-date comparisons.", (r"\bcollection date\b", r"\bdate of collection\b", r"\bsampling[- ]event date\b")),
            ("date_report", "Preserve the report issuance event under its own role.", (r"\breport (?:issuance|issue) date\b", r"\bdate (?:the )?(?:lab(?:oratory)? )?report was issued\b")),
            ("date_separation", "Keep distinct events and their provenance linked without overwriting.", (r"\bseparate\b", r"\bdistinct\b", r"\b(?:retain|keep|preserve) both\b")),
        ))
    if has(r"\b(?:ndvi|vegetation index)\b") and has(r"\b(?:compar\w*|dates?|lower|declin\w*|chang\w*)\b"):
        yield ObservationGuidance("imagery_comparison", (
            "A lower displayed NDVI alone does not establish a real crop-vigor decline, a cause, or a yield loss. "
            "First check each scene's cloud, shadow, snow and other QA masks, valid pixel counts and valid field coverage. "
            "Match the field boundary and comparable spatial support; check sensor/product definitions, harmonization, processing and resolution. Documented harmonization such as HLS can make different sensors comparable, subject to QA and remaining uncertainty. Use comparable valid pixels rather than different clear fragments of the field. "
            "Then compare acquisition dates, crop stage, canopy cover, harvest and management history. Only after those checks should you scout the corresponding affected and normal areas, including roots and soil moisture, to test possible causes. "
            "Until QA and comparable support are available, the apparent difference remains unverified and cannot justify a treatment."
        ), (
            ("imagery_qa", "Check cloud/shadow masks before interpreting a change.", (r"\b(?:cloud|shadow)\b[^.]{0,90}\b(?:mask|QA)",)),
            ("imagery_support", "Check valid pixel count/coverage and comparable spatial support.", (r"\bvalid (?:pixel|field|coverage)",)),
            ("imagery_comparability", "Compare processing and crop stage before causal interpretation.", (r"\b(?:processing|sensor|product)\b",)),
            ("imagery_stage", "Check crop stage or phenology on both dates.", (r"\b(?:crop|growth) stage\b", r"\bphenolog")),
        ))
    area_clauses = re.split(
        r"[.!?;]|\b(?:and|also)\s*,?\s*(?=(?:can|could|does|is|what|how|should|will|do|may)\b)",
        q,
    )
    if (
        has(r"\b(?:gps|dropped|single|one)\b[^.]{0,35}\b(?:pin|point)\b")
        and any(
            re.search(r"\barea\b", clause)
            and not re.search(r"\b(?:pixels?|buffers?|footprints?|sampling support)\b", clause)
            for clause in area_clauses
        )
    ):
        yield ObservationGuidance("point_area", (
            "One GPS pin locates a point; it does not describe the planted area. Trace or survey the planted boundary to make a closed polygon. "
            "For a genuinely rectangular planted block, measure both length and width and multiply them in compatible units. "
            "A known distance or scale alone still leaves the other dimension and field shape unknown. Exclude unplanted areas; an estimated field boundary need not equal the area actually planted."
        ), (("area_shape", "Require a closed boundary or both dimensions of a known shape.", (r"\b(?:closed (?:polygon|boundary)|length and width|both dimensions)\b",)),))
    if has(r"\b(?:mapaq|lidar|terrain)\b") and has(
        r"\b(?:zero|no)\s+(?:mapped\s+)?(?:depressions?|flow[- ]paths?|intersections?|features?)\b|\bempty\b[^.]{0,50}\b(?:clip|layer|result)\b"
    ):
        yield ObservationGuidance("empty_terrain_coverage", (
            "No mapped intersection does not establish absence of waterlogging risk. Verify source parcel coverage and missing or excluded areas, the acquisition period and age, layer completeness, the saved field boundary and the clipping CRS. "
            "An empty clip means no features from that layer intersected that boundary; it cannot distinguish true absence from missing coverage. "
            "Ground-truth low and normal areas after rain: record ponding duration, soil moisture by depth, roots, infiltration, drainage and outlet condition, and compaction. "
            "Mapped terrain cannot establish current saturation or a drainage design without those field observations."
        ), (
            ("terrain_coverage", "Check source parcel coverage before interpreting absence.", (r"\b(?:source|parcel|layer) coverage\b",)),
            ("terrain_age", "Check acquisition period/age separately from publication.", (r"\bacquisition\b",)),
        ))
    guide_scope = has(r"\b(?:guide|table|manual)\b") and has(r"\bvegetable\w*\b")
    haskap = False
    if guide_scope:
        # query_context also uses the router: resolve its canonical aliases at
        # request time rather than introducing an import-time dependency cycle.
        from agronomy_agent.query_context import extract_crop_entities

        haskap = "haskap" in extract_crop_entities(question)
    if guide_scope and (haskap or has(r"\b(?:perennial berr\w*|berry shrub)\b")):
        yield ObservationGuidance("crop_guide_applicability", (
            "A vegetable spacing or fertilizer table is not a planting prescription for a perennial berry crop. "
        ) + ("Haskap (honeyberry) is a perennial fruit crop that needs compatible cultivars with overlapping bloom for cross-pollination. " if haskap else "") + (
            "Check the guide's named crop, production system and region before transferring any table. Use crop-specific perennial-berry guidance to plan mature plant size, row and in-row spacing, machinery and harvest access. Check crop- and cultivar-specific pollination requirements. "
        ) + (
            "Raspberries are generally self-fruitful, so another cultivar is not normally required for pollination; pollinating insects still matter. "
            if has(r"\braspberr(?:y|ies)\b") else ""
        ) + (
            "For fertility, distinguish establishment from bearing years and use current soil tests and locally appropriate crop guidance; do not copy a vegetable rate. "
            "General sampling or soil-preparation principles may transfer with their limits, but they do not establish suitable spacing or a locally calibrated fertilizer recommendation."
        ), (
            ("guide_crop_fit", "Explain vegetable versus perennial fruit production scope.", (r"\bperennial\b",)),
            ("guide_layout", "Check mature plant size and harvest access for layout.", (r"\b(?:mature plant|harvest access|machinery)\b",)),
            ("guide_rate_transfer", "Do not transfer the table's crop-specific fertilizer rates.", (r"\b(?:do not copy|not.*prescription|locally calibrated)\b",)),
        ))
    if has(r"\b(?:crop[- ]health|national.*stress|regional.*stress)\b") and has(r"\b(?:map|layer|index|indices|patch)\b"):
        nitrogen = has(r"\b(?:nitrogen|fertiliz\w*)\b")
        yield ObservationGuidance("regional_crop_signal", (
            "A crop-health or stress layer is a screening signal, not a field diagnosis of drought, nutrient deficiency or a named disease. "
            "Verify the exact metric, date, spatial resolution, source and uncertainty; distinguish modelled weather/water-balance context from satellite, aerial or other observations before interpreting it. "
            "Scout affected and normal areas, including the field interior: record crop stage, plant and leaf symptoms, incidence or severity, roots, root-zone moisture, drainage, compaction and recent weather. "
            "Waterlogging, drought, root injury, nutrient constraints and disease remain alternatives until those observations discriminate them. Arrange timely crop-specific diagnostic sampling if disease is suspected. "
        ) + (
            "For a nitrogen decision, reconcile fertilizer already applied, manure and previous-crop credits with a current soil nitrate test or crop nitrogen status, realistic yield response, available water and the remaining uptake window; use current local calibration. "
            if nitrogen else ""
        ) + (
            "Do not change management from the map alone; a pesticide application also needs current crop/target/product label authority."
        ), (
            ("regional_not_diagnosis", "State that the regional signal cannot diagnose a field cause.", (r"\b(?:not a field diagnosis|cannot diagnose|does not diagnose)\b",)),
            ("regional_field_comparison", "Compare representative affected and normal field observations.", (r"\baffected and normal\b",)),
            ("regional_root_water", "Inspect roots and current root-zone water before inferring stress.", (r"\broots?\b",)),
        ) + (("regional_nitrogen_budget", "Reconcile applied nitrogen and nutrient credits with remaining response and local calibration.", (r"\b(?:credits?|soil nitrate|applied nitrogen)\b",)),) * nitrogen)
    if has(r"\b(?:scout\w*|walk|check)\b") and (
        has(r"\baffected\b.*\b(?:normal|healthy)\b|\b(?:normal|healthy)\b.*\baffected\b")
        or has(r"\b(?:yellow\w*|pale|chlorosis)\b") and has(r"\b(?:rain|wet|low spots?|waterlog\w*)\b")
    ):
        yield ObservationGuidance("paired_scouting", (
            "On the next safe field walk, compare several affected patch margins with nearby normal areas of the same crop and stage, and check representative areas beyond the first patch. "
            "At each, photograph and locate symptoms, count plants and record incidence or severity and which leaves or tissues are affected. "
            "Dig intact plants from both areas to compare roots and crowns for restriction, discoloration or decay; compare soil moisture by depth, ponding, drainage and compaction. "
            "Review rainfall, timing of symptom onset, fertilizer placement, application and crop history. Keep affected and normal plant or soil samples separately labelled and follow the diagnostic lab's sampling instructions. "
            "Revisit marked locations to track recovery or progression. Waterlogging, root disease, nutrient limitation and application injury remain alternatives; crop colour or the rain event alone cannot identify the cause or justify a rescue rate."
        ), (
            ("scouting_comparison", "Compare patch margins with representative nearby normal areas.", (r"\b(?:affected.*normal|normal.*affected)\b",)),
            ("scouting_roots", "Dig intact plants and compare roots/crowns, not just leaves.", (r"\b(?:dig|inspect|examine)\b[^.]{0,100}\broots?\b",)),
            ("scouting_samples", "Keep affected and normal samples separately labelled.", (r"\b(?:separately|separate)\b",)),
            ("scouting_follow_up", "Revisit marked locations to track recovery or symptom progression.", (r"\b(?:revisit|recheck|marked locations|track.{0,35}progression)\b",)),
            ("scouting_water", "Compare soil moisture and drainage in the contrasting areas.", (r"\b(?:soil moisture|root[- ]zone moisture|ponding|drainage)\b",)),
        ))
    return None
