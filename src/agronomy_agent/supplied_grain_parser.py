"""Bind explicitly wet-basis grain mass accounting without choosing targets."""
from __future__ import annotations

import re
from typing import Any

from agronomy_agent.agronomic_calculations import validate_grain_moisture_inputs
from agronomy_agent.supplied_math_scope import supplied_math_scope
from agronomy_agent.calculator_contracts import supplied_input_label

_NUMBER = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"


def parse_supplied_grain_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    text = supplied_math_scope(question)
    if text is None or not re.search(r'\bgrain\b', text, re.I) or not re.search(r'\bwet[- ]basis moisture\b', text, re.I):
        return None
    if not re.search(r'\bequivalent (?:grain )?mass\b', text, re.I):
        return None
    if re.search(r'\b(?:dry[- ]basis|handling losses|shrink schedule|fees|grade|storage recommendation)\b', text, re.I):
        return None
    masses = list(re.finditer(rf'\bgrain (?:mass|yield)\s*(?:is|of|:|=)?\s*(?P<value>{_NUMBER})\s*(?P<unit>kg|tonnes?|t|pounds?|lbs?)\b'
                             r'(?:\s*(?:/|per\s+)(?P<area>ha|hectares?|ac|acres?)\b)?(?!\s*(?:/|per\b))', text, re.I))
    initial = list(re.finditer(rf'(?<![\w.,+-])(?P<value>{_NUMBER})\s*%\s+wet[- ]basis moisture\b', text, re.I))
    target = list(re.finditer(rf'\bequivalent (?:grain )?mass\s+at\s+(?P<value>{_NUMBER})\s*%\s+moisture\b', text, re.I))
    def one(rows):
        values = {m['value'].replace(',', '') for m in rows}
        return next(iter(values)) if len(values) == 1 else None
    def mass_unit(match):
        unit = match['unit'].lower();unit = 't' if unit.startswith('t') else 'kg' if unit == 'kg' else 'lb'
        area = match['area']
        return unit + ('/' + ('ha' if area.lower().startswith('h') else 'ac') if area else '')
    units = {mass_unit(m) for m in masses}
    values = {'wet_mass': one(masses), 'mass_unit': next(iter(units)) if len(units) == 1 else None,
              'initial_moisture_pct': one(initial), 'target_moisture_pct': one(target)}
    missing = tuple(supplied_input_label(key) for key, value in values.items() if value is None)
    values = {key:value for key,value in values.items() if value is not None}
    if not missing:
        try:
            validate_grain_moisture_inputs(values)
        except ValueError as error:
            missing = ('invalid ' + str(error),)
    return 'grain_moisture_adjustment', values, missing
