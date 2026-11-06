"""Sentinel-2 application binding is independent of HLS and fails closed."""
from copy import deepcopy
import hashlib
import json
import pytest
from test_sentinel2_analytics import pipeline, GEOMETRY, SCENE, run
from agronomy_agent import sentinel2_analytics as analytics
from agronomy_agent.sentinel2_receipts import validate_sentinel2_receipt, request_identity
from agronomy_agent.server.services import imagery_service


def test_validated_sentinel_cache_preview_and_rejected_support(tmp_path, pipeline, monkeypatch):
    prepare = analytics.prepare_scene
    def prepared(*args, **kwargs):
        value = prepare(*args, **kwargs)
        value['qa'].update(excluded_area_m2_by_reason={'scl_cloud': 0}, index_eligible_area_m2={'NDVI':1600.,'NDMI':1600.}, index_undefined_area_m2_by_reason={n:{'negative_reflectance':0.,'nonpositive_denominator':0.} for n in ('NDVI','NDMI')})
        value['process_spec'].update(ndvi_nir_band='B8A', ndmi_nir_band='B8A')
        return value
    monkeypatch.setattr(analytics,'prepare_scene',prepared)
    receipt = run(tmp_path)
    validate_sentinel2_receipt(receipt, geometry=GEOMETRY)
    imagery_service.validate_receipt(receipt, geometry=GEOMETRY)
    for key, bad in [('source_native_grid',True), ('geometry_hash','0'*64), ('process_version','hls-chip-v4-hls-radiometry-index-qa')]:
        altered = {**receipt,key:bad}
        with pytest.raises(ValueError): validate_sentinel2_receipt(altered,geometry=GEOMETRY)
    changed = deepcopy(receipt); changed['zonal_stats']['NDVI']['area_m2'] = 0
    with pytest.raises(ValueError): validate_sentinel2_receipt(changed,geometry=GEOMETRY)
    changed = deepcopy(receipt); changed['request']['cloud_buffer_m']=0
    with pytest.raises(ValueError): validate_sentinel2_receipt(changed,geometry=GEOMETRY)
    with pytest.raises(ValueError): request_identity({'type':'Point','coordinates':[-105,40]}, {'scene_id':SCENE})
    with pytest.raises(ValueError): request_identity(GEOMETRY, {'scene_id':SCENE,'sample_radius_m':30})
