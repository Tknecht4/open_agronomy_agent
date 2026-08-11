#!/usr/bin/env python3
"""Build compact Alberta or Manitoba detailed-soil runtime layers.

The two AAFC products share a spatial-plus-relational publication pattern but
not one relational schema. Province profiles below make those differences
explicit. The output is a WGS84 SQLite/RTree context layer for offline field
intersection; it is deliberately not a fertility or prescription product.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import struct
import zlib
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.local_geo_layer.v1"
OUTPUT_CRS = "EPSG:4326"
DEFAULT_TOLERANCE_METRES = 10.0
DEFAULT_COORDINATE_PRECISION = 0.000001

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
COMPONENT_COLORS = ("#5f8a68", "#8ba861", "#c3ad59", "#b98955", "#8e6f63")


@dataclass(frozen=True)
class ProvinceProfile:
    province: str
    source_id: str
    source_dir: str
    source_layer: str
    source_crs: str
    source_url: str
    source_record_id: str
    polygon_id: str
    map_unit_field: str | None
    component_file: str
    component_join_field: str
    component_soil_field: str
    component_slope_field: str
    name_file: str
    name_soil_field: str
    layer_file: str
    layer_soil_field: str
    polygon_table_file: str
    extra_table_file: str | None
    component_detail_file: str | None
    output_file: str
    output_manifest: str
    code_prefix: str
    summary_prefix: str
    source_scale_range: str
    source_scale_note: str
    mapping_basis: str
    color: str


PROFILES = {
    "ab": ProvinceProfile(
        province="Alberta",
        source_id="ca_aafc_ab_detailed_soil_survey",
        source_dir="data/raw/canada_agronomy/ca_aafc_ab_detailed_soil_survey_dss_v3",
        source_layer="dss_v3_ab.shp",
        source_crs="EPSG:3400",
        source_url="https://open.canada.ca/data/en/dataset/9150ad66-73f7-444f-a67c-4be5cf676453",
        source_record_id="9150ad66-73f7-444f-a67c-4be5cf676453",
        polygon_id="POLY_ID",
        map_unit_field=None,
        component_file="dss_v3_ab_cmp.dbf",
        component_join_field="POLY_ID",
        component_soil_field="SOIL_ID",
        component_slope_field="SLOPE_P",
        name_file="soil_name_ab_v2.dbf",
        name_soil_field="SOIL_ID",
        layer_file="soil_layer_ab_v2.dbf",
        layer_soil_field="SOIL_ID",
        polygon_table_file="dss_v3_ab.dbf",
        extra_table_file="dss_v3_ab_prt.dbf",
        component_detail_file="dss_v3_ab_crt.dbf",
        output_file="data/derived/geo_layers/ab_detailed_soil.sqlite3",
        output_manifest="data/derived/geo_layers/ab_detailed_soil_manifest.json",
        code_prefix="AB_SOIL",
        summary_prefix="Alberta detailed soil map unit",
        source_scale_range="1:100,000",
        source_scale_note=(
            "AGRASID 3.0 agricultural-region mapping intended for 1:100,000 representation. "
            "The soil survey is a mapped prior and its attributes are not current field measurements."
        ),
        mapping_basis="AGRASID 3.0 agricultural-region detailed soil survey",
        color="#7d876e",
    ),
    "mb": ProvinceProfile(
        province="Manitoba",
        source_id="ca_aafc_mb_detailed_soil_survey",
        source_dir="data/raw/canada_agronomy/ca_aafc_mb_detailed_soil_survey_dss_v3",
        source_layer="dss_v3_mb.shp",
        source_crs="EPSG:26914",
        source_url="https://open.canada.ca/data/en/dataset/741a06a2-718f-4da9-9adf-6e95c8c37f3d",
        source_record_id="741a06a2-718f-4da9-9adf-6e95c8c37f3d",
        polygon_id="POLY_ID",
        map_unit_field=None,
        component_file="dss_v3_mb_cmp.dbf",
        component_join_field="POLY_ID",
        component_soil_field="SOIL_ID",
        component_slope_field="SLOPE_P",
        name_file="soil_name_mb_v2.dbf",
        name_soil_field="SOIL_ID",
        layer_file="soil_layer_mb_v2.dbf",
        layer_soil_field="SOIL_ID",
        polygon_table_file="dss_v3_mb.dbf",
        extra_table_file="dss_v3_mb_prt.dbf",
        component_detail_file="dss_v3_mb_crt.dbf",
        output_file="data/derived/geo_layers/mb_detailed_soil.sqlite3",
        output_manifest="data/derived/geo_layers/mb_detailed_soil_manifest.json",
        code_prefix="MB_SOIL",
        summary_prefix="Manitoba detailed soil map unit",
        source_scale_range="multiple published scales from 1:20,000 to 1:126,720",
        source_scale_note=(
            "Provincial detailed-soil compilation assembled from surveys at multiple published "
            "scales. Coverage is concentrated in southern agricultural Manitoba with additional "
            "mapped areas; consult the source metadata because the survey is a historical mapped "
            "prior, not a current field measurement."
        ),
        mapping_basis="Manitoba detailed soil surveys compiled across published map sheets and scales",
        color="#7d8875",
    ),
}


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
    return text if text and text not in {"-", "-9", "-9.0", "~~~~~", "xxxx"} else None


def _number(value: Any, *, minimum: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number == -9 or (minimum is not None and number < minimum):
        return None
    return number


def _int_if_whole(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value.is_integer() else round(value, 3)


def _normalized_salinity_label(value: Any) -> tuple[str | None, str | None]:
    raw = _clean(value)
    if raw == "Non Salline":
        return "Non Saline", raw
    return raw, None


def _require_geo_stack() -> tuple[Any, Any, Any]:
    try:
        import geopandas as gpd
        import shapely
        from shapely.geometry import mapping
    except ImportError as exc:  # pragma: no cover - derivation environment only.
        raise SystemExit("This derivation requires geopandas, pyogrio, pyproj, and shapely.") from exc
    return gpd, shapely, mapping


def _round_nested(value: Any, digits: int) -> Any:
    if isinstance(value, (tuple, list)):
        return [_round_nested(item, digits) for item in value]
    return round(value, digits) if isinstance(value, float) else value


def _geometry_mapping(geometry: Any, mapping: Any, coordinate_precision: float) -> dict[str, Any]:
    digits = max(0, int(round(-math.log10(coordinate_precision))))
    payload = mapping(geometry)
    return {"type": payload["type"], "coordinates": _round_nested(payload["coordinates"], digits)}


def _surface_layer(layers: list[dict[str, Any]], *, values_without_counts: bool) -> dict[str, Any] | None:
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
        "upper_depth_cm": _int_if_whole(_number(row.get("UDEPTH"))),
        "lower_depth_cm": _int_if_whole(_number(row.get("LDEPTH"))),
    }
    measurements = (
        ("sand_percent_by_weight", "TSAND", "TSAND_N"),
        ("silt_percent_by_weight", "TSILT", "TSILT_N"),
        ("clay_percent_by_weight", "TCLAY", "TCLAY_N"),
        ("organic_carbon_percent_by_weight", "ORGCARB", "ORGCARB_N"),
        ("ph_cacl2", "PHCA", "PHCA_N"),
        ("ph_project_method", "PH2", "PH2_N"),
        ("cec", "CEC", "CEC_N"),
        ("bulk_density", "BD", "BD_N"),
        ("electrical_conductivity", "EC", "EC_N"),
    )
    counts: dict[str, int] = {}
    for label, value_key, count_key in measurements:
        value = _number(row.get(value_key), minimum=0)
        count = _number(row.get(count_key), minimum=0)
        if value is None:
            continue
        if values_without_counts or (count is not None and count > 0):
            result[label] = _int_if_whole(value)
            if count is not None and count > 0:
                counts[label] = int(count)
    if counts:
        result["observation_counts"] = counts
    elif values_without_counts and any(key in result for key, _, _ in measurements):
        result["measurement_basis"] = "published representative profile value; observation count not supplied"
    return {key: value for key, value in result.items() if value not in (None, "", {})} or None


def _read_archive_table(
    source: Path, member: str, *, columns: tuple[str, ...] | None = None
) -> pd.DataFrame:
    try:
        import pyogrio
    except ImportError as exc:  # pragma: no cover - derivation environment only.
        raise SystemExit("This derivation requires pyogrio for DSS DBF tables.") from exc
    path = f"/vsizip/{source}/{member}"
    selected = None
    if columns is not None:
        available = set(pyogrio.read_info(path)["fields"])
        selected = [column for column in columns if column in available]
    return pyogrio.read_dataframe(path, read_geometry=False, columns=selected)


def _read_dbf_archive_table(
    source: Path, member: str, *, columns: tuple[str, ...]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read selected DBF fields and repair one proven UTF-8 fixed-width defect.

    The Manitoba 2016 PRT contains one UTF-8 non-breaking space encoded as two
    bytes inside a one-byte dBASE field. That shifts all later fixed-width
    records. The repair is accepted only for the exact one-byte size surplus
    and exactly one C2-A0 sequence; every row key is validated downstream.
    """

    with zipfile.ZipFile(source) as archive:
        raw = archive.read(member)
    record_count = struct.unpack("<I", raw[4:8])[0]
    header_length = struct.unpack("<H", raw[8:10])[0]
    record_length = struct.unpack("<H", raw[10:12])[0]
    expected_bytes = header_length + record_count * record_length + 1
    repair = {
        "member": member,
        "original_bytes": len(raw),
        "normalized_bytes": len(raw),
        "utf8_nbsp_fixed_width_repairs": 0,
        "repair_offset": None,
    }
    if len(raw) != expected_bytes:
        marker = b"\xc2\xa0"
        if len(raw) != expected_bytes + 1 or raw.count(marker) != 1:
            raise ValueError(
                f"unsupported DBF record-size anomaly in {member}: {len(raw)} vs {expected_bytes}"
            )
        offset = raw.index(marker)
        raw = raw[:offset] + b" " + raw[offset + 2 :]
        repair.update(
            {
                "normalized_bytes": len(raw),
                "utf8_nbsp_fixed_width_repairs": 1,
                "repair_offset": offset,
            }
        )
    if len(raw) != expected_bytes or raw[-1:] != b"\x1a":
        raise ValueError(f"normalized DBF size or terminator is invalid for {member}")

    fields: list[tuple[str, int, int]] = []
    position = 32
    field_offset = 1
    while raw[position] != 0x0D:
        descriptor = raw[position : position + 32]
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
        width = int(descriptor[16])
        fields.append((name, field_offset, width))
        field_offset += width
        position += 32
    selected_fields = [field for field in fields if field[0] in columns]
    missing_required = {"POLY_ID", "MAPUNIT"} - {field[0] for field in selected_fields}
    if missing_required:
        raise ValueError(f"DBF is missing required fields: {sorted(missing_required)}")
    records: list[dict[str, str]] = []
    for index in range(record_count):
        start = header_length + index * record_length
        record = raw[start : start + record_length]
        if record[:1] == b"*":
            continue
        records.append(
            {
                name: record[offset : offset + width].decode("latin-1").strip()
                for name, offset, width in selected_fields
            }
        )
    return pd.DataFrame.from_records(records, columns=list(columns)), repair


