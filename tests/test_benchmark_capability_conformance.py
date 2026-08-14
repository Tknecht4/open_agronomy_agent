from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_benchmark_capability_conformance.py"
CONTRACT = ROOT / "configs/benchmark_capability_conformance_v1.json"


def _module():
    spec = importlib.util.spec_from_file_location("run_benchmark_capability_conformance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_calculator_operations_execute_through_canonical_registry() -> None:
    report = _module().run_conformance(CONTRACT)

    assert report["status"] == "pass"
    assert report["claim_eligible"] is False
    assert report["failures"] == []
    calculator = report["capabilities"][0]
    assert calculator["capability_id"] == "agronomic_calculator"
    assert calculator["declared_operation_count"] == 12
    assert calculator["implemented_operation_count"] == 12
    assert calculator["conformance_exercised"] is True
    assert calculator["performance_benchmark_exercised"] is False
    assert all(row["passed"] for row in calculator["positive_fixtures"])
    assert all(row["passed"] for row in calculator["negative_fixtures"])
