from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Any, Mapping, Sequence


class CalculationOperation(StrEnum):
    UNIT_CONVERSION = "unit_conversion"
    SEED_RATE_MASS = "seed_rate_mass"
    FERTILIZER_PRODUCT_MASS = "fertilizer_product_mass"
    NUTRIENT_DELIVERY = "nutrient_delivery"
    SPRAYER_APPLICATION_VOLUME = "sprayer_application_volume"
    TANK_COVERAGE = "tank_coverage"
    DAILY_GDD = "daily_gdd"
    ACCUMULATED_GDD = "accumulated_gdd"
    ROW_POPULATION = "row_population"
    FIELD_PRODUCT_TOTAL = "field_product_total"
    AREA_WEIGHTED_AVERAGE = "area_weighted_average"
    PARTIAL_BUDGET = "partial_budget"


_ARITHMETIC_BOUNDARY = (
    "This tool verifies arithmetic from supplied inputs only. It does not choose an agronomic target, "
    "confirm a product label, or establish that a rate or operation is appropriate for the field."
)


@dataclass(frozen=True)
class AgronomicCalculation:
    operation: CalculationOperation
    value: Decimal
    unit: str
    formula: str
    inputs: dict[str, Any]
    assumptions: tuple[str, ...] = ()
    boundary: str = _ARITHMETIC_BOUNDARY

    @property
    def kind(self) -> str:
        """Compatibility alias for older trace readers."""

        return self.operation.value

    def answer(self) -> str:
        result = f"{_format_decimal(self.value)} {self.unit}".strip()
        text = f"{result}. Calculation: {self.formula}."
        if self.assumptions:
            text += " Assumptions: " + "; ".join(self.assumptions) + "."
        return f"{text} {self.boundary}"

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": "open_agronomy_agent.agronomic_calculation.v2",
            "status": "calculated",
            "tool": "agronomic_calculator",
            "operation": self.operation.value,
            "kind": self.operation.value,
            "value": float(self.value),
            "value_decimal": _decimal_text(self.value),
            "unit": self.unit,
            "formula": self.formula,
            "inputs": _json_ready(self.inputs),
            "assumptions": list(self.assumptions),
            "boundary": self.boundary,
            "answer": self.answer(),
        }


def calculation_tool_schema() -> dict[str, Any]:
    """Return the stable structured contract exposed to local agent runtimes."""

    return {
        "schema_version": "open_agronomy_agent.agronomic_calculator.schema.v1",
        "tool": "agronomic_calculator",
        "input": {
            "type": "object",
            "required": ["operation", "inputs"],
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [operation.value for operation in CalculationOperation],
                },
                "inputs": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "operations": {
            "unit_conversion": {
                "required": ["value", "from_unit", "to_unit"],
                "supported_units": ["kg/ha", "lb/ac", "ha", "ac", "L/ha", "US gal/ac"],
            },
            "seed_rate_mass": {
                "required": ["target_plants_per_m2", "tkw_g", "germination_pct", "field_survival_pct"],
            },
            "fertilizer_product_mass": {
                "required": ["nutrient_target_kg_per_ha", "nutrient_percent"],
                "optional": ["nutrient_label"],
            },
            "nutrient_delivery": {
                "required": ["product_rate_kg_per_ha", "nutrient_percent"],
                "optional": ["nutrient_label"],
            },
            "sprayer_application_volume": {
                "required": ["nozzle_count", "flow_l_per_min_per_nozzle", "speed_km_per_h", "boom_width_m"],
            },
            "tank_coverage": {
                "required": ["tank_volume_l", "application_volume_l_per_ha"],
                "optional": ["unusable_volume_l"],
            },
            "daily_gdd": {
                "required": ["max_temp_c", "min_temp_c", "base_temp_c"],
                "optional": ["lower_cap_c", "upper_cap_c"],
            },
            "accumulated_gdd": {"required": ["daily_gdd_values"]},
            "row_population": {"required": ["plants_per_row_m", "row_spacing_m"]},
            "field_product_total": {"required": ["area_ha", "product_rate_kg_per_ha"]},
            "area_weighted_average": {
                "required": ["total_area_ha", "zones", "value_unit"],
                "zone_schema": {"required": ["area_ha", "value"]},
            },
            "partial_budget": {
                "required": ["added_returns", "reduced_costs", "added_costs", "reduced_returns"],
                "optional": ["currency"],
            },
        },
        "boundary": _ARITHMETIC_BOUNDARY,
    }


