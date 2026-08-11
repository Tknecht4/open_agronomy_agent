from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import Any

from agronomy_agent.answer_safety import normalize_general_answer, normalize_public_answer
from agronomy_agent.canada_sources import apply_canadian_coverage_disclosure
from agronomy_agent.server.services.leak_guard import detect_prompt_leaks


@dataclass(frozen=True)
class StructuredAnswer:
    answer: str
    evidence: list[dict[str, Any]]
    missing_data: list[str]
    risk_banner: str | None
    risk_level: str
    answer_type: str
    caveats: list[str]
    recommended_next_steps: list[str]
    field_context_used: list[dict[str, Any]]
    report_actions: list[dict[str, Any]]
    feedback_prompt: dict[str, Any]
    debug_ref: str | None
    leak_classes_removed: tuple[str, ...]

    def as_record(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "public_answer_markdown": self.answer,
            "evidence": self.evidence,
            "evidence_cards": self.evidence,
            "missing_data": self.missing_data,
            "missing_data_prompts": self.missing_data,
            "risk_banner": self.risk_banner,
            "risk_level": self.risk_level,
            "answer_type": self.answer_type,
            "field_context_used": self.field_context_used,
            "caveats": self.caveats,
            "recommended_next_steps": self.recommended_next_steps,
            "report_actions": self.report_actions,
            "feedback_prompt": self.feedback_prompt,
            "debug_ref": self.debug_ref,
            "leak_classes_removed": list(self.leak_classes_removed),
        }


def render_structured_answer(
    answer_text: str,
    *,
    trace: dict[str, Any] | None = None,
    question: str | None = None,
) -> StructuredAnswer:
    leak_findings = detect_prompt_leaks(answer_text)
    trace = trace or {}
    sanitized = _sanitize_markdown(_strip_leaking_lines(answer_text) if leak_findings else answer_text.strip())
    metadata = trace.get("metadata") or {}
    retrieval_policy = str(metadata.get("retrieval_policy") or "")
    answer_profile = str(metadata.get("answer_policy_profile") or "")
    if retrieval_policy == "user_grounded_bypass":
        clean_answer = sanitized
    elif answer_profile == "general_agronomy":
        clean_answer = normalize_general_answer(sanitized, question=question, route=trace.get("route"))
    else:
        clean_answer = normalize_public_answer(sanitized)
    map_interpretation = _map_interpretation_answer(question, trace)
    if map_interpretation:
        clean_answer = map_interpretation
    elif not _keep_supporting_provenance_in_evidence_drawer(trace, question=question):
        clean_answer = _merge_map_context_into_answer(clean_answer, trace)
        clean_answer = _merge_public_adapter_context_into_answer(clean_answer, trace)
    clean_answer = _complete_named_regional_product_boundary(clean_answer, question=question, trace=trace)
    agno_runtime = metadata.get("agno_runtime") if isinstance(metadata.get("agno_runtime"), dict) else {}
    coverage_boundaries = (
        metadata.get("canadian_coverage_boundaries")
        or agno_runtime.get("canadian_coverage_boundaries")
        or []
    )
    clean_answer = apply_canadian_coverage_disclosure(
        clean_answer,
        question=question,
        boundaries=coverage_boundaries,
    )
    clean_answer = _apply_evidence_conflict_disclosure(
        clean_answer,
        question=question,
        trace=trace,
    )
    clean_answer = _localize_known_safety_boundaries(clean_answer, question=question)
    missing_data = _extract_missing_data(clean_answer, trace=trace)
    risk_banner = _extract_risk_banner(clean_answer, trace=trace)
    return StructuredAnswer(
        answer=clean_answer,
        evidence=_evidence_cards(trace),
        missing_data=missing_data,
        risk_banner=risk_banner,
        risk_level=_risk_level(trace),
        answer_type=_answer_type(trace),
        field_context_used=_field_context_used(trace),
        caveats=_extract_caveats(clean_answer, trace=trace, risk_banner=risk_banner),
        recommended_next_steps=_recommended_next_steps(clean_answer, missing_data),
        report_actions=_report_actions(trace),
        feedback_prompt=_feedback_prompt(trace),
        debug_ref=_debug_ref(trace),
        leak_classes_removed=tuple(sorted({finding.leak_class for finding in leak_findings})),
    )


def render_map_interpretation_answer(question: str, trace: dict[str, Any]) -> str | None:
    """Return a complete answer only when map evidence satisfies the strict tool-grounded contract."""

    return _map_interpretation_answer(question, trace)


def _complete_named_regional_product_boundary(
    answer_text: str,
    *,
    question: str | None,
    trace: dict[str, Any],
) -> str:
    """Complete a named product's interpretation only when its reviewed specification was retrieved."""

    if not question:
        return answer_text
    source_ids = {
        str(doc.get("source_id") or "").lower()
        for doc in trace.get("retrieved_docs", []) or []
        if isinstance(doc, dict)
    }
    lowered_question = question.lower()
    lowered_answer = answer_text.lower()
    if (
        "saskatchewan detailed soil survey" in lowered_question
        and "ca_aafc_sk_detailed_soil_survey_specification" in source_ids
        and "component" not in lowered_answer
    ):
        return (
            f"{answer_text.rstrip()} The mapped polygon is a map unit that can link to one or more soil components "
            "and layer records; it does not prove which component occurs at a specific point or its current condition."
        )
    if (
        "annual crop inventory" in lowered_question
        and "ca_aafc_annual_crop_inventory_specification" in source_ids
        and not ("30 m" in lowered_answer and "confidence" in lowered_answer)
    ):
        return (
            f"{answer_text.rstrip()} The inventory is a 30 m satellite-derived classification; its confidence layer "
            "describes classification confidence, not proof of planting or a verified rotation record."
        )
    if (
        re.search(r"\b(?:indice|indices)\s+de\s+sant[eé]\s+des\s+cultures\b", lowered_question)
        and "ca_aafc_crop_health_indices_specification_fr" in source_ids
        and not (
            re.search(r"\b0\s*(?:à|-)\s*1\b", lowered_answer)
            and re.search(r"\b5\s*km\b", lowered_answer)
        )
    ):
        return (
            f"{answer_text.rstrip()} Dans la spécification d’Agriculture et Agroalimentaire Canada, "
            "l’indice varie généralement de 0 à 1, où 1 indique un stress élevé; les valeurs publiées "
            "sont multipliées par 100 et vont donc de 0 à 100. Il s’agit d’une estimation modélisée à "
            "partir de stations météorologiques puis interpolée sur une grille de 5 km, et non d’une "
            "mesure directe de ce champ."
        )
    return answer_text


