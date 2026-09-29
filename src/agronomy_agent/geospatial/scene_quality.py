"""Provider-neutral, receipt-only support policy for one frozen scene set.

This module does not interpret scene cloud percentage, index magnitude, source
identity, geometry, or cache identity. The caller must admit those separately.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


POLICY_VERSION = "scene_quality.v1"
RANKING = "valid_fraction_desc_acquired_desc_scene_id_asc"
_AREA_TOLERANCE = 1e-6  # Square metres; permits float64 reduction roundoff only.


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Admit an explicit, versioned support threshold and fixed ranking rule."""
    keys = {"version", "index", "support", "min_valid_fraction"}
    if not isinstance(policy, dict) or set(policy) not in (keys, keys | {"ranking"}):
        raise ValueError("invalid_scene_quality_policy")
    if "ranking" in policy and policy["ranking"] != RANKING:
        raise ValueError("invalid_scene_quality_ranking")
    if policy["version"] != POLICY_VERSION:
        raise ValueError("unsupported_scene_quality_policy_version")
    if policy["index"] not in ("NDVI", "NDMI") or not isinstance(policy["index"], str):
        raise ValueError("invalid_scene_quality_index")
    if policy["support"] not in ("field", "interior") or not isinstance(policy["support"], str):
        raise ValueError("invalid_scene_quality_support")
    threshold = _number(policy["min_valid_fraction"])
    if threshold is None or not 0 <= threshold <= 1:
        raise ValueError("invalid_scene_quality_threshold")
    return {"version": POLICY_VERSION, "index": policy["index"],
            "support": policy["support"], "min_valid_fraction": threshold,
            "ranking": RANKING}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason,
            "support_area_m2": None, "valid_area_m2": None,
            "valid_fraction": None}


