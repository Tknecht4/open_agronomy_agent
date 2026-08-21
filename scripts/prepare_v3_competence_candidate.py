#!/usr/bin/env python3
"""Acquire, verify, and project the public v3 competence-candidate inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import urlopen

from agronomy_agent.v3_competence_candidate import build_bundle, canonical_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/open_agronomy_v3_competence_candidate.json"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(canonical_json(row) for row in rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-csv", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/v3_competence_candidate/inputs")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    source_csv = args.source_csv
    if source_csv is None:
        source_csv = output / str(config["external_dataset"]["filename"])
    elif not source_csv.is_absolute():
        source_csv = ROOT / source_csv
    if args.download:
        source_csv.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(str(config["external_dataset"]["download_url"]), timeout=60) as response:
            source_csv.write_bytes(response.read())
    if not source_csv.is_file():
        raise FileNotFoundError("source CSV is absent; provide --source-csv or use --download")
    regional_source = ROOT / str(config["regional_source_suite"])
    comparison_paths = sorted((ROOT / "data/eval").glob("*.jsonl"))
    manifest, external, regional = build_bundle(
        config=config,
        source_csv=source_csv,
        regional_source=regional_source,
        comparison_paths=comparison_paths,
    )
    _write_jsonl(output / "external_cases.jsonl", external)
    _write_jsonl(output / "regional_cases.jsonl", regional)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**manifest, "output_dir": str(output)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
