#!/usr/bin/env python3
"""Reanalyze retained release evidence offline, optionally exporting private review context."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agronomy_agent.release_evaluation import evaluation_entrypoints, write_new_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--inventory", action="store_true", help="List source-bound execution/analysis seams without running tests or inference.")
    parser.add_argument("--diagnostic-closeout", type=Path, help="Sealed six-cell closeout; existing observations only, no inference.")
    parser.add_argument("--development-panel", type=Path, help="Sealed private panel; bind synthetic QA fixtures without worker execution.")
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--model-rubrics", type=Path, help="Private case-hash-bound criterion rubric JSONL.")
    parser.add_argument("--criterion-reviews", type=Path, help="Private answer/rubric-bound criterion review JSONL.")
    parser.add_argument("--model-policy", type=Path, help="Explicit project weighting/missingness policy JSON.")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--export-review-packet", action="store_true")
    args = parser.parse_args()
    if args.inventory:
        if any((args.run_dir, args.diagnostic_closeout, args.development_panel, args.reviews, args.reference,
                args.export_review_packet, args.model_rubrics, args.criterion_reviews, args.model_policy)):
            parser.error("--inventory cannot be mixed with retained-run analysis inputs")
        inventory = evaluation_entrypoints()
        if args.output_dir:
            if args.output_dir.exists() and any(args.output_dir.iterdir()):
                parser.error("inventory output must be a new or empty directory")
            write_new_json(args.output_dir / "execution-inventory.json", inventory)
        print(json.dumps(inventory, indent=2))
        return 0
    if args.development_panel:
        if any((args.run_dir, args.diagnostic_closeout, args.reviews, args.reference,
                args.export_review_packet, args.model_rubrics, args.criterion_reviews)) or not args.output_dir:
            parser.error("--development-panel requires --output-dir and accepts only an optional --model-policy")
        from agronomy_agent.release_eval_reanalysis import analyze_development_panel

        report = analyze_development_panel(directory=args.development_panel,
                                           output_dir=args.output_dir, policy_path=args.model_policy)
        print(json.dumps({"output_dir": str(args.output_dir), "status": report["status"],
                          "synthetic_fixture_only": True, "inference_executed": False}))
        return 0 if report["status"] == "descriptive_complete" else 1
    if args.diagnostic_closeout:
        if any((args.run_dir, args.reviews, args.reference, args.export_review_packet)) or not args.output_dir:
            parser.error("--diagnostic-closeout requires --output-dir and cannot mix with retained release inputs")
        from agronomy_agent.release_eval_reanalysis import analyze_diagnostic_closeout

        report = analyze_diagnostic_closeout(
            directory=args.diagnostic_closeout, output_dir=args.output_dir,
            rubrics_path=args.model_rubrics, reviews_path=args.criterion_reviews,
            policy_path=args.model_policy,
        )
        print(json.dumps({"output_dir": str(args.output_dir), "status": report["status"],
                          "inference_executed": False, "full_suite_executed": False}))
        return 0 if report["status"] == "descriptive_complete" else 1
    if not args.run_dir or not args.output_dir:
        parser.error("--run-dir and --output-dir are required for retained analysis")
    from agronomy_agent.release_eval_reanalysis import reanalyze

    report = reanalyze(
        run_dir=args.run_dir,
        output_dir=args.output_dir,
        reviews_path=args.reviews,
        reference_path=args.reference,
        export_review_packet=args.export_review_packet,
        model_rubrics_path=args.model_rubrics,
        criterion_reviews_path=args.criterion_reviews,
        model_policy_path=args.model_policy,
    )
    metrics_path = args.output_dir / "model-metrics.json"
    metrics_status = json.loads(metrics_path.read_text())["status"] if metrics_path.is_file() else None
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "status": report["status"],
                "domain_status": report["domain_status"],
                "inference_executed": False,
                "model_metrics_status": metrics_status,
            }
        )
    )
    return 1 if report["status"] == "blocked" or metrics_status not in {None, "descriptive_complete"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
