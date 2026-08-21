"""Contracts shared by compact offline spatial-data setup and validation.

The source registry describes known source records.  This module adds the
separate, deliberately narrow concept of an *installable profile*: the exact
source records, pinned input bytes, local-state paths, and flat runtime-pack
contract needed for one offline installation.  It never performs a download
or writes an asset.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA_VERSION = "open_agronomy_agent.offline_spatial_profiles.v1"


def sha256_path(path: Path) -> str:
    """Return the SHA-256 of a file without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    """Hash a JSON-compatible value with a stable representation."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_relative_path(value: Any, *, label: str) -> Path:
    text = str(value or "").strip()
    path = Path(text)
    if not text or str(path) in {"", "."} or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a non-empty relative path without '..'")
    return path


def _required_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_text(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _require_sha256(value: Any, *, label: str) -> str:
    digest = _require_text(value, label=label)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def profile_entry_sha256(profile: dict[str, Any]) -> str:
    """Return the immutable, profile-local identity used in pack receipts."""

    return canonical_json_sha256(profile)


def profile_source_rows(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return checked source rows in their contract-defined order."""

    rows = profile.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"profile {profile.get('id')!r} must contain a non-empty sources list")
    return rows


def source_row(profile: dict[str, Any], source_id: str) -> dict[str, Any]:
    for row in profile_source_rows(profile):
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return row
    raise ValueError(f"profile {profile.get('id')!r} does not contain source {source_id!r}")


def source_ids(profile: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row["source_id"]) for row in profile_source_rows(profile))


def resolve_state_path(state_root: Path, source: dict[str, Any], kind: str) -> Path:
    """Resolve one profile-declared asset path below a state root safely."""

    paths = _required_object(source.get("state_paths"), label=f"{source.get('source_id')} state_paths")
    relative = _safe_relative_path(paths.get(kind), label=f"{source.get('source_id')} state_paths.{kind}")
    root = state_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:  # pragma: no cover - defence after path validation.
        raise ValueError(f"{source.get('source_id')} {kind} escapes the state root") from exc
    return candidate


def resolve_pack_root(state_root: Path, profile: dict[str, Any]) -> Path:
    pack = _required_object(profile.get("pack"), label=f"profile {profile.get('id')} pack")
    relative = _safe_relative_path(pack.get("directory"), label=f"profile {profile.get('id')} pack.directory")
    root = state_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:  # pragma: no cover - defence after path validation.
        raise ValueError(f"profile {profile.get('id')} pack directory escapes the state root") from exc
    return candidate


def profile_pack_filename(profile: dict[str, Any], key: str) -> str:
    pack = _required_object(profile.get("pack"), label=f"profile {profile.get('id')} pack")
    value = _safe_relative_path(pack.get(key), label=f"profile {profile.get('id')} pack.{key}")
    if value.name != str(value):
        raise ValueError(f"profile {profile.get('id')} pack.{key} must be a flat filename")
    return value.name


def _validate_profile(profile: dict[str, Any]) -> None:
    profile_id = _require_text(profile.get("id"), label="profile.id")
    _require_text(profile.get("title"), label=f"profile {profile_id}.title")
    _require_text(profile.get("status"), label=f"profile {profile_id}.status")
    _safe_relative_path(
        profile.get("source_registry_path"), label=f"profile {profile_id}.source_registry_path"
    )
    pack = _required_object(profile.get("pack"), label=f"profile {profile_id}.pack")
    _safe_relative_path(pack.get("directory"), label=f"profile {profile_id}.pack.directory")
    for key in ("manifest", "install_receipt"):
        filename = _safe_relative_path(pack.get(key), label=f"profile {profile_id}.pack.{key}")
        if filename.name != str(filename):
            raise ValueError(f"profile {profile_id}.pack.{key} must be a flat filename")
    if int(pack.get("minimum_free_bytes") or 0) <= 0:
        raise ValueError(f"profile {profile_id}.pack.minimum_free_bytes must be positive")

    seen_source_ids: set[str] = set()
    seen_layer_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, source in enumerate(profile_source_rows(profile)):
        source = _required_object(source, label=f"profile {profile_id}.sources[{index}]")
        source_id = _require_text(source.get("source_id"), label=f"profile {profile_id} source_id")
        layer_id = _require_text(source.get("layer_id"), label=f"profile {profile_id} {source_id}.layer_id")
        if source_id in seen_source_ids or layer_id in seen_layer_ids:
            raise ValueError(f"profile {profile_id} source and layer IDs must be unique")
        seen_source_ids.add(source_id)
        seen_layer_ids.add(layer_id)
        _require_text(source.get("source_record_id"), label=f"profile {profile_id} {source_id}.source_record_id")
        _require_text(source.get("download_url"), label=f"profile {profile_id} {source_id}.download_url")
        _require_sha256(source.get("source_entry_sha256"), label=f"profile {profile_id} {source_id}.source_entry_sha256")
        _require_sha256(source.get("expected_raw_sha256"), label=f"profile {profile_id} {source_id}.expected_raw_sha256")
        if int(source.get("expected_raw_bytes") or 0) <= 0:
            raise ValueError(f"profile {profile_id} {source_id}.expected_raw_bytes must be positive")
        paths = _required_object(source.get("state_paths"), label=f"profile {profile_id} {source_id}.state_paths")
        for key in ("raw", "lineage", "derived", "derived_manifest"):
            path = _safe_relative_path(paths.get(key), label=f"profile {profile_id} {source_id}.state_paths.{key}")
            if str(path) in seen_paths:
                raise ValueError(f"profile {profile_id} reuses state asset path {path}")
            seen_paths.add(str(path))


def load_profile(profile_manifest_path: Path, profile_id: str) -> dict[str, Any]:
    """Load and structurally validate one declared offline spatial profile."""

    manifest = json.loads(profile_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"unsupported offline spatial profile schema in {profile_manifest_path}")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("offline spatial profile manifest must contain profiles")
    matches = [profile for profile in profiles if isinstance(profile, dict) and profile.get("id") == profile_id]
    if len(matches) != 1:
        raise ValueError(f"offline spatial profile {profile_id!r} is not declared exactly once")
    profile = matches[0]
    _validate_profile(profile)
    return profile


def validate_profile_registry_contract(profile: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    """Return profile-to-source-registry identity errors without touching assets."""

    registry_rows = {
        str(source.get("id")): source
        for source in registry.get("sources") or []
        if isinstance(source, dict) and source.get("id")
    }
    errors: list[str] = []
    for profile_source in profile_source_rows(profile):
        source_id = str(profile_source.get("source_id"))
        source = registry_rows.get(source_id)
        if source is None:
            errors.append(f"{source_id} is absent from the source registry")
            continue
        for key in ("source_record_id", "download_url"):
            if source.get(key) != profile_source.get(key):
                errors.append(f"{source_id} {key} does not match the profile contract")
        if canonical_json_sha256(source) != profile_source.get("source_entry_sha256"):
            errors.append(f"{source_id} source registry entry SHA256 does not match the profile contract")
        runtime = source.get("runtime") if isinstance(source.get("runtime"), dict) else {}
        if runtime.get("layer_id") != profile_source.get("layer_id"):
            errors.append(f"{source_id} runtime layer_id does not match the profile contract")
    return errors
