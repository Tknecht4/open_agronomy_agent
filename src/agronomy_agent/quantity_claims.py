"""Bounded quantity identity and container-total checks for draft review.

This is a screening contract, not a general mathematical or semantic verifier.
A mentioned quantity is not proof of its relation to an entity or of authority
for an action. Only an unambiguous, explicitly requested container mass total is
derived here. Other calculations need a typed calculation result in evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

_NUM = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
_UNIT = (
    r"kg\s*/\s*ha|lb(?:s)?\s*/\s*(?:acre|ac)|bu\s*/\s*acre|mg\s*/?\s*L|km\s*/?\s*h|"
    r"kilograms?|kg|milligrams?|mg|grams?|g|pounds?|lbs?|ounces?|oz|tonnes?|"
    r"millilitres?|milliliters?|litres?|liters?|mL|L|gallons?|quarts?|hectares?|ha|"
    r"ppm|ppb|kPa|MPa|Pa|mph|mm|cm|inches?|feet|ft|days?|hours?|acres?|%|°?[CF]"
)
NUMBER_RE = re.compile(
    rf"(?<![\w.,])(?P<number>{_NUM})(?:\s*(?:-|–|to)\s*(?P<upper>{_NUM}))?"
    rf"(?:\s*(?P<unit>[A-Za-z°%]+\s*/\s*[A-Za-z0-9²³]+|{_UNIT})(?![\w/])"
    rf"|(?P<opaque_unit>[A-Za-z][A-Za-z0-9/²³]*))?(?!\w|[.,]\d)", re.IGNORECASE,
)
_ALIASES = {
    "kilogram": "kg", "kilograms": "kg", "gram": "g", "grams": "g",
    "pound": "lb", "pounds": "lb", "lbs": "lb", "ounce": "oz", "ounces": "oz",
    "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "inch": "inches", "foot": "ft", "feet": "ft", "day": "days", "hour": "hours",
    "acre": "acres", "tonne": "tonnes", "lbs/acre": "lb/ac", "lb/acre": "lb/ac",
    "hectare": "ha", "hectares": "ha", "gallon": "gallons", "quart": "quarts",
    "millilitre": "ml", "millilitres": "ml", "milliliter": "ml", "milliliters": "ml",
    "milligram": "mg", "milligrams": "mg",
}
_CONTAINERS = r"bags?|boxes|box|sacks?|packs?|packages?|bales?|containers?"


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    upper: Decimal | None
    unit: str


def _quantity(match: re.Match[str]) -> Quantity:
    unit = re.sub(r"\s+", "", match.group("unit") or match.group("opaque_unit") or "").lower()
    return Quantity(
        Decimal(match.group("number").replace(",", "")),
        Decimal(match.group("upper").replace(",", "")) if match.group("upper") else None,
        _ALIASES.get(unit, unit),
    )


def _container_total(question: str, evidence: str) -> tuple[Decimal, Decimal, Quantity] | None:
    """Admit one count and one per-container mass, without unit conversion.

    Derivation is restricted to a total-mass question with explicit premises.
    Conflicting or multiple counts/masses remain unresolved, never guessed.
    """
    if not re.search(r"\btotal (?:mass|weight)\b", question, re.IGNORECASE):
        return None
    # Bind the operands inside one explicit question phrase. Do not join a
    # count from the question to a per-container mass from another source/group.
    phrase = re.compile(
        rf"(?<![\w.,])(?P<count>{_NUM})\s+(?:{_CONTAINERS})\s+"
        rf"(?:weighing|at|of)\s+(?P<number>{_NUM})\s*"
        rf"(?P<unit>kilograms?|kg|grams?|g|pounds?|lbs?|ounces?|oz|tonnes?)\s+(?:each|apiece)\b",
        re.IGNORECASE,
    )
    phrases = list(phrase.finditer(question))
    if len(phrases) != 1:
        return None
    match = phrases[0]
    count = Decimal(match.group("count").replace(",", ""))
    mass = Decimal(match.group("number").replace(",", ""))
    unit = match.group("unit").lower()
    unit = _ALIASES.get(unit, unit)
    if count <= 0 or count != count.to_integral_value() or mass <= 0:
        return None
    for text in (question, evidence):
        mentions = list(re.finditer(rf"(?<![\w.,])({_NUM})\s+(?:{_CONTAINERS})\b", text, re.I))
        if len(mentions) > 1 or any(Decimal(m.group(1).replace(",", "")) != count for m in mentions):
            return None
        # Evidence may veto conflicting premises; it cannot supply a missing
        # operand. Only explicitly per-container quantities are compared here.
        for qmatch in NUMBER_RE.finditer(text):
            q = _quantity(qmatch)
            before = text[max(0, qmatch.start() - 45):qmatch.start()]
            after = text[qmatch.end():qmatch.end() + 25]
            per_container = re.match(rf"\s+(?:each\b|per (?:{_CONTAINERS})\b)", after, re.I) or re.search(
                rf"\beach (?:{_CONTAINERS})\s+(?:weighs?|has a mass of)\s*$", before, re.I,
            )
            if per_container and q != Quantity(mass, None, unit):
                return None
    return count, mass, Quantity(count * mass, None, unit)


def unsupported_quantities(answer: str, *, question: str, evidence: str) -> tuple[str, ...]:
    allowed = {_quantity(m) for m in NUMBER_RE.finditer(f"{question}\n{evidence}")}
    derived = _container_total(question, evidence)
    grounded_operand_spans: list[tuple[int, int]] = []
    if derived:
        count, mass, result = derived
        for equation in re.finditer(rf"(?<![\w.,])({_NUM})\s*[×*]\s*({_NUM})\s*=\s*({_NUM})(?!\w|[.,]\d)", answer):
            a, b, total = (Decimal(v.replace(",", "")) for v in equation.groups())
            if sorted([a, b]) == sorted([count, mass]) and total == result.value:
                grounded_operand_spans.extend((equation.span(1), equation.span(2)))
    values: list[str] = []
    for match in NUMBER_RE.finditer(answer):
        q = _quantity(match)
        prefix = answer[max(0, match.start() - 80):match.start()]
        suffix = answer[match.end():match.end() + 40]
        # Reporting a number explicitly as erroneous is not endorsing it.
        # No broad 'not' exemption: 'not less than 20' is still a numeric claim.
        reported_error = bool(re.match(r"\s+is\s+(?:an?\s+)?(?:error|incorrect|wrong)\b", suffix, re.IGNORECASE))
        if reported_error:
            continue
        total_assertion = bool(re.search(r"\btotal(?:\s+(?:mass|weight))?\s*(?:is|=|:)\s*$", prefix, re.IGNORECASE))
        equation = re.search(rf"(?<![\w.,])({_NUM})\s*[×*]\s*({_NUM})\s*=\s*$", prefix)
        if derived and (total_assertion or equation):
            count, mass, result = derived
            valid = q.upper is None and q.value == result.value and q.unit in {"", result.unit}
            if equation:
                operands = [Decimal(v.replace(",", "")) for v in equation.groups()]
                valid = valid and sorted(operands) == sorted([count, mass])
            if not valid:
                values.append(match.group().strip())
            continue
        # Omitting a unit must not turn an unfamiliar unit suffix into a
        # supported magnitude. Bare operands are admitted only in the checked
        # equation; ordinary scalar references require scalar source evidence.
        supported = q in allowed or (not q.unit and match.span() in grounded_operand_spans)
        if not supported:
            values.append(match.group().strip())
    return tuple(dict.fromkeys(values))
