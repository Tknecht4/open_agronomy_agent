#!/usr/bin/env python3
"""Build compact, provenance-bound Canadian context-boundary SQLite layers.

This builder intentionally handles only small, official vector layers whose
role is geographic orientation and source-routing context.  It does not add a
soil, crop, prescription, yield, or legal-decision layer.  The emitted SQLite
database uses the same ``metadata`` / ``features`` / ``feature_bounds``
contract as the existing offline spatial service, so it can be assembled into
an isolated external-state pack without changing the default DSS profile.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.canada_context_boundary_layer.v1"
OUTPUT_CRS = "EPSG:4326"
COORDINATE_PRECISION_DEGREES = 0.000001


@dataclass(frozen=True)
class ContextBoundarySpec:
    """The tiny allowlist that turns official raw fields into model context."""

    source_id: str
    layer_id: str
    input_kind: str
    expected_source_crs: str
    source_layer: str | None
    code_prefix: str
    code_field: str
    name_field: str
    property_fields: tuple[tuple[str, str], ...]
    dissolve_field: str | None = None


SPECS: dict[str, ContextBoundarySpec] = {
    "ca_statcan_2021_provinces_territories": ContextBoundarySpec(
        source_id="ca_statcan_2021_provinces_territories",
        layer_id="ca_statcan_2021_provinces_territories",
        input_kind="zipped_shapefile",
        expected_source_crs="EPSG:3347",
        source_layer="lpr_000a21a_e.shp",
        code_prefix="PR",
        code_field="PRUID",
        name_field="PRENAME",
        property_fields=(
            ("province_uid", "PRUID"),
            ("province_name", "PRENAME"),
            ("province_abbreviation", "PREABBR"),
            ("dissemination_geography_id", "DGUID"),
        ),
    ),
    "ca_statcan_2021_census_agricultural_regions": ContextBoundarySpec(
        source_id="ca_statcan_2021_census_agricultural_regions",
        layer_id="ca_statcan_2021_census_agricultural_regions",
        input_kind="zipped_shapefile",
        expected_source_crs="EPSG:3347",
        source_layer="lcar000a21a_e.shp",
        code_prefix="CAR",
        code_field="CARUID",
        name_field="CARENAME",
        property_fields=(
            ("census_agricultural_region_code", "CARUID"),
            ("census_agricultural_region", "CARENAME"),
            ("province_uid", "PRUID"),
            ("dissemination_geography_id", "DGUID"),
        ),
    ),
    "ca_aafc_terrestrial_ecoregions_v2_2": ContextBoundarySpec(
        source_id="ca_aafc_terrestrial_ecoregions_v2_2",
        layer_id="ca_aafc_terrestrial_ecoregions_v2_2",
        input_kind="geojson",
        expected_source_crs="EPSG:4326",
        source_layer=None,
        code_prefix="ECOREGION",
        code_field="ECOREGION_ID",
        name_field="ECOREGION_NAME_EN",
        property_fields=(
            ("ecoregion_id", "ECOREGION_ID"),
            ("ecoregion", "ECOREGION_NAME_EN"),
            ("ecozone_id", "ECOZONE_ID"),
            ("ecoprovince_id", "ECOPROVINCE_ID"),
        ),
        dissolve_field="ECOREGION_ID",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _portable_path(path: Path, *, asset_root: Path | None) -> str:
    if asset_root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(asset_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _require_geospatial_stack() -> tuple[Any, Any, Any]:
    try:
        import geopandas as gpd
        import shapely
        from shapely.geometry import mapping
    except ImportError as exc:  # pragma: no cover - environment contract.
        raise RuntimeError(
            "building Canadian context-boundary layers requires geopandas, shapely, and pyproj"
        ) from exc
    return gpd, shapely, mapping


def _clean(value: Any) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value) if value.is_integer() else round(value, 6)
    text = str(value).strip()
    return text or None


def _round_nested(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [_round_nested(item) for item in value]
    if isinstance(value, tuple):
        return [_round_nested(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _round_nested(item) for key, item in value.items()}
    return value


def _feature_geometry(geometry: Any, *, mapping: Any) -> dict[str, Any]:
    payload = _round_nested(mapping(geometry))
    if payload.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("derived context boundary contains a non-polygon geometry")
    return payload


def _archive_members(source: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(source) as archive:
        return [
            {"path": member.filename, "bytes": int(member.file_size)}
            for member in sorted(archive.infolist(), key=lambda item: item.filename)
            if not member.is_dir()
        ]


def _load_frame(*, spec: ContextBoundarySpec, source: Path, gpd: Any) -> tuple[Any, list[dict[str, Any]]]:
    if spec.input_kind == "zipped_shapefile":
        if spec.source_layer is None:
            raise ValueError(f"{spec.source_id} is missing its required source layer")
        members = {row["path"] for row in _archive_members(source)}
        required = {
            spec.source_layer,
            spec.source_layer.replace(".shp", ".shx"),
            spec.source_layer.replace(".shp", ".dbf"),
            spec.source_layer.replace(".shp", ".prj"),
        }
        missing = sorted(required - members)
        if missing:
            raise ValueError(f"{spec.source_id} archive is missing required shapefile members: {missing}")
        return gpd.read_file(f"zip://{source}!{spec.source_layer}"), _archive_members(source)
    if spec.input_kind == "geojson":
        return gpd.read_file(source), []
    raise ValueError(f"unsupported context-boundary input kind: {spec.input_kind}")


def _crs_matches(frame: Any, expected: str) -> bool:
    if frame.crs is None:
        return False
    try:
        return frame.crs.to_epsg() == int(expected.removeprefix("EPSG:"))
    except (AttributeError, TypeError, ValueError):
        return str(frame.crs).upper() == expected.upper()


def _prepared_rows(*, frame: Any, spec: ContextBoundarySpec, shapely: Any, mapping: Any) -> tuple[list[dict[str, Any]], int]:
    missing = {
        spec.code_field,
        spec.name_field,
        *(source_field for _, source_field in spec.property_fields),
    } - set(frame.columns)
    if missing:
        raise ValueError(f"{spec.source_id} source schema is missing required fields: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{spec.source_id} source has no features")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError(f"{spec.source_id} source contains null or empty geometries")
    source_types = set(frame.geometry.geom_type)
    if source_types - {"Polygon", "MultiPolygon"}:
        raise ValueError(f"{spec.source_id} source contains non-polygon geometries: {sorted(source_types)}")
    if not frame.geometry.is_valid.all():
        raise ValueError(f"{spec.source_id} source contains invalid geometry; no automatic repair is allowed")

    source_vertex_count = int(shapely.get_num_coordinates(frame.geometry.array).sum())
    if spec.dissolve_field:
        ordered_groups = sorted(frame.groupby(spec.dissolve_field, sort=True), key=lambda item: str(item[0]))
        raw_rows: list[dict[str, Any]] = []
        for group_value, group in ordered_groups:
            geometry = shapely.union_all(group.geometry.array)
            if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError(f"{spec.source_id} dissolve produced an invalid polygon for {group_value}")
            row = group.iloc[0]
            raw_rows.append({"row": row, "geometry": geometry})
    else:
        raw_rows = [
            {"row": row, "geometry": row.geometry}
            for _, row in frame.sort_values(spec.code_field, kind="mergesort").iterrows()
        ]

    prepared: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for item in raw_rows:
        row = item["row"]
        geometry = item["geometry"]
        code_value = _clean(row.get(spec.code_field))
        name_value = _clean(row.get(spec.name_field))
        if code_value is None or name_value is None:
            raise ValueError(f"{spec.source_id} contains an empty required code or name")
        code = f"{spec.code_prefix}_{code_value}"
        if code in seen_codes:
            raise ValueError(f"{spec.source_id} produced a duplicate output code: {code}")
        seen_codes.add(code)
        properties = {
            output_field: _clean(row.get(source_field))
            for output_field, source_field in spec.property_fields
        }
        properties = {key: value for key, value in properties.items() if value is not None}
        if set(properties) != {key for key, _ in spec.property_fields}:
            raise ValueError(f"{spec.source_id} contains an empty model-visible hierarchy field")
        prepared.append(
            {
                "code": code,
                "name": str(name_value),
                "properties": properties,
                "source_geometry": geometry,
            }
        )
    return prepared, source_vertex_count


def _reproject_prepared_rows(*, prepared: list[dict[str, Any]], source_crs: Any, gpd: Any, shapely: Any, mapping: Any) -> tuple[list[dict[str, Any]], int]:
    """Reproject assembled geometries without borrowing arbitrary source rows."""

    rows: list[dict[str, Any]] = []
    for item in prepared:
        one = gpd.GeoDataFrame({"geometry": [item["source_geometry"]]}, crs=source_crs).to_crs(OUTPUT_CRS)
        geometry = one.geometry.iloc[0]
        if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("reprojection produced an invalid context-boundary geometry")
        rows.append(
            {
                "code": item["code"],
                "name": item["name"],
                "properties": item["properties"],
                "geometry": _feature_geometry(geometry, mapping=mapping),
                "bounds": tuple(float(value) for value in geometry.bounds),
                "vertex_count": int(shapely.get_num_coordinates(geometry)),
            }
        )
    return rows, sum(row["vertex_count"] for row in rows)


def _context_spec(source_id: str) -> ContextBoundarySpec:
    try:
        return SPECS[source_id]
    except KeyError as exc:
        raise ValueError(f"no Canadian context-boundary builder spec is registered for {source_id}") from exc


def build_layer(
    *,
    source_id: str,
    source_entry: dict[str, Any],
    source: Path,
    lineage_path: Path,
    output: Path,
    manifest_path: Path,
    asset_root: Path | None = None,
) -> dict[str, Any]:
    """Derive one exact, local SQLite/RTree context layer from its pinned raw bytes."""

    spec = _context_spec(source_id)
    if source_entry.get("id") != source_id:
        raise ValueError("source registry entry identity does not match the builder request")
    if source_entry.get("runtime", {}).get("layer_id") != spec.layer_id:
        raise ValueError("source registry layer identity does not match the builder specification")
    source = source.resolve()
    lineage_path = lineage_path.resolve()
    output = output.resolve()
    manifest_path = manifest_path.resolve()
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    source_sha256 = _sha256(source)
    if lineage.get("source_id") != source_id or lineage.get("raw_sha256") != source_sha256:
        raise ValueError("raw source identity or SHA256 does not match its lineage record")
    if lineage.get("source_entry_sha256") != _canonical_json_sha256(source_entry):
        raise ValueError("raw lineage source-entry SHA256 does not match the registry entry")

    gpd, shapely, mapping = _require_geospatial_stack()
    frame, archive_members = _load_frame(spec=spec, source=source, gpd=gpd)
    if not _crs_matches(frame, spec.expected_source_crs):
        raise ValueError(f"expected {spec.expected_source_crs}, found {frame.crs}")
    prepared, source_vertex_count = _prepared_rows(
        frame=frame,
        spec=spec,
        shapely=shapely,
        mapping=mapping,
    )
    rows, derived_vertex_count = _reproject_prepared_rows(
        prepared=prepared,
        source_crs=frame.crs,
        gpd=gpd,
        shapely=shapely,
        mapping=mapping,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
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
                properties_zlib BLOB NOT NULL,
                geometry_zlib BLOB NOT NULL,
                min_lon REAL NOT NULL,
                min_lat REAL NOT NULL,
                max_lon REAL NOT NULL,
                max_lat REAL NOT NULL
            );
            CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, min_lon, max_lon, min_lat, max_lat);
            """
        )
        for fid, row in enumerate(rows, start=1):
            min_lon, min_lat, max_lon, max_lat = row["bounds"]
            connection.execute(
                "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fid,
                    row["code"],
                    row["name"],
                    sqlite3.Binary(
                        zlib.compress(json.dumps(row["properties"], sort_keys=True, separators=(",", ":")).encode("utf-8"))
                    ),
                    sqlite3.Binary(
                        zlib.compress(json.dumps(row["geometry"], separators=(",", ":")).encode("utf-8"))
                    ),
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
            "source_id": source_id,
            "source_url": source_entry.get("canonical_url"),
            "source_record_id": source_entry.get("source_record_id"),
            "source_sha256": source_sha256,
            "source_entry_sha256": lineage.get("source_entry_sha256"),
            "source_crs": spec.expected_source_crs,
            "output_crs": OUTPUT_CRS,
            "source_feature_count": int(len(frame)),
            "feature_count": len(rows),
            "source_vertices": source_vertex_count,
            "derived_vertices": derived_vertex_count,
            "coordinate_precision_degrees": COORDINATE_PRECISION_DEGREES,
            "feature_payload_encoding": "zlib_json_v1",
            "archive_members": archive_members,
            "license": lineage.get("license_snapshot"),
            "attribution": lineage.get("license_snapshot", {}).get("attribution"),
            "source_scale_range": source_entry.get("source_scale"),
            "source_scale_note": source_entry.get("boundary"),
            "boundary": source_entry.get("boundary"),
            "model_visible_fields": [key for key, _ in spec.property_fields],
            "distribution_role": "context_only_geographic_organization",
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

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": str(lineage.get("fetched_at") or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()),
        "source_id": source_id,
        "layer_id": spec.layer_id,
        "source_path": _portable_path(source, asset_root=asset_root),
        "source_sha256": source_sha256,
        "source_bytes": source.stat().st_size,
        "source_crs": spec.expected_source_crs,
        "output_crs": OUTPUT_CRS,
        "output_path": _portable_path(output, asset_root=asset_root),
        "output_sha256": _sha256(output),
        "output_bytes": output.stat().st_size,
        "source_feature_count": int(len(frame)),
        "feature_count": len(rows),
        "source_vertices": source_vertex_count,
        "derived_vertices": derived_vertex_count,
        "coordinate_precision_degrees": COORDINATE_PRECISION_DEGREES,
        "archive_members": archive_members,
        "lineage_path": _portable_path(lineage_path, asset_root=asset_root),
        "lineage_sha256": _sha256(lineage_path),
        "source_registry_path": lineage.get("source_registry_path"),
        "source_registry_sha256": lineage.get("source_registry_sha256"),
        "source_entry_sha256": lineage.get("source_entry_sha256"),
        "license_snapshot": lineage.get("license_snapshot"),
        "model_visible_fields": [key for key, _ in spec.property_fields],
        "distribution_boundary": source_entry.get("boundary"),
    }
    _write_json_atomically(manifest_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", choices=sorted(SPECS))
    parser.add_argument("--source-entry", type=Path, required=True, help="JSON file containing one exact source registry entry")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path)
    args = parser.parse_args()
    source_entry = json.loads(args.source_entry.read_text(encoding="utf-8"))
    report = build_layer(
        source_id=args.source_id,
        source_entry=source_entry,
        source=args.source,
        lineage_path=args.lineage,
        output=args.output,
        manifest_path=args.manifest,
        asset_root=args.asset_root,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
