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
    _stop_owned_processes,
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


@pytest.mark.parametrize("leader_waits", [True, False])
def test_uncooperative_descendant_cannot_survive_leader_exit(tmp_path, leader_waits):
    heartbeat = tmp_path / "heartbeat"
    descendant = "import signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); f=open(sys.argv[1],'a');\nwhile True:\n f.write('alive\\n'); f.flush(); time.sleep(.03)"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]]); time.sleep(float(sys.argv[3]))"
    result = _command(
        [
            sys.executable,
            "-c",
            parent,
            str(heartbeat),
            descendant,
            "30" if leader_waits else ".3",
        ],
        cwd=tmp_path,
        output=tmp_path / "log",
        timeout=0.8,
    )
    assert result == ((124, "timeout") if leader_waits else (0, "completed"))
    observed = heartbeat.stat().st_size
    assert observed > 0
    time.sleep(0.15)
    assert heartbeat.stat().st_size == observed


def test_owner_cancellation_closes_its_worker(tmp_path, monkeypatch):
    original = subprocess.Popen.wait
    raised = False

    def cancel_once(child, timeout=None):
        nonlocal raised
        if not raised:
            raised = True
            raise KeyboardInterrupt("simulated owner cancellation")
        return original(child, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", cancel_once)
    with pytest.raises(KeyboardInterrupt):
        _command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            output=tmp_path / "log",
            timeout=3,
        )
    assert raised


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


def _order2_runner(tmp_path, monkeypatch):
    from test_release_evaluation import _controller_packet, _task_exposure
    runner, registry = _tiny_runner(monkeypatch)
    base = runner.build_plan()
    toy, _, _, _, _, inputs = _controller_packet(tmp_path)
    base.update(cases=toy["cases"], matrix=[{k: v for k, v in cell.items() if k not in {"model_id", "model_revision", "backend_id", "analysis_condition", "comparison_cohort", "task_input_sha256", "task_input_status"}} for cell in toy["matrix"]],
                counts={"cases": 2, "observations": 4, "families": 1, "lanes": {"harness": 2}})
    for cell in base["matrix"]:
        cell.update(lane="harness", scenario_family="synthetic_arithmetic")
    monkeypatch.setattr(runner, "build_plan", lambda *_a, **_k: base.copy())
    monkeypatch.setattr(runner, "controlled_inputs", lambda *_a, **_k: base["auxiliary_inputs"])
    calls = []
    def fake(spec, *, timeout):
        calls.append(spec)
        assert "CONTROLLER_ONLY" not in json.dumps(spec)
        assert "model-policy.private" not in json.dumps(spec)
        assert "controller_inputs" not in spec
        result = _fake_worker(spec, timeout=timeout)
        if spec["kind"] == "product":
            assert "task_input_sha256" not in spec["cell"]
            assert "comparison_cohort" not in spec["cell"]
            result["task_exposure"] = _task_exposure(spec["case"], spec["cell"]["arm_id"])
            result["config_identity"] = {role: {"sha256": __import__("hashlib").sha256(Path(spec[path]).read_bytes()).hexdigest()}
                                         for role, path in (("model", "model_config"), ("rag", "rag_config"))}
        return result
    monkeypatch.setattr(runner, "_subprocess_cell", fake)
    args = dict(registry_path=registry, profile="ci", output_dir=tmp_path / "run", run_id="resume-test",
                model_rubrics_path=inputs["rubrics"]["path"], model_policy_path=inputs["policy"]["path"],
                comparison_cohort="toy-prospective-v1")
    return runner, args, calls, fake


