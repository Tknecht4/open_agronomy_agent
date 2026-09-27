"""Optional, offline, pinned frozen EO features; never agronomic predictions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

MODEL_ID = 'ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL'
REVISION = '335eadc2c45ad5abe7bd307223e1c48c5b60c41b'
BANDS = ('blue', 'green', 'red', 'nir_narrow', 'swir1', 'swir2')
PREPROCESSING = 'prithvi-hls-reflectance-sentinel-centerpad-fieldpool-v1'
PINNED_SHA256 = {
    'prithvi_mae.py': '9cee9a8cb17c3859d6365a7e58f723e0f4c08e3e29aa4b8e6523506db70321da',
    'config.json': 'd7f9e36d2253cb82d296bfd95a9a651f2af455c0cfe8a5ea775b2e3d196ad170',
    'Prithvi_EO_V2_tiny_TL.pt': 'd47326db9bad502b611f73e3e3f3a0e68b7b82640d67c22c795417f7209f8d70',
}


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_snapshot(snapshot: str | Path) -> dict:
    """Verify every executable/config/weight byte before import or torch.load."""
    root = Path(snapshot)
    for name, expected in PINNED_SHA256.items():
        if sha256(root / name) != expected:
            raise ValueError(f'model_snapshot_hash_mismatch:{name}')
    return {'model_id': MODEL_ID, 'revision': REVISION, 'license': 'Apache-2.0',
            'sha256': dict(PINNED_SHA256)}


def prepare_stack(bands, valid_mask, field_mask, dates, latitude, longitude, *, cutoff,
                  band_names=BANDS, allow_center_padding=False):
    """Prepare [4,6,H,W] native-resolution reflectance; explicitly retain missingness.

    Sentinel .0001 is official inference's *normalized* missing value, not a
    reflectance observation. No interpolation/repetition of dates is allowed.
    """
    import numpy as np
    x = np.asarray(bands, dtype=np.float32)
    valid = np.asarray(valid_mask)
    field = np.asarray(field_mask)
    if tuple(band_names) != BANDS:
        raise ValueError('unsupported_band_order')
    if x.ndim != 4 or x.shape[:2] != (4, 6):
        raise ValueError('expected_four_dates_six_bands')
    h, w = x.shape[-2:]
    if not (1 <= h <= 224 and 1 <= w <= 224):
        raise ValueError('native_chip_dimensions_must_be_1_to_224')
    if (h, w) != (224, 224) and not allow_center_padding:
        raise ValueError('explicit_center_padding_required')
    if valid.dtype != np.bool_ or valid.shape != (4, h, w):
        raise ValueError('invalid_valid_mask')
    if field.dtype != np.bool_ or field.shape != (h, w) or not field.any():
        raise ValueError('invalid_field_mask')
    if not np.isfinite(x.transpose(0, 2, 3, 1)[valid]).all():
        raise ValueError('nonfinite_declared_valid_reflectance')
    if ((x.transpose(0, 2, 3, 1)[valid] < -.2) | (x.transpose(0, 2, 3, 1)[valid] > 1.6)).any():
        raise ValueError('reflectance_outside_hls_physical_storage_range')
    ds = [date.fromisoformat(str(d)[:10]) for d in dates]
    if len(ds) != 4 or ds != sorted(set(ds)) or ds[-1] > date.fromisoformat(cutoff):
        raise ValueError('dates_must_be_four_unique_chronological_at_or_before_cutoff')
    if not np.isfinite([latitude, longitude]).all() or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError('invalid_latitude_longitude')
    coverage = (valid & field).sum(axis=(1, 2)) / field.sum()
    if (coverage <= 0).any():
        raise ValueError('date_has_no_valid_field_pixels')
    mean = np.array([1087, 1342, 1433, 2734, 1958, 1363], dtype=np.float32)[None, :, None, None] * .0001
    std = np.array([2248, 2179, 2178, 1850, 1242, 1049], dtype=np.float32)[None, :, None, None] * .0001
    normalized = np.where(valid[:, None], (x - mean) / std, .0001)
    top, left = (224 - h) // 2, (224 - w) // 2
    out = np.full((4, 6, 224, 224), .0001, dtype=np.float32)
    out[:, :, top:top+h, left:left+w] = normalized
    padded_valid = np.zeros((4, 224, 224), dtype=bool)
    padded_field = np.zeros((224, 224), dtype=bool)
    padded_valid[:, top:top+h, left:left+w] = valid
    padded_field[top:top+h, left:left+w] = field
    # Fractional field area AND valid fraction weight observed supports only.
    weights = (padded_valid & padded_field).reshape(4, 14, 16, 14, 16).sum(axis=(2, 4)).reshape(-1).astype(np.float32)
    weights /= weights.sum()
    return {
        'input': np.ascontiguousarray(out.transpose(1, 0, 2, 3)[None]),
        'temporal_coords': np.array([[[d.year, d.timetuple().tm_yday] for d in ds]], dtype=np.float32),
        'location_coords': np.array([[latitude, longitude]], dtype=np.float32),
        'pool_weights': weights, 'valid_mask': padded_valid, 'field_mask': padded_field,
        'receipt': {'preprocessing': PREPROCESSING, 'native_shape': [4, 6, h, w],
                    'model_shape': [1, 6, 4, 224, 224], 'center_padding': [top, left, 224-h-top, 224-w-left],
                    'dates': [d.isoformat() for d in ds], 'cutoff': cutoff,
                    'field_valid_fractions': coverage.tolist(), 'normalized_nodata_sentinel': .0001,
                    'valid_model_fraction': float(padded_valid.mean()), 'attention_mask_supported': False,
                    'pooling': 'last_normalized_non_cls_tokens_weighted_by_valid_field_pixel_count',
                    'spatial_regime': 'actual_context_no_padding' if (h, w) == (224, 224) else 'nodata_padding_sensitivity_only',
                    'patch_support_metres': 480, 'native_pixel_metres': 30,
                    'limitations': ['patches_mix_field_and_context', 'sentinel_is_not_observed_reflectance',
                                    'self_attention_mixes_all_tokens'] + (['padding_adaptation_not_accuracy_validated'] if (h, w) != (224, 224) else [])}}


class FrozenPrithvi:
    """Hash-allowlisted local encoder. No network, training, or serving activation."""
    def __init__(self, snapshot, device='cpu'):
        import torch
        if device not in ('cpu', 'mps'):
            raise ValueError('unsupported_device')
        if device == 'mps' and not torch.backends.mps.is_available():
            raise RuntimeError('mps_unavailable')
        self.identity = verify_snapshot(snapshot)
        root = Path(snapshot)
        spec = importlib.util.spec_from_file_location('_pinned_prithvi_mae', root / 'prithvi_mae.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cfg = json.loads((root / 'config.json').read_text())['pretrained_cfg']
        encoder = module.PrithviViT(**cfg)
        state = torch.load(root / 'Prithvi_EO_V2_tiny_TL.pt', map_location='cpu', weights_only=True)
        encoder_state = {key.removeprefix('encoder.'): value for key, value in state.items() if key.startswith('encoder.')}
        # Fixed generated positions follow the official inference loader.
        encoder_state['pos_embed'] = encoder.pos_embed
        encoder.load_state_dict(encoder_state, strict=True)
        self.model = encoder.eval().requires_grad_(False).to(device)
        self.device = device
        self.parameter_count = sum(p.numel() for p in encoder.parameters())

    def encode_tokens(self, prepared):
        """Encode a shared station context once; ROI is not an encoder input.

        Reuse only with the identical input/mask/date/location/model identity.
        Pool each unit separately with its own mask; overlapping tokens remain
        dependent and may yield identical features for different units.
        """
        import numpy as np
        import torch
        args = [torch.from_numpy(prepared[k]).to(self.device) for k in ('input', 'temporal_coords', 'location_coords')]
        with torch.inference_mode():
            tokens = self.model.forward_features(*args)[-1][0, 1:, :].cpu().numpy()
        if tokens.shape != (784, 192) or not np.isfinite(tokens).all():
            raise ValueError('nonfinite_or_malformed_encoder_tokens')
        return tokens

    def extract(self, prepared):
        import numpy as np
        import torch
        args = [torch.from_numpy(prepared[k]).to(self.device) for k in ('input', 'temporal_coords', 'location_coords')]
        weights = torch.from_numpy(prepared['pool_weights']).to(self.device)
        with torch.inference_mode():
            tokens = self.model.forward_features(*args)[-1][:, 1:, :]
            features = (tokens * weights[None, :, None]).sum(dim=1).cpu().numpy()[0]
        if features.shape != (192,) or not np.isfinite(features).all():
            raise ValueError('nonfinite_or_malformed_encoder_features')
        return features



def compare_hls_grid_crs(reference, candidate):
    """Compare CRS semantically, with one explicitly qualified HLS header case.

    This narrow exception establishes a common numerical lattice, not formal
    datum equality. It changes neither pixels nor original CRS metadata.
    """
    import re
    from pyproj import CRS, Transformer
    a, b = CRS.from_user_input(reference['crs']), CRS.from_user_input(candidate['crs'])
    receipt = {'reference_crs':reference['crs'], 'candidate_crs':candidate['crs'],
               'reference_datum':a.datum.name, 'candidate_datum':b.datum.name,
               'formal_crs_equal':a.equals(b), 'resampling_performed':False}
    for crs in (a,b):
        if not crs.is_projected or [(v.direction,v.unit_name,v.unit_conversion_factor) for v in crs.axis_info] != [('east','metre',1.),('north','metre',1.)]:
            raise ValueError('chips_do_not_share_native_grid:requires_projected_metre_axes')
    if a.equals(b):
        return {**receipt, 'status':'semantic_crs_equal'}
    known_wkt = '9c151a666a9e7a41ce65ed2b837108933f4fcca355eff22f9dcc4d880b3f19a2'
    originals = [reference['crs'], candidate['crs']]
    if set(originals) != {'EPSG:32613', next((v for v in originals if hashlib.sha256(v.encode()).hexdigest()==known_wkt), '')}:
        raise ValueError('chips_do_not_share_native_grid:unqualified_crs_difference')
    tiles = []
    for meta, crs in ((reference,a),(candidate,b)):
        src = meta['source']
        tile = re.search(r'\.T(13[C-X][A-Z]{2})\.', src['scene_id'])
        if (meta.get('process_version') != 'hls-chip-v2-native-asset-grid-fmask-v1'
            or meta.get('source_native_grid') is not True
            or src.get('collection') not in ('hls2-l30','hls2-s30') or tile is None):
            raise ValueError('chips_do_not_share_native_grid:unqualified_hls_product')
        tiles.append(tile.group(1))
        axes = [(axis.direction,axis.unit_name,axis.unit_conversion_factor) for axis in crs.axis_info]
        operation = crs.coordinate_operation.to_json_dict()
        parameters = [(p['id']['code'],p['value'],p['unit']) for p in operation['parameters']]
        expected = [(8801,0,'degree'),(8802,-105,'degree'),(8805,.9996,'unity'),(8806,500000,'metre'),(8807,0,'metre')]
        if (not crs.is_projected or axes != [('east','metre',1.),('north','metre',1.)]
            or crs.ellipsoid.semi_major_metre != 6378137.
            or crs.ellipsoid.inverse_flattening != 298.257223563
            or crs.prime_meridian.longitude != 0
            or operation['method']['id']['code'] != 9807 or parameters != expected):
            raise ValueError('chips_do_not_share_native_grid:projection_ellipsoid_axis_difference')
    if tiles[0] != tiles[1]:
        raise ValueError('chips_do_not_share_native_grid:different_mgrs_tiles')
    transform = Transformer.from_crs(a,b,always_xy=True)
    return {**receipt, 'status':'qualified_hls_same_numeric_utm13_lattice',
            'mgrs_tile':tiles[0], 'known_unknown_datum_wkt_sha256':known_wkt,
            'projection_parameters':expected, 'axes':axes,
            'ellipsoid':{'semi_major_metre':6378137.,'inverse_flattening':298.257223563},
            'proj_operation':transform.description,'proj_accuracy_metres':transform.accuracy,
            'datum_status':'unresolved_header_datum_assumed_same_HLS_product_lattice_not_formal_CRS_equality',
            'basis':'official HLS L30/S30 same MGRS UTM tile specification plus exact affine/shape/projection/ellipsoid/axes',
            'source_specification':'https://lpdaac.usgs.gov/documents/1698/HLS_User_Guide_V2.pdf'}

def load_chip_manifest(manifest_path, *, allow_center_padding=False):
    """Load four hash-bound analytics NPZ chips without object deserialization.

    Manifest: chips [{path,date}], cutoff; optional bundle_id. Location comes from the grid.
    NPZ metadata_json is the analytics producer's native-grid/band receipt.
    """
    import numpy as np
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    chips = manifest['chips']
    if len(chips) != 4:
        raise ValueError('exactly_four_chip_paths_required')
    arrays, masks, dates, sources, process_versions, native_flags = [], [], [], [], [], []
    grid = field = reference_meta = None
    crs_comparisons = []
    expected_bands = ['Blue', 'Green', 'Red', 'NarrowNIR', 'SWIR1', 'SWIR2']
    for chip in chips:
        path = Path(chip['path'])
        if not path.is_absolute():
            path = manifest_path.parent / path
        actual_sha256 = sha256(path)
        if chip.get('sha256') is not None and chip['sha256'] != actual_sha256:
            raise ValueError('chip_declared_sha256_mismatch')
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data['metadata_json'].item()))
            if meta['band_names'] != expected_bands or meta['resolution_m'] != 30:
                raise ValueError('unsupported_chip_bands_or_resolution')
            transform = tuple(meta['transform'])
            if len(transform) != 6 or transform[0] != 30 or transform[4] != -30 or transform[1] != 0 or transform[3] != 0:
                raise ValueError('unsupported_native_grid_transform')
            this_grid = (transform, meta['crs'], data['bands'].shape)
            if grid is not None:
                if grid[0] != this_grid[0] or grid[2] != this_grid[2]:
                    raise ValueError('chips_do_not_share_native_grid')
                crs_comparisons.append(compare_hls_grid_crs(reference_meta, meta))
            else:
                reference_meta = meta
            if field is not None and not np.array_equal(field, data['field_mask']):
                raise ValueError('chips_do_not_share_field_mask')
            if str(chip['date'])[:10] != str(meta['source']['acquired_at'])[:10]:
                raise ValueError('chip_date_does_not_match_acquisition')
            process_versions.append(meta.get('process_version'))
            native_flags.append(meta.get('source_native_grid') is True)
            if grid is None:
                grid = this_grid
            field = data['field_mask'].copy()
            arrays.append(data['bands'].copy()); masks.append(data['valid_mask'].copy())
        dates.append(chip['date'])
        sources.append({'name': path.name, 'sha256': actual_sha256,
                        'declared_sha256_verified': chip.get('sha256') == actual_sha256,
                        'original_crs': meta['crs'], 'scene_id': meta['source']['scene_id'],
                        'acquired_at': meta['source']['acquired_at']})
    # Use the actual native raster centre, matching the encoder's location role.
    # Caller-provided coordinates are not a replacement for this grid identity.
    from pyproj import Transformer
    transform, crs, shape = grid
    center_x = transform[2] + transform[0] * shape[-1] / 2
    center_y = transform[5] + transform[4] * shape[-2] / 2
    longitude, latitude = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform(center_x, center_y)
    prepared = prepare_stack(np.stack(arrays), np.stack(masks), field, dates,
                             latitude, longitude, cutoff=manifest['cutoff'],
                             allow_center_padding=allow_center_padding)
    prepared['receipt'].update(input_kind='real_hls_contextual_features_not_accuracy', source_files=sources,
                               manifest_sha256=sha256(manifest_path), native_grid=list(grid[:2]),
                               bundle_id=manifest.get('bundle_id'), label_protocol_id=manifest.get('label_protocol_id'),
                               process_versions=process_versions, source_native_grid=all(native_flags),
                               crs_comparisons=crs_comparisons,
                               spatial_overlap='nearby_contexts_may_overlap_not_spatially_independent',
                               coordinate_order='latitude_longitude_per_encoder_docstring',
                               location_source='native_raster_center_transformed_to_epsg4326',
                               latitude=latitude, longitude=longitude,
                               normalization='reflectance_statistics_scaled_from_config_DN_by_0.0001')
    return prepared


def pool_shared_context(tokens, valid_mask, field_mask):
    """Pool shared four-date/224 tokens by one unit's valid support pixel count."""
    import numpy as np
    tokens, valid, field = np.asarray(tokens), np.asarray(valid_mask), np.asarray(field_mask)
    if tokens.shape != (784, 192) or not np.isfinite(tokens).all():
        raise ValueError('invalid_shared_context_tokens')
    if valid.shape != (4, 224, 224) or valid.dtype != np.bool_:
        raise ValueError('invalid_shared_context_valid_mask')
    if field.shape != (224, 224) or field.dtype != np.bool_ or not field.any():
        raise ValueError('invalid_shared_context_field_mask')
    support = valid & field
    if not support.sum(axis=(1, 2)).all():
        raise ValueError('date_has_no_valid_field_pixels')
    counts = support.reshape(4, 14, 16, 14, 16).sum(axis=(2, 4)).reshape(-1)
    weights = counts.astype(np.float32)
    weights /= weights.sum()
    feature = (tokens * weights[:, None]).sum(axis=0)
    return feature, {
        'pooling': 'last_normalized_non_cls_tokens_weighted_by_valid_field_pixel_count',
        'field_mask_sha256': hashlib.sha256(field.tobytes()).hexdigest(),
        'valid_mask_sha256': hashlib.sha256(valid.tobytes()).hexdigest(),
        'token_support_counts_sha256': hashlib.sha256(counts.astype('<i8').tobytes()).hexdigest(),
        'normalized_pool_weights_sha256': hashlib.sha256(weights.astype('<f4').tobytes()).hexdigest(),
        'supported_token_indices': [int(i) for i in np.flatnonzero(counts)],
        'supported_tokens': int((counts > 0).sum()),
        'field_valid_fractions': (support.sum(axis=(1, 2)) / field.sum()).tolist(),
        'overlap_warning': 'shared_context_and_overlapping_tokens_are_dependent',
    }


