"""Bounded natural-language extraction for supplied-input calculation requests.

This parser recognizes named quantities and units, never chooses agronomic
targets, market prices, or label authority. Ambiguity becomes a clarification.
"""

from __future__ import annotations

import re
from typing import Any


NUMBER = r"(-?[0-9][0-9,]*(?:\.[0-9]+)?)"
SIGNED_NUMBER = NUMBER
AREA = r"(?:ac|acre|acres|ha|hectare|hectares)"
YIELD_UNIT = r"(?:bu|bushels?|tonnes?|kg|lb)"
MONEY = rf"(?:CAD|USD|\$)\s*{NUMBER}"


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _find_number(text: str, *patterns: str) -> float | None:
    values = {
        _number(match.group(1))
        for pattern in patterns
        for match in re.finditer(pattern, text, re.IGNORECASE)
    }
    return next(iter(values)) if len(values) == 1 else None


def _area(value: str) -> str:
    return "ha" if value.lower().startswith(("ha", "hect")) else "ac"


def _yield_unit(value: str) -> str:
    text = value.lower()
    if text.startswith(("bu", "bushel")):
        return "bu"
    if text.startswith("tonne"):
        return "tonne"
    return text


def _currency(text: str) -> str | None:
    values = {value.upper() for value in re.findall(r"\b(?:CAD|USD)\b", text, re.IGNORECASE)}
    if len(values) > 1:
        return None
    if values:
        return next(iter(values))
    return "$" if "$" in text else None


def _mixed_explicit_currencies(text: str) -> bool:
    return len({value.upper() for value in re.findall(r"\b(?:CAD|USD)\b", text, re.IGNORECASE)}) > 1


def _unparsed_magnitude(text: str) -> bool:
    return bool(re.search(r"\b-?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|[kmb])\b", text, re.IGNORECASE))


def _requested_arithmetic(lower: str) -> bool:
    if re.search(r"^\s*(?:what does|what is a|what is an|why|how does|explain|define|compare)\b", lower):
        return False
    return bool(re.search(
        r"\b(?:calculate|compute|work out|how many|about how many|what is (?:the|one|my)|"
        r"what yield breaks even|break-even (?:price|yield)|break even (?:price|yield))\b",
        lower,
    ))


def _unsafe_action_request(lower: str) -> bool:
    return bool(re.search(
        r"\b(?:should (?:i|we) (?:apply|spray|sell|buy|use)|"
        r"recommended (?:application |herbicide |pesticide |fertilizer )?rate|"
        r"legal (?:application |fertilizer |herbicide |pesticide )?rate|"
        r"today['’]s (?:cash |market |local )?(?:bid|price)|sell (?:now|today)|lock in (?:a )?sale)\b",
        lower,
    ))


def parse_foundation_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    text = " ".join(question.replace("−", "-").split())
    lower = text.casefold()
    if not _requested_arithmetic(lower) or _unsafe_action_request(lower):
        return None
    for parser in (_seed_rate, _gdd, _partial_budget, _break_even, _current_ratio, _debt_asset):
        parsed = parser(text, lower)
        if parsed is not None:
            return parsed
    return None


