from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.request import Request, urlopen

from agronomy_agent.paths import repo_path
from agronomy_agent.server.services.geospatial_service import (
    geometries_intersect,
    geometry_bbox,
    validate_geojson_geometry,
)


QUEBEC_LIDAR_PLAN_SCHEMA = "open_agronomy_agent.quebec_lidar_field_pack_plan.v1"
QUEBEC_LIDAR_FROZEN_SCHEMA = "open_agronomy_agent.quebec_lidar_frozen_pack.v1"
QUEBEC_LIDAR_DERIVED_SCHEMA = "open_agronomy_agent.quebec_lidar_field_context.v1"
QUEBEC_LIDAR_PUBLIC_RECEIPT_SCHEMA = (
    "open_agronomy_agent.quebec_lidar_field_pack_public_receipt.v1"
)
QUEBEC_LIDAR_DERIVED_PUBLIC_RECEIPT_SCHEMA = (
    "open_agronomy_agent.quebec_lidar_field_context_public_receipt.v1"
)
DEFAULT_QUEBEC_CONTEXT_MANIFEST = repo_path(
    "data/manifests/quebec_open_context_candidates_20260725.json"
)
DEFAULT_QUEBEC_LIDAR_INDEX = repo_path(
    "data/raw/quebec_open_context/qc_relief_agricole_lidar/field_tile_index.geojson"
)
QUEBEC_LIDAR_SOURCE_ID = "qc_relief_agricole_lidar"
QUEBEC_LIDAR_INDEX_RESOURCE_ID = "a27a7124-6d86-41be-803c-9e7abf0c0c93"
QUEBEC_LIDAR_INDEX_DOWNLOAD_URL = (
    "https://www.donneesquebec.ca/recherche/dataset/"
    "46f9e38c-7802-4a78-80bb-a0d7faa46b78/resource/"
    "a27a7124-6d86-41be-803c-9e7abf0c0c93/download/"
    "feuillets_reliefagricolelidar_parcellesagricoles_mapaq_epsg4326.geojson"
)
QUEBEC_LIDAR_TILE_RE = re.compile(r"^\d{2}[A-P]\d{2}(?:NE|NO|SE|SO)$")
QUEBEC_LIDAR_TILE_URL_PREFIX = (
    "https://dq-prd-bucket1.s3.ca-central-1.amazonaws.com/"
    "mapaq/ReliefLidarAgricole/"
)
MAX_QUEBEC_LIDAR_TILES_PER_FIELD = 4
MAX_QUEBEC_LIDAR_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_QUEBEC_LIDAR_ARCHIVE_MEMBERS = 64
MAX_QUEBEC_LIDAR_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_QUEBEC_LIDAR_COMPRESSION_RATIO = 50.0
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
HTTP_TIMEOUT_SECONDS = 120


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _quebec_lidar_source(
    source_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = next(
        (
            row
            for row in source_manifest.get("candidates") or []
            if row.get("source_id") == QUEBEC_LIDAR_SOURCE_ID
        ),
        None,
    )
    if not isinstance(source, dict):
        raise ValueError("Quebec LiDAR source is missing from the context manifest")
    resource = next(
        (
            row
            for row in source.get("selected_resources") or []
            if row.get("resource_id") == QUEBEC_LIDAR_INDEX_RESOURCE_ID
        ),
        None,
    )
    if not isinstance(resource, dict):
        raise ValueError("Quebec LiDAR field-tile index resource is missing")
    licence = source_manifest.get("licence") or {}
    if (
        licence.get("identifier") != "CC-BY-4.0"
        or licence.get("permits_modification") is not True
        or licence.get("permits_commercial_use") is not True
        or licence.get("permits_redistribution") is not True
    ):
        raise ValueError("Quebec LiDAR context manifest lacks the required open rights")
    return source, resource


def _validate_index(
    *,
    index_path: Path,
    resource: dict[str, Any],
) -> dict[str, Any]:
    if not index_path.is_file() or index_path.is_symlink():
        raise ValueError("Quebec LiDAR field-tile index must be a regular local file")
    expected_bytes = int(resource.get("bytes") or -1)
    expected_sha256 = str(resource.get("sha256") or "")
    if index_path.stat().st_size != expected_bytes:
        raise ValueError("Quebec LiDAR field-tile index byte count mismatch")
    if _sha256(index_path) != expected_sha256:
        raise ValueError("Quebec LiDAR field-tile index SHA256 mismatch")
    index = _load_json_object(index_path, label="Quebec LiDAR field-tile index")
    crs_name = str(((index.get("crs") or {}).get("properties") or {}).get("name") or "")
    if index.get("type") != "FeatureCollection" or crs_name != "urn:ogc:def:crs:OGC:1.3:CRS84":
        raise ValueError("Quebec LiDAR field-tile index must be an OGC CRS84 FeatureCollection")
    features = index.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Quebec LiDAR field-tile index has no features")
    return index


def _trusted_index_geometry_bbox(
    geometry: dict[str, Any],
) -> tuple[float, float, float, float]:
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Quebec LiDAR index geometry must be Polygon or MultiPolygon")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("Quebec LiDAR index geometry has no coordinates")
    positions: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and not isinstance(value[0], bool)
            and isinstance(value[1], (int, float))
            and not isinstance(value[1], bool)
        ):
            longitude = float(value[0])
            latitude = float(value[1])
            if (
                not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or longitude < -180.0
                or longitude > 180.0
                or latitude < -90.0
                or latitude > 90.0
            ):
                raise ValueError("Quebec LiDAR index geometry has invalid WGS84 coordinates")
            positions.append((longitude, latitude))
            return
        if not isinstance(value, list) or not value:
            raise ValueError("Quebec LiDAR index geometry has invalid coordinate nesting")
        for child in value:
            visit(child)

    visit(coordinates)
    if not positions:
        raise ValueError("Quebec LiDAR index geometry has no positions")
    longitudes = [position[0] for position in positions]
    latitudes = [position[1] for position in positions]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def _normalize_trusted_index_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_geojson_geometry(geometry)
    except ValueError as exc:
        if (
            geometry.get("type") != "MultiPolygon"
            or "must enclose a non-zero area" not in str(exc)
        ):
            raise
    valid_polygons: list[list[list[list[float]]]] = []
    for polygon in geometry["coordinates"]:
        try:
            normalized = validate_geojson_geometry(
                {"type": "Polygon", "coordinates": polygon}
            )
        except ValueError as exc:
            if "must enclose a non-zero area" in str(exc):
                continue
            raise
        valid_polygons.append(normalized["coordinates"])
    if not valid_polygons:
        raise ValueError("Quebec LiDAR index geometry contains only zero-area polygons")
    return {"type": "MultiPolygon", "coordinates": valid_polygons}


