"""Plan and select bounded field imagery using explicit support requirements."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agronomy_agent.geospatial.scene_quality import POLICY_VERSION
from agronomy_agent.imagery_selection import PROVIDERS, build_selection_plan, select_from_plan
from agronomy_agent.imagery_budget import DEFAULT_MAX_CACHE_BYTES, DEFAULT_MIN_FREE_BYTES


def _read(path: Path, limit: int) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds byte limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="freeze one bounded STAC page without pixels")
    plan.add_argument("--geometry", required=True, type=Path)
    plan.add_argument("--provider", required=True, choices=PROVIDERS)
    plan.add_argument("--start-date", required=True)
    plan.add_argument("--end-date", required=True)
    plan.add_argument("--index", required=True, choices=("NDVI", "NDMI"))
    plan.add_argument("--support", required=True, choices=("field", "interior"))
    plan.add_argument("--min-valid-fraction", required=True, type=float)
    plan.add_argument("--candidate-limit", type=int, default=3)
    plan.add_argument("--cloud-buffer-m", type=int)
    plan.add_argument("--edge-buffer-m", type=int)
    run = commands.add_parser("run", help="assess every frozen candidate and retain the decision")
    run.add_argument("--plan", required=True, type=Path)
    run.add_argument("--cache-root", required=True, type=Path)
    run.add_argument("--budget-root", type=Path)
    run.add_argument("--max-cache-bytes", type=int, default=DEFAULT_MAX_CACHE_BYTES)
    run.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    run.add_argument("--max-cog-bytes", type=int, default=128 * 1024**2)
    run.add_argument("--per-scene-cog-bytes", type=int, default=32 * 1024**2)
    run.add_argument("--max-cog-requests", type=int, default=512)
    for sub in (plan, run):
        sub.add_argument("--online", action="store_true", help="explicitly permit bounded public egress")
        sub.add_argument("--output", required=True, type=Path, help="new private JSON artifact; never overwritten")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            payload = _read(args.geometry, 128 * 1024)
            geometry = payload.get("geometry") if payload.get("type") == "Feature" else payload
            options = {key: value for key, value in (("cloud_buffer_m", args.cloud_buffer_m),
                                                    ("edge_buffer_m", args.edge_buffer_m)) if value is not None}
            policy = {"version": POLICY_VERSION, "index": args.index, "support": args.support,
                      "min_valid_fraction": args.min_valid_fraction}
        else:
            payload = _read(args.plan, 2 * 1024**2)
        # Reserve a new private output before any discovery/pixel egress. An
        # interrupted command leaves an incomplete artifact, never an old result.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except (OSError, ValueError) as exc:
        parser.error(f"input/output admission failed ({type(exc).__name__}); output must be new and its parent must exist")
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        try:
            mode = "online" if args.online else "offline"
            if args.command == "plan":
                result = build_selection_plan(geometry, args.provider, args.start_date, args.end_date,
                                              policy=policy, limit=args.candidate_limit,
                                              processing=options, network_mode=mode)
            else:
                result = select_from_plan(payload, cache_root=args.cache_root, network_mode=mode,
                    budget_root=args.budget_root, max_cache_bytes=args.max_cache_bytes,
                    min_free_bytes=args.min_free_bytes, max_cog_bytes=args.max_cog_bytes,
                    per_scene_cog_bytes=args.per_scene_cog_bytes, max_cog_requests=args.max_cog_requests)
        except (OSError, ValueError, RuntimeError) as exc:
            result = {"schema_version": "imagery-selection-cli-failure.v1", "status": "unavailable",
                      "reason": "invalid_request_or_processing_failure", "error_type": type(exc).__name__}
        json.dump(result, destination, indent=2, allow_nan=False)
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "selected_scene_id": result.get("selected_scene_id")}))
    if result["status"] not in ("ready", "selected", "no_scene", "no_eligible_scene"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
