#!/usr/bin/env python3
"""Build the compact Pictou County detailed-soil runtime layer.

The OGL-Canada Nova Scotia Detailed Soil Survey covers Pictou County, not the
whole province. The polygon GeoPackage is joined to the published component,
soil-name, and soil-layer CSV tables before being reduced to a context-only
SQLite/RTree layer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from build_pei_detailed_soil_layer import (
    COMPONENT_COLORS,
    DEFAULT_COORDINATE_PRECISION,
    DEFAULT_TOLERANCE_METRES,
    OUTPUT_CRS,
    SCHEMA_VERSION,
    _component_record,
    _geometry_mapping,
    _int_if_whole,
    _number,
    _require_geo_stack,
    _sha256,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "ca_aafc_ns_detailed_soil_survey"
SOURCE_LAYER = "ns_dtl_50k"
SOURCE_CRS = "EPSG:3857"
SOURCE_URL = "https://open.canada.ca/data/en/dataset/083534ca-d5b0-46f5-b540-f3a706dbc2de"
SOURCE_SCALE = "1:50,000"


def _load_tables(
    source_dir: Path,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    components_frame = pd.read_csv(source_dir / "ns_dtl_cmp.csv", dtype=str, keep_default_na=False)
    names_frame = pd.read_csv(source_dir / "ns_dtl_snf.csv", dtype=str, keep_default_na=False)
    layers_frame = pd.read_csv(source_dir / "ns_dtl_slf.csv", dtype=str, keep_default_na=False)
    components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in components_frame.to_dict(orient="records"):
        components[str(row["MAPUNIT"]).strip()].append(row)
    for rows in components.values():
        rows.sort(key=lambda row: _number(row.get("PERCENT"), minimum=0) or 0, reverse=True)
    names = {
        str(row["SOIL_TYPE"]).strip(): row
        for row in names_frame.to_dict(orient="records")
    }
    layers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in layers_frame.to_dict(orient="records"):
        layers[str(row["SOILTYPE"]).strip()].append(row)
    return dict(components), names, dict(layers)


def _verify_support_files(lineage: dict[str, Any], source_dir: Path) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for record in lineage.get("support_files") or []:
        path = ROOT / str(record.get("path") or "")
        if path.parent != source_dir:
            raise ValueError(f"support file is outside the Nova Scotia source directory: {path}")
        if not path.is_file():
            raise ValueError(f"support file is missing: {path}")
        actual = _sha256(path)
        if actual != record.get("sha256"):
            raise ValueError(f"support file SHA256 mismatch: {path}")
        verified.append({**record, "bytes": path.stat().st_size, "sha256": actual})
    required_names = {"ns_dtl_50k.csv", "ns_dtl_cmp.csv", "ns_dtl_slf.csv", "ns_dtl_snf.csv"}
    if {Path(str(item["path"])).name for item in verified} != required_names:
        raise ValueError("lineage must identify the four Nova Scotia survey CSV tables")
    return verified


def _summary(map_unit: str, components: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for component in components[:3]:
        name = str(component.get("soil_name") or component.get("soil_type") or "unnamed component")
        details = [
            str(value)
            for value in (
                component.get("drainage_class"),
                f"{component['predominant_slope_percent']}% mapped slope"
                if component.get("predominant_slope_percent") is not None
                else None,
            )
            if value
        ]
        prefix = (
            f"{component['proportion_percent']}% "
            if component.get("proportion_percent") is not None
            else ""
        )
        parts.append(prefix + name + (f" ({', '.join(details)})" if details else ""))
    component_text = "; ".join(parts) if parts else "components unavailable"
    return f"Pictou County detailed soil map unit {map_unit}: {component_text}"


def build_layer(
    *,
    source: Path,
    lineage_path: Path,
    output: Path,
    manifest_path: Path,
    tolerance_metres: float,
    coordinate_precision: float,
) -> dict[str, Any]:
    gpd, shapely, mapping = _require_geo_stack()
    source = source.resolve()
    source_dir = source.parent
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    source_sha256 = _sha256(source)
    if lineage.get("raw_sha256") != source_sha256:
        raise ValueError("raw source SHA256 does not match its lineage record")
    support_files = _verify_support_files(lineage, source_dir)

    frame = gpd.read_file(source, layer=SOURCE_LAYER)
    if str(frame.crs).upper() != SOURCE_CRS:
        raise ValueError(f"expected {SOURCE_CRS}, found {frame.crs}")
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy().sort_values("SOIL_ID")
    if set(frame.geometry.geom_type) - {"Polygon", "MultiPolygon"}:
        raise ValueError("source layer contains non-polygon geometry")
    invalid_source = int((~frame.geometry.is_valid).sum())
    if invalid_source:
        raise ValueError(f"source layer contains {invalid_source} invalid geometries")

    source_vertices = int(shapely.get_num_coordinates(frame.geometry.array).sum())
    source_area = float(frame.geometry.area.sum())
    simplified = frame.geometry.simplify(tolerance_metres, preserve_topology=True)
    simplified_area = float(simplified.area.sum())
    frame = frame.set_geometry(simplified).to_crs(OUTPUT_CRS)
    invalid_derived = int((~frame.geometry.is_valid).sum())
    if invalid_derived:
        raise ValueError(f"derived layer contains {invalid_derived} invalid geometries")
    derived_vertices = int(shapely.get_num_coordinates(frame.geometry.array).sum())
    components_by_map_unit, soil_names, soil_layers = _load_tables(source_dir)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    drainage_counts: Counter[str] = Counter()
    map_units_without_components = 0
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE TABLE features (
                fid INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                properties_json TEXT NOT NULL,
                geometry_json TEXT NOT NULL,
                min_lon REAL NOT NULL,
                min_lat REAL NOT NULL,
                max_lon REAL NOT NULL,
                max_lat REAL NOT NULL
            );
            CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, min_lon, max_lon, min_lat, max_lat);
            """
        )
        for fid, (_, row) in enumerate(frame.iterrows(), start=1):
            map_unit = str(row.get("MAPUNIT") or "").strip()
            component_rows = components_by_map_unit.get(map_unit, [])
            if not component_rows:
                map_units_without_components += 1
            components = [
                _component_record(record, soil_names=soil_names, soil_layers=soil_layers)
                for record in component_rows
            ]
            for component in components:
                drainage_counts[str(component.get("drainage_class") or "unclassified")] += 1
            properties = {
                "feature_id": fid,
                "map_unit": map_unit,
                "dominant_components": components,
                "soil_summary": _summary(map_unit, components),
                "publication_year": 2013,
                "mapping_basis": "Version 1 detailed survey for Pictou County",
                "coverage_area": "Pictou County only",
                "style_color": (
                    COMPONENT_COLORS[min(len(components), len(COMPONENT_COLORS)) - 1]
                    if components
                    else "#7b887a"
                ),
            }
            geometry = _geometry_mapping(row.geometry, mapping, coordinate_precision)
            min_lon, min_lat, max_lon, max_lat = (float(value) for value in row.geometry.bounds)
            code = f"NS_PICTOU_SOIL_{int(row['SOIL_ID'])}"
            connection.execute(
                "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fid,
                    code,
                    str(properties["soil_summary"]),
                    json.dumps(properties, sort_keys=True, separators=(",", ":")),
                    json.dumps(geometry, separators=(",", ":")),
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                ),
            )
            connection.execute(
                "INSERT INTO feature_bounds VALUES (?, ?, ?, ?, ?)",
                (fid, min_lon, max_lon, min_lat, max_lat),
            )

        metadata = {
            "schema_version": SCHEMA_VERSION,
            "source_id": SOURCE_ID,
            "source_url": SOURCE_URL,
            "source_record_id": lineage.get("source_record_id"),
            "source_sha256": source_sha256,
            "support_files": support_files,
            "source_registry_path": lineage.get("source_registry_path"),
            "source_registry_sha256": lineage.get("source_registry_sha256"),
            "source_crs": SOURCE_CRS,
            "output_crs": OUTPUT_CRS,
            "feature_count": len(frame),
            "simplification_tolerance_metres": tolerance_metres,
            "coordinate_precision_degrees": coordinate_precision,
            "license": lineage.get("license_snapshot"),
            "attribution": lineage.get("license_snapshot", {}).get("attribution"),
            "source_scale_range": SOURCE_SCALE,
            "source_scale_note": (
                "Historical Version 1 detailed soil survey at 1:50,000 for Pictou County only; "
                "published in 2013 and marked completed with no planned updates."
            ),
            "boundary": (
                "Historical mapped soil-landscape context for Pictou County only, not province-wide "
                "Nova Scotia coverage or proof of current field condition, nutrient supply, pH, "
                "drainage performance, crop suitability, or a management rate."
            ),
        }
        for key, value in sorted(metadata.items()):
            connection.execute(
                "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
                (key, json.dumps(value, sort_keys=True, separators=(",", ":"))),
            )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    os.replace(temporary, output)

    generated_at = str(
        lineage.get("fetched_at")
        or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_id": SOURCE_ID,
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": source_sha256,
        "source_bytes": source.stat().st_size,
        "support_files": support_files,
        "source_crs": SOURCE_CRS,
        "output_crs": OUTPUT_CRS,
        "output_path": str(output.relative_to(ROOT)),
        "output_sha256": _sha256(output),
        "output_bytes": output.stat().st_size,
        "feature_count": len(frame),
        "map_units_without_components": map_units_without_components,
        "drainage_component_counts": dict(sorted(drainage_counts.items())),
        "source_vertices": source_vertices,
        "derived_vertices": derived_vertices,
        "vertex_reduction_fraction": round(1 - (derived_vertices / source_vertices), 6),
        "source_invalid_geometries": invalid_source,
        "derived_invalid_geometries": invalid_derived,
        "area_change_fraction": round(abs(simplified_area - source_area) / source_area, 8),
        "simplification_tolerance_metres": tolerance_metres,
        "coordinate_precision_degrees": coordinate_precision,
        "lineage_path": str(lineage_path.relative_to(ROOT)),
        "lineage_sha256": _sha256(lineage_path),
        "source_registry_path": lineage.get("source_registry_path"),
        "source_registry_sha256": lineage.get("source_registry_sha256"),
        "license_snapshot": lineage.get("license_snapshot"),
        "coverage_area": "Pictou County only",
        "distribution_boundary": (
            "Derived OGL-Canada historical soil-map context for Pictou County only; not "
            "province-wide coverage, current field truth, present soil-test evidence, "
            "crop-specific suitability, drainage diagnosis, or management-rate authority."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data/raw/canada_agronomy/ca_aafc_ns_detailed_soil_survey/source.gpkg",
    )
    parser.add_argument(
        "--lineage",
        type=Path,
        default=ROOT
        / "data/raw/canada_agronomy/ca_aafc_ns_detailed_soil_survey/source.gpkg.lineage.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/derived/geo_layers/ns_pictou_detailed_soil.sqlite3",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/derived/geo_layers/ns_pictou_detailed_soil_manifest.json",
    )
    parser.add_argument("--tolerance-metres", type=float, default=DEFAULT_TOLERANCE_METRES)
    parser.add_argument("--coordinate-precision", type=float, default=DEFAULT_COORDINATE_PRECISION)
    args = parser.parse_args()
    if args.tolerance_metres <= 0 or args.coordinate_precision <= 0:
        parser.error("tolerance and coordinate precision must be positive")
    report = build_layer(
        source=args.source,
        lineage_path=args.lineage,
        output=args.output,
        manifest_path=args.manifest,
        tolerance_metres=args.tolerance_metres,
        coordinate_precision=args.coordinate_precision,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
