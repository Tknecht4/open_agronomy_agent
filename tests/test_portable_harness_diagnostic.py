from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_portable_harness_diagnostic", ROOT / "scripts/run_portable_harness_diagnostic.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_case_ids_accept_exposed_id_without_loading_rubric(tmp_path: Path) -> None:
    cases = tmp_path / "exposed.jsonl"
    cases.write_text(json.dumps({"id": "x1", "question": "How do units work?"}) + "\n")
    loaded = runner.load_cases(cases)
    units = runner.build_units(loaded, continuity=True, long_context=True, cache_case_id="x1")
    assert len(units) == 2 * (1 + len(runner.CONTINUITY) + 1 + 1)
    assert all(unit["case_id"] == "x1" for unit in units if unit["kind"] in {"exposed_pair", "cache_cold_warm"})
    with pytest.raises(ValueError, match="distinct"):
        cases.write_text(cases.read_text() * 2)
        runner.load_cases(cases)


def test_public_config_disables_inherited_private_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "1")
    payload = runner.public_rag_config(ROOT / "configs/rag.yaml")
    assert payload["private_knowledge"] == {"enabled": False, "required": False}
    assert runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=False)["prompt_cache_enabled"] is False
    assert runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=True)["prompt_cache_enabled"] is True
    assert "data/manifests/canada_agronomy_sources.json" in runner.rag_artifact_receipt(payload)


def test_direct_cache_probe_reuses_identical_prompt_and_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    paths = []
    for enabled in (False, True):
        path = tmp_path / f"model_{enabled}.yaml"
        path.write_text(yaml.safe_dump(runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=enabled)))
        paths.append(path)
    calls: list[tuple[bool, str, str]] = []

    class FakeGenerator:
        def __init__(self, enabled: bool) -> None:
            self.enabled = enabled
            self.count = 0
            self.model_identity = {"status": "test"}
            self._resolved_model_snapshot = Path("/synthetic/model-snapshot")
            self.last_generation_stats: dict[str, str] = {}

        def set_cache_scope(self, scope: str) -> None:
            self.scope = scope

        def generate(self, messages: list[dict[str, str]]) -> str:
            self.count += 1
            calls.append((self.enabled, self.scope, runner.canonical_hash(messages)))
            self.last_generation_stats = {"prompt_cache_status": (
                "disabled" if not self.enabled else "reused_saved_prefix" if self.count == 2 else "prepared_this_request"
            )}
            return "same answer"

    monkeypatch.setattr(runner, "_build_mlx_generator", lambda _id, config, _path: FakeGenerator(config["prompt_cache_enabled"]))
    messages = [{"role": "system", "content": "Synthetic"}, {"role": "user", "content": "How?"}]
    probe = runner.direct_cache_probe(
        messages=messages, model_id="test", disabled_config_path=paths[0],
        enabled_config_path=paths[1], max_tokens=320, session_id="test-session",
    )
    assert probe["answer_equal"] is True
    assert probe["status"] == "completed"
    assert probe["cache_statuses"] == {"disabled": "disabled", "cold": "prepared_this_request", "warm": "reused_saved_prefix"}
    assert len({scope for _, scope, _ in calls}) == 1
    assert len({prompt_hash for _, _, prompt_hash in calls}) == 1
    assert "diagnostic_isolated_parity" in calls[0][1]
    assert probe["outputs"][0]["resolved_model_snapshot"] == "/synthetic/model-snapshot"
    json.dumps(probe)


def test_cache_probe_retains_disabled_and_cold_when_warm_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    disabled = tmp_path / "disabled.yaml"
    enabled = tmp_path / "enabled.yaml"
    disabled.write_text(yaml.safe_dump(runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=False)))
    enabled.write_text(yaml.safe_dump(runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=True)))

    class FakeGenerator:
        model_identity = {"status": "test"}

        def __init__(self, cache_enabled: bool) -> None:
            self.cache_enabled = cache_enabled
            self.calls = 0
            self.last_generation_stats = {}

        def set_cache_scope(self, _scope: str) -> None:
            pass

        def generate(self, _messages: list[dict[str, str]]) -> str:
            self.calls += 1
            if self.cache_enabled and self.calls == 2:
                raise RuntimeError("warm cache failed")
            self.last_generation_stats = {"prompt_cache_status": "prepared_this_request" if self.cache_enabled else "disabled"}
            return "answer"

    monkeypatch.setattr(runner, "_build_mlx_generator", lambda _id, cfg, _path: FakeGenerator(cfg["prompt_cache_enabled"]))
    probe = runner.direct_cache_probe(messages=[{"role": "user", "content": "synthetic"}], model_id="test",
                                      disabled_config_path=disabled, enabled_config_path=enabled,
                                      max_tokens=8, session_id="synthetic-session")
    assert probe["status"] == "failed"
    assert [row["status"] for row in probe["outputs"]] == ["completed", "completed", "failed"]
    assert probe["answer_equal"] is None


