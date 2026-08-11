#!/usr/bin/env python3
"""Build or verify one portable offline Prairie spatial-data directory.

The public Git repository carries source code, lineage records, and small
derived manifests. Large SQLite/RTree layers are assembled as a separate
release asset because GitHub rejects files over 100 MB. At runtime set
``AGRONOMY_AGENT_SPATIAL_PACK_ROOT`` to the resulting directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from validate_canada_geospatial_sources import validate as validate_registry


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.prairie_spatial_pack.v1"
PACK_SOURCE_IDS = (
    "ca_aafc_ab_detailed_soil_survey",
    "ca_aafc_sk_detailed_soil_survey",
    "ca_aafc_mb_detailed_soil_survey",
    "ca_aafc_soil_erosion_risk_2021",
)
PACK_MANIFEST_NAME = "prairie_spatial_pack_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_entry(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in registry.get("sources") or []:
        if isinstance(source, dict) and source.get("id") == source_id:
            return source
    raise ValueError(f"geospatial registry is missing required Prairie source: {source_id}")


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def _database_receipt(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
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
    if integrity != "ok" or feature_count <= 0 or feature_count != rtree_count:
        raise ValueError(
            f"invalid spatial SQLite asset {database}: integrity={integrity}, "
            f"features={feature_count}, rtree={rtree_count}"
        )
    return {
        "feature_count": feature_count,
        "rtree_count": rtree_count,
        "source_id": metadata.get("source_id"),
        "source_sha256": metadata.get("source_sha256"),
        "source_scale_range": metadata.get("source_scale_range"),
        "output_crs": metadata.get("output_crs"),
    }


def validate_pack(pack_root: Path) -> dict[str, Any]:
    manifest_path = pack_root / PACK_MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"spatial pack manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported Prairie spatial pack schema")
    errors: list[str] = []
    verified_layers: list[dict[str, Any]] = []
    contract_rows: list[str] = []
    layers = manifest.get("layers") or []
    if not isinstance(layers, list):
        raise ValueError("Prairie spatial pack layers must be a list")
    expected_source_ids = set(PACK_SOURCE_IDS)
    observed_source_ids = {
        str(layer.get("source_id")) for layer in layers if isinstance(layer, dict)
    }
    if observed_source_ids != expected_source_ids:
        errors.append("spatial pack does not contain the exact required Prairie source set")
    if int(manifest.get("layer_count") or -1) != len(layers):
        errors.append("spatial pack layer count mismatch")
    seen_paths: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict):
            errors.append("spatial pack contains a malformed layer row")
            continue
        database_value = str(layer.get("database") or "")
        layer_manifest_value = str(layer.get("derived_manifest") or "")
        if (
            not database_value
            or not layer_manifest_value
            or Path(database_value).name != database_value
            or Path(layer_manifest_value).name != layer_manifest_value
        ):
            errors.append(f"{layer.get('layer_id')} contains a non-portable asset path")
            continue
        if database_value in seen_paths or layer_manifest_value in seen_paths:
            errors.append(f"{layer.get('layer_id')} reuses an asset path")
            continue
        seen_paths.update((database_value, layer_manifest_value))
        database = pack_root / database_value
        layer_manifest_path = pack_root / layer_manifest_value
        for label, path in (("database", database), ("derived manifest", layer_manifest_path)):
            if not path.is_file():
                errors.append(f"{layer.get('layer_id')} {label} is missing: {path.name}")
        if not database.is_file() or not layer_manifest_path.is_file():
            continue
        database_sha256 = _sha256(database)
        derived_manifest_sha256 = _sha256(layer_manifest_path)
        derived = json.loads(layer_manifest_path.read_text(encoding="utf-8"))
        if database_sha256 != layer.get("sha256") or database.stat().st_size != int(layer.get("bytes") or -1):
            errors.append(f"{layer.get('layer_id')} database receipt mismatch")
        if derived_manifest_sha256 != layer.get("derived_manifest_sha256"):
            errors.append(f"{layer.get('layer_id')} derived-manifest receipt mismatch")
        if derived.get("output_sha256") != database_sha256:
            errors.append(f"{layer.get('layer_id')} database does not match its derivation manifest")
        if derived.get("source_id") != layer.get("source_id"):
            errors.append(f"{layer.get('layer_id')} source identity mismatch in derivation manifest")
        try:
            receipt = _database_receipt(database)
        except (OSError, sqlite3.Error, ValueError) as exc:
            errors.append(str(exc))
            continue
        if receipt["feature_count"] != int(layer.get("feature_count") or 0):
            errors.append(f"{layer.get('layer_id')} feature count mismatch")
        if receipt["source_id"] != layer.get("source_id"):
            errors.append(f"{layer.get('layer_id')} source identity mismatch in database")
        if receipt["output_crs"] != "EPSG:4326":
            errors.append(f"{layer.get('layer_id')} has an unsupported runtime CRS")
        verified_layers.append({"layer_id": layer.get("layer_id"), **receipt})
        contract_rows.append(f"{layer.get('database')}\0{database_sha256}\n")
        contract_rows.append(f"{layer.get('derived_manifest')}\0{derived_manifest_sha256}\n")
    actual_contract = hashlib.sha256("".join(sorted(contract_rows)).encode("utf-8")).hexdigest()
    if actual_contract != manifest.get("contract_sha256"):
        errors.append("spatial pack contract SHA256 mismatch")
    total_bytes = sum(
        (pack_root / str(row.get("database"))).stat().st_size
        for row in layers
        if isinstance(row, dict)
        and Path(str(row.get("database") or "")).name == str(row.get("database") or "")
        and (pack_root / str(row.get("database"))).is_file()
    )
    if total_bytes != int(manifest.get("total_database_bytes") or -1):
        errors.append("spatial pack total database bytes mismatch")
    return {
        "schema_version": "open_agronomy_agent.prairie_spatial_pack_validation.v1",
        "status": "pass" if not errors else "fail",
        "pack_root": str(pack_root),
        "manifest_sha256": _sha256(manifest_path),
        "layer_count": len(verified_layers),
        "total_bytes": total_bytes,
        "layers": verified_layers,
        "errors": errors,
    }


def build_pack(*, registry_path: Path, asset_root: Path, destination: Path) -> dict[str, Any]:
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"destination must be absent or empty: {destination}")
    registry_validation = validate_registry(registry_path, root=asset_root)
    if registry_validation.get("status") != "pass":
        raise ValueError("Canadian geospatial source registry or source assets failed validation")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    layers: list[dict[str, Any]] = []
    contract_rows: list[str] = []
    for source_id in PACK_SOURCE_IDS:
        source = _source_entry(registry, source_id)
        runtime = source.get("runtime") or {}
        database_source = _resolve(asset_root, runtime.get("derived_path"))
        manifest_source = _resolve(asset_root, runtime.get("derived_manifest_path"))
        database_name = database_source.name
        manifest_name = manifest_source.name
        database_destination = destination / database_name
        manifest_destination = destination / manifest_name
        shutil.copy2(database_source, database_destination)
        shutil.copy2(manifest_source, manifest_destination)
        database_sha256 = _sha256(database_destination)
        manifest_sha256 = _sha256(manifest_destination)
        derived = json.loads(manifest_destination.read_text(encoding="utf-8"))
        receipt = _database_receipt(database_destination)
        if derived.get("output_sha256") != database_sha256:
            raise ValueError(f"copied database failed derivation-manifest validation: {database_name}")
        layers.append(
            {
                "source_id": source_id,
                "layer_id": runtime.get("layer_id"),
                "database": database_name,
                "derived_manifest": manifest_name,
                "bytes": database_destination.stat().st_size,
                "sha256": database_sha256,
                "derived_manifest_sha256": manifest_sha256,
                "feature_count": receipt["feature_count"],
                "source_url": source.get("canonical_url"),
                "source_scale": source.get("source_scale"),
                "license": source.get("license"),
                "boundary": source.get("boundary"),
            }
        )
        contract_rows.append(f"{database_name}\0{database_sha256}\n")
        contract_rows.append(f"{manifest_name}\0{manifest_sha256}\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pack_id": "prairie_dss_and_erosion_v1",
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "source_registry": "data/manifests/canada_geospatial_sources.json",
        "source_registry_sha256": _sha256(registry_path),
        "runtime_environment": {"AGRONOMY_AGENT_SPATIAL_PACK_ROOT": "."},
        "layer_count": len(layers),
        "total_database_bytes": sum(int(layer["bytes"]) for layer in layers),
        "contract_sha256": hashlib.sha256("".join(sorted(contract_rows)).encode("utf-8")).hexdigest(),
        "layers": layers,
        "boundary": (
            "Historical and modelled mapped priors for offline screening. These layers do not establish "
            "current field condition, soil-test values, diagnosis, legal boundaries, or management rates."
        ),
    }
    (destination / PACK_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / "NOTICE.md").write_text(
        "# Prairie spatial pack\n\n"
        "Contains adapted Agriculture and Agri-Food Canada information under the Open Government "
        "Licence - Canada. Exact source, licence, checksum, scale, and limitation records are in "
        f"`{PACK_MANIFEST_NAME}` and the per-layer manifests.\n",
        encoding="utf-8",
    )
    validation = validate_pack(destination)
    if validation["status"] != "pass":
        raise ValueError("built Prairie spatial pack failed validation: " + "; ".join(validation["errors"]))
    return {"manifest": manifest, "validation": validation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, default=ROOT)
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "data/manifests/canada_geospatial_sources.json",
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if args.verify_only:
        report = validate_pack(destination)
    else:
        report = build_pack(
            registry_path=args.registry.resolve(),
            asset_root=args.asset_root.resolve(),
            destination=destination,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status", report.get("validation", {}).get("status")) == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
