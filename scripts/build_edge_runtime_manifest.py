#!/usr/bin/env python3
"""Build a deterministic inventory of assets shipped in the edge image."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from agronomy_agent.corpus_governance import (  # noqa: E402
    corpus_policy_for_path,
    load_corpus_policy,
    partition_runtime_corpus_paths,
)


SCHEMA_VERSION = "open_agronomy_agent.edge_runtime_manifest.v1"
RAG_CONFIG = "configs/rag_governed_runtime_v1.yaml"
MODEL_CONFIG = "configs/model_gemma4_e2b_interface_v2.yaml"
CONTROL_PATHS = (
    "Containerfile",
    "Containerfile.overlay",
    ".dockerignore",
    "requirements-container.txt",
    "pyproject.toml",
    "docker-compose.edge.yml",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "container/.env.example",
    "container/runtime-defaults.env",
    "container/README.md",
    "container/runtime-common.sh",
    "container/build-image.sh",
    "container/build-overlay-image.sh",
    "container/entrypoint.sh",
    "container/model-host.sh",
    "container/apple.sh",
    "container/docker.sh",
    "container/import-release.sh",
    "container/release.sh",
    "scripts/verify_edge_release.py",
    "scripts/repair_edge_oci_archive.py",
    "scripts/validate_edge_runtime_translation.py",
    "data/manifests/canada_agronomy_sources.json",
    "data/manifests/canada_geospatial_sources.json",
    "data/manifests/source_licensing_matrix.json",
    "data/manifests/advisory_blocker_baseline_v1.json",
    "data/manifests/canadian_official_source_census_20260724.json",
    "data/manifests/canadian_applied_guidance_slate_20260726.json",
    "data/manifests/applied_guidance_review_packet_registry_20260726.json",
    "data/manifests/french_applied_guidance_source_disposition_20260726.json",
    "data/manifests/model_adaptation_decision_20260727.json",
    (
        "data/manifests/source_asset_access_receipts/"
        "aafc_western_field_crop_pest_guide_fr_2018.json"
    ),
    (
        "data/manifests/source_asset_access_receipts/"
        "aafc_western_field_crop_pest_guide_2018_archive_continuation.json"
    ),
    (
        "data/manifests/source_asset_access_receipts/"
        "aafc_prairie_cutworms_guide_fr_2017.json"
    ),
    (
        "data/manifests/source_asset_access_receipts/"
        "aafc_prairie_cutworms_guide_2017_archive_continuation.json"
    ),
    (
        "data/manifests/source_asset_access_receipts/"
        "aafc_prairie_wireworms_guide_fr_2021.json"
    ),
    (
        "data/manifests/source_asset_access_receipts/"
        "aafc_prairie_wireworms_guide_2021_archive_continuation.json"
    ),
    "data/manifests/applied_guidance_source_preflight_registry_20260726.json",
    "data/evals/canadian_applied_guidance_admission_eval_contract_20260726.json",
    "docs/canadian_corpus_v8_coverage_20260720.md",
    "docs/canadian_agronomy_corpus_promotion_audit_v8_20260720.json",
    "docs/canadian_agronomy_corpus_promotion_audit_v8_20260720.md",
    "docs/canadian_v8_promotion_full_path_gate.md",
    "docs/canadian_crop_health_indices_v7_direct_semantic_review_20260719.json",
    "docs/canadian_crop_health_indices_v7_direct_semantic_review_20260719.md",
    "docs/canadian_conference_transfer_gate_20260720.md",
    "docs/canadian_conference_source_validation_v1_rc8_20260721.json",
    "docs/canadian_conference_source_validation_v1_rc8_20260721.md",
    "docs/canadian_ab_nutrient_planning_v6_direct_semantic_review_20260719.json",
    "docs/canadian_ab_nutrient_planning_v6_direct_semantic_review_20260719.md",
    "data/derived/geo_layers/bc_agriculture_capability_manifest.json",
    "data/derived/geo_layers/sk_thematic_soil_manifest.json",
    "data/derived/geo_layers/ca_soil_erosion_risk_manifest.json",
    "data/derived/geo_layers/pei_detailed_soil_manifest.json",
    "data/derived/geo_layers/ns_pictou_detailed_soil_manifest.json",
    "data/derived/geo_layers/ab_detailed_soil_manifest.json",
    "data/derived/geo_layers/mb_detailed_soil_manifest.json",
    "docs/canadian_geospatial_sources_validation_20260721.json",
    "docs/canadian_geospatial_sources_coverage_20260721.md",
    "docs/canadian_applied_guidance_rights_audit_20260721.md",
    "docs/canadian_agronomy_corpus_promotion_audit_v13_20260725.json",
    "docs/canadian_agronomy_corpus_promotion_audit_v13_20260725.md",
    "docs/canada_agronomy_ontario_context_v1_audit_20260725.md",
    "docs/conference_freeze_knowledge_gap_matrix_20260725.md",
    "docs/runtime_knowledge_sufficiency_audit_20260725.md",
    "docs/french_applied_guidance_source_disposition_20260726.md",
    "docs/applied_guidance_source_preflight_registry_20260726.md",
    "docs/provincial_applied_guidance_admission_queue_20260724.md",
    "docs/canadian_conference_semantic_review_v3_20260725.json",
    "docs/canadian_conference_semantic_review_v3_20260725.md",
    "outputs/knowledge_freeze_readiness_20260725/runtime_corpus_audit_final_mvp.json",
    "outputs/knowledge_freeze_readiness_20260725/conference_freeze_gap_matrix.json",
    "outputs/knowledge_freeze_readiness_20260725/runtime_knowledge_sufficiency.json",
    "outputs/knowledge_freeze_readiness_20260725/backend_pytest.xml",
    "outputs/knowledge_freeze_readiness_20260725/frontend_vitest.json",
    "outputs/tool_smoke/ppls_adapter_modes_latest.json",
    "outputs/tool_smoke/keyed_public_adapters_latest.json",
    "outputs/tool_smoke/public_adapter_regional_matrix_latest.json",
)
BENCHMARK_ROOTS = (
    "outputs/evals/aiagribench_proxy_iter17_full_live_precision_economics_cleanup",
    "outputs/evals/expert_review_807_blinded_semantic_20260718",
    "outputs/evals/canadian_semantic_reserve_v1_qwen2b",
    "outputs/evals/public_domain_coverage_full_live_1056_current_rescore_contract_repairs_final",
    "outputs/evals/public_claim_stress_focus_full_live_20260710_submission_hygiene_rescore",
    "outputs/evals/public_shadow_heldout",
    "outputs/evals/agentic_gap_matrix",
    "outputs/evals/general_agent_semantic_control_v5_240/agronomic_rag_20260715T031940Z",
    "outputs/evals/canadian_conference_transfer_gate_gemma4_generalized_v5/agronomic_rag_20260720T224916Z",
    "outputs/evals/canadian_conference_preflight_v2_rc20_final_20260725",
    (
        "outputs/evals/"
        "canadian_conference_transfer_gate_v2_rc20_release_candidate_v2_gemma4_20260725/"
        "agronomic_rag_20260725T035257Z"
    ),
)
RUNTIME_POLICY_ROOTS = ("plans",)
RUNTIME_ASSET_ROOTS = (
    "src/agronomy_agent",
    "frontend/src",
    "frontend/public",
    "scripts",
    "configs",
    "data/manifests",
    "data/eval",
    "data/snapshots",
    "docs/open_agronomy_agent_whitepaper_20260709",
    "docs/alberta_applied_guidance_validation_20260725",
    "docs/bc_aem_nutrient_application_plan_validation_20260727",
    "docs/manitoba_applied_guidance_validation_20260725",
    "docs/manitoba_fertilizer_check_stamp_validation_20260726",
    "docs/manitoba_stored_grain_monitoring_validation_20260726",
    "docs/french_applied_guidance_validation_20260725",
)
IGNORED_TREE_NAMES = {".DS_Store", ".pytest_cache", "__pycache__", "dist", "node_modules"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_entry(root: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _tree_digest(root: Path, path: Path) -> dict[str, Any]:
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file()
        and not any(part in IGNORED_TREE_NAMES for part in item.relative_to(path).parts)
        and item.suffix != ".pyc"
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        relative = str(item.relative_to(root))
        file_sha = _sha256(item)
        total_bytes += item.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return {
        "path": str(path.relative_to(root)),
        "file_count": len(files),
        "bytes": total_bytes,
        "sha256": digest.hexdigest(),
    }


def build_manifest(root: Path) -> dict[str, Any]:
    rag_path = root / RAG_CONFIG
    rag = yaml.safe_load(rag_path.read_text(encoding="utf-8")) or {}
    retrieval = rag.get("retrieval") or {}
    configured_corpora = [str(value) for value in retrieval.get("corpus_paths") or []]
    graph_values = [str(value) for value in retrieval.get("graph_paths") or []]
    policy_value = retrieval.get("corpus_policy_manifest")
    policy = load_corpus_policy(root, policy_value)
    included_corpora, excluded_corpora = partition_runtime_corpus_paths(
        configured_corpora,
        policy,
    )
    knowledge_values = [*map(str, included_corpora), *graph_values]
    required = [
        RAG_CONFIG,
        MODEL_CONFIG,
        *CONTROL_PATHS,
        *([str(policy_value)] if policy_value else []),
        *knowledge_values,
    ]
    missing = [value for value in required if not (root / value).is_file()]
    missing.extend(value for value in BENCHMARK_ROOTS if not (root / value).is_dir())
    missing.extend(value for value in RUNTIME_POLICY_ROOTS if not (root / value).is_dir())
    missing.extend(value for value in RUNTIME_ASSET_ROOTS if not (root / value).is_dir())
    if missing:
        raise FileNotFoundError("edge runtime inputs are missing: " + ", ".join(missing))

    knowledge_entries = [_file_entry(root, root / value, "runtime_knowledge") for value in knowledge_values]
    for value in included_corpora:
        policy_row = corpus_policy_for_path(value, policy)
        expected_sha = str((policy_row or {}).get("sha256") or "")
        actual_sha = _sha256(root / str(value))
        if expected_sha != actual_sha:
            raise ValueError(f"runtime corpus failed policy SHA-256 validation: {value}")
    excluded_entries = []
    for row in excluded_corpora:
        policy_row = corpus_policy_for_path(row.get("path") or "", policy) or {}
        excluded_entries.append(
            {
                **row,
                "rights_status": policy_row.get("rights_status"),
                "expected_sha256": policy_row.get("sha256"),
                "included": False,
            }
        )
    control_entries = [_file_entry(root, root / value, "runtime_control") for value in required if value not in knowledge_values]
    geo_cache = _tree_digest(root, root / "data/derived/geo_cache")
    bundled_geo_layers = _tree_digest(root, root / "data/derived/geo_layers")
    benchmark_entries = [_tree_digest(root, root / value) for value in BENCHMARK_ROOTS]
    policy_entries = [_tree_digest(root, root / value) for value in RUNTIME_POLICY_ROOTS]
    asset_entries = [_tree_digest(root, root / value) for value in RUNTIME_ASSET_ROOTS]
    all_digests = [
        entry["sha256"]
        for entry in (
            *control_entries,
            *knowledge_entries,
            *policy_entries,
            *asset_entries,
            *benchmark_entries,
            geo_cache,
            bundled_geo_layers,
        )
    ]
    contract_digest = hashlib.sha256("\n".join(all_digests).encode("ascii")).hexdigest()
    source_epoch = os.getenv("SOURCE_DATE_EPOCH")
    generated_at = (
        dt.datetime.fromtimestamp(int(source_epoch), tz=dt.UTC)
        if source_epoch
        else dt.datetime.now(dt.UTC)
    ).replace(microsecond=0).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "pass",
        "contract_sha256": contract_digest,
        "image_contract": {
            "containerfile": "Containerfile",
            "application_port": 8080,
            "state_mount": "/state",
            "model_protocol": "openai_compatible_http",
            "model_endpoint_path": "/v1/chat/completions",
            "model_weights_in_image": False,
            "native_host_inference": "mlx_lm.server",
            "apple_launcher": "container/apple.sh",
            "docker_launcher": "container/docker.sh",
            "docker_compose": "docker-compose.edge.yml",
        },
        "model": {
            "config_path": MODEL_CONFIG,
            "configured_model_id": (yaml.safe_load((root / MODEL_CONFIG).read_text(encoding="utf-8")) or {}).get("serving_model_id"),
            "included": False,
            "reason": "MLX and Metal run natively on the macOS host; the Linux image calls the host over loopback-only HTTP.",
        },
        "rag_config": RAG_CONFIG,
        "corpus_policy_manifest": str(policy_value) if policy_value else None,
        "configured_corpus_count": len(configured_corpora),
        "included_corpus_count": len(included_corpora),
        "excluded_corpus_count": len(excluded_entries),
        "excluded_corpora": excluded_entries,
        "runtime_knowledge": knowledge_entries,
        "runtime_knowledge_bytes": sum(entry["bytes"] for entry in knowledge_entries),
        "runtime_policies": policy_entries,
        "runtime_assets": asset_entries,
        "geo_cache_seed": geo_cache,
        "bundled_geo_layers": bundled_geo_layers,
        "benchmark_evidence": benchmark_entries,
        "control_files": control_entries,
    }


def _preserve_generated_at(output: Path, manifest: dict[str, Any]) -> None:
    if not output.is_file():
        return
    try:
        existing = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if existing.get("contract_sha256") == manifest.get("contract_sha256") and existing.get("generated_at"):
        manifest["generated_at"] = existing["generated_at"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("container/runtime_manifest.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    manifest = build_manifest(root)
    _preserve_generated_at(output, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("status", "contract_sha256", "runtime_knowledge_bytes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
