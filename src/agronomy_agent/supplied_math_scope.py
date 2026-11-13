"""Whole-request scope for bounded supplied-input arithmetic parsers."""
from __future__ import annotations

import re
from agronomy_agent.foundation_math_parser import _unsafe_action_request


def has_unlabelled_numeric_alternatives(text: str) -> bool:
    """Do not pick the last number in '24 or 30 mm' or '20% or 40%-N'."""
    number = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    return bool(re.search(rf"(?<![\w.,+-]){number}\s*%?\s*(?:or|and|to)\s*{number}(?![\d.,])", text, re.I))


def supplied_math_scope(question: str) -> str | None:
    text = " ".join(question.translate(str.maketrans("₂₅−", "25-")).split())
    if not re.search(r"\b(?:calculate|compute|convert|how many|how much)\b", text, re.I):
        return None
    if re.match(r"(?:why|explain|define|how (?:does|do))\b", text, re.I):
        return None
    # These are closed exclusions/assumptions, not a blanket negation rule.
    # Any later sentence or coordinated instruction still participates.
    scope = re.sub(r",?\s+not a recommended rate(?: or carrier[- ]water volume)?(?=[.!?]|$)", "", text, flags=re.I)
    scope = re.sub(r",?\s+assuming the label basis is correct(?=[.!?]|$)", "", scope, flags=re.I)
    if _unsafe_action_request(scope.casefold()):
        return None
    if re.search(
        r"\b(?:should|may|can|could|would|must|legal|permitted|authorize|recommend|recommended|"
        r"safe to|safety|label|mixing order|re[- ]entry|withholding|today|tomorrow|allowed|approved|"
        r"permissible|choose|select|decide|advise|apply|applying|spray|spraying|irrigate)\b|"
        r"\b(?:which|what)\s+(?:product|rate|crop|treatment)\b|"
        r"\b(?:then|also|and)\s+(?:please\s+)?(?:apply|spray|use|mix|irrigate)\b|"
        r"(?:^|[.!?;])\s*(?:please\s+)?(?:apply|spray|use|mix|irrigate)\b", scope, re.I,
    ):
        return None
    if re.search(r"\b(?:calculate|compute|convert)\b[^!?;]*[.!?;]\s*how (?:many|much)\b", scope, re.I):
        return None
    other_question = re.sub(r"\bhow (?:many|much)\b", "", scope, count=1, flags=re.I)
    if re.search(r"\b(?:what|which|when|where|who|why|how)\b", other_question, re.I):
        return None
    if re.search(r"\bexplain\b(?!\s+(?:its|the|their)\s+(?:limits|limitations|boundaries)\b)", scope, re.I):
        return None
    if re.search(r"\b(?:and|also|then)\s+(?:calculate|compute|convert|choose|select|decide)\b", scope, re.I):
        return None
    remainder = re.sub(r'(?:[.!?;]\s*|\band\s+)state (?:the )?(?:units|assumptions|arithmetic limits)(?=[.!?;]|$)', ' ', scope, flags=re.I)
    if re.search(r'(?:^|[.!?;]\s*|\b(?:and|also|then)\s+)(?:please\s+)?(?:state|describe|identify|report|assess|verify|check|tell|confirm)\b', remainder, re.I):
        return None
    return scope
