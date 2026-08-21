#!/usr/bin/env python3
"""Fail-closed audit for the exposed v3 competence-candidate execution."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/open_agronomy_v3_competence_candidate.json"
REQUIRED_CONTROL_IDS = {
    "answer_order_reversal",
    "concise_correct_vs_verbose_vague",
    "supported_vs_cosmetic_citation",
    "useful_caution_vs_blanket_refusal",
    "corrupted_reference_negative",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"row {line_number} is not an object: {path}")
        rows.append(value)
    return rows


def audit(
    *,
    config: dict[str, Any],
    input_manifest: dict[str, Any] | None,
    results: list[dict[str, Any]] | None,
    semantic_controls: dict[str, Any] | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str, evidence: Any = None) -> None:
        checks.append({"id": check_id, "passed": bool(passed), "detail": detail, "evidence": evidence})

    check(
        "candidate_contract_boundary",
        config.get("claim_eligible") is False
        and config.get("sealed_v3_satisfied") is False
        and config.get("status") == "public_external_reference_candidate_frozen",
        "the public competence candidate cannot be represented as sealed v3",
    )
    check(
        "input_bundle",
        input_manifest is not None
        and input_manifest.get("status") == "frozen_inputs_verified"
        and input_manifest.get("external_rows") == config.get("external_dataset", {}).get("rows")
        and input_manifest.get("regional_rows") == config.get("regional_case_count")
        and input_manifest.get("sealed_v3_satisfied") is False,
        "the exact external and regional inputs were acquired and verified",
        input_manifest,
    )

    expected_external = (
        int(config["external_dataset"]["rows"])
        * len(config["external_arm_order"])
        * len(config["trial_ids"])
    )
    expected_regional = (
        int(config["regional_case_count"])
        * len(config["regional_arm_order"])
        * len(config["trial_ids"])
    )
    observed_counts: Counter[str] = Counter()
    duplicate_observations: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    invalid_model_rows = 0
    incomplete_stage_rows = 0
    if results is not None:
        for row in results:
            lane = str(row.get("lane") or "")
            observed_counts[lane] += 1
            key = (
                lane,
                str(row.get("eval_id") or ""),
                str(row.get("arm") or ""),
                str(row.get("trial_id") or ""),
            )
            if key in seen:
                duplicate_observations.append("|".join(key))
            seen.add(key)
            if (
                row.get("model_id") != config["candidate_model"]["model_id"]
                or row.get("model_revision") != config["candidate_model"]["model_revision"]
            ):
                invalid_model_rows += 1
            if lane == "canadian_regional_competence_candidate" and row.get("arm") != "raw_model":
                if int(row.get("stage_receipt_count") or 0) != 17:
                    incomplete_stage_rows += 1
    check(
        "complete_execution_matrix",
        results is not None
        and observed_counts["public_external_competence_candidate"] == expected_external
        and observed_counts["canadian_regional_competence_candidate"] == expected_regional
        and not duplicate_observations,
        "all declared arms and trials are present exactly once",
        {
            "expected_external": expected_external,
            "observed_external": observed_counts["public_external_competence_candidate"],
            "expected_regional": expected_regional,
            "observed_regional": observed_counts["canadian_regional_competence_candidate"],
            "duplicate_observations": duplicate_observations[:20],
        },
    )
    check(
        "candidate_identity",
        results is not None and invalid_model_rows == 0,
        "every observation uses the one pinned production Gemma 4 identity",
        {"invalid_rows": invalid_model_rows},
    )
    check(
        "production_stage_receipts",
        results is not None and incomplete_stage_rows == 0,
        "each governed regional observation retains the ordered 17-stage receipt count",
        {"incomplete_rows": incomplete_stage_rows},
    )

    controls = (semantic_controls or {}).get("controls") or []
    control_by_id = {
        str(row.get("id")): row
        for row in controls
        if isinstance(row, dict) and str(row.get("id") or "")
    }
    missing_controls = sorted(REQUIRED_CONTROL_IDS - set(control_by_id))
    failed_controls = sorted(
        control_id
        for control_id in REQUIRED_CONTROL_IDS & set(control_by_id)
        if control_by_id[control_id].get("passed") is not True
    )
    check(
        "semantic_instrument_controls",
        semantic_controls is not None and not missing_controls and not failed_controls,
        "semantic grading is diagnostic until every reference-based control passes",
        {"missing": missing_controls, "failed": failed_controls},
    )

    failures = [row for row in checks if not row["passed"]]
    return {
        "schema_version": "open_agronomy_agent.v3_competence_candidate_audit.v1",
        "benchmark_id": config["benchmark_id"],
        "engineering_rc_status": "ready_for_owner_decision" if not failures else "blocked",
        "sealed_v3_status": "blocked_human_gates_unfulfilled",
        "claim_eligible": False,
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-manifest", type=Path, default=ROOT / "outputs/v3_competence_candidate/inputs/manifest.json")
    parser.add_argument("--results", type=Path)
    parser.add_argument("--semantic-controls", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    def resolve(path: Path | None) -> Path | None:
        if path is None:
            return None
        return path if path.is_absolute() else ROOT / path

    config = _json(resolve(args.config) or DEFAULT_CONFIG)
    input_path = resolve(args.input_manifest)
    result_path = resolve(args.results)
    control_path = resolve(args.semantic_controls)
    report = audit(
        config=config,
        input_manifest=_json(input_path) if input_path and input_path.is_file() else None,
        results=_jsonl(result_path) if result_path and result_path.is_file() else None,
        semantic_controls=_json(control_path) if control_path and control_path.is_file() else None,
    )
    output = resolve(args.output)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["engineering_rc_status"] == "ready_for_owner_decision" else 2


if __name__ == "__main__":
    raise SystemExit(main())
