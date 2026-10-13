"""Request-bound calculator planning agrees with real persisted execution."""
from copy import deepcopy
from decimal import Decimal
import asyncio
from threading import Event, Thread
import uuid

from fastapi.testclient import TestClient
import pytest
from httpx import ASGITransport, AsyncClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.services import chat_service
from agronomy_agent.server.settings import build_settings
from agronomy_agent.tool_planner import plan_tools

OWNER = {"X-Agronomy-User-Email": "readiness-owner@example.test"}
OTHER = {"X-Agronomy-User-Email": "readiness-other@example.test"}
CONVERSION = "Convert 100 lb/ac to kg/ha"
TANK = "Calculate how much area will a 1000 L sprayer tank cover applying 100 L/ha, ignoring unusable tank volume?"
SEED_MISSING = "Calculate seed rate: target stand is 200 plants/m², TKW is missing, germination is 95%, expected field survival is 90%."


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    root = tmp_path_factory.mktemp("turn-readiness")
    settings = build_settings(db_path=root / "synthetic.sqlite3", artifact_root=root / "artifacts", network_mode="offline")
    client = TestClient(create_app(settings))
    yield client, client.app.state.trace_store
    client.close()
    client.app.state.trace_store._conn.close()


def turn(question=CONVERSION, **kwargs):
    return {"message": question, "mode": "agronomic_rag", **kwargs}


def session(client, context=None):
    result = client.post("/api/sessions", headers=OWNER, json={"title": "Synthetic readiness", "context": context or {},
                         "consent": {"local_trace_capture": True, "research_export_allowed": False, "training_export_allowed": False}})
    assert result.status_code == 200, result.text
    return result.json()["session_id"]


def preview(client, payload, session_id=None, headers=OWNER):
    result = client.post("/api/turn-readiness", headers=headers,
                         json={"request_id": str(uuid.uuid4()), "session_id": session_id, "turn": payload})
    assert result.status_code == 200, result.text
    return result.json()


def no_generator(*args, **kwargs):
    raise AssertionError("calculator readiness/execution must not construct a generator")


@pytest.mark.parametrize("question,path", [(CONVERSION, "deterministic_tool_result"),
                                          (TANK, "deterministic_tool_result"),
                                          (SEED_MISSING, "deterministic_tool_clarification")])
@pytest.mark.parametrize("backend", ["mlx", "http"])
def test_actual_missing_model_calculation_and_clarification_persist_without_constructor(runtime, monkeypatch, question, path, backend):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    # An unconfigured generation backend cannot obstruct arithmetic either.
    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", backend)
    monkeypatch.delenv("AGRONOMY_AGENT_MODEL_BASE_URL", raising=False)
    sid = session(client)
    payload = turn(question)
    view = preview(client, payload, sid)
    assert view["requires_model"] is False
    plan = plan_tools(question)
    assert view["calculator"]["operation"] == plan.invocations[0].operation
    assert view["calculator"]["inputs"] == dict(plan.invocations[0].inputs)
    assert view["calculator"]["missing_inputs"] == list(plan.invocations[0].missing_inputs)
    assert view["binding"]["planner_version"] == plan.planner_version
    response = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                           json={**payload, "readiness_binding": view["readiness_binding"]})
    assert response.status_code == 200, response.text
    saved = store.get_turn(response.json()["turn_id"])
    assert saved["trace"]["metadata"]["generation_path"] == path
    if path.endswith("result"):
        assert saved["answer"].startswith("10 ha" if question == TANK else "112.085 kg/ha")
    else:
        assert "tkw_g" in saved["answer"]


