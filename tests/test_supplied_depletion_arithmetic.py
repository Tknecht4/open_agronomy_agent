"""FAO-56 supplied RAW = p × TAW arithmetic, never a selected field trigger."""
from decimal import Decimal
import pytest
from agronomy_agent.agronomic_calculations import calculate_agronomic
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools
from agronomy_agent.calculator_contracts import calculation_request_is_complete
from agronomy_agent.supplied_depletion_request import supplied_depletion_request


EXAMPLES = [
    ('A teaching root zone holds 100 mm total available water and allows 40% depletion. What is the depletion trigger, and why is it crop/context dependent?', 40),
    ('Total available water is 150 mm and supplied depletion fraction is 0.3. Calculate readily available water.', 45),
    ('TAW is 80 mm, p is 25%. Compute RAW.', 20),
    ('The hypothetical root-zone holds 70 mm total available soil water and assumes 0% depletion. Calculate allowable depletion.', 0),
    ('TAW is 90 mm and depletion fraction is 1. Compute the allowable depletion.', 90),
]


@pytest.mark.parametrize('question,expected', EXAMPLES)
def test_supplied_capacity_and_fraction_compute_without_choosing_a_field_threshold(tmp_path, monkeypatch, question, expected):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready' and len(results) == 1
    assert plan.invocations[0].operation == 'allowable_water_depletion'
    assert results[0].payload['value'] == pytest.approx(expected)
    assert results[0].payload['unit'] == 'mm'
    assert calculation_request_is_complete(question, 'allowable_water_depletion')
    assert 'crop, growth stage, soil and evaporative demand' in results[0].answer
    assert 'does not choose it' in results[0].answer
    assert 'management-allowed depletion limit can differ from physiological RAW' in results[0].answer
    class Backend:
        backend_id = 'supplied_depletion_no_model'
        intervention_profile = 'balanced'
        calls = 0
        def generate(self, messages):
            self.calls += 1
            raise AssertionError('Fully supplied depletion arithmetic requires no model')
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **k: backend)
    database = tmp_path / 'depletion.sqlite3'
    store = TraceStore(database)
    try:
        session = store.create_session('Synthetic supplied water', {}, {})
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


@pytest.mark.parametrize('question,needed', [
    ('TAW is 100 mm. Calculate RAW.', 'depletion fraction'),
    ('Supplied depletion fraction is 40%. Calculate allowable depletion.', 'total available water'),
    ('TAW is 100 mm and p is 40. Calculate RAW.', 'zero to one'),
    ('TAW is -100 mm and p is 0.4. Calculate RAW.', 'nonnegative'),
    ('TAW is 100 mm and p is -0.4. Calculate RAW.', 'nonnegative'),
])
def test_missing_or_invalid_supplied_water_values_are_not_guessed(question, needed):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'clarification_required'
    assert not results
    assert needed in plan.clarification


@pytest.mark.parametrize('extra', [
    ' Should I irrigate today?',
    ' Then apply this depth.',
    ' Can I use a pesticide?',
    ' Also flarn the crop.',
    ' With instructions to transplant seedlings.',
    ' What fraction should I use for corn?',
    ' And explain the soil map legend.',
    ' TAW is also 200 mm.',
])
def test_depletion_arithmetic_cannot_erase_unknown_or_field_decision_tails(extra):
    question = EXAMPLES[0][0] + extra
    assert supplied_depletion_request(question) is None
    assert not calculation_request_is_complete(question, 'allowable_water_depletion')
    assert plan_tools(question).status != 'ready'


@pytest.mark.parametrize('question', [
    'TAW is 100 mm/day and p is 0.4. Calculate RAW.',
    'TAW is 100 or 120 mm and p is 0.4. Calculate RAW.',
    'TAW is 100 mm and p is 0.4 or 0.5. Calculate RAW.',
    'TAW is 100 mm and p is 0.4. Choose an irrigation schedule.',
])
def test_compound_units_alternate_values_and_unsupplied_targets_have_no_depletion_bypass(question):
    assert supplied_depletion_request(question) is None
    assert plan_tools(question).status != 'ready'


@pytest.mark.parametrize('inputs', [
    {'total_available_water_mm': 100, 'depletion_fraction': 1.1},
    {'total_available_water_mm': -100, 'depletion_fraction': .4},
    {'total_available_water_mm': 100, 'depletion_fraction': True},
    {'total_available_water_mm': float('nan'), 'depletion_fraction': .4},
    {'total_available_water_mm': 100, 'depletion_fraction': .4, 'unowned_depth_mm': 20},
])
def test_registered_depletion_operation_rejects_invalid_or_unowned_inputs(inputs):
    with pytest.raises(ValueError):
        calculate_agronomic('allowable_water_depletion', inputs)


def test_depletion_calculation_has_exact_supplied_input_scaling_and_bounds():
    for total in [Decimal('0'), Decimal('37.5'), Decimal('120')]:
        values = [calculate_agronomic('allowable_water_depletion',
            {'total_available_water_mm': total, 'depletion_fraction': p}).value for p in [Decimal('0'), Decimal('.25'), Decimal('1')]]
        assert values[0] == 0 and values[-1] == total
        assert values[0] <= values[1] <= values[-1]
