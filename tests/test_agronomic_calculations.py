from __future__ import annotations

from decimal import Decimal

import pytest

from agronomy_agent.agronomic_calculations import (
    CalculationOperation,
    agronomic_calculator,
    calculate_agronomic,
    calculation_tool_schema,
)


@pytest.mark.parametrize(
    ("operation", "inputs", "value", "unit"),
    [
        (
            "seed_rate_mass",
            {
                "target_plants_per_m2": 250,
                "tkw_g": 40,
                "germination_pct": 92,
                "field_survival_pct": 88,
            },
            123.5178,
            "kg/ha",
        ),
        (
            "fertilizer_product_mass",
            {"nutrient_target_kg_per_ha": 72, "nutrient_percent": 46, "nutrient_label": "N"},
            156.5217,
            "kg product/ha",
        ),
        (
            "nutrient_delivery",
            {"product_rate_kg_per_ha": 180, "nutrient_percent": 28, "nutrient_label": "N"},
            50.4,
            "kg N/ha",
        ),
        (
            "sprayer_application_volume",
            {
                "nozzle_count": 20,
                "flow_l_per_min_per_nozzle": 1.1,
                "speed_km_per_h": 10,
                "boom_width_m": 11,
            },
            120,
            "L/ha",
        ),
        (
            "tank_coverage",
            {"tank_volume_l": 2400, "application_volume_l_per_ha": 120},
            20,
            "ha",
        ),
        (
            "daily_gdd",
            {"max_temp_c": 22, "min_temp_c": 8, "base_temp_c": 5},
            10,
            "GDD",
        ),
        (
            "accumulated_gdd",
            {"daily_gdd_values": [5, 8, 10, 7]},
            30,
            "GDD",
        ),
        (
            "row_population",
            {"plants_per_row_m": 18, "row_spacing_m": 0.30},
            60,
            "plants/m²",
        ),
        (
            "field_product_total",
            {"area_ha": 42, "product_rate_kg_per_ha": 75},
            3150,
            "kg",
        ),
        (
            "area_weighted_average",
            {
                "total_area_ha": 120,
                "zones": [{"area_ha": 30, "value": 60}, {"area_ha": 90, "value": 40}],
                "value_unit": "bu/ac",
            },
            45,
            "bu/ac",
        ),
        (
            "partial_budget",
            {"added_returns": 120, "reduced_costs": 20, "added_costs": 75, "reduced_returns": 10},
            55,
            "CAD",
        ),
    ],
)
def test_structured_calculator_operations(
    operation: str,
    inputs: dict[str, object],
    value: float,
    unit: str,
) -> None:
    result = calculate_agronomic(operation, inputs)

    assert float(result.value) == pytest.approx(value, rel=1e-4)
    assert result.unit == unit
    assert result.kind == operation
    assert unit in result.answer()
    assert "does not choose an agronomic target" in result.boundary


def test_unit_conversion_is_directional_and_round_trips() -> None:
    to_metric = calculate_agronomic(
        "unit_conversion",
        {"value": 100, "from_unit": "lb/ac", "to_unit": "kg/ha"},
    )
    back = calculate_agronomic(
        "unit_conversion",
        {"value": to_metric.value, "from_unit": "kg/ha", "to_unit": "lb/ac"},
    )

    assert float(to_metric.value) == pytest.approx(112.0851156)
    assert float(back.value) == pytest.approx(100)


def test_inverse_conversion_matches_dimensional_factor() -> None:
    result = calculate_agronomic(
        "unit_conversion",
        {"value": 100, "from_unit": "kg/ha", "to_unit": "lb/ac"},
    )

    assert float(result.value) == pytest.approx(89.2179, rel=1e-5)


def test_weighted_average_rejects_unaccounted_area() -> None:
    with pytest.raises(ValueError, match="zone areas total 80 ha but total_area_ha is 100 ha"):
        calculate_agronomic(
            "area_weighted_average",
            {
                "total_area_ha": 100,
                "zones": [{"area_ha": 40, "value": 50}, {"area_ha": 40, "value": 45}],
                "value_unit": "bu/ac",
            },
        )


@pytest.mark.parametrize(
    ("operation", "inputs", "message"),
    [
        ("seed_rate_mass", {"target_plants_per_m2": 250}, "missing required fields"),
        (
            "seed_rate_mass",
            {"target_plants_per_m2": 250, "tkw_g": 40, "germination_pct": 110, "field_survival_pct": 88},
            "germination_pct",
        ),
        (
            "unit_conversion",
            {"value": 1, "from_unit": "kg/ha", "to_unit": "ha"},
            "dimensions differ",
        ),
        (
            "tank_coverage",
            {"tank_volume_l": 1000, "application_volume_l_per_ha": 100, "unusable_volume_l": 1000},
            "smaller than",
        ),
    ],
)
def test_invalid_requests_fail_closed(operation: str, inputs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_agronomic(operation, inputs)


def test_json_tool_surface_preserves_decimal_and_schema() -> None:
    payload = agronomic_calculator(
        "field_product_total",
        {"area_ha": Decimal("42"), "product_rate_kg_per_ha": Decimal("75")},
    )

    assert payload["schema_version"] == "open_agronomy_agent.agronomic_calculation.v2"
    assert payload["tool"] == "agronomic_calculator"
    assert payload["value"] == 3150.0
    assert payload["value_decimal"] == "3150"


def test_tool_schema_lists_every_operation() -> None:
    schema = calculation_tool_schema()

    assert schema["input"]["properties"]["operation"]["enum"] == [
        operation.value for operation in CalculationOperation
    ]
    assert set(schema["operations"]) == {operation.value for operation in CalculationOperation}
