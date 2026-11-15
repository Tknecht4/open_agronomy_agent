"""Independent arithmetic examples and input/basis countercontrols."""
from copy import deepcopy
from decimal import Decimal

import pytest

from agronomy_agent.supplied_model_arithmetic import (
    MODEL_INPUTS, model_arithmetic, validate_model_arithmetic_inputs,
)


EXAMPLES = {
    "seed_population_density": ({"target_plants_per_m2": 240, "germination_pct": 80,
        "field_survival_pct": 75, "survival_basis": "germinated_seeds"}, "400", "seeds/m²"),
    "seed_mass_from_seed_density": ({"seeds_per_m2": 350, "tkw_g": 30}, "105", "kg/ha"),
    "area_cost_change": ({"zones": [{"area": 2, "change_per_area": -15}, {"area": 3, "change_per_area": 20}],
        "currency": "CAD", "area_unit": "ha"}, "30", "CAD"),
    "incremental_margin": ({"added_yield": ".3", "price_per_yield_unit": 250, "added_costs": [20, 10],
        "currency": "$", "yield_unit": "t", "area_unit": "ha"}, "45", "$/ha"),
    "soil_carbon_stock": ({"carbon_pct": "1.5", "bulk_density_Mg_per_m3": "1.4", "depth_m": ".3",
        "coarse_fragment_volume_pct": 10}, "56.7", "Mg C/ha"),
    "soil_total_porosity": ({"bulk_density_Mg_per_m3": "1.2", "particle_density_Mg_per_m3": "2.4"}, "50", "%"),
    "remaining_nitrogen_budget": ({"target_available_n_kg_per_ha": 180,
        "credits": [{"source": "soil", "available_n_kg_per_ha": 50},
                    {"source": "manure", "available_n_kg_per_ha": 20}]}, "110", "kg N/ha"),
    "daily_water_balance": ({"initial_storage_mm": 90, "effective_rain_mm": 12,
        "irrigation_mm": 8, "et_mm": 7, "drainage_mm": 3}, "100", "mm"),
    "ndvi_from_reflectance": ({"nir_reflectance": ".7", "red_reflectance": ".3"}, ".4", "NDVI"),
    "soil_nitrate_n_stock": ({"nitrate_n_mg_per_kg": 12, "bulk_density_Mg_per_m3": "1.4",
        "depth_m": ".25", "material_basis": "conditional_matching_dry_soil_mass"}, "42", "kg nitrate-N/ha"),
    "land_equivalent_ratio": ({"components": [
        {"intercrop_yield": 4, "sole_yield": 5, "yield_unit": "t/ha"},
        {"intercrop_yield": 2, "sole_yield": 4, "yield_unit": "t/ha"}]}, "1.3", "LER"),
    "mean_paired_difference": ({"treatment_yields": ["3.2", "3.8", "4.0"],
        "control_yields": ["3.0", "3.4", "4.3"], "yield_unit": "t/ha", "matched_blocks": 3}, ".1", "t/ha"),
    "lime_equivalent_mass": ({"pure_caco3_equivalent_per_area": 3,
        "effective_neutralizing_value_pct": 120, "mass_unit": "t", "area_unit": "ha"}, "2.5", "t/ha"),
    "simplified_stress_et": ({"unstressed_et_mm_per_day": 5, "stress_multiplier": ".6",
        "stress_application": "all_et_simplified"}, "3", "mm/day"),
}


@pytest.mark.parametrize("operation", sorted(EXAMPLES))
def test_supplied_models_compute_independent_examples_without_mutating_inputs(operation):
    assert set(EXAMPLES) == set(MODEL_INPUTS)
    inputs, expected, expected_unit = EXAMPLES[operation]
    original = deepcopy(inputs)
    value, unit, formula, normalized, assumptions, boundary = model_arithmetic(operation, inputs)
    assert value == Decimal(expected)
    assert unit == expected_unit and formula and normalized and assumptions and boundary
    assert inputs == original


@pytest.mark.parametrize("operation", sorted(EXAMPLES))
def test_registered_calculator_contract_executes_each_model_with_its_full_record(operation):
    from agronomy_agent.agronomic_calculations import CalculationOperation, FoundationCalculationOperation, calculate_agronomic, calculation_tool_schema
    from agronomy_agent.calculator_contracts import tool_version_for, CALCULATOR_VERSION
    inputs, expected, expected_unit = EXAMPLES[operation]
    assert len(CalculationOperation) == 12  # Historical harness inventory stays frozen.
    assert operation in {item.value for item in FoundationCalculationOperation}
    schema = calculation_tool_schema()
    assert set(schema['operations'][operation]['required']) == MODEL_INPUTS[operation]
    result = calculate_agronomic(operation, inputs)
    assert result.value == Decimal(expected) and result.unit == expected_unit
    record = result.as_record()
    assert record['operation'] == operation and record['formula'] and record['assumptions']
    assert record['answer'] == result.answer() and record['boundary']
    assert tool_version_for(operation) == CALCULATOR_VERSION


@pytest.mark.parametrize("operation", sorted(EXAMPLES))
def test_model_contract_never_discards_an_extra_operand(operation):
    inputs = {**deepcopy(EXAMPLES[operation][0]), "unhandled_quantity": 7}
    with pytest.raises(ValueError, match="exactly"):
        validate_model_arithmetic_inputs(operation, inputs)


@pytest.mark.parametrize("operation", sorted(EXAMPLES))
def test_model_contract_requires_every_named_operand(operation):
    for key in MODEL_INPUTS[operation]:
        inputs = deepcopy(EXAMPLES[operation][0]);inputs.pop(key)
        with pytest.raises(ValueError, match="exactly"):
            validate_model_arithmetic_inputs(operation, inputs)


