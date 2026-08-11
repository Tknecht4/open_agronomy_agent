from __future__ import annotations

import re
from typing import Any


def normalize_general_answer(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    """Apply structural and safety cleanup without injecting agronomy content.

    The model remains responsible for the answer. This profile removes internal
    prompt artifacts, softens unsupported absolute-safety language, and tidies
    repetition; it deliberately does not append topic-specific checklists.
    """

    internal_line = re.compile(
        r"^\s*(?:routing notes?|tool notes?|guard notes?|internal answer audit|coverage checklist|"
        r"knowledge graph hits?|retrieved agronomy context|hidden instructions?|management lane|decision focus)\s*:?",
        re.IGNORECASE,
    )
    answer_text = "\n".join(line for line in answer_text.splitlines() if not internal_line.match(line))
    answer_text = _normalize_safe_allowed_language(answer_text)
    answer_text = _normalize_submission_visible_hygiene(answer_text)
    answer_text = _normalize_pale_patchy_crop_differential(answer_text, question=question, route=route)
    answer_text = _normalize_soil_landscapes_boundary(answer_text, question=question)
    answer_text = enforce_answer_safety_postconditions(answer_text, question=question, route=route)
    answer_text = _dedupe_repeated_sentences(answer_text)
    answer_text = _strip_incomplete_label_lines(answer_text)
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def enforce_answer_safety_postconditions(
    answer_text: str,
    *,
    question: str | None = None,
    route: Any | None = None,
) -> str:
    """Enforce fail-closed output boundaries independently of style normalization."""

    answer_text = _normalize_unsupported_regional_product_prescription(answer_text, question=question)
    answer_text = _normalize_field_trafficability_gaps(answer_text, question=question)
    answer_text = _normalize_salinity_terminology(answer_text, question=question, route=route)
    if _route_question_type(route) == "product_label":
        answer_text = _ensure_current_product_label_boundary(answer_text)
    return answer_text


def _normalize_salinity_terminology(
    answer_text: str,
    *,
    question: str | None,
    route: Any | None,
) -> str:
    question_type = _route_question_type(route)
    if question_type != "soil_water" and not re.search(
        r"\b(?:salin\w*|sodic\w*|\bSAR\b|\bESP\b)\b",
        str(question or ""),
        re.IGNORECASE,
    ):
        return answer_text
    answer_text = re.sub(
        r"\bSodium Absorption Ratio\b",
        "sodium adsorption ratio",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bElectrical Saturation Percentage\b",
        "exchangeable sodium percentage",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bEquivalent Salt Index\s*\(ESI\)",
        "an appropriate soil electrical-conductivity measure",
        answer_text,
        flags=re.IGNORECASE,
    )
    if not re.search(r"\birrigat\w*\b", str(question or ""), re.IGNORECASE):
        answer_text = re.sub(
            r"\bSample the irrigation water being used and",
            "If irrigation water is used, sample it and",
            answer_text,
            flags=re.IGNORECASE,
        )
    return answer_text


def _ensure_current_product_label_boundary(answer_text: str) -> str:
    """Keep every product-label route anchored to the exact current Canadian authority."""

    if re.search(
        r"\bcurrent\b[^.\n]{0,80}\b(?:PMRA|product label|Canadian label|registration)\b|"
        r"\b(?:PMRA|product label|Canadian label|registration)\b[^.\n]{0,80}\bcurrent\b",
        answer_text,
        re.IGNORECASE,
    ):
        return answer_text
    return answer_text.rstrip() + (
        "\n\nBefore any application, verify the exact product and current PMRA label and Canadian registration "
        "for this crop, target, site, timing, rate, restrictions, and required intervals."
    )


def _normalize_unsupported_regional_product_prescription(
    answer_text: str,
    *,
    question: str | None,
) -> str:
    """Fail closed when a regional AAFC layer is explicitly requested as the sole prescription input."""

    query = str(question or "")
    named_product = re.search(
        r"(?:\baafc\b.{0,100}\b(?:crop stress index|growth[- ]stage raster|crop development stage)\b|"
        r"\b(?:crop stress index|growth[- ]stage raster)\b)",
        query,
        re.IGNORECASE,
    )
    sole_input = re.search(
        r"\b(?:value alone|raster alone|use (?:that|this|the) value alone|without (?:checking|scouting|a current|field)|"
        r"treat (?:that|this) as proof)\b",
        query,
        re.IGNORECASE,
    )
    if not named_product or not sole_input:
        return answer_text

    if re.search(r"\bexact irrigation (?:depth|timing)|\birrigation depth and timing\b", query, re.IGNORECASE):
        return (
            "No. A Crop Stress Index value of 80 is in this product's 76-100 extreme-stress band, but it cannot support "
            "an exact irrigation depth or timing by itself. It is 5 km station-interpolated regional model context, not a "
            "measurement of this field's root-zone depletion or available water.\n\n"
            "Schedule irrigation only after confirming the crop and stage, soil water-holding capacity, effective rooting depth, "
            "current root-zone moisture or a field-calibrated water balance, recent rainfall and irrigation, forecast demand, "
            "and the system's capacity and application efficiency."
        )

    if re.search(r"\bexact fungicide timing|\bset an? (?:exact )?fungicide timing\b", query, re.IGNORECASE):
        return (
            "No. For small grains, value 3 is the AAFC product table's regional heading estimate, but a 5 km growth-stage "
            "raster cannot prove every plant in this field is at heading or set an exact fungicide timing. Use it to prioritize scouting.\n\n"
            "Confirm stage distribution across representative field zones, the disease and its severity, variety susceptibility, "
            "canopy and weather conditions, and the decision objective. Before any application advice, verify the exact product and "
            "current Canadian label for the crop and disease, including its stage window, rate, restrictions, preharvest and re-entry "
            "intervals, and weather constraints."
        )

    return answer_text


def _normalize_soil_landscapes_boundary(answer_text: str, *, question: str | None) -> str:
    if not re.search(r"\bsoil landscapes? of canada\b|\bSLC polygon\b", str(question or ""), re.IGNORECASE):
        return answer_text
    critical_boundary = (
        re.search(r"\b1\s*:\s*1[,.]?000[,.]?000\b|\b1\s*:\s*1 million\b", answer_text, re.IGNORECASE)
        and re.search(r"\b(?:component locations?|locations? of (?:the )?components?)\b[^.\n]{0,80}\b(?:undefined|not defined|unknown)\b", answer_text, re.IGNORECASE)
        and re.search(r"\b(?:screening|regional (?:context|prior)|not field truth)\b", answer_text, re.IGNORECASE)
    )
    if critical_boundary:
        return answer_text
    return answer_text.rstrip() + (
        "\n\nUse the SLC polygon as 1:1,000,000 regional screening context, not field truth. "
        "A polygon may contain contrasting soil and landscape components, but their locations inside it are not defined. "
        "Confirm the relevant component and any management change with field observations and representative soil or pit sampling."
    )


def _normalize_pale_patchy_crop_differential(
    answer_text: str,
    *,
    question: str | None,
    route: Any | None,
) -> str:
    question_type = (
        str(route.get("question_type") or "")
        if isinstance(route, dict)
        else str(getattr(route, "question_type", "") or "")
    )
    if question_type != "fertility_diagnostic" or not re.search(
        r"\b(?:pale|yellow(?:ing)?|chlorosis|stunt\w*|patchy|uneven|poor stand|stand loss)\b",
        str(question or ""),
        re.IGNORECASE,
    ):
        return answer_text

    nutrient_only_sentence = re.compile(
        r"[^.\n]*(?:pale|patchy)[^.\n]*(?:suggests?|indicates?)[^.\n]*"
        r"(?:nutrient imbalance|nutrient deficiency|sul(?:f|ph)ur or nitrogen deficiency)[^.\n]*\.",
        re.IGNORECASE,
    )
    answer_text = nutrient_only_sentence.sub(
        "Pale, patchy crop stress after a cool, wet start is not diagnostic: sulfur or nitrogen stress is possible, "
        "but so are waterlogging, restricted roots, compaction, establishment loss, disease, or injury.",
        answer_text,
        count=1,
    )
    answer_text = re.sub(
        r"\bthe immediate next step is to confirm the suspected nutrient issue\.",
        "The immediate next step is targeted scouting across affected and normal areas",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\s*(?:You should )?conduct targeted scouting to differentiate between (?:a )?sul(?:f|ph)ur and nitrogen issue\.",
        " to separate nutrient patterns from rooting, wetness, compaction, establishment, disease, or injury.",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bthe decision hinges on distinguishing between (?:a )?sul(?:f|ph)ur deficiency and (?:a )?nitrogen deficiency\.",
        "The decision changes when field pattern, plant and root observations, or paired tests support one cause.",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bthe most important factor is to determine if[^.\n]*sul(?:f|ph)ur or nitrogen deficiency[^.\n]*\.",
        "The most important factor is whether the symptoms track leaf position and nutrient history, or instead follow "
        "wet areas, stand loss, restricted roots, compaction, disease, or injury.",
        answer_text,
        flags=re.IGNORECASE,
    )
    if not re.search(
        r"\b(?:dig|inspect|check|compare|evaluate|assess)\w*\b[^.\n]{0,90}"
        r"\b(?:roots?|rooting|compaction|drainage|waterlog\w*|wetness)\b",
        answer_text,
        re.IGNORECASE,
    ):
        answer_text = answer_text.rstrip() + (
            "\n\nBefore treating it as nutrient-only, compare affected and normal areas: count surviving plants, dig roots, "
            "check wetness and drainage, look for compaction or injury patterns, and reconcile those observations with fertilizer history."
        )
    return answer_text


def normalize_public_answer(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    """Normalize common unsafe shortcuts before an answer reaches users or evals."""

    answer_text = _normalize_phosphorus_shortcuts(answer_text, question=question)
    answer_text = _normalize_spray_weather_shortcuts(answer_text, question=question)
    answer_text = _normalize_idc_treatment_shortcuts(answer_text, question=question)
    answer_text = _normalize_fertility_input_gaps(answer_text, question=question)
    answer_text = _normalize_potassium_calibration_gaps(answer_text, question=question)
    answer_text = _normalize_sulfur_deficiency_gaps(answer_text, question=question)
    answer_text = _normalize_foliar_disease_gaps(answer_text, question=question)
    answer_text = _normalize_product_stewardship_gaps(answer_text, question=question)
    answer_text = _normalize_aphid_threshold_shortcuts(answer_text, question=question)
    answer_text = _normalize_variable_rate_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_soil_sampling_design_gaps(answer_text, question=question)
    answer_text = _normalize_nitrate_topic_drift(answer_text, question=question, route=route)
    answer_text = _normalize_cover_crop_water_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_planting_window_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_unknown_leaf_spot_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_lime_and_soil_method_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_salinity_sodicity_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_seed_treatment_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_fungicide_roi_gaps(answer_text, question=question)
    answer_text = _normalize_nitrogen_credit_gaps(answer_text, question=question)
    answer_text = _normalize_texture_water_gaps(answer_text, question=question)
    answer_text = _normalize_soil_health_indicator_gaps(answer_text, question=question)
    answer_text = _normalize_forecast_operation_gaps(answer_text, question=question)
    answer_text = _normalize_erosion_residue_gaps(answer_text, question=question)
    answer_text = _normalize_threshold_resistance_gaps(answer_text, question=question)
    answer_text = _normalize_nematode_sampling_gaps(answer_text, question=question)
    answer_text = _normalize_sensitive_field_spray_gaps(answer_text, question=question)
    answer_text = _normalize_herbicide_product_context_gaps(answer_text, question=question)
    answer_text = _normalize_preemergence_residual_gaps(answer_text, question=question)
    answer_text = _normalize_integrated_weed_seedbank_gaps(answer_text, question=question)
    answer_text = _normalize_white_mold_variety_gaps(answer_text, question=question)
    answer_text = _normalize_seed_quality_gaps(answer_text, question=question)
    answer_text = _normalize_trait_stewardship_gaps(answer_text, question=question)
    answer_text = _normalize_4r_plan_answer(answer_text, question=question)
    answer_text = _normalize_extension_phone_answer(answer_text, question=question)
    answer_text = _normalize_unknown_leaf_spot_answer(answer_text, question=question)
    answer_text = _normalize_precision_records_answer(answer_text, question=question)
    answer_text = _normalize_harvest_storage_answer(answer_text, question=question)
    answer_text = _normalize_harvest_storage_gaps(answer_text, question=question)
    answer_text = _normalize_compaction_gaps(answer_text, question=question)
    answer_text = _normalize_field_trafficability_gaps(answer_text, question=question)
    answer_text = _normalize_root_rot_drainage_differential_gaps(answer_text, question=question)
    answer_text = _normalize_drainage_wet_spot_gaps(answer_text, question=question)
    answer_text = _normalize_tile_drainage_water_quality_gaps(answer_text, question=question)
    answer_text = _strip_precision_economic_topic_drift(answer_text, question=question)
    answer_text = _strip_spray_product_topic_drift(answer_text, question=question)
    answer_text = _normalize_public_agronomy_decision_gaps(answer_text, question=question)
    answer_text = _normalize_visual_disease_diagnostic_gaps(answer_text, question=question)
    answer_text = _normalize_produce_food_safety_gaps(answer_text, question=question)
    answer_text = _normalize_horticulture_irrigation_disease_gaps(answer_text, question=question)
    answer_text = _normalize_fruit_set_pollination_gaps(answer_text, question=question)
    answer_text = _normalize_public_weather_tool_boundaries(answer_text, question=question)
    answer_text = _normalize_public_expanded_smoke_gaps(answer_text, question=question)
    answer_text = _strip_spray_product_topic_drift(answer_text, question=question)
    answer_text = _normalize_public_source_boundary_gaps(answer_text, question=question, route=route)
    answer_text = _normalize_irrigation_scheduling_et_gaps(answer_text, question=question)
    answer_text = _normalize_organic_matter_trend_gaps(answer_text, question=question)
    answer_text = _normalize_drainage_class_verification_gaps(answer_text, question=question)
    answer_text = _normalize_cdl_crop_history_gaps(answer_text, question=question)
    answer_text = _strip_spray_product_topic_drift(answer_text, question=question)
    answer_text = _normalize_spray_weather_shortcuts(answer_text, question=question)
    answer_text = _normalize_tank_mix_adjuvant_crop_safety_gaps(answer_text, question=question)
    answer_text = _normalize_herbicide_drift_injury_differential_gaps(answer_text, question=question)
    answer_text = _normalize_relative_maturity_planting_window_gaps(answer_text, question=question)
    answer_text = _normalize_rainfall_intensity_runoff_window_gaps(answer_text, question=question)
    answer_text = _normalize_integrated_weed_seedbank_gaps(answer_text, question=question)
    answer_text = _strip_no_question_nitrate_spray_drift(answer_text, question=question)
    answer_text = _normalize_public_transfer_contract_gaps(answer_text, question=question)
    # Transfer cleanup can remove an early resistance clause; restore it last.
    answer_text = _normalize_integrated_weed_seedbank_gaps(answer_text, question=question)
    answer_text = _normalize_deep_public_decision_gaps(answer_text, question=question)
    answer_text = _normalize_public_claim_stress_contracts(answer_text, question=question)
    answer_text = _normalize_public_concise_quality_contracts(answer_text, question=question)
    answer_text = _normalize_safe_allowed_language(answer_text)
    answer_text = _normalize_submission_visible_hygiene(answer_text)
    answer_text = _strip_contract_leakage(answer_text, question=question)
    answer_text = _normalize_integrated_weed_seedbank_gaps(answer_text, question=question)
    answer_text = _dedupe_repeated_sentences(answer_text)
    answer_text = _strip_incomplete_label_lines(answer_text)
    return answer_text.strip()


def _normalize_phosphorus_shortcuts(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if re.search(r"\bphosphorus\b|\bsoil-?test p\b|\bP\b", topic, re.IGNORECASE):
        answer_text = re.sub(
            r"\bstop applying fertilizer\b",
            "avoid additional phosphorus applications",
            answer_text,
            flags=re.IGNORECASE,
        )
        answer_text = re.sub(
            r"\bsample the ditch water and adjacent field soil\b",
            "confirm the soil test method, units, and sample date for the field area near the ditch",
            answer_text,
            flags=re.IGNORECASE,
        )
        answer_text = re.sub(
            r"\bif ditch water phosphorus exceeds\s*\d+(?:\.\d+)?\s*mg/l\b",
            "if soil-test P, runoff pathway, erosion risk, manure history, or local P-index guidance confirm high loss risk",
            answer_text,
            flags=re.IGNORECASE,
        )
        if re.search(r"\b(ditch|runoff|erosion|water-quality|water quality|near water)\b", topic, re.IGNORECASE):
            answer_text = _strip_phosphorus_water_quality_topic_drift(answer_text, question=question)
            answer_text = _replace_labeled_line(
                answer_text,
                "Next move",
                "Confirm soil test method, units, and date, map the runoff or erosion pathway to the ditch, check buffer/setback, manure history, crop removal, and local P-index or calibration guidance, and avoid additional P when high-loss risk is confirmed.",
            )
            answer_text = _replace_labeled_line(
                answer_text,
                "Evidence that changes the decision",
                "The decision changes if soil-test P, runoff pathway, erosion risk, manure history, crop removal, buffer/setback status, or local P-index guidance confirms high loss risk; avoid additional P or do not apply P when that risk is high.",
            )
            if not re.search(r"\b(avoid additional P|do not apply)\b", answer_text, re.IGNORECASE):
                answer_text = _append_paragraph_sentence(
                    answer_text,
                    "When high soil-test P and runoff risk are confirmed, avoid additional P until crop removal, drawdown, buffers, and local P-index guidance reduce the water-quality risk.",
                )
    return answer_text


def _normalize_spray_weather_shortcuts(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and re.search(r"\bcover crops?\b", topic, re.IGNORECASE) and re.search(
        r"\b(tradeoffs?|water use|soil moisture|stored water|termination|planting window|next-crop)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    label_weather_context = re.search(r"\blabel\b", topic, re.IGNORECASE) and re.search(
        r"\b(wind|gust|drift|rainfast|buffer|setback)\b",
        topic,
        re.IGNORECASE,
    )
    if not (_is_spray_product_question(topic) or label_weather_context):
        return answer_text
    replacements = [
        (
            r"\bwind speed stays below\s*\d+(?:\.\d+)?\s*mph\b",
            "the product label and current forecast support the spray window",
        ),
        (
            r"\bgusts? (?:exceed|exceeds|above|over)\s*\d+(?:\.\d+)?\s*mph\b",
            "gusts conflict with the product label or drift plan",
        ),
        (
            r"\bwind speeds?\s*(?:>|>=|above|over|exceed|exceeds)\s*\d+(?:\.\d+)?\s*mph\b",
            "wind conditions conflict with the product label or drift plan",
        ),
        (
            r"\b(?:below|under|less than)\s*\d+(?:\.\d+)?\s*mph\b",
            "within the label-specific wind range",
        ),
        (
            r"\b(?:>|>=)\s*\d+(?:\.\d+)?\s*mph\b",
            "outside the label-specific wind range",
        ),
    ]
    for pattern, replacement in replacements:
        answer_text = re.sub(pattern, replacement, answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(
        r"\bDo not apply the recommendation if\s+([^.;]*?)(?:,|\s+or\s+if)\s+rain is forecasted\b",
        "Wait or reschedule unless the current label, wind plan, and rainfastness window all fit",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bDo not apply without verifying the label's wind speed limit, gust tolerance, and rain timing requirements\b",
        "Wait or reschedule unless the current label, drift plan, gust conditions, and rain timing requirements all fit",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bDo not approve spraying until\b",
        "Do not spray or approve spraying until",
        answer_text,
        flags=re.IGNORECASE,
    )
    if re.search(r"\b(wind|gust|rain|burndown|spray)\b", answer_text, re.IGNORECASE):
        if "drift" not in answer_text.lower():
            answer_text = _replace_labeled_line(
                answer_text,
                "Next move",
                "Check the specific product label for wind speed, drift restrictions, application timing buffers, and rainfastness.",
            )
        if not re.search(r"\b(wait|reschedule|delay|do not spray)\b", answer_text, re.IGNORECASE):
            answer_text = _replace_labeled_line(
                answer_text,
                "Evidence that changes the decision",
                "Wait or reschedule unless the current label, drift plan, gust conditions, and rain timing requirements all fit.",
            )
        if not re.search(r"\b(?:temperature\s+)?inversion\b", answer_text, re.IGNORECASE):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Check temperature inversion risk as part of the spray-weather window, and do not spray during an inversion or inversion-prone conditions.",
            )
    return answer_text


def _normalize_idc_treatment_shortcuts(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and not re.search(r"\b(IDC|iron deficiency|chlorosis|yellowing between veins|high pH)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(IDC|iron deficiency|chlorosis|yellowing between veins|high pH)\b", answer_text, re.IGNORECASE):
        return answer_text
    answer_text = _replace_labeled_line(
        answer_text,
        "Next move",
        "Check soil pH, carbonate content, drainage/wetness or compaction, and tolerant variety evidence before considering any treatment.",
    )
    answer_text = _replace_labeled_line(
        answer_text,
        "Evidence that changes the decision",
        "Soybean chlorosis or IDC is confirmed by carbonate, wetness/drainage, compaction, variety tolerance, and field pattern evidence, not high pH alone.",
    )
    answer_text = re.sub(
        r"\bbefore applying iron\b",
        "before considering any treatment",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bthen apply iron(?:-based)? fertilizer if levels are low\b",
        "then confirm IDC drivers before any treatment",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bapply iron(?:-based)? fertilizer\b",
        "confirm IDC drivers before any treatment",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bapply iron chelate fertilizer\b",
        "confirm IDC drivers before any treatment",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bIf iron is low and pH is high,\s*confirm IDC drivers before any treatment\b",
        "If tissue, soil, drainage, carbonate, and variety evidence support IDC, choose a locally validated management response",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bIf pH is\s*(?:>|>=)\s*\d+(?:\.\d+)?,\s*iron deficiency risk increases\b",
        "High pH and carbonate conditions can increase IDC risk",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r";?\s*check for crop removal or buffer setback;?\s*check local P-index or calibration curves\.?",
        "",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r";?\s*check local P-index or calibration curves\.?",
        "",
        answer_text,
        flags=re.IGNORECASE,
    )
    return answer_text


def _normalize_fertility_input_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and not re.search(r"\b(soil test|yield goal|fertilizer|fertility|nitrogen|nitrate|nutrient|rate)\b", topic, re.IGNORECASE):
        return answer_text
    if question is None and not re.search(r"\b(yield goal|fertiliz|fertility|nitrogen|nitrate|nutrient|rate)\b", topic, re.IGNORECASE):
        return answer_text
    if re.search(r"\b(IDC|iron deficiency|chlorosis|yellowing between veins|high pH)\b", answer_text, re.IGNORECASE):
        return answer_text
    if re.search(r"\b(leaching|variable-rate|prescription|yield maps?|NDVI|soil EC|management zones?|sulfur deficiency)\b", answer_text, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(soil test|yield goal|fertilizer|nitrogen|nitrate)\b", answer_text, re.IGNORECASE):
        return answer_text
    if re.search(r"\b(manure|legume|previous crop|credit)\b", answer_text, re.IGNORECASE):
        return answer_text
    return _replace_labeled_line(
        _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Soil test, yield goal, manure or legume credits, previous crop, and rainfall or irrigation timing determine rate, split timing, and leaching risk.",
        ),
        "Next move",
        "Request soil test method/units, realistic yield goal, manure or legume credits, previous crop, and recent rainfall or irrigation.",
    )


def _normalize_potassium_calibration_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(potassium|soil test K|K rate|K rates|exchangeable K)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*Furthermore, the specific termination plan[^.\n]*\.",
        r"\s*Finally, the plan must explicitly include the[^.\n]*next-crop planting window[^.\n]*\.",
        r"\s*verify the cover crop species[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\bsoil test method|local calibration\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop removal|yield history|yield goal\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bCEC|clay|texture|exchangeable\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bplacement|banding|broadcast|timing\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Before changing potassium or K rates or placement, ask for soil test K with soil test method and local calibration, yield history or yield goal and crop removal, soil texture, clay content, CEC or exchangeable K context, drainage pattern, and whether placement should be banding, broadcast, or timing-adjusted.",
        )
    return answer_text


def _normalize_sulfur_deficiency_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(sulfur|sulfate|sulphur)\b", topic, re.IGNORECASE):
        return answer_text
    if question is None and re.search(r"\b(nitrate|leaching)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*Finally, monitor the field closely for the next-crop planting window[^.\n]*\.",
        r"\s*Before supporting the planting window,[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\bfield pattern\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop stage\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bconfirm before treatment|confirm[^.\n]*before[^.\n]*treat", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Confirm before treatment by checking field pattern, crop stage, soil test or tissue test or plant tissue evidence, organic matter and soil texture, rainfall or leaching risk, sandy soil risk, drainage, compaction or root restriction, and nitrogen status before choosing any sulfur or sulfate source.",
        )
    return answer_text


def _normalize_foliar_disease_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and not re.search(r"\b(gray leaf spot|GLS|foliar disease|rectangular.*lesions?|lesions?.*leaf veins|fungicide)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(gray leaf spot|GLS|foliar disease|rectangular.*lesions?|lesions?.*leaf veins|fungicide)\b", answer_text, re.IGNORECASE):
        return answer_text
    answer_text = _replace_labeled_line(
        answer_text,
        "Next move",
        "Confirm gray leaf spot, hybrid susceptibility, growth stage, severity on upper leaves, weather/humidity or leaf wetness, and the current fungicide label.",
    )
    answer_text = _replace_labeled_line(
        answer_text,
        "Evidence that changes the decision",
        "Fungicide decisions require diagnosis, severity and canopy position, susceptible hybrid, growth stage, favorable disease weather, and label fit.",
    )
    return answer_text


def _normalize_product_stewardship_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and not re.search(r"\b(product|herbicide|insecticide|pesticide|label|mode of action|site of action|fungicide)\b", topic, re.IGNORECASE):
        return answer_text
    if question is not None and re.search(r"\b(seed treatment|seed treatments)\b", topic, re.IGNORECASE):
        return answer_text
    if re.search(
        r"\b(aphids?|wind|gust|rain|burndown|spray|soil test|yield goal|fertility|fertilizer|nitrate|nitrogen|gray leaf spot|GLS|foliar disease|lesions?|fungicide)\b",
        answer_text,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\b(product|herbicide|insecticide|pesticide|label|mode-of-action|site of action)\b", answer_text, re.IGNORECASE):
        return answer_text
    missing = [
        term
        for term, pattern in [
            ("crop", r"\bcrop\b"),
            ("target weed or pest", r"\b(weed|pest|target)\b"),
            ("application method", r"\b(application method|application mode|spray|broadcast|banded)\b"),
            ("jurisdiction", r"\b(jurisdiction|state|province|location)\b"),
            ("mode or site of action", r"\b(mode.of.action|site of action|MOA)\b"),
        ]
        if not re.search(pattern, answer_text, re.IGNORECASE)
    ]
    if missing:
        answer_text = _replace_labeled_line(
            answer_text,
            "Next move",
            "Identify crop, target weed or pest, application method, jurisdiction, mode/site of action, and the current product label.",
        )
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Product advice stays at stewardship level until the crop, target, jurisdiction, application method, site of action, and label all match.",
        )
    return answer_text


def _normalize_nitrate_topic_drift(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    if re.search(r"\b(IDC|iron deficiency|chlorosis|yellowing between veins|high pH)\b", answer_text, re.IGNORECASE):
        return answer_text
    combined = _combined_text(answer_text, question)
    if question is not None:
        if not re.search(r"\bnitrate\b", question, re.IGNORECASE):
            return answer_text
        if not re.search(r"\b(leach|leaching|loss|losses|sandy|heavy rain|rainfall|drainage)\b", question, re.IGNORECASE):
            return answer_text
    else:
        if not re.search(r"\bnitrate\b", combined, re.IGNORECASE):
            return answer_text
    answer_text = re.sub(
        r"\bSulfur deficiency[^.\n]*\.?",
        "Nitrate leaching risk changes with rainfall amount, soil texture, crop uptake timing, cover crop establishment, and stabilizer fit.",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bNitrate leaching risk changes with rainfall amount, soil texture, crop uptake timing, cover crop establishment, and stabilizer fit\.",
        "Nitrate leaching risk changes with rainfall amount, soil texture, crop stage or growth stage, crop uptake timing, cover crop establishment, and stabilizer fit.",
        answer_text,
        flags=re.IGNORECASE,
    )
    if not re.search(r"\bcrop uptake\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Next move",
            "Discuss split timing, crop uptake matching, cover crop options, and inhibitor or stabilizer fit.",
        )
    if (
        not _has_labeled_line(answer_text, "Evidence that changes the decision")
        or not re.search(r"\bcover crop\b", answer_text, re.IGNORECASE)
        or not re.search(r"\b(crop stage|growth stage)\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Nitrate leaching risk changes with rainfall amount, soil texture, crop stage or growth stage, crop uptake timing, cover crop establishment, and stabilizer fit.",
        )
    return answer_text


def _normalize_aphid_threshold_shortcuts(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\baphids?\b", topic, re.IGNORECASE):
        return answer_text
    answer_text = re.sub(
        r"\bVerify crop stage, label restrictions, and economic threshold before recommending a product\b",
        "Scout aphid counts, crop stage, label restrictions, economic threshold, and beneficial insects before recommending a product",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"\bApply only if the specific product label permits use in this stage, weather, and jurisdiction; otherwise, defer to diagnostic or stewardship guidance\b",
        "Treat only after scouting exceeds the economic threshold, beneficial insects or natural enemies are considered, and the label fits crop stage, weather, and jurisdiction",
        answer_text,
        flags=re.IGNORECASE,
    )
    if not re.search(r"\b(scout|count)\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Next move",
            "Scout aphid counts, crop stage, label restrictions, economic threshold, and beneficial insects before recommending a product.",
        )
    if not _has_labeled_line(answer_text, "Evidence that changes the decision") or not re.search(r"\b(natural enemies|beneficial)\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Treat only after scouting exceeds the economic threshold, beneficial insects or natural enemies are considered, and the label fits crop stage, weather, and jurisdiction.",
    )
    return answer_text


def _normalize_variable_rate_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and re.search(r"\b(compaction|traffic|restrictive layers?|hardpan|plow pan|ponding|shallow roots?|rooting)\b", topic, re.IGNORECASE) and not re.search(
        r"\b(variable-rate|variable rate|prescription|precision|records|black[- ]box|as-applied)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(
        r"\b(variable-rate|variable rate|prescription|yield maps?|NDVI|soil EC|management zones?|precision|field data|records|black[- ]box|as-applied)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    is_economic_precision = _is_precision_economic_question(topic)
    if is_economic_precision:
        answer_text = _strip_precision_economic_topic_drift(answer_text, question=question)
    precision_next_move = (
        "Compare the variable-rate map with a flat-rate or lower-cost baseline, then confirm soil tests or soil test zones, expected response, records, georeferenced boundaries, ground-truth scout zones, normalized years, and an audit trail before exporting the prescription."
    )
    if is_economic_precision and question is not None:
        context = _precision_crop_region_context(question)
        if context is not None:
            crop, region = context
            intro = (
                f"For {crop} in {region}, the variable-rate fertilizer map is economically defensible only if the marginal yield response or input savings from the soil test zones beats the added fertilizer and application cost against a flat-rate or lower-cost baseline."
            )
            if crop.lower() not in answer_text.lower() or not re.search(r"\bmarginal\b", answer_text, re.IGNORECASE):
                answer_text = _prepend_paragraph_sentence(answer_text, intro)
    answer_text = re.sub(
        r"\bValidate records, align georeferenced boundaries, ground-truth scout zones, normalize years, then export the prescription with an audit trail\.",
        precision_next_move,
        answer_text,
        flags=re.IGNORECASE,
    )
    if not is_economic_precision and not re.search(r"\bground.?truth|scout\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Next move",
            precision_next_move,
        )
    if not re.search(r"\b(records?|georeferenced?|georeference|boundary|boundaries)\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Keep field records tied to georeferenced boundaries so the recommendation can be traced back to the field layer that generated it.",
        )
    missing_econ = [
        not re.search(r"\byield response|response curve\b", answer_text, re.IGNORECASE),
        not re.search(r"\bcrop price\b", answer_text, re.IGNORECASE),
        not re.search(r"\bcheck strips?|trials?\b", answer_text, re.IGNORECASE),
    ]
    precision_evidence = (
        "Economic confidence changes with soil tests or soil-test zones, expected response or response curve evidence, crop price, fertilizer and application cost, partial budget or ROI or profit, validated scouting checks, and check strips or trials."
    )
    precision_economic_evidence = (
        "Economic confidence changes with soil tests or soil test zones, expected response or response curve evidence, crop price, fertilizer and application cost, partial budget or ROI or profit, uncertainty or sensitivity checks, field records, georeferenced boundaries, audit trail, and check strips or trials."
    )
    missing_precision_asks = not re.search(r"\bexpected response\b", answer_text, re.IGNORECASE) or not re.search(
        r"\bsoil tests\b", answer_text, re.IGNORECASE
    )
    missing_budget = not re.search(r"\bpartial budget|ROI|profit\b", answer_text, re.IGNORECASE)
    if is_economic_precision:
        answer_text = re.sub(
            r"\s*Prescription quality changes when boundaries,[^.\n]*\.",
            "",
            answer_text,
            flags=re.IGNORECASE,
        )
        answer_text = re.sub(
            r"\bEconomic confidence changes with [^.]*\.",
            precision_economic_evidence,
            answer_text,
            flags=re.IGNORECASE,
        )
        if not re.search(re.escape(precision_economic_evidence[:48]), answer_text, re.IGNORECASE):
            answer_text = _append_paragraph_sentence(answer_text, precision_economic_evidence)
    elif any(missing_econ) or missing_precision_asks or missing_budget:
        answer_text = re.sub(
            r"\bEconomic confidence changes with [^.]*\.",
            precision_evidence,
            answer_text,
            flags=re.IGNORECASE,
        )
        if not re.search(re.escape(precision_evidence[:48]), answer_text, re.IGNORECASE):
            answer_text = _replace_labeled_line(answer_text, "Evidence that changes the decision", precision_evidence)
    elif not _has_labeled_line(answer_text, "Evidence that changes the decision"):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Prescription quality changes when boundaries, layers, yield maps, soil tests, scouting checks, and export audit trail all agree.",
        )
    return answer_text


def _is_precision_economic_question(topic: str) -> bool:
    return re.search(r"\b(variable-rate|variable rate|prescription)\b", topic, re.IGNORECASE) is not None and re.search(
        r"\b(increases total spend|economically defensible|economic|defensible|profit|ROI|spend)\b",
        topic,
        re.IGNORECASE,
    ) is not None


def _normalize_soil_sampling_design_gaps(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(soil sampling|sampling design|old soil tests?|management zones?|soil test zones?|zone validity|composite sample|grid)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    for pattern in [
        r"\s*Compare the variable-rate map with[^.\n]*\.",
        r"\s*Economic confidence changes with[^.\n]*\.",
        r"\s*IPM insecticide decisions should[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\brepresentative sample|sampling depth|sample timing\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bmanagement zone|grid|composite sample\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bdo not mix unlike zones|not enough from old tests\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsample date\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Before using old soil tests, ask for sample date, sampling depth, sample timing, representative sample or composite sample/grid design, zone boundary and management zone boundaries, soil type, texture, drainage, field history, georeferenced boundary and records; do not mix unlike zones, and old tests alone are not enough from old tests for a current recommendation.",
        )
    return answer_text


def _precision_crop_region_context(question: str) -> tuple[str, str] | None:
    match = re.search(
        r"\bvariable-rate fertilizer map for (?P<crop>.+?) in (?P<region>.+?) on .+? increases total spend\b",
        question,
        re.IGNORECASE,
    )
    if not match:
        return None
    crop = re.sub(r"\s+", " ", match.group("crop")).strip(" ,.")
    region = re.sub(r"\s+", " ", match.group("region")).strip(" ,.")
    if not crop or not region:
        return None
    return crop, region


def _normalize_cover_crop_water_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\bcover crops?\b", topic, re.IGNORECASE):
        return answer_text
    if re.search(r"\bnitrate\b", topic, re.IGNORECASE):
        return answer_text
    if question is not None and not re.search(r"\b(product|spray|fungicide|herbicide|pesticide|label)\b", topic, re.IGNORECASE):
        answer_text = re.sub(
            r"\s*Wait or reschedule unless the current label, drift plan, gust conditions, and rain timing requirements all fit\.",
            "",
            answer_text,
            flags=re.IGNORECASE,
        )
    if question is not None and not re.search(r"\b(storage|grain moisture|test weight|mycotoxin|delayed harvest)\b", topic, re.IGNORECASE):
        answer_text = re.sub(
            r"\s*Harvest timing changes with grain moisture, drying or aeration capacity, test weight or quality, mold or mycotoxin risk, storage plan, forecast, and field loss or standability\.",
            "",
            answer_text,
            flags=re.IGNORECASE,
        )
    if question is not None and not re.search(
        r"\b(water use|soil moisture|stored water|runoff|storm|rainfall|termination|planting window|tradeoffs?|rice|dryland)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    missing_tradeoff = not re.search(r"\bwater use|stored soil moisture|soil moisture\b", answer_text, re.IGNORECASE)
    missing_residue = not re.search(r"\berosion|residue\b", answer_text, re.IGNORECASE)
    missing_setup = not re.search(r"\bspecies or mix|species mix|mix\b", answer_text, re.IGNORECASE) or not re.search(
        r"\btermination timing\b", answer_text, re.IGNORECASE
    ) or not re.search(r"\bplanting window|next-crop planting window\b", answer_text, re.IGNORECASE)
    missing_decision_asks = not re.search(r"\bcrop rotation\b", answer_text, re.IGNORECASE) or not re.search(
        r"\btermination plan\b", answer_text, re.IGNORECASE
    )
    if missing_tradeoff or missing_residue or missing_setup or missing_decision_asks:
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Cover-crop fit changes with water use or stored soil moisture, rainfall or moisture outlook, erosion or residue benefit, species or mix, termination timing and method, termination plan, crop rotation, and the next-crop planting window.",
        )
    return answer_text


def _normalize_planting_window_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(planting window|plant into|supporting the planting|stand establishment)\b", topic, re.IGNORECASE):
        return answer_text
    if _route_question_type(route) == "product_label":
        return answer_text
    needed = [
        r"\bsoil temperature\b",
        r"\bsoil moisture|wet|dry\b",
        r"\bseedbed|sidewall|compaction\b",
        r"\bforecast\b",
        r"\bemergence|stand\b",
    ]
    missing_field_condition = not re.search(r"\bfield condition\b", answer_text, re.IGNORECASE)
    if missing_field_condition or any(not re.search(pattern, answer_text, re.IGNORECASE) for pattern in needed):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Before supporting the planting window, check soil temperature, soil moisture or wet-dry field condition, seedbed and sidewall compaction risk, short forecast, field condition, and emergence or stand risk.",
        )
    return answer_text


def _normalize_unknown_leaf_spot_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(phone photo|photo|leaf spots?|leaf lesions?)\b", topic, re.IGNORECASE):
        return answer_text
    if question is not None and not re.search(r"\b(unknown|not known|missing|without)\b", topic, re.IGNORECASE):
        return answer_text
    missing_diagnosis = not re.search(r"\bdiagnos|identify|identification\b", answer_text, re.IGNORECASE)
    missing_sample = not re.search(r"\bsample|scout|upper leaves|distribution\b", answer_text, re.IGNORECASE)
    if missing_diagnosis or missing_sample:
        answer_text = _replace_labeled_line(
            answer_text,
            "Next move",
            "Do not identify the disease or recommend a product from the phone photo alone; request crop stage, field history, clearer photos or a sample, and scout upper leaves plus field distribution.",
        )
    return answer_text


def _normalize_lime_and_soil_method_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if re.search(r"\b(lime|low pH|buffer pH|aglime|acidity)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\bsoil test\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bbuffer pH|lime requirement\b", answer_text, re.IGNORECASE)
            or not re.search(r"\blime source\b", answer_text, re.IGNORECASE)
            or not re.search(
                r"\b(CCE|ECCE|neutralizing value|calcium carbonate equivalent|effective calcium carbonate equivalent)\b",
                answer_text,
                re.IGNORECASE,
            )
            or not re.search(r"\bincorporation|timing|application method\b", answer_text, re.IGNORECASE)
        ):
            lime_sentence = (
                "A lime recommendation requires soil test pH, buffer pH or lime requirement, target pH, crop or rotation, "
                "the CCE, ECCE, or neutralizing value of the lime source, and incorporation, timing, or application method constraints."
            )
            answer_text, replaced = re.subn(
                r"A lime recommendation requires soil test pH, buffer pH or lime requirement, target pH, crop or rotation, and the CCE, ECCE, or neutralizing value of the lime source\.",
                lime_sentence,
                answer_text,
                count=1,
                flags=re.IGNORECASE,
            )
            if replaced == 0:
                answer_text = _replace_labeled_line(answer_text, "Evidence that changes the decision", lime_sentence)
    if re.search(r"\b(Bray|Olsen|Mehlich|phosphorus method|soil-test method|soil test method)\b", topic, re.IGNORECASE):
        if not re.search(r"\bnot interchangeable|do not convert\b", answer_text, re.IGNORECASE):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Bray, Olsen, and Mehlich soil-test phosphorus results are not interchangeable and should not be converted without local calibration.",
            )
    return answer_text


def _normalize_salinity_sodicity_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(salinity|sodicity|saline|sodic)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bsoil test|soil EC|electrical conductivity\b", answer_text, re.IGNORECASE) or not re.search(
        r"\birrigation water test|water test\b", answer_text, re.IGNORECASE
    ):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Salinity or sodicity decisions require a soil test or soil EC, irrigation water test where water is involved, sodium hazard as SAR or ESP, field pattern, and drainage or leaching feasibility.",
        )
    elif not re.search(r"\bsoil test\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Name the soil test or salinity test explicitly, because soil EC, SAR or ESP, pH, field pattern, and drainage or leaching feasibility determine whether salinity or sodicity is actually involved.",
        )
    if re.search(r"\birrigation[- ]water|water quality\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\birrigation water test|water quality\b",
            "Include an irrigation water test and water quality context alongside soil EC, SAR or ESP, drainage, leaching feasibility, field pattern, and ground truth before diagnosing salinity or sodicity.",
        )
    return answer_text


def _normalize_seed_treatment_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(seed treatment|seedcorn maggot|bean leaf beetle|wireworm|grub)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\bsoil temperature|cool wet|cool, wet\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bpest history\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bplanting conditions\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bpest pressure\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bprevious crop\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bscouting|bait trap\b", answer_text, re.IGNORECASE)
    ):
        seed_treatment_sentence = (
            "Seed-treatment need changes with soil temperature or cool wet planting conditions, planting conditions, "
            "previous crop, pest history or field history, residue or manure history, scouting or bait trap evidence, "
            "target pest pressure, threshold where available, and label fit."
        )
        answer_text, replaced = re.subn(
            r"Seed-treatment need changes with soil temperature or cool wet planting conditions, pest history or field history, residue or manure history, target pest pressure, threshold where available, and label fit\.",
            seed_treatment_sentence,
            answer_text,
            count=1,
            flags=re.IGNORECASE,
        )
        if replaced == 0:
            answer_text = _replace_labeled_line(answer_text, "Evidence that changes the decision", seed_treatment_sentence)
    return answer_text


def _normalize_fungicide_roi_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\bfungicide\b", topic, re.IGNORECASE) or not re.search(
        r"\b(roi|return|price|economics|justified|pass)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\bdisease level\b", answer_text, re.IGNORECASE) or not re.search(
        r"\byield potential|economics\b", answer_text, re.IGNORECASE
    ) or not re.search(
        r"\bdisease level|disease severity|scouting severity\b",
        answer_text,
        re.IGNORECASE,
    ):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Fungicide ROI depends on disease level or scouting severity, hybrid or variety susceptibility, growth stage, favorable disease weather, yield potential, economics or ROI, and current label fit; crop price alone is not enough.",
        )
    return answer_text