def test_order2_freezes_before_dispatch_and_terminal_resume_is_read_only(tmp_path, monkeypatch):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    def inspect(spec, *, timeout):
        run = args["output_dir"]
        assert (run / "model-policy.private.json").read_bytes() == args["model_policy_path"].read_bytes()
        assert (run / "model-rubrics.private.jsonl").read_bytes() == args["model_rubrics_path"].read_bytes()
        return fake(spec, timeout=timeout)
    monkeypatch.setattr(runner, "_subprocess_cell", inspect)
    result = runner.run_suite(**args)
    assert result["status"] == "engineering_pass"
    rows = [json.loads(line) for line in (args["output_dir"] / "observations.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and all(row["comparison_cohort"] == "toy-prospective-v1" for row in rows)
    assert all(row["task_input_sha256"] == row["planned_input_binding"]["task_input_sha256"] for row in rows)
    count = len(calls)
    assert runner.run_suite(**args, resume=True) == result
    assert len(calls) == count
    args["model_policy_path"].write_text(args["model_policy_path"].read_text() + "\n")
    with pytest.raises(ValueError, match="resume identity"):
        runner.run_suite(**args, resume=True)
    assert len(calls) == count


@pytest.mark.parametrize("target", ["original_policy", "frozen_rubrics", "source", "runtime", "runtime_model"])
def test_order2_drift_refuses_next_dispatch(tmp_path, monkeypatch, target):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    def change(spec, *, timeout):
        result = fake(spec, timeout=timeout)
        if len(calls) == 1:
            if target == "original_policy":
                args["model_policy_path"].write_text(args["model_policy_path"].read_text() + "\n")
            if target == "frozen_rubrics":
                path = args["output_dir"] / "model-rubrics.private.jsonl"; path.write_text(path.read_text() + "\n")
            if target == "source":
                original = runner.source_identity()
                monkeypatch.setattr(runner, "source_identity", lambda: {**original, "source_sha256": "f" * 64})
            if target == "runtime":
                path = args["output_dir"] / "effective/public-rag.yaml"; path.write_text(path.read_text() + "\n")
            if target == "runtime_model":
                path = args["output_dir"] / "effective/model-trial-001.yaml"; path.write_text(path.read_text() + "\n")
        return result
    monkeypatch.setattr(runner, "_subprocess_cell", change)
    with pytest.raises(ValueError, match="changed"):
        runner.run_suite(**args)
    assert len(calls) == 1
    assert len((args["output_dir"] / "components.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("mutation", ["question", "facts", "missing"])
def test_order2_worker_inputs_not_overwritten_by_planned_cell(tmp_path, monkeypatch, mutation):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    def changed(spec, *, timeout):
        result = fake(spec, timeout=timeout)
        if spec["kind"] == "product":
            exposure = result["task_exposure"]
            if mutation == "question": exposure["requests"][0]["message"] = "Changed request despite same case"
            if mutation == "facts":
                if spec["cell"]["arm_id"] == "production_full": exposure["requests"][0]["field_context_delivered"]["a"] = 99
                else: exposure["requests"][0]["prompt_messages"][-1]["content"] = "Changed raw facts"
            if mutation == "missing": result.pop("task_exposure")
            else: exposure["receipt_sha256"] = digest({k: v for k, v in exposure.items() if k != "receipt_sha256"})
            # A worker claim alone is never promoted into an actual binding.
            result.update(task_input_sha256="a" * 64, comparison_cohort="worker-claim")
        return result
    monkeypatch.setattr(runner, "_subprocess_cell", changed)
    if mutation == "missing": runner.run_suite(**args)
    else:
        with pytest.raises(ValueError, match="retained attempted worker"):
            runner.run_suite(**args)
    rows = [json.loads(line) for line in (args["output_dir"] / "observations.jsonl").read_text().splitlines()]
    assert rows and all(row["task_input_sha256"] is None and row["comparison_cohort"] is None for row in rows)
    assert all(row["worker_input_binding"]["comparison_cohort"] == "worker-claim" for row in rows)
    assert all(row["planned_input_binding"]["task_input_sha256"] is not None for row in rows)
    if mutation != "missing":
        assert len(rows) == 1 and rows[0]["status"] == "failed"
        assert not (args["output_dir"] / "report.json").exists()


@pytest.mark.parametrize("missing", [True, False])
def test_order2_recorded_runtime_missing_or_wrong_is_not_expected_identity(tmp_path, monkeypatch, missing):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    def changed(spec, *, timeout):
        result = fake(spec, timeout=timeout)
        if spec["kind"] == "product":
            if missing: result.pop("config_identity")
            else: result["config_identity"]["model"]["sha256"] = "f" * 64
        return result
    monkeypatch.setattr(runner, "_subprocess_cell", changed)
    if missing: runner.run_suite(**args)
    else:
        with pytest.raises(ValueError, match="observed worker runtime"):
            runner.run_suite(**args)
    rows = [json.loads(line) for line in (args["output_dir"] / "observations.jsonl").read_text().splitlines()]
    assert rows
    if missing:
        assert all(row["runtime_input_binding_status"] == "unknown_missing_worker_config" and row.get("analysis_condition") is None for row in rows)
    else:
        assert len(rows) == 1 and rows[0]["status"] == "failed"


@pytest.mark.parametrize("key", ["observation_id", "case_id", "case_sha256", "suite_id", "arm_id", "trial_id", "backend"])
def test_order2_wrong_outer_worker_identity_is_retained_failed(tmp_path, monkeypatch, key):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    def changed(spec, *, timeout):
        result = fake(spec, timeout=timeout)
        if spec["kind"] == "product": result[key] = "f" * 64 if key == "case_sha256" else "contradictory-worker"
        return result
    monkeypatch.setattr(runner, "_subprocess_cell", changed)
    with pytest.raises(ValueError, match="observed worker cell identity"):
        runner.run_suite(**args)
    row = json.loads((args["output_dir"] / "observations.jsonl").read_text().splitlines()[0])
    assert row["status"] == "failed"
    assert row["worker_input_binding"][key] == ("f" * 64 if key == "case_sha256" else "contradictory-worker")
    assert row[key] != row["worker_input_binding"][key]


def test_order2_validation_time_can_expire_without_dispatch(tmp_path, monkeypatch):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    current = [0.0]
    monkeypatch.setattr(runner.time, "monotonic", lambda: current[0])
    original = runner.source_identity
    validations = [0]
    def slow_validation():
        validations[0] += 1
        if validations[0] == 2: current[0] = 999999.0
        return original()
    monkeypatch.setattr(runner, "source_identity", slow_validation)
    report = runner.run_suite(**args)
    assert calls == []
    assert report["status"] == "blocked"


@pytest.mark.parametrize("bad", [42, [], {"model": None}, {"rag": []}])
def test_order2_malformed_runtime_receipt_is_durably_failed(tmp_path, monkeypatch, bad):
    runner, args, calls, fake = _order2_runner(tmp_path, monkeypatch)
    def changed(spec, *, timeout):
        result = fake(spec, timeout=timeout)
        if spec["kind"] == "product": result["config_identity"] = bad
        return result
    monkeypatch.setattr(runner, "_subprocess_cell", changed)
    with pytest.raises(ValueError, match="must be a mapping"):
        runner.run_suite(**args)
    row = json.loads((args["output_dir"] / "observations.jsonl").read_text().splitlines()[0])
    assert row["status"] == "failed" and row["config_identity"] == bad


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


def test_applied_reviews_use_frozen_initial_bytes(tmp_path, monkeypatch):
    runner, registry = _tiny_runner(monkeypatch)
    reviews = tmp_path / "input-reviews.jsonl"
    reviews.write_text("")
    output = tmp_path / "run"

    def mutate_external_reviews(spec, *, timeout):
        reviews.write_text('{"not": "the frozen input"}\n')
        return _fake_worker(spec, timeout=timeout)

    monkeypatch.setattr(runner, "_subprocess_cell", mutate_external_reviews)
    result = runner.run_suite(
        registry_path=registry,
        profile="ci",
        output_dir=output,
        run_id="resume-test",
        reviews_path=reviews,
    )
    assert result["status"] == "engineering_pass"
    assert result["reviewed_observations"] == 0
    assert (output / "reviews.private.jsonl").read_bytes() == b""
    assert (
        json.loads((output / "plan.json").read_text())["reviews_sha256"]
        == __import__("hashlib").sha256(b"").hexdigest()
    )


def test_completed_profiler_envelope_cannot_hide_missing_cell_work(
    tmp_path, monkeypatch
):
    import agronomy_agent.release_eval_runner as runner
    from agronomy_agent.release_evaluation import load_registry

    def incomplete_profile(*_args, **_kwargs):
        write_new_json(
            tmp_path / "backend-profile/receipt.json",
            {"status": "completed", "cells": {}},
        )
        return 0, "completed"

    monkeypatch.setattr(runner, "_command", incomplete_profile)
    report = runner.execute_worker(
        {
            "kind": "performance",
            "directory": str(tmp_path),
            "registry": load_registry(),
            "profile": "ci",
            "timeout": 3,
        }
    )
    assert report["status"] == "blocked"
    assert report["checks"][0]["passed"] is False


@pytest.mark.parametrize("persistent", [False, True])
def test_group_probe_permission_race_retries_but_persistent_denial_fails(
    monkeypatch, persistent
):
    class OwnedChild:
        pid = 12345

        def poll(self):
            return -15

        def wait(self, timeout):
            return -15

    probes = 0

    def probe(pid, sig):
        nonlocal probes
        if sig == 0:
            probes += 1
            if persistent or probes == 1:
                raise PermissionError("transient native exit race")
            raise ProcessLookupError("owned group has exited")

    monkeypatch.setattr(os, "killpg", probe)
    if persistent:
        with pytest.raises(PermissionError, match="unobservable"):
            _stop_owned_processes(OwnedChild(), new_session=True, grace=0.04)
    else:
        _stop_owned_processes(OwnedChild(), new_session=True, grace=0.04)
        assert probes == 2
