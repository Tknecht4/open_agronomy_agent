"""Offline source-pinned assessment. Raw labels and model outputs never enter retrieval."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

SOURCE_SHA256 = 'a1599b9c523f4ed44efd9b7f0c3ba6baf9f263f7c274415c77b4eb81d623f38b'
EXCLUDED_FIELDS = frozenset({'S2', 'S3', 'S4', 'S5', 'S6', 'S7'})
MOISTURE_PERCENT = {'Wheat': 12.5, 'Corn': 15.5, 'Millet': 12.0}
LIMITATION = ('Exploratory one-farm assessment, 12 physical groups; adjacent units and imagery contexts remain dependent. '
              'Physical label-group holdout is not spatially disjoint imagery holdout. No external-farm generalization '
              'or agronomic validation. Targets are sample-location means, never whole-field harvest yields.')


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load_source(path: Path) -> list[dict[str, str]]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('Source SHA-256 mismatch; do not substitute evaluation answers')
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def aggregate(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row['field'] not in EXCLUDED_FIELDS:
            grouped[(row['field'], int(row['year']))].append(row)
    result = []
    for (field, year), samples in sorted(grouped.items()):
        crops = {r['crop'] for r in samples}
        if len(crops) != 1 or not crops <= MOISTURE_PERCENT.keys():
            raise ValueError('Each field-season must have one supported crop')
        values = [float(r['yield_kg_ha']) for r in samples]
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('Nonfinite or negative source yield')
        result.append({'bundle_id': f'akron-{field}-{year}', 'field': field, 'year': year,
                       'crop': next(iter(crops)), 'yield_kg_ha': sum(values)/len(values),
                       'sample_count': len(samples), 'samples': samples})
    return result


def build_protocol(rows: list[dict[str, str]]) -> dict[str, Any]:
    bundles = aggregate(rows)
    units = sorted({r['field'] for r in bundles})
    out = {
        'schema_version': 'imagery_assessment.v1', 'source_sha256': SOURCE_SHA256,
        'source_url': 'https://doi.org/10.15482/USDA.ADC/28914434.v1', 'source_license': 'CC0',
        'excluded_physical_units_all_years': sorted(EXCLUDED_FIELDS),
        'exclusion_reason': 'Units exposed in field-QA development evaluation; no gold answers read',
        'raw_rows': len(rows), 'eligible_raw_rows': sum(r['sample_count'] for r in bundles),
        'physical_units': units, 'field_seasons': len(bundles), 'limitation': LIMITATION,
        'geometry': {'role': 'sampled_support_research_aoi', 'source_crs': 'UTM zone 13N; datum unresolved',
                     'assumed_crs': 'EPSG:32613', 'datum_status': 'assumption_not_publisher_confirmation',
                     'aoi_rule': 'convex hull of sampling locations buffered 15 metres; research support only',
                     'sensitivity_required': 'Compare EPSG:26913 and EPSG:32613 transforms plus cardinal 15 m and 30 m shifts; report changes without selecting by label performance'},
        'time': {'cutoff_month_day': '06-15', 'acquisition_window_start_month_day': '05-01',
                 'selection_rule': 'latest QA-eligible acquisitions within window, chronological order; source item ID breaks ties; no target-aware selection',
                 'publication_time_status': 'unknown; retrospective acquisition-cutoff experiment, not operational forecast'},
        'tasks': {'crop': 'management-unit/season crop identity',
                  'yield': 'arithmetic mean of yield-monitor-derived yield at available sampled locations'},
        'moisture_percent': MOISTURE_PERCENT, 'yield_pooling': 'no pooled cross-crop yield metrics',
        'models': {'crop': 'train-only StandardScaler; LogisticRegression C=1, lbfgs, max_iter=2000, random_state=0',
                   'yield': 'separate per-crop train-only StandardScaler and Ridge alpha=1; minimum two training seasons',
                   'baseline': 'training crop majority with lexical tie break; training per-crop mean yield',
                   'missingness': 'no imputation; unavailable vectors excluded from fitting, retained as evaluation failures'},
        'representations': {'prithvi': '192-D mean tokens over exactly four chronological dates, weighted by valid sampled-support pixels per 16x16 patch/date, requiring positive valid support each date; actual 224x224 native-30m context primary; missing pixels normalized nodata 0.0001, no resizing; small-chip center nodata-padding only as separate sensitivity',
                            'prithvi_boundary': '480m token and 6.72km context exceed management units; mixed context is not a spatially isolated field embedding',
                            'alias_audit': 'report exact duplicate feature vectors and maximum pairwise cosine similarity; no feature selection'},
        'metrics': ['crop_accuracy', 'crop_balanced_accuracy', 'crop_macro_f1', 'per_crop_yield_mae_kg_ha',
                    'per_crop_yield_rmse_kg_ha', 'per_crop_yield_bias_kg_ha', 'per_crop_paired_baseline_mae_skill', 'coverage_and_failure_denominators'],
        'source_tabular': {'admitted': ['sand_percent', 'carbon_percent'],
                          'reason': '2018 soil sampling per dictionary; publication availability unknown',
                          'excluded': ['crop', 'field', 'rotation', 'yield_kg_ha', 'N_kg_ha', 'P_spring_mm', 'P_summer_mm', 'spei3_Jun', 'spei3_Prior_Sep', 'elev', 'twi', 'psri', 'curv', 'slope', 'tpi', 'roughness'],
                          'excluded_reason': 'target/identity shortcut, future seasonal covariate, or timing/availability unresolved'},
        'location_time_control': ['mean_easting_UTM13N', 'mean_northing_UTM13N', 'year'],
        'folds': [{'fold_id': 'physical-'+u, 'test_units': [u], 'train_units': [v for v in units if v != u]} for u in units],
        'forward_year': {'test_year': 2022, 'train_years': [2019, 2020, 2021],
                         'estimand': 'later year on potentially previously observed units of same farm; not new-field generalization'},
        'bundles': [{'bundle_id': b['bundle_id'], 'physical_unit': b['field'], 'year': b['year'],
                     'cutoff': f"{b['year']}-06-15", 'window_start': f"{b['year']}-05-01", 'sample_count': b['sample_count'],
                     'sampling_utm13n': [[float(r['easting_UTM13N']), float(r['northing_UTM13N'])] for r in b['samples']]} for b in bundles],
    }
    out['split_id'] = digest(out['folds'])
    out['protocol_id'] = digest(out)
    return out


def validate_features(payload: dict, protocol: dict) -> tuple[dict, dict]:
    if payload.get('protocol_id') != protocol['protocol_id']:
        raise ValueError('Feature protocol_id mismatch')
    if not payload.get('feature_set_id') or not payload.get('provenance'):
        raise ValueError('Feature identity and provenance required')
    forbidden = set(protocol['source_tabular']['excluded'])
    if forbidden.intersection(payload['provenance'].get('columns', [])):
        raise ValueError('Forbidden target, future or unresolved source feature column')
    expected = {b['bundle_id']: b for b in protocol['bundles']}
    valid, failures, seen = {}, {}, set()
    dimension = payload.get('dimension')
    if not isinstance(dimension, int) or isinstance(dimension, bool) or not 1 <= dimension <= 4096:
        raise ValueError('Feature dimension must be between 1 and 4096')
    for row in payload.get('rows', []):
        key = row.get('bundle_id')
        if key in seen or key not in expected:
            raise ValueError('Duplicate or unknown feature bundle_id')
        seen.add(key)
        try:
            if row.get('status', 'ok') != 'ok':
                raise ValueError(str(row.get('error', 'producer_failure')))
            end = date.fromisoformat(row['acquisition_max_date'][:10])
            if end > date.fromisoformat(expected[key]['cutoff']):
                raise ValueError('post_cutoff')
            source_hash = row.get('source_sha256', '')
            if len(source_hash) != 64 or any(c not in '0123456789abcdef' for c in source_hash):
                raise ValueError('missing_source_sha256')
            vector = [float(v) for v in row['features']]
            if len(vector) != dimension or not all(math.isfinite(v) for v in vector):
                raise ValueError('invalid_vector')
            valid[key] = vector
        except (ValueError, KeyError, TypeError) as exc:
            failures[key] = str(exc)
    for key in expected.keys()-seen:
        failures[key] = 'missing_feature_row'
    return valid, failures


def source_features(rows: list[dict[str, str]], protocol: dict, *, location_time: bool = False) -> dict:
    columns = ['easting_UTM13N', 'northing_UTM13N'] if location_time else ['sand_percent', 'carbon_percent']
    out = {'feature_set_id': 'location_time_control' if location_time else 'source_soils_2018_fixed',
           'protocol_id': protocol['protocol_id'], 'dimension': 3 if location_time else 2,
           'provenance': {'role': 'source_observation_aggregate', 'source_sha256': SOURCE_SHA256,
                          'columns': columns+(['year'] if location_time else []), 'availability': 'retrospective; publication time unknown'}, 'rows': []}
    for b in aggregate(rows):
        values = [sum(float(r[c]) for r in b['samples'])/b['sample_count'] for c in columns]
        out['rows'].append({'bundle_id': b['bundle_id'], 'source_sha256': SOURCE_SHA256,
                            'acquisition_max_date': f"{b['year']}-01-01" if location_time else '2018-12-31',
                            'features': values+([b['year']] if location_time else [])})
    return out


def _metrics(predictions: list[dict], branch: str) -> dict:
    import numpy as np
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
    scored = [r for r in predictions if r[branch]['crop'] is not None]
    crop = {'eligible': len(predictions), 'predicted': len(scored), 'failed': len(predictions)-len(scored)}
    if scored:
        truth, pred = [r['observed_crop'] for r in scored], [r[branch]['crop'] for r in scored]
        crop.update(accuracy=float(accuracy_score(truth, pred)), balanced_accuracy=float(balanced_accuracy_score(truth, pred)),
                    macro_f1=float(f1_score(truth, pred, labels=sorted(MOISTURE_PERCENT), average='macro', zero_division=0)),
                    accuracy_all_eligible_failures_incorrect=sum(a == b for a, b in zip(truth, pred))/len(predictions))
    yields = {}
    for name, moisture in MOISTURE_PERCENT.items():
        eligible = [r for r in predictions if r['observed_crop'] == name]
        scored = [r for r in eligible if r[branch]['yield_kg_ha'] is not None]
        metric = {'eligible': len(eligible), 'predicted': len(scored), 'failed': len(eligible)-len(scored), 'moisture_percent': moisture}
        if scored:
            error = np.array([r[branch]['yield_kg_ha']-r['observed_yield_kg_ha'] for r in scored])
            baseline = np.array([r['baseline']['yield_kg_ha']-r['observed_yield_kg_ha'] for r in scored])
            mae, base_mae = float(np.mean(abs(error))), float(np.mean(abs(baseline)))
            metric.update(mae_kg_ha=mae, rmse_kg_ha=float(np.sqrt(np.mean(error**2))), bias_kg_ha=float(np.mean(error)),
                          paired_baseline_mae_kg_ha=base_mae, mae_skill_vs_paired_baseline=1-mae/base_mae if base_mae else None)
        yields[name] = metric
    return {'crop': crop, 'yield_by_crop': yields}


def assess(rows: list[dict[str, str]], protocol: dict, features: dict | None = None, *, forward_year: bool = False, matched_cohort: set[str] | None = None) -> dict:
    import numpy as np
    import sklearn
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if protocol != build_protocol(rows):
        raise ValueError('Frozen protocol does not match source or implementation')
    bundles = aggregate(rows)
    vectors, failures = validate_features(features, protocol) if features else ({}, {b['bundle_id']: 'features_not_supplied' for b in bundles})
    folds = ([{'fold_id': 'forward-2022', 'train_years': [2019, 2020, 2021], 'test_years': [2022]}] if forward_year else protocol['folds'])
    predictions = []
    for fold in folds:
        train = [b for b in bundles if (b['year'] in fold['train_years'] if forward_year else b['field'] in fold['train_units'])]
        test = [b for b in bundles if (b['year'] in fold['test_years'] if forward_year else b['field'] in fold['test_units'])]
        if matched_cohort is not None:
            train = [b for b in train if b['bundle_id'] in matched_cohort]
        counts = Counter(b['crop'] for b in train)
        majority = sorted(counts, key=lambda c: (-counts[c], c))[0] if counts else None
        means = {c: float(np.mean([b['yield_kg_ha'] for b in train if b['crop'] == c])) for c in counts}
        fitting = [b for b in train if b['bundle_id'] in vectors]
        classifier, regressors, errors = None, {}, {}
        try:
            if len({b['crop'] for b in fitting}) < 2:
                raise ValueError('fewer_than_two_training_classes')
            classifier = make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=2000, random_state=0))
            classifier.fit([vectors[b['bundle_id']] for b in fitting], [b['crop'] for b in fitting])
        except (ValueError, FloatingPointError) as exc:
            classifier = None
            errors['crop'] = str(exc)
        for crop in MOISTURE_PERCENT:
            fit_crop = [b for b in fitting if b['crop'] == crop]
            try:
                if len(fit_crop) < 2:
                    raise ValueError('fewer_than_two_training_seasons')
                regressor = make_pipeline(StandardScaler(), Ridge(alpha=1))
                regressor.fit([vectors[b['bundle_id']] for b in fit_crop], [b['yield_kg_ha'] for b in fit_crop])
                regressors[crop] = regressor
            except (ValueError, FloatingPointError) as exc:
                errors[crop] = str(exc)
        for b in test:
            model = {'crop': None, 'yield_kg_ha': None, 'failures': {}}
            key = b['bundle_id']
            if key not in vectors:
                model['failures']['features'] = failures[key]
            else:
                if classifier is not None:
                    model['crop'] = str(classifier.predict([vectors[key]])[0])
                else:
                    model['failures']['crop'] = errors.get('crop', 'unavailable')
                if b['crop'] in regressors:
                    value = float(regressors[b['crop']].predict([vectors[key]])[0])
                    if math.isfinite(value):
                        model['yield_kg_ha'] = value
                    else:
                        model['failures']['yield'] = 'nonfinite_prediction'
                else:
                    model['failures']['yield'] = errors.get(b['crop'], 'unavailable')
            predictions.append({'bundle_id': key, 'physical_unit': b['field'], 'fold_id': fold['fold_id'],
                                'train_bundle_ids': [r['bundle_id'] for r in train], 'feature_train_bundle_ids': [r['bundle_id'] for r in fitting],
                                'observed_crop': b['crop'], 'observed_yield_kg_ha': b['yield_kg_ha'], 'sample_count': b['sample_count'],
                                'baseline': {'crop': majority, 'yield_kg_ha': means.get(b['crop'])}, 'features': model})
    aliases = defaultdict(list)
    for key, vector in vectors.items():
        aliases[digest(vector)].append(key)
    matrix = np.array(list(vectors.values())) if vectors else None
    max_cosine = None
    if matrix is not None and len(matrix) > 1:
        norms = np.linalg.norm(matrix, axis=1)
        normalized = matrix[norms > 0]/norms[norms > 0, None]
        if len(normalized) > 1:
            sim = normalized @ normalized.T
            np.fill_diagonal(sim, -np.inf)
            max_cosine = float(np.max(sim))
    return {'schema_version': 'imagery_assessment_result.v1', 'evidence_role': 'exploratory_model_assessment',
            'protocol_id': protocol['protocol_id'], 'split_id': digest(folds), 'source_sha256': SOURCE_SHA256,
            'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'sklearn_version': sklearn.__version__,
            'feature_set_id': features['feature_set_id'] if features else None, 'feature_payload_sha256': hashlib.sha256(json.dumps(features, sort_keys=True, allow_nan=True).encode()).hexdigest() if features else None,
            'feature_provenance': features.get('provenance') if features else None,
            'matched_training_cohort': sorted(matched_cohort) if matched_cohort is not None else None,
            'feature_row_lineage': [{k:v for k,v in r.items() if k != 'features'} for r in features['rows']] if features else None,
            'estimand': protocol['forward_year']['estimand'] if forward_year else 'held-out physical units on same farm and observed years',
            'yield_conditioning': 'observed crop supplied to regression and crop-mean baseline; not end-to-end predicted-crop yield',
            'limitation': LIMITATION, 'baseline': _metrics(predictions, 'baseline'), 'features': _metrics(predictions, 'features'),
            'feature_failures': failures, 'alias_audit': {'exact_duplicate_groups': [v for v in aliases.values() if len(v)>1], 'max_pairwise_cosine_similarity': max_cosine},
            'predictions': predictions}


SPECTRAL_RECIPE = {
    'version': 'hls-valid-support-spectral-32-v1',
    'dimension': 32,
    'dates': 'four distinct chronological dates from the same frozen context manifests as Prithvi',
    'per_date_order': ['mean_blue', 'mean_green', 'mean_red', 'mean_narrow_nir', 'mean_swir1', 'mean_swir2', 'mean_pixel_ndvi', 'mean_pixel_ndmi'],
    'support': 'positive-area intersection with frozen sample-hull plus15m research AOI; binary valid pixel weighting, matching Prithvi support',
    'indices': {'ndvi': '(NarrowNIR-Red)/(NarrowNIR+Red)', 'ndmi': '(NarrowNIR-SWIR1)/(NarrowNIR+SWIR1)'},
    'ratio_denominator': 'absolute denominator > 1e-6; no eligible pixels means failure, no imputation',
    'date_weighting': 'separate chronological slots; no temporal interpolation or duplicate dates',
    'selection': 'fixed before EO feature/score inspection; prior source-only soil/control scores already observed',
}


def spectral_vector(bands, valid, field):
    """Fixed 32D, raw-reflectance/local-index comparator; no trained encoder."""
    import numpy as np
    bands, valid, field = np.asarray(bands), np.asarray(valid), np.asarray(field)
    if bands.ndim != 4 or bands.shape[:2] != (4, 6) or valid.shape != (4, *bands.shape[2:]) or field.shape != bands.shape[2:]:
        raise ValueError('invalid_spectral_shapes')
    if valid.dtype != np.bool_ or field.dtype != np.bool_:
        raise ValueError('invalid_spectral_masks')
    support = valid & field
    if not support.sum(axis=(1, 2)).all():
        raise ValueError('date_has_no_valid_field_pixels')
    values, counts = [], []
    for index in range(4):
        pixels = bands[index][:, support[index]].astype('float64')
        if not np.isfinite(pixels).all():
            raise ValueError('nonfinite_declared_valid_reflectance')
        values.extend(pixels.mean(axis=1).tolist())
        date_counts = {}
        for name, other in [('ndvi', 2), ('ndmi', 4)]:
            denominator = pixels[3]+pixels[other]
            eligible = abs(denominator) > 1e-6
            if not eligible.any():
                raise ValueError('no_valid_'+name+'_denominator')
            values.append(float(((pixels[3, eligible]-pixels[other, eligible])/denominator[eligible]).mean()))
            date_counts[name] = int(eligible.sum())
        counts.append(date_counts)
    return values, {'field_valid_pixel_counts': support.sum(axis=(1, 2)).tolist(),
                    'field_valid_fractions': (support.sum(axis=(1, 2))/field.sum()).tolist(),
                    'ratio_valid_pixel_counts': counts,
                    'field_mask_sha256': hashlib.sha256(field.tobytes()).hexdigest(),
                    'valid_mask_sha256': hashlib.sha256(valid.tobytes()).hexdigest()}


def extract_spectral_features(protocol_path: Path, contexts_path: Path) -> dict:
    """Local-only spectral features from exactly the verified four-date model grids."""
    import numpy as np
    from agronomy_agent.imagery_models import load_chip_manifest, sampled_support_mask, sha256
    protocol = json.loads(protocol_path.read_text())
    inputs = json.loads(contexts_path.read_text())['contexts']
    years = [int(entry['year']) for entry in inputs]
    if len(years) != len(set(years)) or not set(years) <= {b['year'] for b in protocol['bundles']}:
        raise ValueError('invalid_context_years')
    results, receipts = {}, []
    for entry in inputs:
        year = int(entry['year'])
        bundles = [b for b in protocol['bundles'] if b['year'] == year]
        receipt = {'year': year, 'status': 'error'}
        try:
            if entry.get('status', 'ok') != 'ok':
                raise ValueError(entry.get('error', 'context_acquisition_failed'))
            path = Path(entry['manifest'])
            if not path.is_absolute():
                path = contexts_path.parent/path
            manifest = json.loads(path.read_text())
            if manifest.get('label_protocol_id') != protocol['protocol_id']:
                raise ValueError('context_protocol_id_mismatch')
            arrays = []
            for chip in manifest['chips']:
                chip_path = Path(chip['path'])
                if not chip_path.is_absolute():
                    chip_path = path.parent/chip_path
                if chip.get('sha256') != sha256(chip_path):
                    raise ValueError('chip_manifest_sha256_mismatch')
                with np.load(chip_path, allow_pickle=False) as data:
                    arrays.append(data['bands'].copy())
            prepared = load_chip_manifest(path)
            dates = prepared['receipt']['dates']
            if any(not f'{year}-05-01' <= d <= f'{year}-06-15' for d in dates):
                raise ValueError('outside_frozen_year_acquisition_window')
            if prepared['receipt']['spatial_regime'] != 'actual_context_no_padding':
                raise ValueError('primary_cohort_disallows_padding')
            if not prepared['receipt']['source_native_grid'] or set(prepared['receipt']['process_versions']) != {'hls-chip-v2-native-asset-grid-fmask-v1'}:
                raise ValueError('primary_cohort_requires_verified_v2_source_native_grid')
            source_hash = hashlib.sha256(json.dumps(prepared['receipt']['source_files'], sort_keys=True).encode()).hexdigest()
            for bundle in bundles:
                try:
                    field = sampled_support_mask(bundle['sampling_utm13n'], prepared['receipt']['native_grid'])
                    feature, pooling = spectral_vector(np.stack(arrays), prepared['valid_mask'], field)
                    results[bundle['bundle_id']] = {'bundle_id': bundle['bundle_id'], 'status': 'ok', 'features': feature,
                        'acquisition_max_date': max(dates), 'acquisition_dates': dates, 'dates_sha256': digest(dates),
                        'source_sha256': source_hash, 'pooling': pooling, 'shared_context_year': year}
                except (ValueError, TypeError, KeyError) as error:
                    results[bundle['bundle_id']] = {'bundle_id': bundle['bundle_id'], 'status': 'error', 'error': str(error)}
            receipt.update(status='ok', source=prepared['receipt'], dates_sha256=digest(dates))
        except Exception as error:
            receipt['error'] = f'{type(error).__name__}: {error}'
            for bundle in bundles:
                results[bundle['bundle_id']] = {'bundle_id': bundle['bundle_id'], 'status': 'error', 'error': receipt['error']}
        receipts.append(receipt)
    return {'protocol_id': protocol['protocol_id'], 'feature_set_id': SPECTRAL_RECIPE['version'], 'dimension': 32,
            'provenance': {'role': 'derived_local_spectral_features_not_field_measurements', 'recipe': SPECTRAL_RECIPE,
                'recipe_sha256': digest(SPECTRAL_RECIPE), 'adapter_sha256': sha256(Path(__file__)),
                'context_loader_sha256': sha256(Path(__file__).with_name('imagery_models.py')),
                'protocol_sha256': sha256(protocol_path), 'contexts_manifest_sha256': sha256(contexts_path),
                'common_contexts': receipts, 'model': 'none; fixed spectral arithmetic',
                'source_crs_assumption': 'EPSG:32613'},
            'rows': [results.get(b['bundle_id'], {'bundle_id': b['bundle_id'], 'status': 'error', 'error': 'missing_shared_context_year'}) for b in protocol['bundles']]}


def compare_features(rows: list[dict], protocol: dict, spectral: dict, encoder: dict) -> dict:
    """Identical-source, identical-mask success intersection; keep all bundle failures."""
    import copy
    left, left_errors = validate_features(spectral, protocol)
    right, right_errors = validate_features(encoder, protocol)
    left_rows = {r['bundle_id']: r for r in spectral['rows']}
    right_rows = {r['bundle_id']: r for r in encoder['rows']}
    common, dispositions = set(), []
    for bundle in protocol['bundles']:
        key = bundle['bundle_id']
        errors = {}
        if key not in left:
            errors['spectral'] = left_errors.get(key, 'unavailable')
        if key not in right:
            errors['encoder'] = right_errors.get(key, 'unavailable')
        if not errors:
            a, b = left_rows[key], right_rows[key]
            if a['source_sha256'] != b['source_sha256'] or a['acquisition_max_date'] != b['acquisition_max_date']:
                errors['comparison'] = 'source_or_acquisition_mismatch'
            for kind in ['field_mask_sha256', 'valid_mask_sha256']:
                if not a.get('pooling', {}).get(kind) or a['pooling'][kind] != b.get('pooling', {}).get(kind):
                    errors['comparison'] = 'support_or_qa_mask_mismatch'
        if not errors:
            common.add(key)
        dispositions.append({'bundle_id': key, 'status': 'ok' if not errors else 'error', 'failures': errors})
    lanes = {}
    for name, payload in [('spectral', spectral), ('encoder', encoder),
                          ('location_time', source_features(rows, protocol, location_time=True))]:
        paired = copy.deepcopy(payload)
        for row in paired['rows']:
            if row['bundle_id'] not in common:
                row.update(status='error', error='not_in_common_success_cohort')
        lanes[name] = {}
        for forward in [False, True]:
            result = assess(rows, protocol, paired, forward_year=forward, matched_cohort=common)
            subset = [p for p in result['predictions'] if p['bundle_id'] in common]
            result['common_case_metrics'] = {branch: _metrics(subset, branch) for branch in ['baseline', 'features']}
            lanes[name]['forward_year' if forward else 'physical_group'] = result
    return {'schema_version': 'paired_imagery_assessment.v1', 'protocol_id': protocol['protocol_id'],
            'recipe_sha256': digest(SPECTRAL_RECIPE), 'source_sha256': SOURCE_SHA256,
            'comparison_rule': 'same source/date and support/QA masks; fit each arm and baseline on identical common-success training bundles',
            'eligible': len(protocol['bundles']), 'common_success': len(common), 'failed': len(protocol['bundles'])-len(common),
            'common_bundle_ids': sorted(common), 'dispositions': dispositions,
            'original_feature_payload_sha256': {'spectral': digest(spectral), 'encoder': digest(encoder)},
            'lanes': lanes, 'limitation': LIMITATION}


def spectral_spatial_sensitivity(protocol_path: Path, contexts_path: Path) -> dict:
    """Label-free support/feature sensitivity; never fit or choose offsets by scores."""
    import numpy as np
    from pyproj import Transformer
    from agronomy_agent.imagery_models import load_chip_manifest, sampled_support_mask, sha256
    protocol = json.loads(protocol_path.read_text())
    primary = extract_spectral_features(protocol_path, contexts_path)
    primary_rows = {r['bundle_id']: r for r in primary['rows']}
    contexts = {int(e['year']): e for e in json.loads(contexts_path.read_text())['contexts']}
    cached, results = {}, []
    alternatives = [('east_15m', 15, 0), ('west_15m', -15, 0), ('north_15m', 0, 15), ('south_15m', 0, -15),
                    ('east_30m', 30, 0), ('west_30m', -30, 0), ('north_30m', 0, 30), ('south_30m', 0, -30),
                    ('nad83_utm13n_alternative', None, None)]
    transformer = Transformer.from_crs('EPSG:26913', 'EPSG:32613', always_xy=True)
    for bundle in protocol['bundles']:
        key, year = bundle['bundle_id'], bundle['year']
        result = {'bundle_id': key, 'status': 'error', 'alternatives': []}
        nominal = primary_rows[key]
        if nominal['status'] != 'ok':
            result['error'] = nominal.get('error', 'primary_unavailable')
            results.append(result)
            continue
        try:
            if year not in cached:
                path = Path(contexts[year]['manifest'])
                if not path.is_absolute():
                    path = contexts_path.parent/path
                arrays = []
                for chip in json.loads(path.read_text())['chips']:
                    chip_path = Path(chip['path'])
                    if not chip_path.is_absolute():
                        chip_path = path.parent/chip_path
                    if chip['sha256'] != sha256(chip_path):
                        raise ValueError('chip_manifest_sha256_mismatch')
                    with np.load(chip_path, allow_pickle=False) as data:
                        arrays.append(data['bands'].copy())
                cached[year] = (np.stack(arrays), load_chip_manifest(path))
            bands, prepared = cached[year]
            grid, valid = prepared['receipt']['native_grid'], prepared['valid_mask']
            mask = sampled_support_mask(bundle['sampling_utm13n'], grid)
            result.update(status='ok', nominal_mask_pixels=int(mask.sum()),
                          nominal_valid_pixel_counts=(valid & mask).sum(axis=(1,2)).tolist(),
                          source_sha256=nominal['source_sha256'], dates_sha256=nominal['dates_sha256'],
                          nominal_feature_sha256=digest(nominal['features']))
            for name, dx, dy in alternatives:
                cell = {'alternative': name, 'status': 'error'}
                try:
                    points = [transformer.transform(x, y) if dx is None else (x+dx, y+dy) for x, y in bundle['sampling_utm13n']]
                    shifted = sampled_support_mask(points, grid)
                    union = int((mask | shifted).sum())
                    cell.update(mask_pixels=int(shifted.sum()), support_jaccard=float((mask & shifted).sum()/union),
                                changed_pixels=int((mask != shifted).sum()),
                                field_mask_sha256=hashlib.sha256(shifted.tobytes()).hexdigest(),
                                valid_pixel_counts=(valid & shifted).sum(axis=(1,2)).tolist())
                    vector, pooling = spectral_vector(bands, valid, shifted)
                    delta = np.array(vector)-np.array(nominal['features'])
                    cell.update(status='ok', feature_sha256=digest(vector), max_absolute_feature_delta=float(abs(delta).max()),
                                rms_feature_delta=float(np.sqrt(np.mean(delta**2))), field_valid_fractions=pooling['field_valid_fractions'])
                except (ValueError, KeyError, TypeError) as error:
                    cell['error'] = str(error)
                result['alternatives'].append(cell)
        except Exception as error:
            result['status'] = 'error'
            result['error'] = f'{type(error).__name__}: {error}'
        results.append(result)
    return {'schema_version': 'imagery_spatial_sensitivity.v1', 'protocol_id': protocol['protocol_id'],
            'recipe_sha256': digest(SPECTRAL_RECIPE), 'source_sha256': SOURCE_SHA256,
            'code_sha256': sha256(Path(__file__)), 'contexts_manifest_sha256': sha256(contexts_path),
            'primary_feature_payload_sha256': digest(primary), 'primary_feature_provenance': primary['provenance'],
            'method': 'Cardinal15m/30m support translations and NAD83-UTM13N to WGS84-UTM13N alternative; fixed imagery; no resampling, labels, readout fitting or offset selection',
            'datum_transform': {'description': transformer.description, 'accuracy_metres': transformer.accuracy},
            'eligible': len(results), 'nominal_available': sum(r['status']=='ok' for r in results), 'rows': results,
            'limitation': 'Support and feature stability only; does not resolve source datum or establish shifted prediction accuracy. Primary metrics unchanged.'}
