from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_NAME = "backup_manifest.json"
MANIFEST_DIGEST_NAME = "backup_manifest.sha256"
DB_SNAPSHOT_NAME = "cockpit.sqlite3"
ARTIFACTS_DIR_NAME = "artifacts"
KNOWLEDGE_UPDATES_DIR_NAME = "knowledge_updates"
RESTORE_JOURNAL_SCHEMA = "open_agronomy_agent.restore_transaction.v2"
RESTORE_RECOVERY_SCHEMA = "open_agronomy_agent.restore_recovery.v1"


@dataclass(frozen=True)
class BackupResult:
    backup_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]


def create_backup(
    *,
    db_path: Path,
    artifact_root: Path,
    backup_root: Path,
    backup_id: str | None = None,
    knowledge_update_root: Path | None = None,
) -> BackupResult:
    db_path = db_path.resolve()
    artifact_root = artifact_root.resolve()
    backup_root = backup_root.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    if not artifact_root.exists():
        raise FileNotFoundError(f"artifact root not found: {artifact_root}")
    backup_id = _safe_backup_id(backup_id or f"phase4-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = (backup_root / backup_id).resolve()
    if backup_dir.exists():
        raise FileExistsError(f"backup already exists: {backup_dir}")
    if backup_root != backup_dir and backup_root not in backup_dir.parents:
        raise ValueError("backup directory escapes backup root")
    staged_dir = backup_root / f".{backup_id}.{uuid.uuid4().hex}.partial"
    staged_dir.mkdir(mode=0o700)
    try:
        db_snapshot = staged_dir / DB_SNAPSHOT_NAME
        _sqlite_backup(db_path, db_snapshot)
        artifact_snapshot = staged_dir / ARTIFACTS_DIR_NAME
        _copy_artifacts(artifact_root, artifact_snapshot)
        knowledge_snapshot = staged_dir / KNOWLEDGE_UPDATES_DIR_NAME
        if knowledge_update_root is not None:
            knowledge_update_root = knowledge_update_root.resolve()
            if not knowledge_update_root.exists():
                raise FileNotFoundError(
                    f"knowledge update root not found: {knowledge_update_root}"
                )
            _copy_artifacts(knowledge_update_root, knowledge_snapshot)

        manifest = {
            "format": (
                "agronomy-agent-phase4-backup-v3"
                if knowledge_update_root is not None
                else "agronomy-agent-phase4-backup-v2"
            ),
            "backup_id": backup_id,
            "created_at_unix": int(time.time()),
            "source": {
                "db_path": str(db_path),
                "artifact_root": str(artifact_root),
            },
            "database": _file_entry(db_snapshot, name=DB_SNAPSHOT_NAME),
            "artifacts": _manifest_files(artifact_snapshot),
        }
        if knowledge_update_root is not None:
            manifest["source"]["knowledge_update_root"] = str(knowledge_update_root)
            manifest["knowledge_updates"] = _manifest_files(knowledge_snapshot)
        staged_manifest_path = staged_dir / MANIFEST_NAME
        staged_manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staged_manifest_path.chmod(0o600)
        digest_path = staged_dir / MANIFEST_DIGEST_NAME
        digest_path.write_text(
            f"{_sha256(staged_manifest_path)}  {MANIFEST_NAME}\n",
            encoding="ascii",
        )
        digest_path.chmod(0o600)
        validate_backup(staged_dir)
        _fsync_restore_staging([staged_dir])
        if backup_dir.exists() or backup_dir.is_symlink():
            raise FileExistsError(f"backup already exists: {backup_dir}")
        staged_dir.rename(backup_dir)
        _fsync_directory(backup_root)
    except BaseException:
        _remove_path(staged_dir)
        raise
    manifest_path = backup_dir / MANIFEST_NAME
    return BackupResult(backup_dir=backup_dir, manifest_path=manifest_path, manifest=manifest)


def validate_backup(backup_dir: Path) -> dict[str, Any]:
    if backup_dir.is_symlink():
        raise ValueError(f"backup directory must not be a symlink: {backup_dir}")
    backup_dir = backup_dir.resolve()
    if not backup_dir.is_dir():
        raise FileNotFoundError(f"backup directory not found: {backup_dir}")
    manifest_path = backup_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"backup manifest not found: {manifest_path}")
    digest_path = backup_dir / MANIFEST_DIGEST_NAME
    if not digest_path.is_file():
        raise FileNotFoundError(f"backup manifest digest not found: {digest_path}")
    expected_digest, separator, bound_name = digest_path.read_text(encoding="ascii").strip().partition("  ")
    if not separator or bound_name != MANIFEST_NAME or expected_digest != _sha256(manifest_path):
        raise ValueError("backup manifest digest mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") not in {
        "agronomy-agent-phase4-backup-v2",
        "agronomy-agent-phase4-backup-v3",
    }:
        raise ValueError("unsupported backup format")
    _assert_file_entry(backup_dir / DB_SNAPSHOT_NAME, manifest["database"])
    artifact_dir = backup_dir / ARTIFACTS_DIR_NAME
    for entry in manifest.get("artifacts", []):
        relative_path = _safe_relative(entry["path"])
        _assert_file_entry(artifact_dir / relative_path, entry)
    knowledge_dir = backup_dir / KNOWLEDGE_UPDATES_DIR_NAME
    for entry in manifest.get("knowledge_updates", []):
        relative_path = _safe_relative(entry["path"])
        _assert_file_entry(knowledge_dir / relative_path, entry)
    _validate_exact_backup_contents(backup_dir, manifest)
    return manifest