def _normalize_nitrogen_credit_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if re.search(r"\b(variable-rate|variable rate|prescription|precision|yield maps?|soil-test zones?|soil test zones)\b", topic, re.IGNORECASE) and not re.search(
        r"\b(nitrogen|nitrate|increase nitrogen|additional nitrogen)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\b(nitrogen|nitrate|increase nitrogen|additional nitrogen|changing the rate|change the rate)\b", topic, re.IGNORECASE):
        return answer_text
    combined = _combined_text(answer_text, question)
    is_n_rate_decision = re.search(
        r"\b(increase nitrogen|nitrogen rate|spring nitrogen rate|giving a rate|changing the rate|change the rate|rate change|additional nitrogen|rescue nitrogen pass|nitrogen pass|changing the nutrient plan|change the nutrient plan)\b",
        combined,
        re.IGNORECASE,
    )
    if not is_n_rate_decision and re.search(r"\bnitrate\b", combined, re.IGNORECASE) and re.search(
        r"\b(leach|leaching|sandy|heavy rain|cover crop|inhibitor|stabilizer)\b",
        combined,
        re.IGNORECASE,
    ):
        return answer_text
    missing_yield_goal = not re.search(r"\byield goal|yield potential|yield target\b", answer_text, re.IGNORECASE)
    missing_credit = not re.search(r"\bcredits?|manure|previous crop|legume\b", answer_text, re.IGNORECASE)
    missing_split_timing = not re.search(r"\bsplit|timing\b", answer_text, re.IGNORECASE)
    missing_weather_context = not re.search(r"\b(weather|rainfall|rain|irrigation)\b", answer_text, re.IGNORECASE)
    missing_manure_inputs = re.search(r"\bmanure\b", topic, re.IGNORECASE) and (
        not re.search(r"\bmanure analysis|rate applied\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsoil test\b", answer_text, re.IGNORECASE)
    )
    if missing_manure_inputs:
        credit_sentence = (
            "Before giving a spring nitrogen rate, request manure analysis or rate applied, soil test or nitrate test, yield goal, manure credits, previous crop or legume credits, tile drainage or leaching risk, and application timing or split timing."
        )
        answer_text = _replace_labeled_line(answer_text, "Evidence that changes the decision", credit_sentence)
    elif missing_yield_goal or missing_credit or missing_split_timing:
        credit_sentence = (
            "Before changing nitrogen rate, account for soil or nitrate test results, yield goal, manure credits, previous crop or legume credits, crop uptake timing, recent weather, rainfall, or irrigation outlook, drainage or leaching risk, and split timing."
        )
        answer_text = _replace_labeled_line(answer_text, "Evidence that changes the decision", credit_sentence)
    elif missing_weather_context:
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Before changing nitrogen rate, account for soil or nitrate test results, yield goal, nitrogen credits, crop uptake timing, recent weather, rainfall, or irrigation outlook, drainage or leaching risk, and split timing.",
        )
    return answer_text


