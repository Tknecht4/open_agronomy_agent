#!/usr/bin/env python3
"""Plan the frozen v3 competence-candidate matrix without generating it."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from agronomy_agent.benchmark_arms import execution_arm
from agronomy_agent.execution_core import EXECUTION_STAGE_IDS, execution_fingerprints
from agronomy_agent.judge_authorization import canonical_sha256
from agronomy_agent.v3_candidate_runner import (
    AppendOnlyObservationLedger,
    build_matrix,
    matrix_manifest,
    run_matrix,
    execute_in_fresh_process,
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
    parser.add_argument("--executor-ref")
    parser.add_argument("--execution-ledger", type=Path)
    parser.add_argument("--execution-authorization", type=Path)
    parser.add_argument("--observation-timeout-seconds", type=float, default=600.0)
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
        if not args.executor_ref or not args.execution_ledger or not args.execution_authorization:
            raise SystemExit("--execute requires --executor-ref, --execution-ledger, and --execution-authorization")
        authorization_path = args.execution_authorization if args.execution_authorization.is_absolute() else ROOT / args.execution_authorization
        authorization = json.loads(authorization_path.read_text())
        now = dt.datetime.now(dt.UTC)
        expires = dt.datetime.fromisoformat(str(authorization.get("expires_at") or "").replace("Z", "+00:00"))
        if (
            authorization.get("authorization_decision") != "authorized"
            or authorization.get("benchmark_id") != config["benchmark_id"]
            or authorization.get("matrix_manifest_sha256") != manifest["manifest_sha256"]
            or authorization.get("benchmark_contract_sha256") != canonical_sha256(config)
            or authorization.get("candidate_models_sha256") != canonical_sha256(config["candidate_models"])
            or set(authorization.get("permitted_payload_classes") or []) != {
                "public_external_competence_cases",
                "synthetic_regional_competence_cases",
                "public_release_evidence",
            }
            or expires.tzinfo is None
            or now >= expires
        ):
            raise SystemExit("candidate execution authorization is absent, expired, or identity-mismatched")
        ledger_path = args.execution_ledger if args.execution_ledger.is_absolute() else ROOT / args.execution_ledger
        ledger = AppendOnlyObservationLedger(ledger_path, matrix)
        executed = run_matrix(
            matrix=matrix,
            ledger=ledger,
            executor=lambda request: execute_in_fresh_process(
                request,
                executor_ref=args.executor_ref,
                timeout_seconds=args.observation_timeout_seconds,
            ),
        )
        print(json.dumps({"executed_rows": executed, "ledger": str(ledger_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
