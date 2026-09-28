import numpy as np
import pytest
from agronomy_agent.imagery_models import prepare_stack, verify_snapshot


def inputs():
    return dict(bands=np.full((4, 6, 8, 9), .2, np.float32), valid_mask=np.ones((4, 8, 9), bool),
                field_mask=np.ones((8, 9), bool), dates=['2020-04-01', '2020-04-15', '2020-05-01', '2020-05-15'],
                latitude=40., longitude=-103., cutoff='2020-06-15', allow_center_padding=True)


def test_normalization_and_missingness_are_distinct():
    x = inputs()
    x['valid_mask'][:, 0, 0] = False
    x['bands'][:, :, 0, 0] = np.nan
    p = prepare_stack(**x)
    assert p['input'].shape == (1, 6, 4, 224, 224)
    assert np.isfinite(p['input']).all()
    assert p['valid_mask'].sum() == 4 * 71
    top, left = p['receipt']['center_padding'][:2]
    assert p['input'][0, 0, 0, top, left] == np.float32(.0001)
    assert p['input'][0, 0, 0, top, left + 1] == pytest.approx((.2-.1087)/.2248)
    assert p['pool_weights'].sum() == pytest.approx(1)
    assert p['receipt']['attention_mask_supported'] is False


@pytest.mark.parametrize('change,match', [
    ({'allow_center_padding': False}, 'explicit_center_padding'),
    ({'dates': ['2020-04-01']*4}, 'four_unique'),
    ({'cutoff': '2020-05-01'}, 'at_or_before_cutoff'),
    ({'latitude': float('nan')}, 'latitude'),
    ({'band_names': ['red']*6}, 'band_order'),
    ({'valid_mask': np.zeros((4, 8, 9), bool)}, 'no_valid_field'),
    ({'bands': np.full((4, 6, 8, 9), np.nan)}, 'nonfinite'),
    ({'bands': np.full((4, 6, 8, 9), 2000)}, 'reflectance'),
])
def test_unsupported_inputs_fail(change, match):
    x = inputs(); x.update(change)
    with pytest.raises(ValueError, match=match):
        prepare_stack(**x)


def test_modified_code_rejected_before_import(tmp_path):
    (tmp_path/'prithvi_mae.py').write_text('raise RuntimeError("must not run")')
    with pytest.raises(ValueError, match='hash_mismatch'):
        verify_snapshot(tmp_path)


def write_chip_set(tmp_path):
    import json
    manifest = {'chips': [], 'latitude': 40., 'longitude': -103., 'cutoff': '2020-06-15', 'bundle_id': 'fixture-only'}
    for i, date in enumerate(inputs()['dates']):
        meta = {'band_names': ['Blue','Green','Red','NarrowNIR','SWIR1','SWIR2'], 'resolution_m':30,
                'crs':'EPSG:32613', 'transform':[30,0,600000,0,-30,4400000],
                'source':{'acquired_at':date+'T12:00:00Z','scene_id':f'fixture-{i}'}}
        path = tmp_path/f'{i}.npz'
        np.savez_compressed(path, bands=inputs()['bands'][i], valid_mask=inputs()['valid_mask'][i],
                            field_mask=inputs()['field_mask'], metadata_json=json.dumps(meta))
        manifest['chips'].append({'path':path.name, 'date':date})
    path = tmp_path/'manifest.json'; path.write_text(json.dumps(manifest))
    return path, manifest


def test_chip_lineage_and_sensitivity_are_retained(tmp_path):
    pytest.importorskip('pyproj', reason='optional EO environment')
    from agronomy_agent.imagery_models import load_chip_manifest
    path, _ = write_chip_set(tmp_path)
    p = load_chip_manifest(path, allow_center_padding=True)
    assert len(p['receipt']['source_files']) == 4
    assert len(p['receipt']['source_files'][0]['sha256']) == 64
    assert p['receipt']['spatial_regime'] == 'nodata_padding_sensitivity_only'
    assert p['receipt']['source_files'][0]['scene_id'] == 'fixture-0'
    assert p['receipt']['location_source'] == 'native_raster_center_transformed_to_epsg4326'
    assert p['location_coords'][0, 0] != 40.  # caller coordinates cannot override the grid


