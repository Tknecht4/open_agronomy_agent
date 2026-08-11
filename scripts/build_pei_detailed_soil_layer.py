#!/usr/bin/env python3
"""Build the compact PEI detailed-soil runtime layer.

The source is the OGL-Canada Prince Edward Island Detailed Soil Survey.  The
polygon GeoPackage is joined to the published component, soil-name, and
soil-layer CSV tables before the result is reduced to a context-only local
SQLite/RTree layer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "ca_aafc_pei_detailed_soil_survey"
SOURCE_LAYER = "pe_dtl_75k"
SCHEMA_VERSION = "open_agronomy_agent.local_geo_layer.v1"
SOURCE_CRS = "EPSG:3857"
OUTPUT_CRS = "EPSG:4326"
DEFAULT_TOLERANCE_METRES = 5.0
DEFAULT_COORDINATE_PRECISION = 0.000001
SOURCE_URL = "https://open.canada.ca/data/en/dataset/7fa18ce7-6c14-438a-95c6-bb0906ddfb30"

DRAINAGE = {
    "VR": "very rapidly drained",
    "R": "rapidly drained",
    "W": "well drained",
    "MW": "moderately well drained",
    "I": "imperfectly drained",
    "P": "poorly drained",
    "VP": "very poorly drained",
}
WATER_TABLE = {
    "NO": "not present",
    "YU": "present during an unspecified time",
    "YG": "present during the growing season",
    "YN": "present during the non-growing season",
    "YB": "present during both seasons",
}
MATERIAL_KIND = {
    "M": "mineral soil",
    "N": "non-soil",
    "O": "organic soil",
    "U": "unclassified or incomplete",
}
RESTRICTION = {
    "UN": "undifferentiated restriction",
    "BN": "Solonetzic B horizon",
    "SA": "salinity above 4 dS/m",
    "CT": "compact basal till",
    "OR": "ortstein horizon",
    "FP": "fragipan",
    "LI": "consolidated bedrock",
    "CR": "frozen horizon",
    "DU": "duric horizon",
    "PL": "placic horizon",
}
STONINESS = {
    "0": "nonstony",
    "1": "slightly stony",
    "2": "moderately stony",
    "3": "very stony",
    "4": "exceedingly stony",
    "5": "excessively stony",
}
COMPONENT_COLORS = (
    "#5f8a68",
    "#8ba861",
    "#c3ad59",
    "#b98955",
    "#8e6f63",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text and text not in {"-", "-9", "-9.0"} else None


def _number(value: Any, *, minimum: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or (minimum is not None and number < minimum):
        return None
    return number


def _int_if_whole(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value.is_integer() else round(value, 3)


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


def _surface_layer(layers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not layers:
        return None
    row = min(layers, key=lambda item: _number(item.get("LAYER_NO"), minimum=0) or 999)
    result: dict[str, Any] = {
        "horizon": "".join(
            value
            for value in (
                _clean(row.get("HZN_LIT")),
                _clean(row.get("HZN_MAS")),
                _clean(row.get("HZN_SUF")),
                _clean(row.get("HZN_MOD")),
            )
            if value
        )
        or None,
        "upper_depth_cm": _int_if_whole(_number(row.get("UDEPTH"), minimum=0)),
        "lower_depth_cm": _int_if_whole(_number(row.get("LDEPTH"), minimum=0)),
    }
    measurements = (
        ("sand_percent_by_weight", "TSAND", "TSAND_N"),
        ("silt_percent_by_weight", "TSILT", "TSILT_N"),
        ("clay_percent_by_weight", "TCLAY", "TCLAY_N"),
        ("organic_carbon_percent_by_weight", "ORGCARB", "ORGCARB_N"),
        ("ph_project_method", "PH2", "PH2_N"),
    )
    observation_counts: dict[str, int] = {}
    for label, value_key, count_key in measurements:
        value = _number(row.get(value_key), minimum=0)
        count = _number(row.get(count_key), minimum=0)
        if value is not None and count is not None and count > 0:
            result[label] = _int_if_whole(value)
            observation_counts[label] = int(count)
    if observation_counts:
        result["observation_counts"] = observation_counts
    return {key: value for key, value in result.items() if value not in (None, "", {})} or None


def _component_record(
    row: dict[str, Any],
    *,
    soil_names: dict[str, dict[str, Any]],
    soil_layers: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    soil_type = _clean(row.get("SOILTYPE"))
    name = soil_names.get(soil_type or "", {})
    drainage_code = _clean(name.get("DRAINAGE"))
    water_table_code = _clean(name.get("WATERTBL"))
    material_code = _clean(name.get("KIND"))
    restriction_code = _clean(name.get("RESTR_TYPE"))
    restriction_layer = _clean(name.get("ROOTRESTRI"))
    percent = _int_if_whole(_number(row.get("PERCENT"), minimum=0))
    slope = _int_if_whole(_number(row.get("SLOPE"), minimum=0))
    stoniness_code = _clean(row.get("STONINESS"))
    component = {
        "component": _clean(row.get("CMP")),
        "proportion_percent": percent,
        "soil_type": soil_type,
        "soil_name": _clean(name.get("SOILNAME")),
        "material_kind": MATERIAL_KIND.get(material_code or "", material_code),
        "drainage_class": DRAINAGE.get(drainage_code or "", drainage_code),
        "water_table_presence": WATER_TABLE.get(water_table_code or "", water_table_code),
        "root_restriction_layer": restriction_layer if restriction_layer not in {None, "0"} else None,
        "restriction_type": RESTRICTION.get(restriction_code or "", restriction_code),
        "predominant_slope_percent": slope,
        "surface_stoniness": STONINESS.get(stoniness_code or "", stoniness_code),
        "soil_order_code": _clean(name.get("ORDER_")),
        "great_group_code": _clean(name.get("G_GROUP")),
        "surface_layer": _surface_layer(soil_layers.get(soil_type or "", [])),
    }
    return {key: value for key, value in component.items() if value not in (None, "", [], {})}


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
    return f"PEI detailed soil map unit {map_unit}: " + ("; ".join(parts) if parts else "components unavailable")


def _load_tables(source_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    components_frame = pd.read_csv(source_dir / "pe_dtl_cmp.csv", dtype=str, keep_default_na=False)
    names_frame = pd.read_csv(source_dir / "pe_dtl_snf.csv", dtype=str, keep_default_na=False)
    layers_frame = pd.read_csv(source_dir / "pe_dtl_slf.csv", dtype=str, keep_default_na=False)
    components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in components_frame.to_dict(orient="records"):
        components[str(row["MAPUNIT"]).strip()].append(row)
    for rows in components.values():
        rows.sort(key=lambda row: _number(row.get("PERCENT"), minimum=0) or 0, reverse=True)
    names = {str(row["SOILTYPE"]).strip(): row for row in names_frame.to_dict(orient="records")}
    layers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in layers_frame.to_dict(orient="records"):
        layers[str(row["SOILTYPE"]).strip()].append(row)
    return dict(components), names, dict(layers)


def _verify_support_files(lineage: dict[str, Any], source_dir: Path) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for record in lineage.get("support_files") or []:
        path = ROOT / str(record.get("path") or "")
        if path.parent != source_dir:
            raise ValueError(f"support file is outside the PEI source directory: {path}")
        if not path.is_file():
            raise ValueError(f"support file is missing: {path}")
        actual = _sha256(path)
        if actual != record.get("sha256"):
            raise ValueError(f"support file SHA256 mismatch: {path}")
        verified.append({**record, "bytes": path.stat().st_size, "sha256": actual})
    required_names = {"pe_dtl_75k.csv", "pe_dtl_cmp.csv", "pe_dtl_slf.csv", "pe_dtl_snf.csv"}
    if {Path(str(item["path"])).name for item in verified} != required_names:
        raise ValueError("lineage must identify the four PEI survey CSV tables")
    return verified


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
                "land_area_source_units": _int_if_whole(_number(row.get("LAND_AREA"), minimum=0)),
                "water_area_source_units": _int_if_whole(_number(row.get("WATER_AREA"), minimum=0)),
                "dominant_components": components,
                "soil_summary": _summary(map_unit, components),
                "publication_year": 2013,
                "mapping_basis": "soil information compiled and published over several prior decades",
                "style_color": COMPONENT_COLORS[min(len(components), len(COMPONENT_COLORS)) - 1]
                if components
                else "#7c8b72",
            }
            geometry = _geometry_mapping(row.geometry, mapping, coordinate_precision)
            min_lon, min_lat, max_lon, max_lat = (float(value) for value in row.geometry.bounds)
            code = f"PEI_SOIL_{int(row['SOIL_ID'])}"
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
            "source_scale_range": "1:75,000",
            "source_scale_note": (
                "Published in 2013 for island-wide 1:75,000 representation. "
                "The underlying soil information was compiled over several prior decades."
            ),
            "boundary": (
                "Historical mapped soil-landscape context. A polygon and its listed components are hypotheses, "
                "not proof of the soil at a point or of present nutrient supply, pH, drainage performance, "
                "compaction, erosion, crop suitability, or a management rate."
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
        "distribution_boundary": (
            "Derived OGL-Canada historical soil-map context only; not current field truth, present soil-test "
            "evidence, crop-specific suitability, drainage diagnosis, or management-rate authority."
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
        default=ROOT / "data/raw/canada_agronomy/ca_aafc_pei_detailed_soil_survey/source.gpkg",
    )
    parser.add_argument(
        "--lineage",
        type=Path,
        default=ROOT
        / "data/raw/canada_agronomy/ca_aafc_pei_detailed_soil_survey/source.gpkg.lineage.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/derived/geo_layers/pei_detailed_soil.sqlite3",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/derived/geo_layers/pei_detailed_soil_manifest.json",
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
