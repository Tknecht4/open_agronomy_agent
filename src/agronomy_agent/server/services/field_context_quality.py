from __future__ import annotations

from typing import Any


CONCEPTUAL_FIELDS = ("crop_current", "region_text")
LOCATION_FIELDS = ("region_text", "country", "province_state", "county_rm")
DIAGNOSTIC_DETAIL_FIELDS = (
    "soil_series_or_texture",
    "drainage_class",
    "irrigation_status",
    "soil_test_summary",
    "crop_rotation_notes",
    "management_notes",
    "known_constraints",
)


def evaluate_field_context_quality(field_context: dict[str, Any]) -> dict[str, Any]:
    """Rate whether a field profile is enough for demo-safe answer modes."""

    available = _available_fields(field_context)
    crop_ready = "crop_current" in available
    location_ready = bool(set(LOCATION_FIELDS) & available)
    diagnostic_details = sorted(set(DIAGNOSTIC_DETAIL_FIELDS) & available)
    conceptual_ready = crop_ready or location_ready
    diagnostic_ready = crop_ready and location_ready and bool(diagnostic_details)

    checks = [
        {
            "id": "conceptual_answer",
            "label": "Enough for conceptual answer",
            "status": "ready" if conceptual_ready else "missing",
            "available_fields": sorted(available & set(CONCEPTUAL_FIELDS)),
            "missing_fields": [] if conceptual_ready else ["crop_current or region_text"],
        },
        {
            "id": "diagnostic_triage",
            "label": "Enough for diagnostic triage",
            "status": "ready" if diagnostic_ready else "missing",
            "available_fields": [
                field
                for field in ("crop_current", "region_text", *DIAGNOSTIC_DETAIL_FIELDS)
                if field in available
            ],
            "missing_fields": _diagnostic_missing(crop_ready, location_ready, diagnostic_details),
        },
        {
            "id": "product_rate_decision",
            "label": "Not enough for product/rate decision",
            "status": "blocked",
            "available_fields": sorted(available),
            "missing_fields": [
                "current product label",
                "local jurisdiction and recommendation authority",
                "field-specific calibrated rate method",
            ],
        },
    ]

    return {
        "schema_version": "phase6_field_context_quality_v1",
        "summary": _summary(conceptual_ready=conceptual_ready, diagnostic_ready=diagnostic_ready),
        "ready": {
            "conceptual_answer": conceptual_ready,
            "diagnostic_triage": diagnostic_ready,
            "product_rate_decision": False,
        },
        "checks": checks,
        "available_fields": sorted(available),
        "missing_minimum_next_prompts": _next_prompts(crop_ready, location_ready, diagnostic_details),
        "product_rate_boundary": "Field profiles do not authorize product, label, or rate decisions.",
    }


def _available_fields(field_context: dict[str, Any]) -> set[str]:
    available: set[str] = set()
    for key, value in field_context.items():
        if key in {"id", "organization_id", "workspace_id", "created_by_user_id", "metadata", "created_at", "updated_at", "deleted_at"}:
            continue
        if _has_value(value):
            available.add(key)
    return available


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _diagnostic_missing(crop_ready: bool, location_ready: bool, diagnostic_details: list[str]) -> list[str]:
    missing: list[str] = []
    if not crop_ready:
        missing.append("crop_current")
    if not location_ready:
        missing.append("region_text or jurisdiction")
    if not diagnostic_details:
        missing.append("soil, drainage, weather, history, or constraint notes")
    return missing


def _next_prompts(crop_ready: bool, location_ready: bool, diagnostic_details: list[str]) -> list[str]:
    prompts: list[str] = []
    if not crop_ready:
        prompts.append("What crop or crop stage should this answer assume?")
    if not location_ready:
        prompts.append("What region, state/province, county/RM, or generalized location should this use?")
    if crop_ready and location_ready and not diagnostic_details:
        prompts.append("Add one field note: soil texture, drainage, recent weather, soil test, rotation, or observed pressure.")
    if not prompts:
        prompts.append("For product or rate decisions, attach the current label and local recommendation basis.")
    return prompts


def _summary(*, conceptual_ready: bool, diagnostic_ready: bool) -> str:
    if diagnostic_ready:
        return "diagnostic_triage_ready"
    if conceptual_ready:
        return "conceptual_answer_ready"
    return "insufficient_context"
