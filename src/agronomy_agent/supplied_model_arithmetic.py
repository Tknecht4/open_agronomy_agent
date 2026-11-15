"""Typed arithmetic for supplied agronomic models, not field prescriptions.

Every operand is explicit. Formula-specific assumptions stay in the result;
none establishes measured field conditions, a calibrated target or permission.
Natural-language ownership belongs to the separate request parser.
Porosity uses dry bulk density and matching soil-solid particle density.
LER numerators use yields per total intercrop area, not per crop's own strip.
"""
from __future__ import annotations

from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from typing import Any, Mapping

from agronomy_agent.seed_establishment import SEED_SURVIVAL_BASES, established_fraction


MODEL_INPUTS = {
    "seed_population_density": {"target_plants_per_m2", "field_survival_pct", "survival_basis"},
    "seed_mass_from_seed_density": {"seeds_per_m2", "tkw_g"},
    "area_cost_change": {"zones", "currency", "area_unit"},
    "incremental_margin": {"added_yield", "price_per_yield_unit", "added_costs", "currency", "yield_unit", "area_unit"},
    "soil_carbon_stock": {"carbon_pct", "bulk_density_Mg_per_m3", "depth_m", "coarse_fragment_volume_pct"},
    "soil_total_porosity": {"bulk_density_Mg_per_m3", "particle_density_Mg_per_m3"},
    "remaining_nitrogen_budget": {"target_available_n_kg_per_ha", "credits"},
    "daily_water_balance": {"initial_storage_mm", "effective_rain_mm", "irrigation_mm", "et_mm", "drainage_mm"},
    "ndvi_from_reflectance": {"nir_reflectance", "red_reflectance"},
    "soil_nitrate_n_stock": {"nitrate_n_mg_per_kg", "bulk_density_Mg_per_m3", "depth_m", "material_basis"},
    "land_equivalent_ratio": {"components"},
    "mean_paired_difference": {"treatment_yields", "control_yields", "yield_unit"},
    "lime_equivalent_mass": {"pure_caco3_equivalent_per_area", "effective_neutralizing_value_pct", "mass_unit", "area_unit"},
    "simplified_stress_et": {"unstressed_et_mm_per_day", "stress_multiplier", "stress_application"},
}
MODEL_OPTIONAL_INPUTS = {
    "seed_population_density": {"germination_pct", "mortality_pct"},
    "seed_mass_from_seed_density": {"context_germination_pct"},
    "mean_paired_difference": {"matched_blocks"},
}
MASS_UNITS = ("kg", "t", "Mg", "lb")
YIELD_UNITS = ("kg/ha", "t/ha", "Mg/ha", "lb/ac", "bu/ac")


