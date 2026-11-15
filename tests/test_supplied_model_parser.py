"""Natural requests, input ownership and actual production result delivery."""
import pytest

from agronomy_agent.calculator_contracts import calculation_request_is_complete
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools


EXAMPLES = [
    ("Target established stand is 240 plants/m2, germination 80% and field survival 75% of germinated seed. Calculate seeds/m2.", "seed_population_density", 400),
    ("At 350 seeds/m2 and a thousand-kernel weight of 30 g, calculate seed mass per hectare, ignoring germination corrections.", "seed_mass_from_seed_density", 105),
    ("A prescription saves CAD 15/ha on 2 ha and costs an extra CAD 20/ha on 3 ha. Compute total and whole-field per-hectare cost change.", "area_cost_change", 30),
    ("Expected added yield is 0.3 t/ha at CAD 250/t, with product cost CAD 20/ha and application cost CAD 10/ha. Compute incremental margin.", "incremental_margin", 45),
    ("A teaching layer has 1.5% carbon, bulk density 1.4 Mg/m3 and depth 0.30 m, with coarse-fragment volume 10%. Compute carbon stock per hectare.", "soil_carbon_stock", 56.7),
    ("A soil has bulk density 1.2 Mg/m3 and particle density 2.4 Mg/m3. Using porosity = 1 - bulk/particle density, calculate total porosity and explain why it is not plant-available water.", "soil_total_porosity", 50),
    ("Under a teaching nutrient budget, target available N is 180 kg/ha, soil supply 50 and manure available-N credit 20. Compute the remaining requirement.", "remaining_nitrogen_budget", 110),
    ("For a teaching daily balance, initial stored water is 90 mm, effective rain 12, irrigation 8, ET 7 and drainage 3. Compute final storage.", "daily_water_balance", 100),
    ("Using NDVI = (NIR - red)/(NIR + red), calculate NDVI for reflectances NIR 0.70 and red 0.30. State one agronomic interpretation limit.", "ndvi_from_reflectance", .4),
    ("A uniform 0.25 m layer has 12 mg nitrate-N/kg and bulk density 1.4 Mg/m3. Compute its nitrate-N stock per hectare.", "soil_nitrate_n_stock", 42),
    ("For a teaching intercrop, crop A yields 4 versus 5 t/ha sole and crop B 2 versus 4 t/ha sole. Compute land equivalent ratio.", "land_equivalent_ratio", 1.3),
    ("Treatment yields in three matched blocks are 3.2, 3.8, 4.0 t/ha and controls 3.0, 3.4, 4.3. Compute the mean paired difference.", "mean_paired_difference", .1),
    ("A teaching calculation requires 3 t/ha of pure CaCO3 equivalent. A material has 120% effective neutralizing value. Compute product mass assuming the stated value applies.", "lime_equivalent_mass", 2.5),
    ("A model gives unstressed ETc 5 mm/day and a simplified stress multiplier 0.6 applied to all ET for this exercise. Compute the modeled value and state the simplification.", "simplified_stress_et", 3),
]


@pytest.mark.parametrize("question,operation,value", EXAMPLES)
def test_complete_owned_request_uses_the_named_typed_model(question, operation, value):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "ready", plan
    assert plan.invocations[0].operation == operation
    assert calculation_request_is_complete(question, operation)
    assert len(results) == 1 and results[0].status == "calculated"
    assert results[0].payload["value"] == pytest.approx(value)
    assert "Decimal(" not in results[0].answer


@pytest.mark.parametrize("question,operation,value", EXAMPLES)
@pytest.mark.parametrize("extra", [" Then apply it tomorrow.", " With instructions to improve drainage.", " Also select a product."])
def test_model_result_never_completes_an_unhandled_field_instruction(question, operation, value, extra):
    mixed = question.rstrip(".") + extra
    assert not calculation_request_is_complete(mixed, operation)
    plan, results = plan_and_execute_tools(mixed)
    assert plan.status != "ready" and not results


