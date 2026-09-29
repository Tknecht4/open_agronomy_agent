from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3

import pytest
import agronomy_agent.server.storage.backup as backup_module

from agronomy_agent.server.storage.backup import (
    assert_no_pending_restore,
    create_backup,
    recover_interrupted_restore,
    restore_backup,
    restore_journal_path,
)
from agronomy_agent.server.storage.object_store import LocalObjectStore


def test_database_startup_allows_absent_restore_journal(tmp_path: Path) -> None:
    assert_no_pending_restore(tmp_path / "open-agronomy.sqlite3")


def test_database_startup_blocks_with_supported_recovery_guidance(
    tmp_path: Path,
) -> None:
    database = tmp_path / "open-agronomy.sqlite3"
    journal = restore_journal_path(database)
    journal.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError) as error:
        assert_no_pending_restore(database)

    message = str(error.value)
    assert str(journal) in message
    assert "recover_interrupted_restore" in message
    assert "phase4_backup.py" not in message


@pytest.mark.parametrize("relocated", [False, True])
def test_restore_rebases_attachment_reference_for_local_store(
    tmp_path: Path, relocated: bool,
) -> None:
    original_root = tmp_path / "original-artifacts"
    original_store = LocalObjectStore(original_root)
    content = b"synthetic private attachment"
    original_uri = original_store.put_bytes("phase4/attachments/workspace/attachment.txt", content).uri
    original_db = tmp_path / "original.sqlite3"
    with sqlite3.connect(original_db) as connection:
        connection.execute(
            "CREATE TABLE phase4_attachments (id TEXT, storage_uri TEXT, "
            "size_bytes INTEGER, sha256 TEXT, deleted_at TEXT)"
        )
        connection.execute(
            "INSERT INTO phase4_attachments VALUES (?, ?, ?, ?, NULL)",
            ("attachment", original_uri, len(content), hashlib.sha256(content).hexdigest()),
        )
    backup = create_backup(
        db_path=original_db, artifact_root=original_root, backup_root=tmp_path / "backups",
    )
    manifest_bytes = backup.manifest_path.read_bytes()
    snapshot_bytes = (backup.backup_dir / "cockpit.sqlite3").read_bytes()
    target_root = tmp_path / "new-artifacts" if relocated else original_root
    target_db = tmp_path / "restored.sqlite3"
    receipt = restore_backup(
        backup_dir=backup.backup_dir, target_db_path=target_db,
        target_artifact_root=target_root, overwrite=not relocated,
    )
    with sqlite3.connect(target_db) as connection:
        restored_uri = connection.execute(
            "SELECT storage_uri FROM phase4_attachments WHERE id = 'attachment'"
        ).fetchone()[0]
    restored_store = LocalObjectStore(target_root)
    assert restored_store.get_bytes(restored_uri) == content
    assert restored_store.delete_uri(restored_uri) is True  # attachment deletion consumer
    assert restored_uri == str(target_root / "phase4/attachments/workspace/attachment.txt")
    assert receipt["restore_transform"]["rewritten"]["attachments"] == int(relocated)
    assert receipt["restore_transform"]["staged_database_sha256"] == hashlib.sha256(
        target_db.read_bytes()
    ).hexdigest()
    assert backup.manifest_path.read_bytes() == manifest_bytes
    assert (backup.backup_dir / "cockpit.sqlite3").read_bytes() == snapshot_bytes


def test_backup_rejects_attachment_reference_outside_source_root(tmp_path: Path) -> None:
    source_root = tmp_path / "artifacts"
    LocalObjectStore(source_root)
    db = tmp_path / "source.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE phase4_attachments (id TEXT, storage_uri TEXT, "
            "size_bytes INTEGER, sha256 TEXT, deleted_at TEXT)"
        )
        connection.execute(
            "INSERT INTO phase4_attachments VALUES ('a', ?, 1, ?, NULL)",
            (str(tmp_path / "unrelated.txt"), hashlib.sha256(b"x").hexdigest()),
        )
    backup_root = tmp_path / "backups"
    with pytest.raises(ValueError, match="outside backup source root"):
        create_backup(db_path=db, artifact_root=source_root, backup_root=backup_root)
    assert list(backup_root.iterdir()) == []


