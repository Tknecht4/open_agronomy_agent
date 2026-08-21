from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_open_agronomy_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_open_agronomy_benchmark_timeout_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_child_timeout_retains_log_and_typed_receipt(tmp_path: Path) -> None:
    module = _module()
    log = tmp_path / "runner.log"
    with pytest.raises(RuntimeError, match="timed out"):
        module._run(
            [sys.executable, "-c", "import time; print('partial', flush=True); time.sleep(5)"],
            log_path=log,
            environment=dict(os.environ),
            timeout_seconds=0.05,
        )
    receipt = json.loads((tmp_path / "runner.execution.json").read_text())
    assert receipt["status"] == "timed_out"
    assert receipt["partial_outputs_retained"] is True
    assert receipt["cancellation"] == "terminate_then_kill_after_10_seconds"
    assert "partial" in log.read_text()


def test_child_completion_receipt_is_content_addressed(tmp_path: Path) -> None:
    module = _module()
    receipt = module._run(
        [sys.executable, "-c", "print('ok')"],
        log_path=tmp_path / "runner.log",
        environment=dict(os.environ),
        timeout_seconds=5,
    )
    assert receipt["status"] == "complete"
    assert len(receipt["command_sha256"]) == 64
    assert receipt["return_code"] == 0
