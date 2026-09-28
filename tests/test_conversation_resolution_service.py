from __future__ import annotations

from agronomy_agent.execution_core import AgentExecutionRequest
from agronomy_agent.server.services import conversation_resolution
from agronomy_agent.server.services.chat_service import execute_agent_request
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


class NeverGenerate:
    measured_capability_profile = "balanced"

    def generate(self, messages):  # noqa: ANN001, ANN201
        raise AssertionError("a complete conversion must bypass model generation")


class StubGenerator:
    measured_capability_profile = "balanced"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages):  # noqa: ANN001, ANN201
        self.calls += 1
        return "Please state the complete request with units."


class FailingGenerator:
    measured_capability_profile = "balanced"

    def generate(self, messages):  # noqa: ANN001, ANN201
        raise RuntimeError("synthetic model failure")


def _setup(tmp_path):  # noqa: ANN001, ANN202
    db_path = tmp_path / "trace.sqlite3"
    store = TraceStore(db_path)
    settings = build_settings(
        db_path=db_path,
        artifact_root=tmp_path / "artifacts",
        model_config_path="configs/model.yaml",
        default_rag_config="configs/rag.yaml",
        network_mode="offline",
    )
    return store, settings


def _ask(
    store, settings, session_id, question, backend, *, parent_turn_id=None,
    mode="agronomic_rag", typed_tools_enabled=True,
):  # noqa: ANN001, ANN202
    request = AgentExecutionRequest(
        store=store,
        settings=settings,
        session_id=session_id,
        message=question,
        mode=mode,
        model_id="mock",
        rag_config="configs/rag.yaml",
        max_tokens=100,
        trace_options={"store_prompt_messages": True},
        generation_backend=backend,
        parent_turn_id=parent_turn_id,
        typed_tools_enabled=typed_tools_enabled,
        execution_class="observed_system_execution_nonclaim",
    )
    return execute_agent_request(request).turn


def _resolution(turn):  # noqa: ANN001, ANN202
    return turn["trace"]["metadata"]["conversation_resolution"]


def test_actual_session_turns_resolve_conversion_and_preserve_original_text(tmp_path) -> None:  # noqa: ANN001
    store, settings = _setup(tmp_path)
    session_id = store.create_session("Calculator", {}, {})["session_id"]
    backend = NeverGenerate()

    first = _ask(store, settings, session_id, "Convert 100 lb/ac to kg/ha", backend)
    second = _ask(store, settings, session_id, "What about 200 instead?", backend)
    third = _ask(store, settings, session_id, "What about 300 instead?", backend)

    assert first["answer"].startswith("112.085 kg/ha")
    assert second["answer"].startswith("224.17 kg/ha")
    assert third["answer"].startswith("336.255 kg/ha")
    assert second["user_message"] == "What about 200 instead?"
    assert third["user_message"] == "What about 300 instead?"
    assert store.get_turn(second["turn_id"])["user_message"] == second["user_message"]
    assert _resolution(second)["effective_question"] == "Convert 200 lb/ac to kg/ha"
    assert _resolution(second)["source_turn_id"] == first["turn_id"]
    assert _resolution(third)["effective_question"] == "Convert 300 lb/ac to kg/ha"
    assert _resolution(third)["source_turn_id"] == second["turn_id"]
    for turn in (first, second, third):
        assert turn["trace"]["metadata"]["generation_path"] == "deterministic_tool_result"


def test_other_session_cannot_supply_the_operand_or_units(tmp_path) -> None:  # noqa: ANN001
    store, settings = _setup(tmp_path)
    first_session = store.create_session("First", {}, {})["session_id"]
    other_session = store.create_session("Other", {}, {})["session_id"]
    _ask(store, settings, first_session, "Convert 100 lb/ac to kg/ha", NeverGenerate())
    backend = StubGenerator()

    followup = _ask(store, settings, other_session, "What about 200 instead?", backend)

    assert _resolution(followup)["status"] == "no_antecedent"
    assert _resolution(followup)["source_turn_id"] is None
    assert _resolution(followup)["effective_question"] == "What about 200 instead?"
    assert followup["trace"]["metadata"]["context_budget"]["history_turns_available"] == 0
    assert followup["trace"]["tool_invocations"] == []
    assert backend.calls == 1


