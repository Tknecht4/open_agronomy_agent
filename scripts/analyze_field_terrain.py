#!/usr/bin/env python3
"""Derive bounded terrain context from a local DTM; no network or drainage diagnosis."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agronomy_agent.geospatial.terrain import TerrainError, run_terrain_analysis, terrain_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", action="store_true", help="Report optional dependency installation without processing")
    parser.add_argument("--dem", type=Path, help="Local single-band bare-earth DTM GeoTIFF; projected metres, square cells")
    parser.add_argument("--geometry", type=Path, help="Local WGS84 Polygon/MultiPolygon or Feature JSON")
    parser.add_argument("--source-metadata", type=Path, help="JSON: source_id, source_url, source_date, license, terrain_type=DTM, bare_earth=true, vertical_units=m, vertical_datum")
    parser.add_argument("--output-dir", type=Path, help="New output directory; existing directories are refused")
    parser.add_argument("--context-buffer-m", type=float, help="Explicit context around the field bounding rectangle, at least two cells")
    parser.add_argument("--max-cells", type=int, default=1_000_000, help="Context cell budget, 1 to 1000000")
    parser.add_argument("--include-twi", action="store_true", help="Optional D8 TWI; flat slopes/edge-influenced cells remain unknown")
    args = parser.parse_args(argv)
    if args.readiness:
        print(json.dumps(terrain_readiness(), indent=2))
        return 0
    for name in ("dem", "geometry", "source_metadata", "output_dir", "context_buffer_m"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required unless --readiness is used")
    try:
        for path in (args.geometry, args.source_metadata):
            if path.stat().st_size > 2 * 1024 * 1024:
                raise TerrainError("Geometry and metadata JSON inputs are limited to 2 MiB each")
        result = run_terrain_analysis(
            args.dem, json.loads(args.geometry.read_text()), args.output_dir,
            source_metadata=json.loads(args.source_metadata.read_text()),
            context_buffer_m=args.context_buffer_m, include_twi=args.include_twi,
            max_cells=args.max_cells,
        )
    except (TerrainError, OSError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "manifest": str(args.output_dir.resolve() / "terrain.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
