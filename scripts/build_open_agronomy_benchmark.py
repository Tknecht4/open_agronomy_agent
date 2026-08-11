#!/usr/bin/env python3
"""Build or validate a frozen Open Agronomy benchmark contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_contract import validate_benchmark, write_benchmark


DEFAULT_CONTRACT = ROOT / "configs" / "open_agronomy_canadian_performance_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--check", action="store_true", help="Validate without rewriting artifacts.")
    args = parser.parse_args()
    contract = args.contract.resolve()
    result = validate_benchmark(ROOT, contract) if args.check else write_benchmark(ROOT, contract)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
