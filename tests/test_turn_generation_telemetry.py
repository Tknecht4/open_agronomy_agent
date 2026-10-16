"""A reused backend may only contribute telemetry for calls made by this turn."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from agronomy_agent.execution_core import AgentExecutionRequest
from agronomy_agent.server.services import chat_service
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


class ReusedBackend:
    def __init__(self) -> None:
        self.calls = 0
        self.fail_next = False
        self.last_generation_stats = None
        self.model_identity = {
            "configured_model_id": "synthetic-local-model",
            "configured_model_revision": "test-revision",
            "response_model_id": None,
            "runtime": {"call_id": 0},
        }

    def count_prompt_tokens(self, messages):  # noqa: ANN001, ANN201
        return sum(len(item["content"].split()) + 4 for item in messages)

    def generate(self, messages):  # noqa: ANN001, ANN201
        del messages
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic backend interruption")
        self.calls += 1
        if self.last_generation_stats is None:
            self.last_generation_stats = {"generation_tokens": 0, "call_id": 0, "nested": {"call_id": 0}}
        self.last_generation_stats["generation_tokens"] = self.calls
        self.last_generation_stats["call_id"] = self.calls
        self.last_generation_stats["nested"]["call_id"] = self.calls
        self.model_identity["response_model_id"] = f"actual-response-{self.calls}"
        self.model_identity["runtime"]["call_id"] = self.calls
        return f"Synthetic model output {self.calls}."


def _turn(tmp_path, store, settings, backend, question, *, mode="baseline", **controls):  # noqa: ANN001, ANN201
    session = store.create_session("Telemetry", {}, {})
    request = AgentExecutionRequest(
        store=store, settings=settings, session_id=session["session_id"],
        message=question, mode=mode, model_id="synthetic-local-model",
        rag_config="configs/rag.yaml", max_tokens=100,
        trace_options={"store_prompt_messages": True},
        generation_backend=backend,
        execution_class="observed_system_execution_nonclaim",
        **controls,
    )
    return chat_service.execute_agent_request(request).turn


def _runtime(tmp_path):  # noqa: ANN001, ANN201
    db_path = tmp_path / "telemetry.sqlite3"
    store = TraceStore(db_path)
    settings = build_settings(
        db_path=db_path, artifact_root=tmp_path / "artifacts",
        model_config_path="configs/model.yaml", default_rag_config="configs/rag.yaml",
        network_mode="offline",
    )
    return store, settings


def test_reused_draft_stats_do_not_enter_bypass_or_unavailable_turns(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    store, settings = _runtime(tmp_path)
    backend = ReusedBackend()
    generated = _turn(tmp_path, store, settings, backend, "Explain crop rotation.")
    assert generated["answer"] == "Synthetic model output 1."
    assert generated["trace"]["metadata"]["generation_stats"]["call_id"] == 1
    assert generated["trace"]["metadata"]["model_identity"]["response_model_id"] == "synthetic-local-model"
    backend.model_identity["response_model_id"] = "actual-response-2"

    deterministic = _turn(
        tmp_path, store, settings, backend,
        "Convert a fertilizer rate of 100 lb/ac to kg/ha.", mode="agronomic_rag",
    )
    assert deterministic["trace"]["metadata"]["generation_bypass"]
    assert "generation_stats" not in deterministic["trace"]["metadata"]
    assert deterministic["trace"]["metadata"]["model_identity"]["response_model_id"] is None
    assert deterministic["trace"]["metadata"]["model_identity"]["configured_model_revision"] == "test-revision"
    assert backend.model_identity["response_model_id"] == "actual-response-2"

    backend.fail_next = True
    fallback = _turn(tmp_path, store, settings, backend, "Explain a synthetic model failure.")
    assert fallback["answer"] == chat_service.ANALYSIS_UNAVAILABLE_ANSWER
    assert fallback["trace"]["metadata"]["generation_fallback"]["fallback_model_id"] == "analysis_unavailable"
    assert "generation_stats" not in fallback["trace"]["metadata"]
    assert fallback["trace"]["metadata"]["model_identity"]["response_model_id"] is None

    hold = SimpleNamespace(
        status="held", hold_text="Synthetic authority hold.", reason="authority_missing",
        as_record=lambda: {"status": "held", "reason": "authority_missing"},
    )
    monkeypatch.setattr(chat_service, "decide_evidence_intervention", lambda *args, **kwargs: hold)
    authority = _turn(
        tmp_path, store, settings, backend,
        "What soil health evidence is relevant to soil erosion?", mode="agronomic_rag",
        typed_tools_enabled=False, document_retrieval_enabled=False, graph_retrieval_enabled=False,
    )
    assert authority["trace"]["metadata"]["generation_bypass"]["reason"] == "authority_missing"
    assert authority["answer"] == "Synthetic authority hold."
    assert "generation_stats" not in authority["trace"]["metadata"]
    assert authority["trace"]["metadata"]["model_identity"]["response_model_id"] is None

    small_config = deepcopy(chat_service.load_model_config(settings.model_config_path))
    small_config["context_management"] = {"context_limit_tokens": 30}
    monkeypatch.setattr(chat_service, "load_model_config", lambda _path: small_config)
    unavailable = _turn(tmp_path, store, settings, backend, "Explain a synthetic long prompt " * 20)
    assert unavailable["trace"]["metadata"]["generation_unavailable"]["reason"] == "context_budget_exceeded"
    assert "generation_stats" not in unavailable["trace"]["metadata"]
    assert unavailable["trace"]["metadata"]["model_identity"]["response_model_id"] is None
    assert backend.calls == 1
    assert backend.last_generation_stats == {"generation_tokens": 1, "call_id": 1, "nested": {"call_id": 1}}


def test_completed_draft_identity_does_not_depend_on_stats_availability(tmp_path) -> None:  # noqa: ANN001
    class StatsUnavailableBackend(ReusedBackend):
        def generate(self, messages):  # noqa: ANN001, ANN201
            answer = super().generate(messages)
            self.last_generation_stats = None
            return answer

    store, settings = _runtime(tmp_path)
    backend = StatsUnavailableBackend()
    generated = _turn(tmp_path, store, settings, backend, "Explain crop rotation.")
    metadata = generated["trace"]["metadata"]
    assert generated["answer"] == "Synthetic model output 1."
    assert "generation_stats" not in metadata
    assert metadata["model_identity"]["response_model_id"] == "synthetic-local-model"


class _VerificationOutcome:
    def __init__(self, answer: str, editor_output: str | None) -> None:
        self.answer = answer
        self.editor_output = editor_output
        self.triggered = True
        self.rewrite_accepted = editor_output is not None
        self.fallback_applied = editor_output is None
        self.draft_assessment = SimpleNamespace(reasons=("synthetic_review",))

    def as_record(self):  # noqa: ANN201
        return {
            "triggered": True,
            "rewrite_accepted": self.rewrite_accepted,
            "fallback_applied": self.fallback_applied,
            "intervention_action": "accept_rewrite" if self.rewrite_accepted else "fallback_or_degraded",
            "rejection_reasons": [] if self.rewrite_accepted else ["editor_preflight_return"],
        }


def test_draft_snapshot_survives_editor_and_triggered_preflight_does_not_reuse_editor_stats(
    tmp_path, monkeypatch,  # noqa: ANN001
) -> None:
    store, settings = _runtime(tmp_path)
    backend = ReusedBackend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args, **kwargs: backend)
    editor_calls = 0

    def verify(draft, *, editor, **kwargs):  # noqa: ANN001, ANN202
        nonlocal editor_calls
        del kwargs
        editor_calls += 1
        if editor_calls == 1:
            edited = editor.generate([{"role": "user", "content": "Synthetic editor request."}])
            return _VerificationOutcome(edited, edited)
        return _VerificationOutcome(draft, None)

    monkeypatch.setattr(chat_service, "verify_answer", verify)
    controls = dict(
        mode="agronomic_rag", typed_tools_enabled=False,
        document_retrieval_enabled=False, graph_retrieval_enabled=False,
        risk_intervention_enabled=False,
    )
    first = _turn(tmp_path, store, settings, backend,
                  "What soil health evidence is relevant to soil erosion?", **controls)
    first_metadata = first["trace"]["metadata"]
    assert first["answer"] == "Synthetic model output 2."
    assert first_metadata["generation_stats"]["call_id"] == 1
    assert first_metadata["generation_stats"]["nested"]["call_id"] == 1
    assert first_metadata["answer_verification"]["generation_stats"]["call_id"] == 2
    assert first_metadata["answer_verification"]["generation_stats"]["nested"]["call_id"] == 2
    assert first_metadata["model_identity"]["runtime"]["call_id"] == 1

    second = _turn(tmp_path, store, settings, backend,
                   "Why does soil structure matter for erosion?", **controls)
    second_metadata = second["trace"]["metadata"]
    assert second["answer"] == "Synthetic model output 3."
    assert second_metadata["generation_stats"]["call_id"] == 3
    assert second_metadata["generation_stats"]["nested"]["call_id"] == 3
    assert second_metadata["answer_verification"]["triggered"] is True
    assert "generation_stats" not in second_metadata["answer_verification"]
    assert first_metadata["answer_verification"]["generation_stats"]["nested"]["call_id"] == 2
    assert backend.calls == 3


def test_editor_word_config_forwarded_without_changing_draft_or_token_caps(tmp_path, monkeypatch):
    store, settings = _runtime(tmp_path)
    draft, editor = ReusedBackend(), ReusedBackend()
    draft.max_tokens = editor.max_tokens = 640
    original_load = chat_service.load_model_config
    observed = []
    config_values = iter([512, None, 'absent'])

    def load(path):
        config = deepcopy(original_load(path))
        value = next(config_values)
        if value != 'absent':
            config['answer_verification']['max_words'] = value
        return config

    def verify(answer, *, editor_max_words, editor_max_tokens, **kwargs):
        observed.append((editor_max_words, editor_max_tokens))
        assert kwargs['editor'].max_tokens == 220
        return _VerificationOutcome(answer, None)

    monkeypatch.setattr(chat_service, 'load_model_config', load)
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **kw: editor)
    monkeypatch.setattr(chat_service, 'verify_answer', verify)
    controls = dict(mode='agronomic_rag', typed_tools_enabled=False,
                    document_retrieval_enabled=False, graph_retrieval_enabled=False,
                    risk_intervention_enabled=False)
    for _ in range(3):
        _turn(tmp_path, store, settings, draft, 'Explain soil structure and erosion.', **controls)
        assert draft.max_tokens == 100
    assert observed == [(512, 220), (None, 220), (None, 220)]
    assert draft.calls == 3 and editor.calls == 0


@pytest.mark.parametrize('value', [True, 0, -1, '512', 512.0, 4097])
def test_invalid_editor_word_config_refused_before_any_generator(value, monkeypatch):
    backend = ReusedBackend()
    monkeypatch.setattr(chat_service, 'prepare_turn_question', lambda **kw: {
        'model_config': {'answer_verification': {'max_words': value}},
    })
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **kw: pytest.fail('editor constructed'))
    with pytest.raises(ValueError, match='max_words'):
        chat_service._run_turn_impl(
            store=SimpleNamespace(session_exists=lambda sid: True),
            settings=SimpleNamespace(default_model_id='synthetic-local-model'),
            session_id='synthetic', message='Explain soil structure.', mode='agronomic_rag',
            model_id='synthetic-local-model', rag_config='configs/rag.yaml', max_tokens=100,
            trace_options={}, generation_backend=backend,
        )
    assert backend.calls == 0


def test_all_editor_attempts_remain_observed_when_rejected_unchanged_or_accepted(tmp_path, monkeypatch):
    store, settings = _runtime(tmp_path)
    draft = ReusedBackend()

    class Editor(ReusedBackend):
        max_tokens = 1024
        output = ''

        def generate(self, messages):
            super().generate(messages)
            return self.output

    editor = Editor()
    original_load = chat_service.load_model_config

    def load(path):
        config = deepcopy(original_load(path))
        config['answer_verification'].update(max_tokens=1024, max_words=512)
        return config

    def verify(answer, *, editor_max_words, editor_max_tokens, **kwargs):
        assert (editor_max_words, editor_max_tokens) == (512, 1024)
        editor.output = answer if editor.calls == 1 else 'Synthetic editor output.'
        output = editor.generate([{'role': 'user', 'content': 'Synthetic editor request.'}])
        accepted = editor.calls == 3
        result = _VerificationOutcome(output if accepted else answer, output)
        result.rewrite_accepted = accepted
        result.fallback_applied = False
        return result

    monkeypatch.setattr(chat_service, 'load_model_config', load)
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **kw: editor)
    monkeypatch.setattr(chat_service, 'verify_answer', verify)
    attempts = []
    for index in range(3):
        turn = _turn(tmp_path, store, settings, draft, 'Explain soil structure and erosion.',
                     mode='agronomic_rag', typed_tools_enabled=False,
                     document_retrieval_enabled=False, graph_retrieval_enabled=False,
                     risk_intervention_enabled=False)
        metadata = turn['trace']['metadata']
        assert metadata['generation_stats']['call_id'] == index + 1
        assert metadata['answer_verification']['generation_stats']['call_id'] == index + 1
        assert metadata['answer_verification']['rewrite_accepted'] is (index == 2)
        attempts.append(metadata['generation_stats']['generation_tokens']
                        + metadata['answer_verification']['generation_stats']['generation_tokens'])
    assert attempts == [2, 4, 6]  # All synthetic attempted stage counts, including the two unaccepted edits.
    assert sum(attempts) == 12
    assert draft.calls == editor.calls == 3


def test_editor_observation_actual_service_captures_own_native_shaped_call_before_persistence(tmp_path, monkeypatch):
    """Native-shaped synthetic method stub; no MLX constructor/SDK/load occurs."""
    from dataclasses import replace
    from pathlib import Path
    import hashlib
    import yaml
    from agronomy_agent.agent import MLXGenerator
    from agronomy_agent.execution_core import stable_sha256, validate_execution_stage_receipts
    from agronomy_agent.release_eval_executor import _EditorCheckpoint
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "configs/model.yaml").read_text())
    config.update(model_id="synthetic-editor-model", serving_model_id="synthetic-editor-model", model_revision="b" * 40)
    config["answer_verification"].update(model_id="synthetic-editor-model", model_revision="b" * 40)
    model = tmp_path / "model.yaml"
    model.write_text(yaml.safe_dump(config))
    corpus = tmp_path / "synthetic-corpus.jsonl"
    corpus.write_text("")
    rag = tmp_path / "rag.yaml"
    rag.write_text(yaml.safe_dump({"retrieval": {"corpus_paths": [str(corpus)], "graph_paths": []},
                                  "private_knowledge": {"enabled": False}}))
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    settings = build_settings(db_path=db, artifact_root=tmp_path / "artifacts", model_config_path=str(model),
                              default_rag_config=str(rag), network_mode="offline")
    safe = "Field Alpha soil nitrate record reports 13 mg/kg on a dry-soil basis. This record alone cannot determine an application rate."
    unsafe = safe + " Apply 71 kg/ha immediately."
    class Draft(ReusedBackend):
        def generate(self, messages):
            super().generate(messages)
            return unsafe
    draft = Draft()
    editor = MLXGenerator.__new__(MLXGenerator)
    editor.max_tokens = 640
    editor._context_window_tokens = 32768
    editor._resolved_model_snapshot = tmp_path / "synthetic-snapshot" / ("b" * 40)
    editor.model_identity = {"schema_version": "open_agronomy_agent.model_identity_contract.v1",
        "status": "verified_direct_loader", "backend": "mlx_local", "configured_model_id": "synthetic-editor-model",
        "configured_model_revision": "b" * 40, "model_config_sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
    editor.last_generation_stats = {"finish_reason": "length", "generation_tokens": 220}
    calls = []
    def generate(messages):
        assert editor.last_generation_stats is None
        calls.append(deepcopy(messages))
        editor.last_generation_stats = {"finish_reason": "stop", "generation_tokens": 7,
            "generation_lock_model_id": "synthetic-editor-model", "generation_lock_model_revision": "b" * 40,
            "prompt_cache_enabled": False}
        return " \n" + safe + "\n "
    editor.generate = generate
    editor.count_prompt_tokens = lambda messages: sum(len(item["content"].split()) + 4 for item in messages)
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args, **kwargs: editor)
    question = ("Read only Field Alpha soil nitrate record and preserve its value, unit and basis. Do not recommend a rate. " + safe)
    session = store.create_session("Synthetic editor lifecycle", {}, {})["session_id"]
    request = AgentExecutionRequest(store=store, settings=settings, session_id=session, message=question,
        mode="agronomic_rag", model_id="synthetic-editor-model", rag_config=str(rag), max_tokens=640,
        trace_options={"store_prompt_messages": True}, generation_backend=draft,
        typed_tools_enabled=False, document_retrieval_enabled=False, graph_retrieval_enabled=False,
        risk_intervention_enabled=False, execution_class="observed_system_execution_nonclaim")
    sink = _EditorCheckpoint(tmp_path / "completed-editor.json", {"scope": "synthetic service QA"})
    try:
        result = chat_service.execute_agent_request(request, evaluation_editor_hook=sink)
        observed = sink.read()["observation"]
        metadata = result.turn["trace"]["metadata"]
        assert [event.read()["observation"]["state"] for event in sink.events] == ["dispatch_intent", "returned"]
        assert len(calls) == draft.calls == 1 and editor.max_tokens == 220
        assert observed["identity_status"] == "observed_native_call"  # Stub contract QA only.
        assert observed["raw_output"] == " \n" + safe + "\n "
        assert observed["normalized_output_sha256"] == stable_sha256(safe)
        assert observed["model_identity"]["model_config_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
        assert observed["editor_context_budget"]["reserved_output_tokens"] == 220
        assert observed["editor_context_budget"]["context_limit_tokens"] == 8192
        assert observed["native_observation"]["context_window_tokens"] == 32768
        summary = metadata["answer_verification"]["editor_observation"]
        assert summary["receipt_sha256"] == observed["receipt_sha256"]
        assert not {"raw_output", "prompt_messages", "resolved_snapshot"} & set(summary)
        assert metadata["answer_verification"]["model_identity"] == observed["model_identity"]
        stages = {x["stage_id"]: x for x in validate_execution_stage_receipts(list(result.stage_receipts))}
        assert stages["verification"]["evidence"]["adjudication_sha256"] == stable_sha256(metadata["answer_verification"])
        assert store.count_session_turns(session) == 1
        saved = result.turn["turn_id"]
        failing = store.create_session("Synthetic failed persistence", {}, {})["session_id"]
        late = _EditorCheckpoint(tmp_path / "failed-final-editor.json", {"scope": "synthetic final failure"})
        with monkeypatch.context() as patch:
            patch.setattr(store, "create_turn", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Synthetic final persistence failure")))
            with pytest.raises(OSError, match="Synthetic final persistence failure"):
                chat_service.execute_agent_request(replace(request, session_id=failing), evaluation_editor_hook=late)
        assert late.read()["observation"]["state"] == "returned"
        assert late.read()["observation"]["raw_output"] == observed["raw_output"]
        assert store.count_session_turns(failing) == 0 and store.get_turn(saved)["answer"] == result.answer
        assert observed["generation_stats"] == sink.read()["observation"]["generation_stats"]
        no_call = []
        baseline = store.create_session("Synthetic no editor", {}, {})["session_id"]
        chat_service.execute_agent_request(replace(request, session_id=baseline, mode="baseline",
            document_retrieval_enabled=True, graph_retrieval_enabled=True), evaluation_editor_hook=no_call.append)
        assert len(calls) == 2 and len(no_call) == 1
        assert no_call[0]["state"] == "no_call" and no_call[0]["model_identity"] is None and no_call[0]["generation_stats"] is None
    finally:
        store._conn.close()


def test_canonical_actual_service_owns_lazy_editor_and_retains_provider_return(tmp_path,monkeypatch):
    import hashlib,json,yaml
    from dataclasses import replace
    import test_codex_app_server_egress as fixtures
    import agronomy_agent.codex_app_server as transport
    from agronomy_agent.agent import SOURCE_GROUNDED_SYSTEM_PROMPT
    from agronomy_agent.release_eval_executor import _EditorCheckpoint
    question="A synthetic record describes a shallow layer and another describes a deeper layer. Explain why this distinction matters when comparing the records."
    model=tmp_path/"model.yaml";model.write_text(yaml.safe_dump({"model_id":"gpt-6-luna","model_revision":None,
        "max_tokens":640,"reasoning_effort":"medium","context_management":{"context_limit_tokens":8192},
        "answer_verification":{"enabled":True,"model_id":"gpt-6-luna","max_tokens":220,"mode":"risk_conditioned_selective_v3"}}))
    corpus=tmp_path/"corpus.jsonl";corpus.write_text("")
    rag=tmp_path/"rag.yaml";rag.write_text(yaml.safe_dump({"retrieval":{"corpus_paths":[str(corpus)],"graph_paths":[]},"private_knowledge":{"enabled":False}}))
    store=TraceStore(tmp_path/"synthetic.sqlite3")
    settings=build_settings(db_path=tmp_path/"synthetic.sqlite3",artifact_root=tmp_path/"artifacts",model_config_path=str(model),default_rag_config=str(rag),network_mode="offline")
    instances=[];closed=[]
    class Client:
        def __init__(self,**kwargs):self.role=len(instances);instances.append(self)
        def generate(self,**kwargs):
            self.role=0 if kwargs["metadata"]["role"]=="candidate_generation" else 1
            text="Apply 71 kg/ha immediately." if self.role==0 else "Different sample depths can limit comparison; those records alone cannot justify an application rate."
            return fixtures.AppServerResult(text=text,receipt={"selected_model":"gpt-6-luna","output_sha256":hashlib.sha256(text.encode()).hexdigest(),
                "input_sha256":hashlib.sha256(kwargs["user_text"].encode()).hexdigest(),
                "base_instructions_sha256":hashlib.sha256((fixtures.TEXT_ONLY_BENCHMARK_CONTROL+"\n\n"+kwargs["base_instructions"].strip()).encode()).hexdigest(),
                "token_usage":{"last":{"inputTokens":10,"outputTokens":9}},"thread_id":f"thread-{self.role}","turn_id":f"turn-{self.role}",
                "finish_reason":None,"hard_output_cap_supported":False,"effective_turn_reasoning_effort_observed":False})
        def close(self):closed.append(self.role);return {"status":"synthetic_closed","remote_cancellation_confirmed":None}
    monkeypatch.setattr(transport,"CodexAppServerClient",Client)
    monkeypatch.setattr(chat_service,"_build_mlx_generator",lambda *a,**k:pytest.fail("no native construction"))
    # Freeze actual compiled messages before granting fake transport access.
    # The borrowed capture backend stops before producing a draft/editor call.
    class Captured(BaseException):pass
    captured={};contexts=[]
    real_context=chat_service.build_context
    def observe_context(*args,**kwargs):
        value=real_context(*args,**kwargs);contexts.append(value);return value
    monkeypatch.setattr(chat_service,"build_context",observe_context)
    class Capture:
        model_id="gpt-6-luna"
        def generate(self,messages):captured["messages"]=deepcopy(messages);raise Captured()
    preview=AgentExecutionRequest(store=store,settings=settings,
        session_id=store.create_session("synthetic prospective compile",{}, {})["session_id"],
        message=question,mode="agronomic_rag",model_id="gpt-6-luna",rag_config=str(rag),max_tokens=640,
        generation_backend=Capture(),execution_class="observed_system_execution_nonclaim")
    with pytest.raises(Captured):chat_service.execute_agent_request(preview)
    messages=captured["messages"]
    expected_evidence=chat_service._combined_verification_evidence(contexts[-1],None)[:9000]
    made=[]
    def factory(phase):
        def create():
            made.append(phase)
            return fixtures._canonical_generator(tmp_path/phase,question=question,messages=messages,phase=phase,
                evidence=expected_evidence,config_sha=hashlib.sha256(model.read_bytes()).hexdigest(),config_path=model,max_tokens=640 if phase=="candidate_generation" else 220)
        return create
    request=AgentExecutionRequest(store=store,settings=settings,session_id=store.create_session("synthetic",{}, {})["session_id"],message=question,
        mode="agronomic_rag",model_id="gpt-6-luna",rag_config=str(rag),max_tokens=640,execution_class="observed_system_execution_nonclaim",
        generation_backend_factory=factory("candidate_generation"),verification_backend_factory=factory("verification"),benchmark_eval_id=fixtures._EVAL_ID,
        trace_options={"store_prompt_messages":True})
    sink=_EditorCheckpoint(tmp_path/"editor.json",{"scope":"synthetic canonical service"})
    try:
        result=chat_service.execute_agent_request(request,evaluation_editor_hook=sink)
        assert result.execution_class=="observed_system_execution_nonclaim" and result.owned_backend_closeout
        assert all(request.arm_configuration.to_dict()[key] is True for key in request.arm_configuration.to_dict() if key.endswith("_enabled"))
        observation=sink.read()["observation"]
        assert observation["state"]=="returned" and observation["identity_status"]=="unknown"
        assert observation["native_observation"] is None and observation["provider_observation"]["model_revision"] is None
        assert observation["provider_observation"]["finish_reason"] is None
        assert sink.read()["observation"]["generation_stats"]["request_model_id"]=="gpt-6-luna"
        assert closed==[1,0] and made==["candidate_generation","verification"]
        saved=result.turn_id
        failed_session=store.create_session("synthetic failed persistence",{}, {})["session_id"]
        late=_EditorCheckpoint(tmp_path/"late-editor.json",{"scope":"synthetic failed persistence"})
        monkeypatch.setattr(store,"create_turn",lambda *a,**k:(_ for _ in ()).throw(OSError("synthetic persistence")))
        with pytest.raises(OSError,match="persistence") as caught:
            chat_service.execute_agent_request(replace(request,session_id=failed_session),evaluation_editor_hook=late)
        assert late.read()["observation"]["state"]=="returned"
        assert store.get_turn(saved)["answer"]==result.answer and closed==[1,0,1,0]
        assert caught.value.evaluation_backend_closeout
    finally:store._conn.close()


def test_canonical_deterministic_bypass_constructs_and_closes_no_backend(tmp_path,monkeypatch):
    from dataclasses import replace
    from test_release_eval_executor import _hook_runtime
    store,request,_,_,_=_hook_runtime(tmp_path,question="Calculate daily GDD from Tmax 26 C, Tmin 16 C and base 10 C. Do not infer crop stage.",mode="agronomic_rag",verification=True)
    def fail():pytest.fail("deterministic bypass must not construct backend")
    request=replace(request,generation_backend=None,generation_backend_factory=fail,verification_backend_factory=fail,benchmark_eval_id="synthetic",
        document_retrieval_enabled=True,graph_retrieval_enabled=True,field_context_enabled=True,typed_tools_enabled=True,
        risk_intervention_enabled=True,verifier_enabled=True,fallback_enabled=True)
    try:
        result=chat_service.execute_agent_request(request)
        assert result.answer and not result.owned_backend_closeout
    finally:store._conn.close()
