#!/usr/bin/env python3
"""Freeze a label-free protocol or score offline features. Refuses output overwrite; no network.

Raw source labels are isolated from runtime and evaluation QA answers. Feature CSV
uses bundle_id,acquisition_max_date,source_sha256,f0..fN with .metadata.json sidecar.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from agronomy_agent.imagery_assessment import assess, build_protocol, load_source, source_features, extract_spectral_features, compare_features, spectral_spatial_sensitivity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--features', type=Path)
    inputs.add_argument('--source-soils', action='store_true')
    inputs.add_argument('--location-time', action='store_true')
    inputs.add_argument('--spectral-contexts', type=Path, help='Extract fixed spectral feature JSON; no labels opened')
    parser.add_argument('--spatial-sensitivity', action='store_true', help='With --spectral-contexts, emit label-free support/feature shift diagnostics')
    parser.add_argument('--compare-encoder', type=Path, help='Pair --features spectral JSON with encoder JSON, grouped and forward')
    parser.add_argument('--forward-year', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.spectral_contexts:
        if not args.output:
            parser.error('--output required for extraction')
        result = (spectral_spatial_sensitivity if args.spatial_sensitivity else extract_spectral_features)(args.protocol, args.spectral_contexts)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as handle:
            json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        print(json.dumps({'ok_rows':sum(r['status']=='ok' for r in result['rows']), 'total_rows':len(result['rows'])}))
        return
    rows = load_source(args.source)
    if args.freeze:
        result, destination = build_protocol(rows), args.protocol
    else:
        if not args.output:
            parser.error('--output required for assessment')
        protocol = json.loads(args.protocol.read_text())
        features = source_features(rows, protocol, location_time=args.location_time) if args.source_soils or args.location_time else None
        if args.features:
            if args.features.suffix.lower() == '.csv':
                features = json.loads(args.features.with_suffix('.metadata.json').read_text())
                with args.features.open(newline='') as handle:
                    features['rows'] = [{**r, 'features': [r[f'f{i}'] for i in range(features['dimension'])]} for r in csv.DictReader(handle)]
            else:
                features = json.loads(args.features.read_text())
        if args.compare_encoder:
            if not args.features:
                parser.error('--compare-encoder requires --features spectral JSON')
            result = compare_features(rows, protocol, features, json.loads(args.compare_encoder.read_text()))
        else:
            result = assess(rows, protocol, features, forward_year=args.forward_year)
        destination = args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'output': str(destination), 'protocol_id': result['protocol_id']}))


if __name__ == '__main__':
    main()