def test_preview_is_read_only_and_does_not_create_a_session(runtime, monkeypatch):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    # Initialize the workspace principal through the same bootstrap as the UI.
    # /auth/me creates only the user; relying on an earlier test to create its
    # workspace makes this all-table assertion depend on xdist scheduling.
    bootstrap = client.get("/api/demo/fields", headers=OWNER)
    assert bootstrap.status_code == 200, bootstrap.text
    tables = [row[0] for row in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    counts = lambda: {name: store._conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
    before = counts()
    first = preview(client, turn())
    second = preview(client, turn())
    assert first["readiness_binding"] == second["readiness_binding"]
    assert first["binding"]["session_id"] is None
    assert counts() == before


def test_tank_preview_never_executes_an_adapter_or_creates_a_receipt(runtime, monkeypatch):
    import agronomy_agent.agronomic_calculations as calculations
    import agronomy_agent.capability_registry as registry
    client, store = runtime
    assert client.get("/api/demo/fields", headers=OWNER).status_code == 200
    def forbidden(*args, **kwargs):
        raise AssertionError("preview cannot execute a calculator/adapter")
    monkeypatch.setattr(calculations, "calculate_agronomic", forbidden)
    monkeypatch.setattr(registry, "execute_registered_capability", forbidden)
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    tables = [row[0] for row in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    counts = lambda: {name: store._conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
    before = counts()
    view = preview(client, turn(TANK))
    assert view["requires_model"] is False and view["status"] == "ready"
    assert view["calculator"]["operation"] == "tank_coverage"
    assert "value" not in view["calculator"] and "result_id" not in view["calculator"]
    assert counts() == before


@pytest.mark.parametrize("value", ["0", "1" + "0" * 25, "1" + "0" * 309])
def test_invalid_tank_coverage_cannot_receive_a_ready_preview(runtime, value):
    client, _ = runtime
    view = preview(client, turn(f"Calculate how much area will a {value} L sprayer tank cover applying 100 L/ha?"))
    assert view["requires_model"] is None and view["status"] == "unknown"
    assert view["reason"] == "invalid_calculator_inputs"


@pytest.mark.parametrize("tank,rate", [("-1000", "100"), ("−1000", "100"), ("- 1000", "100"),
                                      ("1000", "-100"), ("1000", "−100"), ("1000", "- 100")])
def test_signed_tank_operands_reach_canonical_validation_and_never_qualify(runtime, monkeypatch, tank, rate):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    question = f"Calculate how much area will a {tank} L sprayer tank cover applying {rate} L/ha?"
    plan = plan_tools(question)
    assert plan.status == "ready"
    assert Decimal(str(plan.invocations[0].inputs["tank_volume_l"])) < 0 or Decimal(str(plan.invocations[0].inputs["application_volume_l_per_ha"])) < 0
    sid = session(client)
    payload = turn(question)
    view = preview(client, payload, sid)
    assert view["requires_model"] is None and view["status"] == "unknown"
    assert view["reason"] == "invalid_calculator_inputs"
    rejected = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                           json={**payload, "readiness_binding": view["readiness_binding"]})
    assert rejected.status_code == 400 and "greater than zero" in rejected.json()["detail"]
    assert store.count_session_turns(sid) == 0


@pytest.mark.parametrize("unusable", ["1000", "1001", "-1", "−1"])
def test_explicit_unusable_tank_volume_is_not_discarded_or_qualified(runtime, unusable):
    client, _ = runtime
    question = f"Calculate how much area will a 1000 L sprayer tank cover applying 100 L/ha with {unusable} L unusable tank volume?"
    plan = plan_tools(question)
    assert Decimal(str(plan.invocations[0].inputs["unusable_volume_l"])) == Decimal(unusable.replace("−", "-"))
    view = preview(client, turn(question))
    assert view["requires_model"] is None and view["status"] == "unknown"
    assert view["reason"] == "invalid_calculator_inputs"


@pytest.mark.parametrize("key,literal", [
    ("tank_volume_l", "1000.0000000000000000000000000001"),
    ("tank_volume_l", "1000.0000000000000000000000000000"),
    ("application_volume_l_per_ha", "100.0000000000000000000000000001"),
    ("unusable_volume_l", "0.00000000000000000000000000010000000000000000000000000001"),
    ("unusable_volume_l", "-0." + "0" * 330 + "1"),
])
def test_tank_numeric_literals_cannot_lose_precision_before_preview_or_submission(runtime, monkeypatch, key, literal):
    from agronomy_agent.agronomic_calculations import calculate_agronomic, validate_tank_coverage_inputs
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    inputs = {"tank_volume_l": "1000", "application_volume_l_per_ha": "100", "unusable_volume_l": "0", key: literal}
    question = (f"Calculate how much area will a {inputs['tank_volume_l']} L sprayer tank cover applying "
                f"{inputs['application_volume_l_per_ha']} L/ha with {inputs['unusable_volume_l']} L unusable tank volume?")
    plan = plan_tools(question)
    assert plan.status == "ready"
    assert plan.invocations[0].inputs[key] == literal
    with pytest.raises(ValueError) as validation:
        validate_tank_coverage_inputs(inputs)
    with pytest.raises(ValueError) as execution:
        calculate_agronomic("tank_coverage", plan.invocations[0].inputs)
    assert str(execution.value) == str(validation.value)
    sid = session(client)
    payload = turn(question)
    view = preview(client, payload, sid)
    assert view["requires_model"] is None and view["status"] == "unknown"
    assert view["reason"] == "invalid_calculator_inputs"
    rejected = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                           json={**payload, "readiness_binding": view["readiness_binding"]})
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["detail"] == str(validation.value)
    assert store.count_session_turns(sid) == 0


def test_valid_tank_decimal_literals_persist_the_exact_canonical_answer(runtime, monkeypatch):
    from agronomy_agent.agronomic_calculations import calculate_agronomic
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    supplied = {"tank_volume_l": "1000.00000000000001", "application_volume_l_per_ha": "100.00000000000001",
                "unusable_volume_l": "0.00000000000001"}
    question = (f"Calculate how much area will a {supplied['tank_volume_l']} L sprayer tank cover applying "
                f"{supplied['application_volume_l_per_ha']} L/ha with {supplied['unusable_volume_l']} L unusable tank volume?")
    plan = plan_tools(question)
    assert {key: Decimal(str(value)) for key, value in plan.invocations[0].inputs.items()} == {
        key: Decimal(value) for key, value in supplied.items()}
    expected = calculate_agronomic("tank_coverage", supplied)
    sid = session(client)
    payload = turn(question)
    view = preview(client, payload, sid)
    assert view["requires_model"] is False and view["status"] == "ready"
    response = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                           json={**payload, "readiness_binding": view["readiness_binding"]})
    assert response.status_code == 200, response.text
    saved = store.get_turn(response.json()["turn_id"])
    assert saved["answer"] == expected.answer()
    assert saved["trace"]["metadata"]["generation_path"] == "deterministic_tool_result"


def test_ordinary_tank_operands_retain_the_existing_numeric_contract():
    assert dict(plan_tools(TANK).invocations[0].inputs) == {
        "tank_volume_l": 1000.0, "application_volume_l_per_ha": 100.0, "unusable_volume_l": 0}
    assert all(type(value) in {int, float} for value in plan_tools(TANK).invocations[0].inputs.values())


@pytest.mark.parametrize("suffix,area", [("", 10), (" with unusable tank volume of 100 L", 9),
                                       (" with 100 L unusable volume", 9)])
def test_valid_signed_positive_and_unusable_operands_persist_the_same_planned_area(runtime, monkeypatch, suffix, area):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    question = f"Calculate how much area will a +1000 L sprayer tank cover applying +100 L/ha{suffix}?"
    payload = turn(question)
    sid = session(client)
    view = preview(client, payload, sid)
    assert view["requires_model"] is False and view["status"] == "ready"
    result = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                         json={**payload, "readiness_binding": view["readiness_binding"]})
    assert result.status_code == 200, result.text
    saved = store.get_turn(result.json()["turn_id"])
    assert saved["answer"].startswith(f"{area} ha")
    assert saved["trace"]["metadata"]["generation_path"] == "deterministic_tool_result"