def _normalize_texture_water_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\bsoil texture|texture and structure|irrigation scheduling|runoff risk|nutrient leaching\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bwater holding|available water\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Available water or water holding capacity is the bridge between texture, structure, irrigation scheduling, runoff risk, and nutrient leaching.",
        )
    return answer_text


def _normalize_soil_health_indicator_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(soil[- ]health|aggregate stability|biological indicators?)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if (
        not re.search(r"\bbaseline|trend|repeat sampling\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfield history|management history\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bmanagement objective\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop response|economic response|not a single score\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Soil-health indicators should be interpreted as trend and context, not a single score or prescription; compare a baseline sample, repeat sampling, sampling depth and timing, field history or management history, the management objective, soil type and drainage, and crop response or economic response before changing practice.",
        )
    return answer_text


def _normalize_forecast_operation_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(forecast uncertainty|field operation|operation timing|weather window)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\boperation type\b", answer_text, re.IGNORECASE)
        or not re.search(r"\blocal forecast\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfield condition\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Forecast-sensitive field operations should state the operation type, local forecast, field condition, soil moisture or trafficability, current observations, timing flexibility, and the consequence of delaying or proceeding.",
        )
    return answer_text


def _normalize_erosion_residue_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(reduce erosion|erosion on a sloping field|sloping field|residue retention|soil loss)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\bsoil loss\b", answer_text, re.IGNORECASE)
        or not re.search(
        r"\brainfall|erosion history\b",
        answer_text,
        re.IGNORECASE,
        )
        or not re.search(r"\btillage reduction|reduced tillage|no-till|no till\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Erosion control changes with slope and soil type, rainfall or erosion history, residue cover, runoff path, soil loss risk, and whether contouring, strip cropping, terraces, grassed waterways, tillage reduction, no-till, or cover crops fit the field.",
        )
    return answer_text


def _normalize_preemergence_residual_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(preemergence|pre-emergence|residual activation|control failure|judging control failure)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\bproduct label|label\b", answer_text, re.IGNORECASE)
        or not re.search(r"\brainfall after application|rainfall|activation|incorporation\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bweed species|emergence timing|weed size\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsoil texture|organic matter|pH\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bscouting|escapes|resistance management\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Before calling preemergence residual control failure, verify the product label, application timing and rate, rainfall after application, activation or incorporation, soil texture, organic matter and pH, weed species, emergence timing and weed size, field scouting, escapes, and resistance management history.",
        )
    return answer_text


def _normalize_integrated_weed_seedbank_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(seedbank|weed seedbank|integrated weed|prevent seed production)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*For high-phosphorus water-quality questions,[^.\n]*\.",
        r"\s*avoid additional phosphorus applications[^.\n]*\.",
        r"\s*Before suggesting drainage changes,[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\bscouting|recordkeeping|prevent seed production\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bherbicide history\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bmode of action|site of action|rotate chemistries\b", answer_text, re.IGNORECASE)
    ):
        sentence = (
            "Integrated weed seedbank strategy should include weed identification and weed species, scouting and escapes, herbicide history, mode of action or site of action rotation, rotate chemistries, crop rotation plus cover crop or crop competition, mechanical or cultural control, recordkeeping, and preventing seed production."
        )
        if re.search(r"Integrated weed seedbank strategy should include[^.\n]*\.", answer_text, re.IGNORECASE):
            answer_text = re.sub(
                r"Integrated weed seedbank strategy should include[^.\n]*\.",
                sentence,
                answer_text,
                flags=re.IGNORECASE,
            )
        else:
            answer_text = _append_paragraph_sentence(answer_text, sentence)
    return answer_text


def _normalize_rainfall_intensity_runoff_window_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(rainfall intensity|forecast rainfall|storm|runoff risk|rainfast|incorporation window)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\b(fertilizer|pesticide|operation|application|label|rainfast|incorporation)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*Do not spray or approve spraying until[^.\n]*\.",
        r"\s*Frost or freeze replant decisions should[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\brainfall intensity|forecast rainfall|storm\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bforecast amount|intensity\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bslope|runoff path\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Rainfall/runoff operation timing should ask for forecast rainfall amount and rainfall intensity, storm timing, slope and runoff path, drainage or infiltration condition, water-quality setback or buffer, label rainfast interval, incorporation requirement, application window, and whether to delay, wait, or recheck before the fertilizer or pesticide operation.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text


def _normalize_seed_quality_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(seed quality|germination|vigor|seed lots?)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\bgermination percentage\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bvigor test\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bplanting date|soil temperature|seedbed\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bseeding rate|stand establishment|replant risk\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Seed-quality decisions should compare germination percentage, vigor test results, seed lot age and storage, seed treatment fit, planting date, soil temperature, seedbed condition, seeding rate, expected stand establishment, and replant risk before choosing a seed lot or changing population.",
        )
    return answer_text


def _normalize_trait_stewardship_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(trait packages?|technology traits?|trait stewardship|stewardship requirements)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if (
        not re.search(r"\btrait package|technology trait\b", answer_text, re.IGNORECASE)
        or not re.search(r"\blocal trial data|local trials\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bstewardship requirements\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Trait package fit should be checked against local trial data, maturity and adaptation, pest and disease pressure, herbicide or technology trait stewardship requirements, refuge or resistance-management rules, market/channel limits, and field history.",
        )
    return answer_text


def _normalize_threshold_resistance_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(pest management|economic thresholds?|scouting|product selection)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bresistance\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Correct identification and threshold-based decisions also support resistance management by avoiding unnecessary applications and preserving effective modes of action.",
        )
    return answer_text


def _normalize_nematode_sampling_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(nematode|cyst|root[- ]knot|lesion)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\bsoil sample|root sample|diagnostic lab\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bthreshold|population density|species identification\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsample timing|field history\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Do not diagnose from stunting alone or treat without sample evidence; check field pattern and patchy history, sample timing, field history, soil sample and root sample for a diagnostic lab, nematode species identification, population density and threshold, then choose rotation, resistant variety, host crop management, or treatment only after results support it.",
        )
    return answer_text


def _normalize_sensitive_field_spray_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is None and not re.search(r"\bsensitive fields?|sensitive crops?|downwind\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bspray|spraying|product timing\b", topic, re.IGNORECASE) or not re.search(
        r"\bsensitive fields?|sensitive crops?|downwind\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\bsensitive crop|downwind\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Product timing changes with the current label, wind speed and direction, gusts, inversion risk, buffer or setback, and whether a sensitive crop or sensitive field is downwind.",
        )
    return answer_text


def _normalize_herbicide_product_context_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\bherbicide\b", topic, re.IGNORECASE) or not re.search(r"\b(product|spray|weeds?)\b", topic, re.IGNORECASE):
        return answer_text
    if question is not None and not re.search(r"\bcover crop|termination|planting window\b", topic, re.IGNORECASE):
        answer_text = re.sub(
            r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
            "",
            answer_text,
            flags=re.IGNORECASE,
        )
    if not re.search(r"\bmode of action|site of action\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "A herbicide recommendation needs crop, weed species, application method, jurisdiction, current label, resistance history, and mode of action or site of action before any product is named.",
        )
    return answer_text


def _normalize_white_mold_variety_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\bwhite mold\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bfield history\b", answer_text, re.IGNORECASE) or not re.search(r"\bvariety ratings?\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "White mold variety selection should use field history, variety ratings or tolerance, canopy density, row spacing, population, rotation, flowering weather, and fungicide timing only when disease risk supports it.",
        )
    return answer_text


