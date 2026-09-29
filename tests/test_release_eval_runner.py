import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from agronomy_agent.release_eval_runner import (
    _append,
    _bind_artifacts,
    _command,
    _effective_yaml,
    _instrument_controls,
    _ledger,
    _seal_record,
    _subprocess_cell,
    load_retained_report,
    retention_manifest,
    verify_retention,
)
from agronomy_agent.release_evaluation import digest, write_new_json


def test_instrument_proves_unit_negation_and_empty_rubric_controls():
    result = _instrument_controls()
    assert result["status"] == "pass"
    assert result["metrics"] == {"controls": 7, "failed": 0}


def test_ledger_rejects_raw_artifact_tamper_and_duplicate_records(tmp_path):
    directory = tmp_path / "cells/a"
    directory.mkdir(parents=True)
    raw = directory / "answer.json"
    raw.write_text('"observed"')
    row = {"observation_id": "a", "status": "completed"}
    _bind_artifacts(row, directory, tmp_path)
    row = _seal_record(row, "plan")
    ledger = tmp_path / "observations.jsonl"
    _append(ledger, row)
    assert _ledger(ledger, plan_sha256="plan") == [row]
    raw.write_text('"changed"')
    with pytest.raises(ValueError, match="artifact"):
        _ledger(ledger, plan_sha256="plan")
    raw.write_text('"observed"')
    _append(ledger, row)
    with pytest.raises(ValueError, match="duplicate"):
        _ledger(ledger, plan_sha256="plan")


def test_ledger_rejects_record_tamper_or_plan_drift(tmp_path):
    path = tmp_path / "rows.jsonl"
    row = _seal_record({"component": "instrument", "status": "pass"}, "plan")
    _append(path, row)
    with pytest.raises(ValueError, match="binding"):
        _ledger(path, plan_sha256="different")
    row["status"] = "blocked"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="binding"):
        _ledger(path, plan_sha256="plan")


def test_interrupted_cell_is_retained_without_automatic_retry(tmp_path):
    cell = tmp_path / "cell"
    cell.mkdir()
    (cell / "partial.log").write_text("interrupted")
    result = _subprocess_cell({"directory": str(cell)}, timeout=1)
    assert result["error_type"] == "InterruptedAttempt"
    assert (cell / "partial.log").read_text() == "interrupted"
    assert not (cell / "spec.json").exists()


def test_effective_config_drift_cannot_resume(tmp_path):
    path = tmp_path / "model.yaml"
    _effective_yaml(path, {"seed": 42})
    _effective_yaml(path, {"seed": 42})
    with pytest.raises(ValueError, match="config"):
        _effective_yaml(path, {"seed": 43})


def test_retention_detects_nested_receipt_tamper_and_symlinks(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "retention.json"
    target.write_text("raw nested evidence")
    write_new_json(tmp_path / "retention.json", retention_manifest(tmp_path))
    verify_retention(tmp_path)
    target.write_text("tamper")
    with pytest.raises(ValueError, match="hash"):
        verify_retention(tmp_path)
    (nested / "link").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        retention_manifest(tmp_path)


def test_unretained_reference_is_rejected(tmp_path):
    write_new_json(tmp_path / "report.json", {"status": "engineering_pass"})
    with pytest.raises(FileNotFoundError):
        load_retained_report(tmp_path / "report.json")


def test_timeout_contains_descendant_and_retains_log(tmp_path):
    marker = tmp_path / "terminated"
    descendant = "import signal,sys,time; from pathlib import Path; signal.signal(signal.SIGTERM,lambda *_:(Path(sys.argv[1]).write_text('terminated'),sys.exit(0))); time.sleep(30)"
    script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]]); print('started',flush=True); time.sleep(30)"
    result = _command(
        [sys.executable, "-c", script, str(marker), descendant],
        cwd=tmp_path,
        output=tmp_path / "log",
        timeout=0.8,
    )
    assert result == (124, "timeout")
    assert "started" in (tmp_path / "log").read_text()
    for _ in range(20):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.read_text() == "terminated"


