from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


class _ReferenceStoreFixture:
    """Tiny store seam for telemetry units; persistence has separate controls."""
    def __init__(self, *_args):
        self.rows = {}
        self._conn = SimpleNamespace(close=lambda: None)

    def create_session(self, *_args):
        return {"session_id": "synthetic-session"}

    def create_turn(self, session_id, question, answer, **kwargs):
        key = str(len(self.rows) + 1)
        self.rows[key] = {"answer": answer, "question": question, **kwargs}
        return key

    def get_turn(self, key):
        return self.rows[key]

    def count_session_turns(self, _session_id):
        return len(self.rows)


def test_development_nested_cell_failure_retains_actual_leaf(tmp_path, monkeypatch):
    import agronomy_agent.release_eval_executor as executor
    monkeypatch.setattr(executor, "TraceStore", _ReferenceStoreFixture)

    def fail(*_args, **_kwargs):
        raise ExceptionGroup("Synthetic outer failure", [ValueError("Synthetic inner fault")])

    monkeypatch.setattr(executor, "_production_turn", fail)
    result = run(tmp_path, case(question="Explain a synthetic soil observation."))
    assert result["status"] == "failed"
    evidence = result["turns"][0]["error"]["exception_evidence"]
    assert any(node["type"] == "ValueError" and node["message"] == "Synthetic inner fault"
               for node in evidence["nodes"])