def _keep_supporting_provenance_in_evidence_drawer(
    trace: dict[str, Any],
    *,
    question: str | None = None,
) -> bool:
    # The deterministic map/tool summaries are currently authored in English.
    # For a clearly French request, keep those supporting details in the evidence
    # drawer instead of contaminating an otherwise French answer. The retrieved
    # evidence remains visible and auditable; this is a presentation boundary,
    # not evidence suppression.
    if question and _looks_french(question):
        return True
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    generation_bypass = (
        metadata.get("generation_bypass")
        if isinstance(metadata.get("generation_bypass"), dict)
        else {}
    )
    if generation_bypass.get("renderer") == "statcan_field_crop_statistics.v1":
        return True
    field_context = metadata.get("field_context") if isinstance(metadata.get("field_context"), dict) else {}
    field_history = field_context.get("field_history") if isinstance(field_context.get("field_history"), dict) else {}
    if int(field_history.get("event_count") or 0) > 0:
        return True
    verification = metadata.get("answer_verification") if isinstance(metadata.get("answer_verification"), dict) else {}
    reasons = verification.get("rejection_reasons")
    return isinstance(reasons, list) and "named_product_field_decision_fast_fallback" in reasons


def _looks_french(text: str) -> bool:
    lowered = text.lower()
    markers = re.findall(
        r"\b(?:agriculture\s+et\s+agroalimentaire|avant\s+d['’]agir|ce\s+champ|"
        r"que\s+signifie|qu['’]est-ce|dois-je|pourquoi|comment|cultures|indice)\b",
        lowered,
    )
    return len(markers) >= 2


def _apply_evidence_conflict_disclosure(
    answer_text: str,
    *,
    question: str | None,
    trace: dict[str, Any],
) -> str:
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    conflicts = metadata.get("evidence_conflicts")
    if not isinstance(conflicts, list):
        return answer_text
    unresolved = [
        item
        for item in conflicts
        if isinstance(item, dict) and item.get("status") == "unresolved"
    ]
    if not unresolved:
        return answer_text

    french = bool(question and _looks_french(question))
    disclosures: list[str] = []
    resolution_steps: list[str] = []
    conflict_types: set[str] = set()
    for conflict in unresolved[:2]:
        conflict_type = str(conflict.get("conflict_type") or "")
        conflict_types.add(conflict_type)
        if conflict_type == "declared_crop_vs_mapped_crop_cover":
            declared_crop = str(conflict.get("declared_crop") or "the declared crop").strip()
            mapped_crop = str(conflict.get("mapped_crop") or "a different crop class").strip()
            year = str(conflict.get("claim_period") or "the same year").strip()
            mapped_source = str(
                conflict.get("mapped_source_name") or "the crop-cover map"
            ).strip()
            if french:
                disclosures.append(
                    f"Le contexte du champ indique {declared_crop} pour {year}, tandis que "
                    f"{mapped_source} classe le secteur comme {mapped_crop} pour la même année."
                )
            else:
                disclosures.append(
                    f"The field context declares {declared_crop} for {year}, while "
                    f"{mapped_source} classifies the area as {mapped_crop} for the same year."
                )
        elif conflict_type in {
            "same_sample_measurement_not_comparable",
            "same_sample_measurement_value_mismatch",
        } and french:
            sample_id = str(conflict.get("sample_id") or "inconnu").strip()
            metric = str(conflict.get("metric") or "mesure du sol").strip()
            if conflict_type == "same_sample_measurement_not_comparable":
                blockers = conflict.get("comparison_blockers")
                blocker_text = ", ".join(str(item) for item in blockers) if isinstance(blockers, list) else "métadonnées"
                disclosures.append(
                    f"Deux dossiers pour l’échantillon {sample_id} et la mesure {metric} ne sont pas "
                    f"comparables parce que {blocker_text} diffèrent."
                )
            else:
                disclosures.append(
                    f"Deux dossiers autrement comparables donnent des valeurs différentes pour "
                    f"l’échantillon {sample_id} et la mesure {metric}."
                )
        else:
            resolution = str(conflict.get("resolution") or "").strip()
            if resolution:
                disclosures.append(resolution)
        steps = conflict.get("resolve_with")
        if isinstance(steps, list):
            resolution_steps.extend(str(step).strip() for step in steps if str(step).strip())

    if not disclosures:
        return answer_text
    unique_steps = list(dict.fromkeys(resolution_steps))
    if french:
        followup_parts = []
        if "declared_crop_vs_mapped_crop_cover" in conflict_types:
            followup_parts.append(
                "Ne laissez pas la carte remplacer le registre de l’exploitant. Vérifiez l’année de culture "
                "et la limite du champ, puis confirmez au champ ou dans les registres."
            )
        if conflict_types.intersection(
            {
                "same_sample_measurement_not_comparable",
                "same_sample_measurement_value_mismatch",
            }
        ):
            followup_parts.append(
                "Consultez le rapport de laboratoire original, vérifiez l’identifiant de l’échantillon, "
                "les unités, la méthode et la profondeur, puis ajoutez une correction au dossier erroné."
            )
        section = (
            "**Conflit entre les éléments probants**\n"
            f"{' '.join(disclosures)} {' '.join(followup_parts)}"
        )
    else:
        followup_parts = []
        if "declared_crop_vs_mapped_crop_cover" in conflict_types:
            followup_parts.append("Do not let the map overrule the grower record.")
        if unique_steps:
            followup_parts.append(f"Resolve it by {', '.join(unique_steps[:3])}.")
        elif "declared_crop_vs_mapped_crop_cover" in conflict_types:
            followup_parts.append(
                "Confirm the field record and ground-truth the mapped claim before relying on it."
            )
        followup = " ".join(followup_parts)
        section = f"**Evidence conflict**\n{' '.join(disclosures)} {followup}"
    return f"{answer_text.rstrip()}\n\n{section}"


