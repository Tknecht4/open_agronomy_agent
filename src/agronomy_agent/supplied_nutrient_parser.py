"""Extract bounded nutrient and product arithmetic from supplied inputs.

No operand comes from a retrieved passage, a model answer or an assumed field
condition. Conflicting quantities and mixed nutrient bases need clarification.
Operational follow-up requests must continue through the normal agent path.
"""
from __future__ import annotations

import re
from typing import Any
from agronomy_agent.agronomic_calculations import validate_supplied_nutrient_inputs, validate_fertilizer_product_mass_inputs
from agronomy_agent.supplied_math_scope import supplied_math_scope
from agronomy_agent.calculator_contracts import supplied_input_label

_NUMBER = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
_BASIS = r"P2O5|K2O|N|P|K"


def _one(matches: list[re.Match[str]], group: str) -> str | None:
    # Repeated identical premises are fine; conflicting operands are not.
    if group in {'quantity', 'factor'} and any(re.match(rf'\s*(?:or|to)\s*{_NUMBER}', m.string[m.end():], re.I) for m in matches):
        return None
    values = {m[group].replace(",", "") for m in matches}
    return next(iter(values)) if len(values) == 1 else None


def parse_supplied_nutrient_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    scope = supplied_math_scope(question)
    if scope is None:
        return None
    parsed = _basis_conversion(scope) or _nutrient_balance(scope) or _liquid_total(scope) or _product_mass(scope)
    if parsed is not None and not parsed[2]:
        operation, values, missing = parsed
        try:
            if operation == 'fertilizer_product_mass':
                validate_fertilizer_product_mass_inputs(values)
            else:
                validate_supplied_nutrient_inputs(operation, values)
        except ValueError as error:
            return operation, values, ("invalid " + str(error),)
    return parsed


def _product_mass(text: str):
    if not re.search(r'\b(?:how much|calculate|compute)\b', text, re.I) or not re.search(r'\b(?:blend|fertili[sz]er|product)\b', text, re.I):
        return None
    if not re.search(r'\bsuppl(?:y|ies)\b', text, re.I):
        return None
    targets = list(re.finditer(rf'\bsuppl(?:y|ies)\s+(?P<quantity>{_NUMBER})\s*kg\s*(?P<basis>{_BASIS})\s*/\s*ha\b', text, re.I))
    if not targets:
        return None
    target = _one(targets, 'quantity');basis = _one(targets, 'basis')
    percentages = list(re.finditer(rf'(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*%\s*[- ]?\s*(?P<basis>{_BASIS})\b', text, re.I))
    matching = [m for m in percentages if basis and m['basis'].upper() == basis.upper()]
    percent = _one(matching, 'quantity')
    values = {'nutrient_target_kg_per_ha': target, 'nutrient_percent': percent, 'nutrient_label': basis.upper() if basis else None}
    return 'fertilizer_product_mass', {k:v for k,v in values.items() if v is not None}, tuple(supplied_input_label(k) for k,v in values.items() if v is None)


def _basis_conversion(text: str):
    if not re.search(r"\bconvert\b", text, re.I):
        return None
    amounts = list(re.finditer(rf"\bconvert\s+(?P<quantity>{_NUMBER})\s*kg\s*(?P<basis>{_BASIS})\s*/\s*ha\b", text, re.I))
    target = re.search(r"\bto\s+(?:kg\s*)?(?:elemental\s+)?(?P<basis>phosphorus|potassium|P2O5|K2O|P|K)(?:\s*/\s*ha)?\b", text, re.I)
    if not amounts or not target:
        return None
    quantity = _one(amounts, "quantity")
    basis = _one(amounts, "basis")
    destination = {"phosphorus": "P", "potassium": "K"}.get(target["basis"].lower(), target["basis"].upper())
    values = {"quantity_kg_per_ha": quantity, "from_basis": basis.upper() if basis else None, "to_basis": destination}
    missing = tuple(supplied_input_label(key) for key, value in values.items() if value is None)
    # A supplied factor must be attached to the same destination/source
    # relation. Never silently discard a conflicting or unrecognized factor.
    equations = list(re.finditer(rf"\b(?P<to>{_BASIS})\s*=\s*(?P<factor>{_NUMBER})\s*[×*]\s*(?P<from>{_BASIS})\b", text, re.I))
    if equations:
        if any(m["from"].upper() != values["from_basis"] or m["to"].upper() != destination for m in equations):
            missing += ("invalid conversion equation: use the requested source and destination bases",)
        factor = _one(equations, "factor")
        if factor is None:
            missing += ("invalid conflicting conversion factors",)
        else:
            values["factor"] = factor
    elif re.search(r"[=×*]|\bfactor\b", text):
        missing += ("one explicit destination = factor × source conversion equation",)
    return "nutrient_basis_conversion", {key: value for key, value in values.items() if value is not None}, missing


def _nutrient_balance(text: str):
    if not re.search(r"\b(?:apparent )?(?:nutrient )?balance\b", text, re.I):
        return None
    amounts = list(re.finditer(rf"(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*kg\s*(?P<basis>{_BASIS})\s*/\s*ha\s+(?P<role>applied|removed)\b", text, re.I))
    if not amounts:
        return None
    values: dict[str, Any] = {}
    missing = []
    bases = {m["basis"].upper() for m in amounts}
    if len(bases) != 1:
        missing.append("invalid mixed nutrient bases: convert both amounts to the same basis first")
    else:
        values["nutrient_basis"] = next(iter(bases))
    for role in ("applied", "removed"):
        value = _one([m for m in amounts if m["role"].lower() == role], "quantity")
        if value is None:
            missing.append(f"one unambiguous {role} quantity in kg nutrient/ha")
        else:
            values[role + "_kg_per_ha"] = value
    # Additional flow terms cannot disappear into a two-term balance.
    if re.search(r"\b(?:deposition|leaching|runoff|erosion|fixation|mineralization|credit|manure|soil supply)\b", text, re.I):
        return None
    return "apparent_nutrient_balance", values, tuple(missing)


def _liquid_total(text: str):
    if not re.search(r"\b(?:product (?:quantity|volume)|(?:total )?product)\b", text, re.I):
        return None
    rates = list(re.finditer(rf"(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*L\s+product\s*/\s*ha\b", text, re.I))
    areas = list(re.finditer(rf"(?<![\w.,+-])(?P<quantity>{_NUMBER})\s*(?:ha|hectares?)\b", text, re.I))
    # The denominator in a rate is not a separate area operand.
    areas = [m for m in areas if not any(r.start() <= m.start() < r.end() for r in rates)]
    if not rates:
        return None
    values = {"area_ha": _one(areas, "quantity"), "product_rate_l_per_ha": _one(rates, "quantity")}
    missing = tuple(supplied_input_label(key) for key, value in values.items() if value is None)
    if re.search(r"\b(?:carrier|water|tank)\b", text, re.I) and not re.search(r"\bdistinguish\b", text, re.I):
        return None
    return "liquid_product_total", {key: value for key, value in values.items() if value is not None}, missing
