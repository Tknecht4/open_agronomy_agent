from __future__ import annotations

import os
from typing import Literal


AgentRuntimeMode = Literal["agno"]
VALID_AGENT_RUNTIME_MODES: tuple[AgentRuntimeMode, ...] = ("agno",)


def resolve_agent_runtime(config: dict | None = None, explicit: str | None = None) -> AgentRuntimeMode:
    """Resolve the serving runtime after the Agno cutover."""

    runtime_cfg = (config or {}).get("agent_runtime") if isinstance(config, dict) else {}
    configured = explicit or os.getenv("AGRONOMY_AGENT_AGENT_RUNTIME") or (runtime_cfg or {}).get("mode") or "agno"
    mode = str(configured).strip().lower()
    if mode not in VALID_AGENT_RUNTIME_MODES:
        raise ValueError("AGRONOMY_AGENT_AGENT_RUNTIME must be 'agno'; legacy runtime was removed after Agno promotion")
    return mode  # type: ignore[return-value]