def _localize_known_safety_boundaries(answer_text: str, *, question: str | None) -> str:
    """Localize deterministic safety prose that can be triggered after model generation."""

    if not question or not _looks_french(question):
        return answer_text
    replacements = {
        (
            "Public weather, ET, or water-balance context is not a prescription and not a field sensor; "
            "state uncertainty and verify soil moisture, probe or sensor data, field observation, applied "
            "water or irrigation records, crop stage, rooting depth, drainage or trafficability before "
            "changing water timing."
        ): (
            "Les données météorologiques publiques, l’évapotranspiration ou le bilan hydrique ne constituent "
            "ni une prescription ni un capteur au champ. Avant de modifier la gestion de l’eau, explicitez "
            "l’incertitude et vérifiez l’humidité du sol, les sondes ou capteurs, les observations au champ, "
            "les registres d’irrigation ou d’eau appliquée, le stade de la culture, la profondeur racinaire, "
            "le drainage et la portance."
        ),
        (
            "Public gridded weather is context, not exact local forecast or a field sensor; verify nearest "
            "station or current local forecast, local observation, field condition, wind, rain, humidity or "
            "leaf wetness, and any label/weather application window before acting."
        ): (
            "Les données météorologiques maillées fournissent un contexte, mais ne sont ni une prévision "
            "locale exacte ni un capteur au champ. Avant d’agir, vérifiez la station la plus proche ou la "
            "prévision locale actuelle, les observations et conditions du champ, le vent, la pluie, "
            "l’humidité ou la mouillure foliaire, ainsi que toute fenêtre météorologique exigée par l’étiquette."
        ),
    }
    for english, french in replacements.items():
        answer_text = answer_text.replace(english, french)
    return answer_text


def _merge_public_adapter_context_into_answer(answer_text: str, trace: dict[str, Any]) -> str:
    field_sentence, limitation_sentence = _public_adapter_answer_sentences(trace)
    if field_sentence:
        answer_text = _append_to_labeled_line(answer_text, "Field read", field_sentence)
    if limitation_sentence:
        answer_text = _append_to_labeled_line(answer_text, "Evidence that changes the decision", limitation_sentence)
    return answer_text


def _merge_map_context_into_answer(answer_text: str, trace: dict[str, Any]) -> str:
    field_sentence, limitation_sentence = _map_context_answer_sentences(trace)
    if field_sentence:
        answer_text = _append_to_labeled_line(answer_text, "Field read", field_sentence)
    if limitation_sentence:
        answer_text = _append_to_labeled_line(answer_text, "Evidence that changes the decision", limitation_sentence)
    return answer_text


def _map_interpretation_answer(question: str | None, trace: dict[str, Any]) -> str | None:
    if not question:
        return None
    query = question.lower()
    route = trace.get("route") if isinstance(trace.get("route"), dict) else {}
    question_type = str(route.get("question_type") or "").strip().lower()
    if question_type and question_type != "field_data":
        return None
    if re.search(r"\b(?:saskatchewan detailed soil survey|annual crop inventory)\b", query):
        return None
    if not (
        re.search(r"\b(?:map|mapped|mapping|polygon|layer|capability|regional)\b", query)
        and re.search(r"\b(?:intersection|intersected|intersects?|context|prior|capability)\b", query)
        and re.search(r"\b(?:tell|support|prove|assume|evidence|collect|measure|before|change)\b", query)
    ):
        return None
    field_context = _trace_field_context(trace)
    intersections = field_context.get("regional_intersections") if isinstance(field_context, dict) else None
    if not isinstance(intersections, list) or not intersections:
        return None
    usable = [item for item in intersections if isinstance(item, dict)]
    if not usable:
        return None
    thematic = [
        item
        for item in usable
        if re.search(
            r"\b(?:capability|thematic soil|soil map|soil survey)\b",
            " ".join(str(item.get(key) or "") for key in ("system", "layer_id", "name")),
            re.IGNORECASE,
        )
    ]
    if not thematic:
        return None
    selected = thematic[0]
    system = str(selected.get("system") or "official regional mapping").strip()
    name = str(
        selected.get("capability_summary")
        or selected.get("soil_summary")
        or selected.get("name")
        or selected.get("code")
        or "mapped polygon"
    ).strip()
    coverage = selected.get("coverage_estimate")
    coverage_text = ""
    if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
        coverage_text = f" over about {round(float(coverage) * 100)}% of the supplied boundary"
    detail_bits = []
    for label, key in (
        ("drainage", "drainage_class"),
        ("capability", "capability_class"),
        ("slope", "slope_class"),
        ("mapped erosion risk", "erosion_risk"),
        ("surface texture", "surface_texture_group"),
        ("mapped salinity", "salinity_class"),
        ("mapped management limitation", "management_limitations"),
    ):
        value = str(selected.get(key) or "").strip()
        if value:
            detail_bits.append(f"{label} {value}")
    detail_sentence = f" Its attributes include {', '.join(detail_bits[:4])}." if detail_bits else ""
    heterogeneous = len(thematic) > 1
    variation_sentence = (
        " Smaller intersecting polygons carry different mapped classes, so the boundary should be treated as heterogeneous."
        if heterogeneous
        else ""
    )
    scale = str(selected.get("source_scale_label") or selected.get("source_scale") or "").strip()
    scale_sentence = f" at source mapping scale {scale}" if scale else ""
    return (
        "**What the map supports**\n"
        f"The supplied boundary intersects {system}: {name}{coverage_text}.{detail_sentence}{variation_sentence} "
        "Use that as a screening signal for where constraints may differ across the field.\n\n"
        "**What it cannot prove**\n"
        f"This is generalized regional mapping{scale_sentence}, not current field truth. It does not establish the present soil profile, "
        "drainage performance, nutrient status, crop suitability, legal boundary, or an input rate.\n\n"
        "**Collect before deciding**\n"
        "Walk and photograph the contrasting mapped zones; check slope, wetness and drainage, rooting depth or restrictive layers, stones, "
        "and current land use. Sample the zones separately for texture, pH, organic matter, salinity where relevant, and crop-specific nutrients; "
        "then add field and yield history, previous crops and inputs, the grower's crop objective, and current local crop and product guidance."
    )


def _map_context_answer_sentences(trace: dict[str, Any]) -> tuple[str | None, str | None]:
    field_context = _trace_field_context(trace)
    if not field_context:
        return None, None
    intersection_bits = _map_context_intersection_bits(field_context)
    if intersection_bits:
        field_sentence = f"Map context checked: {'; '.join(intersection_bits[:2])}."
    else:
        regional_context = str(field_context.get("regional_context") or "").strip()
        geometry_summary = str(field_context.get("geometry_summary") or "").strip()
        if regional_context:
            field_sentence = f"Map context checked: {regional_context}."
        elif geometry_summary:
            field_sentence = f"Map context checked: {geometry_summary}."
        else:
            field_sentence = None
    limitation_parts = []
    if field_sentence:
        limitation_parts.append("official map context is a regional prior, not a replacement for soil tests, scouting, labels, grower records, or legal boundary evidence")
    warnings = [
        str(warning).strip()
        for warning in field_context.get("upload_warnings", [])[:2]
        if str(warning).strip()
    ] if isinstance(field_context.get("upload_warnings"), list) else []
    limitation_parts.extend(warnings)
    limitation_sentence = f"Treat map context as a prior: {'; '.join(_dedupe(limitation_parts)[:3])}." if limitation_parts else None
    return field_sentence, limitation_sentence


