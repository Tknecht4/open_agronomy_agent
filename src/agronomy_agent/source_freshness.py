from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


FRESHNESS_SCHEMA = "open_agronomy_agent.source_freshness.v1"

# These are operational review intervals, not claims about scientific validity.
# High-consequence sources fail closed when their date cannot be established.
FRESHNESS_POLICIES: tuple[tuple[tuple[str, ...], str, int | None, bool], ...] = (
    (("epa_ppls", "health_canada_pmra", "label"), "legal_label", 7, True),
    (("forecast",), "weather_forecast", 1, True),
    (("nasa_power", "daymet", "nasdi", "weather", "climate"), "weather_observation", 7, True),
    (("disease", "alert"), "disease_alert", 7, True),
    (("price", "market"), "market_price", 1, True),
    (("statcan", "quickstats", "crop_statistics"), "official_statistics", 400, False),
    (("variety", "trial"), "variety_trial", 730, False),
    (
        ("soil_survey", "cansis", "soil_landscape", "map", "erosion", "crop_inventory", "cropland"),
        "static_reference",
        None,
        False,
    ),
)


def _policy(tool_name: str) -> tuple[str, int | None, bool]:
    normalized = tool_name.lower()
    for needles, source_class, max_age_days, high_consequence in FRESHNESS_POLICIES:
        if any(needle in normalized for needle in needles):
            return source_class, max_age_days, high_consequence
    return "general_public_source", 365, False


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        if len(text) == 4 and text.isdigit():
            parsed = datetime(int(text), 12, 31, tzinfo=timezone.utc)
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_datetime(payload: dict[str, Any]) -> tuple[str | None, datetime | None]:
    for key in (
        "observation_end",
        "valid_at",
        "effective_date",
        "retrieved_at",
        "checked_at",
        "updated_at",
        "end",
        "reference_period",
        "year",
    ):
        parsed = _parse_date(payload.get(key))
        if parsed is not None:
            return key, parsed
    return None, None


def assess_source_freshness(
    tool_name: str,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    source_class, max_age_days, high_consequence = _policy(tool_name)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    date_field, source_at = _source_datetime(payload)

    if source_class == "static_reference":
        status = "static_reference"
        age_days = (now - source_at).days if source_at else None
        safe = True
        declaration = "Static reference: review source edition and field applicability; real-time freshness is not implied."
    elif source_at is None:
        status = "unknown"
        age_days = None
        safe = not high_consequence
        declaration = (
            f"{source_class.replace('_', ' ').title()} date is unknown; "
            + ("do not use it for a high-consequence decision." if high_consequence else "verify its date before relying on it.")
        )
    else:
        age_days = (now.date() - source_at.date()).days
        if age_days < -1:
            status = "future_invalid"
            safe = False
        elif max_age_days is not None and age_days > max_age_days:
            status = "stale"
            safe = False if high_consequence else True
        else:
            status = "current"
            safe = True
        declaration = (
            f"{source_class.replace('_', ' ').title()} dated {source_at.date().isoformat()} "
            f"({age_days} day{'s' if age_days != 1 else ''} old; review interval {max_age_days} days)."
        )

    return {
        "schema_version": FRESHNESS_SCHEMA,
        "source_class": source_class,
        "status": status,
        "date_field": date_field,
        "source_at": source_at.isoformat() if source_at else None,
        "age_days": age_days,
        "max_age_days": max_age_days,
        "high_consequence": high_consequence,
        "safe_for_high_consequence": safe,
        "declaration": declaration,
    }
