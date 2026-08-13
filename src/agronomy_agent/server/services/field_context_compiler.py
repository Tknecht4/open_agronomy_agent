"""Build a compact, attributable field-context receipt for an answer turn.

The compiler deliberately projects only bounded values already accepted by the
server or returned by a public adapter.  It keeps local map intersections and
live/public observations separate, and it records their limitations alongside
the facts supplied to the model.
"""

from __future__ import annotations

from typing import Any, Callable


SCHEMA_VERSION = "open_agronomy_agent.field_context_compiler.v1"
AVAILABLE_STATUSES = {"available", "partial_available", "available_offline_snapshot"}


def compile_field_context(
    field_context: dict[str, Any] | None,
    public_adapter_records: list[dict[str, Any]],
    *,
    safe_field_summary: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """Return a bounded receipt and prompt block from source-bound context.

    ``safe_field_summary`` is injected from the chat service to make the
    browser-input allowlist authoritative and avoid a dependency cycle.
    """

    safe_field = safe_field_summary(field_context)
    map_context = _map_context(safe_field.get("regional_intersections"))
    live_context = _live_context(public_adapter_records)
    status = "available" if map_context or live_context else "limited"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "field": {
            key: safe_field[key]
            for key in ("crop", "region", "jurisdiction", "concern", "geometry_summary")
            if safe_field.get(key) not in (None, "")
        },
        "map_context": map_context,
        "live_context": live_context,
        "boundary": (
            "Compiled context is source-bound decision support. Historical map polygons and gridded or point "
            "public data are priors, not field truth, a soil test, a field sensor, or management-rate authority."
        ),
    }
    return {"receipt": receipt, "prompt": render_field_context_prompt(receipt)}


def render_field_context_prompt(receipt: dict[str, Any]) -> str:
    """Render the same bounded receipt for the model, without hidden values."""

    lines = ["Compiled field context (source-bound):"]
    field = receipt.get("field") if isinstance(receipt.get("field"), dict) else {}
    if field:
        bits = [f"{label}: {field[key]}" for key, label in (("crop", "Crop"), ("region", "Region"), ("jurisdiction", "Jurisdiction"), ("concern", "Concern"), ("geometry_summary", "Geometry")) if field.get(key)]
        if bits:
            lines.append(f"- Field: {'; '.join(bits)}")
    for item in receipt.get("map_context") or []:
        label = item.get("label") or item.get("layer_id") or "Mapped context"
        facts = [item.get("map_unit"), item.get("soil_summary"), item.get("coverage")]
        components = item.get("dominant_components") or []
        component_text = "; ".join(_component_label(component) for component in components if _component_label(component))
        if component_text:
            facts.append(f"components: {component_text}")
        lines.append(f"- Mapped prior — {label}: {'; '.join(str(value) for value in facts if value)}")
    for item in receipt.get("live_context") or []:
        label = item.get("label") or item.get("adapter") or "Public source"
        facts = item.get("facts") or []
        lines.append(f"- Public check — {label}: {'; '.join(str(value) for value in facts if value)}")
    lines.append(f"- Boundary: {receipt['boundary']}")
    lines.append("- Preserve source identity and uncertainty. Do not turn these priors into a field measurement or a prescription.")
    return "\n".join(lines)


def _map_context(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compiled: list[dict[str, Any]] = []
    for item in value[:4]:
        if not isinstance(item, dict):
            continue
        record = {
            "layer_id": _text(item.get("layer_id")),
            "label": _text(item.get("system")) or _text(item.get("name")),
            "map_unit": _text(item.get("map_unit")) or _text(item.get("code")),
            "soil_summary": _text(item.get("soil_summary")),
            "coverage": _coverage_label(item),
            "source_scale": _text(item.get("source_scale")) or _text(item.get("source_scale_range")),
            "dominant_components": [_component(component) for component in (item.get("dominant_components") or [])[:3] if isinstance(component, dict)],
            "boundary": _text(item.get("boundary")),
        }
        record = {key: value for key, value in record.items() if value not in (None, "", [])}
        if record:
            compiled.append(record)
    return compiled


def _live_context(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compiled: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = _text(record.get("name"))
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        status = _text(payload.get("status")) or "unknown"
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        facts = _adapter_facts(name, summary)
        if status not in AVAILABLE_STATUSES or not facts:
            continue
        compiled.append(
            {
                "adapter": name,
                "label": _adapter_label(name),
                "status": status,
                "transport": _text(payload.get("transport")),
                "facts": facts[:5],
                "source": _text(payload.get("source")),
                "boundary": _text(payload.get("boundary")),
            }
        )
    return compiled[:5]


def _adapter_facts(name: str, summary: dict[str, Any]) -> list[str]:
    if name == "cansis_soil_landscapes_canada":
        landscapes = summary.get("landscapes") if isinstance(summary.get("landscapes"), list) else []
        facts: list[str] = []
        for landscape in landscapes[:2]:
            if not isinstance(landscape, dict):
                continue
            values = [
                _text(landscape.get("slc_id")),
                _text(landscape.get("soil_order")),
                _text(landscape.get("soil_great_group")),
                _text(landscape.get("drainage_code")),
            ]
            labels = ["SLC", "soil order", "great group", "drainage code"]
            facts.append(
                ", ".join(f"{label} {value}" for label, value in zip(labels, values) if value)
            )
        return [fact for fact in facts if fact]
    if name == "nasa_power_daily":
        parameters = summary.get("parameter_summary") if isinstance(summary.get("parameter_summary"), dict) else {}
        facts = []
        for key, label, statistic, units in (
            ("PRECTOTCORR", "recent precipitation", "sum", "mm"),
            ("T2M", "mean temperature", "mean", "°C"),
            ("WS2M", "mean wind", "mean", "m/s"),
        ):
            value = parameters.get(key) if isinstance(parameters.get(key), dict) else {}
            number = value.get(statistic)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                facts.append(f"{label} {round(float(number), 2):g} {units}")
        return facts
    return []


def _component(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in ("soil_name", "proportion_percent", "drainage_class", "soil_order_code", "great_group_code", "predominant_slope_percent")
        if value.get(key) not in (None, "")
    }


def _component_label(component: Any) -> str:
    if not isinstance(component, dict):
        return ""
    name = _text(component.get("soil_name")) or "unnamed component"
    details = []
    if component.get("proportion_percent") is not None:
        details.append(f"{component['proportion_percent']}%")
    if _text(component.get("drainage_class")):
        details.append(_text(component.get("drainage_class")) or "")
    if _text(component.get("soil_order_code")):
        details.append(f"order {_text(component.get('soil_order_code'))}")
    return f"{name} ({', '.join(details)})" if details else name


def _coverage_label(item: dict[str, Any]) -> str | None:
    value = item.get("coverage_estimate")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 1:
        return f"{round(float(value) * 100)}% field coverage estimate"
    return None


def _adapter_label(name: str) -> str:
    return {
        "cansis_soil_landscapes_canada": "CanSIS Soil Landscapes of Canada",
        "nasa_power_daily": "NASA POWER daily weather",
    }.get(name, name.replace("_", " "))


def _text(value: Any) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text[:240] if text else None