def _load_tables(profile: ProvinceProfile, source: Path, polygon_ids: list[str]) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    components_frame = _read_archive_table(
        source,
        profile.component_file,
        columns=(
            profile.component_join_field,
            "CMP",
            "PERCENT",
            profile.component_slope_field,
            "SLOPE_LEN",
            "STONINESS",
            profile.component_soil_field,
            "CMP_ID",
        ),
    )
    names_frame = _read_archive_table(
        source,
        profile.name_file,
        columns=(
            profile.name_soil_field,
            "SOILNAME",
            "KIND",
            "WATERTBL",
            "ROOTRESTRI",
            "RESTR_TYPE",
            "DRAINAGE",
            "ORDER2",
            "G_GROUP2",
            "ORDER3",
            "G_GROUP3",
        ),
    )
    layers_frame = _read_archive_table(
        source,
        profile.layer_file,
        columns=(
            profile.layer_soil_field,
            "LAYER_NO",
            "UDEPTH",
            "LDEPTH",
            "HZN_LIT",
            "HZN_MAS",
            "HZN_SUF",
            "HZN_MOD",
            "TSAND",
            "TSILT",
            "TCLAY",
            "ORGCARB",
            "PHCA",
            "PH2",
            "CEC",
            "BD",
            "EC",
        ),
    )
    components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in components_frame.to_dict(orient="records"):
        components[str(row[profile.component_join_field]).strip()].append(row)
    for rows in components.values():
        rows.sort(key=lambda row: _number(row.get("PERCENT"), minimum=0) or 0, reverse=True)
    names = {
        str(row[profile.name_soil_field]).strip(): row for row in names_frame.to_dict(orient="records")
    }
    layers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in layers_frame.to_dict(orient="records"):
        layers[str(row[profile.layer_soil_field]).strip()].append(row)
    extras: dict[str, dict[str, Any]] = {}
    table_repairs: dict[str, Any] = {"prt_shift_repaired_rows": 0, "prt_mismatched_rows": 0}
    if profile.extra_table_file:
        extra_columns = (
            profile.polygon_id,
            "MAPUNIT",
            "SLC_V3R2",
            "MAP_NAME",
            "OLD_POLY_ID",
            "SLOPE",
            "SALINITY",
            "DRAINAGE",
            "SURFTEXT",
            "ERPOLY",
            "MANAGEMENT",
            "AGRI_CAP",
        )
        extra_frame, dbf_repair = _read_dbf_archive_table(
            source,
            profile.extra_table_file,
            columns=extra_columns,
        )
        table_repairs["dbf_fixed_width_repair"] = dbf_repair
        extra_records = extra_frame.to_dict(orient="records")
        if len(extra_records) != len(polygon_ids):
            raise ValueError(
                f"PRT row count {len(extra_records)} does not match polygon count {len(polygon_ids)}"
            )
        for expected_id, row in zip(polygon_ids, extra_records, strict=True):
            actual_id = str(row[profile.polygon_id]).strip()
            map_unit = str(row.get("MAPUNIT") or "")
            if actual_id == expected_id:
                pass
            elif (
                len(expected_id) == len(actual_id) + 1
                and expected_id.startswith(actual_id)
                and map_unit.startswith(expected_id[-1])
            ):
                row[profile.polygon_id] = expected_id
                row["MAPUNIT"] = map_unit[1:]
                table_repairs["prt_shift_repaired_rows"] += 1
            else:
                table_repairs["prt_mismatched_rows"] += 1
                raise ValueError(
                    f"PRT row cannot be reconciled to polygon {expected_id}: {actual_id!r}, {map_unit!r}"
                )
            extras[expected_id] = row
    component_details: dict[str, dict[str, Any]] = {}
    if profile.component_detail_file:
        detail_frame = _read_archive_table(
            source,
            profile.component_detail_file,
            columns=("CMP_ID", "LFPOS", "SLOPE_80", "EROSION", "SALINITY"),
        )
        component_details = {
            str(row["CMP_ID"]).strip(): row for row in detail_frame.to_dict(orient="records")
        }
    return dict(components), names, dict(layers), extras, component_details, table_repairs


