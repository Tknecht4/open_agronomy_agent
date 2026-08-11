#!/usr/bin/env python3
"""Exercise installed Prairie spatial layers at three fixed Canadian fields.

The pack-level validator proves byte and SQLite integrity. This probe proves
that the application service can discover the pack, perform offline RTree and
geometry intersections, and expose soil-component context for representative
Alberta, Saskatchewan, and Manitoba field polygons.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = (
    {
        "sample_id": "ab_edmonton_south",
        "province": "Alberta",
        "layer_id": "ab_detailed_soil",
        "bbox": (-113.608, 53.296, -113.592, 53.304),
        "expected_scale": "1:100,000",
    },
    {
        "sample_id": "sk_regina_south",
        "province": "Saskatchewan",
        "layer_id": "sk_detailed_soil",
        "bbox": (-104.734, 50.447, -104.726, 50.453),
        "expected_scale": "1:100,000",
    },
    {
        "sample_id": "mb_brandon_south",
        "province": "Manitoba",
        "layer_id": "mb_detailed_soil",
        "bbox": (-99.959, 49.865, -99.941, 49.875),
        "expected_scale": "multiple published scales from 1:20,000 to 1:126,720",
    },
)


def _polygon(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    west, south, east, north = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
    }


def run_probe(pack_root: Path) -> dict[str, Any]:
    os.environ["AGRONOMY_AGENT_SPATIAL_PACK_ROOT"] = str(pack_root)
    source_root = ROOT / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from agronomy_agent.server.services.geospatial_service import (  # noqa: PLC0415
        intersect_region_layers,
        layer_catalog,
    )
    from agronomy_agent.query_context import extract_field_graph_terms  # noqa: PLC0415

    catalog = layer_catalog(network_mode="offline")
    catalog_by_id = {row["id"]: row for row in catalog["layers"]}
    errors: list[str] = []
    samples: list[dict[str, Any]] = []
    for sample in SAMPLES:
        layer_id = str(sample["layer_id"])
        installation = catalog_by_id.get(layer_id) or {}
        result = intersect_region_layers(
            geometry=_polygon(sample["bbox"]),
            layer_ids=[layer_id],
            network_mode="offline",
        )
        intersections = result.get("intersections") or []
        dominant_component_count = sum(
            len(row.get("dominant_components") or []) for row in intersections
        )
        observed_scales = sorted(
            {
                str(row.get("source_scale"))
                for row in intersections
                if row.get("source_scale")
            }
        )
        graph_bridge_terms = list(
            extract_field_graph_terms({"regional_intersections": intersections})
        )
        sample_errors: list[str] = []
        if installation.get("installation_status") != "installed":
            sample_errors.append("layer_not_installed")
        if result.get("errors"):
            sample_errors.append("runtime_query_error")
        if not intersections:
            sample_errors.append("no_field_intersection")
        if dominant_component_count <= 0:
            sample_errors.append("no_soil_components")
        if not graph_bridge_terms:
            sample_errors.append("no_soilwise_bridge_terms")
        if sample["expected_scale"] not in observed_scales:
            sample_errors.append("unexpected_or_missing_source_scale")
        errors.extend(f"{sample['sample_id']}:{error}" for error in sample_errors)
        samples.append(
            {
                **sample,
                "bbox": list(sample["bbox"]),
                "installation_status": installation.get("installation_status"),
                "feature_count": result.get("feature_count"),
                "intersection_count": len(intersections),
                "dominant_component_count": dominant_component_count,
                "soilwise_bridge_terms": graph_bridge_terms,
                "observed_source_scales": observed_scales,
                "runtime_errors": result.get("errors") or [],
                "status": "pass" if not sample_errors else "fail",
                "errors": sample_errors,
            }
        )
    return {
        "schema_version": "open_agronomy_agent.prairie_spatial_runtime_probe.v1",
        "status": "pass" if not errors else "fail",
        "pack_root": str(pack_root),
        "network_mode": "offline",
        "sample_count": len(samples),
        "samples": samples,
        "errors": errors,
        "boundary": (
            "This is an application-path and geographic-alignment probe, not validation "
            "of map-unit truth at these fields or agronomic management advice."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_probe(args.pack_root.resolve())
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
