"""Application admission for Sentinel-2 C1 products, independently of HLS QA."""
from __future__ import annotations
import hashlib
import json
import math
from typing import Any
from agronomy_agent.geospatial.sentinel2 import PROVIDER_ID, COLLECTION, PROCESS_VERSION
from agronomy_agent.sentinel2_analytics import _request


def request_identity(geometry: dict, payload: dict) -> dict:
    if payload.get('buffer_m', 0) or payload.get('sample_radius_m') is not None or payload.get('sampling_mode') not in (None, 'field_polygon'):
        raise ValueError('Sentinel-2 supports saved single polygons without point or HLS buffer options')
    return _request(geometry, payload.get('scene_id'), payload.get('start_date'), payload.get('end_date'), 60, 20)


def validate_sentinel2_receipt(receipt: dict, *, geometry: dict, provider_id: str | None = None, **_: Any) -> None:
    request = receipt.get('request') or {}
    expected = request_identity(geometry, request)
    source, grid, qa, spec = (receipt.get(key) or {} for key in ('source', 'grid', 'qa', 'process_spec'))
    if (provider_id not in (None, PROVIDER_ID) or receipt.get('provider_id') != PROVIDER_ID
        or source.get('provider_id') != PROVIDER_ID or source.get('collection') != COLLECTION
        or source.get('scene_id') != receipt.get('scene_id')
        or not str(receipt.get('scene_id', '')).startswith(COLLECTION + ':')
        or request != expected['identity'] or receipt.get('request_hash') != expected['request_hash']
        or receipt.get('geometry_hash') != expected['geometry_hash']
        or receipt.get('process_version') != PROCESS_VERSION or receipt.get('source_native_grid') is not False
        or spec.get('version') != PROCESS_VERSION or spec.get('cloud_buffer_m') != 60 or spec.get('edge_buffer_m') != 20
        or spec.get('ndvi_nir_band') != 'B8A' or spec.get('ndmi_nir_band') != 'B8A'
        or receipt.get('process_hash') != hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        or grid.get('resolution_m') != 20
        or any(type(grid.get(k)) is not int or not 1 <= grid[k] <= 256 for k in ('width', 'height'))):
        raise ValueError('Sentinel-2 source, processing or request binding failed')
    def number(value: Any, low: float = 0, high: float = math.inf) -> bool:
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    area, clear, fraction = (qa.get(k) for k in ('field_area_m2', 'valid_area_m2', 'valid_area_fraction'))
    if not number(area, 1e-9, grid['width'] * grid['height'] * 400 + 1e-3) or not number(clear, 0, area) or not number(fraction, 0, 1) or not math.isclose(clear / area, fraction, abs_tol=1e-6):
        raise ValueError('Sentinel-2 field support invalid')
    if receipt.get('status') not in ('available', 'empty_valid_area') or (receipt['status'] == 'empty_valid_area') != (clear == 0):
        raise ValueError('Sentinel-2 status contradicts support')
    tolerance = max(1e-5, area * 1e-6)
    excluded = qa.get('excluded_area_m2_by_reason')
    if not isinstance(excluded, dict) or not excluded or any(not number(v, 0, area + tolerance) for v in excluded.values()) or sum(excluded.values()) < area - clear - tolerance:
        raise ValueError('Sentinel-2 exclusion support invalid')
    for name in ('NDVI', 'NDMI'):
        stats = receipt.get('zonal_stats', {}).get(name, {})
        support = stats.get('area_m2')
        reasons = qa.get('index_undefined_area_m2_by_reason', {}).get(name)
        if not number(support, 0, clear + tolerance) or not isinstance(reasons, dict) or not reasons or any(not number(v, 0, clear + tolerance) for v in reasons.values()) or not math.isclose(support + sum(reasons.values()), clear, abs_tol=tolerance) or not math.isclose(qa.get('index_eligible_area_m2', {}).get(name, -1), support, abs_tol=tolerance):
            raise ValueError('Sentinel-2 index support invalid')
        values = [stats.get(k) for k in ('min', 'mean', 'max')]
        if (support == 0 and any(v is not None for v in values)) or (support > 0 and (not all(number(v, -1.000001, 1.000001) for v in values) or values != sorted(values))):
            raise ValueError('Sentinel-2 index values invalid')
