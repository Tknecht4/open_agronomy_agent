"""A reused backend may only contribute telemetry for calls made by this turn."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

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
