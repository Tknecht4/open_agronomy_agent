"""Synthetic fixtures only: label isolation, folds, cutoff and failures."""
import copy
import pytest
from agronomy_agent.imagery_assessment import aggregate, assess, build_protocol, load_source, source_features, validate_features


@pytest.fixture
def rows():
    result = []
    for i, field in enumerate(['A', 'B', 'C', 'S2']):
        for j, crop in enumerate(['Wheat', 'Corn', 'Millet']):
            for sample in range(2):
                result.append({'field': field, 'year': str(2020+j), 'crop': crop,
                               'yield_kg_ha': str(100+i*10+j*100+sample*20),
                               'easting_UTM13N': str(650000+i*50+sample),
                               'northing_UTM13N': str(4400000+i*20+sample),
                               'sand_percent': str(30+i+sample), 'carbon_percent': str(1+i/10)})
    return result


def test_excludes_all_years_and_label_free_protocol(rows):
    protocol = build_protocol(rows)
    assert protocol['eligible_raw_rows'] == 18
    assert protocol['field_seasons'] == 9
    assert protocol['physical_units'] == ['A', 'B', 'C']
    assert not any('yield_kg_ha' in b or 'crop' in b for b in protocol['bundles'])
    for fold in protocol['folds']:
        assert set(fold['test_units']).isdisjoint(fold['train_units'])


def test_sample_mean_and_moisture_are_not_field_yield(rows):
    bundles = aggregate(rows)
    assert bundles[0]['yield_kg_ha'] == 110
    assert bundles[0]['sample_count'] == 2
    assert build_protocol(rows)['moisture_percent'] == {'Wheat':12.5,'Corn':15.5,'Millet':12.0}


def test_source_pin_rejects_substitution(tmp_path):
    source = tmp_path/'labels.csv'
    source.write_text('not_the_raw_source')
    with pytest.raises(ValueError, match='SHA-256'):
        load_source(source)


def test_duplicate_unknown_features_fail_closed(rows):
    protocol = build_protocol(rows)
    features = source_features(rows, protocol)
    features['rows'].append(features['rows'][0])
    with pytest.raises(ValueError, match='Duplicate'):
        validate_features(features, protocol)
    features['rows'][-1] = {'bundle_id': 'akron-S2-2020'}
    with pytest.raises(ValueError, match='unknown'):
        validate_features(features, protocol)


def test_missing_nonfinite_future_preserved(rows):
    protocol = build_protocol(rows)
    features = source_features(rows, protocol)
    a, b, c = [r['bundle_id'] for r in features['rows'][:3]]
    features['rows'][0]['features'][0] = float('nan')
    features['rows'][1]['acquisition_max_date'] = '2099-07-01'
    del features['rows'][2]
    vectors, failures = validate_features(features, protocol)
    assert failures[a] == 'invalid_vector'
    assert failures[b] == 'post_cutoff'
    assert failures[c] == 'missing_feature_row'
    assert len(vectors) == 6


def test_all_folds_and_training_only_baseline(rows):
    protocol = build_protocol(rows)
    result = assess(rows, protocol, source_features(rows, protocol))
    assert result['baseline']['crop']['eligible'] == 9
    assert result['features']['crop']['predicted'] == 9
    for prediction in result['predictions']:
        field = prediction['physical_unit']
        assert all(f'akron-{field}-' not in key for key in prediction['train_bundle_ids'])
    assert set(result['features']['yield_by_crop']) == {'Wheat','Corn','Millet'}
    changed = copy.deepcopy(rows)
    for row in changed:
        if row['field'] == 'A':
            row['yield_kg_ha'] = '99999'
    second = assess(changed, protocol, source_features(changed, protocol))
    first_a = [p['baseline']['yield_kg_ha'] for p in result['predictions'] if p['physical_unit']=='A']
    second_a = [p['baseline']['yield_kg_ha'] for p in second['predictions'] if p['physical_unit']=='A']
    assert first_a == second_a


def test_all_failures_still_have_full_denominator(rows):
    result = assess(rows, build_protocol(rows))
    assert result['features']['crop'] == {'eligible':9,'predicted':0,'failed':9}
    assert len(result['predictions']) == 9
    assert len(result['feature_failures']) == 9


def test_protocol_identity_and_dimension(rows):
    protocol = build_protocol(rows)
    features = source_features(rows, protocol)
    features['protocol_id'] = 'wrong'
    with pytest.raises(ValueError, match='protocol_id'):
        validate_features(features, protocol)
    features['protocol_id'] = protocol['protocol_id']
    features['dimension'] = 0
    with pytest.raises(ValueError, match='dimension'):
        validate_features(features, protocol)


def test_forward_year_has_no_future_training(rows):
    protocol = build_protocol(rows)
    result = assess(rows, protocol, source_features(rows, protocol), forward_year=True)
    assert len(result['predictions']) == 3
    assert all(not key.endswith('-2022') for p in result['predictions'] for key in p['train_bundle_ids'])
    assert result['features']['yield_by_crop']['Millet']['failed'] == 3


