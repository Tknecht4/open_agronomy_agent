#!/usr/bin/env python3
"""Plan the frozen v3 competence-candidate matrix without generating it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.benchmark_arms import execution_arm
from agronomy_agent.execution_core import EXECUTION_STAGE_IDS, execution_fingerprints
from agronomy_agent.v3_candidate_runner import (
    AppendOnlyObservationLedger,
    build_matrix,
    matrix_manifest,
    run_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/open_agronomy_v3_competence_candidate.json")
    parser.add_argument("--inputs", type=Path, default=ROOT / "outputs/v3_competence_candidate/inputs")
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run-ledger", type=Path)
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    inputs = args.inputs if args.inputs.is_absolute() else ROOT / args.inputs
    config = json.loads(config_path.read_text())
    matrix = build_matrix(
        config=config,
        external_cases=_jsonl(inputs / "external_cases.jsonl"),
        regional_cases=_jsonl(inputs / "regional_cases.jsonl"),
    )
    manifest = matrix_manifest(matrix)
    if args.manifest_output:
        output = args.manifest_output if args.manifest_output.is_absolute() else ROOT / args.manifest_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if args.dry_run_ledger:
        ledger_path = args.dry_run_ledger if args.dry_run_ledger.is_absolute() else ROOT / args.dry_run_ledger
        ledger = AppendOnlyObservationLedger(ledger_path, matrix)

        def mock_executor(request):
            arm = execution_arm(request.arm)
            fingerprints = execution_fingerprints(
                arm=arm.to_dict(),
                harness={"backend": "deterministic_matrix_dry_run_v1"},
                model={"model_key": request.model_key, "backend": "deterministic_mock"},
            )
            return {
                **request.to_dict(),
                "status": "dry_run_complete",
                "row_disposition": "accepted",
                "dry_run_only": True,
                "claim_eligible": False,
                "stage_receipt_count": len(EXECUTION_STAGE_IDS) if arm.governed_topology else 0,
                "fingerprints": {
                    key.removesuffix("_fingerprint"): value
                    for key, value in fingerprints.items()
                },
                "private_retention_id": f"dry_private_{request.observation_id}",
                "public_projection_id": f"dry_public_{request.observation_id}",
            }

        executed = run_matrix(matrix=matrix, ledger=ledger, executor=mock_executor)
        print(json.dumps({"dry_run_rows_appended": executed, "ledger": str(ledger_path)}, sort_keys=True))
    if args.execute:
        raise SystemExit("real execution is blocked until production-core observation execution, model snapshots, and recipient-bound authorizations are supplied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
