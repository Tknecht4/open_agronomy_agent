"""Supplied-input water accounting, not irrigation scheduling or calibration.

The standard-condition coefficient and uniform-profile relationships follow
FAO Irrigation and Drainage Paper 56, chapters 6 and 8. All field-specific
coefficients, water contents, depths and efficiencies must be supplied.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Mapping

WATER_INPUTS = {
    "water_storage_difference": {"upper_volumetric", "lower_volumetric", "root_depth_m", "interpretation"},
    "crop_evapotranspiration": {"crop_coefficient", "reference_et_mm_per_day"},
    "gross_irrigation_depth": {"net_depth_mm", "application_efficiency_pct"},
    "water_depth_volume": {"depth_mm", "area_ha"},
}


def validate_water_arithmetic_inputs(operation: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if operation not in WATER_INPUTS or not isinstance(inputs, Mapping) or set(inputs) != WATER_INPUTS[operation]:
        raise ValueError("supply exactly the named water-calculation inputs")
    values: dict[str, Any] = {}
    for key, value in inputs.items():
        if key == "interpretation":
            if value not in ("available_capacity", "refill_deficit"):
                raise ValueError("identify available capacity or refill deficit")
            values[key] = value
            continue
        if isinstance(value, bool):
            raise ValueError(f"{key} must be numeric")
        try:
            number = Decimal(str(value))
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"{key} must be numeric") from error
        if not number.is_finite() or number < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
        if len(number.as_tuple().digits) > 12 or number and not -12 <= number.adjusted() <= 10:
            raise ValueError(f"{key} exceeds supported precision")
        values[key] = number
    if operation == "water_storage_difference":
        if max(values["upper_volumetric"], values["lower_volumetric"]) > 1:
            raise ValueError("volumetric contents must be fractions from zero to one")
        if values["root_depth_m"] <= 0:
            raise ValueError("root_depth_m must be positive")
        if values["interpretation"] == "available_capacity" and values["upper_volumetric"] < values["lower_volumetric"]:
            raise ValueError("field capacity must not be below wilting point")
    if operation == "gross_irrigation_depth" and not 0 < values["application_efficiency_pct"] <= 100:
        raise ValueError("application_efficiency_pct must be above zero and at most 100")
    return values


def water_arithmetic(operation: str, inputs: Mapping[str, Any]) -> tuple[Decimal, str, str, dict[str, Any], tuple[str, ...], str]:
    values = validate_water_arithmetic_inputs(operation, inputs)
    with localcontext() as context:
        context.prec = 28
        if operation == "water_storage_difference":
            upper, lower, depth = (values[k] for k in ("upper_volumetric", "lower_volumetric", "root_depth_m"))
            difference = upper - lower
            if values["interpretation"] == "refill_deficit":
                difference = max(Decimal(0), difference)
                formula = f"max(0, {upper} − {lower}) × {depth} m × 1000 mm/m"
                limit = "This is a modeled refill deficit, ignoring losses; it does not establish when, whether or how much gross irrigation to apply."
            else:
                formula = f"({upper} − {lower}) × {depth} m × 1000 mm/m"
                limit = "Total available capacity is not current available water or readily available water before crop stress."
            return difference * depth * 1000, "mm", formula, values, ("uniform root-zone profile with supplied volumetric contents",), limit
        if operation == "crop_evapotranspiration":
            coefficient, reference = values["crop_coefficient"], values["reference_et_mm_per_day"]
            return coefficient * reference, "mm/day", f"Kc × ETo = {coefficient} × {reference} mm/day", values, (
                "single crop coefficient under standard, unstressed conditions; supplied Kc and ETo are not independently calibrated",), "Modeled ETc is not a field moisture measurement, irrigation requirement or soil-water-stress adjustment."
        if operation == "gross_irrigation_depth":
            net, efficiency = values["net_depth_mm"], values["application_efficiency_pct"]
            return net / (efficiency / 100), "mm", f"{net} mm net ÷ ({efficiency}/100)", values, (
                "the supplied application efficiency represents the fraction of gross application stored as net water",), "This converts the supplied net depth only; it does not select an irrigation target, timing or acceptable runoff and drainage losses."
        depth, area = values["depth_mm"], values["area_ha"]
        return depth * area * 10, "m³", f"{depth} mm × {area} ha × 10 m³/(mm ha)", values, (
            "uniform depth over the supplied area; losses excluded",), "This is volume corresponding to a supplied depth and area, not a field irrigation prescription."