def test_chip_date_spoof_is_rejected(tmp_path):
    import json
    from agronomy_agent.imagery_models import load_chip_manifest
    path, manifest = write_chip_set(tmp_path)
    manifest['chips'][0]['date'] = '2020-03-01'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='does_not_match_acquisition'):
        load_chip_manifest(path, allow_center_padding=True)


def test_grid_change_is_rejected(tmp_path):
    import json
    from agronomy_agent.imagery_models import load_chip_manifest
    path, _ = write_chip_set(tmp_path)
    chip = tmp_path/'1.npz'
    with np.load(chip, allow_pickle=False) as data:
        fields = dict(data)
    meta = json.loads(str(fields['metadata_json'].item())); meta['transform'][2] += 30
    fields['metadata_json'] = json.dumps(meta)
    np.savez_compressed(chip, **fields)
    with pytest.raises(ValueError, match='share_native_grid'):
        load_chip_manifest(path, allow_center_padding=True)


def test_shared_context_pooling_uses_roi_and_preserves_token_alias():
    from agronomy_agent.imagery_models import pool_shared_context
    tokens = np.repeat(np.arange(784, dtype=np.float32)[:, None], 192, axis=1)
    valid = np.ones((4,224,224),bool)
    left = np.zeros((224,224),bool); left[0,0] = True
    alias = np.zeros((224,224),bool); alias[1,1] = True
    right = np.zeros((224,224),bool); right[0,16] = True
    a, ar = pool_shared_context(tokens,valid,left)
    b, br = pool_shared_context(tokens,valid,alias)
    c, cr = pool_shared_context(tokens,valid,right)
    np.testing.assert_array_equal(a,b)
    np.testing.assert_allclose(c,a+1)
    assert ar['field_mask_sha256'] != br['field_mask_sha256']
    assert ar['token_support_counts_sha256'] == br['token_support_counts_sha256']
    assert ar['normalized_pool_weights_sha256'] == br['normalized_pool_weights_sha256']
    assert ar['supported_token_indices'] == br['supported_token_indices']
    assert ar['token_support_counts_sha256'] != cr['token_support_counts_sha256']


def test_sampled_support_mask_is_local_and_not_full_context():
    for package in ('affine','pyproj','rasterio','shapely'):
        pytest.importorskip(package, reason='optional EO environment')
    from agronomy_agent.imagery_models import sampled_support_mask
    grid = [[30,0,600000,0,-30,4400000], 'EPSG:32613']
    points = [[603300,4396700],[603450,4396700],[603450,4396550],[603300,4396550]]
    mask = sampled_support_mask(points, grid)
    assert mask.dtype == np.bool_ and mask.shape == (224,224)
    assert 25 <= mask.sum() < 100
    with pytest.raises(ValueError, match='outside_shared_context'):
        sampled_support_mask([[0,0],[100,0],[100,100]], grid)


def test_cohort_retains_missing_and_rejects_unverified_native_grid(tmp_path, monkeypatch):
    import json
    import agronomy_agent.imagery_models as m
    class Model:
        identity = {'model_id':'fixture'}
        def __init__(self,*args): pass
        def encode_tokens(self,*args): raise AssertionError('must reject before inference')
    monkeypatch.setattr(m,'FrozenPrithvi',Model)
    import importlib.metadata
    monkeypatch.setattr(importlib.metadata,'version',lambda name:'fixture')
    monkeypatch.setattr(m,'load_chip_manifest',lambda path: {'receipt': {
        'dates':['2020-05-01','2020-05-10','2020-05-20','2020-06-01'],
        'spatial_regime':'actual_context_no_padding','source_native_grid':False,'process_versions':[None]*4}})
    protocol = {'protocol_id':'fixture','bundles':[{'bundle_id':'unit-2020','year':2020}, {'bundle_id':'unit-2021','year':2021}]}
    pp=tmp_path/'protocol.json'; pp.write_text(json.dumps(protocol))
    cp=tmp_path/'contexts.json'; cp.write_text(json.dumps({'label_protocol_id':'fixture','contexts':[{'year':2020,'manifest':'unused.json'}]}))
    result=m.extract_cohort_features(pp,cp,tmp_path)
    assert len(result['rows']) == 2
    assert 'requires_verified_v2' in result['rows'][0]['error']
    assert result['rows'][1]['error'] == 'missing_shared_context_year'


