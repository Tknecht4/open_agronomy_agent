#!/usr/bin/env python3
"""Run the expandable release suite, retain every cell, and enforce its gates."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agronomy_agent.release_evaluation import (
    DEFAULT_REGISTRY,
    FINAL_REGISTRY,
    build_plan,
    bind_controller_inputs,
    read_controller_inputs,
    read_stop_policy,
    bind_stop_policy,
    load_registry,
    write_new_json,
)  # noqa: E402
from agronomy_agent.release_eval_runner import execute_worker, run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--registry", type=Path)
    scope.add_argument(
        "--final-suite", action="store_true",
        help="require the complete prepared question catalog after significant harness changes",
    )
    parser.add_argument(
        "--profile", choices=("ci", "smoke", "baseline", "release")
    )
    parser.add_argument("--run-id", default="evaluation")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--model-rubrics", type=Path)
    parser.add_argument("--model-policy", type=Path)
    parser.add_argument("--comparison-cohort")
    parser.add_argument("--stop-policy", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    registry_path = FINAL_REGISTRY if args.final_suite else args.registry or DEFAULT_REGISTRY
    profile = args.profile or ("baseline" if args.final_suite else "ci")
    if args.final_suite and (profile not in {"baseline", "release"} or args.limit is not None):
        parser.error("--final-suite requires baseline or release and accepts no case limit")
    # Public/synthetic suite execution never inherits a private local overlay.
    # Canonical external envelopes require the explicit off sentinel too.
    os.environ["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] = "0"
    os.environ.pop("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", None)
    try:
        if args.worker_spec:
            if not args.worker_output:
                parser.error("worker output is required")
            try:
                result = execute_worker(json.loads(args.worker_spec.read_text()))
            except Exception as exc:
                result = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "checks": [{"id": "worker_execution", "passed": False}],
                }
            write_new_json(args.worker_output, result)
            return 1 if result.get("status") in {"failed", "blocked"} else 0
        if args.dry_run:
            registry = load_registry(registry_path)
            plan = build_plan(
                registry,
                profile=profile,
                limit=args.limit,
                run_id=args.run_id,
            )
            plan = bind_controller_inputs(plan, read_controller_inputs(rubrics_path=args.model_rubrics, policy_path=args.model_policy), args.comparison_cohort)
            plan = bind_stop_policy(plan, read_stop_policy(args.stop_policy), registry["whole_run_timeout_seconds"])
            if "external_generation" in registry:
                from agronomy_agent.release_eval_external import read_external_inputs, validate_external_plan
                external = read_external_inputs(registry["external_generation"], ROOT)
                plan["external_admission"] = validate_external_plan(external, plan)
            print(
                json.dumps(
                    {
                        key: plan[key]
                        for key in (
                            "schema_version",
                            "suite_id",
                            "profile",
                            "counts",
                            "sampling",
                            "source",
                            "model",
                            *(["external_admission"] if "external_admission" in plan else []),
                            *(["bounded_stop_policy"] if "bounded_stop_policy" in plan else []),
                            *(["final_inventory", "suites"] if "final_inventory" in plan else []),
                        )
                    },
                    indent=2,
                )
            )
            return 0
        if not args.output_dir:
            parser.error("--output-dir is required for retained execution")
        result = run_suite(
            registry_path=registry_path,
            profile=profile,
            output_dir=args.output_dir,
            run_id=args.run_id,
            resume=args.resume,
            limit=args.limit,
            reference_path=args.reference,
            reviews_path=args.reviews,
            model_rubrics_path=args.model_rubrics,
            model_policy_path=args.model_policy,
            comparison_cohort=args.comparison_cohort,
            stop_policy_path=args.stop_policy,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "domain_status": result["domain_status"],
                    "counts": result["counts"],
                    "report": str(args.output_dir / "report.json"),
                    **({"final_suite_coverage": result["final_suite_coverage"]}
                       if "final_suite_coverage" in result else {}),
                }
            )
        )
        return 0 if result["status"] in {"engineering_pass", "smoke_complete"} else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"release evaluation rejected: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
