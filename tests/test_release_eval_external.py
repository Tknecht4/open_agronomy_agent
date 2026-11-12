import hashlib
import json

import pytest

from agronomy_agent.release_eval_external import read_external_inputs, phase_factories


def _controls(tmp_path):
    import test_codex_app_server_egress as fixtures
    generator = fixtures._canonical_generator(tmp_path / "fixture")
    values = {"authorization": json.loads(generator._authorization_path.read_text()),
              "suite": generator.expected_suite_case_contract,
              "artifacts": generator.expected_artifact_contract,
              "static_prompts": generator.expected_static_prompt_contract}
    bindings = {}
    for name, value in values.items():
        path = tmp_path / (name + ".json")
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        bindings[name] = {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
    return generator, bindings


def test_external_inputs_and_factories_stay_lazy_and_phase_bound(tmp_path):
    generator, declaration = _controls(tmp_path)
    inputs = read_external_inputs(declaration, tmp_path)
    bindings = {name: {"path": str(item["path"]), "sha256": item["sha256"]} for name, item in inputs.items()}
    draft_factory, editor_factory = phase_factories(bindings,
        model_config=generator._model_config_path, arm="production_full", max_tokens=640)
    draft, editor = draft_factory(), editor_factory()
    assert draft.egress_phase == "candidate_generation" and draft.max_tokens == 640
    assert editor.egress_phase == "verification" and editor.max_tokens == 220
    assert draft.model_identity["model_revision"] is None
    assert draft._client is None and editor._client is None
    assert draft.expected_suite_case_contract == generator.expected_suite_case_contract


@pytest.mark.parametrize("change", ["missing", "extra", "bytes", "escape"])
def test_unbound_external_controls_are_rejected(tmp_path, change):
    _, declaration = _controls(tmp_path)
    if change == "missing": declaration.pop("authorization")
    if change == "extra": declaration["gold"] = declaration["suite"]
    if change == "bytes": (tmp_path / "suite.json").write_text("{}")
    if change == "escape": declaration["suite"]["path"] = "../suite.json"
    with pytest.raises(ValueError):
        read_external_inputs(declaration, tmp_path)


def test_factory_rechecks_frozen_controls_before_client_creation(tmp_path):
    generator, declaration = _controls(tmp_path)
    inputs = read_external_inputs(declaration, tmp_path)
    bindings = {name: {"path": str(item["path"]), "sha256": item["sha256"]} for name, item in inputs.items()}
    (tmp_path / "artifacts.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        phase_factories(bindings, model_config=generator._model_config_path,
                        arm="production_full", max_tokens=640)


def test_trial_grants_are_frozen_and_selected_by_effective_config(tmp_path):
    from agronomy_agent.release_eval_external import TRIAL_AUTHORIZATION_SCHEMA
    generator, declaration = _controls(tmp_path)
    auth_path = tmp_path / "authorization.json"
    grant = json.loads(auth_path.read_text())
    sha = grant["model_config_sha256"]
    other_sha = "a" * 64
    auth_path.write_text(json.dumps({"schema_version": TRIAL_AUTHORIZATION_SCHEMA,
        "grants": {sha: grant, other_sha: {**grant, "model_config_sha256": other_sha}}}))
    declaration["authorization"]["sha256"] = hashlib.sha256(auth_path.read_bytes()).hexdigest()
    inputs = read_external_inputs(declaration, tmp_path)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    bindings = {}
    for name, item in inputs.items():
        path = frozen / (name + ".json")
        path.write_bytes(item["bytes"])
        bindings[name] = {"path": str(path), "sha256": item["sha256"]}
    draft_factory, _ = phase_factories(bindings, model_config=generator._model_config_path,
                                    arm="raw_model", max_tokens=640)
    draft = draft_factory()
    assert draft.egress_authorization["model_config_sha256"] == sha
    assert draft._authorization_path == frozen / ("authorization-" + sha + ".json")
    assert draft._client is None
    (frozen / ("authorization-" + sha + ".json")).write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        phase_factories(bindings, model_config=generator._model_config_path,
                        arm="raw_model", max_tokens=640)


def test_canonical_cli_worker_admits_public_envelope_with_private_overlay_disabled(tmp_path, monkeypatch):
    """Exercise the actual child environment and CLI before the egress seam."""
    import sys
    from pathlib import Path
    from agronomy_agent.release_eval_runner import _command
    from agronomy_agent.release_evaluation import ROOT
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "1")
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", "must-not-be-inherited.json")
    spec, output = tmp_path/"spec.json", tmp_path/"result.json"
    spec.write_text("{}")
    code = f'''
import json, os, runpy, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT/'tests')!r})
import test_codex_app_server_egress as fixtures
from agronomy_agent import agent, release_eval_runner
def execute(spec):
    assert os.environ['AGRONOMY_AGENT_PRIVATE_KNOWLEDGE'] == '0'
    assert 'AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST' not in os.environ
    generator = fixtures._canonical_generator(Path({str(tmp_path/'contract')!r}), arm='raw_model')
    envelope = agent._build_benchmark_egress_envelope(
        generator=generator, messages=[{{'role':'user','content':'Explain a synthetic supplied observation.'}}],
        eval_id=fixtures._EVAL_ID, question='Explain a synthetic supplied observation.',
        field_context=None, context=None, resources=None)
    assert envelope['private_knowledge_policy'] == 'disabled'
    assert envelope['private_knowledge_overlay_loaded'] is False
    return {{'status':'completed','checks':[]}}
release_eval_runner.execute_worker = execute
sys.argv = ['run_release_evaluation.py','--worker-spec',{str(spec)!r},'--worker-output',{str(output)!r}]
runpy.run_path({str(ROOT/'scripts/run_release_evaluation.py')!r},run_name='__main__')
'''
    status, disposition = _command([sys.executable, "-c", code], cwd=ROOT,
                                   output=tmp_path/"child.log", timeout=30)
    assert (status, disposition) == (0, "completed"), (tmp_path/"child.log").read_text()
    assert json.loads(output.read_text())["status"] == "completed"


