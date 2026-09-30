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
    build_plan,
    load_registry,
    write_new_json,
)  # noqa: E402
from agronomy_agent.release_eval_runner import execute_worker, run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--profile", choices=("ci", "smoke", "baseline", "release"), default="ci"
    )
    parser.add_argument("--run-id", default="evaluation")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    # Public/synthetic suite execution never inherits a private local overlay.
    os.environ["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] = "disabled"
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
            plan = build_plan(
                load_registry(args.registry),
                profile=args.profile,
                limit=args.limit,
                run_id=args.run_id,
            )
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
                        )
                    },
                    indent=2,
                )
            )
            return 0
        if not args.output_dir:
            parser.error("--output-dir is required for retained execution")
        result = run_suite(
            registry_path=args.registry,
            profile=args.profile,
            output_dir=args.output_dir,
            run_id=args.run_id,
            resume=args.resume,
            limit=args.limit,
            reference_path=args.reference,
            reviews_path=args.reviews,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "domain_status": result["domain_status"],
                    "counts": result["counts"],
                    "report": str(args.output_dir / "report.json"),
                }
            )
        )
        return 0 if result["status"] in {"engineering_pass", "smoke_complete"} else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"release evaluation rejected: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
