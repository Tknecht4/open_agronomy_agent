"""Bind water and calibration arithmetic to supplied quantities and units."""
from __future__ import annotations

import re
from typing import Any

from agronomy_agent.supplied_math_scope import supplied_math_scope, has_unlabelled_numeric_alternatives
from agronomy_agent.water_arithmetic import validate_water_arithmetic_inputs
from agronomy_agent.agronomic_calculations import validate_single_nozzle_inputs
from agronomy_agent.calculator_contracts import supplied_input_label

from agronomy_agent.supplied_numeric_inputs import NUMBER as _NUMBER, supplied_numeric_gaps, extended_unit


def _value(text: str, *patterns: str, bindings: list[re.Match[str]]) -> str | None:
    matches = [m for pattern in patterns for m in re.finditer(pattern, text, re.I)]
    bindings.extend(matches)
    if any(extended_unit(match) for match in matches if match.end() != match.end('quantity')):
        return None
    for match in matches:
        tail = text[match.end():]
        alternative = re.match(rf'\s*(?P<join>or|and|to)\s*{_NUMBER}', tail, re.I)
        if alternative is None:
            continue
        if alternative['join'].lower() != 'and' or match.end('quantity') == match.end():
            return None
        # Coordinated operands of different roles are not conflicting values:
        # net depth and efficiency, for example, have different dimensions.
        unit = re.search(r'(mm/day|L/min|km/h|mm|m)$', match.group(), re.I)
        if unit and re.match(rf'\s*{re.escape(unit[1])}\b', tail[alternative.end():], re.I):
            return None
    values = {m['quantity'].replace(',', '') for m in matches}
    return next(iter(values)) if len(values) == 1 else None


def parse_supplied_water_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    text = supplied_math_scope(question)
    if text is None:
        return None
    parsed = _water_storage(text) or _crop_et(text) or _gross_depth(text) or _depth_volume(text) or _nozzle_volume(text)
    if parsed is not None and has_unlabelled_numeric_alternatives(text):
        return parsed[0], parsed[1], parsed[2] + ('invalid alternatives: supply one quantity for each named role',)
    if parsed is not None and not parsed[2]:
        try:
            if parsed[0] == 'single_nozzle_application_volume':
                validate_single_nozzle_inputs(parsed[1])
            else:
                validate_water_arithmetic_inputs(parsed[0], parsed[1])
        except ValueError as error:
            return parsed[0], parsed[1], ('invalid ' + str(error),)
    return parsed


def _bound(operation: str, values: dict[str, Any], text: str, bindings: list[re.Match[str]]):
    missing = tuple(("measured volumetric water content" if values.get('interpretation') == 'refill_deficit' else "wilting point as a volumetric fraction")
                    if key == 'lower_volumetric' else supplied_input_label(key)
                    for key, value in values.items() if value is None)
    return operation, {key: value for key, value in values.items() if value is not None}, missing + supplied_numeric_gaps(text, bindings)


def _water_storage(text: str):
    bindings = []
    if not re.search(r'\b(?:available water|water needed to refill|refill (?:water|storage)|water deficit)\b', text, re.I):
        return None
    if not re.search(r'\buniform\b', text, re.I) or re.search(r'\b(?:gravimetric|mass basis|layers|zones)\b|kg/kg|g/g|%', text, re.I):
        return None
    upper = _value(text, rf'\b(?:target )?field capacity\s*(?:is|of|:|=)?\s*(?P<quantity>{_NUMBER})(?![\d%]|\.\d)', bindings=bindings)
    refill = bool(re.search(r'\b(?:refill|deficit)\b', text, re.I))
    lower = _value(text, rf'\b' + (r'(?:measured )?volumetric water' if refill else r'(?:permanent )?wilting point') + rf'\s*(?:is|of|:|=)?\s*(?P<quantity>{_NUMBER})(?![\d%]|\.\d)', bindings=bindings)
    depth_m = _value(text, rf'\b(?:rooting|root[- ]zone) depth\s*(?:is|of|:|=)?\s*(?P<quantity>{_NUMBER})\s*m\b',
                     rf'(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*m\s+root[- ]zone\b', bindings=bindings)
    return _bound('water_storage_difference', {'upper_volumetric': upper, 'lower_volumetric': lower, 'root_depth_m': depth_m,
                  'interpretation': 'refill_deficit' if refill else 'available_capacity'}, text, bindings)