def test_direct_reference_uses_only_fixed_system_and_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    model = tmp_path / "model.yaml"
    model.write_text(yaml.safe_dump(runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=False)))

    class FakeGenerator:
        model_identity = {"status": "test"}
        last_generation_stats = {"prompt_cache_status": "disabled"}

        def generate(self, messages: list[dict[str, str]]) -> str:
            assert messages == [
                {"role": "system", "content": runner.DIRECT_REFERENCE_SYSTEM},
                {"role": "user", "content": "How do units work?"},
            ]
            return "Use consistent units."

    monkeypatch.setattr(runner, "_build_mlx_generator", lambda *_args: FakeGenerator())
    row = runner.direct_reference(question="How do units work?", model_id="test",
                                  model_config_path=model, max_tokens=320)
    assert row["answer"] == "Use consistent units."
    assert row["prompt_sha256"] == runner.canonical_hash(row["prompt_messages"])
    assert "not_product_mode" in row["boundary"]


@pytest.mark.parametrize("rag_source", ["rag.yaml", "rag_production_foundations_method_candidate.yaml"])
def test_worker_retains_product_trace_with_mock(
    tmp_path: Path, rag_source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    # This is a product-trace contract test. Native GPU initialization belongs
    # to the separately recorded real-model diagnostic, not a mock CPU test.
    monkeypatch.setattr(runner, "_runtime_receipt", lambda: {"mlx_device": "mock"})
    rag = tmp_path / "rag.yaml"
    rag.write_text(yaml.safe_dump(runner.public_rag_config(ROOT / "configs" / rag_source)))
    model = tmp_path / "model.yaml"
    model.write_text(yaml.safe_dump(runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=False)))
    spec = {
        "unit": {"kind": "exposed_pair", "turns": ["What does lb/ac mean?"], "cache_enabled": False},
        "db_path": str(tmp_path / "traces.sqlite3"),
        "artifact_root": str(tmp_path / "artifacts"),
        "rag_config": str(rag), "model_config": str(model),
        "model_id": "mock", "max_tokens": 64,
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    result = tmp_path / "worker.jsonl"
    assert runner._worker(spec_path, result) == 0
    row = json.loads(result.read_text())
    assert row["status"] == "completed"
    assert row["answer_stages"]["final"]["text"] == row["answer"]
    assert row["prompt_messages"]
    assert row["context_budget"]["status"]
    assert len(row["stage_receipts"]) == 17


def test_parent_preserves_timeout_as_failed_cell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "x1", "question": "What is a seed lot?"}) + "\n")
    monkeypatch.setattr(runner, "DEFAULT_ARMS", {"active": ROOT / "configs/rag.yaml"})
    monkeypatch.setattr(runner, "_ensure_preflight", lambda **_kwargs: True)

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("worker", 0.01)

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    arguments = argparse.Namespace(
        cases=cases, model_config=ROOT / "configs/model.yaml", output_dir=tmp_path / "run",
        model_id=None, run_id="timeout-test", max_tokens=320, cell_timeout_seconds=0.01,
        include_continuity=False, include_long_context=False, include_cache=False,
        include_direct_reference=False, cache_case_id=None,
        execute=True, resume=False,
    )
    assert runner._run_parent(arguments) == 1
    row = json.loads((tmp_path / "run/cells.jsonl").read_text())
    assert row["status"] == "timed_out"
    assert row["observed_turns"] == 0
    arguments.resume = True
    assert runner._run_parent(arguments) == 1
    assert len((tmp_path / "run/cells.jsonl").read_text().splitlines()) == 1