def calculate_agronomic(operation: str | CalculationOperation, inputs: Mapping[str, Any]) -> AgronomicCalculation:
    """Execute one validated calculation from structured inputs.

    Natural-language interpretation is intentionally outside this function. A
    caller must select an operation and provide explicit named quantities. This
    keeps arithmetic deterministic, auditable, and independent of model size.
    """

    try:
        selected = operation if isinstance(operation, CalculationOperation) else CalculationOperation(str(operation))
    except ValueError as exc:
        supported = ", ".join(item.value for item in CalculationOperation)
        raise ValueError(f"unknown calculation operation {operation!r}; supported: {supported}") from exc
    if not isinstance(inputs, Mapping):
        raise ValueError("calculation inputs must be an object")

    handlers = {
        CalculationOperation.UNIT_CONVERSION: _unit_conversion,
        CalculationOperation.SEED_RATE_MASS: _seed_rate_mass,
        CalculationOperation.FERTILIZER_PRODUCT_MASS: _fertilizer_product_mass,
        CalculationOperation.NUTRIENT_DELIVERY: _nutrient_delivery,
        CalculationOperation.SPRAYER_APPLICATION_VOLUME: _sprayer_application_volume,
        CalculationOperation.TANK_COVERAGE: _tank_coverage,
        CalculationOperation.DAILY_GDD: _daily_gdd,
        CalculationOperation.ACCUMULATED_GDD: _accumulated_gdd,
        CalculationOperation.ROW_POPULATION: _row_population,
        CalculationOperation.FIELD_PRODUCT_TOTAL: _field_product_total,
        CalculationOperation.AREA_WEIGHTED_AVERAGE: _area_weighted_average,
        CalculationOperation.PARTIAL_BUDGET: _partial_budget,
    }
    return handlers[selected](inputs)


