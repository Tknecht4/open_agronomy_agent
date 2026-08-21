#!/usr/bin/env python3
"""Fail closed unless an edge overlay changes only declared governed trees."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXACT_FIELDS = (
    "schema_version",
    "status",
    "image_contract",
    "model",
    "rag_config",
    "runtime_knowledge",
    "runtime_knowledge_bytes",
    "runtime_policies",
    "geo_cache_seed",
    "bundled_geo_layers",
    "benchmark_evidence",
)
ALLOWED_RUNTIME_ASSET_CHANGES = {
    "src/agronomy_agent",
    "frontend/src",
    "scripts",
}
ALLOWED_CONTROL_FILE_CHANGES = {
    "Containerfile.overlay",
    "container/README.md",
    "container/build-overlay-image.sh",
    "container/release.sh",
}


def _index(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(entry.get("path") or ""): entry for entry in entries}


def validate(
    base: dict[str, Any],
    current: dict[str, Any],
    *,
    expected_base_contract_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    if base.get("contract_sha256") != expected_base_contract_sha256:
        errors.append(
            "base runtime contract does not match the explicitly approved contract"
        )
    if current.get("status") != "pass":
        errors.append("current runtime manifest is not passing")

    changed_exact_fields = [
        field for field in EXACT_FIELDS if base.get(field) != current.get(field)
    ]
    errors.extend(
        f"overlay would change immutable runtime field: {field}"
        for field in changed_exact_fields
    )

    base_assets = _index(base.get("runtime_assets") or [])
    current_assets = _index(current.get("runtime_assets") or [])
    if set(base_assets) != set(current_assets):
        errors.append("overlay would change the governed runtime-asset path set")
    changed_assets = sorted(
        path
        for path in set(base_assets) | set(current_assets)
        if base_assets.get(path) != current_assets.get(path)
    )
    unexpected_assets = sorted(
        set(changed_assets) - ALLOWED_RUNTIME_ASSET_CHANGES
    )
    errors.extend(
        f"overlay contains an undeclared runtime-asset change: {path}"
        for path in unexpected_assets
    )

    base_controls = _index(base.get("control_files") or [])
    current_controls = _index(current.get("control_files") or [])
    changed_controls = sorted(
        path
        for path in set(base_controls) | set(current_controls)
        if base_controls.get(path) != current_controls.get(path)
    )
    unexpected_controls = sorted(
        set(changed_controls) - ALLOWED_CONTROL_FILE_CHANGES
    )
    errors.extend(
        f"overlay contains an undeclared control-file change: {path}"
        for path in unexpected_controls
    )

    required_changes = {
        "src/agronomy_agent",
        "frontend/src",
    }
    missing_required_changes = sorted(required_changes - set(changed_assets))
    errors.extend(
        f"overlay is missing the expected runtime-asset change: {path}"
        for path in missing_required_changes
    )

    return {
        "schema_version": "open_agronomy_agent.edge_overlay_base_validation.v1",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "base_contract_sha256": base.get("contract_sha256"),
        "expected_base_contract_sha256": expected_base_contract_sha256,
        "current_contract_sha256": current.get("contract_sha256"),
        "changed_runtime_assets": changed_assets,
        "changed_control_files": changed_controls,
        "allowed_runtime_asset_changes": sorted(ALLOWED_RUNTIME_ASSET_CHANGES),
        "allowed_control_file_changes": sorted(ALLOWED_CONTROL_FILE_CHANGES),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--expected-base-contract-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    base = json.loads(args.base.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    report = validate(
        base,
        current,
        expected_base_contract_sha256=args.expected_base_contract_sha256,
    )
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_pass and report["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
