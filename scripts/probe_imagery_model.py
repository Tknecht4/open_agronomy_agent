#!/usr/bin/env python3
"""Bounded optional EO probe: offline pinned snapshot, synthetic smoke or four NPZ chips.

Run in an isolated torch/timm/numpy/psutil environment. A supervisor retains
failed cells and terminates a child on deadline, RSS >8GiB or swap growth >64MiB.
--chips-manifest JSON: {chips:[{path,date}],cutoff}; NPZ keys
bands[6,H,W], valid_mask[H,W], field_mask[H,W], metadata_json. Real chips must
share a grid. Small native chips require explicit --allow-center-padding.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    tmp.replace(path)


def prepared_input(args):
    import numpy as np
    from agronomy_agent.imagery_models import prepare_stack, sha256
    if not args.chips_manifest:
        rng = np.random.default_rng(72491)
        p = prepare_stack(rng.uniform(.05, .45, (4, 6, 224, 224)).astype(np.float32),
                          np.ones((4, 224, 224), bool), np.ones((224, 224), bool),
                          ['2020-05-01', '2020-05-15', '2020-06-01', '2020-06-15'],
                          40.15, -103.14, cutoff='2020-06-15')
        p['receipt']['input_kind'] = 'synthetic_technical_smoke_not_accuracy'
        return p
    from agronomy_agent.imagery_models import load_chip_manifest
    return load_chip_manifest(args.chips_manifest, allow_center_padding=args.allow_center_padding)



def worker(args):
    import numpy as np
    import psutil
    from agronomy_agent.imagery_models import FrozenPrithvi
    result = {'status': 'running', 'device': args.device, 'dtype': 'float32',
              'stage': 'imports', 'stage_started_monotonic': time.monotonic()}
    path = Path(args.output)
    write(path, result)
    try:
        import torch
        torch.set_num_threads(4)
        if args.cohort_input:
            from agronomy_agent.imagery_models import extract_cohort_features
            def progress(stage, partial=None):
                result.update(stage=stage, stage_started_monotonic=time.monotonic())
                if partial is not None:
                    result['partial_feature_rows'] = partial['rows']
                    result['partial_context_receipts'] = partial['contexts']
                write(path, result)
            payload = extract_cohort_features(args.protocol, args.cohort_input, args.snapshot,
                                              device=args.device, progress=progress, token_output_dir=args.token_output_dir)
            result.pop('partial_feature_rows', None)
            result.pop('partial_context_receipts', None)
            result.update(status='ok', stage='done', feature_payload=payload)
            write(path, result)
            return 0
        p = prepared_input(args)
        result.update(preprocessing=p['receipt'], mps_available=torch.backends.mps.is_available())
        result.update(stage='cold_load', stage_started_monotonic=time.monotonic())
        write(path, result)
        start = time.perf_counter(); model = FrozenPrithvi(args.snapshot, args.device)
        if args.device == 'mps': torch.mps.synchronize()
        result.update(cold_load_seconds=time.perf_counter()-start, identity=model.identity,
                      encoder_parameters=model.parameter_count)
        times = []
        for i in range(6):
            result.update(stage=f'forward_{i}', stage_started_monotonic=time.monotonic())
            write(path, result)
            if args.device == 'mps': torch.mps.synchronize()
            start = time.perf_counter(); feature = model.extract(p)
            if args.device == 'mps': torch.mps.synchronize()
            times.append(time.perf_counter()-start)
        result.update(status='ok', stage='done', warmup_seconds=times[0], warm_forward_seconds=times[1:],
                      feature_dimension=int(feature.size), features=feature.tolist(), finite=bool(np.isfinite(feature).all()),
                      memory={'rss_bytes': psutil.Process().memory_info().rss,
                              'mps_current_allocated_bytes': torch.mps.current_allocated_memory() if args.device=='mps' else None,
                              'mps_driver_allocated_bytes': torch.mps.driver_allocated_memory() if args.device=='mps' else None,
                              'unified_memory_note': 'RSS and MPS overlap; do not add them'},
                      versions={p: importlib.metadata.version(p) for p in ('torch','timm','numpy','einops','psutil')})
    except Exception as error:
        result.update(status='error', error=f'{type(error).__name__}: {error}')
    write(path, result)
    return 0 if result['status']=='ok' else 1


def main(args):
    import psutil
    import numpy as np
    output = Path(args.output)
    cells = []
    targets = [output, *(output.parent / (output.stem + f'-{d}.json') for d in ('cpu','mps'))]
    if any(p.exists() for p in targets):
        raise FileExistsError('probe_output_already_exists_choose_new_path_to_preserve_evidence')
    for device in (('mps',) if args.cohort_input else ('cpu','mps')):
        cell_path = output.parent / (output.stem + f'-{device}.json')
        command = [sys.executable, __file__, '--worker', '--device', device, '--snapshot', args.snapshot, '--output', str(cell_path)]
        if args.chips_manifest: command += ['--chips-manifest', args.chips_manifest]
        if args.cohort_input: command += ['--cohort-input', args.cohort_input, '--protocol', args.protocol]
        if args.token_output_dir: command += ['--token-output-dir', args.token_output_dir]
        if args.allow_center_padding: command += ['--allow-center-padding']
        start_swap = psutil.swap_memory().used
        child = subprocess.Popen(command, env={**os.environ, 'HF_HUB_OFFLINE':'1', 'PYTORCH_ENABLE_MPS_FALLBACK':'0'})
        process = psutil.Process(child.pid)
        started = time.monotonic(); peak_rss = 0; peak_swap_delta = 0; stopped = None
        while child.poll() is None:
            try:
                peak_rss = max(peak_rss, process.memory_info().rss)
                peak_swap_delta = max(peak_swap_delta, psutil.swap_memory().used-start_swap)
                partial = json.loads(cell_path.read_text()) if cell_path.exists() else {}
                stage_start = partial.get('stage_started_monotonic', started)
                if time.monotonic()-stage_start > 120: stopped = 'stage_deadline_120_seconds'
                if peak_rss > 8*1024**3: stopped = 'rss_limit_8_gib'
                if peak_swap_delta > 64*1024**2: stopped = 'system_swap_growth_over_64_mib'
                if stopped:
                    child.kill(); child.wait(); break
            except (psutil.NoSuchProcess, json.JSONDecodeError):
                pass
            time.sleep(.1)
        cell = json.loads(cell_path.read_text()) if cell_path.exists() else {'status':'error','error':'worker_no_receipt'}
        cell.update(observed_peak_rss_bytes=peak_rss, observed_peak_system_swap_growth_bytes=peak_swap_delta,
                    system_swap_start_bytes=start_swap, worker_exit_code=child.returncode)
        if stopped: cell.update(status='stopped', error=stopped)
        write(cell_path, cell); cells.append(cell)
        if stopped: break
    if args.cohort_input:
        if cells[0].get('status') == 'ok':
            payload = cells[0].pop('feature_payload')
            payload['execution_receipt'] = cells[0]
            write(output, payload)
            print(json.dumps({'status':'feature_extraction_completed', 'ok_rows':sum(r['status']=='ok' for r in payload['rows']), 'total_rows':len(payload['rows'])}))
            return 0
        write(output, {'status':'error', 'cells':cells})
        return 1
    result = {'scope':'local_feature_technical_probe_not_agronomic_accuracy', 'cells':cells,
              'fallback_disabled':True, 'batch_size':1, 'forward_deadline_seconds':120,
              'memory_sampling_seconds':.1, 'memory_peak_limit_bytes':8*1024**3}
    if len(cells)==2 and all(c.get('status')=='ok' for c in cells):
        cpu, mps = (np.array(c['features']) for c in cells)
        result['cpu_mps_feature_difference'] = {'max_absolute':float(np.max(np.abs(cpu-mps))),
                                               'mean_absolute':float(np.mean(np.abs(cpu-mps))),
                                               'cosine_similarity':float(cpu@mps/(np.linalg.norm(cpu)*np.linalg.norm(mps)))}
    write(output, result)
    print(json.dumps({k:v for k,v in result.items() if k!='cells'}, indent=2))
    return 0 if len(cells)==2 and all(c.get('status')=='ok' for c in cells) else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--chips-manifest')
    parser.add_argument('--cohort-input', help='Local JSON contexts list; writes all frozen feature rows')
    parser.add_argument('--protocol', help='Required frozen protocol JSON for --cohort-input')
    parser.add_argument('--token-output-dir', help='Optional new local token-cache directory for spatial sensitivity')
    parser.add_argument('--allow-center-padding', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--device', choices=['cpu','mps'], default='cpu', help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.cohort_input and not args.protocol: parser.error('--protocol required with --cohort-input')
    if args.cohort_input and args.chips_manifest: parser.error('choose cohort or single probe input')
    raise SystemExit(worker(args) if args.worker else main(args))
