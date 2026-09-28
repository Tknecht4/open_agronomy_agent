"""Bounded method-only retrieval for reviewed US/Canada farm foundations.

These identifiers describe reusable reasoning, never a local target, measured
field fact, current price, regulated use, or permission to act.  The corpus
policy still decides which hash-bound records may enter the runtime.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


METHOD_SCHEMA = "open_agronomy_agent.method_scope.v1"
METHODS: dict[str, tuple[str, str]] = {
    "seed_mass": (
        r"\b(?:seed(?:ing)?[- ](?:rate|mass|lot|size)|kernel weight|seeds? per (?:pound|lb|kilogram|kg)|"
        r"thousand.kernel.weight|target stand|plant population|drill calibration)\b",
        "Explain how target stand, seed size, germination and expected establishment combine; obtain a local target and lot measurements.",
    ),
    "thermal_time": (
        r"\b(?:growing degree.days?|gdd|heat.units?|thermal.time|temperature accumulation|heat.unit chart)\b",
        "Explain thermal-time arithmetic with an explicit crop base, units, accumulation interval and model limits; compare with field observations.",
    ),
    "partial_budget": (
        r"\b(?:partial.budgets?|incremental[^.!?]{0,40}budget|incremental comparison|"
        r"budget[^.!?]{0,70}(?:rent|switch|instead)|"
        r"(?:rent|buy|hire|switch|replace|change|adopt)\w*[^.!?]{0,90}(?:instead|versus|vs\.?|alternative|current|existing|present)|"
        r"(?:instead|versus|vs\.?) [^.!?]{0,90}(?:cost|return|profit|farm|cultivat|weeder))\b",
        "Compare only added returns, saved costs, added costs and lost returns on the same time and area basis.",
    ),
    "enterprise_budget": (
        r"\b(?:enterprise budgets?|crop budgets?|cost.of.production|break.even|breakeven|"
        r"(?:enterprise|crop|farm) [^.!?]{0,55}(?:viabilit|margin|profitab|costs?|budget))\b",
        "State the enterprise, period, units and cost boundary; use farm-specific price, yield and cost scenarios.",
    ),
    "liquidity": (
        r"\b(?:current ratio|working capital|liquidit\w*|land equity|land wealth|"
        r"current assets|current liabilities|short of money)\b",
        "Distinguish dated current assets and liabilities from total wealth and from the timing of cash payments.",
    ),
    "cash_flow": (
        r"\b(?:cash.flow|cash (?:shortage|pinch|timing)|invoices?[^.!?]{0,60}(?:before|due)|"
        r"(?:bills?|payments?|debt service)[^.!?]{0,60}(?:before|due|arrive)|"
        r"(?:grain|crop|produce)[^.!?]{0,50}(?:sold|sale)[^.!?]{0,50}(?:before|after)|"
        r"(?:cash|tax) (?:basis|records?)|accrual)\b",
        "Schedule actual inflows and outflows, financing and debt service by period; distinguish cash from accrual profit.",
    ),
    "nutrient_plan_inputs": (
        r"\b(?:nutrient.plan\w*|nutrient advis(?:er|or)|manure (?:plan|analysis|analyses|nutrient)|"
        r"(?:fertiliz\w*|manure)[^.!?]{0,65}(?:soil test|crop need|application rate)|"
        r"soil (?:and|&) manure analys\w*)\b",
        "Organize field, soil, manure, crop and application records; require local calibration and current rules before any rate or regulated plan.",
    ),
}


def requested_methods(question: str) -> tuple[str, ...]:
    """Recognize an explicit method need without using retrieved text as input."""

    text = str(question or "")
    selected = [method for method, (pattern, _) in METHODS.items() if re.search(pattern, text, re.IGNORECASE)]
    if (re.search(r"\bseed\w*\b", text, re.IGNORECASE)
        and re.search(r"\b(?:germinat\w*|seed size|seeds? per|kernel weight)\b", text, re.IGNORECASE)
        and re.search(r"\b(?:stand|drill|mass|quantity|rate|lot)\b", text, re.IGNORECASE)):
        selected.append("seed_mass")
    if re.search(r"\benterprise\b", text, re.IGNORECASE) and re.search(r"\bbudget\b", text, re.IGNORECASE):
        selected.append("enterprise_budget")
    if re.search(r"\benterprise\b", text, re.IGNORECASE) and re.search(
        r"\b(?:output|sales?|receipts?|expenses?|costs?|margins?|viability|template)\b", text, re.IGNORECASE
    ):
        selected.append("enterprise_budget")
    if re.search(r"\b(?:manure|amendment)\b", text, re.IGNORECASE) and re.search(
        r"\b(?:nutrient|advis(?:er|or)|field|soil test|history|analysis|storage)\b", text, re.IGNORECASE
    ):
        selected.append("nutrient_plan_inputs")
    return tuple(dict.fromkeys(selected))


def reviewed_method_ids(doc: Any) -> tuple[str, ...]:
    """Fail closed on incomplete or self-inconsistent method metadata."""

    if str(getattr(doc, "answer_role", "")) != "method_context":
        return ()
    if str(getattr(doc, "transfer_scope", "")) != "general_method_only":
        return ()
    if str(getattr(doc, "retrieval_policy", "")) != "context_only":
        return ()
    if str(getattr(doc, "authority_tier", "")) != "internal_synthesis":
        return ()
    scope = getattr(doc, "method_scope", None)
    if not isinstance(scope, dict) or scope.get("schema_version") != METHOD_SCHEMA:
        return ()
    if scope.get("review_status") != "source_supported_method_scope_reviewed":
        return ()
    support_hash = scope.get("source_support_receipt_sha256")
    if not isinstance(support_hash, str) or re.fullmatch(r"[0-9a-f]{64}", support_hash) is None:
        return ()
    methods = scope.get("method_ids")
    if not isinstance(methods, list) or not methods or any(method not in METHODS for method in methods):
        return ()
    countries = scope.get("applicability_countries")
    if countries != ["Canada", "United States"]:
        return ()
    if set(getattr(doc, "jurisdictions", ()) or ()) != set(countries):
        return ()
    support = getattr(doc, "supporting_source_ids", ()) or ()
    if len(set(support)) < 2:
        return ()
    if not all(isinstance(value, str) and value for value in support):
        return ()
    return tuple(dict.fromkeys(methods))


def method_fit_reason(doc: Any, question: str, country: str | None) -> str | None:
    """Return a method-row disposition; ordinary documents use other filters."""

    if str(getattr(doc, "answer_role", "")) != "method_context":
        return None
    method_ids = reviewed_method_ids(doc)
    if not method_ids:
        return "invalid_method_scope"
    if country not in {"canada", "united states"}:
        return "method_target_country_unknown"
    if not set(method_ids).intersection(requested_methods(question)):
        return "method_mismatch"
    return "method_context_match"


def curated_method_response(context: Any, question: str) -> tuple[str | None, dict[str, Any] | None]:
    """Render admitted project-authored methods for explanation-only requests.

    This is a candidate-only deterministic skill. It cannot calculate supplied
    values, decide a farm action, or substitute a method for current authority.
    The normal safety and high-consequence policies still run afterward.
    """

    if context is None:
        return None, None
    runtime = getattr(context, "runtime_metadata", None) or {}
    if runtime.get("method_response_mode") != "curated_method_text_v1":
        return None, None
    route = getattr(context, "route", None)
    if str(getattr(route, "risk_level", "") or "") in {"high", "regulated"} or str(getattr(route, "question_type", "") or "") == "product_label":
        return None, None
    if re.search(r"\b(?:pesticide|herbicide|fungicide|insecticide|spray|label|registration)\b", question, re.IGNORECASE):
        return None, None
    if str(getattr(route, "question_type", "") or "") in {"fertility_diagnostic", "plant_health"}:
        return None, None
    if not re.search(r"\b(?:explain|describe|understand|how|what|which|why|framework|method|concept)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:and|also)\s+(?:advise|tell|recommend|decide|judge|assess|determine|predict)\b", question, re.IGNORECASE):
        return None, None
    for match in re.finditer(r"\bhow\s+(?:should|could|would)\s+(?:i|we)\s+(?P<verb>\w+)", question, re.IGNORECASE):
        if match.group("verb").lower() not in {"use", "adapt", "interpret", "organize", "compare", "record", "reconcile", "explain", "check", "think", "evaluate"}:
            return None, None
    if re.search(r"\buse\s+(?:this|the)\s+(?:fertilizer|manure|seed|pesticide|herbicide|product)\b", question, re.IGNORECASE):
        return None, None
    for match in re.finditer(r"\b(?:should|could|would)\s+(?:i|we)\b", question, re.IGNORECASE):
        prefix = question[max(0, match.start() - 90):match.start()]
        if re.search(r"\b(?:how|what|which)\b[^?.!;]{0,75}$", prefix, re.IGNORECASE) is None:
            return None, None
    if re.search(r"\b(?:can|may)\s+(?:i|we)\s+(?:sell|buy|finance|borrow|hire|choose|rank|copy|adopt|apply|spray|treat)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\btell me if\b|\b(?:diagnos\w*|deficien\w*)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:current|today'?s|live|latest)\b[^?]{0,55}\b(?:prices?|quotes?|bids?|market values?)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:prices?|quotes?|bids?|market values?)\b[^?]{0,40}\b(?:now|today|currently|latest|live)\b", question, re.IGNORECASE):
        return None, None
    if re.search(
        r"\b(?:prices?|quotes?|bids?)\b[^?]{0,75}\b(?:at|from)\s+(?:our|the|a)\s+"
        r"(?:local\s+)?(?:elevator|buyer|market|exchange|broker)\b|"
        r"\b(?:cash bid|spot price|market quote)\b",
        question,
        re.IGNORECASE,
    ):
        return None, None
    if re.search(r"\b(?:suggest|choose|set|give|pick)\b[^?]{0,55}\b(?:target stand|plant population|seeding rate)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:give me|tell me|advise|recommend|decide for me|ready to harvest|best choice|selling for|sell land|buy land|borrow to)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:estimate|forecast|predict)\b", question, re.IGNORECASE):
        return None, None
    request_start = re.compile(r"^\s*(?:please|explain|describe|outline|list|show|how|what|which|why|can|could|would|should|is|are|do|does|will|may|give|tell|recommend|advise|decide|suggest|assess|judge|evaluate|determine)\b", re.IGNORECASE)
    method_request_terms = re.compile(
        r"\b(?:method|framework|reasoning|inputs?|conventions?|comparison|compare|belong|adapt|chart|budget|"
        r"ratios?|log|records?|gather|organize|cash[- ]flow|working capital|degree days|measures?|rows?|"
        r"basis|seed[- ]mass|seed lots?|germination|units?|evidence packet|nutrient advis(?:er|or)|"
        r"(?:setting|calibrating) the drill)\b",
        re.IGNORECASE,
    )
    request_boundary = (
        r"(?<=[.!?;])\s+|"
        r"(?:,\s*|\s+)(?:and|or)\s+(?=(?:please|is|are|do|does|should|can|could|would|will|may|what|how|which|why|give|tell|recommend|advise|decide|suggest|assess|judge|evaluate|determine)\b)"
    )
    for sentence in re.split(request_boundary, question, flags=re.IGNORECASE):
        if request_start.search(sentence):
            if not method_request_terms.search(sentence):
                return None, None
    expected_hash = str(runtime.get("method_support_receipt_sha256") or "")
    store_path = str(runtime.get("method_transfer_store") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or not store_path:
        return None, None
    if re.search(r"\b(?:how much|how many|calculate|compute|exact(?:ly)?)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:can|should)\s+(?:i|we)\s+(?:copy|adopt|rank|apply|spray|treat)\b", question, re.IGNORECASE):
        return None, None
    if re.search(r"\b(?:what|which)\s+(?:fertilizer |pesticide |herbicide |manure )?(?:rate|product|dose|threshold)\b", question, re.IGNORECASE):
        return None, None
    query_context = runtime.get("query_context") or {}
    country = str(query_context.get("country") or "")
    targets = tuple(query_context.get("target_jurisdictions") or ())
    if country not in {"canada", "united states"} or len(targets) != 1:
        return None, None
    from agronomy_agent.query_context import _NON_SITE_CONJOINED_PREFIXES, _normalize_jurisdiction_scope

    # Every explicitly owned site must resolve inside the declared destination.
    # Unknown descriptors are a safe miss for this optional renderer.
    owned_site_pattern = (
        r"\b(?:my|our)\s+(?P<place>[A-Za-z-]+(?:\s+[A-Za-z-]+){0,2})\s+"
        r"(?:farm|field|dairy|crop|operation|orchard|ranch)\b"
    )
    for match in re.finditer(owned_site_pattern, question, re.IGNORECASE):
        site_countries, site_subdivisions = _normalize_jurisdiction_scope((match.group("place"),))
        if country not in site_countries or (site_subdivisions and str(targets[0]).lower() not in site_subdivisions):
            return None, None

    for match in re.finditer(r"\b(?:and|or)\s+in\s+(?P<place>[A-Za-z-]+(?:\s+[A-Za-z-]+){0,2})", question, re.IGNORECASE):
        place = match.group("place")
        first = place.split()[0].lower()
        if first in _NON_SITE_CONJOINED_PREFIXES:
            continue
        countries, subdivisions = _normalize_jurisdiction_scope((place,))
        if country not in countries or (subdivisions and str(targets[0]).lower() not in subdivisions):
            return None, None
    from agronomy_agent.query_context import (
        _inferred_destination_jurisdiction,
        _inferred_owned_country,
        _named_jurisdiction_spans,
    )

    named_site = _inferred_destination_jurisdiction(
        question, _named_jurisdiction_spans(question), require_multiple=False
    )
    owned_country = _inferred_owned_country(question)
    if named_site:
        if (str(targets[0]).lower(), country) != named_site:
            return None, None
    elif owned_country != country or str(targets[0]).lower() != country:
        # A cited source's geography is not proof of the user's operation site.
        return None, None
    wanted = requested_methods(question)
    if not wanted or len(wanted) > 2:
        return None, None
    expected_dir = PurePosixPath(store_path).parent.as_posix() + "/"
    admitted = {
        source_id
        for section in getattr(getattr(context, "packed_context", None), "sections", ())
        for source_id in getattr(section, "source_ids", ())
    }
    by_method: dict[str, Any] = {}
    for doc in getattr(context, "retrieved_docs", ()):
        if doc.doc_id not in admitted or not str(getattr(doc, "corpus_path", "")).startswith(expected_dir):
            continue
        if (getattr(doc, "method_scope", None) or {}).get("source_support_receipt_sha256") != expected_hash:
            continue
        for method_id in reviewed_method_ids(doc):
            by_method.setdefault(method_id, doc)
    if any(method_id not in by_method for method_id in wanted):
        return None, None
    selected = tuple(by_method[method_id] for method_id in wanted)
    from agronomy_agent.evidence_contracts import applicability_from_retrieved_doc

    for method_id, doc in zip(wanted, selected):
        envelope = applicability_from_retrieved_doc(doc, question_jurisdictions=targets)
        if envelope.transfer_status != "reviewed_general_method_scope" or method_id not in envelope.methods:
            return None, None
    target = str(targets[0]).title()
    opening = (
        f"For your {target} operation, the following source-supported method can organize the reasoning."
        if len(selected) == 1 else
        f"For your {target} operation, these source-supported methods can organize the reasoning."
    )
    sections = [f"**{doc.title}**\n{doc.text}" for doc in selected]
    boundary = (
        "The cited source regions support the method only. Use applicable local evidence "
        "for crop targets, field measurements, current prices, rates, labels and legal duties."
    )
    response = "\n\n".join((opening, *sections, boundary))
    receipt = {
        "schema_version": "open_agronomy_agent.curated_method_response.v1",
        "renderer": "curated_method_text_v1",
        "method_ids": list(wanted),
        "doc_ids": [doc.doc_id for doc in selected],
        "source_support_receipt_sha256": expected_hash,
        "target_jurisdiction": target,
        "authority": "method_context_only",
    }
    return response, receipt
