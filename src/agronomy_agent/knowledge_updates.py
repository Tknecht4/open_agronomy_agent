from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from agronomy_agent.artifact_signature import sign_manifest, verify_manifest_signature
from agronomy_agent.corpus_governance import ALLOWED_ELIGIBILITY, audit_runtime_corpora
from agronomy_agent.knowledge_update_trust import (
    VerifiedKnowledgeUpdateTrustPolicy,
    private_key_id,
    sign_bytes,
    verify_bytes,
)


KNOWLEDGE_UPDATE_SCHEMA = "open_agronomy_agent.knowledge_update.v2"
THRESHOLD_KNOWLEDGE_UPDATE_SCHEMA = "open_agronomy_agent.knowledge_update.v3"
SUPPORTED_KNOWLEDGE_UPDATE_SCHEMAS = {
    KNOWLEDGE_UPDATE_SCHEMA,
    THRESHOLD_KNOWLEDGE_UPDATE_SCHEMA,
}
ACTIVATION_SCHEMA = "open_agronomy_agent.knowledge_activation.v2"
RECEIPT_SCHEMA = "open_agronomy_agent.knowledge_update_receipt.v2"
PREVIEW_SCHEMA = "open_agronomy_agent.knowledge_update_preview.v1"
TRANSACTION_SCHEMA = "open_agronomy_agent.knowledge_update_transaction.v1"
RECOVERY_SCHEMA = "open_agronomy_agent.knowledge_update_recovery.v1"
MANIFEST_NAME = "knowledge_update_manifest.json"
SIGNATURE_NAME = "knowledge_update_manifest.sig"
SIGNATURES_DIR_NAME = "knowledge_update_signatures"
ACTIVE_NAME = "active.json"
TRANSACTION_NAME = "pending_transaction.json"
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_MEMBERS = 8192
MAX_EXTRACTED_BYTES = 4 * 1024**3
MAX_SINGLE_FILE_BYTES = 2 * 1024**3
MAX_FUTURE_CLOCK_SKEW = dt.timedelta(hours=24)
MAX_CLOCK_ROLLBACK = dt.timedelta(minutes=5)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_knowledge_update(
    *,
    repo_root: Path,
    rag_config: Path,
    output_archive: Path,
    package_id: str,
    release_sequence: int,
    expires_at: str | dt.datetime,
    private_key: Path | None = None,
    signer_private_keys: Iterable[Path] = (),
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    notes: str = "",
    extra_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """Build a portable RAG release whose manifest can be signed offline."""

    repo_root = repo_root.resolve()
    rag_config = rag_config.resolve()
    package_id = _safe_id(package_id)
    release_sequence = _safe_sequence(release_sequence)
    created_at_value = _utc_now()
    expires_at_value = _parse_utc_datetime(expires_at, field="expires_at")
    if expires_at_value <= created_at_value:
        raise ValueError("knowledge update expires_at must be after created_at")
    if not rag_config.is_file():
        raise FileNotFoundError(rag_config)
    if repo_root != rag_config and repo_root not in rag_config.parents:
        raise ValueError("RAG configuration must be inside the repository")

    source_config = yaml.safe_load(rag_config.read_text(encoding="utf-8")) or {}
    retrieval = source_config.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ValueError("RAG configuration must contain a retrieval mapping")
    configured = [
        *(retrieval.get("corpus_paths") or []),
        *(retrieval.get("graph_paths") or []),
    ]
    policy = retrieval.get("corpus_policy_manifest")
    if policy:
        configured.append(policy)

    source_paths = [rag_config, *(_repo_file(repo_root, value) for value in configured)]
    source_paths.extend(path.resolve() for path in extra_paths)
    relative_paths: dict[str, Path] = {}
    for source in source_paths:
        if not source.is_file():
            raise FileNotFoundError(source)
        if repo_root != source and repo_root not in source.parents:
            raise ValueError(f"knowledge update source escapes repository: {source}")
        relative = source.relative_to(repo_root).as_posix()
        relative_path = PurePosixPath(relative)
        if (
            relative_path == PurePosixPath(MANIFEST_NAME)
            or relative_path == PurePosixPath(SIGNATURE_NAME)
            or relative_path.parts[0] == SIGNATURES_DIR_NAME
        ):
            raise ValueError(f"knowledge update source uses a reserved package path: {relative}")
        if relative in relative_paths and relative_paths[relative] != source:
            raise ValueError(f"duplicate package path: {relative}")
        relative_paths[relative] = source

    output_archive = output_archive.resolve()
    output_archive.parent.mkdir(parents=True, exist_ok=True)
    if output_archive.exists() or output_archive.is_symlink():
        raise FileExistsError(f"knowledge update archive already exists: {output_archive}")
    signer_paths = [path.resolve() for path in signer_private_keys]
    if trust_policy is not None:
        if private_key is not None:
            raise ValueError("legacy private_key cannot be combined with a threshold trust policy")
        if len(signer_paths) < trust_policy.threshold:
            raise ValueError("threshold knowledge update requires enough signer private keys")
    elif signer_paths:
        raise ValueError("signer_private_keys require a verified trust policy")
    with tempfile.TemporaryDirectory(prefix=".knowledge-update-build-", dir=output_archive.parent) as temp_name:
        package_root = Path(temp_name) / package_id
        package_root.mkdir()
        for relative, source in sorted(relative_paths.items()):
            target = package_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        config_relative = rag_config.relative_to(repo_root)
        packaged_config_path = package_root / config_relative
        packaged_config = yaml.safe_load(packaged_config_path.read_text(encoding="utf-8")) or {}
        packaged_retrieval = packaged_config.setdefault("retrieval", {})
        packaged_retrieval["artifact_root"] = os.path.relpath(package_root, packaged_config_path.parent)
        packaged_config_path.write_text(
            yaml.safe_dump(packaged_config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        entries = [_file_entry(package_root, path) for path in _package_files(package_root)]
        manifest = {
            "schema_version": (
                THRESHOLD_KNOWLEDGE_UPDATE_SCHEMA
                if trust_policy is not None
                else KNOWLEDGE_UPDATE_SCHEMA
            ),
            "package_id": package_id,
            "release_sequence": release_sequence,
            "created_at": _format_utc(created_at_value),
            "expires_at": _format_utc(expires_at_value),
            "rag_config": config_relative.as_posix(),
            "source_rag_config_sha256": sha256_path(rag_config),
            "notes": notes,
            "files": entries,
            "security_boundary": (
                "The detached Ed25519 signature authenticates this manifest; manifest hashes and byte counts "
                "bind every packaged file. Activation additionally runs the corpus governance audit."
            ),
        }
        signer_key_ids: list[str] = []
        if trust_policy is not None:
            signer_key_ids = sorted(private_key_id(path) for path in signer_paths)
            if len(signer_key_ids) != len(set(signer_key_ids)):
                raise ValueError("duplicate threshold signer private key")
            for key_id in signer_key_ids:
                trust_policy.key_for_signature(key_id, signed_at=created_at_value)
            manifest["signature_policy"] = {
                "policy_id": trust_policy.policy_id,
                "required_threshold": trust_policy.threshold,
                "signing_key_ids": signer_key_ids,
            }
        manifest_path = package_root / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if trust_policy is not None:
            signatures_dir = package_root / SIGNATURES_DIR_NAME
            signatures_dir.mkdir(mode=0o700)
            manifest_bytes = manifest_path.read_bytes()
            for signer_path in signer_paths:
                key_id, signature = sign_bytes(signer_path, manifest_bytes)
                (signatures_dir / f"{key_id}.sig").write_bytes(signature)
        elif private_key is not None:
            sign_manifest(
                manifest=manifest_path,
                private_key=private_key.resolve(),
                signature=package_root / SIGNATURE_NAME,
            )

        partial = output_archive.with_name(
            f".{output_archive.name}.{uuid.uuid4().hex}.partial"
        )
        try:
            with tarfile.open(partial, "w:gz", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(package_root.rglob("*")):
                    archive.add(
                        path,
                        arcname=str(
                            Path(package_id) / path.relative_to(package_root)
                        ),
                        recursive=False,
                    )
            os.link(partial, output_archive)
            partial.unlink()
            directory = os.open(output_archive.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            partial.unlink(missing_ok=True)

    return {
        "schema_version": manifest["schema_version"],
        "status": "built",
        "package_id": package_id,
        "release_sequence": release_sequence,
        "expires_at": _format_utc(expires_at_value),
        "archive": str(output_archive),
        "archive_sha256": sha256_path(output_archive),
        "manifest_sha256": sha256_path(manifest_path) if manifest_path.exists() else _manifest_hash(manifest),
        "signed": private_key is not None or bool(signer_paths),
        "signature_mode": (
            "threshold_policy"
            if trust_policy is not None
            else "legacy_single_key"
            if private_key is not None
            else "unsigned_development"
        ),
        "signing_key_ids": signer_key_ids,
        "file_count": len(entries),
        "rag_config": config_relative.as_posix(),
    }


def validate_knowledge_update(
    package_root: Path,
    *,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest_path = package_root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in SUPPORTED_KNOWLEDGE_UPDATE_SCHEMAS:
        raise ValueError("unsupported knowledge update schema")
    package_id = _safe_id(str(manifest.get("package_id") or ""))
    if package_root.name != package_id:
        raise ValueError("package directory does not match manifest package_id")
    release_sequence = _safe_sequence(manifest.get("release_sequence"))
    created_at = _parse_utc_datetime(manifest.get("created_at"), field="created_at")
    expires_at = _parse_utc_datetime(manifest.get("expires_at"), field="expires_at")
    if expires_at <= created_at:
        raise ValueError("knowledge update expires_at must be after created_at")
    checked_at = _coerce_now(now)
    if trust_policy is not None:
        trust_policy.validate_freshness(now=checked_at)
    if created_at > checked_at + MAX_FUTURE_CLOCK_SKEW:
        raise ValueError("knowledge update created_at is too far in the future")
    if checked_at >= expires_at:
        raise ValueError("knowledge update has expired")

    signature_path = package_root / SIGNATURE_NAME
    if schema_version == THRESHOLD_KNOWLEDGE_UPDATE_SCHEMA:
        if trust_policy is None:
            raise ValueError("v3 knowledge update requires a verified threshold trust policy")
        if public_key is not None or allow_unsigned:
            raise ValueError("v3 knowledge update cannot use legacy or unsigned verification")
        signature = _verify_threshold_manifest(
            package_root=package_root,
            manifest_path=manifest_path,
            manifest=manifest,
            created_at=created_at,
            trust_policy=trust_policy,
        )
    elif trust_policy is not None:
        raise ValueError(
            "legacy v2 knowledge updates are rejected in threshold trust-policy mode"
        )
    elif public_key is not None:
        signature = verify_manifest_signature(
            manifest=manifest_path,
            public_key=public_key.resolve(),
            signature=signature_path,
        )
        if not signature["verified"]:
            raise ValueError("knowledge update manifest signature is invalid")
    elif not allow_unsigned:
        raise ValueError("a pinned public key is required unless unsigned development updates are explicitly allowed")
    else:
        signature = {"verified": False, "status": "unsigned_development_only"}

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("knowledge update manifest must contain files")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("knowledge update file entries must be objects")
        relative = _safe_relative(str(entry.get("path") or ""))
        normalized = relative.as_posix()
        if normalized in seen:
            raise ValueError(f"duplicate knowledge update file: {normalized}")
        seen.add(normalized)
        target = _inside(package_root, Path(*relative.parts))
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(target)
        if target.stat().st_size != int(entry.get("bytes") or -1):
            raise ValueError(f"knowledge update byte count mismatch: {normalized}")
        if sha256_path(target) != entry.get("sha256"):
            raise ValueError(f"knowledge update checksum mismatch: {normalized}")

    actual_files = {
        path.relative_to(package_root).as_posix()
        for path in _package_files(package_root)
        if path.name not in {MANIFEST_NAME, SIGNATURE_NAME}
    }
    if actual_files != seen:
        unexpected = sorted(actual_files - seen)
        missing = sorted(seen - actual_files)
        raise ValueError(f"knowledge update file set mismatch: unexpected={unexpected}, missing={missing}")

    rag_relative = _safe_relative(str(manifest.get("rag_config") or ""))
    if rag_relative.as_posix() not in seen:
        raise ValueError("packaged RAG configuration is not bound by the manifest")
    rag_config = _inside(package_root, Path(*rag_relative.parts))
    config = yaml.safe_load(rag_config.read_text(encoding="utf-8")) or {}
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    artifact_root = (rag_config.parent / str(retrieval.get("artifact_root") or "")).resolve()
    if artifact_root != package_root:
        raise ValueError("packaged RAG artifact_root must resolve to the package root")
    audit = audit_runtime_corpora(root=package_root, rag_config_path=rag_config)
    if audit["status"] != "pass":
        raise ValueError(f"knowledge update corpus audit failed: {audit['errors']}")

    return {
        "schema_version": schema_version,
        "status": "valid",
        "package_id": package_id,
        "release_sequence": release_sequence,
        "created_at": _format_utc(created_at),
        "expires_at": _format_utc(expires_at),
        "validated_at": _format_utc(checked_at),
        "manifest_sha256": sha256_path(manifest_path),
        "signature": signature,
        "rag_config": str(rag_config),
        "file_count": len(entries),
        "corpus_audit": audit,
    }


def install_knowledge_update(
    *,
    archive: Path,
    update_root: Path,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    actor: str = "local_admin",
    reason: str = "knowledge_update",
    expected_manifest_sha256: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    update_root = update_root.resolve()
    with _update_lock(update_root):
        _recover_knowledge_update_transaction_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        return _install_knowledge_update_locked(
            archive=archive,
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            actor=actor,
            reason=reason,
            expected_manifest_sha256=expected_manifest_sha256,
            now=now,
        )


def _install_knowledge_update_locked(
    *,
    archive: Path,
    update_root: Path,
    public_key: Path | None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None,
    allow_unsigned: bool,
    actor: str,
    reason: str,
    expected_manifest_sha256: str | None,
    now: dt.datetime | None,
) -> dict[str, Any]:
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    releases = update_root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    before = read_activation(update_root)
    checked_at = _coerce_now(now)
    with tempfile.TemporaryDirectory(prefix=".knowledge-update-stage-", dir=update_root) as temp_name:
        stage = Path(temp_name)
        package_root = _extract_archive_safely(archive, stage)
        validation = validate_knowledge_update(
            package_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        if (
            expected_manifest_sha256 is not None
            and validation["manifest_sha256"] != expected_manifest_sha256
        ):
            raise ValueError("knowledge update manifest does not match the reviewed preview")
        package_id = validation["package_id"]
        if (
            before
            and before.get("package_id") != package_id
            and validation["release_sequence"] <= before["highest_release_sequence"]
        ):
            raise ValueError(
                "knowledge update release_sequence must increase for install; "
                "use explicit rollback for an older release"
            )
        release = releases / package_id
        if release.exists():
            existing = validate_knowledge_update(
                release,
                public_key=public_key,
                trust_policy=trust_policy,
                allow_unsigned=allow_unsigned,
                now=now,
            )
            if existing["manifest_sha256"] != validation["manifest_sha256"]:
                raise FileExistsError(f"release id already exists with different contents: {package_id}")
        else:
            package_root.replace(release)
        _make_release_read_only(release)

    if before and before.get("package_id") == package_id:
        if before.get("manifest_sha256") != validation["manifest_sha256"]:
            raise ValueError("active package id matches but manifest hash differs")
        receipt = _write_receipt(
            update_root=update_root,
            operation="install_noop",
            actor=actor,
            reason=reason,
            before=before,
            after=before,
            validation=validation,
            archive_sha256=sha256_path(archive),
        )
        return {
            "status": "already_active",
            "activation": before,
            "receipt": receipt,
            "validation": validation,
        }
    after = _activation_payload(
        package_id=package_id,
        rag_config_relative=Path(validation["rag_config"]).relative_to(package_root).as_posix(),
        manifest_sha256=validation["manifest_sha256"],
        release_sequence=validation["release_sequence"],
        highest_release_sequence=max(
            validation["release_sequence"],
            (before or {}).get("highest_release_sequence", 0),
        ),
        expires_at=validation["expires_at"],
        previous_package_id=(before or {}).get("package_id"),
        operation="install",
        activated_at=checked_at,
        clock_floor=_next_clock_floor(before, checked_at),
    )
    transaction = _begin_activation_transaction(
        update_root=update_root,
        operation="install",
        actor=actor,
        reason=reason,
        before=before,
        after=after,
        validation=validation,
        archive_sha256=sha256_path(archive),
    )
    _write_activation(update_root=update_root, activation=after)
    try:
        receipt = _write_receipt(
            update_root=update_root,
            operation="install",
            actor=actor,
            reason=reason,
            before=before,
            after=after,
            validation=validation,
            archive_sha256=transaction["archive_sha256"],
            receipt_id=transaction["receipt_id"],
        )
    except BaseException:
        _restore_activation(update_root=update_root, activation=before)
        _discard_transaction_receipt(
            update_root=update_root,
            receipt_id=transaction["receipt_id"],
        )
        _clear_activation_transaction(update_root)
        raise
    _clear_activation_transaction(update_root)
    return {"status": "activated", "activation": after, "receipt": receipt, "validation": validation}


def preview_knowledge_update(
    *,
    archive: Path,
    update_root: Path,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Validate an archive and summarize its effect without storing or activating it."""

    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    update_root = update_root.resolve()
    with _update_lock(update_root):
        _recover_knowledge_update_transaction_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        before = read_activation(update_root)
        with tempfile.TemporaryDirectory(
            prefix=f".{update_root.name}.knowledge-update-preview-",
            dir=update_root.parent,
        ) as temp_name:
            package_root = _extract_archive_safely(archive, Path(temp_name))
            candidate = validate_knowledge_update(
                package_root,
                public_key=public_key,
                trust_policy=trust_policy,
                allow_unsigned=allow_unsigned,
                now=now,
            )
            candidate_manifest = _read_manifest(package_root)

            active: dict[str, Any] | None = None
            active_manifest: dict[str, Any] | None = None
            active_error: str | None = None
            if before:
                active_root = update_root / "releases" / before["package_id"]
                try:
                    active = validate_knowledge_update(
                        active_root,
                        public_key=public_key,
                        trust_policy=trust_policy,
                        allow_unsigned=allow_unsigned,
                        now=now,
                    )
                    active_manifest = _read_manifest(active_root)
                except (ValueError, FileNotFoundError, json.JSONDecodeError, yaml.YAMLError, OSError) as exc:
                    active_error = str(exc)

            action = "activate"
            blockers: list[str] = []
            if before and before["package_id"] == candidate["package_id"]:
                if before["manifest_sha256"] == candidate["manifest_sha256"]:
                    action = "no_op"
                else:
                    action = "blocked"
                    blockers.append("package_id_collision")
            elif before and candidate["release_sequence"] <= before["highest_release_sequence"]:
                action = "blocked"
                blockers.append("release_sequence_not_above_high_water")

            return {
                "schema_version": PREVIEW_SCHEMA,
                "status": "ready" if not blockers else "blocked",
                "activation_allowed": not blockers,
                "activation_action": action,
                "blockers": blockers,
                "archive": str(archive),
                "archive_sha256": sha256_path(archive),
                "candidate": _preview_release(candidate, candidate_manifest),
                "active": _preview_release(active, active_manifest) if active and active_manifest else None,
                "active_activation": before,
                "active_validation_error": active_error,
                "changes": _preview_changes(
                    active=active,
                    active_manifest=active_manifest,
                    candidate=candidate,
                    candidate_manifest=candidate_manifest,
                ),
                "boundary": (
                    "Preview verifies the signed archive and compares it with the active release. "
                    "It does not activate or retain the candidate."
                ),
            }


def rollback_knowledge_update(
    *,
    update_root: Path,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    actor: str = "local_admin",
    reason: str = "operator_rollback",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    update_root = update_root.resolve()
    with _update_lock(update_root):
        _recover_knowledge_update_transaction_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        return _rollback_knowledge_update_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            actor=actor,
            reason=reason,
            now=now,
        )


def _rollback_knowledge_update_locked(
    *,
    update_root: Path,
    public_key: Path | None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None,
    allow_unsigned: bool,
    actor: str,
    reason: str,
    now: dt.datetime | None,
) -> dict[str, Any]:
    before = read_activation(update_root)
    if not before:
        raise FileNotFoundError("no active knowledge update")
    target_id = before.get("previous_package_id")
    if not target_id:
        raise ValueError("active knowledge update has no rollback target")
    target = update_root / "releases" / _safe_id(str(target_id))
    validation = validate_knowledge_update(
        target,
        public_key=public_key,
        trust_policy=trust_policy,
        allow_unsigned=allow_unsigned,
        now=now,
    )
    rag_relative = Path(validation["rag_config"]).relative_to(target).as_posix()
    checked_at = _coerce_now(now)
    after = _activation_payload(
        package_id=validation["package_id"],
        rag_config_relative=rag_relative,
        manifest_sha256=validation["manifest_sha256"],
        release_sequence=validation["release_sequence"],
        highest_release_sequence=before["highest_release_sequence"],
        expires_at=validation["expires_at"],
        previous_package_id=before["package_id"],
        operation="rollback",
        activated_at=checked_at,
        clock_floor=_next_clock_floor(before, checked_at),
    )
    transaction = _begin_activation_transaction(
        update_root=update_root,
        operation="rollback",
        actor=actor,
        reason=reason,
        before=before,
        after=after,
        validation=validation,
        archive_sha256=None,
    )
    _write_activation(update_root=update_root, activation=after)
    try:
        receipt = _write_receipt(
            update_root=update_root,
            operation="rollback",
            actor=actor,
            reason=reason,
            before=before,
            after=after,
            validation=validation,
            archive_sha256=None,
            receipt_id=transaction["receipt_id"],
        )
    except BaseException:
        _restore_activation(update_root=update_root, activation=before)
        _discard_transaction_receipt(
            update_root=update_root,
            receipt_id=transaction["receipt_id"],
        )
        _clear_activation_transaction(update_root)
        raise
    _clear_activation_transaction(update_root)
    return {"status": "rolled_back", "activation": after, "receipt": receipt, "validation": validation}


def recover_knowledge_update_transaction(
    *,
    update_root: Path,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Resolve an interrupted activation transaction before serving knowledge."""

    update_root = update_root.resolve()
    with _update_lock(update_root):
        return _recover_knowledge_update_transaction_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )


def _recover_knowledge_update_transaction_locked(
    *,
    update_root: Path,
    public_key: Path | None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None,
    allow_unsigned: bool,
    now: dt.datetime | None,
) -> dict[str, Any]:
    journal_path = update_root / TRANSACTION_NAME
    if not journal_path.is_file():
        return {
            "schema_version": RECOVERY_SCHEMA,
            "status": "clean",
            "action": "none",
        }
    transaction = json.loads(journal_path.read_text(encoding="utf-8"))
    _validate_activation_transaction(transaction)
    before = transaction["before_activation"]
    after = transaction["intended_activation"]
    current = read_activation(update_root)
    receipt_valid = _transaction_receipt_is_valid(
        update_root=update_root,
        transaction=transaction,
    )

    if current == after and receipt_valid:
        _validate_activation_target(
            update_root=update_root,
            activation=after,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        action = "retain_committed"
    elif current == before:
        _discard_transaction_receipt(
            update_root=update_root,
            receipt_id=transaction["receipt_id"],
        )
        action = "discard_prepared"
    elif current == after:
        if before is not None:
            _validate_activation_target(
                update_root=update_root,
                activation=before,
                public_key=public_key,
                trust_policy=trust_policy,
                allow_unsigned=allow_unsigned,
                now=now,
            )
        _restore_activation(update_root=update_root, activation=before)
        _discard_transaction_receipt(
            update_root=update_root,
            receipt_id=transaction["receipt_id"],
        )
        action = "rollback_unreceipted_activation"
    else:
        raise ValueError(
            "knowledge update activation does not match either side of the "
            "pending transaction; manual recovery is required"
        )

    report = {
        "schema_version": RECOVERY_SCHEMA,
        "status": "recovered",
        "action": action,
        "transaction_id": transaction["transaction_id"],
        "operation": transaction["operation"],
        "before_package_id": (before or {}).get("package_id"),
        "intended_package_id": after["package_id"],
        "receipt_complete": receipt_valid,
        "recovered_at": _now(),
        "boundary": (
            "Recovery retains an intended activation only when both its receipt "
            "and receipt digest are durable; otherwise it restores the exact "
            "pre-transaction activation. Signed release validation still runs "
            "before the recovered release can serve knowledge."
        ),
    }
    _record_transaction_recovery(update_root=update_root, report=report)
    _clear_activation_transaction(update_root)
    return report


def read_activation(update_root: Path) -> dict[str, Any] | None:
    path = update_root.resolve() / ACTIVE_NAME
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ACTIVATION_SCHEMA:
        raise ValueError("unsupported knowledge activation schema")
    _safe_id(str(payload.get("package_id") or ""))
    release_sequence = _safe_sequence(payload.get("release_sequence"))
    highest_release_sequence = _safe_sequence(payload.get("highest_release_sequence"))
    if highest_release_sequence < release_sequence:
        raise ValueError("knowledge activation highest_release_sequence cannot be below the active sequence")
    _parse_utc_datetime(payload.get("expires_at"), field="expires_at")
    _parse_utc_datetime(payload.get("activated_at"), field="activated_at")
    _activation_clock_floor(payload)
    if payload.get("previous_package_id"):
        _safe_id(str(payload["previous_package_id"]))
    return payload


def validate_activation_freshness(
    activation: dict[str, Any],
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    expires_at = _parse_utc_datetime(activation.get("expires_at"), field="expires_at")
    checked_at = _coerce_now(now)
    clock_floor = _activation_clock_floor(activation)
    if checked_at < clock_floor - MAX_CLOCK_ROLLBACK:
        raise ValueError(
            "device clock is behind the durable knowledge-update time floor; "
            "restore trusted system time before using this release"
        )
    if checked_at >= expires_at:
        raise ValueError("active knowledge update has expired")
    active_sequence = _safe_sequence(activation.get("release_sequence"))
    highest_sequence = _safe_sequence(activation.get("highest_release_sequence"))
    if highest_sequence < active_sequence:
        raise ValueError("knowledge activation highest_release_sequence cannot be below the active sequence")
    return {
        "status": "fresh",
        "release_sequence": active_sequence,
        "highest_release_sequence": highest_sequence,
        "expires_at": _format_utc(expires_at),
        "checked_at": _format_utc(checked_at),
        "clock_floor": _format_utc(clock_floor),
    }


def resolve_active_rag_config(
    *,
    update_root: Path,
    fallback: str | Path,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    now: dt.datetime | None = None,
) -> Path:
    update_root = update_root.resolve()
    with _update_lock(update_root):
        _recover_knowledge_update_transaction_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        return _resolve_active_rag_config_locked(
            update_root=update_root,
            fallback=fallback,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )


def _resolve_active_rag_config_locked(
    *,
    update_root: Path,
    fallback: str | Path,
    public_key: Path | None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None,
    allow_unsigned: bool,
    now: dt.datetime | None,
) -> Path:
    activation = read_activation(update_root)
    if not activation:
        return Path(fallback)
    validate_activation_freshness(activation, now=now)
    release = update_root.resolve() / "releases" / activation["package_id"]
    validation = validate_knowledge_update(
        release,
        public_key=public_key,
        trust_policy=trust_policy,
        allow_unsigned=allow_unsigned,
        now=now,
    )
    if validation["manifest_sha256"] != activation.get("manifest_sha256"):
        raise ValueError("active knowledge update manifest does not match activation receipt")
    if validation["release_sequence"] != activation.get("release_sequence"):
        raise ValueError("active knowledge update sequence does not match activation receipt")
    if validation["expires_at"] != activation.get("expires_at"):
        raise ValueError("active knowledge update expiry does not match activation receipt")
    rag_config = Path(validation["rag_config"]).resolve()
    expected = _inside(release.resolve(), Path(*_safe_relative(activation["rag_config"]).parts))
    if rag_config != expected:
        raise ValueError("active knowledge update RAG configuration mismatch")
    return rag_config


def knowledge_update_status(
    *,
    update_root: Path,
    public_key: Path | None = None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None = None,
    allow_unsigned: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    update_root = update_root.resolve()
    with _update_lock(update_root):
        recovery = _recover_knowledge_update_transaction_locked(
            update_root=update_root,
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        activation = read_activation(update_root)
        if not activation:
            return {
                "schema_version": ACTIVATION_SCHEMA,
                "status": "no_active_update",
                "activation": None,
                "transaction_recovery": recovery,
            }
        freshness = validate_activation_freshness(activation, now=now)
        rag_config = _resolve_active_rag_config_locked(
            update_root=update_root,
            fallback="",
            public_key=public_key,
            trust_policy=trust_policy,
            allow_unsigned=allow_unsigned,
            now=now,
        )
        return {
            "schema_version": ACTIVATION_SCHEMA,
            "status": "active",
            "activation": activation,
            "freshness": freshness,
            "rag_config": str(rag_config),
            "transaction_recovery": recovery,
        }


def _activation_payload(
    *,
    package_id: str,
    rag_config_relative: str,
    manifest_sha256: str,
    release_sequence: int,
    highest_release_sequence: int,
    expires_at: str,
    previous_package_id: str | None,
    operation: str,
    activated_at: dt.datetime | None = None,
    clock_floor: dt.datetime | None = None,
) -> dict[str, Any]:
    active_sequence = _safe_sequence(release_sequence)
    highest_sequence = _safe_sequence(highest_release_sequence)
    if highest_sequence < active_sequence:
        raise ValueError("highest_release_sequence cannot be below the active sequence")
    activated = _coerce_now(activated_at)
    floor = _coerce_now(clock_floor or activated)
    if floor > activated:
        activated = floor
    return {
        "schema_version": ACTIVATION_SCHEMA,
        "package_id": _safe_id(package_id),
        "rag_config": _safe_relative(rag_config_relative).as_posix(),
        "manifest_sha256": manifest_sha256,
        "release_sequence": active_sequence,
        "highest_release_sequence": highest_sequence,
        "expires_at": _format_utc(_parse_utc_datetime(expires_at, field="expires_at")),
        "activated_at": _format_utc(activated),
        "clock_floor": _format_utc(floor),
        "previous_package_id": _safe_id(previous_package_id) if previous_package_id else None,
        "operation": operation,
    }


def _write_activation(
    *,
    update_root: Path,
    activation: dict[str, Any],
) -> None:
    update_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(update_root / ACTIVE_NAME, activation)


def _restore_activation(
    *,
    update_root: Path,
    activation: dict[str, Any] | None,
) -> None:
    path = update_root / ACTIVE_NAME
    if activation is not None:
        _atomic_json(path, activation)
        return
    path.unlink(missing_ok=True)
    if path.parent.is_dir():
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _write_receipt(
    *,
    update_root: Path,
    operation: str,
    actor: str,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    validation: dict[str, Any],
    archive_sha256: str | None,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    receipts = update_root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    prior = sorted(receipts.glob("*.json"))
    prior_hash = sha256_path(prior[-1]) if prior else None
    receipt_id = receipt_id or _new_receipt_id()
    payload = {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "recorded_at": _now(),
        "operation": operation,
        "actor": actor,
        "reason": reason,
        "before_package_id": (before or {}).get("package_id"),
        "before_release_sequence": (before or {}).get("release_sequence"),
        "before_highest_release_sequence": (before or {}).get("highest_release_sequence"),
        "after_package_id": after["package_id"],
        "after_release_sequence": after["release_sequence"],
        "after_highest_release_sequence": after["highest_release_sequence"],
        "expires_at": after["expires_at"],
        "manifest_sha256": validation["manifest_sha256"],
        "archive_sha256": archive_sha256,
        "signature_verified": bool(validation["signature"].get("verified")),
        "corpus_audit_status": validation["corpus_audit"]["status"],
        "previous_receipt_sha256": prior_hash,
    }
    path = receipts / f"{receipt_id}.json"
    _atomic_json(path, payload)
    digest = sha256_path(path)
    _atomic_text(receipts / f"{receipt_id}.sha256", f"{digest}  {path.name}\n", encoding="ascii")
    return {**payload, "path": str(path), "sha256": digest}


def _begin_activation_transaction(
    *,
    update_root: Path,
    operation: str,
    actor: str,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    validation: dict[str, Any],
    archive_sha256: str | None,
) -> dict[str, Any]:
    path = update_root / TRANSACTION_NAME
    if path.exists() or path.is_symlink():
        raise RuntimeError(
            "pending knowledge update transaction must be recovered before activation"
        )
    receipt_id = _new_receipt_id()
    payload = {
        "schema_version": TRANSACTION_SCHEMA,
        "transaction_id": uuid.uuid4().hex,
        "prepared_at": _now(),
        "operation": operation,
        "actor": actor,
        "reason": reason,
        "before_activation": before,
        "intended_activation": after,
        "receipt_id": receipt_id,
        "archive_sha256": archive_sha256,
        "validation": {
            "manifest_sha256": validation["manifest_sha256"],
            "signature_verified": bool(validation["signature"].get("verified")),
            "corpus_audit_status": validation["corpus_audit"]["status"],
        },
    }
    _validate_activation_transaction(payload)
    _atomic_json(path, payload)
    return payload


def _validate_activation_transaction(transaction: Any) -> None:
    if not isinstance(transaction, dict):
        raise ValueError("knowledge update transaction must be an object")
    expected = {
        "schema_version",
        "transaction_id",
        "prepared_at",
        "operation",
        "actor",
        "reason",
        "before_activation",
        "intended_activation",
        "receipt_id",
        "archive_sha256",
        "validation",
    }
    if set(transaction) != expected:
        raise ValueError("knowledge update transaction fields are invalid")
    if transaction["schema_version"] != TRANSACTION_SCHEMA:
        raise ValueError("unsupported knowledge update transaction schema")
    _safe_id(str(transaction["transaction_id"]))
    _parse_utc_datetime(transaction["prepared_at"], field="transaction prepared_at")
    if transaction["operation"] not in {"install", "rollback"}:
        raise ValueError("knowledge update transaction operation is invalid")
    if not isinstance(transaction["actor"], str) or not transaction["actor"].strip():
        raise ValueError("knowledge update transaction actor is invalid")
    if not isinstance(transaction["reason"], str) or not transaction["reason"].strip():
        raise ValueError("knowledge update transaction reason is invalid")
    before = transaction["before_activation"]
    if before is not None:
        _validate_activation_record(before)
    after = transaction["intended_activation"]
    _validate_activation_record(after)
    _safe_id(str(transaction["receipt_id"]))
    archive_sha256 = transaction["archive_sha256"]
    if archive_sha256 is not None and (
        not isinstance(archive_sha256, str)
        or len(archive_sha256) != 64
        or any(character not in "0123456789abcdef" for character in archive_sha256)
    ):
        raise ValueError("knowledge update transaction archive SHA-256 is invalid")
    validation = transaction["validation"]
    if not isinstance(validation, dict) or set(validation) != {
        "manifest_sha256",
        "signature_verified",
        "corpus_audit_status",
    }:
        raise ValueError("knowledge update transaction validation summary is invalid")
    if validation["manifest_sha256"] != after["manifest_sha256"]:
        raise ValueError("knowledge update transaction manifest binding is invalid")
    if not isinstance(validation["signature_verified"], bool):
        raise ValueError("knowledge update transaction signature state is invalid")
    if validation["corpus_audit_status"] != "pass":
        raise ValueError("knowledge update transaction corpus audit did not pass")


def _validate_activation_record(activation: Any) -> None:
    if not isinstance(activation, dict):
        raise ValueError("knowledge activation record must be an object")
    if activation.get("schema_version") != ACTIVATION_SCHEMA:
        raise ValueError("unsupported knowledge activation schema")
    _safe_id(str(activation.get("package_id") or ""))
    release_sequence = _safe_sequence(activation.get("release_sequence"))
    highest_sequence = _safe_sequence(activation.get("highest_release_sequence"))
    if highest_sequence < release_sequence:
        raise ValueError(
            "knowledge activation highest_release_sequence cannot be below the active sequence"
        )
    manifest_sha256 = activation.get("manifest_sha256")
    if (
        not isinstance(manifest_sha256, str)
        or len(manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in manifest_sha256)
    ):
        raise ValueError("knowledge activation manifest SHA-256 is invalid")
    _safe_relative(str(activation.get("rag_config") or ""))
    _parse_utc_datetime(activation.get("expires_at"), field="expires_at")
    _parse_utc_datetime(activation.get("activated_at"), field="activated_at")
    _activation_clock_floor(activation)
    if activation.get("previous_package_id"):
        _safe_id(str(activation["previous_package_id"]))
    if activation.get("operation") not in {"install", "rollback"}:
        raise ValueError("knowledge activation operation is invalid")


def _validate_activation_target(
    *,
    update_root: Path,
    activation: dict[str, Any],
    public_key: Path | None,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy | None,
    allow_unsigned: bool,
    now: dt.datetime | None,
) -> None:
    _validate_activation_record(activation)
    release = update_root / "releases" / activation["package_id"]
    validation = validate_knowledge_update(
        release,
        public_key=public_key,
        trust_policy=trust_policy,
        allow_unsigned=allow_unsigned,
        now=now,
    )
    if validation["manifest_sha256"] != activation["manifest_sha256"]:
        raise ValueError(
            "pending transaction activation does not match the installed release"
        )
    if validation["release_sequence"] != activation["release_sequence"]:
        raise ValueError(
            "pending transaction activation sequence does not match the installed release"
        )


def _transaction_receipt_is_valid(
    *,
    update_root: Path,
    transaction: dict[str, Any],
) -> bool:
    receipt_id = transaction["receipt_id"]
    receipts = update_root / "receipts"
    receipt_path = receipts / f"{receipt_id}.json"
    digest_path = receipts / f"{receipt_id}.sha256"
    if not receipt_path.is_file() or not digest_path.is_file():
        return False
    digest = sha256_path(receipt_path)
    if digest_path.read_text(encoding="ascii") != f"{digest}  {receipt_path.name}\n":
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    before = transaction["before_activation"] or {}
    after = transaction["intended_activation"]
    validation = transaction["validation"]
    expected = {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "operation": transaction["operation"],
        "actor": transaction["actor"],
        "reason": transaction["reason"],
        "before_package_id": before.get("package_id"),
        "before_release_sequence": before.get("release_sequence"),
        "before_highest_release_sequence": before.get("highest_release_sequence"),
        "after_package_id": after["package_id"],
        "after_release_sequence": after["release_sequence"],
        "after_highest_release_sequence": after["highest_release_sequence"],
        "expires_at": after["expires_at"],
        "manifest_sha256": validation["manifest_sha256"],
        "archive_sha256": transaction["archive_sha256"],
        "signature_verified": validation["signature_verified"],
        "corpus_audit_status": validation["corpus_audit_status"],
    }
    return all(receipt.get(key) == value for key, value in expected.items())


def _record_transaction_recovery(
    *,
    update_root: Path,
    report: dict[str, Any],
) -> None:
    recovery_dir = update_root / "recovery"
    _atomic_json(recovery_dir / f"{report['transaction_id']}.json", report)


def _clear_activation_transaction(update_root: Path) -> None:
    path = update_root / TRANSACTION_NAME
    path.unlink(missing_ok=True)
    _fsync_directory_if_present(path.parent)


def _discard_transaction_receipt(
    *,
    update_root: Path,
    receipt_id: str,
) -> None:
    receipts = update_root / "receipts"
    (receipts / f"{receipt_id}.json").unlink(missing_ok=True)
    (receipts / f"{receipt_id}.sha256").unlink(missing_ok=True)
    _fsync_directory_if_present(receipts)


def _new_receipt_id() -> str:
    return (
        f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{uuid.uuid4().hex[:8]}"
    )


def _activation_clock_floor(activation: dict[str, Any]) -> dt.datetime:
    return _parse_utc_datetime(
        activation.get("clock_floor") or activation.get("activated_at"),
        field="clock_floor",
    )


def _next_clock_floor(
    before: dict[str, Any] | None,
    checked_at: dt.datetime,
) -> dt.datetime:
    if before is None:
        return checked_at
    floor = _activation_clock_floor(before)
    if checked_at < floor - MAX_CLOCK_ROLLBACK:
        raise ValueError(
            "device clock is behind the durable knowledge-update time floor; "
            "restore trusted system time before changing releases"
        )
    return max(floor, checked_at)


def _extract_archive_safely(archive_path: Path, destination: Path) -> Path:
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("knowledge update archive exceeds the compressed-size limit")
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("knowledge update archive is empty")
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("knowledge update archive contains too many members")
        top_levels: set[str] = set()
        member_paths: set[str] = set()
        extracted_bytes = 0
        for member in members:
            relative = _safe_relative(member.name)
            normalized = relative.as_posix()
            if normalized in member_paths:
                raise ValueError(f"duplicate knowledge update archive member: {normalized}")
            member_paths.add(normalized)
            top_levels.add(relative.parts[0])
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsupported archive member type: {member.name}")
            target = _inside(destination, Path(*relative.parts))
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"unsupported archive member type: {member.name}")
            if member.size < 0 or member.size > MAX_SINGLE_FILE_BYTES:
                raise ValueError(f"knowledge update archive member exceeds the file-size limit: {member.name}")
            extracted_bytes += member.size
            if extracted_bytes > MAX_EXTRACTED_BYTES:
                raise ValueError("knowledge update archive exceeds the extracted-size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read archive member: {member.name}")
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
        if len(top_levels) != 1:
            raise ValueError("knowledge update archive must contain one package directory")
    package_root = destination / next(iter(top_levels))
    if not package_root.is_dir():
        raise ValueError("knowledge update archive has no package directory")
    return package_root


def _repo_file(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (repo_root / path).resolve()


def _package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative in {Path(MANIFEST_NAME), Path(SIGNATURE_NAME)}:
            continue
        if relative.parts[0] == SIGNATURES_DIR_NAME:
            continue
        files.append(path)
    return sorted(files)


def _read_manifest(package_root: Path) -> dict[str, Any]:
    payload = json.loads((package_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("knowledge update manifest must be an object")
    return payload


def _preview_release(
    validation: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    audit = validation["corpus_audit"]
    return {
        "package_id": validation["package_id"],
        "release_sequence": validation["release_sequence"],
        "created_at": validation["created_at"],
        "expires_at": validation["expires_at"],
        "manifest_sha256": validation["manifest_sha256"],
        "signature_verified": bool(validation["signature"].get("verified")),
        "notes": str(manifest.get("notes") or ""),
        "file_count": validation["file_count"],
        "configured_corpus_count": audit["configured_corpus_count"],
        "row_counts_by_eligibility": audit["row_counts_by_eligibility"],
    }


def _preview_changes(
    *,
    active: dict[str, Any] | None,
    active_manifest: dict[str, Any] | None,
    candidate: dict[str, Any],
    candidate_manifest: dict[str, Any],
) -> dict[str, Any]:
    active_files = _manifest_file_map(active_manifest)
    candidate_files = _manifest_file_map(candidate_manifest)
    active_corpora = _corpus_audit_map(active)
    candidate_corpora = _corpus_audit_map(candidate)
    eligibility = sorted(ALLOWED_ELIGIBILITY)
    active_counts = (
        active["corpus_audit"]["row_counts_by_eligibility"] if active else {}
    )
    candidate_counts = candidate["corpus_audit"]["row_counts_by_eligibility"]
    return {
        "files_added": sorted(candidate_files.keys() - active_files.keys()),
        "files_removed": sorted(active_files.keys() - candidate_files.keys()),
        "files_changed": sorted(
            path
            for path in candidate_files.keys() & active_files.keys()
            if candidate_files[path] != active_files[path]
        ),
        "corpora_added": sorted(candidate_corpora.keys() - active_corpora.keys()),
        "corpora_removed": sorted(active_corpora.keys() - candidate_corpora.keys()),
        "corpora_changed": sorted(
            path
            for path in candidate_corpora.keys() & active_corpora.keys()
            if candidate_corpora[path] != active_corpora[path]
        ),
        "row_delta_by_eligibility": {
            role: int(candidate_counts.get(role, 0)) - int(active_counts.get(role, 0))
            for role in eligibility
        },
    }


def _manifest_file_map(manifest: dict[str, Any] | None) -> dict[str, tuple[str, int]]:
    if not manifest:
        return {}
    return {
        str(entry["path"]): (str(entry["sha256"]), int(entry["bytes"]))
        for entry in manifest.get("files", [])
        if isinstance(entry, dict)
    }


def _corpus_audit_map(validation: dict[str, Any] | None) -> dict[str, tuple[str, str, int]]:
    if not validation:
        return {}
    return {
        str(row["path"]): (
            str(row["sha256"]),
            str(row["runtime_eligibility"]),
            int(row["rows"]),
        )
        for row in validation["corpus_audit"]["corpora"]
    }


def _verify_threshold_manifest(
    *,
    package_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    created_at: dt.datetime,
    trust_policy: VerifiedKnowledgeUpdateTrustPolicy,
) -> dict[str, Any]:
    policy = manifest.get("signature_policy")
    if not isinstance(policy, dict):
        raise ValueError("v3 knowledge update signature_policy must be an object")
    expected_fields = {
        "policy_id",
        "required_threshold",
        "signing_key_ids",
    }
    if set(policy) != expected_fields:
        raise ValueError("v3 knowledge update signature_policy fields are invalid")
    if policy["policy_id"] != trust_policy.policy_id:
        raise ValueError("knowledge update trust policy id mismatch")
    manifest_threshold = policy["required_threshold"]
    if (
        isinstance(manifest_threshold, bool)
        or not isinstance(manifest_threshold, int)
        or manifest_threshold < 1
    ):
        raise ValueError("knowledge update signature threshold is invalid")
    key_ids = policy["signing_key_ids"]
    if (
        not isinstance(key_ids, list)
        or len(key_ids) < max(manifest_threshold, trust_policy.threshold)
        or key_ids != sorted(key_ids)
        or len(key_ids) != len(set(key_ids))
        or any(
            not isinstance(key_id, str)
            or len(key_id) != 64
            or any(character not in "0123456789abcdef" for character in key_id)
            for key_id in key_ids
        )
    ):
        raise ValueError("knowledge update signing_key_ids are invalid")
    signatures_dir = package_root / SIGNATURES_DIR_NAME
    if signatures_dir.is_symlink() or not signatures_dir.is_dir():
        raise ValueError("v3 knowledge update signature directory is missing or unsafe")
    legacy_signature_path = package_root / SIGNATURE_NAME
    if legacy_signature_path.exists() or legacy_signature_path.is_symlink():
        raise ValueError("v3 knowledge update contains a legacy signature")
    actual_paths = list(signatures_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in actual_paths):
        raise ValueError("v3 knowledge update signature directory contains unsafe entries")
    expected_names = {f"{key_id}.sig" for key_id in key_ids}
    actual_names = {path.name for path in actual_paths}
    if actual_names != expected_names:
        raise ValueError("knowledge update signature file set does not match its manifest")
    manifest_bytes = manifest_path.read_bytes()
    # Evaluate signer eligibility as a set before verifying individual
    # signatures. Otherwise the diagnostic depends on the lexical order of
    # random key IDs: a rotated package containing both a revoked signer and a
    # still-active signer whose new authorization window starts later could
    # report either condition first. Rejection is fail-closed in both cases,
    # but revocation must take deterministic precedence.
    revoked_key_ids = sorted(
        key_id
        for key_id in key_ids
        if (
            (trusted_key := trust_policy.keys.get(key_id)) is not None
            and trusted_key.status != "active"
        )
    )
    if revoked_key_ids:
        raise ValueError(
            f"knowledge update signing key is revoked: {revoked_key_ids[0]}"
        )
    untrusted_key_ids = sorted(
        key_id for key_id in key_ids if key_id not in trust_policy.keys
    )
    if untrusted_key_ids:
        raise ValueError(
            f"knowledge update signing key is not trusted: {untrusted_key_ids[0]}"
        )
    outside_period_key_ids = sorted(
        key_id
        for key_id in key_ids
        if (
            created_at < trust_policy.keys[key_id].not_before
            or created_at > trust_policy.keys[key_id].not_after
        )
    )
    if outside_period_key_ids:
        raise ValueError(
            "knowledge update signing key was outside its authorized signing "
            f"period: {outside_period_key_ids[0]}"
        )
    verified: list[str] = []
    for key_id in key_ids:
        trusted_key = trust_policy.key_for_signature(
            key_id,
            signed_at=created_at,
        )
        signature_bytes = (signatures_dir / f"{key_id}.sig").read_bytes()
        if len(signature_bytes) != 64:
            raise ValueError("knowledge update Ed25519 signature length is invalid")
        verify_bytes(
            trusted_key.public_key,
            payload=manifest_bytes,
            signature=signature_bytes,
        )
        verified.append(key_id)
    if len(verified) < trust_policy.threshold:
        raise ValueError("knowledge update signature threshold was not met")
    return {
        "verified": True,
        "status": "verified_threshold_policy",
        "policy_id": trust_policy.policy_id,
        "policy_sequence": trust_policy.policy_sequence,
        "policy_sha256": trust_policy.sha256,
        "required_threshold": trust_policy.threshold,
        "verified_key_ids": verified,
        "root_public_key_sha256": trust_policy.root_public_key_sha256,
    }


def _make_release_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _file_entry(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_path(path),
    }


def _safe_id(value: str) -> str:
    if not value or value in {".", ".."} or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._" for ch in value):
        raise ValueError("knowledge update package id contains unsafe characters")
    return value


def _safe_sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("knowledge update release_sequence must be a positive integer")
    return value


def _parse_utc_datetime(value: Any, *, field: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = dt.datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"knowledge update {field} must be an ISO-8601 datetime") from exc
    else:
        raise ValueError(f"knowledge update {field} must be an ISO-8601 datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"knowledge update {field} must include a timezone")
    return parsed.astimezone(dt.UTC)


def _coerce_now(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return _utc_now()
    return _parse_utc_datetime(value, field="validation time")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _format_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).replace(microsecond=0).isoformat()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"unsafe package-relative path: {value}")
    return path


def _inside(root: Path, relative: Path) -> Path:
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"path escapes knowledge update root: {relative}")
    return target


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _atomic_text(path: Path, value: str, *, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding=encoding) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory_if_present(path: Path) -> None:
    if not path.is_dir():
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _update_lock(update_root: Path):
    update_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = update_root.parent / f".{update_root.name}.knowledge-update.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now() -> str:
    return _format_utc(_utc_now())


def _manifest_hash(manifest: dict[str, Any]) -> str:
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