def test_development_exception_evidence_is_bounded_under_actual_result_encoding():
    from agronomy_agent.release_eval_executor import exception_evidence
    error = ExceptionGroup("Synthetic root", [ValueError("水" * 10000) for _ in range(40)])
    evidence = exception_evidence(error)
    encoded = json.dumps({"turns": [{"error": {"exception_evidence": evidence}}]},
                         indent=2, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= 4096
    assert len(evidence["nodes"]) <= 12
    assert evidence["truncated"] is True


def test_development_hostile_exception_message_and_cause_cycle_are_safe():
    from agronomy_agent.release_eval_executor import exception_evidence
    class BadMessage(Exception):
        def __str__(self):
            raise RuntimeError("Synthetic message failure")
    error = BadMessage()
    error.__cause__ = error
    evidence = exception_evidence(error)
    assert evidence["nodes"][0]["type"] == "BadMessage"
    assert evidence["message_errors"] is True
    assert evidence["truncated"] is True


def test_development_cancel_group_is_retained_then_propagated(tmp_path, monkeypatch):
    import agronomy_agent.release_eval_executor as executor
    monkeypatch.setattr(executor, "TraceStore", _ReferenceStoreFixture)
    original = BaseExceptionGroup("Synthetic cancelled group", [KeyboardInterrupt("Synthetic cancellation")])
    def fail(*_args, **_kwargs):
        raise original
    monkeypatch.setattr(executor, "_production_turn", fail)
    with pytest.raises(BaseExceptionGroup) as caught:
        run(tmp_path, case(question="Explain a synthetic soil observation."))
    assert caught.value is original
    saved = json.loads(next(tmp_path.glob("*/result.json")).read_text())
    assert saved["status"] == "interrupted"
    assert saved["turns"][0]["status"] == "interrupted"
    assert any(row["type"] == "KeyboardInterrupt" for row in saved["turns"][0]["error"]["exception_evidence"]["nodes"])


def _completed_draft_fixture():
    return {"schema_version": "open_agronomy_agent.completed_draft_observation.v1",
            "draft": "Synthetic completed draft.",
            "prompt_messages": [{"role": "user", "content": "Synthetic supplied task."}],
            "generation_stats": {"finish_reason": "stop", "generation_tokens": 7},
            "model_identity": {"status": "synthetic_fixture"}, "context_budget": None}


def test_development_completed_draft_checkpoint_is_exclusive_detached_and_verified(tmp_path):
    from agronomy_agent.release_eval_executor import _DraftCheckpoint
    bindings = {"case_sha256": "a" * 64, "turn_index": 1}
    sink = _DraftCheckpoint(tmp_path / "draft.json", bindings)
    observed = _completed_draft_fixture()
    sink(observed)
    observed["generation_stats"]["finish_reason"] = "length"
    bindings["turn_index"] = 99
    assert sink.read()["observation"]["generation_stats"]["finish_reason"] == "stop"
    assert sink.read()["bindings"]["turn_index"] == 1
    assert sink.receipt()["status"] == "retained"
    with pytest.raises(ValueError, match="reused"):
        sink(_completed_draft_fixture())
    sink.path.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        sink.read()


def test_development_checkpoint_unknown_terminal_stays_unknown_and_is_not_final(tmp_path):
    from agronomy_agent.release_eval_executor import _DraftCheckpoint, generation_termination
    sink = _DraftCheckpoint(tmp_path / "draft.json", {})
    observed = _completed_draft_fixture()
    observed["generation_stats"] = None
    sink(observed)
    assert generation_termination(sink.read()["observation"]["generation_stats"])["status"] == "unknown"
    assert "final" not in sink.read()


def test_development_checkpoint_file_failure_preserves_existing_bytes(tmp_path):
    from agronomy_agent.release_eval_executor import _DraftCheckpoint
    path = tmp_path / "draft.json"
    path.write_bytes(b"original synthetic evidence")
    sink = _DraftCheckpoint(path, {})
    with pytest.raises(FileExistsError):
        sink(_completed_draft_fixture())
    assert path.read_bytes() == b"original synthetic evidence"
    assert sink.receipt()["status"] == "unavailable"


def test_development_checkpoint_refuses_oversized_observation_before_output(tmp_path):
    from agronomy_agent.release_eval_executor import _DraftCheckpoint
    sink = _DraftCheckpoint(tmp_path / "draft.json", {})
    observed = _completed_draft_fixture()
    observed["draft"] = "x" * 262144
    with pytest.raises(ValueError, match="256 KiB"):
        sink(observed)
    assert not sink.path.exists()


class _HookBackendFixture:
    backend_id = "synthetic_completed_draft_fixture"

    def __init__(self):
        self.calls = 0
        self.attempts = 0
        self.last_generation_stats = None
        self.generation_stats_call_id = 0
        self.model_identity = {"configured_model_id": "synthetic-evaluation-model",
                               "configured_model_revision": "synthetic-revision",
                               "status": "synthetic_fixture"}

    def count_prompt_tokens(self, messages):
        return sum(len(item["content"].split()) + 4 for item in messages)

    def generate(self, _messages):
        self.attempts += 1
        if getattr(self, "fail", False):
            raise RuntimeError("Synthetic unavailable backend")
        self.calls += 1
        self.generation_stats_call_id += 1
        self.last_generation_stats = {"finish_reason": "stop", "generation_tokens": 7,
                                      "generation_stats_call_id": self.generation_stats_call_id,
                                      "synthetic": True}
        return "Synthetic supplied observation remains uncertain."


def _hook_runtime(tmp_path, *, question="Explain the supplied soil observation.", mode="baseline", verification=False):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    model = tmp_path / "model.yaml"
    model.write_text(yaml.safe_dump({
        "model_id": "synthetic-evaluation-model", "model_revision": "synthetic-revision",
        "max_tokens": 100, "context_management": {"context_limit_tokens": 8192},
        "answer_verification": {"enabled": verification, "max_tokens": 60},
    }))
    corpus = tmp_path / "synthetic-corpus.jsonl"
    corpus.write_text("")
    rag = tmp_path / "rag.yaml"
    rag.write_text(yaml.safe_dump({"retrieval": {"corpus_paths": [str(corpus)], "graph_paths": []},
                                  "private_knowledge": {"enabled": False}}))
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    settings = build_settings(db_path=db, artifact_root=tmp_path / "artifacts",
                              model_config_path=str(model), default_rag_config=str(rag),
                              network_mode="offline")
    session = store.create_session("Synthetic hook control", {}, {})
    backend = _HookBackendFixture()
    request = AgentExecutionRequest(store=store, settings=settings, session_id=session["session_id"],
                                    message=question, mode=mode, model_id="synthetic-evaluation-model",
                                    rag_config=str(rag), max_tokens=100,
                                    generation_backend=backend, trace_options={"store_prompt_messages": True},
                                    risk_intervention_enabled=False,
                                    execution_class="observed_system_execution_nonclaim")
    return store, request, backend, model, rag


def test_development_service_hook_default_and_detached_capture_preserve_success(tmp_path):
    from dataclasses import replace
    from agronomy_agent.server.services import chat_service
    store, request, backend, _, _ = _hook_runtime(tmp_path)
    captured = []
    try:
        first = chat_service.execute_agent_request(request)
        next_session = store.create_session("Synthetic second control", {}, {})
        second_request = replace(request, session_id=next_session["session_id"])
        def capture(observation):
            captured.append(deepcopy(observation))
            observation["generation_stats"]["finish_reason"] = "length"
            observation["prompt_messages"].clear()
        second = chat_service.execute_agent_request(second_request, evaluation_draft_hook=capture)
        assert first.answer == second.answer
        assert len(captured) == 1 and backend.calls == 2
        assert captured[0]["draft"] == second.turn["trace"]["metadata"]["answer_stages"]["draft"]["text"]
        assert second.turn["trace"]["metadata"]["generation_stats"]["finish_reason"] == "stop"
        assert second.turn["trace"]["prompt_messages"]
    finally:
        store._conn.close()


def test_development_service_hook_invalid_refused_before_store_or_generation():
    from agronomy_agent.server.services import chat_service
    with pytest.raises(TypeError, match="callable or None"):
        chat_service.execute_agent_request(None, evaluation_draft_hook=1)


def test_development_service_hook_failure_precedes_verification_without_retry(tmp_path, monkeypatch):
    from agronomy_agent.server.services import chat_service
    store, request, backend, _, _ = _hook_runtime(tmp_path, mode="agronomic_rag", verification=True)
    monkeypatch.setattr(chat_service, "verify_answer", lambda *_a, **_k: pytest.fail("verification must not start"))
    def fail(_observation):
        raise OSError("Synthetic checkpoint failure")
    try:
        with pytest.raises(OSError, match="Synthetic checkpoint"):
            chat_service.execute_agent_request(request, evaluation_draft_hook=fail)
        assert backend.calls == 1
        assert store.count_session_turns(request.session_id) == 0
    finally:
        store._conn.close()


@pytest.mark.parametrize("question", [
    "Calculate daily GDD from Tmax 26 C, Tmin 16 C and base 10 C. Do not infer crop stage.",
    "Calculate daily GDD from Tmax 26 C, Tmin 16 C.",
])
def test_development_deterministic_service_never_generates_or_calls_hook(tmp_path, question):
    from agronomy_agent.server.services import chat_service
    store, request, backend, _, _ = _hook_runtime(tmp_path, question=question, mode="agronomic_rag")
    try:
        result = chat_service.execute_agent_request(request, evaluation_draft_hook=lambda _: pytest.fail("bypass observed as generation"))
        assert backend.calls == 0
        assert result.turn["trace"]["metadata"]["generation_bypass"]
    finally:
        store._conn.close()


@pytest.mark.parametrize("fault", ["verification", "persistence"])
def test_development_full_cell_retains_draft_and_nested_downstream_failure(tmp_path, monkeypatch, fault):
    import agronomy_agent.release_eval_executor as executor
    store, request, backend, model, rag = _hook_runtime(tmp_path, mode="agronomic_rag", verification=fault == "verification")
    store._conn.close()
    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "http")
    monkeypatch.setattr(executor.chat_service, "_build_mlx_generator", lambda *_a, **_k: backend)
    if fault == "verification":
        def fail_verification(*_a, **_k):
            assert list(tmp_path.glob("cells/*/turn-1-completed-draft.json"))
            raise ExceptionGroup("Synthetic verification wrapper", [ValueError("Synthetic verification leaf")])
        monkeypatch.setattr(executor.chat_service, "verify_answer", fail_verification)
    else:
        def fail_persistence(*_a, **_k):
            raise ExceptionGroup("Synthetic persistence wrapper", [OSError("Synthetic persistence leaf")])
        monkeypatch.setattr(executor.TraceStore, "create_turn", fail_persistence)
    result = executor.execute_product_case(case(question=request.message), model_config=model, rag_config=rag,
                                           backend="mlx", output_dir=tmp_path / "cells")
    assert result["status"] == "failed"
    turn = result["turns"][0]
    assert turn["draft"] == "Synthetic supplied observation remains uncertain."
    assert turn["answer"] is None and turn["final"] is None
    assert turn["draft_checkpoint"]["status"] == "retained"
    assert turn["generation_stats"]["finish_reason"] == "stop"
    assert any(node["message"] == f"Synthetic {fault} leaf" for node in turn["error"]["exception_evidence"]["nodes"])
    if fault == "verification":
        assert turn["termination"]["status"] == "unknown"
        assert turn["termination"]["stages"][1]["attempt_observation"] == "unknown"
    assert backend.calls == 1


