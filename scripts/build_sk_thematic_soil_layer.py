#!/usr/bin/env python3
"""Build the compact Saskatchewan thematic-soil runtime layer."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "ca_sk_thematic_soil_maps"
SOURCE_LAYER = "sk_derived_soil"
SCHEMA_VERSION = "open_agronomy_agent.local_geo_layer.v1"
SOURCE_CRS = "EPSG:3857"
OUTPUT_CRS = "EPSG:4326"
DEFAULT_TOLERANCE_METRES = 60.0
DEFAULT_COORDINATE_PRECISION = 0.00001
SOURCE_URL = "https://open.canada.ca/data/en/dataset/ed36f4f3-2fb9-4241-8e29-6741e8b9e400"

CAPABILITY_DESCRIPTIONS = {
    "1": "no significant limitations for common field crops",
    "2": "moderate limitations or moderate conservation needs",
    "3": "moderately severe limitations or special conservation needs",
    "4": "severe limitations, a narrow crop range, or elevated crop-failure risk",
    "5": "very severe limitations; annual cultivated field crops are generally unsuitable",
    "6": "native perennial forage capability only; improvement is generally impractical",
    "7": "no capability for arable agriculture or permanent pasture",
    "O": "organic soil, improved or unimproved",
}

CLASS_COLORS = {
    "1": "#25896f",
    "2": "#64a35d",
    "3": "#a9b84c",
    "4": "#d8b446",
    "5": "#d9823b",
    "6": "#bd5547",
    "7": "#815b7a",
    "O": "#597f9d",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"none", "nan", "unclassified"} else None


def _properties(row: Any, feature_id: int) -> dict[str, Any]:
    drainage = _clean(row.get("DRAINAGE_CODE"))
    capability = _clean(row.get("AGCAP_CODE"))
    erosion = _clean(row.get("EROSION_CODE"))
    slope = _clean(row.get("SLOPE_CODE"))
    texture = _clean(row.get("TEXTURE_CODE"))
    parts = []
    if capability:
        description = CAPABILITY_DESCRIPTIONS.get(capability)
        parts.append(f"capability class {capability}" + (f" ({description})" if description else ""))
    if drainage:
        parts.append(f"{drainage.lower()} drainage")
    if slope:
        parts.append(f"{slope} slope")
    if erosion:
        parts.append(f"{erosion.lower()} mapped water-erosion risk")
    if texture:
        parts.append(f"{texture.lower()} surface-texture group")
    summary = "Saskatchewan thematic soil: " + ("; ".join(parts) if parts else "unclassified polygon")
    return {
        "feature_id": feature_id,
        "drainage_class": drainage,
        "capability_class": capability,
        "capability_interpretation": CAPABILITY_DESCRIPTIONS.get(capability or ""),
        "erosion_risk": erosion,
        "slope_class": slope,
        "surface_texture_group": texture,
        "soil_summary": summary,
        "style_color": CLASS_COLORS.get(capability or "", "#6f8f70"),
    }


def _require_geo_stack() -> tuple[Any, Any, Any]:
    try:
        import geopandas as gpd
        import shapely
        from shapely.geometry import mapping
    except ImportError as exc:  # pragma: no cover - derivation environment only.
        raise SystemExit(
            "This derivation step requires geopandas, pyogrio, pyproj, and shapely in the build environment."
        ) from exc
    return gpd, shapely, mapping


def _round_nested(value: Any, digits: int) -> Any:
    if isinstance(value, (tuple, list)):
        return [_round_nested(item, digits) for item in value]
    if isinstance(value, float):
        return round(value, digits)
    return value


def _geometry_mapping(geometry: Any, mapping: Any, coordinate_precision: float) -> dict[str, Any]:
    digits = max(0, int(round(-math.log10(coordinate_precision))))
    payload = mapping(geometry)
    return {"type": payload["type"], "coordinates": _round_nested(payload["coordinates"], digits)}


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
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    source_sha256 = _sha256(source)
    if lineage.get("raw_sha256") != source_sha256:
        raise ValueError("raw source SHA256 does not match its lineage record")

    frame = gpd.read_file(source, layer=SOURCE_LAYER)
    if str(frame.crs).upper() != SOURCE_CRS:
        raise ValueError(f"expected {SOURCE_CRS}, found {frame.crs}")
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy().sort_index()
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
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    invalid_derived = int((~frame.geometry.is_valid).sum())
    if invalid_derived:
        raise ValueError(f"derived layer contains {invalid_derived} invalid geometries")
    derived_vertices = int(shapely.get_num_coordinates(frame.geometry.array).sum())

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    capability_counts: Counter[str] = Counter()
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
            properties = _properties(row, fid)
            capability_counts[str(properties.get("capability_class") or "unclassified")] += 1
            geometry = _geometry_mapping(row.geometry, mapping, coordinate_precision)
            min_lon, min_lat, max_lon, max_lat = (float(value) for value in row.geometry.bounds)
            code = f"SK_SOIL_{fid}"
            name = str(properties["soil_summary"])
            connection.execute(
                "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fid,
                    code,
                    name,
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
            "source_registry_path": lineage.get("source_registry_path"),
            "source_registry_sha256": lineage.get("source_registry_sha256"),
            "source_crs": SOURCE_CRS,
            "output_crs": OUTPUT_CRS,
            "feature_count": len(frame),
            "simplification_tolerance_metres": tolerance_metres,
            "coordinate_precision_degrees": coordinate_precision,
            "license": lineage.get("license_snapshot"),
            "attribution": lineage.get("license_snapshot", {}).get("attribution"),
            "source_scale_note": "Revised and condensed from the Saskatchewan Detailed Soils Database; the 2013 specification does not state a display scale for this thematic layer.",
            "boundary": (
                "Dominant generalized thematic values derived from the Saskatchewan Detailed Soils Database. "
                "A polygon can contain variation and does not establish current field condition, an exact soil "
                "component at a point, crop-specific suitability, nutrient status, or a management rate."
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

    generated_at = str(lineage.get("fetched_at") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_id": SOURCE_ID,
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": source_sha256,
        "source_bytes": source.stat().st_size,
        "source_crs": SOURCE_CRS,
        "output_crs": OUTPUT_CRS,
        "output_path": str(output.relative_to(ROOT)),
        "output_sha256": _sha256(output),
        "output_bytes": output.stat().st_size,
        "feature_count": len(frame),
        "capability_counts": dict(sorted(capability_counts.items())),
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
        "distribution_boundary": (
            "Derived OGL-Canada regional soil-map context only; not current field truth, crop-specific "
            "suitability, an exact soil component at a point, nutrient status, or management-rate authority."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data/raw/canada_agronomy/ca_sk_thematic_soil_maps/source.gpkg",
    )
    parser.add_argument(
        "--lineage",
        type=Path,
        default=ROOT / "data/raw/canada_agronomy/ca_sk_thematic_soil_maps/source.gpkg.lineage.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/derived/geo_layers/sk_thematic_soil.sqlite3",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/derived/geo_layers/sk_thematic_soil_manifest.json",
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
