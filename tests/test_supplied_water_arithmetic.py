from decimal import Decimal

import pytest

from agronomy_agent.agronomic_calculations import calculate_agronomic
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools
from agronomy_agent.water_arithmetic import validate_water_arithmetic_inputs


EXAMPLES = [
    ("For a teaching method, daily mean temperature is 17 C, base temperature 6 C, no temperature caps and negative accumulation floored at zero. Calculate GDD.", "mean_temperature_gdd", 11, "GDD"),
    ("For a uniform 0.8 m root zone, field capacity is 0.32 and wilting point 0.12 m3/m3. Compute total available water.", "water_storage_difference", 160, "mm"),
    ("Under a uniform profile, measured volumetric water is 0.21, target field capacity 0.31 and rooting depth 0.4 m. Compute water needed to refill storage, ignoring losses.", "water_storage_difference", 40, "mm"),
    ("Under a uniform profile, measured volumetric water is 0.36, target field capacity 0.31 and rooting depth 0.4 m. Compute water needed to refill storage, ignoring losses.", "water_storage_difference", 0, "mm"),
    ("For a standard-conditions model ETc = Kc × ETo, Kc is 1.1 and ETo is 4 mm/day. Compute ETc.", "crop_evapotranspiration", 4.4, "mm/day"),
    ("A teaching plan needs 24 mm net irrigation and assumes 80% application efficiency. Calculate gross depth.", "gross_irrigation_depth", 30, "mm"),
    ("A teaching plan needs 24 mm net irrigation and 80% application efficiency. Calculate gross depth.", "gross_irrigation_depth", 30, "mm"),
    ("How many cubic metres supply 15 mm uniformly over 8 ha, ignoring losses?", "water_depth_volume", 1200, "m³"),
    ("A nozzle delivers 1.2 L/min, travel speed is 10 km/h and nozzle spacing 0.5 m. Using L/ha = 600Q/(speed × spacing), calculate application volume.", "single_nozzle_application_volume", 144, "L/ha"),
    ("A blend contains 16% K2O. How much blend supplies 48 kg K2O/ha, assuming the label basis is correct?", "fertilizer_product_mass", 300, "kg product/ha"),
    ("How much 25%-N fertilizer supplies 75 kg N/ha in a product-mass calculation?", "fertilizer_product_mass", 300, "kg product/ha"),
]


@pytest.mark.parametrize("question,operation,value,unit", EXAMPLES)
def test_named_supplied_quantities_use_typed_arithmetic(question, operation, value, unit):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == "ready", plan
    assert plan.invocations[0].operation == operation
    assert len(results) == 1 and results[0].status == "calculated"
    assert results[0].payload["value"] == pytest.approx(value)
    assert results[0].payload["unit"] == unit
    assert "does not choose an agronomic target" in results[0].answer


@pytest.mark.parametrize("question,operation,value,unit", EXAMPLES)
def test_full_production_response_keeps_all_typed_units_and_limits(tmp_path, monkeypatch, question, operation, value, unit):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    class Backend:
        backend_id = 'synthetic_no_model'
        intervention_profile = 'balanced'
        def generate(self, messages):
            raise AssertionError('complete supplied arithmetic must not need a model')
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, '_build_mlx_generator', lambda *a, **k: backend)
    database = tmp_path / 'arithmetic.sqlite3';store = TraceStore(database)
    try:
        session = store.create_session('Synthetic arithmetic', {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path/'artifacts', network_mode='offline'),
            session_id=session['session_id'], message=question, mode='agronomic_rag', model_id='imposed',
            rag_config='configs/rag.yaml', max_tokens=180, generation_backend=backend))
        expected = plan_and_execute_tools(question)[1][0].answer
        assert result.answer == expected
        assert store.get_turn(result.turn['turn_id'])['answer'] == expected
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