@pytest.mark.parametrize("bad", [True, False, None, "NaN", "Infinity", "-Infinity", "1e1000", "1e-1000", "9" * 100])
def test_model_numeric_values_are_bounded_and_never_booleans(bad):
    with pytest.raises(ValueError):
        validate_model_arithmetic_inputs("seed_mass_from_seed_density", {"seeds_per_m2": bad, "tkw_g": 30})


def test_seed_density_is_not_established_plant_density_or_double_germination():
    value, _, _, inputs, _, _ = model_arithmetic("seed_population_density", {
        "target_plants_per_m2": 240, "germination_pct": 80, "field_survival_pct": 75, "survival_basis": "seeds_sown"})
    assert value == 320 and inputs["germination_pct"] == 80
    mass = model_arithmetic("seed_mass_from_seed_density", {"seeds_per_m2": 350, "tkw_g": 30, "context_germination_pct": 0})
    assert mass[0] == 105 and mass[3]["context_germination_pct"] == 0
    with pytest.raises(ValueError):
        validate_model_arithmetic_inputs("seed_mass_from_seed_density", {"target_plants_per_m2": 350, "tkw_g": 30})


@pytest.mark.parametrize("changes", [
    {"germination_pct": 101}, {"field_survival_pct": 0}, {"survival_basis": "unknown"},
    {"mortality_pct": 20}, {"germination_pct": None},
])
def test_seed_establishment_basis_and_percentages_remain_explicit(changes):
    with pytest.raises(ValueError):
        validate_model_arithmetic_inputs("seed_population_density", {**EXAMPLES["seed_population_density"][0], **changes})


def test_a_nitrogen_budget_surplus_is_signed_not_a_negative_application():
    value, _, _, _, _, limit = model_arithmetic("remaining_nitrogen_budget", {
        "target_available_n_kg_per_ha": 100, "credits": [{"source": "soil", "available_n_kg_per_ha": 110}]})
    assert value == -10 and "surplus" in limit and "not a negative application" in limit


def test_carbon_rock_volume_cannot_default_to_zero_and_nitrate_support_is_conditional():
    inputs = deepcopy(EXAMPLES["soil_carbon_stock"][0]);inputs.pop("coarse_fragment_volume_pct")
    with pytest.raises(ValueError):
        validate_model_arithmetic_inputs("soil_carbon_stock", inputs)
    result = model_arithmetic("soil_nitrate_n_stock", EXAMPLES["soil_nitrate_n_stock"][0])
    assert "no missing coarse-fragment fraction is set to zero" in result[4][0]
    with pytest.raises(ValueError):
        validate_model_arithmetic_inputs("soil_nitrate_n_stock", {
            **EXAMPLES["soil_nitrate_n_stock"][0], "material_basis": "confirmed_field_stock"})


@pytest.mark.parametrize("operation,changes", [
    ("soil_total_porosity", {"bulk_density_Mg_per_m3": 3}),
    ("soil_total_porosity", {"particle_density_Mg_per_m3": 0}),
    ("soil_carbon_stock", {"coarse_fragment_volume_pct": 110}),
    ("daily_water_balance", {"et_mm": 120}),
    ("ndvi_from_reflectance", {"nir_reflectance": 7000, "red_reflectance": 3000}),
    ("ndvi_from_reflectance", {"nir_reflectance": 0, "red_reflectance": 0}),
    ("ndvi_from_reflectance", {"red_reflectance": "-.1"}),
    ("simplified_stress_et", {"stress_multiplier": "1.1"}),
    ("simplified_stress_et", {"stress_application": "FAO_dual_coefficient"}),
    ("lime_equivalent_mass", {"effective_neutralizing_value_pct": 0}),
    ("mean_paired_difference", {"control_yields": [3, 4]}),
    ("mean_paired_difference", {"matched_blocks": 2}),
    ("mean_paired_difference", {"treatment_yields": []}),
])
def test_invalid_physical_bases_methods_or_pairings_fail_validation(operation, changes):
    with pytest.raises(ValueError):
        validate_model_arithmetic_inputs(operation, {**deepcopy(EXAMPLES[operation][0]), **changes})


def test_ler_keeps_components_and_cannot_divide_by_zero_or_ignore_extra_fields():
    for change in [{"sole_yield": 0}, {"extra_yield": 2}, {"yield_unit": "kg"}]:
        inputs = deepcopy(EXAMPLES["land_equivalent_ratio"][0]);inputs["components"][0].update(change)
        with pytest.raises(ValueError):
            validate_model_arithmetic_inputs("land_equivalent_ratio", inputs)


def test_cost_mean_is_explicitly_conditional_on_whole_field_coverage():
    result = model_arithmetic("area_cost_change", EXAMPLES["area_cost_change"][0])
    assert "6 CAD/ha" in result[2]
    assert "whole-field only if" in result[5] and "omitted area" in result[5].lower()


def test_ler_and_porosity_expose_required_physical_support_conventions():
    ler = model_arithmetic("land_equivalent_ratio", EXAMPLES["land_equivalent_ratio"][0])
    porosity = model_arithmetic("soil_total_porosity", EXAMPLES["soil_total_porosity"][0])
    assert "per total intercrop area" in ler[4][0] and "own strip" in ler[5]
    assert "dry bulk density" in porosity[4][0] and "same soil-solid material/support" in porosity[4][0]
    assert "Wet bulk density" in porosity[5]
