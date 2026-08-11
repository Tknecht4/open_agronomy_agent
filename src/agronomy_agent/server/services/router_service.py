from __future__ import annotations

from typing import Any

from agronomy_agent.lfm_prompt_router import (
    LfmPromptRouter,
    conservative_hybrid_route,
)
from agronomy_agent.local_tools import route_question
from agronomy_agent.route_decision_v2 import factorized_route_decision


def route_query(message: str) -> dict[str, Any]:
    payload = route_question(message)
    return payload["route"]


def route_query_with_lfm_shadow(
    message: str, prompt_router: LfmPromptRouter
) -> dict[str, Any]:
    """Return opt-in comparison evidence without changing the live route.

    The caller must explicitly construct and inject the optional model.  The
    authoritative route is always the existing deterministic result.
    """

    current = route_query(message)
    shadow = prompt_router.route(message)
    hybrid_route, hybrid_reason = conservative_hybrid_route(
        current["question_type"], shadow
    )
    factorized = factorized_route_decision(current, shadow)
    return {
        "authoritative_route": current,
        "lfm_shadow": shadow.to_dict(),
        "conservative_hybrid_candidate": {
            "question_type": hybrid_route,
            "reason": hybrid_reason,
            "applied_to_authoritative_route": False,
        },
        "factorized_route_candidate": factorized.to_dict(),
    }
