from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_router_does_not_own_capability_selection_mutations() -> None:
    path = ROOT / "src/agronomy_agent/router.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if (
            isinstance(target, ast.Name)
            and target.id in {"tools", "required_tools"}
            and node.func.attr in {"add", "update", "discard", "clear"}
        ):
            offenders.append(node.lineno)
    assert offenders == []
