from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def minimized_path_reference(value: str | Path) -> str:
    """Return portable lineage without exposing an external absolute path."""
    target = repo_path(value).resolve()
    try:
        return target.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return f"<external>/{target.name}"
