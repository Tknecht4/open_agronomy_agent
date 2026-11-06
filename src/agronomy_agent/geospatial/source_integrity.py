"""Read-only identity gate for optional, locally derived spatial layers.

This binds a database to its derivation receipt and the current registered
source. It does not establish map accuracy, source currency, or field truth.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path


SCHEMA_VERSION = "open_agronomy_agent.local_layer_integrity.v1"
LAYER_SCHEMA_VERSION = "open_agronomy_agent.local_geo_layer.v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 64


def _identity(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
        return (str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except OSError:
        return (str(path.absolute()), None)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _object(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest byte limit exceeded")
    value = json.loads(payload, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    return value


def _entry_sha256(source: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _positive_integer(value: Any) -> bool:
    return type(value) is int and value > 0


def _hash_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def local_layer_integrity(
    database: Path | str,
    *,
    layer_id: str,
    registry_path: Path | None = None,
    profile_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Return a bounded integrity receipt without modifying any source file.

    A missing database is distinct from an installed but unverified database.
    There is no permissive path for databases lacking derivation receipts.
    Explicit test registries can bind synthetic fixtures through the same gate.
    Filesystem identity includes ctime and inode so restoring size and mtime
    after a mutation cannot reuse a prior verification in the process cache.
    """
    database = Path(database).expanduser()
    manifest = database.with_name(f"{database.stem}_manifest.json")
    registry = registry_path or repo_path("data/manifests/canada_geospatial_sources.json")
    profiles = profile_manifest_path or repo_path("data/manifests/offline_spatial_profiles_v1.json")
    sidecars = tuple(Path(str(database) + suffix) for suffix in ("-wal", "-journal", "-shm"))
    paths = (database, manifest, registry, profiles, *sidecars)
    identities = tuple(_identity(path) for path in paths)
    key = (str(layer_id), *identities)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return deepcopy(cached)

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "layer_id": layer_id,
        "status": "integrity_failed",
        "errors": [],
        "observed": {},
        "expected": {},
        "filesystem_identity_sha256": hashlib.sha256(
            json.dumps(identities, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "boundary": "Database, derivation and registered-source identity only; not map accuracy, current observations or field truth.",
    }
    errors = result["errors"]
    observed = result["observed"]
    expected = result["expected"]
    if not database.is_file():
        result["status"] = "missing"
        errors.append("database_missing")
    else:
        try:
            observed["database_bytes"] = database.stat().st_size
            observed["database_sha256"] = _sha256(database)
            descriptor = _object(manifest)
            observed["manifest_sha256"] = _sha256(manifest)
            registered = _object(registry)
            observed["registry_sha256"] = _sha256(registry)
            profile = _object(profiles)
            observed["profile_manifest_sha256"] = _sha256(profiles)
            sources = [
                source for source in registered.get("sources", [])
                if isinstance(source, dict)
                and isinstance(source.get("runtime"), dict)
                and source["runtime"].get("layer_id") == layer_id
            ]
            if len(sources) != 1:
                errors.append("registered_layer_identity_missing_or_ambiguous")
            else:
                source = sources[0]
                expected["source_id"] = source.get("id")
                if not isinstance(source.get("id"), str) or not source["id"]:
                    errors.append("registered_source_identity_invalid")
                expected["source_entry_sha256"] = _entry_sha256(source)
                pinned_hashes = {
                    row.get("expected_raw_sha256")
                    for selected in profile.get("profiles", []) if isinstance(selected, dict)
                    for row in selected.get("sources", []) if isinstance(row, dict)
                    and row.get("source_id") == source.get("id")
                }
                if len(pinned_hashes) > 1:
                    errors.append("profile_raw_source_identity_ambiguous")
                elif pinned_hashes:
                    expected["source_sha256"] = next(iter(pinned_hashes))
                expected["database_sha256"] = descriptor.get("output_sha256")
                expected["database_bytes"] = descriptor.get("output_bytes")
                expected["feature_count"] = descriptor.get("feature_count")
                if descriptor.get("schema_version") != LAYER_SCHEMA_VERSION:
                    errors.append("derivation_schema_mismatch")
                if descriptor.get("source_id") != expected["source_id"]:
                    errors.append("derivation_source_identity_mismatch")
                if descriptor.get("output_sha256") != observed["database_sha256"]:
                    errors.append("database_sha256_mismatch")
                if type(descriptor.get("output_bytes")) is not int or descriptor["output_bytes"] != observed["database_bytes"]:
                    errors.append("database_byte_count_mismatch")
                if descriptor.get("output_crs") != "EPSG:4326":
                    errors.append("derivation_crs_mismatch")
                if not _positive_integer(descriptor.get("feature_count")):
                    errors.append("derivation_feature_count_invalid")
                if "source_sha256" in expected and descriptor.get("source_sha256") != expected["source_sha256"]:
                    errors.append("derivation_raw_source_identity_mismatch")
                if not _hash_string(descriptor.get("source_sha256")):
                    errors.append("derivation_raw_source_identity_invalid")
                descriptor_entry = descriptor.get("source_entry_sha256")
                if descriptor_entry is not None:
                    if descriptor_entry != expected["source_entry_sha256"]:
                        errors.append("derivation_source_entry_mismatch")
                elif descriptor.get("source_registry_sha256") != observed["registry_sha256"]:
                    errors.append("derivation_legacy_registry_mismatch")

                # Immutable prevents SQLite from reading unchecked WAL sidecars.
                # Concurrent mutation remains forbidden; stat stability is checked below.
                connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
                try:
                    rows = connection.execute("SELECT key, value_json FROM metadata LIMIT 129").fetchall()
                    if len(rows) > 128 or sum(len(str(value).encode("utf-8")) for _, value in rows) > MAX_MANIFEST_BYTES:
                        raise ValueError("database metadata limit exceeded")
                    metadata = {str(k): json.loads(v, parse_constant=_reject_constant) for k, v in rows}
                    observed["database_metadata"] = {
                        name: metadata.get(name) for name in (
                            "schema_version", "source_id", "source_sha256", "source_entry_sha256",
                            "source_registry_sha256", "output_crs", "feature_count",
                        )
                    }
                    observed["sqlite_quick_check"] = [row[0] for row in connection.execute("PRAGMA quick_check")]
                    observed["feature_count"] = connection.execute("SELECT COUNT(*) FROM features").fetchone()[0]
                    observed["rtree_count"] = connection.execute("SELECT COUNT(*) FROM feature_bounds").fetchone()[0]
                finally:
                    connection.close()
                for name in ("schema_version", "source_id", "source_sha256", "output_crs", "feature_count"):
                    if metadata.get(name) != descriptor.get(name):
                        errors.append(f"database_metadata_{name}_mismatch")
                metadata_entry = metadata.get("source_entry_sha256")
                if metadata_entry is not None:
                    if metadata_entry != expected["source_entry_sha256"]:
                        errors.append("database_source_entry_mismatch")
                elif metadata.get("source_registry_sha256") != observed["registry_sha256"]:
                    errors.append("database_legacy_registry_mismatch")
                if observed["sqlite_quick_check"] != ["ok"]:
                    errors.append("sqlite_quick_check_failed")
                if observed["feature_count"] != descriptor.get("feature_count") or observed["rtree_count"] != observed["feature_count"]:
                    errors.append("database_feature_count_mismatch")
            for sidecar in sidecars:
                if sidecar.exists():
                    errors.append("database_sidecar_present")
                    break
        except FileNotFoundError:
            errors.append("identity_receipt_missing")
        except (OSError, ValueError, TypeError, RecursionError, sqlite3.Error) as exc:
            errors.append(f"identity_unreadable:{type(exc).__name__}")
        if tuple(_identity(path) for path in paths) != identities:
            errors.append("source_changed_during_verification")
        if not errors:
            result["status"] = "verified"
    result["fingerprint"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    if "source_changed_during_verification" not in errors:
        with _CACHE_LOCK:
            _CACHE[key] = deepcopy(result)
            _CACHE.move_to_end(key)
            while len(_CACHE) > _CACHE_MAX_ENTRIES:
                _CACHE.popitem(last=False)
    return result
