"""Read bounded public categorical ImageServer exports against a field boundary."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from agronomy_agent.geospatial.geometry import canonical_geometry, project_geometry
from agronomy_agent.geospatial.raster import fractional_weights

COVERAGE_VERSION = "crop-cover.v1"
AAFC_ACI_CATALOG_URL = "https://agriculture.canada.ca/imagery-images/rest/services/annual_crop_inventory"
CDL_IMAGE_SERVER = "https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer"
HAWAII_CDL_IMAGE_SERVER = "https://pdi.scinet.usda.gov/image/rest/services/CDL_WM_Hawaii/ImageServer"
DOMINANT_FRACTION = 0.8
_MAX_SIDE = 1024
_MAX_CELLS = 1024 * 1024
_MAX_WINDOWS = 16
_MAX_EXPORT_BYTES = 2_000_000


@dataclass(frozen=True)
class _Window:
    resolution: int
    west: int
    north: int
    width: int
    height: int

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.west, self.north - self.resolution * self.height,
                self.west + self.resolution * self.width, self.north)


def prepare_geometry(geometry: dict[str, Any], max_vertices: int, max_span: float) -> Any:
    from shapely.geometry import shape

    value = shape(canonical_geometry(geometry, max_vertices=max_vertices))
    west, south, east, north = value.bounds
    if east - west > max_span or north - south > max_span:
        raise ValueError("Crop-cover lookup requires a smaller field boundary")
    return value


def cdl_service(geometry: Any) -> tuple[str, int] | None:
    west, south, east, north = geometry.bounds
    if -161 <= west <= east <= -154 and 18 <= south <= north <= 23:
        return HAWAII_CDL_IMAGE_SERVER, 6933
    if -126 <= west <= east <= -65 and 23 <= south <= north <= 50:
        return CDL_IMAGE_SERVER, 6933
    return None


def read_provider_response(url: str, operation: str, *, timeout: int, limit: int) -> bytes:
    user_agent = "agronomy-agent-local-tools/0.1"
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise RuntimeError(f"Crop-cover {operation} response exceeds size limit")
    return raw


def _read(service: str, operation: str, parameters: dict[str, Any], *, timeout: int, limit: int) -> bytes:
    query = urllib.parse.urlencode(parameters)
    return read_provider_response(f"{service}/{operation}?{query}", operation, timeout=timeout, limit=limit)


def cdl_catalog(service: str, *, timeout: int) -> tuple[dict[int, dict[str, Any]], str]:
    raw = _read(service, "query", {
        "f": "json", "where": "Category=1 AND Year>=2008",
        "outFields": "OBJECTID,Year,Name", "returnGeometry": "false",
    }, timeout=timeout, limit=100_000)
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("error") or data.get("exceededTransferLimit") or not isinstance(data.get("features"), list):
        raise RuntimeError("USDA CDL catalog did not return a complete annual raster listing")
    suffix = "cdl_hawaii" if service == HAWAII_CDL_IMAGE_SERVER else "cdls"
    catalog: dict[int, dict[str, Any]] = {}
    object_ids: set[int] = set()
    for row in data["features"]:
        attributes = row.get("attributes") if isinstance(row, dict) else None
        if not isinstance(attributes, dict):
            raise RuntimeError("USDA CDL catalog returned invalid raster metadata")
        year, oid, name = (attributes.get(key) for key in ("Year", "OBJECTID", "Name"))
        if type(year) is not int or type(oid) is not int or oid <= 0 or not isinstance(name, str):
            raise RuntimeError("USDA CDL catalog returned invalid raster metadata")
        match = re.fullmatch(rf"{year}_(10|30)m_{suffix}", name)
        if year < 2008 or not match or year in catalog or oid in object_ids:
            raise RuntimeError("USDA CDL catalog returned ambiguous or unsupported annual raster metadata")
        catalog[year] = {"object_id": oid, "name": name, "resolution_m": int(match[1])}
        object_ids.add(oid)
    if not catalog:
        raise RuntimeError("USDA CDL catalog has no supported annual rasters")
    return catalog, hashlib.sha256(raw).hexdigest()


def _window(geometry: Any, resolution: int) -> _Window:
    west, south, east, north = geometry.bounds
    x = math.floor(west / resolution)
    y = math.floor(south / resolution)
    right = max(x + 1, math.ceil(east / resolution))
    top = max(y + 1, math.ceil(north / resolution))
    if geometry.geom_type == "Point":
        # Fetch the cell containing the point, including coordinates on a grid line.
        right, top = x + 1, y + 1
    return _Window(resolution, x * resolution, top * resolution, right - x, top - y)


class WindowLimitError(ValueError):
    """The complete boundary would exceed the published-resolution query budget."""


def _windows(geometry: Any, resolution: int) -> list[tuple[Any, _Window]]:
    whole = _window(geometry, resolution)
    candidates = [(geometry, whole)]
    if whole.width * whole.height > _MAX_CELLS and geometry.geom_type == "MultiPolygon":
        candidates = [(part, _window(part, resolution)) for part in geometry.geoms]
    if sum(win.width * win.height for _, win in candidates) > _MAX_CELLS:
        raise WindowLimitError("Crop-cover boundary exceeds the raster cell limit at the published resolution")
    windows = [
        (part, _Window(resolution, win.west + x * resolution, win.north - y * resolution,
                       min(_MAX_SIDE, win.width - x), min(_MAX_SIDE, win.height - y)))
        for part, win in candidates
        for y in range(0, win.height, _MAX_SIDE)
        for x in range(0, win.width, _MAX_SIDE)
    ]
    if len(windows) > _MAX_WINDOWS:
        raise WindowLimitError("Crop-cover boundary exceeds the raster window limit at the published resolution")
    return windows


def _validate_storage(page: Any, window: _Window, raw_size: int) -> None:
    if page.is_tiled:
        tile_width, tile_height = page.tilewidth, page.tilelength
        if not (1 <= tile_width <= _MAX_SIDE and 1 <= tile_height <= _MAX_SIDE and page.tiledepth == 1):
            raise RuntimeError("Crop-cover GeoTIFF has unsupported tile dimensions")
        segment_count = math.ceil(window.width / tile_width) * math.ceil(window.height / tile_height)
        sizes = [tile_width * tile_height] * segment_count
    else:
        rows = page.rowsperstrip
        if not 1 <= rows <= _MAX_SIDE:
            raise RuntimeError("Crop-cover GeoTIFF has unsupported strip dimensions")
        sizes = [window.width * min(rows, window.height - y) for y in range(0, window.height, rows)]
    if len(page.dataoffsets) != len(sizes) or len(page.databytecounts) != len(sizes):
        raise RuntimeError("Crop-cover GeoTIFF has an invalid pixel block count")
    for offset, count, size in zip(page.dataoffsets, page.databytecounts, sizes):
        if (offset, count) == (0, 0):
            continue  # The provider uses a sparse block to represent NoData.
        if offset <= 0 or count != size or offset + count > raw_size:
            raise RuntimeError("Crop-cover GeoTIFF contains an invalid or truncated pixel block")


def _decode_export(raw: bytes, window: _Window, crs: int) -> Any:
    """Decode the service's single-band, uncompressed GeoTIFF and its sparse blocks."""
    import numpy as np
    from tifffile import TiffFile

    try:
        with TiffFile(io.BytesIO(raw)) as image:
            if len(image.pages) != 1:
                raise RuntimeError("Crop-cover export must contain one GeoTIFF page")
            page = image.pages[0]
            orientation = page.tags.get(274)
            nodata = page.tags.get(42113)
            if (page.shape != (window.height, window.width) or page.dtype != np.dtype("uint8")
                    or page.samplesperpixel != 1 or page.bitspersample != 8
                    or page.compression != 1 or page.photometric != 1 or page.predictor != 1
                    or page.subifds or 34264 in page.tags or (orientation is not None and orientation.value != 1)
                    or nodata is None or nodata.value != "0"):
                raise RuntimeError("Crop-cover raster does not match the requested unsigned class-code grid")
            geotiff = page.geotiff_tags or {}
            scale = geotiff.get("ModelPixelScale", ())
            tiepoint = geotiff.get("ModelTiepoint", ())
            if (
                geotiff.get("ProjectedCSTypeGeoKey") != crs or geotiff.get("GTRasterTypeGeoKey") != 1
                or len(scale) != 3 or len(tiepoint) != 6 or tuple(tiepoint[:3]) != (0, 0, 0)
                or not all(math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6) for actual, expected in zip(
                    (*scale[:2], *tiepoint[3:5]), (window.resolution, window.resolution, window.west, window.north),
                ))
            ):
                raise RuntimeError("Crop-cover raster does not match the requested CRS and pixel-grid alignment")
            _validate_storage(page, window, len(raw))
            return page.asarray(maxworkers=1)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Crop-cover service did not return a readable raw GeoTIFF") from exc