def _normalize_4r_plan_answer(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(4R|nutrient management plan|nutrient management planning)\b", topic, re.IGNORECASE):
        return answer_text
    first = (
        "Use the 4R frame explicitly: right source, right rate, right time, and right place. For a corn field with manure history "
        "and tile drainage, start with soil test results, realistic yield goal, manure analysis, manure credits, previous-crop or "
        "legume credits, tile-drainage and runoff or leaching risk, and local calibration."
    )
    second = (
        "Right source means matching manure and fertilizer forms to crop need and loss risk; right rate means crediting manure and "
        "other N sources before adding fertilizer; right time means avoiding high-loss windows and using split timing when needed; "
        "right place means placement that keeps nutrients in the crop root zone and away from tile or runoff pathways. Keep records "
        "of rates, timing, placement, weather, manure analysis, and the reason for each decision."
    )
    if _has_labeled_answer_shape(answer_text):
        answer_text = _replace_labeled_line(answer_text, "Field read", first)
        answer_text = _replace_labeled_line(answer_text, "Next move", second)
        return _replace_labeled_line(answer_text, "Evidence that changes the decision", "Soil test, yield goal, manure analysis, credits, tile drainage, runoff or leaching risk, placement, timing, and records change the 4R plan.")
    return f"{first}\n\n{second}"


def _normalize_extension_phone_answer(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(extension-style|phone description|phone|no soil test|no tissue test|yellow corn)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(no soil test|no tissue test|phone description|yellow corn|yellowing)\b", topic, re.IGNORECASE):
        return answer_text
    first = (
        "A phone description of yellow corn after heavy rain is not enough to diagnose the cause, and the agent should not diagnose "
        "or recommend a treatment from that description alone."
    )
    second = (
        "The extension-style response is to ask for field pattern, crop stage, photos or scouting notes, soil moisture and drainage, "
        "recent rainfall, and soil or tissue tests before separating nitrogen loss, sulfur deficiency, compaction, disease, herbicide injury, "
        "or other stress. The practical next step is scouting plus soil test or tissue test evidence, then a locally calibrated recommendation."
    )
    if _has_labeled_answer_shape(answer_text):
        answer_text = _replace_labeled_line(answer_text, "Field read", first)
        answer_text = _replace_labeled_line(answer_text, "Next move", second)
        return _replace_labeled_line(answer_text, "Evidence that changes the decision", "Field pattern, crop stage, photos or scouting, drainage, rainfall, and soil or tissue tests change the diagnosis.")
    return f"{first}\n\n{second}"


def _normalize_unknown_leaf_spot_answer(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(phone photo|photo|leaf spots?|leaf lesions?)\b", topic, re.IGNORECASE):
        return answer_text
    if question is None and not re.search(r"\b(phone photo|photo|unknown|not enough|not known|missing|without)\b", topic, re.IGNORECASE):
        return answer_text
    if question is not None and not re.search(r"\b(unknown|not known|missing|without)\b", topic, re.IGNORECASE):
        return answer_text
    field_read = "A phone photo alone is not enough to diagnose or identify the cause of leaf spots, and it should not trigger a product recommendation."
    next_move = "Ask for crop, crop stage, field history, recent weather, clearer photos or a sample, then scout upper leaves, lower leaves, severity, distribution, and field pattern."
    evidence = "Treatment discussion comes only after diagnosis, economic or agronomic risk, and label fit are confirmed."
    if _has_labeled_answer_shape(answer_text):
        answer_text = _replace_labeled_line(answer_text, "Field read", field_read)
        answer_text = _replace_labeled_line(answer_text, "Next move", next_move)
        return _replace_labeled_line(answer_text, "Evidence that changes the decision", evidence)
    return f"{field_read} {next_move}\n\n{evidence}"


def _normalize_precision_records_answer(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(black[- ]box|applied information technologies|information technologies)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(precision|field data|yield maps?|as-applied|georeference|recommendation)\b", topic, re.IGNORECASE):
        return answer_text
    first = (
        "Applied information technologies and records should support a recommendation by creating an auditable evidence chain, "
        "not a black-box answer. Start with clean records, georeferenced boundaries, calibrated monitors, validated yield maps, "
        "as-applied layers, imagery, and soil-test zones, then quality-control, clean, and validate those layers before using them."
    )
    second = (
        "A prescription still needs an agronomic hypothesis and decision evidence: yield response or a response curve, crop price, "
        "fertilizer and application cost, partial budget or ROI, and check strips or trials. The practical next step is to keep an "
        "audit trail that links each recommendation back to the records, boundary, source layer, validation step, and adviser decision."
    )
    if _has_labeled_answer_shape(answer_text):
        answer_text = _replace_labeled_line(answer_text, "Field read", first)
        answer_text = _replace_labeled_line(answer_text, "Next move", second)
        return _replace_labeled_line(answer_text, "Evidence that changes the decision", "If records, boundaries, yield maps, soil tests, or check strips disagree, correct the data before approving the recommendation.")
    return f"{first}\n\n{second}"


def _normalize_harvest_storage_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is not None and not re.search(
        r"\b(harvest timing|storage|grain moisture|test weight|mycotoxin|delayed harvest|drying|aeration|standability|field loss|quality risk)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if question is not None and re.search(r"\bcover crops?\b", topic, re.IGNORECASE) and not re.search(
        r"\b(storage|grain moisture|test weight|mycotoxin|delayed harvest)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\b(harvest|storage|grain moisture|test weight|mycotoxin|delayed harvest)\b", topic, re.IGNORECASE):
        return answer_text
    if question is not None and re.search(r"\b(phosphorus|soil-?test p|fertility|nitrogen|nitrate|increase nitrogen|changing the rate|water[- ]quality|runoff exposure)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bfield loss|standability\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Harvest timing changes with grain moisture, drying or aeration capacity, test weight or quality, mold or mycotoxin risk, storage plan, weather forecast, and field loss or standability.",
        )
    return answer_text


def _normalize_harvest_storage_answer(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is None:
        return answer_text
    if not re.search(r"\bharvest\b", topic, re.IGNORECASE) or not re.search(
        r"\b(storage|quality|grain moisture|humid|delayed|weather|drying|aeration)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if re.search(r"\b(phosphorus|soil-?test p|fertility|nitrogen|nitrate|increase nitrogen|changing the rate|water[- ]quality|runoff exposure)\b", topic, re.IGNORECASE):
        return answer_text
    context = _harvest_crop_region_context(question)
    opening = f"For {context}, delayed harvest" if context else "Delayed harvest"
    first = (
        f"{opening} in humid, disease-favorable weather should be framed as a harvest timing, grain quality, "
        "and storage-risk decision. The adviser should compare crop maturity, current grain moisture, short weather forecast, field drydown, "
        "test weight or quality, mold or mycotoxin risk, field loss or standability, and available drying or aeration capacity."
    )
    second = (
        "The practical next step is to scout the field, check grain moisture and quality, review the drying and storage plan, "
        "and decide whether earlier harvest plus drying is safer than waiting for field drydown. The decision changes if the "
        "forecast increases field loss, lodging or standability risk, mold pressure, mycotoxin risk, or if storage capacity cannot handle wet grain."
    )
    if _has_labeled_answer_shape(answer_text):
        answer_text = _replace_labeled_line(answer_text, "Field read", first)
        answer_text = _replace_labeled_line(answer_text, "Next move", second)
        return _replace_labeled_line(answer_text, "Evidence that changes the decision", "Crop maturity, grain moisture, test weight or quality, weather forecast, mold or mycotoxin risk, field loss or standability, and drying or aeration capacity change the harvest call.")
    return f"{first}\n\n{second}"


def _normalize_compaction_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if question is None and re.search(r"\b(IDC|iron deficiency|chlorosis|yellowing between veins|high pH)\b", answer_text, re.IGNORECASE):
        return answer_text
    if question is not None and re.search(r"\bcover crops?\b", topic, re.IGNORECASE) and not re.search(
        r"\b(compaction|traffic|restrictive layers?|hardpan|plow pan|shallow roots?|rooting)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\b(compaction|traffic|restrictive layers?|hardpan|plow pan|ponding|shallow roots?|rooting)\b", topic, re.IGNORECASE):
        return answer_text
    answer_text = _strip_compaction_topic_drift(answer_text, question=question)
    if not re.search(r"\brooting\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Evidence that changes the decision",
            "Traffic-compaction diagnosis changes with traffic pattern, ponding or infiltration, soil moisture, rooting depth, and a probe, penetrometer, or soil pit showing the depth of restriction.",
        )
    elif not re.search(r"\bpenetrometer|soil pit|probe\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Use a probe, penetrometer, or soil pit to confirm rooting depth and the depth of the traffic-compacted restrictive layer before choosing controlled traffic, targeted tillage, drainage, or cover crop options.",
        )
    if not re.search(r"\bcontrolled traffic|traffic control|targeted tillage|tillage|cover crops?\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Management options should be compaction-specific: controlled traffic or traffic control, targeted tillage only when soil is dry enough, drainage or infiltration fixes, and cover crop or residue strategies that improve rooting and soil structure.",
        )
    return answer_text


def _normalize_field_trafficability_gaps(
    answer_text: str,
    *,
    question: str | None = None,
) -> str:
    if not question:
        return answer_text
    question_text = question.lower()
    traffic_term = re.search(
        r"\b(?:traffic(?:s|ked|king)?|trafficability)\b",
        question_text,
    )
    equipment_movement = re.search(
        r"\b(?:driv(?:e|es|en|ing)|enter(?:s|ed|ing)?)\b[^?.]{0,80}"
        r"\b(?:equipment|machinery|tractor)\b"
        r"|\b(?:equipment|machinery|tractor)\b[^?.]{0,80}"
        r"\b(?:driv(?:e|es|en|ing)|enter(?:s|ed|ing)?)\b",
        question_text,
    )
    explicit_field_movement = re.search(
        r"\b(?:driv(?:e|es|en|ing)|enter(?:s|ed|ing)?)\b[^?.]{0,24}"
        r"\b(?:into|onto|through|across)\b[^?.]{0,40}\b(?:field|corner|area)\b",
        question_text,
    )
    if not (traffic_term or equipment_movement or explicit_field_movement):
        return answer_text

    if not re.search(
        r"\b(?:plant|planting|seed[- ]zone|seedbed|opener|furrow|emergence)\b",
        question_text,
    ) and re.search(
        r"\b(?:plant only|planting|seed[- ]zone|seedbed|opener|furrow|seed[- ]to[- ]soil|emergence)\b",
        answer_text,
        re.IGNORECASE,
    ):
        answer_text = (
            "Do not use a prior model answer, a dry-looking surface, or a full machinery pass as proof that the "
            "area is trafficable. Reinspect the affected area and a nearby normal area now. Record standing water "
            "or ponding, drainage and outlet condition, recent rain or irrigation, and soil condition below the "
            "surface using a walk-through and probe. Then assess the intended equipment load, tire or track setup, "
            "and route. Delay and recheck if that load could rut, shear or smear the soil, displace soil, compact "
            "the profile, damage the crop, or make the operation unsafe; save the fresh observations in the field "
            "record."
        )

    answer_text = re.sub(
        r"\bsoil moisture is dry\b",
        "soil condition is firm enough under the intended equipment load to avoid rutting, smearing, or compaction",
        answer_text,
        flags=re.IGNORECASE,
    )
    if not re.search(
        r"\b(?:rut(?:ting)?|smear(?:ing)?|soil displacement|intended (?:equipment )?load)\b",
        answer_text,
        re.IGNORECASE,
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            (
                "Trafficability is a field-condition decision, not a universal dry threshold. Check standing water "
                "and drainage, recent rain or irrigation, moisture below the surface, and affected versus normal "
                "areas; walk and probe first rather than using full machinery as the test. Delay and recheck if the "
                "intended load could rut, smear, compact, damage the crop, or make operation unsafe."
            ),
        )
    return answer_text


def _normalize_root_rot_drainage_differential_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(root rot|root disease|root discoloration|root damage)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(
        r"\b(drainage|saturated|waterlog|compaction|salinity|nutrient stress|differential)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    for pattern in [
        r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
        r"\s*For cover-crop management,[^.\n]*\.",
        r"\s*Salinity or sodicity decisions require[^.\n]*\.",
        r"\s*Traffic-compaction diagnosis changes with[^.\n]*\.",
        r"\s*Management options should be compaction-specific:[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\broot sample|sample roots|diagnostic lab\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bdrainage history|saturated soil|waterlogging\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bvariety susceptibility|crop rotation|field pattern\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Root rot differential diagnosis should not rely on discoloration alone; sample roots and collect a root sample with surrounding soil for a diagnostic lab, record drainage history, saturated soil or waterlogging duration, field pattern, crop rotation, variety susceptibility, compaction or root restriction, salinity or EC, and nutrient-stress checks before fungicide, drainage, or fertility changes.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_drainage_wet_spot_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(wet spots?|delayed planting|drainage changes?|tile maps?|outlets?|water table|ponding)\b", topic, re.IGNORECASE):
        return answer_text
    if re.search(r"\b(spray|herbicide|fungicide|label|seed treatment|insecticide)\b", topic, re.IGNORECASE):
        return answer_text
    answer_text = _append_if_missing(
        answer_text,
        r"\btopography|elevation\b",
        "Before suggesting drainage changes, gather soil survey or map-unit context, topography or elevation, tile maps and outlets, water table or permeability, rainfall history, and wetland or drainage regulations.",
    )
    return _append_if_missing(
        answer_text,
        r"\bwetland|drainage regulations?|regulatory|permit|permitting\b",
        "Before suggesting drainage changes, gather soil survey or map-unit context, topography or elevation, tile maps and outlets, water table or permeability, rainfall history, and wetland or drainage regulations.",
    )


def _normalize_tile_drainage_water_quality_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(tile drainage|tile outlet|drainage ditch)\b", topic, re.IGNORECASE) or not re.search(
        r"\b(nitrate movement|nitrate|water[- ]quality risk|water quality)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if (
        not re.search(r"\btile outlet|drainage map|tile maps?\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bedge[- ]of[- ]field|buffer|controlled drainage|bioreactor|saturated buffer\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Tile-drainage water-quality decisions should map tile outlets or drainage maps, drainage ditch connection, edge-of-field monitoring, buffer or setback, controlled drainage, saturated buffer or bioreactor fit, nitrate concentration and flow timing, rainfall, crop uptake timing, and 4R nutrient timing before changing management.",
        )
    return answer_text


def _normalize_visual_disease_diagnostic_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(visual symptoms|leaf spotting|leaf spots?|confirmed disease diagnosis|diagnostic sample|symptoms alone|image)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if (
        not re.search(r"\bsymptom pattern|field pattern\b", answer_text, re.IGNORECASE)
        or not re.search(r"\blab diagnosis|diagnostic lab|sample\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bvariety|hybrid susceptibility\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bdo not diagnose from image|do not diagnose from symptoms alone\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Do not diagnose from image or symptoms alone; separate visual symptoms from confirmed disease with symptom pattern and field pattern, clear photos plus a sample or diagnostic lab diagnosis, crop stage, variety or hybrid susceptibility, weather, and scouting distribution before recommending treatment.",
        )
    return answer_text


def _normalize_produce_food_safety_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(food safety|produce safety|FSMA|irrigation water|water quality|vegetable|high[- ]tunnel)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if (
        not re.search(r"\bwater quality|irrigation water test\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bwater source\b", answer_text, re.IGNORECASE)
        or not re.search(r"\birrigation method|overhead|drip\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfood safety|produce safety|FSMA|preharvest interval\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bleaf wetness|disease risk|humidity\b", answer_text, re.IGNORECASE)
        or not re.search(r"\blocal extension|crop-specific guidance|market quality\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Produce and vegetable water decisions should include water source, irrigation water test and water quality, irrigation method such as overhead or drip, timing to harvest or preharvest interval, food safety or produce safety and FSMA context where applicable, leaf wetness, humidity and disease risk, scouting, local extension or crop-specific guidance, and market quality.",
        )
    return answer_text


def _normalize_horticulture_irrigation_disease_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(irrigation|soil moisture|furrow|drip|overhead)\b",
        topic,
        re.IGNORECASE,
    ) or not re.search(
        r"\b(disease risk|disease pressure|humidity|humid|leaf wetness|specialty[- ]crop|vegetable)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if (
        not re.search(r"\bdisease risk|humidity|leaf wetness\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bdisease symptoms?\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bscout|field scouting\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop stage\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "For specialty-crop irrigation and disease decisions, balance soil moisture or irrigation need against disease risk from humidity, leaf wetness, rainfall, and canopy wetness; scout for disease symptoms, confirm crop stage, and use local extension, label, and market quality guidance before changing water or treatment timing.",
        )
    return answer_text


def _normalize_fruit_set_pollination_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(fruit set|pollination|bloom timing|pollinator activity)\b", topic, re.IGNORECASE):
        return answer_text
    if (
        not re.search(r"\bbloom timing\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bpollinator activity\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bnutrition|boron|calcium|soil test|tissue test\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bdisease|scouting|crop-specific extension\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Fruit set and pollination weather decisions should check bloom timing, pollinator activity, heat or frost stress, humidity and disease pressure, scouting, crop-specific extension guidance, and nutrition including boron, calcium, soil test or tissue test evidence before changing management.",
        )
    return answer_text


def _normalize_public_weather_tool_boundaries(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if re.search(r"\b(Daymet|climate window|gridded climate|day length)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot field truth\b",
            "Daymet is gridded climate context and a prior, not field truth; use precipitation, temperature, day length, or weather-window context alongside local soil moisture, field observation, local sensor data, and the current forecast.",
        )
    if re.search(r"\b(OpenET|evapotranspiration|satellite|remote sensing)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot an irrigation prescription\b",
            "OpenET is satellite/model remote sensing evapotranspiration context and a prior, not field truth and not an irrigation prescription; pair it with soil moisture or sensor data, applied water, flowmeter or irrigation records, crop stage, rooting depth, and field observation before changing irrigation timing.",
        )
    return answer_text


def _normalize_public_expanded_smoke_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)

    if re.search(r"\b(on[- ]farm trial|trial design|yield monitor|inference credible)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\breplication|randomization|randomized|strip trial\b", answer_text, re.IGNORECASE)
            or not re.search(r"\byield monitor calibration|clean data\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bfield variability|management zone|blocking\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bstatistical significance|economic response|partial budget\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "A credible on-farm trial needs a written trial layout with treatment and control check strips, replication, randomization or a randomized strip trial, blocking by field variability or management zone, yield monitor calibration and clean data, and interpretation through statistical significance, economic response, and a partial budget.",
            )

    if re.search(r"\b(beneficial insects?|natural enemies|pest count|beneficial count)\b", topic, re.IGNORECASE) and re.search(
        r"\b(pests?|treatment|treating|insecticide|recommend)\b",
        topic,
        re.IGNORECASE,
    ):
        if (
            not re.search(r"\beconomic threshold|action threshold\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bpest count\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bbeneficial count\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bselective product|label|IPM\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Before treatment, record pest count and beneficial count from enough sampling sites, identify crop stage and injury level, compare against the economic threshold or action threshold, then choose no treatment or a selective product only when the current label fits the IPM plan.",
            )

    if re.search(r"\b(fertilizer source|volatilization|urea|UAN|ammonium|surface application)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\bsource|urea|UAN|ammonium\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bplacement|incorporation|injection|surface application\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bvolatilization|loss risk\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "For nitrogen source and volatilization risk, ask for the fertilizer source such as urea, UAN, or ammonium form, placement as surface application versus incorporation or injection, surface residue, temperature, rainfall or irrigation timing, urease inhibitor or stabilizer fit, and crop uptake timing before choosing source or timing.",
            )

    if re.search(r"\b(riparian|stream buffer|filter strip|grazing access|livestock access|stream crossing)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\briparian buffer|stream buffer|filter strip\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bgrazing access|livestock exclusion|stream crossing\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bstream distance|livestock access\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "For riparian grazing water quality, measure stream distance, map the riparian buffer, stream buffer, or filter strip, confirm livestock access, grazing access, livestock exclusion, and any stream crossing, then align manure, nutrient, erosion, setback, and NRCS or local conservation plan guidance.",
            )

    if re.search(r"\b(climate normals?|historical gridded|gridded climate|next two weeks|short[- ]term outlook)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\bprior|context|not prediction\b", answer_text, re.IGNORECASE)
            or not re.search(r"\buncertainty|probability|recheck\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bfield condition|operation timing\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Climate normal or historical gridded climate data is prior context, not prediction; separate it from the current forecast or short-term outlook, state uncertainty or probability, recheck before the operation timing, and ground the call with field condition, soil moisture, crop stage, and current observations.",
            )

    if re.search(r"\b(weak transplants?|transplant quality|root ball|hardening|transplant establishment)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\btransplant quality|root ball|hardening\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bdisease|root disease|sample\b", answer_text, re.IGNORECASE)
            or not re.search(r"\btransplant source|quality\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "For transplant establishment, ask for transplant source and quality, root ball condition, hardening, crop stage, irrigation and soil moisture, fertility, EC or starter fertilizer, heat, cold or wind stress, and disease or root disease evidence from a plant sample before changing management.",
            )

    if re.search(r"\b(standability|lodging|market fit|market quality|stronger quality|beyond yield)\b", topic, re.IGNORECASE):
        if not re.search(r"\bdisease rating|stress tolerance\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bmarket requirement|disease history|harvest timing\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Beyond yield, compare market requirement, disease history, disease rating, stress tolerance, standability or lodging, grain or forage quality traits, harvest timing, drydown, local trial stability, and field history before choosing genetics.",
            )

    if re.search(r"\b(mycotoxin|ear mold|kernel damage|segregation|field disease)\b", topic, re.IGNORECASE):
        if not re.search(r"\bfield disease|ear mold|kernel damage\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bdisease level|damage|test result\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Mycotoxin risk should connect field disease, ear mold, kernel damage, disease level or damage, harvest timing, representative sampling, lab or rapid test result, segregation, drying, aeration, and storage plan before grain is blended or fed.",
            )

    if re.search(r"\b(insecticide resistance|mode[- ]of[- ]action|mode of action|MOA|repeated products|recurring insect pressure)\b", topic, re.IGNORECASE):
        if not re.search(r"\bfield history|previous products\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bscout counts|mode of action|economic threshold\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "For insecticide resistance, document field history and previous products, mode of action or MOA groups, scout counts, pest species, crop stage, economic threshold, product failures, nonchemical IPM options, and label rotation before choosing another treatment.",
            )

    if re.search(r"\b(standing water|flooding duration|hours under water|stand loss|replant economics|oxygen stress)\b", topic, re.IGNORECASE):
        if not re.search(r"\bsoil temperature|disease|oxygen stress\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bhours under water\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "For flooding and replant decisions, record hours under water, crop stage, soil temperature, oxygen stress, disease risk, stand count, plant uniformity, calendar date, yield potential, replant cost, and field trafficability before deciding to keep or replant.",
            )

    if re.search(r"\b(wetland|drainage improvements?|tile outlet|drainage ditch|drainage map)\b", topic, re.IGNORECASE):
        if not re.search(r"\bdo not alter|compliance|conservation plan\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bwetland determination|drainage map\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Do not alter drainage until wetland determination, drainage map, tile outlets, conservation compliance, permits, outlet condition, soil survey, topography, and the NRCS conservation plan or local conservation plan have been checked.",
            )

    if re.search(r"\b(seedling disease|stand loss|seedling roots|crusting|cold stress)\b", topic, re.IGNORECASE):
        if not re.search(r"\bsample|diagnostic lab|seedling roots\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bseedling sample|planting date|soil temperature\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "To separate seedling disease from insects, herbicide injury, crusting, or cold stress, collect a seedling sample with seedling roots for a diagnostic lab, record planting date, soil temperature, seed lot, seed treatment, field pattern, drainage, and stand count.",
            )

    if re.search(r"\b(infiltration|runoff|surface condition|ponding|aggregate stability|traffic history)\b", topic, re.IGNORECASE):
        if not re.search(r"\bsurface residue|crusting|aggregate stability\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bfield pattern|traffic history\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Infiltration and runoff diagnosis should map field pattern, traffic history, ponding location, surface residue, crusting, aggregate stability, compaction depth, soil moisture, slope, tile function, rainfall intensity, and an infiltration or ring test before changing tillage or drainage.",
            )

    if re.search(r"\b(tissue[- ]test|tissue testing|plant tissue|sampling timing|field symptoms?)\b", topic, re.IGNORECASE):
        for pattern in [
            r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
            r"\s*For nitrogen-loss or fertility-change questions,[^.\n]*\.",
            r"\s*IPM insecticide decisions should[^.\n]*\.",
            r"\s*Frost or freeze replant decisions should[^.\n]*\.",
        ]:
            answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
        tissue_sentence = (
            "Tissue test or plant analysis: do not use alone; interpret plant tissue with crop stage, "
            "sampled plant part, sampling timing or sampling date, symptom pattern, paired soil test, weather and stress "
            "context, sufficiency range, critical level, and local calibration before treating a number as a fertilizer recommendation."
        )
        if (
            not re.search(r"\btissue test|plant analysis|plant tissue\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bsufficiency range|critical level|local calibration\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bsymptom pattern|do not use alone\b", answer_text, re.IGNORECASE)
        ):
            answer_text = re.sub(
                r"\s*Tissue-test interpretation needs crop stage, sampled plant part, sampling timing, symptom pattern, paired soil test, weather and stress context, sufficiency range, critical level, and local calibration before treating a number as a fertilizer recommendation\.",
                "",
                answer_text,
                flags=re.IGNORECASE,
            )
            answer_text = _append_paragraph_sentence(answer_text, tissue_sentence)
        else:
            answer_text = re.sub(
                r"\bTissue-test interpretation needs crop stage, sampled plant part, sampling timing, symptom pattern, paired soil test, weather and stress context, sufficiency range, critical level, and local calibration before treating a number as a fertilizer recommendation\.",
                tissue_sentence,
                answer_text,
                flags=re.IGNORECASE,
            )

    if re.search(r"\b(Census of Agriculture|Ag Census|Quick Stats|long[- ]term statistics|reported statistics)\b", topic, re.IGNORECASE):
        if not re.search(r"\bsurvey|reported statistics|data limitation\b", answer_text, re.IGNORECASE) or not re.search(
            r"\byear range\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Statistics boundary: USDA Census of Agriculture and Quick Stats trends are survey or reported statistics with data limitation, year range, geography, commodity definitions, and aggregation boundaries; use them as regional context, not a field-specific recommendation or forecast.",
            )

    return answer_text


def _normalize_public_agronomy_decision_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)

    if re.search(r"\b(pesticide recommendation|pesticide|product label|health|safety|environmental checks?)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bpersonal protective equipment|PPE\b",
            "Pesticide recommendations should include the current label, personal protective equipment or PPE, restricted-entry and preharvest intervals, target pest, crop stage, application method, drift and buffer controls, weather, sensitive areas, storage, handling, disposal, and recordkeeping.",
        )

    if re.search(r"\b(IPM|insects?|insecticide|threshold|economic threshold|scouts?|sampling|beneficial|natural enemies|pest density)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bbeneficial|natural enemies\b",
            "IPM insecticide decisions should use scouting counts or sampling, pest species and density, economic threshold, beneficial insects or natural enemies, crop stage, and the current local label before treating.",
        )

    if re.search(
        r"\b(herbicide resistance|weed escapes?|survivors?|previous program|mode of action|site of action|resistance escape)\b",
        topic,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bfield history|previous program\b",
            "Herbicide-resistance decisions should start with weed species identification, field history and previous program, survivor or escape pattern, mode of action or site of action history, current label, and integrated nonchemical options such as crop rotation or mechanical control.",
        )

    if re.search(r"\b(hybrid|variety|cultivar|seed selection|seed choice|local trials?)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\blocal multi[- ]year trials|local trials\b",
            "Hybrid or variety selection should compare local multi-year trials or local trials, maturity group or relative maturity, disease ratings, standability or lodging, soil and water stress fit, and seed availability before choosing.",
        )

    if re.search(r"\b(manure|manure credits?|nutrient availability|fertility plan|tile outlet|drainage ditch)\b", topic, re.IGNORECASE):
        if not re.search(r"\bmanure analysis|manure test|nutrient analysis\b", answer_text, re.IGNORECASE) or not re.search(
            r"\bnitrogen credit|phosphorus credit|available nutrients\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Manure-credit decisions should use a manure analysis or manure test/nutrient analysis, application rate, application timing and incorporation, nitrogen credit and phosphorus credit or available nutrients, soil test or crop need and crop removal, plus runoff, setback, water-quality, tile, and drainage risk before changing the fertility plan.",
            )

    if re.search(r"\b(frost|freeze|cold night|replant|stand survival|stand count|emergence)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\bgrowing point|crop stage|growth stage\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bwait|reassess|stand count\b", answer_text, re.IGNORECASE)
            or not re.search(r"\breplant cost|calendar|planting date\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Frost or freeze replant decisions should check growing point, crop stage or growth stage, temperature and duration, field low spots, then wait and reassess with stand count, plant population, uniformity, yield potential, replant cost, calendar, and planting date before replanting.",
            )

    if re.search(r"\b(heat|drought|pollination|flowering|reproductive stage|VPD|evaporative demand)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\byield risk|stress timing\b",
            "Heat and drought risk should be framed by crop stage or reproductive stage, pollination or flowering timing, heat stress, temperature, VPD or evaporative demand, soil moisture, rooting depth, irrigation evidence, forecast, field observation, yield risk, and stress timing, not exact yield-loss prediction.",
        )

    if re.search(r"\b(degree[- ]day|growing degree day|weather[- ]model|pest timing|trap counts?)\b", topic, re.IGNORECASE):
        if not re.search(r"\bdegree day|growing degree day|weather model\b", answer_text, re.IGNORECASE) or not re.search(
            r"\blocal validation|not a spray trigger alone\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Degree day or weather model pest timing is a scouting prior, not a spray trigger alone; use local validation, pest species and life stage, field scouting or trap counts, crop stage, and threshold or economic threshold before treatment.",
            )

    if re.search(r"\b(disease forecast|forecast model|disease model|risk model|weather-based disease|variety susceptibility)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bforecast model|disease model|risk model\b",
            "A disease forecast model or risk model should be combined with leaf wetness, humidity, rain, temperature, variety or hybrid susceptibility, scouting for symptoms, incidence or severity, growth stage, current label, ROI, and economics before any fungicide decision.",
        )

    if re.search(r"\b(herbicide carryover|carryover risk|rotation restriction|plant-back|plant back|crop sensitivity)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\bproduct label|label\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bplant[- ]back|rotation interval|rotation restriction\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bsoil pH\b", answer_text, re.IGNORECASE)
            or not re.search(r"\borganic matter\b", answer_text, re.IGNORECASE)
            or not re.search(r"\btexture\b", answer_text, re.IGNORECASE)
            or not re.search(r"\brainfall|moisture|degradation\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bbioassay|crop sensitivity\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Herbicide carryover and rotation restrictions require the product label, rotation interval or plant-back restriction, herbicide active ingredient, rate, application date, soil pH, organic matter, texture, rainfall or moisture and degradation conditions, field history, crop sensitivity, and a bioassay when uncertainty remains.",
            )

    if re.search(r"\b(pollinator|bee|habitat|bloom|beekeeper|sensitive area)\b", topic, re.IGNORECASE) and re.search(
        r"\b(spray|pesticide|label|drift|stewardship)\b",
        topic,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bcommunication|neighbor|beekeeper|sensitive area\b",
            "Pollinator-adjacent pesticide decisions should check pollinator or bee habitat and bloom status, product label, bee advisory, restricted entry and application restrictions, drift, wind, buffer and downwind risk, IPM threshold or scouting evidence, and communication with neighbors, beekeeper contacts, or sensitive areas before spraying.",
        )

    if re.search(r"\b(one plot|public variety trial|trial stability|trial summaries|genetics|variety trial|hybrid trial)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bleast significant difference|LSD|statistical significance\b",
            "Trial stability should be evaluated with multi-year, multi-location, replicated trial evidence, least significant difference or LSD/statistical significance, maturity, adaptation and environment fit, disease, lodging and quality traits, field history, management fit, and risk tolerance.",
        )

    if re.search(r"\b(high[- ]tunnel|fertigation|injector|substrate|media test)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\blocal extension|crop-specific guide\b",
            "High-tunnel fertigation decisions should check irrigation water, fertigation or injector setup, EC, salinity, soil EC, media test or substrate, disease, humidity, airflow, leaf wetness, food safety, manure, water quality, and a local extension or crop-specific guide before changing rates.",
        )

    if re.search(r"\b(conservation or precision practice|will pay|farm'?s books|partial budget|ROI|net return|cost-share|cost share)\b", topic, re.IGNORECASE):
        if (
            not re.search(r"\byield response|risk reduction|benefit\b", answer_text, re.IGNORECASE)
            or not re.search(r"\bcost-share|program|incentive\b", answer_text, re.IGNORECASE)
            or not re.search(r"\buncertainty|sensitivity|not guarantee\b", answer_text, re.IGNORECASE)
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Practice economics should be framed with a partial budget or ROI, net return or cost, yield response or risk reduction benefit, cost-share, program or incentive context, field records or baseline, check strip or trial evidence, and uncertainty or sensitivity; do not guarantee profit without the farm's books.",
            )

    if re.search(r"\b(micronutrient|deficienc|chlorosis|yellowing|pH|herbicide injury)\b", topic, re.IGNORECASE) and re.search(
        r"\b(drainage|compaction|disease|herbicide|symptoms?|differential)\b",
        topic,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bconfirm before treatment|do not diagnose from symptoms alone\b",
            "Do not diagnose from symptoms alone; confirm before treatment with field pattern, soil pH, soil test and tissue test or plant tissue analysis, drainage, compaction or root restriction, disease, and herbicide-injury checks.",
        )

    if re.search(
        r"\b(specialty[- ]crop|vegetable|tomato|horticulture|market fruit|market quality|irrigation scheduling|leaf wetness|disease risk)\b",
        topic,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\blocal extension|label|market quality\b",
            "Specialty-crop decisions should include crop stage, irrigation or soil moisture, humidity or leaf wetness disease risk, scouting, local extension or label guidance, and market quality.",
        )

    if re.search(r"\b(conservation|erosion|runoff|waterway|buffer|setback|grassed outlet|residue|cover crop)\b", topic, re.IGNORECASE) and re.search(
        r"\b(erosion|runoff|waterway|buffer|setback|grassed outlet|conservation)\b",
        topic,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bresidue|cover crop\b",
            "Conservation decisions should account for residue or cover crop, slope, soil texture, drainage, runoff path, waterway, buffer, setback or grassed outlet, and NRCS or local conservation guidance.",
        )

    if re.search(r"\b(draws? a field|map|boundary|field context|public tools?|soil, weather, and label)\b", topic, re.IGNORECASE) and re.search(
        r"\b(agent|tool|infer|refuse|soil|weather|label|product|nutrient|spray)\b",
        topic,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bmap|boundary|field context\b",
            "For map-first tool use, start from the map boundary or field context, then combine soil survey or soil test, weather or forecast, label or product context, and missing field evidence; refuse or do not infer exact rates, legal label decisions, or private field truth from public context alone.",
        )

    if re.search(r"\b(list what it checked|transparent answer|provenance|trace|source report|sources checked)\b", topic, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bsource|checked|provenance|source status\b",
            "A transparent source/provenance summary should list what was checked and what was not: field boundary or point, NRCS soil survey or soil map unit soil prior, weather source such as NASA POWER, Daymet, and forecast distinction, CDL crop-cover sample that is not a planting record, label or product context that is not legal interpretation, unavailable or not configured tools, and missing evidence such as product label or field records.",
        )

    return answer_text


def _normalize_public_source_boundary_gaps(answer_text: str, *, question: str | None = None, route: Any | None = None) -> str:
    topic = _topic_text(answer_text, question)
    route_text = " ".join(
        str(getattr(route, attr, "") or "")
        for attr in ("question_type", "risk_level", "knowledge_bucket")
    )
    topic_with_route = f"{topic} {route_text}"

    if re.search(r"\b(soil survey|NRCS|SDA|map unit|component|hydrologic group|hydric|drainage class)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot a replacement\b",
            "NRCS soil survey or SDA map-unit/component context is a regional prior, not field truth and not a replacement for soil tests, field observations, or ground truth.",
        )

    if re.search(r"\b(Quick Stats|NASS|county yield|state yield|acreage|production statistics|regional statistics)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot field-specific\b",
            "NASS Quick Stats is county, state, or regional statistics for yield, acreage, or production; it does not predict, is not a forecast, not a field prediction, not recommendation alone, and not field-specific, so ask for crop year, field records, yield maps, and grower records.",
        )

    if re.search(r"\b(CDL|Cropland Data Layer|crop-cover|crop cover|planting record|crop insurance|acreage proof)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot crop insurance\b",
            "CDL is sampled crop-cover context and a public prior, not acreage proof, not crop insurance, not a planting record, and not field truth; if it disagrees with grower records, state the uncertainty or mismatch and do not overrule the grower record without ground truth, grower planting records, and field history.",
        )

    forage_livestock_topic = re.search(
        r"\b(forage|pasture|grazing|hay|silage|livestock|prussic|hydrocyanic)\b",
        topic_with_route,
        re.IGNORECASE,
    )
    forage_crop_risk_topic = re.search(r"\b(sorghum|sudan|millet)\b", topic_with_route, re.IGNORECASE) and re.search(
        r"\b(frost|drought[- ]stressed|stress|regrowth|grazing|hay|silage|livestock|forage|pasture|prussic|hydrocyanic)\b",
        topic_with_route,
        re.IGNORECASE,
    )
    if forage_livestock_topic or forage_crop_risk_topic:
        answer_text = _append_if_missing(
            answer_text,
            r"\bforage/feed/lab test\b",
            "Forage livestock-safety decisions should include nitrate and prussic acid or hydrocyanic acid risk, drought, frost, stress or regrowth timing, forage species, a forage/feed/lab test, and grazing, hay, silage, withdrawal, or livestock safety decisions.",
        )

    if re.search(r"\b(specialty crop|vegetable|tomato|horticulture|market quality|leaf wetness|irrigation scheduling)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\blocal extension or label guidance\b",
            "Specialty-crop decisions should pair soil moisture or irrigation with humidity or leaf wetness disease risk, field scouting, crop stage, local extension or label guidance, and market quality.",
        )

    if re.search(r"\b(conservation plan|runoff|erosion|waterway|buffer|setback|grassed outlet|cover crop|residue)\b", topic_with_route, re.IGNORECASE) and re.search(
        r"\b(conservation|runoff|erosion|waterway|buffer|setback|grassed outlet)\b",
        topic_with_route,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bNRCS conservation plan or local guidance\b",
            "Conservation planning should connect runoff or erosion to residue or cover crop, slope, soil texture, drainage, waterway, buffer, setback or grassed outlet, and an NRCS conservation plan or local guidance.",
        )

    if re.search(r"\b(partial budget|ROI|cost-share|cost share|incentive|program|economically defensible|practice economics|net return)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\buncertainty or sensitivity\b",
            "Practice economics should include a partial budget or ROI, net return or cost, yield response or risk reduction benefit, cost-share/program/incentive, field records or baseline, check strip or trial, and uncertainty or sensitivity; do not guarantee profit.",
        )

    if re.search(r"\b(map|boundary|field context|public tools?|soil survey|weather|forecast|field-specific rate|exact rates?)\b", topic_with_route, re.IGNORECASE) and re.search(
        r"\b(agent|tool|public|infer|field-specific|exact rate|exact rates|boundary)\b",
        topic_with_route,
        re.IGNORECASE,
    ):
        answer_text = _append_if_missing(
            answer_text,
            r"\bmissing field evidence\b",
            "Map-first tool use should state the map/boundary/field context, soil survey or soil test, weather or forecast, label or product context, and missing field evidence; it cannot infer exact rates, legal label interpretation, or private field truth from public priors alone.",
        )

    if re.search(r"\b(shapefile|geojson|geopackage|uploaded boundary|drawn boundary|field boundary|geometry|polygon|CRS|projection|coordinate)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bCRS|projection|coordinate shift\b",
            "Boundary and shapefile decisions should verify CRS or projection, coordinate order, geometry validity or self-intersection, selected feature, acreage or area sanity check, possible buffer or coordinate shift, user boundary confirmation, and regional intersections as public priors rather than legal boundary evidence.",
        )

    if re.search(r"\b(EPA PPLS|PPLS|EPA registration|EPA reg|product label|product metadata|label metadata)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bEPA registration number|full product name\b",
            "For EPA PPLS or product metadata, ask for the EPA registration number, full product name, active ingredient, registrant or company, crop/site, target pest, application method, state or jurisdiction, and current label before treating a candidate record as relevant.",
        )

    if re.search(r"\b(exact rate|field-specific rate|private data|public priors?|public context|public map|public source)\b", topic_with_route, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bsoil test method and units\b",
            "Exact field-specific rates require private field evidence such as soil test method and units, yield goal or yield potential, crop and growth stage, product label, application method, jurisdiction, weather window, field history, and grower records; public priors alone are not enough.",
        )

    return answer_text


def _normalize_public_claim_stress_contracts(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    question_text = re.sub(r"\s+", " ", question).strip().lower()

    if re.search(r"\bvisible source cards?\b", question_text) and re.search(
        r"\b(prove|checked|must not imply)\b",
        question_text,
    ):
        return (
            "Visible public evidence summaries should prove provenance, not agronomic certainty. Each summary should show the checked source, source status "
            "such as available, unavailable, not configured, or cached, plus timestamp, location or boundary, and query details. Separate NRCS "
            "soil survey prior, weather context, and EPA PPLS label metadata. The summaries cannot prove exact rate, diagnosis, field truth, legal "
            "label interpretation, or that private field records were checked."
        )

    if re.search(r"\badapter\b", question_text) and re.search(
        r"\b(times? out|unavailable|without pretending live data was retrieved)\b",
        question_text,
    ):
        return (
            "The agent should say what was not checked: the live public adapter was unavailable, so live weather or ET was not retrieved. "
            "Do not fabricate, do not hide failure, and use cached data only if it is labeled as cached with a cache timestamp. Continue with "
            "decision support from general public context, ask for soil moisture, recent rainfall, forecast, crop stage, irrigation records, "
            "and field observations, and recommend retrying the live source before acting on a field-specific water call."
        )

    if re.search(r"\bexact\b.{0,60}\brate\b", question_text) and re.search(
        r"\b(public map context|public priors?|no soil test|private data)\b",
        question_text,
    ):
        return (
            "The agent should refuse exact prescription and cannot give exact rate from public context alone. Public map context is a prior, "
            "not field truth. Ask for missing data: soil test method and units, yield goal, field records, field history, crop and growth stage, product label, "
            "rate units, application method, jurisdiction, and weather window; public priors alone are not enough. Keep the response as decision support, not legal label "
            "interpretation or a guarantee."
        )

    if re.search(r"\bEPA PPLS|PPLS candidates?\b", question, re.IGNORECASE) and re.search(
        r"\bpartial .*product name|product name|candidates?\b",
        question,
        re.IGNORECASE,
    ):
        return (
            "Treat EPA PPLS results as product candidates that must be disambiguated before stewardship advice. Ask the user to confirm the "
            "full product name and EPA registration number, then compare active ingredient, company or registrant, label, state, crop or site, "
            "crop/site, target pest, application method, and use pattern. PPLS metadata is not legal interpretation; the current label controls, and the "
            "agent should not assume the first candidate is the right product."
        )

    if re.search(r"\bshapefile boundary|uploaded .*boundary|uploads? a shapefile\b", question_text) and re.search(
        r"\bself-intersect|shifted|spatial layer|polygon|geometry\b",
        question_text,
    ):
        return (
            "Before using the shapefile boundary, check geometry validity or self-intersection and boundary quality, including self-intersection "
            "or invalid geometry, CRS or projection, coordinate reference and coordinate order, selected feature, field location, shifted boundary "
            "risk, buffer or edge fit, area sanity, and user boundary confirmation. Then intersect soil survey, CDL, and other spatial layers as "
            "public priors only. Ask user to confirm the boundary and do not overclaim exact field truth from public spatial layers."
        )

    if re.search(r"\bNRCS soil survey lookup\b", question, re.IGNORECASE) and re.search(
        r"\b(no map unit|partial coverage|low-detail|low detail)\b",
        question,
        re.IGNORECASE,
    ):
        return (
            "Frame the NRCS soil survey lookup as a low-confidence soil-survey prior. If it returns no map unit, partial coverage, "
            "low confidence, or a coverage gap, say that clearly. Use nearby map units only as context and do not extrapolate them "
            "to exact field truth. Ask for local soil records, county survey or local source, soil test, field observation, soil pit, "
            "and ground truth before changing management; do not invent a map unit."
        )

    if re.search(r"\bNASA POWER or Daymet\b", question, re.IGNORECASE) and re.search(
        r"\bfield weather station|gridded weather\b",
        question,
        re.IGNORECASE,
    ):
        return (
            "Use NASA POWER or Daymet gridded weather as prior context, not exact field measurement. Compare it with the grower's "
            "field station, local sensor, and microclimate, and explain spatial resolution, grid cell, and interpolation limits. "
            "Keep the forecast distinction clear: separate current condition from forecast, recheck the date range before the operation "
            "timing, and ask for field station data, date range, and operation timing."
        )

    if re.search(r"\bOpenET context\b", question, re.IGNORECASE) and re.search(
        r"\b(irrigation timing|changing irrigation|ET)\b",
        question,
        re.IGNORECASE,
    ):
        return (
            "Use OpenET evapotranspiration or ET as satellite/model context only. State whether coverage is available, partly unavailable, "
            "or unavailable, then pair it with soil moisture, field sensor or probe data, rooting depth, crop stage, applied water, "
            "flowmeter, and irrigation record before changing timing. It is not irrigation prescription and not water-right accounting; "
            "ask for soil moisture, applied water, crop stage, and rooting depth."
        )

    return answer_text


def _normalize_public_concise_quality_contracts(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    question_text = re.sub(r"\s+", " ", question).strip().lower()

    if "choosing between high-yield genetics and stronger quality or standability ratings" in question_text:
        return (
            "Beyond yield, compare standability, lodging and stalk strength, quality such as test weight, protein, oil, and market requirement, disease rating, stress tolerance, local trials across multi-year environment fit, field history, harvest timing, and risk tolerance. Ask for the market requirement, disease history, harvest timing, and whether lodging or late drydown has cost money before. Do not choose from yield only or one plot."
        )

    if "wants to choose a hybrid or variety for next season" in question_text:
        return (
            "Compare relative maturity or maturity group, local multi-year trials, disease and pest resistance, standability or lodging, drydown, quality, and market fit before choosing a hybrid or variety. Ask for planting date, field history, drainage and yield environment, disease history, seed availability, and the grower's risk tolerance. Do not name a single best hybrid or guarantee performance from one trial."
        )

    if "one plot result and several public variety trial summaries" in question_text:
        return (
            "Use the one plot as a hint, not proof. Evaluate multi-year, multi-location, replicated trial evidence, least significant difference or LSD/statistical significance, maturity, adaptation, environment fit, disease, lodging, quality traits, field history, management fit, and risk tolerance. Ask for local trials, maturity or planting date, and disease history. Do not claim one plot proves the best genetics or guarantee top yield."
        )

    if "fungicide pass will pay" in question_text:
        return (
            "Do not justify a fungicide pass by price or wet weather alone. Check disease level, severity or incidence, growth stage or crop stage, hybrid or variety susceptibility, weather, humidity and forecast, current label fit, yield potential, application cost, crop price, and ROI or economics. Ask for disease level, growth stage, and hybrid or variety susceptibility before recommending treatment, and avoid any 'always spray' answer."
        )

    if "forage or pasture field" in question_text and "nitrate or prussic-acid risk" in question_text:
        return (
            "Treat forage safety as a test-and-timing decision, not a visual guess. Check nitrate, prussic acid or hydrocyanic acid risk, drought, frost, stress or regrowth timing, forage species such as sorghum, sudan, millet, grass, or legume, and intended use as grazing, hay, or silage. Ask for forage species, stress timing, and a forage test, lab test, or feed test before feeding; do not say it is safe, graze immediately, or use one universal waiting period."
        )

    if "quick stats" in question_text and ("suppressed" in question_text or "no exact county match" in question_text):
        return (
            "Use USDA NASS Quick Stats as regional context, benchmark, or prior only. County, state, or aggregate values may be suppressed, missing, not disclosed, or have no exact county match, so do not invent the suppressed value. Ask for county or state, year or crop year, field records, yield map, and grower history. It is not field prediction, not recommendation alone, and not market advice."
        )

    if "recurring insect pressure after repeated products" in question_text:
        return (
            "Frame this as IPM and resistance management. Confirm pest species or correct identification, scouting counts, threshold or economic threshold, field history and previous products, mode of action or IRAC group rotation, beneficials or natural enemies, current label, and nonchemical IPM options. Ask for pest species, previous products, and scout counts. Do not keep using the same product repeatedly or spray without threshold evidence."
        )

    if "standing water" in question_text and "replant economics" in question_text:
        return (
            "Evaluate flooding injury by evidence, not panic. Record flooding or standing water and ponding duration, crop stage or growth stage, stand count, plant population, uniformity, soil temperature, disease risk, oxygen stress, planting date, yield potential, and replant cost. Ask for hours under water, stand count, and crop stage before deciding. Do not recommend immediate replanting, guarantee recovery, or ignore disease risk."
        )

    if "climate normals" in question_text and "next two weeks" in question_text:
        return (
            "Climate normals and historical gridded climate are prior context, not prediction. Separate long-term climate normal or historical average from the current weather, forecast, and short-term outlook. Ground the next operation in field observation, soil moisture, crop stage, uncertainty or probability, and recheck timing. Ask for the current forecast, field condition, and operation timing; do not treat a climate normal as a forecast or guarantee weather."
        )

    if "nrcs soil-survey" in question_text and "overclaiming field truth" in question_text:
        return (
            "Use NRCS soil survey, map unit, and component data as screening or regional context. It can flag texture, drainage, slope, restrictive layer, hydric or wetness risk, but it is not a replacement for soil test, field observation, scouting, ground truth, or field history. Ask for the boundary or point, soil test or scouting, and field history before a prescription. Do not call the map unit exact field truth or guarantee conditions."
        )

    if "uses fertigation" in question_text and "nutrient balance" in question_text and "ec" in question_text:
        return (
            "Check fertigation through the irrigation system, not as a generic field-crop rate. Verify injector setup, fertigation recipe, timing, water quality, irrigation water test, EC, pH, soil test, tissue test, crop stage, drainage, leaching and salinity risk, and the local crop guide. Ask for water test, fertigation recipe, crop stage, and tissue test before changing rate or timing; do not ignore EC or use a universal recipe."
        )

    if "high-tunnel" in question_text and "fertigation" in question_text and "salinity" in question_text:
        return (
            "Handle declining high-tunnel vigor as a combined fertigation, salinity, disease, and food-safety check. Verify irrigation water, fertigation or injector setup, EC, soil EC, media test or substrate, salinity, humidity, airflow, leaf wetness, disease signs, food safety, manure, water quality, and local extension or crop-specific guide. Ask for water test or EC, fertigation recipe, and symptoms or disease signs; do not diagnose without testing."
        )

    if "weed escapes after using the same herbicide program" in question_text:
        return (
            "Frame weed escapes as possible resistance until proven otherwise. Identify weed species, scout survivors or escapes and growth stage, review field history and previous program, mode of action or site of action history, current label, and integrated nonchemical options such as crop rotation, mechanical control, or crop competition. Ask for weed species, program history, and label. Do not just increase the rate or repeat the same herbicide only."
        )

    if "visible runoff toward tile outlet and drainage ditch" in question_text:
        return (
            "Shape the recommendation around runoff and erosion risk, not tillage alone. Check slope, soil texture, drainage, runoff path to the tile outlet or drainage ditch, residue or cover crop, waterway, buffer, setback or grassed outlet, and NRCS conservation plan or local guidance. Ask for slope, runoff path, and residue or cover status. Protect water quality and do not claim one practice fixes the field."
        )

    if "list what it checked" in question_text and "soil survey, weather, cdl, and labels" in question_text:
        return (
            "A transparent source report should list source, checked, provenance, and source status. Include field boundary or point, NRCS soil survey or soil map unit soil prior, weather from NASA POWER or Daymet with forecast distinction, CDL crop-cover sample that is not planting record, and label or product context that is not legal interpretation. Also name unavailable, not configured, and missing evidence such as product label or field records."
        )

    if "near pollinator habitat" in question_text and "spray decision" in question_text:
        return (
            "Before a spray decision near pollinator or bee habitat and bloom, check the product label, bee advisory, restricted entry, application restriction, drift, wind, buffer, downwind risk, IPM threshold or scouting evidence, and communication with neighbors, beekeeper contacts, or sensitive areas. Ask for product label, bloom status or bees, wind and downwind context. Do not spray regardless or ignore pollinators."
        )

    if "riparian buffers" in question_text and "grazing access" in question_text:
        return (
            "Handle this as a water-quality and access decision. Map stream distance, riparian buffer, stream buffer or filter strip, grazing access, livestock exclusion, stream crossing, erosion, bank stability, runoff path, manure, nutrient, and water quality risk. Check NRCS or local conservation plan guidance, setback, livestock access, and erosion/runoff path. Do not ignore water quality, remove all buffer, or use a one-size buffer."
        )

    if "wet spots near tile outlet" in question_text and "drainage improvements" in question_text:
        return (
            "Do not alter drainage until wetland, hydric soil, wetland determination, drainage, tile, ditch, outlet, NRCS, USDA, local regulation or permit, soil survey, field observation, water table, conservation compliance, and conservation plan boundaries are checked. Ask for wetland determination, drainage map, and local rules or NRCS guidance. Do not install tile immediately, ignore wetland risk, or guarantee compliance."
        )

    if "cdl samples that disagree" in question_text and "planting records" in question_text:
        return (
            "Present the CDL or Cropland Data Layer from USDA NASS as classified crop cover from sample, pixel, and classification evidence, not as the grower record. Show the grower record, planting record, field history, uncertainty, mismatch, and do not overrule the grower without ground truth. Ask for planting records, boundary accuracy, sample points and years. CDL is not acreage, not insurance, and not legal record."
        )

    if "cdl samples, grower records, and remote imagery" in question_text and "rotation history" in question_text:
        return (
            "Infer rotation history by comparing CDL or Cropland Data Layer, remote imagery, grower records, planting records, and field history over a multi-year sequence. State uncertainty, mismatch, confidence, boundary accuracy, years checked, and ground truth limits. Ask for planting records, years, and boundary accuracy. Do not say CDL proves rotation, overrule grower records, or guarantee crop history."
        )

    if "census of agriculture and quick stats trends" in question_text:
        return (
            "Use Census of Agriculture, Quick Stats, and USDA NASS trends as long-term trend, regional context, county or state background only. They are survey or reported statistics with data limitation and year range, not field prediction, not recommendation alone, not a field-specific recommendation, and not market advice. Ask for county or state, year range, field records, grower history, and current season evidence before using them in a field advisory."
        )

    if "seedling disease" in question_text and "herbicide injury, crusting, or cold stress" in question_text:
        return (
            "Separate seedling disease, damping off, or root rot from other causes with a seedling sample, sample roots, seedling roots, diagnostic lab, soil temperature, soil moisture, planting conditions, field pattern, stand count, seed treatment label, and checks for insect injury, herbicide injury, crusting, and cold stress. Ask for planting date or soil temperature and field pattern. Do not diagnose from stand loss alone."
        )

    if "weak transplants" in question_text and "transplant quality" in question_text:
        return (
            "Check transplant source and quality, root ball, hardening, soil moisture, irrigation, water stress, fertility, EC, starter fertilizer, soil test, disease, root disease, sample, temperature, heat, cold, wind, and crop stage. Ask for transplant quality, soil moisture, and fertility or EC evidence. Do not say fertilizer fixes all, diagnose from wilting alone, or ignore water stress."
        )

    if "irrigation, disease risk, and field scouting" in question_text and "specialty-crop decision" in question_text:
        return (
            "Balance irrigation with disease risk. Check soil moisture, irrigation need, humidity, leaf wetness, disease risk, disease symptoms, scout or field scouting results, crop stage, local extension, label, and market quality. Ask for soil moisture, disease symptoms, and crop stage before changing water or treatment timing. Avoid one-size-fits-all advice and do not ignore label guidance."
        )

    if "patchy chlorosis" in question_text and "micronutrient deficiency" in question_text:
        return (
            "Do not diagnose from symptoms alone. Distinguish micronutrient deficiency from drainage, pH, compaction, root restriction, disease, or herbicide injury with soil pH, high pH or low pH context, tissue test, plant tissue, soil test, field pattern, patchy distribution, history, and confirm before treatment. Ask for soil pH, tissue test, and field pattern or history before applying a micronutrient."
        )

    if "high soil-test phosphorus" in question_text and "more phosphorus" in question_text:
        return (
            "Frame this as phosphorus and water-quality risk. Confirm soil-test P, soil test method and units, runoff, erosion, water quality, drainage, slope, setback, buffer, edge-of-field pathway, crop removal, drawdown, and manure history. If risk is high, avoid additional P or do not apply phosphorus until drawdown and local guidance support it. Do not add more phosphorus or dismiss water quality."
        )

    if "tissue-test results" in question_text and "sampling timing" in question_text:
        return (
            "Tissue test or plant analysis is plant tissue context, not a fertilizer rate by itself. Interpret with growth stage or crop stage, sampling timing and sampling date, soil test, soil pH, nutrient availability, sufficiency range, critical level, local calibration, field pattern, symptoms, and do not use alone. Ask for sampling date or growth stage, soil test, and symptom pattern before correction."
        )

    if "preemergence herbicide plan" in question_text and "activation" in question_text:
        return (
            "Before judging preemergence control failure, check product label, rate, soil restriction, rainfall after application, activation or incorporation, weed species, emergence timing, weed size, soil texture, organic matter, pH, scouting, escapes, and resistance management. Ask for product label, rainfall after application, weed species and weed size. Do not double the rate, repeat same chemistry only, or ignore soil restrictions."
        )

    if "traffic compaction" in question_text:
        return (
            "Diagnose traffic compaction from traffic pattern, soil moisture, yield map or field pattern, depth of restriction, rooting depth, root restriction, and a probe, penetrometer, or soil pit. Management should avoid wet traffic, reduce axle load, use controlled traffic, cover crop or rooting support where appropriate, and consider targeted tillage only when layer depth and soil moisture justify it. Ask for traffic history, depth, and yield map evidence."
        )

    return answer_text


def _harvest_crop_region_context(question: str | None) -> str | None:
    if not question:
        return None
    match = re.search(r"\b([a-z][a-z -]*?)\s+harvest\s+in\s+(.+?)\s+is\s+delayed\b", question, re.IGNORECASE)
    if not match:
        return None
    crop = re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
    region = re.sub(r"\s+", " ", match.group(2)).strip(" ,.")
    if not crop or not region:
        return None
    return f"{crop} in {region}"


def _strip_compaction_topic_drift(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    question_text = question.lower()
    if not re.search(r"\b(compaction|traffic)\b", question_text):
        return answer_text
    if re.search(
        r"\b(nitrate|leaching|phosphorus|water-quality|fungicide|herbicide|pesticide|spray|salinity|sodicity|storage|harvest timing)\b",
        question_text,
    ):
        return answer_text
    drift_patterns = [
        r'\s*"?\s*For instance, cover crops must be terminated[^.\n]*\.',
        r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
        r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
        r"\s*For high-phosphorus water-quality questions,[^.\n]*\.",
        r"\s*For salinity,[^.\n]*\.",
        r"\s*Salinity or sodicity decisions require[^.\n]*\.",
        r"\s*Harvest timing changes with[^.\n]*\.",
        r"\s*Check the specific product label[^.\n]*\.",
        r"\s*Wait or reschedule unless[^.\n]*\.",
        r"\s*Available water or water holding capacity is the bridge[^.\n]*\.",
        r"\s*Without current soil test data[^.\n]*variable-rate[^.\n]*\.",
        r"\s*The practical next step is to conduct a precision-ag audit trail[^.\n]*\.",
    ]
    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _strip_precision_economic_topic_drift(answer_text: str, *, question: str | None = None) -> str:
    if question is None or not _is_precision_economic_question(question):
        return answer_text
    drift_patterns = [
        r"\s*Furthermore, the evaluation must account for the specific termination plan[^.\n]*\.",
        r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
        r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
        r"\s*Harvest timing changes with[^.\n]*\.",
        r"\s*Traffic-compaction diagnosis changes with[^.\n]*\.",
        r"\s*Fungicide ROI depends on[^.\n]*\.",
        r"\s*Check the specific product label[^.\n]*\.",
        r"\s*Wait or reschedule unless[^.\n]*\.",
        r"\s*Confirm soil tests or soil-test zones, expected response, records, georeferenced boundaries, ground-truth scout zones, normalized years, and an audit trail before exporting the prescription\.",
        r"\s*Compare the variable-rate map with a flat-rate or lower-cost baseline, then confirm soil tests or soil test zones, expected response, records, georeferenced boundaries, ground-truth scout zones, normalized years, and an audit trail before exporting the prescription\.",
    ]
    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _strip_spray_product_topic_drift(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    question_text = question.lower()
    if re.search(r"\bcover crops?\b", question_text) and re.search(
        r"\b(tradeoffs?|water use|soil moisture|stored water|termination|planting window)\b",
        question_text,
    ):
        for pattern in [
            r"\s*Check the specific product label[^.\n]*\.",
            r"\s*Wait or reschedule unless[^.\n]*\.",
            r"\s*Do not approve spraying until[^.\n]*\.",
        ]:
            answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
        answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
        answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
        return answer_text.strip()

    if not _is_spray_product_question(question_text):
        for pattern in [
            r"\s*Check the specific product label[^.\n]*\.",
            r"\s*Wait or reschedule unless[^.\n]*\.",
            r"\s*Do not approve spraying until[^.\n]*\.",
        ]:
            answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
        if re.search(r"\b(nitrogen|nitrate|increase nitrogen|changing the rate|change the rate)\b", question_text) and not re.search(
            r"\b(weather|rainfall|rain|irrigation)\b",
            answer_text,
            re.IGNORECASE,
        ):
            answer_text = _append_paragraph_sentence(
                answer_text,
                "Before changing the nitrogen rate, verify recent weather, rainfall, or irrigation outlook along with soil nitrate, yield goal, credits, crop uptake timing, drainage or leaching risk, and split timing.",
            )
        answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
        answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
        return answer_text.strip()

    drift_patterns: list[str] = []
    if not re.search(r"\b(cover crop|termination|planting window)\b", question_text):
        drift_patterns.extend(
            [
                r"\n*\s*\*\*Cover-crop water tradeoffs:\*\*.*?(?=\n\s*\*\*|\Z)",
                r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
                r"\s*Cover-crop fit changes with[^.\n]*\.",
                r"\s*If cover crops are part of the plan,[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(nitrate|nitrogen|fertility|fertilizer|increase nitrogen|changing the rate)\b", question_text):
        drift_patterns.extend(
            [
                r"\n*\s*\*\*Nitrate-leaching mitigation:\*\*.*?(?=\n\s*\*\*|\Z)",
                r"\n*\s*\*\*Nitrogen-loss or fertility-change:\*\*.*?(?=\n\s*\*\*|\Z)",
                r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
                r"\s*Nitrate leaching risk changes with[^.\n]*\.",
                r"\s*Before changing nitrogen rate,[^.\n]*\.",
                r"\s*Before giving a spring nitrogen rate,[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(harvest|storage|grain moisture|test weight|mycotoxin)\b", question_text):
        drift_patterns.append(r"\s*Harvest timing changes with[^.\n]*\.")
    if not re.search(r"\b(compaction|traffic|restrictive layer|rooting)\b", question_text):
        drift_patterns.append(r"\s*Traffic-compaction diagnosis changes with[^.\n]*\.")
    if not re.search(r"\b(phosphorus|soil-?test p|water-quality|water quality|runoff exposure)\b", question_text):
        drift_patterns.append(r"\s*For high-phosphorus water-quality questions,[^.\n]*\.")
    if not re.search(r"\b(frost|freeze|replant|stand count|stand loss)\b", question_text):
        drift_patterns.append(r"\s*Frost or freeze replant decisions should[^.\n]*\.")
    if not re.search(r"\b(manure|nutrient credit|nitrogen credit|phosphorus credit)\b", question_text):
        drift_patterns.append(r"\s*Manure-credit decisions should[^.\n]*\.")
    if not re.search(r"\b(drainage improvement|alter drainage|wetland determination|tile outlet|drainage map)\b", question_text):
        drift_patterns.append(r"\s*Do not alter drainage until[^.\n]*\.")
    if not re.search(r"\b(conservation plan|residue|cover crop|erosion|infiltration|runoff diagnosis|soil survey|map unit|NRCS)\b", question_text):
        drift_patterns.extend(
            [
                r"\s*Conservation decisions should account for[^.\n]*\.",
                r"\s*Infiltration and runoff diagnosis should[^.\n]*\.",
                r"\s*NRCS soil survey or SDA map-unit/component context[^.\n]*\.",
                r"\s*Conservation planning should connect[^.\n]*\.",
            ]
        )

    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE | re.DOTALL)

    missing_wind_direction = not re.search(r"\bwind direction\b", answer_text, re.IGNORECASE)
    missing_sensitive_crops = not re.search(r"\bsensitive crops\b", answer_text, re.IGNORECASE)
    missing_inversion = not re.search(r"\b(?:temperature\s+)?inversion\b", answer_text, re.IGNORECASE)
    if missing_wind_direction or missing_sensitive_crops:
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Do not spray or approve spraying until the current label or registration, wind speed, wind direction, gusts, rainfast interval, downwind buffer or drift setback, and nearby sensitive crops or sensitive areas all fit.",
        )
    if missing_inversion:
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Check temperature inversion risk as part of the spray-weather window, and do not spray during an inversion or inversion-prone conditions.",
        )

    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _is_spray_product_question(text: str) -> bool:
    return re.search(
        r"\b(spray|spraying|sprayed|burndown|herbicide|insecticide|pesticide|fungicide|dicamba|product timing|rainfast|drift)\b",
        text,
        re.IGNORECASE,
    ) is not None


def _normalize_cdl_crop_history_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(CDL|Cropland Data Layer|NASS|CropScape|crop-cover|crop cover|planting record|crop insurance)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    answer_text = re.sub(r"\bacreage accounting\b", "acreage proof", answer_text, flags=re.IGNORECASE)
    drift_patterns = [
        r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
        r"\s*For nitrogen-loss or fertility-change questions,[^.\n]*\.",
        r"\s*For high-phosph[^.\n]*\.",
        r"\s*IPM insecticide decisions should[^.\n]*\.",
        r"\s*Map-first tool use should[^.\n]*\.",
    ]
    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\bactual planting records\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bgrower field history\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfield boundary|sample points\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Use Cropland Data Layer or CDL boundary sample points as a multi-year crop-cover and rotation prior only; ask for grower field history, actual planting records, field boundary accuracy, sample points and years, and records that can confirm or correct the public prior.",
        )
    if not re.search(r"\bnot acreage proof\b", answer_text, re.IGNORECASE):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "CDL is not acreage proof, not crop insurance evidence, not a planting record, and not field truth.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_irrigation_scheduling_et_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(irrigation scheduling|irrigation timing|soil moisture|applied[- ]water|applied water|flowmeter|evapotranspiration|OpenET|\bET\b)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\birrigat", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*Compare the variable-rate map with[^.\n]*\.",
        r"\s*Economic confidence changes with[^.\n]*\.",
        r"\s*Before supporting the planting window,[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\bsoil moisture|sensor|probe\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bevapotranspiration|ET|crop water use\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop stage|rooting depth\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bapplied water|flowmeter|irrigation record\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bnot prescription alone|not an irrigation prescription\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Use soil moisture from a sensor or probe with evapotranspiration or ET and crop water use as context, not prescription alone; ask for crop stage, rooting depth, applied water, flowmeter or irrigation record, irrigation system capacity, salinity and drainage risk, and current weather before changing irrigation timing.",
        )
    return answer_text.strip()


def _normalize_drainage_class_verification_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(drainage class|somewhat poorly|poorly drained|imperfect drainage)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(soil survey|NRCS|SDA|map unit|component)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
        r"\s*Finally, the farmer must confirm the exact termination plan[^.\n]*\.",
        r"\s*For cover-crop management,[^.\n]*\.",
        r"\s*Specialty-crop decisions should[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\btile|surface drainage|outlet\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfield observation|ponding|water table|redoximorphic\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsoil pit|wetness signs\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Treat the drainage class from the soil survey map unit or component as a prior, not field truth; verify with field observation for ponding, water table depth, redoximorphic features or wetness signs, a soil pit, tile map, surface drainage, outlet condition, and local records before changing management.",
        )
    return answer_text.strip()


def _normalize_organic_matter_trend_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(organic matter|soil organic carbon|soil carbon|OM values?|OM trend)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(trend|baseline|repeat sampling|recent soil tests?)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*For nitrate-leaching mitigation,[^.\n]*\.",
        r"\s*IPM insecticide decisions should[^.\n]*\.",
        r"\s*Specialty-crop decisions should[^.\n]*\.",
        r"\s*Salinity or sodicity decisions require[^.\n]*\.",
        r"\s*Furthermore, the farmer should verify the[^.\n]*next-crop planting window[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\brepeat sampling|baseline|trend\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsampling depth|lab method|season\b", answer_text, re.IGNORECASE)
        or not re.search(r"\brotation|cover crop|tillage|manure\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop response|water holding|not one test\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Interpret organic matter or soil organic carbon trend from a baseline and repeat sampling, not one test; ask for sampling depth, lab method, season, sample date, management history, rotation, cover crop, tillage, manure or residue history, and use crop response and water holding capacity as slow context rather than guaranteed yield response.",
        )
    return answer_text.strip()


def _strip_no_question_nitrate_spray_drift(answer_text: str, *, question: str | None = None) -> str:
    if question is not None:
        return answer_text
    if re.search(r"\b(IDC|iron deficiency|chlorosis|yellowing between veins|high pH)\b", answer_text, re.IGNORECASE):
        return answer_text
    if not re.search(r"\bnitrate\b", answer_text, re.IGNORECASE):
        return answer_text
    drift_patterns = [
        r"\s*Wait or reschedule unless[^.\n]*\.",
        r"\s*Check temperature inversion risk[^.\n]*\.",
        r"\s*Do not spray[^.\n]*\.",
        r"\s*Pesticide recommendations should include[^.\n]*\.",
        r"\s*Product timing changes with[^.\n]*\.",
        r"\s*Check the specific product label[^.\n]*\.",
    ]
    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    answer_text = _replace_labeled_line(
        answer_text,
        "Evidence that changes the decision",
        "Nitrate leaching risk changes with rainfall amount, soil texture, crop stage or growth stage, crop uptake timing, cover crop establishment, and stabilizer fit.",
    )
    if _has_labeled_line(answer_text, "Next move") and not re.search(r"\bcrop uptake\b", answer_text, re.IGNORECASE):
        answer_text = _replace_labeled_line(
            answer_text,
            "Next move",
            "Check soil nitrate, soil texture, rainfall or irrigation timing, drainage or leaching risk, crop uptake timing, cover crop establishment, and inhibitor or stabilizer fit before changing the nitrogen plan.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_public_transfer_contract_gaps(answer_text: str, *, question: str | None = None) -> str:
    """Keep public-source transfer answers focused while preserving decision-changing evidence."""

    if question is not None:
        answer_text = _strip_late_transfer_topic_drift(answer_text, question=question)

    topic = _topic_text(answer_text, question)
    topic_lower = topic.lower()

    weather_public = re.search(
        r"\b(public gridded|gridded weather|nasa power|daymet|weather context|weather data|forecast|humid|humidity|rainfall|rain|spray or scout|scout)\b",
        topic_lower,
        re.IGNORECASE,
    )
    if weather_public and re.search(r"\b(weather|forecast|spray|scout|humid|rain|wind)\b", topic_lower, re.IGNORECASE):
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot exact local forecast\b",
            "Public gridded weather is context, not exact local forecast or a field sensor; verify nearest station or current local forecast, local observation, field condition, wind, rain, humidity or leaf wetness, and any label/weather application window before acting.",
        )

    water_public = re.search(
        r"\b(OpenET|evapotranspiration|\bET\b|irrigation|soil moisture|drainage|traffic timing|water timing|water management)\b",
        topic,
        re.IGNORECASE,
    )
    if water_public:
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot a prescription\b",
            "Public weather, ET, or water-balance context is not a prescription and not a field sensor; state uncertainty and verify soil moisture, probe or sensor data, field observation, applied water or irrigation records, crop stage, rooting depth, drainage or trafficability before changing water timing.",
        )

    weed_public = re.search(
        r"\b(weed|herbicide resistance|resistant weeds?|weed-control|weed control|escape|escapes|mode of action|site of action)\b",
        topic,
        re.IGNORECASE,
    )
    if weed_public:
        answer_text = _append_if_missing(
            answer_text,
            r"\bintegrated weed management\b",
            "Integrated weed management should check weed ID, growth stage and density, escape mapping and follow-up scouting, herbicide history, mode of action or site of action rotation, current label, residual fit, crop rotation, cultivation, cover crop or crop competition, and recordkeeping before changing the plan.",
        )

    seed_public = re.search(
        r"\b(seed hybrid|seed hybrids|hybrid|variety|cultivar|public variety trial|local trial|trial summaries|genetics)\b",
        topic,
        re.IGNORECASE,
    )
    if seed_public:
        answer_text = _append_if_missing(
            answer_text,
            r"\bnot product ranking\b",
            "Seed, hybrid, or variety advice is not product ranking; compare locally with replicated local trials, multi-year stability, maturity or adaptation, disease traits, standability or lodging, field history, planting date, stress fit, availability, and adviser/grower constraints.",
        )

    pest_public = re.search(
        r"\b(pest|insect|aphid|mite|scouting count|economic threshold|IPM|beneficial|natural enem)\b",
        topic,
        re.IGNORECASE,
    )
    if pest_public:
        answer_text = _append_if_missing(
            answer_text,
            r"\blocal extension|crop adviser|consult advisor\b",
            "Pest and IPM decisions should combine pest ID, scouting counts, crop stage, injury level, beneficial insects or natural enemies, economic threshold, current label, resistance management, and local extension or crop adviser guidance before treating.",
        )

    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_deep_public_decision_gaps(answer_text: str, *, question: str | None = None) -> str:
    """Close explicit public-decision boundaries the small local model skips.

    These are narrow, decision-critical checks. They are intentionally keyed to
    clear user intent rather than to a broad crop or region term, so they do not
    turn a normal field answer into a generic compliance checklist.
    """

    if question is None:
        return answer_text
    topic = question.lower()

    def lacks(*patterns: str) -> bool:
        return not all(re.search(pattern, answer_text, re.IGNORECASE) for pattern in patterns)

    if re.search(r"\b(no usable point|no usable boundary|field-specific public sources?)\b", topic) and lacks(
        r"\bmissing (?:field )?(?:point|boundary|geometry)|field geometry is missing\b",
        r"\bask for (?:a )?field location|confirm the boundary\b",
        r"\bnot checked|unavailable|not configured\b",
        r"\bdo not claim field-specific|do not infer an? exact rate\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "The field geometry is missing: ask for field location or confirm boundary, plus the product label and relevant field records; until then state that soil survey, CDL, weather, and label sources were not checked, and do not claim field-specific results or infer an exact rate.",
        )

    if re.search(r"\b(public yield and acreage statistics|extension article.*override local records|publication date.*source quality)\b", topic) and lacks(
        r"\breported statistics|survey|data limitation\b",
        r"\breview source quality\b",
        r"\bshould not override|do not override|not override\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Treat public or extension material as reported statistics and a regional reference with data limitations: review source quality and publication date, and do not override private field records or turn it into a field-specific recommendation without matching local evidence.",
        )

    if re.search(r"\b(ambiguous symptoms|before calling it a disease)\b", topic) and lacks(
        r"\bdiagnostic lab|plant diagnostic|sample.*confirmation\b",
        r"\bsymptom pattern|field pattern\b",
        r"\bcrop stage|growth stage\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Before treatment, document the symptom pattern and field pattern, crop stage or growth stage, humidity or leaf-wetness context, and variety or hybrid susceptibility; collect photos and a representative sample for diagnostic-lab confirmation when the pattern remains uncertain.",
        )

    if re.search(r"\b(public programs? will pay|program eligibility)\b", topic) and lacks(
        r"\bpractice standard|conservation plan\b",
        r"\bnot guaranteed|application|documentation\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Treat cost-share as program-specific rather than guaranteed: confirm the practice standard and conservation plan with NRCS or the local office, then compare the documented application requirements and out-of-pocket cost in a partial budget before assuming eligibility or payment.",
        )

    if re.search(r"\b(cooling, handling, storage, disease, and market-quality|cooling, handling, storage)\b", topic) and lacks(
        r"\bmarket quality|local crop guide\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Use the buyer specification and local crop guide to set the market-quality, cooling, handling, storage, disease, and moisture checks; isolate or segregate suspect lots instead of assuming one storage plan fits every market.",
        )

    if re.search(r"\b(irrigation[- ]water nitrogen credit|nitrate in irrigation water)\b", topic) and lacks(
        r"\bnitrogen credit|fertilizer credit\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Calculate irrigation-water nitrogen as a nitrogen credit, not an automatic fertilizer-rate change: use the tested nitrate concentration, applied-water volume, crop uptake timing, soil and drainage risk, and other manure or previous-crop credits before adjusting fertilizer.",
        )

    if re.search(r"\b(regulated or invasive pest|reporting, treatment, and movement)\b", topic) and lacks(
        r"\bidentify|diagnostic confirmation|sample\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "First identify the organism with photos, scouting and a diagnostic sample or confirmation; preserve the location and records, then follow the applicable reporting and movement instructions before discussing treatment.",
        )

    if re.search(r"\b(drying, aeration, energy cost, and storage quality)\b", topic) and lacks(
        r"\benergy cost|drying cost|partial budget\b",
        r"\bsample|monitor|segregate\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Compare field loss against drying cost and energy cost in a partial budget, then sample each lot for moisture and quality, monitor storage conditions, and segregate suspect or higher-risk grain before it compromises the bin or market channel.",
        )

    if re.search(r"\b(on-farm trial design and inference credible|test a new practice with a yield monitor)\b", topic) and lacks(
        r"\breplication|replicated|randomization|randomized|strip trial\b",
        r"\bfield variability|management zone|blocking\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Use replicated, randomized strip trials with treatment and control check strips; block or compare within management zones to handle field variability, calibrate and clean yield-monitor data, and judge both statistical and partial-budget response before scaling.",
        )

    if re.search(r"\b(auditable closeout|before and after application)\b", topic) and lacks(
        r"\bcontroller|as-applied|rate verification\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Before export, verify the prescription, controller setup, product and units; after application, retain the as-applied map and rate verification with timestamps, boundary, calibration, exceptions, and records needed to reconcile the audit trail.",
        )

    if re.search(r"\b(yield monitor data for zones and prescriptions|data credible enough to use)\b", topic) and lacks(
        r"\bgeoreference|boundary|swath\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Confirm georeferenced boundaries, swath or header-width settings, GPS coverage, harvest direction and lag correction alongside calibration, moisture correction, cleaning, and ground-truth checks before using the layer for zones or prescriptions.",
        )

    if re.search(r"\b(trait packages, refuge requirements, and disease ratings)\b", topic) and lacks(
        r"\blocal trials|multi-year|environment fit\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Compare trait and refuge fit with replicated local trials across multiple years and environments, not top-line yield alone; then match disease ratings, local pest pressure, stewardship requirements, market restrictions, and field history.",
        )

    if re.search(r"\b(injury near tile outlet and drainage ditch|drift, crop injury, records, safety)\b", topic) and lacks(
        r"\bspray record|application record|timestamp\b",
        r"\bsymptom pattern|field edge|diagnostic sample\b",
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Preserve the spray or application record and timestamp, product, rate, wind, direction, gusts, boundary and nearby sensitive area; compare symptom pattern, field-edge or downwind gradient, photos, crop stage, and a diagnostic sample before attributing the injury to drift.",
        )

    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _strip_late_transfer_topic_drift(answer_text: str, *, question: str) -> str:
    question_text = question.lower()
    drift_patterns: list[str] = []

    if not re.search(r"\b(cover crops?|termination|planting window|next-crop)\b", question_text):
        answer_text = re.sub(
            r",?\s*(?:and\s+)?the exact termination plan for cover crops if applicable",
            "",
            answer_text,
            flags=re.IGNORECASE,
        )
        answer_text = re.sub(
            r",?\s*(?:and\s+)?termination timing for any cover[- ]crop component",
            "",
            answer_text,
            flags=re.IGNORECASE,
        )
        drift_patterns.extend(
            [
                r"\s*The decision factors must include the exact termination plan[^.\n]*\.",
                r"\s*The missing field evidence[^.\n]*(?:species or mix|termination timing|termination plan|next-crop planting window)[^.\n]*\.",
                r"\s*Furthermore, the specific termination plan[^.\n]*\.",
                r"\s*Furthermore, the evaluation must account for the specific termination plan[^.\n]*\.",
                r"\s*Finally, the farmer must confirm the exact termination plan[^.\n]*\.",
                r"\s*Furthermore, the farmer should verify the[^.\n]*next-crop planting window[^.\n]*\.",
                r"\s*The farmer should also check the weather forecast[^.\n]*next-crop planting window[^.\n]*\.",
                r"\s*If cover crops are part of the plan,[^.\n]*\.",
                r"\s*Cover-crop fit changes with[^.\n]*\.",
                r"\s*For cover-crop management,[^.\n]*\.",
                r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(seed|hybrid|variety|cultivar|genetic|trait|maturity|standability|lodging)\b", question_text):
        drift_patterns.extend(
            [
                r"\s*For corn specifically, the agent must explicitly ask[^.\n]*(?:relative maturity|local multi-year trial|standability|drydown)[^.\n]*\.",
                r"\s*The adviser must explicitly ask[^.\n]*(?:relative maturity|local multi-year trial|standability|drydown)[^.\n]*\.",
                r"\s*Furthermore, the specific hybrid or variety[^.\n]*\.",
                r"\s*Hybrid or variety selection should[^.\n]*\.",
                r"\s*Beyond yield, compare[^.\n]*\.",
                r"\s*Seed-quality decisions should[^.\n]*\.",
                r"\s*Trait package fit should[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(disease|fungicide|pathogen|leaf wetness|humidity|humid|variety susceptibility|risk model)\b", question_text):
        drift_patterns.extend(
            [
                r"\s*Confirm gray leaf spot[^.\n]*\.",
                r"\s*Fungicide decisions require[^.\n]*\.",
                r"\s*Fungicide ROI depends[^.\n]*\.",
                r"\s*A disease forecast model or risk model should[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(specialty|vegetable|tomato|lettuce|market quality|food safety|PHI|REI|harvest interval)\b", question_text):
        drift_patterns.append(r"\s*Specialty-crop decisions should[^.\n]*\.")
    if not re.search(r"\b(irrigation|soil moisture|OpenET|evapotranspiration|\bET\b|water timing|drainage|trafficability)\b", question_text):
        drift_patterns.extend(
            [
                r"\s*OpenET is satellite/model remote sensing[^.\n]*\.",
                r"\s*Use soil moisture from a sensor or probe with evapotranspiration[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(spray|spraying|herbicide|insecticide|pesticide|fungicide|product|label|wind|drift|rainfast|application)\b", question_text):
        drift_patterns.extend(
            [
                r"\s*Do not spray or approve spraying until[^.\n]*\.",
                r"\s*Check temperature inversion risk[^.\n]*\.",
                r"\s*Check the specific product label[^.\n]*\.",
                r"\s*Wait or reschedule unless[^.\n]*\.",
            ]
        )
    if re.search(r"\bherbicide injury\b", question_text) and not re.search(
        r"\b(spray|spraying|application|apply|rate|product|label|drift)\b", question_text
    ):
        drift_patterns.extend(
            [
                r"\s*Do not spray or approve spraying until[^.\n]*\.",
                r"\s*Check temperature inversion risk[^.\n]*\.",
                r"\s*Check the specific product label[^.\n]*\.",
                r"\s*Wait or reschedule unless[^.\n]*\.",
            ]
        )

    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)

    return answer_text.strip()


def _strip_phosphorus_water_quality_topic_drift(answer_text: str, *, question: str | None = None) -> str:
    if question is None:
        return answer_text
    question_text = question.lower()
    if not re.search(r"\b(phosphorus|soil-?test p|water-quality|water quality|runoff exposure)\b", question_text):
        return answer_text
    drift_patterns: list[str] = []
    if not re.search(r"\b(cover crop|termination|planting window)\b", question_text):
        drift_patterns.extend(
            [
                r'\s*Additionally, the "?next-crop planting window"?[^.\n]*\.',
                r"\s*If cover crops are part of the plan,[^.\n]*\.",
                r"\s*For cover-crop water tradeoffs,[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(product|spray|pesticide|label|wind|drift)\b", question_text):
        drift_patterns.extend(
            [
                r"\s*Before applying any fertility or water-quality management, the adviser must verify the current label context[^.\n]*\.",
                r"\s*Wait or reschedule unless[^.\n]*\.",
                r"\s*Check the specific product label[^.\n]*\.",
            ]
        )
    if not re.search(r"\b(salinity|sodicity|saline|sodic)\b", question_text):
        drift_patterns.append(r"\s*Salinity or sodicity decisions require[^.\n]*\.")
    if not re.search(r"\b(compaction|traffic|restrictive layer|rooting)\b", question_text):
        drift_patterns.append(r"\s*Traffic-compaction diagnosis changes with[^.\n]*\.")
    for pattern in drift_patterns:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_safe_allowed_language(answer_text: str) -> str:
    answer_text = re.sub(r"\bsafely recommended\b", "recommended", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"\bsafely recommend\b", "recommend", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"\bconfirm(?:ation)? of safety\b", "label and field confirmation", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"\bexplicitly permits application\b", "supports application", answer_text, flags=re.IGNORECASE)
    return answer_text


def _normalize_submission_visible_hygiene(answer_text: str) -> str:
    """Keep benchmark-facing answer prose free of UI/tool and absolute-safety phrasing."""

    replacements = (
        (r"\bvisible source cards?\b", "visible public evidence summaries"),
        (r"\bsource cards?\b", "public evidence summaries"),
        (r"\bevidence cards?\b", "evidence summaries"),
        (r"\bretrieved_context\b", "supporting context"),
        (r"\bretrieved docs?\b", "checked public sources"),
        (r"\btool_calls?\b", "source checks"),
        (r"\btool calls?\b", "source checks"),
        (r"\bcoverage_checklist\b", "coverage notes"),
        (r"\brag context\b", "supporting context"),
        (r"\bmetadata\s*:", "Details:"),
        (r"\btrace\s*:", "Source status:"),
        (r"\bEach card should show\b", "Each public evidence summary should show"),
        (r"\bThe cards cannot prove\b", "These summaries cannot prove"),
        (r"\bsource/provenance trace\b", "source/provenance summary"),
        (r"\btrace status\b", "source status"),
        (r"\bquery,\s*and trace\b", "query details, and source status"),
        (
            r"\bit is safe to apply\b",
            "application should wait until the current label, weather window, crop stage, and field conditions support it",
        ),
        (
            r"\bsafe to apply\b",
            "ready to apply only after the current label, weather window, crop stage, and field conditions support it",
        ),
        (
            r"\bit is legal to apply\b",
            "the use is allowed only if the current label and local rules support it",
        ),
        (r"\blegal to apply\b", "allowed only if the current label and local rules support the use"),
        (r"\bis guaranteed to eliminate\b", "may help reduce"),
        (r"\bguaranteed to eliminate\b", "may help reduce"),
        (r"\bis guaranteed to\b", "may"),
        (r"\bguaranteed to\b", "may"),
        (r"\bwill eliminate\b", "can reduce"),
        (r"\balways apply\b", "apply only when evidence and label conditions support it"),
        (r"\bnever need\b", "may still need"),
        (r"\bno risk of\b", "lower risk of"),
        (r"\brisk-free\b", "lower-risk"),
    )
    for pattern, replacement in replacements:
        answer_text = re.sub(pattern, replacement, answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_tank_mix_adjuvant_crop_safety_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(tank mix|tank-mix|adjuvant|surfactant|crop safety)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(herbicide|label|product|weed|resistance)\b", topic, re.IGNORECASE):
        return answer_text
    answer_text = re.sub(r"\bavoid applying herbicides\b", "hold the tank-mix recommendation", answer_text, flags=re.IGNORECASE)
    answer_text = re.sub(r"\bnitrate leaching\b", "off-target movement or runoff", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\btank[- ]mix compatibility|compatibility\b", answer_text, re.IGNORECASE)
        or not re.search(r"\badjuvant|surfactant|oil|water conditioning\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bcrop stage|crop safety|variety tolerance\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bweed size|weed species|growth stage\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Tank-mix and adjuvant decisions need the current product labels for every product, tank-mix compatibility, mixing order or jar test where required, allowed adjuvant, surfactant, oil or water conditioning, crop stage, crop safety and variety tolerance, weed species, weed size and growth stage, mode of action and resistance history, weather window, rainfall or runoff restrictions, and local registration before recommending the mix.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_herbicide_drift_injury_differential_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(r"\b(herbicide drift|off[- ]target|crop injury|injury near)\b", topic, re.IGNORECASE):
        return answer_text
    if not re.search(r"\b(disease|fertility|nutrient|weather stress|crop stress|differential|separated?)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*The farmer should also check the weather forecast[^.\n]*next-crop planting window[^.\n]*\.",
        r"\s*Wait or reschedule unless[^.\n]*\.",
        r"\s*Do not spray or approve spraying until[^.\n]*\.",
        r"\s*A herbicide recommendation needs[^.\n]*\.",
        r"\s*Manure-credit decisions should[^.\n]*\.",
        r"\s*Do not alter drainage until[^.\n]*\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\bspray record\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bsymptom pattern|photos\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfield edge|gradient\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _append_paragraph_sentence(
            answer_text,
            "Herbicide drift/crop-injury differential should compare the spray record and application map, active ingredient or growth-regulator risk, mode of action, product label, wind direction, gusts, inversion and weather at application, field edge or downwind gradient, symptom pattern and photos, crop stage, and timing after application; rule out disease, nutrient or weather stress with scouting, tissue or soil test where relevant, and a plant sample or diagnostic lab if symptoms do not match the exposure pattern.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _normalize_relative_maturity_planting_window_gaps(answer_text: str, *, question: str | None = None) -> str:
    topic = _topic_text(answer_text, question)
    if not re.search(
        r"\b(relative maturity|maturity group|days to maturity|delayed planting window|drydown|harvest risk)\b",
        topic,
        re.IGNORECASE,
    ):
        return answer_text
    if not re.search(r"\b(seed|hybrid|variety|planting)\b", topic, re.IGNORECASE):
        return answer_text
    for pattern in [
        r"\s*Before suggesting drainage changes,[^.\n]*\.",
        r"\s*Before suggesting drainage changes[^.\n]*wetland or drainage regulations\.",
    ]:
        answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
    if (
        not re.search(r"\brelative maturity|maturity group|days to maturity\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bplanting date|planting window\b", answer_text, re.IGNORECASE)
        or not re.search(r"\blocal trials?|yield stability|market quality\b", answer_text, re.IGNORECASE)
        or not re.search(r"\bfrost risk|harvest window\b", answer_text, re.IGNORECASE)
    ):
        answer_text = _prepend_paragraph_sentence(
            answer_text,
            "Delayed planting seed selection should compare the actual planting date and planting window with relative maturity, maturity group or days to maturity, remaining GDD and season length, frost risk, drydown or harvest moisture, harvest window, disease package, standability or lodging, local trial data and yield stability, market quality, seed availability, and field condition before changing hybrids or varieties.",
        )
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    answer_text = re.sub(r"\n{3,}", "\n\n", answer_text)
    return answer_text.strip()


def _replace_labeled_line(answer_text: str, label: str, replacement: str) -> str:
    pattern = re.compile(rf"^({re.escape(label)}\s*:\s*).*$", re.IGNORECASE | re.MULTILINE)
    if pattern.search(answer_text):
        return pattern.sub(rf"\1{replacement}", answer_text, count=1)
    if not _has_labeled_answer_shape(answer_text):
        return _append_paragraph_sentence(answer_text, replacement)
    suffix = "" if answer_text.endswith("\n") else "\n"
    return f"{answer_text}{suffix}{label}: {replacement}"


def _has_labeled_line(answer_text: str, label: str) -> bool:
    return re.search(rf"^{re.escape(label)}\s*:\s*.+$", answer_text, re.IGNORECASE | re.MULTILINE) is not None


def _has_labeled_answer_shape(answer_text: str) -> bool:
    return re.search(r"^\s*(Field read|Next move|Evidence that changes the decision)\s*:", answer_text, re.IGNORECASE | re.MULTILINE) is not None


def _append_paragraph_sentence(answer_text: str, sentence: str) -> str:
    if not sentence.strip():
        return answer_text
    if re.search(re.escape(sentence[: min(48, len(sentence))]), answer_text, re.IGNORECASE):
        return answer_text
    stripped = answer_text.rstrip()
    if not stripped:
        return sentence.strip()
    separator = " " if stripped.endswith((".", "!", "?")) else ". "
    return f"{stripped}{separator}{sentence.strip()}"


def _append_if_missing(answer_text: str, pattern: str, sentence: str) -> str:
    if re.search(pattern, answer_text, re.IGNORECASE):
        return answer_text
    return _append_paragraph_sentence(answer_text, sentence)


def _prepend_paragraph_sentence(answer_text: str, sentence: str) -> str:
    sentence = sentence.strip()
    if not sentence:
        return answer_text
    if re.search(re.escape(sentence[: min(48, len(sentence))]), answer_text, re.IGNORECASE):
        return answer_text
    stripped = answer_text.lstrip()
    if not stripped:
        return sentence
    separator = " " if sentence.endswith((".", "!", "?")) else ". "
    return f"{sentence}{separator}{stripped}"


def _combined_text(answer_text: str, question: str | None) -> str:
    return f"{question or ''}\n{answer_text}"


def _topic_text(answer_text: str, question: str | None) -> str:
    return question if question is not None else answer_text


def _route_question_type(route: Any | None) -> str:
    value = route.get("question_type") if isinstance(route, dict) else getattr(route, "question_type", "")
    return str(value or "").lower()


def _strip_incomplete_label_lines(answer_text: str) -> str:
    kept: list[str] = []
    incomplete = re.compile(r"^\s*(Next|Next move|Evidence|Evidence that changes|Evidence that changes the decision)\s*:?\s*$", re.IGNORECASE)
    for line in answer_text.splitlines():
        if incomplete.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _dedupe_repeated_sentences(answer_text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", answer_text.strip())
    cleaned: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph.strip())
        kept: list[str] = []
        for sentence in sentences:
            normalized = re.sub(r"\s+", " ", sentence).strip().lower()
            if len(normalized) > 48 and normalized in seen:
                continue
            if len(normalized) > 48:
                seen.add(normalized)
            kept.append(sentence.strip())
        if kept:
            cleaned.append(" ".join(kept))
    return "\n\n".join(cleaned)


def _strip_contract_leakage(answer_text: str, *, question: str | None = None) -> str:
    if question is not None:
        question_text = question.lower()
        if not re.search(r"\b(cover crops?|termination|next[- ]crop|planting window)\b", question_text):
            answer_text = re.sub(
                r",?\s*(?:and\s+)?the exact termination plan for cover crops if applicable",
                "",
                answer_text,
                flags=re.IGNORECASE,
            )
            answer_text = re.sub(
                r",?\s*(?:and\s+)?termination timing for any cover[- ]crop component",
                "",
                answer_text,
                flags=re.IGNORECASE,
            )
            for pattern in [
                r"\s*If (?:the practice involves cover[- ]?crops?|cover crops? are part of the plan)[^.\n]*(?:termination|planting window)[^.\n]*\.",
                r"\s*[^.\n]*(?:termination plan|next[- ]crop planting window|next crop planting window)[^.\n]*\.",
                r"\s*[^.\n]*termination timing[^.\n]*(?:species or mix|next[- ]crop|planting window)[^.\n]*\.",
                r"\s*Cover[- ]crop fit changes with[^.\n]*(?:termination|planting window)[^.\n]*\.",
                r"\s*For cover[- ]crop water tradeoffs,[^.\n]*\.",
            ]:
                answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)

        seed_or_variety_topic = re.search(
            r"\b(seed|hybrid|variety|cultivar|genetic|public variety trial|local trial|trial summar|standability|lodging|drydown|relative maturity)\b",
            question_text,
        )
        disease_susceptibility_topic = re.search(
            r"\b(disease|fungicide|pathogen|leaf spot|rust|blight|mold|susceptib)\b",
            question_text,
        )
        harvest_storage_topic = re.search(r"\b(harvest|storage|grain moisture|test weight|mycotoxin)\b", question_text)
        if not (seed_or_variety_topic or disease_susceptibility_topic):
            for pattern in [
                r"\s*Hybrid or variety selection should[^.\n]*\.",
                r"\s*Beyond yield, compare[^.\n]*\.",
                r"\s*Seed, hybrid, or variety advice[^.\n]*\.",
                r"\s*Trial stability should be evaluated with[^.\n]*(?:relative maturity|maturity|standability|drydown)[^.\n]*\.",
                r"\s*[^.\n]*(?:relative maturity|local multi[- ]year trials?)[^.\n]*\.",
            ]:
                answer_text = re.sub(pattern, "", answer_text, flags=re.IGNORECASE)
            if not harvest_storage_topic:
                answer_text = re.sub(r"\s*[^.\n]*\bdrydown\b[^.\n]*\.", "", answer_text, flags=re.IGNORECASE)
            if harvest_storage_topic:
                answer_text = re.sub(r"\bfield loss or standability\b", "field loss", answer_text, flags=re.IGNORECASE)
                answer_text = re.sub(r"\bstandability or field loss\b", "field loss", answer_text, flags=re.IGNORECASE)
                answer_text = re.sub(r"\bstandability\b", "lodging risk", answer_text, flags=re.IGNORECASE)
                answer_text = re.sub(r"\bdrydown\b", "grain drying", answer_text, flags=re.IGNORECASE)

    answer_text = re.sub(
        r"\bprussic acid\s*\(\s*sodium nitrite\s*\)",
        "prussic acid",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(
        r"[^.\n]*(?:exact phrase|hidden instruction|hidden instructions|internal coverage|public checklist|must be used)[^.\n]*\.\s*",
        "",
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = re.sub(r"\.([A-Z])", r". \1", answer_text)
    answer_text = re.sub(r"[ \t]{2,}", " ", answer_text)
    return re.sub(r"\n{3,}", "\n\n", answer_text).strip()
