from __future__ import annotations

from typing import Any

from agronomy_agent.local_tools import route_question


def route_query(message: str) -> dict[str, Any]:
    payload = route_question(message)
    return payload["route"]