def test_command_excludes_inherited_private_overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "enabled")
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", "SECRET")
    monkeypatch.setenv("AGRONOMY_AGENT_SYSTEM_PROMPT", "CONTAMINATED")
    result = _command(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['AGRONOMY_AGENT_PRIVATE_KNOWLEDGE']); print(os.environ.get('AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST'))",
        ],
        cwd=tmp_path,
        output=tmp_path / "log",
        timeout=3,
    )
    assert result == (0, "completed")
    assert (tmp_path / "log").read_text() == "disabled\nNone\n"
    assert _command(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('AGRONOMY_AGENT_SYSTEM_PROMPT')); print(os.environ['AGRONOMY_AGENT_MODEL_BACKEND']); print(os.environ['HF_HUB_OFFLINE'])",
        ],
        cwd=tmp_path,
        output=tmp_path / "runtime-log",
        timeout=3,
    ) == (0, "completed")
    assert (tmp_path / "runtime-log").read_text() == "None\nmlx\n1\n"


def _tiny_runner(monkeypatch):
    import agronomy_agent.release_eval_runner as runner
    from agronomy_agent.release_evaluation import (
        DEFAULT_REGISTRY,
        build_plan,
        load_registry,
    )

    plan = build_plan(load_registry(), profile="ci", run_id="resume-test")
    plan["cases"] = plan["cases"][:1]
    plan["matrix"] = plan["matrix"][:1]
    plan["counts"] = {
        "cases": 1,
        "observations": 1,
        "families": 1,
        "lanes": {"harness": 1},
    }
    monkeypatch.setattr(runner, "build_plan", lambda *_args, **_kwargs: plan.copy())
    monkeypatch.setattr(
        runner,
        "environment_identity",
        lambda: {"performance_environment_sha256": "test"},
    )
    monkeypatch.setattr(runner, "source_identity", lambda: plan["source"])
    return runner, DEFAULT_REGISTRY


def _fake_worker(spec, *, timeout):
    directory = Path(spec["directory"])
    directory.mkdir(parents=True)
    (directory / "raw.json").write_text('{"observed":true}')
    if spec["kind"] == "product":
        return {
            "status": "completed",
            "checks": [{"id": "mechanical", "passed": True}],
            "turns": [{"answer": "135.95 kg/ha", "elapsed_ms": 1}],
            "unknown": [],
        }
    return {"component": spec["kind"], "status": "pass", "metrics": {}}


def test_complete_resume_reuses_exact_retained_run_without_new_execution(
    tmp_path, monkeypatch
):
    runner, registry = _tiny_runner(monkeypatch)
    monkeypatch.setattr(runner, "_subprocess_cell", _fake_worker)
    args = dict(
        registry_path=registry, profile="ci", output_dir=tmp_path, run_id="resume-test"
    )
    result = runner.run_suite(**args)
    assert result["status"] == "engineering_pass"
    monkeypatch.setattr(
        runner,
        "_subprocess_cell",
        lambda *_a, **_k: pytest.fail("completed resume launched inference"),
    )
    assert runner.run_suite(**args, resume=True) == result
    raw = next((tmp_path / "cells").rglob("raw.json"))
    raw.write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        runner.run_suite(**args, resume=True)


def test_interrupted_resume_preserves_deadline_and_failed_denominators(
    tmp_path, monkeypatch
):
    runner, registry = _tiny_runner(monkeypatch)
    calls = []

    def interrupt(spec, *, timeout):
        calls.append(spec["kind"])
        if len(calls) == 2:
            raise KeyboardInterrupt("simulated owner interruption")
        return _fake_worker(spec, timeout=timeout)

    monkeypatch.setattr(runner, "_subprocess_cell", interrupt)
    args = dict(
        registry_path=registry, profile="ci", output_dir=tmp_path, run_id="resume-test"
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run_suite(**args)
    clock = json.loads((tmp_path / "run-clock.json").read_text())
    clock["started_unix_seconds"] = time.time() - 20000
    (tmp_path / "run-clock.json").write_text(json.dumps(clock))
    monkeypatch.setattr(
        runner,
        "_subprocess_cell",
        lambda *_a, **_k: pytest.fail("expired resume launched work"),
    )
    report = runner.run_suite(**args, resume=True)
    assert report["status"] == "blocked"
    assert report["counts"]["observed"] == 1
    assert report["counts"]["failed"] == 1
    assert len(report["failures"]["components"]) == 5
    assert json.loads((tmp_path / "run-clock.json").read_text()) == clock