def _tile_record(
    feature: Any,
) -> tuple[str, str, dict[str, Any], tuple[float, float, float, float]]:
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise ValueError("Quebec LiDAR index contains an invalid feature")
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        raise ValueError("Quebec LiDAR index feature lacks properties or geometry")
    tile_id = str(properties.get("FEUILLET") or "")
    url = str(properties.get("RELPAG_URL") or "")
    if not QUEBEC_LIDAR_TILE_RE.fullmatch(tile_id):
        raise ValueError(f"Quebec LiDAR index has an unsafe tile identifier: {tile_id!r}")
    return tile_id, url, geometry, _trusted_index_geometry_bbox(geometry)


def _bboxes_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0]
        or left[0] > right[2]
        or left[3] < right[1]
        or left[1] > right[3]
    )


def plan_quebec_lidar_field_pack(
    *,
    field_geometry: dict[str, Any],
    source_manifest_path: Path = DEFAULT_QUEBEC_CONTEXT_MANIFEST,
    index_path: Path = DEFAULT_QUEBEC_LIDAR_INDEX,
    max_tiles: int = MAX_QUEBEC_LIDAR_TILES_PER_FIELD,
) -> dict[str, Any]:
    if max_tiles < 1 or max_tiles > MAX_QUEBEC_LIDAR_TILES_PER_FIELD:
        raise ValueError(
            f"max_tiles must be between 1 and {MAX_QUEBEC_LIDAR_TILES_PER_FIELD}"
        )
    normalized_field = validate_geojson_geometry(field_geometry)
    if normalized_field["type"] not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Quebec LiDAR field-pack planning requires Polygon or MultiPolygon geometry")
    if source_manifest_path.is_symlink():
        raise ValueError("Quebec open-context manifest must not be a symlink")
    if index_path.is_symlink():
        raise ValueError("Quebec LiDAR field-tile index must not be a symlink")
    source_manifest_path = source_manifest_path.resolve()
    index_path = index_path.resolve()
    source_manifest = _load_json_object(
        source_manifest_path,
        label="Quebec open-context manifest",
    )
    source, index_resource = _quebec_lidar_source(source_manifest)
    index = _validate_index(index_path=index_path, resource=index_resource)
    field_bbox = geometry_bbox(normalized_field)

    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    for feature in index["features"]:
        tile_id, url, raw_tile_geometry, tile_bbox = _tile_record(feature)
        if tile_id in seen:
            raise ValueError(f"Quebec LiDAR index contains duplicate tile: {tile_id}")
        seen.add(tile_id)
        if not _bboxes_intersect(field_bbox, tile_bbox):
            continue
        expected_url = (
            f"{QUEBEC_LIDAR_TILE_URL_PREFIX}{tile_id}/"
            f"ReliefParcellesAgricoles_{tile_id}.zip"
        )
        if url != expected_url:
            raise ValueError(
                f"Quebec LiDAR candidate tile URL is outside the trusted pattern: {tile_id}"
            )
        tile_geometry = _normalize_trusted_index_geometry(raw_tile_geometry)
        if geometries_intersect(normalized_field, tile_geometry):
            matches.append((tile_id, url))
    matches.sort()
    if len(matches) > max_tiles:
        raise ValueError(
            f"field intersects {len(matches)} Quebec LiDAR tiles; "
            f"the safety limit is {max_tiles}. Split or simplify the field boundary."
        )

    source_manifest_sha256 = _sha256(source_manifest_path)
    field_geometry_sha256 = _canonical_sha256(normalized_field)
    unsigned = {
        "schema_version": QUEBEC_LIDAR_PLAN_SCHEMA,
        "status": "ready_to_download" if matches else "no_matching_tiles",
        "source": {
            "source_id": QUEBEC_LIDAR_SOURCE_ID,
            "title": source["title"],
            "publisher": source["publisher"],
            "package_id": source["package_id"],
            "catalogue_url": source["catalogue_url"],
            "metadata_api_url": source["metadata_api_url"],
            "source_manifest_path": str(source_manifest_path),
            "source_manifest_sha256": source_manifest_sha256,
            "index_resource_id": QUEBEC_LIDAR_INDEX_RESOURCE_ID,
            "index_path": str(index_path),
            "index_sha256": index_resource["sha256"],
            "index_bytes": index_resource["bytes"],
            "index_feature_count": len(index["features"]),
            "licence": source_manifest["licence"],
        },
        "field_binding": {
            "field_geometry_sha256": field_geometry_sha256,
            "geometry_type": normalized_field["type"],
            "exact_geometry_included": False,
            "jurisdiction_required": "Quebec",
        },
        "resources": [
            {
                "tile_id": tile_id,
                "url": url,
                "archive_filename": f"ReliefParcellesAgricoles_{tile_id}.zip",
                "publisher_checksum_available": False,
                "acquisition_integrity": (
                    "HTTPS acquisition followed by local SHA256 freeze; "
                    "the publisher does not publish a checksum in the tile index."
                ),
            }
            for tile_id, url in matches
        ],
        "privacy": {
            "classification": "workspace_private",
            "exact_field_geometry_sent_to_source": False,
            "disclosure_when_downloading": (
                "The remote host receives the requested 1:20,000 tile identifier and network "
                "metadata, which reveals an approximate area but not the exact field boundary."
            ),
            "public_trace_must_omit": [
                "tile_id",
                "url",
                "archive_filename",
                "exact geometry",
            ],
        },
        "decision_boundary": {
            "retrieval_policy": "context_only",
            "query_ready_after_download": False,
            "requires_local_derivation": True,
            "does_not_establish": source["does_not_establish"],
            "statement": (
                "This plan only identifies official high-resolution terrain files available "
                "for the field area. It is not a terrain measurement, drainage diagnosis, "
                "erosion finding, design, legal boundary, or management recommendation."
            ),
        },
    }
    return {**unsigned, "plan_sha256": _canonical_sha256(unsigned)}