def _seed_rate(text: str, lower: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    if not re.search(r"\b(?:seed(?:ing)? (?:rate|mass|purchase)|seed[- ]lot|thousand[- ]kernel|tkw)\b", lower):
        return None
    target_matches = list(re.finditer(
        rf"{NUMBER}\s*(?:[A-Za-z-]+\s+)?(?:established\s+)?plants\s*(?:/|per\s+)(m²|m2|square metre|square meter|ft²|ft2|square foot|square feet)",
        text, re.IGNORECASE,
    ))
    targets = {(_number(match.group(1)), match.group(2).casefold()) for match in target_matches}
    target, unit = next(iter(targets)) if len(targets) == 1 else (None, "")
    imperial = "ft" in unit or "foot" in unit or "feet" in unit
    tkw = _find_number(
        text,
        rf"{NUMBER}\s*g\s*(?:thousand[- ]kernel weight|tkw)\b",
        rf"(?:thousand[- ]kernel weight|tkw)\s*(?:is|of|:)?\s*{NUMBER}\s*g\b",
    )
    germination = _find_number(
        text,
        rf"{NUMBER}\s*%\s*(?:seed[- ]lot\s+)?germination\b",
        rf"\bgermination\s*(?:is|of|:)?\s*{NUMBER}\s*%",
    )
    survival = _find_number(
        text,
        rf"{NUMBER}\s*%\s*(?:(?:expected|field|emergence)\s+)*(?:survival|emergence)\b",
        rf"\b(?:field|emergence|seedling)\s+survival\s*(?:is|of|:)?\s*{NUMBER}\s*%",
    )
    loss = _find_number(
        text,
        rf"{NUMBER}\s*%\s*(?:expected\s+)?(?:post[- ]germination\s+)?(?:seedling\s+)?(?:loss|mortality)\b",
        rf"\b(?:loss|mortality)\s*(?:is|of|:)?\s*{NUMBER}\s*%",
    )
    if survival is not None and loss is not None and abs(survival + loss - 100) > 0.0001:
        return "seed_rate_mass_imperial" if imperial else "seed_rate_mass", {}, ("consistent survival and loss percentages",)
    if survival is None and loss is not None:
        survival = 100 - loss
    inputs: dict[str, Any] = {}
    target_key = "target_plants_per_ft2" if imperial else "target_plants_per_m2"
    if target is not None:
        inputs[target_key] = target
    if tkw is not None:
        inputs["tkw_g"] = tkw
    if germination is not None:
        inputs["germination_pct"] = germination
    if survival is not None:
        inputs["field_survival_pct"] = survival
    missing = tuple(
        label for key, label in (
            (target_key, "target plants per square metre or foot"),
            ("tkw_g", "thousand-kernel weight in grams"),
            ("germination_pct", "seed-lot germination percent"),
            ("field_survival_pct", "post-germination field survival or mortality percent"),
        ) if key not in inputs
    )
    for key, label in ((target_key, "target plants"), ("tkw_g", "thousand-kernel weight")):
        if key in inputs and inputs[key] <= 0:
            missing += (f"invalid {label}: use a positive value",)
    for key, label in (("germination_pct", "germination"), ("field_survival_pct", "field survival")):
        if key in inputs and not 0 < inputs[key] <= 100:
            missing += (f"invalid {label}: use a percentage above zero and at most 100",)
    if loss is not None and not 0 <= loss < 100:
        missing += ("invalid mortality: use a percentage from zero to below 100",)
    requested_unit = re.search(r"\b(?:give|in|as)\s+(kg/ha|lb/ac)\b", lower)
    if requested_unit and requested_unit.group(1) != ("lb/ac" if imperial else "kg/ha"):
        missing += ("invalid requested output unit: use a separate unit conversion",)
    if imperial:
        if "factor-10" in lower or "factor 10" in lower:
            method = "published_factor_10"
        elif "manitoba" in lower and "dimensional" not in lower:
            method = "compare"
        else:
            method = "dimensional"
        inputs["method"] = method
        return "seed_rate_mass_imperial", inputs, missing
    return "seed_rate_mass", inputs, missing


def _gdd(text: str, lower: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    if not re.search(r"\b(?:gdd|growing degree[- ]days?|heat units?)\b", lower):
        return None
    high = _find_number(text, rf"\b(?:tmax|max(?:imum)?(?: temp(?:erature)?)?|high)\s*(?:was|is|of|:)?\s*{SIGNED_NUMBER}\s*°?\s*C\b")
    low = _find_number(text, rf"\b(?:tmin|min(?:imum)?(?: temp(?:erature)?)?|low)\s*(?:was|is|of|:)?\s*{SIGNED_NUMBER}\s*°?\s*C\b")
    base = _find_number(
        text,
        rf"\bbase(?: temperature)?\s*(?:was|is|of|:)?\s*{SIGNED_NUMBER}\s*°?\s*C\b",
        rf"{SIGNED_NUMBER}\s*°?\s*C\s+base\b",
    )
    upper_cap = _find_number(
        text,
        rf"\b(?:upper|maximum|high)\s+(?:temperature\s+)?cap\s*(?:at|of|is|:)?\s*{SIGNED_NUMBER}\s*°?\s*C\b",
        rf"\bcap\s+(?:the\s+)?(?:maximum|high|tmax)\s*(?:at|to)?\s*{SIGNED_NUMBER}\s*°?\s*C\b",
    )
    lower_cap = _find_number(
        text,
        rf"\b(?:lower|minimum|low)\s+(?:temperature\s+)?cap\s*(?:at|of|is|:)?\s*{SIGNED_NUMBER}\s*°?\s*C\b",
        rf"\bcap\s+(?:the\s+)?(?:minimum|low|tmin)\s*(?:at|to)?\s*{SIGNED_NUMBER}\s*°?\s*C\b",
    )
    values = {"max_temp_c": high, "min_temp_c": low, "base_temp_c": base,
              "upper_cap_c": upper_cap, "lower_cap_c": lower_cap}
    inputs = {key: value for key, value in values.items() if value is not None}
    missing = tuple(key for key in ("max_temp_c", "min_temp_c", "base_temp_c") if values[key] is None)
    if high is not None and low is not None and high < low:
        missing += ("invalid temperatures: maximum must be at least minimum",)
    if lower_cap is not None and upper_cap is not None and lower_cap > upper_cap:
        missing += ("invalid caps: lower cap must not exceed upper cap",)
    mentions_cap = bool(re.search(r"\bcap(?:s|ped|ping)?\b", lower))
    says_no_cap = bool(re.search(r"\b(?:no|without)\s+(?:temperature\s+)?caps?\b", lower))
    if mentions_cap and not says_no_cap and upper_cap is None and lower_cap is None:
        missing += ("invalid cap: specify an upper or lower temperature cap in C",)
    return "daily_gdd", inputs, missing


def _partial_budget(text: str, lower: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    if not re.search(r"\b(?:partial[- ]budget|partial budget|net change)\b", lower) or not re.search(r"\b(?:revenue|return|income|cost)\b", lower):
        return None
    categories = {
        "added_returns": (
            rf"\b(?:added|additional|increased)\s+(?:revenue|returns?|income)\s*(?:(?:of|is|are|:)\s*)?{MONEY}",
            rf"\b(?:adds?|increases?)\s*{MONEY}.{{0,35}}\b(?:revenue|returns?|income)\b",
        ),
        "reduced_costs": (
            rf"\b(?:reduced|saved|lower)\s+costs?\s*(?:(?:of|is|are|:)\s*)?{MONEY}",
            rf"\b(?:saves?|reduces?)\s*{MONEY}.{{0,35}}\bcosts?\b",
            rf"\bcost\s+savings?\s*(?:(?:of|is|are|:)\s*)?{MONEY}",
        ),
        "added_costs": (
            rf"\b(?:added|additional|increased)\s+costs?\s*(?:(?:of|is|are|:)\s*)?{MONEY}",
            rf"\b(?:adds?|increases?)\s*{MONEY}.{{0,35}}\bcosts?\b",
        ),
        "reduced_returns": (
            rf"\b(?:lost|foregone|reduced)\s+(?:revenue|returns?|income)\s*(?:(?:of|is|are|:)\s*)?{MONEY}",
            rf"\b(?:loses?|forgoes?)\s*{MONEY}.{{0,35}}\b(?:revenue|returns?|income)\b",
        ),
    }
    values = {key: _find_number(text, *patterns) for key, patterns in categories.items()}
    inputs: dict[str, Any] = {key: value for key, value in values.items() if value is not None}
    currency = _currency(text)
    if currency:
        inputs["currency"] = currency
    category_area_units: dict[str, set[str]] = {}
    for key, patterns in categories.items():
        units: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # The basis must bind to this amount. A preceding "per acre"
                # in the question header cannot set every component's basis.
                immediate_suffix = re.match(rf"\s*(?:/|per\s+)({AREA})\b", text[match.end():], re.IGNORECASE)
                phrase = match.group(0) + (immediate_suffix.group(0) if immediate_suffix else "")
                units.update(_area(value) for value in re.findall(rf"(?:/|per\s+)({AREA})\b", phrase, re.IGNORECASE))
        category_area_units[key] = units
    area_matches = set().union(*category_area_units.values())
    if len(area_matches) == 1 and all(units == area_matches for units in category_area_units.values()):
        inputs["area_unit"] = next(iter(area_matches))
    missing = tuple(key for key, value in values.items() if value is None)
    if _unparsed_magnitude(text):
        missing += ("invalid magnitude: write each amount as an explicit number",)
    if _mixed_explicit_currencies(text):
        missing += ("invalid currency: all amounts must use the same currency",)
    if any(value is not None and value < 0 for value in values.values()):
        missing += ("invalid budget component: use nonnegative amounts in each named category",)
    if currency is None:
        missing += ("one consistent currency",)
    if len(area_matches) > 1:
        missing += ("invalid basis: use one consistent area unit",)
    if area_matches and not all(units == area_matches for units in category_area_units.values()):
        missing += ("invalid basis: state the same per-area basis for all four changes",)
    if area_matches and re.search(r"\b(?:whole[- ]farm|whole farm|total for (?:the )?(?:farm|field))\b", lower):
        missing += ("invalid basis: whole-farm totals cannot be mixed with per-area amounts",)
    return "partial_budget", inputs, missing


def _cost_candidates(text: str) -> set[tuple[float, str, str]]:
    specific_patterns = (
        rf"\b(?P<basis>total economic|total|operating)\s+costs?\s*(?:of|is|are|:)?\s*(?:CAD|USD|\$)\s*(?P<value>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/|per\s+)(?P<area>{AREA})\b",
        rf"\b(?:crop\s+)?budget\s+totals?\s*(?:CAD|USD|\$)\s*(?P<value>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/|per\s+)(?P<area>{AREA})\b",
        rf"(?:CAD|USD|\$)\s*(?P<value>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/|per\s+)(?P<area>{AREA})\s+(?P<basis>total|operating)\s+cost\b",
    )
    candidates: set[tuple[float, str, str]] = set()
    for index, pattern in enumerate(specific_patterns):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            basis = (match.groupdict().get("basis") or ("budget_total_supplied" if index == 1 else "")).lower()
            candidates.add((_number(match.group("value")), _area(match.group("area")), "total_economic" if basis == "total economic" else basis))
    if candidates:
        return candidates
    generic = rf"\bcosts?\s*(?:of|is|are|:)?\s*(?:CAD|USD|\$)\s*(?P<value>-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/|per\s+)(?P<area>{AREA})\b"
    return {
        (_number(match.group("value")), _area(match.group("area")), "")
        for match in re.finditer(generic, text, re.IGNORECASE)
    }


def _yield(text: str) -> tuple[float, str, str] | None:
    patterns = (
        rf"\b(?:expected|harvested|target)?\s*yield\s*(?:of|is|:)?\s*{NUMBER}\s*({YIELD_UNIT})\s*(?:/|per\s+)({AREA})\b",
        rf"{NUMBER}\s*({YIELD_UNIT})\s*(?:/|per\s+)({AREA})\b",
    )
    values = {
        (_number(match.group(1)), _yield_unit(match.group(2)), _area(match.group(3)))
        for pattern in patterns
        for match in re.finditer(pattern, text, re.IGNORECASE)
    }
    return next(iter(values)) if len(values) == 1 else None


def _price(text: str) -> tuple[float, str] | None:
    values = {
        (_number(match.group(1)), _yield_unit(match.group(2)))
        for match in re.finditer(rf"(?:CAD|USD|\$)\s*{NUMBER}\s*(?:/|per\s+)({YIELD_UNIT})\b", text, re.IGNORECASE)
    }
    return next(iter(values)) if len(values) == 1 else None


def _break_even(text: str, lower: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    if not re.search(r"\bbreak[- ]?even\b|\bbreaks? even\b", lower):
        return None
    price_question = bool(re.search(r"\bbreak[- ]?even\s+(?:sale\s+)?price\b", lower))
    yield_question = bool(re.search(r"\bbreak[- ]?even\s+yield\b|\bwhat yield breaks? even\b|\byield breaks? even\b", lower))
    if price_question == yield_question:
        return None
    operation = "break_even_price" if price_question else "break_even_yield"
    costs = _cost_candidates(text)
    requested_basis = (
        "operating" if re.search(r"\boperating[- ]cost break[- ]?even\b", lower)
        else "total_economic" if re.search(r"\btotal economic[- ]cost break[- ]?even\b", lower)
        else "total" if re.search(r"\btotal[- ]cost break[- ]?even\b", lower)
        else None
    )
    if requested_basis:
        compatible = {"total", "total_economic", "budget_total_supplied"} if requested_basis == "total" else {requested_basis}
        costs = {candidate for candidate in costs if candidate[2] in compatible}
    cost = next(iter(costs)) if len(costs) == 1 else None
    harvested = _yield(text) if price_question else None
    selling_price = _price(text) if yield_question else None
    currency = _currency(text)
    inputs: dict[str, Any] = {}
    missing: tuple[str, ...] = ()
    if _unparsed_magnitude(text):
        missing += ("invalid magnitude: write each amount as an explicit number",)
    if _mixed_explicit_currencies(text):
        missing += ("invalid currency: cost and price must use the same currency",)
    if cost:
        inputs["cost_per_area"], inputs["area_unit"], inputs["cost_basis"] = cost
        if inputs["cost_per_area"] < 0:
            missing += ("invalid cost: use a nonnegative amount",)
        if not inputs["cost_basis"]:
            missing += ("whether the cost is operating or total",)
    else:
        missing += (
            ("one unambiguous cost amount and basis",) if costs
            else ("cost per acre or hectare", "whether the cost is operating or total")
        )
    if currency:
        inputs["currency"] = currency
    else:
        missing += ("one consistent currency",)
    if price_question:
        if harvested:
            inputs["yield_per_area"], inputs["yield_unit"], yield_area = harvested
            if cost and yield_area != cost[1]:
                missing += ("cost and yield on the same area unit",)
            if inputs["yield_per_area"] <= 0:
                missing += ("invalid expected yield must be positive",)
        else:
            missing += ("expected harvested yield per area",)
    else:
        if selling_price:
            inputs["price_per_unit"], inputs["yield_unit"] = selling_price
            if inputs["price_per_unit"] <= 0:
                missing += ("invalid assumed selling price must be positive",)
        else:
            missing += ("assumed selling price per harvested unit",)
    return operation, inputs, tuple(dict.fromkeys(missing))


def _finance_value(text: str, noun: str) -> float | None:
    return _find_number(
        text,
        rf"\b{noun}\s*(?:of|are|is|:)?\s*(?:CAD|USD|\$)?\s*{NUMBER}",
        rf"(?:CAD|USD|\$)\s*{NUMBER}\s*{noun}\b",
    )


def _current_ratio(text: str, lower: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    if not re.search(r"\bcurrent ratio\b", lower):
        return None
    values = {
        "current_assets": _finance_value(text, r"current assets?"),
        "current_liabilities": _finance_value(text, r"current liabilities"),
    }
    inputs = {key: value for key, value in values.items() if value is not None}
    missing = tuple(key for key, value in values.items() if value is None)
    if _unparsed_magnitude(text):
        missing += ("invalid magnitude: write assets and liabilities as explicit numbers",)
    if _mixed_explicit_currencies(text):
        missing += ("invalid currency: assets and liabilities must use the same currency",)
    if values["current_assets"] is not None and values["current_assets"] < 0:
        missing += ("invalid current assets: use a nonnegative amount",)
    if values["current_liabilities"] is not None and values["current_liabilities"] <= 0:
        missing += ("current liabilities must be positive",)
    return "current_ratio", inputs, missing


def _debt_asset(text: str, lower: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    if not re.search(r"\bdebt[- ]to[- ]asset(?: ratio)?\b|\bdebt/asset(?: ratio)?\b", lower):
        return None
    values = {
        "total_debt": _finance_value(text, r"(?:total\s+)?debt"),
        "total_assets": _finance_value(text, r"(?:total\s+)?assets"),
    }
    inputs = {key: value for key, value in values.items() if value is not None}
    missing = tuple(key for key, value in values.items() if value is None)
    if _unparsed_magnitude(text):
        missing += ("invalid magnitude: write debt and assets as explicit numbers",)
    if _mixed_explicit_currencies(text):
        missing += ("invalid currency: debt and assets must use the same currency",)
    if values["total_debt"] is not None and values["total_debt"] < 0:
        missing += ("invalid total debt: use a nonnegative amount",)
    if values["total_assets"] is not None and values["total_assets"] <= 0:
        missing += ("total assets must be positive",)
    return "debt_to_asset_percent", inputs, missing
