"""Failure bounds and data isolation for synthetic workspace profiling."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest
import yaml

from agronomy_agent.private_knowledge import load_private_knowledge_overlay

ROOT = Path(__file__).resolve().parents[1]


def load_profiler(name, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("swallow_timeout", [False, True])
def test_worker_deadline_prevents_later_model_calls(tmp_path, monkeypatch, swallow_timeout):
    module = load_profiler("profile_workspace_model", monkeypatch)
    handlers, calls = {}, []
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "enabled")
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", "unused-synthetic-manifest")
    monkeypatch.setattr(module.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))
    monkeypatch.setattr(module.signal, "alarm", lambda seconds: 0)
    monkeypatch.setattr(module, "snapshot_download", lambda **kwargs: "mock snapshot")
    monkeypatch.setattr(module, "build_settings", lambda **kwargs: SimpleNamespace())
    store = SimpleNamespace(create_session=lambda *args: {"session_id": "synthetic"})
    monkeypatch.setattr(module, "create_app", lambda settings: SimpleNamespace(state=SimpleNamespace(trace_store=store)))
    metal = SimpleNamespace(reset_peak_memory=lambda: None, get_active_memory=lambda: 0, get_peak_memory=lambda: 0)
    core = SimpleNamespace(metal=metal, default_device=lambda: "mock GPU")
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)

    def execute(request):
        calls.append(request.message)
        try:
            handlers[module.signal.SIGALRM](module.signal.SIGALRM, None)
        except TimeoutError:
            if not swallow_timeout:
                raise
        return SimpleNamespace(answer="synthetic", stage_receipts=[], turn={})

    monkeypatch.setattr(module, "execute_agent_request", execute)
    monkeypatch.setattr(sys, "argv", ["profile", "--execute-local-pinned", "--profile-worker", "--output-dir", str(tmp_path), "--deadline-seconds", "1"])
    assert module.main() == 1
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert len(calls) == 1
    assert receipt["status"] == "failed"
    assert receipt["failure"]["type"] == "TimeoutError"
    assert len(receipt["cells"]) == 1
    assert receipt["cells"][0]["status"] == "failed"
    assert receipt["private_knowledge_mode"] == "disabled"


def test_parent_deadline_kills_stalled_worker_and_retains_receipt(tmp_path, monkeypatch):
    module = load_profiler("profile_workspace_model", monkeypatch)
    path = tmp_path / "receipt.json"
    code = """
import json, os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(json.dumps({'claim_eligible': False, 'worker_pid': os.getpid(),
 'cells': [{'status': 'completed', 'answer_sha256': 'synthetic-receipt'}, {'status': 'running'}]}))
time.sleep(30)
"""
    started = time.monotonic()
    assert module.supervise_profile([sys.executable, "-c", code, str(path)], path, 1) == 1
    assert time.monotonic() - started < 6
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "failed"
    assert receipt["failure"]["type"] == "TimeoutError"
    assert receipt["cells"][0] == {"status": "completed", "answer_sha256": "synthetic-receipt"}
    assert receipt["cells"][1]["status"] == "interrupted"
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["worker_pid"], 0)


@pytest.mark.parametrize("name", ["profile_workspace_model", "profile_workspace_backend"])
def test_profilers_disable_inherited_private_overlay_before_runtime(tmp_path, monkeypatch, name):
    module = load_profiler(name, monkeypatch)
    corpus = tmp_path / "synthetic-private.jsonl"
    corpus.write_text('{"text":"Synthetic private isolation sentinel."}\n')
    manifest = tmp_path / "synthetic-private-manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "open_agronomy_agent.private_knowledge_overlay.v1",
        "distribution_scope": "local_only_not_for_redistribution", "answer_role": "context_only",
        "corpora": [{"path": str(corpus), "sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
                     "rows": 1, "distribution_scope": "local_only_not_for_redistribution", "answer_role": "context_only"}],
    }))
    config = yaml.safe_load((ROOT / "configs/rag.yaml").read_text())["private_knowledge"]
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "enabled")
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", str(manifest))
    assert load_private_knowledge_overlay(ROOT, config) is not None
    seen = []

    def stop_before_runtime(settings):
        seen.append(load_private_knowledge_overlay(ROOT, config))
        assert os.environ["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] == "disabled"
        assert "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST" not in os.environ
        raise RuntimeError("Synthetic stop before runtime startup")

    monkeypatch.setattr(module, "create_app", stop_before_runtime)
    args = ["profile", "--output-dir", str(tmp_path / "profile")]
    if name == "profile_workspace_model":
        monkeypatch.setattr(module, "snapshot_download", lambda **kwargs: "mock snapshot")
        args += ["--execute-local-pinned", "--profile-worker"]
    monkeypatch.setattr(sys, "argv", args)
    assert module.main() == 1
    assert seen == [None]
    receipt = json.loads((tmp_path / "profile" / "receipt.json").read_text())
    assert receipt["private_knowledge_mode"] == "disabled"
