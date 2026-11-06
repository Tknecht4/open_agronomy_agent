"""Dependency-free descriptions of mapped support; scores are not probabilities."""
from __future__ import annotations

import math
from typing import Any


def validated_fraction(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1 and math.isfinite(value):
        return float(value)
    return None


def mapped_coverage_label(item: dict[str, Any]) -> str:
    """Describe explicit support without interpreting legacy fractions as area."""
    support = item.get("coverage_support_type")
    value = validated_fraction(item.get("coverage_estimate"))
    if support == "point_membership":
        if value in (0, 1):
            return "point is covered by mapped polygon" if value == 1 else "point is outside mapped polygon"
        return "point membership unknown"
    if support == "polygon_area":
        return f"{round(value * 100)}% polygon area overlap" if value is not None else "polygon area overlap unknown"
    return "spatial support unknown; no area coverage inferred"


def mapped_confidence_label(item: dict[str, Any]) -> str | None:
    """No score obtains calibrated probability authority from a label alone."""
    value = validated_fraction(item.get("confidence"))
    if value is None:
        return None
    if item.get("confidence_kind") == "heuristic_not_calibrated":
        return f"heuristic overlap score {value:g} (not a calibrated probability)"
    return f"source score {value:g} (calibration unknown)"
