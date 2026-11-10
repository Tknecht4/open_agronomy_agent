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
    r"ppm|ppb|kPa|MPa|Pa|mph|mm|cm|inches?|feet|ft|days?|hours?|acres?|"
    r"per\s+cent|pour\s+cent|percent|%|°?[CF]"
)
NUMBER_RE = re.compile(
    rf"(?<![\w.,])(?P<number>{_NUM})(?:\s*(?:-|–|to|à)\s*(?P<upper>{_NUM}))?"
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
    "percent": "%", "pourcent": "%",
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



def _scientific_notation(text: str) -> tuple[str, set[str]]:
    """Normalize a bounded vocabulary of charges/exponents, never magnitudes.

    Whole ion/unit identity must occur in the supplied material. Annotation
    digits cannot authorize scalar quantities. This is typography equivalence,
    not a chemical correctness or general unit-conversion check.
    """
    text = re.sub(r"\\(?:text|mathrm)\{\s*([A-Za-z][A-Za-z0-9]*)\s*\}", r"\1", text)
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+", lambda m: "^" + m.group().translate(
        str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")), text)
    text = re.sub(r"\^\s*\{\s*([+-]?\d+[+-]?|[+-])\s*\}", r"^\1", text)
    text = text.replace("−", "-")
    annotations: set[str] = set()
    digits = str.maketrans("0123456789+-", "abcdefghijpm")
    def ion(m: re.Match[str]) -> str:
        token = m.group('ion') + m.group('charge')
        annotations.add(token)
        return "ion" + token.translate(digits)
    text = re.sub(r"(?<![A-Za-z0-9])(?P<ion>NH4|NO3|SO4|PO4|Al|Ca|Mg|Na|K|H)"
                  r"\^?(?P<charge>\d*[+-])(?![\w+-])", ion, text)
    def exponent(m: re.Match[str]) -> str:
        token = m.group('unit') + '^' + m.group('exp')
        annotations.add(token)
        return m.group('unit') + 'power' + m.group('exp').translate(digits)
    text = re.sub(r"(?<![A-Za-z0-9])(?P<unit>kg|cm|mm|ha|mol|mg|g|m|s|L)"
                  r"(?:\^(?P<exp>[+-]?\d+)|(?P<plain>-[123]))(?!\w|\.\d)",
                  lambda m: exponent(m) if m.group('exp') is not None else
                  _plain_unit_exponent(m, annotations, digits), text)
    return text, annotations


def _plain_unit_exponent(match: re.Match[str], annotations: set[str], digits: dict) -> str:
    exp = match.group('plain')
    annotations.add(match.group('unit') + '^' + exp)
    return match.group('unit') + 'power' + exp.translate(digits)


def unsupported_quantities(answer: str, *, question: str, evidence: str) -> tuple[str, ...]:
    normalized_source, source_annotations = _scientific_notation(f"{question}\n{evidence}")
    answer, answer_annotations = _scientific_notation(answer)
    allowed = {_quantity(m) for m in NUMBER_RE.finditer(normalized_source)}
    derived = _container_total(question, evidence)
    grounded_operand_spans: list[tuple[int, int]] = []
    if derived:
        count, mass, result = derived
        for equation in re.finditer(rf"(?<![\w.,])({_NUM})\s*[×*]\s*({_NUM})\s*=\s*({_NUM})(?!\w|[.,]\d)", answer):
            a, b, total = (Decimal(v.replace(",", "")) for v in equation.groups())
            if sorted([a, b]) == sorted([count, mass]) and total == result.value:
                grounded_operand_spans.extend((equation.span(1), equation.span(2)))
    values: list[str] = sorted(answer_annotations - source_annotations)
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
