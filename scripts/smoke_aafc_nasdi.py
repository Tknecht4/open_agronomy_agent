#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from agronomy_agent import local_tools
from agronomy_agent.paths import repo_path


SCHEMA_VERSION = "open_agronomy_agent.aafc_nasdi_live_smoke.v1"
DEFAULT_OUTPUT = "outputs/tool_smoke/aafc_nasdi_live_latest.json"


def run_smoke(
    *,
    latitude: float = 50.445,
    longitude: float = -104.617,
    time_window: str | None = None,
    output: str | Path = DEFAULT_OUTPUT,
    timeout: int = 20,
) -> dict[str, Any]:
    result = local_tools.aafc_nasdi_agroclimate(
        latitude=latitude,
        longitude=longitude,
        province="SK",
        indicators=tuple(local_tools.AAFC_NASDI_INDICATORS),
        time_window=time_window,
        cache_dir="outputs/tool_cache/aafc_nasdi_live_smoke",
        timeout=timeout,
    )
    required = set(local_tools.AAFC_NASDI_INDICATORS)
    observed = set(result.get("indicator_summary") or {})
    failures = []
    if result.get("status") not in {"available", "partial_available"}:
        failures.append(f"adapter status was {result.get('status')}")
    if required - observed:
        failures.append(f"missing indicators: {', '.join(sorted(required - observed))}")
    if not result.get("observation_end"):
        failures.append("observation end date missing")
    if not all(item.get("object_id") and item.get("catalog_name") for item in result.get("observations") or []):
        failures.append("locked catalog-raster lineage missing")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "mode": "live_public_endpoint",
        "passed": not failures,
        "failures": failures,
        "result": result,
        "boundary": (
            "This live smoke proves AAFC NASDI endpoint reachability and the bounded adapter contract at one point. "
            "It does not validate field truth, a forecast, ET, soil moisture, or a management prescription."
        ),
    }
    output_path = repo_path(str(output))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live AAFC NASDI point-adapter smoke check.")
    parser.add_argument("--lat", type=float, default=50.445)
    parser.add_argument("--lon", type=float, default=-104.617)
    parser.add_argument("--time-window", default=None, help="Optional single NASDI window for every indicator; default uses each product's native profile window.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    payload = run_smoke(
        latitude=args.lat,
        longitude=args.lon,
        time_window=args.time_window,
        output=args.output,
        timeout=args.timeout,
    )
    print(json.dumps({"output": str(repo_path(args.output)), "passed": payload["passed"], "failures": payload["failures"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
