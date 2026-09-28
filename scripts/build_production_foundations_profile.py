#!/usr/bin/env python3
"""Compose the active offline profile with the bounded foundations supplement.

Use an ignored output path for an A/B candidate. Writing the active paths is a
separate, explicit promotion step after benchmark and corpus gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_offline_agronomy_composite_profile import (  # noqa: E402
    ACTIVE_STORE,
    BASE_CONFIG,
    US_STORE,
    build_profile,
)

SUPPLEMENT_STORE = ROOT / "data/derived/rag/offline_agronomy/production_foundations/v1/store_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compose(*, output_config: Path, output_policy: Path, supplement_store: Path = SUPPLEMENT_STORE) -> tuple[dict, dict]:
    config, policy = build_profile(base_config=BASE_CONFIG, active_store=ACTIVE_STORE, us_store=US_STORE)
    supplement_store = supplement_store.resolve()
    if not supplement_store.is_relative_to(ROOT):
        raise ValueError("supplement store must be inside this repository")
    manifest = json.loads(supplement_store.read_text(encoding="utf-8"))
    shards = manifest.get("shards") or []
    store_id = manifest.get("store_id")
    if store_id not in {"production-foundations-v1", "production-foundations-method-v2"} or len(shards) != 1:
        raise ValueError("unexpected foundations release contract")
    shard = shards[0]
    shard_path = supplement_store.parent / str(shard["path"])
    if _sha256(shard_path) != shard.get("sha256"):
        raise ValueError("foundations shard hash mismatch")
    relative = shard_path.relative_to(ROOT).as_posix()
    output_config = output_config.resolve()
    output_policy = output_policy.resolve()
    if not output_config.is_relative_to(ROOT) or not output_policy.is_relative_to(ROOT):
        raise ValueError("output paths must be inside the repository")
    config["retrieval"]["corpus_paths"].append(relative)
    config["retrieval"]["corpus_policy_manifest"] = output_policy.relative_to(ROOT).as_posix()
    config["release_profile"]["production_foundations_store"] = supplement_store.relative_to(ROOT).as_posix()
    if store_id == "production-foundations-method-v2":
        config["release_profile"]["method_transfer_store"] = supplement_store.relative_to(ROOT).as_posix()
    receipt = json.loads((supplement_store.parent / str(manifest["source_receipt_path"])).read_text(encoding="utf-8"))
    if store_id == "production-foundations-method-v2":
        config["release_profile"]["method_support_receipt_sha256"] = receipt["source_support_receipt_sha256"]
    policy["corpora"].append({
        "evidence_tier": "internal_synthesis",
        "path": relative,
        "reason": "Source-linked, project-authored production and farm-business foundations; context only; external source snapshots are identified by hash but not redistributed.",
        "rights_status": "project_authored",
        "runtime_eligibility": "context_only",
        "sha256": str(shard["sha256"]),
        "shard_policy_role": ["context_only"],
        "source_ids": (["mb_spring_cereal_seeding_rates", "aafc_growing_degree_days_service", "mb_special_crop_costs", "isu_partial_budget", "usda_ers_financial_ratios", "usda_nrcs_nutrient_management", "usda_ars_wholefarm"] if store_id == "production-foundations-v1" else receipt["source_ids"]),
        "store_profile_id": store_id,
        "activation": "startup",
    })
    policy["corpora"].sort(key=lambda row: str(row["path"]))
    policy["composite_release"]["production_foundations_store"] = supplement_store.relative_to(ROOT).as_posix()
    policy["composite_release"]["production_foundations_store_sha256"] = manifest["store_sha256"]
    output_policy.parent.mkdir(parents=True, exist_ok=True)
    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_policy.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    output_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config, policy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-config", type=Path, default=ROOT / "outputs/production_foundations_candidate/rag.yaml")
    parser.add_argument("--output-policy", type=Path, default=ROOT / "outputs/production_foundations_candidate/runtime_corpus_policy.json")
    parser.add_argument("--supplement-store", type=Path, default=SUPPLEMENT_STORE)
    args = parser.parse_args()
    _, policy = compose(output_config=args.output_config, output_policy=args.output_policy, supplement_store=args.supplement_store)
    print(json.dumps({"config": str(args.output_config), "policy": str(args.output_policy), "corpora": len(policy["corpora"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
