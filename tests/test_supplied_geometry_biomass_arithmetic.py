from decimal import Decimal

import pytest

from agronomy_agent.agronomic_calculations import (
    calculate_agronomic, validate_circular_sampling_area_inputs, validate_grain_harvest_index_inputs,
)
from agronomy_agent.tool_planner import plan_and_execute_tools, plan_tools

HI = 'Total above-ground dry biomass is 12 t/ha and grain dry mass is 4.2 t/ha. Compute harvest index.'
CIRCLE = 'Calculate area of a circular sampling plot with radius 12 metres. Explain why this is not the field area.'


def test_grain_ratio_uses_common_dry_mass_and_preserves_percentage():
    plan, rows = plan_and_execute_tools(HI)
    assert plan.status == 'ready'
    result = rows[0]
    assert result.operation == 'grain_harvest_index'
    assert result.payload['value'] == .35
    assert '(35%)' in result.answer
    assert 'includes grain' in result.answer
    assert 'does not determine harvest timing' in result.answer


def test_circle_keeps_footprint_and_boundary_area_distinct():
    plan, rows = plan_and_execute_tools(CIRCLE)
    assert plan.status == 'ready'
    assert rows[0].payload['value'] == pytest.approx(452.389342, abs=.000001)
    assert rows[0].payload['unit'] == 'm²'
    assert '0.045 ha' in rows[0].answer
    assert 'sampling radius rather than a mapped field boundary' in rows[0].answer


@pytest.mark.parametrize('question', [
    HI.replace('4.2 t/ha', '4.2 kg/ha'), HI.replace('4.2 t/ha', '4.2 t/ac'),
    HI.replace('4.2 t/ha', '13 t/ha'), HI.replace('4.2 t/ha', '-1 t/ha'),
    HI.replace('12 t/ha', '0 t/ha'), HI.replace('4.2 t/ha', '4.2 or 5 t/ha'),
    CIRCLE.replace('12 metres', '-12 metres'), CIRCLE.replace('12 metres', '12 or 14 metres'),
])
def test_ambiguous_units_or_invalid_values_need_clarification(question):
    assert plan_tools(question).status == 'clarification_required'


@pytest.mark.parametrize('question', [
    HI.replace('grain dry mass', 'grain wet mass'), HI.replace('above-ground', 'below-ground'),
    HI + ' Should I harvest tomorrow?', HI + ' Proceed with planting.',
    CIRCLE + ' Then drain the field.', CIRCLE.replace('radius', 'diameter'),
    CIRCLE.replace('circular sampling plot', 'sampling ring'),
    CIRCLE.replace('circular sampling plot', 'semicircular sampling plot'),
    CIRCLE.replace('circular sampling plot', 'elliptical sampling plot'),
    CIRCLE.replace('circular sampling plot', 'sampling plot'),
    CIRCLE.replace('circular sampling plot', 'half of a circular sampling plot'),
    HI.replace('Compute harvest index.', 'The biomass value does not include grain. Compute harvest index.'),
    HI.replace('Compute harvest index.', 'Grain is not included in the biomass value. Compute harvest index.'),
    HI.replace('Compute harvest index.', 'The biomass value is not including grain. Compute harvest index.'),
    *[HI.replace('Compute harvest index.', suffix + ' Compute harvest index.') for suffix in (
        'The biomass excludes grain.', 'The biomass omits grain.', 'The biomass contains no grain.',
        'Grain was left out of the biomass.', 'The biomass is stover only.',
    )],
    HI + ' Explain why this is not the field area.',
    CIRCLE.replace('Explain why this is not the field area.', 'Explain why this crop is failing.'),
])
def test_unrepresented_bases_shapes_or_advice_are_not_swallowed(question):
    assert plan_tools(question).status == 'not_applicable'


@pytest.mark.parametrize('operation,validator,inputs', [
    ('grain_harvest_index', validate_grain_harvest_index_inputs, {'grain_dry_mass': True, 'aboveground_dry_mass': 12, 'mass_unit': 't'}),
    ('grain_harvest_index', validate_grain_harvest_index_inputs, {'grain_dry_mass': 6, 'aboveground_dry_mass': 4, 'mass_unit': 't'}),
    ('circular_sampling_area', validate_circular_sampling_area_inputs, {'radius_m': 'Infinity'}),
    ('circular_sampling_area', validate_circular_sampling_area_inputs, {'radius_m': '1e100'}),
    ('circular_sampling_area', validate_circular_sampling_area_inputs, {'radius_m': 12, 'diameter_m': 24}),
])
def test_preview_and_execution_share_validation(operation, validator, inputs):
    with pytest.raises(ValueError) as preview:
        validator(inputs)
    with pytest.raises(ValueError) as execution:
        calculate_agronomic(operation, inputs)
    assert str(preview.value) == str(execution.value)


def test_zero_grain_or_zero_radius_are_values():
    assert calculate_agronomic('grain_harvest_index', {'grain_dry_mass': 0, 'aboveground_dry_mass': 12, 'mass_unit': 't'}).value == Decimal(0)
    assert calculate_agronomic('circular_sampling_area', {'radius_m': 0}).value == Decimal(0)