@pytest.mark.parametrize("suffix", [" with unusable tank volume unknown", " with 100 L unusable tank volume and 200 L unusable tank volume",
                                  " with 100 L unusable tank volume, ignoring unusable tank volume"])
def test_ambiguous_or_conflicting_unusable_volume_uses_the_canonical_clarification(runtime, suffix):
    client, _ = runtime
    question = f"Calculate how much area will a 1000 L sprayer tank cover applying 100 L/ha{suffix}?"
    view = preview(client, turn(question))
    assert view["status"] == "clarification_required"
    assert view["calculator"]["missing_inputs"] == ["unusable_volume_l"]


@pytest.mark.parametrize("payload", [turn("Why are my wheat leaves yellow?"), turn(mode="baseline")])
def test_generation_or_disabled_modes_remain_model_required(runtime, payload):
    client, _ = runtime
    result = preview(client, payload)
    assert result["requires_model"] is True and result["calculator"] is None
    assert result["status"] == "model_required"


def test_disabled_mock_mode_cannot_claim_real_calculator_availability(runtime):
    client, _ = runtime
    result = client.post("/api/turn-readiness", headers=OWNER,
                         json={"request_id": str(uuid.uuid4()), "turn": turn(mode="mock")})
    assert result.status_code == 409, result.text


