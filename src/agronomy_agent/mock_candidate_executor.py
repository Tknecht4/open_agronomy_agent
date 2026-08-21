"""Deterministic executor fixtures for candidate-runner process tests."""

from __future__ import annotations

import time
from typing import Any, Mapping


def echo_observation(request: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(request), "status": "complete", "row_disposition": "accepted"}


def stalled_observation(request: Mapping[str, Any]) -> dict[str, Any]:
    time.sleep(60)
    return dict(request)
