from __future__ import annotations

from typing import Any

from agronomy_agent.router import QueryRoute


def knowledge_filter_cache_key(filters: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Return a hashable cache key for Agno Knowledge filters."""

    return tuple(
        (str(key), _freeze_filter_value(value))
        for key, value in sorted(filters.items(), key=lambda item: str(item[0]))
    )


def route_to_knowledge_filters(
    route: QueryRoute,
    *,
    workspace_id: str | None = None,
    allow_private_workspace_sources: bool = False,
    region: str | None = None,
    crop: str | None = None,
) -> dict[str, Any]:
    visibility = "private" if allow_private_workspace_sources else "public"
    filters: dict[str, Any] = {
        "workspace_id": workspace_id,
        "access_level": visibility,
        "source_visibility": visibility,
        "license_status": "approved",
        "namespaces": list(route.namespaces),
        "knowledge_domains": list(route.knowledge_domains),
        "knowledge_bucket": route.knowledge_bucket,
        "source_type": [],
        "audience": [route.audience],
        "region": region or "",
        "crop": crop or "",
        "risk_level": route.risk_level,
        "retrieval_policy": ["standard", "context_only"],
    }
    if route.risk_level == "regulated" or {"product_stewardship", "label_boundary"} & set(route.namespaces):
        filters["source_type"] = ["boundary", "applied_guidance"]
        filters["license_status"] = "approved"
    elif "field_data_boundary" in route.namespaces and allow_private_workspace_sources:
        filters["source_visibility"] = "private"
        filters["access_level"] = "private"
    elif "regional_environment" in route.namespaces:
        filters["source_type"] = ["regional_environment_profile", "applied_guidance", "ontology", "boundary"]
    else:
        filters["source_type"] = ["applied_guidance", "exam", "ontology", "boundary"]
    return filters


def _freeze_filter_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(
            (str(key), _freeze_filter_value(nested_value))
            for key, nested_value in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, list):
        if not any(isinstance(item, (dict, list, tuple, set)) for item in value):
            return tuple(value)
        return tuple(_freeze_filter_value(item) for item in value)
    if isinstance(value, tuple):
        if not any(isinstance(item, (dict, list, tuple, set)) for item in value):
            return value
        return tuple(_freeze_filter_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze_filter_value(item) for item in value), key=repr))
    return value