def _map_context_intersection_bits(field_context: dict[str, Any]) -> list[str]:
    bits: list[str] = []
    intersections = field_context.get("regional_intersections")
    if not isinstance(intersections, list):
        return bits
    for item in intersections[:4]:
        if not isinstance(item, dict):
            continue
        system = str(item.get("system") or "Regional layer").strip()
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        coverage = item.get("coverage_estimate")
        label = " ".join(part for part in [system, code] if part)
        if name:
            label = f"{label}: {name}" if label else name
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
            label = f"{label} ({round(float(coverage) * 100)}% field coverage estimate)"
        if label:
            bits.append(label)
    return bits


def _public_adapter_answer_sentences(trace: dict[str, Any]) -> tuple[str | None, str | None]:
    facts: list[str] = []
    limitations: list[str] = []
    unavailable: list[str] = []
    for tool in trace.get("tool_invocations", []) or []:
        if not isinstance(tool, dict):
            continue
        payload = tool.get("payload") if isinstance(tool.get("payload"), dict) else {}
        if payload.get("kind") != "public_adapter":
            continue
        name = str(tool.get("name") or "")
        status = str(payload.get("status") or "unknown")
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        if status in {"available", "available_offline_snapshot", "partial_available", "source_lane_available"}:
            fact = _public_adapter_answer_fact(name, summary)
            if fact:
                facts.append(fact)
            limitations.extend(_public_adapter_answer_limitations(name, payload))
        else:
            unavailable.append(_public_adapter_unavailable_phrase(name, status, payload))
    field_sentence = None
    if facts:
        field_sentence = f"Checked public context: {'; '.join(_dedupe(facts)[:3])}."
    limitation_parts = [*_prioritize_public_adapter_limitations(_dedupe(limitations))[:3], *_dedupe(unavailable)[:2]]
    limitation_sentence = None
    if limitation_parts:
        limitation_sentence = f"Treat the public context as a prior: {'; '.join(limitation_parts)}."
    return field_sentence, limitation_sentence