def _export(service: str, window: _Window, crs: int, year: int, raster_id: int | None, timeout: int) -> bytes:
    parameters = {
        "f": "image", "format": "tiff", "compression": "None", "pixelType": "U8", "noData": 0,
        "bbox": ",".join(map(str, window.bbox)), "bboxSR": crs, "imageSR": crs,
        "size": f"{window.width},{window.height}",
        "interpolation": "RSP_NearestNeighbor", "renderingRule": '{"rasterFunction":"None"}',
    }
    if raster_id is None:
        parameters["mosaicRule"] = '{"where":"Category=1"}'
    else:
        parameters["mosaicRule"] = json.dumps({
            "mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [raster_id], "where": f"Year={year}",
        }, separators=(",", ":"))
    return _read(service, "exportImage", parameters, timeout=timeout, limit=_MAX_EXPORT_BYTES)


def query_crop_cover(
    geometry: Any, *, service: str, crs: int, year: int, resolution: int,
    labels: dict[int, str], no_class_codes: frozenset, timeout: int,
    raster: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import numpy as np
    from affine import Affine

    projected = project_geometry(geometry, crs)
    is_point = projected.geom_type == "Point"
    areas = np.zeros(256, dtype=np.float64)
    receipts = []
    for part, window in _windows(projected, resolution):
        raster_id = raster["object_id"] if raster else None
        raw = _export(service, window, crs, year, raster_id, timeout)
        values = _decode_export(raw, window, crs)
        receipts.append({"bbox": list(window.bbox), "width": window.width, "height": window.height, "sha256": hashlib.sha256(raw).hexdigest()})
        if not is_point:
            grid = Affine(resolution, 0, window.west, 0, -resolution, window.north)
            weights = fractional_weights(part, grid, window.width, window.height, use_all_cells=True)
            areas += np.bincount(values.ravel(), weights=weights.ravel(), minlength=256) * resolution**2

    result = {
        "year": year, "source": service, "analysis_crs": f"EPSG:{crs}", "resolution_m": resolution,
        "method": "containing_raster_pixel" if is_point else "fractional_raster_overlap",
        "resampling": "nearest_neighbor", "raster": raster, "exports": receipts,
    }
    if is_point:
        code = int(values[0, 0])
        label = labels.get(code) if code not in no_class_codes else None
        return {**result, "status": "available" if label else "no_data", "point_class": {"code": code, "label": label} if label else None}

    boundary_area = projected.area
    if not math.isclose(float(areas.sum()), boundary_area, rel_tol=1e-7, abs_tol=1e-6):
        raise RuntimeError("Crop-cover pixel overlap does not close against the field area")
    codes = [int(code) for code in areas.nonzero()[0] if code in labels and code not in no_class_codes]
    codes.sort(key=lambda code: (-areas[code], code))
    classified_area = math.fsum(areas[code] for code in codes)
    missing_area = max(0.0, boundary_area - classified_area)
    if math.isclose(classified_area, boundary_area, rel_tol=1e-9, abs_tol=0):
        missing_area = 0.0
        classified_area = boundary_area
    classes = [
        {"code": code, "label": labels[code], "area_m2": float(areas[code]), "field_fraction": min(float(areas[code]) / boundary_area, 1.0)}
        for code in codes
    ]
    classification = "no_data"
    dominant = None
    if classes:
        leader = classes[0]
        leader_fraction = leader["field_fraction"]
        if leader_fraction > DOMINANT_FRACTION and not math.isclose(leader_fraction, DOMINANT_FRACTION, rel_tol=0, abs_tol=1e-9):
            classification, dominant = "dominant", leader
        elif missing_area and leader_fraction + missing_area / boundary_area > DOMINANT_FRACTION + 1e-9:
            classification = "insufficient_coverage"
        else:
            classification = "mixed"
    return {
        **result, "status": ("partial_available" if missing_area else "available") if classes else "no_data",
        "classification_status": classification, "dominant_class": dominant, "classes": classes,
        "boundary_area_m2": boundary_area, "classified_area_m2": classified_area, "unclassified_area_m2": missing_area,
        "classified_fraction": classified_area / boundary_area,
        "unclassified_codes": [int(code) for code in areas.nonzero()[0] if code in no_class_codes or code not in labels],
    }


def coverage_facts(records: dict[str, Any], limit: int = 3) -> list[str]:
    """Short, bounded facts shared by the chat tool, prompt and answer renderer."""
    facts = []
    for year in sorted(records, reverse=True)[:limit]:
        record = records[year]
        label = (record.get("point_class") or {}).get("label")
        if label:
            facts.append(f"{year}: {label} at the queried point")
            continue
        classified = record.get("classified_fraction")
        if not isinstance(classified, (int, float)) or not classified:
            facts.append(f"{year}: " + {
                "unavailable": "source unavailable", "not_applicable": "outside supported CDL regions",
                "year_unavailable": "no annual raster published for this location",
                "unsupported_geometry": "boundary exceeds this year’s raster query limits",
            }.get(record.get("status"), "no classified cover returned"))
            continue
        descriptions = {
            "dominant": "dominant mapped class", "mixed": "mixed mapped cover",
            "insufficient_coverage": "insufficient coverage to resolve dominance",
        }
        state = descriptions[record["classification_status"]]
        class_shares = ", ".join(f"{item['label']} {item['field_fraction']:.1%}" for item in record["classes"][:3])
        facts.append(f"{year}: {state}. {class_shares} of the boundary. {classified:.1%} classified")
    return facts