def sampled_support_mask(samples_utm13n, grid):
    """Frozen research AOI: UTM13N sample hull +15m; positive cell intersection.

    This is sampled support, never a surveyed boundary. EPSG:32613 remains the
    protocol's explicitly unresolved-datum assumption.
    """
    import numpy as np
    from affine import Affine
    from pyproj import Transformer
    from rasterio.features import geometry_mask
    from shapely.geometry import MultiPoint, box
    from shapely.ops import transform as transform_geometry
    geometry = MultiPoint(samples_utm13n).convex_hull.buffer(15)
    transform, crs = grid
    if crs != 'EPSG:32613':
        geometry = transform_geometry(Transformer.from_crs('EPSG:32613', crs, always_xy=True).transform, geometry)
    affine = Affine(*transform)
    bounds = box(affine.c, affine.f - 224*30, affine.c + 224*30, affine.f)
    if not bounds.covers(geometry):
        raise ValueError('sampled_support_outside_shared_context')
    candidates = geometry_mask([geometry.__geo_interface__], out_shape=(224,224),
                               transform=affine, all_touched=True, invert=True)
    mask = np.zeros((224,224), dtype=bool)
    for row, col in zip(*np.nonzero(candidates)):
        x, y = affine.c + col*30, affine.f-row*30
        mask[row,col] = geometry.intersection(box(x,y-30,x+30,y)).area > 0
    return mask


