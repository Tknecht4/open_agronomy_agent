#!/usr/bin/env python3
"""Prepare one pinned CSCAP site for the existing typed table import path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.cscap_intake import prepare_cscap_intake


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True, help="Existing captured workbook and article metadata; no download")
    parser.add_argument("--output-dir", type=Path, required=True, help="New small review bundle; existing destinations refused")
    args = parser.parse_args()
    receipt = prepare_cscap_intake(args.raw_root, args.output_dir)
    print(json.dumps({"status": receipt["status"], "rows": receipt["row_count"], "plots": receipt["plot_count"],
                      "runtime_rag_chunks": receipt["runtime_rag_chunks"], "receipt": str(args.output_dir / "source-receipt.json")}, indent=2))


if __name__ == "__main__":
    main()
