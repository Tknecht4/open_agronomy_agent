#!/usr/bin/env python3
"""Measure successor corpus provenance completeness without promoting it.

The audit is deliberately stricter than legacy runtime loading.  It reports
which components meet the new source-exact/quality-ledger contract and blocks
promotion of a composite profile until *every* runtime row does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import quality_ledger_status, source_locator_status  # noqa: E402


DEFAULT_CONFIG = ROOT / "configs/rag.yaml"
DEFAULT_OUTPUT = ROOT / "data/manifests/offline_corpus_quality_audit.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configured_paths(config: dict[str, Any], root: Path) -> list[tuple[str, str]]:
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    entries = [(str(path), "direct_startup") for path in retrieval.get("corpus_paths") or []]
    for release in retrieval.get("on_demand_corpus_releases") or []:
        if not isinstance(release, dict):
            raise ValueError("on-demand corpus release entry must be an object")
        manifest_path = root / str(release.get("manifest_path") or "")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for shard in manifest.get("shards") or []:
            entries.append(((manifest_path.parent / str(shard["path"])).relative_to(root).as_posix(), "on_demand"))
    return entries


def audit(config_path: Path, *, root: Path) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    policy_path = root / str(retrieval.get("corpus_policy_manifest") or "")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy_by_path = {str(item.get("path") or ""): item for item in policy.get("corpora") or [] if isinstance(item, dict)}
    components: list[dict[str, Any]] = []
    total = Counter()
    for relative, activation in _configured_paths(config, root):
        path = root / relative
        policy_item = policy_by_path.get(relative, {})
        count = Counter()
        failures: Counter[str] = Counter()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            count["rows"] += 1
            locator_ok, locator_status = source_locator_status(row.get("source_locator"))
            quality_ok, quality_status = quality_ledger_status(row)
            count["source_locator_complete"] += int(locator_ok)
            count["quality_ledger_complete"] += int(quality_ok)
            if not locator_ok:
                failures[f"locator:{locator_status}"] += 1
            if not quality_ok:
                failures[f"quality:{quality_status}"] += 1
        total.update(count)
        components.append(
            {
                "path": relative,
                "activation": activation,
                "rows": count["rows"],
                "evidence_tier": policy_item.get("evidence_tier"),
                "source_locator_complete_rows": count["source_locator_complete"],
                "quality_ledger_complete_rows": count["quality_ledger_complete"],
                "source_locator_complete_rate": count["source_locator_complete"] / count["rows"] if count["rows"] else 0.0,
                "quality_ledger_complete_rate": count["quality_ledger_complete"] / count["rows"] if count["rows"] else 0.0,
                "failures": dict(sorted(failures.items())),
            }
        )
    promotion_ready = bool(total["rows"]) and total["source_locator_complete"] == total["rows"] and total["quality_ledger_complete"] == total["rows"]
    return {
        "schema_version": "open_agronomy_agent.offline_corpus_successor_quality_audit.v1",
        "config_path": config_path.relative_to(root).as_posix(),
        "config_sha256": _sha256(config_path),
        "policy_path": policy_path.relative_to(root).as_posix(),
        "policy_sha256": _sha256(policy_path),
        "components": components,
        "totals": {
            "rows": total["rows"],
            "source_locator_complete_rows": total["source_locator_complete"],
            "quality_ledger_complete_rows": total["quality_ledger_complete"],
        },
        "promotion_gate": {
            "requires_source_locator_complete_rate": 1.0,
            "requires_quality_ledger_complete_rate": 1.0,
            "passed": promotion_ready,
            "status": "pass" if promotion_ready else "blocked_legacy_components_require_source_exact_rebuild",
        },
        "interpretation": (
            "This is a provenance/extraction gate, not a retrieval-quality or agronomic-validity result. "
            "A blocked result prevents successor profile promotion; it does not erase legacy component lineage."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fail-on-gap", action="store_true")
    args = parser.parse_args()
    report = audit(args.config, root=ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["promotion_gate"]["status"], "totals": report["totals"]}, indent=2))
    return 1 if args.fail_on_gap and not report["promotion_gate"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
