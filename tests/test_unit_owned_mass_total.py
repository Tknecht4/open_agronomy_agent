"""A unit-owned field mass uses existing arithmetic, never a field target."""
import pytest
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools
from agronomy_agent.calculator_contracts import calculation_request_is_complete
from agronomy_agent.supplied_numeric_inputs import unit_owned_area_mass_total


@pytest.mark.parametrize('question,expected', [
    ('For 65 ha at 85 kg/ha, what is the total?', 5525),
    ('For 120 ha at 75 kg/ha, what is the total product mass?', 9000),
    ('For 18 hectares at 47.5 kg per hectare, compute the total mass.', 855),
    ('Calculate the total mass for 2.5 ha at 12 kg/ha.', 30),
    ('What is the total for 1,200 ha at 12.5 kg/ha?', 15000),
    ('For 8 ha with a supplied rate of 0 kg/ha, what is the total?', 0),
])
def test_unit_owned_mass_total_is_calculated_and_persisted_without_model(tmp_path, monkeypatch, question, expected):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    assert unit_owned_area_mass_total(question)
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready' and len(results) == 1
    assert plan.invocations[0].operation == 'field_product_total'
    assert results[0].payload['value'] == pytest.approx(expected)
    assert results[0].payload['unit'] == 'kg'
    assert calculation_request_is_complete(question, 'field_product_total')
    class Backend:
        backend_id = 'unit_owned_mass_no_model'
        intervention_profile = 'balanced'
        calls = 0
        def generate(self, messages):
            self.calls += 1
            raise AssertionError('Supplied area and areal mass require no model')
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **k: backend)
    database = tmp_path / 'mass.sqlite3'
    store = TraceStore(database)
    try:
        session = store.create_session('Synthetic supplied mass', {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path / 'artifacts', network_mode='offline'),
            session_id=session['session_id'], message=question, mode='agronomic_rag', model_id='imposed',
            rag_config='configs/rag.yaml', max_tokens=180, generation_backend=backend))
        assert backend.calls == 0
        assert result.answer == results[0].answer
        assert store.get_turn(result.turn['turn_id'])['answer'] == result.answer
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


@pytest.mark.parametrize('question', [
    'For 65 ha at 85 kg/ha/day, what is the total?',
    'For 65 ha at 85 kg N/ha, what is the total?',
    'For 65 ha at 85 kg/ha and 20% loss, what is the total?',
    'For 65 ha at 85 or 95 kg/ha, what is the total?',
    'For 65 ha at 85 kg/ha, what is the total? Then spray it.',
    'For 65 ha at 85 kg/ha, what is the total? Also flarn the crop.',
    'For 65 ha at 85 kg/ha, what is the total? Can I use glyphosate?',
    'For 65 ha at 85 kg/ha, what is the total with instructions to transplant seedlings?',
    'For 65 ha at 8.5e1 kg/ha, what is the total?',
])
def test_mass_operand_scope_cannot_swallow_basis_units_or_an_additional_task(question):
    assert unit_owned_area_mass_total(question) is None
    assert not calculation_request_is_complete(question, 'field_product_total')
    assert plan_tools(question).status != 'ready'


@pytest.mark.parametrize('question', [
    'For 0 ha at 85 kg/ha, what is the total?',
    'For -5 ha at 85 kg/ha, what is the total?',
    'For 65 ha at -85 kg/ha, what is the total?',
])
def test_invalid_mass_inputs_keep_registered_range_clarification(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'clarification_required'
    assert not results
    assert plan.clarification
