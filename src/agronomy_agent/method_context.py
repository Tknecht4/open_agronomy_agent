"""Bounded method-only retrieval for reviewed US/Canada farm foundations.

These identifiers describe reusable reasoning, never a local target, measured
field fact, current price, regulated use, or permission to act.  The corpus
policy still decides which hash-bound records may enter the runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MethodTask:
    """A question-owned operation; span indexes refer to the original question."""

    method_id: str
    operation: str
    disposition: str  # requested, background, negated, unresolved
    span: tuple[int, int]
    text: str


# Cues identify a method, while the clause parser below decides whether that
# method is actually requested. They are deliberately narrower than topical
# retrieval keywords: a vague farm budget or cash problem does not select a card.
_CUES = {
    "seed_mass": re.compile(r"\b(?:seed(?:ing)?[- ](?:mass|rate|size)|seed (?:kilograms?|kg)|drill (?:rate|calibration)|target stand|plant population|thousand[- ]kernel weight|kernel weight|seeds? per (?:pound|lb|kilogram|kg))\b", re.I),
    "thermal_time": re.compile(r"\b(?:growing degree[- ]days?|gdd|heat units?|thermal time|temperature accumulation)\b", re.I),
    "partial_budget": re.compile(r"\b(?:partial budgets?|incremental (?:farm )?(?:budget|comparison)|rent[- ]versus[- ]buy|rent (?:instead of|versus|vs\.?|or) buy|(?:added|saved)(?: and (?:added|saved))? costs? and returns?|changed (?:returns? and costs?|costs? and returns?))\b", re.I),
    "enterprise_budget": re.compile(r"\b(?:enterprise budgets?|crop (?:enterprise )?budgets?|cost[- ]of[- ]production|break[- ]even|breakeven)\b", re.I),
    "liquidity": re.compile(r"\b(?:liquidit\w*|working capital|current ratio|current assets?|current liabilities|balance[- ]sheet (?:ratios?|measures?|check))\b", re.I),
    "cash_flow": re.compile(r"\b(?:cash[- ]flow|cash (?:plan|schedule|forecast|budget|gap|shortage|pinch|timing)|monthly cash|dated cash|schedule (?:receipts|payments|inflows|outflows)|(?:receipts|inflows) against (?:bills|payments|outflows))\b", re.I),
    "nutrient_plan_inputs": re.compile(r"\b(?:nutrient[- ]plan\w*|manure (?:nutrient )?plan\w*|manure analys\w*|nutrient advis(?:er|or)|soil and manure analys\w*)\b", re.I),
}
_REQUEST = re.compile(
    r"\b(?:how|what|which|why|whether|can|could|should|would|explain|describe|show|compare|calculate|compute|convert|lay out|make|build|list|identify|organize|schedule|assess|draft|prepare|help|tell|use|gather)\b",
    re.I,
)
_NEGATION = re.compile(r"\b(?:do not|don't|no need to|i do not need|i don't need|skip|avoid|ignore|no)\b", re.I)
_DOUBLE_NEGATION = re.compile(r"\b(?:do not|don't|never)\s+(?:omit|forget|skip|exclude|leave out)\b", re.I)
_BACKGROUND = re.compile(r"\b(?:mentions?|says?|lists?|labelled|labeled|appears?|attached|shows?|contains?|includes?|as background)\b", re.I)
_METADATA_REQUEST = re.compile(
    r"\b(?:address|author|wrote|publisher|publication|doi|deadline|filing year|"
    r"workshop date|license|licensed|certificate|file location|where (?:is|was))\b",
    re.I,
)
_SPLIT = re.compile(
    r"[.!?;]+\s*|\s+\b(?:but|then|even though|whereas)\b\s+|"
    r"\s+\band\b\s+(?=\b(?:do not|don't|ignore|avoid|skip|explain|describe|show|compare|calculate|compute|convert|lay out|make|build|list|identify|organize|schedule|assess|draft|prepare)\b)|"
    r",\s*(?=\b(?:only|just|instead|rather|explain|show|compare|calculate|compute|assess|prepare|make|build)\b)",
    re.I,
)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\'[^\'\n]*\'(?!\w)')
_FOLLOW_ON = {
    "seed_mass": re.compile(r"\b(?:stand|drill|seed|germination|plant population)\b", re.I),
    "partial_budget": re.compile(r"\b(?:comparison|changed costs?|changed returns?)\b", re.I),
    "enterprise_budget": re.compile(r"\b(?:budget|saleable|output|sales?|expenses?|costs?|margins?)\b", re.I),
    "nutrient_plan_inputs": re.compile(r"\b(?:inputs?|records?|evidence|manure|plan)\b", re.I),
}


def _cue_directive(clause: str, cue_start: int) -> str | None:
    """Use the last directive before this cue, not sentence-wide polarity."""

    prefix = clause[:cue_start]
    inclusions = list(_DOUBLE_NEGATION.finditer(prefix))
    directives = [(*match.span(), "negative") for match in _NEGATION.finditer(prefix)
                  if not any(item.start() <= match.start() < item.end() for item in inclusions)]
    directives += [(*match.span(), "include") for match in inclusions]
    # Predicate negation ("cash flow is not liquidity") expresses a relation
    # between two requested concepts. Bare "not liquidity" excludes a task.
    directives += [(*match.span(), "negative") for match in re.finditer(
        r"(?<!do )(?<!is )(?<!are )(?<!was )(?<!were )(?<!does )(?<!did )"
        r"(?<!can )(?<!could )(?<!should )(?<!would )(?<!will )\bnot\b",
        prefix, re.I)
                  if cue_start - match.end() <= 18]
    if not directives:
        return None
    start, end, kind = max(directives, key=lambda item: (item[0], item[1]))
    # Bare "no" is only a method denial when adjacent to that method; "no
    # numbers" after a cash-flow request cannot retroactively negate it.
    if prefix[start:end].lower() == "no" and cue_start - end > 3:
        return None
    return kind


def _operation(clause: str) -> str:
    match = _REQUEST.search(clause)
    return match.group(0).lower() if match else "unspecified"


def method_task_frame(question: str) -> tuple[MethodTask, ...]:
    """Parse bounded, explicit method tasks from the user's question alone.

    Unrecognized paraphrases stay unresolved by omission; this frame does not
    infer an operation from retrieved text or a model. Quoted material is treated
    as background unless the method is also named outside the quotation.
    """

    source = str(question or "")
    quoted = list(_QUOTED.finditer(source))
    masked = _QUOTED.sub(lambda m: " " * (m.end() - m.start()), source)
    boundaries = [0, *(match.end() for match in _SPLIT.finditer(masked)), len(source)]
    tasks: list[MethodTask] = []
    for quote in quoted:
        for method_id, cue in _CUES.items():
            for match in cue.finditer(quote.group(0)):
                span = (quote.start() + match.start(), quote.start() + match.end())
                tasks.append(MethodTask(method_id, "unspecified", "background", span, source[span[0]:span[1]]))
    history: list[tuple[int, str]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        clause = masked[start:end]
        original = source[start:end]
        if not clause.strip():
            continue
        operation = _operation(clause)
        double_negation = bool(_DOUBLE_NEGATION.search(clause))
        if double_negation and operation == "unspecified":
            operation = "include"
        has_request = operation != "unspecified"
        # A leading denial scopes only this clause. "Do not omit" requests
        # inclusion and must not turn a cash plan into a negated task.
        negated = bool(_NEGATION.search(clause)) and not double_negation
        background = (bool(re.search(r"\bas background\b", clause, re.I)) or
                      bool(_METADATA_REQUEST.search(clause)) or
                      (bool(_BACKGROUND.search(clause)) and not has_request))
        for method_id, cue in _CUES.items():
            for match in cue.finditer(clause):
                directive = _cue_directive(clause, match.start())
                disposition = (
                    "negated" if directive == "negative" else
                    "background" if background else
                    "requested" if has_request else
                    "unresolved"
                )
                if method_id == "seed_mass" and re.search(r"\b(?:right|best|recommended|optimal) seed(?:ing)? rate\b", clause, re.I):
                    # This asks for a local target, not the transfer method.
                    disposition = "unresolved"
                tasks.append(MethodTask(method_id, "include" if directive == "include" else operation, disposition,
                                        (start + match.start(), start + match.end()),
                                        original[match.start():match.end()]))
        # A few compositional expressions name the calculation without its
        # conventional title. Require both operands in the same requested clause.
        directive_denial = bool(re.match(r"\s*(?:do not|don't|no\b|skip\b|avoid\b|ignore\b)", clause, re.I)) and not double_negation
        if has_request and not directive_denial and not background:
            composed = (
                ("seed_mass", r"\bseed\w*\b.*\b(?:germinat\w*|seed size|kernel weight)\b.*\b(?:stand|drill|mass|kilograms?|kg)\b"),
                ("seed_mass", r"\btarget (?:number|stand|population)\b.*\b(?:plants?|seeds?)\b.*\b(?:kilograms?|kg)\b.*\bseed lot\b"),
                ("enterprise_budget", r"\benterprise\b.*\b(?:output|saleable|sales?|expenses?|costs?|margins?)\b"),
                ("nutrient_plan_inputs", r"\b(?:manure|amendment)\b.*\b(?:field history|soil tests?|advis(?:er|or)|storage)\b"),
                ("partial_budget", r"\b(?:rent|buy|hire|switch|replace)\b.*\b(?:weeder|spreader|contractor|machine)\b.*\b(?:changed|added|saved) (?:returns?|costs?)\b"),
                ("cash_flow", r"\b(?:schedule|lay out|plan)\b.*\b(?:receipts?|inflows?|bills?|payments?)\b.*\b(?:bills?|payments?|cash gap|loan)\b"),
            )
            for method_id, pattern in composed:
                match = re.search(pattern, clause, re.I)
                if match and not any(task.method_id == method_id and start <= task.span[0] < end for task in tasks):
                    tasks.append(MethodTask(method_id, operation, "requested",
                                            (start + match.start(), start + match.end()),
                                            original[match.start():match.end()]))
            # A method named in an immediately preceding background clause may
            # be the antecedent of a method-specific follow-up operation.
            # Generic follow-ups (author, address, deadline, file location)
            # cannot inherit that method.
            explicit_requested = any(task.disposition == "requested" and start <= task.span[0] < end
                                     for task in tasks)
            for method_id, reference in _FOLLOW_ON.items():
                if explicit_requested:
                    break
                if not reference.search(clause):
                    continue
                if any(task.method_id == method_id and task.disposition == "requested"
                       and start <= task.span[0] < end for task in tasks):
                    continue
                for previous_start, previous_text in reversed(history[-3:]):
                    antecedent = (_CUES[method_id].search(previous_text) or
                                  (method_id == "enterprise_budget" and re.search(r"\benterprise\b", previous_text, re.I)) or
                                  (method_id == "partial_budget" and re.search(
                                      r"\b(?:hire|rent|buy|switch|replace)\b.*\b(?:instead|versus|vs\.?|alternative)\b",
                                      previous_text, re.I)))
                    if method_id == "nutrient_plan_inputs" and re.search(r"\bevidence\b", clause, re.I):
                        antecedent = (re.search(r"\b(?:manure|nutrient)\b", previous_text, re.I)
                                      and re.search(r"\b(?:field history|soil test|advis(?:er|or)|storage)\b", previous_text, re.I))
                    if antecedent and not _NEGATION.search(previous_text):
                        tasks.append(MethodTask(method_id, operation, "requested",
                                                (previous_start, end), source[previous_start:end]))
                        break
        history.append((start, clause))
    return tuple(sorted(tasks, key=lambda task: task.span))


def requested_methods(question: str) -> tuple[str, ...]:
    """Project only requested tasks for both obligations and method-card fit."""

    return tuple(dict.fromkeys(task.method_id for task in method_task_frame(question)
                               if task.disposition == "requested"))


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
    from agronomy_agent.query_context import _unrecognized_operation_site

    if _unrecognized_operation_site(question):
        return "method_target_scope_unresolved"
    if not set(method_ids).intersection(requested_methods(question)):
        return "method_mismatch"
    return "method_context_match"
