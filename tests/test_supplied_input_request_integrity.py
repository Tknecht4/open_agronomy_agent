"""Whole input/request regressions from independent composed-source review."""
import pytest

from agronomy_agent.answerability import is_mechanism_explanation
from agronomy_agent.decision_route import build_decision_route_state
from agronomy_agent.plant_health_scope import clubroot_question_scope
from agronomy_agent.router import classify_query, refine_query_route
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools


@pytest.mark.parametrize('question', [
    'For a uniform profile, field capacity is 0,31, wilting point 0,15 and rooting depth 0.4 m. Compute total available water.',
    'For a standard-conditions model ETc = Kc × ETo, Kc is 1/day and ETo is 4 mm/day. Compute ETc.',
    'For a standard-conditions model ETc = Kc × ETo, Kc is 0,9 and ETo is 4 mm/day. Compute ETc.',
    'For a standard-conditions model ETc = Kc × ETo, Kc is 0.11e1 and ETo is 4 mm/day. Compute ETc.',
    'Calculate harvest index from 1e3 kg grain dry mass and 2000 kg total above-ground dry biomass.',
    'Calculate harvest index from 4,2 t/ha grain dry mass and 12 t/ha total above-ground dry biomass.',
    'Calculate daily GDD from Tmax 25,0 C, Tmin 9,0 C and base 7,0 C with no temperature caps.',
    'Grain mass is 12 t at 25% wet-basis moisture. Calculate equivalent mass at 10% moisture, including 5% dry-matter loss.',
    'Grain mass is 12 t at 25% wet-basis moisture. Calculate equivalent mass at 10% moisture, including respiration losses.',
    'How much 25%-N fertilizer supplies 75 kg N/ha/day?',
    'How much 25%-N fertilizer supplies 75 kg N/ha per day?',
    'Calculate apparent nutrient balance: 85 kg N/ha applied and 60 kg N/ha removed, plus 10 kg N/ha supplied in irrigation water.',
    'Calculate area of a circular sampling plot with radius 12 metres, excluding 5 m2 occupied by a tree.',
    'Total above-ground dry biomass is 12 t/ha and grain dry mass is 4.2 t/ha. Compute harvest index and biomass per plant for a stand of 40 plants/m2.',
    'Total above-ground dry biomass is 12 t/ha and grain dry mass is 4.2 t/ha. Compute harvest index and biomass per plant.',
])
def test_unrepresented_or_malformed_inputs_never_produce_calculator_only_answer(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status != 'ready'
    assert not results


@pytest.mark.parametrize('question,value', [
    ('Calculate harvest index from 1,000 kg grain dry mass and 2,000 kg total above-ground dry biomass.', .5),
    ('Grain mass is 12,000 kg at 25% wet-basis moisture. Calculate equivalent mass at 10% moisture, ignoring losses.', 10000),
    ('For a standard-conditions model ETc = Kc × ETo, Kc is .9 and ETo is 4 mm/day. Compute ETc.', 3.6),
    ('Compute fertilizer product rate: how much 25%-N fertilizer supplies 75 kg N/ha across 16 ha?', 300),
    ('Calculate daily GDD from Tmax 25.0 C, Tmin 9.0 C and base 7.0 C with no temperature caps.', 10),
])
def test_valid_decimals_thousands_and_incidental_area_keep_their_contract(question, value):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready', plan
    assert results[0].payload['value'] == pytest.approx(value)


@pytest.mark.parametrize('directive', ['Thin the stand.', 'Reseed the field.', 'Mulch the bed.', 'Transplant the seedlings.', 'Mulch beds.', 'Transplant seedlings.'])
def test_an_unknown_followup_cannot_inherit_an_explanation_or_calculation_bypass(directive):
    question = 'Why does cold slow emergence? ' + directive
    assert not is_mechanism_explanation(question)
    route = refine_query_route(question, classify_query(question))
    assert route.question_type != 'exam_review' and route.risk_level != 'low'
    arithmetic = 'Daily mean temperature is 17 C, base temperature 6 C, no temperature caps and negative accumulation floored at zero. Calculate GDD. '
    for complete in [arithmetic + directive, arithmetic.rstrip('. ') + ' and ' + directive,
                     arithmetic.rstrip('. ') + ', ' + directive]:
        assert plan_tools(complete).status == 'not_applicable'
        routed = refine_query_route(complete, classify_query(complete))
        assert routed.question_type != 'exam_review' and routed.risk_level != 'low'


def test_coordinated_explanation_does_not_authorize_mixing():
    assert not is_mechanism_explanation('Explain why soil acidifies and mix fertilizer with irrigation water.')


@pytest.mark.parametrize('reference', ['Adjacent corn looks healthy.', 'Nearby wheat is normal.', 'And adjacent corn looks healthy.'])
def test_healthy_reference_crop_does_not_erase_affected_canola(reference):
    question = 'My canola roots are swollen. Could this be clubroot? ' + reference
    scope = clubroot_question_scope(question)
    assert scope.host_scope == 'susceptible' and scope.current_symptoms
    assert scope.confirmation_requested
    assert build_decision_route_state(question, 'plant_health').decision == 'clubroot_containment'


@pytest.mark.parametrize('question', [
    'My canola is stunted, but roots are not swollen and there are no galls. Could this be clubroot?',
    'My canola has no root galls. Is this clubroot?',
])
def test_negative_root_observations_are_preserved_in_route_and_fallback(question):
    from agronomy_agent.answer_verifier import _decision_route_failure_answer
    scope = clubroot_question_scope(question)
    assert scope.negative_root_symptoms and not scope.current_symptoms
    route = build_decision_route_state(question, 'plant_health')
    # A fallback must not turn a diagnostic question into positive evidence.
    answer = _decision_route_failure_answer(route, jurisdiction=None)
    assert 'You report:' in answer
    for observation in scope.negated_root_observations:
        assert observation in answer
    if 'not swollen' not in question:
        assert 'no swollen roots' not in answer
    assert 'Treat this as suspected clubroot' not in answer
    assert 'photograph the pattern and galls' not in answer
    assert 'representative sample' in answer


def test_soil_history_precautions_do_not_replace_current_other_crop_inspection():
    from agronomy_agent.answer_verifier import _decision_route_failure_answer
    question = 'My corn roots are swollen this season. Previous canola had clubroot. What soil-movement precautions and corn inspection are needed?'
    scope = clubroot_question_scope(question)
    assert scope.host_scope == 'other' and scope.symptomatic_other_crop
    route = build_decision_route_state(question, 'plant_health')
    answer = _decision_route_failure_answer(route, jurisdiction=None)
    assert 'current-crop symptoms separately' in answer
    assert 'soil movement' in answer and 'sanitation' in answer
    assert 'historical disease name does not diagnose' in answer


def test_route_rejects_affirmative_signs_that_overwrite_reported_absence():
    question = 'My canola has no root galls. Is this clubroot?'
    route = build_decision_route_state(question, 'plant_health')
    assert 'clubroot_negative_observation_overwritten' in route.answer_violations(
        'Your roots are swollen. Arrange confirmation and follow sanitation guidance.')
    assert 'clubroot_negative_observation_overwritten' not in route.answer_violations(
        'Your roots are not swollen. Arrange confirmation if concern remains and follow sanitation guidance.')


def test_route_requires_both_explicit_current_inspection_and_history_precautions():
    question = 'My corn roots are swollen this season. Previous canola had clubroot. What soil-movement precautions and corn inspection are needed?'
    route = build_decision_route_state(question, 'plant_health')
    assert 'current_crop_inspection_not_answered' in route.answer_violations('Follow sanitation guidance and limit soil movement.')
    assert 'current_crop_inspection_not_answered' not in route.answer_violations(
        'Follow sanitation guidance and limit soil movement. Compare affected and normal corn roots and plants.')


@pytest.mark.parametrize('question,draft,required', [
    ('My canola has no root galls. Is this clubroot?',
     'Your roots are swollen and clubroot is confirmed. Follow sanitation guidance and arrange confirmation.',
     'You report: no root galls'),
    ('My corn roots are swollen this season. Previous canola had clubroot. What soil-movement precautions and corn inspection are needed?',
     'Follow sanitation guidance and limit soil movement.', 'current-crop symptoms separately'),
])
def test_production_persistence_keeps_observation_roles_and_both_requested_workflows(tmp_path, monkeypatch, question, draft, required):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    class Backend:
        backend_id = 'synthetic_composed_integrity'
        intervention_profile = 'balanced'
        def generate(self, messages):
            return draft
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *args, **kwargs: backend)
    database = tmp_path/'integrity.sqlite3'
    store = TraceStore(database)
    try:
        session = store.create_session('Synthetic role-integrity review', {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(
            store=store, settings=build_settings(db_path=database, artifact_root=tmp_path/'artifacts', network_mode='offline'),
            session_id=session['session_id'], message=question, mode='agronomic_rag', model_id='imposed',
            rag_config='configs/rag.yaml', max_tokens=180, generation_backend=backend))
        assert required in result.answer
        assert store.get_turn(result.turn['turn_id'])['answer'] == result.answer
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


@pytest.mark.parametrize('question', [
    'Calculate seed rate for 80 plants/m2 target, TKW 4.5 g, germination is 9,6%, and overall emergence is 75%.',
    'Calculate seed rate for 80 plants/m2 target, TKW 4.5 g, germination is 96%, and overall emergence is 0,75%.',
    'Calculate seed rate for 80 plants/m2 target, TKW 4.5 g, germination is 96%, overall emergence is 75%, seed purity 90%.',
    'Calculate daily GDD from Tmax 25 C/hour, Tmin 9 C/hour and base 7 C.',
    'Calculate daily GDD. {"max_temp_C":25,"min_temp_C":9,"base_temp_C":7,"upper_cap_F":77}',
])
def test_seed_and_gdd_cannot_drop_unsupported_notation_units_or_keys(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status != 'ready'
    assert not results


@pytest.mark.parametrize('question', [
    'Explain why soil acidifies and topdress wheat.',
    'Explain why cold slows emergence and weed the field.',
    'Explain why cold slows emergence and improve soil drainage.',
    'Why does cold slow emergence, mulch the field?',
])
def test_verb_spelling_and_comma_syntax_do_not_authorize_an_operational_followup(question):
    assert not is_mechanism_explanation(question)
    route = refine_query_route(question, classify_query(question))
    assert route.question_type != 'exam_review' and route.risk_level != 'low'


def test_a_comma_does_not_hide_a_command_from_the_calculator():
    question = 'Daily mean temperature is 17 C, base temperature 6 C, no temperature caps and negative accumulation floored at zero. Calculate GDD, thin the stand.'
    assert plan_tools(question).status == 'not_applicable'


@pytest.mark.parametrize('comparison', [
    'compared with normal plants elsewhere in the same field',
    'next to healthy corn',
])
def test_a_reference_inside_the_affected_clause_does_not_erase_current_symptoms(comparison):
    scope = clubroot_question_scope(f'My canola roots are swollen {comparison}. Could this be clubroot?')
    assert scope.host_scope == 'susceptible' and scope.current_symptoms and scope.confirmation_requested


@pytest.mark.parametrize('question', [
    'Explain soil texture, structure and porosity.',
    'What are photosynthesis and respiration?',
    'Explain soil texture and soil structure.',
])
def test_coordinated_concept_definitions_remain_direct_low_risk_explanations(question):
    route = refine_query_route(question, classify_query(question))
    assert route.question_type == 'exam_review' and route.risk_level == 'low'


@pytest.mark.parametrize('question', [
    'Calculate break-even price from total cost CAD 40,50/ac and expected yield 50 bu/ac.',
    'Calculate how much area will a 1000 L sprayer tank cover applying 10,0 L/ha, ignoring unusable tank volume?',
])
def test_reachable_legacy_cost_and_tank_extractors_use_the_same_number_contract(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status != 'ready'
    assert not results


def test_deep_unrecognized_gdd_data_is_clarified_without_an_uncaught_decoder_error():
    nested = '[' * 1100 + '0' + ']' * 1100
    question = 'Calculate daily GDD. {"max_temp_C":25,"min_temp_C":9,"base_temp_C":7,"extra":' + nested + '}'
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'clarification_required' and not results


@pytest.mark.parametrize('tail', ['Mulch beds.', 'Transplant seedlings.'])
def test_verified_daily_gdd_evidence_is_retained_while_extra_operations_need_a_complete_response(tail):
    from types import SimpleNamespace
    from agronomy_agent.agent import deterministic_tool_response
    from agronomy_agent.answerability import assess_answerability
    question = 'Calculate daily GDD from Tmax 24 C, Tmin 8 C and base 6 C, ' + tail
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready' and results[0].payload['value'] == 10
    records = [row.to_dict() for row in results]
    context = SimpleNamespace(runtime_metadata={'tool_plan': plan.to_dict(), 'tool_results': records})
    assert deterministic_tool_response(context, question=question) == (None, None)
    assert context.runtime_metadata['tool_results'] == records
    decision = assess_answerability(question, tool_plan=plan.to_dict(), tool_results=records)
    assert decision.reason != 'validated_deterministic_tool_result_available'


def test_renderer_owned_boundary_only_completes_the_matching_operation():
    from agronomy_agent.calculator_contracts import calculation_request_is_complete
    question = 'Calculate area of a circular sampling plot with radius 12 metres. Explain why this is not the field area.'
    assert calculation_request_is_complete(question, 'circular_sampling_area')
    assert not calculation_request_is_complete(question, 'grain_harvest_index')


def test_named_gdd_note_is_context_and_does_not_supply_a_new_request_or_operand():
    from types import SimpleNamespace
    from agronomy_agent.agent import deterministic_tool_response
    question = 'Calculate GDD. {"max_temp_C":24,"min_temp_C":8,"base_temp_C":6,"note":"State the weather provenance"}'
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready' and results[0].payload['value'] == 10
    context = SimpleNamespace(runtime_metadata={'tool_plan':plan.to_dict(), 'tool_results':[r.to_dict() for r in results]})
    assert deterministic_tool_response(context, question=question)[1] == 'deterministic_tool_result'


@pytest.mark.parametrize('prefix', ['Can you', 'Could you please', 'Please would you', "I'd like you to", '  Will you'])
@pytest.mark.parametrize('tail', [', mulch beds.', ' and transplant seedlings.', '. Mulch beds.'])
def test_polite_calculation_wrappers_cannot_drop_a_second_request(prefix, tail):
    from types import SimpleNamespace
    from agronomy_agent.agent import deterministic_tool_response
    from agronomy_agent.calculator_contracts import calculation_request_is_complete
    question = prefix + ' calculate daily GDD from Tmax 24 C, Tmin 8 C and base 6 C' + tail
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready' and results[0].payload['value'] == 10
    assert not calculation_request_is_complete(question, 'daily_gdd')
    context = SimpleNamespace(runtime_metadata={'tool_plan':plan.to_dict(), 'tool_results':[r.to_dict() for r in results]})
    assert deterministic_tool_response(context, question=question) == (None, None)
    route = refine_query_route(question, classify_query(question))
    assert route.question_type != 'exam_review' and route.risk_level != 'low'


@pytest.mark.parametrize('question', [
    'Can you calculate daily GDD from Tmax 24 C, Tmin 8 C and base 6 C?',
    'Could you please calculate daily GDD from Tmax 24 C, Tmin 8 C and base 6 C?',
    'Ignoring unusable tank volume, how much area will a 1000 L sprayer tank cover applying 100 L/ha?',
    'For one day in a corn field, maximum temperature was 24°C and minimum temperature was 8°C. Using a 6°C base and no temperature caps, calculate growing degree days.',
    'What yield breaks even from total cost CAD 400/ac and assumed price CAD 5/bu?',
])
def test_accepted_request_phrasings_keep_complete_deterministic_results(question):
    from types import SimpleNamespace
    from agronomy_agent.agent import deterministic_tool_response
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'ready' and results
    context = SimpleNamespace(runtime_metadata={'tool_plan':plan.to_dict(), 'tool_results':[r.to_dict() for r in results]})
    assert deterministic_tool_response(context, question=question)[1] == 'deterministic_tool_result'


def test_unrecognized_calculation_head_still_inspects_unknown_tails():
    from agronomy_agent.calculator_contracts import calculation_request_is_complete
    assert not calculation_request_is_complete('Daily GDD from Tmax 24 C, Tmin 8 C and base 6 C, mulch beds.', 'daily_gdd')
    assert not calculation_request_is_complete('Ignoring unusable tank volume, how much area will a 1000 L sprayer tank cover applying 100 L/ha, calculate fertilizer needs.', 'tank_coverage')
    assert not calculation_request_is_complete('Using mulch beds, calculate daily GDD from Tmax 24 C, Tmin 8 C and base 6 C.', 'daily_gdd')


@pytest.mark.parametrize('prefix', ['Mulch beds. ', 'Transplant seedlings, ',
    'Maximum temperature was 24 C then mulch beds. ',
    'Maximum temperature was 24 C also mulch beds. ',
    'Maximum temperature was 24 C and mulch beds. '])
def test_a_later_calculation_cannot_erase_an_earlier_request(prefix):
    from agronomy_agent.calculator_contracts import calculation_request_is_complete
    question = prefix + 'Calculate daily GDD from Tmax 24 C, Tmin 8 C and base 6 C.'
    assert not calculation_request_is_complete(question, 'daily_gdd')
    route = refine_query_route(question, classify_query(question))
    assert route.question_type != 'exam_review' and route.risk_level != 'low'


@pytest.mark.parametrize('question', [
    'Can you explain soil texture, structure and porosity?',
    'Could you please explain soil texture and soil structure?',
])
def test_polite_concept_lists_do_not_become_operational_requests(question):
    route = refine_query_route(question, classify_query(question))
    assert route.risk_level == 'low'
    assert route.question_type in {'conceptual', 'exam_review'}