@pytest.mark.parametrize("question", [
    EXAMPLES[1][0] + " Seed purity is 90%.",
    EXAMPLES[4][0].replace("1.4 Mg/m3", "1.4 mg/m3"),
    EXAMPLES[4][0].replace("coarse-fragment volume 10%", "coarse fragments are unknown"),
    EXAMPLES[5][0].replace("bulk density", "wet bulk density"),
    EXAMPLES[5][0].replace("particle density 2.4 Mg/m3", "particle density 2.4 Mg/m3 from different soil material"),
    EXAMPLES[8][0].replace("0.70", "7000").replace("0.30", "3000"),
    EXAMPLES[9][0].replace("12 mg nitrate-N/kg", "12 mg nitrate/kg"),
    EXAMPLES[10][0] + " These are yields per crop's own strip.",
    EXAMPLES[11][0].replace("three matched", "two matched"),
    EXAMPLES[11][0].replace("controls 3.0, 3.4, 4.3", "controls 3.0, 3.4"),
    EXAMPLES[11][0].replace("controls 3.0, 3.4, 4.3", "controls 3.0, 3.4, 4.3 kg/ha"),
    EXAMPLES[12][0].replace("pure CaCO3 equivalent", "a recommendation already based on 60% ECCE"),
    EXAMPLES[13][0].replace("applied to all ET for this exercise", "applied only to transpiration"),
])
def test_incompatible_or_unrepresented_quantities_and_bases_cannot_be_ignored(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status != "ready" and not results


def test_paired_lists_can_state_matching_units_and_keep_every_pair_without_spaces():
    question = EXAMPLES[11][0].replace("3.2, 3.8, 4.0", "3.2,3.8,4.0").replace("controls 3.0, 3.4, 4.3", "controls 3.0,3.4,4.3 t/ha")
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "ready"
    assert results[0].payload["value"] == pytest.approx(.1)
    assert len(plan.invocations[0].inputs["control_yields"]) == 3


@pytest.mark.parametrize("question,operation,value", EXAMPLES)
def test_actual_production_persists_the_complete_model_result_without_generation(tmp_path, monkeypatch, question, operation, value):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    class Backend:
        backend_id = "synthetic_no_generation"
        intervention_profile = "balanced"
        def generate(self, messages):
            raise AssertionError("complete supplied model arithmetic must not require generation")
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    database = tmp_path / "models.sqlite3";store = TraceStore(database)
    try:
        session = store.create_session("Synthetic model arithmetic", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(
            store=store, settings=build_settings(db_path=database, artifact_root=tmp_path/"artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag", model_id="imposed",
            rag_config="configs/rag.yaml", max_tokens=180, generation_backend=backend))
        expected = plan_and_execute_tools(question)[1][0].answer
        assert result.answer == expected
        assert store.get_turn(result.turn["turn_id"])["answer"] == expected
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


@pytest.fixture(scope="module")
def http_runtime(tmp_path_factory):
    from fastapi.testclient import TestClient
    from agronomy_agent.server.app import create_app
    from agronomy_agent.server.settings import build_settings
    root = tmp_path_factory.mktemp("supplied-model-http")
    with TestClient(create_app(build_settings(db_path=root/"synthetic.sqlite3", artifact_root=root/"artifacts", network_mode="offline"))) as client:
        yield client, client.app.state.trace_store
        client.app.state.trace_store._conn.close()


@pytest.mark.parametrize("question,operation,value", EXAMPLES)
@pytest.mark.parametrize("backend", ["mlx", "http"])
def test_http_readiness_and_persisted_execution_share_model_contract(http_runtime, monkeypatch, question, operation, value, backend):
    import uuid
    import agronomy_agent.agronomic_calculations as calculations
    import agronomy_agent.capability_registry as registry
    from agronomy_agent.server.services import chat_service
    client, store = http_runtime
    headers = {"X-Agronomy-User-Email": "supplied-model-owner@example.test"}
    def forbidden(*args, **kwargs):
        raise AssertionError("preview cannot execute and complete arithmetic cannot construct a model")
    monkeypatch.setattr(chat_service, "_build_mlx_generator", forbidden)
    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", backend)
    monkeypatch.delenv("AGRONOMY_AGENT_MODEL_BASE_URL", raising=False)
    created = client.post("/api/sessions", headers=headers, json={"title":"Synthetic model arithmetic", "context":{},
        "consent":{"local_trace_capture":True,"research_export_allowed":False,"training_export_allowed":False}})
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    payload = {"message":question,"mode":"agronomic_rag"}
    before = store._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    with monkeypatch.context() as preview_patch:
        preview_patch.setattr(calculations,"calculate_agronomic",forbidden)
        preview_patch.setattr(registry,"execute_registered_capability",forbidden)
        preview = client.post("/api/turn-readiness", headers=headers, json={"request_id":str(uuid.uuid4()),"session_id":sid,"turn":payload})
    assert preview.status_code == 200, preview.text
    view = preview.json()
    assert view["requires_model"] is False and view["status"] == "ready", view
    assert view["calculator"]["operation"] == operation
    assert store._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == before
    response = client.post(f"/api/sessions/{sid}/turns", headers=headers, json={**payload,"readiness_binding":view["readiness_binding"]})
    assert response.status_code == 200, response.text
    saved = store.get_turn(response.json()["turn_id"])
    assert saved["answer"] == plan_and_execute_tools(question)[1][0].answer
    assert saved["trace"]["metadata"]["generation_path"] == "deterministic_tool_result"
    assert saved["trace"]["metadata"].get("generation_stats") is None
    from agronomy_agent.leak_guard import detect_prompt_leaks
    assert not detect_prompt_leaks(saved["answer"])


@pytest.mark.parametrize("basis,expected", [("among germinated seeds",400),("including germination",320),("among all seeds sown",320)])
def test_seed_count_existing_denominator_language_remains_owned(basis, expected):
    question = EXAMPLES[0][0].replace("of germinated seed",basis)
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "ready"
    assert results[0].payload["value"] == pytest.approx(expected)


@pytest.mark.parametrize("germination", [True,False])
def test_seed_count_basis_followup_and_optional_germination_chain_are_persisted(http_runtime, monkeypatch, germination):
    import uuid
    from copy import deepcopy
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.seed_establishment import SEED_SURVIVAL_BASIS_GAP
    client, store = http_runtime
    headers = {"X-Agronomy-User-Email":"supplied-model-owner@example.test"}
    def forbidden(*args, **kwargs):raise AssertionError("typed seed clarification must not construct a generator")
    monkeypatch.setattr(chat_service,"_build_mlx_generator",forbidden)
    question = EXAMPLES[0][0].replace(" of germinated seed", "")
    if not germination:question = question.replace("germination 80% and ", "")
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "clarification_required"
    assert plan.invocations[0].missing_inputs == (SEED_SURVIVAL_BASIS_GAP,)
    if germination:
        payload = results[0].payload
        assert payload["selected_scenario"] is None and "value" not in payload
        assert [s["calculation"]["value"] for s in payload["scenarios"]] == pytest.approx([320,400])
    else:assert not results
    sid = client.post("/api/sessions",headers=headers,json={"title":"Synthetic count chain","context":{},"consent":{"local_trace_capture":True,"research_export_allowed":False,"training_export_allowed":False}}).json()["session_id"]
    first = client.post(f"/api/sessions/{sid}/turns",headers=headers,json={"message":question,"mode":"agronomic_rag"})
    assert first.status_code == 200, first.text
    original = deepcopy(store.get_turn(first.json()["turn_id"]))
    replies = ["Only germinated seeds."] + ([] if germination else ["Germination is 80%."])
    for index, reply in enumerate(replies):
        payload = {"message":reply,"mode":"agronomic_rag"}
        view = client.post("/api/turn-readiness",headers=headers,json={"request_id":str(uuid.uuid4()),"session_id":sid,"turn":payload}).json()
        assert view["requires_model"] is False, view
        assert view["calculator"]["operation"] == "seed_population_density"
        response = client.post(f"/api/sessions/{sid}/turns",headers=headers,json={**payload,"readiness_binding":view["readiness_binding"]})
        assert response.status_code == 200, response.text
        saved = store.get_turn(response.json()["turn_id"])
        assert saved["user_message"] == reply
        assert saved["trace"]["metadata"]["generation_path"] == ("deterministic_tool_result" if index == len(replies)-1 else "deterministic_tool_clarification")
    assert saved["answer"].startswith("400 seeds/m²")
    assert store.get_turn(original["turn_id"]) == original


@pytest.mark.parametrize("question", [
    EXAMPLES[10][0].replace("crop B", "crop A"),
    EXAMPLES[10][0].replace(". Compute", " and crop A 4 versus 5 t/ha sole. Compute"),
])
def test_one_named_intercrop_component_cannot_be_counted_twice(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "clarification_required" and not results
    assert any("repeated crop component" in gap for gap in plan.invocations[0].missing_inputs)


def test_equivalent_decimal_spellings_do_not_create_an_operand_conflict():
    question = EXAMPLES[1][0].replace(", calculate", ", TKW 30.0 g, calculate")
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "ready"
    assert results[0].payload["value"] == pytest.approx(105)