@pytest.mark.parametrize("question", [
    EXAMPLES[2][0] + ' Should I irrigate today?',
    EXAMPLES[4][0] + ' Then apply this depth.',
    EXAMPLES[7][0] + ' Is this safe to spray?',
    EXAMPLES[8][0] + ' Also recommend a field rate.',
    EXAMPLES[4][0] + ' State the weather provenance.',
    EXAMPLES[4][0] + ' Describe whether this establishes crop stage.',
    EXAMPLES[4][0] + ' And verify the weather station.',
    EXAMPLES[4][0] + ' Puis-je irriguer?',
    'Calculate ETc = Kc × ETo under water stress: Kc is 1.1, ETo is 4 mm/day and Ks is 0.5.',
    'For two soil layers, field capacity is 0.32 and wilting point 0.12 over a 0.8 m root zone. Compute available water.',
])
def test_extra_actions_or_unhandled_model_terms_are_not_swallowed(question):
    from agronomy_agent.supplied_water_parser import parse_supplied_water_calculation
    from agronomy_agent.supplied_nutrient_parser import parse_supplied_nutrient_calculation
    assert parse_supplied_water_calculation(question) is None
    assert parse_supplied_nutrient_calculation(question) is None


@pytest.mark.parametrize("question", [
    'A teaching plan needs 24 mm net irrigation and assumes 0% application efficiency. Calculate gross depth.',
    'A teaching plan needs 24 mm net irrigation and assumes 120% application efficiency. Calculate gross depth.',
    'A teaching plan needs 24 mm net irrigation and assumes 80% and 90% application efficiency. Calculate gross depth.',
    'For a standard-conditions model ETc = Kc × ETo, Kc is 1.1 and ETo is 4 mm/day or 5 mm/day. Compute ETc.',
    'A nozzle delivers 1.2 L/min or 1.5 L/min, travel speed is 10 km/h and nozzle spacing 0.5 m. Calculate application volume.',
    'For a uniform 0.8 m root zone, field capacity is 0.12 and wilting point 0.32 m3/m3. Compute total available water.',
    'A nozzle delivers 1.2 L/min, travel speed is 10 km/h and nozzle spacing -0.5 m. Calculate application volume.',
    'A nozzle delivers 1.2 L/min, travel speed is 0 km/h and nozzle spacing 0.5 m. Calculate application volume.',
    'A nozzle delivers 1.2 L/min, travel speed is 10 km/h and nozzle spacing 0.5 m. Using L/ha = 650Q/(speed × spacing), calculate application volume.',
    'A blend contains 16% P. How much blend supplies 48 kg P2O5/ha?',
])
def test_missing_conflicting_or_invalid_inputs_clarify(question):
    assert plan_tools(question).status == 'clarification_required'


@pytest.mark.parametrize("operation,inputs", [
    ('water_storage_difference', {'upper_volumetric': 1.1, 'lower_volumetric': .1, 'root_depth_m': .5, 'interpretation': 'available_capacity'}),
    ('water_storage_difference', {'upper_volumetric': .3, 'lower_volumetric': .1, 'root_depth_m': 0, 'interpretation': 'available_capacity'}),
    ('crop_evapotranspiration', {'crop_coefficient': True, 'reference_et_mm_per_day': 5}),
    ('crop_evapotranspiration', {'crop_coefficient': 'NaN', 'reference_et_mm_per_day': 5}),
    ('gross_irrigation_depth', {'net_depth_mm': 20, 'application_efficiency_pct': 0}),
    ('gross_irrigation_depth', {'net_depth_mm': 20, 'application_efficiency_pct': 101}),
    ('water_depth_volume', {'depth_mm': -2, 'area_ha': 5}),
    ('water_depth_volume', {'depth_mm': 20, 'area_ha': '1e100'}),
])
def test_water_readiness_rejects_the_same_inputs_as_execution(operation, inputs):
    with pytest.raises(ValueError) as preview:
        validate_water_arithmetic_inputs(operation, inputs)
    with pytest.raises(ValueError) as execution:
        calculate_agronomic(operation, inputs)
    assert str(preview.value) == str(execution.value)


