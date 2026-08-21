#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.offline_readiness import build_offline_readiness


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and record every local asset required before leaving connectivity."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--rag-config", type=Path)
    parser.add_argument("--hf-hub-cache", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument(
        "--spatial-pack-root",
        type=Path,
        help="verified external spatial-pack directory; omitted means RAG-only offline readiness",
    )
    parser.add_argument(
        "--spatial-profile",
        help="declared offline spatial profile required for --spatial-pack-root",
    )
    parser.add_argument(
        "--spatial-profile-manifest",
        type=Path,
        help="profile contract; defaults to data/manifests/offline_spatial_profiles_v1.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    report = build_offline_readiness(
        root=root,
        runtime_manifest_path=args.runtime_manifest,
        model_config_path=args.model_config,
        rag_config_path=args.rag_config,
        hub_cache=args.hf_hub_cache,
        state_dir=args.state_dir,
        spatial_pack_root=args.spatial_pack_root,
        spatial_profile_id=args.spatial_profile,
        spatial_profile_manifest_path=args.spatial_profile_manifest,
    )
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if args.require_ready and not report["offline_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
