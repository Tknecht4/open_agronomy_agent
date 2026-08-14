#!/usr/bin/env python3
"""Build or verify one profile-scoped portable offline spatial-data pack.

The repository holds source/profile contracts and the installer, not large
SQLite/RTree assets.  A pack is assembled in a caller-selected external state
directory only after the corresponding source profile validates.  The current
implementation profile is ``prairie-dss-v1`` (AB, SK, and MB DSS only), but
the profile contract also permits separate non-default packs with the same
integrity and portability requirements.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from offline_spatial_profiles import (
    ROOT as REPOSITORY_ROOT,
    load_profile,
    profile_entry_sha256,
    profile_pack_filename,
    resolve_state_path,
    sha256_path,
    source_ids as profile_source_ids,
    source_row,
)
from validate_canada_geospatial_sources import validate as validate_registry


ROOT = REPOSITORY_ROOT
SCHEMA_VERSION = "open_agronomy_agent.offline_spatial_pack.v2"
LEGACY_SCHEMA_VERSION = "open_agronomy_agent.prairie_spatial_pack.v1"
INSTALL_RECEIPT_SCHEMA_VERSION = "open_agronomy_agent.offline_spatial_install_receipt.v1"
PACK_MANIFEST_NAME = "prairie_spatial_pack_manifest.json"
LEGACY_PACK_SOURCE_IDS = (
    "ca_aafc_ab_detailed_soil_survey",
    "ca_aafc_sk_detailed_soil_survey",
    "ca_aafc_mb_detailed_soil_survey",
    "ca_aafc_soil_erosion_risk_2021",
)
DEFAULT_PROFILE_ID = "prairie-dss-v1"
DEFAULT_PROFILE_MANIFEST = ROOT / "data/manifests/offline_spatial_profiles_v1.json"


def _sha256(path: Path) -> str:
    return sha256_path(path)


def _source_entry(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in registry.get("sources") or []:
        if isinstance(source, dict) and source.get("id") == source_id:
            return source
    raise ValueError(f"geospatial registry is missing required profile source: {source_id}")


def _render_path(path: Path, *, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


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
        "source_entry_sha256": metadata.get("source_entry_sha256"),
        "source_scale_range": metadata.get("source_scale_range"),
        "output_crs": metadata.get("output_crs"),
    }


def _profile_paths(
    *, profile: dict[str, Any], asset_root: Path, source_id: str
) -> tuple[Path, Path]:
    source = source_row(profile, source_id)
    return (
        resolve_state_path(asset_root, source, "derived"),
        resolve_state_path(asset_root, source, "derived_manifest"),
    )


def _expected_profile_layers(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["source_id"]): row for row in profile.get("sources") or [] if isinstance(row, dict)}


def _validate_install_receipt(
    *,
    pack_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    profile_manifest_path: Path,
    errors: list[str],
) -> None:
    receipt_name = profile_pack_filename(profile, "install_receipt")
    receipt_path = pack_root / receipt_name
    if not receipt_path.is_file():
        errors.append(f"spatial pack install receipt is missing: {receipt_name}")
        return
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"spatial pack install receipt is unreadable: {exc}")
        return
    if receipt.get("schema_version") != INSTALL_RECEIPT_SCHEMA_VERSION:
        errors.append("spatial pack install receipt schema is unsupported")
    if receipt.get("profile_id") != profile.get("id"):
        errors.append("spatial pack install receipt profile does not match the pack")
    if receipt.get("pack_manifest_sha256") != _sha256(manifest_path):
        errors.append("spatial pack install receipt does not match the pack manifest")
    if receipt.get("profile_manifest_sha256") != _sha256(profile_manifest_path):
        errors.append("spatial pack install receipt does not match the profile manifest")
    if receipt.get("profile_entry_sha256") != profile_entry_sha256(profile):
        errors.append("spatial pack install receipt does not match the profile entry")
    expected_sources = set(profile_source_ids(profile))
    receipt_sources = {
        str(row.get("source_id"))
        for row in receipt.get("sources") or []
        if isinstance(row, dict)
    }
    if receipt_sources != expected_sources:
        errors.append("spatial pack install receipt source set does not match the profile")
    if receipt.get("contract_sha256") != manifest.get("contract_sha256"):
        errors.append("spatial pack install receipt contract does not match the pack")


def validate_pack(
    pack_root: Path,
    *,
    profile_id: str | None = None,
    profile_manifest_path: Path = DEFAULT_PROFILE_MANIFEST,
    require_install_receipt: bool = True,
) -> dict[str, Any]:
    """Validate one flat external runtime pack and its profile-bound receipt."""

    pack_root = pack_root.resolve()
    selected_profile: dict[str, Any] | None = None
    manifest_name = PACK_MANIFEST_NAME
    if profile_id is not None:
        selected_profile = load_profile(profile_manifest_path, profile_id)
        manifest_name = profile_pack_filename(selected_profile, "manifest")
    manifest_path = pack_root / manifest_name
    if not manifest_path.is_file():
        raise FileNotFoundError(f"spatial pack manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    errors: list[str] = []
    profile: dict[str, Any] | None = None
    expected_layers: dict[str, dict[str, Any]] = {}
    if schema_version == SCHEMA_VERSION:
        observed_profile_id = str(manifest.get("profile_id") or "")
        if profile_id is not None and observed_profile_id != profile_id:
            errors.append("spatial pack profile does not match the requested profile")
        selected_profile_id = profile_id or observed_profile_id
        try:
            profile = (
                selected_profile
                if selected_profile is not None and selected_profile_id == profile_id
                else load_profile(profile_manifest_path, selected_profile_id)
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"spatial pack profile contract is unreadable: {exc}")
        else:
            expected_layers = _expected_profile_layers(profile)
            if manifest.get("profile_entry_sha256") != profile_entry_sha256(profile):
                errors.append("spatial pack profile entry SHA256 mismatch")
            if manifest.get("profile_manifest_sha256") != _sha256(profile_manifest_path):
                errors.append("spatial pack profile manifest SHA256 mismatch")
    elif schema_version == LEGACY_SCHEMA_VERSION:
        expected_layers = {source_id: {} for source_id in LEGACY_PACK_SOURCE_IDS}
        if profile_id is not None:
            errors.append("legacy Prairie spatial pack cannot satisfy an explicit DSS-only profile")
    else:
        raise ValueError("unsupported offline spatial pack schema")

    verified_layers: list[dict[str, Any]] = []
    contract_rows: list[str] = []
    layers = manifest.get("layers") or []
    if not isinstance(layers, list):
        raise ValueError("offline spatial pack layers must be a list")
    observed_source_ids = {
        str(layer.get("source_id")) for layer in layers if isinstance(layer, dict)
    }
    if observed_source_ids != set(expected_layers):
        errors.append("spatial pack does not contain the exact required profile source set")
    if int(manifest.get("layer_count") or -1) != len(layers):
        errors.append("spatial pack layer count mismatch")
    seen_paths: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict):
            errors.append("spatial pack contains a malformed layer row")
            continue
        source_id = str(layer.get("source_id") or "")
        profile_source = expected_layers.get(source_id)
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
        try:
            derived = json.loads(layer_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{layer.get('layer_id')} derived manifest is unreadable: {exc}")
            continue
        database_sha256 = _sha256(database)
        derived_manifest_sha256 = _sha256(layer_manifest_path)
        if database_sha256 != layer.get("sha256") or database.stat().st_size != int(layer.get("bytes") or -1):
            errors.append(f"{layer.get('layer_id')} database receipt mismatch")
        if derived_manifest_sha256 != layer.get("derived_manifest_sha256"):
            errors.append(f"{layer.get('layer_id')} derived-manifest receipt mismatch")
        if derived.get("output_sha256") != database_sha256:
            errors.append(f"{layer.get('layer_id')} database does not match its derivation manifest")
        if derived.get("source_id") != source_id:
            errors.append(f"{layer.get('layer_id')} source identity mismatch in derivation manifest")
        if isinstance(profile_source, dict):
            if layer.get("layer_id") != profile_source.get("layer_id"):
                errors.append(f"{source_id} layer identity does not match the profile")
            if derived.get("source_sha256") != profile_source.get("expected_raw_sha256"):
                errors.append(f"{source_id} derivation manifest raw SHA256 does not match the profile")
            if derived.get("source_entry_sha256") != profile_source.get("source_entry_sha256"):
                errors.append(f"{source_id} derivation manifest source entry does not match the profile")
        try:
            receipt = _database_receipt(database)
        except (OSError, sqlite3.Error, ValueError) as exc:
            errors.append(str(exc))
            continue
        if receipt["feature_count"] != int(layer.get("feature_count") or 0):
            errors.append(f"{layer.get('layer_id')} feature count mismatch")
        if receipt["source_id"] != source_id:
            errors.append(f"{layer.get('layer_id')} source identity mismatch in database")
        if receipt["output_crs"] != "EPSG:4326":
            errors.append(f"{layer.get('layer_id')} has an unsupported runtime CRS")
        if isinstance(profile_source, dict):
            if receipt["source_sha256"] != profile_source.get("expected_raw_sha256"):
                errors.append(f"{source_id} database raw SHA256 does not match the profile")
            if receipt["source_entry_sha256"] != profile_source.get("source_entry_sha256"):
                errors.append(f"{source_id} database source entry does not match the profile")
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
    if profile is not None and require_install_receipt:
        _validate_install_receipt(
            pack_root=pack_root,
            manifest_path=manifest_path,
            manifest=manifest,
            profile=profile,
            profile_manifest_path=profile_manifest_path,
            errors=errors,
        )
    return {
        "schema_version": "open_agronomy_agent.offline_spatial_pack_validation.v2",
        "status": "pass" if not errors else "fail",
        "pack_root": str(pack_root),
        "profile_id": profile.get("id") if profile is not None else None,
        "manifest_sha256": _sha256(manifest_path),
        "layer_count": len(verified_layers),
        "total_bytes": total_bytes,
        "layers": verified_layers,
        "errors": errors,
    }


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_install_receipt(
    *,
    destination: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    profile_manifest_path: Path,
    retain_raw: bool,
) -> None:
    source_layers = {str(row.get("source_id")): row for row in manifest.get("layers") or []}
    sources = []
    for profile_source in profile.get("sources") or []:
        if not isinstance(profile_source, dict):
            continue
        source_id = str(profile_source["source_id"])
        layer = source_layers[source_id]
        sources.append(
            {
                "source_id": source_id,
                "layer_id": profile_source["layer_id"],
                "source_entry_sha256": profile_source["source_entry_sha256"],
                "raw_sha256": profile_source["expected_raw_sha256"],
                "raw_bytes": profile_source["expected_raw_bytes"],
                "database": layer["database"],
                "database_sha256": layer["sha256"],
                "database_bytes": layer["bytes"],
                "derived_manifest": layer["derived_manifest"],
                "derived_manifest_sha256": layer["derived_manifest_sha256"],
            }
        )
    receipt = {
        "schema_version": INSTALL_RECEIPT_SCHEMA_VERSION,
        "profile_id": profile["id"],
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "profile_manifest_sha256": _sha256(profile_manifest_path),
        "profile_entry_sha256": profile_entry_sha256(profile),
        "pack_manifest": manifest_path.name,
        "pack_manifest_sha256": _sha256(manifest_path),
        "contract_sha256": manifest["contract_sha256"],
        "raw_retained": bool(retain_raw),
        "sources": sources,
        "runtime_environment": {"AGRONOMY_AGENT_SPATIAL_PACK_ROOT": "."},
        "boundary": profile.get("boundary"),
    }
    _write_json_atomically(destination / profile_pack_filename(profile, "install_receipt"), receipt)


def build_pack(
    *,
    registry_path: Path,
    asset_root: Path,
    destination: Path,
    profile_id: str = DEFAULT_PROFILE_ID,
    profile_manifest_path: Path = DEFAULT_PROFILE_MANIFEST,
    retain_raw: bool = False,
) -> dict[str, Any]:
    """Assemble an all-or-nothing flat runtime pack for one validated profile."""

    asset_root = asset_root.resolve()
    destination = destination.resolve()
    registry_path = registry_path.resolve()
    profile_manifest_path = profile_manifest_path.resolve()
    profile = load_profile(profile_manifest_path, profile_id)
    if destination.exists():
        raise FileExistsError(f"destination must not already exist: {destination}")
    registry_validation = validate_registry(
        registry_path,
        root=asset_root,
        profile_manifest_path=profile_manifest_path,
        profile_id=profile_id,
    )
    if registry_validation.get("status") != "pass":
        raise ValueError("profile-scoped geospatial source validation failed")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    staging = destination.parent / f".{destination.name}.build-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    layers: list[dict[str, Any]] = []
    contract_rows: list[str] = []
    try:
        for source_id in profile_source_ids(profile):
            profile_source = source_row(profile, source_id)
            source = _source_entry(registry, source_id)
            database_source, manifest_source = _profile_paths(
                profile=profile, asset_root=asset_root, source_id=source_id
            )
            database_name = database_source.name
            manifest_name = manifest_source.name
            database_destination = staging / database_name
            manifest_destination = staging / manifest_name
            shutil.copy2(database_source, database_destination)
            shutil.copy2(manifest_source, manifest_destination)
            database_sha256 = _sha256(database_destination)
            manifest_sha256 = _sha256(manifest_destination)
            derived = json.loads(manifest_destination.read_text(encoding="utf-8"))
            receipt = _database_receipt(database_destination)
            if derived.get("output_sha256") != database_sha256:
                raise ValueError(f"copied database failed derivation-manifest validation: {database_name}")
            if receipt["source_id"] != source_id:
                raise ValueError(f"copied database source identity mismatch: {database_name}")
            layers.append(
                {
                    "source_id": source_id,
                    "layer_id": profile_source["layer_id"],
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
            "pack_id": profile_id,
            "profile_id": profile_id,
            "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
            "profile_manifest": _render_path(profile_manifest_path),
            "profile_manifest_sha256": _sha256(profile_manifest_path),
            "profile_entry_sha256": profile_entry_sha256(profile),
            "source_registry": _render_path(registry_path),
            "source_registry_sha256": _sha256(registry_path),
            "runtime_environment": {"AGRONOMY_AGENT_SPATIAL_PACK_ROOT": "."},
            "layer_count": len(layers),
            "total_database_bytes": sum(int(layer["bytes"]) for layer in layers),
            "contract_sha256": hashlib.sha256("".join(sorted(contract_rows)).encode("utf-8")).hexdigest(),
            "layers": layers,
            "boundary": profile.get("boundary"),
        }
        manifest_path = staging / profile_pack_filename(profile, "manifest")
        _write_json_atomically(manifest_path, manifest)
        attribution_lines = []
        for layer in layers:
            attribution = (layer.get("license") or {}).get("attribution")
            if attribution:
                attribution_lines.append(f"- `{layer['source_id']}`: {attribution}")
        (staging / "NOTICE.md").write_text(
            f"# {profile['title']} offline spatial pack\n\n"
            "Contains adapted official Canadian spatial information. Exact source, licence, checksum, scale, "
            f"and limitation records are in `{manifest_path.name}`, `install_receipt.json`, and the per-layer manifests.\n\n"
            + "\n".join(attribution_lines)
            + "\n",
            encoding="utf-8",
        )
        pre_receipt_validation = validate_pack(
            staging,
            profile_id=profile_id,
            profile_manifest_path=profile_manifest_path,
            require_install_receipt=False,
        )
        if pre_receipt_validation["status"] != "pass":
            raise ValueError(
                "built spatial pack failed validation before receipt: "
                + "; ".join(pre_receipt_validation["errors"])
            )
        _write_install_receipt(
            destination=staging,
            manifest_path=manifest_path,
            manifest=manifest,
            profile=profile,
            profile_manifest_path=profile_manifest_path,
            retain_raw=retain_raw,
        )
        validation = validate_pack(
            staging,
            profile_id=profile_id,
            profile_manifest_path=profile_manifest_path,
        )
        if validation["status"] != "pass":
            raise ValueError("built spatial pack failed validation: " + "; ".join(validation["errors"]))
        os.replace(staging, destination)
    except BaseException:
        # Preserve the isolated staging directory for inspection; it was never promoted.
        raise
    return {"manifest": manifest, "validation": validation, "destination": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, default=ROOT)
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "data/manifests/canada_geospatial_sources.json",
    )
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--profile-manifest", type=Path, default=DEFAULT_PROFILE_MANIFEST)
    parser.add_argument("--retain-raw", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if args.verify_only:
        report = validate_pack(
            destination,
            profile_id=args.profile,
            profile_manifest_path=args.profile_manifest.resolve(),
        )
    else:
        report = build_pack(
            registry_path=args.registry.resolve(),
            asset_root=args.asset_root.resolve(),
            destination=destination,
            profile_id=args.profile,
            profile_manifest_path=args.profile_manifest.resolve(),
            retain_raw=args.retain_raw,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status", report.get("validation", {}).get("status")) == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