def _component_record(
    row: dict[str, Any],
    *,
    profile: ProvinceProfile,
    soil_names: dict[str, dict[str, Any]],
    soil_layers: dict[str, list[dict[str, Any]]],
    component_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    soil_key = str(row.get(profile.component_soil_field) or "").strip()
    name = soil_names.get(soil_key, {})
    detail = component_details.get(str(row.get("CMP_ID") or "").strip(), {})
    drainage_code = _clean(name.get("DRAINAGE"))
    water_table_code = _clean(name.get("WATERTBL"))
    material_code = _clean(name.get("KIND"))
    restriction_code = _clean(name.get("RESTR_TYPE"))
    restriction_layer = _clean(name.get("ROOTRESTRI"))
    order_code = _clean(name.get("ORDER3")) or _clean(name.get("ORDER_")) or _clean(name.get("ORDER2"))
    great_group = _clean(name.get("G_GROUP3")) or _clean(name.get("G_GROUP")) or _clean(name.get("G_GROUP2"))
    component = {
        "component": _clean(row.get("CMP")),
        "proportion_percent": _int_if_whole(_number(row.get("PERCENT"), minimum=0)),
        "soil_type": soil_key or None,
        "soil_name": _clean(name.get("SOILNAME")),
        "material_kind": MATERIAL_KIND.get(material_code or "", material_code),
        "drainage_class": DRAINAGE.get(drainage_code or "", drainage_code),
        "water_table_presence": WATER_TABLE.get(water_table_code or "", water_table_code),
        "root_restriction_layer": restriction_layer if restriction_layer not in {None, "0"} else None,
        "restriction_type": RESTRICTION.get(restriction_code or "", restriction_code),
        "predominant_slope_percent": _int_if_whole(
            _number(row.get(profile.component_slope_field), minimum=0)
        ),
        "slope_length_metres": _int_if_whole(_number(row.get("SLOPE_LEN"), minimum=0)),
        "landform_position_code": _clean(detail.get("LFPOS")),
        "slope_80th_percentile": _int_if_whole(_number(detail.get("SLOPE_80"), minimum=0)),
        "mapped_erosion_code": _clean(detail.get("EROSION")),
        "mapped_salinity_code": _clean(detail.get("SALINITY")),
        "surface_stoniness": STONINESS.get(_clean(row.get("STONINESS")) or "", _clean(row.get("STONINESS"))),
        "soil_order_code": order_code,
        "great_group_code": great_group,
        "surface_layer": _surface_layer(
            soil_layers.get(soil_key, []), values_without_counts=True
        ),
    }
    return {key: value for key, value in component.items() if value not in (None, "", [], {})}


def _summary(profile: ProvinceProfile, map_unit: str, components: list[dict[str, Any]]) -> str:
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
        prefix = f"{component['proportion_percent']}% " if component.get("proportion_percent") is not None else ""
        parts.append(prefix + name + (f" ({', '.join(details)})" if details else ""))
    return f"{profile.summary_prefix} {map_unit}: " + ("; ".join(parts) if parts else "components unavailable")


def _verify_archive(source: Path, profile: ProvinceProfile) -> list[dict[str, Any]]:
    required = {
        profile.source_layer,
        profile.source_layer.replace(".shp", ".shx"),
        profile.source_layer.replace(".shp", ".dbf"),
        profile.source_layer.replace(".shp", ".prj"),
        profile.component_file,
        profile.name_file,
        profile.layer_file,
    }
    if profile.extra_table_file:
        required.add(profile.extra_table_file)
    if profile.component_detail_file:
        required.add(profile.component_detail_file)
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        names = {item.filename for item in members}
        unsafe = [name for name in names if Path(name).is_absolute() or ".." in Path(name).parts]
        if unsafe:
            raise ValueError(f"DSS archive contains unsafe member paths: {unsafe}")
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"DSS archive is missing required members: {missing}")
        return [
            {"name": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}"}
            for item in sorted(members, key=lambda value: value.filename)
        ]