def _keys(values: Mapping[str, Any], required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(values, Mapping) or not required <= set(values) <= required | (optional or set()):
        raise ValueError("supply exactly the named model-calculation inputs")


def _number(value: Any, name: str, *, positive: bool = False, signed: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{name} must be numeric")
    if isinstance(value, str) and len(value) > 64:
        raise ValueError(f"{name} exceeds supported input precision")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not number.is_finite() or (not signed and number < 0) or (positive and number <= 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative' if not signed else 'numeric'}")
    if len(number.as_tuple().digits) > 12 or number and not -12 <= number.adjusted() <= 10:
        raise ValueError(f"{name} exceeds supported input precision")
    return number


def _choice(value: Any, name: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}")
    return value


def _sequence(value: Any, name: str, *, minimum: int = 1) -> list[Any]:
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= 100:
        raise ValueError(f"{name} must contain {minimum} to 100 supplied entries")
    return list(value)


def validate_model_arithmetic_inputs(operation: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Pure operand/basis/range checks shared by readiness and execution."""
    if operation not in MODEL_INPUTS:
        raise ValueError("unsupported supplied-model operation")
    _keys(inputs, MODEL_INPUTS[operation], MODEL_OPTIONAL_INPUTS.get(operation, set()))
    values: dict[str, Any] = {}
    nested = {"zones", "credits", "components", "added_costs", "treatment_yields", "control_yields"}
    choices = {
        "currency": ("CAD", "USD", "$"), "area_unit": ("ha", "ac"),
        "mass_unit": MASS_UNITS, "yield_unit": (*MASS_UNITS, "bu") if operation == "incremental_margin" else YIELD_UNITS,
        "survival_basis": SEED_SURVIVAL_BASES,
        "material_basis": ("conditional_matching_dry_soil_mass",),
        "stress_application": ("all_et_simplified",),
    }
    positive = {"target_plants_per_m2", "tkw_g", "bulk_density_Mg_per_m3", "particle_density_Mg_per_m3",
                "depth_m", "field_survival_pct", "germination_pct", "effective_neutralizing_value_pct"}
    for name, value in inputs.items():
        if name in nested:
            continue
        values[name] = (_choice(value, name, choices[name]) if name in choices
                        else _number(value, name, positive=name in positive))
    for name in ("carbon_pct", "coarse_fragment_volume_pct", "field_survival_pct", "germination_pct", "context_germination_pct"):
        if name in values and values[name] > 100:
            raise ValueError(f"{name} must be at most 100")
    if operation == "seed_population_density":
        established_fraction(values["field_survival_pct"], values["survival_basis"], values.get("germination_pct"))
        if "mortality_pct" in values:
            if values["mortality_pct"] >= 100 or abs(values["mortality_pct"] + values["field_survival_pct"] - 100) > Decimal("0.0001"):
                raise ValueError("mortality and survival must be complementary percentages on the same basis")
    if operation == "area_cost_change":
        values["zones"] = []
        for zone in _sequence(inputs["zones"], "zones"):
            _keys(zone, {"area", "change_per_area"})
            values["zones"].append({"area": _number(zone["area"], "zone area", positive=True),
                                    "change_per_area": _number(zone["change_per_area"], "cost change", signed=True)})
    if operation == "incremental_margin":
        values["added_costs"] = [_number(cost, "added cost") for cost in _sequence(inputs["added_costs"], "added_costs")]
    if operation == "remaining_nitrogen_budget":
        values["credits"] = []
        for credit in _sequence(inputs["credits"], "credits"):
            _keys(credit, {"source", "available_n_kg_per_ha"})
            source = _choice(credit["source"], "credit source", ("soil", "manure", "other_supplied"))
            values["credits"].append({"source": source, "available_n_kg_per_ha": _number(credit["available_n_kg_per_ha"], "available-N credit")})
    if operation == "land_equivalent_ratio":
        values["components"] = []
        for component in _sequence(inputs["components"], "components", minimum=2):
            _keys(component, {"intercrop_yield", "sole_yield", "yield_unit"})
            values["components"].append({
                "intercrop_yield": _number(component["intercrop_yield"], "intercrop yield"),
                "sole_yield": _number(component["sole_yield"], "sole-crop yield", positive=True),
                "yield_unit": _choice(component["yield_unit"], "component yield unit", YIELD_UNITS),
            })
    if operation == "mean_paired_difference":
        for name in ("treatment_yields", "control_yields"):
            values[name] = [_number(value, name) for value in _sequence(inputs[name], name)]
        if len(values["treatment_yields"]) != len(values["control_yields"]):
            raise ValueError("treatment and control lists must contain the same matched pairs")
        if "matched_blocks" in values and values["matched_blocks"] != len(values["treatment_yields"]):
            raise ValueError("matched block count must equal both supplied list lengths")
    if operation == "soil_total_porosity" and values["bulk_density_Mg_per_m3"] > values["particle_density_Mg_per_m3"]:
        raise ValueError("bulk density must not exceed particle density")
    if operation == "ndvi_from_reflectance":
        if max(values["nir_reflectance"], values["red_reflectance"]) > 1:
            raise ValueError("supply normalized nonnegative reflectances from zero to one, not raw scaled sensor numbers")
        if values["nir_reflectance"] + values["red_reflectance"] == 0:
            raise ValueError("NIR plus red must be positive")
    if operation == "simplified_stress_et" and values["stress_multiplier"] > 1:
        raise ValueError("the supplied stress multiplier must be between zero and one")
    # Prospective range checks are pure validation, not a tool invocation.
    try:
        with localcontext() as context:
            context.prec = 28
            result = _model_outcome(operation, values)[0]
        if not result.is_finite() or result and not -300 <= result.adjusted() <= 23:
            raise ValueError("model result exceeds supported output precision")
    except DecimalException as error:
        raise ValueError("model operands exceed supported arithmetic precision") from error
    return values


def model_arithmetic(operation: str, inputs: Mapping[str, Any]) -> tuple[Decimal, str, str, dict[str, Any], tuple[str, ...], str]:
    values = validate_model_arithmetic_inputs(operation, inputs)
    with localcontext() as context:
        context.prec = 28
        return _model_outcome(operation, values)


def _model_outcome(operation: str, v: dict[str, Any]) -> tuple[Decimal, str, str, dict[str, Any], tuple[str, ...], str]:
    if operation == "seed_population_density":
        fraction, note = established_fraction(v["field_survival_pct"], v["survival_basis"], v.get("germination_pct"))
        value = v["target_plants_per_m2"] / fraction
        return value, "seeds/m²", f"{v['target_plants_per_m2']} plants/m² ÷ {fraction} established plants per seed sown", v, (note,), "The supplied target and establishment percentages are not field estimates made by this calculation."
    if operation == "seed_mass_from_seed_density":
        value = v["seeds_per_m2"] * v["tkw_g"] / 100
        return value, "kg/ha", f"{v['seeds_per_m2']} seeds/m² × {v['tkw_g']} g/1000 seeds × 10000 m²/ha ÷ 1000 g/kg", v, ("input is physical seeds per area, not a target established plant population; germination is not multiplied into seed mass",), "This converts an already supplied seed density; it does not select a sowing density or predict emergence."
    if operation == "area_cost_change":
        area = sum((row["area"] for row in v["zones"]), Decimal(0))
        total = sum((row["area"] * row["change_per_area"] for row in v["zones"]), Decimal(0))
        mean = total / area
        terms = " + ".join(f"({row['area']} {v['area_unit']} × {row['change_per_area']} {v['currency']}/{v['area_unit']})" for row in v["zones"])
        formula = f"represented total cost change = {terms} = {total} {v['currency']}; per represented area = {total} ÷ {area} = {mean} {v['currency']}/{v['area_unit']}"
        return total, v["currency"], formula, v, ("positive is added cost; negative is a saving; supplied zone areas are treated as nonoverlapping",), "The per-area value is whole-field only if these zones cover the whole field; omitted area and its costs remain unknown."
    if operation == "incremental_margin":
        costs = sum(v["added_costs"], Decimal(0))
        returns = v["added_yield"] * v["price_per_yield_unit"]
        value = returns - costs
        return value, f"{v['currency']}/{v['area_unit']}", f"({v['added_yield']} {v['yield_unit']}/{v['area_unit']} × {v['price_per_yield_unit']} {v['currency']}/{v['yield_unit']}) − {costs} {v['currency']}/{v['area_unit']}", v, ("added yield and price are supplied assumptions; yield and price use the same crop-quantity unit",), "This margin includes the specified changes only; it does not predict yield, validate a market price or establish overall return on investment."
    if operation == "soil_carbon_stock":
        fraction = 1 - v["coarse_fragment_volume_pct"] / 100
        value = v["carbon_pct"] * v["bulk_density_Mg_per_m3"] * v["depth_m"] * fraction * 100
        return value, "Mg C/ha", f"({v['carbon_pct']}/100) × {v['bulk_density_Mg_per_m3']} Mg soil/m³ × {v['depth_m']} m × 10000 m²/ha × (1 − {v['coarse_fragment_volume_pct']}/100)", v, ("uniform layer; carbon concentration and bulk density refer to the same dry fine-earth material; coarse fragments are a supplied volume percentage",), "This supplied-layer stock is not evidence of sequestration or a change over time."
    if operation == "soil_total_porosity":
        fraction = 1 - v["bulk_density_Mg_per_m3"] / v["particle_density_Mg_per_m3"]
        return fraction * 100, "%", f"(1 − ({v['bulk_density_Mg_per_m3']} / {v['particle_density_Mg_per_m3']})) × 100; pore-volume fraction = {fraction} m³/m³", v, ("dry bulk density and particle density represent the same soil-solid material/support with matching mass and volume units",), "Total porosity includes water-filled and air-filled pores. Wet bulk density or incompatible fine-earth/whole-soil density support needs correction first. Plant-available water instead depends on water retention between field capacity and wilting point and the root-zone depth."
    if operation == "remaining_nitrogen_budget":
        credits = sum((row["available_n_kg_per_ha"] for row in v["credits"]), Decimal(0))
        value = v["target_available_n_kg_per_ha"] - credits
        return value, "kg N/ha", f"supplied available-N target {v['target_available_n_kg_per_ha']} − credited available N {credits}", v, ("credits are already expressed as available N on the same area basis; no mineralization or availability coefficient is inferred",), "A negative balance is a surplus under the supplied budget, not a negative application rate. The calculation does not choose an N target or fertilizer recommendation."
    if operation == "daily_water_balance":
        value = v["initial_storage_mm"] + v["effective_rain_mm"] + v["irrigation_mm"] - v["et_mm"] - v["drainage_mm"]
        if value < 0:
            raise ValueError("outflows exceed supplied initial storage and inflows; define unmet demand rather than reporting negative physical water storage")
        return value, "mm", f"{v['initial_storage_mm']} + {v['effective_rain_mm']} + {v['irrigation_mm']} − {v['et_mm']} − {v['drainage_mm']}", v, ("effective rainfall is net input; all terms share the supplied daily interval and storage support",), "This balances the specified terms only; storage capacity, unlisted fluxes and irrigation timing are not established."
    if operation == "ndvi_from_reflectance":
        value = (v["nir_reflectance"] - v["red_reflectance"]) / (v["nir_reflectance"] + v["red_reflectance"])
        return value, "NDVI", f"({v['nir_reflectance']} − {v['red_reflectance']}) ÷ ({v['nir_reflectance']} + {v['red_reflectance']})", v, ("NIR and red are normalized reflectances on matching support, not unconverted digital numbers",), "This band ratio alone does not diagnose crop stress, its cause or yield; scene quality, comparable support and crop stage still matter."
    if operation == "soil_nitrate_n_stock":
        value = v["nitrate_n_mg_per_kg"] * v["bulk_density_Mg_per_m3"] * v["depth_m"] * 10
        return value, "kg nitrate-N/ha", f"{v['nitrate_n_mg_per_kg']} mg N/kg soil × {v['bulk_density_Mg_per_m3']} Mg soil/m³ × {v['depth_m']} m × 10", v, ("conditional on concentration and bulk density referring to matching dry-soil mass support in a uniform layer; no missing coarse-fragment fraction is set to zero",), "This is a conditional stock in the stated layer, not crop-available N or a fertilizer credit; incompatible material support needs correction before field interpretation."
    if operation == "land_equivalent_ratio":
        ratios = [row["intercrop_yield"] / row["sole_yield"] for row in v["components"]]
        value = sum(ratios, Decimal(0))
        terms = " + ".join(f"({row['intercrop_yield']} / {row['sole_yield']})" for row in v["components"])
        return value, "LER", terms, v, ("each intercrop yield is per total intercrop area; each sole-crop yield is per sole-crop area, with matching units within its crop",), "Yields per crop's own strip need total-intercrop-area normalization first. This yield-based land-equivalence ratio does not establish profitability or a recommendation to intercrop."
    if operation == "mean_paired_difference":
        differences = [treatment - control for treatment, control in zip(v["treatment_yields"], v["control_yields"], strict=True)]
        value = sum(differences, Decimal(0)) / len(differences)
        displayed = ", ".join(str(difference) for difference in differences)
        return value, v["yield_unit"], f"sum of matched treatment-minus-control differences [{displayed}] ÷ {len(differences)}", v, ("lists are paired in the supplied block order; every pair is retained",), "A mean paired difference alone does not establish statistical significance, uncertainty or a treatment recommendation."
    if operation == "lime_equivalent_mass":
        value = v["pure_caco3_equivalent_per_area"] / (v["effective_neutralizing_value_pct"] / 100)
        return value, f"{v['mass_unit']}/{v['area_unit']}", f"{v['pure_caco3_equivalent_per_area']} pure-CaCO3-equivalent {v['mass_unit']}/{v['area_unit']} ÷ ({v['effective_neutralizing_value_pct']}/100)", v, ("the supplied effective neutralizing value applies on the stated material mass basis; it is not treated as a nutrient mass fraction",), "This adjusts a supplied equivalence target; soil-test lime requirement, product moisture/basis and field application suitability remain separate checks."
    if operation == "simplified_stress_et":
        value = v["unstressed_et_mm_per_day"] * v["stress_multiplier"]
        return value, "mm/day", f"{v['unstressed_et_mm_per_day']} mm/day × {v['stress_multiplier']}", v, ("the supplied simplified model applies its stress multiplier to all ET",), "This does not separately model soil evaporation and crop transpiration; the FAO dual-coefficient water-stress relationship is different."
    raise ValueError("unsupported supplied-model operation")
