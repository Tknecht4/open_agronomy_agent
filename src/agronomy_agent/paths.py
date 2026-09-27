from __future__ import annotations

import os
from pathlib import Path


def _runtime_root(override: str | None) -> Path:
    if override is None:
        return Path(__file__).resolve().parents[2]
    path = Path(override)
    if not path.is_absolute():
        raise ValueError("AGRONOMY_AGENT_RUNTIME_ROOT must be an absolute path")
    root = path.resolve(strict=True)
    if not root.is_dir() or not (root / "configs/runtime_profiles.json").is_file():
        raise ValueError(
            "AGRONOMY_AGENT_RUNTIME_ROOT must contain the runtime profile registry"
        )
    return root


REPO_ROOT = _runtime_root(os.environ.get("AGRONOMY_AGENT_RUNTIME_ROOT"))


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