def validate_quebec_lidar_plan(plan: dict[str, Any]) -> dict[str, Any]:
    claimed = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if plan.get("schema_version") != QUEBEC_LIDAR_PLAN_SCHEMA:
        raise ValueError("unexpected Quebec LiDAR field-pack plan schema")
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("Quebec LiDAR field-pack plan hash mismatch")
    resources = plan.get("resources")
    if not isinstance(resources, list):
        raise ValueError("Quebec LiDAR field-pack plan resources must be a list")
    if len(resources) > MAX_QUEBEC_LIDAR_TILES_PER_FIELD:
        raise ValueError("Quebec LiDAR field-pack plan exceeds the tile limit")
    seen: set[str] = set()
    for resource in resources:
        if not isinstance(resource, dict):
            raise ValueError("Quebec LiDAR field-pack plan resource is invalid")
        tile_id = str(resource.get("tile_id") or "")
        expected_url = (
            f"{QUEBEC_LIDAR_TILE_URL_PREFIX}{tile_id}/"
            f"ReliefParcellesAgricoles_{tile_id}.zip"
        )
        expected_filename = f"ReliefParcellesAgricoles_{tile_id}.zip"
        if (
            not QUEBEC_LIDAR_TILE_RE.fullmatch(tile_id)
            or resource.get("url") != expected_url
            or resource.get("archive_filename") != expected_filename
            or tile_id in seen
        ):
            raise ValueError(f"unsafe Quebec LiDAR field-pack resource: {tile_id!r}")
        seen.add(tile_id)
    return plan


