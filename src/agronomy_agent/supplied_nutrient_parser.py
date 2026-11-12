"""Extract three bounded, supplied-input arithmetic families.

No operand comes from a retrieved passage, a model answer or an assumed field
condition. Conflicting quantities and mixed nutrient bases need clarification.
Operational follow-up requests must continue through the normal agent path.
"""
from __future__ import annotations

import re
from typing import Any
from agronomy_agent.agronomic_calculations import validate_supplied_nutrient_inputs

_NUMBER = r"[+-]?(?:\d+(?:,\d{3})*)(?:\.\d+)?"
_BASIS = r"P2O5|K2O|N|P|K"


def _one(matches: list[re.Match[str]], group: str) -> str | None:
    # Repeated identical premises are fine; conflicting operands are not.
    values = {m[group].replace(",", "") for m in matches}
    return next(iter(values)) if len(values) == 1 else None


def parse_supplied_nutrient_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    text = " ".join(question.translate(str.maketrans("₂₅−", "25-")).split())
    if not re.search(r"\b(?:calculate|compute|convert|how many)\b", text, re.I):
        return None
    if re.match(r"(?:why|explain|define|how (?:does|do))\b", text, re.I):
        return None
    # Only a closed exclusion of requested output categories is ignored. A
    # later sentence/imperative still participates in the whole-request check.
    scope = re.sub(r",?\s+not a recommended rate(?: or carrier[- ]water volume)?(?=[.!?]|$)", "", text, flags=re.I)
    if re.search(
        r"\b(?:should|may|can|could|would|must|legal|permitted|authorize|recommend|recommended|"
        r"safe to|safety|label|mixing order|re[- ]entry|withholding|today|tomorrow|allowed|approved|"
        r"permissible|choose|select|decide|advise|apply|applying|spray|spraying|irrigate)\b|"
        r"\b(?:which|what)\s+(?:product|rate|crop|treatment)\b|"
        r"\b(?:then|also|and)\s+(?:please\s+)?(?:apply|spray|use|mix|irrigate)\b|"
        r"(?:^|[.!?;])\s*(?:please\s+)?(?:apply|spray|use|mix|irrigate)\b",
        scope, re.I,
    ):
        return None
    other_question = re.sub(r"^how many\b", "", scope, flags=re.I)
    if re.search(r"\b(?:what|which|when|where|who|why|how)\b", other_question, re.I):
        return None
    if re.search(r"\bexplain\b(?!\s+(?:its|the|their)\s+(?:limits|limitations|boundaries)\b)", scope, re.I):
        return None
    # Do not consume a second unrelated arithmetic or decision question.
    if re.search(r"\b(?:and|also|then)\s+(?:calculate|compute|convert|choose|select|decide)\b", scope, re.I):
        return None
    parsed = _basis_conversion(scope) or _nutrient_balance(scope) or _liquid_total(scope)
    if parsed is not None and not parsed[2]:
        operation, values, missing = parsed
        try:
            validate_supplied_nutrient_inputs(operation, values)
        except ValueError as error:
            return operation, values, ("invalid " + str(error),)
    return parsed


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
    missing = tuple(key for key, value in values.items() if value is None)
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
    missing = tuple(key for key, value in values.items() if value is None)
    if re.search(r"\b(?:carrier|water|tank)\b", text, re.I) and not re.search(r"\bdistinguish\b", text, re.I):
        return None
    return "liquid_product_total", {key: value for key, value in values.items() if value is not None}, missing
