"""Current typed-calculator identities shared by planning and verification."""

import re

CALCULATOR_VERSION = "agronomic_calculator_v3"
LEGACY_CALCULATOR_VERSION = "agronomic_calculator_v1"
CALCULATOR_SCHEMA_VERSION = "open_agronomy_agent.agronomic_calculator.schema.v3"
TOOL_PLANNER_VERSION = "open_agronomy_agent.tool_planner.v3"
EXPLICIT_ARITHMETIC_SELECTOR_ID = "explicit_arithmetic_parser_v3"

FOUNDATION_OPERATIONS = frozenset({
    "seed_rate_mass_imperial",
    "break_even_price",
    "break_even_yield",
    "current_ratio",
    "debt_to_asset_percent",
    "fertilizer_field_total",
    "soil_water_storage",
    "nutrient_basis_conversion",
    "apparent_nutrient_balance",
    "liquid_product_total",
    "water_storage_difference",
    "crop_evapotranspiration",
    "gross_irrigation_depth",
    "water_depth_volume",
    "grain_moisture_adjustment",
    "single_nozzle_application_volume",
    "mean_temperature_gdd",
    "grain_harvest_index",
    "circular_sampling_area",
})


def tool_version_for(operation: str) -> str:
    """Keep unchanged v1 contracts distinct from current additions/revisions."""

    return CALCULATOR_VERSION if operation in FOUNDATION_OPERATIONS or operation == "seed_rate_mass" else LEGACY_CALCULATOR_VERSION


def supplied_input_label(name: str) -> str:
    """Display new supplied-quantity gaps without exposing internal keys."""
    return {
        "quantity_kg_per_ha": "quantity in kg nutrient/ha",
        "from_basis": "original nutrient basis", "to_basis": "requested nutrient basis",
        "area_ha": "area in hectares", "product_rate_l_per_ha": "supplied product rate in L/ha",
        "nutrient_target_kg_per_ha": "supplied nutrient amount in kg/ha",
        "nutrient_percent": "nutrient concentration on the stated basis (%)",
        "nutrient_label": "one explicit nutrient basis",
        "upper_volumetric": "field capacity as a volumetric fraction",
        "lower_volumetric": "the comparison water content as a volumetric fraction",
        "root_depth_m": "root-zone depth in metres",
        "crop_coefficient": "supplied crop coefficient Kc",
        "reference_et_mm_per_day": "supplied reference ET in mm/day",
        "net_depth_mm": "supplied net irrigation depth in mm",
        "application_efficiency_pct": "application efficiency (%)",
        "depth_mm": "water depth in mm",
        "grain_dry_mass": "grain dry mass", "aboveground_dry_mass": "total above-ground dry biomass including grain",
        "radius_m": "one sampling-circle radius in metres",
        "wet_mass": "wet grain mass or yield", "mass_unit": "mass unit (kg, tonnes or lb, including any ha/ac denominator)",
        "flow_l_per_min_per_nozzle": "nozzle flow in L/min", "speed_km_per_h": "travel speed in km/h",
        "boom_width_m": "effective treated width or nozzle spacing in metres",
        "nozzle_spacing_m": "nozzle spacing in metres",
        "initial_moisture_pct": "initial wet-basis moisture (%)",
        "target_moisture_pct": "target wet-basis moisture (%)",
        "mean_temp_c": "one supplied daily mean temperature in Celsius",
        "base_temp_c": "base temperature in Celsius",
    }.get(name, name)


def format_calculator_clarification(missing_inputs: tuple[str, ...]) -> str:
    """One text contract for planner output and answerability replay."""

    if any(item.startswith("invalid ") for item in missing_inputs):
        return "I can't calculate from these inputs: " + "; ".join(
            item.removeprefix("invalid ") for item in missing_inputs
        ) + "."
    return "To calculate this, provide " + ", ".join(missing_inputs) + "."


def calculation_request_text(question: str, operation: str) -> str:
    """Remove only explanatory co-outputs already owned by this renderer."""
    if operation == "circular_sampling_area":
        return re.sub(r"\s*Explain why (?:it|this) is not (?:the )?(?:farm )?field area[.!?]?\s*$", "", question, flags=re.I)
    return question


def calculation_request_is_complete(question: str, operation: str) -> bool:
    """A valid calculation can be evidence without completing a compound task."""
    from agronomy_agent.request_scope import has_unqualified_followup
    return not has_unqualified_followup(calculation_request_text(question, operation), calculation=True)