def test_resume_preserves_orphan_worker_and_uses_fresh_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "x1", "question": "What is a seed lot?"}) + "\n")
    monkeypatch.setattr(runner, "DEFAULT_ARMS", {"active": ROOT / "configs/rag.yaml"})
    monkeypatch.setattr(runner, "_source_receipt", lambda: {"source_tree_sha256": "test"})
    monkeypatch.setattr(runner, "_ensure_preflight", lambda **_kwargs: True)
    seen: list[Path] = []

    def child(*argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = argv[0]
        assert isinstance(command, list)
        output = Path(command[command.index("--worker-output") + 1])
        seen.append(output)
        output.write_text(json.dumps({"status": "completed", "turn_index": 0}) + "\n")
        if len(seen) == 1:
            raise KeyboardInterrupt("parent interrupted after child wrote")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", child)
    arguments = argparse.Namespace(
        cases=cases, model_config=ROOT / "configs/model.yaml", output_dir=tmp_path / "run",
        model_id=None, run_id="interrupted-test", max_tokens=320, cell_timeout_seconds=1.0,
        include_continuity=False, include_long_context=False, include_cache=False,
        include_direct_reference=False, cache_case_id=None, execute=True, resume=False,
    )
    with pytest.raises(KeyboardInterrupt):
        runner._run_parent(arguments)
    assert seen[0].is_file()
    assert not (tmp_path / "run/cells.jsonl").exists()
    arguments.resume = True
    assert runner._run_parent(arguments) == 0
    assert len(seen) == 2 and seen[0] != seen[1]
    assert seen[0].read_text() == seen[1].read_text()
    row = json.loads((tmp_path / "run/cells.jsonl").read_text())
    assert row["status"] == "completed"
    assert row["attempt"] == 2


def test_preflight_requires_resolved_snapshot_and_measured_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    config = tmp_path / "model.yaml"
    config.write_text(yaml.safe_dump(runner.model_config_for_cell(ROOT / "configs/model.yaml", cache_enabled=False)))
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"model_config": str(config), "model_id": "synthetic-model",
                                "manifest_sha256": "test-manifest"}))

    class FakeGenerator:
        last_generation_stats = {"generation_tokens": 8}
        model_identity = {"status": "verified_direct_loader"}
        _resolved_model_snapshot = None

        def set_cache_scope(self, _scope: str) -> None:
            pass

        def generate(self, _messages: list[dict[str, str]]) -> str:
            return "Unknown."

    monkeypatch.setattr(runner, "_build_mlx_generator", lambda *_args: FakeGenerator())
    monkeypatch.setattr(runner, "_runtime_receipt", lambda: {"mlx_device": "Device(gpu, 0)"})
    result = tmp_path / "preflight.json"
    assert runner._preflight_child(spec, result) == 1
    assert json.loads(result.read_text())["status"] == "failed"
    FakeGenerator._resolved_model_snapshot = Path("/synthetic/pinned-snapshot")
    result2 = tmp_path / "preflight-passed.json"
    assert runner._preflight_child(spec, result2) == 0
    row = json.loads(result2.read_text())
    assert row["generation_stats"]["generation_tokens"] == 8
    assert row["resolved_model_snapshot"] == "/synthetic/pinned-snapshot"


def test_failed_preflight_stops_before_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "x1", "question": "What is a seed lot?"}) + "\n")
    monkeypatch.setattr(runner, "DEFAULT_ARMS", {"active": ROOT / "configs/rag.yaml"})
    monkeypatch.setattr(runner, "_source_receipt", lambda: {"source_tree_sha256": "test"})
    calls: list[list[str]] = []

    def failed_preflight(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert "--preflight-spec" in command
        output = Path(command[command.index("--preflight-output") + 1])
        output.write_text(json.dumps({"status": "failed", "error_type": "FileNotFoundError",
                                      "error": "model snapshot missing"}) + "\n")
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(runner.subprocess, "run", failed_preflight)
    arguments = argparse.Namespace(
        cases=cases, model_config=ROOT / "configs/model.yaml", output_dir=tmp_path / "run",
        model_id=None, run_id="missing-snapshot", max_tokens=320, cell_timeout_seconds=1.0,
        include_continuity=False, include_long_context=False, include_cache=False,
        include_direct_reference=False, cache_case_id=None, execute=True, resume=False,
    )
    assert runner._run_parent(arguments) == 1
    assert len(calls) == 1
    assert not (tmp_path / "run/cells.jsonl").exists()
    assert json.loads((tmp_path / "run/preflight.jsonl").read_text())["status"] == "failed"


def test_model_execution_is_distinct_from_executor_completion() -> None:
    execution = {"stage_receipts": [{"stage_id": "draft_generation", "evidence": {"model_call_executed": True}}]}
    generated = runner.model_execution_disposition({"generation_stats": {"generation_tokens": 8}}, execution)
    assert generated["disposition"] == "model_generated"
    assert generated["model_generation_eligible"] is True
    fallback = runner.model_execution_disposition({"generation_fallback": {"reason": "backend failed"}}, execution)
    assert fallback["product_quality_eligible"] is False
    assert fallback["model_generation_eligible"] is False
    bypass = runner.model_execution_disposition({"generation_bypass": {"reason": "typed result"}}, execution)
    assert bypass["product_quality_eligible"] is True
    assert bypass["model_generation_eligible"] is False


def test_editor_failure_does_not_qualify_final_product_after_successful_draft() -> None:
    execution = {"stage_receipts": [{"stage_id": "draft_generation", "evidence": {
        "model_call_executed": True, "fallback_used": False}}]}
    verification = {"rejection_reasons": ["editor_error", "RuntimeError"], "fallback_applied": True}
    result = runner.model_execution_disposition({
        "generation_stats": {"generation_tokens": 17}, "answer_verification": verification,
    }, execution)
    assert result["disposition"] == "editor_backend_failure"
    assert result["product_quality_eligible"] is False
    assert result["draft_generation_eligible"] is True
    assert result["model_generation_eligible"] is True
    assert result["editor_failure"] == verification


def test_editor_content_rejection_keeps_successful_product_eligible() -> None:
    execution = {"stage_receipts": [{"stage_id": "draft_generation", "evidence": {
        "model_call_executed": True, "fallback_used": False}}]}
    result = runner.model_execution_disposition({
        "generation_stats": {"generation_tokens": 17},
        "answer_verification": {"rejection_reasons": ["claim_risk_not_cleared"], "fallback_applied": True},
    }, execution)
    assert result["disposition"] == "model_generated"
    assert result["product_quality_eligible"] is True
    assert result["editor_failure"] is None
