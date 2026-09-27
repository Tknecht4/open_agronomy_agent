"""Run exposed real-data field pilot in isolated temporary stores, retaining cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agronomy_agent.field_data_benchmark import run_pilot  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-root", type=Path, default=root / "data/eval/field_data_pilot_v1")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New empty result directory; output records every attempted case")
    parser.add_argument("--limit", type=int, default=None, help="Optional first N cases for a smoke run")
    parser.add_argument("--skip-product", action="store_true",
                        help="Run raw and reviewed-query layers only")
    args = parser.parse_args()
    try:
        summary = run_pilot(args.pilot_root, args.output_dir, limit=args.limit,
                            product=not args.skip_product)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"field-data pilot run failed: {exc}\n")
    print(json.dumps(summary, sort_keys=True))
    return 1 if summary["failed_case_count"] or not summary["runtime_code_stable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
