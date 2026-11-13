"""Question scope for symptom confirmation versus soil biosecurity.

These predicates select a response obligation, never establish a diagnosis.
Reported disease history can justify soil-movement precautions without current
symptoms in the rotation crop or a demand for another symptomatic plant sample.
"""
from __future__ import annotations

import re


def clubroot_confirmation_requested(question: str) -> bool:
    text = " ".join(question.casefold().split())
    text = re.sub(r"\b(?:no|without)\s+(?:visible\s+)?(?:galls?|swollen roots?)\b|\broots? (?:are|look) not swollen\b", "", text)
    return bool(re.search(
        r"\b(?:swollen roots?|roots?\s+(?:are|look|appear)\s+swollen|galls?|dying patch)\b|\bclubroot\s*\?|"
        r"\b(?:enough to confirm|confirm (?:the )?clubroot|diagnos(?:e|ing) clubroot|"
        r"is (?:this|that|it) (?:really )?clubroot)\b", text,
    ))


def clubroot_short_rotation_requested(question: str) -> bool:
    return bool(re.search(r"\b(?:one|1|single)\s+(?:(?:non[- ]?host|rotation)\s+)?year\b", question, re.I))