def test_development_raw_cell_retains_completed_draft_when_persistence_fails(tmp_path, monkeypatch):
    import agronomy_agent.release_eval_executor as executor
    store, request, backend, model, rag = _hook_runtime(tmp_path)
    store._conn.close()
    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "http")
    monkeypatch.setattr(executor.chat_service, "_build_mlx_generator", lambda *_a, **_k: backend)
    def fail(*_a, **_k):
        raise OSError("Synthetic raw persistence failure")
    monkeypatch.setattr(executor.TraceStore, "create_turn", fail)
    result = executor.execute_product_case(case(question=request.message), model_config=model, rag_config=rag,
                                           backend="mlx", arm_id="raw_model", output_dir=tmp_path / "cells")
    turn = result["turns"][0]
    assert result["status"] == "failed" and backend.calls == 1
    assert turn["draft"] == "Synthetic supplied observation remains uncertain."
    assert turn["final"] is None and turn["answer"] is None
    assert turn["generation_stats"]["finish_reason"] == "stop"
    assert turn["draft_checkpoint"]["status"] == "retained"
    assert turn["stage_receipts"] == []
    assert turn["termination"]["stages"][0]["stage"] == "reference"
    assert turn["generation_origin"] == "execution_failed"


def test_development_raw_checkpoint_fsync_failure_stops_before_another_turn(tmp_path, monkeypatch):
    import agronomy_agent.release_eval_executor as executor
    backend = _HookBackendFixture()
    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "http")
    monkeypatch.setattr(executor, "TraceStore", _ReferenceStoreFixture)
    monkeypatch.setattr(executor.chat_service, "_build_mlx_generator", lambda *_a, **_k: backend)
    def fail_sync(_fd):
        raise OSError("Synthetic checkpoint flush failure")
    monkeypatch.setattr(executor.os, "fsync", fail_sync)
    row = case()
    row.pop("question")
    row["turns"] = ["Explain synthetic observation one.", "Explain synthetic observation two."]
    result = run(tmp_path, row, backend="mlx", arm_id="raw_model")
    assert result["status"] == "failed"
    assert backend.calls == 1 and len(result["turns"]) == 1
    assert result["turns"][0]["draft_checkpoint"]["status"] == "unavailable"
    assert "Synthetic checkpoint flush failure" in result["turns"][0]["error"]["message"]


