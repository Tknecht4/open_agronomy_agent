#!/usr/bin/env python3
"""Prepare the saved-field MAPAQ terrain index and private vector summaries."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agronomy_agent.offline_context_packs import (
    DEFAULT_QUEBEC_CONTEXT_MANIFEST,
    DEFAULT_QUEBEC_LIDAR_INDEX,
    derive_quebec_lidar_field_context,
    download_and_freeze_quebec_lidar_pack,
    download_quebec_lidar_index,
    plan_quebec_lidar_field_pack,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch-index", help="Fetch and verify the pinned official tile index")
    fetch.add_argument("--source-manifest", type=Path, default=DEFAULT_QUEBEC_CONTEXT_MANIFEST)
    fetch.add_argument("--output", type=Path, default=DEFAULT_QUEBEC_LIDAR_INDEX)
    fetch.add_argument("--online", action="store_true")
    plan = commands.add_parser("plan", help="Find tiles using local verified bytes")
    plan.add_argument("--source-manifest", type=Path, default=DEFAULT_QUEBEC_CONTEXT_MANIFEST)
    plan.add_argument("--index", type=Path, default=DEFAULT_QUEBEC_LIDAR_INDEX)
    plan.add_argument("--geometry", type=Path, required=True, help="WGS84 Polygon or MultiPolygon GeoJSON")
    plan.add_argument("--output", type=Path, required=True)
    download = commands.add_parser("download", help="Download bounded official archives and freeze their hashes")
    download.add_argument("--plan", type=Path, required=True)
    download.add_argument("--directory", type=Path, required=True)
    download.add_argument("--output", type=Path, required=True)
    download.add_argument("--online", action="store_true")
    derive = commands.add_parser("derive", help="Clip the frozen vectors to the exact planned field")
    derive.add_argument("--plan", type=Path, required=True)
    derive.add_argument("--frozen", type=Path, required=True)
    derive.add_argument("--geometry", type=Path, required=True)
    derive.add_argument("--directory", type=Path, required=True)
    derive.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command != "fetch-index" and args.output.exists():
            raise ValueError("Choose a new output path to retain the existing receipt")
        if args.command in {"plan", "derive"}:
            if args.geometry.stat().st_size > 100_000:
                raise ValueError("GeoJSON exceeds 100 KB")
            geometry = json.loads(args.geometry.read_text())
        if args.command == "fetch-index":
            result = download_quebec_lidar_index(
                source_manifest_path=args.source_manifest,
                output_path=args.output,
                allow_network=args.online,
            )
        elif args.command == "plan":
            result = plan_quebec_lidar_field_pack(
                field_geometry=geometry,
                source_manifest_path=args.source_manifest,
                index_path=args.index,
            )
        elif args.command == "download":
            result = download_and_freeze_quebec_lidar_pack(
                plan=json.loads(args.plan.read_text()),
                download_dir=args.directory,
                output_manifest=args.output,
                allow_network=args.online,
            )
        else:
            result = derive_quebec_lidar_field_context(
                plan=json.loads(args.plan.read_text()),
                frozen=json.loads(args.frozen.read_text()),
                field_geometry=geometry,
                download_dir=args.directory,
            )
        if args.command in {"plan", "derive"}:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"Terrain preparation failed. {error}\n")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
