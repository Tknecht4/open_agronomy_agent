from __future__ import annotations

import re
from typing import Any


HIGH_CONSEQUENCE_SCHEMA = "open_agronomy_agent.high_consequence_policy.v1"


def classify_high_consequence_domains(question: str) -> list[str]:
    domains: list[str] = []
    product_term = re.search(
        r"\b(?:spray|herbicide|fungicide|insecticide|pesticide|product|tank mix|adjuvant|label|registration|"
        r"pulvéris\w*|produit|mélange en cuve|étiquette|homologation)\b",
        question,
        re.IGNORECASE,
    )
    product_action = re.search(
        r"\b(?:can|should|may|would|do)\s+(?:i|we)\b|\b(?:use|apply|spray|mix|recommend|choose|select)\b"
        r"|\b(?:rate|timing|interval|preharvest|re-entry|grazing restriction)\b"
        r"|\b(?:puis-je|devrais-je|peut-on|utiliser|appliquer|pulvériser|mélanger|recommander|choisir|"
        r"taux|dose|moment|délai|avant récolte|rentrée|restriction de pâturage)\b",
        question,
        re.IGNORECASE,
    )
    if product_term and product_action:
        domains.append("product_label")
    explicit_rate_request = re.search(
        r"\b(?:how much|what rate|rate should|dose|apply per|fertilizer rate|"
        r"nitrogen rate|phosphorus rate|combien|quel(?:le)? taux|quel(?:le)? dose|"
        r"dose par|taux d['’](?:engrais|azote|phosphore))\b",
        question,
        re.IGNORECASE,
    )
    rate_unit = re.search(r"\b(?:lb/?ac|kg/?ha)\b", question, re.IGNORECASE)
    rate_action_context = re.search(
        r"\b(?:apply|application|fertiliz\w*|nitrogen|phosphorus|potassium|"
        r"sulphur|sulfur|manure|lime|seed(?:ing)?|spray|dose|rate|"
        r"enough|too much|recommend|should|need|appliquer|application|engrais|azote|"
        r"phosphore|potassium|soufre|fumier|chaux|semis|pulvéris\w*|taux|"
        r"suffisant|trop|recommand\w*|devrais|besoin)\b",
        question,
        re.IGNORECASE,
    )
    if explicit_rate_request or (rate_unit and rate_action_context):
        domains.append("numeric_rate")
    if re.search(
        r"\b(?:diagnos\w*|identify (?:this|the)|what disease|what is wrong|what caused|is this (?:a|an)|"
        r"diagnosti\w*|identifier|quelle maladie|quel est le problème|qu['’]est-ce qui a causé|est-ce (?:une?|un))\b",
        question,
        re.IGNORECASE,
    ):
        domains.append("diagnosis")
    if re.search(
        r"\b(?:current weather|forecast|spray window|spray today|spray tomorrow|rain today|rain tomorrow|wind now|"
        r"météo actuelle|prévisions?|fenêtre de pulvérisation|pulvériser aujourd['’]hui|pulvériser demain|"
        r"pluie aujourd['’]hui|pluie demain|vent maintenant)\b",
        question,
        re.IGNORECASE,
    ):
        domains.append("current_weather")
    if re.search(
        r"\b(?:roi|return on investment|will\b.{0,40}\bpay|payback|break[- ]even|profit|margin|financial decision|"
        r"rendement du capital investi|sera\b.{0,40}\brentable|rentabilité|seuil de rentabilité|marge|décision financière)\b",
        question,
        re.IGNORECASE,
    ):
        domains.append("financial")
    if re.search(
        r"\b(?:food safety|produce safety|crop[- ]contact (?:agricultural )?water|"
        r"agricultural water.{0,40}(?:harvest|produce|crop)|"
        r"(?:livestock|animal|manure).{0,60}(?:upstream|water intake|irrigation water)|"
        r"(?:washing|wash).{0,40}(?:safe|safety|contamination)|"
        r"salubrité des aliments|salubrité des produits|eau.{0,30}contact.{0,30}culture|"
        r"eau agricole.{0,40}(?:récolte|produit|culture)|"
        r"(?:bétail|animal|fumier).{0,60}(?:en amont|prise d['’]eau|eau d['’]irrigation)|"
        r"(?:lavage|laver).{0,40}(?:salubre|sécuritaire|contamination))\b",
        question,
        re.IGNORECASE,
    ):
        domains.append("food_safety")
    regulatory_subject = re.search(
        r"\b(?:legal|law|regulation|regulatory|compliance|requirement|required|permit|"
        r"setback|record keeping|recordkeeping|agricultural operation practices act|aopa|nrcb|"
        r"légal|loi|règlement|réglementaire|conformité|exigence|requis|permis|distance de retrait|"
        r"tenue de registres)\b",
        question,
        re.IGNORECASE,
    )
    regulatory_action = re.search(
        r"\b(?:exact|must|need|use|apply|comply|tomorrow|today|how far|how many|how much|what|"
        r"dois|doit|besoin|utiliser|appliquer|respecter|demain|aujourd['’]hui|quelle distance|"
        r"combien|quel(?:le)?)\b",
        question,
        re.IGNORECASE,
    )
    if regulatory_subject and regulatory_action:
        domains.append("regulatory_compliance")
    return domains


def _context_value(context: dict[str, Any], key: str) -> Any:
    if context.get(key) not in (None, "", [], {}):
        return context.get(key)
    metadata = context.get("metadata")
    if isinstance(metadata, dict) and metadata.get(key) not in (None, "", [], {}):
        return metadata.get(key)
    return None


def _has_value(context: dict[str, Any], *keys: str) -> bool:
    return any(_context_value(context, key) not in (None, "", [], {}) for key in keys)


