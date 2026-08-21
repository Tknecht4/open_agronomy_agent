#!/usr/bin/env python3
"""Validate a locally built curated knowledge store without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.curated_knowledge_store import (  # noqa: E402
    validate_curated_knowledge_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify curated-store hashes, source rights snapshots, policy segregation, "
            "and exact profile config/policy path agreement."
        )
    )
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=ROOT / "data" / "manifests" / "canada_agronomy_sources.json",
    )
    parser.add_argument(
        "--expect-profile",
        action="append",
        default=[],
        help="Require this exact set of profile IDs when one or more are supplied.",
    )
    args = parser.parse_args()
    report = validate_curated_knowledge_store(
        store_root=args.store_root,
        source_manifest_path=args.source_manifest,
        expected_profile_ids=set(args.expect_profile) if args.expect_profile else None,
        repository_root=ROOT,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
