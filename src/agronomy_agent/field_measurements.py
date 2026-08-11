from __future__ import annotations

import math
import re
from typing import Any


MEASUREMENT_SCHEMA_VERSION = "open_agronomy_agent.field_measurement.v1"
SOIL_MEASUREMENT_KIND = "soil_test"
SOIL_SOURCE_QUALITIES = {
    "lab_report",
    "imported_lab_report",
    "user_transcribed_lab_report",
    "field_kit",
}
SOIL_SPATIAL_SCOPES = {"point", "zone", "composite", "field"}
DEPTH_UNITS = {"cm", "in"}
METRIC_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def validate_field_event_payload(payload: Any) -> None:
    """Validate the optional typed measurement envelope without changing hashed input."""
    if not isinstance(payload, dict) or "measurement" not in payload:
        return
    validate_soil_measurement(payload["measurement"])


def validate_soil_measurement(measurement: Any) -> None:
    if not isinstance(measurement, dict):
        raise ValueError("measurement must be an object")
    required = {
        "schema_version",
        "kind",
        "sample_id",
        "metric",
        "value",
        "unit",
        "method",
        "sample_depth",
        "spatial_scope",
        "source_quality",
    }
    missing = sorted(key for key in required if measurement.get(key) in (None, ""))
    if missing:
        raise ValueError(f"measurement is missing required fields: {', '.join(missing)}")
    if measurement.get("schema_version") != MEASUREMENT_SCHEMA_VERSION:
        raise ValueError(f"measurement schema_version must be {MEASUREMENT_SCHEMA_VERSION}")
    if measurement.get("kind") != SOIL_MEASUREMENT_KIND:
        raise ValueError("field_measurement.v1 currently supports kind=soil_test only")

    _bounded_text(measurement.get("sample_id"), field="measurement.sample_id", max_length=128)
    metric = _bounded_text(measurement.get("metric"), field="measurement.metric", max_length=64)
    if not METRIC_PATTERN.fullmatch(metric):
        raise ValueError(
            "measurement.metric must be a lowercase canonical identifier using letters, numbers, dot, dash, or underscore"
        )
    value = measurement.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("measurement.value must be a finite number")
    _bounded_text(measurement.get("unit"), field="measurement.unit", max_length=48)
    _bounded_text(measurement.get("method"), field="measurement.method", max_length=160)

    depth = measurement.get("sample_depth")
    if not isinstance(depth, dict):
        raise ValueError("measurement.sample_depth must be an object")
    depth_unit = _bounded_text(
        depth.get("unit"),
        field="measurement.sample_depth.unit",
        max_length=8,
    ).lower()
    if depth_unit not in DEPTH_UNITS:
        raise ValueError("measurement.sample_depth.unit must be cm or in")
    top = _finite_number(depth.get("top"), field="measurement.sample_depth.top")
    bottom = _finite_number(depth.get("bottom"), field="measurement.sample_depth.bottom")
    if top < 0 or bottom <= top:
        raise ValueError("measurement.sample_depth requires 0 <= top < bottom")

    spatial_scope = _bounded_text(
        measurement.get("spatial_scope"),
        field="measurement.spatial_scope",
        max_length=24,
    )
    if spatial_scope not in SOIL_SPATIAL_SCOPES:
        raise ValueError(
            "measurement.spatial_scope must be point, zone, composite, or field"
        )
    source_quality = _bounded_text(
        measurement.get("source_quality"),
        field="measurement.source_quality",
        max_length=48,
    )
    if source_quality not in SOIL_SOURCE_QUALITIES:
        raise ValueError(
            "measurement.source_quality must be lab_report, imported_lab_report, "
            "user_transcribed_lab_report, or field_kit"
        )

    for key, max_length in (
        ("label", 160),
        ("lab_name", 160),
        ("zone_id", 128),
        ("qualifier", 32),
    ):
        if measurement.get(key) not in (None, ""):
            _bounded_text(
                measurement.get(key),
                field=f"measurement.{key}",
                max_length=max_length,
            )


def safe_soil_measurement(value: Any) -> dict[str, Any] | None:
    """Return a bounded typed measurement only after the full contract validates."""
    try:
        validate_soil_measurement(value)
    except ValueError:
        return None
    measurement = value
    depth = measurement["sample_depth"]
    safe = {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "kind": SOIL_MEASUREMENT_KIND,
        "sample_id": str(measurement["sample_id"]).strip(),
        "metric": str(measurement["metric"]).strip(),
        "value": float(measurement["value"]),
        "unit": str(measurement["unit"]).strip(),
        "method": str(measurement["method"]).strip(),
        "sample_depth": {
            "top": float(depth["top"]),
            "bottom": float(depth["bottom"]),
            "unit": str(depth["unit"]).strip().lower(),
        },
        "spatial_scope": str(measurement["spatial_scope"]).strip(),
        "source_quality": str(measurement["source_quality"]).strip(),
    }
    for key in ("label", "lab_name", "zone_id", "qualifier"):
        if measurement.get(key) not in (None, ""):
            safe[key] = str(measurement[key]).strip()
    return safe


def soil_measurements_comparable(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return all(
        _comparison_text(first.get(key)) == _comparison_text(second.get(key))
        for key in (
            "sample_id",
            "metric",
            "unit",
            "method",
            "spatial_scope",
            "zone_id",
            "qualifier",
        )
    ) and _depth_signature(first.get("sample_depth")) == _depth_signature(
        second.get("sample_depth")
    )


def soil_measurement_comparison_blockers(
    first: dict[str, Any],
    second: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for key in ("unit", "method", "spatial_scope", "zone_id", "qualifier"):
        if _comparison_text(first.get(key)) != _comparison_text(second.get(key)):
            blockers.append(key)
    if _depth_signature(first.get("sample_depth")) != _depth_signature(
        second.get("sample_depth")
    ):
        blockers.append("sample_depth")
    return blockers


def soil_measurement_display(measurement: dict[str, Any]) -> str:
    label = str(measurement.get("label") or measurement.get("metric") or "soil measurement")
    value = measurement.get("value")
    value_text = f"{float(value):g}" if isinstance(value, (int, float)) else str(value)
    depth = measurement.get("sample_depth") if isinstance(measurement.get("sample_depth"), dict) else {}
    depth_text = (
        f"{float(depth.get('top')):g}-{float(depth.get('bottom')):g} {depth.get('unit')}"
        if isinstance(depth.get("top"), (int, float))
        and isinstance(depth.get("bottom"), (int, float))
        else "depth unknown"
    )
    return (
        f"{label}={value_text} {measurement.get('unit')} "
        f"(sample {measurement.get('sample_id')}; {measurement.get('method')}; {depth_text})"
    )


def _bounded_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(character in text for character in "\r\n\x00"):
        raise ValueError(f"{field} must be single-line text")
    return text


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _comparison_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _depth_signature(value: Any) -> tuple[float | None, float | None, str]:
    if not isinstance(value, dict):
        return None, None, ""
    top = float(value["top"]) if isinstance(value.get("top"), (int, float)) else None
    bottom = float(value["bottom"]) if isinstance(value.get("bottom"), (int, float)) else None
    unit = _comparison_text(value.get("unit"))
    return top, bottom, unit
