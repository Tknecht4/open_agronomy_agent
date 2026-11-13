"""Bounded observation methods shared by drafting, holds and verification.

These are project-authored methods, not measurements, diagnoses, current labels
or locally calibrated prescriptions. Source rationale lives in the operations
guide. Never load assessment questions, gold or reviewer labels here.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import re

from agronomy_agent.answerability import preferred_response_language, is_rate_basis_explanation, is_dose_response_explanation, is_sampling_basis_explanation, product_action_request_text
from agronomy_agent.plant_health_scope import root_inspection_requested, current_root_inspection_is_soybean


POTATO_MONITORING_ANSWER = (
    "Scout representative areas of the potato crop regularly, including low or shaded places where the canopy stays damp longer. Inspect leaves, their undersides and stems for water-soaked spots or new, dark, spreading lesions. White growth may appear beneath lesions under humid conditions, especially early in the morning; its absence does not exclude late blight. "
    "If suspect symptoms appear, photograph and locate them, compare suspect and nearby healthy plants, and promptly contact a local potato specialist or diagnostic lab for sampling instructions and confirmation. Follow current local disease alerts and crop-specific IPM guidance. "
    "Use crop stage, local disease risk and forecasts, and the exact crop/target/product label to plan any preventive fungicide program; visible collapse is not a prerequisite for prevention planning."
)


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
        missing = [name for name, _, patterns in self.facets
                   if not any(re.search(p, answer, re.I) for p in patterns)]
        if any(name == "illustrative_rate_example" for name, _, _ in self.facets):
            # A disclaimer alone is not an example. Reuse the same arithmetic
            # and span contract that guards quantities; never whitelist values.
            from agronomy_agent.quantity_claims import _checked_rate_illustration_spans
            request = "Explain product rate versus nutrient rate using a hypothetical example."
            if not _checked_rate_illustration_spans(answer, request):
                missing.append("illustrative_rate_example")
        return tuple(dict.fromkeys(missing))

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
    if root_inspection_requested(question):
        answer = (
            "Carefully dig or lift whole plants with their roots intact rather than pulling them out. "
            "Compare affected plants with nearby normal plants and the normal underground structures of the affected crop. "
            "Examine where the swelling joins the root, its shape, and any discoloration, soft or decaying tissue, or injury; swelling alone does not identify a cause. "
            "Photograph the structures and record crop identity, growth stage, location and the pattern across the field. "
            "Keep material from different areas separate and contain attached soil; ask a local diagnostic lab how to collect and package representative plants and soil if the cause remains uncertain."
        )
        facets = [
            ("root_intact_sampling", "Explain how to examine intact roots without losing useful structures.",
             (r"\b(?:dig|lift)\b", r"\bintact roots?\b")),
            ("root_comparison", "Compare affected and normal plants rather than one swollen root alone.",
             (r"\b(?:normal|healthy|unaffected)\b",)),
            ("root_structure", "Describe concrete root structures, damage or discoloration to inspect.",
             (r"\b(?:nodules?|galls?|discolou?r\w*|rot|injury|attachment|shape)\b",)),
            ("root_records", "Record crop stage and field location or distribution of the symptoms.",
             (r"\b(?:record|document|photograph|map)\w*\b",)),
            ("root_confirmation", "Keep the cause uncertain and use diagnostic guidance if inspection is inconclusive.",
             (r"\b(?:diagnostic|lab(?:oratory)?|confirmation|uncertain)\b",)),
        ]
        if current_root_inspection_is_soybean(question):
            answer += (" On soybean, distinguish normal nodules attached to roots from irregular root galls; "
                       "do not assume every swelling is a disease.")
            facets.append(("soybean_normal_nodules", "Distinguish normal soybean nodules from abnormal root swellings.",
                           (r"\b(?:nodules?|rhizobi\w*|nitrogen[- ]fix\w*)\b",)))
        yield ObservationGuidance("current_root_inspection", answer, tuple(facets))
    if is_sampling_basis_explanation(question):
        yield ObservationGuidance("sampling_basis_concept", (
            "Counts per plant, leaf, stem or tiller describe insects on a defined plant unit; "
            "counts per sweep describe insects caught by a defined sweep-net method. "
            "These are different sampling bases, not interchangeable measurements with a universal conversion. "
            "Use the counting method and units for which the relevant crop-and-pest threshold was validated; "
            "a change of method needs a validated relationship, not an assumed conversion. "
            "This explains the measurement basis and does not establish a field population or treatment decision."
        ), (
            ("sampling_basis_distinction", "Explain the different sampling units or methods.",
             (r"\bper (?:plant|leaf|stem|tiller|sweep)\b", r"\bdifferent (?:sampling )?(?:units|bases|methods)\b")),
            ("sampling_basis_calibration", "Do not assume conversion between methods; retain the threshold's validated basis.",
             (r"\b(?:not interchangeable|validated|calibrat\w*|no universal conversion)\b",
              r"\b(?:cannot|can't)\b[^.]{0,45}\bconvert\w*\b")),
        ))
        return
    if is_dose_response_explanation(question):
        yield ObservationGuidance("dose_response_concept", (
            "A dose-response curve relates dose to a measured biological response under stated test conditions. "
            "Its shape depends on the organism, response endpoint, exposure method and conditions. "
            "It does not by itself establish a suitable field dose or override the applicable product label."
        ), (("dose_response_relationship", "Explain the relationship between dose and measured biological response.",
             (r"\bdose\b[^.]{0,140}\b(?:response|effect)\b", r"\b(?:response|effect)\b[^.]{0,140}\bdose\b")),))
    if is_rate_basis_explanation(question):
        q = product_action_request_text(question).lower()
        parts: list[str] = []
        facets: list[tuple[str, str, tuple[str, ...]]] = []
        if has(r"\blabel\b"):
            parts.append("A pesticide label rate states the product amount or concentration for a specified labelled use and formulation. Read the label's stated product or active-ingredient basis and units; do not assume they are interchangeable. An application rate is distinct from a maximum residue limit, which concerns residue remaining in food.")
            facets.append(("label_rate_basis", "Explain the amount/concentration basis specified by the product label.", (r"\b(?:amount|quantity|concentration)\b[^.]{0,100}\b(?:product|label|pesticide|formulation)\b", r"\b(?:product|label|pesticide|formulation)\b[^.]{0,100}\b(?:amount|quantity|concentration)\b")))
        elif has(r"\bproduct\b"):
            parts.append("A product rate describes the amount of the commercial formulation on its stated application basis, such as product mass or volume per area.")
            facets.append(("product_rate_basis", "Explain the commercial-product amount basis.", (r"\bproduct\b[^.]{0,100}\b(?:amount|mass|volume|quantity)\b", r"\b(?:amount|mass|volume|quantity)\b[^.]{0,100}\bproduct\b")))
        if has(r"\bnutrient\b"):
            parts.append("For a field application, a fertilizer nutrient rate commonly expresses the mass of a named nutrient per area. Other application systems may use an explicitly stated concentration or volume basis. Use the declared nutrient basis and product analysis to convert nutrient mass into product amount; it is not a nutrient concentration measured in the crop or soil.")
            facets.append(("nutrient_rate_basis", "Explain nutrient mass per area, distinct from product amount or measured crop concentration.", (r"\b(?:mass|amount|kg|kilograms?|lb|pounds?)\b[^.]{0,100}\b(?:nutrient|nitrogen|phosphorus|N|P|K)\b[^.]{0,60}\b(?:area|hectare|ha|acre|ac)\b", r"\bnutrient\b[^.]{0,60}\bmass per (?:unit )?area\b")))
        if has(r"\bexample\b"):
            parts.append("For a hypothetical illustration, suppose a fictional fertilizer contains 20% N. A product rate of 60 kg/ha supplies a nutrient rate of 12 kg N/ha (60 × 0.20 = 12). These invented quantities illustrate the mass-fraction relationship; they do not select a field target or establish a real product's analysis or permission.")
            facets.append(("illustrative_rate_example", "Include the requested clearly hypothetical illustration without a field recommendation.",
                (r"\b(?:hypothetical|illustrative|made[- ]up|fictional|suppose)\b",)))
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
    if has(r"\bpotato\w*\b") and has(r"\blate blight\b") and has(r"\bhealthy potato\w*\b|\bpotato\w*(?: crop)? (?:is|are|looks?|appears?) healthy\b") and has(r"\b(?:monitor|scout|watch)\w*\b"):
        yield ObservationGuidance("healthy_potato_monitoring", POTATO_MONITORING_ANSWER, (
            ("potato_monitor_surfaces", "Inspect potato foliage and stems for early symptoms.", (r"\b(?:leaves|foliage|stems)\b",)),
            ("potato_monitor_signs", "Describe recognizable signs to look for, conditionally rather than diagnosing the healthy crop.",
             (r"\b(?:lesions?|water[- ]soaked|necrosis)\b", r"\bwhite\b[^.]{0,50}\b(?:growth|sporulation)\b")),
            ("potato_monitor_coverage", "Scout representative locations and consider places that remain damp or weather-related risk.",
             (r"\brepresentative\b", r"\bacross (?:the )?field\b", r"\b(?:damp|wet|humid|weather|shaded|low[- ]lying)\b")),
            ("potato_monitor_followup", "Record suspicious findings and seek diagnostic guidance if they appear.",
             (r"\b(?:diagnostic|lab(?:oratory)?|confirmation|specialist)\b",)),
            ("potato_monitor_alerts", "Check current local disease alerts as part of healthy-crop monitoring.", (r"\b(?:local|regional)\b[^.]{0,60}\b(?:disease )?alerts?\b", r"\balerts?\b[^.]{0,60}\b(?:local|regional)\b")),
        ))
    if sample_event_roles_stated(question) and has(
        r"\b(?:sampling dates?|sample date|collection date|which date|preserv\w*)\b|"
        r"\b(?:store|record|keep|retain|distinguish)\b[^.!?;]{0,50}\bdates?\b"
    ):
        yield ObservationGuidance("sample_record_dates", (
            "Use the actual sample collection date as the sampling-event date when comparing seasons. "
            "Preserve the laboratory report issuance date in a separate field linked to the sample identifier "
            "and original report. Keep an analysis or processing date separately if supplied; do not infer it "
            "from report issuance. Compare sampling depth, timing and analytical method as well as the dates."
        ), (
            ("date_collection", "Use the collection event for sampling-date comparisons.", (r"\bcollection date\b", r"\bdate of collection\b", r"\bsampling[- ]event date\b")),
            ("date_report", "Preserve the report issuance event under its own role.", (r"\breport (?:issuance|issue) date\b", r"\bdate (?:the )?(?:lab(?:oratory)? )?report was issued\b")),
            ("date_separation", "Keep distinct events and their provenance linked without overwriting.", (r"\bseparate(?:ly)?\b", r"\bdistinct(?:ly)?\b", r"\b(?:retain|keep|preserve) both\b")),
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
