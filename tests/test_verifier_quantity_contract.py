from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import assess_claim_risk, _looks_incomplete
from agronomy_agent.quantity_claims import unsupported_quantities


@pytest.mark.parametrize(('source', 'answer', 'unsupported'), [
    ('Mass: 120 kg.', 'Mass: 20 kg.', True),
    ('Mass: 120 kg.', 'Mass: 120 kg.', False),
    ('Mass: 20 kg.', 'Rate: 20 kg/ha.', True),
    ('Mass: 1,200 kilograms.', 'Mass: 1200 kg.', False),
    ('Temperature: -5 C.', 'Temperature: 5 C.', True),
    ('Depth: 2 to 4 inches.', 'Depth: 2–4 inches.', False),
    ('Mass: 120 kg.', '20 kg is an error; the source records 120 kg.', False),
    ('Mass: 120 kg.', 'The mass is not less than 20 kg.', True),
])
def test_quantities_are_complete_values_with_units(source, answer, unsupported):
    assert bool(unsupported_quantities(answer, question='Read the record.', evidence=source)) is unsupported


@pytest.mark.parametrize(('answer', 'unsupported'), [
    ('The total is 300 kg because 12 × 25 = 300.', False),
    ('The total is 25 kg because 12 bags weigh 25 kg each.', True),
    ('The total is 250 kg because 12 × 25 = 250.', True),
    ('The total is 300 lb.', True),
    ('The total is 300 kg. Apply 300 kg/ha.', True),
    ('12 × 12 = 300.', True),
])
def test_total_relation_requires_grounded_operands_and_units(answer, unsupported):
    values = unsupported_quantities(answer, question='What is the total mass of 12 bags weighing 25 kg each?',
                                   evidence='There are 12 bags and each bag weighs 25 kg.')
    assert bool(values) is unsupported


def test_unseen_container_values_and_conflicting_premises():
    q = 'What is the total weight of 7 boxes weighing 2.5 pounds each?'
    assert not unsupported_quantities('The total weight is 17.5 lb.', question=q, evidence='')
    assert unsupported_quantities('The total weight is 17.5 lb.', question=q, evidence='There are 9 boxes.')


def test_arithmetic_does_not_grant_action_permission():
    assessment = assess_claim_risk('The total is 300 kg. You can spray now because it is dry.',
        question='What is the total mass of 12 bags weighing 25 kg each?',
        question_type='product_label', risk_level='high')
    assert 'unsupported_regulated_permission' in assessment.reasons


@pytest.mark.parametrize(('answer', 'incomplete'), [
    ('The total is 300.', False), ('12 × 25 = 300.', False),
    ('First item.\n2.', True), ('1)', True), ('Next steps:\n-', True),
])
def test_terminal_number_is_not_a_dangling_list(answer, incomplete):
    assert _looks_incomplete(answer) is incomplete


@pytest.mark.parametrize(('source', 'answer', 'unsupported'), [
    ('Gray leaf spot was ruled out by the laboratory.', 'The diagnosis is not gray leaf spot; the cause remains unknown.', False),
    ('Gray leaf spot was not ruled out by the laboratory.', 'The diagnosis is not gray leaf spot.', True),
    ('Gray leaf spot may be ruled out after testing.', 'The diagnosis is not gray leaf spot.', True),
    ('Rust was ruled out by the laboratory.', 'The diagnosis is not gray leaf spot.', True),
    ('Gray leaf spot is possible.', 'The diagnosis is gray leaf spot.', True),
    ('The source mentions *Cercospora zeae*.', 'The diagnosis is *Cercospora zeae*.', True),
])
def test_diagnosis_polarity_needs_source_support(source, answer, unsupported):
    assessment = assess_claim_risk(answer, question='What does this note establish?', evidence_text=source)
    assert ('unsupported_diagnostic_certainty' in assessment.reasons) is unsupported


def test_changed_safe_claim_does_not_inherit_another_claims_trigger():
    from agronomy_agent.answer_verifier import AnswerVerificationResult
    draft = 'The shipment mass is 120 kg. You can spray now because it is dry.'
    assessment = assess_claim_risk(draft, question='Read the shipment note.', evidence_text='Mass: 120 kg.')
    record = AnswerVerificationResult(answer='Check the label.', triggered=True, rewrite_accepted=True,
        draft_assessment=assessment, draft_output=draft).as_record()
    ledger = record['claim_edit_ledger']
    assert ledger['schema_version'].endswith('.v2')
    assert ledger['changed_claims'][0]['defect_ids'] == []
    assert ledger['changed_claims'][1]['defect_ids'] == ['verifier_defect::unsupported_regulated_permission']
    assert ledger['all_changed_claims_have_localized_trigger'] is False
    assert ledger['replacement_has_named_defect'] is True  # Answer-level trigger only.
    assert ledger['changed_claims'][1]['evidence_scope'] == 'answer_review_context_not_claim_support'


