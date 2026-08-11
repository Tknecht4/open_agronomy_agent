from __future__ import annotations

import pytest

from agronomy_agent.field_measurements import (
    MEASUREMENT_SCHEMA_VERSION,
    safe_soil_measurement,
    soil_measurement_comparison_blockers,
    soil_measurements_comparable,
    validate_field_event_payload,
    validate_soil_measurement,
)


def _measurement(**overrides):
    value = {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "kind": "soil_test",
        "sample_id": "NQ-2026-01",
        "metric": "soil_ph",
        "label": "Soil pH",
        "value": 6.4,
        "unit": "pH",
        "method": "1:1 water",
        "sample_depth": {"top": 0, "bottom": 15, "unit": "cm"},
        "spatial_scope": "composite",
        "source_quality": "lab_report",
        "lab_name": "Example Lab",
    }
    value.update(overrides)
    return value


def test_soil_measurement_contract_preserves_method_depth_units_and_quality() -> None:
    measurement = _measurement()

    validate_field_event_payload({"measurement": measurement})
    safe = safe_soil_measurement(measurement)

    assert safe == {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "kind": "soil_test",
        "sample_id": "NQ-2026-01",
        "metric": "soil_ph",
        "label": "Soil pH",
        "value": 6.4,
        "unit": "pH",
        "method": "1:1 water",
        "sample_depth": {"top": 0.0, "bottom": 15.0, "unit": "cm"},
        "spatial_scope": "composite",
        "source_quality": "lab_report",
        "lab_name": "Example Lab",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"metric": "Soil pH"}, "lowercase canonical identifier"),
        ({"value": float("nan")}, "finite number"),
        ({"unit": ""}, "missing required fields"),
        ({"method": ""}, "missing required fields"),
        ({"sample_depth": {"top": 15, "bottom": 0, "unit": "cm"}}, "0 <= top < bottom"),
        ({"sample_depth": {"top": 0, "bottom": 6, "unit": "feet"}}, "must be cm or in"),
        ({"source_quality": "trust_me"}, "source_quality must be"),
        ({"spatial_scope": "province"}, "spatial_scope must be"),
        ({"kind": "weather_sensor"}, "supports kind=soil_test only"),
    ],
)
def test_soil_measurement_contract_fails_closed_on_ambiguous_or_invalid_fields(
    overrides,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_soil_measurement(_measurement(**overrides))


def test_soil_measurements_compare_only_with_matching_units_method_depth_and_scope() -> None:
    first = safe_soil_measurement(_measurement())
    same = safe_soil_measurement(_measurement(value=6.8))
    different_unit = safe_soil_measurement(_measurement(unit="1"))
    different_method = safe_soil_measurement(_measurement(method="saturated paste"))
    different_depth = safe_soil_measurement(
        _measurement(sample_depth={"top": 0, "bottom": 6, "unit": "in"})
    )
    different_scope = safe_soil_measurement(_measurement(spatial_scope="zone"))

    assert all(item is not None for item in (first, same, different_unit, different_method, different_depth, different_scope))
    assert soil_measurements_comparable(first, same) is True
    assert soil_measurements_comparable(first, different_unit) is False
    assert soil_measurements_comparable(first, different_method) is False
    assert soil_measurements_comparable(first, different_depth) is False
    assert soil_measurements_comparable(first, different_scope) is False
    assert soil_measurement_comparison_blockers(first, different_unit) == ["unit"]
    assert soil_measurement_comparison_blockers(first, different_method) == ["method"]
    assert soil_measurement_comparison_blockers(first, different_depth) == ["sample_depth"]
    assert soil_measurement_comparison_blockers(first, different_scope) == ["spatial_scope"]