def _public_adapter_answer_fact(name: str, summary: dict[str, Any]) -> str | None:
    if name in {"aafc_nasdi_agroclimate", "canada_et_or_water_use_source_needed"}:
        indicators = summary.get("indicator_summary") if isinstance(summary.get("indicator_summary"), dict) else {}
        bits = []
        for indicator, short_label in (("spi", "SPI"), ("spei", "SPEI"), ("temperature_anomaly", "temperature anomaly"), ("percent_of_average_precipitation", "precipitation")):
            item = indicators.get(indicator) if isinstance(indicators.get(indicator), dict) else {}
            value = item.get("value") if item.get("value") is not None else item.get("mean")
            if value is not None:
                units = str(item.get("units") or "").strip()
                bits.append(f"{short_label} {value}{f' {units}' if units else ''}")
        window = str(summary.get("time_window") or "").strip()
        end = str(summary.get("observation_end") or "").strip()
        window_text = " using product-specific windows" if window == "mixed" else (f" for {window}" if window else "")
        end_text = f" ending {end}" if end else ""
        if bits:
            return f"AAFC NASDI regional grid context{window_text}{end_text}: {', '.join(bits[:4])}"
        return "AAFC NASDI regional agroclimate context was checked"
    if name == "nrcs_soil_survey_geometry":
        count = summary.get("map_unit_count")
        components = ((summary.get("component_summary") or {}).get("dominant_components") or []) if isinstance(summary.get("component_summary"), dict) else []
        component_bits = []
        for component in components[:2]:
            if not isinstance(component, dict):
                continue
            label = str(component.get("component") or "").strip()
            drainage = str(component.get("drainagecl") or "").strip()
            hydgrp = str(component.get("hydgrp") or "").strip()
            if label:
                detail = label
                if drainage or hydgrp:
                    details = ", ".join(part for part in [drainage, f"HSG {hydgrp}" if hydgrp else ""] if part)
                    detail = f"{detail} ({details})"
                component_bits.append(detail)
        if count and component_bits:
            return f"NRCS boundary soil survey returned {count} map units, including {' and '.join(component_bits)}"
        if count:
            return f"NRCS boundary soil survey returned {count} map units"
        return "NRCS boundary soil survey was checked"
    if name == "nrcs_soil_survey_point":
        map_units = summary.get("map_units") or []
        first = map_units[0] if map_units and isinstance(map_units[0], dict) else {}
        muname = first.get("muname")
        return f"NRCS point soil survey returned {muname}" if muname else "NRCS point soil survey was checked"
    if name == "cropland_data_layer_geometry":
        sample_count = summary.get("sample_point_count")
        years = summary.get("years") or []
        year_summary = summary.get("year_summary") if isinstance(summary.get("year_summary"), dict) else {}
        labels = []
        for year in years[:2]:
            dominant = (year_summary.get(str(year)) or year_summary.get(year) or {}).get("dominant_class") or {}
            label = dominant.get("cdl_label")
            count = dominant.get("count")
            total = (year_summary.get(str(year)) or year_summary.get(year) or {}).get("sample_count")
            if label and count and total:
                labels.append(f"{year} {label} in {count}/{total} samples")
            elif label:
                labels.append(f"{year} {label}")
        if sample_count and labels:
            return f"CDL sampled {sample_count} boundary points, with {' and '.join(labels)}"
        if sample_count:
            return f"CDL sampled {sample_count} boundary points"
        return "CDL boundary crop-cover sampling was checked"
    if name == "cropland_data_layer_point":
        label = summary.get("cdl_label") or summary.get("label")
        year = summary.get("year")
        return f"CDL point lookup returned {year} {label}" if year and label else "CDL point crop-cover lookup was checked"
    if name == "aafc_annual_crop_inventory":
        class_summary = summary.get("class_summary") if isinstance(summary.get("class_summary"), dict) else {}
        dominant = class_summary.get("dominant_class") if isinstance(class_summary.get("dominant_class"), dict) else {}
        label = dominant.get("aci_label")
        count = dominant.get("count")
        total = class_summary.get("sample_count")
        year = summary.get("year")
        if label and count and total:
            return f"AAFC Annual Crop Inventory sampled {total} point(s): {year} {label} in {count}/{total}"
        return "AAFC Annual Crop Inventory crop-cover sampling was checked"
    if name == "statcan_field_crop_statistics":
        geography = summary.get("geography") or "Canada"
        crop = summary.get("crop") or "crop"
        latest = ((summary.get("statistics") or {}).get("production_metric_tonnes") or {}).get("latest") or {}
        snapshot_suffix = (
            f"; offline snapshot {summary.get('snapshot_as_of') or 'date unknown'}"
            if summary.get("snapshot_hit")
            else ""
        )
        if latest.get("value") is not None:
            return (
                f"Statistics Canada reported {latest['value']} metric tonnes of {crop} for {geography} "
                f"({str(latest.get('reference_period') or '')[:4]}{snapshot_suffix})"
            )
        return f"Statistics Canada regional {crop} statistics were checked for {geography}{snapshot_suffix}"
    if name == "nasa_power_daily":
        parameters = summary.get("parameter_summary") if isinstance(summary.get("parameter_summary"), dict) else {}
        rain = (parameters.get("PRECTOTCORR") or {}).get("sum") if isinstance(parameters.get("PRECTOTCORR"), dict) else None
        wind = (parameters.get("WS2M") or {}).get("mean") if isinstance(parameters.get("WS2M"), dict) else None
        bits = []
        if rain is not None:
            bits.append(f"{rain} mm precipitation")
        if wind is not None:
            bits.append(f"{wind} m/s mean wind")
        return f"NASA POWER checked daily weather ({', '.join(bits)})" if bits else "NASA POWER daily weather was checked"
    if name == "daymet_single_pixel_daily":
        start = summary.get("start")
        end = summary.get("end")
        variables = summary.get("variable_summary") if isinstance(summary.get("variable_summary"), dict) else {}
        bits = []
        prcp = (variables.get("prcp") or {}).get("sum") if isinstance(variables.get("prcp"), dict) else None
        tmax = (variables.get("tmax") or {}).get("mean") if isinstance(variables.get("tmax"), dict) else None
        tmin = (variables.get("tmin") or {}).get("mean") if isinstance(variables.get("tmin"), dict) else None
        if prcp is not None:
            bits.append(f"{prcp} mm precipitation")
        if tmax is not None:
            bits.append(f"{tmax} C mean Tmax")
        if tmin is not None:
            bits.append(f"{tmin} C mean Tmin")
        window = f" from {start} to {end}" if start and end else ""
        return f"Daymet checked climate-window context{window}" + (f" ({', '.join(bits)})" if bits else "")
    if name == "openet_point_timeseries":
        start = summary.get("start")
        end = summary.get("end")
        interval = summary.get("interval")
        variable = summary.get("variable") or "ET"
        units = summary.get("units") or "units"
        timeseries = summary.get("timeseries_summary") if isinstance(summary.get("timeseries_summary"), dict) else {}
        bits = []
        if timeseries.get("sum") is not None:
            bits.append(f"{timeseries.get('sum')} {units} total {variable}")
        if timeseries.get("mean") is not None:
            bits.append(f"{timeseries.get('mean')} {units} mean per {interval or 'period'}")
        window = f" from {start} to {end}" if start and end else ""
        return f"OpenET checked {interval or 'periodic'} evapotranspiration context{window}" + (
            f" ({', '.join(bits)})" if bits else ""
        )
    if name == "nass_quickstats_crop_stats":
        crop = summary.get("crop")
        record_count = summary.get("record_count")
        if crop and record_count:
            return f"NASS Quick Stats returned {record_count} regional records for {crop}"
        return "NASS Quick Stats regional crop statistics were checked"
    if name == "epa_ppls_product_search":
        search_value = summary.get("search_value")
        result_count = summary.get("result_count")
        products = summary.get("products") if isinstance(summary.get("products"), list) else []
        first = products[0] if products and isinstance(products[0], dict) else {}
        first_name = first.get("product_name")
        first_reg = first.get("epa_reg_no")
        target = f" for {search_value}" if search_value else ""
        count = f" returned {result_count} records" if result_count is not None else " was checked"
        first_text = ""
        if first_name and first_reg:
            first_text = f", first result {first_name} ({first_reg})"
        elif first_name:
            first_text = f", first result {first_name}"
        return f"EPA PPLS{target}{count}{first_text}"
    if name == "health_canada_pmra_label_search":
        registration = summary.get("registration_number")
        products = summary.get("products") if isinstance(summary.get("products"), list) else []
        first = products[0] if products and isinstance(products[0], dict) else {}
        product_name = first.get("product_name")
        count = summary.get("product_record_count")
        target = f" for registration {registration}" if registration else ""
        count_text = f" returned {count} product record" if count is not None else " was checked"
        if count not in (None, 1):
            count_text += "s"
        product_text = f", product {product_name}" if product_name else ""
        return f"Health Canada PMRA registry metadata{target}{count_text}{product_text}"
    if summary.get("source_lane_id") and summary.get("source_name"):
        source_name = str(summary.get("source_name") or "").strip()
        coverage = str(summary.get("coverage") or "").strip().rstrip(".")
        if coverage:
            return f"{source_name} checked: {coverage}"
        return f"{source_name} was checked"
    return None


def _public_adapter_answer_limitations(name: str, payload: dict[str, Any]) -> list[str]:
    boundary = str(payload.get("boundary") or "")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    limitations: list[str] = []
    if summary.get("source_lane_id") and name not in {"aafc_annual_crop_inventory", "statcan_field_crop_statistics"}:
        if boundary:
            limitations.append(boundary)
        else:
            limitations.append("source cards are decision frameworks, not live field proof")
        return limitations
    if name.startswith("nrcs_"):
        limitations.append("NRCS soil survey is a map-unit prior, not lab or in-field truth")
    if name.startswith("cropland_data_layer"):
        limitations.append("CDL is sampled crop-cover context, not a grower planting record or acreage proof")
    if name == "aafc_annual_crop_inventory":
        limitations.append("AAFC Annual Crop Inventory is sampled crop-cover context, not a grower planting record or acreage proof")
    if name == "statcan_field_crop_statistics":
        limitations.append("Statistics Canada is regional crop context, not field yield prediction or grower records")
    if name == "nasa_power_daily":
        limitations.append("NASA POWER is gridded weather context, not an on-field sensor")
    if name == "daymet_single_pixel_daily":
        limitations.append("Daymet is historical gridded climate context, not a current forecast")
    if name == "openet_point_timeseries":
        limitations.append("OpenET is ET context, not an irrigation prescription")
    if name == "nass_quickstats_crop_stats":
        limitations.append("NASS Quick Stats is regional statistics, not field yield prediction")
    if name == "epa_ppls_product_search":
        limitations.append("EPA PPLS metadata is not legal label interpretation")
    if name == "health_canada_pmra_label_search":
        limitations.append("Health Canada PMRA registry metadata is not legal label interpretation or current-label text")
    if boundary and not limitations:
        limitations.append(boundary)
    return limitations