def test_location_time_features_are_declared_control(rows):
    protocol = build_protocol(rows)
    features = source_features(rows, protocol, location_time=True)
    assert features['dimension'] == 3
    assert features['feature_set_id'] == 'location_time_control'
    assert features['rows'][0]['features'][-1] == 2020


def test_assessment_retains_nonfinite_input_failure(rows):
    protocol = build_protocol(rows)
    features = source_features(rows, protocol)
    features['rows'][0]['features'][0] = float('nan')
    result = assess(rows, protocol, features)
    assert result['features']['crop']['failed'] == 1
    assert result['features']['crop']['eligible'] == 9


def test_future_source_columns_are_not_feature_admitted(rows):
    protocol = build_protocol(rows)
    features = source_features(rows, protocol)
    features['provenance']['columns'] = ['P_summer_mm']
    with pytest.raises(ValueError, match='Forbidden'):
        validate_features(features, protocol)


def test_spectral_vector_masks_indices_and_date_order():
    import numpy as np
    from agronomy_agent.imagery_assessment import spectral_vector
    x=np.empty((4,6,2,2), dtype=float)
    for i in range(4):
        x[i] = np.array([.1,.2,.2,.6,.3,.2])[:,None,None]*(i+1)
    valid=np.ones((4,2,2),dtype=bool)
    field=np.zeros((2,2),dtype=bool);field[0,0]=True
    x[:,:,-1,-1]=float('nan')
    vector,receipt=spectral_vector(x,valid,field)
    assert len(vector)==32
    assert vector[6]==pytest.approx(.5)
    assert vector[7]==pytest.approx(1/3)
    assert vector[8]==pytest.approx(.2)
    assert receipt['field_valid_pixel_counts']==[1,1,1,1]
    valid[1,0,0]=False
    with pytest.raises(ValueError,match='no_valid_field'):
        spectral_vector(x,valid,field)


def test_spectral_no_ratio_support_is_failure():
    import numpy as np
    from agronomy_agent.imagery_assessment import spectral_vector
    with pytest.raises(ValueError,match='no_valid_ndvi'):
        spectral_vector(np.zeros((4,6,1,1)),np.ones((4,1,1),dtype=bool),np.ones((1,1),dtype=bool))


def _paired_fixture(rows):
    from agronomy_agent.imagery_assessment import source_features
    protocol=build_protocol(rows)
    a=source_features(rows,protocol)
    for r in a['rows']:
        r['pooling']={'field_mask_sha256':'1'*64,'valid_mask_sha256':'2'*64}
    b=copy.deepcopy(a);b['feature_set_id']='synthetic_encoder'
    return protocol,a,b


def test_common_comparison_excludes_failed_training_and_retains_denominator(rows):
    from agronomy_agent.imagery_assessment import compare_features
    protocol,a,b=_paired_fixture(rows)
    key=b['rows'][0]['bundle_id']
    b['rows'][0].update(status='error',error='no_valid_field')
    result=compare_features(rows,protocol,a,b)
    assert result['eligible']==9 and result['common_success']==8 and result['failed']==1
    for lane in result['lanes'].values():
        group=lane['physical_group']
        assert group['features']['crop']['eligible']==9
        assert group['common_case_metrics']['features']['crop']['eligible']==8
        assert all(key not in p['train_bundle_ids'] for p in group['predictions'])


def test_common_comparison_rejects_different_dates_and_support(rows):
    from agronomy_agent.imagery_assessment import compare_features
    protocol,a,b=_paired_fixture(rows)
    b['rows'][0]['source_sha256']='a'*64
    b['rows'][1]['pooling']['field_mask_sha256']='b'*64
    result=compare_features(rows,protocol,a,b)
    assert result['common_success']==7
    assert result['dispositions'][0]['failures']['comparison']=='source_or_acquisition_mismatch'
    assert result['dispositions'][1]['failures']['comparison']=='support_or_qa_mask_mismatch'


def test_spectral_context_hash_failure_retains_all_bundles(rows,tmp_path):
    import json
    import numpy as np
    from agronomy_agent.imagery_assessment import extract_spectral_features
    protocol=build_protocol(rows)
    protocol_path=tmp_path/'protocol.json';protocol_path.write_text(json.dumps(protocol))
    chip=tmp_path/'chip.npz';np.savez(chip,bands=np.ones((6,2,2)))
    manifest=tmp_path/'2020.json'
    manifest.write_text(json.dumps({'label_protocol_id':protocol['protocol_id'],'chips':[{'path':'chip.npz','sha256':'0'*64}]}))
    contexts=tmp_path/'contexts.json';contexts.write_text(json.dumps({'contexts':[{'year':2020,'manifest':'2020.json'}]}))
    result=extract_spectral_features(protocol_path,contexts)
    assert len(result['rows'])==9
    assert all(r['status']=='error' for r in result['rows'])
    assert 'sha256_mismatch' in result['rows'][0]['error']
    assert result['rows'][1]['error']=='missing_shared_context_year'
