#!/usr/bin/env python3
"""Inspect bounded public imagery metadata for a WGS84 GeoJSON field polygon."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.field_imagery import provider_catalog, probe_asset_range, search_field_imagery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", action="store_true", help="show provider catalog without network access")
    parser.add_argument("--geometry", type=Path, help="path to GeoJSON Point, Polygon or Feature")
    parser.add_argument("--provider", help="provider ID from --providers")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--online", action="store_true", help="permit bounded public STAC requests")
    parser.add_argument("--probe", help="asset key to probe from the first returned scene (max 16 KiB)")
    args = parser.parse_args()
    if args.providers:
        print(json.dumps(provider_catalog(), indent=2))
        return
    if not all((args.geometry, args.provider, args.start_date, args.end_date)):
        parser.error("--geometry, --provider, --start-date and --end-date are required")
    payload = json.loads(args.geometry.read_text(encoding="utf-8"))
    geometry = payload.get("geometry") if payload.get("type") == "Feature" else payload
    result = search_field_imagery(
        geometry, args.provider, args.start_date, args.end_date,
        limit=args.limit, network_mode="online" if args.online else "offline",
    )
    if args.probe and result["scenes"]:
        result["probe"] = probe_asset_range(
            result["scenes"][0], args.probe, args.provider,
            network_mode="online" if args.online else "offline",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
