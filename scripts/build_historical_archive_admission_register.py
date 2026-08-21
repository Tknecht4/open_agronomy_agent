#!/usr/bin/env python3
"""Build the reviewed-status register for the historical USB intake.

The intake inventory describes observed bytes.  This register describes the
strictly narrower decision about whether a *source family* may participate in
a successor product, and under which boundary.  It deliberately does not make
the archive's generated outputs or historical benchmark scores current.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import canonical_json, sha256_bytes  # noqa: E402


ARCHIVE_INVENTORY = ROOT / "data/manifests/historical_archive_lexar_20260819.json"
RAW_NRCS_INVENTORY = ROOT / "data/manifests/nrcs_full_raw_source_inventory_20260819.json"
EVAL_CATALOG = ROOT / "data/manifests/historical_evaluation_asset_catalog_20260819.json"
US_STORE = ROOT / "data/derived/rag/offline_agronomy/us_nrcs/store_manifest.json"
DEFAULT_OUTPUT = ROOT / "data/manifests/historical_archive_admission_register_20260820.json"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected an object: {path}")
    return payload


def build_register(
    *,
    archive_inventory: Path,
    raw_nrcs_inventory: Path,
    evaluation_catalog: Path,
    us_store: Path,
) -> dict[str, Any]:
    archive = _load(archive_inventory)
    raw = _load(raw_nrcs_inventory)
    evaluation = _load(evaluation_catalog)
    store = _load(us_store)
    if raw.get("source_archive_inventory_sha256") != archive.get("inventory_sha256"):
        raise ValueError("raw NRCS inventory is not bound to the supplied archive inventory")
    if str(store.get("raw_inventory_sha256") or "") != str(raw.get("inventory_sha256") or ""):
        raise ValueError("U.S. successor store is not bound to the supplied raw NRCS inventory")
    if evaluation.get("archive_git_revision") != archive.get("archive_git_revision"):
        raise ValueError("historical evaluation catalog is not bound to the supplied archive revision")

    records: list[dict[str, Any]] = [
        {
            "source_family": "usda_nrcs_ecological_site_json",
            "status": "admitted",
            "admission_scope": "offline-agronomy active explicit-U.S.-analogue component",
            "jurisdiction": "United States",
            "runtime_role": "context_only_us_analogue",
            "rights_basis": "US_government_public_source_with_citation",
            "reproducibility": "hash-bound raw JSON inventory to immutable 16 MiB-or-smaller JSONL shards",
            "bound_artifacts": {
                "raw_inventory_sha256": raw["inventory_sha256"],
                "successor_store_sha256": store["store_sha256"],
                "rows": store["rows"],
            },
            "prohibitions": [
                "Canadian legal authority",
                "Canadian product-label authority",
                "Canadian rates or thresholds",
                "Canadian field calibration or field-condition authority",
            ],
        },
        {
            "source_family": "historical_aiagribench_style_proxy",
            "status": "candidate",
            "admission_scope": "failure-mode review and separately authored successor-case harvesting only",
            "jurisdiction": "mixed_or_not_established",
            "runtime_role": "not_runtime_data",
            "rights_basis": "local historical proxy; upstream benchmark provenance and reuse rights not established",
            "reproducibility": "hash-bound historical catalog only",
            "bound_artifacts": {"catalog_sha256": evaluation["catalog_sha256"]},
            "prohibitions": [
                "RC3 pooling",
                "official benchmark comparison",
                "leaderboard or model-promotion claim",
                "evaluation-suite import without duplicate, split, and licence review",
            ],
        },
        {
            "source_family": "historical_forum_and_community_corpora",
            "status": "candidate",
            "admission_scope": "source-specific rights, privacy, attribution, and redistributability review required",
            "jurisdiction": "mixed_or_not_established",
            "runtime_role": "not_runtime_data",
            "rights_basis": "unknown until each upstream source is reviewed",
            "reproducibility": "archive hash alone is not redistribution permission",
            "prohibitions": [
                "prescription support",
                "diagnosis support",
                "legal or regulatory support",
                "replacement of official Canadian guidance",
            ],
        },
        {
            "source_family": "historical_spatial_layers_and_caches",
            "status": "candidate",
            "admission_scope": "optional hash-bound install pack after source, portability, and field-boundary review",
            "jurisdiction": "mixed_or_not_established",
            "runtime_role": "not_runtime_data",
            "rights_basis": "per-layer review required",
            "reproducibility": "raw and derived spatial artifacts remain external install-pack candidates",
            "prohibitions": ["implicit local-machine path dependency", "unresolved field-boundary inference"],
        },
        {
            "source_family": "private_and_secret_pattern_archive_material",
            "status": "quarantined",
            "admission_scope": "manual security and fixture review only",
            "jurisdiction": "not_applicable",
            "runtime_role": "not_runtime_data",
            "rights_basis": "not_applicable",
            "reproducibility": "intake path and hash retained without contents in this register",
            "prohibitions": ["public release", "runtime loading", "benchmark payload use"],
        },
        {
            "source_family": "macos_sidecars_caches_and_superseded_generated_outputs",
            "status": "rejected",
            "admission_scope": "historical inventory only",
            "jurisdiction": "not_applicable",
            "runtime_role": "not_runtime_data",
            "rights_basis": "not_applicable",
            "reproducibility": "not a source-data lineage basis",
            "prohibitions": ["runtime loading", "public release", "benchmark evidence substitution"],
        },
    ]
    payload: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.historical_archive_admission_register.v1",
        "decision_date": "2026-08-20",
        "archive_inventory_path": archive_inventory.relative_to(ROOT).as_posix(),
        "archive_inventory_sha256": archive["inventory_sha256"],
        "archive_scope_boundary": (
            "The intake receipt covers the source, implementation, configuration, documentation, and selected "
            "historical-data roots recorded in that receipt. Unhashed operator caches, virtual environments, and "
            "volatile execution outputs are not evidence of source admission and remain excluded from this register."
        ),
        "status_semantics": {
            "admitted": "Allowed only in the declared successor scope and under all listed policy boundaries.",
            "candidate": "Observed but not allowed in runtime, public release, or benchmark claims.",
            "quarantined": "Blocked pending a security, privacy, or manual-review disposition.",
            "rejected": "Retained only as historical inventory, never a source-data input.",
        },
        "records": records,
    }
    payload["register_sha256"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-inventory", type=Path, default=ARCHIVE_INVENTORY)
    parser.add_argument("--raw-nrcs-inventory", type=Path, default=RAW_NRCS_INVENTORY)
    parser.add_argument("--evaluation-catalog", type=Path, default=EVAL_CATALOG)
    parser.add_argument("--us-store", type=Path, default=US_STORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_register(
        archive_inventory=args.archive_inventory,
        raw_nrcs_inventory=args.raw_nrcs_inventory,
        evaluation_catalog=args.evaluation_catalog,
        us_store=args.us_store,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "register_sha256": payload["register_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
