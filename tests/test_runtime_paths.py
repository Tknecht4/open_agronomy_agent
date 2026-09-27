from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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


def test_implementation_binding_uses_relocated_runtime_root(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    registry = runtime / "configs/runtime_profiles.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{}", encoding="utf-8")
    source = runtime / "src/agronomy_agent/agent.py"
    source.parent.mkdir(parents=True)
    source.write_text("relocated source receipt\n", encoding="utf-8")
    repository = Path(__file__).resolve().parents[1]
    command = [
        sys.executable, "-c",
        "import json; from agronomy_agent.security_evidence import build_implementation_binding; "
        "print(json.dumps(build_implementation_binding(['src/agronomy_agent/agent.py'])))",
    ]
    completed = subprocess.run(
        command,
        env={
            **os.environ,
            "AGRONOMY_AGENT_RUNTIME_ROOT": str(runtime),
            "PYTHONPATH": str(repository / "src"),
        },
        check=True, capture_output=True, text=True,
    )
    row = json.loads(completed.stdout)["files"][0]
    assert row == {
        "path": "src/agronomy_agent/agent.py",
        "bytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
