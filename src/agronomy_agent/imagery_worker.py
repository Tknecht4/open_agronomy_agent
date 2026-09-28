"""Optional local HLS worker, usable from a checkout or packaged runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.imagery_analytics import analyze_scene
from agronomy_agent.imagery_budget import DEFAULT_MAX_CACHE_BYTES, DEFAULT_MIN_FREE_BYTES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", required=True, type=Path, help="WGS84 GeoJSON Point/Polygon/Feature")
    parser.add_argument("--provider", required=True, choices=("hls-s30-planetary-computer", "hls-l30-planetary-computer"))
    parser.add_argument("--scene-id", help="exact HLS scene ID")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--cache-root", required=True, type=Path, help="private cache outside runtime/checkout")
    parser.add_argument("--budget-root", type=Path, help="shared cache parent whose capacity covers all fields")
    parser.add_argument("--max-cache-bytes", type=int, default=DEFAULT_MAX_CACHE_BYTES)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--buffer-m", type=int, default=0)
    parser.add_argument("--sampling-mode", choices=("field_polygon", "point_pixel", "point_buffer"))
    parser.add_argument("--sample-radius-m", type=int)
    parser.add_argument("--context-pixels", type=int, choices=(224,))
    parser.add_argument("--online", action="store_true", help="allow public STAC, token and COG requests")
    args = parser.parse_args()
    if args.geometry.stat().st_size > 128 * 1024:
        parser.error("geometry file exceeds 128 KiB")
    payload = json.loads(args.geometry.read_text(encoding="utf-8"))
    geometry = payload.get("geometry") if payload.get("type") == "Feature" else payload
    result = analyze_scene(
        geometry, args.provider, args.scene_id, cache_root=args.cache_root,
        budget_root=args.budget_root, max_cache_bytes=args.max_cache_bytes,
        min_free_bytes=args.min_free_bytes, network_mode="online" if args.online else "offline",
        start_date=args.start_date, end_date=args.end_date, buffer_m=args.buffer_m,
        context_pixels=args.context_pixels, sampling_mode=args.sampling_mode,
        sample_radius_m=args.sample_radius_m)
    print(json.dumps(result, indent=2))
    if result["status"] not in ("available", "empty_valid_area"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