def build_layer(
    *,
    profile: ProvinceProfile,
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
    if lineage.get("source_id") != profile.source_id or lineage.get("raw_sha256") != source_sha256:
        raise ValueError("raw source identity or SHA256 does not match its lineage record")
    support_files = lineage.get("support_files") or []
    archive_members = _verify_archive(source, profile)

    frame = gpd.read_file(f"zip://{source}!{profile.source_layer}")
    if str(frame.crs).upper() != profile.source_crs:
        raise ValueError(f"expected {profile.source_crs}, found {frame.crs}")
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy().sort_values(profile.polygon_id)
    if set(frame.geometry.geom_type) - {"Polygon", "MultiPolygon"}:
        raise ValueError("source layer contains non-polygon geometry")
    invalid_source_mask = ~frame.geometry.is_valid
    invalid_source = int(invalid_source_mask.sum())
    source_repaired_feature_ids: list[str] = []
    source_repair_area_before = 0.0
    source_repair_area_delta = 0.0
    if invalid_source:
        for index in frame.index[invalid_source_mask]:
            original = frame.at[index, "geometry"]
            repaired = shapely.make_valid(original)
            if repaired.geom_type not in {"Polygon", "MultiPolygon"} or not repaired.is_valid:
                raise ValueError(
                    f"source repair did not yield a valid polygon for {frame.at[index, profile.polygon_id]}"
                )
            original_area = float(original.area)
            source_repair_area_before += original_area
            source_repair_area_delta += abs(float(repaired.area) - original_area)
            frame.at[index, "geometry"] = repaired
            source_repaired_feature_ids.append(str(frame.at[index, profile.polygon_id]))
    source_repair_area_change_fraction = (
        source_repair_area_delta / source_repair_area_before if source_repair_area_before else 0.0
    )
    if source_repair_area_change_fraction > 0.000001 or int((~frame.geometry.is_valid).sum()):
        raise ValueError("source geometry repair exceeded the one-part-per-million area boundary")

    source_vertices = int(shapely.get_num_coordinates(frame.geometry.array).sum())
    source_area = float(frame.geometry.area.sum())
    simplified = frame.geometry.simplify(tolerance_metres, preserve_topology=True)
    simplified_area = float(simplified.area.sum())
    frame = frame.set_geometry(simplified).to_crs(OUTPUT_CRS)
    invalid_after_reprojection = ~frame.geometry.is_valid
    repaired_feature_ids: list[str] = []
    repair_area_before = 0.0
    repair_area_delta = 0.0
    if invalid_after_reprojection.any():
        for index in frame.index[invalid_after_reprojection]:
            original = frame.at[index, "geometry"]
            repaired = shapely.make_valid(original)
            if repaired.geom_type not in {"Polygon", "MultiPolygon"} or not repaired.is_valid:
                raise ValueError(
                    f"reprojection repair did not yield a valid polygon for {frame.at[index, profile.polygon_id]}"
                )
            original_area = float(original.area)
            repair_area_before += original_area
            repair_area_delta += abs(float(repaired.area) - original_area)
            frame.at[index, "geometry"] = repaired
            repaired_feature_ids.append(str(frame.at[index, profile.polygon_id]))
    reprojection_repair_area_change_fraction = (
        repair_area_delta / repair_area_before if repair_area_before else 0.0
    )
    if reprojection_repair_area_change_fraction > 0.000001:
        raise ValueError(
            "reprojection geometry repair changed affected-feature area by more than one part per million"
        )
    invalid_derived = int((~frame.geometry.is_valid).sum())
    if invalid_derived:
        raise ValueError(f"derived layer contains {invalid_derived} invalid geometries after repair")
    derived_vertices = int(shapely.get_num_coordinates(frame.geometry.array).sum())
    (
        components_by_unit,
        soil_names,
        soil_layers,
        extra_rows,
        component_details,
        table_repairs,
    ) = _load_tables(
        profile,
        source,
        [str(value).strip() for value in frame[profile.polygon_id].tolist()],
    )

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
        for fid, (_, row) in enumerate(frame.iterrows(), start=1):
            polygon_id = str(row.get(profile.polygon_id) or "").strip()
            extra = extra_rows.get(polygon_id, {})
            map_unit = (
                str(row.get(profile.map_unit_field) or "").strip()
                if profile.map_unit_field
                else str(extra.get("MAPUNIT") or polygon_id).strip()
            )
            join_key = polygon_id if profile.component_join_field == profile.polygon_id else map_unit
            component_rows = components_by_unit.get(join_key, [])
            if not component_rows:
                map_units_without_components += 1
            components = [
                _component_record(
                    record,
                    profile=profile,
                    soil_names=soil_names,
                    soil_layers=soil_layers,
                    component_details=component_details,
                )
                for record in component_rows
            ]
            for component in components:
                drainage_counts[str(component.get("drainage_class") or "unclassified")] += 1
            salinity_class, salinity_source_value = _normalized_salinity_label(extra.get("SALINITY"))
            properties = {
                "feature_id": fid,
                "map_unit": map_unit,
                "map_name": _clean(extra.get("MAP_NAME")) or _clean(row.get("MAP_NAME")),
                "map_key": _clean(extra.get("OLD_POLY_ID")) or _clean(row.get("MAP_KEY")),
                "soil_landscape_id": _clean(extra.get("SLC_V3R2")),
                "land_area_source_units": _int_if_whole(_number(row.get("LAND_AREA"), minimum=0)),
                "water_area_source_units": _int_if_whole(_number(row.get("WATER_AREA"), minimum=0)),
                "hectares": _int_if_whole(_number(row.get("HECTARES"), minimum=0)),
                "source_scale": profile.source_scale_range,
                "drainage_class": _clean(extra.get("DRAINAGE")),
                "capability_class": _clean(extra.get("AGRI_CAP")),
                "slope_class": _clean(extra.get("SLOPE")),
                "surface_texture_group": _clean(extra.get("SURFTEXT")),
                "erosion_risk": _clean(extra.get("ERPOLY")),
                "salinity_class": salinity_class,
                "salinity_class_source_value": salinity_source_value,
                "management_limitations": _clean(extra.get("MANAGEMENT")),
                "dominant_components": components,
                "soil_summary": _summary(profile, map_unit, components),
                "mapping_basis": profile.mapping_basis,
                "style_color": COMPONENT_COLORS[min(len(components), len(COMPONENT_COLORS)) - 1]
                if components
                else profile.color,
            }
            properties = {key: value for key, value in properties.items() if value not in (None, "", [], {})}
            geometry = _geometry_mapping(row.geometry, mapping, coordinate_precision)
            min_lon, min_lat, max_lon, max_lat = (float(value) for value in row.geometry.bounds)
            code = f"{profile.code_prefix}_{polygon_id}"
            name = str(properties["soil_summary"])
            connection.execute(
                "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fid,
                    code,
                    name,
                    sqlite3.Binary(
                        zlib.compress(
                            json.dumps(
                                properties, sort_keys=True, separators=(",", ":")
                            ).encode("utf-8")
                        )
                    ),
                    sqlite3.Binary(
                        zlib.compress(
                            json.dumps(geometry, separators=(",", ":")).encode("utf-8")
                        )
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

        source_scale_range = profile.source_scale_range
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "source_id": profile.source_id,
            "source_url": profile.source_url,
            "source_record_id": profile.source_record_id,
            "source_sha256": source_sha256,
            "support_files": support_files,
            "archive_members": archive_members,
            "relational_table_repairs": table_repairs,
            "source_registry_path": lineage.get("source_registry_path"),
            "source_registry_sha256": lineage.get("source_registry_sha256"),
            "source_entry_sha256": lineage.get("source_entry_sha256"),
            "source_crs": profile.source_crs,
            "output_crs": OUTPUT_CRS,
            "feature_count": len(frame),
            "simplification_tolerance_metres": tolerance_metres,
            "coordinate_precision_degrees": coordinate_precision,
            "feature_payload_encoding": "zlib_json_v1",
            "source_repaired_feature_count": len(source_repaired_feature_ids),
            "source_repaired_feature_ids": source_repaired_feature_ids,
            "source_repair_area_change_fraction": source_repair_area_change_fraction,
            "reprojection_repaired_feature_count": len(repaired_feature_ids),
            "reprojection_repaired_feature_ids": repaired_feature_ids,
            "reprojection_repair_area_change_fraction": reprojection_repair_area_change_fraction,
            "license": lineage.get("license_snapshot"),
            "attribution": lineage.get("license_snapshot", {}).get("attribution"),
            "source_scale_range": source_scale_range,
            "source_scale_note": profile.source_scale_note,
            "boundary": (
                "Historical detailed soil-landscape context. A polygon and listed components are mapped priors, "
                "not proof of soil at a point or present nutrient supply, pH, drainage performance, compaction, "
                "erosion, crop suitability, or a management rate. Ground-truth with field observations and "
                "current soil tests before decisions."
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
        "source_id": profile.source_id,
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": source_sha256,
        "source_bytes": source.stat().st_size,
        "support_files": support_files,
        "archive_members": archive_members,
        "relational_table_repairs": table_repairs,
        "source_crs": profile.source_crs,
        "output_crs": OUTPUT_CRS,
        "output_path": str(output.relative_to(ROOT)),
        "output_sha256": _sha256(output),
        "output_bytes": output.stat().st_size,
        "feature_count": len(frame),
        "map_units_without_components": map_units_without_components,
        "drainage_component_counts": dict(sorted(drainage_counts.items())),
        "source_scale_range": source_scale_range,
        "source_vertices": source_vertices,
        "derived_vertices": derived_vertices,
        "vertex_reduction_fraction": round(1 - (derived_vertices / source_vertices), 6),
        "source_invalid_geometries": invalid_source,
        "source_repaired_feature_count": len(source_repaired_feature_ids),
        "source_repaired_feature_ids": source_repaired_feature_ids,
        "source_repair_area_change_fraction": round(source_repair_area_change_fraction, 12),
        "derived_invalid_geometries": invalid_derived,
        "reprojection_repaired_feature_count": len(repaired_feature_ids),
        "reprojection_repaired_feature_ids": repaired_feature_ids,
        "reprojection_repair_area_change_fraction": round(
            reprojection_repair_area_change_fraction, 12
        ),
        "area_change_fraction": round(abs(simplified_area - source_area) / source_area, 8),
        "simplification_tolerance_metres": tolerance_metres,
        "coordinate_precision_degrees": coordinate_precision,
        "lineage_path": str(lineage_path.relative_to(ROOT)),
        "lineage_sha256": _sha256(lineage_path),
        "source_registry_path": lineage.get("source_registry_path"),
        "source_registry_sha256": lineage.get("source_registry_sha256"),
        "source_entry_sha256": lineage.get("source_entry_sha256"),
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
    parser.add_argument("province", choices=sorted(PROFILES))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--lineage", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--tolerance-metres", type=float, default=DEFAULT_TOLERANCE_METRES)
    parser.add_argument("--coordinate-precision", type=float, default=DEFAULT_COORDINATE_PRECISION)
    args = parser.parse_args()
    if args.tolerance_metres <= 0 or args.coordinate_precision <= 0:
        parser.error("tolerance and coordinate precision must be positive")
    profile = PROFILES[args.province]
    source_dir = ROOT / profile.source_dir
    report = build_layer(
        profile=profile,
        source=(args.source or source_dir / "source.zip"),
        lineage_path=(args.lineage or source_dir / "source.zip.lineage.json"),
        output=(args.output or ROOT / profile.output_file),
        manifest_path=(args.manifest or ROOT / profile.output_manifest),
        tolerance_metres=args.tolerance_metres,
        coordinate_precision=args.coordinate_precision,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
