#!/usr/bin/env python3
"""Rebuild the frozen historical RC2 runtime policy when its evidence is audited.

The active development policy is ``data/manifests/runtime_corpus_policy.json``
and is assembled by ``build_offline_agronomy_composite_profile.py``.  This
script intentionally keeps the historical RC2 bytes and identifiers separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MASTER_ROOT = Path("data/derived/rag/curated_canada/releases/2026-08-14")
DEFAULT_MASTER_PROFILE = "canada-offline-master"
DEFAULT_OUTPUT = Path("data/manifests/runtime_corpus_policy_v2.json")
DEFAULT_POLICY_ID = "open-agronomy-runtime-master-2026-08-14"
POLICY_SCHEMA = "open_agronomy_agent.runtime_corpus_policy.v1"
MASTER_SHARDS = (
    "shards/context_only-canada-offline-master-0001.jsonl",
    "shards/requires_live_authority-canada-offline-master-0001.jsonl",
)
STATIC_CORPORA: tuple[dict[str, str], ...] = (
    {
        "path": "data/seed/agronomy_rag_corpus.jsonl",
        "runtime_eligibility": "context_only",
        "rights_status": "project_authored",
        "evidence_tier": "internal_synthesis",
        "reason": "Project-authored conceptual scaffolding; not document-level or field-specific authority.",
    },
    {
        "path": "data/seed/boundary_rag_corpus.jsonl",
        "runtime_eligibility": "decisive",
        "rights_status": "project_authored",
        "evidence_tier": "project_safety_policy",
        "reason": "Project-authored fail-closed safety boundaries; not a substitute for external agronomic authority.",
    },
    {
        "path": "data/derived/rag/soilwise_rag_corpus.jsonl",
        "runtime_eligibility": "context_only",
        "rights_status": "CC-BY-4.0",
        "evidence_tier": "open_ontology",
        "reason": "Open soil-health concepts and relations; not field-specific management authority.",
    },
    {
        "path": "data/derived/rag/nrcs_esd_rag_corpus_compact_v2.jsonl",
        "runtime_eligibility": "context_only",
        "rights_status": "US_government_public_source",
        "evidence_tier": "government_regional_profile",
        "reason": (
            "Portable section-balanced USDA ecological-site context. Retrieval for Canadian questions "
            "requires an explicit NRCS, MLRA, ecological-site, or US analogue request; it cannot establish "
            "Canadian field condition, calibration, legal authority, product use, rate, threshold, or prescription."
        ),
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def build_policy(
    *,
    root: Path = ROOT,
    master_root: Path = DEFAULT_MASTER_ROOT,
    master_profile: str = DEFAULT_MASTER_PROFILE,
    policy_id: str = DEFAULT_POLICY_ID,
) -> dict[str, Any]:
    root = root.resolve()
    if master_root.is_absolute():
        master_path = master_root.resolve()
        try:
            master_relative = master_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("master corpus root must be inside the repository") from exc
    else:
        master_relative = master_root
        master_path = (root / master_relative).resolve()
    if not master_path.is_relative_to(root):
        raise ValueError("master corpus root escapes the repository")

    profile_policy_path = (
        master_path / "profiles" / master_profile / "runtime_corpus_policy.json"
    )
    source_policy = _load_json(profile_policy_path)
    if source_policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("master profile uses an unsupported runtime corpus policy schema")
    source_rows = {
        str(row.get("path") or ""): row
        for row in source_policy.get("corpora") or []
        if isinstance(row, dict)
    }
    if set(source_rows) != set(MASTER_SHARDS):
        raise ValueError(
            "master profile policy must contain exactly the two declared immutable master shards"
        )

    rows: list[dict[str, Any]] = []
    for metadata in STATIC_CORPORA:
        relative = Path(metadata["path"])
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"active runtime corpus is missing: {relative.as_posix()}")
        rows.append({**metadata, "sha256": _sha256(path)})

    for shard in MASTER_SHARDS:
        source_row = dict(source_rows[shard])
        path = master_path / shard
        if not path.is_file():
            raise FileNotFoundError(f"master runtime shard is missing: {path}")
        actual_sha256 = _sha256(path)
        if actual_sha256 != source_row.get("sha256"):
            raise ValueError(f"master runtime shard failed source-policy SHA-256: {shard}")
        runtime_path = (master_relative / shard).as_posix()
        source_row["path"] = runtime_path
        source_row["runtime_path_reference"] = runtime_path
        rows.append(source_row)

    rows.sort(key=lambda row: str(row["path"]))
    return {
        "schema_version": POLICY_SCHEMA,
        "policy_id": policy_id,
        "default_eligibility": "quarantined",
        "rules": {
            "decisive": (
                "May support an action only within source, jurisdiction, currency, retrieval-policy, "
                "and field-fit limits."
            ),
            "context_only": (
                "May explain concepts or frame questions, but cannot support a high-consequence action."
            ),
            "quarantined": "Must not enter runtime model context.",
        },
        "master_knowledge_release": {
            "path": master_relative.as_posix(),
            "profile_id": master_profile,
            "source_policy_path": profile_policy_path.relative_to(root).as_posix(),
            "source_policy_sha256": _sha256(profile_policy_path),
        },
        "corpora": rows,
        "training_authorization": {
            "granted": False,
            "statement": (
                "Runtime retrieval admission and redistribution do not grant permission to train "
                "or fine-tune a model."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--master-root", type=Path, default=DEFAULT_MASTER_ROOT)
    parser.add_argument("--master-profile", default=DEFAULT_MASTER_PROFILE)
    parser.add_argument("--policy-id", default=DEFAULT_POLICY_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    payload = build_policy(
        root=root,
        master_root=args.master_root,
        master_profile=args.master_profile,
        policy_id=args.policy_id,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "corpus_count": len(payload["corpora"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
