"""Real raster -> publication -> frozen selection -> offline integrity seam."""
from contextlib import contextmanager
from copy import deepcopy
import json

import numpy as np
import pytest
pytest.importorskip('rasterio')
pytest.importorskip('pyproj')

from test_sentinel2_preprocessing import raw_item, tiffs, geom_for_cells
from agronomy_agent import imagery_selection as selection
from agronomy_agent import sentinel2_analytics as analytics
from agronomy_agent.geospatial.scene_quality import POLICY_VERSION


def test_actual_rasters_choose_coverage_preserve_policy_and_replay_offline(monkeypatch,tmp_path):
    items=[];local={}
    for day in (7,8,9):
        item=raw_item();old=item['id'];new=old.replace('20240407',f'2024040{day}')
        item['id']=new;item['properties']['datetime']=f'2024-04-0{day}T01:24:10Z'
        for asset in item['assets'].values(): asset['href']=asset['href'].replace(old,new)
        items.append(item)
        folder=tmp_path/str(day);folder.mkdir()
        arrays={}
        if day==9:
            scl=np.full((6,6),4,dtype=np.uint8);scl[2,2]=9;arrays['scl']=scl
        if day==7: arrays['nir08']=np.full((6,6),10000,dtype=np.uint16)
        local[new]=tiffs(folder,arrays)
    monkeypatch.setattr(selection,'_request_json',lambda *a,**k:{'features':items})
    policy={'version':POLICY_VERSION,'index':'NDVI','support':'field','min_valid_fraction':.9}
    plan=selection.build_selection_plan(geom_for_cells(),analytics.PROVIDER_ID,'2024-04-01','2024-04-30',
        policy=policy,processing={'cloud_buffer_m':0,'edge_buffer_m':0},network_mode='online')
    requests=[]
    def source(url,*,body):
        requests.append(body);return {'features':[next(i for i in items if i['id']==body['ids'][0])]}
    monkeypatch.setattr(analytics,'_request_json',source)
    @contextmanager
    def proxy(hrefs):
        identity=next(key for key in local if '/'+key+'/' in hrefs['red'])
        yield local[identity],{'bytes':0,'requests':0}
    monkeypatch.setattr(analytics,'bounded_cog_proxy',proxy)
    cache=tmp_path/'cache'
    result=selection.select_from_plan(plan,cache_root=cache,network_mode='online',min_free_bytes=0)
    assert result['status']=='selected' and '20240408' in result['selected_scene_id']
    assert result['rejected_count']==1 and len(requests)==3
    # A larger NDVI in the older scene cannot win over equal coverage plus recency.
    winner=next(c for c in result['candidates'] if c['scene_id']==result['selected_scene_id'])
    monkeypatch.setattr(analytics,'_request_json',lambda *a,**k:pytest.fail('offline source fetch'))
    monkeypatch.setattr(selection,'_request_json',lambda *a,**k:pytest.fail('offline discovery'))
    repeated=selection.select_from_plan(plan,cache_root=cache)
    assert repeated['status']=='selected' and repeated['decision_hash']==result['decision_hash']
    assert all(c['cache_hit'] for c in repeated['candidates'])
    (cache/(winner['chip_hash']+'.npz')).write_bytes(b'corrupt')
    incomplete=selection.select_from_plan(plan,cache_root=cache)
    assert incomplete['status']=='incomplete' and incomplete['selected_scene_id'] is None
    assert incomplete['unavailable_count']==1 and len(incomplete['ranked_scene_ids'])==1
