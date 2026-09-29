#!/usr/bin/env python3
"""Reanalyze retained release evidence offline, optionally exporting private review context."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agronomy_agent.release_eval_reanalysis import reanalyze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--export-review-packet", action="store_true")
    args = parser.parse_args()
    report = reanalyze(
        run_dir=args.run_dir,
        output_dir=args.output_dir,
        reviews_path=args.reviews,
        reference_path=args.reference,
        export_review_packet=args.export_review_packet,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "status": report["status"],
                "domain_status": report["domain_status"],
                "inference_executed": False,
            }
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