def _area(mapping: Any, key: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    value = _number(mapping.get(key))
    return value if value is not None and value >= 0 else None


def _within(part: float, whole: float) -> bool:
    if whole == 0:
        return part == 0
    return part <= whole + max(_AREA_TOLERANCE, whole * 1e-9)


def _fraction(part: float, whole: float) -> float:
    """Normalize only an already checked, tolerance-sized area overrun."""
    return min(1.0, part / whole)


def _stat_area(stats: Any, index: str) -> float | None:
    if not isinstance(stats, dict) or not isinstance(stats.get(index), dict):
        return None
    stat = stats[index]
    area = _area(stat, "area_m2")
    if area is None:
        return None
    summary = [stat.get(key) for key in ("mean", "min", "max")]
    if area == 0:
        return area if all(value is None for value in summary) else None
    values = [_number(value) for value in summary]
    if any(value is None for value in values):
        return None
    mean, minimum, maximum = values
    if not (minimum - 1e-9 <= mean <= maximum + 1e-9 and
            -1 - 1e-6 <= minimum <= maximum <= 1 + 1e-6):
        return None
    return area


def assess_support(receipt: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Assess actual index support on field or interior, preserving unknowns."""
    chosen = validate_policy(policy)
    if not isinstance(receipt, dict) or receipt.get("status") not in (
        "available", "empty_valid_area"
    ):
        return _unavailable("processing_unavailable")
    qa = receipt.get("qa")
    field = _area(qa, "field_area_m2")
    clear = _area(qa, "valid_area_m2")
    field_index = _stat_area(receipt.get("zonal_stats"), chosen["index"])
    if (field is None or clear is None or field_index is None or field <= 0 or
            not _within(clear, field) or not _within(field_index, clear)):
        return _unavailable("invalid_support_metadata")
    if (receipt["status"] == "empty_valid_area") != (clear == 0):
        return _unavailable("contradictory_processing_status")

    if chosen["support"] == "field":
        support_area, valid_area, qa_clear = field, field_index, clear
    else:
        support_area = _area(qa, "interior_field_area_m2")
        qa_clear = _area(qa, "interior_valid_area_m2")
        valid_area = _stat_area(receipt.get("interior_zonal_stats"), chosen["index"])
        if (support_area is None or qa_clear is None or valid_area is None or
                not _within(support_area, field) or not _within(qa_clear, support_area) or
                not _within(qa_clear, clear) or not _within(valid_area, qa_clear) or
                not _within(valid_area, field_index)):
            return _unavailable("invalid_interior_support_metadata")
        if support_area == 0:
            return {"status": "rejected", "reason": "empty_interior",
                    "support_area_m2": 0.0, "valid_area_m2": 0.0,
                    "valid_fraction": None}

    fraction = _fraction(valid_area, support_area)
    if valid_area == 0:
        status, reason = "rejected", "no_valid_index_support"
    elif fraction < chosen["min_valid_fraction"]:
        status, reason = "rejected", "below_min_valid_fraction"
    else:
        status, reason = "eligible", "meets_min_valid_fraction"
    return {"status": status, "reason": reason,
            "support_area_m2": support_area, "valid_area_m2": valid_area,
            "valid_fraction": fraction}


def _acquired(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_candidate_acquired_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_candidate_acquired_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_candidate_acquired_at")
    return parsed.astimezone(timezone.utc)


def rank_candidates(rows: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Rank complete observations; any unavailable attempt blocks selection."""
    chosen = validate_policy(policy)
    if not isinstance(rows, list):
        raise ValueError("invalid_candidate_rows")
    seen: set[str] = set()
    eligible: list[tuple[float, datetime, str]] = []
    rejected = unavailable = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"scene_id", "acquired_at", "assessment"}:
            raise ValueError("invalid_candidate_row")
        scene_id = row["scene_id"]
        if not isinstance(scene_id, str) or not scene_id or scene_id.strip() != scene_id or scene_id in seen:
            raise ValueError("invalid_candidate_scene_id")
        seen.add(scene_id)
        acquired = _acquired(row["acquired_at"])
        assessment = row["assessment"]
        if not isinstance(assessment, dict) or assessment.get("status") not in (
            "eligible", "rejected", "unavailable"
        ):
            raise ValueError("invalid_candidate_assessment")
        state = assessment["status"]
        fraction = assessment.get("valid_fraction")
        support_area = _area(assessment, "support_area_m2")
        valid_area = _area(assessment, "valid_area_m2")
        if state == "unavailable":
            if fraction is not None or assessment.get("support_area_m2") is not None or assessment.get("valid_area_m2") is not None:
                raise ValueError("invalid_candidate_assessment")
        elif support_area is None or valid_area is None or not _within(valid_area, support_area):
            raise ValueError("invalid_candidate_assessment")
        elif support_area == 0:
            if state != "rejected" or fraction is not None or valid_area != 0:
                raise ValueError("invalid_candidate_assessment")
        else:
            number = _number(fraction)
            if number is None or not 0 <= number <= 1 or not math.isclose(
                number, _fraction(valid_area, support_area), rel_tol=1e-9, abs_tol=1e-9
            ):
                raise ValueError("invalid_candidate_assessment")
        if state == "eligible":
            number = _number(fraction)
            if number is None or not 0 < number <= 1 or number < chosen["min_valid_fraction"]:
                raise ValueError("invalid_candidate_assessment")
            eligible.append((number, acquired, scene_id))
        elif state == "rejected":
            if support_area and valid_area and fraction >= chosen["min_valid_fraction"]:
                raise ValueError("invalid_candidate_assessment")
            rejected += 1
        else:
            unavailable += 1
    eligible.sort(key=lambda item: (-item[0], -item[1].timestamp(), item[2]))
    ranked = [item[2] for item in eligible]
    status = "incomplete" if unavailable else "selected" if ranked else "no_eligible_scene"
    return {"status": status, "selected_scene_id": ranked[0] if status == "selected" else None,
            "ranked_scene_ids": ranked, "evaluated_count": len(rows),
            "rejected_count": rejected, "unavailable_count": unavailable}
