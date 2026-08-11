from __future__ import annotations

from pathlib import Path

import pytest

from agronomy_agent.security_evidence import (
    IMPLEMENTATION_BINDING_SCHEMA,
    build_implementation_binding,
    validate_implementation_binding,
)


def test_implementation_binding_is_exact_and_current(tmp_path: Path) -> None:
    (tmp_path / "control.py").write_text("CONTROL = 1\n", encoding="utf-8")
    (tmp_path / "runtime.py").write_text("RUNTIME = 1\n", encoding="utf-8")

    binding = build_implementation_binding(
        ("runtime.py", "control.py"),
        root=tmp_path,
    )

    assert binding["schema_version"] == IMPLEMENTATION_BINDING_SCHEMA
    assert [row["path"] for row in binding["files"]] == [
        "control.py",
        "runtime.py",
    ]
    validate_implementation_binding(
        binding,
        expected_paths=("control.py", "runtime.py"),
        root=tmp_path,
    )


def test_implementation_binding_rejects_stale_or_wrong_file_set(
    tmp_path: Path,
) -> None:
    (tmp_path / "control.py").write_text("CONTROL = 1\n", encoding="utf-8")
    binding = build_implementation_binding(("control.py",), root=tmp_path)

    (tmp_path / "control.py").write_text("CONTROL = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        validate_implementation_binding(
            binding,
            expected_paths=("control.py",),
            root=tmp_path,
        )

    (tmp_path / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file set"):
        validate_implementation_binding(
            binding,
            expected_paths=("control.py", "other.py"),
            root=tmp_path,
        )


def test_implementation_binding_rejects_symlink_and_path_escape(
    tmp_path: Path,
) -> None:
    (tmp_path / "control.py").write_text("CONTROL = 1\n", encoding="utf-8")
    (tmp_path / "link.py").symlink_to(tmp_path / "control.py")

    with pytest.raises(FileNotFoundError, match="regular file"):
        build_implementation_binding(("link.py",), root=tmp_path)
    with pytest.raises(ValueError, match="unsafe"):
        build_implementation_binding(("../outside.py",), root=tmp_path)