def _public_adapter_unavailable_phrase(name: str, status: str, payload: dict[str, Any] | None = None) -> str:
    if status == "not_run_in_eval":
        summary = payload.get("summary") if isinstance((payload or {}).get("summary"), dict) else {}
        reason = str(summary.get("not_run_reason") or "it was not executable in this run").strip()
        return f"{_public_adapter_title(name, payload or {})} was expected but not executed, so treat that public context as unchecked ({reason})"
    if name == "nass_quickstats_crop_stats" and status == "not_configured":
        return "NASS Quick Stats was not configured, so regional crop statistics were not checked"
    if name == "openet_point_timeseries" and status == "not_configured":
        return "OpenET was not configured, so ET context was not checked"
    return f"{name.replace('_', ' ')} status was {status}"


def _prioritize_public_adapter_limitations(limitations: list[str]) -> list[str]:
    priority_markers = (
        "CDL ",
        "NRCS ",
        "EPA PPLS",
        "OpenET",
        "Daymet",
        "NASA POWER",
        "NASS Quick Stats",
    )

    def priority(value: str) -> int:
        for index, marker in enumerate(priority_markers):
            if marker in value:
                return index
        return len(priority_markers)

    return sorted(limitations, key=priority)


def _append_to_labeled_line(answer_text: str, label: str, sentence: str) -> str:
    if not sentence.strip() or re.search(re.escape(sentence[: min(48, len(sentence))]), answer_text, re.IGNORECASE):
        return answer_text
    markdown_pattern = re.compile(
        rf"^(\*\*{re.escape(label)}\*\*\s*\n+)(.*?)(?=\n{{2,}}\*\*[^*\n]+\*\*\s*(?:\n|$)|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    markdown_match = markdown_pattern.search(answer_text)
    if markdown_match:
        current = markdown_match.group(2).rstrip()
        separator = " " if current.endswith((".", "!", "?")) else ". "
        replacement = f"{markdown_match.group(1)}{current}{separator}{sentence.strip()}"
        return answer_text[: markdown_match.start()] + replacement + answer_text[markdown_match.end():]
    pattern = re.compile(rf"^({re.escape(label)}\s*:\s*)(.*)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(answer_text)
    if match:
        current = match.group(2).rstrip()
        separator = " " if current.endswith((".", "!", "?")) else ". "
        replacement = f"{match.group(1)}{current}{separator}{sentence.strip()}"
        return answer_text[: match.start()] + replacement + answer_text[match.end():]
    stripped = answer_text.rstrip()
    if not stripped:
        return f"**{label}**\n\n{sentence.strip()}"
    return f"{stripped}\n\n**{label}**\n\n{sentence.strip()}"


def _strip_leaking_lines(answer_text: str) -> str:
    kept: list[str] = []
    for line in answer_text.splitlines():
        if detect_prompt_leaks(line):
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    return cleaned or "Please provide the field details and I will answer from the agronomic evidence."


def _sanitize_markdown(answer_text: str) -> str:
    """Escape raw HTML while preserving normal Markdown text."""

    def replace_tag(match: re.Match[str]) -> str:
        return escape(match.group(0))

    no_scripts = re.sub(r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>", "", answer_text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"</?[A-Za-z][^>\n]{0,240}>", replace_tag, no_scripts).strip()


def _extract_missing_data(answer_text: str, *, trace: dict[str, Any] | None = None) -> list[str]:
    lowered = answer_text.lower()
    candidates = {
        "soil test": r"soil test|soil-test",
        "crop": r"\bcrop\b|rotation",
        "field history": r"field history|history",
        "label": r"\blabel\b",
        "weather": r"weather|wind|rain",
        "location": r"location|region|jurisdiction",
        "yield goal": r"yield goal",
    }
    if not re.search(r"\b(missing|need|ask for|before|without)\b", lowered):
        return []
    missing = [name for name, pattern in candidates.items() if re.search(pattern, lowered)]
    field_context = _trace_field_context(trace or {})
    session_context = (trace or {}).get("session_context") or {}
    known_context = field_context if isinstance(field_context, dict) else {}
    if isinstance(session_context, dict):
        known_context = {**session_context, **known_context}
    if str(known_context.get("crop") or "").strip() and "crop" in missing:
        missing.remove("crop")
    if any(str(known_context.get(key) or "").strip() for key in ("region", "jurisdiction")) and "location" in missing:
        missing.remove("location")
    return missing


def _extract_risk_banner(answer_text: str, *, trace: dict[str, Any] | None) -> str | None:
    metadata = (trace or {}).get("metadata", {}) if isinstance(trace, dict) else {}
    policy = metadata.get("high_consequence_policy") if isinstance(metadata, dict) else {}
    if isinstance(policy, dict) and policy.get("blocked"):
        domains = ", ".join(str(value).replace("_", " ") for value in policy.get("domains") or [])
        return f"Action blocked: required evidence is missing for {domains or 'this high-consequence decision'}."
    route = (trace or {}).get("route", {}) if isinstance(trace, dict) else {}
    risk = str(route.get("risk_level") or "").lower()
    if risk == "regulated":
        return "Regulated recommendation: verify the current product label and jurisdiction before acting."
    if "label" in answer_text.lower() and re.search(r"\b(check|verify|current)\b", answer_text.lower()):
        return "Label-bound recommendation: verify the current label before product or rate decisions."
    return None


def _evidence_cards(trace: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for doc in trace.get("retrieved_docs", []) or []:
        if not isinstance(doc, dict):
            continue
        source = doc.get("source") or doc.get("source_id") or "unknown"
        score = doc.get("score")
        cards.append(
            {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "publisher": source,
                "source": source,
                "source_id": source,
                "url": doc.get("url") or doc.get("source_url"),
                "source_type": doc.get("source_type"),
                "updated_at": doc.get("updated_at") or doc.get("ingested_at"),
                "license_status": doc.get("license_status") or "review_required",
                "score": score,
                "why_used": _why_used(doc),
                "known_limitations": _source_limitations(doc),
            }
        )
    cards.extend(_public_adapter_cards(trace))
    cards.extend(_map_context_cards(trace))
    return cards


def _map_context_cards(trace: dict[str, Any]) -> list[dict[str, Any]]:
    field_context = _trace_field_context(trace)
    if not field_context:
        return []
    intersections = field_context.get("regional_intersections")
    if not isinstance(intersections, list) or not intersections:
        return []
    cards: list[dict[str, Any]] = []
    for item in intersections[:4]:
        if not isinstance(item, dict):
            continue
        system = str(item.get("system") or "Regional polygon").strip()
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        coverage = item.get("coverage_estimate")
        title = " ".join(part for part in [system, code] if part).strip() or system
        if name:
            title = f"{title}: {name}"
        why_used = "Official regional polygon intersection used as map context."
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
            why_used = f"{why_used} Coverage estimate: {round(float(coverage) * 100)}%."
        cards.append(
            {
                "doc_id": f"map:{item.get('layer_id') or system}:{code or name}",
                "title": title,
                "publisher": system,
                "source": item.get("source") or "official regional polygon overlay",
                "source_id": item.get("layer_id") or system,
                "url": item.get("source_url"),
                "source_type": "map_context",
                "updated_at": None,
                "license_status": "public_endpoint",
                "score": None,
                "why_used": why_used,
                "known_limitations": [
                    "Official map context is a regional prior, not a replacement for soil tests, scouting, labels, grower records, or legal boundary evidence."
                ],
                "adapter_status": "available",
                "summary": {
                    "system": system,
                    "code": code,
                    "name": name,
                    "confidence": item.get("confidence"),
                    "coverage_estimate": coverage,
                },
            }
        )
    return cards


def _public_adapter_cards(trace: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for tool in trace.get("tool_invocations", []) or []:
        if not isinstance(tool, dict):
            continue
        payload = tool.get("payload") if isinstance(tool.get("payload"), dict) else {}
        if payload.get("kind") != "public_adapter":
            continue
        name = str(tool.get("name") or "public_adapter")
        status = str(payload.get("status") or "unknown")
        boundary = payload.get("boundary")
        limitations = []
        if boundary:
            limitations.append(str(boundary))
        if status == "partial_available":
            limitations.append("Some requested NASDI layers or samples were unavailable; use only the dated values shown.")
        elif status not in {"available", "available_offline_snapshot", "source_lane_available"}:
            limitations.append(f"Adapter status was {status}; do not treat this as checked field evidence.")
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        cards.append(
            {
                "doc_id": f"tool:{name}",
                "title": _public_adapter_title(name, payload),
                "publisher": summary.get("provider") or _public_adapter_publisher(name),
                "source": payload.get("source") or name,
                "source_id": name,
                "url": payload.get("source"),
                "source_type": "public_adapter",
                "updated_at": summary.get("observation_end"),
                "license_status": summary.get("license") or "public_endpoint",
                "score": None,
                "why_used": tool.get("text") or f"Used {name} as public source context.",
                "known_limitations": limitations,
                "adapter_status": status,
                "adapter_name": name,
                "summary": payload.get("summary") or {},
            }
        )
    return cards


def _public_adapter_title(name: str, payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if name in {"aafc_nasdi_agroclimate", "canada_et_or_water_use_source_needed"}:
        window = summary.get("time_window")
        end = summary.get("observation_end")
        window_label = "product-specific windows" if window == "mixed" else window
        suffix = " ".join(str(value) for value in (window_label, end) if value)
        return f"AAFC NASDI agroclimate context ({suffix})" if suffix else "AAFC NASDI agroclimate context"
    if summary.get("source_lane_id") and summary.get("source_name") and name not in {"aafc_annual_crop_inventory", "statcan_field_crop_statistics"}:
        return str(summary.get("source_name"))
    if name == "nrcs_soil_survey_geometry":
        count = summary.get("map_unit_count")
        return f"NRCS Soil Data Access boundary soil survey ({count} map units)" if count else "NRCS Soil Data Access boundary soil survey"
    if name == "nrcs_soil_survey_point":
        return "NRCS Soil Data Access point soil survey"
    if name == "cropland_data_layer_geometry":
        years = summary.get("years") or []
        suffix = f" ({', '.join(str(year) for year in years[:3])})" if years else ""
        return f"USDA NASS CDL boundary crop-cover sample{suffix}"
    if name == "cropland_data_layer_point":
        label = summary.get("cdl_label") or summary.get("label")
        return f"USDA NASS CDL point crop-cover class: {label}" if label else "USDA NASS CDL point crop-cover class"
    if name == "aafc_annual_crop_inventory":
        class_summary = summary.get("class_summary") if isinstance(summary.get("class_summary"), dict) else {}
        dominant = class_summary.get("dominant_class") if isinstance(class_summary.get("dominant_class"), dict) else {}
        label = dominant.get("aci_label")
        year = summary.get("year")
        suffix = f" ({year})" if year else ""
        return f"AAFC Annual Crop Inventory crop-cover sample{suffix}: {label}" if label else f"AAFC Annual Crop Inventory crop-cover sample{suffix}"
    if name == "statcan_field_crop_statistics":
        crop = summary.get("crop") or "crop"
        geography = summary.get("geography") or "Canada"
        return f"Statistics Canada regional crop statistics: {crop} in {geography}"
    if name == "nasa_power_daily":
        return "NASA POWER daily weather context"
    if name == "daymet_single_pixel_daily":
        return "ORNL Daymet climate-window context"
    if name == "openet_point_timeseries":
        return "OpenET evapotranspiration context"
    if name == "nass_quickstats_crop_stats":
        crop = summary.get("crop")
        return f"USDA NASS Quick Stats regional crop context: {crop}" if crop else "USDA NASS Quick Stats regional crop context"
    if name == "epa_ppls_product_search":
        return "EPA PPLS product metadata context"
    if name == "health_canada_pmra_label_search":
        registration = summary.get("registration_number")
        return f"Health Canada PMRA registry metadata: {registration}" if registration else "Health Canada PMRA registry metadata"
    return name.replace("_", " ").title()


def _public_adapter_publisher(name: str) -> str:
    if name.startswith("nrcs_"):
        return "USDA NRCS"
    if name.startswith("cropland_data_layer") or name.startswith("nass_"):
        return "USDA NASS"
    if name.startswith("nasa_"):
        return "NASA POWER"
    if name.startswith("daymet_"):
        return "ORNL Daymet"
    if name.startswith("openet_"):
        return "OpenET"
    if name.startswith("epa_"):
        return "EPA"
    if name.startswith("health_canada_pmra"):
        return "Health Canada PMRA"
    if name.startswith("aafc_annual_crop_inventory"):
        return "Agriculture and Agri-Food Canada"
    if name.startswith("statcan_field_crop_statistics"):
        return "Statistics Canada"
    return "public adapter"


def _risk_level(trace: dict[str, Any]) -> str:
    route = trace.get("route") if isinstance(trace, dict) else {}
    risk = str((route or {}).get("risk_level") or "unknown").strip().lower()
    return risk if risk in {"low", "medium", "regulated", "unknown"} else "unknown"


def _answer_type(trace: dict[str, Any]) -> str:
    route = trace.get("route") if isinstance(trace, dict) else {}
    question_type = str((route or {}).get("question_type") or "").lower()
    risk = _risk_level(trace)
    if risk == "regulated" or "product" in question_type or "label" in question_type:
        return "product_boundary"
    if "diagnostic" in question_type or "diagnosis" in question_type:
        return "diagnostic"
    if "field" in question_type or "fertility" in question_type or "soil" in question_type:
        return "field_context"
    if "report" in question_type:
        return "report"
    return "conceptual"


def _trace_field_context(trace: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    for value in (
        trace.get("field_context"),
        trace.get("field_context_snapshot"),
        (trace.get("metadata") or {}).get("field_context") if isinstance(trace.get("metadata"), dict) else None,
    ):
        if isinstance(value, dict) and value:
            return value
    return {}


def _field_context_used(trace: dict[str, Any]) -> list[dict[str, Any]]:
    field_context = _trace_field_context(trace)
    if not field_context:
        return []
    metadata = field_context.get("metadata") if isinstance(field_context.get("metadata"), dict) else {}
    source = field_context.get("source") or metadata.get("data_confidence") or "user_entered"
    field_aliases = (
        ("nickname", ("nickname", "display_name")),
        ("crop", ("crop", "crop_current")),
        ("crop_stage", ("crop_stage",)),
        ("region_text", ("region_text",)),
        ("jurisdiction", ("province_state", "country", "county_rm")),
        ("soil_texture", ("soil_texture", "soil_series_or_texture")),
        ("drainage", ("drainage", "drainage_class")),
        ("irrigation", ("irrigation", "irrigation_status")),
        ("soil_test", ("soil_test_summary",)),
        ("history_notes", ("crop_rotation_notes", "management_notes")),
        ("geometry_summary", ("geometry_summary",)),
        ("regional_context", ("regional_context",)),
    )
    used: list[dict[str, Any]] = []
    for public_name, keys in field_aliases:
        value = next((field_context[key] for key in keys if field_context.get(key)), None)
        if value:
            used.append({"field": public_name, "value": value, "source": source})
    quality = field_context.get("quality_meter")
    if isinstance(quality, dict) and quality.get("summary"):
        used.append({"field": "context_quality", "value": quality["summary"], "source": "system_quality_meter"})
    intersections = field_context.get("regional_intersections")
    if isinstance(intersections, list) and intersections:
        labels = []
        for item in intersections[:3]:
            if isinstance(item, dict):
                labels.append(" ".join(str(item.get(key) or "").strip() for key in ("system", "code", "name")).strip())
        if labels:
            used.append({"field": "regional_intersections", "value": "; ".join(label for label in labels if label), "source": "official_map_context"})
    return used


def _extract_caveats(answer_text: str, *, trace: dict[str, Any], risk_banner: str | None) -> list[str]:
    caveats: list[str] = []
    if risk_banner:
        caveats.append(risk_banner)
    if _risk_level(trace) == "regulated":
        caveats.append("Do not treat this as a product label, legal requirement, or rate recommendation.")
    if not _evidence_cards(trace):
        caveats.append("No source-backed evidence cards were available for this answer.")
    if re.search(r"\b(local|jurisdiction|region|county|state|province)\b", answer_text, re.IGNORECASE):
        caveats.append("Local rules, weather, and field conditions still need verification.")
    return _dedupe(caveats)


def _recommended_next_steps(answer_text: str, missing_data: list[str]) -> list[str]:
    steps = [f"Provide {item}." for item in missing_data[:4]]
    lowered = answer_text.lower()
    if "label" in lowered:
        steps.append("Verify the current local label before product decisions.")
    if "soil test" in lowered:
        steps.append("Attach or summarize the relevant soil test and method.")
    if not steps:
        steps.append("Open the evidence panel and confirm the sources fit the field context.")
    return _dedupe(steps)


def _report_actions(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": "thread_report", "label": "Thread report", "formats": ["pdf", "markdown", "json"], "thread_id": trace.get("thread_id")},
        {"id": "source_evidence_bundle", "label": "Source evidence bundle", "formats": ["json", "csv", "markdown"], "thread_id": trace.get("thread_id")},
    ]


def _feedback_prompt(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "quick_tags": [
            "helpful",
            "not_helpful",
            "questionable_safety",
            "missing_context",
            "weak_evidence",
            "too_generic",
            "too_cautious",
            "exposed_internal_wording",
        ],
        "consent_default": False,
        "thread_id": trace.get("thread_id"),
    }


def _debug_ref(trace: dict[str, Any]) -> str | None:
    metadata = trace.get("metadata") if isinstance(trace, dict) else {}
    return str(trace.get("trace_id") or (metadata or {}).get("phase5_trace_id") or "") or None


def _why_used(doc: dict[str, Any]) -> str:
    score = doc.get("score")
    if score is None:
        return "Selected as public agronomy context for this question."
    return f"Selected as public agronomy context with retrieval score {score}."


def _source_limitations(doc: dict[str, Any]) -> list[str]:
    limitations = []
    if not doc.get("updated_at") and not doc.get("ingested_at"):
        limitations.append("Source date was not available in the local metadata.")
    if not doc.get("url") and not doc.get("source_url"):
        limitations.append("Canonical URL was not available in the local metadata.")
    return limitations


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
