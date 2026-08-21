#!/usr/bin/env python3
"""Execute deterministic public capability fixtures through the canonical registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.agronomic_calculations import CalculationOperation  # noqa: E402
from agronomy_agent.capability_registry import (  # noqa: E402
    capability_catalog,
    capability_registry,
    execute_registered_capability,
)


DEFAULT_CONTRACT = ROOT / "configs/benchmark_capability_conformance_v1.json"


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_conformance(contract_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema_version") != "open_agronomy_agent.benchmark_capability_conformance.v1":
        raise ValueError("unsupported capability conformance schema")
    if contract.get("claim_eligible") is not False:
        raise ValueError("capability conformance must remain non-claim")

    registry = capability_registry()
    registry_catalog = capability_catalog()
    capability_reports: list[dict[str, Any]] = []
    failures: list[str] = []
    for declaration in contract.get("capabilities") or []:
        if not isinstance(declaration, Mapping):
            failures.append("capability_declaration_not_object")
            continue
        capability_id = str(declaration.get("capability_id") or "")
        spec = registry.require(capability_id)
        if spec.version != declaration.get("capability_version"):
            failures.append(f"{capability_id}:version_mismatch")

        positive_reports: list[dict[str, Any]] = []
        declared_operations: set[str] = set()
        for fixture in declaration.get("fixtures") or []:
            fixture_id = str(fixture["fixture_id"])
            operation = str(fixture["operation"])
            declared_operations.add(operation)
            try:
                result = execute_registered_capability(
                    capability_id,
                    {"operation": operation, "inputs": dict(fixture["inputs"])},
                )
                value = float(result["value"])
                expected = float(fixture["expected_value"])
                tolerance = float(fixture["absolute_tolerance"])
                passed = (
                    math.isfinite(value)
                    and abs(value - expected) <= tolerance
                    and result.get("unit") == fixture.get("expected_unit")
                    and result.get("operation") == operation
                    and result.get("status") == "calculated"
                    and "does not choose an agronomic target" in str(result.get("boundary") or "")
                )
                detail = None
            except Exception as exc:  # noqa: BLE001 - conformance must retain typed failure text.
                result = {}
                passed = False
                detail = f"{type(exc).__name__}:{exc}"
            if not passed:
                failures.append(f"{capability_id}:{fixture_id}:positive_failed")
            positive_reports.append(
                {
                    "fixture_id": fixture_id,
                    "operation": operation,
                    "passed": passed,
                    "result_sha256": _canonical_sha256(result) if result else None,
                    "observed_value": result.get("value") if result else None,
                    "observed_unit": result.get("unit") if result else None,
                    "failure": detail,
                }
            )

        negative_reports: list[dict[str, Any]] = []
        for fixture in declaration.get("negative_fixtures") or []:
            fixture_id = str(fixture["fixture_id"])
            expected_text = str(fixture["expected_error_contains"])
            observed_error = ""
            try:
                execute_registered_capability(
                    capability_id,
                    {"operation": str(fixture["operation"]), "inputs": dict(fixture["inputs"])},
                )
            except Exception as exc:  # noqa: BLE001 - the failure is the expected observation.
                observed_error = f"{type(exc).__name__}:{exc}"
            passed = expected_text in observed_error
            if not passed:
                failures.append(f"{capability_id}:{fixture_id}:negative_failed")
            negative_reports.append(
                {
                    "fixture_id": fixture_id,
                    "passed": passed,
                    "expected_error_contains": expected_text,
                    "observed_error_sha256": _canonical_sha256(observed_error) if observed_error else None,
                }
            )

        if capability_id == "agronomic_calculator":
            implemented_operations = {operation.value for operation in CalculationOperation}
            if declared_operations != implemented_operations:
                failures.append(f"{capability_id}:operation_coverage_mismatch")
        else:
            implemented_operations = set()
        capability_reports.append(
            {
                "capability_id": capability_id,
                "capability_version": spec.version,
                "implemented": spec.implemented,
                "tested": spec.tested,
                "performance_benchmark_exercised": spec.benchmark_exercised,
                "conformance_exercised": all(row["passed"] for row in positive_reports + negative_reports),
                "declared_operation_count": len(declared_operations),
                "implemented_operation_count": len(implemented_operations),
                "positive_fixtures": positive_reports,
                "negative_fixtures": negative_reports,
            }
        )

    return {
        "schema_version": "open_agronomy_agent.benchmark_capability_conformance_receipt.v1",
        "suite_id": contract.get("suite_id"),
        "status": "pass" if not failures else "blocked",
        "claim_eligible": False,
        "claim_boundary": "deterministic capability and registry conformance only; not model or agronomic performance",
        "contract_path": str(contract_path.resolve()),
        "contract_sha256": _file_sha256(contract_path),
        "registry_schema_version": registry_catalog.get("schema_version"),
        "registry_catalog_sha256": _canonical_sha256(registry_catalog),
        "capabilities": capability_reports,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    contract_path = args.contract.resolve() if args.contract.is_absolute() else (ROOT / args.contract).resolve()
    report = run_conformance(contract_path)
    if args.output:
        output = args.output.resolve() if args.output.is_absolute() else (ROOT / args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