@pytest.mark.parametrize("original", [KeyboardInterrupt("Synthetic interrupt"), SystemExit(7)])
def test_development_closeout_write_failure_cannot_replace_pending_control_flow(tmp_path, monkeypatch, original):
    import agronomy_agent.release_eval_executor as executor
    monkeypatch.setattr(executor, "TraceStore", _ReferenceStoreFixture)
    def fail(*_a, **_k):
        raise original
    monkeypatch.setattr(executor, "_production_turn", fail)
    old_write = Path.write_text
    def reject_result(path, *args, **kwargs):
        if path.name == "result.json":
            raise OSError("Synthetic unwritable closeout")
        return old_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", reject_result)
    with pytest.raises(type(original)) as caught:
        run(tmp_path, case(question="Explain a synthetic soil observation."))
    assert caught.value is original
    assert original.evaluation_closeout_error["type"] == "OSError"
    assert "Synthetic unwritable closeout" in original.__notes__[-1]
    assert len(original.__notes__[-1].encode("utf-8")) <= 4096


def test_development_fallback_does_not_publish_a_completed_draft_observation(tmp_path):
    from agronomy_agent.server.services import chat_service
    store, request, backend, _, _ = _hook_runtime(tmp_path)
    backend.fail = True
    try:
        result = chat_service.execute_agent_request(request, evaluation_draft_hook=lambda _: pytest.fail("fallback observed as generation"))
        assert backend.attempts == 1 and backend.calls == 0
        assert result.turn["trace"]["metadata"]["generation_fallback"]
    finally:
        store._conn.close()


def test_development_operation_replay_does_not_call_completed_draft_hook_again(tmp_path):
    from dataclasses import replace
    from uuid import uuid4
    from agronomy_agent.server.services import chat_service
    store, request, backend, _, _ = _hook_runtime(tmp_path)
    request = replace(request, client_operation_id=str(uuid4()), operation_request_sha256="d" * 64)
    observations = []
    try:
        first = chat_service.execute_agent_request(request, evaluation_draft_hook=observations.append)
        second = chat_service.execute_agent_request(request, evaluation_draft_hook=observations.append)
        assert first.answer == second.answer
        assert backend.calls == 1 and len(observations) == 1
    finally:
        store._conn.close()


def test_distinct_draft_editor_and_unknown_termination():
    from agronomy_agent.release_eval_executor import observation_termination
    turn = {"generation_stats": {"finish_reason": "stop", "generation_tokens": 100},
            "editor_generation_stats": {"finish_reason": "length"},
            "metadata": {"answer_verification": {"rewrite_accepted": True}}}
    result = observation_termination([turn])
    assert [stage["finish_reason"] for stage in result["stages"]] == ["stop", "length"]
    assert result["truncated"] is True
    del turn["editor_generation_stats"]["finish_reason"]
    result = observation_termination([turn])
    assert result["truncated"] is None and result["status"] == "unknown"
    bypass = observation_termination([{"metadata": {"generation_bypass": {"reason": "calculator"}}}])
    assert bypass["status"] == "not_applicable"


def test_reference_does_not_reuse_unchanged_provider_stats(tmp_path):
    from agronomy_agent.release_eval_executor import _reference_turn
    store = _ReferenceStoreFixture()
    session = store.create_session("Synthetic", {}, {})
    class Backend:
        last_generation_stats = {"finish_reason": "length"}
        def generate(self, messages):
            return "Synthetic answer"
    turn = _reference_turn("Synthetic question", arm_id="raw_model", generator=Backend(),
                           store=store, session_id=session["session_id"], history=[])
    assert turn["generation_stats"] is None
    store._conn.close()


@pytest.mark.parametrize("output", ["Rejected synthetic rewrite", "", "Same synthetic draft"])
def test_rejected_or_unchanged_editor_output_requires_terminal(output):
    from agronomy_agent.release_eval_executor import observation_termination
    turn = {"generation_stats": {"finish_reason": "stop"},
            "editor": {"triggered": True, "rewrite_accepted": False, "editor_output": output}}
    result = observation_termination([turn])
    assert result["stages"][1]["required"] is True
    assert result["stages"][1]["status"] == "unknown"
    assert result["status"] == "unknown" and result["truncated"] is None
    turn["editor"]["editor_output"] = None
    assert observation_termination([turn])["stages"][1]["status"] == "not_applicable"


@pytest.mark.parametrize("marker", [None, True, "1", 0, -1])
def test_reference_copied_stale_receipt_is_unknown(tmp_path, marker):
    from agronomy_agent.release_eval_executor import _reference_turn
    store = _ReferenceStoreFixture()
    session = store.create_session("Synthetic", {}, {})
    class Backend:
        generation_stats_call_id = marker
        cached = {"finish_reason": "length", "generation_tokens": 2}
        last_generation_stats = cached.copy()
        def generate(self, messages):
            self.last_generation_stats = self.cached.copy()
            return "Synthetic answer"
    backend = Backend()
    turn = _reference_turn("Synthetic request", arm_id="raw_model", generator=backend,
                           store=store, session_id=session["session_id"], history=[])
    assert turn["generation_stats"] is None
    assert turn["reference_receipt"]["generation_stats_freshness"] == "unknown"
    store._conn.close()


