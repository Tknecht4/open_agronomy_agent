#!/usr/bin/env python3
"""List public sources or discover one bounded metadata page for a field."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.geospatial.catalog import source_catalog
from agronomy_agent.geospatial.discovery import discover_sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", action="store_true", help="Print source/access definitions without network access")
    parser.add_argument("--geometry", type=Path, help="WGS84 GeoJSON point/polygon/multipolygon")
    parser.add_argument("--source-id")
    parser.add_argument("--context-buffer-m", type=int, default=0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--online", action="store_true", help="Send geometry/extent to the selected public catalog")
    args = parser.parse_args()
    if args.catalog:
        result = source_catalog()
    else:
        if not args.geometry or not args.source_id:
            parser.error("--geometry and --source-id are required unless --catalog is used")
        if args.geometry.stat().st_size > 100_000:
            parser.error("GeoJSON exceeds 100 KB")
        try:
            result = discover_sources(json.loads(args.geometry.read_text()), args.source_id,
                context_buffer_m=args.context_buffer_m, limit=args.limit,
                start_date=args.start_date, end_date=args.end_date,
                network_mode="online" if args.online else "offline")
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