def test_declared_chip_hash_mismatch_is_rejected(tmp_path):
    import json
    from agronomy_agent.imagery_models import load_chip_manifest
    path, manifest = write_chip_set(tmp_path)
    manifest['chips'][0]['sha256'] = '0'*64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='declared_sha256_mismatch'):
        load_chip_manifest(path, allow_center_padding=True)


KNOWN_HLS_WKT = 'PROJCS["UTM Zone 13, Northern Hemisphere",GEOGCS["Unknown datum based upon the WGS 84 ellipsoid",DATUM["Not specified (based on WGS 84 spheroid)",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-105],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'


def test_qualified_hls_crs_lattice_retains_unresolved_datum():
    pytest.importorskip('pyproj', reason='optional EO environment')
    from agronomy_agent.imagery_models import compare_hls_grid_crs
    from copy import deepcopy
    a={'crs':'EPSG:32613','process_version':'hls-chip-v2-native-asset-grid-fmask-v1','source_native_grid':True,
       'source':{'collection':'hls2-s30','scene_id':'hls2-s30:HLS.S30.T13TFE.2020150T173909.v2.0'}}
    b=deepcopy(a); b['crs']=KNOWN_HLS_WKT
    receipt=compare_hls_grid_crs(a,b)
    assert receipt['formal_crs_equal'] is False
    assert receipt['resampling_performed'] is False
    assert receipt['status']=='qualified_hls_same_numeric_utm13_lattice'
    assert receipt['candidate_crs']==KNOWN_HLS_WKT
    assert receipt['proj_accuracy_metres']==-1
    for crs in ('EPSG:26913','EPSG:32612'):
        wrong=deepcopy(b); wrong['crs']=crs
        with pytest.raises(ValueError,match='unqualified_crs_difference'):
            compare_hls_grid_crs(a,wrong)
    wrong=deepcopy(b); wrong['source']['scene_id']=wrong['source']['scene_id'].replace('T13TFE','T13TFF')
    with pytest.raises(ValueError,match='different_mgrs_tiles'):
        compare_hls_grid_crs(a,wrong)
    for altered in (KNOWN_HLS_WKT.replace('6378137','6378138'),
                    KNOWN_HLS_WKT.replace('UNIT["metre",1','UNIT["foot",0.3048'),
                    KNOWN_HLS_WKT.replace('UTM Zone 13','Different name Zone 13')):
        wrong=deepcopy(b); wrong['crs']=altered
        with pytest.raises(ValueError,match='chips_do_not_share_native_grid'):
            compare_hls_grid_crs(a,wrong)
    wrong=deepcopy(b); wrong['process_version']='hls-chip-v1'
    with pytest.raises(ValueError,match='unqualified_hls_product'):
        compare_hls_grid_crs(a,wrong)
    wrong=deepcopy(b); wrong['source_native_grid']=False
    with pytest.raises(ValueError,match='unqualified_hls_product'):
        compare_hls_grid_crs(a,wrong)
    geographic=deepcopy(a);geographic['crs']='EPSG:4326'
    with pytest.raises(ValueError,match='requires_projected_metre_axes'):
        compare_hls_grid_crs(geographic,geographic)