def test_trial_bundle_rejects_mislabeled_config_and_unbound_trial(tmp_path):
    from agronomy_agent.release_eval_external import TRIAL_AUTHORIZATION_SCHEMA
    generator, declaration = _controls(tmp_path)
    path = tmp_path / "authorization.json"
    grant = json.loads(path.read_text())
    path.write_text(json.dumps({"schema_version": TRIAL_AUTHORIZATION_SCHEMA,
        "grants": {"b" * 64: grant}}))
    declaration["authorization"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="binding"):
        read_external_inputs(declaration, tmp_path)


@pytest.mark.parametrize("change", [None, "source", "inventory", "missing_case"])
def test_external_controls_bind_actual_source_and_complete_inventory(change):
    from agronomy_agent.release_eval_external import suite_inventory_sha256, validate_external_plan
    plan = {"suite_id": "synthetic", "source": {"source_sha256": "a" * 64},
            "cases": [{"case_id": "one", "case_sha256": "b" * 64}]}
    suite = {"source_sha256": "a" * 64, "benchmark_suite_sha256": suite_inventory_sha256(plan),
             "cases": {"one": {}}}
    if change == "source": suite["source_sha256"] = "c" * 64
    if change == "inventory": suite["benchmark_suite_sha256"] = "d" * 64
    if change == "missing_case": suite["cases"] = {}
    inputs = {"suite": {"value": suite}}
    if change:
        with pytest.raises(ValueError, match="actual source"):
            validate_external_plan(inputs, plan)
    else:
        validate_external_plan(inputs, plan)


def test_canonical_worker_passes_lazy_phase_factories_only_to_hosted_backend(tmp_path, monkeypatch):
    from agronomy_agent import release_eval_runner as runner, release_eval_executor as executor
    import agronomy_agent.release_eval_external as external
    calls = []
    draft, editor = lambda: None, lambda: None
    def factories(bindings, **kwargs):
        calls.append((bindings, kwargs))
        return draft, editor
    monkeypatch.setattr(external, "phase_factories", factories)
    monkeypatch.setattr(executor, "execute_product_case", lambda *a, **k: k)
    spec = {"kind": "product", "directory": str(tmp_path), "case": {},
            "model_config": str(tmp_path / "model.yaml"), "rag_config": str(tmp_path / "rag.yaml"),
            "max_tokens": 640, "cell": {"backend": "codex_app_server", "arm_id": "production_full", "trial_id": "trial-001"},
            "external_generation": {"synthetic": "pinned controls"}}
    result = runner.execute_worker(spec)
    assert result["generation_backend_factory"] is draft
    assert result["verification_backend_factory"] is editor
    assert calls[0][1]["arm"] == "production_full"
    assert len(calls) == 1
    spec["cell"]["backend"] = "mlx"
    result = runner.execute_worker(spec)
    assert "generation_backend_factory" not in result and len(calls) == 1


