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



def source_bound_method_appendix(context: Any, question: str) -> tuple[str | None, dict[str, Any] | None]:
    """Prepare admitted method background for the ordinary answer path.

    This optional candidate component is evidence text, not a final answer.
    The model still drafts for the full request, and verification and safety
    evaluate the combined draft. Missing scope or support fails closed.
    """

    if context is None:
        return None, None
    runtime = getattr(context, "runtime_metadata", None) or {}
    if runtime.get("method_response_mode") != "source_bound_appendix_v1":
        return None, None
    route = getattr(context, "route", None)
    if str(getattr(route, "risk_level", "") or "") in {"high", "regulated"}:
        return None, None
    if str(getattr(route, "question_type", "") or "") in {
        "product_label", "fertility_rate", "fertility_diagnostic", "plant_health"
    }:
        return None, None
    expected_hash = str(runtime.get("method_support_receipt_sha256") or "")
    store_path = str(runtime.get("method_transfer_store") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or not store_path:
        return None, None
    wanted = requested_methods(question)
    if not wanted:
        return None, None
    query_context = runtime.get("query_context") or {}
    country = str(query_context.get("country") or "")
    targets = tuple(query_context.get("target_jurisdictions") or ())
    if country not in {"canada", "united states"} or len(targets) != 1:
        return None, None
    admitted = {
        source_id
        for section in getattr(getattr(context, "packed_context", None), "sections", ())
        for source_id in getattr(section, "source_ids", ())
    }
    expected_dir = PurePosixPath(store_path).parent.as_posix() + "/"
    from agronomy_agent.evidence_contracts import applicability_from_retrieved_doc

    selected: list[tuple[Any, tuple[str, ...]]] = []
    included_methods: set[str] = set()
    for doc in getattr(context, "retrieved_docs", ()):
        if doc.doc_id not in admitted or not str(getattr(doc, "corpus_path", "")).startswith(expected_dir):
            continue
        scope = getattr(doc, "method_scope", None) or {}
        if scope.get("source_support_receipt_sha256") != expected_hash:
            continue
        methods = tuple(method for method in reviewed_method_ids(doc) if method in wanted)
        if not methods:
            continue
        envelope = applicability_from_retrieved_doc(doc, question_jurisdictions=targets)
        if envelope.transfer_status != "reviewed_general_method_scope":
            continue
        selected.append((doc, methods))
        included_methods.update(methods)
    if not selected:
        return None, None
    sections = [
        f"**{doc.title}** [method source: {doc.doc_id}]\n{doc.text}"
        for doc, _ in selected
    ]
    boundary = (
        "These project-authored source-linked summaries explain general methods only. "
        "They do not establish this farm's target, measured field condition, "
        "current price, application rate, product permission, or legal duty."
    )
    text = "\n\n".join(("Source-supported method background (context only):", *sections, boundary))
    receipt = {
        "schema_version": "open_agronomy_agent.method_answer_appendix.v1",
        "renderer": "source_bound_appendix_v1",
        "requested_method_ids": list(wanted),
        "included_method_ids": sorted(included_methods),
        "doc_ids": [doc.doc_id for doc, _ in selected],
        "source_support_receipt_sha256": expected_hash,
        "authority": "method_context_only_not_complete_answer",
    }
    return text, receipt
