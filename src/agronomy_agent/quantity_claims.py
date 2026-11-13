"""Bounded quantity identity and container-total checks for draft review.

This is a screening contract, not a general mathematical or semantic verifier.
A mentioned quantity is not proof of its relation to an entity or of authority
for an action. An explicit container mass total and a bounded fictional
mass-fraction illustration can be checked here. Neither grants field authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


def remove_numeric_application_instructions(text: str) -> tuple[str, tuple[str, ...]]:
    """Separate direct numeric application instructions from explanatory prose.

    This bounded screening helper does not infer authority from a known value.
    Callers decide whether an application instruction was actually requested.
    Marked examples, historical statements and conversion instructions remain.
    """
    # A leading decimal is part of the quantity, and closing Markdown belongs
    # to the sentence it decorates. Keep original bytes for retained prose.
    pieces = re.split(r"(\.(?!\d)[*_`]*|[;!?\n]+)", text)
    kept: list[str] = []
    removed: list[str] = []
    physical = {"kg", "mg", "g", "lb", "oz", "ml", "l", "gallons", "quarts", "tonnes", "gal", "qt", "pt", "fl", "%"}
    index = 0
    while index < len(pieces):
        clause = pieces[index]
        ending = pieces[index + 1] if index + 1 < len(pieces) else ""
        if re.fullmatch(r"\s*\d+", clause) and ending == "." and index + 2 < len(pieces):
            clause += ending + pieces[index + 2]
            index += 2
            ending = pieces[index + 1] if index + 1 < len(pieces) else ""
        matching_text = re.sub(r"[*_`]", "", clause)
        action = re.search(
            r"^\s*(?:(?:[-•]|\d+[.)])\s*)?(?:(?:recommendation|next step|action)\s*:\s*)?"
            r"(?:(?:then|next|please)\s+)?(?:(?:you|we)\s+(?:should|can|may|must)\s+)?"
            r"(?:apply|spray(?!\s+(?:volume|rate|coverage)\b)|use)\b|"
            r"^\s*(?:I|we)\s+(?:recommend|advise|suggest)\b[^.!?;]{0,45}\b(?:applying|spraying|using)\b",
            matching_text, re.I,
        )
        conversion = re.search(
            rf"^\s*(?:use\s+{_NUM}\s+to\s+convert\b|(?:use|apply)\s+(?:the\s+)?(?:conversion factor|unit conversion)\b)",
            matching_text, re.I,
        )
        quantities = [_quantity(m) for m in NUMBER_RE.finditer(matching_text)]
        chosen_amount = any(q.unit.split("/")[0] in physical for q in quantities)
        part = clause + ending
        (removed if action and chosen_amount and not conversion else kept).append(part)
        index += 2
    return ("".join(kept).strip(), tuple(removed)) if removed else (text, ())


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


def _calendar_dates(text: str) -> tuple[str, set[str]]:
    """Keep whole valid dates distinct from scalar amounts and ranges."""
    months = {name: index for index, names in enumerate((
        ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
        ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
        ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec"),
    ), 1) for name in names}
    month = "|".join(months)
    patterns = (
        re.compile(r"(?<![\w-])(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?![\d-])"),
        re.compile(rf"\b(?P<month_name>{month})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
                   r"(?:,?\s+(?P<year>\d{4}))?\b", re.I),
        re.compile(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month_name>{month})\.?"
                   r"(?:,?\s+(?P<year>\d{4}))?\b", re.I),
    )
    identities: set[str] = set()
    def replace(match: re.Match[str]) -> str:
        fields = match.groupdict()
        if re.match(r"\s*(?:kg|kilograms?|g|grams?|lbs?|pounds?|mL|L|litres?|liters?|%|percent)\b|\s*%",
                    text[match.end():], re.I):
            # 'May 18 kg/ha' must not mask a quantity as a yearless date.
            return match.group()
        month_number = months[fields["month_name"].lower()] if fields.get("month_name") else int(fields["month"])
        try:
            # A leap reference year validates month/day without inventing the
            # missing year. Unknown-year identities cannot authorize a year.
            value = date(int(fields["year"] or 2000), month_number, int(fields["day"]))
            identity = value.isoformat() if fields["year"] else value.strftime("--%m-%d")
        except ValueError:
            identity = "invalid calendar date: " + match.group()
            suffix = text[match.end():match.end() + 70]
            if re.match(r"\s+(?:(?:is|was)\s+(?:an?\s+)?(?:invalid(?: calendar)? date|"
                        r"not (?:a )?valid (?:calendar )?date)|does not exist)\b", suffix, re.I):
                return "calendar_date"
        identities.add(identity)
        # Mask the entire date, including its year. A supplied date does not
        # authorize the same digits as a fertilizer quantity or free scalar.
        return "calendar_date"
    for pattern in patterns:
        text = pattern.sub(replace, text)
    return text, identities


def _checked_rate_illustration_spans(answer: str, question: str) -> set[tuple[int, int]]:
    """Check fictional operands and a labelled mass-fraction relation.

    This is not candidate-generated evidence. It checks internal arithmetic
    under an explicitly requested illustration, never a field observation,
    label permission, chosen target or an unrelated paragraph.
    """
    from agronomy_agent.answerability import is_rate_basis_explanation, _NAMED_PESTICIDE_RE
    if not is_rate_basis_explanation(question) or not re.search(r"\bexample\b", question, re.I):
        return set()
    mass = {"kg": Decimal(1), "kilogram": Decimal(1), "kilograms": Decimal(1),
            "g": Decimal("0.001"), "gram": Decimal("0.001"), "grams": Decimal("0.001"),
            "lb": Decimal(1), "lbs": Decimal(1), "pound": Decimal(1), "pounds": Decimal(1)}
    aliases = {"nitrogen": "n", "phosphorus": "p", "potassium": "k", "nutrient": "", "nutrients": ""}
    nutrient = r"nitrogen|phosphorus|potassium|nutrients?|P2O5|K2O|N|P|K"
    product = r"product|it|(?:(?:this|the)\s+)?fertili[sz]er"
    rate = re.compile(rf"(?<![\w.,])(?P<value>{_NUM})\s*(?P<mass>kilograms?|grams?|pounds?|kg|lbs?|g)\b"
        rf"(?:\s+(?:of\s+)?(?P<basis>{nutrient}|{product}))?"
        r"\s*(?:/|\bper\s+)(?P<area>hectares?|acres?|ha|ac)\b", re.I)
    checked: set[tuple[int, int]] = set()
    offset = 0
    for block in re.split(r"(\n\s*\n)", answer):
        start = offset
        offset += len(block)
        if (not re.search(r"\b(?:hypothetical|illustrative|made[- ]up|fictional|suppose)\b", block, re.I)
                or _NAMED_PESTICIDE_RE.search(block)
                or remove_numeric_application_instructions(block)[1]
                or re.search(r"\b(?:my|your|our|this|the)\s+field\b|"
                    r"\b(?:you|we)\s+(?:can|should|may|must)\s+(?:apply|use|spray)\b|"
                    r"\b(?:actual|current|legal|registered|approved|authorized|recommended|protein|density|volume)\b", block, re.I)):
            continue
        percentage_mentions = list(re.finditer(
            rf"(?<![\w.,])({_NUM})\s*(?:%|percent\b|per\s+cent\b)\s*({nutrient})\b", block, re.I))
        percentages = {(Decimal(m[1].replace(',', '')), aliases.get(m[2].lower(), m[2].lower()))
            for m in percentage_mentions}
        if len(percentages) != 1:
            continue
        percent, percent_basis = next(iter(percentages))
        if not 0 <= percent <= 100:
            continue
        rows = []
        invalid = False
        for match in rate.finditer(block):
            unit, area = match['mass'].lower(), match['area'].lower()
            area = 'ha' if area in {'ha','hectare','hectares'} else 'ac'
            value = Decimal(match['value'].replace(',', ''))
            basis = (match['basis'] or '').lower()
            role = ('product' if re.fullmatch(product, basis, re.I) else 'nutrient' if basis else None)
            identity = aliases.get(basis, basis) if role == 'nutrient' else None
            prefix = re.sub(r'[*_`]', '', block[max(0,match.start()-80):match.start()])
            label = re.search(r"\b(product|nutrient|nitrogen|phosphorus|potassium)\s+"
                r"(?:rate|mass|amount)\s*(?:(?:of|is)\s*|[:=]\s*)?$", prefix, re.I)
            if label:
                labelled = 'product' if label[1].lower() == 'product' else 'nutrient'
                labelled_identity = aliases.get(label[1].lower(), label[1].lower())
                if role and (role != labelled or role == 'nutrient' and identity and labelled_identity
                             and identity != labelled_identity):
                    invalid = True
                role = labelled
                if role == 'nutrient' and not identity:
                    identity = labelled_identity
            if role == 'nutrient' and identity and identity != percent_basis:
                invalid = True
            rows.append((value * mass[unit], 'lb' if unit in {'lb','lbs','pound','pounds'} else 'kg', area, role, value, *match.span()))
        # Only spans in an actual product-to-nutrient relation receive an
        # exemption. Equal numeric values elsewhere are not derived evidence.
        related_rows = []
        for product_row in (row for row in rows if row[3] == 'product'):
            for nutrient_row in (row for row in rows if row[3] == 'nutrient' and row[5] >= product_row[6]):
                connector = re.sub(r'[*_`]', '', block[product_row[6]:nutrient_row[5]])
                if re.fullmatch(r"\s*(?:gives?|delivers?|yields?|suppl(?:y|ies)|contains?|equals?|corresponds? to)\s+"
                    r"(?:(?:a|an|the)\s+)?(?:(?:nutrient|nitrogen|phosphorus|potassium)\s+"
                    r"(?:rate|mass|amount)\s*(?:(?:of|is)\s*|[:=]\s*)?)?", connector, re.I):
                    related_rows.extend((product_row, nutrient_row))
        rows = related_rows
        products = {r[0] for r in rows if r[3] == 'product'}
        nutrients = {r[0] for r in rows if r[3] == 'nutrient'}
        if (invalid or len(products) != 1 or len(nutrients) != 1 or not rows
                or len({(r[1], r[2]) for r in rows}) != 1 or any(r[0] < 0 for r in rows)):
            continue
        product_mass, nutrient_mass = next(iter(products)), next(iter(nutrients))
        if product_mass * percent / 100 != nutrient_mass or any(r[0] not in {product_mass,nutrient_mass} for r in rows):
            continue
        equations = list(re.finditer(rf"({_NUM})\s*[×*]\s*({_NUM})\s*=\s*({_NUM})", block))
        if any(Decimal(m[1].replace(',', '')) * Decimal(m[2].replace(',', '')) != Decimal(m[3].replace(',', ''))
               for m in equations):
            continue
        scalars = {percent, percent/100, *(r[4] for r in rows)}
        bound_spans = [(row[5], row[6]) for row in rows]
        bound_spans += [m.span() for m in percentage_mentions if (
            re.search(r"\b(?:product|fertili[sz]er)\s+(?:contains?|is|has)\s*(?:(?:about|approximately)\s+)?$",
                      block[max(0, m.start()-90):m.start()], re.I)
            or re.match(r"\s*(?:product|fertili[sz]er)\b", block[m.end():], re.I))]
        bound_spans += [m.span() for m in equations
                        if all(Decimal(v.replace(',', '')) in scalars for v in m.groups())]
        for match in NUMBER_RE.finditer(block):
            if not any(left <= match.start() and match.end() <= right for left, right in bound_spans):
                continue
            quantity = _quantity(match)
            if quantity.upper is not None:
                continue
            supported = quantity.unit == '%' and quantity.value == percent
            if not quantity.unit:
                supported = quantity.value in scalars
            unit_match = re.fullmatch(r"(kilograms?|grams?|pounds?|kg|lbs?|g)(?:/(hectares?|acres?|ha|ac))?", quantity.unit)
            if unit_match:
                base, area = unit_match.groups()
                area = 'ha' if area in {'ha','hectare','hectares'} else 'ac' if area else ''
                supported = (quantity.value * mass[base] in {product_mass,nutrient_mass}
                    and (not area or area == rows[0][2])
                    and ('lb' if base in {'lb','lbs','pound','pounds'} else 'kg') == rows[0][1])
            if supported:
                checked.add((start + match.start(), start + match.end()))
    return checked


def unsupported_quantities(answer: str, *, question: str, evidence: str) -> tuple[str, ...]:
    source = f"{question}\n{evidence}"
    source_dates: set[str] = set()
    answer_dates: set[str] = set()
    if re.search(r"\b(?:dates?|dated|collected|sampled|analy[sz]ed|issued|issuance|reported|"
                 r"acquired|acquisition|sown|planted|harvested)\b", question, re.I):
        source, source_dates = _calendar_dates(source)
        answer, answer_dates = _calendar_dates(answer)
    normalized_source, source_annotations = _scientific_notation(source)
    answer, answer_annotations = _scientific_notation(answer)
    illustrative_spans = _checked_rate_illustration_spans(answer, question)
    allowed = {_quantity(m) for m in NUMBER_RE.finditer(normalized_source)}
    derived = _container_total(question, evidence)
    grounded_operand_spans: list[tuple[int, int]] = []
    if derived:
        count, mass, result = derived
        for equation in re.finditer(rf"(?<![\w.,])({_NUM})\s*[×*]\s*({_NUM})\s*=\s*({_NUM})(?!\w|[.,]\d)", answer):
            a, b, total = (Decimal(v.replace(",", "")) for v in equation.groups())
            if sorted([a, b]) == sorted([count, mass]) and total == result.value:
                grounded_operand_spans.extend((equation.span(1), equation.span(2)))
    values: list[str] = sorted((answer_annotations - source_annotations) | (answer_dates - source_dates)
                               | {value for value in answer_dates if value.startswith("invalid calendar date:")})
    for match in NUMBER_RE.finditer(answer):
        if match.span() in illustrative_spans:
            continue
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
