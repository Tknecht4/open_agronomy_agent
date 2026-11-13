from decimal import Decimal

import pytest

from agronomy_agent.agronomic_calculations import calculate_agronomic, validate_grain_moisture_inputs
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools


QUESTION = 'Grain mass is 12 t at 25% wet-basis moisture. Calculate dry matter and equivalent mass at 10% moisture, ignoring losses.'


def test_grain_weight_preserves_dry_matter_and_does_not_choose_storage_target():
    plan, results = plan_and_execute_tools(QUESTION)
    assert plan.status == 'ready'
    assert results[0].operation == 'grain_moisture_adjustment'
    assert results[0].payload['value'] == 10
    assert results[0].payload['unit'] == 't'
    assert 'dry matter = 12 t × (1 − 25/100) = 9 t' in results[0].answer
    assert 'does not select a safe storage moisture' in results[0].answer
    assert 'handling losses are excluded' in results[0].answer


@pytest.mark.parametrize('change', [
    {'initial_moisture_pct': 100}, {'target_moisture_pct': 100}, {'target_moisture_pct': -1},
    {'mass_unit': 'bushels'}, {'wet_mass': True}, {'wet_mass': 'Infinity'}, {'wet_mass': '1e100'},
])
def test_grain_preview_and_execution_share_rejection(change):
    inputs = {'wet_mass': 12, 'mass_unit': 't', 'initial_moisture_pct': 25, 'target_moisture_pct': 10, **change}
    with pytest.raises(ValueError) as preview:
        validate_grain_moisture_inputs(inputs)
    with pytest.raises(ValueError) as execution:
        calculate_agronomic('grain_moisture_adjustment', inputs)
    assert str(preview.value) == str(execution.value)


def test_zero_moisture_and_mass_are_values_not_missing_inputs():
    result = calculate_agronomic('grain_moisture_adjustment', {'wet_mass': 0, 'mass_unit': 'kg', 'initial_moisture_pct': 0, 'target_moisture_pct': 0})
    assert result.value == Decimal(0)


@pytest.mark.parametrize('supplied,unit', [('12 t/ha', 't/ha'), ('12 tonnes per acre', 't/ac'), ('12 lb/ac', 'lb/ac')])
def test_grain_adjustment_never_discards_a_yield_area_denominator(supplied, unit):
    question = QUESTION.replace('12 t', supplied)
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready'
    assert results[0].payload['value'] == 10
    assert results[0].payload['unit'] == unit


@pytest.mark.parametrize('question', [QUESTION + ' Should I store this now?', QUESTION + ' Puis-je stocker maintenant?',
    QUESTION + ' Also recommend a storage target.', QUESTION.replace('wet-basis', 'dry-basis')])
def test_grain_arithmetic_does_not_answer_a_storage_decision_or_assume_the_basis(question):
    assert plan_tools(question).status == 'not_applicable'


def test_production_save_keeps_both_derived_results(tmp_path, monkeypatch):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    class Backend:
        backend_id = 'synthetic_no_model'
        intervention_profile = 'balanced'
        def generate(self, messages):
            raise AssertionError('supplied grain accounting must not need a model')
        def close(self):
            pass
    backend = Backend();monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **k: backend)
    database = tmp_path / 'grain.sqlite3';store = TraceStore(database)
    try:
        session = store.create_session('Synthetic grain accounting', {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path/'artifacts', network_mode='offline'),
            session_id=session['session_id'], message=QUESTION, mode='agronomic_rag', model_id='imposed',
            rag_config='configs/rag.yaml', max_tokens=180, generation_backend=backend))
        assert result.answer == plan_and_execute_tools(QUESTION)[1][0].answer
        assert store.get_turn(result.turn['turn_id'])['answer'] == result.answer
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


@pytest.mark.parametrize('question', [
    QUESTION.replace('12 t', '12 t or 14 t'),
    QUESTION.replace('12 t', '12 t and 14 t'),
    QUESTION.replace('25% wet-basis', '25% or 30% wet-basis'),
    QUESTION.replace('25% wet-basis', '25% and 30% wet-basis'),
    QUESTION.replace('10% moisture', '10% or 15% moisture'),
])
def test_unlabelled_alternatives_never_become_a_selected_grain_operand(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'clarification_required'
    assert not results
