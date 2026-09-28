#!/usr/bin/env python3
"""Prepare pinned local field datasets into a new, offline review-only bundle."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from agronomy_agent.field_source_preparation import RAW_DIRECTORY, prepare_sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path(__file__).resolve().parents[1] / RAW_DIRECTORY)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing destinations refused")
    args = parser.parse_args()
    index = prepare_sources(args.raw_root, args.output_dir)
    print(json.dumps({"status": index["status"], "groups": len(index["groups"]), "rows": sum(g["row_count"] for g in index["groups"]), "index": str(args.output_dir / "index.json")}, indent=2))


if __name__ == "__main__":
    main()