def restore_backup(
    *,
    backup_dir: Path,
    target_db_path: Path,
    target_artifact_root: Path,
    target_knowledge_update_root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    manifest = validate_backup(backup_dir)
    backup_dir = backup_dir.resolve()
    if target_db_path.is_symlink():
        raise ValueError(f"target database must not be a symlink: {target_db_path}")
    if target_artifact_root.is_symlink():
        raise ValueError(f"target artifact root must not be a symlink: {target_artifact_root}")
    if target_knowledge_update_root is not None and target_knowledge_update_root.is_symlink():
        raise ValueError(
            f"target knowledge update root must not be a symlink: {target_knowledge_update_root}"
        )
    target_db_path = target_db_path.resolve()
    target_artifact_root = target_artifact_root.resolve()
    if manifest.get("knowledge_updates") and target_knowledge_update_root is None:
        raise ValueError("target_knowledge_update_root is required for a backup containing knowledge updates")
    target_knowledge_update_root = (
        target_knowledge_update_root.resolve()
        if target_knowledge_update_root is not None
        else None
    )
    if _path_exists(target_db_path) and not overwrite:
        raise FileExistsError(f"target database exists: {target_db_path}")
    if target_artifact_root.exists() and any(target_artifact_root.iterdir()) and not overwrite:
        raise FileExistsError(f"target artifact root is not empty: {target_artifact_root}")
    if (
        target_knowledge_update_root is not None
        and target_knowledge_update_root.exists()
        and any(target_knowledge_update_root.iterdir())
        and not overwrite
    ):
        raise FileExistsError(f"target knowledge update root is not empty: {target_knowledge_update_root}")

    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    target_artifact_root.parent.mkdir(parents=True, exist_ok=True)
    if target_knowledge_update_root is not None:
        target_knowledge_update_root.parent.mkdir(parents=True, exist_ok=True)

    journal_path = restore_journal_path(target_db_path)
    pending_journal_path = restore_journal_pending_path(target_db_path)
    if _path_exists(journal_path) or _path_exists(pending_journal_path):
        raise FileExistsError(
            f"pending restore journal state exists: {journal_path}; recover it before starting another restore"
        )
    transaction_id = uuid.uuid4().hex
    staged_db = target_db_path.with_name(f".{target_db_path.name}.restore-{transaction_id}.stage")
    staged_artifacts = target_artifact_root.with_name(
        f".{target_artifact_root.name}.restore-{transaction_id}.stage"
    )
    staged_knowledge = (
        target_knowledge_update_root.with_name(
            f".{target_knowledge_update_root.name}.restore-{transaction_id}.stage"
        )
        if target_knowledge_update_root is not None
        else None
    )

    staged_paths = [staged_db, staged_artifacts]
    if staged_knowledge is not None:
        staged_paths.append(staged_knowledge)
    try:
        shutil.copy2(backup_dir / DB_SNAPSHOT_NAME, staged_db)
        staged_db.chmod(0o600)
        _assert_file_entry(staged_db, manifest["database"])
        staged_artifacts.mkdir(mode=0o700)
        artifact_source = backup_dir / ARTIFACTS_DIR_NAME
        for entry in manifest.get("artifacts", []):
            relative_path = _safe_relative(entry["path"])
            source = artifact_source / relative_path
            target = (staged_artifacts / relative_path).resolve()
            if staged_artifacts != target and staged_artifacts not in target.parents:
                raise ValueError(f"artifact restore path escapes target root: {relative_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            target.chmod(0o600)
            _assert_file_entry(target, entry)
        _make_tree_private(staged_artifacts)
        if staged_knowledge is not None:
            staged_knowledge.mkdir(mode=0o700)
            knowledge_source = backup_dir / KNOWLEDGE_UPDATES_DIR_NAME
            for entry in manifest.get("knowledge_updates", []):
                relative_path = _safe_relative(entry["path"])
                source = knowledge_source / relative_path
                target = (staged_knowledge / relative_path).resolve()
                if staged_knowledge != target and staged_knowledge not in target.parents:
                    raise ValueError(f"knowledge update restore path escapes target root: {relative_path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                target.chmod(0o600)
                _assert_file_entry(target, entry)
            _restore_knowledge_update_permissions(staged_knowledge)
    except BaseException:
        for staged in staged_paths:
            _remove_path(staged)
        raise

    replacements = [
        ("database", target_db_path, staged_db),
        ("artifacts", target_artifact_root, staged_artifacts),
    ]
    if target_knowledge_update_root is not None and staged_knowledge is not None:
        replacements.append(("knowledge_updates", target_knowledge_update_root, staged_knowledge))
    _fsync_restore_staging(staged_paths)
    journal = _build_restore_journal(
        transaction_id=transaction_id,
        backup_dir=backup_dir,
        backup_manifest_sha256=_sha256(backup_dir / MANIFEST_NAME),
        replacements=replacements,
    )
    try:
        _atomic_private_json(journal_path, journal)
    except BaseException:
        for staged in staged_paths:
            _remove_path(staged)
        raise
    _restore_checkpoint("journal_prepared", journal_path)
    _commit_staged_restore(journal_path)
    return manifest


def restore_journal_path(target_db_path: Path) -> Path:
    target_db_path = target_db_path.resolve()
    return target_db_path.with_name(f".{target_db_path.name}.restore-journal.json")


def restore_journal_pending_path(target_db_path: Path) -> Path:
    journal_path = restore_journal_path(target_db_path)
    return journal_path.with_name(f"{journal_path.name}.pending")


def assert_no_pending_restore(target_db_path: Path) -> None:
    journal_path = restore_journal_path(target_db_path)
    pending_path = restore_journal_pending_path(target_db_path)
    if _path_exists(journal_path) or _path_exists(pending_path):
        raise RuntimeError(
            f"pending restore journal blocks database use: {journal_path}; run "
            f"`python scripts/phase4_backup.py recover --target-db-path {target_db_path}` first"
        )


def recover_interrupted_restore(journal_path: Path) -> dict[str, Any]:
    if journal_path.is_symlink():
        raise ValueError(f"restore journal must not be a symlink: {journal_path}")
    journal_path = journal_path.resolve()
    pending_path = journal_path.with_name(f"{journal_path.name}.pending")
    if pending_path.is_symlink():
        raise ValueError(f"pending restore journal must not be a symlink: {pending_path}")
    pending_reconciliation = "none"
    if not journal_path.is_file() and pending_path.is_file():
        pending = _read_restore_journal(
            pending_path,
            expected_journal_path=journal_path,
        )
        if pending["status"] != "prepared":
            raise ValueError(
                "a committed pending journal without an authoritative journal is ambiguous"
            )
        os.replace(pending_path, journal_path)
        _fsync_directory(journal_path.parent)
        pending_reconciliation = "promoted_prepared_pending_journal"
    elif journal_path.is_file() and pending_path.is_file():
        authoritative = _read_restore_journal(journal_path)
        pending = _read_restore_journal(
            pending_path,
            expected_journal_path=journal_path,
        )
        shared_fields = (
            "schema_version",
            "transaction_id",
            "backup_dir",
            "backup_manifest_sha256",
            "entries",
            "recovery_policy",
        )
        if any(pending[field] != authoritative[field] for field in shared_fields):
            raise ValueError("pending restore journal does not match the authoritative transaction")
        pending_path.unlink()
        _fsync_directory(pending_path.parent)
        pending_reconciliation = "discarded_non_authoritative_pending_journal"
    if not journal_path.is_file():
        return {
            "schema_version": RESTORE_RECOVERY_SCHEMA,
            "status": "no_pending_restore",
            "journal": str(journal_path),
            "pending_journal_reconciliation": pending_reconciliation,
        }
    journal = _read_restore_journal(journal_path)
    action = (
        _finalize_committed_restore(journal_path, journal)
        if journal["status"] == "committed"
        else _rollback_prepared_restore(journal_path, journal)
    )
    return {
        "schema_version": RESTORE_RECOVERY_SCHEMA,
        "status": "recovered",
        "action": action,
        "transaction_id": journal["transaction_id"],
        "journal": str(journal_path),
        "journal_removed": not journal_path.exists(),
        "pending_journal_reconciliation": pending_reconciliation,
    }


def _commit_staged_restore(journal_path: Path) -> None:
    journal = _read_restore_journal(journal_path)
    entries = journal["entries"]
    try:
        for entry in entries:
            target = Path(entry["target"])
            staged = Path(entry["staged"])
            prior = Path(entry["previous"])
            if entry["original_present"]:
                os.replace(target, prior)
                _fsync_directory(target.parent)
                _restore_checkpoint(
                    f"prepared_{entry['kind']}_previous_renamed",
                    journal_path,
                )
            os.replace(staged, target)
            _fsync_directory(target.parent)
            _restore_checkpoint(
                f"prepared_{entry['kind']}_target_installed",
                journal_path,
            )
        committed = {**journal, "status": "committed", "committed_at_unix": int(time.time())}
        _atomic_private_json(journal_path, committed)
        _restore_checkpoint("committed_journal_persisted", journal_path)
    except Exception:
        recover_interrupted_restore(journal_path)
        raise
    recover_interrupted_restore(journal_path)


def _build_restore_journal(
    *,
    transaction_id: str,
    backup_dir: Path,
    backup_manifest_sha256: str,
    replacements: list[tuple[str, Path, Path]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for kind, target, staged in replacements:
        previous = target.with_name(f".{target.name}.restore-{transaction_id}.previous")
        original_present = _path_exists(target)
        entries.append(
            {
                "kind": kind,
                "target": str(target),
                "staged": str(staged),
                "previous": str(previous),
                "original_present": original_present,
                "original_identity": _path_identity(target) if original_present else None,
                "staged_identity": _path_identity(staged),
            }
        )
    return {
        "schema_version": RESTORE_JOURNAL_SCHEMA,
        "transaction_id": transaction_id,
        "status": "prepared",
        "prepared_at_unix": int(time.time()),
        "committed_at_unix": None,
        "backup_dir": str(backup_dir),
        "backup_manifest_sha256": backup_manifest_sha256,
        "entries": entries,
        "recovery_policy": "rollback_prepared_finalize_committed",
    }


def _read_restore_journal(
    journal_path: Path,
    *,
    expected_journal_path: Path | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"restore journal is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("restore journal root must be an object")
    expected_keys = {
        "schema_version",
        "transaction_id",
        "status",
        "prepared_at_unix",
        "committed_at_unix",
        "backup_dir",
        "backup_manifest_sha256",
        "entries",
        "recovery_policy",
    }
    if set(payload) != expected_keys:
        raise ValueError("restore journal keys do not match the supported schema")
    if payload.get("schema_version") != RESTORE_JOURNAL_SCHEMA:
        raise ValueError("unsupported restore journal schema")
    transaction_id = payload.get("transaction_id")
    if (
        not isinstance(transaction_id, str)
        or len(transaction_id) != 32
        or any(character not in "0123456789abcdef" for character in transaction_id)
    ):
        raise ValueError("restore journal transaction_id is invalid")
    if payload.get("status") not in {"prepared", "committed"}:
        raise ValueError("restore journal status is invalid")
    if payload.get("recovery_policy") != "rollback_prepared_finalize_committed":
        raise ValueError("restore journal recovery policy is invalid")
    if not isinstance(payload.get("prepared_at_unix"), int):
        raise ValueError("restore journal prepared_at_unix is invalid")
    if payload["status"] == "prepared" and payload.get("committed_at_unix") is not None:
        raise ValueError("prepared restore journal must not have committed_at_unix")
    if payload["status"] == "committed" and not isinstance(payload.get("committed_at_unix"), int):
        raise ValueError("committed restore journal must have committed_at_unix")
    backup_dir = Path(str(payload.get("backup_dir") or ""))
    if not backup_dir.is_absolute():
        raise ValueError("restore journal backup_dir must be absolute")
    digest = payload.get("backup_manifest_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("restore journal backup manifest digest is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) not in {2, 3}:
        raise ValueError("restore journal must contain database, artifact, and optional knowledge entries")
    expected_kinds = ["database", "artifacts"] + (["knowledge_updates"] if len(entries) == 3 else [])
    for entry, expected_kind in zip(entries, expected_kinds, strict=True):
        _validate_restore_journal_entry(entry, expected_kind, transaction_id)
    bound_journal_path = restore_journal_path(Path(entries[0]["target"]))
    if (expected_journal_path or journal_path) != bound_journal_path:
        raise ValueError("restore journal path is not bound to its database target")
    return payload


def _validate_restore_journal_entry(entry: Any, kind: str, transaction_id: str) -> None:
    if not isinstance(entry, dict):
        raise ValueError("restore journal entry must be an object")
    expected_keys = {
        "kind",
        "target",
        "staged",
        "previous",
        "original_present",
        "original_identity",
        "staged_identity",
    }
    if set(entry) != expected_keys or entry.get("kind") != kind:
        raise ValueError("restore journal entry keys or order are invalid")
    target = Path(str(entry.get("target") or ""))
    staged = Path(str(entry.get("staged") or ""))
    previous = Path(str(entry.get("previous") or ""))
    if not target.is_absolute() or not staged.is_absolute() or not previous.is_absolute():
        raise ValueError("restore journal paths must be absolute")
    if staged != target.with_name(f".{target.name}.restore-{transaction_id}.stage"):
        raise ValueError("restore journal staged path is not bound to its target")
    if previous != target.with_name(f".{target.name}.restore-{transaction_id}.previous"):
        raise ValueError("restore journal previous path is not bound to its target")
    if not isinstance(entry.get("original_present"), bool):
        raise ValueError("restore journal original_present must be boolean")
    if entry["original_present"] != (entry.get("original_identity") is not None):
        raise ValueError("restore journal original identity does not match original_present")
    if entry.get("original_identity") is not None:
        _validate_path_identity(entry["original_identity"])
    _validate_path_identity(entry.get("staged_identity"))


def _rollback_prepared_restore(journal_path: Path, journal: dict[str, Any]) -> str:
    for entry in reversed(journal["entries"]):
        target = Path(entry["target"])
        staged = Path(entry["staged"])
        previous = Path(entry["previous"])
        if previous.is_symlink() or staged.is_symlink():
            raise ValueError("restore recovery refuses symlink transaction paths")
        if entry["original_present"]:
            if _path_exists(previous):
                if _path_identity(previous) != entry["original_identity"]:
                    raise ValueError(f"restore previous identity mismatch: {previous}")
                if _path_exists(target):
                    _remove_only_if_identity(target, entry["staged_identity"])
                os.replace(previous, target)
                _fsync_directory(target.parent)
            elif not _path_exists(target):
                raise RuntimeError(f"restore cannot locate original or previous target: {target}")
            elif _path_identity(target) != entry["original_identity"]:
                raise RuntimeError(f"restore target is not the recorded original: {target}")
        elif _path_exists(target):
            _remove_only_if_identity(target, entry["staged_identity"])
            _fsync_directory(target.parent)
        if _path_exists(staged):
            _remove_only_if_identity(staged, entry["staged_identity"])
            _fsync_directory(staged.parent)
    _remove_journal(journal_path)
    return "rolled_back_prepared_restore"


def _finalize_committed_restore(journal_path: Path, journal: dict[str, Any]) -> str:
    for entry in journal["entries"]:
        target = Path(entry["target"])
        staged = Path(entry["staged"])
        previous = Path(entry["previous"])
        if not _path_exists(target) or _path_identity(target) != entry["staged_identity"]:
            raise RuntimeError(f"committed restore target identity mismatch: {target}")
        if _path_exists(previous):
            if not entry["original_present"] or _path_identity(previous) != entry["original_identity"]:
                raise ValueError(f"restore previous identity mismatch: {previous}")
            _remove_path(previous)
            _fsync_directory(previous.parent)
            _restore_checkpoint(
                f"committed_{entry['kind']}_previous_removed",
                journal_path,
            )
        if _path_exists(staged):
            _remove_only_if_identity(staged, entry["staged_identity"])
            _fsync_directory(staged.parent)
    _restore_checkpoint("committed_cleanup_complete", journal_path)
    _remove_journal(journal_path)
    _restore_checkpoint("journal_removed", journal_path)
    return "finalized_committed_restore"


def _path_identity(path: Path) -> dict[str, Any]:
    stat_result = path.lstat()
    if path.is_symlink():
        raise ValueError(f"restore transaction paths must not be symlinks: {path}")
    kind = "directory" if path.is_dir() else "file"
    return {
        "device": stat_result.st_dev,
        "inode": stat_result.st_ino,
        "kind": kind,
        "content_sha256": (
            _directory_content_sha256(path)
            if kind == "directory"
            else _sha256(path)
        ),
    }


def _validate_path_identity(identity: Any) -> None:
    if (
        not isinstance(identity, dict)
        or set(identity) != {"device", "inode", "kind", "content_sha256"}
        or not isinstance(identity.get("device"), int)
        or not isinstance(identity.get("inode"), int)
        or identity.get("kind") not in {"file", "directory"}
        or not isinstance(identity.get("content_sha256"), str)
        or len(identity["content_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in identity["content_sha256"])
    ):
        raise ValueError("restore journal path identity is invalid")


def _remove_only_if_identity(path: Path, expected: dict[str, Any]) -> None:
    if path.is_symlink() or _path_identity(path) != expected:
        raise ValueError(f"restore recovery refuses to remove an unrecognized path: {path}")
    _remove_path(path)


def _directory_content_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"open-agronomy-agent-directory-content-v1\0")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            raise ValueError(f"restore transaction trees must not contain symlinks: {path}")
        if path.is_dir():
            kind = b"directory"
            content_digest = b""
        elif path.is_file():
            kind = b"file"
            content_digest = _sha256(path).encode("ascii")
        else:
            raise ValueError(f"restore transaction trees contain an unsupported path: {path}")
        for field in (kind, relative, content_digest):
            digest.update(len(field).to_bytes(8, "big"))
            digest.update(field)
    return digest.hexdigest()


def _fsync_restore_staging(staged_paths: list[Path]) -> None:
    for path in staged_paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    _fsync_file(child)
            for child in sorted(
                (child for child in path.rglob("*") if child.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                _fsync_directory(child)
            _fsync_directory(path)
        else:
            _fsync_file(path)
        _fsync_directory(path.parent)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.pending")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _restore_checkpoint(
            f"{payload.get('status', 'unknown')}_journal_pending_fsynced",
            path,
        )
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _remove_journal(path: Path) -> None:
    path.unlink()
    _restore_checkpoint("journal_unlinked", path)
    _fsync_directory(path.parent)


def _restore_checkpoint(name: str, journal_path: Path) -> None:
    """No-op production hook used by subprocess fault-injection drills."""


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if not _path_exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source))
    try:
        target_conn = sqlite3.connect(str(target))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()
    target.chmod(0o600)


def _copy_artifacts(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for file_path in sorted(path for path in source.rglob("*") if path.is_file()):
        if file_path.is_symlink():
            raise ValueError(f"artifact symlinks are not supported in backups: {file_path}")
        relative_path = file_path.relative_to(source)
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination)
        destination.chmod(0o600)


def _make_tree_private(root: Path) -> None:
    root.chmod(0o700)
    for path in root.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)


def _restore_knowledge_update_permissions(root: Path) -> None:
    _make_tree_private(root)
    releases = root / "releases"
    if not releases.is_dir():
        return
    for release in releases.iterdir():
        if not release.is_dir():
            continue
        for path in sorted(release.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        release.chmod(0o555)


def _manifest_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return [
        _file_entry(file_path, name=str(file_path.relative_to(root)))
        for file_path in sorted(path for path in root.rglob("*") if path.is_file())
    ]


def _validate_exact_backup_contents(
    backup_dir: Path,
    manifest: dict[str, Any],
) -> None:
    paths = list(backup_dir.rglob("*"))
    for path in paths:
        if path.is_symlink():
            raise ValueError(
                "backup symlinks are not supported: "
                f"{path.relative_to(backup_dir)}"
            )
    expected_files = {
        MANIFEST_NAME,
        MANIFEST_DIGEST_NAME,
        DB_SNAPSHOT_NAME,
        *(
            f"{ARTIFACTS_DIR_NAME}/{_safe_relative(entry['path']).as_posix()}"
            for entry in manifest.get("artifacts", [])
        ),
        *(
            f"{KNOWLEDGE_UPDATES_DIR_NAME}/{_safe_relative(entry['path']).as_posix()}"
            for entry in manifest.get("knowledge_updates", [])
        ),
    }
    expected_directories = {ARTIFACTS_DIR_NAME}
    if "knowledge_updates" in manifest:
        expected_directories.add(KNOWLEDGE_UPDATES_DIR_NAME)
    for relative_name in expected_files:
        parent = Path(relative_name).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    actual_files = {
        path.relative_to(backup_dir).as_posix()
        for path in paths
        if path.is_file()
    }
    actual_directories = {
        path.relative_to(backup_dir).as_posix()
        for path in paths
        if path.is_dir()
    }
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ValueError(
            "backup contents are not exactly manifest-bound; "
            f"unexpected_files={sorted(actual_files - expected_files)}; "
            f"missing_files={sorted(expected_files - actual_files)}; "
            f"unexpected_directories={sorted(actual_directories - expected_directories)}; "
            f"missing_directories={sorted(expected_directories - actual_directories)}"
        )


def _file_entry(path: Path, *, name: str) -> dict[str, Any]:
    return {
        "path": name,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _assert_file_entry(path: Path, entry: dict[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"backup file missing: {path}")
    actual = _file_entry(path, name=entry["path"])
    if actual["size_bytes"] != entry["size_bytes"] or actual["sha256"] != entry["sha256"]:
        raise ValueError(f"backup checksum mismatch: {entry['path']}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_backup_id(value: str) -> str:
    cleaned = "".join(ch for ch in value.strip() if ch.isalnum() or ch in {"-", "_", "."}).strip(".")
    if not cleaned:
        raise ValueError("backup id is required")
    return cleaned


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path in backup manifest: {value}")
    return path