@pytest.mark.parametrize("question", [
    "Calculate how much area will a 1000 L sprayer tank cover applying 0 L/ha, ignoring unusable tank volume?",
    "Calculate application volume for 20 nozzles flowing 1.1 L/min, travels at 10 km/h on an 11 m boom.",
])
def test_a_complete_plan_without_separate_canonical_validation_stays_unknown(runtime, monkeypatch, question):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    plan = plan_tools(question)
    assert plan.status == "ready"
    sid = session(client)
    payload = turn(question)
    view = preview(client, payload, sid)
    assert view["requires_model"] is None and view["status"] == "unknown"
    assert view["reason"] == ("invalid_calculator_inputs" if plan.invocations[0].operation == "tank_coverage" else "operation_validation_unavailable")
    assert view["calculator"]["operation"] == plan.invocations[0].operation
    if plan.invocations[0].operation == "tank_coverage":
        invalid = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                              json={**payload, "readiness_binding": view["readiness_binding"]})
        assert invalid.status_code == 400, invalid.text
        assert "greater than zero" in invalid.json()["detail"]
        assert store.count_session_turns(sid) == 0


@pytest.mark.parametrize("value", ["1" + "0" * 25, "1" + "0" * 309])
def test_overlarge_or_nonfinite_conversion_cannot_be_declared_ready(runtime, value):
    client, _ = runtime
    view = preview(client, turn(f"Convert {value} lb/ac to kg/ha"))
    assert view["requires_model"] is None and view["status"] == "unknown"


def test_unsupported_conversion_units_remain_a_canonical_input_clarification(runtime, monkeypatch):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    payload = turn("Convert 100 unsupported_units to kg/ha")
    sid = session(client)
    view = preview(client, payload, sid)
    assert view["status"] == "clarification_required"
    assert view["calculator"]["missing_inputs"] == list(plan_tools(payload["message"]).invocations[0].missing_inputs)
    result = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                         json={**payload, "readiness_binding": view["readiness_binding"]})
    assert result.status_code == 200, result.text
    assert store.get_turn(result.json()["turn_id"])["trace"]["metadata"]["generation_path"] == "deterministic_tool_clarification"


def test_queue_wait_does_not_block_a_validated_conversion(runtime, monkeypatch):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    monkeypatch.setattr(chat_service, "_model_queue_circuit_breaker", lambda *args, **kwargs: {
        "tripped": True, "reason": "model_queue_wait_exceeded"})
    sid = session(client)
    view = preview(client, turn(), sid)
    result = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                         json={**turn(), "readiness_binding": view["readiness_binding"]})
    assert result.status_code == 200, result.text
    assert store.get_turn(result.json()["turn_id"])["answer"].startswith("112.085 kg/ha")


def test_history_changed_after_http_precheck_is_rejected_under_worker_guard(runtime, monkeypatch):
    import agronomy_agent.server.app as app_module
    client, store = runtime
    sid = session(client)
    view = preview(client, turn(), sid)
    original = app_module.preview_turn_readiness
    calls = 0
    def change_before_worker(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            store.create_turn(sid, "Intervening synthetic question", "Stored synthetic response", parent_turn_id=None,
                              system_state={}, trace={}, objectives={}, event_stream=False)
        return original(**kwargs)
    monkeypatch.setattr(app_module, "preview_turn_readiness", change_before_worker)
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    result = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                         json={**turn(), "readiness_binding": view["readiness_binding"]})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["code"] == "turn_readiness_stale"
    assert store.count_session_turns(sid) == 1


def test_wrong_session_cannot_read_private_history(runtime, monkeypatch):
    client, store = runtime
    sid = session(client)
    def forbidden(*args, **kwargs):
        raise AssertionError("private history read before ownership")
    monkeypatch.setattr(store, "get_recent_session_turns", forbidden)
    result = client.post("/api/turn-readiness", headers=OTHER,
                         json={"request_id": str(uuid.uuid4()), "session_id": sid, "turn": turn()})
    assert result.status_code == 404, result.text