def test_ambiguous_prior_operands_do_not_trigger_calculator(tmp_path) -> None:  # noqa: ANN001
    store, settings = _setup(tmp_path)
    session_id = store.create_session("Ambiguous", {}, {})["session_id"]
    store.create_turn(
        session_id,
        "For 65 ha at 85 kg/ha, what is the product total?",
        "Synthetic answer.",
        parent_turn_id=None, system_state={}, trace={}, objectives={}, event_stream=False,
    )
    backend = StubGenerator()

    followup = _ask(store, settings, session_id, "What about 200 instead?", backend)

    assert _resolution(followup)["status"] == "ambiguous_antecedent"
    assert _resolution(followup)["effective_question"] == "What about 200 instead?"
    assert followup["trace"]["tool_invocations"] == []
    assert backend.calls == 1


def test_replay_uses_only_history_before_original_turn(tmp_path) -> None:  # noqa: ANN001
    store, settings = _setup(tmp_path)
    session_id = store.create_session("Replay", {}, {})["session_id"]
    earlier = store.create_turn(
        session_id, "Convert 100 lb/ac to kg/ha", "112.085 kg/ha",
        parent_turn_id=None, system_state={}, trace={}, objectives={}, event_stream=False,
    )
    base = store.create_turn(
        session_id, "What about 200 instead?", "224.17 kg/ha",
        parent_turn_id=None, system_state={}, trace={}, objectives={}, event_stream=False,
    )
    future = store.create_turn(
        session_id, "Convert 900 lb/ac to kg/ha", "1008.765 kg/ha",
        parent_turn_id=None, system_state={}, trace={}, objectives={}, event_stream=False,
    )

    replay = _ask(
        store, settings, session_id, "What about 300 instead?",
        NeverGenerate(), parent_turn_id=base,
    )

    assert replay["answer"].startswith("336.255 kg/ha")
    assert _resolution(replay)["source_turn_id"] == earlier
    assert _resolution(replay)["source_turn_id"] != future
    assert replay["trace"]["metadata"]["context_budget"]["history_before_turn_id"] == base
    assert replay["trace"]["metadata"]["context_budget"]["history_turns_available"] == 1
    assert replay["trace"]["metadata"]["context_budget"]["history_included_turn_ids"] == []


def test_disabled_or_baseline_mode_never_invokes_reference_planner(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    store, settings = _setup(tmp_path)
    session_id = store.create_session("Ablation", {}, {})["session_id"]
    _ask(store, settings, session_id, "Convert 100 lb/ac to kg/ha", NeverGenerate())

    def forbidden_plan(_question):  # noqa: ANN001, ANN202
        raise AssertionError("disabled reference resolution invoked the planner")

    monkeypatch.setattr(conversation_resolution, "plan_tools", forbidden_plan)
    for mode, typed_tools_enabled in (
        ("baseline", True), ("mock", True), ("agronomic_rag", False)
    ):
        backend = StubGenerator()
        turn = _ask(
            store, settings, session_id, "What about 200 instead?", backend,
            mode=mode, typed_tools_enabled=typed_tools_enabled,
        )
        assert _resolution(turn)["status"] == "typed_resolution_disabled"
        assert _resolution(turn)["effective_question"] == "What about 200 instead?"
        assert turn["user_message"] == "What about 200 instead?"
        assert backend.calls == 1


def test_prior_model_failure_does_not_supply_operand_for_current_calculation(tmp_path) -> None:  # noqa: ANN001
    store, settings = _setup(tmp_path)
    session_id = store.create_session("Failed prior answer", {}, {})["session_id"]
    failed = _ask(
        store, settings, session_id, "Convert 100 lb/ac to kg/ha",
        FailingGenerator(), mode="baseline",
    )
    assert failed["answer_status"] == "draft"
    assert "analysis unavailable" in failed["answer"].casefold()

    current = _ask(store, settings, session_id, "What about 200 instead?", NeverGenerate())
    assert current["answer"].startswith("224.17 kg/ha")
    assert _resolution(current)["source_turn_id"] == failed["turn_id"]
    assert _resolution(current)["effective_question"] == "Convert 200 lb/ac to kg/ha"
    assert _resolution(current)["status"] == "resolved_unique_user_number"
