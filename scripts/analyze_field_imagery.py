#!/usr/bin/env python3
"""Create one bounded anonymous HLS scene chip and source-bound receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.imagery_analytics import analyze_scene


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", required=True, type=Path, help="WGS84 GeoJSON Polygon/Feature")
    parser.add_argument("--provider", required=True, choices=("hls-s30-planetary-computer", "hls-l30-planetary-computer"))
    parser.add_argument("--scene-id", help="exact hls2-s30:... or hls2-l30:... scene ID")
    parser.add_argument("--start-date", help="ISO date when selecting a scene")
    parser.add_argument("--end-date", help="ISO date when selecting a scene")
    parser.add_argument("--cache-root", required=True, type=Path, help="local cache outside checkout")
    parser.add_argument("--buffer-m", type=int, default=0, help="0-3000 m visual/context buffer; field statistics use original polygon")
    parser.add_argument("--context-pixels", type=int, choices=(224,), help="native 224 x 224 model context; field statistics use original polygon")
    parser.add_argument("--online", action="store_true", help="allow public STAC, token and COG range requests")
    args = parser.parse_args()
    payload = json.loads(args.geometry.read_text(encoding="utf-8"))
    geometry = payload.get("geometry") if payload.get("type") == "Feature" else payload
    result = analyze_scene(geometry, args.provider, args.scene_id, cache_root=args.cache_root,
                           network_mode="online" if args.online else "offline",
                           start_date=args.start_date, end_date=args.end_date, buffer_m=args.buffer_m,
                           context_pixels=args.context_pixels)
    print(json.dumps(result, indent=2))
    if result["status"] not in ("available", "empty_valid_area"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
