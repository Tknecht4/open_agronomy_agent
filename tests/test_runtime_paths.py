from __future__ import annotations

from pathlib import Path

import pytest

from agronomy_agent.paths import _runtime_root


def test_runtime_root_defaults_to_source_checkout() -> None:
    assert (_runtime_root(None) / "configs/runtime_profiles.json").is_file()


def test_runtime_root_accepts_packaged_resource_tree(tmp_path: Path) -> None:
    registry = tmp_path / "configs/runtime_profiles.json"
    registry.parent.mkdir()
    registry.write_text("{}", encoding="utf-8")

    assert _runtime_root(str(tmp_path)) == tmp_path.resolve()


@pytest.mark.parametrize("override", ["relative/runtime", "/path/that/is/not/present"])
def test_runtime_root_rejects_missing_or_relative_packaged_root(override: str) -> None:
    with pytest.raises((OSError, ValueError)):
        _runtime_root(override)


def test_runtime_root_rejects_tree_without_registry(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="runtime profile registry"):
        _runtime_root(str(tmp_path))