def test_restore_rebases_legacy_absolute_export_references(tmp_path: Path) -> None:
    source_root = tmp_path / "artifacts"
    source_store = LocalObjectStore(source_root)
    uri = source_store.put_bytes("phase4/export/report.json", b"{}").uri
    db = tmp_path / "source.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE phase4_exports (id TEXT, storage_uri TEXT, metadata TEXT)")
        connection.execute(
            "INSERT INTO phase4_exports VALUES (?, ?, ?)",
            ("export", str(Path(uri).parent), json.dumps({
                "files": {"report.json": uri},
                "file_manifest": {"report.json": {
                    "size_bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest(),
                }},
            })),
        )
    backup = create_backup(db_path=db, artifact_root=source_root, backup_root=tmp_path / "backups")
    target_root = tmp_path / "restored-artifacts"
    target_db = tmp_path / "restored.sqlite3"
    receipt = restore_backup(
        backup_dir=backup.backup_dir, target_db_path=target_db, target_artifact_root=target_root,
    )
    with sqlite3.connect(target_db) as connection:
        directory, metadata = connection.execute(
            "SELECT storage_uri, metadata FROM phase4_exports WHERE id = 'export'"
        ).fetchone()
    assert directory == str(target_root / "phase4/export")
    assert LocalObjectStore(target_root).get_bytes(json.loads(metadata)["files"]["report.json"]) == b"{}"
    assert receipt["restore_transform"]["rewritten"] == {
        "attachments": 0, "exports": 1, "export_files": 1,
    }


def test_recovery_finalizes_rebased_database_after_commit_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "artifacts"
    content = b"attachment"
    uri = LocalObjectStore(source_root).put_bytes("phase4/a.txt", content).uri
    db = tmp_path / "source.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE phase4_attachments (id TEXT, storage_uri TEXT, "
            "size_bytes INTEGER, sha256 TEXT, deleted_at TEXT)"
        )
        connection.execute(
            "INSERT INTO phase4_attachments VALUES ('a', ?, ?, ?, NULL)",
            (uri, len(content), hashlib.sha256(content).hexdigest()),
        )
    archive = create_backup(db_path=db, artifact_root=source_root, backup_root=tmp_path / "backups")
    target_db = tmp_path / "restored.sqlite3"
    target_root = tmp_path / "restored-artifacts"

    def interrupt(name: str, _journal: Path) -> None:
        if name == "committed_journal_persisted":
            raise SystemExit("synthetic interruption after commit")

    monkeypatch.setattr(backup_module, "_restore_checkpoint", interrupt)
    with pytest.raises(SystemExit, match="synthetic interruption"):
        restore_backup(
            backup_dir=archive.backup_dir, target_db_path=target_db,
            target_artifact_root=target_root,
        )
    monkeypatch.setattr(backup_module, "_restore_checkpoint", lambda *_: None)
    recovered = recover_interrupted_restore(restore_journal_path(target_db))
    assert recovered["action"] == "finalized_committed_restore"
    with sqlite3.connect(target_db) as connection:
        restored_uri = connection.execute("SELECT storage_uri FROM phase4_attachments").fetchone()[0]
    assert LocalObjectStore(target_root).get_bytes(restored_uri) == content