def test_reference_fresh_equal_values_supported_and_marked(tmp_path, monkeypatch):
    import agronomy_agent.release_eval_executor as executor
    store = _ReferenceStoreFixture()
    session = store.create_session("Synthetic", {}, {})
    monkeypatch.setattr(executor.time, "monotonic", lambda: 0.0)
    backend = executor._RecordedMock()
    def call(generator):
        return executor._reference_turn("Synthetic request", arm_id="raw_model", generator=generator,
                                        store=store, session_id=session["session_id"], history=[])
    first, second = call(backend), call(backend)
    assert first["generation_stats"] == second["generation_stats"]
    assert first["generation_stats"] is not second["generation_stats"]
    assert second["reference_receipt"]["generation_stats_freshness"] == "supported_call_scoped_provider"
    class Marked:
        generation_stats_call_id = 0
        last_generation_stats = None
        def generate(self, messages):
            assert self.last_generation_stats is None
            self.generation_stats_call_id += 1
            self.last_generation_stats = {"finish_reason": "stop", "generation_tokens": 2,
                                          "generation_stats_call_id": self.generation_stats_call_id}
            return "Synthetic answer"
    marked = Marked()
    one, two = call(marked), call(marked)
    assert one["generation_stats"]["finish_reason"] == two["generation_stats"]["finish_reason"] == "stop"
    assert one["generation_stats"]["generation_stats_call_id"] == 1
    assert two["generation_stats"]["generation_stats_call_id"] == 2
    assert two["reference_receipt"]["generation_stats_freshness"] == "advanced_call_marker"
    store._conn.close()


def test_reference_failure_keeps_cleared_stats_unknown(tmp_path):
    import agronomy_agent.release_eval_executor as executor
    store = _ReferenceStoreFixture()
    session = store.create_session("Synthetic", {}, {})
    class Backend:
        last_generation_stats = {"finish_reason": "length"}
        def generate(self, messages):
            raise RuntimeError("Synthetic failure")
    backend = Backend()
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        executor._reference_turn("Synthetic request", arm_id="raw_model", generator=backend,
                                  store=store, session_id=session["session_id"], history=[])
    assert backend.last_generation_stats is None
    store._conn.close()
import yaml

from agronomy_agent.execution_core import EXECUTION_STAGE_IDS, stable_sha256
from agronomy_agent.release_eval_executor import (
    compile_case_field_context,
    execute_product_case,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "data/eval/release_harness_v1.jsonl").read_text().splitlines()
]


def case(**updates):
    return {
        "case_id": "synthetic-probe",
        "scenario_family": "numeric_complete",
        "lane": "harness",
        "question": "Convert 100 lb/ac to kg/ha.",
        "field_context": {},
        "assertions": {},
        "review_required": False,
        **updates,
    }


def run(tmp_path, row=None, **kwargs):
    return execute_product_case(
        row or case(),
        model_config=ROOT / "configs/model.yaml",
        rag_config=ROOT / "configs/rag.yaml",
        output_dir=tmp_path,
        **kwargs,
    )


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["case_id"])
def test_synthetic_scenarios_have_observed_product_receipts(tmp_path, row):
    result = run(tmp_path, row)
    assert result["status"] == "completed", result.get("error")
    assert result["failed_checks"] == []
    assert result["model_execution_eligible"] is False
    assert result["claim_eligible"] is False
    for turn in result["turns"]:
        assert [receipt["stage_id"] for receipt in turn["stage_receipts"]] == list(
            EXECUTION_STAGE_IDS
        )
        assert turn["profiler_spans"]
        assert turn["peak_memory_bytes"] is None
        assert turn["persisted_turn"]["answer"] == turn["answer"]
    if row["review_required"]:
        assert "semantic_review" in {item["id"] for item in result["unknown"]}


def test_numeric_binding_retains_exact_result_and_never_calls_mock(tmp_path):
    row = case(
        scoring={"reference_numeric": 9999, "reference_unit": "wrong", "tolerance": 0}
    )
    result = run(tmp_path, row)
    turn = result["turns"][0]
    tool_result = turn["tool_results"][0]
    assert tool_result["payload"]["value"] == pytest.approx(112.0851156)
    assert tool_result["payload_sha256"] == stable_sha256(tool_result["payload"])
    assert turn["draft"] == tool_result["payload"]["answer"]
    assert result["backend_calls"] == []
    assert {
        "turn_1.tool_results_bound",
        "turn_1.tool_payloads_bound",
        "turn_1.tool_answer_used",
    }.issubset({row["id"] for row in result["checks"] if row["passed"]})
    assert "9999" not in json.dumps(turn["prompt_messages"])
    assert any(row["id"] == "answer_scoring" for row in result["unknown"])


