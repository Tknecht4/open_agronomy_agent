"""Whole-request ownership for supplied TAW × allowable-depletion arithmetic.

FAO-56 RAW = p × TAW supplies the no-stress relationship, never field-specific p.
An arbitrary management allowance uses the same product without proving RAW.
This module only binds explicit data roles and the requested calculation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from agronomy_agent.supplied_numeric_inputs import NUMBER


@dataclass(frozen=True)
class SuppliedDepletionRequest:
    total_available_water_mm: str | None
    depletion_fraction: str | None


def supplied_depletion_request(question: str) -> SuppliedDepletionRequest | None:
    """Consume the entire calculation and a bounded explanation of its limits.

    Missing operands stay missing. Unknown actions, extra quantities, alternate
    values and other questions cannot inherit a supplied-arithmetic bypass.
    """
    text = ' '.join(question.split())
    total = rf'(?P<taw>{NUMBER})\s*mm'
    fraction = rf'(?P<fraction>{NUMBER})\s*(?P<percent>%?)'
    taw_role = r'(?:total available (?:soil )?water|TAW)'
    p_role = r'(?:supplied )?(?:allowable depletion fraction|depletion fraction|p)'
    assignment = r'\s*(?:is|of|=|:)?\s*'
    request = r'(?:(?:what is|calculate|compute|work out)\s+(?:the\s+)?(?:depletion trigger|allowable depletion|readily available (?:soil )?water|RAW))'
    limits = (r'(?:,?\s+and\s+why is (?:it|this|that)\s+(?:crop/context|crop and context|crop[- ] and context)[- ]dependent'
              r'|[.!?]\s*explain (?:its|the) (?:limits|limitations|boundaries))?')
    context = (
        rf'(?:an?|the)\s+(?:(?:teaching|hypothetical|example)\s+)?root[- ]zone\s+(?:holds|has|contains)\s+{total}\s+{taw_role}'
        rf'(?:\s+and\s+(?:allows|uses|assumes)\s+{fraction}\s+(?:allowable\s+)?depletion)?',
        rf'{taw_role}{assignment}{total}(?:\s*(?:,|and)\s*{p_role}{assignment}{fraction})?',
    )
    for premise in context:
        match = re.fullmatch(rf'\s*{premise}[.!;]?\s+{request}{limits}[.!?]*\s*', text, re.I)
        if match:
            raw = match['fraction']
            value = None if raw is None else Decimal(raw.replace(',', ''))
            if value is not None and match['percent']:
                value /= 100
            return SuppliedDepletionRequest(match['taw'].replace(',', ''), None if value is None else str(value))
    # A named supplied fraction without TAW needs the missing capacity; no crop
    # table or assumed rooting depth can supply it implicitly.
    match = re.fullmatch(rf'\s*{p_role}{assignment}{fraction}[.!;]?\s+{request}{limits}[.!?]*\s*', text, re.I)
    if match:
        value = Decimal(match['fraction'].replace(',', ''))
        if match['percent']:
            value /= 100
        return SuppliedDepletionRequest(None, str(value))
    return None
