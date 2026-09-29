"""Sentinel-2 operator orchestration, identity and immutable-cache contracts."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from agronomy_agent import sentinel2_analytics as analytics

SCENE = "sentinel-2-c1-l2a:S2B_T13TEE_20220714T000000_L2A"
GEOMETRY = {"type": "Polygon", "coordinates": [[[-104.99, 40.0], [-104.989, 40.0],
             [-104.989, 40.001], [-104.99, 40.001], [-104.99, 40.0]]]}


@pytest.fixture
def pipeline(monkeypatch):
    calls = []
    item = {"id": SCENE, "collection": analytics.COLLECTION, "acquired_at": "2022-07-14T00:00:00Z",
            "availability_at": "2024-01-01T00:00:00Z", "scene_cloud_percent": 4,
            "baseline": "05.13", "sun_zenith_deg": 35,
            "product_uri": "S2B_MSIL2A_20220714T000000_N0513_R000_T13TEE_20260922T000000.SAFE",
            "processing_generation": "baseline_recorded_not_inferred",
            "assets": {"red": {"id": SCENE + ":red", "href": "https://example.invalid/red.tif"}}}
    def request(url, *, body):
        calls.append(body)
        return {"features": [item]}
    monkeypatch.setattr(analytics, "_request_json", request)
    monkeypatch.setattr(analytics, "validate_item", lambda value: value)
    @contextmanager
    def local(hrefs):
        yield hrefs, {"bytes": 100, "requests": 2}
    monkeypatch.setattr(analytics, "bounded_cog_proxy", local)
    def prepare(item, hrefs, geometry, **kwargs):
        a = np.ones((2, 2), dtype=np.float64)
        stat = {"mean": 0.5, "min": 0.5, "max": 0.5, "area_m2": 1600.0}
        return {"arrays": {"bands": np.stack([a] * 6), "ndvi": a * 0.5, "ndmi": a * 0.5,
                           "valid_mask": a.astype(bool), "field_weights": a, "field_mask": a.astype(bool),
                           "scl": (a * 4).astype(np.uint8), "raw_dn_red": (a * 2000).astype(np.uint16)},
                "grid": {"resolution_m": 20, "width": 2, "height": 2},
                "source_band_metadata": {"red": {"scale": 0.0001, "offset": -0.1}},
                "qa": {"field_area_m2": 1600.0, "valid_area_m2": 1600.0, "valid_area_fraction": 1.0},
                "zonal_stats": {"NDVI": stat, "NDMI": stat}, "interior_zonal_stats": {"NDVI": stat, "NDMI": stat},
                "process_spec": {"version": analytics.PROCESS_VERSION, **kwargs}, "limitations": ["synthetic fixture"]}
    monkeypatch.setattr(analytics, "prepare_scene", prepare)
    return calls, item


def run(tmp_path, **kwargs):
    return analytics.analyze_sentinel2_scene(GEOMETRY, SCENE, cache_root=tmp_path / 'cache',
        network_mode='online', min_free_bytes=0, **kwargs)


def test_exact_offline_reuse_and_parameter_identity(tmp_path, pipeline):
    receipt = run(tmp_path)
    assert receipt['status'] == 'available' and not receipt['cache_hit']
    assert receipt['process_version'] == analytics.PROCESS_VERSION
    assert receipt['source_native_grid'] is False
    for key in ('product_uri', 'processing_generation'):
        assert receipt['source'][key] == pipeline[1][key]
    assert receipt['cog_transfer_bytes'] == 100
    offline = analytics.analyze_sentinel2_scene(GEOMETRY, SCENE, cache_root=tmp_path / 'cache')
    assert offline['cache_hit'] and offline['chip_hash'] == receipt['chip_hash']
    assert len(pipeline[0]) == 1
    for options in ({'edge_buffer_m': 21}, {'cloud_buffer_m': 80}):
        miss = analytics.analyze_sentinel2_scene(GEOMETRY, SCENE, cache_root=tmp_path / 'cache', **options)
        assert miss['status'] == 'blocked_offline'
    with np.load(tmp_path / 'cache' / receipt['cache_files']['npz'], allow_pickle=False) as chip:
        assert chip['raw_dn_red'].dtype == np.uint16
        metadata = json.loads(str(chip['metadata_json']))
        assert metadata['source']['band_metadata']['red']['offset'] == -0.1
        assert metadata['array_manifest'] == receipt['array_manifest']
        for key in ('product_uri', 'processing_generation'):
            assert metadata['source'][key] == pipeline[1][key]
    assert offline['source'] == receipt['source']
    assert receipt['source']['asset_hrefs'] == {k: v['href'] for k, v in pipeline[1]['assets'].items()}
    assert metadata['admitted_source_item'] == pipeline[1]
    assert analytics._hash(metadata['admitted_source_item']) == receipt['source']['item_metadata_sha256']


def test_corrupt_artifact_cannot_satisfy_offline(tmp_path, pipeline):
    receipt = run(tmp_path)
    (tmp_path / 'cache' / receipt['cache_files']['npz']).write_bytes(b'corrupt')
    result = analytics.analyze_sentinel2_scene(GEOMETRY, SCENE, cache_root=tmp_path / 'cache')
    assert result['status'] == 'blocked_offline' and len(pipeline[0]) == 1


def test_offline_miss_does_not_create_cache_or_fetch(tmp_path, pipeline):
    result = analytics.analyze_sentinel2_scene(GEOMETRY, SCENE, cache_root=tmp_path / 'cache')
    assert result['status'] == 'blocked_offline' and not pipeline[0]
    assert not (tmp_path / 'cache').exists()


def test_storage_refusal_precedes_egress(tmp_path, pipeline):
    result = run(tmp_path, max_cache_bytes=1)
    assert result['status'] == 'storage_limit' and not pipeline[0]


@pytest.mark.parametrize('kw', [{'cloud_buffer_m': 1}, {'cloud_buffer_m': True},
    {'cloud_buffer_m': 220}, {'edge_buffer_m': -1}, {'edge_buffer_m': float('nan')}])
def test_invalid_parameters_fail_before_egress(tmp_path, pipeline, kw):
    with pytest.raises(ValueError):
        run(tmp_path, **kw)
    assert not pipeline[0]


def test_point_is_not_promoted_to_a_field(tmp_path, pipeline):
    with pytest.raises(ValueError):
        analytics.analyze_sentinel2_scene({'type': 'Point', 'coordinates': [-105, 40]}, SCENE,
                                          cache_root=tmp_path / 'cache')
    assert not pipeline[0]


def test_exact_scene_and_date_response_constraints(tmp_path, pipeline):
    calls, item = pipeline
    result = run(tmp_path, start_date='2022-08-01', end_date='2022-08-31')
    assert result['status'] == 'unavailable'
    assert calls[0]['ids'] == [SCENE.split(':')[1]]
    assert 'datetime' in calls[0]
    item['id'] = analytics.COLLECTION + ':different-item'
    assert run(tmp_path)['status'] == 'unavailable'


def test_no_scene_is_retained_without_fallback(tmp_path, pipeline, monkeypatch):
    requests = []
    def empty(*args, **kwargs):
        requests.append(kwargs)
        return {'features': []}
    monkeypatch.setattr(analytics, '_request_json', empty)
    result = run(tmp_path)
    assert result['status'] == 'no_scene' and len(requests) == 1


def test_object_array_cannot_be_published():
    with pytest.raises(ValueError):
        analytics._array_identity({'bad': np.array([{}], dtype=object)})


def test_cli_offline_and_sensor_option_boundaries(tmp_path):
    geometry = tmp_path / 'field.json'
    geometry.write_text(json.dumps(GEOMETRY))
    base = [sys.executable, '-m', 'agronomy_agent.imagery_worker', '--geometry', str(geometry),
            '--provider', analytics.PROVIDER_ID, '--scene-id', SCENE, '--cache-root', str(tmp_path / 'cache')]
    result = subprocess.run(base, capture_output=True, text=True)
    assert result.returncode == 2 and json.loads(result.stdout)['status'] == 'blocked_offline'
    result = subprocess.run(base + ['--sampling-mode', 'point_pixel'], capture_output=True, text=True)
    assert result.returncode == 2 and 'currently supports field polygons' in result.stderr
    result = subprocess.run([sys.executable, '-m', 'agronomy_agent.imagery_worker', '--geometry', str(geometry),
        '--provider', 'hls-s30-planetary-computer', '--scene-id', 'hls2-s30:test',
        '--cache-root', str(tmp_path/'cache'), '--cloud-buffer-m', '0'], capture_output=True, text=True)
    assert result.returncode == 2 and 'specific to Sentinel-2' in result.stderr


def test_scientific_refusal_is_explicit_and_never_echoes_url(tmp_path, pipeline, monkeypatch):
    def refused(*args, **kwargs):
        raise analytics.Sentinel2Refusal("solar_zenith_exceeds_limit")
    monkeypatch.setattr(analytics, "prepare_scene", refused)
    result = run(tmp_path)
    assert result["status"] == "unavailable" and result["reason"] == "solar_zenith_exceeds_limit"
    assert "https://" not in json.dumps(result)
