"""Bounded observation methods shared by drafting, holds and verification.

These are project-authored methods, not measurements, diagnoses, current labels
or locally calibrated prescriptions. Source rationale lives in the operations
guide. Never load assessment questions, gold or reviewer labels here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from agronomy_agent.answerability import preferred_response_language


@dataclass(frozen=True)
class ObservationGuidance:
    key: str
    answer: str
    # Every facet is required; alternatives within a facet accept equivalent prose.
    facets: tuple[tuple[str, str, tuple[str, ...]], ...]

    def missing(self, answer: str) -> tuple[str, ...]:
        return tuple(name for name, _, patterns in self.facets
                     if not any(re.search(p, answer, re.I) for p in patterns))

    def unsupported_inference(self, answer: str) -> bool:
        """Reject bounded contradictions even when a correct check is appended."""
        for sentence in re.split(r"[.!?;]\s*|\n+", answer):
            if self.key == "empty_terrain_coverage":
                if re.search(
                    r"\b(?:absence|empty|no (?:mapped )?features?|lack of data)\b[^.!?]{0,160}"
                    r"\b(?:suggest\w*|indicat\w*|means?|proves?|confirms?)\b[^.!?]{0,100}"
                    r"\b(?:low(?:er)?[- ]risk|(?:low|lower|reduced|minimal|no) (?:waterlogging )?risk|lack of coverage|missing coverage|no coverage)\b",
                    sentence, re.I,
                ) and not re.search(r"\b(?:does not|do not|cannot|can't|doesn't|not enough to)\s+(?:by itself\s+)?(?:suggest|indicat|mean|prove|confirm)\w*", sentence, re.I):
                    return True
            if self.key == "point_area":
                if re.search(r"\b(?:area|size)\b[^.;]{0,35}\b(?:covered by|of)\b[^.;]{0,25}\b(?:pin|point)\b", sentence, re.I):
                    return True
                if re.search(r"\b(?:simplest|only|sufficient)\b[^.;]{0,160}\b(?:known|single|one) (?:distance|dimension|scale|reference point)\b", sentence, re.I) and not re.search(r"\b(?:not|insufficient|both|length and width|closed boundary|closed polygon)\b", sentence, re.I):
                    return True
                if re.search(r"\b(?:estimate slope length|use benchmark sites|directed benchmark sampling)\b", sentence, re.I) and not re.search(r"\b(?:not|cannot|insufficient|doesn't)\b", sentence, re.I):
                    return True
        return False


def observation_guidance(question: str) -> ObservationGuidance | None:
    q = question.lower()
    has = lambda p: bool(re.search(p, q))
    # English method text must never replace a French answer.
    if preferred_response_language(question) == "fr" or has(r"\b(?:en fran[cç]ais|in french)\b"):
        return None
    if has(r"\b(?:ndvi|vegetation index)\b") and has(r"\b(?:compar\w*|dates?|lower|declin\w*|chang\w*)\b"):
        return ObservationGuidance("imagery_comparison", (
            "A lower displayed NDVI alone does not establish a real crop-vigor decline, a cause, or a yield loss. "
            "First check each scene's cloud, shadow, snow and other QA masks, valid pixel counts and valid field coverage. "
            "Compare the same boundary and spatial support, sensor/product, processing and resolution; use comparable valid pixels rather than different clear fragments of the field. "
            "Then compare acquisition dates, crop stage, canopy cover, harvest and management history. Only after those checks should you scout the corresponding affected and normal areas, including roots and soil moisture, to test possible causes. "
            "Until QA and comparable support are available, the apparent difference remains unverified and cannot justify a treatment."
        ), (
            ("imagery_qa", "Check cloud/shadow masks before interpreting a change.", (r"\b(?:cloud|shadow)\b[^.]{0,90}\b(?:mask|QA)",)),
            ("imagery_support", "Check valid pixel count/coverage and comparable spatial support.", (r"\bvalid (?:pixel|field|coverage)",)),
            ("imagery_comparability", "Compare processing and crop stage before causal interpretation.", (r"\b(?:processing|sensor|product)\b",)),
            ("imagery_stage", "Check crop stage or phenology on both dates.", (r"\b(?:crop|growth) stage\b", r"\bphenolog")),
        ))
    if has(r"\b(?:gps|dropped|single|one)\b[^.]{0,35}\b(?:pin|point)\b") and has(r"\barea\b"):
        return ObservationGuidance("point_area", (
            "One GPS pin locates a point; it does not describe the planted area. Trace or survey the planted boundary to make a closed polygon. "
            "For a genuinely rectangular planted block, measure both length and width and multiply them in compatible units. "
            "A known distance or scale alone still leaves the other dimension and field shape unknown. Exclude unplanted areas; an estimated field boundary need not equal the area actually planted."
        ), (("area_shape", "Require a closed boundary or both dimensions of a known shape.", (r"\b(?:closed (?:polygon|boundary)|length and width|both dimensions)\b",)),))
    if has(r"\b(?:mapaq|lidar|terrain)\b") and has(
        r"\b(?:zero|no)\s+(?:mapped\s+)?(?:depressions?|flow[- ]paths?|intersections?|features?)\b|\bempty\b[^.]{0,50}\b(?:clip|layer|result)\b"
    ):
        return ObservationGuidance("empty_terrain_coverage", (
            "No mapped intersection does not establish absence of waterlogging risk. Verify source parcel coverage and missing or excluded areas, the acquisition period and age, layer completeness, the saved field boundary and the clipping CRS. "
            "An empty clip means no features from that layer intersected that boundary; it cannot distinguish true absence from missing coverage. "
            "Ground-truth low and normal areas after rain: record ponding duration, soil moisture by depth, roots, infiltration, drainage and outlet condition, and compaction. "
            "Mapped terrain cannot establish current saturation or a drainage design without those field observations."
        ), (
            ("terrain_coverage", "Check source parcel coverage before interpreting absence.", (r"\b(?:source|parcel|layer) coverage\b",)),
            ("terrain_age", "Check acquisition period/age separately from publication.", (r"\bacquisition\b",)),
        ))
    if has(r"\b(?:guide|table|manual)\b") and has(r"\bvegetable\w*\b") and has(r"\b(?:haskap|honeyberry|perennial berr\w*|berry shrub)\b"):
        return ObservationGuidance("crop_guide_applicability", (
            "A vegetable spacing or fertilizer table is not a planting prescription for a perennial berry shrub. "
        ) + ("Haskap (honeyberry) is a perennial fruit crop. " if has(r"\b(?:haskap|honeyberry)\b") else "") + (
            "Check the guide's named crop, production system and region before transferring any table. Use crop-specific perennial-berry guidance to plan mature plant size, row and in-row spacing, machinery and harvest access, compatible pollinizer cultivars and bloom overlap. "
            "For fertility, distinguish establishment from bearing years and use current soil tests and locally appropriate crop guidance; do not copy a vegetable rate. "
            "General sampling or soil-preparation principles may transfer with their limits, but they do not establish suitable spacing or a locally calibrated fertilizer recommendation."
        ), (
            ("guide_crop_fit", "Explain vegetable versus perennial fruit production scope.", (r"\bperennial\b",)),
            ("guide_layout", "Check mature plant size and harvest access for layout.", (r"\b(?:mature plant|harvest access|machinery)\b",)),
            ("guide_rate_transfer", "Do not transfer the table's crop-specific fertilizer rates.", (r"\b(?:do not copy|not.*prescription|locally calibrated)\b",)),
        ))
    if has(r"\b(?:crop[- ]health|national.*stress|regional.*stress)\b") and has(r"\b(?:map|layer|index|indices|patch)\b"):
        nitrogen = has(r"\b(?:nitrogen|fertiliz\w*)\b")
        return ObservationGuidance("regional_crop_signal", (
            "A regional crop-health or stress layer is a screening signal, not a field diagnosis of drought, nutrient deficiency or a named disease. "
            "Verify the exact metric, date, spatial resolution, source and uncertainty; determine whether it is a modelled weather/water-balance product or a satellite observation before interpreting it. "
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
        return ObservationGuidance("paired_scouting", (
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
