"""Bounded vector exchange intake using GDAL through Pyogrio/GeoPandas.

Only uploaded bytes are admitted; no external URLs, GDAL VFS paths, arbitrary
SQL, or archive-provided paths are passed to the driver. Original source CRS
and transformations remain explicit in the returned receipt.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Any
import zipfile

from .geometry import canonical_geometry, project_geometry

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FEATURES = 250
MAX_ZIP_MEMBERS = 40
MAX_EXPANDED_BYTES = 30 * 1024 * 1024


def _property(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _property(value.item())
    return str(value)


def _geojson(raw: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        root = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("GeoJSON upload must be valid UTF-8 JSON") from exc
    if not isinstance(root, dict):
        raise ValueError("GeoJSON root must be an object")
    if "crs" in root:
        raise ValueError("GeoJSON CRS declarations are unsupported; RFC 7946 requires WGS84")
    if root.get("type") == "FeatureCollection":
        features = root.get("features")
        if not isinstance(features, list):
            raise ValueError("GeoJSON FeatureCollection requires a features array")
    else:
        features = [root if root.get("type") == "Feature" else {"type": "Feature", "geometry": root}]
    if len(features) > MAX_FEATURES:
        raise ValueError(f"boundary upload exceeds {MAX_FEATURES} features; split it before import")
    result = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"GeoJSON feature {index} is malformed")
        geometry = canonical_geometry(feature)
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise ValueError(f"GeoJSON feature {index} properties must be an object")
        result.append({"type": "Feature", "geometry": geometry, "properties": properties, "source_layer": "geojson", "source_feature_index": index})
    return result, [{"layer": "geojson", "source_crs": "EPSG:4326", "crs_basis": "RFC7946", "target_crs": "EPSG:4326", "reprojected": False}]


def _read_dataset(path: Path, *, expected_driver: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        import geopandas  # noqa: F401 - Pyogrio's GeoDataFrame reader dependency.
        import pyogrio
        from pyproj import CRS
        from shapely.geometry import mapping
    except ImportError as exc:
        raise ValueError("Vector import dependencies are unavailable; install the supported geospatial requirements") from exc
    try:
        layers = pyogrio.list_layers(path)
        if len(layers) > MAX_ZIP_MEMBERS:
            raise ValueError("vector upload contains too many layers")
        output, receipts = [], []
        for layer_name, geometry_type in layers:
            if geometry_type is None:
                continue
            info = pyogrio.read_info(path, layer=layer_name)
            if info["driver"] != expected_driver:
                raise ValueError("uploaded vector driver does not match its file type")
            if not info.get("crs"):
                raise ValueError(f"layer {layer_name} has missing or undefined CRS metadata")
            source_crs = CRS.from_user_input(info["crs"])
            if (not (source_crs.is_projected or source_crs.is_geographic)
                or any(word in source_crs.name.lower() for word in ("undefined", "unknown"))):
                raise ValueError(f"layer {layer_name} has missing or ambiguous CRS metadata")
            remaining = MAX_FEATURES - len(output)
            frame = pyogrio.read_dataframe(path, layer=layer_name, max_features=remaining + 1)
            if len(frame) > remaining:
                raise ValueError(f"boundary upload exceeds {MAX_FEATURES} features; split it before import")
            reprojected = not source_crs.equals(CRS.from_epsg(4326), ignore_axis_order=True)
            receipts.append({"layer": str(layer_name), "source_crs": source_crs.to_string(), "source_crs_wkt": source_crs.to_wkt(), "crs_basis": "declared_dataset_metadata", "target_crs": "EPSG:4326", "reprojected": reprojected, "transform_policy": "PyProj always_xy; no ballpark; best available operation required"})
            for index, (_, row) in enumerate(frame.iterrows()):
                original = row[frame.geometry.name]
                if original is None or original.is_empty:
                    raise ValueError(f"layer {layer_name} feature {index} has missing geometry")
                if original.geom_type not in {"Point", "Polygon", "MultiPolygon"}:
                    raise ValueError(f"layer {layer_name} feature {index} has unsupported {original.geom_type} geometry")
                projected = project_geometry(original, "EPSG:4326", source_crs=source_crs)
                output.append({"type": "Feature", "geometry": canonical_geometry(mapping(projected)), "properties": {str(key): _property(value) for key, value in row.items() if key != frame.geometry.name}, "source_layer": str(layer_name), "source_feature_index": index})
        return output, receipts
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("vector upload could not be read as a supported geospatial dataset") from exc


def _shapefile(raw: bytes, directory: Path) -> Path:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("zip upload is not a valid zip archive") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_MEMBERS or sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
            raise ValueError("zip upload exceeds member count or expanded size limit")
        names: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise ValueError("zip upload contains an unsafe path, symlink, or encrypted member")
            if info.is_dir():
                continue
            key = info.filename.lower()
            if key in names:
                raise ValueError("zip upload contains ambiguous duplicate member names")
            names[key] = info
        shapefiles = [name for name in names if name.endswith(".shp")]
        if len(shapefiles) != 1:
            raise ValueError("zipped shapefile must contain exactly one .shp dataset; select a layer before import")
        base = shapefiles[0][:-4]
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            if base + suffix not in names:
                raise ValueError(f"zipped shapefile requires matching {suffix} metadata; CRS must be declared")
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            info = names.get(base + suffix)
            if info is not None:
                # Fixed private filenames: never extract paths supplied by upload.
                try:
                    content = archive.read(info)
                except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
                    raise ValueError("zip member could not be safely read") from exc
                (directory / ("boundary" + suffix)).write_bytes(content)
    return directory / "boundary.shp"


def read_vector_upload(*, filename: str, raw: bytes, content_type: str | None = None) -> dict[str, Any]:
    """Read all supported features, retaining complete topology and CRS receipts."""
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("boundary upload is empty or exceeds 25 MB limit")
    suffix = Path(filename).suffix.lower()
    if suffix in {".json", ".geojson"} or (content_type or "").lower() in {"application/json", "application/geo+json", "geojson"}:
        features, receipts = _geojson(raw)
        source_format = "geojson"
    elif suffix == ".shp":
        raise ValueError("standalone .shp has no declared CRS; upload a ZIP with .shp, .shx, .dbf and .prj")
    elif suffix in {".zip", ".gpkg"}:
        with tempfile.TemporaryDirectory(prefix="agronomy-vector-") as temp:
            directory = Path(temp)
            if suffix == ".zip":
                path = _shapefile(raw, directory)
                source_format, driver = "zipped_shapefile", "ESRI Shapefile"
            else:
                if not raw.startswith(b"SQLite format 3\x00"):
                    raise ValueError("GeoPackage must be a SQLite GeoPackage file")
                path = directory / "boundary.gpkg"
                path.write_bytes(raw)
                source_format, driver = "geopackage", "GPKG"
            features, receipts = _read_dataset(path, expected_driver=driver)
    else:
        raise ValueError("boundary upload must be GeoJSON, zipped shapefile, or GeoPackage")
    if not features:
        raise ValueError("boundary upload did not contain supported Point, Polygon, or MultiPolygon geometry")
    return {"schema_version": "open_agronomy_agent.vector_import.v1", "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw), "features": features, "source_format": source_format, "coordinate_reference": {"target_crs": "EPSG:4326", "label": "WGS84 longitude/latitude", "reprojected": any(row["reprojected"] for row in receipts), "sources": receipts}}
