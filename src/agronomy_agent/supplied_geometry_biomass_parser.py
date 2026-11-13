"""Supplied dry-biomass ratios and planar sampling geometry, without field targets."""
from __future__ import annotations

import re
from typing import Any

from agronomy_agent.agronomic_calculations import (
    validate_circular_sampling_area_inputs, validate_grain_harvest_index_inputs,
)
from agronomy_agent.calculator_contracts import supplied_input_label
from agronomy_agent.supplied_math_scope import supplied_math_scope, has_unlabelled_numeric_alternatives

_NUMBER = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
_MASS = rf"(?P<value>{_NUMBER})\s*(?P<unit>kg|tonnes?|t|pounds?|lbs?)\b(?:\s*(?:/|per\s+)(?P<area>ha|hectares?|ac|acres?)\b)?(?!\s*(?:/|per\b))"


def _one(rows, *, units=False):
    if units:
        values = set()
        for match in rows:
            unit = match['unit'].lower()
            unit = 't' if unit.startswith('t') else 'kg' if unit == 'kg' else 'lb'
            area = match['area']
            values.add(unit + ('/' + ('ha' if area.lower().startswith('h') else 'ac') if area else ''))
    else:
        values = {match['value'].replace(',', '') for match in rows}
    return next(iter(values)) if len(values) == 1 else None


def parse_supplied_geometry_biomass_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    # This one closed explanatory suffix is answered by the geometry result's
    # boundary. All preceding text, and any other follow-up, remains in scope.
    text = re.sub(r'\s*Explain why (?:it|this) is not (?:the )?(?:farm )?field area[.!?]?\s*$', '', question, flags=re.I)
    scope = supplied_math_scope(text)
    if scope is None:
        return None
    parsed = _harvest_index(scope) or _circle(scope)
    if parsed is None:
        return None
    operation, values, missing = parsed
    # The suffix cannot silently vanish from a different operation.
    if text != question and operation != 'circular_sampling_area':
        return None
    if has_unlabelled_numeric_alternatives(scope) or re.search(rf'\b(?:or|to)\s*{_NUMBER}', scope, re.I):
        missing += ('invalid alternatives: supply one value for each named role',)
    if not missing:
        try:
            {'grain_harvest_index': validate_grain_harvest_index_inputs,
             'circular_sampling_area': validate_circular_sampling_area_inputs}[operation](values)
        except ValueError as error:
            missing += ('invalid ' + str(error),)
    return operation, values, missing


def _harvest_index(text):
    if not re.search(r'\b(?:harvest index|HI)\b', text, re.I):
        return None
    if re.search(r"\b(?:wet|fresh|root|tuber|below[- ]ground|excluding|without grain|straw only|not includ(?:e[ds]?|ing)|doesn't include|does not include)\b|\bgrain\b[^.!?;]{0,35}\bnot (?:included|part)\b", text, re.I):
        return None
    grain = list(re.finditer(_MASS + r'\s+(?:of\s+)?grain dry (?:mass|matter)\b', text, re.I))
    grain += list(re.finditer(r'\bgrain dry (?:mass|matter)\s*(?:is|of|:|=)\s*' + _MASS, text, re.I))
    total_role = r'total above[- ]ground dry (?:biomass|mass|matter)'
    total = list(re.finditer(_MASS + rf'\s+(?:of\s+)?{total_role}\b', text, re.I))
    total += list(re.finditer(rf'\b{total_role}\s*(?:is|of|:|=)\s*' + _MASS, text, re.I))
    units = {_one(rows, units=True) for rows in (grain, total)}
    values = {'grain_dry_mass': _one(grain), 'aboveground_dry_mass': _one(total),
              'mass_unit': next(iter(units)) if len(units) == 1 and None not in units else None}
    return _bound('grain_harvest_index', values)


def _circle(text):
    if not re.search(r'\b(?:circular|circle)\b', text, re.I) or not re.search(r'\bsampling (?:buffer|circle|area|plot)\b', text, re.I):
        return None
    if not re.search(r'\barea\b', text, re.I) or re.search(r'\b(?:diameter|annulus|ring|geodesic|slope|terrain|circumference|perimeter|polygon|semicircl\w*|semicircular|half|quarter|partial|sector|ellips\w*|elliptical|square|rectang\w*|noncircular)\b', text, re.I):
        return None
    rows = list(re.finditer(rf'(?<![\w.,+-])(?P<value>{_NUMBER})\s*m(?:etre|eter)?s?[- ]radius\b', text, re.I))
    rows += list(re.finditer(rf'\bradius\s*(?:is|of|:|=)?\s*(?P<value>{_NUMBER})\s*(?:m|metres?|meters?)\b', text, re.I))
    return _bound('circular_sampling_area', {'radius_m': _one(rows)})


def _bound(operation, values):
    return operation, {key:value for key,value in values.items() if value is not None}, tuple(
        supplied_input_label(key) for key,value in values.items() if value is None)
