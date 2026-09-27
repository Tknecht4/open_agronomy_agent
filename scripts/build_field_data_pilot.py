"""Build source-pinned exposed field-data pilot fixtures, without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agronomy_agent.field_data_benchmark import build_pilot  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path,
                        default=root / "data/raw/field_data_research/20260927/us",
                        help="Directory containing the two SHA-pinned original CSVs")
    parser.add_argument("--output-root", type=Path,
                        default=root / "data/eval/field_data_pilot_v1",
                        help="New empty directory for fixtures, manifest and separate gold cases")
    args = parser.parse_args()
    try:
        result = build_pilot(args.source_root, args.output_root)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"field-data pilot build failed: {exc}\n")
    print(json.dumps({"output_root": str(args.output_root), "bundle_count": result["bundle_count"],
                      "case_count": result["case_count"], "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
