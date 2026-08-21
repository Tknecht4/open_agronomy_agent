#!/usr/bin/env python3
"""Run the complete Benchmark v2 matrix through an explicit executor.

Only the deterministic contract-QA executor is checked in today. It performs
no model inference, retrieval, external calls, or judging and its output is
always claim-ineligible. A production executor must implement every declared
component flag and emit the same structured observation contract before it can
be added; the legacy four-arm runner is deliberately not used as a substitute.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agronomy_agent.benchmark_v2_runner import (  # noqa: E402
    DeterministicContractExecutor,
    ModelIdentity,
    file_sha256,
    run_benchmark_v2,
    write_run_bundle,
)
from agronomy_agent.benchmark_harness_compatibility import (  # noqa: E402
    REQUIRED_ARTIFACT_RECEIPTS,
)
from scripts.audit_open_agronomy_benchmark_v2 import audit_benchmark_v2  # noqa: E402


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(value)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=ROOT / "configs/open_agronomy_benchmark_v2.json")
    parser.add_argument(
        "--executor",
        choices=["deterministic-contract-qa"],
        default="deterministic-contract-qa",
        help="No model inference. Produces synthetic harness-QA observations only.",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--claim-eligible", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.claim_eligible:
        raise ValueError("Benchmark v2 refuses claim-eligible output")
    contract_path = args.contract.resolve()
    contract = _read_json(contract_path)
    if contract.get("claim_eligible") is not False:
        raise ValueError("Benchmark v2 contract must remain claim_eligible=false")
    suite_path = ROOT / str(contract["suite_path"])
    manifest_path = ROOT / str(contract["manifest_path"])
    interface_path = ROOT / str(contract["system_interface_contract"])
    preregistration_path = ROOT / str(contract["preregistration_path"])
    exposure_amendment_path = ROOT / str(contract["exposure_amendment_path"])
    harness_contract_path = ROOT / str(contract["harness_contract_path"])
    harness_amendment_path = ROOT / str(contract["harness_amendment_path"])
    audit = audit_benchmark_v2(ROOT, manifest_path)
    if audit["status"] != "pass":
        raise ValueError(
            "Benchmark v2 design/content audit failed before execution: "
            + ", ".join(audit["failure_ids"])
        )
    manifest = _read_json(manifest_path)
    artifacts_by_role = {
        str(item["role"]): str(item["sha256"])
        for item in manifest["artifacts"]
    }
    artifact_receipts = {
        role: artifacts_by_role[role]
        for role in REQUIRED_ARTIFACT_RECEIPTS
    }
    cases = _read_jsonl(suite_path)
    interface = _read_json(interface_path)
    preregistration = _read_json(preregistration_path)
    exposure_amendment = _read_json(exposure_amendment_path)
    harness_contract = _read_json(harness_contract_path)
    harness_amendment = _read_json(harness_amendment_path)
    executor = DeterministicContractExecutor()
    model = ModelIdentity(
        model_id="deterministic-contract-qa",
        model_revision="v1",
        backend="no_model_inference",
        configuration_sha256=file_sha256(contract_path),
    )
    run = run_benchmark_v2(
        cases=cases,
        interface=interface,
        model=model,
        executor=executor,
        suite_sha256=file_sha256(suite_path),
        interface_sha256=file_sha256(interface_path),
        contract_sha256=file_sha256(contract_path),
        harness_contract=harness_contract,
        harness_amendment=harness_amendment,
        artifact_receipts=artifact_receipts,
        preregistration=preregistration,
        exposure_amendment=exposure_amendment,
        run_id=args.run_id,
    )
    output_dir = args.output_dir or (
        ROOT
        / "outputs/open_agronomy_benchmark_v2"
        / dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ_contract_qa")
    )
    receipt = write_run_bundle(run, output_dir.resolve())
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