def test_crop_coefficient_above_one_is_not_confused_with_an_efficiency_fraction():
    result = calculate_agronomic('crop_evapotranspiration', {'crop_coefficient': '1.2', 'reference_et_mm_per_day': '5'})
    assert result.value == Decimal('6')
    assert 'standard, unstressed' in result.answer()
    assert 'not a field moisture measurement' in result.answer()


@pytest.mark.parametrize("change", [
    {"mean_temp_c": True}, {"mean_temp_c": "NaN"}, {"mean_temp_c": "1e100"},
    {"method": "modified_corn"}, {"upper_cap_c": 30}, {"max_temp_c": 25},
])
def test_mean_gdd_rejects_invented_extremes_or_capping_methods(change):
    from agronomy_agent.agronomic_calculations import validate_mean_temperature_gdd_inputs
    inputs = {"mean_temp_c": 17, "base_temp_c": 6, "method": "daily_mean_no_temperature_caps", **change}
    with pytest.raises(ValueError) as preview:
        validate_mean_temperature_gdd_inputs(inputs)
    with pytest.raises(ValueError) as execution:
        calculate_agronomic("mean_temperature_gdd", inputs)
    assert str(preview.value) == str(execution.value)


@pytest.mark.parametrize("mean,expected", [(17, 11), (0, 0), (-4, 0)])
def test_mean_gdd_keeps_only_actual_temperature_inputs(mean, expected):
    plan, results = plan_and_execute_tools(f"Mean daily temperature is {mean} C, base 6 C, no upper cap, negative values are floored at zero. Calculate today's GDD.")
    assert plan.status == "ready"
    assert results[0].payload["value"] == expected
    assert set(plan.invocations[0].inputs) == {"mean_temp_c", "base_temp_c", "method"}
    assert "field-stage observation" in results[0].answer


@pytest.mark.parametrize("suffix", [" Should I spray now?", " What stage is my field?", " State weather provenance.", " Puis-je pulvériser maintenant?"])
def test_mean_temperature_math_does_not_consume_other_decisions(suffix):
    assert plan_tools(EXAMPLES[0][0] + suffix).status == "not_applicable"


@pytest.mark.parametrize("question", [
    EXAMPLES[0][0].replace("17 C", "17 C or 18 C"),
    EXAMPLES[0][0].replace("no temperature caps", "upper cap 30 C"),
    EXAMPLES[0][0].replace("negative accumulation floored at zero", "negative accumulation retained"),
    EXAMPLES[0][0].replace("17 C", "17 F"),
])
def test_mean_temperature_gdd_needs_one_complete_consistent_method(question):
    assert plan_tools(question).status == "clarification_required"


@pytest.mark.parametrize('formula', ['600Q/(speed + spacing)', '600Q/(speed × spacing) × 2',
    '600Q/(speed × spacing), L/ha = 650Q/(speed × spacing)'])
def test_nozzle_formula_cannot_silently_disagree_with_its_supplied_inputs(formula):
    question = f'A nozzle delivers 1.2 L/min, travel speed is 10 km/h and nozzle spacing 0.5 m. Using L/ha = {formula}, calculate application volume.'
    assert plan_tools(question).status == 'clarification_required'


@pytest.mark.parametrize('question', [
    'A teaching plan needs 24 or 30 mm net irrigation and 80% application efficiency. Calculate gross depth.',
    'How many cubic metres supply 15 or 20 mm uniformly over 8 ha?',
])
def test_alternatives_before_the_shared_unit_need_clarification(question):
    plan, results = plan_and_execute_tools(question)
    assert plan.status == 'clarification_required'
    assert not results


@pytest.mark.parametrize('directive', ['Harvest corn.', 'Mow the pasture.', 'Drive into the field.', 'Plant corn.', 'Seed barley.', 'Feed the cattle.', 'Graze the pasture.', 'Récoltez le maïs.'])
def test_an_extra_farm_imperative_is_not_consumed_by_calculator(directive):
    assert plan_tools('A teaching plan needs 24 mm net irrigation and 80% application efficiency. Calculate gross depth. ' + directive).status == 'not_applicable'