def public_quebec_lidar_pack_receipt(plan: dict[str, Any]) -> dict[str, Any]:
    validate_quebec_lidar_plan(plan)
    return {
        "schema_version": QUEBEC_LIDAR_PUBLIC_RECEIPT_SCHEMA,
        "status": plan["status"],
        "source_id": plan["source"]["source_id"],
        "source_title": plan["source"]["title"],
        "publisher": plan["source"]["publisher"],
        "source_manifest_sha256": plan["source"]["source_manifest_sha256"],
        "index_sha256": plan["source"]["index_sha256"],
        "field_geometry_sha256": plan["field_binding"]["field_geometry_sha256"],
        "matched_tile_count": len(plan["resources"]),
        "exact_geometry_included": False,
        "tile_identifiers_included": False,
        "download_urls_included": False,
        "retrieval_policy": "context_only",
        "query_ready": False,
        "boundary": plan["decision_boundary"]["statement"],
    }


def _safe_archive_member_name(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise ValueError("Quebec LiDAR archive contains an unsafe member path")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Quebec LiDAR archive contains an unsafe member path")
    if len(path.parts) != 1:
        raise ValueError("Quebec LiDAR archive members must be flat files")
    return path.name


def inspect_quebec_lidar_archive(
    archive_path: Path,
    *,
    tile_id: str,
) -> dict[str, Any]:
    if not QUEBEC_LIDAR_TILE_RE.fullmatch(tile_id):
        raise ValueError("invalid Quebec LiDAR tile identifier")
    if archive_path.is_symlink():
        raise ValueError("Quebec LiDAR archive must not be a symlink")
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise ValueError("Quebec LiDAR archive must be a regular file")
    archive_bytes = archive_path.stat().st_size
    if archive_bytes <= 0 or archive_bytes > MAX_QUEBEC_LIDAR_ARCHIVE_BYTES:
        raise ValueError("Quebec LiDAR archive size is outside the allowed range")
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("Quebec LiDAR archive is not a valid ZIP file") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_QUEBEC_LIDAR_ARCHIVE_MEMBERS:
            raise ValueError("Quebec LiDAR archive member count is outside the allowed range")
        names: list[str] = []
        seen: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            if info.is_dir():
                raise ValueError("Quebec LiDAR archive must not contain directories")
            safe_name = _safe_archive_member_name(info.filename)
            normalized = safe_name.casefold()
            if normalized in seen:
                raise ValueError("Quebec LiDAR archive contains duplicate member paths")
            seen.add(normalized)
            names.append(safe_name)
            total_uncompressed += int(info.file_size)
            if info.flag_bits & 0x1:
                raise ValueError("Quebec LiDAR archive must not contain encrypted members")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise ValueError("Quebec LiDAR archive must not contain symlinks")
        if total_uncompressed > MAX_QUEBEC_LIDAR_UNCOMPRESSED_BYTES:
            raise ValueError("Quebec LiDAR archive uncompressed size exceeds the allowed range")
        ratio = total_uncompressed / max(archive_bytes, 1)
        if ratio > MAX_QUEBEC_LIDAR_COMPRESSION_RATIO:
            raise ValueError("Quebec LiDAR archive compression ratio exceeds the allowed range")

    required: list[str] = []
    for prefix in ("CuvPAg", "TEPAg"):
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            required.append(f"{prefix}_{tile_id}{suffix}")
    required.append(f"PentesParcellesAgricoles_{tile_id}.tif")
    missing = sorted(set(required) - set(names))
    if missing:
        raise ValueError(f"Quebec LiDAR archive is missing required members: {missing}")
    return {
        "tile_id": tile_id,
        "archive_filename": archive_path.name,
        "archive_sha256": _sha256(archive_path),
        "archive_bytes": archive_bytes,
        "member_count": len(names),
        "uncompressed_bytes": total_uncompressed,
        "compression_ratio": round(ratio, 3),
        "required_members_present": True,
        "member_names": sorted(names),
    }


def freeze_downloaded_quebec_lidar_pack(
    *,
    plan: dict[str, Any],
    download_dir: Path,
    output_manifest: Path,
) -> dict[str, Any]:
    validate_quebec_lidar_plan(plan)
    if plan["status"] != "ready_to_download" or not plan["resources"]:
        raise ValueError("Quebec LiDAR plan has no resources to freeze")
    if download_dir.is_symlink():
        raise ValueError("Quebec LiDAR download directory must not be a symlink")
    download_dir = download_dir.resolve()
    if not download_dir.is_dir():
        raise ValueError("Quebec LiDAR download directory must be a regular directory")
    downloads: list[dict[str, Any]] = []
    for resource in plan["resources"]:
        archive_path = download_dir / resource["archive_filename"]
        downloads.append(
            {
                **inspect_quebec_lidar_archive(
                    archive_path,
                    tile_id=resource["tile_id"],
                ),
                "source_url": resource["url"],
                "publisher_checksum_available": False,
            }
        )
    unsigned = {
        "schema_version": QUEBEC_LIDAR_FROZEN_SCHEMA,
        "status": "frozen_raw_private_context_pack",
        "plan_sha256": plan["plan_sha256"],
        "source": plan["source"],
        "field_binding": plan["field_binding"],
        "downloads": downloads,
        "privacy": plan["privacy"],
        "decision_boundary": {
            **plan["decision_boundary"],
            "query_ready_after_download": False,
            "requires_local_derivation": True,
            "statement": (
                "The raw official tile archives are hash-frozen for offline preparation. "
                "They are not queryable agent evidence until a separate derivation validates "
                "the vector/raster contents against the exact field binding."
            ),
        },
    }
    frozen = {**unsigned, "frozen_pack_sha256": _canonical_sha256(unsigned)}
    if output_manifest.is_symlink():
        raise ValueError("Quebec LiDAR frozen manifest must not be a symlink")
    if output_manifest.parent.is_symlink():
        raise ValueError("Quebec LiDAR frozen manifest directory must not be a symlink")
    output_manifest = output_manifest.resolve()
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_manifest.parent,
        prefix=f".{output_manifest.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(frozen, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output_manifest)
    return frozen


def validate_quebec_lidar_frozen_pack(
    frozen: dict[str, Any],
    *,
    plan: dict[str, Any],
) -> dict[str, Any]:
    validate_quebec_lidar_plan(plan)
    claimed = str(frozen.get("frozen_pack_sha256") or "")
    unsigned = dict(frozen)
    unsigned.pop("frozen_pack_sha256", None)
    if frozen.get("schema_version") != QUEBEC_LIDAR_FROZEN_SCHEMA:
        raise ValueError("unexpected Quebec LiDAR frozen-pack schema")
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("Quebec LiDAR frozen-pack hash mismatch")
    if frozen.get("plan_sha256") != plan["plan_sha256"]:
        raise ValueError("Quebec LiDAR frozen pack does not match the field-pack plan")
    if frozen.get("status") != "frozen_raw_private_context_pack":
        raise ValueError("Quebec LiDAR frozen pack has an unsafe status")
    downloads = frozen.get("downloads")
    if not isinstance(downloads, list) or len(downloads) != len(plan["resources"]):
        raise ValueError("Quebec LiDAR frozen pack has an invalid download set")
    by_tile = {
        str(download.get("tile_id") or ""): download
        for download in downloads
        if isinstance(download, dict)
    }
    if len(by_tile) != len(downloads):
        raise ValueError("Quebec LiDAR frozen pack has duplicate or invalid downloads")
    for resource in plan["resources"]:
        download = by_tile.get(resource["tile_id"])
        if (
            download is None
            or download.get("archive_filename") != resource["archive_filename"]
            or download.get("source_url") != resource["url"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(download.get("archive_sha256") or ""))
            or int(download.get("archive_bytes") or 0) <= 0
            or download.get("required_members_present") is not True
        ):
            raise ValueError(
                f"Quebec LiDAR frozen download binding is invalid: {resource['tile_id']}"
            )
    return frozen


def _load_geospatial_prep_dependencies() -> tuple[Any, Any]:
    try:
        import geopandas
        from shapely.geometry import shape
    except ImportError as exc:
        raise RuntimeError(
            "Quebec LiDAR derivation requires the optional geospatial-prep dependencies"
        ) from exc
    return geopandas, shape


def derive_quebec_lidar_field_context(
    *,
    plan: dict[str, Any],
    frozen: dict[str, Any],
    field_geometry: dict[str, Any],
    download_dir: Path,
) -> dict[str, Any]:
    validate_quebec_lidar_frozen_pack(frozen, plan=plan)
    normalized_field = validate_geojson_geometry(field_geometry)
    if normalized_field["type"] not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Quebec LiDAR derivation requires Polygon or MultiPolygon geometry")
    field_geometry_sha256 = _canonical_sha256(normalized_field)
    if field_geometry_sha256 != plan["field_binding"]["field_geometry_sha256"]:
        raise ValueError("field geometry does not match the Quebec LiDAR plan binding")
    if download_dir.is_symlink():
        raise ValueError("Quebec LiDAR download directory must not be a symlink")
    download_dir = download_dir.resolve()
    if not download_dir.is_dir():
        raise ValueError("Quebec LiDAR download directory must be a regular directory")

    geopandas, shape = _load_geospatial_prep_dependencies()
    field_shape = shape(normalized_field)
    frozen_by_tile = {
        download["tile_id"]: download for download in frozen["downloads"]
    }
    tile_results: list[dict[str, Any]] = []
    total_depression_parts = 0
    total_depression_area_m2 = 0.0
    total_flow_path_parts = 0
    total_flow_path_length_m = 0.0

    for resource in plan["resources"]:
        tile_id = resource["tile_id"]
        archive_path = download_dir / resource["archive_filename"]
        inspected = inspect_quebec_lidar_archive(archive_path, tile_id=tile_id)
        expected = frozen_by_tile[tile_id]
        if (
            inspected["archive_sha256"] != expected["archive_sha256"]
            or inspected["archive_bytes"] != expected["archive_bytes"]
        ):
            raise ValueError(f"Quebec LiDAR archive changed after freeze: {tile_id}")
        with tempfile.TemporaryDirectory(prefix=f"quebec-lidar-{tile_id}-") as temporary:
            extraction_dir = Path(temporary)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extraction_dir)
            depressions = geopandas.read_file(extraction_dir / f"CuvPAg_{tile_id}.shp")
            flow_paths = geopandas.read_file(extraction_dir / f"TEPAg_{tile_id}.shp")
            for layer_name, frame in (
                ("depression", depressions),
                ("flow-path", flow_paths),
            ):
                if frame.crs is None or not frame.crs.is_projected:
                    raise ValueError(
                        f"Quebec LiDAR {layer_name} layer lacks a projected CRS: {tile_id}"
                    )
                axis_units = {
                    str(axis.unit_name or "").lower() for axis in frame.crs.axis_info
                }
                if not axis_units or not axis_units <= {"metre", "meter"}:
                    raise ValueError(
                        f"Quebec LiDAR {layer_name} layer is not metre-based: {tile_id}"
                    )
                if frame.geometry.isna().any() or frame.geometry.is_empty.any():
                    raise ValueError(
                        f"Quebec LiDAR {layer_name} layer contains empty geometry: {tile_id}"
                    )
                if not frame.geometry.is_valid.all():
                    raise ValueError(
                        f"Quebec LiDAR {layer_name} layer contains invalid geometry: {tile_id}"
                    )
            field_in_tile_crs = geopandas.GeoSeries(
                [field_shape],
                crs="EPSG:4326",
            ).to_crs(depressions.crs).iloc[0]
            if depressions.crs != flow_paths.crs:
                flow_field = geopandas.GeoSeries(
                    [field_shape],
                    crs="EPSG:4326",
                ).to_crs(flow_paths.crs).iloc[0]
            else:
                flow_field = field_in_tile_crs

            depression_hits = depressions.loc[
                depressions.geometry.intersects(field_in_tile_crs)
            ]
            depression_intersections = depression_hits.geometry.intersection(
                field_in_tile_crs
            )
            flow_hits = flow_paths.loc[flow_paths.geometry.intersects(flow_field)]
            flow_intersections = flow_hits.geometry.intersection(flow_field)
            depression_parts = int(len(depression_intersections))
            depression_area_m2 = float(depression_intersections.area.sum())
            flow_path_parts = int(len(flow_intersections))
            flow_path_length_m = float(flow_intersections.length.sum())

        total_depression_parts += depression_parts
        total_depression_area_m2 += depression_area_m2
        total_flow_path_parts += flow_path_parts
        total_flow_path_length_m += flow_path_length_m
        tile_results.append(
            {
                "tile_id": tile_id,
                "archive_sha256": inspected["archive_sha256"],
                "source_crs": str(depressions.crs),
                "depression_feature_parts_intersecting": depression_parts,
                "depression_clipped_area_m2": round(depression_area_m2, 2),
                "flow_path_feature_parts_intersecting": flow_path_parts,
                "flow_path_clipped_length_m": round(flow_path_length_m, 2),
            }
        )

    totals = {
        "depression_feature_parts_intersecting": total_depression_parts,
        "depression_clipped_area_m2": round(total_depression_area_m2, 2),
        "flow_path_feature_parts_intersecting": total_flow_path_parts,
        "flow_path_clipped_length_m": round(total_flow_path_length_m, 2),
        "slope_raster_processed": False,
    }
    context_text = (
        "Official MAPAQ LiDAR-derived terrain layers intersecting this field contain "
        f"{total_depression_parts} mapped depression feature part(s), covering "
        f"{total_depression_area_m2:.2f} m² inside the supplied boundary, and "
        f"{total_flow_path_parts} mapped flow-path feature part(s), totalling "
        f"{total_flow_path_length_m:.2f} m inside the boundary. "
        "These are terrain-derived regional context, not observations of current water, "
        "erosion, drainage performance, or a management recommendation. The slope raster "
        "has not been processed."
    )
    context_text_fr = (
        "Les couches de terrain dérivées du LiDAR du MAPAQ qui croisent ce champ "
        f"contiennent {total_depression_parts} partie(s) d'entités de dépression "
        f"cartographiées, couvrant {total_depression_area_m2:.2f} m² à l'intérieur de "
        f"la limite fournie, ainsi que {total_flow_path_parts} partie(s) de parcours "
        f"d'écoulement cartographiés, totalisant {total_flow_path_length_m:.2f} m à "
        "l'intérieur de cette limite. Ces données constituent un contexte régional "
        "dérivé du terrain; elles ne décrivent pas l'eau présente, l'érosion actuelle, "
        "le rendement du drainage ni une recommandation de gestion. Le raster de pente "
        "n'a pas été traité."
    )
    unsigned = {
        "schema_version": QUEBEC_LIDAR_DERIVED_SCHEMA,
        "status": "derived_private_field_context",
        "plan_sha256": plan["plan_sha256"],
        "frozen_pack_sha256": frozen["frozen_pack_sha256"],
        "source": {
            "source_id": plan["source"]["source_id"],
            "title": plan["source"]["title"],
            "publisher": plan["source"]["publisher"],
            "licence": plan["source"]["licence"],
        },
        "field_binding": {
            **plan["field_binding"],
            "exact_geometry_included": False,
        },
        "tile_results": tile_results,
        "totals": totals,
        "context_record": {
            "language": ["fr-CA", "en-CA"],
            "retrieval_policy": "context_only",
            "decision_role": "field_specific_terrain_context",
            "text": context_text,
            "text_en": context_text,
            "text_fr": context_text_fr,
        },
        "privacy": {
            "classification": "workspace_private_field_context",
            "exact_geometry_included": False,
            "approximate_location_identifiers_included": True,
            "public_trace_requires_minimization": True,
        },
        "decision_boundary": {
            "query_ready_for_bound_field": True,
            "recommendation_grade": False,
            "slope_raster_processed": False,
            "publisher_attribute_units_inferred": False,
            "tile_edge_feature_parts_may_not_equal_unique_landscape_features": True,
            "statement": (
                "The vector summary can be retrieved only as context for the hash-bound "
                "field. It does not establish current conditions, a legal boundary, a "
                "drainage design, erosion severity, or a management recommendation."
            ),
        },
    }
    return {**unsigned, "derived_context_sha256": _canonical_sha256(unsigned)}


