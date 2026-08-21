#!/usr/bin/env python3
"""Exercise a compact Canadian boundary-context pack through the offline service.

The probe checks location-to-context wiring at known Alberta, Manitoba, and
Ontario points.  It does not claim that a census or ecoregion boundary proves
farm location, field conditions, agronomic suitability, or management action.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from build_prairie_spatial_pack import validate_pack


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_ID = "canada-context-boundaries-v1"
DEFAULT_PROFILE_MANIFEST = ROOT / "data/manifests/offline_spatial_profiles_v1.json"
LAYER_IDS = (
    "ca_statcan_2021_provinces_territories",
    "ca_statcan_2021_census_agricultural_regions",
    "ca_aafc_terrestrial_ecoregions_v2_2",
)
SAMPLES = (
    {
        "sample_id": "ab_edmonton",
        "province": "Alberta",
        "bbox": (-113.57, 53.51, -113.55, 53.53),
    },
    {
        "sample_id": "mb_brandon",
        "province": "Manitoba",
        "bbox": (-99.96, 49.84, -99.94, 49.86),
    },
    {
        "sample_id": "on_guelph",
        "province": "Ontario",
        "bbox": (-80.27, 43.53, -80.25, 43.55),
    },
)


def _polygon(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    west, south, east, north = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
    }


def _first_by_layer(intersections: list[dict[str, Any]], layer_id: str) -> dict[str, Any] | None:
    return next((row for row in intersections if row.get("layer_id") == layer_id), None)


def run_probe(
    pack_root: Path,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    profile_manifest_path: Path = DEFAULT_PROFILE_MANIFEST,
) -> dict[str, Any]:
    pack_validation = validate_pack(
        pack_root,
        profile_id=profile_id,
        profile_manifest_path=profile_manifest_path,
    )
    if pack_validation["status"] != "pass":
        return {
            "schema_version": "open_agronomy_agent.canada_context_boundary_runtime_probe.v1",
            "status": "fail",
            "profile_id": profile_id,
            "pack_root": str(pack_root),
            "network_mode": "offline",
            "sample_count": 0,
            "samples": [],
            "errors": ["pack_validation_failed", *pack_validation["errors"]],
            "pack_validation": pack_validation,
            "boundary": "The runtime probe did not query an invalid or mismatched context-boundary pack.",
        }

    os.environ["AGRONOMY_AGENT_SPATIAL_PACK_ROOT"] = str(pack_root)
    source_root = ROOT / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from agronomy_agent.server.services.geospatial_service import (  # noqa: PLC0415
        intersect_region_layers,
        layer_catalog,
    )

    catalog = {row["id"]: row for row in layer_catalog(network_mode="offline")["layers"]}
    errors: list[str] = []
    samples: list[dict[str, Any]] = []
    for sample in SAMPLES:
        result = intersect_region_layers(
            geometry=_polygon(sample["bbox"]),
            layer_ids=list(LAYER_IDS),
            network_mode="offline",
        )
        intersections = result.get("intersections") or []
        province = _first_by_layer(intersections, "ca_statcan_2021_provinces_territories")
        car = _first_by_layer(intersections, "ca_statcan_2021_census_agricultural_regions")
        ecoregion = _first_by_layer(intersections, "ca_aafc_terrestrial_ecoregions_v2_2")
        sample_errors: list[str] = []
        if result.get("errors"):
            sample_errors.append("runtime_query_error")
        if any(catalog.get(layer_id, {}).get("installation_status") != "installed" for layer_id in LAYER_IDS):
            sample_errors.append("layer_not_installed")
        if not province or province.get("province_name") != sample["province"]:
            sample_errors.append("province_mismatch")
        if not car or not car.get("census_agricultural_region_code") or not car.get("census_agricultural_region"):
            sample_errors.append("missing_census_agricultural_region")
        if not ecoregion or not ecoregion.get("ecoregion_id") or not ecoregion.get("ecoregion"):
            sample_errors.append("missing_ecoregion")
        errors.extend(f"{sample['sample_id']}:{error}" for error in sample_errors)
        samples.append(
            {
                **sample,
                "bbox": list(sample["bbox"]),
                "province_intersection": province,
                "census_agricultural_region_intersection": car,
                "ecoregion_intersection": ecoregion,
                "runtime_errors": result.get("errors") or [],
                "status": "pass" if not sample_errors else "fail",
                "errors": sample_errors,
            }
        )
    return {
        "schema_version": "open_agronomy_agent.canada_context_boundary_runtime_probe.v1",
        "status": "pass" if not errors else "fail",
        "profile_id": profile_id,
        "pack_root": str(pack_root),
        "network_mode": "offline",
        "sample_count": len(samples),
        "samples": samples,
        "errors": errors,
        "pack_validation": pack_validation,
        "boundary": (
            "This is an offline application-path and geographic-alignment probe. It proves only that the "
            "installed source hierarchy is returned as context at these points, not that a field is within a "
            "legal, agronomic, crop-production, or management boundary."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--profile-manifest", type=Path, default=DEFAULT_PROFILE_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_probe(
        args.pack_root.resolve(),
        profile_id=args.profile,
        profile_manifest_path=args.profile_manifest.resolve(),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
