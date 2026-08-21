#!/usr/bin/env python3
"""Validate the unadmitted Canadian offline-source research queue."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.offline_source_admission import (  # noqa: E402
    DEFAULT_MANIFEST_PATH,
    load_offline_source_admission_candidates,
    source_admission_candidate_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / DEFAULT_MANIFEST_PATH,
        help="candidate-only admission registry to validate",
    )
    args = parser.parse_args()
    payload = load_offline_source_admission_candidates(args.manifest)
    print(json.dumps(source_admission_candidate_summary(payload), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