def extract_cohort_features(protocol_path, contexts_path, snapshot, *, device='mps', progress=None, token_output_dir=None):
    """Local-only shared-context features; retain every frozen bundle's status.

    contexts_path JSON: {contexts:[{year,manifest,status,error}]}. Paths resolve
    relative to that file. Only successful four-date May1--June15 contexts are
    admitted; no new imagery requests, labels, fitting or score inspection.
    """
    import time
    protocol_path, contexts_path = Path(protocol_path), Path(contexts_path)
    protocol = json.loads(protocol_path.read_text())
    context_index = json.loads(contexts_path.read_text())
    if context_index.get('label_protocol_id') != protocol['protocol_id']:
        raise ValueError('context_index_protocol_id_mismatch')
    inputs = context_index['contexts']
    years = [int(row['year']) for row in inputs]
    if len(years) > 4 or len(set(years)) != len(years) or not set(years) <= {b['year'] for b in protocol['bundles']}:
        raise ValueError('expected_at_most_four_unique_year_contexts')
    progress = progress or (lambda stage, partial=None: None)
    progress('cohort_model_load')
    model = FrozenPrithvi(snapshot, device)
    results, receipts = {}, []
    for entry in inputs:
        year = int(entry['year'])
        bundles = [b for b in protocol['bundles'] if b['year'] == year]
        receipt = {'year': year, 'status':'error'}
        try:
            if entry.get('status', 'ok') != 'ok':
                raise ValueError(entry.get('error', 'context_acquisition_failed'))
            path = Path(entry['manifest'])
            if not path.is_absolute(): path = contexts_path.parent / path
            prepared = load_chip_manifest(path)
            dates = prepared['receipt']['dates']
            if any(not f'{year}-05-01' <= d <= f'{year}-06-15' for d in dates):
                raise ValueError('outside_frozen_year_acquisition_window')
            if prepared['receipt']['spatial_regime'] != 'actual_context_no_padding':
                raise ValueError('primary_cohort_disallows_padding')
            if not prepared['receipt']['source_native_grid'] or set(prepared['receipt']['process_versions']) != {'hls-chip-v2-native-asset-grid-fmask-v1'}:
                raise ValueError('primary_cohort_requires_verified_v2_source_native_grid')
            if prepared['receipt']['label_protocol_id'] != protocol['protocol_id']:
                raise ValueError('context_manifest_protocol_id_mismatch')
            if not all(source['declared_sha256_verified'] for source in prepared['receipt']['source_files']):
                raise ValueError('primary_cohort_requires_declared_chip_hashes')
            progress(f'cohort_forward_{year}')
            start = time.perf_counter()
            tokens = model.encode_tokens(prepared)
            receipt.update(status='ok', forward_seconds=time.perf_counter()-start,
                           source=prepared['receipt'], token_sha256=hashlib.sha256(tokens.tobytes()).hexdigest())
            source_hash = hashlib.sha256(json.dumps(prepared['receipt']['source_files'],sort_keys=True).encode()).hexdigest()
            if token_output_dir is not None:
                import numpy as np
                token_root = Path(token_output_dir)
                token_root.mkdir(parents=True, exist_ok=True)
                token_path = token_root / f"{year}-{receipt['token_sha256']}.npz"
                with token_path.open('xb') as handle:
                    np.savez_compressed(handle, tokens=tokens, valid_mask=prepared['valid_mask'],
                        metadata_json=json.dumps({'year':year, 'protocol_id':protocol['protocol_id'],
                            'source_sha256':source_hash, 'model':model.identity, 'source':prepared['receipt']},sort_keys=True))
                receipt['token_cache_file'] = {'name':token_path.name, 'sha256':sha256(token_path)}
            for bundle in bundles:
                try:
                    mask = sampled_support_mask(bundle['sampling_utm13n'], prepared['receipt']['native_grid'])
                    feature, pooling = pool_shared_context(tokens, prepared['valid_mask'], mask)
                    results[bundle['bundle_id']] = {
                        'bundle_id':bundle['bundle_id'], 'status':'ok', 'features':feature.tolist(),
                        'acquisition_max_date':max(dates), 'source_sha256':source_hash,
                        'pooling':pooling, 'shared_context_year':year,
                    }
                except (ValueError, TypeError, KeyError) as error:
                    results[bundle['bundle_id']] = {'bundle_id':bundle['bundle_id'], 'status':'error', 'error':str(error)}
        except Exception as error:
            receipt.update(status='error', error=f'{type(error).__name__}: {error}')
            for bundle in bundles:
                results[bundle['bundle_id']] = {'bundle_id':bundle['bundle_id'], 'status':'error', 'error':receipt['error']}
        receipts.append(receipt)
        progress(f'cohort_finished_{year}', {'rows':list(results.values()), 'contexts':list(receipts)})
    rows = [results.get(b['bundle_id'], {'bundle_id':b['bundle_id'],'status':'error','error':'missing_shared_context_year'})
            for b in protocol['bundles']]
    from collections import defaultdict
    feature_groups, weight_groups = defaultdict(list), defaultdict(list)
    for row in rows:
        if row['status'] == 'ok':
            feature_groups[tuple(row['features'])].append(row['bundle_id'])
            weight_groups[(row['source_sha256'], row['pooling']['normalized_pool_weights_sha256'])].append(row['bundle_id'])
    aliases = {'exact_feature_groups':[group for group in feature_groups.values() if len(group)>1],
               'same_context_normalized_weight_groups':[group for group in weight_groups.values() if len(group)>1]}
    import importlib.metadata
    versions = {name:importlib.metadata.version(name) for name in ('torch','timm','numpy','pyproj','shapely','rasterio')}
    return {'protocol_id':protocol['protocol_id'], 'feature_set_id':PREPROCESSING+'-shared-station-context',
            'dimension':192, 'provenance':{'model':model.identity, 'preprocessing':PREPROCESSING,
                'role':'frozen_contextual_model_features_not_observations', 'device':device, 'dtype':'float32',
                'versions':versions, 'adapter_sha256':sha256(Path(__file__)),
                'protocol_sha256':sha256(protocol_path), 'contexts_manifest_sha256':sha256(contexts_path),
                'common_contexts':receipts, 'source_crs_assumption':'EPSG:32613',
                'roi_rule':'sample_location_hull_buffer_15m_positive_pixel_intersection',
                'roi_pooling':'valid_sampled_support_pixel_count_per_patch_date',
                'spatial_dependence':'common_context_attention_and_overlapping_tokens', 'alias_audit':aliases}, 'rows':rows}