def _tool_payloads(trace: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for record in trace.get("tool_invocations") or []:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        rows.append((str(record.get("name") or ""), payload))
    return rows


def evaluate_high_consequence_policy(
    *,
    question: str,
    trace: dict[str, Any],
    field_context: dict[str, Any] | None,
    network_mode: str,
) -> dict[str, Any]:
    domains = classify_high_consequence_domains(question)
    if not domains:
        return {
            "schema_version": HIGH_CONSEQUENCE_SCHEMA,
            "status": "not_applicable",
            "domains": [],
            "blocked": False,
            "missing_evidence": [],
            "network_mode": network_mode,
        }

    context = field_context if isinstance(field_context, dict) else {}
    tools = _tool_payloads(trace)
    missing: list[str] = []

    if "product_label" in domains:
        exact_label_verified = any(
            name in {"epa_ppls_product_search", "health_canada_pmra_label_search"}
            and payload.get("status") == "available"
            and payload.get("current_label_text_verified") is True
            and (
                not isinstance(payload.get("freshness"), dict)
                or payload["freshness"].get("safe_for_high_consequence") is True
            )
            for name, payload in tools
        )
        if not exact_label_verified:
            missing.append("exact current product label and jurisdiction-specific registration")
        if not _has_value(context, "product_name", "registration_number", "epa_registration_number", "pmra_registration_number"):
            missing.append("exact product or registration number")
        if not _has_value(context, "crop", "crop_current"):
            missing.append("crop/site")
        if not _has_value(context, "target_pest", "target_weed", "disease_or_symptom"):
            missing.append("target pest, weed, or disease")

    if "numeric_rate" in domains:
        for description, keys in (
            ("current method-identified soil or tissue test with units and date", ("soil_test_summary", "soil_test")),
            ("crop and realistic yield goal", ("yield_goal", "target_yield")),
            ("field application and crop-credit history", ("fertility_history", "application_history", "manure_history")),
            ("jurisdiction-specific calibration or authority", ("local_calibration", "recommendation_authority")),
        ):
            if not _has_value(context, *keys):
                missing.append(description)

    if "diagnosis" in domains and not _has_value(
        context,
        "diagnosis_confirmed_by_lab",
        "diagnostic_lab_result",
        "confirmed_diagnosis",
    ):
        missing.append("representative sample or qualified diagnostic confirmation")

    if "current_weather" in domains:
        current_weather = any(
            (
                "weather" in name
                or "nasa_power" in name
                or "daymet" in name
                or "nasdi" in name
                or "forecast" in name
            )
            and payload.get("status") in {"available", "partial_available"}
            and isinstance(payload.get("freshness"), dict)
            and payload["freshness"].get("safe_for_high_consequence") is True
            for name, payload in tools
        )
        if network_mode == "offline":
            missing.append("current local weather/forecast after reconnecting")
        elif not current_weather:
            missing.append("dated current weather or forecast from an appropriate local source")

    if "financial" in domains:
        for description, keys in (
            ("user-specific input and application costs", ("input_cost", "application_cost", "costs")),
            ("crop price or value assumption", ("crop_price", "commodity_price")),
            ("locally defensible response range", ("expected_response", "response_probability", "trial_response")),
        ):
            if not _has_value(context, *keys):
                missing.append(description)

    if "food_safety" in domains:
        for description, keys in (
            (
                "dated crop-contact water incident and hazard assessment",
                ("water_hazard_assessment", "food_safety_incident", "agricultural_water_assessment"),
            ),
            (
                "crop, water-contact timing, harvest timing, and affected lot identity",
                ("affected_lot_and_timing", "harvest_lot_record", "crop_contact_record"),
            ),
            (
                "current jurisdiction-specific produce-safety plan or authority",
                ("produce_safety_plan", "food_safety_authority", "current_food_safety_requirement"),
            ),
            (
                "documented hold, segregation, corrective-action, or disposition decision",
                ("harvest_disposition", "corrective_action_record", "hold_or_release_record"),
            ),
        ):
            if not _has_value(context, *keys):
                missing.append(description)

    if "regulatory_compliance" in domains:
        if not _has_value(
            context,
            "current_regulatory_authority",
            "current_legislation",
            "regulatory_source_version",
        ):
            missing.append("dated current jurisdiction-specific legislation or regulator guidance")
        if not _has_value(context, "jurisdiction", "province_state", "province", "state"):
            missing.append("applicable jurisdiction")

    missing = list(dict.fromkeys(missing))
    blocked = bool(missing)
    return {
        "schema_version": HIGH_CONSEQUENCE_SCHEMA,
        "status": "blocked_missing_evidence" if blocked else "supported_with_verification",
        "domains": domains,
        "blocked": blocked,
        "missing_evidence": missing,
        "network_mode": network_mode,
        "boundary": (
            "No action should be taken from this answer until the listed evidence is supplied and checked."
            if blocked
            else "The minimum machine-checkable evidence is present; verify local authority and field fit before acting."
        ),
    }


def apply_high_consequence_boundary(answer: str, policy: dict[str, Any]) -> str:
    if not policy.get("blocked"):
        return answer
    domains = ", ".join(str(value).replace("_", " ") for value in policy.get("domains") or [])
    missing = "; ".join(str(value) for value in policy.get("missing_evidence") or [])
    banner = (
        f"Decision boundary: do not act on this {domains} decision from this answer. "
        f"Missing evidence: {missing}. Use the answer only to plan the next verification step."
    )
    if banner.lower() in answer.lower():
        return answer
    return f"{banner}\n\n{answer.strip()}"
