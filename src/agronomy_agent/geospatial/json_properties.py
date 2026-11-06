"""Lossless, bounded JSON properties for uploaded vector features.

Source properties are context, not observations or instructions. Refuse values
that cannot be represented rather than replacing them with strings or silently
removing unknown (null) cells.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

MAX_PROPERTY_DEPTH = 8
MAX_PROPERTY_NODES = 4096
MAX_PROPERTY_STRING_BYTES = 16 * 1024
MAX_PROPERTY_BYTES = 64 * 1024


def bounded_json_value(
    value: Any,
    *,
    scalar_adapter: Callable[[Any], Any] | None = None,
) -> Any:
    """Copy JSON types exactly, with shared node, depth and byte limits.

The driver adapter may translate driver-specific scalar missing values to
null or native scalar/array types to JSON types. Plain GeoJSON never uses it.
Unsupported types, nonfinite JSON numbers and over-budget values fail closed.
"""
    nodes = 0

    def copy(item: Any, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_PROPERTY_NODES:
            raise ValueError(f"source properties exceed {MAX_PROPERTY_NODES} JSON values")
        if depth > MAX_PROPERTY_DEPTH:
            raise ValueError(f"source properties exceed nesting depth {MAX_PROPERTY_DEPTH}")
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, str):
            if len(item.encode("utf-8")) > MAX_PROPERTY_STRING_BYTES:
                raise ValueError(f"source property string exceeds {MAX_PROPERTY_STRING_BYTES} UTF-8 bytes")
            return item
        if isinstance(item, int):
            if item.bit_length() > MAX_PROPERTY_STRING_BYTES:
                raise ValueError("source property integer exceeds the representation budget")
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                if scalar_adapter is not None:
                    adapted = scalar_adapter(item)
                    if adapted is None:
                        return None
                raise ValueError("source properties require finite JSON numbers")
            return item
        if isinstance(item, list):
            return [copy(child, depth + 1) for child in item]
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("source property object keys must be strings")
                copy(key, depth + 1)
                result[key] = copy(child, depth + 1)
            return result
        if scalar_adapter is not None:
            adapted = scalar_adapter(item)
            if adapted is not item:
                return copy(adapted, depth)
        raise ValueError(f"source properties contain unsupported {type(item).__name__} values")

    result = copy(value, 0)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_PROPERTY_BYTES:
        raise ValueError(f"source properties exceed {MAX_PROPERTY_BYTES} encoded JSON bytes")
    return result


def bounded_json_properties(
    properties: dict[str, Any],
    *,
    scalar_adapter: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(properties, dict):
        raise ValueError("source properties must be an object")
    return bounded_json_value(properties, scalar_adapter=scalar_adapter)