def public_quebec_lidar_derived_context_receipt(
    derived: dict[str, Any],
) -> dict[str, Any]:
    claimed = str(derived.get("derived_context_sha256") or "")
    unsigned = dict(derived)
    unsigned.pop("derived_context_sha256", None)
    if derived.get("schema_version") != QUEBEC_LIDAR_DERIVED_SCHEMA:
        raise ValueError("unexpected Quebec LiDAR derived-context schema")
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("Quebec LiDAR derived-context hash mismatch")
    return {
        "schema_version": QUEBEC_LIDAR_DERIVED_PUBLIC_RECEIPT_SCHEMA,
        "status": derived["status"],
        "source_id": derived["source"]["source_id"],
        "publisher": derived["source"]["publisher"],
        "field_geometry_sha256": derived["field_binding"]["field_geometry_sha256"],
        "derived_context_sha256": claimed,
        "matched_tile_count": len(derived["tile_results"]),
        "totals": derived["totals"],
        "exact_geometry_included": False,
        "tile_identifiers_included": False,
        "download_urls_included": False,
        "retrieval_policy": "context_only",
        "recommendation_grade": False,
        "boundary": derived["decision_boundary"]["statement"],
    }


def quebec_lidar_field_event_envelope(
    derived: dict[str, Any],
) -> dict[str, Any]:
    receipt = public_quebec_lidar_derived_context_receipt(derived)
    return {
        "event_type": "note",
        "payload": {
            "schema_version": "open_agronomy_agent.field_context_evidence_note.v1",
            "summary": derived["context_record"]["text"],
            "summary_fr": derived["context_record"]["text_fr"],
            "context_kind": "quebec_lidar_terrain",
            "derived_context_sha256": receipt["derived_context_sha256"],
            "field_geometry_sha256": receipt["field_geometry_sha256"],
            "retrieval_policy": "context_only",
            "recommendation_grade": False,
            "totals": receipt["totals"],
            "boundary": receipt["boundary"],
        },
        "provenance": {
            "capture_method": "local_offline_context_derivation",
            "source_id": receipt["source_id"],
            "publisher": receipt["publisher"],
            "plan_sha256": derived["plan_sha256"],
            "frozen_pack_sha256": derived["frozen_pack_sha256"],
            "derived_context_sha256": receipt["derived_context_sha256"],
            "source_archive_sha256s": sorted(
                result["archive_sha256"] for result in derived["tile_results"]
            ),
            "exact_geometry_included": False,
            "tile_identifiers_included": False,
        },
    }