def agronomic_calculator(operation: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """JSON-ready local tool adapter."""

    return calculate_agronomic(operation, inputs).as_record()


_UNIT_ALIASES = {
    "kg/ha": "kg/ha",
    "kg ha-1": "kg/ha",
    "lb/ac": "lb/ac",
    "lb/acre": "lb/ac",
    "ha": "ha",
    "hectare": "ha",
    "hectares": "ha",
    "ac": "ac",
    "acre": "ac",
    "acres": "ac",
    "l/ha": "L/ha",
    "litre/ha": "L/ha",
    "litres/ha": "L/ha",
    "us gal/ac": "US gal/ac",
    "gal/ac": "US gal/ac",
}

# Multipliers convert a quantity into the dimension's canonical unit.
_UNIT_DIMENSIONS = {
    "kg/ha": ("mass_per_area", Decimal("1")),
    "lb/ac": ("mass_per_area", Decimal("1.120851156")),
    "ha": ("area", Decimal("1")),
    "ac": ("area", Decimal("0.40468564224")),
    "L/ha": ("volume_per_area", Decimal("1")),
    "US gal/ac": ("volume_per_area", Decimal("9.35395818")),
}


def _unit_conversion(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(inputs, required={"value", "from_unit", "to_unit"})
    value = _decimal(inputs, "value")
    from_unit = _unit(inputs.get("from_unit"))
    to_unit = _unit(inputs.get("to_unit"))
    from_dimension, from_factor = _UNIT_DIMENSIONS[from_unit]
    to_dimension, to_factor = _UNIT_DIMENSIONS[to_unit]
    if from_dimension != to_dimension:
        raise ValueError(f"cannot convert {from_unit} to {to_unit}: dimensions differ")
    answer = value * from_factor / to_factor
    factor = from_factor / to_factor
    return _result(
        CalculationOperation.UNIT_CONVERSION,
        answer,
        to_unit,
        f"{_format_decimal(value)} {from_unit} × {_format_decimal(factor)} = {_format_decimal(answer)} {to_unit}",
        {"value": value, "from_unit": from_unit, "to_unit": to_unit, "conversion_factor": factor},
    )


def _seed_rate_mass(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    required = {"target_plants_per_m2", "tkw_g", "germination_pct", "field_survival_pct"}
    _require_only(inputs, required=required)
    target = _positive(inputs, "target_plants_per_m2")
    tkw = _positive(inputs, "tkw_g")
    germination = _percent(inputs, "germination_pct") / Decimal("100")
    survival = _percent(inputs, "field_survival_pct") / Decimal("100")
    answer = target * tkw / (germination * survival * Decimal("100"))
    return _result(
        CalculationOperation.SEED_RATE_MASS,
        answer,
        "kg/ha",
        (
            f"({_format_decimal(target)} plants/m² × {_format_decimal(tkw)} g/1,000 seeds) ÷ "
            f"({_format_decimal(germination)} × {_format_decimal(survival)} × 100) = "
            f"{_format_decimal(answer)} kg/ha"
        ),
        {
            "target_plants_per_m2": target,
            "tkw_g": tkw,
            "germination_pct": germination * Decimal("100"),
            "field_survival_pct": survival * Decimal("100"),
        },
    )


def _fertilizer_product_mass(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(
        inputs,
        required={"nutrient_target_kg_per_ha", "nutrient_percent"},
        optional={"nutrient_label"},
    )
    target = _positive(inputs, "nutrient_target_kg_per_ha")
    percent = _percent(inputs, "nutrient_percent")
    nutrient = str(inputs.get("nutrient_label") or "nutrient").strip() or "nutrient"
    answer = target / (percent / Decimal("100"))
    return _result(
        CalculationOperation.FERTILIZER_PRODUCT_MASS,
        answer,
        "kg product/ha",
        f"{_format_decimal(target)} kg {nutrient}/ha ÷ {_format_decimal(percent / Decimal('100'))} = {_format_decimal(answer)} kg product/ha",
        {"nutrient_target_kg_per_ha": target, "nutrient_percent": percent, "nutrient_label": nutrient},
    )


def _nutrient_delivery(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(
        inputs,
        required={"product_rate_kg_per_ha", "nutrient_percent"},
        optional={"nutrient_label"},
    )
    rate = _nonnegative(inputs, "product_rate_kg_per_ha")
    percent = _percent(inputs, "nutrient_percent")
    nutrient = str(inputs.get("nutrient_label") or "nutrient").strip() or "nutrient"
    answer = rate * percent / Decimal("100")
    return _result(
        CalculationOperation.NUTRIENT_DELIVERY,
        answer,
        f"kg {nutrient}/ha",
        f"{_format_decimal(rate)} kg product/ha × {_format_decimal(percent / Decimal('100'))} = {_format_decimal(answer)} kg {nutrient}/ha",
        {"product_rate_kg_per_ha": rate, "nutrient_percent": percent, "nutrient_label": nutrient},
    )


def _sprayer_application_volume(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    required = {"nozzle_count", "flow_l_per_min_per_nozzle", "speed_km_per_h", "boom_width_m"}
    _require_only(inputs, required=required)
    nozzle_count = _positive(inputs, "nozzle_count")
    if nozzle_count != nozzle_count.to_integral_value():
        raise ValueError("nozzle_count must be a whole number")
    flow = _positive(inputs, "flow_l_per_min_per_nozzle")
    speed = _positive(inputs, "speed_km_per_h")
    boom = _positive(inputs, "boom_width_m")
    answer = nozzle_count * flow * Decimal("600") / (speed * boom)
    return _result(
        CalculationOperation.SPRAYER_APPLICATION_VOLUME,
        answer,
        "L/ha",
        f"({_format_decimal(nozzle_count)} × {_format_decimal(flow)} L/min × 600) ÷ ({_format_decimal(speed)} km/h × {_format_decimal(boom)} m) = {_format_decimal(answer)} L/ha",
        {
            "nozzle_count": nozzle_count,
            "flow_l_per_min_per_nozzle": flow,
            "speed_km_per_h": speed,
            "boom_width_m": boom,
        },
    )


def _tank_coverage(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(
        inputs,
        required={"tank_volume_l", "application_volume_l_per_ha"},
        optional={"unusable_volume_l"},
    )
    tank = _positive(inputs, "tank_volume_l")
    rate = _positive(inputs, "application_volume_l_per_ha")
    unusable = _nonnegative(inputs, "unusable_volume_l", default=Decimal("0"))
    if unusable >= tank:
        raise ValueError("unusable_volume_l must be smaller than tank_volume_l")
    usable = tank - unusable
    answer = usable / rate
    assumptions = () if unusable else ("unusable tank volume supplied as zero",)
    return _result(
        CalculationOperation.TANK_COVERAGE,
        answer,
        "ha",
        f"({_format_decimal(tank)} L − {_format_decimal(unusable)} L) ÷ {_format_decimal(rate)} L/ha = {_format_decimal(answer)} ha",
        {"tank_volume_l": tank, "application_volume_l_per_ha": rate, "unusable_volume_l": unusable},
        assumptions=assumptions,
    )


def _daily_gdd(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(
        inputs,
        required={"max_temp_c", "min_temp_c", "base_temp_c"},
        optional={"lower_cap_c", "upper_cap_c"},
    )
    maximum = _decimal(inputs, "max_temp_c")
    minimum = _decimal(inputs, "min_temp_c")
    base = _decimal(inputs, "base_temp_c")
    if maximum < minimum:
        raise ValueError("max_temp_c must be greater than or equal to min_temp_c")
    lower_cap = _optional_decimal(inputs, "lower_cap_c")
    upper_cap = _optional_decimal(inputs, "upper_cap_c")
    if lower_cap is not None and upper_cap is not None and lower_cap > upper_cap:
        raise ValueError("lower_cap_c must be less than or equal to upper_cap_c")
    adjusted_max = _clamp(maximum, lower_cap, upper_cap)
    adjusted_min = _clamp(minimum, lower_cap, upper_cap)
    answer = max(Decimal("0"), (adjusted_max + adjusted_min) / Decimal("2") - base)
    assumptions = (
        "daily mean method",
        "temperatures were capped before averaging" if lower_cap is not None or upper_cap is not None else "no temperature caps",
    )
    return _result(
        CalculationOperation.DAILY_GDD,
        answer,
        "GDD",
        f"max(0, (({_format_decimal(adjusted_max)} + {_format_decimal(adjusted_min)}) ÷ 2) − {_format_decimal(base)}) = {_format_decimal(answer)} GDD",
        {
            "max_temp_c": maximum,
            "min_temp_c": minimum,
            "base_temp_c": base,
            "lower_cap_c": lower_cap,
            "upper_cap_c": upper_cap,
        },
        assumptions=assumptions,
    )


def _accumulated_gdd(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(inputs, required={"daily_gdd_values"})
    raw_values = inputs.get("daily_gdd_values")
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)) or not raw_values:
        raise ValueError("daily_gdd_values must be a non-empty array")
    values = [_decimal_value(value, f"daily_gdd_values[{index}]") for index, value in enumerate(raw_values)]
    if any(value < 0 for value in values):
        raise ValueError("daily_gdd_values cannot contain negative values")
    answer = sum(values, Decimal("0"))
    expression = " + ".join(_format_decimal(value) for value in values)
    return _result(
        CalculationOperation.ACCUMULATED_GDD,
        answer,
        "GDD",
        f"{expression} = {_format_decimal(answer)} GDD",
        {"daily_gdd_values": values},
    )


def _row_population(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(inputs, required={"plants_per_row_m", "row_spacing_m"})
    plants = _nonnegative(inputs, "plants_per_row_m")
    spacing = _positive(inputs, "row_spacing_m")
    answer = plants / spacing
    return _result(
        CalculationOperation.ROW_POPULATION,
        answer,
        "plants/m²",
        f"{_format_decimal(plants)} plants/m ÷ {_format_decimal(spacing)} m = {_format_decimal(answer)} plants/m²",
        {"plants_per_row_m": plants, "row_spacing_m": spacing},
    )


def _field_product_total(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(inputs, required={"area_ha", "product_rate_kg_per_ha"})
    area = _positive(inputs, "area_ha")
    rate = _nonnegative(inputs, "product_rate_kg_per_ha")
    answer = area * rate
    return _result(
        CalculationOperation.FIELD_PRODUCT_TOTAL,
        answer,
        "kg",
        f"{_format_decimal(area)} ha × {_format_decimal(rate)} kg/ha = {_format_decimal(answer)} kg",
        {"area_ha": area, "product_rate_kg_per_ha": rate},
    )


def _area_weighted_average(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(inputs, required={"total_area_ha", "zones", "value_unit"}, optional={"area_tolerance_ha"})
    total_area = _positive(inputs, "total_area_ha")
    value_unit = str(inputs.get("value_unit") or "").strip()
    if not value_unit:
        raise ValueError("value_unit is required")
    raw_zones = inputs.get("zones")
    if not isinstance(raw_zones, Sequence) or isinstance(raw_zones, (str, bytes)) or len(raw_zones) < 2:
        raise ValueError("zones must contain at least two area/value objects")
    zones: list[dict[str, Decimal]] = []
    for index, raw_zone in enumerate(raw_zones):
        if not isinstance(raw_zone, Mapping):
            raise ValueError(f"zones[{index}] must be an object")
        _require_only(raw_zone, required={"area_ha", "value"}, label=f"zones[{index}]")
        zones.append(
            {
                "area_ha": _positive(raw_zone, "area_ha", label=f"zones[{index}].area_ha"),
                "value": _decimal(raw_zone, "value", label=f"zones[{index}].value"),
            }
        )
    described_area = sum((zone["area_ha"] for zone in zones), Decimal("0"))
    tolerance = _nonnegative(inputs, "area_tolerance_ha", default=max(Decimal("0.01"), total_area * Decimal("0.001")))
    if abs(described_area - total_area) > tolerance:
        raise ValueError(
            f"zone areas total {_format_decimal(described_area)} ha but total_area_ha is "
            f"{_format_decimal(total_area)} ha; supply the missing/extra area or increase an explicit tolerance"
        )
    answer = sum((zone["area_ha"] * zone["value"] for zone in zones), Decimal("0")) / described_area
    expression = " + ".join(
        f"{_format_decimal(zone['area_ha'])}×{_format_decimal(zone['value'])}" for zone in zones
    )
    return _result(
        CalculationOperation.AREA_WEIGHTED_AVERAGE,
        answer,
        value_unit,
        f"({expression}) ÷ {_format_decimal(described_area)} = {_format_decimal(answer)} {value_unit}",
        {
            "total_area_ha": total_area,
            "described_area_ha": described_area,
            "area_tolerance_ha": tolerance,
            "zones": zones,
            "value_unit": value_unit,
        },
    )


def _partial_budget(inputs: Mapping[str, Any]) -> AgronomicCalculation:
    _require_only(
        inputs,
        required={"added_returns", "reduced_costs", "added_costs", "reduced_returns"},
        optional={"currency"},
    )
    added_returns = _decimal(inputs, "added_returns")
    reduced_costs = _decimal(inputs, "reduced_costs")
    added_costs = _decimal(inputs, "added_costs")
    reduced_returns = _decimal(inputs, "reduced_returns")
    currency = str(inputs.get("currency") or "CAD").strip().upper() or "CAD"
    answer = added_returns + reduced_costs - added_costs - reduced_returns
    return _result(
        CalculationOperation.PARTIAL_BUDGET,
        answer,
        currency,
        (
            f"{_format_decimal(added_returns)} + {_format_decimal(reduced_costs)} − "
            f"{_format_decimal(added_costs)} − {_format_decimal(reduced_returns)} = {_format_decimal(answer)} {currency}"
        ),
        {
            "added_returns": added_returns,
            "reduced_costs": reduced_costs,
            "added_costs": added_costs,
            "reduced_returns": reduced_returns,
            "currency": currency,
        },
        assumptions=("all monetary inputs use the same time and area basis",),
    )


def _result(
    operation: CalculationOperation,
    value: Decimal,
    unit: str,
    formula: str,
    inputs: dict[str, Any],
    *,
    assumptions: tuple[str, ...] = (),
) -> AgronomicCalculation:
    if not value.is_finite():
        raise ValueError("calculation produced a non-finite result")
    return AgronomicCalculation(
        operation=operation,
        value=value.normalize(),
        unit=unit,
        formula=formula,
        inputs=inputs,
        assumptions=assumptions,
    )


def _require_only(
    inputs: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str = "inputs",
) -> None:
    optional = optional or set()
    present = set(inputs)
    missing = sorted(required - present)
    unknown = sorted(present - required - optional)
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _decimal(inputs: Mapping[str, Any], key: str, *, label: str | None = None) -> Decimal:
    if key not in inputs:
        raise ValueError(f"{label or key} is required")
    return _decimal_value(inputs[key], label or key)


def _optional_decimal(inputs: Mapping[str, Any], key: str) -> Decimal | None:
    value = inputs.get(key)
    return None if value is None else _decimal_value(value, key)


def _decimal_value(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        with localcontext() as context:
            context.prec = 28
            numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not numeric.is_finite():
        raise ValueError(f"{label} must be finite")
    return numeric


def _positive(inputs: Mapping[str, Any], key: str, *, label: str | None = None) -> Decimal:
    value = _decimal(inputs, key, label=label)
    if value <= 0:
        raise ValueError(f"{label or key} must be greater than zero")
    return value


def _nonnegative(
    inputs: Mapping[str, Any],
    key: str,
    *,
    default: Decimal | None = None,
    label: str | None = None,
) -> Decimal:
    if key not in inputs and default is not None:
        return default
    value = _decimal(inputs, key, label=label)
    if value < 0:
        raise ValueError(f"{label or key} cannot be negative")
    return value


def _percent(inputs: Mapping[str, Any], key: str) -> Decimal:
    value = _decimal(inputs, key)
    if not Decimal("0") < value <= Decimal("100"):
        raise ValueError(f"{key} must be greater than 0 and no more than 100")
    return value


def _unit(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    unit = _UNIT_ALIASES.get(normalized)
    if unit is None:
        raise ValueError(f"unsupported unit {value!r}")
    return unit


def _clamp(value: Decimal, lower: Decimal | None, upper: Decimal | None) -> Decimal:
    if lower is not None:
        value = max(value, lower)
    if upper is not None:
        value = min(value, upper)
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _format_decimal(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"))
    if rounded == rounded.to_integral_value():
        return f"{int(rounded):,}"
    return f"{rounded:,.3f}".rstrip("0").rstrip(".")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_ready(item) for item in value]
    return value
