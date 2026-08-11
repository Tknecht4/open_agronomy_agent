#!/usr/bin/env python3
"""Validate Canadian geospatial licensing, lineage, and bundled layer integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.canada_geospatial_sources.v1"
ALLOWED_OPEN_LICENCES = {
    "Open Government Licence - British Columbia",
    "Open Government Licence - Canada",
}
REQUIRED_SOURCE_FIELDS = {
    "id",
    "title",
    "publisher",
    "jurisdiction",
    "canonical_url",
    "catalogue_api_url",
    "download_url",
    "source_record_id",
    "format",
    "source_crs",
    "source_scale",
    "currency",
    "license",
    "runtime",
    "boundary",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_entry_sha256(source: dict[str, Any]) -> str:
    """Hash one canonical registry entry so unrelated additions do not break lineage."""

    payload = json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def validate(manifest_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = _sha256(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    soil_gate = manifest.get("national_soil_context_gate")
    if not isinstance(soil_gate, dict):
        errors.append("national_soil_context_gate is missing")
        soil_gate = {}
    required_provinces = soil_gate.get("required_provinces") or []
    if len(set(str(value) for value in required_provinces)) != 10:
        errors.append("national soil gate must enumerate the ten crop-producing provinces")
    if soil_gate.get("release_eligible") is not False:
        errors.append("national soil gate must remain fail-closed until the national prior passes")
    national_candidate = soil_gate.get("candidate_national_prior") or {}
    if not national_candidate.get("required_layers") or not national_candidate.get("promotion_gates"):
        errors.append("national soil candidate is missing required layers or promotion gates")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    source_ids = [str(source.get("id") or "") for source in sources if isinstance(source, dict)]
    if len(set(source_ids)) != len(source_ids):
        errors.append("source ids must be unique")

    bundled: list[dict[str, Any]] = []
    candidates: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        source_id = str(source.get("id") or f"sources[{index}]")
        missing = sorted(REQUIRED_SOURCE_FIELDS - set(source))
        if missing:
            errors.append(f"{source_id} missing fields: {missing}")
            continue
        if source.get("source_record_id") not in str(source.get("catalogue_api_url") or ""):
            errors.append(f"{source_id} catalogue API URL does not identify the exact record")
        license_record = source.get("license") if isinstance(source.get("license"), dict) else {}
        if license_record.get("identifier") not in ALLOWED_OPEN_LICENCES:
            errors.append(f"{source_id} does not identify an allowed Canadian open-government licence")
        for permission in ("permits_modification", "permits_commercial", "permits_redistribution"):
            if license_record.get(permission) is not True:
                errors.append(f"{source_id} missing licence permission: {permission}")
        runtime = source.get("runtime") if isinstance(source.get("runtime"), dict) else {}
        if runtime.get("status") != "bundled":
            candidates.append(source_id)
            continue

        raw_path = _resolve(root, runtime.get("raw_path"))
        lineage_path = _resolve(root, runtime.get("lineage_path"))
        derived_path = _resolve(root, runtime.get("derived_path"))
        derived_manifest_path = _resolve(root, runtime.get("derived_manifest_path"))
        for label, path in (
            ("raw", raw_path),
            ("lineage", lineage_path),
            ("derived", derived_path),
            ("derived manifest", derived_manifest_path),
        ):
            if not path.is_file():
                errors.append(f"{source_id} {label} file is missing: {path}")
        if any(not path.is_file() for path in (raw_path, lineage_path, derived_path, derived_manifest_path)):
            continue

        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        derived_manifest = json.loads(derived_manifest_path.read_text(encoding="utf-8"))
        source_entry_sha256 = _source_entry_sha256(source)
        raw_sha256 = _sha256(raw_path)
        lineage_sha256 = _sha256(lineage_path)
        derived_sha256 = _sha256(derived_path)
        if lineage.get("source_id") != source_id or lineage.get("source_record_id") != source.get("source_record_id"):
            errors.append(f"{source_id} lineage identity does not match the registry")
        if lineage.get("download_url") != source.get("download_url"):
            errors.append(f"{source_id} lineage download URL does not match the registry")
        if int(lineage.get("raw_bytes") or -1) != raw_path.stat().st_size:
            errors.append(f"{source_id} raw byte count does not match lineage")
        if lineage.get("raw_sha256") != raw_sha256:
            errors.append(f"{source_id} raw SHA256 does not match lineage")
        lineage_entry_sha256 = lineage.get("source_entry_sha256")
        if lineage_entry_sha256 is not None:
            if lineage_entry_sha256 != source_entry_sha256:
                errors.append(f"{source_id} lineage does not match its geospatial source entry SHA256")
        elif lineage.get("source_registry_sha256") != manifest_sha256:
            errors.append(
                f"{source_id} legacy lineage does not match the geospatial registry SHA256; "
                "migrate it to source-entry lineage"
            )
        support_files = lineage.get("support_files", [])
        if not isinstance(support_files, list):
            errors.append(f"{source_id} lineage support_files must be a list")
            support_files = []
        permitted_support_urls = {
            str(value)
            for value in source.get("support_download_urls", [])
            if isinstance(value, str) and value
        }
        for support_index, support in enumerate(support_files):
            if not isinstance(support, dict):
                errors.append(f"{source_id} support_files[{support_index}] must be an object")
                continue
            support_path = _resolve(root, support.get("path"))
            if not support_path.is_file():
                errors.append(f"{source_id} support file is missing: {support_path}")
                continue
            if int(support.get("bytes") or -1) != support_path.stat().st_size:
                errors.append(f"{source_id} support file byte count does not match: {support_path}")
            if support.get("sha256") != _sha256(support_path):
                errors.append(f"{source_id} support file SHA256 does not match: {support_path}")
            if str(support.get("download_url") or "") not in permitted_support_urls:
                errors.append(f"{source_id} support file URL is not registered: {support_path}")
        if derived_manifest.get("source_sha256") != raw_sha256:
            errors.append(f"{source_id} derived manifest does not match the raw source")
        if derived_manifest.get("lineage_sha256") != lineage_sha256:
            errors.append(f"{source_id} derived manifest does not match the lineage record")
        derived_entry_sha256 = derived_manifest.get("source_entry_sha256")
        if derived_entry_sha256 is not None:
            if derived_entry_sha256 != source_entry_sha256:
                errors.append(f"{source_id} derived manifest does not match its geospatial source entry")
        elif derived_manifest.get("source_registry_sha256") != manifest_sha256:
            errors.append(f"{source_id} legacy derived manifest does not match the geospatial registry")
        if int(derived_manifest.get("output_bytes") or -1) != derived_path.stat().st_size:
            errors.append(f"{source_id} derived layer byte count does not match its manifest")
        if derived_manifest.get("output_sha256") != derived_sha256:
            errors.append(f"{source_id} derived layer SHA256 does not match its manifest")
        if derived_manifest.get("support_files", []) != support_files:
            errors.append(f"{source_id} derived manifest support files do not match lineage")

        connection = sqlite3.connect(f"file:{derived_path}?mode=ro", uri=True)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            feature_count = int(connection.execute("SELECT COUNT(*) FROM features").fetchone()[0])
            rtree_count = int(connection.execute("SELECT COUNT(*) FROM feature_bounds").fetchone()[0])
            metadata = {
                str(key): json.loads(str(value))
                for key, value in connection.execute("SELECT key, value_json FROM metadata")
            }
        finally:
            connection.close()
        if integrity != "ok":
            errors.append(f"{source_id} SQLite integrity check failed: {integrity}")
        if not feature_count or feature_count != rtree_count:
            errors.append(f"{source_id} feature/RTree counts differ: {feature_count}/{rtree_count}")
        if feature_count != int(derived_manifest.get("feature_count") or 0):
            errors.append(f"{source_id} feature count does not match the derived manifest")
        if metadata.get("source_sha256") != raw_sha256:
            errors.append(f"{source_id} SQLite metadata does not match the raw source")
        metadata_entry_sha256 = metadata.get("source_entry_sha256")
        if metadata_entry_sha256 is not None:
            if metadata_entry_sha256 != source_entry_sha256:
                errors.append(f"{source_id} SQLite metadata does not match its geospatial source entry")
        elif metadata.get("source_registry_sha256") != manifest_sha256:
            errors.append(f"{source_id} legacy SQLite metadata does not match the geospatial registry")
        bundled.append(
            {
                "source_id": source_id,
                "layer_id": runtime.get("layer_id"),
                "feature_count": feature_count,
                "bytes": derived_path.stat().st_size,
                "sha256": derived_sha256,
            }
        )

    try:
        rendered_manifest_path = str(manifest_path.relative_to(root))
    except ValueError:
        rendered_manifest_path = str(manifest_path)
    return {
        "schema_version": "open_agronomy_agent.canada_geospatial_validation.v1",
        "status": "pass" if not errors else "fail",
        "manifest_path": rendered_manifest_path,
        "manifest_sha256": manifest_sha256,
        "source_count": len(sources),
        "bundled_source_count": len(bundled),
        "candidate_source_ids": candidates,
        "bundled_layers": bundled,
        "national_soil_context_gate": {
            "status": soil_gate.get("status"),
            "release_eligible": bool(soil_gate.get("release_eligible")),
            "required_province_count": len(required_provinces),
            "regional_overlay_count": len(soil_gate.get("currently_available_regional_overlays") or []),
            "candidate_source_id": national_candidate.get("source_id"),
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/manifests/canada_geospatial_sources.json",
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=ROOT,
        help="root containing raw and derived geospatial assets; may differ from the source checkout",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate(args.manifest.resolve(), root=args.asset_root.resolve())
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
