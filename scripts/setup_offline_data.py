#!/usr/bin/env python3
"""Explicitly prepare one compact offline spatial-data profile in local state.

No application startup path calls this script.  Network activity occurs only
with ``--download``; ``--build`` and ``--verify`` use local files only.  Each
explicit profile transforms its pinned official source bytes into a flat
SQLite/RTree runtime pack outside the Git checkout.  The default remains the
Prairie DSS profile; optional boundary-context profiles stay separate.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from build_canada_context_boundary_layer import SPECS as CONTEXT_BOUNDARY_SPECS
from build_canada_context_boundary_layer import build_layer as build_context_boundary_layer
from build_prairie_detailed_soil_layer import PROFILES, build_layer
from build_prairie_spatial_pack import (
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_MANIFEST,
    _database_receipt,
    build_pack,
    validate_pack,
)
from offline_spatial_profiles import (
    ROOT,
    load_profile,
    profile_entry_sha256,
    resolve_pack_root,
    resolve_state_path,
    sha256_path,
    source_ids as profile_source_ids,
    source_row,
    validate_profile_registry_contract,
)
from validate_canada_geospatial_sources import ALLOWED_OPEN_LICENCES, validate as validate_registry
from verify_canada_context_boundary_pack import run_probe as run_context_boundary_probe
from verify_prairie_spatial_pack import run_probe as run_prairie_probe


DEFAULT_REGISTRY = ROOT / "data/manifests/canada_geospatial_sources.json"
LINEAGE_SCHEMA_VERSION = "open_agronomy_agent.canada_raw_source_lineage.v1"
SETUP_SCHEMA_VERSION = "open_agronomy_agent.offline_spatial_setup.v1"
STATE_ROOT_LOCK_SCHEMA_VERSION = "open_agronomy_agent.offline_spatial_setup_lock.v1"
STATE_ROOT_LOCK_FILENAME = ".open_agronomy_offline_spatial_setup.lock"
MAX_LOCK_METADATA_BYTES = 16 * 1024
DOWNLOAD_BLOCK_SIZE = 1024 * 1024
SOURCE_ID_TO_PROVINCE = {
    "ca_aafc_ab_detailed_soil_survey": "ab",
    "ca_aafc_sk_detailed_soil_survey": "sk",
    "ca_aafc_mb_detailed_soil_survey": "mb",
}


class StateRootLockError(FileExistsError):
    """Raised when another installer owns the requested external state root."""


class StateRootLockReleaseError(OSError):
    """Raised when a lock cannot safely be released by its original owner."""


def _state_root_lock_path(data_root: Path) -> Path:
    """Return the one non-profile-specific lock used for an external state root."""

    return data_root / STATE_ROOT_LOCK_FILENAME


def _existing_lock_diagnostic(lock_path: Path) -> str:
    """Render untrusted existing lock metadata without treating it as removable."""

    try:
        status = lock_path.lstat()
    except FileNotFoundError:
        return "lock entry disappeared while acquisition was retried"
    except OSError as exc:
        return f"lock metadata could not be inspected ({exc})"
    if lock_path.is_symlink() or not lock_path.is_file():
        kind = "symlink" if lock_path.is_symlink() else "non-file entry"
        return f"lock path is a {kind}; it is treated as an active lock"
    if status.st_size > MAX_LOCK_METADATA_BYTES:
        return f"lock metadata is too large ({status.st_size} bytes) and is treated as active"
    try:
        payload = _json(lock_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"lock metadata is unreadable ({exc}) and is treated as active"
    owner = []
    for key in ("pid", "hostname", "acquired_at", "profile_id"):
        value = payload.get(key)
        if value not in (None, ""):
            owner.append(f"{key}={value}")
    return ", ".join(owner) if owner else "lock metadata has no owner details"


class _StateRootLock:
    """An ownership-checked, no-wait lock held for one installer invocation."""

    def __init__(self, *, data_root: Path, profile_id: str) -> None:
        self.data_root = data_root
        self.profile_id = profile_id
        self.path = _state_root_lock_path(data_root)
        self._identity: tuple[int, int] | None = None
        self._lock_id: str | None = None

    def acquire(self) -> None:
        """Atomically claim the state root or fail closed with owner diagnostics."""

        self.data_root.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        flags |= no_follow
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            detail = _existing_lock_diagnostic(self.path)
            raise StateRootLockError(
                "offline spatial setup state root is already locked: "
                f"{self.path} ({detail}). Another installer may be changing raw, derived, or pack "
                "assets; wait for it to finish. Do not remove this lock unless its owner is confirmed stopped."
            ) from exc
        except OSError as exc:
            raise OSError(f"cannot create offline spatial setup lock {self.path}: {exc}") from exc

        identity: tuple[int, int] | None = None
        lock_id = uuid.uuid4().hex
        try:
            status = os.fstat(descriptor)
            identity = (status.st_dev, status.st_ino)
            payload = {
                "schema_version": STATE_ROOT_LOCK_SCHEMA_VERSION,
                "lock_id": lock_id,
                "state_root": str(self.data_root),
                "profile_id": self.profile_id,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
            }
            encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
            written = 0
            while written < len(encoded):
                count = os.write(descriptor, encoded[written:])
                if count <= 0:
                    raise OSError("failed to write offline spatial setup lock metadata")
                written += count
            os.fsync(descriptor)
        except BaseException:
            # Metadata publication failed before this lock could safely protect an
            # installation. Remove only the inode we just created; otherwise retain
            # the entry for diagnosis rather than deleting an unknown replacement.
            if identity is not None:
                try:
                    observed = self.path.lstat()
                    if not self.path.is_symlink() and (observed.st_dev, observed.st_ino) == identity:
                        self.path.unlink()
                except OSError:
                    pass
            raise
        finally:
            os.close(descriptor)
        self._identity = identity
        self._lock_id = lock_id

    def release(self) -> None:
        """Remove only the exact lock entry this process created."""

        if self._identity is None or self._lock_id is None:
            return
        try:
            status = self.path.lstat()
        except FileNotFoundError as exc:
            raise StateRootLockReleaseError(
                f"offline spatial setup lock disappeared before release: {self.path}; "
                "the state root may have been modified outside this installer"
            ) from exc
        if self.path.is_symlink() or (status.st_dev, status.st_ino) != self._identity:
            raise StateRootLockReleaseError(
                f"offline spatial setup lock ownership changed before release: {self.path}; "
                "refusing to remove another process's lock"
            )
        try:
            payload = _json(self.path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise StateRootLockReleaseError(
                f"offline spatial setup lock became unreadable before release: {self.path}; "
                "refusing to remove it"
            ) from exc
        if payload.get("lock_id") != self._lock_id:
            raise StateRootLockReleaseError(
                f"offline spatial setup lock token changed before release: {self.path}; "
                "refusing to remove it"
            )
        self.path.unlink()
        self._identity = None
        self._lock_id = None


@contextlib.contextmanager
def _exclusive_state_root_lock(*, data_root: Path, profile_id: str) -> Any:
    """Hold the state-root lock across every mutating or validation phase."""

    lock = _StateRootLock(data_root=data_root, profile_id=profile_id)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected at {path}")
    return payload


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _registry_source(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in registry.get("sources") or []:
        if isinstance(source, dict) and source.get("id") == source_id:
            return source
    raise ValueError(f"source registry does not declare {source_id}")


def _external_state_root(data_root: Path) -> Path:
    """Reject a state root inside or containing the checkout before any write."""

    root = data_root.expanduser().resolve()
    checkout = ROOT.resolve()
    try:
        root.relative_to(checkout)
    except ValueError:
        pass
    else:
        raise ValueError("--data-root must be outside the Git checkout")
    try:
        checkout.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("--data-root must not contain the Git checkout")
    return root


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        candidate = candidate.parent
    if not candidate.is_dir():
        raise ValueError(f"no directory exists above state root {path}")
    return candidate


def _check_disk_space(data_root: Path, *, required_bytes: int) -> dict[str, int]:
    usage = shutil.disk_usage(_nearest_existing_directory(data_root))
    if usage.free < required_bytes:
        raise OSError(
            f"insufficient free space for profile setup: {usage.free} bytes available, "
            f"{required_bytes} bytes required"
        )
    return {"available_bytes": usage.free, "required_bytes": required_bytes}


def _license_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    license_record = source.get("license") if isinstance(source.get("license"), dict) else {}
    return {
        "status": "redistributable",
        "identifier": license_record.get("identifier"),
        "evidence_url": source.get("catalogue_api_url"),
        "reviewed_on": license_record.get("reviewed_on"),
        "permits_modification": license_record.get("permits_modification"),
        "permits_commercial": license_record.get("permits_commercial"),
        "permits_redistribution": license_record.get("permits_redistribution"),
        "attribution": license_record.get("attribution"),
    }


def _assert_download_eligible(source: dict[str, Any]) -> None:
    """Require the reviewed open-use permissions before any network transfer."""

    license_record = source.get("license") if isinstance(source.get("license"), dict) else {}
    if license_record.get("identifier") not in ALLOWED_OPEN_LICENCES:
        raise ValueError(f"{source.get('id')} does not have an allowed reviewed open-government licence")
    for permission in ("permits_modification", "permits_commercial", "permits_redistribution"):
        if license_record.get(permission) is not True:
            raise ValueError(f"{source.get('id')} is missing required licence permission: {permission}")


def _expected_lineage(
    *,
    profile_source: dict[str, Any],
    registry_source: dict[str, Any],
    raw_path: Path,
    data_root: Path,
    registry_path: Path,
    registry_sha256: str,
    fetched_at: str,
) -> dict[str, Any]:
    try:
        rendered_registry_path = str(registry_path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        rendered_registry_path = str(registry_path)
    return {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "source_id": profile_source["source_id"],
        "source_record_id": profile_source["source_record_id"],
        "canonical_url": registry_source.get("canonical_url"),
        "download_url": profile_source["download_url"],
        "fetched_at": fetched_at,
        "raw_path": str(raw_path.relative_to(data_root)),
        "raw_bytes": raw_path.stat().st_size,
        "raw_sha256": sha256_path(raw_path),
        "support_files": [],
        "source_registry_path": rendered_registry_path,
        "source_registry_sha256": registry_sha256,
        "source_entry_sha256": profile_source["source_entry_sha256"],
        "format": registry_source.get("format"),
        "source_crs": registry_source.get("source_crs"),
        "language": ["en-CA", "fr-CA"],
        "jurisdiction": registry_source.get("jurisdiction"),
        "currency": registry_source.get("currency"),
        "license_snapshot": _license_snapshot(registry_source),
        "boundary": registry_source.get("boundary"),
    }


def _lineage_matches(
    lineage_path: Path,
    *,
    profile_source: dict[str, Any],
    raw_path: Path,
) -> bool:
    if not lineage_path.is_file() or not raw_path.is_file():
        return False
    try:
        lineage = _json(lineage_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        lineage.get("schema_version") == LINEAGE_SCHEMA_VERSION
        and lineage.get("source_id") == profile_source.get("source_id")
        and lineage.get("source_record_id") == profile_source.get("source_record_id")
        and lineage.get("download_url") == profile_source.get("download_url")
        and lineage.get("source_entry_sha256") == profile_source.get("source_entry_sha256")
        and int(lineage.get("raw_bytes") or -1) == raw_path.stat().st_size
        and lineage.get("raw_sha256") == sha256_path(raw_path)
    )


def _assert_expected_raw(raw_path: Path, profile_source: dict[str, Any]) -> None:
    if not raw_path.is_file():
        raise FileNotFoundError(f"profile raw source is missing: {raw_path}")
    if raw_path.stat().st_size != int(profile_source["expected_raw_bytes"]):
        raise ValueError(f"{profile_source['source_id']} raw byte count differs from the profile contract")
    if sha256_path(raw_path) != profile_source["expected_raw_sha256"]:
        raise ValueError(f"{profile_source['source_id']} raw SHA256 differs from the profile contract")


def _ensure_lineage(
    *,
    profile_source: dict[str, Any],
    registry_source: dict[str, Any],
    data_root: Path,
    registry_path: Path,
    registry_sha256: str,
) -> str:
    raw_path = resolve_state_path(data_root, profile_source, "raw")
    lineage_path = resolve_state_path(data_root, profile_source, "lineage")
    _assert_expected_raw(raw_path, profile_source)
    if _lineage_matches(lineage_path, profile_source=profile_source, raw_path=raw_path):
        return "reused"
    if lineage_path.exists():
        raise ValueError(
            f"{profile_source['source_id']} lineage exists but does not match the verified raw asset; "
            "inspect or move it aside instead of overwriting evidence"
        )
    _write_json_atomically(
        lineage_path,
        _expected_lineage(
            profile_source=profile_source,
            registry_source=registry_source,
            raw_path=raw_path,
            data_root=data_root,
            registry_path=registry_path,
            registry_sha256=registry_sha256,
            fetched_at=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        ),
    )
    return "created"


def _download_source(
    *,
    profile_source: dict[str, Any],
    data_root: Path,
) -> str:
    """Download exact declared bytes to a temporary file before promotion."""

    raw_path = resolve_state_path(data_root, profile_source, "raw")
    if raw_path.exists():
        _assert_expected_raw(raw_path, profile_source)
        return "reused"
    part_path = raw_path.with_name(raw_path.name + ".part")
    if part_path.exists():
        raise FileExistsError(
            f"partial download exists at {part_path}; retain it for diagnosis or remove it explicitly before retrying"
        )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    received = 0
    digest = hashlib.sha256()
    request = urllib.request.Request(
        str(profile_source["download_url"]),
        headers={"User-Agent": "OpenAgronomyAgent/offline-spatial-setup"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, part_path.open("xb") as handle:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) != int(profile_source["expected_raw_bytes"]):
                raise ValueError(
                    f"{profile_source['source_id']} publisher Content-Length differs from the pinned profile bytes"
                )
            for block in iter(lambda: response.read(DOWNLOAD_BLOCK_SIZE), b""):
                received += len(block)
                if received > int(profile_source["expected_raw_bytes"]):
                    raise ValueError(f"{profile_source['source_id']} download exceeds the pinned profile bytes")
                digest.update(block)
                handle.write(block)
    except (OSError, urllib.error.URLError, ValueError):
        # The .part file is deliberate evidence of a failed transfer and is never promoted.
        raise
    if received != int(profile_source["expected_raw_bytes"]):
        raise ValueError(f"{profile_source['source_id']} download byte count differs from the pinned profile")
    if digest.hexdigest() != profile_source["expected_raw_sha256"]:
        raise ValueError(f"{profile_source['source_id']} download SHA256 differs from the pinned profile")
    os.replace(part_path, raw_path)
    return "downloaded"


def _derived_is_current(
    *, profile_source: dict[str, Any], data_root: Path
) -> bool:
    database = resolve_state_path(data_root, profile_source, "derived")
    manifest_path = resolve_state_path(data_root, profile_source, "derived_manifest")
    if not database.is_file() or not manifest_path.is_file():
        return False
    try:
        manifest = _json(manifest_path)
        receipt = _database_receipt(database)
    except (OSError, ValueError, sqlite3.Error):
        return False
    return (
        manifest.get("source_id") == profile_source.get("source_id")
        and manifest.get("source_sha256") == profile_source.get("expected_raw_sha256")
        and manifest.get("source_entry_sha256") == profile_source.get("source_entry_sha256")
        and manifest.get("output_sha256") == sha256_path(database)
        and int(manifest.get("output_bytes") or -1) == database.stat().st_size
        and receipt.get("source_id") == profile_source.get("source_id")
        and receipt.get("source_sha256") == profile_source.get("expected_raw_sha256")
        and receipt.get("source_entry_sha256") == profile_source.get("source_entry_sha256")
    )


def _build_derived_source(
    *,
    profile_source: dict[str, Any],
    registry_source: dict[str, Any],
    data_root: Path,
) -> str:
    if _derived_is_current(profile_source=profile_source, data_root=data_root):
        return "reused"
    database = resolve_state_path(data_root, profile_source, "derived")
    manifest_path = resolve_state_path(data_root, profile_source, "derived_manifest")
    if database.exists() or manifest_path.exists():
        raise FileExistsError(
            f"{profile_source['source_id']} has an incomplete or mismatched derived asset; "
            "inspect or move it aside instead of overwriting it"
        )
    source_id = str(profile_source["source_id"])
    province = SOURCE_ID_TO_PROVINCE.get(source_id)
    if province is not None:
        profile = PROFILES[province]
        build_layer(
            profile=profile,
            source=resolve_state_path(data_root, profile_source, "raw"),
            lineage_path=resolve_state_path(data_root, profile_source, "lineage"),
            output=database,
            manifest_path=manifest_path,
            tolerance_metres=10.0,
            coordinate_precision=0.000001,
            asset_root=data_root,
        )
    elif source_id in CONTEXT_BOUNDARY_SPECS:
        build_context_boundary_layer(
            source_id=source_id,
            source_entry=registry_source,
            source=resolve_state_path(data_root, profile_source, "raw"),
            lineage_path=resolve_state_path(data_root, profile_source, "lineage"),
            output=database,
            manifest_path=manifest_path,
            asset_root=data_root,
        )
    else:
        raise ValueError(f"no local derivation profile is registered for {source_id}")
    if not _derived_is_current(profile_source=profile_source, data_root=data_root):
        raise ValueError(f"{profile_source['source_id']} derivation did not satisfy the profile contract")
    return "built"


def _raw_assets_present(profile: dict[str, Any], data_root: Path) -> bool:
    return all(resolve_state_path(data_root, row, "raw").is_file() for row in profile.get("sources") or [])


def _discard_raw(profile: dict[str, Any], data_root: Path) -> list[str]:
    """Remove only exact verified raw bytes after a successful pack+probe gate."""

    rows: list[tuple[dict[str, Any], Path]] = []
    for profile_source in profile.get("sources") or []:
        if not isinstance(profile_source, dict):
            continue
        raw_path = resolve_state_path(data_root, profile_source, "raw")
        _assert_expected_raw(raw_path, profile_source)
        rows.append((profile_source, raw_path))
    removed: list[str] = []
    for _, raw_path in rows:
        raw_path.unlink()
        removed.append(str(raw_path.relative_to(data_root)))
    return removed


def _run_setup_under_lock(
    *,
    profile_id: str,
    data_root: Path,
    download: bool,
    build: bool,
    verify: bool,
    retain_raw: bool,
    registry_path: Path,
    profile_manifest_path: Path,
    profile: dict[str, Any],
    registry: dict[str, Any],
    pack_root: Path,
    report: dict[str, Any],
) -> None:
    """Execute every state-root operation while its exclusive lock is held."""

    if download or build:
        _check_disk_space(data_root, required_bytes=int(profile["pack"]["minimum_free_bytes"]))
    registry_sha256 = sha256_path(registry_path)
    for source_id in profile_source_ids(profile):
        profile_source = source_row(profile, source_id)
        registry_source = _registry_source(registry, source_id)
        row: dict[str, Any] = {"source_id": source_id, "layer_id": profile_source["layer_id"]}
        raw_path = resolve_state_path(data_root, profile_source, "raw")
        if download:
            row["download"] = _download_source(profile_source=profile_source, data_root=data_root)
        if download or build:
            _assert_expected_raw(raw_path, profile_source)
            row["lineage"] = _ensure_lineage(
                profile_source=profile_source,
                registry_source=registry_source,
                data_root=data_root,
                registry_path=registry_path,
                registry_sha256=registry_sha256,
            )
        if build:
            row["derivation"] = _build_derived_source(
                profile_source=profile_source,
                registry_source=registry_source,
                data_root=data_root,
            )
        report["sources"].append(row)

    if build:
        source_validation = validate_registry(
            registry_path,
            root=data_root,
            profile_manifest_path=profile_manifest_path,
            profile_id=profile_id,
        )
        report["source_validation"] = source_validation
        if source_validation["status"] != "pass":
            raise ValueError("derived source validation failed: " + "; ".join(source_validation["errors"]))
        if pack_root.exists():
            existing_pack = validate_pack(
                pack_root,
                profile_id=profile_id,
                profile_manifest_path=profile_manifest_path,
            )
            if existing_pack["status"] != "pass":
                raise FileExistsError(
                    f"existing pack is invalid or mismatched: {pack_root}; inspect it instead of overwriting it"
                )
            if not retain_raw:
                raise ValueError(
                    "cannot discard raw archives while reusing an existing pack receipt; "
                    "build a fresh state directory or retain the raw archives"
                )
            report["pack"] = {"action": "reused", "validation": existing_pack}
        else:
            report["pack"] = {
                "action": "built",
                **build_pack(
                    registry_path=registry_path,
                    asset_root=data_root,
                    destination=pack_root,
                    profile_id=profile_id,
                    profile_manifest_path=profile_manifest_path,
                    retain_raw=retain_raw,
                ),
            }

    if verify:
        pack_validation = validate_pack(
            pack_root,
            profile_id=profile_id,
            profile_manifest_path=profile_manifest_path,
        )
        report["pack_validation"] = pack_validation
        if pack_validation["status"] != "pass":
            raise ValueError("spatial pack validation failed: " + "; ".join(pack_validation["errors"]))
        if profile_id == "prairie-dss-v1":
            probe = run_prairie_probe(
                pack_root,
                profile_id=profile_id,
                profile_manifest_path=profile_manifest_path,
            )
        elif profile_id == "canada-context-boundaries-v1":
            probe = run_context_boundary_probe(
                pack_root,
                profile_id=profile_id,
                profile_manifest_path=profile_manifest_path,
            )
        else:
            raise ValueError(f"no offline runtime probe is registered for {profile_id}")
        report["runtime_probe"] = probe
        if probe["status"] != "pass":
            raise ValueError("offline spatial runtime probe failed: " + "; ".join(probe["errors"]))

    if build and not retain_raw:
        if not verify:
            raise ValueError("--discard-raw-after-build requires --verify after pack assembly")
        report["removed_raw_assets"] = _discard_raw(profile, data_root)
    elif not _raw_assets_present(profile, data_root):
        report["raw_assets"] = "not_retained; pack/receipt validation remains available"


def run_setup(
    *,
    profile_id: str,
    data_root: Path,
    download: bool,
    build: bool,
    verify: bool,
    dry_run: bool,
    retain_raw: bool,
    registry_path: Path = DEFAULT_REGISTRY,
    profile_manifest_path: Path = DEFAULT_PROFILE_MANIFEST,
) -> dict[str, Any]:
    """Run the requested explicit setup phases and return a provenance receipt."""

    data_root = _external_state_root(data_root)
    registry_path = registry_path.resolve()
    profile_manifest_path = profile_manifest_path.resolve()
    profile = load_profile(profile_manifest_path, profile_id)
    registry = _json(registry_path)
    contract_errors = validate_profile_registry_contract(profile, registry)
    if contract_errors:
        raise ValueError("profile/source-registry contract mismatch: " + "; ".join(contract_errors))
    for source_id in profile_source_ids(profile):
        _assert_download_eligible(_registry_source(registry, source_id))
    pack_root = resolve_pack_root(data_root, profile)
    disk = {
        "available_bytes": shutil.disk_usage(_nearest_existing_directory(data_root)).free,
        "required_bytes": int(profile["pack"]["minimum_free_bytes"]),
    }
    requested = {"download": bool(download), "build": bool(build), "verify": bool(verify)}
    report: dict[str, Any] = {
        "schema_version": SETUP_SCHEMA_VERSION,
        "status": "planned" if dry_run else "pass",
        "profile_id": profile_id,
        "profile_manifest": str(profile_manifest_path),
        "profile_manifest_sha256": sha256_path(profile_manifest_path),
        "profile_entry_sha256": profile_entry_sha256(profile),
        "registry": str(registry_path),
        "registry_sha256": sha256_path(registry_path),
        "data_root": str(data_root),
        "pack_root": str(pack_root),
        "requested": requested,
        "network_requested": bool(download),
        "raw_retained_after_success": bool(retain_raw),
        "disk_space": disk,
        "sources": [],
        "actions": [],
        "runtime_environment": {"AGRONOMY_AGENT_SPATIAL_PACK_ROOT": str(pack_root)},
        "boundary": profile.get("boundary"),
    }
    if dry_run:
        report["actions"] = [
            "validate profile and source-registry entry identities",
            *(
                ["download exact pinned official bytes to .part files, then hash-before-promote"]
                if download
                else []
            ),
            *(
                ["derive WGS84 SQLite/RTree layers and atomically promote a flat runtime pack"]
                if build
                else []
            ),
            *(["verify pack integrity and run offline application-path probes"] if verify else []),
        ]
        for profile_source in profile.get("sources") or []:
            if not isinstance(profile_source, dict):
                continue
            report["sources"].append(
                {
                    "source_id": profile_source["source_id"],
                    "layer_id": profile_source["layer_id"],
                    "raw": str(resolve_state_path(data_root, profile_source, "raw")),
                    "derived": str(resolve_state_path(data_root, profile_source, "derived")),
                    "expected_raw_bytes": profile_source["expected_raw_bytes"],
                    "expected_raw_sha256": profile_source["expected_raw_sha256"],
                }
            )
        return report

    report["state_root_lock"] = {
        "path": str(_state_root_lock_path(data_root)),
        "mode": "exclusive_no_wait",
        "scope": "raw_derived_pack",
    }
    with _exclusive_state_root_lock(data_root=data_root, profile_id=profile_id):
        _run_setup_under_lock(
            profile_id=profile_id,
            data_root=data_root,
            download=download,
            build=build,
            verify=verify,
            retain_raw=retain_raw,
            registry_path=registry_path,
            profile_manifest_path=profile_manifest_path,
            profile=profile,
            registry=registry,
            pack_root=pack_root,
            report=report,
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--profile-manifest", type=Path, default=DEFAULT_PROFILE_MANIFEST)
    parser.add_argument("--download", action="store_true", help="allow the explicit official-source downloads")
    parser.add_argument("--build", action="store_true", help="derive local profile layers and assemble the pack")
    parser.add_argument("--verify", action="store_true", help="validate the pack and run offline runtime probes")
    parser.add_argument("--dry-run", action="store_true", help="show the requested operations without network or writes")
    retention = parser.add_mutually_exclusive_group()
    retention.add_argument(
        "--retain-raw",
        action="store_true",
        help="retain verified raw source archives after a successful build (the safe default)",
    )
    retention.add_argument(
        "--discard-raw-after-build",
        action="store_true",
        help="remove exact verified raw archives only after --build --verify succeeds",
    )
    args = parser.parse_args()
    if not (args.download or args.build or args.verify or args.dry_run):
        parser.error("select at least one of --download, --build, --verify, or --dry-run")
    if args.dry_run and args.discard_raw_after_build:
        parser.error("--dry-run cannot discard raw source archives")
    if args.discard_raw_after_build and not (args.build and args.verify):
        parser.error("--discard-raw-after-build requires both --build and --verify")
    try:
        report = run_setup(
            profile_id=args.profile,
            data_root=args.data_root,
            download=args.download,
            build=args.build,
            verify=args.verify,
            dry_run=args.dry_run,
            retain_raw=not args.discard_raw_after_build,
            registry_path=args.registry,
            profile_manifest_path=args.profile_manifest,
        )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        report = {
            "schema_version": SETUP_SCHEMA_VERSION,
            "status": "fail",
            "error": str(exc),
            "network_requested": bool(args.download),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"pass", "planned"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