def test_stale_question_binding_is_rejected_before_persisting_and_exact_retry_replays(runtime, monkeypatch):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    sid = session(client)
    payload = turn()
    view = preview(client, payload, sid)
    stale = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                        json={**payload, "message": "Convert 200 lb/ac to kg/ha", "readiness_binding": view["readiness_binding"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "turn_readiness_stale"
    assert store.count_session_turns(sid) == 0
    operation = str(uuid.uuid4())
    request = {**payload, "readiness_binding": view["readiness_binding"], "client_operation_id": operation}
    first = client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json=request)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json=request)
    assert second.status_code == 200, second.text
    assert second.json()["turn_id"] == first.json()["turn_id"]
    assert store.count_session_turns(sid) == 1


def test_follow_up_preview_uses_shared_history_and_rejects_changed_head(runtime, monkeypatch):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    sid = session(client)
    first = client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json=turn())
    assert first.status_code == 200, first.text
    follow = turn("What about 200 instead?")
    view = preview(client, follow, sid)
    assert view["requires_model"] is False and view["calculator"]["inputs"]["value"] == 200
    intervening = client.post(f"/api/sessions/{sid}/turns", headers=OWNER, json=turn("Convert 400 lb/ac to kg/ha"))
    assert intervening.status_code == 200, intervening.text
    for suffix in ("", "/stream"):
        rejected = client.post(f"/api/sessions/{sid}/turns{suffix}", headers=OWNER,
                               json={**follow, "readiness_binding": view["readiness_binding"]})
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "turn_readiness_stale"
    assert store.count_session_turns(sid) == 2


def test_stored_field_authorization_and_changed_revision_invalidate_readiness(runtime, monkeypatch):
    client, store = runtime
    monkeypatch.setattr(chat_service, "_build_mlx_generator", no_generator)
    created = client.post("/api/demo/fields", headers=OWNER,
                          json={"name": "Synthetic readiness field", "field": {}, "geometry": {"kind": "none"}})
    assert created.status_code == 201, created.text
    field = created.json()["field"]
    context = {"field_context_id": field["id"], "field_conversation_key": f"field:{field['id']}"}
    sid = session(client, context)
    payload = turn(session_context=context)
    view = preview(client, payload, sid)
    denied = client.post("/api/turn-readiness", headers=OTHER,
                         json={"request_id": str(uuid.uuid4()), "turn": payload})
    assert denied.status_code == 403, denied.text
    record = store.get_phase4_field_context(field["id"])
    metadata = deepcopy(record["metadata"])
    metadata["open_agronomy_agent"]["field"]["notes"] = "Corrected synthetic note"
    user = client.get("/auth/me", headers=OWNER).json()["user"]
    store.update_phase4_field_context(field_context_id=field["id"], actor_user_id=user["id"], payload={"metadata": metadata})
    rejected = client.post(f"/api/sessions/{sid}/turns", headers=OWNER,
                           json={**payload, "readiness_binding": view["readiness_binding"]})
    assert rejected.status_code == 409, rejected.text
    assert store.count_session_turns(sid) == 0


def test_preview_waiting_for_session_guard_keeps_other_api_requests_responsive(runtime, monkeypatch):
    from contextlib import contextmanager
    import agronomy_agent.server.app as app_module

    client, store = runtime
    sid = session(client)
    held, release, attempted = Event(), Event(), Event()
    original_guard = chat_service._session_turn_guard

    def holder():
        with original_guard(store, sid):
            held.set()
            assert release.wait(5), 'test did not release the owned session guard'

    @contextmanager
    def observed_guard(current_store, session_id):
        attempted.set()
        with original_guard(current_store, session_id):
            yield

    monkeypatch.setattr(app_module, '_session_turn_guard', observed_guard)
    monkeypatch.setattr(chat_service, '_build_mlx_generator', no_generator)
    thread = Thread(target=holder)
    thread.start()
    assert held.wait(1)

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=client.app), base_url='http://test') as http:
            pending = asyncio.create_task(http.post('/api/turn-readiness', headers=OWNER,
                json={'request_id': str(uuid.uuid4()), 'session_id': sid, 'turn': turn()}))
            try:
                assert await asyncio.to_thread(attempted.wait, 1)
                assert not pending.done()
                health = await asyncio.wait_for(http.get('/api/health'), timeout=1)
                assert health.status_code == 200
                assert not release.is_set(), 'health must complete while the session stays locked'
                assert not pending.done()
            finally:
                release.set()
            result = await asyncio.wait_for(pending, timeout=2)
            assert result.status_code == 200, result.text
            assert result.json()['requires_model'] is False

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()
