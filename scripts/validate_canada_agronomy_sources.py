#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.canada_sources import load_canada_source_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Canadian agronomy source and use-policy registry.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "manifests" / "canada_agronomy_sources.json",
    )
    args = parser.parse_args()
    manifest = load_canada_source_manifest(args.manifest)
    sources = manifest["sources"]
    summary = {
        "schema_version": manifest["schema_version"],
        "sources": len(sources),
        "jurisdictions": dict(sorted(Counter(j for source in sources for j in source["jurisdiction"]).items())),
        "license_status": dict(sorted(Counter(source["license"]["status"] for source in sources).items())),
        "distributable_sources": [source["id"] for source in sources if source["use_policy"]["distributable_bundle"]],
        "local_rag_sources": [source["id"] for source in sources if source["use_policy"]["local_rag"]],
        "live_reference_sources": [source["id"] for source in sources if source["use_policy"]["live_retrieval"]],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