def test_recovery_rolls_back_rebased_database_before_artifact_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def attachment_db(path: Path, uri: str, content: bytes) -> None:
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE phase4_attachments (id TEXT, storage_uri TEXT, "
                "size_bytes INTEGER, sha256 TEXT, deleted_at TEXT)"
            )
            connection.execute(
                "INSERT INTO phase4_attachments VALUES ('a', ?, ?, ?, NULL)",
                (uri, len(content), hashlib.sha256(content).hexdigest()),
            )

    source_root = tmp_path / "source-artifacts"
    new_content = b"new generation"
    new_uri = LocalObjectStore(source_root).put_bytes("phase4/a.txt", new_content).uri
    source_db = tmp_path / "source.sqlite3"
    attachment_db(source_db, new_uri, new_content)
    archive = create_backup(
        db_path=source_db, artifact_root=source_root, backup_root=tmp_path / "backups",
    )
    manifest_bytes = archive.manifest_path.read_bytes()
    snapshot_bytes = (archive.backup_dir / "cockpit.sqlite3").read_bytes()

    target_root = tmp_path / "target-artifacts"
    old_content = b"prior generation"
    old_uri = LocalObjectStore(target_root).put_bytes("phase4/a.txt", old_content).uri
    target_db = tmp_path / "target.sqlite3"
    attachment_db(target_db, old_uri, old_content)
    prior_db_bytes = target_db.read_bytes()

    def interrupt(name: str, _journal: Path) -> None:
        if name == "prepared_database_target_installed":
            raise SystemExit("synthetic interruption before artifact install")

    monkeypatch.setattr(backup_module, "_restore_checkpoint", interrupt)
    with pytest.raises(SystemExit, match="synthetic interruption"):
        restore_backup(
            backup_dir=archive.backup_dir, target_db_path=target_db,
            target_artifact_root=target_root, overwrite=True,
        )
    with sqlite3.connect(target_db) as connection:
        interrupted_uri, interrupted_sha = connection.execute(
            "SELECT storage_uri, sha256 FROM phase4_attachments"
        ).fetchone()
    assert interrupted_uri == str(target_root / "phase4/a.txt")
    assert interrupted_sha == hashlib.sha256(new_content).hexdigest()
    assert target_db.read_bytes() != prior_db_bytes
    assert (target_root / "phase4/a.txt").read_bytes() == old_content
    assert restore_journal_path(target_db).is_file()
    monkeypatch.setattr(backup_module, "_restore_checkpoint", lambda *_: None)
    recovered = recover_interrupted_restore(restore_journal_path(target_db))
    assert recovered["action"] == "rolled_back_prepared_restore"
    assert target_db.read_bytes() == prior_db_bytes
    with sqlite3.connect(target_db) as connection:
        restored_uri = connection.execute("SELECT storage_uri FROM phase4_attachments").fetchone()[0]
    restored_store = LocalObjectStore(target_root)
    assert restored_uri == old_uri
    assert restored_store.get_bytes(restored_uri) == old_content
    assert restored_store.delete_uri(restored_uri) is True
    assert archive.manifest_path.read_bytes() == manifest_bytes
    assert (archive.backup_dir / "cockpit.sqlite3").read_bytes() == snapshot_bytes


@pytest.mark.parametrize("during_copy", ["deleted", "changed"])
def test_backup_refuses_snapshot_with_missing_or_changed_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, during_copy: str,
) -> None:
    source_root = tmp_path / "artifacts"
    content = b"original attachment"
    uri = LocalObjectStore(source_root).put_bytes("phase4/a.txt", content).uri
    db = tmp_path / "source.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE phase4_attachments (id TEXT, storage_uri TEXT, "
            "size_bytes INTEGER, sha256 TEXT, deleted_at TEXT)"
        )
        connection.execute(
            "INSERT INTO phase4_attachments VALUES ('a', ?, ?, ?, NULL)",
            (uri, len(content), hashlib.sha256(content).hexdigest()),
        )
    original_copy = backup_module._copy_artifacts

    def concurrent_change(source: Path, destination: Path) -> None:
        if during_copy == "deleted":
            Path(uri).unlink()
        original_copy(source, destination)
        if during_copy == "changed":
            (destination / "phase4/a.txt").write_bytes(b"different attachment")

    monkeypatch.setattr(backup_module, "_copy_artifacts", concurrent_change)
    backup_root = tmp_path / "backups"
    with pytest.raises(ValueError, match="missing from backup|checksum differs"):
        create_backup(db_path=db, artifact_root=source_root, backup_root=backup_root)
    assert list(backup_root.iterdir()) == []


def test_backup_refuses_changed_export_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "artifacts"
    uri = LocalObjectStore(source_root).put_bytes("phase4/export/report.json", b"{}").uri
    db = tmp_path / "source.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE phase4_exports (id TEXT, storage_uri TEXT, metadata TEXT)")
        connection.execute(
            "INSERT INTO phase4_exports VALUES (?, ?, ?)",
            ("export", str(Path(uri).parent), json.dumps({
                "files": {"report.json": uri},
                "file_manifest": {"report.json": {
                    "size_bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest(),
                }},
            })),
        )
    original_copy = backup_module._copy_artifacts

    def changed_copy(source: Path, destination: Path) -> None:
        original_copy(source, destination)
        (destination / "phase4/export/report.json").write_bytes(b"[]")

    monkeypatch.setattr(backup_module, "_copy_artifacts", changed_copy)
    backup_root = tmp_path / "backups"
    with pytest.raises(ValueError, match="export file size or checksum differs"):
        create_backup(db_path=db, artifact_root=source_root, backup_root=backup_root)
    assert list(backup_root.iterdir()) == []