def test_count_and_mass_of_different_containers_are_not_joined():
    assert unsupported_quantities('The total mass is 300 kg.',
        question='What is the total mass of 12 bags?', evidence='Each box weighs 25 kg.')


@pytest.mark.parametrize('answer', ['20kg/acre', '20 kg/acre', '20 kPa', '20abc'])
def test_unit_suffix_cannot_fall_back_to_supported_bare_magnitude(answer):
    assert unsupported_quantities(answer, question='', evidence='Mass: 20 kg.')


@pytest.mark.parametrize('answer', ['.5 kg/ha', '-.5 cm', '0.5 kg/ha'])
def test_decimal_without_integer_part_is_not_silently_omitted(answer):
    assert unsupported_quantities(answer, question='Read the record.', evidence='')


@pytest.mark.parametrize('unit', ['hectares', 'gallons', 'millilitres'])
def test_mass_is_not_support_for_area_or_volume(unit):
    assert unsupported_quantities(f'20 {unit}', question='Read the record.', evidence='20 kg')


def test_equal_counts_in_distinct_groups_are_not_deduplicated():
    assert unsupported_quantities('The total mass is 300 kg.', question=(
        'What is the total mass of 12 bags of barley and 12 bags of wheat? Each bag weighs 25 kg.'), evidence='')


@pytest.mark.parametrize('source', [
    'There is no evidence that gray leaf spot was ruled out by the laboratory.',
    'Whether gray leaf spot was ruled out by the laboratory is unknown.',
    'Gray leaf spot was ruled out by the laboratory?',
    'Gray leaf spot was ruled out by the laboratory is an unverified claim.',
])
def test_uncertain_exclusion_is_not_an_affirmative_lab_result(source):
    assessment = assess_claim_risk('The diagnosis is not gray leaf spot.',
        question='What does this note establish?', evidence_text=source)
    assert 'unsupported_diagnostic_certainty' in assessment.reasons


def test_derivation_does_not_join_unbound_groups_across_question_and_evidence():
    assert unsupported_quantities('The total mass is 300 kg.',
        question='What is the total mass of 12 bags of barley?',
        evidence='12 bags of wheat weigh 25 kg each.')


@pytest.mark.parametrize('evidence', [
    'Gray leaf spot was ruled out by the laboratory. A later test confirmed gray leaf spot.',
    'Gray leaf spot was ruled out by the laboratory. That exclusion was overturned.',
])
def test_later_contradiction_does_not_license_exclusion(evidence):
    assessment = assess_claim_risk('The diagnosis is not gray leaf spot.',
        question='What does this note establish?', evidence_text=evidence)
    assert 'unsupported_diagnostic_certainty' in assessment.reasons


@pytest.mark.parametrize('quantity', ['twenty', 'twenty-five', 'one hundred and twenty', 'minus twenty'])
def test_spelling_a_quantity_does_not_evade_numeric_review(quantity):
    assessment = assess_claim_risk(f'The shipment mass is {quantity} kg.',
        question='What shipment mass is recorded?', evidence_text='The shipment mass is 120 kg.')
    assert 'unsupported_numeric_specificity' in assessment.reasons


def test_editor_cannot_clear_numeric_defect_by_spelling_unsupported_value():
    from agronomy_agent.answer_verifier import verify_answer
    class Editor:
        def generate(self, _messages):
            return 'The mismatch is that the shipment mass is twenty kg.'
    result = verify_answer('The shipment mass is 20 kg.',
        question='Spot the mismatch in this shipment note and state the source value.',
        evidence_text='The shipment mass is 120 kg.', question_type='conceptual', risk_level='low',
        editor=Editor(), review_mode='risk_conditioned_selective_v3')
    assert not result.rewrite_accepted
    assert result.rewrite_assessment is not None
    assert 'unsupported_numeric_specificity' in result.rewrite_assessment.reasons
    assert 'twenty kg' not in result.answer


@pytest.mark.parametrize(('source', 'answer'), [
    ('The shipment mass is one hundred and twenty kg.', 'The shipment mass is twenty kg.'),
    ('The change is minus twenty kg.', 'The change is twenty kg.'),
    ('The shipment mass is twenty kg.', 'The rate is twenty kg/ha.'),
    ('The shipment mass is twenty kg.', 'The rate is twenty kg per hectare.'),
])
def test_spelled_quantities_match_whole_phrase_sign_and_rate(source, answer):
    assessment = assess_claim_risk(answer, question='Read the record.', evidence_text=source)
    assert 'unsupported_numeric_specificity' in assessment.reasons


def test_exact_spelled_quantity_is_preserved():
    assessment = assess_claim_risk('The shipment mass is one hundred and twenty kg.',
        question='Read the record.', evidence_text='The shipment mass is one hundred and twenty kg.')
    assert not assessment.unsupported_numbers
