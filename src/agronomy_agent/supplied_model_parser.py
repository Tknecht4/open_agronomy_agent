"""Closed fact-span ownership for supplied-model arithmetic requests.

An output head selects a named model. Only complete, recognized operand and
method spans are consumed; other quantities and instructions cannot disappear.
This module reads no evaluation material or external state.
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

from agronomy_agent.arithmetic_input_roles import SEED_WEIGHT_ROLE, SEED_TARGET_ROLE
from agronomy_agent.foundation_math_parser import _unsafe_action_request
from agronomy_agent.seed_establishment import parse_seed_establishment
from agronomy_agent.supplied_model_arithmetic import MODEL_INPUTS, validate_model_arithmetic_inputs
from agronomy_agent.supplied_numeric_inputs import NUMBER, supplied_numeric_gaps


_NUMBERS = re.compile(NUMBER)
_N = rf"(?P<quantity>{NUMBER})"
_VERB = r"(?:please\s+)?(?:calculate|compute|work out|how many|how much|what is)\s+(?:the\s+)?"
_SQM = r"(?:m2|square met(?:re|er)s?)"
_DENSITY = rf"(?:/\s*{_SQM}|per\s+{_SQM})"
_MASS = r"(?:kg|t|(?-i:Mg)|lb|bu|tonnes?)"
_AREA = r"(?:ha|hectares?|ac|acres?)"
_YIELD_UNIT = rf"(?P<mass_unit>{_MASS})\s*(?:/|per\s+)(?P<area_unit>{_AREA})"
_HEADS = {
    "seed_population_density": rf"(?:seeds?\s*{_DENSITY}|(?:required )?seed (?:population density|count))",
    "seed_mass_from_seed_density": r"seed mass(?: (?:per hectare|in kg/ha))?",
    "area_cost_change": r"(?:total and whole[- ]field per[- ]hectare cost change|(?:total|whole[- ]field) cost change)",
    "incremental_margin": r"incremental margin",
    "soil_carbon_stock": r"(?:soil )?carbon stock(?: per hectare)?",
    "soil_total_porosity": r"(?:total )?porosity",
    "remaining_nitrogen_budget": r"remaining (?:available[- ]N |nitrogen |N )?(?:requirement|budget)",
    "daily_water_balance": r"(?:final|ending) (?:water )?storage",
    "ndvi_from_reflectance": r"NDVI",
    "soil_nitrate_n_stock": r"(?:its |the )?(?:soil )?nitrate[- ]N stock(?: per hectare)?",
    "land_equivalent_ratio": r"land equivalent ratio",
    "mean_paired_difference": r"mean paired difference",
    "lime_equivalent_mass": r"product mass",
    "simplified_stress_et": r"modeled (?:ET|value)",
}


def _area(text: str) -> str:
    return "ha" if text.casefold().startswith(("ha", "hect")) else "ac"


def _mass(text: str) -> str:
    return "t" if text == "Mg" or text.casefold().startswith("tonne") else text.casefold()


def _decimal_text(text: str) -> str:
    return str(Decimal(text.replace(",", "")))


class _Facts:
    def __init__(self, text: str):
        self.text = text
        self.spans: list[tuple[int, int]] = []
        self.numbers: list[re.Match[str]] = []
        self.errors: list[str] = []

    def own(self, pattern: str) -> list[re.Match[str]]:
        matches = list(re.finditer(pattern, self.text, re.I))
        for match in matches:
            self.spans.append(match.span())
            self.numbers.extend(_NUMBERS.finditer(self.text, match.start(), match.end()))
        return matches

    def scalar(self, name: str, *patterns: str) -> str | None:
        values = {Decimal(_decimal_text(match["quantity"])) for pattern in patterns for match in self.own(pattern)}
        if len(values) > 1:
            self.errors.append("invalid conflicting values for " + name.replace("_", " "))
        return str(next(iter(values))) if len(values) == 1 else None

    def scope_owned(self) -> bool:
        if not self.spans or re.search(r"[A-Za-z0-9]", self.text[max(end for _, end in self.spans):]):
            return False  # A trailing 'and/with/using' is an unfinished request.
        chars = list(self.text)
        for start, end in self.spans:
            chars[start:end] = " " * (end - start)
        remaining = "".join(chars)
        remaining = re.sub(r"\b(?:a|an|the|and|with|at|on|over|for|of|in|under|using|to|per|its|this)\b", " ", remaining, flags=re.I)
        return not re.sub(r"[\s,.;:!?()=]+", "", remaining)


def _recognize(question: str) -> tuple[str, dict[str, Any], tuple[str, ...], bool] | None:
    text = " ".join(question.translate(str.maketrans("²³−", "23-")).split())
    if _unsafe_action_request(text.casefold()):
        return None
    heads = []
    for operation, object_pattern in _HEADS.items():
        if operation == "seed_mass_from_seed_density" and not re.search(rf"\bseeds?\s*{_DENSITY}|\bseed density\b", text, re.I):
            continue
        if operation == "lime_equivalent_mass" and not re.search(r"\bCaCO3\b|\bneutralizing value\b", text, re.I):
            continue
        if operation == "remaining_nitrogen_budget" and not re.search(r"\bavailable[- ]N\b|\bavailable N\b|\bnutrient budget\b", text, re.I):
            continue
        if operation == "simplified_stress_et" and not re.search(r"\bunstressed ETc?\b", text, re.I):
            continue
        if operation == "daily_water_balance" and not re.search(r"\b(?:water|rain|irrigation|ET|drainage)\b", text, re.I):
            continue
        pattern = rf"\b{_VERB}{object_pattern}\b"
        if re.search(pattern, text, re.I):
            heads.append((operation, pattern))
    if len(heads) != 1:
        return None
    operation, head = heads[0]
    f = _Facts(text);f.own(head)
    values: dict[str, Any] = {}
    missing: list[str] = []

    if operation in {"seed_population_density", "seed_mass_from_seed_density"}:
        if operation == "seed_population_density":
            values["target_plants_per_m2"] = f.scalar("target plants", rf"\b{SEED_TARGET_ROLE}\s*(?:is|of|:|=)?\s*{_N}\s*plants?\s*{_DENSITY}\b")
            bindings: list[re.Match[str]] = []
            establishment, gaps = parse_seed_establishment(text, bindings=bindings)
            values.update(establishment);missing.extend(gaps)
            for binding in bindings:
                f.spans.append(binding.span())
                f.numbers.extend(_NUMBERS.finditer(text, binding.start(), binding.end()))
            f.own(r"\b(?:of|among)\s+(?:(?:all\s+|the\s+)?seeds? (?:sown|planted)|(?:only\s+|the\s+)?(?:germinated|viable) seeds?)\b")
            f.own(r"\b(?:already )?including germination\b")
            f.own(r"\bFor this calculation\b|\bThe laboratory\b")
        else:
            values["seeds_per_m2"] = f.scalar("supplied seed density", rf"(?<!\w){_N}\s*seeds?\s*{_DENSITY}\b")
            values["tkw_g"] = f.scalar("thousand kernel weight", rf"\b{SEED_WEIGHT_ROLE}\s*(?:is|of|:|=)?\s*{_N}\s*g\b")
            f.own(r"\bignoring germination corrections\b")
    elif operation == "area_cost_change":
        f.own(r"\b(?:a|the) prescription\b")
        zones = []
        currencies = set();areas = set()
        for match in f.own(rf"\b(?P<direction>saves?|costs?(?: an? extra)?)\s*(?P<currency>CAD|USD|\$)\s*{_N}\s*/\s*(?P<rate_area>{_AREA})\s+(?:on|over)\s*(?P<zone_area>{NUMBER})\s*(?P<area>{_AREA})\b"):
            rate_area, area = _area(match["rate_area"]), _area(match["area"])
            if rate_area != area:
                f.errors.append("invalid area bases: supply matching zone-area and cost-per-area units")
            sign = -1 if match["direction"].casefold().startswith("save") else 1
            zones.append({"area": _decimal_text(match["zone_area"]), "change_per_area": str(sign * Decimal(match["quantity"].replace(",", "")))})
            currencies.add(match["currency"].upper());areas.add(area)
        values.update(zones=zones or None, currency=next(iter(currencies)) if len(currencies) == 1 else None,
                      area_unit=next(iter(areas)) if len(areas) == 1 else None)
    elif operation == "incremental_margin":
        yields = f.own(rf"\b(?:expected )?added yield\s*(?:is|of|:|=)?\s*{_N}\s*{_YIELD_UNIT}\b")
        prices = f.own(rf"(?P<currency>CAD|USD|\$)\s*{_N}\s*/\s*(?P<mass_unit>{_MASS})\b")
        costs = f.own(rf"\b(?:product|application|added) cost\s*(?:is|of|:|=)?\s*(?P<currency>CAD|USD|\$)\s*{_N}\s*/\s*(?P<area_unit>{_AREA})\b")
        if len(yields) == len(prices) == 1 and costs:
            y, price = yields[0], prices[0]
            units = {_mass(y["mass_unit"]), _mass(price["mass_unit"])}
            areas = {_area(y["area_unit"]), *(_area(m["area_unit"]) for m in costs)}
            currencies = {price["currency"].upper(), *(m["currency"].upper() for m in costs)}
            if len(units) != 1 or len(areas) != 1 or len(currencies) != 1:
                f.errors.append("invalid mixed units/currencies: align yield, price and per-area cost bases")
            values.update(added_yield=_decimal_text(y["quantity"]), price_per_yield_unit=_decimal_text(price["quantity"]),
                          added_costs=[_decimal_text(m["quantity"]) for m in costs], currency=price["currency"].upper(),
                          yield_unit=_mass(y["mass_unit"]), area_unit=_area(y["area_unit"]))
    elif operation in {"soil_carbon_stock", "soil_total_porosity", "soil_nitrate_n_stock"}:
        # SI Mg is a megagram; case-insensitive mg would be a billionfold error.
        density_unit = r"(?:(?-i:Mg)/m3|g/cm3)"
        values["bulk_density_Mg_per_m3"] = f.scalar("dry bulk density", rf"\b(?:dry )?bulk density\s*(?:is|of|:|=)?\s*{_N}\s*{density_unit}\b")
        f.own(r"\b(?:a|the) (?:(?:teaching|uniform) )?(?:soil|layer)\s+(?:has|is)\b")
        if operation == "soil_total_porosity":
            values["particle_density_Mg_per_m3"] = f.scalar("matching particle density", rf"\bparticle density\s*(?:is|of|:|=)?\s*{_N}\s*{density_unit}\b")
            f.own(r"\bUsing porosity\s*=\s*1\s*-\s*bulk\s*/\s*particle density\b")
            f.own(r"\band explain why it is not plant[- ]available water\b")
        else:
            values["depth_m"] = f.scalar("layer depth", rf"\bdepth\s*(?:is|of|:|=)?\s*{_N}\s*m\b", rf"\b(?:a|the) uniform\s*{_N}\s*m\s*layer\s+has\b")
            if operation == "soil_carbon_stock":
                values["carbon_pct"] = f.scalar("carbon concentration percent", rf"(?<!\w){_N}\s*%\s*(?:organic )?carbon\b")
                if f.own(r"\b(?:with )?no coarse fragments\b"):
                    values["coarse_fragment_volume_pct"] = "0"
                else:
                    values["coarse_fragment_volume_pct"] = f.scalar("coarse-fragment volume percent", rf"\bcoarse[- ]fragment volume\s*(?:is|of|:|=)?\s*{_N}\s*%(?!\w)")
            else:
                values["nitrate_n_mg_per_kg"] = f.scalar("nitrate-N concentration", rf"(?<!\w){_N}\s*(?-i:mg)\s+nitrate[- ]N/kg\b")
                values["material_basis"] = "conditional_matching_dry_soil_mass"
    elif operation == "remaining_nitrogen_budget":
        f.own(r"\bUnder a teaching nutrient budget\b")
        values["target_available_n_kg_per_ha"] = f.scalar("supplied available-N target", rf"\btarget available[- ]?\s*N\s*(?:is|of|:|=)?\s*{_N}\s*kg(?:\s*N)?/ha\b")
        credits = []
        for source, role in [("soil", r"soil supply"), ("manure", r"manure available[- ]N credit")]:
            value = f.scalar(source + " available-N credit", rf"\b{role}\s*(?:is|of|:|=)?\s*{_N}(?:\s*kg(?:\s*N)?/ha)?\b")
            if value is not None:
                credits.append({"source": source, "available_n_kg_per_ha": value})
        values["credits"] = credits or None
    elif operation == "daily_water_balance":
        f.own(r"\bFor a teaching daily balance\b")
        for name, role in [("initial_storage_mm", "initial stored water"), ("effective_rain_mm", "effective rain"),
                           ("irrigation_mm", "irrigation"), ("et_mm", "ET"), ("drainage_mm", "drainage")]:
            values[name] = f.scalar(role, rf"\b{role}\s*(?:is|of|:|=)?\s*{_N}(?:\s*mm)?\b")
        if not re.search(r"\bmm\b", text, re.I):
            f.errors.append("invalid water-balance units: supply a common millimetre basis")
    elif operation == "ndvi_from_reflectance":
        f.own(r"\bUsing NDVI\s*=\s*\(NIR\s*-\s*red\)\s*/\s*\(NIR\s*\+\s*red\)(?!\w)")
        f.own(r"\bfor reflectances\b|\bState one agronomic interpretation limit\b")
        values["nir_reflectance"] = f.scalar("NIR reflectance", rf"\bNIR\s*(?:is|of|:|=)?\s*{_N}\b")
        values["red_reflectance"] = f.scalar("red reflectance", rf"\bred\s*(?:is|of|:|=)?\s*{_N}\b")
    elif operation == "land_equivalent_ratio":
        f.own(r"\bFor a teaching intercrop\b")
        components = []
        crop_ids = set()
        for match in f.own(rf"\bcrop\s+(?P<crop_id>[A-Z])\s+(?:yields\s+)?{_N}\s+(?:versus|vs\.?)\s+(?P<sole>{NUMBER})\s*{_YIELD_UNIT}\s+sole\b"):
            crop_id = match["crop_id"].casefold()
            if crop_id in crop_ids:
                f.errors.append("invalid repeated crop component: supply one intercrop/sole yield pair per crop")
            crop_ids.add(crop_id)
            components.append({"intercrop_yield": _decimal_text(match["quantity"]), "sole_yield": _decimal_text(match["sole"]),
                               "yield_unit": _mass(match["mass_unit"]) + "/" + _area(match["area_unit"])})
        values["components"] = components or None
    elif operation == "mean_paired_difference":
        # Here commas are explicit list separators. Ordinary scalar parsing
        # intentionally rejects decimal-comma ambiguity; block count/length
        # checks keep lists from silently becoming grouped scalar quantities.
        list_number = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
        numbers = rf"{list_number}(?:\s*,\s*{list_number})*"
        treatments = f.own(rf"\bTreatment yields in (?P<count>\d+|two|three|four|five) matched blocks are (?P<values>{numbers})\s*{_YIELD_UNIT}\b")
        controls = f.own(rf"\bcontrols?\s*(?:are\s+)?(?P<values>{numbers})(?:\s*{_YIELD_UNIT})?\b")
        f.numbers.extend([*treatments, *controls])
        if len(treatments) == len(controls) == 1:
            t, control = treatments[0], controls[0]
            count_words = {"two": 2, "three": 3, "four": 4, "five": 5}
            count = count_words.get(t["count"].casefold())
            if control["mass_unit"] is not None and (
                _mass(control["mass_unit"]) != _mass(t["mass_unit"])
                or _area(control["area_unit"]) != _area(t["area_unit"])
            ):
                f.errors.append("invalid paired yield units: supply matching treatment and control bases")
            values.update(treatment_yields=[_decimal_text(value) for value in re.split(r"\s*,\s*", t["values"])],
                          control_yields=[_decimal_text(value) for value in re.split(r"\s*,\s*", control["values"])],
                          matched_blocks=count if count is not None else int(t["count"]),
                          yield_unit=_mass(t["mass_unit"]) + "/" + _area(t["area_unit"]))
    elif operation == "lime_equivalent_mass":
        f.own(r"\b(?:a|the) teaching calculation requires\b|\b(?:a|the) material has\b")
        values["pure_caco3_equivalent_per_area"] = f.scalar("supplied pure-CaCO3 equivalence", rf"(?<!\w){_N}\s*{_YIELD_UNIT}\s+of pure CaCO3 equivalent\b")
        units = re.search(rf"(?P<mass>{_MASS})/(?P<area>{_AREA})\s+of pure CaCO3 equivalent\b", text, re.I)
        if units:
            values.update(mass_unit=_mass(units["mass"]), area_unit=_area(units["area"]))
        values["effective_neutralizing_value_pct"] = f.scalar("effective neutralizing value", rf"(?<!\w){_N}\s*%\s*effective neutralizing value\b")
        f.own(r"\bassuming the stated value applies\b")
    elif operation == "simplified_stress_et":
        f.own(r"\b(?:a|the) model gives\b")
        values["unstressed_et_mm_per_day"] = f.scalar("supplied unstressed ET", rf"\bunstressed ETc?\s*(?:is|of|:|=)?\s*{_N}\s*mm/day\b")
        values["stress_multiplier"] = f.scalar("supplied stress multiplier", rf"\b(?:a )?simplified stress multiplier\s*(?:is|of|:|=)?\s*{_N}\b")
        if f.own(r"\bapplied to all ET for this exercise\b"):
            values["stress_application"] = "all_et_simplified"
        f.own(r"\band state the simplification\b")

    required = MODEL_INPUTS[operation]
    if operation == "seed_population_density":
        required = required - {"field_survival_pct", "survival_basis"}
    missing.extend(name.replace("_", " ") for name in sorted(required) if values.get(name) is None)
    values = {name: value for name, value in values.items() if value is not None}
    missing.extend(f.errors)
    missing.extend(supplied_numeric_gaps(text, f.numbers))
    owned = f.scope_owned()
    if not missing:
        try:
            validate_model_arithmetic_inputs(operation, values)
        except (ValueError, ArithmeticError) as error:
            missing.append("invalid " + str(error))
    return operation, values, tuple(dict.fromkeys(missing)), owned


def parse_supplied_model_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    result = _recognize(question)
    return result[:3] if result is not None and result[3] else None


def model_calculation_request_is_complete(question: str, operation: str) -> bool:
    result = _recognize(question)
    return result is not None and result[0] == operation and result[3]
