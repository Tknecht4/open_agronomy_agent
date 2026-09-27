from __future__ import annotations

from pathlib import Path

import pytest

from agronomy_agent.server.storage.backup import (
    assert_no_pending_restore,
    restore_journal_path,
)


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