def test_multiturn_reference_uses_persisted_user_history_and_scope(tmp_path):
    row = case()
    row.pop("question")
    row.update(
        turns=[
            {"content": "Convert 100 lb/ac to kg/ha."},
            "What about 200 instead?",
            "300 instead?",
        ]
    )
    result = run(tmp_path, row)
    assert result["failed_checks"] == []
    first, second, third = result["turns"]
    assert (
        second["metadata"]["conversation_resolution"]["source_turn_id"]
        == first["turn_id"]
    )
    assert (
        third["metadata"]["conversation_resolution"]["source_turn_id"]
        == second["turn_id"]
    )
    assert third["metadata"]["conversation_resolution"]["chain_depth"] == 2
    assert third["tool_results"][0]["payload"]["inputs"]["value"] == 300
    fresh = run(tmp_path / "fresh", case(question="What about 200 instead?"))
    assert fresh["session_id"] != result["session_id"]
    assert (
        fresh["turns"][0]["metadata"]["conversation_resolution"]["status"]
        == "no_antecedent"
    )


def test_field_aliases_reach_compiler_and_conflicts_fail_without_erasure(tmp_path):
    compiled, receipt = compile_case_field_context(
        {"crop_name": "canola", "crop": "wheat", "region_text": "Alberta"}
    )
    assert compiled["crop"] == "wheat"
    assert compiled["crop_name"] == "canola"
    assert compiled["region"] == "Alberta"
    assert receipt["conflicts"][0]["canonical"] == "crop"
    result = run(
        tmp_path,
        case(
            question="What observations should I collect?",
            field_context={"crop_name": "canola", "crop": "wheat"},
        ),
    )
    assert result["status"] == "completed"
    assert result["failed_checks"][0]["id"] == "field_aliases_unambiguous"
    assert (
        result["turns"][0]["metadata"]["field_context_compiler"]["field"]["crop"]
        == "wheat"
    )


@pytest.mark.parametrize(
    ("arm", "stages"),
    [
        ("retrieval_neither", ["document_retrieval", "graph_retrieval"]),
        ("full_minus_typed_tools", ["tool_planning", "tool_execution"]),
        ("full_minus_field_context", ["typed_field_context"]),
        ("full_minus_verifier", ["verification"]),
    ],
)
def test_direct_product_controls_preserve_disabled_stage_receipts(
    tmp_path, arm, stages
):
    result = run(tmp_path, arm_id=arm)
    assert result["status"] == "completed"
    assert result["failed_checks"] == []
    receipts = {row["stage_id"]: row for row in result["turns"][0]["stage_receipts"]}
    assert all(receipts[stage]["state"] == "disabled_by_arm" for stage in stages)


@pytest.mark.parametrize("arm", ["raw_model", "kernel_only"])
def test_reference_arms_use_generator_and_never_fabricate_topology(tmp_path, arm):
    result = run(tmp_path, case(question="Explain soil texture."), arm_id=arm)
    assert result["status"] == "completed"
    turn = result["turns"][0]
    assert result["backend_calls"][0]["status"] == "completed"
    assert turn["stage_receipts"] == []
    assert turn["execution_kind"] == "ungoverned_reference"
    assert turn["reference_receipt"]["topology_receipts_present"] is False
    assert [message["role"] for message in turn["prompt_messages"]] == (
        ["system", "user"] if arm == "kernel_only" else ["user"]
    )
    assert turn["persisted_turn"]["answer"] == turn["answer"]
    assert result["model_execution_eligible"] is False


def test_unrecovered_mock_fault_remains_failed_without_complete_topology(tmp_path):
    row = case(
        scenario_family="backend_faults",
        question="Explain crop rotation.",
        synthetic_fault={"kind": "backend_unavailable", "fail_calls": 1},
    )
    result = run(tmp_path, row, arm_id="full_minus_fallback")
    assert result["status"] == "failed"
    turn = result["turns"][0]
    assert turn["status"] == "failed"
    assert turn["error"]["type"] == "SyntheticBackendUnavailable"
    assert turn["answer"] is None
    assert turn["stage_receipts"] == []
    assert turn["persistence_observation"]["session_turn_count"] == 0
    assert any(span["status"] == "error" for span in turn["profiler_spans"])
    assert result["failed_checks"]
    assert (
        json.loads((Path(result["artifact_dir"]) / "result.json").read_text())["status"]
        == "failed"
    )


def test_recovered_mock_fault_has_truthful_fallback_origin_and_calls(tmp_path):
    row = deepcopy(next(row for row in CASES if row["case_id"] == "HR1-fault-recovery"))
    result = run(tmp_path, row)
    first, second = result["turns"]
    first_receipts = {row["stage_id"]: row for row in first["stage_receipts"]}
    assert first_receipts["draft_generation"]["state"] != "completed"
    assert (
        first_receipts["fallback_origin"]["evidence"]["origin_class"]
        == "analysis_unavailable_fallback"
    )
    assert first["generation_stats"] is None
    assert second["generation_stats"]["synthetic"] is True
    assert [row["status"] for row in result["backend_calls"]] == ["failed", "completed"]
    assert result["model_execution_eligible"] is False


def test_fault_injection_rejects_real_model_and_nonfault_case_before_execution(
    tmp_path,
):
    row = case(synthetic_fault={"kind": "backend_unavailable", "fail_calls": 1})
    for backend in ("mock", "mlx"):
        result = run(tmp_path / backend, row, backend=backend)
        assert result["status"] == "failed"
        assert "synthetic_fault requires" in result["error"]["message"]
        assert result["turns"] == []