def _crop_et(text: str):
    bindings = []
    if not re.search(r'\bETc\s*=\s*Kc\s*[×*]\s*ETo\b', text, re.I):
        return None
    if re.search(r'\b(?:stress(?:ed)?|drought|water[- ]limited|salin\w*|Ks|Kcb|Ke|adjusted)\b', text, re.I):
        return None
    coefficient = _value(text, rf'\bKc\s*(?:is|of|:|=)\s*(?P<quantity>{_NUMBER})(?![\d%]|\.\d)', bindings=bindings)
    reference = _value(text, rf'\bETo\s*(?:is|of|:|=)\s*(?P<quantity>{_NUMBER})\s*mm\s*/\s*day\b', bindings=bindings)
    return _bound('crop_evapotranspiration', {'crop_coefficient': coefficient, 'reference_et_mm_per_day': reference}, text, bindings)


def _gross_depth(text: str):
    bindings = []
    if not re.search(r'\bgross (?:irrigation )?depth\b', text, re.I):
        return None
    net = _value(text, rf'(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*mm\s+net (?:irrigation|depth)\b',
                 rf'\bnet (?:irrigation )?depth\s*(?:is|of|:|=)\s*(?P<quantity>{_NUMBER})\s*mm\b', bindings=bindings)
    efficiency = _value(text, rf'(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*%\s+(?:application )?efficiency\b',
                        rf'(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*%\s+(?:and|or)\s+{_NUMBER}\s*%\s+(?:application )?efficiency\b', bindings=bindings)
    return _bound('gross_irrigation_depth', {'net_depth_mm': net, 'application_efficiency_pct': efficiency}, text, bindings)


def _depth_volume(text: str):
    bindings = []
    if not re.search(r'\b(?:cubic met(?:re|er)s|m[³3])\b', text, re.I) or not re.search(r'\buniformly\b', text, re.I):
        return None
    depth = _value(text, rf'(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*mm\b', bindings=bindings)
    area = _value(text, rf'\bover\s+(?P<quantity>{_NUMBER})\s*(?:ha|hectares?)\b', bindings=bindings)
    return _bound('water_depth_volume', {'depth_mm': depth, 'area_ha': area}, text, bindings)


def _nozzle_volume(text: str):
    bindings = []
    if not re.search(r'\ba nozzle\b', text, re.I) or not re.search(r'\bapplication volume\b', text, re.I):
        return None
    if re.search(r'\b(?:nozzles|band|bands|orchard|airblast)\b', text, re.I):
        return None
    flow = _value(text, rf'\bnozzle\s+(?:delivers|flows at)\s+(?P<quantity>{_NUMBER})\s*L/min\b', bindings=bindings)
    speed = _value(text, rf'\b(?:travel )?speed\s*(?:is|of|:|=)?\s*(?P<quantity>{_NUMBER})\s*km/h\b', bindings=bindings)
    spacing = _value(text, rf'\bnozzle spacing\s*(?:is|of|:|=)?\s*(?P<quantity>{_NUMBER})\s*m\b', bindings=bindings)
    # Preserve spacing as spacing; neither whole-boom width nor total nozzle
    # count is a supplied fact. Do not ignore a conflicting formula.
    formulas = list(re.finditer(r'\bL/ha\s*=', text, re.I))
    valid = list(re.finditer(r'\bL/ha\s*=\s*600(?:\.0+)?\s*Q\s*/\s*\(\s*speed\s*[×*]\s*spacing\s*\)(?=\s*(?:[,.;!?]|$|calculate\b))', text, re.I))
    missing = ('invalid supplied nozzle formula: use 600Q/(speed × spacing) with L/min, km/h and metres',) if len(valid) != len(formulas) else ()
    bindings.extend(valid)
    operation, values, absent = _bound('single_nozzle_application_volume', {'flow_l_per_min_per_nozzle': flow, 'speed_km_per_h': speed, 'nozzle_spacing_m': spacing}, text, bindings)
    return operation, values, absent + missing