@pytest.mark.parametrize("change", [None, "output", "model", "thread", "status"])
def test_hosted_return_observation_never_substitutes_for_native_identity(change):
    from agronomy_agent.release_eval_executor import _observed_hosted_return
    sha = hashlib.sha256(b"Synthetic returned answer.").hexdigest()
    receipt = {"provider_status": "completed", "selected_model": "synthetic_hosted_model",
               "thread_id": "synthetic-thread", "turn_id": "synthetic-turn", "output_sha256": sha}
    turn = {"draft": "Synthetic returned answer.", "model_identity": {"model_id": "synthetic_hosted_model", "model_revision": None},
            "model_execution_eligible": False,
            "generation_stats": {"backend": "codex_app_server_chatgpt_auth", "app_server_receipt": receipt,
                                 "benchmark_egress_receipt": {"model_output_sha256": sha}}}
    if change == "output": receipt["output_sha256"] = "0" * 64
    if change == "model": receipt["selected_model"] = "other"
    if change == "thread": receipt.pop("thread_id")
    if change == "status": receipt["provider_status"] = "failed"
    assert _observed_hosted_return(turn) is (change is None)
    assert turn["model_execution_eligible"] is False


@pytest.mark.parametrize("change", [None, "legacy_schema", "native_controls", "extra_arm", "missing_controls", "invented_revision"])
def test_versioned_external_registry_keeps_native_and_authority_boundaries(tmp_path, monkeypatch, change):
    import yaml
    from agronomy_agent import release_evaluation as evaluation
    _, declaration = _controls(tmp_path)
    registry = json.loads(evaluation.DEFAULT_REGISTRY.read_text())
    for value in (registry["model_config"], registry["rag_config"],
                  *(s["path"] for s in registry["suites"]), *registry["product_contract_tests"], *evaluation.SCORER_FILES):
        path = tmp_path/value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((evaluation.ROOT/value).read_bytes())
    model = tmp_path/registry["model_config"]
    config = yaml.safe_load(model.read_text())
    config["model_revision"] = "invented-hosted-weight-pin" if change == "invented_revision" else None
    model.write_text(yaml.safe_dump(config))
    registry.update(schema_version=evaluation.EXTERNAL_REGISTRY_SCHEMA, arms=["raw_model", "production_full"],
                    external_generation=declaration)
    for name, profile in registry["profiles"].items():
        if name != "ci":profile["backend"] = "codex_app_server"
    if change == "legacy_schema": registry["schema_version"] = evaluation.REGISTRY_SCHEMA
    if change == "native_controls":
        for name, profile in registry["profiles"].items():
            if name != "ci":profile["backend"] = "mlx"
    if change == "extra_arm": registry["arms"].append("kernel_only")
    if change == "missing_controls": registry.pop("external_generation")
    path = tmp_path/"registry.json"
    path.write_text(json.dumps(registry))
    if change not in (None, "invented_revision"):
        with pytest.raises(ValueError):evaluation.load_registry(path, root=tmp_path)
        return
    parsed = evaluation.load_registry(path, root=tmp_path)
    monkeypatch.setattr(evaluation, "controlled_inputs", lambda *a, **k: {})
    monkeypatch.setattr(evaluation, "source_identity", lambda *a, **k: {"commit":"synthetic", "source_sha256":"a"*64, "files":{}})
    if change == "invented_revision":
        with pytest.raises(ValueError, match="unknown"):evaluation.build_plan(parsed, profile="baseline", root=tmp_path)
    else:
        plan = evaluation.build_plan(parsed, profile="baseline", root=tmp_path)
        assert plan["model"]["revision"] is None
        assert "provider_revision_unknown" in plan["sampling"]["environment_policy"]