def test_unknown_mechanical_assertion_fails_and_semantic_review_stays_unknown(tmp_path):
    result = run(
        tmp_path,
        case(
            assertions={
                "unimplemented_mechanical_contract": True,
                "semantic_assertions": ["valid agronomic recommendation"],
            },
            review_required=True,
        ),
    )
    assert result["status"] == "completed"
    assert [row["id"] for row in result["failed_checks"]] == [
        "unimplemented_mechanical_contract"
    ]
    assert {
        "unimplemented_mechanical_contract",
        "semantic_assertions",
        "semantic_review",
    }.issubset({row["id"] for row in result["unknown"]})


def test_existing_cell_is_immutable_and_invalid_cases_retained(tmp_path):
    original = run(tmp_path)
    path = Path(original["artifact_dir"]) / "result.json"
    before = path.read_bytes()
    repeated = run(tmp_path)
    assert repeated["status"] == "failed"
    assert repeated["error"]["type"] == "FileExistsError"
    assert path.read_bytes() == before
    invalid = run(tmp_path / "invalid", case(question=""))
    assert invalid["status"] == "failed"
    assert invalid["turns"] == []
    assert invalid["failed_checks"]


@pytest.mark.parametrize(
    ("transport", "resolved", "eligible"),
    [
        ("mlx", "revision-123", True),
        ("mlx", "wrong-revision", False),
        ("http", "revision-123", True),
        ("http", "wrong-revision", False),
    ],
)
def test_real_backend_eligibility_requires_verified_loaded_revision(
    tmp_path, monkeypatch, transport, resolved, eligible
):
    """Fake only the model boundary; still execute the production pipeline."""
    import agronomy_agent.release_eval_executor as executor

    config = yaml.safe_load((ROOT / "configs/model.yaml").read_text())
    config["model_revision"] = "revision-123"
    config["answer_verification"]["enabled"] = False
    config_path = tmp_path / "effective-model.yaml"
    config_path.write_text(yaml.safe_dump(config))

    class FixtureGenerator:
        backend_id = "identity_contract_fixture"
        model_id = config["model_id"]
        last_generation_stats = None
        model_identity = {
            "status": (
                "verified_direct_loader"
                if transport == "mlx"
                else "verified_runtime_receipt"
            ),
            "configured_model_id": config["model_id"],
            "configured_model_revision": "revision-123",
            "runtime": {"model_revision": resolved} if transport == "http" else {},
        }

        def generate(self, messages):
            self.last_generation_stats = {
                "backend": "identity_contract_fixture",
                "generation_tokens": 10,
                "prompt_tokens": 30,
            }
            return (
                "Soil texture describes relative proportions of sand, silt, and clay."
            )

    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", transport)
    monkeypatch.setattr(
        executor,
        "resolve_local_model_snapshot",
        lambda *args, **kwargs: tmp_path / resolved,
    )
    monkeypatch.setattr(
        executor.chat_service,
        "_build_mlx_generator",
        lambda *args, **kwargs: FixtureGenerator(),
    )
    result = executor.execute_product_case(
        case(question="What does soil texture mean?"),
        model_config=config_path,
        rag_config=ROOT / "configs/rag.yaml",
        output_dir=tmp_path / "cells",
        backend="mlx",
    )
    assert result["status"] == "completed", result.get("error")
    assert result["model_execution_eligible"] is eligible
    assert result["turns"][0]["model_revision_observation"]["resolved"] == resolved
    assert result["turns"][0]["model_revision_observation"]["verified"] is eligible
    assert bool(result["failed_checks"]) is not eligible


@pytest.mark.parametrize("fault_location", ["draft", "editor"])
def test_real_unavailable_draft_or_editor_blocks_quality_gate(
    tmp_path, monkeypatch, fault_location
):
    import agronomy_agent.release_eval_executor as executor

    config = yaml.safe_load((ROOT / "configs/model.yaml").read_text())
    config_path = tmp_path / "effective-model.yaml"
    config_path.write_text(yaml.safe_dump(config))

    class FixtureGenerator:
        model_id = config["model_id"]
        last_generation_stats = None
        model_identity = {
            "status": "verified_runtime_receipt",
            "configured_model_revision": config["model_revision"],
            "runtime": {"model_revision": config["model_revision"]},
        }

        def generate(self, messages):
            if fault_location == "draft":
                raise RuntimeError("fixture real draft backend unavailable")
            self.last_generation_stats = {"generation_tokens": 12, "prompt_tokens": 50}
            return "Soil texture describes sand, silt, and clay proportions."

    def editor_outcome(*args, **kwargs):
        return SimpleNamespace(
            answer="Fixture conservative fallback.",
            triggered=True,
            rewrite_accepted=False,
            draft_assessment=SimpleNamespace(reasons=("fixture_review",)),
            as_record=lambda: {
                "triggered": True,
                "rewrite_accepted": False,
                "fallback_applied": True,
                "rejection_reasons": ["editor_error", "RuntimeError"],
            },
        )

    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "http")
    monkeypatch.setattr(
        executor.chat_service,
        "_build_mlx_generator",
        lambda *args, **kwargs: FixtureGenerator(),
    )
    monkeypatch.setattr(executor.chat_service, "verify_answer", editor_outcome)
    result = executor.execute_product_case(
        case(question="What does soil texture mean?"),
        model_config=config_path,
        rag_config=ROOT / "configs/rag.yaml",
        output_dir=tmp_path / "cells",
        backend="mlx",
    )
    assert result["status"] == "completed", result.get("error")
    turn = result["turns"][0]
    assert turn["model_execution"]["disposition"] == "backend_fallback_or_unavailable"
    assert turn["model_execution"]["product_quality_eligible"] is False
    assert "turn_1.real_backend_and_editor_available" in {
        row["id"] for row in result["failed_checks"]
    }


