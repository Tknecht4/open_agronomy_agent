"""Frozen discovery, dispatch, source identity and missingness contracts."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest

from agronomy_agent import imagery_selection as selection
from agronomy_agent.geospatial.scene_quality import POLICY_VERSION

GEOMETRY = {"type": "Polygon", "coordinates": [[[-104.99, 40], [-104.989, 40],
    [-104.989, 40.001], [-104.99, 40.001], [-104.99, 40]]]}
POLICY = {"version": POLICY_VERSION, "index": "NDVI", "support": "field", "min_valid_fraction": .8}


def stac(provider=selection.sentinel2.PROVIDER_ID):
    collection = selection.source_definition(provider)["collection"]
    return {"features": [{"id": f"S2B_T13TFE_2022060{i}T170000_L2A" if provider == selection.sentinel2.PROVIDER_ID else f"HLS.S30.T13TFE.202215{i}T170000.v2.0",
        "collection": collection, "properties": {"datetime": f"2022-06-0{i}T17:00:00Z", "eo:cloud_cover": 0}}
        for i in (1, 3, 2)], "links": [{"rel": "next", "href": "https://never-follow.invalid/private"}]}


def make_plan(monkeypatch, provider=selection.sentinel2.PROVIDER_ID, **kwargs):
    calls = []
    def query(url, *, body):
        calls.append((url, body))
        return stac(provider)
    monkeypatch.setattr(selection, '_request_json', query)
    plan = selection.build_selection_plan(GEOMETRY, provider, '2022-06-01', '2022-06-30',
        policy=POLICY, network_mode='online', **kwargs)
    return plan, calls


def fake_receipt(plan, scene_id, *, area=100, **updates):
    request = plan['request']; candidate = next(c for c in plan['candidates'] if c['scene_id'] == scene_id)
    stat = {'area_m2': area, 'mean': .3 if area else None, 'min': .3 if area else None, 'max': .3 if area else None}
    return {'status': 'available', 'request_hash': selection._expected_request(request, scene_id),
        'geometry_hash': request['geometry_hash'], 'provider_id': request['provider_id'],
        'scene_id': scene_id, 'process_version': request['processor_version'], 'process_hash': 'a'*64,
        'chip_hash': selection._hash(scene_id), 'cache_hit': True,
        'source': {'provider_id': request['provider_id'], 'collection': selection.source_definition(request['provider_id'])['collection'],
                   'scene_id': scene_id, 'acquired_at': candidate['acquired_at']},
        'qa': {'field_area_m2': 100, 'valid_area_m2': 100}, 'zonal_stats': {'NDVI': stat}, **updates}


def test_frozen_page_records_scope_and_ignores_next_link(monkeypatch):
    plan, calls = make_plan(monkeypatch)
    assert len(calls) == 1 and calls[0][1]['limit'] == 3
    assert calls[0][1]['sortby'][0]['direction'] == 'desc'
    assert plan['status'] == 'ready' and plan['discovery']['more_results_indicated'] is True
    assert [c['acquired_at'][9] for c in plan['candidates']] == ['3', '2', '1']
    assert 'never-follow' not in json.dumps(plan)
    assert selection.validate_plan(plan) == plan


@pytest.mark.parametrize('provider', selection.PROVIDERS)
def test_provider_dispatch_uses_actual_support_not_latest(monkeypatch, tmp_path, provider):
    plan, _ = make_plan(monkeypatch, provider)
    calls = []
    def processor(geometry, *args, **kwargs):
        sid = args[-1]; calls.append((sid, kwargs))
        return fake_receipt(plan, sid, area=50 if sid == plan['candidates'][0]['scene_id'] else 90)
    module = selection.sentinel2 if provider == selection.sentinel2.PROVIDER_ID else selection.hls
    monkeypatch.setattr(module, 'analyze_sentinel2_scene' if module is selection.sentinel2 else 'analyze_scene', processor)
    result = selection.select_from_plan(plan, cache_root=tmp_path, network_mode='offline')
    assert result['status'] == 'selected'
    assert result['selected_scene_id'] == plan['candidates'][1]['scene_id']
    assert result['rejected_count'] == 1 and len(calls) == 3
    assert all(kw['network_mode'] == 'offline' for _, kw in calls)
    assert result['transfer']['bytes'] == 0
    assert result['receipt_hash'] == selection._hash({k:v for k,v in result.items() if k != 'receipt_hash'})


def test_failure_kept_as_unknown_and_no_replacement(monkeypatch, tmp_path):
    plan, calls = make_plan(monkeypatch)
    failed = plan['candidates'][1]['scene_id']; attempts = []
    def processor(geometry, sid, **kwargs):
        attempts.append(sid)
        return {'status':'blocked_offline'} if sid == failed else fake_receipt(plan,sid)
    monkeypatch.setattr(selection.sentinel2, 'analyze_sentinel2_scene', processor)
    result = selection.select_from_plan(plan, cache_root=tmp_path)
    assert result['status']=='incomplete' and result['selected_scene_id'] is None
    assert result['unavailable_count']==1 and len(result['ranked_scene_ids'])==2
    assert len(calls)==1 and attempts==[c['scene_id'] for c in plan['candidates']]
    assert result['candidates'][1]['assessment']['valid_fraction'] is None


@pytest.mark.parametrize('change', [
    lambda p: p['request'].update(processor_version='future'),
    lambda p: p['request']['geometry']['coordinates'][0][1].__setitem__(0, -104.988),
    lambda p: p['discovery'].update(scope='exhaustive'),
    lambda p: p['discovery'].update(returned_count=True),
    lambda p: p['discovery'].update(more_results_indicated=1),
    lambda p: p['candidates'][0].update(scene_id={}),
    lambda p: p['candidates'].reverse(),
    lambda p: p['candidates'][0].update(acquired_at='2021-06-01T00:00:00Z'),
])
def test_rehashed_contradictory_plan_rejected_before_processing(monkeypatch, tmp_path, change):
    plan, _ = make_plan(monkeypatch); change(plan)
    plan['plan_hash']=selection._hash({k:v for k,v in plan.items() if k!='plan_hash'})
    monkeypatch.setattr(selection.sentinel2,'analyze_sentinel2_scene',lambda *a,**k:pytest.fail('processed invalid plan'))
    with pytest.raises(ValueError): selection.select_from_plan(plan,cache_root=tmp_path)


@pytest.mark.parametrize('key,value', [('geometry_hash','b'*64), ('provider_id','wrong'), ('process_version','old'), ('request_hash','c'*64)])
def test_wrong_receipt_identity_never_selected(monkeypatch, tmp_path, key, value):
    plan,_=make_plan(monkeypatch)
    monkeypatch.setattr(selection.sentinel2,'analyze_sentinel2_scene',lambda geom,sid,**kw:fake_receipt(plan,sid,**{key:value}))
    result=selection.select_from_plan(plan,cache_root=tmp_path)
    assert result['status']=='incomplete' and result['unavailable_count']==3
    assert all(c['assessment']['reason']=='receipt_identity_mismatch' for c in result['candidates'])


def test_discovery_failures_empty_and_offline_remain_distinct(monkeypatch, tmp_path):
    monkeypatch.setattr(selection,'_request_json',lambda *a,**k:pytest.fail('offline egress'))
    blocked=selection.build_selection_plan(GEOMETRY,selection.sentinel2.PROVIDER_ID,'2022-06-01','2022-06-30',policy=POLICY)
    assert selection.select_from_plan(blocked,cache_root=tmp_path)['status']=='blocked_offline'
    for payload,expected in [({'features':[]},'no_scene'),({'features':None},'unavailable'),
        ({'features':[stac()['features'][0]]*2},'unavailable'),({'features':stac()['features']*3},'unavailable')]:
        monkeypatch.setattr(selection,'_request_json',lambda *a,**k:payload)
        plan=selection.build_selection_plan(GEOMETRY,selection.sentinel2.PROVIDER_ID,'2022-06-01','2022-06-30',policy=POLICY,network_mode='online')
        assert plan['status']==expected
        assert selection.select_from_plan(plan,cache_root=tmp_path)['status']==expected


def test_hls_interior_policy_refuses_before_egress(monkeypatch):
    monkeypatch.setattr(selection,'_request_json',lambda *a,**k:pytest.fail('egress'))
    with pytest.raises(ValueError):
        selection.build_selection_plan(GEOMETRY,'hls-s30-planetary-computer','2022-06-01','2022-06-30',policy={**POLICY,'support':'interior'},network_mode='online')


def test_cli_offline_plan_and_exclusive_output(tmp_path):
    geo=tmp_path/'field.json';geo.write_text(json.dumps(GEOMETRY));output=tmp_path/'plan.json'
    command=[sys.executable,'-m','agronomy_agent.imagery_selection_worker','plan','--geometry',str(geo),
        '--provider',selection.sentinel2.PROVIDER_ID,'--start-date','2022-06-01','--end-date','2022-06-30',
        '--index','NDVI','--support','field','--min-valid-fraction','0.8','--output',str(output)]
    run=subprocess.run(command,capture_output=True,text=True)
    assert run.returncode==2 and json.loads(output.read_text())['status']=='blocked_offline'
    original=output.read_bytes()
    repeat=subprocess.run(command+['--online'],capture_output=True,text=True)
    assert repeat.returncode==2 and output.read_bytes()==original
    assert output.stat().st_mode & 0o077 == 0