def _download_response_to_file(
    response: BinaryIO,
    *,
    destination: Path,
    max_bytes: int,
) -> None:
    written = 0
    with destination.open("wb") as handle:
        while True:
            block = response.read(DOWNLOAD_CHUNK_BYTES)
            if not block:
                break
            written += len(block)
            if written > max_bytes:
                raise ValueError("Quebec LiDAR archive exceeds the download size limit")
            handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())


def download_quebec_lidar_index(
    *,
    source_manifest_path: Path = DEFAULT_QUEBEC_CONTEXT_MANIFEST,
    output_path: Path = DEFAULT_QUEBEC_LIDAR_INDEX,
    allow_network: bool,
) -> dict[str, Any]:
    if not allow_network:
        raise ValueError("index download requires explicit allow_network=True")
    if source_manifest_path.is_symlink():
        raise ValueError("Quebec open-context manifest must not be a symlink")
    source_manifest_path = source_manifest_path.resolve()
    source_manifest = _load_json_object(
        source_manifest_path,
        label="Quebec open-context manifest",
    )
    source, resource = _quebec_lidar_source(source_manifest)
    if resource.get("url") != QUEBEC_LIDAR_INDEX_DOWNLOAD_URL:
        raise ValueError("Quebec LiDAR index URL is outside the trusted resource")
    if output_path.is_symlink() or output_path.parent.is_symlink():
        raise ValueError("Quebec LiDAR index output path must not use symlinks")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    request = Request(
        QUEBEC_LIDAR_INDEX_DOWNLOAD_URL,
        headers={"User-Agent": "OpenAgronomyAgent/0.1 offline-context-pack"},
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            content_length = response.headers.get("Content-Length")
            if content_type and not any(
                allowed in content_type
                for allowed in ("json", "geo+json", "octet-stream", "text/plain")
            ):
                raise ValueError("Quebec LiDAR index response is not a GeoJSON content type")
            if content_length and int(content_length) != int(resource["bytes"]):
                raise ValueError("Quebec LiDAR index response byte count mismatch")
            _download_response_to_file(
                response,
                destination=temporary,
                max_bytes=int(resource["bytes"]),
            )
        index = _validate_index(index_path=temporary, resource=resource)
        os.replace(temporary, output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "schema_version": "open_agronomy_agent.quebec_lidar_index_fetch_receipt.v1",
        "status": "verified",
        "source_id": source["source_id"],
        "resource_id": resource["resource_id"],
        "download_url": QUEBEC_LIDAR_INDEX_DOWNLOAD_URL,
        "output_path": str(output_path),
        "sha256": resource["sha256"],
        "bytes": resource["bytes"],
        "feature_count": len(index["features"]),
        "licence": source_manifest["licence"],
    }


def download_and_freeze_quebec_lidar_pack(
    *,
    plan: dict[str, Any],
    download_dir: Path,
    output_manifest: Path,
    allow_network: bool,
) -> dict[str, Any]:
    validate_quebec_lidar_plan(plan)
    if not allow_network:
        raise ValueError("network download requires explicit allow_network=True")
    if plan["status"] != "ready_to_download" or not plan["resources"]:
        raise ValueError("Quebec LiDAR plan has no resources to download")
    if download_dir.is_symlink():
        raise ValueError("Quebec LiDAR download directory must not be a symlink")
    download_dir = download_dir.resolve()
    download_dir.mkdir(parents=True, exist_ok=True)
    for resource in plan["resources"]:
        destination = download_dir / resource["archive_filename"]
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.unlink(missing_ok=True)
        request = Request(
            resource["url"],
            headers={"User-Agent": "OpenAgronomyAgent/0.1 offline-context-pack"},
        )
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                content_length = response.headers.get("Content-Length")
                if content_type and "zip" not in content_type and "octet-stream" not in content_type:
                    raise ValueError("Quebec LiDAR response is not a ZIP content type")
                if content_length and int(content_length) > MAX_QUEBEC_LIDAR_ARCHIVE_BYTES:
                    raise ValueError("Quebec LiDAR response exceeds the download size limit")
                _download_response_to_file(
                    response,
                    destination=temporary,
                    max_bytes=MAX_QUEBEC_LIDAR_ARCHIVE_BYTES,
                )
            inspect_quebec_lidar_archive(temporary, tile_id=resource["tile_id"])
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return freeze_downloaded_quebec_lidar_pack(
        plan=plan,
        download_dir=download_dir,
        output_manifest=output_manifest,
    )
