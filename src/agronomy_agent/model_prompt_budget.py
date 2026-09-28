"""Model-independent prompt accounting for generation boundaries."""

from __future__ import annotations

import math
from typing import Any


def positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def count_prompt_tokens(
    messages: list[dict[str, str]], generator: Any
) -> tuple[int, str]:
    method = getattr(generator, "count_prompt_tokens", None)
    if callable(method):
        try:
            exact = method(messages)
        except (RuntimeError, ValueError, TypeError):
            exact = None
        if type(exact) is int and exact >= 0:
            return exact, "tokenizer"
    # A UTF-8-aware heuristic with message framing. It is not an exact token
    # count or guarantee of native fit; callers must retain its basis label.
    estimate = sum(
        math.ceil(
            max(len(item["content"]), len(item["content"].encode("utf-8"))) / 3
        ) + 12
        for item in messages
    )
    return estimate, "estimated_characters"


def prompt_budget_receipt(
    messages: list[dict[str, str]],
    generator: Any,
    *,
    config: dict[str, Any] | None,
    reserved_output_tokens: int,
) -> dict[str, Any]:
    """Account for the exact messages about to generate, including output reserve."""

    policy = config if isinstance(config, dict) else {}
    configured_limit = positive_int(policy.get("context_limit_tokens"), 8192)
    reserve = max(
        0,
        int(reserved_output_tokens),
        positive_int(policy.get("reserved_output_tokens"), 0),
    )
    count, basis = count_prompt_tokens(messages, generator)
    # Local tokenizer loading can expose a previously unknown native limit.
    native_limit = getattr(generator, "context_window_tokens", None)
    if type(native_limit) is not int or native_limit <= 0:
        native_limit = None
    limit = min(configured_limit, native_limit) if native_limit else configured_limit
    remaining = limit - reserve - count
    return {
        "schema_version": "open_agronomy_agent.context_budget.v1",
        "status": (
            "over_limit"
            if remaining < 0
            else "within_budget"
            if basis == "tokenizer"
            else "estimated_within_budget"
        ),
        "input_tokens": count,
        "token_count_basis": basis,
        "context_limit_tokens": limit,
        "limit_basis": "model" if native_limit and native_limit < configured_limit else "configured",
        "reserved_output_tokens": reserve,
        "remaining_tokens": remaining,
    }
