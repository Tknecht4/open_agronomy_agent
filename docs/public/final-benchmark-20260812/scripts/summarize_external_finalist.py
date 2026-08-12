#!/usr/bin/env python3
"""Validate and summarize the one-time external finalist database."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sqlite3
from pathlib import Path
from statistics import mean, median


EXPECTED_VARIANTS = ("raw_model", "full_system")


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_mean_ci(values: list[float], *, seed: int, draws: int = 10_000) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(values)
    boot = [mean(values[rng.randrange(n)] for _ in range(n)) for _ in range(draws)]
    return percentile(boot, 0.025), percentile(boot, 0.975)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--response-output", type=Path)
    args = parser.parse_args()
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"external database integrity check failed: {integrity}")
    rows = [dict(row) for row in connection.execute("""
        SELECT m.model_id, m.model_revision, r.system_variant, resp.eval_id,
               resp.score_json, resp.elapsed_seconds, resp.output_sha256
        FROM benchmark_run r
        JOIN model m USING(model_key)
        JOIN response resp USING(run_id)
        WHERE r.is_canonical = 1
        ORDER BY r.system_variant, resp.eval_id
    """)]
    connection.close()
    if len(rows) != 512:
        raise ValueError(f"expected 512 external responses, found {len(rows)}")
    if {row["system_variant"] for row in rows} != set(EXPECTED_VARIANTS):
        raise ValueError("external database does not contain exactly raw_model and full_system")
    if {row["model_id"] for row in rows} != {freeze["model_id"]}:
        raise ValueError("external model identity does not match finalist freeze")

    arms = {}
    per_case: dict[str, dict[str, float]] = {}
    for variant in EXPECTED_VARIANTS:
        subset = [row for row in rows if row["system_variant"] == variant]
        if len(subset) != 256:
            raise ValueError(f"{variant}: expected 256 responses, found {len(subset)}")
        scores = [json.loads(row["score_json"]) for row in subset]
        values = [float(score["score"]) / 100.0 for score in scores if score.get("proxy_valid")]
        if len(values) != 256:
            raise ValueError(f"{variant}: expected 256 valid diagnostic scores, found {len(values)}")
        arms[variant] = {
            "responses": len(subset),
            "mean_reference_token_f1": round(mean(values), 6),
            "median_reference_token_f1": round(median(values), 6),
            "median_latency_seconds": round(median(float(row["elapsed_seconds"]) for row in subset), 6),
        }
        per_case[variant] = {
            row["eval_id"]: float(json.loads(row["score_json"])["score"]) / 100.0
            for row in subset
        }

    eval_ids = sorted(per_case["raw_model"])
    if set(eval_ids) != set(per_case["full_system"]):
        raise ValueError("external arm case identities do not match")
    deltas = [per_case["full_system"][eval_id] - per_case["raw_model"][eval_id] for eval_id in eval_ids]
    low, high = bootstrap_mean_ci(deltas, seed=20260812)
    paired = {
        "mean_full_system_minus_raw": round(mean(deltas), 6),
        "fixed_suite_bootstrap_ci95": [round(low, 6), round(high, 6)],
        "bootstrap_draws": 10_000,
        "bootstrap_seed": 20260812,
        "improved_cases": sum(value > 0 for value in deltas),
        "unchanged_cases": sum(value == 0 for value in deltas),
        "worse_cases": sum(value < 0 for value in deltas),
        "uncertainty_boundary": "Case-resampling sensitivity for this fixed geographically mismatched diagnostic only; not a population-generalization interval.",
    }

    output = {
        "schema_version": "open_agronomy_agent.external_finalist_summary.v1",
        "status": "one_time_held_out_transfer_diagnostic_complete",
        "rows": 256,
        "finalist": freeze,
        "arms": arms,
        "paired_comparison": paired,
        "database": str(args.database.resolve()),
        "database_sha256": sha256(args.database),
        "claim_boundary": "Uganda-source normalized reference-token overlap diagnostic only; not Canadian validation or agronomist review.",
        "same_version_repair_allowed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if args.response_output:
        args.response_output.parent.mkdir(parents=True, exist_ok=True)
        with args.response_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["eval_id", "raw_reference_token_f1", "full_system_reference_token_f1", "paired_delta"])
            writer.writeheader()
            for eval_id in eval_ids:
                raw = per_case["raw_model"][eval_id]
                full = per_case["full_system"][eval_id]
                writer.writerow(
                    {
                        "eval_id": eval_id,
                        "raw_reference_token_f1": round(raw, 6),
                        "full_system_reference_token_f1": round(full, 6),
                        "paired_delta": round(full - raw, 6),
                    }
                )
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
