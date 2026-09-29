"""Optional local optical imagery worker, usable from a checkout or packaged runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.imagery_analytics import analyze_scene
from agronomy_agent.imagery_budget import DEFAULT_MAX_CACHE_BYTES, DEFAULT_MIN_FREE_BYTES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", required=True, type=Path, help="WGS84 GeoJSON Point/Polygon/Feature")
    parser.add_argument("--provider", required=True, choices=("hls-s30-planetary-computer", "hls-l30-planetary-computer", "sentinel2-c1-earth-search"))
    parser.add_argument("--scene-id", help="exact provider collection:item ID")
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
    parser.add_argument("--cloud-buffer-m", type=int, default=None, help="Sentinel-2 cloud/shadow adjacency, default 60 m")
    parser.add_argument("--edge-buffer-m", type=int, default=None, help="Sentinel-2 field-interior reporting margin, default 20 m")
    parser.add_argument("--online", action="store_true", help="allow public STAC, token and COG requests")
    args = parser.parse_args()
    if args.geometry.stat().st_size > 128 * 1024:
        parser.error("geometry file exceeds 128 KiB")
    payload = json.loads(args.geometry.read_text(encoding="utf-8"))
    geometry = payload.get("geometry") if payload.get("type") == "Feature" else payload
    if args.provider == "sentinel2-c1-earth-search":
        if args.buffer_m or args.context_pixels is not None or args.sample_radius_m is not None or args.sampling_mode not in (None, "field_polygon"):
            parser.error("Sentinel-2 currently supports field polygons without HLS buffer/context/point options")
        from agronomy_agent.sentinel2_analytics import analyze_sentinel2_scene
        result = analyze_sentinel2_scene(
            geometry, args.scene_id, cache_root=args.cache_root,
            budget_root=args.budget_root, max_cache_bytes=args.max_cache_bytes,
            min_free_bytes=args.min_free_bytes, network_mode="online" if args.online else "offline",
            start_date=args.start_date, end_date=args.end_date,
            cloud_buffer_m=60 if args.cloud_buffer_m is None else args.cloud_buffer_m,
            edge_buffer_m=20 if args.edge_buffer_m is None else args.edge_buffer_m)
    else:
        if args.cloud_buffer_m is not None or args.edge_buffer_m is not None:
            parser.error("cloud/edge buffer options are specific to Sentinel-2")
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