@pytest.mark.parametrize("arm", ["raw_model", "kernel_only"])
def test_same_harness_case_reference_omits_production_assertions_explicitly(
    tmp_path, arm
):
    row = deepcopy(
        next(row for row in CASES if row["case_id"] == "HR1-conversion-forward")
    )
    result = run(tmp_path, row, arm_id=arm)
    assert result["status"] == "completed"
    assert result["failed_checks"] == []
    assert result["turns"][0]["stage_receipts"] == []
    assert result["assertion_scope"]["selected_assertion_ids"] == []
    omitted = result["assertion_scope"]["not_applicable_product_expectations"]
    assert {item["id"] for item in omitted} == set(row["assertions"])
    assert all(
        item["status"] == "not_applicable_diagnostic_arm" and "passed" not in item
        for item in omitted
    )
    assert not set(row["assertions"]).intersection(
        item["id"] for item in result["checks"]
    )


def test_arm_specific_unknown_assertion_blocks_instead_of_becoming_pass(tmp_path):
    row = case(
        assertions={"tool_status": "ready"},
        assertions_by_arm={"raw_model": {"unimplemented_arm_contract": True}},
    )
    result = run(tmp_path, row, arm_id="raw_model")
    assert result["status"] == "completed"
    assert [item["id"] for item in result["failed_checks"]] == [
        "unimplemented_arm_contract"
    ]
    assert "unimplemented_arm_contract" in {item["id"] for item in result["unknown"]}
    assert result["assertion_scope"]["selected_assertion_ids"] == [
        "unimplemented_arm_contract"
    ]


@pytest.mark.parametrize(
    "arm, invariant",
    [
        ("full_minus_field_context", "turn_1.typed_field_context_disabled"),
        ("retrieval_neither", "turn_1.document_retrieval_disabled"),
    ],
)
def test_diagnostic_arm_keeps_real_disable_invariants_without_product_expectations(
    tmp_path, arm, invariant
):
    row = case(
        question="What observations should I collect?",
        field_context={"crop": "canola"},
        assertions={
            "field_values": {"crop": "canola"},
            "expected_source_ids": ["unavailable_expectation"],
        },
    )
    result = run(tmp_path, row, arm_id=arm)
    assert result["status"] == "completed"
    assert result["failed_checks"] == []
    passed = {item["id"] for item in result["checks"] if item["passed"]}
    assert invariant in passed
    assert "turn_1.ordered_stages" in passed
    assert "turn_1.private_overlays_absent" in passed
    assert "field_values" not in passed and "expected_source_ids" not in passed


def test_production_existing_assertions_remain_required_and_do_not_use_diagnostic_override(
    tmp_path,
):
    row = case(
        assertions={"tool_status": "clarification_required"},
        assertions_by_arm={"production_full": {"tool_status": "ready"}},
    )
    result = run(tmp_path, row)
    assert result["status"] == "completed"
    assert [item["id"] for item in result["failed_checks"]] == ["tool_status"]
    assert result["assertion_scope"]["policy"] == "production_required"
    assert result["assertion_scope"]["not_applicable_product_expectations"] == []


@pytest.mark.parametrize("mapping", [{"invented_arm": {}}, {"raw_model": []}, []])
def test_invalid_arm_assertion_schema_is_rejected_before_execution(tmp_path, mapping):
    result = run(tmp_path, case(assertions_by_arm=mapping), arm_id="raw_model")
    assert result["status"] == "failed"
    assert result["turns"] == []
    assert "assertions_by_arm" in result["error"]["message"]


def test_disabled_field_receipt_contradiction_fails_automatic_diagnostic_check(
    tmp_path, monkeypatch
):
    import agronomy_agent.release_eval_executor as executor

    original = executor._production_turn

    def contradictory_observation(question, request):
        turn = original(question, request)
        field = next(
            row
            for row in turn["stage_receipts"]
            if row["stage_id"] == "typed_field_context"
        )
        field["evidence"]["field_context_present"] = True
        return turn

    monkeypatch.setattr(executor, "_production_turn", contradictory_observation)
    result = run(
        tmp_path,
        case(
            field_context={"crop": "canola"},
            assertions={"field_values": {"crop": "canola"}},
        ),
        arm_id="full_minus_field_context",
    )
    assert result["status"] == "completed"
    assert "turn_1.typed_field_context_disabled" in {
        row["id"] for row in result["failed_checks"]
    }
    assert "field_values" not in {row["id"] for row in result["checks"]}
