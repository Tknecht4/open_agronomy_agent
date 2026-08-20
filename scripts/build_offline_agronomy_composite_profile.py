#!/usr/bin/env python3
"""Build the stable-path Canada-first offline product profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = ROOT / "configs" / "rag.yaml"
ACTIVE_STORE = ROOT / "data" / "derived" / "rag" / "offline_agronomy" / "active" / "store_manifest.json"
US_STORE = ROOT / "data" / "derived" / "rag" / "offline_agronomy" / "us_nrcs" / "store_manifest.json"
OUTPUT_CONFIG = ROOT / "configs" / "rag.yaml"
OUTPUT_POLICY = ROOT / "data" / "manifests" / "runtime_corpus_policy.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_store_shards(store_path: Path) -> list[dict[str, Any]]:
    store = json.loads(store_path.read_text(encoding="utf-8"))
    root = store_path.parent
    values: list[dict[str, Any]] = []
    for item in store.get("shards") or []:
        relative = str(item.get("path") or "")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing declared US release shard: {path}")
        if _sha256(path) != str(item.get("sha256") or ""):
            raise ValueError(f"US release shard hash mismatch: {path}")
        values.append({**item, "path": path.relative_to(ROOT).as_posix()})
    if not values:
        raise ValueError("US release has no shards")
    return values


def build_profile(
    *,
    base_config: Path,
    active_store: Path,
    us_store: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = yaml.safe_load(base_config.read_text(encoding="utf-8")) or {}
    active = json.loads(active_store.read_text(encoding="utf-8"))
    store = json.loads(us_store.read_text(encoding="utf-8"))
    active_shards = _relative_store_shards(active_store)
    us_shards = _relative_store_shards(us_store)
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    # The compact NRCS projection is deliberately absent: the complete
    # source-exact U.S. pack is the only NRCS runtime component and activates
    # only for explicit U.S./NRCS/MLRA requests.
    retrieval["corpus_paths"] = [str(item["path"]) for item in active_shards]
    retrieval["on_demand_corpus_releases"] = [
        {
            "release_id": str(store.get("release_id") or ""),
            "manifest_path": us_store.relative_to(ROOT).as_posix(),
            "activation": "explicit_us_nrcs_or_mlra",
            "jurisdiction": "United States",
            "retrieval_policy": "context_only",
            "authority_boundary": "U.S. material is analogue/context only for Canadian questions.",
        }
    ]
    retrieval["corpus_policy_manifest"] = "data/manifests/runtime_corpus_policy.json"
    retrieval["jurisdiction_ranking"] = {
        "schema_version": "open_agronomy_agent.jurisdiction_ranking.v1",
        "canadian_query_priority": [
            "curated_canadian_source",
            "project_safety_policy",
            "internal_synthesis",
            "open_ontology",
            "US_government_analogue_reference",
            "community_experience",
        ],
        "us_analogue_boundary": "U.S. evidence is labelled analogue context and cannot support Canadian decisive claims.",
        "community_boundary": "Community material is non-decisive and requires source-specific rights and privacy admission before it can be loaded.",
    }
    config["retrieval"] = retrieval
    config["release_profile"] = {
        "profile_id": "offline-agronomy",
        "active_store": active_store.relative_to(ROOT).as_posix(),
        "us_reference_store": us_store.relative_to(ROOT).as_posix(),
        "community_status": "no_archive_community_source_has_a_public_runtime_rights_admission",
    }

    corpora: list[dict[str, Any]] = []
    for shard in active_shards:
        policies = {str(value) for value in shard.get("retrieval_policies") or []}
        name = str(shard["path"])
        if "project_decisive" in name:
            tier, rights, eligibility = "project_safety_policy", "project_authored", "decisive"
        elif "soilwise" in name:
            tier, rights, eligibility = "open_ontology", "CC-BY-4.0", "context_only"
        elif "canadian" in name:
            tier, rights = "curated_canadian_source", "redistributable_with_verified_source_scope"
            eligibility = "decisive" if "requires_live_authority" in policies else "context_only"
        else:
            tier, rights, eligibility = "internal_synthesis", "project_authored", "context_only"
        corpora.append(
            {
                "evidence_tier": tier,
                "path": name,
                "reason": "Source-exact active offline corpus shard.",
                "rights_status": rights,
                "runtime_eligibility": eligibility,
                "sha256": str(shard["sha256"]),
                "shard_policy_role": sorted(policies),
                "source_ids": [],
                "store_profile_id": str(active.get("store_id") or "offline-agronomy"),
                "activation": "startup",
            }
        )
    for shard in us_shards:
        path = str(shard["path"])
        physical = ROOT / path
        corpora.append(
            {
                "evidence_tier": "US_government_analogue_reference",
                "path": path,
                "reason": "Full portable USDA NRCS ecological-site archive. For Canadian questions, it is explicitly labelled U.S. analogue context and cannot establish Canadian labels, law, rates, thresholds, calibration, or field conditions.",
                "rights_status": "US_government_public_source",
                "runtime_eligibility": "context_only",
                "sha256": _sha256(physical),
                "shard_policy_role": "context_only",
                "source_ids": ["nrcs_edit_ecological_site_description_json"],
                "store_profile_id": str(store.get("release_id") or "us-nrcs-full-reference"),
                "activation": "explicit_us_nrcs_or_mlra",
            }
        )
    policy: dict[str, Any] = {"corpora": corpora}
    policy["policy_id"] = "open-agronomy-runtime"
    policy["schema_version"] = "open_agronomy_agent.runtime_corpus_policy.v1"
    policy["composite_release"] = {
        "profile_id": "offline-agronomy",
        "active_store": active_store.relative_to(ROOT).as_posix(),
        "active_store_sha256": str(active.get("store_sha256") or ""),
        "us_reference_store": us_store.relative_to(ROOT).as_posix(),
        "us_reference_store_sha256": str(store.get("store_sha256") or ""),
        "canadian_authority_priority": True,
        "community_sources_loaded": False,
    }
    return config, policy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, default=BASE_CONFIG)
    parser.add_argument("--active-store", type=Path, default=ACTIVE_STORE)
    parser.add_argument("--us-store", type=Path, default=US_STORE)
    parser.add_argument("--output-config", type=Path, default=OUTPUT_CONFIG)
    parser.add_argument("--output-policy", type=Path, default=OUTPUT_POLICY)
    args = parser.parse_args()
    config, policy = build_profile(base_config=args.base_config, active_store=args.active_store, us_store=args.us_store)
    args.output_policy.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    args.output_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(json.dumps({"config": str(args.output_config), "policy": str(args.output_policy), "shards": len(policy["corpora"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
